"""Real-PostgreSQL races between a leave approval and the other things that touch the same
balance or period: the year-end sweep (LM-08), the comp-off expiry sweep, and attendance period
finalisation.

The balance races use a one-shot delay *after* the sweep's balance read (the exact window the
lock exists to close) so the interleaving is deterministic instead of a matter of luck; the
approval is started while the sweep is parked inside that window. With the per-(employee, type)
balance lock the approval simply waits for the sweep to commit and then decides on the new
balance; without it the approval would debit against the stale figure the sweep acted on.
"""

import asyncio
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.test_attendance_day import (
    _build_wired_employee,
    _cleanup_attendance_day,
)
from tests.integration.modules.attendance.test_attendance_period import (
    _cleanup_attendance_period,
    _create_period,
    _full_calculate,
)
from tests.integration.modules.leave import test_leave_year as year_helpers
from tests.integration.modules.leave.test_leave_application import (
    _cleanup,
    _create_employee,
    _create_employment,
    _create_leave_type,
    _create_legal_entity,
    _give_balance,
    _register_tenant,
    _setup_calendar,
    _setup_full,
    _setup_leave_policy,
    _submit,
    _teardown,
)

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.attendance.service import OvertimeRecordService
from hrms.modules.leave.repository import LeaveLedgerRepository
from hrms.modules.leave.service import LeaveCompOffService

pytestmark = pytest.mark.asyncio


async def _approve(
    client: AsyncClient, headers: dict[str, str], application: dict[str, Any]
) -> Any:
    return await client.post(
        f"/v1/leave-applications/{application['id']}/approve",
        headers={**headers, "If-Match": str(application["version"])},
        json={},
    )


def _park_first_balance_read(monkeypatch: pytest.MonkeyPatch, seconds: float) -> None:
    """The first `get_balance` call (the sweep's) returns its figure and then waits, holding
    whatever locks the caller took; later calls (the approval's) are untouched."""
    real = LeaveLedgerRepository.get_balance
    state = {"armed": True}

    async def parked(self: Any, *args: Any, **kwargs: Any) -> Decimal:
        value = await real(self, *args, **kwargs)
        if state["armed"]:
            state["armed"] = False
            await asyncio.sleep(seconds)
        return value

    monkeypatch.setattr(LeaveLedgerRepository, "get_balance", parked)


async def _delete_leave_rows(company_id: UUID) -> None:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        for table in (
            "leave_day_projection",
            "leave_application_day",
            "leave_application_action",
            "leave_application",
            "leave_ledger",
            "leave_year_end_run",
            "policy_assignment",
            "leave_policy_version",
            "leave_policy",
            "leave_type",
        ):
            await session.execute(
                text(f"DELETE FROM {table} WHERE company_id = :cid"), {"cid": str(company_id)}
            )
        await session.commit()


async def _ledger_total(company_id: UUID, employee_id: str) -> Decimal:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        row = await session.execute(
            text(
                "SELECT coalesce(sum(amount), 0) FROM leave_ledger "
                "WHERE company_id = CAST(:c AS uuid) AND employee_id = CAST(:e AS uuid)"
            ),
            {"c": str(company_id), "e": employee_id},
        )
        return Decimal(row.scalar_one())


