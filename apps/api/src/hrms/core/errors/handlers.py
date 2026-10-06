from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DataError as SqlDataError
from sqlalchemy.exc import DBAPIError
from starlette.exceptions import HTTPException as StarletteHTTPException

from hrms.core.db.timeouts import is_wait_timeout
from hrms.core.errors.base import AppError
from hrms.core.errors.envelope import ErrorBody, ErrorDetail, ErrorEnvelope
from hrms.core.observability.logging import get_logger
from hrms.core.tenancy.context import current_request_id, current_tenant

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
    async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
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
    async def db_error_handler(_request: Request, exc: DBAPIError) -> JSONResponse:
        """Safety net for the whole class "client value does not fit the column": a 422, not a
        500. Schemas should still bound their fields; this catches whatever they miss. Any other
        database error keeps the generic 500 envelope."""
        if is_wait_timeout(exc):
            # A lock or statement timeout: the work was rolled back cleanly and is safe to retry.
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
        # FINDING-01 — every unhandled exception must leave a server-side trace before the
        # client-facing envelope is built; a Sentry/error-tracker hook can be layered on top of
        # this log call later (Document 13 §3) without changing the response contract.
        try:
            tenant = current_tenant()
            company_id: str | None = str(tenant.company_id)
            user_id: str | None = str(tenant.user_id) if tenant.user_id else None
        except RuntimeError:
            company_id = None
            user_id = None
        _logger.exception(
            "unhandled_exception",
            request_id=current_request_id() or "unknown",
            http_method=request.method,
            http_path=request.url.path,
            company_id=company_id,
            user_id=user_id,
            exception_type=type(exc).__name__,
            exception_message=str(exc),
        )
        return _error_response(500, "INTERNAL_ERROR", "An unexpected error occurred")


def server_meta() -> dict[str, str]:
    return {"server_time": datetime.now(UTC).isoformat().replace("+00:00", "Z")}
