"""The Reports tab as CSV, Excel or PDF files over a window of up to a year.

Five reports: daily attendance, present / absent, late / early, work hours and overtime. They read
the same population, filters and day rules as `/attendance/summary` (`summary.py`), so a file never
disagrees with the dashboard, and a caller gets only the employees their attendance scope allows.
Payroll attendance is not here: it is the attendance period's own summary. Minutes are written as
whole numbers, so a spreadsheet can add them. Every download is audited.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.audit.service import AuditService
from hrms.core.errors.base import ValidationError
from hrms.modules.attendance.documents import ExportFile, ExportFormat, Table, render
from hrms.modules.attendance.muster_export import BUCKET_LABELS, display_name
from hrms.modules.attendance.summary import AttendanceSummaryService, SummaryFilters
from hrms.modules.employee.models import Employee
from hrms.shared.timezone import resolve_zoneinfo

ReportName = Literal["daily", "present-absent", "late-early", "hours", "overtime"]
REPORT_NAMES: tuple[ReportName, ...] = (
    "daily",
    "present-absent",
    "late-early",
    "hours",
    "overtime",
)

#: The most rows one file may hold; beyond this the request is refused, not cut short.
MAX_REPORT_ROWS = 200_000

_PRESENT = frozenset({"PRESENT", "REMOTE", "ON_DUTY"})
REPORT_TITLES: dict[str, str] = {
    "daily": "Daily attendance",
    "present-absent": "Present and absent",
    "late-early": "Late arrivals and early departures",
    "hours": "Work hours",
    "overtime": "Overtime",
}
OVERTIME_STATUS_LABELS = {
    "PENDING": "Pending",
    "AUTO_APPROVED": "Auto-approved",
    "APPROVED": "Approved",
    "REJECTED": "Rejected",
}
OVERTIME_DAY_CLASS_LABELS = {
    "NORMAL": "Normal",
    "WEEKLY_OFF": "Weekly off",
    "HOLIDAY": "Holiday",
    "NIGHT": "Night",
}


@dataclass
class _Person:
    id: UUID
    name: str
    code: str


@dataclass
class _Tally:
    present: int = 0
    half: int = 0
    absent: int = 0
    leave: int = 0
    off: int = 0
    holiday: int = 0
    incomplete: int = 0
    days: int = 0  # days with a first punch
    worked: int = 0
    scheduled: int = 0


def _clock(moment: datetime | None, tz: ZoneInfo) -> str:
    return moment.astimezone(tz).strftime("%H:%M") if moment else ""


class ReportExportService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def build(
        self,
        company_id: UUID,
        report: ReportName,
        *,
        actor_user_id: UUID | None,
        date_from: date,
        date_to: date,
        filters: SummaryFilters,
        today: date,
        timezone: str,
        ip: str | None = None,
        user_agent: str | None = None,
        now: datetime | None = None,
        fmt: ExportFormat = "csv",
    ) -> ExportFile:
        """The report as a CSV, Excel or PDF file."""
        service = AttendanceSummaryService(self._session)
        window: dict[str, Any] = {
            "date_from": date_from,
            "date_to": date_to,
            "filters": filters,
            "today": today,
            "timezone": timezone,
            "limit": MAX_REPORT_ROWS,
            "now": now,
        }
        if report == "overtime":
            rows: Sequence[Any] = await service.report_overtime(company_id, **window)
        else:
            rows = await service.report_days(company_id, **window)
        if len(rows) > MAX_REPORT_ROWS:
            raise ValidationError("That report is too large. Narrow the dates or the filters.")

        people = await self._people(company_id, {r.employee_id for r in rows})
        tz = resolve_zoneinfo(timezone)
        header, body = _REPORTS[report](rows, people, tz)

        table = Table(
            title=REPORT_TITLES[report],
            subtitle=f"{date_from.isoformat()} to {date_to.isoformat()}",
            headers=header,
            rows=body,
        )
        # Render before auditing: a file that cannot be built (too large for a PDF) is not a
        # download, and must not be recorded as one.
        file = render(table, fmt, f"{report}_{date_from.isoformat()}_{date_to.isoformat()}")

        await AuditService().record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="ATTENDANCE_REPORT_EXPORTED",
            entity_type="attendance_export",
            after={
                "report": report,
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
                "rows": len(body),
                "format": fmt,
                "department_id": str(filters.department_id) if filters.department_id else None,
                "branch_id": str(filters.branch_id) if filters.branch_id else None,
            },
            ip=ip,
            user_agent=user_agent,
        )
        return file

    async def _people(self, company_id: UUID, ids: set[UUID]) -> dict[UUID, _Person]:
        if not ids:
            return {}
        result = await self._session.execute(
            select(
                Employee.id,
                Employee.employee_code,
                Employee.first_name,
                Employee.middle_name,
                Employee.last_name,
                Employee.display_name,
            ).where(Employee.company_id == company_id, Employee.id.in_(ids))
        )
        return {
            r.id: _Person(
                r.id,
                display_name(r.first_name, r.middle_name, r.last_name, r.display_name),
                r.employee_code,
            )
            for r in result
        }


def _who(people: dict[UUID, _Person], employee_id: UUID) -> tuple[str, str]:
    person = people.get(employee_id)
    return (person.name, person.code) if person else ("", "")


def _daily(
    rows: Sequence[Any], people: dict[UUID, _Person], tz: ZoneInfo
) -> tuple[list[str], list[list[Any]]]:
    header = [
        "Date",
        "Employee",
        "Code",
        "Status",
        "In",
        "Out",
        "Worked (min)",
        "Late (min)",
        "Early out (min)",
    ]
    body = []
    for r in rows:
        name, code = _who(people, r.employee_id)
        body.append(
            [
                r.attendance_date.isoformat(),
                name,
                code,
                BUCKET_LABELS.get(r.bucket, r.bucket),
                _clock(r.first_in, tz),
                _clock(r.last_out, tz),
                r.worked_minutes,
                r.late_minutes if r.is_late else "",
                r.early_minutes if r.is_early_out else "",
            ]
        )
    return header, body


def _late_early(
    rows: Sequence[Any], people: dict[UUID, _Person], tz: ZoneInfo
) -> tuple[list[str], list[list[Any]]]:
    header = ["Date", "Employee", "Code", "Late (min)", "Early out (min)"]
    body = []
    for r in rows:
        if not (r.is_late or r.is_early_out):
            continue
        name, code = _who(people, r.employee_id)
        body.append(
            [
                r.attendance_date.isoformat(),
                name,
                code,
                r.late_minutes if r.is_late else "",
                r.early_minutes if r.is_early_out else "",
            ]
        )
    return header, body


def _tallies(rows: Sequence[Any]) -> dict[UUID, _Tally]:
    tallies: dict[UUID, _Tally] = defaultdict(_Tally)
    for r in rows:
        t = tallies[r.employee_id]
        if r.bucket in _PRESENT:
            t.present += 1
        elif r.bucket == "HALF_DAY":
            t.half += 1
        elif r.bucket == "ABSENT":
            t.absent += 1
        elif r.bucket == "LEAVE":
            t.leave += 1
        elif r.bucket == "WEEKLY_OFF":
            t.off += 1
        elif r.bucket == "HOLIDAY":
            t.holiday += 1
        elif r.bucket == "INCOMPLETE":
            t.incomplete += 1
        if r.first_in is not None:
            t.days += 1
            t.worked += r.worked_minutes
            t.scheduled += r.scheduled_minutes or 0
    return tallies


def _by_name(tallies: dict[UUID, _Tally], people: dict[UUID, _Person]) -> list[UUID]:
    return sorted(tallies, key=lambda e: ((people[e].name.lower() if e in people else ""), str(e)))


def _present_absent(
    rows: Sequence[Any], people: dict[UUID, _Person], tz: ZoneInfo
) -> tuple[list[str], list[list[Any]]]:
    header = [
        "Employee",
        "Code",
        "Present",
        "Half day",
        "Absent",
        "Leave",
        "Weekly off",
        "Holiday",
        "Incomplete",
    ]
    tallies = _tallies(rows)
    body = []
    for employee_id in _by_name(tallies, people):
        t = tallies[employee_id]
        name, code = _who(people, employee_id)
        body.append(
            [name, code, t.present, t.half, t.absent, t.leave, t.off, t.holiday, t.incomplete]
        )
    return header, body


def _hours(
    rows: Sequence[Any], people: dict[UUID, _Person], tz: ZoneInfo
) -> tuple[list[str], list[list[Any]]]:
    header = ["Employee", "Code", "Days", "Worked (min)", "Average (min)", "Scheduled (min)"]
    tallies = _tallies(rows)
    body = []
    for employee_id in _by_name(tallies, people):
        t = tallies[employee_id]
        if t.days == 0:
            continue
        name, code = _who(people, employee_id)
        body.append([name, code, t.days, t.worked, round(t.worked / t.days), t.scheduled])
    return header, body


def _overtime(
    rows: Sequence[Any], people: dict[UUID, _Person], tz: ZoneInfo
) -> tuple[list[str], list[list[Any]]]:
    header = [
        "Date",
        "Employee",
        "Code",
        "Day class",
        "Detected (min)",
        "Approved (min)",
        "Pending (min)",
        "Status",
    ]
    body = []
    for r in rows:
        name, code = _who(people, r.employee_id)
        pending = max(0, r.minutes_detected - r.minutes_approved) if r.status == "PENDING" else 0
        body.append(
            [
                r.attendance_date.isoformat(),
                name,
                code,
                OVERTIME_DAY_CLASS_LABELS.get(r.day_class or "", r.day_class or ""),
                r.minutes_detected,
                r.minutes_approved,
                pending if pending > 0 else "",
                OVERTIME_STATUS_LABELS.get(r.status, r.status),
            ]
        )
    return header, body


_REPORTS = {
    "daily": _daily,
    "present-absent": _present_absent,
    "late-early": _late_early,
    "hours": _hours,
    "overtime": _overtime,
}
