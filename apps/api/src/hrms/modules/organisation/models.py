"""ORM models owned by the organisation module."""

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
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
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from hrms.core.db.base import Base, TimestampMixin


class CompanySetupProgress(Base, TimestampMixin):
    __tablename__ = "company_setup_progress"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), unique=True
    )
    steps_completed: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    current_step: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="IN_PROGRESS")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class Plan(Base, TimestampMixin):
    __tablename__ = "plan"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class PlanFeature(Base, TimestampMixin):
    __tablename__ = "plan_feature"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    plan_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("plan.id"), index=True)
    feature_code: Mapped[str] = mapped_column(String(60))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    limit_value: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Subscription(Base, TimestampMixin):
    __tablename__ = "subscription"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    plan_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("plan.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="TRIALING")
    current_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    seat_limit_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class LegalEntity(Base, TimestampMixin):
    """The registered employer that owns statutory identifiers (PF/ESI/TAN/PAN/GST) and
    contracts with employees — sits between Company (tenant) and Branch in the org
    hierarchy (docs/product/17_SRS_Phase1_Core_Modules.md §3.1). Branch/Employment already
    carry a `legal_entity_id` FK at the DB level; this module does not yet own either."""

    __tablename__ = "legal_entity"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    registered_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    pan: Mapped[str | None] = mapped_column(String(20), nullable=True)
    tan: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cin: Mapped[str | None] = mapped_column(String(30), nullable=True)
    gstin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    pf_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    esi_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    lwf_reg: Mapped[str | None] = mapped_column(String(30), nullable=True)
    signatory_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    signatory_designation: Mapped[str | None] = mapped_column(String(150), nullable=True)
    signature_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class Branch(Base, TimestampMixin):
    """A physical work location under a Legal Entity (docs/product/17_SRS_Phase1_Core_
    Modules.md §3.1). `holiday_calendar_id`/`week_off_pattern_id` are intentionally absent
    — deferred to Feature 4.1 and Task 3.1.3 respectively (see the Branch module audit)."""

    __tablename__ = "branch"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    legal_entity_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("legal_entity.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    address_line1: Mapped[str | None] = mapped_column(String(200), nullable=True)
    address_line2: Mapped[str | None] = mapped_column(String(200), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    pincode: Mapped[str | None] = mapped_column(String(10), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    geofence_radius_m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class Department(Base, TimestampMixin):
    """An organisational unit under a Branch, optionally nested under a parent Department
    (FR-ORG-005 — hierarchy must reject cycles, max 5 levels; enforced in the service layer).
    `head_employee_id` (LD-23, Leave decision log) is now a real ORM-level FK — the DB
    constraint has existed since migration 20260813140000, but the ORM column stayed a plain
    UUID until now because `Employee` didn't exist at the time (Sprint 3 Scope Decision D10);
    `Employee` exists today, so nothing prevents a real `ForeignKey` any longer. Exposed via
    `DepartmentCreate`/`Update`/`Read` and validated in `OrganisationService`
    (`_assert_department_head_reference`) as of LD-23 — used to resolve Leave's third
    (`HOD`) approval stage.
    `cost_centre_id` is intentionally absent — see the Department module audit."""

    __tablename__ = "department"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    branch_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("branch.id"), nullable=True, index=True
    )
    parent_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("department.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(150))
    code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    head_employee_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employee.id"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class Grade(Base, TimestampMixin):
    """A compensation grade/band, referenced by Designation (FR-ORG-006/FR-ORG-007;
    docs/modules/grade/00_GRADE_AUDIT.md §3). `code` is required and already uniquely
    constrained per company at the DB level (`grade_company_id_code_key`, predates this
    slice). `min_ctc`/`max_ctc`/`approval_limit` are BIGINT minor units (ADR-0006) with no
    per-row currency — Company owns a single configured currency. `leave_policy_id` is
    intentionally absent — see the Grade module audit §2.4."""

    __tablename__ = "grade"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(100))
    level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_ctc: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    max_ctc: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    notice_period_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    probation_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approval_limit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class Designation(Base, TimestampMixin):
    """A job title/role, optionally scoped to a Department (FR-ORG-006 — "department
    (optional)") and to a Grade (FR-ORG-006/007 — added this slice, see
    docs/modules/grade/00_GRADE_AUDIT.md §3). `next_designation_id` (career-path pointer)
    exists at the DB level only (Sprint 3 Scope Decision D10) — not exposed by any
    schema/service/UI this slice. `jd_document_id` is intentionally absent — see the
    Designation module audit."""

    __tablename__ = "designation"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    department_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("department.id"), nullable=True, index=True
    )
    grade_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("grade.id"), nullable=True, index=True
    )
    next_designation_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("designation.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(150))
    code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class Shift(Base, TimestampMixin):
    """A shift master definition (FR-ATT-001; docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md
    Decision D5, Task 4.2.1) — timings, breaks, grace, and OT-eligibility only. No
    assignment/roster/rotation-pattern data (D5 — that's an Attendance-module concern,
    Sprint 7). `week_off_pattern_id` is intentionally absent — `week_off_pattern` itself was
    never built (deferred by the Branch slice's own Task 3.1.3, never picked up since); see
    docs/modules/shift-rules/00_SHIFT_RULES_AUDIT.md §2.4."""

    __tablename__ = "shift"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    break_minutes_paid: Mapped[int] = mapped_column(Integer, default=0)
    break_minutes_unpaid: Mapped[int] = mapped_column(Integer, default=0)
    grace_in_minutes: Mapped[int] = mapped_column(Integer, default=0)
    grace_out_minutes: Mapped[int] = mapped_column(Integer, default=0)
    half_day_threshold_hours: Mapped[Decimal | None] = mapped_column(Numeric(4, 2), nullable=True)
    min_hours_full_day: Mapped[Decimal | None] = mapped_column(Numeric(4, 2), nullable=True)
    is_night_shift: Mapped[bool] = mapped_column(Boolean, default=False)
    is_cross_midnight: Mapped[bool] = mapped_column(Boolean, default=False)
    is_ot_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class ShiftVersion(Base, TimestampMixin):
    """Immutable, effective-dated schedule for a `Shift` identity row (W2 —
    docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md §9-§10). `status` is
    `DRAFT`|`PUBLISHED`; at most one open DRAFT per shift (`shift_version_one_open_draft_idx`),
    at most one PUBLISHED row covering any given date per shift (`shift_version_no_overlap`
    GiST exclusion). `effective_to` is the one permitted mutation on a published row — set only
    when a later version publishes and closes this one (mirrors `PolicyAssignment.close`).
    Type-specific timing columns are nullable at the ORM layer; the DB CHECK
    `shift_version_published_required_check` enforces which combination is required once
    `status='PUBLISHED'` — SPLIT's "≥2 duty blocks" rule can't be a CHECK (counts child rows),
    so it's service-layer only, enforced at publish time."""

    __tablename__ = "shift_version"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    shift_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("shift.id"), index=True
    )
    status: Mapped[str] = mapped_column(String(20))
    version: Mapped[int] = mapped_column(Integer, default=1)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    shift_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    end_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    window_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    window_end: Mapped[time | None] = mapped_column(Time, nullable=True)
    core_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    core_end: Mapped[time | None] = mapped_column(Time, nullable=True)
    required_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scheduled_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_scheduled_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_scheduled_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_night_shift: Mapped[bool] = mapped_column(Boolean, default=False)
    is_cross_midnight: Mapped[bool] = mapped_column(Boolean, default=False)
    is_ot_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    operates_on_holiday: Mapped[bool] = mapped_column(Boolean, default=False)
    operates_on_weekly_off: Mapped[bool] = mapped_column(Boolean, default=False)
    weekly_off_pattern_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("weekly_off_pattern.id"), nullable=True
    )
    publish_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ShiftBreak(Base, TimestampMixin):
    """A typed break within a `ShiftVersion` — no independent lifecycle: full-replace on every
    draft PATCH, frozen once the parent version is published (W2). `break_kind` drives which
    columns are meaningful (`FIXED_WINDOW`: `start_time`/`end_time`; `FLEXIBLE_DURATION`:
    `window_start`/`window_end`/`min_minutes`/`max_minutes`), enforced by the DB CHECK
    `shift_break_kind_fields_check`."""

    __tablename__ = "shift_break"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    shift_version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("shift_version.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    break_kind: Mapped[str] = mapped_column(String(20))
    start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    end_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    window_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    window_end: Mapped[time | None] = mapped_column(Time, nullable=True)
    min_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scheduled_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    is_mandatory: Mapped[bool] = mapped_column(Boolean, default=True)
    allows_split: Mapped[bool] = mapped_column(Boolean, default=False)
    crosses_midnight: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class ShiftDutyBlock(Base, TimestampMixin):
    """A single contiguous working block within a SPLIT `ShiftVersion` (W2) — no independent
    lifecycle, same posture as `ShiftBreak`. `sequence` is contiguous starting at 1, unique per
    version (`shift_duty_block_version_sequence_key`); count/sequence/overlap rules are
    service-layer, enforced at publish time (SPLIT requires ≥2 blocks)."""

    __tablename__ = "shift_duty_block"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    shift_version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("shift_version.id"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    crosses_midnight: Mapped[bool] = mapped_column(Boolean, default=False)


class CompanyFeatureFlag(Base, TimestampMixin):
    __tablename__ = "company_feature_flag"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    feature_code: Mapped[str] = mapped_column(String(60))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    overrides_plan: Mapped[bool] = mapped_column(Boolean, default=False)
    value: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)


class HolidayCalendar(Base, TimestampMixin):
    """Reusable named catalogue of holiday dates — e.g. "India National 2026", "Karnataka
    2026", "Company FY26" (WD-01, architecture §7.1). Expanded from the Prisma-era stub in
    place (DEC-021) — the table has existed since `001_init_schema.sql` with only
    id/company_id/name/timestamps; this slice adds `code`/`kind`/`state_code`/`valid_from`/
    `valid_to`/`is_active`/`version` (migration `20260818090000_holiday_calendar_expand`)."""

    __tablename__ = "holiday_calendar"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(150))
    code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), default="COMPANY")
    state_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class Holiday(Base, TimestampMixin):
    """A dated fact on a HolidayCalendar (architecture §7.2). Expanded in place (DEC-021,
    migration `20260818100000_holiday_expand`) from a stub that had no `company_id`,
    timestamps, or versioning at all. `is_optional` is kept as a deprecated shadow of
    `holiday_type == 'OPTIONAL'` for backward compatibility — `holiday_type` is canonical
    (§7.2: "keep both briefly")."""

    __tablename__ = "holiday"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    calendar_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("holiday_calendar.id"), index=True
    )
    date: Mapped[date] = mapped_column(Date)
    name: Mapped[str] = mapped_column(String(150))
    is_optional: Mapped[bool] = mapped_column(Boolean, default=False)
    holiday_type: Mapped[str] = mapped_column(String(20), default="PUBLIC")
    is_paid: Mapped[bool] = mapped_column(Boolean, default=True)
    is_working: Mapped[bool] = mapped_column(Boolean, default=False)
    region_note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    replaced_holiday_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("holiday.id"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class WeeklyOffPattern(Base, TimestampMixin):
    """Reusable typed weekly-off rule set (WD-14 — typed rules, not JSONB; architecture
    §8.1). `pattern_kind` drives which `WeeklyOffRule` shapes are meaningful."""

    __tablename__ = "weekly_off_pattern"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(150))
    code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    pattern_kind: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class WeeklyOffRule(Base, TimestampMixin):
    """A single typed rule row within a `WeeklyOffPattern` (architecture §8.1) — e.g.
    "Saturday, nth=2", "Sunday, off_fraction=1.00". Carries its own `company_id` (denormalized
    child, matching the `employee_assignment` convention rather than relying on a join through
    `pattern_id`)."""

    __tablename__ = "weekly_off_rule"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    pattern_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("weekly_off_pattern.id"), index=True
    )
    weekday: Mapped[int] = mapped_column(SmallInteger)
    nth_in_month: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    cycle_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    off_fraction: Mapped[Decimal] = mapped_column(Numeric(3, 2), default=Decimal("1.00"))
    week_parity: Mapped[str | None] = mapped_column(String(4), nullable=True)


