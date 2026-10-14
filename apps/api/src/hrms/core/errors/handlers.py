from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DataError as SqlDataError
from sqlalchemy.exc import DBAPIError
from starlette.exceptions import HTTPException as StarletteHTTPException

from hrms.core.db.timeouts import is_wait_timeout
from hrms.core.errors.base import AppError
from hrms.core.errors.envelope import ErrorBody, ErrorDetail, ErrorEnvelope
from hrms.core.observability.logging import get_logger, safe_log
from hrms.core.observability.redaction import redact_path
from hrms.core.tenancy.context import current_request_id, verified_tenant_for_logging

_logger = get_logger(__name__)


def _error_response(
    status_code: int,
    code: str,
    message: str,
    details: list[ErrorDetail] | None = None,
) -> JSONResponse:
    request_id = current_request_id() or "unknown"
    body = ErrorEnvelope(
        error=ErrorBody(
            code=code,
            message=message,
            details=details or [],
            request_id=request_id,
        )
    )
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


#: asyncpg exception class names for "the value you sent cannot be stored" — raised client-side
#: (`DataError`, e.g. an int beyond int64) or by Postgres (SQLSTATE class 22: numeric out of range,
#: invalid text representation, string truncation, NUL bytes...). Always the caller's input.
_BAD_INPUT_DRIVER_ERRORS = {
    "DataError",
    "InvalidTextRepresentationError",
    "NumericValueOutOfRangeError",
    "StringDataRightTruncationError",
    "DatetimeFieldOverflowError",
    "InvalidDatetimeFormatError",
    "CharacterNotInRepertoireError",
}


def _is_bad_input(exc: DBAPIError) -> bool:
    if isinstance(exc, SqlDataError):
        return True
    cause = getattr(exc.orig, "__cause__", None) or exc.orig
    if type(cause).__name__ in _BAD_INPUT_DRIVER_ERRORS:
        return True
    return str(getattr(cause, "sqlstate", None) or "").startswith("22")


def register_exception_handlers(app: FastAPI) -> None:
    """Register global exception handlers once in app factory (Document 07 §8)."""

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        _log_app_error(request.scope, exc)
        detail_models = [
            ErrorDetail(
                field=str(d.get("field", "")),
                code=str(d.get("code", exc.code)),
                message=str(d.get("message", exc.message)),
                context=d.get("context"),
            )
            for d in exc.details
        ]
        return _error_response(exc.status_code, exc.code, exc.message, detail_models)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        details = [
            ErrorDetail(
                field=".".join(str(p) for p in err.get("loc", [])),
                code=err.get("type", "validation_error"),
                message=err.get("msg", ""),
            )
            for err in exc.errors()
        ]
        return _error_response(
            422,
            "REQUEST_VALIDATION_ERROR",
            "Request validation failed",
            details,
        )

    @app.exception_handler(DBAPIError)
    async def db_error_handler(request: Request, exc: DBAPIError) -> JSONResponse:
        """Safety net for the whole class "client value does not fit the column": a 422, not a
        500. Schemas should still bound their fields; this catches whatever they miss. Any other
        database error keeps the generic 500 envelope."""
        if is_wait_timeout(exc):
            # A lock or statement timeout: the work was rolled back cleanly and is safe to retry.
            _log_db_error(request.scope, exc, status_code=503)
            response = _error_response(
                503,
                "DATABASE_BUSY",
                "The system is busy right now. Please try again in a moment.",
            )
            response.headers["Retry-After"] = "2"
            return response
        if _is_bad_input(exc):
            return _error_response(
                422,
                "INVALID_VALUE",
                "A submitted value is out of range or not storable",
            )
        _log_db_error(request.scope, exc, status_code=500)
        return _error_response(500, "INTERNAL_ERROR", "An unexpected error occurred")

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        _request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        return _error_response(exc.status_code, "HTTP_ERROR", str(exc.detail))

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        # Fallback only. In `create_app()`, `RequestContextMiddleware` catches every exception
        # that escapes the stack before Starlette's ServerErrorMiddleware (where this handler
        # lives) ever sees it — see that module for why. Kept so an app built without that
        # middleware (focused tests) still logs and answers with the standard envelope.
        log_unhandled_exception(request.scope, exc, response_started=False)
        return unhandled_error_response()


