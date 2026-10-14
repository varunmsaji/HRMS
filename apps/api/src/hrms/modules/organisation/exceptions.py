"""Module-specific AppError subclasses for the organisation module."""

from typing import Any

from hrms.core.errors.base import ConflictError, LockedError, NotFoundError, ValidationError


class TimezoneChangeBlockedError(ConflictError):
    """`DEC-TZ-04` (SELECTED) — once any computed attendance exists for the affected scope, a
    company or branch timezone cannot be edited through the ordinary profile/branch-settings
    screen (execution gate §12). Historical attendance is payroll evidence; a silent timezone
    edit would reinterpret already-finalized hours under a different clock the next time they
    are recomputed. A genuine correction is a deliberate, audited, one-off procedure, not an
    ordinary settings PATCH."""

    code = "TIMEZONE_CHANGE_BLOCKED"

    def __init__(
        self,
        message: str = (
            "timezone cannot be changed — computed attendance already exists for this scope"
        ),
    ) -> None:
        super().__init__(
            message,
            details=[{"field": "timezone", "code": "TIMEZONE_CHANGE_BLOCKED", "message": message}],
        )


class CurrencyLockedError(ValidationError):
    code = "CURRENCY_LOCKED"

    def __init__(self, message: str = "Currency cannot be changed after trial") -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "currency",
                    "code": "CURRENCY_LOCKED",
                    "message": message,
                }
            ],
        )


class InvalidWorkingDaysError(ValidationError):
    code = "INVALID_WORKING_DAYS"

    def __init__(self, message: str = "At least one working day is required") -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "working_days",
                    "code": "INVALID_WORKING_DAYS",
                    "message": message,
                }
            ],
        )


class CompanyWriteBlockedError(LockedError):
    """Raised when a write is blocked by company lifecycle status (e.g. SUSPENDED)."""

    def __init__(self, message: str = "Company is suspended and cannot be modified") -> None:
        super().__init__(message, code="LOCKED")


class CompanyLimitReachedError(ConflictError):
    """Initial release allows a single company per tenant (any number of branches)."""

    code = "COMPANY_LIMIT_REACHED"

    def __init__(self, *, limit: int) -> None:
        message = (
            "Only one company can be added. Add more branches under your existing company instead."
            if limit == 1
            else f"At most {limit} companies can be added."
        )
        super().__init__(
            message,
            details=[{"field": "name", "code": "COMPANY_LIMIT_REACHED", "message": message}],
        )


class LegalEntityDeactivationBlockedError(ConflictError):
    """FR-ORG-014 — never hard-delete; deactivation is blocked while active Branch rows
    still reference this legal entity."""

    code = "LEGAL_ENTITY_HAS_ACTIVE_BRANCHES"

    def __init__(self, *, active_branch_count: int) -> None:
        message = "This legal entity cannot be deactivated while it has active branches"
        super().__init__(
            message,
            details=[
                {
                    "field": "is_active",
                    "code": "LEGAL_ENTITY_HAS_ACTIVE_BRANCHES",
                    "message": message,
                    "context": {"active_branch_count": active_branch_count},
                }
            ],
        )


class BranchDeactivationBlockedError(ConflictError):
    """FR-ORG-014 — never hard-delete; deactivation is blocked while active Department rows
    still reference this branch. (The Employee half of FR-ORG-014 is out of scope: Employee
    does not exist yet.)"""

    code = "BRANCH_HAS_ACTIVE_DEPARTMENTS"

    def __init__(self, *, active_department_count: int) -> None:
        message = "This branch cannot be deactivated while it has active departments"
        super().__init__(
            message,
            details=[
                {
                    "field": "is_active",
                    "code": "BRANCH_HAS_ACTIVE_DEPARTMENTS",
                    "message": message,
                    "context": {"active_department_count": active_department_count},
                }
            ],
        )


