"""Pydantic request/response shapes for the attendance module (W3)."""

import calendar
from datetime import date, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING, Annotated, Any
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


def _reject_non_string_instant(value: Any) -> Any:
    """`ED-5` — the wire contract for any client-supplied attendance instant is *"ISO-8601 string
    with an explicit offset"*, and `AwareDatetime` alone does not deliver it.

    `AwareDatetime` correctly rejects a naive string (`"2026-09-15T09:00:00"`) and a date-only
    string (`"2026-09-15"`), but **accepts an epoch integer**: Pydantic v2 reads an `int` as Unix
    epoch seconds, and the resulting datetime is genuinely timezone-aware, so the annotation has
    nothing to object to — `punch_time: 0` would silently become `1970-01-01T00:00:00Z`.

    Rejecting anything that is not a `str` before parsing closes that, and also rejects a float
    epoch and a `{"$date": ...}`-style object. A real `datetime` instance is allowed through so
    server-side construction of these models (tests, internal callers) still works — only
    *wire* input is constrained, and wire input is always JSON-decoded to `str`/`int`/`float`."""
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        # noqa rationale: TRY004 suggests TypeError for a type check, but this runs inside a
        # Pydantic `BeforeValidator`, which converts only `ValueError`/`AssertionError` into a
        # 422. A `TypeError` here would escape as an unhandled 500 — exactly the failure mode
        # this whole phase exists to remove.
        raise ValueError(  # noqa: TRY004
            "must be an ISO-8601 datetime string with an explicit UTC offset "
            "(e.g. 2026-09-15T09:00:00+05:30) — numeric epoch values are not accepted"
        )
    return value


AwareIsoDatetime = Annotated[AwareDatetime, BeforeValidator(_reject_non_string_instant)]

if TYPE_CHECKING:
    from hrms.modules.attendance.models import (
        AttendanceBreak,
        AttendanceDay,
        AttendancePeriod,
        AttendancePeriodAction,
        AttendancePeriodSummary,
        AttendancePolicy,
        AttendancePolicyEarlyDepartureBand,
        AttendancePolicyHourBand,
        AttendancePolicyLateBand,
        AttendancePolicyVersion,
        AttendanceRegularizationAction,
        AttendanceRegularizationRequest,
        AttendanceRegularizationRequestedPunch,
        EmployeeFaceProfile,
        FaceEnrollmentWindow,
        LeaveDayProjection,
        OvertimeAction,
        OvertimePolicy,
        OvertimePolicyRateRow,
        OvertimePolicyVersion,
        OvertimeRecord,
        Punch,
        RegularizationPolicy,
        RegularizationPolicyAllowedType,
        RegularizationPolicyVersion,
        ShiftRoster,
    )

# ---------------------------------------------------------------------------
# Shared enums (WD-12/WD-20 — typed choices, not free text)
# ---------------------------------------------------------------------------

_PUNCH_ROUNDING = ("NONE", "NEAREST", "UP", "DOWN")
_MISSING_PUNCH_BEHAVIOURS = ("INCOMPLETE", "ABSENT", "AUTO_CLOSE", "REQUIRE_REGULARIZATION")
_MISSING_SHIFT_BEHAVIOURS = ("INCOMPLETE", "ABSENT")
_HALF_DAY_SPLITS = ("BY_HOURS", "BY_MIDPOINT")
_MULTI_PUNCH_MODES = ("PAIR_ALL", "FIRST_IN_LAST_OUT")
_CORE_HOURS_BREACH_BEHAVIOURS = ("IGNORE", "FLAG", "HALF_DAY", "ABSENT")
_SPLIT_SHIFT_MISSED_BLOCK_BEHAVIOURS = ("IGNORE", "HALF_DAY", "ABSENT", "REQUIRE_REGULARIZATION")
_WORK_ON_LEAVE_BEHAVIOURS = ("KEEP_LEAVE", "PRESENT_CANCEL_LEAVE_HINT")
_EXCESS_BREAK_BEHAVIOURS = ("IGNORE", "DEDUCT", "FLAG", "REQUIRE_APPROVAL")
_LATE_COUNT_WINDOWS = ("MONTH",)
_INCOMPLETE_AT_LOCK_BEHAVIOURS = ("TREAT_ABSENT", "TREAT_PRESENT", "KEEP_INCOMPLETE")
_HOUR_BAND_STATUSES = ("PRESENT", "HALF_DAY", "ABSENT")
_LATE_CLASSIFICATIONS = ("NONE", "LATE", "HALF_DAY", "ABSENT")
_EARLY_CLASSIFICATIONS = ("NONE", "EARLY_DEPARTURE", "HALF_DAY", "ABSENT")

_OT_ELIGIBILITY = ("SHIFT_FLAG", "ALWAYS", "NEVER", "GRADE_VIA_ASSIGNMENT")
_OT_ROUNDING_MODES = ("NONE", "NEAREST", "UP", "DOWN")
_NIGHT_OT_MODES = ("SHIFT_FLAG", "WINDOW", "BOTH")
_APPROVAL_CHAINS = ("AUTO", "MANAGER", "MANAGER_THEN_HR", "HR")
_DAY_CLASSES = ("NORMAL", "WEEKLY_OFF", "HOLIDAY", "NIGHT")

_REGULARIZATION_TYPES = (
    "MISSING_PUNCH",
    "WRONG_PUNCH",
    "WRONG_SHIFT",
    "WRONG_STATUS",
    "WFH",
    "ON_DUTY",
    "EXCESS_BREAK",
    "FULL_DAY",
    # WD-32 decision 5 — the one type that is forward-dated by nature; see
    # `RegularizationRequestService.submit`'s future-date carve-out.
    "EARLY_DEPARTURE_APPROVAL",
)

_POLICY_RESOLUTION_KINDS = ("ATTENDANCE_POLICY", "OVERTIME_POLICY", "REGULARIZATION_POLICY")

_OVERTIME_RECORD_STATUSES = ("PENDING", "AUTO_APPROVED", "APPROVED", "REJECTED")
_OVERTIME_ACTIONS = (
    "DETECTED",
    "APPROVER_UNRESOLVED",
    "AUTO_APPROVED",
    "STAGE_APPROVED",
    "APPROVED",
    "REJECTED",
)


def _format_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    iso = str(value.isoformat())
    return iso.replace("+00:00", "Z")


def _format_time(value: time | None) -> str | None:
    if value is None:
        return None
    return value.strftime("%H:%M")


def _parse_time(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def _check_choice(field: str, value: str | None, choices: tuple[str, ...]) -> None:
    if value is not None and value not in choices:
        raise ValueError(f"{field} must be one of {choices}")


# ---------------------------------------------------------------------------
# Attendance Policy — identity
# ---------------------------------------------------------------------------


class AttendancePolicyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=150)
    code: str | None = Field(default=None, max_length=30)


class AttendancePolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=150)
    code: str | None = Field(default=None, max_length=30)
    is_active: bool | None = None


class AttendancePolicyRead(BaseModel):
    id: UUID
    company_id: UUID
    name: str
    code: str | None
    is_active: bool
    version: int
    created_at: str
    updated_at: str


def attendance_policy_to_read(row: "AttendancePolicy") -> AttendancePolicyRead:
    return AttendancePolicyRead(
        id=row.id,
        company_id=row.company_id,
        name=row.name,
        code=row.code,
        is_active=row.is_active,
        version=row.version,
        created_at=_format_timestamp(row.created_at) or "",
        updated_at=_format_timestamp(row.updated_at) or "",
    )


def attendance_policy_to_audit_dict(read: AttendancePolicyRead) -> dict[str, Any]:
    return read.model_dump(mode="json")


def build_attendance_policy_update_values(patch: AttendancePolicyUpdate) -> dict[str, Any]:
    return {field: getattr(patch, field) for field in patch.model_fields_set}


# ---------------------------------------------------------------------------
# Attendance Policy — hour / late / early-departure bands
# ---------------------------------------------------------------------------


class AttendancePolicyHourBandInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_minutes: int = Field(ge=0)
    max_minutes: int | None = Field(default=None, ge=0)
    result_status: str
    sort_order: int = 0

    @field_validator("result_status")
    @classmethod
    def validate_result_status(cls, value: str) -> str:
        _check_choice("result_status", value, _HOUR_BAND_STATUSES)
        return value

    @model_validator(mode="after")
    def validate_range(self) -> "AttendancePolicyHourBandInput":
        if self.max_minutes is not None and self.max_minutes < self.min_minutes:
            raise ValueError("max_minutes must be >= min_minutes")
        return self


class AttendancePolicyHourBandRead(BaseModel):
    id: UUID
    min_minutes: int
    max_minutes: int | None
    result_status: str
    sort_order: int


def hour_band_to_read(row: "AttendancePolicyHourBand") -> AttendancePolicyHourBandRead:
    return AttendancePolicyHourBandRead(
        id=row.id,
        min_minutes=row.min_minutes,
        max_minutes=row.max_minutes,
        result_status=row.result_status,
        sort_order=row.sort_order,
    )


class AttendancePolicyLateBandInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_minutes: int = Field(ge=0)
    max_minutes: int | None = Field(default=None, ge=0)
    classification: str
    counts_toward_cap: bool = True
    sort_order: int = 0

    @field_validator("classification")
    @classmethod
    def validate_classification(cls, value: str) -> str:
        _check_choice("classification", value, _LATE_CLASSIFICATIONS)
        return value

    @model_validator(mode="after")
    def validate_range(self) -> "AttendancePolicyLateBandInput":
        if self.max_minutes is not None and self.max_minutes < self.min_minutes:
            raise ValueError("max_minutes must be >= min_minutes")
        return self


class AttendancePolicyLateBandRead(BaseModel):
    id: UUID
    min_minutes: int
    max_minutes: int | None
    classification: str
    counts_toward_cap: bool
    sort_order: int


