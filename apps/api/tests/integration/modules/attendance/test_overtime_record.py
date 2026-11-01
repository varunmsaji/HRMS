"""Integration tests for W7 — `/v1/overtime*` (architecture §12, decision log WD-29).

Reuses `_build_wired_employee`/`_punch`/`_register_tenant`/`_cleanup_attendance_day` from
`test_attendance_day.py` and `_add_reportee_employee`/`_create_permission_scoped_user`/
`_cleanup_scoped_users` from `test_attendance_security.py`, the same cross-file reuse pattern
`test_regularization.py` already established. `_build_wired_employee`'s shift has
`is_ot_eligible=False` (never patched to `True` by that shared helper), so every OT policy
version created here uses `eligibility="ALWAYS"` to bypass the shift flag rather than reaching
into shared setup.
"""

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
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

from hrms.core.db.session import get_session_factory, set_rls_company_id

pytestmark = pytest.mark.asyncio


async def _create_overtime_policy(
    client: AsyncClient, headers: dict[str, str], **version_overrides: Any
) -> dict[str, Any]:
    policy = (
        await client.post("/v1/overtime-policies", headers=headers, json={"name": "Standard OT"})
    ).json()["data"]
    body: dict[str, Any] = {
        "effective_from": "2026-01-01",
        "eligibility": "ALWAYS",
        "min_ot_minutes": 0,
        "approval_chain": "MANAGER",
        "requires_post_approval": True,
        **version_overrides,
    }
    draft = (
        await client.post(
            f"/v1/overtime-policies/{policy['id']}/versions", headers=headers, json=body
        )
    ).json()["data"]
    published = await client.post(
        f"/v1/overtime-policies/{policy['id']}/versions/{draft['id']}/publish",
        headers={**headers, "If-Match": "1"},
        json={},
    )
    assert published.status_code == 200, published.text

    assignment = await client.post(
        "/v1/policy-assignments",
        headers=headers,
        json={
            "policy_kind": "OVERTIME_POLICY",
            "policy_id": policy["id"],
            "scope_type": "COMPANY",
            "effective_from": "2026-01-01",
        },
    )
    assert assignment.status_code == 201, assignment.text
    return policy


