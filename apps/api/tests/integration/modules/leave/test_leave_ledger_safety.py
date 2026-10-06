"""Leave ledger safety: LM-02 (balance locks on encashment and adjustment), LM-07 (tenant-safe
adjustment targets and numeric bounds) and decision 14 (closed/finalised periods).

The race tests run real concurrent requests against PostgreSQL (advisory locks, optimistic
versions); nothing about the locking is mocked, and each race is repeated so a one-in-a-few
interleaving does not slip through.
"""

import asyncio
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.test_attendance_period import (
    _cleanup_attendance_period,
    _insert_closed_period,
)
from tests.integration.modules.leave.test_leave_application import (
    _get_balance,
    _register_tenant,
    _setup_full,
    _submit,
    _teardown,
)
from tests.integration.modules.leave.test_leave_encashment import _encash
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.core.db.session import get_session_factory, set_rls_company_id

pytestmark = pytest.mark.asyncio

_RACE_ROUNDS = 4


async def _adjust(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    employee_id: str,
    leave_type_id: str,
    amount: str,
    effective_date: str = "2026-09-08",
) -> Any:
    return await client.post(
        "/v1/leave-ledger/adjustments",
        headers=headers,
        json={
            "employee_id": employee_id,
            "leave_type_id": leave_type_id,
            "amount": amount,
            "effective_date": effective_date,
            "reason": "safety test",
        },
    )


async def _ledger_sum(company_id: UUID, employee_id: str) -> Decimal:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        row = await session.execute(
            text(
                "SELECT coalesce(sum(amount), 0) FROM leave_ledger "
                "WHERE employee_id = CAST(:e AS uuid) AND company_id = CAST(:c AS uuid)"
            ),
            {"e": employee_id, "c": str(company_id)},
        )
        return Decimal(row.scalar_one())


async def _ledger_rows(company_id: str | UUID, employee_id: str) -> int:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        row = await session.execute(
            text(
                "SELECT count(*) FROM leave_ledger WHERE employee_id = CAST(:e AS uuid) "
                "AND company_id = CAST(:c AS uuid)"
            ),
            {"e": employee_id, "c": str(company_id)},
        )
        return int(row.scalar_one())


async def _approve(
    client: AsyncClient, headers: dict[str, str], application: dict[str, Any]
) -> Any:
    return await client.post(
        f"/v1/leave-applications/{application['id']}/approve",
        headers={**headers, "If-Match": str(application["version"])},
        json={},
    )


# --------------------------------------------------------------------------------------------
# LM-07 - tenant-safe targets, numeric bounds
# --------------------------------------------------------------------------------------------


