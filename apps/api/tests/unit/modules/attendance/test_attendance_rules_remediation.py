"""Attendance rules audit, AR-01..AR-14 (`ATTENDANCE_RULES_COMPREHENSIVE_AUDIT_2026-11-16.md`),
owner decisions D-01..D-04. Pure engine, no DB/HTTP.

Default day: FIXED 09:00-18:00 UTC with an unpaid 13:00-14:00 lunch (net 480; halves 09-13 and
14-18, 240 each), grace 10/10, the "Standard office" hour bands (ABSENT < 240, HALF_DAY 240-479,
PRESENT >= 480), overtime always eligible and auto-approved."""

from dataclasses import replace
from datetime import UTC, datetime, time
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from tests.unit.modules.attendance.test_calculation import _base_input, _policy, _punch, _shift
from tests.unit.modules.attendance.test_night_ot import _policy as _night_policy

from hrms.modules.attendance.calculation import (
    AttendanceCalculationResult,
    BandData,
    LeaveOverlayEntry,
    OvertimePolicyInputs,
    ShiftBreakData,
    ShiftDutyBlockData,
    evaluate_day,
    split_shift_halves,
)

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
    mode="AUTO_DEDUCT",
    scheduled_minutes=60,
)
_HOUR_BANDS = [
    BandData(min_minutes=0, max_minutes=239, classification="ABSENT"),
    BandData(min_minutes=240, max_minutes=479, classification="HALF_DAY"),
    BandData(min_minutes=480, max_minutes=None, classification="PRESENT"),
]
#: A late mark for under an hour, a half day from an hour (and the same for leaving early).
_LATE_BANDS = [
    BandData(min_minutes=1, max_minutes=59, classification="LATE"),
    BandData(min_minutes=60, max_minutes=None, classification="HALF_DAY"),
]
_EARLY_BANDS = [
    BandData(min_minutes=1, max_minutes=59, classification="EARLY_DEPARTURE"),
    BandData(min_minutes=60, max_minutes=None, classification="HALF_DAY"),
]


def _ot() -> OvertimePolicyInputs:
    return replace(_night_policy("SHIFT_FLAG"), night_window_start=None, night_window_end=None)


def _day(punches: list[tuple[Any, ...]], **overrides: Any) -> AttendanceCalculationResult:
    inputs: dict[str, Any] = dict(
        shift=_shift(is_ot_eligible=True, breaks=[_LUNCH]),
        policy=_policy(grace_in_minutes=10, grace_out_minutes=10),
        timezone="UTC",
        scheduled_start=datetime(2026, 8, 10, 9, 0, tzinfo=UTC),
        scheduled_end=datetime(2026, 8, 10, 18, 0, tzinfo=UTC),
        ot_policy=_ot(),
        hour_bands=_HOUR_BANDS,
        late_bands=[],
        early_bands=[],
        punches=[_punch(*p[:3], day=p[3] if len(p) > 3 else 10) for p in punches],
    )
    inputs.update(overrides)
    return evaluate_day(_base_input(**inputs))


def _leave(half: str, *, paid: bool = True) -> list[LeaveOverlayEntry]:
    return [LeaveOverlayEntry(fraction="0.50", is_paid=paid, half=half)]


def _pay(result: AttendanceCalculationResult) -> tuple[str, str]:
    return result.paid_day_fraction, result.lop_fraction


# --- AR-02 / D-01: lateness is judged separately from full-day eligibility ----------------------


@pytest.mark.parametrize(
    ("in_minute", "late", "status"),
    [(10, 0, "PRESENT"), (11, 1, "PRESENT"), (59, 49, "PRESENT")],
)
def test_a_late_mark_does_not_also_cost_half_a_day(in_minute: int, late: int, status: str) -> None:
    """Arriving at 09:11 and leaving on time was HALF_DAY (0.50 LOP) before engine 16, because
    the hour band was one minute short. The late band calls it a late mark; that is the verdict."""
    result = _day([(9, in_minute, "IN"), (18, 0, "OUT")], late_bands=_LATE_BANDS)
    assert result.late_minutes == late
    assert result.is_late is (late > 0)
    assert result.attendance_status == status
    assert _pay(result) == ("1.00", "0.00")


