"""Authentication lifecycle for provisioned users: lockout, deactivation, logout, refresh and JWT
tampering. Every case asserts the *safe* outcome — a rejected request is a clean 4xx, never a 500,
and never a silent success."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt as pyjwt
import pytest
from httpx import AsyncClient
from sqlalchemy import text

from hrms.core.config.settings import get_settings
from hrms.core.db.session import get_session_factory

from .uac_helpers import (
    VALID_PASSWORD,
    onboard,
    register_tenant,
    reset_auth_rate_limit,
    set_sql,
    teardown,
)

pytestmark = pytest.mark.asyncio


async def _login(client: AsyncClient, email: str, password: str, **extra: object):
    await reset_auth_rate_limit()
    return await client.post("/v1/auth/login", json={"email": email, "password": password, **extra})


async def _user_row(email: str):
    factory = get_session_factory()
    async with factory() as session:
        return (
            await session.execute(
                text('SELECT failed_login_count, locked_until FROM "user" WHERE email = :e'),
                {"e": email},
            )
        ).one()


# ------------------------------------------------------------------ lockout


async def test_five_wrong_passwords_lock_the_account_even_for_the_right_password(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant = await register_tenant(client)
    try:
        user = await onboard(client, tenant, "EMPLOYEE")
        for _ in range(5):
            assert (await _login(client, user.email, "WrongGuess123")).status_code == 401
        row = await _user_row(user.email)
        assert row.failed_login_count >= 5
        assert row.locked_until is not None and row.locked_until > datetime.now(UTC)

        locked = await _login(client, user.email, user.password)
        assert locked.status_code != 200, "right password must be refused while locked"
        assert locked.json()["error"]["code"] in {"ACCOUNT_LOCKED", "LOCKED"}

        # lock expiry restores access
        await set_sql(
            "UPDATE \"user\" SET locked_until = now() - interval '1 minute' WHERE email = :e",
            e=user.email,
        )
        assert (await _login(client, user.email, user.password)).status_code == 200
    finally:
        await teardown(tenant)


async def test_successful_login_resets_the_failure_counter(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant = await register_tenant(client)
    try:
        user = await onboard(client, tenant, "EMPLOYEE")
        for _ in range(4):
            await _login(client, user.email, "WrongGuess123")
        assert (await _login(client, user.email, user.password)).status_code == 200
        assert (await _user_row(user.email)).failed_login_count == 0
        for _ in range(4):  # four more is still below the threshold
            await _login(client, user.email, "WrongGuess123")
        assert (await _login(client, user.email, user.password)).status_code == 200
    finally:
        await teardown(tenant)


# ------------------------------------------------------------------ deactivation


@pytest.mark.parametrize(
    "deactivate_sql",
    [
        "UPDATE \"user\" SET status = 'SUSPENDED' WHERE email = :e",
        "UPDATE \"user\" SET status = 'INACTIVE' WHERE email = :e",
        'UPDATE "user" SET deleted_at = now() WHERE email = :e',
        "UPDATE user_company SET status = 'INACTIVE' "
        'WHERE user_id = (SELECT id FROM "user" WHERE email = :e)',
    ],
    ids=["user-suspended", "user-inactive", "user-soft-deleted", "membership-inactive"],
)
async def test_deactivated_user_loses_every_way_in(
    client: AsyncClient, seeded_plan_catalogue: None, deactivate_sql: str
) -> None:
    tenant = await register_tenant(client)
    try:
        user = await onboard(client, tenant, "HR_ADMIN")
        login = await _login(client, user.email, user.password)
        assert login.status_code == 200
        refresh_cookie = login.cookies.get("hrms_refresh")
        assert (await client.get("/v1/auth/me", headers=user.headers)).status_code == 200

        await set_sql(deactivate_sql, e=user.email)

        # 1. the already-issued access token dies immediately
        me = await client.get("/v1/auth/me", headers=user.headers)
        assert me.status_code in (401, 404), me.text
        # 2. no new login
        assert (await _login(client, user.email, user.password)).status_code in (401, 403)
        # 3. the refresh token cannot mint a working session
        await reset_auth_rate_limit()
        refreshed = await client.post(
            "/v1/auth/token/refresh", json={"refresh_token": refresh_cookie}
        )
        assert refreshed.status_code in (401, 403), refreshed.text
        # 4. they vanish from nothing they should still see
        assert (await client.get("/v1/users", headers=user.headers)).status_code in (401, 403, 404)
    finally:
        await teardown(tenant)


async def test_deactivated_membership_in_one_company_does_not_affect_the_other(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    from .uac_helpers import teardown_all

    a = await register_tenant(client)
    b = await register_tenant(client)
    try:
        member = await onboard(client, a, "EMPLOYEE")
        b.emails.append(member.email)
        invite = await client.post(
            "/v1/users/invite",
            headers=b.headers,
            json={"email": member.email, "role_code": "EMPLOYEE"},
        )
        token = invite.json()["data"]["invite_url"].rsplit("/", 1)[-1]
        await reset_auth_rate_limit()
        accept = await client.post(
            f"/v1/public/account-invites/{token}/accept", json={"password": member.password}
        )
        assert accept.status_code == 201
        await set_sql(
            "UPDATE user_company SET status = 'INACTIVE' "
            "WHERE user_id = CAST(:u AS uuid) AND company_id = CAST(:c AS uuid)",
            u=member.user_id,
            c=a.company_id,
        )
        assert (await client.get("/v1/auth/me", headers=member.headers)).status_code in (401, 404)
        ok = await _login(client, member.email, member.password, company_id=str(b.company_id))
        assert ok.status_code == 200
        denied = await _login(client, member.email, member.password, company_id=str(a.company_id))
        assert denied.status_code == 401
    finally:
        await teardown_all(a, b)


# ------------------------------------------------------------------ logout / refresh


async def test_logout_kills_the_access_token_and_the_refresh_token(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant = await register_tenant(client)
    try:
        user = await onboard(client, tenant, "EMPLOYEE")
        login = await _login(client, user.email, user.password)
        access = login.json()["data"]["access_token"]
        refresh = login.cookies.get("hrms_refresh")
        headers = {"Authorization": f"Bearer {access}", "X-Company-Id": str(tenant.company_id)}

        out = await client.post("/v1/auth/logout", headers=headers)
        assert out.status_code == 204
        assert (await client.get("/v1/auth/me", headers=headers)).status_code == 401

        await reset_auth_rate_limit()
        revived = await client.post("/v1/auth/token/refresh", json={"refresh_token": refresh})
        assert revived.status_code == 401, (
            "a refresh token that outlives logout lets a stolen cookie keep minting sessions"
        )
    finally:
        await teardown(tenant)


async def test_logout_only_ends_that_one_session(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant = await register_tenant(client)
    try:
        user = await onboard(client, tenant, "EMPLOYEE")
        one = await _login(client, user.email, user.password)
        two = await _login(client, user.email, user.password)
        h1 = {"Authorization": f"Bearer {one.json()['data']['access_token']}"}
        h2 = {"Authorization": f"Bearer {two.json()['data']['access_token']}"}
        await client.post("/v1/auth/logout", headers=h1)
        assert (await client.get("/v1/auth/me", headers=h1)).status_code == 401
        assert (await client.get("/v1/auth/me", headers=h2)).status_code == 200
    finally:
        await teardown(tenant)


async def test_refresh_token_validation(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    for body in (
        {},
        {"refresh_token": ""},
        {"refresh_token": "nope"},
        {"refresh_token": "a" * 9000},
    ):
        await reset_auth_rate_limit()
        r = await client.post("/v1/auth/token/refresh", json=body)
        assert r.status_code == 401, (body, r.text)


# ------------------------------------------------------------------ JWT tampering


def _claims(user, tenant, **override):
    base = {
        "sub": str(user.user_id),
        "company_id": str(tenant.company_id),
        "session_id": str(uuid4()),
        "employee_id": None,
        "exp": datetime.now(UTC) + timedelta(minutes=5),
        "iat": datetime.now(UTC),
        "type": "access",
    }
    base.update(override)
    return base


async def test_forged_and_malformed_access_tokens_are_rejected_cleanly(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant = await register_tenant(client)
    try:
        user = await onboard(client, tenant, "COMPANY_ADMIN")
        secret = get_settings().jwt_access_secret
        good = user.headers["Authorization"].split()[1]
        real = pyjwt.decode(good, options={"verify_signature": False})
        valid_claims = _claims(user, tenant, session_id=real["session_id"])

        forged: dict[str, str] = {
            "wrong-secret": pyjwt.encode(valid_claims, "x" * 32, algorithm="HS256"),
            "alg-none": pyjwt.encode(valid_claims, None, algorithm="none"),
            "expired": pyjwt.encode(
                {**valid_claims, "exp": datetime.now(UTC) - timedelta(seconds=1)},
                secret,
                algorithm="HS256",
            ),
            "refresh-type": pyjwt.encode(
                {**valid_claims, "type": "refresh"}, secret, algorithm="HS256"
            ),
            "no-type": pyjwt.encode(
                {k: v for k, v in valid_claims.items() if k != "type"}, secret, algorithm="HS256"
            ),
            "no-sub": pyjwt.encode(
                {k: v for k, v in valid_claims.items() if k != "sub"}, secret, algorithm="HS256"
            ),
            "non-uuid-sub": pyjwt.encode(
                {**valid_claims, "sub": "admin"}, secret, algorithm="HS256"
            ),
            "no-company": pyjwt.encode(
                {k: v for k, v in valid_claims.items() if k != "company_id"},
                secret,
                algorithm="HS256",
            ),
            "non-uuid-company": pyjwt.encode(
                {**valid_claims, "company_id": "1; DROP TABLE x"}, secret, algorithm="HS256"
            ),
            "no-session": pyjwt.encode(
                {k: v for k, v in valid_claims.items() if k != "session_id"},
                secret,
                algorithm="HS256",
            ),
            "non-uuid-employee": pyjwt.encode(
                {**valid_claims, "employee_id": "zzz"}, secret, algorithm="HS256"
            ),
            "unknown-user": pyjwt.encode(
                {**valid_claims, "sub": str(uuid4())}, secret, algorithm="HS256"
            ),
            "unknown-session": pyjwt.encode(
                {**valid_claims, "session_id": str(uuid4())}, secret, algorithm="HS256"
            ),
            "tampered-payload": good.rsplit(".", 2)[0] + ".e30." + good.rsplit(".", 1)[1],
            "truncated": good[:-5],
        }
        failures = []
        for name, token in forged.items():
            r = await client.get(
                "/v1/users",
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Company-Id": str(tenant.company_id),
                },
            )
            if r.status_code != 401:
                failures.append(f"{name}: {r.status_code}")
        assert not failures, "forged tokens not cleanly rejected:\n" + "\n".join(failures)

        # control: the genuine token still works
        assert (await client.get("/v1/users", headers=user.headers)).status_code == 200
    finally:
        await teardown(tenant)


async def test_token_for_a_company_the_user_never_joined_is_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    a = await register_tenant(client)
    b = await register_tenant(client)
    try:
        user = await onboard(client, a, "COMPANY_ADMIN")
        real = pyjwt.decode(
            user.headers["Authorization"].split()[1], options={"verify_signature": False}
        )
        token = pyjwt.encode(
            _claims(user, b, session_id=real["session_id"]),
            get_settings().jwt_access_secret,
            algorithm="HS256",
        )
        r = await client.get(
            "/v1/users",
            headers={"Authorization": f"Bearer {token}", "X-Company-Id": str(b.company_id)},
        )
        assert r.status_code == 401
    finally:
        await teardown(a)
        await teardown(b)


async def test_login_does_not_reveal_which_part_was_wrong(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant = await register_tenant(client)
    try:
        user = await onboard(client, tenant, "EMPLOYEE")
        wrong_pw = await _login(client, user.email, "WrongGuess123")
        no_user = await _login(client, f"ghost-{uuid4().hex[:6]}@example.com", "WrongGuess123")
        wrong_company = await _login(client, user.email, user.password, company_id=str(uuid4()))
        shapes = {
            (r.status_code, r.json()["error"]["code"], r.json()["error"]["message"])
            for r in (wrong_pw, no_user, wrong_company)
        }
        assert len(shapes) == 1, shapes
    finally:
        await teardown(tenant)


async def test_login_and_reset_reject_oversized_input(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    await reset_auth_rate_limit()
    r = await client.post(
        "/v1/auth/login", json={"email": "a@example.com", "password": "x" * 100_000}
    )
    assert r.status_code == 422
    await reset_auth_rate_limit()
    r = await client.post(
        "/v1/auth/password/reset", json={"token": "t", "password": "Aa1" + "x" * 100_000}
    )
    assert r.status_code == 422


async def test_new_password_used_at_accept_is_what_login_checks(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant = await register_tenant(client)
    try:
        user = await onboard(client, tenant, "EMPLOYEE", password="UniquePw2468x")
        assert (await _login(client, user.email, "UniquePw2468x")).status_code == 200
        assert (await _login(client, user.email, VALID_PASSWORD)).status_code == 401
        assert (
            await _login(client, user.email, "uniquepw2468x")
        ).status_code == 401  # case-sensitive
    finally:
        await teardown(tenant)
