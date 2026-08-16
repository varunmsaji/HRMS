"""Pydantic request/response schemas for the employee module — E-01 (identity foundation) only.

Fields deliberately excluded from `EmployeeCreate`/`EmployeeUpdate`, and why:
- `employee_code`: system-generated via the `number_series` allocator, never client-settable.
- `status`: system-managed via lifecycle actions (FR-EMP-014); no transition exists in this
  slice, so it is set once at creation (`PRE_JOINING`) and never exposed as writable.
- `display_name`: derived, not directly editable.
- `pan_number_enc` / `aadhaar_number_enc` / `uan_number`: documented as requiring
  `EMPLOYEE.UPDATE_SENSITIVE` (`02_EMPLOYEE_DATA_MODEL.md` §2 section A), a permission out of
  E-01's scope (`01_EMPLOYEE_FOUNDATION_AUDIT.md` §2.2) — the columns exist at the DB level but
  have no write path until the slice that adds that permission.
- `user_id`: system-managed (login provisioning), not client-settable.
"""

from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from hrms.modules.employee.models import (
        Employee,
        EmployeeAssignment,
        EmployeeBank,
        EmployeeCompensation,
        EmployeeStatutory,
        Employment,
    )

# FR-EMP-014 (docs/product/17_SRS_Phase1_Core_Modules.md:151) — the authoritative 10-value
# enumeration found in Phase 0 decision verification. Not client-writable (see module
# docstring); exposed here only so `EmployeeRead.status` and tests have one source of truth.
EMPLOYEE_STATUS_VALUES = (
    "PRE_JOINING",
    "PROBATION",
    "ACTIVE",
    "ON_NOTICE",
    "SUSPENDED",
    "ON_LONG_LEAVE",
    "EXITED",
    "ABSCONDING",
    "RETIRED",
    "DECEASED",
)


class EmployeeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    first_name: str = Field(min_length=1, max_length=100)
    middle_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    date_of_birth: date | None = None
    gender: str | None = Field(default=None, max_length=20)
    blood_group: str | None = Field(default=None, max_length=10)
    marital_status: str | None = Field(default=None, max_length=20)
    nationality: str | None = Field(default=None, max_length=80)
    personal_email: str | None = Field(default=None, max_length=255)
    personal_mobile: str | None = Field(default=None, max_length=20)
    photo_url: str | None = None
    custom_fields: dict[str, Any] | None = None


class EmployeeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    middle_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    date_of_birth: date | None = None
    gender: str | None = Field(default=None, max_length=20)
    blood_group: str | None = Field(default=None, max_length=10)
    marital_status: str | None = Field(default=None, max_length=20)
    nationality: str | None = Field(default=None, max_length=80)
    personal_email: str | None = Field(default=None, max_length=255)
    personal_mobile: str | None = Field(default=None, max_length=20)
    photo_url: str | None = None
    custom_fields: dict[str, Any] | None = None
    is_active: bool | None = None


class EmployeeRead(BaseModel):
    id: UUID
    company_id: UUID
    employee_code: str
    first_name: str
    middle_name: str | None
    last_name: str | None
    display_name: str | None
    date_of_birth: date | None
    gender: str | None
    blood_group: str | None
    marital_status: str | None
    nationality: str | None
    personal_email: str | None
    personal_mobile: str | None
    photo_url: str | None
    status: str
    custom_fields: dict[str, Any] | None
    is_active: bool
    version: int
    created_at: str
    updated_at: str


def _format_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


def employee_to_read(employee: "Employee") -> EmployeeRead:
    return EmployeeRead(
        id=employee.id,
        company_id=employee.company_id,
        employee_code=employee.employee_code,
        first_name=employee.first_name,
        middle_name=employee.middle_name,
        last_name=employee.last_name,
        display_name=employee.display_name,
        date_of_birth=employee.date_of_birth,
        gender=employee.gender,
        blood_group=employee.blood_group,
        marital_status=employee.marital_status,
        nationality=employee.nationality,
        personal_email=employee.personal_email,
        personal_mobile=employee.personal_mobile,
        photo_url=employee.photo_url,
        status=employee.status,
        custom_fields=employee.custom_fields,
        is_active=employee.is_active,
        version=employee.version,
        created_at=_format_timestamp(employee.created_at) or "",
        updated_at=_format_timestamp(employee.updated_at) or "",
    )