def test_a_late_arrival_in_the_half_day_band_is_still_a_half_day() -> None:
    result = _day([(10, 10, "IN"), (18, 0, "OUT")], late_bands=_LATE_BANDS)
    assert result.late_minutes == 60
    assert result.attendance_status == "HALF_DAY"
    assert _pay(result) == ("0.50", "0.50")


@pytest.mark.parametrize(("out_minute", "early"), [(50, 0), (49, 1), (1, 49)])
def test_an_early_departure_mark_does_not_also_cost_half_a_day(out_minute: int, early: int) -> None:
    result = _day([(9, 0, "IN"), (17, out_minute, "OUT")], early_bands=_EARLY_BANDS)
    assert result.early_departure_minutes == early
    assert result.attendance_status == "PRESENT"


def test_real_worked_minutes_and_overtime_are_not_inflated_by_the_late_mark() -> None:
    result = _day([(9, 30, "IN"), (19, 0, "OUT")], late_bands=_LATE_BANDS)
    assert result.worked_minutes == 510
    assert result.ot_minutes_detected == 30  # 510 worked against 480, not 60
    assert result.snapshot["grace_band_credit"]["in"] == 30


def test_minutes_no_band_covers_are_only_forgiven_up_to_the_grace() -> None:
    """A policy with no late bands has no late rule of its own, so the hours decide, as before.
    (The shipped templates now carry late and early bands for this reason.)"""
    result = _day([(9, 11, "IN"), (18, 0, "OUT")])
    assert result.attendance_status == "HALF_DAY"


def test_a_late_mark_never_lifts_a_day_out_of_absence() -> None:
    """An open-ended "late" band must not turn two hours of work into a full paid day."""
    open_ended = [BandData(min_minutes=1, max_minutes=None, classification="LATE")]
    result = _day([(16, 0, "IN"), (18, 0, "OUT")], late_bands=open_ended)
    assert result.worked_minutes == 120
    assert result.attendance_status == "ABSENT"
    assert _pay(result) == ("0.00", "1.00")


# --- AR-05: the harshest verdict wins ----------------------------------------------------------


def test_a_half_day_early_band_does_not_soften_an_absent_hour_band() -> None:
    """Two hours worked was HALF_DAY (0.50 paid) once an early band said HALF_DAY, and ABSENT
    with no early band at all: adding a penalty paid more."""
    result = _day([(9, 0, "IN"), (11, 0, "OUT")], early_bands=_EARLY_BANDS)
    assert result.attendance_status == "ABSENT"
    assert _pay(result) == ("0.00", "1.00")


def test_a_half_day_late_band_does_not_soften_an_absent_hour_band() -> None:
    result = _day([(16, 0, "IN"), (18, 0, "OUT")], late_bands=_LATE_BANDS)
    assert result.attendance_status == "ABSENT"


def test_an_absent_late_band_still_overrides_a_present_hour_band() -> None:
    bands = [BandData(min_minutes=1, max_minutes=None, classification="ABSENT")]
    result = _day([(9, 30, "IN"), (19, 0, "OUT")], late_bands=bands)
    assert result.attendance_status == "ABSENT"
    assert result.ot_minutes_detected == 0


# --- AR-02 / D-02: a short worked half on a half-day-leave day ---------------------------------


@pytest.mark.parametrize(
    ("in_minute", "expected"),
    [(10, ("1.00", "0.00")), (11, ("0.75", "0.25"))],
)
def test_first_half_leave_one_minute_past_grace_no_longer_loses_the_worked_half(
    in_minute: int, expected: tuple[str, str]
) -> None:
    """IN 14:11 with no late bands: 229 minutes worked was paid nothing (0.50 LOP) before
    engine 16. The worked half reaches the half-day band, so half of it is paid."""
    result = _day([(14, in_minute, "IN"), (18, 0, "OUT")], leave_entries=_leave("FIRST"))
    assert _pay(result) == expected
    assert result.attendance_status == "HALF_DAY"
    assert result.leave_fraction == "0.50"


def test_with_a_late_band_the_same_minute_is_a_late_mark_and_the_half_is_paid() -> None:
    result = _day(
        [(14, 11, "IN"), (18, 0, "OUT")], leave_entries=_leave("FIRST"), late_bands=_LATE_BANDS
    )
    assert result.late_minutes == 1
    assert _pay(result) == ("1.00", "0.00")


