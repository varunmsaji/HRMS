"""Shift-window rule: one test per branch of `evaluate_shift_window` (pure, no database)."""

from datetime import UTC, datetime, timedelta

import pytest

from hrms.modules.attendance.exceptions import OutsideShiftWindowError
from hrms.modules.attendance.shift_window import (
    ShiftSpan,
    ShiftWindowDecision,
    combine_shift_window_decisions,
    evaluate_shift_window,
)

DAY = datetime(2026, 10, 30, tzinfo=UTC)
SHIFT = ShiftSpan(start=DAY.replace(hour=9, minute=30), end=DAY.replace(hour=18, minute=30))
NIGHT_YESTERDAY = ShiftSpan(
    start=(DAY - timedelta(days=1)).replace(hour=22), end=DAY.replace(hour=6)
)
NIGHT_TODAY = ShiftSpan(start=DAY.replace(hour=22), end=(DAY + timedelta(days=1)).replace(hour=6))


def decide(
    punch: datetime,
    *,
    direction: str = "IN",
    current: ShiftSpan | None = SHIFT,
    previous: ShiftSpan | None = None,
    allowance: int | None = 60,
    grace_out: int = 15,
):
    return evaluate_shift_window(
        direction=direction,
        punch_time=punch,
        current=current,
        previous=previous,
        early_in_allowance_minutes=allowance,
        grace_out_minutes=grace_out,
    )


def test_punch_in_before_the_allowance_is_too_early() -> None:
    d = decide(DAY.replace(hour=8, minute=29, second=59))
    assert d.outcome == "TOO_EARLY"
    assert d.earliest_punch_in == DAY.replace(hour=8, minute=30)
    assert d.shift == SHIFT


def test_punch_in_exactly_at_the_boundary_is_allowed() -> None:
    assert decide(DAY.replace(hour=8, minute=30)).outcome == "ALLOWED"


def test_punch_in_within_the_allowance_is_allowed() -> None:
    assert decide(DAY.replace(hour=9, minute=0)).outcome == "ALLOWED"


def test_a_late_punch_in_is_never_refused() -> None:
    # Lateness (and grace-in) stays the calculation engine's concern.
    assert decide(DAY.replace(hour=11, minute=45)).outcome == "ALLOWED"


def test_punch_after_shift_end_plus_grace_out_is_reported_not_refused() -> None:
    assert decide(DAY.replace(hour=18, minute=45)).outcome == "ALLOWED"  # exactly end + grace
    assert decide(DAY.replace(hour=18, minute=46)).outcome == "AFTER_SHIFT"
    assert decide(DAY.replace(hour=20), direction="OUT").outcome == "AFTER_SHIFT"


def test_punch_out_is_never_refused_even_before_the_allowance() -> None:
    assert decide(DAY.replace(hour=6), direction="OUT").outcome == "ALLOWED"


def test_null_allowance_never_refuses() -> None:
    d = decide(DAY.replace(hour=1), allowance=None)
    assert d.outcome == "ALLOWED"
    assert d.earliest_punch_in is None


def test_no_shift_is_not_judged() -> None:
    assert decide(DAY.replace(hour=1), current=None).outcome == "NO_SHIFT"


def test_zero_allowance_means_not_before_shift_start() -> None:
    assert decide(DAY.replace(hour=9, minute=29), allowance=0).outcome == "TOO_EARLY"
    assert decide(DAY.replace(hour=9, minute=30), allowance=0).outcome == "ALLOWED"


def test_overnight_shift_still_running_makes_a_just_after_midnight_punch_in_allowed() -> None:
    # 00:30 on the 31st: today's night shift (22:00) is hours away, yesterday's is running.
    punch = (DAY + timedelta(days=1)).replace(hour=0, minute=30)
    tomorrow_night = ShiftSpan(
        start=(DAY + timedelta(days=1)).replace(hour=22),
        end=(DAY + timedelta(days=2)).replace(hour=6),
    )
    assert decide(punch, current=tomorrow_night, previous=NIGHT_TODAY).outcome == "ALLOWED"
    assert decide(punch, current=tomorrow_night, previous=None).outcome == "TOO_EARLY"


def test_overnight_shift_punch_in_before_the_allowance_is_too_early() -> None:
    assert decide(DAY.replace(hour=20, minute=59), current=NIGHT_TODAY).outcome == "TOO_EARLY"
    assert decide(DAY.replace(hour=21), current=NIGHT_TODAY).outcome == "ALLOWED"


def test_yesterdays_finished_shift_does_not_excuse_an_early_punch_in() -> None:
    previous_day_shift = ShiftSpan(
        start=SHIFT.start - timedelta(days=1), end=SHIFT.end - timedelta(days=1)
    )
    d = decide(DAY.replace(hour=6), previous=previous_day_shift)
    assert d.outcome == "TOO_EARLY"


def test_error_carries_only_the_shift_window_fields() -> None:
    error = OutsideShiftWindowError(
        shift_start=SHIFT.start,
        shift_end=SHIFT.end,
        grace_in_minutes=10,
        grace_out_minutes=15,
        early_in_allowance_minutes=60,
        earliest_punch_in=DAY.replace(hour=8, minute=30),
    )
    assert (error.code, error.status_code) == ("OUTSIDE_SHIFT_WINDOW", 422)
    assert error.details[0]["context"] == {
        "shift_start": "2026-10-30T09:30:00+00:00",
        "shift_end": "2026-10-30T18:30:00+00:00",
        "grace_in_minutes": 10,
        "grace_out_minutes": 15,
        "early_in_allowance_minutes": 60,
        "earliest_punch_in": "2026-10-30T08:30:00+00:00",
    }


@pytest.mark.parametrize("hour", [0, 5, 8])
def test_every_early_hour_is_refused(hour: int) -> None:
    assert decide(DAY.replace(hour=hour)).outcome == "TOO_EARLY"


def test_candidate_dates_refuse_only_when_every_date_is_too_early() -> None:
    early = ShiftWindowDecision("TOO_EARLY", SHIFT, DAY.replace(hour=8, minute=30))
    allowed = ShiftWindowDecision("ALLOWED", SHIFT, DAY.replace(hour=8, minute=30))
    after = ShiftWindowDecision("AFTER_SHIFT", SHIFT, DAY.replace(hour=8, minute=30))
    missing = ShiftWindowDecision("NO_SHIFT")

    both_early = combine_shift_window_decisions([early, early])
    assert both_early.outcome == "TOO_EARLY"
    # The branch-local decision is the one the employee is shown.
    assert both_early.earliest_punch_in == early.earliest_punch_in
    assert combine_shift_window_decisions([early, allowed]).outcome == "ALLOWED"
    assert combine_shift_window_decisions([early, after]).outcome == "AFTER_SHIFT"
    assert combine_shift_window_decisions([early, missing]).outcome == "NO_SHIFT"
    assert combine_shift_window_decisions([]).outcome == "NO_SHIFT"
