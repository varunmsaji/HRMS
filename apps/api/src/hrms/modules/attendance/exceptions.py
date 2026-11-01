"""Module-specific AppError subclasses for the attendance module.

Shared across all three policy families (Attendance/Overtime/Regularization) since they share
one identity+version+publish shape (mirrors `organisation.exceptions`'s `ShiftVersion*` classes,
generalised here instead of tripled — the three families differ only in which typed rule
children they carry, not in the versioning state machine)."""

from datetime import date, datetime
from typing import Any

from hrms.core.errors.base import (
    AppError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)


class PolicyCodeAlreadyExistsError(ConflictError):
    """A partial unique index on `(company_id, code)` for active rows backs this, mirroring
    `HolidayCalendarCodeAlreadyExistsError`."""

    code = "POLICY_CODE_ALREADY_EXISTS"

    def __init__(self, message: str = "A policy with this code already exists") -> None:
        super().__init__(
            message,
            details=[{"field": "code", "code": "POLICY_CODE_ALREADY_EXISTS", "message": message}],
        )


class PolicyDraftAlreadyExistsError(ConflictError):
    """At most one open DRAFT version per policy identity (partial unique index, mirrors
    `shift_version_one_open_draft_idx`)."""

    code = "POLICY_DRAFT_ALREADY_EXISTS"

    def __init__(self, message: str = "This policy already has an open draft version") -> None:
        super().__init__(
            message,
            details=[
                {"field": "policy_id", "code": "POLICY_DRAFT_ALREADY_EXISTS", "message": message}
            ],
        )


class PolicyVersionNotDraftError(ConflictError):
    """A published version can never be mutated/discarded again — a new draft must be created."""

    code = "POLICY_VERSION_NOT_DRAFT"

    def __init__(self, message: str = "Only a DRAFT version can be modified") -> None:
        super().__init__(
            message,
            details=[{"field": "status", "code": "POLICY_VERSION_NOT_DRAFT", "message": message}],
        )


class PolicyVersionPreviousVersionRequiredError(ValidationError):
    """When a currently open PUBLISHED version already exists, the caller must supply
    `expected_previous_version` so it can be closed (mirrors
    `ShiftVersionPreviousVersionRequiredError`)."""

    code = "POLICY_VERSION_PREVIOUS_VERSION_REQUIRED"

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
                    "code": "POLICY_VERSION_PREVIOUS_VERSION_REQUIRED",
                    "message": message,
                }
            ],
        )


class InvalidPolicyVersionEffectiveFromError(ValidationError):
    code = "INVALID_POLICY_VERSION_EFFECTIVE_FROM"

    def __init__(
        self,
        message: str = (
            "effective_from must be after the currently published version's effective_from"
        ),
    ) -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "effective_from",
                    "code": "INVALID_POLICY_VERSION_EFFECTIVE_FROM",
                    "message": message,
                }
            ],
        )


class PolicyVersionOverlapError(ConflictError):
    """GiST exclusion backstop for the insert-new/close-previous publish flow, converts the
    resulting `IntegrityError` into the documented envelope (mirrors `ShiftVersionOverlapError`)."""

    code = "POLICY_VERSION_OVERLAP"

    def __init__(
        self,
        message: str = "Another published version already covers part of this date range",
    ) -> None:
        super().__init__(
            message,
            details=[
                {"field": "effective_from", "code": "POLICY_VERSION_OVERLAP", "message": message}
            ],
        )


class PolicyVersionNotFoundForDateError(NotFoundError):
    code = "POLICY_VERSION_NOT_FOUND_FOR_DATE"

    def __init__(self, message: str = "No published policy version covers this date") -> None:
        super().__init__(message)


class StalePolicyResourceError(ConflictError):
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


class PolicyPublishIncompleteError(ValidationError):
    """Raised when a draft is missing typed configuration required to publish — e.g. an
    Attendance Policy with zero hour bands (architecture §36: "publishing incomplete policy" must
    be a clear validation error, never silently normalized)."""

    code = "POLICY_PUBLISH_INCOMPLETE"

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            details=[{"field": "status", "code": "POLICY_PUBLISH_INCOMPLETE", "message": message}],
        )


class InvalidPolicyBandError(ValidationError):
    """Raised when hour/late/early-departure bands are missing, negative, unordered, gapped, or
    overlapping (architecture §36). Applies uniformly to all three band child tables."""

    code = "INVALID_POLICY_BAND"

    def __init__(self, message: str, *, field: str = "bands") -> None:
        super().__init__(
            message,
            details=[{"field": field, "code": "INVALID_POLICY_BAND", "message": message}],
        )


class InvalidPolicyRateRowError(ValidationError):
    code = "INVALID_POLICY_RATE_ROW"

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            details=[{"field": "rate_rows", "code": "INVALID_POLICY_RATE_ROW", "message": message}],
        )


class InvalidRegularizationAllowedTypeError(ValidationError):
    code = "INVALID_REGULARIZATION_ALLOWED_TYPE"

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "allowed_types",
                    "code": "INVALID_REGULARIZATION_ALLOWED_TYPE",
                    "message": message,
                }
            ],
        )


