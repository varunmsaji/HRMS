"""Platform super-admin console: company approval and lifecycle, enforcement on the tenant side,
platform authentication, and the audit trail. Registrations go through the real API."""

from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from hrms.core.db.session import get_session_factory

from .conftest import PLATFORM_PASSWORD, TENANT_PASSWORD, login_platform

pytestmark = pytest.mark.asyncio

P = "/v1/platform"


async def _status(company_id: Any) -> str:
    async with get_session_factory()() as session:
        return str(
            (
                await session.execute(
                    text("SELECT status FROM company WHERE id = :i"), {"i": str(company_id)}
                )
            ).scalar_one()
        )


async def _action(
    client: AsyncClient, admin: Any, company_id: Any, action: str, body: dict | None = None
) -> Any:
    return await client.post(
        f"{P}/companies/{company_id}/{action}", headers=admin.headers, json=body or {}
    )


async def _tenant_write(client: AsyncClient, tenant: Any) -> Any:
    # An empty body: allowed companies answer 422 (validation); gated ones answer 403 first.
    return await client.post("/v1/branches", headers=tenant.headers, json={})


# --- registration & read-only mode -------------------------------------------------------------


async def test_new_company_is_pending_and_read_only(client: AsyncClient, make_tenant: Any) -> None:
    tenant = await make_tenant()
    assert await _status(tenant.company_id) == "PENDING_APPROVAL"

    me = await client.get("/v1/auth/me", headers=tenant.headers)
    assert me.status_code == 200
    assert me.json()["data"]["user"]["company_status"] == "PENDING_APPROVAL"

    write = await _tenant_write(client, tenant)
    assert write.status_code == 403
    assert write.json()["error"]["code"] == "COMPANY_PENDING_APPROVAL"

    # Sign-in works (read-only), and so do reads.
    login = await client.post(
        "/v1/auth/login", json={"email": tenant.email, "password": TENANT_PASSWORD}
    )
    assert login.status_code == 200, login.text
    assert (await client.get("/v1/auth/me", headers=tenant.headers)).status_code == 200


async def test_trial_clock_starts_at_approval(
    client: AsyncClient, make_tenant: Any, platform_admin: Any
) -> None:
    tenant = await make_tenant()
    before = (
        await client.get(f"{P}/companies/{tenant.company_id}", headers=platform_admin.headers)
    ).json()["data"]
    assert before["trial_ends_at"] is None and before["approved_at"] is None

    r = await _action(client, platform_admin, tenant.company_id, "approve")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["status"] == "TRIAL"
    assert data["trial_ends_at"] and data["approved_at"]
    assert data["subscription"]["trial_ends_at"] == data["trial_ends_at"]

    # Takes effect on the very next request with the SAME token: no longer gated.
    write = await _tenant_write(client, tenant)
    assert write.status_code == 422


# --- lifecycle ---------------------------------------------------------------------------------


async def test_reject_requires_reason_blocks_access_and_is_reversible(
    client: AsyncClient, make_tenant: Any, platform_admin: Any
) -> None:
    tenant = await make_tenant()
    no_reason = await _action(client, platform_admin, tenant.company_id, "reject")
    assert no_reason.status_code == 422
    assert no_reason.json()["error"]["code"] == "REQUEST_VALIDATION_ERROR"
    assert await _status(tenant.company_id) == "PENDING_APPROVAL"

    r = await _action(
        client, platform_admin, tenant.company_id, "reject", {"reason": "Incomplete KYC"}
    )
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "REJECTED"
    assert r.json()["data"]["status_reason"] == "Incomplete KYC"

    me = await client.get("/v1/auth/me", headers=tenant.headers)
    assert me.status_code == 403 and me.json()["error"]["code"] == "COMPANY_REJECTED"
    login = await client.post(
        "/v1/auth/login", json={"email": tenant.email, "password": TENANT_PASSWORD}
    )
    assert login.status_code == 403 and login.json()["error"]["code"] == "COMPANY_REJECTED"

    # A rejection can be reconsidered.
    again = await _action(client, platform_admin, tenant.company_id, "approve")
    assert again.status_code == 200 and again.json()["data"]["status"] == "TRIAL"


