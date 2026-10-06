"""Module-specific AppError subclasses for the Leave module.

Mirrors `attendance.exceptions`'s generic Policy* shapes (identity+version+publish state
machine) rather than importing them — LD-05's reasoning (each module owns its own copy of a
shared *pattern* instead of a cross-module import) applies here too: Leave should stay a fully
independent, deletable module, not one that reaches into Attendance's exception classes for a
concept that happens to be shaped the same way."""

from datetime import date
from decimal import Decimal
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


class LeaveTypeCompOffAlreadyExistsError(ConflictError):
    """LD-14 — the DB partial unique index allows at most one active `is_comp_off=true` leave
    type per company."""

    code = "LEAVE_TYPE_COMP_OFF_ALREADY_EXISTS"

    def __init__(
        self, message: str = "Another leave type is already marked as the comp-off type"
    ) -> None:
        super().__init__(
            message,
            details=[
                {"field": "is_comp_off", "code": self.code, "message": message},
            ],
        )


class LeaveTypeInUseError(ConflictError):
    """Decision 11 — `requires_balance`, `is_comp_off` and `is_paid_default` define what a leave
    type's applications and ledger entries *mean*; once any exist they must keep that meaning, so
    the change is refused instead of silently reinterpreting history."""

    code = "LEAVE_TYPE_IN_USE"

    def __init__(self, fields: list[str]) -> None:
        message = (
            "This leave type has already been used, so "
            + ", ".join(fields)
            + " can no longer be changed. Create a new leave type instead."
        )
        super().__init__(
            message,
            details=[{"field": field, "code": self.code, "message": message} for field in fields],
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


class LeaveApplicationNotAllowedDuringProbationError(ValidationError):
    """LD-18 — the applicable `LeavePolicyVersion` has `allowed_during_probation=False` and the
    employee's `Employee.status` is currently `PROBATION`."""

    code = "LEAVE_APPLICATION_NOT_ALLOWED_DURING_PROBATION"

    def __init__(
        self,
        message: str = "This leave type is not available to employees on probation",
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


class LeaveApplicationOverlapError(ConflictError):
    """The employee already has active (submitted or approved) leave on one of these dates and
    the days would add up to more than one. The same invariant `LeaveProjectionService.sync`
    enforces at approval, checked at submission so the second request is refused up front."""

    code = "LEAVE_APPLICATION_OVERLAP"

    def __init__(
        self,
        message: str = (
            "You already have leave submitted or approved for one or more of these dates"
        ),
    ) -> None:
        super().__init__(
            message, details=[{"field": "start_date", "code": self.code, "message": message}]
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


class LeaveApplicationMaxConsecutiveExceededError(ValidationError):
    """Decision 15 - the applicable policy version caps a single application's calendar span
    (`max_consecutive_days`, default 30)."""

    code = "LEAVE_APPLICATION_MAX_CONSECUTIVE_EXCEEDED"

    def __init__(self, *, limit: int, requested: int) -> None:
        message = (
            f"This leave policy allows at most {limit} consecutive days in one application "
            f"({requested} requested)"
        )
        super().__init__(
            message,
            details=[
                {
                    "field": "end_date",
                    "code": self.code,
                    "message": message,
                    "context": {"limit": limit, "requested": requested},
                }
            ],
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


class LeaveApplicationBalanceShortfallError(ConflictError):
    """PAY-010 (decision 9) — at final approval the balance (plus any allowed negative floor) no
    longer covers the application, e.g. another application was approved since it was
    submitted. The approver must reject, or approve again with `excess_as_lop` so the uncovered
    days become unpaid leave. Never silently negative."""

    code = "LEAVE_APPLICATION_BALANCE_SHORTFALL"

    def __init__(
        self, *, balance: Decimal, available: Decimal, requested: Decimal, shortfall: Decimal
    ) -> None:
        message = (
            f"Leave balance covers {max(available, Decimal('0.00'))} of the {requested} days "
            f"requested ({shortfall} short). Reject, or approve with the excess as loss of pay."
        )
        super().__init__(
            message,
            details=[
                {
                    "field": "total_days",
                    "code": self.code,
                    "message": message,
                    "context": {
                        "balance": str(balance),
                        "available": str(available),
                        "requested": str(requested),
                        "shortfall": str(shortfall),
                    },
                }
            ],
        )


class LeaveApplicationPeriodClosedError(ConflictError):
    """PD-3 — the application covers a date inside a `CLOSED` attendance period. Closing the
    period locks leave for those dates too: no new application, approval, or cancellation of
    approved leave there. Late corrections flow as arrears in the next payroll (decision 15)."""

    code = "LEAVE_APPLICATION_PERIOD_CLOSED"

    def __init__(self, *, period_start: date, period_end: date) -> None:
        message = (
            f"The attendance period {period_start} to {period_end} is closed — leave on these "
            "dates can no longer be applied for, approved, or cancelled"
        )
        super().__init__(
            message,
            details=[
                {
                    "field": "start_date",
                    "code": self.code,
                    "message": message,
                    "context": {
                        "period_start": period_start.isoformat(),
                        "period_end": period_end.isoformat(),
                    },
                }
            ],
        )


class LeaveLedgerPeriodClosedError(ConflictError):
    """Decision 14 - a manual adjustment or encashment may not directly modify a closed
    attendance period; a correction after closure is a new entry dated in an open period."""

    code = "LEAVE_LEDGER_PERIOD_CLOSED"

    def __init__(self, *, period_start: date, period_end: date) -> None:
        message = (
            f"The attendance period {period_start} to {period_end} is closed, so the balance "
            "cannot be changed with an effective date inside it. Date the correction in an open "
            "period instead."
        )
        super().__init__(
            message,
            details=[
                {
                    "field": "effective_date",
                    "code": self.code,
                    "message": message,
                    "context": {
                        "period_start": period_start.isoformat(),
                        "period_end": period_end.isoformat(),
                    },
                }
            ],
        )


class LeaveLedgerPayrollFinalisedError(ConflictError):
    """Decision 14 - the period's payroll is finalised; issued payroll history is never rewritten
    by a balance change dated inside it."""

    code = "LEAVE_LEDGER_PAYROLL_FINALISED"

    def __init__(self, *, period_start: date, period_end: date) -> None:
        message = (
            f"Payroll for {period_start} to {period_end} is already finalised, so the balance "
            "cannot be changed with an effective date inside it. Date the correction in an open "
            "period instead."
        )
        super().__init__(
            message,
            details=[
                {
                    "field": "effective_date",
                    "code": self.code,
                    "message": message,
                    "context": {
                        "period_start": period_start.isoformat(),
                        "period_end": period_end.isoformat(),
                    },
                }
            ],
        )


class LeaveApplicationCancelReasonRequiredError(ValidationError):
    """Decision 10 — cancelling approved leave that has already started needs a reason."""

    code = "LEAVE_APPLICATION_CANCEL_REASON_REQUIRED"

    def __init__(
        self, message: str = "A reason is required to cancel leave that has already started"
    ) -> None:
        super().__init__(
            message, details=[{"field": "reason", "code": self.code, "message": message}]
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


# ---------------------------------------------------------------------------
# Encashment — client spec §12 (LD-19)
# ---------------------------------------------------------------------------


class LeaveEncashmentPolicyNotResolvedError(ValidationError):
    code = "LEAVE_ENCASHMENT_POLICY_NOT_RESOLVED"

    def __init__(
        self, message: str = "No leave policy is configured for this employee and leave type"
    ) -> None:
        super().__init__(
            message, details=[{"field": "leave_type_id", "code": self.code, "message": message}]
        )


class LeaveEncashmentNotAllowedError(ValidationError):
    code = "LEAVE_ENCASHMENT_NOT_ALLOWED"

    def __init__(self, message: str = "Encashment is not allowed for this leave type") -> None:
        super().__init__(
            message, details=[{"field": "leave_type_id", "code": self.code, "message": message}]
        )


class LeaveEncashmentMaxDaysExceededError(ValidationError):
    code = "LEAVE_ENCASHMENT_MAX_DAYS_EXCEEDED"

    def __init__(
        self, message: str = "This request exceeds the maximum encashable days allowed"
    ) -> None:
        super().__init__(
            message, details=[{"field": "days", "code": self.code, "message": message}]
        )


class LeaveEncashmentMinimumBalanceViolationError(ValidationError):
    code = "LEAVE_ENCASHMENT_MINIMUM_BALANCE_VIOLATION"

    def __init__(
        self,
        message: str = "This request would leave the balance below the required minimum",
    ) -> None:
        super().__init__(
            message, details=[{"field": "days", "code": self.code, "message": message}]
        )


# ---------------------------------------------------------------------------
# Leave Combination Rule — client spec §7 (LD-16)
# ---------------------------------------------------------------------------


class LeaveCombinationRuleAlreadyExistsError(ConflictError):
    """The DB partial unique index allows at most one rule per unordered leave-type pair
    (LD-16)."""

    code = "LEAVE_COMBINATION_RULE_ALREADY_EXISTS"

    def __init__(
        self, message: str = "A combination rule for this pair of leave types already exists"
    ) -> None:
        super().__init__(
            message,
            details=[{"field": "leave_type_id_b", "code": self.code, "message": message}],
        )


class LeaveCombinationRuleNotFoundError(NotFoundError):
    code = "LEAVE_COMBINATION_RULE_NOT_FOUND"

    def __init__(self, message: str = "Leave combination rule not found") -> None:
        super().__init__(message)


class LeaveApplicationCombinationNotAllowedError(ValidationError):
    """LD-16 — this leave type has an explicit `allowed=False` combination rule against another
    leave type the employee already has an active (SUBMITTED or APPROVED) application for on an
    overlapping date."""

    code = "LEAVE_APPLICATION_COMBINATION_NOT_ALLOWED"

    def __init__(
        self,
        message: str = (
            "This leave type cannot be combined with another leave type already applied for "
            "on an overlapping date"
        ),
    ) -> None:
        super().__init__(
            message, details=[{"field": "leave_type_id", "code": self.code, "message": message}]
        )


# ---------------------------------------------------------------------------
# Statutory Leave Minimum — client spec §16 (LD-22), legal compliance floor
# ---------------------------------------------------------------------------


class LeaveStatutoryMinimumNotFoundError(NotFoundError):
    code = "LEAVE_STATUTORY_MINIMUM_NOT_FOUND"

    def __init__(self, message: str = "Statutory leave minimum not found") -> None:
        super().__init__(message)


class LeavePolicyBelowStatutoryMinimumError(ValidationError):
    """LD-22 — the draft's computed annual entitlement (from `accrual_frequency`/
    `accrual_rate_per_cycle`) is below the strictest `statutory_leave_minimum` configured for its
    leave type's `statutory_category`. Publishing is hard-blocked (client answer 2026-09-06), not
    just flagged."""

    code = "LEAVE_POLICY_BELOW_STATUTORY_MINIMUM"

    def __init__(
        self,
        message: str = "This policy's annual entitlement is below the statutory minimum",
    ) -> None:
        super().__init__(
            message,
            details=[{"field": "accrual_rate_per_cycle", "code": self.code, "message": message}],
        )


class LeaveApproverStillEligibleError(ConflictError):
    """Decision 13 - a stage is reassigned only when its current approver can no longer act."""

    code = "LEAVE_APPROVER_STILL_ELIGIBLE"

    def __init__(self) -> None:
        super().__init__(
            "The current approver is still eligible to act on this stage, so it cannot be "
            "reassigned"
        )


class LeaveApproverReassignNotApplicableError(ConflictError):
    """Decision 13 - only a pending MANAGER or HOD stage names a specific person; the HR stage is
    open to any company-wide approver and a finished application has no stage at all."""

    code = "LEAVE_APPROVER_REASSIGN_NOT_APPLICABLE"

    def __init__(self) -> None:
        super().__init__(
            "Only a pending application waiting at the MANAGER or HOD stage can be reassigned"
        )


class LeaveReassignApproverNotEligibleError(ValidationError):
    """Decision 13 - the proposed approver must satisfy the stage's own eligibility rules."""

    code = "LEAVE_REASSIGN_APPROVER_NOT_ELIGIBLE"

    def __init__(self, reason: str) -> None:
        message = "The proposed approver cannot approve this application"
        super().__init__(
            message,
            details=[{"field": "new_approver_employee_id", "code": reason, "message": message}],
        )


def _outside_employment_message(status: str, offending: date | None) -> str:
    when = f" ({offending.isoformat()})" if offending is not None else ""
    return {
        "NO_EMPLOYMENT": "The employee has no employment record covering these dates",
        "PRE_JOINING": f"These dates start before the employee's joining date{when}",
        "AFTER_LAST_WORKING_DAY": f"These dates run past the employee's last working day{when}",
        "REHIRE_GAP": f"These dates fall in a gap between two employments{when}",
        "CROSS_EMPLOYMENT_SPELL": (
            f"These dates span two separate employments{when}; split them into one request each"
        ),
    }.get(status, "These dates are outside the employee's employment")


def _outside_employment_details(
    field: str, code: str, status: str, offending: date | None
) -> list[dict[str, Any]]:
    message = _outside_employment_message(status, offending)
    context: dict[str, str] = {"reason": status}
    if offending is not None:
        context["offending_date"] = offending.isoformat()
    return [{"field": field, "code": code, "message": message, "context": context}]


class LeaveDateOutsideEmploymentError(ValidationError):
    """D0-D3/D5 - a new leave application, manual adjustment or encashment whose date(s) are not
    covered by ONE employment spell of the employee. `reason` is one of NO_EMPLOYMENT,
    PRE_JOINING, AFTER_LAST_WORKING_DAY, REHIRE_GAP, CROSS_EMPLOYMENT_SPELL."""

    code = "LEAVE_DATE_OUTSIDE_EMPLOYMENT"

    def __init__(
        self, *, reason: str, offending_date: date | None, field: str = "start_date"
    ) -> None:
        details = _outside_employment_details(field, self.code, reason, offending_date)
        super().__init__(details[0]["message"], details=details)


class LeaveApprovalOutsideEmploymentError(ConflictError):
    """D3/LM-15 - the application was valid when submitted but employment has changed since, so
    approving it would book leave outside employment. Nothing is debited or approved; the
    application stays as it is (HR rejects or cancels it)."""

    code = "LEAVE_APPROVAL_OUTSIDE_EMPLOYMENT"

    def __init__(self, *, reason: str, offending_date: date | None) -> None:
        details = _outside_employment_details("start_date", self.code, reason, offending_date)
        super().__init__(details[0]["message"], details=details)
