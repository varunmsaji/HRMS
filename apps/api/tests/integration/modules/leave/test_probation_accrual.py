"""R-11 (D-13): monthly accrual leaves out probation days, judged by `probation_end_date` rather
than by the employee's status on the day the job runs, and confirmation records that date."""

from datetime import date, timedelta
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.leave.test_leave_accrual import (
    _create_employee,
    _create_leave_type,
    _create_legal_entity,
    _create_published_monthly_policy,
    _get_balance,
    _register_tenant,
    _run_accrual,
    _teardown,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.shared.business_time import business_today

pytestmark = pytest.mark.asyncio


async def _hire(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    joining_date: str = "2025-01-01",
    probation_end_date: str | None = None,
) -> dict[str, Any]:
    employee = await _create_employee(client, headers)
    legal_entity = await _create_legal_entity(client, headers)
    response = await client.post(
        f"/v1/employees/{employee['id']}/employments",
        headers=headers,
        json={
            "legal_entity_id": legal_entity["id"],
            "joining_date": joining_date,
            "probation_end_date": probation_end_date,
        },
    )
    assert response.status_code == 201, response.text
    return employee


async def _confirm(client: AsyncClient, headers: dict[str, str], employee_id: str) -> None:
    current = await client.get(f"/v1/employees/{employee_id}", headers=headers)
    assert current.json()["data"]["status"] == "PROBATION"
    confirmed = await client.post(
        f"/v1/employees/{employee_id}/confirm",
        headers={**headers, "If-Match": str(current.json()["data"]["version"])},
        json={},
    )
    assert confirmed.status_code == 200, confirmed.text


async def _probation_end(
    client: AsyncClient, headers: dict[str, str], employee_id: str
) -> str | None:
    response = await client.get(f"/v1/employees/{employee_id}/employments", headers=headers)
    assert response.status_code == 200, response.text
    (employment,) = response.json()["data"]
    return employment["probation_end_date"]


async def _company_yesterday(company_id: UUID) -> date:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        tz = (
            await session.execute(
                text("SELECT timezone FROM company WHERE id = :cid"), {"cid": str(company_id)}
            )
        ).scalar_one()
    return business_today(tz) - timedelta(days=1)


@pytest.mark.parametrize(
    ("accrue_during_probation", "balance"),
    [
        # February 2026 has 28 days; probation ends on the 14th, so 14 days earn 0.75.
        (False, "0.75"),
        # The policy accrues during probation: the whole month earns, as before.
        (True, "1.50"),
    ],
)
async def test_the_confirmation_month_leaves_out_probation_days(
    client: AsyncClient,
    seeded_plan_catalogue: None,
    accrue_during_probation: bool,
    balance: str,
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _hire(client, headers, probation_end_date="2026-02-14")
        await _confirm(client, headers, employee["id"])
        leave_type = await _create_leave_type(client, headers)
        await _create_published_monthly_policy(
            client,
            headers,
            leave_type_id=leave_type["id"],
            accrue_during_probation=accrue_during_probation,
        )

        written = await _run_accrual(company_id, as_of=date(2026, 3, 1))
        assert written == 1
        assert await _get_balance(client, headers, employee["id"]) == balance
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_a_month_wholly_on_probation_earns_nothing_after_confirmation(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Confirmed before the job runs, but probation covered all of January: no credit, the same
    as if the job had run while the employee was still on probation."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _hire(client, headers, probation_end_date="2026-02-14")
        await _confirm(client, headers, employee["id"])
        leave_type = await _create_leave_type(client, headers)
        await _create_published_monthly_policy(
            client, headers, leave_type_id=leave_type["id"], accrue_during_probation=False
        )

        assert await _run_accrual(company_id, as_of=date(2026, 2, 1)) == 0
        assert await _run_accrual(company_id, as_of=date(2026, 4, 1)) == 1
        # Only March, in full.
        assert await _get_balance(client, headers, employee["id"]) == "1.50"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.parametrize(
    ("entered", "expected"),
    [
        (None, "yesterday"),  # nothing entered: the day before confirmation
        ("2099-12-31", "yesterday"),  # a planned later date: confirmation ends probation sooner
        ("2025-06-30", "2025-06-30"),  # an earlier date HR entered is kept
    ],
)
async def test_confirmation_records_the_end_of_probation(
    client: AsyncClient,
    seeded_plan_catalogue: None,
    entered: str | None,
    expected: str,
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _hire(client, headers, probation_end_date=entered)
        await _confirm(client, headers, employee["id"])

        if expected == "yesterday":
            expected = (await _company_yesterday(company_id)).isoformat()
        assert await _probation_end(client, headers, employee["id"]) == expected
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
