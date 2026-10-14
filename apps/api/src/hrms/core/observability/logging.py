import logging
import sys
from collections.abc import Callable
from typing import Any

import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

from hrms.core.config.settings import get_settings
from hrms.core.observability.redaction import AccessLogPathRedactionFilter

#: Marks the root handler `configure_logging(configure_stdlib=True)` installs, so a repeated call
#: (Celery may signal more than once per process) replaces it instead of stacking duplicates.
_STDLIB_HANDLER_NAME = "hrms-json"


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
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # LOG-04 — idempotent: `logging.Filterer.addFilter` ignores a filter already present, and the
    # isinstance check keeps a second instance from being added on a repeated call.
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, AccessLogPathRedactionFilter) for f in access.filters):
        access.addFilter(AccessLogPathRedactionFilter())

    if configure_stdlib:
        handler = logging.StreamHandler(sys.stdout)
        handler.set_name(_STDLIB_HANDLER_NAME)
        handler.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                foreign_pre_chain=[structlog.stdlib.add_logger_name, *shared],
                processors=[
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    structlog.processors.format_exc_info,
                    structlog.processors.JSONRenderer(),
                ],
            )
        )
        root = logging.getLogger()
        for existing in list(root.handlers):
            root.removeHandler(existing)
        root.addHandler(handler)
        root.setLevel(level)


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
