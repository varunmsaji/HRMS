"""Integration tests for Leave module L2 — `/v1/leave-ledger*`, `/v1/leave-balances`.

Covers the append-only ledger (ADR-0004/DEC-004): balance is always a derived `SUM(amount)`,
manual adjustments credit/debit correctly, validation (zero amount, unknown leave type), the raw
audit-trail list, and cross-tenant visibility (the `LEAVE.BALANCE_VIEW`/`LEAVE.BALANCE_VIEW_ALL`
combined-`DataScope` mechanism — `attendance/router.py`'s `cancel_regularization_request` union
shape applied here for the first time).
"""

from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.organisation.test_registration_flow import _cleanup, _register

from hrms.core.db.session import get_session_factory, set_rls_company_id


async def _register_tenant(
    client: AsyncClient, **overrides: Any
) -> tuple[dict[str, str], UUID, UUID | None]:
    response, company_id, user_id = await _register(client, **overrides)
    assert response.status_code == 201, response.text
    assert company_id is not None
    data = response.json()["data"]
    return (
        {
            "Authorization": f"Bearer {data['access_token']}",
            "X-Company-Id": str(company_id),
        },
        company_id,
        user_id,
    )


async def _create_employee(
    client: AsyncClient, headers: dict[str, str], first_name: str = "Asha"
) -> dict[str, Any]:
    response = await client.post("/v1/employees", headers=headers, json={"first_name": first_name})
    assert response.status_code == 201, response.text
    employee = dict(response.json()["data"])
    # Manual adjustments must be dated inside an employment spell (D5), so the employee is joined.
    entity = await client.post(
        "/v1/legal-entities", headers=headers, json={"name": f"Ledger LE {uuid4().hex[:8]}"}
    )
    assert entity.status_code == 201, entity.text
    employment = await client.post(
        f"/v1/employees/{employee['id']}/employments",
        headers=headers,
        json={"legal_entity_id": entity.json()["data"]["id"], "joining_date": "2025-01-01"},
    )
    assert employment.status_code == 201, employment.text
    return employee


async def _create_leave_type(
    client: AsyncClient, headers: dict[str, str], **extra: Any
) -> dict[str, Any]:
    payload = {"code": "CL", "name": "Casual Leave", **extra}
    response = await client.post("/v1/leave-types", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _teardown(*, company_id: UUID) -> None:
    """FK-safe: leave_ledger (child of leave_type/employee) before leave_type/employee, mirrors
    `test_rls_runtime_role.py::_teardown`'s ordering."""
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        for table in (
            "leave_ledger",
            "leave_type",
            "employment",
            "employee",
            "legal_entity",
            "number_series",
        ):
            await session.execute(
                text(f"DELETE FROM {table} WHERE company_id = :cid"), {"cid": str(company_id)}
            )
        await session.commit()


@pytest.mark.asyncio
async def test_balance_zero_before_any_entries(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        leave_type = await _create_leave_type(client, headers)

        balances = await client.get(
            "/v1/leave-balances", headers=headers, params={"employee_id": employee["id"]}
        )
        assert balances.status_code == 200, balances.text
        data = balances.json()["data"]
        assert len(data) == 1
        assert data[0]["leave_type_id"] == leave_type["id"]
        assert data[0]["balance"] == "0"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_adjustment_credits_and_debits_balance(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        leave_type = await _create_leave_type(client, headers)

        credit = await client.post(
            "/v1/leave-ledger/adjustments",
            headers=headers,
            json={
                "employee_id": employee["id"],
                "leave_type_id": leave_type["id"],
                "amount": "12.00",
                "effective_date": "2026-01-01",
                "reason": "Opening balance",
            },
        )
        assert credit.status_code == 201, credit.text
        assert credit.json()["data"]["entry_type"] == "ADJUSTMENT"

        debit = await client.post(
            "/v1/leave-ledger/adjustments",
            headers=headers,
            json={
                "employee_id": employee["id"],
                "leave_type_id": leave_type["id"],
                "amount": "-2.00",
                "effective_date": "2026-02-01",
                "reason": "Correction",
            },
        )
        assert debit.status_code == 201, debit.text

        balances = await client.get(
            "/v1/leave-balances", headers=headers, params={"employee_id": employee["id"]}
        )
        assert balances.status_code == 200
        assert balances.json()["data"][0]["balance"] == "10.00"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_zero_amount_adjustment_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        leave_type = await _create_leave_type(client, headers)

        response = await client.post(
            "/v1/leave-ledger/adjustments",
            headers=headers,
            json={
                "employee_id": employee["id"],
                "leave_type_id": leave_type["id"],
                "amount": "0",
                "effective_date": "2026-01-01",
                "reason": "Should be rejected",
            },
        )
        assert response.status_code == 422, response.text
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_adjustment_unknown_leave_type_not_found(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        response = await client.post(
            "/v1/leave-ledger/adjustments",
            headers=headers,
            json={
                "employee_id": employee["id"],
                "leave_type_id": "00000000-0000-0000-0000-000000000000",
                "amount": "5",
                "effective_date": "2026-01-01",
                "reason": "Unknown type",
            },
        )
        assert response.status_code == 404
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_list_ledger_entries_is_audit_trail(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        leave_type = await _create_leave_type(client, headers)

        for amount, note in (("12.00", "Opening"), ("-2.00", "Correction")):
            await client.post(
                "/v1/leave-ledger/adjustments",
                headers=headers,
                json={
                    "employee_id": employee["id"],
                    "leave_type_id": leave_type["id"],
                    "amount": amount,
                    "effective_date": "2026-01-01",
                    "reason": note,
                },
            )

        entries = await client.get(
            "/v1/leave-ledger", headers=headers, params={"employee_id": employee["id"]}
        )
        assert entries.status_code == 200, entries.text
        data = entries.json()["data"]
        assert len(data) == 2
        assert {e["reason"] for e in data} == {"Opening", "Correction"}
        # Append-only: both entries carry the same entry_type, neither was mutated into
        # something else.
        assert all(e["entry_type"] == "ADJUSTMENT" for e in data)
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_cross_tenant_balance_not_visible(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        employee_a = await _create_employee(client, headers_a)
        leave_type_a = await _create_leave_type(client, headers_a)
        await client.post(
            "/v1/leave-ledger/adjustments",
            headers=headers_a,
            json={
                "employee_id": employee_a["id"],
                "leave_type_id": leave_type_a["id"],
                "amount": "5",
                "effective_date": "2026-01-01",
                "reason": "Company A only",
            },
        )

        # Company B's admin holds COMPANY-scope LEAVE.BALANCE_VIEW_ALL, which resolves to "no
        # employee-id filter" (resolve_visible_employee_ids returns None for COMPANY scope) —
        # but the underlying balance query is independently scoped to company B's own leave
        # types and ledger rows (both filtered by company_id), so an out-of-company employee_id
        # simply matches nothing: 200 with an empty list, never Company A's data. Confirmed
        # against the real endpoint (not just asserted) before writing this test.
        response = await client.get(
            "/v1/leave-balances", headers=headers_b, params={"employee_id": employee_a["id"]}
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"] == []
    finally:
        await _teardown(company_id=company_a)
        await _teardown(company_id=company_b)
        await _cleanup(company_id=company_a, user_id=user_a)
        await _cleanup(company_id=company_b, user_id=user_b)


@pytest.mark.asyncio
async def test_unauthenticated_request_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    response = await client.get("/v1/leave-balances", params={"employee_id": str(UUID(int=0))})
    assert response.status_code == 401
