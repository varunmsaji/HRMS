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
    SmallInteger,
    String,
    Text,
    Time,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
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

    # Cumulative excess-break-day counter (WD-32 decision 2) — same shape as the late counter
    # above; no prior field existed for this (unlike core-hours/late-count/early-approval, which
    # all had dormant fields from earlier slices).
    excess_break_count_window: Mapped[str] = mapped_column(String(10), default="MONTH")
    excess_break_days_to_half_day_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

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
    # LEAVE_DECISION_LOG.md LD-14 — the minutes-per-day basis Leave's comp-off credit engine uses
    # to convert `OvertimeRecord.comp_off_minutes` into `leave_ledger.amount` (days). `None` means
    # not configured yet; the credit engine skips crediting for such a policy version rather than
    # guessing a day length.
    comp_off_day_length_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
# ShiftRoster — per-employee-per-date schedule override (W5 — architecture §4.2/§9.7/§17,
# decision log WD-27)
# ---------------------------------------------------------------------------


class ShiftRoster(Base, TimestampMixin):
    """Per-employee-per-date schedule override. The calculation engine's shift resolution
    (`AttendanceDayService._build_calculation_input`) checks for a `PUBLISHED` row here first,
    falling back to `EmployeeAssignment.shift_id` only when none exists (§9.7). `shift_id` is
    nullable — a pure "day off" or "no schedule" roster fact needs none.
    `is_week_off_override`/`is_holiday_working_override` are schedule facts only; they never
    change `calendar_day_type` (WD-04/WD-07 — calendar type stays Calendar's concern), only the
    calculation engine's expectation-of-presence branch. Mutually exclusive (DB CHECK).

    Mutable master, not an insert-new history — mirrors `Shift`, not `ShiftVersion`: a single
    row per `(company_id, employee_id, roster_date)` (§17 — "the roster_date is the effective
    date"). `status` DRAFT|PUBLISHED (WD-27, not literally named in architecture's field list
    but not prohibited either): only `PUBLISHED` rows are visible to the calculation engine, so
    HR can stage a roster before it affects live attendance. Every mutation is audited via
    `AuditService.record` (architecture §24 names "Roster write" as an audited action) rather
    than a separate revision table."""

    __tablename__ = "shift_roster"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    employee_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employee.id"), index=True
    )
    roster_date: Mapped[date] = mapped_column(Date)
    shift_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("shift.id"), nullable=True
    )
    is_week_off_override: Mapped[bool] = mapped_column(Boolean, default=False)
    is_holiday_working_override: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(10), default="DRAFT")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )


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
# Face attendance — enrollment profile + verification attempt log
# ---------------------------------------------------------------------------


class FaceEnrollmentWindow(Base, TimestampMixin):
    """A one-time, HR-opened window in which one employee may self-enroll their face. OPEN past
    `expires_at` counts as expired; USED once a submission succeeds, never reusable."""

    __tablename__ = "face_enrollment_window"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    employee_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employee.id"))
    status: Mapped[str] = mapped_column(String(20))
    opened_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    #: Lease taken (and committed) before a submission's slow provider calls start; see
    #: migration 20261018090000. Both null when no submission is in flight.
    submission_token: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    submission_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class EmployeeFaceProfile(Base, TimestampMixin):
    """An employee's enrollment with the face-verification provider. Stores the provider's person
    id; the only image ever kept is the straight-on capture awaiting HR review
    (`review_photo_key`), deleted once reviewed. `consent_recorded_at` is mandatory."""

    __tablename__ = "employee_face_profile"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    employee_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employee.id"))
    provider: Mapped[str] = mapped_column(String(20))
    provider_person_id: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20))
    reference_photo_count: Mapped[int] = mapped_column(Integer, default=1)
    consent_recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    enrolled_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    enrollment_window_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("face_enrollment_window.id", ondelete="SET NULL"),
        nullable=True,
    )
    review_photo_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    review_note: Mapped[str | None] = mapped_column(String(500), nullable=True)