def test_second_half_leave_leaving_just_early_is_paid_in_proportion() -> None:
    result = _day([(9, 0, "IN"), (12, 49, "OUT")], leave_entries=_leave("SECOND"))
    assert result.early_departure_minutes == 1
    assert _pay(result) == ("0.75", "0.25")


def test_a_worked_half_under_the_absent_band_is_still_lost() -> None:
    result = _day([(14, 0, "IN"), (15, 30, "OUT")], leave_entries=_leave("FIRST"))
    assert result.attendance_status == "LEAVE"
    assert _pay(result) == ("0.50", "0.50")


def test_unpaid_half_day_leave_with_a_short_worked_half_reconciles() -> None:
    result = _day([(14, 11, "IN"), (18, 0, "OUT")], leave_entries=_leave("FIRST", paid=False))
    assert _pay(result) == ("0.25", "0.75")
    total = Decimal(result.paid_day_fraction) + Decimal(result.lop_fraction)
    assert total == Decimal("1.00")


# --- AR-07: early arrival is not work on leave -------------------------------------------------


@pytest.mark.parametrize("in_time", [(13, 30), (12, 40), (12, 1)])
def test_arriving_early_for_the_worked_half_is_neither_a_conflict_nor_credited(
    in_time: tuple[int, int],
) -> None:
    """First-half leave, second half starts 14:00. IN 12:40 flagged the day and blocked period
    close before engine 16."""
    result = _day([(*in_time, "IN"), (18, 0, "OUT")], leave_entries=_leave("FIRST"))
    assert result.work_on_leave_flagged is False
    assert result.worked_minutes == 240
    assert result.ot_minutes_detected == 0
    assert _pay(result) == ("1.00", "0.00")


def test_early_arrival_does_not_take_away_overtime_earned_after_the_shift() -> None:
    """IN 12:40, OUT 20:00: the two hours after shift end were removed with the flag before."""
    result = _day([(12, 40, "IN"), (20, 0, "OUT")], leave_entries=_leave("FIRST"))
    assert result.work_on_leave_flagged is False
    assert result.ot_minutes_detected == 120


def test_working_most_of_the_leave_half_is_still_a_conflict() -> None:
    """Boundary: present for half of the leave half (120 of 240 minutes) or more."""
    just_under = _day([(11, 1, "IN"), (18, 0, "OUT")], leave_entries=_leave("FIRST"))
    assert just_under.work_on_leave_flagged is False
    at_half = _day([(11, 0, "IN"), (18, 0, "OUT")], leave_entries=_leave("FIRST"))
    assert at_half.work_on_leave_flagged is True
    assert at_half.ot_minutes_detected == 0
    whole_day = _day([(9, 0, "IN"), (21, 0, "OUT")], leave_entries=_leave("SECOND"))
    assert whole_day.work_on_leave_flagged is True
    assert whole_day.worked_minutes == 240  # the leave half is paid as leave, not as work
    assert whole_day.ot_minutes_detected == 0
    assert _pay(whole_day) == ("1.00", "0.00")


# --- AR-06: half-day leave on SPLIT and FLEXIBLE shifts ----------------------------------------

_BLOCKS = [
    ShiftDutyBlockData(1, time(9, 0), time(13, 0), False),
    ShiftDutyBlockData(2, time(17, 0), time(21, 0), False),
]


def _split_day(punches: list[tuple[Any, ...]], **overrides: Any) -> AttendanceCalculationResult:
    return _day(
        punches,
        shift=_shift(shift_type="SPLIT", is_ot_eligible=True, duty_blocks=_BLOCKS),
        scheduled_end=datetime(2026, 8, 10, 21, 0, tzinfo=UTC),
        **overrides,
    )


def test_split_blocks_are_divided_at_the_middle_of_the_span() -> None:
    placed = [
        (datetime(2026, 8, 10, 9, tzinfo=UTC), datetime(2026, 8, 10, 13, tzinfo=UTC)),
        (datetime(2026, 8, 10, 17, tzinfo=UTC), datetime(2026, 8, 10, 21, tzinfo=UTC)),
    ]
    first, second = split_shift_halves(placed)
    assert (first, second) == ([placed[0]], [placed[1]])


