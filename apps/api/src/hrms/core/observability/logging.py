import json
import logging
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

from hrms.core.config.settings import get_settings
from hrms.core.observability.classification import error_category
from hrms.core.observability.file_sink import (
    FileLoggingConfig,
    current_sink,
    install_file_sink,
    uninstall_file_sink,
)
from hrms.core.observability.metrics import LOG_DROPPED, LOG_EVENTS, safe_count
from hrms.core.observability.redaction import AccessLogPathRedactionFilter, redact_event

#: Marks the root handler `configure_logging(configure_stdlib=True)` installs, so a repeated call
#: (Celery may signal more than once per process) replaces it instead of stacking duplicates.
_STDLIB_HANDLER_NAME = "hrms-json"

#: `apps/api` (`/app` in the image) — the anchor for a relative `LOG_DIR`.
API_ROOT = Path(__file__).resolve().parents[4]


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
            safe_count(LOG_DROPPED, "stdout")
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


class _NamedPrintLogger(structlog.PrintLogger):
    """`PrintLogger` that remembers the name it was created with, so the `logger` field (and with
    it the per-module file routing) works for native structlog loggers, not just stdlib ones."""

    def __init__(self, file: Any = None, name: str | None = None) -> None:
        super().__init__(file)
        self.name = name


class _NamedPrintLoggerFactory:
    def __init__(self, file: Any) -> None:
        self._file = file

    def __call__(self, *args: Any) -> _NamedPrintLogger:
        return _NamedPrintLogger(self._file, str(args[0]) if args else None)


def _add_logger_name(logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
    name = getattr(logger, "name", None)
    if name:
        event_dict.setdefault("logger", name)
    return event_dict


_LOG_LEVELS = frozenset({"debug", "info", "warning", "error", "critical"})


def _level_label(level: object) -> str:
    text = str(level).lower()
    return "error" if text == "exception" else (text if text in _LOG_LEVELS else "other")


def _render_and_route(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> str:
    """Last processor of every pipeline: renders the (already redacted) event to its JSON line,
    hands the same event to the local file sink, and returns the line for stdout."""
    safe_count(LOG_EVENTS, _level_label(event_dict.get("level")))
    renderer = structlog.processors.JSONRenderer()
    sink = current_sink()
    if sink is not None:
        sink.emit(event_dict, lambda e: str(renderer(_logger, _method, dict(e))))
    return str(renderer(_logger, _method, event_dict))


def resolve_log_dir(raw: str) -> Path:
    path = Path(raw).expanduser()
    return path if path.is_absolute() else API_ROOT / path


def _configure_file_sink() -> None:
    settings = get_settings()
    if not settings.log_to_files:
        uninstall_file_sink()
        return
    install_file_sink(
        FileLoggingConfig(
            directory=resolve_log_dir(settings.log_dir),
            max_bytes=settings.log_file_max_bytes,
            backup_count=settings.log_file_backup_count,
            retention_days=settings.log_retention_days,
        ),
        required=settings.log_files_required,
    )


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

    _configure_file_sink()

    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        _add_logger_name,
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
            _render_and_route,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=_NamedPrintLoggerFactory(_STDOUT),
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
                    _render_and_route,
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
