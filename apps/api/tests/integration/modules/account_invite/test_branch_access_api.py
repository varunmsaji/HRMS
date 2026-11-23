"""Admin-assigned branch access through the user-management API: `PUT /users/{id}/branches`,
`PATCH /users/{id}/roles` with `branch_ids`, and the invite flow.

Every user is created through the real invite -> accept flow (see `uac_helpers`), so the role seeds
and permission grants are the production ones."""

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from tests.integration.branch_access_support import make_branch

from hrms.core.audit.models import AuditLog
from hrms.core.db.models.identity import User, UserBranchAccess
from hrms.core.db.session import get_session_factory, set_rls_company_id

from ..organisation.test_registration_flow import VALID_PASSWORD
from .test_account_invite import _token_from_invite_url
from .uac_helpers import Tenant, onboard, register_tenant, teardown

pytestmark = pytest.mark.asyncio


async def _live_branches(company_id: UUID, user_id: UUID) -> set[UUID]:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        rows = await session.execute(
            select(UserBranchAccess.branch_id).where(
                UserBranchAccess.company_id == company_id,
                UserBranchAccess.user_id == user_id,
                UserBranchAccess.deleted_at.is_(None),
            )
        )
        return set(rows.scalars().all())


async def _access_row_ids(company_id: UUID, user_id: UUID) -> set[UUID]:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        rows = await session.execute(
            select(UserBranchAccess.id).where(
                UserBranchAccess.company_id == company_id,
                UserBranchAccess.user_id == user_id,
                UserBranchAccess.deleted_at.is_(None),
            )
        )
        return set(rows.scalars().all())


async def _audit_actions(company_id: UUID, action: str) -> list[AuditLog]:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        rows = await session.execute(
            select(AuditLog).where(AuditLog.company_id == company_id, AuditLog.action == action)
        )
        return list(rows.scalars().all())