class MasterDataInUseError(ConflictError):
    """Deactivating a branch, department, designation, grade or shift is refused while active
    employees are still assigned to it — they must be reassigned first. Nothing is reassigned
    automatically and no replacement is guessed."""

    code = "MASTER_DATA_HAS_ACTIVE_EMPLOYEES"

    def __init__(self, *, kind: str, active_employee_count: int) -> None:
        message = (
            f"This {kind} cannot be deactivated while active employees are assigned to it; "
            "reassign them first"
        )
        super().__init__(
            message,
            details=[
                {
                    "field": "is_active",
                    "code": "MASTER_DATA_HAS_ACTIVE_EMPLOYEES",
                    "message": message,
                    "context": {"kind": kind, "active_employee_count": active_employee_count},
                }
            ],
        )


class InvalidLegalEntityError(ValidationError):
    """Raised when a Branch is created/updated against a `legal_entity_id` that does not
    exist, is soft-deleted, or belongs to a different tenant — the FK constraint alone
    would surface an opaque `IntegrityError`/500, not the documented 422 envelope."""

    code = "INVALID_LEGAL_ENTITY"

    def __init__(
        self, message: str = "legal_entity_id does not reference a valid legal entity"
    ) -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "legal_entity_id",
                    "code": "INVALID_LEGAL_ENTITY",
                    "message": message,
                }
            ],
        )


class InvalidBranchError(ValidationError):
    """Raised when a Department is created/updated against a `branch_id` that does not
    exist, is soft-deleted, or belongs to a different tenant — mirrors
    `InvalidLegalEntityError` for Branch's own `legal_entity_id`."""

    code = "INVALID_BRANCH"

    def __init__(self, message: str = "branch_id does not reference a valid branch") -> None:
        super().__init__(
            message,
            details=[{"field": "branch_id", "code": "INVALID_BRANCH", "message": message}],
        )


class InvalidParentDepartmentError(ValidationError):
    """Raised when a Department's `parent_id` does not exist, is soft-deleted, or belongs
    to a different tenant."""

    code = "INVALID_PARENT_DEPARTMENT"

    def __init__(self, message: str = "parent_id does not reference a valid department") -> None:
        super().__init__(
            message,
            details=[
                {"field": "parent_id", "code": "INVALID_PARENT_DEPARTMENT", "message": message}
            ],
        )


class InvalidDepartmentHeadError(ValidationError):
    """Raised when a Department's `head_employee_id` does not exist or belongs to a
    different tenant — mirrors `InvalidBranchError` for Department's own `branch_id`."""

    code = "INVALID_DEPARTMENT_HEAD"

    def __init__(
        self, message: str = "head_employee_id does not reference a valid employee"
    ) -> None:
        super().__init__(
            message,
            details=[{"field": "head_employee_id", "code": self.code, "message": message}],
        )


class InvalidDepartmentError(ValidationError):
    """Raised when a Designation is created/updated against a `department_id` that does not
    exist, is soft-deleted, or belongs to a different tenant — mirrors `InvalidBranchError`
    for Department's own `branch_id`."""

    code = "INVALID_DEPARTMENT"

    def __init__(
        self, message: str = "department_id does not reference a valid department"
    ) -> None:
        super().__init__(
            message,
            details=[{"field": "department_id", "code": "INVALID_DEPARTMENT", "message": message}],
        )


class InvalidGradeError(ValidationError):
    """Raised when a Designation is created/updated against a `grade_id` that does not
    exist, is soft-deleted, or belongs to a different tenant — mirrors
    `InvalidDepartmentError` for Designation's own `department_id`."""

    code = "INVALID_GRADE"

    def __init__(self, message: str = "grade_id does not reference a valid grade") -> None:
        super().__init__(
            message,
            details=[{"field": "grade_id", "code": "INVALID_GRADE", "message": message}],
        )


