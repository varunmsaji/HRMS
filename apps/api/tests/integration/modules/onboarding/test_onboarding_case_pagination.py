"""Integration tests for `GET /v1/onboarding-cases` pagination (FINDING-03).

Mirrors `employee/test_employee_pagination.py`'s contract checks (defaults, explicit
page/per_page, empty dataset, beyond-final-page, invalid params, server max, deterministic
paging, tenant isolation, authorization) plus the `status` filter interacting with pagination —
the one other parameter this endpoint accepts."""

from typing import Any

import pytest
from httpx import AsyncClient

from .test_onboarding_case import (
    _case_payload,
    _cleanup_scoped_users,
    _create_permission_scoped_user,
    _register_tenant,
    _teardown,
)

pytestmark = pytest.mark.asyncio


async def _create_cases(
    client: AsyncClient, headers: dict[str, str], count: int, **overrides: Any
) -> list[dict[str, Any]]:
    created = []
    for _ in range(count):
        response = await client.post(
            "/v1/onboarding-cases", headers=headers, json=_case_payload(**overrides)
        )
        assert response.status_code == 201, response.text
        created.append(response.json()["data"])
    return created


async def test_default_page_returns_first_25(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        created = await _create_cases(client, headers, 27)

        response = await client.get("/v1/onboarding-cases", headers=headers)
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
        assert {row["id"] for row in body["data"]}.issubset({c["id"] for c in created})
    finally:
        await _teardown(company_id=company_id, user_id=admin_id)


async def test_explicit_page_and_per_page(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        await _create_cases(client, headers, 12)

        response = await client.get("/v1/onboarding-cases?page=2&per_page=5", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert len(body["data"]) == 5
        assert body["pagination"]["page"] == 2
        assert body["pagination"]["per_page"] == 5
        assert body["pagination"]["total"] == 12
        assert body["pagination"]["total_pages"] == 3
    finally:
        await _teardown(company_id=company_id, user_id=admin_id)


async def test_page_beyond_final_page_returns_empty_data(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        await _create_cases(client, headers, 3)

        response = await client.get("/v1/onboarding-cases?page=99", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["data"] == []
        assert body["pagination"]["total"] == 3
        assert body["pagination"]["total_pages"] == 1
    finally:
        await _teardown(company_id=company_id, user_id=admin_id)


async def test_empty_dataset_pagination(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        response = await client.get("/v1/onboarding-cases", headers=headers)
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
        await _teardown(company_id=company_id, user_id=admin_id)


@pytest.mark.parametrize("query", ["page=0", "page=-1", "per_page=0", "per_page=101"])
async def test_invalid_pagination_params_rejected(
    client: AsyncClient, seeded_plan_catalogue: None, query: str
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        response = await client.get(f"/v1/onboarding-cases?{query}", headers=headers)
        assert response.status_code == 422
    finally:
        await _teardown(company_id=company_id, user_id=admin_id)


async def test_max_page_size_boundary_accepted(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        response = await client.get("/v1/onboarding-cases?per_page=100", headers=headers)
        assert response.status_code == 200
        assert response.json()["pagination"]["per_page"] == 100
    finally:
        await _teardown(company_id=company_id, user_id=admin_id)


async def test_pagination_deterministic_no_duplicates_no_gaps(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        created = await _create_cases(client, headers, 17)
        expected_ids = {c["id"] for c in created}

        seen_ids: list[str] = []
        page = 1
        while True:
            response = await client.get(
                f"/v1/onboarding-cases?page={page}&per_page=5", headers=headers
            )
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
        await _teardown(company_id=company_id, user_id=admin_id)


async def test_tenant_isolation_pagination_total(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, admin_a = await _register_tenant(client)
    headers_b, company_b, admin_b = await _register_tenant(client)
    try:
        await _create_cases(client, headers_a, 3)
        await _create_cases(client, headers_b, 9)

        response_a = await client.get("/v1/onboarding-cases", headers=headers_a)
        assert response_a.json()["pagination"]["total"] == 3

        response_b = await client.get("/v1/onboarding-cases", headers=headers_b)
        assert response_b.json()["pagination"]["total"] == 9
    finally:
        await _teardown(company_id=company_a, user_id=admin_a)
        await _teardown(company_id=company_b, user_id=admin_b)


async def test_status_filter_interacts_correctly_with_pagination(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The `status` filter narrows the result *before* pagination, same ordering as every other
    paginated endpoint's filters (API-01 §5) — `pagination.total` reflects the filtered count,
    not the whole company."""
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        await _create_cases(client, headers, 10)  # every new case starts life as DRAFT

        unfiltered = await client.get("/v1/onboarding-cases?per_page=5", headers=headers)
        assert unfiltered.json()["pagination"]["total"] == 10

        filtered = await client.get(
            "/v1/onboarding-cases?status=ACTIVATED&per_page=5", headers=headers
        )
        assert filtered.status_code == 200
        body = filtered.json()
        assert body["data"] == []
        assert body["pagination"]["total"] == 0
        assert body["pagination"]["total_pages"] == 0

        matching = await client.get("/v1/onboarding-cases?status=DRAFT&per_page=5", headers=headers)
        assert matching.json()["pagination"]["total"] == 10
        assert len(matching.json()["data"]) == 5
    finally:
        await _teardown(company_id=company_id, user_id=admin_id)


async def test_authorization_unchanged_by_pagination(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`ONBOARDING.VIEW` still gates this endpoint — pagination params don't bypass it."""
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        await _create_cases(client, headers, 2)
        scoped_headers, _scoped_id = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=["ONBOARDING.CREATE"]
        )

        scoped = await client.get("/v1/onboarding-cases?page=1", headers=scoped_headers)
        assert scoped.status_code == 403

        anonymous = await client.get("/v1/onboarding-cases?page=1")
        assert anonymous.status_code == 401
    finally:
        await _teardown(company_id=company_id, user_id=admin_id)
        await _cleanup_scoped_users()
