"""Integration tests for leave year configuration + the year-end sweep (LEAVE_DECISION_LOG.md
LD-20/LD-21, client spec §10).

Reuses `_create_employee`/`_create_employment`/`_create_legal_entity`/`_create_leave_type`/
`_setup_leave_policy`/`_give_balance`/`_get_balance`/`_register_tenant`/`_cleanup`/`_teardown`
from `test_leave_application.py` — the same cross-file reuse pattern every other Leave test file
in this suite already established.
"""

from datetime import date
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
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
from hrms.modules.leave.service import LeaveAccrualService

pytestmark = pytest.mark.asyncio


async def _run_year_end(company_id: UUID, *, as_of: date) -> int:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        written = await LeaveAccrualService(session).run_year_end_for_company(
            company_id, as_of=as_of
        )
        await session.commit()
        return written


async def _teardown_year_setting(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        await session.execute(
            text("DELETE FROM leave_year_setting WHERE company_id = :cid"),
            {"cid": str(company_id)},
        )
        await session.commit()


async def test_default_leave_year_setting_is_calendar(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.get("/v1/leave-year-setting", headers=headers)
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["leave_year_type"] == "CALENDAR"
        assert data["start_month"] is None
        assert data["start_day"] is None
    finally:
        await _teardown_year_setting(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_upsert_to_custom_round_trips(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        put = await client.put(
            "/v1/leave-year-setting",
            headers=headers,
            json={"leave_year_type": "CUSTOM", "start_month": 7, "start_day": 1},
        )
        assert put.status_code == 200, put.text
        assert put.json()["data"]["start_month"] == 7

        get = await client.get("/v1/leave-year-setting", headers=headers)
        assert get.json()["data"]["leave_year_type"] == "CUSTOM"
        assert get.json()["data"]["start_day"] == 1
    finally:
        await _teardown_year_setting(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_custom_without_start_fields_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.put(
            "/v1/leave-year-setting", headers=headers, json={"leave_year_type": "CUSTOM"}
        )
        assert response.status_code == 422, response.text
    finally:
        await _teardown_year_setting(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_non_custom_with_start_fields_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.put(
            "/v1/leave-year-setting",
            headers=headers,
            json={"leave_year_type": "CALENDAR", "start_month": 1, "start_day": 1},
        )
        assert response.status_code == 422, response.text
    finally:
        await _teardown_year_setting(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_yearly_accrual_credited_on_leave_year_start_and_is_idempotent(
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
            joining_date="2020-01-01",
        )
        leave_type = await _create_leave_type(client, headers)
        await _setup_leave_policy(
            client,
            headers,
            leave_type_id=leave_type["id"],
            approval_chain="AUTO",
            accrual_frequency="YEARLY",
            accrual_rate_per_cycle="12.00",
        )

        # Default CALENDAR leave year -> starts Jan 1.
        written_off_day = await _run_year_end(company_id, as_of=date(2026, 6, 15))
        assert written_off_day == 0
        assert await _get_balance(client, headers, employee["id"]) == "0"

        written = await _run_year_end(company_id, as_of=date(2026, 1, 1))
        assert written == 1
        assert await _get_balance(client, headers, employee["id"]) == "12.00"

        # Idempotent — re-running the same leave-year-start date doesn't double-credit.
        again = await _run_year_end(company_id, as_of=date(2026, 1, 1))
        assert again == 0
        assert await _get_balance(client, headers, employee["id"]) == "12.00"
    finally:
        await _teardown_year_setting(company_id=company_id)
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_carry_forward_cap_forfeits_excess_and_is_idempotent(
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
            joining_date="2020-01-01",
        )
        leave_type = await _create_leave_type(client, headers)
        await _setup_leave_policy(
            client,
            headers,
            leave_type_id=leave_type["id"],
            approval_chain="AUTO",
            max_carry_forward_days="5.00",
        )
        await _give_balance(
            client,
            headers,
            employee_id=employee["id"],
            leave_type_id=leave_type["id"],
            amount="20.00",
        )

        written = await _run_year_end(company_id, as_of=date(2026, 1, 1))
        assert written == 1
        assert await _get_balance(client, headers, employee["id"]) == "5.00"

        # Idempotent.
        again = await _run_year_end(company_id, as_of=date(2026, 1, 1))
        assert again == 0
        assert await _get_balance(client, headers, employee["id"]) == "5.00"
    finally:
        await _teardown_year_setting(company_id=company_id)
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_carry_forward_no_op_when_balance_under_cap(
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
            joining_date="2020-01-01",
        )
        leave_type = await _create_leave_type(client, headers)
        await _setup_leave_policy(
            client,
            headers,
            leave_type_id=leave_type["id"],
            approval_chain="AUTO",
            max_carry_forward_days="5.00",
        )
        await _give_balance(
            client,
            headers,
            employee_id=employee["id"],
            leave_type_id=leave_type["id"],
            amount="3.00",
        )

        written = await _run_year_end(company_id, as_of=date(2026, 1, 1))
        assert written == 0
        assert await _get_balance(client, headers, employee["id"]) == "3.00"
    finally:
        await _teardown_year_setting(company_id=company_id)
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
