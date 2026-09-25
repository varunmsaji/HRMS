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
        message: str = ("An active onboarding case already exists for this personal email"),
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
    fresh link would let them bypass HR's review, and `EXPIRED`/`CANCELLED` cases have nothing
    left to invite. `CHANGES_REQUESTED`'s own reopen-and-resend flow belongs to O6, not this
    generic endpoint. `ACTIVATED` is *not* raised here — see `ONBOARDING_CASE_INVITABLE_STATUSES`
    for why a link is still issuable (read-only) after activation."""

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


class InvalidOnboardingDocumentTypeError(ValidationError):
    code = "INVALID_DOCUMENT_TYPE"

    def __init__(self, document_type: str) -> None:
        message = f"{document_type} is not a valid document type"
        super().__init__(
            message,
            details=[
                {"field": "document_type", "code": "INVALID_DOCUMENT_TYPE", "message": message}
            ],
        )


class OnboardingDocumentTooLargeError(ValidationError):
    """Raised when an uploaded file exceeds `ONBOARDING_DOCUMENT_MAX_SIZE_BYTES` — this task's
    own cap (plan §8.3 flags virus scanning as deferred but names no size limit)."""

    code = "DOCUMENT_TOO_LARGE"

    def __init__(self, max_size_bytes: int) -> None:
        message = f"File exceeds the {max_size_bytes // (1024 * 1024)}MB upload limit"
        super().__init__(
            message,
            details=[{"field": "file", "code": "DOCUMENT_TOO_LARGE", "message": message}],
        )


class UnsupportedDocumentContentError(ValidationError):
    """Raised when an uploaded file's own bytes don't match any allowed document signature
    (SEC-04, `hrms.modules.onboarding.document_validation.sniff_document_content_type`) —
    covers an empty file, random binary data, and content (HTML/JS/executables/etc.) that doesn't
    match its claimed type, regardless of what `Content-Type` header or filename the client sent."""

    code = "UNSUPPORTED_DOCUMENT_CONTENT"

    def __init__(self) -> None:
        message = "File content is not a supported document type (PDF, JPEG, or PNG)"
        super().__init__(
            message,
            details=[{"field": "file", "code": "UNSUPPORTED_DOCUMENT_CONTENT", "message": message}],
        )


class OnboardingCaseNotReviewableError(ConflictError):
    """Raised by section/document review when the case isn't in a status a review action makes
    sense for (`ONBOARDING_CASE_REVIEWABLE_STATUSES` — `SUBMITTED`/`UNDER_REVIEW`). Reviewing
    something the candidate hasn't submitted yet, or that HR has already finished with
    (`VERIFIED`/`CHANGES_REQUESTED`/terminal), is not a supported action."""

    code = "ONBOARDING_CASE_NOT_REVIEWABLE"

    def __init__(
        self, message: str = "This onboarding case is not currently open for review"
    ) -> None:
        super().__init__(
            message,
            details=[
                {"field": "status", "code": "ONBOARDING_CASE_NOT_REVIEWABLE", "message": message}
            ],
        )


class OnboardingSectionAlreadyVerifiedError(ConflictError):
    """Raised when a candidate `PATCH`es a section HR has already verified — once verified, a
    section is locked even if the case's own status (`CHANGES_REQUESTED`) would otherwise allow
    writes to *other*, still-`PENDING`/`REJECTED` sections (plan §7.2: "Only sections currently
    in PENDING/reopened-by-rejection state are writable")."""

    code = "ONBOARDING_SECTION_ALREADY_VERIFIED"

    def __init__(
        self, message: str = "This section has already been verified and can no longer be edited"
    ) -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "status",
                    "code": "ONBOARDING_SECTION_ALREADY_VERIFIED",
                    "message": message,
                }
            ],
        )


class OnboardingNothingToRequestChangesForError(ConflictError):
    """Raised by `request-changes` when the case isn't `UNDER_REVIEW`, or is but nothing has
    actually been rejected yet — requesting changes for a fully-verified (or not-yet-reviewed)
    case is not a meaningful action."""

    code = "ONBOARDING_NOTHING_TO_REQUEST_CHANGES_FOR"

    def __init__(
        self,
        message: str = (
            "This case is not under review, or nothing has been rejected yet — "
            "there is nothing to request changes for"
        ),
    ) -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "status",
                    "code": "ONBOARDING_NOTHING_TO_REQUEST_CHANGES_FOR",
                    "message": message,
                }
            ],
        )


class OnboardingCaseNotReadyForActivationError(ConflictError):
    """Raised by `activate` when the case is not `VERIFIED` — the only status activation may act
    on. Reaching `VERIFIED` already proves every section and document was verified
    (`_maybe_auto_verify_case`, O6), so activation trusts that invariant rather than
    re-deriving it here."""

    code = "ONBOARDING_CASE_NOT_READY_FOR_ACTIVATION"

    def __init__(
        self, message: str = "This onboarding case must be fully verified before activation"
    ) -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "status",
                    "code": "ONBOARDING_CASE_NOT_READY_FOR_ACTIVATION",
                    "message": message,
                }
            ],
        )


class OnboardingCaseMissingLegalEntityError(ValidationError):
    """Raised by `activate` when `legal_entity_id` was never set on the case — optional
    throughout the rest of the flow (case creation, sections, submit), but `EmploymentCreate`
    (`hrms.modules.employee.schemas`) requires a real legal entity, so activation cannot proceed
    without one. `branch_id`/`department_id`/`designation_id` get no equivalent check here —
    `EmployeeAssignmentService.create_assignment` already raises its own
    `AssignmentFieldsRequiredError` for those, and duplicating that check in this module would
    just be two sources of truth for the same rule."""

    code = "ONBOARDING_CASE_MISSING_LEGAL_ENTITY"

    def __init__(
        self,
        message: str = "A legal entity must be set on this case before it can be activated",
    ) -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "legal_entity_id",
                    "code": "ONBOARDING_CASE_MISSING_LEGAL_ENTITY",
                    "message": message,
                }
            ],
        )
