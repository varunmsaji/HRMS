"""Integration tests for the Legal Entity API — Sprint 3A vertical slice.

Covers docs/modules/company/06_Testing_Strategy.md-style coverage for the new
`/v1/legal-entities` surface: create, list, get, update, validation, deactivation
business rule (FR-ORG-014), audit records, and not-found behavior. Tenant isolation and
permission-matrix coverage live in the sibling `test_cross_tenant_isolation.py` /
`test_permission_matrix.py` files, extended alongside this one.
"""

from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from hrms.core.audit.models import AuditLog
from hrms.core.db.session import get_session_factory
from hrms.modules.organisation.models import LegalEntity

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


async def _insert_active_branch(*, company_id: UUID, legal_entity_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text(
                """
                INSERT INTO branch (id, company_id, legal_entity_id, name, created_at, updated_at)
                VALUES (:id, :company_id, :legal_entity_id, :name, now(), now())
                """
            ),
            {
                "id": str(uuid4()),
                "company_id": str(company_id),
                "legal_entity_id": str(legal_entity_id),
                "name": "HQ Branch",
            },
        )
        await session.commit()


async def _delete_branches(*, legal_entity_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("DELETE FROM branch WHERE legal_entity_id = :id"), {"id": str(legal_entity_id)}
        )
        await session.commit()


