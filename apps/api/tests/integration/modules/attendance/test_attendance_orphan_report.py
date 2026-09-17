"""Phase 8 — the orphan-punch report (`TZ-08`/`DEC-TZ-16`, execution gate §16.4,
`AttendanceDayService.list_orphaned_punches`).

Three things this proves that no other test file covers:

1. A punch outside its shift's ±2h padded load window is reported; one inside is not — the
   report actually reflects `calculation.py`'s own window math, not an independent guess at it.
2. `SR-14` — a no-shift employee's window is the **full local calendar day, no pad**, not the
   ±2h shape every shift-bearing employee gets. The same late-night punch time (23:45 local) is
   reported for a shift-bearing employee (outside their `07:00-20:00` padded window) but NOT
   reported for a no-shift employee (inside their `00:00-24:00` calendar-day window) — proving
   the report applies the right shape to each, not one shape to everyone.
3. A punch on a date no `AttendanceDay` was ever computed for is reported — inserted directly at
   the DB layer (bypassing `PunchService`) specifically so Phase 8's own best-effort immediate
   calculate (`service.py::PunchService._try_immediate_calculate`) does not create the very row
   this case needs to be *absent*.
"""

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from tests.integration.modules.attendance.test_attendance_day import (
    _build_wired_employee,
    _cleanup_attendance_day,
    _punch,
    _register_tenant,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.attendance.models import Punch
from hrms.modules.attendance.service import AttendanceDayService

pytestmark = pytest.mark.asyncio


async def _build_employee_no_shift(
    client: AsyncClient, headers: dict[str, str], *, joining_date: str = "2026-01-01"
) -> dict[str, Any]:
    """`_build_wired_employee`'s twin, minus the shift — an assignment with `shift_id` omitted
    (nullable, `employee/schemas.py`), everything else identical so the only variable between the
    two fixtures is whether a shift resolves."""
    employee = (
        await client.post("/v1/employees", headers=headers, json={"first_name": "Chitra"})
    ).json()["data"]
    legal_entity = (
        await client.post("/v1/legal-entities", headers=headers, json={"name": "Acme LE 2"})
    ).json()["data"]
    branch = (
        await client.post(
            "/v1/branches",
            headers=headers,
            json={"legal_entity_id": legal_entity["id"], "name": "Remote", "timezone": "UTC"},
        )
    ).json()["data"]
    department = (
        await client.post(
            "/v1/departments",
            headers=headers,
            json={"name": "Ops", "branch_id": branch["id"]},
        )
    ).json()["data"]
    designation = (
        await client.post(
            "/v1/designations",
            headers=headers,
            json={"title": "Field Agent", "department_id": department["id"]},
        )
    ).json()["data"]

    employment = await client.post(
        f"/v1/employees/{employee['id']}/employments",
        headers=headers,
        json={"legal_entity_id": legal_entity["id"], "joining_date": joining_date},
    )
    assert employment.status_code == 201, employment.text

    assignment = await client.post(
        f"/v1/employees/{employee['id']}/assignments",
        headers=headers,
        json={
            "effective_from": joining_date,
            "change_type": "INITIAL",
            "branch_id": branch["id"],
            "department_id": department["id"],
            "designation_id": designation["id"],
        },
    )
    assert assignment.status_code == 201, assignment.text

    work_calendar = (
        await client.post("/v1/work-calendars", headers=headers, json={"name": "NoShiftCal"})
    ).json()["data"]
    await client.post(
        "/v1/policy-assignments",
        headers=headers,
        json={
            "policy_kind": "WORK_CALENDAR",
            "policy_id": work_calendar["id"],
            "scope_type": "COMPANY",
            "effective_from": "2026-01-01",
        },
    )

    return {"employee": employee, "branch": branch}


async def _calculate(
    client: AsyncClient, headers: dict[str, str], *, employee_id: str, day: str
) -> dict[str, Any]:
    response = await client.post(
        "/v1/attendance/days/calculate",
        headers=headers,
        params={"employee_id": employee_id, "date": day},
    )
    assert response.status_code == 200, response.text
    return dict(response.json()["data"])


async def test_shift_employee_late_night_punch_is_orphaned(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _punch(client, headers, employee_id=employee_id, hour=9, minute=0, direction="IN")
        await _punch(client, headers, employee_id=employee_id, hour=18, minute=0, direction="OUT")
        await _calculate(client, headers, employee_id=employee_id, day="2026-08-10")

        # 09:00-18:00 FIXED shift -> padded load window is 07:00-20:00. 23:45 is well outside it.
        await _punch(
            client,
            headers,
            employee_id=employee_id,
            hour=23,
            minute=45,
            direction="IN",
            reference="late arrival, outside the pad",
        )

        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, str(company_id))
            report = await AttendanceDayService(session).list_orphaned_punches(
                company_id, date_from=date(2026, 8, 10), date_to=date(2026, 8, 10)
            )
        orphaned_hours = {
            datetime.fromisoformat(p.punch_time).hour
            for p in report
            if str(p.employee_id) == employee_id
        }
        assert 23 in orphaned_hours, "a punch outside the ±2h padded window must be reported"
        assert 9 not in orphaned_hours, "the punch that anchored the shift must not be reported"
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_no_shift_employee_late_night_punch_is_not_orphaned(client: AsyncClient) -> None:
    """`SR-14` — the exact same local punch time (23:45) that is orphaned for a shift-bearing
    employee above must NOT be orphaned for a no-shift employee: their window is the full local
    calendar day, not a ±2h pad centered on a shift that doesn't exist."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_employee_no_shift(client, headers)
        employee_id = wired["employee"]["id"]
        await _calculate(client, headers, employee_id=employee_id, day="2026-08-10")

        await _punch(
            client,
            headers,
            employee_id=employee_id,
            hour=23,
            minute=45,
            direction="IN",
            reference="late arrival, no shift resolved",
        )

        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, str(company_id))
            report = await AttendanceDayService(session).list_orphaned_punches(
                company_id, date_from=date(2026, 8, 10), date_to=date(2026, 8, 10)
            )
        orphaned_for_employee = [p for p in report if str(p.employee_id) == employee_id]
        assert orphaned_for_employee == [], (
            "SR-14: a no-shift employee's window is the unpadded local calendar day — this "
            "punch falls inside it and must not be misreported as orphaned"
        )
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_punch_with_no_attendance_day_at_all_is_orphaned(client: AsyncClient) -> None:
    """A date `calculate()` never ran for has no window to cover anything — every punch on it is
    orphaned by definition (the `F-14` gap this report exists to surface, before a row exists).

    Inserted directly via the ORM, bypassing `PunchService` entirely — going through the normal
    on-behalf punch endpoint would trigger Phase 8's own best-effort immediate calculate hook,
    which would create exactly the `AttendanceDay` row this case needs to stay absent."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = UUID(wired["employee"]["id"])

        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, str(company_id))
            session.add(
                Punch(
                    id=uuid4(),
                    company_id=company_id,
                    employee_id=employee_id,
                    punch_time=datetime(2026, 8, 20, 9, 0, tzinfo=UTC),
                    direction="IN",
                    source="ADMIN",
                    reference="never calculated",
                )
            )
            await session.commit()

            report = await AttendanceDayService(session).list_orphaned_punches(
                company_id, date_from=date(2026, 8, 20), date_to=date(2026, 8, 20)
            )
        assert len(report) == 1
        assert report[0].employee_id == employee_id
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
