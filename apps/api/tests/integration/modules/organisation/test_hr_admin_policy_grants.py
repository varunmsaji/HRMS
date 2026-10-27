"""HR_ADMIN policy - the role's grants for new and existing tenants, and what it still cannot do.

New tenants: `register_company` seeds company-wide attendance READ and the onboarding permissions.
Existing tenants: the additive Alembic data migration `20261026090000` (its real `upgrade()` and
`downgrade()` are executed here against a tenant whose grants were removed). Nothing else about the
role, and nothing about any other role, changes.
"""

import importlib.util
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.account_invite.uac_helpers import Tenant as UacTenant
from tests.integration.modules.account_invite.uac_helpers import onboard, teardown
from tests.integration.modules.onboarding.test_onboarding_case import _cleanup_onboarding_cases
from tests.integration.modules.organisation.test_registration_flow import (
    _register,
    _role_grants,
)

from hrms.core.db.session import get_session_factory, set_rls_company_id

pytestmark = pytest.mark.asyncio

_MIGRATION = (
    Path(__file__).resolve().parents[4]
    / "alembic/versions/20261026090000_hr_admin_attendance_onboarding_grants.py"
)
NEW_GRANTS = {
    "ATTENDANCE.VIEW",
    "ATTENDANCE.VIEW_ALL",
    "ONBOARDING.CREATE",
    "ONBOARDING.VIEW",
    "ONBOARDING.REVIEW",
    "ONBOARDING.ACTIVATE",
    "ONBOARDING.CANCEL",
}
# never part of the HR_ADMIN policy: policy management, shifts/rosters, period lock/unlock,
# on-behalf/recompute powers, user/role administration, payroll approval and bank advice.
NEVER = {
    "ATTENDANCE.POLICY_MANAGE",
    "ATTENDANCE.ROSTER_MANAGE",
    "ATTENDANCE.LOCK",
    "ATTENDANCE.UNLOCK",
    "ATTENDANCE.PUNCH",
    "ATTENDANCE.PUNCH_ON_BEHALF",
    "ATTENDANCE.RECOMPUTE",
    "SETTINGS.USER.MANAGE",
    "SETTINGS.ROLE.MANAGE",
    "PAYROLL.RUN_APPROVE",
    "PAYROLL.BANK_ADVICE_DOWNLOAD",
}


async def _new_tenant(client: AsyncClient) -> tuple[UacTenant, UUID]:
    response, company_id, user_id = await _register(client)
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    headers = {"Authorization": f"Bearer {data['access_token']}", "X-Company-Id": str(company_id)}
    return UacTenant(
        headers=headers, company_id=company_id, admin_user_id=user_id, emails=[]
    ), company_id


