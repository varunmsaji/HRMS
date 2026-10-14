"""LOG-07 — operational `security.*` events through the real app and test database.

Each test asserts (a) the event and its safe fields, (b) that no credential, token or raw email
address reaches stdout, and (c) that the client-facing behaviour is unchanged. The last test
proves a broken log sink cannot weaken lockout. Log output is read from the real stdout pipe."""

import json
from typing import Any

import pytest
from httpx import AsyncClient
from pytest import CaptureFixture

from hrms.core.observability import security_events
from hrms.seed.constants import (
    ADMIN_EMAIL,
    COMPANY_A_ID,
    COMPANY_B_ID,
    DEMO_PASSWORD,
    VIEWER_EMAIL,
)

WRONG_PASSWORD = "Wr0ng-SENTINEL-pw"


def _events(raw: str, prefix: str = "security.") -> list[dict[str, Any]]:
    out = []
    for line in raw.splitlines():
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict) and str(parsed.get("event", "")).startswith(prefix):
            out.append(parsed)
    return out


def _named(events: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [e for e in events if e["event"] == name]


async def _login(client: AsyncClient, email: str, password: str) -> Any:
    return await client.post("/v1/auth/login", json={"email": email, "password": password})


async def test_failed_logins_then_lockout(
    client: AsyncClient, seeded_db: None, capfd: CaptureFixture[str]
) -> None:
    capfd.readouterr()
    statuses = [(await _login(client, VIEWER_EMAIL, WRONG_PASSWORD)).status_code for _ in range(6)]
    raw = capfd.readouterr().out

    assert statuses == [401] * 5 + [423]  # client contract unchanged
    events = _events(raw)
    failed = _named(events, "security.login.failed")
    assert [e["reason"] for e in failed] == ["bad_password"] * 5 + ["account_locked"]
    assert [e.get("failed_attempts") for e in failed[:5]] == [1, 2, 3, 4, 5]
    assert all(e["level"] == "warning" and e["user_id"] for e in failed)
    (locked,) = _named(events, "security.account.locked")
    assert locked["failed_attempts"] == 5
    assert locked["locked_until"]
    assert WRONG_PASSWORD not in raw
    assert VIEWER_EMAIL not in raw


async def test_unknown_account_is_pseudonymous_and_stable(
    client: AsyncClient, seeded_db: None, capfd: CaptureFixture[str]
) -> None:
    email = "nobody-sentinel@example.com"
    capfd.readouterr()
    for _ in range(2):
        assert (await _login(client, email, WRONG_PASSWORD)).status_code == 401
    raw = capfd.readouterr().out
    failed = _named(_events(raw), "security.login.failed")
    assert len(failed) == 2
    assert {e["reason"] for e in failed} == {"unknown_account"}
    assert failed[0]["user_id"] is None
    assert failed[0]["subject_hash"] == failed[1]["subject_hash"]
    assert len(failed[0]["subject_hash"]) == 16
    assert email not in raw and WRONG_PASSWORD not in raw


async def test_successful_login_and_logout(
    client: AsyncClient, seeded_db: None, capfd: CaptureFixture[str]
) -> None:
    capfd.readouterr()
    response = await _login(client, ADMIN_EMAIL, DEMO_PASSWORD)
    assert response.status_code == 200
    access = response.json()["data"]["access_token"]
    refresh = response.cookies.get("hrms_refresh")
    logout = await client.post("/v1/auth/logout", headers={"Authorization": f"Bearer {access}"})
    assert logout.status_code in (200, 204)
    raw = capfd.readouterr().out

    events = _events(raw)
    (ok,) = _named(events, "security.login.succeeded")
    assert ok["level"] == "info"
    assert ok["company_id"] == str(COMPANY_A_ID)
    assert ok["user_id"]
    (out,) = _named(events, "security.logout")
    assert out["user_id"] == ok["user_id"]
    assert access not in raw and refresh not in raw and DEMO_PASSWORD not in raw


async def test_unknown_refresh_token_is_rejected_and_logged(
    client: AsyncClient, seeded_db: None, capfd: CaptureFixture[str]
) -> None:
    bogus = "rt-SENTINEL-not-a-real-refresh-token"
    capfd.readouterr()
    response = await client.post("/v1/auth/token/refresh", json={"refresh_token": bogus})
    raw = capfd.readouterr().out
    assert response.status_code == 401
    (event,) = _named(_events(raw), "security.refresh.rejected")
    assert event["reason"] == "unknown_token"
    assert event["level"] == "warning"
    assert bogus not in raw


async def test_authorization_denial_and_tenant_mismatch(
    client: AsyncClient, seeded_db: None, capfd: CaptureFixture[str]
) -> None:
    viewer = (await _login(client, VIEWER_EMAIL, DEMO_PASSWORD)).json()["data"]["access_token"]
    admin = (await _login(client, ADMIN_EMAIL, DEMO_PASSWORD)).json()["data"]["access_token"]
    capfd.readouterr()
    denied = await client.get(
        "/v1/auth/admin/users-check", headers={"Authorization": f"Bearer {viewer}"}
    )
    mismatch = await client.get(
        "/v1/auth/me",
        headers={"Authorization": f"Bearer {admin}", "X-Company-Id": str(COMPANY_B_ID)},
    )
    raw = capfd.readouterr().out
    assert denied.status_code == 403
    assert mismatch.status_code == 404

    events = _events(raw)
    (authz,) = _named(events, "security.authorization.denied")
    assert authz["permission"]
    assert authz["company_id"] == str(COMPANY_A_ID)
    (tenant,) = _named(events, "security.tenant.rejected")
    assert tenant["reason"] == "company_header_mismatch"
    assert tenant["level"] == "warning"
    # The attacker-supplied company id is never logged.
    assert str(COMPANY_B_ID) not in json.dumps(tenant)


async def test_password_reset_flow_events(
    client: AsyncClient, seeded_db: None, capfd: CaptureFixture[str]
) -> None:
    unknown = "ghost-sentinel@example.com"
    bad_token = "pr-SENTINEL-invalid-reset-token"
    capfd.readouterr()
    forgot = await client.post("/v1/auth/password/forgot", json={"email": unknown})
    reset = await client.post(
        "/v1/auth/password/reset", json={"token": bad_token, "password": "NewPassw0rd!"}
    )
    raw = capfd.readouterr().out
    assert forgot.status_code in (200, 202, 204)
    assert reset.status_code == 401

    events = _events(raw)
    (requested,) = _named(events, "security.password_reset.requested")
    assert requested["account_matched"] is False
    (failed,) = _named(events, "security.password_reset.failed")
    assert failed["reason"] == "invalid_or_expired"
    assert unknown not in raw and bad_token not in raw


async def test_rate_limit_trip_is_logged_once_per_window(
    client: AsyncClient, seeded_db: None, capfd: CaptureFixture[str]
) -> None:
    email = "flood-sentinel@example.com"
    capfd.readouterr()
    statuses = [(await _login(client, email, WRONG_PASSWORD)).status_code for _ in range(13)]
    raw = capfd.readouterr().out
    assert statuses.count(429) == 3
    (tripped,) = _named(_events(raw), "security.rate_limited")
    assert tripped["bucket"] == "login"
    assert tripped["dimension"] == "ip+email"
    assert tripped["subject_hash"]
    assert email not in raw


async def test_broken_log_sink_does_not_weaken_lockout(
    client: AsyncClient, seeded_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Broken:
        def __getattr__(self, _name: str) -> Any:
            def _raise(*_a: Any, **_k: Any) -> None:
                raise OSError("log sink unavailable")

            return _raise

    monkeypatch.setattr(security_events, "_logger", _Broken())
    statuses = [(await _login(client, VIEWER_EMAIL, WRONG_PASSWORD)).status_code for _ in range(6)]
    assert statuses == [401] * 5 + [423]
    # The correct password is still refused while locked.
    assert (await _login(client, VIEWER_EMAIL, DEMO_PASSWORD)).status_code == 423


async def test_audited_login_emits_one_slim_business_event_after_commit(
    client: AsyncClient, seeded_db: None, capfd: CaptureFixture[str]
) -> None:
    capfd.readouterr()
    response = await client.post(
        "/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": DEMO_PASSWORD},
        headers={"X-Request-Id": "biz-login-1", "User-Agent": "UA-SENTINEL/1.0"},
    )
    raw = capfd.readouterr().out
    assert response.status_code == 200
    (event,) = [
        e
        for e in _events(raw, prefix="business.")
        if e["event"] == "business.audit_recorded" and e["action"] == "LOGIN"
    ]
    assert event["entity_type"] == "session"
    assert event["company_id"] == str(COMPANY_A_ID)
    assert event["request_id"] == "biz-login-1"
    # IP, user agent and before/after stay in audit_log only.
    assert "UA-SENTINEL" not in raw
    assert set(event) >= {"action", "entity_id", "actor_user_id", "from_status", "to_status"}
