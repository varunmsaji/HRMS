"""Stage 3 of the P1 remediation: tenant resolution and authentication under the runtime role.

Everything under test runs inside `app_as_runtime_role()` (the app's engine connected as
`hrms_app`, RLS enforced, role attributes asserted by `tests/rls_support.py`); registration, the
extra membership row and cleanup use the admin engine outside the block.

Contract being verified (docs/api/API_OVERVIEW.md, `core/auth/dependencies.py`,
`core/tenancy/dependencies.py`):
* the signed token alone selects the tenant; `X-Company-Id` is optional;
* when sent, the header must equal the token's company, otherwise `404 NOT_FOUND`;
* the token's company claim is verified against a real, ACTIVE membership;
* a multi-company user's tenant is chosen at login (`company_id` in the body, else primary) and is
  fixed in that token - no endpoint selects a tenant by header, so there is no endpoint that
  "requires" a header either; the explicit-selection point is login, tested below.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from tests.integration.modules.attendance.test_attendance_day import _cleanup_attendance_day
from tests.integration.modules.organisation.test_registration_flow import (
    VALID_PASSWORD,
    _cleanup,
    _register,
)

from hrms.core.auth.jwt import create_access_token
from hrms.core.config.settings import get_settings
from hrms.core.db.session import get_session_factory

pytestmark = pytest.mark.asyncio

EMPLOYEES = "/v1/employees"
ME = "/v1/auth/me"


@dataclass
class Tenant:
    company_id: UUID
    user_id: UUID
    email: str
    token: str
    employee_id: str

    @property
    def bearer(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def with_header(self, company_id: object) -> dict[str, str]:
        return {**self.bearer, "X-Company-Id": str(company_id)}


async def _provision(client: AsyncClient, label: str) -> Tenant:
    email = f"{label}-{uuid4().hex[:10]}@tenant-test.example"
    response, company_id, user_id = await _register(client, admin_email=email)
    assert response.status_code == 201, response.text
    assert company_id is not None and user_id is not None
    token = response.json()["data"]["access_token"]
    created = await client.post(
        EMPLOYEES,
        headers={"Authorization": f"Bearer {token}", "X-Company-Id": str(company_id)},
        json={"first_name": label},
    )
    assert created.status_code == 201, created.text
    return Tenant(company_id, user_id, email, token, created.json()["data"]["id"])


async def _teardown(*tenants: Tenant) -> None:
    # Reverse order: a later tenant may hold extra memberships of an earlier tenant's user.
    for tenant in reversed(tenants):
        await _cleanup_attendance_day(company_id=tenant.company_id)
        # A login for this company by *another* tenant's user leaves tokens `_cleanup` (which only
        # removes the owning user's) does not know about.
        async with get_session_factory()() as session:
            for table in ("refresh_token", "session"):
                await session.execute(
                    text(f'DELETE FROM "{table}" WHERE company_id = :c'),  # noqa: S608
                    {"c": str(tenant.company_id)},
                )
            # Rows an unauthenticated flow (password reset) leaves for the owning user / address.
            await session.execute(
                text("DELETE FROM password_reset_token WHERE user_id = :u"),
                {"u": str(tenant.user_id)},
            )
            # `email_log` is append-only by design (trigger) and has no FK to tenant data, so the
            # rows the flow writes for this address stay; the outbox is ordinary state.
            await session.execute(
                text("DELETE FROM email_outbox WHERE recipient = :r"), {"r": tenant.email}
            )
            await session.commit()
        await _cleanup(company_id=tenant.company_id, user_id=tenant.user_id)


@pytest.fixture
async def world(
    client: AsyncClient, seeded_plan_catalogue: None
) -> AsyncIterator[tuple[Tenant, Tenant]]:
    """Two tenants, each with one employee, provisioned on the admin engine. Teardown is in
    `finally`, on the admin engine, after the runtime block has exited."""
    created: list[Tenant] = []
    try:
        created.append(await _provision(client, "alpha"))
        created.append(await _provision(client, "bravo"))
        yield created[0], created[1]
    finally:
        await _teardown(*created)


def _ids(payload: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key == "id" and isinstance(value, str):
                found.add(value)
            found |= _ids(value)
    elif isinstance(payload, list):
        for item in payload:
            found |= _ids(item)
    return found


# --- token-only and header handling --------------------------------------------------------------


async def test_token_only_request_is_served_for_the_token_tenant(
    client: AsyncClient, world: tuple[Tenant, Tenant], app_as_runtime_role: Any
) -> None:
    a, b = world
    async with app_as_runtime_role():
        listed = await client.get(EMPLOYEES, headers=a.bearer)
        assert listed.status_code == 200, listed.text
        assert a.employee_id in _ids(listed.json())
        assert b.employee_id not in _ids(listed.json())
        me = await client.get(ME, headers=a.bearer)
        assert me.status_code == 200, me.text
        assert me.json()["data"]["user"]["company_id"] == str(a.company_id)


async def test_matching_header_is_accepted(
    client: AsyncClient, world: tuple[Tenant, Tenant], app_as_runtime_role: Any
) -> None:
    a, _ = world
    async with app_as_runtime_role():
        listed = await client.get(EMPLOYEES, headers=a.with_header(a.company_id))
        assert listed.status_code == 200, listed.text
        assert a.employee_id in _ids(listed.json())


@pytest.mark.parametrize("form", ["upper", "mixed", "no_hyphens", "braced"])
async def test_the_same_company_in_another_textual_form_is_accepted(
    client: AsyncClient, world: tuple[Tenant, Tenant], app_as_runtime_role: Any, form: str
) -> None:
    """The header is compared as a UUID value, not as text."""
    a, b = world
    text_form = str(a.company_id)
    value = {
        "upper": text_form.upper(),
        "mixed": text_form[:18].upper() + text_form[18:],
        "no_hyphens": a.company_id.hex,
        "braced": "{" + text_form + "}",
    }[form]
    async with app_as_runtime_role():
        for path in (EMPLOYEES, ME):
            response = await client.get(path, headers=a.with_header(value))
            assert response.status_code == 200, (path, response.text)
        listed = await client.get(EMPLOYEES, headers=a.with_header(value))
        assert a.employee_id in _ids(listed.json())
        assert b.employee_id not in _ids(listed.json())


@pytest.mark.parametrize(
    "kind",
    [
        "other_tenant",
        "other_tenant_upper",
        "unknown_uuid",
        "malformed",
        "empty",
        "blank",
        "too_long",
        "non_hex",
    ],
)
async def test_header_naming_another_company_is_a_404_and_exposes_nothing(
    client: AsyncClient, world: tuple[Tenant, Tenant], app_as_runtime_role: Any, kind: str
) -> None:
    a, b = world
    value = {
        "other_tenant": b.company_id,
        "other_tenant_upper": str(b.company_id).upper(),
        "unknown_uuid": uuid4(),
        "malformed": "not-a-uuid",
        "empty": "",
        "blank": " ",
        "too_long": f"{a.company_id}0",
        "non_hex": "g" * 36,
    }[kind]
    async with app_as_runtime_role():
        for path in (EMPLOYEES, ME):
            response = await client.get(path, headers=a.with_header(value))
            assert response.status_code == 404, (path, response.text)
            assert response.json()["error"]["code"] == "NOT_FOUND"
            assert b.employee_id not in response.text and a.employee_id not in response.text


async def test_a_spoofed_header_on_an_unauthenticated_route_never_attributes_email_to_it(
    client: AsyncClient,
    world: tuple[Tenant, Tenant],
    admin_engine: AsyncEngine,
    app_as_runtime_role: Any,
) -> None:
    """`email_log.company_id` used to come from the raw header (P1 verification V-4c)."""
    a, b = world
    async with app_as_runtime_role():
        response = await client.post(
            "/v1/auth/password/forgot",
            json={"email": a.email},
            headers={"X-Company-Id": str(b.company_id)},
        )
        assert response.status_code in {200, 202, 204}, response.text
    async with admin_engine.connect() as conn:
        rows = (
            await conn.execute(
                text("SELECT company_id FROM email_log WHERE recipient = :r"), {"r": a.email}
            )
        ).all()
    assert rows, "the unauthenticated flow was expected to write an email_log row"
    assert all(r.company_id != b.company_id for r in rows), rows


# --- invalid / expired credentials, forged claims ------------


async def test_missing_garbage_and_expired_credentials_are_401(
    client: AsyncClient, world: tuple[Tenant, Tenant], app_as_runtime_role: Any
) -> None:
    a, _ = world
    claims = jwt.decode(a.token, options={"verify_signature": False})
    expired = create_access_token(
        user_id=a.user_id,
        company_id=a.company_id,
        session_id=UUID(claims["session_id"]),
        employee_id=None,
        ttl_minutes=-5,
    )
    async with app_as_runtime_role():
        for headers in (
            {},
            {"X-Company-Id": str(a.company_id)},
            {"Authorization": "Bearer garbage"},
            {"Authorization": f"Bearer {expired}"},
            {"Authorization": f"Bearer {expired}", "X-Company-Id": str(a.company_id)},
        ):
            response = await client.get(EMPLOYEES, headers=headers)
            assert response.status_code == 401, (headers, response.text)
            assert a.employee_id not in response.text


async def test_a_validly_signed_token_claiming_a_company_without_membership_is_rejected(
    client: AsyncClient, world: tuple[Tenant, Tenant], app_as_runtime_role: Any
) -> None:
    """The claim only selects the RLS context; it is still checked against `user_company`."""
    a, b = world
    claims = jwt.decode(a.token, options={"verify_signature": False})
    forged = create_access_token(
        user_id=a.user_id,
        company_id=b.company_id,  # A's user and session, B's company
        session_id=UUID(claims["session_id"]),
        employee_id=None,
    )
    async with app_as_runtime_role():
        for headers in (
            {"Authorization": f"Bearer {forged}"},
            {"Authorization": f"Bearer {forged}", "X-Company-Id": str(b.company_id)},
        ):
            response = await client.get(EMPLOYEES, headers=headers)
            assert response.status_code == 401, response.text
            assert b.employee_id not in response.text


# --- multi-company user ---------------------------------------------------------------------------


async def test_multi_company_user_tenant_is_fixed_by_the_login_selection(
    client: AsyncClient,
    world: tuple[Tenant, Tenant],
    admin_engine: AsyncEngine,
    app_as_runtime_role: Any,
) -> None:
    a, b = world
    async with admin_engine.begin() as conn:  # privileged setup: second membership for A's user
        await conn.execute(
            text(
                "INSERT INTO user_company (id, company_id, user_id, is_primary, status, "
                "created_at, updated_at) VALUES (:i, :c, :u, false, 'ACTIVE', now(), now())"
            ),
            {"i": str(uuid4()), "c": str(b.company_id), "u": str(a.user_id)},
        )
        await conn.execute(  # login requires a verified address; registration leaves it pending
            text('UPDATE "user" SET email_verified_at = now() WHERE id = :u'),
            {"u": str(a.user_id)},
        )
    login = "/v1/auth/login"
    async with app_as_runtime_role():
        # No company selected: the primary membership wins, and it is the token's tenant.
        default = await client.post(login, json={"email": a.email, "password": VALID_PASSWORD})
        assert default.status_code == 200, default.text
        default_token = default.json()["data"]["access_token"]
        me = await client.get(ME, headers={"Authorization": f"Bearer {default_token}"})
        assert me.json()["data"]["user"]["company_id"] == str(a.company_id)

        # Explicit selection of the second company yields a token bound to that company only.
        chosen = await client.post(
            login,
            json={"email": a.email, "password": VALID_PASSWORD, "company_id": str(b.company_id)},
        )
        assert chosen.status_code == 200, chosen.text
        b_headers = {"Authorization": f"Bearer {chosen.json()['data']['access_token']}"}
        me_b = await client.get(ME, headers=b_headers)
        assert me_b.status_code == 200, me_b.text
        assert me_b.json()["data"]["user"]["company_id"] == str(b.company_id)
        # That token cannot be redirected to the other membership with a header, and it does not
        # surface the first company's data.
        redirected = await client.get(ME, headers={**b_headers, "X-Company-Id": str(a.company_id)})
        assert redirected.status_code == 404, redirected.text
        data = await client.get(EMPLOYEES, headers=b_headers)
        assert a.employee_id not in data.text

        # Selecting a company the user does not belong to is refused like a bad password.
        refused = await client.post(
            login, json={"email": a.email, "password": VALID_PASSWORD, "company_id": str(uuid4())}
        )
        assert refused.status_code == 401, refused.text


# --- cross-tenant access after resolution, and pooled connections -----------------


async def test_cross_tenant_read_and_write_after_resolution(
    client: AsyncClient,
    world: tuple[Tenant, Tenant],
    admin_engine: AsyncEngine,
    app_as_runtime_role: Any,
) -> None:
    a, b = world

    async def snapshot() -> list[Any]:
        async with admin_engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT id, first_name, version, updated_at FROM employee WHERE company_id = :c"
                ),
                {"c": str(b.company_id)},
            )
            return [tuple(r) for r in rows]

    before = await snapshot()
    async with app_as_runtime_role():
        read = await client.get(f"{EMPLOYEES}/{b.employee_id}", headers=a.bearer)
        assert read.status_code == 404, read.text
        write = await client.patch(
            f"{EMPLOYEES}/{b.employee_id}",
            headers={**a.bearer, "If-Match": "1"},
            json={"first_name": "hijacked"},
        )
        assert write.status_code in {403, 404, 412, 422, 428}, write.text
        assert "hijacked" not in write.text
    assert await snapshot() == before


async def test_alternating_tenants_over_pooled_connections_never_leak_context(
    client: AsyncClient, world: tuple[Tenant, Tenant], app_as_runtime_role: Any
) -> None:
    a, b = world
    async with app_as_runtime_role():
        for i in range(14):  # more requests than the pool has connections: reuse is certain
            own, other = (a, b) if i % 2 == 0 else (b, a)
            headers = own.bearer if i % 3 else own.with_header(own.company_id)
            listed = await client.get(EMPLOYEES, headers=headers)
            assert listed.status_code == 200, (i, listed.text)
            assert own.employee_id in _ids(listed.json())
            assert other.employee_id not in _ids(listed.json())
        # A header-less, token-less request after tenant traffic still sees nothing.
        anonymous = await client.get(EMPLOYEES)
        assert anonymous.status_code == 401
        assert a.employee_id not in anonymous.text and b.employee_id not in anonymous.text


# --- sanity: the signed claim is what the app trusts ------------


async def test_tokens_in_this_module_are_signed_with_the_app_secret(
    world: tuple[Tenant, Tenant],
) -> None:
    a, _ = world
    claims = jwt.decode(a.token, get_settings().jwt_access_secret, algorithms=["HS256"])
    assert claims["company_id"] == str(a.company_id)
    assert datetime.fromtimestamp(claims["exp"], UTC) > datetime.now(UTC)
