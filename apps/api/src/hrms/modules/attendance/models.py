"""ORM models owned by the attendance module (W3 —
docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md §11-13, WD-02/WD-03).

Three independent versioned policy identities (WD-03 — locked, not one mega-policy):
`AttendancePolicy` (grace/rounding/bands/missing-punch/breaks/flex/split — how compliance is
judged), `OvertimePolicy` (eligibility/caps/approval/rate rows), `RegularizationPolicy` (who may
correct, windows, caps, allowed types, approval chain). Each follows the exact
identity + immutable-published-version shape `ShiftVersion` established in W2
(`organisation/models.py`): a mutable *identity* row (name/code/active) plus a versioned body
(`status` DRAFT|PUBLISHED, `effective_from`/`effective_to`, insert-new/close-previous, GiST
no-overlap on published rows, one open draft per identity).

`PolicyAssignment` (the scope/precedence table these are assigned through) deliberately stays in
`organisation/models.py` — it was pulled forward into W1 there (WD-24) and this module widens its
`policy_kind` CHECK rather than duplicating the table (architecture §18 "do not create another
assignment table if the architecture already provides a reusable mechanism").

Typed columns only (WD-12/WD-20) — no JSONB rules engine. Multi-valued rule shapes (hour bands,
late/early bands, OT rate rows, regularization allowed types) are child tables, not arrays or
JSON, mirroring `ShiftBreak`/`WeeklyOffRule`.
"""

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from hrms.core.db.base import Base, TimestampMixin

# ---------------------------------------------------------------------------
# Attendance Policy — identity + version + typed rule children
# ---------------------------------------------------------------------------


