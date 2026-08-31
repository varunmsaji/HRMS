"""Integration tests for Leave module L1 — `/v1/leave-types*`, `/v1/leave-policies*`.

Covers leave-type CRUD, leave-policy identity CRUD, draft/publish/discard versioning
(insert-new/close-previous, mirroring `test_attendance_policy.py`), cross-tenant 404, and the
`PolicyAssignment` integration (LEAVE_DECISION_LOG.md LD-04) — including the DB-level
`policy_assignment_policy_kind_check` CHECK constraint, not just the Pydantic allow-list.
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
    payload = {"name": "Standard Leave Policy", **extra}
    response = await client.post("/v1/leave-policies", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


# ---------------------------------------------------------------------------
# Leave Type
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_and_get_leave_type(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        leave_type = await _create_leave_type(client, headers)
        assert leave_type["code"] == "CL"
        assert leave_type["is_paid_default"] is True
        assert leave_type["requires_balance"] is True

        fetched = await client.get(f"/v1/leave-types/{leave_type['id']}", headers=headers)
        assert fetched.status_code == 200
        assert fetched.json()["data"]["name"] == "Casual Leave"
    finally:
        await _cleanup_leave(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_duplicate_leave_type_code_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        await _create_leave_type(client, headers)
        dup = await client.post(
            "/v1/leave-types", headers=headers, json={"code": "CL", "name": "Duplicate"}
        )
        assert dup.status_code == 409
        assert dup.json()["error"]["code"] == "LEAVE_TYPE_CODE_ALREADY_EXISTS"
    finally:
        await _cleanup_leave(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_update_leave_type_requires_if_match(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        leave_type = await _create_leave_type(client, headers)
        updated = await client.patch(
            f"/v1/leave-types/{leave_type['id']}",
            headers={**headers, "If-Match": "1"},
            json={"requires_balance": False},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["data"]["requires_balance"] is False
        assert updated.json()["data"]["version"] == 2

        stale = await client.patch(
            f"/v1/leave-types/{leave_type['id']}",
            headers={**headers, "If-Match": "1"},
            json={"is_active": False},
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "STALE_RESOURCE"
    finally:
        await _cleanup_leave(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# ---------------------------------------------------------------------------
# Leave Policy — identity + versions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_policy_has_no_draft_by_default(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        policy = await _create_leave_policy(client, headers)
        assert policy["is_active"] is True
        listed = await client.get(f"/v1/leave-policies/{policy['id']}/versions", headers=headers)
        assert listed.status_code == 200
        assert listed.json()["data"] == []
    finally:
        await _cleanup_leave(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_second_open_draft_rejected(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        policy = await _create_leave_policy(client, headers)
        first = await client.post(
            f"/v1/leave-policies/{policy['id']}/versions", headers=headers, json={}
        )
        assert first.status_code == 201, first.text
        second = await client.post(
            f"/v1/leave-policies/{policy['id']}/versions", headers=headers, json={}
        )
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "LEAVE_POLICY_DRAFT_ALREADY_EXISTS"
    finally:
        await _cleanup_leave(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_publish_without_effective_from_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        policy = await _create_leave_policy(client, headers)
        draft = await client.post(
            f"/v1/leave-policies/{policy['id']}/versions", headers=headers, json={}
        )
        assert draft.status_code == 201, draft.text
        version_id = draft.json()["data"]["id"]

        published = await client.post(
            f"/v1/leave-policies/{policy['id']}/versions/{version_id}/publish",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert published.status_code == 422, published.text
        assert published.json()["error"]["code"] == "LEAVE_POLICY_PUBLISH_INCOMPLETE"
    finally:
        await _cleanup_leave(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_publish_success_and_resolve_as_of(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        policy = await _create_leave_policy(client, headers)
        draft = await client.post(
            f"/v1/leave-policies/{policy['id']}/versions",
            headers=headers,
            json={
                "effective_from": "2026-01-01",
                "accrual_frequency": "MONTHLY",
                "accrual_rate_per_cycle": "1.50",
                "approval_chain": "MANAGER_THEN_HR",
            },
        )
        assert draft.status_code == 201, draft.text
        version_id = draft.json()["data"]["id"]

        published = await client.post(
            f"/v1/leave-policies/{policy['id']}/versions/{version_id}/publish",
            headers={**headers, "If-Match": "1"},
            json={"publish_reason": "Initial rollout"},
        )
        assert published.status_code == 200, published.text
        data = published.json()["data"]
        assert data["status"] == "PUBLISHED"
        assert data["accrual_frequency"] == "MONTHLY"
        assert data["accrual_rate_per_cycle"] == "1.50"
        assert data["approval_chain"] == "MANAGER_THEN_HR"

        resolved = await client.get(
            f"/v1/leave-policies/{policy['id']}/versions/resolve",
            headers=headers,
            params={"as_of": "2026-06-01"},
        )
        assert resolved.status_code == 200
        assert resolved.json()["data"]["id"] == version_id

        before_effective = await client.get(
            f"/v1/leave-policies/{policy['id']}/versions/resolve",
            headers=headers,
            params={"as_of": "2025-01-01"},
        )
        assert before_effective.status_code == 404
    finally:
        await _cleanup_leave(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_publish_second_version_insert_new_close_previous(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        policy = await _create_leave_policy(client, headers)
        first_draft = await client.post(
            f"/v1/leave-policies/{policy['id']}/versions",
            headers=headers,
            json={"effective_from": "2026-01-01"},
        )
        version1_id = first_draft.json()["data"]["id"]
        publish1 = await client.post(
            f"/v1/leave-policies/{policy['id']}/versions/{version1_id}/publish",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert publish1.status_code == 200, publish1.text

        second_draft = await client.post(
            f"/v1/leave-policies/{policy['id']}/versions",
            headers=headers,
            json={"effective_from": "2026-07-01"},
        )
        version2_id = second_draft.json()["data"]["id"]

        missing_token = await client.post(
            f"/v1/leave-policies/{policy['id']}/versions/{version2_id}/publish",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert missing_token.status_code == 422
        assert (
            missing_token.json()["error"]["code"]
            == "LEAVE_POLICY_VERSION_PREVIOUS_VERSION_REQUIRED"
        )

        publish2 = await client.post(
            f"/v1/leave-policies/{policy['id']}/versions/{version2_id}/publish",
            headers={**headers, "If-Match": "1"},
            json={"expected_previous_version": 2},
        )
        assert publish2.status_code == 200, publish2.text

        versions = await client.get(f"/v1/leave-policies/{policy['id']}/versions", headers=headers)
        by_id = {v["id"]: v for v in versions.json()["data"]}
        assert by_id[version1_id]["effective_to"] == "2026-06-30"
        assert by_id[version2_id]["effective_to"] is None
    finally:
        await _cleanup_leave(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_published_version_immutable(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        policy = await _create_leave_policy(client, headers)
        draft = await client.post(
            f"/v1/leave-policies/{policy['id']}/versions",
            headers=headers,
            json={"effective_from": "2026-01-01"},
        )
        version_id = draft.json()["data"]["id"]
        await client.post(
            f"/v1/leave-policies/{policy['id']}/versions/{version_id}/publish",
            headers={**headers, "If-Match": "1"},
            json={},
        )

        patched = await client.patch(
            f"/v1/leave-policies/{policy['id']}/versions/{version_id}",
            headers={**headers, "If-Match": "2"},
            json={"reason_required": False},
        )
        assert patched.status_code == 409
        assert patched.json()["error"]["code"] == "LEAVE_POLICY_VERSION_NOT_DRAFT"

        discarded = await client.delete(
            f"/v1/leave-policies/{policy['id']}/versions/{version_id}",
            headers={**headers, "If-Match": "2"},
        )
        assert discarded.status_code == 409
        assert discarded.json()["error"]["code"] == "LEAVE_POLICY_VERSION_NOT_DRAFT"
    finally:
        await _cleanup_leave(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_discard_draft(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        policy = await _create_leave_policy(client, headers)
        draft = await client.post(
            f"/v1/leave-policies/{policy['id']}/versions",
            headers=headers,
            json={"effective_from": "2026-01-01"},
        )
        version_id = draft.json()["data"]["id"]

        discarded = await client.delete(
            f"/v1/leave-policies/{policy['id']}/versions/{version_id}",
            headers={**headers, "If-Match": "1"},
        )
        assert discarded.status_code == 200, discarded.text

        # A new draft can now be opened again (the discarded one no longer blocks it).
        reopened = await client.post(
            f"/v1/leave-policies/{policy['id']}/versions", headers=headers, json={}
        )
        assert reopened.status_code == 201, reopened.text
    finally:
        await _cleanup_leave(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_cross_tenant_policy_not_found(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        policy = await _create_leave_policy(client, headers_a)
        response = await client.get(f"/v1/leave-policies/{policy['id']}", headers=headers_b)
        assert response.status_code == 404
    finally:
        await _cleanup_leave(company_id=company_a)
        await _cleanup_leave(company_id=company_b)
        await _cleanup(company_id=company_a, user_id=user_a)
        await _cleanup(company_id=company_b, user_id=user_b)


@pytest.mark.asyncio
async def test_unauthenticated_request_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    response = await client.get("/v1/leave-policies")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# PolicyAssignment integration (LEAVE_DECISION_LOG.md LD-04)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_leave_policy_assignable_at_company_scope(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Exercises both the Pydantic `_POLICY_KINDS` allow-list *and* the DB-level
    `policy_assignment_policy_kind_check` CHECK constraint — a real bug caught during manual
    verification where only the Pydantic side had been widened."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        policy = await _create_leave_policy(client, headers)
        draft = await client.post(
            f"/v1/leave-policies/{policy['id']}/versions",
            headers=headers,
            json={"effective_from": "2026-01-01"},
        )
        version_id = draft.json()["data"]["id"]
        await client.post(
            f"/v1/leave-policies/{policy['id']}/versions/{version_id}/publish",
            headers={**headers, "If-Match": "1"},
            json={},
        )

        assignment = await client.post(
            "/v1/policy-assignments",
            headers=headers,
            json={
                "policy_kind": "LEAVE_POLICY",
                "policy_id": policy["id"],
                "scope_type": "COMPANY",
                "effective_from": "2026-01-01",
            },
        )
        assert assignment.status_code == 201, assignment.text
        assert assignment.json()["data"]["policy_kind"] == "LEAVE_POLICY"

        # A policy_id that doesn't exist is still rejected as an invalid reference, not
        # silently accepted just because the kind is now allowed. A non-COMPANY scope_type is
        # used here (with an arbitrary UUID — scope_id carries no DB FK, per architecture §15.1)
        # purely to avoid colliding with the COMPANY-scope assignment just created above.
        bad_ref = await client.post(
            "/v1/policy-assignments",
            headers=headers,
            json={
                "policy_kind": "LEAVE_POLICY",
                "policy_id": "00000000-0000-0000-0000-000000000000",
                "scope_type": "DESIGNATION",
                "scope_id": "11111111-2222-4333-8444-555555555555",
                "effective_from": "2026-01-01",
            },
        )
        assert bad_ref.status_code in (400, 404, 422), bad_ref.text
    finally:
        await _cleanup_leave(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
