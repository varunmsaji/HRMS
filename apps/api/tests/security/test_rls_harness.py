"""Proves the two-role test harness (`tests/rls_support.py`) actually enforces RLS.

Stage 1 of the P1 remediation (docs/blind-audit-2026-10-29/HRMS_P1_VERIFICATION_REPORT.md, V-1).
These tests do not exercise product code. They establish that:

* the application-under-test role is not a superuser, does not bypass RLS and cannot do DDL;
* the privileged role used for fixtures and teardown is a *different*, genuinely privileged role, so
  setup/cleanup never needs the runtime role to be widened;
* a table with the standard `tenant_isolation` policy is filtered by `app.company_id` for the
  runtime role, blocks cross-tenant writes, and shows nothing without a tenant;
* `app_as_runtime_role` really connects the app's own engine as the runtime role and then restores
  the admin role.

The probe table is created and dropped by the admin role inside each test that needs it; the
runtime role is never granted anything beyond the DML it already has by default.
"""

from collections.abc import AsyncIterator
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine
from tests import rls_support

from hrms.core.db.session import get_engine

pytestmark = pytest.mark.asyncio

_PROBE = "zz_rls_harness_probe"


@pytest.fixture
async def probe(admin_engine: AsyncEngine) -> AsyncIterator[None]:
    """A tenant table with the same policy shape as the real ones, owned by the admin role."""
    async with admin_engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE IF EXISTS {_PROBE}"))  # noqa: S608
        await conn.execute(
            text(
                f"CREATE TABLE {_PROBE} (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "  # noqa: S608
                "company_id UUID NOT NULL, note TEXT)"
            )
        )
        await conn.execute(text(f"ALTER TABLE {_PROBE} ENABLE ROW LEVEL SECURITY"))  # noqa: S608
        await conn.execute(text(f"ALTER TABLE {_PROBE} FORCE ROW LEVEL SECURITY"))  # noqa: S608
        await conn.execute(
            text(
                f"CREATE POLICY tenant_isolation ON {_PROBE} "  # noqa: S608
                "USING (company_id = current_setting('app.company_id', true)::uuid) "
                "WITH CHECK (company_id = current_setting('app.company_id', true)::uuid)"
            )
        )
    try:
        yield
    finally:
        async with admin_engine.begin() as conn:
            await conn.execute(text(f"DROP TABLE IF EXISTS {_PROBE}"))  # noqa: S608


async def _set_tenant(conn, company_id: object) -> None:  # type: ignore[no-untyped-def]
    await conn.execute(
        text("SELECT set_config('app.company_id', :c, true)"), {"c": str(company_id)}
    )


# --- the guard ----------------------------------------------------------------------------------


async def test_runtime_role_is_not_superuser_and_does_not_bypass_rls(
    runtime_engine: AsyncEngine,
) -> None:
    async with runtime_engine.connect() as conn:
        attrs = await rls_support.role_attributes(conn)
        await rls_support.assert_role_is_unprivileged(conn)
    assert attrs["rolsuper"] is False
    assert attrs["rolbypassrls"] is False


async def test_admin_role_is_a_different_privileged_role(
    admin_engine: AsyncEngine, runtime_engine: AsyncEngine
) -> None:
    async with admin_engine.connect() as admin, runtime_engine.connect() as runtime:
        admin_attrs = await rls_support.role_attributes(admin)
        runtime_attrs = await rls_support.role_attributes(runtime)
    assert admin_attrs["name"] != runtime_attrs["name"]
    # The guard must reject the admin role, otherwise it guards nothing.
    assert rls_support.unprivileged_problems(admin_attrs), admin_attrs


async def test_runtime_role_cannot_do_ddl_or_truncate(
    runtime_engine: AsyncEngine, admin_engine: AsyncEngine, probe: None
) -> None:
    async with runtime_engine.connect() as conn:
        with pytest.raises(DBAPIError):
            await conn.execute(text("CREATE TABLE zz_rls_harness_should_not_exist (id int)"))
        await conn.rollback()
        can_truncate = (
            await conn.execute(
                text("SELECT has_table_privilege(current_user, :t, 'TRUNCATE')"), {"t": _PROBE}
            )
        ).scalar_one()
        can_create = (
            await conn.execute(
                text("SELECT has_schema_privilege(current_user, 'public', 'CREATE')")
            )
        ).scalar_one()
    assert can_truncate is False
    assert can_create is False