class WorkCalendar(Base, TimestampMixin):
    """The assignment-facing calendar (WD-01) — composes HolidayCalendars + a WeeklyOffPattern
    + dated exceptions into "what kind of day is this?" (architecture §6.1).
    `restricted_holidays_are_off_by_default` is the sanctioned per-company escape hatch for the
    open product decision PD-CAL-1 (default `False` — restricted/optional holidays are working
    days until Leave applies)."""

    __tablename__ = "work_calendar"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(150))
    code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    weekly_off_pattern_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("weekly_off_pattern.id"), nullable=True
    )
    restricted_holidays_are_off_by_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class WorkCalendarHolidayCalendar(Base):
    """Ordered composition join: which HolidayCalendars feed a WorkCalendar's holiday union
    (architecture §6.3 — "first HolidayCalendar in the ordered list supplies the display name
    if types otherwise tie"). No `TimestampMixin` (no `updated_at` — composition rows are
    replaced wholesale, never edited in place)."""

    __tablename__ = "work_calendar_holiday_calendar"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    work_calendar_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("work_calendar.id"), index=True
    )
    holiday_calendar_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("holiday_calendar.id"), index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CalendarException(Base, TimestampMixin):
    """A one-off dated override on a WorkCalendar (architecture §7.3) — always wins over the
    composed holiday/weekly-off classification for that date (§6.3 rule 1). Corrections are
    deactivate-then-insert; `exception_date`/`exception_type` are never edited in place once
    created."""

    __tablename__ = "calendar_exception"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    work_calendar_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("work_calendar.id"), index=True
    )
    exception_date: Mapped[date] = mapped_column(Date)
    exception_type: Mapped[str] = mapped_column(String(20))
    name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_paid: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class PolicyAssignment(Base, TimestampMixin):
    """Unified effective-dated assignment of a policy (WorkCalendar/WeeklyOffPattern in W1;
    Attendance/OT/Regularization policies from W3 onward) to a scope (architecture §15.1,
    WD-09 precedence). **Pulled forward from W3 into W1, restricted** (see WD-24 in the
    decision log) — `policy_kind` is checked at the DB level to only `WORK_CALENDAR`/
    `WEEKLY_OFF` for now. `policy_id` has no DB foreign key (polymorphic across
    `work_calendar`/`weekly_off_pattern`; validated at the service layer), mirroring
    `audit_log.entity_id`. Insert-new/close-previous only — no in-place mutation of a
    published assignment's core values (mirrors `EmployeeAssignment`).

    `leave_type_id` (LD-11): NULL for every kind except `LEAVE_POLICY`, where it's required — a
    company needs multiple simultaneous leave policies at the same scope (one per leave type),
    unlike every other kind where exactly one policy governs a scope. A real FK (unlike the
    polymorphic `policy_id`), since this column is never anything but a leave type."""

    __tablename__ = "policy_assignment"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    policy_kind: Mapped[str] = mapped_column(String(30))
    policy_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    leave_type_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("leave_type.id"), nullable=True
    )
    scope_type: Mapped[str] = mapped_column(String(20))
    scope_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
