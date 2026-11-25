"""Integration tests for `GET /v1/attendance/pattern-alerts`.

The alerts read the same stored days and day rules as the dashboard. Under test: each kind of
pattern fires at its threshold with the days behind it, someone below every threshold is left
alone, the filters, the caller's scope, the window rules and the tenant boundary.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from tests.integration.modules.attendance.test_attendance_day import _cleanup_attendance_day
from tests.integration.modules.attendance.test_attendance_summary import _company, _forget_users
from tests.integration.modules.attendance.test_company_attendance_overview import (
    TZ,
    _add_day,
    _setup,
)
from tests.integration.modules.leave.test_leave_notifications import _login_for

from hrms.modules.attendance.permissions import ATTENDANCE_VIEW
from hrms.shared.business_time import business_today

pytestmark = pytest.mark.asyncio

URL = "/v1/attendance/pattern-alerts"


def _at(day: date, hour: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=UTC)


def _complete(day: date, **fields: Any) -> dict[str, Any]:
    return {"actual_first_in": _at(day, 4), "actual_last_out": _at(day, 12), **fields}


async def _seed(client: AsyncClient) -> dict[str, Any]:
    """`_company` plus the history that makes patterns:
    Asha: late on 5 days (today, yesterday and three more).
    Bala: absent on 5 past days, 3 of them on today's weekday.
    Dev: a missing punch on 3 days. Chitra: nothing."""
    ctx = await _company(client)
    cid, today = ctx["company_id"], business_today(TZ)

    for back in (2, 3, 4):
        day = today - timedelta(days=back)
        await _add_day(
            cid, ctx["asha"], day, "PRESENT", **_complete(day, is_late=True, late_minutes=10 + back)
        )
    for back in (2, 3, 14, 21):  # with the existing week-ago absence: 5 in all
        await _add_day(cid, ctx["bala"], today - timedelta(days=back), "ABSENT")
    for back in (10, 11, 12):
        day = today - timedelta(days=back)
        await _add_day(cid, ctx["dev"], day, "INCOMPLETE", actual_first_in=_at(day, 4))
    return {**ctx, "today": today}


def _by(alerts: list[dict[str, Any]], employee: str, kind: str) -> dict[str, Any] | None:
    return next((a for a in alerts if a["employee_id"] == employee and a["kind"] == kind), None)


async def _alerts(client: AsyncClient, headers: dict[str, str], **params: Any) -> dict[str, Any]:
    response = await client.get(URL, headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def test_each_pattern_fires_at_its_threshold_with_the_days_behind_it(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    ctx = await _seed(client)
    today = ctx["today"]
    try:
        data = await _alerts(client, ctx["headers"])
        alerts = data["alerts"]
        assert data["as_of"] == today.isoformat()
        assert data["thresholds"] == {
            "window_days": 30,
            "weekday_window_days": 56,
            "late_days": 5,
            "absent_days": 4,
            "incomplete_days": 3,
            "weekday_absences": 3,
        }

        late = _by(alerts, ctx["asha"], "repeat_late")
        assert late is not None and late["count"] == 5
        assert late["dates"] == sorted(late["dates"], reverse=True)  # newest first
        assert late["dates"][0] == today.isoformat()

        absent = _by(alerts, ctx["bala"], "frequent_absence")
        assert absent is not None and absent["count"] == 5
        assert len(absent["dates"]) == 5 and today.isoformat() not in absent["dates"]

        weekday = _by(alerts, ctx["bala"], "repeat_absent_weekday")
        assert weekday is not None and weekday["count"] == 3
        assert weekday["weekday"] == today.weekday()
        expected = {(today - timedelta(days=b)).isoformat() for b in (7, 14, 21)}
        assert set(weekday["dates"]) == expected

        punch = _by(alerts, ctx["dev"], "repeat_missing_punch")
        assert punch is not None and punch["count"] == 3

        # Chitra has nothing; Asha was never absent, Dev never late.
        assert not [a for a in alerts if a["employee_id"] == ctx["chitra"]]
        assert _by(alerts, ctx["asha"], "frequent_absence") is None
        assert _by(alerts, ctx["dev"], "repeat_late") is None
        # Biggest count first.
        counts = [a["count"] for a in alerts]
        assert counts == sorted(counts, reverse=True)
    finally:
        await _cleanup_attendance_day(company_id=ctx["company_id"])


async def test_a_lower_count_is_not_a_pattern(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    ctx = await _company(client)  # Asha is late twice, Bala absent once
    try:
        assert (await _alerts(client, ctx["headers"]))["alerts"] == []
    finally:
        await _cleanup_attendance_day(company_id=ctx["company_id"])


async def test_filters_window_scope_and_tenant(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    ctx = await _seed(client)
    other = await _setup(client)
    today = ctx["today"]
    created: list[UUID] = []
    try:
        hr = await _alerts(client, ctx["headers"], department_id=ctx["hr"])
        assert hr["alerts"] == []  # only Chitra is in HR, and she has no pattern
        only_asha = await _alerts(client, ctx["headers"], employee_id=ctx["asha"])
        assert {a["employee_id"] for a in only_asha["alerts"]} == {ctx["asha"]}

        # Looking back from a day before the history ends drops what was not yet there.
        earlier = await _alerts(
            client, ctx["headers"], as_of=(today - timedelta(days=5)).isoformat()
        )
        assert (
            _by(earlier["alerts"], ctx["asha"], "repeat_late") is None
        )  # only 3 late days by then

        future = await client.get(
            URL, headers=ctx["headers"], params={"as_of": (today + timedelta(days=1)).isoformat()}
        )
        assert future.status_code == 422

        # Someone who sees only their own attendance sees only their own patterns.
        own, own_user = await _login_for(ctx["company_id"], ctx["bala"], [ATTENDANCE_VIEW], "SELF")
        created.append(own_user)
        mine = await _alerts(client, own)
        assert {a["employee_id"] for a in mine["alerts"]} == {ctx["bala"]}
        chitra, chitra_user = await _login_for(
            ctx["company_id"], ctx["chitra"], [ATTENDANCE_VIEW], "SELF"
        )
        created.append(chitra_user)
        assert (await _alerts(client, chitra))["alerts"] == []

        assert (await _alerts(client, other["headers"]))["alerts"] == []
        assert (await client.get(URL)).status_code in (401, 403)
    finally:
        await _forget_users(ctx["company_id"], created)
        await _cleanup_attendance_day(company_id=ctx["company_id"])
        await _cleanup_attendance_day(company_id=other["company_id"])
