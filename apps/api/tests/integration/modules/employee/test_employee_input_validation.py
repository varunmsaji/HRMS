"""Input-validation hardening for the employee module: every payroll- or compliance-relevant
field rejects obviously-invalid data with a clean 422 (and accepts the legitimate edge cases that
a too-strict rule would wrongly refuse), and absurd numbers can never reach the database."""

from typing import Any

import pytest
from httpx import AsyncClient

from ...tenant_wipe import wipe_tenant
from .conftest import seeded_plan_catalogue  # noqa: F401
from .test_employee_assignment import (
    _create_employee,
    _create_employment,
    _create_legal_entity,
    _register_tenant,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("seeded_plan_catalogue")]


async def _lift_seat_limit(company_id) -> None:
    from sqlalchemy import text

    from hrms.core.db.session import get_session_factory

    async with get_session_factory()() as session:
        await session.execute(
            text(
                "UPDATE subscription SET seat_limit_override = 1000 "
                "WHERE company_id = CAST(:c AS uuid)"
            ),
            {"c": str(company_id)},
        )
        await session.commit()


async def _employee_with_employment(client, headers):
    employee = await _create_employee(client, headers)
    entity = await _create_legal_entity(client, headers)
    await _create_employment(
        client,
        headers,
        employee_id=employee["id"],
        legal_entity_id=entity["id"],
        joining_date="2027-06-01",
    )
    return employee, entity


def _error_fields(response) -> set[str]:
    return {d["field"] for d in response.json()["error"]["details"]}


# ---------------------------------------------------------------- employee basics

_BAD_EMPLOYEE_FIELDS = [
    ("first_name", ""),
    ("first_name", "   "),
    ("first_name", "x" * 101),
    ("personal_email", "not-an-email"),
    ("personal_email", "a@"),
    ("personal_email", "two@@example.com"),
    ("date_of_birth", "2999-01-01"),
    ("date_of_birth", "1800-01-01"),
    ("date_of_birth", "not-a-date"),
    ("personal_mobile", "abc"),
    ("personal_mobile", "12"),
    ("personal_mobile", "9" * 25),
    ("emergency_contact_phone", "call me"),
    ("present_pincode", "zz"),
    ("present_pincode", "!!!!!!"),
    ("permanent_pincode", "1"),
    ("present_country_code", "1!"),
    ("present_country_code", "IND"),
    ("permanent_country_code", "I"),
    ("custom_fields", {"blob": "x" * 200_000}),
]


