"""Integration tests for `GET /v1/users` pagination (FINDING-03).

Mirrors `employee/test_employee_pagination.py`'s exact contract checks (defaults, explicit
page/per_page, empty dataset, beyond-final-page, invalid params, server max, deterministic
paging, tenant isolation) for the one remaining unbounded endpoint the pre-payroll audit found
in the account-invite module. Extra memberships are seeded directly at the database layer
(`User`/`UserCompany` rows) rather than through the full invite-and-accept email flow — this
test is about pagination mechanics, not invite business logic, which `test_account_invite.py`
already covers."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from hrms.core.db.models.identity import User, UserCompany
from hrms.core.db.session import get_session_factory

from ..organisation.test_registration_flow import VALID_PASSWORD, _cleanup
from .test_account_invite import (
    _create_employee,
    _register_tenant,
    _teardown,
    _token_from_invite_url,
)

pytestmark = pytest.mark.asyncio


async def _seed_extra_users(*, company_id: UUID, count: int, prefix: str = "Extra") -> list[UUID]:
    # Explicit `created_at`/`updated_at` sidestep a bulk-insert quirk: SQLAlchemy's
    # insertmanyvalues batching for several new rows in one flush omits server-defaulted
    # columns from the INSERT expecting Postgres to fill them, but there is no DB-level DEFAULT
    # on `user.updated_at` (only the ORM's own `server_default` metadata) — fine for the
    # single-row `session.add`/`flush` the app itself always uses, not for this batch.
    now = datetime.now(UTC)
    factory = get_session_factory()
    user_ids: list[UUID] = []
    async with factory() as session:
        for i in range(count):
            user_id = uuid4()
            session.add(
                User(
                    id=user_id,
                    email=f"{prefix.lower()}{i:03d}-{user_id.hex[:8]}@example.com",
                    first_name=f"{prefix}{i:03d}",
                    created_at=now,
                    updated_at=now,
                )
            )
            session.add(
                UserCompany(
                    id=uuid4(),
                    company_id=company_id,
                    user_id=user_id,
                    created_at=now,
                    updated_at=now,
                )
            )
            user_ids.append(user_id)
        await session.commit()
    return user_ids


async def _cleanup_extra_users(*, user_ids: list[UUID]) -> None:
    factory = get_session_factory()
    async with factory() as session:
        for user_id in user_ids:
            await session.execute(
                UserCompany.__table__.delete().where(UserCompany.user_id == user_id)
            )
            await session.execute(User.__table__.delete().where(User.id == user_id))
        await session.commit()


async def test_default_page_returns_first_25(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    extra_ids: list[UUID] = []
    try:
        # the registering admin is already one UserCompany row; 26 more makes 27 total.
        extra_ids = await _seed_extra_users(company_id=company_id, count=26)

        response = await client.get("/v1/users", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert len(body["data"]) == 25
        assert body["pagination"] == {
            "page": 1,
            "per_page": 25,
            "total": 27,
            "total_pages": 2,
            "next_cursor": None,
        }
        assert len({row["user_id"] for row in body["data"]}) == 25
    finally:
        await _cleanup_extra_users(user_ids=extra_ids)
        await _cleanup(company_id=company_id, user_id=admin_id)


async def test_explicit_page_and_per_page(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    extra_ids: list[UUID] = []
    try:
        extra_ids = await _seed_extra_users(company_id=company_id, count=11)  # + admin = 12

        response = await client.get("/v1/users?page=2&per_page=5", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert len(body["data"]) == 5
        assert body["pagination"]["page"] == 2
        assert body["pagination"]["per_page"] == 5
        assert body["pagination"]["total"] == 12
        assert body["pagination"]["total_pages"] == 3
    finally:
        await _cleanup_extra_users(user_ids=extra_ids)
        await _cleanup(company_id=company_id, user_id=admin_id)


async def test_page_beyond_final_page_returns_empty_data(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        response = await client.get("/v1/users?page=99", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["data"] == []
        assert body["pagination"]["total"] == 1  # just the registering admin
        assert body["pagination"]["total_pages"] == 1
    finally:
        await _cleanup(company_id=company_id, user_id=admin_id)


@pytest.mark.parametrize("query", ["page=0", "page=-1", "per_page=0", "per_page=101"])
async def test_invalid_pagination_params_rejected(
    client: AsyncClient, seeded_plan_catalogue: None, query: str
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        response = await client.get(f"/v1/users?{query}", headers=headers)
        assert response.status_code == 422
    finally:
        await _cleanup(company_id=company_id, user_id=admin_id)


async def test_max_page_size_boundary_accepted(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        response = await client.get("/v1/users?per_page=100", headers=headers)
        assert response.status_code == 200
        assert response.json()["pagination"]["per_page"] == 100
    finally:
        await _cleanup(company_id=company_id, user_id=admin_id)


async def test_pagination_deterministic_no_duplicates_no_gaps(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    extra_ids: list[UUID] = []
    try:
        extra_ids = await _seed_extra_users(company_id=company_id, count=16)  # + admin = 17

        seen_ids: list[str] = []
        page = 1
        while True:
            response = await client.get(f"/v1/users?page={page}&per_page=5", headers=headers)
            assert response.status_code == 200
            body = response.json()
            if not body["data"]:
                break
            seen_ids.extend(row["user_id"] for row in body["data"])
            if page >= body["pagination"]["total_pages"]:
                break
            page += 1

        assert len(seen_ids) == 17
        assert len(set(seen_ids)) == 17
    finally:
        await _cleanup_extra_users(user_ids=extra_ids)
        await _cleanup(company_id=company_id, user_id=admin_id)


async def test_tenant_isolation_pagination_total(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Another tenant's users never contribute to this tenant's `pagination.total`."""
    headers_a, company_a, admin_a = await _register_tenant(client)
    headers_b, company_b, admin_b = await _register_tenant(client)
    extra_a: list[UUID] = []
    extra_b: list[UUID] = []
    try:
        extra_a = await _seed_extra_users(company_id=company_a, count=2, prefix="TenantA")
        extra_b = await _seed_extra_users(company_id=company_b, count=8, prefix="TenantB")

        response_a = await client.get("/v1/users", headers=headers_a)
        assert response_a.json()["pagination"]["total"] == 3

        response_b = await client.get("/v1/users", headers=headers_b)
        assert response_b.json()["pagination"]["total"] == 9
    finally:
        await _cleanup_extra_users(user_ids=extra_a)
        await _cleanup(company_id=company_a, user_id=admin_a)
        await _cleanup_extra_users(user_ids=extra_b)
        await _cleanup(company_id=company_b, user_id=admin_b)


