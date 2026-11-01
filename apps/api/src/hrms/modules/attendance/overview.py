"""Company attendance overview for one date — a read-only aggregation of persisted
`attendance_day` rows.

No attendance rule lives here. Every verdict (present, leave, weekly-off/holiday, late after
grace, missing punch) is the calculation engine's own, stored on the row; this module only
groups those rows with SQL. The single judgement it adds is a *time* one the engine cannot make
because it has no clock: a zero-punch expected day reads `ABSENT`/`INCOMPLETE` the moment the row
exists, even before the shift has started. For today, such an employee is `NOT_CHECKED_IN` until
the scheduled shift end has passed (the row's own `scheduled_end`, else the end of the company's
local day), and a mid-shift open punch counts as `PRESENT` rather than a missing-punch exception.

Employees with no row for the date are reported as `no_record` — never guessed as absent, weekly
off or not-checked-in: resolving their shift/calendar needs the engine run per employee, which a
dashboard read must not do (nor write rows).
"""

from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, Integer, and_, case, cast, exists, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.errors.base import ValidationError
from hrms.modules.attendance.models import AttendanceDay, AttendanceRegularizationRequest
from hrms.modules.attendance.overview_schemas import (
    AttendanceDepartmentRow,
    AttendanceOverviewRead,
)
from hrms.modules.employee.models import Employee, EmployeeAssignment, Employment
from hrms.modules.organisation.models import Department
from hrms.shared.business_time import business_today
from hrms.shared.timezone import resolve_zoneinfo

NOT_EXPECTED_STATUSES = ("NOT_EXPECTED", "NOT_JOINED", "EXITED")
PRESENT_STATUSES = ("PRESENT", "HALF_DAY")
#: Statuses the engine gives a day with no (or an unfinished) punch pair.
OPEN_STATUSES = ("ABSENT", "INCOMPLETE")

BUCKETS = (
    "PRESENT",
    "ABSENT",
    "ON_LEAVE",
    "ON_DUTY",
    "REMOTE",
    "NOT_CHECKED_IN",
    "INCOMPLETE",
    "NOT_EXPECTED",
    "NO_RECORD",
)


def local_day_end_utc(attendance_date: date, tz_name: str) -> datetime:
    """The instant the company's local `attendance_date` ends, in UTC."""
    tz: ZoneInfo = resolve_zoneinfo(tz_name)
    next_midnight = datetime.combine(attendance_date + timedelta(days=1), time.min, tzinfo=tz)
    return next_midnight.astimezone(UTC)


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
        day_end = local_day_end_utc(target, timezone)

        ad = AttendanceDay
        # Shift end after which a zero-punch day is a confirmed absence. Only meaningful today.
        shift_end = func.coalesce(ad.scheduled_end, literal(day_end))
        in_progress = and_(literal(is_today), shift_end > literal(now))
        has_punch = ad.actual_first_in.is_not(None)

        bucket = case(
            (ad.id.is_(None), "NO_RECORD"),
            (ad.attendance_status.in_(NOT_EXPECTED_STATUSES), "NOT_EXPECTED"),
            (ad.attendance_status == "LEAVE", "ON_LEAVE"),
            (ad.attendance_status == "ON_DUTY", "ON_DUTY"),
            (ad.attendance_status == "WFH", "REMOTE"),
            (ad.attendance_status.in_(PRESENT_STATUSES), "PRESENT"),
            # Checked in and the shift is still running: present, not a missing-punch exception.
            (and_(ad.attendance_status.in_(OPEN_STATUSES), has_punch, in_progress), "PRESENT"),
            # No punch yet and the shift has not ended: not yet due, never "absent".
            (
                and_(ad.attendance_status.in_(OPEN_STATUSES), ~has_punch, in_progress),
                "NOT_CHECKED_IN",
            ),
            (ad.attendance_status == "ABSENT", "ABSENT"),
            else_="INCOMPLETE",  # INCOMPLETE, CONFIG_ERROR
        ).label("bucket")

        pending_regularization = exists().where(
            AttendanceRegularizationRequest.company_id == company_id,
            AttendanceRegularizationRequest.employee_id == Employee.id,
            AttendanceRegularizationRequest.attendance_date == target,
            AttendanceRegularizationRequest.status == "SUBMITTED",
        )
        is_exception = or_(
            ad.missing_punch.is_(True),
            ad.is_pending_approval.is_(True),
            ad.attendance_status.in_(("INCOMPLETE", "CONFIG_ERROR")),
            ad.has_unresolved_break.is_(True),
            ad.has_excess_break_exception.is_(True),
            pending_regularization,
        )

        def flag(condition: ColumnElement[bool]) -> ColumnElement[int]:
            return func.coalesce(func.sum(cast(case((condition, 1), else_=0), Integer)), 0)

        stmt = (
            select(
                EmployeeAssignment.department_id.label("department_id"),
                bucket,
                func.count(Employee.id).label("n"),
                flag(and_(ad.is_late.is_(True), has_punch)).label("late"),
                flag(ad.attendance_status == "HALF_DAY").label("half_day"),
                flag(and_(ad.leave_fraction > 0, ad.leave_fraction < 1)).label("half_day_leave"),
                flag(and_(ad.id.is_not(None), is_exception)).label("exceptions"),
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
        overlays = {"late": 0, "half_day": 0, "half_day_leave": 0, "exceptions": 0}
        for r in rows:
            by_dept.setdefault(r.department_id, blank())[r.bucket] += r.n
            overall[r.bucket] += r.n
            for key in overlays:
                overlays[key] += int(getattr(r, key))

        def buckets_payload(counts: dict[str, int]) -> dict[str, int]:
            return {
                "total": sum(counts.values()),
                "present": counts["PRESENT"],
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
        return AttendanceOverviewRead(
            attendance_date=target,
            timezone=timezone,
            is_today=is_today,
            generated_at=now,
            expected_employees=payload["total"] - payload["not_expected"] - payload["no_record"],
            departments=departments,
            **payload,
            **overlays,
        )