class FaceVerificationAttempt(Base):
    """Insert-only log of every face check, rejected ones included. `punch_id` is set only when a
    MATCHED attempt produced a punch. No image is ever persisted."""

    __tablename__ = "face_verification_attempt"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    employee_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employee.id"))
    punch_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("punch.id"), nullable=True, unique=True
    )
    provider: Mapped[str] = mapped_column(String(20))
    provider_person_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    decision: Mapped[str] = mapped_column(String(30))
    similarity: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    liveness_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    provider_response: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    liveness_session_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("face_liveness_session.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FaceEmbedding(Base):
    """One enrollment capture of an OPENSOURCE-engine person. `embedding_enc` is the face
    embedding encrypted with the environment data key (never plaintext, never returned by any API);
    `person_ref` is the random id inside `employee_face_profile.provider_person_id`. See
    `attendance/opensource_face/` and migration 20261022090000."""

    __tablename__ = "face_embedding"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    employee_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employee.id"))
    person_ref: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    sample_index: Mapped[int] = mapped_column(SmallInteger)
    model_version: Mapped[str] = mapped_column(String(40))
    embedding_enc: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FaceEnrollmentAttempt(Base):
    """One rejected self-enrollment submission. Insert-only and minimal on purpose: the decision,
    the capture angle that failed and who/when — never an image, score or provider body.
    `enrollment_window_id` is a plain column (no foreign key): see migration 20261017090000."""

    __tablename__ = "face_enrollment_attempt"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    employee_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employee.id"))
    enrollment_window_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    decision: Mapped[str] = mapped_column(String(30))
    angle: Mapped[str | None] = mapped_column(String(10), nullable=True)
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FaceExternalDeletion(Base, TimestampMixin):
    """Outbox row: an external biometric resource (a Face++ FaceSet or a stored review photo)
    that must be deleted, written in the same transaction that authorises the deletion and acted
    on only after it commits. Holds the opaque provider id / object key only (migration
    20261018090000)."""

    __tablename__ = "face_external_deletion"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20))
    provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    resource_ref: Mapped[str] = mapped_column(String(300))
    reason: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(10), default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FaceLivenessSession(Base, TimestampMixin):
    """A server-issued, single-use liveness challenge for one employee's next face punch in
    one direction. ISSUED until presented (CONSUMED, whatever the outcome) or replaced by a newer
    one (SUPERSEDED); past `expires_at` it is unusable. `frame_digests` holds SHA-256 hashes of
    the frames presented with it — never the frames themselves."""

    __tablename__ = "face_liveness_session"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    employee_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employee.id"))
    direction: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(20))
    issued_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    frame_digests: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)


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

    # W9 — leave overlay (§19.3). Set only when `AttendancePolicyVersion.work_on_leave_behaviour
    # = PRESENT_CANCEL_LEAVE_HINT` and punches exist despite an approved leave projection
    # covering the day: Attendance keeps the punch-derived outcome and raises this flag for Leave
    # to see and decide whether to cancel the leave application — Attendance never writes the
    # leave ledger itself (architecture §21).
    work_on_leave_flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    # BUS-012 — HR's decision on a flagged day. `KEEP_LEAVE` = the leave stands, punches ignored.
    # (The other resolution — cancelling the leave — needs no column: the leave projection is
    # cancelled, the day recomputes from its punches and the flag clears.) Not a derived field:
    # `calculate()` preserves it while the day stays flagged and clears it once it isn't.
    work_on_leave_resolution: Mapped[str | None] = mapped_column(String(20), nullable=True)
    work_on_leave_resolution_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    work_on_leave_resolved_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id"), nullable=True
    )
    work_on_leave_resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # WD-32 decision 6 — real ON_DUTY status. Set inside `calculate()` from an approved
    # `ON_DUTY`-type `AttendanceRegularizationRequest` covering this date — a derived fact
    # re-resolved on every recompute (mirrors `work_on_leave_flagged` above), not something the
    # regularization approval step writes directly. `on_duty_regularization_id` is provenance
    # only (which request produced this), same spirit as the version-FK snapshot fields above.
    on_duty: Mapped[bool] = mapped_column(Boolean, default=False)
    on_duty_regularization_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("attendance_regularization_request.id", ondelete="SET NULL"),
        nullable=True,
    )

    # WD-32 decision 1 — core-hours breach (FLEX shifts only). Mirrors `work_on_leave_flagged`'s
    # shape: a derived, re-resolved-on-every-recompute fact, set whenever
    # `AttendancePolicyVersion.core_hours_breach_behaviour` is not `IGNORE` and the punches don't
    # fully cover `ShiftVersion.core_start`-`core_end`. Independent of whether the breach also
    # forced a status override (`HALF_DAY`/`ABSENT`) — `FLAG` sets this with no status change.
    is_core_hours_breach: Mapped[bool] = mapped_column(Boolean, default=False)

    paid_day_fraction: Mapped[Decimal] = mapped_column(Numeric(3, 2), default=Decimal("0"))
    lop_fraction: Mapped[Decimal] = mapped_column(Numeric(3, 2), default=Decimal("0"))
    # PAY-003 — share of the day honoured as approved leave (`calculation.leave_fraction`).
    leave_fraction: Mapped[Decimal] = mapped_column(Numeric(3, 2), default=Decimal("0"))
    # PAY-012 — paid off share of a half-day weekly off (`calculation.weekly_off_fraction`).
    weekly_off_fraction: Mapped[Decimal] = mapped_column(Numeric(3, 2), default=Decimal("0"))
    # BUS-001 — share of the day that is an unpaid off day (`calculation.unpaid_off_fraction`).
    unpaid_off_fraction: Mapped[Decimal] = mapped_column(Numeric(3, 2), default=Decimal("0"))

    ot_minutes_detected: Mapped[int] = mapped_column(Integer, default=0)
    ot_minutes_approved: Mapped[int] = mapped_column(Integer, default=0)
    ot_pending: Mapped[bool] = mapped_column(Boolean, default=False)
    ot_classification: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # The engine's OT day class (NORMAL|WEEKLY_OFF|HOLIDAY|NIGHT) — `ot_classification` is the
    # policy's configurable rate code, so the period summary buckets OT by this column instead.
    ot_day_class: Mapped[str | None] = mapped_column(String(20), nullable=True)
    comp_off_minutes_earned: Mapped[int] = mapped_column(Integer, default=0)

    calculation_version: Mapped[int] = mapped_column(Integer, default=1)
    # PAY-008 — `calculation.ENGINE_VERSION` that produced this row; NULL = computed before it.
    engine_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    computation_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    # Decision 14 — the period whose finalize locked this day. Reopen unlocks exactly these rows,
    # never a bare date range (another legal entity's closed period may cover the same dates).
    locked_period_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("attendance_period.id", ondelete="SET NULL"),
        nullable=True,
    )


