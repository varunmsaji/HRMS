"""Schema checks for the geofencing migration (`20261030090000`): backward-compatible defaults,
bounded values enforced by the database itself, and row-level security switched on and forced."""

import pytest
from sqlalchemy import text

from hrms.core.db.session import get_session_factory

pytestmark = pytest.mark.asyncio


async def _query(sql: str) -> list[tuple]:
    async with get_session_factory()() as session:
        return [tuple(r) for r in await session.execute(text(sql))]


async def test_policy_version_columns_default_to_the_unchanged_behaviour() -> None:
    rows = {
        r[0]: (r[1], r[2])
        for r in await _query(
            "SELECT column_name, column_default, is_nullable FROM information_schema.columns "
            "WHERE table_name = 'attendance_policy_version' AND column_name LIKE 'geofence_%'"
        )
    }
    assert set(rows) == {"geofence_mode", "geofence_max_accuracy_m", "geofence_max_age_seconds"}
    assert "DISABLED" in rows["geofence_mode"][0]
    assert rows["geofence_max_accuracy_m"][0] == "100"
    assert rows["geofence_max_age_seconds"][0] == "60"
    assert all(nullable == "NO" for _, nullable in rows.values())


async def test_database_enforces_the_policy_bounds() -> None:
    defs = " ".join(
        r[0]
        for r in await _query(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'attendance_policy_version'::regclass AND contype = 'c' "
            "AND conname LIKE '%geofence%'"
        )
    )
    assert "DISABLED" in defs and "OPTIONAL" in defs and "REQUIRED" in defs
    assert "geofence_max_accuracy_m >= 5" in defs and "geofence_max_accuracy_m <= 500" in defs
    assert "geofence_max_age_seconds >= 5" in defs and "geofence_max_age_seconds <= 300" in defs


@pytest.mark.parametrize("table", ["employee_workplace_authorization", "geofence_attempt"])
async def test_new_tenant_tables_have_forced_rls_and_a_tenant_policy(table: str) -> None:
    ((enabled, forced),) = await _query(
        f"SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = '{table}'"  # noqa: S608
    )
    assert enabled is True and forced is True
    ((policy,),) = await _query(
        f"SELECT pg_get_expr(polqual, polrelid) FROM pg_policy "  # noqa: S608
        f"WHERE polrelid = '{table}'::regclass"
    )
    assert "company_id" in policy and "app.company_id" in policy


async def test_composite_tenant_foreign_keys_exist() -> None:
    defs = [
        r[0]
        for r in await _query(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE contype = 'f' AND conrelid IN "
            "('employee_workplace_authorization'::regclass, 'geofence_attempt'::regclass)"
        )
    ]
    joined = " | ".join(defs)
    assert "FOREIGN KEY (company_id, employee_id) REFERENCES employee(company_id, id)" in joined
    assert "FOREIGN KEY (company_id, branch_id) REFERENCES branch(company_id, id)" in joined
