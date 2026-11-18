"""P-04 and F2 through the real API: punches in, stored day out.

The wired employee works a FIXED 09:00-18:00 shift (no break: net 540) under a policy with ABSENT
below 240 minutes and PRESENT from 240, grace 0. The default ownership window lets a punch belong
to the day from 05:00 (`max_early_punch_minutes` 240), so 05:00-09:00 is the longest pre-start
session a day can hold.
"""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from tests.integration.modules.attendance.test_attendance_day import (
    _build_wired_employee,
    _punch,
    _register_tenant,
)
from tests.integration.modules.attendance.test_attendance_rules_remediation import (
    MON,
    _calc,
    _cleanup_all,
    _stored,
)

pytestmark = pytest.mark.asyncio


async def _wire(client: AsyncClient) -> tuple[dict[str, str], object, object, str]:
    headers, company_id, user_id = await _register_tenant(client)
    wired = await _build_wired_employee(client, headers)
    return headers, company_id, user_id, str(wired["employee"]["id"])


async def test_work_wholly_before_the_shift_is_classified_flagged_and_not_overtime(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id, employee_id = await _wire(client)
    try:
        await _punch(client, headers, employee_id=employee_id, hour=5, minute=0, direction="IN")
        await _punch(client, headers, employee_id=employee_id, hour=9, minute=0, direction="OUT")
        await _calc(client, headers, employee_id, MON)
        day = await _stored(client, headers, employee_id, MON)

        # P-04: 240 minutes before the start classify the day; it was ABSENT with a full day of LOP
        assert day["attendance_status"] == "PRESENT"
        assert day["paid_day_fraction"] == "1.00"
        # classification only: not worked time, never overtime, the real punches kept
        assert day["worked_minutes"] == 0
        assert day["ot_minutes_detected"] == 0
        assert datetime.fromisoformat(day["actual_first_in"]) == datetime(
            2026, 8, 10, 5, tzinfo=UTC
        )
        flag = day["computation_snapshot"]["worked_outside_shift"]
        assert flag["flag"] == "WORKED_OUTSIDE_SHIFT"
        assert (flag["sessions"], flag["minutes"], flag["credited_for_classification"]) == (
            1,
            240,
            240,
        )
        assert day["late_minutes"] == 0 and day["is_late"] is False  # no automatic late mark
    finally:
        await _cleanup_all(company_id, user_id)


async def test_a_session_shorter_than_the_half_day_threshold_stays_absent_but_is_flagged(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id, employee_id = await _wire(client)
    try:
        await _punch(client, headers, employee_id=employee_id, hour=6, minute=0, direction="IN")
        await _punch(client, headers, employee_id=employee_id, hour=9, minute=0, direction="OUT")
        await _calc(client, headers, employee_id, MON)
        day = await _stored(client, headers, employee_id, MON)
        assert day["attendance_status"] == "ABSENT"  # 180 < 240
        assert day["computation_snapshot"]["worked_outside_shift"]["minutes"] == 180
    finally:
        await _cleanup_all(company_id, user_id)


async def test_an_early_session_cannot_erase_lateness(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """F2: 08:30-08:50 then 11:00-18:00. Arrival is 11:00, two hours late (grace 0); the real first
    punch stays 08:30 for reporting."""
    headers, company_id, user_id, employee_id = await _wire(client)
    try:
        for hour, minute, direction in (
            (8, 30, "IN"),
            (8, 50, "OUT"),
            (11, 0, "IN"),
            (18, 0, "OUT"),
        ):
            await _punch(
                client,
                headers,
                employee_id=employee_id,
                hour=hour,
                minute=minute,
                direction=direction,
            )
        await _calc(client, headers, employee_id, MON)
        day = await _stored(client, headers, employee_id, MON)
        assert day["late_minutes"] == 120 and day["is_late"] is True
        assert datetime.fromisoformat(day["actual_first_in"]) == datetime(
            2026, 8, 10, 8, 30, tzinfo=UTC
        )
        assert "worked_outside_shift" not in day["computation_snapshot"]  # credited work exists
    finally:
        await _cleanup_all(company_id, user_id)


async def test_a_normal_day_is_unchanged(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id, employee_id = await _wire(client)
    try:
        await _punch(client, headers, employee_id=employee_id, hour=9, minute=0, direction="IN")
        await _punch(client, headers, employee_id=employee_id, hour=18, minute=0, direction="OUT")
        await _calc(client, headers, employee_id, MON)
        day = await _stored(client, headers, employee_id, MON)
        assert day["attendance_status"] == "PRESENT" and day["worked_minutes"] == 540
        assert day["late_minutes"] == 0
        assert "worked_outside_shift" not in day["computation_snapshot"]
    finally:
        await _cleanup_all(company_id, user_id)
