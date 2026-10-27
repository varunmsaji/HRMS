"""`GET /v1/employee-calendar/me` - the read-only employee self-service calendar.

Needs the disposable integration stack (the root conftest refuses the shared dev stack).

September 2026 reference: 1 Sep is a Tuesday, so Sundays are 6/13/20/27 and Saturdays 5/12/19/26.
The company calendar ("A") has Sunday off; the employee-specific calendar ("B") has Saturday off,
a holiday on Wed 9 Sep and a SHUTDOWN exception on Mon 14 Sep.
"""

import json
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import event, text
from tests.integration.modules.attendance.test_attendance_security import (
    _cleanup_scoped_users,
    _create_permission_scoped_user,
)
from tests.integration.modules.leave.test_leave_application import (
    _cleanup,
    _register_tenant,
    _setup_calendar,
    _setup_full,
    _submit,
    _teardown,
)
from tests.integration.modules.leave.test_leave_rbac_matrix import _user_with_default_role

from hrms.core.db.session import get_engine, get_session_factory

from .test_workforce_calendar import (
    _cleanup_workforce_calendar,
    _create_holiday,
    _create_holiday_calendar,
    _create_weekly_off_pattern,
    _create_work_calendar,
)

pytestmark = pytest.mark.asyncio

URL = "/v1/employee-calendar/me"

_ALLOWED_DAY_KEYS = {
    "date",
    "configured",
    "day_type",
    "holiday_name",
    "holiday_type",
    "holiday_on_weekly_off",
    "is_holiday_named",
    "optional_holiday_name",
    "restricted_holiday_name",
    "exception_type",
    "weekly_off_fraction",
    "leave",
}
_ALLOWED_LEAVE_KEYS = {"status", "fraction", "half"}


async def _days(client: AsyncClient, headers: dict[str, str], start: str, end: str):
    response = await client.get(URL, headers=headers, params={"from": start, "to": end})
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    return data, {d["date"]: d for d in data["days"]}


async def _assign(client: AsyncClient, headers: dict[str, str], **body: Any) -> None:
    response = await client.post("/v1/policy-assignments", headers=headers, json=body)
    assert response.status_code == 201, response.text


async def _employee_calendar_b(client: AsyncClient, admin: dict[str, str]) -> dict[str, Any]:
    """Calendar B: Saturday off + a Wednesday holiday + a SHUTDOWN exception."""
    holidays = await _create_holiday_calendar(client, admin, name="Employee holidays")
    await _create_holiday(
        client,
        admin,
        holidays["id"],
        date="2026-09-09",
        name="Founders Day",
        holiday_type="COMPANY",
    )
    saturday = await _create_weekly_off_pattern(
        client, admin, name="Saturday Off", rules=[{"weekday": 5, "off_fraction": "1.00"}]
    )
    calendar = await _create_work_calendar(
        client,
        admin,
        name="Calendar B",
        weekly_off_pattern_id=saturday["id"],
        holiday_calendar_ids=[holidays["id"]],
    )
    exception = await client.post(
        f"/v1/work-calendars/{calendar['id']}/exceptions",
        headers=admin,
        json={
            "exception_date": "2026-09-14",
            "exception_type": "SHUTDOWN",
            "name": "Plant shutdown",
        },
    )
    assert exception.status_code == 201, exception.text
    return calendar


async def _set_leave_status(application_id: str, status: str) -> None:
    """Data setup only: moves an existing application to a status the public flow reaches via
    approver/cancel actions that are not under test here."""
    async with get_session_factory()() as session:
        await session.execute(
            text("UPDATE leave_application SET status = :s WHERE id = CAST(:i AS uuid)"),
            {"s": status, "i": application_id},
        )
        await session.commit()


