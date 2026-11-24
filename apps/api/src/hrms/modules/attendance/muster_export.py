"""The muster register as a CSV file: one row per employee, one column per date.

The cells are the same buckets the Attendance page shows (`day_classification`), read over the same
population and filters as `/attendance/summary`, so a register and the dashboard never disagree and
a caller sees only the employees their attendance scope allows. A day with no stored record is left
blank, never written as absent. Every download is audited: the register lists names against
attendance, which is personal data.
"""

import csv
import io
from collections import defaultdict
from datetime import date, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.audit.service import AuditService
from hrms.core.errors.base import ValidationError
from hrms.modules.attendance.summary import AttendanceSummaryService, SummaryFilters
from hrms.modules.employee.models import Employee

#: Employees times days; beyond this the file is too large to build in one request.
MAX_EXPORT_CELLS = 1_000_000

#: The code written in a cell for each bucket (plain ASCII, so any spreadsheet tool reads it).
BUCKET_CODES: dict[str, str] = {
    "PRESENT": "P",
    "REMOTE": "R",
    "ON_DUTY": "OD",
    "HALF_DAY": "HD",
    "ABSENT": "A",
    "LEAVE": "L",
    "INCOMPLETE": "!",
    "CONFIG_ERROR": "E",
    "HOLIDAY": "H",
    "WEEKLY_OFF": "W",
    "NON_WORKING": "NW",
    "NOT_EMPLOYED": "NE",
    "NOT_CHECKED_IN": "NC",
}
BUCKET_LABELS: dict[str, str] = {
    "PRESENT": "Present",
    "REMOTE": "Work from home",
    "ON_DUTY": "On duty",
    "HALF_DAY": "Half day",
    "ABSENT": "Absent",
    "LEAVE": "On leave",
    "INCOMPLETE": "Incomplete (missing punch)",
    "CONFIG_ERROR": "Needs attention",
    "HOLIDAY": "Holiday",
    "WEEKLY_OFF": "Weekly off",
    "NON_WORKING": "Non-working day",
    "NOT_EMPLOYED": "Not employed",
    "NOT_CHECKED_IN": "Not checked in yet",
}
_PRESENT = frozenset({"PRESENT", "REMOTE", "ON_DUTY"})
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def csv_text(value: object) -> str:
    """A cell as text. One that starts like a spreadsheet formula gets a leading apostrophe, so a
    name an employee typed can never run as one."""
    text = "" if value is None else str(value)
    return f"'{text}" if text.startswith(_FORMULA_START) else text


def display_name(first: str, middle: str | None, last: str | None, shown: str | None) -> str:
    return shown or " ".join(part for part in (first, middle, last) if part)


class MusterExportService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def build(
        self,
        company_id: UUID,
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
    ) -> tuple[str, str]:
        """The file name and the CSV text (BOM first, so Excel reads UTF-8)."""
        cells = await AttendanceSummaryService(self._session).muster_cells(
            company_id,
            date_from=date_from,
            date_to=date_to,
            filters=filters,
            today=today,
            timezone=timezone,
            now=now,
        )
        by_employee: dict[UUID, dict[date, str]] = defaultdict(dict)
        for employee_id, day, bucket in cells:
            by_employee[employee_id][day] = bucket
        days = (date_to - date_from).days + 1
        if len(by_employee) * days > MAX_EXPORT_CELLS:
            raise ValidationError("That register is too large. Narrow the dates or the filters.")

        people = await self._people(company_id, list(by_employee))
        dates = [date_from + timedelta(days=i) for i in range(days)]

        out = io.StringIO()
        writer = csv.writer(out, lineterminator="\r\n")
        writer.writerow(
            ["Employee", "Code", *(d.isoformat() for d in dates)]
            + ["Present", "Half day", "Absent", "Leave", "Weekly off", "Holiday", "Incomplete"]
        )
        for employee_id in sorted(by_employee, key=lambda e: (people[e][0].lower(), str(e))):
            name, code = people[employee_id]
            row = by_employee[employee_id]
            counts = [row.get(d) for d in dates]
            writer.writerow(
                [csv_text(name), csv_text(code)]
                + [BUCKET_CODES.get(b, "") if b else "" for b in counts]
                + [
                    sum(1 for b in counts if b in _PRESENT),
                    counts.count("HALF_DAY"),
                    counts.count("ABSENT"),
                    counts.count("LEAVE"),
                    counts.count("WEEKLY_OFF"),
                    counts.count("HOLIDAY"),
                    counts.count("INCOMPLETE"),
                ]
            )
        writer.writerow([])
        writer.writerow(["Legend"])
        for bucket, code in BUCKET_CODES.items():
            writer.writerow([code, BUCKET_LABELS[bucket]])

        await AuditService().record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="ATTENDANCE_MUSTER_EXPORTED",
            entity_type="attendance_export",
            after={
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
                "employees": len(by_employee),
                "department_id": str(filters.department_id) if filters.department_id else None,
                "branch_id": str(filters.branch_id) if filters.branch_id else None,
            },
            ip=ip,
            user_agent=user_agent,
        )
        return (
            f"muster-register_{date_from.isoformat()}_{date_to.isoformat()}.csv",
            "﻿" + out.getvalue(),
        )

    async def _people(self, company_id: UUID, ids: list[UUID]) -> dict[UUID, tuple[str, str]]:
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
            r.id: (
                display_name(r.first_name, r.middle_name, r.last_name, r.display_name),
                r.employee_code,
            )
            for r in result
        }