async def test_suspend_is_read_only_then_reactivate(
    client: AsyncClient, make_tenant: Any, platform_admin: Any
) -> None:
    tenant = await make_tenant()
    await _action(client, platform_admin, tenant.company_id, "approve")

    r = await _action(
        client, platform_admin, tenant.company_id, "suspend", {"reason": "Payment overdue"}
    )
    assert r.status_code == 200 and r.json()["data"]["status"] == "SUSPENDED"

    assert (await client.get("/v1/auth/me", headers=tenant.headers)).status_code == 200
    write = await _tenant_write(client, tenant)
    assert write.status_code == 403 and write.json()["error"]["code"] == "COMPANY_SUSPENDED"
    login = await client.post(
        "/v1/auth/login", json={"email": tenant.email, "password": TENANT_PASSWORD}
    )
    assert login.status_code == 200  # grace mode: can still sign in and read

    back = await _action(client, platform_admin, tenant.company_id, "reactivate")
    assert back.status_code == 200 and back.json()["data"]["status"] == "TRIAL"
    assert (await _tenant_write(client, tenant)).status_code == 422


async def test_terminate_needs_confirmation_blocks_everything_and_sets_retention(
    client: AsyncClient, make_tenant: Any, platform_admin: Any
) -> None:
    tenant = await make_tenant()
    await _action(client, platform_admin, tenant.company_id, "approve")
    login = await client.post(
        "/v1/auth/login", json={"email": tenant.email, "password": TENANT_PASSWORD}
    )
    assert login.status_code == 200

    wrong = await _action(
        client,
        platform_admin,
        tenant.company_id,
        "terminate",
        {"reason": "Contract ended", "confirm_name": "not the name"},
    )
    assert wrong.status_code == 422
    assert wrong.json()["error"]["code"] == "CONFIRMATION_MISMATCH"
    assert await _status(tenant.company_id) == "TRIAL"

    ok = await _action(
        client,
        platform_admin,
        tenant.company_id,
        "terminate",
        {"reason": "Contract ended", "confirm_name": tenant.name},
    )
    assert ok.status_code == 200
    data = ok.json()["data"]
    assert data["status"] == "TERMINATED" and data["retention_until"]

    old_token = await client.get("/v1/auth/me", headers=tenant.headers)
    assert (
        old_token.status_code == 403 and old_token.json()["error"]["code"] == "COMPANY_TERMINATED"
    )
    relogin = await client.post(
        "/v1/auth/login", json={"email": tenant.email, "password": TENANT_PASSWORD}
    )
    assert relogin.status_code == 403 and relogin.json()["error"]["code"] == "COMPANY_TERMINATED"

    # Terminal: nothing can move it again.
    assert (
        await _action(client, platform_admin, tenant.company_id, "reactivate")
    ).status_code == 409


async def test_illegal_transitions_are_409(
    client: AsyncClient, make_tenant: Any, platform_admin: Any
) -> None:
    tenant = await make_tenant()
    suspend_pending = await _action(
        client, platform_admin, tenant.company_id, "suspend", {"reason": "x y z"}
    )
    assert suspend_pending.status_code == 409
    assert suspend_pending.json()["error"]["code"] == "INVALID_COMPANY_TRANSITION"
    await _action(client, platform_admin, tenant.company_id, "approve")
    again = await _action(client, platform_admin, tenant.company_id, "approve")
    assert again.status_code == 409
    assert (await _action(client, platform_admin, uuid4(), "approve")).status_code == 404


# --- queries, subscription, support ------------------------------------------------------------


async def test_list_filter_search_and_detail(
    client: AsyncClient, make_tenant: Any, platform_admin: Any
) -> None:
    tenant = await make_tenant()
    listing = await client.get(
        f"{P}/companies",
        headers=platform_admin.headers,
        params={"status": "PENDING_APPROVAL", "q": tenant.name},
    )
    assert listing.status_code == 200
    body = listing.json()
    assert [c["id"] for c in body["data"]] == [str(tenant.company_id)]
    assert body["pagination"]["total"] == 1
    assert body["data"][0]["admin_email"] == tenant.email

    none = await client.get(
        f"{P}/companies",
        headers=platform_admin.headers,
        params={"status": "ACTIVE", "q": tenant.name},
    )
    assert none.json()["data"] == []
    assert (
        await client.get(
            f"{P}/companies", headers=platform_admin.headers, params={"status": "BOGUS"}
        )
    ).status_code == 422

    detail = (
        await client.get(f"{P}/companies/{tenant.company_id}", headers=platform_admin.headers)
    ).json()["data"]
    assert detail["usage"]["active_users"] == 1
    assert detail["subscription"]["plan_code"]
    assert "password" not in str(detail).lower()

    dash = (await client.get(f"{P}/dashboard", headers=platform_admin.headers)).json()["data"]
    assert dash["pending_count"] >= 1 and dash["oldest_pending_since"]


