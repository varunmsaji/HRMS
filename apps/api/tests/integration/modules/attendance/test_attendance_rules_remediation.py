"""Attendance rules audit AR-01, AR-03, AR-04, AR-08, AR-09, AR-11 and LV-04, through the real
API (`docs/audits/ATTENDANCE_RULES_COMPREHENSIVE_AUDIT_2026-11-16.md`). Each test is the audit's
own reproduction, now asserting the corrected result."""

from __future__ import annotations

import asyncio
from typing import Any
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
from tests.integration.modules.attendance.test_attendance_security import (
    _cleanup_scoped_users,
    _create_permission_scoped_user,
)
from tests.integration.modules.attendance.test_overtime_record import (
    _cleanup_overtime,
    _create_overtime_policy,
)
from tests.integration.modules.attendance.test_regularization import (
    _cleanup_regularization,
    _create_regularization_policy,
)
from tests.integration.modules.attendance.test_shift_roster import _publish_roster
from tests.integration.modules.attendance.test_shift_window import _sql
from tests.integration.modules.organisation.test_registration_flow import _cleanup
from tests.integration.modules.organisation.test_workforce_calendar import (
    _cleanup_workforce_calendar,
)

from hrms.modules.attendance import recalc

pytestmark = pytest.mark.asyncio

MON, TUE, WED = "2026-08-10", "2026-08-11", "2026-08-12"


async def _calc(
    client: AsyncClient, headers: dict[str, str], employee_id: str, day: str
) -> dict[str, Any]:
    response = await client.post(
        "/v1/attendance/days/calculate",
        headers=headers,
        params={"employee_id": employee_id, "date": day},
    )
    assert response.status_code == 200, response.text
    return dict(response.json()["data"])


async def _stored(
    client: AsyncClient, headers: dict[str, str], employee_id: str, day: str
) -> dict[str, Any]:
    listed = await client.get(
        "/v1/attendance/days",
        headers=headers,
        params={"employee_id": employee_id, "date_from": day, "date_to": day},
    )
    assert listed.status_code == 200, listed.text
    return dict(listed.json()["data"][0])


async def _records(
    client: AsyncClient, headers: dict[str, str], employee_id: str, first: str, last: str
) -> dict[str, dict[str, Any]]:
    listed = await client.get(
        "/v1/overtime",
        headers=headers,
        params={"employee_id": employee_id, "date_from": first, "date_to": last},
    )
    assert listed.status_code == 200, listed.text
    return {r["attendance_date"]: dict(r) for r in listed.json()["data"]}


async def _approved(
    client: AsyncClient, headers: dict[str, str], employee_id: str
) -> dict[str, int]:
    records = await _records(client, headers, employee_id, MON, WED)
    return {day: r["minutes_approved"] for day, r in sorted(records.items())}


async def _work(
    client: AsyncClient, headers: dict[str, str], employee_id: str, day: str, out_hour: int = 19
) -> None:
    for hour, direction in ((9, "IN"), (out_hour, "OUT")):
        await _punch(
            client,
            headers,
            employee_id=employee_id,
            hour=hour,
            minute=0,
            direction=direction,
            day=day,
        )


async def _forget_calculations(company_id: UUID) -> None:
    """Punches stay; every calculated day and overtime record goes, so the order in which the
    days are calculated next is the test's own choice."""
    for table in ("overtime_action", "overtime_record", "attendance_break", "attendance_day"):
        await _sql(company_id, f"DELETE FROM {table} WHERE company_id = :cid")


async def _pending_reasons(company_id: UUID) -> list[str]:
    rows = await _sql(
        company_id,
        "SELECT reason FROM attendance_recalc_request "
        "WHERE company_id = :cid AND processed_at IS NULL",
    )
    return sorted(r[0] for r in rows)


async def _settle_queue(company_id: UUID) -> None:
    await _sql(
        company_id,
        "UPDATE attendance_recalc_request SET processed_at = now() WHERE company_id = :cid",
    )


async def _cleanup_all(company_id: Any, user_id: Any) -> None:
    await _cleanup_attendance_period(company_id=company_id)
    await _cleanup_regularization(company_id=company_id)
    await _cleanup_overtime(company_id=company_id)
    await _cleanup_workforce_calendar(company_id=company_id)
    await _cleanup_attendance_day(company_id=company_id)
    await _cleanup(company_id=company_id, user_id=user_id)
    await _cleanup_scoped_users()


# --- AR-01 / D-03 ------------------------------------------------------------------------------


