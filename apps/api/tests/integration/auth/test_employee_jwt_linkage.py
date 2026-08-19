"""Proves the Phase 2 JWT employee-linkage fix (W1-W4 stabilization task): a real,
login-issued JWT now carries the caller's `employee_id` when one exists, `/auth/me` reflects it,
and SELF DataScope resolution actually works off a *real* token — not just a hand-built one, as
the rest of the RBAC test suite already exercises (`test_employee_data_scope.py`,
`test_rls_runtime_role.py`). Covers the four cases the task named explicitly:

1. Admin login without an `Employee` record still succeeds, with `employee_id: null`.
2. Employee login receives their real `employee_id`.
3. SELF DataScope is enforced correctly starting from a real `/auth/login` token.
4. A broken/missing employee link (soft-deleted `Employee` row) fails safely — `employee_id`
   resolves to `None`, login still succeeds — never a 500, never a stale/wrong id.

Each test self-registers its own company (`_register`/`_cleanup`, same helpers
`test_employee_data_scope.py` and `test_rls_runtime_role.py` already reuse) rather than using the
shared `seeded_db` fixture, so it can freely create/link/soft-delete `Employee` rows without
touching the demo seed data other suites depend on."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from tests.integration.modules.organisation.test_registration_flow import _cleanup, _register

from hrms.core.auth.jwt import decode_access_token
from hrms.core.auth.passwords import hash_password
from hrms.core.db.models.identity import (
    Permission,
    Role,
    RolePermission,
    User,
    UserCompany,
    UserRole,
)
from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.employee.permissions import EMPLOYEE_VIEW_ALL
from hrms.modules.identity.permissions import EMPLOYEE_VIEW

pytestmark = pytest.mark.asyncio

_PASSWORD = "CorrectHorse9!"


async def _create_employee(
    client: AsyncClient, headers: dict[str, str], first_name: str = "Priya"
) -> dict[str, Any]:
    response = await client.post("/v1/employees", headers=headers, json={"first_name": first_name})
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _link_user_to_employee(
    *,
    company_id: UUID,
    employee_id: UUID,
    email: str,
    data_scope: str | None = None,
    permission_codes: tuple[str, ...] = (),
) -> UUID:
    """Creates a fresh, real `User` (with a real password hash) + `UserCompany` membership,
    points `Employee.user_id` at it, and — if `permission_codes` is given — grants a role at
    `data_scope` for each. Mirrors `test_rls_runtime_role.py::_create_scoped_actor`, but links an
    existing `Employee` row (created via the real `POST /v1/employees` endpoint) rather than
    leaving `employee_id` unset, so the resulting login exercises the real employee-linkage path
    end to end."""
    factory = get_session_factory()
    async with factory() as session:
        now = datetime.now(UTC)
        user_id = uuid4()
        session.add(
            User(
                id=user_id,
                email=email,
                password_hash=hash_password(_PASSWORD),
                status="ACTIVE",
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()

        user_company = UserCompany(
            id=uuid4(),
            user_id=user_id,
            company_id=company_id,
            is_primary=True,
            status="ACTIVE",
            created_at=now,
            updated_at=now,
        )
        session.add(user_company)
        await session.flush()

        if permission_codes:
            role_id = uuid4()
            session.add(
                Role(
                    id=role_id,
                    company_id=company_id,
                    code=f"JWT_LINKAGE_TEST_ROLE_{role_id.hex[:8]}",
                    name="JWT linkage test role",
                    is_system=False,
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.flush()
            for code in permission_codes:
                permission = (
                    await session.execute(select(Permission).where(Permission.code == code))
                ).scalar_one()
                session.add(
                    RolePermission(
                        role_id=role_id,
                        permission_id=permission.id,
                        data_scope=data_scope or "COMPANY",
                    )
                )
            await session.flush()
            session.add(UserRole(id=uuid4(), user_company_id=user_company.id, role_id=role_id))

        await session.execute(
            text("UPDATE employee SET user_id = :uid WHERE id = :eid"),
            {"uid": str(user_id), "eid": str(employee_id)},
        )
        await session.commit()
    return user_id


async def _teardown(
    *,
    company_id: UUID | None,
    admin_user_id: UUID | None,
    extra_user_ids: tuple[UUID, ...] = (),
) -> None:
    """`_cleanup` deletes the `company` row itself, which `session`/`refresh_token` rows for any
    extra (non-admin) user still hold a `company_id` FK against — those must be deleted first, and
    the extra `user` rows themselves only after `_cleanup` has removed their `user_company`/
    `user_role` FK references (same ordering `test_rls_runtime_role.py::_teardown` uses)."""
    factory = get_session_factory()
    if company_id is not None:
        async with factory() as session:
            await set_rls_company_id(session, str(company_id))
            await session.execute(
                text("DELETE FROM employee WHERE company_id = :cid"), {"cid": str(company_id)}
            )
            # `POST /v1/employees` (via `_create_employee`) allocates an `employee_code` off a
            # `number_series` row per company — `_cleanup` doesn't know about it (mirrors
            # `test_rls_runtime_role.py::_teardown`'s same extra cleanup).
            await session.execute(
                text("DELETE FROM number_series WHERE company_id = :cid"), {"cid": str(company_id)}
            )
            for uid in extra_user_ids:
                await session.execute(
                    text("DELETE FROM refresh_token WHERE user_id = :uid"), {"uid": str(uid)}
                )
                await session.execute(
                    text("DELETE FROM session WHERE user_id = :uid"), {"uid": str(uid)}
                )
            await session.commit()
    await _cleanup(company_id=company_id, user_id=admin_user_id)
    if extra_user_ids:
        async with factory() as session:
            for uid in extra_user_ids:
                await session.execute(text('DELETE FROM "user" WHERE id = :uid'), {"uid": str(uid)})
            await session.commit()


# --- 1: admin login without an Employee record --------------------------------------------


async def test_admin_login_without_employee_record_returns_null_employee_id(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    response, company_id, user_id = await _register(client)
    try:
        assert response.status_code == 201, response.text
        data = response.json()["data"]

        payload = decode_access_token(data["access_token"])
        assert payload["employee_id"] is None

        me = await client.get(
            "/v1/auth/me",
            headers={
                "Authorization": f"Bearer {data['access_token']}",
                "X-Company-Id": str(company_id),
            },
        )
        assert me.status_code == 200, me.text
        assert me.json()["data"]["user"]["employee_id"] is None
    finally:
        await _teardown(company_id=company_id, admin_user_id=user_id)


# --- 2: employee login receives employee_id ------------------------------------------------


async def test_employee_login_receives_employee_id(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    response, company_id, admin_user_id = await _register(client)
    assert response.status_code == 201, response.text
    admin_token = response.json()["data"]["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}", "X-Company-Id": str(company_id)}
    employee_user_id: UUID | None = None
    try:
        employee = await _create_employee(client, admin_headers, "Asha")
        emp_email = f"emp-{uuid4().hex[:8]}@example.com"
        employee_user_id = await _link_user_to_employee(
            company_id=company_id, employee_id=UUID(employee["id"]), email=emp_email
        )

        login = await client.post(
            "/v1/auth/login",
            json={"email": emp_email, "password": _PASSWORD, "company_id": str(company_id)},
        )
        assert login.status_code == 200, login.text
        token = login.json()["data"]["access_token"]

        payload = decode_access_token(token)
        assert payload["employee_id"] == employee["id"]

        me = await client.get(
            "/v1/auth/me",
            headers={"Authorization": f"Bearer {token}", "X-Company-Id": str(company_id)},
        )
        assert me.status_code == 200, me.text
        assert me.json()["data"]["user"]["employee_id"] == employee["id"]

        # Token refresh must keep resolving the same employee_id, not drop it.
        refresh = await client.post(
            "/v1/auth/token/refresh", json={"refresh_token": login.json()["data"]["refresh_token"]}
        )
        assert refresh.status_code == 200, refresh.text
        refreshed_payload = decode_access_token(refresh.json()["data"]["access_token"])
        assert refreshed_payload["employee_id"] == employee["id"]
    finally:
        extra = (employee_user_id,) if employee_user_id is not None else ()
        await _teardown(company_id=company_id, admin_user_id=admin_user_id, extra_user_ids=extra)


# --- 3: SELF DataScope enforced from a real, login-issued JWT ------------------------------


async def test_self_datascope_enforced_from_real_jwt(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    response, company_id, admin_user_id = await _register(client)
    assert response.status_code == 201, response.text
    admin_token = response.json()["data"]["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}", "X-Company-Id": str(company_id)}
    employee_user_id: UUID | None = None
    try:
        self_employee = await _create_employee(client, admin_headers, "SelfEmployee")
        stranger = await _create_employee(client, admin_headers, "Stranger")

        emp_email = f"self-{uuid4().hex[:8]}@example.com"
        employee_user_id = await _link_user_to_employee(
            company_id=company_id,
            employee_id=UUID(self_employee["id"]),
            email=emp_email,
            data_scope="SELF",
            permission_codes=(EMPLOYEE_VIEW, EMPLOYEE_VIEW_ALL),
        )

        login = await client.post(
            "/v1/auth/login",
            json={"email": emp_email, "password": _PASSWORD, "company_id": str(company_id)},
        )
        assert login.status_code == 200, login.text
        self_headers = {
            "Authorization": f"Bearer {login.json()['data']['access_token']}",
            "X-Company-Id": str(company_id),
        }

        # SELF scope, from the real JWT: sees only their own employee record.
        listing = await client.get("/v1/employees", headers=self_headers)
        assert listing.status_code == 200, listing.text
        ids = {e["id"] for e in listing.json()["data"]}
        assert ids == {self_employee["id"]}

        own = await client.get(f"/v1/employees/{self_employee['id']}", headers=self_headers)
        assert own.status_code == 200

        # A colleague, outside SELF scope, is a 404 — not 403 (doesn't reveal existence).
        blocked = await client.get(f"/v1/employees/{stranger['id']}", headers=self_headers)
        assert blocked.status_code == 404
        assert blocked.json()["error"]["code"] == "NOT_FOUND"
    finally:
        extra = (employee_user_id,) if employee_user_id is not None else ()
        await _teardown(company_id=company_id, admin_user_id=admin_user_id, extra_user_ids=extra)


# --- 4: a broken/missing employee link fails safely -----------------------------------------


async def test_soft_deleted_employee_link_resolves_to_null_employee_id_not_error(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A `User` that *was* linked to an `Employee` whose record has since been soft-deleted must
    not crash login and must not carry the stale employee_id forward — `SELF` DataScope must not
    silently keep granting access to a record that no longer counts as this user's own."""
    response, company_id, admin_user_id = await _register(client)
    assert response.status_code == 201, response.text
    admin_token = response.json()["data"]["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}", "X-Company-Id": str(company_id)}
    employee_user_id: UUID | None = None
    try:
        employee = await _create_employee(client, admin_headers, "SoonDeleted")
        emp_email = f"broken-{uuid4().hex[:8]}@example.com"
        employee_user_id = await _link_user_to_employee(
            company_id=company_id, employee_id=UUID(employee["id"]), email=emp_email
        )

        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                text("UPDATE employee SET deleted_at = now() WHERE id = :eid"),
                {"eid": employee["id"]},
            )
            await session.commit()

        login = await client.post(
            "/v1/auth/login",
            json={"email": emp_email, "password": _PASSWORD, "company_id": str(company_id)},
        )
        assert login.status_code == 200, login.text
        payload = decode_access_token(login.json()["data"]["access_token"])
        assert payload["employee_id"] is None
    finally:
        extra = (employee_user_id,) if employee_user_id is not None else ()
        await _teardown(company_id=company_id, admin_user_id=admin_user_id, extra_user_ids=extra)
