"""Stage 11 (F-01 / F-10 backstop) - migration `20261031090000`: the DATABASE refuses a roster row
or a regularization request that points at a shift of another company.

Isolation from the service layer: every write here is a raw SQL statement, so the Stage 9
`_ensure_shift_in_company` check is never involved - only the composite foreign keys can reject it.
Each scenario runs twice, as the owner role (RLS bypassed, so the constraint alone must hold) and
as `hrms_app` with the tenant variable set (RLS enforced, the role the application really uses).
Cases R1-R9 follow docs/blind-audit-2026-10-29/HRMS_STAGE10_SHIFT_COMPOSITE_FK_DESIGN.md section 4.
Setup and teardown use the admin engine; teardown is `wipe_tenant`, limited to the tenants created
here."""

# ruff: noqa: E501 - long SQL strings

from datetime import date
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
from tests.integration.modules.attendance.test_roster_regularization_rls_runtime_role import (
    Tenant,
    _provision,
    tenants,  # noqa: F401 - fixture
)
from tests.integration.tenant_wipe import wipe_tenant

pytestmark = pytest.mark.asyncio

ROSTER_FK = "shift_roster_company_shift_fkey"
REG_FK = "attendance_regularization_request_company_shift_fkey"
ROLES = ["owner", "runtime"]


@pytest.fixture(params=ROLES)
def role_engine(
    request: pytest.FixtureRequest, admin_engine: AsyncEngine, runtime_engine: AsyncEngine
) -> tuple[str, AsyncEngine]:
    return request.param, admin_engine if request.param == "owner" else runtime_engine


async def _open(engine: AsyncEngine, role: str, tenant: Tenant) -> AsyncConnection:
    conn = await engine.connect()
    await conn.begin()
    if role == "runtime":  # RLS on: scope the transaction to the tenant, as the app does
        await conn.execute(
            text("SELECT set_config('app.company_id', :c, true)"), {"c": str(tenant.company_id)}
        )
    return conn


def _constraint(exc: BaseException) -> str | None:
    cause = getattr(getattr(exc, "orig", None), "__cause__", None) or getattr(exc, "orig", None)
    return getattr(cause, "constraint_name", None)


async def _must_fail(conn: AsyncConnection, sql: str, **params: Any) -> str | None:
    nested = await conn.begin_nested()
    try:
        with pytest.raises((IntegrityError, DBAPIError)) as err:
            await conn.execute(text(sql), params)
    finally:
        await nested.rollback()
    return _constraint(err.value)


_ROSTER_INSERT = (
    "INSERT INTO shift_roster (id, company_id, employee_id, roster_date, shift_id, status, "
    "is_week_off_override, is_holiday_working_override) "
    "VALUES (:i, :c, :e, :d, :s, 'DRAFT', :w, false)"
)


def _reg_insert(version_id: UUID) -> str:
    return (
        "INSERT INTO attendance_regularization_request (id, company_id, employee_id, "
        "attendance_date, request_type, status, approval_chain, regularization_policy_version_id, "
        f"requested_shift_id, submitted_at) VALUES (:i, :c, :e, :d, 'WRONG_SHIFT', 'SUBMITTED', 'HR', '{version_id}', :s, now())"
    )


async def _policy_version(admin_engine: AsyncEngine, tenant: Tenant) -> UUID:
    async with admin_engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT id FROM regularization_policy_version WHERE company_id = :c LIMIT 1"),
                {"c": str(tenant.company_id)},
            )
        ).one()
    return UUID(str(row[0]))


