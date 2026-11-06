"""R-12: cancelling approved leave from a leave year whose year end has already run re-applies
that year's rule to the refund, so the refund cannot escape the lapse or carry-forward cap."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.leave.test_leave_application import (
    _create_employee,
    _create_employment,
    _create_leave_type,
    _create_legal_entity,
    _get_balance,
    _give_balance,
    _register_tenant,
    _setup_calendar,
    _setup_leave_policy,
    _submit,
    _teardown,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.leave.service import LeaveAccrualService

pytestmark = pytest.mark.asyncio

_YEAR_START = date(2026, 1, 1)


async def _take_december_leave(
    client: AsyncClient, headers: dict[str, str], **version_extra: Any
) -> tuple[str, dict[str, Any]]:
    """10 days held in 2025, then 3 working days (Mon 22 to Wed 24 Dec 2025) auto-approved."""
    employee = await _create_employee(client, headers)
    legal_entity = await _create_legal_entity(client, headers)
    await _create_employment(
        client, headers, employee_id=employee["id"], legal_entity_id=legal_entity["id"]
    )
    leave_type = await _create_leave_type(client, headers)
    await _setup_calendar(client, headers)
    await _setup_leave_policy(client, headers, leave_type_id=leave_type["id"], **version_extra)
    await _give_balance(
        client,
        headers,
        employee_id=employee["id"],
        leave_type_id=leave_type["id"],
        amount="10.00",
        effective_date="2025-06-01",
    )
    submitted = await _submit(
        client,
        headers,
        employee_id=employee["id"],
        leave_type_id=leave_type["id"],
        start_date="2025-12-22",
        end_date="2025-12-24",
    )
    assert submitted.status_code == 201, submitted.text
    application = submitted.json()["data"]
    assert application["status"] == "APPROVED"
    assert await _get_balance(client, headers, employee["id"]) == "7.00"
    return employee["id"], application


async def _run_year_end(company_id: Any) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        await LeaveAccrualService(session).run_year_end_for_company(company_id, as_of=_YEAR_START)
        await session.commit()


async def _drop_year_setting(company_id: Any) -> None:
    """Reading the leave-year setting creates it, and the shared teardown does not remove it."""
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        await session.execute(
            text("DELETE FROM leave_year_setting WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.commit()


async def _cancel(
    client: AsyncClient, headers: dict[str, str], application: dict[str, Any]
) -> None:
    cancelled = await client.post(
        f"/v1/leave-applications/{application['id']}/cancel",
        headers={**headers, "If-Match": str(application["version"])},
        json={"reason": "Did not travel"},
    )
    assert cancelled.status_code == 200, cancelled.text


async def _ledger(client: AsyncClient, headers: dict[str, str], employee_id: str) -> list[Any]:
    response = await client.get(
        "/v1/leave-ledger", headers=headers, params={"employee_id": employee_id}
    )
    assert response.status_code == 200, response.text
    return list(response.json()["data"])


@pytest.mark.parametrize(
    ("policy", "after_year_end", "after_cancel", "encashed_now"),
    [
        # Cap 5: year end lapsed 2 of 7. Had the leave not been taken, 10 would have met the cap
        # and 5 would have lapsed, so all 3 refunded days lapse now.
        ({"year_end_action": "CARRY_FORWARD", "max_carry_forward_days": "5.00"}, "5.00", "5.00", 0),
        # Everything lapses at year end, the refund included.
        ({"year_end_action": "LAPSE"}, "0.00", "0.00", 0),
        # No cap: nothing lapses, so the whole refund stays (must not change).
        ({"year_end_action": "CARRY_FORWARD"}, "7.00", "10.00", 0),
        # Cap 5, encash at most 4: year end encashed 2. With the refund, 5 over the cap would have
        # meant 4 encashed and 1 lapsed: 2 more are encashed now and 1 lapses.
        (
            {
                "year_end_action": "ENCASH_EXCESS",
                "max_carry_forward_days": "5.00",
                "max_encashment_days": "4.00",
            },
            "5.00",
            "5.00",
            2,
        ),
    ],
)
async def test_a_refund_into_a_closed_year_follows_that_years_rule(
    client: AsyncClient,
    seeded_plan_catalogue: None,
    policy: dict[str, str],
    after_year_end: str,
    after_cancel: str,
    encashed_now: int,
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id, application = await _take_december_leave(client, headers, **policy)
        await _run_year_end(company_id)
        assert await _get_balance(client, headers, employee_id) == after_year_end

        await _cancel(client, headers, application)

        assert await _get_balance(client, headers, employee_id) == after_cancel
        entries = [e for e in await _ledger(client, headers, employee_id)]
        refunds = [
            e
            for e in entries
            if e["entry_type"] == "ADJUSTMENT" and e["reference_id"] == application["id"]
        ]
        assert sum(Decimal(e["amount"]) for e in refunds if Decimal(e["amount"]) > 0) == Decimal(
            "3.00"
        )
        encashments = [
            e
            for e in entries
            if e["entry_type"] == "ENCASHMENT" and e["reference_id"] == application["id"]
        ]
        assert sum(-Decimal(e["amount"]) for e in encashments) == Decimal(encashed_now)
    finally:
        await _teardown(company_id=company_id)
        await _drop_year_setting(company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_a_refund_before_year_end_runs_is_left_to_year_end(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The leave year has ended but its year end has not run: the refund lands in full and the
    year-end run, which reads the balance as it stands, applies the cap to it later."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id, application = await _take_december_leave(
            client, headers, year_end_action="CARRY_FORWARD", max_carry_forward_days="5.00"
        )
        await _cancel(client, headers, application)
        assert await _get_balance(client, headers, employee_id) == "10.00"

        await _run_year_end(company_id)
        assert await _get_balance(client, headers, employee_id) == "5.00"
    finally:
        await _teardown(company_id=company_id)
        await _drop_year_setting(company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
