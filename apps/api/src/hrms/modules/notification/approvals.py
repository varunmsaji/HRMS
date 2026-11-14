"""Notifications for the staged approval workflows (leave, attendance regularization, overtime).

All three store a request the same way: `employee_id`, `status`, `approval_stage`
(`MANAGER` | `HOD` | `HR` | NULL once decided) and the reviewers snapshotted at submit time. So one
function, called by the owning service right after each state change, works out who to tell
from the row as it now stands:

* still awaiting a decision -> the reviewer(s) of the current stage: the snapshotted manager or
  department head, or for the HR stage everyone holding the module's approve permission
  company-wide (the same people the API lets act on it);
* decided (approved / applied / rejected / cancelled) -> the employee.

Earlier "awaiting your approval" notifications for the request are marked read first, so the
previous stage's reviewer is not left with a stale call to action. Whoever performed the action
is never notified about their own action.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.modules.notification.producer import (
    employee_name,
    employee_user_id,
    notify,
    permission_holder_user_ids,
    settle,
)
from hrms.modules.notification.types import (
    LEAVE_APPROVAL_REQUESTED,
    LEAVE_DECIDED,
    OVERTIME_APPROVAL_REQUESTED,
    OVERTIME_DECIDED,
    REGULARIZATION_APPROVAL_REQUESTED,
    REGULARIZATION_DECIDED,
    NotificationType,
)

#: Status -> the word used in "Your leave request was ...". `APPLIED` is a regularization that
#: was approved and then written onto the attendance day.
_DECIDED = {
    "APPROVED": "approved",
    "APPLIED": "approved",
    "REJECTED": "rejected",
    "CANCELLED": "cancelled",
}


def fmt_date(value: date) -> str:
    return f"{value.day} {value.strftime('%b %Y')}"


def _days(value: Any) -> str:
    n = float(value)
    shown = f"{n:g}"
    return f"{shown} day" if n == 1 else f"{shown} days"


def _minutes(value: int) -> str:
    hours, minutes = divmod(int(value), 60)
    if hours and minutes:
        return f"{hours}h {minutes}m"
    return f"{hours}h" if hours else f"{minutes}m"


@dataclass(frozen=True)
class ApprovalFlow:
    #: Trusted table name (only ever one of the constants below), never user input.
    table: str
    entity_type: str
    noun: str
    path: str
    approve_permission: str
    pending: NotificationType
    decided: NotificationType
    extra_columns: str
    describe: Callable[[Any], str]
    has_hod: bool = False


LEAVE_FLOW = ApprovalFlow(
    table="leave_application",
    entity_type="leave_application",
    noun="leave request",
    path="/app/leave-applications",
    approve_permission="LEAVE.APPLICATION_APPROVE",
    pending=LEAVE_APPROVAL_REQUESTED,
    decided=LEAVE_DECIDED,
    extra_columns="start_date, end_date, total_days",
    describe=lambda r: (
        f"{_days(r.total_days)} of leave on {fmt_date(r.start_date)}"
        if r.start_date == r.end_date
        else f"{_days(r.total_days)} of leave, {fmt_date(r.start_date)} to {fmt_date(r.end_date)}"
    ),
    has_hod=True,
)

REGULARIZATION_FLOW = ApprovalFlow(
    table="attendance_regularization_request",
    entity_type="attendance_regularization_request",
    noun="attendance correction",
    path="/app/regularizations",
    approve_permission="ATTENDANCE.REGULARIZATION_APPROVE",
    pending=REGULARIZATION_APPROVAL_REQUESTED,
    decided=REGULARIZATION_DECIDED,
    extra_columns="attendance_date",
    describe=lambda r: f"Attendance correction for {fmt_date(r.attendance_date)}",
)

OVERTIME_FLOW = ApprovalFlow(
    table="overtime_record",
    entity_type="overtime_record",
    noun="overtime",
    path="/app/overtime",
    approve_permission="ATTENDANCE.OVERTIME_APPROVE",
    pending=OVERTIME_APPROVAL_REQUESTED,
    decided=OVERTIME_DECIDED,
    extra_columns="attendance_date, minutes_detected",
    describe=lambda r: (
        f"{_minutes(r.minutes_detected)} of overtime on {fmt_date(r.attendance_date)}"
    ),
)


async def _stage_reviewers(
    session: AsyncSession, flow: ApprovalFlow, company_id: UUID, row: Any
) -> list[UUID]:
    stage = row.approval_stage
    snapshot: UUID | None = None
    if stage == "MANAGER":
        snapshot = row.resolved_approver_manager_id
    elif stage == "HOD" and flow.has_hod:
        snapshot = row.resolved_department_head_id
    if snapshot is not None:
        user_id = await employee_user_id(session, company_id, snapshot)
        if user_id is not None:
            return [user_id]
    # HR stage, or a reviewer with no login: the people who can act on it company-wide.
    return await permission_holder_user_ids(session, company_id, flow.approve_permission)


async def notify_approval_change(
    session: AsyncSession,
    flow: ApprovalFlow,
    *,
    company_id: UUID,
    entity_id: UUID,
    actor_user_id: UUID | None,
) -> None:
    """Call after every state change of a request in `flow` (submit, stage approval, final
    approval, rejection, cancellation, reviewer reassignment)."""
    hod = ", resolved_department_head_id" if flow.has_hod else ""
    row = (
        await session.execute(
            text(
                f"SELECT employee_id, status, approval_stage, resolved_approver_manager_id{hod},"
                f" {flow.extra_columns} FROM {flow.table} WHERE id = :id AND company_id = :cid"
            ),
            {"id": entity_id, "cid": company_id},
        )
    ).first()
    if row is None:
        return

    await settle(
        session,
        company_id=company_id,
        entity_type=flow.entity_type,
        entity_id=entity_id,
        types=(flow.pending,),
    )
    employee_user = await employee_user_id(session, company_id, row.employee_id)
    summary = flow.describe(row)
    action_url = f"{flow.path}/{entity_id}"

    outcome = _DECIDED.get(row.status)
    if outcome is not None:
        await notify(
            session,
            company_id=company_id,
            recipients=[employee_user],
            exclude=[actor_user_id],
            type=flow.decided,
            title=f"Your {flow.noun} was {outcome}",
            body=f"{summary}.",
            dedupe_key=f"{flow.decided.code}:{entity_id}:{outcome}",
            entity_type=flow.entity_type,
            entity_id=entity_id,
            action_url=action_url,
            action_label="View",
            metadata={"status": row.status},
        )
        return

    if row.approval_stage is None:
        return
    reviewers = await _stage_reviewers(session, flow, company_id, row)
    name = await employee_name(session, company_id, row.employee_id)
    await notify(
        session,
        company_id=company_id,
        recipients=reviewers,
        exclude=[actor_user_id, employee_user],
        type=flow.pending,
        title=f"{flow.noun[0].upper()}{flow.noun[1:]} awaiting your approval",
        body=f"{name}: {summary}.",
        dedupe_key=f"{flow.pending.code}:{entity_id}:{row.approval_stage}",
        entity_type=flow.entity_type,
        entity_id=entity_id,
        action_url=action_url,
        action_label="Review",
        metadata={"stage": row.approval_stage},
    )
