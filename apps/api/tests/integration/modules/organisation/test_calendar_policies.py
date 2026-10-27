"""Work Calendar phase 4 - policy alignment, against the disposable integration stack.

A  half-day weekly off is read identically by leave and attendance
B  no automatic substitute holiday; an explicit exception is the only mechanism
C  `Holiday.is_working` mirrors `holiday_type == WORKING_HOLIDAY`
D  holiday-calendar validity is applied by resolution, preview and confirmation alike
E  protected periods: acknowledged confirmation never rewrites history
F  a work calendar / weekly-off pattern cannot be deactivated while assignments depend on it

September 2026: 1 Sep is a Tuesday; Saturdays 5/12/19/26, Sundays 6/13/20/27. The `_world` company
calendar has Sunday off and one linked holiday calendar "H"; Saturday is a working day until a
test changes the pattern.
"""

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.test_attendance_policy import _cleanup_attendance
from tests.integration.modules.leave.test_leave_application import _submit, _teardown
from tests.integration.modules.leave.test_leave_rbac_matrix import _user_with_default_role

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.shared.business_time import business_today

from .test_calendar_impact import (
    CONFIRM,
    PREVIEW,
    World,
    _audit_count,
    _confirm,
    _finish,
    _holiday,
    _preview,
    _preview_ok,
    _row_hashes,
    _world,
)
from .test_employee_calendar import _assign
from .test_workforce_calendar import (
    _cleanup_workforce_calendar,
    _create_holiday,
    _create_holiday_calendar,
    _create_weekly_off_pattern,
    _create_work_calendar,
)

pytestmark = pytest.mark.asyncio

SEPTEMBER = {"window_from": "2026-09-01", "window_to": "2026-09-30"}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


async def _sql(company_id: UUID, sql: str, **params: Any) -> list[Any]:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        result = await session.execute(text(sql), params)
        rows = list(result.all()) if result.returns_rows else []
        await session.commit()
        return rows


async def _set_company_pattern(client: AsyncClient, w: World, rules: list[dict[str, Any]]) -> None:
    pattern_id = w.calendar["weekly_off_pattern_id"]
    current = (await client.get(f"/v1/weekly-off-patterns/{pattern_id}", headers=w.admin)).json()[
        "data"
    ]
    response = await client.patch(
        f"/v1/weekly-off-patterns/{pattern_id}",
        headers={**w.admin, "If-Match": str(current["version"])},
        json={"rules": rules},
    )
    assert response.status_code == 200, response.text


async def _leave_days(w: World, application_id: str) -> list[tuple[str, str, str | None, bool]]:
    rows = await _sql(
        w.company_id,
        "SELECT calendar_date, fraction, half, is_sandwich_generated FROM leave_application_day "
        "WHERE leave_application_id = CAST(:a AS uuid) ORDER BY calendar_date",
        a=application_id,
    )
    return [(r[0].isoformat(), f"{r[1]:.2f}", r[2], r[3]) for r in rows]


async def _attendance_day(w: World, day: str) -> dict[str, Any]:
    rows = await _sql(
        w.company_id,
        "SELECT attendance_status, leave_fraction, weekly_off_fraction, paid_day_fraction, "
        "lop_fraction FROM attendance_day WHERE employee_id = CAST(:e AS uuid) "
        "AND attendance_date = :d",
        e=w.employee_id,
        d=date.fromisoformat(day),
    )
    assert len(rows) == 1, f"no attendance_day for {day}"
    r = rows[0]
    return {
        "status": r[0],
        "leave": f"{r[1]:.2f}",
        "off": f"{r[2]:.2f}",
        "paid": f"{r[3]:.2f}",
        "lop": f"{r[4]:.2f}",
    }


async def _attach_attendance_policy(client: AsyncClient, w: World) -> None:
    """Without an attendance policy a day is a CONFIG_ERROR and no overlay runs; this is the
    minimum that lets attendance reach a verdict (mirrors `_build_wired_employee`)."""
    policy = (
        await client.post("/v1/attendance-policies", headers=w.admin, json={"name": "Standard"})
    ).json()["data"]
    draft = (
        await client.post(
            f"/v1/attendance-policies/{policy['id']}/versions",
            headers=w.admin,
            json={
                "effective_from": "2026-01-01",
                "hour_bands": [
                    {"min_minutes": 0, "max_minutes": 239, "result_status": "ABSENT"},
                    {"min_minutes": 240, "max_minutes": None, "result_status": "PRESENT"},
                ],
            },
        )
    ).json()["data"]
    published = await client.post(
        f"/v1/attendance-policies/{policy['id']}/versions/{draft['id']}/publish",
        headers={**w.admin, "If-Match": "1"},
        json={},
    )
    assert published.status_code == 200, published.text
    assigned = await client.post(
        "/v1/policy-assignments",
        headers=w.admin,
        json={
            "policy_kind": "ATTENDANCE_POLICY",
            "policy_id": policy["id"],
            "scope_type": "COMPANY",
            "effective_from": "2026-01-01",
        },
    )
    assert assigned.status_code == 201, assigned.text


