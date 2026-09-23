"""Integration tests for `GET /v1/employees` pagination (API-01 Tier 1).

Covers the shared pagination contract (page/per_page defaults, server-side max, invalid
params, empty dataset, beyond-final-page, deterministic ordering) plus proof that pagination
narrows a caller's own already-authorized `DataScope` — never around it (API-01 §4/§10).

Reuses `test_employee_data_scope.py`'s exact actor/branch/assignment fixtures rather than
redefining them, since this is the same permission surface, just paginated.
"""

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from hrms.core.db.session import get_session_factory
from hrms.modules.employee.permissions import EMPLOYEE_VIEW_ALL
from hrms.modules.identity.permissions import EMPLOYEE_VIEW
from hrms.modules.organisation.models import Subscription

from ..organisation.test_registration_flow import _cleanup
from .test_employee_data_scope import (
    _assign_manager,
    _cleanup_employees,
    _cleanup_scoped_actors,
    _create_employee,
    _create_scoped_actor,
    _register_tenant,
    _setup_branches,
)

pytestmark = pytest.mark.asyncio


async def _raise_seat_limit(*, company_id: UUID, limit: int = 500) -> None:
    """The FREE plan new registrations land on (`seed/plan_catalogue.py`) caps at 5 seats —
    far too few to test pagination past a page boundary. `Subscription.seat_limit_override`
    (read by `EmployeeService._check_seat_limit` via `OrganisationService.get_subscription`) is
    the same override a real plan upgrade would set; bumping it directly here is equivalent to
    that, just without a plan-upgrade endpoint to drive it through (tracked separately —
    `known_feature_gaps` memory)."""
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            update(Subscription)
            .where(Subscription.company_id == company_id)
            .values(seat_limit_override=limit)
        )
        await session.commit()


async def _create_employees(
    client: AsyncClient, headers: dict[str, str], count: int, *, prefix: str = "Emp"
) -> list[dict[str, Any]]:
    return [
        await _create_employee(client, headers, first_name=f"{prefix}{i:03d}")
        for i in range(count)
    ]


