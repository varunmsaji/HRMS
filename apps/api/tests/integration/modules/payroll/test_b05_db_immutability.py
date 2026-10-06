"""PAY-B05 — a FINALISED / PAID pay run is immutable in the database, for the runtime role.

Migration `20261013090000` adds row triggers on `pay_run`, `pay_run_employee`, `pay_run_line`,
`pay_run_arrear` and `pay_adjustment`. The tests build a real paid run, a finalised run that paid
an arrear, and a draft run through the API (as the schema owner, like every other test), then:

* attack the finalised rows over a raw connection as `hrms_app` — the runtime role, which still
  holds blanket UPDATE/DELETE — and expect the *database* to refuse;
* run the whole normal lifecycle (create, lock, compute, recompute, approve, finalise, pay, roll
  back, delete a draft, correct a paid month and pay it as arrears) through the HTTP API with the
  app engine repointed at `hrms_app`, proving the guard does not get in the way of real work;
* check tenant isolation still holds with the triggers in place.

The schema owner is exempt by design (tenant erasure / retention / test teardown), which is also
what lets this module's own cleanup remove finalised runs."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
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

from hrms.core.config.settings import get_settings
from hrms.core.db.session import dispose_engine

pytestmark = pytest.mark.asyncio

_APP_USER, _APP_PASSWORD = "hrms_app", "hrms_app_dev_password"


def _runtime_url(driver: str) -> str:
    url = make_url(os.environ["DATABASE_URL"]).set(
        drivername=driver, username=_APP_USER, password=_APP_PASSWORD
    )
    return url.render_as_string(hide_password=False)


@asynccontextmanager
async def _runtime_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(_runtime_url("postgresql+asyncpg"))
    try:
        yield engine
    finally:
        await engine.dispose()


@asynccontextmanager
async def _app_as_runtime_role(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    """The application's own engine connects as `hrms_app` for the block."""
    original = os.environ["DATABASE_URL"]
    monkeypatch.setenv("DATABASE_URL", _runtime_url("postgresql"))
    get_settings.cache_clear()
    await dispose_engine()
    try:
        yield
    finally:
        monkeypatch.setenv("DATABASE_URL", original)
        get_settings.cache_clear()
        await dispose_engine()


async def _as_app(company_id: UUID, sql: str, **params: Any) -> int:
    """One statement as `hrms_app` inside the tenant's RLS context, in its own transaction.
    Returns the row count; the transaction is rolled back, so an attack that succeeded is not
    left behind to confuse the next check."""
    async with _runtime_engine() as engine, engine.connect() as conn:
        trans = await conn.begin()
        try:
            await conn.execute(
                text("SELECT set_config('app.company_id', :c, true)"), {"c": str(company_id)}
            )
            result = await conn.execute(text(sql), params)
            return int(result.rowcount)
        finally:
            await trans.rollback()


async def _blocked(company_id: UUID, sql: str, **params: Any) -> str:
    with pytest.raises(DBAPIError) as raised:
        await _as_app(company_id, sql, **params)
    message = str(raised.value.orig)
    # SQLSTATE 23001 is what the guard raises — not a syntax, permission or constraint error
    assert "RestrictViolationError" in message, message
    return message


async def _admin_scalar(sql: str, **params: Any) -> Any:
    from hrms.core.db.session import get_session_factory

    async with get_session_factory()() as session:
        return (await session.execute(text(sql), params)).scalar()


class _World:
    company_id: UUID
    headers: dict[str, str]
    approver: dict[str, str]
    le: str
    employee: str
    paid_run: dict[str, Any]  # Aug: finalised, corrected, then marked PAID
    final_run: dict[str, Any]  # Sep: FINALISED, pays the Aug correction as arrears
    draft_run: dict[str, Any]  # Oct: DRAFT
    adjustment_id: str


