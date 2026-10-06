"""Decision 16 / LM-01 - the year-end sweep has a catch-up window: a missed first day of the leave
year is recovered on a later day inside the window, exactly once, against the balance as it stands
when the recovery runs, with per-employee and per-company failure isolation preserved."""

import asyncio
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.leave import test_leave_year as year_helpers
from tests.integration.modules.leave.test_leave_application import (
    _cleanup,
    _create_employee,
    _create_employment,
    _create_leave_type,
    _create_legal_entity,
    _get_balance,
    _give_balance,
    _register_tenant,
    _setup_leave_policy,
    _teardown,
)

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.leave import tasks as leave_tasks
from hrms.modules.leave.service import LeaveAccrualService

pytestmark = pytest.mark.asyncio

_run_year_end = year_helpers._run_year_end


async def _setup(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    employees: int = 1,
    balance: str = "20.00",
    **version_extra: str,
) -> tuple[list[str], str]:
    legal_entity = await _create_legal_entity(client, headers)
    leave_type = await _create_leave_type(client, headers)
    await _setup_leave_policy(
        client, headers, leave_type_id=leave_type["id"], approval_chain="AUTO", **version_extra
    )
    ids: list[str] = []
    for index in range(employees):
        employee = await _create_employee(client, headers, first_name=f"Emp{index}")
        await _create_employment(
            client,
            headers,
            employee_id=employee["id"],
            legal_entity_id=legal_entity["id"],
            joining_date="2020-01-01",
        )
        await _give_balance(
            client,
            headers,
            employee_id=employee["id"],
            leave_type_id=leave_type["id"],
            amount=balance,
        )
        ids.append(str(employee["id"]))
    return ids, str(leave_type["id"])


async def _year_end_rows(company_id: UUID, employee_id: str) -> list[tuple[str, str, date]]:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        rows = await session.execute(
            text(
                "SELECT entry_type, amount, effective_date FROM leave_ledger "
                "WHERE company_id = CAST(:c AS uuid) AND employee_id = CAST(:e AS uuid) "
                "AND (entry_type IN ('CARRY_FORWARD', 'ENCASHMENT') "
                "OR (entry_type = 'ACCRUAL' AND reason LIKE 'Yearly%')) "
                "ORDER BY created_at, entry_type"
            ),
            {"c": str(company_id), "e": employee_id},
        )
        return [(t, str(a), d) for t, a, d in rows.all()]


async def _markers(company_id: UUID) -> int:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        row = await session.execute(
            text("SELECT count(*) FROM leave_year_end_run WHERE company_id = CAST(:c AS uuid)"),
            {"c": str(company_id)},
        )
        return int(row.scalar_one())


async def _teardown_all(company_id: UUID) -> None:
    await year_helpers._teardown_year_setting(company_id=company_id)
    await _teardown(company_id=company_id)