async def test_roster_week_off_work_is_weekly_off_overtime_held_for_approval(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The audit's reproduction returned `ot_minutes_detected 0`, no record. Even under an AUTO
    chain the minutes wait for a person (D-03): nobody planned work on a rostered day off."""
    from hrms.modules.attendance.permissions import ATTENDANCE_OVERTIME_APPROVE

    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = (await _build_wired_employee(client, headers))["employee"]["id"]
        await _create_overtime_policy(client, headers, approval_chain="AUTO")
        await _publish_roster(
            client,
            headers,
            {"employee_id": employee_id, "roster_date": MON, "is_week_off_override": True},
        )
        await _work(client, headers, employee_id, MON, out_hour=18)
        day = await _calc(client, headers, employee_id, MON)

        assert day["attendance_status"] == "PRESENT" and day["paid_day_fraction"] == "1.00"
        assert day["shift_id"] is None
        assert day["ot_minutes_detected"] == 540
        assert day["ot_day_class"] == "WEEKLY_OFF"
        assert day["worked_on_weekly_off"] is True
        assert day["ot_minutes_approved"] == 0 and day["ot_pending"] is True
        record = (await _records(client, headers, employee_id, MON, MON))[MON]
        assert (record["status"], record["day_class"]) == ("PENDING", "WEEKLY_OFF")

        hr, _ = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[ATTENDANCE_OVERTIME_APPROVE],
            data_scope="COMPANY",
            caller_employee_id=None,
        )
        approved = await client.post(
            f"/v1/overtime/{record['id']}/approve",
            headers={**hr, "If-Match": str(record["version"])},
            json={},
        )
        assert approved.status_code == 200, approved.text
        after = await _stored(client, headers, employee_id, MON)
        assert after["ot_minutes_approved"] == 540 and after["ot_pending"] is False
        # A recalculation with the same punches leaves the human decision alone.
        again = await _calc(client, headers, employee_id, MON)
        assert again["ot_minutes_approved"] == 540
    finally:
        await _cleanup_all(company_id, user_id)


# --- AR-03 -------------------------------------------------------------------------------------


async def test_overtime_rejected_at_lock_returns_when_the_reopened_day_is_corrected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Close -> system rejection -> reopen -> correction. Before: PRESENT, 60 detected, 0
    approved, record REJECTED for good, and validation said READY."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = (await _build_wired_employee(client, headers))["employee"]["id"]
        await _create_overtime_policy(client, headers, approval_chain="AUTO")
        await _create_regularization_policy(client, headers, approval_chain="AUTO")
        for hour, minute, direction in ((7, 30, "IN"), (9, 0, "IN"), (19, 0, "OUT")):
            await _punch(
                client,
                headers,
                employee_id=employee_id,
                hour=hour,
                minute=minute,
                direction=direction,
                day=MON,
            )
        held = await _calc(client, headers, employee_id, MON)
        assert held["attendance_status"] == "INCOMPLETE"
        assert (held["ot_minutes_approved"], held["ot_pending"]) == (0, True)

        period = await _create_period(client, headers)
        closed = await client.post(
            f"/v1/attendance-periods/{period['id']}/finalize",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert closed.status_code == 200, closed.text
        locked = await _stored(client, headers, employee_id, MON)
        assert (locked["lop_fraction"], locked["ot_minutes_approved"]) == ("1.00", 0)
        assert (await _records(client, headers, employee_id, MON, MON))[MON]["status"] == "REJECTED"

        reopened = await client.post(
            f"/v1/attendance-periods/{period['id']}/reopen",
            headers={**headers, "If-Match": str(closed.json()["data"]["version"])},
            json={"reason": "employee disputes the absent day"},
        )
        assert reopened.status_code == 200, reopened.text

        # Still incomplete after the reopen: recalculating holds it again, it does not pay it.
        still = await _calc(client, headers, employee_id, MON)
        assert still["attendance_status"] == "INCOMPLETE"
        assert (still["ot_minutes_approved"], still["ot_pending"]) == (0, True)
        assert (await _records(client, headers, employee_id, MON, MON))[MON]["status"] == "PENDING"

        corrected = await client.post(
            "/v1/regularizations",
            headers=headers,
            json={
                "employee_id": employee_id,
                "attendance_date": MON,
                "request_type": "MISSING_PUNCH",
                "reason": "stray check-in closed",
                "requested_punches": [{"direction": "OUT", "requested_time": f"{MON}T07:31:00Z"}],
            },
        )
        assert corrected.status_code == 201, corrected.text
        day = await _stored(client, headers, employee_id, MON)
        assert day["attendance_status"] == "PRESENT" and day["paid_day_fraction"] == "1.00"
        assert (day["ot_minutes_detected"], day["ot_minutes_approved"]) == (60, 60)
        record = (await _records(client, headers, employee_id, MON, MON))[MON]
        assert (record["status"], record["minutes_approved"]) == ("AUTO_APPROVED", 60)
        # The lock's rejection stays on the record's timeline; nothing was overwritten.
        actions = [a["action"] for a in record["actions"]]
        assert "REJECTED" in actions and "SUPERSEDED_BY_RECALCULATION" in actions

        validated = await client.post(
            f"/v1/attendance-periods/{period['id']}/validate", headers=headers
        )
        assert validated.json()["data"]["status"] == "READY", validated.text
    finally:
        await _cleanup_all(company_id, user_id)


async def test_a_human_rejection_is_still_not_reversed_by_a_recalculation(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """AR-03 must not weaken P-C: only the lock's own rejection is re-derived."""
    from hrms.modules.attendance.permissions import ATTENDANCE_OVERTIME_APPROVE

    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = (await _build_wired_employee(client, headers))["employee"]["id"]
        await _create_overtime_policy(client, headers, approval_chain="HR")
        await _work(client, headers, employee_id, MON)
        await _calc(client, headers, employee_id, MON)
        record = (await _records(client, headers, employee_id, MON, MON))[MON]
        hr, _ = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[ATTENDANCE_OVERTIME_APPROVE],
            data_scope="COMPANY",
            caller_employee_id=None,
        )
        rejected = await client.post(
            f"/v1/overtime/{record['id']}/reject",
            headers={**hr, "If-Match": str(record["version"])},
            json={"rejection_reason": "not authorised"},
        )
        assert rejected.status_code == 200, rejected.text
        for _ in range(2):
            day = await _calc(client, headers, employee_id, MON)
            assert day["ot_minutes_approved"] == 0 and day["ot_pending"] is False
        assert (await _records(client, headers, employee_id, MON, MON))[MON]["status"] == "REJECTED"
    finally:
        await _cleanup_all(company_id, user_id)


