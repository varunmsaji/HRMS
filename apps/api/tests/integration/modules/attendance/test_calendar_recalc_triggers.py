"""AC-02 / AC-07 (attendance + calendar + overtime audit, 16 Nov 2026): holiday, weekly-off pattern,
work-calendar, calendar-exception and policy-version changes queue a recalculation, and the
processor brings the stored day up to date. Before, a day older than the 3-day sweep stayed wrong
until period close."""

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from tests.integration.modules.attendance.test_attendance_day import (
    _cleanup_attendance_day,
    _register_tenant,
)
from tests.integration.modules.attendance.test_overtime_record import (
    _cleanup_overtime,
    _create_overtime_policy,
)
from tests.integration.modules.attendance.test_recalc_queue import (
    DAY,
    _calculate,
    _pending,
    _stored_status,
)
from tests.integration.modules.attendance.test_shift_window import _wire
from tests.integration.modules.organisation.test_registration_flow import _cleanup
from tests.integration.modules.organisation.test_workforce_calendar import (
    _cleanup_workforce_calendar,
)

from hrms.modules.attendance import recalc

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def tenant(
    client: AsyncClient, seeded_plan_catalogue: None
) -> AsyncIterator[tuple[dict[str, str], UUID]]:
    headers, company_id, user_id = await _register_tenant(client)
    yield headers, company_id
    await _cleanup_overtime(company_id=company_id)
    await _cleanup_workforce_calendar(company_id=company_id)
    await _cleanup_attendance_day(company_id=company_id)
    await _cleanup(company_id=company_id, user_id=user_id)


async def _settled(client: AsyncClient, headers: dict[str, str], company_id: UUID) -> str:
    """A wired employee with the date calculated and the setup's own requests processed."""
    employee_id = (await _wire(client, headers, allowance=None))["employee_id"]
    await _calculate(client, headers, employee_id)
    await recalc.process_company_requests(company_id)
    assert await _pending(company_id) == []
    return str(employee_id)


async def _holiday_calendar_linked(client: AsyncClient, headers: dict[str, str]) -> str:
    calendar = await client.post("/v1/holiday-calendars", headers=headers, json={"name": "Closed"})
    assert calendar.status_code == 201, calendar.text
    calendar_id = str(calendar.json()["data"]["id"])
    work_calendar = (await client.get("/v1/work-calendars", headers=headers)).json()["data"][0]
    linked = await client.patch(
        f"/v1/work-calendars/{work_calendar['id']}",
        headers={**headers, "If-Match": str(work_calendar["version"])},
        json={"holiday_calendar_ids": [calendar_id]},
    )
    assert linked.status_code == 200, linked.text
    return calendar_id


async def _reasons(company_id: UUID) -> list[str]:
    return sorted({r.reason for r in await _pending(company_id)})


async def test_a_holiday_added_after_calculation_recalculates_the_stored_day(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID]
) -> None:
    headers, company_id = tenant
    employee_id = await _settled(client, headers, company_id)
    stale = await _stored_status(company_id, employee_id)
    assert stale != "NOT_EXPECTED"
    calendar_id = await _holiday_calendar_linked(client, headers)
    await recalc.process_company_requests(company_id)  # the calendar link's own request

    created = await client.post(
        f"/v1/holiday-calendars/{calendar_id}/holidays",
        headers=headers,
        json={"date": DAY, "name": "Closed"},
    )
    assert created.status_code == 201, created.text
    pending = await _pending(company_id)
    assert [r.reason for r in pending] == ["HOLIDAY_CHANGED"]
    assert pending[0].date_from.isoformat() == pending[0].date_to.isoformat() == DAY
    assert await _stored_status(company_id, employee_id) == stale  # until the processor runs

    await recalc.process_company_requests(company_id)
    assert await _stored_status(company_id, employee_id) == "NOT_EXPECTED"

    # Deactivating it queues the same date again and the day goes back.
    holiday = created.json()["data"]
    deactivated = await client.patch(
        f"/v1/holidays/{holiday['id']}",
        headers={**headers, "If-Match": str(holiday["version"])},
        json={"is_active": False},
    )
    assert deactivated.status_code == 200, deactivated.text
    assert await _reasons(company_id) == ["HOLIDAY_CHANGED"]
    await recalc.process_company_requests(company_id)
    assert await _stored_status(company_id, employee_id) == stale


