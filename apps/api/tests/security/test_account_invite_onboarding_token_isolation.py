"""Proves FINDING-04's security decision (`docs/architecture/POSTGRES_RLS_ROLE_MIGRATION_PLAN.md`
§23): `account_invite` and `onboarding_token` carry no Row-Level Security policy, by design, and
that is safe because (1) every authenticated, client-facing path still filters by the caller's own
server-resolved `company_id`, never a client-supplied one, (2) `token_hash` is globally unique, not
per-company, so no two tenants can ever collide on the one key the public, pre-tenant-context
routes are allowed to look up by, and (3) `company_id` on both tables is only ever server-written.

Mirrors `tests/security/test_rls_runtime_role.py`'s cross-tenant proof pattern for the 19
RLS-backed tables, adapted to the two tables that are documented exceptions instead."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError
from tests.integration.modules.account_invite.test_account_invite import (
    _create_employee as _create_employee_for_invite,
)
from tests.integration.modules.account_invite.test_account_invite import (
    _teardown as _teardown_account_invite,
)
from tests.integration.modules.account_invite.test_account_invite import (
    _token_from_invite_url,
)
from tests.integration.modules.onboarding.test_onboarding_case import _case_payload
from tests.integration.modules.onboarding.test_onboarding_case import (
    _register_tenant as _register_onboarding_tenant,
)
from tests.integration.modules.onboarding.test_onboarding_case import (
    _teardown as _teardown_onboarding,
)
from tests.integration.modules.organisation.test_registration_flow import VALID_PASSWORD, _register

from hrms.core.db.session import get_session_factory
from hrms.modules.account_invite.models import AccountInvite
from hrms.modules.onboarding.models import OnboardingToken

pytestmark = pytest.mark.asyncio


async def _register_tenant(
    client: AsyncClient, **overrides: Any
) -> tuple[dict[str, str], UUID, UUID | None]:
    response, company_id, user_id = await _register(client, **overrides)
    assert response.status_code == 201, response.text
    assert company_id is not None
    data = response.json()["data"]
    return (
        {"Authorization": f"Bearer {data['access_token']}", "X-Company-Id": str(company_id)},
        company_id,
        user_id,
    )


async def test_token_hash_is_globally_unique_not_per_company(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The one lookup key either public route accepts cannot collide across tenants — a DB-level
    constraint, not just a convention. Two *real* tenants (so every FK — `company_id`,
    `created_by_user_id`, `onboarding_case_id` — points at a row that actually exists) each try to
    claim the same hash; the second insert is rejected for both tables."""
    headers_a, company_a, admin_a = await _register_tenant(client)
    headers_b, company_b, admin_b = await _register_tenant(client)
    case_a, case_b = None, None
    shared_hash = f"collision-{uuid4().hex}"[:64]
    now = datetime.now(UTC)
    factory = get_session_factory()
    try:
        case_a = (
            await client.post("/v1/onboarding-cases", headers=headers_a, json=_case_payload())
        ).json()["data"]
        case_b = (
            await client.post("/v1/onboarding-cases", headers=headers_b, json=_case_payload())
        ).json()["data"]

        async with factory() as session:
            session.add(
                AccountInvite(
                    id=uuid4(),
                    company_id=company_a,
                    email="first@example.com",
                    role_code="EMPLOYEE",
                    token_hash=shared_hash,
                    created_by_user_id=admin_a,
                    expires_at=now + timedelta(days=1),
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.flush()
            session.add(
                AccountInvite(
                    id=uuid4(),
                    company_id=company_b,  # a different tenant
                    email="second@example.com",
                    role_code="EMPLOYEE",
                    token_hash=shared_hash,  # the same hash a second tenant happened to generate
                    created_by_user_id=admin_b,
                    expires_at=now + timedelta(days=1),
                    created_at=now,
                    updated_at=now,
                )
            )
            with pytest.raises(IntegrityError):
                await session.flush()
            await session.rollback()

        async with factory() as session:
            session.add(
                OnboardingToken(
                    id=uuid4(),
                    company_id=company_a,
                    onboarding_case_id=UUID(case_a["id"]),
                    token_hash=shared_hash,
                    expires_at=now + timedelta(days=1),
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.flush()
            session.add(
                OnboardingToken(
                    id=uuid4(),
                    company_id=company_b,
                    onboarding_case_id=UUID(case_b["id"]),
                    token_hash=shared_hash,
                    expires_at=now + timedelta(days=1),
                    created_at=now,
                    updated_at=now,
                )
            )
            with pytest.raises(IntegrityError):
                await session.flush()
            await session.rollback()
    finally:
        # Neither colliding row was ever committed — each `session.rollback()` above reverted
        # its whole transaction, including the first (otherwise-successful) insert — so there is
        # nothing of this test's own making left to clean up beyond the two tenants themselves.
        await _teardown_onboarding(company_id=company_a, user_id=admin_a)
        await _teardown_onboarding(company_id=company_b, user_id=admin_b)


async def test_forged_company_id_in_invite_request_body_is_ignored(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`company_id` on `account_invite` is never client input — `UserInviteRequest` doesn't even
    declare the field, so a client-supplied one is silently dropped and the invite is issued under
    the authenticated caller's own `TenantContext`, never a forged target."""
    headers, company_id, admin_id = await _register_tenant(client)
    other_company_id = uuid4()
    try:
        response = await client.post(
            "/v1/users/invite",
            headers=headers,
            json={
                "email": f"forged-{uuid4().hex[:8]}@example.com",
                "role_code": "EMPLOYEE",
                "company_id": str(other_company_id),  # not a real field on the schema
            },
        )
        assert response.status_code == 201, response.text

        factory = get_session_factory()
        async with factory() as session:
            from sqlalchemy import select

            row = (
                await session.execute(
                    select(AccountInvite).where(AccountInvite.created_by_user_id == admin_id)
                )
            ).scalar_one()
            assert row.company_id == company_id
            assert row.company_id != other_company_id
    finally:
        await _teardown_account_invite(company_id=company_id, user_id=admin_id)


async def test_cross_tenant_users_list_never_leaks_an_invited_user(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`GET /v1/users` is authenticated and company-scoped server-side; an invite accepted under
    company A can never surface in company B's listing, even though `account_invite` itself has no
    RLS policy to fall back on."""
    headers_a, company_a, admin_a = await _register_tenant(client)
    headers_b, company_b, admin_b = await _register_tenant(client)
    invitee_email = f"isolated-{uuid4().hex[:8]}@example.com"
    try:
        employee = await _create_employee_for_invite(
            client, headers_a, personal_email=invitee_email
        )
        invite = (
            await client.post(f"/v1/employees/{employee['id']}/invite", headers=headers_a)
        ).json()["data"]
        token = _token_from_invite_url(invite["invite_url"])
        accepted = await client.post(
            f"/v1/public/account-invites/{token}/accept", json={"password": VALID_PASSWORD}
        )
        assert accepted.status_code == 201, accepted.text

        listed_b = await client.get("/v1/users", headers=headers_b)
        assert listed_b.status_code == 200
        emails_b = {row["email"] for row in listed_b.json()["data"]}
        assert invitee_email not in emails_b

        listed_a = await client.get("/v1/users", headers=headers_a)
        emails_a = {row["email"] for row in listed_a.json()["data"]}
        assert invitee_email in emails_a
    finally:
        await _teardown_account_invite(
            company_id=company_a, user_id=admin_a, extra_emails=[invitee_email]
        )
        await _teardown_account_invite(company_id=company_b, user_id=admin_b)


async def test_cross_tenant_onboarding_case_and_token_never_leak(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`GET /v1/onboarding-cases` under company B never returns company A's case, and the token
    issued for company A's case resolves (by its own `company_id`, server-written) only against
    company A — never reachable or listable from company B's authenticated context."""
    headers_a, company_a, admin_a = await _register_onboarding_tenant(client)
    headers_b, company_b, admin_b = await _register_onboarding_tenant(client)
    try:
        unique_name = f"Isolated{uuid4().hex[:8]}"
        case = (
            await client.post(
                "/v1/onboarding-cases",
                headers=headers_a,
                json=_case_payload(candidate_first_name=unique_name),
            )
        ).json()["data"]
        invite = (
            await client.post(f"/v1/onboarding-cases/{case['id']}/send-invite", headers=headers_a)
        ).json()["data"]
        token = invite["invite_url"].rsplit("/", 1)[-1]

        listed_b = await client.get("/v1/onboarding-cases", headers=headers_b)
        assert listed_b.status_code == 200
        assert case["id"] not in {row["id"] for row in listed_b.json()["data"]}

        # company B cannot read company A's case by id either — 404, not 403 (no existence
        # oracle), same posture `test_onboarding_case.py` already proves for the case itself.
        direct_b = await client.get(f"/v1/onboarding-cases/{case['id']}", headers=headers_b)
        assert direct_b.status_code == 404

        # the public token resolves (it is, by design, reachable without any tenant context —
        # that is the one thing a public link must do) but only ever to company A's own case.
        resolved = await client.get(f"/v1/public/onboarding/{token}")
        assert resolved.status_code == 200
        assert resolved.json()["data"]["candidate_first_name"] == unique_name
    finally:
        # `send-invite` created an `onboarding_token` row referencing `case` — delete it before
        # `_teardown_onboarding` deletes the case, or the FK blocks that delete.
        async with get_session_factory()() as session:
            from sqlalchemy import text

            await session.execute(
                text("DELETE FROM onboarding_token WHERE onboarding_case_id = :case_id"),
                {"case_id": case["id"]},
            )
            await session.commit()
        await _teardown_onboarding(company_id=company_a, user_id=admin_a)
        await _teardown_onboarding(company_id=company_b, user_id=admin_b)