async def test_subscription_changes(
    client: AsyncClient, make_tenant: Any, platform_admin: Any
) -> None:
    tenant = await make_tenant()
    await _action(client, platform_admin, tenant.company_id, "approve")
    url = f"{P}/companies/{tenant.company_id}/subscription"
    start = (
        await client.get(f"{P}/companies/{tenant.company_id}", headers=platform_admin.headers)
    ).json()["data"]

    r = await client.patch(
        url,
        headers=platform_admin.headers,
        json={"extend_trial_days": 10, "seat_limit_override": 25},
    )
    assert r.status_code == 200, r.text
    sub = r.json()["data"]["subscription"]
    assert sub["seat_limit_override"] == 25
    assert sub["trial_ends_at"] > start["subscription"]["trial_ends_at"]
    assert r.json()["data"]["trial_ends_at"] == sub["trial_ends_at"]

    cleared = await client.patch(
        url, headers=platform_admin.headers, json={"seat_limit_override": None}
    )
    assert cleared.json()["data"]["subscription"]["seat_limit_override"] is None

    bad_plan = await client.patch(url, headers=platform_admin.headers, json={"plan_code": "NOPE"})
    assert bad_plan.status_code == 422 and bad_plan.json()["error"]["code"] == "PLAN_NOT_FOUND"
    unknown = await client.patch(url, headers=platform_admin.headers, json={"is_admin": True})
    assert unknown.status_code == 422  # unknown fields are rejected, not ignored


async def test_unlock_company_admin(
    client: AsyncClient, make_tenant: Any, platform_admin: Any
) -> None:
    tenant = await make_tenant()
    async with get_session_factory()() as session:
        await session.execute(
            text(
                'UPDATE "user" SET failed_login_count = 5, '
                "locked_until = now() + interval '1 hour' WHERE id = :i"
            ),
            {"i": str(tenant.user_id)},
        )
        await session.commit()
    locked = (
        await client.get(f"{P}/companies/{tenant.company_id}", headers=platform_admin.headers)
    ).json()["data"]
    assert locked["admin_locked"] is True
    r = await client.post(
        f"{P}/companies/{tenant.company_id}/admin/unlock", headers=platform_admin.headers
    )
    assert r.json()["data"]["admin_locked"] is False


# --- authentication & isolation ----------------------------------------------------------------


async def test_platform_auth_and_token_separation(
    client: AsyncClient, make_tenant: Any, platform_admin: Any
) -> None:
    tenant = await make_tenant()
    # no token / tenant token on platform routes
    anon = await client.get(f"{P}/dashboard")
    assert anon.status_code == 401 and anon.headers["www-authenticate"] == "Bearer"
    tenant_on_platform = await client.get(
        f"{P}/dashboard", headers={"Authorization": tenant.headers["Authorization"]}
    )
    assert tenant_on_platform.status_code == 401
    # platform token on tenant routes
    platform_on_tenant = await client.get("/v1/auth/me", headers=platform_admin.headers)
    assert platform_on_tenant.status_code == 401

    me = await client.get(f"{P}/auth/me", headers=platform_admin.headers)
    assert me.json()["data"]["username"] == platform_admin.username

    # logout revokes the session immediately
    assert (
        await client.post(f"{P}/auth/logout", headers=platform_admin.headers)
    ).status_code == 204
    assert (await client.get(f"{P}/auth/me", headers=platform_admin.headers)).status_code == 401


async def test_platform_login_failures_and_lockout(
    client: AsyncClient, platform_admin: Any
) -> None:
    unknown = await login_platform(client, "nobody-here", "whatever")
    wrong = await login_platform(client, platform_admin.username, "wrong-password")
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["error"]["code"] == wrong.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert unknown.json()["error"]["message"] == wrong.json()["error"]["message"]

    for _ in range(4):
        await login_platform(client, platform_admin.username, "wrong-password")
    locked = await login_platform(client, platform_admin.username, PLATFORM_PASSWORD)
    assert locked.status_code == 423 and locked.json()["error"]["code"] == "ACCOUNT_LOCKED"


# --- audit & notifications ---------------------------------------------------------------------


