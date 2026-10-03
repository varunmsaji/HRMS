"""Module-specific AppError subclasses for the account-invite module — defined locally, following
the same per-module-owns-its-own-error-shapes convention `onboarding/exceptions.py` states."""

from hrms.core.errors.base import ConflictError, NotFoundError, ValidationError


class AccountInviteInvalidError(NotFoundError):
    """Raised for any token that doesn't resolve to a live, acceptable invite — unknown hash,
    revoked, expired, or already accepted. Deliberately a `404` for every failure mode, identical
    reasoning to `OnboardingTokenInvalidError`: a public surface must never let a response
    distinguish "never existed" from "existed but is no longer valid"."""

    code = "NOT_FOUND"

    def __init__(self, message: str = "Resource not found") -> None:
        super().__init__(message)


class EmployeeAlreadyHasAccountError(ConflictError):
    code = "EMPLOYEE_ALREADY_HAS_ACCOUNT"

    def __init__(self, message: str = "This employee already has a login account") -> None:
        super().__init__(
            message, details=[{"field": "employee_id", "code": self.code, "message": message}]
        )


class EmployeeMissingEmailError(ValidationError):
    code = "EMPLOYEE_MISSING_EMAIL"

    def __init__(
        self, message: str = "This employee has no personal email on file to invite"
    ) -> None:
        super().__init__(
            message, details=[{"field": "personal_email", "code": self.code, "message": message}]
        )


class InvalidRoleCodeError(ValidationError):
    code = "INVALID_ROLE_CODE"

    def __init__(self, role_code: str) -> None:
        message = f"{role_code} is not a valid role"
        super().__init__(
            message, details=[{"field": "role_code", "code": self.code, "message": message}]
        )


class SelfRoleChangeNotAllowedError(ConflictError):
    """Deliberate Phase 2 scope limit — a full "is this the last COMPANY_ADMIN?" check is not
    built (`docs/modules/employee/41_EMPLOYEE_ACCOUNT_PROVISIONING_LOGIN_AUDIT_AND_PLAN.md` Phase
    2 does not scope it in). Blocking any self-role-change entirely is the simplest guard that
    can't lock an admin out of their own company by mistake; a narrower "last admin" check can
    replace this later without changing the endpoint's contract."""

    code = "SELF_ROLE_CHANGE_NOT_ALLOWED"

    def __init__(self, message: str = "You cannot change your own role assignment") -> None:
        super().__init__(
            message, details=[{"field": "user_id", "code": self.code, "message": message}]
        )


class UserAlreadyInCompanyError(ConflictError):
    code = "USER_ALREADY_IN_COMPANY"

    def __init__(self, message: str = "This email already has an account in this company") -> None:
        super().__init__(
            message, details=[{"field": "email", "code": self.code, "message": message}]
        )


class RoleRequiredError(ValidationError):
    """`PATCH /users/{id}/roles` with an empty list — a member with no role is an active account
    that can do nothing and shows up in no "who is an admin" view. Dropping access entirely is a
    deactivation decision, not a side-effect of an empty array."""

    code = "ROLE_REQUIRED"

    def __init__(self, message: str = "A user must have at least one role") -> None:
        super().__init__(
            message, details=[{"field": "role_codes", "code": self.code, "message": message}]
        )


class AccountCreationConflictError(ConflictError):
    """Two invites for the same not-yet-registered email were accepted at the same instant; the
    loser hit the global unique index on `user.email`. Retrying resolves it (the account now
    exists, so the retry takes the existing-account path)."""

    code = "ACCOUNT_CREATION_CONFLICT"

    def __init__(
        self, message: str = "Account setup collided with another request — retry"
    ) -> None:
        super().__init__(
            message, details=[{"field": "email", "code": self.code, "message": message}]
        )