async def _deactivate_branch(company_id: UUID, branch_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        await session.execute(
            text("UPDATE branch SET is_active = false WHERE id = :b AND company_id = :c"),
            {"b": str(branch_id), "c": str(company_id)},
        )
        await session.commit()


async def _roles_of(client: AsyncClient, tenant: Tenant, user_id: UUID) -> list[str]:
    """The role codes `GET /users` reports for one user."""
    r = await client.get("/v1/users", headers=tenant.headers, params={"page_size": 100})
    assert r.status_code == 200, r.text
    row = next(u for u in r.json()["data"] if u["user_id"] == str(user_id))
    return sorted(row["role_codes"])


def _put(client: AsyncClient, tenant: Tenant, user_id: UUID, branch_ids: list[UUID]):
    return client.put(
        f"/v1/users/{user_id}/branches",
        headers=tenant.headers,
        json={"branch_ids": [str(b) for b in branch_ids]},
    )


# --- PUT /users/{id}/branches ------------------------------------------------------------------


async def test_put_branches_replaces_the_list_and_is_idempotent(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant = await register_tenant(client)
    try:
        hr = await onboard(client, tenant, "HR_ADMIN")
        original = tenant.branch_id
        assert original is not None
        second = await make_branch(tenant.company_id)
        third = await make_branch(tenant.company_id)

        r = await _put(client, tenant, hr.user_id, [second, third])
        assert r.status_code == 200, r.text
        assert set(map(UUID, r.json()["data"]["branch_ids"])) == {second, third}
        assert await _live_branches(tenant.company_id, hr.user_id) == {second, third}
        assert original not in await _live_branches(tenant.company_id, hr.user_id)

        rows_before = await _access_row_ids(tenant.company_id, hr.user_id)
        audits_before = len(await _audit_actions(tenant.company_id, "USER_BRANCH_ACCESS_SET"))
        again = await _put(client, tenant, hr.user_id, [third, second])
        assert again.status_code == 200, again.text
        assert await _access_row_ids(tenant.company_id, hr.user_id) == rows_before
        assert (
            len(await _audit_actions(tenant.company_id, "USER_BRANCH_ACCESS_SET")) == audits_before
        )
    finally:
        await teardown(tenant)


async def test_put_branches_rejected_for_a_user_without_hr_or_branch_manager(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant = await register_tenant(client)
    try:
        employee = await onboard(client, tenant, "EMPLOYEE")
        branch = await make_branch(tenant.company_id)
        r = await _put(client, tenant, employee.user_id, [branch])
        assert r.status_code == 422, r.text
        assert r.json()["error"]["details"][0]["code"] == "BRANCH_ACCESS_NOT_APPLICABLE"
        assert await _live_branches(tenant.company_id, employee.user_id) == set()
    finally:
        await teardown(tenant)


async def test_put_branches_rejects_an_empty_list(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant = await register_tenant(client)
    try:
        hr = await onboard(client, tenant, "HR_ADMIN")
        r = await _put(client, tenant, hr.user_id, [])
        assert r.status_code == 422, r.text
        assert r.json()["error"]["details"][0]["code"] == "BRANCH_ACCESS_REQUIRED"
        assert await _live_branches(tenant.company_id, hr.user_id) == {tenant.branch_id}
    finally:
        await teardown(tenant)


async def test_put_branches_with_another_companys_branch_is_404(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant = await register_tenant(client)
    other = await register_tenant(client)
    try:
        hr = await onboard(client, tenant, "HR_ADMIN")
        foreign = await make_branch(other.company_id)
        r = await _put(client, tenant, hr.user_id, [foreign])
        assert r.status_code == 404, r.text
        assert await _live_branches(tenant.company_id, hr.user_id) == {tenant.branch_id}
    finally:
        await teardown(tenant)
        await teardown(other)


async def test_put_branches_with_an_inactive_branch_is_422(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant = await register_tenant(client)
    try:
        hr = await onboard(client, tenant, "HR_ADMIN")
        dead = await make_branch(tenant.company_id)
        await _deactivate_branch(tenant.company_id, dead)
        r = await _put(client, tenant, hr.user_id, [dead])
        assert r.status_code == 422, r.text
        assert r.json()["error"]["details"][0]["code"] == "INACTIVE_BRANCH"
        assert await _live_branches(tenant.company_id, hr.user_id) == {tenant.branch_id}
    finally:
        await teardown(tenant)


async def test_put_branches_on_yourself_is_409(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant = await register_tenant(client)
    try:
        assert tenant.admin_user_id is not None
        branch = await make_branch(tenant.company_id)
        r = await _put(client, tenant, tenant.admin_user_id, [branch])
        assert r.status_code == 409, r.text
        assert r.json()["error"]["details"][0]["code"] == "SELF_BRANCH_CHANGE_NOT_ALLOWED"
    finally:
        await teardown(tenant)


async def test_put_branches_is_forbidden_to_an_hr_administrator(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant = await register_tenant(client)
    try:
        hr = await onboard(client, tenant, "HR_ADMIN")
        other_hr = await onboard(client, tenant, "HR_ADMIN")
        branch = await make_branch(tenant.company_id)
        r = await client.put(
            f"/v1/users/{other_hr.user_id}/branches",
            headers=hr.headers,
            json={"branch_ids": [str(branch)]},
        )
        assert r.status_code == 403, r.text
        assert await _live_branches(tenant.company_id, other_hr.user_id) == {tenant.branch_id}
    finally:
        await teardown(tenant)


# --- PATCH /users/{id}/roles with branch_ids ---------------------------------------------------


async def test_patch_roles_hr_without_branches_is_rejected_and_writes_nothing(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant = await register_tenant(client)
    try:
        target = await onboard(client, tenant, "EMPLOYEE")
        r = await client.patch(
            f"/v1/users/{target.user_id}/roles",
            headers=tenant.headers,
            json={"role_codes": ["HR_ADMIN"]},
        )
        assert r.status_code == 422, r.text
        assert r.json()["error"]["details"][0]["code"] == "BRANCH_ACCESS_REQUIRED"
        assert await _roles_of(client, tenant, target.user_id) == ["EMPLOYEE"]
        assert await _live_branches(tenant.company_id, target.user_id) == set()
    finally:
        await teardown(tenant)


async def test_patch_roles_saves_roles_and_branches_together(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant = await register_tenant(client)
    try:
        target = await onboard(client, tenant, "EMPLOYEE")
        branch = await make_branch(tenant.company_id)
        r = await client.patch(
            f"/v1/users/{target.user_id}/roles",
            headers=tenant.headers,
            json={"role_codes": ["HR_ADMIN"], "branch_ids": [str(branch)]},
        )
        assert r.status_code == 200, r.text
        assert await _roles_of(client, tenant, target.user_id) == ["HR_ADMIN"]
        assert await _live_branches(tenant.company_id, target.user_id) == {branch}
    finally:
        await teardown(tenant)


async def test_patch_roles_with_a_bad_branch_leaves_the_roles_unchanged(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant = await register_tenant(client)
    try:
        target = await onboard(client, tenant, "EMPLOYEE")
        dead = await make_branch(tenant.company_id)
        await _deactivate_branch(tenant.company_id, dead)
        r = await client.patch(
            f"/v1/users/{target.user_id}/roles",
            headers=tenant.headers,
            json={"role_codes": ["HR_ADMIN"], "branch_ids": [str(dead)]},
        )
        assert r.status_code == 422, r.text
        assert await _roles_of(client, tenant, target.user_id) == ["EMPLOYEE"]
        assert await _live_branches(tenant.company_id, target.user_id) == set()
    finally:
        await teardown(tenant)


async def test_patch_roles_dropping_both_roles_clears_the_branch_list(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant = await register_tenant(client)
    try:
        hr = await onboard(client, tenant, "HR_ADMIN")
        assert await _live_branches(tenant.company_id, hr.user_id) == {tenant.branch_id}
        r = await client.patch(
            f"/v1/users/{hr.user_id}/roles",
            headers=tenant.headers,
            json={"role_codes": ["EMPLOYEE"]},
        )
        assert r.status_code == 200, r.text
        assert await _live_branches(tenant.company_id, hr.user_id) == set()
    finally:
        await teardown(tenant)


async def test_company_admin_and_hr_together_need_no_branches(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant = await register_tenant(client)
    try:
        target = await onboard(client, tenant, "EMPLOYEE")
        r = await client.patch(
            f"/v1/users/{target.user_id}/roles",
            headers=tenant.headers,
            json={"role_codes": ["COMPANY_ADMIN", "HR_ADMIN"]},
        )
        assert r.status_code == 200, r.text
        assert await _roles_of(client, tenant, target.user_id) == ["COMPANY_ADMIN", "HR_ADMIN"]
        assert await _live_branches(tenant.company_id, target.user_id) == set()
    finally:
        await teardown(tenant)


# --- invites -----------------------------------------------------------------------------------


async def test_invite_hr_without_branches_is_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant = await register_tenant(client)
    try:
        for role in ("HR_ADMIN", "BRANCH_MANAGER"):
            r = await client.post(
                "/v1/users/invite",
                headers=tenant.headers,
                json={"email": f"x-{uuid4().hex[:8]}@example.com", "role_code": role},
            )
            assert r.status_code == 422, r.text
            assert r.json()["error"]["details"][0]["code"] == "BRANCH_ACCESS_REQUIRED"
    finally:
        await teardown(tenant)


async def test_invite_employee_role_with_branches_is_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant = await register_tenant(client)
    try:
        branch = await make_branch(tenant.company_id)
        r = await client.post(
            "/v1/users/invite",
            headers=tenant.headers,
            json={
                "email": f"x-{uuid4().hex[:8]}@example.com",
                "role_code": "EMPLOYEE",
                "branch_ids": [str(branch)],
            },
        )
        assert r.status_code == 422, r.text
        assert r.json()["error"]["details"][0]["code"] == "BRANCH_ACCESS_NOT_APPLICABLE"
    finally:
        await teardown(tenant)


async def test_accepting_an_invite_writes_the_access_rows(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant = await register_tenant(client)
    try:
        second = await make_branch(tenant.company_id)
        email = f"hr-{uuid4().hex[:8]}@example.com"
        tenant.emails.append(email)
        first = await make_branch(tenant.company_id)
        invite = await client.post(
            "/v1/users/invite",
            headers=tenant.headers,
            json={
                "email": email,
                "role_code": "HR_ADMIN",
                "branch_ids": [str(first), str(second)],
            },
        )
        assert invite.status_code == 201, invite.text
        token = _token_from_invite_url(invite.json()["data"]["invite_url"])
        accept = await client.post(
            f"/v1/public/account-invites/{token}/accept", json={"password": VALID_PASSWORD}
        )
        assert accept.status_code == 201, accept.text
        factory = get_session_factory()
        async with factory() as session:
            user_id = (
                await session.execute(select(User.id).where(User.email == email))
            ).scalar_one()
        assert await _live_branches(tenant.company_id, user_id) == {first, second}
    finally:
        await teardown(tenant)


async def test_accepting_after_every_named_branch_was_deactivated_creates_no_user(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant = await register_tenant(client)
    try:
        branch = await make_branch(tenant.company_id)
        email = f"hr-{uuid4().hex[:8]}@example.com"
        tenant.emails.append(email)
        invite = await client.post(
            "/v1/users/invite",
            headers=tenant.headers,
            json={"email": email, "role_code": "HR_ADMIN", "branch_ids": [str(branch)]},
        )
        assert invite.status_code == 201, invite.text
        token = _token_from_invite_url(invite.json()["data"]["invite_url"])
        await _deactivate_branch(tenant.company_id, branch)
        accept = await client.post(
            f"/v1/public/account-invites/{token}/accept", json={"password": VALID_PASSWORD}
        )
        assert accept.status_code == 409, accept.text
        assert accept.json()["error"]["details"][0]["code"] == "INVITE_BRANCHES_UNAVAILABLE"
        factory = get_session_factory()
        async with factory() as session:
            created = (await session.execute(select(User.id).where(User.email == email))).first()
        assert created is None
    finally:
        await teardown(tenant)


# --- listing and audit -------------------------------------------------------------------------


async def test_users_listing_shows_branch_ids(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant = await register_tenant(client)
    try:
        hr = await onboard(client, tenant, "HR_ADMIN")
        employee = await onboard(client, tenant, "EMPLOYEE")
        r = await client.get("/v1/users", headers=tenant.headers, params={"page_size": 100})
        assert r.status_code == 200, r.text
        rows = {u["user_id"]: u for u in r.json()["data"]}
        assert rows[str(hr.user_id)]["branch_ids"] == [str(tenant.branch_id)]
        assert rows[str(employee.user_id)]["branch_ids"] == []
    finally:
        await teardown(tenant)


async def test_branch_access_changes_are_audited(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant = await register_tenant(client)
    try:
        hr = await onboard(client, tenant, "HR_ADMIN")
        new_branch = await make_branch(tenant.company_id)
        assert (await _put(client, tenant, hr.user_id, [new_branch])).status_code == 200
        rows = await _audit_actions(tenant.company_id, "USER_BRANCH_ACCESS_SET")
        # One from accepting the invite, one from the PUT.
        assert len(rows) == 2
        put_row = next(r for r in rows if r.after_json == {"branch_ids": [str(new_branch)]})
        assert put_row.actor_user_id == tenant.admin_user_id
        assert put_row.entity_id == hr.user_id
    finally:
        await teardown(tenant)
