"""Business logic for the onboarding module — O1 (case create/list/detail), O2 (token issuance +
public section read/write), O3 (send-invite, backed by the minimal `EmailSender`), O4 (submit,
the wizard's own completion step), O5 (document upload/review, backed by
`DocumentStorageService`), O6 (section review + changes-requested loop), and O7 (activation —
the transaction that creates the real Employee/Employment/Assignment/Bank/Statutory rows)."""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.audit.service import AuditService
from hrms.core.config.settings import Settings, get_settings
from hrms.core.crypto.service import PiiCryptoService
from hrms.core.db.session import set_rls_company_id
from hrms.core.errors.base import NotFoundError
from hrms.core.storage import DocumentStorageService
from hrms.modules.onboarding.document_validation import (
    content_disposition_attachment,
    safe_document_object_key,
    sanitize_display_filename,
    sniff_document_content_type,
)
from hrms.modules.onboarding.email_sender import get_email_sender
from hrms.modules.onboarding.email_templates import (
    build_activated_email,
    build_changes_requested_email,
    build_invite_email,
)
from hrms.modules.onboarding.exceptions import (
    DuplicateActiveOnboardingCaseError,
    InvalidBranchReferenceError,
    InvalidDepartmentReferenceError,
    InvalidDesignationReferenceError,
    InvalidOnboardingDocumentTypeError,
    InvalidOnboardingSectionError,
    OnboardingCaseMissingLegalEntityError,
    OnboardingCaseNotInvitableError,
    OnboardingCaseNotReadyForActivationError,
    OnboardingCaseNotReviewableError,
    OnboardingCaseNotSubmittableError,
    OnboardingDocumentTooLargeError,
    OnboardingIncompleteSectionsError,
    OnboardingNothingToRequestChangesForError,
    OnboardingSectionAlreadyVerifiedError,
    OnboardingSectionNotWritableError,
    OnboardingTokenInvalidError,
    UnsupportedDocumentContentError,
)
from hrms.modules.onboarding.repository import (
    OnboardingCaseRepository,
    OnboardingDocumentRepository,
    OnboardingSectionReviewRepository,
    OnboardingTokenRepository,
)
from hrms.modules.onboarding.schemas import (
    ONBOARDING_CASE_REVIEWABLE_STATUSES,
    ONBOARDING_CASE_WRITABLE_STATUSES,
    ONBOARDING_DOCUMENT_MAX_SIZE_BYTES,
    ONBOARDING_DOCUMENT_TYPES,
    ONBOARDING_SECTION_LABELS,
    ONBOARDING_SECTION_NAMES,
    OnboardingCaseCreate,
    OnboardingCaseDetailRead,
    OnboardingCaseRead,
    OnboardingDocumentRead,
    OnboardingDocumentWithUrlRead,
    OnboardingInviteRead,
    OnboardingSectionReviewRead,
    PublicOnboardingCaseRead,
    onboarding_case_to_audit_dict,
    onboarding_case_to_detail_read,
    onboarding_case_to_public_read,
    onboarding_case_to_read,
    onboarding_document_to_read,
    onboarding_document_to_read_with_url,
    onboarding_section_review_to_read,
)

if TYPE_CHECKING:
    from hrms.modules.onboarding.models import OnboardingCase

#: Statuses `send-invite` may act on (O3) — `DRAFT`/`EXPIRED` (first send / re-send after
#: lapsing) and `INVITED`/`IN_PROGRESS` (plain resend, e.g. "candidate lost the email"; case
#: status is unchanged in these last two — `issue_token` only transitions `DRAFT`/`EXPIRED`).
#: `SUBMITTED`/`UNDER_REVIEW`/`VERIFIED` are deliberately excluded — a fresh link there would
#: let the candidate bypass HR's review; `CHANGES_REQUESTED`'s own reopen-and-resend flow
#: belongs to O6, not this endpoint. `ACTIVATED` *is* included even though the case itself is
#: terminal: HR may still need to hand back a link so the (now-)employee can view what they
#: submitted — `resolve_and_touch` resolves it read-only (`writable` is false past this point,
#: `ONBOARDING_CASE_WRITABLE_STATUSES` below), so this can never reopen editing.
ONBOARDING_CASE_INVITABLE_STATUSES = ("DRAFT", "EXPIRED", "INVITED", "IN_PROGRESS", "ACTIVATED")

#: Default public-link lifetime (plan §4.2: "default 7 days, HR-configurable per case at
#: send/resend time" — the per-case override arrives with the O3 send-invite endpoint; this
#: constant is O2's own default, used directly since nothing yet calls `issue_token` with a
#: caller-supplied override).
DEFAULT_TOKEN_TTL_DAYS = 7


async def _ensure_case_under_review(
    case_repo: OnboardingCaseRepository,
    session: AsyncSession,
    case: "OnboardingCase",
    now: datetime,
) -> None:
    """Shared by section review and document review (O6) — the first review action on a freshly
    `SUBMITTED` case moves it to `UNDER_REVIEW` (state machine, plan §6). A no-op once already
    `UNDER_REVIEW`, and — deliberately — also a no-op for every other status (e.g. `IN_PROGRESS`):
    document review has no case-status gate of its own (module docstring,
    `OnboardingDocumentService.review_document`), so calling this unconditionally from there must
    never have a side effect on a case the candidate hasn't submitted yet."""
    if case.status == "SUBMITTED":
        await case_repo.set_status(session, case=case, status="UNDER_REVIEW", now=now)


async def _maybe_auto_verify_case(
    session: AsyncSession,
    *,
    case_repo: OnboardingCaseRepository,
    section_review_repo: OnboardingSectionReviewRepository,
    document_repo: OnboardingDocumentRepository,
    company_id: UUID,
    case: "OnboardingCase",
    now: datetime,
) -> None:
    """Shared by section review and document review (O6) — plan §6's "(all verified) -> VERIFIED"
    transition, computed rather than a manual HR action: fires the moment the last outstanding
    section or document turns `VERIFIED`. Zero uploaded documents counts as vacuously "all
    verified" — this module has never made document upload mandatory
    (`OnboardingIncompleteSectionsError`'s own docstring), so a case with all five sections
    verified and no documents at all should not be stuck waiting on something that was never
    required."""
    if case.status != "UNDER_REVIEW":
        return

    reviews = await section_review_repo.list_for_case(
        session, company_id=company_id, case_id=case.id
    )
    review_status_by_section = {r.section: r.status for r in reviews}
    if any(review_status_by_section.get(name) != "VERIFIED" for name in ONBOARDING_SECTION_NAMES):
        return

    documents = await document_repo.list_documents(session, company_id=company_id, case_id=case.id)
    if any(document.status != "VERIFIED" for document in documents):
        return

    await case_repo.set_status(session, case=case, status="VERIFIED", now=now)


#: DATA-01 (`docs/audits/DATA_01_PII_ENCRYPTION_IMPLEMENTATION_PLAN.md` §2.4/§9) — the one key
#: inside `bank_info` (and, symmetrically, `BankInfoSection`/`BankCreate`) that DATA-01 encrypts.
#: The other keys (`bank_name`, `branch_name`, `payment_mode`, `account_holder_name`, `ifsc`) are
#: not sensitive (inventory §1) and are never touched by the calls below.
BANK_INFO_SENSITIVE_KEY = "account_number_enc"

