"""ORM models owned by the employee module.

Covers E-01 (Employee Foundation — `Employee`, `NumberSeries`), E-03 (Employment Lifecycle —
`Employment`), E-04 (Employee Assignment — `EmployeeAssignment`), E-06 (Employee Compensation —
`EmployeeCompensation`), E-07 (Employee Statutory — `EmployeeStatutory`), and E-08 (Employee
Banking — `EmployeeBank`).
"""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from hrms.core.db.base import Base, TimestampMixin


class Employee(Base, TimestampMixin):
    """Permanent employee identity (docs/modules/employee/05_EMPLOYEE_ARCHITECTURE_DECISIONS.md
    Part C) — `id`/`employee_code` are never reissued, including across a rehire. Deliberately
    does not carry anything that changes with the job (department/designation/branch/manager/
    shift — Assignment, E-04), anything scoped to one continuous spell (joining/exit dates —
    Employment, E-03), or pay (Compensation, E-06). `pan_number_enc`/`aadhaar_number_enc`/
    `uan_number` exist as columns (per `02_EMPLOYEE_DATA_MODEL.md` §3's ALTER TABLE target) but
    have no write path in this slice — `EMPLOYEE.UPDATE_SENSITIVE` is out of E-01's permission
    scope (`01_EMPLOYEE_FOUNDATION_AUDIT.md` §2.2). `status` defaults to `PRE_JOINING`
    (FR-EMP-014, `docs/product/17_SRS_Phase1_Core_Modules.md:151`) and is system-managed only —
    no lifecycle transition exists yet in this slice."""

    __tablename__ = "employee"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id"), nullable=True
    )
    employee_code: Mapped[str] = mapped_column(String(30))
    first_name: Mapped[str] = mapped_column(String(100))
    middle_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(20), nullable=True)
    blood_group: Mapped[str | None] = mapped_column(String(10), nullable=True)
    marital_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    nationality: Mapped[str | None] = mapped_column(String(80), nullable=True)
    personal_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    personal_mobile: Mapped[str | None] = mapped_column(String(20), nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String, nullable=True)
    pan_number_enc: Mapped[str | None] = mapped_column(String, nullable=True)
    aadhaar_number_enc: Mapped[str | None] = mapped_column(String, nullable=True)
    uan_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(25), default="PRE_JOINING")
    custom_fields: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class Employment(Base, TimestampMixin):
    """One continuous employment spell at one legal entity
    (`docs/modules/employee/05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part C) — 1:N from
    `Employee`, keyed on `employee_id`. A spell is never mutated to represent a rehire;
    rejoining always inserts a new row linked via `previous_employment_id` (self-referential,
    mirroring `Designation.next_designation_id`'s existing precedent). `status` is locked to
    exactly two stored values (`ACTIVE`/`TERMINATED`, DB `CHECK`-enforced) —
    `docs/modules/employee/07_EMPLOYMENT_STATUS_DECISION.md` investigated the value set but
    left it open; the two-value set with no stored `ON_NOTICE` is this task's own authoritative
    decision, not invented here. `last_working_day` is set if and only if `status =
    'TERMINATED'` (DB `CHECK`-enforced) — notice state is derived from this column at the
    service layer, never stored. A GiST exclusion constraint
    (`employment_no_overlap`) prevents two spells for the same employee from having
    overlapping `[joining_date, last_working_day]` ranges, which is also what makes "at most
    one `ACTIVE` employment per employee" a database-level guarantee, not just an application
    check."""

    __tablename__ = "employment"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    employee_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employee.id"), index=True
    )
    legal_entity_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("legal_entity.id")
    )
    joining_date: Mapped[date] = mapped_column(Date)
    last_working_day: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    previous_employment_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employment.id"), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class EmployeeAssignment(Base, TimestampMixin):
    """The employee's organisational placement over time — branch, department, designation,
    grade, reporting line, cost centre, work location
    (`docs/modules/employee/05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part B3/C). Keyed on
    `employee_id`, **not** `employment_id` — deliberate, not an oversight: this is what makes
    a rehire correct without special-case code (the assignment/employment tables share no FK,
    so a five-year gap between employment episodes simply produces zero assignment rows during
    the gap, not a data-integrity problem). A GiST exclusion constraint
    (`employee_assignment_no_overlap`, already live since the very first migration) prevents
    two rows for the same employee from having overlapping `[effective_from, effective_to]`
    ranges — the same mechanism `Employment` uses for `employment_no_overlap`. `shift_id`
    (E-05) follows the same nullable-FK shape as `branch_id`/`department_id`/etc.
    (`docs/modules/employee/13_EMPLOYEE_SHIFT_ASSIGNMENT_IMPLEMENTATION_PLAN.md` §6)."""

    __tablename__ = "employee_assignment"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    employee_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employee.id"), index=True
    )
    branch_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("branch.id"), nullable=True
    )
    department_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("department.id"), nullable=True
    )
    designation_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("designation.id"), nullable=True
    )
    grade_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("grade.id"), nullable=True
    )
    reporting_manager_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employee.id"), nullable=True
    )
    dotted_line_manager_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employee.id"), nullable=True
    )
    cost_centre_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    shift_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("shift.id"), nullable=True
    )
    work_location_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    change_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    change_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class EmployeeCompensation(Base, TimestampMixin):
    """Pay, effective-dated independently of Assignment — a raise without a transfer, or a
    transfer without a raise, are both representable without coupling the two tables
    (`docs/modules/employee/05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part C "Employee
    Compensation"). Keyed on `employee_id`, **not** `employment_id`, the same rehire-correctness
    shape as `EmployeeAssignment` (§5/§10 of `docs/modules/employee/
    17_EMPLOYEE_COMPENSATION_IMPLEMENTATION_PLAN.md`). A GiST exclusion constraint
    (`employee_compensation_no_overlap`, already live since the very first migration) prevents
    two rows for the same employee from having overlapping `[effective_from, effective_to]`
    ranges. `revision_type`/`revision_reason` (E-06) were added by an additive migration on top
    of the pre-existing table; `salary_structure_id`/`monthly_gross`/`approved_by`/
    `approval_request_id`/`is_arrears_processed` and the component-breakdown child table are
    deferred — they depend on modules (Payroll's salary-structure catalogue, the
    approval-routing engine) that do not exist yet (plan §4.2)."""

    __tablename__ = "employee_compensation"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    employee_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employee.id"), index=True
    )
    annual_ctc_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    revision_type: Mapped[str] = mapped_column(String(20), default="JOINING")
    revision_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class EmployeeStatutory(Base, TimestampMixin):
    """The employee's own PF/ESI/PT/LWF applicability and tax-regime profile, effective-dated
    independently of Assignment/Compensation (`docs/modules/employee/
    29_EMPLOYEE_STATUTORY_IMPLEMENTATION_PLAN.md` §7). Keyed on `employee_id`, **not**
    `employment_id`, the same rehire-correctness shape as `EmployeeAssignment`/
    `EmployeeCompensation` (plan §9). A GiST exclusion constraint
    (`employee_statutory_no_overlap`) prevents two rows for the same employee from having
    overlapping `[effective_from, effective_to]` ranges. Deliberately excludes `uan` — that stays
    on `employee.uan_number`, never duplicated here (plan §5) — and every payroll rate/
    calculation field, which belongs to Payroll, not this table (plan §13)."""

    __tablename__ = "employee_statutory"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    employee_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employee.id"), index=True
    )
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_pf_applicable: Mapped[bool] = mapped_column(Boolean, default=False)
    pf_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    pf_wage_ceiling_opt_out: Mapped[bool] = mapped_column(Boolean, default=False)
    vpf_amount: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    vpf_percentage: Mapped[float | None] = mapped_column(Numeric(9, 4), nullable=True)
    is_esi_applicable: Mapped[bool] = mapped_column(Boolean, default=False)
    esi_ip_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    pt_state_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    is_lwf_applicable: Mapped[bool] = mapped_column(Boolean, default=False)
    tax_regime: Mapped[str | None] = mapped_column(String(10), nullable=True)
    is_director: Mapped[bool] = mapped_column(Boolean, default=False)
    is_international_worker: Mapped[bool] = mapped_column(Boolean, default=False)
    revision_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class EmployeeBank(Base, TimestampMixin):
    """The employee's own payout-account facts, effective-dated independently of Assignment/
    Compensation/Statutory (`docs/modules/employee/33_EMPLOYEE_BANKING_IMPLEMENTATION_PLAN.md`
    §6). Keyed on `employee_id`, **not** `employment_id`, the same rehire-correctness shape as
    `EmployeeAssignment`/`EmployeeCompensation`/`EmployeeStatutory`. A GiST exclusion constraint
    (`employee_bank_no_overlap`) prevents two rows for the same employee from having overlapping
    `[effective_from, effective_to]` ranges.

    Unlike Assignment/Compensation/Statutory, this table's current row is **not** closed by
    `EmploymentService.terminate_employment` — a locked architecture decision
    (`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part C "Employee Bank") keeps it open through and
    after exit, since it is still needed for full-and-final settlement payout after the
    employee has left (plan §7). No other Employee sub-resource has this behavior.

    `account_number_enc` is a plain, unencrypted `TEXT` column today — the same posture as
    `Employee.pan_number_enc`/`aadhaar_number_enc`, an explicitly accepted, documented gap
    (`HRMS_SYSTEM_DESIGN_BASELINE.md` Decision D-2 Option 2; plan §14/§22 PD-4), not a silent
    oversight. Real account numbers must not be written here before that decision is revisited."""

    __tablename__ = "employee_bank"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    employee_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employee.id"), index=True
    )
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    account_holder_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    account_number_enc: Mapped[str | None] = mapped_column(String, nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    ifsc: Mapped[str | None] = mapped_column(String(15), nullable=True)
    branch_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    payment_mode: Mapped[str | None] = mapped_column(String(10), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True)
    verification_status: Mapped[str] = mapped_column(String(20), default="PENDING")
    penny_drop_reference: Mapped[str | None] = mapped_column(String(60), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class NumberSeries(Base, TimestampMixin):
    """Race-safe sequential code allocator (`docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md`
    Task 4.5.1 shape), scoped to `EMPLOYEE_CODE` only for this slice. Built inside the employee
    module rather than `organisation` — deliberate deviation from that sprint doc's original
    placement, since this task's locked decisions forbid adding Employee implementation into
    `organisation/` (`01_EMPLOYEE_FOUNDATION_AUDIT.md` §1.6). `(company_id, entity_type)` is
    unique — one series per entity type per company."""

    __tablename__ = "number_series"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    entity_type: Mapped[str] = mapped_column(String(30))
    prefix: Mapped[str] = mapped_column(String(10))
    separator: Mapped[str] = mapped_column(String(3), default="-")
    current_number: Mapped[int] = mapped_column(Integer, default=0)
    padding: Mapped[int] = mapped_column(Integer, default=4)
    reset_rule: Mapped[str] = mapped_column(String(10), default="NEVER")
    last_reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
