"""LM-11 - a leave request waiting on a leave advisory lock gives up with a retryable "busy"
answer instead of queuing indefinitely behind another transaction, and succeeds when retried."""

import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from tests.integration.modules.leave.test_leave_application import (
    _cleanup,
    _get_balance,
    _register_tenant,
    _setup_full,
    _teardown,
)
from tests.integration.modules.leave.test_leave_encashment import _encash

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.leave.repository import LeaveLedgerRepository

pytestmark = pytest.mark.asyncio


async def test_a_blocked_balance_lock_times_out_as_database_busy_and_the_retry_succeeds(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(
            client, headers, approval_chain="AUTO", balance="10.00", encashment_allowed=True
        )
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]

        holder = get_session_factory()()
        try:
            await set_rls_company_id(holder, str(company_id))
            from uuid import UUID

            await LeaveLedgerRepository().lock_balance(
                holder,
                company_id=company_id,
                employee_id=UUID(employee_id),
                leave_type_id=UUID(leave_type_id),
            )
            with patch(
                "hrms.modules.leave.repository.get_settings",
                return_value=SimpleNamespace(leave_lock_wait_ms=400),
            ):
                started = time.monotonic()
                busy = await _encash(
                    client,
                    headers,
                    employee_id=employee_id,
                    leave_type_id=leave_type_id,
                    days="1.00",
                )
                waited = time.monotonic() - started
            assert busy.status_code == 503, busy.text
            assert busy.json()["error"]["code"] == "DATABASE_BUSY"
            assert busy.headers.get("Retry-After") == "2"
            assert 0.3 < waited < 3.0, waited  # bounded, not indefinite
            assert await _get_balance(client, headers, employee_id) == "10.00"
        finally:
            await holder.rollback()
            await holder.close()

        retried = await _encash(
            client, headers, employee_id=employee_id, leave_type_id=leave_type_id, days="1.00"
        )
        assert retried.status_code == 201, retried.text
        assert await _get_balance(client, headers, employee_id) == "9.00"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
