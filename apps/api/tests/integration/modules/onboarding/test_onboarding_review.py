"""Integration tests for the Onboarding module's O6 slice — section review
(`POST /onboarding-cases/{id}/sections/{section}/review`) and the changes-requested loop
(`POST /onboarding-cases/{id}/request-changes`).

Covers: the first review action moving `SUBMITTED -> UNDER_REVIEW`, reject requiring a reason,
the auto-`VERIFIED` transition once every section (and document — zero here, vacuously
satisfied) is verified, a verified section becoming locked against further candidate `PATCH`es,
`request-changes` reopening exactly the rejected section (others stay locked) and notifying the
candidate, resubmission resetting the fixed section back to `PENDING`, permission gating, and
invalid-input rejection."""

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


async def _cleanup_section_reviews(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("DELETE FROM onboarding_section_review WHERE company_id = :cid"),
            {"cid": str(company_id)},
        )
        await session.commit()


async def _teardown_with_tokens(*, company_id: UUID, user_id: UUID | None) -> None:
    await _cleanup_section_reviews(company_id=company_id)
    await _cleanup_tokens(company_id=company_id)
    await _teardown(company_id=company_id, user_id=user_id)


async def _submitted_case(
    client: AsyncClient, headers: dict[str, str]
) -> tuple[dict[str, Any], str]:
    case = await _create_case(client, headers)
    company_id = UUID(headers["X-Company-Id"])
    token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))
    await _fill_all_sections(client, token)
    submit = await client.post(f"/v1/public/onboarding/{token}/submit")
    assert submit.status_code == 200, submit.text
    return case, token


def _review_url(case_id: str, section: str) -> str:
    return f"/v1/onboarding-cases/{case_id}/sections/{section}/review"


