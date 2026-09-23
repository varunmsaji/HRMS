"""PAY-001 — `POST /v1/attendance/days/calculate-range` and the `attendance.calculate_range` job
(`tasks._calculate_range_async`): a whole period can be calculated in one request and then
finalized, without one call per employee-date."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

import pytest
from httpx import AsyncClient
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
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.modules.attendance import tasks as attendance_tasks

pytestmark = pytest.mark.asyncio


async def test_calculate_range_queues_job_and_validates_input(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        with patch.object(
            attendance_tasks.calculate_range, "delay", return_value=SimpleNamespace(id="job-1")
        ) as delay:
            queued = await client.post(
                "/v1/attendance/days/calculate-range",
                headers=headers,
                json={"date_from": "2026-08-01", "date_to": "2026-08-31"},
            )
            assert queued.status_code == 202, queued.text
            assert queued.json()["data"]["task_id"] == "job-1"
            delay.assert_called_once_with(
                str(company_id), "2026-08-01", "2026-08-31", None, str(user_id)
            )

            too_long = await client.post(
                "/v1/attendance/days/calculate-range",
                headers=headers,
                json={"date_from": "2026-06-01", "date_to": "2026-08-31"},
            )
            assert too_long.status_code == 422, too_long.text

            backwards = await client.post(
                "/v1/attendance/days/calculate-range",
                headers=headers,
                json={"date_from": "2026-08-31", "date_to": "2026-08-01"},
            )
            assert backwards.status_code == 422, backwards.text

            future = await client.post(
                "/v1/attendance/days/calculate-range",
                headers=headers,
                json={"date_from": "2099-01-01", "date_to": "2099-01-02"},
            )
            assert future.status_code == 422, future.text
            assert future.json()["error"]["code"] == "ATTENDANCE_RANGE_IN_FUTURE"
            assert delay.call_count == 1
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_range_job_calculates_only_employed_days_and_period_finalizes(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers, joining_date="2026-08-11")
        employee_id = wired["employee"]["id"]
        for day in ("2026-08-11", "2026-08-12"):
            await _punch(
                client, headers, employee_id=employee_id, hour=9, minute=0, direction="IN", day=day
            )
            await _punch(
                client,
                headers,
                employee_id=employee_id,
                hour=18,
                minute=0,
                direction="OUT",
                day=day,
            )

        counts = await attendance_tasks._calculate_range_async(
            company_id, date(2026, 8, 10), date(2026, 8, 12), None, None
        )
        assert counts == {"employees": 1, "calculated": 2, "skipped_locked": 0, "failed": 0}

        days = await client.get(
            "/v1/attendance/days",
            headers=headers,
            params={"employee_id": employee_id, "date_from": "2026-08-10", "date_to": "2026-08-12"},
        )
        assert sorted(d["attendance_date"] for d in days.json()["data"]) == [
            "2026-08-11",
            "2026-08-12",
        ]

        period = await _create_period(
            client, headers, period_start="2026-08-10", period_end="2026-08-12"
        )
        finalized = await client.post(
            f"/v1/attendance-periods/{period['id']}/finalize",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert finalized.status_code == 200, finalized.text

        # A second run over the now-locked period skips every day instead of failing.
        rerun = await attendance_tasks._calculate_range_async(
            company_id, date(2026, 8, 10), date(2026, 8, 12), [UUID(employee_id)], None
        )
        assert rerun == {"employees": 1, "calculated": 0, "skipped_locked": 2, "failed": 0}
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
