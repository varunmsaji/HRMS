"""Attendance summary for a date window: the dashboard totals both apps used to add up themselves.

No attendance rule lives here. Every verdict (status, late, minutes, overtime, missing punch) is
the calculation engine's own, stored on the `attendance_day` row; this module only groups rows with
SQL. The day buckets are the dashboards' existing ones (web `bucketOf`, mobile
`attendanceBucketOf`), now defined once:

    NOT_JOINED / EXITED            -> NOT_EMPLOYED
    WFH                            -> REMOTE
    NOT_EXPECTED + HOLIDAY         -> HOLIDAY
    NOT_EXPECTED + WEEKLY_OFF      -> WEEKLY_OFF
    any other NOT_EXPECTED         -> NON_WORKING
    every other status             -> itself

"Expected" (the denominator of every rate) is every bucket except NOT_EMPLOYED, HOLIDAY,
WEEKLY_OFF and NON_WORKING. "Working" (the numerator) is PRESENT, REMOTE and ON_DUTY.

Department and branch come from the employee's assignment in force on each attendance date, so a
transfer moves the employee's later days, not their history.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    Integer,
    Select,
    and_,
    case,
    cast,
    func,
    or_,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from hrms.core.errors.base import ValidationError
from hrms.modules.attendance.models import AttendanceDay
from hrms.modules.attendance.summary_schemas import (
    AttendanceSummaryRead,
    BucketCount,
    DailyRate,
    FrequentLate,
    GroupStat,
    LateBand,
    Punctuality,
    SummaryKpis,
    WeekdayAbsence,
)
from hrms.modules.employee.models import Employee, EmployeeAssignment, Employment
from hrms.modules.organisation.models import Branch, Department

#: The longest window one request may summarise (the dashboards' own range cap).
MAX_SUMMARY_DAYS = 92

#: Display order, the same as both dashboards.
DAY_BUCKETS = (
    "PRESENT",
    "REMOTE",
    "ON_DUTY",
    "HALF_DAY",
    "ABSENT",
    "LEAVE",
    "INCOMPLETE",
    "CONFIG_ERROR",
    "HOLIDAY",
    "WEEKLY_OFF",
    "NON_WORKING",
    "NOT_EMPLOYED",
)
NOT_EXPECTED_BUCKETS = frozenset({"NOT_EMPLOYED", "HOLIDAY", "WEEKLY_OFF", "NON_WORKING"})
WORKING_BUCKETS = frozenset({"PRESENT", "REMOTE", "ON_DUTY"})

LATE_BANDS = (
    ("1_15", "1–15 min", 1, 15),
    ("16_30", "16–30 min", 16, 30),
    ("31_60", "31–60 min", 31, 60),
    ("60_plus", "Over an hour", 61, None),
)

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
UNASSIGNED = "Unassigned"
#: A department / branch filter value meaning "no department (branch) on that day".
UNASSIGNED_FILTER = "unassigned"
FREQUENT_LATE_LIMIT = 5
FREQUENT_LATE_MIN_DAYS = 2


def pct(numerator: int, denominator: int) -> float | None:
    return numerator / denominator * 100 if denominator > 0 else None


def is_expected(bucket: str) -> bool:
    return bucket not in NOT_EXPECTED_BUCKETS


@dataclass(frozen=True)
class SummaryFilters:
    """Who is in the population. `department_id`/`branch_id` match the assignment in force on the
    attendance date; `"unassigned"` matches days with none (the breakdown's "Unassigned" row)."""

    visible_employee_ids: frozenset[UUID] | None = None
    employee_id: UUID | None = None
    shift_id: UUID | None = None
    employee_status: str | None = None
    department_id: UUID | Literal["unassigned"] | None = None
    branch_id: UUID | Literal["unassigned"] | None = None


def _org_filter(
    column: InstrumentedAttribute[UUID | None], value: UUID | Literal["unassigned"]
) -> ColumnElement[bool]:
    return column.is_(None) if value == UNASSIGNED_FILTER else column == value


def _bucket_expr() -> ColumnElement[str]:
    ad = AttendanceDay
    status = ad.attendance_status
    return case(
        (status.in_(("NOT_JOINED", "EXITED")), "NOT_EMPLOYED"),
        (status == "WFH", "REMOTE"),
        (
            status.in_(
                ("PRESENT", "ON_DUTY", "HALF_DAY", "ABSENT", "LEAVE", "INCOMPLETE", "CONFIG_ERROR")
            ),
            status,
        ),
        (and_(status == "NOT_EXPECTED", ad.calendar_day_type == "HOLIDAY"), "HOLIDAY"),
        (and_(status == "NOT_EXPECTED", ad.calendar_day_type == "WEEKLY_OFF"), "WEEKLY_OFF"),
        else_="NON_WORKING",
    )


def _count_if(condition: ColumnElement[bool]) -> ColumnElement[int]:
    return func.coalesce(func.sum(cast(case((condition, 1), else_=0), Integer)), 0)


def _sum_if(condition: ColumnElement[bool], value: ColumnElement[int]) -> ColumnElement[int]:
    return func.coalesce(func.sum(case((condition, value), else_=0)), 0)


class AttendanceSummaryService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------ population

    def _rows(
        self,
        company_id: UUID,
        filters: SummaryFilters,
        date_from: date,
        date_to: date,
        *,
        org_filters: bool = True,
    ) -> Any:
        """One row per attendance day in the window, after the filters, as a subquery."""
        ad = AttendanceDay
        checked_in = ad.actual_first_in.is_not(None)
        stmt: Select[Any] = (
            select(
                ad.employee_id.label("employee_id"),
                ad.attendance_date.label("attendance_date"),
                _bucket_expr().label("bucket"),
                checked_in.label("checked_in"),
                ad.actual_last_out.is_not(None).label("checked_out"),
                ad.is_late.label("is_late"),
                ad.late_minutes.label("late_minutes"),
                or_(
                    ad.missing_punch.is_(True),
                    ad.attendance_status == "CONFIG_ERROR",
                    ad.is_pending_approval.is_(True),
                    and_(
                        ad.work_on_leave_flagged.is_(True),
                        ad.work_on_leave_resolution.is_(None),
                    ),
                ).label("exception"),
                ad.ot_minutes_detected.label("ot_detected"),
                ad.ot_minutes_approved.label("ot_approved"),
                ad.worked_minutes.label("worked_minutes"),
                EmployeeAssignment.department_id.label("department_id"),
                EmployeeAssignment.branch_id.label("branch_id"),
            )
            .select_from(ad)
            .join(Employee, and_(Employee.id == ad.employee_id, Employee.company_id == company_id))
            .outerjoin(
                EmployeeAssignment,
                and_(
                    EmployeeAssignment.employee_id == ad.employee_id,
                    EmployeeAssignment.company_id == company_id,
                    EmployeeAssignment.deleted_at.is_(None),
                    EmployeeAssignment.effective_from <= ad.attendance_date,
                    or_(
                        EmployeeAssignment.effective_to.is_(None),
                        EmployeeAssignment.effective_to >= ad.attendance_date,
                    ),
                ),
            )
            .where(
                ad.company_id == company_id,
                ad.attendance_date >= date_from,
                ad.attendance_date <= date_to,
            )
        )
        if filters.visible_employee_ids is not None:
            stmt = stmt.where(ad.employee_id.in_(filters.visible_employee_ids))
        if filters.employee_id is not None:
            stmt = stmt.where(ad.employee_id == filters.employee_id)
        if filters.shift_id is not None:
            stmt = stmt.where(ad.shift_id == filters.shift_id)
        if filters.employee_status is not None:
            stmt = stmt.where(Employee.status == filters.employee_status)
        if org_filters and filters.department_id is not None:
            stmt = stmt.where(_org_filter(EmployeeAssignment.department_id, filters.department_id))
        if org_filters and filters.branch_id is not None:
            stmt = stmt.where(_org_filter(EmployeeAssignment.branch_id, filters.branch_id))
        return stmt.subquery("rows")

    async def _no_record(self, company_id: UUID, filters: SummaryFilters, focus: date) -> int:
        """Employed on `focus` and in the population, but with no attendance day yet."""
        if filters.shift_id is not None:
            # A shift belongs to the attendance day; without a day the shift is unknown.
            return 0
        ad = AttendanceDay
        stmt = (
            select(func.count(func.distinct(Employee.id)))
            .select_from(Employee)
            .join(
                Employment,
                and_(
                    Employment.employee_id == Employee.id,
                    Employment.company_id == company_id,
                    Employment.deleted_at.is_(None),
                    Employment.joining_date <= focus,
                    or_(
                        Employment.last_working_day.is_(None), Employment.last_working_day >= focus
                    ),
                ),
            )
            .outerjoin(
                EmployeeAssignment,
                and_(
                    EmployeeAssignment.employee_id == Employee.id,
                    EmployeeAssignment.company_id == company_id,
                    EmployeeAssignment.deleted_at.is_(None),
                    EmployeeAssignment.effective_from <= focus,
                    or_(
                        EmployeeAssignment.effective_to.is_(None),
                        EmployeeAssignment.effective_to >= focus,
                    ),
                ),
            )
            .where(
                Employee.company_id == company_id,
                Employee.deleted_at.is_(None),
                Employee.is_active.is_(True),
                ~select(ad.id)
                .where(
                    ad.company_id == company_id,
                    ad.employee_id == Employee.id,
                    ad.attendance_date == focus,
                )
                .exists(),
            )
        )
        if filters.visible_employee_ids is not None:
            stmt = stmt.where(Employee.id.in_(filters.visible_employee_ids))
        if filters.employee_id is not None:
            stmt = stmt.where(Employee.id == filters.employee_id)
        if filters.employee_status is not None:
            stmt = stmt.where(Employee.status == filters.employee_status)
        if filters.department_id is not None:
            stmt = stmt.where(_org_filter(EmployeeAssignment.department_id, filters.department_id))
        if filters.branch_id is not None:
            stmt = stmt.where(_org_filter(EmployeeAssignment.branch_id, filters.branch_id))
        return int((await self._session.execute(stmt)).scalar_one())

    # ------------------------------------------------------------------ summary

    async def summary(
        self,
        company_id: UUID,
        *,
        date_from: date,
        date_to: date,
        today: date,
        compare_date: date | None = None,
        filters: SummaryFilters | None = None,
    ) -> AttendanceSummaryRead:
        filters = filters or SummaryFilters()
        if date_from > date_to:
            raise ValidationError("date_from must be on or before date_to.")
        if date_to > today:
            raise ValidationError("The attendance summary cannot cover a future date.")
        if (date_to - date_from).days + 1 > MAX_SUMMARY_DAYS:
            raise ValidationError(f"The window can be at most {MAX_SUMMARY_DAYS} days.")
        focus = date_to
        compare = compare_date or focus - timedelta(days=7)
        is_today = focus == today

        rows = self._rows(company_id, filters, date_from, date_to)

        per_day = (await self._session.execute(_per_day(rows))).all()

        by_date: dict[date, list[Any]] = {}
        for r in per_day:
            by_date.setdefault(r.attendance_date, []).append(r)
        row_count = sum(int(r.n) for r in per_day)

        daily = []
        weekday_expected = [0] * 7
        weekday_absent = [0] * 7
        day = date_from
        while day <= date_to:
            tally = dict.fromkeys(
                ("expected", "present", "remote", "absent", "leave", "late", "checked_in"), 0
            )
            worked = 0
            for r in by_date.get(day, []):
                if is_expected(r.bucket):
                    tally["expected"] += r.n
                if r.bucket in WORKING_BUCKETS:
                    tally["present"] += r.n
                if r.bucket == "REMOTE":
                    tally["remote"] += r.n
                if r.bucket == "ABSENT":
                    tally["absent"] += r.n
                if r.bucket == "LEAVE":
                    tally["leave"] += r.n
                tally["late"] += int(r.late)
                tally["checked_in"] += int(r.checked_in)
                worked += int(r.worked_minutes)
            weekday_expected[day.weekday()] += tally["expected"]
            weekday_absent[day.weekday()] += tally["absent"]
            daily.append(
                DailyRate(
                    date=day,
                    rate=pct(tally["present"], tally["expected"]),
                    worked_minutes=worked,
                    **tally,
                )
            )
            day += timedelta(days=1)

        no_record = await self._no_record(company_id, filters, focus) if is_today else 0
        focus_kpis = _kpis(by_date.get(focus, []), no_record)
        if date_from <= compare <= date_to:
            compare_kpis = _kpis(by_date[compare], 0) if by_date.get(compare) else None
        else:
            compare_kpis = await self._kpis_on(company_id, filters, compare)

        focus_counts = {r.bucket: int(r.n) for r in by_date.get(focus, [])}
        distribution = [
            BucketCount(bucket=b, count=focus_counts[b]) for b in DAY_BUCKETS if focus_counts.get(b)
        ]

        return AttendanceSummaryRead(
            date_from=date_from,
            date_to=date_to,
            focus_date=focus,
            compare_date=compare,
            is_today=is_today,
            row_count=row_count,
            daily=daily,
            focus=focus_kpis,
            compare=compare_kpis,
            distribution=distribution,
            punctuality=await self._punctuality(rows),
            frequent_late=await self._frequent_late(rows),
            weekday_absence=[
                WeekdayAbsence(
                    index=i,
                    label=WEEKDAYS[i],
                    expected=weekday_expected[i],
                    absent=weekday_absent[i],
                    rate=pct(weekday_absent[i], weekday_expected[i]),
                )
                for i in range(7)
            ],
            by_department=await self._breakdown(company_id, filters, focus, "department"),
            by_branch=await self._breakdown(company_id, filters, focus, "branch"),
        )

    async def _kpis_on(
        self, company_id: UUID, filters: SummaryFilters, day: date
    ) -> SummaryKpis | None:
        """KPIs for a day outside the window (the comparison day of a short window)."""
        rows = self._rows(company_id, filters, day, day)
        result = (await self._session.execute(_per_day(rows))).all()
        return _kpis(result, 0) if result else None

    async def _punctuality(self, rows: Any) -> Punctuality:
        # A day with a check-in but no check-out yet is not judged: the engine decides lateness
        # only on a complete IN/OUT pair, so counting it would read as on time.
        complete = and_(rows.c.checked_in, rows.c.checked_out)
        late = and_(complete, rows.c.is_late)
        # A late day with no minutes recorded is still late; it lands in the smallest band.
        minutes = func.greatest(rows.c.late_minutes, 1)
        band_columns = []
        for key, _label, low, high in LATE_BANDS:
            in_band = minutes >= low if high is None else and_(minutes >= low, minutes <= high)
            band_columns.append(_count_if(and_(late, in_band)).label(f"band_{key}"))
        r = (
            await self._session.execute(
                select(
                    _count_if(complete).label("checked_in"),
                    _count_if(late).label("late"),
                    _sum_if(late, rows.c.late_minutes).label("late_minutes"),
                    *band_columns,
                )
            )
        ).one()
        checked_in, late_n = int(r.checked_in), int(r.late)
        on_time = checked_in - late_n
        return Punctuality(
            checked_in=checked_in,
            on_time=on_time,
            late=late_n,
            late_rate=pct(late_n, checked_in),
            on_time_rate=pct(on_time, checked_in),
            avg_late_minutes=int(r.late_minutes) / late_n if late_n else None,
            bands=[
                LateBand(key=key, label=label, count=int(getattr(r, f"band_{key}")))
                for key, label, _low, _high in LATE_BANDS
            ],
        )

    async def _frequent_late(self, rows: Any) -> list[FrequentLate]:
        days = func.count().label("late_days")
        minutes = func.coalesce(func.sum(rows.c.late_minutes), 0).label("total_late_minutes")
        result = await self._session.execute(
            select(rows.c.employee_id, days, minutes)
            .where(rows.c.is_late)
            .group_by(rows.c.employee_id)
            .having(func.count() >= FREQUENT_LATE_MIN_DAYS)
            .order_by(days.desc(), minutes.desc(), rows.c.employee_id)
            .limit(FREQUENT_LATE_LIMIT)
        )
        return [
            FrequentLate(
                employee_id=r.employee_id,
                late_days=int(r.late_days),
                total_late_minutes=int(r.total_late_minutes),
            )
            for r in result
        ]

    async def _breakdown(
        self, company_id: UUID, filters: SummaryFilters, focus: date, key: str
    ) -> list[GroupStat]:
        rows = self._rows(company_id, filters, focus, focus, org_filters=False)
        column = rows.c.department_id if key == "department" else rows.c.branch_id
        result = (
            await self._session.execute(
                select(
                    column.label("group_id"),
                    rows.c.bucket,
                    func.count().label("n"),
                    _count_if(rows.c.is_late).label("late"),
                ).group_by(column, rows.c.bucket)
            )
        ).all()
        ids = {r.group_id for r in result if r.group_id is not None}
        names = await self._names(company_id, ids, key)

        groups: dict[UUID | None, dict[str, int]] = {}
        for r in result:
            g = groups.setdefault(
                r.group_id,
                {"headcount": 0, "expected": 0, "present": 0, "absent": 0, "leave": 0, "late": 0},
            )
            g["headcount"] += r.n
            g["late"] += r.late
            if is_expected(r.bucket):
                g["expected"] += r.n
            if r.bucket in WORKING_BUCKETS:
                g["present"] += r.n
            if r.bucket == "ABSENT":
                g["absent"] += r.n
            if r.bucket == "LEAVE":
                g["leave"] += r.n
        stats = [
            GroupStat(
                id=group_id,
                name=names.get(group_id, UNASSIGNED) if group_id else UNASSIGNED,
                rate=pct(g["present"], g["expected"]),
                **g,
            )
            for group_id, g in groups.items()
        ]

        # Lowest attendance first, groups nobody was expected in last: the places to look at top.
        def order(s: GroupStat) -> tuple[Any, ...]:
            if s.rate is None:
                return (1, 0.0, 0, s.name.lower())
            return (0, s.rate, -s.headcount, s.name.lower())

        return sorted(stats, key=order)

    async def _names(self, company_id: UUID, ids: Iterable[UUID], key: str) -> dict[UUID, str]:
        ids = list(ids)
        if not ids:
            return {}
        model = Department if key == "department" else Branch
        result = await self._session.execute(
            select(model.id, model.name).where(model.company_id == company_id, model.id.in_(ids))
        )
        return {r.id: r.name for r in result}


def _per_day(rows: Any) -> Select[Any]:
    """Per date and bucket: everything the daily rate, the KPIs and the weekday pattern need."""
    return select(
        rows.c.attendance_date,
        rows.c.bucket,
        func.count().label("n"),
        _count_if(rows.c.checked_in).label("checked_in"),
        _count_if(rows.c.is_late).label("late"),
        _count_if(and_(rows.c.bucket.in_(("ABSENT", "INCOMPLETE")), ~rows.c.checked_in)).label(
            "not_checked_in"
        ),
        _count_if(rows.c.exception).label("exceptions"),
        _count_if(rows.c.ot_detected > 0).label("ot_employees"),
        _sum_if(rows.c.ot_detected > 0, rows.c.ot_detected).label("ot_detected"),
        _sum_if(rows.c.ot_detected > 0, rows.c.ot_approved).label("ot_approved"),
        _sum_if(rows.c.checked_in, rows.c.worked_minutes).label("worked_minutes"),
    ).group_by(rows.c.attendance_date, rows.c.bucket)


def _kpis(rows: Iterable[Any], no_record: int) -> SummaryKpis:
    counts = dict.fromkeys(DAY_BUCKETS, 0)
    totals = {
        "checked_in": 0,
        "late": 0,
        "not_checked_in": 0,
        "exceptions": 0,
        "ot_employees": 0,
        "ot_detected": 0,
        "ot_approved": 0,
    }
    for r in rows:
        counts[r.bucket] += int(r.n)
        if r.bucket == "NOT_EMPLOYED":
            continue
        for name in totals:
            totals[name] += int(getattr(r, name))
    employed = sum(counts.values()) - counts["NOT_EMPLOYED"]
    return SummaryKpis(
        total_employees=employed + no_record,
        no_record=no_record,
        present=counts["PRESENT"],
        remote=counts["REMOTE"],
        on_duty=counts["ON_DUTY"],
        absent=counts["ABSENT"],
        leave=counts["LEAVE"],
        half_day=counts["HALF_DAY"],
        holiday=counts["HOLIDAY"],
        weekly_off=counts["WEEKLY_OFF"],
        incomplete=counts["INCOMPLETE"],
        late=totals["late"],
        not_checked_in=totals["not_checked_in"] + no_record,
        checked_in=totals["checked_in"],
        exceptions=totals["exceptions"],
        overtime_employees=totals["ot_employees"],
        overtime_minutes_detected=totals["ot_detected"],
        overtime_minutes_approved=totals["ot_approved"],
        not_employed=counts["NOT_EMPLOYED"],
    )