async def test_adjustment_and_encashment_for_another_tenants_employee_are_not_found(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        ctx_a = await _setup_full(client, headers_a, encashment_allowed=True)
        ctx_b = await _setup_full(client, headers_b, encashment_allowed=True)
        foreign_employee = ctx_b["employee"]["id"]
        rows_before = await _ledger_rows(company_b, foreign_employee)

        adjusted = await _adjust(
            client,
            headers_a,
            employee_id=foreign_employee,
            leave_type_id=ctx_a["leave_type"]["id"],
            amount="5.00",
        )
        assert adjusted.status_code == 404, adjusted.text
        encashed = await _encash(
            client,
            headers_a,
            employee_id=foreign_employee,
            leave_type_id=ctx_a["leave_type"]["id"],
            days="1.00",
        )
        assert encashed.status_code == 404, encashed.text
        submitted = await _submit(
            client,
            headers_a,
            employee_id=foreign_employee,
            leave_type_id=ctx_a["leave_type"]["id"],
        )
        assert submitted.status_code == 404, submitted.text

        # nothing was written under either tenant for that employee id
        assert await _ledger_rows(company_a, foreign_employee) == 0
        assert await _ledger_rows(company_b, foreign_employee) == rows_before
        # an id that exists nowhere answers identically, so existence is not revealed
        unknown = await _adjust(
            client,
            headers_a,
            employee_id="00000000-0000-4000-8000-000000000001",
            leave_type_id=ctx_a["leave_type"]["id"],
            amount="5.00",
        )
        assert unknown.status_code == 404, unknown.text
        assert unknown.json()["error"]["code"] == adjusted.json()["error"]["code"]
    finally:
        await _teardown(company_id=company_a)
        await _teardown(company_id=company_b)
        await _cleanup(company_id=company_a, user_id=user_a)
        await _cleanup(company_id=company_b, user_id=user_b)


@pytest.mark.parametrize(
    ("amount", "valid"),
    [
        ("9999.99", True),
        ("-9999.99", True),
        ("10000.00", False),
        ("-10000", False),
        ("1.234", False),
        ("0", False),
    ],
)
async def test_adjustment_amount_is_bounded_to_what_the_ledger_stores(
    client: AsyncClient, seeded_plan_catalogue: None, amount: str, valid: bool
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers)
        response = await _adjust(
            client,
            headers,
            employee_id=ctx["employee"]["id"],
            leave_type_id=ctx["leave_type"]["id"],
            amount=amount,
        )
        if valid:
            assert response.status_code == 201, response.text
        else:
            assert response.status_code == 422, response.text
            assert response.json()["error"]["code"] == "REQUEST_VALIDATION_ERROR"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_encashment_days_are_bounded(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, encashment_allowed=True)
        for days in ("10000", "1.234", "0", "-1"):
            response = await _encash(
                client,
                headers,
                employee_id=ctx["employee"]["id"],
                leave_type_id=ctx["leave_type"]["id"],
                days=days,
            )
            assert response.status_code == 422, (days, response.text)
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# --------------------------------------------------------------------------------------------
# LM-02 - concurrency
# --------------------------------------------------------------------------------------------


async def test_concurrent_encashments_cannot_overdraw_the_balance(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Encashment x encashment. Balance 5, two requests of 3 days: both used to read 5 and both
    passed the minimum-balance check. Under the balance lock exactly one wins, every round."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(
            client, headers, approval_chain="AUTO", balance="5.00", encashment_allowed=True
        )
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]
        for _ in range(_RACE_ROUNDS):
            current = Decimal(await _get_balance(client, headers, employee_id))
            if current < Decimal("5.00"):
                await _adjust(
                    client,
                    headers,
                    employee_id=employee_id,
                    leave_type_id=leave_type_id,
                    amount=str(Decimal("5.00") - current),
                )
            results = await asyncio.gather(
                *[
                    _encash(
                        client,
                        headers,
                        employee_id=employee_id,
                        leave_type_id=leave_type_id,
                        days="3.00",
                    )
                    for _ in range(2)
                ]
            )
            assert sorted(r.status_code for r in results) == [201, 422], [r.text for r in results]
            loser = next(r for r in results if r.status_code == 422)
            assert loser.json()["error"]["code"] == "LEAVE_ENCASHMENT_MINIMUM_BALANCE_VIOLATION"
            assert await _get_balance(client, headers, employee_id) == "2.00"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_concurrent_encashment_and_approval_cannot_spend_one_balance_twice(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Encashment x approval. One day of balance; the encashment and the approval of a one-day
    leave each need it. Exactly one succeeds and the balance never goes negative."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(
            client, headers, approval_chain="HR", balance="1.00", encashment_allowed=True
        )
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]
        days = ["2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11"]
        for index in range(_RACE_ROUNDS):
            current = Decimal(await _get_balance(client, headers, employee_id))
            if current < Decimal("1.00"):
                await _adjust(
                    client,
                    headers,
                    employee_id=employee_id,
                    leave_type_id=leave_type_id,
                    amount=str(Decimal("1.00") - current),
                )
            application = (
                await _submit(
                    client,
                    headers,
                    employee_id=employee_id,
                    leave_type_id=leave_type_id,
                    start_date=days[index],
                    end_date=days[index],
                )
            ).json()["data"]
            approval, encashment = await asyncio.gather(
                _approve(client, headers, application),
                _encash(
                    client,
                    headers,
                    employee_id=employee_id,
                    leave_type_id=leave_type_id,
                    days="1.00",
                ),
            )
            assert sorted([approval.status_code, encashment.status_code]) in (
                [200, 422],
                [201, 409],
            ), (approval.text, encashment.text)
            assert await _get_balance(client, headers, employee_id) == "0.00"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_concurrent_negative_adjustment_and_approval_stay_consistent(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Adjustment x approval. A manual debit is unconditional (HR may drive a balance below zero),
    so either order is a legal result: approval first leaves -1, adjustment first makes the
    approval refuse and leaves 0. What must never happen is a 500, a half-applied approval, or a
    ledger that disagrees with the application."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, approval_chain="HR", balance="1.00")
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]
        days = ["2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11"]
        for index in range(_RACE_ROUNDS):
            current = Decimal(await _ledger_sum(company_id, employee_id))
            if current != Decimal("1.00"):
                await _adjust(
                    client,
                    headers,
                    employee_id=employee_id,
                    leave_type_id=leave_type_id,
                    amount=str(Decimal("1.00") - current),
                )
            application = (
                await _submit(
                    client,
                    headers,
                    employee_id=employee_id,
                    leave_type_id=leave_type_id,
                    start_date=days[index],
                    end_date=days[index],
                )
            ).json()["data"]
            approval, adjustment = await asyncio.gather(
                _approve(client, headers, application),
                _adjust(
                    client,
                    headers,
                    employee_id=employee_id,
                    leave_type_id=leave_type_id,
                    amount="-1.00",
                ),
            )
            assert adjustment.status_code == 201, adjustment.text
            assert approval.status_code in (200, 409), approval.text
            total = await _ledger_sum(company_id, employee_id)
            # approval won: -1 (debit and adjustment both landed); approval lost: 0
            assert total == (Decimal("-1.00") if approval.status_code == 200 else Decimal("0.00"))
            fetched = await client.get(
                f"/v1/leave-applications/{application['id']}", headers=headers
            )
            assert fetched.json()["data"]["status"] == (
                "APPROVED" if approval.status_code == 200 else "SUBMITTED"
            )
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# --------------------------------------------------------------------------------------------
# Decision 14 - closed / finalised periods
# --------------------------------------------------------------------------------------------


