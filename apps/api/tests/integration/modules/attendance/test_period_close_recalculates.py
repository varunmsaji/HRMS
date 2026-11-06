"""R-09: finalizing a period recalculates its unlocked days first, so a holiday added for a day
that was already calculated is not locked into payroll as an absence."""

from typing import Any

import pytest
from httpx import AsyncClient
from tests.integration.modules.attendance.test_attendance_day import (
    _build_wired_employee,
    _cleanup_attendance_day,
    _punch,
    _register_tenant,
)
from tests.integration.modules.attendance.test_attendance_period import (
    _cleanup_attendance_period,
    _create_period,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup
from tests.integration.modules.organisation.test_workforce_calendar import (
    _cleanup_workforce_calendar,
)

pytestmark = pytest.mark.asyncio

_DAY = "2026-08-10"


async def _calculate(client: AsyncClient, headers: dict[str, str], employee_id: str) -> Any:
    response = await client.post(
        "/v1/attendance/days/calculate",
        headers=headers,
        params={"employee_id": employee_id, "date": _DAY},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def _get_day(client: AsyncClient, headers: dict[str, str], employee_id: str) -> Any:
    response = await client.get(
        "/v1/attendance/days",
        headers=headers,
        params={"employee_id": employee_id, "date_from": _DAY, "date_to": _DAY},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"][0]


async def _add_holiday(client: AsyncClient, headers: dict[str, str]) -> None:
    calendar = await client.post("/v1/holiday-calendars", headers=headers, json={"name": "Closed"})
    assert calendar.status_code == 201, calendar.text
    calendar_id = calendar.json()["data"]["id"]
    holiday = await client.post(
        f"/v1/holiday-calendars/{calendar_id}/holidays",
        headers=headers,
        json={"date": _DAY, "name": "Closed"},
    )
    assert holiday.status_code == 201, holiday.text
    work_calendar = (await client.get("/v1/work-calendars", headers=headers)).json()["data"][0]
    linked = await client.patch(
        f"/v1/work-calendars/{work_calendar['id']}",
        headers={**headers, "If-Match": str(work_calendar["version"])},
        json={"holiday_calendar_ids": [calendar_id]},
    )
    assert linked.status_code == 200, linked.text


async def _finalize(client: AsyncClient, headers: dict[str, str]) -> Any:
    period = await _create_period(client, headers)
    finalized = await client.post(
        f"/v1/attendance-periods/{period['id']}/finalize",
        headers={**headers, "If-Match": "1"},
        json={},
    )
    assert finalized.status_code == 200, finalized.text
    summary = await client.get(f"/v1/attendance-periods/{period['id']}/summary", headers=headers)
    assert summary.status_code == 200, summary.text
    return summary.json()["data"]


async def test_a_holiday_added_after_calculation_is_not_locked_as_an_absence(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        # No punches on a working day: INCOMPLETE, which the default policy locks as a full day
        # of loss of pay (TREAT_ABSENT).
        missed = await _calculate(client, headers, employee_id)
        assert missed["attendance_status"] == "INCOMPLETE"

        await _add_holiday(client, headers)
        # Nothing recalculates the day by itself: it is still stale before finalize.
        assert (await _get_day(client, headers, employee_id))["attendance_status"] == "INCOMPLETE"

        summary = await _finalize(client, headers)

        day = await _get_day(client, headers, employee_id)
        assert day["is_locked"] is True
        # An unworked holiday: not expected at work, and paid.
        assert day["attendance_status"] == "NOT_EXPECTED"
        assert day["lop_fraction"] == "0.00"
        row = next(r for r in summary if r["employee_id"] == employee_id)
        assert row["lop_days"] == "0.00"
        assert row["absent_days"] == "0.00"
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_workforce_calendar(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_an_up_to_date_day_locks_with_the_same_figures(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _punch(client, headers, employee_id=employee_id, hour=9, minute=0, direction="IN")
        await _punch(client, headers, employee_id=employee_id, hour=18, minute=0, direction="OUT")
        before = await _calculate(client, headers, employee_id)
        assert before["attendance_status"] == "PRESENT"

        summary = await _finalize(client, headers)

        day = await _get_day(client, headers, employee_id)
        assert day["is_locked"] is True
        for field in (
            "attendance_status",
            "worked_minutes",
            "paid_day_fraction",
            "lop_fraction",
            "is_late",
        ):
            assert day[field] == before[field], field
        row = next(r for r in summary if r["employee_id"] == employee_id)
        assert row["present_days"] == "1.00"
        assert row["lop_days"] == "0.00"
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
