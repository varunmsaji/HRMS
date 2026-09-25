"""SEC-09 (RELEASE_HARDENING_PHASE_3A_SECURITY_REMEDIATION.md) — email verification.

Registers a fresh tenant for each test (mirrors `test_registration_flow.py`'s own pattern) rather
than using the fixed `seeded_db` demo users, which are already treated as verified (the
`email_verified_at` column defaults to "now" — see `core/db/models/identity.py`'s own docstring —
precisely so this suite is the only place that needs to exercise the unverified path at all."""

from datetime import UTC
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from hrms.core.audit.models import AuditLog
from hrms.core.db.models.identity import (
    Company,
    RefreshToken,
    Role,
    RolePermission,
    Session,
    User,
    UserCompany,
    UserRole,
)
from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.organisation.models import CompanyFeatureFlag, CompanySetupProgress, LegalEntity

VALID_PASSWORD = "CorrectHorse9"


def _payload(**overrides: Any) -> dict[str, Any]:
    unique = uuid4().hex[:10]
    body = {
        "name": f"Verify {unique}",
        "industry_code": "MANUFACTURING",
        "company_size": "51-200",
        "admin_first_name": "Priya",
        "admin_last_name": "Sharma",
        "admin_email": f"verify-{unique}@acme.example",
        "admin_password": VALID_PASSWORD,
    }
    body.update(overrides)
    return body


async def _cleanup(*, company_id: UUID | None, user_id: UUID | None) -> None:
    factory = get_session_factory()
    async with factory() as session:
        if company_id is not None:
            await set_rls_company_id(session, str(company_id))
            await session.execute(
                AuditLog.__table__.delete().where(AuditLog.company_id == company_id)
            )
            await session.execute(
                LegalEntity.__table__.delete().where(LegalEntity.company_id == company_id)
            )
            await session.execute(
                CompanySetupProgress.__table__.delete().where(
                    CompanySetupProgress.company_id == company_id
                )
            )
            await session.execute(
                CompanyFeatureFlag.__table__.delete().where(
                    CompanyFeatureFlag.company_id == company_id
                )
            )
            await session.execute(
                UserRole.__table__.delete().where(
                    UserRole.user_company_id.in_(
                        select(UserCompany.id).where(UserCompany.company_id == company_id)
                    )
                )
            )
            await session.execute(
                RolePermission.__table__.delete().where(
                    RolePermission.role_id.in_(select(Role.id).where(Role.company_id == company_id))
                )
            )
            await session.execute(
                UserCompany.__table__.delete().where(UserCompany.company_id == company_id)
            )
            await session.execute(Role.__table__.delete().where(Role.company_id == company_id))
        if user_id is not None:
            await session.execute(
                RefreshToken.__table__.delete().where(RefreshToken.user_id == user_id)
            )
            await session.execute(Session.__table__.delete().where(Session.user_id == user_id))
            # `email_verification_token` cascades on `User` delete (its own migration) — no
            # explicit cleanup needed here.
            await session.execute(User.__table__.delete().where(User.id == user_id))
        if company_id is not None:
            await session.execute(Company.__table__.delete().where(Company.id == company_id))
        await session.commit()


async def _register(client: AsyncClient, **overrides: Any) -> tuple[Any, UUID | None, UUID | None]:
    response = await client.post("/v1/companies/register", json=_payload(**overrides))
    company_id: UUID | None = None
    user_id: UUID | None = None
    if response.status_code == 201:
        data = response.json()["data"]
        company_id = UUID(data["company_id"])
        factory = get_session_factory()
        async with factory() as session:
            row = (
                await session.execute(select(Company).where(Company.id == company_id))
            ).scalar_one()
            user_id = row.created_by
    return response, company_id, user_id


