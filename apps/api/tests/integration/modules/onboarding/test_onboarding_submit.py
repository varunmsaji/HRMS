"""Integration tests for the Onboarding module's O4 backend slice —
`POST /v1/public/onboarding/{token}/submit`, the candidate wizard's completion step.

Covers: rejection while any of the five sections is still empty, success once all five are
filled (transitions `IN_PROGRESS -> SUBMITTED`), the case becoming non-writable afterward (a
`PATCH` against any section now 409s, mirroring O2's own writable-status contract), and
rejection when the case isn't in a submittable status to begin with."""

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient

from .test_onboarding_case import _case_payload, _register_tenant, _teardown
from .test_onboarding_public import _cleanup_tokens, _issue_token

pytestmark = pytest.mark.asyncio


async def _create_case(
    client: AsyncClient, headers: dict[str, str], **overrides: Any
) -> dict[str, Any]:
    response = await client.post(
        "/v1/onboarding-cases", headers=headers, json=_case_payload(**overrides)
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _teardown_with_tokens(*, company_id: UUID, user_id: UUID | None) -> None:
    await _cleanup_tokens(company_id=company_id)
    await _teardown(company_id=company_id, user_id=user_id)


async def _fill_all_sections(client: AsyncClient, token: str) -> None:
    await client.patch(
        f"/v1/public/onboarding/{token}/sections/personal_info", json={"first_name": "Asha"}
    )
    await client.patch(
        f"/v1/public/onboarding/{token}/sections/address_info", json={"city": "Bengaluru"}
    )
    await client.patch(
        f"/v1/public/onboarding/{token}/sections/emergency_contact",
        json={"contact_name": "Raj", "phone": "9876543210"},
    )
    await client.patch(
        f"/v1/public/onboarding/{token}/sections/bank_info", json={"payment_mode": "BANK"}
    )
    await client.patch(
        f"/v1/public/onboarding/{token}/sections/statutory_info",
        json={
            "is_pf_applicable": False,
            "is_esi_applicable": False,
            "is_lwf_applicable": False,
            "tax_regime": "NEW",
        },
    )
    await client.patch(
        f"/v1/public/onboarding/{token}/sections/compensation_info",
        json={"annual_ctc_minor": 60000000, "currency": "INR"},
    )
    await client.patch(
        f"/v1/public/onboarding/{token}/sections/previous_employment_info",
        json={"items": []},
    )
    await client.patch(
        f"/v1/public/onboarding/{token}/sections/education_info",
        json={"items": []},
    )
    await client.patch(
        f"/v1/public/onboarding/{token}/sections/nominee_info",
        json={"items": []},
    )


async def test_submit_rejected_when_sections_incomplete(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))

        response = await client.post(f"/v1/public/onboarding/{token}/submit")
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "ONBOARDING_INCOMPLETE_SECTIONS"
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_submit_success_transitions_to_submitted(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))
        await _fill_all_sections(client, token)

        response = await client.post(f"/v1/public/onboarding/{token}/submit")
        assert response.status_code == 200, response.text
        assert response.json()["data"]["status"] == "SUBMITTED"
        assert response.json()["data"]["writable"] is False

        admin_view = (
            await client.get(f"/v1/onboarding-cases/{case['id']}", headers=headers)
        ).json()["data"]
        assert admin_view["status"] == "SUBMITTED"
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_patch_section_rejected_after_submit(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))
        await _fill_all_sections(client, token)
        await client.post(f"/v1/public/onboarding/{token}/submit")

        response = await client.patch(
            f"/v1/public/onboarding/{token}/sections/personal_info",
            json={"first_name": "Changed"},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "ONBOARDING_SECTION_NOT_WRITABLE"
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_submit_twice_rejected(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))
        await _fill_all_sections(client, token)
        first = await client.post(f"/v1/public/onboarding/{token}/submit")
        assert first.status_code == 200

        second = await client.post(f"/v1/public/onboarding/{token}/submit")
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "ONBOARDING_CASE_NOT_SUBMITTABLE"
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)
