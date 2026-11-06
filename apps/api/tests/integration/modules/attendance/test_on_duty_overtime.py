"""F11 (D-5): an ON_DUTY day that does not require punches pays no overtime, even when the
overtime was approved before the on-duty request was. The overtime decision itself stands, as
with full-day leave (BUS-011)."""

import pytest
from httpx import AsyncClient
from tests.integration.modules.attendance.test_attendance_day import (
    _build_wired_employee,
    _cleanup_attendance_day,
    _register_tenant,
)
from tests.integration.modules.attendance.test_attendance_security import (
    _cleanup_scoped_users,
    _create_permission_scoped_user,
)
from tests.integration.modules.attendance.test_overtime_record import (
    _cleanup_overtime,
    _create_overtime_policy,
    _get_overtime_record_for_day,
    _ot_calculate_day,
)
from tests.integration.modules.attendance.test_regularization import (
    _cleanup_regularization,
    _create_regularization_policy,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

pytestmark = pytest.mark.asyncio

_DAY = "2026-08-10"


async def test_on_duty_after_approved_overtime_leaves_no_overtime_payable(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _create_overtime_policy(client, headers, approval_chain="AUTO")
        day = await _ot_calculate_day(client, headers, employee_id=employee_id)
        assert day["ot_minutes_approved"] == 60

        await _create_regularization_policy(
            client, headers, allowed_types=["ON_DUTY"], approval_chain="HR"
        )
        created = await client.post(
            "/v1/regularizations",
            headers=headers,
            json={
                "employee_id": employee_id,
                "attendance_date": _DAY,
                "request_type": "ON_DUTY",
                "reason": "Client site visit",
                "requested_punches": [
                    {"direction": "IN", "requested_time": f"{_DAY}T09:00:00Z"},
                    {"direction": "OUT", "requested_time": f"{_DAY}T19:00:00Z"},
                ],
            },
        )
        assert created.status_code == 201, created.text
        request = created.json()["data"]

        from hrms.modules.attendance.permissions import ATTENDANCE_REGULARIZATION_APPROVE

        hr_headers, _ = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=[ATTENDANCE_REGULARIZATION_APPROVE]
        )
        approved = await client.post(
            f"/v1/regularizations/{request['id']}/approve",
            headers={**hr_headers, "If-Match": str(request["version"])},
            json={},
        )
        assert approved.status_code == 200, approved.text

        on_duty = (await client.get(f"/v1/attendance/days/{day['id']}", headers=headers)).json()[
            "data"
        ]
        assert on_duty["attendance_status"] == "ON_DUTY"
        assert on_duty["paid_day_fraction"] == "1.00"
        assert on_duty["ot_minutes_approved"] == 0
        assert on_duty["ot_pending"] is False
        assert on_duty["comp_off_minutes_earned"] == 0
        record = await _get_overtime_record_for_day(
            client, headers, employee_id=employee_id, day=_DAY
        )
        assert record["status"] == "AUTO_APPROVED"
    finally:
        await _cleanup_regularization(company_id=company_id)
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()
