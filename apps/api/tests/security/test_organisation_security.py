"""C-16 — Security checks for the organisation company surface.

Covers docs/modules/company/06_Testing_Strategy.md §3:

- unauthenticated / invalid / malformed tokens
- mass-assignment rejection on PATCH
- structural: no ``{company_id}`` path params on organisation routes
- malformed branding / theme payloads
- registration password never appears in audit trail
"""

from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from tests.integration.modules.organisation.test_registration_flow import (
    _cleanup,
    _payload,
    _register,
)

from hrms.core.audit.models import AuditLog
from hrms.core.auth.jwt import create_access_token
from hrms.core.config.settings import get_settings
from hrms.core.db.session import get_session_factory
from hrms.modules.organisation.router import router as organisation_router


async def _auth_headers(
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
@pytest.mark.parametrize(
    "path",
    [
        "/v1/companies/current",
        "/v1/companies/current/setup-progress",
        "/v1/companies/current/subscription",
        "/v1/dashboards/company",
        "/v1/legal-entities",
        "/v1/branches",
        "/v1/departments",
        "/v1/designations",
        "/v1/grades",
    ],
)
async def test_unauthenticated_requests_rejected(
    client: AsyncClient, seeded_plan_catalogue: None, path: str
) -> None:
    response = await client.get(path)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_malformed_token_rejected(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    response = await client.get(
        "/v1/companies/current",
        headers={"Authorization": "Bearer not-a-jwt", "X-Company-Id": str(uuid4())},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_expired_token_rejected(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _auth_headers(client)
    try:
        assert user_id is not None
        settings = get_settings()
        expired = create_access_token(
            user_id=user_id,
            company_id=company_id,
            session_id=uuid4(),
            employee_id=None,
            settings=settings,
            ttl_minutes=-1,
        )
        response = await client.get(
            "/v1/companies/current",
            headers={"Authorization": f"Bearer {expired}", "X-Company-Id": str(company_id)},
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "INVALID_TOKEN"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_patch_mass_assignment_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _auth_headers(client)
    try:
        profile = await client.get("/v1/companies/current", headers=headers)
        data = profile.json()["data"]
        version = data["version"]

        response = await client.patch(
            "/v1/companies/current",
            headers={**headers, "If-Match": str(version)},
            json={
                "legal_name": "Allowed Field",
                "status": "ACTIVE",
                "id": str(uuid4()),
                "subdomain": "hijacked",
                "version": 999,
            },
        )
        # Extra immutable fields are forbidden by schema (extra=forbid) → 422.
        assert response.status_code == 422

        after = await client.get("/v1/companies/current", headers=headers)
        assert after.json()["data"]["status"] == data["status"]
        assert after.json()["data"]["subdomain"] == data["subdomain"]
        assert after.json()["data"]["id"] == data["id"]
        assert after.json()["data"]["version"] == version
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_patch_malformed_theme_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _auth_headers(client)
    try:
        profile = await client.get("/v1/companies/current", headers=headers)
        version = profile.json()["data"]["version"]
        response = await client.patch(
            "/v1/companies/current",
            headers={**headers, "If-Match": str(version)},
            json={"branding": {"logo_url": None, "theme": {"primary_color": 12345}}},
        )
        assert response.status_code == 422
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_registration_password_not_in_audit(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    password = "CorrectHorse9"
    response, company_id, user_id = await _register(
        client, admin_password=password, admin_email=f"sec-{uuid4().hex[:8]}@acme.example"
    )
    assert response.status_code == 201
    assert company_id is not None
    try:
        factory = get_session_factory()
        async with factory() as session:
            rows = (
                (await session.execute(select(AuditLog).where(AuditLog.company_id == company_id)))
                .scalars()
                .all()
            )
            blob = " ".join(
                str(row.before_json) + str(row.after_json) + str(row.action) for row in rows
            )
            assert password not in blob
            assert "admin_password" not in blob
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


def test_organisation_router_has_no_company_id_path_params() -> None:
    """Structural IDOR guard — no organisation route may accept a company id path param."""
    for route in organisation_router.routes:
        path = getattr(route, "path", "")
        assert "{company_id}" not in path
        assert "{id}" not in path


@pytest.mark.asyncio
async def test_register_rejects_unexpected_fields(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    body = _payload()
    body["status"] = "ACTIVE"
    response = await client.post("/v1/companies/register", json=body)
    # Registration schema does not set extra=forbid today — ensure status is not applied
    # by checking either 422 or that a successful create still starts as TRIAL.
    if response.status_code == 201:
        company_id = UUID(response.json()["data"]["company_id"])
        user_id = None
        try:
            headers = {
                "Authorization": f"Bearer {response.json()['data']['access_token']}",
                "X-Company-Id": str(company_id),
            }
            profile = await client.get("/v1/companies/current", headers=headers)
            assert profile.json()["data"]["status"] == "TRIAL"
            from hrms.core.db.models.identity import Company

            factory = get_session_factory()
            async with factory() as session:
                row = (
                    await session.execute(select(Company).where(Company.id == company_id))
                ).scalar_one()
                user_id = row.created_by
        finally:
            await _cleanup(company_id=company_id, user_id=user_id)
    else:
        assert response.status_code == 422
