"""Stage 6 of the P1 remediation: a tenant-scoped Celery task under the real runtime role.

Selected task (and why): `leave.accrue_company` (monthly leave accrual). It is tenant-scoped (one
company per message), writes money-like data (the append-only `leave_ledger`, where a duplicate is
a business defect), is the Leave module's late-ack/auto-retry/idempotent task shape, and its
neighbours (comp-off credit and expiry, year-end) share the same wrapper
(`session_scope(company_id=...)` + `run_task`), so its guarantees carry over by construction.

Production design (verified from `docker-compose.prod.yml`): the worker and Beat load the same
`apps/api/env/.env.production` as the API, whose `DATABASE_URL` is `hrms_app`. So a task is meant
to run as `hrms_app` with a transaction-local `app.company_id` set by `session_scope`. The only
tenant-less read is the fan-out's company listing; `company` has no RLS (`relrowsecurity = false`),
which is deliberate for that global read and is asserted below rather than assumed.

These tests execute the real Celery task object (`Task.apply(throw=True)`, in a worker thread
because `run_task` calls `asyncio.run`) with the app engine repointed at `hrms_app`. Setup,
independent snapshots and teardown use the admin engine / default role. Nothing here deletes data
other than the two tenants this module creates.

Not covered here: the attendance, employee-termination and employee-import tasks (the latter two
have no late-ack/retry; see the stage report), and Beat/heartbeat operations.
"""

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import patch
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from celery.exceptions import Retry
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from tests import rls_support
from tests.integration.modules.leave.test_leave_accrual import (
    _create_employee,
    _create_employment,
    _create_leave_type,
    _create_legal_entity,
    _create_published_monthly_policy,
    _register_tenant,
    _teardown,
)
from tests.integration.modules.leave.test_leave_tasks_business_time import _frozen_now
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.modules.leave import tasks as leave_tasks
from hrms.modules.leave.service import LeaveAccrualService

pytestmark = pytest.mark.asyncio

#: 2026-03-02 06:00 UTC is 1-3 March in every timezone, so the accrued month is always February
#: 2026 (28 days, effective_date 2026-02-28) and the run is inside the 5-day accrual window.
_NOW = datetime(2026, 3, 2, 6, 0, tzinfo=UTC)
_PERIOD_END = date(2026, 2, 28)


@dataclass
class Tenant:
    headers: dict[str, str]
    company_id: UUID
    user_id: UUID | None
    employees: list[str]
    rate: Decimal


async def _provision(client: AsyncClient, *, employees: int, rate: str) -> Tenant:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        legal_entity = await _create_legal_entity(client, headers)
        ids: list[str] = []
        for n in range(employees):
            employee = await _create_employee(client, headers, first_name=f"Emp{n}")
            await _create_employment(
                client,
                headers,
                employee_id=employee["id"],
                legal_entity_id=legal_entity["id"],
                joining_date="2025-01-01",
            )
            ids.append(employee["id"])
        leave_type = await _create_leave_type(client, headers)
        await _create_published_monthly_policy(
            client, headers, leave_type_id=leave_type["id"], accrual_rate_per_cycle=rate
        )
    except BaseException:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        raise
    return Tenant(headers, company_id, user_id, ids, Decimal(rate))


@pytest.fixture
async def world(
    client: AsyncClient, seeded_plan_catalogue: None
) -> AsyncIterator[tuple[Tenant, Tenant]]:
    """A: two employees, 1.50/month. B: one employee, 2.00/month. Teardown per tenant."""
    made: list[Tenant] = []
    try:
        made.append(await _provision(client, employees=2, rate="1.50"))
        made.append(await _provision(client, employees=1, rate="2.00"))
        yield made[0], made[1]
    finally:
        for tenant in reversed(made):
            await _teardown(company_id=tenant.company_id)
            await _cleanup(company_id=tenant.company_id, user_id=tenant.user_id)


async def _ledger(admin_engine: AsyncEngine, tenant: Tenant) -> list[tuple[Any, ...]]:
    """Independent admin-role (RLS-exempt) snapshot of the tenant's ledger."""
    async with admin_engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT employee_id, entry_type, amount, effective_date FROM leave_ledger "
                    "WHERE company_id = :c ORDER BY employee_id, entry_type, effective_date"
                ),
                {"c": str(tenant.company_id)},
            )
        ).all()
    return [tuple(r) for r in rows]