# ---------------------------------------------------------------------------
# AttendanceRegularizationRequest — employee/manager/HR correction request (W6 — architecture
# §13, decision log WD-28)
# ---------------------------------------------------------------------------


class AttendanceRegularizationRequest(Base, TimestampMixin):
    """A request to correct one employee's attendance for one date. Applied only through the
    two mechanisms that already exist — synthetic `Punch` rows (`source='REGULARIZATION'`) and,
    for `WRONG_SHIFT`, a `PUBLISHED` `ShiftRoster` row — followed by the existing
    `AttendanceDayService.calculate()` (WD-28 decision 1). Never mutates a punch or writes a new
    calculation-engine status branch.

    `attendance_day_id` is nullable: a day may never have been calculated yet (zero punches ever
    recorded, no batch job has touched it), so `attendance_date` is the canonical reference and
    `attendance_day_id` is resolved/backfilled once `calculate()` has run at least once (at
    submit time if a row already exists, always by apply time).

    `approval_chain`/`regularization_policy_version_id` are snapshotted at submit time (mirrors
    `AttendanceDay`'s own version-FK-plus-snapshot reproducibility posture, WD-11) so a later
    policy edit cannot retroactively change how an in-flight request is reviewed.
    `approval_stage` tracks whose turn it is next (`MANAGER`|`HR`|`NULL` once terminal or
    `AUTO`) — WD-28 decision 4."""

    __tablename__ = "attendance_regularization_request"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    employee_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employee.id"), index=True
    )
    attendance_day_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("attendance_day.id"), nullable=True
    )
    attendance_date: Mapped[date] = mapped_column(Date)

    request_type: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_shift_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("shift.id"), nullable=True
    )
    attachment_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="SUBMITTED")
    approval_chain: Mapped[str] = mapped_column(String(20))
    approval_stage: Mapped[str | None] = mapped_column(String(10), nullable=True)
    regularization_policy_version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("regularization_policy_version.id")
    )
    resolved_approver_manager_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employee.id"), nullable=True
    )

    submitted_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    reviewed_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewer_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )

    version: Mapped[int] = mapped_column(Integer, default=1)


