"""Integration tests for API-01 §6 pagination on the Workforce Calendar surface:
`/v1/policy-assignments`, `/v1/work-calendars/{id}/exceptions`,
`/v1/holiday-calendars/{id}/holidays`.

Reuses `test_workforce_calendar.py`'s exact fixture helpers.
"""

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from hrms.core.db.session import get_session_factory

from .test_registration_flow import _cleanup
from .test_workforce_calendar import (
    _cleanup_workforce_calendar,
    _create_holiday_calendar,
    _create_work_calendar,
    _register_tenant,
)

pytestmark = pytest.mark.asyncio


async def _create_branch(
    client: AsyncClient, headers: dict[str, str], *, legal_entity_id: str, name: str
) -> dict[str, Any]:
    response = await client.post(
        "/v1/branches", headers=headers, json={"legal_entity_id": legal_entity_id, "name": name}
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _cleanup_branches_and_legal_entities(*, company_id: UUID) -> None:
    """`_cleanup_workforce_calendar` doesn't know about `branch`/`legal_entity` — this test
    file is the only one on this surface that creates them, as `policy_assignment` BRANCH-scope
    fixtures."""
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("DELETE FROM branch WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.execute(
            text("DELETE FROM legal_entity WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.commit()


# ---------------------------------------------------------------------------
# /v1/policy-assignments
# ---------------------------------------------------------------------------


async def test_policy_assignments_paginate_and_filter_by_kind(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        legal_entity = (
            await client.post("/v1/legal-entities", headers=headers, json={"name": "Acme LE"})
        ).json()["data"]
        work_calendar = await _create_work_calendar(client, headers)

        assignment_ids: set[str] = set()
        for i in range(7):
            branch = await _create_branch(
                client, headers, legal_entity_id=legal_entity["id"], name=f"Branch {i}"
            )
            response = await client.post(
                "/v1/policy-assignments",
                headers=headers,
                json={
                    "policy_kind": "WORK_CALENDAR",
                    "policy_id": work_calendar["id"],
                    "scope_type": "BRANCH",
                    "scope_id": branch["id"],
                    "effective_from": "2026-01-01",
                },
            )
            assert response.status_code == 201, response.text
            assignment_ids.add(response.json()["data"]["id"])

        response = await client.get(
            "/v1/policy-assignments",
            headers=headers,
            params={"policy_kind": "WORK_CALENDAR", "per_page": 3},
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["data"]) == 3
        assert body["pagination"]["total"] == 7
        assert body["pagination"]["total_pages"] == 3

        seen_ids: set[str] = set()
        for page in (1, 2, 3):
            page_resp = await client.get(
                "/v1/policy-assignments",
                headers=headers,
                params={"policy_kind": "WORK_CALENDAR", "page": page, "per_page": 3},
            )
            seen_ids.update(row["id"] for row in page_resp.json()["data"])
        assert seen_ids == assignment_ids
    finally:
        await _cleanup_workforce_calendar(company_id=company_id)
        await _cleanup_branches_and_legal_entities(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_policy_assignments_invalid_pagination_params_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.get("/v1/policy-assignments", headers=headers, params={"page": 0})
        assert response.status_code == 422
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


# ---------------------------------------------------------------------------
# /v1/work-calendars/{id}/exceptions
# ---------------------------------------------------------------------------


async def test_calendar_exceptions_paginate_ordered_by_date(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        work_calendar = await _create_work_calendar(client, headers)

        created_dates = []
        for day in range(1, 8):
            date = f"2026-03-{day:02d}"
            response = await client.post(
                f"/v1/work-calendars/{work_calendar['id']}/exceptions",
                headers=headers,
                json={
                    "exception_date": date,
                    "exception_type": "SPECIAL_WORKING",
                    "reason": "Test",
                },
            )
            assert response.status_code == 201, response.text
            created_dates.append(date)

        response = await client.get(
            f"/v1/work-calendars/{work_calendar['id']}/exceptions",
            headers=headers,
            params={"per_page": 3},
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["data"]) == 3
        assert body["pagination"]["total"] == 7
        assert body["pagination"]["total_pages"] == 3
        # Ascending by date, deterministic — page 1 is the 3 earliest dates.
        assert [row["exception_date"] for row in body["data"]] == created_dates[:3]

        page2 = await client.get(
            f"/v1/work-calendars/{work_calendar['id']}/exceptions",
            headers=headers,
            params={"per_page": 3, "page": 2},
        )
        assert [row["exception_date"] for row in page2.json()["data"]] == created_dates[3:6]
    finally:
        await _cleanup_workforce_calendar(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_calendar_exceptions_cross_calendar_isolation(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        calendar_a = await _create_work_calendar(client, headers, name="Calendar A")
        calendar_b = await _create_work_calendar(client, headers, name="Calendar B")

        for calendar, date in ((calendar_a, "2026-04-01"), (calendar_b, "2026-04-02")):
            response = await client.post(
                f"/v1/work-calendars/{calendar['id']}/exceptions",
                headers=headers,
                json={"exception_date": date, "exception_type": "SPECIAL_WORKING"},
            )
            assert response.status_code == 201, response.text

        response_a = await client.get(
            f"/v1/work-calendars/{calendar_a['id']}/exceptions", headers=headers
        )
        assert response_a.json()["pagination"]["total"] == 1
        assert response_a.json()["data"][0]["exception_date"] == "2026-04-01"
    finally:
        await _cleanup_workforce_calendar(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# ---------------------------------------------------------------------------
# /v1/holiday-calendars/{id}/holidays
# ---------------------------------------------------------------------------


async def test_holidays_paginate_within_year_filter(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        calendar = await _create_holiday_calendar(client, headers)

        for day in range(1, 6):
            response = await client.post(
                f"/v1/holiday-calendars/{calendar['id']}/holidays",
                headers=headers,
                json={"date": f"2026-01-{day:02d}", "name": f"Holiday {day}"},
            )
            assert response.status_code == 201, response.text
        # One holiday in a different year — must not appear when `year=2026` is passed, and
        # pagination must still work even without the filter (API-01 §6: `year` optional is not
        # itself sufficient protection).
        other_year = await client.post(
            f"/v1/holiday-calendars/{calendar['id']}/holidays",
            headers=headers,
            json={"date": "2027-01-01", "name": "Next year"},
        )
        assert other_year.status_code == 201, other_year.text

        filtered = await client.get(
            f"/v1/holiday-calendars/{calendar['id']}/holidays",
            headers=headers,
            params={"year": 2026, "per_page": 3},
        )
        assert filtered.status_code == 200
        filtered_body = filtered.json()
        assert len(filtered_body["data"]) == 3
        assert filtered_body["pagination"]["total"] == 5
        assert filtered_body["pagination"]["total_pages"] == 2

        unfiltered = await client.get(
            f"/v1/holiday-calendars/{calendar['id']}/holidays",
            headers=headers,
            params={"per_page": 3},
        )
        assert unfiltered.json()["pagination"]["total"] == 6
    finally:
        await _cleanup_workforce_calendar(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_holidays_invalid_pagination_params_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        calendar = await _create_holiday_calendar(client, headers)
        response = await client.get(
            f"/v1/holiday-calendars/{calendar['id']}/holidays",
            headers=headers,
            params={"per_page": 500},
        )
        assert response.status_code == 422
    finally:
        await _cleanup_workforce_calendar(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