def late_band_to_read(row: "AttendancePolicyLateBand") -> AttendancePolicyLateBandRead:
    return AttendancePolicyLateBandRead(
        id=row.id,
        min_minutes=row.min_minutes,
        max_minutes=row.max_minutes,
        classification=row.classification,
        counts_toward_cap=row.counts_toward_cap,
        sort_order=row.sort_order,
    )


class AttendancePolicyEarlyDepartureBandInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_minutes: int = Field(ge=0)
    max_minutes: int | None = Field(default=None, ge=0)
    classification: str
    counts_toward_cap: bool = True
    sort_order: int = 0

    @field_validator("classification")
    @classmethod
    def validate_classification(cls, value: str) -> str:
        _check_choice("classification", value, _EARLY_CLASSIFICATIONS)
        return value

    @model_validator(mode="after")
    def validate_range(self) -> "AttendancePolicyEarlyDepartureBandInput":
        if self.max_minutes is not None and self.max_minutes < self.min_minutes:
            raise ValueError("max_minutes must be >= min_minutes")
        return self


class AttendancePolicyEarlyDepartureBandRead(BaseModel):
    id: UUID
    min_minutes: int
    max_minutes: int | None
    classification: str
    counts_toward_cap: bool
    sort_order: int


def early_departure_band_to_read(
    row: "AttendancePolicyEarlyDepartureBand",
) -> AttendancePolicyEarlyDepartureBandRead:
    return AttendancePolicyEarlyDepartureBandRead(
        id=row.id,
        min_minutes=row.min_minutes,
        max_minutes=row.max_minutes,
        classification=row.classification,
        counts_toward_cap=row.counts_toward_cap,
        sort_order=row.sort_order,
    )


# ---------------------------------------------------------------------------
# Attendance Policy — version
# ---------------------------------------------------------------------------

_ATTENDANCE_VERSION_FIELDS = (
    "grace_in_minutes",
    "grace_out_minutes",
    "punch_rounding",
    "rounding_minutes",
    "missing_punch_behaviour",
    "auto_close_after_minutes",
    "auto_close_uses_shift_end",
    "missing_shift_behaviour",
    "half_day_split",
    "half_day_boundary_minutes",
    "multi_punch_mode",
    "duplicate_punch_window_seconds",
    "core_hours_breach_behaviour",
    "early_out_uses_core_end",
    "split_shift_block_mandatory",
    "split_shift_missed_block_behaviour",
    "split_shift_allow_hours_compensation",
    "wfh_requires_punch",
    "on_duty_requires_punch",
    "wfh_uses_shift_hours",
    "work_on_leave_behaviour",
    "excess_break_behaviour",
    "late_count_window",
    "lates_to_half_day_count",
    "early_departure_requires_approval",
    "incomplete_at_lock_behaviour",
)


class AttendancePolicyVersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effective_from: date | None = None

    grace_in_minutes: int = Field(default=0, ge=0)
    grace_out_minutes: int = Field(default=0, ge=0)
    punch_rounding: str = "NONE"
    rounding_minutes: int | None = Field(default=None, gt=0)
    missing_punch_behaviour: str = "INCOMPLETE"
    auto_close_after_minutes: int | None = Field(default=None, gt=0)
    auto_close_uses_shift_end: bool = True
    missing_shift_behaviour: str = "INCOMPLETE"
    half_day_split: str = "BY_HOURS"
    half_day_boundary_minutes: int | None = Field(default=None, ge=0)
    multi_punch_mode: str = "PAIR_ALL"
    duplicate_punch_window_seconds: int = Field(default=60, ge=0)
    core_hours_breach_behaviour: str = "FLAG"
    early_out_uses_core_end: bool = False
    split_shift_block_mandatory: bool = True
    split_shift_missed_block_behaviour: str = "HALF_DAY"
    split_shift_allow_hours_compensation: bool = False
    wfh_requires_punch: bool = True
    on_duty_requires_punch: bool = False
    wfh_uses_shift_hours: bool = True
    work_on_leave_behaviour: str = "KEEP_LEAVE"
    excess_break_behaviour: str = "FLAG"
    late_count_window: str = "MONTH"
    lates_to_half_day_count: int | None = Field(default=None, gt=0)
    early_departure_requires_approval: bool = False
    excess_break_count_window: str = "MONTH"
    excess_break_days_to_half_day_count: int | None = Field(default=None, gt=0)
    incomplete_at_lock_behaviour: str = "TREAT_ABSENT"

    hour_bands: list[AttendancePolicyHourBandInput] = Field(default_factory=list)
    late_bands: list[AttendancePolicyLateBandInput] = Field(default_factory=list)
    early_departure_bands: list[AttendancePolicyEarlyDepartureBandInput] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def validate_choices(self) -> "AttendancePolicyVersionCreate":
        _check_choice("punch_rounding", self.punch_rounding, _PUNCH_ROUNDING)
        _check_choice(
            "missing_punch_behaviour", self.missing_punch_behaviour, _MISSING_PUNCH_BEHAVIOURS
        )
        _check_choice(
            "missing_shift_behaviour", self.missing_shift_behaviour, _MISSING_SHIFT_BEHAVIOURS
        )
        _check_choice("half_day_split", self.half_day_split, _HALF_DAY_SPLITS)
        _check_choice("multi_punch_mode", self.multi_punch_mode, _MULTI_PUNCH_MODES)
        _check_choice(
            "core_hours_breach_behaviour",
            self.core_hours_breach_behaviour,
            _CORE_HOURS_BREACH_BEHAVIOURS,
        )
        _check_choice(
            "split_shift_missed_block_behaviour",
            self.split_shift_missed_block_behaviour,
            _SPLIT_SHIFT_MISSED_BLOCK_BEHAVIOURS,
        )
        _check_choice(
            "work_on_leave_behaviour", self.work_on_leave_behaviour, _WORK_ON_LEAVE_BEHAVIOURS
        )
        _check_choice(
            "excess_break_behaviour", self.excess_break_behaviour, _EXCESS_BREAK_BEHAVIOURS
        )
        _check_choice("late_count_window", self.late_count_window, _LATE_COUNT_WINDOWS)
        _check_choice(
            "excess_break_count_window", self.excess_break_count_window, _LATE_COUNT_WINDOWS
        )
        _check_choice(
            "incomplete_at_lock_behaviour",
            self.incomplete_at_lock_behaviour,
            _INCOMPLETE_AT_LOCK_BEHAVIOURS,
        )
        return self


class AttendancePolicyVersionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effective_from: date | None = None
    grace_in_minutes: int | None = Field(default=None, ge=0)
    grace_out_minutes: int | None = Field(default=None, ge=0)
    punch_rounding: str | None = None
    rounding_minutes: int | None = Field(default=None, gt=0)
    missing_punch_behaviour: str | None = None
    auto_close_after_minutes: int | None = Field(default=None, gt=0)
    auto_close_uses_shift_end: bool | None = None
    missing_shift_behaviour: str | None = None
    half_day_split: str | None = None
    half_day_boundary_minutes: int | None = Field(default=None, ge=0)
    multi_punch_mode: str | None = None
    duplicate_punch_window_seconds: int | None = Field(default=None, ge=0)
    core_hours_breach_behaviour: str | None = None
    early_out_uses_core_end: bool | None = None
    split_shift_block_mandatory: bool | None = None
    split_shift_missed_block_behaviour: str | None = None
    split_shift_allow_hours_compensation: bool | None = None
    wfh_requires_punch: bool | None = None
    on_duty_requires_punch: bool | None = None
    wfh_uses_shift_hours: bool | None = None
    work_on_leave_behaviour: str | None = None
    excess_break_behaviour: str | None = None
    late_count_window: str | None = None
    lates_to_half_day_count: int | None = Field(default=None, gt=0)
    early_departure_requires_approval: bool | None = None
    excess_break_count_window: str | None = None
    excess_break_days_to_half_day_count: int | None = Field(default=None, gt=0)
    incomplete_at_lock_behaviour: str | None = None

    hour_bands: list[AttendancePolicyHourBandInput] | None = None
    late_bands: list[AttendancePolicyLateBandInput] | None = None
    early_departure_bands: list[AttendancePolicyEarlyDepartureBandInput] | None = None

    @model_validator(mode="after")
    def validate_choices(self) -> "AttendancePolicyVersionUpdate":
        _check_choice("punch_rounding", self.punch_rounding, _PUNCH_ROUNDING)
        _check_choice(
            "missing_punch_behaviour", self.missing_punch_behaviour, _MISSING_PUNCH_BEHAVIOURS
        )
        _check_choice(
            "missing_shift_behaviour", self.missing_shift_behaviour, _MISSING_SHIFT_BEHAVIOURS
        )
        _check_choice("half_day_split", self.half_day_split, _HALF_DAY_SPLITS)
        _check_choice("multi_punch_mode", self.multi_punch_mode, _MULTI_PUNCH_MODES)
        _check_choice(
            "core_hours_breach_behaviour",
            self.core_hours_breach_behaviour,
            _CORE_HOURS_BREACH_BEHAVIOURS,
        )
        _check_choice(
            "split_shift_missed_block_behaviour",
            self.split_shift_missed_block_behaviour,
            _SPLIT_SHIFT_MISSED_BLOCK_BEHAVIOURS,
        )
        _check_choice(
            "work_on_leave_behaviour", self.work_on_leave_behaviour, _WORK_ON_LEAVE_BEHAVIOURS
        )
        _check_choice(
            "excess_break_behaviour", self.excess_break_behaviour, _EXCESS_BREAK_BEHAVIOURS
        )
        _check_choice("late_count_window", self.late_count_window, _LATE_COUNT_WINDOWS)
        _check_choice(
            "excess_break_count_window", self.excess_break_count_window, _LATE_COUNT_WINDOWS
        )
        _check_choice(
            "incomplete_at_lock_behaviour",
            self.incomplete_at_lock_behaviour,
            _INCOMPLETE_AT_LOCK_BEHAVIOURS,
        )
        return self


class AttendancePolicyVersionPublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    publish_reason: str | None = None
    expected_previous_version: int | None = None


class AttendancePolicyVersionRead(BaseModel):
    id: UUID
    company_id: UUID
    policy_id: UUID
    status: str
    version: int
    effective_from: date | None
    effective_to: date | None

    grace_in_minutes: int
    grace_out_minutes: int
    punch_rounding: str
    rounding_minutes: int | None
    missing_punch_behaviour: str
    auto_close_after_minutes: int | None
    auto_close_uses_shift_end: bool
    missing_shift_behaviour: str
    half_day_split: str
    half_day_boundary_minutes: int | None
    multi_punch_mode: str
    duplicate_punch_window_seconds: int
    core_hours_breach_behaviour: str
    early_out_uses_core_end: bool
    split_shift_block_mandatory: bool
    split_shift_missed_block_behaviour: str
    split_shift_allow_hours_compensation: bool
    wfh_requires_punch: bool
    on_duty_requires_punch: bool
    wfh_uses_shift_hours: bool
    work_on_leave_behaviour: str
    excess_break_behaviour: str
    late_count_window: str
    lates_to_half_day_count: int | None
    early_departure_requires_approval: bool
    excess_break_count_window: str
    excess_break_days_to_half_day_count: int | None
    incomplete_at_lock_behaviour: str

    hour_bands: list[AttendancePolicyHourBandRead]
    late_bands: list[AttendancePolicyLateBandRead]
    early_departure_bands: list[AttendancePolicyEarlyDepartureBandRead]

    publish_reason: str | None
    published_at: str | None
    published_by: UUID | None
    created_at: str
    updated_at: str


def attendance_policy_version_to_read(
    row: "AttendancePolicyVersion",
    hour_bands: list["AttendancePolicyHourBand"],
    late_bands: list["AttendancePolicyLateBand"],
    early_departure_bands: list["AttendancePolicyEarlyDepartureBand"],
) -> AttendancePolicyVersionRead:
    return AttendancePolicyVersionRead(
        id=row.id,
        company_id=row.company_id,
        policy_id=row.policy_id,
        status=row.status,
        version=row.version,
        effective_from=row.effective_from,
        effective_to=row.effective_to,
        grace_in_minutes=row.grace_in_minutes,
        grace_out_minutes=row.grace_out_minutes,
        punch_rounding=row.punch_rounding,
        rounding_minutes=row.rounding_minutes,
        missing_punch_behaviour=row.missing_punch_behaviour,
        auto_close_after_minutes=row.auto_close_after_minutes,
        auto_close_uses_shift_end=row.auto_close_uses_shift_end,
        missing_shift_behaviour=row.missing_shift_behaviour,
        half_day_split=row.half_day_split,
        half_day_boundary_minutes=row.half_day_boundary_minutes,
        multi_punch_mode=row.multi_punch_mode,
        duplicate_punch_window_seconds=row.duplicate_punch_window_seconds,
        core_hours_breach_behaviour=row.core_hours_breach_behaviour,
        early_out_uses_core_end=row.early_out_uses_core_end,
        split_shift_block_mandatory=row.split_shift_block_mandatory,
        split_shift_missed_block_behaviour=row.split_shift_missed_block_behaviour,
        split_shift_allow_hours_compensation=row.split_shift_allow_hours_compensation,
        wfh_requires_punch=row.wfh_requires_punch,
        on_duty_requires_punch=row.on_duty_requires_punch,
        wfh_uses_shift_hours=row.wfh_uses_shift_hours,
        work_on_leave_behaviour=row.work_on_leave_behaviour,
        excess_break_behaviour=row.excess_break_behaviour,
        late_count_window=row.late_count_window,
        lates_to_half_day_count=row.lates_to_half_day_count,
        early_departure_requires_approval=row.early_departure_requires_approval,
        excess_break_count_window=row.excess_break_count_window,
        excess_break_days_to_half_day_count=row.excess_break_days_to_half_day_count,
        incomplete_at_lock_behaviour=row.incomplete_at_lock_behaviour,
        hour_bands=[hour_band_to_read(b) for b in hour_bands],
        late_bands=[late_band_to_read(b) for b in late_bands],
        early_departure_bands=[early_departure_band_to_read(b) for b in early_departure_bands],
        publish_reason=row.publish_reason,
        published_at=_format_timestamp(row.published_at),
        published_by=row.published_by,
        created_at=_format_timestamp(row.created_at) or "",
        updated_at=_format_timestamp(row.updated_at) or "",
    )


def attendance_policy_version_to_audit_dict(read: AttendancePolicyVersionRead) -> dict[str, Any]:
    return read.model_dump(mode="json")


def build_attendance_policy_version_update_values(
    patch: AttendancePolicyVersionUpdate,
) -> dict[str, Any]:
    return {
        field: getattr(patch, field)
        for field in patch.model_fields_set
        if field not in ("hour_bands", "late_bands", "early_departure_bands")
    }


# ---------------------------------------------------------------------------
# Overtime Policy
# ---------------------------------------------------------------------------


class OvertimePolicyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=150)
    code: str | None = Field(default=None, max_length=30)


class OvertimePolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=150)
    code: str | None = Field(default=None, max_length=30)
    is_active: bool | None = None


class OvertimePolicyRead(BaseModel):
    id: UUID
    company_id: UUID
    name: str
    code: str | None
    is_active: bool
    version: int
    created_at: str
    updated_at: str


def overtime_policy_to_read(row: "OvertimePolicy") -> OvertimePolicyRead:
    return OvertimePolicyRead(
        id=row.id,
        company_id=row.company_id,
        name=row.name,
        code=row.code,
        is_active=row.is_active,
        version=row.version,
        created_at=_format_timestamp(row.created_at) or "",
        updated_at=_format_timestamp(row.updated_at) or "",
    )


def overtime_policy_to_audit_dict(read: OvertimePolicyRead) -> dict[str, Any]:
    return read.model_dump(mode="json")


def build_overtime_policy_update_values(patch: OvertimePolicyUpdate) -> dict[str, Any]:
    return {field: getattr(patch, field) for field in patch.model_fields_set}


class OvertimePolicyRateRowInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day_class: str
    classification_code: str = Field(min_length=1, max_length=50)
    multiplier_decimal: Decimal | None = Field(default=None, gt=0)
    sort_order: int = 0

    @field_validator("day_class")
    @classmethod
    def validate_day_class(cls, value: str) -> str:
        _check_choice("day_class", value, _DAY_CLASSES)
        return value


class OvertimePolicyRateRowRead(BaseModel):
    id: UUID
    day_class: str
    classification_code: str
    multiplier_decimal: Decimal | None
    sort_order: int


def rate_row_to_read(row: "OvertimePolicyRateRow") -> OvertimePolicyRateRowRead:
    return OvertimePolicyRateRowRead(
        id=row.id,
        day_class=row.day_class,
        classification_code=row.classification_code,
        multiplier_decimal=row.multiplier_decimal,
        sort_order=row.sort_order,
    )


class OvertimePolicyVersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effective_from: date | None = None
    eligibility: str = "SHIFT_FLAG"
    min_ot_minutes: int = Field(default=0, ge=0)
    rounding_minutes: int | None = Field(default=None, gt=0)
    rounding_mode: str = "NONE"
    requires_pre_approval: bool = False
    requires_post_approval: bool = True
    daily_cap_minutes: int | None = Field(default=None, gt=0)
    weekly_cap_minutes: int | None = Field(default=None, gt=0)
    monthly_cap_minutes: int | None = Field(default=None, gt=0)
    comp_off_instead_of_pay: bool = False
    comp_off_expiry_days: int | None = Field(default=None, gt=0)
    comp_off_day_length_minutes: int | None = Field(default=None, gt=0)
    night_ot_mode: str = "SHIFT_FLAG"
    night_window_start: str | None = None
    night_window_end: str | None = None
    approval_chain: str = "MANAGER"
    rate_rows: list[OvertimePolicyRateRowInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_choices(self) -> "OvertimePolicyVersionCreate":
        _check_choice("eligibility", self.eligibility, _OT_ELIGIBILITY)
        _check_choice("rounding_mode", self.rounding_mode, _OT_ROUNDING_MODES)
        _check_choice("night_ot_mode", self.night_ot_mode, _NIGHT_OT_MODES)
        _check_choice("approval_chain", self.approval_chain, _APPROVAL_CHAINS)
        if (self.night_window_start is None) != (self.night_window_end is None):
            raise ValueError("night_window_start and night_window_end must be given together")
        return self


class OvertimePolicyVersionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effective_from: date | None = None
    eligibility: str | None = None
    min_ot_minutes: int | None = Field(default=None, ge=0)
    rounding_minutes: int | None = Field(default=None, gt=0)
    rounding_mode: str | None = None
    requires_pre_approval: bool | None = None
    requires_post_approval: bool | None = None
    daily_cap_minutes: int | None = Field(default=None, gt=0)
    weekly_cap_minutes: int | None = Field(default=None, gt=0)
    monthly_cap_minutes: int | None = Field(default=None, gt=0)
    comp_off_instead_of_pay: bool | None = None
    comp_off_expiry_days: int | None = Field(default=None, gt=0)
    comp_off_day_length_minutes: int | None = Field(default=None, gt=0)
    night_ot_mode: str | None = None
    night_window_start: str | None = None
    night_window_end: str | None = None
    approval_chain: str | None = None
    rate_rows: list[OvertimePolicyRateRowInput] | None = None

    @model_validator(mode="after")
    def validate_choices(self) -> "OvertimePolicyVersionUpdate":
        _check_choice("eligibility", self.eligibility, _OT_ELIGIBILITY)
        _check_choice("rounding_mode", self.rounding_mode, _OT_ROUNDING_MODES)
        _check_choice("night_ot_mode", self.night_ot_mode, _NIGHT_OT_MODES)
        _check_choice("approval_chain", self.approval_chain, _APPROVAL_CHAINS)
        return self


class OvertimePolicyVersionPublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    publish_reason: str | None = None
    expected_previous_version: int | None = None


class OvertimePolicyVersionRead(BaseModel):
    id: UUID
    company_id: UUID
    policy_id: UUID
    status: str
    version: int
    effective_from: date | None
    effective_to: date | None

    eligibility: str
    min_ot_minutes: int
    rounding_minutes: int | None
    rounding_mode: str
    requires_pre_approval: bool
    requires_post_approval: bool
    daily_cap_minutes: int | None
    weekly_cap_minutes: int | None
    monthly_cap_minutes: int | None
    comp_off_instead_of_pay: bool
    comp_off_expiry_days: int | None
    comp_off_day_length_minutes: int | None
    night_ot_mode: str
    night_window_start: str | None
    night_window_end: str | None
    approval_chain: str

    rate_rows: list[OvertimePolicyRateRowRead]

    publish_reason: str | None
    published_at: str | None
    published_by: UUID | None
    created_at: str
    updated_at: str


def overtime_policy_version_to_read(
    row: "OvertimePolicyVersion", rate_rows: list["OvertimePolicyRateRow"]
) -> OvertimePolicyVersionRead:
    return OvertimePolicyVersionRead(
        id=row.id,
        company_id=row.company_id,
        policy_id=row.policy_id,
        status=row.status,
        version=row.version,
        effective_from=row.effective_from,
        effective_to=row.effective_to,
        eligibility=row.eligibility,
        min_ot_minutes=row.min_ot_minutes,
        rounding_minutes=row.rounding_minutes,
        rounding_mode=row.rounding_mode,
        requires_pre_approval=row.requires_pre_approval,
        requires_post_approval=row.requires_post_approval,
        daily_cap_minutes=row.daily_cap_minutes,
        weekly_cap_minutes=row.weekly_cap_minutes,
        monthly_cap_minutes=row.monthly_cap_minutes,
        comp_off_instead_of_pay=row.comp_off_instead_of_pay,
        comp_off_expiry_days=row.comp_off_expiry_days,
        comp_off_day_length_minutes=row.comp_off_day_length_minutes,
        night_ot_mode=row.night_ot_mode,
        night_window_start=_format_time(row.night_window_start),
        night_window_end=_format_time(row.night_window_end),
        approval_chain=row.approval_chain,
        rate_rows=[rate_row_to_read(r) for r in rate_rows],
        publish_reason=row.publish_reason,
        published_at=_format_timestamp(row.published_at),
        published_by=row.published_by,
        created_at=_format_timestamp(row.created_at) or "",
        updated_at=_format_timestamp(row.updated_at) or "",
    )


def overtime_policy_version_to_audit_dict(read: OvertimePolicyVersionRead) -> dict[str, Any]:
    return read.model_dump(mode="json")


def build_overtime_policy_version_update_values(
    patch: OvertimePolicyVersionUpdate,
) -> dict[str, Any]:
    values = {
        field: getattr(patch, field)
        for field in patch.model_fields_set
        if field not in ("rate_rows", "night_window_start", "night_window_end")
    }
    if "night_window_start" in patch.model_fields_set:
        values["night_window_start"] = (
            _parse_time(patch.night_window_start) if patch.night_window_start else None
        )
    if "night_window_end" in patch.model_fields_set:
        values["night_window_end"] = (
            _parse_time(patch.night_window_end) if patch.night_window_end else None
        )
    return values


# ---------------------------------------------------------------------------
# Regularization Policy
# ---------------------------------------------------------------------------


class RegularizationPolicyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=150)
    code: str | None = Field(default=None, max_length=30)


class RegularizationPolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=150)
    code: str | None = Field(default=None, max_length=30)
    is_active: bool | None = None


class RegularizationPolicyRead(BaseModel):
    id: UUID
    company_id: UUID
    name: str
    code: str | None
    is_active: bool
    version: int
    created_at: str
    updated_at: str


def regularization_policy_to_read(row: "RegularizationPolicy") -> RegularizationPolicyRead:
    return RegularizationPolicyRead(
        id=row.id,
        company_id=row.company_id,
        name=row.name,
        code=row.code,
        is_active=row.is_active,
        version=row.version,
        created_at=_format_timestamp(row.created_at) or "",
        updated_at=_format_timestamp(row.updated_at) or "",
    )


def regularization_policy_to_audit_dict(read: RegularizationPolicyRead) -> dict[str, Any]:
    return read.model_dump(mode="json")


def build_regularization_policy_update_values(patch: RegularizationPolicyUpdate) -> dict[str, Any]:
    return {field: getattr(patch, field) for field in patch.model_fields_set}


class RegularizationPolicyAllowedTypeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    regularization_type: str
    sort_order: int = 0

    @field_validator("regularization_type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        _check_choice("regularization_type", value, _REGULARIZATION_TYPES)
        return value


class RegularizationPolicyAllowedTypeRead(BaseModel):
    id: UUID
    regularization_type: str
    sort_order: int


def allowed_type_to_read(
    row: "RegularizationPolicyAllowedType",
) -> RegularizationPolicyAllowedTypeRead:
    return RegularizationPolicyAllowedTypeRead(
        id=row.id, regularization_type=row.regularization_type, sort_order=row.sort_order
    )


class RegularizationPolicyVersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effective_from: date | None = None
    allow_employee_request: bool = True
    allow_manager_request: bool = True
    allow_hr_request: bool = True
    max_backdated_days: int | None = Field(default=None, ge=0)
    max_requests_per_month: int | None = Field(default=None, gt=0)
    reason_required: bool = True
    attachment_required: bool = False
    approval_chain: str = "MANAGER"
    auto_approve_within_minutes: int | None = Field(default=None, ge=0)
    blocked_when_locked: bool = True
    allowed_types: list[RegularizationPolicyAllowedTypeInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_choices(self) -> "RegularizationPolicyVersionCreate":
        _check_choice("approval_chain", self.approval_chain, _APPROVAL_CHAINS)
        return self


class RegularizationPolicyVersionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effective_from: date | None = None
    allow_employee_request: bool | None = None
    allow_manager_request: bool | None = None
    allow_hr_request: bool | None = None
    max_backdated_days: int | None = Field(default=None, ge=0)
    max_requests_per_month: int | None = Field(default=None, gt=0)
    reason_required: bool | None = None
    attachment_required: bool | None = None
    approval_chain: str | None = None
    auto_approve_within_minutes: int | None = Field(default=None, ge=0)
    blocked_when_locked: bool | None = None
    allowed_types: list[RegularizationPolicyAllowedTypeInput] | None = None

    @model_validator(mode="after")
    def validate_choices(self) -> "RegularizationPolicyVersionUpdate":
        _check_choice("approval_chain", self.approval_chain, _APPROVAL_CHAINS)
        return self


class RegularizationPolicyVersionPublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    publish_reason: str | None = None
    expected_previous_version: int | None = None


class RegularizationPolicyVersionRead(BaseModel):
    id: UUID
    company_id: UUID
    policy_id: UUID
    status: str
    version: int
    effective_from: date | None
    effective_to: date | None

    allow_employee_request: bool
    allow_manager_request: bool
    allow_hr_request: bool
    max_backdated_days: int | None
    max_requests_per_month: int | None
    reason_required: bool
    attachment_required: bool
    approval_chain: str
    auto_approve_within_minutes: int | None
    blocked_when_locked: bool

    allowed_types: list[RegularizationPolicyAllowedTypeRead]

    publish_reason: str | None
    published_at: str | None
    published_by: UUID | None
    created_at: str
    updated_at: str


def regularization_policy_version_to_read(
    row: "RegularizationPolicyVersion", allowed_types: list["RegularizationPolicyAllowedType"]
) -> RegularizationPolicyVersionRead:
    return RegularizationPolicyVersionRead(
        id=row.id,
        company_id=row.company_id,
        policy_id=row.policy_id,
        status=row.status,
        version=row.version,
        effective_from=row.effective_from,
        effective_to=row.effective_to,
        allow_employee_request=row.allow_employee_request,
        allow_manager_request=row.allow_manager_request,
        allow_hr_request=row.allow_hr_request,
        max_backdated_days=row.max_backdated_days,
        max_requests_per_month=row.max_requests_per_month,
        reason_required=row.reason_required,
        attachment_required=row.attachment_required,
        approval_chain=row.approval_chain,
        auto_approve_within_minutes=row.auto_approve_within_minutes,
        blocked_when_locked=row.blocked_when_locked,
        allowed_types=[allowed_type_to_read(a) for a in allowed_types],
        publish_reason=row.publish_reason,
        published_at=_format_timestamp(row.published_at),
        published_by=row.published_by,
        created_at=_format_timestamp(row.created_at) or "",
        updated_at=_format_timestamp(row.updated_at) or "",
    )


def regularization_policy_version_to_audit_dict(
    read: RegularizationPolicyVersionRead,
) -> dict[str, Any]:
    return read.model_dump(mode="json")


def build_regularization_policy_version_update_values(
    patch: RegularizationPolicyVersionUpdate,
) -> dict[str, Any]:
    return {
        field: getattr(patch, field) for field in patch.model_fields_set if field != "allowed_types"
    }


# ---------------------------------------------------------------------------
# Policy resolution preview (architecture §19/§35 — "resolved through" explain view)
# ---------------------------------------------------------------------------


class PolicyResolutionRead(BaseModel):
    employee_id: UUID
    date: date
    policy_kind: str
    config_incomplete: bool
    resolved_policy_id: UUID | None = None
    resolved_policy_name: str | None = None
    resolved_policy_code: str | None = None
    resolved_version_id: UUID | None = None
    resolved_through: str | None = None


# ---------------------------------------------------------------------------
# W5 — ShiftRoster (architecture §4.2/§9.7, WD-27)
# ---------------------------------------------------------------------------

_ROSTER_STATUSES = ("DRAFT", "PUBLISHED")


def _check_roster_overrides(is_week_off_override: bool, is_holiday_working_override: bool) -> None:
    if is_week_off_override and is_holiday_working_override:
        raise ValueError(
            "is_week_off_override and is_holiday_working_override are mutually exclusive"
        )


class ShiftRosterCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    employee_id: UUID
    roster_date: date
    shift_id: UUID | None = None
    is_week_off_override: bool = False
    is_holiday_working_override: bool = False
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _validate(self) -> "ShiftRosterCreate":
        _check_roster_overrides(self.is_week_off_override, self.is_holiday_working_override)
        if self.is_week_off_override and self.shift_id is not None:
            raise ValueError("a week-off override row must not carry a shift_id")
        return self


class ShiftRosterBulkCreateItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    roster_date: date
    shift_id: UUID | None = None
    is_week_off_override: bool = False
    is_holiday_working_override: bool = False

    @model_validator(mode="after")
    def _validate(self) -> "ShiftRosterBulkCreateItem":
        _check_roster_overrides(self.is_week_off_override, self.is_holiday_working_override)
        if self.is_week_off_override and self.shift_id is not None:
            raise ValueError("a week-off override row must not carry a shift_id")
        return self


class ShiftRosterBulkCreate(BaseModel):
    """Covers the brief's "fixed roster" (repeat one shift across a date range, expanded
    client-side into `entries`) and "monthly roster" (an explicit date→shift list) — no
    rotation-pattern generator is built server-side (WD-27); the backend only ever sees dated
    rows, matching the architecture's typed/no-generic-engine posture (WD-12)."""

    model_config = ConfigDict(extra="forbid")

    employee_id: UUID
    entries: list[ShiftRosterBulkCreateItem] = Field(min_length=1, max_length=366)
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _validate_unique_dates(self) -> "ShiftRosterBulkCreate":
        dates = [entry.roster_date for entry in self.entries]
        if len(dates) != len(set(dates)):
            raise ValueError("entries must not repeat the same roster_date")
        return self


class ShiftRosterUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shift_id: UUID | None = None
    is_week_off_override: bool | None = None
    is_holiday_working_override: bool | None = None
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _validate(self) -> "ShiftRosterUpdate":
        _check_roster_overrides(
            bool(self.is_week_off_override), bool(self.is_holiday_working_override)
        )
        return self


class ShiftRosterRead(BaseModel):
    id: UUID
    company_id: UUID
    employee_id: UUID
    roster_date: date
    shift_id: UUID | None
    is_week_off_override: bool
    is_holiday_working_override: bool
    status: str
    reason: str | None
    version: int
    created_at: str
    updated_at: str


def shift_roster_to_read(row: "ShiftRoster") -> ShiftRosterRead:
    return ShiftRosterRead(
        id=row.id,
        company_id=row.company_id,
        employee_id=row.employee_id,
        roster_date=row.roster_date,
        shift_id=row.shift_id,
        is_week_off_override=row.is_week_off_override,
        is_holiday_working_override=row.is_holiday_working_override,
        status=row.status,
        reason=row.reason,
        version=row.version,
        created_at=_format_timestamp(row.created_at) or "",
        updated_at=_format_timestamp(row.updated_at) or "",
    )


def shift_roster_to_audit_dict(read: ShiftRosterRead) -> dict[str, Any]:
    return read.model_dump(mode="json")


def build_shift_roster_update_values(patch: ShiftRosterUpdate) -> dict[str, Any]:
    return {field: getattr(patch, field) for field in patch.model_fields_set}


# ---------------------------------------------------------------------------
# W4 — Punch / AttendanceDay / AttendanceBreak
# ---------------------------------------------------------------------------

_PUNCH_DIRECTIONS = ("IN", "OUT")
_PUNCH_SOURCES = (
    "WEB",
    "MOBILE",
    "DEVICE",
    "IMPORT",
    "ADMIN",
    "API",
    "REGULARIZATION",
    "FACE",
)
_ATTENDANCE_STATUSES = (
    "NOT_JOINED",
    "EXITED",
    "NOT_EXPECTED",
    "PRESENT",
    "HALF_DAY",
    "ABSENT",
    "LEAVE",
    "ON_DUTY",
    "WFH",
    "INCOMPLETE",
    "CONFIG_ERROR",
)


class PunchCreateSelf(BaseModel):
    """Body for `POST /attendance/punches/me` — employee self-service (`DEC-TZ-01`, SELECTED).

    **There is deliberately no `punch_time`, no `source`, and no `employee_id` field here.** The
    punch instant is the moment the server receives the request; the source is assigned from the
    authenticated route; the employee is the caller. Under `extra="forbid"` a client that sends
    any of the three gets a 422 rather than being quietly ignored, so an old client fails loudly
    instead of silently having its timestamp discarded.

    This is why no clock-skew tolerance is configurable anywhere in the module: with no
    client-supplied instant on this path there is nothing to compare a tolerance against. The
    control is structural, not a threshold (execution gate §7.1)."""

    model_config = ConfigDict(extra="forbid")

    direction: str
    reference: str | None = Field(default=None, max_length=200)
    idempotency_key: str | None = Field(default=None, max_length=100)

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, value: str) -> str:
        if value not in _PUNCH_DIRECTIONS:
            raise ValueError(f"direction must be one of {_PUNCH_DIRECTIONS}")
        return value


class PunchCreateOnBehalf(BaseModel):
    """Body for `POST /attendance/punches` — HR/admin entering a punch for someone else
    (`ATTENDANCE.PUNCH_ON_BEHALF`).

    Client-supplied time is **required** here, because that is the workflow's entire purpose:
    recording an instant the server did not itself observe. It is bounded rather than trusted —
    not in the future (`FuturePunchTimeError`), not inside a `CLOSED` period (`_ensure_date_open`),
    not before the employee's employment began (`PunchTimeBeforeEmploymentError`).

    `reference` is the **reason** and is mandatory here (it stays optional on the self route),
    so every administrative override carries its own justification into the audit log.

    `source` is absent by design and server-assigned as `ADMIN`, closing `F-11`: the value can no
    longer be chosen by the caller on any route."""

    model_config = ConfigDict(extra="forbid")

    employee_id: UUID
    punch_time: AwareIsoDatetime
    direction: str
    reference: str = Field(min_length=1, max_length=200)
    idempotency_key: str | None = Field(default=None, max_length=100)

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, value: str) -> str:
        if value not in _PUNCH_DIRECTIONS:
            raise ValueError(f"direction must be one of {_PUNCH_DIRECTIONS}")
        return value


class PunchRead(BaseModel):
    id: UUID
    company_id: UUID
    employee_id: UUID
    punch_time: str
    direction: str
    source: str
    idempotency_key: str | None
    recorded_by_user_id: UUID | None
    reference: str | None
    created_at: str


def punch_to_read(row: "Punch") -> PunchRead:
    return PunchRead(
        id=row.id,
        company_id=row.company_id,
        employee_id=row.employee_id,
        punch_time=_format_timestamp(row.punch_time) or "",
        direction=row.direction,
        source=row.source,
        idempotency_key=row.idempotency_key,
        recorded_by_user_id=row.recorded_by_user_id,
        reference=row.reference,
        created_at=_format_timestamp(row.created_at) or "",
    )


def punch_to_audit_dict(read: PunchRead) -> dict[str, Any]:
    return read.model_dump(mode="json")


class AttendanceBreakRead(BaseModel):
    id: UUID
    attendance_day_id: UUID
    shift_break_id: UUID | None
    break_start: str | None
    break_end: str | None
    minutes: int
    is_paid: bool
    is_excess: bool


def attendance_break_to_read(row: "AttendanceBreak") -> AttendanceBreakRead:
    return AttendanceBreakRead(
        id=row.id,
        attendance_day_id=row.attendance_day_id,
        shift_break_id=row.shift_break_id,
        break_start=_format_timestamp(row.break_start),
        break_end=_format_timestamp(row.break_end),
        minutes=row.minutes,
        is_paid=row.is_paid,
        is_excess=row.is_excess,
    )


class AttendanceDayRead(BaseModel):
    id: UUID
    company_id: UUID
    employee_id: UUID
    attendance_date: date
    timezone: str

    shift_id: UUID | None
    shift_version_id: UUID | None
    work_calendar_id: UUID | None
    attendance_policy_version_id: UUID | None
    overtime_policy_version_id: UUID | None
    regularization_policy_version_id: UUID | None

    calendar_day_type: str | None
    holiday_name: str | None
    holiday_on_weekly_off: bool

    scheduled_start: str | None
    scheduled_end: str | None
    scheduled_minutes: int | None

    actual_first_in: str | None
    actual_last_out: str | None
    worked_minutes: int
    unpaid_break_minutes: int
    paid_break_minutes: int
    excess_break_minutes: int

    attendance_status: str
    late_minutes: int
    early_departure_minutes: int
    late_classification: str | None
    early_departure_classification: str | None
    missing_punch: bool
    auto_closed: bool

    is_late: bool
    is_early_out: bool
    is_overtime: bool
    is_regularized: bool
    is_pending_approval: bool
    worked_on_holiday: bool
    worked_on_weekly_off: bool
    work_on_leave_flagged: bool
    work_on_leave_resolution: str | None
    work_on_leave_resolution_reason: str | None
    work_on_leave_resolved_by: UUID | None
    work_on_leave_resolved_at: str | None
    is_core_hours_breach: bool
    on_duty: bool
    on_duty_regularization_id: UUID | None

    paid_day_fraction: str
    lop_fraction: str
    leave_fraction: str
    weekly_off_fraction: str
    unpaid_off_fraction: str

    ot_minutes_detected: int
    ot_minutes_approved: int
    ot_pending: bool
    ot_classification: str | None
    ot_day_class: str | None
    comp_off_minutes_earned: int

    calculation_version: int
    engine_version: int | None
    computation_snapshot: dict[str, Any] | None
    calculated_at: str | None

    is_locked: bool
    locked_at: str | None
    locked_by: UUID | None

    breaks: list[AttendanceBreakRead]

    created_at: str
    updated_at: str


