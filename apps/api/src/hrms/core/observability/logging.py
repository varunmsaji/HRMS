import json
import logging
import sys
from collections.abc import Callable
from typing import Any

import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

from hrms.core.config.settings import get_settings
from hrms.core.observability.classification import error_category
from hrms.core.observability.redaction import AccessLogPathRedactionFilter, redact_event

#: Marks the root handler `configure_logging(configure_stdlib=True)` installs, so a repeated call
#: (Celery may signal more than once per process) replaces it instead of stacking duplicates.
_STDLIB_HANDLER_NAME = "hrms-json"


class _ResilientStdout:
    """The stream every log line is written to. Two properties a plain `sys.stdout` reference
    lacks:

    * it resolves `sys.stdout` at *write* time, so a logger configured while stdout was
      temporarily swapped (test capture, a supervisor reopening the stream) never keeps writing
      to a stale, closed file object;
    * a failed write (closed or broken pipe, full disk on a redirected stdout) is dropped and
      counted instead of raised. A log call must never turn into a business failure — before
      this, a `ValueError: I/O operation on closed file` from a `_logger.warning(...)` inside a
      fan-out loop aborted the loop — and it must not recurse into more logging (no "logging
      error" tracebacks on stderr), which would turn a sink outage into a log storm.
    """

    dropped_writes = 0
    reported_drops = 0

    def write(self, text: str) -> int:
        try:
            written = sys.stdout.write(text)
        except (OSError, ValueError):
            type(self).dropped_writes += 1
            return 0
        if text.endswith("\n") and self.dropped_writes > self.reported_drops:
            self._report_drops()
        return written

    def _report_drops(self) -> None:
        """The sink works again after losing lines: say so, in-band, once per outage. This is
        the only signal that lines are missing (the host monitor alerts on it), because while the
        sink was down nothing could be logged about it."""
        cls = type(self)
        total, newly = cls.dropped_writes, cls.dropped_writes - cls.reported_drops
        try:
            sys.stdout.write(
                json.dumps(
                    {
                        "event": "log_writes_dropped",
                        "level": "error",
                        "newly_dropped": newly,
                        "dropped_total": total,
                    }
                )
                + "\n"
            )
        except (OSError, ValueError):
            return  # still broken: try again on the next successful write
        cls.reported_drops = total

    def flush(self) -> None:
        try:
            sys.stdout.flush()
        except (OSError, ValueError):
            type(self).dropped_writes += 1


_STDOUT = _ResilientStdout()


def dropped_log_writes() -> int:
    """Log lines lost because stdout was unwritable since process start."""
    return _ResilientStdout.dropped_writes


def _static_fields(service: str, environment: str) -> Processor:
    def add(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
        event_dict.setdefault("service", service)
        event_dict.setdefault("environment", environment)
        return event_dict

    return add


def configure_logging(service: str = "api", *, configure_stdlib: bool = False) -> None:
    """One JSON-lines logging contract for every process (API, worker, beat).

    `configure_stdlib=True` (worker/beat — LOG-03) additionally routes the standard-library
    `logging` tree (Celery's own task/worker records, kombu, httpx...) through the same JSON
    renderer via a single root handler. The API leaves stdlib logging alone: under gunicorn the
    `uvicorn.*`/`gunicorn.*` loggers have their own handlers, and adding a root handler there
    would duplicate their lines."""
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        _static_fields(service, settings.environment),
    ]
    structlog.configure(
        processors=[
            *shared,
            # FINDING-01 — renders `exc_info` (set by `.exception()`/`exc_info=...`) into a
            # formatted traceback string; without this the JSON line only carries a boolean flag.
            structlog.processors.format_exc_info,
            # LOG-08 — after `format_exc_info`, so the rendered traceback is masked too.
            redact_event,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=_STDOUT),  # type: ignore[arg-type]
        cache_logger_on_first_use=True,
    )

    # LOG-04 — idempotent: `logging.Filterer.addFilter` ignores a filter already present, and the
    # isinstance check keeps a second instance from being added on a repeated call.
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, AccessLogPathRedactionFilter) for f in access.filters):
        access.addFilter(AccessLogPathRedactionFilter())

    if configure_stdlib:
        handler = logging.StreamHandler(_STDOUT)
        handler.set_name(_STDLIB_HANDLER_NAME)
        handler.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                foreign_pre_chain=[structlog.stdlib.add_logger_name, *shared],
                processors=[
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    structlog.processors.format_exc_info,
                    redact_event,
                    structlog.processors.JSONRenderer(),
                ],
            )
        )
        root = logging.getLogger()
        for existing in list(root.handlers):
            root.removeHandler(existing)
        root.addHandler(handler)
        root.setLevel(level)


def safe_error(exc: BaseException) -> dict[str, Any]:
    """LOG-08 — the structured, non-sensitive description of an exception for a log field:
    its type plus, where present, the stable application error code, the database SQLSTATE
    and driver class, and the type of its cause. Never `str(exc)`: exception text can carry
    user input, SQL, provider responses or constraint values (`Key (email)=(...)`). When the
    full message is needed for diagnosis, log the exception itself via `exc_info`, which goes
    through the redaction processor."""
    fields: dict[str, Any] = {
        "exception_type": type(exc).__name__,
        "error_category": error_category(exc),
    }
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code.isupper():
        fields["error_code"] = code
    orig = getattr(exc, "orig", None)  # SQLAlchemy DBAPIError
    if orig is not None:
        driver = getattr(orig, "__cause__", None) or orig
        fields["driver_error"] = type(driver).__name__
        sqlstate = getattr(driver, "sqlstate", None)
        if isinstance(sqlstate, str):
            fields["sqlstate"] = sqlstate
    if exc.__cause__ is not None:
        fields["cause_type"] = type(exc.__cause__).__name__
    return fields


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]


def safe_log(log_method: Callable[..., Any], event: str, **fields: Any) -> None:
    """Emits a log event, swallowing any failure of the logging pipeline itself (a closed stdout,
    a field that cannot be serialized). Used on error paths and right after security-relevant
    commits, where a logging failure must never replace the intended response or undo/obscure a
    business outcome that has already happened."""
    try:
        log_method(event, **fields)
    except Exception:  # noqa: BLE001 — logging must never break the caller
        pass
