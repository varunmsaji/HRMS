"""Company dashboard insight cards: headcount trend, leave statistics, upcoming birthdays and
recent activity (`GET /v1/dashboards/company/insights`).

Read-only aggregation over data other modules own (employment, leave, audit log). Nothing here
writes, and every figure is computed from stored rows — no placeholder values."""

import calendar
from datetime import date, datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

LeaveScope = Literal["month", "year"]

# Same verdicts the attendance overview counts as "present" (attendance.overview.PRESENT_STATUSES).
_PRESENT_STATUSES = ("PRESENT", "HALF_DAY")

# audit action -> (activity title, whether the subject line names the employee)
_ACTIVITY_TITLES: dict[str, str] = {
    "EMPLOYEE_CREATED": "New employee joined",
    "EMPLOYEE_CONFIRMED": "Employee confirmed",
    "LEAVE_APPLICATION_APPROVED": "Leave request approved",
    "REGULARIZATION_APPROVED": "Regularization approved",
    "PAYROLL_PAY_RUN_FINALISED": "Payroll processed",
    "PAYROLL_PAY_RUN_PAID": "Payroll paid",
}


class HeadcountPoint(BaseModel):
    month: str  # YYYY-MM
    headcount: int


class LeaveTypeStat(BaseModel):
    leave_type_id: UUID
    name: str
    code: str | None
    days: float
    applications: int


class LeaveStatistics(BaseModel):
    scope: LeaveScope
    period_start: date
    period_end: date
    total_days: float
    by_type: list[LeaveTypeStat]


class UpcomingBirthday(BaseModel):
    employee_id: UUID
    name: str
    designation: str | None
    photo_url: str | None
    birthday: date  # the next occurrence
    days_until: int


class RecentActivity(BaseModel):
    kind: str
    title: str
    subject: str | None
    detail: str | None
    occurred_at: datetime


class KpiComparison(BaseModel):
    """Prior-period figures the KPI cards compare today's live numbers against."""

    headcount_prev_month_end: int
    yesterday: date
    yesterday_present: int
    yesterday_on_leave: int


class CompanyDashboardInsights(BaseModel):
    today: date
    kpi_comparison: KpiComparison
    headcount_trend: list[HeadcountPoint]
    leave_statistics: LeaveStatistics
    upcoming_birthdays: list[UpcomingBirthday]
    recent_activities: list[RecentActivity]


_NAME_SQL = (
    "coalesce(nullif(e.display_name, ''), trim(e.first_name || ' ' || coalesce(e.last_name, '')))"
)


def leave_period(today: date, scope: LeaveScope) -> tuple[date, date]:
    """The month or calendar year that contains `today`, in the company timezone's local date."""
    if scope == "year":
        return date(today.year, 1, 1), date(today.year, 12, 31)
    start = today.replace(day=1)
    end = today.replace(day=calendar.monthrange(today.year, today.month)[1])
    return start, end


def _in_branch(employee_col: str, on_date: str, branch_id: UUID | None) -> str:
    """An extra `AND` clause keeping only employees whose assignment on `on_date` places them in
    the requested branch, or "" when no branch is requested. Same rule as the attendance
    overview's branch filter: the assignment in effect on that day, so a transfer only moves
    someone's figures from the day it took effect. Both arguments are trusted SQL fragments
    written in this module; the branch id itself is always bound as `:bid`."""
    if branch_id is None:
        return ""
    return f"""
        AND EXISTS (
          SELECT 1 FROM employee_assignment ba
          WHERE ba.employee_id = {employee_col} AND ba.company_id = :cid
            AND ba.deleted_at IS NULL AND ba.branch_id = :bid
            AND ba.effective_from <= {on_date}
            AND (ba.effective_to IS NULL OR ba.effective_to >= {on_date}))"""


def _next_birthday(dob: date, today: date) -> date:
    def on_year(year: int) -> date:
        try:
            return dob.replace(year=year)
        except ValueError:  # 29 Feb in a non-leap year
            return date(year, 2, 28)

    candidate = on_year(today.year)
    return candidate if candidate >= today else on_year(today.year + 1)


