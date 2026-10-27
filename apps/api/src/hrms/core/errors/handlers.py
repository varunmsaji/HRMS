from collections.abc import Mapping
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DataError as SqlDataError
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from starlette.exceptions import HTTPException as StarletteHTTPException

from hrms.core.db.timeouts import is_wait_timeout
from hrms.core.errors.base import AppError
from hrms.core.errors.envelope import ErrorBody, ErrorDetail, ErrorEnvelope
from hrms.core.observability.classification import RETRYABLE_DB_CATEGORIES, error_category
from hrms.core.observability.logging import get_logger, safe_error, safe_log
from hrms.core.observability.metrics import ERRORS, HTTP_UNHANDLED, safe_count
from hrms.core.observability.redaction import redact_path
from hrms.core.tenancy.context import current_request_id, verified_tenant_for_logging

_logger = get_logger(__name__)


def note_error_code(scope: Mapping[str, Any], code: str) -> None:
    """Records the envelope's error code on the request scope so the per-request `http_request`
    access event (`RequestContextMiddleware`) can report *which* handled error a 4xx/5xx was,
    without parsing the response body."""
    state = scope.get("state")
    if isinstance(state, dict):
        state["error_code"] = code


def _error_response(
    status_code: int,
    code: str,
    message: str,
    details: list[ErrorDetail] | None = None,
    headers: Mapping[str, str] | None = None,
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
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json"),
        headers=dict(headers) if headers else None,
    )


#: Stable envelope codes for framework-raised `HTTPException`s (unknown route, wrong method,
#: a router-level 4xx). Anything not listed gets a code derived from its class so a client can
#: still branch on it. Domain errors never come through here — they are `AppError`s with their own
#: codes.
_HTTP_STATUS_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    406: "NOT_ACCEPTABLE",
    408: "REQUEST_TIMEOUT",
    409: "CONFLICT",
    410: "GONE",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "UNPROCESSABLE_REQUEST",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    502: "BAD_GATEWAY",
    503: "SERVICE_UNAVAILABLE",
    504: "GATEWAY_TIMEOUT",
}

#: Framework headers worth keeping on an `HTTPException` response; everything else the raiser
#: attached is dropped rather than echoed.
_PASSTHROUGH_HTTP_HEADERS = frozenset({"allow", "www-authenticate", "retry-after"})

#: Pydantic prefixes messages raised by `ValueError` validators with this; it is noise to a user.
_VALUE_ERROR_PREFIX = "Value error, "


def _http_exception_code(status_code: int) -> str:
    if status_code in _HTTP_STATUS_CODES:
        return _HTTP_STATUS_CODES[status_code]
    return "CLIENT_ERROR" if status_code < 500 else "SERVER_ERROR"


def _http_exception_message(status_code: int, detail: object) -> str:
    """`HTTPException.detail` may be any JSON value; only a plain string is safe to show. For a 5xx
    the framework's text is never forwarded (it can name internals)."""
    if status_code >= 500:
        return "An unexpected error occurred"
    if isinstance(detail, str) and detail:
        return detail
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "Request failed"


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


def _is_unique_violation(exc: DBAPIError) -> bool:
    cause = _driver_error(exc)
    return str(getattr(cause, "sqlstate", None) or "") == "23505"


