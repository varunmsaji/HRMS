"""Pydantic request/response schemas for the employee module — E-01 (identity foundation) only.

Fields deliberately excluded from `EmployeeCreate`/`EmployeeUpdate`, and why:
- `employee_code`: system-generated via the `number_series` allocator, never client-settable.
- `status`: system-managed via lifecycle actions (FR-EMP-014); no transition exists in this
  slice, so it is set once at creation (`PRE_JOINING`) and never exposed as writable.
- `display_name`: derived, not directly editable.
- `pan_number_enc` / `aadhaar_number_enc` / `uan_number`: gated by `EMPLOYEE.UPDATE_SENSITIVE`/
  `.VIEW_SENSITIVE` via the dedicated `EmployeeIdentityUpdate`/`EmployeeIdentityRead` schemas
  below (market-parity onboarding-data pass, "E-02") — deliberately kept off the general
  `EmployeeCreate`/`EmployeeUpdate`/`EmployeeRead` surface so a caller holding only
  `EMPLOYEE.UPDATE` can never read or write them through the basic-details endpoint.
- `user_id`: system-managed (login provisioning), not client-settable.
"""

import json
import re
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)

from hrms.core.audit.redact import SENSITIVE_FIELD_MASKS, mask_sensitive
from hrms.shared.limits import MAX_CUSTOM_FIELDS_BYTES, MAX_MONEY_MINOR

