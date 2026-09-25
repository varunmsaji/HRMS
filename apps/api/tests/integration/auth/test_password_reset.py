"""Integration tests for Phase 3 of `docs/modules/employee/
41_EMPLOYEE_ACCOUNT_PROVISIONING_LOGIN_AUDIT_AND_PLAN.md` —
`POST /auth/password/forgot` / `POST /auth/password/reset`.

Uses the fixed demo seed (`seeded_db`, same fixture `test_auth_security.py` already relies on)
rather than registering a fresh tenant — these endpoints act on a `User`'s password only, with no
tenant-scoped data to set up."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from hrms.core.auth.passwords import verify_password
from hrms.core.db.models.identity import PasswordResetToken, User
from hrms.core.db.session import get_session_factory
from hrms.seed.constants import ADMIN_EMAIL, ADMIN_USER_ID, DEMO_PASSWORD

NEW_PASSWORD = "BrandNewPass9"


async def _cleanup_reset_tokens() -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("DELETE FROM password_reset_token WHERE user_id = :uid"),
            {"uid": str(ADMIN_USER_ID)},
        )
        await session.commit()


async def _restore_admin_password() -> None:
    """Tests that successfully reset the password must not leak a changed credential into later
    tests sharing the same fixed seed user."""
    from hrms.core.auth.passwords import hash_password

    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text('UPDATE "user" SET password_hash = :hash WHERE id = :uid'),
            {"hash": hash_password(DEMO_PASSWORD), "uid": str(ADMIN_USER_ID)},
        )
        await session.commit()


async def _latest_raw_reset_token(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """`forgot_password` never returns the raw token (only the hash is persisted) — capture it
    the same way production would only ever see it: intercept the email send. Deliberately
    unlike the onboarding invite tests (which read `invite_url` straight out of the authenticated
    admin API response) — a public, unauthenticated forgot-password endpoint must never return
    the reset link in its own response body, so there is no API-response shortcut here."""
    captured: list[str] = []

    async def _fake_send(
        self: object, *, to: str, subject: str, html_body: str, text_body: str
    ) -> None:
        captured.append(text_body)

    from hrms.modules.onboarding import email_sender

    monkeypatch.setattr(email_sender.LoggingEmailSender, "send", _fake_send)
    return captured


def _extract_token(text_body: str) -> str:
    url = next(line for line in text_body.split() if "/reset-password/" in line)
    return url.rsplit("/", 1)[-1]


@pytest.mark.asyncio
async def test_forgot_password_existing_user_issues_token(
    client: AsyncClient, seeded_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = await _latest_raw_reset_token(monkeypatch)
    try:
        response = await client.post("/v1/auth/password/forgot", json={"email": ADMIN_EMAIL})
        assert response.status_code == 202
        assert response.json()["data"] == {"accepted": True}
        assert len(captured) == 1

        factory = get_session_factory()
        async with factory() as session:
            token_row = (
                await session.execute(
                    select(PasswordResetToken).where(PasswordResetToken.user_id == ADMIN_USER_ID)
                )
            ).scalar_one()
            assert token_row.used_at is None
            assert token_row.expires_at > datetime.now(UTC)
    finally:
        await _cleanup_reset_tokens()


@pytest.mark.asyncio
async def test_forgot_password_unknown_email_returns_identical_response(
    client: AsyncClient, seeded_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Anti-enumeration: the response must not reveal whether the email matches an account."""
    captured = await _latest_raw_reset_token(monkeypatch)
    response = await client.post(
        "/v1/auth/password/forgot", json={"email": "nobody-here@example.com"}
    )
    assert response.status_code == 202
    assert response.json()["data"] == {"accepted": True}
    assert captured == []  # no email actually sent, but the caller can't tell from the response


