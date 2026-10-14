"""Pydantic request/response schemas for the onboarding module — O1 (case create/list/detail),
O2 (token issuance + public section read/write), O5 (documents), and O6 (section review +
changes-requested loop).

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

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

if TYPE_CHECKING:
    from hrms.modules.onboarding.models import (
        OnboardingCase,
        OnboardingDocument,
        OnboardingSectionReview,
        OnboardingToken,
    )

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
    "previous_employment_info",
    "education_info",
    "nominee_info",
)
# `compensation_info` is deliberately NOT in `ONBOARDING_SECTION_NAMES` (candidates no longer
# enter or get reviewed on CTC during onboarding). Its column and `SECTION_SCHEMAS` entry stay so
# a value written some other way is still turned into an `employee_compensation` row at activation.

# Human-readable labels for the five reviewable sections — used in the "changes requested" email
# (O6) and available for any admin-UI rendering that wants one canonical mapping. Plan §4.4's own
# `onboarding_section_review.section` enum also names a sixth value, `DOCUMENTS` — deliberately
# not included here: document review already has its own per-row status (`OnboardingDocument
# .status`, O5), so a redundant case-level "DOCUMENTS section" row would just be a second,
# possibly-contradictory source of truth for the same fact. "All documents verified" is computed
# directly from `onboarding_document` rows wherever it matters (e.g. the auto-verify check below),
# not from a row in this table.
ONBOARDING_SECTION_LABELS = {
    "personal_info": "Personal Info",
    "address_info": "Address",
    "emergency_contact": "Emergency Contact",
    "bank_info": "Bank Details",
    "statutory_info": "Statutory Details",
    "compensation_info": "Compensation",
    "previous_employment_info": "Previous Employment",
    "education_info": "Education",
    "nominee_info": "Nominees & Family Details",
}

ONBOARDING_SECTION_REVIEW_STATUS_VALUES = ("PENDING", "VERIFIED", "REJECTED")

# Case statuses in which a section/document review action is meaningful (O6) — `SUBMITTED` (the
# first review action on a freshly-submitted case moves it to `UNDER_REVIEW`, plan §6) and
# `UNDER_REVIEW` itself (subsequent review actions).
ONBOARDING_CASE_REVIEWABLE_STATUSES = ("SUBMITTED", "UNDER_REVIEW")

# Plan §4.3's own enumeration. Not client-extensible — `OTHER` is the deliberate escape hatch for
# anything not covered by the named seven.
ONBOARDING_DOCUMENT_TYPES = (
    "PHOTO",
    "PAN",
    "AADHAAR",
    "ADDRESS_PROOF",
    "EDUCATION_CERTIFICATE",
    "PREVIOUS_EMPLOYMENT_PROOF",
    "BANK_PROOF",
    "OTHER",
)

# Plan §8.3 flags virus scanning as explicitly out of scope for this first cut — this cap is
# this task's own engineering decision (no source document names a number), sized to comfortably
# fit a phone-camera photo of an ID document without allowing arbitrary large uploads.
ONBOARDING_DOCUMENT_MAX_SIZE_BYTES = 10 * 1024 * 1024

ONBOARDING_DOCUMENT_STATUS_VALUES = ("PENDING", "VERIFIED", "REJECTED")


class OnboardingCaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_first_name: str = Field(min_length=1, max_length=100)
    candidate_last_name: str | None = Field(default=None, max_length=100)
    personal_email: EmailStr
    personal_mobile: str | None = Field(default=None, max_length=20)
    designation_id: UUID | None = None
    department_id: UUID | None = None
    branch_id: UUID | None = None
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
    case record, set by HR at creation) and `custom_fields` (internal, not candidate-facing).

    `pan_number_enc`/`aadhaar_number_enc` (E-02, market-parity onboarding-data pass) follow the
    exact same case-level-AAD encrypt-on-write/decrypt-on-read pattern `bank_info.
    account_number_enc` already uses (`OnboardingCaseService.update_section`/
    `_decrypt_case_pii`) — plaintext never reaches the database despite the `_enc` suffix on a
    request-body field name. `father_or_husband_name` is plain, matching `Employee.
    father_or_husband_name`'s own sensitivity tier."""

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
    pan_number_enc: str | None = Field(default=None, min_length=10, max_length=10)
    aadhaar_number_enc: str | None = Field(default=None, min_length=12, max_length=12)
    photo_url: str | None = None


