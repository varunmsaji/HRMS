"""Integration tests for `GET /v1/leave-ledger` pagination (API-01 §6).

Reuses `test_leave_ledger.py`'s exact fixture helpers — this is the same append-only ledger,
just with enough entries to exercise pagination.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from tests.integration.modules.leave.test_leave_ledger import (
    _create_employee,
    _create_leave_type,
    _register_tenant,
    _teardown,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

pytestmark = pytest.mark.asyncio


async def _adjust(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    employee_id: str,
    leave_type_id: str,
    amount: str,
    effective_date: str,
) -> dict[str, Any]:
    response = await client.post(
        "/v1/leave-ledger/adjustments",
        headers=headers,
        json={
            "employee_id": employee_id,
            "leave_type_id": leave_type_id,
            "amount": amount,
            "effective_date": effective_date,
            "reason": "Test adjustment",
        },
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def test_leave_ledger_paginates_ordered_by_effective_date_desc(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        leave_type = await _create_leave_type(client, headers)

        entry_ids = set()
        for day in range(1, 8):
            entry = await _adjust(
                client,
                headers,
                employee_id=employee["id"],
                leave_type_id=leave_type["id"],
                amount="1.00",
                effective_date=f"2026-01-{day:02d}",
            )
            entry_ids.add(entry["id"])

        response = await client.get(
            "/v1/leave-ledger",
            headers=headers,
            params={"employee_id": employee["id"], "per_page": 3},
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["data"]) == 3
        assert body["pagination"]["total"] == 7
        assert body["pagination"]["total_pages"] == 3
        # `effective_date` descending — page 1 is the 3 most recent dates.
        assert [row["effective_date"] for row in body["data"]] == [
            "2026-01-07",
            "2026-01-06",
            "2026-01-05",
        ]

        seen_ids: set[str] = set()
        for page in (1, 2, 3):
            page_resp = await client.get(
                "/v1/leave-ledger",
                headers=headers,
                params={"employee_id": employee["id"], "page": page, "per_page": 3},
            )
            seen_ids.update(row["id"] for row in page_resp.json()["data"])
        assert seen_ids == entry_ids
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_leave_ledger_filter_by_leave_type_preserved_under_pagination(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        leave_type_a = await _create_leave_type(client, headers, code="CL", name="Casual Leave")
        leave_type_b = await _create_leave_type(client, headers, code="SL", name="Sick Leave")

        for day in range(1, 4):
            await _adjust(
                client,
                headers,
                employee_id=employee["id"],
                leave_type_id=leave_type_a["id"],
                amount="1.00",
                effective_date=f"2026-02-{day:02d}",
            )
        await _adjust(
            client,
            headers,
            employee_id=employee["id"],
            leave_type_id=leave_type_b["id"],
            amount="1.00",
            effective_date="2026-02-10",
        )

        response = await client.get(
            "/v1/leave-ledger",
            headers=headers,
            params={"employee_id": employee["id"], "leave_type_id": leave_type_a["id"]},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["pagination"]["total"] == 3
        assert all(row["leave_type_id"] == leave_type_a["id"] for row in body["data"])
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_leave_ledger_invalid_pagination_params_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        response = await client.get(
            "/v1/leave-ledger",
            headers=headers,
            params={"employee_id": employee["id"], "per_page": 101},
        )
        assert response.status_code == 422
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
