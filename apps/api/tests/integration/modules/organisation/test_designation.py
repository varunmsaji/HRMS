"""Integration tests for the Designation API — Sprint 3 vertical slice.

Covers the `/v1/designations` surface: create, list, get, update, validation (department
ownership, mass-assignment), deactivation/reactivation (no dependency-blocking rule applies
this slice — see docs/modules/designation/00_DESIGNATION_AUDIT.md §5.3/§5.4), audit records,
and not-found behavior. Tenant isolation and permission-matrix coverage live in the sibling
`test_cross_tenant_isolation.py` / `test_permission_matrix.py` files.
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


async def _create_department(
    client: AsyncClient, headers: dict[str, str], name: str = "Engineering"
) -> str:
    department = await client.post("/v1/departments", headers=headers, json={"name": name})
    assert department.status_code == 201
    return str(department.json()["data"]["id"])


async def _create_designation(
    client: AsyncClient, headers: dict[str, str], title: str = "Software Engineer", **extra: Any
) -> dict[str, Any]:
    response = await client.post(
        "/v1/designations", headers=headers, json={"title": title, **extra}
    )
    assert response.status_code == 201
    return dict(response.json()["data"])


async def _cleanup_designations_and_departments(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("DELETE FROM designation WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.execute(
            text("DELETE FROM department WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.commit()


@pytest.mark.asyncio
async def test_list_designations_empty_state(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.get("/v1/designations", headers=headers)
        assert response.status_code == 200
        assert response.json()["data"] == []
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_designation_success_without_department(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.post(
            "/v1/designations",
            headers=headers,
            json={"title": "Software Engineer", "code": "SWE"},
        )
        assert response.status_code == 201
        data = response.json()["data"]
        assert data["title"] == "Software Engineer"
        assert data["department_id"] is None
        assert data["is_active"] is True
        assert data["version"] == 1
        assert data["company_id"] == str(company_id)

        listed = await client.get("/v1/designations", headers=headers)
        assert len(listed.json()["data"]) == 1

        factory = get_session_factory()
        async with factory() as session:
            audit_rows = (
                (
                    await session.execute(
                        select(AuditLog).where(
                            AuditLog.company_id == company_id,
                            AuditLog.entity_type == "designation",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(audit_rows) == 1
            assert audit_rows[0].action == "DESIGNATION_CREATED"
    finally:
        await _cleanup_designations_and_departments(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_designation_with_department_success(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        department_id = await _create_department(client, headers)
        response = await client.post(
            "/v1/designations",
            headers=headers,
            json={"title": "Software Engineer", "department_id": department_id},
        )
        assert response.status_code == 201
        assert response.json()["data"]["department_id"] == department_id
    finally:
        await _cleanup_designations_and_departments(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_designation_invalid_department_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.post(
            "/v1/designations",
            headers=headers,
            json={"title": "Software Engineer", "department_id": str(uuid4())},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_DEPARTMENT"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_designation_cross_tenant_department_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        department_b = await _create_department(client, headers_b)

        response = await client.post(
            "/v1/designations",
            headers=headers_a,
            json={"title": "Software Engineer", "department_id": department_b},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_DEPARTMENT"
    finally:
        await _cleanup_designations_and_departments(company_id=company_b)
        await _cleanup(company_id=company_a, user_id=user_a)
        await _cleanup(company_id=company_b, user_id=user_b)


@pytest.mark.asyncio
async def test_create_designation_missing_title_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.post("/v1/designations", headers=headers, json={})
        assert response.status_code == 422
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_designation_mass_assignment_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.post(
            "/v1/designations",
            headers=headers,
            json={"title": "Software Engineer", "is_active": False, "version": 99},
        )
        assert response.status_code == 422
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_update_designation_mass_assignment_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        designation = await _create_designation(client, headers)
        response = await client.patch(
            f"/v1/designations/{designation['id']}",
            headers={**headers, "If-Match": str(designation["version"])},
            json={"id": str(uuid4()), "company_id": str(uuid4())},
        )
        assert response.status_code == 422

        after = await client.get(f"/v1/designations/{designation['id']}", headers=headers)
        assert after.json()["data"]["id"] == designation["id"]
        assert after.json()["data"]["company_id"] == str(company_id)
    finally:
        await _cleanup_designations_and_departments(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_get_designation_not_found(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.get(f"/v1/designations/{uuid4()}", headers=headers)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_update_designation_success(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        designation = await _create_designation(client, headers)
        response = await client.patch(
            f"/v1/designations/{designation['id']}",
            headers={**headers, "If-Match": str(designation["version"])},
            json={"code": "SWE"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["code"] == "SWE"
        assert data["version"] == 2
        assert data["title"] == "Software Engineer"
    finally:
        await _cleanup_designations_and_departments(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_update_designation_stale_version_conflict(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        designation = await _create_designation(client, headers)
        response = await client.patch(
            f"/v1/designations/{designation['id']}",
            headers={**headers, "If-Match": "999"},
            json={"title": "Renamed"},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "STALE_RESOURCE"
    finally:
        await _cleanup_designations_and_departments(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_deactivate_designation_success(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        designation = await _create_designation(client, headers)
        response = await client.request(
            "DELETE",
            f"/v1/designations/{designation['id']}",
            headers={**headers, "If-Match": str(designation["version"])},
        )
        assert response.status_code == 200
        assert response.json()["data"]["is_active"] is False

        factory = get_session_factory()
        async with factory() as session:
            audit_rows = (
                (
                    await session.execute(
                        select(AuditLog).where(
                            AuditLog.entity_id == UUID(designation["id"]),
                            AuditLog.action == "DESIGNATION_DEACTIVATED",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(audit_rows) == 1
    finally:
        await _cleanup_designations_and_departments(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_deactivate_designation_not_blocked_by_next_designation_reference(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`next_designation_id` has no schema/UI exposure this slice (D10 — see
    docs/modules/designation/00_DESIGNATION_AUDIT.md §5.4), so nothing can populate it and
    no deactivation-blocking check on it is implemented. A designation can be freely
    deactivated regardless."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        designation = await _create_designation(client, headers)

        response = await client.request(
            "DELETE",
            f"/v1/designations/{designation['id']}",
            headers={**headers, "If-Match": str(designation["version"])},
        )
        assert response.status_code == 200
        assert response.json()["data"]["is_active"] is False
    finally:
        await _cleanup_designations_and_departments(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_reactivate_designation_via_patch(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        designation = await _create_designation(client, headers)
        deactivated = await client.request(
            "DELETE",
            f"/v1/designations/{designation['id']}",
            headers={**headers, "If-Match": str(designation["version"])},
        )
        assert deactivated.json()["data"]["is_active"] is False
        version_after_deactivate = deactivated.json()["data"]["version"]

        reactivated = await client.patch(
            f"/v1/designations/{designation['id']}",
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
                            AuditLog.entity_id == UUID(designation["id"]),
                            AuditLog.action == "DESIGNATION_REACTIVATED",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(audit_rows) == 1
    finally:
        await _cleanup_designations_and_departments(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_multiple_designations_supported(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        await _create_designation(client, headers, title="Software Engineer")
        await _create_designation(client, headers, title="Product Manager")
        listed = await client.get("/v1/designations", headers=headers)
        titles = {row["title"] for row in listed.json()["data"]}
        assert titles == {"Software Engineer", "Product Manager"}
    finally:
        await _cleanup_designations_and_departments(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