#: E-02 (market-parity onboarding-data pass) — the two keys inside `personal_info` (and,
#: symmetrically, `PersonalInfoSection`) DATA-01-style encryption now covers, mirroring
#: `BANK_INFO_SENSITIVE_KEY` exactly. Every other key (`first_name`, `date_of_birth`,
#: `father_or_husband_name`, etc.) is not sensitive enough to warrant field-level encryption and
#: is never touched by the calls below.
PERSONAL_INFO_SENSITIVE_KEYS = ("pan_number_enc", "aadhaar_number_enc")

#: Market-parity onboarding-data pass, part 6 — the one key inside each `nominee_info["items"]`
#: entry (and, symmetrically, `NomineeItem`) DATA-01-style encryption covers, mirroring
#: `BANK_INFO_SENSITIVE_KEY`/`PERSONAL_INFO_SENSITIVE_KEYS` exactly. Unlike those two,
#: `nominee_info` is a *list*, so each item's ciphertext is bound by a per-index `jsonb_key`
#: (`items.<index>.aadhaar_number_enc`) rather than one fixed key — correct because the whole
#: `nominee_info` column is always overwritten atomically by `update_section` (never a partial
#: per-item patch), so a stale index never outlives the write that established it.
NOMINEE_INFO_SENSITIVE_ITEM_KEY = "aadhaar_number_enc"


def _address_info_to_employee_fields(address_info: dict[str, Any]) -> dict[str, Any]:
    """E-02 (market-parity onboarding-data pass part 2) — `AddressInfoSection`'s unprefixed
    `address_line1`/`.../country_code` keys (the present address) map onto `Employee`'s
    `present_*`-prefixed columns; `permanent_*`/`permanent_same_as_present` map through
    unchanged (same names on both sides). Closes the gap `onboarding/schemas.py`'s own module
    docstring flagged: `address_info` previously had no activation-time consumer at all."""
    return {
        "present_address_line1": address_info.get("address_line1"),
        "present_address_line2": address_info.get("address_line2"),
        "present_city": address_info.get("city"),
        "present_state_code": address_info.get("state_code"),
        "present_pincode": address_info.get("pincode"),
        "present_country_code": address_info.get("country_code"),
        "permanent_address_line1": address_info.get("permanent_address_line1"),
        "permanent_address_line2": address_info.get("permanent_address_line2"),
        "permanent_city": address_info.get("permanent_city"),
        "permanent_state_code": address_info.get("permanent_state_code"),
        "permanent_pincode": address_info.get("permanent_pincode"),
        "permanent_country_code": address_info.get("permanent_country_code"),
        "permanent_same_as_present": address_info.get("permanent_same_as_present", True),
    }


def _emergency_contact_to_employee_fields(emergency_contact: dict[str, Any]) -> dict[str, Any]:
    """E-02 — `EmergencyContactSection`'s `contact_name`/`relationship`/`phone` map onto
    `Employee.emergency_contact_name`/`.emergency_contact_relationship`/`.emergency_contact_phone`.
    Same "previously had no activation-time consumer" gap as address_info, above."""
    return {
        "emergency_contact_name": emergency_contact.get("contact_name"),
        "emergency_contact_relationship": emergency_contact.get("relationship"),
        "emergency_contact_phone": emergency_contact.get("phone"),
    }