class AddressInfoSection(BaseModel):
    """Mirrors `EmployeeCreate`'s `present_*`/`permanent_*`/`permanent_same_as_present` fields
    (E-02, market-parity onboarding-data pass part 2) — activation now has a real target to
    write this section to (`Employee.present_*`/`permanent_*`), closing the gap this class's
    original docstring flagged ("no activation-time consumer yet"). Field names keep the
    original `address_line1`/`address_line2`/`city`/`state_code`/`pincode`/`country_code` shape
    for the present address (unprefixed, backward-compatible with every existing candidate
    submission), and add a mirrored `permanent_*` block plus a `permanent_same_as_present` flag
    the wizard uses to collapse the second block into a copy of the first."""

    model_config = ConfigDict(extra="forbid")

    address_line1: str | None = Field(default=None, max_length=200)
    address_line2: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=100)
    state_code: str | None = Field(default=None, max_length=10)
    pincode: str | None = Field(default=None, max_length=10)
    country_code: str | None = Field(default=None, max_length=2)
    permanent_same_as_present: bool = True
    permanent_address_line1: str | None = Field(default=None, max_length=200)
    permanent_address_line2: str | None = Field(default=None, max_length=200)
    permanent_city: str | None = Field(default=None, max_length=100)
    permanent_state_code: str | None = Field(default=None, max_length=10)
    permanent_pincode: str | None = Field(default=None, max_length=10)
    permanent_country_code: str | None = Field(default=None, max_length=2)


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
    uan_number: str | None = Field(default=None, max_length=20)
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


class CompensationInfoSection(BaseModel):
    """Subset of `CompensationCreate` — excludes `effective_from` (computed at activation from
    `proposed_joining_date`) and `revision_type`/`revision_reason` (activation always fills
    these in as `"JOINING"`/a fixed reason string, exactly like `StatutoryInfoSection` already
    omits `revision_reason` for the same reason). Closes the gap `OnboardingActivationService`'s
    own class docstring named: Compensation was listed among the services it composes, but there
    was no section to source CTC from until now (E-02, market-parity onboarding-data pass)."""

    model_config = ConfigDict(extra="forbid")

    annual_ctc_minor: int = Field(gt=0)
    # Omitted -> the company's own configured currency, filled in when the section is saved.
    currency: str | None = Field(min_length=3, max_length=3, default=None)


class PreviousEmploymentItem(BaseModel):
    """Mirrors `EmployeeExperienceCreate` field-for-field (minus `document_id`, which the
    candidate has no way to set from the wizard — proof-of-employment is uploaded separately
    via the existing `PREVIOUS_EMPLOYMENT_PROOF` document type, O5)."""

    model_config = ConfigDict(extra="forbid")

    company_name: str = Field(min_length=1, max_length=200)
    designation: str | None = Field(default=None, max_length=150)
    from_date: date
    to_date: date | None = None
    last_ctc_minor: int | None = Field(default=None, ge=0)
    reason_for_leaving: str | None = None
    had_prior_pf_membership: bool = False
    previous_uan: str | None = Field(default=None, max_length=20)
    previous_pf_account_number: str | None = Field(default=None, max_length=30)
    previous_esi_ip_number: str | None = Field(default=None, max_length=30)


class PreviousEmploymentSection(BaseModel):
    """Market-parity onboarding-data pass, part 4 — EPF Form 11's continuity block (previous
    UAN, PF account number, employer, dates) plus Form 12B's salary-continuity fields. A list,
    not a flat object like every other section — a candidate may have multiple past employers,
    all concurrently valid — wrapped in a single `items` key so this section's JSONB column
    still fits the same `dict[str, object]` shape every other section uses. Optional: a fresh
    graduate with no prior employer submits an empty `items` list, same "never made mandatory"
    posture `bank_info`/`statutory_info` already have at case level."""

    model_config = ConfigDict(extra="forbid")

    items: list[PreviousEmploymentItem] = Field(default_factory=list)


class EducationItem(BaseModel):
    """Mirrors `EmployeeEducationCreate` field-for-field (minus `document_id`, same reasoning
    as `PreviousEmploymentItem` — proof is a separate `EDUCATION_CERTIFICATE` document upload)."""

    model_config = ConfigDict(extra="forbid")

    qualification: str = Field(min_length=1, max_length=150)
    institution_name: str | None = Field(default=None, max_length=200)
    year_of_passing: int | None = Field(default=None, ge=1950, le=2100)


