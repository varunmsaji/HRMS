"""Pydantic request/response schemas for the onboarding module — O1 (case create/list/detail)
only. Sections (`personal_info`/`address_info`/etc.) have no request schema yet — that lands in
O2 as one schema per section, each a strict field subset of the matching `EmployeeCreate`/
`BankCreate`/`StatutoryCreate` (plan §7.2/§8.2)."""

from datetime import date, datetime
from typing import TYPE_CHECKING
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