async def _finish_with_attendance(w: World) -> None:
    """`_finish` plus the attendance policy rows this module adds (after the attendance days that
    reference them are gone, before the company is deleted)."""
    from tests.integration.modules.attendance.test_attendance_security import (
        _cleanup_scoped_users,
    )
    from tests.integration.modules.leave.test_leave_application import _cleanup

    await _cleanup_workforce_calendar(company_id=w.company_id)
    await _teardown(company_id=w.company_id)
    await _cleanup_attendance(company_id=w.company_id)
    await _cleanup(company_id=w.company_id, user_id=w.user_id)
    await _cleanup_scoped_users()


async def _apply(client: AsyncClient, w: World, **body: Any) -> Any:
    return await _submit(
        client, w.admin, employee_id=w.employee_id, leave_type_id=w.ctx["leave_type"]["id"], **body
    )


async def _days(client: AsyncClient, w: World, calendar_id: str, start: str, end: str):
    response = await client.get(
        f"/v1/work-calendars/{calendar_id}/days",
        headers=w.admin,
        params={"from": start, "to": end},
    )
    assert response.status_code == 200, response.text
    return {d["date"]: d for d in response.json()["data"]["days"]}


def _day_type(day: dict[str, Any]) -> str:
    return str(
        day["day_type"]["day_type"] if isinstance(day.get("day_type"), dict) else day["day_type"]
    )


async def _resolved(client: AsyncClient, w: World, employee_id: str, day: str) -> dict[str, Any]:
    response = await client.get(
        "/v1/calendar-resolution",
        headers=w.admin,
        params={"employee_id": employee_id, "date": day},
    )
    assert response.status_code == 200, response.text
    return dict(response.json()["data"]["day_type"])


# ---------------------------------------------------------------------------
# Policy A - half-day weekly off, leave and attendance
# ---------------------------------------------------------------------------


async def test_half_day_weekly_off_leave_and_attendance_agree(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client)
    try:
        await _attach_attendance_policy(client, w)
        await _set_company_pattern(
            client,
            w,
            [{"weekday": 5, "off_fraction": "0.50"}, {"weekday": 6, "off_fraction": "1.00"}],
        )
        # The calendar says: Saturday is half off, half working.
        saturday = await _resolved(client, w, w.employee_id, "2026-09-05")
        assert (saturday["day_type"], saturday["weekly_off_fraction"]) == ("WEEKLY_OFF", "0.50")

        # A full-day application on the half-day weekly off consumes the working half only.
        full = await _apply(client, w, start_date="2026-09-05", end_date="2026-09-05")
        assert full.status_code == 201, full.text
        assert await _leave_days(w, full.json()["data"]["id"]) == [
            ("2026-09-05", "0.50", None, False)
        ]
        # ...and attendance agrees for the same employee and date: leave 0.5 + off 0.5 = a paid
        # day with no loss of pay.
        assert await _attendance_day(w, "2026-09-05") == {
            "status": "LEAVE",
            "leave": "0.50",
            "off": "0.50",
            "paid": "1.00",
            "lop": "0.00",
        }

        # The same date cannot be booked twice for the working half (cap = working fraction).
        again = await _apply(client, w, start_date="2026-09-05", end_date="2026-09-05")
        assert again.status_code == 409, again.text

        # Leave spanning a weekly off: Fri 11 - Mon 14 crosses a half-day Saturday and a full
        # Sunday; the sandwich rule makes the bracketed full Sunday a whole sandwich day.
        span = await _apply(client, w, start_date="2026-09-11", end_date="2026-09-14")
        assert span.status_code == 201, span.text
        assert await _leave_days(w, span.json()["data"]["id"]) == [
            ("2026-09-11", "1.00", None, False),
            ("2026-09-12", "0.50", None, False),
            ("2026-09-13", "1.00", None, True),
            ("2026-09-14", "1.00", None, False),
        ]

        # Half-day leave on the half-day weekly off keeps its half marker.
        half = await _apply(
            client, w, start_date="2026-09-19", end_date="2026-09-19", half_day="FIRST_HALF"
        )
        assert half.status_code == 201, half.text
        assert await _leave_days(w, half.json()["data"]["id"]) == [
            ("2026-09-19", "0.50", "FIRST_HALF", False)
        ]
        assert (await _attendance_day(w, "2026-09-19"))["paid"] == "1.00"

        # A full weekly off still consumes nothing: a lone Sunday is not a leave day.
        sunday = await _apply(client, w, start_date="2026-09-20", end_date="2026-09-20")
        assert sunday.status_code == 422, sunday.text
    finally:
        await _finish_with_attendance(w)


async def test_full_day_weekly_off_leave_behaviour_is_unchanged(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client)
    try:
        await _set_company_pattern(client, w, [{"weekday": 5, "off_fraction": "1.00"}])
        lone = await _apply(client, w, start_date="2026-09-05", end_date="2026-09-05")
        assert lone.status_code == 422, lone.text
        # Without a bracketing working day the range ends on the weekly off: only Fri counts.
        end_on_off = await _apply(client, w, start_date="2026-09-04", end_date="2026-09-05")
        assert end_on_off.status_code == 201, end_on_off.text
        assert await _leave_days(w, end_on_off.json()["data"]["id"]) == [
            ("2026-09-04", "1.00", None, False)
        ]
    finally:
        await _finish(w)


