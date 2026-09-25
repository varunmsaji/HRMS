"""Integration tests for the Onboarding module's O2 slice — public, token-authenticated
`/v1/public/onboarding/{token}` routes (GET case, PATCH section).

No admin-triggerable send-invite endpoint exists yet (that lands in O3, once a minimal
EmailSender exists) — tokens are minted directly via `OnboardingTokenService.issue_token`,
exactly as the future send-invite route will do internally (module docstring,
`hrms.modules.onboarding.service`).

Covers: token issuance's own state transition (`DRAFT` -> `INVITED`), the first-open transition
(`INVITED` -> `IN_PROGRESS`), a GET/PATCH round-trip for personal/bank/statutory sections,
extra-field and unknown-section rejection, PATCH rejected once the case is no longer writable,
unknown/expired/revoked token handling (all indistinguishable `404`s, never a distinct code per
token failure mode), and cross-tenant isolation — the highest-risk property of this whole slice
(plan §10)."""

from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from hrms.core.db.session import get_session_factory
from hrms.modules.onboarding.service import OnboardingTokenService

from .test_onboarding_case import _case_payload, _register_tenant, _teardown

pytestmark = pytest.mark.asyncio


async def _issue_token(*, company_id: UUID, case_id: UUID, ttl_days: int = 7) -> str:
    factory = get_session_factory()
    async with factory() as session:
        service = OnboardingTokenService(session)
        token = await service.issue_token(company_id, case_id, ttl_days=ttl_days)
        await session.commit()
        return token