class EducationInfoSection(BaseModel):
    """Market-parity onboarding-data pass, part 5 — a list, same shape as
    `PreviousEmploymentSection`, since a candidate may hold multiple qualifications."""

    model_config = ConfigDict(extra="forbid")

    items: list[EducationItem] = Field(default_factory=list)


class NomineeItem(BaseModel):
    """Mirrors `EmployeeDependentCreate` field-for-field (minus `document_id`, same reasoning as
    `PreviousEmploymentItem`/`EducationItem` — proof is a separate document upload). `
    aadhaar_number_enc` follows the exact same case-level-AAD encrypt-on-write/decrypt-on-read
    pattern `personal_info.aadhaar_number_enc`/`bank_info.account_number_enc` already use
    (`OnboardingCaseService.update_section`/`_decrypt_nominee_info`), keyed per list index since
    a nominee item has no stable id of its own until activation creates its `EmployeeDependent`
    row — plaintext never reaches the database despite the `_enc` suffix on a request-body field
    name."""

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

    @model_validator(mode="after")
    def _require_guardian_when_minor(self) -> "NomineeItem":
        if self.is_minor and not (self.guardian_name or "").strip():
            raise ValueError("guardian_name is required when is_minor is true")
        return self

    @model_validator(mode="after")
    def _require_percentage_when_nominee(self) -> "NomineeItem":
        if self.is_pf_nominee and self.pf_nominee_share_percentage is None:
            raise ValueError("pf_nominee_share_percentage is required when is_pf_nominee is true")
        if self.is_gratuity_nominee and self.gratuity_nominee_share_percentage is None:
            raise ValueError(
                "gratuity_nominee_share_percentage is required when is_gratuity_nominee is true"
            )
        return self