# ---------------------------------------------------------------------------
# W4 — Punch / AttendanceDay
# ---------------------------------------------------------------------------


class AttendanceDayLockedError(ConflictError):
    """Recompute refused because `AttendanceDay.is_locked` is true (WD-11 — locked days never
    silently recompute). No W4 code path can set `is_locked=true` yet (`AttendanceLock`, the
    period-lock entity, is W8 per architecture §30) — this exists so the recompute code path
    already has the refusal wired for when W8 lands."""

    code = "ATTENDANCE_DAY_LOCKED"

    def __init__(
        self, message: str = "This attendance day is locked and cannot be recomputed"
    ) -> None:
        super().__init__(
            message,
            details=[{"field": "is_locked", "code": "ATTENDANCE_DAY_LOCKED", "message": message}],
        )


class ShiftRosterNotFoundError(NotFoundError):
    code = "SHIFT_ROSTER_NOT_FOUND"

    def __init__(self, message: str = "Roster entry not found") -> None:
        super().__init__(message)


class ShiftRosterDateConflictError(ConflictError):
    """The partial unique index on `(company_id, employee_id, roster_date)` backs this —
    mirrors `DuplicatePunchIdempotencyKeyError`'s pattern of converting a DB-level
    `IntegrityError` into the documented envelope. A date already has a roster row; the caller
    must PATCH the existing entry instead of creating a second one."""

    code = "SHIFT_ROSTER_DATE_CONFLICT"

    def __init__(
        self, message: str = "A roster entry already exists for this employee and date"
    ) -> None:
        super().__init__(
            message,
            details=[
                {"field": "roster_date", "code": "SHIFT_ROSTER_DATE_CONFLICT", "message": message}
            ],
        )


class StaleShiftRosterResourceError(ConflictError):
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


class RegularizationPolicyNotResolvedError(ValidationError):
    """WD-21 fail-closed: no `RegularizationPolicyVersion` resolves for this employee-date, so
    a request cannot be evaluated against caps/windows/allowed-types that don't exist."""

    code = "REGULARIZATION_POLICY_NOT_RESOLVED"

    def __init__(
        self, message: str = "No regularization policy is configured for this employee and date"
    ) -> None:
        super().__init__(
            message, details=[{"field": "attendance_date", "code": self.code, "message": message}]
        )


class RegularizationTypeNotAllowedError(ValidationError):
    code = "REGULARIZATION_TYPE_NOT_ALLOWED"

    def __init__(
        self, message: str = "This request type is not allowed by the applicable policy"
    ) -> None:
        super().__init__(
            message, details=[{"field": "request_type", "code": self.code, "message": message}]
        )


class RegularizationNotPermittedError(PermissionDeniedError):
    """The applicable `RegularizationPolicyVersion` does not allow this submitter kind
    (`allow_employee_request`/`allow_manager_request`/`allow_hr_request`)."""

    code = "REGULARIZATION_NOT_PERMITTED"

    def __init__(
        self, message: str = "The applicable policy does not allow this kind of request"
    ) -> None:
        super().__init__(
            message, details=[{"field": "employee_id", "code": self.code, "message": message}]
        )


class RegularizationWindowExceededError(ValidationError):
    code = "REGULARIZATION_WINDOW_EXCEEDED"

    def __init__(self, message: str = "This date is outside the allowed backdating window") -> None:
        super().__init__(
            message, details=[{"field": "attendance_date", "code": self.code, "message": message}]
        )


class RegularizationRequestLimitExceededError(ValidationError):
    code = "REGULARIZATION_REQUEST_LIMIT_EXCEEDED"

    def __init__(
        self,
        message: str = "The maximum number of requests for this period has been reached",
    ) -> None:
        super().__init__(
            message, details=[{"field": "employee_id", "code": self.code, "message": message}]
        )


class RegularizationReasonRequiredError(ValidationError):
    code = "REGULARIZATION_REASON_REQUIRED"

    def __init__(self, message: str = "A reason is required by the applicable policy") -> None:
        super().__init__(
            message, details=[{"field": "reason", "code": self.code, "message": message}]
        )


class RegularizationAttachmentRequiredError(ValidationError):
    code = "REGULARIZATION_ATTACHMENT_REQUIRED"

    def __init__(self, message: str = "An attachment is required by the applicable policy") -> None:
        super().__init__(
            message,
            details=[{"field": "attachment_reference", "code": self.code, "message": message}],
        )


class RegularizationDuplicateActiveRequestError(ConflictError):
    code = "REGULARIZATION_DUPLICATE_ACTIVE_REQUEST"

    def __init__(
        self,
        message: str = "An active regularization request already exists for this employee and date",
    ) -> None:
        super().__init__(
            message, details=[{"field": "attendance_date", "code": self.code, "message": message}]
        )


