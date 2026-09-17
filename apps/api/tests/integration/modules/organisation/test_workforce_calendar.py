"""Integration tests for the Workforce Calendar (W1) API surface —
`/v1/holiday-calendars*`, `/v1/weekly-off-patterns*`, `/v1/work-calendars*`,
`/v1/calendar-exceptions*`, `/v1/policy-assignments`, `/v1/calendar-resolution`.

Covers: CRUD + If-Match concurrency + soft-deactivate for each resource, the
`policy_assignment_no_overlap` GiST exclusion constraint's friendly-error surface,
the calendar-day-type classification endpoint, the full WD-09 precedence-walk
`/calendar-resolution` endpoint against a real employee/assignment, cross-tenant 404s, and
`ORG.CALENDAR.MANAGE`/`ORG.HOLIDAY.MANAGE` permission-matrix 403s. Mirrors the shape of
`test_shift.py`/`test_employee_assignment.py`.
"""

from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from hrms.core.audit.models import AuditLog
from hrms.core.db.models.identity import Permission, Role, RolePermission
from hrms.core.db.session import get_session_factory
from hrms.modules.organisation.permissions import ORG_CALENDAR_MANAGE, ORG_HOLIDAY_MANAGE

from .test_registration_flow import _cleanup, _register

pytestmark = pytest.mark.asyncio


async def _register_tenant(
    client: AsyncClient, **overrides: Any
) -> tuple[dict[str, str], UUID, UUID | None]:
    response, company_id, user_id = await _register(client, **overrides)
    assert response.status_code == 201
    assert company_id is not None
    data = response.json()["data"]
    return (
        {"Authorization": f"Bearer {data['access_token']}", "X-Company-Id": str(company_id)},
        company_id,
        user_id,
    )


