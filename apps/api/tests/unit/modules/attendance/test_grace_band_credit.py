"""N-02 - grace minutes credit the hour-band lookup only (engine 14).

Before: grace forgave lateness but added no worked minutes, so on an 8-hour net shift an arrival
inside grace (09:05 on 09:00-18:00 with an unpaid hour, 09:08 on 09:00-17:00) fell under the
480-minute full-day band and cost a half day. Now the forgiven minutes count toward the band, and
nothing else: worked minutes, overtime, late and early minutes are exactly what they were.
Baseline = the web app's "Standard office" template (grace 10/10, 480 full, 240 half).
"""

from datetime import UTC, date, datetime, time, timedelta
from uuid import uuid4

import pytest

from hrms.modules.attendance import calculation as c

D = date(2026, 8, 10)  # a Monday; every time is UTC so the arithmetic reads directly
IN, OUT = "IN", "OUT"


def at(hour: int, minute: int = 0, day: int = 0) -> datetime:
    return datetime.combine(D + timedelta(days=day), time(hour, minute), tzinfo=UTC)


def punch(hour: int, minute: int, direction: str, day: int = 0) -> c.PunchData:
    return c.PunchData(uuid4(), at(hour, minute, day), direction)


def policy(**kw: object) -> c.PolicyInputs:
    base: dict[str, object] = dict(
        grace_in_minutes=10,
        grace_out_minutes=10,
        punch_rounding="NONE",
        rounding_minutes=None,
        missing_punch_behaviour="INCOMPLETE",
        missing_shift_behaviour="INCOMPLETE",
        half_day_split="NONE",
        half_day_boundary_minutes=None,
        multi_punch_mode="PAIR_ALL",
        duplicate_punch_window_seconds=120,
        core_hours_breach_behaviour="FLAG",
        early_out_uses_core_end=False,
        split_shift_missed_block_behaviour="IGNORE",
        excess_break_behaviour="IGNORE",
        incomplete_at_lock_behaviour="TREAT_ABSENT",
        work_on_leave_behaviour="KEEP_PUNCH_STATUS",
    )
    base.update(kw)
    return c.PolicyInputs(**base)  # type: ignore[arg-type]


HOURS = [
    c.BandData(0, 239, "ABSENT"),
    c.BandData(240, 479, "HALF_DAY"),
    c.BandData(480, None, "PRESENT"),
]
OT = c.OvertimePolicyInputs(
    eligibility="SHIFT_FLAG",
    min_ot_minutes=30,
    rounding_minutes=None,
    rounding_mode="NONE",
    requires_post_approval=False,
    daily_cap_minutes=None,
    comp_off_instead_of_pay=False,
    night_ot_mode="SHIFT_FLAG",
    night_window_start=None,
    night_window_end=None,
)


def lunch() -> c.ShiftBreakData:
    return c.ShiftBreakData(
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
        name="Lunch",
        mode="AUTO_DEDUCT",
        scheduled_minutes=60,
    )


def day(
    punches: list[c.PunchData],
    *,
    start: tuple[int, int] = (9, 0),
    end: tuple[int, int] = (18, 0),
    breaks: list[c.ShiftBreakData] | None = None,
    **kw: object,
) -> c.AttendanceCalculationResult:
    shift = c.ShiftInputs("FIXED", True, False, False, False, breaks or [])
    inp: dict[str, object] = dict(
        employee_id=uuid4(),
        attendance_date=D,
        timezone="UTC",
        population_status="ACTIVE",
        calendar_day_type="WORKING",
        holiday_name=None,
        holiday_on_weekly_off=False,
        shift=shift,
        scheduled_start=at(*start),
        scheduled_end=at(*end),
        policy=policy(),
        hour_bands=HOURS,
        ot_policy=OT,
        punches=punches,
    )
    inp.update(kw)
    return c.evaluate_day(c.AttendanceCalculationInput(**inp))  # type: ignore[arg-type]