async def test_r1_r4_roster_references_are_enforced_by_the_database(
    tenants: tuple[Tenant, Tenant],  # noqa: F811
    role_engine: tuple[str, AsyncEngine],
) -> None:
    role, engine = role_engine
    a, b = tenants
    conn = await _open(engine, role, a)
    try:
        ids = {"c": a.company_id, "e": UUID(a.employee_id)}
        own, week_off = uuid4(), uuid4()
        # R1: own-company shift; R4: NULL shift (week-off) - both accepted
        await conn.execute(
            text(_ROSTER_INSERT),
            {**ids, "i": own, "d": date(2026, 9, 1), "s": UUID(a.shift_id), "w": False},
        )
        await conn.execute(
            text(_ROSTER_INSERT),
            {**ids, "i": week_off, "d": date(2026, 9, 2), "s": None, "w": True},
        )
        # R2: another company's shift - rejected by the composite FK, not by anything in the app
        foreign = await _must_fail(
            conn, _ROSTER_INSERT, **ids, i=uuid4(), d=date(2026, 9, 3), s=UUID(b.shift_id), w=False
        )
        assert foreign == ROSTER_FK
        unknown = await _must_fail(
            conn, _ROSTER_INSERT, **ids, i=uuid4(), d=date(2026, 9, 4), s=uuid4(), w=False
        )
        assert unknown in (ROSTER_FK, "shift_roster_shift_id_fkey")
        # R3: re-pointing an existing row at another company's shift
        moved = await _must_fail(
            conn, "UPDATE shift_roster SET shift_id = :s WHERE id = :i", s=UUID(b.shift_id), i=own
        )
        assert moved == ROSTER_FK
        # ... or moving the row itself into the other company
        await _must_fail(
            conn, "UPDATE shift_roster SET company_id = :c WHERE id = :i", c=b.company_id, i=own
        )
        stored = (
            await conn.execute(
                text("SELECT company_id, shift_id FROM shift_roster WHERE id = :i"), {"i": own}
            )
        ).one()
        assert (stored[0], str(stored[1])) == (a.company_id, a.shift_id)
    finally:
        await conn.rollback()
        await conn.close()


async def test_r5_regularization_references_are_enforced_by_the_database(
    tenants: tuple[Tenant, Tenant],  # noqa: F811
    role_engine: tuple[str, AsyncEngine],
    admin_engine: AsyncEngine,
) -> None:
    role, engine = role_engine
    a, b = tenants
    insert = _reg_insert(await _policy_version(admin_engine, a))
    conn = await _open(engine, role, a)
    try:
        ids = {"c": a.company_id, "e": UUID(a.employee_id)}
        own = uuid4()
        await conn.execute(
            text(insert), {**ids, "i": own, "d": date(2026, 8, 3), "s": UUID(a.shift_id)}
        )
        await conn.execute(text(insert), {**ids, "i": uuid4(), "d": date(2026, 8, 4), "s": None})
        foreign = await _must_fail(
            conn, insert, **ids, i=uuid4(), d=date(2026, 8, 5), s=UUID(b.shift_id)
        )
        assert foreign == REG_FK
        unknown = await _must_fail(conn, insert, **ids, i=uuid4(), d=date(2026, 8, 6), s=uuid4())
        assert unknown in (REG_FK, "attendance_regularization_request_requested_shift_id_fkey")
        moved = await _must_fail(
            conn,
            "UPDATE attendance_regularization_request SET requested_shift_id = :s WHERE id = :i",
            s=UUID(b.shift_id),
            i=own,
        )
        assert moved == REG_FK
    finally:
        await conn.rollback()
        await conn.close()


async def test_r6_a_referenced_shift_cannot_be_moved_to_another_company(
    tenants: tuple[Tenant, Tenant],  # noqa: F811
    admin_engine: AsyncEngine,
) -> None:
    a, b = tenants
    conn = await _open(admin_engine, "owner", a)
    try:
        await conn.execute(
            text(_ROSTER_INSERT),
            {
                "i": uuid4(),
                "c": a.company_id,
                "e": UUID(a.employee_id),
                "d": date(2026, 9, 1),
                "s": UUID(a.shift_id),
                "w": False,
            },
        )
        await _must_fail(
            conn,
            "UPDATE shift SET company_id = :c WHERE id = :s",
            c=b.company_id,
            s=UUID(a.shift_id),
        )
    finally:
        await conn.rollback()
        await conn.close()