class InvalidCtcRangeError(ValidationError):
    """Sprint 3 Task 3.3.1's own documented rule: `min_ctc <= max_ctc` when both are
    present (docs/modules/grade/00_GRADE_AUDIT.md §6.4)."""

    code = "INVALID_CTC_RANGE"

    def __init__(self, message: str = "min_ctc must not be greater than max_ctc") -> None:
        super().__init__(
            message,
            details=[{"field": "max_ctc", "code": "INVALID_CTC_RANGE", "message": message}],
        )


class GradeCodeAlreadyExistsError(ConflictError):
    """The `grade` table already carries a `UNIQUE (company_id, code)` constraint
    (predates this slice, scripts/sql/001_init_schema.sql) — this converts the resulting
    `IntegrityError` into the documented error envelope rather than a raw 500, mirroring how
    `register_company` converts a duplicate-email `IntegrityError` into `ConflictError`."""

    code = "GRADE_CODE_ALREADY_EXISTS"

    def __init__(self, message: str = "A grade with this code already exists") -> None:
        super().__init__(
            message,
            details=[{"field": "code", "code": "GRADE_CODE_ALREADY_EXISTS", "message": message}],
        )


class DepartmentCycleDetectedError(ConflictError):
    """FR-ORG-005 — the department hierarchy must never contain a cycle. Raised when the
    candidate `parent_id` is the department itself or one of its own descendants."""

    code = "DEPARTMENT_CYCLE_DETECTED"

    def __init__(
        self, message: str = "This parent department would create a cycle in the hierarchy"
    ) -> None:
        super().__init__(
            message,
            details=[
                {"field": "parent_id", "code": "DEPARTMENT_CYCLE_DETECTED", "message": message}
            ],
        )


class DepartmentMaxDepthExceededError(ConflictError):
    """FR-ORG-005 — the department hierarchy is capped at 5 levels."""

    code = "DEPARTMENT_MAX_DEPTH_EXCEEDED"

    def __init__(
        self, message: str = "This parent department would exceed the maximum hierarchy depth of 5"
    ) -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "parent_id",
                    "code": "DEPARTMENT_MAX_DEPTH_EXCEEDED",
                    "message": message,
                }
            ],
        )


class StaleResourceError(ConflictError):
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


class HolidayCalendarCodeAlreadyExistsError(ConflictError):
    """`holiday_calendar` carries a partial unique index on `(company_id, code)` (migration
    `20260818090000_holiday_calendar_expand`) — converts the resulting `IntegrityError` into
    the documented error envelope, mirroring `GradeCodeAlreadyExistsError`."""

    code = "HOLIDAY_CALENDAR_CODE_ALREADY_EXISTS"

    def __init__(self, message: str = "A holiday calendar with this code already exists") -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "code",
                    "code": "HOLIDAY_CALENDAR_CODE_ALREADY_EXISTS",
                    "message": message,
                }
            ],
        )


class HolidayDateAlreadyExistsError(ConflictError):
    """`holiday` carries a partial unique index on `(calendar_id, date)` for active rows
    (migration `20260818100000_holiday_expand`) — at most one active holiday per date per
    calendar."""

    code = "HOLIDAY_DATE_ALREADY_EXISTS"

    def __init__(
        self, message: str = "This calendar already has an active holiday on this date"
    ) -> None:
        super().__init__(
            message,
            details=[{"field": "date", "code": "HOLIDAY_DATE_ALREADY_EXISTS", "message": message}],
        )


class InvalidHolidayCalendarError(ValidationError):
    """Raised when a Holiday is created against a `calendar_id` that does not exist, is
    soft-deleted, or belongs to a different tenant."""

    code = "INVALID_HOLIDAY_CALENDAR"

    def __init__(
        self, message: str = "calendar_id does not reference a valid holiday calendar"
    ) -> None:
        super().__init__(
            message,
            details=[
                {"field": "calendar_id", "code": "INVALID_HOLIDAY_CALENDAR", "message": message}
            ],
        )


