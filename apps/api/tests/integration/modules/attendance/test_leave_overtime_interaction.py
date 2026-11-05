"""How overtime decisions behave when leave lands on the same date afterwards (BUS-011)."""

from typing import Any

import pytest
from httpx import AsyncClient
from tests.integration.modules.attendance.test_attendance_day import (
    _build_wired_employee,
    _cleanup_attendance_day,
    _register_tenant,
)
from tests.integration.modules.attendance.test_leave_projection import (
    _cleanup_leave_projection,
    _sync,
)
from tests.integration.modules.attendance.test_overtime_record import (
    _cleanup_overtime,
    _create_overtime_policy,
    _get_overtime_record_for_day,
    _ot_calculate_day,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

pytestmark = pytest.mark.asyncio

_DAY = "2026-08-10"


async def _read_day(client: AsyncClient, headers: dict[str, str], day_id: str) -> dict[str, Any]:
    response = await client.get(f"/v1/attendance/days/{day_id}", headers=headers)
    assert response.status_code == 200, response.text
    return dict(response.json()["data"])


async def test_full_day_leave_after_approved_overtime_leaves_nothing_payable(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _create_overtime_policy(client, headers, approval_chain="AUTO")
        day = await _ot_calculate_day(client, headers, employee_id=employee_id)
        assert day["ot_minutes_approved"] == 60

        synced = await _sync(client, headers, employee_id=employee_id, fraction="1.00")
        assert synced.status_code == 201, synced.text

        on_leave = await _read_day(client, headers, day["id"])
        assert on_leave["attendance_status"] == "LEAVE"
        assert on_leave["work_on_leave_flagged"] is True
        assert on_leave["ot_minutes_approved"] == 0
        assert on_leave["comp_off_minutes_earned"] == 0
        assert on_leave["ot_pending"] is False
        # The decision itself stands, so that cancelling the leave can restore it.
        record = await _get_overtime_record_for_day(
            client, headers, employee_id=employee_id, day=_DAY
        )
        assert record["status"] == "AUTO_APPROVED"
        assert record["minutes_approved"] == 60

        cancelled = await client.post(
            f"/v1/leave-projections/{synced.json()['data']['id']}/cancel",
            headers={**headers, "If-Match": str(synced.json()["data"]["version"])},
            json={"reason": "Worked the day after all"},
        )
        assert cancelled.status_code == 200, cancelled.text
        restored = await _read_day(client, headers, day["id"])
        assert restored["attendance_status"] != "LEAVE"
        assert restored["ot_minutes_approved"] == 60
    finally:
        await _cleanup_leave_projection(company_id=company_id)
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_half_day_leave_keeps_approved_overtime(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _create_overtime_policy(client, headers, approval_chain="AUTO")
        day = await _ot_calculate_day(client, headers, employee_id=employee_id)

        synced = await _sync(
            client, headers, employee_id=employee_id, fraction="0.50", half="FIRST"
        )
        assert synced.status_code == 201, synced.text

        assert (await _read_day(client, headers, day["id"]))["ot_minutes_approved"] == 60
    finally:
        await _cleanup_leave_projection(company_id=company_id)
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_full_day_leave_removes_pending_overtime(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _create_overtime_policy(client, headers, approval_chain="HR")
        day = await _ot_calculate_day(client, headers, employee_id=employee_id)
        assert day["ot_pending"] is True

        synced = await _sync(client, headers, employee_id=employee_id, fraction="1.00")
        assert synced.status_code == 201, synced.text

        on_leave = await _read_day(client, headers, day["id"])
        assert on_leave["ot_minutes_approved"] == 0
        assert on_leave["ot_pending"] is False
        listed = await client.get(
            "/v1/overtime",
            headers=headers,
            params={"employee_id": employee_id, "date_from": _DAY, "date_to": _DAY},
        )
        assert listed.json()["data"] == []
    finally:
        await _cleanup_leave_projection(company_id=company_id)
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
