"""Integration tests for the Employee Dependent API (market-parity onboarding-data pass, part 6)
— `/v1/employees/{employee_id}/dependents*`.

Mirrors `EmployeeExperienceService`/`EmployeeEducationService`'s plain-list shape (no covering-
employment check, `POST` always inserts a new row, `DELETE` the only other mutation path), plus
the two things neither of those needs: DATA-01 Aadhaar encryption (same round-trip contract as
`test_employee_banking.py`'s `account_number_enc` coverage) and the nominee-percentage-sums-to
-<=100 validator this module adds — the employee-service-layer half of that rule (the onboarding-
layer half is covered by `test_onboarding_public.py`'s nominee_info tests)."""

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from hrms.core.db.session import get_session_factory

from ..organisation.test_registration_flow import _cleanup, _register

pytestmark = pytest.mark.asyncio


async def _register_tenant(
    client: AsyncClient, **overrides: Any
) -> tuple[dict[str, str], UUID, UUID | None]:
    response, company_id, user_id = await _register(client, **overrides)
    assert response.status_code == 201
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
    client: AsyncClient, headers: dict[str, str], first_name: str = "Meera", **extra: Any
) -> dict[str, Any]:
    response = await client.post(
        "/v1/employees", headers=headers, json={"first_name": first_name, **extra}
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _create_dependent(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    employee_id: str,
    expected_status: int = 201,
    **body: Any,
) -> dict[str, Any]:
    payload = {"full_name": "Sunita Rao", "relationship": "SPOUSE", **body}
    response = await client.post(
        f"/v1/employees/{employee_id}/dependents", headers=headers, json=payload
    )
    assert response.status_code == expected_status, response.text
    return dict(response.json()["data"]) if expected_status < 400 else dict(response.json())


async def _cleanup_dependents(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("DELETE FROM employee_dependent WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.commit()


async def _cleanup_employees(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("DELETE FROM employee WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.execute(
            text("DELETE FROM number_series WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.commit()


async def _teardown(*, company_id: UUID, user_id: UUID | None) -> None:
    await _cleanup_dependents(company_id=company_id)
    await _cleanup_employees(company_id=company_id)
    await _cleanup(company_id=company_id, user_id=user_id)


async def test_create_dependent_encrypts_and_decrypts_aadhaar(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)

        dependent = await _create_dependent(
            client,
            headers,
            employee_id=employee["id"],
            aadhaar_number_enc="234567890123",
            is_pf_nominee=True,
            pf_nominee_share_percentage=100,
        )
        assert dependent["aadhaar_number_enc"] == "234567890123"
        assert dependent["is_pf_nominee"] is True
        assert dependent["pf_nominee_share_percentage"] == 100

        # Ciphertext at rest, not plaintext.
        factory = get_session_factory()
        async with factory() as session:
            row = (
                await session.execute(
                    text("SELECT aadhaar_number_enc FROM employee_dependent WHERE id = :id"),
                    {"id": dependent["id"]},
                )
            ).scalar_one()
            assert row != "234567890123"
            assert row.startswith("v1:")

        get_response = await client.get(
            f"/v1/employees/{employee['id']}/dependents/{dependent['id']}", headers=headers
        )
        assert get_response.status_code == 200, get_response.text
        assert get_response.json()["data"]["aadhaar_number_enc"] == "234567890123"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_dependent_minor_without_guardian_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        response = await client.post(
            f"/v1/employees/{employee['id']}/dependents",
            headers=headers,
            json={"full_name": "Arjun Rao", "relationship": "SON", "is_minor": True},
        )
        assert response.status_code == 422
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_dependent_pf_percentage_exceeding_100_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The employee-service-layer half of the nominee-percentage-sums-to-<=100 rule — a second
    dependent whose own percentage is valid in isolation (60%) but pushes the employee's PF
    nominee total past 100% (60% already on file) must be rejected."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        await _create_dependent(
            client,
            headers,
            employee_id=employee["id"],
            full_name="Sunita Rao",
            is_pf_nominee=True,
            pf_nominee_share_percentage=60,
        )
        rejected = await _create_dependent(
            client,
            headers,
            employee_id=employee["id"],
            full_name="Arjun Rao",
            relationship="SON",
            is_pf_nominee=True,
            pf_nominee_share_percentage=60,
            expected_status=422,
        )
        assert rejected["error"]["code"] == "NOMINEE_PERCENTAGE_EXCEEDED"

        # The 100%-exact boundary (60 + 40) is accepted, not rejected.
        accepted = await _create_dependent(
            client,
            headers,
            employee_id=employee["id"],
            full_name="Arjun Rao",
            relationship="SON",
            is_pf_nominee=True,
            pf_nominee_share_percentage=40,
        )
        assert accepted["pf_nominee_share_percentage"] == 40
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_list_and_delete_dependent(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        dependent = await _create_dependent(client, headers, employee_id=employee["id"])

        list_response = await client.get(
            f"/v1/employees/{employee['id']}/dependents", headers=headers
        )
        assert list_response.status_code == 200, list_response.text
        assert len(list_response.json()["data"]) == 1

        delete_response = await client.delete(
            f"/v1/employees/{employee['id']}/dependents/{dependent['id']}",
            headers={**headers, "If-Match": str(dependent["version"])},
        )
        assert delete_response.status_code == 204, delete_response.text

        list_after = await client.get(
            f"/v1/employees/{employee['id']}/dependents", headers=headers
        )
        assert list_after.json()["data"] == []
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_dependent_without_permission_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        bad_headers = {**headers, "Authorization": "Bearer not-a-real-token"}
        response = await client.post(
            f"/v1/employees/{employee['id']}/dependents",
            headers=bad_headers,
            json={"full_name": "Sunita Rao", "relationship": "SPOUSE"},
        )
        assert response.status_code == 401
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
