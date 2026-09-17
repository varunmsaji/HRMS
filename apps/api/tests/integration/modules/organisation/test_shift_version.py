"""Integration tests for the W2 Shift + Break System — `/v1/shifts/{id}/versions*`.

Covers create/publish/discard for all three shift types (FIXED/FLEXIBLE/SPLIT), duty-block
and break validation, the insert-new/close-previous publish flow (mirroring
`test_workforce_calendar.py`'s `test_policy_assignment_insert_new_close_previous`/
`test_policy_assignment_overlap_rejected_without_closing`), cross-tenant 404, and stale-version
409s for both concurrency tokens. Pure validator-only coverage (no HTTP round-trip) lives in
`test_shift_version_validation.py`.
"""

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from hrms.core.db.session import get_session_factory, set_rls_company_id

from .test_registration_flow import _cleanup, _register


async def _register_tenant(
    client: AsyncClient, **overrides: Any
) -> tuple[dict[str, str], UUID, UUID | None]:
    response, company_id, user_id = await _register(client, **overrides)
    assert response.status_code == 201
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


async def _create_shift(
    client: AsyncClient, headers: dict[str, str], code: str = "GEN", **extra: Any
) -> dict[str, Any]:
    payload = {"code": code, "name": "General Shift", **extra}
    response = await client.post("/v1/shifts", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _cleanup_shifts(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        # A pooled connection that has ever had `app.company_id` set reverts to `''` (not
        # NULL) once its transaction ends — a Postgres custom-GUC-placeholder quirk, not an
        # RLS bug. Setting it explicitly here avoids `invalid input syntax for type uuid: ""`
        # on this unscoped raw cleanup query.
        await set_rls_company_id(session, str(company_id))
        await session.execute(
            text("DELETE FROM shift_version WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.execute(
            text("DELETE FROM shift WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.commit()


@pytest.mark.asyncio
async def test_create_shift_auto_creates_open_draft(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers)
        listed = await client.get(f"/v1/shifts/{shift['id']}/versions", headers=headers)
        assert listed.status_code == 200
        versions = listed.json()["data"]
        assert len(versions) == 1
        assert versions[0]["status"] == "DRAFT"
        assert versions[0]["id"] == shift["draft_version_id"]
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_second_draft_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers)
        response = await client.post(f"/v1/shifts/{shift['id']}/versions", headers=headers, json={})
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "SHIFT_VERSION_DRAFT_ALREADY_EXISTS"
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_publish_fixed_shift_success(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers)
        draft_id = shift["draft_version_id"]

        patched = await client.patch(
            f"/v1/shifts/{shift['id']}/versions/{draft_id}",
            headers={**headers, "If-Match": "1"},
            json={
                "shift_type": "FIXED",
                "effective_from": "2026-01-01",
                "start_time": "09:00",
                "end_time": "18:00",
            },
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["data"]["is_cross_midnight"] is False

        published = await client.post(
            f"/v1/shifts/{shift['id']}/versions/{draft_id}/publish",
            headers={**headers, "If-Match": "2"},
            json={},
        )
        assert published.status_code == 200, published.text
        data = published.json()["data"]
        assert data["status"] == "PUBLISHED"
        assert data["published_at"] is not None

        fetched_shift = await client.get(f"/v1/shifts/{shift['id']}", headers=headers)
        assert fetched_shift.json()["data"]["current_version_id"] == draft_id
        assert fetched_shift.json()["data"]["draft_version_id"] is None
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_publish_cross_midnight_fixed_shift_derives_flag(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers)
        draft_id = shift["draft_version_id"]
        await client.patch(
            f"/v1/shifts/{shift['id']}/versions/{draft_id}",
            headers={**headers, "If-Match": "1"},
            json={
                "shift_type": "FIXED",
                "effective_from": "2026-01-01",
                "start_time": "22:00",
                "end_time": "06:00",
                "is_night_shift": True,
            },
        )
        published = await client.post(
            f"/v1/shifts/{shift['id']}/versions/{draft_id}/publish",
            headers={**headers, "If-Match": "2"},
            json={},
        )
        assert published.status_code == 200, published.text
        data = published.json()["data"]
        assert data["is_cross_midnight"] is True
        assert data["is_night_shift"] is True
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_publish_fixed_shift_equal_times_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers)
        draft_id = shift["draft_version_id"]
        await client.patch(
            f"/v1/shifts/{shift['id']}/versions/{draft_id}",
            headers={**headers, "If-Match": "1"},
            json={
                "shift_type": "FIXED",
                "effective_from": "2026-01-01",
                "start_time": "09:00",
                "end_time": "09:00",
            },
        )
        published = await client.post(
            f"/v1/shifts/{shift['id']}/versions/{draft_id}/publish",
            headers={**headers, "If-Match": "2"},
            json={},
        )
        assert published.status_code == 422
        assert published.json()["error"]["code"] == "INVALID_SHIFT_VERSION_TIME_RANGE"
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_publish_flexible_shift_success(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers)
        draft_id = shift["draft_version_id"]
        await client.patch(
            f"/v1/shifts/{shift['id']}/versions/{draft_id}",
            headers={**headers, "If-Match": "1"},
            json={
                "shift_type": "FLEXIBLE",
                "effective_from": "2026-01-01",
                "window_start": "07:00",
                "window_end": "11:00",
                "core_start": "10:00",
                "core_end": "16:00",
                "required_minutes": 480,
            },
        )
        published = await client.post(
            f"/v1/shifts/{shift['id']}/versions/{draft_id}/publish",
            headers={**headers, "If-Match": "2"},
            json={},
        )
        assert published.status_code == 200, published.text
        assert published.json()["data"]["is_cross_midnight"] is False
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_publish_flexible_shift_core_hours_outside_window_accepted(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`window_start`-`window_end` is the *start-time* flexibility range (architecture §9.4's
    own example: "07:00-10:00 start"), not the whole working span — core hours are a separate,
    independently-positioned block and are not required to nest inside it."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers)
        draft_id = shift["draft_version_id"]
        await client.patch(
            f"/v1/shifts/{shift['id']}/versions/{draft_id}",
            headers={**headers, "If-Match": "1"},
            json={
                "shift_type": "FLEXIBLE",
                "effective_from": "2026-01-01",
                "window_start": "07:00",
                "window_end": "11:00",
                "core_start": "10:00",
                "core_end": "16:00",
                "required_minutes": 480,
            },
        )
        published = await client.post(
            f"/v1/shifts/{shift['id']}/versions/{draft_id}/publish",
            headers={**headers, "If-Match": "2"},
            json={},
        )
        assert published.status_code == 200, published.text
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_publish_flexible_shift_core_hours_inverted_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers)
        draft_id = shift["draft_version_id"]
        await client.patch(
            f"/v1/shifts/{shift['id']}/versions/{draft_id}",
            headers={**headers, "If-Match": "1"},
            json={
                "shift_type": "FLEXIBLE",
                "effective_from": "2026-01-01",
                "window_start": "07:00",
                "window_end": "11:00",
                "core_start": "16:00",
                "core_end": "10:00",
                "required_minutes": 480,
            },
        )
        published = await client.post(
            f"/v1/shifts/{shift['id']}/versions/{draft_id}/publish",
            headers={**headers, "If-Match": "2"},
            json={},
        )
        assert published.status_code == 422
        assert published.json()["error"]["code"] == "INVALID_SHIFT_VERSION_CORE_HOURS"
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_publish_split_shift_success(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers)
        draft_id = shift["draft_version_id"]
        await client.patch(
            f"/v1/shifts/{shift['id']}/versions/{draft_id}",
            headers={**headers, "If-Match": "1"},
            json={
                "shift_type": "SPLIT",
                "effective_from": "2026-01-01",
                "duty_blocks": [
                    {"sequence": 1, "start_time": "09:00", "end_time": "13:00"},
                    {"sequence": 2, "start_time": "17:00", "end_time": "21:00"},
                ],
            },
        )
        published = await client.post(
            f"/v1/shifts/{shift['id']}/versions/{draft_id}/publish",
            headers={**headers, "If-Match": "2"},
            json={},
        )
        assert published.status_code == 200, published.text
        data = published.json()["data"]
        assert len(data["duty_blocks"]) == 2
        assert data["is_cross_midnight"] is False
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_publish_split_shift_single_block_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers)
        draft_id = shift["draft_version_id"]
        await client.patch(
            f"/v1/shifts/{shift['id']}/versions/{draft_id}",
            headers={**headers, "If-Match": "1"},
            json={
                "shift_type": "SPLIT",
                "effective_from": "2026-01-01",
                "duty_blocks": [{"sequence": 1, "start_time": "09:00", "end_time": "13:00"}],
            },
        )
        published = await client.post(
            f"/v1/shifts/{shift['id']}/versions/{draft_id}/publish",
            headers={**headers, "If-Match": "2"},
            json={},
        )
        assert published.status_code == 422
        assert published.json()["error"]["code"] == "INVALID_SHIFT_VERSION_DUTY_BLOCK_COUNT"
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_publish_split_shift_overlapping_blocks_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers)
        draft_id = shift["draft_version_id"]
        await client.patch(
            f"/v1/shifts/{shift['id']}/versions/{draft_id}",
            headers={**headers, "If-Match": "1"},
            json={
                "shift_type": "SPLIT",
                "effective_from": "2026-01-01",
                "duty_blocks": [
                    {"sequence": 1, "start_time": "09:00", "end_time": "14:00"},
                    {"sequence": 2, "start_time": "13:00", "end_time": "18:00"},
                ],
            },
        )
        published = await client.post(
            f"/v1/shifts/{shift['id']}/versions/{draft_id}/publish",
            headers={**headers, "If-Match": "2"},
            json={},
        )
        assert published.status_code == 422
        assert published.json()["error"]["code"] == "INVALID_SHIFT_VERSION_DUTY_BLOCK_OVERLAP"
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_breaks_fixed_window_overlap_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers)
        draft_id = shift["draft_version_id"]
        response = await client.patch(
            f"/v1/shifts/{shift['id']}/versions/{draft_id}",
            headers={**headers, "If-Match": "1"},
            json={
                "breaks": [
                    {
                        "name": "Lunch",
                        "break_kind": "FIXED_WINDOW",
                        "start_time": "13:00",
                        "end_time": "14:00",
                        "is_paid": False,
                    },
                    {
                        "name": "Tea",
                        "break_kind": "FIXED_WINDOW",
                        "start_time": "13:30",
                        "end_time": "13:45",
                        "is_paid": True,
                    },
                ]
            },
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_SHIFT_BREAK_OVERLAP"
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_breaks_flexible_duration_min_exceeds_max_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers)
        draft_id = shift["draft_version_id"]
        response = await client.patch(
            f"/v1/shifts/{shift['id']}/versions/{draft_id}",
            headers={**headers, "If-Match": "1"},
            json={
                "breaks": [
                    {
                        "name": "Flexible break",
                        "break_kind": "FLEXIBLE_DURATION",
                        "window_start": "12:00",
                        "window_end": "15:00",
                        "min_minutes": 60,
                        "max_minutes": 30,
                        "is_paid": False,
                    }
                ]
            },
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_SHIFT_BREAK"
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_breaks_outside_fixed_shift_window_rejected_at_publish(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers)
        draft_id = shift["draft_version_id"]
        await client.patch(
            f"/v1/shifts/{shift['id']}/versions/{draft_id}",
            headers={**headers, "If-Match": "1"},
            json={
                "shift_type": "FIXED",
                "effective_from": "2026-01-01",
                "start_time": "09:00",
                "end_time": "18:00",
                "breaks": [
                    {
                        "name": "Late break",
                        "break_kind": "FIXED_WINDOW",
                        "start_time": "19:00",
                        "end_time": "19:30",
                        "is_paid": False,
                    }
                ],
            },
        )
        published = await client.post(
            f"/v1/shifts/{shift['id']}/versions/{draft_id}/publish",
            headers={**headers, "If-Match": "2"},
            json={},
        )
        assert published.status_code == 422
        assert published.json()["error"]["code"] == "INVALID_SHIFT_BREAK"
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_discard_draft_success(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers)
        draft_id = shift["draft_version_id"]
        response = await client.request(
            "DELETE",
            f"/v1/shifts/{shift['id']}/versions/{draft_id}",
            headers={**headers, "If-Match": "1"},
        )
        assert response.status_code == 200

        listed = await client.get(f"/v1/shifts/{shift['id']}/versions", headers=headers)
        # Discarded drafts are soft-deleted (deleted_at set) — excluded from the list.
        assert listed.json()["data"] == []

        recreated = await client.post(
            f"/v1/shifts/{shift['id']}/versions", headers=headers, json={}
        )
        assert recreated.status_code == 201
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_update_published_version_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers)
        draft_id = shift["draft_version_id"]
        await client.patch(
            f"/v1/shifts/{shift['id']}/versions/{draft_id}",
            headers={**headers, "If-Match": "1"},
            json={
                "shift_type": "FIXED",
                "effective_from": "2026-01-01",
                "start_time": "09:00",
                "end_time": "18:00",
            },
        )
        await client.post(
            f"/v1/shifts/{shift['id']}/versions/{draft_id}/publish",
            headers={**headers, "If-Match": "2"},
            json={},
        )
        response = await client.patch(
            f"/v1/shifts/{shift['id']}/versions/{draft_id}",
            headers={**headers, "If-Match": "3"},
            json={"timezone": "Asia/Kolkata"},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "SHIFT_VERSION_NOT_DRAFT"
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_publish_insert_new_close_previous(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers)
        first_draft_id = shift["draft_version_id"]
        await client.patch(
            f"/v1/shifts/{shift['id']}/versions/{first_draft_id}",
            headers={**headers, "If-Match": "1"},
            json={
                "shift_type": "FIXED",
                "effective_from": "2026-01-01",
                "start_time": "09:00",
                "end_time": "18:00",
            },
        )
        first_published = await client.post(
            f"/v1/shifts/{shift['id']}/versions/{first_draft_id}/publish",
            headers={**headers, "If-Match": "2"},
            json={},
        )
        assert first_published.status_code == 200
        first_version_token = first_published.json()["data"]["version"]

        second_draft = await client.post(
            f"/v1/shifts/{shift['id']}/versions", headers=headers, json={}
        )
        assert second_draft.status_code == 201
        second_draft_id = second_draft.json()["data"]["id"]
        await client.patch(
            f"/v1/shifts/{shift['id']}/versions/{second_draft_id}",
            headers={**headers, "If-Match": "1"},
            json={
                "shift_type": "FIXED",
                "effective_from": "2026-04-01",
                "start_time": "09:30",
                "end_time": "18:30",
            },
        )
        second_published = await client.post(
            f"/v1/shifts/{shift['id']}/versions/{second_draft_id}/publish",
            headers={**headers, "If-Match": "2"},
            json={"expected_previous_version": first_version_token},
        )
        assert second_published.status_code == 200, second_published.text

        listed = await client.get(f"/v1/shifts/{shift['id']}/versions", headers=headers)
        rows = listed.json()["data"]
        assert len(rows) == 2
        closed = next(r for r in rows if r["id"] == first_draft_id)
        assert closed["effective_to"] == "2026-03-31"
        open_version = next(r for r in rows if r["id"] == second_draft_id)
        assert open_version["effective_to"] is None

        resolved_before = await client.get(
            f"/v1/shifts/{shift['id']}/versions/resolve",
            headers=headers,
            params={"as_of": "2026-02-01"},
        )
        assert resolved_before.json()["data"]["id"] == first_draft_id

        resolved_after = await client.get(
            f"/v1/shifts/{shift['id']}/versions/resolve",
            headers=headers,
            params={"as_of": "2026-05-01"},
        )
        assert resolved_after.json()["data"]["id"] == second_draft_id
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_publish_overlap_rejected_without_previous_token(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers)
        first_draft_id = shift["draft_version_id"]
        await client.patch(
            f"/v1/shifts/{shift['id']}/versions/{first_draft_id}",
            headers={**headers, "If-Match": "1"},
            json={
                "shift_type": "FIXED",
                "effective_from": "2026-01-01",
                "start_time": "09:00",
                "end_time": "18:00",
            },
        )
        await client.post(
            f"/v1/shifts/{shift['id']}/versions/{first_draft_id}/publish",
            headers={**headers, "If-Match": "2"},
            json={},
        )

        second_draft = await client.post(
            f"/v1/shifts/{shift['id']}/versions", headers=headers, json={}
        )
        second_draft_id = second_draft.json()["data"]["id"]
        await client.patch(
            f"/v1/shifts/{shift['id']}/versions/{second_draft_id}",
            headers={**headers, "If-Match": "1"},
            json={
                "shift_type": "FIXED",
                "effective_from": "2026-04-01",
                "start_time": "09:30",
                "end_time": "18:30",
            },
        )
        response = await client.post(
            f"/v1/shifts/{shift['id']}/versions/{second_draft_id}/publish",
            headers={**headers, "If-Match": "2"},
            json={},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "SHIFT_VERSION_PREVIOUS_VERSION_REQUIRED"
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_publish_stale_draft_conflict(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers)
        draft_id = shift["draft_version_id"]
        await client.patch(
            f"/v1/shifts/{shift['id']}/versions/{draft_id}",
            headers={**headers, "If-Match": "1"},
            json={
                "shift_type": "FIXED",
                "effective_from": "2026-01-01",
                "start_time": "09:00",
                "end_time": "18:00",
            },
        )
        response = await client.post(
            f"/v1/shifts/{shift['id']}/versions/{draft_id}/publish",
            headers={**headers, "If-Match": "999"},
            json={},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "STALE_RESOURCE"
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_resolve_no_published_version_not_found(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers)
        response = await client.get(
            f"/v1/shifts/{shift['id']}/versions/resolve",
            headers=headers,
            params={"as_of": "2026-01-01"},
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "SHIFT_VERSION_NOT_FOUND_FOR_DATE"
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_cross_tenant_shift_version_not_found(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        shift_a = await _create_shift(client, headers_a)
        response = await client.get(
            f"/v1/shifts/{shift_a['id']}/versions/{shift_a['draft_version_id']}",
            headers=headers_b,
        )
        assert response.status_code == 404
    finally:
        await _cleanup_shifts(company_id=company_a)
        await _cleanup_shifts(company_id=company_b)
        await _cleanup(company_id=company_a, user_id=user_a)
        await _cleanup(company_id=company_b, user_id=user_b)


# ---------------------------------------------------------------------------
# NEW-01 / SR-09 — ShiftVersion timezone validation (execution gate §4.4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shift_version_create_invalid_timezone_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`IST` is the single most likely value an Indian HR user would type for their own
    timezone (`SR-09`) — before Phase 2, this was accepted at create and failed only at
    calculation time as an unhandled 500."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers)
        response = await client.post(
            f"/v1/shifts/{shift['id']}/versions",
            headers=headers,
            json={"timezone": "IST"},
        )
        assert response.status_code == 422, response.text
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_shift_version_update_invalid_timezone_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers)
        draft_id = shift["draft_version_id"]
        response = await client.patch(
            f"/v1/shifts/{shift['id']}/versions/{draft_id}",
            headers={**headers, "If-Match": "1"},
            json={"timezone": "IST"},
        )
        assert response.status_code == 422, response.text
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_shift_version_publish_rechecks_legacy_invalid_timezone(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Defence in depth (execution gate §4.3): a row written before the Phase 2 validators
    existed, whose `timezone` a later PATCH never happened to touch, must still be caught at
    publish — the one gate every version must pass before it can affect real attendance."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers)
        draft_id = shift["draft_version_id"]
        await client.patch(
            f"/v1/shifts/{shift['id']}/versions/{draft_id}",
            headers={**headers, "If-Match": "1"},
            json={
                "shift_type": "FIXED",
                "effective_from": "2026-01-01",
                "start_time": "09:00",
                "end_time": "18:00",
            },
        )
        # Simulates a legacy row: written directly, bypassing the schema validator entirely —
        # exactly what a row created before Phase 2 shipped would look like.
        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, str(company_id))
            await session.execute(
                text("UPDATE shift_version SET timezone = 'IST' WHERE id = :vid"),
                {"vid": draft_id},
            )
            await session.commit()

        published = await client.post(
            f"/v1/shifts/{shift['id']}/versions/{draft_id}/publish",
            headers={**headers, "If-Match": "2"},
            json={},
        )
        assert published.status_code == 422, published.text
        assert published.json()["error"]["code"] == "INVALID_SHIFT_VERSION_TIMEZONE"
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_shift_version_timezone_null_falls_through_wd06(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`NULL` remains valid — it is WD-06's "inherit from branch/company" signal, not an
    invalid value (7 live rows depend on this, execution gate §4.3)."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers)
        draft_id = shift["draft_version_id"]
        response = await client.patch(
            f"/v1/shifts/{shift['id']}/versions/{draft_id}",
            headers={**headers, "If-Match": "1"},
            json={"timezone": None},
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["timezone"] is None
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_shift_version_timezone_utc_accepted(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Regression guard: 22 live dev rows and 15 existing test literals carry `UTC` — must
    remain accepted, unaffected by the India-only registration gate (`CD-2`), which does not
    apply to `ShiftVersion` (execution gate §4.1, Option 1's rejection)."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers)
        draft_id = shift["draft_version_id"]
        response = await client.patch(
            f"/v1/shifts/{shift['id']}/versions/{draft_id}",
            headers={**headers, "If-Match": "1"},
            json={"timezone": "UTC"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["timezone"] == "UTC"
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_shift_version_timezone_asia_calcutta_canonicalised(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The one real IANA legacy alias handled (execution gate §5) — a real browser can send
    this; a guessed abbreviation like `IST` is never silently mapped."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers)
        draft_id = shift["draft_version_id"]
        response = await client.patch(
            f"/v1/shifts/{shift['id']}/versions/{draft_id}",
            headers={**headers, "If-Match": "1"},
            json={"timezone": "Asia/Calcutta"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["timezone"] == "Asia/Kolkata"
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