@pytest.mark.asyncio
async def test_list_legal_entities_empty_state(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.get("/v1/legal-entities", headers=headers)
        assert response.status_code == 200
        assert response.json()["data"] == []
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_legal_entity_success(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.post(
            "/v1/legal-entities",
            headers=headers,
            json={
                "name": "Acme Technologies Pvt Ltd",
                "pan": "abcde1234f",
                "gstin": "29abcde1234f1z5",
            },
        )
        assert response.status_code == 201
        data = response.json()["data"]
        assert data["name"] == "Acme Technologies Pvt Ltd"
        assert data["pan"] == "ABCDE1234F"
        assert data["gstin"] == "29ABCDE1234F1Z5"
        assert data["is_active"] is True
        assert data["version"] == 1
        assert data["company_id"] == str(company_id)

        listed = await client.get("/v1/legal-entities", headers=headers)
        assert len(listed.json()["data"]) == 1

        factory = get_session_factory()
        async with factory() as session:
            audit_rows = (
                (
                    await session.execute(
                        select(AuditLog).where(
                            AuditLog.company_id == company_id,
                            AuditLog.entity_type == "legal_entity",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(audit_rows) == 1
            assert audit_rows[0].action == "LEGAL_ENTITY_CREATED"
            assert audit_rows[0].before_json is None
            assert audit_rows[0].after_json is not None
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_legal_entity_invalid_pan_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.post(
            "/v1/legal-entities",
            headers=headers,
            json={"name": "Acme Pvt Ltd", "pan": "not-a-pan"},
        )
        assert response.status_code == 422
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_legal_entity_invalid_gstin_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.post(
            "/v1/legal-entities",
            headers=headers,
            json={"name": "Acme Pvt Ltd", "gstin": "invalid"},
        )
        assert response.status_code == 422
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_legal_entity_missing_name_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.post("/v1/legal-entities", headers=headers, json={})
        assert response.status_code == 422
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_legal_entity_mass_assignment_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.post(
            "/v1/legal-entities",
            headers=headers,
            json={"name": "Acme Pvt Ltd", "is_active": False, "version": 99},
        )
        assert response.status_code == 422
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_update_legal_entity_mass_assignment_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        created = await client.post(
            "/v1/legal-entities", headers=headers, json={"name": "Acme Pvt Ltd"}
        )
        entity = created.json()["data"]
        response = await client.patch(
            f"/v1/legal-entities/{entity['id']}",
            headers={**headers, "If-Match": str(entity["version"])},
            json={"id": str(uuid4()), "company_id": str(uuid4())},
        )
        assert response.status_code == 422

        after = await client.get(f"/v1/legal-entities/{entity['id']}", headers=headers)
        assert after.json()["data"]["id"] == entity["id"]
        assert after.json()["data"]["company_id"] == str(company_id)
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_get_legal_entity_not_found(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.get(f"/v1/legal-entities/{uuid4()}", headers=headers)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_update_legal_entity_success(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        created = await client.post(
            "/v1/legal-entities", headers=headers, json={"name": "Acme Pvt Ltd"}
        )
        entity = created.json()["data"]
        response = await client.patch(
            f"/v1/legal-entities/{entity['id']}",
            headers={**headers, "If-Match": str(entity["version"])},
            json={"registered_address": "1 MG Road, Bengaluru"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["registered_address"] == "1 MG Road, Bengaluru"
        assert data["version"] == 2
        assert data["name"] == "Acme Pvt Ltd"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_update_legal_entity_stale_version_conflict(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        created = await client.post(
            "/v1/legal-entities", headers=headers, json={"name": "Acme Pvt Ltd"}
        )
        entity = created.json()["data"]
        response = await client.patch(
            f"/v1/legal-entities/{entity['id']}",
            headers={**headers, "If-Match": "999"},
            json={"name": "Renamed"},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "STALE_RESOURCE"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_deactivate_legal_entity_success(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        created = await client.post(
            "/v1/legal-entities", headers=headers, json={"name": "Acme Pvt Ltd"}
        )
        entity = created.json()["data"]
        response = await client.request(
            "DELETE",
            f"/v1/legal-entities/{entity['id']}",
            headers={**headers, "If-Match": str(entity["version"])},
        )
        assert response.status_code == 200
        assert response.json()["data"]["is_active"] is False

        factory = get_session_factory()
        async with factory() as session:
            audit_rows = (
                (
                    await session.execute(
                        select(AuditLog).where(
                            AuditLog.entity_id == UUID(entity["id"]),
                            AuditLog.action == "LEGAL_ENTITY_DEACTIVATED",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(audit_rows) == 1
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_deactivate_legal_entity_blocked_by_active_branch(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    entity_id: UUID | None = None
    try:
        created = await client.post(
            "/v1/legal-entities", headers=headers, json={"name": "Acme Pvt Ltd"}
        )
        entity = created.json()["data"]
        entity_id = UUID(entity["id"])
        await _insert_active_branch(company_id=company_id, legal_entity_id=entity_id)

        response = await client.request(
            "DELETE",
            f"/v1/legal-entities/{entity['id']}",
            headers={**headers, "If-Match": str(entity["version"])},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "LEGAL_ENTITY_HAS_ACTIVE_BRANCHES"

        # Prove it was not mutated.
        current = await client.get(f"/v1/legal-entities/{entity['id']}", headers=headers)
        assert current.json()["data"]["is_active"] is True
    finally:
        if entity_id is not None:
            await _delete_branches(legal_entity_id=entity_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_reactivate_legal_entity_via_patch(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        created = await client.post(
            "/v1/legal-entities", headers=headers, json={"name": "Acme Pvt Ltd"}
        )
        entity = created.json()["data"]
        deactivated = await client.request(
            "DELETE",
            f"/v1/legal-entities/{entity['id']}",
            headers={**headers, "If-Match": str(entity["version"])},
        )
        assert deactivated.json()["data"]["is_active"] is False
        version_after_deactivate = deactivated.json()["data"]["version"]

        reactivated = await client.patch(
            f"/v1/legal-entities/{entity['id']}",
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
                            AuditLog.entity_id == UUID(entity["id"]),
                            AuditLog.action == "LEGAL_ENTITY_REACTIVATED",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(audit_rows) == 1
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_multiple_legal_entities_per_company_supported(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The product decision this slice implements: a company may own more than one
    legal entity (docs/product/02_PRD.md glossary)."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        await client.post("/v1/legal-entities", headers=headers, json={"name": "Acme Tech Pvt Ltd"})
        await client.post(
            "/v1/legal-entities", headers=headers, json={"name": "Acme Services Pvt Ltd"}
        )
        listed = await client.get("/v1/legal-entities", headers=headers)
        names = {row["name"] for row in listed.json()["data"]}
        assert names == {"Acme Tech Pvt Ltd", "Acme Services Pvt Ltd"}
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_company_registration_does_not_auto_create_legal_entity(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Confirms the product decision made for this slice: no default Legal Entity is
    seeded at registration (docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md Task 2.1.3 does
    not list it; the Screen 4 empty-state note's contrary assumption was treated as the
    doc bug per this task's audit)."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        factory = get_session_factory()
        async with factory() as session:
            rows = (
                (
                    await session.execute(
                        select(LegalEntity).where(LegalEntity.company_id == company_id)
                    )
                )
                .scalars()
                .all()
            )
            assert rows == []
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_second_company_rejected_when_limit_is_one(
    client: AsyncClient, seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Initial release: one company per tenant (branches are unlimited)."""
    from hrms.core.config.settings import get_settings

    headers, company_id, user_id = await _register_tenant(client)
    try:
        monkeypatch.setattr(get_settings(), "max_legal_entities_per_company", 1)
        first = await client.post("/v1/legal-entities", headers=headers, json={"name": "Acme"})
        assert first.status_code == 201
        second = await client.post("/v1/legal-entities", headers=headers, json={"name": "Beta"})
        assert second.status_code == 409
        assert second.json()["error"]["details"][0]["code"] == "COMPANY_LIMIT_REACHED"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)
