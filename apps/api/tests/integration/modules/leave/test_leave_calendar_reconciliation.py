"""AC-03 / owner decision P-E (16 Nov 2026): approved leave follows the calendar it sits on.

A holiday added inside approved leave refunds the day; one removed debits it, or - when the balance
cannot cover it and the leave type does not allow a negative balance - opens a shortfall exception
that blocks attendance period close and is never turned into loss of pay. Sandwich rule off
throughout, so a holiday between two leave days is not charged as a bracketed day."""

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.test_attendance_period import (
    _cleanup_attendance_period,
    _create_period,
    _insert_closed_period,
)
from tests.integration.modules.leave.test_leave_application import (
    _get_balance,
    _give_balance,
    _register_tenant,
    _setup_full,
    _submit,
    _teardown,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup
from tests.integration.modules.organisation.test_workforce_calendar import (
    _cleanup_workforce_calendar,
)

from hrms.core.db.session import get_session_factory, set_rls_company_id

pytestmark = pytest.mark.asyncio

_PERIOD = ("2026-09-01", "2026-09-30")
_HOLIDAY = "2026-09-09"  # the Wednesday inside the Tue-Thu leave below


async def _sql(company_id: UUID, query: str) -> list[Any]:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        result = await session.execute(text(query), {"cid": str(company_id)})
        rows = list(result) if result.returns_rows else []
        await session.commit()
        return rows


async def _blockers(
    client: AsyncClient, headers: dict[str, str], period: dict[str, Any]
) -> dict[str, Any]:
    validated = await client.post(
        f"/v1/attendance-periods/{period['id']}/validate", headers=headers
    )
    assert validated.status_code == 200, validated.text
    return {r["code"]: r for r in validated.json()["data"]["reasons"]}


async def _period(client: AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    return await _create_period(
        client, headers, period_start=_PERIOD[0], period_end=_PERIOD[1], label="Sep"
    )


async def _holiday_calendar(client: AsyncClient, headers: dict[str, str]) -> str:
    calendar = await client.post("/v1/holiday-calendars", headers=headers, json={"name": "Closed"})
    assert calendar.status_code == 201, calendar.text
    calendar_id = str(calendar.json()["data"]["id"])
    work_calendar = (await client.get("/v1/work-calendars", headers=headers)).json()["data"][0]
    linked = await client.patch(
        f"/v1/work-calendars/{work_calendar['id']}",
        headers={**headers, "If-Match": str(work_calendar["version"])},
        json={"holiday_calendar_ids": [calendar_id]},
    )
    assert linked.status_code == 200, linked.text
    return calendar_id


async def _add_holiday(
    client: AsyncClient, headers: dict[str, str], calendar_id: str, day: str = _HOLIDAY
) -> dict[str, Any]:
    holiday = await client.post(
        f"/v1/holiday-calendars/{calendar_id}/holidays",
        headers=headers,
        json={"date": day, "name": "Closed"},
    )
    assert holiday.status_code == 201, holiday.text
    return dict(holiday.json()["data"])


async def _remove_holiday(
    client: AsyncClient, headers: dict[str, str], holiday: dict[str, Any]
) -> None:
    removed = await client.patch(
        f"/v1/holidays/{holiday['id']}",
        headers={**headers, "If-Match": str(holiday["version"])},
        json={"is_active": False},
    )
    assert removed.status_code == 200, removed.text


async def _leave(
    client: AsyncClient, headers: dict[str, str], ctx: dict[str, Any]
) -> dict[str, Any]:
    submitted = await _submit(
        client,
        headers,
        employee_id=ctx["employee"]["id"],
        leave_type_id=ctx["leave_type"]["id"],
        start_date="2026-09-08",
        end_date="2026-09-10",
    )
    assert submitted.status_code == 201, submitted.text
    assert submitted.json()["data"]["status"] == "APPROVED"
    return dict(submitted.json()["data"])


async def _application(
    client: AsyncClient, headers: dict[str, str], application_id: str
) -> dict[str, Any]:
    read = await client.get(f"/v1/leave-applications/{application_id}", headers=headers)
    assert read.status_code == 200, read.text
    return dict(read.json()["data"])


async def _ledger(company_id: UUID) -> list[tuple[str, str]]:
    rows = await _sql(
        company_id,
        "SELECT entry_type, amount FROM leave_ledger WHERE company_id = :cid ORDER BY created_at",
    )
    return [(r[0], str(r[1])) for r in rows]


async def _cleanup_all(company_id: Any, user_id: Any) -> None:
    await _sql(company_id, "DELETE FROM leave_balance_shortfall WHERE company_id = :cid")
    await _cleanup_attendance_period(company_id=company_id)
    await _cleanup_workforce_calendar(company_id=company_id)
    await _teardown(company_id=company_id)
    await _cleanup(company_id=company_id, user_id=user_id)


async def test_a_holiday_added_inside_approved_leave_refunds_the_day(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, sandwich_rule_enabled=False)
        employee_id = ctx["employee"]["id"]
        leave = await _leave(client, headers, ctx)
        assert leave["total_days"] == "3.00"
        assert await _get_balance(client, headers, employee_id) == "17.00"
        calendar_id = await _holiday_calendar(client, headers)
        ledger_before = await _ledger(company_id)

        holiday = await _add_holiday(client, headers, calendar_id)

        assert await _get_balance(client, headers, employee_id) == "18.00"
        after = await _application(client, headers, leave["id"])
        assert after["status"] == "APPROVED"  # the approval itself is untouched
        assert (after["start_date"], after["end_date"]) == ("2026-09-08", "2026-09-10")
        assert after["total_days"] == "2.00"
        assert [d["calendar_date"] for d in after["days"]] == ["2026-09-08", "2026-09-10"]
        assert "CALENDAR_RECONCILED" in [a["action"] for a in after["actions"]]
        # History is appended to, never rewritten: the old entries are all still there.
        ledger_after = await _ledger(company_id)
        assert ledger_after[: len(ledger_before)] == ledger_before
        assert ledger_after[len(ledger_before) :] == [("ADJUSTMENT", "1.00")]
        # The attendance projection for the holiday is gone; the other two stand.
        active = await _sql(
            company_id,
            "SELECT attendance_date FROM leave_day_projection "
            "WHERE company_id = :cid AND status = 'APPROVED' ORDER BY attendance_date",
        )
        assert [r[0].isoformat() for r in active] == ["2026-09-08", "2026-09-10"]
        assert (
            (await _blockers(client, headers, await _period(client, headers)))
            .keys()
            .isdisjoint({"LEAVE_CALENDAR_MISMATCH", "LEAVE_BALANCE_SHORTFALL"})
        )

        # Idempotent: another edit of the same holiday re-runs reconciliation and changes nothing.
        renamed = await client.patch(
            f"/v1/holidays/{holiday['id']}",
            headers={**headers, "If-Match": str(holiday["version"])},
            json={"name": "Closed for the day"},
        )
        assert renamed.status_code == 200, renamed.text
        assert await _ledger(company_id) == ledger_after
        assert await _get_balance(client, headers, employee_id) == "18.00"
        notified = await _sql(
            company_id,
            "SELECT count(*) FROM notification WHERE company_id = :cid "
            "AND type = 'LEAVE_BALANCE_RECONCILED'",
        )
        assert notified[0][0] >= 1
    finally:
        await _cleanup_all(company_id, user_id)


async def test_a_holiday_removed_inside_approved_leave_debits_the_day(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, sandwich_rule_enabled=False)
        employee_id = ctx["employee"]["id"]
        holiday = await _add_holiday(client, headers, await _holiday_calendar(client, headers))
        leave = await _leave(client, headers, ctx)
        assert leave["total_days"] == "2.00"  # the holiday is not charged
        assert await _get_balance(client, headers, employee_id) == "18.00"

        await _remove_holiday(client, headers, holiday)

        assert await _get_balance(client, headers, employee_id) == "17.00"
        after = await _application(client, headers, leave["id"])
        assert after["total_days"] == "3.00" and after["lop_days"] == "0.00"
        assert [d["calendar_date"] for d in after["days"]] == [
            "2026-09-08",
            "2026-09-09",
            "2026-09-10",
        ]
        assert (await _ledger(company_id))[-1] == ("APPLICATION", "-1.00")
        blockers = await _blockers(client, headers, await _period(client, headers))
        assert blockers.keys().isdisjoint({"LEAVE_CALENDAR_MISMATCH", "LEAVE_BALANCE_SHORTFALL"})

        # Cancelling the leave afterwards refunds everything it debited, the added day included.
        cancelled = await client.post(
            f"/v1/leave-applications/{leave['id']}/cancel",
            headers={**headers, "If-Match": str(after["version"])},
            json={"reason": "Plans changed"},
        )
        assert cancelled.status_code == 200, cancelled.text
        assert await _get_balance(client, headers, employee_id) == "20.00"
    finally:
        await _cleanup_all(company_id, user_id)


async def test_a_shortfall_is_an_exception_not_loss_of_pay_and_hr_resolves_it_with_balance(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, sandwich_rule_enabled=False, balance="2.00")
        employee_id = ctx["employee"]["id"]
        holiday = await _add_holiday(client, headers, await _holiday_calendar(client, headers))
        leave = await _leave(client, headers, ctx)
        assert await _get_balance(client, headers, employee_id) == "0.00"
        ledger_before = await _ledger(company_id)

        await _remove_holiday(client, headers, holiday)

        # Nothing is debited, no day is added, nothing becomes loss of pay.
        assert await _ledger(company_id) == ledger_before
        after = await _application(client, headers, leave["id"])
        assert after["total_days"] == "2.00" and after["lop_days"] == "0.00"
        assert "BALANCE_SHORTFALL" in [a["action"] for a in after["actions"]]
        period = await _period(client, headers)
        blockers = await _blockers(client, headers, period)
        assert "LEAVE_BALANCE_SHORTFALL" in blockers
        assert "LEAVE_CALENDAR_MISMATCH" not in blockers  # reported once, as the shortfall
        sample = blockers["LEAVE_BALANCE_SHORTFALL"]["sample"][0]
        assert employee_id in sample and _HOLIDAY in sample and "needs 1.00" in sample
        open_rows = await _sql(
            company_id,
            "SELECT status FROM leave_balance_shortfall WHERE company_id = :cid",
        )
        assert [r[0] for r in open_rows] == ["OPEN"]

        # HR grants the missing day: the waiting day is debited and the exception closes.
        await _give_balance(
            client,
            headers,
            employee_id=employee_id,
            leave_type_id=ctx["leave_type"]["id"],
            amount="1.00",
        )
        assert await _get_balance(client, headers, employee_id) == "0.00"
        resolved = await _application(client, headers, leave["id"])
        assert resolved["total_days"] == "3.00" and resolved["lop_days"] == "0.00"
        rows = await _sql(
            company_id,
            "SELECT status, resolution FROM leave_balance_shortfall WHERE company_id = :cid",
        )
        assert [(r[0], r[1]) for r in rows] == [("RESOLVED", "DEBITED")]
        blockers = await _blockers(client, headers, period)
        assert blockers.keys().isdisjoint({"LEAVE_CALENDAR_MISMATCH", "LEAVE_BALANCE_SHORTFALL"})
    finally:
        await _cleanup_all(company_id, user_id)


async def test_a_shortfall_closes_itself_when_the_holiday_comes_back(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, sandwich_rule_enabled=False, balance="2.00")
        calendar_id = await _holiday_calendar(client, headers)
        holiday = await _add_holiday(client, headers, calendar_id)
        await _leave(client, headers, ctx)
        await _remove_holiday(client, headers, holiday)
        reactivated = await client.patch(
            f"/v1/holidays/{holiday['id']}",
            headers={**headers, "If-Match": str(holiday["version"] + 1)},
            json={"is_active": True},
        )
        assert reactivated.status_code == 200, reactivated.text
        rows = await _sql(
            company_id,
            "SELECT status, resolution FROM leave_balance_shortfall WHERE company_id = :cid",
        )
        assert [(r[0], r[1]) for r in rows] == [("RESOLVED", "NO_LONGER_REQUIRED")]
    finally:
        await _cleanup_all(company_id, user_id)


async def test_a_negative_balance_is_used_only_where_the_policy_allows_it(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(
            client,
            headers,
            sandwich_rule_enabled=False,
            balance="2.00",
            allow_negative_balance=True,
            negative_balance_floor="2.00",
        )
        employee_id = ctx["employee"]["id"]
        holiday = await _add_holiday(client, headers, await _holiday_calendar(client, headers))
        leave = await _leave(client, headers, ctx)

        await _remove_holiday(client, headers, holiday)

        assert await _get_balance(client, headers, employee_id) == "-1.00"
        assert (await _application(client, headers, leave["id"]))["total_days"] == "3.00"
        assert (
            await _sql(company_id, "SELECT 1 FROM leave_balance_shortfall WHERE company_id = :cid")
            == []
        )
    finally:
        await _cleanup_all(company_id, user_id)


async def test_leave_in_a_closed_attendance_period_is_never_changed(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, sandwich_rule_enabled=False)
        employee_id = ctx["employee"]["id"]
        leave = await _leave(client, headers, ctx)
        calendar_id = await _holiday_calendar(client, headers)
        await _insert_closed_period(
            company_id=company_id,
            period_start=_PERIOD[0],
            period_end=_PERIOD[1],
            legal_entity_id=ctx["legal_entity"]["id"],
        )
        ledger_before = await _ledger(company_id)

        await _add_holiday(client, headers, calendar_id)

        assert await _ledger(company_id) == ledger_before
        assert await _get_balance(client, headers, employee_id) == "17.00"
        assert (await _application(client, headers, leave["id"]))["total_days"] == "3.00"
    finally:
        await _cleanup_all(company_id, user_id)