class AttendanceRegularizationRequestedPunch(Base, TimestampMixin):
    """Typed correction payload — one row per requested IN/OUT instant (WD-12/WD-20: typed
    child table, not a JSON list). Applying an approved request turns each row into a new
    immutable `Punch` (`source='REGULARIZATION'`); this row is the auditable record of what was
    *requested*, which never changes even if the resulting punch is later collapsed/paired
    differently by a recompute."""

    __tablename__ = "attendance_regularization_requested_punch"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    request_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("attendance_regularization_request.id"), index=True
    )
    direction: Mapped[str] = mapped_column(String(10))
    requested_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class AttendanceRegularizationAction(Base, TimestampMixin):
    """Append-only per-request timeline (architecture §13.2/§33.4 names `RegularizationAction`
    explicitly) — the per-stage history `RegularizationRequest`'s single
    `reviewed_by_user_id`/`reviewed_at` pair cannot hold for a `MANAGER_THEN_HR` chain, and the
    read model the frontend timeline queries directly without needing `audit_log` read access
    (WD-28 decision 7). `AuditService.record` is called in addition, once per transition — the
    two are not redundant, see WD-28 decision 7."""

    __tablename__ = "attendance_regularization_action"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    request_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("attendance_regularization_request.id"), index=True
    )
    action: Mapped[str] = mapped_column(String(30))
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    actor_employee_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employee.id"), nullable=True
    )
    stage: Mapped[str | None] = mapped_column(String(10), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class OvertimeRecord(Base, TimestampMixin):
    """The approval workflow entity for one `AttendanceDay`'s detected overtime (W7 — architecture
    §12, decision log WD-29). `attendance_day_id` is `UNIQUE`: unlike
    `AttendanceRegularizationRequest`, this is a single mutable-then-frozen row per day, not an
    accumulating history — nothing is ever re-detected concurrently for the same day.

    A `PENDING` row is fully replaced on every recompute of its day (mirrors `AttendanceBreak`'s
    delete/recreate posture — nothing has been decided yet). Once `status` reaches a terminal
    value (`AUTO_APPROVED`/`APPROVED`/`REJECTED`), `AttendanceDayService.calculate()` never
    overwrites this row again (WD-29 decision 2) — a later recompute (e.g. driven by an approved
    regularization) still refreshes `AttendanceDay.ot_minutes_detected`/`ot_classification`
    informationally, but this row's own decision fields are frozen.

    `configured_multiplier` is the snapshot payroll fact architecture §12.1/§22.1 calls for —
    captured here rather than added as a new `AttendanceDay` column."""

    __tablename__ = "overtime_record"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    employee_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employee.id"), index=True
    )
    attendance_day_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("attendance_day.id"), unique=True
    )
    attendance_date: Mapped[date] = mapped_column(Date)
    overtime_policy_version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("overtime_policy_version.id")
    )

    day_class: Mapped[str | None] = mapped_column(String(20), nullable=True)
    classification_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    configured_multiplier: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)

    minutes_detected: Mapped[int] = mapped_column(Integer, default=0)
    minutes_approved: Mapped[int] = mapped_column(Integer, default=0)

    status: Mapped[str] = mapped_column(String(20))
    approval_chain: Mapped[str] = mapped_column(String(20))
    approval_stage: Mapped[str | None] = mapped_column(String(10), nullable=True)
    resolved_approver_manager_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employee.id"), nullable=True
    )

    reviewed_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewer_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    comp_off_minutes: Mapped[int] = mapped_column(Integer, default=0)
    comp_off_expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    version: Mapped[int] = mapped_column(Integer, default=1)


