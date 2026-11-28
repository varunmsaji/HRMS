"""Pattern alerts: who keeps being late or absent.

One day's lateness is not a pattern, so this looks across a window of the stored attendance days
and flags an employee only when the same thing keeps happening:

* `repeat_late`: late on at least N days in the window (only complete check-in and check-out days
  are judged, as in the punctuality figures);
* `frequent_absence`: absent on at least N days in the window;
* `repeat_missing_punch`: a day left incomplete (a missing punch) on at least N days;
* `repeat_absent_weekday`: absent on the same weekday at least N times in a longer window (the
  Monday or Friday habit).

The thresholds are `Settings.attendance_pattern_*`, the same for every company. The population,
the filters and the day rules are the dashboard's (`AttendanceSummaryService`), so an alert never
disagrees with the figures beside it, and a caller sees only the employees their attendance scope
allows. An alert is a prompt to look, never a finding about a person: it names the days behind it.
"""

from datetime import date, timedelta
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import and_, extract, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.config.settings import Settings
from hrms.core.errors.base import ValidationError
from hrms.modules.attendance.summary import AttendanceSummaryService, SummaryFilters

PatternKind = Literal[
    "repeat_late", "frequent_absence", "repeat_missing_punch", "repeat_absent_weekday"
]
#: Shown most important first when two alerts have the same count.
_KIND_ORDER: dict[str, int] = {
    "frequent_absence": 0,
    "repeat_absent_weekday": 1,
    "repeat_late": 2,
    "repeat_missing_punch": 3,
}
#: Days listed with an alert: enough to see the pattern, not a second report.
MAX_DATES = 5


class PatternThresholds(BaseModel):
    window_days: int
    weekday_window_days: int
    late_days: int
    absent_days: int
    incomplete_days: int
    weekday_absences: int


class PatternAlertRead(BaseModel):
    employee_id: UUID
    kind: PatternKind
    #: How many days matched.
    count: int
    #: The days that matched, newest first (at most `MAX_DATES`).
    dates: list[date]
    #: For `repeat_absent_weekday` only: 0 = Monday ... 6 = Sunday.
    weekday: int | None = None


class PatternAlertsRead(BaseModel):
    as_of: date
    thresholds: PatternThresholds
    alerts: list[PatternAlertRead]


def thresholds_from(settings: Settings) -> PatternThresholds:
    return PatternThresholds(
        window_days=settings.attendance_pattern_window_days,
        weekday_window_days=settings.attendance_pattern_weekday_window_days,
        late_days=settings.attendance_pattern_late_days,
        absent_days=settings.attendance_pattern_absent_days,
        incomplete_days=settings.attendance_pattern_incomplete_days,
        weekday_absences=settings.attendance_pattern_weekday_absences,
    )


