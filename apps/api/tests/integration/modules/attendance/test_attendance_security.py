"""Security tests for W4 — data-scope enforcement on `/v1/attendance/*`.

Mirrors the F4/F8/F9 pattern already proven in `employee/test_employee_assignment.py`: a caller
holding a permission at a narrower `DataScope` than `COMPANY` must not see data outside that
scope, and an out-of-scope target must 404 (never 403, which would reveal existence). Also covers
permission-denied paths for the on-behalf-punch and recompute routes, and cross-tenant isolation.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from tests.integration.modules.attendance.test_attendance_day import (
    _build_wired_employee,
    _cleanup_attendance_day,
    _punch,
    _register_tenant,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup, _register

from hrms.core.auth.jwt import create_access_token
from hrms.core.auth.passwords import hash_password
from hrms.core.db.models.identity import (
    Permission,
    Role,
    RolePermission,
    Session,
    User,
    UserCompany,
    UserRole,
)
from hrms.core.db.session import get_session_factory

pytestmark = pytest.mark.asyncio


async def _create_permission_scoped_user(
    *,
    company_id: UUID,
    permission_codes: list[str],
    data_scope: str = "COMPANY",
    caller_employee_id: UUID | None = None,
) -> tuple[dict[str, str], UUID]:
    """Mirrors `employee/test_employee_assignment.py::_create_permission_scoped_user` — a fresh
    role holding exactly the given permission codes at the given `data_scope`, attached to a
    fresh user in the same company."""
    factory = get_session_factory()
    async with factory() as session:
        permissions = (
            (await session.execute(select(Permission).where(Permission.code.in_(permission_codes))))
            .scalars()
            .all()
        )
        assert len(permissions) == len(permission_codes)

        now = datetime.now(UTC)
        role_id = uuid4()
        session.add(
            Role(
                id=role_id,
                company_id=company_id,
                code=f"ATT_TEST_ROLE_{role_id.hex[:8]}",
                name="Attendance test role",
                is_system=False,
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        for permission in permissions:
            session.add(
                RolePermission(role_id=role_id, permission_id=permission.id, data_scope=data_scope)
            )

        scoped_user_id = uuid4()
        session.add(
            User(
                id=scoped_user_id,
                email=f"scoped-{scoped_user_id.hex[:8]}@example.com",
                password_hash=hash_password("CorrectHorse9"),
                status="ACTIVE",
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        user_company = UserCompany(
            id=uuid4(),
            user_id=scoped_user_id,
            company_id=company_id,
            is_primary=True,
            status="ACTIVE",
            created_at=now,
            updated_at=now,
        )
        session.add(user_company)
        await session.flush()
        session.add(UserRole(id=uuid4(), user_company_id=user_company.id, role_id=role_id))
        scoped_session_id = uuid4()
        session.add(
            Session(
                id=scoped_session_id,
                user_id=scoped_user_id,
                company_id=company_id,
                expires_at=now + timedelta(days=1),
            )
        )
        await session.commit()

    token = create_access_token(
        user_id=scoped_user_id,
        company_id=company_id,
        session_id=scoped_session_id,
        employee_id=caller_employee_id,
    )
    return (
        {"Authorization": f"Bearer {token}", "X-Company-Id": str(company_id)},
        scoped_user_id,
    )


async def _cleanup_scoped_users() -> None:
    from sqlalchemy import text

    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text(
                "DELETE FROM session WHERE user_id IN "
                "(SELECT id FROM \"user\" WHERE email LIKE 'scoped-%')"
            )
        )
        await session.execute(text("DELETE FROM \"user\" WHERE email LIKE 'scoped-%'"))
        await session.commit()


async def test_self_scope_sees_only_own_attendance_day(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    from hrms.modules.attendance.permissions import ATTENDANCE_VIEW

    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        self_employee_id = wired["employee"]["id"]
        await _punch(
            client, headers, employee_id=self_employee_id, hour=9, minute=0, direction="IN"
        )
        await _punch(
            client, headers, employee_id=self_employee_id, hour=18, minute=0, direction="OUT"
        )
        self_day = (
            await client.post(
                "/v1/attendance/days/calculate",
                headers=headers,
                params={"employee_id": self_employee_id, "date": "2026-08-10"},
            )
        ).json()["data"]

        # A second, bare employee (no employment/assignment) in the same company — `calculate`
        # still produces a real `AttendanceDay` row (`NOT_JOINED`), which is all this test
        # needs: a row belonging to someone other than the SELF-scoped caller. Reusing
        # `_build_wired_employee` here would fail — it always inserts a fresh COMPANY-scope
        # `WORK_CALENDAR`/`ATTENDANCE_POLICY` assignment, which overlaps the one `wired` above
        # already created at the same scope.
        other_employee_id = (
            await client.post("/v1/employees", headers=headers, json={"first_name": "Chetan"})
        ).json()["data"]["id"]
        other_day = (
            await client.post(
                "/v1/attendance/days/calculate",
                headers=headers,
                params={"employee_id": other_employee_id, "date": "2026-08-10"},
            )
        ).json()["data"]

        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[ATTENDANCE_VIEW],
            data_scope="SELF",
            caller_employee_id=UUID(self_employee_id),
        )

        own = await client.get(f"/v1/attendance/days/{self_day['id']}", headers=scoped_headers)
        assert own.status_code == 200

        # Permission granted, but the target falls outside SELF scope -> 404, never 403 (F4/F8/F9
        # pattern; a 403 would confirm the resource exists for a caller who can't see it).
        other = await client.get(f"/v1/attendance/days/{other_day['id']}", headers=scoped_headers)
        assert other.status_code == 404

        listed = await client.get(
            "/v1/attendance/days", headers=scoped_headers, params={"date_from": "2026-08-10"}
        )
        assert listed.status_code == 200
        ids = {row["id"] for row in listed.json()["data"]}
        assert ids == {self_day["id"]}
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_recompute_without_permission_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    from hrms.modules.attendance.permissions import ATTENDANCE_VIEW

    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _punch(client, headers, employee_id=employee_id, hour=9, minute=0, direction="IN")
        await _punch(client, headers, employee_id=employee_id, hour=18, minute=0, direction="OUT")
        day = (
            await client.post(
                "/v1/attendance/days/calculate",
                headers=headers,
                params={"employee_id": employee_id, "date": "2026-08-10"},
            )
        ).json()["data"]

        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=[ATTENDANCE_VIEW], data_scope="COMPANY"
        )
        response = await client.post(
            f"/v1/attendance/days/{day['id']}/recompute", headers=scoped_headers
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_on_behalf_punch_without_permission_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A caller holding only `ATTENDANCE.PUNCH` (SELF) may not punch on behalf of someone
    else — the dynamic permission dispatch (mirrors `create_assignment`) must reject it, not
    silently downgrade to a self-punch for the wrong employee."""
    from hrms.modules.attendance.permissions import ATTENDANCE_PUNCH

    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        target_employee_id = wired["employee"]["id"]

        scoped_headers, scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=[ATTENDANCE_PUNCH], data_scope="SELF"
        )
        response = await client.post(
            "/v1/attendance/punches",
            headers=scoped_headers,
            json={
                "employee_id": target_employee_id,
                "punch_time": "2026-08-10T09:00:00Z",
                "direction": "IN",
            },
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_cross_tenant_punch_list_isolated(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        wired_a = await _build_wired_employee(client, headers_a)
        await _punch(
            client,
            headers_a,
            employee_id=wired_a["employee"]["id"],
            hour=9,
            minute=0,
            direction="IN",
        )

        listed_b = await client.get("/v1/attendance/punches", headers=headers_b)
        assert listed_b.status_code == 200
        assert listed_b.json()["data"] == []
    finally:
        await _cleanup_attendance_day(company_id=company_a)
        await _cleanup(company_id=company_a, user_id=user_a)
        await _cleanup_attendance_day(company_id=company_b)
        await _cleanup(company_id=company_b, user_id=user_b)


async def test_unauthenticated_request_rejected(client: AsyncClient) -> None:
    response = await client.get("/v1/attendance/days")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# REPORTEES / REPORTEE_TREE — W4 prompt explicitly requires all four DataScope
# levels exercised against attendance, not just SELF/COMPANY (already above).
# ---------------------------------------------------------------------------


async def _add_reportee_employee(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    wired: dict[str, Any],
    first_name: str,
    reporting_manager_id: UUID | None,
    joining_date: str = "2026-01-01",
) -> dict[str, Any]:
    """Adds one more employee onto the org graph `_build_wired_employee` already created —
    employment + an assignment reusing the same branch/shift (so it resolves against the same
    COMPANY-scope `WORK_CALENDAR`/`ATTENDANCE_POLICY` assignments `_build_wired_employee` made),
    with `reporting_manager_id` set so REPORTEES/REPORTEE_TREE have a real hierarchy to walk.
    Calling `_build_wired_employee` a second time in the same test would fail — it always inserts
    a fresh COMPANY-scope calendar/policy `PolicyAssignment`, which overlaps the first call's."""
    employee = (
        await client.post("/v1/employees", headers=headers, json={"first_name": first_name})
    ).json()["data"]
    legal_entity = (
        await client.post("/v1/legal-entities", headers=headers, json={"name": f"{first_name} LE"})
    ).json()["data"]
    employment = await client.post(
        f"/v1/employees/{employee['id']}/employments",
        headers=headers,
        json={"legal_entity_id": legal_entity["id"], "joining_date": joining_date},
    )
    assert employment.status_code == 201, employment.text
    department = (
        await client.post(
            "/v1/departments",
            headers=headers,
            json={"name": f"{first_name} Dept", "branch_id": wired["branch"]["id"]},
        )
    ).json()["data"]
    designation = (
        await client.post(
            "/v1/designations",
            headers=headers,
            json={"title": f"{first_name} Role", "department_id": department["id"]},
        )
    ).json()["data"]
    assignment = await client.post(
        f"/v1/employees/{employee['id']}/assignments",
        headers=headers,
        json={
            "effective_from": joining_date,
            "change_type": "INITIAL",
            "branch_id": wired["branch"]["id"],
            "department_id": department["id"],
            "designation_id": designation["id"],
            "shift_id": wired["shift"]["id"],
            "reporting_manager_id": str(reporting_manager_id) if reporting_manager_id else None,
        },
    )
    assert assignment.status_code == 201, assignment.text
    return dict(employee)


async def _calculate_day(
    client: AsyncClient, headers: dict[str, str], *, employee_id: str, day: str = "2026-08-10"
) -> dict[str, Any]:
    await _punch(
        client, headers, employee_id=employee_id, hour=9, minute=0, direction="IN", day=day
    )
    await _punch(
        client, headers, employee_id=employee_id, hour=18, minute=0, direction="OUT", day=day
    )
    response = await client.post(
        "/v1/attendance/days/calculate",
        headers=headers,
        params={"employee_id": employee_id, "date": day},
    )
    assert response.status_code == 200, response.text
    return dict(response.json()["data"])


async def test_reportees_scope_sees_direct_reports_only(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    from hrms.modules.attendance.permissions import ATTENDANCE_VIEW

    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        manager_id = wired["employee"]["id"]
        reportee = await _add_reportee_employee(
            client,
            headers,
            wired=wired,
            first_name="Reportee",
            reporting_manager_id=UUID(manager_id),
        )
        # Reports to the reportee, not directly to the manager — must stay invisible under
        # REPORTEES (only REPORTEE_TREE would see this one).
        grandchild = await _add_reportee_employee(
            client,
            headers,
            wired=wired,
            first_name="Grandchild",
            reporting_manager_id=UUID(reportee["id"]),
        )
        stranger = await _add_reportee_employee(
            client, headers, wired=wired, first_name="Stranger", reporting_manager_id=None
        )

        reportee_day = await _calculate_day(client, headers, employee_id=reportee["id"])
        grandchild_day = await _calculate_day(client, headers, employee_id=grandchild["id"])
        stranger_day = await _calculate_day(client, headers, employee_id=stranger["id"])

        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[ATTENDANCE_VIEW],
            data_scope="REPORTEES",
            caller_employee_id=UUID(manager_id),
        )

        ok = await client.get(f"/v1/attendance/days/{reportee_day['id']}", headers=scoped_headers)
        assert ok.status_code == 200

        for day in (grandchild_day, stranger_day):
            resp = await client.get(f"/v1/attendance/days/{day['id']}", headers=scoped_headers)
            assert resp.status_code == 404

        listed = await client.get(
            "/v1/attendance/days", headers=scoped_headers, params={"date_from": "2026-08-10"}
        )
        assert listed.status_code == 200
        assert {row["id"] for row in listed.json()["data"]} == {reportee_day["id"]}
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_reportee_tree_scope_sees_descendants_not_unrelated_branch(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    from hrms.modules.attendance.permissions import ATTENDANCE_VIEW

    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        top_id = wired["employee"]["id"]
        sub_manager = await _add_reportee_employee(
            client, headers, wired=wired, first_name="SubManager", reporting_manager_id=UUID(top_id)
        )
        leaf = await _add_reportee_employee(
            client,
            headers,
            wired=wired,
            first_name="Leaf",
            reporting_manager_id=UUID(sub_manager["id"]),
        )
        unrelated = await _add_reportee_employee(
            client, headers, wired=wired, first_name="Unrelated", reporting_manager_id=None
        )

        sub_manager_day = await _calculate_day(client, headers, employee_id=sub_manager["id"])
        leaf_day = await _calculate_day(client, headers, employee_id=leaf["id"])
        unrelated_day = await _calculate_day(client, headers, employee_id=unrelated["id"])

        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[ATTENDANCE_VIEW],
            data_scope="REPORTEE_TREE",
            caller_employee_id=UUID(top_id),
        )

        for day in (sub_manager_day, leaf_day):
            resp = await client.get(f"/v1/attendance/days/{day['id']}", headers=scoped_headers)
            assert resp.status_code == 200

        resp = await client.get(
            f"/v1/attendance/days/{unrelated_day['id']}", headers=scoped_headers
        )
        assert resp.status_code == 404

        listed = await client.get(
            "/v1/attendance/days", headers=scoped_headers, params={"date_from": "2026-08-10"}
        )
        assert listed.status_code == 200
        assert {row["id"] for row in listed.json()["data"]} == {
            sub_manager_day["id"],
            leaf_day["id"],
        }
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


# ---------------------------------------------------------------------------
# Forged company ID — a caller authenticated for company A cannot read company B's attendance
# by presenting a mismatched `X-Company-Id` header (`get_tenant_context` compares it against
# the JWT's own `company_id` claim, not the raw header, before any RLS/scope resolution runs).
# ---------------------------------------------------------------------------


async def test_forged_company_id_header_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    response_b, company_b, user_b = await _register(client)
    assert response_b.status_code == 201
    try:
        forged_headers = {**headers_a, "X-Company-Id": str(company_b)}
        response = await client.get("/v1/attendance/days", headers=forged_headers)
        assert response.status_code == 404
    finally:
        await _cleanup_attendance_day(company_id=company_a)
        await _cleanup(company_id=company_a, user_id=user_a)
        await _cleanup_attendance_day(company_id=company_b)
        await _cleanup(company_id=company_b, user_id=user_b)