async def _latest_verification_email(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Same interception pattern `test_password_reset.py::_latest_raw_reset_token` uses — a
    public endpoint must never hand the raw token back in its own response, so the only way to
    observe it in a test is to intercept the (logging-only, in this test environment) send."""
    captured: list[str] = []

    async def _fake_send(
        self: object, *, to: str, subject: str, html_body: str, text_body: str
    ) -> None:
        captured.append(text_body)

    from hrms.modules.onboarding import email_sender

    monkeypatch.setattr(email_sender.LoggingEmailSender, "send", _fake_send)
    return captured


def _extract_token(text_body: str) -> str:
    url = next(line for line in text_body.split() if "/verify-email/" in line)
    return url.rsplit("/", 1)[-1]


@pytest.mark.asyncio
async def test_registration_sends_a_verification_email(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = await _latest_verification_email(monkeypatch)
    company_id: UUID | None = None
    user_id: UUID | None = None
    try:
        response, company_id, user_id = await _register(client)
        assert response.status_code == 201
        assert len(captured) == 1
        assert "/verify-email/" in captured[0]
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_registration_session_works_immediately_even_though_unverified(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The registrant's own first session (issued directly by `issue_tokens_for`, never through
    `login`) must not be blocked — only a *subsequent* login attempt is."""
    await _latest_verification_email(monkeypatch)
    company_id: UUID | None = None
    user_id: UUID | None = None
    try:
        response, company_id, user_id = await _register(client)
        access_token = response.json()["data"]["access_token"]
        me = await client.get("/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"})
        assert me.status_code == 200
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_login_blocked_until_email_verified(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _latest_verification_email(monkeypatch)
    company_id: UUID | None = None
    user_id: UUID | None = None
    try:
        payload = _payload()
        response, company_id, user_id = await _register(client, **payload)
        assert response.status_code == 201

        login = await client.post(
            "/v1/auth/login",
            json={"email": payload["admin_email"], "password": payload["admin_password"]},
        )
        assert login.status_code == 403
        assert login.json()["error"]["code"] == "EMAIL_NOT_VERIFIED"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_verify_email_then_login_succeeds(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = await _latest_verification_email(monkeypatch)
    company_id: UUID | None = None
    user_id: UUID | None = None
    try:
        payload = _payload()
        response, company_id, user_id = await _register(client, **payload)
        assert response.status_code == 201
        raw_token = _extract_token(captured[0])

        verify = await client.post("/v1/auth/email/verify", json={"token": raw_token})
        assert verify.status_code == 200
        assert verify.json()["data"] == {"verified": True}

        login = await client.post(
            "/v1/auth/login",
            json={"email": payload["admin_email"], "password": payload["admin_password"]},
        )
        assert login.status_code == 200
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_verify_email_token_is_single_use(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = await _latest_verification_email(monkeypatch)
    company_id: UUID | None = None
    user_id: UUID | None = None
    try:
        response, company_id, user_id = await _register(client)
        raw_token = _extract_token(captured[0])

        first = await client.post("/v1/auth/email/verify", json={"token": raw_token})
        assert first.status_code == 200

        replay = await client.post("/v1/auth/email/verify", json={"token": raw_token})
        assert replay.status_code == 401
        assert replay.json()["error"]["code"] == "INVALID_TOKEN"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_verify_email_invalid_token_rejected(client: AsyncClient) -> None:
    response = await client.post("/v1/auth/email/verify", json={"token": "not-a-real-token"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


@pytest.mark.asyncio
async def test_verify_email_expired_token_rejected(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import datetime, timedelta

    from sqlalchemy import text

    captured = await _latest_verification_email(monkeypatch)
    company_id: UUID | None = None
    user_id: UUID | None = None
    try:
        response, company_id, user_id = await _register(client)
        raw_token = _extract_token(captured[0])

        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                text(
                    "UPDATE email_verification_token SET expires_at = :expired WHERE user_id = :uid"
                ),
                {"expired": datetime.now(UTC) - timedelta(hours=1), "uid": str(user_id)},
            )
            await session.commit()

        expired = await client.post("/v1/auth/email/verify", json={"token": raw_token})
        assert expired.status_code == 401
        assert expired.json()["error"]["code"] == "INVALID_TOKEN"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_resend_verification_unknown_email_returns_identical_response(
    client: AsyncClient,
) -> None:
    """Anti-enumeration, same posture as `forgot_password` — the endpoint must respond
    identically whether or not the address belongs to a real, unverified account."""
    response = await client.post(
        "/v1/auth/email/resend-verification", json={"email": "nobody-here@example.com"}
    )
    assert response.status_code == 202
    assert response.json()["data"] == {"accepted": True}


@pytest.mark.asyncio
async def test_resend_verification_issues_a_new_usable_token(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = await _latest_verification_email(monkeypatch)
    company_id: UUID | None = None
    user_id: UUID | None = None
    try:
        payload = _payload()
        response, company_id, user_id = await _register(client, **payload)
        assert len(captured) == 1

        resend = await client.post(
            "/v1/auth/email/resend-verification", json={"email": payload["admin_email"]}
        )
        assert resend.status_code == 202
        assert len(captured) == 2

        new_token = _extract_token(captured[1])
        verify = await client.post("/v1/auth/email/verify", json={"token": new_token})
        assert verify.status_code == 200
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_resend_verification_already_verified_does_not_send_another_email(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = await _latest_verification_email(monkeypatch)
    company_id: UUID | None = None
    user_id: UUID | None = None
    try:
        payload = _payload()
        response, company_id, user_id = await _register(client, **payload)
        raw_token = _extract_token(captured[0])
        await client.post("/v1/auth/email/verify", json={"token": raw_token})

        resend = await client.post(
            "/v1/auth/email/resend-verification", json={"email": payload["admin_email"]}
        )
        assert resend.status_code == 202
        # Still just the one email from registration — verified accounts don't get re-sent one.
        assert len(captured) == 1
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)
