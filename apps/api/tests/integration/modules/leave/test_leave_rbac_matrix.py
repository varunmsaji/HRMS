"""Decision 12 - default role grants, route by route.

Each case logs in as a user holding ONE real default role (`EMPLOYEE`, `REPORTING_MANAGER`,
`BRANCH_MANAGER`, `HR_ADMIN`, `COMPANY_ADMIN` - looked up by code in the registered company, not a
hand-built test role) and calls every Leave route. A route is "allowed" when the response is not a
403 (a permitted call with a made-up id or empty body legitimately answers 404 or 422), "denied"
when it is. Authorization is evaluated before the body and the target, so 403 is never masked.
`COMPANY_ADMIN` is asserted explicitly, not assumed.

The expected grants are the approved decision, written out here independently of the seeding code.
"""

# ruff: noqa: E501 - the route table is deliberately one row per line

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from tests.integration.modules.attendance.test_attendance_security import _cleanup_scoped_users
from tests.integration.modules.leave.test_leave_application import (
    _register_tenant,
    _setup_full,
    _teardown,
)
from tests.integration.modules.leave.test_leave_year import _teardown_year_setting
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.core.auth.jwt import create_access_token
from hrms.core.auth.passwords import hash_password
from hrms.core.db.models.identity import Role, Session, User, UserCompany, UserRole
from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.leave.permissions import (
    LEAVE_APPLICATION_APPROVE,
    LEAVE_APPLICATION_CANCEL_APPROVED,
    LEAVE_APPLICATION_REASSIGN,
    LEAVE_APPLICATION_SUBMIT,
    LEAVE_APPLICATION_SUBMIT_ON_BEHALF,
    LEAVE_BALANCE_ADJUST,
    LEAVE_BALANCE_VIEW,
    LEAVE_BALANCE_VIEW_ALL,
    LEAVE_COMBINATION_RULE_MANAGE,
    LEAVE_PERMISSIONS,
    LEAVE_POLICY_MANAGE,
    LEAVE_STATUTORY_MINIMUM_MANAGE,
    LEAVE_TYPE_MANAGE,
    LEAVE_YEAR_SETTING_MANAGE,
)

pytestmark = pytest.mark.asyncio

_ID = "00000000-0000-4000-8000-000000000001"
_ID2 = "00000000-0000-4000-8000-000000000002"

_ALL_LEAVE = {code for code, _domain, _description in LEAVE_PERMISSIONS}

#: What each default role must be able to do in Leave (decision 12 / 13), nothing more.
_GRANTS: dict[str, set[str]] = {
    "EMPLOYEE": {LEAVE_APPLICATION_SUBMIT, LEAVE_BALANCE_VIEW},
    "REPORTING_MANAGER": {LEAVE_APPLICATION_APPROVE, LEAVE_BALANCE_VIEW_ALL},
    "BRANCH_MANAGER": {LEAVE_APPLICATION_APPROVE, LEAVE_BALANCE_VIEW_ALL},
    "HR_ADMIN": {
        LEAVE_APPLICATION_APPROVE,
        LEAVE_APPLICATION_CANCEL_APPROVED,
        LEAVE_BALANCE_VIEW_ALL,
        LEAVE_BALANCE_ADJUST,
        LEAVE_APPLICATION_SUBMIT_ON_BEHALF,
        LEAVE_APPLICATION_REASSIGN,
    },
    "COMPANY_ADMIN": _ALL_LEAVE,
}

