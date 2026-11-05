"""Half-day leave: the worked half is judged on its own (D-2), with lateness and early departure
measured from the middle of the shift (D-3). No DB/HTTP."""

from dataclasses import replace
from datetime import UTC, datetime, time
from uuid import uuid4

import pytest
from tests.unit.modules.attendance.test_calculation import _base_input, _policy, _punch, _shift

from hrms.modules.attendance.calculation import (
    AttendanceCalculationResult,
    BandData,
    LeaveOverlayEntry,
    ShiftBreakData,
    ShiftDutyBlockData,
    evaluate_day,
)

_HOUR_BANDS = [
    BandData(min_minutes=0, max_minutes=239, classification="ABSENT"),
    BandData(min_minutes=240, max_minutes=419, classification="HALF_DAY"),
    BandData(min_minutes=420, max_minutes=None, classification="PRESENT"),
]
_LATENESS_BANDS = [
    BandData(min_minutes=1, max_minutes=60, classification="LATE"),
    BandData(min_minutes=61, max_minutes=180, classification="HALF_DAY"),
    BandData(min_minutes=181, max_minutes=None, classification="ABSENT"),
]


def _day(
    punches: list[tuple[int, int, str]],
    *,
    half: str = "FIRST",
    is_paid: bool = True,
    **overrides: object,
) -> AttendanceCalculationResult:
    """09:00-18:00 UTC shift (midpoint 13:30), 15 minutes grace."""
    inputs: dict[str, object] = dict(
        shift=_shift(),
        policy=_policy(grace_in_minutes=15, grace_out_minutes=15),
        timezone="UTC",
        scheduled_start=datetime(2026, 8, 10, 9, 0, tzinfo=UTC),
        scheduled_end=datetime(2026, 8, 10, 18, 0, tzinfo=UTC),
        hour_bands=_HOUR_BANDS,
        late_bands=_LATENESS_BANDS,
        early_bands=_LATENESS_BANDS,
        punches=[_punch(h, m, direction, day=10) for h, m, direction in punches],
        leave_entries=[LeaveOverlayEntry(fraction="0.50", is_paid=is_paid, half=half)],
    )
    inputs.update(overrides)
    return evaluate_day(_base_input(**inputs))


def _pay(result: AttendanceCalculationResult) -> tuple[str, str, str]:
    return (result.attendance_status, result.paid_day_fraction, result.lop_fraction)


def test_no_punches_loses_the_other_half() -> None:
    assert _pay(_day([])) == ("LEAVE", "0.50", "0.50")


def test_first_half_leave_arriving_at_the_midpoint_is_on_time() -> None:
    result = _day([(13, 30, "IN"), (18, 0, "OUT")], half="FIRST")
    assert _pay(result) == ("HALF_DAY", "1.00", "0.00")
    assert result.is_late is False
    assert result.late_minutes == 0


def test_second_half_leave_leaving_at_the_midpoint_is_not_early() -> None:
    result = _day([(9, 0, "IN"), (13, 30, "OUT")], half="SECOND")
    assert _pay(result) == ("HALF_DAY", "1.00", "0.00")
    assert result.is_early_out is False
    assert result.early_departure_minutes == 0


def test_first_half_leave_counts_lateness_from_the_midpoint() -> None:
    result = _day([(14, 15, "IN"), (18, 30, "OUT")], half="FIRST")
    assert result.late_minutes == 30
    assert result.is_late is True
    assert _pay(result) == ("HALF_DAY", "1.00", "0.00")


def test_second_half_leave_counts_early_departure_from_the_midpoint() -> None:
    result = _day([(8, 30, "IN"), (12, 45, "OUT")], half="SECOND")
    assert result.early_departure_minutes == 30
    assert result.is_early_out is True


def test_a_very_late_worked_half_loses_its_pay() -> None:
    result = _day([(17, 30, "IN"), (22, 0, "OUT")], half="FIRST")
    assert result.late_classification == "ABSENT"
    assert _pay(result) == ("LEAVE", "0.50", "0.50")


def test_a_few_minutes_of_work_does_not_earn_the_half() -> None:
    assert _pay(_day([(13, 30, "IN"), (13, 50, "OUT")], half="FIRST")) == ("LEAVE", "0.50", "0.50")


def test_a_normal_half_day_is_not_docked_by_the_full_day_hour_bands() -> None:
    """4.5 hours falls in the full-day HALF_DAY band but is a whole worked half."""
    result = _day([(13, 30, "IN"), (18, 0, "OUT")], half="FIRST")
    assert _pay(result) == ("HALF_DAY", "1.00", "0.00")