async def test_year_end_and_approval_cannot_act_on_one_stale_balance(
    client: AsyncClient, seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Balance 5 against a carry-forward cap of 2, and a five-day approval waiting.

    Year-end first: it lapses 3, leaving 2, so the five-day approval must be refused. Approval
    first: balance 0, nothing to lapse. The anomaly the lock prevents: year-end reads 5 and lapses
    3, the approval (which checked 5) then debits 5, and the balance ends at -3."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(
            client, headers, approval_chain="HR", balance="5.00", max_carry_forward_days="2.00"
        )
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]
        application = (
            await _submit(
                client,
                headers,
                employee_id=employee_id,
                leave_type_id=leave_type_id,
                start_date="2026-09-08",
                end_date="2026-09-12",
            )
        ).json()["data"]
        assert application["total_days"] in ("5.00", 5, "5")

        _park_first_balance_read(monkeypatch, seconds=0.6)
        sweep = asyncio.create_task(year_helpers._run_year_end(company_id, as_of=date(2027, 1, 1)))
        await asyncio.sleep(0.2)  # the sweep is now parked after its balance read
        approval = await _approve(client, headers, application)
        written = await sweep

        total = await _ledger_total(company_id, employee_id)
        assert total >= 0, f"balance went negative: {total}"
        # the sweep held the lock, so the approval decided on the post-lapse balance
        assert (written, approval.status_code, total) == (1, 409, Decimal("2.00")), approval.text
        assert approval.json()["error"]["code"] == "LEAVE_APPLICATION_BALANCE_SHORTFALL"
    finally:
        await year_helpers._teardown_year_setting(company_id=company_id)
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_comp_off_expiry_and_approval_cannot_spend_one_credit_twice(
    client: AsyncClient, seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One comp-off day, expiring, and a one-day approval waiting. Expiry only offsets a credit
    the balance still covers; the approval only debits what is there. Whichever goes first, the
    other sees the result: balance 0, never -1."""
    headers, company_id, user_id = await _register_tenant(client)
    credit_reference = uuid4()
    try:
        employee = await _create_employee(client, headers)
        legal_entity = await _create_legal_entity(client, headers)
        await _create_employment(
            client, headers, employee_id=employee["id"], legal_entity_id=legal_entity["id"]
        )
        leave_type = await _create_leave_type(
            client, headers, code="CO", name="Comp off", is_comp_off=True
        )
        await _setup_calendar(client, headers)
        await _setup_leave_policy(
            client, headers, leave_type_id=leave_type["id"], approval_chain="HR"
        )
        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(company_id))
            await session.execute(
                text(
                    "INSERT INTO leave_ledger (id, company_id, employee_id, leave_type_id, "
                    "entry_type, amount, effective_date, reference_id, reason) VALUES "
                    "(gen_random_uuid(), :c, :e, :t, 'COMP_OFF_CREDIT', 1, DATE '2026-08-10', "
                    ":r, 'credit')"
                ),
                {
                    "c": company_id,
                    "e": UUID(employee["id"]),
                    "t": UUID(leave_type["id"]),
                    "r": credit_reference,
                },
            )
            await session.commit()

        class _Fact:
            overtime_record_id = credit_reference
            comp_off_expiry_date = date(2026, 11, 1)

        async def facts(self: Any, company: UUID) -> list[Any]:
            return [_Fact()]

        monkeypatch.setattr(OvertimeRecordService, "list_comp_off_facts", facts)

        application = (
            await _submit(
                client, headers, employee_id=employee["id"], leave_type_id=leave_type["id"]
            )
        ).json()["data"]

        _park_first_balance_read(monkeypatch, seconds=0.6)

        async def expire() -> int:
            async with get_session_factory()() as session:
                await set_rls_company_id(session, str(company_id))
                count = await LeaveCompOffService(session).expire_company(
                    company_id, as_of=date(2026, 12, 1)
                )
                await session.commit()
                return count

        sweep = asyncio.create_task(expire())
        await asyncio.sleep(0.2)
        approval = await _approve(client, headers, application)
        expired = await sweep

        total = await _ledger_total(company_id, employee["id"])
        assert total == Decimal("0.00"), f"balance {total} (approval {approval.status_code})"
        # the sweep was parked holding the lock, so it expired the credit first and the approval
        # then found nothing left to spend
        assert (expired, approval.status_code) == (1, 409), approval.text
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_approval_racing_period_finalisation_leaves_leave_and_attendance_consistent(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Approve x finalize on the same day, several rounds. Allowed outcomes: the approval wins and
    the day is frozen showing leave, or finalisation wins and the approval is refused with
    PERIOD_CLOSED (nothing debited, nothing projected). Never an approved leave, a debit and a
    projection sitting in a closed period whose frozen summary does not count it."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = str(wired["employee"]["id"])
        leave_type = await _create_leave_type(client, headers)
        await _setup_leave_policy(
            client, headers, leave_type_id=leave_type["id"], approval_chain="HR"
        )
        await _give_balance(
            client,
            headers,
            employee_id=employee_id,
            leave_type_id=leave_type["id"],
            amount="20.00",
        )
        outcomes: list[tuple[int, int]] = []
        for day in ("2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13"):
            await _full_calculate(client, headers, employee_id=employee_id, day=day)
            period = await _create_period(client, headers, period_start=day, period_end=day)
            application = (
                await _submit(
                    client,
                    headers,
                    employee_id=employee_id,
                    leave_type_id=leave_type["id"],
                    start_date=day,
                    end_date=day,
                )
            ).json()["data"]
            approval, finalize = await asyncio.gather(
                _approve(client, headers, application),
                client.post(
                    f"/v1/attendance-periods/{period['id']}/finalize",
                    headers={**headers, "If-Match": str(period["version"])},
                    json={},
                ),
            )
            outcomes.append((approval.status_code, finalize.status_code))
            assert approval.status_code in (200, 409), approval.text
            assert finalize.status_code in (200, 409, 422), finalize.text

            async with get_session_factory()() as session:
                await set_rls_company_id(session, str(company_id))
                projections = (
                    await session.execute(
                        text(
                            "SELECT count(*) FROM leave_day_projection WHERE company_id = "
                            "CAST(:c AS uuid) AND attendance_date = CAST(:d AS date) "
                            "AND status <> 'CANCELLED'"
                        ),
                        {"c": str(company_id), "d": date.fromisoformat(day)},
                    )
                ).scalar_one()
                summary_leave = (
                    await session.execute(
                        text(
                            "SELECT coalesce(sum(leave_days), 0) FROM "
                            "attendance_period_summary "
                            "WHERE attendance_period_id = CAST(:p AS uuid)"
                        ),
                        {"p": period["id"]},
                    )
                ).scalar_one()
            debits = await _ledger_total(company_id, employee_id)  # 20 minus (approved days so far)
            if approval.status_code == 409:
                assert projections == 0
            else:
                assert projections == 1
                if finalize.status_code == 200:
                    assert Decimal(summary_leave) == Decimal("1.00"), (
                        f"{day}: leave approved inside a finalised period but the frozen "
                        f"summary counts {summary_leave} leave days"
                    )
            assert debits >= Decimal("0")
        # at least one ordering must actually have been exercised
        assert outcomes
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _delete_leave_rows(company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def _calculate_without_punches(
    client: AsyncClient, headers: dict[str, str], employee_id: str, day: str
) -> None:
    response = await client.post(
        "/v1/attendance/days/calculate",
        headers=headers,
        params={"employee_id": employee_id, "date": day},
    )
    assert response.status_code == 200, response.text


async def _park_attendance_recalculation(monkeypatch: pytest.MonkeyPatch, *, after: bool) -> Any:
    """One-shot park of the attendance recalculation a leave approval triggers: before the real
    call (projection inserted, day not yet recalculated) or after it (day recalculated with the
    leave, approval not yet committed). Returns the real method for restoring."""
    from hrms.modules.attendance.service import AttendanceDayService

    real = AttendanceDayService.calculate
    state = {"armed": True}

    async def parked(self: Any, *args: Any, **kwargs: Any) -> Any:
        if state["armed"] and not after:
            state["armed"] = False
            await asyncio.sleep(0.8)
        result = await real(self, *args, **kwargs)
        if state["armed"] and after:
            state["armed"] = False
            await asyncio.sleep(0.8)
        return result

    monkeypatch.setattr(AttendanceDayService, "calculate", parked)
    return real


@pytest.mark.parametrize("park_after_recalculation", [False, True])
async def test_finalisation_waits_for_an_in_flight_approval_and_counts_its_leave(
    client: AsyncClient,
    seeded_plan_catalogue: None,
    monkeypatch: pytest.MonkeyPatch,
    park_after_recalculation: bool,
) -> None:
    """The window the plain race rarely hits: the approval is parked mid-flight (after its period
    check and projection, with or without the day already recalculated) when finalisation starts.
    Without ordering, finalisation froze the day from what it had read and the approval then
    committed leave into it: approved leave, a debit, and a frozen summary counting 0 leave days.
    With the shared/exclusive period lock the finalisation waits, then reads the committed leave."""
    from hrms.modules.attendance.service import AttendanceDayService

    headers, company_id, user_id = await _register_tenant(client)
    real = None
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = str(wired["employee"]["id"])
        leave_type = await _create_leave_type(client, headers)
        await _setup_leave_policy(
            client, headers, leave_type_id=leave_type["id"], approval_chain="HR"
        )
        await _give_balance(
            client, headers, employee_id=employee_id, leave_type_id=leave_type["id"]
        )
        day = "2026-08-10"
        await _calculate_without_punches(client, headers, employee_id, day)
        period = await _create_period(client, headers, period_start=day, period_end=day)
        application = (
            await _submit(
                client,
                headers,
                employee_id=employee_id,
                leave_type_id=leave_type["id"],
                start_date=day,
                end_date=day,
            )
        ).json()["data"]

        real = await _park_attendance_recalculation(monkeypatch, after=park_after_recalculation)
        approval_task = asyncio.create_task(_approve(client, headers, application))
        await asyncio.sleep(0.3)
        finalize = await client.post(
            f"/v1/attendance-periods/{period['id']}/finalize",
            headers={**headers, "If-Match": str(period["version"])},
            json={},
        )
        approval = await approval_task

        assert approval.status_code == 200, approval.text
        assert finalize.status_code == 200, finalize.text
        assert await _ledger_total(company_id, employee_id) == Decimal("19.00")
        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(company_id))
            summary_leave = (
                await session.execute(
                    text(
                        "SELECT coalesce(sum(leave_days), 0) FROM attendance_period_summary "
                        "WHERE attendance_period_id = CAST(:p AS uuid)"
                    ),
                    {"p": period["id"]},
                )
            ).scalar_one()
        assert Decimal(summary_leave) == Decimal("1.00"), (
            "leave was approved and committed while the period finalised, but the frozen "
            f"summary counts {summary_leave} leave days"
        )
    finally:
        if real is not None:
            monkeypatch.setattr(AttendanceDayService, "calculate", real)
        await _cleanup_attendance_period(company_id=company_id)
        await _delete_leave_rows(company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_an_approval_arriving_during_finalisation_is_refused_cleanly(
    client: AsyncClient, seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mirror image: finalisation is in flight (parked after it took its lock) and the
    approval arrives. It waits, then finds the period closed and is refused - application still
    SUBMITTED, nothing debited, nothing projected."""
    from hrms.modules.attendance.service import AttendancePeriodService

    headers, company_id, user_id = await _register_tenant(client)
    real_validation = AttendancePeriodService._run_validation
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = str(wired["employee"]["id"])
        leave_type = await _create_leave_type(client, headers)
        await _setup_leave_policy(
            client, headers, leave_type_id=leave_type["id"], approval_chain="HR"
        )
        await _give_balance(
            client, headers, employee_id=employee_id, leave_type_id=leave_type["id"]
        )
        day = "2026-08-10"
        await _calculate_without_punches(client, headers, employee_id, day)
        period = await _create_period(client, headers, period_start=day, period_end=day)
        application = (
            await _submit(
                client,
                headers,
                employee_id=employee_id,
                leave_type_id=leave_type["id"],
                start_date=day,
                end_date=day,
            )
        ).json()["data"]

        async def slow_validation(self: Any, *args: Any, **kwargs: Any) -> Any:
            result = await real_validation(self, *args, **kwargs)
            await asyncio.sleep(0.8)  # finalisation holds its lock, closing the period next
            return result

        monkeypatch.setattr(AttendancePeriodService, "_run_validation", slow_validation)
        finalize_task = asyncio.create_task(
            client.post(
                f"/v1/attendance-periods/{period['id']}/finalize",
                headers={**headers, "If-Match": str(period["version"])},
                json={},
            )
        )
        await asyncio.sleep(0.3)
        approval = await _approve(client, headers, application)
        finalize = await finalize_task

        assert finalize.status_code == 200, finalize.text
        assert approval.status_code == 409, approval.text
        assert approval.json()["error"]["code"] in (
            "LEAVE_APPLICATION_PERIOD_CLOSED",
            "ATTENDANCE_PERIOD_CLOSED",
        )
        fetched = await client.get(f"/v1/leave-applications/{application['id']}", headers=headers)
        assert fetched.json()["data"]["status"] == "SUBMITTED"
        assert await _ledger_total(company_id, employee_id) == Decimal("20.00")
    finally:
        monkeypatch.setattr(AttendancePeriodService, "_run_validation", real_validation)
        await _cleanup_attendance_period(company_id=company_id)
        await _delete_leave_rows(company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
