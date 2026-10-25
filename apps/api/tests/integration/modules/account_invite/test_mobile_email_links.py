"""API audit H-3 - token emails carry an optional link into the mobile app.

No mail is sent: `get_email_sender` is replaced by a capturing sender in the two modules that call
it. The default (no `MOBILE_APP_LINK_BASE`) must leave every email exactly as it was."""

import re
from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import text

from hrms.core.config.settings import Settings, get_settings
from hrms.core.db.session import get_session_factory
from hrms.core.links import mobile_link
from hrms.core.observability.redaction import REDACTED, redact_text

from ..organisation.test_registration_flow import VALID_PASSWORD
from .test_account_invite import _create_employee, _register_tenant
from .test_account_invite import _teardown as _base_teardown
from .uac_helpers import reset_auth_rate_limit

pytestmark = pytest.mark.asyncio


async def _teardown(
    *, company_id: Any, user_id: Any, extra_emails: list[str] | None = None
) -> None:
    """Also drops the one-time tokens these tests create (FK to `user`)."""
    factory = get_session_factory()
    async with factory() as session:
        for table in ("password_reset_token", "email_verification_token"):
            await session.execute(
                text(
                    f'DELETE FROM {table} WHERE user_id IN (SELECT id FROM "user" '
                    "WHERE id = :uid OR email = ANY(:emails))"
                ),
                {"uid": str(user_id), "emails": extra_emails or []},
            )
        await session.commit()
    await _base_teardown(company_id=company_id, user_id=user_id, extra_emails=extra_emails)


class _Capture:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def send(self, *, to: str, subject: str, html_body: str, text_body: str) -> None:
        self.sent.append({"to": to, "subject": subject, "html": html_body, "text": text_body})


@pytest.fixture
def capture(monkeypatch: pytest.MonkeyPatch) -> _Capture:
    cap = _Capture()
    for mod in ("identity", "account_invite", "onboarding"):
        monkeypatch.setattr(
            f"hrms.modules.{mod}.service.get_email_sender",
            lambda settings, _c=cap: _c,
            raising=False,
        )
    return cap


def _tokens(body: str) -> dict[str, str]:
    return {
        "web": re.search(
            r"https?://[^\s\"<]+/(?:reset-password|verify-email|accept-invite|onboarding)/([\w-]+)",
            body,
        ).group(1),  # type: ignore[union-attr]
        "app": (
            re.search(
                r"hrms://app/(?:reset-password|verify-email|accept-invite|onboarding)/([\w-]+)",
                body,
            )
            or [None, None]
        )[1],  # type: ignore[index]
    }


async def test_reset_and_verification_emails_have_no_app_link_by_default(
    client: AsyncClient, seeded_plan_catalogue: None, capture: _Capture
) -> None:
    headers, company_id, user_id = await _register_tenant(
        client, admin_email=f"m-{uuid4().hex[:8]}@example.com"
    )
    try:
        email = capture.sent[0]["to"] if capture.sent else None
        await client.post("/v1/auth/password/forgot", json={"email": email or "x@example.com"})
        assert all("hrms://" not in m["text"] and "hrms://" not in m["html"] for m in capture.sent)
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_mobile_link_added_with_the_same_token_when_configured(
    client: AsyncClient,
    seeded_plan_catalogue: None,
    capture: _Capture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MOBILE_APP_LINK_BASE", "hrms://app/")
    get_settings.cache_clear()
    email = f"m-{uuid4().hex[:8]}@example.com"
    invitee = f"inv-{uuid4().hex[:8]}@example.com"
    headers, company_id, user_id = await _register_tenant(client, admin_email=email)
    try:
        # registration -> verification email
        verify = capture.sent[-1]
        t = _tokens(verify["text"])
        assert t["app"] == t["web"], "app link must carry the very same one-time token"
        assert "hrms://app/verify-email/" in verify["html"]

        employee = await _create_employee(client, headers, personal_email=invitee)
        assert (
            await client.post(f"/v1/employees/{employee['id']}/invite", headers=headers)
        ).status_code == 201
        invite = capture.sent[-1]
        assert invite["to"] == invitee
        t = _tokens(invite["text"])
        assert t["app"] == t["web"] and "hrms://app/accept-invite/" in invite["html"]
        resolved = await client.get(f"/v1/public/account-invites/{t['app']}")
        assert resolved.status_code == 200
        # a reset revokes every session (SEC-07), so it runs after the admin-authenticated steps
        await reset_auth_rate_limit()
        assert (
            await client.post("/v1/auth/password/forgot", json={"email": email})
        ).status_code == 202
        reset = capture.sent[-1]
        t = _tokens(reset["text"])
        assert t["app"] == t["web"] and "hrms://app/reset-password/" in reset["text"]
        # the token works exactly like the web one
        ok = await client.post(
            "/v1/auth/password/reset", json={"token": t["app"], "password": VALID_PASSWORD + "x1"}
        )
        assert ok.status_code == 200, ok.text
        # single use: replaying the same token (from either link) is refused
        again = await client.post(
            "/v1/auth/password/reset", json={"token": t["app"], "password": VALID_PASSWORD + "y2"}
        )
        assert again.status_code == 401 and again.json()["error"]["code"] == "INVALID_TOKEN"

    finally:
        await _teardown(company_id=company_id, user_id=user_id, extra_emails=[invitee])


async def test_invalid_and_expired_tokens_are_uniformly_rejected(client: AsyncClient) -> None:
    await reset_auth_rate_limit()
    bad: dict[str, Any] = {"token": "not-a-real-token", "password": VALID_PASSWORD}
    for path in ("/v1/auth/password/reset",):
        r = await client.post(path, json=bad)
        assert r.status_code == 401 and r.json()["error"]["code"] == "INVALID_TOKEN"
    r = await client.post("/v1/auth/email/verify", json={"token": "not-a-real-token"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "INVALID_TOKEN"
    assert (await client.get("/v1/public/account-invites/not-a-real-token")).status_code == 404


def test_mobile_app_link_base_validation_and_helper() -> None:
    assert Settings(mobile_app_link_base="hrms://app/").mobile_app_link_base == "hrms://app"
    assert Settings().mobile_app_link_base == ""
    for bad in ("javascript:alert(1)", "hrms://app/path?x=1", "not a url", "hrms://"):
        with pytest.raises(ValidationError):
            Settings(mobile_app_link_base=bad)
    s = Settings(mobile_app_link_base="hrms://app")
    assert mobile_link(s, "reset-password", "tok") == "hrms://app/reset-password/tok"
    assert mobile_link(Settings(), "reset-password", "tok") is None


def test_app_links_are_redacted_in_logs() -> None:
    for path in ("reset-password", "verify-email", "accept-invite", "onboarding"):
        out = redact_text(f"opened hrms://app/{path}/SECRETTOKEN123 now")
        assert "SECRETTOKEN123" not in out and REDACTED in out
