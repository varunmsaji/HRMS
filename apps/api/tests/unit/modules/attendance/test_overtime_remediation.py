"""AC-05, AC-06, P-A, P-B (attendance + calendar + overtime audit, 16 Nov 2026). No DB/HTTP.

Shift 09:00-18:00 UTC with an unpaid 13:00-14:00 lunch (net 480; halves 09-13 = 240 and
14-18 = 240), overtime always on, auto-approved."""

from dataclasses import replace
from datetime import UTC, datetime, time
from typing import Any
from uuid import uuid4

from tests.unit.modules.attendance.test_calculation import _base_input, _policy, _punch, _shift
from tests.unit.modules.attendance.test_night_ot import _policy as _ot_policy

from hrms.modules.attendance.calculation import (
    AttendanceCalculationResult,
    BandData,
    LeaveOverlayEntry,
    ShiftBreakData,
    evaluate_day,
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
    BandData(min_minutes=240, max_minutes=419, classification="HALF_DAY"),
    BandData(min_minutes=420, max_minutes=None, classification="PRESENT"),
]
_LATE_BANDS = [
    BandData(min_minutes=1, max_minutes=59, classification="LATE"),
    BandData(min_minutes=60, max_minutes=None, classification="HALF_DAY"),
]


def _day(punches: list[tuple[int, int, str]], **overrides: Any) -> AttendanceCalculationResult:
    inputs: dict[str, Any] = dict(
        shift=_shift(is_ot_eligible=True, breaks=[_LUNCH]),
        policy=_policy(grace_in_minutes=10, grace_out_minutes=10),
        timezone="UTC",
        scheduled_start=datetime(2026, 8, 10, 9, 0, tzinfo=UTC),
        scheduled_end=datetime(2026, 8, 10, 18, 0, tzinfo=UTC),
        ot_policy=_ot_policy("NONE"),
        hour_bands=_HOUR_BANDS,
        late_bands=_LATE_BANDS,
        punches=[_punch(h, m, d, day=10) for h, m, d in punches],
    )
    inputs.update(overrides)
    return evaluate_day(_base_input(**inputs))


def _leave(half: str) -> list[LeaveOverlayEntry]:
    return [LeaveOverlayEntry(fraction="0.50", is_paid=True, half=half)]


# --- AC-05: half-day leave --------------------------------------------------------------------


def test_first_half_leave_working_the_afternoon_and_beyond_earns_overtime() -> None:
    # 14:00-22:00 = 480 worked against the second half's net 240.
    result = _day([(14, 0, "IN"), (22, 0, "OUT")], leave_entries=_leave("FIRST"))
    assert result.ot_minutes_detected == 240
    assert result.work_on_leave_flagged is False


def test_second_half_leave_working_only_the_morning_earns_none() -> None:
    result = _day([(9, 0, "IN"), (13, 0, "OUT")], leave_entries=_leave("SECOND"))
    assert result.ot_minutes_detected == 0
    assert result.work_on_leave_flagged is False


def test_second_half_leave_but_worked_the_afternoon_is_flagged_and_earns_no_overtime() -> None:
    # 09:00-21:00 spans the leave half: the same hours would be paid as leave and as overtime.
    result = _day([(9, 0, "IN"), (21, 0, "OUT")], leave_entries=_leave("SECOND"))
    assert result.work_on_leave_flagged is True
    assert result.ot_minutes_detected == 0
    assert result.ot_minutes_approved == 0


def test_a_short_overstay_into_the_leave_half_is_not_a_conflict_and_is_not_credited() -> None:
    """AR-07 (engine 16): staying a little past the worked half is not work on leave. The time
    in the leave half is not credited, so nothing is paid twice. Before, 15 minutes over the
    grace flagged the day and blocked period close."""
    result = _day([(9, 0, "IN"), (14, 15, "OUT")], leave_entries=_leave("SECOND"))
    assert result.work_on_leave_flagged is False
    assert result.worked_minutes == 240
    assert result.ot_minutes_detected == 0


def test_no_punches_on_a_half_day_leave_has_no_flag_and_no_overtime() -> None:
    result = _day([], leave_entries=_leave("FIRST"))
    assert result.work_on_leave_flagged is False
    assert result.ot_minutes_detected == 0


