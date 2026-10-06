"""Leave production-hardening regressions: PRA-07 (accrual reliability), PRA-14 (company-local
dates), PRA-15 (concurrency and overlap), PRA-16 (append-only history).

Concurrency tests run real concurrent requests against PostgreSQL (advisory locks, optimistic
`If-Match` versions, unique indexes); nothing about the locking is mocked.
"""

import asyncio
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from celery.schedules import crontab
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.leave import test_leave_accrual as accrual_helpers
from tests.integration.modules.leave.test_leave_application import (
    _create_leave_type,
    _get_balance,
    _give_balance,
    _register_tenant,
    _setup_full,
    _setup_leave_policy,
    _submit,
    _teardown,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.core.celery_app import celery_app
from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.leave import tasks as leave_tasks
from hrms.modules.leave.service import LeaveAccrualService

pytestmark = pytest.mark.asyncio

EMPLOYEE_DAY = "2026-09-08"


def _frozen_now(instant: datetime) -> Any:
    return patch(
        "hrms.shared.business_time.datetime", wraps=datetime, **{"now.return_value": instant}
    )


async def _approve(client: AsyncClient, headers: dict, application: dict, **body: Any):
    return await client.post(
        f"/v1/leave-applications/{application['id']}/approve",
        headers={**headers, "If-Match": str(application["version"])},
        json=body,
    )


async def _cancel(client: AsyncClient, headers: dict, application: dict, **body: Any):
    return await client.post(
        f"/v1/leave-applications/{application['id']}/cancel",
        headers={**headers, "If-Match": str(application["version"])},
        json=body or {"reason": "needed"},
    )


async def _ledger(company_id: UUID, employee_id: str) -> list[dict[str, Any]]:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        rows = await session.execute(
            text(
                "SELECT entry_type, amount, effective_date FROM leave_ledger "
                "WHERE employee_id = CAST(:e AS uuid) ORDER BY created_at, entry_type"
            ),
            {"e": employee_id},
        )
        return [dict(r._mapping) for r in rows]


# ------------------------------------------------------------------------------ PRA-14


async def test_backdating_window_uses_the_company_local_date(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """00:30 IST on the 9th is still the 8th in UTC. Leave starting on the 8th is one day back in
    India, so a zero-day backdating window must refuse it; the UTC date would have let it by."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, approval_chain="HR", max_backdated_days=0)
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]
        with _frozen_now(datetime(2026, 9, 8, 19, 0, tzinfo=UTC)):  # 00:30 IST on 9 Sep
            refused = await _submit(
                client,
                headers,
                employee_id=employee_id,
                leave_type_id=leave_type_id,
                start_date="2026-09-08",
                end_date="2026-09-08",
            )
            assert refused.status_code == 422, refused.text
            assert refused.json()["error"]["code"] == "LEAVE_APPLICATION_WINDOW_EXCEEDED"
            today_ist = await _submit(
                client,
                headers,
                employee_id=employee_id,
                leave_type_id=leave_type_id,
                start_date="2026-09-09",
                end_date="2026-09-09",
            )
            assert today_ist.status_code == 201, today_ist.text
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_monthly_request_limit_counts_the_company_local_month(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A request filed at 00:30 IST on the 1st of the (company) month belongs to that month even
    though its UTC timestamp is still in the previous month."""
    from hrms.shared.business_time import business_month_start

    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, approval_chain="HR", max_requests_per_month=1)
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]
        first = await _submit(
            client,
            headers,
            employee_id=employee_id,
            leave_type_id=leave_type_id,
            start_date="2026-09-08",
            end_date="2026-09-08",
        )
        assert first.status_code == 201, first.text
        local_month_start = business_month_start("Asia/Kolkata")
        # 00:30 IST on the 1st of the current company month, expressed in UTC (the day before)
        filed_at = datetime(
            local_month_start.year, local_month_start.month, 1, 0, 30, tzinfo=UTC
        ) - __import__("datetime").timedelta(hours=5, minutes=30)
        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(company_id))
            await session.execute(
                text("UPDATE leave_application SET submitted_at = :t"), {"t": filed_at}
            )
            await session.commit()

        second = await _submit(
            client,
            headers,
            employee_id=employee_id,
            leave_type_id=leave_type_id,
            start_date="2026-09-10",
            end_date="2026-09-10",
        )
        assert second.status_code == 422, second.text
        assert second.json()["error"]["code"] == "LEAVE_APPLICATION_LIMIT_EXCEEDED"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_cancellation_reversal_is_dated_with_the_company_local_date(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, approval_chain="AUTO")
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]
        approved = (
            await _submit(client, headers, employee_id=employee_id, leave_type_id=leave_type_id)
        ).json()["data"]

        with _frozen_now(datetime(2026, 9, 30, 19, 30, tzinfo=UTC)):  # 01:00 IST on 1 Oct 2026
            cancelled = await _cancel(client, headers, approved, reason="HR cancelled")
        assert cancelled.status_code == 200, cancelled.text
        reversal = [
            e for e in await _ledger(company_id, employee_id) if e["entry_type"] == "ADJUSTMENT"
        ]
        assert reversal[-1]["effective_date"] == date(2026, 10, 1)
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# ------------------------------------------------------------------------------ PRA-15


