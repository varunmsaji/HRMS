"""Business logic for the onboarding module — O1 (case create/list/detail) only."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.audit.service import AuditService
from hrms.core.config.settings import Settings, get_settings
from hrms.core.errors.base import NotFoundError
from hrms.modules.onboarding.exceptions import (
    DuplicateActiveOnboardingCaseError,
    InvalidBranchReferenceError,
    InvalidDepartmentReferenceError,
    InvalidDesignationReferenceError,
    InvalidLegalEntityReferenceError,
)
from hrms.modules.onboarding.repository import OnboardingCaseRepository
from hrms.modules.onboarding.schemas import (
    OnboardingCaseCreate,
    OnboardingCaseRead,
    onboarding_case_to_audit_dict,
    onboarding_case_to_read,
)


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