async def _create_case(
    client: AsyncClient, headers: dict[str, str], **overrides: Any
) -> dict[str, Any]:
    response = await client.post(
        "/v1/onboarding-cases", headers=headers, json=_case_payload(**overrides)
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _force_status(*, company_id: UUID, case_id: UUID, status: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("UPDATE onboarding_case SET status = :status WHERE id = :cid"),
            {"status": status, "cid": str(case_id)},
        )
        await session.commit()


async def _cleanup_tokens(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("DELETE FROM onboarding_token WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.commit()


async def _teardown_with_tokens(*, company_id: UUID, user_id: UUID | None) -> None:
    await _cleanup_tokens(company_id=company_id)
    await _teardown(company_id=company_id, user_id=user_id)


async def test_issue_token_transitions_draft_to_invited(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        assert case["status"] == "DRAFT"

        token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))
        assert token

        detail = await client.get(f"/v1/onboarding-cases/{case['id']}", headers=headers)
        assert detail.json()["data"]["status"] == "INVITED"
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_public_get_case_transitions_invited_to_in_progress(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))

        response = await client.get(f"/v1/public/onboarding/{token}")
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["status"] == "IN_PROGRESS"
        assert data["writable"] is True
        assert data["personal_info"] == {}
        assert data["candidate_first_name"] == case["candidate_first_name"]
        assert "id" not in data
        assert "company_id" not in data

        admin_view = (
            await client.get(f"/v1/onboarding-cases/{case['id']}", headers=headers)
        ).json()["data"]
        assert admin_view["status"] == "IN_PROGRESS"
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_patch_personal_info_section_success(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))

        response = await client.patch(
            f"/v1/public/onboarding/{token}/sections/personal_info",
            json={"first_name": "Asha", "last_name": "Rao", "gender": "Female"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["personal_info"] == {
            "first_name": "Asha",
            "middle_name": None,
            "last_name": "Rao",
            "date_of_birth": None,
            "gender": "Female",
            "blood_group": None,
            "marital_status": None,
            "nationality": None,
            "father_or_husband_name": None,
            "pan_number_enc": None,
            "aadhaar_number_enc": None,
            "photo_url": None,
        }
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_patch_bank_and_statutory_sections_success(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))

        bank_response = await client.patch(
            f"/v1/public/onboarding/{token}/sections/bank_info",
            json={"bank_name": "State Bank", "ifsc": "SBIN0001234", "payment_mode": "BANK"},
        )
        assert bank_response.status_code == 200, bank_response.text
        assert bank_response.json()["data"]["bank_info"]["bank_name"] == "State Bank"

        statutory_response = await client.patch(
            f"/v1/public/onboarding/{token}/sections/statutory_info",
            json={
                "is_pf_applicable": True,
                "is_esi_applicable": False,
                "is_lwf_applicable": False,
                "tax_regime": "NEW",
            },
        )
        assert statutory_response.status_code == 200, statutory_response.text
        assert statutory_response.json()["data"]["statutory_info"]["tax_regime"] == "NEW"
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_patch_section_rejects_extra_field(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))

        response = await client.patch(
            f"/v1/public/onboarding/{token}/sections/personal_info",
            json={"first_name": "Asha", "employee_code": "SNEAKY-001"},
        )
        assert response.status_code == 422
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_patch_unknown_section_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))

        response = await client.patch(f"/v1/public/onboarding/{token}/sections/documents", json={})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_SECTION"
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_patch_nominee_info_percentage_exceeding_100_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The onboarding-layer half of the nominee-percentage-sums-to-<=100 rule
    (`NomineeInfoSection`'s own validator) — checked across the *submitted* list, independent of
    `EmployeeDependentService`'s own employee-service-layer check (`test_employee_dependent.py`)."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))

        response = await client.patch(
            f"/v1/public/onboarding/{token}/sections/nominee_info",
            json={
                "items": [
                    {
                        "full_name": "Sunita Rao",
                        "relationship": "SPOUSE",
                        "is_pf_nominee": True,
                        "pf_nominee_share_percentage": 60,
                    },
                    {
                        "full_name": "Arjun Rao",
                        "relationship": "SON",
                        "is_pf_nominee": True,
                        "pf_nominee_share_percentage": 60,
                    },
                ]
            },
        )
        assert response.status_code == 422
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_patch_nominee_info_minor_without_guardian_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))

        response = await client.patch(
            f"/v1/public/onboarding/{token}/sections/nominee_info",
            json={"items": [{"full_name": "Arjun Rao", "relationship": "SON", "is_minor": True}]},
        )
        assert response.status_code == 422
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_patch_nominee_info_decrypts_aadhaar_per_item(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Each item's `aadhaar_number_enc` is encrypted under its own index-bound AAD
    (`NOMINEE_INFO_SENSITIVE_ITEM_KEY` docstring) — this proves both items round-trip correctly,
    not just the first."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))

        response = await client.patch(
            f"/v1/public/onboarding/{token}/sections/nominee_info",
            json={
                "items": [
                    {
                        "full_name": "Sunita Rao",
                        "relationship": "SPOUSE",
                        "aadhaar_number_enc": "234567890123",
                    },
                    {
                        "full_name": "Arjun Rao",
                        "relationship": "SON",
                        "aadhaar_number_enc": "345678901234",
                    },
                ]
            },
        )
        assert response.status_code == 200, response.text
        items = response.json()["data"]["nominee_info"]["items"]
        assert items[0]["aadhaar_number_enc"] == "234567890123"
        assert items[1]["aadhaar_number_enc"] == "345678901234"

        # Ciphertext at rest, not plaintext.
        factory = get_session_factory()
        async with factory() as session:
            row = (
                await session.execute(
                    text("SELECT nominee_info FROM onboarding_case WHERE id = :id"),
                    {"id": case["id"]},
                )
            ).scalar_one()
            assert row["items"][0]["aadhaar_number_enc"] != "234567890123"
            assert row["items"][0]["aadhaar_number_enc"].startswith("v1:")
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_get_public_case_unknown_token_returns_404(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    response = await client.get(f"/v1/public/onboarding/not-a-real-token-{uuid4().hex}")
    assert response.status_code == 404


async def test_expired_token_returns_404(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]), ttl_days=-1)

        response = await client.get(f"/v1/public/onboarding/{token}")
        assert response.status_code == 404
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_reissuing_token_revokes_previous_one(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        old_token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))
        new_token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))
        assert old_token != new_token

        old_response = await client.get(f"/v1/public/onboarding/{old_token}")
        assert old_response.status_code == 404

        new_response = await client.get(f"/v1/public/onboarding/{new_token}")
        assert new_response.status_code == 200
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_patch_section_rejected_once_case_not_writable(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)
        token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))
        await _force_status(company_id=company_id, case_id=UUID(case["id"]), status="SUBMITTED")

        response = await client.patch(
            f"/v1/public/onboarding/{token}/sections/personal_info",
            json={"first_name": "Asha"},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "ONBOARDING_SECTION_NOT_WRITABLE"
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_public_tokens_do_not_cross_tenant_boundaries(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The RLS-from-token mechanism (plan §5) is the highest-risk piece of this whole slice —
    proves a token for company A's case can never observe or mutate company B's case, even
    though both are looked up through the exact same route with no company-scoped auth at all."""
    headers_a, company_id_a, user_id_a = await _register_tenant(client)
    headers_b, company_id_b, user_id_b = await _register_tenant(client)
    try:
        case_a = await _create_case(client, headers_a, candidate_first_name="Asha")
        case_b = await _create_case(client, headers_b, candidate_first_name="Bilal")

        token_a = await _issue_token(company_id=company_id_a, case_id=UUID(case_a["id"]))
        token_b = await _issue_token(company_id=company_id_b, case_id=UUID(case_b["id"]))

        response_a = await client.get(f"/v1/public/onboarding/{token_a}")
        response_b = await client.get(f"/v1/public/onboarding/{token_b}")
        assert response_a.json()["data"]["candidate_first_name"] == "Asha"
        assert response_b.json()["data"]["candidate_first_name"] == "Bilal"

        await client.patch(
            f"/v1/public/onboarding/{token_a}/sections/personal_info",
            json={"first_name": "Asha", "gender": "Female"},
        )
        response_b_after = await client.get(f"/v1/public/onboarding/{token_b}")
        assert response_b_after.json()["data"]["personal_info"] == {}
    finally:
        await _teardown_with_tokens(company_id=company_id_a, user_id=user_id_a)
        await _teardown_with_tokens(company_id=company_id_b, user_id=user_id_b)
