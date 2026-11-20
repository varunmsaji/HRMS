"""Company attendance overview for one date — a read-only aggregation of persisted
`attendance_day` rows.

No attendance rule lives here. Every verdict (present, leave, weekly-off/holiday, late after
grace, missing punch) is the calculation engine's own, stored on the row; this module only
groups those rows with SQL. How a row becomes a bucket, an exception and a rate weight is decided
once, in `day_classification.py`, which the attendance summary also uses, so the home dashboard
and the Attendance page agree. This module maps that module's buckets onto the overview's own:
holiday, weekly off, non-working and not-employed days are `NOT_EXPECTED`, and `CONFIG_ERROR`
reads `INCOMPLETE`. A half day is its own `HALF_DAY` bucket, not "present".

Employees with no row for the date are reported as `no_record` — never guessed as absent, weekly
off or not-checked-in: resolving their shift/calendar needs the engine run per employee, which a
dashboard read must not do (nor write rows).
"""

from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import ColumnElement, Integer, and_, case, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.errors.base import ValidationError
from hrms.modules.attendance.day_classification import (
    DayClock,
    attendance_rate,
    day_bucket,
    is_exception,
    local_day_end_utc,
    rate_weight,
)
from hrms.modules.attendance.models import AttendanceDay
from hrms.modules.attendance.overview_schemas import (
    AttendanceDepartmentRow,
    AttendanceOverviewRead,
)
from hrms.modules.employee.models import Employee, EmployeeAssignment, Employment
from hrms.modules.organisation.models import Department
from hrms.shared.business_time import business_today

__all__ = ["BUCKETS", "AttendanceOverviewService", "local_day_end_utc"]

#: The classifier's buckets folded into the overview's.
_OVERVIEW_BUCKET = {
    "NOT_EMPLOYED": "NOT_EXPECTED",
    "HOLIDAY": "NOT_EXPECTED",
    "WEEKLY_OFF": "NOT_EXPECTED",
    "NON_WORKING": "NOT_EXPECTED",
    "LEAVE": "ON_LEAVE",
    "CONFIG_ERROR": "INCOMPLETE",
}

BUCKETS = (
    "PRESENT",
    "HALF_DAY",
    "ABSENT",
    "ON_LEAVE",
    "ON_DUTY",
    "REMOTE",
    "NOT_CHECKED_IN",
    "INCOMPLETE",
    "NOT_EXPECTED",
    "NO_RECORD",
)