async def test_r7_deleting_a_referenced_shift_nulls_only_the_shift_reference(
    tenants: tuple[Tenant, Tenant],  # noqa: F811
    admin_engine: AsyncEngine,
) -> None:
    a, _ = tenants
    shift_id, roster_id, reg_id = uuid4(), uuid4(), uuid4()
    version = await _policy_version(admin_engine, a)
    async with admin_engine.begin() as conn:  # a throw-away shift of this test's own tenant
        await conn.execute(
            text(
                "INSERT INTO shift (id, company_id, name, start_time, end_time) "
                "VALUES (:s, :c, 'R7', '09:00', '18:00')"
            ),
            {"s": shift_id, "c": a.company_id},
        )
        await conn.execute(
            text(_ROSTER_INSERT),
            {
                "i": roster_id,
                "c": a.company_id,
                "e": UUID(a.employee_id),
                "d": date(2026, 9, 7),
                "s": shift_id,
                "w": False,
            },
        )
        await conn.execute(
            text(_reg_insert(version)),
            {
                "i": reg_id,
                "c": a.company_id,
                "e": UUID(a.employee_id),
                "d": date(2026, 8, 7),
                "s": shift_id,
            },
        )
        await conn.execute(text("DELETE FROM shift WHERE id = :s"), {"s": shift_id})
    async with admin_engine.connect() as conn:
        roster = (
            await conn.execute(
                text("SELECT company_id, shift_id FROM shift_roster WHERE id = :i"),
                {"i": roster_id},
            )
        ).one()
        reg = (
            await conn.execute(
                text(
                    "SELECT company_id, requested_shift_id FROM attendance_regularization_request WHERE id = :i"
                ),
                {"i": reg_id},
            )
        ).one()
    assert tuple(roster) == (a.company_id, None)  # company key untouched, only the shift cleared
    assert tuple(reg) == (a.company_id, None)


async def test_r8_the_service_layer_still_answers_404_for_a_foreign_shift(
    client: AsyncClient,
    tenants: tuple[Tenant, Tenant],  # noqa: F811
    app_as_runtime_role: Any,
    admin_engine: AsyncEngine,
) -> None:
    a, b = tenants
    async with app_as_runtime_role():
        roster = await client.post(
            "/v1/rosters",
            headers=a.headers,
            json={
                "employee_id": a.employee_id,
                "roster_date": "2026-09-14",
                "shift_id": b.shift_id,
            },
        )
        reg = await client.post(
            "/v1/regularizations",
            headers=a.headers,
            json={
                "employee_id": a.employee_id,
                "attendance_date": "2026-08-12",
                "request_type": "WRONG_SHIFT",
                "reason": "r8",
                "requested_shift_id": b.shift_id,
            },
        )
    assert (roster.status_code, reg.status_code) == (404, 404)  # not an opaque FK error / 500


async def test_r9_teardown_removes_only_the_tests_own_rows(
    client: AsyncClient, seeded_plan_catalogue: None, admin_engine: AsyncEngine
) -> None:
    async def count(sql: str) -> int:
        async with admin_engine.connect() as conn:
            return int((await conn.execute(text(sql))).scalar_one())

    companies_before = await count("SELECT count(*) FROM company")
    tenant = await _provision(client)
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(_ROSTER_INSERT),
            {
                "i": uuid4(),
                "c": tenant.company_id,
                "e": UUID(tenant.employee_id),
                "d": date(2026, 9, 1),
                "s": UUID(tenant.shift_id),
                "w": False,
            },
        )
    await wipe_tenant(company_id=tenant.company_id, user_id=tenant.user_id)
    assert (
        await count(f"SELECT count(*) FROM shift_roster WHERE company_id = '{tenant.company_id}'")
        == 0
    )
    assert await count(f"SELECT count(*) FROM shift WHERE company_id = '{tenant.company_id}'") == 0
    assert await count("SELECT count(*) FROM company") == companies_before