def attendance_day_to_read(
    row: "AttendanceDay", breaks: list["AttendanceBreak"]
) -> AttendanceDayRead:
    return AttendanceDayRead(
        id=row.id,
        company_id=row.company_id,
        employee_id=row.employee_id,
        attendance_date=row.attendance_date,
        timezone=row.timezone,
        shift_id=row.shift_id,
        shift_version_id=row.shift_version_id,
        work_calendar_id=row.work_calendar_id,
        attendance_policy_version_id=row.attendance_policy_version_id,
        overtime_policy_version_id=row.overtime_policy_version_id,
        regularization_policy_version_id=row.regularization_policy_version_id,
        calendar_day_type=row.calendar_day_type,
        holiday_name=row.holiday_name,
        holiday_on_weekly_off=row.holiday_on_weekly_off,
        scheduled_start=_format_timestamp(row.scheduled_start),
        scheduled_end=_format_timestamp(row.scheduled_end),
        scheduled_minutes=row.scheduled_minutes,
        actual_first_in=_format_timestamp(row.actual_first_in),
        actual_last_out=_format_timestamp(row.actual_last_out),
        worked_minutes=row.worked_minutes,
        unpaid_break_minutes=row.unpaid_break_minutes,
        paid_break_minutes=row.paid_break_minutes,
        excess_break_minutes=row.excess_break_minutes,
        attendance_status=row.attendance_status,
        late_minutes=row.late_minutes,
        early_departure_minutes=row.early_departure_minutes,
        late_classification=row.late_classification,
        early_departure_classification=row.early_departure_classification,
        missing_punch=row.missing_punch,
        auto_closed=row.auto_closed,
        is_late=row.is_late,
        is_early_out=row.is_early_out,
        is_overtime=row.is_overtime,
        is_regularized=row.is_regularized,
        is_pending_approval=row.is_pending_approval,
        worked_on_holiday=row.worked_on_holiday,
        worked_on_weekly_off=row.worked_on_weekly_off,
        work_on_leave_flagged=row.work_on_leave_flagged,
        work_on_leave_resolution=row.work_on_leave_resolution,
        work_on_leave_resolution_reason=row.work_on_leave_resolution_reason,
        work_on_leave_resolved_by=row.work_on_leave_resolved_by,
        work_on_leave_resolved_at=_format_timestamp(row.work_on_leave_resolved_at),
        is_core_hours_breach=row.is_core_hours_breach,
        on_duty=row.on_duty,
        on_duty_regularization_id=row.on_duty_regularization_id,
        paid_day_fraction=str(row.paid_day_fraction),
        lop_fraction=str(row.lop_fraction),
        leave_fraction=str(row.leave_fraction),
        weekly_off_fraction=str(row.weekly_off_fraction),
        unpaid_off_fraction=str(row.unpaid_off_fraction),
        ot_minutes_detected=row.ot_minutes_detected,
        ot_minutes_approved=row.ot_minutes_approved,
        ot_pending=row.ot_pending,
        ot_classification=row.ot_classification,
        ot_day_class=row.ot_day_class,
        comp_off_minutes_earned=row.comp_off_minutes_earned,
        calculation_version=row.calculation_version,
        engine_version=row.engine_version,
        computation_snapshot=row.computation_snapshot,
        calculated_at=_format_timestamp(row.calculated_at),
        is_locked=row.is_locked,
        locked_at=_format_timestamp(row.locked_at),
        locked_by=row.locked_by,
        breaks=[attendance_break_to_read(b) for b in breaks],
        created_at=_format_timestamp(row.created_at) or "",
        updated_at=_format_timestamp(row.updated_at) or "",
    )


def attendance_day_to_audit_dict(read: AttendanceDayRead) -> dict[str, Any]:
    return read.model_dump(mode="json")


# ---------------------------------------------------------------------------
# W6 — AttendanceRegularizationRequest / RequestedPunch / Action (architecture §13, WD-28)
# ---------------------------------------------------------------------------

_REGULARIZATION_STATUSES = ("SUBMITTED", "APPROVED", "REJECTED", "CANCELLED")
_APPROVAL_STAGES = ("MANAGER", "HR")
_REGULARIZATION_ACTIONS = (
    "SUBMITTED",
    "APPROVER_UNRESOLVED",
    "STAGE_APPROVED",
    "APPROVED",
    "REJECTED",
    "CANCELLED",
    "APPLIED",
)


class RegularizationRequestedPunchInput(BaseModel):
    """One requested IN/OUT instant — reuses `_PUNCH_DIRECTIONS` verbatim (WD-12: don't
    redefine a second direction enum).

    `requested_time` carries the same `AwareIsoDatetime` contract as the on-behalf punch route:
    regularization is the *other* legitimately client-time-accepting path (execution gate §7.2),
    so it gets the identical wire guard rather than a weaker one. It stays approval-gated — the
    instant only becomes a `punch` row once a reviewer approves it."""

    model_config = ConfigDict(extra="forbid")

    direction: str
    requested_time: AwareIsoDatetime

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, value: str) -> str:
        if value not in _PUNCH_DIRECTIONS:
            raise ValueError(f"direction must be one of {_PUNCH_DIRECTIONS}")
        return value


class RegularizationRequestedPunchRead(BaseModel):
    id: UUID
    direction: str
    requested_time: str
    sort_order: int


def requested_punch_to_read(
    row: "AttendanceRegularizationRequestedPunch",
) -> RegularizationRequestedPunchRead:
    return RegularizationRequestedPunchRead(
        id=row.id,
        direction=row.direction,
        requested_time=_format_timestamp(row.requested_time) or "",
        sort_order=row.sort_order,
    )


class RegularizationActionRead(BaseModel):
    id: UUID
    action: str
    actor_user_id: UUID | None
    actor_employee_id: UUID | None
    stage: str | None
    comment: str | None
    created_at: str


def regularization_action_to_read(
    row: "AttendanceRegularizationAction",
) -> RegularizationActionRead:
    return RegularizationActionRead(
        id=row.id,
        action=row.action,
        actor_user_id=row.actor_user_id,
        actor_employee_id=row.actor_employee_id,
        stage=row.stage,
        comment=row.comment,
        created_at=_format_timestamp(row.created_at) or "",
    )


class RegularizationRequestCreate(BaseModel):
    """Shared by self-submit and on-behalf-submit (router decides `employee_id` — architecture
    §23.2: self is SELF-scoped, on-behalf is COMPANY-scoped). WD-28 decision 2: every request
    must carry `requested_punches` and/or `requested_shift_id` so an approval always has a
    well-defined, engine-supported effect.

    Note this schema keeps the single-endpoint, body-decides-`employee_id` shape that the punch
    routes deliberately moved away from in Phase 1 (`ED-4`). That is intentional and not an
    oversight: regularization is approval-gated end to end, so the body cannot select a
    *privilege* here the way it could on the punch path — the reviewer, not the submitter,
    decides whether anything is written."""

    model_config = ConfigDict(extra="forbid")

    employee_id: UUID | None = None
    attendance_date: date
    request_type: str
    reason: str | None = None
    requested_shift_id: UUID | None = None
    attachment_reference: str | None = Field(default=None, max_length=500)
    requested_punches: list[RegularizationRequestedPunchInput] = Field(default_factory=list)

    @field_validator("request_type")
    @classmethod
    def validate_request_type(cls, value: str) -> str:
        if value not in _REGULARIZATION_TYPES:
            raise ValueError(f"request_type must be one of {_REGULARIZATION_TYPES}")
        return value

    @model_validator(mode="after")
    def validate_correction_payload(self) -> "RegularizationRequestCreate":
        if not self.requested_punches and self.requested_shift_id is None:
            raise ValueError(
                "requested_punches or requested_shift_id is required — see WD-28 decision 2"
            )
        return self


class RegularizationReviewInput(BaseModel):
    """Body for approve/reject. `rejection_reason` is only meaningful (and only persisted) on
    reject; the service ignores it on approve rather than erroring, since a caller-supplied
    but-unused field on the wrong action is not itself invalid input."""

    model_config = ConfigDict(extra="forbid")

    reviewer_comment: str | None = None
    rejection_reason: str | None = None


class RegularizationRequestRead(BaseModel):
    id: UUID
    company_id: UUID
    employee_id: UUID
    attendance_day_id: UUID | None
    attendance_date: date

    request_type: str
    reason: str | None
    requested_shift_id: UUID | None
    attachment_reference: str | None

    status: str
    approval_chain: str
    approval_stage: str | None
    regularization_policy_version_id: UUID
    resolved_approver_manager_id: UUID | None

    submitted_by_user_id: UUID | None
    submitted_at: str

    reviewed_by_user_id: UUID | None
    reviewed_at: str | None
    reviewer_comment: str | None
    rejection_reason: str | None

    applied_at: str | None
    cancelled_at: str | None
    cancelled_by_user_id: UUID | None

    version: int

    requested_punches: list[RegularizationRequestedPunchRead]
    actions: list[RegularizationActionRead]

    created_at: str
    updated_at: str