async def test_authorization_unchanged_by_pagination(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`SETTINGS.USER.MANAGE` still gates this endpoint — pagination params don't bypass it.
    An accepted-invite `EMPLOYEE`-role user (no `SETTINGS.USER.MANAGE`) gets 403, the same as an
    unauthenticated caller gets 401."""
    headers, company_id, admin_id = await _register_tenant(client)
    invitee_email = f"invitee-{uuid4().hex[:8]}@example.com"
    try:
        employee = await _create_employee(client, headers, personal_email=invitee_email)
        invite = (
            await client.post(f"/v1/employees/{employee['id']}/invite", headers=headers)
        ).json()["data"]
        token = _token_from_invite_url(invite["invite_url"])
        accepted = (
            await client.post(
                f"/v1/public/account-invites/{token}/accept", json={"password": VALID_PASSWORD}
            )
        ).json()["data"]
        employee_headers = {
            "Authorization": f"Bearer {accepted['access_token']}",
            "X-Company-Id": str(company_id),
        }

        scoped = await client.get("/v1/users?page=1", headers=employee_headers)
        assert scoped.status_code == 403

        anonymous = await client.get("/v1/users?page=1")
        assert anonymous.status_code == 401
    finally:
        await _teardown(company_id=company_id, user_id=admin_id, extra_emails=[invitee_email])
