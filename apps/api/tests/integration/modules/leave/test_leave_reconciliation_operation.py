"""R-3 (independent pre-commit review, 16 Nov 2026): the HR leave-reconciliation operation.

Roster, shift, weekly-off pattern and work-calendar changes do not rewrite approved leave by
themselves (Work Calendar policy A is not retroactive), so the approved leave can disagree with the
calendar it sits on. `POST /v1/leave-reconciliation/preview` shows exactly what HR would change;
`POST /v1/leave-reconciliation/apply` applies what was previewed - one transaction, idempotent,
audited, never touching a closed attendance period, never converting a shortfall to loss of pay.

Sandwich rule off throughout, so a day off between two leave days is not bracketed into a charge.
"""

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from tests.integration.modules.attendance.test_attendance_period import (
    _cleanup_attendance_period,
    _insert_closed_period,
)
from tests.integration.modules.attendance.test_attendance_security import (
    _cleanup_scoped_users,
    _create_permission_scoped_user,
)
from tests.integration.modules.leave.test_leave_application import (
    _get_balance,
    _register_tenant,
    _setup_full,
    _teardown,
)
from tests.integration.modules.leave.test_leave_calendar_reconciliation import (
    _application,
    _blockers,
    _cleanup_all,
    _ledger,
    _period,
    _sql,
)
from tests.integration.modules.leave.test_leave_full_release_restoration import _leave_on
from tests.integration.modules.leave.test_leave_roster_days import (
    _assign_shift,
    _drop_rosters,
    _drop_shifts,
    _roster,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup
from tests.integration.modules.organisation.test_workforce_calendar import (
    _cleanup_workforce_calendar,
)

from hrms.modules.leave.permissions import LEAVE_BALANCE_ADJUST

pytestmark = pytest.mark.asyncio

_WINDOW = {"date_from": "2026-09-01", "date_to": "2026-09-30"}
_DRIFT = {"LEAVE_CALENDAR_MISMATCH", "LEAVE_BALANCE_SHORTFALL"}


async def _preview(client: AsyncClient, headers: dict[str, str], **extra: Any) -> dict[str, Any]:
    response = await client.post(
        "/v1/leave-reconciliation/preview", headers=headers, json={**_WINDOW, **extra}
    )
    assert response.status_code == 200, response.text
    return dict(response.json()["data"])


async def _apply_raw(
    client: AsyncClient,
    headers: dict[str, str],
    digest: str,
    *,
    key: str | None = None,
    reason: str = "Roster published after approval",
    **extra: Any,
) -> Any:
    return await client.post(
        "/v1/leave-reconciliation/apply",
        headers={**headers, "Idempotency-Key": key or f"recon-{uuid4()}"},
        json={**_WINDOW, "reason": reason, "preview_digest": digest, **extra},
    )


async def _apply(
    client: AsyncClient, headers: dict[str, str], digest: str, **kwargs: Any
) -> dict[str, Any]:
    response = await _apply_raw(client, headers, digest, **kwargs)
    assert response.status_code == 200, response.text
    return dict(response.json()["data"])


async def _set_weekly_off(
    client: AsyncClient, headers: dict[str, str], weekdays: tuple[int, ...]
) -> None:
    calendar = (await client.get("/v1/work-calendars", headers=headers)).json()["data"][0]
    pattern_id = calendar["weekly_off_pattern_id"]
    current = (await client.get(f"/v1/weekly-off-patterns/{pattern_id}", headers=headers)).json()[
        "data"
    ]
    changed = await client.patch(
        f"/v1/weekly-off-patterns/{pattern_id}",
        headers={**headers, "If-Match": str(current["version"])},
        json={"rules": [{"weekday": d, "off_fraction": "1.00"} for d in weekdays]},
    )
    assert changed.status_code == 200, changed.text


async def _audit_actions(company_id: UUID) -> list[str]:
    rows = await _sql(
        company_id,
        "SELECT action FROM audit_log WHERE company_id = :cid "
        "AND action LIKE 'LEAVE_%RECONCIL%' ORDER BY occurred_at",
    )
    return [r[0] for r in rows]


async def test_weekly_off_change_over_charge_previews_then_applies_once(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, sandwich_rule_enabled=False)
        employee_id = ctx["employee"]["id"]
        leave = await _leave_on(client, headers, ctx, "2026-09-08", "2026-09-10")
        assert await _get_balance(client, headers, employee_id) == "17.00"

        # Wednesday becomes a weekly off. Nothing rewrites the approved leave by itself...
        await _set_weekly_off(client, headers, (2, 6))
        assert await _get_balance(client, headers, employee_id) == "17.00"
        period = await _period(client, headers)
        assert "LEAVE_CALENDAR_MISMATCH" in await _blockers(client, headers, period)
        ledger_before = await _ledger(company_id)

        # ...HR previews: the preview is read-only and says exactly what would be written.
        preview = await _preview(client, headers)
        assert len(preview["digest"]) == 64 and preview["nothing_to_do"] is False
        assert [
            (i["calendar_date"], i["kind"], i["outcome"], i["balance_effect"])
            for i in preview["items"]
        ] == [("2026-09-09", "OVER_CHARGED", "REFUND", "1.00")]
        assert preview["refund_days"] == "1.00" and preview["debit_days"] == "0.00"
        assert await _ledger(company_id) == ledger_before
        assert await _get_balance(client, headers, employee_id) == "17.00"
        assert (await _application(client, headers, leave["id"]))["total_days"] == "3.00"

        # A digest that is not the one previewed is refused and writes nothing.
        refused = await _apply_raw(client, headers, "0" * 64)
        assert refused.status_code == 409, refused.text
        assert refused.json()["error"]["code"] == "LEAVE_RECONCILIATION_PREVIEW_STALE"
        assert await _ledger(company_id) == ledger_before

        key = f"recon-{uuid4()}"
        run = await _apply(client, headers, preview["digest"], key=key)
        assert run["noop"] is False
        assert run["applications_changed"] == 1 and run["refunded_days"] == "1.00"
        assert run["days_released"] == 1 and run["shortfalls_opened"] == 0
        assert await _get_balance(client, headers, employee_id) == "18.00"
        after = await _application(client, headers, leave["id"])
        assert after["status"] == "APPROVED" and after["total_days"] == "2.00"
        assert [d["calendar_date"] for d in after["days"]] == ["2026-09-08", "2026-09-10"]
        ledger_after = await _ledger(company_id)
        assert ledger_after[: len(ledger_before)] == ledger_before  # history never rewritten
        assert ledger_after[len(ledger_before) :] == [("ADJUSTMENT", "1.00")]
        timeline = [a for a in after["actions"] if a["action"] == "CALENDAR_RECONCILED"]
        assert len(timeline) == 1 and "Roster published after approval" in timeline[0]["comment"]
        assert {
            "LEAVE_APPLICATION_CALENDAR_RECONCILED",
            "LEAVE_CALENDAR_RECONCILIATION_RUN",
        } <= set(await _audit_actions(company_id))
        assert (await _blockers(client, headers, period)).keys().isdisjoint(_DRIFT)

        # Idempotent: the same request replays; a fresh request finds nothing left to do.
        replay = await _apply_raw(client, headers, preview["digest"], key=key)
        assert replay.status_code == 200 and replay.json()["data"]["run_id"] == run["run_id"]
        again = await _apply(client, headers, preview["digest"])
        assert again["noop"] is True and again["applications_changed"] == 0
        assert await _ledger(company_id) == ledger_after
        assert await _get_balance(client, headers, employee_id) == "18.00"
        assert (await _preview(client, headers))["nothing_to_do"] is True
    finally:
        await _cleanup_all(company_id, user_id)


async def test_a_shortfall_stays_an_exception_and_is_never_turned_into_loss_of_pay(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        # Friday and Saturday off: leave Fri 11 - Sun 13 September charges only the Sunday?? No:
        # weekly off (5, 6) means Sat and Sun are off, so the leave charges Friday alone.
        ctx = await _setup_full(
            client, headers, sandwich_rule_enabled=False, balance="1.00", weekly_off_days=(5, 6)
        )
        employee_id = ctx["employee"]["id"]
        leave = await _leave_on(client, headers, ctx, "2026-09-11", "2026-09-13")
        assert leave["total_days"] == "1.00"
        assert await _get_balance(client, headers, employee_id) == "0.00"

        await _set_weekly_off(client, headers, (6,))  # Saturday is a working day again
        ledger_before = await _ledger(company_id)

        preview = await _preview(client, headers)
        assert [
            (i["calendar_date"], i["kind"], i["outcome"], i["balance_effect"])
            for i in preview["items"]
        ] == [("2026-09-12", "UNDER_CHARGED", "SHORTFALL", "0.00")]
        assert preview["shortfall_days"] == "1.00" and preview["debit_days"] == "0.00"

        run = await _apply(client, headers, preview["digest"], reason="Saturday now a working day")
        assert run["shortfalls_opened"] == 1 and run["days_added"] == 0
        assert await _ledger(company_id) == ledger_before  # nothing debited
        after = await _application(client, headers, leave["id"])
        assert after["total_days"] == "1.00" and after["lop_days"] == "0.00"  # not LOP
        period = await _period(client, headers)
        assert "LEAVE_BALANCE_SHORTFALL" in await _blockers(client, headers, period)
        rows = await _sql(
            company_id, "SELECT status FROM leave_balance_shortfall WHERE company_id = :cid"
        )
        assert [r[0] for r in rows] == ["OPEN"]

        # Applying again does not open a second exception or notify twice.
        again = await _preview(client, headers)
        second = await _apply(client, headers, again["digest"])
        assert second["shortfalls_opened"] == 0
        rows = await _sql(
            company_id, "SELECT count(*) FROM leave_balance_shortfall WHERE company_id = :cid"
        )
        assert rows[0][0] == 1
    finally:
        await _cleanup_all(company_id, user_id)


async def test_a_published_roster_day_off_after_approval_is_refunded_by_hr(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, sandwich_rule_enabled=False)
        employee_id = ctx["employee"]["id"]
        leave = await _leave_on(client, headers, ctx, "2026-09-08", "2026-09-10")
        await _roster(client, headers, employee_id, "2026-09-09", is_week_off_override=True)
        assert await _get_balance(client, headers, employee_id) == "17.00"

        preview = await _preview(client, headers, employee_ids=[employee_id])
        assert [(i["calendar_date"], i["outcome"]) for i in preview["items"]] == [
            ("2026-09-09", "REFUND")
        ]
        await _apply(client, headers, preview["digest"], employee_ids=[employee_id])

        assert await _get_balance(client, headers, employee_id) == "18.00"
        assert (await _application(client, headers, leave["id"]))["total_days"] == "2.00"
    finally:
        await _drop_rosters(company_id)
        await _cleanup_all(company_id, user_id)


async def test_a_shift_that_operates_on_the_weekly_off_after_approval_is_debited_by_hr(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, sandwich_rule_enabled=False)
        employee_id = ctx["employee"]["id"]
        # Friday 11 - Monday 14 September: Sunday off, so Fri, Sat, Mon are charged.
        leave = await _leave_on(client, headers, ctx, "2026-09-11", "2026-09-14")
        assert await _get_balance(client, headers, employee_id) == "17.00"

        await _assign_shift(
            client, headers, employee_id, ctx["legal_entity"]["id"], operates_on_weekly_off=True
        )

        preview = await _preview(client, headers)
        assert [
            (i["calendar_date"], i["kind"], i["outcome"], i["balance_effect"])
            for i in preview["items"]
        ] == [("2026-09-13", "UNDER_CHARGED", "DEBIT", "-1.00")]
        await _apply(client, headers, preview["digest"])

        assert await _get_balance(client, headers, employee_id) == "16.00"
        after = await _application(client, headers, leave["id"])
        assert after["total_days"] == "4.00" and after["lop_days"] == "0.00"
        assert "2026-09-13" in [d["calendar_date"] for d in after["days"]]
    finally:
        await _sql(company_id, "DELETE FROM leave_balance_shortfall WHERE company_id = :cid")
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_workforce_calendar(company_id=company_id)
        await _teardown(company_id=company_id)
        await _drop_shifts(company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_a_preview_gone_stale_applies_nothing(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, sandwich_rule_enabled=False)
        employee_id = ctx["employee"]["id"]
        await _leave_on(client, headers, ctx, "2026-09-08", "2026-09-10")
        await _set_weekly_off(client, headers, (2, 6))
        preview = await _preview(client, headers)
        ledger_before = await _ledger(company_id)

        await _set_weekly_off(client, headers, (1, 2, 6))  # Tuesday joins: the drift grew

        refused = await _apply_raw(client, headers, preview["digest"])
        assert refused.status_code == 409, refused.text
        assert refused.json()["error"]["code"] == "LEAVE_RECONCILIATION_PREVIEW_STALE"
        assert await _ledger(company_id) == ledger_before
        assert await _get_balance(client, headers, employee_id) == "17.00"

        fresh = await _preview(client, headers)
        assert [i["calendar_date"] for i in fresh["items"]] == ["2026-09-08", "2026-09-09"]
        await _apply(client, headers, fresh["digest"])
        assert await _get_balance(client, headers, employee_id) == "19.00"
    finally:
        await _cleanup_all(company_id, user_id)


async def test_a_closed_attendance_period_is_protected_from_the_operation(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, sandwich_rule_enabled=False)
        employee_id = ctx["employee"]["id"]
        leave = await _leave_on(client, headers, ctx, "2026-09-08", "2026-09-10")
        await _set_weekly_off(client, headers, (2, 6))
        await _insert_closed_period(
            company_id=company_id,
            period_start="2026-09-01",
            period_end="2026-09-30",
            legal_entity_id=ctx["legal_entity"]["id"],
        )
        ledger_before = await _ledger(company_id)

        preview = await _preview(client, headers)
        assert [(i["calendar_date"], i["outcome"]) for i in preview["items"]] == [
            ("2026-09-09", "PROTECTED")
        ]
        assert preview["nothing_to_do"] is True and preview["protected_count"] == 1

        run = await _apply(client, headers, preview["digest"])
        assert run["noop"] is True and run["protected_count"] == 1
        assert await _ledger(company_id) == ledger_before
        assert await _get_balance(client, headers, employee_id) == "17.00"
        assert (await _application(client, headers, leave["id"]))["total_days"] == "3.00"
    finally:
        await _cleanup_all(company_id, user_id)


async def test_two_hr_users_applying_the_same_preview_change_the_leave_once(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, sandwich_rule_enabled=False)
        employee_id = ctx["employee"]["id"]
        leave = await _leave_on(client, headers, ctx, "2026-09-08", "2026-09-10")
        await _set_weekly_off(client, headers, (2, 6))
        preview = await _preview(client, headers)
        ledger_before = await _ledger(company_id)

        first, second = await asyncio.gather(
            _apply_raw(client, headers, preview["digest"]),
            _apply_raw(client, headers, preview["digest"]),
        )

        assert first.status_code == 200 and second.status_code == 200, (first.text, second.text)
        outcomes = sorted([first.json()["data"]["noop"], second.json()["data"]["noop"]])
        assert outcomes == [False, True]  # one did the work, the other found nothing left
        assert await _get_balance(client, headers, employee_id) == "18.00"
        ledger_after = await _ledger(company_id)
        assert ledger_after[len(ledger_before) :] == [("ADJUSTMENT", "1.00")]  # refunded once
        assert (await _application(client, headers, leave["id"]))["total_days"] == "2.00"
        runs = await _sql(
            company_id,
            "SELECT count(*) FROM leave_application_action WHERE company_id = :cid "
            "AND action = 'CALENDAR_RECONCILED'",
        )
        assert runs[0][0] == 1
    finally:
        await _cleanup_all(company_id, user_id)


async def test_only_company_wide_leave_balance_holders_may_reconcile(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, sandwich_rule_enabled=False)
        await _leave_on(client, headers, ctx, "2026-09-08", "2026-09-10")
        await _set_weekly_off(client, headers, (2, 6))
        ledger_before = await _ledger(company_id)

        no_permission, _ = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=["LEAVE.BALANCE_VIEW"], data_scope="COMPANY"
        )
        team_only, _ = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[LEAVE_BALANCE_ADJUST],
            data_scope="SELF",
            caller_employee_id=UUID(ctx["employee"]["id"]),
        )
        for who in (no_permission, team_only):
            denied = await client.post(
                "/v1/leave-reconciliation/preview", headers=who, json=_WINDOW
            )
            assert denied.status_code == 403, denied.text
            applied = await _apply_raw(client, who, "a" * 64)
            assert applied.status_code == 403, applied.text
        assert await _ledger(company_id) == ledger_before

        # The window is bounded.
        too_wide = await client.post(
            "/v1/leave-reconciliation/preview",
            headers=headers,
            json={"date_from": "2020-01-01", "date_to": "2026-09-30"},
        )
        assert too_wide.status_code == 422, too_wide.text
    finally:
        await _cleanup_all(company_id, user_id)
        await _cleanup_scoped_users()
