"""Response schema for `GET /v1/dashboards/company/attendance-overview`.

Counting contract (also rendered on the dashboard): the *primary* buckets are mutually exclusive
and always sum to `total_employees`. `late`, `half_day`, `half_day_leave` and `exceptions` are
*overlays* — they describe employees already counted in a primary bucket and must never be added
to it.
"""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel


class AttendanceBuckets(BaseModel):
    total: int
    present: int
    absent: int
    on_leave: int
    on_duty: int
    remote_work: int
    not_checked_in: int
    incomplete: int
    not_expected: int
    no_record: int


class AttendanceDepartmentRow(AttendanceBuckets):
    department_id: UUID | None
    department_name: str


class AttendanceOverviewRead(AttendanceBuckets):
    attendance_date: date
    timezone: str
    is_today: bool
    generated_at: datetime
    #: Employees the engine expects to work (total minus NOT_EXPECTED and no-record).
    expected_employees: int
    late: int
    half_day: int
    half_day_leave: int
    exceptions: int
    departments: list[AttendanceDepartmentRow]
