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

Money is integer paise (`BIGINT`), percentages `NUMERIC(7,4)`."""

from datetime import date, datetime
from decimal import Decimal
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
)
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