def register_exception_handlers(app: FastAPI) -> None:
    """Register global exception handlers once in app factory (Document 07 §8)."""

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        _log_app_error(request.scope, exc)
        note_error_code(request.scope, exc.code)
        detail_models = [
            ErrorDetail(
                field=str(d.get("field", "")),
                code=str(d.get("code", exc.code)),
                message=str(d.get("message", exc.message)),
                context=d.get("context"),
            )
            for d in exc.details
        ]
        return _error_response(
            exc.status_code, exc.code, exc.message, detail_models, headers=exc.headers
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        note_error_code(request.scope, "REQUEST_VALIDATION_ERROR")
        details = [
            ErrorDetail(
                field=".".join(str(p) for p in err.get("loc", [])),
                code=err.get("type", "validation_error"),
                message=str(err.get("msg", "")).removeprefix(_VALUE_ERROR_PREFIX),
            )
            for err in exc.errors()
        ]
        return _error_response(
            422,
            "REQUEST_VALIDATION_ERROR",
            "Request validation failed",
            details,
        )

    @app.exception_handler(PoolTimeoutError)
    async def pool_timeout_handler(request: Request, exc: PoolTimeoutError) -> JSONResponse:
        """Every pooled connection stayed busy for `pool_timeout`: the request never reached the
        database, so it is safe to retry — the same contract as a lock/statement timeout. Before
        this it fell through to the generic 500 with a traceback per request."""
        _log_db_error(request.scope, exc, status_code=503)
        return _database_busy(request.scope)

    @app.exception_handler(DBAPIError)
    async def db_error_handler(request: Request, exc: DBAPIError) -> JSONResponse:
        """Safety net for the whole class "client value does not fit the column": a 422, not a
        500. Schemas should still bound their fields; this catches whatever they miss. Any other
        database error keeps the generic 500 envelope."""
        if is_wait_timeout(exc) or error_category(exc) in RETRYABLE_DB_CATEGORIES:
            # A lock/statement timeout, a deadlock victim or a serialization failure: Postgres
            # rolled the whole transaction back, so it is safe to retry. A *connection* loss is
            # deliberately not here — the COMMIT may already have landed, so it stays a 500
            # rather than inviting a retry that could apply a mutation twice.
            _log_db_error(request.scope, exc, status_code=503)
            return _database_busy(request.scope)
        if _is_unique_violation(exc):
            # A concurrent request inserted the same natural key between the service's existence
            # check and its INSERT. Services convert the races they anticipate into specific
            # codes; this is the net for the rest — the state conflicts with the request, so 409,
            # not a 500. The constraint name stays in the server log only.
            _log_db_error(request.scope, exc, status_code=409)
            note_error_code(request.scope, "DUPLICATE_RESOURCE")
            return _error_response(
                409,
                "DUPLICATE_RESOURCE",
                "A record with these details already exists",
            )
        if _is_bad_input(exc):
            note_error_code(request.scope, "INVALID_VALUE")
            return _error_response(
                422,
                "INVALID_VALUE",
                "A submitted value is out of range or not storable",
            )
        _log_db_error(request.scope, exc, status_code=500)
        note_error_code(request.scope, "INTERNAL_ERROR")
        return _error_response(500, "INTERNAL_ERROR", "An unexpected error occurred")

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        code = _http_exception_code(exc.status_code)
        note_error_code(request.scope, code)
        if exc.status_code >= 500:
            safe_log(
                _logger.error,
                "http_exception",
                request_id=current_request_id() or "unknown",
                http_method=request.scope.get("method"),
                http_path=route_for_logging(request.scope),
                status_code=exc.status_code,
                **tenant_log_fields(),
            )
        headers = {
            k: v for k, v in (exc.headers or {}).items() if k.lower() in _PASSTHROUGH_HTTP_HEADERS
        }
        return _error_response(
            exc.status_code,
            code,
            _http_exception_message(exc.status_code, exc.detail),
            headers=headers,
        )

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


def _database_busy(scope: Mapping[str, Any]) -> JSONResponse:
    note_error_code(scope, "DATABASE_BUSY")
    response = _error_response(
        503,
        "DATABASE_BUSY",
        "The system is busy right now. Please try again in a moment.",
    )
    response.headers["Retry-After"] = "2"
    return response


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


def tenant_log_fields() -> dict[str, str | None]:
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
    note_error_code(scope, "INTERNAL_ERROR")
    category = error_category(exc)
    safe_count(HTTP_UNHANDLED, category)
    safe_count(ERRORS, "http_unhandled", category)
    safe_log(
        _logger.error,
        "unhandled_exception",
        exc_info=None if response_started else exc,
        request_id=current_request_id() or "unknown",
        http_method=scope.get("method"),
        http_path=route_for_logging(scope),
        # LOG-08 — no `str(exc)` field: the message is already inside the traceback, which goes
        # through the redaction processor; a separate copy would bypass nothing but add bulk.
        **safe_error(exc),
        response_started=response_started,
        **tenant_log_fields(),
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
    safe_count(ERRORS, "http_app_error", error_category(exc.__cause__ or exc))
    fields: dict[str, Any] = {
        "request_id": current_request_id() or "unknown",
        "http_method": scope.get("method"),
        "http_path": route_for_logging(scope),
        "status_code": exc.status_code,
        "error_code": exc.code,
        "exception_type": type(exc).__name__,
        "cause_type": type(exc.__cause__).__name__ if exc.__cause__ is not None else None,
        **tenant_log_fields(),
    }
    if exc.status_code == 500:
        safe_log(_logger.error, "app_error", exc_info=exc, **fields)
    else:
        safe_log(_logger.warning, "app_error", **fields)


def _log_db_error(
    scope: Mapping[str, Any], exc: DBAPIError | PoolTimeoutError, *, status_code: int
) -> None:
    """LOG-02 — database failures that become a 5xx. Never `str(exc)` as a field: the engine runs
    with `hide_parameters=True` (`core/db/session.py`), so the traceback's SQL text carries no
    bound values, but the statement itself is still only rendered inside the traceback."""
    driver = _driver_error(exc) if isinstance(exc, DBAPIError) else None
    category = error_category(exc)
    safe_count(ERRORS, "http_db_error", category)
    fields: dict[str, Any] = {
        "request_id": current_request_id() or "unknown",
        "http_method": scope.get("method"),
        "http_path": route_for_logging(scope),
        "status_code": status_code,
        "exception_type": type(exc).__name__,
        "driver_error": type(driver).__name__ if driver is not None else None,
        "sqlstate": getattr(driver, "sqlstate", None),
        "error_category": category,
        **tenant_log_fields(),
    }
    if status_code == 409:
        # An unanticipated duplicate means a service lacks its specific conversion: the client gets
        # a 409, but the traceback (values masked by the redaction processor) is kept so the gap
        # can be found. WARNING, not ERROR — the request itself was handled correctly.
        safe_log(_logger.warning, "db_error", exc_info=exc, **fields)
    elif status_code == 503:
        # Transient and retryable: one compact WARNING per request, no traceback. The event
        # name stays `db_wait_timeout` for lock/statement timeouts (existing alert queries).
        event = "db_wait_timeout" if category == "db_timeout" else category
        safe_log(_logger.warning, event, **fields)
    else:
        safe_log(_logger.error, "db_error", exc_info=exc, **fields)


def server_meta() -> dict[str, str]:
    return {"server_time": datetime.now(UTC).isoformat().replace("+00:00", "Z")}
