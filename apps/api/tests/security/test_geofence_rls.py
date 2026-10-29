"""Row-level security on the geofencing tables, proven with the real `hrms_app` runtime role
(not SUPERUSER, not BYPASSRLS) on a raw connection — so it is the database, not application
`WHERE company_id` predicates, that is being tested.

Rows are created through the API under the admin test role; they are then read and attacked
through `hrms_app` with each tenant's `app.company_id`."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from tests.integration.modules.attendance.test_attendance_day import (
    _cleanup_attendance_day,
    _register_tenant,
)
from tests.integration.modules.attendance.test_attendance_security import (
    _cleanup_scoped_users,
    _create_permission_scoped_user,
)
from tests.integration.modules.attendance.test_geofence import KOCHI, _wire, fix, north
from tests.integration.modules.organisation.test_registration_flow import _cleanup
from tests.security.test_rls_runtime_role import RUNTIME_ROLE_ASYNC_URL

from hrms.modules.attendance.permissions import ATTENDANCE_PUNCH, ATTENDANCE_VIEW

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def runtime_conn() -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(RUNTIME_ROLE_ASYNC_URL)
    async with engine.connect() as conn:
        yield conn
    await engine.dispose()


async def _scoped(conn: AsyncConnection, company_id: UUID) -> None:
    await conn.rollback()
    await conn.execute(text(f"SET LOCAL app.company_id = '{company_id}'"))  # noqa: S608


async def _as_tenant_count(conn: AsyncConnection, company_id: UUID, table: str) -> int:
    await _scoped(conn, company_id)
    value = (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()  # noqa: S608
    await conn.rollback()
    return int(value)


async def _seed(client: AsyncClient, headers: dict[str, str], company_id: UUID) -> dict[str, str]:
    """One REQUIRED-policy employee with a rejected attempt and an accepted one, plus an extra
    workplace authorisation."""
    wired = await _wire(client, headers, mode="REQUIRED")
    me, _ = await _create_permission_scoped_user(
        company_id=company_id,
        permission_codes=[ATTENDANCE_PUNCH, ATTENDANCE_VIEW],
        data_scope="SELF",
        caller_employee_id=UUID(wired["employee_id"]),
    )
    assert (
        await client.post(
            "/v1/attendance/punches/me",
            headers=me,
            json={"direction": "IN", "location": fix(north(900))},
        )
    ).status_code == 422
    assert (
        await client.post(
            "/v1/attendance/punches/me",
            headers=me,
            json={"direction": "IN", "location": fix(KOCHI)},
        )
    ).status_code == 201
    other = (
        await client.post(
            "/v1/branches",
            headers=headers,
            json={
                "legal_entity_id": wired["legal_entity_id"],
                "name": "Second",
                "timezone": "UTC",
                "latitude": KOCHI[0] + 1,
                "longitude": KOCHI[1],
                "geofence_radius_m": 100,
            },
        )
    ).json()["data"]
    granted = await client.post(
        "/v1/attendance/workplace-authorizations",
        headers=headers,
        json={"employee_id": wired["employee_id"], "branch_id": other["id"]},
    )
    assert granted.status_code == 201, granted.text
    return {**wired, "second_branch_id": other["id"]}


async def _teardown(company_id: UUID, user_id: UUID | None) -> None:
    await _cleanup_attendance_day(company_id=company_id)
    await _cleanup(company_id=company_id, user_id=user_id)


async def test_each_tenant_sees_only_its_own_geofence_rows(
    client: AsyncClient, seeded_plan_catalogue: None, runtime_conn: AsyncConnection
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        await _seed(client, headers_a, company_a)
        wired_b = await _seed(client, headers_b, company_b)

        for company in (company_a, company_b):
            assert await _as_tenant_count(runtime_conn, company, "geofence_attempt") == 2
            assert (
                await _as_tenant_count(runtime_conn, company, "employee_workplace_authorization")
                == 1
            )

        # Even a hand-written query with no company filter at all sees only the scoped tenant.
        await _scoped(runtime_conn, company_a)
        foreign = (
            await runtime_conn.execute(
                text("SELECT count(*) FROM geofence_attempt WHERE company_id = :other"),
                {"other": str(company_b)},
            )
        ).scalar_one()
        assert foreign == 0
        await runtime_conn.rollback()
        assert wired_b  # silence unused warning; B's data exists and was counted above
    finally:
        await _teardown(company_a, user_a)
        await _teardown(company_b, user_b)
        await _cleanup_scoped_users()


async def test_no_tenant_context_sees_nothing(
    client: AsyncClient, seeded_plan_catalogue: None, runtime_conn: AsyncConnection
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        await _seed(client, headers, company_id)
        await runtime_conn.rollback()
        # An unscoped connection must not read tenant rows (RLS compares against a NULL/absent
        # GUC). Depending on the pooled-GUC quirk it returns no rows or errors; it never leaks.
        try:
            rows = (
                await runtime_conn.execute(text("SELECT count(*) FROM geofence_attempt"))
            ).scalar_one()
            assert rows == 0
        except DBAPIError:
            pass
        await runtime_conn.rollback()
    finally:
        await _teardown(company_id, user_id)
        await _cleanup_scoped_users()


async def test_cross_tenant_writes_are_blocked_by_the_database(
    client: AsyncClient, seeded_plan_catalogue: None, runtime_conn: AsyncConnection
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        wired_a = await _seed(client, headers_a, company_a)
        wired_b = await _seed(client, headers_b, company_b)

        # Positive control: the same INSERT is allowed for B's own company, so the refusals
        # below are the row-level policy, not a missing grant.
        await _scoped(runtime_conn, company_b)
        inserted = await runtime_conn.execute(
            text(
                "INSERT INTO geofence_attempt (id, company_id, employee_id, direction, source,"
                " mode, outcome, accepted) VALUES (:i, :c, :e, 'IN', 'WEB', 'REQUIRED',"
                " 'INSIDE', true)"
            ),
            {"i": str(uuid4()), "c": str(company_b), "e": wired_b["employee_id"]},
        )
        assert inserted.rowcount == 1
        await runtime_conn.rollback()

        # B cannot INSERT a row that claims to belong to A (WITH CHECK).
        await _scoped(runtime_conn, company_b)
        with pytest.raises(DBAPIError):
            await runtime_conn.execute(
                text(
                    "INSERT INTO geofence_attempt (id, company_id, employee_id, direction, source,"
                    " mode, outcome, accepted) VALUES (:i, :c, :e, 'IN', 'WEB', 'REQUIRED',"
                    " 'INSIDE', true)"
                ),
                {"i": str(uuid4()), "c": str(company_a), "e": wired_a["employee_id"]},
            )
        await runtime_conn.rollback()

        with pytest.raises(DBAPIError):
            await _scoped(runtime_conn, company_b)
            await runtime_conn.execute(
                text(
                    "INSERT INTO employee_workplace_authorization (id, company_id, employee_id,"
                    " branch_id) VALUES (:i, :c, :e, :b)"
                ),
                {
                    "i": str(uuid4()),
                    "c": str(company_a),
                    "e": wired_a["employee_id"],
                    "b": wired_a["second_branch_id"],
                },
            )
        await runtime_conn.rollback()

        # B cannot UPDATE or DELETE A's rows: they are invisible, so zero rows match.
        await _scoped(runtime_conn, company_b)
        updated = await runtime_conn.execute(
            text("UPDATE geofence_attempt SET accepted = true WHERE company_id = :a"),
            {"a": str(company_a)},
        )
        deleted = await runtime_conn.execute(
            text("DELETE FROM geofence_attempt WHERE company_id = :a"), {"a": str(company_a)}
        )
        deleted_auth = await runtime_conn.execute(
            text("DELETE FROM employee_workplace_authorization WHERE company_id = :a"),
            {"a": str(company_a)},
        )
        assert (updated.rowcount, deleted.rowcount, deleted_auth.rowcount) == (0, 0, 0)
        await runtime_conn.commit()

        assert await _as_tenant_count(runtime_conn, company_a, "geofence_attempt") == 2
        assert (
            await _as_tenant_count(runtime_conn, company_a, "employee_workplace_authorization") == 1
        )
    finally:
        await _teardown(company_a, user_a)
        await _teardown(company_b, user_b)
        await _cleanup_scoped_users()


async def test_composite_foreign_keys_reject_a_foreign_branch_even_inside_one_tenant(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Database-level proof the tenant can't be spoofed through the foreign keys: with the *owner*
    role (RLS bypassed), an authorisation that pairs company A with company B's branch is still
    refused by the composite (company_id, branch_id) key."""
    from hrms.core.db.session import get_session_factory

    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        wired_a = await _seed(client, headers_a, company_a)
        wired_b = await _seed(client, headers_b, company_b)
        async with get_session_factory()() as session:
            with pytest.raises(DBAPIError):
                await session.execute(
                    text(
                        "INSERT INTO employee_workplace_authorization (id, company_id, employee_id,"
                        " branch_id) VALUES (:i, :c, :e, :b)"
                    ),
                    {
                        "i": str(uuid4()),
                        "c": str(company_a),
                        "e": wired_a["employee_id"],
                        "b": wired_b["branch_id"],
                    },
                )
                await session.commit()
            await session.rollback()
            with pytest.raises(DBAPIError):
                await session.execute(
                    text(
                        "INSERT INTO geofence_attempt (id, company_id, employee_id, direction,"
                        " source, mode, outcome, accepted, created_at) VALUES (:i, :c, :e, 'IN',"
                        " 'WEB', 'REQUIRED', 'INSIDE', true, :t)"
                    ),
                    {
                        "i": str(uuid4()),
                        "c": str(company_a),
                        "e": wired_b["employee_id"],
                        "t": datetime.now(UTC),
                    },
                )
                await session.commit()
            await session.rollback()
    finally:
        await _teardown(company_a, user_a)
        await _teardown(company_b, user_b)
        await _cleanup_scoped_users()
