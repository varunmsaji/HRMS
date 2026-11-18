"""H-01 (owner decision), through the real API: hour bands must cover every minute count.

Publication refuses hour bands that do not start at 0, leave a gap, or end bounded. A draft may be
saved incomplete. Late-mark and early-departure bands may leave gaps (no mark). A version published
before the rule is never edited - HR publishes a corrected one.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from tests.integration.modules.attendance.test_attendance_day import _register_tenant
from tests.integration.modules.attendance.test_attendance_policy import (
    _cleanup_attendance,
    _create_policy,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

pytestmark = pytest.mark.asyncio


def _band(lo: int, hi: int | None, status: str) -> dict[str, Any]:
    return {"min_minutes": lo, "max_minutes": hi, "result_status": status}


GOOD = [_band(0, 239, "ABSENT"), _band(240, 479, "HALF_DAY"), _band(480, None, "PRESENT")]
BAD: dict[str, tuple[list[dict[str, Any]], str]] = {
    "starts_at_240": ([_band(240, None, "PRESENT")], "must start at 0 minutes"),
    "starts_at_1": ([_band(1, 239, "ABSENT"), _band(240, None, "PRESENT")], "must start at 0"),
    "gap_240_299": (
        [_band(0, 239, "ABSENT"), _band(300, None, "PRESENT")],
        "minutes 240 to 299 are not covered",
    ),
    "bounded_last": (
        [_band(0, 239, "ABSENT"), _band(240, 479, "PRESENT")],
        "must be open-ended",
    ),
}


async def _draft(
    client: AsyncClient, headers: dict[str, str], policy_id: str, **body: Any
) -> dict[str, Any]:
    response = await client.post(
        f"/v1/attendance-policies/{policy_id}/versions",
        headers=headers,
        json={"effective_from": "2026-01-01", **body},
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _publish(
    client: AsyncClient, headers: dict[str, str], policy_id: str, draft: dict[str, Any]
) -> Any:
    return await client.post(
        f"/v1/attendance-policies/{policy_id}/versions/{draft['id']}/publish",
        headers={**headers, "If-Match": str(draft["version"])},
        json={},
    )


@pytest.mark.parametrize("case", sorted(BAD))
async def test_publication_refuses_bands_that_do_not_cover_every_minute(
    client: AsyncClient, seeded_plan_catalogue: None, case: str
) -> None:
    bands, fragment = BAD[case]
    headers, company_id, user_id = await _register_tenant(client)
    try:
        policy = await _create_policy(client, headers)
        draft = await _draft(
            client, headers, policy["id"], hour_bands=bands
        )  # saved: it is a draft
        refused = await _publish(client, headers, policy["id"], draft)
        assert refused.status_code == 422, refused.text
        error = refused.json()["error"]
        assert error["code"] == "INVALID_POLICY_BAND"
        assert fragment in error["details"][0]["message"]
        assert error["details"][0]["field"] == "hour_bands"
        # nothing was published: the version is still an editable draft
        fetched = await client.get(
            f"/v1/attendance-policies/{policy['id']}/versions/{draft['id']}", headers=headers
        )
        assert fetched.json()["data"]["status"] == "DRAFT"
    finally:
        await _cleanup_attendance(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_a_draft_can_be_saved_incomplete_and_completed_later(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        policy = await _create_policy(client, headers)
        draft = await _draft(client, headers, policy["id"], hour_bands=BAD["gap_240_299"][0])
        assert len(draft["hour_bands"]) == 2
        fixed = await client.patch(
            f"/v1/attendance-policies/{policy['id']}/versions/{draft['id']}",
            headers={**headers, "If-Match": str(draft["version"])},
            json={"hour_bands": GOOD},
        )
        assert fixed.status_code == 200, fixed.text
        published = await _publish(client, headers, policy["id"], fixed.json()["data"])
        assert published.status_code == 200, published.text
        assert published.json()["data"]["status"] == "PUBLISHED"
    finally:
        await _cleanup_attendance(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.parametrize(
    "bands",
    [
        [_band(0, None, "PRESENT")],
        GOOD,
        [_band(0, 0, "ABSENT"), _band(1, 239, "ABSENT"), _band(240, None, "PRESENT")],
    ],
)
async def test_contiguous_bands_publish(
    client: AsyncClient, seeded_plan_catalogue: None, bands: list[dict[str, Any]]
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        policy = await _create_policy(client, headers)
        draft = await _draft(client, headers, policy["id"], hour_bands=bands)
        published = await _publish(client, headers, policy["id"], draft)
        assert published.status_code == 200, published.text
    finally:
        await _cleanup_attendance(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_late_and_early_mark_bands_may_leave_gaps(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The completeness rule is for worked-hour bands only: a gap in a mark band means no mark."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        policy = await _create_policy(client, headers)
        draft = await _draft(
            client,
            headers,
            policy["id"],
            hour_bands=GOOD,
            late_bands=[
                {"min_minutes": 5, "max_minutes": 20, "classification": "LATE"},
                {"min_minutes": 40, "max_minutes": 59, "classification": "LATE"},
            ],
            early_departure_bands=[
                {"min_minutes": 30, "max_minutes": 45, "classification": "EARLY_DEPARTURE"}
            ],
        )
        published = await _publish(client, headers, policy["id"], draft)
        assert published.status_code == 200, published.text
    finally:
        await _cleanup_attendance(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_the_one_call_setup_refuses_gapped_bands_when_it_publishes(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        refused = await client.post(
            "/v1/attendance-policies/setup",
            headers=headers,
            json={
                "name": "Gapped setup",
                "publish": True,
                "rules": {"effective_from": "2026-01-01", "hour_bands": BAD["gap_240_299"][0]},
            },
        )
        assert refused.status_code == 422, refused.text
        assert refused.json()["error"]["code"] == "INVALID_POLICY_BAND"
        accepted = await client.post(
            "/v1/attendance-policies/setup",
            headers=headers,
            json={
                "name": "Good setup",
                "publish": True,
                "rules": {"effective_from": "2026-01-01", "hour_bands": GOOD},
            },
        )
        assert accepted.status_code == 201, accepted.text
    finally:
        await _cleanup_attendance(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.parametrize(
    "bands",
    [
        [_band(0, 239, "ABSENT"), _band(240, None, "HALF_DAY")],
        [_band(0, None, "HALF_DAY")],
        [_band(0, None, "ABSENT")],
    ],
)
async def test_p05_publication_requires_a_present_band(
    client: AsyncClient, seeded_plan_catalogue: None, bands: list[dict[str, Any]]
) -> None:
    """P-05: the lowest PRESENT band's start is the full-day length shorter shifts scale against;
    contiguous bands without one are refused (nothing is guessed)."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        policy = await _create_policy(client, headers)
        draft = await _draft(client, headers, policy["id"], hour_bands=bands)
        refused = await _publish(client, headers, policy["id"], draft)
        assert refused.status_code == 422, refused.text
        error = refused.json()["error"]
        assert error["code"] == "INVALID_POLICY_BAND"
        assert "PRESENT" in error["details"][0]["message"]
        assert error["details"][0]["field"] == "hour_bands"
    finally:
        await _cleanup_attendance(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_p05_the_setup_endpoint_refuses_a_version_without_a_present_band(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        refused = await client.post(
            "/v1/attendance-policies/setup",
            headers=headers,
            json={
                "name": "No present band",
                "publish": True,
                "rules": {
                    "effective_from": "2026-01-01",
                    "hour_bands": [_band(0, 239, "ABSENT"), _band(240, None, "HALF_DAY")],
                },
            },
        )
        assert refused.status_code == 422, refused.text
        assert "PRESENT" in refused.json()["error"]["details"][0]["message"]
    finally:
        await _cleanup_attendance(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
