"""Integration tests for `TZ-01`/`DEC-TZ-04` (SELECTED) — the timezone-change guard added in
Phase 3 of the attendance timezone remediation (`docs/audits/
ATTENDANCE_TIMEZONE_FINAL_DECISION_AND_EXECUTION_GATE.md` §12).

Reuses `_build_wired_employee`/`_punch`/`_register_tenant`/`_cleanup_attendance_day` from
`test_attendance_day.py` and `_insert_closed_period`/`_full_calculate` from
`test_attendance_period.py` — the same cross-file reuse pattern every W6/W7/W8 test file already
established, rather than re-deriving the employee+shift+policy wiring `evaluate_day` needs to
reach a real `PRESENT` verdict.
"""

from uuid import UUID

import pytest
from httpx import AsyncClient
from tests.integration.modules.attendance.test_attendance_day import (
    _build_wired_employee,
    _cleanup_attendance_day,
    _register_tenant,
)
from tests.integration.modules.attendance.test_attendance_period import (
    _DAY,
    _full_calculate,
    _insert_closed_period,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup
from tests.integration.modules.organisation.test_shift_version import (
    _cleanup_shifts,
    _create_shift,
)

pytestmark = pytest.mark.asyncio


async def _cleanup_period(*, company_id: UUID) -> None:
    from sqlalchemy import text

    from hrms.core.db.session import get_session_factory, set_rls_company_id

    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        await session.execute(
            text("DELETE FROM attendance_period WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.commit()


async def _set_company_timezone_raw(*, company_id: UUID, timezone: str) -> None:
    """Registration already produces `Asia/Kolkata` — the one and only allowed value under
    `DEC-TZ-02` (SELECTED, Phase 2) — so a company can never legitimately request a *different*
    allowed value to change to via the API. This simulates the case the guard exists for: a
    company whose timezone predates the Phase 2 allow-list, or an environment configured with a
    wider `allowed_company_timezones`. Bypasses the schema validator entirely, on purpose."""
    from sqlalchemy import text

    from hrms.core.db.session import get_session_factory, set_rls_company_id

    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        await session.execute(
            text("UPDATE company SET timezone = :tz WHERE id = :cid"),
            {"tz": timezone, "cid": str(company_id)},
        )
        await session.commit()


# ---------------------------------------------------------------------------
# Company-scope guard — update_company_profile
# ---------------------------------------------------------------------------


async def test_company_timezone_change_blocked_once_attendance_exists(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        await _full_calculate(client, headers, employee_id=wired["employee"]["id"])
        # Registration already produces the one allowed value (`Asia/Kolkata`) — simulate a
        # legacy/pre-Phase-2 row so there is a genuinely different value to patch away from.
        await _set_company_timezone_raw(company_id=company_id, timezone="UTC")

        get_response = await client.get("/v1/companies/current", headers=headers)
        version = get_response.json()["data"]["version"]
        response = await client.patch(
            "/v1/companies/current",
            headers={**headers, "If-Match": str(version)},
            json={"timezone": "Asia/Kolkata"},
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "TIMEZONE_CHANGE_BLOCKED"
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_company_timezone_change_permitted_with_zero_attendance(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A brand-new company with zero computed attendance may still be corrected freely — the
    guard is data-driven, not a blanket lock on the field."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        get_response = await client.get("/v1/companies/current", headers=headers)
        version = get_response.json()["data"]["version"]
        response = await client.patch(
            "/v1/companies/current",
            headers={**headers, "If-Match": str(version)},
            json={"timezone": "Asia/Kolkata"},
        )
        assert response.status_code == 200, response.text
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_company_timezone_change_blocked_by_closed_period_even_with_zero_attendance(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`ED-12` point 3 — a `CLOSED` period can exist with zero `AttendanceDay` rows underneath
    it (no employment spans overlapped it). The `CLOSED`-period check must be absolute and
    checked BEFORE the zero-attendance case is treated as permissive."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        await _insert_closed_period(company_id=company_id)
        await _set_company_timezone_raw(company_id=company_id, timezone="UTC")
        get_response = await client.get("/v1/companies/current", headers=headers)
        version = get_response.json()["data"]["version"]
        response = await client.patch(
            "/v1/companies/current",
            headers={**headers, "If-Match": str(version)},
            json={"timezone": "Asia/Kolkata"},
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "TIMEZONE_CHANGE_BLOCKED"
    finally:
        await _cleanup_period(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_company_timezone_unchanged_value_not_guarded(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Patching `timezone` to its OWN current value is not a change — must not trip the guard
    even with computed attendance present, mirroring `update_company_profile`'s own
    `patch.timezone != company.timezone` condition."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        await _full_calculate(client, headers, employee_id=wired["employee"]["id"])

        get_response = await client.get("/v1/companies/current", headers=headers)
        current_timezone = get_response.json()["data"]["timezone"]
        version = get_response.json()["data"]["version"]
        response = await client.patch(
            "/v1/companies/current",
            headers={**headers, "If-Match": str(version)},
            json={"timezone": current_timezone},
        )
        assert response.status_code == 200, response.text
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# ---------------------------------------------------------------------------
# Branch-scope guard — update_branch, walking EmployeeAssignment history (ED-12)
# ---------------------------------------------------------------------------


async def test_branch_timezone_change_blocked_once_attendance_exists(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        await _full_calculate(client, headers, employee_id=wired["employee"]["id"])

        branch_id = wired["branch"]["id"]
        get_branch = await client.get(f"/v1/branches/{branch_id}", headers=headers)
        version = get_branch.json()["data"]["version"]
        response = await client.patch(
            f"/v1/branches/{branch_id}",
            headers={**headers, "If-Match": str(version)},
            json={"timezone": "Asia/Kolkata"},
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "TIMEZONE_CHANGE_BLOCKED"
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_branch_timezone_change_permitted_with_zero_attendance(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        branch_id = wired["branch"]["id"]
        get_branch = await client.get(f"/v1/branches/{branch_id}", headers=headers)
        version = get_branch.json()["data"]["version"]
        response = await client.patch(
            f"/v1/branches/{branch_id}",
            headers={**headers, "If-Match": str(version)},
            json={"timezone": "Asia/Kolkata"},
        )
        assert response.status_code == 200, response.text
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_branch_timezone_change_blocked_for_employee_who_has_since_transferred_away(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`ED-12` — the guard's scope is "any computed `attendance_day` exists for the affected
    scope," walking `EmployeeAssignment` HISTORY, not the current roster. An employee who has
    since transferred to a different branch still has historical days computed under the
    original branch's timezone; a current-roster-only check would miss exactly this case."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        original_branch_id = wired["branch"]["id"]
        await _full_calculate(client, headers, employee_id=employee_id, day=_DAY)

        # Transfer the employee to a brand-new branch — the original branch now has NO employee
        # in its *current* roster.
        legal_entity = (
            await client.post("/v1/legal-entities", headers=headers, json={"name": "New LE"})
        ).json()["data"]
        new_branch = (
            await client.post(
                "/v1/branches",
                headers=headers,
                json={"legal_entity_id": legal_entity["id"], "name": "New Branch"},
            )
        ).json()["data"]
        transfer = await client.post(
            f"/v1/employees/{employee_id}/assignments",
            headers={**headers, "If-Match": "1"},
            json={
                "effective_from": "2026-08-11",
                "change_type": "TRANSFER",
                "branch_id": new_branch["id"],
            },
        )
        assert transfer.status_code == 201, transfer.text

        # The ORIGINAL branch — no one is currently assigned to it — must still be blocked.
        get_branch = await client.get(f"/v1/branches/{original_branch_id}", headers=headers)
        version = get_branch.json()["data"]["version"]
        response = await client.patch(
            f"/v1/branches/{original_branch_id}",
            headers={**headers, "If-Match": str(version)},
            json={"timezone": "Asia/Kolkata"},
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "TIMEZONE_CHANGE_BLOCKED"
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# ---------------------------------------------------------------------------
# SR-11 — CLOSED-period check on shift-version publish
# ---------------------------------------------------------------------------


async def test_shift_version_publish_blocked_by_closed_period(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A backdated publish whose `effective_from` falls inside an already-`CLOSED` period is
    refused, the same way punch ingestion and roster writes already are (`SR-11`)."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        await _insert_closed_period(
            company_id=company_id, period_start="2026-08-01", period_end="2026-08-31"
        )
        shift = await _create_shift(client, headers)
        draft_id = shift["draft_version_id"]
        await client.patch(
            f"/v1/shifts/{shift['id']}/versions/{draft_id}",
            headers={**headers, "If-Match": "1"},
            json={
                "shift_type": "FIXED",
                "effective_from": "2026-08-10",
                "start_time": "09:00",
                "end_time": "18:00",
            },
        )
        published = await client.post(
            f"/v1/shifts/{shift['id']}/versions/{draft_id}/publish",
            headers={**headers, "If-Match": "2"},
            json={},
        )
        assert published.status_code == 409, published.text
        assert published.json()["error"]["code"] == "ATTENDANCE_PERIOD_CLOSED"
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup_period(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_shift_version_publish_open_period_unaffected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Regression guard: an `effective_from` outside any closed period publishes exactly as
    before this phase — the ordinary case in every other shift-version test remains untouched."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = await _create_shift(client, headers)
        draft_id = shift["draft_version_id"]
        await client.patch(
            f"/v1/shifts/{shift['id']}/versions/{draft_id}",
            headers={**headers, "If-Match": "1"},
            json={
                "shift_type": "FIXED",
                "effective_from": "2026-01-01",
                "start_time": "09:00",
                "end_time": "18:00",
            },
        )
        published = await client.post(
            f"/v1/shifts/{shift['id']}/versions/{draft_id}/publish",
            headers={**headers, "If-Match": "2"},
            json={},
        )
        assert published.status_code == 200, published.text
    finally:
        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
