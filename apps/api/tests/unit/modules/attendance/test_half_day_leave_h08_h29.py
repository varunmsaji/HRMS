"""H-08 and H-29 (owner decisions): half-day leave on a day off, and the worked half of a leave day.

H-08. A day that is, or becomes, a day off (holiday, weekly off, roster week-off) must not turn into
loss of pay because a half-day leave projection still sits on it. It keeps its normal day-off pay;
the leave projection, the balance and the reconciliation blocker are the leave module's and stay
until HR reconciles (nothing is refunded or erased here). Working on the day off is unchanged.

H-29. The worked half of a half-day-leave day follows the same approved rules, proportionally: the
grace (H-05), the D-01 mark credit and R-2 ceiling, and the P-05 scaled hour bands. The worked half
is judged against a half-day's own schedule and its credited minutes are scaled up to the full-day
bands. The one-minute cliff for a policy without mark bands is the same cliff a full day has (the
H-06 warning is the safeguard, separately).
"""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from tests.unit.modules.attendance.test_attendance_rules_remediation import (
    _EARLY_BANDS,
    _LATE_BANDS,
    _day,
    _leave,
)
from tests.unit.modules.attendance.test_calculation import _policy, _shift

from hrms.modules.attendance.calculation import LeaveOverlayEntry

EIGHT: dict[str, Any] = dict(
    shift=_shift(is_ot_eligible=True), scheduled_end=datetime(2026, 8, 10, 17, tzinfo=UTC)
)
FOUR: dict[str, Any] = dict(
    shift=_shift(is_ot_eligible=True), scheduled_end=datetime(2026, 8, 10, 13, tzinfo=UTC)
)


def triple(result: Any) -> tuple[str, str, str]:
    return (result.attendance_status, result.paid_day_fraction, result.lop_fraction)


# --- H-08 ---

DAYS_OFF: dict[str, dict[str, Any]] = {
    "roster_week_off": dict(roster_week_off_override=True),
    "calendar_holiday": dict(calendar_day_type="HOLIDAY", holiday_name="Diwali"),
    "calendar_weekly_off": dict(calendar_day_type="WEEKLY_OFF"),
}


@pytest.mark.parametrize("kind", sorted(DAYS_OFF))
@pytest.mark.parametrize("half", ["FIRST", "SECOND"])
@pytest.mark.parametrize("paid_leave", [True, False])
def test_a_half_day_leave_projection_on_a_day_off_creates_no_loss_of_pay(
    kind: str, half: str, paid_leave: bool
) -> None:
    result = _day([], leave_entries=_leave(half, paid=paid_leave), **DAYS_OFF[kind])
    assert triple(result) == ("NOT_EXPECTED", "1.00", "0.00")  # the normal day-off pay


def test_a_day_off_without_any_leave_is_the_same_so_the_projection_changes_nothing() -> None:
    plain = _day([], roster_week_off_override=True)
    with_leave = _day([], leave_entries=_leave("FIRST"), roster_week_off_override=True)
    assert triple(plain) == triple(with_leave) == ("NOT_EXPECTED", "1.00", "0.00")


def test_working_on_the_day_off_is_unchanged() -> None:
    result = _day(
        [(10, 0, "IN"), (14, 0, "OUT")],
        leave_entries=_leave("FIRST"),
        roster_week_off_override=True,
    )
    assert result.paid_day_fraction == "1.00" and result.lop_fraction == "0.00"


def test_a_working_day_with_the_same_leave_is_not_affected() -> None:
    """The fix is only for days off: on a working day the worked half is still decided at lock."""
    result = _day([], leave_entries=_leave("FIRST"))
    assert triple(result) == ("INCOMPLETE", "0.50", "0.00")


def test_full_day_leave_on_a_day_off_is_unchanged() -> None:
    """H-08 is about HALF-day leave; a full-day projection keeps the existing rule."""
    paid = _day([], leave_entries=_leave_full(True), roster_week_off_override=True)
    assert triple(paid) == ("LEAVE", "1.00", "0.00")


def _leave_full(paid: bool) -> list[Any]:
    return [LeaveOverlayEntry(fraction="1.00", is_paid=paid, half=None)]


# --- H-29: the worked half follows the same rules, proportionally ---


