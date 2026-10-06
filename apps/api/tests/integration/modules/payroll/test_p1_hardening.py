"""PAY-A01 / PAY-A02 / PAY-A03 — the three P1 payroll fixes (decision PD-4).

* A01 — attendance reopen and pay-run finalisation share the attendance period-close lock
  (`core/db/locks.py`); the invariant is "FINALISED run => CLOSED period", asserted from the
  database after genuinely concurrent requests.
* A02 — an input changed after `INPUTS_LOCKED` blocks approval and finalisation (409
  `PAY_RUN_INPUTS_CHANGED`); the run is left alone and locking again picks the change up.
* A03 — finalisation is serialised per legal entity and each arrears payment is numbered under a
  unique index, so concurrent runs sharing unpaid arrears pay them exactly once.

Periods are inserted directly (see `test_pay_run.py`); everything else goes through the API."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
import redis.asyncio as redis
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from tests.integration.modules.attendance.test_attendance_day import _register_tenant
from tests.integration.modules.attendance.test_attendance_security import _cleanup_scoped_users
from tests.integration.modules.organisation.test_registration_flow import _cleanup
from tests.integration.modules.payroll.test_arrears import _finalised_run, _lines
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
from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.payroll.repository import PayRunArrearRepository

pytestmark = pytest.mark.asyncio


@asynccontextmanager
async def _tenant(client: AsyncClient) -> AsyncIterator[tuple[dict[str, str], UUID]]:
    """A fresh tenant — the plan caps a tenant at five employees, so repeated trials each get
    their own — cleaned up afterwards."""
    redis_client = redis.from_url(get_settings().redis_url, decode_responses=True)
    await redis_client.delete("ratelimit:auth:127.0.0.1")
    await redis_client.aclose()
    headers, company_id, user_id = await _register_tenant(client)
    try:
        yield headers, company_id
    finally:
        await _cleanup_pay_runs(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def _scalar(company_id: UUID, sql: str, **params: Any) -> Any:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        return (await session.execute(text(sql), {"cid": str(company_id), **params})).scalar()


# ---------------------------------------------------------------------------------------------
# PAY-A01
# ---------------------------------------------------------------------------------------------


async def test_finalise_and_reopen_never_leave_finalised_payroll_on_an_open_period(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Finalise and reopen of the same period race, several times over. Whatever the order, the
    committed state is either 'not finalised, reopened' or 'finalised, still CLOSED' — never a
    finalised run on an OPEN period (the audit reproduced that 7 times in 8)."""
    outcomes: set[str] = set()
    for _trial in range(8):
        async with _tenant(client) as (headers, company_id):
            approver = await _approver(company_id)
            le = await _legal_entity(client, headers)
            employee = await _employee(client, headers, le)
            period_id = await _closed_period(
                company_id=company_id, legal_entity_id=le, start="2026-09-01", end="2026-09-30",
                paid_days={employee: "30"}, days_in_month=30,
            )  # fmt: skip
            run = await _create_run(client, headers, le, "2026-09")
            run = await _action(client, headers, run, "lock-inputs")
            run = await _action(client, headers, run, "compute")
            run = await _action(client, approver, run, "approve")
            period = await client.get(f"/v1/attendance-periods/{period_id}", headers=headers)

            finalise, reopen = await asyncio.gather(
                client.post(
                    f"/v1/payroll/pay-runs/{run['id']}/finalise",
                    headers={**approver, "If-Match": str(run["version"])},
                ),
                client.post(
                    f"/v1/attendance-periods/{period_id}/reopen",
                    headers={**headers, "If-Match": str(period.json()["data"]["version"])},
                    json={"reason": "Race"},
                ),
            )
            assert finalise.status_code in (200, 409), finalise.text
            assert reopen.status_code in (200, 409), reopen.text

            run_status = await _scalar(
                company_id, "SELECT status FROM pay_run WHERE id = :id", id=run["id"]
            )
            period_status = await _scalar(
                company_id, "SELECT status FROM attendance_period WHERE id = :id", id=period_id
            )
            assert (run_status, period_status) in {
                ("APPROVED", "OPEN"),
                ("FINALISED", "CLOSED"),
            }, (run_status, period_status, finalise.text, reopen.text)
            # The responses agree with what was committed.
            assert (finalise.status_code == 200) == (run_status == "FINALISED")
            assert (reopen.status_code == 200) == (period_status == "OPEN")
            outcomes.add(run_status)
    assert outcomes  # every trial held the invariant