def employee_to_audit_dict(employee: EmployeeRead) -> dict[str, Any]:
    return employee.model_dump(mode="json")


def build_employee_update_values(patch: EmployeeUpdate) -> dict[str, Any]:
    """Only fields explicitly present in the request are applied — unset fields must not
    clobber existing values (mirrors `build_grade_update_values`)."""
    values: dict[str, Any] = {}
    for field in patch.model_fields_set:
        values[field] = getattr(patch, field)
    return values


# --- Employment (E-03) ------------------------------------------------------------------
#
# `status` is locked to exactly two stored values — this task's own authoritative decision,
# not a value set any source document settles
# (`docs/modules/employee/07_EMPLOYMENT_STATUS_DECISION.md`). `ON_NOTICE` is deliberately not
# a stored value; notice state is derived from `last_working_day` by callers, never persisted.
EMPLOYMENT_STATUS_VALUES = ("ACTIVE", "TERMINATED")


class EmploymentCreate(BaseModel):
    """Creates a new employment episode for an existing employee — covers both a first hire
    (no prior employment rows) and a rehire (at least one prior, necessarily `TERMINATED`,
    episode exists). The distinction is not client-supplied: `previous_employment_id` is
    always computed server-side from the employee's own employment history, never accepted as
    input (`status`/`version` are likewise system-set, never client-settable)."""

    model_config = ConfigDict(extra="forbid")

    legal_entity_id: UUID
    joining_date: date


class EmploymentUpdate(BaseModel):
    """Only `legal_entity_id` is correctable post-creation. `joining_date` is a historical
    fact once recorded (no document states it is ever legitimately revised, and every other
    slice in this codebase treats a spell's start as immutable); `status`/`last_working_day`
    only ever change via the dedicated `terminate` action, never a generic field patch — this
    keeps the one-way `ACTIVE` → `TERMINATED` transition from being reachable through an
    unvalidated arbitrary-field update."""

    model_config = ConfigDict(extra="forbid")

    legal_entity_id: UUID | None = None


class EmploymentTerminate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    last_working_day: date


class EmploymentRead(BaseModel):
    id: UUID
    company_id: UUID
    employee_id: UUID
    legal_entity_id: UUID
    joining_date: date
    last_working_day: date | None
    status: str
    previous_employment_id: UUID | None
    version: int
    created_at: str
    updated_at: str


def employment_to_read(employment: "Employment") -> EmploymentRead:
    return EmploymentRead(
        id=employment.id,
        company_id=employment.company_id,
        employee_id=employment.employee_id,
        legal_entity_id=employment.legal_entity_id,
        joining_date=employment.joining_date,
        last_working_day=employment.last_working_day,
        status=employment.status,
        previous_employment_id=employment.previous_employment_id,
        version=employment.version,
        created_at=_format_timestamp(employment.created_at) or "",
        updated_at=_format_timestamp(employment.updated_at) or "",
    )


def employment_to_audit_dict(employment: EmploymentRead) -> dict[str, Any]:
    return employment.model_dump(mode="json")


def build_employment_update_values(patch: EmploymentUpdate) -> dict[str, Any]:
    """Only fields explicitly present in the request are applied — mirrors
    `build_employee_update_values`."""
    values: dict[str, Any] = {}
    for field in patch.model_fields_set:
        values[field] = getattr(patch, field)
    return values


