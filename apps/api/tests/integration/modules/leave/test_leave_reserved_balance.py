"""Integration tests for Reserved/Pending Balance (LEAVE_DECISION_LOG.md LD-15).

Reuses `_setup_full`/`_submit`/`_get_balance`/`_teardown`/`_register_tenant` from
`test_leave_application.py` — the same cross-file reuse pattern `test_leave_accrual.py` and
`test_leave_comp_off.py` already established. `approval_chain="HR"` throughout: it needs no
manager resolution and leaves a submitted application in `SUBMITTED` status indefinitely (unlike
`AUTO`, which resolves immediately), which is exactly the pending state these tests exercise.

`total_days` is never a client input — it's computed server-side from the date range against the
Sunday-off calendar `_setup_calendar` assigns. Every date range used below is Monday-Friday only
(no Sunday), so N consecutive days = N total_days exactly.
"""

import pytest
from httpx import AsyncClient
from tests.integration.modules.leave.test_leave_application import (
    _cleanup,
    _get_balance,
    _register_tenant,
    _setup_full,
    _submit,
    _teardown,
)

pytestmark = pytest.mark.asyncio


async def _get_reserved(client: AsyncClient, headers: dict[str, str], employee_id: str) -> str:
    response = await client.get(
        "/v1/leave-balances", headers=headers, params={"employee_id": employee_id}
    )
    assert response.status_code == 200, response.text
    return str(response.json()["data"][0]["reserved_balance"])


async def test_reserved_balance_shown_but_not_enforced_by_default(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        # reserve_balance_on_submission left at its default (False) — LD-15's unchanged behavior.
        ctx = await _setup_full(client, headers, approval_chain="HR", balance="5.00")
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]

        # Tue-Thu, 3 working days.
        first = await _submit(
            client,
            headers,
            employee_id=employee_id,
            leave_type_id=leave_type_id,
            start_date="2026-09-08",
            end_date="2026-09-10",
        )
        assert first.status_code == 201, first.text
        assert first.json()["data"]["total_days"] == "3.00"

        # Ledger-derived balance is untouched by a pending application...
        assert await _get_balance(client, headers, employee_id) == "5.00"
        # ...but the reserved figure reflects it, purely informationally.
        assert await _get_reserved(client, headers, employee_id) == "3.00"

        # A second application (Mon-Thu, 4 working days) that, combined with the first, would
        # exceed the balance still succeeds — reservation isn't enforced unless turned on.
        second = await _submit(
            client,
            headers,
            employee_id=employee_id,
            leave_type_id=leave_type_id,
            start_date="2026-09-14",
            end_date="2026-09-17",
        )
        assert second.status_code == 201, second.text
        assert second.json()["data"]["total_days"] == "4.00"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_reservation_enabled_blocks_pending_plus_new_over_balance(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(
            client,
            headers,
            approval_chain="HR",
            balance="5.00",
            reserve_balance_on_submission=True,
        )
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]

        # Tue-Thu, 3 working days.
        first = await _submit(
            client,
            headers,
            employee_id=employee_id,
            leave_type_id=leave_type_id,
            start_date="2026-09-08",
            end_date="2026-09-10",
        )
        assert first.status_code == 201, first.text
        assert await _get_reserved(client, headers, employee_id) == "3.00"

        # 3.00 already reserved + 3.00 new (Mon-Wed) > 5.00 balance -> rejected.
        over = await _submit(
            client,
            headers,
            employee_id=employee_id,
            leave_type_id=leave_type_id,
            start_date="2026-09-14",
            end_date="2026-09-16",
        )
        assert over.status_code == 422, over.text
        assert over.json()["error"]["code"] == "LEAVE_APPLICATION_INSUFFICIENT_BALANCE"

        # 3.00 reserved + 2.00 new (Thu-Fri) == 5.00 balance exactly -> allowed.
        exact = await _submit(
            client,
            headers,
            employee_id=employee_id,
            leave_type_id=leave_type_id,
            start_date="2026-09-17",
            end_date="2026-09-18",
        )
        assert exact.status_code == 201, exact.text
        assert await _get_reserved(client, headers, employee_id) == "5.00"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_reserved_balance_clears_on_reject_and_cancel(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(
            client,
            headers,
            approval_chain="HR",
            balance="3.00",
            reserve_balance_on_submission=True,
        )
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]

        # Tue-Thu, 3 working days.
        rejected_app = await _submit(
            client,
            headers,
            employee_id=employee_id,
            leave_type_id=leave_type_id,
            start_date="2026-09-08",
            end_date="2026-09-10",
        )
        rejected_id = rejected_app.json()["data"]["id"]
        assert await _get_reserved(client, headers, employee_id) == "3.00"

        rejected = await client.post(
            f"/v1/leave-applications/{rejected_id}/reject",
            headers={**headers, "If-Match": "1"},
            json={"rejection_reason": "test"},
        )
        assert rejected.status_code == 200, rejected.text
        assert await _get_reserved(client, headers, employee_id) == "0.00"

        # Reservation cleared -> the same 3-day range can be submitted again.
        cancelled_app = await _submit(
            client,
            headers,
            employee_id=employee_id,
            leave_type_id=leave_type_id,
            start_date="2026-09-08",
            end_date="2026-09-10",
        )
        cancelled_id = cancelled_app.json()["data"]["id"]
        assert cancelled_app.status_code == 201, cancelled_app.text
        assert await _get_reserved(client, headers, employee_id) == "3.00"

        cancelled = await client.post(
            f"/v1/leave-applications/{cancelled_id}/cancel",
            headers={**headers, "If-Match": "1"},
        )
        assert cancelled.status_code == 200, cancelled.text
        assert await _get_reserved(client, headers, employee_id) == "0.00"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
