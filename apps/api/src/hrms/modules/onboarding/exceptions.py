"""Module-specific AppError subclasses for the onboarding module — defined locally rather than
reused from `employee/exceptions.py`, following that module's own stated convention (each module
owns its own error shapes)."""

from hrms.core.errors.base import ConflictError, ValidationError


class DuplicateActiveOnboardingCaseError(ConflictError):
    """Raised when HR tries to start a new case for a `personal_email` that already has a
    non-terminal case in this company (plan §13 Q5, recommended default: block while an active
    case exists)."""

    code = "DUPLICATE_ACTIVE_ONBOARDING_CASE"

    def __init__(
        self,
        message: str = (
            "An active onboarding case already exists for this personal email"
        ),
    ) -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "personal_email",
                    "code": "DUPLICATE_ACTIVE_ONBOARDING_CASE",
                    "message": message,
                }
            ],
        )


class InvalidDesignationReferenceError(ValidationError):
    code = "INVALID_DESIGNATION"

    def __init__(
        self, message: str = "designation_id does not reference a valid designation"
    ) -> None:
        super().__init__(
            message,
            details=[
                {"field": "designation_id", "code": "INVALID_DESIGNATION", "message": message}
            ],
        )


class InvalidDepartmentReferenceError(ValidationError):
    code = "INVALID_DEPARTMENT"

    def __init__(
        self, message: str = "department_id does not reference a valid department"
    ) -> None:
        super().__init__(
            message,
            details=[{"field": "department_id", "code": "INVALID_DEPARTMENT", "message": message}],
        )


class InvalidBranchReferenceError(ValidationError):
    code = "INVALID_BRANCH"

    def __init__(self, message: str = "branch_id does not reference a valid branch") -> None:
        super().__init__(
            message, details=[{"field": "branch_id", "code": "INVALID_BRANCH", "message": message}]
        )


class InvalidLegalEntityReferenceError(ValidationError):
    code = "INVALID_LEGAL_ENTITY"

    def __init__(
        self, message: str = "legal_entity_id does not reference a valid legal entity"
    ) -> None:
        super().__init__(
            message,
            details=[
                {"field": "legal_entity_id", "code": "INVALID_LEGAL_ENTITY", "message": message}
            ],
        )
