"""Stage 5 of the P1 remediation: the pay-run lifecycle under the real runtime role (`hrms_app`).

Selected workflow (and why): create -> lock-inputs -> compute -> approve -> finalise -> mark-paid of
a pay run, with the payslip / bank-advice / compensation reads that hang off it. It crosses the
tables that matter for payroll tenant isolation - `pay_run`, `pay_run_employee`, `pay_run_line`
(all `company_id` + FORCE RLS) plus the employee-linked compensation tables - and carries the
financial invariants (run totals are the sum of the employee rows; net = gross - deductions) and
the ADR-0005 rule that a FINALISED / PAID run never changes. Expectations come from the existing
behaviour pinned by `test_pay_run.py`, `test_payslip.py` and `test_b05_db_immutability.py`; nothing
new is invented.

Roles: tenant registration, the legal entity / employee / closed-period graph and teardown run on
the admin side (the suite's default engine, like every other payroll test). Every operation under
test runs inside `app_as_runtime_role()` (the app's own engine as `hrms_app`, role attributes
asserted by `tests/rls_support.py`). Independent snapshots use the admin engine.

Not covered here (existing coverage / out of the single selected workflow): statutory rates,
arrears and adjustments (`test_arrears.py`, `test_b04_*`), trigger-level immutability of every
child table (`test_b05_db_immutability.py`).
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine
from tests import rls_support
from tests.integration.modules.attendance.test_attendance_day import _register_tenant
from tests.integration.modules.attendance.test_attendance_security import _cleanup_scoped_users
from tests.integration.modules.organisation.test_registration_flow import _cleanup
from tests.integration.modules.payroll.test_arrears import _finalised_run
from tests.integration.modules.payroll.test_pay_run import (
    _action,
    _approver,
    _cleanup_pay_runs,
    _closed_period,
    _create_run,
    _employee,
    _legal_entity,
)

pytestmark = pytest.mark.asyncio

_RUN_COLUMNS = (
    "id, status, version, employee_count, gross_minor, deductions_minor, "
    "employer_contributions_minor, net_minor, paid_at, finalised_at"
)


@dataclass
class Tenant:
    headers: dict[str, str]
    approver: dict[str, str]
    company_id: UUID
    user_id: UUID | None
    le: str
    employee: str
    aug_run: dict[str, Any]  # FINALISED
    sep_run: dict[str, Any]  # A: DRAFT (lifecycle subject); B: COMPUTED (mutation target)

    @property
    def token_only(self) -> dict[str, str]:
        return {"Authorization": self.headers["Authorization"]}


async def _provision(client: AsyncClient, *, name: str, ctc: int, sep_state: str) -> Tenant:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        le = await _legal_entity(client, headers)
        employee = await _employee(client, headers, le, name=name, ctc=ctc)
        approver = await _approver(company_id)
        aug = await _finalised_run(
            client, headers, approver, company_id=company_id, legal_entity_id=le,
            month="2026-08", paid_days={employee: "31"},
        )  # fmt: skip
        await _closed_period(
            company_id=company_id, legal_entity_id=le, start="2026-09-01", end="2026-09-30",
            paid_days={employee: "30"}, days_in_month=30,
        )  # fmt: skip
        sep = await _create_run(client, headers, le, "2026-09")
        if sep_state == "COMPUTED":
            sep = await _action(client, headers, sep, "lock-inputs")
            sep = await _action(client, headers, sep, "compute")
    except BaseException:
        await _teardown(company_id, user_id)
        await _cleanup_scoped_users()
        raise
    return Tenant(headers, approver, company_id, user_id, le, employee, aug, sep)


async def _teardown(company_id: UUID, user_id: UUID | None) -> None:
    """Per tenant. `_cleanup_scoped_users` is global (every `scoped-%` user), so it runs once after
    all tenants are gone - earlier it would hit another tenant's still-linked approver."""
    await _cleanup_pay_runs(company_id=company_id)
    await _cleanup(company_id=company_id, user_id=user_id)