# --- AR-04 / D-04 ------------------------------------------------------------------------------


async def _capped_employee(client: AsyncClient, headers: dict[str, str]) -> str:
    """Weekly cap 90; 60 minutes of overtime on Monday, Tuesday and Wednesday."""
    employee_id = str((await _build_wired_employee(client, headers))["employee"]["id"])
    await _create_overtime_policy(client, headers, approval_chain="AUTO", weekly_cap_minutes=90)
    await _create_regularization_policy(client, headers, approval_chain="AUTO")
    for day in (MON, TUE, WED):
        await _work(client, headers, employee_id, day)
    return employee_id


@pytest.mark.parametrize(
    "order", [(MON, TUE, WED), (WED, TUE, MON), (TUE, WED, MON), (WED, MON, TUE)]
)
async def test_weekly_cap_goes_to_the_earliest_days_whatever_order_they_are_calculated_in(
    client: AsyncClient, seeded_plan_catalogue: None, order: tuple[str, ...]
) -> None:
    """Before: Tuesday-then-Monday gave Monday 30 / Tuesday 60, Monday-then-Tuesday the reverse."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = await _capped_employee(client, headers)
        await _forget_calculations(company_id)
        for day in order:
            await _calc(client, headers, employee_id, day)
        expected = {MON: 60, TUE: 30}
        got = await _approved(client, headers, employee_id)
        assert {d: m for d, m in got.items() if m} == expected
        assert (await _stored(client, headers, employee_id, WED))["ot_minutes_approved"] == 0
        # Repeating any day changes nothing.
        for day in reversed(order):
            await _calc(client, headers, employee_id, day)
        assert {
            d: m for d, m in (await _approved(client, headers, employee_id)).items() if m
        } == expected
    finally:
        await _cleanup_all(company_id, user_id)


async def test_correcting_an_earlier_day_recalculates_the_later_days_of_the_week(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Before: Monday corrected to no overtime left Tuesday at 30 until someone recomputed it."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = await _capped_employee(client, headers)
        for day in (MON, TUE, WED):
            await _calc(client, headers, employee_id, day)
        assert (await _stored(client, headers, employee_id, TUE))["ot_minutes_approved"] == 30

        corrected = await client.post(
            "/v1/regularizations",
            headers=headers,
            json={
                "employee_id": employee_id,
                "attendance_date": MON,
                "request_type": "WRONG_PUNCH",
                "reason": "Wrong OUT time",
                "requested_punches": [{"direction": "OUT", "requested_time": f"{MON}T18:00:00Z"}],
            },
        )
        assert corrected.status_code == 201, corrected.text
        # No explicit recompute of Tuesday or Wednesday: the correction itself did it.
        assert (await _stored(client, headers, employee_id, MON))["ot_minutes_approved"] == 0
        assert (await _stored(client, headers, employee_id, TUE))["ot_minutes_approved"] == 60
        assert (await _stored(client, headers, employee_id, WED))["ot_minutes_approved"] == 30
        records = await _records(client, headers, employee_id, MON, WED)
        assert {d: r["minutes_approved"] for d, r in records.items()} == {TUE: 60, WED: 30}
    finally:
        await _cleanup_all(company_id, user_id)


async def test_a_locked_later_day_is_not_touched_by_an_earlier_correction(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = await _capped_employee(client, headers)
        for day in (MON, TUE, WED):
            await _calc(client, headers, employee_id, day)
        await _sql(
            company_id,
            f"UPDATE attendance_day SET is_locked = true "
            f"WHERE company_id = :cid AND attendance_date = '{TUE}'",
        )
        corrected = await client.post(
            "/v1/regularizations",
            headers=headers,
            json={
                "employee_id": employee_id,
                "attendance_date": MON,
                "request_type": "WRONG_PUNCH",
                "reason": "Wrong OUT time",
                "requested_punches": [{"direction": "OUT", "requested_time": f"{MON}T18:00:00Z"}],
            },
        )
        assert corrected.status_code == 201, corrected.text
        assert (await _stored(client, headers, employee_id, MON))["ot_minutes_approved"] == 0
        # Tuesday is locked: final. Wednesday is open and gets what is left after Tuesday's 30.
        assert (await _stored(client, headers, employee_id, TUE))["ot_minutes_approved"] == 30
        assert (await _stored(client, headers, employee_id, WED))["ot_minutes_approved"] == 60
    finally:
        await _sql(
            company_id, "UPDATE attendance_day SET is_locked = false WHERE company_id = :cid"
        )
        await _cleanup_all(company_id, user_id)


async def test_concurrent_calculation_of_days_sharing_a_cap_ends_in_the_same_allocation(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Three days of one week calculated at once. A request that loses a row-lock race may fail
    cleanly (it never writes half a result); the days are then calculated once more, as the
    queue and the sweep do, and the allocation is the chronological one."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = await _capped_employee(client, headers)
        await _forget_calculations(company_id)
        responses = await asyncio.gather(
            *(
                client.post(
                    "/v1/attendance/days/calculate",
                    headers=headers,
                    params={"employee_id": employee_id, "date": day},
                )
                for day in (WED, TUE, MON)
            )
        )
        assert all(r.status_code in (200, 409, 423, 503) for r in responses), [
            r.text for r in responses
        ]
        for day in (MON, TUE, WED):
            await _calc(client, headers, employee_id, day)
        got = await _approved(client, headers, employee_id)
        assert {d: m for d, m in got.items() if m} == {MON: 60, TUE: 30}
        rows = await _sql(
            company_id,
            "SELECT count(*), count(DISTINCT attendance_date) FROM overtime_record "
            "WHERE company_id = :cid",
        )
        assert rows[0][0] == rows[0][1]  # never two records for one day
    finally:
        await _cleanup_all(company_id, user_id)


# --- AR-11 -------------------------------------------------------------------------------------


async def test_auto_close_policy_does_not_auto_approve_overtime_beside_an_orphan_punch(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`missing_punch_behaviour = AUTO_CLOSE` leaves the day PRESENT; its overtime was
    auto-approved although a punch was unexplained (the AC-04 hold did not apply)."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = (await _build_wired_employee(client, headers))["employee"]["id"]
        await _create_overtime_policy(client, headers, approval_chain="AUTO")
        await _sql(
            company_id,
            "UPDATE attendance_policy_version SET missing_punch_behaviour = 'AUTO_CLOSE' "
            "WHERE company_id = :cid",
        )
        for hour, minute, direction in ((7, 30, "IN"), (9, 0, "IN"), (19, 0, "OUT")):
            await _punch(
                client,
                headers,
                employee_id=employee_id,
                hour=hour,
                minute=minute,
                direction=direction,
                day=MON,
            )
        day = await _calc(client, headers, employee_id, MON)
        assert day["attendance_status"] == "PRESENT" and day["missing_punch"] is True
        assert day["ot_minutes_detected"] == 60
        assert (day["ot_minutes_approved"], day["ot_pending"]) == (0, True)
        assert (await _records(client, headers, employee_id, MON, MON))[MON]["status"] == "PENDING"
    finally:
        await _cleanup_all(company_id, user_id)


# --- AR-08 / AR-09 -----------------------------------------------------------------------------


async def test_removing_a_work_calendars_weekly_off_pattern_recalculates_its_days(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    sunday = "2026-08-09"
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = (await _build_wired_employee(client, headers))["employee"]["id"]
        pattern = await client.post(
            "/v1/weekly-off-patterns",
            headers=headers,
            json={
                "name": "Sundays",
                "pattern_kind": "FIXED_WEEKDAYS",
                "rules": [{"weekday": 6, "off_fraction": "1.00"}],
            },
        )
        assert pattern.status_code == 201, pattern.text
        calendar = (await client.get("/v1/work-calendars", headers=headers)).json()["data"][0]
        linked = await client.patch(
            f"/v1/work-calendars/{calendar['id']}",
            headers={**headers, "If-Match": str(calendar["version"])},
            json={"weekly_off_pattern_id": pattern.json()["data"]["id"]},
        )
        assert linked.status_code == 200, linked.text
        assert (await _calc(client, headers, employee_id, sunday))[
            "calendar_day_type"
        ] == "WEEKLY_OFF"
        await _settle_queue(company_id)

        cleared = await client.patch(
            f"/v1/work-calendars/{calendar['id']}",
            headers={**headers, "If-Match": str(linked.json()["data"]["version"])},
            json={"weekly_off_pattern_id": None},
        )
        assert cleared.status_code == 200, cleared.text
        assert await _pending_reasons(company_id) == ["WORK_CALENDAR_CHANGED"]  # was []
        await recalc.process_company_requests(company_id)
        stored = await _stored(client, headers, employee_id, sunday)
        assert stored["calendar_day_type"] == "WORKING"
        assert stored["attendance_status"] == "INCOMPLETE"

        # A patch that does not touch the pattern queues nothing.
        renamed = await client.patch(
            f"/v1/work-calendars/{calendar['id']}",
            headers={**headers, "If-Match": str(cleared.json()["data"]["version"])},
            json={"name": "Default (renamed)"},
        )
        assert renamed.status_code == 200, renamed.text
        assert await _pending_reasons(company_id) == []
    finally:
        await _cleanup_all(company_id, user_id)


async def test_a_backdated_termination_recalculates_the_days_after_the_last_working_day(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = (await _build_wired_employee(client, headers))["employee"]["id"]
        for day in (MON, TUE):
            assert (await _calc(client, headers, employee_id, day))[
                "attendance_status"
            ] == "INCOMPLETE"
        await _settle_queue(company_id)
        employment = (
            await client.get(f"/v1/employees/{employee_id}/employments", headers=headers)
        ).json()["data"][0]
        terminated = await client.post(
            f"/v1/employees/{employee_id}/employments/{employment['id']}/terminate",
            headers={**headers, "If-Match": str(employment["version"])},
            json={"last_working_day": MON},
        )
        assert terminated.status_code == 200, terminated.text
        assert "EMPLOYMENT_TERMINATED" in await _pending_reasons(company_id)  # was nothing
        await recalc.process_company_requests(company_id)
        assert (await _stored(client, headers, employee_id, MON))[
            "attendance_status"
        ] == "INCOMPLETE"
        after = await _stored(client, headers, employee_id, TUE)
        assert after["attendance_status"] == "EXITED"
        assert (after["paid_day_fraction"], after["lop_fraction"]) == ("0.00", "0.00")
    finally:
        await _cleanup_all(company_id, user_id)


async def test_a_backdated_break_override_recalculates_the_days_it_covers(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """AR-09: the day was calculated with the shift's 60-minute lunch; an override dated back
    to it shortens the lunch. Before, nothing was queued and the stored day kept 480 minutes."""
    from tests.integration.modules.attendance.test_break_events_api import (
        _cleanup_all as _cleanup_breaks,
    )
    from tests.integration.modules.attendance.test_break_events_api import _setup
    from tests.integration.modules.attendance.test_break_overrides_api import (
        AUTO_LUNCH,
        _day,
        _override,
    )

    ctx = await _setup(client, [AUTO_LUNCH])
    try:
        assert (await _day(client, ctx, MON))["worked_minutes"] == 480
        await _settle_queue(ctx["company_id"])
        created = await _override(
            client,
            ctx,
            action="REPLACE",
            target_break_name="Lunch",
            effective_from=MON,
            scheduled_minutes=30,
            end_time="13:30",
        )
        assert created.status_code == 201, created.text
        assert await _pending_reasons(ctx["company_id"]) == ["BREAK_OVERRIDE_CHANGED"]
        await recalc.process_company_requests(ctx["company_id"])
        stored = await _stored(client, ctx["hr"], ctx["employee_id"], MON)
        assert stored["worked_minutes"] == 510
    finally:
        await _cleanup_breaks(ctx)