async def _period_id(company_id: UUID, period_start: str) -> UUID:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        row = await session.execute(
            text(
                "SELECT id FROM attendance_period WHERE company_id = CAST(:c AS uuid) "
                "AND period_start = :s"
            ),
            {"c": str(company_id), "s": date.fromisoformat(period_start)},
        )
        return UUID(str(row.scalar_one()))


async def _insert_finalised_run(company_id: UUID, attendance_period_id: UUID) -> None:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        await session.execute(
            text(
                """
                INSERT INTO pay_run (company_id, legal_entity_id, period_month, period_start,
                    period_end, days_in_month, status, pay_date, attendance_period_id,
                    attendance_period_version)
                SELECT company_id, legal_entity_id, DATE '2026-08-01', DATE '2026-08-01',
                    DATE '2026-08-31', 31, 'FINALISED', DATE '2026-09-01', id, version
                FROM attendance_period WHERE id = :p
                """
            ),
            {"p": str(attendance_period_id)},
        )
        await session.commit()


async def _drop_pay_runs(company_id: UUID) -> None:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        await session.execute(
            text("DELETE FROM pay_run WHERE company_id = :c"), {"c": str(company_id)}
        )
        await session.commit()


async def test_adjustment_and_encashment_respect_open_and_closed_periods(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(
            client, headers, approval_chain="AUTO", balance="10.00", encashment_allowed=True
        )
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]
        await _insert_closed_period(
            company_id=company_id, period_start="2026-08-01", period_end="2026-08-31"
        )
        rows_before = await _ledger_rows(company_id, employee_id)

        # closed period -> refused, with the dedicated code and the period's bounds
        refused_adjust = await _adjust(
            client,
            headers,
            employee_id=employee_id,
            leave_type_id=leave_type_id,
            amount="3.00",
            effective_date="2026-08-15",
        )
        assert refused_adjust.status_code == 409, refused_adjust.text
        error = refused_adjust.json()["error"]
        assert error["code"] == "LEAVE_LEDGER_PERIOD_CLOSED"
        assert error["details"][0]["context"]["period_start"] == "2026-08-01"
        assert error["details"][0]["context"]["period_end"] == "2026-08-31"
        refused_encash = await _encash(
            client,
            headers,
            employee_id=employee_id,
            leave_type_id=leave_type_id,
            days="1.00",
            effective_date="2026-08-31",
        )
        assert refused_encash.status_code == 409, refused_encash.text
        assert refused_encash.json()["error"]["code"] == "LEAVE_LEDGER_PERIOD_CLOSED"

        # history untouched: no row written, balance unchanged
        assert await _ledger_rows(company_id, employee_id) == rows_before
        assert await _get_balance(client, headers, employee_id) == "10.00"

        # the retry, dated in an open period, is the way to record the correction
        retried = await _adjust(
            client,
            headers,
            employee_id=employee_id,
            leave_type_id=leave_type_id,
            amount="3.00",
            effective_date="2026-09-08",
        )
        assert retried.status_code == 201, retried.text
        assert await _get_balance(client, headers, employee_id) == "13.00"
        encashed = await _encash(
            client,
            headers,
            employee_id=employee_id,
            leave_type_id=leave_type_id,
            days="1.00",
            effective_date="2026-09-01",
        )
        assert encashed.status_code == 201, encashed.text
        assert await _get_balance(client, headers, employee_id) == "12.00"
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_adjustment_and_encashment_refused_in_a_finalised_payroll_period(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(
            client, headers, approval_chain="AUTO", balance="10.00", encashment_allowed=True
        )
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]
        await _insert_closed_period(
            company_id=company_id, period_start="2026-08-01", period_end="2026-08-31"
        )
        await _insert_finalised_run(company_id, await _period_id(company_id, "2026-08-01"))
        rows_before = await _ledger_rows(company_id, employee_id)

        for response in (
            await _adjust(
                client,
                headers,
                employee_id=employee_id,
                leave_type_id=leave_type_id,
                amount="2.00",
                effective_date="2026-08-20",
            ),
            await _encash(
                client,
                headers,
                employee_id=employee_id,
                leave_type_id=leave_type_id,
                days="1.00",
                effective_date="2026-08-20",
            ),
        ):
            assert response.status_code == 409, response.text
            assert response.json()["error"]["code"] == "LEAVE_LEDGER_PAYROLL_FINALISED"
        assert await _ledger_rows(company_id, employee_id) == rows_before
        assert await _get_balance(client, headers, employee_id) == "10.00"

        # a retry after the refusal, dated in the open period, succeeds
        retried = await _adjust(
            client,
            headers,
            employee_id=employee_id,
            leave_type_id=leave_type_id,
            amount="2.00",
            effective_date="2026-09-08",
        )
        assert retried.status_code == 201, retried.text
        assert await _get_balance(client, headers, employee_id) == "12.00"
    finally:
        await _drop_pay_runs(company_id)
        await _cleanup_attendance_period(company_id=company_id)
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_another_legal_entitys_closed_period_does_not_lock_the_ledger(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Periods belong to a legal entity (decision 14): another entity's closed period does not
    lock this employee's ledger dates."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, balance="10.00")
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]
        other = await client.post("/v1/legal-entities", headers=headers, json={"name": "Other"})
        assert other.status_code == 201, other.text
        await _insert_closed_period(
            company_id=company_id,
            period_start="2026-08-01",
            period_end="2026-08-31",
            legal_entity_id=other.json()["data"]["id"],
        )
        allowed = await _adjust(
            client,
            headers,
            employee_id=employee_id,
            leave_type_id=leave_type_id,
            amount="1.00",
            effective_date="2026-08-15",
        )
        assert allowed.status_code == 201, allowed.text
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