# --- Employee Assignment (E-04) ---------------------------------------------------------
#
# No literal `change_type`/`work_location_type` enumeration is stated in any authoritative
# document — both are this task's own engineering decision, derived from the three named
# workflows (FR-EMP-011/012/013) plus the "no current row" case
# (`docs/modules/employee/09_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_PLAN.md` §14.2) and the
# documented `work_location_type` field
# (`02_EMPLOYEE_DATA_MODEL.md` §2 section D: "OFFICE/WFH/HYBRID/FIELD"). `SHIFT_CHANGE` (E-05)
# is a fifth value added on top, per
# `docs/modules/employee/13_EMPLOYEE_SHIFT_ASSIGNMENT_IMPLEMENTATION_PLAN.md` §6.2.
ASSIGNMENT_CHANGE_TYPE_VALUES = (
    "INITIAL",
    "TRANSFER",
    "PROMOTION",
    "MANAGER_CHANGE",
    "SHIFT_CHANGE",
)
WORK_LOCATION_TYPE_VALUES = ("OFFICE", "WFH", "HYBRID", "FIELD")

AssignmentChangeType = Literal["INITIAL", "TRANSFER", "PROMOTION", "MANAGER_CHANGE", "SHIFT_CHANGE"]
WorkLocationType = Literal["OFFICE", "WFH", "HYBRID", "FIELD"]


class AssignmentCreate(BaseModel):
    """Creates a new effective-dated assignment row — covers initial placement, transfer,
    promotion, and manager change alike; all are the same insert-a-new-row operation,
    distinguished only by `change_type` (plan §9). Every organisational reference field is
    optional here even though `branch_id`/`department_id`/`designation_id` are mandatory for
    an employee's very first assignment — when a current row exists, an omitted field carries
    forward unchanged from it (`03_EMPLOYEE_API_PLAN.md` §2.2); the "required on first row"
    rule is therefore enforced in the service, not this schema (plan §14.3)."""

    model_config = ConfigDict(extra="forbid")

    effective_from: date
    change_type: AssignmentChangeType
    change_reason: str | None = None
    branch_id: UUID | None = None
    department_id: UUID | None = None
    designation_id: UUID | None = None
    grade_id: UUID | None = None
    reporting_manager_id: UUID | None = None
    dotted_line_manager_id: UUID | None = None
    cost_centre_id: UUID | None = None
    shift_id: UUID | None = None
    work_location_type: WorkLocationType | None = None


class AssignmentRead(BaseModel):
    id: UUID
    company_id: UUID
    employee_id: UUID
    branch_id: UUID | None
    department_id: UUID | None
    designation_id: UUID | None
    grade_id: UUID | None
    reporting_manager_id: UUID | None
    dotted_line_manager_id: UUID | None
    cost_centre_id: UUID | None
    shift_id: UUID | None
    work_location_type: str | None
    change_type: str | None
    change_reason: str | None
    effective_from: date
    effective_to: date | None
    version: int
    created_at: str
    updated_at: str


def assignment_to_read(assignment: "EmployeeAssignment") -> AssignmentRead:
    return AssignmentRead(
        id=assignment.id,
        company_id=assignment.company_id,
        employee_id=assignment.employee_id,
        branch_id=assignment.branch_id,
        department_id=assignment.department_id,
        designation_id=assignment.designation_id,
        grade_id=assignment.grade_id,
        reporting_manager_id=assignment.reporting_manager_id,
        dotted_line_manager_id=assignment.dotted_line_manager_id,
        cost_centre_id=assignment.cost_centre_id,
        shift_id=assignment.shift_id,
        work_location_type=assignment.work_location_type,
        change_type=assignment.change_type,
        change_reason=assignment.change_reason,
        effective_from=assignment.effective_from,
        effective_to=assignment.effective_to,
        version=assignment.version,
        created_at=_format_timestamp(assignment.created_at) or "",
        updated_at=_format_timestamp(assignment.updated_at) or "",
    )


def assignment_to_audit_dict(assignment: AssignmentRead) -> dict[str, Any]:
    return assignment.model_dump(mode="json")


# --- Employee Compensation (E-06) -------------------------------------------------------
#
# The only place any `revision_type` value set appears in any authoritative document —
# `docs/product/08_Database_Architecture.md:242` — fully specified, never contradicted
# (`docs/modules/employee/17_EMPLOYEE_COMPENSATION_IMPLEMENTATION_PLAN.md` §9). Validated at the
# Pydantic layer as a `Literal`, matching the actually-shipped precedent (`employment.status`,
# `employee_assignment.change_type`) rather than a DB `CHECK` constraint or a lookup table.
REVISION_TYPE_VALUES = ("JOINING", "ANNUAL", "PROMOTION", "CORRECTION", "MARKET")