@pytest.mark.parametrize(("field", "value"), _BAD_EMPLOYEE_FIELDS)
async def test_create_and_update_reject_invalid_field_values(
    client: AsyncClient, field: str, value: Any
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        r = await client.post(
            "/v1/employees", headers=headers, json={"first_name": "Valid", field: value}
        )
        if field == "first_name":
            r = await client.post("/v1/employees", headers=headers, json={field: value})
        assert r.status_code == 422, (field, value, r.text[:200])

        employee = await _create_employee(client, headers)
        r = await client.patch(
            f"/v1/employees/{employee['id']}",
            headers={**headers, "If-Match": str(employee["version"])},
            json={field: value},
        )
        assert r.status_code == 422, (field, value, r.text[:200])
        assert any(f.endswith(field) for f in _error_fields(r)), _error_fields(r)
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


async def test_legitimate_edge_values_are_still_accepted(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    await _lift_seat_limit(company_id)
    try:
        good = [
            {"first_name": "  Asha  "},  # stripped, not rejected
            {"first_name": "Zoë-Marie"},
            {"first_name": "A", "date_of_birth": "1900-01-01"},
            {"first_name": "A", "date_of_birth": "2000-02-29"},
            {"first_name": "A", "personal_email": "first.last+tag@sub.example.com"},
            {"first_name": "A", "personal_mobile": "9876543210"},
            {"first_name": "A", "personal_mobile": "+91 98765 43210"},
            {"first_name": "A", "personal_mobile": "+1 (415) 555-0100"},
            {"first_name": "A", "present_pincode": "560001"},
            {"first_name": "A", "present_pincode": "SW1A 1AA"},
            {"first_name": "A", "present_country_code": "IN", "permanent_country_code": "gb"},
            {"first_name": "A", "custom_fields": {"k": "v" * 1000}},
            {"first_name": "A", "custom_fields": None},
        ]
        for body in good:
            r = await client.post("/v1/employees", headers=headers, json=body)
            assert r.status_code == 201, (body, r.text[:200])
        r = await client.post("/v1/employees", headers=headers, json={"first_name": "  Asha  "})
        assert r.json()["data"]["first_name"] == "Asha"
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


# ---------------------------------------------------------------- identity (compliance IDs)


@pytest.mark.parametrize(
    ("body", "bad"),
    [
        ({"pan_number": "1234567890"}, True),
        ({"pan_number": "ABCDE12345"}, True),
        ({"pan_number": "ABCD1234EF"}, True),
        ({"pan_number": "ABC DE1234"}, True),
        ({"aadhaar_number": "abcdefghijkl"}, True),
        ({"aadhaar_number": "12345678901"}, True),
        ({"aadhaar_number": "1234 5678 901"}, True),
        ({"uan_number": "12345"}, True),
        ({"uan_number": "ABCDEFGHIJKL"}, True),
        ({"pan_number": "ABCDE1234F"}, False),
        ({"pan_number": "abcde1234f"}, False),  # normalised to upper-case
        ({"aadhaar_number": "123456789012"}, False),
        ({"uan_number": "100123456789"}, False),
    ],
)
async def test_identity_documents_must_have_valid_formats(
    client: AsyncClient, body: dict[str, str], bad: bool
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        r = await client.patch(
            f"/v1/employees/{employee['id']}/identity",
            headers={**headers, "If-Match": str(employee["version"])},
            json=body,
        )
        if bad:
            assert r.status_code == 422, (body, r.text[:200])
        else:
            assert r.status_code == 200, (body, r.text[:200])
            got = await client.get(f"/v1/employees/{employee['id']}/identity", headers=headers)
            key = next(iter(body))
            assert got.json()["data"][key] == body[key].upper() if key == "pan_number" else True
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


# ---------------------------------------------------------------- employment dates


@pytest.mark.parametrize(
    "dates",
    [
        {"joining_date": "1900-01-01"},
        {"joining_date": "9999-12-31"},
        {"joining_date": "2027-06-01", "probation_end_date": "2027-05-31"},
        {"joining_date": "2027-06-01", "probation_end_date": "1999-01-01"},
    ],
)
async def test_employment_dates_must_be_sane(client: AsyncClient, dates: dict[str, str]) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        entity = await _create_legal_entity(client, headers)
        r = await client.post(
            f"/v1/employees/{employee['id']}/employments",
            headers=headers,
            json={"legal_entity_id": entity["id"], **dates},
        )
        assert r.status_code == 422, (dates, r.text[:200])
        ok = await client.post(
            f"/v1/employees/{employee['id']}/employments",
            headers=headers,
            json={
                "legal_entity_id": entity["id"],
                "joining_date": "2027-06-01",
                "probation_end_date": "2027-06-01",  # same day is allowed
            },
        )
        assert ok.status_code == 201, ok.text
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


# ---------------------------------------------------------------- money & statutory


def _comp(**patch: Any) -> dict[str, Any]:
    return {
        "effective_from": "2027-06-01",
        "annual_ctc_minor": 12_00_000_00,
        "currency": "INR",
        "revision_type": "JOINING",
        "revision_reason": "Initial hire",
        **patch,
    }


@pytest.mark.parametrize(
    "patch",
    [
        {"annual_ctc_minor": -1},
        {"annual_ctc_minor": 10**30},
        {"annual_ctc_minor": 2**63},
        {"annual_ctc_minor": 10**13 + 1},
        {"annual_ctc_minor": 1.5},
        {"annual_ctc_minor": "lots"},
        {"currency": "inr"},
        {"currency": "123"},
        {"currency": "RUPEE"},
        {"currency": ""},
        {"revision_reason": ""},
        {"revision_reason": "x" * 1001},
        {"revision_type": "BONUS"},
    ],
)
async def test_compensation_rejects_invalid_values_and_never_crashes(
    client: AsyncClient, patch: dict[str, Any]
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _ = await _employee_with_employment(client, headers)
        r = await client.post(
            f"/v1/employees/{employee['id']}/compensation", headers=headers, json=_comp(**patch)
        )
        assert r.status_code == 422, (patch, r.status_code, r.text[:200])
        got = await client.get(f"/v1/employees/{employee['id']}/compensation", headers=headers)
        assert got.json()["data"] == []
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


async def test_compensation_boundary_amounts_are_accepted(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _ = await _employee_with_employment(client, headers)
        r = await client.post(
            f"/v1/employees/{employee['id']}/compensation",
            headers=headers,
            json=_comp(annual_ctc_minor=10**13),
        )
        assert r.status_code == 201, r.text
        assert r.json()["data"]["annual_ctc_minor"] == 10**13
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


def _stat(**patch: Any) -> dict[str, Any]:
    return {
        "effective_from": "2027-06-01",
        "is_pf_applicable": True,
        "is_esi_applicable": False,
        "is_lwf_applicable": False,
        "tax_regime": "NEW",
        "revision_reason": "Initial",
        **patch,
    }


@pytest.mark.parametrize(
    "patch",
    [
        {"vpf_percentage": 100.01},
        {"vpf_percentage": 5000},
        {"vpf_percentage": -1},
        {"vpf_amount": 10**30},
        {"vpf_amount": -1},
        {"tax_regime": "FLAT"},
        {"revision_reason": ""},
    ],
)
async def test_statutory_rejects_invalid_values(client: AsyncClient, patch: dict[str, Any]) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _ = await _employee_with_employment(client, headers)
        r = await client.post(
            f"/v1/employees/{employee['id']}/statutory", headers=headers, json=_stat(**patch)
        )
        assert r.status_code == 422, (patch, r.status_code, r.text[:200])
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


async def test_statutory_boundary_values_are_accepted(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _ = await _employee_with_employment(client, headers)
        r = await client.post(
            f"/v1/employees/{employee['id']}/statutory",
            headers=headers,
            json=_stat(vpf_percentage=100, vpf_amount=0),
        )
        assert r.status_code == 201, r.text
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


# ---------------------------------------------------------------- bank


@pytest.mark.parametrize(
    "patch",
    [
        {"ifsc": "!!!"},
        {"ifsc": "HDFC1001234"},  # 5th char must be 0
        {"ifsc": "HDF00001234"},
        {"ifsc": "HDFC000123"},
        {"ifsc": "HDFC00012345"},
        {"account_number_enc": "not digits"},
        {"account_number_enc": "123"},
        {"account_number_enc": "1" * 40},
        {"account_number_enc": "12345-6789"},
        {"payment_mode": "BITCOIN"},
    ],
)
async def test_bank_details_are_format_checked(client: AsyncClient, patch: dict[str, Any]) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _ = await _employee_with_employment(client, headers)
        body = {"effective_from": "2027-06-01", "payment_mode": "BANK", **patch}
        r = await client.post(f"/v1/employees/{employee['id']}/bank", headers=headers, json=body)
        assert r.status_code == 422, (patch, r.status_code, r.text[:200])
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


async def test_valid_bank_details_accepted_and_ifsc_normalised(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _ = await _employee_with_employment(client, headers)
        r = await client.post(
            f"/v1/employees/{employee['id']}/bank",
            headers=headers,
            json={
                "effective_from": "2027-06-01",
                "payment_mode": "BANK",
                "account_holder_name": "Asha Rao",
                "account_number_enc": "123456789012",
                "ifsc": "hdfc0001234",
                "bank_name": "HDFC",
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["data"]["ifsc"] == "HDFC0001234"
        assert r.json()["data"]["account_number_enc"] == "123456789012"
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


# ---------------------------------------------------------------- organisation grade bounds


@pytest.mark.parametrize(
    "patch",
    [
        {"min_ctc": 10**30},
        {"max_ctc": 2**63},
        {"approval_limit": 10**20},
        {"level": 2**40},
        {"notice_period_days": 99999},
        {"probation_days": -1},
        {"min_ctc": 500, "max_ctc": 100},
    ],
)
async def test_grade_numeric_fields_are_bounded(client: AsyncClient, patch: dict[str, Any]) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        r = await client.post(
            "/v1/grades", headers=headers, json={"code": "G1", "name": "Grade", **patch}
        )
        assert r.status_code == 422, (patch, r.status_code, r.text[:200])
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)