class OnboardingCaseService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._repo = OnboardingCaseRepository()
        self._section_review_repo = OnboardingSectionReviewRepository()
        self._token_repo = OnboardingTokenRepository()
        self._audit = AuditService()
        self._crypto = PiiCryptoService(self._settings)

    async def _decrypt_bank_info(self, case: "OnboardingCase") -> dict[str, Any]:
        """DATA-01 (plan §2.5/§7) — returns a copy of `case.bank_info` with the one sensitive key
        decrypted; every other key passes through unchanged. Used at every read-back site
        (`get_case_detail`, `get_public_case`, `update_section`'s own return value,
        `submit_case`'s own return value) — never returns the raw dict directly."""
        bank_info = dict(case.bank_info)
        ciphertext = bank_info.get(BANK_INFO_SENSITIVE_KEY)
        if isinstance(ciphertext, str):
            bank_info[BANK_INFO_SENSITIVE_KEY] = await self._crypto.decrypt_jsonb_key(
                self._session,
                ciphertext=ciphertext,
                table="onboarding_case",
                column="bank_info",
                jsonb_key=BANK_INFO_SENSITIVE_KEY,
                record_id=case.id,
            )
        return bank_info

    async def _decrypt_personal_info(self, case: "OnboardingCase") -> dict[str, Any]:
        """E-02 — mirrors `_decrypt_bank_info` exactly, for `pan_number_enc`/`aadhaar_number_enc`
        instead of `account_number_enc`. Used at every read-back site, same convention."""
        personal_info = dict(case.personal_info)
        for key in PERSONAL_INFO_SENSITIVE_KEYS:
            ciphertext = personal_info.get(key)
            if isinstance(ciphertext, str):
                personal_info[key] = await self._crypto.decrypt_jsonb_key(
                    self._session,
                    ciphertext=ciphertext,
                    table="onboarding_case",
                    column="personal_info",
                    jsonb_key=key,
                    record_id=case.id,
                )
        return personal_info

    async def _decrypt_nominee_info(self, case: "OnboardingCase") -> dict[str, Any]:
        """Market-parity onboarding-data pass, part 6 — mirrors `_decrypt_bank_info`/
        `_decrypt_personal_info`'s exact contract, but per list item (see
        `NOMINEE_INFO_SENSITIVE_ITEM_KEY`'s docstring for why the AAD is index-bound)."""
        nominee_info = dict(case.nominee_info)
        items = nominee_info.get("items")
        if not isinstance(items, list):
            return nominee_info
        decrypted_items = []
        for index, item in enumerate(items):
            item = dict(item)
            ciphertext = item.get(NOMINEE_INFO_SENSITIVE_ITEM_KEY)
            if isinstance(ciphertext, str):
                item[NOMINEE_INFO_SENSITIVE_ITEM_KEY] = await self._crypto.decrypt_jsonb_key(
                    self._session,
                    ciphertext=ciphertext,
                    table="onboarding_case",
                    column="nominee_info",
                    jsonb_key=f"items.{index}.{NOMINEE_INFO_SENSITIVE_ITEM_KEY}",
                    record_id=case.id,
                )
            decrypted_items.append(item)
        nominee_info["items"] = decrypted_items
        return nominee_info

    async def _assert_designation_ownership(self, company_id: UUID, designation_id: UUID) -> None:
        """Cross-module reference check, mirroring `EmployeeAssignmentService.
        _assert_designation_ownership` exactly — imported lazily, `organisation.service` is the
        only surface this module may import from (Module Standard §2), never `.repository`/
        `.models`."""
        from hrms.modules.organisation.service import OrganisationService

        organisation = OrganisationService(self._session, self._settings)
        try:
            await organisation.get_designation(company_id, designation_id)
        except NotFoundError as exc:
            raise InvalidDesignationReferenceError() from exc

    async def _assert_department_ownership(self, company_id: UUID, department_id: UUID) -> None:
        from hrms.modules.organisation.service import OrganisationService

        organisation = OrganisationService(self._session, self._settings)
        try:
            await organisation.get_department(company_id, department_id)
        except NotFoundError as exc:
            raise InvalidDepartmentReferenceError() from exc

    async def _assert_branch_ownership(self, company_id: UUID, branch_id: UUID) -> UUID:
        """Returns the branch's `legal_entity_id` — a company has exactly one legal entity
        (`single_legal_entity_per_company` product decision), so the case's legal entity is
        always derived from its branch rather than asked for separately."""
        from hrms.modules.organisation.service import OrganisationService

        organisation = OrganisationService(self._session, self._settings)
        try:
            branch = await organisation.get_branch(company_id, branch_id)
        except NotFoundError as exc:
            raise InvalidBranchReferenceError() from exc
        return branch.legal_entity_id

    async def create_case(
        self,
        company_id: UUID,
        body: OnboardingCaseCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> OnboardingCaseRead:
        # `created_by_user_id` is a NOT NULL column (a case always has a known creator) —
        # `actor_user_id` is typed `UUID | None` only to match the audit-log call's own
        # convention (`EmployeeService.create_employee`); every authenticated route's
        # `TenantContext.user_id` (this parameter's sole caller) is always populated.
        assert actor_user_id is not None
        if body.designation_id is not None:
            await self._assert_designation_ownership(company_id, body.designation_id)
        if body.department_id is not None:
            await self._assert_department_ownership(company_id, body.department_id)
        legal_entity_id: UUID | None = None
        if body.branch_id is not None:
            legal_entity_id = await self._assert_branch_ownership(company_id, body.branch_id)

        existing = await self._repo.get_active_case_by_email(
            self._session, company_id=company_id, personal_email=body.personal_email
        )
        if existing is not None:
            raise DuplicateActiveOnboardingCaseError()

        now = datetime.now(UTC)
        case_id = uuid4()
        case = await self._repo.insert_case(
            self._session,
            data={
                "id": case_id,
                "company_id": company_id,
                "status": "DRAFT",
                "candidate_first_name": body.candidate_first_name,
                "candidate_last_name": body.candidate_last_name,
                "personal_email": body.personal_email,
                "personal_mobile": body.personal_mobile,
                "designation_id": body.designation_id,
                "department_id": body.department_id,
                "branch_id": body.branch_id,
                "legal_entity_id": legal_entity_id,
                "proposed_joining_date": body.proposed_joining_date,
                "created_by_user_id": actor_user_id,
                "personal_info": {},
                "address_info": {},
                "emergency_contact": {},
                "bank_info": {},
                "statutory_info": {},
                "compensation_info": {},
                "previous_employment_info": {},
                "education_info": {},
                "nominee_info": {},
                "created_at": now,
                "updated_at": now,
            },
        )

        read = onboarding_case_to_read(case)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="ONBOARDING_CASE_CREATED",
            entity_type="onboarding_case",
            entity_id=case_id,
            after=onboarding_case_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def list_cases(
        self, company_id: UUID, *, status: str | None = None
    ) -> list[OnboardingCaseRead]:
        cases = await self._repo.list_cases(self._session, company_id=company_id, status=status)
        return [onboarding_case_to_read(case) for case in cases]

    async def get_case(self, company_id: UUID, case_id: UUID) -> OnboardingCaseRead:
        case = await self._repo.get_case(self._session, company_id=company_id, case_id=case_id)
        if case is None:
            raise NotFoundError("Resource not found")
        return onboarding_case_to_read(case)

    async def get_case_detail(self, company_id: UUID, case_id: UUID) -> OnboardingCaseDetailRead:
        """`GET /onboarding-cases/{id}` (admin) — the O6 richer detail read: the five section
        JSON blobs plus their review status, so HR can see what the candidate actually submitted
        instead of verifying/rejecting blind (plan §9)."""
        case = await self._repo.get_case(self._session, company_id=company_id, case_id=case_id)
        if case is None:
            raise NotFoundError("Resource not found")
        reviews = await self._section_review_repo.list_for_case(
            self._session, company_id=company_id, case_id=case_id
        )
        latest_token = await self._token_repo.get_latest_for_case(self._session, case_id=case_id)
        return onboarding_case_to_detail_read(
            case,
            reviews,
            bank_info=await self._decrypt_bank_info(case),
            personal_info=await self._decrypt_personal_info(case),
            nominee_info=await self._decrypt_nominee_info(case),
            latest_token=latest_token,
        )

    async def get_public_case(self, company_id: UUID, case_id: UUID) -> PublicOnboardingCaseRead:
        """Called only after `OnboardingTokenService.resolve_and_touch` has already proven the
        token is live and set the RLS `company_id` GUC from it — `company_id`/`case_id` here
        come from that resolved, server-side context, never from client input (module docstring,
        `hrms.modules.onboarding.public_router`)."""
        case = await self._repo.get_case(self._session, company_id=company_id, case_id=case_id)
        if case is None:
            raise NotFoundError("Resource not found")
        reviews = await self._section_review_repo.list_for_case(
            self._session, company_id=company_id, case_id=case_id
        )
        return onboarding_case_to_public_read(
            case,
            reviews,
            bank_info=await self._decrypt_bank_info(case),
            personal_info=await self._decrypt_personal_info(case),
            nominee_info=await self._decrypt_nominee_info(case),
        )

    async def update_section(
        self, company_id: UUID, case_id: UUID, section: str, data: dict[str, Any]
    ) -> PublicOnboardingCaseRead:
        """`section` is always one of `SECTION_SCHEMAS`' keys by the time this is called — the
        public router rejects anything else before this point (`InvalidOnboardingSectionError`)
        — and `data` is always the already-`model_validate`d, `extra="forbid"` section schema's
        own dump, never raw client JSON."""
        case = await self._repo.get_case(self._session, company_id=company_id, case_id=case_id)
        if case is None:
            raise NotFoundError("Resource not found")
        if case.status not in ONBOARDING_CASE_WRITABLE_STATUSES:
            raise OnboardingSectionNotWritableError()

        # O6: a section HR has already verified is locked even if the case's own status
        # (`CHANGES_REQUESTED`) still allows writes to *other* sections (plan §7.2) — checked
        # before writing anything.
        existing_review = await self._section_review_repo.get_by_section(
            self._session, company_id=company_id, case_id=case_id, section=section
        )
        if existing_review is not None and existing_review.status == "VERIFIED":
            raise OnboardingSectionAlreadyVerifiedError()

        # DATA-01 (plan §2.4/§2.5) — encrypt the one sensitive key *before* the JSONB dict is
        # persisted. `case.id` (not a freshly-generated id — this is an update to an existing
        # row) is what AAD binds to; a wizard resubmission overwrites the value under the same
        # AAD, which is correct (it is still the same case's bank_info column).
        if section == "bank_info":
            data = dict(data)
            plaintext = data.get(BANK_INFO_SENSITIVE_KEY)
            if isinstance(plaintext, str):
                data[BANK_INFO_SENSITIVE_KEY] = await self._crypto.encrypt_jsonb_key(
                    self._session,
                    plaintext=plaintext,
                    table="onboarding_case",
                    column="bank_info",
                    jsonb_key=BANK_INFO_SENSITIVE_KEY,
                    record_id=case.id,
                )
        elif section == "personal_info":
            data = dict(data)
            for key in PERSONAL_INFO_SENSITIVE_KEYS:
                plaintext = data.get(key)
                if isinstance(plaintext, str):
                    data[key] = await self._crypto.encrypt_jsonb_key(
                        self._session,
                        plaintext=plaintext,
                        table="onboarding_case",
                        column="personal_info",
                        jsonb_key=key,
                        record_id=case.id,
                    )
        elif section == "nominee_info":
            # Market-parity onboarding-data pass, part 6 — encrypts each item's
            # `aadhaar_number_enc` under its own index-bound AAD (`NOMINEE_INFO_SENSITIVE_ITEM_KEY`
            # docstring). The whole `items` list is always resubmitted and overwritten atomically,
            # so re-encrypting every item on every write (not just changed ones) is correct.
            data = dict(data)
            items = data.get("items")
            if isinstance(items, list):
                encrypted_items = []
                for index, item in enumerate(items):
                    item = dict(item)
                    plaintext = item.get(NOMINEE_INFO_SENSITIVE_ITEM_KEY)
                    if isinstance(plaintext, str):
                        item[NOMINEE_INFO_SENSITIVE_ITEM_KEY] = await self._crypto.encrypt_jsonb_key(
                            self._session,
                            plaintext=plaintext,
                            table="onboarding_case",
                            column="nominee_info",
                            jsonb_key=f"items.{index}.{NOMINEE_INFO_SENSITIVE_ITEM_KEY}",
                            record_id=case.id,
                        )
                    encrypted_items.append(item)
                data["items"] = encrypted_items

        now = datetime.now(UTC)
        updated = await self._repo.update_section(
            self._session,
            company_id=company_id,
            case_id=case_id,
            column=section,
            value=data,
            now=now,
        )
        assert updated is not None

        # O6: editing a section HR had `REJECTED` puts it back in HR's queue as `PENDING`,
        # clearing the stale reason — a no-op if it was never reviewed or is (impossible, per the
        # check above) `VERIFIED`.
        await self._section_review_repo.reset_to_pending(
            self._session, company_id=company_id, case_id=case_id, section=section, now=now
        )
        reviews = await self._section_review_repo.list_for_case(
            self._session, company_id=company_id, case_id=case_id
        )
        return onboarding_case_to_public_read(
            updated,
            reviews,
            bank_info=await self._decrypt_bank_info(updated),
            personal_info=await self._decrypt_personal_info(updated),
            nominee_info=await self._decrypt_nominee_info(updated),
        )

    async def submit_case(self, company_id: UUID, case_id: UUID) -> PublicOnboardingCaseRead:
        """`POST /public/onboarding/{token}/submit` (O4) — `IN_PROGRESS`/`CHANGES_REQUESTED` ->
        `SUBMITTED`. No `actor_user_id` to record (this is the candidate's own action, and the
        candidate has no `User`/employee row yet — there is nothing to attribute the audit entry
        to besides the case itself). Document completeness is not checked (exception docstring)
        — only that all five section columns are non-empty."""
        case = await self._repo.get_case(self._session, company_id=company_id, case_id=case_id)
        if case is None:
            raise NotFoundError("Resource not found")
        if case.status not in ONBOARDING_CASE_WRITABLE_STATUSES:
            raise OnboardingCaseNotSubmittableError()

        missing = [name for name in ONBOARDING_SECTION_NAMES if not getattr(case, name)]
        if missing:
            raise OnboardingIncompleteSectionsError(missing)

        now = datetime.now(UTC)
        await self._repo.set_status(self._session, case=case, status="SUBMITTED", now=now)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=None,
            action="ONBOARDING_CASE_SUBMITTED",
            entity_type="onboarding_case",
            entity_id=case_id,
        )
        reviews = await self._section_review_repo.list_for_case(
            self._session, company_id=company_id, case_id=case_id
        )
        return onboarding_case_to_public_read(
            case,
            reviews,
            bank_info=await self._decrypt_bank_info(case),
            personal_info=await self._decrypt_personal_info(case),
            nominee_info=await self._decrypt_nominee_info(case),
        )


