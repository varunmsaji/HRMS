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
from hrms.core.db.session import set_rls_company_id
from hrms.core.errors.base import NotFoundError
from hrms.modules.onboarding.document_storage import DocumentStorageService
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
    InvalidLegalEntityReferenceError,
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
)
from hrms.modules.onboarding.repository import (
    OnboardingCaseRepository,
    OnboardingDocumentRepository,
    OnboardingSectionReviewRepository,
    OnboardingTokenRepository,
)
from hrms.modules.onboarding.schemas import (
    ONBOARDING_CASE_REVIEWABLE_STATUSES,
    ONBOARDING_CASE_TERMINAL_STATUSES,
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
#: Everything past `IN_PROGRESS` has either already submitted (a fresh link would let the
#: candidate bypass review) or is terminal (nothing left to invite);
#: `CHANGES_REQUESTED`'s own reopen-and-resend flow belongs to O6, not this endpoint.
ONBOARDING_CASE_INVITABLE_STATUSES = ("DRAFT", "EXPIRED", "INVITED", "IN_PROGRESS")

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


class OnboardingCaseService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._repo = OnboardingCaseRepository()
        self._section_review_repo = OnboardingSectionReviewRepository()
        self._audit = AuditService()

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

    async def _assert_branch_ownership(self, company_id: UUID, branch_id: UUID) -> None:
        from hrms.modules.organisation.service import OrganisationService

        organisation = OrganisationService(self._session, self._settings)
        try:
            await organisation.get_branch(company_id, branch_id)
        except NotFoundError as exc:
            raise InvalidBranchReferenceError() from exc

    async def _assert_legal_entity_ownership(self, company_id: UUID, legal_entity_id: UUID) -> None:
        from hrms.modules.organisation.service import OrganisationService

        organisation = OrganisationService(self._session, self._settings)
        try:
            await organisation.get_legal_entity(company_id, legal_entity_id)
        except NotFoundError as exc:
            raise InvalidLegalEntityReferenceError() from exc

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
        if body.branch_id is not None:
            await self._assert_branch_ownership(company_id, body.branch_id)
        if body.legal_entity_id is not None:
            await self._assert_legal_entity_ownership(company_id, body.legal_entity_id)

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
                "legal_entity_id": body.legal_entity_id,
                "proposed_joining_date": body.proposed_joining_date,
                "created_by_user_id": actor_user_id,
                "personal_info": {},
                "address_info": {},
                "emergency_contact": {},
                "bank_info": {},
                "statutory_info": {},
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
        return onboarding_case_to_detail_read(case, reviews)

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
        return onboarding_case_to_public_read(case, reviews)

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
        return onboarding_case_to_public_read(updated, reviews)

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
        return onboarding_case_to_public_read(case, reviews)


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
        case = await self._case_repo.get_case(
            self._session, company_id=company_id, case_id=case_id
        )
        if case is None:
            raise NotFoundError("Resource not found")

        now = datetime.now(UTC)
        await self._token_repo.revoke_live_tokens_for_case(
            self._session, case_id=case_id, now=now
        )

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
            await self._case_repo.set_status(
                self._session, case=case, status="INVITED", now=now
            )

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
        if case is None or case.status in ONBOARDING_CASE_TERMINAL_STATUSES:
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
        write against the case."""
        case = await self._case_repo.get_case(self._session, company_id=company_id, case_id=case_id)
        if case is None:
            raise NotFoundError("Resource not found")
        if case.status not in ONBOARDING_CASE_WRITABLE_STATUSES:
            raise OnboardingSectionNotWritableError()
        if document_type not in ONBOARDING_DOCUMENT_TYPES:
            raise InvalidOnboardingDocumentTypeError(document_type)
        if len(data) > ONBOARDING_DOCUMENT_MAX_SIZE_BYTES:
            raise OnboardingDocumentTooLargeError(ONBOARDING_DOCUMENT_MAX_SIZE_BYTES)

        now = datetime.now(UTC)
        document_id = uuid4()
        s3_key = f"onboarding/{company_id}/{case_id}/{document_id}/{filename}"
        await self._storage.put_object(key=s3_key, body=data, content_type=content_type)

        document = await self._repo.insert_document(
            self._session,
            data={
                "id": document_id,
                "company_id": company_id,
                "onboarding_case_id": case_id,
                "document_type": document_type,
                "s3_key": s3_key,
                "original_filename": filename,
                "content_type": content_type,
                "size_bytes": len(data),
                "status": "PENDING",
                "uploaded_at": now,
                "created_at": now,
                "updated_at": now,
            },
        )
        return onboarding_document_to_read(document)

    async def list_documents(
        self, company_id: UUID, case_id: UUID
    ) -> list[OnboardingDocumentRead]:
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
            url = await self._storage.presigned_get_url(key=document.s3_key)
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
    `EmployeeStatutoryService`) rather than writing to `hrms.modules.employee.repository`/
    `.models` directly (Module Standard §2) — every field-level rule those services already
    enforce (seat limits, employee codes, the assignment/employment/statutory/bank overlap
    constraints, `AssignmentFieldsRequiredError` for a missing branch/department/designation) is
    inherited for free, not re-implemented here (plan §8.6's own point).

    No explicit transaction management — `hrms.core.db.session.get_session` already commits only
    once the whole request succeeds and rolls back on any raised exception (every write below
    shares that one request-scoped session), which is exactly the "single DB transaction" plan
    §8.6 asks for."""

    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._case_repo = OnboardingCaseRepository()
        self._audit = AuditService()

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
            EmployeeCreate,
            EmploymentCreate,
            StatutoryCreate,
        )
        from hrms.modules.employee.service import (
            EmployeeAssignmentService,
            EmployeeBankService,
            EmployeeService,
            EmployeeStatutoryService,
            EmploymentService,
        )

        employee_service = EmployeeService(self._session, self._settings)
        employment_service = EmploymentService(self._session, self._settings)
        assignment_service = EmployeeAssignmentService(self._session, self._settings)
        bank_service = EmployeeBankService(self._session, self._settings)
        statutory_service = EmployeeStatutoryService(self._session, self._settings)

        # `personal_info` never carries `personal_email`/`personal_mobile` — those are owned by
        # the case record itself, set by HR at creation (schemas.py module docstring) — merged
        # back in only now, at the one point that actually needs the complete `EmployeeCreate`.
        employee = await employee_service.create_employee(
            company_id,
            EmployeeCreate(
                **case.personal_info,
                personal_email=case.personal_email,
                personal_mobile=case.personal_mobile,
            ),
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
            await bank_service.create_bank(
                company_id,
                employee.id,
                BankCreate(effective_from=case.proposed_joining_date, **case.bank_info),
                expected_version=None,
                actor_user_id=actor_user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )

        if case.statutory_info:
            await statutory_service.create_statutory(
                company_id,
                employee.id,
                StatutoryCreate(
                    effective_from=case.proposed_joining_date,
                    revision_reason="Initial statutory profile captured during onboarding",
                    **case.statutory_info,
                ),
                expected_version=None,
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
