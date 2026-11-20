"""The home dashboard (company overview) and the Attendance page (summary) must agree.

Both endpoints read the same stored `attendance_day` rows through `day_classification`. For one
date and one population, the counts that mean the same thing must be identical, and so must the
attendance rate. The rows below are the cases the two endpoints used to decide differently: a half
day (own figure, half weight, never "present"), an open check-in and a no-punch day while the shift
is still running, a config error, a past date with a missing row, and a day with a pending
regularization.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from tests.integration.modules.attendance.test_attendance_day import _cleanup_attendance_day
from tests.integration.modules.attendance.test_company_attendance_overview import (
    TZ,
    _add_day,
    _employee,
    _setup,
)
from tests.integration.modules.attendance.test_company_attendance_overview import (
    URL as OVERVIEW_URL,
)

from hrms.shared.business_time import business_today

pytestmark = pytest.mark.asyncio

SUMMARY_URL = "/v1/attendance/summary"

#: overview field -> summary focus field, for figures that mean the same thing.
SHARED = {
    "present": "present",
    "half_day": "half_day",
    "absent": "absent",
    "on_leave": "leave",
    "not_checked_in": "not_in_yet",
    "no_record": "no_record",
    "expected_employees": "expected",
    "exceptions": "exceptions",
}


async def _both(client: AsyncClient, headers: dict[str, str], day: Any) -> tuple[Any, Any]:
    overview = await client.get(OVERVIEW_URL, headers=headers, params={"date": day.isoformat()})
    summary = await client.get(
        SUMMARY_URL,
        headers=headers,
        params={"date_from": day.isoformat(), "date_to": day.isoformat()},
    )
    assert overview.status_code == 200, overview.text
    assert summary.status_code == 200, summary.text
    return overview.json()["data"], summary.json()["data"]


def _assert_agree(overview: Any, summary: Any) -> None:
    focus = summary["focus"]
    for overview_key, summary_key in SHARED.items():
        assert overview[overview_key] == focus[summary_key], (
            f"{overview_key}: overview {overview[overview_key]} != summary {focus[summary_key]}"
        )
    assert overview["attendance_rate"] == pytest.approx(focus["rate"])
    # The trend's rate for the focus day is the same figure again.
    assert summary["daily"][-1]["rate"] == pytest.approx(focus["rate"])


async def test_today_both_dashboards_count_the_same(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    ctx = await _setup(client)
    headers, company_id = ctx["headers"], ctx["company_id"]
    today = business_today(TZ)
    now = datetime.now(UTC)
    past, future = now - timedelta(hours=2), now + timedelta(hours=3)
    first_in = now - timedelta(minutes=90)
    try:

        async def emp(name: str) -> str:
            return await _employee(
                client,
                headers,
                name=name,
                legal_entity_id=ctx["le"],
                department_id=ctx["eng"],
                branch_id=ctx["branch"],
                designation_id=ctx["desig"],
            )

        full = await emp("Full")
        half = await emp("Half")
        open_in = await emp("OpenIn")
        no_punch_running = await emp("NoPunchRunning")
        no_punch_over = await emp("NoPunchOver")
        config = await emp("Config")
        leave = await emp("Leave")
        await emp("NoRow")

        await _add_day(
            company_id, full, today, "PRESENT",
            actual_first_in=first_in, actual_last_out=now, scheduled_end=past,
        )  # fmt: skip
        await _add_day(
            company_id, half, today, "HALF_DAY",
            actual_first_in=first_in, actual_last_out=now, scheduled_end=past,
        )  # fmt: skip
        await _add_day(
            company_id, open_in, today, "INCOMPLETE",
            actual_first_in=first_in, missing_punch=True, scheduled_end=future,
        )  # fmt: skip
        await _add_day(company_id, no_punch_running, today, "ABSENT", scheduled_end=future)
        await _add_day(company_id, no_punch_over, today, "ABSENT", scheduled_end=past)
        await _add_day(company_id, config, today, "CONFIG_ERROR", scheduled_end=past)
        await _add_day(
            company_id, leave, today, "LEAVE", leave_fraction=Decimal("1.00"), scheduled_end=future
        )

        overview, summary = await _both(client, headers, today)
        _assert_agree(overview, summary)

        # The cases that used to differ, spelled out.
        assert overview["present"] == 2  # Full, and OpenIn while its shift runs
        assert overview["half_day"] == 1  # its own figure, not "present"
        assert overview["absent"] == 1  # only the one whose shift is over
        assert overview["not_checked_in"] == 1  # never "absent" while the shift runs
        assert overview["incomplete"] == 1  # the config error
        assert overview["no_record"] == 1
        # 7 expected: present 2 x 1 + half day 1 x 0.5 = 2.5 of 7.
        assert overview["expected_employees"] == 7
        assert overview["attendance_rate"] == pytest.approx(2.5 / 7 * 100)
        # Both endpoints sort every row into exactly one primary bucket.
        buckets = (
            "present half_day absent on_leave on_duty remote_work not_checked_in incomplete "
            "not_expected no_record"
        ).split()
        assert sum(overview[b] for b in buckets) == overview["total"]

        # Each row's own `display.code` is the bucket the dashboards counted it in.
        days = await client.get(
            "/v1/attendance/days",
            headers=headers,
            params={"date_from": today.isoformat(), "date_to": today.isoformat(), "page_size": 100},
        )
        assert days.status_code == 200, days.text
        rows = days.json()["data"]
        codes = [d["display"]["code"] for d in rows]
        assert codes.count("PRESENT") == overview["present"]
        assert codes.count("HALF_DAY") == overview["half_day"]
        assert codes.count("ABSENT") == overview["absent"]
        assert codes.count("NOT_CHECKED_IN") == overview["not_checked_in"]
        assert codes.count("LEAVE") == overview["on_leave"]
        provisional = {d["display"]["code"] for d in rows if d["display"]["provisional"]}
        assert provisional == {"PRESENT", "NOT_CHECKED_IN"}
    finally:
        await _cleanup_attendance_day(company_id=company_id)


async def test_past_date_both_dashboards_count_the_same(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    ctx = await _setup(client)
    headers, company_id = ctx["headers"], ctx["company_id"]
    day = business_today(TZ) - timedelta(days=2)
    try:

        async def emp(name: str) -> str:
            return await _employee(
                client,
                headers,
                name=name,
                legal_entity_id=ctx["le"],
                department_id=ctx["eng"],
                branch_id=ctx["branch"],
                designation_id=ctx["desig"],
            )

        full = await emp("Full")
        half = await emp("Half")
        absent = await emp("Absent")
        open_day = await emp("Open")
        await emp("Missing")  # employed that day, never calculated
        at = datetime(day.year, day.month, day.day, 4, tzinfo=UTC)
        await _add_day(company_id, full, day, "PRESENT", actual_first_in=at)
        await _add_day(company_id, half, day, "HALF_DAY", actual_first_in=at)
        await _add_day(company_id, absent, day, "ABSENT")
        # Even with the row's shift "ending" in the future, a past date is never in progress.
        await _add_day(
            company_id, open_day, day, "INCOMPLETE",
            actual_first_in=at, missing_punch=True,
            scheduled_end=datetime.now(UTC) + timedelta(hours=1),
        )  # fmt: skip

        overview, summary = await _both(client, headers, day)
        _assert_agree(overview, summary)

        assert overview["not_checked_in"] == 0  # a past day is never "not in yet"
        assert overview["absent"] == 1 and overview["incomplete"] == 1
        assert overview["no_record"] == 1  # the missing row is reported, not guessed
        assert overview["half_day"] == 1 and overview["present"] == 1
        assert overview["attendance_rate"] == pytest.approx(1.5 / 4 * 100)
    finally:
        await _cleanup_attendance_day(company_id=company_id)