async def test_review_section_first_action_moves_to_under_review(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case, _token = await _submitted_case(client, headers)

        response = await client.post(
            _review_url(case["id"], "personal_info"), headers=headers, json={"status": "VERIFIED"}
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["status"] == "VERIFIED"

        admin_view = (
            await client.get(f"/v1/onboarding-cases/{case['id']}", headers=headers)
        ).json()["data"]
        assert admin_view["status"] == "UNDER_REVIEW"
        assert admin_view["personal_info"]["first_name"] == "Asha"
        section_statuses = {s["section"]: s["status"] for s in admin_view["section_reviews"]}
        assert section_statuses["personal_info"] == "VERIFIED"
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_review_section_reject_requires_reason(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case, _token = await _submitted_case(client, headers)

        response = await client.post(
            _review_url(case["id"], "bank_info"), headers=headers, json={"status": "REJECTED"}
        )
        assert response.status_code == 422

        with_reason = await client.post(
            _review_url(case["id"], "bank_info"),
            headers=headers,
            json={"status": "REJECTED", "rejection_reason": "IFSC looks wrong"},
        )
        assert with_reason.status_code == 200
        assert with_reason.json()["data"]["status"] == "REJECTED"
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_review_section_invalid_name_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case, _token = await _submitted_case(client, headers)

        response = await client.post(
            _review_url(case["id"], "not_a_real_section"),
            headers=headers,
            json={"status": "VERIFIED"},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_SECTION"
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_review_section_before_submit_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)

        response = await client.post(
            _review_url(case["id"], "personal_info"), headers=headers, json={"status": "VERIFIED"}
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "ONBOARDING_CASE_NOT_REVIEWABLE"
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_review_section_without_permission_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    from hrms.modules.onboarding.permissions import ONBOARDING_VIEW

    headers, company_id, user_id = await _register_tenant(client)
    try:
        case, _token = await _submitted_case(client, headers)
        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=[ONBOARDING_VIEW]
        )

        response = await client.post(
            _review_url(case["id"], "personal_info"),
            headers=scoped_headers,
            json={"status": "VERIFIED"},
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_verifying_all_sections_auto_verifies_case(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case, _token = await _submitted_case(client, headers)

        sections = ["personal_info", "address_info", "emergency_contact", "bank_info"]
        for section in sections:
            response = await client.post(
                _review_url(case["id"], section), headers=headers, json={"status": "VERIFIED"}
            )
            assert response.status_code == 200, response.text

        mid_view = (await client.get(f"/v1/onboarding-cases/{case['id']}", headers=headers)).json()[
            "data"
        ]
        assert mid_view["status"] == "UNDER_REVIEW"

        last = await client.post(
            _review_url(case["id"], "statutory_info"), headers=headers, json={"status": "VERIFIED"}
        )
        assert last.status_code == 200

        final_view = (
            await client.get(f"/v1/onboarding-cases/{case['id']}", headers=headers)
        ).json()["data"]
        assert final_view["status"] == "VERIFIED"
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_patch_section_locked_after_verified(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case, token = await _submitted_case(client, headers)
        await client.post(
            _review_url(case["id"], "personal_info"), headers=headers, json={"status": "VERIFIED"}
        )

        # Case is UNDER_REVIEW (not writable at all), so first drive it to CHANGES_REQUESTED via
        # a rejection elsewhere, to isolate the per-section lock from the case-level gate.
        await client.post(
            _review_url(case["id"], "bank_info"),
            headers=headers,
            json={"status": "REJECTED", "rejection_reason": "fix IFSC"},
        )
        await client.post(f"/v1/onboarding-cases/{case['id']}/request-changes", headers=headers)

        response = await client.patch(
            f"/v1/public/onboarding/{token}/sections/personal_info",
            json={"first_name": "Changed"},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "ONBOARDING_SECTION_ALREADY_VERIFIED"
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_request_changes_without_rejection_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case, _token = await _submitted_case(client, headers)

        response = await client.post(
            f"/v1/onboarding-cases/{case['id']}/request-changes", headers=headers
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "ONBOARDING_NOTHING_TO_REQUEST_CHANGES_FOR"
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_request_changes_reopens_only_rejected_section_and_resubmit_resets_it(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case, token = await _submitted_case(client, headers)

        for section in ["personal_info", "address_info", "emergency_contact", "statutory_info"]:
            resp = await client.post(
                _review_url(case["id"], section), headers=headers, json={"status": "VERIFIED"}
            )
            assert resp.status_code == 200
        await client.post(
            _review_url(case["id"], "bank_info"),
            headers=headers,
            json={"status": "REJECTED", "rejection_reason": "IFSC looks wrong"},
        )

        changes = await client.post(
            f"/v1/onboarding-cases/{case['id']}/request-changes", headers=headers
        )
        assert changes.status_code == 200, changes.text
        assert changes.json()["data"]["status"] == "CHANGES_REQUESTED"

        # The candidate's own view surfaces the rejection reason and per-section lock state.
        public_view = (await client.get(f"/v1/public/onboarding/{token}")).json()["data"]
        assert public_view["status"] == "CHANGES_REQUESTED"
        assert public_view["writable"] is True
        public_sections = {s["section"]: s for s in public_view["section_reviews"]}
        assert public_sections["bank_info"]["status"] == "REJECTED"
        assert public_sections["personal_info"]["status"] == "VERIFIED"

        # A still-VERIFIED section stays locked...
        locked = await client.patch(
            f"/v1/public/onboarding/{token}/sections/personal_info",
            json={"first_name": "Changed"},
        )
        assert locked.status_code == 409

        # ...but the rejected one is writable, and fixing it resets it to PENDING.
        fixed = await client.patch(
            f"/v1/public/onboarding/{token}/sections/bank_info",
            json={"payment_mode": "UPI"},
        )
        assert fixed.status_code == 200, fixed.text
        fixed_sections = {s["section"]: s for s in fixed.json()["data"]["section_reviews"]}
        assert fixed_sections["bank_info"]["status"] == "PENDING"
        assert fixed_sections["bank_info"]["rejection_reason"] is None

        resubmit = await client.post(f"/v1/public/onboarding/{token}/submit")
        assert resubmit.status_code == 200
        assert resubmit.json()["data"]["status"] == "SUBMITTED"

        admin_view = (
            await client.get(f"/v1/onboarding-cases/{case['id']}", headers=headers)
        ).json()["data"]
        admin_sections = {s["section"]: s["status"] for s in admin_view["section_reviews"]}
        assert admin_sections["personal_info"] == "VERIFIED"
        assert admin_sections["bank_info"] == "PENDING"
    finally:
        await _teardown_with_tokens(company_id=company_id, user_id=user_id)


async def test_review_section_cross_tenant_isolation(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_id_a, user_id_a = await _register_tenant(client)
    headers_b, company_id_b, user_id_b = await _register_tenant(client)
    try:
        case_a, _token_a = await _submitted_case(client, headers_a)

        response = await client.post(
            _review_url(case_a["id"], "personal_info"),
            headers=headers_b,
            json={"status": "VERIFIED"},
        )
        assert response.status_code == 404
    finally:
        await _teardown_with_tokens(company_id=company_id_a, user_id=user_id_a)
        await _teardown_with_tokens(company_id=company_id_b, user_id=user_id_b)