@pytest.fixture
async def world(
    client: AsyncClient, seeded_plan_catalogue: None
) -> AsyncIterator[tuple[Tenant, Tenant]]:
    """Two fully provisioned tenants with different salaries; teardown in `finally`."""
    made: list[Tenant] = []
    try:
        made.append(await _provision(client, name="Asha", ctc=7_20_000_00, sep_state="DRAFT"))
        made.append(await _provision(client, name="Bhavna", ctc=12_00_000_00, sep_state="COMPUTED"))
        yield made[0], made[1]
    finally:
        for tenant in reversed(made):
            await _teardown(tenant.company_id, tenant.user_id)
        await _cleanup_scoped_users()


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


async def _db_state(admin_engine: AsyncEngine, tenant: Tenant) -> dict[str, Any]:
    """Admin-role (RLS-exempt) snapshot of everything pay-run related for one tenant."""
    cid = {"c": str(tenant.company_id)}
    async with admin_engine.connect() as conn:
        runs = (
            await conn.execute(
                text(f"SELECT {_RUN_COLUMNS} FROM pay_run WHERE company_id = :c ORDER BY id"),  # noqa: S608
                cid,
            )
        ).all()
        employees = (
            await conn.execute(
                text(
                    "SELECT id, pay_run_id, gross_minor, deductions_minor, net_minor, "
                    "variance_acknowledged_at FROM pay_run_employee WHERE company_id = :c "
                    "ORDER BY id"
                ),
                cid,
            )
        ).all()
        lines = (
            await conn.execute(
                text(
                    "SELECT id, line_type, amount_minor FROM pay_run_line "
                    "WHERE company_id = :c ORDER BY id"
                ),
                cid,
            )
        ).all()
    return {
        "runs": [tuple(r) for r in runs],
        "employees": [tuple(r) for r in employees],
        "lines": [tuple(r) for r in lines],
    }


async def _assert_totals_consistent(admin_engine: AsyncEngine, tenant: Tenant) -> None:
    """Invariants taken from the engine: net = gross - deductions per employee (D8: no rounding),
    each employee's totals are the sums of their lines by type, and a run's totals are the sums of
    its employee rows. Checked on the admin side so the application cannot vouch for itself."""
    async with admin_engine.connect() as conn:
        bad_employee = (
            await conn.execute(
                text(
                    """
                    SELECT e.id FROM pay_run_employee e
                    WHERE e.company_id = :c AND e.is_computed AND (
                      e.net_minor <> e.gross_minor - e.deductions_minor
                      OR e.gross_minor <> COALESCE((SELECT sum(l.amount_minor) FROM pay_run_line l
                          WHERE l.pay_run_employee_id = e.id AND l.line_type = 'EARNING'), 0)
                      OR e.deductions_minor <> COALESCE((SELECT sum(l.amount_minor)
                          FROM pay_run_line l WHERE l.pay_run_employee_id = e.id
                          AND l.line_type = 'DEDUCTION'), 0)
                    )
                    """
                ),
                {"c": str(tenant.company_id)},
            )
        ).all()
        bad_run = (
            await conn.execute(
                text(
                    """
                    SELECT r.id FROM pay_run r
                    WHERE r.company_id = :c AND r.status IN
                          ('COMPUTED', 'APPROVED', 'FINALISED', 'PAID') AND (
                      r.gross_minor <> COALESCE((SELECT sum(gross_minor) FROM pay_run_employee
                          WHERE pay_run_id = r.id), 0)
                      OR r.deductions_minor <> COALESCE((SELECT sum(deductions_minor)
                          FROM pay_run_employee WHERE pay_run_id = r.id), 0)
                      OR r.net_minor <> COALESCE((SELECT sum(net_minor) FROM pay_run_employee
                          WHERE pay_run_id = r.id), 0)
                      OR r.employee_count <> (SELECT count(*) FROM pay_run_employee
                          WHERE pay_run_id = r.id)
                    )
                    """
                ),
                {"c": str(tenant.company_id)},
            )
        ).all()
    assert bad_employee == [] and bad_run == [], (bad_employee, bad_run)


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
        listed = await client.get("/v1/payroll/pay-runs", headers=a.headers)
        assert listed.status_code == 200, listed.text
        async with admin_engine.connect() as conn:
            created = {row.usename for row in await conn.execute(backends) if row.pid not in before}
    assert created == {runtime_user}, created


# --- 1 + 6: the intended operation and financial invariants ------------