RevisionType = Literal["JOINING", "ANNUAL", "PROMOTION", "CORRECTION", "MARKET"]


class CompensationCreate(BaseModel):
    """Creates a new effective-dated compensation row — closes the employee's current row (if
    any) and inserts a new one. Unlike `AssignmentCreate`, no field carries forward from the
    current row: `annual_ctc_minor`, `currency`, `revision_type`, and `revision_reason` are
    always required, on every write, including an employee's very first compensation row
    (plan §17.2/§17.3) — a stale CTC carried forward by omission is a materially worse failure
    mode than a stale org-placement field."""

    model_config = ConfigDict(extra="forbid")

    effective_from: date
    annual_ctc_minor: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    revision_type: RevisionType
    revision_reason: str


class CompensationRead(BaseModel):
    id: UUID
    company_id: UUID
    employee_id: UUID
    annual_ctc_minor: int
    currency: str
    revision_type: str
    revision_reason: str | None
    effective_from: date
    effective_to: date | None
    version: int
    created_at: str
    updated_at: str


def compensation_to_read(compensation: "EmployeeCompensation") -> CompensationRead:
    return CompensationRead(
        id=compensation.id,
        company_id=compensation.company_id,
        employee_id=compensation.employee_id,
        annual_ctc_minor=compensation.annual_ctc_minor,
        currency=compensation.currency,
        revision_type=compensation.revision_type,
        revision_reason=compensation.revision_reason,
        effective_from=compensation.effective_from,
        effective_to=compensation.effective_to,
        version=compensation.version,
        created_at=_format_timestamp(compensation.created_at) or "",
        updated_at=_format_timestamp(compensation.updated_at) or "",
    )


def compensation_to_audit_dict(compensation: CompensationRead) -> dict[str, Any]:
    return compensation.model_dump(mode="json")


# --- Employee Statutory (E-07) ----------------------------------------------------------
#
# The only two values `docs/modules/employee/29_EMPLOYEE_STATUTORY_IMPLEMENTATION_PLAN.md` §16
# names for `tax_regime` — validated as a `Literal`, matching this module's own precedent
# (`revision_type`, `employment.status`) rather than a DB `CHECK` constraint.
TAX_REGIME_VALUES = ("OLD", "NEW")

TaxRegime = Literal["OLD", "NEW"]


class StatutoryCreate(BaseModel):
    """Creates a new effective-dated statutory row — closes the employee's current row (if
    any) and inserts a new one, mirroring `CompensationCreate` exactly: no field carries
    forward from the current row, `revision_reason` is required on every write (plan §16/§27
    item 7), including an employee's very first statutory row."""

    model_config = ConfigDict(extra="forbid")

    effective_from: date
    is_pf_applicable: bool
    pf_number: str | None = Field(default=None, max_length=30)
    pf_wage_ceiling_opt_out: bool = False
    vpf_amount: int | None = Field(default=None, ge=0)
    vpf_percentage: float | None = Field(default=None, ge=0)
    is_esi_applicable: bool
    esi_ip_number: str | None = Field(default=None, max_length=30)
    pt_state_code: str | None = Field(default=None, max_length=10)
    is_lwf_applicable: bool
    tax_regime: TaxRegime
    is_director: bool = False
    is_international_worker: bool = False
    revision_reason: str


class StatutoryRead(BaseModel):
    id: UUID
    company_id: UUID
    employee_id: UUID
    effective_from: date
    effective_to: date | None
    is_pf_applicable: bool
    pf_number: str | None
    pf_wage_ceiling_opt_out: bool
    vpf_amount: int | None
    vpf_percentage: float | None
    is_esi_applicable: bool
    esi_ip_number: str | None
    pt_state_code: str | None
    is_lwf_applicable: bool
    tax_regime: str | None
    is_director: bool
    is_international_worker: bool
    revision_reason: str | None
    version: int
    created_at: str
    updated_at: str


