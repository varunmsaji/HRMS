"""H-04 through the real API: which policy a rostered day off resolves.

The wired employee is assigned a FIXED shift and has a COMPANY-scoped attendance policy. A
published roster week-off row carries no shift, so before H-04 the day skipped its SHIFT scope and a
broader scope decided. Now the SHIFT scope is the assigned shift. Precedence is untouched: EMPLOYEE
outranks SHIFT, SHIFT outranks DEPARTMENT. With no assigned shift there is no SHIFT scope and
resolution falls through to the next scope. 2026-08-10 is the rostered day off.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.test_attendance_day import (
    _build_wired_employee,
    _punch,
    _register_tenant,
)
from tests.integration.modules.attendance.test_attendance_policy import (
    _cleanup_attendance,
    _create_policy,
)
from tests.integration.modules.attendance.test_attendance_rules_remediation import (
    MON,
    _calc,
    _cleanup_all,
    _stored,
)
from tests.integration.modules.attendance.test_hour_band_publication import GOOD, _draft, _publish
from tests.integration.modules.attendance.test_shift_roster import _publish_roster
from tests.integration.modules.attendance.test_shift_window import _sql

from hrms.core.db.session import get_session_factory, set_rls_company_id

pytestmark = pytest.mark.asyncio


async def _scoped_policy(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    name: str,
    scope_type: str,
    scope_id: str,
) -> str:
    """A published attendance policy assigned to one scope; returns its (only) version id."""
    policy = await _create_policy(client, headers, name=name)
    draft = await _draft(client, headers, policy["id"], hour_bands=GOOD)
    published = await _publish(client, headers, policy["id"], draft)
    assert published.status_code == 200, published.text
    assigned = await client.post(
        "/v1/policy-assignments",
        headers=headers,
        json={
            "policy_kind": "ATTENDANCE_POLICY",
            "policy_id": policy["id"],
            "scope_type": scope_type,
            "scope_id": scope_id,
            "effective_from": "2026-01-01",
        },
    )
    assert assigned.status_code == 201, assigned.text
    return str(draft["id"])


async def _department_id(client: AsyncClient, headers: dict[str, str]) -> str:
    listed = await client.get("/v1/departments", headers=headers)
    return str(listed.json()["data"][0]["id"])


async def _rostered_off(client: AsyncClient, headers: dict[str, str], employee_id: str) -> None:
    await _publish_roster(
        client,
        headers,
        {"employee_id": employee_id, "roster_date": MON, "is_week_off_override": True},
    )


async def test_a_rostered_day_off_resolves_the_assigned_shifts_policy_with_and_without_punches(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id, shift_id = str(wired["employee"]["id"]), str(wired["shift"]["id"])
        shift_version = await _scoped_policy(
            client, headers, name="Shift policy", scope_type="SHIFT", scope_id=shift_id
        )
        await _rostered_off(client, headers, employee_id)

        quiet = await _calc(client, headers, employee_id, MON)
        assert quiet["attendance_status"] == "NOT_EXPECTED"
        assert quiet["attendance_policy_version_id"] == shift_version

        await _punch(client, headers, employee_id=employee_id, hour=10, minute=0, direction="IN")
        await _punch(client, headers, employee_id=employee_id, hour=14, minute=0, direction="OUT")
        worked = await _calc(client, headers, employee_id, MON)
        assert worked["attendance_policy_version_id"] == shift_version
    finally:
        await _cleanup_attendance(company_id=company_id)
        await _cleanup_all(company_id, user_id)


async def test_a_working_day_resolves_the_same_shift_policy_so_the_off_day_now_matches(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Control: on an ordinary day the SHIFT scope was already the assigned shift."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id, shift_id = str(wired["employee"]["id"]), str(wired["shift"]["id"])
        shift_version = await _scoped_policy(
            client, headers, name="Shift policy", scope_type="SHIFT", scope_id=shift_id
        )
        await _punch(
            client,
            headers,
            employee_id=employee_id,
            hour=9,
            minute=0,
            direction="IN",
            day="2026-08-11",
        )
        await _punch(
            client,
            headers,
            employee_id=employee_id,
            hour=18,
            minute=0,
            direction="OUT",
            day="2026-08-11",
        )
        day = await _calc(client, headers, employee_id, "2026-08-11")
        assert day["attendance_policy_version_id"] == shift_version
    finally:
        await _cleanup_attendance(company_id=company_id)
        await _cleanup_all(company_id, user_id)


async def test_a_department_policy_does_not_override_the_shift_policy_on_a_day_off(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id, shift_id = str(wired["employee"]["id"]), str(wired["shift"]["id"])
        await _scoped_policy(
            client,
            headers,
            name="Department policy",
            scope_type="DEPARTMENT",
            scope_id=await _department_id(client, headers),
        )
        shift_version = await _scoped_policy(
            client, headers, name="Shift policy", scope_type="SHIFT", scope_id=shift_id
        )
        await _rostered_off(client, headers, employee_id)
        day = await _calc(client, headers, employee_id, MON)
        assert day["attendance_policy_version_id"] == shift_version
    finally:
        await _cleanup_attendance(company_id=company_id)
        await _cleanup_all(company_id, user_id)


async def test_an_employee_policy_still_outranks_the_shift_policy_on_a_day_off(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id, shift_id = str(wired["employee"]["id"]), str(wired["shift"]["id"])
        await _scoped_policy(
            client, headers, name="Shift policy", scope_type="SHIFT", scope_id=shift_id
        )
        employee_version = await _scoped_policy(
            client, headers, name="Employee policy", scope_type="EMPLOYEE", scope_id=employee_id
        )
        await _rostered_off(client, headers, employee_id)
        day = await _calc(client, headers, employee_id, MON)
        assert day["attendance_policy_version_id"] == employee_version
    finally:
        await _cleanup_attendance(company_id=company_id)
        await _cleanup_all(company_id, user_id)


async def test_with_no_assigned_shift_the_day_off_falls_through_to_the_next_scope(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id, shift_id = str(wired["employee"]["id"]), str(wired["shift"]["id"])
        await _scoped_policy(
            client, headers, name="Shift policy", scope_type="SHIFT", scope_id=shift_id
        )
        department_version = await _scoped_policy(
            client,
            headers,
            name="Department policy",
            scope_type="DEPARTMENT",
            scope_id=await _department_id(client, headers),
        )
        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(company_id))
            await session.execute(
                text(
                    "UPDATE employee_assignment SET shift_id = NULL "
                    "WHERE company_id = :cid AND employee_id = CAST(:eid AS uuid)"
                ),
                {"cid": str(company_id), "eid": employee_id},
            )
            await session.commit()
        await _rostered_off(client, headers, employee_id)
        day = await _calc(client, headers, employee_id, MON)
        assert day["attendance_policy_version_id"] == department_version  # no SHIFT scope
    finally:
        await _cleanup_attendance(company_id=company_id)
        await _cleanup_all(company_id, user_id)


async def test_a_day_off_with_no_resolvable_configuration_is_paid_and_does_not_block_the_close(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = str(wired["employee"]["id"])
        await _rostered_off(client, headers, employee_id)
        # take every attendance policy assignment away: nothing resolves any more
        await _sql(
            company_id,
            "DELETE FROM policy_assignment WHERE company_id = :cid "
            "AND policy_kind = 'ATTENDANCE_POLICY'",
        )
        day: dict[str, Any] = await _calc(client, headers, employee_id, MON)
        assert day["attendance_status"] == "NOT_EXPECTED"
        assert (day["paid_day_fraction"], day["lop_fraction"]) == ("1.00", "0.00")
        stored = await _stored(client, headers, employee_id, MON)
        assert stored["attendance_status"] == "NOT_EXPECTED"

        from tests.integration.modules.attendance.test_attendance_period import _create_period

        period = await _create_period(client, headers, period_start=MON, period_end=MON)
        finalized = await client.post(
            f"/v1/attendance-periods/{period['id']}/finalize",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert finalized.status_code == 200, finalized.text
    finally:
        await _cleanup_attendance(company_id=company_id)
        await _cleanup_all(company_id, user_id)
