"""Response schema for `GET /v1/attendance/summary`.

Every figure is a count of persisted `attendance_day` rows (or a sum of the engine's own minutes)
over the requested window, so the web and mobile dashboards show the same numbers instead of each
re-adding the rows themselves. A rate is a percentage (0-100), and `null` when nothing was there to
divide by, never a made-up 0%.
"""

from datetime import date
from uuid import UUID

from pydantic import BaseModel


class DailyRate(BaseModel):
    date: date
    #: Employees expected to work (not on a holiday, weekly off, or before joining / after exit).
    expected: int
    #: Of those, working: present, remote or on duty.
    present: int
    rate: float | None
    #: The rest of the day's tally, for the trend chart's other metrics. `remote`, `absent` and
    #: `leave` are of `expected`; `late` is of `checked_in` (days with a first punch), and
    #: `worked_minutes` is the engine's worked time summed over those checked-in days.
    remote: int
    absent: int
    leave: int
    late: int
    checked_in: int
    worked_minutes: int


class SummaryKpis(BaseModel):
    """Counts for one day. `total_employees` = employed rows + `no_record`."""

    total_employees: int
    no_record: int
    present: int
    remote: int
    on_duty: int
    absent: int
    leave: int
    half_day: int
    holiday: int
    weekly_off: int
    incomplete: int
    late: int
    not_checked_in: int
    checked_in: int
    exceptions: int
    overtime_employees: int
    overtime_minutes_detected: int
    overtime_minutes_approved: int
    not_employed: int


class BucketCount(BaseModel):
    bucket: str
    count: int


class LateBand(BaseModel):
    key: str
    label: str
    count: int


class Punctuality(BaseModel):
    """Only days with a complete check-in and check-out: an open day is not yet judged on time."""

    checked_in: int
    on_time: int
    late: int
    late_rate: float | None
    on_time_rate: float | None
    avg_late_minutes: float | None
    bands: list[LateBand]


class FrequentLate(BaseModel):
    employee_id: UUID
    late_days: int
    total_late_minutes: int


class WeekdayAbsence(BaseModel):
    #: 0 = Monday ... 6 = Sunday.
    index: int
    label: str
    expected: int
    absent: int
    rate: float | None


class GroupStat(BaseModel):
    """One department or branch on the focus date. `id` is null for "Unassigned"."""

    id: UUID | None
    name: str
    headcount: int
    expected: int
    present: int
    absent: int
    leave: int
    late: int
    rate: float | None


class AttendanceSummaryRead(BaseModel):
    date_from: date
    date_to: date
    #: The day the KPIs, distribution and breakdown describe (= `date_to`).
    focus_date: date
    compare_date: date
    is_today: bool
    #: Attendance days counted across the window, after the filters.
    row_count: int
    daily: list[DailyRate]
    focus: SummaryKpis
    #: `null` when there are no rows on `compare_date` to compare with.
    compare: SummaryKpis | None
    distribution: list[BucketCount]
    punctuality: Punctuality
    frequent_late: list[FrequentLate]
    weekday_absence: list[WeekdayAbsence]
    #: Department / branch comparison on the focus date. These ignore the department and branch
    #: filters themselves, otherwise picking one would leave nothing to compare.
    by_department: list[GroupStat]
    by_branch: list[GroupStat]
