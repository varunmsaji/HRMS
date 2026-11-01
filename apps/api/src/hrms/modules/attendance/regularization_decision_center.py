"""Regularization decision-center read model (`GET /v1/regularizations/decision-center`).

Read-only aggregation for the approver screen: headline figures, tab counts and, per request, what
the system recorded for the day beside the punches the employee asked for. Nothing here approves,
rejects or writes - deciding stays on the existing `/regularizations/{id}/approve|reject` routes -
and no figure is invented: hours after the correction are not guessed (the engine recomputes them
on approval), only the requested span between the first requested IN and last requested OUT."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

RegularizationTab = Literal["pending", "approved", "declined"]

_TAB_STATUSES: dict[str, tuple[str, ...]] = {
    "pending": ("SUBMITTED",),
    "approved": ("APPROVED",),
    "declined": ("REJECTED", "CANCELLED"),
}

_NAME = (
    "coalesce(nullif({a}.display_name, ''), "
    "trim({a}.first_name || ' ' || coalesce({a}.last_name, '')))"
)
# Day statuses that carry no expectation to work; excluded from the regularization rate.
_NOT_EXPECTED = ("NOT_EXPECTED", "NOT_JOINED", "EXITED")


class RegularizationSummary(BaseModel):
    pending_count: int
    oldest_pending_at: datetime | None
    window_regularized_days: int
    window_expected_days: int
    window_rate_pct: (
        float | None
    )  # regularized / expected days over the last 30 days; None with no days


class RegularizationTabCounts(BaseModel):
    pending: int
    approved: int
    declined: int


class RequestedPunch(BaseModel):
    direction: str
    time: datetime


class RegularizationItem(BaseModel):
    id: UUID
    version: int
    employee_id: UUID
    employee_name: str
    employee_code: str
    designation: str | None
    department: str | None
    attendance_date: date
    timezone: str | None
    shift_name: str | None
    request_type: str
    status: str
    approval_stage: str | None
    submitted_at: datetime
    reason: str | None
    # What the system holds for that day today.
    recorded_first_in: datetime | None
    recorded_last_out: datetime | None
    recorded_worked_minutes: int | None
    recorded_late_minutes: int | None
    recorded_status: str | None
    recorded_missing_punch: bool | None
    # What the employee asked for.
    requested_punches: list[RequestedPunch]
    requested_span_minutes: int | None


class RegularizationDecisionCenter(BaseModel):
    today: date
    summary: RegularizationSummary
    counts: RegularizationTabCounts
    tab: RegularizationTab
    items: list[RegularizationItem]


def requested_span_minutes(
    punches: list[RequestedPunch],
    recorded_first_in: datetime | None = None,
    recorded_last_out: datetime | None = None,
) -> int | None:
    """Minutes from the earliest IN to the latest OUT the day would have if the request were
    applied: requested punches win, and whichever side was not requested falls back to what is
    already recorded. None when either side is unknown or the OUT is not after the IN."""
    ins = [p.time for p in punches if p.direction == "IN"] or (
        [recorded_first_in] if recorded_first_in else []
    )
    outs = [p.time for p in punches if p.direction == "OUT"] or (
        [recorded_last_out] if recorded_last_out else []
    )
    if not ins or not outs:
        return None
    span = int((max(outs) - min(ins)).total_seconds() // 60)
    return span if span > 0 else None


async def build_regularization_decision_center(
    session: AsyncSession,
    company_id: UUID,
    visible_ids: frozenset[UUID] | None,
    *,
    tab: RegularizationTab = "pending",
    limit: int = 50,
) -> RegularizationDecisionCenter:
    params: dict[str, object] = {"cid": company_id}
    scope = ""
    day_scope = ""
    if visible_ids is not None:
        scope = "AND r.employee_id = ANY(:ids)"
        day_scope = "AND ad.employee_id = ANY(:ids)"
        params["ids"] = list(visible_ids)

    today = (
        await session.execute(
            text(
                "SELECT (now() AT TIME ZONE coalesce(c.timezone, 'UTC'))::date "
                "FROM company c WHERE c.id = :cid"
            ),
            params,
        )
    ).scalar_one_or_none() or date.today()
    p = {**params, "today": today}

    cnt = (
        await session.execute(
            text(
                f"""
                SELECT count(*) FILTER (WHERE r.status = 'SUBMITTED') AS pending,
                       count(*) FILTER (WHERE r.status = 'APPROVED') AS approved,
                       count(*) FILTER (WHERE r.status IN ('REJECTED', 'CANCELLED')) AS declined,
                       min(r.submitted_at) FILTER (WHERE r.status = 'SUBMITTED') AS oldest
                FROM attendance_regularization_request r
                WHERE r.company_id = :cid {scope}
                """
            ),
            p,
        )
    ).one()

    window = (
        await session.execute(
            text(
                f"""
                SELECT count(*) FILTER (WHERE ad.is_regularized) AS regularized,
                       count(*) AS expected
                FROM attendance_day ad
                WHERE ad.company_id = :cid
                  AND ad.attendance_date > CAST(:today AS date) - 30
                  AND ad.attendance_date <= :today
                  AND ad.attendance_status <> ALL(:skip) {day_scope}
                """
            ),
            {**p, "skip": list(_NOT_EXPECTED)},
        )
    ).one()
    expected = int(window.expected)

    rows = (
        await session.execute(
            text(
                f"""
                SELECT r.id, r.version, r.employee_id, {_NAME.format(a="e")} AS emp_name,
                       e.employee_code, dg.title AS designation, d.name AS department,
                       r.attendance_date, ad.timezone, s.name AS shift_name, r.request_type,
                       r.status, r.approval_stage, r.submitted_at, r.reason,
                       ad.actual_first_in, ad.actual_last_out, ad.worked_minutes,
                       ad.late_minutes, ad.attendance_status, ad.missing_punch,
                       ad.id AS day_id
                FROM attendance_regularization_request r
                JOIN employee e ON e.id = r.employee_id
                LEFT JOIN attendance_day ad
                       ON ad.company_id = r.company_id AND ad.employee_id = r.employee_id
                      AND ad.attendance_date = r.attendance_date
                LEFT JOIN shift s ON s.id = coalesce(r.requested_shift_id, ad.shift_id)
                LEFT JOIN employee_assignment a ON a.employee_id = e.id AND a.effective_to IS NULL
                LEFT JOIN designation dg ON dg.id = a.designation_id
                LEFT JOIN department d ON d.id = a.department_id
                WHERE r.company_id = :cid AND r.status = ANY(:statuses) {scope}
                ORDER BY r.submitted_at {"ASC" if tab == "pending" else "DESC"}
                LIMIT :lim
                """
            ),
            {**p, "statuses": list(_TAB_STATUSES[tab]), "lim": limit},
        )
    ).all()

    punches: dict[UUID, list[RequestedPunch]] = {}
    if rows:
        for r in (
            await session.execute(
                text(
                    """
                    SELECT request_id, direction, requested_time
                    FROM attendance_regularization_requested_punch
                    WHERE request_id = ANY(:ids) ORDER BY sort_order, requested_time
                    """
                ),
                {"ids": [r.id for r in rows]},
            )
        ).all():
            punches.setdefault(r.request_id, []).append(
                RequestedPunch(direction=r.direction, time=r.requested_time)
            )

    items = []
    for r in rows:
        has_day = r.day_id is not None
        req = punches.get(r.id, [])
        items.append(
            RegularizationItem(
                id=r.id,
                version=r.version,
                employee_id=r.employee_id,
                employee_name=r.emp_name,
                employee_code=r.employee_code,
                designation=r.designation,
                department=r.department,
                attendance_date=r.attendance_date,
                timezone=r.timezone,
                shift_name=r.shift_name,
                request_type=r.request_type,
                status=r.status,
                approval_stage=r.approval_stage,
                submitted_at=r.submitted_at,
                reason=r.reason,
                recorded_first_in=r.actual_first_in,
                recorded_last_out=r.actual_last_out,
                recorded_worked_minutes=r.worked_minutes if has_day else None,
                recorded_late_minutes=r.late_minutes if has_day else None,
                recorded_status=r.attendance_status,
                recorded_missing_punch=r.missing_punch if has_day else None,
                requested_punches=req,
                requested_span_minutes=requested_span_minutes(
                    req, r.actual_first_in, r.actual_last_out
                ),
            )
        )

    return RegularizationDecisionCenter(
        today=today,
        summary=RegularizationSummary(
            pending_count=int(cnt.pending),
            oldest_pending_at=cnt.oldest,
            window_regularized_days=int(window.regularized),
            window_expected_days=expected,
            window_rate_pct=round(100 * int(window.regularized) / expected, 1)
            if expected
            else None,
        ),
        counts=RegularizationTabCounts(
            pending=int(cnt.pending), approved=int(cnt.approved), declined=int(cnt.declined)
        ),
        tab=tab,
        items=items,
    )
