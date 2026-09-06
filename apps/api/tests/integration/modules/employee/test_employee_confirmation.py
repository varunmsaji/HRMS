"""Integration tests for the Employee confirmation feature (minimal slice) —
`POST /v1/employees/{employee_id}/confirm`, plus the `PRE_JOINING` -> `PROBATION`
auto-transition `EmploymentService.create_employment` now performs.

No reminders, no manager-recommendation routing, no auto-extend/auto-confirm rules, no letter
generation — the full FR-EMP-010 scope is deliberately not built here. This closes the real gap
`test_leave_probation_rules.py` used to document: `Employee.status` now has two real transitions
(`PRE_JOINING` -> `PROBATION` on joining, `PROBATION` -> `ACTIVE` on confirm), not zero.
"""

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from tests.integration.modules.employee.test_employment import (
    _cleanup_employees,
    _cleanup_employments,
    _create_employment,
    _create_legal_entity,
    _register_tenant,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.core.audit.models import AuditLog
from hrms.core.db.session import get_session_factory

pytestmark = pytest.mark.asyncio


async def _create_employee(
    client: AsyncClient, headers: dict[str, str], first_name: str = "Asha", **extra: Any
) -> dict[str, Any]:
    response = await client.post(
        "/v1/employees", headers=headers, json={"first_name": first_name, **extra}
    )
    assert response.status_code == 201
    return dict(response.json()["data"])


async def _get_employee(client: AsyncClient, headers: dict[str, str], employee_id: str) -> Any:
    response = await client.get(f"/v1/employees/{employee_id}", headers=headers)
    assert response.status_code == 200
    return response.json()["data"]


async def _teardown(*, company_id: UUID, user_id: UUID | None) -> None:
    await _cleanup_employments(company_id=company_id)
    await _cleanup_employees(company_id=company_id)
    await _cleanup(company_id=company_id, user_id=user_id)


async def test_create_employment_moves_employee_to_probation(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        assert employee["status"] == "PRE_JOINING"

        legal_entity = await _create_legal_entity(client, headers)
        await _create_employment(
            client, headers, employee_id=employee["id"], legal_entity_id=legal_entity["id"]
        )

        after = await _get_employee(client, headers, employee["id"])
        assert after["status"] == "PROBATION"

        factory = get_session_factory()
        async with factory() as session:
            audit_rows = (
                (
                    await session.execute(
                        select(AuditLog).where(
                            AuditLog.entity_id == UUID(employee["id"]),
                            AuditLog.action == "EMPLOYEE_PROBATION_STARTED",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(audit_rows) == 1
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_confirm_employee_success(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        legal_entity = await _create_legal_entity(client, headers)
        await _create_employment(
            client, headers, employee_id=employee["id"], legal_entity_id=legal_entity["id"]
        )
        before = await _get_employee(client, headers, employee["id"])
        assert before["status"] == "PROBATION"

        confirmed = await client.post(
            f"/v1/employees/{employee['id']}/confirm",
            headers={**headers, "If-Match": str(before["version"])},
            json={},
        )
        assert confirmed.status_code == 200, confirmed.text
        data = confirmed.json()["data"]
        assert data["status"] == "ACTIVE"
        assert data["version"] == before["version"] + 1

        factory = get_session_factory()
        async with factory() as session:
            audit_rows = (
                (
                    await session.execute(
                        select(AuditLog).where(
                            AuditLog.entity_id == UUID(employee["id"]),
                            AuditLog.action == "EMPLOYEE_CONFIRMED",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(audit_rows) == 1
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_confirm_employee_not_on_probation_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A `PRE_JOINING` employee (no employment yet) has never reached `PROBATION` — confirming
    them is rejected, same as confirming an already-`ACTIVE` employee a second time."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        assert employee["status"] == "PRE_JOINING"

        response = await client.post(
            f"/v1/employees/{employee['id']}/confirm",
            headers={**headers, "If-Match": str(employee["version"])},
            json={},
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "EMPLOYEE_NOT_ON_PROBATION"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_confirm_employee_twice_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        legal_entity = await _create_legal_entity(client, headers)
        await _create_employment(
            client, headers, employee_id=employee["id"], legal_entity_id=legal_entity["id"]
        )
        before = await _get_employee(client, headers, employee["id"])

        first = await client.post(
            f"/v1/employees/{employee['id']}/confirm",
            headers={**headers, "If-Match": str(before["version"])},
            json={},
        )
        assert first.status_code == 200, first.text

        second = await client.post(
            f"/v1/employees/{employee['id']}/confirm",
            headers={**headers, "If-Match": str(first.json()["data"]["version"])},
            json={},
        )
        assert second.status_code == 409, second.text
        assert second.json()["error"]["code"] == "EMPLOYEE_NOT_ON_PROBATION"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_confirm_employee_stale_version_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        legal_entity = await _create_legal_entity(client, headers)
        await _create_employment(
            client, headers, employee_id=employee["id"], legal_entity_id=legal_entity["id"]
        )

        response = await client.post(
            f"/v1/employees/{employee['id']}/confirm",
            headers={**headers, "If-Match": "999"},
            json={},
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "STALE_RESOURCE"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_rehire_for_confirmed_employee_does_not_reset_to_probation(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """An already-`ACTIVE` (confirmed) employee whose employment ended and who is rehired must
    stay `ACTIVE`, not get reset into `PROBATION` — the auto-transition only ever fires from
    `PRE_JOINING`."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        legal_entity = await _create_legal_entity(client, headers)
        first_employment = await _create_employment(
            client,
            headers,
            employee_id=employee["id"],
            legal_entity_id=legal_entity["id"],
            joining_date="2027-01-01",
        )
        confirmed = await _get_employee(client, headers, employee["id"])
        await client.post(
            f"/v1/employees/{employee['id']}/confirm",
            headers={**headers, "If-Match": str(confirmed["version"])},
            json={},
        )

        terminated = await client.post(
            f"/v1/employees/{employee['id']}/employments/{first_employment['id']}/terminate",
            headers={**headers, "If-Match": str(first_employment["version"])},
            json={"last_working_day": "2027-06-01"},
        )
        assert terminated.status_code == 200, terminated.text

        await _create_employment(
            client,
            headers,
            employee_id=employee["id"],
            legal_entity_id=legal_entity["id"],
            joining_date="2027-07-01",
        )

        after_rehire = await _get_employee(client, headers, employee["id"])
        assert after_rehire["status"] == "ACTIVE"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
