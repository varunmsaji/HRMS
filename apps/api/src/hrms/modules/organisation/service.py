"""Business logic for the organisation module — the public interface for other modules."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.audit.service import AuditService
from hrms.core.auth.passwords import hash_password, is_password_strong_enough
from hrms.core.config.settings import Settings, get_settings
from hrms.core.db.repositories.identity import IdentityRepository
from hrms.core.db.session import set_rls_company_id
from hrms.core.errors.base import ConflictError, NotFoundError, ValidationError
from hrms.modules.identity.schemas import CompanySummary, TokenResponseData
from hrms.modules.identity.service import IdentityService
from hrms.modules.organisation.exceptions import (
    BranchDeactivationBlockedError,
    CompanyWriteBlockedError,
    CurrencyLockedError,
    DepartmentCycleDetectedError,
    DepartmentMaxDepthExceededError,
    GradeCodeAlreadyExistsError,
    InvalidBranchError,
    InvalidCtcRangeError,
    InvalidDepartmentError,
    InvalidGradeError,
    InvalidLegalEntityError,
    InvalidParentDepartmentError,
    InvalidWorkingDaysError,
    LegalEntityDeactivationBlockedError,
    StaleResourceError,
)
from hrms.modules.organisation.permissions import (
    DASHBOARD_COMPANY_VIEW,
    ORG_BRANCH_MANAGE,
    ORG_COMPANY_MANAGE,
    ORG_DEPARTMENT_MANAGE,
    ORG_DESIGNATION_MANAGE,
    ORG_GRADE_MANAGE,
    ORG_LEGAL_ENTITY_MANAGE,
)
from hrms.modules.organisation.repository import OrganisationRepository
from hrms.modules.organisation.schemas import (
    BranchCreate,
    BranchRead,
    BranchUpdate,
    CompanyDashboardSummary,
    CompanyProfileRead,
    CompanyProfileUpdate,
    CompanyRegistrationRequest,
    CompanySetupProgressSummary,
    DashboardSetupProgress,
    DashboardSubscription,
    DepartmentCreate,
    DepartmentRead,
    DepartmentUpdate,
    DesignationCreate,
    DesignationRead,
    DesignationUpdate,
    FeatureFlagView,
    GradeCreate,
    GradeRead,
    GradeUpdate,
    LegalEntityCreate,
    LegalEntityRead,
    LegalEntityUpdate,
    PlanSummary,
    SetupStepDefinition,
    SetupStepSummary,
    SubscriptionSummary,
    branch_to_audit_dict,
    branch_to_read,
    build_branch_update_values,
    build_department_update_values,
    build_designation_update_values,
    build_grade_update_values,
    build_legal_entity_update_values,
    build_update_values,
    company_to_profile_read,
    count_working_days,
    department_to_audit_dict,
    department_to_read,
    designation_to_audit_dict,
    designation_to_read,
    grade_to_audit_dict,
    grade_to_read,
    legal_entity_to_audit_dict,
    legal_entity_to_read,
    profile_to_audit_dict,
    setup_progress_to_summary,
)
from hrms.seed.plan_catalogue import SEAT_LIMIT_FEATURE_CODE

# No explicit trial length is defined anywhere in the frozen Company docs — 14 days is an
# assumed, easily-changed default (common SaaS convention), not a sourced product decision.
TRIAL_PERIOD_DAYS = 14

# No `Plan.is_default` flag exists (frozen schema, C-05). "FREE" is treated as the default
# trial plan because it is the only catalogue entry whose own description says "for
# evaluating the platform" (`hrms/seed/plan_catalogue.py`) — the closest match to "trial."
DEFAULT_TRIAL_PLAN_CODE = "FREE"

COMPANY_ADMIN_ROLE_CODE = "COMPANY_ADMIN"

# FR-ORG-005 — department hierarchy is capped at 5 levels (root = depth 1).
DEPARTMENT_MAX_DEPTH = 5

# Extensibility point (05_Backend_Architecture.md §3.1): Company owns this registry and the
# aggregation loop in `get_setup_progress`, never the predicate logic for a sibling step once
# one exists — e.g. a future `SetupStepDefinition(code="BRANCHES", ..., check=lambda repo,
# session, cid: repo.branch_count(session, company_id=cid) > 0)` would live in a Branch-owned
# repository method, appended here without touching the aggregation loop below.
SETUP_STEPS: list[SetupStepDefinition] = [
    SetupStepDefinition(
        code="COMPANY_PROFILE",
        label="Company Profile",
        check=lambda repo, session, company_id: repo.company_profile_is_complete(
            session, company_id=company_id
        ),
    ),
]


class OrganisationService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._repo = OrganisationRepository()
        self._identity_repo = IdentityRepository()
        self._identity = IdentityService(session, self._settings)
        self._audit = AuditService()

    async def register_company(
        self,
        body: CompanyRegistrationRequest,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> TokenResponseData:
        if not is_password_strong_enough(body.admin_password):
            raise ValidationError(
                "Password does not meet minimum strength requirements",
                details=[
                    {
                        "field": "admin_password",
                        "code": "WEAK_PASSWORD",
                        "message": "Password must be at least 8 characters and include "
                        "both a letter and a digit",
                    }
                ],
            )

        admin_email = body.admin_email.lower()
        existing_user = await self._identity_repo.get_user_by_email(self._session, admin_email)
        if existing_user is not None:
            raise ConflictError("An account with this email already exists")

        now = datetime.now(UTC)
        user_id = uuid4()
        company_id = uuid4()

        # Set the RLS tenant variable for this new company before touching any RLS-bearing
        # table (`company_setup_progress`, `subscription`, `audit_log`) — there is no
        # pre-existing tenant context for a public registration request.
        await set_rls_company_id(self._session, str(company_id))

        try:
            await self._repo.insert_user(
                self._session,
                user_id=user_id,
                email=admin_email,
                password_hash=hash_password(body.admin_password),
                first_name=body.admin_first_name,
                last_name=body.admin_last_name,
                now=now,
            )
        except IntegrityError as exc:
            # The pre-check above is racy by construction — `user.email` carries a real DB
            # unique index (`user_email_key`, scripts/sql/001_init_schema.sql) that is the
            # actual backstop for two concurrent registrations with the same email.
            raise ConflictError("An account with this email already exists") from exc

        trial_ends_at = now + timedelta(days=TRIAL_PERIOD_DAYS)
        company = await self._repo.insert_company(
            self._session,
            data={
                "id": company_id,
                "name": body.name,
                "industry_code": body.industry_code,
                "country_code": body.country_code,
                "currency": body.currency,
                "timezone": body.timezone,
                "fy_start_month": body.fy_start_month,
                "company_size": body.company_size,
                "status": "TRIAL",
                "trial_ends_at": trial_ends_at,
                "created_by": user_id,
                "updated_by": user_id,
                "created_at": now,
                "updated_at": now,
            },
        )

        user_company = await self._repo.insert_user_company(
            self._session,
            user_id=user_id,
            company_id=company_id,
            is_primary=True,
            now=now,
        )

        org_manage_perm = await self._repo.get_or_create_permission(
            self._session,
            code=ORG_COMPANY_MANAGE,
            domain="ORG",
            description="Manage company settings",
        )
        dashboard_view_perm = await self._repo.get_or_create_permission(
            self._session,
            code=DASHBOARD_COMPANY_VIEW,
            domain="DASHBOARD",
            description="View company dashboard",
        )
        legal_entity_manage_perm = await self._repo.get_or_create_permission(
            self._session,
            code=ORG_LEGAL_ENTITY_MANAGE,
            domain="ORG",
            description="Manage legal entities",
        )
        branch_manage_perm = await self._repo.get_or_create_permission(
            self._session,
            code=ORG_BRANCH_MANAGE,
            domain="ORG",
            description="Manage branches",
        )
        department_manage_perm = await self._repo.get_or_create_permission(
            self._session,
            code=ORG_DEPARTMENT_MANAGE,
            domain="ORG",
            description="Manage departments",
        )
        designation_manage_perm = await self._repo.get_or_create_permission(
            self._session,
            code=ORG_DESIGNATION_MANAGE,
            domain="ORG",
            description="Manage designations",
        )
        grade_manage_perm = await self._repo.get_or_create_permission(
            self._session,
            code=ORG_GRADE_MANAGE,
            domain="ORG",
            description="Manage grades",
        )

        role = await self._repo.insert_role(
            self._session,
            company_id=company_id,
            code=COMPANY_ADMIN_ROLE_CODE,
            name="Company Administrator",
            is_system=True,
            now=now,
        )
        await self._repo.insert_role_permission(
            self._session, role_id=role.id, permission_id=org_manage_perm.id
        )
        await self._repo.insert_role_permission(
            self._session, role_id=role.id, permission_id=dashboard_view_perm.id
        )
        await self._repo.insert_role_permission(
            self._session, role_id=role.id, permission_id=legal_entity_manage_perm.id
        )
        await self._repo.insert_role_permission(
            self._session, role_id=role.id, permission_id=branch_manage_perm.id
        )
        await self._repo.insert_role_permission(
            self._session, role_id=role.id, permission_id=department_manage_perm.id
        )
        await self._repo.insert_role_permission(
            self._session, role_id=role.id, permission_id=designation_manage_perm.id
        )
        await self._repo.insert_role_permission(
            self._session, role_id=role.id, permission_id=grade_manage_perm.id
        )
        await self._repo.insert_user_role(
            self._session, user_company_id=user_company.id, role_id=role.id
        )

        await self._repo.insert_setup_progress(self._session, company_id=company_id, now=now)

        plan = await self._repo.get_plan_by_code(self._session, code=DEFAULT_TRIAL_PLAN_CODE)
        if plan is not None:
            await self._repo.insert_subscription(
                self._session,
                company_id=company_id,
                plan_id=plan.id,
                status="TRIALING",
                trial_ends_at=trial_ends_at,
                now=now,
            )

        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=user_id,
            action="COMPANY_REGISTERED",
            entity_type="company",
            entity_id=company_id,
            ip=ip_address,
            user_agent=user_agent,
        )

        return await self._identity.issue_tokens_for(
            user_id=user_id,
            company_id=company_id,
            companies=[CompanySummary(id=company_id, name=company.name, is_primary=True)],
            ip_address=ip_address,
            user_agent=user_agent,
            audit_action="COMPANY_REGISTERED",
        )

    async def get_company_profile(self, company_id: UUID) -> CompanyProfileRead:
        company = await self._repo.get_company(self._session, company_id=company_id)
        if company is None:
            raise NotFoundError("Resource not found")
        return company_to_profile_read(company)

    async def update_company_profile(
        self,
        company_id: UUID,
        patch: CompanyProfileUpdate,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> CompanyProfileRead:
        company = await self._repo.get_company(self._session, company_id=company_id)
        if company is None:
            raise NotFoundError("Resource not found")

        if company.status == "SUSPENDED":
            raise CompanyWriteBlockedError()

        before_profile = company_to_profile_read(company)
        before_json = profile_to_audit_dict(before_profile)

        if patch.currency is not None and patch.currency != company.currency:
            if company.status != "TRIAL":
                raise CurrencyLockedError()

        if patch.timezone is not None and patch.timezone != company.timezone:
            self._assert_timezone_change_allowed(company_id, company.timezone, patch.timezone)

        if count_working_days(company, patch) < 1:
            raise InvalidWorkingDaysError()

        values = build_update_values(company, patch)
        if not values:
            return before_profile

        now = datetime.now(UTC)
        updated = await self._repo.update_company(
            self._session,
            company_id=company_id,
            values=values,
            expected_version=expected_version,
            updated_by=actor_user_id,
            now=now,
        )
        if updated is None:
            current = await self._repo.get_company(self._session, company_id=company_id)
            if current is None:
                raise NotFoundError("Resource not found")
            current_profile = company_to_profile_read(current)
            raise StaleResourceError(
                "The company profile has been modified by another request",
                current=profile_to_audit_dict(current_profile),
            )

        after_profile = company_to_profile_read(updated)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="UPDATED",
            entity_type="company",
            entity_id=company_id,
            before=before_json,
            after=profile_to_audit_dict(after_profile),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_profile

    def _assert_timezone_change_allowed(
        self,
        company_id: UUID,
        current_timezone: str,
        new_timezone: str,
    ) -> None:
        """Documented no-op hook until Payroll/Attendance modules exist (Domain Model §5.5)."""
        _ = (company_id, current_timezone, new_timezone)

    async def get_setup_progress(self, company_id: UUID) -> CompanySetupProgressSummary:
        progress = await self._repo.get_setup_progress(self._session, company_id=company_id)
        if progress is None:
            # This resource always exists once a company does (created at registration,
            # see 04_API_Design.md §5) — reaching here would indicate a data-integrity bug,
            # not a normal client error, mirroring get_company_profile's own NotFoundError use.
            raise NotFoundError("Resource not found")
        # Captured before `update_setup_progress` runs below: that bulk UPDATE
        # auto-synchronizes the session's identity map, mutating this same
        # already-loaded `progress` instance in place — reading `.status` off it
        # afterwards would silently observe the *new* value, not the prior one.
        previous_status = progress.status
        previous_completed_at = progress.completed_at

        completed_codes = [
            step.code
            for step in SETUP_STEPS
            if await step.check(self._repo, self._session, company_id)
        ]
        all_complete = len(completed_codes) == len(SETUP_STEPS)
        status = "COMPLETE" if all_complete else "IN_PROGRESS"
        # current_step is a UX hint only, never gates access (Domain Model §2.2) — derived
        # here as the first incomplete step, since no wizard-navigation endpoint exists to
        # set it explicitly in V1.
        current_step = next(
            (step.code for step in SETUP_STEPS if step.code not in completed_codes), None
        )

        now = datetime.now(UTC)
        completed_at = now if all_complete else None
        if all_complete and previous_status == "COMPLETE":
            completed_at = previous_completed_at

        updated = await self._repo.update_setup_progress(
            self._session,
            company_id=company_id,
            steps_completed=completed_codes,
            current_step=current_step,
            status=status,
            completed_at=completed_at,
            now=now,
        )

        if all_complete and previous_status != "COMPLETE":
            await self._repo.mark_company_onboarded(
                self._session, company_id=company_id, onboarded_at=now
            )

        steps = [
            SetupStepSummary(
                code=step.code, label=step.label, is_complete=step.code in completed_codes
            )
            for step in SETUP_STEPS
        ]
        return setup_progress_to_summary(updated, steps)

    async def get_subscription_summary(self, company_id: UUID) -> SubscriptionSummary:
        """Resolve live plan + effective feature flags (04_API_Design.md §6).

        Feature resolution (Domain Model §5.10):
        - Plan features seed the effective set with ``source=PLAN``.
        - ``overrides_plan=true`` company flags win even when the plan lacks the feature
          (``source=COMPANY_OVERRIDE``).
        - ``overrides_plan=false`` company flags may only toggle features already on the
          plan; orphans are ignored on read (write-time rejection is out of scope until a
          feature-flag write API exists).
        """
        subscription = await self._repo.get_active_subscription(
            self._session, company_id=company_id
        )
        if subscription is None:
            raise NotFoundError("Resource not found")

        plan = await self._repo.get_plan(self._session, plan_id=subscription.plan_id)
        if plan is None:
            raise NotFoundError("Resource not found")

        plan_features = await self._repo.get_plan_features(self._session, plan_id=plan.id)
        company_flags = await self._repo.get_company_feature_flags(
            self._session, company_id=company_id
        )

        features_by_code: dict[str, FeatureFlagView] = {}
        plan_seat_limit: int | None = None

        for feature in plan_features:
            features_by_code[feature.feature_code] = FeatureFlagView(
                code=feature.feature_code,
                is_enabled=feature.is_enabled,
                source="PLAN",
                limit_value=feature.limit_value,
            )
            if feature.feature_code == SEAT_LIMIT_FEATURE_CODE:
                plan_seat_limit = feature.limit_value

        for flag in company_flags:
            if flag.overrides_plan:
                existing = features_by_code.get(flag.feature_code)
                features_by_code[flag.feature_code] = FeatureFlagView(
                    code=flag.feature_code,
                    is_enabled=flag.is_enabled,
                    source="COMPANY_OVERRIDE",
                    limit_value=existing.limit_value if existing is not None else None,
                )
            elif flag.feature_code in features_by_code:
                existing = features_by_code[flag.feature_code]
                features_by_code[flag.feature_code] = FeatureFlagView(
                    code=flag.feature_code,
                    is_enabled=flag.is_enabled,
                    source="PLAN",
                    limit_value=existing.limit_value,
                )

        seat_limit = (
            subscription.seat_limit_override
            if subscription.seat_limit_override is not None
            else plan_seat_limit
        )

        return SubscriptionSummary(
            plan=PlanSummary(code=plan.code, name=plan.name),
            status=subscription.status,
            current_period_start=_format_optional_timestamp(subscription.current_period_start),
            current_period_end=_format_optional_timestamp(subscription.current_period_end),
            trial_ends_at=_format_optional_timestamp(subscription.trial_ends_at),
            seat_limit=seat_limit,
            features=sorted(features_by_code.values(), key=lambda item: item.code),
        )

    async def get_dashboard_summary(self, company_id: UUID) -> CompanyDashboardSummary:
        """Company Admin dashboard aggregation (04_API_Design.md §7).

        Sibling counts (branches / departments / employees) stay ``null`` until those
        modules exist — never fabricated ``0``.
        """
        setup = await self.get_setup_progress(company_id)
        steps_completed = sum(1 for step in setup.steps if step.is_complete)

        subscription_block: DashboardSubscription | None = None
        try:
            subscription = await self.get_subscription_summary(company_id)
            subscription_block = DashboardSubscription(
                plan_code=subscription.plan.code,
                status=subscription.status,
                trial_ends_at=subscription.trial_ends_at,
            )
        except NotFoundError:
            subscription_block = None

        return CompanyDashboardSummary(
            setup_progress=DashboardSetupProgress(
                status=setup.status,
                steps_completed=steps_completed,
                steps_total=len(setup.steps),
            ),
            subscription=subscription_block,
            branch_count=None,
            department_count=None,
            employee_count=None,
        )

    async def create_legal_entity(
        self,
        company_id: UUID,
        body: LegalEntityCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> LegalEntityRead:
        now = datetime.now(UTC)
        entity_id = uuid4()
        entity = await self._repo.insert_legal_entity(
            self._session,
            data={
                "id": entity_id,
                "company_id": company_id,
                "name": body.name,
                "registered_address": body.registered_address,
                "pan": body.pan,
                "tan": body.tan,
                "cin": body.cin,
                "gstin": body.gstin,
                "pf_code": body.pf_code,
                "esi_code": body.esi_code,
                "lwf_reg": body.lwf_reg,
                "signatory_name": body.signatory_name,
                "signatory_designation": body.signatory_designation,
                "signature_image_url": body.signature_image_url,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
        )
        read = legal_entity_to_read(entity)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="LEGAL_ENTITY_CREATED",
            entity_type="legal_entity",
            entity_id=entity_id,
            after=legal_entity_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def list_legal_entities(self, company_id: UUID) -> list[LegalEntityRead]:
        entities = await self._repo.list_legal_entities(self._session, company_id=company_id)
        return [legal_entity_to_read(entity) for entity in entities]

    async def get_legal_entity(self, company_id: UUID, entity_id: UUID) -> LegalEntityRead:
        entity = await self._repo.get_legal_entity(
            self._session, company_id=company_id, entity_id=entity_id
        )
        if entity is None:
            raise NotFoundError("Resource not found")
        return legal_entity_to_read(entity)

    async def update_legal_entity(
        self,
        company_id: UUID,
        entity_id: UUID,
        patch: LegalEntityUpdate,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> LegalEntityRead:
        entity = await self._repo.get_legal_entity(
            self._session, company_id=company_id, entity_id=entity_id
        )
        if entity is None:
            raise NotFoundError("Resource not found")

        before_read = legal_entity_to_read(entity)
        # Captured before `update_legal_entity` runs below: that `UPDATE ... RETURNING`
        # auto-synchronizes the session's identity map, mutating this same already-loaded
        # `entity` instance in place (same gotcha documented on `update_setup_progress`
        # above) — reading `.is_active` off it afterwards would silently observe the *new*
        # value, not the prior one.
        was_active_before = entity.is_active

        deactivating = patch.is_active is False and was_active_before is True
        if deactivating:
            active_branches = await self._repo.count_active_branches_for_legal_entity(
                self._session, entity_id=entity_id
            )
            if active_branches > 0:
                raise LegalEntityDeactivationBlockedError(active_branch_count=active_branches)

        values = build_legal_entity_update_values(patch)
        if not values:
            return before_read

        now = datetime.now(UTC)
        updated = await self._repo.update_legal_entity(
            self._session,
            company_id=company_id,
            entity_id=entity_id,
            values=values,
            expected_version=expected_version,
            now=now,
        )
        if updated is None:
            current = await self._repo.get_legal_entity(
                self._session, company_id=company_id, entity_id=entity_id
            )
            if current is None:
                raise NotFoundError("Resource not found")
            current_read = legal_entity_to_read(current)
            raise StaleResourceError(
                "This legal entity has been modified by another request",
                current=legal_entity_to_audit_dict(current_read),
            )

        after_read = legal_entity_to_read(updated)
        action = (
            "LEGAL_ENTITY_DEACTIVATED"
            if deactivating
            else "LEGAL_ENTITY_REACTIVATED"
            if patch.is_active is True and was_active_before is False
            else "LEGAL_ENTITY_UPDATED"
        )
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action=action,
            entity_type="legal_entity",
            entity_id=entity_id,
            before=legal_entity_to_audit_dict(before_read),
            after=legal_entity_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    async def deactivate_legal_entity(
        self,
        company_id: UUID,
        entity_id: UUID,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> LegalEntityRead:
        """Semantic wrapper around `update_legal_entity` for `DELETE /legal-entities/{id}` —
        never a hard delete (FR-ORG-014); flips `is_active` to False via the same
        business-rule path (blocked-branch check, audit, optimistic concurrency)."""
        return await self.update_legal_entity(
            company_id,
            entity_id,
            LegalEntityUpdate(is_active=False),
            expected_version=expected_version,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def _assert_legal_entity_ownership(self, company_id: UUID, legal_entity_id: UUID) -> None:
        """A Branch may only reference a Legal Entity that exists and belongs to the same
        tenant — the FK constraint alone would surface an opaque `IntegrityError`/500 for
        a bad id, and would not catch a cross-tenant reference at all (RLS would just make
        the FK lookup fail the same way as a nonexistent id, which is the desired 422)."""
        entity = await self._repo.get_legal_entity(
            self._session, company_id=company_id, entity_id=legal_entity_id
        )
        if entity is None:
            raise InvalidLegalEntityError()

    async def create_branch(
        self,
        company_id: UUID,
        body: BranchCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> BranchRead:
        await self._assert_legal_entity_ownership(company_id, body.legal_entity_id)

        now = datetime.now(UTC)
        branch_id = uuid4()
        branch = await self._repo.insert_branch(
            self._session,
            data={
                "id": branch_id,
                "company_id": company_id,
                "legal_entity_id": body.legal_entity_id,
                "name": body.name,
                "code": body.code,
                "address_line1": body.address_line1,
                "address_line2": body.address_line2,
                "city": body.city,
                "state_code": body.state_code,
                "pincode": body.pincode,
                "timezone": body.timezone,
                "latitude": body.latitude,
                "longitude": body.longitude,
                "geofence_radius_m": body.geofence_radius_m,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
        )
        read = branch_to_read(branch)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="BRANCH_CREATED",
            entity_type="branch",
            entity_id=branch_id,
            after=branch_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def list_branches(self, company_id: UUID) -> list[BranchRead]:
        branches = await self._repo.list_branches(self._session, company_id=company_id)
        return [branch_to_read(branch) for branch in branches]

    async def get_branch(self, company_id: UUID, branch_id: UUID) -> BranchRead:
        branch = await self._repo.get_branch(
            self._session, company_id=company_id, branch_id=branch_id
        )
        if branch is None:
            raise NotFoundError("Resource not found")
        return branch_to_read(branch)

    async def update_branch(
        self,
        company_id: UUID,
        branch_id: UUID,
        patch: BranchUpdate,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> BranchRead:
        branch = await self._repo.get_branch(
            self._session, company_id=company_id, branch_id=branch_id
        )
        if branch is None:
            raise NotFoundError("Resource not found")

        if patch.legal_entity_id is not None:
            await self._assert_legal_entity_ownership(company_id, patch.legal_entity_id)

        before_read = branch_to_read(branch)
        # Captured before `update_branch` runs below: that `UPDATE ... RETURNING`
        # auto-synchronizes the session's identity map, mutating this same already-loaded
        # `branch` instance in place (same gotcha documented on `update_legal_entity`) —
        # reading `.is_active` off it afterwards would silently observe the *new* value.
        was_active_before = branch.is_active

        deactivating = patch.is_active is False and was_active_before is True
        if deactivating:
            active_departments = await self._repo.count_active_departments_for_branch(
                self._session, branch_id=branch_id
            )
            if active_departments > 0:
                raise BranchDeactivationBlockedError(active_department_count=active_departments)

        values = build_branch_update_values(patch)
        if not values:
            return before_read

        now = datetime.now(UTC)
        updated = await self._repo.update_branch(
            self._session,
            company_id=company_id,
            branch_id=branch_id,
            values=values,
            expected_version=expected_version,
            now=now,
        )
        if updated is None:
            current = await self._repo.get_branch(
                self._session, company_id=company_id, branch_id=branch_id
            )
            if current is None:
                raise NotFoundError("Resource not found")
            current_read = branch_to_read(current)
            raise StaleResourceError(
                "This branch has been modified by another request",
                current=branch_to_audit_dict(current_read),
            )

        after_read = branch_to_read(updated)
        action = (
            "BRANCH_DEACTIVATED"
            if deactivating
            else "BRANCH_REACTIVATED"
            if patch.is_active is True and was_active_before is False
            else "BRANCH_UPDATED"
        )
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action=action,
            entity_type="branch",
            entity_id=branch_id,
            before=branch_to_audit_dict(before_read),
            after=branch_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    async def deactivate_branch(
        self,
        company_id: UUID,
        branch_id: UUID,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> BranchRead:
        """Semantic wrapper around `update_branch` for `DELETE /branches/{id}` — never a
        hard delete (FR-ORG-014); flips `is_active` to False via the same business-rule
        path (blocked-department check, audit, optimistic concurrency)."""
        return await self.update_branch(
            company_id,
            branch_id,
            BranchUpdate(is_active=False),
            expected_version=expected_version,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def _assert_branch_ownership(self, company_id: UUID, branch_id: UUID) -> None:
        """A Department's `branch_id`, when provided, must belong to the same tenant —
        mirrors `_assert_legal_entity_ownership` for Branch's own `legal_entity_id`."""
        branch = await self._repo.get_branch(
            self._session, company_id=company_id, branch_id=branch_id
        )
        if branch is None:
            raise InvalidBranchError()

    async def _validate_department_parent(
        self, company_id: UUID, own_id: UUID | None, parent_id: UUID
    ) -> None:
        """FR-ORG-005 — hierarchy must reject cycles and cap depth at
        `DEPARTMENT_MAX_DEPTH`. `own_id` is `None` on create (a brand-new department can
        never already be its own ancestor)."""
        if own_id is not None and parent_id == own_id:
            raise DepartmentCycleDetectedError()

        parent = await self._repo.get_department(
            self._session, company_id=company_id, department_id=parent_id
        )
        if parent is None:
            raise InvalidParentDepartmentError()

        ancestor_chain = await self._repo.get_department_ancestor_chain(
            self._session, company_id=company_id, start_id=parent_id
        )
        if own_id is not None and own_id in ancestor_chain:
            raise DepartmentCycleDetectedError()
        if len(ancestor_chain) >= DEPARTMENT_MAX_DEPTH:
            raise DepartmentMaxDepthExceededError()

    async def create_department(
        self,
        company_id: UUID,
        body: DepartmentCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> DepartmentRead:
        if body.branch_id is not None:
            await self._assert_branch_ownership(company_id, body.branch_id)
        if body.parent_id is not None:
            await self._validate_department_parent(company_id, None, body.parent_id)

        now = datetime.now(UTC)
        department_id = uuid4()
        department = await self._repo.insert_department(
            self._session,
            data={
                "id": department_id,
                "company_id": company_id,
                "branch_id": body.branch_id,
                "parent_id": body.parent_id,
                "name": body.name,
                "code": body.code,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
        )
        read = department_to_read(department)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="DEPARTMENT_CREATED",
            entity_type="department",
            entity_id=department_id,
            after=department_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def list_departments(self, company_id: UUID) -> list[DepartmentRead]:
        departments = await self._repo.list_departments(self._session, company_id=company_id)
        return [department_to_read(department) for department in departments]

    async def get_department(self, company_id: UUID, department_id: UUID) -> DepartmentRead:
        department = await self._repo.get_department(
            self._session, company_id=company_id, department_id=department_id
        )
        if department is None:
            raise NotFoundError("Resource not found")
        return department_to_read(department)

    async def update_department(
        self,
        company_id: UUID,
        department_id: UUID,
        patch: DepartmentUpdate,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> DepartmentRead:
        department = await self._repo.get_department(
            self._session, company_id=company_id, department_id=department_id
        )
        if department is None:
            raise NotFoundError("Resource not found")

        if patch.branch_id is not None:
            await self._assert_branch_ownership(company_id, patch.branch_id)
        if patch.parent_id is not None:
            await self._validate_department_parent(company_id, department_id, patch.parent_id)

        before_read = department_to_read(department)
        # Captured before `update_department` runs below: that `UPDATE ... RETURNING`
        # auto-synchronizes the session's identity map, mutating this same already-loaded
        # `department` instance in place (same gotcha documented on `update_branch`) —
        # reading `.is_active` off it afterwards would silently observe the *new* value.
        was_active_before = department.is_active

        # No documented dependency-blocking rule applies to Department deactivation this
        # slice (FR-ORG-014's only named blocker — active employees — can't be checked
        # since Employee doesn't exist; no doc names sub-departments/Designations as
        # blockers either, unlike Branch's own explicit "blocked by active department"
        # gloss). See docs/modules/department/00_DEPARTMENT_AUDIT.md §5.3/§8.1.
        deactivating = patch.is_active is False and was_active_before is True

        values = build_department_update_values(patch)
        if not values:
            return before_read

        now = datetime.now(UTC)
        updated = await self._repo.update_department(
            self._session,
            company_id=company_id,
            department_id=department_id,
            values=values,
            expected_version=expected_version,
            now=now,
        )
        if updated is None:
            current = await self._repo.get_department(
                self._session, company_id=company_id, department_id=department_id
            )
            if current is None:
                raise NotFoundError("Resource not found")
            current_read = department_to_read(current)
            raise StaleResourceError(
                "This department has been modified by another request",
                current=department_to_audit_dict(current_read),
            )

        after_read = department_to_read(updated)
        action = (
            "DEPARTMENT_DEACTIVATED"
            if deactivating
            else "DEPARTMENT_REACTIVATED"
            if patch.is_active is True and was_active_before is False
            else "DEPARTMENT_UPDATED"
        )
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action=action,
            entity_type="department",
            entity_id=department_id,
            before=department_to_audit_dict(before_read),
            after=department_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    async def deactivate_department(
        self,
        company_id: UUID,
        department_id: UUID,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> DepartmentRead:
        """Semantic wrapper around `update_department` for `DELETE /departments/{id}` —
        never a hard delete (FR-ORG-014); flips `is_active` to False via the same
        business-rule path (audit, optimistic concurrency)."""
        return await self.update_department(
            company_id,
            department_id,
            DepartmentUpdate(is_active=False),
            expected_version=expected_version,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def _assert_department_ownership(self, company_id: UUID, department_id: UUID) -> None:
        """A Designation's `department_id`, when provided, must belong to the same tenant —
        mirrors `_assert_branch_ownership` for Designation's own `department_id`."""
        department = await self._repo.get_department(
            self._session, company_id=company_id, department_id=department_id
        )
        if department is None:
            raise InvalidDepartmentError()

    async def _assert_grade_ownership(self, company_id: UUID, grade_id: UUID) -> None:
        """A Designation's `grade_id`, when provided, must belong to the same tenant —
        mirrors `_assert_department_ownership` for Designation's own `department_id`. See
        docs/modules/grade/00_GRADE_AUDIT.md §3/§6.7."""
        grade = await self._repo.get_grade(self._session, company_id=company_id, grade_id=grade_id)
        if grade is None:
            raise InvalidGradeError()

    async def create_designation(
        self,
        company_id: UUID,
        body: DesignationCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> DesignationRead:
        if body.department_id is not None:
            await self._assert_department_ownership(company_id, body.department_id)
        if body.grade_id is not None:
            await self._assert_grade_ownership(company_id, body.grade_id)

        now = datetime.now(UTC)
        designation_id = uuid4()
        designation = await self._repo.insert_designation(
            self._session,
            data={
                "id": designation_id,
                "company_id": company_id,
                "department_id": body.department_id,
                "grade_id": body.grade_id,
                "title": body.title,
                "code": body.code,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
        )
        read = designation_to_read(designation)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="DESIGNATION_CREATED",
            entity_type="designation",
            entity_id=designation_id,
            after=designation_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def list_designations(self, company_id: UUID) -> list[DesignationRead]:
        designations = await self._repo.list_designations(self._session, company_id=company_id)
        return [designation_to_read(designation) for designation in designations]

    async def get_designation(self, company_id: UUID, designation_id: UUID) -> DesignationRead:
        designation = await self._repo.get_designation(
            self._session, company_id=company_id, designation_id=designation_id
        )
        if designation is None:
            raise NotFoundError("Resource not found")
        return designation_to_read(designation)

    async def update_designation(
        self,
        company_id: UUID,
        designation_id: UUID,
        patch: DesignationUpdate,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> DesignationRead:
        designation = await self._repo.get_designation(
            self._session, company_id=company_id, designation_id=designation_id
        )
        if designation is None:
            raise NotFoundError("Resource not found")

        if patch.department_id is not None:
            await self._assert_department_ownership(company_id, patch.department_id)
        if patch.grade_id is not None:
            await self._assert_grade_ownership(company_id, patch.grade_id)

        before_read = designation_to_read(designation)
        # Captured before `update_designation` runs below: that `UPDATE ... RETURNING`
        # auto-synchronizes the session's identity map, mutating this same already-loaded
        # `designation` instance in place (same gotcha documented on `update_department`) —
        # reading `.is_active` off it afterwards would silently observe the *new* value.
        was_active_before = designation.is_active

        # No documented dependency-blocking rule applies to Designation deactivation this
        # slice (FR-ORG-014's only named blocker — active employees — can't be checked
        # since Employee doesn't exist; the only other named blocker, a
        # `next_designation_id` career-path reference, is not implementable this slice
        # since `next_designation_id` itself has no UI control — see
        # docs/modules/designation/00_DESIGNATION_AUDIT.md §5.3/§5.4).
        deactivating = patch.is_active is False and was_active_before is True

        values = build_designation_update_values(patch)
        if not values:
            return before_read

        now = datetime.now(UTC)
        updated = await self._repo.update_designation(
            self._session,
            company_id=company_id,
            designation_id=designation_id,
            values=values,
            expected_version=expected_version,
            now=now,
        )
        if updated is None:
            current = await self._repo.get_designation(
                self._session, company_id=company_id, designation_id=designation_id
            )
            if current is None:
                raise NotFoundError("Resource not found")
            current_read = designation_to_read(current)
            raise StaleResourceError(
                "This designation has been modified by another request",
                current=designation_to_audit_dict(current_read),
            )

        after_read = designation_to_read(updated)
        action = (
            "DESIGNATION_DEACTIVATED"
            if deactivating
            else "DESIGNATION_REACTIVATED"
            if patch.is_active is True and was_active_before is False
            else "DESIGNATION_UPDATED"
        )
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action=action,
            entity_type="designation",
            entity_id=designation_id,
            before=designation_to_audit_dict(before_read),
            after=designation_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    async def deactivate_designation(
        self,
        company_id: UUID,
        designation_id: UUID,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> DesignationRead:
        """Semantic wrapper around `update_designation` for `DELETE /designations/{id}` —
        never a hard delete (FR-ORG-014); flips `is_active` to False via the same
        business-rule path (audit, optimistic concurrency)."""
        return await self.update_designation(
            company_id,
            designation_id,
            DesignationUpdate(is_active=False),
            expected_version=expected_version,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    def _validate_ctc_range(self, min_ctc: int | None, max_ctc: int | None) -> None:
        """Sprint 3 Task 3.3.1's own documented rule: `min_ctc <= max_ctc` when both are
        present (docs/modules/grade/00_GRADE_AUDIT.md §6.4)."""
        if min_ctc is not None and max_ctc is not None and min_ctc > max_ctc:
            raise InvalidCtcRangeError()

    async def create_grade(
        self,
        company_id: UUID,
        body: GradeCreate,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> GradeRead:
        self._validate_ctc_range(body.min_ctc, body.max_ctc)

        now = datetime.now(UTC)
        grade_id = uuid4()
        try:
            grade = await self._repo.insert_grade(
                self._session,
                data={
                    "id": grade_id,
                    "company_id": company_id,
                    "code": body.code,
                    "name": body.name,
                    "level": body.level,
                    "min_ctc": body.min_ctc,
                    "max_ctc": body.max_ctc,
                    "notice_period_days": body.notice_period_days,
                    "probation_days": body.probation_days,
                    "approval_limit": body.approval_limit,
                    "is_active": True,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        except IntegrityError as exc:
            # `grade_company_id_code_key UNIQUE (company_id, code)` predates this slice
            # (scripts/sql/001_init_schema.sql) — the real backstop for a race between two
            # concurrent creates with the same code, same pattern as `register_company`'s
            # duplicate-email handling.
            raise GradeCodeAlreadyExistsError() from exc

        read = grade_to_read(grade)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="GRADE_CREATED",
            entity_type="grade",
            entity_id=grade_id,
            after=grade_to_audit_dict(read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return read

    async def list_grades(self, company_id: UUID) -> list[GradeRead]:
        grades = await self._repo.list_grades(self._session, company_id=company_id)
        return [grade_to_read(grade) for grade in grades]

    async def get_grade(self, company_id: UUID, grade_id: UUID) -> GradeRead:
        grade = await self._repo.get_grade(self._session, company_id=company_id, grade_id=grade_id)
        if grade is None:
            raise NotFoundError("Resource not found")
        return grade_to_read(grade)

    async def update_grade(
        self,
        company_id: UUID,
        grade_id: UUID,
        patch: GradeUpdate,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> GradeRead:
        grade = await self._repo.get_grade(self._session, company_id=company_id, grade_id=grade_id)
        if grade is None:
            raise NotFoundError("Resource not found")

        effective_min = patch.min_ctc if "min_ctc" in patch.model_fields_set else grade.min_ctc
        effective_max = patch.max_ctc if "max_ctc" in patch.model_fields_set else grade.max_ctc
        self._validate_ctc_range(effective_min, effective_max)

        before_read = grade_to_read(grade)
        # Captured before `update_grade` runs below: that `UPDATE ... RETURNING`
        # auto-synchronizes the session's identity map, mutating this same already-loaded
        # `grade` instance in place (same gotcha documented on `update_designation`) —
        # reading `.is_active` off it afterwards would silently observe the *new* value.
        was_active_before = grade.is_active

        # No documented dependency-blocking rule applies to Grade deactivation this slice
        # (FR-ORG-014's only named blocker — active employees — can't be checked since
        # Employee doesn't exist; no document names an active Designation referencing a
        # Grade as a blocker either — see docs/modules/grade/00_GRADE_AUDIT.md §6.3).
        deactivating = patch.is_active is False and was_active_before is True

        values = build_grade_update_values(patch)
        if not values:
            return before_read

        now = datetime.now(UTC)
        try:
            updated = await self._repo.update_grade(
                self._session,
                company_id=company_id,
                grade_id=grade_id,
                values=values,
                expected_version=expected_version,
                now=now,
            )
        except IntegrityError as exc:
            raise GradeCodeAlreadyExistsError() from exc
        if updated is None:
            current = await self._repo.get_grade(
                self._session, company_id=company_id, grade_id=grade_id
            )
            if current is None:
                raise NotFoundError("Resource not found")
            current_read = grade_to_read(current)
            raise StaleResourceError(
                "This grade has been modified by another request",
                current=grade_to_audit_dict(current_read),
            )

        after_read = grade_to_read(updated)
        action = (
            "GRADE_DEACTIVATED"
            if deactivating
            else "GRADE_REACTIVATED"
            if patch.is_active is True and was_active_before is False
            else "GRADE_UPDATED"
        )
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action=action,
            entity_type="grade",
            entity_id=grade_id,
            before=grade_to_audit_dict(before_read),
            after=grade_to_audit_dict(after_read),
            ip=ip_address,
            user_agent=user_agent,
        )
        return after_read

    async def deactivate_grade(
        self,
        company_id: UUID,
        grade_id: UUID,
        *,
        expected_version: int,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> GradeRead:
        """Semantic wrapper around `update_grade` for `DELETE /grades/{id}` — never a hard
        delete (FR-ORG-014); flips `is_active` to False via the same business-rule path
        (audit, optimistic concurrency)."""
        return await self.update_grade(
            company_id,
            grade_id,
            GradeUpdate(is_active=False),
            expected_version=expected_version,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )


def _format_optional_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    iso = value.isoformat()
    return iso.replace("+00:00", "Z")