class WeeklyOffRuleInvalidError(ValidationError):
    """Raised when a `WeeklyOffRule` shape doesn't match its parent `pattern_kind`
    (architecture §8.1) — e.g. `NTH_WEEKDAY` without `nth_in_month`, or `ALTERNATE` without
    `cycle_start_date`."""

    code = "WEEKLY_OFF_RULE_INVALID"

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            details=[{"field": "rules", "code": "WEEKLY_OFF_RULE_INVALID", "message": message}],
        )


class WorkCalendarCompositionInvalidError(ValidationError):
    """Raised when a WorkCalendar's `holiday_calendar_ids` or `weekly_off_pattern_id`
    reference calendars/patterns that don't exist, are soft-deleted, or belong to a different
    tenant."""

    code = "WORK_CALENDAR_COMPOSITION_INVALID"

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "holiday_calendar_ids",
                    "code": "WORK_CALENDAR_COMPOSITION_INVALID",
                    "message": message,
                }
            ],
        )


class WorkCalendarDeactivationBlockedError(ConflictError):
    """Architecture §4.2 WorkCalendar table: "Blocked if referenced by an open assignment or
    current branch default." — mirrors `BranchDeactivationBlockedError`."""

    code = "WORK_CALENDAR_HAS_ACTIVE_ASSIGNMENTS"

    def __init__(self, *, active_assignment_count: int) -> None:
        message = "This work calendar cannot be deactivated while it has active assignments"
        super().__init__(
            message,
            details=[
                {
                    "field": "is_active",
                    "code": "WORK_CALENDAR_HAS_ACTIVE_ASSIGNMENTS",
                    "message": message,
                    "context": {"active_assignment_count": active_assignment_count},
                }
            ],
        )


class CalendarExceptionDateConflictError(ConflictError):
    """`calendar_exception` carries a partial unique index on `(work_calendar_id,
    exception_date)` for active rows (migration `20260818120000_work_calendar`) — at most one
    active exception per date per calendar. Correcting one is deactivate-then-insert."""

    code = "CALENDAR_EXCEPTION_DATE_CONFLICT"

    def __init__(
        self,
        message: str = "This work calendar already has an active exception on this date",
    ) -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "exception_date",
                    "code": "CALENDAR_EXCEPTION_DATE_CONFLICT",
                    "message": message,
                }
            ],
        )


class InvalidWorkCalendarError(ValidationError):
    """Raised when a CalendarException is created against a `work_calendar_id` that does not
    exist, is soft-deleted, or belongs to a different tenant."""

    code = "INVALID_WORK_CALENDAR"

    def __init__(
        self, message: str = "work_calendar_id does not reference a valid work calendar"
    ) -> None:
        super().__init__(
            message,
            details=[
                {"field": "work_calendar_id", "code": "INVALID_WORK_CALENDAR", "message": message}
            ],
        )


class PolicyKindNotSupportedError(ValidationError):
    """Guards the W1-restricted `policy_kind` CHECK constraint (migration
    `20260818130000_policy_assignment`) at the service layer with a clean 4xx, instead of
    letting a caller who sends e.g. `ATTENDANCE_POLICY` hit a raw DB constraint violation.
    `ATTENDANCE_POLICY`/`OVERTIME_POLICY`/`REGULARIZATION_POLICY` ship in W3 (see WD-24)."""

    code = "POLICY_KIND_NOT_SUPPORTED"

    def __init__(self, policy_kind: str) -> None:
        message = f"policy_kind '{policy_kind}' is not supported in this slice"
        super().__init__(
            message,
            details=[
                {"field": "policy_kind", "code": "POLICY_KIND_NOT_SUPPORTED", "message": message}
            ],
        )


class InvalidPolicyReferenceError(ValidationError):
    """Raised when `policy_id` does not reference an existing, same-tenant row of the table
    implied by `policy_kind` (`work_calendar` for `WORK_CALENDAR`, `weekly_off_pattern` for
    `WEEKLY_OFF`) — `policy_id` has no DB-level FK since it is polymorphic (mirrors
    `audit_log.entity_id`), so this check is entirely service-layer."""

    code = "INVALID_POLICY_REFERENCE"

    def __init__(self, message: str = "policy_id does not reference a valid policy") -> None:
        super().__init__(
            message,
            details=[
                {"field": "policy_id", "code": "INVALID_POLICY_REFERENCE", "message": message}
            ],
        )