async def _run_task(task: Any, *args: Any) -> Any:
    """The real Celery task object, eagerly, in a worker thread (its body calls `asyncio.run`)."""

    def call() -> Any:
        return task.apply(args=list(args), throw=True).get()

    with _frozen_now(_NOW):
        return await asyncio.to_thread(call)


def _spy_original() -> Callable[..., Any]:
    return LeaveAccrualService.run_for_company


# --- role and tenant context inside the task ------------


async def test_task_runs_as_runtime_role_with_the_tasks_tenant_context(
    world: tuple[Tenant, Tenant], app_as_runtime_role: Any, admin_engine: AsyncEngine
) -> None:
    a, b = world
    original = _spy_original()
    seen: list[tuple[str, str]] = []

    async def spy(self: LeaveAccrualService, company_id: UUID, *, as_of: date) -> int:
        row = (
            await self._session.execute(
                text(
                    "SELECT current_user, current_setting('app.company_id', true), "
                    "(SELECT rolbypassrls OR rolsuper FROM pg_roles WHERE rolname = current_user)"
                )
            )
        ).one()
        seen.append((row[0], row[1]))
        assert row[2] is False, "task role bypasses RLS"
        return await original(self, company_id, as_of=as_of)

    async with app_as_runtime_role():
        with patch.object(LeaveAccrualService, "run_for_company", spy):
            written = await _run_task(leave_tasks.accrue_company, str(a.company_id))
    assert written == 2
    assert seen == [(urlsplit(rls_support.runtime_url()).username, str(a.company_id))]
    assert await _ledger(admin_engine, b) == []


async def test_tenant_context_is_transaction_local_and_is_not_left_on_the_connection(
    world: tuple[Tenant, Tenant], app_as_runtime_role: Any, runtime_engine: AsyncEngine
) -> None:
    """`set_config(..., true)` dies with the transaction: after a mid-task commit the tenant is
    gone (a service that commits and keeps querying must re-apply it), and nothing of the task's
    tenant is visible to the next connection."""
    a, _ = world
    original = _spy_original()
    after_commit: list[str | None] = []

    async def spy(self: LeaveAccrualService, company_id: UUID, *, as_of: date) -> int:
        result = await original(self, company_id, as_of=as_of)
        await self._session.commit()
        after_commit.append(
            (
                await self._session.execute(text("SELECT current_setting('app.company_id', true)"))
            ).scalar_one()
        )
        return result

    async with app_as_runtime_role():
        with patch.object(LeaveAccrualService, "run_for_company", spy):
            await _run_task(leave_tasks.accrue_company, str(a.company_id))
    assert after_commit in ([""], [None]), after_commit
    async with runtime_engine.connect() as conn:  # a fresh runtime connection
        leaked = (
            await conn.execute(text("SELECT current_setting('app.company_id', true)"))
        ).scalar()
        assert leaked in (None, "")
        assert (await conn.execute(text("SELECT count(*) FROM leave_ledger"))).scalar_one() == 0


# --- tenant isolation ------------


async def test_task_for_tenant_a_never_reads_or_writes_tenant_b(
    world: tuple[Tenant, Tenant], app_as_runtime_role: Any, admin_engine: AsyncEngine
) -> None:
    a, b = world
    async with app_as_runtime_role():
        assert await _run_task(leave_tasks.accrue_company, str(a.company_id)) == 2
        assert await _ledger(admin_engine, b) == []
        a_after_a = await _ledger(admin_engine, a)
        assert await _run_task(leave_tasks.accrue_company, str(b.company_id)) == 1
    assert await _ledger(admin_engine, a) == a_after_a  # B's run did not touch A
    assert {(r[1], r[2], r[3]) for r in a_after_a} == {("ACCRUAL", Decimal("1.50"), _PERIOD_END)}
    assert [r[0] for r in a_after_a] == sorted(UUID(e) for e in a.employees)
    assert [(r[1], r[2], r[3]) for r in await _ledger(admin_engine, b)] == [
        ("ACCRUAL", Decimal("2.00"), _PERIOD_END)
    ]


