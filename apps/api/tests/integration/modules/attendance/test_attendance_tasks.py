"""Phase 8 — `attendance/tasks.py` (`DEC-TZ-07`/`CD-4` SELECTED, execution gate §16). Confirms:

1. `_calculate_company_async` derives its trailing-window dates from `business_today(company.
   timezone)`, not `datetime.now(UTC).date()` — the same `SR-05` class of defect Phase 4/7 close
   elsewhere, now closed at this call site too.
2. The trailing window is exactly `TRAILING_DAYS` (3) calendar days: today and the two before it.
3. An expected, non-error outcome for one employee-date (`AttendanceDayLockedError`) does not stop
   the loop from reaching the remaining employee-dates.
4. `run_daily_calculation` fans out one `calculate_company` task per active company, mirroring
   `leave.run_monthly_accrual`'s own established shape.
"""

from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from tests.integration.modules.attendance.test_attendance_day import (
    _cleanup_attendance_day,
    _register_tenant,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.modules.attendance import tasks as attendance_tasks
from hrms.modules.attendance.exceptions import AttendanceDayLockedError


def _frozen_now(instant: datetime) -> Any:
    return patch(
        "hrms.shared.business_time.datetime", wraps=datetime, **{"now.return_value": instant}
    )


@pytest.mark.asyncio
async def test_calculate_company_uses_business_today_trailing_window(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = (
            await client.post("/v1/employees", headers=headers, json={"first_name": "Deepa"})
        ).json()["data"]
        employee_id = UUID(employee["id"])

        # 01:00 IST on 1 Oct 2026 = 19:30 UTC on 30 Sep — `business_today` must resolve 1 Oct,
        # matching `test_leave_tasks_business_time.py`'s own frozen instant for consistency.
        instant = datetime(2026, 9, 30, 19, 30, tzinfo=UTC)
        with (
            _frozen_now(instant),
            patch(
                "hrms.modules.attendance.service.AttendanceDayService.calculate",
                new_callable=AsyncMock,
            ) as calculate,
        ):
            calculated = await attendance_tasks._calculate_company_async(company_id)

        assert calculated == attendance_tasks.TRAILING_DAYS
        called_dates = sorted(call.args[2] for call in calculate.await_args_list)
        assert called_dates == [date(2026, 9, 29), date(2026, 9, 30), date(2026, 10, 1)]
        for call in calculate.await_args_list:
            assert call.args[0] == company_id
            assert call.args[1] == employee_id
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_calculate_company_survives_a_locked_day(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """One employee-date raising the expected `AttendanceDayLockedError` (a period closed
    mid-sweep, or an interactive lock that landed between the trailing dates being enumerated
    and each one being calculated) must not stop the remaining employee-dates in the loop."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        await client.post("/v1/employees", headers=headers, json={"first_name": "Esha"})

        instant = datetime(2026, 9, 30, 19, 30, tzinfo=UTC)
        with (
            _frozen_now(instant),
            patch(
                "hrms.modules.attendance.service.AttendanceDayService.calculate",
                new_callable=AsyncMock,
                side_effect=[AttendanceDayLockedError(), None, None],
            ) as calculate,
        ):
            calculated = await attendance_tasks._calculate_company_async(company_id)

        assert calculate.await_count == attendance_tasks.TRAILING_DAYS
        assert calculated == attendance_tasks.TRAILING_DAYS - 1
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


def test_run_daily_calculation_fans_out_one_task_per_company() -> None:
    """`run_daily_calculation` is the sync Celery entrypoint (`asyncio.run` inside), so this is
    a plain sync test — calling it from an `async def` test would nest `asyncio.run()` inside an
    already-running event loop and raise, the same reason `test_leave_tasks_business_time.py`
    only ever tests the private async wrappers, never `leave.tasks.run_monthly_accrual` itself.
    No DB round trip is needed: `_list_active_company_ids` is mocked out entirely, so a
    fabricated id stands in for a real company."""
    company_id = uuid4()
    with (
        patch.object(
            attendance_tasks,
            "_list_active_company_ids",
            new_callable=AsyncMock,
            return_value=[company_id],
        ),
        patch.object(attendance_tasks.calculate_company, "delay") as delay,
    ):
        dispatched = attendance_tasks.run_daily_calculation()
    assert dispatched == 1
    delay.assert_called_once_with(str(company_id))