async def test_pay_run_lifecycle_under_runtime_role_keeps_totals_consistent(
    client: AsyncClient,
    world: tuple[Tenant, Tenant],
    app_as_runtime_role: Any,
    admin_engine: AsyncEngine,
) -> None:
    a, b = world
    b_before = await _db_state(admin_engine, b)
    async with app_as_runtime_role():
        run = await _action(client, a.headers, a.sep_run, "lock-inputs")
        assert run["status"] == "INPUTS_LOCKED" and run["employee_count"] == 1
        run = await _action(client, a.headers, run, "compute")
        assert run["status"] == "COMPUTED" and run["error_count"] == 0
        # Same salary and a fully paid month as August: monthly CTC 60,000.
        assert run["gross_minor"] == run["net_minor"] == 6_000_000 and run["deductions_minor"] == 0
        await _assert_totals_consistent(admin_engine, a)

        # D9 - the user who computed cannot approve.
        maker = await _action(client, a.headers, run, "approve", expect=403)
        assert maker["code"] == "PAY_RUN_MAKER_CHECKER"
        run = await _action(client, a.approver, run, "approve")
        assert run["status"] == "APPROVED"
        run = await _action(client, a.approver, run, "finalise")
        assert run["status"] == "FINALISED"
        run = await _action(client, a.approver, run, "mark-paid")
        assert run["status"] == "PAID" and run["paid_by_user_id"] is not None
        assert run["net_minor"] == 6_000_000

        # Employee-linked reads for the tenant's own run.
        payslip = await client.get(
            f"/v1/payroll/pay-runs/{run['id']}/employees/{a.employee}/payslip", headers=a.headers
        )
        assert payslip.status_code == 200, payslip.text
        assert payslip.json()["data"]["net_minor"] == 6_000_000
        assert payslip.json()["data"]["is_final"] is True
        advice = await client.get(
            f"/v1/payroll/pay-runs/{run['id']}/bank-advice", headers=a.headers
        )
        assert advice.status_code == 200 and "60000.00" in advice.text, advice.text
    await _assert_totals_consistent(admin_engine, a)
    assert await _db_state(admin_engine, b) == b_before  # A's lifecycle never touched B


async def test_rejected_operations_leave_pay_run_state_and_totals_untouched(
    client: AsyncClient,
    world: tuple[Tenant, Tenant],
    app_as_runtime_role: Any,
    admin_engine: AsyncEngine,
) -> None:
    a, _ = world
    before = await _db_state(admin_engine, a)
    async with app_as_runtime_role():
        duplicate = await client.post(
            "/v1/payroll/pay-runs",
            headers=a.headers,
            json={"legal_entity_id": a.le, "month": "2026-09"},
        )
        assert duplicate.status_code == 409, duplicate.text
        assert duplicate.json()["error"]["code"] == "PAY_RUN_ALREADY_EXISTS"
        # A processor-only approver cannot create runs.
        forbidden = await client.post(
            "/v1/payroll/pay-runs",
            headers=a.approver,
            json={"legal_entity_id": a.le, "month": "2026-10"},
        )
        assert forbidden.status_code == 403, forbidden.text
        # Compute before the inputs are locked, approve a DRAFT, roll a FINALISED run back.
        too_early = await _action(client, a.headers, a.sep_run, "compute", expect=409)
        assert too_early["code"].startswith("PAY_RUN"), too_early
        await _action(client, a.approver, a.sep_run, "approve", expect=409)
        refused = await _action(
            client, a.headers, a.aug_run, "rollback", expect=409,
            json={"to_status": "DRAFT", "reason": "too late"},
        )  # fmt: skip
        assert refused["code"] == "PAY_RUN_INVALID_TRANSITION"
        # Stale If-Match.
        stale = await client.post(
            f"/v1/payroll/pay-runs/{a.sep_run['id']}/lock-inputs",
            headers={**a.headers, "If-Match": "999"},
        )
        assert stale.status_code in {409, 412}, stale.text
    assert await _db_state(admin_engine, a) == before
    await _assert_totals_consistent(admin_engine, a)


# --- 2: cross-tenant reads ------------


