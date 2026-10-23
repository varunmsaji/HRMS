"""Operation-level logging for service methods: one compact line per important business
operation, with its outcome and duration.

```python
@logged_operation("payroll.pay_run.finalise")
async def finalise(self, company_id, run_id, *, actor_user_id, ...): ...
```

What it records, and what it deliberately does not:

* `operation`, `outcome`, `duration_ms`, plus the UUID-typed arguments from a fixed allow-list of
  names (`company_id`, `employee_id`, `run_id`, ...) and a few short scalar arguments
  (`direction`, `as_of`, ...). Nothing else from the arguments — request bodies, filenames,
  document bytes, amounts — is ever read.
* `outcome="succeeded"` (INFO). The service method returned; whether the surrounding transaction
  committed is confirmed separately by `business.audit_recorded`, which is emitted only after
  commit.
* `outcome="rejected"` for an `AppError` below 500 — an expected business or authorization
  outcome (validation, conflict, permission). INFO, except 403/409 which are WARNING because they
  are the ones worth noticing in aggregate. Carries the stable `error_code`.
* `outcome="failed"` for a 5xx `AppError` or any other exception (ERROR). The event carries the
  safe error description only — **no traceback**. The traceback is logged exactly once, by the
  layer that finally handles the exception (the request middleware, or Celery), so a failure is
  never recorded with a stack trace at every layer. The exception is always re-raised unchanged.
* A logging failure never alters the operation's result (`safe_log`).
"""

from __future__ import annotations

import functools
import inspect
import time
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any, ParamSpec, TypeVar
from uuid import UUID

from hrms.core.errors.base import AppError
from hrms.core.observability.logging import get_logger, safe_error, safe_log

P = ParamSpec("P")
R = TypeVar("R")

_ID_ARGUMENTS = frozenset(
    {
        "company_id",
        "employee_id",
        "actor_user_id",
        "caller_employee_id",
        "user_id",
        "run_id",
        "pay_run_id",
        "period_id",
        "application_id",
        "leave_application_id",
        "request_id",
        "document_id",
        "case_id",
        "batch_id",
        "policy_id",
        "target_user_id",
    }
)
_SHORT_SCALAR_ARGUMENTS = frozenset(
    {"direction", "source", "document_type", "as_of", "target_date", "expected_version"}
)
_MAX_SCALAR_CHARS = 40
_WARNING_STATUSES = frozenset({403, 409})


def _context(bound: dict[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for name, value in bound.items():
        if name in _ID_ARGUMENTS and isinstance(value, UUID):
            # `request_id` here is a domain object id (a regularization request), never the HTTP
            # correlation id, which the log context carries itself.
            fields["domain_request_id" if name == "request_id" else name] = str(value)
        elif name in _SHORT_SCALAR_ARGUMENTS:
            if isinstance(value, date) or isinstance(value, (int, bool)):
                fields[name] = value.isoformat() if isinstance(value, date) else value
            elif isinstance(value, str) and len(value) <= _MAX_SCALAR_CHARS:
                fields[name] = value
    return fields


def log_operation_outcome(
    logger_name: str,
    operation: str,
    *,
    started: float,
    exc: BaseException | None,
    **fields: Any,
) -> None:
    """Emits the outcome line. Public so non-decorator call sites (task bodies, loops) share the
    exact same schema and severity rules."""
    logger = get_logger(logger_name)
    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    if exc is None:
        safe_log(
            logger.info,
            operation,
            outcome="succeeded",
            duration_ms=duration_ms,
            **fields,
        )
    elif isinstance(exc, AppError) and exc.status_code < 500:
        method = logger.warning if exc.status_code in _WARNING_STATUSES else logger.info
        safe_log(
            method,
            operation,
            outcome="rejected",
            duration_ms=duration_ms,
            error_code=exc.code,
            status_code=exc.status_code,
            **fields,
        )
    else:
        safe_log(
            logger.error,
            operation,
            outcome="failed",
            duration_ms=duration_ms,
            **fields,
            **safe_error(exc),
        )


def logged_operation(
    operation: str,
    *,
    logger_name: str | None = None,
    result_fields: Callable[[Any], dict[str, Any]] | None = None,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Decorator for `async` service methods. `logger_name` defaults to the decorated function's
    module, which is what routes the line to that module's log file. `result_fields` may map the
    return value to extra *identifier or fixed-code* fields (never business data)."""

    def decorate(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        signature = inspect.signature(func)
        target_logger = logger_name or func.__module__

        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            started = time.perf_counter()
            try:
                bound = signature.bind_partial(*args, **kwargs).arguments
                fields = _context(bound)
            except Exception:  # noqa: BLE001 — context extraction must never fail the call
                fields = {}
            try:
                result = await func(*args, **kwargs)
            except BaseException as exc:
                if isinstance(exc, Exception):
                    log_operation_outcome(
                        target_logger, operation, started=started, exc=exc, **fields
                    )
                raise
            extra: dict[str, Any] = {}
            if result_fields is not None:
                try:
                    extra = result_fields(result)
                except Exception:  # noqa: BLE001
                    extra = {}
            log_operation_outcome(
                target_logger, operation, started=started, exc=None, **fields, **extra
            )
            return result

        return wrapper

    return decorate