class RegularizationRequestNotFoundError(NotFoundError):
    code = "REGULARIZATION_REQUEST_NOT_FOUND"

    def __init__(self, message: str = "Regularization request not found") -> None:
        super().__init__(message)


class RegularizationInvalidTransitionError(ConflictError):
    code = "REGULARIZATION_INVALID_TRANSITION"

    def __init__(
        self, message: str = "This request is not in a state that allows this action"
    ) -> None:
        super().__init__(
            message, details=[{"field": "status", "code": self.code, "message": message}]
        )


class FaceEnrollmentSelfApprovalNotAllowedError(PermissionDeniedError):
    """Face enrollment decides which face every later punch is matched against, so the person
    being enrolled can never be the one who approves or rejects it. Always blocked (same stance as
    WD-28 regularisation): a second authorised reviewer is required, no policy field permits it."""

    code = "FACE_ENROLLMENT_SELF_APPROVAL_NOT_ALLOWED"

    def __init__(
        self, message: str = "You cannot approve or reject your own face enrollment"
    ) -> None:
        super().__init__(
            message, details=[{"field": "employee_id", "code": self.code, "message": message}]
        )


class RegularizationSelfApprovalNotAllowedError(PermissionDeniedError):
    """WD-28 decision 5 — self-approval is always blocked; no policy field exists to permit it."""

    code = "REGULARIZATION_SELF_APPROVAL_NOT_ALLOWED"

    def __init__(self, message: str = "You cannot approve or reject your own request") -> None:
        super().__init__(
            message, details=[{"field": "employee_id", "code": self.code, "message": message}]
        )


class RegularizationApproverMismatchError(PermissionDeniedError):
    code = "REGULARIZATION_APPROVER_MISMATCH"

    def __init__(
        self, message: str = "You are not the resolved approver for this request's current stage"
    ) -> None:
        super().__init__(
            message, details=[{"field": "approval_stage", "code": self.code, "message": message}]
        )


class RegularizationBlockedByLockError(ConflictError):
    code = "REGULARIZATION_BLOCKED_BY_LOCK"

    def __init__(
        self, message: str = "This attendance day is locked and cannot be regularized"
    ) -> None:
        super().__init__(
            message, details=[{"field": "attendance_date", "code": self.code, "message": message}]
        )


class StaleRegularizationRequestResourceError(ConflictError):
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


class OvertimeRecordNotFoundError(NotFoundError):
    code = "OVERTIME_RECORD_NOT_FOUND"

    def __init__(self, message: str = "Overtime record not found") -> None:
        super().__init__(message)


class OvertimeInvalidTransitionError(ConflictError):
    code = "OVERTIME_INVALID_TRANSITION"

    def __init__(
        self, message: str = "This overtime record is not in a state that allows this action"
    ) -> None:
        super().__init__(
            message, details=[{"field": "status", "code": self.code, "message": message}]
        )


class OvertimeSelfApprovalNotAllowedError(PermissionDeniedError):
    """WD-29 decision 4 — mirrors WD-28 decision 5: self-approval is always blocked, no policy
    field exists to permit it."""

    code = "OVERTIME_SELF_APPROVAL_NOT_ALLOWED"

    def __init__(self, message: str = "You cannot approve or reject your own overtime") -> None:
        super().__init__(
            message, details=[{"field": "employee_id", "code": self.code, "message": message}]
        )


class OvertimeApproverMismatchError(PermissionDeniedError):
    code = "OVERTIME_APPROVER_MISMATCH"

    def __init__(
        self,
        message: str = "You are not the resolved approver for this overtime record's current stage",
    ) -> None:
        super().__init__(
            message, details=[{"field": "approval_stage", "code": self.code, "message": message}]
        )


class StaleOvertimeRecordResourceError(ConflictError):
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


class AttendancePeriodNotFoundError(NotFoundError):
    code = "ATTENDANCE_PERIOD_NOT_FOUND"

    def __init__(self, message: str = "Attendance period not found") -> None:
        super().__init__(message)


class AttendancePeriodOverlapError(ConflictError):
    """The GiST exclusion constraint on `(company_id, legal_entity_id, daterange(period_start,
    period_end))` backs this — mirrors `PolicyVersionOverlapError`'s pattern of converting a
    DB-level `IntegrityError` into the documented envelope."""

    code = "ATTENDANCE_PERIOD_OVERLAP"

    def __init__(
        self,
        message: str = (
            "Another attendance period for this legal entity already covers part of this date range"
        ),
    ) -> None:
        super().__init__(
            message, details=[{"field": "period_start", "code": self.code, "message": message}]
        )


class AttendancePeriodLegalEntityInvalidError(ValidationError):
    """Decision 14 — a period belongs to one legal entity of the caller's own company."""

    code = "ATTENDANCE_PERIOD_LEGAL_ENTITY_INVALID"

    def __init__(self, message: str = "Legal entity not found in this company") -> None:
        super().__init__(
            message, details=[{"field": "legal_entity_id", "code": self.code, "message": message}]
        )