class PolicyAssignmentOverlapError(ConflictError):
    """`policy_assignment_no_overlap` (GiST exclusion, migration
    `20260818130000_policy_assignment`) is the race-condition backstop — this converts the
    resulting `IntegrityError` into the documented envelope, mirroring
    `AssignmentDatesOverlapError` in the employee module."""

    code = "POLICY_ASSIGNMENT_OVERLAP"

    def __init__(
        self,
        message: str = (
            "Another assignment of this kind already covers part of this date range at this scope"
        ),
    ) -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "effective_from",
                    "code": "POLICY_ASSIGNMENT_OVERLAP",
                    "message": message,
                }
            ],
        )


class PolicyAssignmentVersionRequiredError(ValidationError):
    """Mirrors `AssignmentVersionRequiredError` — when a current (open) assignment already
    exists at this exact `(policy_kind, scope_type, scope_id)`, the caller must supply
    `expected_version` so the previous row can be closed."""

    code = "POLICY_ASSIGNMENT_VERSION_REQUIRED"

    def __init__(
        self,
        message: str = (
            "expected_version is required to replace an existing assignment at this scope"
        ),
    ) -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "expected_version",
                    "code": "POLICY_ASSIGNMENT_VERSION_REQUIRED",
                    "message": message,
                }
            ],
        )


# ---------------------------------------------------------------------------
# Shift + Break System (W2) — ShiftVersion/ShiftBreak/ShiftDutyBlock.
# docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md §9-§10.
# ---------------------------------------------------------------------------


class InvalidShiftVersionTimeRangeError(ValidationError):
    """FIXED shift type: `start_time`/`end_time` must differ — unlike the legacy `Shift`
    (which had a client-settable `is_cross_midnight` flag to disambiguate), `ShiftVersion`
    derives cross-midnight server-side from the time comparison, so an equal start/end pair is
    inherently ambiguous (zero-length vs. full 24h shift) and rejected."""

    code = "INVALID_SHIFT_VERSION_TIME_RANGE"

    def __init__(
        self, message: str = "end_time must differ from start_time for a FIXED shift"
    ) -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "end_time",
                    "code": "INVALID_SHIFT_VERSION_TIME_RANGE",
                    "message": message,
                }
            ],
        )


class InvalidShiftVersionFlexWindowError(ValidationError):
    """FLEXIBLE shift type: `window_start`/`window_end` are required and must describe a
    sane (non-empty) window."""

    code = "INVALID_SHIFT_VERSION_FLEX_WINDOW"

    def __init__(
        self,
        message: str = "window_start and window_end are required and window_end must be "
        "after window_start for a FLEXIBLE shift",
        *,
        field: str = "window_end",
    ) -> None:
        super().__init__(
            message,
            details=[
                {"field": field, "code": "INVALID_SHIFT_VERSION_FLEX_WINDOW", "message": message}
            ],
        )


class InvalidShiftVersionCoreHoursError(ValidationError):
    """FLEXIBLE shift type: `core_start`/`core_end` must be given together (not just one), and
    when given must describe a sane (non-empty) range. They are NOT required to nest inside
    `window_start`/`window_end` — architecture §9.4 describes the window as the *start-time*
    flexibility range ("07:00-10:00 start"), not the whole working span; core hours are a
    separate, independently-positioned block."""

    code = "INVALID_SHIFT_VERSION_CORE_HOURS"

    def __init__(self, message: str = "core_end must be after core_start") -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "core_end",
                    "code": "INVALID_SHIFT_VERSION_CORE_HOURS",
                    "message": message,
                }
            ],
        )


