"""SH-17: dates that mean "a day" use the company's timezone (Asia/Kolkata), not UTC or the
server's clock."""

from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from tests.integration.modules.attendance.test_attendance_day import (
    _build_wired_employee,
    _cleanup_attendance_day,
    _punch,
    _register_tenant,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

pytestmark = pytest.mark.asyncio


async def test_punch_list_dates_are_company_days(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """20:00 UTC on 10 Aug is 01:30 IST on 11 Aug. Before, the list filtered on UTC days and
    showed this punch under the 10th."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _punch(client, headers, employee_id=employee_id, hour=20, minute=0, direction="IN")

        async def listed(day: str) -> int:
            response = await client.get(
                "/v1/attendance/punches",
                headers=headers,
                params={"employee_id": employee_id, "date_from": day, "date_to": day},
            )
            assert response.status_code == 200, response.text
            return len(response.json()["data"])

        assert await listed("2026-08-11") == 1
        assert await listed("2026-08-10") == 0
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_weekly_schedule_defaults_to_the_company_week(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.get("/v1/rosters/weekly-schedule", headers=headers)
        assert response.status_code == 200, response.text
        week_start = date.fromisoformat(response.json()["data"]["week_start"])
        assert week_start.weekday() == 0
        from hrms.shared.business_time import business_today

        today = business_today("Asia/Kolkata")
        assert week_start == today - timedelta(days=today.weekday())
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)
