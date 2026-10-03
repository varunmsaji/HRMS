"""SEC-02 (PLATFORM_READINESS_SECURITY_AUDIT_2026-09-17) — `/auth/login` and
`/auth/token/refresh` against the real mounted routes, real Postgres and real Redis. The
"login"/"token_refresh" buckets are reset before and after every test by the autouse fixture in
`tests/conftest.py` (`_reset_credential_rate_limits`), so these tests don't interfere with each
other or with the rest of the suite despite sharing one Redis instance.
"""

from entrypoints.api import app
from httpx import ASGITransport, AsyncClient

from hrms.seed.constants import ADMIN_EMAIL, DEMO_PASSWORD


async def test_normal_login_succeeds_under_the_limit(client: AsyncClient, seeded_db: None) -> None:
    response = await client.post(
        "/v1/auth/login", json={"email": ADMIN_EMAIL, "password": DEMO_PASSWORD}
    )
    assert response.status_code == 200


async def test_repeated_failed_login_from_same_ip_is_rate_limited(
    client: AsyncClient, seeded_db: None
) -> None:
    """11 attempts against distinct, nonexistent emails from one IP — no account lockout can
    fire (no real user to lock), so only the IP bucket can be the thing that trips."""
    responses = [
        await client.post(
            "/v1/auth/login",
            json={"email": f"no-such-user-{i}@example.com", "password": "wrong"},
        )
        for i in range(11)
    ]
    assert all(r.status_code == 401 for r in responses[:10])
    assert responses[10].status_code == 429
    assert responses[10].json()["error"]["code"] == "RATE_LIMITED"


async def test_repeated_attempts_against_same_email_are_rate_limited(
    client: AsyncClient, seeded_db: None
) -> None:
    target = "spray-target@example.com"  # nonexistent — isolates the rate limiter from lockout
    responses = [
        await client.post("/v1/auth/login", json={"email": target, "password": f"guess-{i}"})
        for i in range(11)
    ]
    assert all(r.status_code == 401 for r in responses[:10])
    assert responses[10].status_code == 429


async def test_distributed_ip_attempts_against_same_email_still_get_rate_limited() -> None:
    """The anti-DoS case the audit calls out: an attacker spread across many source IPs must
    still be caught by the email-keyed bucket even though no single IP looks abusive on its
    own."""
    target = "distributed-target@example.com"
    responses = []
    for i in range(11):
        transport = ASGITransport(app=app, client=(f"10.20.30.{i + 1}", 40000))
        async with AsyncClient(transport=transport, base_url="http://test") as scoped_client:
            responses.append(
                await scoped_client.post("/v1/auth/login", json={"email": target, "password": "x"})
            )
    assert all(r.status_code == 401 for r in responses[:10])
    assert responses[10].status_code == 429


async def test_different_ips_against_different_emails_are_not_cross_blocked(
    client: AsyncClient, seeded_db: None
) -> None:
    """Case E sanity check — one email's failed attempts must not affect an unrelated
    concurrent login for a different, legitimate account."""
    for i in range(3):
        r = await client.post(
            "/v1/auth/login",
            json={"email": f"unrelated-{i}@example.com", "password": "wrong"},
        )
        assert r.status_code == 401

    ok = await client.post("/v1/auth/login", json={"email": ADMIN_EMAIL, "password": DEMO_PASSWORD})
    assert ok.status_code == 200


async def test_login_rate_limit_leaves_the_existing_credential_check_behaviour_unchanged(
    client: AsyncClient, seeded_db: None
) -> None:
    """The rate limit (10/min) is an independent control from the per-account lockout (5 failed
    passwords → 423 for 15 minutes). A run of wrong passwords under the rate limit gets a plain
    401 until the account-lockout threshold, then 423 — the lockout counter used to be silently
    rolled back with the failed request's transaction, so it never engaged; see
    `IdentityService.login`."""
    responses = [
        await client.post(
            "/v1/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong-password"}
        )
        for _ in range(6)
    ]
    assert all(
        r.status_code == 401 and r.json()["error"]["code"] == "INVALID_CREDENTIALS"
        for r in responses[:5]
    )
    assert responses[5].status_code == 423
    assert responses[5].json()["error"]["code"] == "ACCOUNT_LOCKED"


async def test_login_error_does_not_reveal_whether_the_email_exists(
    client: AsyncClient, seeded_db: None
) -> None:
    unknown = await client.post(
        "/v1/auth/login", json={"email": "never-registered@example.com", "password": "x"}
    )
    wrong_password = await client.post(
        "/v1/auth/login", json={"email": ADMIN_EMAIL, "password": "definitely-wrong"}
    )
    assert unknown.status_code == wrong_password.status_code == 401
    assert (
        unknown.json()["error"]["code"]
        == wrong_password.json()["error"]["code"]
        == "INVALID_CREDENTIALS"
    )


async def test_refresh_endpoint_is_rate_limited(client: AsyncClient, seeded_db: None) -> None:
    responses = [
        await client.post("/v1/auth/token/refresh", json={"refresh_token": "not-a-real-token"})
        for _ in range(11)
    ]
    assert all(r.status_code == 401 for r in responses[:10])
    assert responses[10].status_code == 429
    assert responses[10].json()["error"]["code"] == "RATE_LIMITED"


async def test_legitimate_refresh_rotation_still_works_under_the_limit(
    client: AsyncClient, seeded_db: None
) -> None:
    login = await client.post(
        "/v1/auth/login", json={"email": ADMIN_EMAIL, "password": DEMO_PASSWORD}
    )
    assert login.status_code == 200
    # SEC-06 (RELEASE_HARDENING_PHASE_3A) — the refresh token is only in the HttpOnly cookie now.
    refresh_token = login.cookies.get("hrms_refresh")
    assert refresh_token

    response = await client.post("/v1/auth/token/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 200
    assert response.cookies.get("hrms_refresh") != refresh_token


async def test_refresh_replay_detection_still_works_under_the_limit(
    client: AsyncClient, seeded_db: None
) -> None:
    login = await client.post(
        "/v1/auth/login", json={"email": ADMIN_EMAIL, "password": DEMO_PASSWORD}
    )
    old_refresh = login.cookies.get("hrms_refresh")
    assert old_refresh

    first = await client.post("/v1/auth/token/refresh", json={"refresh_token": old_refresh})
    assert first.status_code == 200

    reuse = await client.post("/v1/auth/token/refresh", json={"refresh_token": old_refresh})
    assert reuse.status_code == 401
    assert reuse.json()["error"]["code"] == "INVALID_TOKEN"