async def test_second_request_for_the_same_type_and_date_is_refused_but_half_days_fit(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, approval_chain="HR")
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]
        first = await _submit(client, headers, employee_id=employee_id, leave_type_id=leave_type_id)
        assert first.status_code == 201, first.text

        duplicate = await _submit(
            client, headers, employee_id=employee_id, leave_type_id=leave_type_id
        )
        assert duplicate.status_code == 409, duplicate.text
        assert duplicate.json()["error"]["code"] == "LEAVE_APPLICATION_OVERLAP"

        # once the first is cancelled the day is free again
        assert (await _cancel(client, headers, first.json()["data"])).status_code == 200
        again = await _submit(client, headers, employee_id=employee_id, leave_type_id=leave_type_id)
        assert again.status_code == 201, again.text

        # two half days on one date add up to a day and are fine; a third part is not
        halves = []
        for half in ("FIRST_HALF", "SECOND_HALF"):
            halves.append(
                await _submit(
                    client,
                    headers,
                    employee_id=employee_id,
                    leave_type_id=leave_type_id,
                    start_date="2026-09-15",
                    end_date="2026-09-15",
                    half_day=half,
                )
            )
        assert [h.status_code for h in halves] == [201, 201], [h.text for h in halves]
        third = await _submit(
            client,
            headers,
            employee_id=employee_id,
            leave_type_id=leave_type_id,
            start_date="2026-09-15",
            end_date="2026-09-15",
            half_day="FIRST_HALF",
        )
        assert third.status_code == 409
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_concurrent_identical_submissions_create_one_application(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, approval_chain="HR")
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]
        results = await asyncio.gather(
            *[
                _submit(client, headers, employee_id=employee_id, leave_type_id=leave_type_id)
                for _ in range(4)
            ]
        )
        assert sorted(r.status_code for r in results) == [201, 409, 409, 409]
        listed = await client.get(
            "/v1/leave-applications", headers=headers, params={"employee_id": employee_id}
        )
        assert len(listed.json()["data"]) == 1
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_concurrent_approvals_of_overlapping_leave_of_different_types_book_one(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """PRA-15's race: the per-type balance lock does not order two approvals of different types,
    so both used to read an empty date and both insert, double-booking the day."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, approval_chain="HR", balance="10.00")
        employee_id = ctx["employee"]["id"]
        other_type = await _create_leave_type(client, headers, code="CL", name="Casual")
        await _setup_leave_policy(
            client, headers, leave_type_id=other_type["id"], approval_chain="HR"
        )
        await _give_balance(
            client, headers, employee_id=employee_id, leave_type_id=other_type["id"], amount="10.00"
        )
        a = (
            await _submit(
                client, headers, employee_id=employee_id, leave_type_id=ctx["leave_type"]["id"]
            )
        ).json()["data"]
        b = (
            await _submit(client, headers, employee_id=employee_id, leave_type_id=other_type["id"])
        ).json()["data"]

        first, second = await asyncio.gather(
            _approve(client, headers, a), _approve(client, headers, b)
        )
        assert sorted([first.status_code, second.status_code]) == [200, 409]
        loser = first if first.status_code == 409 else second
        assert loser.json()["error"]["code"] == "LEAVE_PROJECTION_OVERLAP"

        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(company_id))
            active = (
                await session.execute(
                    text(
                        "SELECT count(*), coalesce(sum(fraction), 0) FROM leave_day_projection "
                        "WHERE employee_id = CAST(:e AS uuid) AND status <> 'CANCELLED'"
                    ),
                    {"e": employee_id},
                )
            ).one()
        assert active[0] == 1 and active[1] == 1
        # exactly one debit across both types; the refused approval left no ledger trace
        debits = [
            e for e in await _ledger(company_id, employee_id) if e["entry_type"] == "APPLICATION"
        ]
        assert len(debits) == 1
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_concurrent_approvals_cannot_overdraw_the_balance(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, approval_chain="HR", balance="1.00")
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]
        apps = [
            (
                await _submit(
                    client,
                    headers,
                    employee_id=employee_id,
                    leave_type_id=leave_type_id,
                    start_date=day,
                    end_date=day,
                )
            ).json()["data"]
            for day in ("2026-09-08", "2026-09-09")
        ]
        results = await asyncio.gather(*[_approve(client, headers, a) for a in apps])
        assert sorted(r.status_code for r in results) == [200, 409]
        assert await _get_balance(client, headers, employee_id) == "0.00"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_concurrent_double_cancel_restores_the_balance_once(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, approval_chain="AUTO", balance="5.00")
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]
        approved = (
            await _submit(client, headers, employee_id=employee_id, leave_type_id=leave_type_id)
        ).json()["data"]
        assert await _get_balance(client, headers, employee_id) == "4.00"

        results = await asyncio.gather(
            *[_cancel(client, headers, approved, reason="dup") for _ in range(3)]
        )
        codes = sorted(r.status_code for r in results)
        assert codes[0] == 200 and all(c in (404, 409, 422) for c in codes[1:]), codes
        assert await _get_balance(client, headers, employee_id) == "5.00"
        reversals = [
            e for e in await _ledger(company_id, employee_id) if e["entry_type"] == "ADJUSTMENT"
        ]
        # the opening-balance adjustment plus exactly one reversal
        assert len(reversals) == 2

        # a later retry of the same cancel changes nothing
        retry = await _cancel(client, headers, approved, reason="dup")
        assert retry.status_code in (404, 409, 422)
        assert await _get_balance(client, headers, employee_id) == "5.00"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_approve_racing_cancel_leaves_a_consistent_ledger(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, approval_chain="HR", balance="5.00")
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]
        pending = (
            await _submit(client, headers, employee_id=employee_id, leave_type_id=leave_type_id)
        ).json()["data"]
        approve, cancel = await asyncio.gather(
            _approve(client, headers, pending), _cancel(client, headers, pending)
        )
        final = (
            await client.get(f"/v1/leave-applications/{pending['id']}", headers=headers)
        ).json()["data"]
        assert [approve.status_code, cancel.status_code].count(200) >= 1
        balance = await _get_balance(client, headers, employee_id)
        if final["status"] == "CANCELLED":
            # whatever happened in between, a cancelled application holds no balance or projection
            assert balance == "5.00"
        else:
            assert final["status"] == "APPROVED" and balance == "4.00"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# ------------------------------------------------------------------------------ PRA-07


async def _accrual_setup(client: AsyncClient, headers: dict, joins: list[tuple[str, str]]):
    legal_entity = await accrual_helpers._create_legal_entity(client, headers)
    employees = []
    for name, joining in joins:
        employee = await accrual_helpers._create_employee(client, headers, name)
        await accrual_helpers._create_employment(
            client,
            headers,
            employee_id=employee["id"],
            legal_entity_id=legal_entity["id"],
            joining_date=joining,
        )
        employees.append(employee)
    leave_type = await accrual_helpers._create_leave_type(client, headers)
    await accrual_helpers._create_published_monthly_policy(
        client, headers, leave_type_id=leave_type["id"]
    )
    return employees, legal_entity


async def test_one_employees_accrual_failure_does_not_stop_the_company_and_a_retry_completes_it(
    client: AsyncClient, seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, company_id, user_id = await accrual_helpers._register_tenant(client)
    try:
        (first, second), _ = await _accrual_setup(
            client, headers, [("Asha", "2025-01-01"), ("Bina", "2025-01-01")]
        )
        real = LeaveAccrualService._accrue_employee_month

        async def failing_for_first(self, company, employee_id, *args, **kwargs):  # type: ignore[no-untyped-def]
            if str(employee_id) == first["id"]:
                raise RuntimeError("boom")
            return await real(self, company, employee_id, *args, **kwargs)

        monkeypatch.setattr(LeaveAccrualService, "_accrue_employee_month", failing_for_first)
        written = await accrual_helpers._run_accrual(company_id, as_of=date(2026, 3, 1))
        assert written == 1
        assert await accrual_helpers._get_balance(client, headers, second["id"]) == "1.50"
        assert await _ledger(company_id, first["id"]) == []

        # the retry (next day's run) accrues the missed employee and double-credits nobody
        monkeypatch.setattr(LeaveAccrualService, "_accrue_employee_month", real)
        assert await accrual_helpers._run_accrual(company_id, as_of=date(2026, 3, 2)) == 1
        assert await accrual_helpers._get_balance(client, headers, first["id"]) == "1.50"
        assert await accrual_helpers._get_balance(client, headers, second["id"]) == "1.50"
        assert await accrual_helpers._run_accrual(company_id, as_of=date(2026, 3, 3)) == 0
    finally:
        await accrual_helpers._teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_accrual_across_the_employment_lifecycle(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """February 2026 (28 days, rate 1.50): a full-month employee, one who leaves on the 14th (last
    working day counts), one who joins after the month, and one rehired inside it (two spells)."""
    headers, company_id, user_id = await accrual_helpers._register_tenant(client)
    try:
        (full, leaver, future, rehired), legal_entity = await _accrual_setup(
            client,
            headers,
            [
                ("Asha", "2025-01-01"),
                ("Bina", "2025-01-01"),
                ("Chitra", "2026-03-10"),
                ("Divya", "2025-01-01"),
            ],
        )
        for person, last_day in ((leaver, "2026-02-14"), (rehired, "2026-02-07")):
            employment = (
                await client.get(f"/v1/employees/{person['id']}/employments", headers=headers)
            ).json()["data"][0]
            ended = await client.post(
                f"/v1/employees/{person['id']}/employments/{employment['id']}/terminate",
                headers={**headers, "If-Match": str(employment["version"])},
                json={"last_working_day": last_day},
            )
            assert ended.status_code == 200, ended.text
        # rehired on the 15th: spells 1-7 Feb (7 days) and 15-28 Feb (14 days) = 21 of 28
        rehire = await client.post(
            f"/v1/employees/{rehired['id']}/employments",
            headers=headers,
            json={"legal_entity_id": legal_entity["id"], "joining_date": "2026-02-15"},
        )
        assert rehire.status_code == 201, rehire.text

        await accrual_helpers._run_accrual(company_id, as_of=date(2026, 3, 1))

        assert await accrual_helpers._get_balance(client, headers, full["id"]) == "1.50"
        # 14 of 28 days -> 0.75
        assert await accrual_helpers._get_balance(client, headers, leaver["id"]) == "0.75"
        # 21 of 28 days -> 1.125 -> 1.13 (both spells counted, not just the first)
        assert await accrual_helpers._get_balance(client, headers, rehired["id"]) == "1.13"
        # not employed during February at all: nothing accrued
        assert await _ledger(company_id, future["id"]) == []
    finally:
        await accrual_helpers._teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_truly_concurrent_accrual_runs_credit_each_employee_once(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await accrual_helpers._register_tenant(client)
    try:
        (first, second), _ = await _accrual_setup(
            client, headers, [("Asha", "2025-01-01"), ("Bina", "2025-01-01")]
        )
        results = await asyncio.gather(
            *[accrual_helpers._run_accrual(company_id, as_of=date(2026, 3, 1)) for _ in range(4)]
        )
        assert sum(results) == 2
        for person in (first, second):
            assert await accrual_helpers._get_balance(client, headers, person["id"]) == "1.50"
            assert len(await _ledger(company_id, person["id"])) == 1
    finally:
        await accrual_helpers._teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_one_company_failing_does_not_stop_another_companys_accrual(
    client: AsyncClient, seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    a_headers, a_company, a_user = await accrual_helpers._register_tenant(client)
    b_headers, b_company, b_user = await accrual_helpers._register_tenant(client)
    real = LeaveAccrualService.run_for_company
    try:
        (a_emp,), _ = await _accrual_setup(client, a_headers, [("Asha", "2025-01-01")])
        (b_emp,), _ = await _accrual_setup(client, b_headers, [("Bina", "2025-01-01")])

        async def failing_for_a(self, company_id, **kwargs):  # type: ignore[no-untyped-def]
            if company_id == a_company:
                raise RuntimeError("company A is broken")
            return await real(self, company_id, **kwargs)

        monkeypatch.setattr(LeaveAccrualService, "run_for_company", failing_for_a)
        with _frozen_now(datetime(2026, 2, 28, 19, 30, tzinfo=UTC)):  # 01:00 IST on 1 Mar
            outcomes = await asyncio.gather(
                leave_tasks._accrue_company_async(a_company),
                leave_tasks._accrue_company_async(b_company),
                return_exceptions=True,
            )
        assert isinstance(outcomes[0], RuntimeError) and outcomes[1] == 1
        assert await accrual_helpers._get_balance(client, b_headers, b_emp["id"]) == "1.50"
        assert await _ledger(a_company, a_emp["id"]) == []
    finally:
        monkeypatch.setattr(LeaveAccrualService, "run_for_company", real)
        await accrual_helpers._teardown(company_id=a_company)
        await accrual_helpers._teardown(company_id=b_company)
        await _cleanup(company_id=a_company, user_id=a_user)
        await _cleanup(company_id=b_company, user_id=b_user)


async def test_accrual_task_repairs_a_missed_first_day_but_stays_quiet_late_in_the_month(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await accrual_helpers._register_tenant(client)
    try:
        run = "hrms.modules.leave.service.LeaveAccrualService.run_for_company"
        # the Beat entry is daily, not day-1-only
        schedule = celery_app.conf.beat_schedule["leave-run-monthly-accrual"]["schedule"]
        assert isinstance(schedule, crontab) and schedule.day_of_month == set(range(1, 32))

        for instant, expect_runs, as_of in (
            (
                datetime(2026, 2, 28, 19, 30, tzinfo=UTC),
                1,
                date(2026, 3, 1),
            ),  # 01:00 IST on the 1st
            (datetime(2026, 3, 2, 19, 30, tzinfo=UTC), 1, date(2026, 3, 3)),  # the 3rd: repair run
            (datetime(2026, 3, 10, 19, 30, tzinfo=UTC), 0, None),  # the 11th: outside the window
        ):
            with _frozen_now(instant), patch(run, new_callable=AsyncMock, return_value=0) as mock:
                await leave_tasks._accrue_company_async(company_id)
            assert mock.await_count == expect_runs
            if expect_runs:
                assert mock.await_args.kwargs["as_of"] == as_of
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


# ------------------------------------------------------------------------------ PRA-16


async def test_runtime_role_cannot_rewrite_or_erase_leave_history() -> None:
    async with get_session_factory()() as session:
        for table in ("leave_ledger", "leave_application_action", "audit_log"):
            for privilege in ("UPDATE", "DELETE", "TRUNCATE"):
                allowed = (
                    await session.execute(
                        text("SELECT has_table_privilege('hrms_app', :t, :p)"),
                        {"t": table, "p": privilege},
                    )
                ).scalar_one()
                assert allowed is False, f"hrms_app can still {privilege} {table}"
            for privilege in ("INSERT", "SELECT"):
                allowed = (
                    await session.execute(
                        text("SELECT has_table_privilege('hrms_app', :t, :p)"),
                        {"t": table, "p": privilege},
                    )
                ).scalar_one()
                assert allowed is True
        # the workflow tables that legitimately change state keep their rights
        assert (
            await session.execute(
                text("SELECT has_table_privilege('hrms_app', 'leave_application', 'UPDATE')")
            )
        ).scalar_one() is True


async def test_every_balance_mutation_carries_a_source_reason_and_actor(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, approval_chain="AUTO", balance="5.00")
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]
        approved = (
            await _submit(client, headers, employee_id=employee_id, leave_type_id=leave_type_id)
        ).json()["data"]
        await _cancel(client, headers, approved, reason="HR cancelled")

        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(company_id))
            rows = (
                await session.execute(
                    text(
                        "SELECT entry_type, reason, reference_id, created_by_user_id "
                        "FROM leave_ledger WHERE employee_id = CAST(:e AS uuid)"
                    ),
                    {"e": employee_id},
                )
            ).all()
            audits = (
                (
                    await session.execute(
                        text(
                            "SELECT action FROM audit_log WHERE entity_type IN "
                            "('leave_application', 'leave_ledger')"
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert len(rows) == 3  # opening adjustment, APPLICATION debit, reversal
        assert all(r.reason and r.created_by_user_id for r in rows)
        by_type = {(r.entry_type, r.reference_id is not None) for r in rows}
        assert ("APPLICATION", True) in by_type  # the debit points at its application
        assert {
            "LEAVE_APPLICATION_SUBMITTED",
            "LEAVE_APPLICATION_APPROVED",
            "LEAVE_APPLICATION_CANCELLED",
            "LEAVE_LEDGER_ADJUSTMENT_CREATED",
        } <= set(audits)
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