class NomineeInfoSection(BaseModel):
    """Market-parity onboarding-data pass, part 6 — PF/Gratuity nominee declaration + ESI family
    details (EPF Form 2, Gratuity Form F, ESI Form 1/Form 2). A list, same shape as
    `PreviousEmploymentSection`/`EducationInfoSection`, since a candidate may declare multiple
    dependents. Validates each nominee scheme's percentages sum to <=100 across the *submitted*
    list — `EmployeeDependentService`'s own validator (employee-service layer) re-checks this
    against already-persisted rows at activation/direct-API-create time; this is the
    onboarding-layer half of that same rule (module conventions: "both the employee-service layer
    and the onboarding `update_section` layer")."""

    model_config = ConfigDict(extra="forbid")

    items: list[NomineeItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def _percentages_within_limit(self) -> "NomineeInfoSection":
        pf_total = sum(
            item.pf_nominee_share_percentage or 0 for item in self.items if item.is_pf_nominee
        )
        if pf_total > 100:
            raise ValueError(f"PF nominee share percentages total {pf_total}%, exceeding 100%")
        gratuity_total = sum(
            item.gratuity_nominee_share_percentage or 0
            for item in self.items
            if item.is_gratuity_nominee
        )
        if gratuity_total > 100:
            raise ValueError(
                f"Gratuity nominee share percentages total {gratuity_total}%, exceeding 100%"
            )
        return self


SECTION_SCHEMAS: dict[str, type[BaseModel]] = {
    "personal_info": PersonalInfoSection,
    "address_info": AddressInfoSection,
    "emergency_contact": EmergencyContactSection,
    "bank_info": BankInfoSection,
    "statutory_info": StatutoryInfoSection,
    "compensation_info": CompensationInfoSection,
    "previous_employment_info": PreviousEmploymentSection,
    "education_info": EducationInfoSection,
    "nominee_info": NomineeInfoSection,
}


class OnboardingSectionReviewRead(BaseModel):
    section: str
    status: str
    rejection_reason: str | None


class PublicOnboardingCaseRead(BaseModel):
    """`GET /public/onboarding/{token}` — deliberately narrower than `OnboardingCaseRead`: no
    `id`/`company_id`/`created_by_user_id`/`employee_id` (the candidate has no use for internal
    IDs and no session to authorize looking anything else up with), and `writable` tells the
    wizard which sections it may currently `PATCH` (module docstring,
    `ONBOARDING_CASE_WRITABLE_STATUSES`). `section_reviews` (O6) lets the wizard show which
    sections HR has already verified (lock the fields, nothing left to fix) versus rejected (show
    the reason) — deliberately just `section`/`status`/`rejection_reason`, no reviewer identity or
    timestamp, which the candidate has no use for."""

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
    compensation_info: dict[str, object]
    previous_employment_info: dict[str, object]
    education_info: dict[str, object]
    nominee_info: dict[str, object]
    section_reviews: list[OnboardingSectionReviewRead]


class OnboardingInviteRead(BaseModel):
    """`POST /onboarding-cases/{id}/send-invite` (O3) — returns the updated case plus the raw
    `invite_url`, since this response is the *only* time the raw link is ever available (only
    its token's SHA-256 hash is persisted, plan §8.1). This is also what backs the admin UI's
    "Copy link" action (plan §9) independent of whether `email_sent` succeeded — a failed email
    delivery must not block HR from getting the link some other way."""

    case: OnboardingCaseRead
    invite_url: str
    email_sent: bool


def onboarding_section_review_to_read(
    review: "OnboardingSectionReview",
) -> OnboardingSectionReviewRead:
    return OnboardingSectionReviewRead(
        section=review.section,
        status=review.status,
        rejection_reason=review.rejection_reason,
    )


def onboarding_case_to_public_read(
    case: "OnboardingCase",
    section_reviews: "list[OnboardingSectionReview]",
    *,
    bank_info: dict[str, object],
    personal_info: dict[str, object] | None = None,
    nominee_info: dict[str, object] | None = None,
) -> PublicOnboardingCaseRead:
    """DATA-01 (`docs/audits/DATA_01_PII_ENCRYPTION_IMPLEMENTATION_PLAN.md` §2.5/§7) —
    `case.bank_info`'s `account_number_enc` key holds ciphertext at rest; `bank_info` is a
    required keyword, not defaulted to `case.bank_info`, so a call site cannot forget to decrypt
    it first. The caller (`OnboardingCaseService`) is responsible for calling
    `PiiCryptoService.decrypt_jsonb_key(...)` and substituting the result before this function is
    called.

    `personal_info` (E-02) follows the same contract for `pan_number_enc`/`aadhaar_number_enc` —
    optional-with-default (`None` -> `case.personal_info` unchanged) only so every pre-E-02 test
    fixture that never passed it keeps working; every real call site in `OnboardingCaseService`
    always passes the decrypted dict explicitly, same as `bank_info`. `nominee_info` (market-parity
    onboarding-data pass, part 6) follows the identical optional-with-default contract for each
    item's `aadhaar_number_enc`."""
    return PublicOnboardingCaseRead(
        status=case.status,
        candidate_first_name=case.candidate_first_name,
        candidate_last_name=case.candidate_last_name,
        proposed_joining_date=case.proposed_joining_date,
        writable=case.status in ONBOARDING_CASE_WRITABLE_STATUSES,
        personal_info=personal_info if personal_info is not None else case.personal_info,
        address_info=case.address_info,
        emergency_contact=case.emergency_contact,
        bank_info=bank_info,
        statutory_info=case.statutory_info,
        compensation_info=case.compensation_info,
        previous_employment_info=case.previous_employment_info,
        education_info=case.education_info,
        nominee_info=nominee_info if nominee_info is not None else case.nominee_info,
        section_reviews=[onboarding_section_review_to_read(r) for r in section_reviews],
    )


# --- O5: documents ---------------------------------------------------------------------------


class OnboardingDocumentRead(BaseModel):
    """Deliberately excludes `s3_key` — an internal storage detail, never returned to either the
    candidate or the admin UI (which gets a presigned URL instead, `OnboardingDocumentWithUrlRead`
    below)."""

    id: UUID
    document_type: str
    original_filename: str
    content_type: str
    size_bytes: int
    status: str
    rejection_reason: str | None
    uploaded_at: str


class OnboardingDocumentWithUrlRead(OnboardingDocumentRead):
    """The admin-only shape (`GET /onboarding-cases/{id}/documents`) — adds the short-lived
    presigned GET URL so document bytes never round-trip through the API server (plan §8.3)."""

    download_url: str


class OnboardingDocumentReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["VERIFIED", "REJECTED"]
    rejection_reason: str | None = None

    @model_validator(mode="after")
    def _require_reason_when_rejected(self) -> "OnboardingDocumentReviewRequest":
        if self.status == "REJECTED" and not (self.rejection_reason or "").strip():
            raise ValueError("rejection_reason is required when status is REJECTED")
        return self


def _format_timestamp_required(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def onboarding_document_to_read(document: "OnboardingDocument") -> OnboardingDocumentRead:
    return OnboardingDocumentRead(
        id=document.id,
        document_type=document.document_type,
        original_filename=document.original_filename,
        content_type=document.content_type,
        size_bytes=document.size_bytes,
        status=document.status,
        rejection_reason=document.rejection_reason,
        uploaded_at=_format_timestamp_required(document.uploaded_at),
    )


def onboarding_document_to_read_with_url(
    document: "OnboardingDocument", download_url: str
) -> OnboardingDocumentWithUrlRead:
    base = onboarding_document_to_read(document)
    return OnboardingDocumentWithUrlRead(**base.model_dump(), download_url=download_url)


# --- O6: section review + changes-requested loop ---------------------------------------------


class OnboardingSectionReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["VERIFIED", "REJECTED"]
    rejection_reason: str | None = None

    @model_validator(mode="after")
    def _require_reason_when_rejected(self) -> "OnboardingSectionReviewRequest":
        if self.status == "REJECTED" and not (self.rejection_reason or "").strip():
            raise ValueError("rejection_reason is required when status is REJECTED")
        return self


class OnboardingCaseDetailRead(OnboardingCaseRead):
    """`GET /onboarding-cases/{id}` (admin) — extends the list-safe `OnboardingCaseRead` with the
    five section JSON blobs and their review status, so HR can actually see what the candidate
    submitted, not just verify/reject blind (plan §9: "per-section review cards"). Deliberately
    not folded into `OnboardingCaseRead` itself — that shape is also used by `GET
    /onboarding-cases` (the list view), which has no business returning bank-account/statutory
    detail for every row on a list screen."""

    personal_info: dict[str, object]
    address_info: dict[str, object]
    emergency_contact: dict[str, object]
    bank_info: dict[str, object]
    statutory_info: dict[str, object]
    compensation_info: dict[str, object]
    previous_employment_info: dict[str, object]
    education_info: dict[str, object]
    nominee_info: dict[str, object]
    section_reviews: list[OnboardingSectionReviewRead]
    #: Never the raw token (never persisted, plan §8.1) — just enough for HR to tell whether the
    #: last link they sent is still usable. `None` when no token has ever been issued.
    token_status: Literal["ACTIVE", "EXPIRED", "REVOKED"] | None = None
    token_expires_at: str | None = None


def _token_status(
    token: "OnboardingToken | None", *, now: datetime
) -> Literal["ACTIVE", "EXPIRED", "REVOKED"] | None:
    if token is None:
        return None
    if token.revoked_at is not None:
        return "REVOKED"
    if token.expires_at <= now:
        return "EXPIRED"
    return "ACTIVE"


def onboarding_case_to_detail_read(
    case: "OnboardingCase",
    section_reviews: "list[OnboardingSectionReview]",
    *,
    bank_info: dict[str, object],
    personal_info: dict[str, object] | None = None,
    nominee_info: dict[str, object] | None = None,
    latest_token: "OnboardingToken | None" = None,
) -> OnboardingCaseDetailRead:
    """DATA-01 — see `onboarding_case_to_public_read`'s docstring; same contract, HR-facing."""
    base = onboarding_case_to_read(case)
    return OnboardingCaseDetailRead(
        **base.model_dump(),
        personal_info=personal_info if personal_info is not None else case.personal_info,
        address_info=case.address_info,
        emergency_contact=case.emergency_contact,
        bank_info=bank_info,
        statutory_info=case.statutory_info,
        compensation_info=case.compensation_info,
        previous_employment_info=case.previous_employment_info,
        education_info=case.education_info,
        nominee_info=nominee_info if nominee_info is not None else case.nominee_info,
        section_reviews=[onboarding_section_review_to_read(r) for r in section_reviews],
        token_status=_token_status(latest_token, now=datetime.now(UTC)),
        token_expires_at=_format_timestamp(latest_token.expires_at) if latest_token else None,
    )