async def _finish(company_id: UUID, user_id: UUID | None, *, scoped_users: bool = True) -> None:
    await _cleanup_workforce_calendar(company_id=company_id)
    await _teardown(company_id=company_id)
    await _cleanup(company_id=company_id, user_id=user_id)
    if scoped_users:
        await _cleanup_scoped_users()


async def test_company_calendar_classifies_working_days_and_weekly_offs(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    admin, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, admin)
        me = await _user_with_default_role(company_id, "EMPLOYEE", UUID(ctx["employee"]["id"]))
        data, by_date = await _days(client, me, "2026-09-01", "2026-09-30")
        assert data["configuration"] == "COMPLETE"
        assert data["leave_included"] is True
        assert len(data["days"]) == 30
        assert by_date["2026-09-08"]["day_type"] == "WORKING"
        assert by_date["2026-09-06"]["day_type"] == "WEEKLY_OFF"
        assert by_date["2026-09-13"]["day_type"] == "WEEKLY_OFF"
        assert by_date["2026-09-12"]["day_type"] == "WORKING"  # Saturday is a working day here
        assert all(d["configured"] for d in data["days"])
    finally:
        await _finish(company_id, user_id)


async def test_employee_assignment_takes_precedence_with_holidays_and_exceptions(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    admin, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, admin)
        employee_id = ctx["employee"]["id"]
        calendar_b = await _employee_calendar_b(client, admin)
        await _assign(
            client,
            admin,
            policy_kind="WORK_CALENDAR",
            policy_id=calendar_b["id"],
            scope_type="EMPLOYEE",
            scope_id=employee_id,
            effective_from="2026-09-01",
        )
        me = await _user_with_default_role(company_id, "EMPLOYEE", UUID(employee_id))
        _, by_date = await _days(client, me, "2026-09-01", "2026-09-30")

        assert by_date["2026-09-06"]["day_type"] == "WORKING"  # company Sunday-off does not apply
        assert by_date["2026-09-12"]["day_type"] == "WEEKLY_OFF"  # B's Saturday
        assert by_date["2026-09-09"]["day_type"] == "HOLIDAY"
        assert by_date["2026-09-09"]["holiday_name"] == "Founders Day"
        assert by_date["2026-09-14"]["day_type"] == "SHUTDOWN"
        assert by_date["2026-09-14"]["exception_type"] == "SHUTDOWN"

        # The admin-side resolver agrees (same classifier) and a colleague without the
        # employee-level assignment still gets the company calendar.
        other = await client.post("/v1/employees", headers=admin, json={"first_name": "Other"})
        other_id = other.json()["data"]["id"]
        resolved = await client.get(
            "/v1/calendar-resolution",
            headers=admin,
            params={"employee_id": other_id, "date": "2026-09-06"},
        )
        assert resolved.json()["data"]["day_type"]["day_type"] == "WEEKLY_OFF"
    finally:
        await _finish(company_id, user_id)


async def test_assignment_change_inside_range_is_applied_from_its_effective_date(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    admin, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, admin)
        employee_id = ctx["employee"]["id"]
        calendar_b = await _employee_calendar_b(client, admin)
        await _assign(
            client,
            admin,
            policy_kind="WORK_CALENDAR",
            policy_id=calendar_b["id"],
            scope_type="EMPLOYEE",
            scope_id=employee_id,
            effective_from="2026-09-15",
        )
        me = await _user_with_default_role(company_id, "EMPLOYEE", UUID(employee_id))
        _, by_date = await _days(client, me, "2026-09-10", "2026-09-22")
        assert by_date["2026-09-13"]["day_type"] == "WEEKLY_OFF"  # A (Sunday) before the change
        assert by_date["2026-09-12"]["day_type"] == "WORKING"
        assert by_date["2026-09-14"]["day_type"] == "WORKING"  # B's exception is B-only, and B
        assert by_date["2026-09-19"]["day_type"] == "WEEKLY_OFF"  # starts on the 15th
        assert by_date["2026-09-20"]["day_type"] == "WORKING"
    finally:
        await _finish(company_id, user_id)


