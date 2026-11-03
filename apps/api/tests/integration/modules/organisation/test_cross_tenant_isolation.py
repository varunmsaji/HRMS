"""C-16 — Cross-tenant isolation for organisation company endpoints.

Each authenticated company route is asserted independently: a Company A token with
an ``X-Company-Id`` pointing at Company B must never return B's data (404, never
403 — docs/modules/company/04_API_Design.md §8 / 06_Testing_Strategy.md §2.1).
"""

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from hrms.core.db.session import get_session_factory

from .test_registration_flow import _cleanup, _register


async def _delete_branches_for_company(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("DELETE FROM branch WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.commit()


async def _delete_departments_for_company(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("DELETE FROM department WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.commit()


async def _delete_designations_for_company(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("DELETE FROM designation WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.commit()


async def _delete_grades_for_company(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("DELETE FROM grade WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.commit()


ORG_GET_PATHS = (
    "/v1/companies/current",
    "/v1/companies/current/setup-progress",
    "/v1/companies/current/subscription",
    "/v1/dashboards/company",
)


async def _register_tenant(
    client: AsyncClient, **overrides: Any
) -> tuple[dict[str, str], UUID, UUID | None]:
    response, company_id, user_id = await _register(client, **overrides)
    assert response.status_code == 201
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


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ORG_GET_PATHS)
async def test_cross_tenant_get_blocked_by_header_mismatch(
    client: AsyncClient, seeded_plan_catalogue: None, path: str
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        # Token for A, but claim B's company id — tenancy dependency must 404.
        response = await client.get(
            path,
            headers={
                "Authorization": headers_a["Authorization"],
                "X-Company-Id": str(company_b),
            },
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"

        # Control: A reading A still works.
        ok = await client.get(path, headers=headers_a)
        assert ok.status_code == 200
        if path == "/v1/companies/current":
            assert ok.json()["data"]["id"] == str(company_a)
    finally:
        await _cleanup(company_id=company_a, user_id=user_a)
        await _cleanup(company_id=company_b, user_id=user_b)


@pytest.mark.asyncio
async def test_cross_tenant_patch_profile_blocked(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        profile = await client.get("/v1/companies/current", headers=headers_b)
        assert profile.status_code == 200
        version_b = profile.json()["data"]["version"]
        original_name = profile.json()["data"]["name"]

        response = await client.patch(
            "/v1/companies/current",
            headers={
                "Authorization": headers_a["Authorization"],
                "X-Company-Id": str(company_b),
                "If-Match": str(version_b),
            },
            json={"legal_name": "Should Not Apply"},
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"

        # Prove B's row was not mutated.
        after = await client.get("/v1/companies/current", headers=headers_b)
        assert after.status_code == 200
        assert after.json()["data"]["name"] == original_name
        assert after.json()["data"]["legal_name"] is None
        assert after.json()["data"]["version"] == version_b
    finally:
        await _cleanup(company_id=company_a, user_id=user_a)
        await _cleanup(company_id=company_b, user_id=user_b)


@pytest.mark.asyncio
async def test_cross_tenant_legal_entity_get_blocked(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A's token + B's X-Company-Id must never resolve B's legal entity, even by its own
    id (the router path param is the entity's id, not a tenant id — tenant scoping still
    comes only from the header/JWT, verified server-side)."""
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        created = await client.post(
            "/v1/legal-entities", headers=headers_b, json={"name": "B Legal Entity"}
        )
        entity_id = created.json()["data"]["id"]

        forged = await client.get(
            f"/v1/legal-entities/{entity_id}",
            headers={"Authorization": headers_a["Authorization"], "X-Company-Id": str(company_b)},
        )
        assert forged.status_code == 404
        assert forged.json()["error"]["code"] == "NOT_FOUND"

        # Even A's own (real, verified-membership) tenant context can't see B's row.
        own_context = await client.get(f"/v1/legal-entities/{entity_id}", headers=headers_a)
        assert own_context.status_code == 404

        control = await client.get(f"/v1/legal-entities/{entity_id}", headers=headers_b)
        assert control.status_code == 200
    finally:
        await _cleanup(company_id=company_a, user_id=user_a)
        await _cleanup(company_id=company_b, user_id=user_b)


@pytest.mark.asyncio
async def test_cross_tenant_legal_entity_list_never_leaks(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        await client.post("/v1/legal-entities", headers=headers_b, json={"name": "B Legal Entity"})

        listed_a = await client.get("/v1/legal-entities", headers=headers_a)
        assert listed_a.status_code == 200
        assert listed_a.json()["data"] == []
    finally:
        await _cleanup(company_id=company_a, user_id=user_a)
        await _cleanup(company_id=company_b, user_id=user_b)


@pytest.mark.asyncio
async def test_cross_tenant_branch_get_blocked(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A's token + B's X-Company-Id must never resolve B's branch, even by its own id (the
    router path param is the branch's id, not a tenant id — tenant scoping still comes
    only from the header/JWT, verified server-side)."""
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        entity_b = await client.post(
            "/v1/legal-entities", headers=headers_b, json={"name": "B Legal Entity"}
        )
        entity_id_b = entity_b.json()["data"]["id"]
        created = await client.post(
            "/v1/branches",
            headers=headers_b,
            json={"legal_entity_id": entity_id_b, "name": "B Branch"},
        )
        branch_id = created.json()["data"]["id"]

        forged = await client.get(
            f"/v1/branches/{branch_id}",
            headers={"Authorization": headers_a["Authorization"], "X-Company-Id": str(company_b)},
        )
        assert forged.status_code == 404
        assert forged.json()["error"]["code"] == "NOT_FOUND"

        own_context = await client.get(f"/v1/branches/{branch_id}", headers=headers_a)
        assert own_context.status_code == 404

        control = await client.get(f"/v1/branches/{branch_id}", headers=headers_b)
        assert control.status_code == 200
    finally:
        await _delete_branches_for_company(company_id=company_b)
        await _cleanup(company_id=company_a, user_id=user_a)
        await _cleanup(company_id=company_b, user_id=user_b)


@pytest.mark.asyncio
async def test_cross_tenant_branch_list_never_leaks(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        entity_b = await client.post(
            "/v1/legal-entities", headers=headers_b, json={"name": "B Legal Entity"}
        )
        entity_id_b = entity_b.json()["data"]["id"]
        await client.post(
            "/v1/branches",
            headers=headers_b,
            json={"legal_entity_id": entity_id_b, "name": "B Branch"},
        )

        listed_a = await client.get("/v1/branches", headers=headers_a)
        assert listed_a.status_code == 200
        assert listed_a.json()["data"] == []
    finally:
        await _delete_branches_for_company(company_id=company_b)
        await _cleanup(company_id=company_a, user_id=user_a)
        await _cleanup(company_id=company_b, user_id=user_b)


@pytest.mark.asyncio
async def test_cross_tenant_department_get_blocked(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A's token + B's X-Company-Id must never resolve B's department, even by its own id."""
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        created = await client.post(
            "/v1/departments", headers=headers_b, json={"name": "B Department"}
        )
        department_id = created.json()["data"]["id"]

        forged = await client.get(
            f"/v1/departments/{department_id}",
            headers={"Authorization": headers_a["Authorization"], "X-Company-Id": str(company_b)},
        )
        assert forged.status_code == 404
        assert forged.json()["error"]["code"] == "NOT_FOUND"

        own_context = await client.get(f"/v1/departments/{department_id}", headers=headers_a)
        assert own_context.status_code == 404

        control = await client.get(f"/v1/departments/{department_id}", headers=headers_b)
        assert control.status_code == 200
    finally:
        await _delete_departments_for_company(company_id=company_b)
        await _cleanup(company_id=company_a, user_id=user_a)
        await _cleanup(company_id=company_b, user_id=user_b)


@pytest.mark.asyncio
async def test_cross_tenant_department_list_never_leaks(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        await client.post("/v1/departments", headers=headers_b, json={"name": "B Department"})

        listed_a = await client.get("/v1/departments", headers=headers_a)
        assert listed_a.status_code == 200
        assert listed_a.json()["data"] == []
    finally:
        await _delete_departments_for_company(company_id=company_b)
        await _cleanup(company_id=company_a, user_id=user_a)
        await _cleanup(company_id=company_b, user_id=user_b)


@pytest.mark.asyncio
async def test_cross_tenant_designation_get_blocked(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A's token + B's X-Company-Id must never resolve B's designation, even by its own id."""
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        created = await client.post(
            "/v1/designations", headers=headers_b, json={"title": "B Designation"}
        )
        designation_id = created.json()["data"]["id"]

        forged = await client.get(
            f"/v1/designations/{designation_id}",
            headers={"Authorization": headers_a["Authorization"], "X-Company-Id": str(company_b)},
        )
        assert forged.status_code == 404
        assert forged.json()["error"]["code"] == "NOT_FOUND"

        own_context = await client.get(f"/v1/designations/{designation_id}", headers=headers_a)
        assert own_context.status_code == 404

        control = await client.get(f"/v1/designations/{designation_id}", headers=headers_b)
        assert control.status_code == 200
    finally:
        await _delete_designations_for_company(company_id=company_b)
        await _cleanup(company_id=company_a, user_id=user_a)
        await _cleanup(company_id=company_b, user_id=user_b)


@pytest.mark.asyncio
async def test_cross_tenant_designation_list_never_leaks(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        await client.post("/v1/designations", headers=headers_b, json={"title": "B Designation"})

        listed_a = await client.get("/v1/designations", headers=headers_a)
        assert listed_a.status_code == 200
        assert listed_a.json()["data"] == []
    finally:
        await _delete_designations_for_company(company_id=company_b)
        await _cleanup(company_id=company_a, user_id=user_a)
        await _cleanup(company_id=company_b, user_id=user_b)


@pytest.mark.asyncio
async def test_cross_tenant_grade_get_blocked(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A's token + B's X-Company-Id must never resolve B's grade, even by its own id."""
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        created = await client.post("/v1/grades", headers=headers_b, json={"name": "B Grade"})
        grade_id = created.json()["data"]["id"]

        forged = await client.get(
            f"/v1/grades/{grade_id}",
            headers={"Authorization": headers_a["Authorization"], "X-Company-Id": str(company_b)},
        )
        assert forged.status_code == 404
        assert forged.json()["error"]["code"] == "NOT_FOUND"

        own_context = await client.get(f"/v1/grades/{grade_id}", headers=headers_a)
        assert own_context.status_code == 404

        control = await client.get(f"/v1/grades/{grade_id}", headers=headers_b)
        assert control.status_code == 200
    finally:
        await _delete_grades_for_company(company_id=company_b)
        await _cleanup(company_id=company_a, user_id=user_a)
        await _cleanup(company_id=company_b, user_id=user_b)


@pytest.mark.asyncio
async def test_cross_tenant_grade_list_never_leaks(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        await client.post("/v1/grades", headers=headers_b, json={"name": "B Grade"})

        listed_a = await client.get("/v1/grades", headers=headers_a)
        assert listed_a.status_code == 200
        assert listed_a.json()["data"] == []
    finally:
        await _delete_grades_for_company(company_id=company_b)
        await _cleanup(company_id=company_a, user_id=user_a)
        await _cleanup(company_id=company_b, user_id=user_b)


@pytest.mark.asyncio
async def test_cross_tenant_subscription_data_never_leaks(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        sub_a = await client.get("/v1/companies/current/subscription", headers=headers_a)
        sub_b = await client.get("/v1/companies/current/subscription", headers=headers_b)
        assert sub_a.status_code == 200
        assert sub_b.status_code == 200

        # Distinct tenants still resolve their own live FREE trial — identity is via
        # membership, not by echoing the other tenant's payload under a forged header.
        forged = await client.get(
            "/v1/companies/current/subscription",
            headers={
                "Authorization": headers_a["Authorization"],
                "X-Company-Id": str(company_b),
            },
        )
        assert forged.status_code == 404
    finally:
        await _cleanup(company_id=company_a, user_id=user_a)
        await _cleanup(company_id=company_b, user_id=user_b)
