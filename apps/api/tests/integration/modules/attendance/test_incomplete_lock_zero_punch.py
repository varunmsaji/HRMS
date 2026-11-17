"""H-02 and H-07 (owner decisions), through the real API: what the period lock does with a day that
is still incomplete.

* A day with NO punches at all (an expected working day, no leave / on-duty / regularization) is
  absent at lock, whatever `incomplete_at_lock_behaviour` says - `TREAT_PRESENT` never pays a
  no-show. `KEEP_INCOMPLETE` still blocks the close until HR resolves the day.
* A day with at least one punch (an IN-only day included) still follows the company's choice, so
  under `TREAT_PRESENT` it is paid in full, exactly as today.
* A half-day-leave day with no punch leaves the worked half PENDING until the lock; at lock it is
  absent whatever the setting. The leave half is settled on its own and never touched.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
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
from tests.integration.modules.attendance.test_attendance_rules_remediation import _calc
from tests.integration.modules.attendance.test_leave_projection import (
    _cleanup_leave_projection,
    _get_day,
    _sync,
)
from tests.integration.modules.attendance.test_shift_window import _sql
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.core.db.session import get_session_factory, set_rls_company_id

pytestmark = pytest.mark.asyncio

DAY = "2026-08-10"


async def _set_behaviour(company_id: Any, behaviour: str) -> None:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        await session.execute(
            text(
                "UPDATE attendance_policy_version SET incomplete_at_lock_behaviour = :b "
                "WHERE company_id = :cid"
            ),
            {"b": behaviour, "cid": str(company_id)},
        )
        await session.commit()


async def _finalize(client: AsyncClient, headers: dict[str, str]) -> tuple[Any, dict[str, Any]]:
    period = await _create_period(client, headers)
    response = await client.post(
        f"/v1/attendance-periods/{period['id']}/finalize",
        headers={**headers, "If-Match": "1"},
        json={},
    )
    return response, period


async def _cleanup_all(company_id: Any, user_id: Any) -> None:
    await _cleanup_attendance_period(company_id=company_id)
    await _cleanup_leave_projection(company_id=company_id)
    await _cleanup_attendance_day(company_id=company_id)
    await _cleanup(company_id=company_id, user_id=user_id)


async def _resolution_audit(company_id: Any) -> list[dict[str, Any]]:
    rows = await _sql(
        company_id,
        "SELECT after_json FROM audit_log WHERE company_id = :cid "
        "AND action = 'ATTENDANCE_INCOMPLETE_RESOLVED_AT_LOCK'",
    )
    import json

    days: list[dict[str, Any]] = []
    for (after,) in rows:
        payload = json.loads(after) if isinstance(after, str) else after
        days.extend(payload["resolved_days"])
    return days


# --- H-02: a day with no punches at all ---


@pytest.mark.parametrize("behaviour", ["TREAT_ABSENT", "TREAT_PRESENT"])
async def test_a_day_with_no_punches_is_absent_at_lock_whatever_the_setting(
    client: AsyncClient, seeded_plan_catalogue: None, behaviour: str
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = str(wired["employee"]["id"])
        await _set_behaviour(company_id, behaviour)
        before = await _calc(client, headers, employee_id, DAY)
        assert before["attendance_status"] == "INCOMPLETE"  # pending until the lock

        finalized, period = await _finalize(client, headers)
        assert finalized.status_code == 200, finalized.text
        locked = await _get_day(client, headers, employee_id=employee_id)
        assert locked["is_locked"] is True
        assert (locked["paid_day_fraction"], locked["lop_fraction"]) == ("0.00", "1.00")

        audited = (await _resolution_audit(company_id))[0]
        assert audited["zero_punch"] is True
        assert audited["configured_behaviour"] == behaviour
        assert audited["behaviour"] == "TREAT_ABSENT"  # what was applied
    finally:
        await _cleanup_all(company_id, user_id)


async def test_keep_incomplete_still_blocks_a_day_with_no_punches(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = str(wired["employee"]["id"])
        await _set_behaviour(company_id, "KEEP_INCOMPLETE")
        await _calc(client, headers, employee_id, DAY)
        refused, _ = await _finalize(client, headers)
        assert refused.status_code == 409, refused.text
        reasons = refused.json()["error"]["details"][0]["context"]["reasons"]
        assert any(r["code"] == "INCOMPLETE_ATTENDANCE" for r in reasons)
    finally:
        await _cleanup_all(company_id, user_id)


@pytest.mark.parametrize(
    ("behaviour", "paid", "lop"),
    [("TREAT_ABSENT", "0.00", "1.00"), ("TREAT_PRESENT", "1.00", "0.00")],
)
async def test_a_day_with_only_an_in_punch_follows_the_policy_as_it_did_before(
    client: AsyncClient, seeded_plan_catalogue: None, behaviour: str, paid: str, lop: str
) -> None:
    """The IN-only day is a day with a punch: under TREAT_PRESENT it is paid in full. HR is told so
    explicitly in the policy wording and the incomplete-day digest."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = str(wired["employee"]["id"])
        await _set_behaviour(company_id, behaviour)
        await _punch(client, headers, employee_id=employee_id, hour=9, minute=0, direction="IN")
        before = await _calc(client, headers, employee_id, DAY)
        assert before["attendance_status"] == "INCOMPLETE"
        finalized, _ = await _finalize(client, headers)
        assert finalized.status_code == 200, finalized.text
        locked = await _get_day(client, headers, employee_id=employee_id)
        assert (locked["paid_day_fraction"], locked["lop_fraction"]) == (paid, lop)
        audited = (await _resolution_audit(company_id))[0]
        assert audited["zero_punch"] is False
    finally:
        await _cleanup_all(company_id, user_id)


