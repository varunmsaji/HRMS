"""D-1 — all minutes worked on a day off the shift does not operate count as overtime; where the
shift operates, only minutes beyond it do. No DB/HTTP."""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from tests.unit.modules.attendance.test_calculation import _base_input, _policy, _punch, _shift
from tests.unit.modules.attendance.test_night_ot import _policy as _ot_policy

from hrms.modules.attendance.calculation import AttendanceCalculationResult, evaluate_day


def _day(out_hour: int, **overrides: Any) -> AttendanceCalculationResult:
    """09:00 to `out_hour`:00 UTC against a 09:00-18:00 shift."""
    inputs: dict[str, Any] = dict(
        shift=_shift(),
        policy=_policy(),
        timezone="UTC",
        scheduled_start=datetime(2026, 8, 10, 9, 0, tzinfo=UTC),
        scheduled_end=datetime(2026, 8, 10, 18, 0, tzinfo=UTC),
        ot_policy=_ot_policy("NONE"),
        punches=[_punch(9, 0, "IN", day=10), _punch(out_hour, 0, "OUT", day=10)],
    )
    inputs.update(overrides)
    return evaluate_day(_base_input(**inputs))


@pytest.mark.parametrize(
    ("day_type", "out_hour", "expected"),
    [
        ("WEEKLY_OFF", 18, 540),
        ("WEEKLY_OFF", 20, 660),
        ("WEEKLY_OFF", 13, 240),
        ("HOLIDAY", 18, 540),
        ("SHUTDOWN", 18, 540),
    ],
)
def test_all_minutes_on_a_non_operating_day_off_are_overtime(
    day_type: str, out_hour: int, expected: int
) -> None:
    result = _day(out_hour, calendar_day_type=day_type)
    assert result.ot_minutes_detected == expected
    assert result.is_overtime is True


def test_a_roster_week_off_on_a_working_day_counts_all_minutes() -> None:
    assert _day(18, roster_week_off_override=True).ot_minutes_detected == 540


def test_shift_operating_on_the_weekly_off_counts_only_beyond_the_shift() -> None:
    result = _day(20, calendar_day_type="WEEKLY_OFF", shift=_shift(operates_on_weekly_off=True))
    assert result.ot_minutes_detected == 120


def test_shift_operating_on_the_holiday_counts_only_beyond_the_shift() -> None:
    result = _day(20, calendar_day_type="HOLIDAY", shift=_shift(operates_on_holiday=True))
    assert result.ot_minutes_detected == 120


def test_rostered_holiday_work_counts_only_beyond_the_shift() -> None:
    result = _day(20, calendar_day_type="HOLIDAY", roster_holiday_working_override=True)
    assert result.ot_minutes_detected == 120


def test_half_day_weekly_off_counts_only_beyond_the_shift() -> None:
    result = _day(20, calendar_day_type="WEEKLY_OFF", weekly_off_fraction="0.50")
    assert result.ot_minutes_detected == 120


def test_a_working_day_is_unchanged() -> None:
    assert _day(18).ot_minutes_detected == 0
    assert _day(20).ot_minutes_detected == 120


def test_daily_cap_and_minimum_still_apply_on_a_day_off() -> None:
    capped = replace(_ot_policy("NONE"), daily_cap_minutes=120)
    assert _day(18, calendar_day_type="WEEKLY_OFF", ot_policy=capped).ot_minutes_detected == 120
    high_minimum = replace(_ot_policy("NONE"), min_ot_minutes=600)
    assert _day(18, calendar_day_type="WEEKLY_OFF", ot_policy=high_minimum).ot_minutes_detected == 0


def test_comp_off_follows_all_the_minutes_on_a_day_off() -> None:
    comp_off = replace(_ot_policy("NONE"), comp_off_instead_of_pay=True)
    result = _day(18, calendar_day_type="WEEKLY_OFF", ot_policy=comp_off)
    assert result.comp_off_minutes_earned == 540


def test_no_overtime_policy_means_no_overtime_on_a_day_off() -> None:
    assert _day(18, calendar_day_type="WEEKLY_OFF", ot_policy=None).ot_minutes_detected == 0