def _load_migration():
    spec = importlib.util.spec_from_file_location("hr_admin_grants_mig", _MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


async def _run(fn_name: str) -> None:
    mig = _load_migration()
    async with get_session_factory()() as session:
        conn = await session.connection()

        def _go(sync_conn) -> None:  # noqa: ANN001
            with Operations.context(MigrationContext.configure(sync_conn)):
                getattr(mig, fn_name)()

        await conn.run_sync(_go)
        await session.commit()


async def test_new_tenant_hr_admin_gets_exactly_the_approved_additions(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant, company_id = await _new_tenant(client)
    try:
        hr = await _role_grants(company_id, "HR_ADMIN")
        assert {c: hr[c] for c in NEW_GRANTS} == {c: "COMPANY" for c in NEW_GRANTS}
        assert not NEVER & set(hr), NEVER & set(hr)
        # unchanged neighbours
        assert hr["ATTENDANCE.REGULARIZATION_APPROVE"] == "COMPANY"
        assert hr["PAYROLL.RUN_PROCESS"] == "COMPANY" and "PAYROLL.RUN_APPROVE" not in hr
        # other roles gained nothing
        rm = await _role_grants(company_id, "REPORTING_MANAGER")
        bm = await _role_grants(company_id, "BRANCH_MANAGER")
        emp = await _role_grants(company_id, "EMPLOYEE")
        assert not {c for c in rm if c.startswith("ONBOARDING.") or c.startswith("ATTENDANCE.VIEW")}
        assert not {
            c for c in bm | emp if c.startswith("ONBOARDING.") or c == "ATTENDANCE.VIEW_ALL"
        }
        assert bm["ATTENDANCE.VIEW"] == "BRANCH" and emp["ATTENDANCE.VIEW"] == "SELF"
        admin = await _role_grants(company_id, "COMPANY_ADMIN")
        assert NEW_GRANTS | {"PAYROLL.RUN_APPROVE", "PAYROLL.BANK_ADVICE_DOWNLOAD"} <= set(admin)
    finally:
        await teardown(tenant)


async def test_backfill_migration_is_additive_idempotent_and_scope_preserving(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant, company_id = await _new_tenant(client)
    try:
        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(company_id))
            codes = ",".join(f"'{c}'" for c in sorted(NEW_GRANTS))
            # pre-fix tenant: HR_ADMIN lacks the grants, one customised narrower row exists
            await session.execute(
                text(
                    "DELETE FROM role_permission rp USING role r, permission p "
                    "WHERE rp.role_id=r.id AND rp.permission_id=p.id AND r.company_id=:c "
                    "AND r.code='HR_ADMIN' "
                    f"AND p.code IN ({codes})"
                ),
                {"c": str(company_id)},
            )
            await session.execute(
                text(
                    "INSERT INTO role_permission(role_id, permission_id, data_scope) SELECT r.id, "
                    "p.id, 'BRANCH' FROM role r, permission p WHERE r.company_id=:c "
                    "AND r.code='HR_ADMIN' AND p.code='ATTENDANCE.VIEW'"
                ),
                {"c": str(company_id)},
            )
            await session.commit()
        others_before = {}
        for role in ("COMPANY_ADMIN", "REPORTING_MANAGER", "BRANCH_MANAGER", "EMPLOYEE"):
            others_before[role] = await _role_grants(company_id, role)
        hr_before = await _role_grants(company_id, "HR_ADMIN")
        assert not NEW_GRANTS - {"ATTENDANCE.VIEW"} & set(hr_before)

        await _run("upgrade")
        await _run("upgrade")  # idempotent
        hr = await _role_grants(company_id, "HR_ADMIN")
        assert hr["ATTENDANCE.VIEW"] == "BRANCH"  # customised scope not widened
        assert {hr[c] for c in NEW_GRANTS - {"ATTENDANCE.VIEW"}} == {"COMPANY"}
        assert not NEVER & set(hr)
        assert set(hr) - set(hr_before) == NEW_GRANTS - {"ATTENDANCE.VIEW"}  # only additions
        assert {r: await _role_grants(company_id, r) for r in others_before} == others_before

        await _run("downgrade")
        after_down = await _role_grants(company_id, "HR_ADMIN")
        assert not (NEW_GRANTS - {"ATTENDANCE.VIEW"}) & set(after_down)
        assert after_down["ATTENDANCE.VIEW"] == "BRANCH"  # non-COMPANY row untouched
        assert {r: await _role_grants(company_id, r) for r in others_before} == others_before
    finally:
        await _run("upgrade")  # leave the disposable DB at head grants
        await teardown(tenant)


async def test_hr_admin_runtime_access_and_limits(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant, company_id = await _new_tenant(client)
    other, _other_company = await _new_tenant(client)
    try:
        hr = await onboard(client, tenant, "HR_ADMIN")
        h = hr.headers

        # onboarding: create / list / read
        case = await client.post(
            "/v1/onboarding-cases",
            headers=h,
            json={
                "candidate_first_name": "Asha",
                "candidate_last_name": "Rao",
                "personal_email": f"asha-{uuid4().hex[:8]}@personal.example",
                "personal_mobile": "9876543210",
                "proposed_joining_date": "2027-01-15",
            },
        )
        assert case.status_code == 201, case.text
        cid = case.json()["data"]["id"]
        assert (await client.get("/v1/onboarding-cases", headers=h)).status_code == 200
        assert (await client.get(f"/v1/onboarding-cases/{cid}", headers=h)).status_code == 200
        # another tenant's HR_ADMIN cannot see it
        other_hr = await onboard(client, other, "HR_ADMIN")
        assert (
            await client.get(f"/v1/onboarding-cases/{cid}", headers=other_hr.headers)
        ).status_code == 404

        # attendance: company-wide READ yes, administration no
        for path in ("/v1/attendance/days", "/v1/attendance/punches", "/v1/attendance-periods"):
            assert (await client.get(path, headers=h)).status_code == 200, path
        for method, path, body in [
            ("GET", "/v1/attendance-policies", None),
            ("POST", "/v1/attendance-policies", {"name": "x"}),
            ("POST", "/v1/shifts", {"name": "x", "code": "X"}),
            ("POST", "/v1/rosters", {}),
            ("POST", "/v1/attendance-periods", {}),
            ("POST", f"/v1/attendance-periods/{uuid4()}/finalize", {}),
            ("POST", f"/v1/attendance-periods/{uuid4()}/reopen", {}),
        ]:
            r = await client.request(method, path, headers=h, json=body)
            assert r.status_code == 403, (method, path, r.status_code, r.text)

        # no privilege escalation: cannot invite a COMPANY_ADMIN or change anyone's roles
        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(company_id))
            before = (
                await session.execute(
                    text(
                        "SELECT (SELECT count(*) FROM account_invite WHERE company_id=:c), "
                        "(SELECT count(*) FROM user_role ur JOIN user_company uc ON "
                        "uc.id=ur.user_company_id WHERE uc.company_id=:c)"
                    ),
                    {"c": str(company_id)},
                )
            ).one()
        for role in ("COMPANY_ADMIN", "HR_ADMIN"):
            r = await client.post(
                "/v1/users/invite",
                headers=h,
                json={"email": f"x-{uuid4().hex[:6]}@example.com", "role_code": role},
            )
            assert r.status_code == 403, (role, r.text)
        for role in (["COMPANY_ADMIN"], ["HR_ADMIN", "COMPANY_ADMIN"]):
            r = await client.patch(
                f"/v1/users/{hr.user_id}/roles", headers=h, json={"role_codes": role}
            )
            assert r.status_code == 403, (role, r.text)
        assert (await client.get("/v1/users", headers=h)).status_code == 403
        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(company_id))
            after = (
                await session.execute(
                    text(
                        "SELECT (SELECT count(*) FROM account_invite WHERE company_id=:c), "
                        "(SELECT count(*) FROM user_role ur JOIN user_company uc ON "
                        "uc.id=ur.user_company_id WHERE uc.company_id=:c)"
                    ),
                    {"c": str(company_id)},
                )
            ).one()
        assert tuple(after) == tuple(before)
        me = (await client.get("/v1/auth/me", headers=h)).json()["data"]["user"]
        assert "SETTINGS.USER.MANAGE" not in me["permissions"]
        assert (
            "ATTENDANCE.VIEW_ALL" in me["permissions"]
            and "ONBOARDING.ACTIVATE" in me["permissions"]
        )
    finally:
        await teardown(other)
        await _cleanup_onboarding_cases(company_id=company_id)
        await teardown(tenant)