async def test_audit_trail_is_recorded_and_append_only(
    client: AsyncClient, make_tenant: Any, platform_admin: Any
) -> None:
    tenant = await make_tenant()
    await _action(client, platform_admin, tenant.company_id, "approve")
    await _action(client, platform_admin, tenant.company_id, "suspend", {"reason": "Policy breach"})

    r = await client.get(
        f"{P}/audit-log",
        headers=platform_admin.headers,
        params={"company_id": str(tenant.company_id)},
    )
    entries = r.json()["data"]
    assert [e["action"] for e in entries] == ["COMPANY_SUSPENDED", "COMPANY_APPROVED"]
    suspended = entries[0]
    assert suspended["reason"] == "Policy breach"
    assert (suspended["before_status"], suspended["after_status"]) == ("TRIAL", "SUSPENDED")
    assert suspended["actor_username"] == platform_admin.username and suspended["request_id"]

    # the company's own audit log also shows the platform action
    async with get_session_factory()() as session:
        await session.execute(
            text("SELECT set_config('app.company_id', :c, true)"), {"c": str(tenant.company_id)}
        )
        n = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE company_id = :c "
                    "AND action = 'COMPANY_STATUS_CHANGED_BY_PLATFORM'"
                ),
                {"c": str(tenant.company_id)},
            )
        ).scalar_one()
    assert n == 2

    async with get_session_factory()() as session:
        for stmt in (
            "UPDATE platform_audit_log SET reason = 'x'",
            "DELETE FROM platform_audit_log",
        ):
            with pytest.raises(Exception, match="append-only|permission denied"):
                await session.execute(text(stmt))
            await session.rollback()


