"""R-04: correcting an earlier day's lateness recomputes the later days of that month, because the
every-Nth late rule (D-10) counts the earlier days."""

from datetime import date
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.test_attendance_day import (
    _build_wired_employee,
    _cleanup_attendance_day,
    _punch,
    _register_tenant,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.core.db.session import get_session_factory, set_rls_company_id

pytestmark = pytest.mark.asyncio

# Monday to Wednesday.
_DAYS = ("2026-08-10", "2026-08-11", "2026-08-12")


async def _set_lates_to_half_day(company_id: Any, count: int) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        await session.execute(
            text(
                "UPDATE attendance_policy_version SET lates_to_half_day_count = :n "
                "WHERE company_id = :cid"
            ),
            {"n": count, "cid": str(company_id)},
        )
        await session.commit()


async def _lock_day(company_id: Any, employee_id: str, day: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        await session.execute(
            text(
                "UPDATE attendance_day SET is_locked = true "
                "WHERE company_id = :cid AND employee_id = :eid AND attendance_date = :d"
            ),
            {"cid": str(company_id), "eid": employee_id, "d": date.fromisoformat(day)},
        )
        await session.commit()


async def _days(client: AsyncClient, headers: dict[str, str], employee_id: str) -> list[Any]:
    response = await client.get(
        "/v1/attendance/days",
        headers=headers,
        params={"employee_id": employee_id, "date_from": _DAYS[0], "date_to": _DAYS[-1]},
    )
    assert response.status_code == 200, response.text
    rows = sorted(response.json()["data"], key=lambda r: r["attendance_date"])
    assert [r["attendance_date"] for r in rows] == list(_DAYS)
    return rows


async def _three_late_days(client: AsyncClient, headers: dict[str, str], company_id: Any) -> str:
    """Late on all three days with a count of 3, so the third is a HALF_DAY."""
    wired = await _build_wired_employee(client, headers)
    employee_id = str(wired["employee"]["id"])
    await _set_lates_to_half_day(company_id, 3)
    for day in _DAYS:
        await _punch(
            client, headers, employee_id=employee_id, hour=9, minute=30, direction="IN", day=day
        )
        await _punch(
            client, headers, employee_id=employee_id, hour=18, minute=0, direction="OUT", day=day
        )
    return employee_id


async def test_correcting_an_earlier_late_day_recomputes_the_later_days(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = await _three_late_days(client, headers, company_id)
        before = await _days(client, headers, employee_id)
        assert [d["is_late"] for d in before] == [True, True, True]
        assert before[2]["attendance_status"] == "HALF_DAY"

        # A 09:00 IN on the first day: the 09:30 IN becomes a stray, so that day is on time.
        await _punch(
            client, headers, employee_id=employee_id, hour=9, minute=0, direction="IN", day=_DAYS[0]
        )

        after = await _days(client, headers, employee_id)
        assert [d["is_late"] for d in after] == [False, True, True]
        # The third day is now only the second late day of the month.
        assert after[2]["attendance_status"] == "PRESENT"
        assert after[2]["calculation_version"] > before[2]["calculation_version"]
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_a_change_that_keeps_lateness_does_not_recompute_later_days(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = await _three_late_days(client, headers, company_id)
        before = await _days(client, headers, employee_id)

        # A second OUT ten minutes later changes the first day but not whether it was late.
        await _punch(
            client,
            headers,
            employee_id=employee_id,
            hour=18,
            minute=10,
            direction="OUT",
            day=_DAYS[0],
        )

        after = await _days(client, headers, employee_id)
        assert after[0]["calculation_version"] > before[0]["calculation_version"]
        assert after[0]["is_late"] is True
        for day_before, day_after in zip(before[1:], after[1:], strict=True):
            assert day_after["calculation_version"] == day_before["calculation_version"]
        assert after[2]["attendance_status"] == "HALF_DAY"
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_a_locked_later_day_is_not_recomputed(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = await _three_late_days(client, headers, company_id)
        await _lock_day(company_id, employee_id, _DAYS[2])
        before = await _days(client, headers, employee_id)

        await _punch(
            client, headers, employee_id=employee_id, hour=9, minute=0, direction="IN", day=_DAYS[0]
        )

        after = await _days(client, headers, employee_id)
        assert after[0]["is_late"] is False
        assert after[1]["calculation_version"] > before[1]["calculation_version"]
        assert after[2]["calculation_version"] == before[2]["calculation_version"]
        assert after[2]["attendance_status"] == "HALF_DAY"
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
