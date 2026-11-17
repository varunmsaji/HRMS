"""R-1 (independent pre-commit review, 16 Nov 2026): leave whose every day was released.

When a holiday lands on every date of an approved leave, reconciliation refunds each day and deletes
its day row, leaving an `APPROVED` application with no day rows. Before the fix, nothing could
reconstruct the leave from that state, so removing the holiday again charged nothing, projected
nothing, and period close raised no `LEAVE_CALENDAR_MISMATCH` - the employee lost a day's pay on a
date they held approved leave for.

These tests describe the required behaviour: the original full-day or half-day leave is rebuilt
from the application itself (the half is stored on it), the ledger is only ever appended to, and
the attendance projections follow. Sandwich rule off, as in `test_leave_calendar_reconciliation`.
"""

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from tests.integration.modules.leave.test_leave_application import (
    _get_balance,
    _register_tenant,
    _setup_full,
    _submit,
)
from tests.integration.modules.leave.test_leave_calendar_reconciliation import (
    _add_holiday,
    _application,
    _blockers,
    _cleanup_all,
    _holiday_calendar,
    _ledger,
    _period,
    _remove_holiday,
    _sql,
)

pytestmark = pytest.mark.asyncio

_DAY = "2026-09-09"  # a Wednesday
_NO_DRIFT = {"LEAVE_CALENDAR_MISMATCH", "LEAVE_BALANCE_SHORTFALL"}


async def _leave_on(
    client: AsyncClient,
    headers: dict[str, str],
    ctx: dict[str, Any],
    start: str,
    end: str,
    **extra: Any,
) -> dict[str, Any]:
    submitted = await _submit(
        client,
        headers,
        employee_id=ctx["employee"]["id"],
        leave_type_id=ctx["leave_type"]["id"],
        start_date=start,
        end_date=end,
        **extra,
    )
    assert submitted.status_code == 201, submitted.text
    assert submitted.json()["data"]["status"] == "APPROVED"
    return dict(submitted.json()["data"])


async def _active_projections(company_id: UUID) -> list[tuple[str, str]]:
    rows = await _sql(
        company_id,
        "SELECT attendance_date, fraction FROM leave_day_projection "
        "WHERE company_id = :cid AND status = 'APPROVED' ORDER BY attendance_date",
    )
    return [(r[0].isoformat(), str(r[1])) for r in rows]


def _assert_append_only(before: list[tuple[str, str]], after: list[tuple[str, str]]) -> None:
    assert after[: len(before)] == before, "a ledger entry was edited or removed"


async def test_single_full_day_leave_is_restored_after_its_only_day_was_released(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, sandwich_rule_enabled=False)
        employee_id = ctx["employee"]["id"]
        calendar_id = await _holiday_calendar(client, headers)
        leave = await _leave_on(client, headers, ctx, _DAY, _DAY)
        assert await _get_balance(client, headers, employee_id) == "19.00"
        assert await _active_projections(company_id) == [(_DAY, "1.00")]
        history = await _ledger(company_id)

        holiday = await _add_holiday(client, headers, calendar_id, _DAY)

        released = await _application(client, headers, leave["id"])
        assert released["status"] == "APPROVED" and released["days"] == []
        assert released["total_days"] == "0.00"
        assert await _get_balance(client, headers, employee_id) == "20.00"
        assert await _active_projections(company_id) == []
        after_release = await _ledger(company_id)
        _assert_append_only(history, after_release)

        await _remove_holiday(client, headers, holiday)

        restored = await _application(client, headers, leave["id"])
        assert restored["status"] == "APPROVED"
        assert (restored["start_date"], restored["end_date"]) == (_DAY, _DAY)
        assert restored["total_days"] == "1.00" and restored["lop_days"] == "0.00"
        assert [(d["calendar_date"], d["fraction"]) for d in restored["days"]] == [(_DAY, "1.00")]
        assert await _get_balance(client, headers, employee_id) == "19.00"
        assert await _active_projections(company_id) == [(_DAY, "1.00")]
        after_restore = await _ledger(company_id)
        _assert_append_only(after_release, after_restore)
        assert after_restore[len(after_release) :] == [("APPLICATION", "-1.00")]
        blockers = await _blockers(client, headers, await _period(client, headers))
        assert blockers.keys().isdisjoint(_NO_DRIFT)
    finally:
        await _cleanup_all(company_id, user_id)


async def test_single_half_day_leave_is_restored_as_the_same_half(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, sandwich_rule_enabled=False)
        employee_id = ctx["employee"]["id"]
        calendar_id = await _holiday_calendar(client, headers)
        leave = await _leave_on(client, headers, ctx, _DAY, _DAY, half_day="SECOND_HALF")
        assert await _get_balance(client, headers, employee_id) == "19.50"
        assert await _active_projections(company_id) == [(_DAY, "0.50")]
        history = await _ledger(company_id)

        holiday = await _add_holiday(client, headers, calendar_id, _DAY)

        assert (await _application(client, headers, leave["id"]))["days"] == []
        assert await _get_balance(client, headers, employee_id) == "20.00"
        assert await _active_projections(company_id) == []

        await _remove_holiday(client, headers, holiday)

        restored = await _application(client, headers, leave["id"])
        assert restored["total_days"] == "0.50"
        assert [(d["calendar_date"], d["fraction"], d["half"]) for d in restored["days"]] == [
            (_DAY, "0.50", "SECOND_HALF")
        ]
        assert await _get_balance(client, headers, employee_id) == "19.50"
        assert await _active_projections(company_id) == [(_DAY, "0.50")]
        ledger = await _ledger(company_id)
        _assert_append_only(history, ledger)
        assert ledger[-1] == ("APPLICATION", "-0.50")
        blockers = await _blockers(client, headers, await _period(client, headers))
        assert blockers.keys().isdisjoint(_NO_DRIFT)
    finally:
        await _cleanup_all(company_id, user_id)


