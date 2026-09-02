"""Integration tests for the Onboarding module's O7 slice —
`POST /onboarding-cases/{id}/activate`, the transaction that turns a fully-verified case into a
real `Employee`/`Employment`/`Assignment`(/`Bank`/`Statutory`) row graph.

Covers: the happy path (verified via the real employee-module read endpoints, not just the
onboarding response), rejection when not yet `VERIFIED`, rejection when `legal_entity_id` was
never set, the `AssignmentFieldsRequiredError` bubbling through unmodified when branch/
department/designation were never set on the case, permission gating, double-activation
rejection, and cross-tenant isolation."""

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from hrms.core.db.session import get_session_factory

from .test_onboarding_case import (
    _case_payload,
    _cleanup_scoped_users,
    _create_permission_scoped_user,
    _register_tenant,
    _teardown,
)
from .test_onboarding_public import _cleanup_tokens, _issue_token
from .test_onboarding_review import _cleanup_section_reviews
from .test_onboarding_submit import _fill_all_sections

pytestmark = pytest.mark.asyncio


async def _create_case(
    client: AsyncClient, headers: dict[str, str], **overrides: Any
) -> dict[str, Any]:
    response = await client.post(
        "/v1/onboarding-cases", headers=headers, json=_case_payload(**overrides)
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _create_legal_entity(
    client: AsyncClient, headers: dict[str, str], name: str = "Acme Legal Entity"
) -> dict[str, Any]:
    response = await client.post("/v1/legal-entities", headers=headers, json={"name": name})
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _create_branch(
    client: AsyncClient, headers: dict[str, str], legal_entity_id: str, name: str = "HQ Branch"
) -> dict[str, Any]:
    response = await client.post(
        "/v1/branches", headers=headers, json={"legal_entity_id": legal_entity_id, "name": name}
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _create_department(
    client: AsyncClient, headers: dict[str, str], name: str = "Engineering", **extra: Any
) -> dict[str, Any]:
    response = await client.post("/v1/departments", headers=headers, json={"name": name, **extra})
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _create_designation(
    client: AsyncClient, headers: dict[str, str], title: str = "Software Engineer", **extra: Any
) -> dict[str, Any]:
    response = await client.post(
        "/v1/designations", headers=headers, json={"title": title, **extra}
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


def _review_url(case_id: str, section: str) -> str:
    return f"/v1/onboarding-cases/{case_id}/sections/{section}/review"


_ALL_SECTIONS = [
    "personal_info",
    "address_info",
    "emergency_contact",
    "bank_info",
    "statutory_info",
]


async def _verified_case(
    client: AsyncClient, headers: dict[str, str], company_id: UUID, *, with_org: bool
) -> dict[str, Any]:
    """Creates a case (optionally with full org context — legal entity/branch/department/
    designation), fills and submits every section, then has HR verify all five, which
    auto-transitions the case to `VERIFIED` (O6) since there are no documents to also require."""
    overrides: dict[str, Any] = {}
    if with_org:
        legal_entity = await _create_legal_entity(client, headers)
        branch = await _create_branch(client, headers, legal_entity_id=legal_entity["id"])
        department = await _create_department(client, headers, branch_id=branch["id"])
        designation = await _create_designation(client, headers, department_id=department["id"])
        overrides = {
            "legal_entity_id": legal_entity["id"],
            "branch_id": branch["id"],
            "department_id": department["id"],
            "designation_id": designation["id"],
        }

    case = await _create_case(client, headers, **overrides)
    token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))
    await _fill_all_sections(client, token)
    submit = await client.post(f"/v1/public/onboarding/{token}/submit")
    assert submit.status_code == 200, submit.text

    for section in _ALL_SECTIONS:
        response = await client.post(
            _review_url(case["id"], section), headers=headers, json={"status": "VERIFIED"}
        )
        assert response.status_code == 200, response.text

    return case


async def _cleanup_employee_graph(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        # FK-safe order: onboarding_case (references employee) -> bank/statutory/assignment ->
        # employment (references employee, legal_entity) -> employee (references number_series)
        # -> designation/department/branch (references legal_entity/company).
        await session.execute(
            text("DELETE FROM onboarding_case WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.execute(
            text("DELETE FROM employee_bank WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.execute(
            text("DELETE FROM employee_statutory WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.execute(
            text("DELETE FROM employee_assignment WHERE company_id = :cid"),
            {"cid": str(company_id)},
        )
        await session.execute(
            text("DELETE FROM employment WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.execute(
            text("DELETE FROM employee WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.execute(
            text("DELETE FROM number_series WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.execute(
            text("DELETE FROM designation WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.execute(
            text("DELETE FROM department WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.execute(
            text("DELETE FROM branch WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.commit()


async def _full_teardown(*, company_id: UUID, user_id: UUID | None) -> None:
    await _cleanup_section_reviews(company_id=company_id)
    await _cleanup_tokens(company_id=company_id)
    await _cleanup_employee_graph(company_id=company_id)
    await _teardown(company_id=company_id, user_id=user_id)


async def test_activate_success_creates_full_employee_graph(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _verified_case(client, headers, company_id, with_org=True)

        response = await client.post(f"/v1/onboarding-cases/{case['id']}/activate", headers=headers)
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["status"] == "ACTIVATED"
        employee_id = data["employee_id"]
        assert employee_id

        employee = (
            await client.get(f"/v1/employees/{employee_id}", headers=headers)
        ).json()["data"]
        assert employee["first_name"] == "Asha"
        assert employee["personal_email"] == case["personal_email"]

        employments = (
            await client.get(f"/v1/employees/{employee_id}/employments", headers=headers)
        ).json()["data"]
        assert len(employments) == 1
        assert employments[0]["legal_entity_id"] == case["legal_entity_id"]
        assert employments[0]["joining_date"] == case["proposed_joining_date"]

        assignments = (
            await client.get(f"/v1/employees/{employee_id}/assignments", headers=headers)
        ).json()["data"]
        assert len(assignments) == 1
        assert assignments[0]["change_type"] == "INITIAL"
        assert assignments[0]["branch_id"] == case["branch_id"]
        assert assignments[0]["department_id"] == case["department_id"]
        assert assignments[0]["designation_id"] == case["designation_id"]

        banks = (await client.get(f"/v1/employees/{employee_id}/bank", headers=headers)).json()[
            "data"
        ]
        assert len(banks) == 1
        assert banks[0]["payment_mode"] == "BANK"

        statutories = (
            await client.get(f"/v1/employees/{employee_id}/statutory", headers=headers)
        ).json()["data"]
        assert len(statutories) == 1
        assert statutories[0]["tax_regime"] == "NEW"
    finally:
        await _full_teardown(company_id=company_id, user_id=user_id)


async def test_activate_not_verified_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)

        response = await client.post(f"/v1/onboarding-cases/{case['id']}/activate", headers=headers)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "ONBOARDING_CASE_NOT_READY_FOR_ACTIVATION"
    finally:
        await _full_teardown(company_id=company_id, user_id=user_id)


async def test_activate_without_legal_entity_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _verified_case(client, headers, company_id, with_org=False)

        response = await client.post(f"/v1/onboarding-cases/{case['id']}/activate", headers=headers)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "ONBOARDING_CASE_MISSING_LEGAL_ENTITY"
    finally:
        await _full_teardown(company_id=company_id, user_id=user_id)


async def test_activate_without_placement_fields_bubbles_assignment_error(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        legal_entity = await _create_legal_entity(client, headers)
        case = await _create_case(client, headers, legal_entity_id=legal_entity["id"])
        token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))
        await _fill_all_sections(client, token)
        await client.post(f"/v1/public/onboarding/{token}/submit")
        for section in _ALL_SECTIONS:
            await client.post(
                _review_url(case["id"], section), headers=headers, json={"status": "VERIFIED"}
            )

        response = await client.post(f"/v1/onboarding-cases/{case['id']}/activate", headers=headers)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "ASSIGNMENT_FIELDS_REQUIRED"
    finally:
        await _full_teardown(company_id=company_id, user_id=user_id)


async def test_activate_without_permission_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    from hrms.modules.onboarding.permissions import ONBOARDING_REVIEW

    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _verified_case(client, headers, company_id, with_org=True)
        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=[ONBOARDING_REVIEW]
        )

        response = await client.post(
            f"/v1/onboarding-cases/{case['id']}/activate", headers=scoped_headers
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"
    finally:
        await _full_teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_activate_twice_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _verified_case(client, headers, company_id, with_org=True)

        first = await client.post(f"/v1/onboarding-cases/{case['id']}/activate", headers=headers)
        assert first.status_code == 200

        second = await client.post(f"/v1/onboarding-cases/{case['id']}/activate", headers=headers)
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "ONBOARDING_CASE_NOT_READY_FOR_ACTIVATION"
    finally:
        await _full_teardown(company_id=company_id, user_id=user_id)


async def test_activate_cross_tenant_isolation(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_id_a, user_id_a = await _register_tenant(client)
    headers_b, company_id_b, user_id_b = await _register_tenant(client)
    try:
        case_a = await _verified_case(client, headers_a, company_id_a, with_org=True)

        response = await client.post(
            f"/v1/onboarding-cases/{case_a['id']}/activate", headers=headers_b
        )
        assert response.status_code == 404
    finally:
        await _full_teardown(company_id=company_id_a, user_id=user_id_a)
        await _full_teardown(company_id=company_id_b, user_id=user_id_b)