async def test_weekly_off_pattern_work_calendar_and_exception_changes_queue_recalculation(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID]
) -> None:
    headers, company_id = tenant
    await _settled(client, headers, company_id)

    pattern = await client.post(
        "/v1/weekly-off-patterns",
        headers=headers,
        json={
            "name": "Sundays",
            "pattern_kind": "FIXED_WEEKDAYS",
            "rules": [{"weekday": 6, "off_fraction": "1.00"}],
        },
    )
    assert pattern.status_code == 201, pattern.text
    assert await _pending(company_id) == []  # an unassigned new pattern affects nobody

    work_calendar = (await client.get("/v1/work-calendars", headers=headers)).json()["data"][0]
    changed = await client.patch(
        f"/v1/work-calendars/{work_calendar['id']}",
        headers={**headers, "If-Match": str(work_calendar["version"])},
        json={"weekly_off_pattern_id": pattern.json()["data"]["id"]},
    )
    assert changed.status_code == 200, changed.text
    assert await _reasons(company_id) == ["WORK_CALENDAR_CHANGED"]
    await recalc.process_company_requests(company_id)

    pat = pattern.json()["data"]
    edited = await client.patch(
        f"/v1/weekly-off-patterns/{pat['id']}",
        headers={**headers, "If-Match": str(pat["version"])},
        json={"rules": [{"weekday": 5, "off_fraction": "1.00"}]},
    )
    assert edited.status_code == 200, edited.text
    assert await _reasons(company_id) == ["WEEKLY_OFF_PATTERN_CHANGED"]
    await recalc.process_company_requests(company_id)

    exception = await client.post(
        f"/v1/work-calendars/{work_calendar['id']}/exceptions",
        headers=headers,
        json={"exception_date": DAY, "exception_type": "SHUTDOWN", "name": "Flood"},
    )
    assert exception.status_code == 201, exception.text
    pending = await _pending(company_id)
    assert [r.reason for r in pending] == ["CALENDAR_EXCEPTION_CHANGED"]
    assert pending[0].date_from.isoformat() == DAY


async def test_publishing_an_overtime_policy_version_queues_only_its_assignees(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID]
) -> None:
    headers, company_id = tenant
    await _settled(client, headers, company_id)
    policy = await _create_overtime_policy(client, headers, approval_chain="AUTO")
    await recalc.process_company_requests(company_id)  # the assignment's own request
    assert await _pending(company_id) == []

    draft = await client.post(
        f"/v1/overtime-policies/{policy['id']}/versions",
        headers=headers,
        json={
            "effective_from": DAY,
            "eligibility": "ALWAYS",
            "min_ot_minutes": 30,
            "approval_chain": "AUTO",
            "requires_post_approval": False,
        },
    )
    assert draft.status_code == 201, draft.text
    assert await _pending(company_id) == []  # a draft changes nothing
    versions = (
        await client.get(f"/v1/overtime-policies/{policy['id']}/versions", headers=headers)
    ).json()["data"]
    current = next(v for v in versions if v["status"] == "PUBLISHED")
    published = await client.post(
        f"/v1/overtime-policies/{policy['id']}/versions/{draft.json()['data']['id']}/publish",
        headers={**headers, "If-Match": "1"},
        json={"expected_previous_version": current["version"]},
    )
    assert published.status_code == 200, published.text
    pending: list[Any] = await _pending(company_id)
    assert [r.reason for r in pending] == ["POLICY_VERSION_PUBLISHED"]
    assert pending[0].date_from.isoformat() == DAY


async def test_a_failed_immediate_calculation_leaves_a_durable_request(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A back-dated on-behalf punch whose immediate calculation fails no longer depends on the
    3-day sweep: the retry is a stored, visible recalculation request."""
    from tests.integration.modules.attendance.test_attendance_day import _punch

    from hrms.modules.attendance.service import AttendanceDayService

    headers, company_id = tenant
    employee_id = await _settled(client, headers, company_id)

    async def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("calculation exploded")

    monkeypatch.setattr(AttendanceDayService, "calculate", boom)
    await _punch(
        client, headers, employee_id=employee_id, hour=9, minute=0, direction="IN", day=DAY
    )

    pending = await _pending(company_id)
    assert [r.reason for r in pending] == ["IMMEDIATE_CALCULATION_FAILED"]
    assert str(pending[0].employee_id) == employee_id
    assert pending[0].date_from.isoformat() == DAY


async def test_calendar_setup_past_date_warning_uses_the_business_date(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-09 - the warning compares with the company's date, not the UTC date."""
    import datetime as dt

    from hrms.modules.organisation import calendar_setup

    headers, _ = tenant
    body = {"weekly_off_weekdays": [5, 6], "effective_from": "2026-09-01"}

    monkeypatch.setattr(calendar_setup, "business_today", lambda tz: dt.date(2026, 8, 31))
    same_day = await client.post("/v1/work-calendar-setup/preview", headers=headers, json=body)
    assert same_day.status_code == 200, same_day.text
    assert not any("in the past" in w for w in same_day.json()["data"]["warnings"])

    monkeypatch.setattr(calendar_setup, "business_today", lambda tz: dt.date(2026, 9, 2))
    past = await client.post("/v1/work-calendar-setup/preview", headers=headers, json=body)
    assert any("in the past" in w for w in past.json()["data"]["warnings"])
