"""ORM models owned by the onboarding module (O1 — data model + admin create/list/detail).

Covers `docs/modules/onboarding/01_ONBOARDING_MODULE_PLAN.md` §4: `OnboardingCase` (the staging
record HR starts for a known new hire), `OnboardingToken` (the public-link credential, issued
from O2 onward), `OnboardingDocument` (candidate-uploaded files, from O5 onward), and
`OnboardingSectionReview` (per-section HR verify/reject state, from O6 onward). All four tables
are created together in this slice's migration since the shape is settled up front, even though
only `OnboardingCase` has application code reading/writing it in O1 — `OnboardingToken`/
`OnboardingDocument`/`OnboardingSectionReview` stay empty until the phases that own their write
paths land (plan §12).

Deliberately does not duplicate any field validation already owned by the employee module —
`personal_info`/`address_info`/`emergency_contact`/`bank_info`/`statutory_info` are untyped JSONB
here; the plan's own decision (§2/§7.2) is that each section's shape is validated against the
matching subset of `EmployeeCreate`/`BankCreate`/`StatutoryCreate` only when the public PATCH
routes that write them exist (O2), not at the ORM layer.

`employment_type_id` from the plan's own §4.1 table does not correspond to any real column —
`EmploymentCreate` (`hrms.modules.employee.schemas`) only ever takes `legal_entity_id` and
`joining_date`; there is no `employment_type` table anywhere in this codebase. This model uses
`legal_entity_id` instead, since that is what activation (§8.6, O7) will actually need to pass to
`EmploymentService.create_employment`."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from hrms.core.db.base import Base, TimestampMixin


class OnboardingCase(Base, TimestampMixin):
    """One new hire's staged onboarding record — created by HR/Admin, later filled in by the
    candidate via the public token-authenticated wizard (O2/O4), reviewed section-by-section by
    HR (O6), and finally turned into a real `Employee`/`Employment`/`Assignment` row graph by
    activation (O7). `status` follows the plan's own state machine (§6): `DRAFT, INVITED,
    IN_PROGRESS, SUBMITTED, UNDER_REVIEW, CHANGES_REQUESTED, VERIFIED, ACTIVATED, EXPIRED,
    CANCELLED` — transitions are server-enforced in the service layer, not a DB `CHECK` (mirrors
    `Employee.status`'s own convention: a `String` column, not a SQL enum type)."""

    __tablename__ = "onboarding_case"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    status: Mapped[str] = mapped_column(String(25), default="DRAFT")
    candidate_first_name: Mapped[str] = mapped_column(String(100))
    candidate_last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    personal_email: Mapped[str] = mapped_column(String(255), index=True)
    personal_mobile: Mapped[str | None] = mapped_column(String(20), nullable=True)
    designation_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("designation.id"), nullable=True
    )
    department_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("department.id"), nullable=True
    )
    branch_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("branch.id"), nullable=True
    )
    legal_entity_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("legal_entity.id"), nullable=True
    )
    proposed_joining_date: Mapped[date] = mapped_column(Date)
    created_by_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id")
    )
    personal_info: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    address_info: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    emergency_contact: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # DATA-01 (`docs/audits/DATA_01_PII_ENCRYPTION_IMPLEMENTATION_PLAN.md` §2.5/§9) — the
    # `account_number_enc` key inside this dict holds ciphertext once written via
    # `OnboardingCaseService.update_section`; every other key is untouched plaintext (not
    # sensitive, inventory §1). Decrypted explicitly, per read, via
    # `OnboardingCaseService._decrypt_bank_info`/`OnboardingActivationService._decrypt_bank_info`
    # — never automatically. This column is not cleared after activation in this batch (DATA-01
    # implementation batch §9/§15 — gated on a product/compliance sign-off that has not been
    # recorded; the retained ciphertext-copy alternative, plan §9.2, is what this batch ships).
    bank_info: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    statutory_info: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # E-02 (market-parity onboarding-data pass, part 3) — CTC, not encrypted (mirrors
    # `EmployeeCompensation.annual_ctc_minor`'s own plain-column shape; RESTRICTED here means
    # permission-gated, not encrypted-at-rest, same posture the employee module already uses).
    compensation_info: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Market-parity onboarding-data pass, part 4 — `{"items": [...]}`, a list wrapped in a dict
    # so this column fits the same shape every other section uses (see `PreviousEmploymentSection`
    # docstring). Not encrypted — `previous_uan`/`previous_pf_account_number` are the same
    # sensitivity tier as `Employee.uan_number`/`EmployeeStatutory.pf_number`, both plain.
    previous_employment_info: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Market-parity onboarding-data pass, part 5 — same `{"items": [...]}` list shape.
    education_info: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Market-parity onboarding-data pass, part 6 — PF/Gratuity nominee + ESI family details, same
    # `{"items": [...]}` list shape. Each item's `aadhaar_number_enc` key holds ciphertext once
    # written via `OnboardingCaseService.update_section`, keyed per list index (`NomineeItem`
    # docstring) — decrypted explicitly, per read, via `OnboardingCaseService.
    # _decrypt_nominee_info`/`OnboardingActivationService._decrypt_nominee_info`, never
    # automatically.
    nominee_info: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    policy_ack_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    policy_ack_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    employee_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employee.id"), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class OnboardingToken(Base, TimestampMixin):
    """The public-link credential (O2) — `token_hash` is a SHA-256 hex digest, the raw token is
    never persisted (plan §4.2/§8.1). Only one live (non-revoked, non-expired) row per case is
    ever meant to exist at a time; a resend revokes the previous row rather than deleting it
    (plan §4.2), enforced in the service layer, not a DB constraint.

    Unlike every other table in this module, this one carries **no RLS policy** — a corrective
    migration (`20260906090000_onboarding_o2`) disables the `tenant_isolation` policy the O1
    migration mistakenly gave it. A public, unauthenticated caller has no tenant context yet; the
    only thing that can look up a row here is the token hash itself, before any `company_id` GUC
    can be set — the same pre-tenant-context shape `refresh_token` already has
    (`scripts/sql/001_init_schema.sql`). `company_id` is kept as a plain, unenforced column so the
    resolved value can seed the RLS GUC for every subsequent query in the same request (plan §5) —
    it is still re-validated by that subsequent, RLS-protected `onboarding_case` lookup, so a
    tampered/forged `company_id` on this row (not possible from any client input; this column is
    only ever server-written) still could not leak another tenant's data."""

    __tablename__ = "onboarding_token"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    onboarding_case_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("onboarding_case.id"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_first_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OnboardingDocument(Base, TimestampMixin):
    """A candidate-uploaded identity/education/bank-proof document (O5) — `s3_key` points into
    `Settings.s3_bucket_documents`; document bytes never round-trip through the API server for
    the admin review UI (presigned GET URLs instead, plan §8.3)."""

    __tablename__ = "onboarding_document"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    onboarding_case_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("onboarding_case.id"), index=True
    )
    document_type: Mapped[str] = mapped_column(String(40))
    s3_key: Mapped[str] = mapped_column(String(512))
    original_filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    verified_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id"), nullable=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OnboardingSectionReview(Base, TimestampMixin):
    """Per-section HR verify/reject state (O6) — kept as its own table rather than a status
    column on `OnboardingCase` so a rejection can reopen exactly one section for the candidate
    to redo, without touching the others (plan §4.4)."""

    __tablename__ = "onboarding_section_review"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    onboarding_case_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("onboarding_case.id"), index=True
    )
    section: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    reviewed_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String, nullable=True)