def test_unequal_halves_use_each_halfs_own_net_minutes() -> None:
    lunch = replace(_LUNCH, start_time=time(11, 0), end_time=time(12, 0))
    inputs = _base_input(
        shift=_shift(is_ot_eligible=True, breaks=[lunch]),
        policy=_policy(),
        timezone="UTC",
        scheduled_start=datetime(2026, 8, 10, 9, 0, tzinfo=UTC),
        scheduled_end=datetime(2026, 8, 10, 18, 0, tzinfo=UTC),
        leave_entries=_leave("FIRST"),
    )
    from hrms.modules.attendance.calculation import scheduled_half_net_minutes

    # Lunch 11-12 contains the 13:30 midpoint? No: the midpoint is outside it, so the halves are
    # 09:00-13:30 (270 gross, 60 lunch -> 210) and 13:30-18:00 (270).
    assert scheduled_half_net_minutes(inputs, "FIRST") == 210
    assert scheduled_half_net_minutes(inputs, "SECOND") == 270


# --- AC-06: roster week-off --------------------------------------------------------------------


def test_roster_week_off_work_is_priced_as_weekly_off() -> None:
    rows = _ot_policy("NONE")
    result = _day([(9, 0, "IN"), (18, 0, "OUT")], ot_policy=rows, roster_week_off_override=True)
    assert result.ot_day_class == "WEEKLY_OFF"
    assert result.worked_on_weekly_off is True


def test_calendar_weekly_off_and_roster_week_off_agree() -> None:
    calendar = _day([(9, 0, "IN"), (18, 0, "OUT")], calendar_day_type="WEEKLY_OFF")
    roster = _day([(9, 0, "IN"), (18, 0, "OUT")], roster_week_off_override=True)
    assert calendar.ot_day_class == roster.ot_day_class == "WEEKLY_OFF"
    assert calendar.ot_minutes_detected == roster.ot_minutes_detected


def test_roster_week_off_on_a_working_day_without_punches_is_just_a_day_off() -> None:
    result = _day([], roster_week_off_override=True)
    assert result.attendance_status == "NOT_EXPECTED"
    assert result.ot_minutes_detected == 0


def test_rostered_work_on_a_holiday_is_an_ordinary_working_day() -> None:
    result = _day(
        [(9, 0, "IN"), (20, 0, "OUT")],
        calendar_day_type="HOLIDAY",
        roster_holiday_working_override=True,
    )
    assert result.ot_day_class == "NORMAL"


# --- P-A / P-B ---------------------------------------------------------------------------------


def test_half_weekly_off_overtime_starts_after_the_working_half() -> None:
    result = _day(
        [(9, 0, "IN"), (22, 0, "OUT")], calendar_day_type="WEEKLY_OFF", weekly_off_fraction="0.50"
    )
    # 13h - 1h lunch = 720 worked against the longer half's 240 net.
    assert result.ot_minutes_detected == 720 - 240


def test_a_half_day_penalised_by_lateness_pays_no_overtime() -> None:
    # 80 minutes late = HALF_DAY late band; staying until 21:00 would otherwise earn overtime.
    result = _day([(10, 20, "IN"), (21, 0, "OUT")])
    assert result.attendance_status == "HALF_DAY"
    assert result.ot_minutes_detected == 0
    assert result.ot_day_class is None


def test_a_band_longer_than_the_shift_cannot_make_a_long_day_absent() -> None:
    """Before P-05, bands needing 1,000 minutes made a 12-hour day on an 8-hour shift ABSENT by
    configuration (and an absent day pays no overtime). With P-05 the bands scale down to the
    shift's own net minutes, so a day worked well past the shift is PRESENT and earns overtime:
    an ABSENT-by-hours day can no longer coexist with worked time beyond the schedule."""
    bands = [
        BandData(min_minutes=0, max_minutes=999, classification="ABSENT"),
        BandData(min_minutes=1000, max_minutes=None, classification="PRESENT"),
    ]
    result = _day([(9, 0, "IN"), (21, 0, "OUT")], hour_bands=bands)
    assert result.attendance_status == "PRESENT"
    assert result.ot_minutes_detected > 0


def test_a_normal_present_day_still_earns_overtime() -> None:
    result = _day([(9, 0, "IN"), (20, 0, "OUT")])
    assert result.attendance_status == "PRESENT"
    assert result.ot_minutes_detected == 120
