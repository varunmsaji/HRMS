"""User-management access control: who may call what, tenant isolation, and role assignment.

The permission matrix is exhaustive over the five default roles × every user-management endpoint,
so any future change to a role's grants (or a new endpoint wired to the wrong permission) fails
here with a table of exactly which cells moved."""

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from hrms.core.audit.models import AuditLog
from hrms.core.db.models.identity import UserCompany, UserRole
from hrms.core.db.session import get_session_factory, set_rls_company_id

from .uac_helpers import (
    ALL_ROLES,
    VALID_PASSWORD,
    onboard,
    register_tenant,
    teardown,
)

pytestmark = pytest.mark.asyncio

# endpoint → roles allowed. Only COMPANY_ADMIN holds SETTINGS.USER.MANAGE / SETTINGS.ROLE.MANAGE;
# EMPLOYEE.INVITE is part of the employee catalogue HR_ADMIN also holds.
_EXPECTED_ALLOWED = {
    "list_users": {"COMPANY_ADMIN"},
    "invite_user": {"COMPANY_ADMIN"},
    "assign_roles": {"COMPANY_ADMIN"},
    "users_check": {"COMPANY_ADMIN"},
    "invite_employee": {"COMPANY_ADMIN", "HR_ADMIN"},
}


async def _call(client: AsyncClient, endpoint: str, headers: dict[str, str], ctx: dict) -> int:
    if endpoint == "list_users":
        r = await client.get("/v1/users", headers=headers)
    elif endpoint == "invite_user":
        r = await client.post(
            "/v1/users/invite",
            headers=headers,
            json={"email": f"m-{uuid4().hex[:8]}@example.com", "role_code": "EMPLOYEE"},
        )
    elif endpoint == "assign_roles":
        r = await client.patch(
            f"/v1/users/{ctx['victim_id']}/roles",
            headers=headers,
            json={"role_codes": ["EMPLOYEE"]},
        )
    elif endpoint == "users_check":
        r = await client.get("/v1/auth/admin/users-check", headers=headers)
    elif endpoint == "invite_employee":
        r = await client.post(f"/v1/employees/{ctx['employee_id']}/invite", headers=headers)
    else:  # pragma: no cover
        raise AssertionError(endpoint)
    return r.status_code


async def test_permission_matrix_all_default_roles_all_endpoints(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant = await register_tenant(client)
    try:
        employee = await client.post(
            "/v1/employees",
            headers=tenant.headers,
            json={"first_name": "Matrix", "personal_email": f"mx-{uuid4().hex[:8]}@example.com"},
        )
        assert employee.status_code == 201, employee.text
        victim = await onboard(client, tenant, "EMPLOYEE")
        ctx = {"victim_id": victim.user_id, "employee_id": employee.json()["data"]["id"]}

        actors = {role: await onboard(client, tenant, role) for role in ALL_ROLES}

        mismatches: list[str] = []
        for endpoint, allowed in _EXPECTED_ALLOWED.items():
            for role in ALL_ROLES:
                status = await _call(client, endpoint, actors[role].headers, ctx)
                if role in allowed:
                    # Authorized callers must get past the permission gate. Business-rule
                    # rejections (409/422) are fine — 401/403/5xx are not.
                    ok = status not in (401, 403) and status < 500
                else:
                    ok = status == 403
                if not ok:
                    mismatches.append(f"{role:18} {endpoint:16} -> {status}")
        assert not mismatches, "permission matrix drifted:\n" + "\n".join(mismatches)
    finally:
        await teardown(tenant)


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/v1/users", None),
        ("POST", "/v1/users/invite", {"email": "a@example.com", "role_code": "EMPLOYEE"}),
        ("PATCH", f"/v1/users/{uuid4()}/roles", {"role_codes": ["EMPLOYEE"]}),
        ("POST", f"/v1/employees/{uuid4()}/invite", None),
        ("GET", "/v1/auth/me", None),
        ("GET", "/v1/auth/admin/users-check", None),
        ("POST", "/v1/auth/logout", None),
    ],
)
async def test_every_protected_endpoint_rejects_anonymous_and_garbage_tokens(
    client: AsyncClient, method: str, path: str, body: dict | None
) -> None:
    for headers in (
        {},
        {"Authorization": "Bearer "},
        {"Authorization": "Bearer not-a-jwt"},
        {"Authorization": "Basic Zm9vOmJhcg=="},
        {"Authorization": "Bearer a.b.c"},
    ):
        response = await client.request(method, path, headers=headers, json=body)
        assert response.status_code == 401, (headers, response.text)
        assert response.json()["error"]["code"] in {"UNAUTHORIZED", "INVALID_TOKEN"}