class AttendancePolicy(Base, TimestampMixin):
    """Identity row — name/code/active only, never carries evaluation fields directly (mirrors
    `Shift` post-W2). The actual rule configuration lives on `AttendancePolicyVersion`."""

    __tablename__ = "attendance_policy"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(150))
    code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class AttendancePolicyVersion(Base, TimestampMixin):
    """Immutable once PUBLISHED (architecture §11.1). Typed evaluation fields for grace,
    rounding, missing-punch/shift handling, half-day split, multi-punch pairing, flex/split
    evaluation, WFH/on-duty punch rules, leave-overlay, break-excess handling, and late/early
    counters. Hour bands / late bands / early-departure bands are separate child tables (this
    row would otherwise need repeating groups)."""

    __tablename__ = "attendance_policy_version"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    policy_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("attendance_policy.id"), index=True
    )
    status: Mapped[str] = mapped_column(String(20))
    version: Mapped[int] = mapped_column(Integer, default=1)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Grace (§11.6, §6)
    grace_in_minutes: Mapped[int] = mapped_column(Integer, default=0)
    grace_out_minutes: Mapped[int] = mapped_column(Integer, default=0)

    # Rounding (§11.6)
    punch_rounding: Mapped[str] = mapped_column(String(10), default="NONE")
    rounding_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Missing punch / missing shift (§11.5, §9.6)
    missing_punch_behaviour: Mapped[str] = mapped_column(String(30), default="INCOMPLETE")
    auto_close_after_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    auto_close_uses_shift_end: Mapped[bool] = mapped_column(Boolean, default=True)
    missing_shift_behaviour: Mapped[str] = mapped_column(String(20), default="INCOMPLETE")

    # Half-day split (§9)
    half_day_split: Mapped[str] = mapped_column(String(20), default="BY_HOURS")
    half_day_boundary_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Multiple intervals / duplicate collapse (§11.2)
    multi_punch_mode: Mapped[str] = mapped_column(String(20), default="PAIR_ALL")
    duplicate_punch_window_seconds: Mapped[int] = mapped_column(Integer, default=60)

    # Flexible shift evaluation (§11.8)
    core_hours_breach_behaviour: Mapped[str] = mapped_column(String(20), default="FLAG")
    early_out_uses_core_end: Mapped[bool] = mapped_column(Boolean, default=False)

    # Split shift evaluation (§14)
    split_shift_block_mandatory: Mapped[bool] = mapped_column(Boolean, default=True)
    split_shift_missed_block_behaviour: Mapped[str] = mapped_column(String(30), default="HALF_DAY")
    split_shift_allow_hours_compensation: Mapped[bool] = mapped_column(Boolean, default=False)

    # WFH / On duty (§11.7, WD-17)
    wfh_requires_punch: Mapped[bool] = mapped_column(Boolean, default=True)
    on_duty_requires_punch: Mapped[bool] = mapped_column(Boolean, default=False)
    wfh_uses_shift_hours: Mapped[bool] = mapped_column(Boolean, default=True)

    # Leave overlay (§19.3)
    work_on_leave_behaviour: Mapped[str] = mapped_column(String(30), default="KEEP_LEAVE")

    # Break violations (§12, WD-15)
    excess_break_behaviour: Mapped[str] = mapped_column(String(20), default="FLAG")

    # Late / early counters (§11.2)
    late_count_window: Mapped[str] = mapped_column(String(10), default="MONTH")
    lates_to_half_day_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    early_departure_requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)

    # Lock-time default for still-INCOMPLETE days (§11.4)
    incomplete_at_lock_behaviour: Mapped[str] = mapped_column(String(20), default="TREAT_ABSENT")

    publish_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AttendancePolicyHourBand(Base, TimestampMixin):
    """Worked-minutes -> PRESENT/HALF_DAY/ABSENT (§9, §11.1). No independent lifecycle —
    full-replace on every draft PATCH, frozen once the parent version publishes (mirrors
    `ShiftBreak`). Non-overlap/ordering is validated in the service layer at publish time, not a
    DB GiST constraint, so a draft's full-replace transaction is never mid-transaction-invalid."""

    __tablename__ = "attendance_policy_hour_band"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    policy_version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("attendance_policy_version.id"), index=True
    )
    min_minutes: Mapped[int] = mapped_column(Integer)
    max_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_status: Mapped[str] = mapped_column(String(20))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class AttendancePolicyLateBand(Base, TimestampMixin):
    """Late-minutes-after-grace -> classification (§6, §11.2)."""

    __tablename__ = "attendance_policy_late_band"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    policy_version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("attendance_policy_version.id"), index=True
    )
    min_minutes: Mapped[int] = mapped_column(Integer)
    max_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    classification: Mapped[str] = mapped_column(String(20))
    counts_toward_cap: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class AttendancePolicyEarlyDepartureBand(Base, TimestampMixin):
    """Early-minutes-after-grace -> classification (§7, §11.2) — the mirror of
    `AttendancePolicyLateBand` for the end of the shift."""

    __tablename__ = "attendance_policy_early_departure_band"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    policy_version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("attendance_policy_version.id"), index=True
    )
    min_minutes: Mapped[int] = mapped_column(Integer)
    max_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    classification: Mapped[str] = mapped_column(String(20))
    counts_toward_cap: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


# ---------------------------------------------------------------------------
# Overtime Policy — identity + version + typed rate rows (WD-03)
# ---------------------------------------------------------------------------


class OvertimePolicy(Base, TimestampMixin):
    __tablename__ = "overtime_policy"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(150))
    code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class OvertimePolicyVersion(Base, TimestampMixin):
    """Detection/eligibility/caps/approval contract only — no monetary calculation (ADR-0006,
    WD-03 §12.1). `configured_multiplier` rows live on `OvertimePolicyRateRow`, informational for
    payroll, never applied as money here."""

    __tablename__ = "overtime_policy_version"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    policy_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("overtime_policy.id"), index=True
    )
    status: Mapped[str] = mapped_column(String(20))
    version: Mapped[int] = mapped_column(Integer, default=1)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)

    eligibility: Mapped[str] = mapped_column(String(30), default="SHIFT_FLAG")
    min_ot_minutes: Mapped[int] = mapped_column(Integer, default=0)
    rounding_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rounding_mode: Mapped[str] = mapped_column(String(10), default="NONE")
    requires_pre_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_post_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    daily_cap_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weekly_cap_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    monthly_cap_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comp_off_instead_of_pay: Mapped[bool] = mapped_column(Boolean, default=False)
    comp_off_expiry_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    night_ot_mode: Mapped[str] = mapped_column(String(20), default="SHIFT_FLAG")
    night_window_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    night_window_end: Mapped[time | None] = mapped_column(Time, nullable=True)
    approval_chain: Mapped[str] = mapped_column(String(20), default="MANAGER")

    publish_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OvertimePolicyRateRow(Base, TimestampMixin):
    """Day-class -> classification code (+ optional informational multiplier) (§12.1). The
    multiplier is configuration, never a hardcoded statutory rate (WD-12)."""

    __tablename__ = "overtime_policy_rate_row"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    policy_version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("overtime_policy_version.id"), index=True
    )
    day_class: Mapped[str] = mapped_column(String(20))
    classification_code: Mapped[str] = mapped_column(String(50))
    multiplier_decimal: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


