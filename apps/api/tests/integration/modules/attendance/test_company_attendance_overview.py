"""Integration tests for `GET /v1/dashboards/company/attendance-overview`.

The endpoint only groups the `attendance_day` rows the calculation engine already wrote, so the
rows here are inserted directly with the statuses the engine produces — what is under test is the
population (employment coverage, tenant), the bucket mapping, the not-yet-due time rule for today,
the overlays, department grouping and permissions. Company timezone is Asia/Kolkata (registration
default).
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.test_attendance_day import (
    _cleanup_attendance_day,
    _register_tenant,
)

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.attendance.models import AttendanceDay
from hrms.shared.business_time import business_today

pytestmark = pytest.mark.asyncio

URL = "/v1/dashboards/company/attendance-overview"
TZ = "Asia/Kolkata"


async def _employee(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    name: str,
    legal_entity_id: str,
    department_id: str | None,
    branch_id: str,
    designation_id: str,
    joining_date: str = "2026-01-01",
) -> str:
    employee = (
        await client.post("/v1/employees", headers=headers, json={"first_name": name})
    ).json()["data"]
    response = await client.post(
        f"/v1/employees/{employee['id']}/employments",
        headers=headers,
        json={"legal_entity_id": legal_entity_id, "joining_date": joining_date},
    )
    assert response.status_code == 201, response.text
    if department_id is not None:
        assignment = await client.post(
            f"/v1/employees/{employee['id']}/assignments",
            headers=headers,
            json={
                "effective_from": joining_date,
                "change_type": "INITIAL",
                "branch_id": branch_id,
                "department_id": department_id,
                "designation_id": designation_id,
            },
        )
        assert assignment.status_code == 201, assignment.text
    return str(employee["id"])


async def _add_day(
    company_id: UUID,
    employee_id: str,
    attendance_date: date,
    status: str,
    **fields: Any,
) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        session.add(
            AttendanceDay(
                id=uuid4(),
                company_id=company_id,
                employee_id=UUID(employee_id),
                attendance_date=attendance_date,
                timezone=TZ,
                attendance_status=status,
                calculation_version=1,
                is_locked=False,
                **fields,
            )
        )
        await session.commit()


async def _setup(client: AsyncClient) -> dict[str, Any]:
    headers, company_id, _user = await _register_tenant(client)
    # The default trial plan caps seats at 5; this suite needs a realistic headcount.
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        await session.execute(
            text(
                "UPDATE subscription SET plan_id = (SELECT id FROM plan WHERE code='ENTERPRISE') "
                "WHERE company_id = :cid"
            ),
            {"cid": str(company_id)},
        )
        await session.commit()
    legal_entity = (
        await client.post("/v1/legal-entities", headers=headers, json={"name": "Acme LE"})
    ).json()["data"]
    branch = (
        await client.post(
            "/v1/branches",
            headers=headers,
            json={"legal_entity_id": legal_entity["id"], "name": "HQ", "timezone": TZ},
        )
    ).json()["data"]
    eng = (
        await client.post(
            "/v1/departments",
            headers=headers,
            json={"name": "Engineering", "branch_id": branch["id"]},
        )
    ).json()["data"]
    hr = (
        await client.post(
            "/v1/departments", headers=headers, json={"name": "HR", "branch_id": branch["id"]}
        )
    ).json()["data"]
    designation = (
        await client.post(
            "/v1/designations",
            headers=headers,
            json={"title": "Engineer", "department_id": eng["id"]},
        )
    ).json()["data"]
    return {
        "branch": branch["id"],
        "desig": designation["id"],
        "headers": headers,
        "company_id": company_id,
        "le": legal_entity["id"],
        "eng": eng["id"],
        "hr": hr["id"],
    }


async def test_buckets_overlays_and_departments_for_today(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    ctx = await _setup(client)
    headers, company_id = ctx["headers"], ctx["company_id"]
    today = business_today(TZ)
    now = datetime.now(UTC)
    past, future = now - timedelta(hours=2), now + timedelta(hours=3)
    try:

        async def emp(name: str, dept: str | None, **kw: Any) -> str:
            return await _employee(
                client,
                headers,
                name=name,
                legal_entity_id=ctx["le"],
                department_id=dept,
                branch_id=ctx["branch"],
                designation_id=ctx["desig"],
                **kw,
            )

        present_late = await emp("Late", ctx["eng"])
        absent = await emp("Absent", ctx["eng"])
        not_yet = await emp("NotYet", ctx["hr"])
        half_leave = await emp("HalfLeave", ctx["hr"])
        weekly_off = await emp("WeeklyOff", ctx["eng"])
        await emp("NoRecord", ctx["eng"])  # never gets a row
        in_progress = await emp("InProgress", ctx["eng"])
        missing_out = await emp("MissingOut", ctx["hr"])
        unassigned = await emp("Unassigned", None)
        left = await emp("Left", ctx["eng"])  # employment ended before today

        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, str(company_id))
            await session.execute(
                text(
                    "UPDATE employment SET status='TERMINATED', last_working_day=:d "
                    "WHERE employee_id=:e"
                ),
                {"d": today - timedelta(days=1), "e": left},
            )
            await session.commit()

        first_in = now - timedelta(minutes=90)
        await _add_day(
            company_id, present_late, today, "PRESENT",
            actual_first_in=first_in, worked_minutes=480, is_late=True, late_minutes=20,
            scheduled_end=past,
        )  # fmt: skip
        await _add_day(company_id, absent, today, "ABSENT", scheduled_end=past)
        await _add_day(company_id, not_yet, today, "ABSENT", scheduled_end=future)
        await _add_day(
            company_id,
            half_leave,
            today,
            "LEAVE",
            leave_fraction=Decimal("0.50"),
            scheduled_end=future,
        )
        await _add_day(company_id, weekly_off, today, "NOT_EXPECTED")
        await _add_day(
            company_id, in_progress, today, "INCOMPLETE",
            actual_first_in=first_in, missing_punch=True, scheduled_end=future,
        )  # fmt: skip
        await _add_day(
            company_id, missing_out, today, "INCOMPLETE",
            actual_first_in=first_in, missing_punch=True, scheduled_end=past,
        )  # fmt: skip
        await _add_day(
            company_id, unassigned, today, "PRESENT", actual_first_in=first_in, worked_minutes=60
        )
        # Terminated employee's stale row must not count either.
        await _add_day(
            company_id, left, today, "PRESENT", actual_first_in=first_in, worked_minutes=60
        )

        response = await client.get(URL, headers=headers)
        assert response.status_code == 200, response.text
        data = response.json()["data"]

        assert data["attendance_date"] == today.isoformat()
        assert data["timezone"] == TZ
        assert data["is_today"] is True
        # The terminated employee is outside the population.
        assert data["total"] == 9
        assert data["present"] == 3  # late, in-progress, unassigned
        assert data["absent"] == 1  # shift over, nothing punched
        assert data["not_checked_in"] == 1  # shift still ahead: never "absent"
        assert data["on_leave"] == 1
        assert data["not_expected"] == 1  # weekly off / holiday never absent
        assert data["no_record"] == 1  # not guessed
        assert data["incomplete"] == 1  # missing checkout after shift end
        assert data["on_duty"] == 0 and data["remote_work"] == 0
        # Primary buckets are exclusive and add up to the population.
        assert (
            data["present"] + data["absent"] + data["on_leave"] + data["on_duty"]
            + data["remote_work"] + data["not_checked_in"] + data["incomplete"]
            + data["not_expected"] + data["no_record"]
        ) == data["total"]  # fmt: skip
        assert data["expected_employees"] == data["total"] - 1 - 1
        # Overlays are not extra buckets.
        assert data["late"] == 1
        assert data["half_day_leave"] == 1
        assert data["exceptions"] == 2  # in-progress open punch + missing checkout

        departments = {d["department_name"]: d for d in data["departments"]}
        assert departments["Engineering"]["total"] == 5  # late, absent, weekly-off, none, progress
        assert departments["Engineering"]["present"] == 2
        assert departments["Engineering"]["absent"] == 1
        assert departments["HR"]["total"] == 3
        assert departments["HR"]["on_leave"] == 1
        assert departments["HR"]["not_checked_in"] == 1
        assert departments["Unassigned"]["total"] == 1
        assert data["departments"][-1]["department_name"] == "Unassigned"
        assert sum(d["total"] for d in data["departments"]) == data["total"]

        filtered = (
            await client.get(URL, headers=headers, params={"department_id": ctx["hr"]})
        ).json()["data"]
        assert filtered["total"] == 3
        assert [d["department_name"] for d in filtered["departments"]] == ["HR"]
    finally:
        await _cleanup_attendance_day(company_id=company_id)


async def test_past_date_has_no_not_checked_in_and_future_date_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    ctx = await _setup(client)
    headers, company_id = ctx["headers"], ctx["company_id"]
    today = business_today(TZ)
    yesterday = today - timedelta(days=1)
    try:
        emp = await _employee(
            client,
            headers,
            name="Pat",
            legal_entity_id=ctx["le"],
            department_id=ctx["eng"],
            branch_id=ctx["branch"],
            designation_id=ctx["desig"],
        )
        # A zero-punch day whose shift "ends" in the future of that date is still a confirmed
        # absence once the date itself is past.
        await _add_day(
            company_id, emp, yesterday, "ABSENT",
            scheduled_end=datetime.now(UTC) + timedelta(hours=1),
        )  # fmt: skip
        data = (
            await client.get(URL, headers=headers, params={"date": yesterday.isoformat()})
        ).json()["data"]
        assert data["is_today"] is False
        assert data["absent"] == 1 and data["not_checked_in"] == 0

        future = await client.get(
            URL, headers=headers, params={"date": (today + timedelta(days=1)).isoformat()}
        )
        assert future.status_code == 422
    finally:
        await _cleanup_attendance_day(company_id=company_id)


async def test_tenant_isolation_and_auth(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    ctx_a = await _setup(client)
    ctx_b = await _setup(client)
    today = business_today(TZ)
    try:
        emp = await _employee(
            client,
            ctx_a["headers"],
            name="Alice",
            legal_entity_id=ctx_a["le"],
            department_id=ctx_a["eng"],
            branch_id=ctx_a["branch"],
            designation_id=ctx_a["desig"],
        )
        await _add_day(
            ctx_a["company_id"], emp, today, "PRESENT",
            actual_first_in=datetime.now(UTC) - timedelta(hours=1), worked_minutes=60,
        )  # fmt: skip

        a = (await client.get(URL, headers=ctx_a["headers"])).json()["data"]
        b = (await client.get(URL, headers=ctx_b["headers"])).json()["data"]
        assert a["total"] == 1 and a["present"] == 1
        assert b["total"] == 0 and b["departments"] == []

        # A department id from another tenant yields an empty population, never foreign data.
        cross = (
            await client.get(URL, headers=ctx_b["headers"], params={"department_id": ctx_a["eng"]})
        ).json()["data"]
        assert cross["total"] == 0

        unauthenticated = await client.get(URL)
        assert unauthenticated.status_code in (401, 403)
    finally:
        await _cleanup_attendance_day(company_id=ctx_a["company_id"])
        await _cleanup_attendance_day(company_id=ctx_b["company_id"])
