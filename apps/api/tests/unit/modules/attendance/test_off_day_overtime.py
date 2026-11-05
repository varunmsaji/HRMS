"""D-1 — all minutes worked on a day off the shift does not operate count as overtime; where the
shift operates, only minutes beyond it do. No DB/HTTP."""

from dataclasses import replace
from datetime import UTC, datetime, time
from typing import Any

import pytest
from tests.unit.modules.attendance.test_calculation import _base_input, _policy, _punch, _shift
from tests.unit.modules.attendance.test_night_ot import _policy as _ot_policy

from hrms.modules.attendance.calculation import (
    AttendanceCalculationResult,
    BandData,
    ShiftDutyBlockData,
    evaluate_day,
)


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


_BANDS = [
    BandData(min_minutes=0, max_minutes=239, classification="ABSENT"),
    BandData(min_minutes=240, max_minutes=419, classification="HALF_DAY"),
    BandData(min_minutes=420, max_minutes=None, classification="PRESENT"),
]
_LATENESS = [
    BandData(min_minutes=1, max_minutes=60, classification="LATE"),
    BandData(min_minutes=61, max_minutes=180, classification="HALF_DAY"),
    BandData(min_minutes=181, max_minutes=None, classification="ABSENT"),
]


def _off_day(punches: list[tuple[int, str]], **overrides: Any) -> AttendanceCalculationResult:
    inputs: dict[str, Any] = dict(
        calendar_day_type="WEEKLY_OFF",
        hour_bands=_BANDS,
        late_bands=_LATENESS,
        early_bands=_LATENESS,
        punches=[_punch(hour, 0, direction, day=10) for hour, direction in punches],
    )
    inputs.update(overrides)
    return _day(18, **inputs)


def _pay(result: AttendanceCalculationResult) -> tuple[str, str, str, str]:
    return (
        result.attendance_status,
        result.paid_day_fraction,
        result.lop_fraction,
        result.unpaid_off_fraction,
    )


@pytest.mark.parametrize("day_type", ["WEEKLY_OFF", "HOLIDAY", "SHUTDOWN"])
@pytest.mark.parametrize("punches", [[(10, "IN"), (12, "OUT")], [(14, "IN"), (20, "OUT")]])
def test_work_on_a_paid_day_off_is_never_penalised(
    day_type: str, punches: list[tuple[int, str]]
) -> None:
    result = _off_day(punches, calendar_day_type=day_type)
    assert _pay(result) == ("PRESENT", "1.00", "0.00", "0.00")
    assert result.is_late is False
    assert result.is_early_out is False
    assert result.ot_minutes_detected > 0


def test_a_stray_punch_on_a_day_off_does_not_cost_pay() -> None:
    result = _off_day([(10, "IN"), (10, "IN"), (12, "OUT"), (13, "OUT")])
    assert _pay(result) == ("PRESENT", "1.00", "0.00", "0.00")
    assert result.missing_punch is True


def test_a_roster_week_off_is_treated_as_a_day_off() -> None:
    result = _off_day(
        [(14, "IN"), (20, "OUT")], calendar_day_type="WORKING", roster_week_off_override=True
    )
    assert _pay(result) == ("PRESENT", "1.00", "0.00", "0.00")


def test_a_shift_operating_on_the_day_off_keeps_its_penalties() -> None:
    result = _off_day([(14, "IN"), (20, "OUT")], shift=_shift(operates_on_weekly_off=True))
    assert result.is_late is True
    assert result.attendance_status == "ABSENT"


def test_daily_wage_off_day_work_is_paid_as_overtime_only() -> None:
    result = _off_day([(9, "IN"), (18, "OUT")], pay_basis="DAILY_WAGE")
    assert _pay(result) == ("PRESENT", "0.00", "0.00", "1.00")
    assert result.ot_minutes_detected == 540


@pytest.mark.parametrize(
    ("out_hour", "paid", "unpaid_off"),
    [(11, "0.00", "1.00"), (14, "0.50", "0.50"), (18, "1.00", "0.00")],
)
def test_daily_wage_off_day_work_without_overtime_follows_the_hour_bands(
    out_hour: int, paid: str, unpaid_off: str
) -> None:
    result = _off_day([(9, "IN"), (out_hour, "OUT")], pay_basis="DAILY_WAGE", ot_policy=None)
    assert _pay(result) == ("PRESENT", paid, "0.00", unpaid_off)


def test_daily_wage_paid_holiday_stays_paid_alongside_overtime() -> None:
    result = _off_day(
        [(9, "IN"), (18, "OUT")],
        pay_basis="DAILY_WAGE",
        calendar_day_type="HOLIDAY",
        holiday_type="PUBLIC",
    )
    assert _pay(result) == ("PRESENT", "1.00", "0.00", "0.00")
    assert result.ot_minutes_detected == 540


def test_split_shift_work_on_a_day_off_ignores_missed_blocks() -> None:
    blocks = [
        ShiftDutyBlockData(
            sequence=1, start_time=time(9), end_time=time(12), crosses_midnight=False
        ),
        ShiftDutyBlockData(
            sequence=2, start_time=time(14), end_time=time(18), crosses_midnight=False
        ),
    ]
    result = _off_day(
        [(9, "IN"), (11, "OUT")],
        shift=_shift(shift_type="SPLIT", duty_blocks=blocks),
        policy=_policy(split_shift_missed_block_behaviour="ABSENT"),
    )
    assert _pay(result) == ("PRESENT", "1.00", "0.00", "0.00")
