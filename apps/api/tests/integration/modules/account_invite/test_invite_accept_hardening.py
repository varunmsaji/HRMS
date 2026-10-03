"""Invite issue / resolve / accept edge cases: token hygiene, replay, races, input validation,
existing-account handling and the email-delivery failure path."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from hrms.core.db.models.identity import User, UserCompany
from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.account_invite.models import AccountInvite

from .test_account_invite import _force_invite_expired, _token_from_invite_url
from .uac_helpers import (
    VALID_PASSWORD,
    onboard,
    register_tenant,
    reset_auth_rate_limit,
    set_sql,
    teardown,
    teardown_all,
)

pytestmark = pytest.mark.asyncio


async def _invite(client: AsyncClient, tenant, email: str, role: str = "EMPLOYEE") -> str:
    tenant.emails.append(email)
    r = await client.post(
        "/v1/users/invite", headers=tenant.headers, json={"email": email, "role_code": role}
    )
    assert r.status_code == 201, r.text
    return _token_from_invite_url(r.json()["data"]["invite_url"])


def _email(prefix: str = "inv") -> str:
    return f"{prefix}-{uuid4().hex[:8]}@example.com"


# ---------------------------------------------------------------- issuing


async def test_invite_rejects_bad_role_codes_and_bad_emails(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant = await register_tenant(client)
    try:
        for role in ("SUPER_ADMIN", "hr_admin", "", "COMPANY_ADMIN; DROP TABLE role"):
            r = await client.post(
                "/v1/users/invite",
                headers=tenant.headers,
                json={"email": _email(), "role_code": role},
            )
            assert r.status_code == 422, (role, r.text)
        for email in ("", "no-at-sign", "a@", "@b.com", "a b@c.com", "x" * 300 + "@example.com"):
            r = await client.post(
                "/v1/users/invite",
                headers=tenant.headers,
                json={"email": email, "role_code": "EMPLOYEE"},
            )
            assert r.status_code == 422, (email, r.text)
        for body in ({}, {"email": _email()}, {"role_code": "EMPLOYEE"}, []):
            r = await client.post("/v1/users/invite", headers=tenant.headers, json=body)
            assert r.status_code == 422, (body, r.text)
        # nothing was created
        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, str(tenant.company_id))
            count = (
                (
                    await session.execute(
                        select(AccountInvite).where(AccountInvite.company_id == tenant.company_id)
                    )
                )
                .scalars()
                .all()
            )
        assert count == []
    finally:
        await teardown(tenant)


async def test_invite_email_is_normalised_to_lowercase(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant = await register_tenant(client)
    mixed = f"MiXeD-{uuid4().hex[:6]}@Example.COM"
    try:
        token = await _invite(client, tenant, mixed.lower())
        tenant.emails.append(mixed.lower())
        r = await client.post(
            "/v1/users/invite",
            headers=tenant.headers,
            json={"email": mixed, "role_code": "EMPLOYEE"},
        )
        assert r.status_code == 201
        assert r.json()["data"]["email"] == mixed.lower()
        # the second invite for the same (case-folded) address revoked the first
        assert (await client.get(f"/v1/public/account-invites/{token}")).status_code == 404
        # and the account is created lower-cased, so login by any casing works
        new_token = _token_from_invite_url(r.json()["data"]["invite_url"])
        accept = await client.post(
            f"/v1/public/account-invites/{new_token}/accept", json={"password": VALID_PASSWORD}
        )
        assert accept.status_code == 201
        for variant in (mixed, mixed.lower(), mixed.upper()):
            login = await client.post(
                "/v1/auth/login", json={"email": variant, "password": VALID_PASSWORD}
            )
            assert login.status_code == 200, variant
    finally:
        await teardown(tenant)


async def test_invite_stores_only_a_hash_and_response_never_exposes_it(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant = await register_tenant(client)
    try:
        email = _email()
        tenant.emails.append(email)
        r = await client.post(
            "/v1/users/invite",
            headers=tenant.headers,
            json={"email": email, "role_code": "HR_ADMIN"},
        )
        data = r.json()["data"]
        raw = _token_from_invite_url(data["invite_url"])
        assert len(raw) >= 40  # 256 bits of urlsafe entropy
        assert set(data) == {"id", "email", "role_code", "expires_at", "invite_url", "email_sent"}
        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, str(tenant.company_id))
            row = (
                await session.execute(select(AccountInvite).where(AccountInvite.email == email))
            ).scalar_one()
        assert row.token_hash != raw
        assert raw not in str(row.__dict__)
        ttl = row.expires_at - datetime.now(UTC)
        assert timedelta(days=6, hours=23) < ttl <= timedelta(days=7)
        # tokens are unique per issue
        again = await client.post(
            "/v1/users/invite",
            headers=tenant.headers,
            json={"email": email, "role_code": "HR_ADMIN"},
        )
        assert _token_from_invite_url(again.json()["data"]["invite_url"]) != raw
    finally:
        await teardown(tenant)


async def test_email_delivery_failure_does_not_fail_the_invite(
    client: AsyncClient, seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hrms.modules.account_invite import service as svc

    class _Boom:
        async def send(self, **_: object) -> None:
            raise RuntimeError("smtp down")

    monkeypatch.setattr(svc, "get_email_sender", lambda _settings: _Boom())
    tenant = await register_tenant(client)
    try:
        email = _email()
        tenant.emails.append(email)
        r = await client.post(
            "/v1/users/invite",
            headers=tenant.headers,
            json={"email": email, "role_code": "EMPLOYEE"},
        )
        assert r.status_code == 201, r.text
        assert r.json()["data"]["email_sent"] is False
        # the admin can still hand over the link manually and it works
        token = _token_from_invite_url(r.json()["data"]["invite_url"])
        accept = await client.post(
            f"/v1/public/account-invites/{token}/accept", json={"password": VALID_PASSWORD}
        )
        assert accept.status_code == 201
    finally:
        await teardown(tenant)


async def test_invite_employee_edge_cases(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    tenant = await register_tenant(client)
    try:
        # unknown employee id / malformed id
        assert (
            await client.post(f"/v1/employees/{uuid4()}/invite", headers=tenant.headers)
        ).status_code == 404
        assert (
            await client.post("/v1/employees/nope/invite", headers=tenant.headers)
        ).status_code == 422

        # employee with an email is invitable; the invite carries the EMPLOYEE role only
        email = _email("emp")
        tenant.emails.append(email)
        emp = await client.post(
            "/v1/employees",
            headers=tenant.headers,
            json={"first_name": "Emp", "personal_email": email.upper()},
        )
        assert emp.status_code == 201, emp.text
        invite = await client.post(
            f"/v1/employees/{emp.json()['data']['id']}/invite", headers=tenant.headers
        )
        assert invite.status_code == 201
        assert invite.json()["data"]["role_code"] == "EMPLOYEE"
        assert invite.json()["data"]["email"] == email  # lower-cased

        # soft-deleted employee is not invitable
        await set_sql(
            "UPDATE employee SET deleted_at = now() WHERE id = CAST(:i AS uuid)",
            i=emp.json()["data"]["id"],
        )
        gone = await client.post(
            f"/v1/employees/{emp.json()['data']['id']}/invite", headers=tenant.headers
        )
        assert gone.status_code == 404
    finally:
        await teardown(tenant)


# ---------------------------------------------------------------- resolving / accepting


async def test_token_is_single_use_and_replay_is_indistinguishable_from_unknown(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant = await register_tenant(client)
    try:
        email = _email()
        token = await _invite(client, tenant, email)
        first = await client.post(
            f"/v1/public/account-invites/{token}/accept", json={"password": VALID_PASSWORD}
        )
        assert first.status_code == 201
        replay = await client.post(
            f"/v1/public/account-invites/{token}/accept", json={"password": VALID_PASSWORD}
        )
        unknown = await client.post(
            f"/v1/public/account-invites/{'x' * 43}/accept", json={"password": VALID_PASSWORD}
        )
        assert replay.status_code == unknown.status_code == 404
        assert replay.json()["error"]["code"] == unknown.json()["error"]["code"]
        assert replay.json()["error"]["message"] == unknown.json()["error"]["message"]
        assert (await client.get(f"/v1/public/account-invites/{token}")).status_code == 404
    finally:
        await teardown(tenant)


async def test_revoked_and_expired_tokens_cannot_be_resolved_or_accepted(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant = await register_tenant(client)
    try:
        email = _email()
        old = await _invite(client, tenant, email)
        new = await _invite(client, tenant, email)  # revokes `old`
        for t in (old,):
            assert (await client.get(f"/v1/public/account-invites/{t}")).status_code == 404
            assert (
                await client.post(
                    f"/v1/public/account-invites/{t}/accept", json={"password": VALID_PASSWORD}
                )
            ).status_code == 404
        await _force_invite_expired(company_id=tenant.company_id, email=email)
        assert (await client.get(f"/v1/public/account-invites/{new}")).status_code == 404
        assert (
            await client.post(
                f"/v1/public/account-invites/{new}/accept", json={"password": VALID_PASSWORD}
            )
        ).status_code == 404
        # no user was created by any of the rejected attempts
        factory = get_session_factory()
        async with factory() as session:
            assert (
                await session.execute(select(User).where(User.email == email))
            ).scalar_one_or_none() is None
    finally:
        await teardown(tenant)


@pytest.mark.parametrize(
    "token", ["", " ", "%20", "../../etc/passwd", "a" * 5000, "😀", "' OR '1'='1"]
)
async def test_garbage_tokens_never_500(client: AsyncClient, token: str) -> None:
    get = await client.get(f"/v1/public/account-invites/{token}")
    post = await client.post(
        f"/v1/public/account-invites/{token}/accept", json={"password": VALID_PASSWORD}
    )
    assert get.status_code in (404, 405, 422), get.text
    assert post.status_code in (404, 405, 422), post.text


async def test_resolve_leaks_nothing_beyond_the_minimum(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant = await register_tenant(client)
    try:
        token = await _invite(client, tenant, _email(), "COMPANY_ADMIN")
        r = await client.get(f"/v1/public/account-invites/{token}")
        assert r.status_code == 200
        assert set(r.json()["data"]) == {"email", "company_name", "expires_at", "existing_account"}
        assert "COMPANY_ADMIN" not in r.text
        assert "company_id" not in r.text
    finally:
        await teardown(tenant)


async def test_accept_body_validation(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    tenant = await register_tenant(client)
    try:
        token = await _invite(client, tenant, _email())
        url = f"/v1/public/account-invites/{token}/accept"
        bad_bodies = [
            {},
            {"password": ""},
            {"password": None},
            {"password": 12345678},
            {"password": VALID_PASSWORD, "first_name": "x" * 101},
            {"password": VALID_PASSWORD, "last_name": "x" * 101},
            {"password": "12345678"},  # digits only
            {"password": "abcdefgh"},  # letters only
            {"password": "Ab1"},  # too short
            {"password": "Password1"},  # blocklisted common password
        ]
        for body in bad_bodies:
            await reset_auth_rate_limit()
            r = await client.post(url, json=body)
            assert r.status_code == 422, (body, r.text)
        # a rejected accept must not burn the token
        await reset_auth_rate_limit()
        ok = await client.post(url, json={"password": VALID_PASSWORD})
        assert ok.status_code == 201, ok.text
    finally:
        await teardown(tenant)


async def test_huge_password_is_rejected_not_hashed(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """An unauthenticated endpoint that argon2-hashes an attacker-sized string is a CPU/memory
    amplifier. A sane upper bound must reject it up front."""
    tenant = await register_tenant(client)
    try:
        token = await _invite(client, tenant, _email())
        r = await client.post(
            f"/v1/public/account-invites/{token}/accept",
            json={"password": "Aa1" + "x" * 1_000_000},
        )
        assert r.status_code == 422, r.status_code
        login = await client.post(
            "/v1/auth/login", json={"email": "a@example.com", "password": "x" * 1_000_000}
        )
        assert login.status_code == 422, login.status_code
    finally:
        await teardown(tenant)


async def test_accept_persists_names_marks_verified_and_allows_login(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant = await register_tenant(client)
    try:
        email = _email()
        token = await _invite(client, tenant, email, "HR_ADMIN")
        r = await client.post(
            f"/v1/public/account-invites/{token}/accept",
            json={"password": VALID_PASSWORD, "first_name": "Ravi", "last_name": "Kumar"},
        )
        assert r.status_code == 201
        assert "refresh_token" not in r.json()["data"]  # cookie only
        assert r.cookies.get("hrms_refresh")
        factory = get_session_factory()
        async with factory() as session:
            user = (await session.execute(select(User).where(User.email == email))).scalar_one()
        assert (user.first_name, user.last_name) == ("Ravi", "Kumar")
        assert user.email_verified_at is not None
        assert user.status == "ACTIVE"
        assert user.password_hash and VALID_PASSWORD not in user.password_hash
        login = await client.post(
            "/v1/auth/login", json={"email": email, "password": VALID_PASSWORD}
        )
        assert login.status_code == 200
    finally:
        await teardown(tenant)


async def test_accept_for_employee_links_account_and_jwt_carries_employee_id(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    import jwt as pyjwt

    tenant = await register_tenant(client)
    try:
        email = _email("empl")
        tenant.emails.append(email)
        emp = await client.post(
            "/v1/employees",
            headers=tenant.headers,
            json={"first_name": "Link", "personal_email": email},
        )
        employee_id = emp.json()["data"]["id"]
        invite = await client.post(f"/v1/employees/{employee_id}/invite", headers=tenant.headers)
        token = _token_from_invite_url(invite.json()["data"]["invite_url"])
        accept = await client.post(
            f"/v1/public/account-invites/{token}/accept", json={"password": VALID_PASSWORD}
        )
        claims = pyjwt.decode(
            accept.json()["data"]["access_token"], options={"verify_signature": False}
        )
        assert claims["employee_id"] == employee_id
        # now has an account: a second invite is a 409, not a silent second user
        again = await client.post(f"/v1/employees/{employee_id}/invite", headers=tenant.headers)
        assert again.status_code == 409
        assert again.json()["error"]["code"] == "EMPLOYEE_ALREADY_HAS_ACCOUNT"
    finally:
        await teardown(tenant)


async def test_concurrent_accepts_of_one_token_create_exactly_one_account(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant = await register_tenant(client)
    try:
        email = _email("race")
        token = await _invite(client, tenant, email)
        url = f"/v1/public/account-invites/{token}/accept"
        results = await asyncio.gather(
            *[client.post(url, json={"password": VALID_PASSWORD}) for _ in range(5)],
            return_exceptions=True,
        )
        statuses = sorted(getattr(r, "status_code", -1) for r in results)
        assert statuses.count(201) == 1, statuses
        assert all(s in (201, 404, 409, 401) for s in statuses), statuses  # never 500
        factory = get_session_factory()
        async with factory() as session:
            users = (await session.execute(select(User).where(User.email == email))).scalars().all()
            assert len(users) == 1
            await set_rls_company_id(session, str(tenant.company_id))
            memberships = (
                (
                    await session.execute(
                        select(UserCompany).where(UserCompany.user_id == users[0].id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(memberships) == 1
    finally:
        await teardown(tenant)


# ---------------------------------------------------------------- existing accounts (SEC-08)


async def test_existing_account_gets_second_company_non_primary_and_can_pick_either(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    a = await register_tenant(client)
    b = await register_tenant(client)
    try:
        member = await onboard(client, a, "EMPLOYEE")
        b.emails.append(member.email)
        token = await _invite(client, b, member.email, "HR_ADMIN")
        resolved = await client.get(f"/v1/public/account-invites/{token}")
        assert resolved.json()["data"]["existing_account"] is True
        accept = await client.post(
            f"/v1/public/account-invites/{token}/accept", json={"password": member.password}
        )
        assert accept.status_code == 201, accept.text
        assert len(accept.json()["data"]["companies"]) == 2

        factory = get_session_factory()
        async with factory() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT company_id, is_primary FROM login_lookup_user_companies"
                        "(CAST(:u AS uuid))"
                    ),
                    {"u": str(member.user_id)},
                )
            ).all()
        primaries = {str(r.company_id): r.is_primary for r in rows}
        assert primaries[str(a.company_id)] is True
        assert primaries[str(b.company_id)] is False

        # Roles are per company: HR_ADMIN in B, EMPLOYEE-only in A.
        for company, expected in ((a, 403), (b, 403)):
            login = await client.post(
                "/v1/auth/login",
                json={
                    "email": member.email,
                    "password": member.password,
                    "company_id": str(company.company_id),
                },
            )
            assert login.status_code == 200
            h = {
                "Authorization": f"Bearer {login.json()['data']['access_token']}",
                "X-Company-Id": str(company.company_id),
            }
            # neither holds SETTINGS.USER.MANAGE
            assert (await client.get("/v1/users", headers=h)).status_code == expected
        me_b = await client.post(
            "/v1/auth/login",
            json={
                "email": member.email,
                "password": member.password,
                "company_id": str(b.company_id),
            },
        )
        hb = {"Authorization": f"Bearer {me_b.json()['data']['access_token']}"}
        perms_b = (await client.get("/v1/auth/me", headers=hb)).json()["data"]["user"][
            "permissions"
        ]
        assert "EMPLOYEE.CREATE" in perms_b  # HR_ADMIN in B
        me_a = await client.post(
            "/v1/auth/login",
            json={
                "email": member.email,
                "password": member.password,
                "company_id": str(a.company_id),
            },
        )
        ha = {"Authorization": f"Bearer {me_a.json()['data']['access_token']}"}
        perms_a = (await client.get("/v1/auth/me", headers=ha)).json()["data"]["user"][
            "permissions"
        ]
        assert "EMPLOYEE.CREATE" not in perms_a  # privileges did not bleed across tenants
    finally:
        await teardown_all(a, b)


async def test_existing_account_wrong_passwords_lock_the_account_and_never_consume_the_invite(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    a = await register_tenant(client)
    b = await register_tenant(client)
    try:
        victim = await onboard(client, a, "EMPLOYEE")
        b.emails.append(victim.email)
        token = await _invite(client, b, victim.email, "COMPANY_ADMIN")
        url = f"/v1/public/account-invites/{token}/accept"
        for _ in range(5):
            r = await client.post(url, json={"password": "WrongGuess123"})
            assert r.status_code == 401
        # locked now: even the right password is refused (brute-force guard shared with login)
        locked = await client.post(url, json={"password": victim.password})
        assert locked.status_code in (401, 423, 429), locked.text
        login = await client.post(
            "/v1/auth/login", json={"email": victim.email, "password": victim.password}
        )
        assert login.status_code != 200
        # no membership / role in B was granted at any point
        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, str(b.company_id))
            got = (
                await session.execute(
                    select(UserCompany).where(
                        UserCompany.user_id == victim.user_id,
                        UserCompany.company_id == b.company_id,
                    )
                )
            ).scalar_one_or_none()
        assert got is None
    finally:
        await teardown_all(a, b)


async def test_password_field_for_new_account_is_never_checked_against_someone_elses(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A new invitee must be able to choose a password even when it equals another user's."""
    tenant = await register_tenant(client)
    try:
        first = await onboard(client, tenant, "EMPLOYEE", password="SharedChoice77x")
        second = await onboard(client, tenant, "EMPLOYEE", password="SharedChoice77x")
        assert first.user_id != second.user_id
    finally:
        await teardown(tenant)


async def test_same_new_email_accepted_concurrently_from_two_companies_never_500s(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Different tokens, same not-yet-registered email: row-locking one invite cannot serialise
    them, so the loser hits the global unique index on `user.email`. It must surface as a clean
    retryable conflict, and exactly one account must exist."""
    a = await register_tenant(client)
    b = await register_tenant(client)
    try:
        email = _email("dual")
        token_a = await _invite(client, a, email)
        token_b = await _invite(client, b, email)
        await reset_auth_rate_limit()
        results = await asyncio.gather(
            client.post(
                f"/v1/public/account-invites/{token_a}/accept", json={"password": VALID_PASSWORD}
            ),
            client.post(
                f"/v1/public/account-invites/{token_b}/accept", json={"password": VALID_PASSWORD}
            ),
            return_exceptions=True,
        )
        statuses = sorted(getattr(r, "status_code", -1) for r in results)
        assert statuses[0] != -1, f"unhandled exception escaped: {results}"
        assert 201 in statuses
        assert all(s in (201, 409, 401) for s in statuses), statuses
        factory = get_session_factory()
        async with factory() as session:
            users = (await session.execute(select(User).where(User.email == email))).scalars().all()
        assert len(users) == 1
    finally:
        await teardown_all(a, b)
