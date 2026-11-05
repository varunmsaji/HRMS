"""How a change of reporting manager interacts with Leave, Regularization and Overtime approvals.

The business rule under test:

    A pending request stays with the approver resolved when it was created. Changing the
    employee's reporting manager affects requests created afterwards only.

Several tests are *characterizations*: they pin down what the system does today, including the
parts that are subtle or not what a reader would assume (see the module-level notes on each).
"""

from typing import Any

import pytest
from httpx import AsyncClient

from .manager_change_support import (
    CHANGE_FROM,
    LEAVE_AFTER,
    LEAVE_BEFORE,
    REG_AFTER,
    REG_BEFORE,
    REG_BEFORE_OTHER,
    approve,
    build_world,
    change_manager,
    detect_overtime,
    fetch,
    manager_headers,
    recalculate_day,
    submit_leave,
    submit_regularization,
    teardown_world,
)
from .test_employee_assignment import _register_tenant

pytestmark = pytest.mark.asyncio


def _resolved(request: dict[str, Any]) -> str | None:
    return request.get("resolved_approver_manager_id")


# --- Reassignment: the snapshot --------------------------------------------------------------


async def test_leave_pending_request_stays_with_the_original_manager_after_reassignment(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        world = await build_world(client, headers)
        a, b, e = world["a"]["id"], world["b"]["id"], world["e"]["id"]
        pending = await submit_leave(client, headers, world, LEAVE_BEFORE)
        assert (pending["approval_stage"], _resolved(pending)) == ("MANAGER", a)

        moved = await change_manager(client, headers, e, manager_id=b, effective_from=CHANGE_FROM)
        assert moved.status_code == 201, moved.text

        # The existing request did not move...
        again = await fetch(client, headers, "leave", pending["id"])
        assert _resolved(again) == a
        # ...so B cannot decide it, and A still can.
        b_headers = await manager_headers(company_id, b)
        assert (await approve(client, b_headers, "leave", again)).status_code == 403
        a_headers = await manager_headers(company_id, a)
        decided = await approve(client, a_headers, "leave", again)
        assert decided.status_code == 200, decided.text
    finally:
        await teardown_world(company_id=company_id, user_id=user_id)


async def test_leave_new_requests_resolve_the_manager_in_force_on_the_leave_start_date(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Characterization. The approver is looked up *as of the leave's start date*, not as of the
    day it is submitted. After the change takes effect on 2026-10-01: a new request for a date on
    or after it goes to the new manager, but a new request for an earlier date still goes to the
    old one."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        world = await build_world(client, headers)
        a, b, e = world["a"]["id"], world["b"]["id"], world["e"]["id"]
        moved = await change_manager(client, headers, e, manager_id=b, effective_from=CHANGE_FROM)
        assert moved.status_code == 201, moved.text

        later_date = await submit_leave(client, headers, world, LEAVE_AFTER)
        earlier_date = await submit_leave(client, headers, world, LEAVE_BEFORE)

        assert _resolved(later_date) == b
        assert _resolved(earlier_date) == a
    finally:
        await teardown_world(company_id=company_id, user_id=user_id)


async def test_regularization_pending_request_stays_with_the_original_manager(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        world = await build_world(client, headers)
        a, b, e = world["a"]["id"], world["b"]["id"], world["e"]["id"]
        pending = await submit_regularization(client, headers, world, REG_BEFORE)
        assert (pending["approval_stage"], _resolved(pending)) == ("MANAGER", a)

        moved = await change_manager(client, headers, e, manager_id=b, effective_from=CHANGE_FROM)
        assert moved.status_code == 201, moved.text

        again = await fetch(client, headers, "reg", pending["id"])
        assert _resolved(again) == a
        b_headers = await manager_headers(company_id, b)
        assert (await approve(client, b_headers, "reg", again)).status_code == 403
        # New requests: by attendance date, same as-of rule as leave.
        assert _resolved(await submit_regularization(client, headers, world, REG_AFTER)) == b
        assert _resolved(await submit_regularization(client, headers, world, REG_BEFORE_OTHER)) == a
        a_headers = await manager_headers(company_id, a)
        decided = await approve(client, a_headers, "reg", again)
        assert decided.status_code == 200, decided.text
    finally:
        await teardown_world(company_id=company_id, user_id=user_id)


async def test_overtime_pending_record_stays_when_the_change_is_after_the_overtime_day(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        world = await build_world(client, headers)
        a, b, e = world["a"]["id"], world["b"]["id"], world["e"]["id"]
        pending = await detect_overtime(client, headers, world)
        assert (pending["status"], pending["approval_stage"], _resolved(pending)) == (
            "PENDING",
            "MANAGER",
            a,
        )

        moved = await change_manager(client, headers, e, manager_id=b, effective_from=CHANGE_FROM)
        assert moved.status_code == 201, moved.text
        await recalculate_day(client, headers, world)

        record = await fetch(client, headers, "ot", pending["id"])
        assert _resolved(record) == a  # the day (08-10) precedes the change (10-01)
        a_headers = await manager_headers(company_id, a)
        assert (await approve(client, a_headers, "ot", record)).status_code == 200
    finally:
        await teardown_world(company_id=company_id, user_id=user_id)


async def test_overtime_pending_record_is_not_re_resolved_by_a_backdated_change(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A manager change effective *on or before* the overtime day, followed by anything that
    recalculates that day while the record is still PENDING, must not move the record: it stays
    with the approver it was created for."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        world = await build_world(client, headers)
        a, b, e = world["a"]["id"], world["b"]["id"], world["e"]["id"]
        pending = await detect_overtime(client, headers, world)
        assert _resolved(pending) == a

        moved = await change_manager(client, headers, e, manager_id=b, effective_from="2026-08-01")
        assert moved.status_code == 201, moved.text
        await recalculate_day(client, headers, world)

        record = await fetch(client, headers, "ot", pending["id"])
        assert record["status"] == "PENDING"
        assert _resolved(record) == a
        b_headers = await manager_headers(company_id, b)
        assert (await approve(client, b_headers, "ot", record)).status_code == 403
    finally:
        await teardown_world(company_id=company_id, user_id=user_id)


async def test_overtime_recalculation_keeps_a_partly_approved_chain_at_hr(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A recalculation that leaves the detected minutes unchanged does not undo the manager's step
    of a two-stage chain (N-2, a business decision that replaced the earlier restart). The record
    keeps its approver, and that manager cannot act on it again."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        world = await build_world(client, headers, ot_chain="MANAGER_THEN_HR")
        a = world["a"]["id"]
        pending = await detect_overtime(client, headers, world)
        assert (pending["approval_chain"], pending["approval_stage"]) == (
            "MANAGER_THEN_HR",
            "MANAGER",
        )
        a_headers = await manager_headers(company_id, a)
        assert (await approve(client, a_headers, "ot", pending)).status_code == 200
        at_hr = await fetch(client, headers, "ot", pending["id"])
        assert (at_hr["status"], at_hr["approval_stage"]) == ("PENDING", "HR")

        await recalculate_day(client, headers, world)

        after = await fetch(client, headers, "ot", pending["id"])
        assert (after["status"], after["approval_stage"]) == ("PENDING", "HR")
        assert _resolved(after) == a
        assert (await approve(client, a_headers, "ot", after)).status_code == 403
    finally:
        await teardown_world(company_id=company_id, user_id=user_id)


# --- Removal ---------------------------------------------------------------------------------


async def test_pending_requests_survive_manager_removal_and_new_ones_route_to_hr(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        world = await build_world(client, headers)
        a, e = world["a"]["id"], world["e"]["id"]
        leave = await submit_leave(client, headers, world, LEAVE_BEFORE)
        reg = await submit_regularization(client, headers, world, REG_BEFORE)
        ot = await detect_overtime(client, headers, world)

        removed = await change_manager(
            client, headers, e, manager_id=None, effective_from=CHANGE_FROM
        )
        assert removed.status_code == 201, removed.text
        await recalculate_day(client, headers, world)

        # Existing requests keep their approver and are not stuck.
        for kind, request in (("leave", leave), ("reg", reg), ("ot", ot)):
            current = await fetch(client, headers, kind, request["id"])
            assert (current["approval_stage"], _resolved(current)) == ("MANAGER", a), kind
        a_headers = await manager_headers(company_id, a)
        for kind, request in (("leave", leave), ("reg", reg), ("ot", ot)):
            current = await fetch(client, headers, kind, request["id"])
            decided = await approve(client, a_headers, kind, current)
            assert decided.status_code == 200, (kind, decided.text)

        # New requests dated after the removal have nobody to ask, so they go to HR.
        after_leave = await submit_leave(client, headers, world, LEAVE_AFTER)
        after_reg = await submit_regularization(client, headers, world, REG_AFTER)
        for request in (after_leave, after_reg):
            assert (request["approval_stage"], _resolved(request)) == ("HR", None)
        hr_decision = await approve(client, headers, "leave", after_leave)
        assert hr_decision.status_code == 200, hr_decision.text
    finally:
        await teardown_world(company_id=company_id, user_id=user_id)


# --- An approver who can no longer act -------------------------------------------------------


async def test_when_the_approver_leaves_leave_can_be_reassigned_but_attendance_requests_cannot(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Characterization of an existing gap. Leave has an HR "reassign approver" action for a
    stage whose approver can no longer act. Regularization and Overtime have nothing equivalent:
    HR (company-wide approve grant) is refused at the MANAGER stage, so the request waits for a
    person who is gone."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        world = await build_world(client, headers)
        a, b = world["a"]["id"], world["b"]["id"]
        leave = await submit_leave(client, headers, world, LEAVE_BEFORE)
        reg = await submit_regularization(client, headers, world, REG_BEFORE)
        ot = await detect_overtime(client, headers, world)

        live = await client.get(f"/v1/employees/{a}", headers=headers)
        left = await client.delete(
            f"/v1/employees/{a}",
            headers={**headers, "If-Match": str(live.json()["data"]["version"])},
        )
        assert left.status_code == 200, left.text

        for kind, request in (("reg", reg), ("ot", ot)):
            refused = await approve(client, headers, kind, request)
            assert refused.status_code == 403, (kind, refused.text)
            assert refused.json()["error"]["code"].endswith("APPROVER_MISMATCH")

        # Leave: the current approver is ineligible, so HR may hand the stage to someone else.
        b_headers = await manager_headers(company_id, b)
        reassigned = await client.post(
            f"/v1/leave-applications/{leave['id']}/reassign-approver",
            headers={**headers, "If-Match": str(leave["version"])},
            json={"new_approver_employee_id": b, "reason": "Manager left the company"},
        )
        assert reassigned.status_code == 200, reassigned.text
        moved = await fetch(client, headers, "leave", leave["id"])
        assert _resolved(moved) == b
        assert (await approve(client, b_headers, "leave", moved)).status_code == 200
    finally:
        await teardown_world(company_id=company_id, user_id=user_id)


# --- Notice period ---------------------------------------------------------------------------


async def test_notice_period_employee_drops_out_of_the_managers_view_but_requests_remain_decidable(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Characterization of the previously-suspected defect.

    Recording a termination with a *future* last working day closes the employee's assignment
    immediately. Everything that decides "is this my report?" from the current assignment then
    stops matching, although the person is still employed. The approval itself keeps working
    because it compares the caller to the snapshotted approver, not to the reporting tree.
    """
    headers, company_id, user_id = await _register_tenant(client)
    try:
        world = await build_world(client, headers)
        a, e = world["a"]["id"], world["e"]["id"]
        leave = await submit_leave(client, headers, world, LEAVE_BEFORE)
        reg = await submit_regularization(client, headers, world, REG_BEFORE)
        ot = await detect_overtime(client, headers, world)
        a_headers = await manager_headers(company_id, a)

        async def view(path: str) -> int:
            return (await client.get(path, headers=a_headers)).status_code

        # Control: while the employee is simply working, A sees them everywhere.
        assert await view(f"/v1/employees/{e}") == 200
        team = await client.get(f"/v1/employees/{a}/direct-reports", headers=a_headers)
        assert e in {row["employee_id"] for row in team.json()["data"]}
        assert await view(f"/v1/leave-applications/{leave['id']}") == 200

        employments = (await client.get(f"/v1/employees/{e}/employments", headers=headers)).json()[
            "data"
        ]
        terminated = await client.post(
            f"/v1/employees/{e}/employments/{employments[0]['id']}/terminate",
            headers={**headers, "If-Match": str(employments[0]["version"])},
            json={"last_working_day": "2026-12-31"},
        )
        assert terminated.status_code == 200, terminated.text

        # Reproduced: the employee is gone from A's team and A can no longer open any record,
        # although 2026-12-31 is two months away.
        team = await client.get(f"/v1/employees/{a}/direct-reports", headers=a_headers)
        assert e not in {row["employee_id"] for row in team.json()["data"]}
        assert await view(f"/v1/employees/{e}") == 404
        assert await view(f"/v1/leave-applications/{leave['id']}") == 404

        # ...but A can still decide every pending request by id.
        for kind, request in (("leave", leave), ("reg", reg), ("ot", ot)):
            current = await fetch(client, headers, kind, request["id"])
            decided = await approve(client, a_headers, kind, current)
            assert decided.status_code == 200, (kind, decided.text)
    finally:
        await teardown_world(company_id=company_id, user_id=user_id)


# --- Future-dated manager change -------------------------------------------------------------


async def test_future_dated_manager_change_flips_visibility_at_once_but_not_approval_routing(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Characterization of the previously-suspected defect.

    A manager change dated in the future closes the current assignment immediately and the new
    one is already "current". Approval routing is looked up by date and is correct; the
    reporting-tree visibility (direct reports, data scope) is not, so the new manager gains the
    employee early and the old manager loses them early.
    """
    headers, company_id, user_id = await _register_tenant(client)
    try:
        world = await build_world(client, headers)
        a, b, e = world["a"]["id"], world["b"]["id"], world["e"]["id"]
        future = "2027-01-15"
        moved = await change_manager(client, headers, e, manager_id=b, effective_from=future)
        assert moved.status_code == 201, moved.text

        team_a = await client.get(f"/v1/employees/{a}/direct-reports", headers=headers)
        team_b = await client.get(f"/v1/employees/{b}/direct-reports", headers=headers)
        # Reproduced: B already has E, A already lost them, months before the change date.
        assert e not in {row["employee_id"] for row in team_a.json()["data"]}
        assert e in {row["employee_id"] for row in team_b.json()["data"]}

        # Approval routing is date-correct.
        before = await submit_leave(client, headers, world, "2026-11-10")
        after = await submit_leave(client, headers, world, "2027-02-02")
        assert _resolved(before) == a
        assert _resolved(after) == b

        # The history is what the date implies.
        rows = (await client.get(f"/v1/employees/{e}/assignments", headers=headers)).json()["data"]
        assert [(r["effective_from"], r["effective_to"]) for r in rows][-2:] == [
            ("2026-01-01", "2027-01-14"),
            (future, None),
        ]
    finally:
        await teardown_world(company_id=company_id, user_id=user_id)


# --- Existing guarantees (cross-references, not duplicated here) -----------------------------

#   self-approval is blocked:   test_overtime_record / test_regularization / test_leave_application
#                               ::test_self_approval_blocked
#   wrong manager is refused:   ::test_wrong_manager_cannot_approve (overtime, regularization)
#                               and test_leave_approval_hod
#   cross-tenant is invisible:  ::test_cross_tenant_*_returns_404