@dataclass(frozen=True)
class OnboardingTokenContext:
    """What a resolved, validated public token proves — deliberately just two IDs (mirrors
    `core.tenancy.context.TenantContext`'s own shape), never a full ORM object, so a route can't
    accidentally read stale case data instead of re-fetching it through the service layer."""

    case_id: UUID
    company_id: UUID


class OnboardingTokenService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._token_repo = OnboardingTokenRepository()
        self._case_repo = OnboardingCaseRepository()
        self._audit = AuditService()

    async def issue_token(
        self, company_id: UUID, case_id: UUID, *, ttl_days: int = DEFAULT_TOKEN_TTL_DAYS
    ) -> str:
        """Mints a new public-link token for the case, revoking any previous live one first
        (plan §4.2), and moves `DRAFT`/`EXPIRED` → `INVITED` (state machine, plan §6) — the same
        transition the O3 send-invite endpoint will trigger; this method already does the full
        state-machine work so O3 only has to add the email-sending wrapper around it, per the
        plan's own phase split (§12: token issuance is O2, the email itself is O3).

        Returns the raw token — the only place it is ever available. Only its SHA-256 hash is
        persisted (plan §8.1); losing this return value means the link must be reissued."""
        case = await self._case_repo.get_case(self._session, company_id=company_id, case_id=case_id)
        if case is None:
            raise NotFoundError("Resource not found")

        now = datetime.now(UTC)
        await self._token_repo.revoke_live_tokens_for_case(self._session, case_id=case_id, now=now)

        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        await self._token_repo.insert_token(
            self._session,
            data={
                "id": uuid4(),
                "company_id": company_id,
                "onboarding_case_id": case_id,
                "token_hash": token_hash,
                "expires_at": now + timedelta(days=ttl_days),
                "created_at": now,
                "updated_at": now,
            },
        )

        if case.status in ("DRAFT", "EXPIRED"):
            await self._case_repo.set_status(self._session, case=case, status="INVITED", now=now)

        return raw_token

    async def resolve_and_touch(self, raw_token: str) -> OnboardingTokenContext:
        """The single security boundary for the entire public surface (plan §5) — every public
        route depends on this. Deliberately raises the same `OnboardingTokenInvalidError` (a
        `404`) for every failure mode (unknown hash, revoked, expired, terminal case status) so a
        response can never let a caller distinguish "this token never existed" from "this token
        existed but is no longer valid", which would otherwise leak information to anyone
        systematically guessing tokens."""
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        token = await self._token_repo.get_by_hash(self._session, token_hash=token_hash)
        if token is None:
            raise OnboardingTokenInvalidError()

        now = datetime.now(UTC)
        if token.revoked_at is not None or token.expires_at <= now:
            raise OnboardingTokenInvalidError()

        # Establishes RLS scope from the token's own server-authored `company_id` (plan §5) —
        # every RLS-protected query from this point on, starting with the very next line, is
        # what actually re-validates that this is a real, correctly-scoped case; a token can
        # never carry a `company_id` that wasn't already true when `issue_token` created it,
        # since that column is never client-writable.
        await set_rls_company_id(self._session, str(token.company_id))
        case = await self._case_repo.get_case(
            self._session, company_id=token.company_id, case_id=token.onboarding_case_id
        )
        # `ACTIVATED` is intentionally *not* blocked here (unlike `EXPIRED`/`CANCELLED`, the rest
        # of `ONBOARDING_CASE_TERMINAL_STATUSES`) — an activated case still resolves so HR can
        # hand back a working link, but every write route below independently checks
        # `ONBOARDING_CASE_WRITABLE_STATUSES` (`update_section`, `submit_case`, `upload_document`,
        # `delete_document`), which excludes `ACTIVATED`, so resolving here never reopens editing.
        if case is None or case.status in ("EXPIRED", "CANCELLED"):
            raise OnboardingTokenInvalidError()

        await self._token_repo.mark_used_first_at(self._session, token=token, now=now)
        if case.status == "INVITED":
            await self._case_repo.set_status(
                self._session, case=case, status="IN_PROGRESS", now=now
            )

        return OnboardingTokenContext(case_id=case.id, company_id=token.company_id)

    async def send_invite(
        self,
        company_id: UUID,
        case_id: UUID,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> OnboardingInviteRead:
        """`POST /onboarding-cases/{id}/send-invite` (O3) — issues/reissues a token via
        `issue_token` (module docstring: that method already does the full state-machine work,
        this just wraps it with the email-sending step the plan's own phase split deferred to
        O3) and emails the resulting link. A failed send never rolls back the token — the link
        is already live and valid the moment it's issued, so HR can always fall back to "Copy
        link" (plan §9) even if delivery failed."""
        case = await self._case_repo.get_case(self._session, company_id=company_id, case_id=case_id)
        if case is None:
            raise NotFoundError("Resource not found")
        if case.status not in ONBOARDING_CASE_INVITABLE_STATUSES:
            raise OnboardingCaseNotInvitableError()

        raw_token = await self.issue_token(company_id, case_id)
        # Re-fetch rather than reuse the `case` object above — `issue_token` may have just
        # transitioned its status (DRAFT/EXPIRED -> INVITED) and the response/audit trail below
        # must reflect that.
        case = await self._case_repo.get_case(self._session, company_id=company_id, case_id=case_id)
        assert case is not None
        invite_url = f"{self._settings.web_app_base_url}/onboarding/{raw_token}"

        # Cross-module read only (`OrganisationService.get_company_profile`), never
        # `.repository`/`.models` directly — same lazy-import convention as
        # `OnboardingCaseService._assert_*_ownership` (Module Standard §2).
        from hrms.modules.organisation.service import OrganisationService

        organisation = OrganisationService(self._session, self._settings)
        company = await organisation.get_company_profile(company_id)

        subject, html_body, text_body = build_invite_email(
            candidate_first_name=case.candidate_first_name,
            company_name=company.name,
            invite_url=invite_url,
        )
        email_sent = True
        try:
            await get_email_sender(self._settings).send(
                to=case.personal_email, subject=subject, html_body=html_body, text_body=text_body
            )
        except Exception:  # noqa: BLE001 — delivery failure must not fail the request, see above
            email_sent = False

        read = onboarding_case_to_read(case)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="ONBOARDING_INVITE_SENT",
            entity_type="onboarding_case",
            entity_id=case_id,
            after={**onboarding_case_to_audit_dict(read), "email_sent": email_sent},
            ip=ip_address,
            user_agent=user_agent,
        )
        return OnboardingInviteRead(case=read, invite_url=invite_url, email_sent=email_sent)