async def test_status_change_emails_the_company_admin(
    client: AsyncClient, make_tenant: Any, platform_admin: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[dict[str, str]] = []

    class _Capture:
        async def send(self, **kwargs: str) -> None:
            sent.append(kwargs)

    monkeypatch.setattr("hrms.modules.platform.service.get_email_sender", lambda _s: _Capture())
    tenant = await make_tenant()
    await _action(
        client, platform_admin, tenant.company_id, "reject", {"reason": "Missing <b>documents</b>"}
    )
    assert len(sent) == 1
    assert sent[0]["to"] == tenant.email
    assert "not approved" in sent[0]["subject"]
    assert "Missing" in sent[0]["text_body"]
    assert "<b>" not in sent[0]["html_body"]  # reason is HTML-escaped


async def test_email_failure_does_not_undo_the_change(
    client: AsyncClient, make_tenant: Any, platform_admin: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Broken:
        async def send(self, **kwargs: str) -> None:
            raise ConnectionError("smtp down")

    monkeypatch.setattr("hrms.modules.platform.service.get_email_sender", lambda _s: _Broken())
    tenant = await make_tenant()
    r = await _action(client, platform_admin, tenant.company_id, "approve")
    assert r.status_code == 200
    assert await _status(tenant.company_id) == "TRIAL"


# --- dashboard, plans, admin accounts, support --------------------------------------------------


async def test_dashboard_has_queues_trend_and_activity(
    client: AsyncClient, make_tenant: Any, platform_admin: Any
) -> None:
    pending = await make_tenant()
    trial = await make_tenant()
    await _action(client, platform_admin, trial.company_id, "approve")
    async with get_session_factory()() as session:  # make the trial end soon
        await session.execute(
            text("UPDATE company SET trial_ends_at = now() + interval '2 days' WHERE id = :i"),
            {"i": str(trial.company_id)},
        )
        await session.commit()

    d = (await client.get(f"{P}/dashboard", headers=platform_admin.headers)).json()["data"]
    assert d["total_companies"] == sum(d["counts_by_status"].values())
    assert len(d["registrations_last_30_days"]) == 30
    assert d["registrations_total_30_days"] >= 2
    assert str(pending.company_id) in {c["id"] for c in d["pending"]} or d["pending_count"] > 5
    assert str(trial.company_id) in {c["id"] for c in d["trials_expiring"]}
    assert d["trials_expiring_within_7_days"] >= 1
    assert d["active_platform_admins"] >= 1
    assert any(a["action"] == "COMPANY_APPROVED" for a in d["recent_activity"])
    assert "password" not in str(d).lower()


async def test_plan_catalogue_feeds_plan_changes(
    client: AsyncClient, make_tenant: Any, platform_admin: Any
) -> None:
    tenant = await make_tenant()
    plans = (await client.get(f"{P}/plans", headers=platform_admin.headers)).json()["data"]
    assert plans and {"code", "name"} <= set(plans[0])
    code = plans[-1]["code"]
    r = await client.patch(
        f"{P}/companies/{tenant.company_id}/subscription",
        headers=platform_admin.headers,
        json={"plan_code": code},
    )
    assert r.status_code == 200 and r.json()["data"]["subscription"]["plan_code"] == code


async def test_platform_admin_account_management(client: AsyncClient, platform_admin: Any) -> None:
    username = f"pt-{uuid4().hex[:8]}"
    created_id = None
    try:
        weak = await client.post(
            f"{P}/admins",
            headers=platform_admin.headers,
            json={"username": username, "password": "short"},
        )
        assert weak.status_code == 422 and weak.json()["error"]["code"] == "WEAK_PASSWORD"

        ok = await client.post(
            f"{P}/admins",
            headers=platform_admin.headers,
            json={"username": username.upper(), "password": "Another-Pass-7"},
        )
        assert ok.status_code == 201, ok.text
        created_id = ok.json()["data"]["id"]
        assert ok.json()["data"]["username"] == username  # normalised to lower case
        assert "password" not in ok.text.lower()

        dup = await client.post(
            f"{P}/admins",
            headers=platform_admin.headers,
            json={"username": username, "password": "Another-Pass-7"},
        )
        assert dup.status_code == 409 and dup.json()["error"]["code"] == "USERNAME_TAKEN"

        listing = (await client.get(f"{P}/admins", headers=platform_admin.headers)).json()["data"]
        assert {a["username"] for a in listing} >= {username, platform_admin.username}
        assert [a for a in listing if a["is_you"]][0]["username"] == platform_admin.username

        # the new admin signs in; disabling them signs them out at once and blocks sign-in
        token = (await login_platform(client, username, "Another-Pass-7")).json()["data"][
            "access_token"
        ]
        theirs = {"Authorization": f"Bearer {token}"}
        assert (await client.get(f"{P}/auth/me", headers=theirs)).status_code == 200
        off = await client.post(f"{P}/admins/{created_id}/disable", headers=platform_admin.headers)
        assert off.status_code == 200 and off.json()["data"]["status"] == "DISABLED"
        assert (await client.get(f"{P}/auth/me", headers=theirs)).status_code == 401
        assert (await login_platform(client, username, "Another-Pass-7")).status_code == 401

        await client.post(f"{P}/admins/{created_id}/enable", headers=platform_admin.headers)
        weak_reset = await client.post(
            f"{P}/admins/{created_id}/reset-password",
            headers=platform_admin.headers,
            json={"password": "x"},
        )
        assert weak_reset.status_code == 422
        reset = await client.post(
            f"{P}/admins/{created_id}/reset-password",
            headers=platform_admin.headers,
            json={"password": "Brand-New-Pass-3"},
        )
        assert reset.status_code == 200
        assert (await login_platform(client, username, "Another-Pass-7")).status_code == 401
        assert (await login_platform(client, username, "Brand-New-Pass-3")).status_code == 200

        # you cannot disable yourself
        me_id = [a for a in listing if a["is_you"]][0]["id"]
        own = await client.post(f"{P}/admins/{me_id}/disable", headers=platform_admin.headers)
        assert own.status_code == 409 and own.json()["error"]["code"] == "CANNOT_DISABLE_ADMIN"

        actions = {
            e["action"]
            for e in (
                await client.get(
                    f"{P}/audit-log", headers=platform_admin.headers, params={"per_page": 50}
                )
            ).json()["data"]
        }
        assert {
            "PLATFORM_ADMIN_CREATED",
            "PLATFORM_ADMIN_DISABLED",
            "PLATFORM_ADMIN_PASSWORD_RESET",
        } <= actions
    finally:
        if created_id:
            async with get_session_factory()() as session:
                await session.execute(
                    text("DELETE FROM platform_admin WHERE id = :i"), {"i": created_id}
                )
                await session.commit()


async def test_resend_verification_only_for_unverified_admins(
    client: AsyncClient, make_tenant: Any, platform_admin: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[dict[str, str]] = []

    class _Capture:
        async def send(self, **kwargs: str) -> None:
            sent.append(kwargs)

    monkeypatch.setattr("hrms.modules.identity.service.get_email_sender", lambda _s: _Capture())
    unverified = await make_tenant(verified=False)
    verified = await make_tenant(verified=True)
    sent.clear()  # registration itself sends a verification email
    r = await client.post(
        f"{P}/companies/{unverified.company_id}/admin/resend-verification",
        headers=platform_admin.headers,
    )
    assert r.status_code == 200
    assert len(sent) == 1 and sent[0]["to"] == unverified.email

    again = await client.post(
        f"{P}/companies/{verified.company_id}/admin/resend-verification",
        headers=platform_admin.headers,
    )
    assert again.status_code == 409 and again.json()["error"]["code"] == "ADMIN_ALREADY_VERIFIED"
    assert len(sent) == 1