def statutory_to_read(statutory: "EmployeeStatutory") -> StatutoryRead:
    return StatutoryRead(
        id=statutory.id,
        company_id=statutory.company_id,
        employee_id=statutory.employee_id,
        effective_from=statutory.effective_from,
        effective_to=statutory.effective_to,
        is_pf_applicable=statutory.is_pf_applicable,
        pf_number=statutory.pf_number,
        pf_wage_ceiling_opt_out=statutory.pf_wage_ceiling_opt_out,
        vpf_amount=statutory.vpf_amount,
        vpf_percentage=(
            float(statutory.vpf_percentage) if statutory.vpf_percentage is not None else None
        ),
        is_esi_applicable=statutory.is_esi_applicable,
        esi_ip_number=statutory.esi_ip_number,
        pt_state_code=statutory.pt_state_code,
        is_lwf_applicable=statutory.is_lwf_applicable,
        tax_regime=statutory.tax_regime,
        is_director=statutory.is_director,
        is_international_worker=statutory.is_international_worker,
        revision_reason=statutory.revision_reason,
        version=statutory.version,
        created_at=_format_timestamp(statutory.created_at) or "",
        updated_at=_format_timestamp(statutory.updated_at) or "",
    )


def statutory_to_audit_dict(statutory: StatutoryRead) -> dict[str, Any]:
    return statutory.model_dump(mode="json")


# --- Employee Bank (E-08) -----------------------------------------------------------------
#
# The only four values `docs/product/08_Database_Architecture.md` §5.6 names for
# `payment_mode` — validated as a `Literal`, matching this module's own precedent
# (`tax_regime`, `revision_type`, `employment.status`) rather than a DB `CHECK` constraint.
PAYMENT_MODE_VALUES = ("BANK", "CASH", "CHEQUE", "UPI")

PaymentMode = Literal["BANK", "CASH", "CHEQUE", "UPI"]


class BankCreate(BaseModel):
    """Creates a new effective-dated bank row — closes the employee's current row (if any) and
    inserts a new one, mirroring `StatutoryCreate`'s write shape. Unlike Statutory, no
    `revision_reason` field — no source document requires one for Banking
    (`docs/modules/employee/33_EMPLOYEE_BANKING_IMPLEMENTATION_PLAN.md` §5/§13).
    `is_primary`/`verification_status`/`penny_drop_reference` are deliberately absent —
    system-managed, never client-writable (plan §13)."""

    model_config = ConfigDict(extra="forbid")

    effective_from: date
    account_holder_name: str | None = Field(default=None, max_length=150)
    account_number_enc: str | None = None
    bank_name: str | None = Field(default=None, max_length=150)
    ifsc: str | None = Field(default=None, max_length=15)
    branch_name: str | None = Field(default=None, max_length=150)
    payment_mode: PaymentMode


class BankRead(BaseModel):
    id: UUID
    company_id: UUID
    employee_id: UUID
    effective_from: date
    effective_to: date | None
    account_holder_name: str | None
    account_number_enc: str | None
    bank_name: str | None
    ifsc: str | None
    branch_name: str | None
    payment_mode: str | None
    is_primary: bool
    verification_status: str
    penny_drop_reference: str | None
    version: int
    created_at: str
    updated_at: str


def bank_to_read(bank: "EmployeeBank") -> BankRead:
    return BankRead(
        id=bank.id,
        company_id=bank.company_id,
        employee_id=bank.employee_id,
        effective_from=bank.effective_from,
        effective_to=bank.effective_to,
        account_holder_name=bank.account_holder_name,
        account_number_enc=bank.account_number_enc,
        bank_name=bank.bank_name,
        ifsc=bank.ifsc,
        branch_name=bank.branch_name,
        payment_mode=bank.payment_mode,
        is_primary=bank.is_primary,
        verification_status=bank.verification_status,
        penny_drop_reference=bank.penny_drop_reference,
        version=bank.version,
        created_at=_format_timestamp(bank.created_at) or "",
        updated_at=_format_timestamp(bank.updated_at) or "",
    )


def bank_to_audit_dict(bank: BankRead) -> dict[str, Any]:
    return bank.model_dump(mode="json")
