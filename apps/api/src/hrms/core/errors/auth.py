from hrms.core.errors.base import AppError


class UnauthorizedError(AppError):
    code = "UNAUTHORIZED"
    status_code = 401


class InvalidCredentialsError(UnauthorizedError):
    code = "INVALID_CREDENTIALS"


class InvalidTokenError(UnauthorizedError):
    code = "INVALID_TOKEN"


class AccountLockedError(AppError):
    code = "ACCOUNT_LOCKED"
    status_code = 423
