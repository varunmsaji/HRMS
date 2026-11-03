"""Integration tests for W3 Attendance Policy — `/v1/attendance-policies*`.

Covers identity CRUD, draft/publish versioning (insert-new/close-previous, mirroring
`test_shift_version.py`), hour-band publish validation, and cross-tenant 404.
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


async def _cleanup_attendance(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        for table in (
            "policy_assignment",
            "attendance_policy_version",
            "attendance_policy",
            "overtime_policy_version",
            "overtime_policy",
            "regularization_policy_version",
            "regularization_policy",
        ):
            await session.execute(
                text(f"DELETE FROM {table} WHERE company_id = :cid"), {"cid": str(company_id)}
            )
        await session.commit()


async def _create_policy(
    client: AsyncClient, headers: dict[str, str], **extra: Any
) -> dict[str, Any]:
    payload = {"name": "Standard Attendance Policy", **extra}
    response = await client.post("/v1/attendance-policies", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


@pytest.mark.asyncio
async def test_create_policy_has_no_draft_by_default(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        policy = await _create_policy(client, headers)
        assert policy["is_active"] is True
        listed = await client.get(
            f"/v1/attendance-policies/{policy['id']}/versions", headers=headers
        )
        assert listed.status_code == 200
        assert listed.json()["data"] == []
    finally:
        await _cleanup_attendance(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_second_open_draft_rejected(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        policy = await _create_policy(client, headers)
        first = await client.post(
            f"/v1/attendance-policies/{policy['id']}/versions", headers=headers, json={}
        )
        assert first.status_code == 201, first.text
        second = await client.post(
            f"/v1/attendance-policies/{policy['id']}/versions", headers=headers, json={}
        )
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "POLICY_DRAFT_ALREADY_EXISTS"
    finally:
        await _cleanup_attendance(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_publish_without_hour_bands_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        policy = await _create_policy(client, headers)
        draft = await client.post(
            f"/v1/attendance-policies/{policy['id']}/versions",
            headers=headers,
            json={"effective_from": "2026-01-01", "grace_in_minutes": 10},
        )
        assert draft.status_code == 201
        version_id = draft.json()["data"]["id"]

        published = await client.post(
            f"/v1/attendance-policies/{policy['id']}/versions/{version_id}/publish",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert published.status_code == 422, published.text
        assert published.json()["error"]["code"] == "INVALID_POLICY_BAND"
    finally:
        await _cleanup_attendance(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_publish_overlapping_hour_bands_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        policy = await _create_policy(client, headers)
        draft = await client.post(
            f"/v1/attendance-policies/{policy['id']}/versions",
            headers=headers,
            json={
                "effective_from": "2026-01-01",
                "hour_bands": [
                    {"min_minutes": 0, "max_minutes": 300, "result_status": "ABSENT"},
                    {"min_minutes": 200, "max_minutes": 480, "result_status": "HALF_DAY"},
                ],
            },
        )
        assert draft.status_code == 201, draft.text
        version_id = draft.json()["data"]["id"]

        published = await client.post(
            f"/v1/attendance-policies/{policy['id']}/versions/{version_id}/publish",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert published.status_code == 422, published.text
        assert published.json()["error"]["code"] == "INVALID_POLICY_BAND"
    finally:
        await _cleanup_attendance(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_publish_success_and_resolve_as_of(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        policy = await _create_policy(client, headers)
        draft = await client.post(
            f"/v1/attendance-policies/{policy['id']}/versions",
            headers=headers,
            json={
                "effective_from": "2026-01-01",
                "grace_in_minutes": 10,
                "hour_bands": [
                    {"min_minutes": 0, "max_minutes": 239, "result_status": "ABSENT"},
                    {"min_minutes": 240, "max_minutes": 479, "result_status": "HALF_DAY"},
                    {"min_minutes": 480, "max_minutes": None, "result_status": "PRESENT"},
                ],
                "late_bands": [
                    {"min_minutes": 0, "max_minutes": 30, "classification": "LATE"},
                    {"min_minutes": 31, "max_minutes": None, "classification": "HALF_DAY"},
                ],
            },
        )
        assert draft.status_code == 201, draft.text
        version_id = draft.json()["data"]["id"]

        published = await client.post(
            f"/v1/attendance-policies/{policy['id']}/versions/{version_id}/publish",
            headers={**headers, "If-Match": "1"},
            json={"publish_reason": "Initial rollout"},
        )
        assert published.status_code == 200, published.text
        data = published.json()["data"]
        assert data["status"] == "PUBLISHED"
        assert len(data["hour_bands"]) == 3
        assert len(data["late_bands"]) == 2

        resolved = await client.get(
            f"/v1/attendance-policies/{policy['id']}/versions/resolve",
            headers=headers,
            params={"as_of": "2026-06-01"},
        )
        assert resolved.status_code == 200
        assert resolved.json()["data"]["id"] == version_id

        before_effective = await client.get(
            f"/v1/attendance-policies/{policy['id']}/versions/resolve",
            headers=headers,
            params={"as_of": "2025-01-01"},
        )
        assert before_effective.status_code == 404
    finally:
        await _cleanup_attendance(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_publish_second_version_insert_new_close_previous(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        policy = await _create_policy(client, headers)
        first_draft = await client.post(
            f"/v1/attendance-policies/{policy['id']}/versions",
            headers=headers,
            json={
                "effective_from": "2026-01-01",
                "hour_bands": [{"min_minutes": 0, "max_minutes": None, "result_status": "PRESENT"}],
            },
        )
        version1_id = first_draft.json()["data"]["id"]
        publish1 = await client.post(
            f"/v1/attendance-policies/{policy['id']}/versions/{version1_id}/publish",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert publish1.status_code == 200, publish1.text

        second_draft = await client.post(
            f"/v1/attendance-policies/{policy['id']}/versions",
            headers=headers,
            json={
                "effective_from": "2026-07-01",
                "hour_bands": [{"min_minutes": 0, "max_minutes": None, "result_status": "PRESENT"}],
            },
        )
        version2_id = second_draft.json()["data"]["id"]

        # Missing expected_previous_version -> 422
        missing_token = await client.post(
            f"/v1/attendance-policies/{policy['id']}/versions/{version2_id}/publish",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert missing_token.status_code == 422
        assert missing_token.json()["error"]["code"] == "POLICY_VERSION_PREVIOUS_VERSION_REQUIRED"

        publish2 = await client.post(
            f"/v1/attendance-policies/{policy['id']}/versions/{version2_id}/publish",
            headers={**headers, "If-Match": "1"},
            json={"expected_previous_version": 2},
        )
        assert publish2.status_code == 200, publish2.text

        versions = await client.get(
            f"/v1/attendance-policies/{policy['id']}/versions", headers=headers
        )
        by_id = {v["id"]: v for v in versions.json()["data"]}
        assert by_id[version1_id]["effective_to"] == "2026-06-30"
        assert by_id[version2_id]["effective_to"] is None
    finally:
        await _cleanup_attendance(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_published_version_immutable(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        policy = await _create_policy(client, headers)
        draft = await client.post(
            f"/v1/attendance-policies/{policy['id']}/versions",
            headers=headers,
            json={
                "effective_from": "2026-01-01",
                "hour_bands": [{"min_minutes": 0, "max_minutes": None, "result_status": "PRESENT"}],
            },
        )
        version_id = draft.json()["data"]["id"]
        await client.post(
            f"/v1/attendance-policies/{policy['id']}/versions/{version_id}/publish",
            headers={**headers, "If-Match": "1"},
            json={},
        )

        patched = await client.patch(
            f"/v1/attendance-policies/{policy['id']}/versions/{version_id}",
            headers={**headers, "If-Match": "2"},
            json={"grace_in_minutes": 20},
        )
        assert patched.status_code == 409
        assert patched.json()["error"]["code"] == "POLICY_VERSION_NOT_DRAFT"

        discarded = await client.delete(
            f"/v1/attendance-policies/{policy['id']}/versions/{version_id}",
            headers={**headers, "If-Match": "2"},
        )
        assert discarded.status_code == 409
        assert discarded.json()["error"]["code"] == "POLICY_VERSION_NOT_DRAFT"
    finally:
        await _cleanup_attendance(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_cross_tenant_policy_not_found(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        policy = await _create_policy(client, headers_a)
        response = await client.get(f"/v1/attendance-policies/{policy['id']}", headers=headers_b)
        assert response.status_code == 404
    finally:
        await _cleanup_attendance(company_id=company_a)
        await _cleanup_attendance(company_id=company_b)
        await _cleanup(company_id=company_a, user_id=user_a)
        await _cleanup(company_id=company_b, user_id=user_b)


@pytest.mark.asyncio
async def test_unauthenticated_request_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    response = await client.get("/v1/attendance-policies")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_policy_code_is_generated_and_not_accepted(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        first = await _create_policy(client, headers, name="Auto code one")
        second = await _create_policy(client, headers, name="Auto code two")
        assert first["code"].startswith("ATTP-")
        assert first["code"] != second["code"]
        rejected = await client.post(
            "/v1/attendance-policies", headers=headers, json={"name": "Typed", "code": "MINE"}
        )
        assert rejected.status_code == 422
    finally:
        await _cleanup_attendance(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