# (method, path, json body, any-of permissions that allow it)
_P = f"/v1/leave-policies/{_ID}"
_ROUTES: list[tuple[str, str, dict | None, set[str]]] = [
    ("GET", "/v1/leave-types", None, {LEAVE_TYPE_MANAGE, LEAVE_APPLICATION_SUBMIT, LEAVE_APPLICATION_SUBMIT_ON_BEHALF}),
    ("POST", "/v1/leave-types", {}, {LEAVE_TYPE_MANAGE}),
    ("GET", f"/v1/leave-types/{_ID}", None, {LEAVE_TYPE_MANAGE}),
    ("PATCH", f"/v1/leave-types/{_ID}", {}, {LEAVE_TYPE_MANAGE}),
    ("GET", "/v1/leave-policies", None, {LEAVE_POLICY_MANAGE}),
    ("POST", "/v1/leave-policies", {}, {LEAVE_POLICY_MANAGE}),
    ("GET", _P, None, {LEAVE_POLICY_MANAGE}),
    ("PATCH", _P, {}, {LEAVE_POLICY_MANAGE}),
    ("GET", f"{_P}/versions", None, {LEAVE_POLICY_MANAGE}),
    ("POST", f"{_P}/versions", {}, {LEAVE_POLICY_MANAGE}),
    ("GET", f"{_P}/versions/resolve", None, {LEAVE_POLICY_MANAGE}),
    ("GET", f"{_P}/versions/{_ID2}", None, {LEAVE_POLICY_MANAGE}),
    ("PATCH", f"{_P}/versions/{_ID2}", {}, {LEAVE_POLICY_MANAGE}),
    ("DELETE", f"{_P}/versions/{_ID2}", None, {LEAVE_POLICY_MANAGE}),
    ("POST", f"{_P}/versions/{_ID2}/publish", {}, {LEAVE_POLICY_MANAGE}),
    ("GET", "/v1/leave-year-setting", None, {LEAVE_YEAR_SETTING_MANAGE}),
    ("PUT", "/v1/leave-year-setting", {}, {LEAVE_YEAR_SETTING_MANAGE}),
    ("GET", "/v1/leave-combination-rules", None, {LEAVE_COMBINATION_RULE_MANAGE}),
    ("POST", "/v1/leave-combination-rules", {}, {LEAVE_COMBINATION_RULE_MANAGE}),
    ("DELETE", f"/v1/leave-combination-rules/{_ID}", None, {LEAVE_COMBINATION_RULE_MANAGE}),
    ("GET", "/v1/statutory-leave-minimums", None, {LEAVE_STATUTORY_MINIMUM_MANAGE}),
    ("POST", "/v1/statutory-leave-minimums", {}, {LEAVE_STATUTORY_MINIMUM_MANAGE}),
    ("DELETE", f"/v1/statutory-leave-minimums/{_ID}", None, {LEAVE_STATUTORY_MINIMUM_MANAGE}),
    ("POST", "/v1/leave-ledger/adjustments", {}, {LEAVE_BALANCE_ADJUST}),
    ("POST", "/v1/leave-ledger/encashments", {}, {LEAVE_BALANCE_ADJUST}),
    ("GET", f"/v1/leave-ledger?employee_id={_ID}", None, {LEAVE_BALANCE_VIEW, LEAVE_BALANCE_VIEW_ALL}),
    ("GET", f"/v1/leave-balances?employee_id={_ID}", None, {LEAVE_BALANCE_VIEW, LEAVE_BALANCE_VIEW_ALL}),
    ("GET", "/v1/leave-applications", None, {LEAVE_BALANCE_VIEW, LEAVE_BALANCE_VIEW_ALL}),
    ("GET", f"/v1/leave-applications/{_ID}", None, {LEAVE_BALANCE_VIEW, LEAVE_BALANCE_VIEW_ALL}),
    # submit: own (no employee_id) needs SUBMIT; for someone else needs the on-behalf grant
    ("POST", "/v1/leave-applications", {"leave_type_id": _ID, "start_date": "2026-09-08", "end_date": "2026-09-08"}, {LEAVE_APPLICATION_SUBMIT}),
    ("POST", "/v1/leave-applications", {"employee_id": _ID, "leave_type_id": _ID, "start_date": "2026-09-08", "end_date": "2026-09-08"}, {LEAVE_APPLICATION_SUBMIT_ON_BEHALF}),
    ("POST", f"/v1/leave-applications/{_ID}/cancel", {}, {LEAVE_APPLICATION_SUBMIT, LEAVE_APPLICATION_SUBMIT_ON_BEHALF, LEAVE_APPLICATION_CANCEL_APPROVED}),
    ("POST", f"/v1/leave-applications/{_ID}/approve", {}, {LEAVE_APPLICATION_APPROVE}),
    ("POST", f"/v1/leave-applications/{_ID}/reject", {}, {LEAVE_APPLICATION_APPROVE}),
    ("POST", f"/v1/leave-applications/{_ID}/reassign-approver", {"new_approver_employee_id": _ID2, "reason": "x"}, {LEAVE_APPLICATION_REASSIGN}),
]  # fmt: skip


