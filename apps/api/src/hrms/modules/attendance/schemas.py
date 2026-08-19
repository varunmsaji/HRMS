"""Pydantic request/response shapes for the attendance module (W3)."""

from datetime import date, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

if TYPE_CHECKING:
    from hrms.modules.attendance.models import (
        AttendanceBreak,
        AttendanceDay,
        AttendancePolicy,
        AttendancePolicyEarlyDepartureBand,
        AttendancePolicyHourBand,
        AttendancePolicyLateBand,
        AttendancePolicyVersion,
        OvertimePolicy,
        OvertimePolicyRateRow,
        OvertimePolicyVersion,
        Punch,
        RegularizationPolicy,
        RegularizationPolicyAllowedType,
        RegularizationPolicyVersion,
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
)

_POLICY_RESOLUTION_KINDS = ("ATTENDANCE_POLICY", "OVERTIME_POLICY", "REGULARIZATION_POLICY")


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
        field: getattr(patch, field)
        for field in patch.model_fields_set
        if field != "allowed_types"
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
# W4 — Punch / AttendanceDay / AttendanceBreak
# ---------------------------------------------------------------------------

_PUNCH_DIRECTIONS = ("IN", "OUT")
_PUNCH_SOURCES = ("WEB", "MOBILE", "DEVICE", "IMPORT", "ADMIN", "API")
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


class PunchCreate(BaseModel):
    """Shared by both `POST /attendance/punches` (self) and the on-behalf variant — the router
    decides `employee_id` (forces the caller's own for self-punch, requires it in the body for
    on-behalf), not this schema (architecture §23.2: `ATTENDANCE.PUNCH` is SELF,
    `ATTENDANCE.PUNCH_ON_BEHALF` is COMPANY). `source` defaults to `None` (not `"WEB"`) so the
    router's `default_source` (`WEB` for self, `ADMIN` for on-behalf) actually takes effect
    unless the caller explicitly overrides it — a truthy default here would silently defeat
    that fallback for every on-behalf punch."""

    model_config = ConfigDict(extra="forbid")

    employee_id: UUID | None = None
    punch_time: datetime | None = None
    direction: str
    source: str | None = None
    reference: str | None = Field(default=None, max_length=200)
    idempotency_key: str | None = Field(default=None, max_length=100)

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, value: str) -> str:
        if value not in _PUNCH_DIRECTIONS:
            raise ValueError(f"direction must be one of {_PUNCH_DIRECTIONS}")
        return value

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str | None) -> str | None:
        if value is not None and value not in _PUNCH_SOURCES:
            raise ValueError(f"source must be one of {_PUNCH_SOURCES}")
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

    paid_day_fraction: str
    lop_fraction: str

    ot_minutes_detected: int
    ot_minutes_approved: int
    ot_pending: bool
    ot_classification: str | None
    comp_off_minutes_earned: int

    calculation_version: int
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
        paid_day_fraction=str(row.paid_day_fraction),
        lop_fraction=str(row.lop_fraction),
        ot_minutes_detected=row.ot_minutes_detected,
        ot_minutes_approved=row.ot_minutes_approved,
        ot_pending=row.ot_pending,
        ot_classification=row.ot_classification,
        comp_off_minutes_earned=row.comp_off_minutes_earned,
        calculation_version=row.calculation_version,
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