async def test_effective_dated_override_changes_what_leave_can_consume(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client)
    try:
        await _set_company_pattern(
            client,
            w,
            [{"weekday": 5, "off_fraction": "0.50"}, {"weekday": 6, "off_fraction": "1.00"}],
        )
        full_saturday = await _create_weekly_off_pattern(
            client, w.admin, name="Saturday Off", rules=[{"weekday": 5, "off_fraction": "1.00"}]
        )
        await _assign(
            client,
            w.admin,
            policy_kind="WEEKLY_OFF",
            policy_id=full_saturday["id"],
            scope_type="EMPLOYEE",
            scope_id=w.employee_id,
            effective_from="2026-09-26",
        )
        # Before the effective date the company's half-day Saturday applies...
        before = await _apply(client, w, start_date="2026-09-19", end_date="2026-09-19")
        assert before.status_code == 201, before.text
        assert (await _leave_days(w, before.json()["data"]["id"]))[0][1] == "0.50"
        # ...from it the employee's own full-day Saturday off applies: nothing to consume.
        after = await _apply(client, w, start_date="2026-09-26", end_date="2026-09-26")
        assert after.status_code == 422, after.text
        # The colleague stays on the company pattern, so attendance/leave still see a half day.
        other = await _resolved(client, w, str(w.other_employee["id"]), "2026-09-26")
        assert other["weekly_off_fraction"] == "0.50"
        mine = await _resolved(client, w, w.employee_id, "2026-09-26")
        assert mine["weekly_off_fraction"] == "1.00"
    finally:
        await _finish(w)


