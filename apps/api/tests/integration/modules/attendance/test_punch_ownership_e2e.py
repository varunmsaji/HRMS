"""Invariant B end to end (SH-01, SH-02, SH-05, SH-09): punches are attributed through the API,
calculation and immediate recalculation by ownership, not by a fixed two-hour window.

`_build_wired_employee` gives a FIXED 09:00-18:00 UTC shift; `_create_night_shift` a 22:00-06:00
UTC one. The attendance policy has the default limits (240 minutes before, 720 after)."""

from typing import Any

import pytest
from httpx import AsyncClient

from .test_attendance_day import (
    _build_wired_employee,
    _cleanup,
    _cleanup_attendance_day,
    _punch,
    _register_tenant,
)
from .test_attendance_edge_cases import _terminate
from .test_resolved_work_schedule import _roster
from .test_shift_roster import _create_night_shift

pytestmark = pytest.mark.asyncio


async def _calc(client: AsyncClient, headers: dict[str, str], eid: str, day: str) -> dict[str, Any]:
    response = await client.post(
        "/v1/attendance/days/calculate", headers=headers, params={"employee_id": eid, "date": day}
    )
    assert response.status_code == 200, response.text
    return dict(response.json()["data"])


async def _stored(
    client: AsyncClient, headers: dict[str, str], eid: str, day: str
) -> dict[str, Any]:
    response = await client.get(
        "/v1/attendance/days",
        headers=headers,
        params={"employee_id": eid, "date_from": day, "date_to": day},
    )
    assert response.status_code == 200, response.text
    rows = response.json()["data"]
    assert len(rows) == 1, rows
    return dict(rows[0])


async def test_checkout_more_than_two_hours_after_shift_end_is_counted(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Regression SH-01: OUT at 20:30 on a 09:00-18:00 shift was never loaded (INCOMPLETE)."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        eid = (await _build_wired_employee(client, headers))["employee"]["id"]
        await _punch(client, headers, employee_id=eid, hour=9, minute=0, direction="IN")
        await _punch(client, headers, employee_id=eid, hour=20, minute=30, direction="OUT")
        day = await _calc(client, headers, eid, "2026-08-10")
        assert day["attendance_status"] == "PRESENT"
        assert day["missing_punch"] is False
        assert day["worked_minutes"] == 690
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_night_then_day_shift_each_day_owns_its_own_punches(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Regression SH-02: night 22:00-07:30 (90 min overtime) then day 07:45-18:00. Before,
    each day loaded the other's punch and both became INCOMPLETE."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        eid = (await _build_wired_employee(client, headers))["employee"]["id"]
        night = await _create_night_shift(client, headers)
        await _roster(client, headers, eid, "2026-08-10", night["id"])
        await _punch(client, headers, employee_id=eid, hour=22, minute=0, direction="IN")
        await _punch(
            client, headers, employee_id=eid, hour=7, minute=30, direction="OUT", day="2026-08-11"
        )
        await _punch(
            client, headers, employee_id=eid, hour=7, minute=45, direction="IN", day="2026-08-11"
        )
        await _punch(
            client, headers, employee_id=eid, hour=18, minute=0, direction="OUT", day="2026-08-11"
        )
        night_day = await _calc(client, headers, eid, "2026-08-10")
        day_day = await _calc(client, headers, eid, "2026-08-11")
        assert night_day["attendance_status"] == "PRESENT"
        assert night_day["worked_minutes"] == 570
        assert day_day["attendance_status"] == "PRESENT"
        assert day_day["missing_punch"] is False
        night_ids = set(night_day["computation_snapshot"]["inputs"]["punch_ids"])
        day_ids = set(day_day["computation_snapshot"]["inputs"]["punch_ids"])
        assert len(night_ids) == 2 and len(day_ids) == 2
        assert not night_ids & day_ids
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_overnight_checkout_recalculates_shift_start_date_immediately(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Regression SH-05: the 06:00 checkout recalculated only its own date, so the shift's day
    stayed 'missing checkout' until the next sweep. No explicit calculate call here."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        eid = (await _build_wired_employee(client, headers))["employee"]["id"]
        night = await _create_night_shift(client, headers)
        await _roster(client, headers, eid, "2026-08-10", night["id"])
        await _punch(client, headers, employee_id=eid, hour=22, minute=0, direction="IN")
        before = await _stored(client, headers, eid, "2026-08-10")
        assert before["missing_punch"] is True
        await _punch(
            client, headers, employee_id=eid, hour=6, minute=0, direction="OUT", day="2026-08-11"
        )
        after = await _stored(client, headers, eid, "2026-08-10")
        assert after["attendance_status"] == "PRESENT"
        assert after["missing_punch"] is False
        assert after["worked_minutes"] == 480
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_last_working_day_night_shift_checkout_is_allowed(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Regression SH-09: last working day the 10th, night shift 22:00-06:00. The 06:00 checkout
    on the 11th belongs to the 10th and is accepted; a check-in on the 11th is still refused."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        eid = (await _build_wired_employee(client, headers))["employee"]["id"]
        night = await _create_night_shift(client, headers)
        await _roster(client, headers, eid, "2026-08-10", night["id"])
        await _terminate(client, headers, eid, "2026-08-10")
        await _punch(client, headers, employee_id=eid, hour=22, minute=0, direction="IN")
        out = await client.post(
            "/v1/attendance/punches",
            headers=headers,
            json={
                "employee_id": eid,
                "punch_time": "2026-08-11T06:00:00Z",
                "direction": "OUT",
                "reference": "night checkout",
            },
        )
        assert out.status_code == 201, out.text
        late_in = await client.post(
            "/v1/attendance/punches",
            headers=headers,
            json={
                "employee_id": eid,
                "punch_time": "2026-08-11T09:00:00Z",
                "direction": "IN",
                "reference": "after leaving",
            },
        )
        assert late_in.status_code == 422, late_in.text
        assert late_in.json()["error"]["code"] == "EMPLOYEE_TERMINATED"
        day = await _calc(client, headers, eid, "2026-08-10")
        assert day["attendance_status"] == "PRESENT"
        assert day["worked_minutes"] == 480
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_overnight_shift_on_the_last_day_of_a_month_owns_its_checkout(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Month boundary: 31 Aug night shift, checkout 1 Sep 09:00 (3h overtime) — all on 31 Aug."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        eid = (await _build_wired_employee(client, headers))["employee"]["id"]
        night = await _create_night_shift(client, headers)
        await _roster(client, headers, eid, "2026-08-31", night["id"])
        await _punch(
            client, headers, employee_id=eid, hour=22, minute=0, direction="IN", day="2026-08-31"
        )
        await _punch(
            client, headers, employee_id=eid, hour=9, minute=0, direction="OUT", day="2026-09-01"
        )
        aug = await _calc(client, headers, eid, "2026-08-31")
        sep = await _calc(client, headers, eid, "2026-09-01")
        assert aug["worked_minutes"] == 660
        assert aug["missing_punch"] is False
        assert sep["computation_snapshot"]["inputs"]["punch_ids"] == []
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