async def test_tenant_a_cannot_read_tenant_b_payroll_data(
    client: AsyncClient,
    world: tuple[Tenant, Tenant],
    app_as_runtime_role: Any,
    admin_engine: AsyncEngine,
    runtime_engine: AsyncEngine,
) -> None:
    a, b = world
    # Positive control: B's rows do exist (admin side), so "none visible" below means RLS.
    b_state = await _db_state(admin_engine, b)
    assert len(b_state["runs"]) == 2 and b_state["employees"] and b_state["lines"]
    b_run_ids = {b.aug_run["id"], b.sep_run["id"]}
    async with app_as_runtime_role():
        mine = await client.get("/v1/payroll/pay-runs", headers=a.headers)
        assert mine.status_code == 200, mine.text
        assert {a.aug_run["id"], a.sep_run["id"]} <= _ids(mine.json())
        assert not b_run_ids & _ids(mine.json())
        assert b.le not in mine.text

        for run_id in b_run_ids:
            for path in (
                f"/v1/payroll/pay-runs/{run_id}",
                f"/v1/payroll/pay-runs/{run_id}/employees",
                f"/v1/payroll/pay-runs/{run_id}/employees/{b.employee}",
                f"/v1/payroll/pay-runs/{run_id}/employees/{b.employee}/payslip",
                f"/v1/payroll/pay-runs/{run_id}/bank-advice",
                f"/v1/me/payslips/{run_id}",
            ):
                direct = await client.get(path, headers=a.headers)
                assert direct.status_code in {403, 404}, (path, direct.text)
                assert b.employee not in direct.text and "Bhavna" not in direct.text, path
        # A's own run id with B's employee: no B payslip / compensation comes back.
        crossed = await client.get(
            f"/v1/payroll/pay-runs/{a.aug_run['id']}/employees/{b.employee}/payslip",
            headers=a.headers,
        )
        assert crossed.status_code in {403, 404}, crossed.text
        assert "Bhavna" not in crossed.text

        for path in (
            f"/v1/employees/{b.employee}/salary",
            f"/v1/employees/{b.employee}/salary/breakup",
            f"/v1/employees/{b.employee}/compensation",
        ):
            comp = await client.get(path, headers=a.headers)
            assert comp.status_code in {200, 403, 404}, (path, comp.text)
            assert "Bhavna" not in comp.text and "12000000" not in comp.text, path
            if comp.status_code == 200:
                assert comp.json()["data"] in ([], None) or b.employee not in comp.text, (
                    path,
                    comp.text,
                )

    # Database level: under A's tenant the database itself shows none of B's rows.
    async with runtime_engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('app.company_id', :c, true)"), {"c": str(a.company_id)}
        )
        foreign = {}
        for table in ("pay_run", "pay_run_employee", "pay_run_line", "employee_salary"):
            foreign[table] = (
                await conn.execute(
                    text(f"SELECT count(*) FROM {table} WHERE company_id = :b"),  # noqa: S608
                    {"b": str(b.company_id)},
                )
            ).scalar_one()
        own_runs = (await conn.execute(text("SELECT count(*) FROM pay_run"))).scalar_one()
    assert foreign == {"pay_run": 0, "pay_run_employee": 0, "pay_run_line": 0, "employee_salary": 0}
    assert own_runs == 2


# --- 3: cross-tenant mutations ------------