# --- the cases from the scenario map ----------------------------------------------------------


def test_arrival_inside_grace_on_a_net_eight_hour_shift_is_a_full_day() -> None:
    """BRK-08: 09:00-18:00 with an unpaid hour, IN 09:05. Worked 475, credited 480."""
    r = day([punch(9, 5, IN), punch(18, 0, OUT)], breaks=[lunch()])
    assert r.attendance_status == "PRESENT"
    assert (r.paid_day_fraction, r.lop_fraction) == ("1.00", "0.00")
    assert r.worked_minutes == 475  # unchanged
    assert r.late_minutes == 0


def test_departure_inside_grace_out_is_a_full_day() -> None:
    r = day([punch(9, 0, IN), punch(17, 55, OUT)], breaks=[lunch()])
    assert r.attendance_status == "PRESENT"
    assert r.worked_minutes == 475
    assert r.early_departure_minutes == 0


def test_eight_hour_shift_without_a_break_arrival_inside_grace_is_a_full_day() -> None:
    """BRK-09: 09:00-17:00, IN 09:08. Worked 472, credited 480."""
    r = day([punch(9, 8, IN), punch(17, 0, OUT)], start=(9, 0), end=(17, 0))
    assert r.attendance_status == "PRESENT"
    assert r.worked_minutes == 472
    assert r.late_minutes == 0


def test_late_and_early_inside_grace_both_credit_the_band() -> None:
    r = day([punch(9, 8, IN), punch(16, 52, OUT)], start=(9, 0), end=(17, 0))
    assert r.attendance_status == "PRESENT"
    assert r.worked_minutes == 464


def test_night_shift_late_within_grace_is_a_full_day() -> None:
    """NGT-03 family: 22:00-06:00 (480), IN 22:07."""
    shift = c.ShiftInputs("FIXED", True, False, False, True, [], True)
    r = day(
        [punch(22, 7, IN), punch(6, 0, OUT, day=1)],
        start=(22, 0),
        end=(6, 0),
        shift=shift,
        scheduled_end=at(6, 0, day=1),
    )
    assert r.attendance_status == "PRESENT"
    assert r.worked_minutes == 473


# --- the credit is limited -------------------------------------------------------------------


def test_only_the_grace_is_credited_not_the_whole_lateness() -> None:
    """IN 09:40 on 09:00-17:00: 40 minutes missed, grace 10, so 10 are credited: 440+10 < 480."""
    r = day([punch(9, 40, IN), punch(17, 0, OUT)], start=(9, 0), end=(17, 0))
    assert r.attendance_status == "HALF_DAY"
    assert r.worked_minutes == 440
    assert r.late_minutes == 30


def test_one_minute_past_grace_still_costs_the_half_day_on_a_tight_shift() -> None:
    """09:11 on 09:00-17:00: late 1 minute; 469 worked + 10 credited = 479: still under 480."""
    r = day([punch(9, 11, IN), punch(17, 0, OUT)], start=(9, 0), end=(17, 0))
    assert r.attendance_status == "HALF_DAY"
    assert r.late_minutes == 1
    assert r.worked_minutes == 469


def test_credit_never_exceeds_the_net_scheduled_minutes() -> None:
    """A 7-hour shift (420 net) with bands that need 430: the credit cannot lift 415 past 420."""
    bands = [c.BandData(0, 429, "HALF_DAY"), c.BandData(430, None, "PRESENT")]
    r = day(
        [punch(9, 5, IN), punch(16, 0, OUT)],
        start=(9, 0),
        end=(16, 0),
        hour_bands=bands,
    )
    assert r.worked_minutes == 415
    assert r.attendance_status == "HALF_DAY"
    assert r.snapshot["grace_band_credit"]["band_minutes"] == 420