async def test_multi_day_leave_with_every_day_released_is_restored_day_by_day(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, sandwich_rule_enabled=False)
        employee_id = ctx["employee"]["id"]
        calendar_id = await _holiday_calendar(client, headers)
        leave = await _leave_on(client, headers, ctx, "2026-09-08", "2026-09-10")
        assert await _get_balance(client, headers, employee_id) == "17.00"
        history = await _ledger(company_id)

        holidays = [
            await _add_holiday(client, headers, calendar_id, day)
            for day in ("2026-09-08", "2026-09-09", "2026-09-10")
        ]

        released = await _application(client, headers, leave["id"])
        assert released["days"] == [] and released["total_days"] == "0.00"
        assert await _get_balance(client, headers, employee_id) == "20.00"
        assert await _active_projections(company_id) == []
        after_release = await _ledger(company_id)
        _assert_append_only(history, after_release)

        # Restored one at a time: each removal charges exactly its own day.
        for index, holiday in enumerate(holidays, start=1):
            await _remove_holiday(client, headers, holiday)
            assert await _get_balance(client, headers, employee_id) == f"{20 - index}.00"

        restored = await _application(client, headers, leave["id"])
        assert restored["total_days"] == "3.00" and restored["lop_days"] == "0.00"
        assert [d["calendar_date"] for d in restored["days"]] == [
            "2026-09-08",
            "2026-09-09",
            "2026-09-10",
        ]
        assert (restored["start_date"], restored["end_date"]) == ("2026-09-08", "2026-09-10")
        assert await _active_projections(company_id) == [
            ("2026-09-08", "1.00"),
            ("2026-09-09", "1.00"),
            ("2026-09-10", "1.00"),
        ]
        after_restore = await _ledger(company_id)
        _assert_append_only(after_release, after_restore)
        assert after_restore[len(after_release) :] == [("APPLICATION", "-1.00")] * 3
        blockers = await _blockers(client, headers, await _period(client, headers))
        assert blockers.keys().isdisjoint(_NO_DRIFT)
    finally:
        await _cleanup_all(company_id, user_id)


async def test_repeated_reconciliation_and_cancellation_after_restoration(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, sandwich_rule_enabled=False)
        employee_id = ctx["employee"]["id"]
        calendar_id = await _holiday_calendar(client, headers)
        leave = await _leave_on(client, headers, ctx, _DAY, _DAY)

        # Two full cycles: release, restore, release, restore. The balance never drifts.
        holiday = await _add_holiday(client, headers, calendar_id, _DAY)
        await _remove_holiday(client, headers, holiday)
        assert await _get_balance(client, headers, employee_id) == "19.00"
        reactivated = await client.patch(
            f"/v1/holidays/{holiday['id']}",
            headers={**headers, "If-Match": str(holiday["version"] + 1)},
            json={"is_active": True},
        )
        assert reactivated.status_code == 200, reactivated.text
        assert await _get_balance(client, headers, employee_id) == "20.00"
        assert (await _application(client, headers, leave["id"]))["days"] == []
        again = await client.patch(
            f"/v1/holidays/{holiday['id']}",
            headers={**headers, "If-Match": str(holiday["version"] + 2)},
            json={"is_active": False},
        )
        assert again.status_code == 200, again.text
        assert await _get_balance(client, headers, employee_id) == "19.00"

        # Re-saving the same holiday re-runs reconciliation: nothing is written.
        ledger = await _ledger(company_id)
        resaved = await client.patch(
            f"/v1/holidays/{holiday['id']}",
            headers={**headers, "If-Match": str(holiday["version"] + 3)},
            json={"name": "Closed again"},
        )
        assert resaved.status_code == 200, resaved.text
        assert await _ledger(company_id) == ledger
        assert await _active_projections(company_id) == [(_DAY, "1.00")]

        # Cancelling the restored leave refunds exactly what it holds - no more, no less.
        current = await _application(client, headers, leave["id"])
        cancelled = await client.post(
            f"/v1/leave-applications/{leave['id']}/cancel",
            headers={**headers, "If-Match": str(current["version"])},
            json={"reason": "Plans changed"},
        )
        assert cancelled.status_code == 200, cancelled.text
        assert await _get_balance(client, headers, employee_id) == "20.00"
        assert await _active_projections(company_id) == []
        total = await _sql(
            company_id,
            "SELECT sum(amount) FROM leave_ledger WHERE company_id = :cid "
            "AND employee_id = :eid".replace(":eid", f"'{employee_id}'"),
        )
        assert str(total[0][0]) == "20.00"
    finally:
        await _cleanup_all(company_id, user_id)


async def test_cancelling_a_leave_whose_every_day_is_released_refunds_nothing_more(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, sandwich_rule_enabled=False)
        employee_id = ctx["employee"]["id"]
        calendar_id = await _holiday_calendar(client, headers)
        leave = await _leave_on(client, headers, ctx, _DAY, _DAY)
        await _add_holiday(client, headers, calendar_id, _DAY)
        assert await _get_balance(client, headers, employee_id) == "20.00"

        current = await _application(client, headers, leave["id"])
        cancelled = await client.post(
            f"/v1/leave-applications/{leave['id']}/cancel",
            headers={**headers, "If-Match": str(current["version"])},
            json={"reason": "Not needed"},
        )
        assert cancelled.status_code == 200, cancelled.text

        # That day was already refunded when the holiday arrived: no second refund.
        assert await _get_balance(client, headers, employee_id) == "20.00"
    finally:
        await _cleanup_all(company_id, user_id)