@pytest.mark.parametrize(
    ("arrive", "marks", "status", "paid", "lop"),
    [
        # 8h shift, first half on leave, worked half 13:00-17:00 (240 net). Grace 10.
        ((13, 0), False, "HALF_DAY", "1.00", "0.00"),  # full half worked
        ((13, 10), False, "HALF_DAY", "1.00", "0.00"),  # exactly the grace: 230 + 10 credited
        ((13, 11), False, "HALF_DAY", "0.75", "0.25"),  # one minute beyond: no credit (the cliff)
        ((13, 40), False, "HALF_DAY", "0.75", "0.25"),
        ((13, 11), True, "HALF_DAY", "1.00", "0.00"),  # a late mark: grace portion + 1 beyond
        ((13, 40), True, "HALF_DAY", "1.00", "0.00"),  # 10 grace + 30 beyond, inside the ceiling
        (
            (14, 11),
            True,
            "HALF_DAY",
            "0.75",
            "0.25",
        ),  # 61 late: marks don't cover it (HALF_DAY band)
    ],
)
def test_the_worked_half_follows_grace_and_mark_rules(
    arrive: tuple[int, int], marks: bool, status: str, paid: str, lop: str
) -> None:
    result = _day(
        [(*arrive, "IN"), (17, 0, "OUT")],
        leave_entries=_leave("FIRST"),
        late_bands=_LATE_BANDS if marks else [],
        **EIGHT,
    )
    assert triple(result) == (status, paid, lop)


def test_the_worked_half_leaving_early_follows_the_mark_rules() -> None:
    for out, expected in (((13, 0), "1.00"), ((12, 49), "1.00"), ((12, 20), "1.00")):
        result = _day(
            [(9, 0, "IN"), (*out, "OUT")],
            leave_entries=_leave("SECOND"),
            early_bands=_EARLY_BANDS,
            **EIGHT,
        )
        assert result.paid_day_fraction == expected, out


def test_the_r2_ceiling_bounds_the_mark_credit_on_the_worked_half() -> None:
    """4-hour shift, first half on leave: worked half 11:00-13:00 (120 net). Arriving 11:40 is 30
    minutes beyond the grace. Ceiling 59: 80 worked + 10 grace + 30 mark = 120 -> scaled x2 = 240 =
    the full-day threshold of this shift: PRESENT. Ceiling 0: only 90 -> 180 -> HALF_DAY."""
    base = _policy(grace_in_minutes=10, grace_out_minutes=10)
    punches = [(11, 40, "IN"), (13, 0, "OUT")]
    with_ceiling = _day(
        punches,
        leave_entries=_leave("FIRST"),
        late_bands=_LATE_BANDS,
        policy=replace(base, mark_credit_ceiling_minutes=59),
        **FOUR,
    )
    assert triple(with_ceiling) == ("HALF_DAY", "1.00", "0.00")
    without = _day(
        punches,
        leave_entries=_leave("FIRST"),
        late_bands=_LATE_BANDS,
        policy=replace(base, mark_credit_ceiling_minutes=0),
        **FOUR,
    )
    assert triple(without) == ("HALF_DAY", "0.75", "0.25")


@pytest.mark.parametrize(
    ("arrive", "paid", "lop"),
    [((11, 0), "1.00", "0.00"), ((11, 10), "1.00", "0.00"), ((11, 11), "0.75", "0.25")],
)
def test_the_worked_half_of_a_short_shift_uses_the_scaled_bands(
    arrive: tuple[int, int], paid: str, lop: str
) -> None:
    """P-05 + half-day leave on the 4-hour shift: the worked half (120 net) is scaled to the full
    day (240) and judged against the shift's scaled thresholds (120 / 240)."""
    result = _day([(*arrive, "IN"), (13, 0, "OUT")], leave_entries=_leave("FIRST"), **FOUR)
    assert (result.paid_day_fraction, result.lop_fraction) == (paid, lop)


def test_the_leave_half_is_never_double_counted_or_altered() -> None:
    result = _day([(13, 11, "IN"), (17, 0, "OUT")], leave_entries=_leave("FIRST"), **EIGHT)
    assert result.leave_fraction == "0.50"
    assert float(result.paid_day_fraction) + float(result.lop_fraction) == pytest.approx(1.0)
