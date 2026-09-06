"""Integration tests for encashment detail (LEAVE_DECISION_LOG.md LD-19, client spec §12).

Reuses `_setup_full`/`_get_balance`/`_register_tenant`/`_cleanup`/`_teardown` from
`test_leave_application.py` — the same cross-file reuse pattern every other Leave test file in
this suite already established.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from tests.integration.modules.leave.test_leave_application import (
    _cleanup,
    _get_balance,
    _register_tenant,
    _setup_full,
    _teardown,
)

pytestmark = pytest.mark.asyncio


async def _encash(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    employee_id: str,
    leave_type_id: str,
    days: str,
    effective_date: str = "2026-09-08",
) -> Any:
    return await client.post(
        "/v1/leave-ledger/encashments",
        headers=headers,
        json={
            "employee_id": employee_id,
            "leave_type_id": leave_type_id,
            "days": days,
            "effective_date": effective_date,
            "reason": "test encashment",
        },
    )


async def test_encashment_writes_entry_and_debits_balance(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(
            client, headers, approval_chain="AUTO", balance="10.00", encashment_allowed=True
        )
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]

        response = await _encash(
            client, headers, employee_id=employee_id, leave_type_id=leave_type_id, days="3.00"
        )
        assert response.status_code == 201, response.text
        data = response.json()["data"]
        assert data["entry_type"] == "ENCASHMENT"
        assert data["amount"] == "-3.00"

        assert await _get_balance(client, headers, employee_id) == "7.00"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_encashment_blocked_when_not_allowed(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        # encashment_allowed defaults to False.
        ctx = await _setup_full(client, headers, approval_chain="AUTO", balance="10.00")
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]

        response = await _encash(
            client, headers, employee_id=employee_id, leave_type_id=leave_type_id, days="3.00"
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "LEAVE_ENCASHMENT_NOT_ALLOWED"
        assert await _get_balance(client, headers, employee_id) == "10.00"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_encashment_blocked_exceeding_max_days(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(
            client,
            headers,
            approval_chain="AUTO",
            balance="10.00",
            encashment_allowed=True,
            max_encashment_days="2.00",
        )
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]

        response = await _encash(
            client, headers, employee_id=employee_id, leave_type_id=leave_type_id, days="3.00"
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "LEAVE_ENCASHMENT_MAX_DAYS_EXCEEDED"

        allowed = await _encash(
            client, headers, employee_id=employee_id, leave_type_id=leave_type_id, days="2.00"
        )
        assert allowed.status_code == 201, allowed.text
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_encashment_blocked_violating_minimum_balance(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(
            client,
            headers,
            approval_chain="AUTO",
            balance="10.00",
            encashment_allowed=True,
            min_balance_after_encashment="5.00",
        )
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]

        # 10.00 - 6.00 = 4.00 < 5.00 minimum -> blocked.
        blocked = await _encash(
            client, headers, employee_id=employee_id, leave_type_id=leave_type_id, days="6.00"
        )
        assert blocked.status_code == 422, blocked.text
        assert blocked.json()["error"]["code"] == "LEAVE_ENCASHMENT_MINIMUM_BALANCE_VIOLATION"

        # 10.00 - 5.00 = 5.00, exactly the minimum -> allowed.
        allowed = await _encash(
            client, headers, employee_id=employee_id, leave_type_id=leave_type_id, days="5.00"
        )
        assert allowed.status_code == 201, allowed.text
        assert await _get_balance(client, headers, employee_id) == "5.00"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_encashment_config_round_trips_on_policy_version(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(
            client,
            headers,
            approval_chain="AUTO",
            encashment_allowed=True,
            max_encashment_days="10.00",
            min_balance_after_encashment="5.00",
            encashment_frequency="ANNUAL",
            encashment_calculation_basis="BASIC_PAY_PER_DAY",
        )
        policy_id = ctx["policy"]["id"]

        versions = await client.get(f"/v1/leave-policies/{policy_id}/versions", headers=headers)
        assert versions.status_code == 200, versions.text
        version = versions.json()["data"][0]
        assert version["max_encashment_days"] == "10.00"
        assert version["min_balance_after_encashment"] == "5.00"
        assert version["encashment_frequency"] == "ANNUAL"
        assert version["encashment_calculation_basis"] == "BASIC_PAY_PER_DAY"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
