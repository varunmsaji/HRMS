"""H-08 through the real API: a half-day leave projection on a day off creates no loss of pay.

The employee is rostered off on 2026-08-10 (a published roster week-off). The leave module keeps the
projection (and the balance, and the reconciliation blocker); attendance keeps the day's normal
day-off pay.
"""

import pytest
from httpx import AsyncClient
from tests.integration.modules.attendance.test_attendance_day import (
    _build_wired_employee,
    _cleanup_attendance_day,
    _register_tenant,
)
from tests.integration.modules.attendance.test_attendance_period import (
    _cleanup_attendance_period,
    _create_period,
)
from tests.integration.modules.attendance.test_leave_projection import (
    _cleanup_leave_projection,
    _sync,
)
from tests.integration.modules.attendance.test_shift_roster import _publish_roster
from tests.integration.modules.attendance.test_shift_window import _sql
from tests.integration.modules.organisation.test_registration_flow import _cleanup

pytestmark = pytest.mark.asyncio

OFF_DAY = "2026-08-10"


@pytest.mark.parametrize("is_paid", [True, False])
async def test_a_half_day_leave_projection_on_a_rostered_day_off_costs_nothing(
    client: AsyncClient, seeded_plan_catalogue: None, is_paid: bool
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = str(wired["employee"]["id"])
        await _publish_roster(
            client,
            headers,
            {"employee_id": employee_id, "roster_date": OFF_DAY, "is_week_off_override": True},
        )
        synced = await _sync(
            client,
            headers,
            employee_id=employee_id,
            fraction="0.50",
            half="FIRST",
            is_paid=is_paid,
            day=OFF_DAY,
        )
        assert synced.status_code == 201, synced.text

        listed = await client.get(
            "/v1/attendance/days",
            headers=headers,
            params={"employee_id": employee_id, "date_from": OFF_DAY, "date_to": OFF_DAY},
        )
        day = listed.json()["data"][0]
        assert day["attendance_status"] == "NOT_EXPECTED"
        assert (day["paid_day_fraction"], day["lop_fraction"]) == ("1.00", "0.00")

        # the leave projection is preserved - nothing is refunded or erased by attendance ...
        projections = await _sql(
            company_id,
            "SELECT status FROM leave_day_projection WHERE company_id = :cid "
            f"AND attendance_date = '{OFF_DAY}'",
        )
        assert [r[0] for r in projections] == ["APPROVED"]
        # ... and the reconciliation blocker still stops the close until HR reconciles
        period = await _create_period(client, headers, period_start=OFF_DAY, period_end=OFF_DAY)
        blocked = await client.post(
            f"/v1/attendance-periods/{period['id']}/finalize",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert blocked.status_code == 409, blocked.text
        reasons = blocked.json()["error"]["details"][0]["context"]["reasons"]
        assert any(r["code"] == "LEAVE_CALENDAR_MISMATCH" for r in reasons)
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_leave_projection(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