def test_split_shift_first_half_leave_earns_overtime_after_the_worked_block() -> None:
    """Worked 17:00-23:00 against the 4-hour second block: 0 overtime before engine 16."""
    result = _split_day([(17, 0, "IN"), (23, 0, "OUT")], leave_entries=_leave("FIRST"))
    assert result.ot_minutes_detected == 120
    assert result.work_on_leave_flagged is False
    assert _pay(result) == ("1.00", "0.00")
    assert result.snapshot["split_missed_blocks"] == 0  # the leave block is not "missed"


def test_split_shift_working_the_block_that_is_on_leave_is_flagged_not_paid_twice() -> None:
    result = _split_day(
        [(9, 0, "IN"), (13, 0, "OUT"), (17, 0, "IN"), (21, 0, "OUT")],
        leave_entries=_leave("SECOND"),
    )
    assert result.work_on_leave_flagged is True
    assert result.worked_minutes == 240
    assert result.ot_minutes_detected == 0


def test_split_shift_without_leave_is_unchanged() -> None:
    result = _split_day([(9, 0, "IN"), (13, 0, "OUT"), (17, 0, "IN"), (23, 0, "OUT")])
    assert result.worked_minutes == 600
    assert result.ot_minutes_detected == 120
    assert result.attendance_status == "PRESENT"


def _flex_day(punches: list[tuple[Any, ...]], **overrides: Any) -> AttendanceCalculationResult:
    return _day(
        punches,
        shift=_shift(shift_type="FLEXIBLE", is_ot_eligible=True, required_minutes=480),
        scheduled_start=datetime(2026, 8, 10, 8, 0, tzinfo=UTC),
        scheduled_end=datetime(2026, 8, 10, 10, 0, tzinfo=UTC),
        **overrides,
    )


def test_flexible_half_day_leave_overtime_and_the_full_day_conflict() -> None:
    """Required 480, so 240 on a half-day-leave day. Boundary at the full requirement."""
    some = _flex_day([(9, 0, "IN"), (15, 0, "OUT")], leave_entries=_leave("FIRST"))
    assert (some.ot_minutes_detected, some.work_on_leave_flagged) == (120, False)
    just_under = _flex_day([(9, 0, "IN"), (16, 59, "OUT")], leave_entries=_leave("FIRST"))
    assert (just_under.ot_minutes_detected, just_under.work_on_leave_flagged) == (239, False)
    # A full day's requirement on a half-day-leave day: 360 overtime plus the leave before.
    full = _flex_day([(9, 0, "IN"), (19, 0, "OUT")], leave_entries=_leave("SECOND"))
    assert (full.ot_minutes_detected, full.work_on_leave_flagged) == (0, True)


# --- AR-01 / D-03: work on a roster week-off ---------------------------------------------------


def _roster_off(punches: list[tuple[Any, ...]], **overrides: Any) -> AttendanceCalculationResult:
    """What the service builds: a roster week-off row cannot carry a shift."""
    return _day(
        punches,
        roster_week_off_override=True,
        shift=None,
        scheduled_start=None,
        scheduled_end=None,
        **overrides,
    )


def test_roster_week_off_work_is_weekly_off_overtime() -> None:
    """09:00-18:00 on a rostered day off earned no overtime at all before engine 16."""
    result = _roster_off([(9, 0, "IN"), (18, 0, "OUT")])
    assert result.attendance_status == "PRESENT"
    assert _pay(result) == ("1.00", "0.00")
    assert result.ot_minutes_detected == 540
    assert result.ot_day_class == "WEEKLY_OFF"
    assert result.worked_on_weekly_off is True


def test_roster_week_off_on_a_holiday_keeps_the_holiday_class() -> None:
    result = _roster_off(
        [(9, 0, "IN"), (11, 0, "OUT")], calendar_day_type="HOLIDAY", holiday_type="PUBLIC"
    )
    assert (result.ot_minutes_detected, result.ot_day_class) == (120, "HOLIDAY")


@pytest.mark.parametrize(("flag", "minutes"), [(True, 540), (False, 0), (None, 0)])
def test_roster_week_off_shift_flag_eligibility_reads_the_usual_shift(
    flag: bool | None, minutes: int
) -> None:
    result = _roster_off(
        [(9, 0, "IN"), (18, 0, "OUT")],
        ot_policy=replace(_ot(), eligibility="SHIFT_FLAG"),
        off_day_shift_ot_eligible=flag,
    )
    assert result.ot_minutes_detected == minutes


