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
        assert data["refresh_token"]
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
                await session.execute(select(Role).where(Role.company_id == company_id))
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
                "LEAVE.TYPE_MANAGE",
                "LEAVE.POLICY_MANAGE",
                "LEAVE.BALANCE_VIEW",
                "LEAVE.BALANCE_VIEW_ALL",
                "LEAVE.BALANCE_ADJUST",
                "LEAVE.APPLICATION_SUBMIT",
                "LEAVE.APPLICATION_SUBMIT_ON_BEHALF",
                "LEAVE.APPLICATION_APPROVE",
                "ONBOARDING.CREATE",
                "ONBOARDING.VIEW",
                "ONBOARDING.REVIEW",
                "ONBOARDING.ACTIVATE",
                "ONBOARDING.CANCEL",
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
