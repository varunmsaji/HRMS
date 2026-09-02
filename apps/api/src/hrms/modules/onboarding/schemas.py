"""Pydantic request/response schemas for the onboarding module — O1 (case create/list/detail)
and O2 (token issuance + public section read/write).

O2 section schemas (`PersonalInfoSection`/`BankInfoSection`/`StatutoryInfoSection`) are each a
strict field subset of the matching `EmployeeCreate`/`BankCreate`/`StatutoryCreate`
(`hrms.modules.employee.schemas`) — same field names/types/constraints, per plan §7.2/§8.2 —
minus fields that are either owned by the case record itself (`personal_email`/
`personal_mobile`, set by HR at case creation, not re-collected here) or computed at activation
(`effective_from`, derived from `proposed_joining_date`, and `revision_reason`, meaningless for
an initial submission).

`AddressInfoSection`/`EmergencyContactSection` have no existing employee-module schema to mirror
— `Employee` has no home-address or emergency-contact columns anywhere in this codebase today.
These two are therefore this task's own minimal schema, not derived from a locked source; they
have no activation-time consumer yet (§8.6/O7 only writes Employee/Employment/Assignment/
Compensation/Statutory/Bank) — flagged here as a known gap, not a silent one."""

from datetime import date, datetime
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

if TYPE_CHECKING:
    from hrms.modules.onboarding.models import OnboardingCase

# `docs/modules/onboarding/01_ONBOARDING_MODULE_PLAN.md` §6 — the full state machine. Not
# client-writable; exposed here only so `OnboardingCaseRead.status` and tests have one source of
# truth, mirroring `employee.schemas.EMPLOYEE_STATUS_VALUES`'s own convention.
ONBOARDING_CASE_STATUS_VALUES = (
    "DRAFT",
    "INVITED",
    "IN_PROGRESS",
    "SUBMITTED",
    "UNDER_REVIEW",
    "CHANGES_REQUESTED",
    "VERIFIED",
    "ACTIVATED",
    "EXPIRED",
    "CANCELLED",
)

ONBOARDING_CASE_TERMINAL_STATUSES = ("ACTIVATED", "EXPIRED", "CANCELLED")

# Statuses in which the candidate-facing sections are open for editing (state machine §6):
# `INVITED`/`IN_PROGRESS` (first pass), `CHANGES_REQUESTED` (HR reopened it after a rejection —
# O6 hasn't landed yet so nothing currently drives a case into this status, but the check is
# correct in advance rather than needing revisiting when O6 lands).
ONBOARDING_CASE_WRITABLE_STATUSES = ("INVITED", "IN_PROGRESS", "CHANGES_REQUESTED")

ONBOARDING_SECTION_NAMES = (
    "personal_info",
    "address_info",
    "emergency_contact",
    "bank_info",
    "statutory_info",
)


class OnboardingCaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_first_name: str = Field(min_length=1, max_length=100)
    candidate_last_name: str | None = Field(default=None, max_length=100)
    personal_email: EmailStr
    personal_mobile: str | None = Field(default=None, max_length=20)
    designation_id: UUID | None = None
    department_id: UUID | None = None
    branch_id: UUID | None = None
    legal_entity_id: UUID | None = None
    proposed_joining_date: date


class OnboardingCaseRead(BaseModel):
    id: UUID
    company_id: UUID
    status: str
    candidate_first_name: str
    candidate_last_name: str | None
    personal_email: str
    personal_mobile: str | None
    designation_id: UUID | None
    department_id: UUID | None
    branch_id: UUID | None
    legal_entity_id: UUID | None
    proposed_joining_date: date
    created_by_user_id: UUID
    employee_id: UUID | None
    version: int
    created_at: str
    updated_at: str


def _format_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


def onboarding_case_to_read(case: "OnboardingCase") -> OnboardingCaseRead:
    return OnboardingCaseRead(
        id=case.id,
        company_id=case.company_id,
        status=case.status,
        candidate_first_name=case.candidate_first_name,
        candidate_last_name=case.candidate_last_name,
        personal_email=case.personal_email,
        personal_mobile=case.personal_mobile,
        designation_id=case.designation_id,
        department_id=case.department_id,
        branch_id=case.branch_id,
        legal_entity_id=case.legal_entity_id,
        proposed_joining_date=case.proposed_joining_date,
        created_by_user_id=case.created_by_user_id,
        employee_id=case.employee_id,
        version=case.version,
        created_at=_format_timestamp(case.created_at) or "",
        updated_at=_format_timestamp(case.updated_at) or "",
    )