def test_credit_is_zero_when_nothing_was_missed_at_that_end() -> None:
    r = day([punch(8, 55, IN), punch(18, 5, OUT)])
    credit = r.snapshot["grace_band_credit"]
    assert (credit["in"], credit["out"]) == (0, 0)


def test_a_real_short_day_is_not_rescued_by_grace() -> None:
    r = day([punch(9, 0, IN), punch(13, 0, OUT)])
    assert r.attendance_status == "HALF_DAY"


def test_a_missing_punch_day_gets_no_credit_and_stays_incomplete() -> None:
    r = day([punch(9, 5, IN)])
    assert r.attendance_status == "INCOMPLETE"
    assert r.snapshot["grace_band_credit"] == {
        "in": 0,
        "out": 0,
        "band_minutes": 0,
        "worked_minutes": 0,
    }


# --- nothing else moves -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("in_", "out"),
    [
        ((9, 5), (18, 0)),
        ((9, 0), (17, 55)),
        ((9, 40), (18, 0)),
        ((9, 11), (17, 30)),
        ((9, 0), (19, 30)),
    ],
)
def test_worked_overtime_late_and_early_are_the_raw_figures(
    in_: tuple[int, int], out: tuple[int, int]
) -> None:
    """The credit changes the band lookup only: worked/late/early/overtime equal what they would be
    with no credit at all (computed here from first principles)."""
    r = day([punch(*in_, IN), punch(*out, OUT)], breaks=[lunch()])
    worked = (out[0] * 60 + out[1]) - (in_[0] * 60 + in_[1]) - 60
    assert r.worked_minutes == worked
    assert r.late_minutes == max(0, (in_[0] * 60 + in_[1]) - 9 * 60 - 10)
    assert r.early_departure_minutes == max(0, 18 * 60 - (out[0] * 60 + out[1]) - 10)
    assert r.ot_minutes_detected == (worked - 480 if worked - 480 >= 30 else 0)


def test_overtime_is_measured_on_real_minutes_not_credited_ones() -> None:
    """Out 18:35: 515 worked vs 480 net: 35 minutes of overtime; no grace is added to it."""
    r = day([punch(9, 0, IN), punch(18, 35, OUT)], breaks=[lunch()])
    assert r.worked_minutes == 515
    assert r.ot_minutes_detected == 35


def test_is_late_flag_and_cumulative_counting_still_use_the_raw_late() -> None:
    """Inside grace: not late, so no cumulative count. Past grace: late, so it counts."""
    pol = policy(lates_to_half_day_count=3)
    inside = day(
        [punch(9, 5, IN), punch(18, 0, OUT)],
        breaks=[lunch()],
        policy=pol,
        prior_late_days_in_window=2,
    )
    assert inside.is_late is False
    assert inside.attendance_status == "PRESENT"
    past = day(
        [punch(9, 20, IN), punch(18, 0, OUT)],
        breaks=[lunch()],
        policy=pol,
        prior_late_days_in_window=2,
    )
    assert past.is_late is True
    assert past.attendance_status == "HALF_DAY"  # the 3rd late day


def test_late_band_classification_is_unchanged() -> None:
    bands = [c.BandData(1, 29, "NONE"), c.BandData(30, None, "HALF_DAY")]
    r = day([punch(9, 45, IN), punch(18, 0, OUT)], late_bands=bands)  # 35 late
    assert r.late_minutes == 35
    assert r.late_classification == "HALF_DAY"
    assert r.attendance_status == "HALF_DAY"


def test_early_departure_approval_rule_is_unchanged() -> None:
    r = day(
        [punch(9, 0, IN), punch(17, 0, OUT)],
        policy=policy(early_departure_requires_approval=True),
        early_bands=[c.BandData(1, None, "HALF_DAY")],
    )
    assert r.attendance_status == "HALF_DAY"
    assert r.early_departure_minutes == 50


# --- other shift kinds and overlays ----------------------------------------------------------