async def _cleanup_overtime(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        for table in (
            "overtime_action",
            "overtime_record",
            "overtime_policy_version",
            "overtime_policy",
        ):
            await session.execute(
                text(f"DELETE FROM {table} WHERE company_id = :cid"), {"cid": str(company_id)}
            )
        await session.commit()


async def _ot_calculate_day(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    employee_id: str,
    day: str = "2026-08-10",
    out_hour: int = 19,
) -> dict[str, Any]:
    """09:00-`out_hour`:00 against the shared 09:00-18:00 shift — 600m worked (at the default
    `out_hour=19`) against 540m scheduled, i.e. 60m excess before any threshold/rounding/cap.
    The punch-load window is `[scheduled_start-2h, scheduled_end+2h)` — `out_hour` must stay
    strictly below 20 (18:00 + 2h) or the OUT punch falls outside the window entirely."""
    await _punch(
        client, headers, employee_id=employee_id, hour=9, minute=0, direction="IN", day=day
    )
    await _punch(
        client, headers, employee_id=employee_id, hour=out_hour, minute=0, direction="OUT", day=day
    )
    response = await client.post(
        "/v1/attendance/days/calculate",
        headers=headers,
        params={"employee_id": employee_id, "date": day},
    )
    assert response.status_code == 200, response.text
    return dict(response.json()["data"])


async def _get_overtime_record_for_day(
    client: AsyncClient, headers: dict[str, str], *, employee_id: str, day: str
) -> dict[str, Any]:
    listed = await client.get(
        "/v1/overtime",
        headers=headers,
        params={"employee_id": employee_id, "date_from": day, "date_to": day},
    )
    assert listed.status_code == 200, listed.text
    rows = listed.json()["data"]
    assert len(rows) == 1, rows
    return dict(rows[0])


# ---------------------------------------------------------------------------
# Detection + policy resolution wiring
# ---------------------------------------------------------------------------


async def test_overtime_policy_resolves_and_day_snapshots_version(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        policy = await _create_overtime_policy(client, headers, approval_chain="AUTO")

        day = await _ot_calculate_day(client, headers, employee_id=employee_id)
        assert day["ot_minutes_detected"] == 60
        assert day["is_overtime"] is True

        record = await _get_overtime_record_for_day(
            client, headers, employee_id=employee_id, day="2026-08-10"
        )
        assert record["overtime_policy_version_id"] is not None
        assert record["minutes_detected"] == 60
        assert record["day_class"] == "NORMAL"
        assert policy["id"] is not None  # policy identity created successfully
    finally:
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_daily_threshold_and_rounding_applied(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _create_overtime_policy(
            client,
            headers,
            approval_chain="AUTO",
            min_ot_minutes=30,
            rounding_minutes=30,
            rounding_mode="DOWN",
        )
        # 09:00-19:20 -> 620m worked, 80m excess -> above the 30m threshold, rounds down to 60m.
        await _punch(client, headers, employee_id=employee_id, hour=9, minute=0, direction="IN")
        await _punch(client, headers, employee_id=employee_id, hour=19, minute=20, direction="OUT")
        day = (
            await client.post(
                "/v1/attendance/days/calculate",
                headers=headers,
                params={"employee_id": employee_id, "date": "2026-08-10"},
            )
        ).json()["data"]
        assert day["ot_minutes_detected"] == 60
    finally:
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# ---------------------------------------------------------------------------
# Approval chains
# ---------------------------------------------------------------------------


async def test_auto_chain_auto_approves_immediately(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _create_overtime_policy(client, headers, approval_chain="AUTO")

        day = await _ot_calculate_day(client, headers, employee_id=employee_id)
        assert day["ot_minutes_approved"] == 60
        assert day["ot_pending"] is False

        record = await _get_overtime_record_for_day(
            client, headers, employee_id=employee_id, day="2026-08-10"
        )
        assert record["status"] == "AUTO_APPROVED"
        assert record["minutes_approved"] == 60
        assert any(a["action"] == "AUTO_APPROVED" for a in record["actions"])
    finally:
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_requires_post_approval_false_auto_approves_without_auto_chain(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`approval_chain=MANAGER` but `requires_post_approval=False` also auto-approves — no
    reviewer is ever needed if the policy itself says review isn't required."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _create_overtime_policy(
            client, headers, approval_chain="MANAGER", requires_post_approval=False
        )

        day = await _ot_calculate_day(client, headers, employee_id=employee_id)
        assert day["ot_minutes_approved"] == 60
        assert day["ot_pending"] is False

        record = await _get_overtime_record_for_day(
            client, headers, employee_id=employee_id, day="2026-08-10"
        )
        assert record["status"] == "AUTO_APPROVED"
    finally:
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_manager_chain_pending_then_approved_updates_day(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
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
        employee_id = reportee["id"]
        await _create_overtime_policy(client, headers, approval_chain="MANAGER")

        day = await _ot_calculate_day(client, headers, employee_id=employee_id)
        assert day["ot_minutes_detected"] == 60
        assert day["ot_minutes_approved"] == 0
        assert day["ot_pending"] is True

        record = await _get_overtime_record_for_day(
            client, headers, employee_id=employee_id, day="2026-08-10"
        )
        assert record["status"] == "PENDING"
        assert record["approval_stage"] == "MANAGER"
        assert record["resolved_approver_manager_id"] == manager_id

        from hrms.modules.attendance.permissions import ATTENDANCE_OVERTIME_APPROVE

        manager_headers, _ = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[ATTENDANCE_OVERTIME_APPROVE],
            data_scope="REPORTEES",
            caller_employee_id=UUID(manager_id),
        )
        approved = await client.post(
            f"/v1/overtime/{record['id']}/approve",
            headers={**manager_headers, "If-Match": str(record["version"])},
            json={"reviewer_comment": "Confirmed with client site"},
        )
        assert approved.status_code == 200, approved.text
        approved_data = approved.json()["data"]
        assert approved_data["status"] == "APPROVED"
        assert approved_data["minutes_approved"] == 60
        assert any(a["action"] == "APPROVED" for a in approved_data["actions"])

        day_after = (await client.get(f"/v1/attendance/days/{day['id']}", headers=headers)).json()[
            "data"
        ]
        assert day_after["ot_minutes_approved"] == 60
        assert day_after["ot_pending"] is False
    finally:
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_hr_chain_requires_company_scope(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _create_overtime_policy(client, headers, approval_chain="HR")

        day = await _ot_calculate_day(client, headers, employee_id=employee_id)
        record = await _get_overtime_record_for_day(
            client, headers, employee_id=employee_id, day="2026-08-10"
        )
        assert record["approval_stage"] == "HR"

        from hrms.modules.attendance.permissions import ATTENDANCE_OVERTIME_APPROVE

        hr_headers, _ = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[ATTENDANCE_OVERTIME_APPROVE],
            data_scope="COMPANY",
            caller_employee_id=None,
        )
        approved = await client.post(
            f"/v1/overtime/{record['id']}/approve",
            headers={**hr_headers, "If-Match": str(record["version"])},
            json={},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["data"]["status"] == "APPROVED"
        assert day["id"]  # sanity: day row exists
    finally:
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_manager_then_hr_two_stage_chain(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
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
        employee_id = reportee["id"]
        await _create_overtime_policy(client, headers, approval_chain="MANAGER_THEN_HR")

        await _ot_calculate_day(client, headers, employee_id=employee_id)
        record = await _get_overtime_record_for_day(
            client, headers, employee_id=employee_id, day="2026-08-10"
        )
        assert record["approval_stage"] == "MANAGER"

        from hrms.modules.attendance.permissions import ATTENDANCE_OVERTIME_APPROVE

        manager_headers, _ = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[ATTENDANCE_OVERTIME_APPROVE],
            data_scope="REPORTEES",
            caller_employee_id=UUID(manager_id),
        )
        stage1 = await client.post(
            f"/v1/overtime/{record['id']}/approve",
            headers={**manager_headers, "If-Match": str(record["version"])},
            json={"reviewer_comment": "Manager ok"},
        )
        assert stage1.status_code == 200, stage1.text
        stage1_data = stage1.json()["data"]
        assert stage1_data["status"] == "PENDING"
        assert stage1_data["approval_stage"] == "HR"
        assert any(a["action"] == "STAGE_APPROVED" for a in stage1_data["actions"])

        # Manager cannot also clear the HR stage.
        manager_retry = await client.post(
            f"/v1/overtime/{record['id']}/approve",
            headers={**manager_headers, "If-Match": str(stage1_data["version"])},
            json={},
        )
        assert manager_retry.status_code == 403, manager_retry.text

        hr_headers, _ = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[ATTENDANCE_OVERTIME_APPROVE],
            data_scope="COMPANY",
            caller_employee_id=None,
        )
        stage2 = await client.post(
            f"/v1/overtime/{record['id']}/approve",
            headers={**hr_headers, "If-Match": str(stage1_data["version"])},
            json={"reviewer_comment": "HR ok"},
        )
        assert stage2.status_code == 200, stage2.text
        assert stage2.json()["data"]["status"] == "APPROVED"
    finally:
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_no_manager_resolved_routes_to_hr(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]  # no reporting_manager_id set anywhere
        await _create_overtime_policy(client, headers, approval_chain="MANAGER")

        await _ot_calculate_day(client, headers, employee_id=employee_id)
        record = await _get_overtime_record_for_day(
            client, headers, employee_id=employee_id, day="2026-08-10"
        )
        assert record["approval_stage"] == "HR"
        assert record["resolved_approver_manager_id"] is None
        assert any(a["action"] == "APPROVER_UNRESOLVED" for a in record["actions"])
    finally:
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_reject_clears_day_fields(client: AsyncClient, seeded_plan_catalogue: None) -> None:
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
        employee_id = reportee["id"]
        await _create_overtime_policy(client, headers, approval_chain="MANAGER")

        await _ot_calculate_day(client, headers, employee_id=employee_id)
        record = await _get_overtime_record_for_day(
            client, headers, employee_id=employee_id, day="2026-08-10"
        )

        from hrms.modules.attendance.permissions import ATTENDANCE_OVERTIME_APPROVE

        manager_headers, _ = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[ATTENDANCE_OVERTIME_APPROVE],
            data_scope="REPORTEES",
            caller_employee_id=UUID(manager_id),
        )
        rejected = await client.post(
            f"/v1/overtime/{record['id']}/reject",
            headers={**manager_headers, "If-Match": str(record["version"])},
            json={"reviewer_comment": "Not authorized", "rejection_reason": "No prior approval"},
        )
        assert rejected.status_code == 200, rejected.text
        rejected_data = rejected.json()["data"]
        assert rejected_data["status"] == "REJECTED"
        assert rejected_data["minutes_approved"] == 0

        day_after = (
            await client.get(
                "/v1/attendance/days",
                headers=headers,
                params={
                    "employee_id": employee_id,
                    "date_from": "2026-08-10",
                    "date_to": "2026-08-10",
                },
            )
        ).json()["data"][0]
        assert day_after["ot_minutes_approved"] == 0
        assert day_after["ot_pending"] is False
        assert day_after["ot_minutes_detected"] == 60  # detection fact untouched
    finally:
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_self_approval_blocked(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _create_overtime_policy(client, headers, approval_chain="HR")
        await _ot_calculate_day(client, headers, employee_id=employee_id)
        record = await _get_overtime_record_for_day(
            client, headers, employee_id=employee_id, day="2026-08-10"
        )

        from hrms.modules.attendance.permissions import ATTENDANCE_OVERTIME_APPROVE

        self_headers, _ = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[ATTENDANCE_OVERTIME_APPROVE],
            data_scope="COMPANY",
            caller_employee_id=UUID(employee_id),
        )
        response = await client.post(
            f"/v1/overtime/{record['id']}/approve",
            headers={**self_headers, "If-Match": str(record["version"])},
            json={},
        )
        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "OVERTIME_SELF_APPROVAL_NOT_ALLOWED"
    finally:
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_wrong_manager_cannot_approve(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
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
        other_manager = await _add_reportee_employee(
            client, headers, wired=wired, first_name="OtherManager", reporting_manager_id=None
        )
        employee_id = reportee["id"]
        await _create_overtime_policy(client, headers, approval_chain="MANAGER")
        await _ot_calculate_day(client, headers, employee_id=employee_id)
        record = await _get_overtime_record_for_day(
            client, headers, employee_id=employee_id, day="2026-08-10"
        )

        from hrms.modules.attendance.permissions import ATTENDANCE_OVERTIME_APPROVE

        wrong_headers, _ = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[ATTENDANCE_OVERTIME_APPROVE],
            data_scope="COMPANY",
            caller_employee_id=UUID(other_manager["id"]),
        )
        response = await client.post(
            f"/v1/overtime/{record['id']}/approve",
            headers={**wrong_headers, "If-Match": str(record["version"])},
            json={},
        )
        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "OVERTIME_APPROVER_MISMATCH"
    finally:
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_stale_if_match_on_approve_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
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
        employee_id = reportee["id"]
        await _create_overtime_policy(client, headers, approval_chain="MANAGER")
        await _ot_calculate_day(client, headers, employee_id=employee_id)
        record = await _get_overtime_record_for_day(
            client, headers, employee_id=employee_id, day="2026-08-10"
        )

        from hrms.modules.attendance.permissions import ATTENDANCE_OVERTIME_APPROVE

        manager_headers, _ = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[ATTENDANCE_OVERTIME_APPROVE],
            data_scope="REPORTEES",
            caller_employee_id=UUID(manager_id),
        )
        stale = await client.post(
            f"/v1/overtime/{record['id']}/approve",
            headers={**manager_headers, "If-Match": str(record["version"] + 999)},
            json={},
        )
        assert stale.status_code == 409, stale.text
        assert stale.json()["error"]["code"] == "STALE_RESOURCE"
    finally:
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_simultaneous_approve_and_reject_only_one_wins(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
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
        employee_id = reportee["id"]
        await _create_overtime_policy(client, headers, approval_chain="MANAGER")
        await _ot_calculate_day(client, headers, employee_id=employee_id)
        record = await _get_overtime_record_for_day(
            client, headers, employee_id=employee_id, day="2026-08-10"
        )

        from hrms.modules.attendance.permissions import ATTENDANCE_OVERTIME_APPROVE

        manager_headers, _ = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[ATTENDANCE_OVERTIME_APPROVE],
            data_scope="REPORTEES",
            caller_employee_id=UUID(manager_id),
        )
        if_match = {"If-Match": str(record["version"])}
        approve_resp = await client.post(
            f"/v1/overtime/{record['id']}/approve",
            headers={**manager_headers, **if_match},
            json={},
        )
        reject_resp = await client.post(
            f"/v1/overtime/{record['id']}/reject",
            headers={**manager_headers, **if_match},
            json={"rejection_reason": "race"},
        )
        statuses = {approve_resp.status_code, reject_resp.status_code}
        assert statuses == {200, 409}, (approve_resp.status_code, reject_resp.status_code)

        final = await client.get(f"/v1/overtime/{record['id']}", headers=headers)
        final_status = final.json()["data"]["status"]
        assert final_status in ("APPROVED", "REJECTED")
        winner_status = 200
        if approve_resp.status_code == winner_status:
            assert final_status == "APPROVED"
        else:
            assert final_status == "REJECTED"
    finally:
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


# ---------------------------------------------------------------------------
# Terminal-record freeze across recompute (WD-29 decision 2)
# ---------------------------------------------------------------------------


async def test_approved_overtime_frozen_across_later_recompute(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Once approved, a later recompute of the same day (triggered here via the plain
    `/recompute` endpoint after an extra punch) must not silently revise the decided minutes —
    the day's `ot_minutes_approved` stays at the originally-approved amount even though fresh
    detection would now say something different."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _create_overtime_policy(client, headers, approval_chain="AUTO")

        day = await _ot_calculate_day(client, headers, employee_id=employee_id)
        assert day["ot_minutes_approved"] == 60
        record = await _get_overtime_record_for_day(
            client, headers, employee_id=employee_id, day="2026-08-10"
        )
        assert record["status"] == "AUTO_APPROVED"

        # An additional, later IN/OUT pair (still inside the [07:00, 20:00) punch-load window)
        # replaces nothing — punches are immutable — but gives the engine a longer total worked
        # span to detect on recompute. (A pre-shift pair would not do: time before the scheduled
        # start is recorded but not credited, so it cannot raise detected overtime.)
        await _punch(
            client,
            headers,
            employee_id=employee_id,
            hour=19,
            minute=10,
            direction="IN",
            day="2026-08-10",
        )
        await _punch(
            client,
            headers,
            employee_id=employee_id,
            hour=19,
            minute=50,
            direction="OUT",
            day="2026-08-10",
        )
        recomputed = await client.post(
            f"/v1/attendance/days/{day['id']}/recompute", headers=headers
        )
        assert recomputed.status_code == 200, recomputed.text
        recomputed_data = recomputed.json()["data"]
        # Fresh detection now sees more OT (640m worked - 540m scheduled = 100m)...
        assert recomputed_data["ot_minutes_detected"] == 100
        # ...but the frozen, terminal decision survives unchanged.
        assert recomputed_data["ot_minutes_approved"] == 60

        record_after = await _get_overtime_record_for_day(
            client, headers, employee_id=employee_id, day="2026-08-10"
        )
        assert record_after["id"] == record["id"]
        assert record_after["minutes_approved"] == 60
        assert record_after["status"] == "AUTO_APPROVED"
    finally:
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_pre_shift_presence_is_recorded_but_not_credited_or_overtime(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """End to end: IN 08:00 against the 09:00-18:00 shift, OUT 19:00. The punch keeps 08:00 and
    `actual_first_in` is 08:00, but credited work starts at 09:00 (600m), so overtime is the 60m
    after shift end — not 120m from the raw 11h presence."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _create_overtime_policy(client, headers, approval_chain="AUTO")
        await _punch(
            client,
            headers,
            employee_id=employee_id,
            hour=8,
            minute=0,
            direction="IN",
            day="2026-08-10",
        )
        await _punch(
            client,
            headers,
            employee_id=employee_id,
            hour=19,
            minute=0,
            direction="OUT",
            day="2026-08-10",
        )
        response = await client.post(
            "/v1/attendance/days/calculate",
            headers=headers,
            params={"employee_id": employee_id, "date": "2026-08-10"},
        )
        assert response.status_code == 200, response.text
        day = response.json()["data"]
        assert day["worked_minutes"] == 600
        assert day["ot_minutes_detected"] == 60
        assert day["actual_first_in"].startswith("2026-08-10T08:00:00")
        assert day["scheduled_start"].startswith("2026-08-10T09:00:00")

        punches = await client.get(
            "/v1/attendance/punches",
            headers=headers,
            params={"employee_id": employee_id, "date_from": "2026-08-10", "date_to": "2026-08-10"},
        )
        assert punches.status_code == 200, punches.text
        times = sorted(p["punch_time"] for p in punches.json()["data"])
        assert times[0].startswith("2026-08-10T08:00:00")  # the stored punch is untouched

        again = await client.post(
            "/v1/attendance/days/calculate",
            headers=headers,
            params={"employee_id": employee_id, "date": "2026-08-10"},
        )
        assert again.json()["data"]["worked_minutes"] == 600  # recalculation is reproducible
    finally:
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# ---------------------------------------------------------------------------
# Comp-off fact
# ---------------------------------------------------------------------------


async def test_comp_off_fact_with_expiry_on_auto_approval(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _create_overtime_policy(
            client,
            headers,
            approval_chain="AUTO",
            comp_off_instead_of_pay=True,
            comp_off_expiry_days=90,
        )
        day = await _ot_calculate_day(client, headers, employee_id=employee_id)
        assert day["comp_off_minutes_earned"] == 60

        record = await _get_overtime_record_for_day(
            client, headers, employee_id=employee_id, day="2026-08-10"
        )
        assert record["comp_off_minutes"] == 60
        assert record["comp_off_expiry_date"] == "2026-11-08"  # 2026-08-10 + 90 days
    finally:
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_comp_off_not_credited_to_day_while_pending(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
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
        employee_id = reportee["id"]
        await _create_overtime_policy(
            client,
            headers,
            approval_chain="MANAGER",
            comp_off_instead_of_pay=True,
            comp_off_expiry_days=30,
        )
        day = await _ot_calculate_day(client, headers, employee_id=employee_id)
        # Policy-computed fact is stored on the record even while pending...
        record = await _get_overtime_record_for_day(
            client, headers, employee_id=employee_id, day="2026-08-10"
        )
        assert record["comp_off_minutes"] == 60
        # ...but the day's payroll-facing summary is not credited until actually decided.
        assert day["comp_off_minutes_earned"] == 0
    finally:
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# ---------------------------------------------------------------------------
# Weekly cap across sibling days
# ---------------------------------------------------------------------------


async def test_weekly_cap_clamps_second_day_in_same_week(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _create_overtime_policy(client, headers, approval_chain="AUTO", weekly_cap_minutes=90)

        # 2026-08-10 (Mon) and 2026-08-11 (Tue) fall in the same ISO week. Each day's own raw
        # excess is 60m (see `_ot_calculate_day`); the weekly cap is set below 2x that so the
        # second day is provably clamped by the shared budget, not by its own daily detection.
        monday = await _ot_calculate_day(client, headers, employee_id=employee_id, day="2026-08-10")
        assert monday["ot_minutes_detected"] == 60

        tuesday = await _ot_calculate_day(
            client, headers, employee_id=employee_id, day="2026-08-11"
        )
        # Only 90 - 60 = 30m of weekly budget remains, even though 60m was detected again.
        assert tuesday["ot_minutes_detected"] == 30
    finally:
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# ---------------------------------------------------------------------------
# DataScope / security
# ---------------------------------------------------------------------------


async def test_self_scope_sees_only_own_overtime_record(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        self_employee_id = wired["employee"]["id"]
        other = await _add_reportee_employee(
            client, headers, wired=wired, first_name="Other", reporting_manager_id=None
        )
        await _create_overtime_policy(client, headers, approval_chain="AUTO")
        await _ot_calculate_day(client, headers, employee_id=self_employee_id)
        await _ot_calculate_day(client, headers, employee_id=other["id"], day="2026-08-11")

        from hrms.modules.attendance.permissions import ATTENDANCE_VIEW

        self_headers, _ = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[ATTENDANCE_VIEW],
            data_scope="SELF",
            caller_employee_id=UUID(self_employee_id),
        )
        listed = await client.get("/v1/overtime", headers=self_headers)
        assert listed.status_code == 200, listed.text
        employee_ids = {row["employee_id"] for row in listed.json()["data"]}
        assert employee_ids == {self_employee_id}
    finally:
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_reportees_scope_excludes_unrelated_employee(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
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
        await _create_overtime_policy(client, headers, approval_chain="AUTO")
        await _ot_calculate_day(client, headers, employee_id=reportee["id"], day="2026-08-10")
        await _ot_calculate_day(client, headers, employee_id=stranger["id"], day="2026-08-11")

        from hrms.modules.attendance.permissions import ATTENDANCE_VIEW

        manager_headers, _ = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[ATTENDANCE_VIEW],
            data_scope="REPORTEES",
            caller_employee_id=UUID(manager_id),
        )
        listed = await client.get("/v1/overtime", headers=manager_headers)
        assert listed.status_code == 200, listed.text
        employee_ids = {row["employee_id"] for row in listed.json()["data"]}
        assert employee_ids == {reportee["id"]}
    finally:
        await _cleanup_overtime(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_cross_tenant_overtime_record_returns_404(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_id_a, user_id_a = await _register_tenant(client)
    headers_b, company_id_b, user_id_b = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers_a)
        employee_id = wired["employee"]["id"]
        await _create_overtime_policy(client, headers_a, approval_chain="AUTO")
        await _ot_calculate_day(client, headers_a, employee_id=employee_id)
        record = await _get_overtime_record_for_day(
            client, headers_a, employee_id=employee_id, day="2026-08-10"
        )

        cross = await client.get(f"/v1/overtime/{record['id']}", headers=headers_b)
        assert cross.status_code == 404, cross.text
    finally:
        await _cleanup_overtime(company_id=company_id_a)
        await _cleanup_attendance_day(company_id=company_id_a)
        await _cleanup(company_id=company_id_a, user_id=user_id_a)
        await _cleanup_overtime(company_id=company_id_b)
        await _cleanup_attendance_day(company_id=company_id_b)
        await _cleanup(company_id=company_id_b, user_id=user_id_b)