# ---------------------------------------------------------------------------
# Regularization Policy — identity + version + allowed types (WD-03)
# ---------------------------------------------------------------------------


class RegularizationPolicy(Base, TimestampMixin):
    __tablename__ = "regularization_policy"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(150))
    code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class RegularizationPolicyVersion(Base, TimestampMixin):
    """Who may request, windows, caps, approval chain (§13.1) — W3 does not build the workflow
    itself (WD-08); this only defines the contract the future workflow reads."""

    __tablename__ = "regularization_policy_version"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    policy_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("regularization_policy.id"), index=True
    )
    status: Mapped[str] = mapped_column(String(20))
    version: Mapped[int] = mapped_column(Integer, default=1)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)

    allow_employee_request: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_manager_request: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_hr_request: Mapped[bool] = mapped_column(Boolean, default=True)
    max_backdated_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_requests_per_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason_required: Mapped[bool] = mapped_column(Boolean, default=True)
    attachment_required: Mapped[bool] = mapped_column(Boolean, default=False)
    approval_chain: Mapped[str] = mapped_column(String(20), default="MANAGER")
    auto_approve_within_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    blocked_when_locked: Mapped[bool] = mapped_column(Boolean, default=True)

    publish_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RegularizationPolicyAllowedType(Base, TimestampMixin):
    """Typed enumeration of which exception types this policy allows regularizing (§13.1) — a
    child table, not an array column, mirroring the rest of this module's "typed over generic"
    posture."""

    __tablename__ = "regularization_policy_allowed_type"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    policy_version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("regularization_policy_version.id"), index=True
    )
    regularization_type: Mapped[str] = mapped_column(String(30))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


# ---------------------------------------------------------------------------
# Punch — immutable, append-only raw event (W4, WD-11)
# ---------------------------------------------------------------------------


class Punch(Base):
    """A single raw IN/OUT event. Never UPDATE'd or DELETE'd (WD-11 — "punches immutable once
    written"; architecture §2.3 constraint 11). Corrections are new punches with
    `source='REGULARIZATION'`/`'ADMIN'`, never a mutation of this row (W6). No `TimestampMixin`
    (no `updated_at` — mirrors `AuditLog`, the only other insert-only table in this codebase, not
    `TimestampMixin`'s mutable-row shape).

    Partitioning (architecture §27, "PARTITION BY RANGE on local month... required before
    volume") is deliberately **not** implemented in this migration — see decision log **WD-26**.
    This is an ordinary RLS'd tenant table like every other table in this codebase; zero punch
    rows exist anywhere yet, and §28 states V1 tenants will not notice. Partitioning remains a
    valid additive migration once real volume exists.

    Idempotency: a partial unique index on `(company_id, idempotency_key)` guards exact
    resubmission when a caller supplies a key (defensive, chiefly for future device sources,
    W10). The load-bearing dedup mechanism for W4 (web/manual/API sources) is calculation-time
    duplicate collapsing within `AttendancePolicyVersion.duplicate_punch_window_seconds`
    (architecture §19.1 step 9), not insert-time idempotency."""

    __tablename__ = "punch"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    employee_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employee.id"), index=True
    )
    punch_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    direction: Mapped[str] = mapped_column(String(10))
    source: Mapped[str] = mapped_column(String(20))
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    recorded_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# AttendanceDay — derived, recomputable calculation result (W4, WD-10/WD-11)
# ---------------------------------------------------------------------------


