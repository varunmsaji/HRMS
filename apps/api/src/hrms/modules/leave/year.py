"""Leave year boundary computation (client spec §10, LEAVE_DECISION_LOG.md LD-20/LD-21).

Pure functions only — no I/O, no session. `LeaveAccrualService`'s year-end sweep (LD-21) and any
future caller resolve a `LeaveYearSetting` row and an employee's `Employment.joining_date`
themselves, then call these.
"""

from dataclasses import dataclass
from datetime import date

LEAVE_YEAR_TYPES = ("CALENDAR", "FINANCIAL", "ANNIVERSARY", "CUSTOM")

# Client answers (2026-09-06): CALENDAR is Jan 1; FINANCIAL is India's Apr 1. Neither is a
# configurable value — they're fixed by the meaning of the word, not by `start_month`/`start_day`
# on the setting row (those only apply to CUSTOM/ANNIVERSARY's per-employee anchor).
_CALENDAR_START = (1, 1)
_FINANCIAL_START = (4, 1)


@dataclass(frozen=True, slots=True)
class LeaveYearSettingData:
    """Plain-data mirror of `LeaveYearSetting` — decouples this module from the ORM row shape so
    it stays pure/unit-testable without a DB session."""

    leave_year_type: str
    start_month: int | None
    start_day: int | None


def _safe_date(year: int, month: int, day: int) -> date:
    """Clamps to the last valid day of the month — handles a Feb 29 anchor in a non-leap year,
    or any other month/day combination that doesn't exist in a given year."""
    while True:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1
            if day < 1:
                raise


def _anchor_month_day(
    setting: LeaveYearSettingData, *, joining_date: date | None
) -> tuple[int, int]:
    if setting.leave_year_type == "CALENDAR":
        return _CALENDAR_START
    if setting.leave_year_type == "FINANCIAL":
        return _FINANCIAL_START
    if setting.leave_year_type == "ANNIVERSARY":
        if joining_date is None:
            raise ValueError("joining_date is required to resolve an ANNIVERSARY leave year")
        return joining_date.month, joining_date.day
    if setting.leave_year_type == "CUSTOM":
        if setting.start_month is None or setting.start_day is None:
            raise ValueError("CUSTOM leave year setting requires start_month and start_day")
        return setting.start_month, setting.start_day
    raise ValueError(f"Unknown leave_year_type: {setting.leave_year_type}")


def leave_year_start_for(
    setting: LeaveYearSettingData, *, as_of: date, joining_date: date | None = None
) -> date:
    """The start date of the leave year containing `as_of`."""
    month, day = _anchor_month_day(setting, joining_date=joining_date)
    this_year_start = _safe_date(as_of.year, month, day)
    if as_of >= this_year_start:
        return this_year_start
    return _safe_date(as_of.year - 1, month, day)


def is_leave_year_start(
    setting: LeaveYearSettingData, *, as_of: date, joining_date: date | None = None
) -> bool:
    """Whether `as_of` is itself the first day of a leave year for this employee — the day the
    year-end sweep (LD-21) credits `YEARLY` accrual and enforces the carry-forward cap."""
    month, day = _anchor_month_day(setting, joining_date=joining_date)
    return as_of == _safe_date(as_of.year, month, day)