class InvalidShiftVersionDutyBlockCountError(ValidationError):
    """SPLIT shift type: at least 2 duty blocks are required, but only checked at *publish*
    time — a draft may be incomplete mid-edit (can't be a DB CHECK, it counts child rows)."""

    code = "INVALID_SHIFT_VERSION_DUTY_BLOCK_COUNT"

    def __init__(
        self, message: str = "A SPLIT shift requires at least 2 duty blocks to publish"
    ) -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "duty_blocks",
                    "code": "INVALID_SHIFT_VERSION_DUTY_BLOCK_COUNT",
                    "message": message,
                }
            ],
        )


class InvalidShiftVersionDutyBlockSequenceError(ValidationError):
    """SPLIT shift type: `sequence` across duty blocks must be contiguous starting at 1, no
    gaps or duplicates."""

    code = "INVALID_SHIFT_VERSION_DUTY_BLOCK_SEQUENCE"

    def __init__(
        self,
        message: str = "duty_blocks sequence must be contiguous starting at 1",
        *,
        index: int | None = None,
    ) -> None:
        field = f"duty_blocks.{index}.sequence" if index is not None else "duty_blocks"
        super().__init__(
            message,
            details=[
                {
                    "field": field,
                    "code": "INVALID_SHIFT_VERSION_DUTY_BLOCK_SEQUENCE",
                    "message": message,
                }
            ],
        )


class InvalidShiftVersionDutyBlockOverlapError(ValidationError):
    """SPLIT shift type: duty blocks must not overlap one another (midnight-crossing blocks
    compared as wrapped intervals)."""

    code = "INVALID_SHIFT_VERSION_DUTY_BLOCK_OVERLAP"

    def __init__(
        self,
        message: str = "duty_blocks must not overlap one another",
        *,
        index: int | None = None,
    ) -> None:
        field = f"duty_blocks.{index}" if index is not None else "duty_blocks"
        super().__init__(
            message,
            details=[
                {
                    "field": field,
                    "code": "INVALID_SHIFT_VERSION_DUTY_BLOCK_OVERLAP",
                    "message": message,
                }
            ],
        )


class InvalidShiftBreakError(ValidationError):
    """A break's fields don't match its `break_kind` (`FIXED_WINDOW` needs `start_time`/
    `end_time`; `FLEXIBLE_DURATION` needs `window_start`/`window_end`/`min_minutes`/
    `max_minutes`), or `min_minutes` exceeds `scheduled_minutes` when both are given."""

    code = "INVALID_SHIFT_BREAK"

    def __init__(self, message: str, *, index: int | None = None, field: str | None = None) -> None:
        resolved_field = field or ("breaks" if index is None else f"breaks.{index}")
        super().__init__(
            message,
            details=[{"field": resolved_field, "code": "INVALID_SHIFT_BREAK", "message": message}],
        )


class InvalidShiftBreakOverlapError(ValidationError):
    """`FIXED_WINDOW` breaks on the same `ShiftVersion` must not overlap one another.
    `FLEXIBLE_DURATION` breaks (a window the break *may* occur within, not a fixed occupied
    slot) are excluded from this check, per the W2 plan."""

    code = "INVALID_SHIFT_BREAK_OVERLAP"

    def __init__(
        self,
        message: str = "FIXED_WINDOW breaks must not overlap one another",
        *,
        index: int | None = None,
    ) -> None:
        field = f"breaks.{index}" if index is not None else "breaks"
        super().__init__(
            message,
            details=[{"field": field, "code": "INVALID_SHIFT_BREAK_OVERLAP", "message": message}],
        )


class InvalidShiftVersionTypeCombinationError(ValidationError):
    """A field only meaningful for a different `shift_type` was populated (e.g. `window_start`
    on a FIXED version, or `start_time` on a FLEXIBLE one) — a friendly service-layer surface
    for what would otherwise be an opaque DB CHECK violation
    (`shift_version_published_required_check`)."""

    code = "INVALID_SHIFT_VERSION_TYPE_COMBINATION"

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "shift_type",
                    "code": "INVALID_SHIFT_VERSION_TYPE_COMBINATION",
                    "message": message,
                }
            ],
        )


