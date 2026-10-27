"""Employee self-service calendar (Work Calendar phase 2): a read-only month/range view of the
authenticated employee's own working days, weekly offs, holidays and leave.

Design rules:

* The employee comes only from the caller (the router passes `AuthenticatedUser.employee_id`);
  this service has no employee parameter that a client could influence.
* Classification is **not** reimplemented. The effective calendar and weekly-off pattern come from
  `CalendarResolutionService.resolve_for_employee` (the WD-09 precedence walk, fail-closed), and
  each date is classified by `classify_work_calendar_date` via
  `classify_range_for_work_calendar`.
* A per-date precedence walk would cost dozens of queries per month, so the range is split into
  *segments*: the dates on which the employee's placement or a relevant policy assignment can
  change (read with two bounded queries). The resolver runs once per segment start, and the whole
  segment is classified with one set of composition queries. Typical month: one segment.
* Leave comes from persisted `leave_application_day` rows (never recalculated or mutated), limited
  to live statuses: `SUBMITTED` is shown as `PENDING`, `APPROVED` as `APPROVED`. `REJECTED` and
  `CANCELLED` are never returned. No reason, attachment, comment, leave type or reviewer is read.
* No administrative identifiers are returned (no calendar, pattern or assignment ids or scopes).
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.db.session import get_session
from hrms.modules.organisation.calendar_resolution import (
    CalendarResolutionService,
    validate_calendar_range,
)
from hrms.modules.organisation.repository import PolicyAssignmentRepository
from hrms.modules.organisation.schemas import DayTypeRead

_POLICY_KINDS = ["WORK_CALENDAR", "WEEKLY_OFF"]
# `SUBMITTED` leave is awaiting a decision at some approval stage; shown to the employee as
# pending. Anything else (REJECTED, CANCELLED) is not active leave and is filtered in the query.
_LEAVE_STATUS_LABEL = {"SUBMITTED": "PENDING", "APPROVED": "APPROVED"}


class EmployeeCalendarLeave(BaseModel):
    """Minimum leave facts for display. `half` is `FIRST_HALF`/`SECOND_HALF` for a half-day
    application (stored only on single-date applications), otherwise `None` with `fraction=1` -
    except that a full-day application over a half-day weekly off is stored as `fraction=0.50`
    with `half=None` (it takes only the working half of that date)."""

    status: Literal["APPROVED", "PENDING"]
    fraction: Decimal
    half: str | None = None


class EmployeeCalendarDay(BaseModel):
    date: date
    # False when no work calendar resolves for this date (fail-closed): `day_type` is then None
    # and the UI must say the calendar is not set up - never assume a working day.
    configured: bool
    day_type: str | None = None
    holiday_name: str | None = None
    holiday_type: str | None = None
    holiday_on_weekly_off: bool = False
    is_holiday_named: bool = False
    optional_holiday_name: str | None = None
    restricted_holiday_name: str | None = None
    exception_type: str | None = None
    weekly_off_fraction: Decimal | None = None
    leave: list[EmployeeCalendarLeave] = []


class EmployeeCalendarRead(BaseModel):
    from_date: date
    to_date: date
    # COMPLETE: every date resolved. PARTIAL: some dates unresolved. INCOMPLETE: none resolved.
    configuration: Literal["COMPLETE", "PARTIAL", "INCOMPLETE"]
    # False when the caller may not read leave; `leave` is then empty on every day.
    leave_included: bool
    days: list[EmployeeCalendarDay]


class EmployeeCalendarService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._resolver = CalendarResolutionService(session)
        self._policy_repo = PolicyAssignmentRepository()

    async def _segment_starts(
        self, company_id: UUID, employee_id: UUID, start: date, end: date
    ) -> list[date]:
        # Local imports mirror calendar_resolution's cross-module convention.
        from hrms.modules.employee.repository import EmployeeAssignmentRepository

        points: set[date] = set()

        def add(candidate: date | None) -> None:
            if candidate is not None and start < candidate <= end:
                points.add(candidate)

        placements = await EmployeeAssignmentRepository().list_assignments(
            self._session, company_id=company_id, employee_id=employee_id
        )
        for placement in placements:
            add(placement.effective_from)
            if placement.effective_to is not None:
                add(placement.effective_to + timedelta(days=1))
        policies = await self._policy_repo.list_overlapping(
            self._session,
            company_id=company_id,
            policy_kinds=_POLICY_KINDS,
            employee_id=employee_id,
            range_start=start,
            range_end=end,
        )
        for policy in policies:
            add(policy.effective_from)
            if policy.effective_to is not None:
                add(policy.effective_to + timedelta(days=1))
        return [start, *sorted(points)]

    async def get_my_calendar(
        self,
        company_id: UUID,
        employee_id: UUID,
        start: date,
        end: date,
        *,
        include_leave: bool,
    ) -> EmployeeCalendarRead:
        validate_calendar_range(start, end)

        starts = await self._segment_starts(company_id, employee_id, start, end)
        days: list[EmployeeCalendarDay] = []
        for index, seg_start in enumerate(starts):
            seg_end = starts[index + 1] - timedelta(days=1) if index + 1 < len(starts) else end
            resolved = await self._resolver.resolve_for_employee(company_id, employee_id, seg_start)
            if resolved.config_incomplete or resolved.work_calendar_id is None:
                cursor = seg_start
                while cursor <= seg_end:
                    days.append(EmployeeCalendarDay(date=cursor, configured=False))
                    cursor += timedelta(days=1)
                continue
            classified: list[DayTypeRead] = await self._resolver.classify_range_for_work_calendar(
                company_id,
                resolved.work_calendar_id,
                seg_start,
                seg_end,
                weekly_off_pattern_id_override=resolved.weekly_off_pattern_id,
                _weekly_off_override_present=True,
            )
            days.extend(
                EmployeeCalendarDay(
                    date=item.date,
                    configured=True,
                    day_type=item.day_type,
                    holiday_name=item.holiday_name,
                    holiday_type=item.holiday_type,
                    holiday_on_weekly_off=item.holiday_on_weekly_off,
                    is_holiday_named=item.is_holiday_named,
                    optional_holiday_name=item.optional_holiday_name,
                    restricted_holiday_name=item.restricted_holiday_name,
                    exception_type=item.exception_type,
                    weekly_off_fraction=item.weekly_off_fraction,
                )
                for item in classified
            )

        if include_leave:
            from hrms.modules.leave.repository import LeaveApplicationDayRepository

            marks = await LeaveApplicationDayRepository().list_calendar_marks(
                self._session,
                company_id=company_id,
                employee_id=employee_id,
                range_start=start,
                range_end=end,
            )
            by_date = {day.date: day for day in days}
            for calendar_date, status, fraction, half in marks:
                label = _LEAVE_STATUS_LABEL.get(status)
                target = by_date.get(calendar_date)
                if label is None or target is None:
                    continue
                target.leave.append(
                    EmployeeCalendarLeave(
                        status=label,  # type: ignore[arg-type]
                        fraction=fraction,
                        half=half,
                    )
                )

        configured = sum(1 for day in days if day.configured)
        configuration: Literal["COMPLETE", "PARTIAL", "INCOMPLETE"]
        if configured == len(days):
            configuration = "COMPLETE"
        elif configured == 0:
            configuration = "INCOMPLETE"
        else:
            configuration = "PARTIAL"
        return EmployeeCalendarRead(
            from_date=start,
            to_date=end,
            configuration=configuration,
            leave_included=include_leave,
            days=days,
        )


def get_employee_calendar_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> EmployeeCalendarService:
    return EmployeeCalendarService(session)