def route_for_logging(scope: Mapping[str, Any]) -> str:
    """The matched route's template (`/v1/public/onboarding/{token}`) — never the raw path,
    which can carry identifiers or bearer tokens (LOG-04). Falls back to the redacted raw path
    when no route matched (404s, middleware-level failures)."""
    raw_path = str(scope.get("path", ""))
    template = getattr(scope.get("route"), "path", None)
    if isinstance(template, str) and ":path}" not in template:
        # FastAPI nests included routers, so `route.path` lacks the include prefix ("/v1"). The
        # raw path has the same number of segments after that prefix as the template, so the
        # leading remainder of the raw path is the (static) prefix.
        tail_segments = template.count("/")
        parts = raw_path.split("/")
        if len(parts) > tail_segments:
            prefix = "/".join(parts[: len(parts) - tail_segments])
            return redact_path(prefix) + template
    return redact_path(raw_path)


def _tenant_fields() -> dict[str, str | None]:
    tenant = verified_tenant_for_logging()
    if tenant is None:
        return {"company_id": None, "user_id": None}
    return {
        "company_id": str(tenant.company_id),
        "user_id": str(tenant.user_id) if tenant.user_id else None,
    }


def log_unhandled_exception(
    scope: Mapping[str, Any], exc: BaseException, *, response_started: bool
) -> None:
    """FINDING-01 / LOG-01 — exactly one server-side record per unhandled exception, with the
    traceback (server-side only; the client gets the generic envelope). When the response had
    already started, the exception is re-raised to the server, which prints its own traceback,
    so this record omits it to avoid logging the same traceback twice."""
    safe_log(
        _logger.error,
        "unhandled_exception",
        exc_info=None if response_started else exc,
        request_id=current_request_id() or "unknown",
        http_method=scope.get("method"),
        http_path=route_for_logging(scope),
        exception_type=type(exc).__name__,
        exception_message=str(exc),
        response_started=response_started,
        **_tenant_fields(),
    )


def unhandled_error_response() -> JSONResponse:
    return _error_response(500, "INTERNAL_ERROR", "An unexpected error occurred")


def _driver_error(exc: DBAPIError) -> BaseException | None:
    return getattr(exc.orig, "__cause__", None) or exc.orig


def _log_app_error(scope: Mapping[str, Any], exc: AppError) -> None:
    """LOG-02 — a 5xx `AppError` is a server-side failure (Redis down behind the rate limiter, an
    unavailable or failing encryption key, a provider outage) and must leave a record; a 4xx is
    an expected business/client outcome and does not. A 500 is unexpected, so it carries the
    traceback; a 502/503/504 is a dependency being unavailable, logged with the cause's type only
    so an outage produces one compact line per request, not a traceback per request."""
    if exc.status_code < 500:
        return
    fields: dict[str, Any] = {
        "request_id": current_request_id() or "unknown",
        "http_method": scope.get("method"),
        "http_path": route_for_logging(scope),
        "status_code": exc.status_code,
        "error_code": exc.code,
        "exception_type": type(exc).__name__,
        "cause_type": type(exc.__cause__).__name__ if exc.__cause__ is not None else None,
        **_tenant_fields(),
    }
    if exc.status_code == 500:
        safe_log(_logger.error, "app_error", exc_info=exc, **fields)
    else:
        safe_log(_logger.warning, "app_error", **fields)


def _log_db_error(scope: Mapping[str, Any], exc: DBAPIError, *, status_code: int) -> None:
    """LOG-02 — database failures that become a 5xx. Never `str(exc)` as a field: the engine runs
    with `hide_parameters=True` (`core/db/session.py`), so the traceback's SQL text carries no
    bound values, but the statement itself is still only rendered inside the traceback."""
    driver = _driver_error(exc)
    fields: dict[str, Any] = {
        "request_id": current_request_id() or "unknown",
        "http_method": scope.get("method"),
        "http_path": route_for_logging(scope),
        "status_code": status_code,
        "exception_type": type(exc).__name__,
        "driver_error": type(driver).__name__ if driver is not None else None,
        "sqlstate": getattr(driver, "sqlstate", None),
        **_tenant_fields(),
    }
    if status_code == 503:
        safe_log(_logger.warning, "db_wait_timeout", **fields)
    else:
        safe_log(_logger.error, "db_error", exc_info=exc, **fields)


def server_meta() -> dict[str, str]:
    return {"server_time": datetime.now(UTC).isoformat().replace("+00:00", "Z")}