def regularization_request_to_read(
    row: "AttendanceRegularizationRequest",
    *,
    requested_punches: list["AttendanceRegularizationRequestedPunch"],
    actions: list["AttendanceRegularizationAction"],
) -> RegularizationRequestRead:
    return RegularizationRequestRead(
        id=row.id,
        company_id=row.company_id,
        employee_id=row.employee_id,
        attendance_day_id=row.attendance_day_id,
        attendance_date=row.attendance_date,
        request_type=row.request_type,
        reason=row.reason,
        requested_shift_id=row.requested_shift_id,
        attachment_reference=row.attachment_reference,
        status=row.status,
        approval_chain=row.approval_chain,
        approval_stage=row.approval_stage,
        regularization_policy_version_id=row.regularization_policy_version_id,
        resolved_approver_manager_id=row.resolved_approver_manager_id,
        submitted_by_user_id=row.submitted_by_user_id,
        submitted_at=_format_timestamp(row.submitted_at) or "",
        reviewed_by_user_id=row.reviewed_by_user_id,
        reviewed_at=_format_timestamp(row.reviewed_at),
        reviewer_comment=row.reviewer_comment,
        rejection_reason=row.rejection_reason,
        applied_at=_format_timestamp(row.applied_at),
        cancelled_at=_format_timestamp(row.cancelled_at),
        cancelled_by_user_id=row.cancelled_by_user_id,
        version=row.version,
        requested_punches=[requested_punch_to_read(p) for p in requested_punches],
        actions=[regularization_action_to_read(a) for a in actions],
        created_at=_format_timestamp(row.created_at) or "",
        updated_at=_format_timestamp(row.updated_at) or "",
    )


def regularization_request_to_audit_dict(read: RegularizationRequestRead) -> dict[str, Any]:
    return read.model_dump(mode="json")


# ---------------------------------------------------------------------------
# W7 — OvertimeRecord / OvertimeAction (architecture §12, decision log WD-29)
# ---------------------------------------------------------------------------


class OvertimeReviewInput(BaseModel):
    """Body for approve/reject — identical shape to `RegularizationReviewInput`."""

    model_config = ConfigDict(extra="forbid")

    reviewer_comment: str | None = None
    rejection_reason: str | None = None


class OvertimeActionRead(BaseModel):
    id: UUID
    action: str
    actor_user_id: UUID | None
    actor_employee_id: UUID | None
    stage: str | None
    comment: str | None
    created_at: str


def overtime_action_to_read(row: "OvertimeAction") -> OvertimeActionRead:
    return OvertimeActionRead(
        id=row.id,
        action=row.action,
        actor_user_id=row.actor_user_id,
        actor_employee_id=row.actor_employee_id,
        stage=row.stage,
        comment=row.comment,
        created_at=_format_timestamp(row.created_at) or "",
    )


class OvertimeRecordRead(BaseModel):
    id: UUID
    company_id: UUID
    employee_id: UUID
    attendance_day_id: UUID
    attendance_date: date
    overtime_policy_version_id: UUID

    day_class: str | None
    classification_code: str | None
    configured_multiplier: str | None

    minutes_detected: int
    minutes_approved: int

    status: str
    approval_chain: str
    approval_stage: str | None
    resolved_approver_manager_id: UUID | None

    reviewed_by_user_id: UUID | None
    reviewed_at: str | None
    reviewer_comment: str | None
    rejection_reason: str | None

    comp_off_minutes: int
    comp_off_expiry_date: date | None

    version: int

    actions: list[OvertimeActionRead]

    created_at: str
    updated_at: str


def overtime_record_to_read(
    row: "OvertimeRecord", *, actions: list["OvertimeAction"]
) -> OvertimeRecordRead:
    return OvertimeRecordRead(
        id=row.id,
        company_id=row.company_id,
        employee_id=row.employee_id,
        attendance_day_id=row.attendance_day_id,
        attendance_date=row.attendance_date,
        overtime_policy_version_id=row.overtime_policy_version_id,
        day_class=row.day_class,
        classification_code=row.classification_code,
        configured_multiplier=(
            str(row.configured_multiplier) if row.configured_multiplier is not None else None
        ),
        minutes_detected=row.minutes_detected,
        minutes_approved=row.minutes_approved,
        status=row.status,
        approval_chain=row.approval_chain,
        approval_stage=row.approval_stage,
        resolved_approver_manager_id=row.resolved_approver_manager_id,
        reviewed_by_user_id=row.reviewed_by_user_id,
        reviewed_at=_format_timestamp(row.reviewed_at),
        reviewer_comment=row.reviewer_comment,
        rejection_reason=row.rejection_reason,
        comp_off_minutes=row.comp_off_minutes,
        comp_off_expiry_date=row.comp_off_expiry_date,
        version=row.version,
        actions=[overtime_action_to_read(a) for a in actions],
        created_at=_format_timestamp(row.created_at) or "",
        updated_at=_format_timestamp(row.updated_at) or "",
    )


def overtime_record_to_audit_dict(read: OvertimeRecordRead) -> dict[str, Any]:
    return read.model_dump(mode="json")


# ---------------------------------------------------------------------------
# W8 — AttendancePeriod (architecture §4.2/§22, decision log WD-30)
# ---------------------------------------------------------------------------

_ATTENDANCE_PERIOD_STATUSES = ("OPEN", "CLOSED")
_ATTENDANCE_PERIOD_VALIDATION_STATUSES = ("READY", "BLOCKED")
_ATTENDANCE_PERIOD_BLOCKING_REASON_CODES = (
    "EMPLOYEES_WITHOUT_ATTENDANCE",
    "CONFIG_ERROR",
    "INCOMPLETE_ATTENDANCE",
    "PENDING_REGULARIZATION",
    "PENDING_OVERTIME_APPROVAL",
    "UNPUBLISHED_ROSTER",
)


class AttendancePeriodCreate(BaseModel):
    """Create always opens immediately — no separate "open" action, mirroring WD-28's
    no-DRAFT-state precedent (a period isn't useful in a created-but-not-open state; every date
    inside it is mutable/computable from the instant it exists).

    Decision 14 — one legal entity per period. Decision 18 — the cycle is a full calendar month
    by default: send `month` (`YYYY-MM`) and the 1st-to-last-day range is derived from it (and a
    "September 2026"-style label when none is given). An explicit `period_start`/`period_end`
    pair is still accepted for an off-cycle period; send one form or the other, not both."""

    model_config = ConfigDict(extra="forbid")

    legal_entity_id: UUID
    month: str | None = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    period_start: date | None = None
    period_end: date | None = None
    label: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_range(self) -> "AttendancePeriodCreate":
        has_range = self.period_start is not None or self.period_end is not None
        if self.month is not None:
            if has_range:
                raise ValueError("Send either month or period_start/period_end, not both")
            year, month = (int(part) for part in self.month.split("-"))
            self.period_start = date(year, month, 1)
            self.period_end = date(year, month, calendar.monthrange(year, month)[1])
            if self.label is None:
                self.label = self.period_start.strftime("%B %Y")
            return self
        if self.period_start is None or self.period_end is None:
            raise ValueError("Send month, or both period_start and period_end")
        if self.period_end < self.period_start:
            raise ValueError("period_end must not be before period_start")
        return self


#: PAY-001 — the longest range one backfill request may cover (two months), bounding a single
#: queued job for a large company to a size that finishes in reasonable time.
RANGE_CALCULATE_MAX_DAYS = 62


class AttendanceRangeCalculateInput(BaseModel):
    """PAY-001 — backfill every employed day in `[date_from, date_to]` (company-local business
    dates), optionally only for `employee_ids`."""

    model_config = ConfigDict(extra="forbid")

    date_from: date
    date_to: date
    employee_ids: list[UUID] | None = Field(default=None, min_length=1, max_length=1000)
    #: Decision 14 — only employment spells in this legal entity (one entity's period).
    legal_entity_id: UUID | None = None

    @model_validator(mode="after")
    def validate_range(self) -> "AttendanceRangeCalculateInput":
        if self.date_to < self.date_from:
            raise ValueError("date_to must be on or after date_from")
        if (self.date_to - self.date_from).days + 1 > RANGE_CALCULATE_MAX_DAYS:
            raise ValueError(f"A range may cover at most {RANGE_CALCULATE_MAX_DAYS} days")
        return self


class AttendanceRangeCalculateQueued(BaseModel):
    task_id: str
    date_from: date
    date_to: date
    employee_ids: list[UUID] | None
    legal_entity_id: UUID | None = None