def test_unapproved_early_exit_rule_only_applies_past_the_midpoint() -> None:
    policy = _policy(
        grace_in_minutes=15, grace_out_minutes=15, early_departure_requires_approval=True
    )
    result = _day([(9, 0, "IN"), (13, 30, "OUT")], half="SECOND", policy=policy)
    assert _pay(result) == ("HALF_DAY", "1.00", "0.00")


def test_missing_out_stays_incomplete_until_the_lock() -> None:
    result = _day([(13, 30, "IN")], half="FIRST")
    assert _pay(result) == ("INCOMPLETE", "0.50", "0.00")
    assert result.leave_fraction == "0.50"


def test_missing_out_on_unpaid_leave_keeps_the_leave_lop() -> None:
    result = _day([(13, 30, "IN")], half="FIRST", is_paid=False)
    assert _pay(result) == ("INCOMPLETE", "0.00", "0.50")


@pytest.mark.parametrize(("half", "expected_paid"), [("FIRST", "1.00"), ("SECOND", "1.00")])
def test_on_duty_pays_the_other_half(half: str, expected_paid: str) -> None:
    result = _day([], half=half, on_duty_approved=True)
    assert _pay(result) == ("ON_DUTY", expected_paid, "0.00")
    assert result.leave_fraction == "0.50"


def test_on_duty_with_unpaid_leave_keeps_the_leave_lop() -> None:
    assert _pay(_day([], is_paid=False, on_duty_approved=True)) == ("ON_DUTY", "0.50", "0.50")


def test_half_day_weekly_off_with_half_day_leave_is_fully_covered() -> None:
    result = _day([], calendar_day_type="WEEKLY_OFF", weekly_off_fraction="0.50")
    assert _pay(result) == ("LEAVE", "1.00", "0.00")


def test_flexible_shift_has_no_lateness_or_core_hours_breach_on_half_day_leave() -> None:
    result = _day(
        [(14, 0, "IN"), (18, 30, "OUT")],
        half="FIRST",
        shift=_shift(
            shift_type="FLEXIBLE",
            required_minutes=480,
            core_start=time(11, 0),
            core_end=time(16, 0),
        ),
        policy=_policy(grace_in_minutes=15, core_hours_breach_behaviour="ABSENT"),
        scheduled_end=datetime(2026, 8, 10, 10, 0, tzinfo=UTC),
    )
    assert result.is_late is False
    assert result.is_core_hours_breach is False
    assert _pay(result) == ("HALF_DAY", "1.00", "0.00")


def test_split_shift_still_pays_the_half_for_any_work() -> None:
    """A split shift's missed-block rule would read the block on leave as missed."""
    blocks = [
        ShiftDutyBlockData(
            sequence=1, start_time=time(9, 0), end_time=time(13, 0), crosses_midnight=False
        ),
        ShiftDutyBlockData(
            sequence=2, start_time=time(14, 0), end_time=time(18, 0), crosses_midnight=False
        ),
    ]
    result = _day(
        [(14, 0, "IN"), (18, 0, "OUT")],
        half="FIRST",
        shift=_shift(shift_type="SPLIT", duty_blocks=blocks),
    )
    assert _pay(result) == ("HALF_DAY", "1.00", "0.00")


_LUNCH = ShiftBreakData(
    id=uuid4(),
    break_kind="FIXED_WINDOW",
    start_time=time(13, 0),
    end_time=time(14, 0),
    window_start=None,
    window_end=None,
    min_minutes=None,
    max_minutes=None,
    is_paid=False,
    is_mandatory=False,
)


def test_first_half_leave_returning_when_lunch_ends_is_on_time() -> None:
    result = _day([(14, 0, "IN"), (18, 0, "OUT")], shift=_shift(breaks=[_LUNCH]))
    assert result.is_late is False
    assert _pay(result) == ("HALF_DAY", "1.00", "0.00")


def test_first_half_leave_counts_lateness_from_the_end_of_lunch() -> None:
    result = _day([(14, 16, "IN"), (18, 0, "OUT")], shift=_shift(breaks=[_LUNCH]))
    assert result.late_minutes == 1


def test_second_half_leave_leaving_when_lunch_starts_is_not_early() -> None:
    result = _day(
        [(9, 0, "IN"), (13, 0, "OUT")],
        half="SECOND",
        shift=_shift(breaks=[_LUNCH]),
        policy=_policy(
            grace_in_minutes=15, grace_out_minutes=15, early_departure_requires_approval=True
        ),
    )
    assert result.is_early_out is False
    assert _pay(result) == ("HALF_DAY", "1.00", "0.00")


def test_a_break_away_from_the_midpoint_does_not_move_the_split() -> None:
    tea = replace(_LUNCH, start_time=time(11, 0), end_time=time(11, 15))
    result = _day([(14, 0, "IN"), (18, 0, "OUT")], shift=_shift(breaks=[tea]))
    assert result.late_minutes == 15