async def test_tenant_a_cannot_mutate_tenant_b_pay_runs(
    client: AsyncClient,
    world: tuple[Tenant, Tenant],
    app_as_runtime_role: Any,
    admin_engine: AsyncEngine,
    runtime_engine: AsyncEngine,
) -> None:
    a, b = world
    before_b = await _db_state(admin_engine, b)
    assert b.sep_run["status"] == "COMPUTED"
    async with app_as_runtime_role():
        # B's COMPUTED run would genuinely accept these if tenant scoping failed (A's approver is
        # a different user from the one who computed, so maker-checker would not stop approve).
        for actor in (a.headers, a.approver):
            for action, body in (
                ("lock-inputs", None),
                ("compute", None),
                ("approve", None),
                ("finalise", None),
                ("mark-paid", None),
                ("rollback", {"to_status": "DRAFT", "reason": "x"}),
            ):
                response = await client.post(
                    f"/v1/payroll/pay-runs/{b.sep_run['id']}/{action}",
                    headers={**actor, "If-Match": str(b.sep_run["version"])},
                    json=body,
                )
                assert response.status_code in {403, 404}, (action, response.text)
        patched = await client.patch(
            f"/v1/payroll/pay-runs/{b.sep_run['id']}",
            headers={**a.headers, "If-Match": str(b.sep_run["version"])},
            json={"pay_date": "2026-10-05"},
        )
        assert patched.status_code in {403, 404}, patched.text
        deleted = await client.delete(
            f"/v1/payroll/pay-runs/{b.sep_run['id']}",
            headers={**a.headers, "If-Match": str(b.sep_run["version"])},
        )
        assert deleted.status_code in {403, 404}, deleted.text
        # Acting on B's finalised run, and creating a run for B's legal entity.
        finalised = await client.post(
            f"/v1/payroll/pay-runs/{b.aug_run['id']}/mark-paid",
            headers={**a.approver, "If-Match": str(b.aug_run["version"])},
        )
        assert finalised.status_code in {403, 404}, finalised.text
        foreign_create = await client.post(
            "/v1/payroll/pay-runs",
            headers=a.headers,
            json={"legal_entity_id": b.le, "month": "2026-10"},
        )
        assert foreign_create.status_code in {403, 404, 422}, foreign_create.text

    async def as_tenant_a(sql: str) -> int:
        async with runtime_engine.begin() as conn:
            await conn.execute(
                text("SELECT set_config('app.company_id', :c, true)"), {"c": str(a.company_id)}
            )
            return (await conn.execute(text(sql), {"b": str(b.company_id)})).rowcount

    # RLS: UPDATE / DELETE as A match none of B's rows (computed run included).
    assert await as_tenant_a("UPDATE pay_run SET net_minor = 1 WHERE company_id = :b") == 0
    assert await as_tenant_a("DELETE FROM pay_run WHERE company_id = :b") == 0
    assert await as_tenant_a("UPDATE pay_run_employee SET net_minor = 1 WHERE company_id = :b") == 0
    assert await as_tenant_a("DELETE FROM pay_run_line WHERE company_id = :b") == 0
    # WITH CHECK: A cannot write a row that claims B's company.
    with pytest.raises(DBAPIError) as forged:
        async with runtime_engine.begin() as conn:
            await conn.execute(
                text("SELECT set_config('app.company_id', :c, true)"), {"c": str(a.company_id)}
            )
            await conn.execute(
                text("UPDATE pay_run SET company_id = :b WHERE company_id = :a"),
                {"a": str(a.company_id), "b": str(b.company_id)},
            )
    assert "row-level security" in str(forged.value) or "RestrictViolation" in str(forged.value)

    assert await _db_state(admin_engine, b) == before_b
    await _assert_totals_consistent(admin_engine, b)


# --- 4: missing / invalid tenant context ------------


async def test_missing_or_invalid_tenant_context_fails_closed(
    client: AsyncClient, world: tuple[Tenant, Tenant], app_as_runtime_role: Any
) -> None:
    a, b = world
    path = "/v1/payroll/pay-runs"
    async with app_as_runtime_role():
        anonymous = await client.get(path, headers={"X-Company-Id": str(b.company_id)})
        assert anonymous.status_code == 401, anonymous.text
        for value in (str(b.company_id), "not-a-uuid", ""):
            spoofed = await client.get(path, headers={**a.token_only, "X-Company-Id": value})
            assert spoofed.status_code == 404, (value, spoofed.text)
            assert not {a.aug_run["id"], b.aug_run["id"]} & _ids(spoofed.json())
        spoofed_write = await client.post(
            f"/v1/payroll/pay-runs/{b.sep_run['id']}/compute",
            headers={**a.token_only, "X-Company-Id": str(b.company_id), "If-Match": "1"},
        )
        assert spoofed_write.status_code in {403, 404}, spoofed_write.text
        # The documented token-only form works and is scoped to the token's tenant.
        token_only = await client.get(path, headers=a.token_only)
        assert token_only.status_code == 200, token_only.text
        assert a.aug_run["id"] in _ids(token_only.json())
        assert b.aug_run["id"] not in _ids(token_only.json())


async def test_runtime_role_without_tenant_context_sees_no_payroll_rows(
    world: tuple[Tenant, Tenant], runtime_engine: AsyncEngine
) -> None:
    async with runtime_engine.connect() as conn:
        for table in ("pay_run", "pay_run_employee", "pay_run_line"):
            assert (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one() == 0  # noqa: S608
    async with runtime_engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('app.company_id', :c, true)"), {"c": str(uuid4())}
        )
        assert (await conn.execute(text("SELECT count(*) FROM pay_run"))).scalar_one() == 0