class OvertimeAction(Base, TimestampMixin):
    """Append-only per-record timeline, mirroring `AttendanceRegularizationAction` (WD-28
    decision 7 precedent) — the per-stage history a single `reviewed_by_user_id`/`reviewed_at`
    pair on `OvertimeRecord` cannot hold for a `MANAGER_THEN_HR` chain."""

    __tablename__ = "overtime_action"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    overtime_record_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("overtime_record.id"), index=True
    )
    action: Mapped[str] = mapped_column(String(30))
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    actor_employee_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employee.id"), nullable=True
    )
    stage: Mapped[str | None] = mapped_column(String(10), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
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


# ---------------------------------------------------------------------------
# W8 — AttendancePeriod / AttendancePeriodAction / AttendancePeriodSummary
# (architecture §4.2 `AttendanceLock`/`AttendancePeriodSummary`, §22, decision log WD-30)
# ---------------------------------------------------------------------------


class AttendancePeriod(Base, TimestampMixin):
    """The period lifecycle + lock entity architecture §4.2 names `AttendanceLock`. Two
    persisted states only (`OPEN`/`CLOSED`) — WD-30: a period is mutable-and-computable the
    instant it is created (no separate "open" action, mirroring WD-28's no-DRAFT-state
    precedent for `AttendanceRegularizationRequest`), and finalization is synchronous within one
    transaction (no Celery fan-out, matching every other W1-W7 mutation in this module), so a
    durable `CLOSING` state has no code path that would ever observe it. `CLOSED` *is* locked —
    architecture's own `AttendanceLock` never describes a closed-but-unlocked state either.

    `[period_start, period_end]` inclusive-inclusive (§17 convention). No overlap with another
    period for the same `(company_id, legal_entity_id)` (GiST exclusion, mirrors
    `PolicyAssignment`/`Employment`).

    Legal-entity grain (`docs/audits/PAYROLL_BUSINESS_DECISIONS.md` decision 14, resolving
    PD-LOCK-1): payroll — and so the attendance cycle it reads — runs per legal entity, because
    PF/ESI/TDS are filed per entity. A period covers the employee-dates whose employment on that
    date belongs to `legal_entity_id` (see `_period_owns_date` in `service.py`); another entity's
    employees are unaffected by it being open or closed."""

    __tablename__ = "attendance_period"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    legal_entity_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("legal_entity.id"), index=True
    )

    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="OPEN")

    opened_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    last_validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_validation_status: Mapped[str | None] = mapped_column(String(20), nullable=True)

    closed_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    reopened_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reopen_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    version: Mapped[int] = mapped_column(Integer, default=1)


