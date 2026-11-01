"""Request/response schemas for break events and employee break overrides (break management V1).

No schema here carries a client-supplied `source`, `employee_id` (self routes) or event time
(self routes): the server assigns all three, exactly like `PunchCreateSelf`."""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from hrms.modules.attendance.models import AttendanceBreakEvent, EmployeeBreakOverride
from hrms.modules.organisation.schemas import (
    SHIFT_BREAK_EXCESS_OUTCOMES,
    SHIFT_BREAK_MODES,
    SHIFT_BREAK_TYPES,
)

_TIME_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"
_BREAK_KINDS = ("FIXED_WINDOW", "FLEXIBLE_DURATION")
OVERRIDE_ACTIONS = ("REPLACE", "ADD", "DISABLE")


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


# --- employee self-service -------------------------------------------------------------------


class BreakActionSelf(BaseModel):
    """Body for `POST /attendance/breaks/me/start` and `.../end`. The break is named, never
    inferred; the instant is the server's clock."""

    model_config = ConfigDict(extra="forbid")

    break_name: str | None = Field(default=None, min_length=1, max_length=100)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=100)
    #: Display/analytics only (which app recorded it); never an authorization input.
    client: Literal["WEB", "MOBILE"] = "WEB"


class BreakRuleRead(BaseModel):
    """One resolved break rule, as the employee's app needs to render it."""

    name: str
    break_type: str
    mode: str | None
    is_paid: bool
    is_mandatory: bool
    scheduled_start: str | None
    scheduled_end: str | None
    scheduled_minutes: int | None
    min_minutes: int | None
    max_minutes: int | None
    rule_source: str
    can_punch: bool
    taken: bool


class ActiveBreakRead(BaseModel):
    event_id: UUID
    break_name: str | None
    break_type: str | None
    is_paid: bool | None
    started_at: str
    max_minutes: int | None


class CompletedBreakRead(BaseModel):
    break_name: str | None
    started_at: str
    ended_at: str
    minutes: int
    is_approved: bool


class BreakStateRead(BaseModel):
    """The backend's answer to "what can this employee do about breaks right now" — the mobile
    app renders this and never trusts local state."""

    attendance_date: date | None
    shift_name_known: bool
    checked_in: bool
    checked_out: bool
    can_start: bool
    can_end: bool
    punching: Literal["NONE", "MANDATORY", "OPTIONAL"]
    active_break: ActiveBreakRead | None
    rules: list[BreakRuleRead]
    completed: list[CompletedBreakRead]
    server_time: str


# --- events ----------------------------------------------------------------------------------


class BreakEventRead(BaseModel):
    id: UUID
    employee_id: UUID
    attendance_date: date
    event_type: str
    event_time: str
    break_name: str | None
    shift_break_id: UUID | None
    source: str
    recorded_by_user_id: UUID | None
    approved_by_user_id: UUID | None
    supersedes_event_id: UUID | None
    regularization_request_id: UUID | None
    reason: str | None
    created_at: str


def break_event_to_read(row: AttendanceBreakEvent) -> BreakEventRead:
    return BreakEventRead(
        id=row.id,
        employee_id=row.employee_id,
        attendance_date=row.attendance_date,
        event_type=row.event_type,
        event_time=_iso(row.event_time) or "",
        break_name=row.break_name,
        shift_break_id=row.shift_break_id,
        source=row.source,
        recorded_by_user_id=row.recorded_by_user_id,
        approved_by_user_id=row.approved_by_user_id,
        supersedes_event_id=row.supersedes_event_id,
        regularization_request_id=row.regularization_request_id,
        reason=row.reason,
        created_at=_iso(row.created_at) or "",
    )


def break_event_to_audit_dict(read: BreakEventRead) -> dict[str, Any]:
    return read.model_dump(mode="json")


class BreakResolveInput(BaseModel):
    """HR / authorised-manager correction of one break, by the START event it belongs to.
    Writes new events that supersede the old ones — nothing is edited. Provide the corrected
    end instant, or the approved actual duration in minutes (measured from the START)."""

    model_config = ConfigDict(extra="forbid")

    start_event_id: UUID
    corrected_end: datetime | None = None
    approved_minutes: int | None = Field(default=None, ge=0, le=1440)
    reason: str = Field(min_length=3, max_length=500)

    @model_validator(mode="after")
    def exactly_one_resolution(self) -> "BreakResolveInput":
        if (self.corrected_end is None) == (self.approved_minutes is None):
            raise ValueError("provide exactly one of corrected_end or approved_minutes")
        if self.corrected_end is not None and self.corrected_end.tzinfo is None:
            raise ValueError("corrected_end must include a timezone offset")
        return self


class BreakDayRead(BaseModel):
    """Break detail for one employee-date, as HR reviews it."""

    employee_id: UUID
    attendance_date: date
    events: list[BreakEventRead]


# --- employee overrides ----------------------------------------------------------------------


class EmployeeBreakOverrideCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    employee_id: UUID
    action: str
    target_break_name: str | None = Field(default=None, min_length=1, max_length=100)
    shift_id: UUID | None = None
    effective_from: date
    effective_to: date | None = None
    reason: str = Field(min_length=3, max_length=500)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    break_type: str | None = None
    break_kind: str | None = None
    mode: str | None = None
    start_time: str | None = Field(default=None, pattern=_TIME_PATTERN)
    end_time: str | None = Field(default=None, pattern=_TIME_PATTERN)
    window_start: str | None = Field(default=None, pattern=_TIME_PATTERN)
    window_end: str | None = Field(default=None, pattern=_TIME_PATTERN)
    min_minutes: int | None = Field(default=None, ge=0)
    max_minutes: int | None = Field(default=None, ge=1)
    scheduled_minutes: int | None = Field(default=None, ge=1)
    is_paid: bool | None = None
    is_mandatory: bool | None = None
    excess_outcome: str | None = None
    auto_deduct_full: bool | None = None
    optional_recorded_deducts: bool | None = None
    optional_scheduled_fallback: bool | None = None
    sort_order: int | None = None

    @field_validator("action")
    @classmethod
    def _action(cls, value: str) -> str:
        if value not in OVERRIDE_ACTIONS:
            raise ValueError(f"action must be one of {OVERRIDE_ACTIONS}")
        return value

    @field_validator("mode")
    @classmethod
    def _mode(cls, value: str | None) -> str | None:
        if value is not None and value not in SHIFT_BREAK_MODES:
            raise ValueError(f"mode must be one of {SHIFT_BREAK_MODES}")
        return value

    @field_validator("break_type")
    @classmethod
    def _type(cls, value: str | None) -> str | None:
        if value is not None and value not in SHIFT_BREAK_TYPES:
            raise ValueError(f"break_type must be one of {SHIFT_BREAK_TYPES}")
        return value

    @field_validator("break_kind")
    @classmethod
    def _kind(cls, value: str | None) -> str | None:
        if value is not None and value not in _BREAK_KINDS:
            raise ValueError(f"break_kind must be one of {_BREAK_KINDS}")
        return value

    @field_validator("excess_outcome")
    @classmethod
    def _outcome(cls, value: str | None) -> str | None:
        if value is not None and value not in SHIFT_BREAK_EXCESS_OUTCOMES:
            raise ValueError(f"excess_outcome must be one of {SHIFT_BREAK_EXCESS_OUTCOMES}")
        return value

    @model_validator(mode="after")
    def _shape(self) -> "EmployeeBreakOverrideCreate":
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to must not be before effective_from")
        if self.action in ("REPLACE", "DISABLE") and not self.target_break_name:
            raise ValueError("target_break_name is required for REPLACE and DISABLE")
        if self.action == "ADD":
            if not self.name:
                raise ValueError("name is required for ADD")
            if self.break_kind is None:
                raise ValueError("break_kind is required for ADD")
            if self.mode is None:
                raise ValueError("mode is required for ADD")
        if self.action == "DISABLE":
            changed = [
                k
                for k in (
                    "name",
                    "break_type",
                    "break_kind",
                    "mode",
                    "start_time",
                    "end_time",
                    "window_start",
                    "window_end",
                    "min_minutes",
                    "max_minutes",
                    "scheduled_minutes",
                    "is_paid",
                    "is_mandatory",
                    "excess_outcome",
                )
                if getattr(self, k) is not None
            ]
            if changed:
                raise ValueError("DISABLE takes no break fields")
        return self


class EmployeeBreakOverrideRevoke(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=500)


class EmployeeBreakOverrideRead(BaseModel):
    id: UUID
    employee_id: UUID
    shift_id: UUID | None
    action: str
    target_break_name: str | None
    effective_from: date
    effective_to: date | None
    reason: str
    name: str | None
    break_type: str | None
    break_kind: str | None
    mode: str | None
    start_time: str | None
    end_time: str | None
    window_start: str | None
    window_end: str | None
    min_minutes: int | None
    max_minutes: int | None
    scheduled_minutes: int | None
    is_paid: bool | None
    is_mandatory: bool | None
    excess_outcome: str | None
    auto_deduct_full: bool | None
    optional_recorded_deducts: bool | None
    optional_scheduled_fallback: bool | None
    sort_order: int | None
    created_by: UUID | None
    created_at: str
    revoked_at: str | None
    revoked_by: UUID | None
    revoke_reason: str | None


def _clock(value: Any) -> str | None:
    return value.strftime("%H:%M") if value is not None else None


def override_to_read(row: EmployeeBreakOverride) -> EmployeeBreakOverrideRead:
    return EmployeeBreakOverrideRead(
        id=row.id,
        employee_id=row.employee_id,
        shift_id=row.shift_id,
        action=row.action,
        target_break_name=row.target_break_name,
        effective_from=row.effective_from,
        effective_to=row.effective_to,
        reason=row.reason,
        name=row.name,
        break_type=row.break_type,
        break_kind=row.break_kind,
        mode=row.mode,
        start_time=_clock(row.start_time),
        end_time=_clock(row.end_time),
        window_start=_clock(row.window_start),
        window_end=_clock(row.window_end),
        min_minutes=row.min_minutes,
        max_minutes=row.max_minutes,
        scheduled_minutes=row.scheduled_minutes,
        is_paid=row.is_paid,
        is_mandatory=row.is_mandatory,
        excess_outcome=row.excess_outcome,
        auto_deduct_full=row.auto_deduct_full,
        optional_recorded_deducts=row.optional_recorded_deducts,
        optional_scheduled_fallback=row.optional_scheduled_fallback,
        sort_order=row.sort_order,
        created_by=row.created_by,
        created_at=_iso(row.created_at) or "",
        revoked_at=_iso(row.revoked_at),
        revoked_by=row.revoked_by,
        revoke_reason=row.revoke_reason,
    )


class ResolvedBreakRulesRead(BaseModel):
    """What the engine will use for one employee on one date — shift defaults with the
    employee's overrides applied, each rule labelled with where it came from."""

    employee_id: UUID
    date: date
    shift_id: UUID | None
    shift_version_id: UUID | None
    rules: list[BreakRuleRead]
    overrides_applied: list[dict[str, str | None]]
