"""C-16 — Role × endpoint permission matrix for organisation company routes.

Roles exercised (docs/modules/company/06_Testing_Strategy.md §4):

- COMPANY_ADMIN — Allow on all five authenticated company routes
- Zero-permission member (valid session, permissions stripped) — 403
- Different-company user (header mismatch) — 404 before permission check
"""

from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from hrms.core.db.models.identity import Permission, Role, RolePermission
from hrms.core.db.session import get_session_factory
from hrms.modules.organisation.permissions import (
    DASHBOARD_COMPANY_VIEW,
    ORG_BRANCH_MANAGE,
    ORG_COMPANY_MANAGE,
    ORG_DEPARTMENT_MANAGE,
    ORG_DESIGNATION_MANAGE,
    ORG_GRADE_MANAGE,
    ORG_LEGAL_ENTITY_MANAGE,
)

from .test_registration_flow import _cleanup, _register

ORG_MANAGE_PATHS = (
    ("GET", "/v1/companies/current"),
    ("GET", "/v1/companies/current/setup-progress"),
    ("GET", "/v1/companies/current/subscription"),
)
DASHBOARD_PATH = ("GET", "/v1/dashboards/company")


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


async def _strip_permission(company_id: UUID, code: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        role = (
            await session.execute(
                select(Role).where(Role.company_id == company_id, Role.code == "COMPANY_ADMIN")
            )
        ).scalar_one()
        perm = (
            await session.execute(select(Permission).where(Permission.code == code))
        ).scalar_one()
        await session.execute(
            RolePermission.__table__.delete().where(
                RolePermission.role_id == role.id,
                RolePermission.permission_id == perm.id,
            )
        )
        await session.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", [*ORG_MANAGE_PATHS, DASHBOARD_PATH])
async def test_company_admin_allowed(
    client: AsyncClient, seeded_plan_catalogue: None, method: str, path: str
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.request(method, path, headers=headers)
        assert response.status_code == 200
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", ORG_MANAGE_PATHS)
async def test_zero_permission_denied_org_manage(
    client: AsyncClient, seeded_plan_catalogue: None, method: str, path: str
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        await _strip_permission(company_id, ORG_COMPANY_MANAGE)
        response = await client.request(method, path, headers=headers)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_zero_permission_denied_dashboard(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        await _strip_permission(company_id, DASHBOARD_COMPANY_VIEW)
        response = await client.get(DASHBOARD_PATH[1], headers=headers)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", [*ORG_MANAGE_PATHS, DASHBOARD_PATH])
async def test_different_company_user_gets_404(
    client: AsyncClient, seeded_plan_catalogue: None, method: str, path: str
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    _headers_b, company_b, user_b = await _register_tenant(client)
    try:
        response = await client.request(
            method,
            path,
            headers={
                "Authorization": headers_a["Authorization"],
                "X-Company-Id": str(company_b),
            },
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"
    finally:
        await _cleanup(company_id=company_a, user_id=user_a)
        await _cleanup(company_id=company_b, user_id=user_b)


@pytest.mark.asyncio
async def test_patch_company_admin_allowed(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        profile = await client.get("/v1/companies/current", headers=headers)
        version = profile.json()["data"]["version"]
        response = await client.patch(
            "/v1/companies/current",
            headers={**headers, "If-Match": str(version)},
            json={"legal_name": "Acme Legal"},
        )
        assert response.status_code == 200
        assert response.json()["data"]["legal_name"] == "Acme Legal"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_patch_zero_permission_denied(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        profile = await client.get("/v1/companies/current", headers=headers)
        version = profile.json()["data"]["version"]
        await _strip_permission(company_id, ORG_COMPANY_MANAGE)
        response = await client.patch(
            "/v1/companies/current",
            headers={**headers, "If-Match": str(version)},
            json={"legal_name": "Blocked"},
        )
        assert response.status_code == 403
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_legal_entity_company_admin_allowed(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        create = await client.post(
            "/v1/legal-entities", headers=headers, json={"name": "Acme Pvt Ltd"}
        )
        assert create.status_code == 201
        listed = await client.get("/v1/legal-entities", headers=headers)
        assert listed.status_code == 200
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_legal_entity_zero_permission_denied(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        await _strip_permission(company_id, ORG_LEGAL_ENTITY_MANAGE)

        list_response = await client.get("/v1/legal-entities", headers=headers)
        assert list_response.status_code == 403
        assert list_response.json()["error"]["code"] == "PERMISSION_DENIED"

        create_response = await client.post(
            "/v1/legal-entities", headers=headers, json={"name": "Acme Pvt Ltd"}
        )
        assert create_response.status_code == 403
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_branch_company_admin_allowed(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        entity = await client.post(
            "/v1/legal-entities", headers=headers, json={"name": "Acme Pvt Ltd"}
        )
        entity_id = entity.json()["data"]["id"]
        create = await client.post(
            "/v1/branches", headers=headers, json={"legal_entity_id": entity_id, "name": "HQ"}
        )
        assert create.status_code == 201
        listed = await client.get("/v1/branches", headers=headers)
        assert listed.status_code == 200
    finally:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                text("DELETE FROM branch WHERE company_id = :cid"), {"cid": str(company_id)}
            )
            await session.commit()
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_branch_zero_permission_denied(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        await _strip_permission(company_id, ORG_BRANCH_MANAGE)

        list_response = await client.get("/v1/branches", headers=headers)
        assert list_response.status_code == 403
        assert list_response.json()["error"]["code"] == "PERMISSION_DENIED"

        create_response = await client.post(
            "/v1/branches", headers=headers, json={"legal_entity_id": str(uuid4()), "name": "HQ"}
        )
        assert create_response.status_code == 403
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_department_company_admin_allowed(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        create = await client.post("/v1/departments", headers=headers, json={"name": "Engineering"})
        assert create.status_code == 201
        listed = await client.get("/v1/departments", headers=headers)
        assert listed.status_code == 200
    finally:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                text("DELETE FROM department WHERE company_id = :cid"), {"cid": str(company_id)}
            )
            await session.commit()
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_department_zero_permission_denied(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        await _strip_permission(company_id, ORG_DEPARTMENT_MANAGE)

        list_response = await client.get("/v1/departments", headers=headers)
        assert list_response.status_code == 403
        assert list_response.json()["error"]["code"] == "PERMISSION_DENIED"

        create_response = await client.post(
            "/v1/departments", headers=headers, json={"name": "Engineering"}
        )
        assert create_response.status_code == 403
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_designation_company_admin_allowed(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        create = await client.post(
            "/v1/designations", headers=headers, json={"title": "Software Engineer"}
        )
        assert create.status_code == 201
        listed = await client.get("/v1/designations", headers=headers)
        assert listed.status_code == 200
    finally:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                text("DELETE FROM designation WHERE company_id = :cid"), {"cid": str(company_id)}
            )
            await session.commit()
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_designation_zero_permission_denied(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        await _strip_permission(company_id, ORG_DESIGNATION_MANAGE)

        list_response = await client.get("/v1/designations", headers=headers)
        assert list_response.status_code == 403
        assert list_response.json()["error"]["code"] == "PERMISSION_DENIED"

        create_response = await client.post(
            "/v1/designations", headers=headers, json={"title": "Software Engineer"}
        )
        assert create_response.status_code == 403
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_grade_company_admin_allowed(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        create = await client.post(
            "/v1/grades", headers=headers, json={"code": "L5", "name": "Senior Engineer"}
        )
        assert create.status_code == 201
        listed = await client.get("/v1/grades", headers=headers)
        assert listed.status_code == 200
    finally:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                text("DELETE FROM grade WHERE company_id = :cid"), {"cid": str(company_id)}
            )
            await session.commit()
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_grade_zero_permission_denied(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        await _strip_permission(company_id, ORG_GRADE_MANAGE)

        list_response = await client.get("/v1/grades", headers=headers)
        assert list_response.status_code == 403
        assert list_response.json()["error"]["code"] == "PERMISSION_DENIED"

        create_response = await client.post(
            "/v1/grades", headers=headers, json={"code": "L5", "name": "Senior Engineer"}
        )
        assert create_response.status_code == 403
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)