class OnboardingDocumentService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._repo = OnboardingDocumentRepository()
        self._case_repo = OnboardingCaseRepository()
        self._section_review_repo = OnboardingSectionReviewRepository()
        self._storage = DocumentStorageService(self._settings)
        self._audit = AuditService()

    async def upload_document(
        self,
        company_id: UUID,
        case_id: UUID,
        *,
        document_type: str,
        filename: str,
        content_type: str,
        data: bytes,
    ) -> OnboardingDocumentRead:
        """`PENDING` on insert, always — verification is an admin-only action
        (`review_document`). The case must be in a writable status, same gate as
        `OnboardingCaseService.update_section` — uploading a document is just another kind of
        write against the case.

        `content_type` (the client's `UploadFile.content_type`/form header) is accepted for
        interface compatibility but never trusted or persisted (SEC-04) — the stored
        `content_type`, the storage object's own S3 `ContentType`, and the object key's extension
        are all derived from `sniff_document_content_type(data)` instead, which classifies the
        upload from its own magic bytes. A caller claiming `image/jpeg` for an HTML payload (or
        any other mismatch) is rejected outright, not "normalized" — see
        `document_validation.py`'s module docstring for why no source document names an allowed
        type list, and why PDF/JPEG/PNG is this task's own engineering decision."""
        case = await self._case_repo.get_case(self._session, company_id=company_id, case_id=case_id)
        if case is None:
            raise NotFoundError("Resource not found")
        if case.status not in ONBOARDING_CASE_WRITABLE_STATUSES:
            raise OnboardingSectionNotWritableError()
        if document_type not in ONBOARDING_DOCUMENT_TYPES:
            raise InvalidOnboardingDocumentTypeError(document_type)
        if len(data) > ONBOARDING_DOCUMENT_MAX_SIZE_BYTES:
            raise OnboardingDocumentTooLargeError(ONBOARDING_DOCUMENT_MAX_SIZE_BYTES)

        sniffed = sniff_document_content_type(data)
        if sniffed is None:
            raise UnsupportedDocumentContentError()
        sniffed_content_type, extension = sniffed
        display_filename = sanitize_display_filename(filename)

        now = datetime.now(UTC)
        document_id = uuid4()
        s3_key = safe_document_object_key(
            company_id=company_id, case_id=case_id, document_id=document_id, extension=extension
        )
        await self._storage.put_object(key=s3_key, body=data, content_type=sniffed_content_type)

        document = await self._repo.insert_document(
            self._session,
            data={
                "id": document_id,
                "company_id": company_id,
                "onboarding_case_id": case_id,
                "document_type": document_type,
                "s3_key": s3_key,
                "original_filename": display_filename,
                "content_type": sniffed_content_type,
                "size_bytes": len(data),
                "status": "PENDING",
                "uploaded_at": now,
                "created_at": now,
                "updated_at": now,
            },
        )
        return onboarding_document_to_read(document)

    async def list_documents(self, company_id: UUID, case_id: UUID) -> list[OnboardingDocumentRead]:
        """The candidate-facing list (no presigned URL — the candidate already has the file;
        they only need to see what's already uploaded, e.g. to decide whether to replace it)."""
        documents = await self._repo.list_documents(
            self._session, company_id=company_id, case_id=case_id
        )
        return [onboarding_document_to_read(document) for document in documents]

    async def list_documents_with_urls(
        self, company_id: UUID, case_id: UUID
    ) -> list[OnboardingDocumentWithUrlRead]:
        """The admin-facing list — a presigned GET URL per document so bytes never round-trip
        through the API server (plan §8.3)."""
        case = await self._case_repo.get_case(self._session, company_id=company_id, case_id=case_id)
        if case is None:
            raise NotFoundError("Resource not found")
        documents = await self._repo.list_documents(
            self._session, company_id=company_id, case_id=case_id
        )
        result = []
        for document in documents:
            url = await self._storage.presigned_get_url(
                key=document.s3_key,
                response_content_disposition=content_disposition_attachment(
                    document.original_filename
                ),
            )
            result.append(onboarding_document_to_read_with_url(document, url))
        return result

    async def delete_document(self, company_id: UUID, case_id: UUID, document_id: UUID) -> None:
        case = await self._case_repo.get_case(self._session, company_id=company_id, case_id=case_id)
        if case is None:
            raise NotFoundError("Resource not found")
        if case.status not in ONBOARDING_CASE_WRITABLE_STATUSES:
            raise OnboardingSectionNotWritableError()

        document = await self._repo.get_document(
            self._session, company_id=company_id, case_id=case_id, document_id=document_id
        )
        if document is None:
            raise NotFoundError("Resource not found")

        await self._storage.delete_object(key=document.s3_key)
        await self._repo.delete_document(self._session, document=document)

    async def review_document(
        self,
        company_id: UUID,
        case_id: UUID,
        document_id: UUID,
        *,
        status: str,
        rejection_reason: str | None,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> OnboardingDocumentRead:
        """No case-status gate of its own — unlike section review (`OnboardingReviewService.
        review_section`), HR may spot-check a document the moment it's uploaded, before the
        candidate has even finished the rest of the wizard (module docstring). `_ensure_case_
        under_review`/`_maybe_auto_verify_case` (O6) are both safe to call unconditionally: they
        only ever act when the case is actually `SUBMITTED`/`UNDER_REVIEW`, a no-op otherwise."""
        case = await self._case_repo.get_case(self._session, company_id=company_id, case_id=case_id)
        if case is None:
            raise NotFoundError("Resource not found")

        document = await self._repo.get_document(
            self._session, company_id=company_id, case_id=case_id, document_id=document_id
        )
        if document is None:
            raise NotFoundError("Resource not found")

        now = datetime.now(UTC)
        await _ensure_case_under_review(self._case_repo, self._session, case, now)

        updated = await self._repo.update_review(
            self._session,
            document=document,
            status=status,
            rejection_reason=rejection_reason,
            verified_by_user_id=actor_user_id,
            now=now,
        )
        read = onboarding_document_to_read(updated)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="ONBOARDING_DOCUMENT_REVIEWED",
            entity_type="onboarding_document",
            entity_id=document_id,
            after=read.model_dump(mode="json"),
            ip=ip_address,
            user_agent=user_agent,
        )

        await _maybe_auto_verify_case(
            self._session,
            case_repo=self._case_repo,
            section_review_repo=self._section_review_repo,
            document_repo=self._repo,
            company_id=company_id,
            case=case,
            now=now,
        )
        return read