class AttendancePeriodPayrollFinalisedError(ConflictError):
    """Decision 15 — once the pay run that read a period is finalised, the period never reopens;
    a late correction flows as arrears in a later pay run instead."""

    code = "ATTENDANCE_PERIOD_PAYROLL_FINALISED"

    def __init__(
        self,
        message: str = (
            "Payroll for this period is finalised — it cannot be reopened. Make the correction "
            "in a later period; it is paid as arrears"
        ),
    ) -> None:
        super().__init__(
            message, details=[{"field": "status", "code": self.code, "message": message}]
        )


class AttendancePeriodInvalidTransitionError(ConflictError):
    """Raised when finalize/reopen is attempted against a period that is not in the state that
    action requires (e.g. finalizing an already-`CLOSED` period, reopening an `OPEN` one)."""

    code = "ATTENDANCE_PERIOD_INVALID_TRANSITION"

    def __init__(
        self, message: str = "This attendance period is not in a state that allows this action"
    ) -> None:
        super().__init__(
            message, details=[{"field": "status", "code": self.code, "message": message}]
        )


class AttendancePeriodFinalizationBlockedError(ConflictError):
    """Fail-closed: finalize refuses whenever a fresh validation run (never a stale cached
    result) finds any blocking reason. `reasons` mirrors the shape `GET .../validate` returns so
    the caller sees identical detail whether they checked first or not."""

    code = "ATTENDANCE_FINALIZATION_BLOCKED"

    def __init__(
        self,
        message: str = (
            "This attendance period cannot be finalized until all blocking issues are resolved"
        ),
        *,
        reasons: list[dict[str, Any]],
    ) -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "status",
                    "code": self.code,
                    "message": message,
                    "context": {"reasons": reasons},
                }
            ],
        )


class AttendancePeriodClosedError(ConflictError):
    """The authoritative lock-enforcement error: a mutation (punch, roster write, regularization
    submission, overtime approval) targets a date covered by a `CLOSED` `AttendancePeriod`.
    Distinct from `AttendanceDayLockedError` (raised only by `AttendanceDayService.calculate()`
    against an already-computed, already-`is_locked` day row) — this one is the period-level
    check every other mutating service consults, including for a date that has no
    `AttendanceDay` row at all yet (WD-30 — the period, not the per-day flag, is the source of
    truth; `is_locked`/`locked_at` is a synchronized denormalization set atomically by
    finalize/reopen)."""

    code = "ATTENDANCE_PERIOD_CLOSED"

    def __init__(
        self,
        message: str = "This date falls within a closed attendance period and cannot be changed",
    ) -> None:
        super().__init__(
            message, details=[{"field": "attendance_date", "code": self.code, "message": message}]
        )


class StaleAttendancePeriodResourceError(ConflictError):
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


class LeaveProjectionNotFoundError(NotFoundError):
    code = "LEAVE_PROJECTION_NOT_FOUND"

    def __init__(self, message: str = "Leave projection not found") -> None:
        super().__init__(message)


class LeaveProjectionOverlapError(ConflictError):
    """W9 (architecture §21 "fail closed if ambiguous") — active (`APPROVED`) leave projection
    fractions for one employee-date must never sum to more than 1.00. Raised at sync time, before
    any row is written."""

    code = "LEAVE_PROJECTION_OVERLAP"

    def __init__(
        self,
        message: str = (
            "Active leave projections for this employee and date would sum to more than 1.00"
        ),
    ) -> None:
        super().__init__(
            message, details=[{"field": "fraction", "code": self.code, "message": message}]
        )


class StaleLeaveProjectionResourceError(ConflictError):
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


class DuplicatePunchIdempotencyKeyError(ConflictError):
    """The partial unique index on `(company_id, idempotency_key)` backs this — mirrors
    `PolicyCodeAlreadyExistsError`'s pattern of converting a DB-level `IntegrityError` into the
    documented envelope."""

    code = "DUPLICATE_PUNCH_IDEMPOTENCY_KEY"

    def __init__(self, message: str = "A punch with this idempotency_key already exists") -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "idempotency_key",
                    "code": "DUPLICATE_PUNCH_IDEMPOTENCY_KEY",
                    "message": message,
                }
            ],
        )


class FuturePunchTimeError(ValidationError):
    """`DEC-TZ-03` (SELECTED: hard floor, no tolerance) — an on-behalf `punch_time` may never be
    later than the instant the server received the request.

    This bound only exists on the on-behalf route. The self-service route cannot express a future
    time at all, because `DEC-TZ-01` removed its `punch_time` field entirely — the control there
    is structural, not a threshold, which is why no skew tolerance is configurable anywhere.

    Deliberately **no** grace window: an on-behalf punch is a human correction about the past, so
    a future date is always an error, never absorbed device drift."""

    code = "PUNCH_TIME_IN_FUTURE"

    def __init__(
        self, message: str = "punch_time may not be later than the current server time"
    ) -> None:
        super().__init__(
            message,
            details=[{"field": "punch_time", "code": "PUNCH_TIME_IN_FUTURE", "message": message}],
        )


