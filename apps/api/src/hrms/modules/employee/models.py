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
    scope (`01_EMPLOYEE_FOUNDATION_AUDIT.md` §2.2).

    `pan_number_enc`/`aadhaar_number_enc` are plain `String` columns at the SQLAlchemy level —
    **not** auto-encrypting (DATA-01,
    `docs/audits/DATA_01_PII_ENCRYPTION_IMPLEMENTATION_PLAN.md` §2.5). Whenever a future write
    path (E-02) populates them, it must call `hrms.core.crypto.service.PiiCryptoService.
    encrypt_column(table="employee", column=<name>, record_id=employee.id)` explicitly before
    persisting, and any read path must call `.decrypt_column(...)` explicitly, after its own
    permission check, before returning a value to a caller — the ORM attribute itself is never
    automatically decrypted, so an incidental load (a background job, an admin query) always sees
    ciphertext, never plaintext.

    `status` defaults to `PRE_JOINING`
    (FR-EMP-014, `docs/product/17_SRS_Phase1_Core_Modules.md:151`), DB `CHECK`-locked to the
    10-value enum as of the Employee confirmation feature — only two transitions exist:
    `EmploymentService.create_employment` moves `PRE_JOINING` -> `PROBATION` (guarded to only
    fire from `PRE_JOINING`, so a rejoin never resets an already-`ACTIVE` employee), and
    `EmployeeService.confirm_employee` moves `PROBATION` -> `ACTIVE` explicitly. No other
    transition (e.g. into `EXITED`, `SUSPENDED`) is wired yet — this is a deliberately minimal
    slice, not the full FR-EMP-010 confirmation workflow (no reminders, no manager-recommendation
    routing, no auto-extend/auto-confirm rules, no letter generation)."""

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
    # E-02 (market-parity onboarding-data pass) — EPF Form 11 field 2. Plain, not `_enc`: same
    # sensitivity tier as `first_name`/`last_name`, not PAN/Aadhaar-grade.
    father_or_husband_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    personal_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    personal_mobile: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # E-02 (market-parity onboarding-data pass, part 2) — `address_info`/`emergency_contact`
    # were collected during onboarding since O1 but never had an Employee-side column to land
    # on; `OnboardingActivationService.activate_case` silently dropped them (schemas.py's own
    # module docstring flagged this explicitly as "a known gap, not a silent one"). Flat columns,
    # not a child table — these are single current-value facts, same shape as
    # `gender`/`blood_group` above, not history. `permanent_*` mirrors `present_*` for the
    # market-standard two-address block; `permanent_same_as_present` lets the UI collapse the
    # permanent block into a copy of the present one without duplicating data entry.
    present_address_line1: Mapped[str | None] = mapped_column(String(200), nullable=True)
    present_address_line2: Mapped[str | None] = mapped_column(String(200), nullable=True)
    present_city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    present_state_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    present_pincode: Mapped[str | None] = mapped_column(String(10), nullable=True)
    present_country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    permanent_address_line1: Mapped[str | None] = mapped_column(String(200), nullable=True)
    permanent_address_line2: Mapped[str | None] = mapped_column(String(200), nullable=True)
    permanent_city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    permanent_state_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    permanent_pincode: Mapped[str | None] = mapped_column(String(10), nullable=True)
    permanent_country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    permanent_same_as_present: Mapped[bool] = mapped_column(Boolean, default=True)
    emergency_contact_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    emergency_contact_relationship: Mapped[str | None] = mapped_column(String(50), nullable=True)
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
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
    # Purely informational (mirrors Leave's LD-17 maternity-fields posture) — nothing reads or
    # auto-computes this; HR sets/corrects it directly. Not a trigger for anything: the actual
    # PROBATION -> ACTIVE transition is the explicit `EmployeeService.confirm_employee` action.
    probation_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
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

    `account_number_enc` is a plain `String` column at the SQLAlchemy level (DATA-01 does not
    change its DB type, plan §4 Option A) but is **DATA-01-encrypted at the application layer**:
    `EmployeeBankService.create_bank` calls `PiiCryptoService.encrypt_column(table=
    "employee_bank", column="account_number_enc", record_id=<this row's id>)` before the row is
    inserted, and every read path (`bank_to_read`) requires an explicitly-decrypted value passed
    in — the raw ORM attribute always holds ciphertext, never plaintext, and is never
    auto-decrypted on load (plan §2.5)."""

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


