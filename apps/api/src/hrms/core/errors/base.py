from typing import Any


class AppError(Exception):
    """Base application error mapped to the Document 09 §1.3 envelope."""

    code: str = "INTERNAL_ERROR"
    status_code: int = 500

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code
        self.message = message
        self.details = details or []


class NotFoundError(AppError):
    code = "NOT_FOUND"
    status_code = 404


class ValidationError(AppError):
    code = "VALIDATION_ERROR"
    status_code = 422


class ConflictError(AppError):
    code = "CONFLICT"
    status_code = 409


class PermissionDeniedError(AppError):
    code = "PERMISSION_DENIED"
    status_code = 403


class LockedError(AppError):
    code = "LOCKED"
    status_code = 423