if TYPE_CHECKING:
    from hrms.modules.employee.models import (
        Employee,
        EmployeeAssignment,
        EmployeeBank,
        EmployeeCompensation,
        EmployeeDependent,
        EmployeeDocument,
        EmployeeEducation,
        EmployeeExperience,
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


_EMAIL = TypeAdapter(EmailStr)
_PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
_IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
_EARLIEST_DOB = date(1900, 1, 1)

#: Deliberately permissive shapes: they reject obvious garbage ("abc", "zz", "1!") without
#: refusing legitimate international numbers, extensions or non-Indian postcodes.
Mobile = Annotated[str, Field(max_length=20, pattern=r"^\+?[0-9][0-9 ()\-]{5,18}[0-9]$")]
Pincode = Annotated[
    str, Field(max_length=10, pattern=r"^[A-Za-z0-9][A-Za-z0-9 \-]{1,8}[A-Za-z0-9]$")
]
CountryCode = Annotated[str, Field(min_length=2, max_length=2, pattern=r"^[A-Za-z]{2}$")]


def _validate_personal_email(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        _EMAIL.validate_python(value)
    except ValueError as exc:
        raise ValueError("personal_email must be a valid email address") from exc
    return value


def _validate_name(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        raise ValueError("must not be blank")
    return stripped


def _validate_dob(value: date | None) -> date | None:
    if value is not None and not (_EARLIEST_DOB <= value <= date.today()):
        raise ValueError("date_of_birth must be between 1900-01-01 and today")
    return value


def _validate_custom_fields(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is not None and len(json.dumps(value, default=str)) > MAX_CUSTOM_FIELDS_BYTES:
        raise ValueError(f"custom_fields must serialise to at most {MAX_CUSTOM_FIELDS_BYTES} bytes")
    return value


class _EmployeeFieldRules(BaseModel):
    """Format rules common to `EmployeeCreate` and `EmployeeUpdate`."""

    @field_validator("first_name", check_fields=False)
    @classmethod
    def _first_name_not_blank(cls, v: str | None) -> str | None:
        return _validate_name(v)

    @field_validator("personal_email", check_fields=False)
    @classmethod
    def _email_format(cls, v: str | None) -> str | None:
        return _validate_personal_email(v)

    @field_validator("date_of_birth", check_fields=False)
    @classmethod
    def _dob_range(cls, v: date | None) -> date | None:
        return _validate_dob(v)

    @field_validator("custom_fields", check_fields=False)
    @classmethod
    def _custom_fields_size(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        return _validate_custom_fields(v)


class EmployeeCreate(_EmployeeFieldRules):
    model_config = ConfigDict(extra="forbid")

    first_name: str = Field(min_length=1, max_length=100)
    middle_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    date_of_birth: date | None = None
    gender: str | None = Field(default=None, max_length=20)
    blood_group: str | None = Field(default=None, max_length=10)
    marital_status: str | None = Field(default=None, max_length=20)
    nationality: str | None = Field(default=None, max_length=80)
    father_or_husband_name: str | None = Field(default=None, max_length=150)
    personal_email: str | None = Field(default=None, max_length=255)
    personal_mobile: Mobile | None = None
    present_address_line1: str | None = Field(default=None, max_length=200)
    present_address_line2: str | None = Field(default=None, max_length=200)
    present_city: str | None = Field(default=None, max_length=100)
    present_state_code: str | None = Field(default=None, max_length=10)
    present_pincode: Pincode | None = None
    present_country_code: CountryCode | None = None
    permanent_address_line1: str | None = Field(default=None, max_length=200)
    permanent_address_line2: str | None = Field(default=None, max_length=200)
    permanent_city: str | None = Field(default=None, max_length=100)
    permanent_state_code: str | None = Field(default=None, max_length=10)
    permanent_pincode: Pincode | None = None
    permanent_country_code: CountryCode | None = None
    permanent_same_as_present: bool = True
    emergency_contact_name: str | None = Field(default=None, max_length=150)
    emergency_contact_relationship: str | None = Field(default=None, max_length=50)
    emergency_contact_phone: Mobile | None = None
    photo_url: str | None = None
    custom_fields: dict[str, Any] | None = None


class EmployeeUpdate(_EmployeeFieldRules):
    model_config = ConfigDict(extra="forbid")

    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    middle_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    date_of_birth: date | None = None
    gender: str | None = Field(default=None, max_length=20)
    blood_group: str | None = Field(default=None, max_length=10)
    marital_status: str | None = Field(default=None, max_length=20)
    nationality: str | None = Field(default=None, max_length=80)
    father_or_husband_name: str | None = Field(default=None, max_length=150)
    personal_email: str | None = Field(default=None, max_length=255)
    personal_mobile: Mobile | None = None
    present_address_line1: str | None = Field(default=None, max_length=200)
    present_address_line2: str | None = Field(default=None, max_length=200)
    present_city: str | None = Field(default=None, max_length=100)
    present_state_code: str | None = Field(default=None, max_length=10)
    present_pincode: Pincode | None = None
    present_country_code: CountryCode | None = None
    permanent_address_line1: str | None = Field(default=None, max_length=200)
    permanent_address_line2: str | None = Field(default=None, max_length=200)
    permanent_city: str | None = Field(default=None, max_length=100)
    permanent_state_code: str | None = Field(default=None, max_length=10)
    permanent_pincode: Pincode | None = None
    permanent_country_code: CountryCode | None = None
    permanent_same_as_present: bool | None = None
    emergency_contact_name: str | None = Field(default=None, max_length=150)
    emergency_contact_relationship: str | None = Field(default=None, max_length=50)
    emergency_contact_phone: Mobile | None = None
    photo_url: str | None = None
    custom_fields: dict[str, Any] | None = None
    is_active: bool | None = None


class EmployeeConfirmInput(BaseModel):
    """`POST /employees/{id}/confirm` — transitions `PROBATION` -> `ACTIVE`. No fields: unlike
    `EmploymentTerminate` (which needs `last_working_day`), confirmation needs no input at all —
    the before/after `Employee.status` values in the audit record are the entire story. Kept as
    an explicit (empty) body model rather than no body, matching every other action in this
    router."""

    model_config = ConfigDict(extra="forbid")


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
    father_or_husband_name: str | None
    personal_email: str | None
    personal_mobile: str | None
    present_address_line1: str | None
    present_address_line2: str | None
    present_city: str | None
    present_state_code: str | None
    present_pincode: str | None
    present_country_code: str | None
    permanent_address_line1: str | None
    permanent_address_line2: str | None
    permanent_city: str | None
    permanent_state_code: str | None
    permanent_pincode: str | None
    permanent_country_code: str | None
    permanent_same_as_present: bool
    emergency_contact_name: str | None
    emergency_contact_relationship: str | None
    emergency_contact_phone: str | None
    photo_url: str | None
    status: str
    custom_fields: dict[str, Any] | None
    is_active: bool
    version: int
    created_at: str
    updated_at: str
    # F-1 remediation (docs/audits/ATTENDANCE_DASHBOARD_F1_REMEDIATION_REPORT.md) — the employee's
    # *current/most-recent* `Employment` spell boundaries, surfaced here so a bulk caller (the
    # Attendance dashboard's employee directory) can tell "currently employed" from "no record
    # yet" without an N+1 fetch per employee. Deliberately **not** full employment data (pay
    # basis, legal entity, etc. stay on `EmploymentRead` only, via `GET /employees/{id}/
    # employments`) — just the two date boundaries `joining_date <= date <= (last_working_day or
    # infinity)` already used everywhere else in the codebase (e.g.
    # `attendance/service.py::_is_employed_on`) to decide employment coverage for a date.
    # `None` when the employee has no employment row yet (e.g. still `PRE_JOINING`), or when the
    # caller path doesn't compute it (only `GET /employees` — the bulk list — populates these;
    # `GET /employees/{id}` and all write-path responses leave them `None`, unchanged from before
    # this field existed).
    employment_joining_date: date | None = None
    employment_last_working_day: date | None = None


def _format_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


def employee_to_read(employee: "Employee", employment: "Employment | None" = None) -> EmployeeRead:
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
        father_or_husband_name=employee.father_or_husband_name,
        personal_email=employee.personal_email,
        personal_mobile=employee.personal_mobile,
        present_address_line1=employee.present_address_line1,
        present_address_line2=employee.present_address_line2,
        present_city=employee.present_city,
        present_state_code=employee.present_state_code,
        present_pincode=employee.present_pincode,
        present_country_code=employee.present_country_code,
        permanent_address_line1=employee.permanent_address_line1,
        permanent_address_line2=employee.permanent_address_line2,
        permanent_city=employee.permanent_city,
        permanent_state_code=employee.permanent_state_code,
        permanent_pincode=employee.permanent_pincode,
        permanent_country_code=employee.permanent_country_code,
        permanent_same_as_present=employee.permanent_same_as_present,
        emergency_contact_name=employee.emergency_contact_name,
        emergency_contact_relationship=employee.emergency_contact_relationship,
        emergency_contact_phone=employee.emergency_contact_phone,
        photo_url=employee.photo_url,
        status=employee.status,
        custom_fields=employee.custom_fields,
        is_active=employee.is_active,
        version=employee.version,
        created_at=_format_timestamp(employee.created_at) or "",
        updated_at=_format_timestamp(employee.updated_at) or "",
        employment_joining_date=employment.joining_date if employment else None,
        employment_last_working_day=employment.last_working_day if employment else None,
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


#: BUS-001 — see `Employment.pay_basis`.
PayBasis = Literal["MONTHLY", "DAILY_WAGE"]


class EmploymentCreate(BaseModel):
    """Creates a new employment episode for an existing employee — covers both a first hire
    (no prior employment rows) and a rehire (at least one prior, necessarily `TERMINATED`,
    episode exists). The distinction is not client-supplied: `previous_employment_id` is
    always computed server-side from the employee's own employment history, never accepted as
    input (`status`/`version` are likewise system-set, never client-settable).

    `probation_end_date` is optional and purely informational — nothing reads or auto-computes
    it; the actual `PROBATION` -> `ACTIVE` transition is the explicit `confirm` action, never
    gated by this date."""

    model_config = ConfigDict(extra="forbid")

    legal_entity_id: UUID
    joining_date: date
    probation_end_date: date | None = None
    pay_basis: PayBasis = "MONTHLY"

    @model_validator(mode="after")
    def _dates_are_sane(self) -> "EmploymentCreate":
        if not (date(1950, 1, 1) <= self.joining_date <= date.today() + timedelta(days=3650)):
            raise ValueError("joining_date is outside the supported range")
        if self.probation_end_date is not None and self.probation_end_date < self.joining_date:
            raise ValueError("probation_end_date cannot be before joining_date")
        return self


class EmploymentUpdate(BaseModel):
    """Only `legal_entity_id` and `probation_end_date` are correctable post-creation.
    `joining_date` is a historical fact once recorded (no document states it is ever
    legitimately revised, and every other slice in this codebase treats a spell's start as
    immutable); `status`/`last_working_day` only ever change via the dedicated `terminate`
    action, never a generic field patch — this keeps the one-way `ACTIVE` → `TERMINATED`
    transition from being reachable through an unvalidated arbitrary-field update.
    `probation_end_date` is the one exception to "immutable once set": it's purely
    informational bookkeeping, not a fact anything downstream depends on, so HR correcting it
    carries none of `joining_date`'s risk."""

    model_config = ConfigDict(extra="forbid")

    legal_entity_id: UUID | None = None
    probation_end_date: date | None = None
    # Correctable: a wrong pay basis is a data-entry error. Unlocked attendance days pick the new
    # value up on their next recompute; days in a closed period keep the value they were
    # computed with.
    pay_basis: PayBasis | None = None

    @model_validator(mode="after")
    def pay_basis_not_null(self) -> "EmploymentUpdate":
        if "pay_basis" in self.model_fields_set and self.pay_basis is None:
            raise ValueError("pay_basis cannot be null")
        return self


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
    probation_end_date: date | None
    pay_basis: str
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
        probation_end_date=employment.probation_end_date,
        pay_basis=employment.pay_basis,
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
    annual_ctc_minor: int = Field(gt=0, le=MAX_MONEY_MINOR)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    revision_type: RevisionType
    revision_reason: str = Field(min_length=1, max_length=1000)


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
    vpf_amount: int | None = Field(default=None, ge=0, le=MAX_MONEY_MINOR)
    vpf_percentage: float | None = Field(default=None, ge=0, le=100)
    is_esi_applicable: bool
    esi_ip_number: str | None = Field(default=None, max_length=30)
    pt_state_code: str | None = Field(default=None, max_length=10)
    is_lwf_applicable: bool
    tax_regime: TaxRegime
    is_director: bool = False
    is_international_worker: bool = False
    revision_reason: str = Field(min_length=1, max_length=1000)


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

    @field_validator("ifsc")
    @classmethod
    def _ifsc_format(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().upper()
        if not _IFSC_RE.match(v):
            raise ValueError("ifsc must look like HDFC0001234 (4 letters, 0, 6 alphanumerics)")
        return v

    @field_validator("account_number_enc")
    @classmethod
    def _account_number_format(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not re.fullmatch(r"[A-Za-z0-9]{5,34}", v):
            raise ValueError("account number must be 5-34 letters/digits, no spaces or symbols")
        return v


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


def bank_to_read(bank: "EmployeeBank", *, decrypted_account_number: str | None) -> BankRead:
    """DATA-01 (`docs/audits/DATA_01_PII_ENCRYPTION_IMPLEMENTATION_PLAN.md` §2.5) — `bank.
    account_number_enc` now holds ciphertext (the ORM attribute is never auto-decrypted, plan
    §2.5's corrected encryption boundary). `decrypted_account_number` is a required keyword — not
    defaulted — so a call site cannot forget it and silently return ciphertext where the API
    contract expects the plaintext account number; the caller (`EmployeeBankService`, after its
    own permission check has already run) is the only place authorized to have called
    `PiiCryptoService.decrypt_column` to produce it."""
    return BankRead(
        id=bank.id,
        company_id=bank.company_id,
        employee_id=bank.employee_id,
        effective_from=bank.effective_from,
        effective_to=bank.effective_to,
        account_holder_name=bank.account_holder_name,
        account_number_enc=decrypted_account_number,
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
    """DATA-01 §7 (mandatory) — `bank` here already carries the *decrypted* account number
    (`bank_to_read`'s new contract, above), so without this masking step the plaintext would flow
    straight into the immutable `audit_log` table. `mask_sensitive` replaces it with the
    documented last-four-digit form (`"******7890"`) before this dict ever reaches
    `AuditService.record()` — never the plaintext, and never the raw ciphertext blob either."""
    return mask_sensitive(bank.model_dump(mode="json"), sensitive_fields=SENSITIVE_FIELD_MASKS)


# --- Employee Identity (E-02) --------------------------------------------------------------
#
# The write path the module docstring's exclusion note and `EMPLOYEE.UPDATE_SENSITIVE`'s own
# description ("Edit PAN/Aadhaar/bank/statutory") already anticipated — `pan_number_enc`/
# `aadhaar_number_enc`/`uan_number` finally get a schema + service + route. Unlike Bank/
# Statutory/Compensation, this is not an effective-dated history table — PAN/Aadhaar/UAN are
# single current-value facts on `Employee` itself (like `gender`/`blood_group`), so this is a
# plain update-in-place, not an insert-a-new-row-and-close-the-old-one write.


class EmployeeIdentityUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pan_number: str | None = Field(default=None, min_length=10, max_length=10)
    aadhaar_number: str | None = Field(default=None, min_length=12, max_length=12)
    uan_number: str | None = Field(default=None, max_length=20)
    father_or_husband_name: str | None = Field(default=None, max_length=150)

    @field_validator("pan_number")
    @classmethod
    def _pan_format(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().upper()
        if not _PAN_RE.match(v):
            raise ValueError("PAN must look like ABCDE1234F")
        return v

    @field_validator("aadhaar_number")
    @classmethod
    def _aadhaar_format(cls, v: str | None) -> str | None:
        if v is not None and not re.fullmatch(r"[0-9]{12}", v):
            raise ValueError("Aadhaar number must be exactly 12 digits")
        return v

    @field_validator("uan_number")
    @classmethod
    def _uan_format(cls, v: str | None) -> str | None:
        if v is not None and not re.fullmatch(r"[0-9]{12}", v):
            raise ValueError("UAN must be exactly 12 digits")
        return v


class EmployeeIdentityRead(BaseModel):
    employee_id: UUID
    pan_number: str | None
    aadhaar_number: str | None
    uan_number: str | None
    father_or_husband_name: str | None
    version: int


def employee_identity_to_read(
    employee: "Employee", *, pan_number: str | None, aadhaar_number: str | None
) -> EmployeeIdentityRead:
    """`pan_number`/`aadhaar_number` are required keywords, not read off `employee.
    pan_number_enc`/`.aadhaar_number_enc` directly — those ORM attributes hold ciphertext only
    (mirrors `bank_to_read`'s exact contract). The caller (`EmployeeService.get_identity`), after
    its own permission check, is the only place authorized to have called
    `PiiCryptoService.decrypt_column(...)` to produce these plaintext values."""
    return EmployeeIdentityRead(
        employee_id=employee.id,
        pan_number=pan_number,
        aadhaar_number=aadhaar_number,
        uan_number=employee.uan_number,
        father_or_husband_name=employee.father_or_husband_name,
        version=employee.version,
    )


def employee_identity_to_audit_dict(identity: EmployeeIdentityRead) -> dict[str, Any]:
    """DATA-01 §7 (mandatory) — same masking contract as `bank_to_audit_dict`. `identity` here
    carries plaintext `pan_number`/`aadhaar_number`; `SENSITIVE_FIELD_MASKS` is keyed by the
    `_enc` column-name convention, so the dict is aliased onto those keys before masking and
    aliased back afterward — this dict's own field names (`pan_number`, not `pan_number_enc`)
    stay in the audit record, only their values change."""
    payload = identity.model_dump(mode="json")
    aliased = {
        **payload,
        "pan_number_enc": payload["pan_number"],
        "aadhaar_number_enc": payload["aadhaar_number"],
    }
    masked = mask_sensitive(aliased, sensitive_fields=SENSITIVE_FIELD_MASKS)
    payload["pan_number"] = masked["pan_number_enc"]
    payload["aadhaar_number"] = masked["aadhaar_number_enc"]
    return payload


# --- Employee Experience (market-parity onboarding-data pass, part 4) -----------------------
#
# Previous employment / PF continuity — a genuine one-to-many list (multiple past employers,
# all concurrently valid), not an effective-dated history table like Statutory/Bank/
# Compensation. `create_experience` inserts a new independent row every time; there is no
# "close the current row" step because rows never supersede each other.


class EmployeeExperienceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_name: str = Field(min_length=1, max_length=200)
    designation: str | None = Field(default=None, max_length=150)
    from_date: date
    to_date: date | None = None
    last_ctc_minor: int | None = Field(default=None, ge=0, le=MAX_MONEY_MINOR)
    reason_for_leaving: str | None = None
    had_prior_pf_membership: bool = False
    previous_uan: str | None = Field(default=None, max_length=20)
    previous_pf_account_number: str | None = Field(default=None, max_length=30)
    previous_esi_ip_number: str | None = Field(default=None, max_length=30)
    document_id: UUID | None = None


class EmployeeExperienceRead(BaseModel):
    id: UUID
    company_id: UUID
    employee_id: UUID
    company_name: str
    designation: str | None
    from_date: date
    to_date: date | None
    last_ctc_minor: int | None
    reason_for_leaving: str | None
    had_prior_pf_membership: bool
    previous_uan: str | None
    previous_pf_account_number: str | None
    previous_esi_ip_number: str | None
    document_id: UUID | None
    version: int
    created_at: str
    updated_at: str


def employee_experience_to_read(experience: "EmployeeExperience") -> EmployeeExperienceRead:
    return EmployeeExperienceRead(
        id=experience.id,
        company_id=experience.company_id,
        employee_id=experience.employee_id,
        company_name=experience.company_name,
        designation=experience.designation,
        from_date=experience.from_date,
        to_date=experience.to_date,
        last_ctc_minor=experience.last_ctc_minor,
        reason_for_leaving=experience.reason_for_leaving,
        had_prior_pf_membership=experience.had_prior_pf_membership,
        previous_uan=experience.previous_uan,
        previous_pf_account_number=experience.previous_pf_account_number,
        previous_esi_ip_number=experience.previous_esi_ip_number,
        document_id=experience.document_id,
        version=experience.version,
        created_at=_format_timestamp(experience.created_at) or "",
        updated_at=_format_timestamp(experience.updated_at) or "",
    )


def employee_experience_to_audit_dict(experience: EmployeeExperienceRead) -> dict[str, Any]:
    return experience.model_dump(mode="json")


# --- Employee Education (market-parity onboarding-data pass, part 5) ------------------------
#
# Same "plain list" shape as Experience above — a candidate may hold multiple qualifications,
# all concurrently valid, not effective-dated history.


class EmployeeEducationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    qualification: str = Field(min_length=1, max_length=150)
    institution_name: str | None = Field(default=None, max_length=200)
    year_of_passing: int | None = Field(default=None, ge=1950, le=2100)
    document_id: UUID | None = None


class EmployeeEducationRead(BaseModel):
    id: UUID
    company_id: UUID
    employee_id: UUID
    qualification: str
    institution_name: str | None
    year_of_passing: int | None
    document_id: UUID | None
    version: int
    created_at: str
    updated_at: str


def employee_education_to_read(education: "EmployeeEducation") -> EmployeeEducationRead:
    return EmployeeEducationRead(
        id=education.id,
        company_id=education.company_id,
        employee_id=education.employee_id,
        qualification=education.qualification,
        institution_name=education.institution_name,
        year_of_passing=education.year_of_passing,
        document_id=education.document_id,
        version=education.version,
        created_at=_format_timestamp(education.created_at) or "",
        updated_at=_format_timestamp(education.updated_at) or "",
    )


def employee_education_to_audit_dict(education: EmployeeEducationRead) -> dict[str, Any]:
    return education.model_dump(mode="json")


# --- Employee Dependent (market-parity onboarding-data pass, part 6) ------------------------
#
# PF/Gratuity nominee declaration + ESI family details (EPF Form 2, Gratuity Form F, ESI Form
# 1/Form 2). Same "plain list" shape as Experience/Education above, plus a DATA-01-encrypted
# `aadhaar_number_enc` (same request-field-name-holds-plaintext convention `EmployeeIdentityUpdate`/
# `BankCreate` already use) and a minor/guardian conditional block.


class EmployeeDependentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=1, max_length=150)
    relationship: str = Field(min_length=1, max_length=50)
    date_of_birth: date | None = None
    gender: str | None = Field(default=None, max_length=20)
    is_minor: bool = False
    guardian_name: str | None = Field(default=None, max_length=150)
    guardian_relationship: str | None = Field(default=None, max_length=50)
    aadhaar_number_enc: str | None = Field(default=None, min_length=12, max_length=12)
    is_pf_nominee: bool = False
    pf_nominee_share_percentage: float | None = Field(default=None, gt=0, le=100)
    is_gratuity_nominee: bool = False
    gratuity_nominee_share_percentage: float | None = Field(default=None, gt=0, le=100)
    is_esi_dependent: bool = False
    document_id: UUID | None = None

    @model_validator(mode="after")
    def _require_guardian_when_minor(self) -> "EmployeeDependentCreate":
        if self.is_minor and not (self.guardian_name or "").strip():
            raise ValueError("guardian_name is required when is_minor is true")
        return self

    @model_validator(mode="after")
    def _require_percentage_when_nominee(self) -> "EmployeeDependentCreate":
        if self.is_pf_nominee and self.pf_nominee_share_percentage is None:
            raise ValueError("pf_nominee_share_percentage is required when is_pf_nominee is true")
        if self.is_gratuity_nominee and self.gratuity_nominee_share_percentage is None:
            raise ValueError(
                "gratuity_nominee_share_percentage is required when is_gratuity_nominee is true"
            )
        return self


class EmployeeDependentRead(BaseModel):
    id: UUID
    company_id: UUID
    employee_id: UUID
    full_name: str
    relationship: str
    date_of_birth: date | None
    gender: str | None
    is_minor: bool
    guardian_name: str | None
    guardian_relationship: str | None
    aadhaar_number_enc: str | None
    is_pf_nominee: bool
    pf_nominee_share_percentage: float | None
    is_gratuity_nominee: bool
    gratuity_nominee_share_percentage: float | None
    is_esi_dependent: bool
    document_id: UUID | None
    version: int
    created_at: str
    updated_at: str


def employee_dependent_to_read(
    dependent: "EmployeeDependent", *, decrypted_aadhaar_number: str | None
) -> EmployeeDependentRead:
    """DATA-01 — `decrypted_aadhaar_number` is a required keyword, not read off `dependent.
    aadhaar_number_enc` directly, mirroring `bank_to_read`'s exact contract: the caller
    (`EmployeeDependentService`), after its own permission check, is the only place authorized to
    have called `PiiCryptoService.decrypt_column(...)` to produce it."""
    return EmployeeDependentRead(
        id=dependent.id,
        company_id=dependent.company_id,
        employee_id=dependent.employee_id,
        full_name=dependent.full_name,
        relationship=dependent.relationship,
        date_of_birth=dependent.date_of_birth,
        gender=dependent.gender,
        is_minor=dependent.is_minor,
        guardian_name=dependent.guardian_name,
        guardian_relationship=dependent.guardian_relationship,
        aadhaar_number_enc=decrypted_aadhaar_number,
        is_pf_nominee=dependent.is_pf_nominee,
        pf_nominee_share_percentage=(
            float(dependent.pf_nominee_share_percentage)
            if dependent.pf_nominee_share_percentage is not None
            else None
        ),
        is_gratuity_nominee=dependent.is_gratuity_nominee,
        gratuity_nominee_share_percentage=(
            float(dependent.gratuity_nominee_share_percentage)
            if dependent.gratuity_nominee_share_percentage is not None
            else None
        ),
        is_esi_dependent=dependent.is_esi_dependent,
        document_id=dependent.document_id,
        version=dependent.version,
        created_at=_format_timestamp(dependent.created_at) or "",
        updated_at=_format_timestamp(dependent.updated_at) or "",
    )


def employee_dependent_to_audit_dict(dependent: EmployeeDependentRead) -> dict[str, Any]:
    """DATA-01 §7 (mandatory) — `dependent` here carries the plaintext `aadhaar_number_enc`;
    `SENSITIVE_FIELD_MASKS` is keyed by field name (not table), so it already covers this field
    with no registry change needed (`redact.py` module docstring's own point)."""
    return mask_sensitive(dependent.model_dump(mode="json"), sensitive_fields=SENSITIVE_FIELD_MASKS)


# --- Employee Document (post-onboarding document management) --------------------------------
#
# An employee's ongoing document store, independent of onboarding (which has its own, separate
# `OnboardingDocument`/`ONBOARDING_DOCUMENT_TYPES` in `hrms.modules.onboarding.schemas`). The
# type list below is the same literal set as `ONBOARDING_DOCUMENT_TYPES` — re-declared locally
# rather than imported, so this module's public contract doesn't depend on onboarding's schema
# module (the only existing cross-module dependency between these two modules runs the other
# way: onboarding composes the employee module's services at activation, never the reverse).

EMPLOYEE_DOCUMENT_TYPES = (
    "PHOTO",
    "PAN",
    "AADHAAR",
    "ADDRESS_PROOF",
    "EDUCATION_CERTIFICATE",
    "PREVIOUS_EMPLOYMENT_PROOF",
    "BANK_PROOF",
    "OTHER",
)

# Same cap as `ONBOARDING_DOCUMENT_MAX_SIZE_BYTES` — this task's own engineering decision, no
# source document names a number for this sub-resource either.
EMPLOYEE_DOCUMENT_MAX_SIZE_BYTES = 10 * 1024 * 1024

EMPLOYEE_DOCUMENT_STATUS_VALUES = ("PENDING", "VERIFIED", "REJECTED")


class EmployeeDocumentRead(BaseModel):
    """Deliberately excludes `s3_key`/`source_onboarding_document_id` — internal storage/
    provenance details, never returned to a caller."""

    id: UUID
    employee_id: UUID
    document_type: str
    original_filename: str
    content_type: str
    size_bytes: int
    status: str
    verified_by_user_id: UUID | None
    verified_at: str | None
    rejection_reason: str | None
    uploaded_at: str


class EmployeeDocumentWithUrlRead(EmployeeDocumentRead):
    """Adds the short-lived presigned GET URL — document bytes never round-trip through the API
    server. Returned to every caller who can list documents at all (HR/Admin and the SELF-scoped
    employee alike): unlike onboarding's candidate-facing `list_documents` (no URL, because an
    unreviewed candidate upload might still be replaced), every viewer here is already permitted
    to download what they can see."""

    download_url: str


class EmployeeDocumentReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["VERIFIED", "REJECTED"]
    rejection_reason: str | None = None

    @model_validator(mode="after")
    def _require_reason_when_rejected(self) -> "EmployeeDocumentReviewRequest":
        if self.status == "REJECTED" and not (self.rejection_reason or "").strip():
            raise ValueError("rejection_reason is required when status is REJECTED")
        return self


def employee_document_to_read(document: "EmployeeDocument") -> EmployeeDocumentRead:
    return EmployeeDocumentRead(
        id=document.id,
        employee_id=document.employee_id,
        document_type=document.document_type,
        original_filename=document.original_filename,
        content_type=document.content_type,
        size_bytes=document.size_bytes,
        status=document.status,
        verified_by_user_id=document.verified_by_user_id,
        verified_at=_format_timestamp(document.verified_at),
        rejection_reason=document.rejection_reason,
        uploaded_at=_format_timestamp(document.uploaded_at) or "",
    )


def employee_document_to_read_with_url(
    document: "EmployeeDocument", download_url: str
) -> EmployeeDocumentWithUrlRead:
    base = employee_document_to_read(document)
    return EmployeeDocumentWithUrlRead(**base.model_dump(), download_url=download_url)


def employee_document_to_audit_dict(document: EmployeeDocumentRead) -> dict[str, Any]:
    return document.model_dump(mode="json")
