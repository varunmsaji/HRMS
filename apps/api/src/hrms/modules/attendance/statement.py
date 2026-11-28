"""One employee's attendance statement for a calendar month, as a PDF, Excel or CSV file.

A day-by-day record (status, punches, worked time, lateness, overtime) with the month's totals
under it, built from the same stored days and day rules as the dashboard. It is a statement of
attendance, not of pay: payroll splits a half day into paid and unpaid halves, so its day counts
can differ from the whole-day counts here, and the file says so. A caller gets only employees
their attendance scope allows; anyone else is the same 404 as an employee who does not exist.
Every download is audited, since the file names a person against their attendance.
"""

import re
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.audit.service import AuditService
from hrms.core.errors.base import NotFoundError, ValidationError
from hrms.modules.attendance.documents import Cell, ExportFile, ExportFormat, Table, render
from hrms.modules.attendance.muster_export import BUCKET_LABELS, display_name
from hrms.modules.attendance.summary import AttendanceSummaryService, SummaryFilters
from hrms.modules.employee.models import Employee
from hrms.shared.timezone import resolve_zoneinfo

_MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
_PRESENT = frozenset({"PRESENT", "REMOTE", "ON_DUTY"})
_SAFE_NAME = re.compile(r"[^A-Za-z0-9_-]+")


def month_bounds(month: str, today: date) -> tuple[date, date]:
    """The first day of `month` and its last day up to `today`. A month that has not begun, or
    that is not `YYYY-MM`, is refused."""
    match = _MONTH.match(month)
    if match is None:
        raise ValidationError("month must be YYYY-MM.")
    first = date(int(match.group(1)), int(match.group(2)), 1)
    if first > today:
        raise ValidationError("A statement cannot cover a month that has not begun.")
    following = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    return first, min(following - timedelta(days=1), today)


def _clock(moment: datetime | None, tz: ZoneInfo) -> str:
    return moment.astimezone(tz).strftime("%H:%M") if moment else ""


def _hours(minutes: int) -> str:
    return f"{minutes // 60}h {minutes % 60:02d}m"


class StatementService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def build(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        month: str,
        visible_employee_ids: frozenset[UUID] | None,
        actor_user_id: UUID | None,
        today: date,
        timezone: str,
        company_name: str,
        fmt: ExportFormat = "pdf",
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> ExportFile:
        first, last = month_bounds(month, today)
        # One answer for "not yours to see" and "no such employee": the endpoint must not tell
        # a caller who exists outside their scope.
        if visible_employee_ids is not None and employee_id not in visible_employee_ids:
            raise NotFoundError("Employee not found.")
        person = (
            await self._session.execute(
                select(
                    Employee.employee_code,
                    Employee.first_name,
                    Employee.middle_name,
                    Employee.last_name,
                    Employee.display_name,
                ).where(Employee.company_id == company_id, Employee.id == employee_id)
            )
        ).first()
        if person is None:
            raise NotFoundError("Employee not found.")
        name = display_name(
            person.first_name, person.middle_name, person.last_name, person.display_name
        )

        rows: list[Any] = await AttendanceSummaryService(self._session).report_days(
            company_id,
            date_from=first,
            date_to=last,
            filters=SummaryFilters(visible_employee_ids=frozenset({employee_id})),
            today=today,
            timezone=timezone,
            limit=62,
        )
        by_date = {r.attendance_date: r for r in rows}
        tz = resolve_zoneinfo(timezone)

        body: list[list[Cell]] = []
        totals = {
            "present": 0,
            "half": 0,
            "absent": 0,
            "leave": 0,
            "off": 0,
            "holiday": 0,
            "incomplete": 0,
        }
        worked = punched = late_days = late_minutes = ot_found = ot_approved = 0
        day = first
        while day <= last:
            r = by_date.get(day)
            if r is None:
                body.append(
                    [day.isoformat(), day.strftime("%a"), "No record", "", "", "", "", "", "", ""]
                )
            else:
                if r.bucket in _PRESENT:
                    totals["present"] += 1
                elif r.bucket == "HALF_DAY":
                    totals["half"] += 1
                elif r.bucket == "ABSENT":
                    totals["absent"] += 1
                elif r.bucket == "LEAVE":
                    totals["leave"] += 1
                elif r.bucket == "WEEKLY_OFF":
                    totals["off"] += 1
                elif r.bucket == "HOLIDAY":
                    totals["holiday"] += 1
                elif r.bucket == "INCOMPLETE":
                    totals["incomplete"] += 1
                if r.first_in is not None:
                    punched += 1
                    worked += r.worked_minutes
                if r.is_late and r.first_in is not None:
                    late_days += 1
                    late_minutes += r.late_minutes
                ot_found += r.ot_detected
                ot_approved += r.ot_approved
                body.append(
                    [
                        day.isoformat(),
                        day.strftime("%a"),
                        BUCKET_LABELS.get(r.bucket, r.bucket),
                        _clock(r.first_in, tz),
                        _clock(r.last_out, tz),
                        r.worked_minutes if r.first_in is not None else "",
                        r.late_minutes if r.is_late else "",
                        r.early_minutes if r.is_early_out else "",
                        r.ot_detected or "",
                        r.ot_approved or "",
                    ]
                )
            day += timedelta(days=1)

        table = Table(
            title=f"Attendance statement: {first.strftime('%B %Y')}",
            subtitle=f"{name} ({person.employee_code}), {company_name}",
            headers=[
                "Date",
                "Day",
                "Status",
                "In",
                "Out",
                "Worked (min)",
                "Late (min)",
                "Early out (min)",
                "OT found (min)",
                "OT approved (min)",
            ],
            rows=body,
            notes=[
                f"Period: {first.isoformat()} to {last.isoformat()}"
                + (" (the month so far)" if last < _month_end(first) else ""),
                f"Present {totals['present']}, half day {totals['half']}, "
                f"absent {totals['absent']}, leave {totals['leave']}, "
                f"weekly off {totals['off']}, holiday {totals['holiday']}, "
                f"incomplete {totals['incomplete']}.",
                f"Worked {_hours(worked)} over {punched} days with a punch. "
                f"Late {late_days} days ({late_minutes} min).",
                f"Overtime: {ot_found} min found, {ot_approved} min approved.",
                "This is a statement of attendance, not of pay. Payroll splits a half day "
                "into paid and unpaid halves, so its day counts can differ from the whole "
                "days here.",
                f"Generated {today.isoformat()} from the attendance records.",
            ],
            landscape=False,
        )
        file = render(
            table,
            fmt,
            f"statement_{_SAFE_NAME.sub('', person.employee_code) or 'employee'}_{month}",
        )
        await AuditService().record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="ATTENDANCE_STATEMENT_DOWNLOADED",
            entity_type="attendance_statement",
            entity_id=employee_id,
            after={"month": month, "format": fmt},
            ip=ip,
            user_agent=user_agent,
        )
        return file


def _month_end(first: date) -> date:
    return (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
