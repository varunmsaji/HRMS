"""Leave decision-center read model (`GET /v1/leave-applications/decision-center`).

Read-only aggregation for the approver screen: headline figures, tab counts and, per request, the
employee's current balance, the post-approval balance and the colleagues in the same department who
are also away. Nothing here approves, rejects or writes - approving stays on the existing
`/leave-applications/{id}/approve|reject` routes - and no figure is invented: a department-less
employee simply has no clash information."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

DecisionTab = Literal["pending", "approved", "declined"]

_TAB_STATUSES: dict[str, tuple[str, ...]] = {
    "pending": ("SUBMITTED",),
    "approved": ("APPROVED",),
    "declined": ("REJECTED", "CANCELLED"),
}

_NAME = (
    "coalesce(nullif({a}.display_name, ''), "
    "trim({a}.first_name || ' ' || coalesce({a}.last_name, '')))"
)


class DecisionSummary(BaseModel):
    pending_count: int
    oldest_pending_at: datetime | None
    on_leave_today: int
    on_leave_today_by_type: list[tuple[str, int]]
    active_staff: int
    available_pct: float | None  # share of active staff not on leave today; None without staff
    upcoming_starts_7d: int  # approved leaves starting in the next 7 days
    peak_day: date | None  # day in that window with the most people away
    peak_day_away: int


class DecisionTabCounts(BaseModel):
    pending: int
    approved: int
    declined: int


class Colleague(BaseModel):
    name: str
    start_date: date
    end_date: date
    status: str


class DecisionItem(BaseModel):
    id: UUID
    version: int
    employee_id: UUID
    employee_name: str
    employee_code: str
    designation: str | None
    department: str | None
    leave_type_id: UUID
    leave_type: str
    start_date: date
    end_date: date
    total_days: Decimal
    lop_days: Decimal
    reason: str | None
    status: str
    approval_stage: str | None
    submitted_at: datetime
    # Ledger balance for this leave type now. A pending request is only deducted on approval
    # (unless the policy reserves on submission), so the post-approval figure is this minus the
    # paid days; None when the type carries no balance.
    current_balance: Decimal | None
    post_approval_balance: Decimal | None
    department_size: int | None
    colleagues_away: list[Colleague]


class DecisionCenter(BaseModel):
    today: date
    summary: DecisionSummary
    counts: DecisionTabCounts
    tab: DecisionTab
    items: list[DecisionItem]


async def build_decision_center(
    session: AsyncSession,
    company_id: UUID,
    visible_ids: frozenset[UUID] | None,
    *,
    tab: DecisionTab = "pending",
    limit: int = 50,
) -> DecisionCenter:
    params: dict[str, object] = {"cid": company_id}
    scope = ""
    if visible_ids is not None:
        scope = "AND la.employee_id = ANY(:ids)"
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

    # -- tab counts + the oldest pending request ---------------------------------------------
    cnt = (
        await session.execute(
            text(
                f"""
                SELECT count(*) FILTER (WHERE la.status = 'SUBMITTED') AS pending,
                       count(*) FILTER (WHERE la.status = 'APPROVED') AS approved,
                       count(*) FILTER (WHERE la.status IN ('REJECTED', 'CANCELLED')) AS declined,
                       min(la.submitted_at) FILTER (WHERE la.status = 'SUBMITTED') AS oldest
                FROM leave_application la
                WHERE la.company_id = :cid {scope}
                """
            ),
            p,
        )
    ).one()

    # -- who is away today, by leave type ------------------------------------------------------
    away = (
        await session.execute(
            text(
                f"""
                SELECT lt.name, count(DISTINCT la.employee_id) AS n
                FROM leave_application la JOIN leave_type lt ON lt.id = la.leave_type_id
                WHERE la.company_id = :cid AND la.status = 'APPROVED'
                  AND :today BETWEEN la.start_date AND la.end_date {scope}
                GROUP BY lt.name ORDER BY n DESC, lt.name
                """
            ),
            p,
        )
    ).all()
    on_leave_today = (
        await session.execute(
            text(
                f"""
                SELECT count(DISTINCT la.employee_id) FROM leave_application la
                WHERE la.company_id = :cid AND la.status = 'APPROVED'
                  AND :today BETWEEN la.start_date AND la.end_date {scope}
                """
            ),
            p,
        )
    ).scalar_one()
    staff_scope = "AND e.id = ANY(:ids)" if visible_ids is not None else ""
    active_staff = (
        await session.execute(
            text(
                f"""
                SELECT count(*) FROM employee e
                WHERE e.company_id = :cid AND e.deleted_at IS NULL AND e.is_active
                  AND e.status IN ('ACTIVE', 'PROBATION') {staff_scope}
                """
            ),
            p,
        )
    ).scalar_one()

    # -- the next 7 days: approved leaves starting, and the busiest day -----------------------
    starts = (
        await session.execute(
            text(
                f"""
                SELECT count(*) FROM leave_application la
                WHERE la.company_id = :cid AND la.status = 'APPROVED'
                  AND la.start_date > :today AND la.start_date <= :today + 7 {scope}
                """
            ),
            p,
        )
    ).scalar_one()
    peak = (
        await session.execute(
            text(
                f"""
                SELECT d::date AS day, count(DISTINCT la.employee_id) AS n
                FROM generate_series(CAST(:today AS date) + 1, CAST(:today AS date) + 7,
                                     interval '1 day') AS d
                JOIN leave_application la
                  ON la.company_id = :cid AND la.status = 'APPROVED'
                 AND d::date BETWEEN la.start_date AND la.end_date {scope}
                GROUP BY d ORDER BY n DESC, d LIMIT 1
                """
            ),
            p,
        )
    ).first()

    summary = DecisionSummary(
        pending_count=int(cnt.pending),
        oldest_pending_at=cnt.oldest,
        on_leave_today=int(on_leave_today),
        on_leave_today_by_type=[(r.name, int(r.n)) for r in away],
        active_staff=int(active_staff),
        available_pct=(
            round(100 * (1 - int(on_leave_today) / int(active_staff)), 1) if active_staff else None
        ),
        upcoming_starts_7d=int(starts),
        peak_day=peak.day if peak else None,
        peak_day_away=int(peak.n) if peak else 0,
    )

    # -- the requests for the chosen tab ---------------------------------------------------------
    rows = (
        await session.execute(
            text(
                f"""
                SELECT la.id, la.version, la.employee_id, {_NAME.format(a="e")} AS emp_name,
                       e.employee_code, dg.title AS designation, d.name AS department,
                       a.department_id, la.leave_type_id, lt.name AS leave_type,
                       lt.requires_balance,
                       la.start_date, la.end_date, la.total_days, la.lop_days, la.reason, la.status,
                       la.approval_stage, la.submitted_at,
                       (SELECT coalesce(sum(l.amount), 0) FROM leave_ledger l
                         WHERE l.company_id = la.company_id AND l.employee_id = la.employee_id
                           AND l.leave_type_id = la.leave_type_id) AS balance
                FROM leave_application la
                JOIN employee e ON e.id = la.employee_id
                JOIN leave_type lt ON lt.id = la.leave_type_id
                LEFT JOIN employee_assignment a ON a.employee_id = e.id AND a.effective_to IS NULL
                LEFT JOIN designation dg ON dg.id = a.designation_id
                LEFT JOIN department d ON d.id = a.department_id
                WHERE la.company_id = :cid AND la.status = ANY(:statuses) {scope}
                ORDER BY la.submitted_at {"ASC" if tab == "pending" else "DESC"}
                LIMIT :lim
                """
            ),
            {**p, "statuses": list(_TAB_STATUSES[tab]), "lim": limit},
        )
    ).all()

    clashes: dict[UUID, list[Colleague]] = {}
    sizes: dict[UUID, int] = {}
    if tab == "pending" and rows:
        ids = [r.id for r in rows]
        for r in (
            await session.execute(
                text(
                    f"""
                    SELECT la.id AS app_id, {_NAME.format(a="oe")} AS name,
                           o.start_date, o.end_date, o.status
                    FROM leave_application la
                    JOIN employee_assignment a
                      ON a.employee_id = la.employee_id AND a.effective_to IS NULL
                     AND a.department_id IS NOT NULL
                    JOIN employee_assignment a2
                      ON a2.department_id = a.department_id AND a2.effective_to IS NULL
                     AND a2.employee_id <> la.employee_id
                    JOIN leave_application o
                      ON o.employee_id = a2.employee_id AND o.status IN ('SUBMITTED', 'APPROVED')
                     AND o.start_date <= la.end_date AND o.end_date >= la.start_date
                    JOIN employee oe ON oe.id = o.employee_id AND oe.deleted_at IS NULL
                    WHERE la.id = ANY(:ids)
                    ORDER BY o.start_date, name
                    """
                ),
                {"ids": ids},
            )
        ).all():
            clashes.setdefault(r.app_id, []).append(
                Colleague(
                    name=r.name, start_date=r.start_date, end_date=r.end_date, status=r.status
                )
            )
        dept_ids = list({r.department_id for r in rows if r.department_id})
        if dept_ids:
            for r in (
                await session.execute(
                    text(
                        """
                        SELECT a.department_id, count(*) AS n
                        FROM employee_assignment a JOIN employee e ON e.id = a.employee_id
                        WHERE a.effective_to IS NULL AND a.department_id = ANY(:d)
                          AND e.deleted_at IS NULL AND e.is_active
                          AND e.status IN ('ACTIVE', 'PROBATION')
                        GROUP BY a.department_id
                        """
                    ),
                    {"d": dept_ids},
                )
            ).all():
                sizes[r.department_id] = int(r.n)

    items = []
    for r in rows:
        paid = Decimal(r.total_days) - Decimal(r.lop_days)
        has_bal = bool(r.requires_balance)
        items.append(
            DecisionItem(
                id=r.id,
                version=r.version,
                employee_id=r.employee_id,
                employee_name=r.emp_name,
                employee_code=r.employee_code,
                designation=r.designation,
                department=r.department,
                leave_type_id=r.leave_type_id,
                leave_type=r.leave_type,
                start_date=r.start_date,
                end_date=r.end_date,
                total_days=r.total_days,
                lop_days=r.lop_days,
                reason=r.reason,
                status=r.status,
                approval_stage=r.approval_stage,
                submitted_at=r.submitted_at,
                current_balance=Decimal(r.balance) if has_bal else None,
                post_approval_balance=(Decimal(r.balance) - paid) if has_bal else None,
                department_size=sizes.get(r.department_id) if r.department_id else None,
                colleagues_away=clashes.get(r.id, []),
            )
        )

    return DecisionCenter(
        today=today,
        summary=summary,
        counts=DecisionTabCounts(
            pending=int(cnt.pending), approved=int(cnt.approved), declined=int(cnt.declined)
        ),
        tab=tab,
        items=items,
    )
