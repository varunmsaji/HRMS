"""Integration tests for Leave module L5 — the comp-off credit + expiry sweep
(`LeaveCompOffService`, LEAVE_DECISION_LOG.md LD-07/LD-14).

Tested at the service layer directly against real `OvertimeRecord` rows produced through the
actual attendance detection pipeline (punch -> calculate -> auto-approve), reusing
`_build_wired_employee`/`_ot_calculate_day`/`_create_overtime_policy`/`_get_overtime_record_for_
day` from `test_overtime_record.py` — the same cross-file reuse pattern `test_leave_accrual.py`
already established for its own dependencies. `credit_company`/`expire_company` are the same
coroutines `leave/tasks.py`'s Celery tasks call via `asyncio.run`, so exercising them directly is
exercising the real code path minus the Celery/asyncio bridge itself.
"""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.test_attendance_day import (
    _build_wired_employee,
    _cleanup_attendance_day,
    _register_tenant,
)
from tests.integration.modules.attendance.test_leave_projection import (
    _cleanup_leave_projection,
    _sync,
)
from tests.integration.modules.attendance.test_overtime_record import (
    _cleanup_overtime,
    _create_overtime_policy,
    _get_overtime_record_for_day,
    _ot_calculate_day,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.leave.service import LeaveCompOffService

pytestmark = pytest.mark.asyncio


async def _create_leave_type(
    client: AsyncClient, headers: dict[str, str], **extra: Any
) -> dict[str, Any]:
    payload = {"code": "COMP_OFF", "name": "Compensatory Off", **extra}
    response = await client.post("/v1/leave-types", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _teardown_leave(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        for table in ("leave_ledger", "leave_type"):
            await session.execute(
                text(f"DELETE FROM {table} WHERE company_id = :cid"), {"cid": str(company_id)}
            )
        await session.commit()


async def _credit(company_id: UUID) -> int:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        written = await LeaveCompOffService(session).credit_company(company_id)
        await session.commit()
        return written


async def _expire(company_id: UUID, *, as_of: date) -> int:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        expired = await LeaveCompOffService(session).expire_company(company_id, as_of=as_of)
        await session.commit()
        return expired


async def _get_balance(client: AsyncClient, headers: dict[str, str], employee_id: str) -> str:
    response = await client.get(
        "/v1/leave-balances", headers=headers, params={"employee_id": employee_id}
    )
    assert response.status_code == 200, response.text
    return str(response.json()["data"][0]["balance"])


async def _adjust(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    employee_id: str,
    leave_type_id: str,
    amount: str,
) -> None:
    response = await client.post(
        "/v1/leave-ledger/adjustments",
        headers=headers,
        json={
            "employee_id": employee_id,
            "leave_type_id": leave_type_id,
            "amount": amount,
            "effective_date": "2026-08-10",
            "reason": "test setup",
        },
    )
    assert response.status_code == 201, response.text


async def test_credit_converts_minutes_to_days_and_is_idempotent(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _create_overtime_policy(
            client,
            headers,
            approval_chain="AUTO",
            comp_off_instead_of_pay=True,
            comp_off_expiry_days=90,
            comp_off_day_length_minutes=480,
        )
        await _ot_calculate_day(client, headers, employee_id=employee_id)
        record = await _get_overtime_record_for_day(
            client, headers, employee_id=employee_id, day="2026-08-10"
        )
        assert record["comp_off_minutes"] == 60

        leave_type = await _create_leave_type(client, headers, is_comp_off=True)

        written = await _credit(company_id)
        assert written == 1
        # 60 minutes / 480 minutes-per-day = 0.125 days.
        assert await _get_balance(client, headers, employee_id) == "0.13"

        # Re-run: idempotent, keyed on reference_id=overtime_record_id.
        again = await _credit(company_id)
        assert again == 0
        assert await _get_balance(client, headers, employee_id) == "0.13"
        assert leave_type["is_comp_off"] is True
    finally:
        await _teardown_leave(company_id=company_id)
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_credit_skipped_when_no_comp_off_type_designated(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _create_overtime_policy(
            client,
            headers,
            approval_chain="AUTO",
            comp_off_instead_of_pay=True,
            comp_off_expiry_days=90,
            comp_off_day_length_minutes=480,
        )
        await _ot_calculate_day(client, headers, employee_id=employee_id)
        # No LeaveType marked is_comp_off=True anywhere in this company.
        written = await _credit(company_id)
        assert written == 0
    finally:
        await _teardown_leave(company_id=company_id)
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_day_length_and_expiry_default_from_the_shift_when_not_configured(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Decision 13 (`docs/audits/PAYROLL_BUSINESS_DECISIONS.md`) — with neither
    `comp_off_day_length_minutes` nor `comp_off_expiry_days` set, one comp-off day is the
    shift's scheduled minutes that day, and the comp-off expires after 60 days. Before, such a
    policy credited nothing and never expired."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _create_overtime_policy(
            client, headers, approval_chain="AUTO", comp_off_instead_of_pay=True
        )
        day = await _ot_calculate_day(client, headers, employee_id=employee_id)
        record = await _get_overtime_record_for_day(
            client, headers, employee_id=employee_id, day="2026-08-10"
        )
        assert record["comp_off_minutes"] == 60
        assert record["comp_off_expiry_date"] == "2026-10-09"
        await _create_leave_type(client, headers, is_comp_off=True)

        assert await _credit(company_id) == 1
        expected = (Decimal(60) / Decimal(day["scheduled_minutes"])).quantize(Decimal("0.01"))
        assert await _get_balance(client, headers, employee_id) == str(expected)
    finally:
        await _teardown_leave(company_id=company_id)
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_expiry_offsets_full_amount_when_balance_still_covers_it(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _create_overtime_policy(
            client,
            headers,
            approval_chain="AUTO",
            comp_off_instead_of_pay=True,
            comp_off_expiry_days=90,
            comp_off_day_length_minutes=480,
        )
        await _ot_calculate_day(client, headers, employee_id=employee_id)
        await _create_leave_type(client, headers, is_comp_off=True)
        assert await _credit(company_id) == 1
        assert await _get_balance(client, headers, employee_id) == "0.13"

        # Expiry is 2026-08-10 + 90 days = 2026-11-08. Before that date: nothing expires.
        assert await _expire(company_id, as_of=date(2026, 11, 7)) == 0
        assert await _get_balance(client, headers, employee_id) == "0.13"

        # On/after expiry, balance still fully covers the credit -> offset in full.
        assert await _expire(company_id, as_of=date(2026, 11, 8)) == 1
        assert await _get_balance(client, headers, employee_id) == "0.00"

        # Idempotent: re-running the sweep does not double-offset.
        assert await _expire(company_id, as_of=date(2026, 11, 8)) == 0
        assert await _get_balance(client, headers, employee_id) == "0.00"
    finally:
        await _teardown_leave(company_id=company_id)
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_expiry_skipped_when_balance_already_spent_below_credit_amount(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _create_overtime_policy(
            client,
            headers,
            approval_chain="AUTO",
            comp_off_instead_of_pay=True,
            comp_off_expiry_days=90,
            comp_off_day_length_minutes=480,
        )
        await _ot_calculate_day(client, headers, employee_id=employee_id)
        leave_type = await _create_leave_type(client, headers, is_comp_off=True)
        assert await _credit(company_id) == 1
        assert await _get_balance(client, headers, employee_id) == "0.13"

        # Employee has since spent it down below the credit's original amount.
        await _adjust(
            client,
            headers,
            employee_id=employee_id,
            leave_type_id=leave_type["id"],
            amount="-0.10",
        )
        assert await _get_balance(client, headers, employee_id) == "0.03"

        # Past expiry, but balance (0.03) no longer covers the credit (0.13) -> never expired,
        # never drives the balance negative.
        assert await _expire(company_id, as_of=date(2026, 11, 8)) == 0
        assert await _get_balance(client, headers, employee_id) == "0.03"
    finally:
        await _teardown_leave(company_id=company_id)
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def _delete_ledger(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        await session.execute(
            text("DELETE FROM leave_ledger WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.commit()


async def _comp_off_day_with_credit_policy(
    client: AsyncClient, headers: dict[str, str]
) -> tuple[str, str]:
    """One employee with 60 comp-off minutes on 2026-08-10, at 60 minutes to the day, so one credit
    is exactly 1.00. Returns the employee id and the comp-off leave type id."""
    wired = await _build_wired_employee(client, headers)
    employee_id = wired["employee"]["id"]
    await _create_overtime_policy(
        client,
        headers,
        approval_chain="AUTO",
        comp_off_instead_of_pay=True,
        comp_off_expiry_days=90,
        comp_off_day_length_minutes=60,
    )
    await _ot_calculate_day(client, headers, employee_id=employee_id)
    leave_type = await _create_leave_type(client, headers, is_comp_off=True)
    return employee_id, leave_type["id"]


async def _cancel_leave(client: AsyncClient, headers: dict[str, str], synced: Any) -> None:
    cancelled = await client.post(
        f"/v1/leave-projections/{synced.json()['data']['id']}/cancel",
        headers={**headers, "If-Match": str(synced.json()["data"]["version"])},
        json={"reason": "Worked the day after all"},
    )
    assert cancelled.status_code == 200, cancelled.text


async def test_credit_is_reversed_by_later_leave_and_restored_when_it_is_cancelled(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """D-8 — leave approved after the credit takes it back, and only once. Cancelling the leave
    gives it back, and only once."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id, _ = await _comp_off_day_with_credit_policy(client, headers)
        assert await _credit(company_id) == 1
        assert Decimal(await _get_balance(client, headers, employee_id)) == Decimal("1.00")

        synced = await _sync(client, headers, employee_id=employee_id, fraction="1.00")
        assert synced.status_code == 201, synced.text
        await _credit(company_id)
        assert Decimal(await _get_balance(client, headers, employee_id)) == Decimal("0.00")
        await _credit(company_id)
        assert Decimal(await _get_balance(client, headers, employee_id)) == Decimal("0.00")

        await _cancel_leave(client, headers, synced)
        await _credit(company_id)
        assert Decimal(await _get_balance(client, headers, employee_id)) == Decimal("1.00")
        await _credit(company_id)
        assert Decimal(await _get_balance(client, headers, employee_id)) == Decimal("1.00")
    finally:
        await _delete_ledger(company_id=company_id)
        await _cleanup_leave_projection(company_id=company_id)
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_nothing_is_credited_while_the_day_is_on_leave(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id, _ = await _comp_off_day_with_credit_policy(client, headers)
        synced = await _sync(client, headers, employee_id=employee_id, fraction="1.00")
        assert synced.status_code == 201, synced.text

        assert await _credit(company_id) == 0
        assert Decimal(await _get_balance(client, headers, employee_id)) == Decimal("0.00")

        await _cancel_leave(client, headers, synced)
        assert await _credit(company_id) == 1
        assert Decimal(await _get_balance(client, headers, employee_id)) == Decimal("1.00")
    finally:
        await _delete_ledger(company_id=company_id)
        await _cleanup_leave_projection(company_id=company_id)
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_reversal_never_drives_the_balance_negative_and_retries(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The credit was already spent: nothing is taken yet, and a later sweep takes it once the
    balance covers it."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id, leave_type_id = await _comp_off_day_with_credit_policy(client, headers)
        await _credit(company_id)
        await _adjust(
            client, headers, employee_id=employee_id, leave_type_id=leave_type_id, amount="-1.00"
        )
        synced = await _sync(client, headers, employee_id=employee_id, fraction="1.00")
        assert synced.status_code == 201, synced.text

        await _credit(company_id)
        assert Decimal(await _get_balance(client, headers, employee_id)) == Decimal("0.00")

        await _adjust(
            client, headers, employee_id=employee_id, leave_type_id=leave_type_id, amount="1.00"
        )
        await _credit(company_id)
        assert Decimal(await _get_balance(client, headers, employee_id)) == Decimal("0.00")
    finally:
        await _delete_ledger(company_id=company_id)
        await _cleanup_leave_projection(company_id=company_id)
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_expired_credit_is_not_reversed_again(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id, leave_type_id = await _comp_off_day_with_credit_policy(client, headers)
        await _credit(company_id)
        assert await _expire(company_id, as_of=date(2027, 1, 1)) == 1
        await _adjust(
            client, headers, employee_id=employee_id, leave_type_id=leave_type_id, amount="1.00"
        )
        synced = await _sync(client, headers, employee_id=employee_id, fraction="1.00")
        assert synced.status_code == 201, synced.text

        await _credit(company_id)
        assert Decimal(await _get_balance(client, headers, employee_id)) == Decimal("1.00")
    finally:
        await _delete_ledger(company_id=company_id)
        await _cleanup_leave_projection(company_id=company_id)
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_only_one_comp_off_leave_type_allowed_per_company(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        await _create_leave_type(client, headers, code="COMP_OFF_1", is_comp_off=True)
        response = await client.post(
            "/v1/leave-types",
            headers=headers,
            json={"code": "COMP_OFF_2", "name": "Comp Off Two", "is_comp_off": True},
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "LEAVE_TYPE_COMP_OFF_ALREADY_EXISTS"
    finally:
        await _teardown_leave(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