class AttendanceOverviewService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def overview(
        self,
        company_id: UUID,
        *,
        timezone: str,
        attendance_date: date | None,
        visible_employee_ids: frozenset[UUID] | None,
        department_id: UUID | None = None,
        branch_id: UUID | None = None,
        now: datetime | None = None,
    ) -> AttendanceOverviewRead:
        now = now or datetime.now(UTC)
        today = business_today(timezone)
        target = attendance_date or today
        if target > today:
            raise ValidationError("The attendance overview cannot be requested for a future date.")
        is_today = target == today
        clock = DayClock.for_company(today, timezone, now) if is_today else None

        ad = AttendanceDay
        has_punch = ad.actual_first_in.is_not(None)
        # The classifier's bucket (folded into the overview's below); no row at all is NO_RECORD.
        bucket = case((ad.id.is_(None), "NO_RECORD"), else_=day_bucket(clock)).label("bucket")
        exception = is_exception(company_id)

        def flag(condition: ColumnElement[bool]) -> ColumnElement[int]:
            return func.coalesce(func.sum(cast(case((condition, 1), else_=0), Integer)), 0)

        stmt = (
            select(
                EmployeeAssignment.department_id.label("department_id"),
                bucket,
                func.count(Employee.id).label("n"),
                flag(and_(ad.is_late.is_(True), has_punch)).label("late"),
                flag(and_(ad.leave_fraction > 0, ad.leave_fraction < 1)).label("half_day_leave"),
                flag(and_(ad.id.is_not(None), exception)).label("exceptions"),
            )
            .select_from(Employee)
            .join(
                Employment,
                and_(
                    Employment.employee_id == Employee.id,
                    Employment.company_id == company_id,
                    Employment.deleted_at.is_(None),
                    Employment.joining_date <= target,
                    or_(
                        Employment.last_working_day.is_(None), Employment.last_working_day >= target
                    ),
                ),
            )
            .outerjoin(
                EmployeeAssignment,
                and_(
                    EmployeeAssignment.employee_id == Employee.id,
                    EmployeeAssignment.company_id == company_id,
                    EmployeeAssignment.deleted_at.is_(None),
                    EmployeeAssignment.effective_from <= target,
                    or_(
                        EmployeeAssignment.effective_to.is_(None),
                        EmployeeAssignment.effective_to >= target,
                    ),
                ),
            )
            .outerjoin(
                ad,
                and_(
                    ad.employee_id == Employee.id,
                    ad.company_id == company_id,
                    ad.attendance_date == target,
                ),
            )
            .where(
                Employee.company_id == company_id,
                Employee.deleted_at.is_(None),
                Employee.is_active.is_(True),
            )
            .group_by(EmployeeAssignment.department_id, "bucket")
        )
        if visible_employee_ids is not None:
            stmt = stmt.where(Employee.id.in_(visible_employee_ids))
        if department_id is not None:
            stmt = stmt.where(EmployeeAssignment.department_id == department_id)
        if branch_id is not None:
            stmt = stmt.where(EmployeeAssignment.branch_id == branch_id)

        rows = (await self._session.execute(stmt)).all()

        names: dict[UUID, str] = {}
        dept_ids = {r.department_id for r in rows if r.department_id is not None}
        if dept_ids:
            name_rows = await self._session.execute(
                select(Department.id, Department.name).where(
                    Department.company_id == company_id, Department.id.in_(dept_ids)
                )
            )
            names = {row.id: row.name for row in name_rows}

        def blank() -> dict[str, int]:
            return {b: 0 for b in BUCKETS}

        overall = blank()
        by_dept: dict[UUID | None, dict[str, int]] = {}
        overlays = {"late": 0, "half_day_leave": 0, "exceptions": 0}
        for r in rows:
            folded = _OVERVIEW_BUCKET.get(r.bucket, r.bucket)
            by_dept.setdefault(r.department_id, blank())[folded] += r.n
            overall[folded] += r.n
            for key in overlays:
                overlays[key] += int(getattr(r, key))

        def buckets_payload(counts: dict[str, int]) -> dict[str, int]:
            return {
                "total": sum(counts.values()),
                "present": counts["PRESENT"],
                "half_day": counts["HALF_DAY"],
                "absent": counts["ABSENT"],
                "on_leave": counts["ON_LEAVE"],
                "on_duty": counts["ON_DUTY"],
                "remote_work": counts["REMOTE"],
                "not_checked_in": counts["NOT_CHECKED_IN"],
                "incomplete": counts["INCOMPLETE"],
                "not_expected": counts["NOT_EXPECTED"],
                "no_record": counts["NO_RECORD"],
            }

        departments = [
            AttendanceDepartmentRow(
                department_id=dept,
                department_name=names.get(dept, "Unassigned") if dept else "Unassigned",
                **buckets_payload(counts),
            )
            for dept, counts in by_dept.items()
        ]
        departments.sort(key=lambda d: (d.department_id is None, d.department_name.lower()))

        payload = buckets_payload(overall)
        expected = payload["total"] - payload["not_expected"] - payload["no_record"]
        weighted = sum(rate_weight(b) * n for b, n in overall.items())
        return AttendanceOverviewRead(
            attendance_date=target,
            timezone=timezone,
            is_today=is_today,
            generated_at=now,
            expected_employees=expected,
            attendance_rate=attendance_rate(weighted, expected),
            departments=departments,
            **payload,
            **overlays,
        )
