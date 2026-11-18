"""The orphan-punch report (`TZ-08`/`DEC-TZ-16`) on top of punch ownership (Invariant B,
`ownership_service.py`, engine 13).

1. A checkout long after the shift (SH-01) is owned by the shift, not reported; a lone check-in
   that no shift can take (outside every window) is reported.
2. `SR-14` — a no-shift employee's late-night punch belongs to their calendar day.
3. Ownership does not depend on whether the day was calculated: a punch on a never-calculated
   date that a shift owns is not reported (the missing calculation is
   `EMPLOYEES_WITHOUT_ATTENDANCE`'s job at period close).
4. Dismissal: only an orphan can be dismissed, with a reason; it then leaves the report.
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


async def _report(company_id: UUID, day: date) -> list[Any]:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        return await AttendanceDayService(session).list_orphaned_punches(
            company_id, date_from=day, date_to=day
        )


async def test_long_overtime_checkout_is_owned_and_stray_check_in_is_orphaned(
    client: AsyncClient,
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        # 09:00-18:00 UTC shift. 23:45 is 5h45 after the end: owned (12h limit), not orphaned.
        await _punch(client, headers, employee_id=employee_id, hour=9, minute=0, direction="IN")
        await _punch(client, headers, employee_id=employee_id, hour=23, minute=45, direction="OUT")
        # A lone check-in at 02:00 on the 12th: more than 4h before the 12th's shift, and after
        # the 11th's shift ended, so no day can take it.
        await _punch(
            client,
            headers,
            employee_id=employee_id,
            hour=2,
            minute=0,
            direction="IN",
            day="2026-08-12",
        )
        day = await _calculate(client, headers, employee_id=employee_id, day="2026-08-10")
        assert day["attendance_status"] == "PRESENT"
        assert day["worked_minutes"] == 885

        report = await _report(company_id, date(2026, 8, 10))
        assert [p for p in report if str(p.employee_id) == employee_id] == []
        report = await _report(company_id, date(2026, 8, 12))
        hours = {datetime.fromisoformat(p.punch_time).hour for p in report}
        assert hours == {2}
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_no_shift_employee_late_night_punch_is_not_orphaned(client: AsyncClient) -> None:
    """`SR-14` — a no-shift employee's punch belongs to their local calendar day."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_employee_no_shift(client, headers)
        employee_id = wired["employee"]["id"]
        await _punch(
            client,
            headers,
            employee_id=employee_id,
            hour=23,
            minute=45,
            direction="IN",
            reference="late arrival, no shift resolved",
        )
        report = await _report(company_id, date(2026, 8, 10))
        assert [p for p in report if str(p.employee_id) == employee_id] == []
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_owned_punch_on_a_never_calculated_date_is_not_orphaned(client: AsyncClient) -> None:
    """Inserted directly so no calculation runs: ownership alone decides the report."""
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
        assert await _report(company_id, date(2026, 8, 20)) == []
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_only_an_orphan_can_be_dismissed_and_then_leaves_the_report(
    client: AsyncClient,
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        owned = await _punch(
            client, headers, employee_id=employee_id, hour=9, minute=0, direction="IN"
        )
        stray = await _punch(
            client,
            headers,
            employee_id=employee_id,
            hour=2,
            minute=0,
            direction="IN",
            day="2026-08-12",
        )
        listed = await client.get(
            "/v1/attendance/orphaned-punches",
            headers=headers,
            params={"date_from": "2026-08-10", "date_to": "2026-08-12"},
        )
        assert listed.status_code == 200, listed.text
        assert [p["id"] for p in listed.json()["data"]] == [stray["id"]]

        refused = await client.post(
            f"/v1/attendance/orphaned-punches/{owned['id']}/dismiss",
            headers=headers,
            json={"reason": "not needed"},
        )
        assert refused.status_code == 409, refused.text
        assert refused.json()["error"]["code"] == "PUNCH_NOT_ORPHANED"

        dismissed = await client.post(
            f"/v1/attendance/orphaned-punches/{stray['id']}/dismiss",
            headers=headers,
            json={"reason": "tapped by mistake on the way home"},
        )
        assert dismissed.status_code == 200, dismissed.text
        after = await client.get(
            "/v1/attendance/orphaned-punches",
            headers=headers,
            params={"date_from": "2026-08-10", "date_to": "2026-08-12"},
        )
        assert after.json()["data"] == []
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