async def test_employee_weekly_off_assignment_overrides_the_calendar_pattern(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    admin, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, admin)
        employee_id = ctx["employee"]["id"]
        saturday = await _create_weekly_off_pattern(
            client, admin, name="Saturday Off", rules=[{"weekday": 5, "off_fraction": "1.00"}]
        )
        await _assign(
            client,
            admin,
            policy_kind="WEEKLY_OFF",
            policy_id=saturday["id"],
            scope_type="EMPLOYEE",
            scope_id=employee_id,
            effective_from="2026-09-01",
        )
        me = await _user_with_default_role(company_id, "EMPLOYEE", UUID(employee_id))
        _, by_date = await _days(client, me, "2026-09-05", "2026-09-06")
        assert by_date["2026-09-05"]["day_type"] == "WEEKLY_OFF"  # Saturday, from the override
        assert by_date["2026-09-06"]["day_type"] == "WORKING"  # the calendar's Sunday is replaced
    finally:
        await _finish(company_id, user_id)


async def test_no_assignment_is_reported_as_incomplete_not_working(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    admin, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, admin)
        await _cleanup_workforce_calendar(company_id=company_id)  # removes the company assignment
        me = await _user_with_default_role(company_id, "EMPLOYEE", UUID(ctx["employee"]["id"]))
        data, by_date = await _days(client, me, "2026-09-01", "2026-09-07")
        assert data["configuration"] == "INCOMPLETE"
        assert all(not d["configured"] and d["day_type"] is None for d in by_date.values())
    finally:
        await _finish(company_id, user_id)


async def test_partially_configured_range_is_reported_as_partial(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    admin, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, admin)  # company calendar effective from 2024-01-01
        await _cleanup_workforce_calendar(company_id=company_id)
        await _setup_calendar(client, admin, effective_from="2026-09-05")
        me = await _user_with_default_role(company_id, "EMPLOYEE", UUID(ctx["employee"]["id"]))
        data, by_date = await _days(client, me, "2026-09-01", "2026-09-08")
        assert data["configuration"] == "PARTIAL"
        assert by_date["2026-09-04"]["configured"] is False
        assert by_date["2026-09-05"]["configured"] is True
    finally:
        await _finish(company_id, user_id)


@pytest.mark.parametrize(
    ("params", "expected_code"),
    [
        ({"from": "2026-09-10", "to": "2026-09-09"}, "CALENDAR_RANGE_INVALID"),
        ({"from": "2026-01-01", "to": "2026-06-01"}, "CALENDAR_RANGE_INVALID"),
        ({"from": "not-a-date", "to": "2026-09-09"}, None),
        ({"from": "2026-09-01"}, None),
    ],
)
async def test_invalid_and_oversized_ranges_are_rejected(
    client: AsyncClient, seeded_plan_catalogue: None, params: dict[str, str], expected_code
) -> None:
    admin, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, admin)
        me = await _user_with_default_role(company_id, "EMPLOYEE", UUID(ctx["employee"]["id"]))
        response = await client.get(URL, headers=me, params=params)
        assert response.status_code == 422, response.text
        if expected_code:
            assert response.json()["error"]["code"] == expected_code
    finally:
        await _finish(company_id, user_id)


async def test_a_hundred_day_range_is_accepted(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    admin, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, admin)
        me = await _user_with_default_role(company_id, "EMPLOYEE", UUID(ctx["employee"]["id"]))
        data, _ = await _days(client, me, "2026-09-01", "2026-12-09")
        assert len(data["days"]) == 100
    finally:
        await _finish(company_id, user_id)