class EmployeeTerminatedError(ValidationError):
    """A punch (any source) whose company-local date is after the employee's last working day.
    The last working day itself is still a working day; the day after is not. Rejected at
    creation rather than left for the calculation engine to classify as `EXITED`."""

    code = "EMPLOYEE_TERMINATED"

    def __init__(
        self,
        last_working_day: date,
        message: str | None = None,
    ) -> None:
        message = message or (
            "Attendance cannot be recorded after the employee's last working day "
            f"({last_working_day.isoformat()})"
        )
        super().__init__(
            message,
            details=[
                {
                    "field": "punch_time",
                    "code": "EMPLOYEE_TERMINATED",
                    "message": message,
                    "context": {"last_working_day": last_working_day.isoformat()},
                }
            ],
        )


class PunchTimeBeforeEmploymentError(ValidationError):
    """Execution gate §8.2's "employment-start floor" — a data-integrity bound, not a policy
    choice, which is why it needed no client decision. Before this, `1900-01-01Z` was accepted
    for any employee.

    Resolved through the existing `EmploymentService.get_latest_employment_on_or_before` seam
    rather than a new query: no episode starting on or before the punch date means the punch
    predates the employee's own employment record."""

    code = "PUNCH_TIME_BEFORE_EMPLOYMENT"

    def __init__(
        self,
        message: str = (
            "punch_time predates the employee's employment — no employment episode had started "
            "on that date"
        ),
    ) -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "punch_time",
                    "code": "PUNCH_TIME_BEFORE_EMPLOYMENT",
                    "message": message,
                }
            ],
        )


class AttendanceSummaryReconciliationError(ConflictError):
    """PAY-003 — the summary about to be frozen does not reconcile (buckets != period days, or
    paid + LOP != payable days). Validation makes this unreachable; raising rolls the whole
    finalize transaction back instead of freezing figures Payroll would pay from."""

    code = "ATTENDANCE_SUMMARY_RECONCILIATION_FAILED"


class WorkOnLeaveNotFlaggedError(ConflictError):
    """BUS-012 — the day has no punches-on-leave conflict to resolve."""

    code = "ATTENDANCE_WORK_ON_LEAVE_NOT_FLAGGED"

    def __init__(self, message: str = "This attendance day has no work-on-leave conflict") -> None:
        super().__init__(message)


class AttendanceQueueUnavailableError(AppError):
    """The range calculation could not be handed to the job queue (broker unreachable). Nothing
    was queued and nothing was changed, so the client may repeat the request; the calculation is
    idempotent per day."""

    code = "ATTENDANCE_QUEUE_UNAVAILABLE"
    status_code = 503
    headers = {"Retry-After": "5"}

    def __init__(
        self,
        message: str = "The calculation could not be queued. Try again shortly",
    ) -> None:
        super().__init__(message)


class AttendanceRangeInFutureError(ValidationError):
    """PAY-001 — a backfill may not run past the company's current business date: a future day
    has no punches yet and would be computed ABSENT/INCOMPLETE."""

    code = "ATTENDANCE_RANGE_IN_FUTURE"

    def __init__(self, message: str = "date_to cannot be after today") -> None:
        super().__init__(message)


# ---------------------------------------------------------------------------
# Face attendance
# ---------------------------------------------------------------------------


class FaceVerificationUnavailableError(AppError):
    """`face_verification_provider` is `"disabled"` — face enrollment/punching is switched off
    for this deployment, not broken."""

    code = "FACE_VERIFICATION_UNAVAILABLE"
    status_code = 503

    def __init__(
        self, message: str = "Face verification is not enabled for this deployment"
    ) -> None:
        super().__init__(message)


class FaceProviderFailedError(AppError):
    """The face provider could not be reached or answered unexpectedly. Never carries the
    provider's own error text."""

    code = "FACE_PROVIDER_FAILED"
    status_code = 502

    def __init__(
        self, message: str = "Face verification service is unavailable; try again shortly"
    ) -> None:
        super().__init__(message)


class FaceProfileNotFoundError(NotFoundError):
    code = "FACE_PROFILE_NOT_FOUND"

    def __init__(self, message: str = "This employee has no face profile") -> None:
        super().__init__(message)


class FaceProfileAlreadyEnrolledError(ConflictError):
    code = "FACE_PROFILE_ALREADY_ENROLLED"

    def __init__(
        self,
        message: str = "This employee is already enrolled; revoke the profile to re-enroll",
    ) -> None:
        super().__init__(message)


class FaceProfileNotEnrolledError(ConflictError):
    code = "FACE_PROFILE_NOT_ENROLLED"

    def __init__(self, message: str = "This employee's face profile is not enrolled") -> None:
        super().__init__(message)


class FaceConsentRequiredError(ValidationError):
    code = "FACE_CONSENT_REQUIRED"

    def __init__(
        self,
        message: str = "Biometric consent must be confirmed before enrolling a face profile",
    ) -> None:
        super().__init__(
            message,
            details=[{"field": "consent_confirmed", "code": self.code, "message": message}],
        )


