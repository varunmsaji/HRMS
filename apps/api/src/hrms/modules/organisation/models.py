"""ORM models owned by the organisation module."""

from datetime import datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
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
    `head_employee_id` exists at the DB level only (Sprint 3 Scope Decision D10) — not
    exposed by any schema/service/UI this slice, since Employee does not exist yet.
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
    # No `Employee` ORM model exists yet (Employee is out of scope this slice), so this
    # can't be a SQLAlchemy `ForeignKey("employee.id")` — that would fail to resolve
    # against this Base's metadata. The real FK constraint is still enforced at the
    # database level by the migration; this is a plain UUID column at the ORM layer.
    head_employee_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
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