# --- 5: pooled connections ------------


async def test_alternating_tenants_over_pooled_connections_never_leak_context(
    client: AsyncClient, world: tuple[Tenant, Tenant], app_as_runtime_role: Any
) -> None:
    a, b = world
    async with app_as_runtime_role():
        for i in range(14):
            own, other = (a, b) if i % 2 == 0 else (b, a)
            listed = await client.get("/v1/payroll/pay-runs", headers=own.headers)
            assert listed.status_code == 200, (i, listed.text)
            assert own.aug_run["id"] in _ids(listed.json())
            assert other.aug_run["id"] not in _ids(listed.json())
            detail = await client.get(
                f"/v1/payroll/pay-runs/{own.aug_run['id']}/employees/{own.employee}",
                headers=own.headers,
            )
            assert detail.status_code == 200, (i, detail.text)
            foreign = await client.get(
                f"/v1/payroll/pay-runs/{other.aug_run['id']}", headers=own.headers
            )
            assert foreign.status_code == 404, (i, foreign.text)


# --- 7: finalised runs stay immutable ------------


async def test_finalised_run_stays_immutable_for_the_runtime_role(
    client: AsyncClient,
    world: tuple[Tenant, Tenant],
    app_as_runtime_role: Any,
    admin_engine: AsyncEngine,
    runtime_engine: AsyncEngine,
) -> None:
    a, _ = world
    before = await _db_state(admin_engine, a)
    async with app_as_runtime_role():
        for action, body in (
            ("compute", None),
            ("lock-inputs", None),
            ("approve", None),
            ("rollback", {"to_status": "INPUTS_LOCKED", "reason": "x"}),
        ):
            response = await client.post(
                f"/v1/payroll/pay-runs/{a.aug_run['id']}/{action}",
                headers={**a.approver, "If-Match": str(a.aug_run["version"])},
                json=body,
            )
            assert response.status_code in {403, 409}, (action, response.text)
        patched = await client.patch(
            f"/v1/payroll/pay-runs/{a.aug_run['id']}",
            headers={**a.headers, "If-Match": str(a.aug_run["version"])},
            json={"pay_date": "2026-10-05"},
        )
        assert patched.status_code == 409, patched.text
        deleted = await client.delete(
            f"/v1/payroll/pay-runs/{a.aug_run['id']}",
            headers={**a.headers, "If-Match": str(a.aug_run["version"])},
        )
        assert deleted.status_code in {403, 409}, deleted.text

    # Underneath the API: the database refuses direct writes to the finalised rows, even inside
    # the owning tenant's own RLS context (trigger from migration 20261013090000).
    for sql in (
        "UPDATE pay_run SET net_minor = 1 WHERE id = :id",
        "DELETE FROM pay_run WHERE id = :id",
    ):
        with pytest.raises(DBAPIError) as blocked:
            async with runtime_engine.begin() as conn:
                await conn.execute(
                    text("SELECT set_config('app.company_id', :c, true)"),
                    {"c": str(a.company_id)},
                )
                await conn.execute(text(sql), {"id": a.aug_run["id"]})
        assert "RestrictViolationError" in str(blocked.value.orig), sql
    assert await _db_state(admin_engine, a) == before
    await _assert_totals_consistent(admin_engine, a)


# --- 8: isolation of setup / teardown ------------


async def test_teardown_leaves_no_payroll_rows_behind(
    client: AsyncClient, seeded_plan_catalogue: None, admin_engine: AsyncEngine
) -> None:
    tenant = await _provision(client, name="Temp", ctc=7_20_000_00, sep_state="DRAFT")
    await _teardown(tenant.company_id, tenant.user_id)
    await _cleanup_scoped_users()
    async with admin_engine.connect() as conn:
        for table in ("pay_run", "pay_run_employee", "pay_run_line", "employee_salary", "company"):
            column = "id" if table == "company" else "company_id"
            left = (
                await conn.execute(
                    text(f"SELECT count(*) FROM {table} WHERE {column} = :c"),  # noqa: S608
                    {"c": str(tenant.company_id)},
                )
            ).scalar_one()
            assert left == 0, table
