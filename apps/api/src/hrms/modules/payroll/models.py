"""ORM models owned by the Payroll module.

Phase 5.1 (`docs/modules/payroll/00_PAYROLL_IMPLEMENTATION_PLAN.md`) — salary setup:

- `SalaryComponent` — the company's component master (Basic, HRA, Special Allowance, Employer
  PF, …). System components are seeded per company and cannot change code or type.
- `SalaryStructure` / `SalaryStructureVersion` / `SalaryStructureLine` — a template, versioned
  like every policy in this system: one editable `DRAFT` at a time, `PUBLISHED` versions are
  immutable and effective-dated, publishing closes the previous one.
- `EmployeeSalary` — which structure (monthly-paid) or daily rate (daily-wage, D5) applies to an
  employee from a date. CTC itself stays on `employee_compensation`; this table never stores it
  (one source of truth for CTC).

Phase 5.2 — pay runs: `PayrollSetting`, `PayRun`, `PayRunEmployee` (input snapshot + totals),
`PayRunLine` (per component, with trace).

Money is integer paise (`BIGINT`), percentages `NUMERIC(7,4)`."""

from datetime import date, datetime
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
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from hrms.core.db.base import Base, TimestampMixin


class SalaryComponent(Base, TimestampMixin):
    __tablename__ = "salary_component"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(150))
    # EARNING / DEDUCTION / EMPLOYER_CONTRIBUTION
    component_type: Mapped[str] = mapped_column(String(25))
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    is_taxable: Mapped[bool] = mapped_column(Boolean, default=True)
    is_pf_wage: Mapped[bool] = mapped_column(Boolean, default=False)
    is_esi_wage: Mapped[bool] = mapped_column(Boolean, default=False)
    # Scaled by paid days ÷ days in month in a pay run (decision 17).
    is_prorated: Mapped[bool] = mapped_column(Boolean, default=True)
    show_on_payslip: Mapped[bool] = mapped_column(Boolean, default=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class SalaryStructure(Base, TimestampMixin):
    __tablename__ = "salary_structure"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(150))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class SalaryStructureVersion(Base, TimestampMixin):
    __tablename__ = "salary_structure_version"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    salary_structure_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("salary_structure.id"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")  # DRAFT / PUBLISHED
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)


class SalaryStructureLine(Base, TimestampMixin):
    __tablename__ = "salary_structure_line"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    salary_structure_version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("salary_structure_version.id"), index=True
    )
    salary_component_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("salary_component.id")
    )
    calculation_type: Mapped[str] = mapped_column(String(30))
    percentage: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    amount_monthly_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    base_salary_component_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("salary_component.id"), nullable=True
    )
    max_monthly_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    applies_when: Mapped[str] = mapped_column(String(20), default="ALWAYS")
    display_order: Mapped[int] = mapped_column(Integer, default=0)


class EmployeeSalary(Base, TimestampMixin):
    """Effective-dated like `employee_compensation`: a new row closes the open one. Exactly one of
    `salary_structure_id` (monthly-paid) and `daily_rate_minor` (daily-wage, D5) is set (DB
    CHECK); no overlapping rows per employee (GiST exclusion)."""

    __tablename__ = "employee_salary"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    employee_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employee.id"), index=True
    )
    salary_structure_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("salary_structure.id"), nullable=True
    )
    daily_rate_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


# ---------------------------------------------------------------------------
# Phase 5.2 — pay runs
# ---------------------------------------------------------------------------


class PayrollSetting(Base, TimestampMixin):
    """One row per company, created on first read. D10 — the per-employee net-pay change that
    flags a variance for acknowledgement before approval."""

    __tablename__ = "payroll_setting"

    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), primary_key=True
    )
    variance_threshold_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal(15))
    version: Mapped[int] = mapped_column(Integer, default=1)