class WorkOnLeaveKeepLeaveInput(BaseModel):
    """BUS-012 — HR confirms an approved full-day leave stands over punches on the same day."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=1000)


class AttendancePeriodReopenInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=1000)


class AttendancePeriodActionRead(BaseModel):
    id: UUID
    action: str
    actor_user_id: UUID | None
    comment: str | None
    created_at: str


def attendance_period_action_to_read(row: "AttendancePeriodAction") -> AttendancePeriodActionRead:
    return AttendancePeriodActionRead(
        id=row.id,
        action=row.action,
        actor_user_id=row.actor_user_id,
        comment=row.comment,
        created_at=_format_timestamp(row.created_at) or "",
    )


class AttendancePeriodRead(BaseModel):
    id: UUID
    company_id: UUID
    legal_entity_id: UUID
    period_start: date
    period_end: date
    label: str | None
    status: str

    opened_by_user_id: UUID | None
    opened_at: str

    last_validated_at: str | None
    last_validation_status: str | None

    closed_by_user_id: UUID | None
    closed_at: str | None

    reopened_by_user_id: UUID | None
    reopened_at: str | None
    reopen_reason: str | None

    version: int
    actions: list[AttendancePeriodActionRead]
    created_at: str
    updated_at: str


def attendance_period_to_read(
    row: "AttendancePeriod", *, actions: list["AttendancePeriodAction"]
) -> AttendancePeriodRead:
    return AttendancePeriodRead(
        id=row.id,
        company_id=row.company_id,
        legal_entity_id=row.legal_entity_id,
        period_start=row.period_start,
        period_end=row.period_end,
        label=row.label,
        status=row.status,
        opened_by_user_id=row.opened_by_user_id,
        opened_at=_format_timestamp(row.opened_at) or "",
        last_validated_at=_format_timestamp(row.last_validated_at),
        last_validation_status=row.last_validation_status,
        closed_by_user_id=row.closed_by_user_id,
        closed_at=_format_timestamp(row.closed_at),
        reopened_by_user_id=row.reopened_by_user_id,
        reopened_at=_format_timestamp(row.reopened_at),
        reopen_reason=row.reopen_reason,
        version=row.version,
        actions=[attendance_period_action_to_read(a) for a in actions],
        created_at=_format_timestamp(row.created_at) or "",
        updated_at=_format_timestamp(row.updated_at) or "",
    )


def attendance_period_to_audit_dict(read: AttendancePeriodRead) -> dict[str, Any]:
    return read.model_dump(mode="json")


class AttendancePeriodBlockingReason(BaseModel):
    """One typed blocking bucket. `count` is the number of underlying rows/employees in this
    bucket; `sample` carries up to 20 identifying values (employee ids, or `employee_id:date`
    pairs) so the caller can navigate straight to the first few offenders without a second,
    unbounded query."""

    code: str
    message: str
    count: int
    sample: list[str]


class AttendancePeriodValidationRead(BaseModel):
    status: str
    reasons: list[AttendancePeriodBlockingReason]
    validated_at: str


class AttendancePeriodSummaryRead(BaseModel):
    employee_id: UUID
    present_days: str
    absent_days: str
    leave_days: str
    holiday_days: str
    weekly_off_days: str
    half_days: str
    lop_days: str
    # PAY-002/PAY-003 — None only on a summary frozen before these fields existed (old,
    # overlapping bucket semantics); Payroll must refuse such a summary.
    on_duty_days: str | None
    incomplete_days: str | None
    not_employed_days: str | None
    unpaid_off_days: str | None
    paid_days: str | None
    payable_days: str | None
    ot_minutes_normal: int
    ot_minutes_weekly_off: int
    ot_minutes_holiday: int
    ot_minutes_night: int
    comp_off_minutes_earned: int
    late_count: int
    worked_minutes_total: int
    generated_at: str
    frozen: bool


def _optional_decimal_str(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def attendance_period_summary_to_read(
    row: "AttendancePeriodSummary", *, frozen: bool
) -> AttendancePeriodSummaryRead:
    return AttendancePeriodSummaryRead(
        employee_id=row.employee_id,
        present_days=str(row.present_days),
        absent_days=str(row.absent_days),
        leave_days=str(row.leave_days),
        holiday_days=str(row.holiday_days),
        weekly_off_days=str(row.weekly_off_days),
        half_days=str(row.half_days),
        lop_days=str(row.lop_days),
        on_duty_days=_optional_decimal_str(row.on_duty_days),
        incomplete_days=_optional_decimal_str(row.incomplete_days),
        not_employed_days=_optional_decimal_str(row.not_employed_days),
        unpaid_off_days=_optional_decimal_str(row.unpaid_off_days),
        paid_days=_optional_decimal_str(row.paid_days),
        payable_days=_optional_decimal_str(row.payable_days),
        ot_minutes_normal=row.ot_minutes_normal,
        ot_minutes_weekly_off=row.ot_minutes_weekly_off,
        ot_minutes_holiday=row.ot_minutes_holiday,
        ot_minutes_night=row.ot_minutes_night,
        comp_off_minutes_earned=row.comp_off_minutes_earned,
        late_count=row.late_count,
        worked_minutes_total=row.worked_minutes_total,
        generated_at=_format_timestamp(row.generated_at) or "",
        frozen=frozen,
    )


# ---------------------------------------------------------------------------
# W9 — LeaveDayProjection (architecture §21, decision log WD-31)
# ---------------------------------------------------------------------------

_LEAVE_PROJECTION_FRACTIONS = ("0.50", "1.00")
_LEAVE_PROJECTION_HALVES = ("FIRST", "SECOND")


class LeaveProjectionSync(BaseModel):
    """Publishes (or republishes, as a correction) one approved leave day projection —
    architecture §21's `LeaveDayProjection` read model. Fail-closed per Phase 2: `fraction` and
    `half` are typed/validated here, not left as free-form numbers; the cross-row "active
    fractions for this employee-date must not exceed 1.00" check happens in the service layer,
    where the other active rows are visible."""

    model_config = ConfigDict(extra="forbid")

    employee_id: UUID
    attendance_date: date
    leave_application_id: UUID
    leave_type_id: UUID | None = None
    leave_type_code: str | None = Field(default=None, max_length=30)
    fraction: str
    half: str | None = None
    is_paid: bool

    @field_validator("fraction")
    @classmethod
    def validate_fraction(cls, value: str) -> str:
        if value not in _LEAVE_PROJECTION_FRACTIONS:
            raise ValueError(f"fraction must be one of {_LEAVE_PROJECTION_FRACTIONS}")
        return value

    @field_validator("half")
    @classmethod
    def validate_half(cls, value: str | None) -> str | None:
        if value is not None and value not in _LEAVE_PROJECTION_HALVES:
            raise ValueError(f"half must be one of {_LEAVE_PROJECTION_HALVES}")
        return value

    @model_validator(mode="after")
    def _validate_half_matches_fraction(self) -> "LeaveProjectionSync":
        if self.fraction == "0.50" and self.half is None:
            raise ValueError("half is required (FIRST|SECOND) when fraction is 0.50")
        if self.fraction == "1.00" and self.half is not None:
            raise ValueError("half must be omitted when fraction is 1.00")
        return self


class LeaveProjectionCancelInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=1000)


class LeaveDayProjectionRead(BaseModel):
    id: UUID
    company_id: UUID
    employee_id: UUID
    attendance_date: date
    leave_application_id: UUID
    leave_type_id: UUID | None
    leave_type_code: str | None
    fraction: str
    half: str | None
    is_paid: bool
    status: str
    source_version: int
    synced_at: str
    cancelled_at: str | None
    cancelled_reason: str | None
    version: int
    created_at: str
    updated_at: str


def leave_day_projection_to_read(row: "LeaveDayProjection") -> LeaveDayProjectionRead:
    return LeaveDayProjectionRead(
        id=row.id,
        company_id=row.company_id,
        employee_id=row.employee_id,
        attendance_date=row.attendance_date,
        leave_application_id=row.leave_application_id,
        leave_type_id=row.leave_type_id,
        leave_type_code=row.leave_type_code,
        fraction=str(row.fraction),
        half=row.half,
        is_paid=row.is_paid,
        status=row.status,
        source_version=row.source_version,
        synced_at=_format_timestamp(row.synced_at) or "",
        cancelled_at=_format_timestamp(row.cancelled_at),
        cancelled_reason=row.cancelled_reason,
        version=row.version,
        created_at=_format_timestamp(row.created_at) or "",
        updated_at=_format_timestamp(row.updated_at) or "",
    )


def leave_day_projection_to_audit_dict(read: LeaveDayProjectionRead) -> dict[str, Any]:
    return read.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Face attendance
# ---------------------------------------------------------------------------

FACE_IMAGE_MAX_BYTES = 5 * 1024 * 1024
#: Self-enrollment captures, in order. "front" is the anchor: it must pass liveness and every
#: other angle must match it.
FACE_ENROLLMENT_ANGLES = ("front", "left", "right", "up", "down")


class FaceProfileRead(BaseModel):
    """Never exposes `provider_person_id` (a handle into the vendor's biometric store) or the
    review photo's storage key."""

    id: UUID
    employee_id: UUID
    provider: str
    status: str
    reference_photo_count: int
    consent_recorded_at: str
    enrolled_at: str
    enrolled_by_user_id: UUID | None
    has_review_photo: bool
    reviewed_at: str | None
    reviewed_by_user_id: UUID | None
    review_note: str | None
    revoked_at: str | None
    revoked_by_user_id: UUID | None


def face_profile_to_read(row: "EmployeeFaceProfile") -> FaceProfileRead:
    return FaceProfileRead(
        id=row.id,
        employee_id=row.employee_id,
        provider=row.provider,
        status=row.status,
        reference_photo_count=row.reference_photo_count,
        consent_recorded_at=_format_timestamp(row.consent_recorded_at) or "",
        enrolled_at=_format_timestamp(row.enrolled_at) or "",
        enrolled_by_user_id=row.enrolled_by_user_id,
        has_review_photo=row.review_photo_key is not None,
        reviewed_at=_format_timestamp(row.reviewed_at),
        reviewed_by_user_id=row.reviewed_by_user_id,
        review_note=row.review_note,
        revoked_at=_format_timestamp(row.revoked_at),
        revoked_by_user_id=row.revoked_by_user_id,
    )


class FaceEnrollmentWindowRead(BaseModel):
    id: UUID
    employee_id: UUID
    status: str
    opened_by_user_id: UUID | None
    opened_at: str
    expires_at: str


def face_window_to_read(row: "FaceEnrollmentWindow") -> FaceEnrollmentWindowRead:
    return FaceEnrollmentWindowRead(
        id=row.id,
        employee_id=row.employee_id,
        status=row.status,
        opened_by_user_id=row.opened_by_user_id,
        opened_at=_format_timestamp(row.opened_at) or "",
        expires_at=_format_timestamp(row.expires_at) or "",
    )


class FaceEnrollmentStatusRead(BaseModel):
    """Everything a screen needs to decide what to show: the profile (if any) and the currently
    usable enrollment window (OPEN and unexpired), if any."""

    profile: FaceProfileRead | None
    open_window: FaceEnrollmentWindowRead | None


class FaceProfileRejectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=500)


class FacePunchRead(BaseModel):
    """`POST /attendance/face-punches/me` — the punch recorded plus the scores that justified it."""

    punch: PunchRead
    similarity: Decimal
    liveness_score: Decimal | None = None