async def test_service_with_mismatched_or_missing_tenant_context_writes_nothing(
    world: tuple[Tenant, Tenant], runtime_engine: AsyncEngine, admin_engine: AsyncEngine
) -> None:
    """The service is handed A's company id, but the session carries B's tenant (a context bug)
    or none at all: RLS must make that a no-op or an error, never a write."""
    a, b = world
    for context in (str(b.company_id), None):
        try:
            async with AsyncSession(runtime_engine, expire_on_commit=False) as session:
                if context is not None:
                    await session.execute(
                        text("SELECT set_config('app.company_id', :c, true)"), {"c": context}
                    )
                written = await LeaveAccrualService(session).run_for_company(
                    a.company_id, as_of=date(2026, 3, 1)
                )
                await session.commit()
            assert written == 0
        except Exception:  # noqa: BLE001 - failing closed with an error is equally acceptable
            pass
        assert await _ledger(admin_engine, a) == []
        assert await _ledger(admin_engine, b) == []


async def test_malformed_or_unknown_company_fails_safely_without_writes(
    world: tuple[Tenant, Tenant], app_as_runtime_role: Any, admin_engine: AsyncEngine
) -> None:
    a, b = world
    async with app_as_runtime_role():
        with pytest.raises(ValueError):
            await _run_task(leave_tasks.accrue_company, "not-a-uuid")
        with pytest.raises(Exception):  # noqa: B017, PT011 - no such company: any loud failure
            await _run_task(leave_tasks.accrue_company, str(uuid4()))
    assert await _ledger(admin_engine, a) == [] and await _ledger(admin_engine, b) == []


# --- duplicate delivery / retry / failure ------------


async def test_redelivered_task_does_not_double_accrue(
    world: tuple[Tenant, Tenant], app_as_runtime_role: Any, admin_engine: AsyncEngine
) -> None:
    a, _ = world
    async with app_as_runtime_role():
        assert await _run_task(leave_tasks.accrue_company, str(a.company_id)) == 2
        once = await _ledger(admin_engine, a)
        assert await _run_task(leave_tasks.accrue_company, str(a.company_id)) == 0
        assert await _run_task(leave_tasks.accrue_company, str(a.company_id)) == 0
    assert await _ledger(admin_engine, a) == once and len(once) == 2