class PatternAlertService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._t = thresholds_from(settings)

    async def alerts(
        self,
        company_id: UUID,
        *,
        as_of: date,
        filters: SummaryFilters,
        today: date,
        timezone: str,
    ) -> PatternAlertsRead:
        t = self._t
        if as_of > today:
            raise ValidationError("Pattern alerts cannot look beyond today.")
        window_from = as_of - timedelta(days=t.window_days - 1)
        weekday_from = as_of - timedelta(days=t.weekday_window_days - 1)
        rows = AttendanceSummaryService(self._session).population(
            company_id,
            date_from=min(window_from, weekday_from),
            date_to=as_of,
            filters=filters,
            today=today,
            timezone=timezone,
        )
        c = rows.c
        in_window = c.attendance_date >= window_from
        late = and_(c.checked_in, c.checked_out, c.is_late, in_window)
        absent = and_(c.bucket == "ABSENT", in_window)
        incomplete = and_(c.bucket == "INCOMPLETE", in_window)

        late_n = func.count().filter(late)
        absent_n = func.count().filter(absent)
        incomplete_n = func.count().filter(incomplete)
        per_person = await self._session.execute(
            select(c.employee_id, late_n, absent_n, incomplete_n)
            .group_by(c.employee_id)
            .having(
                or_(
                    late_n >= t.late_days,
                    absent_n >= t.absent_days,
                    incomplete_n >= t.incomplete_days,
                )
            )
        )
        weekday = (extract("isodow", c.attendance_date) - 1).label("weekday")
        weekday_n = func.count()
        per_weekday = await self._session.execute(
            select(c.employee_id, weekday, weekday_n)
            .where(c.bucket == "ABSENT", c.attendance_date >= weekday_from)
            .group_by(c.employee_id, weekday)
            .having(weekday_n >= t.weekday_absences)
        )

        found: list[tuple[UUID, PatternKind, int, int | None]] = []
        for employee_id, late_days, absent_days, incomplete_days in per_person:
            if late_days >= t.late_days:
                found.append((employee_id, "repeat_late", late_days, None))
            if absent_days >= t.absent_days:
                found.append((employee_id, "frequent_absence", absent_days, None))
            if incomplete_days >= t.incomplete_days:
                found.append((employee_id, "repeat_missing_punch", incomplete_days, None))
        for employee_id, day_of_week, count in per_weekday:
            found.append((employee_id, "repeat_absent_weekday", count, int(day_of_week)))
        if not found:
            return PatternAlertsRead(as_of=as_of, thresholds=t, alerts=[])

        # The days behind each alert, for just the people flagged.
        flagged = {employee_id for employee_id, *_ in found}
        detail = await self._session.execute(
            select(
                c.employee_id,
                c.attendance_date,
                c.bucket,
                and_(c.checked_in, c.checked_out, c.is_late).label("late"),
                (extract("isodow", c.attendance_date) - 1).label("weekday"),
            )
            .where(
                c.employee_id.in_(flagged),
                or_(c.bucket.in_(("ABSENT", "INCOMPLETE")), and_(c.checked_in, c.is_late)),
            )
            .order_by(c.attendance_date.desc())
        )
        days = list(detail)

        def matching(employee_id: UUID, kind: PatternKind, day_of_week: int | None) -> list[date]:
            out: list[date] = []
            for r in days:
                if r.employee_id != employee_id:
                    continue
                if kind == "repeat_late":
                    hit = r.late and r.attendance_date >= window_from
                elif kind == "frequent_absence":
                    hit = r.bucket == "ABSENT" and r.attendance_date >= window_from
                elif kind == "repeat_missing_punch":
                    hit = r.bucket == "INCOMPLETE" and r.attendance_date >= window_from
                else:
                    hit = (
                        r.bucket == "ABSENT"
                        and r.attendance_date >= weekday_from
                        and int(r.weekday) == day_of_week
                    )
                if hit:
                    out.append(r.attendance_date)
                if len(out) == MAX_DATES:
                    break
            return out

        alerts = [
            PatternAlertRead(
                employee_id=employee_id,
                kind=kind,
                count=count,
                weekday=day_of_week,
                dates=matching(employee_id, kind, day_of_week),
            )
            for employee_id, kind, count, day_of_week in found
        ]
        alerts.sort(
            key=lambda a: (-a.count, _KIND_ORDER[a.kind], str(a.employee_id), a.weekday or 0)
        )
        return PatternAlertsRead(as_of=as_of, thresholds=t, alerts=alerts)


_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def describe_alert(alert: PatternAlertRead, thresholds: PatternThresholds) -> str:
    """The pattern in a few words, for an email or a list: `late on 6 days in the last 30`."""
    window = thresholds.window_days
    if alert.kind == "repeat_late":
        return f"late on {alert.count} days in the last {window}"
    if alert.kind == "frequent_absence":
        return f"absent on {alert.count} days in the last {window}"
    if alert.kind == "repeat_missing_punch":
        return f"missing a punch on {alert.count} days in the last {window}"
    day = _WEEKDAYS[alert.weekday or 0]
    return f"absent on {alert.count} {day}s in the last {thresholds.weekday_window_days} days"
