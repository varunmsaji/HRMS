"""Integration tests for `GET /v1/shifts/{shift_id}/versions` pagination (API-01 §6)."""

from typing import Any

import pytest
from httpx import AsyncClient

from .test_registration_flow import _cleanup
from .test_shift_version import _cleanup_shifts, _create_shift, _register_tenant

pytestmark = pytest.mark.asyncio


async def _publish_new_version(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    shift_id: str,
    effective_from: str,
    existing_draft_id: str | None = None,
    expected_previous_version: int | None = None,
) -> dict[str, Any]:
    """One insert-new/close-previous publish cycle. Pass `existing_draft_id` for the very first
    cycle (`_create_shift` already opens one draft); every subsequent cycle opens its own.
    `expected_previous_version` is the currently-published version's own `version` field —
    required by `POST .../publish` whenever one is already open, to guard the row it's about to
    supersede (mirrors the frontend's `ShiftDetailPage` `currentPublished.version` usage)."""
    if existing_draft_id is not None:
        draft_id = existing_draft_id
    else:
        draft_resp = await client.post(f"/v1/shifts/{shift_id}/versions", headers=headers, json={})
        assert draft_resp.status_code == 201, draft_resp.text
        draft_id = draft_resp.json()["data"]["id"]

    patched = await client.patch(
        f"/v1/shifts/{shift_id}/versions/{draft_id}",
        headers={**headers, "If-Match": "1"},
        json={
            "shift_type": "FIXED",
            "effective_from": effective_from,
            "start_time": "09:00",
            "end_time": "18:00",
        },
    )
    assert patched.status_code == 200, patched.text

    body: dict[str, Any] = {}
    if expected_previous_version is not None:
        body["expected_previous_version"] = expected_previous_version
    published = await client.post(
        f"/v1/shifts/{shift_id}/versions/{draft_id}/publish",
        headers={**headers, "If-Match": "2"},
        json=body,
    )
    assert published.status_code == 200, published.text
    return dict(published.json()["data"])


async def test_versions_paginate_deterministic_and_isolated(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers)
        published_ids = set()
        previous_version_number: int | None = None
        for i in range(4):
            version = await _publish_new_version(
                client,
                headers,
                shift_id=shift["id"],
                effective_from=f"2026-{i + 1:02d}-01",
                existing_draft_id=shift["draft_version_id"] if i == 0 else None,
                expected_previous_version=previous_version_number,
            )
            published_ids.add(version["id"])
            previous_version_number = version["version"]
        # A 5th open draft on top of the 4 now-superseded published versions — 5 rows total.
        open_draft_resp = await client.post(
            f"/v1/shifts/{shift['id']}/versions", headers=headers, json={}
        )
        assert open_draft_resp.status_code == 201, open_draft_resp.text
        open_draft = open_draft_resp.json()["data"]["id"]

        response = await client.get(
            f"/v1/shifts/{shift['id']}/versions", headers=headers, params={"per_page": 2}
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["data"]) == 2
        assert body["pagination"] == {
            "page": 1,
            "per_page": 2,
            "total": 5,
            "total_pages": 3,
            "next_cursor": None,
        }
        # Newest-first, deterministic secondary key — no duplicate IDs on one page.
        assert len({row["id"] for row in body["data"]}) == 2

        seen_ids: set[str] = set()
        for page in (1, 2, 3):
            page_resp = await client.get(
                f"/v1/shifts/{shift['id']}/versions",
                headers=headers,
                params={"page": page, "per_page": 2},
            )
            seen_ids.update(row["id"] for row in page_resp.json()["data"])
        assert seen_ids == published_ids | {open_draft}
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_versions_invalid_pagination_params_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers)
        response = await client.get(
            f"/v1/shifts/{shift['id']}/versions", headers=headers, params={"per_page": 101}
        )
        assert response.status_code == 422
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_versions_cross_shift_isolation_under_pagination(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift_a = await _create_shift(client, headers)
        shift_b = await _create_shift(client, headers)

        response_a = await client.get(f"/v1/shifts/{shift_a['id']}/versions", headers=headers)
        response_b = await client.get(f"/v1/shifts/{shift_b['id']}/versions", headers=headers)
        assert response_a.json()["pagination"]["total"] == 1
        assert response_b.json()["pagination"]["total"] == 1
        assert response_a.json()["data"][0]["id"] != response_b.json()["data"][0]["id"]
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
