"""Comp-off across the employee lifecycle: a credit survives termination and rehire untouched,
the credit sweep never double-credits, and the expiry sweep still expires it exactly once."""

from datetime import date

import pytest
from httpx import AsyncClient
from tests.integration.modules.attendance.test_attendance_day import (
    _build_wired_employee,
    _cleanup_attendance_day,
    _register_tenant,
)
from tests.integration.modules.attendance.test_attendance_edge_cases import _terminate
from tests.integration.modules.attendance.test_overtime_record import (
    _cleanup_overtime,
    _create_overtime_policy,
    _ot_calculate_day,
)
from tests.integration.modules.leave.test_leave_comp_off import (
    _create_leave_type,
    _credit,
    _expire,
    _get_balance,
    _teardown_leave,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

pytestmark = pytest.mark.asyncio


async def test_comp_off_credit_survives_termination_and_rehire_and_expires_once(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = str(wired["employee"]["id"])
        await _create_overtime_policy(
            client,
            headers,
            approval_chain="AUTO",
            comp_off_instead_of_pay=True,
            comp_off_day_length_minutes=480,
            comp_off_expiry_days=30,
        )
        await _ot_calculate_day(client, headers, employee_id=employee_id)
        await _create_leave_type(client, headers, is_comp_off=True)

        assert await _credit(company_id) == 1
        assert await _get_balance(client, headers, employee_id) == "0.13"

        # leaves: the earned balance stays on the ledger, and re-running the credit sweep for a
        # terminated employee neither re-credits nor removes anything
        await _terminate(client, headers, employee_id, "2026-08-11")
        assert await _credit(company_id) == 0
        assert await _get_balance(client, headers, employee_id) == "0.13"

        # rehired: same ledger, same balance
        entity_id = (
            await client.get(f"/v1/employees/{employee_id}/employments", headers=headers)
        ).json()["data"][0]["legal_entity_id"]
        rehire = await client.post(
            f"/v1/employees/{employee_id}/employments",
            headers=headers,
            json={"legal_entity_id": entity_id, "joining_date": "2026-09-01"},
        )
        assert rehire.status_code == 201, rehire.text
        assert await _credit(company_id) == 0
        assert await _get_balance(client, headers, employee_id) == "0.13"

        # not yet due (earned 2026-08-10, 30 days): nothing expires; once due, exactly once
        assert await _expire(company_id, as_of=date(2026, 9, 8)) == 0
        assert await _expire(company_id, as_of=date(2026, 9, 10)) == 1
        assert await _expire(company_id, as_of=date(2026, 9, 11)) == 0
        assert await _get_balance(client, headers, employee_id) == "0.00"
    finally:
        await _teardown_leave(company_id=company_id)
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
