"""Integration tests for the weekly operational schedule and shift-swap requests
(`/v1/rosters/weekly-schedule`, `/v1/rosters/swap-requests`)."""

import pytest
from httpx import AsyncClient
from tests.integration.modules.attendance.test_attendance_day import (
    _build_wired_employee,
    _cleanup_attendance_day,
    _register_tenant,
)
from tests.integration.modules.attendance.test_shift_roster import _create_night_shift
from tests.integration.modules.organisation.test_registration_flow import _cleanup

pytestmark = pytest.mark.asyncio


async def _publish_roster(
    client: AsyncClient, headers: dict[str, str], employee_id: str, day: str, shift_id: str
) -> None:
    created = await client.post(
        "/v1/rosters",
        headers=headers,
        json={"employee_id": employee_id, "roster_date": day, "shift_id": shift_id},
    )
    assert created.status_code == 201, created.text
    published = await client.post(
        f"/v1/rosters/{created.json()['data']['id']}/publish",
        headers={**headers, "If-Match": "1"},
        json={},
    )
    assert published.status_code == 200, published.text


async def test_weekly_schedule_counts_published_roster_and_targets(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        night = await _create_night_shift(client, headers)
        # 2026-08-10 is a Monday; the week is Mon 10 - Sun 16 Aug.
        await _publish_roster(client, headers, employee_id, "2026-08-12", night["id"])

        response = await client.get(
            "/v1/rosters/weekly-schedule", headers=headers, params={"week_start": "2026-08-13"}
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["week_start"] == "2026-08-10"  # any day snaps to its Monday
        assert data["week_end"] == "2026-08-16"
        assert len(data["days"]) == 7
        shift = next(s for s in data["shifts"] if s["id"] == night["id"])
        assert [c["count"] for c in shift["cells"]] == [0, 0, 1, 0, 0, 0, 0]
        assert shift["start_time"] == "22:00:00"
        assert shift["daily_hours"] == 8.0
        assert data["totals"]["rostered_staff"] == 1
        assert data["totals"]["allocated_hours"] == 8.0
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_draft_roster_is_not_in_the_schedule(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        night = await _create_night_shift(client, headers)
        created = await client.post(
            "/v1/rosters",
            headers=headers,
            json={
                "employee_id": wired["employee"]["id"],
                "roster_date": "2026-08-12",
                "shift_id": night["id"],
            },
        )
        assert created.status_code == 201, created.text

        response = await client.get(
            "/v1/rosters/weekly-schedule", headers=headers, params={"week_start": "2026-08-10"}
        )
        shift = next(s for s in response.json()["data"]["shifts"] if s["id"] == night["id"])
        assert sum(c["count"] for c in shift["cells"]) == 0
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_swap_with_oneself_is_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        response = await client.post(
            "/v1/rosters/swap-requests",
            headers=headers,
            json={
                "requester_employee_id": employee_id,
                "counterpart_employee_id": employee_id,
                "swap_date": "2026-08-12",
            },
        )
        assert response.status_code == 422, response.text
        listed = await client.get("/v1/rosters/swap-requests", headers=headers)
        assert listed.status_code == 200
        assert listed.json()["data"] == []
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
