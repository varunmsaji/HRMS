"""Module-specific AppError subclasses for the Leave module.

Mirrors `attendance.exceptions`'s generic Policy* shapes (identity+version+publish state
machine) rather than importing them — LD-05's reasoning (each module owns its own copy of a
shared *pattern* instead of a cross-module import) applies here too: Leave should stay a fully
independent, deletable module, not one that reaches into Attendance's exception classes for a
concept that happens to be shaped the same way."""

from typing import Any

from hrms.core.errors.base import ConflictError, NotFoundError, ValidationError


class LeavePolicyCodeAlreadyExistsError(ConflictError):
    code = "LEAVE_POLICY_CODE_ALREADY_EXISTS"

    def __init__(self, message: str = "A leave policy with this code already exists") -> None:
        super().__init__(
            message,
            details=[
                {"field": "code", "code": "LEAVE_POLICY_CODE_ALREADY_EXISTS", "message": message}
            ],
        )


class LeaveTypeCodeAlreadyExistsError(ConflictError):
    code = "LEAVE_TYPE_CODE_ALREADY_EXISTS"

    def __init__(self, message: str = "A leave type with this code already exists") -> None:
        super().__init__(
            message,
            details=[
                {"field": "code", "code": "LEAVE_TYPE_CODE_ALREADY_EXISTS", "message": message}
            ],
        )


class LeavePolicyDraftAlreadyExistsError(ConflictError):
    code = "LEAVE_POLICY_DRAFT_ALREADY_EXISTS"

    def __init__(
        self, message: str = "This leave policy already has an open draft version"
    ) -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "policy_id",
                    "code": "LEAVE_POLICY_DRAFT_ALREADY_EXISTS",
                    "message": message,
                }
            ],
        )


class LeavePolicyVersionNotDraftError(ConflictError):
    code = "LEAVE_POLICY_VERSION_NOT_DRAFT"

    def __init__(self, message: str = "Only a DRAFT version can be modified") -> None:
        super().__init__(
            message,
            details=[
                {"field": "status", "code": "LEAVE_POLICY_VERSION_NOT_DRAFT", "message": message}
            ],
        )


class LeavePolicyVersionPreviousVersionRequiredError(ValidationError):
    code = "LEAVE_POLICY_VERSION_PREVIOUS_VERSION_REQUIRED"

    def __init__(
        self,
        message: str = (
            "expected_previous_version is required to publish over an existing published version"
        ),
    ) -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "expected_previous_version",
                    "code": "LEAVE_POLICY_VERSION_PREVIOUS_VERSION_REQUIRED",
                    "message": message,
                }
            ],
        )


class LeavePolicyVersionOverlapError(ConflictError):
    code = "LEAVE_POLICY_VERSION_OVERLAP"

    def __init__(
        self,
        message: str = "Another published version already covers part of this date range",
    ) -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "effective_from",
                    "code": "LEAVE_POLICY_VERSION_OVERLAP",
                    "message": message,
                }
            ],
        )


class LeavePolicyVersionNotFoundForDateError(NotFoundError):
    code = "LEAVE_POLICY_VERSION_NOT_FOUND_FOR_DATE"

    def __init__(self, message: str = "No published leave policy version covers this date") -> None:
        super().__init__(message)


class StaleLeaveResourceError(ConflictError):
    code = "STALE_RESOURCE"

    def __init__(self, message: str, *, current: dict[str, Any]) -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "version",
                    "code": "STALE_RESOURCE",
                    "message": message,
                    "context": {"current": current},
                }
            ],
        )


class LeavePolicyPublishIncompleteError(ValidationError):
    code = "LEAVE_POLICY_PUBLISH_INCOMPLETE"

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "effective_from",
                    "code": "LEAVE_POLICY_PUBLISH_INCOMPLETE",
                    "message": message,
                }
            ],
        )