async def build_company_insights(
    session: AsyncSession,
    company_id: UUID,
    *,
    growth_months: int = 6,
    leave_scope: LeaveScope = "month",
    branch_id: UUID | None = None,
    birthday_limit: int = 5,
    activity_limit: int = 6,
) -> CompanyDashboardInsights:
    """With `branch_id`, every figure only counts people placed in that branch on the date the
    figure is about. Recent activity then also drops company-level entries that name no employee
    (payroll runs), since those do not belong to any one branch."""
    params: dict[str, object] = {"cid": company_id}
    if branch_id is not None:
        params["bid"] = branch_id

    today = (
        await session.execute(
            text(
                "SELECT (now() AT TIME ZONE coalesce(c.timezone, 'UTC'))::date "
                "FROM company c WHERE c.id = :cid"
            ),
            params,
        )
    ).scalar_one_or_none() or date.today()

    # -- headcount at each of the last N month-ends (the current month ends today) -----------
    month_end = "least((m + interval '1 month - 1 day')::date, CAST(:today AS date))"
    trend_rows = (
        await session.execute(
            text(
                f"""
                WITH months AS (
                  SELECT date_trunc('month', CAST(:today AS date)) - (g * interval '1 month') AS m
                  FROM generate_series(0, :n - 1) AS g
                )
                SELECT to_char(m, 'YYYY-MM') AS month,
                       (SELECT count(*) FROM employment em
                         WHERE em.company_id = :cid AND em.deleted_at IS NULL
                           AND em.joining_date <= {month_end}
                           AND (em.last_working_day IS NULL
                                OR em.last_working_day > {month_end})
                           {_in_branch("em.employee_id", month_end, branch_id)}) AS headcount
                FROM months ORDER BY m
                """
            ),
            {**params, "today": today, "n": growth_months},
        )
    ).all()
    trend = [HeadcountPoint(month=r.month, headcount=int(r.headcount)) for r in trend_rows]

    # -- approved leave days by type over the month / year containing today -------------------
    start, end = leave_period(today, leave_scope)
    leave_rows = (
        await session.execute(
            text(
                f"""
                SELECT lt.id, lt.name, lt.code,
                       coalesce(sum(la.total_days), 0) AS days, count(la.id) AS applications
                FROM leave_application la
                JOIN leave_type lt ON lt.id = la.leave_type_id
                WHERE la.company_id = :cid AND la.status = 'APPROVED'
                  AND la.start_date BETWEEN :start AND :end
                  {_in_branch("la.employee_id", "la.start_date", branch_id)}
                GROUP BY lt.id, lt.name, lt.code
                ORDER BY days DESC, lt.name
                """
            ),
            {**params, "start": start, "end": end},
        )
    ).all()
    by_type = [
        LeaveTypeStat(
            leave_type_id=r.id,
            name=r.name,
            code=r.code,
            days=float(r.days),
            applications=int(r.applications),
        )
        for r in leave_rows
    ]
    leave_stats = LeaveStatistics(
        scope=leave_scope,
        period_start=start,
        period_end=end,
        total_days=sum(t.days for t in by_type),
        by_type=by_type,
    )

    # -- upcoming birthdays among current staff ------------------------------------------------
    people = (
        await session.execute(
            text(
                f"""
                SELECT e.id, {_NAME_SQL} AS name, e.date_of_birth, e.photo_url,
                       d.title AS designation
                FROM employee e
                LEFT JOIN employee_assignment a
                       ON a.employee_id = e.id AND a.effective_to IS NULL
                LEFT JOIN designation d ON d.id = a.designation_id
                WHERE e.company_id = :cid AND e.deleted_at IS NULL AND e.is_active
                  AND e.status IN ('ACTIVE', 'PROBATION') AND e.date_of_birth IS NOT NULL
                  {_in_branch("e.id", "CAST(:today AS date)", branch_id)}
                """
            ),
            {**params, "today": today},
        )
    ).all()
    birthdays = sorted(
        (
            UpcomingBirthday(
                employee_id=p.id,
                name=p.name,
                designation=p.designation,
                photo_url=p.photo_url,
                birthday=nb,
                days_until=(nb - today).days,
            )
            for p in people
            for nb in [_next_birthday(p.date_of_birth, today)]
        ),
        key=lambda b: (b.days_until, b.name),
    )[:birthday_limit]

    # -- recent activity from the audit log ----------------------------------------------------
    actions = list(_ACTIVITY_TITLES)
    activity_rows = (
        await session.execute(
            text(
                f"""
                SELECT action, occurred_at, subject FROM (
                SELECT al.action, al.occurred_at,
                       coalesce(nullif({_NAME_SQL}, ''),
                                CASE WHEN al.entity_type = 'pay_run'
                                     THEN al.after_json->>'month' END) AS subject,
                       row_number() OVER (PARTITION BY al.action ORDER BY al.occurred_at DESC) AS rn
                FROM audit_log al
                LEFT JOIN leave_application la
                       ON al.entity_type = 'leave_application' AND la.id = al.entity_id
                LEFT JOIN attendance_regularization_request rr
                       ON al.entity_type = 'attendance_regularization_request'
                      AND rr.id = al.entity_id
                LEFT JOIN employee e
                       ON e.id = CASE al.entity_type
                                   WHEN 'employee' THEN al.entity_id
                                   WHEN 'leave_application' THEN la.employee_id
                                   WHEN 'attendance_regularization_request' THEN rr.employee_id
                                 END
                WHERE al.company_id = :cid AND al.action = ANY(:actions)
                  {_in_branch("e.id", "CAST(al.occurred_at AS date)", branch_id)}
                ) ranked
                WHERE rn <= 2
                ORDER BY occurred_at DESC
                LIMIT :lim
                """
            ),
            {**params, "actions": actions, "lim": activity_limit},
        )
    ).all()
    activities = [
        RecentActivity(
            kind=r.action,
            title=_ACTIVITY_TITLES[r.action],
            subject=r.subject or None,
            detail=None,
            occurred_at=r.occurred_at,
        )
        for r in activity_rows
    ]

    # -- comparison figures for the KPI trend chips ---------------------------------------------
    prev_month_end = today.replace(day=1) - timedelta(days=1)
    yesterday = today - timedelta(days=1)
    headcount_prev = (
        await session.execute(
            text(
                f"""
                SELECT count(*) FROM employment em
                WHERE em.company_id = :cid AND em.deleted_at IS NULL
                  AND em.joining_date <= :d
                  AND (em.last_working_day IS NULL OR em.last_working_day > :d)
                  {_in_branch("em.employee_id", "CAST(:d AS date)", branch_id)}
                """
            ),
            {**params, "d": prev_month_end},
        )
    ).scalar_one()
    day_row = (
        await session.execute(
            text(
                f"""
                SELECT count(*) FILTER (WHERE attendance_status = ANY(:present)) AS present,
                       count(*) FILTER (WHERE attendance_status = 'LEAVE') AS on_leave
                FROM attendance_day ad
                WHERE ad.company_id = :cid AND ad.attendance_date = :d
                  {_in_branch("ad.employee_id", "CAST(:d AS date)", branch_id)}
                """
            ),
            {**params, "d": yesterday, "present": list(_PRESENT_STATUSES)},
        )
    ).one()

    return CompanyDashboardInsights(
        today=today,
        kpi_comparison=KpiComparison(
            headcount_prev_month_end=int(headcount_prev),
            yesterday=yesterday,
            yesterday_present=int(day_row.present),
            yesterday_on_leave=int(day_row.on_leave),
        ),
        headcount_trend=trend,
        leave_statistics=leave_stats,
        upcoming_birthdays=birthdays,
        recent_activities=activities,
    )
