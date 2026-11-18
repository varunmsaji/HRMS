"""SH-10 and SH-12 (engine 13).

SH-10: a punched gap matches the legacy break whose window it overlaps most (before: only the
gap's start time was compared), and under `excess_break_behaviour` DEDUCT a paid break pays up to
its maximum, the rest unpaid.

SH-12: a punched gap overlapping an automatic deduction's window counts toward that deduction
(before: the gap was excluded and the window deducted again on top)."""

from datetime import time

import pytest
from tests.unit.modules.attendance.test_break_management import (
    FULL_DAY,
    make_input,
    policy,
    punch,
    rule,
)

from hrms.modules.attendance.calculation import evaluate_day


def _day_with_gap(out_at: tuple[int, int], back_at: tuple[int, int]) -> list:
    return [punch(9, 0, "IN"), punch(*out_at, "OUT"), punch(*back_at, "IN"), punch(18, 0, "OUT")]


def test_paid_lunch_taken_ten_minutes_early_is_still_paid() -> None:
    """Paid 13:00-14:00 lunch taken 12:50-13:50: before, the gap started outside the window and
    the whole hour was unpaid (worked 480 instead of 540)."""
    lunch = rule(mode=None, paid=True)
    result = evaluate_day(make_input([lunch], _day_with_gap((12, 50), (13, 50))))
    (brk,) = result.breaks
    assert brk.shift_break_id == lunch.id and brk.is_paid
    assert result.worked_minutes == 540


def test_gap_matches_the_break_it_overlaps_most() -> None:
    """A gap 10:55-11:40 starts inside the tea window (10:45-11:00, unpaid) but lies mostly in a
    paid 11:00-12:00 window: it matches the paid break."""
    tea = rule("Tea", mode=None, start=time(10, 45), end=time(11, 0), minutes=15)
    meeting = rule("Paid break", mode=None, paid=True, start=time(11, 0), end=time(12, 0))
    result = evaluate_day(make_input([tea, meeting], _day_with_gap((10, 55), (11, 40))))
    (brk,) = result.breaks
    assert brk.shift_break_id == meeting.id


def test_a_gap_outside_every_window_stays_unmatched_and_unpaid() -> None:
    lunch = rule(mode=None, paid=True)
    result = evaluate_day(make_input([lunch], _day_with_gap((15, 0), (15, 30))))
    (brk,) = result.breaks
    assert brk.shift_break_id is None and not brk.is_paid
    assert result.worked_minutes == 510


@pytest.mark.parametrize(
    ("behaviour", "worked"),
    [
        ("DEDUCT", 540 - 120),  # 3h gap, 60 paid, 120 unpaid
        ("FLAG", 540),  # the excess is only flagged, as before
    ],
)
def test_paid_lunch_stretched_past_its_maximum(behaviour: str, worked: int) -> None:
    """A paid 13:00-14:00 lunch (max 60) stretched to 13:00-16:00: before, all 3 hours were paid
    under every policy."""
    lunch = rule(mode=None, paid=True, max_minutes=60)
    result = evaluate_day(
        make_input(
            [lunch],
            _day_with_gap((13, 0), (16, 0)),
            policy=policy(excess_break_behaviour=behaviour),
        )
    )
    assert result.worked_minutes == worked
    assert all(b.is_excess for b in result.breaks)
    assert result.excess_break_minutes == 180


def test_punched_lunch_overlapping_an_auto_deduction_is_not_deducted_twice() -> None:
    """AUTO_DEDUCT 13:00-14:00, employee punches out 12:30-13:30. Before: the punched hour was
    excluded and 30 more minutes deducted for the part of the window they were back (90 lost,
    450 worked, HALF_DAY under a 480-minute full day)."""
    result = evaluate_day(make_input([rule()], _day_with_gap((12, 30), (13, 30))))
    assert result.worked_minutes == 480
    assert result.auto_deducted_break_minutes == 0
    assert result.snapshot["breaks"]["auto_satisfied_by_punch"] == [
        {"rule": "Lunch", "punched_minutes": 60}
    ]


def test_a_short_punched_break_leaves_the_rest_of_the_auto_deduction() -> None:
    """A 20-minute punched gap inside a 60-minute automatic lunch: 40 more are deducted."""
    result = evaluate_day(make_input([rule()], _day_with_gap((13, 0), (13, 20))))
    assert result.worked_minutes == 540 - 60
    assert result.auto_deducted_break_minutes == 40


def test_auto_deduction_without_a_punched_gap_is_unchanged() -> None:
    result = evaluate_day(make_input([rule()], FULL_DAY))
    assert result.auto_deducted_break_minutes == 60
