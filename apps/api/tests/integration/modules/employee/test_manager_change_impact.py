"""The pending-request warning that guards a change of reporting manager.

Two halves, both backend-owned:

* `GET /v1/employees/{id}/manager-change-impact` - a read-only preview of how many of the employee's
  requests would stay with their current approver;
* the manager change itself (`POST /v1/employees/{id}/assignments`), which refuses to proceed until
  the caller acknowledges exactly that set of requests (`confirm_pending_request_impact` plus the
  `pending_impact_token`), re-evaluated inside the write so a preview cannot go stale unnoticed.

Pending means: waiting on a *manager's* decision (Leave and Regularization `SUBMITTED`, Overtime
`PENDING`, each at stage `MANAGER`) with a snapshotted approver other than the proposed manager.
"""

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from hrms.core.audit.models import AuditLog
from hrms.core.db.session import get_session_factory

from .manager_change_support import (
    CHANGE_FROM,
    CONFIRMATION_REQUIRED,
    LEAVE_AFTER,
    LEAVE_BEFORE,
    REG_BEFORE,
    REG_BEFORE_OTHER,
    approve,
    build_world,
    change_manager,
    current_assignment,
    detect_overtime,
    fetch,
    manager_headers,
    post_manager_change,
    submit_leave,
    submit_regularization,
    teardown_world,
)
from .test_employee_assignment import _create_permission_scoped_user, _register_tenant

pytestmark = pytest.mark.asyncio

NONE_PENDING = {"leave": 0, "attendance_regularization": 0, "overtime": 0}


async def _impact(
    client: AsyncClient,
    headers: dict[str, str],
    employee_id: str,
    *,
    manager_id: str | None,
    effective_from: str = CHANGE_FROM,
) -> Any:
    params: dict[str, str] = {"effective_from": effective_from}
    if manager_id is not None:
        params["reporting_manager_id"] = manager_id
    return await client.get(
        f"/v1/employees/{employee_id}/manager-change-impact", headers=headers, params=params
    )


async def _impact_data(
    client: AsyncClient, headers: dict[str, str], employee_id: str, **kwargs: Any
) -> dict[str, Any]:
    response = await _impact(client, headers, employee_id, **kwargs)
    assert response.status_code == 200, response.text
    return dict(response.json()["data"])


async def _reject(
    client: AsyncClient, headers: dict[str, str], kind: str, request: dict[str, Any]
) -> Any:
    path = {"leave": "/v1/leave-applications", "reg": "/v1/regularizations"}[kind]
    body = (
        {"rejection_reason": "Not approved"}
        if kind == "leave"
        else {"reviewer_comment": "No evidence", "rejection_reason": "Insufficient evidence"}
    )
    return await client.post(
        f"{path}/{request['id']}/reject",
        headers={**headers, "If-Match": str(request["version"])},
        json=body,
    )


async def _cancel(
    client: AsyncClient, headers: dict[str, str], kind: str, request: dict[str, Any]
) -> Any:
    path = {"leave": "/v1/leave-applications", "reg": "/v1/regularizations"}[kind]
    return await client.post(
        f"{path}/{request['id']}/cancel", headers={**headers, "If-Match": str(request["version"])}
    )


# --- Detection -------------------------------------------------------------------------------