class InvalidShiftVersionEffectiveFromError(ValidationError):
    """Mirrors `create_policy_assignment`'s inline effective_from check — when publishing and
    an open published version already exists, the new `effective_from` must be strictly after
    the current version's `effective_from`."""

    code = "INVALID_SHIFT_VERSION_EFFECTIVE_FROM"

    def __init__(
        self,
        message: str = (
            "effective_from must be after the current published version's effective_from"
        ),
    ) -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "effective_from",
                    "code": "INVALID_SHIFT_VERSION_EFFECTIVE_FROM",
                    "message": message,
                }
            ],
        )


class ShiftVersionDraftAlreadyExistsError(ConflictError):
    """`shift_version_one_open_draft_idx` (partial unique index) is the DB-level backstop —
    this is the friendly pre-check surface for `POST /shifts/{id}/versions`."""

    code = "SHIFT_VERSION_DRAFT_ALREADY_EXISTS"

    def __init__(self, message: str = "This shift already has an open draft version") -> None:
        super().__init__(
            message,
            details=[
                {
                    "field": "status",
                    "code": "SHIFT_VERSION_DRAFT_ALREADY_EXISTS",
                    "message": message,
                }
            ],
        )


class ShiftVersionNotDraftError(ConflictError):
    """PATCH/DELETE/publish against a `ShiftVersion` that is no longer `DRAFT` — published
    versions are immutable except for `effective_to`, which only the publish flow itself sets."""

    code = "SHIFT_VERSION_NOT_DRAFT"

    def __init__(self, message: str = "This shift version is no longer a draft") -> None:
        super().__init__(
            message,
            details=[{"field": "status", "code": "SHIFT_VERSION_NOT_DRAFT", "message": message}],
        )


class ShiftVersionPreviousVersionRequiredError(ValidationError):
    """Mirrors `PolicyAssignmentVersionRequiredError` — when an open PUBLISHED version already
    exists for this shift, the caller must supply `expected_previous_version` so it can be
    closed as part of this publish."""

    code = "SHIFT_VERSION_PREVIOUS_VERSION_REQUIRED"

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
                    "code": "SHIFT_VERSION_PREVIOUS_VERSION_REQUIRED",
                    "message": message,
                }
            ],
        )


class ShiftVersionOverlapError(ConflictError):
    """`shift_version_no_overlap` (GiST exclusion) is the race-condition backstop — converts
    the resulting `IntegrityError` into the documented envelope, mirroring
    `PolicyAssignmentOverlapError`."""

    code = "SHIFT_VERSION_OVERLAP"

    def __init__(
        self,
        message: str = (
            "Another published version of this shift already covers part of this date range"
        ),
    ) -> None:
        super().__init__(
            message,
            details=[
                {"field": "effective_from", "code": "SHIFT_VERSION_OVERLAP", "message": message}
            ],
        )


class ShiftVersionNotFoundForDateError(NotFoundError):
    """`GET /shifts/{id}/versions/resolve?as_of=` found no PUBLISHED version covering that
    date."""

    code = "SHIFT_VERSION_NOT_FOUND_FOR_DATE"

    def __init__(self, message: str = "No published shift version covers this date") -> None:
        super().__init__(message)


class InvalidPolicyScopeError(ValidationError):
    """`scope_id` does not reference an existing, same-tenant record of the table implied by
    `scope_type`. `scope_id` is polymorphic (no DB foreign key), so without this check a typo —
    or another company's id — would be stored and silently never match anyone."""

    code = "INVALID_POLICY_SCOPE"

    def __init__(self, message: str = "scope_id does not reference a valid record") -> None:
        super().__init__(
            message, details=[{"field": "scope_id", "code": self.code, "message": message}]
        )
