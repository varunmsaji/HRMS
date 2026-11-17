"""AC-01 / AC-04 at period close: overtime that disagrees with its day blocks the close, and an
INCOMPLETE day resolved as absent at lock pays no overtime."""

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
from tests.integration.modules.attendance.test_overtime_record import (
    _cleanup_overtime,
    _create_overtime_policy,
    _ot_calculate_day,
)
from tests.integration.modules.attendance.test_shift_window import _sql
from tests.integration.modules.organisation.test_registration_flow import _cleanup

pytestmark = pytest.mark.asyncio

DAY = "2026-08-10"


async def _cleanup_all(company_id: Any, user_id: Any) -> None:
    await _cleanup_attendance_period(company_id=company_id)
    await _cleanup_overtime(company_id=company_id)
    await _cleanup_attendance_day(company_id=company_id)
    await _cleanup(company_id=company_id, user_id=user_id)


async def test_approved_overtime_above_detected_blocks_the_close(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = (await _build_wired_employee(client, headers))["employee"]["id"]
        await _create_overtime_policy(client, headers, approval_chain="AUTO")
        day = await _ot_calculate_day(client, headers, employee_id=employee_id)
        assert day["ot_minutes_approved"] == 60
        period = await _create_period(client, headers)

        clean = await client.post(
            f"/v1/attendance-periods/{period['id']}/validate", headers=headers
        )
        assert "OVERTIME_INTEGRITY" not in [r["code"] for r in clean.json()["data"]["reasons"]]

        # What the audit found in the field: payroll's day row says more than the punches support.
        await _sql(
            company_id,
            "UPDATE attendance_day SET ot_minutes_approved = 600 "
            "WHERE company_id = :cid AND attendance_date = '2026-08-10'",
        )
        blocked = await client.post(
            f"/v1/attendance-periods/{period['id']}/validate", headers=headers
        )
        reasons = {r["code"]: r for r in blocked.json()["data"]["reasons"]}
        assert "OVERTIME_INTEGRITY" in reasons
        assert "approved>detected(600>60)" in " ".join(reasons["OVERTIME_INTEGRITY"]["sample"])

        # Finalize recalculates every open day first, which repairs the figure, so it closes.
        finalized = await client.post(
            f"/v1/attendance-periods/{period['id']}/finalize",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert finalized.status_code == 200, finalized.text
        rows = await _sql(
            company_id,
            "SELECT ot_minutes_approved FROM attendance_day "
            "WHERE company_id = :cid AND attendance_date = '2026-08-10'",
        )
        assert [r[0] for r in rows] == [60]
    finally:
        await _cleanup_all(company_id, user_id)


async def test_an_incomplete_day_resolved_as_absent_pays_no_overtime(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """AC-04 - the employee loses the day (TREAT_ABSENT, the default) and gets no overtime for
    it. The held overtime is not a close blocker under that policy: lock rejects it."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = (await _build_wired_employee(client, headers))["employee"]["id"]
        await _create_overtime_policy(client, headers, approval_chain="AUTO")
        for hour, minute, direction in ((7, 30, "IN"), (9, 0, "IN"), (19, 0, "OUT")):
            await _punch(
                client,
                headers,
                employee_id=employee_id,
                hour=hour,
                minute=minute,
                direction=direction,
                day=DAY,
            )
        calculated = await client.post(
            "/v1/attendance/days/calculate",
            headers=headers,
            params={"employee_id": employee_id, "date": DAY},
        )
        assert calculated.json()["data"]["attendance_status"] == "INCOMPLETE"
        period = await _create_period(client, headers)

        finalized = await client.post(
            f"/v1/attendance-periods/{period['id']}/finalize",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert finalized.status_code == 200, finalized.text

        day = (
            await client.get(
                "/v1/attendance/days",
                headers=headers,
                params={"employee_id": employee_id, "date_from": DAY, "date_to": DAY},
            )
        ).json()["data"][0]
        assert day["is_locked"] is True
        assert day["paid_day_fraction"] == "0.00" and day["lop_fraction"] == "1.00"
        assert day["ot_minutes_approved"] == 0 and day["ot_pending"] is False
        record = (
            await client.get(
                "/v1/overtime",
                headers=headers,
                params={"employee_id": employee_id, "date_from": DAY, "date_to": DAY},
            )
        ).json()["data"][0]
        assert record["status"] == "REJECTED" and record["minutes_approved"] == 0
        assert "SUPERSEDED" not in [a["action"] for a in record["actions"]]
        assert record["actions"][-1]["action"] == "REJECTED"
    finally:
        await _cleanup_all(company_id, user_id)
