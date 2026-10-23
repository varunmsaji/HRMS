from hrms.core.errors.base import AppError, ConflictError, NotFoundError, ValidationError


class CompanyNotFoundError(NotFoundError):
    code = "COMPANY_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("Company not found")


class InvalidCompanyTransitionError(ConflictError):
    """The company is not in a status this action applies to (or changed while the request ran)."""

    code = "INVALID_COMPANY_TRANSITION"

    def __init__(self, action: str, current_status: str) -> None:
        super().__init__(
            f"Cannot {action} a company that is {current_status}",
            details=[
                {"field": "status", "code": self.code, "message": f"Current: {current_status}"}
            ],
        )


class ConfirmationMismatchError(ValidationError):
    code = "CONFIRMATION_MISMATCH"

    def __init__(self) -> None:
        super().__init__(
            "The confirmation name does not match the company name",
            details=[
                {
                    "field": "confirm_name",
                    "code": self.code,
                    "message": "Type the company name exactly to confirm",
                }
            ],
        )


class PlanNotFoundError(ValidationError):
    code = "PLAN_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__(
            "Unknown plan",
            details=[{"field": "plan_code", "code": self.code, "message": "No such active plan"}],
        )


class NoSubscriptionError(ConflictError):
    code = "NO_SUBSCRIPTION"

    def __init__(self) -> None:
        super().__init__("This company has no subscription to change")


class PlatformAdminLockedError(AppError):
    code = "ACCOUNT_LOCKED"
    status_code = 423

    def __init__(self) -> None:
        super().__init__("Account is temporarily locked")


class PlatformAdminNotFoundError(NotFoundError):
    code = "PLATFORM_ADMIN_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("Platform admin not found")


class PlatformUsernameTakenError(ConflictError):
    code = "USERNAME_TAKEN"

    def __init__(self) -> None:
        super().__init__(
            "That username is already in use",
            details=[{"field": "username", "code": self.code, "message": "Already in use"}],
        )


class WeakPlatformPasswordError(ValidationError):
    code = "WEAK_PASSWORD"

    def __init__(self) -> None:
        super().__init__(
            "Password does not meet minimum strength requirements",
            details=[
                {
                    "field": "password",
                    "code": self.code,
                    "message": "Use at least 8 characters with a letter and a digit, "
                    "and avoid common passwords",
                }
            ],
        )


class CannotRemoveLastAdminError(ConflictError):
    """Disabling yourself, or the last active platform admin, would lock everyone out."""

    code = "CANNOT_DISABLE_ADMIN"

    def __init__(self, message: str) -> None:
        super().__init__(message)


class AdminAlreadyVerifiedError(ConflictError):
    code = "ADMIN_ALREADY_VERIFIED"

    def __init__(self) -> None:
        super().__init__("This admin's email address is already verified")
