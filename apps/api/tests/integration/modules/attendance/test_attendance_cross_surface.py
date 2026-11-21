"""R-G01 — the dashboards and the day pages count one day the same way.

One company, one date, a row of every kind. The company overview (home dashboard), the attendance
summary (Attendance page) and the per-day `display.code` (day pages, calendars) are read for that
same date and must agree on every figure they share. Before R-B01/R-B02 they did not: a half day
was "present" on one and its own figure on the other, and an open day was named differently on
each. A figure added to one endpoint but not the other fails here.
"""

from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from tests.integration.modules.attendance.test_attendance_day import _cleanup_attendance_day
from tests.integration.modules.attendance.test_company_attendance_overview import (
    TZ,
    _add_day,
    _employee,
    _setup,
)

from hrms.shared.business_time import business_today

pytestmark = pytest.mark.asyncio

OVERVIEW = "/v1/dashboards/company/attendance-overview"
SUMMARY = "/v1/attendance/summary"
DAYS = "/v1/attendance/days"


async def test_overview_summary_and_day_pages_agree_for_one_date(
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
        late = await emp("Late")
        half = await emp("Half")
        absent = await emp("Absent")
        not_yet = await emp("NotYet")
        on_leave = await emp("OnLeave")
        weekly_off = await emp("WeeklyOff")
        holiday = await emp("Holiday")
        in_progress = await emp("InProgress")
        missing_out = await emp("MissingOut")
        broken = await emp("Broken")
        on_duty = await emp("OnDuty")
        await emp("NoRecord")  # never gets a row

        worked = {"actual_first_in": first_in, "worked_minutes": 480}
        await _add_day(company_id, full, today, "PRESENT", scheduled_end=past, **worked)
        await _add_day(
            company_id, late, today, "PRESENT",
            is_late=True, late_minutes=20, scheduled_end=past, **worked,
        )  # fmt: skip
        await _add_day(
            company_id, half, today, "HALF_DAY",
            paid_day_fraction=Decimal("0.50"), scheduled_end=past,
            actual_first_in=first_in, worked_minutes=240,
        )  # fmt: skip
        await _add_day(company_id, absent, today, "ABSENT", scheduled_end=past)
        await _add_day(company_id, not_yet, today, "ABSENT", scheduled_end=future)
        await _add_day(company_id, on_leave, today, "LEAVE", scheduled_end=future)
        await _add_day(
            company_id, weekly_off, today, "NOT_EXPECTED", calendar_day_type="WEEKLY_OFF"
        )
        await _add_day(
            company_id, holiday, today, "NOT_EXPECTED",
            calendar_day_type="HOLIDAY", holiday_name="Diwali",
        )  # fmt: skip
        await _add_day(
            company_id, in_progress, today, "INCOMPLETE",
            actual_first_in=first_in, missing_punch=True, scheduled_end=future,
        )  # fmt: skip
        await _add_day(
            company_id, missing_out, today, "INCOMPLETE",
            actual_first_in=first_in, missing_punch=True, scheduled_end=past,
        )  # fmt: skip
        await _add_day(company_id, broken, today, "CONFIG_ERROR", scheduled_end=past)
        await _add_day(company_id, on_duty, today, "ON_DUTY", scheduled_end=past)

        overview = (await client.get(OVERVIEW, headers=headers)).json()["data"]
        summary = (
            await client.get(
                SUMMARY,
                headers=headers,
                params={"date_from": today.isoformat(), "date_to": today.isoformat()},
            )
        ).json()["data"]
        kpi = summary["focus"]
        days = (
            await client.get(
                DAYS,
                headers=headers,
                params={"date_from": today.isoformat(), "date_to": today.isoformat()},
            )
        ).json()["data"]

        # -- overview vs summary: the same names for the same people ---------------------------
        pairs = {
            "total": ("total", "total_employees"),
            "present": ("present", "present"),
            "half_day": ("half_day", "half_day"),
            "absent": ("absent", "absent"),
            "on_leave": ("on_leave", "leave"),
            "on_duty": ("on_duty", "on_duty"),
            "not_checked_in": ("not_checked_in", "not_in_yet"),
            "incomplete": ("incomplete", "incomplete"),
            "no_record": ("no_record", "no_record"),
            "expected": ("expected_employees", "expected"),
            "late": ("late", "late"),
            "exceptions": ("exceptions", "exceptions"),
        }
        for name, (overview_key, summary_key) in pairs.items():
            assert overview[overview_key] == kpi[summary_key], (
                f"{name}: overview {overview[overview_key]} != summary {kpi[summary_key]}"
            )
        assert overview["not_expected"] == kpi["holiday"] + kpi["weekly_off"]
        assert overview["attendance_rate"] == kpi["rate"]

        # -- the day pages name each day with the bucket the dashboards counted -----------------
        by_code = Counter(d["display"]["code"] for d in days)
        assert by_code["PRESENT"] == overview["present"]
        assert by_code["HALF_DAY"] == overview["half_day"]
        assert by_code["ABSENT"] == overview["absent"]
        assert by_code["LEAVE"] == overview["on_leave"]
        assert by_code["ON_DUTY"] == overview["on_duty"]
        assert by_code["NOT_CHECKED_IN"] == overview["not_checked_in"]
        # The dashboards fold a day the engine could not calculate into "incomplete"; the day
        # pages name it separately ("Needs attention").
        assert by_code["INCOMPLETE"] + by_code["CONFIG_ERROR"] == overview["incomplete"]
        assert by_code["HOLIDAY"] + by_code["WEEKLY_OFF"] == overview["not_expected"]
        assert by_code["CONFIG_ERROR"] == 1
        # Every stored row is named; the employee with no row is the only one not in the list.
        assert sum(by_code.values()) == overview["total"] - overview["no_record"]
        # A holiday is named a holiday, never "Not expected" (AUD-11).
        assert {d["display"]["label"] for d in days if d["display"]["code"] == "HOLIDAY"} == {
            "Holiday"
        }
    finally:
        await _cleanup_attendance_day(company_id=company_id)