class FaceImageInvalidError(ValidationError):
    code = "FACE_IMAGE_INVALID"

    def __init__(self, message: str, *, field: str = "photo") -> None:
        super().__init__(message, details=[{"field": field, "code": self.code, "message": message}])


class FaceNotDetectedError(ValidationError):
    code = "FACE_NOT_DETECTED"

    def __init__(
        self,
        message: str = "No face was detected in the photo. Face the camera in good light.",
    ) -> None:
        super().__init__(
            message, details=[{"field": "photo", "code": self.code, "message": message}]
        )


class FaceProfilePendingApprovalError(ConflictError):
    code = "FACE_PROFILE_PENDING_APPROVAL"

    def __init__(self, message: str = "This face profile is waiting for HR approval") -> None:
        super().__init__(message)


class FaceEnrollmentWindowAlreadyOpenError(ConflictError):
    code = "FACE_ENROLLMENT_WINDOW_ALREADY_OPEN"

    def __init__(
        self,
        message: str = "An enrollment window is already open; cancel it first to start a new one",
    ) -> None:
        super().__init__(message)


class FaceProfileNotPendingError(ConflictError):
    code = "FACE_PROFILE_NOT_PENDING"

    def __init__(
        self, message: str = "Only a face profile waiting for approval can be approved or rejected"
    ) -> None:
        super().__init__(message)


class FaceReviewPhotoNotFoundError(NotFoundError):
    code = "FACE_REVIEW_PHOTO_NOT_FOUND"

    def __init__(self, message: str = "There is no photo awaiting review") -> None:
        super().__init__(message)


class FaceEnrollmentWindowNotOpenError(ConflictError):
    code = "FACE_ENROLLMENT_NOT_OPEN"

    def __init__(
        self,
        message: str = "Face enrollment is not open for you. Ask HR to open it.",
    ) -> None:
        super().__init__(message)


class FaceEnrollmentInProgressError(ConflictError):
    """Another submission for this employee is still being processed (its reservation is live)."""

    code = "FACE_ENROLLMENT_IN_PROGRESS"

    def __init__(
        self,
        message: str = "A face enrollment submission is already being processed. Please wait.",
    ) -> None:
        super().__init__(message)


class FaceEnrollmentWindowNotFoundError(NotFoundError):
    code = "FACE_ENROLLMENT_WINDOW_NOT_FOUND"

    def __init__(self, message: str = "There is no open face enrollment to cancel") -> None:
        super().__init__(message)


class FaceEnrollmentAngleMismatchError(ValidationError):
    """One of the turned-head captures did not match the straight-on capture (or had no face)."""

    code = "FACE_ENROLLMENT_ANGLE_MISMATCH"

    def __init__(self, angle: str) -> None:
        self.angle = angle
        message = (
            f"The '{angle}' photo did not clearly show the same face. Retake the photos in good "
            "light, turning your head only part of the way."
        )
        super().__init__(message, details=[{"field": angle, "code": self.code, "message": message}])


class FaceNotEnrolledForPunchError(ConflictError):
    code = "FACE_NOT_ENROLLED"

    def __init__(
        self, message: str = "You are not enrolled for face attendance. Ask HR to enroll you."
    ) -> None:
        super().__init__(message)


class FaceVerificationRequiredError(PermissionDeniedError):
    """A plain self-service punch from an employee whose face is ENROLLED. The only way such an
    employee punches themselves is `POST /attendance/face-punches/me`; recovery when that fails
    is an HR on-behalf correction, never a fallback to a plain punch."""

    code = "FACE_VERIFICATION_REQUIRED"

    def __init__(
        self,
        message: str = (
            "Face verification is required to punch. Use the face punch flow; if it is "
            "unavailable, ask HR to record the punch for you."
        ),
    ) -> None:
        super().__init__(message)


class FaceNotMatchedError(ValidationError):
    code = "FACE_NOT_MATCHED"

    def __init__(
        self, message: str = "Your face did not match your enrolled profile. Please try again."
    ) -> None:
        super().__init__(
            message, details=[{"field": "photo", "code": self.code, "message": message}]
        )


def _frames_error(code: str, message: str) -> list[dict[str, str]]:
    return [{"field": "frames", "code": code, "message": message}]


class FaceSpoofSuspectedError(ValidationError):
    """Server-side liveness judged a frame to be a presented photo/screen, not a live face.
    Deliberately says no more than that — the model's scores are not returned to the client."""

    code = "FACE_SPOOF_SUSPECTED"

    def __init__(
        self,
        message: str = (
            "We could not confirm a live face. Hold the phone yourself, face the camera "
            "directly in good light, and try again."
        ),
    ) -> None:
        super().__init__(message, details=_frames_error(self.code, message))


class FaceLivenessInconclusiveError(ValidationError):
    """Liveness could not decide (low confidence, or the face was too small to assess). Not a
    spoof verdict: the user simply retakes the capture."""

    code = "FACE_LIVENESS_INCONCLUSIVE"

    def __init__(
        self,
        message: str = (
            "We could not check your face clearly. Move closer, face the camera directly in "
            "good light, and try again."
        ),
    ) -> None:
        super().__init__(message, details=_frames_error(self.code, message))


