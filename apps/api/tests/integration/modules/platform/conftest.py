"""Fixtures for the platform console suite: approval is switched ON (the suite-wide default in
`tests/conftest.py` is OFF so the other modules' registrations keep landing in TRIAL), a platform
admin is created directly in the database, and tenants are registered through the real API."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import pytest
import redis.asyncio as redis
from httpx import AsyncClient
from sqlalchemy import text

from hrms.core.auth.passwords import hash_password
from hrms.core.config.settings import get_settings
from hrms.core.db.session import get_session_factory
from hrms.modules.platform.models import PlatformAdmin

from ..account_invite.conftest import seeded_plan_catalogue  # noqa: F401
from ..organisation.test_registration_flow import VALID_PASSWORD, _cleanup, _payload

PLATFORM_PASSWORD = "Platform-Pass-9"


@pytest.fixture(autouse=True)
async def _approval_required(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    monkeypatch.setenv("COMPANY_APPROVAL_REQUIRED", "true")
    get_settings.cache_clear()
    client = redis.from_url(get_settings().redis_url, decode_responses=True)
    for pattern in ("ratelimit:platform_login:*", "ratelimit:auth:*"):
        async for key in client.scan_iter(match=pattern):
            await client.delete(key)
    yield
    await client.aclose()


@dataclass
class PlatformAdminCtx:
    admin_id: UUID
    username: str
    headers: dict[str, str]


@dataclass
class TenantCtx:
    company_id: UUID
    user_id: UUID
    email: str
    name: str
    headers: dict[str, str]


async def login_platform(client: AsyncClient, username: str, password: str) -> Any:
    return await client.post(
        "/v1/platform/auth/login", json={"username": username, "password": password}
    )


@pytest.fixture
async def platform_admin(client: AsyncClient) -> AsyncIterator[PlatformAdminCtx]:
    username = f"pa-{uuid4().hex[:10]}"
    admin_id = uuid4()
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            PlatformAdmin(
                id=admin_id, username=username, password_hash=hash_password(PLATFORM_PASSWORD)
            )
        )
        await session.commit()
    response = await login_platform(client, username, PLATFORM_PASSWORD)
    assert response.status_code == 200, response.text
    token = response.json()["data"]["access_token"]
    try:
        yield PlatformAdminCtx(admin_id, username, {"Authorization": f"Bearer {token}"})
    finally:
        async with factory() as session:
            await session.execute(
                text("DELETE FROM platform_admin WHERE id = :i"), {"i": str(admin_id)}
            )
            await session.commit()


@pytest.fixture
async def make_tenant(
    client: AsyncClient,
    seeded_plan_catalogue: None,  # noqa: F811
) -> AsyncIterator[Any]:
    created: list[tuple[UUID, UUID]] = []

    async def _make(verified: bool = True) -> TenantCtx:
        payload = _payload()
        response = await client.post("/v1/companies/register", json=payload)
        assert response.status_code == 201, response.text
        data = response.json()["data"]
        company_id = UUID(data["company_id"])
        factory = get_session_factory()
        async with factory() as session:
            user_id = (
                await session.execute(
                    text('SELECT id FROM "user" WHERE email = :e'), {"e": payload["admin_email"]}
                )
            ).scalar_one()
            if verified:
                await session.execute(
                    text('UPDATE "user" SET email_verified_at = now() WHERE id = :i'),
                    {"i": str(user_id)},
                )
                await session.commit()
        created.append((company_id, user_id))
        return TenantCtx(
            company_id=company_id,
            user_id=user_id,
            email=payload["admin_email"],
            name=payload["name"],
            headers={
                "Authorization": f"Bearer {data['access_token']}",
                "X-Company-Id": str(company_id),
            },
        )

    yield _make
    for company_id, user_id in created:
        await _cleanup(company_id=company_id, user_id=user_id)


TENANT_PASSWORD = VALID_PASSWORD
