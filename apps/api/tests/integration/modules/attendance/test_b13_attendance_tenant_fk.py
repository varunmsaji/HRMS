"""B13 Workstream C (runtime-role side) - `attendance_day` cannot reference another
tenant's employee, enforced by the database (migration `20261027092000`, composite FK
`attendance_day (company_id, employee_id) -> employee (company_id, id)`).

Run on the migrated run database with real tenants created through the API. The same assertions are
made as the owner role and as the runtime role `hrms_app` (row-level security on, tenant variable
set) - the role the application really uses. The scratch-database tests in
`tests/integration/migrations` cover the migration itself (valid / invalid existing data, down/up).
Application writers of `attendance_day`: `AttendanceDayRepository.insert` (only
`AttendanceDayService.calculate`, which B12 guards) and 7 `update(AttendanceDay)` statements that
set computed columns only - none writes `company_id` or `employee_id`.
"""

import os
from datetime import date
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from tests.integration.modules.employee.test_employee_assignment import _create_employee
from tests.integration.modules.employee.test_employment import _register_tenant
from tests.integration.tenant_wipe import wipe_tenant

from hrms.core.config.settings import get_settings
from hrms.core.db.session import get_session_factory, set_rls_company_id

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("seeded_plan_catalogue")]

FK = "attendance_day_company_employee_fkey"


def _runtime_url() -> str:
    explicit = os.environ.get("HRMS_APP_DATABASE_URL")
    if explicit:
        base = explicit.split("?", 1)[0]
    else:
        admin = os.environ["DATABASE_URL"].split("?", 1)[0]
        host = urlsplit(admin).netloc.rsplit("@", 1)[-1]
        base = urlsplit(admin)._replace(netloc=f"hrms_app:hrms_app_dev_password@{host}").geturl()
    return base.replace("postgresql://", "postgresql+asyncpg://", 1)


async def _insert_day(session: AsyncSession, company: UUID, employee: UUID, day: date) -> UUID:
    row_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO attendance_day (id, company_id, employee_id, attendance_date, timezone, "
            "attendance_status) VALUES (:i, :c, :e, :d, 'UTC', 'PRESENT')"
        ),
        {"i": row_id, "c": company, "e": employee, "d": day},
    )
    return row_id


async def _constraint_name(exc: BaseException) -> str | None:
    cause = getattr(getattr(exc, "orig", None), "__cause__", None) or getattr(exc, "orig", None)
    return getattr(cause, "constraint_name", None)


async def _scenario(
    session: AsyncSession, a: UUID, emp_a: UUID, b: UUID, emp_b: UUID, month: int
) -> None:
    """All assertions for ONE connection/role. `session` already has the tenant variable for `a`
    when the role is subject to RLS."""
    # valid same-tenant insert and update
    ok = await _insert_day(session, a, emp_a, date(2026, month, 1))
    await session.execute(
        text("UPDATE attendance_day SET attendance_date = :d WHERE id = :i"),
        {"d": date(2026, month, 2), "i": ok},
    )
    await session.flush()

    async def must_fail(sql: str, **params: object) -> BaseException:
        nested = await session.begin_nested()
        try:
            with pytest.raises((IntegrityError, DBAPIError)) as err:
                await session.execute(text(sql), params)
        finally:
            await nested.rollback()
        return err.value

    # cross-tenant employee reference, unknown employee
    for employee in (emp_b, uuid4()):
        nested = await session.begin_nested()
        try:
            with pytest.raises((IntegrityError, DBAPIError)) as err:
                await _insert_day(session, a, employee, date(2026, month, 3))
        finally:
            await nested.rollback()
        assert await _constraint_name(err.value) in (FK, "attendance_day_employee_id_fkey")
    cross = await _constraint_name(
        await must_fail(
            "INSERT INTO attendance_day (id, company_id, employee_id, attendance_date, timezone, "
            "attendance_status) VALUES (:i, :c, :e, :d, 'UTC', 'PRESENT')",
            i=uuid4(),
            c=a,
            e=emp_b,
            d=date(2026, month, 4),
        )  # fmt: skip
    )
    assert cross == FK

    # attempts to move an existing row across the boundary: only the employee, only the company
    await must_fail("UPDATE attendance_day SET employee_id = :e WHERE id = :i", e=emp_b, i=ok)
    await must_fail("UPDATE attendance_day SET company_id = :c WHERE id = :i", c=b, i=ok)
    # the row is exactly as it was
    stored = (
        await session.execute(
            text("SELECT company_id, employee_id FROM attendance_day WHERE id = :i"), {"i": ok}
        )
    ).one()
    assert stored == (a, emp_a)


async def test_database_rejects_cross_tenant_attendance_for_owner_and_runtime_roles(
    client: AsyncClient,
) -> None:
    ha, a, ua = await _register_tenant(client)
    hb, b, ub = await _register_tenant(client)
    try:
        emp_a = UUID((await _create_employee(client, ha, first_name="A"))["id"])
        emp_b = UUID((await _create_employee(client, hb, first_name="B"))["id"])

        # owner role (no RLS): the composite FK alone must hold
        async with get_session_factory()() as owner:
            await _scenario(owner, a, emp_a, b, emp_b, 5)
            # moving an employee that has attendance to another company, or deleting it, is refused
            for sql in (
                "UPDATE employee SET company_id = :c WHERE id = :e",
                "DELETE FROM employee WHERE id = :e",
            ):
                nested = await owner.begin_nested()
                try:
                    with pytest.raises((IntegrityError, DBAPIError)):
                        await owner.execute(text(sql), {"c": b, "e": emp_a})
                finally:
                    await nested.rollback()
            await owner.commit()

        # runtime role hrms_app with RLS and the tenant variable set, as the application connects
        engine = create_async_engine(_runtime_url(), hide_parameters=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as runtime:
                await set_rls_company_id(runtime, str(a))
                await _scenario(runtime, a, emp_a, b, emp_b, 6)
                await runtime.rollback()
        finally:
            await engine.dispose()
        get_settings.cache_clear()
    finally:
        await wipe_tenant(company_id=b, user_id=ub)
        await wipe_tenant(company_id=a, user_id=ua)
