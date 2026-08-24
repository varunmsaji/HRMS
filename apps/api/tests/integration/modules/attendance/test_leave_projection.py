"""Integration tests for W9 — `/v1/leave-projections*`, the Leave -> Attendance adapter
(architecture §21, decision log WD-31).

Reuses `_build_wired_employee`/`_punch`/`_register_tenant`/`_cleanup_attendance_day` from
`test_attendance_day.py`, `_create_permission_scoped_user`/`_cleanup_scoped_users` from
`test_attendance_security.py`, `_create_regularization_policy`/`_cleanup_regularization`/
`_requested_punches` from `test_regularization.py`, and `_create_period`/`_insert_closed_period`/
`_cleanup_attendance_period` from `test_attendance_period.py` — the same cross-file reuse pattern
every W6/W7/W8 test file already established. Real Postgres, real RLS, real HTTP through the ASGI
app, not `TestClient`.
"""

from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.test_attendance_day import (
    _build_wired_employee,
    _cleanup_attendance_day,
    _punch,
    _register_tenant,
)
from tests.integration.modules.attendance.test_attendance_period import (
    _cleanup_attendance_period,
    _create_period,
    _insert_closed_period,
)
from tests.integration.modules.attendance.test_attendance_security import (
    _cleanup_scoped_users,
    _create_permission_scoped_user,
)
from tests.integration.modules.attendance.test_regularization import (
    _cleanup_regularization,
    _create_regularization_policy,
    _requested_punches,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.core.db.session import get_session_factory, set_rls_company_id

pytestmark = pytest.mark.asyncio

_DAY = "2026-08-10"


async def _cleanup_leave_projection(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        await session.execute(
            text("DELETE FROM leave_day_projection WHERE company_id = :cid"),
            {"cid": str(company_id)},
        )
        await session.commit()


async def _sync(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    employee_id: str,
    fraction: str = "1.00",
    is_paid: bool = True,
    half: str | None = None,
    day: str = _DAY,
    leave_application_id: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "employee_id": employee_id,
        "attendance_date": day,
        "leave_application_id": leave_application_id or str(uuid4()),
        "fraction": fraction,
        "half": half,
        "is_paid": is_paid,
        **extra,
    }
    response = await client.post("/v1/leave-projections", headers=headers, json=body)
    return response


async def _get_day(
    client: AsyncClient, headers: dict[str, str], *, employee_id: str
) -> dict[str, Any]:
    response = await client.get(
        "/v1/attendance/days",
        headers=headers,
        params={"employee_id": employee_id, "date_from": _DAY, "date_to": _DAY},
    )
    assert response.status_code == 200, response.text
    rows = response.json()["data"]
    assert len(rows) == 1
    return dict(rows[0])


async def _build_wired_employee_with_leave_behaviour(
    client: AsyncClient, headers: dict[str, str], *, behaviour: str
) -> dict[str, Any]:
    """`_build_wired_employee` plus a second, later-effective `AttendancePolicyVersion` on the
    same policy identity with `work_on_leave_behaviour` overridden — avoids a second COMPANY-scope
    policy assignment (which would overlap the first one `_build_wired_employee` already made)."""
    wired = await _build_wired_employee(client, headers)
    policies = (await client.get("/v1/attendance-policies", headers=headers)).json()["data"]
    policy = next(p for p in policies if p["name"] == "Standard Policy")
    second_draft = (
        await client.post(
            f"/v1/attendance-policies/{policy['id']}/versions",
            headers=headers,
            json={
                "effective_from": "2026-08-01",
                "work_on_leave_behaviour": behaviour,
                "hour_bands": [
                    {"min_minutes": 0, "max_minutes": 239, "result_status": "ABSENT"},
                    {"min_minutes": 240, "max_minutes": None, "result_status": "PRESENT"},
                ],
            },
        )
    ).json()["data"]
    publish = await client.post(
        f"/v1/attendance-policies/{policy['id']}/versions/{second_draft['id']}/publish",
        headers={**headers, "If-Match": "1"},
        json={"expected_previous_version": 2},
    )
    assert publish.status_code == 200, publish.text
    return wired


# ---------------------------------------------------------------------------
# Projection contract
# ---------------------------------------------------------------------------


async def test_sync_full_day_paid_leave_no_punches(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]

        response = await _sync(
            client, headers, employee_id=employee_id, fraction="1.00", is_paid=True
        )
        assert response.status_code == 201, response.text
        assert response.json()["data"]["status"] == "APPROVED"

        day = await _get_day(client, headers, employee_id=employee_id)
        assert day["attendance_status"] == "LEAVE"
        assert day["paid_day_fraction"] == "1.00"
        assert day["lop_fraction"] == "0.00"
        assert day["late_minutes"] == 0
    finally:
        await _cleanup_leave_projection(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_sync_full_day_unpaid_leave_no_punches(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]

        await _sync(client, headers, employee_id=employee_id, fraction="1.00", is_paid=False)
        day = await _get_day(client, headers, employee_id=employee_id)
        assert day["attendance_status"] == "LEAVE"
        assert day["paid_day_fraction"] == "0.00"
        assert day["lop_fraction"] == "1.00"
    finally:
        await _cleanup_leave_projection(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_sync_half_day_paid_leave_no_punches(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]

        await _sync(
            client, headers, employee_id=employee_id, fraction="0.50", half="FIRST", is_paid=True
        )
        day = await _get_day(client, headers, employee_id=employee_id)
        assert day["attendance_status"] == "LEAVE"
        assert day["paid_day_fraction"] == "0.50"
        assert day["lop_fraction"] == "0.50"
    finally:
        await _cleanup_leave_projection(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_multiple_half_day_projections_sum_to_full_day(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Two independent half-day leave applications (AM paid, PM unpaid) covering the same date —
    §21's "multiple leave projections" case; fractions add, paid/unpaid mix per entry."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]

        await _sync(
            client, headers, employee_id=employee_id, fraction="0.50", half="FIRST", is_paid=True
        )
        await _sync(
            client, headers, employee_id=employee_id, fraction="0.50", half="SECOND", is_paid=False
        )
        day = await _get_day(client, headers, employee_id=employee_id)
        assert day["attendance_status"] == "LEAVE"
        assert day["paid_day_fraction"] == "0.50"
        assert day["lop_fraction"] == "0.50"
    finally:
        await _cleanup_leave_projection(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_invalid_fraction_rejected(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        response = await _sync(
            client, headers, employee_id=wired["employee"]["id"], fraction="0.75", half="FIRST"
        )
        assert response.status_code == 422, response.text
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_half_required_for_half_day_fraction(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        response = await _sync(
            client, headers, employee_id=wired["employee"]["id"], fraction="0.50", half=None
        )
        assert response.status_code == 422, response.text
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_overlapping_leave_fractions_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        first = await _sync(client, headers, employee_id=employee_id, fraction="0.50", half="FIRST")
        assert first.status_code == 201, first.text

        overlapping = await _sync(client, headers, employee_id=employee_id, fraction="1.00")
        assert overlapping.status_code == 409, overlapping.text
        assert overlapping.json()["error"]["code"] == "LEAVE_PROJECTION_OVERLAP"
    finally:
        await _cleanup_leave_projection(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_forged_employee_id_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await _sync(client, headers, employee_id=str(uuid4()))
        assert response.status_code == 404, response.text
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_cross_tenant_projection_returns_404(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers_a)
        synced = await _sync(client, headers_a, employee_id=wired["employee"]["id"])
        assert synced.status_code == 201, synced.text
        projection_id = synced.json()["data"]["id"]

        response = await client.get(f"/v1/leave-projections/{projection_id}", headers=headers_b)
        assert response.status_code == 404, response.text

        # Also: an employee_id that is real, but belongs to the *other* tenant, is rejected the
        # same way a forged/nonexistent id is (404, never 403 or a cross-tenant write).
        cross_tenant_sync = await _sync(client, headers_b, employee_id=wired["employee"]["id"])
        assert cross_tenant_sync.status_code == 404, cross_tenant_sync.text
    finally:
        await _cleanup_leave_projection(company_id=company_a)
        await _cleanup_attendance_day(company_id=company_a)
        await _cleanup(company_id=company_a, user_id=user_a)
        await _cleanup(company_id=company_b, user_id=user_b)


# ---------------------------------------------------------------------------
# Attendance calculation integration
# ---------------------------------------------------------------------------


async def test_half_day_unpaid_leave_with_full_day_punches(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Architecture §19.4's own worked example: half-day unpaid leave + the other half worked ->
    `paid_day_fraction=0.50`, `lop_fraction=0.50` (the unpaid leave half contributes to LOP, the
    worked half contributes to paid)."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _punch(client, headers, employee_id=employee_id, hour=9, minute=0, direction="IN")
        await _punch(client, headers, employee_id=employee_id, hour=18, minute=0, direction="OUT")

        await _sync(
            client, headers, employee_id=employee_id, fraction="0.50", half="FIRST", is_paid=False
        )
        day = await _get_day(client, headers, employee_id=employee_id)
        assert day["attendance_status"] == "HALF_DAY"
        assert day["paid_day_fraction"] == "0.50"
        assert day["lop_fraction"] == "0.50"
    finally:
        await _cleanup_leave_projection(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_full_day_leave_keep_leave_behaviour_overrides_punches(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Default policy `work_on_leave_behaviour=KEEP_LEAVE` — a full day of punches despite
    approved full-day leave does not cancel the leave; `attendance_status` stays `LEAVE`."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _sync(client, headers, employee_id=employee_id, fraction="1.00", is_paid=True)

        await _punch(client, headers, employee_id=employee_id, hour=9, minute=0, direction="IN")
        await _punch(client, headers, employee_id=employee_id, hour=18, minute=0, direction="OUT")
        recompute = await client.post(
            "/v1/attendance/days/calculate",
            headers=headers,
            params={"employee_id": employee_id, "date": _DAY},
        )
        assert recompute.status_code == 200, recompute.text
        assert recompute.json()["data"]["attendance_status"] == "LEAVE"
        assert recompute.json()["data"]["work_on_leave_flagged"] is False
        assert recompute.json()["data"]["late_minutes"] == 0
    finally:
        await _cleanup_leave_projection(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_full_day_leave_present_cancel_hint_flags_and_keeps_punch_status(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`work_on_leave_behaviour=PRESENT_CANCEL_LEAVE_HINT` — the punch-derived outcome (PRESENT)
    wins, and `work_on_leave_flagged` is raised for Leave to see. Attendance never cancels the
    leave application itself (architecture §19.3)."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee_with_leave_behaviour(
            client, headers, behaviour="PRESENT_CANCEL_LEAVE_HINT"
        )
        employee_id = wired["employee"]["id"]
        await _sync(client, headers, employee_id=employee_id, fraction="1.00", is_paid=True)

        await _punch(client, headers, employee_id=employee_id, hour=9, minute=0, direction="IN")
        await _punch(client, headers, employee_id=employee_id, hour=18, minute=0, direction="OUT")
        recompute = await client.post(
            "/v1/attendance/days/calculate",
            headers=headers,
            params={"employee_id": employee_id, "date": _DAY},
        )
        assert recompute.status_code == 200, recompute.text
        data = recompute.json()["data"]
        assert data["attendance_status"] == "PRESENT"
        assert data["work_on_leave_flagged"] is True
    finally:
        await _cleanup_leave_projection(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_leave_overrides_roster_week_off_not_expected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """§19.4's precedence lists full-day LEAVE above calendar `NOT_EXPECTED` — an approved leave
    projection wins over a roster week-off day, without touching `calendar_day_type`."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]

        roster = await client.post(
            "/v1/rosters",
            headers=headers,
            json={"employee_id": employee_id, "roster_date": _DAY, "is_week_off_override": True},
        )
        assert roster.status_code == 201, roster.text
        await client.post(
            f"/v1/rosters/{roster.json()['data']['id']}/publish",
            headers={**headers, "If-Match": "1"},
            json={},
        )

        await _sync(client, headers, employee_id=employee_id, fraction="1.00", is_paid=True)
        day = await _get_day(client, headers, employee_id=employee_id)
        assert day["attendance_status"] == "LEAVE"
        # calendar_day_type is untouched by the overlay — this is still a WORKING-calendar day,
        # only the roster week-off + leave together changed `attendance_status`.
        assert day["calendar_day_type"] != "LEAVE"
    finally:
        await _cleanup_leave_projection(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_leave_plus_auto_regularization_recompute_keeps_leave_status(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Regularization applies as synthetic punches then calls the same `calculate()` (WD-28) —
    the leave overlay applies identically regardless of what triggered the recompute."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _create_regularization_policy(client, headers, approval_chain="AUTO")
        await _sync(client, headers, employee_id=employee_id, fraction="1.00", is_paid=True)

        created = await client.post(
            "/v1/regularizations",
            headers=headers,
            json={
                "employee_id": employee_id,
                "attendance_date": _DAY,
                "request_type": "MISSING_PUNCH",
                "reason": "x",
                "requested_punches": _requested_punches(_DAY),
            },
        )
        assert created.status_code == 201, created.text
        assert created.json()["data"]["status"] == "APPROVED"

        day = await _get_day(client, headers, employee_id=employee_id)
        assert day["attendance_status"] == "LEAVE"
    finally:
        await _cleanup_regularization(company_id=company_id)
        await _cleanup_leave_projection(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# ---------------------------------------------------------------------------
# Recalculation / historical correctness
# ---------------------------------------------------------------------------


async def test_cancel_projection_reverts_attendance_to_punch_derived_outcome(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _punch(client, headers, employee_id=employee_id, hour=9, minute=0, direction="IN")
        await _punch(client, headers, employee_id=employee_id, hour=18, minute=0, direction="OUT")

        synced = await _sync(
            client, headers, employee_id=employee_id, fraction="1.00", is_paid=True
        )
        projection_id = synced.json()["data"]["id"]
        day = await _get_day(client, headers, employee_id=employee_id)
        assert day["attendance_status"] == "LEAVE"

        cancelled = await client.post(
            f"/v1/leave-projections/{projection_id}/cancel",
            headers={**headers, "If-Match": "1"},
            json={"reason": "employee withdrew the application"},
        )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["data"]["status"] == "CANCELLED"

        day_after = await _get_day(client, headers, employee_id=employee_id)
        assert day_after["attendance_status"] == "PRESENT"
        assert day_after["paid_day_fraction"] == "1.00"
    finally:
        await _cleanup_leave_projection(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_resync_same_leave_application_id_updates_in_place(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        application_id = str(uuid4())

        await _sync(
            client,
            headers,
            employee_id=employee_id,
            fraction="1.00",
            is_paid=True,
            leave_application_id=application_id,
        )
        day = await _get_day(client, headers, employee_id=employee_id)
        assert day["paid_day_fraction"] == "1.00"

        resynced = await _sync(
            client,
            headers,
            employee_id=employee_id,
            fraction="1.00",
            is_paid=False,
            leave_application_id=application_id,
        )
        assert resynced.status_code == 201, resynced.text

        listed = await client.get(
            "/v1/leave-projections",
            headers=headers,
            params={"employee_id": employee_id, "date_from": _DAY, "date_to": _DAY},
        )
        assert len(listed.json()["data"]) == 1

        day_after = await _get_day(client, headers, employee_id=employee_id)
        assert day_after["paid_day_fraction"] == "0.00"
        assert day_after["lop_fraction"] == "1.00"
    finally:
        await _cleanup_leave_projection(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# ---------------------------------------------------------------------------
# Locking (W8 contract, PD-LOCK-2)
# ---------------------------------------------------------------------------


async def test_sync_refused_when_period_closed(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        await _insert_closed_period(company_id=company_id)

        response = await _sync(client, headers, employee_id=wired["employee"]["id"])
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "ATTENDANCE_PERIOD_CLOSED"
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_leave_projection(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_cancel_refused_when_period_closed(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """§21 — "Leave approved after payroll lock... default refuse" applies symmetrically to
    cancellation; the only correction path for a locked date is a full period reopen (PD-LOCK-2,
    matching W8's own scope boundary — no arrears mechanism exists yet)."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        synced = await _sync(client, headers, employee_id=employee_id, fraction="1.00")
        projection_id = synced.json()["data"]["id"]

        await _insert_closed_period(company_id=company_id)
        cancelled = await client.post(
            f"/v1/leave-projections/{projection_id}/cancel",
            headers={**headers, "If-Match": "1"},
            json={"reason": "too late"},
        )
        assert cancelled.status_code == 409, cancelled.text
        assert cancelled.json()["error"]["code"] == "ATTENDANCE_PERIOD_CLOSED"
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_leave_projection(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# ---------------------------------------------------------------------------
# Payroll-facing facts (AttendancePeriodSummary)
# ---------------------------------------------------------------------------


async def test_period_summary_reflects_leave_days_and_lop(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _sync(client, headers, employee_id=employee_id, fraction="1.00", is_paid=False)

        period = await _create_period(client, headers, period_start=_DAY, period_end=_DAY)
        finalized = await client.post(
            f"/v1/attendance-periods/{period['id']}/finalize",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert finalized.status_code == 200, finalized.text

        summary = await client.get(
            f"/v1/attendance-periods/{period['id']}/summary", headers=headers
        )
        assert summary.status_code == 200, summary.text
        row = next(r for r in summary.json()["data"] if r["employee_id"] == employee_id)
        assert row["leave_days"] == "1.00"
        assert row["lop_days"] == "1.00"
        assert row["frozen"] is True
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_leave_projection(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------


async def test_self_scope_sees_only_own_leave_projections(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    from hrms.modules.attendance.permissions import ATTENDANCE_VIEW

    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        self_employee_id = wired["employee"]["id"]
        await _sync(client, headers, employee_id=self_employee_id, fraction="1.00")

        other_employee_id = (
            await client.post("/v1/employees", headers=headers, json={"first_name": "Chetan"})
        ).json()["data"]["id"]
        await _sync(client, headers, employee_id=other_employee_id, fraction="1.00")

        scoped_headers, _ = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[ATTENDANCE_VIEW],
            data_scope="SELF",
            caller_employee_id=UUID(self_employee_id),
        )
        listed = await client.get("/v1/leave-projections", headers=scoped_headers)
        assert listed.status_code == 200, listed.text
        seen_employee_ids = {row["employee_id"] for row in listed.json()["data"]}
        assert seen_employee_ids == {self_employee_id}
    finally:
        await _cleanup_leave_projection(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_sync_without_permission_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        scoped_headers, _ = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=[], data_scope="COMPANY"
        )
        response = await _sync(client, scoped_headers, employee_id=wired["employee"]["id"])
        assert response.status_code == 403, response.text
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_cancel_stale_version_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        synced = await _sync(client, headers, employee_id=employee_id, fraction="1.00")
        projection_id = synced.json()["data"]["id"]

        response = await client.post(
            f"/v1/leave-projections/{projection_id}/cancel",
            headers={**headers, "If-Match": "99"},
            json={"reason": "stale attempt"},
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "STALE_RESOURCE"
    finally:
        await _cleanup_leave_projection(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
