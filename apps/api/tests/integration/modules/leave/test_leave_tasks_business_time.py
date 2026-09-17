"""Phase 7 (`SR-05`, execution gate §16.3) — `leave/tasks.py`'s per-company async wrappers must
derive their `as_of` date from `business_today(company.timezone)`, not
`datetime.now(UTC).date()`.

`celery_app.py`'s `beat_schedule` runs under `Celery.conf.timezone = settings.app_timezone_default`
(`Asia/Kolkata`): `leave.run_monthly_accrual` fires at `crontab(hour=1)` = **01:00 IST**,
`leave.run_comp_off_expiry_sweep` at `crontab(minute=30, hour=1)` = **01:30 IST**, and
`leave.run_year_end_sweep` at `crontab(hour=2)` = **02:00 IST** — all three squarely inside the
00:00-05:29 IST window where the UTC calendar date is still *yesterday*. Before this fix, every one
of these scheduled runs computed `as_of` as the wrong (previous) day, and the monthly job the wrong
(previous) month's 1st, on every single firing.

Tested at the task-module's private async-wrapper layer (`_accrue_company_async` etc.) rather than
through the Celery task or a worker — these coroutines are exactly what the Celery task calls via
`asyncio.run` (mirrors `test_leave_accrual.py`'s own stated testing philosophy), and this is the
layer that actually changed.
"""

from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from httpx import AsyncClient
from tests.integration.modules.organisation.test_registration_flow import _cleanup, _register

from hrms.modules.leave import tasks as leave_tasks

pytestmark = pytest.mark.asyncio


def _frozen_now(instant: datetime) -> Any:
    return patch(
        "hrms.shared.business_time.datetime", wraps=datetime, **{"now.return_value": instant}
    )


async def _register_company(client: AsyncClient, **overrides: Any) -> UUID:
    response, company_id, user_id = await _register(client, **overrides)
    assert response.status_code == 201, response.text
    assert company_id is not None
    return company_id, user_id


async def test_monthly_accrual_as_of_uses_ist_date_not_utc_date(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """01:00 IST on 1 Oct 2026 is 19:30 UTC on 30 Sep — `as_of` must resolve to 1 Oct (the
    correct month start), not 30 Sep (the previous month, per the stale UTC-date bug)."""
    company_id, user_id = await _register_company(client)
    try:
        instant = datetime(2026, 9, 30, 19, 30, tzinfo=UTC)
        with (
            _frozen_now(instant),
            patch(
                "hrms.modules.leave.service.LeaveAccrualService.run_for_company",
                new_callable=AsyncMock,
                return_value=0,
            ) as run_for_company,
        ):
            await leave_tasks._accrue_company_async(company_id)
        run_for_company.assert_awaited_once()
        _, kwargs = run_for_company.await_args
        assert kwargs["as_of"] == date(2026, 10, 1)
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_comp_off_expiry_sweep_as_of_uses_ist_date_not_utc_date(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """01:30 IST on 1 Oct 2026 is 20:00 UTC on 30 Sep — same divergence, the expiry sweep's own
    scheduled instant."""
    company_id, user_id = await _register_company(client)
    try:
        instant = datetime(2026, 9, 30, 20, 0, tzinfo=UTC)
        with (
            _frozen_now(instant),
            patch(
                "hrms.modules.leave.service.LeaveCompOffService.expire_company",
                new_callable=AsyncMock,
                return_value=0,
            ) as expire_company,
        ):
            await leave_tasks._sweep_comp_off_expiry_async(company_id)
        expire_company.assert_awaited_once()
        _, kwargs = expire_company.await_args
        assert kwargs["as_of"] == date(2026, 10, 1)
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_year_end_sweep_as_of_uses_ist_date_not_utc_date(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """02:00 IST on 1 Oct 2026 is 20:30 UTC on 30 Sep — same divergence, the year-end sweep's own
    scheduled instant."""
    company_id, user_id = await _register_company(client)
    try:
        instant = datetime(2026, 9, 30, 20, 30, tzinfo=UTC)
        with (
            _frozen_now(instant),
            patch(
                "hrms.modules.leave.service.LeaveAccrualService.run_year_end_for_company",
                new_callable=AsyncMock,
                return_value=0,
            ) as run_year_end,
        ):
            await leave_tasks._run_year_end_async(company_id)
        run_year_end.assert_awaited_once()
        _, kwargs = run_year_end.await_args
        assert kwargs["as_of"] == date(2026, 10, 1)
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_no_datetime_now_utc_date_call_sites_remain() -> None:
    """Regression guard for the defect class itself, not just its three known instances — a grep
    a future contributor can re-run by reading this test. Checks executable lines only, so the
    explanatory comments above (which necessarily name the banned pattern) don't self-trigger it."""
    import inspect

    code_lines = [
        line
        for line in inspect.getsource(leave_tasks).splitlines()
        if not line.strip().startswith("#")
    ]
    code = "\n".join(code_lines)
    assert "datetime.now(UTC).date()" not in code
    assert "date.today()" not in code
