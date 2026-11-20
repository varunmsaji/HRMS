"""One reading of a stored `attendance_day` row for both dashboards.

The company overview (`overview.py`, the home dashboard) and the attendance summary (`summary.py`,
the Attendance page) used to decide the same day differently. Both now ask this module for:

* the day **bucket** (`day_bucket`),
* whether the day is an **exception** HR must look at (`is_exception`),
* the **weight** a bucket has in the attendance rate (`rate_weight`).

No attendance rule lives here. Every verdict is the calculation engine's, stored on the row. The
one judgement added is a *time* one the engine cannot make because it has no clock: for today, a
day the engine left open (`ABSENT` or `INCOMPLETE`) while the shift is still running is not yet a
confirmed absence or a missing punch. With a first punch it reads `PRESENT`; with none it reads
`NOT_CHECKED_IN`. The shift is running until the row's own `scheduled_end`, else the end of the
company's local day. Without a clock (a past window) nothing is in progress.

Buckets (one per day, mutually exclusive):

    NOT_EMPLOYED   NOT_JOINED / EXITED
    HOLIDAY        NOT_EXPECTED on a holiday
    WEEKLY_OFF     NOT_EXPECTED on a weekly off
    NON_WORKING    any other NOT_EXPECTED
    REMOTE         WFH
    ON_DUTY, LEAVE, PRESENT, HALF_DAY, ABSENT, INCOMPLETE, CONFIG_ERROR   the engine's status
    NOT_CHECKED_IN today, open, no punch, shift not over

"Expected" (the denominator of every rate) is every bucket except NOT_EMPLOYED, HOLIDAY,
WEEKLY_OFF and NON_WORKING.

Rate: weighted present / expected, where PRESENT, REMOTE and ON_DUTY weigh 1, HALF_DAY weighs 0.5
and everything else 0. A half day is its own figure, never counted as "present".

Exception (a day needing HR attention): a missing punch, a day awaiting approval, an INCOMPLETE or
CONFIG_ERROR status, an unresolved or excess break, unresolved work on leave, or a submitted
regularization request for that date. A day still open because the shift is running is an
exception too, as the company overview always counted it (open question: whether it should be).
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, and_, case, exists, func, literal, or_

from hrms.modules.attendance.models import AttendanceDay, AttendanceRegularizationRequest
from hrms.shared.timezone import resolve_zoneinfo

NOT_EMPLOYED_STATUSES = ("NOT_JOINED", "EXITED")
#: Statuses the engine gives a day with no (or an unfinished) punch pair.
OPEN_STATUSES = ("ABSENT", "INCOMPLETE")
#: Statuses that are their own bucket.
STATUS_BUCKETS = (
    "PRESENT",
    "ON_DUTY",
    "HALF_DAY",
    "ABSENT",
    "LEAVE",
    "INCOMPLETE",
    "CONFIG_ERROR",
)
NOT_EXPECTED_BUCKETS = frozenset({"NOT_EMPLOYED", "HOLIDAY", "WEEKLY_OFF", "NON_WORKING"})

#: What a day of each bucket adds to the attendance rate's numerator.
RATE_WEIGHTS: dict[str, float] = {"PRESENT": 1.0, "REMOTE": 1.0, "ON_DUTY": 1.0, "HALF_DAY": 0.5}


def is_expected(bucket: str) -> bool:
    return bucket not in NOT_EXPECTED_BUCKETS


def rate_weight(bucket: str) -> float:
    return RATE_WEIGHTS.get(bucket, 0.0)


def attendance_rate(weighted_present: float, expected: int) -> float | None:
    """A percentage (0-100), or `None` when nobody was expected: never a made-up 0%."""
    return weighted_present / expected * 100 if expected > 0 else None


def local_day_end_utc(attendance_date: date, tz_name: str) -> datetime:
    """The instant the company's local `attendance_date` ends, in UTC."""
    tz: ZoneInfo = resolve_zoneinfo(tz_name)
    next_midnight = datetime.combine(attendance_date + timedelta(days=1), time.min, tzinfo=tz)
    return next_midnight.astimezone(UTC)


@dataclass(frozen=True)
class DayClock:
    """What "today" is and what time it is, for the rows dated today."""

    today: date
    now: datetime
    today_end: datetime

    @classmethod
    def for_company(cls, today: date, timezone: str, now: datetime | None = None) -> "DayClock":
        return cls(
            today=today, now=now or datetime.now(UTC), today_end=local_day_end_utc(today, timezone)
        )


def _in_progress(clock: DayClock | None) -> ColumnElement[bool]:
    """Today's row whose shift (scheduled end, else the local day's end) has not yet passed."""
    ad = AttendanceDay
    if clock is None:
        return literal(False)
    shift_end = func.coalesce(ad.scheduled_end, literal(clock.today_end))
    return and_(ad.attendance_date == literal(clock.today), shift_end > literal(clock.now))


def day_bucket(clock: DayClock | None = None) -> ColumnElement[str]:
    """The bucket of an `attendance_day` row. Callers add their own "no row" case."""
    ad = AttendanceDay
    status = ad.attendance_status
    has_punch = ad.actual_first_in.is_not(None)
    in_progress = _in_progress(clock)
    return case(
        (status.in_(NOT_EMPLOYED_STATUSES), "NOT_EMPLOYED"),
        (and_(status == "NOT_EXPECTED", ad.calendar_day_type == "HOLIDAY"), "HOLIDAY"),
        (and_(status == "NOT_EXPECTED", ad.calendar_day_type == "WEEKLY_OFF"), "WEEKLY_OFF"),
        (status == "NOT_EXPECTED", "NON_WORKING"),
        (status == "WFH", "REMOTE"),
        # Checked in and the shift is still running: present for now, not a missing punch.
        (and_(status.in_(OPEN_STATUSES), has_punch, in_progress), "PRESENT"),
        # No punch yet and the shift has not ended: not yet due, never "absent".
        (and_(status.in_(OPEN_STATUSES), ~has_punch, in_progress), "NOT_CHECKED_IN"),
        (status.in_(STATUS_BUCKETS), status),
        else_="NON_WORKING",
    )


def is_exception(company_id: object) -> ColumnElement[bool]:
    """Whether an `attendance_day` row needs HR attention (see the module docstring)."""
    ad = AttendanceDay
    pending_regularization = exists().where(
        AttendanceRegularizationRequest.company_id == company_id,
        AttendanceRegularizationRequest.employee_id == ad.employee_id,
        AttendanceRegularizationRequest.attendance_date == ad.attendance_date,
        AttendanceRegularizationRequest.status == "SUBMITTED",
    )
    return or_(
        ad.missing_punch.is_(True),
        ad.attendance_status.in_(("INCOMPLETE", "CONFIG_ERROR")),
        ad.is_pending_approval.is_(True),
        ad.has_unresolved_break.is_(True),
        ad.has_excess_break_exception.is_(True),
        and_(ad.work_on_leave_flagged.is_(True), ad.work_on_leave_resolution.is_(None)),
        pending_regularization,
    )
