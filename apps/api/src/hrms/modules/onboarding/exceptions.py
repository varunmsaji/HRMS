"""Module-specific AppError subclasses for the onboarding module — defined locally rather than
reused from `employee/exceptions.py`, following that module's own stated convention (each module
owns its own error shapes)."""

from hrms.core.errors.base import ConflictError, NotFoundError, ValidationError


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


class OnboardingTokenInvalidError(NotFoundError):
    """Raised by `get_onboarding_case_from_token` for any token that doesn't resolve to a live,
    usable case — unknown hash, revoked, expired, or the case is already in a terminal status
    (plan §5). Deliberately a `404`, not a `403` or a dedicated "invalid token" code — a public,
    unauthenticated surface must never let a response distinguish "token never existed" from
    "token existed but is no longer valid", which would leak information to anyone guessing
    tokens."""

    code = "NOT_FOUND"

    def __init__(self, message: str = "Resource not found") -> None:
        super().__init__(message)


class OnboardingSectionNotWritableError(ConflictError):
    """Raised when a candidate `PATCH`es a section while the case is not in a writable status
    (`ONBOARDING_CASE_WRITABLE_STATUSES`) — e.g. after they've already submitted, or before HR
    has sent the invite."""

    code = "ONBOARDING_SECTION_NOT_WRITABLE"

    def __init__(
        self, message: str = "This onboarding case is not currently open for edits"
    ) -> None:
        super().__init__(
            message,
            details=[
                {"field": "status", "code": "ONBOARDING_SECTION_NOT_WRITABLE", "message": message}
            ],
        )


class OnboardingCaseNotInvitableError(ConflictError):
    """Raised by `send-invite` when the case is not in a status that a link can meaningfully be
    (re)sent for — once the candidate has submitted (`SUBMITTED`/`UNDER_REVIEW`/`VERIFIED`) a
    fresh link would let them bypass HR's review, and a terminal case (`ACTIVATED`/`EXPIRED`/
    `CANCELLED`) has nothing left to invite. `CHANGES_REQUESTED`'s own reopen-and-resend flow
    belongs to O6, not this generic endpoint."""

    code = "ONBOARDING_CASE_NOT_INVITABLE"

    def __init__(
        self, message: str = "This onboarding case cannot be (re)invited in its current status"
    ) -> None:
        super().__init__(
            message,
            details=[
                {"field": "status", "code": "ONBOARDING_CASE_NOT_INVITABLE", "message": message}
            ],
        )


class InvalidOnboardingSectionError(ValidationError):
    """Raised for a `section` path parameter outside `ONBOARDING_SECTION_NAMES` — `documents`
    (O5) is a real section but has its own dedicated upload endpoints, not this generic
    `PATCH`."""

    code = "INVALID_SECTION"

    def __init__(self, section: str) -> None:
        message = f"{section} is not a valid onboarding section"
        super().__init__(
            message, details=[{"field": "section", "code": "INVALID_SECTION", "message": message}]
        )


class OnboardingCaseNotSubmittableError(ConflictError):
    """Raised by `submit` when the case is not in a status a submission can come from
    (`ONBOARDING_CASE_WRITABLE_STATUSES` — the same set `PATCH .../sections/*` already checks;
    submitting is itself just another write against the case, gated identically)."""

    code = "ONBOARDING_CASE_NOT_SUBMITTABLE"

    def __init__(
        self, message: str = "This onboarding case cannot be submitted in its current status"
    ) -> None:
        super().__init__(
            message,
            details=[
                {"field": "status", "code": "ONBOARDING_CASE_NOT_SUBMITTABLE", "message": message}
            ],
        )


class OnboardingIncompleteSectionsError(ValidationError):
    """Raised by `submit` when one or more of the five sections is still empty. Document
    completeness (plan §7.2: "validates all required sections+documents present") is not checked
    here — `onboarding_document` has no write path until O5, so there is nothing yet to require."""

    code = "ONBOARDING_INCOMPLETE_SECTIONS"

    def __init__(self, missing_sections: list[str]) -> None:
        message = f"{', '.join(missing_sections)} must be filled in before submitting"
        super().__init__(
            message,
            details=[
                {
                    "field": section,
                    "code": "ONBOARDING_INCOMPLETE_SECTIONS",
                    "message": message,
                }
                for section in missing_sections
            ],
        )
