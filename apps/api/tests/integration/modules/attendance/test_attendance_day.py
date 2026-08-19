"""Integration tests for W4 — `/v1/attendance/punches`, `/v1/attendance/days*`.

Builds the full graph the calculation pipeline reads (architecture §19.1): employee + employment
+ assignment (with `shift_id`) + a published FIXED `ShiftVersion` + a COMPANY-scoped
`WORK_CALENDAR` assignment + a published `AttendancePolicy` with an hour band, COMPANY-assigned —
then submits real punches through the HTTP API and asserts the computed `AttendanceDay`. Real
Postgres, real RLS, real `hrms_app` role via the app's normal session (not the migration role).
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text, update
from tests.integration.modules.organisation.test_registration_flow import _cleanup, _register

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.attendance.models import AttendanceDay

pytestmark = pytest.mark.asyncio


async def _register_tenant(
    client: AsyncClient, **overrides: Any
) -> tuple[dict[str, str], UUID, UUID | None]:
    response, company_id, user_id = await _register(client, **overrides)
    assert response.status_code == 201, response.text
    assert company_id is not None
    data = response.json()["data"]
    return (
        {
            "Authorization": f"Bearer {data['access_token']}",
            "X-Company-Id": str(company_id),
        },
        company_id,
        user_id,
    )


async def _build_wired_employee(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    joining_date: str = "2026-01-01",
) -> dict[str, Any]:
    """Employee + employment + assignment (with `shift_id`) + a published FIXED 09:00-18:00
    shift + a COMPANY `WORK_CALENDAR` assignment + a published Attendance Policy (one hour band,
    `PRESENT` from 240 minutes) COMPANY-assigned. Everything needed for `evaluate_day` to reach
    a real `PRESENT`/`ABSENT` verdict rather than `CONFIG_ERROR`."""
    employee = (
        await client.post("/v1/employees", headers=headers, json={"first_name": "Asha"})
    ).json()["data"]

    legal_entity = (
        await client.post("/v1/legal-entities", headers=headers, json={"name": "Acme LE"})
    ).json()["data"]
    branch = (
        await client.post(
            "/v1/branches",
            headers=headers,
            json={"legal_entity_id": legal_entity["id"], "name": "HQ", "timezone": "UTC"},
        )
    ).json()["data"]
    department = (
        await client.post(
            "/v1/departments",
            headers=headers,
            json={"name": "Engineering", "branch_id": branch["id"]},
        )
    ).json()["data"]
    designation = (
        await client.post(
            "/v1/designations",
            headers=headers,
            json={"title": "Software Engineer", "department_id": department["id"]},
        )
    ).json()["data"]

    employment = await client.post(
        f"/v1/employees/{employee['id']}/employments",
        headers=headers,
        json={"legal_entity_id": legal_entity["id"], "joining_date": joining_date},
    )
    assert employment.status_code == 201, employment.text

    shift = (
        await client.post("/v1/shifts", headers=headers, json={"name": "General", "code": "GEN"})
    ).json()["data"]
    draft_id = shift["draft_version_id"]
    patched = await client.patch(
        f"/v1/shifts/{shift['id']}/versions/{draft_id}",
        headers={**headers, "If-Match": "1"},
        json={
            "shift_type": "FIXED",
            "effective_from": "2026-01-01",
            "start_time": "09:00",
            "end_time": "18:00",
            "timezone": "UTC",
        },
    )
    assert patched.status_code == 200, patched.text
    published = await client.post(
        f"/v1/shifts/{shift['id']}/versions/{draft_id}/publish",
        headers={**headers, "If-Match": "2"},
        json={},
    )
    assert published.status_code == 200, published.text

    assignment = await client.post(
        f"/v1/employees/{employee['id']}/assignments",
        headers=headers,
        json={
            "effective_from": joining_date,
            "change_type": "INITIAL",
            "branch_id": branch["id"],
            "department_id": department["id"],
            "designation_id": designation["id"],
            "shift_id": shift["id"],
        },
    )
    assert assignment.status_code == 201, assignment.text

    work_calendar = (
        await client.post("/v1/work-calendars", headers=headers, json={"name": "Default"})
    ).json()["data"]
    calendar_assignment = await client.post(
        "/v1/policy-assignments",
        headers=headers,
        json={
            "policy_kind": "WORK_CALENDAR",
            "policy_id": work_calendar["id"],
            "scope_type": "COMPANY",
            "effective_from": "2026-01-01",
        },
    )
    assert calendar_assignment.status_code == 201, calendar_assignment.text

    policy = (
        await client.post(
            "/v1/attendance-policies", headers=headers, json={"name": "Standard Policy"}
        )
    ).json()["data"]
    draft = (
        await client.post(
            f"/v1/attendance-policies/{policy['id']}/versions",
            headers=headers,
            json={
                "effective_from": "2026-01-01",
                "hour_bands": [
                    {"min_minutes": 0, "max_minutes": 239, "result_status": "ABSENT"},
                    {"min_minutes": 240, "max_minutes": None, "result_status": "PRESENT"},
                ],
            },
        )
    ).json()["data"]
    publish = await client.post(
        f"/v1/attendance-policies/{policy['id']}/versions/{draft['id']}/publish",
        headers={**headers, "If-Match": "1"},
        json={},
    )
    assert publish.status_code == 200, publish.text
    policy_assignment = await client.post(
        "/v1/policy-assignments",
        headers=headers,
        json={
            "policy_kind": "ATTENDANCE_POLICY",
            "policy_id": policy["id"],
            "scope_type": "COMPANY",
            "effective_from": "2026-01-01",
        },
    )
    assert policy_assignment.status_code == 201, policy_assignment.text

    return {"employee": employee, "shift": shift, "branch": branch}


async def _punch(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    employee_id: str | None = None,
    hour: int,
    minute: int,
    direction: str,
    day: str = "2026-08-10",
    **extra: Any,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "punch_time": f"{day}T{hour:02d}:{minute:02d}:00Z",
        "direction": direction,
        **extra,
    }
    if employee_id is not None:
        body["employee_id"] = employee_id
    response = await client.post("/v1/attendance/punches", headers=headers, json=body)
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _cleanup_attendance_day(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        for table in (
            "attendance_break",
            "attendance_day",
            "punch",
            "policy_assignment",
            "attendance_policy_version",
            "attendance_policy",
            "work_calendar",
            "employee_assignment",
            "employment",
            "shift_version",
            "shift",
            "number_series",
            "employee",
            "designation",
            "department",
            "branch",
            "legal_entity",
        ):
            await session.execute(
                text(f"DELETE FROM {table} WHERE company_id = :cid"), {"cid": str(company_id)}
            )
        await session.commit()


async def test_full_pipeline_present_day(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]

        await _punch(client, headers, employee_id=employee_id, hour=9, minute=0, direction="IN")
        await _punch(client, headers, employee_id=employee_id, hour=18, minute=0, direction="OUT")

        response = await client.post(
            "/v1/attendance/days/calculate",
            headers=headers,
            params={"employee_id": employee_id, "date": "2026-08-10"},
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["attendance_status"] == "PRESENT"
        assert data["worked_minutes"] == 540
        assert data["calendar_day_type"] == "WORKING"
        assert data["calculation_version"] == 1
        assert data["computation_snapshot"] is not None
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_not_joined_before_employment_gate(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Employment gate (§19.1 step 1) is checked *before* calendar/policy resolution — an
    employee with no employment record at all is `NOT_JOINED`, not `CONFIG_ERROR`."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = (
            await client.post("/v1/employees", headers=headers, json={"first_name": "Bala"})
        ).json()["data"]
        response = await client.post(
            "/v1/attendance/days/calculate",
            headers=headers,
            params={"employee_id": employee["id"], "date": "2026-08-10"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["attendance_status"] == "NOT_JOINED"
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_config_incomplete_without_policy_assignment(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Employed, but no `ATTENDANCE_POLICY` assignment anywhere -> `CONFIG_ERROR`, never a
    guessed PRESENT/ABSENT (WD-21 fail closed)."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = (
            await client.post("/v1/employees", headers=headers, json={"first_name": "Bala"})
        ).json()["data"]
        legal_entity = (
            await client.post("/v1/legal-entities", headers=headers, json={"name": "Acme LE"})
        ).json()["data"]
        employment = await client.post(
            f"/v1/employees/{employee['id']}/employments",
            headers=headers,
            json={"legal_entity_id": legal_entity["id"], "joining_date": "2026-01-01"},
        )
        assert employment.status_code == 201, employment.text

        response = await client.post(
            "/v1/attendance/days/calculate",
            headers=headers,
            params={"employee_id": employee["id"], "date": "2026-08-10"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["attendance_status"] == "CONFIG_ERROR"
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_recompute_replaces_derived_fields(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]

        await _punch(client, headers, employee_id=employee_id, hour=9, minute=0, direction="IN")
        await _punch(client, headers, employee_id=employee_id, hour=13, minute=0, direction="OUT")

        first = await client.post(
            "/v1/attendance/days/calculate",
            headers=headers,
            params={"employee_id": employee_id, "date": "2026-08-10"},
        )
        assert first.status_code == 200, first.text
        first_data = first.json()["data"]
        assert first_data["worked_minutes"] == 240
        assert first_data["attendance_status"] == "PRESENT"  # exactly the 240m band boundary

        await _punch(client, headers, employee_id=employee_id, hour=14, minute=0, direction="IN")
        await _punch(client, headers, employee_id=employee_id, hour=18, minute=0, direction="OUT")

        recomputed = await client.post(
            f"/v1/attendance/days/{first_data['id']}/recompute", headers=headers
        )
        assert recomputed.status_code == 200, recomputed.text
        second_data = recomputed.json()["data"]
        assert second_data["id"] == first_data["id"]
        assert second_data["worked_minutes"] == 480
        assert second_data["attendance_status"] == "PRESENT"
        assert second_data["calculation_version"] == 2
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_locked_day_refuses_recompute(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """No W4 API can lock a day (W8 owns `AttendanceLock`) — this flips the flag directly to
    prove the refusal path (WD-11) is wired and ready."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _punch(client, headers, employee_id=employee_id, hour=9, minute=0, direction="IN")
        await _punch(client, headers, employee_id=employee_id, hour=18, minute=0, direction="OUT")
        calculated = await client.post(
            "/v1/attendance/days/calculate",
            headers=headers,
            params={"employee_id": employee_id, "date": "2026-08-10"},
        )
        day_id = calculated.json()["data"]["id"]

        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, str(company_id))
            await session.execute(
                update(AttendanceDay)
                .where(AttendanceDay.id == UUID(day_id))
                .values(is_locked=True, locked_at=datetime.now(UTC))
            )
            await session.commit()

        response = await client.post(f"/v1/attendance/days/{day_id}/recompute", headers=headers)
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "ATTENDANCE_DAY_LOCKED"
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_cross_tenant_attendance_day_not_found(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers_a)
        employee_id = wired["employee"]["id"]
        await _punch(client, headers_a, employee_id=employee_id, hour=9, minute=0, direction="IN")
        await _punch(client, headers_a, employee_id=employee_id, hour=18, minute=0, direction="OUT")
        calculated = await client.post(
            "/v1/attendance/days/calculate",
            headers=headers_a,
            params={"employee_id": employee_id, "date": "2026-08-10"},
        )
        day_id = calculated.json()["data"]["id"]

        response = await client.get(f"/v1/attendance/days/{day_id}", headers=headers_b)
        assert response.status_code == 404
    finally:
        await _cleanup_attendance_day(company_id=company_a)
        await _cleanup(company_id=company_a, user_id=user_a)
        await _cleanup_attendance_day(company_id=company_b)
        await _cleanup(company_id=company_b, user_id=user_b)


async def test_punch_idempotency_key_replays_same_row(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]

        first = await _punch(
            client,
            headers,
            employee_id=employee_id,
            hour=9,
            minute=0,
            direction="IN",
            idempotency_key="device-abc-123",
        )
        second = await _punch(
            client,
            headers,
            employee_id=employee_id,
            hour=9,
            minute=0,
            direction="IN",
            idempotency_key="device-abc-123",
        )
        assert first["id"] == second["id"]

        listed = await client.get(
            "/v1/attendance/punches", headers=headers, params={"employee_id": employee_id}
        )
        assert listed.status_code == 200
        assert len(listed.json()["data"]) == 1
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_on_behalf_punch_requires_permission(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A caller with no linked `employee_id` (e.g. this test's registering admin) may still
    punch on behalf of a real employee, since `COMPANY_ADMIN` holds `ATTENDANCE.PUNCH_ON_BEHALF`
    — this proves the dynamic on-behalf permission dispatch actually fires (mirrors
    `employee/router.py::create_assignment`'s pattern) rather than silently no-op'ing."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        punch = await _punch(
            client, headers, employee_id=employee_id, hour=9, minute=0, direction="IN"
        )
        assert punch["source"] == "ADMIN"
        assert punch["employee_id"] == employee_id
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
