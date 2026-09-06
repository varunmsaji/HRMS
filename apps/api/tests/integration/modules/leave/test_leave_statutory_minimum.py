"""Integration tests for the legal compliance floor — `/v1/statutory-leave-minimums*` CRUD and
the publish-time block on `LeavePolicyVersion` (LEAVE_DECISION_LOG.md LD-22).
"""

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


async def _cleanup_leave(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        for table in (
            "statutory_leave_minimum",
            "policy_assignment",
            "leave_policy_version",
            "leave_policy",
            "leave_type",
        ):
            await session.execute(
                text(f"DELETE FROM {table} WHERE company_id = :cid"), {"cid": str(company_id)}
            )
        await session.commit()


async def _create_leave_type(
    client: AsyncClient, headers: dict[str, str], **extra: Any
) -> dict[str, Any]:
    payload = {"code": "CL", "name": "Casual Leave", **extra}
    response = await client.post("/v1/leave-types", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _create_leave_policy(
    client: AsyncClient, headers: dict[str, str], **extra: Any
) -> dict[str, Any]:
    if "leave_type_id" not in extra:
        leave_type = await _create_leave_type(client, headers, statutory_category="EARNED")
        extra["leave_type_id"] = leave_type["id"]
    payload = {"name": "Standard Leave Policy", **extra}
    response = await client.post("/v1/leave-policies", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _create_minimum(
    client: AsyncClient, headers: dict[str, str], **extra: Any
) -> dict[str, Any]:
    payload = {"leave_category": "EARNED", "min_days_per_year": "12.00", **extra}
    response = await client.post("/v1/statutory-leave-minimums", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _publish_draft(
    client: AsyncClient, headers: dict[str, str], policy_id: str, **version_extra: Any
) -> Any:
    payload = {
        "effective_from": "2026-01-01",
        "accrual_frequency": "MONTHLY",
        "accrual_rate_per_cycle": "1.00",
        **version_extra,
    }
    draft = await client.post(
        f"/v1/leave-policies/{policy_id}/versions", headers=headers, json=payload
    )
    assert draft.status_code == 201, draft.text
    version_id = draft.json()["data"]["id"]
    return await client.post(
        f"/v1/leave-policies/{policy_id}/versions/{version_id}/publish",
        headers={**headers, "If-Match": "1"},
        json={},
    )


# ---------------------------------------------------------------------------
# Statutory Leave Minimum — CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_list_delete_statutory_minimum(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        created = await _create_minimum(
            client, headers, state_code="KA", establishment_type="SHOP_ESTABLISHMENT"
        )
        assert created["leave_category"] == "EARNED"
        assert created["min_days_per_year"] == "12.00"
        assert created["state_code"] == "KA"

        listed = await client.get("/v1/statutory-leave-minimums", headers=headers)
        assert listed.status_code == 200
        assert len(listed.json()["data"]) == 1

        deleted = await client.delete(
            f"/v1/statutory-leave-minimums/{created['id']}", headers=headers
        )
        assert deleted.status_code == 204

        listed_after = await client.get("/v1/statutory-leave-minimums", headers=headers)
        assert listed_after.json()["data"] == []
    finally:
        await _cleanup_leave(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_delete_unknown_minimum_not_found(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.delete(
            "/v1/statutory-leave-minimums/00000000-0000-0000-0000-000000000000",
            headers=headers,
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "LEAVE_STATUTORY_MINIMUM_NOT_FOUND"
    finally:
        await _cleanup_leave(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_invalid_leave_category_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.post(
            "/v1/statutory-leave-minimums",
            headers=headers,
            json={"leave_category": "BOGUS", "min_days_per_year": "5.00"},
        )
        assert response.status_code == 422
    finally:
        await _cleanup_leave(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# ---------------------------------------------------------------------------
# Publish-time enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_blocked_below_statutory_minimum(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        await _create_minimum(client, headers, min_days_per_year="15.00")
        policy = await _create_leave_policy(client, headers)

        # MONTHLY * 1.00 = 12 days/year, below the configured 15-day floor.
        published = await _publish_draft(client, headers, policy["id"])
        assert published.status_code == 422, published.text
        assert published.json()["error"]["code"] == "LEAVE_POLICY_BELOW_STATUTORY_MINIMUM"
    finally:
        await _cleanup_leave(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_publish_allowed_at_or_above_statutory_minimum(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        await _create_minimum(client, headers, min_days_per_year="12.00")
        policy = await _create_leave_policy(client, headers)

        # MONTHLY * 1.00 = 12 days/year, exactly at the floor.
        published = await _publish_draft(client, headers, policy["id"])
        assert published.status_code == 200, published.text
    finally:
        await _cleanup_leave(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_publish_uses_strictest_configured_minimum(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """LD-22 decision 3 — publish-time enforcement doesn't know which state/establishment_type
    a policy will end up assigned to, so it must compare against the MAX across all configured
    minimums for the category, not just one row."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        await _create_minimum(client, headers, state_code="KA", min_days_per_year="10.00")
        await _create_minimum(client, headers, state_code="MH", min_days_per_year="15.00")
        policy = await _create_leave_policy(client, headers)

        # 12 days/year clears KA's 10 but not MH's 15 — must still be blocked.
        published = await _publish_draft(client, headers, policy["id"])
        assert published.status_code == 422, published.text
        assert published.json()["error"]["code"] == "LEAVE_POLICY_BELOW_STATUTORY_MINIMUM"
    finally:
        await _cleanup_leave(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_publish_unaffected_when_leave_type_has_no_statutory_category(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        await _create_minimum(client, headers, min_days_per_year="99.00")
        leave_type = await _create_leave_type(client, headers)  # statutory_category defaults None
        policy = await _create_leave_policy(client, headers, leave_type_id=leave_type["id"])

        published = await _publish_draft(client, headers, policy["id"])
        assert published.status_code == 200, published.text
    finally:
        await _cleanup_leave(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_publish_unaffected_when_no_minimum_configured(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        policy = await _create_leave_policy(client, headers)  # statutory_category="EARNED"

        published = await _publish_draft(client, headers, policy["id"])
        assert published.status_code == 200, published.text
    finally:
        await _cleanup_leave(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
