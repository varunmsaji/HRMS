"""Integration tests for payroll readiness step 3 — attendance periods per legal entity
(`docs/audits/PAYROLL_BUSINESS_DECISIONS.md` decision 14) with a calendar-month default
(decision 18).

Two employees in two legal entities share one tenant (`_add_reportee_employee` gives the second
employee its own legal entity). Closing one entity's period must validate, summarise, lock and
reopen only that entity's employee-dates; a mid-period transfer splits the employee between the
two entities' periods."""

from datetime import date
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.test_attendance_day import (
    _build_wired_employee,
    _cleanup_attendance_day,
    _register_tenant,
)
from tests.integration.modules.attendance.test_attendance_period import (
    _DAY,
    _cleanup_attendance_period,
    _create_period,
    _first_legal_entity_id,
    _full_calculate,
)
from tests.integration.modules.attendance.test_attendance_security import (
    _add_reportee_employee,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.attendance import tasks as attendance_tasks

pytestmark = pytest.mark.asyncio


async def _employment_legal_entity_id(
    client: AsyncClient, headers: dict[str, str], employee_id: str
) -> str:
    response = await client.get(f"/v1/employees/{employee_id}/employments", headers=headers)
    assert response.status_code == 200, response.text
    return str(response.json()["data"][0]["legal_entity_id"])


async def _day(client: AsyncClient, headers: dict[str, str], employee_id: str, day: str) -> Any:
    response = await client.get(
        "/v1/attendance/days",
        headers=headers,
        params={"employee_id": employee_id, "date_from": day, "date_to": day},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"][0]


async def _finalize(
    client: AsyncClient, headers: dict[str, str], period_id: str, version: int
) -> None:
    response = await client.post(
        f"/v1/attendance-periods/{period_id}/finalize",
        headers={**headers, "If-Match": str(version)},
        json={},
    )
    assert response.status_code == 200, response.text


async def test_periods_are_per_legal_entity_with_a_calendar_month_default(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        entity_a = await _first_legal_entity_id(client, headers)
        created_b = await client.post(
            "/v1/legal-entities", headers=headers, json={"name": "Second LE"}
        )
        entity_b = created_b.json()["data"]["id"]

        # Decision 18 — `month` expands to the full calendar month.
        september_a = await client.post(
            "/v1/attendance-periods",
            headers=headers,
            json={"legal_entity_id": entity_a, "month": "2026-09"},
        )
        assert september_a.status_code == 201, september_a.text
        data = september_a.json()["data"]
        assert (data["period_start"], data["period_end"]) == ("2026-09-01", "2026-09-30")
        assert data["label"] == "September 2026"
        assert data["legal_entity_id"] == entity_a

        # Decision 14 — another entity runs its own cycle over the same dates...
        september_b = await client.post(
            "/v1/attendance-periods",
            headers=headers,
            json={"legal_entity_id": entity_b, "month": "2026-09"},
        )
        assert september_b.status_code == 201, september_b.text

        # ...but one entity cannot overlap itself.
        overlap = await client.post(
            "/v1/attendance-periods",
            headers=headers,
            json={
                "legal_entity_id": entity_a,
                "period_start": "2026-09-15",
                "period_end": "2026-10-14",
            },
        )
        assert overlap.status_code == 409, overlap.text
        assert overlap.json()["error"]["code"] == "ATTENDANCE_PERIOD_OVERLAP"

        listed = await client.get(
            "/v1/attendance-periods", headers=headers, params={"legal_entity_id": entity_b}
        )
        assert [p["legal_entity_id"] for p in listed.json()["data"]] == [entity_b]

        unknown = await client.post(
            "/v1/attendance-periods",
            headers=headers,
            json={"legal_entity_id": "00000000-0000-4000-8000-000000000000", "month": "2026-10"},
        )
        assert unknown.status_code == 422, unknown.text
        assert unknown.json()["error"]["code"] == "ATTENDANCE_PERIOD_LEGAL_ENTITY_INVALID"
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_closing_one_entity_leaves_the_other_open(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_a = wired["employee"]["id"]
        employee_b = (
            await _add_reportee_employee(
                client, headers, wired=wired, first_name="Bina", reporting_manager_id=None
            )
        )["id"]
        entity_a = await _employment_legal_entity_id(client, headers, employee_a)
        entity_b = await _employment_legal_entity_id(client, headers, employee_b)
        assert entity_a != entity_b

        await _full_calculate(client, headers, employee_id=employee_a)
        day_b = await _full_calculate(client, headers, employee_id=employee_b)
        # A blocker in entity B must not hold up entity A's close.
        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, str(company_id))
            await session.execute(
                text("UPDATE attendance_day SET attendance_status = 'CONFIG_ERROR' WHERE id = :id"),
                {"id": day_b["id"]},
            )
            await session.commit()

        period_a = await _create_period(client, headers, legal_entity_id=entity_a)
        validation = await client.post(
            f"/v1/attendance-periods/{period_a['id']}/validate", headers=headers
        )
        assert validation.json()["data"]["status"] == "READY", validation.text
        await _finalize(client, headers, period_a["id"], 1)

        summary = await client.get(
            f"/v1/attendance-periods/{period_a['id']}/summary", headers=headers
        )
        assert [r["employee_id"] for r in summary.json()["data"]] == [employee_a]
        assert (await _day(client, headers, employee_a, _DAY))["is_locked"] is True
        assert (await _day(client, headers, employee_b, _DAY))["is_locked"] is False

        # Entity A's employee-date is closed; entity B's same date is not.
        refused = await client.post(
            "/v1/attendance/days/calculate",
            headers=headers,
            params={"employee_id": employee_a, "date": _DAY},
        )
        assert refused.status_code == 409, refused.text
        assert refused.json()["error"]["code"] == "ATTENDANCE_PERIOD_CLOSED"
        recalculated_b = await client.post(
            "/v1/attendance/days/calculate",
            headers=headers,
            params={"employee_id": employee_b, "date": _DAY},
        )
        assert recalculated_b.status_code == 200, recalculated_b.text

        period_b = await _create_period(client, headers, legal_entity_id=entity_b)
        await _finalize(client, headers, period_b["id"], 1)
        assert (await _day(client, headers, employee_b, _DAY))["is_locked"] is True

        # Reopening A unlocks only A's days — B's close stands.
        reopened = await client.post(
            f"/v1/attendance-periods/{period_a['id']}/reopen",
            headers={**headers, "If-Match": "2"},
            json={"reason": "correcting entity A"},
        )
        assert reopened.status_code == 200, reopened.text
        assert (await _day(client, headers, employee_a, _DAY))["is_locked"] is False
        assert (await _day(client, headers, employee_b, _DAY))["is_locked"] is True
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_mid_period_transfer_splits_the_employee_between_entities(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        entity_a = await _employment_legal_entity_id(client, headers, employee_id)
        entity_b = (
            await client.post("/v1/legal-entities", headers=headers, json={"name": "Second LE"})
        ).json()["data"]["id"]

        # Transfer: employment in A ends 2026-08-10, a new one in B starts 2026-08-11.
        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, str(company_id))
            await session.execute(
                text(
                    "UPDATE employment SET last_working_day = '2026-08-10', status = 'TERMINATED' "
                    "WHERE employee_id = :eid"
                ),
                {"eid": employee_id},
            )
            await session.commit()
        transferred = await client.post(
            f"/v1/employees/{employee_id}/employments",
            headers=headers,
            json={"legal_entity_id": entity_b, "joining_date": "2026-08-11"},
        )
        assert transferred.status_code == 201, transferred.text

        await _full_calculate(client, headers, employee_id=employee_id, day="2026-08-10")
        await _full_calculate(client, headers, employee_id=employee_id, day="2026-08-11")

        period_a = await _create_period(
            client,
            headers,
            period_start="2026-08-10",
            period_end="2026-08-11",
            legal_entity_id=entity_a,
        )
        await _finalize(client, headers, period_a["id"], 1)

        summary = await client.get(
            f"/v1/attendance-periods/{period_a['id']}/summary", headers=headers
        )
        (row,) = summary.json()["data"]
        assert row["employee_id"] == employee_id
        assert row["payable_days"] == "1.00"
        assert row["present_days"] == "1.00"
        assert row["not_employed_days"] == "1.00"

        assert (await _day(client, headers, employee_id, "2026-08-10"))["is_locked"] is True
        assert (await _day(client, headers, employee_id, "2026-08-11"))["is_locked"] is False

        # The B-owned day stays open; the A-owned day is closed.
        open_day = await client.post(
            "/v1/attendance/days/calculate",
            headers=headers,
            params={"employee_id": employee_id, "date": "2026-08-11"},
        )
        assert open_day.status_code == 200, open_day.text
        closed_day = await client.post(
            "/v1/attendance/days/calculate",
            headers=headers,
            params={"employee_id": employee_id, "date": "2026-08-10"},
        )
        assert closed_day.status_code == 409, closed_day.text
        assert closed_day.json()["error"]["code"] == "ATTENDANCE_PERIOD_CLOSED"
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_range_calculation_can_be_narrowed_to_one_legal_entity(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_a = wired["employee"]["id"]
        employee_b = (
            await _add_reportee_employee(
                client, headers, wired=wired, first_name="Bina", reporting_manager_id=None
            )
        )["id"]
        entity_a = await _employment_legal_entity_id(client, headers, employee_a)

        counts = await attendance_tasks._calculate_range_async(
            company_id, date(2026, 8, 10), date(2026, 8, 10), None, None, UUID(entity_a)
        )
        assert counts == {"employees": 1, "calculated": 1, "skipped_locked": 0, "failed": 0}
        assert (await _day(client, headers, employee_a, _DAY))["attendance_date"] == _DAY
        days_b = await client.get(
            "/v1/attendance/days",
            headers=headers,
            params={"employee_id": employee_b, "date_from": _DAY, "date_to": _DAY},
        )
        assert days_b.json()["data"] == []
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
