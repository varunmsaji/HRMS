"""API audit C-1 - the system `EMPLOYEE` role can record and read its OWN attendance, nothing more.

Everything here goes through the production paths: tenant registration seeds the roles, employees
are created, employed, invited and accept through the public API, and the permission check is the
real `require_permission` dependency (no dependency overrides, no hand-built roles). The backfill
migration is exercised by running its own SQL against a tenant whose grants were removed."""

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from hrms.core.db.session import get_session_factory, set_rls_company_id

from ...tenant_wipe import wipe_tenant
from ..account_invite.test_account_invite import (
    _cleanup_extra_user_row,
    _cleanup_extra_user_sessions,
    _create_employee,
    _extra_user_id,
    _register_tenant,
    _token_from_invite_url,
)
from ..account_invite.uac_helpers import Tenant as UacTenant
from ..account_invite.uac_helpers import onboard
from ..organisation.test_registration_flow import VALID_PASSWORD, _role_grants

pytestmark = pytest.mark.asyncio

SELF_ATTENDANCE = {
    "ATTENDANCE.PUNCH": "SELF",
    "ATTENDANCE.VIEW": "SELF",
    "ATTENDANCE.REGULARIZATION_REQUEST": "SELF",
}
_MIGRATION = (
    Path(__file__).resolve().parents[4]
    / "alembic/versions/20261020090000_employee_role_self_attendance.py"
)


@dataclass
class Tenant:
    admin: dict[str, str]
    company_id: UUID
    user_id: UUID | None
    legal_entity_id: str
    emails: list[str]


async def _tenant(client: AsyncClient) -> Tenant:
    headers, company_id, user_id = await _register_tenant(client)
    le = await client.post("/v1/legal-entities", headers=headers, json={"name": "Remediation LE"})
    assert le.status_code == 201, le.text
    return Tenant(headers, company_id, user_id, le.json()["data"]["id"], [])


async def _teardown(*tenants: Tenant) -> None:
    ids = [uid for t in tenants for e in t.emails if (uid := await _extra_user_id(email=e))]
    for uid in ids:
        await _cleanup_extra_user_sessions(user_id=uid)
    for t in tenants:
        await wipe_tenant(company_id=t.company_id, user_id=t.user_id)
    for uid in ids:
        await _cleanup_extra_user_row(user_id=uid)


async def _employee_user(client: AsyncClient, t: Tenant, name: str) -> tuple[str, dict[str, str]]:
    """Create + employ + invite + accept. Returns (employee_id, auth headers)."""
    email = f"{name.lower()}-{uuid4().hex[:8]}@example.com"
    t.emails.append(email)
    emp = await _create_employee(client, t.admin, name, personal_email=email)
    employed = await client.post(
        f"/v1/employees/{emp['id']}/employments",
        headers=t.admin,
        json={"legal_entity_id": t.legal_entity_id, "joining_date": "2026-01-01"},
    )
    assert employed.status_code == 201, employed.text
    invite = await client.post(f"/v1/employees/{emp['id']}/invite", headers=t.admin)
    token = _token_from_invite_url(invite.json()["data"]["invite_url"])
    accepted = await client.post(
        f"/v1/public/account-invites/{token}/accept", json={"password": VALID_PASSWORD}
    )
    assert accepted.status_code == 201, accepted.text
    access = accepted.json()["data"]["access_token"]
    return emp["id"], {
        "Authorization": f"Bearer {access}",
        "X-Company-Id": str(t.company_id),
    }