async def test_normal_day_one_run_processes_the_year_start(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        (employee_id,), _ = await _setup(client, headers, max_carry_forward_days="5.00")
        assert await _run_year_end(company_id, as_of=date(2026, 1, 1)) == 1
        assert await _get_balance(client, headers, employee_id) == "5.00"
        assert await _year_end_rows(company_id, employee_id) == [
            ("CARRY_FORWARD", "-15.00", date(2026, 1, 1))
        ]
    finally:
        await _teardown_all(company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.parametrize("recovery_day", [2, 3, 5])
async def test_missed_day_one_is_recovered_inside_the_window_and_dated_on_the_year_start(
    client: AsyncClient, seeded_plan_catalogue: None, recovery_day: int
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        (employee_id,), _ = await _setup(client, headers, max_carry_forward_days="5.00")
        # nothing ran on 1 Jan; the first run happens `recovery_day` days into the year
        assert await _run_year_end(company_id, as_of=date(2026, 1, recovery_day)) == 1
        assert await _get_balance(client, headers, employee_id) == "5.00"
        # ledger rows carry the year-start date, never the catch-up day
        assert await _year_end_rows(company_id, employee_id) == [
            ("CARRY_FORWARD", "-15.00", date(2026, 1, 1))
        ]
    finally:
        await _teardown_all(company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_a_run_outside_the_catch_up_window_does_not_process_the_year_start(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        (employee_id,), _ = await _setup(client, headers, max_carry_forward_days="5.00")
        assert await _run_year_end(company_id, as_of=date(2026, 1, 6)) == 0
        assert await _get_balance(client, headers, employee_id) == "20.00"
        assert await _markers(company_id) == 0
        # an operator can still recover it by choosing an as-of date inside the window
        assert await leave_tasks._run_year_end_async(company_id, date(2026, 1, 3)) == 1
        assert await _get_balance(client, headers, employee_id) == "5.00"
        # and the window size is configurable per call
        assert await _run_year_end(company_id, as_of=date(2026, 1, 3)) == 0
    finally:
        await _teardown_all(company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_a_processed_year_start_is_never_repeated_across_the_window(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The dangerous repeat: LAPSE policy with YEARLY accrual. Day 1 lapses nothing (balance 0)
    and credits 12; if day 3 re-evaluated the year it would lapse the fresh 12."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        (employee_id,), _ = await _setup(
            client,
            headers,
            balance="1.00",
            year_end_action="LAPSE",
            accrual_frequency="YEARLY",
            accrual_rate_per_cycle="12.00",
        )
        # day 1 lapses the 1.00 and credits the 12.00 yearly accrual (two rows)
        assert await _run_year_end(company_id, as_of=date(2026, 1, 1)) == 2
        assert await _get_balance(client, headers, employee_id) == "12.00"
        for day in (2, 3, 4, 5):
            assert await _run_year_end(company_id, as_of=date(2026, 1, day)) == 0
        assert await _get_balance(client, headers, employee_id) == "12.00"
        assert await _markers(company_id) == 1
    finally:
        await _teardown_all(company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_a_top_up_after_the_year_start_is_not_lapsed_by_a_later_window_run(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        (employee_id,), leave_type_id = await _setup(
            client,
            headers,
            balance="3.00",
            year_end_action="LAPSE",
            accrual_frequency="YEARLY",
            accrual_rate_per_cycle="12.00",
        )
        # day 1: lapse 3, accrue 12
        assert await _run_year_end(company_id, as_of=date(2026, 1, 1)) == 2
        # a later top-up inside the window must not be lapsed by a later run
        await _give_balance(
            client, headers, employee_id=employee_id, leave_type_id=leave_type_id, amount="4.00"
        )
        assert await _run_year_end(company_id, as_of=date(2026, 1, 4)) == 0
        assert await _get_balance(client, headers, employee_id) == "16.00"
    finally:
        await _teardown_all(company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_recovery_uses_the_balance_at_execution_time(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        (employee_id,), leave_type_id = await _setup(client, headers, max_carry_forward_days="5.00")
        # the missed year start; before the recovery run the balance drops from 20 to 10
        adjusted = await client.post(
            "/v1/leave-ledger/adjustments",
            headers=headers,
            json={
                "employee_id": employee_id,
                "leave_type_id": leave_type_id,
                "amount": "-10.00",
                "effective_date": "2026-01-02",
                "reason": "taken before recovery",
            },
        )
        assert adjusted.status_code == 201, adjusted.text
        assert await _run_year_end(company_id, as_of=date(2026, 1, 3)) == 1
        # cap 5 against the CURRENT balance 10 -> lapse 5 (not 15)
        assert await _year_end_rows(company_id, employee_id) == [
            ("CARRY_FORWARD", "-5.00", date(2026, 1, 1))
        ]
        assert await _get_balance(client, headers, employee_id) == "5.00"
    finally:
        await _teardown_all(company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_concurrent_catch_up_runs_process_each_employee_once(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_ids, leave_type_id = await _setup(
            client, headers, employees=3, max_carry_forward_days="5.00"
        )
        for year in (2026, 2027, 2028):
            for employee_id in employee_ids:
                current = Decimal(await _get_balance(client, headers, employee_id))
                if current < Decimal("20.00"):
                    await _give_balance(
                        client,
                        headers,
                        employee_id=employee_id,
                        leave_type_id=leave_type_id,
                        amount=str(Decimal("20.00") - current),
                    )
            # one runs on day 1, the others race it as late catch-ups
            results = await asyncio.gather(
                _run_year_end(company_id, as_of=date(year, 1, 1)),
                _run_year_end(company_id, as_of=date(year, 1, 1)),
                _run_year_end(company_id, as_of=date(year, 1, 2)),
            )
            assert sum(results) == 3, results  # one lapse per employee, no more
            for employee_id in employee_ids:
                assert await _get_balance(client, headers, employee_id) == "5.00"
                rows = [
                    r for r in await _year_end_rows(company_id, employee_id) if r[2].year == year
                ]
                assert len(rows) == 1, rows
    finally:
        await _teardown_all(company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_one_employees_year_end_failure_is_isolated_and_recovered_by_the_next_run(
    client: AsyncClient, seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    real = LeaveAccrualService._year_end_for_employee
    try:
        (first, second), _ = await _setup(
            client, headers, employees=2, max_carry_forward_days="5.00"
        )

        async def failing_for_first(
            self: Any, company: UUID, employee_id: UUID, **kwargs: Any
        ) -> int:
            if str(employee_id) == first:
                # fails AFTER claiming the marker, to prove the claim rolls back with the savepoint
                await real(self, company, employee_id, **kwargs)
                raise RuntimeError("boom")
            return await real(self, company, employee_id, **kwargs)

        monkeypatch.setattr(LeaveAccrualService, "_year_end_for_employee", failing_for_first)
        assert await _run_year_end(company_id, as_of=date(2026, 1, 1)) == 1
        assert await _get_balance(client, headers, second) == "5.00"
        assert await _get_balance(client, headers, first) == "20.00"  # rolled back entirely
        assert await _markers(company_id) == 1

        monkeypatch.setattr(LeaveAccrualService, "_year_end_for_employee", real)
        assert await _run_year_end(company_id, as_of=date(2026, 1, 2)) == 1
        assert await _get_balance(client, headers, first) == "5.00"
        assert await _get_balance(client, headers, second) == "5.00"
        assert await _run_year_end(company_id, as_of=date(2026, 1, 3)) == 0
    finally:
        monkeypatch.setattr(LeaveAccrualService, "_year_end_for_employee", real)
        await _teardown_all(company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_one_companys_year_end_failure_does_not_stop_another_company(
    client: AsyncClient, seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    a_headers, a_company, a_user = await _register_tenant(client)
    b_headers, b_company, b_user = await _register_tenant(client)
    real = LeaveAccrualService.run_year_end_for_company
    try:
        (a_emp,), _ = await _setup(client, a_headers, max_carry_forward_days="5.00")
        (b_emp,), _ = await _setup(client, b_headers, max_carry_forward_days="5.00")

        async def failing_for_a(self: Any, company_id: UUID, **kwargs: Any) -> int:
            if company_id == a_company:
                raise RuntimeError("company A is broken")
            return await real(self, company_id, **kwargs)

        monkeypatch.setattr(LeaveAccrualService, "run_year_end_for_company", failing_for_a)
        outcomes = await asyncio.gather(
            leave_tasks._run_year_end_async(a_company, date(2026, 1, 1)),
            leave_tasks._run_year_end_async(b_company, date(2026, 1, 1)),
            return_exceptions=True,
        )
        assert isinstance(outcomes[0], RuntimeError) and outcomes[1] == 1
        assert await _get_balance(client, b_headers, b_emp) == "5.00"
        assert await _get_balance(client, a_headers, a_emp) == "20.00"
        # company B's rows never appear under company A, and A recovers on its next run
        assert await _markers(a_company) == 0
        monkeypatch.setattr(LeaveAccrualService, "run_year_end_for_company", real)
        assert await leave_tasks._run_year_end_async(a_company, date(2026, 1, 2)) == 1
        assert await _get_balance(client, a_headers, a_emp) == "5.00"
    finally:
        monkeypatch.setattr(LeaveAccrualService, "run_year_end_for_company", real)
        await _teardown_all(a_company)
        await _teardown_all(b_company)
        await _cleanup(company_id=a_company, user_id=a_user)
        await _cleanup(company_id=b_company, user_id=b_user)


async def test_year_end_already_done_by_the_pre_marker_engine_is_not_repeated(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Deployment safety: rows the old engine wrote for a year start count as "processed", so the
    first catch-up window after deploying cannot re-run a year that was already handled."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        (employee_id,), leave_type_id = await _setup(
            client, headers, balance="20.00", year_end_action="LAPSE", max_carry_forward_days="5.00"
        )
        # what the old engine left behind: a lapse dated on the year start, no marker row
        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(company_id))
            await session.execute(
                text(
                    "INSERT INTO leave_ledger (id, company_id, employee_id, leave_type_id, "
                    "entry_type, amount, effective_date, reference_id, reason) "
                    "SELECT gen_random_uuid(), :c, :e, :t, 'CARRY_FORWARD', -20, "
                    "DATE '2026-01-01', id, 'old engine' FROM leave_policy_version "
                    "WHERE company_id = :c LIMIT 1"
                ),
                {"c": company_id, "e": UUID(employee_id), "t": UUID(leave_type_id)},
            )
            await session.commit()
        await _give_balance(
            client, headers, employee_id=employee_id, leave_type_id=leave_type_id, amount="8.00"
        )
        assert await _run_year_end(company_id, as_of=date(2026, 1, 2)) == 0
        assert await _get_balance(client, headers, employee_id) == "8.00"  # nothing lapsed again
    finally:
        await _teardown_all(company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
