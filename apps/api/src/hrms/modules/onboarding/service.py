"""Business logic for the onboarding module — O1 (case create/list/detail) and O2 (token
issuance + public section read/write)."""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.audit.service import AuditService
from hrms.core.config.settings import Settings, get_settings
from hrms.core.db.session import set_rls_company_id
from hrms.core.errors.base import NotFoundError
from hrms.modules.onboarding.exceptions import (
    DuplicateActiveOnboardingCaseError,
    InvalidBranchReferenceError,
    InvalidDepartmentReferenceError,
    InvalidDesignationReferenceError,
    InvalidLegalEntityReferenceError,
    OnboardingSectionNotWritableError,
    OnboardingTokenInvalidError,
)
from hrms.modules.onboarding.repository import OnboardingCaseRepository, OnboardingTokenRepository
from hrms.modules.onboarding.schemas import (
    ONBOARDING_CASE_TERMINAL_STATUSES,
    ONBOARDING_CASE_WRITABLE_STATUSES,
    OnboardingCaseCreate,
    OnboardingCaseRead,
    PublicOnboardingCaseRead,
    onboarding_case_to_audit_dict,
    onboarding_case_to_public_read,
    onboarding_case_to_read,
)

#: Default public-link lifetime (plan §4.2: "default 7 days, HR-configurable per case at
#: send/resend time" — the per-case override arrives with the O3 send-invite endpoint; this
#: constant is O2's own default, used directly since nothing yet calls `issue_token` with a
#: caller-supplied override).
DEFAULT_TOKEN_TTL_DAYS = 7


class OnboardingCaseService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._repo = OnboardingCaseRepository()
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

    async def get_public_case(self, company_id: UUID, case_id: UUID) -> PublicOnboardingCaseRead:
        """Called only after `OnboardingTokenService.resolve_and_touch` has already proven the
        token is live and set the RLS `company_id` GUC from it — `company_id`/`case_id` here
        come from that resolved, server-side context, never from client input (module docstring,
        `hrms.modules.onboarding.public_router`)."""
        case = await self._repo.get_case(self._session, company_id=company_id, case_id=case_id)
        if case is None:
            raise NotFoundError("Resource not found")
        return onboarding_case_to_public_read(case)

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
        return onboarding_case_to_public_read(updated)


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
