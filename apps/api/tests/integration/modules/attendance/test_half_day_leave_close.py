"""Period close resolves only the worked half of an INCOMPLETE half-day leave day (D-2)."""

import pytest
from httpx import AsyncClient
from sqlalchemy import text
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
from tests.integration.modules.attendance.test_leave_projection import (
    _cleanup_leave_projection,
    _get_day,
    _sync,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.core.db.session import get_session_factory, set_rls_company_id

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize(
    ("behaviour", "paid", "lop", "bucket"),
    [
        ("TREAT_ABSENT", "0.50", "0.50", "absent_days"),
        ("TREAT_PRESENT", "1.00", "0.00", "present_days"),
    ],
)
async def test_missing_out_around_half_day_leave_is_resolved_at_the_lock(
    client: AsyncClient,
    seeded_plan_catalogue: None,
    behaviour: str,
    paid: str,
    lop: str,
    bucket: str,
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, str(company_id))
            await session.execute(
                text(
                    "UPDATE attendance_policy_version SET incomplete_at_lock_behaviour = :b "
                    "WHERE company_id = :cid"
                ),
                {"b": behaviour, "cid": str(company_id)},
            )
            await session.commit()
        await _punch(client, headers, employee_id=employee_id, hour=14, minute=0, direction="IN")
        synced = await _sync(
            client, headers, employee_id=employee_id, fraction="0.50", half="FIRST"
        )
        assert synced.status_code == 201, synced.text

        before = await _get_day(client, headers, employee_id=employee_id)
        assert before["attendance_status"] == "INCOMPLETE"
        assert before["paid_day_fraction"] == "0.50"
        assert before["lop_fraction"] == "0.00"

        period = await _create_period(client, headers)
        finalized = await client.post(
            f"/v1/attendance-periods/{period['id']}/finalize",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert finalized.status_code == 200, finalized.text

        locked = await _get_day(client, headers, employee_id=employee_id)
        assert locked["is_locked"] is True
        assert locked["paid_day_fraction"] == paid
        assert locked["lop_fraction"] == lop

        summary = await client.get(
            f"/v1/attendance-periods/{period['id']}/summary", headers=headers
        )
        row = next(r for r in summary.json()["data"] if r["employee_id"] == employee_id)
        assert row["payable_days"] == "1.00"
        assert row["paid_days"] == paid
        assert row["lop_days"] == lop
        assert row["leave_days"] == "0.50"
        assert row[bucket] == "0.50"
        assert row["incomplete_days"] == "0.00"
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_leave_projection(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_first_half_leave_arrival_at_the_midpoint_does_not_count_as_late(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The stored flag feeds `lates_to_half_day_count`, so a false late would hurt later days."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _punch(client, headers, employee_id=employee_id, hour=13, minute=30, direction="IN")
        await _punch(client, headers, employee_id=employee_id, hour=18, minute=0, direction="OUT")
        synced = await _sync(
            client, headers, employee_id=employee_id, fraction="0.50", half="FIRST"
        )
        assert synced.status_code == 201, synced.text

        day = await _get_day(client, headers, employee_id=employee_id)
        assert day["attendance_status"] == "HALF_DAY"
        assert day["late_minutes"] == 0
        assert day["is_late"] is False
        assert day["paid_day_fraction"] == "1.00"
    finally:
        await _cleanup_leave_projection(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
