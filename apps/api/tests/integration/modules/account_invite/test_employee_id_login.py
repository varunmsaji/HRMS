"""Signing in with a company code + employee ID instead of an email (migration 20261114090000).

Employee codes repeat across companies (every company's series starts at `EMP-0001`), so the
company code is what picks the account. These tests cover: the happy path (also under the
`hrms_app` runtime role, where `employee` is hidden by RLS until the tenant is known), the same
employee code in another company, wrong codes/passwords, and request validation."""

from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from tests.security.test_rls_runtime_role import _as_runtime_role

from ..organisation.test_registration_flow import VALID_PASSWORD
from .test_account_invite import (
    _create_employee,
    _register_tenant,
    _teardown,
    _token_from_invite_url,
)

pytestmark = pytest.mark.asyncio


async def _employee_with_login(
    client: AsyncClient, headers: dict[str, str], email: str
) -> dict[str, Any]:
    employee = await _create_employee(client, headers, personal_email=email)
    invite = await client.post(f"/v1/employees/{employee['id']}/invite", headers=headers)
    assert invite.status_code == 201, invite.text
    token = _token_from_invite_url(invite.json()["data"]["invite_url"])
    accepted = await client.post(
        f"/v1/public/account-invites/{token}/accept",
        json={"password": VALID_PASSWORD, "first_name": "New", "last_name": "Hire"},
    )
    assert accepted.status_code == 201, accepted.text
    return employee


async def _login_code(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.get("/v1/companies/current", headers=headers)
    assert response.status_code == 200, response.text
    code = response.json()["data"]["login_code"]
    assert isinstance(code, str) and code == code.upper() and 2 <= len(code) <= 12
    return code


async def test_employee_signs_in_with_company_code_and_employee_id(
    client: AsyncClient, seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    email = f"empid-{uuid4().hex[:8]}@example.com"
    try:
        employee = await _employee_with_login(client, headers, email)
        company_code = await _login_code(client, headers)

        async with _as_runtime_role(monkeypatch):
            ok = await client.post(
                "/v1/auth/login",
                json={
                    # Case and stray spaces don't matter.
                    "company_code": f" {company_code.lower()} ",
                    "employee_code": f" {employee['employee_code'].lower()} ",
                    "password": VALID_PASSWORD,
                },
            )
            assert ok.status_code == 200, ok.text
            assert ok.json()["data"]["company_id"] == str(company_id)

            wrong_password = await client.post(
                "/v1/auth/login",
                json={
                    "company_code": company_code,
                    "employee_code": employee["employee_code"],
                    "password": "WrongPassword9",
                },
            )
            assert wrong_password.status_code == 401
            assert wrong_password.json()["error"]["code"] == "INVALID_CREDENTIALS"

        # The email login keeps working alongside it.
        by_email = await client.post(
            "/v1/auth/login", json={"email": email, "password": VALID_PASSWORD}
        )
        assert by_email.status_code == 200, by_email.text
    finally:
        await _teardown(company_id=company_id, user_id=user_id, extra_emails=[email])


async def test_same_employee_id_in_another_company_does_not_sign_in(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    email = f"empid-{uuid4().hex[:8]}@example.com"
    try:
        employee = await _employee_with_login(client, headers_a, email)
        # Company B has an employee with the same code, but no login.
        twin = await _create_employee(client, headers_b, first_name="Twin")
        assert twin["employee_code"] == employee["employee_code"]
        code_a = await _login_code(client, headers_a)
        code_b = await _login_code(client, headers_b)
        assert code_a != code_b

        attempts: list[dict[str, str]] = [
            # right employee ID, the other company's code
            {"company_code": code_b, "employee_code": employee["employee_code"]},
            # unknown company code
            {"company_code": "NOSUCHCO99", "employee_code": employee["employee_code"]},
            # unknown employee ID
            {"company_code": code_a, "employee_code": "EMP-9999"},
        ]
        for attempt in attempts:
            response = await client.post(
                "/v1/auth/login", json={**attempt, "password": VALID_PASSWORD}
            )
            assert response.status_code == 401, (attempt, response.text)
            assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"
    finally:
        await _teardown(company_id=company_a, user_id=user_a, extra_emails=[email])
        await _teardown(company_id=company_b, user_id=user_b)


@pytest.mark.parametrize(
    "body",
    [
        {"employee_code": "EMP-0001"},
        {"company_code": "ACME"},
        {"email": "a@example.com", "company_code": "ACME", "employee_code": "EMP-0001"},
        {},
    ],
)
async def test_login_needs_an_email_or_a_company_code_and_employee_id(
    client: AsyncClient, body: dict[str, str]
) -> None:
    response = await client.post("/v1/auth/login", json={**body, "password": VALID_PASSWORD})
    assert response.status_code == 422, response.text


async def test_new_companies_get_distinct_login_codes(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    name = f"Same Name {uuid4().hex[:6]}"
    tenants: list[tuple[dict[str, str], UUID, UUID | None]] = []
    try:
        for _ in range(2):
            tenants.append(await _register_tenant(client, name=name))
        codes = [await _login_code(client, headers) for headers, _, _ in tenants]
        assert codes[0].startswith("SAMENA")
        assert codes[0] != codes[1]
    finally:
        for _, company_id, user_id in tenants:
            await _teardown(company_id=company_id, user_id=user_id)
