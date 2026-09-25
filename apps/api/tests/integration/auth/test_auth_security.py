from uuid import UUID

import pytest
from httpx import AsyncClient

from hrms.core.auth.jwt import create_access_token
from hrms.seed.constants import (
    ADMIN_EMAIL,
    COMPANY_A_ID,
    COMPANY_B_ID,
    DEMO_PASSWORD,
    VIEWER_EMAIL,
)


@pytest.fixture
async def admin_tokens(client: AsyncClient, seeded_db: None) -> dict[str, str]:
    response = await client.post(
        "/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": DEMO_PASSWORD, "company_id": str(COMPANY_A_ID)},
    )
    assert response.status_code == 200
    body = response.json()
    # SEC-06 (RELEASE_HARDENING_PHASE_3A) — the refresh token is no longer in the JSON body; it
    # travels only as the HttpOnly `hrms_refresh` cookie on this specific response.
    refresh_token = response.cookies.get("hrms_refresh")
    assert refresh_token
    return {
        "access_token": body["data"]["access_token"],
        "refresh_token": refresh_token,
        "company_id": body["data"]["company_id"],
    }


@pytest.fixture
async def viewer_tokens(client: AsyncClient, seeded_db: None) -> dict[str, str]:
    response = await client.post(
        "/v1/auth/login",
        json={"email": VIEWER_EMAIL, "password": DEMO_PASSWORD, "company_id": str(COMPANY_A_ID)},
    )
    assert response.status_code == 200
    body = response.json()
    refresh_token = response.cookies.get("hrms_refresh")
    assert refresh_token
    return {
        "access_token": body["data"]["access_token"],
        "refresh_token": refresh_token,
    }


async def test_login_success(client: AsyncClient, seeded_db: None) -> None:
    response = await client.post(
        "/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": DEMO_PASSWORD},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["access_token"]
    # SEC-06 — no longer in the JSON body; only the HttpOnly cookie carries it.
    assert "refresh_token" not in data
    assert response.cookies.get("hrms_refresh")
    assert data["company_id"] == str(COMPANY_A_ID)
    assert len(data["companies"]) >= 2


async def test_login_invalid_password(client: AsyncClient, seeded_db: None) -> None:
    response = await client.post(
        "/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": "wrong-password"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_expired_access_token(
    client: AsyncClient, seeded_db: None, admin_tokens: dict[str, str]
) -> None:
    from uuid import uuid4

    from hrms.core.config.settings import get_settings

    settings = get_settings()
    me = await client.get(
        "/v1/auth/me",
        headers={"Authorization": f"Bearer {admin_tokens['access_token']}"},
    )
    assert me.status_code == 200
    user_id = UUID(me.json()["data"]["user"]["id"])

    expired_token = create_access_token(
        user_id=user_id,
        company_id=COMPANY_A_ID,
        session_id=uuid4(),
        employee_id=None,
        settings=settings,
        ttl_minutes=-1,
    )
    response = await client.get(
        "/v1/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


async def test_refresh_token_rotation(
    client: AsyncClient, seeded_db: None, admin_tokens: dict[str, str]
) -> None:
    old_refresh = admin_tokens["refresh_token"]
    first = await client.post("/v1/auth/token/refresh", json={"refresh_token": old_refresh})
    assert first.status_code == 200
    # SEC-06 — the rotated token is now only in the Set-Cookie header on this response.
    new_refresh = first.cookies.get("hrms_refresh")
    assert new_refresh
    assert new_refresh != old_refresh

    reuse = await client.post("/v1/auth/token/refresh", json={"refresh_token": old_refresh})
    assert reuse.status_code == 401
    assert reuse.json()["error"]["code"] == "INVALID_TOKEN"

    second = await client.post("/v1/auth/token/refresh", json={"refresh_token": new_refresh})
    assert second.status_code == 200


async def test_permission_denied(
    client: AsyncClient, seeded_db: None, viewer_tokens: dict[str, str]
) -> None:
    response = await client.get(
        "/v1/auth/admin/users-check",
        headers={"Authorization": f"Bearer {viewer_tokens['access_token']}"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"


async def test_cross_company_data_access_blocked(
    client: AsyncClient, seeded_db: None, admin_tokens: dict[str, str]
) -> None:
    response = await client.get(
        f"/v1/auth/companies/{COMPANY_B_ID}",
        headers={
            "Authorization": f"Bearer {admin_tokens['access_token']}",
            "X-Company-Id": str(COMPANY_A_ID),
        },
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


async def test_cross_company_header_mismatch_blocked(
    client: AsyncClient, seeded_db: None, admin_tokens: dict[str, str]
) -> None:
    response = await client.get(
        "/v1/auth/me",
        headers={
            "Authorization": f"Bearer {admin_tokens['access_token']}",
            "X-Company-Id": str(COMPANY_B_ID),
        },
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
