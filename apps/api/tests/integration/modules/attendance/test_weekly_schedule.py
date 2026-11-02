"""Integration tests for the weekly operational schedule and shift-swap requests
(`/v1/rosters/weekly-schedule`, `/v1/rosters/swap-requests`)."""

from datetime import date, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.auth.test_employee_jwt_linkage import _PASSWORD, _link_user_to_employee
from tests.integration.modules.attendance.test_attendance_day import (
    _build_wired_employee,
    _cleanup_attendance_day,
    _register_tenant,
)
from tests.integration.modules.attendance.test_shift_roster import _create_night_shift
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.core.db.session import get_session_factory
from hrms.modules.attendance.permissions import ATTENDANCE_VIEW

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


async def _employee_headers(
    client: AsyncClient, company_id: str, employee_id: str
) -> tuple[dict[str, str], UUID]:
    email = f"swap-{uuid4().hex[:10]}@example.com"
    user_id = await _link_user_to_employee(
        company_id=UUID(company_id),
        employee_id=UUID(employee_id),
        email=email,
        data_scope="SELF",
        permission_codes=(ATTENDANCE_VIEW,),
    )
    login = await client.post(
        "/v1/auth/login",
        json={"email": email, "password": _PASSWORD, "company_id": company_id},
    )
    assert login.status_code == 200, login.text
    return (
        {
            "Authorization": f"Bearer {login.json()['data']['access_token']}",
            "X-Company-Id": company_id,
        },
        user_id,
    )


async def _second_employee(
    client: AsyncClient, headers: dict[str, str], wired: dict[str, Any]
) -> str:
    """A colleague in the same branch and department as the wired employee."""
    employee = (
        await client.post("/v1/employees", headers=headers, json={"first_name": "Ben"})
    ).json()["data"]
    branch = wired["branch"]
    department = (await client.get("/v1/departments", headers=headers)).json()["data"][0]
    designation = (await client.get("/v1/designations", headers=headers)).json()["data"][0]
    employment = await client.post(
        f"/v1/employees/{employee['id']}/employments",
        headers=headers,
        json={"legal_entity_id": branch["legal_entity_id"], "joining_date": "2026-01-01"},
    )
    assert employment.status_code == 201, employment.text
    assignment = await client.post(
        f"/v1/employees/{employee['id']}/assignments",
        headers=headers,
        json={
            "effective_from": "2026-01-01",
            "change_type": "INITIAL",
            "branch_id": branch["id"],
            "department_id": department["id"],
            "designation_id": designation["id"],
        },
    )
    assert assignment.status_code == 201, assignment.text
    return str(employee["id"])


async def test_employee_swap_needs_consent_before_a_manager_can_approve(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    link_users: list[UUID] = []
    try:
        wired = await _build_wired_employee(client, headers)
        a_id = wired["employee"]["id"]
        b_id = await _second_employee(client, headers, wired)
        night = await _create_night_shift(client, headers)
        day = (date.today() + timedelta(days=30)).isoformat()
        await _publish_roster(client, headers, a_id, day, wired["shift"]["id"])
        await _publish_roster(client, headers, b_id, day, night["id"])
        a_headers, a_user = await _employee_headers(client, str(company_id), a_id)
        b_headers, b_user = await _employee_headers(client, str(company_id), b_id)
        link_users += [a_user, b_user]

        candidates = await client.get(
            "/v1/rosters/swap-candidates", headers=a_headers, params={"swap_date": day}
        )
        assert candidates.status_code == 200, candidates.text
        assert [c["employee_id"] for c in candidates.json()["data"]] == [b_id]

        created = await client.post(
            "/v1/rosters/swap-requests/mine",
            headers=a_headers,
            json={"counterpart_employee_id": b_id, "swap_date": day, "reason": "Dentist"},
        )
        assert created.status_code == 201, created.text
        swap = created.json()["data"]
        assert swap["status"] == "PENDING"
        assert swap["counterpart_consented"] is False
        assert swap["requester"]["employee_id"] == a_id

        again = await client.post(
            "/v1/rosters/swap-requests/mine",
            headers=a_headers,
            json={"counterpart_employee_id": b_id, "swap_date": day},
        )
        assert again.status_code == 409, again.text

        # A manager cannot approve until the colleague has agreed.
        early = await client.post(
            f"/v1/rosters/swap-requests/{swap['id']}/approve", headers=headers, json={}
        )
        assert early.status_code == 409, early.text

        # Only the colleague can consent: the requester gets a 404.
        wrong = await client.post(
            f"/v1/rosters/swap-requests/{swap['id']}/consent", headers=a_headers
        )
        assert wrong.status_code == 404, wrong.text
        agreed = await client.post(
            f"/v1/rosters/swap-requests/{swap['id']}/consent", headers=b_headers
        )
        assert agreed.status_code == 200, agreed.text
        assert agreed.json()["data"]["counterpart_consented"] is True

        approved = await client.post(
            f"/v1/rosters/swap-requests/{swap['id']}/approve", headers=headers, json={}
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["data"]["status"] == "APPROVED"
    finally:
        await _drop_link_users(link_users)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_requester_can_withdraw_and_outsiders_cannot_touch_a_swap(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    link_users: list[UUID] = []
    try:
        wired = await _build_wired_employee(client, headers)
        a_id = wired["employee"]["id"]
        b_id = await _second_employee(client, headers, wired)
        night = await _create_night_shift(client, headers)
        day = (date.today() + timedelta(days=31)).isoformat()
        await _publish_roster(client, headers, a_id, day, wired["shift"]["id"])
        await _publish_roster(client, headers, b_id, day, night["id"])
        a_headers, a_user = await _employee_headers(client, str(company_id), a_id)
        link_users.append(a_user)

        created = await client.post(
            "/v1/rosters/swap-requests/mine",
            headers=a_headers,
            json={"counterpart_employee_id": b_id, "swap_date": day},
        )
        assert created.status_code == 201, created.text
        swap_id = created.json()["data"]["id"]

        # The company account has no employee record, so it is neither party.
        outsider = await client.post(
            f"/v1/rosters/swap-requests/{swap_id}/withdraw", headers=headers
        )
        assert outsider.status_code == 404, outsider.text

        withdrawn = await client.post(
            f"/v1/rosters/swap-requests/{swap_id}/withdraw", headers=a_headers
        )
        assert withdrawn.status_code == 200, withdrawn.text
        assert withdrawn.json()["data"]["status"] == "DECLINED"
        assert withdrawn.json()["data"]["decision_note"] == "Withdrawn by the requester"

        past = await client.post(
            "/v1/rosters/swap-requests/mine",
            headers=a_headers,
            json={"counterpart_employee_id": b_id, "swap_date": "2020-01-06"},
        )
        assert past.status_code == 422, past.text
    finally:
        await _drop_link_users(link_users)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def _drop_link_users(user_ids: list[UUID]) -> None:
    async with get_session_factory()() as session:
        for uid in user_ids:
            for table in ("refresh_token", "session"):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE user_id = :u"), {"u": str(uid)}
                )
        await session.commit()