@pytest.mark.asyncio
async def test_reset_password_success_changes_password_and_single_use(
    client: AsyncClient, seeded_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = await _latest_raw_reset_token(monkeypatch)
    try:
        await client.post("/v1/auth/password/forgot", json={"email": ADMIN_EMAIL})
        raw_token = _extract_token(captured[0])

        reset_response = await client.post(
            "/v1/auth/password/reset", json={"token": raw_token, "password": NEW_PASSWORD}
        )
        assert reset_response.status_code == 200
        assert reset_response.json()["data"] == {"reset": True}

        old_login = await client.post(
            "/v1/auth/login", json={"email": ADMIN_EMAIL, "password": DEMO_PASSWORD}
        )
        assert old_login.status_code == 401

        new_login = await client.post(
            "/v1/auth/login", json={"email": ADMIN_EMAIL, "password": NEW_PASSWORD}
        )
        assert new_login.status_code == 200

        factory = get_session_factory()
        async with factory() as session:
            user = (
                await session.execute(select(User).where(User.id == ADMIN_USER_ID))
            ).scalar_one()
            assert verify_password(user.password_hash, NEW_PASSWORD)

        reuse_response = await client.post(
            "/v1/auth/password/reset", json={"token": raw_token, "password": "AnotherPass9"}
        )
        assert reuse_response.status_code == 401
        assert reuse_response.json()["error"]["code"] == "INVALID_TOKEN"
    finally:
        await _restore_admin_password()
        await _cleanup_reset_tokens()


@pytest.mark.asyncio
async def test_reset_password_invalidates_existing_access_and_refresh_token(
    client: AsyncClient, seeded_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEC-07 — a password reset must end sessions that were already issued before the reset, not
    only change the credential. Without this, an attacker who already holds a valid access token
    keeps working until its own short expiry, and a stolen refresh token would keep minting new
    access tokens indefinitely — the new password alone would do nothing to stop either."""
    captured = await _latest_raw_reset_token(monkeypatch)
    try:
        login_response = await client.post(
            "/v1/auth/login", json={"email": ADMIN_EMAIL, "password": DEMO_PASSWORD}
        )
        assert login_response.status_code == 200
        old_tokens = login_response.json()["data"]
        # SEC-06 (RELEASE_HARDENING_PHASE_3A) — the refresh token is only in the HttpOnly cookie.
        old_refresh_token = login_response.cookies.get("hrms_refresh")
        assert old_refresh_token

        me_before = await client.get(
            "/v1/auth/me", headers={"Authorization": f"Bearer {old_tokens['access_token']}"}
        )
        assert me_before.status_code == 200

        await client.post("/v1/auth/password/forgot", json={"email": ADMIN_EMAIL})
        raw_token = _extract_token(captured[0])
        reset_response = await client.post(
            "/v1/auth/password/reset", json={"token": raw_token, "password": NEW_PASSWORD}
        )
        assert reset_response.status_code == 200

        me_after = await client.get(
            "/v1/auth/me", headers={"Authorization": f"Bearer {old_tokens['access_token']}"}
        )
        assert me_after.status_code == 401
        assert me_after.json()["error"]["code"] == "INVALID_TOKEN"

        refresh_after = await client.post(
            "/v1/auth/token/refresh", json={"refresh_token": old_refresh_token}
        )
        assert refresh_after.status_code == 401
        assert refresh_after.json()["error"]["code"] == "INVALID_TOKEN"
    finally:
        await _restore_admin_password()
        await _cleanup_reset_tokens()


@pytest.mark.asyncio
async def test_reset_password_invalidates_every_session_not_only_one(
    client: AsyncClient, seeded_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEC-07 — every session for the user must be revoked, not only the browser/device that
    happened to perform the reset (two independent logins here stand in for two devices)."""
    captured = await _latest_raw_reset_token(monkeypatch)
    try:
        session_a = (
            await client.post(
                "/v1/auth/login", json={"email": ADMIN_EMAIL, "password": DEMO_PASSWORD}
            )
        ).json()["data"]
        session_b = (
            await client.post(
                "/v1/auth/login", json={"email": ADMIN_EMAIL, "password": DEMO_PASSWORD}
            )
        ).json()["data"]
        assert session_a["access_token"] != session_b["access_token"]

        await client.post("/v1/auth/password/forgot", json={"email": ADMIN_EMAIL})
        raw_token = _extract_token(captured[0])
        reset_response = await client.post(
            "/v1/auth/password/reset", json={"token": raw_token, "password": NEW_PASSWORD}
        )
        assert reset_response.status_code == 200

        for stale_session in (session_a, session_b):
            me = await client.get(
                "/v1/auth/me",
                headers={"Authorization": f"Bearer {stale_session['access_token']}"},
            )
            assert me.status_code == 401
    finally:
        await _restore_admin_password()
        await _cleanup_reset_tokens()


@pytest.mark.asyncio
async def test_reset_password_unknown_token_rejected(client: AsyncClient, seeded_db: None) -> None:
    response = await client.post(
        "/v1/auth/password/reset", json={"token": "not-a-real-token", "password": NEW_PASSWORD}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


@pytest.mark.asyncio
async def test_reset_password_weak_password_rejected(
    client: AsyncClient, seeded_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = await _latest_raw_reset_token(monkeypatch)
    try:
        await client.post("/v1/auth/password/forgot", json={"email": ADMIN_EMAIL})
        raw_token = _extract_token(captured[0])

        response = await client.post(
            "/v1/auth/password/reset", json={"token": raw_token, "password": "short"}
        )
        assert response.status_code == 422
        assert response.json()["error"]["details"][0]["code"] == "WEAK_PASSWORD"
    finally:
        await _cleanup_reset_tokens()


@pytest.mark.asyncio
async def test_reset_password_expired_token_rejected(
    client: AsyncClient, seeded_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = await _latest_raw_reset_token(monkeypatch)
    try:
        await client.post("/v1/auth/password/forgot", json={"email": ADMIN_EMAIL})
        raw_token = _extract_token(captured[0])

        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                text("UPDATE password_reset_token SET expires_at = :past WHERE user_id = :uid"),
                {"past": datetime.now(UTC) - timedelta(hours=1), "uid": str(ADMIN_USER_ID)},
            )
            await session.commit()

        response = await client.post(
            "/v1/auth/password/reset", json={"token": raw_token, "password": NEW_PASSWORD}
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "INVALID_TOKEN"
    finally:
        await _cleanup_reset_tokens()