# --- H-07: half-day leave with no punches ---


@pytest.mark.parametrize("behaviour", ["TREAT_ABSENT", "TREAT_PRESENT"])
async def test_half_day_leave_with_no_punch_keeps_the_worked_half_pending_then_absent(
    client: AsyncClient, seeded_plan_catalogue: None, behaviour: str
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = str(wired["employee"]["id"])
        await _set_behaviour(company_id, behaviour)
        synced = await _sync(
            client, headers, employee_id=employee_id, fraction="0.50", half="FIRST"
        )
        assert synced.status_code == 201, synced.text

        pending = await _get_day(client, headers, employee_id=employee_id)
        # the worked half is pending, not lost: the leave half is paid, nothing is LOP yet
        assert pending["attendance_status"] == "INCOMPLETE"
        assert (pending["paid_day_fraction"], pending["lop_fraction"]) == ("0.50", "0.00")
        assert pending["leave_fraction"] == "0.50"

        finalized, period = await _finalize(client, headers)
        assert finalized.status_code == 200, finalized.text
        locked = await _get_day(client, headers, employee_id=employee_id)
        # the worked half is absent whatever the setting; the leave half is untouched
        assert (locked["paid_day_fraction"], locked["lop_fraction"]) == ("0.50", "0.50")
        assert locked["leave_fraction"] == "0.50"

        summary = await client.get(
            f"/v1/attendance-periods/{period['id']}/summary", headers=headers
        )
        row = next(r for r in summary.json()["data"] if r["employee_id"] == employee_id)
        assert row["leave_days"] == "0.50" and row["absent_days"] == "0.50"
        assert row["payable_days"] == "1.00" and row["lop_days"] == "0.50"
        audited = (await _resolution_audit(company_id))[0]
        assert audited["zero_punch"] is True and audited["behaviour"] == "TREAT_ABSENT"
    finally:
        await _cleanup_all(company_id, user_id)


async def test_unpaid_half_day_leave_with_no_punch_is_not_paid_by_treat_present(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = str(wired["employee"]["id"])
        await _set_behaviour(company_id, "TREAT_PRESENT")
        synced = await _sync(
            client, headers, employee_id=employee_id, fraction="0.50", half="FIRST", is_paid=False
        )
        assert synced.status_code == 201, synced.text
        finalized, _ = await _finalize(client, headers)
        assert finalized.status_code == 200, finalized.text
        locked = await _get_day(client, headers, employee_id=employee_id)
        assert (locked["paid_day_fraction"], locked["lop_fraction"]) == ("0.00", "1.00")
    finally:
        await _cleanup_all(company_id, user_id)


async def test_keep_incomplete_blocks_a_half_day_leave_day_with_no_punch(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = str(wired["employee"]["id"])
        await _set_behaviour(company_id, "KEEP_INCOMPLETE")
        synced = await _sync(
            client, headers, employee_id=employee_id, fraction="0.50", half="SECOND"
        )
        assert synced.status_code == 201, synced.text
        refused, _ = await _finalize(client, headers)
        assert refused.status_code == 409, refused.text
        reasons = refused.json()["error"]["details"][0]["context"]["reasons"]
        assert any(r["code"] == "INCOMPLETE_ATTENDANCE" for r in reasons)
    finally:
        await _cleanup_all(company_id, user_id)


async def test_half_day_leave_with_a_punch_follows_the_policy_as_before(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The existing rule for a half-day-leave day that has a punch is unchanged."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = str(wired["employee"]["id"])
        await _set_behaviour(company_id, "TREAT_PRESENT")
        await _punch(client, headers, employee_id=employee_id, hour=14, minute=0, direction="IN")
        synced = await _sync(
            client, headers, employee_id=employee_id, fraction="0.50", half="FIRST"
        )
        assert synced.status_code == 201, synced.text
        finalized, _ = await _finalize(client, headers)
        assert finalized.status_code == 200, finalized.text
        locked = await _get_day(client, headers, employee_id=employee_id)
        assert (locked["paid_day_fraction"], locked["lop_fraction"]) == ("1.00", "0.00")
    finally:
        await _cleanup_all(company_id, user_id)
