"""Integration tests for W5 — `/v1/rosters*` and the calculation engine's roster resolution
(architecture §4.2/§9.7/§25, decision log WD-27).

Reuses `_build_wired_employee`/`_punch`/`_register_tenant`/`_cleanup_attendance_day` from
`test_attendance_day.py` (same cross-file reuse pattern `test_attendance_security.py` already
established) so the wired employee already has an assignment `shift_id`, a COMPANY work
calendar, and a COMPANY attendance policy — the roster tests only need to add roster rows on
top and assert which shift the calculation actually used.
"""

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from tests.integration.modules.attendance.test_attendance_day import (
    _build_wired_employee,
    _cleanup_attendance_day,
    _punch,
    _register_tenant,
)
from tests.integration.modules.attendance.test_attendance_security import (
    _add_reportee_employee,
    _cleanup_scoped_users,
    _create_permission_scoped_user,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.core.db.session import get_session_factory

pytestmark = pytest.mark.asyncio


async def _create_night_shift(client: AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    """A published 22:00-06:00 cross-midnight shift, distinct from `_build_wired_employee`'s
    09:00-18:00 default — used to prove a roster override actually changes which shift the
    calculation engine reads, including its overnight attribution (FR-ATT-005)."""
    shift = (await client.post("/v1/shifts", headers=headers, json={"name": "Night"})).json()[
        "data"
    ]
    draft_id = shift["draft_version_id"]
    patched = await client.patch(
        f"/v1/shifts/{shift['id']}/versions/{draft_id}",
        headers={**headers, "If-Match": "1"},
        json={
            "shift_type": "FIXED",
            "effective_from": "2026-01-01",
            "start_time": "22:00",
            "end_time": "06:00",
            "timezone": "UTC",
        },
    )
    assert patched.status_code == 200, patched.text
    published = await client.post(
        f"/v1/shifts/{shift['id']}/versions/{draft_id}/publish",
        headers={**headers, "If-Match": "2"},
        json={},
    )
    assert published.status_code == 200, published.text
    return shift


async def test_published_roster_overrides_assignment_shift(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """architecture §9.7's worked example: assignment default is the day shift, roster assigns
    the night shift for one date — attendance on that date must use the night shift."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        night_shift = await _create_night_shift(client, headers)

        created = await client.post(
            "/v1/rosters",
            headers=headers,
            json={
                "employee_id": employee_id,
                "roster_date": "2026-08-10",
                "shift_id": night_shift["id"],
            },
        )
        assert created.status_code == 201, created.text
        roster = created.json()["data"]
        assert roster["status"] == "DRAFT"

        published = await client.post(
            f"/v1/rosters/{roster['id']}/publish",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert published.status_code == 200, published.text
        assert published.json()["data"]["status"] == "PUBLISHED"

        # 23:00 on the roster date -> 05:00 the next calendar day, inside the night shift window.
        await _punch(client, headers, employee_id=employee_id, hour=23, minute=0, direction="IN")
        await _punch(
            client,
            headers,
            employee_id=employee_id,
            hour=5,
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
        # Whole overnight duty attributes to the roster date (FR-ATT-005), not the OUT date.
        assert data["attendance_date"] == "2026-08-10"
        assert data["shift_id"] == night_shift["id"]
        assert data["attendance_status"] == "PRESENT"
        assert data["worked_minutes"] == 360
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_draft_roster_does_not_affect_calculation(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A staged DRAFT roster must never change a live calculation (WD-27) — only publishing
    does. Assignment's day shift (09:00-18:00) must still be what the engine reads."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        night_shift = await _create_night_shift(client, headers)

        created = await client.post(
            "/v1/rosters",
            headers=headers,
            json={
                "employee_id": employee_id,
                "roster_date": "2026-08-10",
                "shift_id": night_shift["id"],
            },
        )
        assert created.status_code == 201, created.text
        assert created.json()["data"]["status"] == "DRAFT"

        await _punch(client, headers, employee_id=employee_id, hour=9, minute=0, direction="IN")
        await _punch(client, headers, employee_id=employee_id, hour=18, minute=0, direction="OUT")

        response = await client.post(
            "/v1/attendance/days/calculate",
            headers=headers,
            params={"employee_id": employee_id, "date": "2026-08-10"},
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["shift_id"] == wired["shift"]["id"]
        assert data["worked_minutes"] == 540
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_roster_week_off_override_marks_not_expected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """§9.7's rotating-crew example: a roster row with no shift and
    `is_week_off_override=true` makes an otherwise-WORKING calendar day NOT_EXPECTED for this
    one employee, without touching `calendar_day_type`."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]

        created = await client.post(
            "/v1/rosters",
            headers=headers,
            json={
                "employee_id": employee_id,
                "roster_date": "2026-08-10",
                "is_week_off_override": True,
            },
        )
        assert created.status_code == 201, created.text
        publish = await client.post(
            f"/v1/rosters/{created.json()['data']['id']}/publish",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert publish.status_code == 200, publish.text

        response = await client.post(
            "/v1/attendance/days/calculate",
            headers=headers,
            params={"employee_id": employee_id, "date": "2026-08-10"},
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["attendance_status"] == "NOT_EXPECTED"
        assert data["calendar_day_type"] == "WORKING"
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def _publish_roster(
    client: AsyncClient, headers: dict[str, str], body: dict[str, Any]
) -> None:
    created = await client.post("/v1/rosters", headers=headers, json=body)
    assert created.status_code == 201, created.text
    published = await client.post(
        f"/v1/rosters/{created.json()['data']['id']}/publish",
        headers={**headers, "If-Match": "1"},
        json={},
    )
    assert published.status_code == 200, published.text


async def test_roster_week_off_after_night_shift_leaves_the_overnight_out_to_the_shift_day(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A night shift on 10 Aug ends at 06:00 on 11 Aug, a rostered week-off with no shift. The
    OUT belongs to 10 Aug; 11 Aug loads its whole calendar day and must not pick it up and
    become INCOMPLETE with a missing punch."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        night_shift = await _create_night_shift(client, headers)
        await _publish_roster(
            client,
            headers,
            {
                "employee_id": employee_id,
                "roster_date": "2026-08-10",
                "shift_id": night_shift["id"],
            },
        )
        await _publish_roster(
            client,
            headers,
            {"employee_id": employee_id, "roster_date": "2026-08-11", "is_week_off_override": True},
        )
        await _punch(client, headers, employee_id=employee_id, hour=21, minute=55, direction="IN")
        await _punch(
            client,
            headers,
            employee_id=employee_id,
            hour=6,
            minute=23,
            direction="OUT",
            day="2026-08-11",
        )

        shift_day = await client.post(
            "/v1/attendance/days/calculate",
            headers=headers,
            params={"employee_id": employee_id, "date": "2026-08-10"},
        )
        assert shift_day.status_code == 200, shift_day.text
        assert shift_day.json()["data"]["attendance_status"] == "PRESENT"

        week_off = await client.post(
            "/v1/attendance/days/calculate",
            headers=headers,
            params={"employee_id": employee_id, "date": "2026-08-11"},
        )
        assert week_off.status_code == 200, week_off.text
        data = week_off.json()["data"]
        assert data["attendance_status"] == "NOT_EXPECTED"
        assert data["missing_punch"] is False
        assert len(data["computation_snapshot"]["prior_day_claimed_punch_ids"]) == 1
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_roster_null_shift_without_override_falls_through_to_missing_shift_behaviour(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A roster row that sets `shift_id=NULL` without `is_week_off_override` is a genuine
    "no schedule resolved for this date" fact — distinct from a deliberate day off — so it must
    still hit `missing_shift_behaviour` (default INCOMPLETE), not silently become NOT_EXPECTED
    or PRESENT."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]

        created = await client.post(
            "/v1/rosters",
            headers=headers,
            json={"employee_id": employee_id, "roster_date": "2026-08-10"},
        )
        assert created.status_code == 201, created.text
        publish = await client.post(
            f"/v1/rosters/{created.json()['data']['id']}/publish",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert publish.status_code == 200, publish.text

        response = await client.post(
            "/v1/attendance/days/calculate",
            headers=headers,
            params={"employee_id": employee_id, "date": "2026-08-10"},
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["attendance_status"] == "INCOMPLETE"
        assert data["shift_id"] is None
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_duplicate_roster_date_conflicts(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The partial unique index on `(company_id, employee_id, roster_date)` prevents a second
    roster row for a date that already has one — the caller must PATCH the existing entry."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]

        first = await client.post(
            "/v1/rosters",
            headers=headers,
            json={
                "employee_id": employee_id,
                "roster_date": "2026-08-10",
                "shift_id": wired["shift"]["id"],
            },
        )
        assert first.status_code == 201, first.text

        second = await client.post(
            "/v1/rosters",
            headers=headers,
            json={
                "employee_id": employee_id,
                "roster_date": "2026-08-10",
                "shift_id": wired["shift"]["id"],
            },
        )
        assert second.status_code == 409, second.text
        assert second.json()["error"]["code"] == "SHIFT_ROSTER_DATE_CONFLICT"
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_publish_is_audited(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    """architecture §24 names "Roster write" as an audited action — publish must produce a
    before/after `audit_log` row, mirroring `Shift`'s own audit-on-mutate pattern."""
    from sqlalchemy import text

    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]

        created = await client.post(
            "/v1/rosters",
            headers=headers,
            json={
                "employee_id": employee_id,
                "roster_date": "2026-08-10",
                "shift_id": wired["shift"]["id"],
            },
        )
        roster_id = created.json()["data"]["id"]
        publish = await client.post(
            f"/v1/rosters/{roster_id}/publish",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert publish.status_code == 200, publish.text

        factory = get_session_factory()
        async with factory() as session:
            from hrms.core.db.session import set_rls_company_id

            await set_rls_company_id(session, str(company_id))
            rows = (
                await session.execute(
                    text(
                        "SELECT action FROM audit_log WHERE entity_type = 'shift_roster' "
                        "AND entity_id = :eid ORDER BY occurred_at"
                    ),
                    {"eid": roster_id},
                )
            ).all()
        actions = [r[0] for r in rows]
        assert "SHIFT_ROSTER_CREATED" in actions
        assert "SHIFT_ROSTER_PUBLISHED" in actions
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_roster_manage_reportees_scope_blocks_target_outside_visible_set(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Same bug class fixed for punches in commit `fecb740`: a `REPORTEES`-scoped
    `ATTENDANCE.ROSTER_MANAGE` grant proves the caller may manage rosters for *some* employees,
    not that a specific target is one of them."""
    from hrms.modules.attendance.permissions import ATTENDANCE_ROSTER_MANAGE

    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        manager_id = wired["employee"]["id"]
        reportee = await _add_reportee_employee(
            client,
            headers,
            wired=wired,
            first_name="Reportee",
            reporting_manager_id=UUID(manager_id),
        )
        stranger = await _add_reportee_employee(
            client, headers, wired=wired, first_name="Stranger", reporting_manager_id=None
        )

        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[ATTENDANCE_ROSTER_MANAGE],
            data_scope="REPORTEES",
            caller_employee_id=UUID(manager_id),
        )

        blocked = await client.post(
            "/v1/rosters",
            headers=scoped_headers,
            json={
                "employee_id": stranger["id"],
                "roster_date": "2026-08-10",
                "shift_id": wired["shift"]["id"],
            },
        )
        assert blocked.status_code == 404
        assert blocked.json()["error"]["code"] == "NOT_FOUND"

        allowed = await client.post(
            "/v1/rosters",
            headers=scoped_headers,
            json={
                "employee_id": reportee["id"],
                "roster_date": "2026-08-10",
                "shift_id": wired["shift"]["id"],
            },
        )
        assert allowed.status_code == 201, allowed.text
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_stale_version_rejected_on_publish(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]

        created = await client.post(
            "/v1/rosters",
            headers=headers,
            json={
                "employee_id": employee_id,
                "roster_date": "2026-08-10",
                "shift_id": wired["shift"]["id"],
            },
        )
        roster_id = created.json()["data"]["id"]

        stale_publish = await client.post(
            f"/v1/rosters/{roster_id}/publish",
            headers={**headers, "If-Match": "99"},
            json={},
        )
        assert stale_publish.status_code == 409
        assert stale_publish.json()["error"]["code"] == "STALE_RESOURCE"
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