class PayRun(Base, TimestampMixin):
    """One per (legal entity, calendar month) (decisions 14/18). Lifecycle
    `DRAFT → INPUTS_LOCKED → COMPUTED → APPROVED → FINALISED → PAID`; a rollback returns to
    `DRAFT` or `INPUTS_LOCKED` before `FINALISED`. A `FINALISED`/`PAID` run never changes other
    than being marked paid (ADR-0005) — `PayRunRepository` conditions every write on that.

    `attendance_period_id`/`attendance_period_version` record the `CLOSED` attendance period the
    inputs were snapshotted from; approval and finalisation refuse if that period has since been
    reopened (its version moved)."""

    __tablename__ = "pay_run"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    legal_entity_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("legal_entity.id"), index=True
    )
    period_month: Mapped[date] = mapped_column(Date)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    days_in_month: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")
    pay_date: Mapped[date] = mapped_column(Date)
    attendance_period_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("attendance_period.id"), nullable=True
    )
    attendance_period_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    variance_threshold_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    previous_pay_run_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("pay_run.id"), nullable=True
    )
    employee_count: Mapped[int] = mapped_column(Integer, default=0)
    gross_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    deductions_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    employer_contributions_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    net_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, default=0)
    variance_flag_count: Mapped[int] = mapped_column(Integer, default=0)
    variance_open_count: Mapped[int] = mapped_column(Integer, default=0)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    inputs_locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    inputs_locked_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    computed_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    finalised_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finalised_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    last_rollback_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class PayRunEmployee(Base, TimestampMixin):
    """One employee in a run: the input snapshot taken at lock-inputs (`snapshot`, the only thing
    computation reads), the computed totals, validation issues, and the variance against the
    previous finalised run of the same legal entity."""

    __tablename__ = "pay_run_employee"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    pay_run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("pay_run.id", ondelete="CASCADE"), index=True
    )
    employee_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employee.id"), index=True
    )
    employee_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    employee_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    pay_basis: Mapped[str | None] = mapped_column(String(20), nullable=True)
    paid_days: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    lop_days: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    payable_days: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    is_computed: Mapped[bool] = mapped_column(Boolean, default=False)
    gross_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    deductions_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    employer_contributions_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    net_before_rounding_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    rounding_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    net_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    issues: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    has_error: Mapped[bool] = mapped_column(Boolean, default=False)
    previous_net_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    variance_percent: Mapped[Decimal | None] = mapped_column(Numeric(9, 2), nullable=True)
    variance_flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    variance_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    variance_acknowledged_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    variance_acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Phase 5.4 — payslip header facts and month-end leave balances, captured at finalise.
    payslip_details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class PayRunLine(Base):
    """One component of one employee's pay, with how it was reached (`trace`). Written by compute,
    replaced on recompute, never edited."""

    __tablename__ = "pay_run_line"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    pay_run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("pay_run.id", ondelete="CASCADE"), index=True
    )
    pay_run_employee_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("pay_run_employee.id", ondelete="CASCADE")
    )
    employee_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employee.id"))
    component_code: Mapped[str] = mapped_column(String(30))
    component_name: Mapped[str] = mapped_column(String(150))
    line_type: Mapped[str] = mapped_column(String(25))
    full_monthly_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    trace: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# Phase 5.3 — statutory rate master
# ---------------------------------------------------------------------------


class StatutoryRate(Base, TimestampMixin):
    """Effective-dated statutory rates per company (FR-PAY-005, BR-10): `PF`/`ESI` national
    (`state_code` NULL), `PT`/`LWF` per state. `parameters` holds the scheme's numbers, validated
    per scheme by the service. `verified_at` is the compliance sign-off — a pay run using an
    unverified rate cannot be approved; any edit clears it."""

    __tablename__ = "statutory_rate"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    scheme: Mapped[str] = mapped_column(String(10))
    state_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_seeded: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)


# ---------------------------------------------------------------------------
# Phase 5.5 — arrears
# ---------------------------------------------------------------------------


class PayAdjustment(Base, TimestampMixin):
    """D7 — a correction to a finalised month's paid days. The finalised attendance period stays
    closed; the entity's next pay run pays (or recovers) the difference as arrears. `PENDING`
    until that run is finalised, then `APPLIED`."""

    __tablename__ = "pay_adjustment"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    legal_entity_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("legal_entity.id")
    )
    employee_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employee.id"))
    for_month: Mapped[date] = mapped_column(Date)
    source_pay_run_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("pay_run.id"))
    paid_days_delta: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    applied_pay_run_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("pay_run.id"), nullable=True
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)


class PayRunArrear(Base):
    """Attribution of a run's arrears: which month, from which earlier finalised run, per
    component. Written by compute, replaced on recompute."""

    __tablename__ = "pay_run_arrear"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    pay_run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("pay_run.id", ondelete="CASCADE")
    )
    employee_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employee.id"))
    for_month: Mapped[date] = mapped_column(Date)
    source_pay_run_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("pay_run.id"))
    component_code: Mapped[str] = mapped_column(String(30))
    line_type: Mapped[str] = mapped_column(String(25))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
