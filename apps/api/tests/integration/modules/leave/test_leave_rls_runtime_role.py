"""Stage 4 of the P1 remediation: the leave-application lifecycle under the real runtime role.

Selected workflow (and why): submit -> read -> approve -> cancel / reject of a leave application on
the HR approval chain, with the leave ledger and balance checked at every step. It crosses the
tables that matter for leave tenant isolation - `leave_application`, `leave_application_day`,
`leave_application_action`, `leave_ledger`, `leave_day_projection`, `idempotency_key` - all
`company_id` + FORCE RLS, it exercises the cross-module hand-off to the projection service, and the
HR chain leaves an application pending (reserved balance, no debit) until a reviewer acts, which
gives real status transitions to assert. Expectations are taken from the existing behaviour pinned
by `test_leave_application.py` / `test_leave_reserved_balance.py`; nothing new is invented.

Roles: tenant registration, the policy/calendar/employee graph, the opening balance and teardown
run on the admin engine. Every operation under test runs inside `app_as_runtime_role()` (the app's
own engine as `hrms_app`, role attributes asserted by `tests/rls_support.py`).

Not applicable and not tested: cross-tenant creates by raw INSERT (WITH CHECK is proven on the
probe table in `tests/security/test_rls_harness.py`; the create routes take `company_id` from the
verified token).
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine
from tests import rls_support
from tests.integration.modules.leave.test_leave_application import (
    _cleanup,
    _register_tenant,
    _setup_full,
    _submit,
    _teardown,
)

from hrms.core.db.session import get_session_factory

pytestmark = pytest.mark.asyncio

D1, D2 = "2026-09-08", "2026-09-09"  # Tue / Wed, no Sunday in range


@dataclass
class Tenant:
    headers: dict[str, str]
    company_id: UUID
    user_id: UUID | None
    employee_id: str
    leave_type_id: str
    application_id: str  # a SUBMITTED application created during (admin) setup

    @property
    def token_only(self) -> dict[str, str]:
        return {"Authorization": self.headers["Authorization"]}


async def _provision(client: AsyncClient) -> Tenant:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, approval_chain="HR", balance="20.00")
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]
        submitted = await _submit(
            client,
            headers,
            employee_id=employee_id,
            leave_type_id=leave_type_id,
            start_date="2026-10-05",
            end_date="2026-10-05",
        )
        assert submitted.status_code == 201, submitted.text
        assert submitted.json()["data"]["status"] == "SUBMITTED"
    except BaseException:
        await _full_teardown(company_id, user_id)
        raise
    return Tenant(
        headers, company_id, user_id, employee_id, leave_type_id, submitted.json()["data"]["id"]
    )


async def _full_teardown(company_id: UUID, user_id: UUID | None) -> None:
    await _teardown(company_id=company_id)
    factory = get_session_factory()
    async with factory() as session:  # rows the leave suite's own teardown does not list
        for table in ("idempotency_key",):
            await session.execute(
                text(f"DELETE FROM {table} WHERE company_id = :c"),  # noqa: S608
                {"c": str(company_id)},
            )
        await session.commit()
    await _cleanup(company_id=company_id, user_id=user_id)


@pytest.fixture
async def world(
    client: AsyncClient, seeded_plan_catalogue: None
) -> AsyncIterator[tuple[Tenant, Tenant]]:
    """Two fully provisioned tenants; teardown is in `finally`, on the admin engine."""
    made: list[Tenant] = []
    try:
        made.append(await _provision(client))
        made.append(await _provision(client))
        yield made[0], made[1]
    finally:
        for tenant in reversed(made):
            await _full_teardown(tenant.company_id, tenant.user_id)


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


async def _balance(client: AsyncClient, tenant: Tenant) -> tuple[Decimal, Decimal]:
    response = await client.get(
        "/v1/leave-balances", headers=tenant.headers, params={"employee_id": tenant.employee_id}
    )
    assert response.status_code == 200, response.text
    row = response.json()["data"][0]
    return Decimal(row["balance"]), Decimal(row["reserved_balance"])


async def _ledger(client: AsyncClient, tenant: Tenant) -> list[dict[str, Any]]:
    response = await client.get(
        "/v1/leave-ledger", headers=tenant.headers, params={"employee_id": tenant.employee_id}
    )
    assert response.status_code == 200, response.text
    return list(response.json()["data"])


async def _assert_ledger_matches_balance(client: AsyncClient, tenant: Tenant) -> Decimal:
    """Invariant (LD-03): the balance is the sum of the ledger."""
    balance, _ = await _balance(client, tenant)
    total = sum((Decimal(e["amount"]) for e in await _ledger(client, tenant)), Decimal(0))
    assert total == balance, (total, balance)
    return balance


async def _db_state(admin_engine: AsyncEngine, tenant: Tenant) -> dict[str, Any]:
    """Admin-role (RLS-exempt) snapshot of everything leave-related for one tenant."""
    async with admin_engine.connect() as conn:
        apps = (
            await conn.execute(
                text(
                    "SELECT id, status, version, updated_at FROM leave_application "
                    "WHERE company_id = :c ORDER BY id"
                ),
                {"c": str(tenant.company_id)},
            )
        ).all()
        ledger = (
            await conn.execute(
                text(
                    "SELECT id, entry_type, amount FROM leave_ledger "
                    "WHERE company_id = :c ORDER BY id"
                ),
                {"c": str(tenant.company_id)},
            )
        ).all()
        projections = (
            await conn.execute(
                text(
                    "SELECT id, status FROM leave_day_projection WHERE company_id = :c ORDER BY id"
                ),
                {"c": str(tenant.company_id)},
            )
        ).all()
    return {
        "applications": [tuple(r) for r in apps],
        "ledger": [tuple(r) for r in ledger],
        "projections": [tuple(r) for r in projections],
    }


# --- evidence that the application ran as hrms_app ------------


async def test_requests_are_served_by_the_runtime_role(
    client: AsyncClient,
    world: tuple[Tenant, Tenant],
    app_as_runtime_role: Any,
    admin_engine: AsyncEngine,
) -> None:
    a, _ = world
    runtime_user = urlsplit(rls_support.runtime_url()).username
    backends = text(
        "SELECT pid, usename FROM pg_stat_activity WHERE datname = current_database() "
        "AND pid <> pg_backend_pid() AND backend_type = 'client backend'"
    )
    async with admin_engine.connect() as conn:
        before = {row.pid for row in await conn.execute(backends)}
    async with app_as_runtime_role():
        await _balance(client, a)
        async with admin_engine.connect() as conn:
            created = {row.usename for row in await conn.execute(backends) if row.pid not in before}
    assert created == {runtime_user}, created


# --- 1 + 6: valid lifecycle and ledger invariants ------------


async def test_leave_lifecycle_under_runtime_role_keeps_ledger_and_balance_consistent(
    client: AsyncClient, world: tuple[Tenant, Tenant], app_as_runtime_role: Any
) -> None:
    a, _ = world
    async with app_as_runtime_role():
        assert await _assert_ledger_matches_balance(client, a) == Decimal("20.00")

        # Submit (HR chain): pending, balance not debited, but shown as reserved.
        submitted = await _submit(
            client, a.headers, employee_id=a.employee_id, leave_type_id=a.leave_type_id,
            start_date=D1, end_date=D1,
        )  # fmt: skip
        assert submitted.status_code == 201, submitted.text
        pending = submitted.json()["data"]
        assert pending["status"] == "SUBMITTED" and pending["total_days"] == "1.00"
        balance, reserved = await _balance(client, a)
        assert balance == Decimal("20.00") and reserved == Decimal("2.00")  # setup app + this one
        await _assert_ledger_matches_balance(client, a)

        # Reads inside the tenant.
        listed = await client.get("/v1/leave-applications", headers=a.headers)
        assert listed.status_code == 200, listed.text
        assert {a.application_id, pending["id"]} <= _ids(listed.json())
        one = await client.get(f"/v1/leave-applications/{pending['id']}", headers=a.headers)
        assert one.status_code == 200 and one.json()["data"]["id"] == pending["id"]

        # Approve: debits the ledger exactly once.
        approved = await client.post(
            f"/v1/leave-applications/{pending['id']}/approve",
            headers={**a.headers, "If-Match": str(pending["version"])},
            json={},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["data"]["status"] == "APPROVED"
        assert await _assert_ledger_matches_balance(client, a) == Decimal("19.00")
        assert any(e["entry_type"] == "APPLICATION" for e in await _ledger(client, a))

        # Cancel after approval: offsetting credit, original debit untouched (ADR-0004).
        cancelled = await client.post(
            f"/v1/leave-applications/{pending['id']}/cancel",
            headers={**a.headers, "If-Match": str(approved.json()["data"]["version"])},
            json={"reason": "Recalled to work"},
        )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["data"]["status"] == "CANCELLED"
        assert await _assert_ledger_matches_balance(client, a) == Decimal("20.00")

        # Reject the setup application: no balance effect.
        rejected = await client.post(
            f"/v1/leave-applications/{a.application_id}/reject",
            headers={**a.headers, "If-Match": "1"},
            json={"rejection_reason": "Coverage"},
        )
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["data"]["status"] == "REJECTED"
        assert await _assert_ledger_matches_balance(client, a) == Decimal("20.00")


async def test_rejected_submissions_leave_ledger_and_balance_untouched(
    client: AsyncClient,
    world: tuple[Tenant, Tenant],
    app_as_runtime_role: Any,
    admin_engine: AsyncEngine,
) -> None:
    a, _ = world
    before = await _db_state(admin_engine, a)
    async with app_as_runtime_role():
        too_long = await _submit(
            client, a.headers, employee_id=a.employee_id, leave_type_id=a.leave_type_id,
            start_date="2026-09-14", end_date="2026-10-30",
        )  # fmt: skip
        assert too_long.status_code == 422, too_long.text
        # The consecutive-days rule fires before the balance rule for a 33-working-day request.
        assert too_long.json()["error"]["code"] == "LEAVE_APPLICATION_MAX_CONSECUTIVE_EXCEEDED"
        overlapping = await _submit(
            client, a.headers, employee_id=a.employee_id, leave_type_id=a.leave_type_id,
            start_date="2026-10-05", end_date="2026-10-05",
        )  # fmt: skip
        assert overlapping.status_code >= 400, overlapping.text
        assert await _assert_ledger_matches_balance(client, a) == Decimal("20.00")
    assert await _db_state(admin_engine, a) == before


# --- 2: cross-tenant reads ------------


async def test_tenant_a_cannot_read_tenant_b_leave_data(
    client: AsyncClient,
    world: tuple[Tenant, Tenant],
    app_as_runtime_role: Any,
    runtime_engine: AsyncEngine,
) -> None:
    a, b = world
    async with app_as_runtime_role():
        mine = await client.get("/v1/leave-applications", headers=a.headers)
        assert mine.status_code == 200, mine.text
        assert a.application_id in _ids(mine.json())
        assert b.application_id not in _ids(mine.json())

        direct = await client.get(f"/v1/leave-applications/{b.application_id}", headers=a.headers)
        assert direct.status_code == 404, direct.text
        assert b.application_id not in direct.text

        by_employee = await client.get(
            "/v1/leave-applications", headers=a.headers, params={"employee_id": b.employee_id}
        )
        assert b.application_id not in by_employee.text

        # B's employee id under A's token: B's 20.00 balance and ledger entries are invisible. The
        # balances route answers with A's own leave types at zero (the same shape it gives for any
        # id that has no ledger in A's tenant), so it is not an existence oracle either.
        unknown = await client.get(
            "/v1/leave-balances", headers=a.headers, params={"employee_id": str(uuid4())}
        )
        foreign = await client.get(
            "/v1/leave-balances", headers=a.headers, params={"employee_id": b.employee_id}
        )
        assert foreign.status_code == unknown.status_code == 200, foreign.text
        assert [
            (r["balance"], r["reserved_balance"], r["leave_type_id"])
            for r in foreign.json()["data"]
        ] == [
            (r["balance"], r["reserved_balance"], r["leave_type_id"])
            for r in unknown.json()["data"]
        ]
        assert all(Decimal(r["balance"]) == 0 for r in foreign.json()["data"])
        assert b.leave_type_id not in foreign.text
        ledger = await client.get(
            "/v1/leave-ledger", headers=a.headers, params={"employee_id": b.employee_id}
        )
        assert ledger.status_code in {200, 403, 404}, ledger.text
        if ledger.status_code == 200:
            assert ledger.json()["data"] == []

    # Repository level: under A's tenant the database itself shows none of B's rows.
    async with runtime_engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('app.company_id', :c, true)"), {"c": str(a.company_id)}
        )
        foreign = {}
        for table in ("leave_application", "leave_ledger", "leave_application_day"):
            foreign[table] = (
                await conn.execute(
                    text(f"SELECT count(*) FROM {table} WHERE company_id = :b"),  # noqa: S608
                    {"b": str(b.company_id)},
                )
            ).scalar_one()
        own = (await conn.execute(text("SELECT count(*) FROM leave_application"))).scalar_one()
    assert foreign == {"leave_application": 0, "leave_ledger": 0, "leave_application_day": 0}
    assert own == 1


# --- 3: cross-tenant mutations ------------


async def test_tenant_a_cannot_mutate_tenant_b_leave_data(
    client: AsyncClient,
    world: tuple[Tenant, Tenant],
    app_as_runtime_role: Any,
    admin_engine: AsyncEngine,
    runtime_engine: AsyncEngine,
) -> None:
    a, b = world
    before_b = await _db_state(admin_engine, b)
    async with app_as_runtime_role():
        for action, body in (
            ("approve", {}),
            ("reject", {"rejection_reason": "x"}),
            ("cancel", {"reason": "x"}),
        ):
            response = await client.post(
                f"/v1/leave-applications/{b.application_id}/{action}",
                headers={**a.headers, "If-Match": "1"},
                json=body,
            )
            assert response.status_code == 404, (action, response.text)

        on_behalf = await _submit(
            client, a.headers, employee_id=b.employee_id, leave_type_id=b.leave_type_id,
            start_date=D1, end_date=D1,
        )  # fmt: skip
        assert on_behalf.status_code in {403, 404, 422}, on_behalf.text

        adjustment = await client.post(
            "/v1/leave-ledger/adjustments",
            headers=a.headers,
            json={
                "employee_id": b.employee_id,
                "leave_type_id": b.leave_type_id,
                "amount": "5.00",
                "effective_date": "2026-01-01",
                "reason": "cross-tenant attempt",
            },
        )
        assert adjustment.status_code in {403, 404, 422}, adjustment.text

    async def as_tenant_a(sql: str) -> int:
        async with runtime_engine.begin() as conn:
            await conn.execute(
                text("SELECT set_config('app.company_id', :c, true)"), {"c": str(a.company_id)}
            )
            return (await conn.execute(text(sql), {"b": str(b.company_id)})).rowcount

    # RLS: a mutable table's UPDATE/DELETE as A matches none of B's rows.
    assert (
        await as_tenant_a("UPDATE leave_application SET status = 'APPROVED' WHERE company_id = :b")
        == 0
    )
    assert await as_tenant_a("DELETE FROM leave_application WHERE company_id = :b") == 0
    # The ledger is append-only for the runtime role at the privilege level (no UPDATE/DELETE
    # grant, see test_leave_hardening.py): refused outright, before RLS is even consulted.
    for sql in (
        "UPDATE leave_ledger SET amount = 0 WHERE company_id = :b",
        "DELETE FROM leave_ledger WHERE company_id = :b",
    ):
        with pytest.raises(DBAPIError) as denied:
            await as_tenant_a(sql)
        assert "permission denied" in str(denied.value)
    assert await _db_state(admin_engine, b) == before_b


# --- 4: missing / invalid tenant context ------------


async def test_missing_or_invalid_tenant_context_fails_closed(
    client: AsyncClient, world: tuple[Tenant, Tenant], app_as_runtime_role: Any
) -> None:
    a, b = world
    path = "/v1/leave-applications"
    async with app_as_runtime_role():
        anonymous = await client.get(path, headers={"X-Company-Id": str(b.company_id)})
        assert anonymous.status_code == 401, anonymous.text
        for value in (str(b.company_id), "not-a-uuid", ""):
            spoofed = await client.get(path, headers={**a.token_only, "X-Company-Id": value})
            assert spoofed.status_code == 404, (value, spoofed.text)
            assert b.application_id not in spoofed.text and a.application_id not in spoofed.text
        # The documented token-only form works and is scoped to the token's tenant.
        token_only = await client.get(path, headers=a.token_only)
        assert token_only.status_code == 200, token_only.text
        assert a.application_id in _ids(token_only.json())
        assert b.application_id not in _ids(token_only.json())


# --- 5: pooled connections ------------


async def test_alternating_tenants_over_pooled_connections_never_leak_context(
    client: AsyncClient, world: tuple[Tenant, Tenant], app_as_runtime_role: Any
) -> None:
    a, b = world
    async with app_as_runtime_role():
        for i in range(14):
            own, other = (a, b) if i % 2 == 0 else (b, a)
            listed = await client.get("/v1/leave-applications", headers=own.headers)
            assert listed.status_code == 200, (i, listed.text)
            assert own.application_id in _ids(listed.json())
            assert other.application_id not in _ids(listed.json())
            balance, _ = await _balance(client, own)
            assert balance == Decimal("20.00")