async def test_cross_tenant_isolation_for_user_management(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    a = await register_tenant(client)
    b = await register_tenant(client)
    try:
        b_member = await onboard(client, b, "HR_ADMIN")
        b_employee = await client.post(
            "/v1/employees",
            headers=b.headers,
            json={"first_name": "Bee", "personal_email": f"bee-{uuid4().hex[:8]}@example.com"},
        )
        assert b_employee.status_code == 201

        # 1. A's admin sees only A's users.
        listing = await client.get("/v1/users", headers=a.headers)
        assert listing.status_code == 200
        ids = {row["user_id"] for row in listing.json()["data"]}
        assert str(b_member.user_id) not in ids
        assert str(b.admin_user_id) not in ids

        # 2. A's admin cannot touch B's user: indistinguishable from "does not exist".
        assign = await client.patch(
            f"/v1/users/{b_member.user_id}/roles",
            headers=a.headers,
            json={"role_codes": ["EMPLOYEE"]},
        )
        assert assign.status_code == 404

        # 3. ... nor invite B's employee.
        invite = await client.post(
            f"/v1/employees/{b_employee.json()['data']['id']}/invite", headers=a.headers
        )
        assert invite.status_code == 404

        # 4. A's token paired with B's X-Company-Id header must not pivot into B.
        pivot = await client.get(
            "/v1/users",
            headers={
                "Authorization": a.headers["Authorization"],
                "X-Company-Id": str(b.company_id),
            },
        )
        assert pivot.status_code == 404

        # 5. B's HR_ADMIN token cannot be replayed against A.
        replay = await client.get(
            "/v1/users",
            headers={
                "Authorization": b_member.headers["Authorization"],
                "X-Company-Id": str(a.company_id),
            },
        )
        assert replay.status_code == 404

        # 6. B's data is untouched by 2.
        still = await client.get("/v1/users", headers=b.headers)
        roles = {r["user_id"]: r["role_codes"] for r in still.json()["data"]}
        assert roles[str(b_member.user_id)] == ["HR_ADMIN"]
    finally:
        await teardown(a)
        await teardown(b)


async def test_assign_roles_takes_effect_immediately_on_existing_token(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Permissions are resolved from the DB on every request, not baked into the JWT — a demotion
    must bite on the demoted user's already-issued access token, and a promotion must too."""
    tenant = await register_tenant(client)
    try:
        user = await onboard(client, tenant, "COMPANY_ADMIN")
        assert (await client.get("/v1/users", headers=user.headers)).status_code == 200

        demote = await client.patch(
            f"/v1/users/{user.user_id}/roles",
            headers=tenant.headers,
            json={"role_codes": ["EMPLOYEE"]},
        )
        assert demote.status_code == 200
        assert (await client.get("/v1/users", headers=user.headers)).status_code == 403
        me = await client.get("/v1/auth/me", headers=user.headers)
        assert "SETTINGS.USER.MANAGE" not in me.json()["data"]["user"]["permissions"]

        promote = await client.patch(
            f"/v1/users/{user.user_id}/roles",
            headers=tenant.headers,
            json={"role_codes": ["COMPANY_ADMIN"]},
        )
        assert promote.status_code == 200
        assert (await client.get("/v1/users", headers=user.headers)).status_code == 200
    finally:
        await teardown(tenant)


async def test_multi_role_user_gets_union_of_permissions(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant = await register_tenant(client)
    try:
        user = await onboard(client, tenant, "EMPLOYEE")
        solo_me = await client.get("/v1/auth/me", headers=user.headers)
        solo = set(solo_me.json()["data"]["user"]["permissions"])

        assert (
            await client.patch(
                f"/v1/users/{user.user_id}/roles",
                headers=tenant.headers,
                json={"role_codes": ["EMPLOYEE", "HR_ADMIN"]},
            )
        ).status_code == 200
        both = set(
            (await client.get("/v1/auth/me", headers=user.headers)).json()["data"]["user"][
                "permissions"
            ]
        )
        hr_only_user = await onboard(client, tenant, "HR_ADMIN")
        hr = set(
            (await client.get("/v1/auth/me", headers=hr_only_user.headers)).json()["data"]["user"][
                "permissions"
            ]
        )
        assert solo | hr == both
        assert solo < both

        listing = await client.get("/v1/users", headers=tenant.headers)
        row = next(r for r in listing.json()["data"] if r["user_id"] == str(user.user_id))
        assert row["role_codes"] == ["EMPLOYEE", "HR_ADMIN"]
    finally:
        await teardown(tenant)


async def test_assign_roles_validation_matrix(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant = await register_tenant(client)
    try:
        target = await onboard(client, tenant, "EMPLOYEE")
        url = f"/v1/users/{target.user_id}/roles"

        # Unknown / wrong-case / injection-shaped codes never reach the DB.
        for bad in (
            ["SUPER_ADMIN"],
            ["hr_admin"],
            ["HR_ADMIN ", "EMPLOYEE"],
            ["EMPLOYEE", "NOPE"],
            ["' OR 1=1 --"],
            [""],
        ):
            r = await client.patch(url, headers=tenant.headers, json={"role_codes": bad})
            assert r.status_code == 422, (bad, r.text)
            assert r.json()["error"]["code"] == "INVALID_ROLE_CODE"

        # Wrong shapes are rejected by schema validation, not 500.
        for payload in ({"role_codes": "HR_ADMIN"}, {"role_codes": [1]}, {"role_codes": None}, []):
            r = await client.patch(url, headers=tenant.headers, json=payload)
            assert r.status_code == 422, (payload, r.text)

        # Non-UUID path id.
        r = await client.patch(
            "/v1/users/not-a-uuid/roles", headers=tenant.headers, json={"role_codes": ["EMPLOYEE"]}
        )
        assert r.status_code == 422

        # Unknown user.
        r = await client.patch(
            f"/v1/users/{uuid4()}/roles", headers=tenant.headers, json={"role_codes": ["EMPLOYEE"]}
        )
        assert r.status_code == 404

        # None of the rejected calls changed anything.
        listing = await client.get("/v1/users", headers=tenant.headers)
        row = next(r for r in listing.json()["data"] if r["user_id"] == str(target.user_id))
        assert row["role_codes"] == ["EMPLOYEE"]
    finally:
        await teardown(tenant)


async def test_assign_roles_duplicate_codes_do_not_create_duplicate_grants(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant = await register_tenant(client)
    try:
        target = await onboard(client, tenant, "EMPLOYEE")
        r = await client.patch(
            f"/v1/users/{target.user_id}/roles",
            headers=tenant.headers,
            json={"role_codes": ["HR_ADMIN", "HR_ADMIN", "HR_ADMIN"]},
        )
        assert r.status_code == 200, r.text
        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, str(tenant.company_id))
            membership = (
                await session.execute(
                    select(UserCompany).where(
                        UserCompany.user_id == target.user_id,
                        UserCompany.company_id == tenant.company_id,
                    )
                )
            ).scalar_one()
            rows = (
                (
                    await session.execute(
                        select(UserRole).where(UserRole.user_company_id == membership.id)
                    )
                )
                .scalars()
                .all()
            )
        assert len(rows) == 1
    finally:
        await teardown(tenant)


async def test_assign_roles_empty_list_is_rejected_rather_than_orphaning_the_user(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A member with zero roles is a ghost: active, can log in, can do nothing, and invisible as
    'who is an admin'. Removing every role must be an explicit decision (deactivation), not a
    side-effect of an empty array."""
    tenant = await register_tenant(client)
    try:
        target = await onboard(client, tenant, "HR_ADMIN")
        r = await client.patch(
            f"/v1/users/{target.user_id}/roles", headers=tenant.headers, json={"role_codes": []}
        )
        assert r.status_code == 422, r.text
        listing = await client.get("/v1/users", headers=tenant.headers)
        row = next(x for x in listing.json()["data"] if x["user_id"] == str(target.user_id))
        assert row["role_codes"] == ["HR_ADMIN"]
    finally:
        await teardown(tenant)


async def test_assign_roles_inactive_membership_is_not_found(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    from .uac_helpers import set_sql

    tenant = await register_tenant(client)
    try:
        target = await onboard(client, tenant, "EMPLOYEE")
        await set_sql(
            "UPDATE user_company SET status = 'INACTIVE' WHERE user_id = CAST(:u AS uuid)",
            u=target.user_id,
        )
        r = await client.patch(
            f"/v1/users/{target.user_id}/roles",
            headers=tenant.headers,
            json={"role_codes": ["HR_ADMIN"]},
        )
        assert r.status_code == 404
    finally:
        await teardown(tenant)


async def test_two_admins_cannot_strip_the_company_of_all_admins(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Self-change is blocked, so the last remaining admin can never be demoted by anyone but
    themselves — invariant: at least one COMPANY_ADMIN always survives."""
    tenant = await register_tenant(client)
    try:
        second = await onboard(client, tenant, "COMPANY_ADMIN")
        # Second admin demotes the original admin: allowed (they are a different user).
        r = await client.patch(
            f"/v1/users/{tenant.admin_user_id}/roles",
            headers=second.headers,
            json={"role_codes": ["EMPLOYEE"]},
        )
        assert r.status_code == 200
        # Original admin is now powerless; second admin cannot demote themselves.
        assert (
            await client.patch(
                f"/v1/users/{second.user_id}/roles",
                headers=second.headers,
                json={"role_codes": ["EMPLOYEE"]},
            )
        ).status_code == 409
        assert (await client.get("/v1/users", headers=second.headers)).status_code == 200
        assert (await client.get("/v1/users", headers=tenant.headers)).status_code == 403
    finally:
        await teardown(tenant)


async def test_role_assignment_and_invites_are_audited(
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
        assert r.status_code == 200
        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, str(tenant.company_id))
            rows = (
                (
                    await session.execute(
                        select(AuditLog).where(AuditLog.company_id == tenant.company_id)
                    )
                )
                .scalars()
                .all()
            )
        actions = {row.action for row in rows}
        assert {
            "ACCOUNT_INVITE_ISSUED",
            "ACCOUNT_INVITE_ACCEPTED",
            "USER_ROLES_ASSIGNED",
        } <= actions
        assigned = next(row for row in rows if row.action == "USER_ROLES_ASSIGNED")
        assert assigned.actor_user_id == tenant.admin_user_id
        assert assigned.after_json == {"role_codes": ["HR_ADMIN"]}
    finally:
        await teardown(tenant)


async def test_users_listing_never_leaks_credentials(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    tenant = await register_tenant(client)
    try:
        await onboard(client, tenant, "EMPLOYEE", password=VALID_PASSWORD)
        r = await client.get("/v1/users", headers=tenant.headers)
        blob = r.text.lower()
        for forbidden in ("password", "hash", "argon", "token", "locked_until", "failed_login"):
            assert forbidden not in blob, forbidden
    finally:
        await teardown(tenant)
