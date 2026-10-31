"""Company dashboard insight cards: headcount trend, leave statistics, upcoming birthdays and
recent activity (`GET /v1/dashboards/company/insights`).

Read-only aggregation over data other modules own (employment, leave, audit log). Nothing here
writes, and every figure is computed from stored rows — no placeholder values."""

import calendar
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

LeaveScope = Literal["month", "year"]

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


class CompanyDashboardInsights(BaseModel):
    today: date
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
    birthday_limit: int = 5,
    activity_limit: int = 6,
) -> CompanyDashboardInsights:
    params = {"cid": company_id}

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
    trend_rows = (
        await session.execute(
            text(
                """
                WITH months AS (
                  SELECT date_trunc('month', CAST(:today AS date)) - (g * interval '1 month') AS m
                  FROM generate_series(0, :n - 1) AS g
                )
                SELECT to_char(m, 'YYYY-MM') AS month,
                       (SELECT count(*) FROM employment em
                         WHERE em.company_id = :cid AND em.deleted_at IS NULL
                           AND em.joining_date <= least((m + interval '1 month - 1 day')::date,
                                                        CAST(:today AS date))
                           AND (em.last_working_day IS NULL
                                OR em.last_working_day >
                                   least((m + interval '1 month - 1 day')::date,
                                         CAST(:today AS date)))) AS headcount
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
                """
                SELECT lt.id, lt.name, lt.code,
                       coalesce(sum(la.total_days), 0) AS days, count(la.id) AS applications
                FROM leave_application la
                JOIN leave_type lt ON lt.id = la.leave_type_id
                WHERE la.company_id = :cid AND la.status = 'APPROVED'
                  AND la.start_date BETWEEN :start AND :end
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
                """
            ),
            params,
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

    return CompanyDashboardInsights(
        today=today,
        headcount_trend=trend,
        leave_statistics=leave_stats,
        upcoming_birthdays=birthdays,
        recent_activities=activities,
    )
