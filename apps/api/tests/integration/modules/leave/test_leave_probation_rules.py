"""Integration tests for probation-based leave rules (LEAVE_DECISION_LOG.md LD-18, client spec
§9).

Reuses `_setup_full`/`_submit`/`_create_employee`/`_create_employment`/`_create_legal_entity`/
`_create_leave_type`/`_setup_calendar`/`_setup_leave_policy`/`_register_tenant`/`_cleanup`/
`_teardown` from `test_leave_application.py` — the same cross-file reuse pattern every other
Leave test file in this suite already established.

`_set_employee_status` below sets `Employee.status` directly via SQL — this predates the minimal
Employee confirmation feature and is kept here to test these flags in isolation from that
feature's own transition logic. As of that feature, `Employee.status` genuinely does reach
`PROBATION` organically too: `EmploymentService.create_employment` auto-transitions
`PRE_JOINING` -> `PROBATION` on joining, and `POST /employees/{id}/confirm` transitions
`PROBATION` -> `ACTIVE` — see `test_confirm_unblocks_probation_restricted_leave_type` below for
the real (no-SQL-hack) end-to-end proof, and
`tests/integration/modules/employee/test_employee_confirmation.py` for that feature's own tests.
"""

from datetime import date
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.leave.test_leave_application import (
    _cleanup,
    _create_employee,
    _create_employment,
    _create_leave_type,
    _create_legal_entity,
    _register_tenant,
    _setup_calendar,
    _setup_full,
    _setup_leave_policy,
    _submit,
    _teardown,
)

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.leave.service import LeaveAccrualService

pytestmark = pytest.mark.asyncio


async def _set_employee_status(*, company_id: UUID, employee_id: str, status: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        await session.execute(
            text("UPDATE employee SET status = :status WHERE id = :eid"),
            {"status": status, "eid": employee_id},
        )
        await session.commit()


async def test_default_allows_submission_for_probation_employee(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, approval_chain="AUTO")
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]
        await _set_employee_status(
            company_id=company_id, employee_id=employee_id, status="PROBATION"
        )

        submitted = await _submit(
            client, headers, employee_id=employee_id, leave_type_id=leave_type_id
        )
        assert submitted.status_code == 201, submitted.text
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_allowed_during_probation_false_blocks_probation_employee(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(
            client, headers, approval_chain="AUTO", allowed_during_probation=False
        )
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]
        await _set_employee_status(
            company_id=company_id, employee_id=employee_id, status="PROBATION"
        )

        submitted = await _submit(
            client, headers, employee_id=employee_id, leave_type_id=leave_type_id
        )
        assert submitted.status_code == 422, submitted.text
        assert (
            submitted.json()["error"]["code"] == "LEAVE_APPLICATION_NOT_ALLOWED_DURING_PROBATION"
        )
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_allowed_during_probation_false_does_not_block_active_employee(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(
            client, headers, approval_chain="AUTO", allowed_during_probation=False
        )
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]
        await _set_employee_status(company_id=company_id, employee_id=employee_id, status="ACTIVE")

        submitted = await _submit(
            client, headers, employee_id=employee_id, leave_type_id=leave_type_id
        )
        assert submitted.status_code == 201, submitted.text
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_accrue_during_probation_false_skips_probation_but_not_active(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        legal_entity = await _create_legal_entity(client, headers)
        await _setup_calendar(client, headers)
        leave_type = await _create_leave_type(client, headers)
        await _setup_leave_policy(
            client,
            headers,
            leave_type_id=leave_type["id"],
            approval_chain="AUTO",
            accrual_frequency="MONTHLY",
            accrual_rate_per_cycle="1.50",
            accrue_during_probation=False,
        )

        probation_employee = await _create_employee(client, headers, first_name="Probationer")
        await _create_employment(
            client,
            headers,
            employee_id=probation_employee["id"],
            legal_entity_id=legal_entity["id"],
            joining_date="2025-01-01",
        )
        await _set_employee_status(
            company_id=company_id, employee_id=probation_employee["id"], status="PROBATION"
        )

        active_employee = await _create_employee(client, headers, first_name="Confirmed")
        await _create_employment(
            client,
            headers,
            employee_id=active_employee["id"],
            legal_entity_id=legal_entity["id"],
            joining_date="2025-01-01",
        )
        await _set_employee_status(
            company_id=company_id, employee_id=active_employee["id"], status="ACTIVE"
        )

        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, str(company_id))
            written = await LeaveAccrualService(session).run_for_company(
                company_id, as_of=date(2026, 3, 1)
            )
            await session.commit()
        assert written == 1

        async def _balance(employee_id: str) -> str:
            response = await client.get(
                "/v1/leave-balances", headers=headers, params={"employee_id": employee_id}
            )
            assert response.status_code == 200, response.text
            return str(response.json()["data"][0]["balance"])

        # No ledger row was ever written for the probation employee (accrual skipped
        # entirely) — COALESCE's zero-row fallback serializes as a plain "0", not "0.00".
        assert await _balance(probation_employee["id"]) == "0"
        assert await _balance(active_employee["id"]) == "1.50"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_confirm_unblocks_probation_restricted_leave_type(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The real, no-SQL-hack end-to-end proof: `EmploymentService.create_employment` puts a new
    employee into genuine `PROBATION` on its own; `allowed_during_probation=False` blocks their
    submission exactly like the SQL-hack test above; `POST /employees/{id}/confirm` (the actual
    Employee confirmation action) moves them to `ACTIVE`; the identical submission then
    succeeds — proving the unblock, not just the flag's own isolated logic."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(
            client, headers, approval_chain="AUTO", allowed_during_probation=False
        )
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]

        employee = await client.get(f"/v1/employees/{employee_id}", headers=headers)
        assert employee.json()["data"]["status"] == "PROBATION"

        blocked = await _submit(
            client, headers, employee_id=employee_id, leave_type_id=leave_type_id
        )
        assert blocked.status_code == 422, blocked.text
        assert (
            blocked.json()["error"]["code"] == "LEAVE_APPLICATION_NOT_ALLOWED_DURING_PROBATION"
        )

        confirmed = await client.post(
            f"/v1/employees/{employee_id}/confirm",
            headers={**headers, "If-Match": str(employee.json()["data"]["version"])},
            json={},
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["data"]["status"] == "ACTIVE"

        allowed = await _submit(
            client, headers, employee_id=employee_id, leave_type_id=leave_type_id
        )
        assert allowed.status_code == 201, allowed.text
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