# --- RLS is enforced for the runtime role, and bypassed only by the admin role -----------------


async def test_rls_filters_by_tenant_for_runtime_role_but_not_for_admin(
    admin_engine: AsyncEngine, runtime_engine: AsyncEngine, probe: None
) -> None:
    a, b = uuid4(), uuid4()
    async with admin_engine.begin() as conn:  # privileged setup: no tenant context needed
        await conn.execute(
            text(f"INSERT INTO {_PROBE} (company_id, note) VALUES (:a, 'a'), (:b, 'b')"),  # noqa: S608
            {"a": str(a), "b": str(b)},
        )
        admin_sees = (await conn.execute(text(f"SELECT count(*) FROM {_PROBE}"))).scalar_one()  # noqa: S608
    assert admin_sees == 2  # the admin role bypasses RLS: that is what makes it usable for setup

    async with runtime_engine.begin() as conn:
        await _set_tenant(conn, a)
        rows = (await conn.execute(text(f"SELECT note FROM {_PROBE}"))).scalars().all()  # noqa: S608
    assert rows == ["a"]

    async with runtime_engine.begin() as conn:
        await _set_tenant(conn, b)
        rows = (await conn.execute(text(f"SELECT note FROM {_PROBE}"))).scalars().all()  # noqa: S608
    assert rows == ["b"]


async def test_runtime_role_sees_nothing_without_a_tenant(
    admin_engine: AsyncEngine, runtime_engine: AsyncEngine, probe: None
) -> None:
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(f"INSERT INTO {_PROBE} (company_id, note) VALUES (:a, 'a')"),  # noqa: S608
            {"a": str(uuid4())},
        )
    # Fresh, never-pooled connection: the GUC was never defined, so the policy yields no rows.
    async with runtime_engine.connect() as conn:
        count = (await conn.execute(text(f"SELECT count(*) FROM {_PROBE}"))).scalar_one()  # noqa: S608
    assert count == 0


async def test_runtime_role_cannot_write_across_tenants(
    admin_engine: AsyncEngine, runtime_engine: AsyncEngine, probe: None
) -> None:
    a, b = uuid4(), uuid4()
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(f"INSERT INTO {_PROBE} (company_id, note) VALUES (:b, 'b')"),  # noqa: S608
            {"b": str(b)},
        )

    async with runtime_engine.connect() as conn:  # INSERT into another tenant: WITH CHECK fails
        await _set_tenant(conn, a)
        with pytest.raises(DBAPIError):
            await conn.execute(
                text(f"INSERT INTO {_PROBE} (company_id, note) VALUES (:b, 'x')"),  # noqa: S608
                {"b": str(b)},
            )
        await conn.rollback()

    async with runtime_engine.begin() as conn:  # UPDATE/DELETE of another tenant's row: 0 rows
        await _set_tenant(conn, a)
        updated = await conn.execute(text(f"UPDATE {_PROBE} SET note = 'hacked'"))  # noqa: S608
        deleted = await conn.execute(text(f"DELETE FROM {_PROBE}"))  # noqa: S608
    assert updated.rowcount == 0
    assert deleted.rowcount == 0

    async with admin_engine.connect() as conn:
        notes = (await conn.execute(text(f"SELECT note FROM {_PROBE}"))).scalars().all()  # noqa: S608
    assert notes == ["b"]


# --- the app's own engine ---------------------------------------------------------------


async def test_app_as_runtime_role_connects_as_runtime_then_restores_admin(
    app_as_runtime_role,  # type: ignore[no-untyped-def]
) -> None:
    async with app_as_runtime_role():
        async with get_engine().connect() as conn:
            attrs = await rls_support.role_attributes(conn)
        assert rls_support.unprivileged_problems(attrs) == []
        assert attrs["name"] == urlsplit(rls_support.runtime_url()).username
    async with get_engine().connect() as conn:
        attrs = await rls_support.role_attributes(conn)
    assert attrs["name"] == urlsplit(rls_support.admin_url()).username
