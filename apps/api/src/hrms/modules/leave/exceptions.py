"""Module-specific AppError subclasses for the Leave module.

Mirrors `attendance.exceptions`'s generic Policy* shapes (identity+version+publish state
machine) rather than importing them — LD-05's reasoning (each module owns its own copy of a
shared *pattern* instead of a cross-module import) applies here too: Leave should stay a fully
independent, deletable module, not one that reaches into Attendance's exception classes for a
concept that happens to be shaped the same way."""

from typing import Any

from hrms.core.errors.base import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)


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


# ---------------------------------------------------------------------------
# L4 — LeaveApplication submission/approval. Mirrors attendance.exceptions's Regularization*
# shapes (LD-05: mirrored, not shared code) plus a few Leave-specific ones with no Regularization
# precedent (balance/half-day/date-range/calendar-config checks).
# ---------------------------------------------------------------------------


class LeaveApplicationPolicyNotResolvedError(ValidationError):
    code = "LEAVE_APPLICATION_POLICY_NOT_RESOLVED"

    def __init__(
        self, message: str = "No leave policy is configured for this employee and leave type"
    ) -> None:
        super().__init__(
            message, details=[{"field": "leave_type_id", "code": self.code, "message": message}]
        )


class LeaveApplicationNotPermittedError(PermissionDeniedError):
    """The applicable `LeavePolicyVersion` does not allow this submitter kind
    (`allow_employee_request`/`allow_manager_request_on_behalf`/`allow_hr_request_on_behalf`)."""

    code = "LEAVE_APPLICATION_NOT_PERMITTED"

    def __init__(
        self, message: str = "The applicable policy does not allow this kind of request"
    ) -> None:
        super().__init__(
            message, details=[{"field": "employee_id", "code": self.code, "message": message}]
        )


class LeaveApplicationWindowExceededError(ValidationError):
    code = "LEAVE_APPLICATION_WINDOW_EXCEEDED"

    def __init__(self, message: str = "This date is outside the allowed backdating window") -> None:
        super().__init__(
            message, details=[{"field": "start_date", "code": self.code, "message": message}]
        )


class LeaveApplicationLimitExceededError(ValidationError):
    code = "LEAVE_APPLICATION_LIMIT_EXCEEDED"

    def __init__(
        self, message: str = "The maximum number of requests for this period has been reached"
    ) -> None:
        super().__init__(
            message, details=[{"field": "employee_id", "code": self.code, "message": message}]
        )


class LeaveApplicationReasonRequiredError(ValidationError):
    code = "LEAVE_APPLICATION_REASON_REQUIRED"

    def __init__(self, message: str = "A reason is required by the applicable policy") -> None:
        super().__init__(
            message, details=[{"field": "reason", "code": self.code, "message": message}]
        )


class LeaveApplicationAttachmentRequiredError(ValidationError):
    code = "LEAVE_APPLICATION_ATTACHMENT_REQUIRED"

    def __init__(self, message: str = "An attachment is required by the applicable policy") -> None:
        super().__init__(
            message,
            details=[{"field": "attachment_reference", "code": self.code, "message": message}],
        )


class LeaveApplicationHalfDayNotAllowedError(ValidationError):
    code = "LEAVE_APPLICATION_HALF_DAY_NOT_ALLOWED"

    def __init__(
        self, message: str = "The applicable policy does not allow half-day leave"
    ) -> None:
        super().__init__(
            message, details=[{"field": "half", "code": self.code, "message": message}]
        )


class LeaveApplicationDateRangeInvalidError(ValidationError):
    code = "LEAVE_APPLICATION_DATE_RANGE_INVALID"

    def __init__(self, message: str) -> None:
        super().__init__(
            message, details=[{"field": "end_date", "code": self.code, "message": message}]
        )


class LeaveApplicationCalendarNotResolvedError(ValidationError):
    """WD-21 fail-closed, applied to L4: a date in the requested range has no `WorkCalendar`
    resolving for the employee, so it cannot be classified WORKING/WEEKLY_OFF/HOLIDAY for
    day-counting or the sandwich rule. Never silently treated as a working day."""

    code = "LEAVE_APPLICATION_CALENDAR_NOT_RESOLVED"

    def __init__(
        self, message: str = "The work calendar could not be resolved for one or more dates"
    ) -> None:
        super().__init__(
            message, details=[{"field": "start_date", "code": self.code, "message": message}]
        )


class LeaveApplicationInsufficientBalanceError(ValidationError):
    """LD-06: negative balance is never allowed — every application is hard-capped at the
    employee's current balance at time of submission."""

    code = "LEAVE_APPLICATION_INSUFFICIENT_BALANCE"

    def __init__(self, message: str = "Insufficient leave balance for this request") -> None:
        super().__init__(
            message, details=[{"field": "total_days", "code": self.code, "message": message}]
        )


class LeaveApplicationNotFoundError(NotFoundError):
    code = "LEAVE_APPLICATION_NOT_FOUND"

    def __init__(self, message: str = "Leave application not found") -> None:
        super().__init__(message)


class LeaveApplicationInvalidTransitionError(ConflictError):
    code = "LEAVE_APPLICATION_INVALID_TRANSITION"

    def __init__(
        self, message: str = "This application is not in a state that allows this action"
    ) -> None:
        super().__init__(
            message, details=[{"field": "status", "code": self.code, "message": message}]
        )


class LeaveApplicationSelfApprovalNotAllowedError(PermissionDeniedError):
    code = "LEAVE_APPLICATION_SELF_APPROVAL_NOT_ALLOWED"

    def __init__(self, message: str = "You cannot approve or reject your own application") -> None:
        super().__init__(
            message, details=[{"field": "employee_id", "code": self.code, "message": message}]
        )


class LeaveApplicationApproverMismatchError(PermissionDeniedError):
    code = "LEAVE_APPLICATION_APPROVER_MISMATCH"

    def __init__(
        self,
        message: str = "You are not the resolved approver for this application's current stage",
    ) -> None:
        super().__init__(
            message, details=[{"field": "approval_stage", "code": self.code, "message": message}]
        )
