from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.audit.models import AuditLog
from hrms.core.auth.passwords import verify_password
from hrms.core.db.models.identity import (
    Company,
    Permission,
    RefreshToken,
    Role,
    RolePermission,
    Session,
    User,
    UserCompany,
    UserRole,
)
from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.core.rbac.service import RbacService
from hrms.modules.organisation.models import (
    CompanyFeatureFlag,
    CompanySetupProgress,
    LegalEntity,
    Plan,
    Subscription,
)
from hrms.modules.organisation.permissions import (
    DASHBOARD_COMPANY_VIEW,
    ORG_BRANCH_MANAGE,
    ORG_CALENDAR_MANAGE,
    ORG_COMPANY_MANAGE,
    ORG_DEPARTMENT_MANAGE,
    ORG_DESIGNATION_MANAGE,
    ORG_GRADE_MANAGE,
    ORG_HOLIDAY_MANAGE,
    ORG_LEGAL_ENTITY_MANAGE,
    ORG_SHIFT_MANAGE,
)

VALID_PASSWORD = "CorrectHorse9"


def _payload(**overrides: Any) -> dict[str, Any]:
    unique = uuid4().hex[:10]
    body = {
        "name": f"Acme {unique}",
        "industry_code": "MANUFACTURING",
        "company_size": "51-200",
        "admin_first_name": "Priya",
        "admin_last_name": "Sharma",
        "admin_email": f"priya-{unique}@acme.example",
        "admin_password": VALID_PASSWORD,
    }
    body.update(overrides)
    return body


async def _cleanup(*, company_id: UUID | None, user_id: UUID | None) -> None:
    factory = get_session_factory()
    async with factory() as session:
        if company_id is not None:
            # A pooled connection that has ever had `app.company_id` set reverts to `''` (not
            # NULL) once its transaction ends — a Postgres custom-GUC-placeholder quirk, not
            # an RLS bug. Setting it explicitly here avoids `invalid input syntax for type
            # uuid: ""` on this unscoped raw cleanup query once the suite has run a few tests.
            await set_rls_company_id(session, str(company_id))
            await session.execute(
                AuditLog.__table__.delete().where(AuditLog.company_id == company_id)
            )
            await session.execute(
                LegalEntity.__table__.delete().where(LegalEntity.company_id == company_id)
            )
            await session.execute(
                Subscription.__table__.delete().where(Subscription.company_id == company_id)
            )
            await session.execute(
                CompanySetupProgress.__table__.delete().where(
                    CompanySetupProgress.company_id == company_id
                )
            )
            await session.execute(
                CompanyFeatureFlag.__table__.delete().where(
                    CompanyFeatureFlag.company_id == company_id
                )
            )
            await session.execute(
                UserRole.__table__.delete().where(
                    UserRole.user_company_id.in_(
                        select(UserCompany.id).where(UserCompany.company_id == company_id)
                    )
                )
            )
            await session.execute(
                RolePermission.__table__.delete().where(
                    RolePermission.role_id.in_(select(Role.id).where(Role.company_id == company_id))
                )
            )
            await session.execute(
                UserCompany.__table__.delete().where(UserCompany.company_id == company_id)
            )
            await session.execute(Role.__table__.delete().where(Role.company_id == company_id))
        if user_id is not None:
            await session.execute(
                RefreshToken.__table__.delete().where(RefreshToken.user_id == user_id)
            )
            await session.execute(Session.__table__.delete().where(Session.user_id == user_id))
            await session.execute(User.__table__.delete().where(User.id == user_id))
        if company_id is not None:
            await session.execute(Company.__table__.delete().where(Company.id == company_id))
        await session.commit()


async def _register(client: AsyncClient, **overrides: Any) -> tuple[Any, UUID | None, UUID | None]:
    response = await client.post("/v1/companies/register", json=_payload(**overrides))
    company_id: UUID | None = None
    user_id: UUID | None = None
    if response.status_code == 201:
        data = response.json()["data"]
        company_id = UUID(data["company_id"])
        factory = get_session_factory()
        async with factory() as session:
            row = (
                await session.execute(select(Company).where(Company.id == company_id))
            ).scalar_one()
            user_id = row.created_by
    return response, company_id, user_id


