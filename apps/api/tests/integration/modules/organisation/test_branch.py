"""Integration tests for the Branch API — Sprint 3 vertical slice.

Covers the `/v1/branches` surface: create, list, get, update, validation (state_code,
pincode, lat/long, mass-assignment), Legal Entity ownership (invalid + cross-tenant),
deactivation business rule (FR-ORG-014, blocked by active departments), audit records,
and not-found behavior. Tenant isolation and permission-matrix coverage live in the
sibling `test_cross_tenant_isolation.py` / `test_permission_matrix.py` files.
"""

from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from hrms.core.audit.models import AuditLog
from hrms.core.db.session import get_session_factory

from .test_registration_flow import _cleanup, _register


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


async def _create_legal_entity(
    client: AsyncClient, headers: dict[str, str], name: str = "Acme Pvt Ltd"
) -> str:
    response = await client.post("/v1/legal-entities", headers=headers, json={"name": name})
    assert response.status_code == 201
    return str(response.json()["data"]["id"])


async def _delete_branches_for_company(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("DELETE FROM department WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.execute(
            text("DELETE FROM branch WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.commit()


async def _insert_active_department(*, company_id: UUID, branch_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text(
                """
                INSERT INTO department (id, company_id, branch_id, name, created_at, updated_at)
                VALUES (:id, :company_id, :branch_id, :name, now(), now())
                """
            ),
            {
                "id": str(uuid4()),
                "company_id": str(company_id),
                "branch_id": str(branch_id),
                "name": "Engineering",
            },
        )
        await session.commit()


@pytest.mark.asyncio
async def test_list_branches_empty_state(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.get("/v1/branches", headers=headers)
        assert response.status_code == 200
        assert response.json()["data"] == []
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_branch_success(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        entity_id = await _create_legal_entity(client, headers)
        response = await client.post(
            "/v1/branches",
            headers=headers,
            json={
                "legal_entity_id": entity_id,
                "name": "HQ Branch",
                "code": "HQ",
                "city": "Bengaluru",
                "state_code": "ka",
                "pincode": "560001",
                "latitude": "12.9716",
                "longitude": "77.5946",
                "geofence_radius_m": 200,
            },
        )
        assert response.status_code == 201
        data = response.json()["data"]
        assert data["name"] == "HQ Branch"
        assert data["legal_entity_id"] == entity_id
        assert data["state_code"] == "KA"
        assert data["is_active"] is True
        assert data["version"] == 1
        assert data["company_id"] == str(company_id)

        listed = await client.get("/v1/branches", headers=headers)
        assert len(listed.json()["data"]) == 1

        factory = get_session_factory()
        async with factory() as session:
            audit_rows = (
                (
                    await session.execute(
                        select(AuditLog).where(
                            AuditLog.company_id == company_id,
                            AuditLog.entity_type == "branch",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(audit_rows) == 1
            assert audit_rows[0].action == "BRANCH_CREATED"
            assert audit_rows[0].before_json is None
            assert audit_rows[0].after_json is not None
    finally:
        await _delete_branches_for_company(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_branch_invalid_legal_entity_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.post(
            "/v1/branches", headers=headers, json={"legal_entity_id": str(uuid4()), "name": "HQ"}
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_LEGAL_ENTITY"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_branch_cross_tenant_legal_entity_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        entity_b = await _create_legal_entity(client, headers_b, name="B Legal Entity")

        response = await client.post(
            "/v1/branches", headers=headers_a, json={"legal_entity_id": entity_b, "name": "HQ"}
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_LEGAL_ENTITY"

        listed_a = await client.get("/v1/branches", headers=headers_a)
        assert listed_a.json()["data"] == []
    finally:
        await _cleanup(company_id=company_a, user_id=user_a)
        await _cleanup(company_id=company_b, user_id=user_b)


@pytest.mark.asyncio
async def test_create_branch_missing_required_fields_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.post("/v1/branches", headers=headers, json={})
        assert response.status_code == 422
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_branch_invalid_state_code_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        entity_id = await _create_legal_entity(client, headers)
        response = await client.post(
            "/v1/branches",
            headers=headers,
            json={"legal_entity_id": entity_id, "name": "HQ", "state_code": "ZZ"},
        )
        assert response.status_code == 422
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_branch_invalid_pincode_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        entity_id = await _create_legal_entity(client, headers)
        response = await client.post(
            "/v1/branches",
            headers=headers,
            json={"legal_entity_id": entity_id, "name": "HQ", "pincode": "12"},
        )
        assert response.status_code == 422
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_branch_invalid_latitude_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        entity_id = await _create_legal_entity(client, headers)
        response = await client.post(
            "/v1/branches",
            headers=headers,
            json={"legal_entity_id": entity_id, "name": "HQ", "latitude": "999"},
        )
        assert response.status_code == 422
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_branch_partial_geofence_allowed(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """No spec mandates all-or-nothing geofence fields — lat/long without radius is valid."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        entity_id = await _create_legal_entity(client, headers)
        response = await client.post(
            "/v1/branches",
            headers=headers,
            json={
                "legal_entity_id": entity_id,
                "name": "HQ",
                "latitude": "12.9716",
                "longitude": "77.5946",
            },
        )
        assert response.status_code == 201
        assert response.json()["data"]["geofence_radius_m"] is None
    finally:
        await _delete_branches_for_company(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_branch_mass_assignment_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        entity_id = await _create_legal_entity(client, headers)
        response = await client.post(
            "/v1/branches",
            headers=headers,
            json={
                "legal_entity_id": entity_id,
                "name": "HQ",
                "is_active": False,
                "version": 99,
            },
        )
        assert response.status_code == 422
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_update_branch_mass_assignment_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        entity_id = await _create_legal_entity(client, headers)
        created = await client.post(
            "/v1/branches", headers=headers, json={"legal_entity_id": entity_id, "name": "HQ"}
        )
        branch = created.json()["data"]
        response = await client.patch(
            f"/v1/branches/{branch['id']}",
            headers={**headers, "If-Match": str(branch["version"])},
            json={"id": str(uuid4()), "company_id": str(uuid4())},
        )
        assert response.status_code == 422

        after = await client.get(f"/v1/branches/{branch['id']}", headers=headers)
        assert after.json()["data"]["id"] == branch["id"]
        assert after.json()["data"]["company_id"] == str(company_id)
    finally:
        await _delete_branches_for_company(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_get_branch_not_found(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.get(f"/v1/branches/{uuid4()}", headers=headers)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_update_branch_success(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        entity_id = await _create_legal_entity(client, headers)
        created = await client.post(
            "/v1/branches", headers=headers, json={"legal_entity_id": entity_id, "name": "HQ"}
        )
        branch = created.json()["data"]
        response = await client.patch(
            f"/v1/branches/{branch['id']}",
            headers={**headers, "If-Match": str(branch["version"])},
            json={"city": "Bengaluru"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["city"] == "Bengaluru"
        assert data["version"] == 2
        assert data["name"] == "HQ"
    finally:
        await _delete_branches_for_company(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_update_branch_stale_version_conflict(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        entity_id = await _create_legal_entity(client, headers)
        created = await client.post(
            "/v1/branches", headers=headers, json={"legal_entity_id": entity_id, "name": "HQ"}
        )
        branch = created.json()["data"]
        response = await client.patch(
            f"/v1/branches/{branch['id']}",
            headers={**headers, "If-Match": "999"},
            json={"name": "Renamed"},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "STALE_RESOURCE"
    finally:
        await _delete_branches_for_company(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_deactivate_branch_success(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        entity_id = await _create_legal_entity(client, headers)
        created = await client.post(
            "/v1/branches", headers=headers, json={"legal_entity_id": entity_id, "name": "HQ"}
        )
        branch = created.json()["data"]
        response = await client.request(
            "DELETE",
            f"/v1/branches/{branch['id']}",
            headers={**headers, "If-Match": str(branch["version"])},
        )
        assert response.status_code == 200
        assert response.json()["data"]["is_active"] is False

        factory = get_session_factory()
        async with factory() as session:
            audit_rows = (
                (
                    await session.execute(
                        select(AuditLog).where(
                            AuditLog.entity_id == UUID(branch["id"]),
                            AuditLog.action == "BRANCH_DEACTIVATED",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(audit_rows) == 1
    finally:
        await _delete_branches_for_company(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_deactivate_branch_blocked_by_active_department(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        entity_id = await _create_legal_entity(client, headers)
        created = await client.post(
            "/v1/branches", headers=headers, json={"legal_entity_id": entity_id, "name": "HQ"}
        )
        branch = created.json()["data"]
        await _insert_active_department(company_id=company_id, branch_id=UUID(branch["id"]))

        response = await client.request(
            "DELETE",
            f"/v1/branches/{branch['id']}",
            headers={**headers, "If-Match": str(branch["version"])},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "BRANCH_HAS_ACTIVE_DEPARTMENTS"

        current = await client.get(f"/v1/branches/{branch['id']}", headers=headers)
        assert current.json()["data"]["is_active"] is True
    finally:
        await _delete_branches_for_company(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_reactivate_branch_via_patch(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        entity_id = await _create_legal_entity(client, headers)
        created = await client.post(
            "/v1/branches", headers=headers, json={"legal_entity_id": entity_id, "name": "HQ"}
        )
        branch = created.json()["data"]
        deactivated = await client.request(
            "DELETE",
            f"/v1/branches/{branch['id']}",
            headers={**headers, "If-Match": str(branch["version"])},
        )
        assert deactivated.json()["data"]["is_active"] is False
        version_after_deactivate = deactivated.json()["data"]["version"]

        reactivated = await client.patch(
            f"/v1/branches/{branch['id']}",
            headers={**headers, "If-Match": str(version_after_deactivate)},
            json={"is_active": True},
        )
        assert reactivated.status_code == 200
        assert reactivated.json()["data"]["is_active"] is True

        factory = get_session_factory()
        async with factory() as session:
            audit_rows = (
                (
                    await session.execute(
                        select(AuditLog).where(
                            AuditLog.entity_id == UUID(branch["id"]),
                            AuditLog.action == "BRANCH_REACTIVATED",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(audit_rows) == 1
    finally:
        await _delete_branches_for_company(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_multiple_branches_per_legal_entity_supported(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        entity_id = await _create_legal_entity(client, headers)
        await client.post(
            "/v1/branches",
            headers=headers,
            json={"legal_entity_id": entity_id, "name": "HQ Branch"},
        )
        await client.post(
            "/v1/branches",
            headers=headers,
            json={"legal_entity_id": entity_id, "name": "Regional Branch"},
        )
        listed = await client.get("/v1/branches", headers=headers)
        names = {row["name"] for row in listed.json()["data"]}
        assert names == {"HQ Branch", "Regional Branch"}
    finally:
        await _delete_branches_for_company(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_legal_entity_deactivation_not_blocked_by_inactive_branch(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Regression coverage for the fix to `count_active_branches_for_legal_entity`:
    a *deactivated* branch must not block Legal Entity deactivation (FR-ORG-014)."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        entity_created = await client.post(
            "/v1/legal-entities", headers=headers, json={"name": "Acme Pvt Ltd"}
        )
        entity = entity_created.json()["data"]

        branch_created = await client.post(
            "/v1/branches", headers=headers, json={"legal_entity_id": entity["id"], "name": "HQ"}
        )
        branch = branch_created.json()["data"]
        deactivated_branch = await client.request(
            "DELETE",
            f"/v1/branches/{branch['id']}",
            headers={**headers, "If-Match": str(branch["version"])},
        )
        assert deactivated_branch.json()["data"]["is_active"] is False

        response = await client.request(
            "DELETE",
            f"/v1/legal-entities/{entity['id']}",
            headers={**headers, "If-Match": str(entity["version"])},
        )
        assert response.status_code == 200
        assert response.json()["data"]["is_active"] is False
    finally:
        await _delete_branches_for_company(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