class FaceMultipleFacesError(ValidationError):
    code = "FACE_MULTIPLE_FACES"

    def __init__(
        self, message: str = "More than one face was detected. Make sure only you are in frame."
    ) -> None:
        super().__init__(message, details=_frames_error(self.code, message))


class FaceLivenessUnavailableError(AppError):
    """Server-side liveness is disabled for this deployment, or its model could not be loaded/
    verified. Face punching fails closed: there is no fallback to "face detected = live"."""

    code = "FACE_LIVENESS_UNAVAILABLE"
    status_code = 503

    def __init__(
        self, message: str = "Face attendance is temporarily unavailable; use another punch method"
    ) -> None:
        super().__init__(message)


class FaceLivenessTimeoutError(AppError):
    code = "FACE_LIVENESS_TIMEOUT"
    status_code = 503

    def __init__(
        self, message: str = "Face check took too long; please try again in a moment"
    ) -> None:
        super().__init__(message)


class FaceLivenessChallengeRequiredError(ValidationError):
    """A face punch arrived without a server-issued challenge or without the required frames —
    typically an outdated app."""

    code = "FACE_LIVENESS_CHALLENGE_REQUIRED"

    def __init__(
        self,
        message: str = (
            "This face punch needs a liveness check from the current app. Update the app and "
            "try again."
        ),
    ) -> None:
        super().__init__(
            message,
            details=[{"field": "liveness_session_id", "code": self.code, "message": message}],
        )


class FaceLivenessChallengeInvalidError(ValidationError):
    """Unknown id, another employee's challenge, a superseded one, or one issued for the other
    punch direction — deliberately indistinguishable to the caller."""

    code = "FACE_LIVENESS_CHALLENGE_INVALID"

    def __init__(
        self, message: str = "This face check is not valid. Start the face punch again."
    ) -> None:
        super().__init__(
            message,
            details=[{"field": "liveness_session_id", "code": self.code, "message": message}],
        )


class FaceLivenessChallengeExpiredError(ConflictError):
    code = "FACE_LIVENESS_CHALLENGE_EXPIRED"

    def __init__(
        self, message: str = "This face check expired. Start the face punch again."
    ) -> None:
        super().__init__(message)


class FaceLivenessChallengeUsedError(ConflictError):
    code = "FACE_LIVENESS_CHALLENGE_USED"

    def __init__(
        self, message: str = "This face check was already used. Start the face punch again."
    ) -> None:
        super().__init__(message)


class FaceCaptureReplayedError(ValidationError):
    """A submitted frame is byte-identical to one presented in an earlier challenge, or the same
    frame was sent twice — a replayed capture, not a fresh one."""

    code = "FACE_CAPTURE_REPLAYED"

    def __init__(
        self, message: str = "These photos were already used. Take a new face capture."
    ) -> None:
        super().__init__(message, details=_frames_error(self.code, message))


class FacePunchAttemptsExceededError(AppError):
    code = "FACE_ATTEMPTS_EXCEEDED"
    status_code = 429

    def __init__(self, window_minutes: int) -> None:
        super().__init__(
            f"Too many failed face attempts. Try again in {window_minutes} minutes or ask HR "
            "to record your punch.",
            headers={"Retry-After": str(window_minutes * 60)},
        )


class FaceEnrollmentAttemptsExceededError(AppError):
    """Too many rejected self-enrollment submissions in one HR-opened window. Carries no detail
    about why earlier ones were rejected; HR reopening the window starts a fresh count."""

    code = "FACE_ENROLLMENT_ATTEMPTS_EXCEEDED"
    status_code = 429

    def __init__(self) -> None:
        super().__init__(
            "Too many unsuccessful face enrollment attempts. Ask HR to open a new enrollment "
            "window."
        )


class LeaveProjectionOutsideEmploymentError(ValidationError):
    """D3 / LM-14 - a leave day cannot be projected onto a date the employee has no employment
    covering (before joining, after the last working day, in a rehire gap, or with no employment
    row). Closes the direct `POST /leave-projections` path as well as the approval path, so
    neither can publish leave the Leave module would have refused."""

    code = "LEAVE_PROJECTION_OUTSIDE_EMPLOYMENT"

    def __init__(self, *, reason: str, offending_date: date) -> None:
        message = f"Leave cannot be projected onto {offending_date.isoformat()}: {reason}"
        super().__init__(
            message,
            details=[
                {
                    "field": "attendance_date",
                    "code": self.code,
                    "message": message,
                    "context": {"reason": reason},
                }
            ],
        )


class LeaveProjectionApplicationNotFoundError(NotFoundError):
    """LM-14 - the leave application a projection names does not exist for this company and
    employee. One error for "no such id", "another company's id" and "another employee's id", so
    the response never reveals whether a foreign application exists."""

    code = "LEAVE_PROJECTION_APPLICATION_NOT_FOUND"

    def __init__(self, message: str = "Leave application not found for this employee") -> None:
        super().__init__(message)