async def test_caller_without_employee_record_is_rejected_explicitly(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    admin, company_id, user_id = await _register_tenant(client)
    try:
        await _setup_full(client, admin)
        response = await client.get(
            URL, headers=admin, params={"from": "2026-09-01", "to": "2026-09-02"}
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["details"][0]["code"] == "EMPLOYEE_RECORD_REQUIRED"
    finally:
        await _finish(company_id, user_id)


async def test_request_parameters_cannot_select_another_employee_or_company(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    admin_a, company_a, user_a = await _register_tenant(client)
    admin_b, company_b, user_b = await _register_tenant(client)
    try:
        ctx_a = await _setup_full(client, admin_a)
        ctx_b = await _setup_full(client, admin_b)
        calendar_b = await _employee_calendar_b(client, admin_a)
        # Only employee A has the special calendar; they are the caller.
        await _assign(
            client,
            admin_a,
            policy_kind="WORK_CALENDAR",
            policy_id=calendar_b["id"],
            scope_type="EMPLOYEE",
            scope_id=ctx_a["employee"]["id"],
            effective_from="2026-09-01",
        )
        # A colleague in the same company, with their own approved leave.
        colleague = await client.post("/v1/employees", headers=admin_a, json={"first_name": "Sam"})
        colleague_id = colleague.json()["data"]["id"]

        me_a = await _user_with_default_role(company_a, "EMPLOYEE", UUID(ctx_a["employee"]["id"]))
        _, baseline = await _days(client, me_a, "2026-09-01", "2026-09-30")

        # Injected identifiers are ignored: same answer as without them.
        injected = await client.get(
            URL,
            headers=me_a,
            params={
                "from": "2026-09-01",
                "to": "2026-09-30",
                "employee_id": colleague_id,
                "company_id": str(company_b),
            },
        )
        assert injected.status_code == 200, injected.text
        assert {d["date"]: d for d in injected.json()["data"]["days"]} == baseline
        assert baseline["2026-09-12"]["day_type"] == "WEEKLY_OFF"  # still A's own calendar B

        # Tenant A's token cannot be pointed at tenant B's company.
        cross = await client.get(
            URL,
            headers={**me_a, "X-Company-Id": str(company_b)},
            params={"from": "2026-09-01", "to": "2026-09-02"},
        )
        assert cross.status_code in (401, 403, 404), cross.text

        # Tenant B's employee sees only tenant B's configuration (no holiday from tenant A).
        me_b = await _user_with_default_role(company_b, "EMPLOYEE", UUID(ctx_b["employee"]["id"]))
        _, theirs = await _days(client, me_b, "2026-09-01", "2026-09-30")
        assert theirs["2026-09-09"]["day_type"] == "WORKING"
        assert "Founders Day" not in json.dumps(theirs)
    finally:
        await _finish(company_a, user_a, scoped_users=False)
        await _finish(company_b, user_b)


async def test_leave_statuses_halves_and_privacy(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    admin, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, admin)
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]
        colleague = (
            await client.post("/v1/employees", headers=admin, json={"first_name": "Sam"})
        ).json()["data"]
        secret = "SECRET-MEDICAL-REASON"

        async def submit(start: str, end: str, **extra: Any) -> str:
            response = await _submit(
                client,
                admin,
                employee_id=employee_id,
                leave_type_id=leave_type_id,
                start_date=start,
                end_date=end,
                reason=secret,
                attachment_reference="private/scan.pdf",
                **extra,
            )
            assert response.status_code == 201, response.text
            return str(response.json()["data"]["id"])

        await submit("2026-09-08", "2026-09-08")  # approved, full day
        await submit("2026-09-09", "2026-09-09", half_day="FIRST_HALF")  # approved, half day
        await submit("2026-09-21", "2026-09-23")  # approved, multi-day
        pending = await submit("2026-09-15", "2026-09-15")
        rejected = await submit("2026-09-16", "2026-09-16")
        cancelled = await submit("2026-09-17", "2026-09-17")
        await _set_leave_status(pending, "SUBMITTED")
        await _set_leave_status(rejected, "REJECTED")
        await _set_leave_status(cancelled, "CANCELLED")

        me = await _user_with_default_role(company_id, "EMPLOYEE", UUID(employee_id))
        data, by_date = await _days(client, me, "2026-09-01", "2026-09-30")

        assert by_date["2026-09-08"]["leave"] == [
            {"status": "APPROVED", "fraction": "1.00", "half": None}
        ]
        assert by_date["2026-09-09"]["leave"] == [
            {"status": "APPROVED", "fraction": "0.50", "half": "FIRST_HALF"}
        ]
        assert by_date["2026-09-15"]["leave"][0]["status"] == "PENDING"
        for d in ("2026-09-21", "2026-09-22", "2026-09-23"):
            assert [item["status"] for item in by_date[d]["leave"]] == ["APPROVED"]
        assert by_date["2026-09-16"]["leave"] == []  # rejected
        assert by_date["2026-09-17"]["leave"] == []  # cancelled
        assert by_date["2026-09-10"]["leave"] == []

        # Nothing beyond the minimal display facts is serialised.
        for day in data["days"]:
            assert set(day) <= _ALLOWED_DAY_KEYS
            for item in day["leave"]:
                assert set(item) <= _ALLOWED_LEAVE_KEYS
        raw = json.dumps(data)
        assert secret not in raw and "scan.pdf" not in raw

        # A colleague's leave never appears for this employee.
        other_leave = await _submit(
            client,
            admin,
            employee_id=colleague["id"],
            leave_type_id=leave_type_id,
            start_date="2026-09-24",
            end_date="2026-09-24",
        )
        # (the colleague has no employment / balance in this fixture, so the submit may be
        # refused; either way their dates must not leak)
        _, after = await _days(client, me, "2026-09-01", "2026-09-30")
        assert after["2026-09-24"]["leave"] == [], other_leave.text
    finally:
        await _finish(company_id, user_id)


async def test_leave_is_omitted_without_a_leave_view_grant(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    from hrms.modules.attendance.permissions import ATTENDANCE_VIEW

    admin, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, admin)
        employee_id = ctx["employee"]["id"]
        response = await _submit(
            client, admin, employee_id=employee_id, leave_type_id=ctx["leave_type"]["id"]
        )
        assert response.status_code == 201, response.text
        headers, _ = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[ATTENDANCE_VIEW],
            data_scope="SELF",
            caller_employee_id=UUID(employee_id),
        )
        data, by_date = await _days(client, headers, "2026-09-01", "2026-09-10")
        assert data["leave_included"] is False
        assert by_date["2026-09-08"]["leave"] == []
        assert by_date["2026-09-08"]["day_type"] == "WORKING"
    finally:
        await _finish(company_id, user_id)


async def test_query_count_does_not_grow_with_range_length(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    admin, company_id, user_id = await _register_tenant(client)
    statements: list[str] = []

    def count(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        statements.append(statement)

    try:
        ctx = await _setup_full(client, admin)
        calendar_b = await _employee_calendar_b(client, admin)
        await _assign(
            client,
            admin,
            policy_kind="WORK_CALENDAR",
            policy_id=calendar_b["id"],
            scope_type="EMPLOYEE",
            scope_id=ctx["employee"]["id"],
            effective_from="2026-09-01",
        )
        me = await _user_with_default_role(company_id, "EMPLOYEE", UUID(ctx["employee"]["id"]))
        await _days(client, me, "2026-09-01", "2026-09-07")  # warm caches

        engine = get_engine().sync_engine
        event.listen(engine, "before_cursor_execute", count)
        try:
            await _days(client, me, "2026-09-01", "2026-09-07")
            short = len(statements)
            statements.clear()
            await _days(client, me, "2026-09-01", "2026-10-11")
            long = len(statements)
        finally:
            event.remove(engine, "before_cursor_execute", count)
        assert short == long, (short, long)
    finally:
        await _finish(company_id, user_id)
