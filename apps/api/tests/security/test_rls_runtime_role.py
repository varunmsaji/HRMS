"""Proves Finding F1's fix (`docs/architecture/POSTGRES_RLS_ROLE_MIGRATION_PLAN.md`):
Postgres Row-Level Security is actually enforced when the application connects as the dedicated
`hrms_app` runtime role — not merely that the app still boots and its own `WHERE company_id`
predicates still work (that was already true before this fix; F1 is that RLS contributed nothing
on top of it).

**Why these tests do not use the module's usual `client` fixture unmodified.** Every other test
file in this suite deliberately keeps running against `hrms` (the schema-owner role, which is also
`SUPERUSER`+`BYPASSRLS`) — dozens of files across `tests/integration/` do raw, cross-tenant
`DELETE`/`INSERT` fixture setup/teardown via `get_session_factory()` with no RLS GUC ever set, which
only works because `hrms` bypasses RLS entirely. Switching the *default* test role would silently
break all of that (see the migration plan §6/§13 for why that refactor is explicitly out of this
task's scope). Instead, each test here temporarily repoints the app's global engine at `hrms_app`
for the duration of the test (`_as_runtime_role`), then restores `hrms` before any raw cleanup runs.

Covers, per the migration plan's Phase 3 checklist:
A/B — runtime role is not SUPERUSER, not BYPASSRLS.
C/D/E/F — cross-tenant SELECT/INSERT/UPDATE/DELETE blocked, proven twice: once through the real
          app's HTTP surface, once via a raw connection that bypasses the app's own `WHERE
          company_id` predicates entirely (proving the *database*, not just app code, blocks it).
G/K/L/M/N — same-tenant registration, Employee CRUD (identity, employment, compensation, statutory,
          banking), termination, and audit logging still work end-to-end under the restricted role.
H/I/J — RBAC SELF/REPORTEES scope resolution still works under the restricted role.
O/P — N/A: the only existing background task (`health.ping`) touches no database at all; there is
      nothing to verify. Documented, not silently assumed.
Q — test fixtures: addressed by design (`_as_runtime_role` restores `hrms` before any raw
    fixture/cleanup call runs; no existing fixture file is modified).
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine
from tests.integration.modules.organisation.test_registration_flow import _cleanup, _register

from hrms.core.auth.jwt import create_access_token
from hrms.core.auth.passwords import hash_password
from hrms.core.config.settings import get_settings
from hrms.core.db.models.identity import (
    Permission,
    Role,
    RolePermission,
    Session,
    User,
    UserCompany,
    UserRole,
)
from hrms.core.db.session import dispose_engine, get_session_factory
from hrms.modules.employee.models import EmployeeAssignment, Employment
from hrms.modules.employee.permissions import EMPLOYEE_VIEW_ALL
from hrms.modules.identity.permissions import EMPLOYEE_VIEW
from hrms.modules.organisation.models import LegalEntity

pytestmark = pytest.mark.asyncio

ADMIN_ROLE_URL = "postgresql://hrms:hrms_dev_password@localhost:5433/hrms_dev"
RUNTIME_ROLE_URL = "postgresql://hrms_app:hrms_app_dev_password@localhost:5433/hrms_dev"
# `Settings.ensure_asyncpg_driver` rewrites the plain `postgresql://` scheme above to
# `+asyncpg` when it flows through `DATABASE_URL`/pydantic — raw `create_async_engine()` calls in
# this file (which never go through `Settings`) need the driver spelled out themselves.
RUNTIME_ROLE_ASYNC_URL = RUNTIME_ROLE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)


@asynccontextmanager
async def _as_runtime_role(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[None]:
    """Repoints the app's global engine at `hrms_app` for the block, then restores `hrms` before
    returning — so any raw cleanup/fixture call made after this context manager exits (including
    the caller's own `_cleanup(...)`) keeps running against the unrestricted admin role, exactly as
    every other test file in this suite already assumes."""
    monkeypatch.setenv("DATABASE_URL", RUNTIME_ROLE_URL)
    get_settings.cache_clear()
    await dispose_engine()
    try:
        yield
    finally:
        monkeypatch.setenv("DATABASE_URL", ADMIN_ROLE_URL)
        get_settings.cache_clear()
        await dispose_engine()


async def _register_tenant(
    client: AsyncClient, **overrides: Any
) -> tuple[dict[str, str], UUID, UUID | None]:
    response, company_id, user_id = await _register(client, **overrides)
    assert response.status_code == 201, response.text
    assert company_id is not None
    data = response.json()["data"]
    return (
        {
            "Authorization": f"Bearer {data['access_token']}",
            "X-Company-Id": str(company_id),
        },
        company_id,
        user_id,
    )


async def _create_employee(
    client: AsyncClient, headers: dict[str, str], first_name: str = "Asha"
) -> dict[str, Any]:
    response = await client.post("/v1/employees", headers=headers, json={"first_name": first_name})
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _teardown(*, company_id: UUID | None, user_id: UUID | None) -> None:
    """Full FK-safe teardown for everything this module's tests create beyond what
    `_cleanup` (organisation-level: company/role/user/legal_entity/...) already handles —
    mirrors `test_employee_banking.py::_teardown`'s ordering (sub-resources -> employment ->
    employee -> number_series) with compensation/statutory added. Must run against the admin
    (`hrms`) role — the caller is responsible for calling this only after `_as_runtime_role`'s
    block has exited."""
    if company_id is not None:
        factory = get_session_factory()
        async with factory() as session:
            for table in (
                "employee_bank",
                "employee_statutory",
                "employee_compensation",
                "employee_assignment",
                "employment",
            ):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE company_id = :cid"),  # noqa: S608
                    {"cid": str(company_id)},
                )
            await session.execute(
                text("DELETE FROM employee WHERE company_id = :cid"), {"cid": str(company_id)}
            )
            await session.execute(
                text("DELETE FROM number_series WHERE company_id = :cid"),
                {"cid": str(company_id)},
            )
            await session.commit()
    await _cleanup(company_id=company_id, user_id=user_id)


# --- A/B: role attributes -----------------------------------------------------------------


async def test_runtime_role_is_not_superuser_or_bypassrls() -> None:
    engine = create_async_engine(RUNTIME_ROLE_ASYNC_URL)
    try:
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT current_user, "
                        "(SELECT rolsuper FROM pg_roles WHERE rolname = current_user) AS is_super, "
                        "(SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user) "
                        "AS bypass_rls"
                    )
                )
            ).one()
            assert row.current_user == "hrms_app"
            assert row.is_super is False
            assert row.bypass_rls is False
    finally:
        await engine.dispose()


# --- C-N: full lifecycle + cross-tenant proof under the runtime role -----------------------


async def test_cross_tenant_isolation_and_full_lifecycle_under_runtime_role(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    seeded_plan_catalogue: None,
) -> None:
    company_a: UUID | None = None
    company_b: UUID | None = None
    user_a: UUID | None = None
    user_b: UUID | None = None
    try:
        async with _as_runtime_role(monkeypatch):
            # --- G/K: registration works end-to-end (company, admin user, RBAC role/permission
            # seeding, JWT issuance) while the app is connected as hrms_app. ---
            headers_a, company_a, user_a = await _register_tenant(client)
            headers_b, company_b, user_b = await _register_tenant(client)

            # --- L: Employee CRUD (identity) ---
            employee_a = await _create_employee(client, headers_a, "Priya")

            # --- C: cross-tenant read blocked through the real application ---
            r = await client.get(f"/v1/employees/{employee_a['id']}", headers=headers_b)
            assert r.status_code == 404
            r = await client.get("/v1/employees", headers=headers_b)
            assert r.status_code == 200
            assert all(e["id"] != employee_a["id"] for e in r.json()["data"])

            # --- G: same-tenant read still works ---
            r = await client.get(f"/v1/employees/{employee_a['id']}", headers=headers_a)
            assert r.status_code == 200

            # --- L: Employment ---
            legal_entity_resp = await client.post(
                "/v1/legal-entities", headers=headers_a, json={"name": "Runtime Role LE"}
            )
            assert legal_entity_resp.status_code == 201, legal_entity_resp.text
            legal_entity_id = legal_entity_resp.json()["data"]["id"]

            employment_resp = await client.post(
                f"/v1/employees/{employee_a['id']}/employments",
                headers=headers_a,
                json={"legal_entity_id": legal_entity_id, "joining_date": "2027-01-01"},
            )
            assert employment_resp.status_code == 201, employment_resp.text
            employment = employment_resp.json()["data"]

            # --- L: Compensation ---
            comp_resp = await client.post(
                f"/v1/employees/{employee_a['id']}/compensation",
                headers=headers_a,
                json={
                    "effective_from": "2027-01-01",
                    "annual_ctc_minor": 120000000,
                    "currency": "INR",
                    "revision_type": "JOINING",
                    "revision_reason": "Joining CTC",
                },
            )
            assert comp_resp.status_code == 201, comp_resp.text

            # --- L: Statutory ---
            stat_resp = await client.post(
                f"/v1/employees/{employee_a['id']}/statutory",
                headers=headers_a,
                json={
                    "effective_from": "2027-01-01",
                    "is_pf_applicable": True,
                    "is_esi_applicable": False,
                    "is_lwf_applicable": False,
                    "tax_regime": "NEW",
                    "is_director": False,
                    "is_international_worker": False,
                    "revision_reason": "Joining statutory setup",
                },
            )
            assert stat_resp.status_code == 201, stat_resp.text

            # --- L: Banking ---
            bank_resp = await client.post(
                f"/v1/employees/{employee_a['id']}/bank",
                headers=headers_a,
                json={
                    "effective_from": "2027-01-01",
                    "account_holder_name": "Priya",
                    "bank_name": "Test Bank",
                    "payment_mode": "BANK",
                },
            )
            assert bank_resp.status_code == 201, bank_resp.text

            # Cross-tenant probes for the three RESTRICTED sub-resources too — F2/F3's own scope
            # gap is out of this task's scope, but plain cross-*company* isolation on these routes
            # must hold regardless, exactly as it already did before this role change.
            for path in ("compensation", "statutory", "bank"):
                r = await client.get(f"/v1/employees/{employee_a['id']}/{path}", headers=headers_b)
                assert r.status_code == 404, f"{path} leaked across tenants: {r.text}"

            # --- M: termination lifecycle ---
            term_resp = await client.post(
                f"/v1/employees/{employee_a['id']}/employments/{employment['id']}/terminate",
                headers={**headers_a, "If-Match": str(employment["version"])},
                json={"last_working_day": "2027-06-30"},
            )
            assert term_resp.status_code == 200, term_resp.text
            assert term_resp.json()["data"]["status"] == "TERMINATED"

        # --- D/E/F: raw, app-bypassing proof that Postgres itself — not app code — blocks
        # cross-tenant writes. Runs in a standalone engine, independent of the app's own global
        # engine (already restored to `hrms` by `_as_runtime_role`'s __aexit__ at this point). ---
        raw_engine = create_async_engine(RUNTIME_ROLE_ASYNC_URL)
        try:
            async with raw_engine.connect() as conn:
                await conn.execute(
                    text("SELECT set_config('app.company_id', :cid, false)"),
                    {"cid": str(company_b)},
                )

                # D: direct SELECT of Company A's row while scoped to Company B — must be invisible.
                result = await conn.execute(
                    text("SELECT id FROM employee WHERE id = :id"),
                    {"id": employee_a["id"]},
                )
                assert result.first() is None

                # E: direct UPDATE must affect zero rows.
                result = await conn.execute(
                    text("UPDATE employee SET first_name = 'HACKED' WHERE id = :id"),
                    {"id": employee_a["id"]},
                )
                assert result.rowcount == 0

                # F: direct DELETE must affect zero rows.
                result = await conn.execute(
                    text("DELETE FROM employee WHERE id = :id"),
                    {"id": employee_a["id"]},
                )
                assert result.rowcount == 0

                # C (insert direction): a forged row claiming Company A while the session is
                # scoped to Company B must be rejected outright by the policy's WITH CHECK, not
                # merely filtered on read.
                with pytest.raises(DBAPIError, match="row-level security"):
                    await conn.execute(
                        text(
                            "INSERT INTO employee "
                            "(id, company_id, employee_code, first_name, status, "
                            "created_at, updated_at) "
                            "VALUES (gen_random_uuid(), :cid, 'FORGED-001', 'Forged', "
                            "'ACTIVE', now(), now())"
                        ),
                        {"cid": str(company_a)},
                    )
                await conn.rollback()
        finally:
            await raw_engine.dispose()

        # --- Confirm Company A's row survived the raw attack attempt untouched ---
        factory = get_session_factory()
        async with factory() as session:
            row = (
                await session.execute(
                    text("SELECT first_name FROM employee WHERE id = :id"),
                    {"id": employee_a["id"]},
                )
            ).one()
            assert row.first_name == "Priya"

            # --- N: audit logging still works under the runtime role ---
            audit_count = (
                await session.execute(
                    text(
                        "SELECT count(*) FROM audit_log "
                        "WHERE company_id = :cid AND entity_id = :eid"
                    ),
                    {"cid": str(company_a), "eid": employee_a["id"]},
                )
            ).scalar_one()
            assert audit_count > 0, "expected at least the EMPLOYEE_CREATED audit row"
    finally:
        # Runs against the admin role — `_as_runtime_role` already restored it on the way out of
        # the `async with` block above, or (if an assertion failed inside it) its own `finally`
        # still ran because it's a context manager, so this is always safe.
        await _teardown(company_id=company_a, user_id=user_a)
        await _teardown(company_id=company_b, user_id=user_b)


# --- H/I/J: RBAC SELF/REPORTEES scope resolution under the runtime role --------------------


async def _create_scoped_actor(
    *, company_id: UUID, data_scope: str, employee_id: UUID | None
) -> dict[str, str]:
    """Mirrors `test_employee_data_scope.py::_create_scoped_actor` but, unlike that helper,
    explicitly sets the RLS GUC before inserting — required because this file runs its setup
    while the app's global engine (and therefore `get_session_factory()`, which this helper also
    uses) is pointed at the restricted `hrms_app` role, which has no BYPASSRLS to fall back on.
    `set_config(..., false)` (session-scoped, not `SET LOCAL`) so it holds across every flush in
    this one `async with` block."""
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("SELECT set_config('app.company_id', :cid, false)"), {"cid": str(company_id)}
        )
        now = datetime.now(UTC)
        user_id = uuid4()
        session.add(
            User(
                id=user_id,
                email=f"scoped-actor-{user_id.hex[:8]}@example.com",
                password_hash=hash_password("CorrectHorse9"),
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

        role_id = uuid4()
        session.add(
            Role(
                id=role_id,
                company_id=company_id,
                code=f"RLS_TEST_SCOPED_ROLE_{role_id.hex[:8]}",
                name="RLS test scoped role",
                is_system=False,
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        # `GET /v1/employees` (list) checks `EMPLOYEE_VIEW_ALL`; `GET /v1/employees/{id}` checks
        # `EMPLOYEE_VIEW` — both are granted at the same scope, matching
        # `test_employee_data_scope.py`'s own pattern for exercising both routes.
        for code in (EMPLOYEE_VIEW, EMPLOYEE_VIEW_ALL):
            permission = (
                await session.execute(select(Permission).where(Permission.code == code))
            ).scalar_one()
            session.add(
                RolePermission(role_id=role_id, permission_id=permission.id, data_scope=data_scope)
            )
        await session.flush()
        session.add(UserRole(id=uuid4(), user_company_id=user_company.id, role_id=role_id))

        session_id = uuid4()
        session.add(
            Session(
                id=session_id,
                user_id=user_id,
                company_id=company_id,
                expires_at=now + timedelta(days=1),
            )
        )
        await session.commit()

    token = create_access_token(
        user_id=user_id, company_id=company_id, session_id=session_id, employee_id=employee_id
    )
    return {"Authorization": f"Bearer {token}", "X-Company-Id": str(company_id)}


async def test_rbac_self_and_reportees_scope_enforced_under_runtime_role(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    seeded_plan_catalogue: None,
) -> None:
    company_id: UUID | None = None
    admin_user_id: UUID | None = None
    try:
        async with _as_runtime_role(monkeypatch):
            admin_headers, company_id, admin_user_id = await _register_tenant(client)

            manager = await _create_employee(client, admin_headers, "Manager")
            reportee = await _create_employee(client, admin_headers, "Reportee")
            stranger = await _create_employee(client, admin_headers, "Stranger")

            # Minimal legal_entity + employment rows so the assignment write below has a covering
            # active episode (`NoActiveEmploymentError` otherwise) — same minimal-fixture pattern
            # `test_employee_data_scope.py::_setup_active_employment` uses, but done here with the
            # RLS GUC explicitly set first, for the same reason as `_create_scoped_actor` above.
            factory = get_session_factory()
            async with factory() as session:
                await session.execute(
                    text("SELECT set_config('app.company_id', :cid, false)"),
                    {"cid": str(company_id)},
                )
                now = datetime.now(UTC)
                legal_entity_id = uuid4()
                session.add(
                    LegalEntity(
                        id=legal_entity_id,
                        company_id=company_id,
                        name="RBAC Scope Test LE",
                        created_at=now,
                        updated_at=now,
                    )
                )
                await session.flush()
                for emp in (manager, reportee, stranger):
                    session.add(
                        Employment(
                            id=uuid4(),
                            company_id=company_id,
                            employee_id=UUID(emp["id"]),
                            legal_entity_id=legal_entity_id,
                            joining_date=date(2027, 1, 1),
                            status="ACTIVE",
                            created_at=now,
                            updated_at=now,
                        )
                    )
                session.add(
                    EmployeeAssignment(
                        id=uuid4(),
                        company_id=company_id,
                        employee_id=UUID(reportee["id"]),
                        reporting_manager_id=UUID(manager["id"]),
                        effective_from=date(2027, 1, 1),
                        effective_to=None,
                        created_at=now,
                        updated_at=now,
                    )
                )
                await session.commit()

            # --- I: SELF scope — sees only the caller's own employee record ---
            self_headers = await _create_scoped_actor(
                company_id=company_id, data_scope="SELF", employee_id=UUID(reportee["id"])
            )
            r = await client.get("/v1/employees", headers=self_headers)
            assert r.status_code == 200
            ids = {e["id"] for e in r.json()["data"]}
            assert ids == {reportee["id"]}

            r = await client.get(f"/v1/employees/{manager['id']}", headers=self_headers)
            assert r.status_code == 404

            # --- H/J: REPORTEES scope — sees direct reportees, not the whole company ---
            reportees_headers = await _create_scoped_actor(
                company_id=company_id, data_scope="REPORTEES", employee_id=UUID(manager["id"])
            )
            r = await client.get("/v1/employees", headers=reportees_headers)
            assert r.status_code == 200
            ids = {e["id"] for e in r.json()["data"]}
            assert reportee["id"] in ids
            assert stranger["id"] not in ids
    finally:
        await _teardown(company_id=company_id, user_id=admin_user_id)
        if company_id is not None:
            factory = get_session_factory()
            async with factory() as session:
                await session.execute(
                    text(
                        "DELETE FROM session WHERE user_id IN "
                        "(SELECT id FROM \"user\" WHERE email LIKE 'scoped-actor-%')"
                    )
                )
                await session.execute(
                    text(
                        "DELETE FROM \"user\" WHERE email LIKE 'scoped-actor-%' "
                        "AND id NOT IN (SELECT user_id FROM user_company)"
                    )
                )
                await session.commit()