async def test_approved_leave_snapshots_are_not_rewritten_by_a_weekly_off_change(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Existing leave days keep the fractions they were approved with when the pattern later
    becomes half-day (policy A is not retroactive)."""
    w = await _world(client)
    try:
        approved = await _apply(client, w, start_date="2026-09-08", end_date="2026-09-08")
        assert approved.status_code == 201
        before = await _row_hashes(w.company_id)
        await _set_company_pattern(
            client,
            w,
            [{"weekday": 1, "off_fraction": "0.50"}, {"weekday": 6, "off_fraction": "1.00"}],
        )  # Tuesday becomes a half-day off *after* 8 Sep was approved
        assert await _row_hashes(w.company_id) == before
        assert await _leave_days(w, approved.json()["data"]["id"]) == [
            ("2026-09-08", "1.00", None, False)
        ]
    finally:
        await _finish(w)


# ---------------------------------------------------------------------------
# Policy B - no automatic substitute holiday
# ---------------------------------------------------------------------------


async def test_holiday_on_weekly_off_creates_no_substitute_but_an_exception_can(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client)
    try:
        calendar_id = w.calendar["id"]
        before = await _days(client, w, calendar_id, "2026-09-01", "2026-09-30")

        sunday_holiday = _holiday(w, "2026-09-13", name="Festival", holiday_type="COMPANY")
        data = await _preview_ok(client, w, sunday_holiday)
        assert [r["date"] for r in data["rows"]] == ["2026-09-13"]  # nothing else moves
        assert data["rows"][0]["proposed"]["day_type"] == "WEEKLY_OFF"
        assert "HOLIDAY_ON_WEEKLY_OFF" in {x["code"] for x in data["warnings"]}
        ok = await _confirm(client, w, sunday_holiday, data["impact_digest"])
        assert ok.status_code == 201, ok.text

        after = await _days(client, w, calendar_id, "2026-09-01", "2026-09-30")
        changed = {d for d in after if after[d] != before[d]}
        assert changed == {"2026-09-13"}  # no substitute date appeared
        assert after["2026-09-13"]["holiday_on_weekly_off"] is True
        assert after["2026-09-14"]["day_type"] == "WORKING"

        # HR creates the substitute explicitly; the preview shows it and the original day stays.
        substitute = {
            "change_type": "EXCEPTION_CREATE",
            "work_calendar_id": calendar_id,
            "body": {
                "exception_date": "2026-09-14",
                "exception_type": "SUBSTITUTE_HOLIDAY",
                "name": "Festival (substitute)",
            },
        }
        data = await _preview_ok(client, w, substitute)
        assert [
            (r["date"], r["previous"]["day_type"], r["proposed"]["day_type"]) for r in data["rows"]
        ] == [("2026-09-14", "WORKING", "HOLIDAY")]
        ok = await _confirm(client, w, substitute, data["impact_digest"])
        assert ok.status_code == 201, ok.text
        final = await _days(client, w, calendar_id, "2026-09-01", "2026-09-30")
        assert final["2026-09-14"]["day_type"] == "HOLIDAY"
        assert final["2026-09-14"]["exception_type"] == "SUBSTITUTE_HOLIDAY"
        assert final["2026-09-13"]["day_type"] == "WEEKLY_OFF"  # the original is untouched
    finally:
        await _finish(w)


async def test_exception_overrides_an_overlapping_holiday_and_is_calendar_specific(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client)
    try:
        holiday = await _create_holiday(
            client, w.admin, w.holidays["id"], date="2026-09-16", name="X"
        )
        assert holiday["is_working"] is False
        other_calendar = await _create_work_calendar(client, w.admin, name="Plant B")
        await _assign(
            client,
            w.admin,
            policy_kind="WORK_CALENDAR",
            policy_id=other_calendar["id"],
            scope_type="EMPLOYEE",
            scope_id=str(w.other_employee["id"]),
            effective_from="2026-01-01",
        )
        shutdown = await client.post(
            f"/v1/work-calendars/{w.calendar['id']}/exceptions",
            headers=w.admin,
            json={"exception_date": "2026-09-16", "exception_type": "SHUTDOWN", "name": "Plant"},
        )
        assert shutdown.status_code == 201, shutdown.text
        mine = await _resolved(client, w, w.employee_id, "2026-09-16")
        assert mine["day_type"] == "SHUTDOWN"  # exception beats the holiday on the same date
        other = await _resolved(client, w, str(w.other_employee["id"]), "2026-09-16")
        assert other["day_type"] == "WORKING"  # the other calendar has neither
    finally:
        await _finish(w)


# ---------------------------------------------------------------------------
# Policy C - Holiday.is_working
# ---------------------------------------------------------------------------


async def test_is_working_mirrors_the_type_in_the_api_and_resolution(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client)
    try:
        hid = w.holidays["id"]
        # PUBLIC with is_working=true contradicts the type: refused with a clear code.
        bad = await client.post(
            f"/v1/holiday-calendars/{hid}/holidays",
            headers=w.admin,
            json={"date": "2026-09-09", "name": "Bad", "is_working": True},
        )
        assert bad.status_code == 422, bad.text
        assert bad.json()["error"]["details"][0]["code"] == "HOLIDAY_IS_WORKING_CONFLICT"

        # WORKING_HOLIDAY without the flag stores the implied value; the day stays working.
        working = await _create_holiday(
            client, w.admin, hid, date="2026-09-09", name="Shift", holiday_type="WORKING_HOLIDAY"
        )
        assert working["is_working"] is True
        resolved = await _resolved(client, w, w.employee_id, "2026-09-09")
        assert (resolved["day_type"], resolved["holiday_name"]) == ("WORKING", "Shift")

        # An explicit contradictory flag is refused.
        contradiction = await client.post(
            f"/v1/holiday-calendars/{hid}/holidays",
            headers=w.admin,
            json={
                "date": "2026-09-10",
                "name": "C",
                "holiday_type": "WORKING_HOLIDAY",
                "is_working": False,
            },
        )
        assert contradiction.status_code == 422

        # Changing the type re-derives the flag; stating a contradictory flag is refused.
        hdr = {**w.admin, "If-Match": str(working["version"])}
        refused = await client.patch(
            f"/v1/holidays/{working['id']}",
            headers=hdr,
            json={"holiday_type": "PUBLIC", "is_working": True},
        )
        assert refused.status_code == 422, refused.text
        changed = await client.patch(
            f"/v1/holidays/{working['id']}", headers=hdr, json={"holiday_type": "PUBLIC"}
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["data"]["is_working"] is False
        assert (await _resolved(client, w, w.employee_id, "2026-09-09"))["day_type"] == "HOLIDAY"
        # A rename leaves the flag alone.
        renamed = await client.patch(
            f"/v1/holidays/{working['id']}",
            headers={**w.admin, "If-Match": str(changed.json()["data"]["version"])},
            json={"name": "Renamed"},
        )
        assert renamed.json()["data"]["is_working"] is False

        # Preview applies the same rule as the confirmed path, and yields the same classification.
        preview_bad = await _preview(
            client,
            w,
            _holiday(w, "2026-09-11", name="P", is_working=True),
        )
        assert preview_bad.status_code == 422
        change = _holiday(w, "2026-09-11", name="Shift2", holiday_type="WORKING_HOLIDAY")
        data = await _preview_ok(client, w, change)
        assert [r["proposed"]["day_type"] for r in data["rows"]] == ["WORKING"] or data[
            "rows"
        ] == []
        assert "HOLIDAY_IS_WORKING_IGNORED" not in {x["code"] for x in data["warnings"]}
        ok = await _confirm(client, w, change, data["impact_digest"])
        assert ok.status_code == 201, ok.text
        assert (await _resolved(client, w, w.employee_id, "2026-09-11"))["day_type"] == "WORKING"
    finally:
        await _finish(w)


# ---------------------------------------------------------------------------
# Policy D - holiday-calendar validity
# ---------------------------------------------------------------------------


async def _patch_validity(client: AsyncClient, w: World, calendar: dict[str, Any], **window: Any):
    response = await client.patch(
        f"/v1/holiday-calendars/{calendar['id']}",
        headers={**w.admin, "If-Match": str(calendar["version"])},
        json=window,
    )
    assert response.status_code == 200, response.text
    return dict(response.json()["data"])


async def test_validity_window_is_applied_by_every_resolution_path(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client)
    try:
        hid = w.holidays["id"]
        for day in ("2026-09-07", "2026-09-08", "2026-09-10", "2026-09-12", "2026-09-14"):
            await _create_holiday(client, w.admin, hid, date=day, name=f"H{day[-2:]}")
        await _patch_validity(client, w, w.holidays, valid_from="2026-09-08", valid_to="2026-09-12")

        calendar_id = w.calendar["id"]
        days = await _days(client, w, calendar_id, "2026-09-01", "2026-09-30")
        expected = {
            "2026-09-07": "WORKING",  # the day before validity starts
            "2026-09-08": "HOLIDAY",  # first valid date (inclusive)
            "2026-09-10": "HOLIDAY",
            "2026-09-12": "HOLIDAY",  # last valid date (inclusive)
            "2026-09-14": "WORKING",  # the day after validity ends
        }
        assert {d: _day_type(days[d]) for d in expected} == expected

        # Single-date, employee-resolution and employee self-service paths agree with the range.
        me = await _user_with_default_role(w.company_id, "EMPLOYEE", UUID(w.employee_id))
        mine = await client.get(
            "/v1/employee-calendar/me",
            headers=me,
            params={"from": "2026-09-01", "to": "2026-09-30"},
        )
        assert mine.status_code == 200, mine.text
        mine_by_date = {d["date"]: d["day_type"] for d in mine.json()["data"]["days"]}
        for day, kind in expected.items():
            single = await client.get(
                f"/v1/work-calendars/{calendar_id}/day-type",
                headers=w.admin,
                params={"date": day},
            )
            assert single.json()["data"]["day_type"] == kind, day
            assert (await _resolved(client, w, w.employee_id, day))["day_type"] == kind, day
            assert mine_by_date[day] == kind, day

        # Open-ended: clearing valid_to makes the later holiday apply again.
        calendar_now = (await client.get(f"/v1/holiday-calendars/{hid}", headers=w.admin)).json()[
            "data"
        ]
        await _patch_validity(client, w, calendar_now, valid_to=None)
        assert (
            _day_type(
                (await _days(client, w, calendar_id, "2026-09-14", "2026-09-14"))["2026-09-14"]
            )
            == "HOLIDAY"
        )

        # Inverted windows are refused on write.
        bad = await client.patch(
            f"/v1/holiday-calendars/{hid}",
            headers={**w.admin, "If-Match": "99"},
            json={"valid_from": "2026-10-01", "valid_to": "2026-09-01"},
        )
        assert bad.status_code in (409, 422)
        invalid_create = await client.post(
            "/v1/holiday-calendars",
            headers=w.admin,
            json={"name": "Bad", "valid_from": "2026-10-01", "valid_to": "2026-09-01"},
        )
        assert invalid_create.status_code == 422
    finally:
        await _finish(w)


async def test_preview_and_confirmed_resolution_agree_for_a_validity_change(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client)
    try:
        hid = w.holidays["id"]
        for day in ("2026-09-07", "2026-09-09", "2026-09-14"):
            await _create_holiday(client, w.admin, hid, date=day, name=f"H{day[-2:]}")
        calendar = await _patch_validity(
            client, w, w.holidays, valid_from="2026-09-08", valid_to="2026-09-12"
        )
        calendar_id = w.calendar["id"]
        before = await _days(client, w, calendar_id, "2026-09-01", "2026-09-30")
        hashes_before = await _row_hashes(w.company_id)

        change = {
            "change_type": "HOLIDAY_CALENDAR_UPDATE",
            "holiday_calendar_id": hid,
            "expected_version": calendar["version"],
            "patch": {"valid_from": "2026-09-01", "valid_to": "2026-09-30"},
        }
        data = await _preview_ok(client, w, change)
        assert await _row_hashes(w.company_id) == hashes_before  # preview writes nothing
        moved = {r["date"]: r for r in data["rows"]}
        assert set(moved) == {"2026-09-07", "2026-09-14"}  # the two holidays the window now admits
        for day, row in moved.items():
            assert row["previous"]["day_type"] == _day_type(before[day])  # previous == live state
            assert row["proposed"]["day_type"] == "HOLIDAY"

        ok = await _confirm(client, w, change, data["impact_digest"])
        assert ok.status_code == 201, ok.text
        after = await _days(client, w, calendar_id, "2026-09-01", "2026-09-30")
        for day, row in moved.items():
            assert _day_type(after[day]) == row["proposed"]["day_type"]  # actual == proposed
        untouched = set(after) - set(moved)
        assert all(after[d] == before[d] for d in untouched)

        # Same request again is stale (the version moved) - and a stale preview is not applied.
        stale = await _confirm(client, w, change, data["impact_digest"])
        assert stale.status_code in (409, 422), stale.text
    finally:
        await _finish(w)


async def test_link_change_preview_respects_the_linked_calendars_validity(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client)
    try:
        expired = await _create_holiday_calendar(
            client, w.admin, name="Expired", valid_from="2025-01-01", valid_to="2025-12-31"
        )
        await _create_holiday(client, w.admin, expired["id"], date="2026-09-16", name="Old")
        current = await _create_holiday_calendar(client, w.admin, name="Current")
        await _create_holiday(client, w.admin, current["id"], date="2026-09-17", name="New")

        def link(*ids: str) -> dict[str, Any]:
            return {
                "change_type": "WORK_CALENDAR_UPDATE",
                "work_calendar_id": w.calendar["id"],
                "expected_version": w.calendar["version"],
                "patch": {"holiday_calendar_ids": [w.holidays["id"], *ids]},
            }

        only_expired = await _preview_ok(client, w, link(expired["id"]))
        assert only_expired["rows"] == []  # linking an expired calendar changes nothing
        assert "NO_EFFECTIVE_CHANGE" in {x["code"] for x in only_expired["warnings"]}
        both = await _preview_ok(client, w, link(expired["id"], current["id"]))
        assert [r["date"] for r in both["rows"]] == ["2026-09-17"]
        ok = await _confirm(client, w, link(expired["id"], current["id"]), both["impact_digest"])
        assert ok.status_code == 201, ok.text
        days = await _days(client, w, w.calendar["id"], "2026-09-15", "2026-09-18")
        assert (
            _day_type(days["2026-09-16"]) == "WORKING"
            and _day_type(days["2026-09-17"]) == "HOLIDAY"
        )
    finally:
        await _finish(w)


async def test_validity_follows_the_employee_specific_calendar(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client)
    try:
        own_holidays = await _create_holiday_calendar(
            client, w.admin, name="Own", valid_from="2026-09-20", valid_to="2026-09-25"
        )
        await _create_holiday(client, w.admin, own_holidays["id"], date="2026-09-19", name="Before")
        await _create_holiday(client, w.admin, own_holidays["id"], date="2026-09-21", name="Inside")
        own = await _create_work_calendar(
            client, w.admin, name="Own calendar", holiday_calendar_ids=[own_holidays["id"]]
        )
        await _assign(
            client,
            w.admin,
            policy_kind="WORK_CALENDAR",
            policy_id=own["id"],
            scope_type="EMPLOYEE",
            scope_id=w.employee_id,
            effective_from="2026-01-01",
        )
        assert (await _resolved(client, w, w.employee_id, "2026-09-19"))["day_type"] == "WORKING"
        assert (await _resolved(client, w, w.employee_id, "2026-09-21"))["day_type"] == "HOLIDAY"
        # The colleague stays on the company calendar and sees none of it.
        assert (await _resolved(client, w, str(w.other_employee["id"]), "2026-09-21"))[
            "day_type"
        ] == "WORKING"
    finally:
        await _finish(w)


# ---------------------------------------------------------------------------
# Policy E - protected periods
# ---------------------------------------------------------------------------


async def _close_period(w: World) -> None:
    from hrms.modules.attendance.models import AttendancePeriod

    now = datetime.now(UTC)
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(w.company_id))
        session.add(
            AttendancePeriod(
                id=uuid4(),
                company_id=w.company_id,
                legal_entity_id=UUID(w.ctx["legal_entity"]["id"]),
                period_start=date(2026, 9, 1),
                period_end=date(2026, 9, 30),
                status="CLOSED",
                opened_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()


async def test_a_period_closed_after_preview_makes_the_preview_stale(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client)
    try:
        change = _holiday(w, "2026-09-09")
        data = await _preview_ok(client, w, change)
        assert data["protected_periods"] == [] and data["requires_acknowledgement"] is False
        await _close_period(w)  # protected state changes between preview and confirm
        before = await _row_hashes(w.company_id)
        stale = await _confirm(client, w, change, data["impact_digest"])
        assert stale.status_code == 409, stale.text
        assert stale.json()["error"]["code"] == "CALENDAR_PREVIEW_STALE"
        assert await _row_hashes(w.company_id) == before
        # A fresh preview now lists the period and demands acknowledgement.
        fresh = await _preview_ok(client, w, change)
        assert fresh["requires_acknowledgement"] is True
        assert {p["kind"] for p in fresh["protected_periods"]} == {"ATTENDANCE_PERIOD"}
        assert all(p["changed_dates_in_period"] == 1 for p in fresh["protected_periods"])
        refused = await _confirm(client, w, change, fresh["impact_digest"])
        assert refused.status_code == 422
        ok = await _confirm(client, w, change, fresh["impact_digest"], ack=True)
        assert ok.status_code == 201, ok.text
        assert await _row_hashes(w.company_id) == before
    finally:
        await _finish(w)


async def test_acknowledgement_does_not_bypass_permission_or_tenant_checks(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client)
    other = await _world(client)
    try:
        await _close_period(w)
        change = _holiday(w, "2026-09-09")
        data = await _preview_ok(client, w, change)
        assert data["requires_acknowledgement"] is True

        employee = await _user_with_default_role(w.company_id, "EMPLOYEE", UUID(w.employee_id))
        for url, body in (
            (PREVIEW, {"change": change, **SEPTEMBER}),
            (
                CONFIRM,
                {
                    "change": change,
                    "impact_digest": data["impact_digest"],
                    "acknowledge_protected_impact": True,
                    **SEPTEMBER,
                },
            ),
        ):
            denied = await client.post(url, headers=employee, json=body)
            assert denied.status_code == 403, (url, denied.text)

        # Another tenant's holiday calendar cannot be targeted, acknowledged or not.
        foreign = {
            "change_type": "HOLIDAY_CREATE",
            "holiday_calendar_id": other.holidays["id"],
            "body": {"date": "2026-09-09", "name": "X"},
        }
        cross = await client.post(
            CONFIRM,
            headers=w.admin,
            json={
                "change": foreign,
                "impact_digest": "0" * 64,
                "acknowledge_protected_impact": True,
                **SEPTEMBER,
            },
        )
        assert cross.status_code == 404, cross.text
        assert await _audit_count(w.company_id, "WORK_CALENDAR_CHANGE_CONFIRMED") == 0
    finally:
        await _finish(w)  # owns the scoped employee user, so it goes first
        await _finish(other)


async def test_confirmation_audit_names_actor_tenant_and_change_without_leave_details(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client)
    try:
        leave = await _apply(
            client, w, start_date="2026-09-09", end_date="2026-09-09", reason="private"
        )
        assert leave.status_code == 201
        change = _holiday(w, "2026-09-09")
        data = await _preview_ok(client, w, change)
        ok = await _confirm(client, w, change, data["impact_digest"], ack=True)
        assert ok.status_code == 201, ok.text
        rows = await _sql(
            w.company_id,
            "SELECT actor_user_id, company_id, entity_type, entity_id, after_json::text "
            "FROM audit_log WHERE action = 'WORK_CALENDAR_CHANGE_CONFIRMED' "
            "AND company_id = CAST(:c AS uuid)",
            c=str(w.company_id),
        )
        assert len(rows) == 1
        actor, company, entity_type, entity_id, after = rows[0]
        assert str(company) == str(w.company_id) and str(actor) == str(w.user_id)
        assert entity_type == "work_calendar_change" and entity_id is not None
        assert data["impact_digest"] in after and '"acknowledged_protected_impact": true' in after
        assert "private" not in after  # no leave reason or other sensitive text
    finally:
        await _finish(w)


# ---------------------------------------------------------------------------
# Policy F - deactivation blocked while assignments depend on the calendar
# ---------------------------------------------------------------------------


async def _fresh_calendar(client: AsyncClient, w: World, name: str) -> dict[str, Any]:
    return await _create_work_calendar(client, w.admin, name=name)


async def _deactivate(
    client: AsyncClient, w: World, kind: str, row: dict[str, Any], *, patch: bool
):
    path = f"/v1/{kind}/{row['id']}"
    headers = {**w.admin, "If-Match": str(row["version"])}
    if patch:
        return await client.patch(path, headers=headers, json={"is_active": False})
    return await client.delete(path, headers=headers)


async def _assign_employee(
    client: AsyncClient, w: World, calendar_id: str, *, start: str, end: str | None = None
) -> Any:
    body: dict[str, Any] = {
        "policy_kind": "WORK_CALENDAR",
        "policy_id": calendar_id,
        "scope_type": "EMPLOYEE",
        "scope_id": str(w.other_employee["id"]),
        "effective_from": start,
    }
    if end is not None:
        body["effective_to"] = end
    return await client.post("/v1/policy-assignments", headers=w.admin, json=body)


async def _clear_employee_assignments(w: World) -> None:
    """One (kind, scope) slot holds one open assignment chain; free it between sub-cases."""
    await _sql(
        w.company_id,
        "DELETE FROM policy_assignment WHERE company_id = CAST(:c AS uuid) "
        "AND scope_type = 'EMPLOYEE' AND policy_kind = 'WORK_CALENDAR'",
        c=str(w.company_id),
    )


async def _company_today(w: World) -> date:
    rows = await _sql(
        w.company_id,
        "SELECT timezone FROM company WHERE id = CAST(:c AS uuid)",
        c=str(w.company_id),
    )
    return business_today(rows[0][0])


async def test_unassigned_calendar_can_be_deactivated(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client)
    try:
        for patch in (False, True):
            row = await _fresh_calendar(client, w, f"Spare {patch}")
            done = await _deactivate(client, w, "work-calendars", row, patch=patch)
            assert done.status_code == 200, done.text
            assert done.json()["data"]["is_active"] is False
    finally:
        await _finish(w)


async def test_currently_effective_assignment_blocks_both_routes_with_actionable_detail(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client)
    try:
        for patch in (False, True):  # DELETE and the `PATCH is_active=false` route
            current = (
                await client.get(f"/v1/work-calendars/{w.calendar['id']}", headers=w.admin)
            ).json()["data"]
            blocked = await _deactivate(client, w, "work-calendars", current, patch=patch)
            assert blocked.status_code == 409, blocked.text
            detail = blocked.json()["error"]["details"][0]
            assert detail["code"] == "WORK_CALENDAR_HAS_ACTIVE_ASSIGNMENTS"
            context = detail["context"]
            assert context["active_assignment_count"] == 1
            assert context["assignments"][0]["scope_type"] == "COMPANY"
            assert "Reassign" in context["next_action"]
        still = (await client.get(f"/v1/work-calendars/{w.calendar['id']}", headers=w.admin)).json()
        assert still["data"]["is_active"] is True
        # The same guard holds when the deactivation arrives through the confirmed-change path.
        change = {
            "change_type": "WORK_CALENDAR_UPDATE",
            "work_calendar_id": w.calendar["id"],
            "expected_version": still["data"]["version"],
            "patch": {"is_active": False},
        }
        data = await _preview_ok(client, w, change)
        refused = await _confirm(client, w, change, data["impact_digest"], ack=True)
        assert refused.status_code == 409, refused.text
        assert await _audit_count(w.company_id, "WORK_CALENDAR_CHANGE_CONFIRMED") == 0
        assert await _audit_count(w.company_id, "WORK_CALENDAR_DEACTIVATED") == 0
    finally:
        await _finish(w)


async def test_future_dated_expired_and_boundary_assignments(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client)
    try:
        today = await _company_today(w)
        iso = lambda d: d.isoformat()  # noqa: E731

        future = await _fresh_calendar(client, w, "Future")
        assert (
            await _assign_employee(client, w, future["id"], start=iso(today + timedelta(days=30)))
        ).status_code == 201
        blocked = await _deactivate(client, w, "work-calendars", future, patch=False)
        assert blocked.status_code == 409  # future-dated assignments still depend on it

        await _clear_employee_assignments(w)
        expired = await _fresh_calendar(client, w, "Expired")
        assert (
            await _assign_employee(
                client, w, expired["id"], start="2024-01-01", end=iso(today - timedelta(days=1))
            )
        ).status_code == 201
        assert (
            await _deactivate(client, w, "work-calendars", expired, patch=False)
        ).status_code == 200

        await _clear_employee_assignments(w)
        ends_today = await _fresh_calendar(client, w, "EndsToday")
        assert (
            await _assign_employee(client, w, ends_today["id"], start="2024-01-01", end=iso(today))
        ).status_code == 201
        # Inclusive end date: the assignment is still effective today.
        assert (
            await _deactivate(client, w, "work-calendars", ends_today, patch=False)
        ).status_code == 409

        await _clear_employee_assignments(w)
        ends_tomorrow = await _fresh_calendar(client, w, "EndsTomorrow")
        assert (
            await _assign_employee(
                client,
                w,
                ends_tomorrow["id"],
                start="2024-01-01",
                end=iso(today + timedelta(days=1)),
            )
        ).status_code == 201
        assert (
            await _deactivate(client, w, "work-calendars", ends_tomorrow, patch=True)
        ).status_code == 409
    finally:
        await _finish(w)


async def test_weekly_off_pattern_deactivation_is_guarded_too(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client)
    try:
        default_pattern = (
            await client.get(
                f"/v1/weekly-off-patterns/{w.calendar['weekly_off_pattern_id']}", headers=w.admin
            )
        ).json()["data"]
        for patch in (False, True):
            blocked = await _deactivate(
                client, w, "weekly-off-patterns", default_pattern, patch=patch
            )
            assert blocked.status_code == 409, blocked.text
            detail = blocked.json()["error"]["details"][0]
            assert detail["code"] == "WEEKLY_OFF_PATTERN_HAS_ACTIVE_ASSIGNMENTS"
            assert detail["context"]["default_for_work_calendars"] >= 1

        assigned = await _create_weekly_off_pattern(client, w.admin, name="Assigned")
        await _assign(
            client,
            w.admin,
            policy_kind="WEEKLY_OFF",
            policy_id=assigned["id"],
            scope_type="EMPLOYEE",
            scope_id=w.employee_id,
            effective_from="2026-01-01",
        )
        blocked = await _deactivate(client, w, "weekly-off-patterns", assigned, patch=True)
        assert blocked.status_code == 409
        assert blocked.json()["error"]["details"][0]["context"]["active_assignment_count"] == 1

        spare = await _create_weekly_off_pattern(client, w.admin, name="Spare")
        done = await _deactivate(client, w, "weekly-off-patterns", spare, patch=False)
        assert done.status_code == 200 and done.json()["data"]["is_active"] is False
    finally:
        await _finish(w)


async def test_an_inactive_calendar_cannot_be_assigned(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client)
    try:
        spare = await _fresh_calendar(client, w, "Retired")
        assert (
            await _deactivate(client, w, "work-calendars", spare, patch=False)
        ).status_code == 200
        refused = await _assign_employee(client, w, spare["id"], start="2026-01-01")
        assert refused.status_code in (404, 422), refused.text
    finally:
        await _finish(w)


async def test_concurrent_assignment_and_deactivation_never_both_succeed(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client)
    try:
        outcomes = []
        for index in range(6):
            row = await _fresh_calendar(client, w, f"Race {index}")
            deactivate, assign = await asyncio.gather(
                _deactivate(client, w, "work-calendars", row, patch=bool(index % 2)),
                _assign_employee(client, w, row["id"], start="2026-01-01"),
            )
            outcomes.append((deactivate.status_code, assign.status_code))
            assert not (deactivate.status_code == 200 and assign.status_code == 201), outcomes
            stored = (await client.get(f"/v1/work-calendars/{row['id']}", headers=w.admin)).json()[
                "data"
            ]
            if assign.status_code == 201:
                assert stored["is_active"] is True and deactivate.status_code == 409
            else:
                assert deactivate.status_code == 200 and stored["is_active"] is False
            # Clean the assignment so the next round's employee-scope slot is free.
            await _sql(
                w.company_id,
                "DELETE FROM policy_assignment WHERE company_id = CAST(:c AS uuid) "
                "AND scope_type = 'EMPLOYEE' AND policy_id = CAST(:p AS uuid)",
                c=str(w.company_id),
                p=row["id"],
            )
        assert len({o for o in outcomes}) >= 1
    finally:
        await _finish(w)


async def test_dependency_check_is_tenant_scoped(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    a = await _world(client)
    b = await _world(client)
    try:
        calendar = await _fresh_calendar(client, a, "Mine")
        # Another tenant's assignment row that (impossibly) names this calendar id does not count.
        await _sql(
            b.company_id,
            "INSERT INTO policy_assignment (id, company_id, policy_kind, policy_id, scope_type, "
            "scope_id, effective_from, priority, is_active, version, created_at, updated_at) "
            "VALUES (gen_random_uuid(), CAST(:c AS uuid), 'WORK_CALENDAR', CAST(:p AS uuid), "
            "'EMPLOYEE', CAST(:e AS uuid), '2026-01-01', 0, true, 1, now(), now())",
            c=str(b.company_id),
            p=calendar["id"],
            e=b.employee_id,
        )
        done = await _deactivate(client, a, "work-calendars", calendar, patch=False)
        assert done.status_code == 200, done.text
        # ...and tenant B cannot touch tenant A's calendar at all.
        other = await _fresh_calendar(client, a, "Theirs")
        denied = await _deactivate(client, b, "work-calendars", other, patch=False)
        assert denied.status_code == 404, denied.text
    finally:
        await _sql(
            b.company_id,
            "DELETE FROM policy_assignment WHERE company_id = CAST(:c AS uuid) "
            "AND scope_type = 'EMPLOYEE'",
            c=str(b.company_id),
        )
        await _finish(b)
        await _finish(a)