async def test_default_page_returns_first_25(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        await _raise_seat_limit(company_id=company_id)
        created = await _create_employees(client, headers, 27)

        response = await client.get("/v1/employees", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert len(body["data"]) == 25
        assert body["pagination"] == {
            "page": 1,
            "per_page": 25,
            "total": 27,
            "total_pages": 2,
            "next_cursor": None,
        }
        assert len({row["id"] for row in body["data"]}) == 25
        assert {row["id"] for row in body["data"]}.issubset({e["id"] for e in created})
    finally:
        await _cleanup_employees(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=admin_id)


async def test_explicit_page_and_per_page(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        await _raise_seat_limit(company_id=company_id)
        await _create_employees(client, headers, 12)

        response = await client.get("/v1/employees?page=2&per_page=5", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert len(body["data"]) == 5
        assert body["pagination"]["page"] == 2
        assert body["pagination"]["per_page"] == 5
        assert body["pagination"]["total"] == 12
        assert body["pagination"]["total_pages"] == 3
    finally:
        await _cleanup_employees(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=admin_id)


async def test_page_beyond_final_page_returns_empty_data(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        await _create_employees(client, headers, 3)

        response = await client.get("/v1/employees?page=99", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["data"] == []
        assert body["pagination"]["total"] == 3
        assert body["pagination"]["total_pages"] == 1
    finally:
        await _cleanup_employees(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=admin_id)


async def test_empty_dataset_pagination(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        response = await client.get("/v1/employees", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["data"] == []
        assert body["pagination"] == {
            "page": 1,
            "per_page": 25,
            "total": 0,
            "total_pages": 0,
            "next_cursor": None,
        }
    finally:
        await _cleanup(company_id=company_id, user_id=admin_id)


@pytest.mark.parametrize("query", ["page=0", "page=-1", "per_page=0", "per_page=101"])
async def test_invalid_pagination_params_rejected(
    client: AsyncClient, seeded_plan_catalogue: None, query: str
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        response = await client.get(f"/v1/employees?{query}", headers=headers)
        assert response.status_code == 422
    finally:
        await _cleanup(company_id=company_id, user_id=admin_id)


async def test_max_page_size_boundary_accepted(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`per_page=100` (the documented server maximum) is accepted; a caller can never request
    more than that regardless of what they pass (API-01 §2)."""
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        response = await client.get("/v1/employees?per_page=100", headers=headers)
        assert response.status_code == 200
        assert response.json()["pagination"]["per_page"] == 100
    finally:
        await _cleanup(company_id=company_id, user_id=admin_id)


async def test_pagination_deterministic_no_duplicates_no_gaps(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Paging through the whole collection with a small `per_page` must visit every employee
    exactly once — no row skipped or repeated across adjacent pages (API-01 §11)."""
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        await _raise_seat_limit(company_id=company_id)
        created = await _create_employees(client, headers, 17)
        expected_ids = {e["id"] for e in created}

        seen_ids: list[str] = []
        page = 1
        while True:
            response = await client.get(f"/v1/employees?page={page}&per_page=5", headers=headers)
            assert response.status_code == 200
            body = response.json()
            if not body["data"]:
                break
            seen_ids.extend(row["id"] for row in body["data"])
            if page >= body["pagination"]["total_pages"]:
                break
            page += 1

        assert len(seen_ids) == len(expected_ids)
        assert set(seen_ids) == expected_ids
    finally:
        await _cleanup_employees(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=admin_id)


async def test_tenant_isolation_pagination_total(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Another tenant's employees never contribute to this tenant's `pagination.total`."""
    headers_a, company_a, admin_a = await _register_tenant(client)
    headers_b, company_b, admin_b = await _register_tenant(client)
    try:
        await _create_employees(client, headers_a, 3, prefix="TenantA")
        await _raise_seat_limit(company_id=company_b)
        await _create_employees(client, headers_b, 9, prefix="TenantB")

        response_a = await client.get("/v1/employees", headers=headers_a)
        assert response_a.json()["pagination"]["total"] == 3

        response_b = await client.get("/v1/employees", headers=headers_b)
        assert response_b.json()["pagination"]["total"] == 9
    finally:
        await _cleanup_employees(company_id=company_a)
        await _cleanup(company_id=company_a, user_id=admin_a)
        await _cleanup_employees(company_id=company_b)
        await _cleanup(company_id=company_b, user_id=admin_b)


async def test_branch_scope_pagination_narrows_before_paging(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A `BRANCH`-scoped caller paging through `/v1/employees` only ever pages across their own
    branch's colleagues — the total and every page's rows are confined to that visible set,
    proving authorization is applied before `LIMIT`/`OFFSET`, not after (API-01 §4/§10)."""
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        await _raise_seat_limit(company_id=company_id)
        branch_a, branch_b = await _setup_branches(company_id=company_id, count=2)

        manager = await _create_employee(client, headers, first_name="BranchManager")
        colleagues = await _create_employees(client, headers, 7, prefix="Colleague")
        outsiders = await _create_employees(client, headers, 5, prefix="Outsider")

        await _assign_manager(
            company_id=company_id,
            employee_id=UUID(manager["id"]),
            reporting_manager_id=None,
            branch_id=branch_a,
        )
        for emp in colleagues:
            await _assign_manager(
                company_id=company_id,
                employee_id=UUID(emp["id"]),
                reporting_manager_id=None,
                branch_id=branch_a,
            )
        for emp in outsiders:
            await _assign_manager(
                company_id=company_id,
                employee_id=UUID(emp["id"]),
                reporting_manager_id=None,
                branch_id=branch_b,
            )

        actor_headers, _actor_id = await _create_scoped_actor(
            company_id=company_id,
            role_grants=[[(EMPLOYEE_VIEW, "BRANCH"), (EMPLOYEE_VIEW_ALL, "BRANCH")]],
            employee_id=UUID(manager["id"]),
        )

        visible_ids = {manager["id"]} | {e["id"] for e in colleagues}

        first_page = await client.get(
            "/v1/employees?page=1&per_page=5", headers=actor_headers
        )
        assert first_page.status_code == 200
        first_body = first_page.json()
        assert first_body["pagination"]["total"] == 8
        assert first_body["pagination"]["total_pages"] == 2
        assert len(first_body["data"]) == 5

        second_page = await client.get(
            "/v1/employees?page=2&per_page=5", headers=actor_headers
        )
        second_body = second_page.json()
        assert len(second_body["data"]) == 3

        all_ids = {row["id"] for row in first_body["data"]} | {
            row["id"] for row in second_body["data"]
        }
        assert all_ids == visible_ids
        assert visible_ids.isdisjoint({e["id"] for e in outsiders})
    finally:
        await _cleanup_employees(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=admin_id)
        await _cleanup_scoped_actors()