async def _user_with_default_role(
    company_id: UUID, role_code: str, employee_id: UUID
) -> dict[str, str]:
    """A fresh active user whose only role is the company's real default role `role_code`."""
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        role = (
            await session.execute(
                select(Role).where(Role.company_id == company_id, Role.code == role_code)
            )
        ).scalar_one()
        now = datetime.now(UTC)
        user_id = uuid4()
        session.add(
            User(
                id=user_id,
                email=f"scoped-{role_code.lower()}-{user_id.hex[:8]}@example.com",
                password_hash=hash_password("CorrectHorse9"),
                status="ACTIVE",
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        membership = UserCompany(
            id=uuid4(),
            user_id=user_id,
            company_id=company_id,
            is_primary=True,
            status="ACTIVE",
            created_at=now,
            updated_at=now,
        )
        session.add(membership)
        await session.flush()
        session.add(UserRole(id=uuid4(), user_company_id=membership.id, role_id=role.id))
        session_id = uuid4()
        session.add(
            Session(
                id=session_id,
                user_id=user_id,
                company_id=company_id,
                expires_at=now + timedelta(days=1),
            )
        )
        await session.commit()
    token = create_access_token(
        user_id=user_id, company_id=company_id, session_id=session_id, employee_id=employee_id
    )
    return {"Authorization": f"Bearer {token}", "X-Company-Id": str(company_id)}


@pytest.mark.parametrize("role_code", list(_GRANTS))
async def test_every_leave_route_honours_the_default_role_grants(
    client: AsyncClient, seeded_plan_catalogue: None, role_code: str
) -> None:
    admin_headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, admin_headers)
        headers = await _user_with_default_role(company_id, role_code, UUID(ctx["employee"]["id"]))
        granted = _GRANTS[role_code]
        wrong: list[str] = []
        for method, path, body, any_of in _ROUTES:
            expected_allowed = bool(granted & any_of)
            request_headers = (
                {**headers, "If-Match": "1"}
                if method in ("POST", "PATCH", "PUT", "DELETE")
                else headers
            )
            response = await client.request(method, path, headers=request_headers, json=body)
            allowed = response.status_code != 403
            if response.status_code in (401, 500):
                wrong.append(f"{method} {path} -> {response.status_code} {response.text[:120]}")
            elif allowed != expected_allowed:
                wrong.append(
                    f"{method} {path}: expected {'allowed' if expected_allowed else 'denied'},"
                    f" got {response.status_code}"
                )
        assert not wrong, f"{role_code}:\n" + "\n".join(wrong)
    finally:
        await _teardown_year_setting(company_id=company_id)
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_default_roles_do_not_gain_administration_they_were_not_given(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Spelled out so a future grant that widens a role fails loudly here, not only in the matrix:
    no default role below COMPANY_ADMIN manages leave types, policies, year setting, combination
    rules or statutory minimums, and only HR_ADMIN and COMPANY_ADMIN can adjust or encash."""
    admin_headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, admin_headers)
        employee_id = UUID(ctx["employee"]["id"])
        admin_only = {
            LEAVE_TYPE_MANAGE,
            LEAVE_POLICY_MANAGE,
            LEAVE_YEAR_SETTING_MANAGE,
            LEAVE_COMBINATION_RULE_MANAGE,
            LEAVE_STATUTORY_MINIMUM_MANAGE,
        }
        for role_code in ("EMPLOYEE", "REPORTING_MANAGER", "BRANCH_MANAGER", "HR_ADMIN"):
            assert not (_GRANTS[role_code] & admin_only)
            headers = await _user_with_default_role(company_id, role_code, employee_id)
            for path in (
                "/v1/leave-policies",
                "/v1/leave-year-setting",
                "/v1/leave-combination-rules",
            ):
                assert (await client.get(path, headers=headers)).status_code == 403
            created = await client.post(
                "/v1/leave-types", headers=headers, json={"code": "X", "name": "X"}
            )
            assert created.status_code == 403
        # an employee also cannot see anyone else's balance or write one
        employee = await _user_with_default_role(company_id, "EMPLOYEE", employee_id)
        other = await client.get(f"/v1/leave-balances?employee_id={_ID}", headers=employee)
        assert other.status_code == 404  # visible scope is self only
        adjust = await client.post(
            "/v1/leave-ledger/adjustments",
            headers=employee,
            json={
                "employee_id": str(employee_id),
                "leave_type_id": ctx["leave_type"]["id"],
                "amount": "5",
                "effective_date": "2026-09-08",
                "reason": "self-service top-up",
            },
        )
        assert adjust.status_code == 403
    finally:
        await _teardown_year_setting(company_id=company_id)
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_an_employee_can_load_the_leave_types_the_apply_workflow_needs(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """LM-05: the employee role reads the active leave types without TYPE_MANAGE; an inactive
    type is hidden from it but still visible to a type manager."""
    admin_headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, admin_headers)
        retired = await client.post(
            "/v1/leave-types", headers=admin_headers, json={"code": "OLD", "name": "Retired"}
        )
        assert retired.status_code == 201, retired.text
        deactivated = await client.patch(
            f"/v1/leave-types/{retired.json()['data']['id']}",
            headers={**admin_headers, "If-Match": "1"},
            json={"is_active": False},
        )
        assert deactivated.status_code == 200, deactivated.text

        employee = await _user_with_default_role(
            company_id, "EMPLOYEE", UUID(ctx["employee"]["id"])
        )
        listed = await client.get("/v1/leave-types", headers=employee)
        assert listed.status_code == 200, listed.text
        codes = {t["code"] for t in listed.json()["data"]}
        assert codes == {"EL"}
        everything = await client.get("/v1/leave-types", headers=admin_headers)
        assert {t["code"] for t in everything.json()["data"]} == {"EL", "OLD"}
        # and still cannot write one
        write = await client.post(
            "/v1/leave-types", headers=employee, json={"code": "NEW", "name": "New"}
        )
        assert write.status_code == 403
    finally:
        await _teardown_year_setting(company_id=company_id)
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()