class AttendanceDay(Base, TimestampMixin):
    """One row per employee per *attendance date* (the shift's start date for overnight shifts,
    FR-ATT-005). Fully recomputed on every calculation run — never incrementally patched
    (WD-10). `UNIQUE (company_id, employee_id, attendance_date)`.

    Reproducibility (WD-11, the core requirement of this table): every version FK actually used
    is stored, plus `computation_snapshot` — a JSONB trace of punch inputs and intermediate
    figures. Historical attendance must not change merely because Shift/Policy/Calendar are
    edited later; recompute always re-resolves versions *by date*, so only a backdated version
    publish (a privileged act) can change an unlocked historical day.

    Locking (decision 2, plan): `is_locked`/`locked_at`/`locked_by` exist so recompute can refuse
    a locked day, but nothing in W4 can set `is_locked=true` — the `AttendanceLock` period-lock
    entity and its `/attendance-locks` API are W8 (architecture §30). This mirrors how
    `RegularizationPolicyVersion.blocked_when_locked` shipped in W3 long before any lock
    mechanism existed."""

    __tablename__ = "attendance_day"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    employee_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employee.id"), index=True
    )
    attendance_date: Mapped[date] = mapped_column(Date)
    timezone: Mapped[str] = mapped_column(String(64))

    shift_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("shift.id"), nullable=True
    )
    shift_version_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("shift_version.id"), nullable=True
    )
    work_calendar_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("work_calendar.id"), nullable=True
    )
    attendance_policy_version_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("attendance_policy_version.id"), nullable=True
    )
    overtime_policy_version_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("overtime_policy_version.id"), nullable=True
    )
    regularization_policy_version_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("regularization_policy_version.id"), nullable=True
    )

    calendar_day_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    holiday_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    holiday_on_weekly_off: Mapped[bool] = mapped_column(Boolean, default=False)

    scheduled_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    actual_first_in: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    actual_last_out: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worked_minutes: Mapped[int] = mapped_column(Integer, default=0)
    unpaid_break_minutes: Mapped[int] = mapped_column(Integer, default=0)
    paid_break_minutes: Mapped[int] = mapped_column(Integer, default=0)
    excess_break_minutes: Mapped[int] = mapped_column(Integer, default=0)

    attendance_status: Mapped[str] = mapped_column(String(20))
    late_minutes: Mapped[int] = mapped_column(Integer, default=0)
    early_departure_minutes: Mapped[int] = mapped_column(Integer, default=0)
    late_classification: Mapped[str | None] = mapped_column(String(20), nullable=True)
    early_departure_classification: Mapped[str | None] = mapped_column(String(20), nullable=True)
    missing_punch: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_closed: Mapped[bool] = mapped_column(Boolean, default=False)

    is_late: Mapped[bool] = mapped_column(Boolean, default=False)
    is_early_out: Mapped[bool] = mapped_column(Boolean, default=False)
    is_overtime: Mapped[bool] = mapped_column(Boolean, default=False)
    is_regularized: Mapped[bool] = mapped_column(Boolean, default=False)
    is_pending_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    worked_on_holiday: Mapped[bool] = mapped_column(Boolean, default=False)
    worked_on_weekly_off: Mapped[bool] = mapped_column(Boolean, default=False)

    paid_day_fraction: Mapped[Decimal] = mapped_column(Numeric(3, 2), default=Decimal("0"))
    lop_fraction: Mapped[Decimal] = mapped_column(Numeric(3, 2), default=Decimal("0"))

    ot_minutes_detected: Mapped[int] = mapped_column(Integer, default=0)
    ot_minutes_approved: Mapped[int] = mapped_column(Integer, default=0)
    ot_pending: Mapped[bool] = mapped_column(Boolean, default=False)
    ot_classification: Mapped[str | None] = mapped_column(String(20), nullable=True)
    comp_off_minutes_earned: Mapped[int] = mapped_column(Integer, default=0)

    calculation_version: Mapped[int] = mapped_column(Integer, default=1)
    computation_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )


class AttendanceBreak(Base, TimestampMixin):
    """An actual break interval used in the calculation (auto-deducted and/or detected from
    punch gaps), child of `AttendanceDay` — no independent lifecycle, full-replace on every
    recompute (mirrors `ShiftBreak`'s no-independent-lifecycle posture, architecture §10.2)."""

    __tablename__ = "attendance_break"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    attendance_day_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("attendance_day.id"), index=True
    )
    shift_break_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("shift_break.id"), nullable=True
    )
    break_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    break_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    minutes: Mapped[int] = mapped_column(Integer, default=0)
    is_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    is_excess: Mapped[bool] = mapped_column(Boolean, default=False)
