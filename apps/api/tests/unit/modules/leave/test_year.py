"""Unit tests for the leave-year boundary functions (`leave/year.py`, LEAVE_DECISION_LOG.md
LD-20/LD-21) — no DB/HTTP, pure functions only."""

from datetime import date

from hrms.modules.leave.year import (
    LeaveYearSettingData,
    is_leave_year_start,
    leave_year_start_for,
)


def test_calendar_year_starts_january_first() -> None:
    setting = LeaveYearSettingData(leave_year_type="CALENDAR", start_month=None, start_day=None)
    assert leave_year_start_for(setting, as_of=date(2026, 6, 15)) == date(2026, 1, 1)
    assert leave_year_start_for(setting, as_of=date(2026, 1, 1)) == date(2026, 1, 1)
    assert is_leave_year_start(setting, as_of=date(2026, 1, 1)) is True
    assert is_leave_year_start(setting, as_of=date(2026, 1, 2)) is False


def test_financial_year_starts_april_first() -> None:
    setting = LeaveYearSettingData(leave_year_type="FINANCIAL", start_month=None, start_day=None)
    # A date before April 1 belongs to the financial year that started the previous April.
    assert leave_year_start_for(setting, as_of=date(2026, 2, 1)) == date(2025, 4, 1)
    assert leave_year_start_for(setting, as_of=date(2026, 4, 1)) == date(2026, 4, 1)
    assert leave_year_start_for(setting, as_of=date(2026, 12, 31)) == date(2026, 4, 1)
    assert is_leave_year_start(setting, as_of=date(2026, 4, 1)) is True
    assert is_leave_year_start(setting, as_of=date(2026, 1, 1)) is False


def test_custom_uses_configured_start_month_day() -> None:
    setting = LeaveYearSettingData(leave_year_type="CUSTOM", start_month=7, start_day=1)
    assert leave_year_start_for(setting, as_of=date(2026, 8, 1)) == date(2026, 7, 1)
    assert leave_year_start_for(setting, as_of=date(2026, 6, 30)) == date(2025, 7, 1)
    assert is_leave_year_start(setting, as_of=date(2026, 7, 1)) is True


def test_anniversary_uses_employee_joining_date() -> None:
    setting = LeaveYearSettingData(leave_year_type="ANNIVERSARY", start_month=None, start_day=None)
    joining_date = date(2023, 3, 15)
    # First anniversary trigger is the joining date itself.
    assert is_leave_year_start(setting, as_of=joining_date, joining_date=joining_date) is True
    # Then every year on the same month/day thereafter.
    assert is_leave_year_start(setting, as_of=date(2026, 3, 15), joining_date=joining_date) is True
    assert is_leave_year_start(setting, as_of=date(2026, 3, 14), joining_date=joining_date) is False
    assert leave_year_start_for(setting, as_of=date(2026, 6, 1), joining_date=joining_date) == date(
        2026, 3, 15
    )
    assert leave_year_start_for(setting, as_of=date(2026, 2, 1), joining_date=joining_date) == date(
        2025, 3, 15
    )


def test_anniversary_leap_day_anchor_clamps_in_non_leap_years() -> None:
    setting = LeaveYearSettingData(leave_year_type="ANNIVERSARY", start_month=None, start_day=None)
    joining_date = date(2020, 2, 29)
    # 2026 is not a leap year -> anchor clamps to Feb 28.
    assert is_leave_year_start(setting, as_of=date(2026, 2, 28), joining_date=joining_date) is True
    # 2024 is a leap year -> the real Feb 29 still works.
    assert is_leave_year_start(setting, as_of=date(2024, 2, 29), joining_date=joining_date) is True