async def test_finalise_waits_for_a_reopen_in_flight_and_then_refuses(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Deterministic version of the race: a reopen holds the period-close lock and has already
    committed to OPEN only after the finalise is queued. The finalise must wait for the lock,
    then see the reopened period and refuse — not slip through on its earlier read."""
    from hrms.core.db.locks import lock_attendance_period_close

    headers, company_id, user_id = await _register_tenant(client)
    try:
        le = await _legal_entity(client, headers)
        employee = await _employee(client, headers, le)
        period_id = await _closed_period(
            company_id=company_id, legal_entity_id=le, start="2026-09-01", end="2026-09-30",
            paid_days={employee: "30"}, days_in_month=30,
        )  # fmt: skip
        approver = await _approver(company_id)
        run = await _create_run(client, headers, le, "2026-09")
        run = await _action(client, headers, run, "lock-inputs")
        run = await _action(client, headers, run, "compute")
        run = await _action(client, approver, run, "approve")

        factory = get_session_factory()
        async with factory() as holder:
            await set_rls_company_id(holder, str(company_id))
            await lock_attendance_period_close(holder, company_id, exclusive=True)
            task = asyncio.create_task(
                client.post(
                    f"/v1/payroll/pay-runs/{run['id']}/finalise",
                    headers={**approver, "If-Match": str(run["version"])},
                )
            )
            await asyncio.sleep(0.5)
            assert not task.done(), "finalise did not wait for the period-close lock"
            # The 'reopen' commits while finalise is queued.
            await holder.execute(
                text("UPDATE attendance_period SET status = 'OPEN', version = version + 1 "
                     "WHERE id = :id"),
                {"id": period_id},
            )  # fmt: skip
            await holder.commit()
        response = await task
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "PAY_RUN_ATTENDANCE_CHANGED"
        assert (
            await _scalar(company_id, "SELECT status FROM pay_run WHERE id = :id", id=run["id"])
            == "APPROVED"
        )
    finally:
        await _cleanup_pay_runs(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


# ---------------------------------------------------------------------------------------------
# PAY-A03
# ---------------------------------------------------------------------------------------------


async def _backdated_revision(
    client: AsyncClient,
    headers: dict[str, str],
    employee: str,
    annual_ctc_minor: int = 8_40_000_00,
    effective_from: str = "2026-08-01",
) -> None:
    """August was paid on ₹7,20,000; a raise to ₹8,40,000 from 1 August is recorded afterwards, so
    every later run prepared before the arrears are paid carries ₹5,000 + ₹2,000 + ₹3,000."""
    current = await client.get(f"/v1/employees/{employee}/compensation", headers=headers)
    response = await client.post(
        f"/v1/employees/{employee}/compensation",
        headers={**headers, "If-Match": str(max(r["version"] for r in current.json()["data"]))},
        json={
            "effective_from": effective_from,
            "annual_ctc_minor": annual_ctc_minor,
            "currency": "INR",
            "revision_type": "ANNUAL",
            "revision_reason": "Annual increment, backdated",
        },
    )
    assert response.status_code == 201, response.text


async def _prepared_run(
    client: AsyncClient, headers: dict[str, str], approver: dict[str, str], le: str,
    employee: str, company_id: UUID, month: str, days: int,
) -> dict[str, Any]:  # fmt: skip
    from tests.integration.modules.payroll.test_arrears import _MONTHS

    start, end, _ = _MONTHS[month]
    await _closed_period(
        company_id=company_id, legal_entity_id=le, start=start, end=end,
        paid_days={employee: str(days)}, days_in_month=days,
    )  # fmt: skip
    run = await _create_run(client, headers, le, month)
    run = await _action(client, headers, run, "lock-inputs")
    run = await _action(client, headers, run, "compute")
    _, lines = await _lines(client, headers, run["id"], employee)
    assert "ARR_BASIC" in lines, "the run must carry August's arrears"
    for row in (
        await client.get(f"/v1/payroll/pay-runs/{run['id']}/employees", headers=headers)
    ).json()["data"]:
        if row["variance_flagged"]:
            await client.post(
                f"/v1/payroll/pay-runs/{run['id']}/employees/{row['employee_id']}"
                "/acknowledge-variance",
                headers=headers, json={"reason": "Arrears"},
            )  # fmt: skip
    run = (await client.get(f"/v1/payroll/pay-runs/{run['id']}", headers=headers)).json()["data"]
    return await _action(client, approver, run, "approve")


async def test_concurrent_finalisations_pay_shared_arrears_exactly_once(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """September and October are both prepared and approved carrying the same ₹10,000 arrears for
    August (a backdated raise). Both finalise at once. Exactly one pays them; the other is refused
    as stale; the arrears actually paid equal what was owed (the audit saw it paid twice)."""
    for _trial in range(4):
        async with _tenant(client) as (headers, company_id):
            approver = await _approver(company_id)
            le = await _legal_entity(client, headers)
            employee = await _employee(client, headers, le)
            await _finalised_run(
                client, headers, approver, company_id=company_id, legal_entity_id=le,
                month="2026-08", paid_days={employee: "31"},
            )  # fmt: skip
            await _backdated_revision(client, headers, employee)
            september = await _prepared_run(
                client, headers, approver, le, employee, company_id, "2026-09", 30
            )
            october = await _prepared_run(
                client, headers, approver, le, employee, company_id, "2026-10", 31
            )
            owed = await _scalar(
                company_id,
                "SELECT COALESCE(SUM(amount_minor), 0) FROM pay_run_line "
                "WHERE pay_run_id = :id AND component_code LIKE 'ARR\\_%'",
                id=september["id"],
            )
            assert owed == 10_000_00

            responses = await asyncio.gather(
                *(
                    client.post(
                        f"/v1/payroll/pay-runs/{run['id']}/finalise",
                        headers={**approver, "If-Match": str(run["version"])},
                    )
                    for run in (september, october)
                )
            )
            codes = sorted(r.status_code for r in responses)
            assert codes == [200, 409], [r.text for r in responses]
            loser = next(r for r in responses if r.status_code == 409)
            assert loser.json()["error"]["code"] == "PAY_RUN_ARREARS_STALE"

            paid = await _scalar(
                company_id,
                "SELECT COALESCE(SUM(l.amount_minor), 0) FROM pay_run_line l "
                "JOIN pay_run r ON r.id = l.pay_run_id "
                "WHERE r.legal_entity_id = :le AND r.status IN ('FINALISED', 'PAID') "
                "AND l.employee_id = :emp AND l.component_code LIKE 'ARR\\_%'",
                le=le, emp=employee,
            )  # fmt: skip
            assert paid == owed
            numbered = await _scalar(
                company_id,
                "SELECT count(*) FROM pay_run_arrear WHERE employee_id = :emp "
                "AND applied_at IS NOT NULL",
                emp=employee,
            )
            per_component = await _scalar(
                company_id,
                "SELECT count(DISTINCT component_code) FROM pay_run_arrear "
                "WHERE employee_id = :emp AND applied_at IS NOT NULL",
                emp=employee,
            )
            assert numbered == per_component > 0


async def test_database_refuses_a_second_payment_of_the_same_arrear(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The backstop under the lock: two transactions that both read 'nothing paid yet' number
    their arrears 1; the second fails at the unique index instead of paying again — even with the
    finalise lock out of the picture."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        approver = await _approver(company_id)
        le = await _legal_entity(client, headers)
        employee = await _employee(client, headers, le)
        await _finalised_run(
            client, headers, approver, company_id=company_id, legal_entity_id=le,
            month="2026-08", paid_days={employee: "31"},
        )  # fmt: skip
        await _backdated_revision(client, headers, employee)
        september = await _prepared_run(
            client, headers, approver, le, employee, company_id, "2026-09", 30
        )
        october = await _prepared_run(
            client, headers, approver, le, employee, company_id, "2026-10", 31
        )

        repo = PayRunArrearRepository()
        now = datetime.now(UTC)
        factory = get_session_factory()
        async with factory() as first, factory() as second:
            for session in (first, second):
                await set_rls_company_id(session, str(company_id))
            assert (
                await repo.mark_applied(
                    first, company_id=company_id, run_id=september["id"], now=now
                )
                > 0
            )
            # `second` numbers against the committed state, which does not yet include `first`.
            blocked = asyncio.create_task(
                repo.mark_applied(second, company_id=company_id, run_id=october["id"], now=now)
            )
            await asyncio.sleep(0.3)
            assert not blocked.done()  # waiting on first's uncommitted index entries
            await first.commit()
            with pytest.raises(IntegrityError):
                await blocked
            await second.rollback()
        assert (
            await _scalar(
                company_id,
                "SELECT count(*) FROM pay_run_arrear WHERE employee_id = :emp "
                "AND applied_at IS NOT NULL AND pay_run_id = :id",
                emp=employee,
                id=october["id"],
            )  # fmt: skip
            == 0
        )
    finally:
        await _cleanup_pay_runs(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_a_later_correction_of_the_same_month_is_a_new_payment(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The guard must not forbid legitimate repeats: after August's first correction is paid, a
    second revision is a new arrear — payment number 2 — and finalises normally."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        approver = await _approver(company_id)
        le = await _legal_entity(client, headers)
        employee = await _employee(client, headers, le)
        await _finalised_run(
            client, headers, approver, company_id=company_id, legal_entity_id=le,
            month="2026-08", paid_days={employee: "31"},
        )  # fmt: skip
        await _backdated_revision(client, headers, employee)
        september = await _prepared_run(
            client, headers, approver, le, employee, company_id, "2026-09", 30
        )
        await _action(client, approver, september, "finalise")

        await _backdated_revision(
            client, headers, employee, annual_ctc_minor=9_60_000_00, effective_from="2026-08-02"
        )
        october = await _prepared_run(
            client, headers, approver, le, employee, company_id, "2026-10", 31
        )
        numbers = await _scalar(
            company_id,
            "SELECT array_agg(DISTINCT payment_number) FROM pay_run_arrear "
            "WHERE pay_run_id = :id AND for_month = '2026-08-01'",
            id=october["id"],
        )
        assert numbers == [2]
        october = await _action(client, approver, october, "finalise")
        assert october["status"] == "FINALISED"
    finally:
        await _cleanup_pay_runs(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


# ---------------------------------------------------------------------------------------------
# PAY-A02
# ---------------------------------------------------------------------------------------------

Mutation = Callable[[AsyncClient, dict[str, str], str], Awaitable[None]]


async def _salary(client: AsyncClient, headers: dict[str, str], employee: str) -> None:
    structures = await client.get("/v1/payroll/salary-structures", headers=headers)
    metro = next(s for s in structures.json()["data"] if s["code"] == "STANDARD_METRO")
    response = await client.post(
        f"/v1/employees/{employee}/salary",
        headers=headers,
        json={"salary_structure_id": metro["id"], "effective_from": "2026-09-16",
              "reason": "Moved to a metro office"},
    )  # fmt: skip
    assert response.status_code == 201, response.text


async def _structure(client: AsyncClient, headers: dict[str, str], employee: str) -> None:
    structures = await client.get("/v1/payroll/salary-structures", headers=headers)
    standard = next(s for s in structures.json()["data"] if s["code"] == "STANDARD")
    created = await client.post(
        f"/v1/payroll/salary-structures/{standard['id']}/versions", headers=headers, json={}
    )
    assert created.status_code == 201, created.text
    draft = next(v for v in created.json()["data"]["versions"] if v["status"] == "DRAFT")
    lines = [
        {
            "salary_component_id": line["salary_component_id"],
            "calculation_type": line["calculation_type"],
            "percentage": ("45" if line["calculation_type"] == "PERCENTAGE_OF_CTC"
                           and line["percentage"] == "50" else line["percentage"]),
            "amount_monthly_minor": line["amount_monthly_minor"],
            "base_salary_component_id": line.get("base_salary_component_id"),
            "display_order": line["display_order"],
        }
        for line in draft["lines"]
    ]  # fmt: skip
    base = f"/v1/payroll/salary-structures/{standard['id']}/versions/{draft['id']}"
    updated = await client.put(
        f"{base}/lines", headers={**headers, "If-Match": str(draft["version"])},
        json={"lines": lines},
    )  # fmt: skip
    assert updated.status_code == 200, updated.text
    draft = next(v for v in updated.json()["data"]["versions"] if v["status"] == "DRAFT")
    published = await client.post(
        f"{base}/publish",
        headers={**headers, "If-Match": str(draft["version"])},
        json={"effective_from": "2026-09-16"},
    )
    assert published.status_code == 200, published.text


async def _ctc(client: AsyncClient, headers: dict[str, str], employee: str) -> None:
    current = await client.get(f"/v1/employees/{employee}/compensation", headers=headers)
    response = await client.post(
        f"/v1/employees/{employee}/compensation",
        headers={**headers, "If-Match": str(current.json()["data"][0]["version"])},
        json={"effective_from": "2026-09-01", "annual_ctc_minor": 8_40_000_00, "currency": "INR",
              "revision_type": "ANNUAL", "revision_reason": "Increment"},
    )  # fmt: skip
    assert response.status_code == 201, response.text


async def _statutory(client: AsyncClient, headers: dict[str, str], employee: str) -> None:
    current = await client.get(f"/v1/employees/{employee}/statutory", headers=headers)
    response = await client.post(
        f"/v1/employees/{employee}/statutory",
        headers={**headers, "If-Match": str(current.json()["data"][0]["version"])},
        json={"effective_from": "2026-09-01", "is_pf_applicable": True,
              "is_esi_applicable": False, "is_lwf_applicable": False, "tax_regime": "NEW",
              "revision_reason": "PF opted in"},
    )  # fmt: skip
    assert response.status_code == 201, response.text


async def _statutory_rate(client: AsyncClient, headers: dict[str, str], employee: str) -> None:
    rates = await client.get("/v1/payroll/statutory-rates", headers=headers)
    pf = next(r for r in rates.json()["data"] if r["scheme"] == "PF")
    response = await client.patch(
        f"/v1/payroll/statutory-rates/{pf['id']}",
        headers={**headers, "If-Match": str(pf["version"])},
        json={"parameters": {**pf["parameters"], "admin_percent": "0.6"}},
    )
    assert response.status_code == 200, response.text


async def _bank(client: AsyncClient, headers: dict[str, str], employee: str) -> None:
    current = await client.get(f"/v1/employees/{employee}/bank", headers=headers)
    response = await client.post(
        f"/v1/employees/{employee}/bank",
        headers={**headers, "If-Match": str(current.json()["data"][0]["version"])},
        json={
            "effective_from": "2026-09-01",
            "account_holder_name": "Ravi",
            "account_number_enc": "999988887777",
            "bank_name": "HDFC",
            "ifsc": "HDFC0001234",
            "payment_mode": "BANK",
        },
    )
    assert response.status_code == 201, response.text


_MUTATIONS: dict[str, tuple[Mutation, str]] = {
    "salary_assignment": (_salary, "segments"),
    "salary_structure_version": (_structure, "segments"),
    "ctc": (_ctc, "segments"),
    "statutory_profile": (_statutory, "segments"),
    "statutory_rate": (_statutory_rate, "statutory"),
    "bank_account": (_bank, "bank"),
}


_SNAPSHOT_KEY = {name: section for name, (_fn, section) in _MUTATIONS.items()}


async def _locked_run(
    client: AsyncClient, headers: dict[str, str], company_id: UUID, le: str, employee: str
) -> dict[str, Any]:
    await _closed_period(
        company_id=company_id, legal_entity_id=le, start="2026-09-01", end="2026-09-30",
        paid_days={employee: "30"}, days_in_month=30,
    )  # fmt: skip
    # A PF-applicable employee cannot be approved on an unverified PF rate (FR-PAY-005).
    rates = await client.get("/v1/payroll/statutory-rates", headers=headers)
    pf = next(r for r in rates.json()["data"] if r["scheme"] == "PF")
    verified = await client.post(
        f"/v1/payroll/statutory-rates/{pf['id']}/verify",
        headers={**headers, "If-Match": str(pf["version"])},
    )
    assert verified.status_code == 200, verified.text
    run = await _create_run(client, headers, le, "2026-09")
    return await _action(client, headers, run, "lock-inputs")


async def _fresh(client: AsyncClient, headers: dict[str, str], run: dict[str, Any]) -> Any:
    return (await client.get(f"/v1/payroll/pay-runs/{run['id']}", headers=headers)).json()["data"]


async def _employee_detail(
    client: AsyncClient, headers: dict[str, str], run_id: str, employee: str
) -> dict[str, Any]:
    detail = await client.get(
        f"/v1/payroll/pay-runs/{run_id}/employees/{employee}", headers=headers
    )
    assert detail.status_code == 200, detail.text
    return dict(detail.json()["data"])


@pytest.mark.parametrize("name", sorted(_MUTATIONS))
async def test_input_changed_after_lock_blocks_approval_until_locked_again(
    client: AsyncClient, seeded_plan_catalogue: None, name: str
) -> None:
    """PD-4 — change after INPUTS_LOCKED: approve is refused (run untouched), and rolling back to
    draft and locking again puts the new value in the payroll."""
    mutate, section = _MUTATIONS[name]
    headers, company_id, user_id = await _register_tenant(client)
    try:
        le = await _legal_entity(client, headers)
        employee = await _employee(client, headers, le)
        approver = await _approver(company_id)
        run = await _locked_run(client, headers, company_id, le, employee)

        await mutate(client, headers, employee)

        run = await _fresh(client, headers, run)
        # Computing from the frozen snapshot still works — it simply cannot be approved.
        run = await _action(client, headers, run, "compute")
        blocked = await _action(client, approver, run, "approve", expect=409)
        assert blocked["code"] == "PAY_RUN_INPUTS_CHANGED"
        (change,) = blocked["details"][0]["context"]["changes"]
        assert change["employee_id"] == employee
        assert section in change["sections"]
        # The run was neither mutated nor approved.
        unchanged = await _fresh(client, headers, run)
        assert unchanged["status"] == "COMPUTED"
        assert unchanged["version"] == run["version"]

        stale = await _employee_detail(client, headers, run["id"], employee)
        run = await _action(
            client, headers, unchanged, "rollback", json={"to_status": "DRAFT", "reason": "Input"}
        )
        run = await _action(client, headers, run, "lock-inputs")
        run = await _action(client, headers, run, "compute")
        fresh = await _employee_detail(client, headers, run["id"], employee)
        # Locking again carries the changed input into the snapshot (and so into the pay).
        assert fresh["snapshot"][_SNAPSHOT_KEY[name]] != stale["snapshot"][_SNAPSHOT_KEY[name]]
        if name == "ctc":
            assert (stale["net_minor"], fresh["net_minor"]) == (6_000_000, 7_000_000)
        run = await _action(client, approver, run, "approve")
        run = await _action(client, approver, run, "finalise")
        assert run["status"] == "FINALISED"
    finally:
        await _cleanup_pay_runs(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


@pytest.mark.parametrize("name", sorted(_MUTATIONS))
async def test_input_changed_after_approval_blocks_finalisation(
    client: AsyncClient, seeded_plan_catalogue: None, name: str
) -> None:
    mutate, section = _MUTATIONS[name]
    headers, company_id, user_id = await _register_tenant(client)
    try:
        le = await _legal_entity(client, headers)
        employee = await _employee(client, headers, le)
        approver = await _approver(company_id)
        run = await _locked_run(client, headers, company_id, le, employee)
        run = await _action(client, headers, run, "compute")
        run = await _action(client, approver, run, "approve")

        await mutate(client, headers, employee)

        blocked = await _action(client, approver, run, "finalise", expect=409)
        assert blocked["code"] == "PAY_RUN_INPUTS_CHANGED"
        assert section in blocked["details"][0]["context"]["changes"][0]["sections"]
        still = await _fresh(client, headers, run)
        assert still["status"] == "APPROVED"
        assert still["finalised_at"] is None
        assert (
            await _scalar(
                company_id,
                "SELECT count(*) FROM pay_run_arrear WHERE applied_at IS NOT NULL",
            )
            == 0
        )
    finally:
        await _cleanup_pay_runs(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


@pytest.mark.parametrize("name", sorted(_MUTATIONS))
async def test_input_changed_before_lock_is_in_the_snapshot_and_does_not_block(
    client: AsyncClient, seeded_plan_catalogue: None, name: str
) -> None:
    mutate, _ = _MUTATIONS[name]
    headers, company_id, user_id = await _register_tenant(client)
    try:
        le = await _legal_entity(client, headers)
        employee = await _employee(client, headers, le)
        approver = await _approver(company_id)
        await mutate(client, headers, employee)
        run = await _locked_run(client, headers, company_id, le, employee)
        run = await _action(client, headers, run, "compute")
        run = await _action(client, approver, run, "approve")
        run = await _action(client, approver, run, "finalise")
        assert run["status"] == "FINALISED"
    finally:
        await _cleanup_pay_runs(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_unchanged_inputs_do_not_block(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Control: nothing changed since the lock, so approval and finalisation go through."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        le = await _legal_entity(client, headers)
        employee = await _employee(client, headers, le)
        approver = await _approver(company_id)
        run = await _locked_run(client, headers, company_id, le, employee)
        run = await _action(client, headers, run, "compute")
        run = await _action(client, approver, run, "approve")
        run = await _action(client, approver, run, "finalise")
        assert run["status"] == "FINALISED"
    finally:
        await _cleanup_pay_runs(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()