class LeaveProjectionApplicationNotApprovedError(ConflictError):
    """LM-14 - only an `APPROVED` leave application can back a projection; a submitted, rejected
    or cancelled one must never create or revive an active projection."""

    code = "LEAVE_PROJECTION_APPLICATION_NOT_APPROVED"

    def __init__(self, *, status: str) -> None:
        message = f"Leave application is {status}, not APPROVED, so it cannot be projected"
        super().__init__(
            message,
            details=[{"field": "leave_application_id", "code": self.code, "message": message}],
        )


class LeaveProjectionDateNotInApplicationError(ValidationError):
    """LM-14 - the application has no `LeaveApplicationDay` for the requested date."""

    code = "LEAVE_PROJECTION_DATE_NOT_IN_APPLICATION"

    def __init__(self, *, offending_date: date) -> None:
        message = f"Leave application does not cover {offending_date.isoformat()}"
        super().__init__(
            message,
            details=[{"field": "attendance_date", "code": self.code, "message": message}],
        )


# ---------------------------------------------------------------------------
# Geofencing
# ---------------------------------------------------------------------------

#: Employee-facing text per outcome. Deliberately contains no coordinates.
GEOFENCE_MESSAGES = {
    "OUTSIDE_GEOFENCE": (
        "You appear to be outside an approved workplace, so this punch was not recorded."
    ),
    "OUTSIDE_GEOFENCE_UNCERTAIN": (
        "Your location is just outside an approved workplace and the GPS reading is not precise "
        "enough to be sure. Move to an open area, wait for a better signal and try again."
    ),
    "LOCATION_TOO_INACCURATE": (
        "Your device's location is not accurate enough. Enable precise location, move to an "
        "open area and try again."
    ),
    "LOCATION_STALE": "The location reading is too old. Try again to get a fresh reading.",
    "LOCATION_INVALID": "The location reading was not valid. Try again.",
    "LOCATION_REQUIRED": "Your company requires your location to record attendance.",
    "LOCATION_UNAVAILABLE_CLIENT": (
        "Your device could not provide its location. Turn on location services, allow location "
        "access for this app and try again, or contact HR."
    ),
    "NO_APPLICABLE_WORKPLACE": (
        "No approved workplace is configured for you. Contact HR to have your workplace set up."
    ),
}


class GeofenceRejectedError(AppError):
    """A self-service punch was refused by the geofence policy. 422: the request was understood
    but this location/timing cannot be accepted; the client may retry with a better fix.
    `details[0]` carries the machine-readable outcome and the (coordinate-free) measurements."""

    status_code = 422

    def __init__(
        self,
        outcome: str,
        *,
        distance_m: float | None = None,
        radius_m: float | None = None,
        accuracy_m: float | None = None,
        workplace_name: str | None = None,
    ) -> None:
        self.outcome = outcome
        message = GEOFENCE_MESSAGES.get(outcome, "This punch was refused by the location policy.")
        context: dict[str, Any] = {}
        if distance_m is not None:
            context["distance_m"] = distance_m
        if radius_m is not None:
            context["radius_m"] = radius_m
        if accuracy_m is not None:
            context["accuracy_m"] = accuracy_m
        if workplace_name is not None:
            context["workplace_name"] = workplace_name
        detail: dict[str, Any] = {
            "field": "location",
            "code": outcome,
            "message": message,
            "context": context or None,
        }
        super().__init__(message, code=f"PUNCH_{outcome}", details=[detail])


class OutsideShiftWindowError(AppError):
    """A self-service punch-in was refused because it is earlier than the policy's early-in
    allowance before the employee's shift. 422, like the geofence refusal. `details[0].context`
    carries the shift times (ISO-8601 UTC instants) and the policy values, nothing else."""

    status_code = 422
    code = "OUTSIDE_SHIFT_WINDOW"

    def __init__(
        self,
        *,
        shift_start: datetime,
        shift_end: datetime,
        grace_in_minutes: int,
        grace_out_minutes: int,
        early_in_allowance_minutes: int,
        earliest_punch_in: datetime,
    ) -> None:
        message = "It is too early to punch in for your shift."
        context: dict[str, Any] = {
            "shift_start": shift_start.isoformat(),
            "shift_end": shift_end.isoformat(),
            "grace_in_minutes": grace_in_minutes,
            "grace_out_minutes": grace_out_minutes,
            "early_in_allowance_minutes": early_in_allowance_minutes,
            "earliest_punch_in": earliest_punch_in.isoformat(),
        }
        detail: dict[str, Any] = {
            "field": "punch_time",
            "code": self.code,
            "message": message,
            "context": context,
        }
        super().__init__(message, details=[detail])


class WorkplaceAuthorizationExistsError(ConflictError):
    code = "WORKPLACE_AUTHORIZATION_EXISTS"

    def __init__(self) -> None:
        super().__init__("This employee is already authorised for that workplace")