def test_roster_week_off_comp_off_policy_earns_comp_off_for_the_same_minutes() -> None:
    result = _roster_off(
        [(9, 0, "IN"), (18, 0, "OUT")], ot_policy=replace(_ot(), comp_off_instead_of_pay=True)
    )
    assert result.comp_off_minutes_earned == result.ot_minutes_detected == 540


def test_a_plain_day_without_a_shift_still_earns_no_overtime() -> None:
    result = _day(
        [(9, 0, "IN"), (20, 0, "OUT")], shift=None, scheduled_start=None, scheduled_end=None
    )
    assert result.ot_minutes_detected == 0


def test_roster_week_off_without_punches_is_a_paid_day_off() -> None:
    result = _roster_off([])
    assert result.attendance_status == "NOT_EXPECTED"
    assert result.ot_minutes_detected == 0


# --- AR-12: a completed short shift keeps its overtime -----------------------------------------


def test_short_shift_overtime_is_not_removed_by_the_hour_band_alone() -> None:
    """09:00-13:00 shift, standard bands. Two hours beyond the shift earned nothing before engine
    16. With P-05 the 4-hour shift worked in full is a full day (the bands scale to the shift),
    so the overtime is no longer held back by a half-day verdict at all."""
    short = dict(
        shift=_shift(is_ot_eligible=True), scheduled_end=datetime(2026, 8, 10, 13, tzinfo=UTC)
    )
    worked_over = _day([(9, 0, "IN"), (15, 0, "OUT")], **short)
    assert worked_over.attendance_status == "PRESENT"  # P-05: 6 hours on a 4-hour shift
    assert worked_over.ot_minutes_detected == 120
    on_time = _day([(9, 0, "IN"), (13, 0, "OUT")], **short)
    assert on_time.ot_minutes_detected == 0


def test_a_half_day_by_lateness_still_pays_no_overtime() -> None:
    result = _day([(10, 30, "IN"), (21, 0, "OUT")], late_bands=_LATE_BANDS)
    assert result.attendance_status == "HALF_DAY"
    assert result.ot_minutes_detected == 0


# --- AR-13: half-day weekly off ----------------------------------------------------------------


def _half_off(punches: list[tuple[Any, ...]], **overrides: Any) -> AttendanceCalculationResult:
    return _day(
        punches,
        calendar_day_type="WEEKLY_OFF",
        weekly_off_fraction="0.50",
        late_bands=_LATE_BANDS,
        early_bands=_EARLY_BANDS,
        **overrides,
    )


@pytest.mark.parametrize(
    "punches", [[(14, 0, "IN"), (18, 0, "OUT")], [(9, 0, "IN"), (13, 0, "OUT")]]
)
def test_working_either_half_of_a_half_weekly_off_is_not_late_or_early(
    punches: list[tuple[Any, ...]],
) -> None:
    """Working the afternoon recorded 290 late minutes and a late day before engine 16."""
    result = _half_off(punches)
    assert (result.late_minutes, result.early_departure_minutes) == (0, 0)
    assert result.is_late is False and result.is_early_out is False
    assert result.attendance_status == "PRESENT"
    assert _pay(result) == ("1.00", "0.00")


def test_two_hours_on_a_half_weekly_off_loses_the_working_half() -> None:
    """Was PRESENT, 1.00 paid: the early band softened the absent hour band (AR-05)."""
    result = _half_off([(9, 0, "IN"), (11, 0, "OUT")])
    assert _pay(result) == ("0.50", "0.50")


# --- AR-14: split shift, missing punch ---------------------------------------------------------


def test_split_shift_forgotten_out_is_incomplete_not_a_half_day() -> None:
    """09-13 worked, IN at 17:00 with no OUT: HALF_DAY (0.50 LOP) with no review before."""
    result = _split_day([(9, 0, "IN"), (13, 0, "OUT"), (17, 0, "IN")])
    assert result.missing_punch is True
    assert result.attendance_status == "INCOMPLETE"
    assert _pay(result) == ("0.00", "0.00")


def test_split_shift_block_missed_with_no_orphan_punch_is_still_a_half_day() -> None:
    result = _split_day([(9, 0, "IN"), (13, 0, "OUT")])
    assert result.missing_punch is False
    assert result.attendance_status == "HALF_DAY"