@pytest.mark.asyncio
async def test_registration_success_full_row_graph(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    payload = _payload()
    response = await client.post("/v1/companies/register", json=payload)
    company_id: UUID | None = None
    user_id: UUID | None = None
    try:
        assert response.status_code == 201
        body = response.json()
        data = body["data"]

        assert data["access_token"]
        # SEC-06 (RELEASE_HARDENING_PHASE_3A) — the refresh token no longer appears in the JSON
        # response at all; it travels only as the HttpOnly `hrms_refresh` cookie.
        assert "refresh_token" not in data
        assert response.cookies.get("hrms_refresh")
        assert data["token_type"] == "Bearer"
        company_id = UUID(data["company_id"])
        assert data["companies"] == [
            {"id": str(company_id), "name": payload["name"], "is_primary": True}
        ]

        raw_text = response.text
        assert payload["admin_password"] not in raw_text
        assert "admin_password" not in raw_text
        assert "password" not in data
        assert "password_hash" not in raw_text

        factory = get_session_factory()
        async with factory() as session:
            company = (
                await session.execute(select(Company).where(Company.id == company_id))
            ).scalar_one()
            user_id = company.created_by
            assert company.status == "TRIAL"
            assert company.country_code == "IN"
            assert company.currency == "INR"
            assert company.timezone == "Asia/Kolkata"
            assert company.fy_start_month == 4
            assert company.created_by == user_id
            assert company.updated_by == user_id
            now = datetime.now(UTC)
            assert company.trial_ends_at is not None
            assert now + timedelta(days=13) < company.trial_ends_at < now + timedelta(days=15)

            user = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
            assert user.email == payload["admin_email"].lower()
            assert user.first_name == payload["admin_first_name"]
            assert user.last_name == payload["admin_last_name"]
            assert user.password_hash != payload["admin_password"]
            assert verify_password(str(user.password_hash), payload["admin_password"])

            membership = (
                await session.execute(
                    select(UserCompany).where(
                        UserCompany.user_id == user_id, UserCompany.company_id == company_id
                    )
                )
            ).scalar_one()
            assert membership.is_primary is True
            assert membership.status == "ACTIVE"

            role = (
                await session.execute(
                    select(Role).where(Role.company_id == company_id, Role.code == "COMPANY_ADMIN")
                )
            ).scalar_one()
            assert role.code == "COMPANY_ADMIN"
            assert role.is_system is True

            user_role = (
                await session.execute(
                    select(UserRole).where(UserRole.user_company_id == membership.id)
                )
            ).scalar_one()
            assert user_role.role_id == role.id

            rbac = RbacService(session)
            codes = await rbac.get_permission_codes(user_id, company_id)
            # EMPLOYEE.* codes added by the Employee Foundation (E-01) slice
            # (docs/modules/employee/01_EMPLOYEE_FOUNDATION_AUDIT.md §5), EMPLOYEE.TERMINATE
            # added by the Employment Lifecycle (E-03) slice, EMPLOYEE.TRANSFER/.PROMOTE
            # added by the Employee Assignment (E-04) slice, EMPLOYEE.VIEW_COMPENSATION/
            # .UPDATE_COMPENSATION added by the Employee Compensation (E-06) slice,
            # EMPLOYEE.VIEW_STATUTORY/.UPDATE_SENSITIVE added by the Employee Statutory (E-07)
            # slice, and EMPLOYEE.VIEW_BANKING added by the Employee Banking (E-08) slice
            # (docs/modules/employee/permissions.py) — `register_company` now grants the
            # new company's admin role the same EMPLOYEE.VIEW/.VIEW_ALL/.CREATE/.UPDATE/
            # .DEACTIVATE/.TERMINATE/.TRANSFER/.PROMOTE/.VIEW_COMPENSATION/.UPDATE_COMPENSATION/
            # .VIEW_STATUTORY/.UPDATE_SENSITIVE/.VIEW_BANKING access every other org-domain
            # permission already gets here, since without it a freshly registered company's own
            # admin would have zero Employee access. ORG.CALENDAR.MANAGE/ORG.HOLIDAY.MANAGE
            # added by the Workforce Calendar (W1) slice, ATTENDANCE.POLICY_MANAGE added by
            # the Attendance Policy (W3) slice, ATTENDANCE.VIEW/.VIEW_ALL/.PUNCH/
            # .PUNCH_ON_BEHALF/.RECOMPUTE added by the Punch/AttendanceDay (W4) slice,
            # ATTENDANCE.ROSTER_MANAGE added by the Shift Roster (W5) slice,
            # ATTENDANCE.REGULARIZATION_REQUEST/_ON_BEHALF/.REGULARIZATION_APPROVE added by the
            # Regularization (W6) slice, ATTENDANCE.OVERTIME_APPROVE added by the Overtime (W7)
            # slice, ATTENDANCE.LOCK/.UNLOCK added by the Attendance Period (W8) slice,
            # ATTENDANCE.LEAVE_PROJECTION_SYNC added by the Leave Projection Adapter (W9)
            # slice, LEAVE.* added by the Leave module's L1 slice
            # (LEAVE_DECISION_LOG.md LD-08) — same "must grant at live registration, not
            # just the demo seed" rule. ONBOARDING.* added by the Onboarding module's O1 slice
            # (docs/modules/onboarding/01_ONBOARDING_MODULE_PLAN.md §7.1/§11) — same rule again.
            assert codes == {
                ORG_COMPANY_MANAGE,
                DASHBOARD_COMPANY_VIEW,
                ORG_LEGAL_ENTITY_MANAGE,
                ORG_BRANCH_MANAGE,
                ORG_DEPARTMENT_MANAGE,
                ORG_DESIGNATION_MANAGE,
                ORG_GRADE_MANAGE,
                ORG_SHIFT_MANAGE,
                ORG_CALENDAR_MANAGE,
                ORG_HOLIDAY_MANAGE,
                "ATTENDANCE.POLICY_MANAGE",
                "ATTENDANCE.VIEW",
                "ATTENDANCE.VIEW_ALL",
                "ATTENDANCE.PUNCH",
                "ATTENDANCE.PUNCH_ON_BEHALF",
                "ATTENDANCE.RECOMPUTE",
                "ATTENDANCE.ROSTER_MANAGE",
                "ATTENDANCE.REGULARIZATION_REQUEST",
                "ATTENDANCE.REGULARIZATION_REQUEST_ON_BEHALF",
                "ATTENDANCE.REGULARIZATION_APPROVE",
                "ATTENDANCE.OVERTIME_APPROVE",
                "ATTENDANCE.LOCK",
                "ATTENDANCE.UNLOCK",
                "ATTENDANCE.LEAVE_PROJECTION_SYNC",
                "EMPLOYEE.VIEW",
                "EMPLOYEE.VIEW_ALL",
                "EMPLOYEE.CREATE",
                "EMPLOYEE.UPDATE",
                "EMPLOYEE.DEACTIVATE",
                "EMPLOYEE.TERMINATE",
                "EMPLOYEE.TRANSFER",
                "EMPLOYEE.PROMOTE",
                "EMPLOYEE.VIEW_COMPENSATION",
                "EMPLOYEE.UPDATE_COMPENSATION",
                "EMPLOYEE.VIEW_STATUTORY",
                "EMPLOYEE.UPDATE_SENSITIVE",
                "EMPLOYEE.VIEW_BANKING",
                # Added by employee_import (CSV bulk employee import) — defined in
                # employee/permissions.py so it rides the same EMPLOYEE.* grant loop.
                "EMPLOYEE.BULK_IMPORT",
                # Added by Employee confirmation (minimal slice) — PROBATION -> ACTIVE.
                "EMPLOYEE.CONFIRM",
                # Added by Account Provisioning (doc 41 Phase 2) — gates
                # `POST /employees/{id}/invite`; granted to COMPANY_ADMIN/HR_ADMIN, not EMPLOYEE
                # (Decision H). Pre-existing gap in this assertion, not touched by this change.
                "EMPLOYEE.INVITE",
                # Added alongside the default-roles rollout (Decision H) — granted to
                # COMPANY_ADMIN for managing users/roles. Pre-existing gap in this assertion.
                "SETTINGS.USER.MANAGE",
                "SETTINGS.ROLE.MANAGE",
                # Added by the market-parity onboarding-data pass (E-02) — gates
                # `GET /employees/{id}/identity` (PAN/Aadhaar/UAN); granted to HR_ADMIN via the
                # standard EMPLOYEE_PERMISSIONS grant loop.
                "EMPLOYEE.VIEW_SENSITIVE",
                # Added by market-parity onboarding-data pass part 4 (previous employment / PF
                # continuity) — gates `GET /employees/{id}/experience`.
                "EMPLOYEE.VIEW_EXPERIENCE",
                # Added by market-parity onboarding-data pass part 6 (PF/Gratuity nominee + ESI
                # family details) — gates `GET /employees/{id}/dependents`.
                "EMPLOYEE.VIEW_NOMINEE",
                "LEAVE.TYPE_MANAGE",
                "LEAVE.POLICY_MANAGE",
                "LEAVE.BALANCE_VIEW",
                "LEAVE.BALANCE_VIEW_ALL",
                "LEAVE.BALANCE_ADJUST",
                "LEAVE.APPLICATION_SUBMIT",
                "LEAVE.APPLICATION_SUBMIT_ON_BEHALF",
                "LEAVE.APPLICATION_APPROVE",
                # Decision 10 (PAYROLL_BUSINESS_DECISIONS.md) — HR cancels approved leave.
                "LEAVE.APPLICATION_CANCEL_APPROVED",
                # Added by LD-16/LD-20/LD-22 (leave combination rules, leave year setting,
                # statutory compliance floor) — not new to this session's own work.
                "LEAVE.COMBINATION_RULE_MANAGE",
                "LEAVE.YEAR_SETTING_MANAGE",
                "LEAVE.STATUTORY_MINIMUM_MANAGE",
                "ONBOARDING.CREATE",
                "ONBOARDING.VIEW",
                "ONBOARDING.REVIEW",
                "ONBOARDING.ACTIVATE",
                "ONBOARDING.CANCEL",
                # Payroll Phase 5.1 — salary components, structures and assignment.
                "PAYROLL.SETUP_MANAGE",
                # Payroll Phase 5.2 — pay runs.
                "PAYROLL.RUN_VIEW",
                "PAYROLL.RUN_PROCESS",
                "PAYROLL.RUN_APPROVE",
                # Payroll Phase 5.3 — statutory rate master.
                "PAYROLL.STATUTORY_MANAGE",
                # Payroll Phase 5.4 — payslips and bank advice.
                "PAYROLL.PAYSLIP_VIEW_OWN",
                "PAYROLL.BANK_ADVICE_DOWNLOAD",
            }

            setup_progress = (
                await session.execute(
                    select(CompanySetupProgress).where(
                        CompanySetupProgress.company_id == company_id
                    )
                )
            ).scalar_one()
            assert setup_progress.status == "IN_PROGRESS"
            assert setup_progress.started_at is not None

            subscription = (
                await session.execute(
                    select(Subscription).where(Subscription.company_id == company_id)
                )
            ).scalar_one()
            plan = (
                await session.execute(select(Plan).where(Plan.id == subscription.plan_id))
            ).scalar_one()
            assert plan.code == "FREE"
            assert subscription.status == "TRIALING"
            assert subscription.trial_ends_at == company.trial_ends_at

            audit_rows = (
                (await session.execute(select(AuditLog).where(AuditLog.company_id == company_id)))
                .scalars()
                .all()
            )
            # Two rows are expected: the explicit company-level event this task's API design
            # mandates, plus the session-level event `issue_tokens_for` always records as
            # part of token issuance (reused, not duplicated, per the identity module).
            company_audit_rows = [r for r in audit_rows if r.entity_type == "company"]
            assert len(company_audit_rows) == 1
            audit_row = company_audit_rows[0]
            assert audit_row.action == "COMPANY_REGISTERED"
            assert audit_row.entity_id == company_id
            assert audit_row.actor_user_id == user_id
            assert audit_row.before_json is None
            assert audit_row.after_json is None
            for row in audit_rows:
                assert row.before_json is None
                assert row.after_json is None
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_registration_duplicate_admin_email_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    payload = _payload()
    first, company_id, user_id = await _register(client, **payload)
    try:
        assert first.status_code == 201

        second = await client.post(
            "/v1/companies/register",
            json=_payload(admin_email=payload["admin_email"]),
        )
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "CONFLICT"

        factory = get_session_factory()
        async with factory() as session:
            count = (
                (
                    await session.execute(
                        select(User).where(User.email == payload["admin_email"].lower())
                    )
                )
                .scalars()
                .all()
            )
            assert len(count) == 1
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_registration_concurrent_duplicate_email_race_returns_conflict(
    client: AsyncClient, seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The application-layer pre-check is racy by construction — force both requests past it
    (simulating two registrations racing for the same email) and prove the real DB unique
    index on `user.email` (`user_email_key`) is the actual backstop: the loser gets a clean
    409, not a raw IntegrityError / 500."""
    from hrms.core.db.repositories.identity import IdentityRepository

    async def _never_found(self: IdentityRepository, session: Any, email: str) -> User | None:
        return None

    monkeypatch.setattr(IdentityRepository, "get_user_by_email", _never_found)

    payload = _payload()
    first, company_id, user_id = await _register(client, **payload)
    try:
        assert first.status_code == 201

        second = await client.post(
            "/v1/companies/register",
            json=_payload(admin_email=payload["admin_email"]),
        )
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "CONFLICT"

        factory = get_session_factory()
        async with factory() as session:
            rows = (
                (
                    await session.execute(
                        select(User).where(User.email == payload["admin_email"].lower())
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 1
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_registration_weak_password_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    payload = _payload(admin_password="short")
    response = await client.post("/v1/companies/register", json=payload)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert any(d["field"] == "admin_password" for d in error["details"])

    factory = get_session_factory()
    async with factory() as session:
        rows = (
            (
                await session.execute(
                    select(User).where(User.email == payload["admin_email"].lower())
                )
            )
            .scalars()
            .all()
        )
        assert rows == []
        companies = (
            (await session.execute(select(Company).where(Company.name == payload["name"])))
            .scalars()
            .all()
        )
        assert companies == []


@pytest.mark.asyncio
async def test_registration_invalid_timezone_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    payload = _payload(timezone="Not/AZone")
    response = await client.post("/v1/companies/register", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_registration_non_indian_valid_timezone_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`DEC-TZ-02` (SELECTED) — a *valid* IANA zone outside `settings.allowed_company_timezones`
    is still rejected. Before Phase 2, this was accepted: an anonymous, unauthenticated visitor
    could create a company running every attendance calculation in `America/Los_Angeles` on a
    product that is India-only for V1 (execution gate §6)."""
    payload = _payload(timezone="America/Los_Angeles")
    response = await client.post("/v1/companies/register", json=payload)
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_registration_asia_calcutta_canonicalised(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Canonicalisation runs BEFORE the allow-list check (execution gate §6.3) — `Asia/Calcutta`
    must be accepted, not rejected for a spelling difference, because it resolves to the one
    allowed zone."""
    response, company_id, user_id = await _register(client, timezone="Asia/Calcutta")
    try:
        assert response.status_code == 201, response.text
        factory = get_session_factory()
        async with factory() as session:
            company = (
                await session.execute(select(Company).where(Company.id == company_id))
            ).scalar_one()
            assert company.timezone == "Asia/Kolkata"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_registration_invalid_fy_start_month_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    payload = _payload(fy_start_month=13)
    response = await client.post("/v1/companies/register", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_registration_missing_required_field_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    payload = _payload()
    del payload["name"]
    response = await client.post("/v1/companies/register", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_registration_without_default_plan_skips_subscription(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hrms.modules.organisation.repository import OrganisationRepository

    async def _no_plan(
        self: OrganisationRepository, session: AsyncSession, *, code: str
    ) -> Plan | None:
        return None

    monkeypatch.setattr(OrganisationRepository, "get_plan_by_code", _no_plan)

    response, company_id, user_id = await _register(client)
    try:
        assert response.status_code == 201
        factory = get_session_factory()
        async with factory() as session:
            rows = (
                (
                    await session.execute(
                        select(Subscription).where(Subscription.company_id == company_id)
                    )
                )
                .scalars()
                .all()
            )
            assert rows == []
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_registration_no_client_suppliable_tenant_fields(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A client cannot inject company_id/user_id/role to cross tenants — the schema simply
    has no such fields, so extra keys are ignored (Pydantic default), not honoured."""
    fabricated_company_id = str(uuid4())
    payload = _payload(company_id=fabricated_company_id, id=fabricated_company_id)
    response, company_id, user_id = await _register(client, **payload)
    try:
        assert response.status_code == 201
        assert response.json()["data"]["company_id"] != fabricated_company_id
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_registration_config_is_public_and_lists_india_only(
    client: AsyncClient,
) -> None:
    """No auth header, no company header, no `seeded_plan_catalogue` — this must be reachable
    by the sign-up page before any tenant or session exists (execution gate §6.3)."""
    response = await client.get("/v1/companies/registration-config")
    assert response.status_code == 200, response.text
    assert response.json()["data"]["allowed_company_timezones"] == ["Asia/Kolkata"]


async def _role_grants(company_id: UUID, role_code: str) -> dict[str, str]:
    factory = get_session_factory()
    async with factory() as session:
        role = (
            await session.execute(
                select(Role).where(Role.company_id == company_id, Role.code == role_code)
            )
        ).scalar_one()
        grants = (
            await session.execute(
                select(RolePermission, Permission.code)
                .join(Permission, Permission.id == RolePermission.permission_id)
                .where(RolePermission.role_id == role.id)
            )
        ).all()
        return {code: grant.data_scope for grant, code in grants}


@pytest.mark.asyncio
async def test_registration_seeds_branch_manager_role(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`docs/architecture/RBAC_DATA_SCOPE_DECISIONS.md`'s 2026-09-23/24 Addendum — a fresh
    registration gets a `BRANCH_MANAGER` role alongside `COMPANY_ADMIN`, same as `HR_ADMIN`/
    `REPORTING_MANAGER`/`EMPLOYEE`. Not assigned to the registering admin — exists so a future
    role-assignment flow can grant it, same as its siblings. `EMPLOYEE.VIEW_ALL` is needed
    alongside `EMPLOYEE.VIEW` because `GET /v1/employees` (the list endpoint) gates on `.VIEW_ALL`
    while `GET /v1/employees/{id}` gates on plain `.VIEW` (`employee/router.py`). The three
    `.APPROVE` grants (added by the approval-authority backfill) only take effect for MANAGER/HOD-
    stage approval when this role's holder is also literally the request's snapshotted
    `reporting_manager_id`/department head — `BRANCH` scope has no bearing on that identity check,
    see `organisation/service.py`'s `BRANCH_MANAGER_ROLE_CODE` comment."""
    response, company_id, user_id = await _register(client)
    try:
        assert response.status_code == 201
        assert await _role_grants(company_id, "BRANCH_MANAGER") == {
            "EMPLOYEE.VIEW": "BRANCH",
            "EMPLOYEE.VIEW_ALL": "BRANCH",
            "ATTENDANCE.VIEW": "BRANCH",
            "ATTENDANCE.REGULARIZATION_APPROVE": "BRANCH",
            "ATTENDANCE.OVERTIME_APPROVE": "BRANCH",
            "LEAVE.APPLICATION_APPROVE": "BRANCH",
        }
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_registration_seeds_reporting_manager_approval_grants(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Before this grant, `REPORTING_MANAGER` held only `EMPLOYEE.VIEW` — the literal reporting
    manager named on a regularization/overtime/leave request could never pass the router's
    permission gate to even reach the identity check, so a MANAGER-stage request was
    unapprovable by anyone. `REPORTEE_TREE` scope here is for consistency with this role's other
    grant; the MANAGER/HOD-stage identity check itself doesn't consult it."""
    response, company_id, user_id = await _register(client)
    try:
        assert response.status_code == 201
        assert await _role_grants(company_id, "REPORTING_MANAGER") == {
            "EMPLOYEE.VIEW": "REPORTEE_TREE",
            "ATTENDANCE.REGULARIZATION_APPROVE": "REPORTEE_TREE",
            "ATTENDANCE.OVERTIME_APPROVE": "REPORTEE_TREE",
            "LEAVE.APPLICATION_APPROVE": "REPORTEE_TREE",
        }
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_registration_seeds_hr_admin_approval_grants(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """HR-stage approval (all three request types) checks only `DataScopeLevel.COMPANY` on the
    matching `.APPROVE` code, no identity match — before this grant, only `COMPANY_ADMIN` held
    it, and `COMPANY_ADMIN` typically has no `Employee` record, so HR-stage approval was
    effectively unreachable by the role whose name implies it should own that job."""
    response, company_id, user_id = await _register(client)
    try:
        assert response.status_code == 201
        grants = await _role_grants(company_id, "HR_ADMIN")
        assert grants["ATTENDANCE.REGULARIZATION_APPROVE"] == "COMPANY"
        assert grants["ATTENDANCE.OVERTIME_APPROVE"] == "COMPANY"
        assert grants["LEAVE.APPLICATION_APPROVE"] == "COMPANY"
        assert grants["LEAVE.APPLICATION_CANCEL_APPROVED"] == "COMPANY"
        assert grants["PAYROLL.SETUP_MANAGE"] == "COMPANY"
        assert grants["PAYROLL.RUN_VIEW"] == "COMPANY"
        assert grants["PAYROLL.RUN_PROCESS"] == "COMPANY"
        assert grants["PAYROLL.STATUTORY_MANAGE"] == "COMPANY"
        assert "PAYROLL.BANK_ADVICE_DOWNLOAD" not in grants
        # Payroll 5.4 — every employee reads their own payslips.
        employee_grants = await _role_grants(company_id, "EMPLOYEE")
        assert employee_grants["PAYROLL.PAYSLIP_VIEW_OWN"] == "SELF"
        # D9 — approving a pay run stays with COMPANY_ADMIN.
        assert "PAYROLL.RUN_APPROVE" not in grants
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)