async def test_concurrent_duplicate_deliveries_credit_once_for_the_runtime_role(
    world: tuple[Tenant, Tenant],
    runtime_engine: AsyncEngine,
    admin_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two workers racing past the "already written?" check (forced by making that check always
    say no) still write one row per employee: the partial unique index, as `hrms_app`."""
    a, _ = world
    from hrms.modules.leave.repository import LeaveLedgerRepository

    async def never_seen(self: Any, *_a: Any, **_k: Any) -> bool:
        return False

    monkeypatch.setattr(LeaveLedgerRepository, "exists_for_cycle", never_seen)

    async def one_worker() -> int:
        async with AsyncSession(runtime_engine, expire_on_commit=False) as session:
            await session.execute(
                text("SELECT set_config('app.company_id', :c, true)"), {"c": str(a.company_id)}
            )
            written = await LeaveAccrualService(session).run_for_company(
                a.company_id, as_of=date(2026, 3, 1)
            )
            await session.commit()
            return written

    results = await asyncio.gather(one_worker(), one_worker(), one_worker())
    assert sum(results) == 2, results  # one row per employee across all racers
    ledger = await _ledger(admin_engine, a)
    assert len(ledger) == 2 and {r[2] for r in ledger} == {Decimal("1.50")}


async def test_one_employee_failing_leaves_a_consistent_state_and_a_rerun_completes_it(
    world: tuple[Tenant, Tenant], app_as_runtime_role: Any, admin_engine: AsyncEngine
) -> None:
    a, _ = world
    original = LeaveAccrualService._accrue_employee_month
    victim = sorted(a.employees)[1]
    fail = {"on": True}

    async def flaky(
        self: LeaveAccrualService, company_id: UUID, employee_id: UUID, *args: Any, **kw: Any
    ) -> int:
        written = await original(self, company_id, employee_id, *args, **kw)
        if fail["on"] and str(employee_id) == victim:
            # the row was written inside this employee's savepoint; failing now must discard it
            raise RuntimeError("simulated mid-employee failure")
        return written

    async with app_as_runtime_role():
        with patch.object(LeaveAccrualService, "_accrue_employee_month", flaky):
            assert await _run_task(leave_tasks.accrue_company, str(a.company_id)) == 1
        partial = await _ledger(admin_engine, a)
        assert [str(r[0]) for r in partial] == [e for e in a.employees if e != victim]
        fail["on"] = False
        assert await _run_task(leave_tasks.accrue_company, str(a.company_id)) == 1  # only the gap
    final = await _ledger(admin_engine, a)
    assert len(final) == 2 and {str(r[0]) for r in final} == set(a.employees)
    assert {r[2] for r in final} == {Decimal("1.50")}


async def test_transient_db_error_after_writes_rolls_everything_back_and_the_retry_credits_once(
    world: tuple[Tenant, Tenant], app_as_runtime_role: Any, admin_engine: AsyncEngine
) -> None:
    a, _ = world
    original = _spy_original()
    calls = {"n": 0}
    snapshots: list[int] = []

    async def crash_after_work(self: LeaveAccrualService, company_id: UUID, *, as_of: date) -> int:
        calls["n"] += 1
        written = await original(self, company_id, as_of=as_of)
        if calls["n"] == 1:
            # the connection drops after the rows were written but before the commit
            snapshots.append(written)
            raise OperationalError("COMMIT", {}, Exception("connection lost"))
        return written

    async with app_as_runtime_role():
        with patch.object(LeaveAccrualService, "run_for_company", crash_after_work):
            # Eager `apply()` surfaces Celery's retry request instead of re-running the task:
            # `Retry` is the proof that `autoretry_for=(OperationalError, ...)` fired.
            with pytest.raises(Retry) as retried:
                await _run_task(leave_tasks.accrue_company, str(a.company_id))
            assert isinstance(retried.value.exc, OperationalError)
            # the failed attempt wrote two rows and then died before COMMIT: none may persist
            assert snapshots == [2]
            assert await _ledger(admin_engine, a) == []
            # the retry / a redelivery (what the broker does for a late-acked, lost message)
            assert await _run_task(leave_tasks.accrue_company, str(a.company_id)) == 2
    assert calls["n"] == 2
    ledger = await _ledger(admin_engine, a)
    assert len(ledger) == 2 and {r[2] for r in ledger} == {Decimal("1.50")}  # not 4 rows


# --- fan-out ------------


async def test_fanout_lists_companies_without_tenant_context_under_the_runtime_role(
    world: tuple[Tenant, Tenant],
    app_as_runtime_role: Any,
    runtime_engine: AsyncEngine,
) -> None:
    a, b = world
    queued: list[str] = []

    def capture(task: Any, company_ids: list[UUID], *args: Any) -> int:
        queued.extend(str(c) for c in company_ids)
        return len(company_ids)

    async with app_as_runtime_role():
        with patch.object(leave_tasks, "_dispatch", capture):
            await _run_task(leave_tasks.run_monthly_accrual)
    assert {str(a.company_id), str(b.company_id)} <= set(queued)
    # `company` is deliberately not row-level-secured: the global listing needs no tenant, and
    # this pins that assumption so enabling RLS there would fail loudly here, not silently stop
    # every scheduled fan-out.
    async with runtime_engine.connect() as conn:
        rls = (
            await conn.execute(
                text("SELECT relrowsecurity FROM pg_class WHERE relname = 'company'")
            )
        ).scalar_one()
    assert rls is False


# --- cleanup ------------


async def test_teardown_leaves_no_leave_rows_behind(
    client: AsyncClient, seeded_plan_catalogue: None, admin_engine: AsyncEngine
) -> None:
    tenant = await _provision(client, employees=1, rate="1.50")
    await _teardown(company_id=tenant.company_id)
    await _cleanup(company_id=tenant.company_id, user_id=tenant.user_id)
    async with admin_engine.connect() as conn:
        for table, column in (
            ("leave_ledger", "company_id"),
            ("employee", "company_id"),
            ("company", "id"),
        ):
            left = (
                await conn.execute(
                    text(f"SELECT count(*) FROM {table} WHERE {column} = :c"),  # noqa: S608
                    {"c": str(tenant.company_id)},
                )
            ).scalar_one()
            assert left == 0, table
