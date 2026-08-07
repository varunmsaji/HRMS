from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from hrms.core.errors.base import AppError
from hrms.core.errors.envelope import ErrorBody, ErrorDetail, ErrorEnvelope
from hrms.core.tenancy.context import current_request_id


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

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        _request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        return _error_response(exc.status_code, "HTTP_ERROR", str(exc.detail))

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        _request: Request,
        exc: Exception,
    ) -> JSONResponse:
        # Sentry hook lands here in a later sprint (Document 13 §3).
        _ = exc
        return _error_response(500, "INTERNAL_ERROR", "An unexpected error occurred")


def server_meta() -> dict[str, str]:
    return {"server_time": datetime.now(UTC).isoformat().replace("+00:00", "Z")}