def test_split_shift_auto_close_policy_keeps_the_missed_block_rule() -> None:
    """Only a policy that sends a missing punch for review (`INCOMPLETE`) does so here."""
    result = _split_day(
        [(9, 0, "IN"), (13, 0, "OUT"), (17, 0, "IN")],
        policy=_policy(missing_punch_behaviour="AUTO_CLOSE"),
    )
    assert result.attendance_status == "HALF_DAY"


# --- overnight shift and Asia/Kolkata ---------------------------------------------------------


def test_overnight_shift_half_day_leave_uses_the_half_after_midnight() -> None:
    """22:00-06:00, first half (22:00-02:00) on leave; worked 02:00-08:00 the next morning."""
    result = _day(
        [(1, 30, "IN", 11), (8, 0, "OUT", 11)],
        shift=_shift(is_ot_eligible=True, is_cross_midnight=True),
        scheduled_start=datetime(2026, 8, 10, 22, 0, tzinfo=UTC),
        scheduled_end=datetime(2026, 8, 11, 6, 0, tzinfo=UTC),
        leave_entries=_leave("FIRST"),
    )
    assert result.work_on_leave_flagged is False
    assert result.worked_minutes == 360  # credited from 02:00, not from the 01:30 arrival
    assert result.ot_minutes_detected == 120
    assert _pay(result) == ("1.00", "0.00")


def test_half_day_leave_halves_are_the_same_in_india_time() -> None:
    """09:00-18:00 IST is 03:30-12:30 UTC; lunch 13:00-14:00 IST. First-half leave, arrival at
    13:10 IST (early), out 20:00 IST: two hours of overtime, no conflict."""
    ist_start = datetime(2026, 8, 10, 3, 30, tzinfo=UTC)
    result = _day(
        [(7, 40, "IN"), (14, 30, "OUT")],
        timezone="Asia/Kolkata",
        scheduled_start=ist_start,
        scheduled_end=datetime(2026, 8, 10, 12, 30, tzinfo=UTC),
        leave_entries=_leave("FIRST"),
    )
    assert result.work_on_leave_flagged is False
    assert result.worked_minutes == 360
    assert result.ot_minutes_detected == 120


# --- invariants --------------------------------------------------------------------------------

_SCENARIOS: list[dict[str, Any]] = [
    dict(punches=[(9, 0, "IN"), (18, 0, "OUT")]),
    dict(punches=[(9, 11, "IN"), (18, 0, "OUT")], late_bands=_LATE_BANDS),
    dict(punches=[(9, 0, "IN"), (11, 0, "OUT")], early_bands=_EARLY_BANDS),
    dict(punches=[(14, 11, "IN"), (18, 0, "OUT")], leave_entries=_leave("FIRST")),
    dict(punches=[(12, 40, "IN"), (20, 0, "OUT")], leave_entries=_leave("FIRST")),
    dict(punches=[(9, 0, "IN"), (21, 0, "OUT")], leave_entries=_leave("SECOND")),
    dict(
        punches=[(9, 0, "IN"), (11, 0, "OUT")],
        calendar_day_type="WEEKLY_OFF",
        weekly_off_fraction="0.50",
    ),
    dict(punches=[], leave_entries=_leave("FIRST", paid=False)),
]


@pytest.mark.parametrize("scenario", _SCENARIOS)
def test_fractions_reconcile_and_repeat_calculation_is_identical(scenario: dict[str, Any]) -> None:
    kwargs = dict(scenario)
    punches = kwargs.pop("punches")
    first = _day(punches, **kwargs)
    second = _day(punches, **kwargs)
    assert replace(first, snapshot={}) == replace(second, snapshot={})
    total = (
        Decimal(first.paid_day_fraction)
        + Decimal(first.lop_fraction)
        + Decimal(first.unpaid_off_fraction)
    )
    if first.attendance_status == "INCOMPLETE":
        # H-07: a pending worked half (no punch yet, or an incomplete one) is decided at the lock;
        # until then only the settled parts are on the row and the leave half is exactly as leave
        assert total == Decimal(first.leave_fraction) < Decimal("1.00")
    else:
        assert total == Decimal("1.00")
    assert first.ot_minutes_approved <= first.ot_minutes_detected <= first.worked_minutes