class OnboardingReviewService:
    """O6 — section review and the changes-requested loop. Kept separate from
    `OnboardingCaseService` (which owns the case's own CRUD/section-write surface) the same way
    `OnboardingTokenService`/`OnboardingDocumentService` are each their own class — one service
    per distinct write surface, per this module's own established convention."""

    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._case_repo = OnboardingCaseRepository()
        self._section_review_repo = OnboardingSectionReviewRepository()
        self._document_repo = OnboardingDocumentRepository()
        self._audit = AuditService()

    async def review_section(
        self,
        company_id: UUID,
        case_id: UUID,
        section: str,
        *,
        status: str,
        rejection_reason: str | None,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> OnboardingSectionReviewRead:
        if section not in ONBOARDING_SECTION_NAMES:
            raise InvalidOnboardingSectionError(section)

        case = await self._case_repo.get_case(self._session, company_id=company_id, case_id=case_id)
        if case is None:
            raise NotFoundError("Resource not found")
        if case.status not in ONBOARDING_CASE_REVIEWABLE_STATUSES:
            raise OnboardingCaseNotReviewableError()

        now = datetime.now(UTC)
        await _ensure_case_under_review(self._case_repo, self._session, case, now)

        review = await self._section_review_repo.upsert_review(
            self._session,
            company_id=company_id,
            case_id=case_id,
            section=section,
            status=status,
            rejection_reason=rejection_reason,
            reviewed_by_user_id=actor_user_id,
            now=now,
        )
        read = onboarding_section_review_to_read(review)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="ONBOARDING_SECTION_REVIEWED",
            entity_type="onboarding_section_review",
            entity_id=review.id,
            after=read.model_dump(mode="json"),
            ip=ip_address,
            user_agent=user_agent,
        )

        await _maybe_auto_verify_case(
            self._session,
            case_repo=self._case_repo,
            section_review_repo=self._section_review_repo,
            document_repo=self._document_repo,
            company_id=company_id,
            case=case,
            now=now,
        )
        return read

    async def request_changes(
        self,
        company_id: UUID,
        case_id: UUID,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> OnboardingCaseRead:
        """`POST /onboarding-cases/{id}/request-changes` (plan §7.1) — HR reviews every section/
        document first (`review_section`/`OnboardingDocumentService.review_document`, each just
        recording a verdict), then calls this once to finalize the batch: `UNDER_REVIEW` ->
        `CHANGES_REQUESTED` and the candidate is notified in a single email, rather than once per
        individual rejection."""
        case = await self._case_repo.get_case(self._session, company_id=company_id, case_id=case_id)
        if case is None:
            raise NotFoundError("Resource not found")
        if case.status != "UNDER_REVIEW":
            raise OnboardingNothingToRequestChangesForError()

        sections = await self._section_review_repo.list_for_case(
            self._session, company_id=company_id, case_id=case_id
        )
        documents = await self._document_repo.list_documents(
            self._session, company_id=company_id, case_id=case_id
        )
        rejected_sections = [s for s in sections if s.status == "REJECTED"]
        rejected_documents = [d for d in documents if d.status == "REJECTED"]
        if not rejected_sections and not rejected_documents:
            raise OnboardingNothingToRequestChangesForError()

        now = datetime.now(UTC)
        await self._case_repo.set_status(
            self._session, case=case, status="CHANGES_REQUESTED", now=now
        )

        rejected_items = [
            (ONBOARDING_SECTION_LABELS[s.section], s.rejection_reason or "")
            for s in rejected_sections
        ] + [(f"Document: {d.document_type}", d.rejection_reason or "") for d in rejected_documents]

        # Cross-module read only (`OrganisationService.get_company_profile`), same lazy-import
        # convention as `OnboardingTokenService.send_invite`.
        from hrms.modules.organisation.service import OrganisationService

        organisation = OrganisationService(self._session, self._settings)
        company = await organisation.get_company_profile(company_id)
        subject, html_body, text_body = build_changes_requested_email(
            candidate_first_name=case.candidate_first_name,
            company_name=company.name,
            rejected_items=rejected_items,
        )
        try:
            await get_email_sender(self._settings).send(
                to=case.personal_email, subject=subject, html_body=html_body, text_body=text_body
            )
        except Exception:  # noqa: BLE001 — delivery failure must not block the status transition
            pass

        read = onboarding_case_to_read(case)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="ONBOARDING_CHANGES_REQUESTED",
            entity_type="onboarding_case",
            entity_id=case_id,
            after=onboarding_case_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read


class OnboardingActivationService:
    """O7 — the transaction that turns a fully-verified onboarding case into a real employee.
    Composes the employee module's own already-validated services
    (`EmployeeService`/`EmploymentService`/`EmployeeAssignmentService`/`EmployeeBankService`/
    `EmployeeStatutoryService`/`EmployeeCompensationService`/`EmployeeExperienceService`/
    `EmployeeEducationService`) rather than writing to
    `hrms.modules.employee.repository`/`.models` directly (Module Standard §2) —
    every field-level rule those services already enforce (seat limits, employee codes, the
    assignment/employment/statutory/bank/compensation overlap constraints,
    `AssignmentFieldsRequiredError` for a missing branch/department/designation) is inherited
    for free, not re-implemented here (plan §8.6's own point). Compensation was listed here from
    the start but had no section to source CTC from until E-02 (market-parity onboarding-data
    pass, part 3) added `compensation_info`; Experience is new as of part 4
    (`previous_employment_info`) — unlike every other sub-resource composed here, it may create
    zero, one, or several rows per activation, one per listed past employer.

    No explicit transaction management — `hrms.core.db.session.get_session` already commits only
    once the whole request succeeds and rolls back on any raised exception (every write below
    shares that one request-scoped session), which is exactly the "single DB transaction" plan
    §8.6 asks for."""

    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._case_repo = OnboardingCaseRepository()
        self._audit = AuditService()
        self._crypto = PiiCryptoService(self._settings)

    async def _decrypt_bank_info(self, case: "OnboardingCase") -> dict[str, Any]:
        """Same contract as `OnboardingCaseService._decrypt_bank_info` — duplicated rather than
        shared across the two service classes (this module keeps each O-phase's service class
        self-contained, matching the existing convention of `OnboardingCaseService`/
        `OnboardingTokenService`/`OnboardingDocumentService`/`OnboardingReviewService`/
        `OnboardingActivationService` never depending on each other's internals)."""
        bank_info = dict(case.bank_info)
        ciphertext = bank_info.get(BANK_INFO_SENSITIVE_KEY)
        if isinstance(ciphertext, str):
            bank_info[BANK_INFO_SENSITIVE_KEY] = await self._crypto.decrypt_jsonb_key(
                self._session,
                ciphertext=ciphertext,
                table="onboarding_case",
                column="bank_info",
                jsonb_key=BANK_INFO_SENSITIVE_KEY,
                record_id=case.id,
            )
        return bank_info

    async def _decrypt_personal_info(self, case: "OnboardingCase") -> dict[str, Any]:
        """Same contract as `OnboardingCaseService._decrypt_personal_info` — duplicated for the
        same reason `_decrypt_bank_info` is duplicated above (each O-phase service class stays
        self-contained)."""
        personal_info = dict(case.personal_info)
        for key in PERSONAL_INFO_SENSITIVE_KEYS:
            ciphertext = personal_info.get(key)
            if isinstance(ciphertext, str):
                personal_info[key] = await self._crypto.decrypt_jsonb_key(
                    self._session,
                    ciphertext=ciphertext,
                    table="onboarding_case",
                    column="personal_info",
                    jsonb_key=key,
                    record_id=case.id,
                )
        return personal_info

    async def _decrypt_nominee_info(self, case: "OnboardingCase") -> dict[str, Any]:
        """Same contract as `OnboardingCaseService._decrypt_nominee_info` — duplicated for the
        same reason `_decrypt_bank_info` is duplicated above (each O-phase service class stays
        self-contained)."""
        nominee_info = dict(case.nominee_info)
        items = nominee_info.get("items")
        if not isinstance(items, list):
            return nominee_info
        decrypted_items = []
        for index, item in enumerate(items):
            item = dict(item)
            ciphertext = item.get(NOMINEE_INFO_SENSITIVE_ITEM_KEY)
            if isinstance(ciphertext, str):
                item[NOMINEE_INFO_SENSITIVE_ITEM_KEY] = await self._crypto.decrypt_jsonb_key(
                    self._session,
                    ciphertext=ciphertext,
                    table="onboarding_case",
                    column="nominee_info",
                    jsonb_key=f"items.{index}.{NOMINEE_INFO_SENSITIVE_ITEM_KEY}",
                    record_id=case.id,
                )
            decrypted_items.append(item)
        nominee_info["items"] = decrypted_items
        return nominee_info

    async def activate_case(
        self,
        company_id: UUID,
        case_id: UUID,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> OnboardingCaseRead:
        case = await self._case_repo.get_case(self._session, company_id=company_id, case_id=case_id)
        if case is None:
            raise NotFoundError("Resource not found")
        if case.status != "VERIFIED":
            raise OnboardingCaseNotReadyForActivationError()
        if case.legal_entity_id is None:
            raise OnboardingCaseMissingLegalEntityError()

        # Cross-module writes only through the employee module's own public service surface,
        # imported lazily — same convention as every other cross-module call in this module
        # (`_assert_*_ownership`, `send_invite`'s `OrganisationService` lookup).
        from hrms.modules.employee.schemas import (
            AssignmentCreate,
            BankCreate,
            CompensationCreate,
            EmployeeCreate,
            EmployeeDependentCreate,
            EmployeeEducationCreate,
            EmployeeExperienceCreate,
            EmployeeIdentityUpdate,
            EmploymentCreate,
            StatutoryCreate,
        )
        from hrms.modules.employee.service import (
            EmployeeAssignmentService,
            EmployeeBankService,
            EmployeeCompensationService,
            EmployeeDependentService,
            EmployeeEducationService,
            EmployeeExperienceService,
            EmployeeService,
            EmployeeStatutoryService,
            EmploymentService,
        )

        employee_service = EmployeeService(self._session, self._settings)
        employment_service = EmploymentService(self._session, self._settings)
        assignment_service = EmployeeAssignmentService(self._session, self._settings)
        bank_service = EmployeeBankService(self._session, self._settings)
        compensation_service = EmployeeCompensationService(self._session, self._settings)
        statutory_service = EmployeeStatutoryService(self._session, self._settings)
        experience_service = EmployeeExperienceService(self._session, self._settings)
        education_service = EmployeeEducationService(self._session, self._settings)
        dependent_service = EmployeeDependentService(self._session, self._settings)

        # E-02 — `pan_number_enc`/`aadhaar_number_enc` are deliberately not `EmployeeCreate`
        # fields (schemas.py module docstring: gated by `.UPDATE_SENSITIVE`/`.VIEW_SENSITIVE` via
        # the dedicated identity sub-resource, never the general create/update surface), so they
        # are stripped out here and handled separately, below, via `update_identity` — the same
        # decrypt-then-re-encrypt handoff `bank_info` already uses for its own sensitive key.
        personal_info_for_employee = {
            key: value
            for key, value in case.personal_info.items()
            if key not in PERSONAL_INFO_SENSITIVE_KEYS
        }

        # `personal_info` never carries `personal_email`/`personal_mobile` — those are owned by
        # the case record itself, set by HR at creation (schemas.py module docstring) — merged
        # back in only now, at the one point that actually needs the complete `EmployeeCreate`.
        # `address_info`/`emergency_contact` (E-02 part 2) are folded in the same way — both are
        # optional sections (an empty dict when the candidate never filled them in), so their
        # mapped fields are simply all-`None`/default in that case, matching every other
        # optional-section guard in this method (`if case.bank_info:` etc., below).
        employee = await employee_service.create_employee(
            company_id,
            EmployeeCreate(
                **personal_info_for_employee,
                personal_email=case.personal_email,
                personal_mobile=case.personal_mobile,
                **_address_info_to_employee_fields(case.address_info),
                **_emergency_contact_to_employee_fields(case.emergency_contact),
            ),
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        # E-02 — PAN/Aadhaar (case-level ciphertext, decrypted here) and UAN (plain, sourced from
        # `statutory_info` since Form 11's own KYC block is what collects it) land on the new
        # `Employee` row via the same identity sub-resource a later HR edit would use. Skipped
        # entirely when the candidate never entered any of the three — `update_identity` treats
        # an all-`None` patch as a no-op, but there is no reason to even call it.
        decrypted_personal_info = await self._decrypt_personal_info(case)
        identity_patch: dict[str, str] = {}
        if decrypted_personal_info.get("pan_number_enc"):
            identity_patch["pan_number"] = decrypted_personal_info["pan_number_enc"]
        if decrypted_personal_info.get("aadhaar_number_enc"):
            identity_patch["aadhaar_number"] = decrypted_personal_info["aadhaar_number_enc"]
        uan_number = case.statutory_info.get("uan_number") if case.statutory_info else None
        if uan_number:
            identity_patch["uan_number"] = uan_number
        if identity_patch:
            await employee_service.update_identity(
                company_id,
                employee.id,
                EmployeeIdentityUpdate(**identity_patch),
                expected_version=employee.version,
                actor_user_id=actor_user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )

        # `scope=None`/`caller_employee_id=None` throughout: activation is a system-initiated
        # action with no acting employee's own visibility to narrow against — the same
        # "pre-data-scope exists-only" mode every non-route caller of these services already
        # uses (`EmployeeService._assert_employee_visible`'s own docstring).
        await employment_service.create_employment(
            company_id,
            employee.id,
            EmploymentCreate(
                legal_entity_id=case.legal_entity_id, joining_date=case.proposed_joining_date
            ),
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        await assignment_service.create_assignment(
            company_id,
            employee.id,
            AssignmentCreate(
                effective_from=case.proposed_joining_date,
                change_type="INITIAL",
                branch_id=case.branch_id,
                department_id=case.department_id,
                designation_id=case.designation_id,
            ),
            expected_version=None,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        # `effective_from` is computed here from `proposed_joining_date`, never carried in
        # `bank_info`/`statutory_info` themselves (those sections deliberately exclude it,
        # schemas.py). Both are optional — `submit_case` (O4) requires the section be non-empty,
        # but never made collecting bank/statutory details itself mandatory at case level; an
        # empty dict here just means the candidate's case had nothing to activate for that
        # sub-resource, which matches `OnboardingIncompleteSectionsError`'s own long-standing
        # "never made mandatory" stance.
        if case.bank_info:
            # DATA-01 (plan §2.4/§9) — `case.bank_info["account_number_enc"]` is ciphertext,
            # bound by AAD to `onboarding_case:bank_info.account_number_enc:{case.id}` (plan
            # §2.4). It must be decrypted back to plaintext here, before `BankCreate` is built —
            # never passed through as-is, which would hand `EmployeeBankService.create_bank` an
            # already-encrypted string to re-encrypt as if it were plaintext (double-encryption,
            # and a value nothing could ever decrypt correctly again). `create_bank` then
            # re-encrypts it under the *new* `employee_bank` row's own AAD (plan §9's
            # "decrypt-then-re-encrypt handoff").
            decrypted_bank_info = await self._decrypt_bank_info(case)
            await bank_service.create_bank(
                company_id,
                employee.id,
                BankCreate(effective_from=case.proposed_joining_date, **decrypted_bank_info),
                expected_version=None,
                actor_user_id=actor_user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )

        if case.statutory_info:
            # E-02 — `uan_number` lives on `Employee.uan_number` (handled above, via
            # `update_identity`), never duplicated onto `EmployeeStatutory`
            # (`EmployeeStatutory` model docstring's own "deliberately excludes uan" rule) — so
            # it is stripped out here before `StatutoryCreate` is built, same reasoning as
            # `personal_info_for_employee` above.
            statutory_info_for_employee = {
                key: value for key, value in case.statutory_info.items() if key != "uan_number"
            }
            await statutory_service.create_statutory(
                company_id,
                employee.id,
                StatutoryCreate(
                    effective_from=case.proposed_joining_date,
                    revision_reason="Initial statutory profile captured during onboarding",
                    **statutory_info_for_employee,
                ),
                expected_version=None,
                actor_user_id=actor_user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )

        # E-02 (market-parity onboarding-data pass, part 3) — closes the gap this class's own
        # docstring named: `EmployeeCompensation` was listed among the services composed here,
        # but no call was ever wired up. Same guarded-optional-section shape as bank/statutory
        # above; `revision_type`/`revision_reason` are activation's own fixed values, mirroring
        # how `StatutoryCreate.revision_reason` is filled in above rather than sourced from the
        # candidate.
        if case.compensation_info:
            await compensation_service.create_compensation(
                company_id,
                employee.id,
                CompensationCreate(
                    effective_from=case.proposed_joining_date,
                    revision_type="JOINING",
                    revision_reason="Initial compensation captured during onboarding",
                    **case.compensation_info,
                ),
                expected_version=None,
                actor_user_id=actor_user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )

        # Market-parity onboarding-data pass, part 4 — one `EmployeeExperience` row per past
        # employer the candidate listed. `previous_employment_info` is `{"items": [...]}` (see
        # `PreviousEmploymentSection`'s docstring); an empty or never-filled-in list yields zero
        # rows, the same "optional section" posture as bank/statutory/compensation above.
        for item in case.previous_employment_info.get("items", []):
            await experience_service.create_experience(
                company_id,
                employee.id,
                EmployeeExperienceCreate(**item),
                actor_user_id=actor_user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )

        # Market-parity onboarding-data pass, part 5 — one `EmployeeEducation` row per
        # qualification the candidate listed, same optional-list shape as Experience above.
        for item in case.education_info.get("items", []):
            await education_service.create_education(
                company_id,
                employee.id,
                EmployeeEducationCreate(**item),
                actor_user_id=actor_user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )

        # Market-parity onboarding-data pass, part 6 — one `EmployeeDependent` row per nominee/
        # family member the candidate listed, same optional-list shape as Experience/Education
        # above. `case.nominee_info["items"]` ciphertext is decrypted here (each item's own
        # index-bound AAD, `NOMINEE_INFO_SENSITIVE_ITEM_KEY` docstring), then
        # `EmployeeDependentService.create_dependent` re-encrypts it under the *new*
        # `employee_dependent` row's own AAD — the same decrypt-then-re-encrypt handoff `bank_info`
        # already uses.
        decrypted_nominee_info = await self._decrypt_nominee_info(case)
        for item in decrypted_nominee_info.get("items", []):
            await dependent_service.create_dependent(
                company_id,
                employee.id,
                EmployeeDependentCreate(**item),
                actor_user_id=actor_user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )

        now = datetime.now(UTC)
        case.employee_id = employee.id
        await self._case_repo.set_status(self._session, case=case, status="ACTIVATED", now=now)

        # Cross-module read only, same lazy-import convention as `send_invite`.
        from hrms.modules.organisation.service import OrganisationService

        organisation = OrganisationService(self._session, self._settings)
        company = await organisation.get_company_profile(company_id)
        subject, html_body, text_body = build_activated_email(
            candidate_first_name=case.candidate_first_name,
            company_name=company.name,
            employee_code=employee.employee_code,
        )
        try:
            await get_email_sender(self._settings).send(
                to=case.personal_email, subject=subject, html_body=html_body, text_body=text_body
            )
        except Exception:  # noqa: BLE001 — delivery failure must not undo the activation
            pass

        # Account-invite auto-issue — Decision P2 path 1 (`docs/modules/employee/
        # 41_EMPLOYEE_ACCOUNT_PROVISIONING_LOGIN_AUDIT_AND_PLAN.md`). Best-effort, same as the
        # activation email above: a failure here (including "no actor" for a system-triggered
        # activation) must never undo an activation that has already committed its Employee row.
        if actor_user_id is not None:
            try:
                from hrms.modules.account_invite.service import AccountInviteService

                await AccountInviteService(self._session, self._settings).issue_for_employee(
                    company_id,
                    employee.id,
                    actor_user_id=actor_user_id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
            except Exception:  # noqa: BLE001 — must not undo the activation
                pass

        read = onboarding_case_to_read(case)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="ONBOARDING_CASE_ACTIVATED",
            entity_type="onboarding_case",
            entity_id=case_id,
            after=onboarding_case_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read
