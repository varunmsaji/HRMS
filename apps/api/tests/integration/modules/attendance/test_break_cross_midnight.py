"""End-to-end integration coverage for `SR-01`/`F-05` (execution gate §1, §22 "End-to-end /
regression"): a night-shift break spanning midnight, and a break starting after midnight on the
same shift, both matched correctly through the REAL `calculate()` pipeline — not only through
the pure `match_breaks` unit tests in `tests/unit/modules/attendance/test_calculation.py`.

Reuses `_build_wired_employee`/`_punch`/`_register_tenant`/`_cleanup_attendance_day` from
`test_attendance_day.py` and `_create_night_shift` from `test_shift_roster.py` — the same
cross-file reuse pattern every W4/W5 test file already established.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from tests.integration.modules.attendance.test_attendance_day import (
    _build_wired_employee,
    _cleanup_attendance_day,
    _register_tenant,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

pytestmark = pytest.mark.asyncio


async def _create_night_shift_with_breaks(
    client: AsyncClient, headers: dict[str, str], *, breaks: list[dict[str, Any]]
) -> dict[str, Any]:
    """A published `22:00->06:00` `FIXED` shift carrying the given breaks — mirrors
    `test_shift_roster.py::_create_night_shift`, with breaks added in the same PATCH rather
    than a second call, since `ShiftVersionUpdate.breaks` is full-replace-on-write."""
    shift = (
        await client.post("/v1/shifts", headers=headers, json={"name": "Night", "code": "NGT"})
    ).json()["data"]
    draft_id = shift["draft_version_id"]
    patched = await client.patch(
        f"/v1/shifts/{shift['id']}/versions/{draft_id}",
        headers={**headers, "If-Match": "1"},
        json={
            "shift_type": "FIXED",
            "effective_from": "2026-01-01",
            "start_time": "22:00",
            "end_time": "06:00",
            "timezone": "UTC",
            "breaks": breaks,
        },
    )
    assert patched.status_code == 200, patched.text
    published = await client.post(
        f"/v1/shifts/{shift['id']}/versions/{draft_id}/publish",
        headers={**headers, "If-Match": "2"},
        json={},
    )
    assert published.status_code == 200, published.text
    return shift


async def _assign_night_shift_via_roster(
    client: AsyncClient, headers: dict[str, str], *, employee_id: str, shift_id: str, day: str
) -> None:
    response = await client.post(
        "/v1/rosters",
        headers=headers,
        json={"employee_id": employee_id, "roster_date": day, "shift_id": shift_id},
    )
    assert response.status_code == 201, response.text
    roster = response.json()["data"]
    publish = await client.post(
        f"/v1/rosters/{roster['id']}/publish",
        headers={**headers, "If-Match": "1"},
        json={},
    )
    assert publish.status_code == 200, publish.text


async def test_break_spanning_midnight_matched_end_to_end(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`23:30-00:30` on a `22:00->06:00` shift starting 10 Aug — `F-05`'s defect. Before
    Approach A, this gap was unmatched and unpaid."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        night_shift = await _create_night_shift_with_breaks(
            client,
            headers,
            breaks=[
                {
                    "name": "Midnight break",
                    "break_kind": "FIXED_WINDOW",
                    "start_time": "23:30",
                    "end_time": "00:30",
                    "is_paid": True,
                }
            ],
        )
        await _assign_night_shift_via_roster(
            client, headers, employee_id=employee_id, shift_id=night_shift["id"], day="2026-08-10"
        )

        # 22:00 IN -> 23:45 OUT (break start) -> 00:15 IN (D+1, break end) -> 06:00 OUT (D+1).
        for hour, minute, direction, day in [
            (22, 0, "IN", "2026-08-10"),
            (23, 45, "OUT", "2026-08-10"),
            (0, 15, "IN", "2026-08-11"),
            (6, 0, "OUT", "2026-08-11"),
        ]:
            punch = await client.post(
                "/v1/attendance/punches",
                headers=headers,
                json={
                    "employee_id": employee_id,
                    "punch_time": f"{day}T{hour:02d}:{minute:02d}:00Z",
                    "direction": direction,
                    "reference": "night shift fixture punch",
                },
            )
            assert punch.status_code == 201, punch.text

        calculated = await client.post(
            "/v1/attendance/days/calculate",
            headers=headers,
            params={"employee_id": employee_id, "date": "2026-08-10"},
        )
        assert calculated.status_code == 200, calculated.text
        data = calculated.json()["data"]
        assert data["attendance_status"] == "PRESENT"
        # 8h shift (22:00-06:00) minus the 30m break gap the employee was actually clocked out
        # for, but the break is PAID -> added back. 8h - 0 (break paid, no deduction) = 480m.
        assert data["worked_minutes"] == 480
        assert data["paid_break_minutes"] == 30
        assert data["unpaid_break_minutes"] == 0
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_break_after_midnight_regression_guard_end_to_end(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`01:00-02:00` on the SAME `22:00->06:00` shift — already correct today, and the exact
    case Approach B was proven to regress. Must remain matched end to end, not only in the pure
    `match_breaks` unit test."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        night_shift = await _create_night_shift_with_breaks(
            client,
            headers,
            breaks=[
                {
                    "name": "Post-midnight break",
                    "break_kind": "FIXED_WINDOW",
                    "start_time": "01:00",
                    "end_time": "02:00",
                    "is_paid": True,
                }
            ],
        )
        await _assign_night_shift_via_roster(
            client, headers, employee_id=employee_id, shift_id=night_shift["id"], day="2026-08-10"
        )

        for hour, minute, direction, day in [
            (22, 0, "IN", "2026-08-10"),
            (1, 0, "OUT", "2026-08-11"),
            (2, 0, "IN", "2026-08-11"),
            (6, 0, "OUT", "2026-08-11"),
        ]:
            punch = await client.post(
                "/v1/attendance/punches",
                headers=headers,
                json={
                    "employee_id": employee_id,
                    "punch_time": f"{day}T{hour:02d}:{minute:02d}:00Z",
                    "direction": direction,
                    "reference": "night shift fixture punch",
                },
            )
            assert punch.status_code == 201, punch.text

        calculated = await client.post(
            "/v1/attendance/days/calculate",
            headers=headers,
            params={"employee_id": employee_id, "date": "2026-08-10"},
        )
        assert calculated.status_code == 200, calculated.text
        data = calculated.json()["data"]
        assert data["attendance_status"] == "PRESENT"
        assert data["worked_minutes"] == 480
        assert data["paid_break_minutes"] == 60
        assert data["unpaid_break_minutes"] == 0
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
