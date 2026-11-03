"""Integration tests for W3 Overtime Policy and Regularization Policy — lighter coverage than
`test_attendance_policy.py` since the CRUD/versioning mechanics are identical (same service
pattern); this file focuses on what's specific to each: rate-row day_class uniqueness (Overtime)
and allowed-type uniqueness (Regularization)."""

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.organisation.test_registration_flow import _cleanup, _register

from hrms.core.db.session import get_session_factory, set_rls_company_id


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


async def _cleanup_attendance(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        for table in (
            "policy_assignment",
            "overtime_policy_version",
            "overtime_policy",
            "regularization_policy_version",
            "regularization_policy",
        ):
            await session.execute(
                text(f"DELETE FROM {table} WHERE company_id = :cid"), {"cid": str(company_id)}
            )
        await session.commit()


@pytest.mark.asyncio
async def test_overtime_policy_lifecycle_and_duplicate_rate_row_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        policy = await client.post(
            "/v1/overtime-policies", headers=headers, json={"name": "Standard OT"}
        )
        assert policy.status_code == 201, policy.text
        policy_id = policy.json()["data"]["id"]

        bad_draft = await client.post(
            f"/v1/overtime-policies/{policy_id}/versions",
            headers=headers,
            json={
                "effective_from": "2026-01-01",
                "rate_rows": [
                    {"day_class": "NORMAL", "classification_code": "OT_NORMAL"},
                    {"day_class": "NORMAL", "classification_code": "OT_NORMAL_DUP"},
                ],
            },
        )
        # Duplicate day_class is rejected immediately at draft creation, not deferred to publish.
        assert bad_draft.status_code == 422
        assert bad_draft.json()["error"]["code"] == "INVALID_POLICY_RATE_ROW"

        good_draft = await client.post(
            f"/v1/overtime-policies/{policy_id}/versions",
            headers=headers,
            json={
                "effective_from": "2026-01-01",
                "requires_post_approval": True,
                "rate_rows": [
                    {
                        "day_class": "NORMAL",
                        "classification_code": "OT_NORMAL",
                        "multiplier_decimal": "1.5000",
                    },
                    {"day_class": "HOLIDAY", "classification_code": "OT_HOLIDAY"},
                ],
            },
        )
        assert good_draft.status_code == 201, good_draft.text
        version_id = good_draft.json()["data"]["id"]
        published = await client.post(
            f"/v1/overtime-policies/{policy_id}/versions/{version_id}/publish",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert published.status_code == 200, published.text
        assert len(published.json()["data"]["rate_rows"]) == 2
    finally:
        await _cleanup_attendance(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_regularization_policy_lifecycle_and_duplicate_allowed_type_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        policy = await client.post(
            "/v1/regularization-policies", headers=headers, json={"name": "Standard Reg"}
        )
        assert policy.status_code == 201, policy.text
        policy_id = policy.json()["data"]["id"]

        bad_draft = await client.post(
            f"/v1/regularization-policies/{policy_id}/versions",
            headers=headers,
            json={
                "effective_from": "2026-01-01",
                "allowed_types": [
                    {"regularization_type": "MISSING_PUNCH"},
                    {"regularization_type": "MISSING_PUNCH"},
                ],
            },
        )
        # Duplicate regularization_type is rejected immediately at draft creation.
        assert bad_draft.status_code == 422
        assert bad_draft.json()["error"]["code"] == "INVALID_REGULARIZATION_ALLOWED_TYPE"

        good_draft = await client.post(
            f"/v1/regularization-policies/{policy_id}/versions",
            headers=headers,
            json={
                "effective_from": "2026-01-01",
                "allowed_types": [
                    {"regularization_type": "MISSING_PUNCH"},
                    {"regularization_type": "EXCESS_BREAK"},
                ],
                "approval_chain": "MANAGER_THEN_HR",
            },
        )
        assert good_draft.status_code == 201, good_draft.text
        version_id = good_draft.json()["data"]["id"]
        published = await client.post(
            f"/v1/regularization-policies/{policy_id}/versions/{version_id}/publish",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert published.status_code == 200, published.text
        assert len(published.json()["data"]["allowed_types"]) == 2
        assert published.json()["data"]["approval_chain"] == "MANAGER_THEN_HR"
    finally:
        await _cleanup_attendance(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_invalid_enum_value_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        policy = await client.post(
            "/v1/overtime-policies", headers=headers, json={"name": "Bad OT"}
        )
        policy_id = policy.json()["data"]["id"]
        response = await client.post(
            f"/v1/overtime-policies/{policy_id}/versions",
            headers=headers,
            json={"effective_from": "2026-01-01", "eligibility": "NOT_A_REAL_VALUE"},
        )
        assert response.status_code == 422
    finally:
        await _cleanup_attendance(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "prefix"),
    [("/v1/overtime-policies", "OTP-"), ("/v1/regularization-policies", "REGP-")],
)
async def test_policy_code_is_generated_and_not_accepted(
    client: AsyncClient, seeded_plan_catalogue: None, path: str, prefix: str
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        first = await client.post(path, headers=headers, json={"name": "One"})
        second = await client.post(path, headers=headers, json={"name": "Two"})
        assert first.status_code == 201, first.text
        assert second.status_code == 201, second.text
        first_code = first.json()["data"]["code"]
        assert first_code.startswith(prefix)
        assert first_code != second.json()["data"]["code"]
        rejected = await client.post(path, headers=headers, json={"name": "Typed", "code": "X"})
        assert rejected.status_code == 422
    finally:
        await _cleanup_attendance(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
