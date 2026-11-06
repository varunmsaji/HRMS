"""Integration tests for Leave module L3 — the monthly accrual engine
(`LeaveAccrualService.run_for_company`, LEAVE_DECISION_LOG.md LD-06).

Tested at the service layer directly, not via HTTP — this is background-job business logic
invoked from `leave/tasks.py`'s Celery task, not a request-scoped route (mirrors how the rest of
this codebase has no precedent for testing Celery tasks through a worker; `run_for_company` is
the same coroutine the task calls via `asyncio.run`, so exercising it directly is exercising the
real code path minus the Celery/asyncio bridge itself).
"""

from datetime import date
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.organisation.test_registration_flow import _cleanup, _register

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.leave.service import LeaveAccrualService

pytestmark = pytest.mark.asyncio


async def _register_tenant(
    client: AsyncClient, **overrides: Any
) -> tuple[dict[str, str], UUID, UUID | None]:
    response, company_id, user_id = await _register(client, **overrides)
    assert response.status_code == 201, response.text
    assert company_id is not None
    data = response.json()["data"]
    return (
        {
            "Authorization": f"Bearer {data['access_token']}",
            "X-Company-Id": str(company_id),
        },
        company_id,
        user_id,
    )


async def _create_employee(
    client: AsyncClient, headers: dict[str, str], first_name: str = "Asha"
) -> dict[str, Any]:
    response = await client.post("/v1/employees", headers=headers, json={"first_name": first_name})
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _create_legal_entity(
    client: AsyncClient, headers: dict[str, str], name: str = "Acme Legal Entity"
) -> dict[str, Any]:
    response = await client.post("/v1/legal-entities", headers=headers, json={"name": name})
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _create_employment(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    employee_id: str,
    legal_entity_id: str,
    joining_date: str,
) -> dict[str, Any]:
    response = await client.post(
        f"/v1/employees/{employee_id}/employments",
        headers=headers,
        json={"legal_entity_id": legal_entity_id, "joining_date": joining_date},
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _create_leave_type(
    client: AsyncClient, headers: dict[str, str], **extra: Any
) -> dict[str, Any]:
    payload = {"code": "EL", "name": "Earned Leave", **extra}
    response = await client.post("/v1/leave-types", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _create_published_monthly_policy(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    leave_type_id: str,
    accrual_rate_per_cycle: str = "1.50",
    effective_from: str = "2025-01-01",
    **version_extra: Any,
) -> dict[str, Any]:
    policy_resp = await client.post(
        "/v1/leave-policies",
        headers=headers,
        json={"name": "Standard Earned Leave Policy", "leave_type_id": leave_type_id},
    )
    assert policy_resp.status_code == 201, policy_resp.text
    policy = dict(policy_resp.json()["data"])

    draft = await client.post(
        f"/v1/leave-policies/{policy['id']}/versions",
        headers=headers,
        json={
            "effective_from": effective_from,
            "accrual_frequency": "MONTHLY",
            "accrual_rate_per_cycle": accrual_rate_per_cycle,
            **version_extra,
        },
    )
    assert draft.status_code == 201, draft.text
    version_id = draft.json()["data"]["id"]

    published = await client.post(
        f"/v1/leave-policies/{policy['id']}/versions/{version_id}/publish",
        headers={**headers, "If-Match": "1"},
        json={},
    )
    assert published.status_code == 200, published.text

    assignment = await client.post(
        "/v1/policy-assignments",
        headers=headers,
        json={
            "policy_kind": "LEAVE_POLICY",
            "policy_id": policy["id"],
            "leave_type_id": leave_type_id,
            "scope_type": "COMPANY",
            "effective_from": effective_from,
        },
    )
    assert assignment.status_code == 201, assignment.text
    return policy


async def _teardown(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        for table in (
            "leave_ledger",
            "leave_year_end_run",
            "policy_assignment",
            "leave_policy_version",
            "leave_policy",
            "leave_type",
            "employment",
            "employee",
            "legal_entity",
            "number_series",
        ):
            await session.execute(
                text(f"DELETE FROM {table} WHERE company_id = :cid"), {"cid": str(company_id)}
            )
        await session.commit()


async def _run_accrual(company_id: UUID, *, as_of: date) -> int:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        written = await LeaveAccrualService(session).run_for_company(company_id, as_of=as_of)
        await session.commit()
        return written


async def _get_balance(client: AsyncClient, headers: dict[str, str], employee_id: str) -> str:
    response = await client.get(
        "/v1/leave-balances", headers=headers, params={"employee_id": employee_id}
    )
    assert response.status_code == 200, response.text
    return str(response.json()["data"][0]["balance"])


@pytest.mark.asyncio
async def test_full_month_accrual(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        legal_entity = await _create_legal_entity(client, headers)
        await _create_employment(
            client,
            headers,
            employee_id=employee["id"],
            legal_entity_id=legal_entity["id"],
            joining_date="2025-01-01",
        )
        leave_type = await _create_leave_type(client, headers)
        await _create_published_monthly_policy(client, headers, leave_type_id=leave_type["id"])

        # Runs on 2026-03-01 -> accrues for February 2026 (28 days), employee present the whole
        # month -> full rate, no proration.
        written = await _run_accrual(company_id, as_of=date(2026, 3, 1))
        assert written == 1
        assert await _get_balance(client, headers, employee["id"]) == "1.50"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_mid_month_joiner_prorated(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        legal_entity = await _create_legal_entity(client, headers)
        # Joins on day 15 of a 28-day February -> present 14 of 28 days -> half the rate.
        await _create_employment(
            client,
            headers,
            employee_id=employee["id"],
            legal_entity_id=legal_entity["id"],
            joining_date="2026-02-15",
        )
        leave_type = await _create_leave_type(client, headers)
        await _create_published_monthly_policy(client, headers, leave_type_id=leave_type["id"])

        written = await _run_accrual(company_id, as_of=date(2026, 3, 1))
        assert written == 1
        assert await _get_balance(client, headers, employee["id"]) == "0.75"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_accrual_is_idempotent_on_rerun(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        legal_entity = await _create_legal_entity(client, headers)
        await _create_employment(
            client,
            headers,
            employee_id=employee["id"],
            legal_entity_id=legal_entity["id"],
            joining_date="2025-01-01",
        )
        leave_type = await _create_leave_type(client, headers)
        await _create_published_monthly_policy(client, headers, leave_type_id=leave_type["id"])

        first_run = await _run_accrual(company_id, as_of=date(2026, 3, 1))
        assert first_run == 1
        second_run = await _run_accrual(company_id, as_of=date(2026, 3, 1))
        assert second_run == 0

        # Balance reflects exactly one accrual, not two.
        assert await _get_balance(client, headers, employee["id"]) == "1.50"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_concurrent_accrual_runs_credit_once(
    client: AsyncClient, seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DAT-001 — two Beat firings racing past the "already written?" check (simulated by making
    that check always answer no) still produce one ACCRUAL: the partial unique index turns the
    second insert into a no-op."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        legal_entity = await _create_legal_entity(client, headers)
        await _create_employment(
            client,
            headers,
            employee_id=employee["id"],
            legal_entity_id=legal_entity["id"],
            joining_date="2025-01-01",
        )
        leave_type = await _create_leave_type(client, headers)
        await _create_published_monthly_policy(client, headers, leave_type_id=leave_type["id"])

        from hrms.modules.leave.repository import LeaveLedgerRepository

        async def _never_written(*_args: Any, **_kwargs: Any) -> bool:
            return False

        monkeypatch.setattr(LeaveLedgerRepository, "exists_for_cycle", _never_written)
        assert await _run_accrual(company_id, as_of=date(2026, 3, 1)) == 1
        assert await _run_accrual(company_id, as_of=date(2026, 3, 1)) == 0
        assert await _get_balance(client, headers, employee["id"]) == "1.50"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_no_policy_assigned_skips_accrual(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        legal_entity = await _create_legal_entity(client, headers)
        await _create_employment(
            client,
            headers,
            employee_id=employee["id"],
            legal_entity_id=legal_entity["id"],
            joining_date="2025-01-01",
        )
        # Leave type exists, but no LeavePolicy/PolicyAssignment for it -> resolver finds
        # nothing, accrual is skipped rather than guessing a rate.
        await _create_leave_type(client, headers)

        written = await _run_accrual(company_id, as_of=date(2026, 3, 1))
        assert written == 0
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def _setup_accruing_employee(
    client: AsyncClient, headers: dict[str, str], **version_extra: Any
) -> str:
    employee = await _create_employee(client, headers)
    legal_entity = await _create_legal_entity(client, headers)
    await _create_employment(
        client,
        headers,
        employee_id=employee["id"],
        legal_entity_id=legal_entity["id"],
        joining_date="2025-01-01",
    )
    leave_type = await _create_leave_type(client, headers)
    await _create_published_monthly_policy(
        client, headers, leave_type_id=leave_type["id"], **version_extra
    )
    return str(employee["id"])


async def _run_due_months(company_id: UUID, *, as_of: date) -> int:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        written = await LeaveAccrualService(session).run_due_months(
            company_id, as_of=as_of, window_days=5
        )
        await session.commit()
        return written


@pytest.mark.asyncio
async def test_year_end_lapses_the_last_month_even_if_its_accrual_had_not_run(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """R-07 — the December accrual failed at 01:00; the 02:00 year end must not leave it to land
    afterwards, past the lapse."""
    from tests.integration.modules.leave.test_leave_year import _teardown_year_setting

    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = await _setup_accruing_employee(client, headers, year_end_action="LAPSE")
        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, str(company_id))
            await LeaveAccrualService(session).run_year_end_for_company(
                company_id, as_of=date(2026, 1, 1)
            )
            await session.commit()
        assert await _get_balance(client, headers, employee_id) == "0.00"

        assert await _run_accrual(company_id, as_of=date(2026, 1, 2)) == 0
        assert await _get_balance(client, headers, employee_id) == "0.00"
    finally:
        await _teardown_year_setting(company_id=company_id)
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_daily_run_catches_up_months_an_outage_skipped(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """R-08 — nothing ran in February or March. A run on 20 March writes January and February."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = await _setup_accruing_employee(client, headers)
        await _run_accrual(company_id, as_of=date(2026, 1, 1))
        assert await _get_balance(client, headers, employee_id) == "1.50"

        assert await _run_due_months(company_id, as_of=date(2026, 3, 20)) == 2
        assert await _get_balance(client, headers, employee_id) == "4.50"
        assert await _run_due_months(company_id, as_of=date(2026, 3, 21)) == 0
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_daily_run_outside_the_window_does_nothing_without_an_accrual_history(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = await _setup_accruing_employee(client, headers)
        assert await _run_due_months(company_id, as_of=date(2026, 3, 20)) == 0
        assert await _run_due_months(company_id, as_of=date(2026, 4, 5)) == 1
        assert await _get_balance(client, headers, employee_id) == "1.50"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_daily_run_catches_up_at_most_a_few_months(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        await _setup_accruing_employee(client, headers)
        await _run_accrual(company_id, as_of=date(2026, 1, 1))
        assert await _run_due_months(company_id, as_of=date(2026, 9, 20)) == 3
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_a_yearly_credit_does_not_hide_a_missed_monthly_run(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """R-08 — a yearly accrual dated at a leave-year start on 31 January is not a January
    monthly run. Run on 20 February, the catch-up must still write January."""
    from decimal import Decimal
    from uuid import uuid4

    from hrms.modules.leave.repository import LeaveLedgerRepository

    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = await _setup_accruing_employee(client, headers)
        await _run_accrual(company_id, as_of=date(2026, 1, 1))
        assert await _get_balance(client, headers, employee_id) == "1.50"

        # A second leave type credited yearly, at a leave-year start that falls on 31 January.
        casual = await _create_leave_type(client, headers, code="CL", name="Casual Leave")
        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, str(company_id))
            await LeaveLedgerRepository().insert(
                session,
                data={
                    "id": uuid4(),
                    "company_id": company_id,
                    "employee_id": UUID(employee_id),
                    "leave_type_id": UUID(casual["id"]),
                    "entry_type": "ACCRUAL",
                    "amount": Decimal("12.00"),
                    "effective_date": date(2026, 1, 31),
                    "reference_id": None,
                    "reason": "Yearly accrual for leave year starting 2026-01-31",
                    "created_by_user_id": None,
                },
            )
            await session.commit()

        assert await _run_due_months(company_id, as_of=date(2026, 2, 20)) == 1
        response = await client.get(
            "/v1/leave-balances", headers=headers, params={"employee_id": employee_id}
        )
        assert response.status_code == 200, response.text
        balances = {b["leave_type_id"]: b["balance"] for b in response.json()["data"]}
        assert balances[casual["id"]] == "12.00"
        assert len(balances) == 2
        earned = next(v for k, v in balances.items() if k != casual["id"])
        assert earned == "3.00"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
