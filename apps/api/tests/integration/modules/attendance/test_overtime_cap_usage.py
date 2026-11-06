"""N-5: the weekly and monthly overtime caps count what will be paid. Approved days count their
approved minutes, days still waiting count their detected minutes as a reserve, and days that pay
no overtime (full-day leave, rejected) count nothing.

Each day below works 09:00-19:00 against a 09:00-18:00 shift: 60 minutes detected. The weekly
cap is 90 minutes, and Monday 10 and Tuesday 11 August 2026 fall in the same week."""

from uuid import UUID

import pytest
from httpx import AsyncClient
from tests.integration.modules.attendance.test_attendance_day import (
    _build_wired_employee,
    _cleanup_attendance_day,
    _register_tenant,
)
from tests.integration.modules.attendance.test_attendance_security import (
    _add_reportee_employee,
    _cleanup_scoped_users,
    _create_permission_scoped_user,
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

_MONDAY = "2026-08-10"
_TUESDAY = "2026-08-11"


@pytest.mark.parametrize(
    ("decision", "tuesday_detected"),
    [
        ("partial", 60),  # Monday approved for 20: 70 of the 90 left, so Tuesday is not clamped
        ("rejected", 60),  # Monday rejected: counts nothing
        ("waiting", 30),  # Monday still waiting: its 60 stay reserved (must not change)
    ],
)
async def test_the_weekly_cap_counts_what_monday_will_pay(
    client: AsyncClient,
    seeded_plan_catalogue: None,
    decision: str,
    tuesday_detected: int,
) -> None:
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
        employee_id = reportee["id"]
        await _create_overtime_policy(
            client, headers, approval_chain="MANAGER", weekly_cap_minutes=90
        )
        monday = await _ot_calculate_day(client, headers, employee_id=employee_id, day=_MONDAY)
        assert monday["ot_minutes_detected"] == 60

        if decision != "waiting":
            from hrms.modules.attendance.permissions import ATTENDANCE_OVERTIME_APPROVE

            manager_headers, _ = await _create_permission_scoped_user(
                company_id=company_id,
                permission_codes=[ATTENDANCE_OVERTIME_APPROVE],
                data_scope="REPORTEES",
                caller_employee_id=UUID(manager_id),
            )
            record = await _get_overtime_record_for_day(
                client, headers, employee_id=employee_id, day=_MONDAY
            )
            action, body = (
                ("approve", {"minutes_approved": 20, "reviewer_comment": "Only 20 minutes agreed"})
                if decision == "partial"
                else ("reject", {"reviewer_comment": "Not pre-agreed"})
            )
            decided = await client.post(
                f"/v1/overtime/{record['id']}/{action}",
                headers={**manager_headers, "If-Match": str(record["version"])},
                json=body,
            )
            assert decided.status_code == 200, decided.text

        tuesday = await _ot_calculate_day(client, headers, employee_id=employee_id, day=_TUESDAY)
        assert tuesday["ot_minutes_detected"] == tuesday_detected
    finally:
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_approved_overtime_on_a_full_day_leave_does_not_use_the_cap(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Monday's overtime was approved, then Monday became a full day of leave: it pays nothing
    (BUS-011), so it no longer uses any of the week's cap."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _create_overtime_policy(client, headers, approval_chain="AUTO", weekly_cap_minutes=90)
        monday = await _ot_calculate_day(client, headers, employee_id=employee_id, day=_MONDAY)
        assert monday["ot_minutes_approved"] == 60
        synced = await _sync(client, headers, employee_id=employee_id, fraction="1.00", day=_MONDAY)
        assert synced.status_code == 201, synced.text

        tuesday = await _ot_calculate_day(client, headers, employee_id=employee_id, day=_TUESDAY)
        assert tuesday["ot_minutes_detected"] == 60
    finally:
        await _cleanup_leave_projection(company_id=company_id)
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