class AttendancePeriodAction(Base, TimestampMixin):
    """Append-only per-period timeline, mirroring `AttendanceRegularizationAction`/
    `OvertimeAction` (WD-28 decision 7 precedent)."""

    __tablename__ = "attendance_period_action"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    attendance_period_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("attendance_period.id"), index=True
    )
    action: Mapped[str] = mapped_column(String(30))
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AttendancePeriodSummary(Base, TimestampMixin):
    """The payroll-facing per-employee roll-up architecture §4.2/§22.2 names
    `AttendancePeriodSummary`. "Regenerated only while unlocked; frozen at lock/snapshot" (§4.2)
    is implemented as: while the period is `OPEN`, `GET .../summary` computes a live aggregate
    from `AttendanceDay` on every call and never persists it here; a row is written to this table
    exactly once, inside the same transaction that sets `AttendancePeriod.status='CLOSED'`, and is
    never regenerated after that — the frozen snapshot Payroll will eventually read (ADR-0005).
    Never carries rupees (architecture §22.2 — penalty/bonus *amounts* are Payroll's)."""

    __tablename__ = "attendance_period_summary"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    attendance_period_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("attendance_period.id"), index=True
    )
    employee_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employee.id"), index=True
    )

    present_days: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("0"))
    absent_days: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("0"))
    leave_days: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("0"))
    holiday_days: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("0"))
    weekly_off_days: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("0"))
    half_days: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("0"))
    lop_days: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("0"))
    # PAY-002/PAY-003 — NULL on summaries frozen before these columns existed (their buckets used
    # the old overlapping semantics); Payroll must refuse a summary whose `paid_days` is NULL.
    # For every summary frozen since, the day buckets are mutually exclusive and satisfy:
    #   present + half + absent + leave + on_duty + holiday + weekly_off + incomplete
    #     + not_employed = calendar days in the period
    #   paid_days + lop_days + unpaid_off_days = payable_days  (= employed days in the period)
    on_duty_days: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    incomplete_days: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    not_employed_days: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    # BUS-001 — off days that are neither paid nor LOP (daily-wage weekly offs, unpaid holidays).
    unpaid_off_days: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    paid_days: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    payable_days: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)

    ot_minutes_normal: Mapped[int] = mapped_column(Integer, default=0)
    ot_minutes_weekly_off: Mapped[int] = mapped_column(Integer, default=0)
    ot_minutes_holiday: Mapped[int] = mapped_column(Integer, default=0)
    ot_minutes_night: Mapped[int] = mapped_column(Integer, default=0)
    comp_off_minutes_earned: Mapped[int] = mapped_column(Integer, default=0)

    late_count: Mapped[int] = mapped_column(Integer, default=0)
    worked_minutes_total: Mapped[int] = mapped_column(Integer, default=0)

    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------------------
# W9 — LeaveDayProjection (architecture §21, decision log WD-31)
# ---------------------------------------------------------------------------


class LeaveDayProjection(Base, TimestampMixin):
    """The attendance-owned mirror of architecture §21's `LeaveDayProjection` read model —
    "a read model published by Leave (service method, not table sharing)". No Leave module
    exists yet (architecture §30: "Leave projection adapter, mocked until Leave exists"), so
    this table is Attendance's own temporary backing store standing in for that service call —
    it is **not** the leave ledger (ADR-0004 untouched; entitlement/balance/accrual/approval
    remain entirely Leave's, whenever it ships) and is replaceable wholesale once a real Leave
    module exists: nothing else in this module depends on its storage shape, only on the typed
    `LeaveOverlayEntry` values `AttendanceDayService` resolves from active rows here.

    Only `status='APPROVED'` rows are ever visible to calculation (architecture §21: "only
    approved rows are visible"). Cancellation is `status='CANCELLED'`, never a delete, so
    provenance/audit is preserved (mirrors WD-11's never-mutate-the-fact posture). Multiple rows
    may cover the same `(employee_id, attendance_date)` — e.g. one half-day leave application for
    the morning and a separate one for the afternoon — `leave_application_id` disambiguates them.
    Active (APPROVED) fractions for one employee-date must sum to at most 1.00; enforced at sync
    time in the service layer (fail-closed), not a DB constraint, mirroring
    `InvalidPolicyBandError`'s validate-in-service posture rather than a CHECK that can't express
    a cross-row sum.

    Natural key `(company_id, employee_id, attendance_date, leave_application_id)` is unique
    (partial index, mirrors `ShiftRosterDateConflictError`'s pattern) — a resync of the same
    `leave_application_id` updates the existing row in place (bumping `source_version`) rather
    than accumulating duplicates, so a corrected projection is idempotent to re-publish."""

    __tablename__ = "leave_day_projection"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    employee_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employee.id"), index=True
    )
    attendance_date: Mapped[date] = mapped_column(Date)

    # No FK — Leave does not exist yet, so this is an opaque external reference, not a joinable
    # relationship (architecture §21 names it `leave_application_id`, a plain identifier).
    leave_application_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    leave_type_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    leave_type_code: Mapped[str | None] = mapped_column(String(30), nullable=True)

    fraction: Mapped[Decimal] = mapped_column(Numeric(3, 2))
    half: Mapped[str | None] = mapped_column(String(10), nullable=True)
    is_paid: Mapped[bool] = mapped_column(Boolean)

    status: Mapped[str] = mapped_column(String(20), default="APPROVED")
    source_version: Mapped[int] = mapped_column(Integer, default=1)

    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