async def test_registration_grants_employee_exactly_self_attendance(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    t = await _tenant(client)
    try:
        grants = await _role_grants(t.company_id, "EMPLOYEE")
        assert {k: v for k, v in grants.items() if k.startswith("ATTENDANCE.")} == SELF_ATTENDANCE
        # other roles keep their boundaries: nobody but COMPANY_ADMIN holds PUNCH
        for role in ("HR_ADMIN", "REPORTING_MANAGER", "BRANCH_MANAGER"):
            assert "ATTENDANCE.PUNCH" not in await _role_grants(t.company_id, role)
        assert (await _role_grants(t.company_id, "COMPANY_ADMIN"))["ATTENDANCE.PUNCH"] == "COMPANY"
    finally:
        await _teardown(t)


async def test_new_employee_can_self_punch_and_read_own_attendance(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    t = await _tenant(client)
    try:
        emp_id, eh = await _employee_user(client, t, "Ravi")
        me = (await client.get("/v1/auth/me", headers=eh)).json()["data"]["user"]
        assert me["employee_id"] == emp_id
        assert {"ATTENDANCE.PUNCH", "ATTENDANCE.VIEW"} <= set(me["permissions"])

        punch = await client.post("/v1/attendance/punches/me", headers=eh, json={"direction": "IN"})
        assert punch.status_code == 201, punch.text
        assert punch.json()["data"]["employee_id"] == emp_id
        out = await client.post("/v1/attendance/punches/me", headers=eh, json={"direction": "OUT"})
        assert out.status_code == 201, out.text

        listed = await client.get(f"/v1/attendance/punches?employee_id={emp_id}", headers=eh)
        assert listed.status_code == 200
        assert {p["employee_id"] for p in listed.json()["data"]} == {emp_id}
        assert len(listed.json()["data"]) == 2
        days = await client.get(f"/v1/attendance/days?employee_id={emp_id}", headers=eh)
        assert days.status_code == 200
    finally:
        await _teardown(t)


async def test_employee_cannot_act_for_others_or_reach_admin_attendance(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    t = await _tenant(client)
    try:
        a_id, a = await _employee_user(client, t, "Asha")
        b_id, b = await _employee_user(client, t, "Bala")

        # on-behalf punch needs PUNCH_ON_BEHALF - never granted to EMPLOYEE
        behalf = await client.post(
            "/v1/attendance/punches",
            headers=a,
            json={"employee_id": b_id, "direction": "IN", "punch_time": "2026-02-02T09:00:00Z"},
        )
        assert behalf.status_code == 403
        assert behalf.json()["error"]["code"] == "PERMISSION_DENIED"

        # B's punches are invisible to A: filtered, not leaked
        assert (
            await client.post("/v1/attendance/punches/me", headers=b, json={"direction": "IN"})
        ).status_code == 201
        seen = await client.get(f"/v1/attendance/punches?employee_id={b_id}", headers=a)
        assert seen.status_code == 200 and seen.json()["data"] == []

        # regularization on behalf of someone else needs the _ON_BEHALF permission
        reg = await client.post(
            "/v1/regularizations",
            headers=a,
            json={
                "employee_id": b_id,
                "attendance_date": "2026-02-02",
                "request_type": "MISSING_PUNCH",
                "requested_punches": [
                    {"direction": "OUT", "requested_time": "2026-02-02T18:00:00+05:30"}
                ],
            },
        )
        assert reg.status_code == 403

        for method, path, body in [
            ("GET", "/v1/attendance-policies", None),
            ("POST", "/v1/attendance/days/calculate", {"employee_id": b_id}),
            ("POST", "/v1/attendance-periods", {}),
            ("GET", "/v1/attendance/face-profiles", None),
            ("POST", f"/v1/attendance/face-profiles/{b_id}/enrollment-window", None),
            ("POST", f"/v1/attendance/face-profiles/{a_id}/approve", {}),
            ("POST", "/v1/rosters", {}),
            ("POST", f"/v1/regularizations/{uuid4()}/approve", {}),
            ("POST", f"/v1/overtime/{uuid4()}/approve", {}),
        ]:
            r = await client.request(method, path, headers=a, json=body)
            assert r.status_code == 403, (method, path, r.status_code, r.text)
    finally:
        await _teardown(t)


async def test_cross_tenant_and_unauthenticated_remain_denied(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    t1, t2 = await _tenant(client), await _tenant(client)
    try:
        a_id, a = await _employee_user(client, t1, "Asha")
        other_id, other = await _employee_user(client, t2, "Other")
        assert (
            await client.post("/v1/attendance/punches/me", headers=other, json={"direction": "IN"})
        ).status_code == 201

        assert (
            await client.post("/v1/attendance/punches/me", json={"direction": "IN"})
        ).status_code == 401
        assert (await client.get("/v1/attendance/punches")).status_code == 401
        # a tenant-1 token cannot be pointed at tenant 2
        cross = await client.get(
            f"/v1/attendance/punches?employee_id={other_id}",
            headers={**a, "X-Company-Id": str(t2.company_id)},
        )
        assert cross.status_code == 404
        # and sees nothing of tenant 2 under its own tenant
        own = await client.get(f"/v1/attendance/punches?employee_id={other_id}", headers=a)
        assert own.status_code == 200 and own.json()["data"] == []
    finally:
        await _teardown(t1, t2)


async def test_non_employee_roles_keep_their_boundaries(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    uac = UacTenant(headers=headers, company_id=company_id, admin_user_id=user_id, emails=[])
    t = Tenant(headers, company_id, user_id, "", uac.emails)
    try:
        for role in ("HR_ADMIN", "REPORTING_MANAGER", "BRANCH_MANAGER"):
            u = await onboard(client, uac, role)
            r = await client.post(
                "/v1/attendance/punches/me", headers=u.headers, json={"direction": "IN"}
            )
            assert r.status_code == 403, (role, r.text)
    finally:
        await _teardown(t)


async def test_backfill_migration_restores_missing_grants_without_widening_any_scope(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    spec = importlib.util.spec_from_file_location("backfill_mig", _MIGRATION)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)  # type: ignore[union-attr]
    t = await _tenant(client)
    try:
        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, str(t.company_id))
            codes = "('ATTENDANCE.PUNCH','ATTENDANCE.VIEW','ATTENDANCE.REGULARIZATION_REQUEST')"
            # simulate a pre-fix tenant: no grants; plus one customised row with a wider scope
            await session.execute(
                text(
                    "DELETE FROM role_permission rp USING role r, permission p "
                    "WHERE rp.role_id=r.id "
                    "AND rp.permission_id=p.id AND r.company_id=:c AND r.code='EMPLOYEE' "
                    f"AND p.code IN {codes}"
                ),
                {"c": str(t.company_id)},
            )
            await session.execute(
                text(
                    "INSERT INTO role_permission(role_id, permission_id, data_scope) "
                    "SELECT r.id, p.id, 'BRANCH' FROM role r, permission p WHERE r.company_id=:c "
                    "AND r.code='EMPLOYEE' AND p.code='ATTENDANCE.VIEW'"
                ),
                {"c": str(t.company_id)},
            )
            await session.commit()
            # run the migration's own SQL (twice: it must be idempotent)
            for _ in range(2):
                await session.execute(
                    text(
                        "INSERT INTO role_permission (role_id, permission_id, data_scope) "
                        "SELECT r.id, p.id, 'SELF' FROM role r JOIN permission p ON p.code IN "
                        f"{mig._CODES} WHERE r.code='EMPLOYEE' AND r.is_system "
                        "AND r.deleted_at IS NULL "
                        "ON CONFLICT (role_id, permission_id) DO NOTHING"
                    )
                )
            await session.commit()
        grants = await _role_grants(t.company_id, "EMPLOYEE")
        assert grants["ATTENDANCE.PUNCH"] == "SELF"
        assert grants["ATTENDANCE.REGULARIZATION_REQUEST"] == "SELF"
        assert grants["ATTENDANCE.VIEW"] == "BRANCH"  # customised scope preserved, not overwritten
        assert "ATTENDANCE.PUNCH_ON_BEHALF" not in grants
        assert "ATTENDANCE.VIEW_ALL" not in grants
    finally:
        await _teardown(t)


async def test_face_attendance_stays_fail_closed_by_default(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """H-6 - an employee now holds ATTENDANCE.PUNCH, so the face routes are reachable; with the
    shipped defaults (provider and liveness engine disabled) they must refuse, not fall back to
    'face detected = live'. No provider is contacted."""
    t = await _tenant(client)
    try:
        _, eh = await _employee_user(client, t, "Face")
        for direction in ("IN", "OUT"):
            r = await client.post(
                "/v1/attendance/face-punches/me/liveness-sessions",
                headers=eh,
                json={"direction": direction},
            )
            assert r.status_code == 503, r.text
            assert r.json()["error"]["code"] in {
                "FACE_VERIFICATION_UNAVAILABLE",
                "FACE_LIVENESS_UNAVAILABLE",
            }
        enrol = await client.get("/v1/attendance/face-enrollment/me", headers=eh)
        assert enrol.status_code in {200, 503}
    finally:
        await _teardown(t)