@asynccontextmanager
async def _world(client: AsyncClient) -> AsyncIterator[_World]:
    w = _World()
    w.headers, w.company_id, user_id = await _register_tenant(client)
    try:
        w.le = await _legal_entity(client, w.headers)
        w.employee = await _employee(client, w.headers, w.le)
        w.approver = await _approver(w.company_id)
        aug = await _finalised_run(
            client, w.headers, w.approver, company_id=w.company_id, legal_entity_id=w.le,
            month="2026-08", paid_days={w.employee: "30"},
        )  # fmt: skip
        correction = await client.post(
            "/v1/payroll/adjustments",
            headers=w.headers,
            json={
                "source_pay_run_id": aug["id"],
                "employee_id": w.employee,
                "paid_days_delta": "-1",
                "reason": "Unauthorised absence found later",
            },
        )
        assert correction.status_code == 201, correction.text
        w.adjustment_id = correction.json()["data"]["id"]
        w.final_run = await _finalised_run(
            client, w.headers, w.approver, company_id=w.company_id, legal_entity_id=w.le,
            month="2026-09", paid_days={w.employee: "30"},
        )  # fmt: skip
        w.paid_run = await _action(client, w.approver, aug, "mark-paid")
        await _closed_period(
            company_id=w.company_id, legal_entity_id=w.le, start="2026-10-01", end="2026-10-31",
            paid_days={w.employee: "31"}, days_in_month=31,
        )  # fmt: skip
        w.draft_run = await _create_run(client, w.headers, w.le, "2026-10")
        yield w
    finally:
        await _cleanup_pay_runs(company_id=w.company_id)
        await _cleanup(company_id=w.company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_world_is_what_the_attacks_assume(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    async with _world(client) as w:
        status = "SELECT status FROM pay_run WHERE id = :id"
        assert await _admin_scalar(status, id=w.paid_run["id"]) == "PAID"
        assert await _admin_scalar(status, id=w.final_run["id"]) == "FINALISED"
        assert await _admin_scalar(status, id=w.draft_run["id"]) == "DRAFT"
        assert (
            await _admin_scalar(
                "SELECT status FROM pay_adjustment WHERE id = :id", id=w.adjustment_id
            )
            == "APPLIED"
        )
        assert (
            await _admin_scalar(
                "SELECT count(*) FROM pay_run_arrear WHERE pay_run_id = :id", id=w.final_run["id"]
            )
            > 0
        )


async def test_runtime_role_cannot_change_a_finalised_or_paid_run(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    async with _world(client) as w:
        for run in (w.final_run, w.paid_run):
            rid = run["id"]
            await _blocked(w.company_id, "UPDATE pay_run SET net_minor = 1 WHERE id = :id", id=rid)
            await _blocked(
                w.company_id, "UPDATE pay_run SET status = 'DRAFT' WHERE id = :id", id=rid
            )
            await _blocked(w.company_id, "DELETE FROM pay_run WHERE id = :id", id=rid)
            await _blocked(
                w.company_id,
                "UPDATE pay_run SET status='APPROVED', version=version+1 WHERE id = :id",
                id=rid,
            )
        # PAID is final: not even the paid stamp may be rewritten.
        await _blocked(
            w.company_id, "UPDATE pay_run SET paid_at = now() WHERE id = :id", id=w.paid_run["id"]
        )
        # FINALISED -> PAID may stamp only the paid columns, never slip a financial change in.
        await _blocked(
            w.company_id,
            "UPDATE pay_run SET status='PAID', paid_at=now(), net_minor=net_minor+1 WHERE id=:id",
            id=w.final_run["id"],
        )
        # nothing becomes PAID without being FINALISED, and no run is created final
        await _blocked(
            w.company_id,
            "UPDATE pay_run SET status='PAID', paid_at=now() WHERE id = :id",
            id=w.draft_run["id"],
        )
        await _blocked(
            w.company_id,
            """INSERT INTO pay_run
               SELECT (jsonb_populate_record(null::pay_run, to_jsonb(p) || jsonb_build_object(
                 'id', gen_random_uuid()::text, 'period_month', '2030-01-01',
                 'status', 'FINALISED'))).*
               FROM pay_run p WHERE p.id = :id""",
            id=w.final_run["id"],
        )


async def test_runtime_role_cannot_change_the_payslip_data_of_a_final_run(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    async with _world(client) as w:
        for run in (w.final_run, w.paid_run):
            rid = run["id"]
            await _blocked(
                w.company_id,
                "UPDATE pay_run_employee SET net_minor = net_minor + 100 WHERE pay_run_id = :id",
                id=rid,
            )
            await _blocked(
                w.company_id,
                "UPDATE pay_run_employee SET payslip_details = '{}'::jsonb WHERE pay_run_id = :id",
                id=rid,
            )
            await _blocked(
                w.company_id, "DELETE FROM pay_run_employee WHERE pay_run_id=:id", id=rid
            )
            await _blocked(
                w.company_id,
                "UPDATE pay_run_line SET amount_minor = amount_minor + 100 WHERE pay_run_id = :id",
                id=rid,
            )
            await _blocked(w.company_id, "DELETE FROM pay_run_line WHERE pay_run_id = :id", id=rid)
            await _blocked(
                w.company_id,
                """INSERT INTO pay_run_line (id, company_id, pay_run_id, pay_run_employee_id,
                     employee_id, component_code, component_name, line_type, full_monthly_minor,
                     amount_minor, display_order, trace, created_at)
                   SELECT gen_random_uuid(), company_id, pay_run_id, pay_run_employee_id,
                     employee_id, 'EXTRA', 'Extra', 'EARNING', NULL, 99900, 1, '{}'::jsonb, now()
                   FROM pay_run_line WHERE pay_run_id = :id LIMIT 1""",
                id=rid,
            )
            await _blocked(
                w.company_id,
                """INSERT INTO pay_run_employee
                   SELECT (jsonb_populate_record(null::pay_run_employee, to_jsonb(e)
                     || jsonb_build_object('id', gen_random_uuid()::text))).*
                   FROM pay_run_employee e WHERE e.pay_run_id = :id LIMIT 1""",
                id=rid,
            )
        # a row cannot be moved out of a final run into a draft one either
        await _blocked(
            w.company_id,
            "UPDATE pay_run_line SET pay_run_id = :draft WHERE pay_run_id = :id",
            id=w.final_run["id"],
            draft=w.draft_run["id"],
        )
        # arrears recorded on the run that paid them
        await _blocked(
            w.company_id,
            "UPDATE pay_run_arrear SET amount_minor = amount_minor + 1 WHERE pay_run_id = :id",
            id=w.final_run["id"],
        )
        await _blocked(
            w.company_id,
            "UPDATE pay_run_arrear SET applied_at = NULL WHERE pay_run_id = :id",
            id=w.final_run["id"],
        )
        await _blocked(
            w.company_id, "DELETE FROM pay_run_arrear WHERE pay_run_id = :id", id=w.final_run["id"]
        )
        await _blocked(
            w.company_id,
            """INSERT INTO pay_run_arrear (id, company_id, pay_run_id, employee_id, for_month,
                 source_pay_run_id, component_code, line_type, amount_minor, created_at,
                 payment_number, applied_at)
               SELECT gen_random_uuid(), company_id, pay_run_id, employee_id, for_month,
                 source_pay_run_id, 'EXTRA', line_type, 1, now(), 99, now()
               FROM pay_run_arrear WHERE pay_run_id = :id LIMIT 1""",
            id=w.final_run["id"],
        )


async def test_runtime_role_cannot_change_an_applied_correction_but_can_withdraw_a_pending_one(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    async with _world(client) as w:
        await _blocked(
            w.company_id,
            "UPDATE pay_adjustment SET paid_days_delta = 5 WHERE id = :id",
            id=w.adjustment_id,
        )
        await _blocked(
            w.company_id,
            "UPDATE pay_adjustment SET status='PENDING', applied_pay_run_id=NULL WHERE id = :id",
            id=w.adjustment_id,
        )
        await _blocked(
            w.company_id, "DELETE FROM pay_adjustment WHERE id = :id", id=w.adjustment_id
        )

        pending = await client.post(
            "/v1/payroll/adjustments",
            headers=w.headers,
            json={
                "source_pay_run_id": w.final_run["id"],
                "employee_id": w.employee,
                "paid_days_delta": "-1",
                "reason": "Pending one",
            },
        )
        assert pending.status_code == 201, pending.text
        pid = pending.json()["data"]["id"]
        # a PENDING correction may become APPLIED, but not while changing what it says
        await _blocked(
            w.company_id,
            "UPDATE pay_adjustment SET status='APPLIED', paid_days_delta=9 WHERE id = :id",
            id=pid,
        )
        assert (
            await _as_app(
                w.company_id,
                "UPDATE pay_adjustment SET status='APPLIED', applied_pay_run_id=:run WHERE id=:id",
                id=pid,
                run=w.draft_run["id"],
            )
            == 1
        )
        assert await _as_app(w.company_id, "DELETE FROM pay_adjustment WHERE id = :id", id=pid) == 1
        await _blocked(
            w.company_id,
            """INSERT INTO pay_adjustment (id, company_id, legal_entity_id, employee_id, for_month,
                 source_pay_run_id, paid_days_delta, reason, status, version, created_at,
                 updated_at)
               SELECT gen_random_uuid(), company_id, legal_entity_id, employee_id, for_month,
                 source_pay_run_id, 1, 'forged', 'APPLIED', 1, now(), now()
               FROM pay_adjustment WHERE id = :id""",
            id=w.adjustment_id,
        )


async def test_pre_finalisation_rows_stay_writable_for_the_runtime_role(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    async with _world(client) as w:
        rid = w.draft_run["id"]
        assert (
            await _as_app(
                w.company_id, "UPDATE pay_run SET variance_flag_count = 0 WHERE id = :id", id=rid
            )
            == 1
        )
        assert await _as_app(w.company_id, "DELETE FROM pay_run WHERE id = :id", id=rid) == 1


async def test_tenant_isolation_is_unchanged_by_the_triggers(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    async with _world(client) as a:
        async with _runtime_engine() as engine, engine.connect() as conn:
            trans = await conn.begin()
            try:
                # another tenant's context sees none of A's runs, so nothing is even attempted
                await conn.execute(
                    text("SELECT set_config('app.company_id', :c, true)"), {"c": str(uuid4())}
                )
                visible = (await conn.execute(text("SELECT count(*) FROM pay_run"))).scalar_one()
                touched = (
                    await conn.execute(
                        text("UPDATE pay_run SET net_minor = 1 WHERE id = :id"),
                        {"id": a.final_run["id"]},
                    )
                ).rowcount
            finally:
                await trans.rollback()
        assert visible == 0 and touched == 0
        # and without any tenant context the runtime role sees nothing at all
        async with _runtime_engine() as engine, engine.connect() as conn:
            assert (await conn.execute(text("SELECT count(*) FROM pay_run"))).scalar_one() == 0


async def test_the_runtime_role_cannot_remove_the_protection(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    async with _world(client) as w:
        for sql in (
            "ALTER TABLE pay_run DISABLE TRIGGER pay_run_immutable_guard",
            "DROP TRIGGER pay_run_immutable_guard ON pay_run",
            "DROP FUNCTION payroll_guard_pay_run() CASCADE",
            "SET session_replication_role = replica",
        ):
            with pytest.raises(DBAPIError):
                await _as_app(w.company_id, sql)


async def test_normal_lifecycle_works_end_to_end_as_the_runtime_role(
    client: AsyncClient, seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        le = await _legal_entity(client, headers)
        employee = await _employee(client, headers, le)
        approver = await _approver(company_id)
        for start, end, days in (
            ("2026-08-01", "2026-08-31", 31),
            ("2026-09-01", "2026-09-30", 30),
        ):
            await _closed_period(
                company_id=company_id, legal_entity_id=le, start=start, end=end,
                paid_days={employee: str(days)}, days_in_month=days,
            )  # fmt: skip

        async with _app_as_runtime_role(monkeypatch):
            # a draft run can be created, deleted, created again
            throwaway = await _create_run(client, headers, le, "2026-08")
            gone = await client.delete(
                f"/v1/payroll/pay-runs/{throwaway['id']}",
                headers={**headers, "If-Match": str(throwaway["version"])},
            )
            assert gone.status_code == 204, gone.text

            run = await _create_run(client, headers, le, "2026-08")
            run = await _action(client, headers, run, "lock-inputs")
            run = await _action(client, headers, run, "compute")
            run = await _action(client, headers, run, "compute")  # recompute replaces the lines
            run = await _action(
                client, headers, run, "rollback", json={"to_status": "INPUTS_LOCKED", "reason": "x"}
            )
            run = await _action(client, headers, run, "compute")
            run = await _action(client, approver, run, "approve")
            run = await _action(client, approver, run, "finalise")
            assert run["status"] == "FINALISED"

            # finalised: the API refuses a rollback, and so does the database underneath it
            await _action(
                client, headers, run, "rollback", expect=409,
                json={"to_status": "DRAFT", "reason": "too late"},
            )  # fmt: skip

            # correct the finalised month, pay the difference in September, then mark August paid
            correction = await client.post(
                "/v1/payroll/adjustments",
                headers=headers,
                json={
                    "source_pay_run_id": run["id"],
                    "employee_id": employee,
                    "paid_days_delta": "-1",
                    "reason": "Late absence",
                },
            )
            assert correction.status_code == 201, correction.text
            withdrawn = await client.post(
                "/v1/payroll/adjustments",
                headers=headers,
                json={
                    "source_pay_run_id": run["id"],
                    "employee_id": employee,
                    "paid_days_delta": "1",
                    "reason": "Mistake",
                },
            )
            gone = await client.delete(
                f"/v1/payroll/adjustments/{withdrawn.json()['data']['id']}", headers=headers
            )
            assert gone.status_code == 204, gone.text

            sep = await _create_run(client, headers, le, "2026-09")
            sep = await _action(client, headers, sep, "lock-inputs")
            sep = await _action(client, headers, sep, "compute")
            employees = await client.get(
                f"/v1/payroll/pay-runs/{sep['id']}/employees", headers=headers
            )
            for row in employees.json()["data"]:
                if row["variance_flagged"]:
                    ack = await client.post(
                        f"/v1/payroll/pay-runs/{sep['id']}/employees/{row['employee_id']}"
                        "/acknowledge-variance",
                        headers=headers,
                        json={"reason": "Arrears"},
                    )
                    assert ack.status_code == 200, ack.text
            sep = (await client.get(f"/v1/payroll/pay-runs/{sep['id']}", headers=headers)).json()[
                "data"
            ]
            sep = await _action(client, approver, sep, "approve")
            sep = await _action(client, approver, sep, "finalise")
            assert sep["status"] == "FINALISED"
            paid = await _action(client, approver, run, "mark-paid")
            assert paid["status"] == "PAID"

            payslip = await client.get(
                f"/v1/payroll/pay-runs/{sep['id']}/employees/{employee}", headers=headers
            )
            assert payslip.status_code == 200, payslip.text
            assert any(
                line["component_code"].startswith("ARR_")
                for line in payslip.json()["data"]["lines"]
            )
    finally:
        await _cleanup_pay_runs(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()
