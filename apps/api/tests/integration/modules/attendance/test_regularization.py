"""Integration tests for W6 — `/v1/regularizations*` (architecture §13/§14, decision log WD-28).

Reuses `_build_wired_employee`/`_punch`/`_register_tenant`/`_cleanup_attendance_day` from
`test_attendance_day.py` and `_add_reportee_employee`/`_create_permission_scoped_user`/
`_cleanup_scoped_users` from `test_attendance_security.py` — the same cross-file reuse pattern
`test_shift_roster.py` already established, so the wired employee already has an assignment
`shift_id`, a COMPANY work calendar, and a COMPANY attendance policy; these tests only add a
COMPANY-assigned `RegularizationPolicy` on top.
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


async def _create_regularization_policy(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    allowed_types: list[str] | None = None,
    approval_chain: str = "MANAGER",
    **version_overrides: Any,
) -> dict[str, Any]:
    policy = (
        await client.post(
            "/v1/regularization-policies", headers=headers, json={"name": "Standard Reg"}
        )
    ).json()["data"]
    body = {
        "effective_from": "2026-01-01",
        "allowed_types": [
            {"regularization_type": t}
            for t in (allowed_types or ["MISSING_PUNCH", "WRONG_PUNCH", "WRONG_SHIFT", "FULL_DAY"])
        ],
        "approval_chain": approval_chain,
        **version_overrides,
    }
    draft = (
        await client.post(
            f"/v1/regularization-policies/{policy['id']}/versions", headers=headers, json=body
        )
    ).json()["data"]
    published = await client.post(
        f"/v1/regularization-policies/{policy['id']}/versions/{draft['id']}/publish",
        headers={**headers, "If-Match": "1"},
        json={},
    )
    assert published.status_code == 200, published.text

    assignment = await client.post(
        "/v1/policy-assignments",
        headers=headers,
        json={
            "policy_kind": "REGULARIZATION_POLICY",
            "policy_id": policy["id"],
            "scope_type": "COMPANY",
            "effective_from": "2026-01-01",
        },
    )
    assert assignment.status_code == 201, assignment.text
    return policy


async def _cleanup_regularization(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        for table in (
            "attendance_regularization_action",
            "attendance_regularization_requested_punch",
            "attendance_regularization_request",
            "regularization_policy_version",
            "regularization_policy",
        ):
            await session.execute(
                text(f"DELETE FROM {table} WHERE company_id = :cid"), {"cid": str(company_id)}
            )
        await session.commit()


def _requested_punches(day: str = "2026-08-10") -> list[dict[str, str]]:
    return [
        {"direction": "IN", "requested_time": f"{day}T09:00:00Z"},
        {"direction": "OUT", "requested_time": f"{day}T18:00:00Z"},
    ]


# ---------------------------------------------------------------------------
# Creation & validation
# ---------------------------------------------------------------------------


async def test_employee_creates_own_request_manager_stage_resolved(
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
        await _create_regularization_policy(client, headers)

        from hrms.modules.attendance.permissions import ATTENDANCE_REGULARIZATION_REQUEST

        scoped_headers, _ = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[ATTENDANCE_REGULARIZATION_REQUEST],
            data_scope="SELF",
            caller_employee_id=UUID(reportee["id"]),
        )
        response = await client.post(
            "/v1/regularizations",
            headers=scoped_headers,
            json={
                "attendance_date": "2026-08-10",
                "request_type": "MISSING_PUNCH",
                "reason": "Forgot to punch",
                "requested_punches": _requested_punches(),
            },
        )
        assert response.status_code == 201, response.text
        data = response.json()["data"]
        assert data["status"] == "SUBMITTED"
        assert data["approval_chain"] == "MANAGER"
        assert data["approval_stage"] == "MANAGER"
        assert data["resolved_approver_manager_id"] == manager_id
        assert len(data["requested_punches"]) == 2
        assert data["actions"][0]["action"] == "SUBMITTED"
    finally:
        await _cleanup_regularization(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_disallowed_request_type_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _create_regularization_policy(client, headers, allowed_types=["WRONG_SHIFT"])

        response = await client.post(
            "/v1/regularizations",
            headers=headers,
            json={
                "employee_id": employee_id,
                "attendance_date": "2026-08-10",
                "request_type": "MISSING_PUNCH",
                "reason": "x",
                "requested_punches": _requested_punches(),
            },
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "REGULARIZATION_TYPE_NOT_ALLOWED"
    finally:
        await _cleanup_regularization(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_missing_policy_fails_closed(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        # No RegularizationPolicy/PolicyAssignment created at all.
        response = await client.post(
            "/v1/regularizations",
            headers=headers,
            json={
                "employee_id": employee_id,
                "attendance_date": "2026-08-10",
                "request_type": "MISSING_PUNCH",
                "reason": "x",
                "requested_punches": _requested_punches(),
            },
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "REGULARIZATION_POLICY_NOT_RESOLVED"
    finally:
        await _cleanup_regularization(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_backdating_window_enforced(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _create_regularization_policy(client, headers, max_backdated_days=1)

        response = await client.post(
            "/v1/regularizations",
            headers=headers,
            json={
                "employee_id": employee_id,
                "attendance_date": "2026-01-02",
                "request_type": "MISSING_PUNCH",
                "reason": "x",
                "requested_punches": _requested_punches(day="2026-01-02"),
            },
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "REGULARIZATION_WINDOW_EXCEEDED"
    finally:
        await _cleanup_regularization(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_monthly_request_limit_enforced(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _create_regularization_policy(client, headers, max_requests_per_month=1)

        first = await client.post(
            "/v1/regularizations",
            headers=headers,
            json={
                "employee_id": employee_id,
                "attendance_date": "2026-08-10",
                "request_type": "MISSING_PUNCH",
                "reason": "x",
                "requested_punches": _requested_punches(day="2026-08-10"),
            },
        )
        assert first.status_code == 201, first.text

        second = await client.post(
            "/v1/regularizations",
            headers=headers,
            json={
                "employee_id": employee_id,
                "attendance_date": "2026-08-11",
                "request_type": "MISSING_PUNCH",
                "reason": "x",
                "requested_punches": _requested_punches(day="2026-08-11"),
            },
        )
        assert second.status_code == 422, second.text
        assert second.json()["error"]["code"] == "REGULARIZATION_REQUEST_LIMIT_EXCEEDED"
    finally:
        await _cleanup_regularization(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_duplicate_active_request_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _create_regularization_policy(client, headers)

        body = {
            "employee_id": employee_id,
            "attendance_date": "2026-08-10",
            "request_type": "MISSING_PUNCH",
            "reason": "x",
            "requested_punches": _requested_punches(),
        }
        first = await client.post("/v1/regularizations", headers=headers, json=body)
        assert first.status_code == 201, first.text

        second = await client.post("/v1/regularizations", headers=headers, json=body)
        assert second.status_code == 409, second.text
        assert second.json()["error"]["code"] == "REGULARIZATION_DUPLICATE_ACTIVE_REQUEST"
    finally:
        await _cleanup_regularization(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_missing_correction_payload_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _create_regularization_policy(client, headers)

        response = await client.post(
            "/v1/regularizations",
            headers=headers,
            json={
                "employee_id": employee_id,
                "attendance_date": "2026-08-10",
                "request_type": "MISSING_PUNCH",
                "reason": "x",
            },
        )
        assert response.status_code == 422, response.text
    finally:
        await _cleanup_regularization(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_reason_required_enforced(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _create_regularization_policy(client, headers, reason_required=True)

        response = await client.post(
            "/v1/regularizations",
            headers=headers,
            json={
                "employee_id": employee_id,
                "attendance_date": "2026-08-10",
                "request_type": "MISSING_PUNCH",
                "requested_punches": _requested_punches(),
            },
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "REGULARIZATION_REASON_REQUIRED"
    finally:
        await _cleanup_regularization(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# ---------------------------------------------------------------------------
# DataScope / security
# ---------------------------------------------------------------------------


async def test_on_behalf_requires_on_behalf_permission(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _create_regularization_policy(client, headers)

        from hrms.modules.attendance.permissions import ATTENDANCE_REGULARIZATION_REQUEST

        scoped_headers, _ = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[ATTENDANCE_REGULARIZATION_REQUEST],
            data_scope="SELF",
            caller_employee_id=None,
        )
        response = await client.post(
            "/v1/regularizations",
            headers=scoped_headers,
            json={
                "employee_id": employee_id,
                "attendance_date": "2026-08-10",
                "request_type": "MISSING_PUNCH",
                "reason": "x",
                "requested_punches": _requested_punches(),
            },
        )
        assert response.status_code == 403, response.text
    finally:
        await _cleanup_regularization(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_forged_employee_id_out_of_scope_returns_404(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        manager_id = wired["employee"]["id"]
        stranger = await _add_reportee_employee(
            client, headers, wired=wired, first_name="Stranger", reporting_manager_id=None
        )
        await _create_regularization_policy(client, headers)

        from hrms.modules.attendance.permissions import ATTENDANCE_REGULARIZATION_REQUEST_ON_BEHALF

        scoped_headers, _ = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[ATTENDANCE_REGULARIZATION_REQUEST_ON_BEHALF],
            data_scope="REPORTEES",
            caller_employee_id=UUID(manager_id),
        )
        # `stranger` does not report to `manager_id` -> outside REPORTEES scope.
        response = await client.post(
            "/v1/regularizations",
            headers=scoped_headers,
            json={
                "employee_id": stranger["id"],
                "attendance_date": "2026-08-10",
                "request_type": "MISSING_PUNCH",
                "reason": "x",
                "requested_punches": _requested_punches(),
            },
        )
        assert response.status_code == 404, response.text
    finally:
        await _cleanup_regularization(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_cross_tenant_request_returns_404(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_id_a, user_id_a = await _register_tenant(client)
    headers_b, company_id_b, user_id_b = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers_a)
        employee_id = wired["employee"]["id"]
        await _create_regularization_policy(client, headers_a)

        created = await client.post(
            "/v1/regularizations",
            headers=headers_a,
            json={
                "employee_id": employee_id,
                "attendance_date": "2026-08-10",
                "request_type": "MISSING_PUNCH",
                "reason": "x",
                "requested_punches": _requested_punches(),
            },
        )
        assert created.status_code == 201, created.text
        request_id = created.json()["data"]["id"]

        cross = await client.get(f"/v1/regularizations/{request_id}", headers=headers_b)
        assert cross.status_code == 404, cross.text
    finally:
        await _cleanup_regularization(company_id=company_id_a)
        await _cleanup_attendance_day(company_id=company_id_a)
        await _cleanup(company_id=company_id_a, user_id=user_id_a)
        await _cleanup_regularization(company_id=company_id_b)
        await _cleanup_attendance_day(company_id=company_id_b)
        await _cleanup(company_id=company_id_b, user_id=user_id_b)


# ---------------------------------------------------------------------------
# Lifecycle / approval
# ---------------------------------------------------------------------------


async def test_manager_approval_applies_correction_and_recomputes(
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
        await _create_regularization_policy(client, headers)

        created = await client.post(
            "/v1/regularizations",
            headers=headers,
            json={
                "employee_id": employee_id,
                "attendance_date": "2026-08-10",
                "request_type": "MISSING_PUNCH",
                "reason": "Forgot to punch",
                "requested_punches": _requested_punches(),
            },
        )
        assert created.status_code == 201, created.text
        request = created.json()["data"]
        assert request["approval_stage"] == "MANAGER"

        from hrms.modules.attendance.permissions import ATTENDANCE_REGULARIZATION_APPROVE

        manager_headers, _ = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[ATTENDANCE_REGULARIZATION_APPROVE],
            data_scope="REPORTEES",
            caller_employee_id=UUID(manager_id),
        )
        approved = await client.post(
            f"/v1/regularizations/{request['id']}/approve",
            headers={**manager_headers, "If-Match": str(request["version"])},
            json={"reviewer_comment": "Looks fine"},
        )
        assert approved.status_code == 200, approved.text
        data = approved.json()["data"]
        assert data["status"] == "APPROVED"
        assert data["approval_stage"] is None
        assert data["applied_at"] is not None
        assert any(a["action"] == "APPLIED" for a in data["actions"])

        day = await client.get(f"/v1/attendance/days/{data['attendance_day_id']}", headers=headers)
        assert day.status_code == 200
        day_data = day.json()["data"]
        assert day_data["attendance_status"] == "PRESENT"
        assert day_data["is_regularized"] is True
        assert day_data["is_pending_approval"] is False
        assert day_data["worked_minutes"] == 540

        punches = await client.get(
            "/v1/attendance/punches",
            headers=headers,
            params={"employee_id": employee_id, "date_from": "2026-08-10", "date_to": "2026-08-10"},
        )
        assert punches.status_code == 200
        assert {p["source"] for p in punches.json()["data"]} == {"REGULARIZATION"}
    finally:
        await _cleanup_regularization(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_reject_leaves_attendance_unchanged(
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
        await _create_regularization_policy(client, headers)

        created = await client.post(
            "/v1/regularizations",
            headers=headers,
            json={
                "employee_id": employee_id,
                "attendance_date": "2026-08-10",
                "request_type": "MISSING_PUNCH",
                "reason": "x",
                "requested_punches": _requested_punches(),
            },
        )
        request = created.json()["data"]

        from hrms.modules.attendance.permissions import ATTENDANCE_REGULARIZATION_APPROVE

        manager_headers, _ = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[ATTENDANCE_REGULARIZATION_APPROVE],
            data_scope="REPORTEES",
            caller_employee_id=UUID(manager_id),
        )
        rejected = await client.post(
            f"/v1/regularizations/{request['id']}/reject",
            headers={**manager_headers, "If-Match": str(request["version"])},
            json={"reviewer_comment": "No evidence", "rejection_reason": "Insufficient evidence"},
        )
        assert rejected.status_code == 200, rejected.text
        data = rejected.json()["data"]
        assert data["status"] == "REJECTED"
        assert data["rejection_reason"] == "Insufficient evidence"
        assert data["applied_at"] is None

        punches = await client.get(
            "/v1/attendance/punches",
            headers=headers,
            params={"employee_id": employee_id, "date_from": "2026-08-10", "date_to": "2026-08-10"},
        )
        assert punches.json()["data"] == []

        # A rejected request cannot later be approved (Phase 5).
        replay = await client.post(
            f"/v1/regularizations/{request['id']}/approve",
            headers={**manager_headers, "If-Match": "2"},
            json={},
        )
        assert replay.status_code == 409, replay.text
        assert replay.json()["error"]["code"] == "REGULARIZATION_INVALID_TRANSITION"
    finally:
        await _cleanup_regularization(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_employee_cancels_own_pending_request(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _create_regularization_policy(client, headers)

        created = await client.post(
            "/v1/regularizations",
            headers=headers,
            json={
                "employee_id": employee_id,
                "attendance_date": "2026-08-10",
                "request_type": "MISSING_PUNCH",
                "reason": "x",
                "requested_punches": _requested_punches(),
            },
        )
        request = created.json()["data"]

        cancelled = await client.post(
            f"/v1/regularizations/{request['id']}/cancel",
            headers={**headers, "If-Match": str(request["version"])},
        )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["data"]["status"] == "CANCELLED"

        # A cancelled request cannot later be approved.
        from hrms.modules.attendance.permissions import ATTENDANCE_REGULARIZATION_APPROVE

        manager_headers, _ = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=[ATTENDANCE_REGULARIZATION_APPROVE]
        )
        replay = await client.post(
            f"/v1/regularizations/{request['id']}/approve",
            headers={**manager_headers, "If-Match": "2"},
            json={},
        )
        assert replay.status_code == 409, replay.text
    finally:
        await _cleanup_regularization(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_non_submitter_cannot_cancel(
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
        await _create_regularization_policy(client, headers)

        created = await client.post(
            "/v1/regularizations",
            headers=headers,
            json={
                "employee_id": employee_id,
                "attendance_date": "2026-08-10",
                "request_type": "MISSING_PUNCH",
                "reason": "x",
                "requested_punches": _requested_punches(),
            },
        )
        request = created.json()["data"]

        from hrms.modules.attendance.permissions import ATTENDANCE_REGULARIZATION_REQUEST

        other_headers, _ = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[ATTENDANCE_REGULARIZATION_REQUEST],
            data_scope="COMPANY",
            caller_employee_id=UUID(employee_id),
        )
        response = await client.post(
            f"/v1/regularizations/{request['id']}/cancel",
            headers={**other_headers, "If-Match": str(request["version"])},
        )
        assert response.status_code == 403, response.text
    finally:
        await _cleanup_regularization(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_self_approval_blocked(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _create_regularization_policy(client, headers, approval_chain="HR")

        created = await client.post(
            "/v1/regularizations",
            headers=headers,
            json={
                "employee_id": employee_id,
                "attendance_date": "2026-08-10",
                "request_type": "MISSING_PUNCH",
                "reason": "x",
                "requested_punches": _requested_punches(),
            },
        )
        request = created.json()["data"]

        from hrms.modules.attendance.permissions import ATTENDANCE_REGULARIZATION_APPROVE

        self_hr_headers, _ = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[ATTENDANCE_REGULARIZATION_APPROVE],
            data_scope="COMPANY",
            caller_employee_id=UUID(employee_id),
        )
        response = await client.post(
            f"/v1/regularizations/{request['id']}/approve",
            headers={**self_hr_headers, "If-Match": str(request["version"])},
            json={},
        )
        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "REGULARIZATION_SELF_APPROVAL_NOT_ALLOWED"
    finally:
        await _cleanup_regularization(company_id=company_id)
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
            client, headers, wired=wired, first_name="OtherMgr", reporting_manager_id=None
        )
        employee_id = reportee["id"]
        await _create_regularization_policy(client, headers)

        created = await client.post(
            "/v1/regularizations",
            headers=headers,
            json={
                "employee_id": employee_id,
                "attendance_date": "2026-08-10",
                "request_type": "MISSING_PUNCH",
                "reason": "x",
                "requested_punches": _requested_punches(),
            },
        )
        request = created.json()["data"]

        from hrms.modules.attendance.permissions import ATTENDANCE_REGULARIZATION_APPROVE

        wrong_headers, _ = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[ATTENDANCE_REGULARIZATION_APPROVE],
            data_scope="COMPANY",
            caller_employee_id=UUID(other_manager["id"]),
        )
        response = await client.post(
            f"/v1/regularizations/{request['id']}/approve",
            headers={**wrong_headers, "If-Match": str(request["version"])},
            json={},
        )
        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "REGULARIZATION_APPROVER_MISMATCH"
    finally:
        await _cleanup_regularization(company_id=company_id)
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
        await _create_regularization_policy(client, headers, approval_chain="MANAGER_THEN_HR")

        created = await client.post(
            "/v1/regularizations",
            headers=headers,
            json={
                "employee_id": employee_id,
                "attendance_date": "2026-08-10",
                "request_type": "MISSING_PUNCH",
                "reason": "x",
                "requested_punches": _requested_punches(),
            },
        )
        request = created.json()["data"]
        assert request["approval_stage"] == "MANAGER"

        from hrms.modules.attendance.permissions import ATTENDANCE_REGULARIZATION_APPROVE

        manager_headers, _ = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[ATTENDANCE_REGULARIZATION_APPROVE],
            data_scope="REPORTEES",
            caller_employee_id=UUID(manager_id),
        )
        stage1 = await client.post(
            f"/v1/regularizations/{request['id']}/approve",
            headers={**manager_headers, "If-Match": str(request["version"])},
            json={"reviewer_comment": "Manager OK"},
        )
        assert stage1.status_code == 200, stage1.text
        stage1_data = stage1.json()["data"]
        assert stage1_data["status"] == "SUBMITTED"
        assert stage1_data["approval_stage"] == "HR"
        assert stage1_data["applied_at"] is None
        assert any(a["action"] == "STAGE_APPROVED" for a in stage1_data["actions"])

        # The manager cannot also clear the HR stage.
        manager_retry = await client.post(
            f"/v1/regularizations/{request['id']}/approve",
            headers={**manager_headers, "If-Match": str(stage1_data["version"])},
            json={},
        )
        assert manager_retry.status_code == 403, manager_retry.text

        hr_headers, _ = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[ATTENDANCE_REGULARIZATION_APPROVE],
            data_scope="COMPANY",
            caller_employee_id=None,
        )
        stage2 = await client.post(
            f"/v1/regularizations/{request['id']}/approve",
            headers={**hr_headers, "If-Match": str(stage1_data["version"])},
            json={"reviewer_comment": "HR OK"},
        )
        assert stage2.status_code == 200, stage2.text
        stage2_data = stage2.json()["data"]
        assert stage2_data["status"] == "APPROVED"
        assert stage2_data["applied_at"] is not None
    finally:
        await _cleanup_regularization(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_auto_chain_approves_and_applies_on_submit(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _create_regularization_policy(client, headers, approval_chain="AUTO")

        created = await client.post(
            "/v1/regularizations",
            headers=headers,
            json={
                "employee_id": employee_id,
                "attendance_date": "2026-08-10",
                "request_type": "MISSING_PUNCH",
                "reason": "x",
                "requested_punches": _requested_punches(),
            },
        )
        assert created.status_code == 201, created.text
        data = created.json()["data"]
        assert data["status"] == "APPROVED"
        assert data["applied_at"] is not None

        day = await client.get(f"/v1/attendance/days/{data['attendance_day_id']}", headers=headers)
        assert day.json()["data"]["is_regularized"] is True
    finally:
        await _cleanup_regularization(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_no_manager_resolved_routes_to_hr(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """§14 — resolution failure (no manager as-of the date) routes to HR and audits
    `APPROVER_UNRESOLVED`, never auto-approves."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]  # no reporting_manager_id set
        await _create_regularization_policy(client, headers, approval_chain="MANAGER")

        created = await client.post(
            "/v1/regularizations",
            headers=headers,
            json={
                "employee_id": employee_id,
                "attendance_date": "2026-08-10",
                "request_type": "MISSING_PUNCH",
                "reason": "x",
                "requested_punches": _requested_punches(),
            },
        )
        assert created.status_code == 201, created.text
        data = created.json()["data"]
        assert data["status"] == "SUBMITTED"
        assert data["approval_stage"] == "HR"
        assert data["resolved_approver_manager_id"] is None
        assert any(a["action"] == "APPROVER_UNRESOLVED" for a in data["actions"])
    finally:
        await _cleanup_regularization(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_wrong_shift_applies_via_roster(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _create_regularization_policy(client, headers, approval_chain="HR")

        night_shift = (
            await client.post("/v1/shifts", headers=headers, json={"name": "Night", "code": "NGT"})
        ).json()["data"]
        draft_id = night_shift["draft_version_id"]
        await client.patch(
            f"/v1/shifts/{night_shift['id']}/versions/{draft_id}",
            headers={**headers, "If-Match": "1"},
            json={
                "shift_type": "FIXED",
                "effective_from": "2026-01-01",
                "start_time": "22:00",
                "end_time": "06:00",
                "timezone": "UTC",
            },
        )
        await client.post(
            f"/v1/shifts/{night_shift['id']}/versions/{draft_id}/publish",
            headers={**headers, "If-Match": "2"},
            json={},
        )

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

        created = await client.post(
            "/v1/regularizations",
            headers=headers,
            json={
                "employee_id": employee_id,
                "attendance_date": "2026-08-10",
                "request_type": "WRONG_SHIFT",
                "reason": "Was on the night shift, roster was wrong",
                "requested_shift_id": night_shift["id"],
            },
        )
        assert created.status_code == 201, created.text
        request = created.json()["data"]

        from hrms.modules.attendance.permissions import ATTENDANCE_REGULARIZATION_APPROVE

        hr_headers, _ = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=[ATTENDANCE_REGULARIZATION_APPROVE]
        )
        approved = await client.post(
            f"/v1/regularizations/{request['id']}/approve",
            headers={**hr_headers, "If-Match": str(request["version"])},
            json={},
        )
        assert approved.status_code == 200, approved.text
        day = await client.get(
            f"/v1/attendance/days/{approved.json()['data']['attendance_day_id']}", headers=headers
        )
        day_data = day.json()["data"]
        assert day_data["shift_id"] == night_shift["id"]
        assert day_data["attendance_status"] == "PRESENT"

        roster = await client.get(
            "/v1/rosters", headers=headers, params={"employee_id": employee_id}
        )
        rows = [r for r in roster.json()["data"] if r["roster_date"] == "2026-08-10"]
        assert len(rows) == 1
        assert rows[0]["status"] == "PUBLISHED"
        assert rows[0]["shift_id"] == night_shift["id"]
    finally:
        await _cleanup_regularization(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_locked_day_blocks_new_request(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _create_regularization_policy(client, headers, blocked_when_locked=True)

        await _punch(client, headers, employee_id=employee_id, hour=9, minute=0, direction="IN")
        await _punch(client, headers, employee_id=employee_id, hour=18, minute=0, direction="OUT")
        day = (
            await client.post(
                "/v1/attendance/days/calculate",
                headers=headers,
                params={"employee_id": employee_id, "date": "2026-08-10"},
            )
        ).json()["data"]

        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, str(company_id))
            await session.execute(
                text("UPDATE attendance_day SET is_locked = true WHERE id = :id"), {"id": day["id"]}
            )
            await session.commit()

        response = await client.post(
            "/v1/regularizations",
            headers=headers,
            json={
                "employee_id": employee_id,
                "attendance_date": "2026-08-10",
                "request_type": "MISSING_PUNCH",
                "reason": "x",
                "requested_punches": _requested_punches(),
            },
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "REGULARIZATION_BLOCKED_BY_LOCK"
    finally:
        await _cleanup_regularization(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


async def test_stale_if_match_on_approve_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _create_regularization_policy(client, headers, approval_chain="HR")

        created = await client.post(
            "/v1/regularizations",
            headers=headers,
            json={
                "employee_id": employee_id,
                "attendance_date": "2026-08-10",
                "request_type": "MISSING_PUNCH",
                "reason": "x",
                "requested_punches": _requested_punches(),
            },
        )
        request = created.json()["data"]

        from hrms.modules.attendance.permissions import ATTENDANCE_REGULARIZATION_APPROVE

        hr_headers, _ = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=[ATTENDANCE_REGULARIZATION_APPROVE]
        )
        stale = await client.post(
            f"/v1/regularizations/{request['id']}/approve",
            headers={**hr_headers, "If-Match": "999"},
            json={},
        )
        assert stale.status_code == 409, stale.text
        assert stale.json()["error"]["code"] == "STALE_RESOURCE"
    finally:
        await _cleanup_regularization(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_simultaneous_approve_and_reject_only_one_wins(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Two racing terminal transitions against the same `expected_version`: only the first
    conditional `UPDATE` can match, the second sees a stale version — never a double-application
    or a request left in two contradictory terminal states."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _create_regularization_policy(client, headers, approval_chain="HR")

        created = await client.post(
            "/v1/regularizations",
            headers=headers,
            json={
                "employee_id": employee_id,
                "attendance_date": "2026-08-10",
                "request_type": "MISSING_PUNCH",
                "reason": "x",
                "requested_punches": _requested_punches(),
            },
        )
        request = created.json()["data"]

        from hrms.modules.attendance.permissions import ATTENDANCE_REGULARIZATION_APPROVE

        hr_headers, _ = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=[ATTENDANCE_REGULARIZATION_APPROVE]
        )
        approve = await client.post(
            f"/v1/regularizations/{request['id']}/approve",
            headers={**hr_headers, "If-Match": str(request["version"])},
            json={},
        )
        reject = await client.post(
            f"/v1/regularizations/{request['id']}/reject",
            headers={**hr_headers, "If-Match": str(request["version"])},
            json={"rejection_reason": "too slow"},
        )
        statuses = sorted([approve.status_code, reject.status_code])
        assert statuses == [200, 409]

        final = await client.get(f"/v1/regularizations/{request['id']}", headers=headers)
        assert final.json()["data"]["status"] == "APPROVED"
    finally:
        await _cleanup_regularization(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()
