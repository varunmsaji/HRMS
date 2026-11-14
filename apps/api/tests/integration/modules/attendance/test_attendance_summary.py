"""Integration tests for `GET /v1/attendance/summary`.

The endpoint only groups the `attendance_day` rows the calculation engine already wrote, so the
rows are inserted directly with the statuses the engine produces. What is under test is each
figure the dashboards show (daily rate, KPIs, comparison, distribution, punctuality, frequent late,
weekday absence, department/branch breakdown), the filters, the caller's scope and the window
rules. Company timezone is Asia/Kolkata (registration default).
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.test_attendance_day import _cleanup_attendance_day
from tests.integration.modules.attendance.test_company_attendance_overview import (
    TZ,
    _add_day,
    _employee,
    _setup,
)
from tests.integration.modules.leave.test_leave_notifications import _drop_users, _login_for

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.attendance.permissions import ATTENDANCE_VIEW
from hrms.shared.business_time import business_today

pytestmark = pytest.mark.asyncio

URL = "/v1/attendance/summary"


def _at(day: date, hour: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=UTC)


def _complete(day: date, **fields: Any) -> dict[str, Any]:
    return {"actual_first_in": _at(day, 4), "actual_last_out": _at(day, 12), **fields}


async def _company(client: AsyncClient) -> dict[str, Any]:
    """Four employees: Asha and Bala in Engineering, Chitra in HR, Dev in Engineering with no
    attendance day today. Rows today, yesterday and a week ago."""
    ctx = await _setup(client)
    today = business_today(TZ)
    yesterday = today - timedelta(days=1)
    week_ago = today - timedelta(days=7)

    async def add(name: str, department: str) -> str:
        return await _employee(
            client,
            ctx["headers"],
            name=name,
            legal_entity_id=ctx["le"],
            department_id=department,
            branch_id=ctx["branch"],
            designation_id=ctx["desig"],
        )

    asha, bala = await add("Asha", ctx["eng"]), await add("Bala", ctx["eng"])
    chitra, dev = await add("Chitra", ctx["hr"]), await add("Dev", ctx["eng"])
    cid = ctx["company_id"]

    # Today: Asha late by 20 with overtime, Bala absent with no punch, Chitra on leave.
    await _add_day(
        cid, asha, today, "PRESENT",
        **_complete(today, is_late=True, late_minutes=20, ot_minutes_detected=30,
                    ot_minutes_approved=10, worked_minutes=500),
    )  # fmt: skip
    await _add_day(cid, bala, today, "ABSENT")
    await _add_day(cid, chitra, today, "LEAVE")
    # Yesterday: Asha late by 5; Bala checked in late but has not checked out (not judged yet);
    # Chitra's weekly off; Dev on time.
    await _add_day(
        cid, asha, yesterday, "PRESENT", **_complete(yesterday, is_late=True, late_minutes=5)
    )
    await _add_day(
        cid, bala, yesterday, "PRESENT",
        actual_first_in=_at(yesterday, 5), is_late=True, late_minutes=50,
    )  # fmt: skip
    await _add_day(cid, chitra, yesterday, "NOT_EXPECTED", calendar_day_type="WEEKLY_OFF")
    await _add_day(cid, dev, yesterday, "PRESENT", **_complete(yesterday))
    # A week ago (same weekday as today): Asha and Chitra on time, Bala absent.
    await _add_day(cid, asha, week_ago, "PRESENT", **_complete(week_ago))
    await _add_day(cid, bala, week_ago, "ABSENT")
    await _add_day(cid, chitra, week_ago, "PRESENT", **_complete(week_ago))

    return {
        **ctx,
        "today": today,
        "yesterday": yesterday,
        "week_ago": week_ago,
        "asha": asha,
        "bala": bala,
        "chitra": chitra,
        "dev": dev,
    }


async def _forget_users(company_id: UUID, user_ids: list[UUID]) -> None:
    """The test logins: their company link first, then the users themselves."""
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        await session.execute(
            text(
                "DELETE FROM user_role WHERE user_company_id IN "
                "(SELECT id FROM user_company WHERE user_id = ANY(:ids))"
            ),
            {"ids": user_ids},
        )
        await session.execute(
            text("DELETE FROM user_company WHERE user_id = ANY(:ids)"), {"ids": user_ids}
        )
        await session.commit()
    await _drop_users(company_id, user_ids)


async def _summary(client: AsyncClient, headers: dict[str, str], **params: Any) -> Any:
    response = await client.get(URL, headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def test_every_dashboard_figure_over_the_window(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    ctx = await _company(client)
    today, yesterday, week_ago = ctx["today"], ctx["yesterday"], ctx["week_ago"]
    try:
        data = await _summary(
            client, ctx["headers"], date_from=week_ago.isoformat(), date_to=today.isoformat()
        )
        assert data["focus_date"] == today.isoformat()
        assert data["compare_date"] == week_ago.isoformat()
        assert data["is_today"] is True
        assert data["row_count"] == 10

        daily = {d["date"]: d for d in data["daily"]}
        assert len(daily) == 8  # every day of the window, empty ones included
        assert daily[today.isoformat()] == {
            "date": today.isoformat(), "expected": 3, "present": 1, "rate": pytest.approx(100 / 3),
            "remote": 0, "absent": 1, "leave": 1, "late": 1, "checked_in": 1,
            "worked_minutes": 500,
        }  # fmt: skip
        # Bala's open late day still counts as late and checked in for the trend's late %.
        before = daily[yesterday.isoformat()]
        assert (before["late"], before["checked_in"]) == (2, 3)
        # Chitra's weekly off is not expected, so it does not drag the rate down.
        assert daily[yesterday.isoformat()]["expected"] == 3
        assert daily[yesterday.isoformat()]["rate"] == 100
        assert daily[(today - timedelta(days=3)).isoformat()]["rate"] is None

        focus = data["focus"]
        # Dev has no row today: counted as "no record yet" and as not checked in.
        assert focus["total_employees"] == 4 and focus["no_record"] == 1
        assert (focus["present"], focus["absent"], focus["leave"]) == (1, 1, 1)
        assert focus["late"] == 1 and focus["checked_in"] == 1
        assert focus["not_checked_in"] == 2
        assert focus["overtime_employees"] == 1
        assert focus["overtime_minutes_detected"] == 30
        assert focus["overtime_minutes_approved"] == 10

        compare = data["compare"]
        assert (compare["present"], compare["absent"], compare["total_employees"]) == (2, 1, 3)

        assert data["distribution"] == [
            {"bucket": "PRESENT", "count": 1},
            {"bucket": "ABSENT", "count": 1},
            {"bucket": "LEAVE", "count": 1},
        ]

        # Only complete days are judged: Bala's open day yesterday is left out.
        punctuality = data["punctuality"]
        assert (punctuality["checked_in"], punctuality["late"], punctuality["on_time"]) == (5, 2, 3)
        assert punctuality["on_time_rate"] == pytest.approx(60)
        assert punctuality["avg_late_minutes"] == pytest.approx(12.5)
        assert {b["key"]: b["count"] for b in punctuality["bands"]} == {
            "1_15": 1, "16_30": 1, "31_60": 0, "60_plus": 0,
        }  # fmt: skip

        # Asha was late twice; Bala once, so not "frequent".
        assert data["frequent_late"] == [
            {"employee_id": ctx["asha"], "late_days": 2, "total_late_minutes": 25}
        ]

        weekdays = {w["index"]: w for w in data["weekday_absence"]}
        assert weekdays[today.weekday()]["expected"] == 6
        assert weekdays[today.weekday()]["absent"] == 2
        assert weekdays[yesterday.weekday()]["rate"] == 0

        # Lowest attendance first: HR (Chitra on leave) before Engineering (one of two present).
        assert [(g["name"], g["headcount"], g["rate"]) for g in data["by_department"]] == [
            ("HR", 1, 0),
            ("Engineering", 2, 50),
        ]
        assert [(g["name"], g["headcount"]) for g in data["by_branch"]] == [("HQ", 3)]
    finally:
        await _cleanup_attendance_day(company_id=ctx["company_id"])


async def test_filters_narrow_the_population_but_not_the_breakdown(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    ctx = await _company(client)
    window = {"date_from": ctx["week_ago"].isoformat(), "date_to": ctx["today"].isoformat()}
    try:
        hr = await _summary(client, ctx["headers"], **window, department_id=ctx["hr"])
        # Chitra only; Dev (Engineering, no row) is not HR's "no record".
        assert hr["focus"]["total_employees"] == 1 and hr["focus"]["leave"] == 1
        assert hr["row_count"] == 3
        # The breakdown still compares every department.
        assert [g["name"] for g in hr["by_department"]] == ["HR", "Engineering"]

        one = await _summary(client, ctx["headers"], **window, employee_id=ctx["bala"])
        assert one["focus"]["absent"] == 1 and one["focus"]["total_employees"] == 1
        assert one["frequent_late"] == []

        # "unassigned" is the breakdown's Unassigned row: everyone here has a department and
        # a branch, so it matches nobody (and is not mistaken for "no filter").
        for key in ("department_id", "branch_id"):
            none = await _summary(client, ctx["headers"], **window, **{key: "unassigned"})
            assert none["row_count"] == 0 and none["focus"]["total_employees"] == 0
        bad = await client.get(URL, headers=ctx["headers"], params={**window, "branch_id": "x"})
        assert bad.status_code == 422

        # The directory rows carry the same ids, so the web filter can match its lists by id.
        rows = await client.get(
            "/v1/employees/directory/rows",
            headers=ctx["headers"],
            params={"ids": [ctx["chitra"]]},
        )
        assert rows.status_code == 200, rows.text
        [row] = rows.json()["data"]
        assert (row["department_id"], row["branch_id"]) == (ctx["hr"], ctx["branch"])

        # A past focus date has no "no record yet": that only describes today.
        past = await _summary(
            client,
            ctx["headers"],
            date_from=ctx["week_ago"].isoformat(),
            date_to=ctx["yesterday"].isoformat(),
        )
        assert past["is_today"] is False and past["focus"]["no_record"] == 0
        # The comparison day (8 days back) is outside the window and has no rows.
        assert past["compare"] is None
    finally:
        await _cleanup_attendance_day(company_id=ctx["company_id"])


async def test_window_rules(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    ctx = await _setup(client)
    today = business_today(TZ)
    try:
        for params in (
            {"date_from": today.isoformat(), "date_to": (today + timedelta(days=1)).isoformat()},
            {"date_from": today.isoformat(), "date_to": (today - timedelta(days=1)).isoformat()},
            {"date_from": (today - timedelta(days=92)).isoformat(), "date_to": today.isoformat()},
        ):
            response = await client.get(URL, headers=ctx["headers"], params=params)
            assert response.status_code == 422, (params, response.text)

        longest = await _summary(
            client,
            ctx["headers"],
            date_from=(today - timedelta(days=91)).isoformat(),
            date_to=today.isoformat(),
        )
        assert len(longest["daily"]) == 92 and longest["row_count"] == 0
    finally:
        await _cleanup_attendance_day(company_id=ctx["company_id"])


async def test_scope_tenant_and_auth(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    ctx = await _company(client)
    other = await _setup(client)
    window = {"date_from": ctx["week_ago"].isoformat(), "date_to": ctx["today"].isoformat()}
    created: list[UUID] = []
    try:
        # An employee who can see only their own attendance gets only their own figures.
        own, own_user = await _login_for(ctx["company_id"], ctx["asha"], [ATTENDANCE_VIEW], "SELF")
        created.append(own_user)
        mine = await _summary(client, own, **window)
        assert mine["row_count"] == 3
        assert mine["focus"]["total_employees"] == 1 and mine["focus"]["no_record"] == 0
        assert [g["headcount"] for g in mine["by_department"]] == [1]

        # Another company sees nothing of this one, even when it names this one's department.
        theirs = await _summary(client, other["headers"], **window, department_id=ctx["eng"])
        assert theirs["row_count"] == 0 and theirs["by_department"] == []

        assert (await client.get(URL, params=window)).status_code in (401, 403)
    finally:
        await _forget_users(ctx["company_id"], created)
        await _cleanup_attendance_day(company_id=ctx["company_id"])
        await _cleanup_attendance_day(company_id=other["company_id"])
