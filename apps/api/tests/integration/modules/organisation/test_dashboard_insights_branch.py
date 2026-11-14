"""Integration tests for the `branch_id` filter on `GET /v1/dashboards/company/insights`.

Without `branch_id` the cards are company-wide; with it, headcount, yesterday's attendance and
birthdays only count the people placed in that branch. Builds two branches on a fresh tenant
using the attendance-overview suite's helpers.
"""

from datetime import date, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.test_attendance_day import _cleanup_attendance_day
from tests.integration.modules.attendance.test_company_attendance_overview import (
    TZ,
    _add_day,
    _employee,
    _setup,
)

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.shared.business_time import business_today

pytestmark = pytest.mark.asyncio

URL = "/v1/dashboards/company/insights"


async def test_branch_filter_narrows_every_card(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    ctx = await _setup(client)
    headers, company_id = ctx["headers"], ctx["company_id"]
    today = business_today(TZ)
    yesterday = today - timedelta(days=1)
    try:
        other = (
            await client.post(
                "/v1/branches",
                headers=headers,
                json={"legal_entity_id": ctx["le"], "name": "Annex", "timezone": TZ},
            )
        ).json()["data"]["id"]

        async def emp(name: str, branch: str, born: date | None = None) -> str:
            employee_id = await _employee(
                client,
                headers,
                name=name,
                legal_entity_id=ctx["le"],
                department_id=ctx["eng"],
                branch_id=branch,
                designation_id=ctx["desig"],
            )
            if born is not None:
                async with get_session_factory()() as session:
                    await set_rls_company_id(session, str(company_id))
                    await session.execute(
                        text("UPDATE employee SET date_of_birth = :dob WHERE id = :id"),
                        {"dob": born, "id": employee_id},
                    )
                    await session.commit()
            return employee_id

        soon = date(1990, (today + timedelta(days=3)).month, (today + timedelta(days=3)).day)
        hq_a = await emp("HqA", ctx["branch"], born=soon)
        hq_b = await emp("HqB", ctx["branch"])
        annex = await emp("AnnexA", other, born=soon)
        for employee_id in (hq_a, hq_b, annex):
            await _add_day(company_id, employee_id, yesterday, "PRESENT")

        async def insights(branch: str | None = None) -> dict[str, Any]:
            response = await client.get(
                URL, headers=headers, params={"branch_id": branch} if branch else None
            )
            assert response.status_code == 200, response.text
            return response.json()["data"]

        everyone, hq, annex_only = (
            await insights(),
            await insights(ctx["branch"]),
            await insights(other),
        )

        assert everyone["headcount_trend"][-1]["headcount"] == 3
        assert hq["headcount_trend"][-1]["headcount"] == 2
        assert annex_only["headcount_trend"][-1]["headcount"] == 1

        assert everyone["kpi_comparison"]["yesterday_present"] == 3
        assert hq["kpi_comparison"]["yesterday_present"] == 2
        assert annex_only["kpi_comparison"]["yesterday_present"] == 1

        assert {b["name"] for b in everyone["upcoming_birthdays"]} == {"HqA", "AnnexA"}
        assert [b["name"] for b in hq["upcoming_birthdays"]] == ["HqA"]
        assert [b["name"] for b in annex_only["upcoming_birthdays"]] == ["AnnexA"]

        # Activity rows name an employee, so each one lands in that employee's branch only.
        hq_subjects = {a["subject"] for a in hq["recent_activities"]}
        assert "AnnexA" not in hq_subjects
    finally:
        await _cleanup_attendance_day(company_id=company_id)


async def test_unknown_branch_returns_empty_figures_not_an_error(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    ctx = await _setup(client)
    headers, company_id = ctx["headers"], ctx["company_id"]
    try:
        await _employee(
            client,
            headers,
            name="Solo",
            legal_entity_id=ctx["le"],
            department_id=ctx["eng"],
            branch_id=ctx["branch"],
            designation_id=ctx["desig"],
        )
        response = await client.get(
            URL, headers=headers, params={"branch_id": "00000000-0000-0000-0000-000000000000"}
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["headcount_trend"][-1]["headcount"] == 0
        assert data["upcoming_birthdays"] == []
    finally:
        await _cleanup_attendance_day(company_id=company_id)