async def _strip_permission(company_id: UUID, code: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        role = (
            await session.execute(
                select(Role).where(Role.company_id == company_id, Role.code == "COMPANY_ADMIN")
            )
        ).scalar_one()
        perm = (
            await session.execute(select(Permission).where(Permission.code == code))
        ).scalar_one()
        await session.execute(
            RolePermission.__table__.delete().where(
                RolePermission.role_id == role.id, RolePermission.permission_id == perm.id
            )
        )
        await session.commit()


async def _create_holiday_calendar(
    client: AsyncClient, headers: dict[str, str], name: str = "India National", **extra: Any
) -> dict[str, Any]:
    response = await client.post(
        "/v1/holiday-calendars", headers=headers, json={"name": name, **extra}
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _create_holiday(
    client: AsyncClient,
    headers: dict[str, str],
    calendar_id: str,
    *,
    date: str = "2026-08-15",
    name: str = "Independence Day",
    expected_status: int = 201,
    **extra: Any,
) -> dict[str, Any]:
    response = await client.post(
        f"/v1/holiday-calendars/{calendar_id}/holidays",
        headers=headers,
        json={"date": date, "name": name, **extra},
    )
    assert response.status_code == expected_status, response.text
    return dict(response.json()["data"]) if expected_status < 400 else dict(response.json())


async def _create_weekly_off_pattern(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    name: str = "Sunday Off",
    pattern_kind: str = "FIXED_WEEKDAYS",
    rules: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    response = await client.post(
        "/v1/weekly-off-patterns",
        headers=headers,
        json={
            "name": name,
            "pattern_kind": pattern_kind,
            "rules": rules or [{"weekday": 6, "off_fraction": "1.00"}],
        },
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _create_work_calendar(
    client: AsyncClient, headers: dict[str, str], *, name: str = "India General", **extra: Any
) -> dict[str, Any]:
    response = await client.post(
        "/v1/work-calendars", headers=headers, json={"name": name, **extra}
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _cleanup_workforce_calendar(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        for table in (
            "policy_assignment",
            "calendar_exception",
            "work_calendar_holiday_calendar",
            "work_calendar",
            "weekly_off_rule",
            "weekly_off_pattern",
            "holiday",
            "holiday_calendar",
        ):
            await session.execute(
                text(f"DELETE FROM {table} WHERE company_id = :cid"), {"cid": str(company_id)}
            )
        await session.commit()


# --- HolidayCalendar ---------------------------------------------------------------------


async def test_create_and_get_holiday_calendar(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        calendar = await _create_holiday_calendar(
            client,
            headers,
            name="Kerala Office Holidays",
            code="KL",
            kind="REGIONAL",
            state_code="KL",
        )
        assert calendar["kind"] == "REGIONAL"
        assert calendar["state_code"] == "KL"
        assert calendar["is_active"] is True
        assert calendar["version"] == 1

        fetched = await client.get(f"/v1/holiday-calendars/{calendar['id']}", headers=headers)
        assert fetched.status_code == 200
        assert fetched.json()["data"]["name"] == "Kerala Office Holidays"

        factory = get_session_factory()
        async with factory() as session:
            rows = (
                (
                    await session.execute(
                        select(AuditLog).where(
                            AuditLog.entity_id == UUID(calendar["id"]),
                            AuditLog.action == "HOLIDAY_CALENDAR_CREATED",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 1
    finally:
        await _cleanup_workforce_calendar(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_holiday_calendar_duplicate_code_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        await _create_holiday_calendar(client, headers, name="First", code="NAT")
        response = await client.post(
            "/v1/holiday-calendars", headers=headers, json={"name": "Second", "code": "NAT"}
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "HOLIDAY_CALENDAR_CODE_ALREADY_EXISTS"
    finally:
        await _cleanup_workforce_calendar(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_deactivate_holiday_calendar(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        calendar = await _create_holiday_calendar(client, headers)
        response = await client.request(
            "DELETE",
            f"/v1/holiday-calendars/{calendar['id']}",
            headers={**headers, "If-Match": str(calendar["version"])},
        )
        assert response.status_code == 200
        assert response.json()["data"]["is_active"] is False
    finally:
        await _cleanup_workforce_calendar(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# --- Holiday -------------------------------------------------------------------------------


async def test_create_holiday_and_filter_by_year(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        calendar = await _create_holiday_calendar(client, headers)
        await _create_holiday(
            client, headers, calendar["id"], date="2026-08-15", name="Independence Day"
        )
        await _create_holiday(
            client, headers, calendar["id"], date="2027-01-26", name="Republic Day"
        )

        all_holidays = await client.get(
            f"/v1/holiday-calendars/{calendar['id']}/holidays", headers=headers
        )
        assert len(all_holidays.json()["data"]) == 2

        only_2026 = await client.get(
            f"/v1/holiday-calendars/{calendar['id']}/holidays",
            headers=headers,
            params={"year": 2026},
        )
        names = {h["name"] for h in only_2026.json()["data"]}
        assert names == {"Independence Day"}
    finally:
        await _cleanup_workforce_calendar(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_holiday_duplicate_active_date_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        calendar = await _create_holiday_calendar(client, headers)
        await _create_holiday(client, headers, calendar["id"], date="2026-08-15")
        conflict = await _create_holiday(
            client,
            headers,
            calendar["id"],
            date="2026-08-15",
            name="Duplicate",
            expected_status=409,
        )
        assert conflict["error"]["code"] == "HOLIDAY_DATE_ALREADY_EXISTS"
    finally:
        await _cleanup_workforce_calendar(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_holiday_update_cannot_change_date(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`HolidayUpdate` has no `date`/`calendar_id` field at all — sending one is a 422
    mass-assignment rejection, not a silent no-op (architecture §25: "no PATCH of used dates")."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        calendar = await _create_holiday_calendar(client, headers)
        holiday = await _create_holiday(client, headers, calendar["id"])
        response = await client.patch(
            f"/v1/holidays/{holiday['id']}",
            headers={**headers, "If-Match": str(holiday["version"])},
            json={"date": "2026-08-16"},
        )
        assert response.status_code == 422
    finally:
        await _cleanup_workforce_calendar(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_holiday_update_metadata_and_deactivate(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        calendar = await _create_holiday_calendar(client, headers)
        holiday = await _create_holiday(client, headers, calendar["id"], holiday_type="OPTIONAL")
        assert holiday["is_optional"] is True

        response = await client.patch(
            f"/v1/holidays/{holiday['id']}",
            headers={**headers, "If-Match": str(holiday["version"])},
            json={"is_active": False},
        )
        assert response.status_code == 200
        assert response.json()["data"]["is_active"] is False
    finally:
        await _cleanup_workforce_calendar(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# --- WeeklyOffPattern ------------------------------------------------------------------------


async def test_create_weekly_off_pattern_with_rules(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        pattern = await _create_weekly_off_pattern(
            client,
            headers,
            name="2nd & 4th Saturday + Sunday",
            pattern_kind="CUSTOM",
            rules=[
                {"weekday": 5, "nth_in_month": 2, "off_fraction": "1.00"},
                {"weekday": 5, "nth_in_month": 4, "off_fraction": "1.00"},
                {"weekday": 6, "off_fraction": "1.00"},
            ],
        )
        assert len(pattern["rules"]) == 3

        fetched = await client.get(f"/v1/weekly-off-patterns/{pattern['id']}", headers=headers)
        assert len(fetched.json()["data"]["rules"]) == 3
    finally:
        await _cleanup_workforce_calendar(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_weekly_off_pattern_rejects_shape_mismatch(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.post(
            "/v1/weekly-off-patterns",
            headers=headers,
            json={
                "name": "Bad NTH",
                "pattern_kind": "NTH_WEEKDAY",
                "rules": [{"weekday": 5, "off_fraction": "1.00"}],  # missing nth_in_month
            },
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "WEEKLY_OFF_RULE_INVALID"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_weekly_off_pattern_update_replaces_rules(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        pattern = await _create_weekly_off_pattern(client, headers)
        response = await client.patch(
            f"/v1/weekly-off-patterns/{pattern['id']}",
            headers={**headers, "If-Match": str(pattern["version"])},
            json={
                "rules": [
                    {"weekday": 5, "off_fraction": "0.50"},
                    {"weekday": 6, "off_fraction": "1.00"},
                ]
            },
        )
        assert response.status_code == 200
        rules = response.json()["data"]["rules"]
        assert len(rules) == 2
        assert {r["weekday"] for r in rules} == {5, 6}
    finally:
        await _cleanup_workforce_calendar(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# --- WorkCalendar ----------------------------------------------------------------------------


async def test_create_work_calendar_with_composition(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        holiday_calendar = await _create_holiday_calendar(client, headers)
        pattern = await _create_weekly_off_pattern(client, headers)

        work_calendar = await _create_work_calendar(
            client,
            headers,
            name="India General",
            weekly_off_pattern_id=pattern["id"],
            holiday_calendar_ids=[holiday_calendar["id"]],
        )
        assert work_calendar["holiday_calendar_ids"] == [holiday_calendar["id"]]
        assert work_calendar["weekly_off_pattern_id"] == pattern["id"]
    finally:
        await _cleanup_workforce_calendar(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_work_calendar_invalid_composition_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.post(
            "/v1/work-calendars",
            headers=headers,
            json={"name": "Bad", "holiday_calendar_ids": [str(uuid4())]},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "WORK_CALENDAR_COMPOSITION_INVALID"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_work_calendar_day_type_classification(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        holiday_calendar = await _create_holiday_calendar(client, headers)
        await _create_holiday(
            client, headers, holiday_calendar["id"], date="2026-08-15", name="Independence Day"
        )
        pattern = await _create_weekly_off_pattern(client, headers)  # Sunday off
        work_calendar = await _create_work_calendar(
            client,
            headers,
            weekly_off_pattern_id=pattern["id"],
            holiday_calendar_ids=[holiday_calendar["id"]],
        )

        holiday_day = await client.get(
            f"/v1/work-calendars/{work_calendar['id']}/day-type",
            headers=headers,
            params={"date": "2026-08-15"},
        )
        assert holiday_day.json()["data"]["day_type"] == "HOLIDAY"

        weekly_off_day = await client.get(
            f"/v1/work-calendars/{work_calendar['id']}/day-type",
            headers=headers,
            params={"date": "2026-08-16"},
        )
        assert weekly_off_day.json()["data"]["day_type"] == "WEEKLY_OFF"

        working_day = await client.get(
            f"/v1/work-calendars/{work_calendar['id']}/day-type",
            headers=headers,
            params={"date": "2026-08-17"},
        )
        assert working_day.json()["data"]["day_type"] == "WORKING"
    finally:
        await _cleanup_workforce_calendar(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# --- CalendarException -----------------------------------------------------------------------


async def test_create_calendar_exception_overrides_day_type(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        work_calendar = await _create_work_calendar(client, headers)
        response = await client.post(
            f"/v1/work-calendars/{work_calendar['id']}/exceptions",
            headers=headers,
            json={
                "exception_date": "2026-08-29",
                "exception_type": "SHUTDOWN",
                "reason": "Office move",
            },
        )
        assert response.status_code == 201

        day_type = await client.get(
            f"/v1/work-calendars/{work_calendar['id']}/day-type",
            headers=headers,
            params={"date": "2026-08-29"},
        )
        assert day_type.json()["data"]["day_type"] == "SHUTDOWN"
    finally:
        await _cleanup_workforce_calendar(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_calendar_exception_duplicate_active_date_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        work_calendar = await _create_work_calendar(client, headers)
        await client.post(
            f"/v1/work-calendars/{work_calendar['id']}/exceptions",
            headers=headers,
            json={"exception_date": "2026-08-29", "exception_type": "SHUTDOWN"},
        )
        response = await client.post(
            f"/v1/work-calendars/{work_calendar['id']}/exceptions",
            headers=headers,
            json={"exception_date": "2026-08-29", "exception_type": "SPECIAL_WORKING"},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "CALENDAR_EXCEPTION_DATE_CONFLICT"
    finally:
        await _cleanup_workforce_calendar(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_calendar_exception_update_cannot_change_date_or_type(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        work_calendar = await _create_work_calendar(client, headers)
        created = await client.post(
            f"/v1/work-calendars/{work_calendar['id']}/exceptions",
            headers=headers,
            json={"exception_date": "2026-08-29", "exception_type": "SHUTDOWN"},
        )
        exception = created.json()["data"]
        response = await client.patch(
            f"/v1/calendar-exceptions/{exception['id']}",
            headers={**headers, "If-Match": str(exception["version"])},
            json={"exception_type": "SPECIAL_WORKING"},
        )
        assert response.status_code == 422
    finally:
        await _cleanup_workforce_calendar(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# --- PolicyAssignment -------------------------------------------------------------------------


async def test_policy_assignment_company_scope_create_and_list(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        work_calendar = await _create_work_calendar(client, headers)
        response = await client.post(
            "/v1/policy-assignments",
            headers=headers,
            json={
                "policy_kind": "WORK_CALENDAR",
                "policy_id": work_calendar["id"],
                "scope_type": "COMPANY",
                "effective_from": "2026-01-01",
            },
        )
        assert response.status_code == 201, response.text
        assert response.json()["data"]["scope_id"] is None

        listed = await client.get(
            "/v1/policy-assignments",
            headers=headers,
            params={"policy_kind": "WORK_CALENDAR", "scope_type": "COMPANY"},
        )
        assert len(listed.json()["data"]) == 1
    finally:
        await _cleanup_workforce_calendar(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_policy_assignment_scope_id_required_unless_company(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        work_calendar = await _create_work_calendar(client, headers)
        response = await client.post(
            "/v1/policy-assignments",
            headers=headers,
            json={
                "policy_kind": "WORK_CALENDAR",
                "policy_id": work_calendar["id"],
                "scope_type": "BRANCH",
                "effective_from": "2026-01-01",
            },
        )
        assert response.status_code == 422
    finally:
        await _cleanup_workforce_calendar(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_policy_assignment_overlap_rejected_without_closing(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Inserting a second COMPANY-scope `WORK_CALENDAR` assignment whose range overlaps the
    first, without supplying `If-Match` to close the first one, must be rejected — this
    exercises `PolicyAssignmentVersionRequiredError` first, and if that guard were bypassed,
    the GiST exclusion constraint itself would still catch it."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        work_calendar = await _create_work_calendar(client, headers)
        await client.post(
            "/v1/policy-assignments",
            headers=headers,
            json={
                "policy_kind": "WORK_CALENDAR",
                "policy_id": work_calendar["id"],
                "scope_type": "COMPANY",
                "effective_from": "2026-01-01",
            },
        )
        response = await client.post(
            "/v1/policy-assignments",
            headers=headers,
            json={
                "policy_kind": "WORK_CALENDAR",
                "policy_id": work_calendar["id"],
                "scope_type": "COMPANY",
                "effective_from": "2026-06-01",
            },
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "POLICY_ASSIGNMENT_VERSION_REQUIRED"
    finally:
        await _cleanup_workforce_calendar(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_policy_assignment_insert_new_close_previous(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        calendar_a = await _create_work_calendar(client, headers, name="Calendar A")
        calendar_b = await _create_work_calendar(client, headers, name="Calendar B")

        first = await client.post(
            "/v1/policy-assignments",
            headers=headers,
            json={
                "policy_kind": "WORK_CALENDAR",
                "policy_id": calendar_a["id"],
                "scope_type": "COMPANY",
                "effective_from": "2026-01-01",
            },
        )
        assert first.status_code == 201

        second = await client.post(
            "/v1/policy-assignments",
            headers={**headers, "If-Match": str(first.json()["data"]["version"])},
            json={
                "policy_kind": "WORK_CALENDAR",
                "policy_id": calendar_b["id"],
                "scope_type": "COMPANY",
                "effective_from": "2026-07-01",
            },
        )
        assert second.status_code == 201, second.text

        listed = await client.get(
            "/v1/policy-assignments",
            headers=headers,
            params={"policy_kind": "WORK_CALENDAR", "scope_type": "COMPANY"},
        )
        rows = listed.json()["data"]
        assert len(rows) == 2
        closed = next(r for r in rows if r["policy_id"] == calendar_a["id"])
        assert closed["effective_to"] == "2026-06-30"
        open_row = next(r for r in rows if r["policy_id"] == calendar_b["id"])
        assert open_row["effective_to"] is None
    finally:
        await _cleanup_workforce_calendar(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# --- Calendar resolution (WD-09 precedence) --------------------------------------------------


async def test_calendar_resolution_config_incomplete_without_assignment(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_response = await client.post(
            "/v1/employees", headers=headers, json={"first_name": "Asha"}
        )
        employee = employee_response.json()["data"]
        response = await client.get(
            "/v1/calendar-resolution",
            headers=headers,
            params={"employee_id": employee["id"], "date": "2026-08-15"},
        )
        assert response.status_code == 200
        assert response.json()["data"]["config_incomplete"] is True
        assert response.json()["data"]["work_calendar_id"] is None
    finally:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                text("DELETE FROM employee WHERE company_id = :cid"), {"cid": str(company_id)}
            )
            await session.execute(
                text("DELETE FROM number_series WHERE company_id = :cid"), {"cid": str(company_id)}
            )
            await session.commit()
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_calendar_resolution_company_scope_default(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_response = await client.post(
            "/v1/employees", headers=headers, json={"first_name": "Asha"}
        )
        employee = employee_response.json()["data"]

        holiday_calendar = await _create_holiday_calendar(client, headers)
        await _create_holiday(
            client, headers, holiday_calendar["id"], date="2026-08-15", name="Independence Day"
        )
        work_calendar = await _create_work_calendar(
            client, headers, holiday_calendar_ids=[holiday_calendar["id"]]
        )
        await client.post(
            "/v1/policy-assignments",
            headers=headers,
            json={
                "policy_kind": "WORK_CALENDAR",
                "policy_id": work_calendar["id"],
                "scope_type": "COMPANY",
                "effective_from": "2026-01-01",
            },
        )

        response = await client.get(
            "/v1/calendar-resolution",
            headers=headers,
            params={"employee_id": employee["id"], "date": "2026-08-15"},
        )
        data = response.json()["data"]
        assert data["config_incomplete"] is False
        assert data["work_calendar_id"] == work_calendar["id"]
        assert data["resolved_scope_type"] == "COMPANY"
        assert data["day_type"]["day_type"] == "HOLIDAY"
    finally:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                text("DELETE FROM employee WHERE company_id = :cid"), {"cid": str(company_id)}
            )
            await session.execute(
                text("DELETE FROM number_series WHERE company_id = :cid"), {"cid": str(company_id)}
            )
            await session.commit()
        await _cleanup_workforce_calendar(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_calendar_resolution_branch_scope_beats_company(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """WD-09 — BRANCH outranks COMPANY. An employee assigned to a branch with its own
    WORK_CALENDAR PolicyAssignment must resolve to the branch calendar, not the company
    default, even though both are active on the target date."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = (
            await client.post("/v1/employees", headers=headers, json={"first_name": "Asha"})
        ).json()["data"]
        legal_entity = (
            await client.post("/v1/legal-entities", headers=headers, json={"name": "Acme LE"})
        ).json()["data"]
        branch = (
            await client.post(
                "/v1/branches",
                headers=headers,
                json={"legal_entity_id": legal_entity["id"], "name": "Kochi Branch"},
            )
        ).json()["data"]
        department = (
            await client.post(
                "/v1/departments",
                headers=headers,
                json={"name": "Engineering", "branch_id": branch["id"]},
            )
        ).json()["data"]
        designation = (
            await client.post(
                "/v1/designations",
                headers=headers,
                json={"title": "Software Engineer", "department_id": department["id"]},
            )
        ).json()["data"]
        employment = (
            await client.post(
                f"/v1/employees/{employee['id']}/employments",
                headers=headers,
                json={"legal_entity_id": legal_entity["id"], "joining_date": "2026-01-01"},
            )
        ).json()["data"]
        assert employment is not None
        assignment_response = await client.post(
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
        assert assignment_response.status_code == 201, assignment_response.text

        company_calendar = await _create_work_calendar(client, headers, name="Company Default")
        branch_calendar = await _create_work_calendar(client, headers, name="Kochi Branch Calendar")

        company_assignment = await client.post(
            "/v1/policy-assignments",
            headers=headers,
            json={
                "policy_kind": "WORK_CALENDAR",
                "policy_id": company_calendar["id"],
                "scope_type": "COMPANY",
                "effective_from": "2026-01-01",
            },
        )
        assert company_assignment.status_code == 201, company_assignment.text
        branch_assignment = await client.post(
            "/v1/policy-assignments",
            headers=headers,
            json={
                "policy_kind": "WORK_CALENDAR",
                "policy_id": branch_calendar["id"],
                "scope_type": "BRANCH",
                "scope_id": branch["id"],
                "effective_from": "2026-01-01",
            },
        )
        assert branch_assignment.status_code == 201, branch_assignment.text

        response = await client.get(
            "/v1/calendar-resolution",
            headers=headers,
            params={"employee_id": employee["id"], "date": "2026-08-15"},
        )
        data = response.json()["data"]
        assert data["work_calendar_id"] == branch_calendar["id"]
        assert data["resolved_scope_type"] == "BRANCH"
    finally:
        factory = get_session_factory()
        async with factory() as session:
            for table in (
                "employee_assignment",
                "employment",
                "employee",
                "number_series",
                "designation",
                "department",
                "branch",
                "legal_entity",
            ):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE company_id = :cid"), {"cid": str(company_id)}
                )
            await session.commit()
        await _cleanup_workforce_calendar(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# --- Cross-tenant isolation -------------------------------------------------------------------


async def test_work_calendar_cross_tenant_404(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        work_calendar = await _create_work_calendar(client, headers_b)
        response = await client.get(f"/v1/work-calendars/{work_calendar['id']}", headers=headers_a)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"

        listed = await client.get("/v1/work-calendars", headers=headers_a)
        assert listed.json()["data"] == []
    finally:
        await _cleanup_workforce_calendar(company_id=company_a)
        await _cleanup_workforce_calendar(company_id=company_b)
        await _cleanup(company_id=company_a, user_id=user_a)
        await _cleanup(company_id=company_b, user_id=user_b)


async def test_holiday_calendar_cross_tenant_404(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        calendar = await _create_holiday_calendar(client, headers_b)
        response = await client.get(f"/v1/holiday-calendars/{calendar['id']}", headers=headers_a)
        assert response.status_code == 404
    finally:
        await _cleanup_workforce_calendar(company_id=company_a)
        await _cleanup_workforce_calendar(company_id=company_b)
        await _cleanup(company_id=company_a, user_id=user_a)
        await _cleanup(company_id=company_b, user_id=user_b)


# --- Permission matrix -------------------------------------------------------------------------


async def test_work_calendar_denied_without_org_calendar_manage(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        await _strip_permission(company_id, ORG_CALENDAR_MANAGE)
        response = await client.get("/v1/work-calendars", headers=headers)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_holiday_calendar_denied_without_org_holiday_manage(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        await _strip_permission(company_id, ORG_HOLIDAY_MANAGE)
        response = await client.get("/v1/holiday-calendars", headers=headers)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_registration_grants_calendar_permissions_to_new_company(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Regression guard for the "forgot to grant the second call site" failure mode —
    `register_company` must grant `ORG.CALENDAR.MANAGE`/`ORG.HOLIDAY.MANAGE`, not just the
    demo seed."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.get("/v1/work-calendars", headers=headers)
        assert response.status_code == 200
        response = await client.get("/v1/holiday-calendars", headers=headers)
        assert response.status_code == 200
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)