def onboarding_case_to_audit_dict(read: OnboardingCaseRead) -> dict[str, object]:
    return read.model_dump(mode="json")


# --- O2: public section schemas --------------------------------------------------------------

TaxRegime = Literal["OLD", "NEW"]
PaymentMode = Literal["BANK", "CASH", "CHEQUE", "UPI"]


class PersonalInfoSection(BaseModel):
    """Subset of `EmployeeCreate` — excludes `personal_email`/`personal_mobile` (owned by the
    case record, set by HR at creation) and `custom_fields` (internal, not candidate-facing)."""

    model_config = ConfigDict(extra="forbid")

    first_name: str = Field(min_length=1, max_length=100)
    middle_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    date_of_birth: date | None = None
    gender: str | None = Field(default=None, max_length=20)
    blood_group: str | None = Field(default=None, max_length=10)
    marital_status: str | None = Field(default=None, max_length=20)
    nationality: str | None = Field(default=None, max_length=80)
    photo_url: str | None = None


class AddressInfoSection(BaseModel):
    """No `EmployeeCreate`-equivalent exists (module docstring) — this task's own minimal shape,
    mirroring `organisation.Branch`'s own address field names for consistency."""

    model_config = ConfigDict(extra="forbid")

    address_line1: str | None = Field(default=None, max_length=200)
    address_line2: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=100)
    state_code: str | None = Field(default=None, max_length=10)
    pincode: str | None = Field(default=None, max_length=10)
    country_code: str | None = Field(default=None, max_length=2)


class EmergencyContactSection(BaseModel):
    """No `EmployeeCreate`-equivalent exists (module docstring) — this task's own minimal
    shape."""

    model_config = ConfigDict(extra="forbid")

    contact_name: str = Field(min_length=1, max_length=150)
    relationship: str | None = Field(default=None, max_length=50)
    phone: str = Field(min_length=1, max_length=20)


class BankInfoSection(BaseModel):
    """Subset of `BankCreate` — excludes `effective_from` (computed at activation from
    `proposed_joining_date`, O7)."""

    model_config = ConfigDict(extra="forbid")

    account_holder_name: str | None = Field(default=None, max_length=150)
    account_number_enc: str | None = None
    bank_name: str | None = Field(default=None, max_length=150)
    ifsc: str | None = Field(default=None, max_length=15)
    branch_name: str | None = Field(default=None, max_length=150)
    payment_mode: PaymentMode


class StatutoryInfoSection(BaseModel):
    """Subset of `StatutoryCreate` — excludes `effective_from` (computed at activation) and
    `revision_reason` (meaningless for an initial submission)."""

    model_config = ConfigDict(extra="forbid")

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


SECTION_SCHEMAS: dict[str, type[BaseModel]] = {
    "personal_info": PersonalInfoSection,
    "address_info": AddressInfoSection,
    "emergency_contact": EmergencyContactSection,
    "bank_info": BankInfoSection,
    "statutory_info": StatutoryInfoSection,
}


class PublicOnboardingCaseRead(BaseModel):
    """`GET /public/onboarding/{token}` — deliberately narrower than `OnboardingCaseRead`: no
    `id`/`company_id`/`created_by_user_id`/`employee_id` (the candidate has no use for internal
    IDs and no session to authorize looking anything else up with), and `writable` tells the
    wizard which sections it may currently `PATCH` (module docstring,
    `ONBOARDING_CASE_WRITABLE_STATUSES`)."""

    status: str
    candidate_first_name: str
    candidate_last_name: str | None
    proposed_joining_date: date
    writable: bool
    personal_info: dict[str, object]
    address_info: dict[str, object]
    emergency_contact: dict[str, object]
    bank_info: dict[str, object]
    statutory_info: dict[str, object]


def onboarding_case_to_public_read(case: "OnboardingCase") -> PublicOnboardingCaseRead:
    return PublicOnboardingCaseRead(
        status=case.status,
        candidate_first_name=case.candidate_first_name,
        candidate_last_name=case.candidate_last_name,
        proposed_joining_date=case.proposed_joining_date,
        writable=case.status in ONBOARDING_CASE_WRITABLE_STATUSES,
        personal_info=case.personal_info,
        address_info=case.address_info,
        emergency_contact=case.emergency_contact,
        bank_info=case.bank_info,
        statutory_info=case.statutory_info,
    )
