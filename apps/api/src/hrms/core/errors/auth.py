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


class EmailNotVerifiedError(AppError):
    """SEC-09 (RELEASE_HARDENING_PHASE_3A) — raised by `IdentityService.login` when the
    password check already succeeded but `User.email_verified_at` is still `NULL`. 403, not 401:
    the credentials themselves are correct, so this is a distinct, resend-actionable state, not
    an authentication failure."""

    code = "EMAIL_NOT_VERIFIED"
    status_code = 403