def test_flexible_shift_credits_grace_after_the_start_window() -> None:
    """Window 09:00-10:00, 8 h required. IN 10:05 (inside grace after the window), 8 h less 5."""
    shift = c.ShiftInputs("FLEXIBLE", True, False, False, False, [], required_minutes=480)
    r = day([punch(10, 5, IN), punch(18, 0, OUT)], start=(9, 0), end=(10, 0), shift=shift)
    assert r.worked_minutes == 475
    assert r.late_minutes == 0
    assert r.attendance_status == "PRESENT"


def test_split_shift_credits_grace_at_the_outer_edges_only() -> None:
    blocks = [
        c.ShiftDutyBlockData(1, time(7, 0), time(11, 0), False),
        c.ShiftDutyBlockData(2, time(16, 0), time(20, 0), False),
    ]
    shift = c.ShiftInputs("SPLIT", True, False, False, False, [], duty_blocks=blocks)
    r = day(
        [punch(7, 6, IN), punch(11, 0, OUT), punch(16, 0, IN), punch(20, 0, OUT)],
        start=(7, 0),
        end=(20, 0),
        shift=shift,
    )
    assert r.worked_minutes == 474
    assert r.attendance_status == "PRESENT"
    assert r.late_minutes == 0


def test_split_shift_inner_gaps_get_no_credit() -> None:
    blocks = [
        c.ShiftDutyBlockData(1, time(7, 0), time(11, 0), False),
        c.ShiftDutyBlockData(2, time(16, 0), time(20, 0), False),
    ]
    shift = c.ShiftInputs("SPLIT", True, False, False, False, [], duty_blocks=blocks)
    r = day(
        [punch(7, 0, IN), punch(10, 40, OUT), punch(16, 0, IN), punch(20, 0, OUT)],
        start=(7, 0),
        end=(20, 0),
        shift=shift,
    )
    assert r.worked_minutes == 460  # leaving the first block 20 minutes early earns no credit
    assert r.attendance_status == "HALF_DAY"


def test_half_day_leave_keeps_judging_the_worked_half_alone() -> None:
    """09:00-17:00, first-half leave: the worked half is 13:00-17:00 (240 min), judged x2 against
    the 480 band. IN 13:05 (inside grace) leaves 235 worked: before N-02 that doubled to 470 and
    the worked half was lost to LOP; now 235 + 5 credited = 240, so the worked half counts."""
    leave = [c.LeaveOverlayEntry("0.50", True, "FIRST")]
    r = day([punch(13, 5, IN), punch(17, 0, OUT)], start=(9, 0), end=(17, 0), leave_entries=leave)
    assert r.worked_minutes == 235
    assert r.late_minutes == 0
    assert r.attendance_status == "HALF_DAY"
    assert (r.paid_day_fraction, r.lop_fraction) == ("1.00", "0.00")


def test_half_day_leave_worked_half_still_lost_when_it_is_really_short() -> None:
    leave = [c.LeaveOverlayEntry("0.50", True, "FIRST")]
    r = day([punch(13, 0, IN), punch(15, 0, OUT)], start=(9, 0), end=(17, 0), leave_entries=leave)
    assert r.attendance_status == "LEAVE"
    assert (r.paid_day_fraction, r.lop_fraction) == ("0.50", "0.50")


def test_day_off_work_has_no_credit_and_is_unchanged() -> None:
    r = day([punch(9, 5, IN), punch(18, 0, OUT)], calendar_day_type="WEEKLY_OFF")
    assert r.snapshot["grace_band_credit"]["in"] == 0
    assert r.snapshot["grace_band_credit"]["out"] == 0
    assert r.attendance_status == "PRESENT"


def test_engine_version_records_the_change() -> None:
    assert c.ENGINE_VERSION >= 14
    r = day([punch(9, 0, IN), punch(18, 0, OUT)])
    assert r.snapshot["engine_version"] == c.ENGINE_VERSION