class EmployeeExperience(Base, TimestampMixin):
    """Previous employment / PF continuity (market-parity onboarding-data pass, part 4) — EPF
    Form 11's continuity block (previous UAN, PF account number, DOJ/DOE) plus Form 12B's
    salary-continuity fields, using the shape `docs/modules/employee/02_EMPLOYEE_DATA_MODEL.md`
    §2 pre-named (`company_name, designation, from/to date, last_ctc, reason_for_leaving,
    document_id`). Unlike `EmployeeStatutory`/`EmployeeBank`, this is a genuine one-to-many list
    — a candidate may have multiple past employers, all concurrently valid rows — not "one
    current value over time," so there is no effective-dating and no GiST exclusion constraint,
    just a plain `employee_id` FK, mirroring `OnboardingDocument`'s own "list of child rows"
    shape."""

    __tablename__ = "employee_experience"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    employee_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employee.id"), index=True
    )
    company_name: Mapped[str] = mapped_column(String(200))
    designation: Mapped[str | None] = mapped_column(String(150), nullable=True)
    from_date: Mapped[date] = mapped_column(Date)
    to_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_ctc_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reason_for_leaving: Mapped[str | None] = mapped_column(String, nullable=True)
    had_prior_pf_membership: Mapped[bool] = mapped_column(Boolean, default=False)
    # Same sensitivity tier as `Employee.uan_number` — plain, not `_enc` (plan §1's own posture).
    previous_uan: Mapped[str | None] = mapped_column(String(20), nullable=True)
    previous_pf_account_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    previous_esi_ip_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    document_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class EmployeeEducation(Base, TimestampMixin):
    """Education history (market-parity onboarding-data pass, part 5) — same "plain list" shape
    as `EmployeeExperience`: a candidate may hold multiple qualifications, all concurrently
    valid, so this is a plain `employee_id` FK with no effective-dating. Field shape
    (`qualification, institution_name, year_of_passing, document_id`) matches
    `docs/modules/employee/02_EMPLOYEE_DATA_MODEL.md` §2's own `employee_education` row."""

    __tablename__ = "employee_education"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    employee_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employee.id"), index=True
    )
    qualification: Mapped[str] = mapped_column(String(150))
    institution_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    year_of_passing: Mapped[int | None] = mapped_column(Integer, nullable=True)
    document_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class EmployeeDependent(Base, TimestampMixin):
    """PF/Gratuity nominee declaration + ESI family details (market-parity onboarding-data
    pass, part 6) — per EPF Form 2, Gratuity Form F, and ESI Form 1/Form 2. Same "plain list"
    shape as `EmployeeExperience`/`EmployeeEducation`: an employee may declare several
    dependents, all concurrently valid, so this is a plain `employee_id` FK with no
    effective-dating and no GiST exclusion constraint.

    `aadhaar_number_enc` is a plain `String` column at the SQLAlchemy level but is
    **DATA-01-encrypted at the application layer**, same contract as `EmployeeBank.
    account_number_enc`: `EmployeeDependentService.create_dependent` calls `PiiCryptoService.
    encrypt_column(table="employee_dependent", column="aadhaar_number_enc", record_id=<this
    row's id>)` before insert, and every read path requires an explicitly-decrypted value passed
    in — the raw ORM attribute always holds ciphertext, never plaintext.

    A dependent may be declared a nominee under PF and/or Gratuity independently
    (`is_pf_nominee`/`is_gratuity_nominee`), each with its own share percentage — application-
    layer validation (`EmployeeDependentService`) keeps each scheme's percentages summing to
    <=100 across an employee's dependents, since a DB `CHECK` cannot aggregate across rows.
    `is_esi_dependent` has no percentage — ESI family coverage is not proportioned. `is_minor`/
    `guardian_name`/`guardian_relationship` mirror EPF Form 2's own minor-nominee guardian
    block."""

    __tablename__ = "employee_dependent"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    employee_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employee.id"), index=True
    )
    full_name: Mapped[str] = mapped_column(String(150))
    relationship: Mapped[str] = mapped_column(String(50))
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_minor: Mapped[bool] = mapped_column(Boolean, default=False)
    guardian_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    guardian_relationship: Mapped[str | None] = mapped_column(String(50), nullable=True)
    aadhaar_number_enc: Mapped[str | None] = mapped_column(String, nullable=True)
    is_pf_nominee: Mapped[bool] = mapped_column(Boolean, default=False)
    pf_nominee_share_percentage: Mapped[float | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    is_gratuity_nominee: Mapped[bool] = mapped_column(Boolean, default=False)
    gratuity_nominee_share_percentage: Mapped[float | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    is_esi_dependent: Mapped[bool] = mapped_column(Boolean, default=False)
    document_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
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
