"""Invariant A — one resolved schedule per employee-date, used everywhere (SH-07, SH-16)."""

from typing import Any

import pytest
from httpx import AsyncClient
from tests.integration.modules.attendance.test_attendance_day import (
    _build_wired_employee,
    _cleanup_attendance_day,
    _punch,
    _register_tenant,
)
from tests.integration.modules.attendance.test_shift_roster import _create_night_shift
from tests.integration.modules.organisation.test_registration_flow import _cleanup

pytestmark = pytest.mark.asyncio


async def _published_policy(
    client: AsyncClient, headers: dict[str, str], *, name: str, grace_in: int
) -> dict[str, Any]:
    policy = (
        await client.post("/v1/attendance-policies", headers=headers, json={"name": name})
    ).json()["data"]
    draft = (
        await client.post(
            f"/v1/attendance-policies/{policy['id']}/versions",
            headers=headers,
            json={
                "effective_from": "2026-01-01",
                "grace_in_minutes": grace_in,
                "hour_bands": [
                    {"min_minutes": 0, "max_minutes": 239, "result_status": "ABSENT"},
                    {"min_minutes": 240, "max_minutes": None, "result_status": "PRESENT"},
                ],
            },
        )
    ).json()["data"]
    published = await client.post(
        f"/v1/attendance-policies/{policy['id']}/versions/{draft['id']}/publish",
        headers={**headers, "If-Match": "1"},
        json={},
    )
    assert published.status_code == 200, published.text
    return {"policy": policy, "version_id": draft["id"]}


async def _roster(
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


async def test_rostered_shift_controls_shift_scoped_policy(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """SH-07 — a policy assigned to the night shift must apply on a day the employee is
    rostered onto the night shift, even though their assignment names the day shift."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        night = await _create_night_shift(client, headers)
        night_policy = await _published_policy(client, headers, name="Night rules", grace_in=45)
        scoped = await client.post(
            "/v1/policy-assignments",
            headers=headers,
            json={
                "policy_kind": "ATTENDANCE_POLICY",
                "policy_id": night_policy["policy"]["id"],
                "scope_type": "SHIFT",
                "scope_id": night["id"],
                "effective_from": "2026-01-01",
            },
        )
        assert scoped.status_code == 201, scoped.text
        await _roster(client, headers, employee_id, "2026-08-10", night["id"])

        # 30 minutes late: inside the night policy's 45-minute grace, outside the company's 0.
        await _punch(client, headers, employee_id=employee_id, hour=22, minute=30, direction="IN")
        await _punch(
            client,
            headers,
            employee_id=employee_id,
            hour=6,
            minute=0,
            direction="OUT",
            day="2026-08-11",
        )
        response = await client.post(
            "/v1/attendance/days/calculate",
            headers=headers,
            params={"employee_id": employee_id, "date": "2026-08-10"},
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["shift_id"] == night["id"]
        assert data["attendance_policy_version_id"] == night_policy["version_id"]
        assert data["late_minutes"] == 0

        # The next day has no roster row: the day shift and the company policy apply again.
        other = await client.post(
            "/v1/attendance/days/calculate",
            headers=headers,
            params={"employee_id": employee_id, "date": "2026-08-12"},
        )
        assert other.status_code == 200, other.text
        assert other.json()["data"]["shift_id"] == wired["shift"]["id"]
        assert other.json()["data"]["attendance_policy_version_id"] != night_policy["version_id"]
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