async def test_no_pending_requests_means_no_warning_and_the_change_goes_straight_through(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        world = await build_world(client, headers)
        b, e = world["b"]["id"], world["e"]["id"]

        impact = await _impact_data(client, headers, e, manager_id=b)
        assert impact["has_pending_requests"] is False
        assert impact["requires_confirmation"] is False
        assert impact["total_pending_requests"] == 0
        assert impact["requests"] == NONE_PENDING
        assert impact["changes_manager"] is True
        assert impact["current_reporting_manager_id"] == world["a"]["id"]
        assert impact["new_manager_applies_to_requests_dated_from"] == CHANGE_FROM

        moved = await post_manager_change(
            client, headers, e, manager_id=b, effective_from=CHANGE_FROM
        )
        assert moved.status_code == 201, moved.text
    finally:
        await teardown_world(company_id=company_id, user_id=user_id)


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("leave", {"leave": 1, "attendance_regularization": 0, "overtime": 0}),
        ("reg", {"leave": 0, "attendance_regularization": 1, "overtime": 0}),
        ("ot", {"leave": 0, "attendance_regularization": 0, "overtime": 1}),
    ],
)
async def test_each_workflow_is_counted_on_its_own(
    client: AsyncClient, seeded_plan_catalogue: None, kind: str, expected: dict[str, int]
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        world = await build_world(client, headers)
        factories = {
            "leave": lambda: submit_leave(client, headers, world, LEAVE_BEFORE),
            "reg": lambda: submit_regularization(client, headers, world, REG_BEFORE),
            "ot": lambda: detect_overtime(client, headers, world),
        }
        await factories[kind]()

        impact = await _impact_data(client, headers, world["e"]["id"], manager_id=world["b"]["id"])

        assert impact["requests"] == expected
        assert impact["total_pending_requests"] == 1
        assert impact["has_pending_requests"] is True
        assert impact["requires_confirmation"] is True
    finally:
        await teardown_world(company_id=company_id, user_id=user_id)


async def test_mixed_workflows_are_totalled_and_finished_requests_are_excluded(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        world = await build_world(client, headers)
        a_headers = await manager_headers(company_id, world["a"]["id"])

        # Leave: one pending, one approved, one rejected, one cancelled -> only the pending counts.
        pending_leave = await submit_leave(client, headers, world, LEAVE_BEFORE)
        approved_leave = await submit_leave(client, headers, world, "2026-09-09")
        rejected_leave = await submit_leave(client, headers, world, "2026-09-10")
        cancelled_leave = await submit_leave(client, headers, world, "2026-09-11")
        assert (await approve(client, a_headers, "leave", approved_leave)).status_code == 200
        assert (await _reject(client, a_headers, "leave", rejected_leave)).status_code == 200
        assert (await _cancel(client, headers, "leave", cancelled_leave)).status_code == 200

        # Regularization: one pending, one rejected, one cancelled.
        pending_reg = await submit_regularization(client, headers, world, REG_BEFORE)
        rejected_reg = await submit_regularization(client, headers, world, REG_BEFORE_OTHER)
        cancelled_reg = await submit_regularization(client, headers, world, "2026-08-14")
        assert (await _reject(client, a_headers, "reg", rejected_reg)).status_code == 200
        assert (await _cancel(client, headers, "reg", cancelled_reg)).status_code == 200

        # Overtime: one pending.
        pending_ot = await detect_overtime(client, headers, world)

        impact = await _impact_data(client, headers, world["e"]["id"], manager_id=world["b"]["id"])

        assert impact["requests"] == {"leave": 1, "attendance_regularization": 1, "overtime": 1}
        assert impact["total_pending_requests"] == 3
        # ...and nothing was moved by merely looking.
        assert (await fetch(client, headers, "leave", pending_leave["id"]))[
            "resolved_approver_manager_id"
        ] == world["a"]["id"]
        assert (await fetch(client, headers, "reg", pending_reg["id"]))[
            "resolved_approver_manager_id"
        ] == world["a"]["id"]
        assert pending_ot["status"] == "PENDING"
    finally:
        await teardown_world(company_id=company_id, user_id=user_id)


async def test_requests_waiting_on_hr_or_already_with_the_proposed_manager_are_not_counted(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        world = await build_world(client, headers)
        a, b, e = world["a"]["id"], world["b"]["id"], world["e"]["id"]

        # E reports to nobody: a new request waits on HR, not on a manager.
        removed = await change_manager(
            client, headers, e, manager_id=None, effective_from="2026-09-01"
        )
        assert removed.status_code == 201, removed.text
        waiting_on_hr = await submit_leave(client, headers, world, LEAVE_AFTER)
        assert waiting_on_hr["approval_stage"] == "HR"
        assert (await _impact_data(client, headers, e, manager_id=b))["total_pending_requests"] == 0

        # A request already snapshotted to A is not "left behind" when A becomes the manager again.
        restored = await change_manager(
            client, headers, e, manager_id=a, effective_from="2026-09-15"
        )
        assert restored.status_code == 201, restored.text
        with_a = await submit_leave(client, headers, world, "2026-10-26")
        assert with_a["resolved_approver_manager_id"] == a
        assert (await _impact_data(client, headers, e, manager_id=a))["total_pending_requests"] == 0
        assert (await _impact_data(client, headers, e, manager_id=a))["changes_manager"] is False
        assert (await _impact_data(client, headers, e, manager_id=b))["total_pending_requests"] == 1
    finally:
        await teardown_world(company_id=company_id, user_id=user_id)


async def test_removing_the_manager_also_reports_the_pending_requests(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        world = await build_world(client, headers)
        await submit_leave(client, headers, world, LEAVE_BEFORE)

        impact = await _impact_data(client, headers, world["e"]["id"], manager_id=None)

        assert impact["proposed_reporting_manager_id"] is None
        assert impact["requests"]["leave"] == 1
        assert impact["requires_confirmation"] is True
    finally:
        await teardown_world(company_id=company_id, user_id=user_id)


# --- Confirmation ----------------------------------------------------------------------------


async def test_a_change_with_pending_requests_is_refused_until_acknowledged(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        world = await build_world(client, headers)
        a, b, e = world["a"]["id"], world["b"]["id"], world["e"]["id"]
        leave = await submit_leave(client, headers, world, LEAVE_BEFORE)
        await submit_regularization(client, headers, world, REG_BEFORE)
        before = await current_assignment(client, headers, e)

        refused = await post_manager_change(
            client, headers, e, manager_id=b, effective_from=CHANGE_FROM
        )

        assert refused.status_code == 409, refused.text
        error = refused.json()["error"]
        assert error["code"] == CONFIRMATION_REQUIRED
        context = error["details"][0]["context"]
        assert context["impact"]["total_pending_requests"] == 2
        assert context["impact"]["requests"] == {
            "leave": 1,
            "attendance_regularization": 1,
            "overtime": 0,
        }
        # The preview hands out the very same token the write demands.
        preview = await _impact_data(client, headers, e, manager_id=b)
        assert context["impact_token"] == preview["impact_token"]
        # Nothing was written: same row, same manager, same version.
        after = await current_assignment(client, headers, e)
        assert (after["id"], after["version"], after["reporting_manager_id"]) == (
            before["id"],
            before["version"],
            a,
        )
        assert (await fetch(client, headers, "leave", leave["id"]))[
            "resolved_approver_manager_id"
        ] == a
    finally:
        await teardown_world(company_id=company_id, user_id=user_id)


async def test_confirmation_cannot_be_faked_or_replayed(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        world = await build_world(client, headers)
        a, b, e = world["a"]["id"], world["b"]["id"], world["e"]["id"]
        await submit_leave(client, headers, world, LEAVE_BEFORE)
        token = (await _impact_data(client, headers, e, manager_id=b))["impact_token"]

        attempts = {
            "flag without a token": {"confirm_pending_request_impact": True},
            "token without the flag": {"pending_impact_token": token},
            "flag with a made-up token": {
                "confirm_pending_request_impact": True,
                "pending_impact_token": "0" * 64,
            },
        }
        for label, extra in attempts.items():
            response = await post_manager_change(
                client, headers, e, manager_id=b, effective_from=CHANGE_FROM, extra=extra
            )
            assert response.status_code in (409, 422), (label, response.text)
            assert (await current_assignment(client, headers, e))["reporting_manager_id"] == a, (
                label
            )

        # A token issued for one proposed manager is useless for another.
        other_token = (await _impact_data(client, headers, e, manager_id=a))["impact_token"]
        assert other_token != token
        wrong_target = await post_manager_change(
            client,
            headers,
            e,
            manager_id=b,
            effective_from=CHANGE_FROM,
            extra={"confirm_pending_request_impact": True, "pending_impact_token": other_token},
        )
        assert wrong_target.status_code == 409, wrong_target.text
        assert wrong_target.json()["error"]["code"] == CONFIRMATION_REQUIRED
        assert (await current_assignment(client, headers, e))["reporting_manager_id"] == a
    finally:
        await teardown_world(company_id=company_id, user_id=user_id)


async def test_acknowledging_the_impact_lets_the_change_through_and_is_audited(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        world = await build_world(client, headers)
        a, b, e = world["a"]["id"], world["b"]["id"], world["e"]["id"]
        leave = await submit_leave(client, headers, world, LEAVE_BEFORE)
        preview = await _impact_data(client, headers, e, manager_id=b)

        moved = await post_manager_change(
            client,
            headers,
            e,
            manager_id=b,
            effective_from=CHANGE_FROM,
            extra={
                "confirm_pending_request_impact": True,
                "pending_impact_token": preview["impact_token"],
            },
        )

        assert moved.status_code == 201, moved.text
        assert moved.json()["data"]["reporting_manager_id"] == b
        # The business rule: the pending request did not move.
        assert (await fetch(client, headers, "leave", leave["id"]))[
            "resolved_approver_manager_id"
        ] == a
        factory = get_session_factory()
        async with factory() as session:
            audit = (
                (
                    await session.execute(
                        select(AuditLog)
                        .where(
                            AuditLog.company_id == company_id,
                            AuditLog.entity_id == UUID(moved.json()["data"]["id"]),
                        )
                        .order_by(AuditLog.occurred_at)
                    )
                )
                .scalars()
                .all()
            )
        assert [row.action for row in audit] == ["ASSIGNMENT_CHANGED"]
        assert audit[0].after_json["reporting_manager_id"] == b
        assert audit[0].before_json["reporting_manager_id"] == a
        assert audit[0].after_json["pending_request_impact_acknowledged"] == {
            "leave": 1,
            "attendance_regularization": 0,
            "overtime": 0,
        }
    finally:
        await teardown_world(company_id=company_id, user_id=user_id)


async def test_a_request_submitted_after_the_preview_invalidates_the_acknowledgement(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The user saw one request. Before they confirm, another is submitted. The old token no
    longer matches, so the change is refused again - this time showing two."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        world = await build_world(client, headers)
        a, b, e = world["a"]["id"], world["b"]["id"], world["e"]["id"]
        await submit_leave(client, headers, world, LEAVE_BEFORE)
        stale = await _impact_data(client, headers, e, manager_id=b)
        assert stale["total_pending_requests"] == 1

        await submit_leave(client, headers, world, "2026-09-09")

        refused = await post_manager_change(
            client,
            headers,
            e,
            manager_id=b,
            effective_from=CHANGE_FROM,
            extra={
                "confirm_pending_request_impact": True,
                "pending_impact_token": stale["impact_token"],
            },
        )
        assert refused.status_code == 409, refused.text
        fresh = refused.json()["error"]["details"][0]["context"]
        assert fresh["impact"]["total_pending_requests"] == 2
        assert fresh["impact_token"] != stale["impact_token"]
        assert (await current_assignment(client, headers, e))["reporting_manager_id"] == a

        accepted = await post_manager_change(
            client,
            headers,
            e,
            manager_id=b,
            effective_from=CHANGE_FROM,
            extra={
                "confirm_pending_request_impact": True,
                "pending_impact_token": fresh["impact_token"],
            },
        )
        assert accepted.status_code == 201, accepted.text
    finally:
        await teardown_world(company_id=company_id, user_id=user_id)


@pytest.mark.parametrize("change_type", ["MANAGER_CHANGE", "TRANSFER"])
async def test_removal_and_any_change_type_that_alters_the_manager_are_gated(
    client: AsyncClient, seeded_plan_catalogue: None, change_type: str
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        world = await build_world(client, headers)
        a, b, e = world["a"]["id"], world["b"]["id"], world["e"]["id"]
        await submit_leave(client, headers, world, LEAVE_BEFORE)

        removal = await post_manager_change(
            client, headers, e, manager_id=None, effective_from=CHANGE_FROM
        )
        relabelled = await client.post(
            f"/v1/employees/{e}/assignments",
            headers={
                **headers,
                "If-Match": str((await current_assignment(client, headers, e))["version"]),
            },
            json={
                "effective_from": CHANGE_FROM,
                "change_type": change_type,
                "reporting_manager_id": b,
            },
        )

        for response in (removal, relabelled):
            assert response.status_code == 409, response.text
            assert response.json()["error"]["code"] == CONFIRMATION_REQUIRED
        assert (await current_assignment(client, headers, e))["reporting_manager_id"] == a
    finally:
        await teardown_world(company_id=company_id, user_id=user_id)


async def test_changes_that_leave_the_manager_alone_are_never_gated(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        world = await build_world(client, headers)
        a, e = world["a"]["id"], world["e"]["id"]
        await submit_leave(client, headers, world, LEAVE_BEFORE)

        transfer = await post_manager_change(
            client,
            headers,
            e,
            manager_id=a,
            effective_from=CHANGE_FROM,
            extra={"change_type": "TRANSFER"},
        )
        assert transfer.status_code == 201, transfer.text
        carried = await client.post(
            f"/v1/employees/{e}/assignments",
            headers={
                **headers,
                "If-Match": str((await current_assignment(client, headers, e))["version"]),
            },
            json={"effective_from": "2026-10-15", "change_type": "TRANSFER"},
        )
        assert carried.status_code == 201, carried.text
        assert carried.json()["data"]["reporting_manager_id"] == a
    finally:
        await teardown_world(company_id=company_id, user_id=user_id)


# --- Who may look, and what they can learn ---------------------------------------------------


async def test_the_preview_requires_login_and_the_permission_to_make_the_change(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        world = await build_world(client, headers)
        b, e = world["b"]["id"], world["e"]["id"]
        await submit_leave(client, headers, world, LEAVE_BEFORE)

        anonymous = await client.get(
            f"/v1/employees/{e}/manager-change-impact", params={"reporting_manager_id": b}
        )
        viewer_only, _ = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=["EMPLOYEE.VIEW"], data_scope="COMPANY"
        )
        # The default manager role can approve requests and view its team - it cannot re-point
        # reporting lines, so it cannot see this either.
        a_headers = await manager_headers(company_id, world["a"]["id"])
        hr, _ = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=["EMPLOYEE.TRANSFER"], data_scope="COMPANY"
        )

        assert anonymous.status_code == 401, anonymous.text
        for who, denied in (("viewer", viewer_only), ("manager", a_headers)):
            response = await _impact(client, denied, e, manager_id=b)
            assert response.status_code == 403, (who, response.text)
            assert "total_pending_requests" not in response.text
        allowed = await _impact(client, hr, e, manager_id=b)
        assert allowed.status_code == 200, allowed.text
        assert allowed.json()["data"]["total_pending_requests"] == 1
    finally:
        await teardown_world(company_id=company_id, user_id=user_id)


async def test_the_preview_cannot_be_aimed_at_employees_outside_the_callers_scope_or_tenant(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        world_a = await build_world(client, headers_a)
        world_b = await build_world(client, headers_b)
        await submit_leave(client, headers_a, world_a, LEAVE_BEFORE)
        await submit_leave(client, headers_b, world_b, LEAVE_BEFORE)
        e_a, e_b = world_a["e"]["id"], world_b["e"]["id"]

        # Cross-tenant, both directions: indistinguishable from an id that does not exist.
        a_to_b = await _impact(client, headers_a, e_b, manager_id=world_a["b"]["id"])
        b_to_a = await _impact(client, headers_b, e_a, manager_id=world_b["b"]["id"])
        nonexistent = await _impact(
            client, headers_a, "00000000-0000-4000-8000-000000000000", manager_id=None
        )
        for response in (a_to_b, b_to_a, nonexistent):
            assert response.status_code == 404, response.text
            assert "total_pending_requests" not in response.text
        # ...and each tenant still sees only its own figures.
        own = await _impact_data(client, headers_a, e_a, manager_id=world_a["b"]["id"])
        assert own["total_pending_requests"] == 1

        # In-tenant IDOR: a transfer-capable caller limited to their own reports cannot probe
        # someone else's pending requests by swapping the id.
        limited, _ = await _create_permission_scoped_user(
            company_id=company_a,
            permission_codes=["EMPLOYEE.TRANSFER"],
            data_scope="REPORTEES",
            caller_employee_id=UUID(world_a["b"]["id"]),
        )
        outside = await _impact(client, limited, e_a, manager_id=None)
        assert outside.status_code == 404, outside.text
        assert "total_pending_requests" not in outside.text
    finally:
        await teardown_world(company_id=company_a, user_id=user_a)
        await teardown_world(company_id=company_b, user_id=user_b)
