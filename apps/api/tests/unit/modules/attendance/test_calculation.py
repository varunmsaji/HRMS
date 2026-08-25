"""Unit tests for the W4 calculation engine (`attendance/calculation.py`) — no DB/HTTP.

Covers the documented punch-pairing sequences from the W4 task brief (IN->OUT, IN->OUT->IN->OUT,
IN->IN->OUT, IN->OUT->OUT), duplicate collapsing, timezone resolution, cross-midnight window
computation, break matching, band lookup, and the terminal-status short-circuits."""

from datetime import UTC, date, datetime, time, timedelta
from uuid import uuid4

from hrms.modules.attendance.calculation import (
    AttendanceCalculationInput,
    BandData,
    OvertimePolicyInputs,
    PolicyInputs,
    PunchData,
    ShiftBreakData,
    ShiftDutyBlockData,
    ShiftInputs,
    calendar_day_window_utc,
    classify_ot_day,
    collapse_duplicate_punches,
    detect_overtime,
    evaluate_day,
    lookup_band,
    pair_punches,
    presence_span,
    resolve_timezone,
    round_minutes,
    scheduled_span_utc,
)


def _punch(hour: int, minute: int, direction: str, day: int = 1) -> PunchData:
    return PunchData(
        id=uuid4(),
        punch_time=datetime(2026, 8, day, hour, minute, tzinfo=UTC),
        direction=direction,
    )


def _policy(**overrides: object) -> PolicyInputs:
    defaults: dict[str, object] = dict(
        grace_in_minutes=10,
        grace_out_minutes=10,
        punch_rounding="NONE",
        rounding_minutes=None,
        missing_punch_behaviour="INCOMPLETE",
        missing_shift_behaviour="INCOMPLETE",
        half_day_split="BY_HOURS",
        half_day_boundary_minutes=None,
        multi_punch_mode="PAIR_ALL",
        duplicate_punch_window_seconds=60,
        core_hours_breach_behaviour="FLAG",
        early_out_uses_core_end=False,
        split_shift_missed_block_behaviour="HALF_DAY",
        excess_break_behaviour="FLAG",
        incomplete_at_lock_behaviour="TREAT_ABSENT",
        work_on_leave_behaviour="KEEP_LEAVE",
    )
    defaults.update(overrides)
    return PolicyInputs(**defaults)  # type: ignore[arg-type]


def _shift(**overrides: object) -> ShiftInputs:
    defaults: dict[str, object] = dict(
        shift_type="FIXED",
        is_ot_eligible=False,
        operates_on_holiday=False,
        operates_on_weekly_off=False,
        is_cross_midnight=False,
        breaks=[],
        duty_blocks=[],
    )
    defaults.update(overrides)
    return ShiftInputs(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Timezone (WD-06)
# ---------------------------------------------------------------------------


def test_resolve_timezone_prefers_shift_version() -> None:
    assert (
        resolve_timezone(
            shift_version_timezone="America/New_York",
            branch_timezone="Asia/Kolkata",
            company_timezone="UTC",
        )
        == "America/New_York"
    )


def test_resolve_timezone_falls_back_to_branch_then_company() -> None:
    assert (
        resolve_timezone(
            shift_version_timezone=None, branch_timezone="Europe/London", company_timezone="UTC"
        )
        == "Europe/London"
    )
    assert (
        resolve_timezone(
            shift_version_timezone=None, branch_timezone=None, company_timezone="Asia/Kolkata"
        )
        == "Asia/Kolkata"
    )


# ---------------------------------------------------------------------------
# Cross-midnight schedule window (FR-ATT-005)
# ---------------------------------------------------------------------------


def test_scheduled_span_cross_midnight_attributes_to_start_date() -> None:
    start, end = scheduled_span_utc(
        attendance_date=date(2026, 8, 10),
        tz_name="Asia/Kolkata",
        start_time=time(22, 0),
        end_time=time(6, 0),
        is_cross_midnight=True,
    )
    assert start.date() == date(2026, 8, 10)
    assert end.date() == date(2026, 8, 11)
    assert (end - start) == timedelta(hours=8)


def test_calendar_day_window_is_plain_local_midnight_to_midnight() -> None:
    start, end = calendar_day_window_utc(attendance_date=date(2026, 8, 10), tz_name="UTC")
    assert start == datetime(2026, 8, 10, tzinfo=UTC)
    assert end == datetime(2026, 8, 11, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Duplicate collapsing (§19.1 step 9, FR-ATT-017)
# ---------------------------------------------------------------------------


def test_collapse_duplicate_punches_within_window() -> None:
    p1 = _punch(9, 0, "IN")
    p2 = PunchData(id=uuid4(), punch_time=p1.punch_time + timedelta(seconds=30), direction="IN")
    p3 = _punch(18, 0, "OUT")
    collapsed = collapse_duplicate_punches([p1, p2, p3], window_seconds=60)
    assert collapsed == [p1, p3]


def test_collapse_duplicate_punches_outside_window_kept() -> None:
    p1 = _punch(9, 0, "IN")
    p2 = PunchData(id=uuid4(), punch_time=p1.punch_time + timedelta(seconds=120), direction="IN")
    collapsed = collapse_duplicate_punches([p1, p2], window_seconds=60)
    assert collapsed == [p1, p2]


# ---------------------------------------------------------------------------
# Punch pairing — the four documented sequences
# ---------------------------------------------------------------------------


def test_pairing_in_out() -> None:
    p_in, p_out = _punch(9, 0, "IN"), _punch(18, 0, "OUT")
    result = pair_punches([p_in, p_out])
    assert result.pairs == [(p_in, p_out)]
    assert result.orphans == []


def test_pairing_in_out_in_out() -> None:
    a_in, a_out = _punch(9, 0, "IN"), _punch(13, 0, "OUT")
    b_in, b_out = _punch(14, 0, "IN"), _punch(18, 0, "OUT")
    result = pair_punches([a_in, a_out, b_in, b_out])
    assert result.pairs == [(a_in, a_out), (b_in, b_out)]
    assert result.orphans == []


def test_pairing_in_in_out_orphans_the_earlier_in() -> None:
    first_in, second_in, out = _punch(9, 0, "IN"), _punch(9, 30, "IN"), _punch(18, 0, "OUT")
    result = pair_punches([first_in, second_in, out])
    assert result.pairs == [(second_in, out)]
    assert result.orphans == [first_in]


def test_pairing_in_out_out_orphans_the_second_out() -> None:
    p_in, first_out, second_out = _punch(9, 0, "IN"), _punch(13, 0, "OUT"), _punch(18, 0, "OUT")
    result = pair_punches([p_in, first_out, second_out])
    assert result.pairs == [(p_in, first_out)]
    assert result.orphans == [second_out]


def test_pairing_trailing_unmatched_in_is_orphan() -> None:
    p_in = _punch(9, 0, "IN")
    result = pair_punches([p_in])
    assert result.pairs == []
    assert result.orphans == [p_in]


# ---------------------------------------------------------------------------
# Presence span — PAIR_ALL vs FIRST_IN_LAST_OUT
# ---------------------------------------------------------------------------


def test_presence_span_pair_all_excludes_gap() -> None:
    a_in, a_out = _punch(9, 0, "IN"), _punch(12, 0, "OUT")
    b_in, b_out = _punch(13, 0, "IN"), _punch(17, 0, "OUT")
    pairing = pair_punches([a_in, a_out, b_in, b_out])
    first_in, last_out, gross, gaps = presence_span(pairing.pairs, mode="PAIR_ALL")
    assert gross == 7 * 60  # 3h + 4h, the 1h gap excluded
    assert gaps == [(a_out.punch_time, b_in.punch_time)]
    assert first_in == a_in.punch_time
    assert last_out == b_out.punch_time


def test_presence_span_first_in_last_out_includes_gap() -> None:
    a_in, a_out = _punch(9, 0, "IN"), _punch(12, 0, "OUT")
    b_in, b_out = _punch(13, 0, "IN"), _punch(17, 0, "OUT")
    pairing = pair_punches([a_in, a_out, b_in, b_out])
    _first_in, _last_out, gross, _gaps = presence_span(pairing.pairs, mode="FIRST_IN_LAST_OUT")
    assert gross == 8 * 60  # full 9:00-17:00 span, gap included


# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------


def test_round_minutes_up_down_nearest() -> None:
    assert round_minutes(52, mode="UP", minutes=15) == 60
    assert round_minutes(52, mode="DOWN", minutes=15) == 45
    assert round_minutes(52, mode="NEAREST", minutes=15) == 45
    assert round_minutes(53, mode="NEAREST", minutes=15) == 60
    assert round_minutes(52, mode="NONE", minutes=15) == 52


# ---------------------------------------------------------------------------
# Band lookup
# ---------------------------------------------------------------------------


def test_lookup_band_matches_ordered_ranges() -> None:
    bands = [
        BandData(min_minutes=0, max_minutes=239, classification="ABSENT"),
        BandData(min_minutes=240, max_minutes=479, classification="HALF_DAY"),
        BandData(min_minutes=480, max_minutes=None, classification="PRESENT"),
    ]
    assert lookup_band(0, bands) == "ABSENT"
    assert lookup_band(300, bands) == "HALF_DAY"
    assert lookup_band(500, bands) == "PRESENT"


def test_lookup_band_no_match_returns_none() -> None:
    assert lookup_band(10, []) is None


# ---------------------------------------------------------------------------
# Overtime detection (§12)
# ---------------------------------------------------------------------------


def test_detect_overtime_ineligible_shift_flag() -> None:
    policy = OvertimePolicyInputs(
        eligibility="SHIFT_FLAG",
        min_ot_minutes=15,
        rounding_minutes=None,
        rounding_mode="NONE",
        requires_post_approval=True,
        daily_cap_minutes=None,
        comp_off_instead_of_pay=False,
        night_ot_mode="SHIFT_FLAG",
        night_window_start=None,
        night_window_end=None,
        rate_rows=[],
    )
    minutes, classification, eligible = detect_overtime(
        worked_minutes=600,
        scheduled_minutes=480,
        is_shift_ot_eligible=False,
        is_holiday=False,
        is_weekly_off=False,
        is_night=False,
        policy=policy,
    )
    assert (minutes, classification, eligible) == (0, None, False)


def test_detect_overtime_below_minimum_not_counted() -> None:
    policy = OvertimePolicyInputs(
        eligibility="ALWAYS",
        min_ot_minutes=30,
        rounding_minutes=None,
        rounding_mode="NONE",
        requires_post_approval=True,
        daily_cap_minutes=None,
        comp_off_instead_of_pay=False,
        night_ot_mode="SHIFT_FLAG",
        night_window_start=None,
        night_window_end=None,
        rate_rows=[],
    )
    minutes, _classification, eligible = detect_overtime(
        worked_minutes=490,
        scheduled_minutes=480,
        is_shift_ot_eligible=True,
        is_holiday=False,
        is_weekly_off=False,
        is_night=False,
        policy=policy,
    )
    assert minutes == 0
    assert eligible is False


def test_detect_overtime_caps_at_daily_cap() -> None:
    policy = OvertimePolicyInputs(
        eligibility="ALWAYS",
        min_ot_minutes=15,
        rounding_minutes=None,
        rounding_mode="NONE",
        requires_post_approval=True,
        daily_cap_minutes=60,
        comp_off_instead_of_pay=False,
        night_ot_mode="SHIFT_FLAG",
        night_window_start=None,
        night_window_end=None,
        rate_rows=[],
    )
    minutes, _classification, eligible = detect_overtime(
        worked_minutes=700,
        scheduled_minutes=480,
        is_shift_ot_eligible=True,
        is_holiday=False,
        is_weekly_off=False,
        is_night=False,
        policy=policy,
    )
    assert eligible is True
    assert minutes == 60


def _ot_policy(**overrides: object) -> OvertimePolicyInputs:
    defaults: dict[str, object] = dict(
        eligibility="ALWAYS",
        min_ot_minutes=0,
        rounding_minutes=None,
        rounding_mode="NONE",
        requires_post_approval=True,
        daily_cap_minutes=None,
        comp_off_instead_of_pay=False,
        night_ot_mode="SHIFT_FLAG",
        night_window_start=None,
        night_window_end=None,
        rate_rows=[],
    )
    defaults.update(overrides)
    return OvertimePolicyInputs(**defaults)  # type: ignore[arg-type]


def test_detect_overtime_weekly_cap_clamps_below_daily_cap() -> None:
    """W7 (WD-29 decision 3) — `remaining_weekly_minutes` clamps independently of, and can bind
    tighter than, `daily_cap_minutes`."""
    policy = _ot_policy(daily_cap_minutes=180, remaining_weekly_minutes=45)
    minutes, _classification, eligible = detect_overtime(
        worked_minutes=700,
        scheduled_minutes=480,
        is_shift_ot_eligible=True,
        is_holiday=False,
        is_weekly_off=False,
        is_night=False,
        policy=policy,
    )
    assert eligible is True
    assert minutes == 45


def test_detect_overtime_monthly_cap_clamps() -> None:
    policy = _ot_policy(remaining_monthly_minutes=10)
    minutes, _classification, eligible = detect_overtime(
        worked_minutes=600,
        scheduled_minutes=480,
        is_shift_ot_eligible=True,
        is_holiday=False,
        is_weekly_off=False,
        is_night=False,
        policy=policy,
    )
    assert eligible is True
    assert minutes == 10


def test_detect_overtime_weekly_cap_exhausted_still_eligible_zero_minutes() -> None:
    """A fully-consumed weekly budget still returns `eligible=True` with `0` minutes — never
    silently discarded/miscounted, matching the existing daily-cap posture (`min_ot_minutes`
    short-circuits to `eligible=False`, but an exhausted *cap* does not)."""
    policy = _ot_policy(remaining_weekly_minutes=0)
    minutes, _classification, eligible = detect_overtime(
        worked_minutes=600,
        scheduled_minutes=480,
        is_shift_ot_eligible=True,
        is_holiday=False,
        is_weekly_off=False,
        is_night=False,
        policy=policy,
    )
    assert eligible is True
    assert minutes == 0


def test_classify_ot_day_holiday_wins_over_weekly_off_and_night() -> None:
    assert (
        classify_ot_day(is_holiday=True, is_weekly_off=True, is_night=True, night_ot_mode="BOTH")
        == "HOLIDAY"
    )


def test_classify_ot_day_weekly_off_wins_over_night() -> None:
    assert (
        classify_ot_day(is_holiday=False, is_weekly_off=True, is_night=True, night_ot_mode="BOTH")
        == "WEEKLY_OFF"
    )


def test_classify_ot_day_night_requires_window_or_both_mode() -> None:
    assert (
        classify_ot_day(
            is_holiday=False, is_weekly_off=False, is_night=True, night_ot_mode="SHIFT_FLAG"
        )
        == "NORMAL"
    )
    assert (
        classify_ot_day(
            is_holiday=False, is_weekly_off=False, is_night=True, night_ot_mode="WINDOW"
        )
        == "NIGHT"
    )


def test_classify_ot_day_normal_default() -> None:
    assert (
        classify_ot_day(is_holiday=False, is_weekly_off=False, is_night=False, night_ot_mode="BOTH")
        == "NORMAL"
    )


# ---------------------------------------------------------------------------
# evaluate_day — terminal statuses
# ---------------------------------------------------------------------------


def _base_input(**overrides: object) -> AttendanceCalculationInput:
    defaults: dict[str, object] = dict(
        employee_id=uuid4(),
        attendance_date=date(2026, 8, 10),
        timezone="Asia/Kolkata",
        population_status="ACTIVE",
        calendar_day_type="WORKING",
        holiday_name=None,
        holiday_on_weekly_off=False,
        shift=_shift(),
        scheduled_start=datetime(2026, 8, 10, 3, 30, tzinfo=UTC),
        scheduled_end=datetime(2026, 8, 10, 12, 30, tzinfo=UTC),
        policy=_policy(),
        hour_bands=[BandData(min_minutes=240, max_minutes=None, classification="PRESENT")],
        late_bands=[],
        early_bands=[],
        ot_policy=None,
        punches=[],
    )
    defaults.update(overrides)
    return AttendanceCalculationInput(**defaults)  # type: ignore[arg-type]


def test_evaluate_day_not_joined() -> None:
    result = evaluate_day(_base_input(population_status="NOT_JOINED"))
    assert result.attendance_status == "NOT_JOINED"


def test_evaluate_day_exited() -> None:
    result = evaluate_day(_base_input(population_status="EXITED"))
    assert result.attendance_status == "EXITED"


def test_evaluate_day_config_error_no_calendar() -> None:
    result = evaluate_day(_base_input(calendar_day_type=None))
    assert result.attendance_status == "CONFIG_ERROR"
    assert result.paid_day_fraction == "0.00"
    assert result.lop_fraction == "0.00"


def test_evaluate_day_config_error_no_policy() -> None:
    result = evaluate_day(_base_input(policy=None))
    assert result.attendance_status == "CONFIG_ERROR"


def test_evaluate_day_not_expected_holiday_no_punches() -> None:
    result = evaluate_day(_base_input(calendar_day_type="HOLIDAY", holiday_name="Test Holiday"))
    assert result.attendance_status == "NOT_EXPECTED"
    assert result.paid_day_fraction == "1.00"


def test_evaluate_day_present_full_day() -> None:
    punches = [
        _punch(3, 25, "IN", day=10),
        _punch(12, 35, "OUT", day=10),
    ]
    result = evaluate_day(_base_input(punches=punches))
    assert result.attendance_status == "PRESENT"
    assert result.worked_minutes == 550
    assert result.is_late is False
    assert result.paid_day_fraction == "1.00"


def test_evaluate_day_late_beyond_grace() -> None:
    punches = [
        _punch(4, 0, "IN", day=10),
        _punch(12, 30, "OUT", day=10),
    ]
    result = evaluate_day(_base_input(punches=punches))
    assert result.is_late is True
    assert result.late_minutes == 20  # 30 min late - 10 min grace


def test_evaluate_day_no_punches_working_day_defaults_incomplete() -> None:
    """§11.5: "ABSENT is harsh and must be an explicit policy choice" — the documented
    `missing_punch_behaviour` default (INCOMPLETE) applies even to a zero-punch day."""
    result = evaluate_day(_base_input(punches=[]))
    assert result.attendance_status == "INCOMPLETE"
    assert result.lop_fraction == "0.00"


def test_evaluate_day_no_punches_absent_when_policy_says_absent() -> None:
    result = evaluate_day(_base_input(punches=[], policy=_policy(missing_punch_behaviour="ABSENT")))
    assert result.attendance_status == "ABSENT"
    assert result.lop_fraction == "1.00"


def test_evaluate_day_worked_on_weekly_off() -> None:
    punches = [
        _punch(3, 30, "IN", day=10),
        _punch(8, 30, "OUT", day=10),
    ]
    result = evaluate_day(_base_input(calendar_day_type="WEEKLY_OFF", punches=punches))
    assert result.worked_on_weekly_off is True


def test_evaluate_day_missing_shift_no_punches_incomplete_by_default() -> None:
    result = evaluate_day(_base_input(shift=None, scheduled_start=None, scheduled_end=None))
    assert result.attendance_status == "INCOMPLETE"


def test_evaluate_day_missing_shift_absent_when_policy_says_absent() -> None:
    result = evaluate_day(
        _base_input(
            shift=None,
            scheduled_start=None,
            scheduled_end=None,
            policy=_policy(missing_shift_behaviour="ABSENT"),
        )
    )
    assert result.attendance_status == "ABSENT"


# ---------------------------------------------------------------------------
# W5 — ShiftRoster overrides (architecture §9.7, WD-27)
# ---------------------------------------------------------------------------


def test_evaluate_day_roster_week_off_override_no_shift_no_punches_not_expected() -> None:
    """A pure roster week-off row (`shift_id=NULL`) must not fall through to
    `missing_shift_behaviour` and be misread as an unresolved-shift config problem — it is a
    deliberate day-off fact, checked ahead of the missing-shift branch."""
    result = evaluate_day(
        _base_input(
            shift=None,
            scheduled_start=None,
            scheduled_end=None,
            roster_week_off_override=True,
        )
    )
    assert result.attendance_status == "NOT_EXPECTED"
    assert result.paid_day_fraction == "1.00"


def test_evaluate_day_roster_week_off_override_wins_over_working_calendar() -> None:
    """§9.7's motivating case: a rotating-crew day off that the calendar/weekly-off pattern
    alone cannot represent. `calendar_day_type` stays WORKING (WD-04/WD-07 — roster never
    rewrites calendar type); only the expectation-of-presence outcome changes."""
    result = evaluate_day(
        _base_input(calendar_day_type="WORKING", roster_week_off_override=True, punches=[])
    )
    assert result.attendance_status == "NOT_EXPECTED"
    assert result.calendar_day_type == "WORKING"


def test_evaluate_day_roster_week_off_override_with_punches_still_evaluates_presence() -> None:
    """Working on a roster-marked off day is not a terminal short-circuit — it falls through to
    ordinary presence evaluation, the same way calendar-WEEKLY_OFF-with-punches does."""
    punches = [_punch(3, 30, "IN", day=10), _punch(12, 30, "OUT", day=10)]
    result = evaluate_day(
        _base_input(calendar_day_type="WORKING", roster_week_off_override=True, punches=punches)
    )
    assert result.attendance_status == "PRESENT"


def test_evaluate_day_roster_holiday_working_override_present() -> None:
    """architecture's explicit example: assignment default is a normal shift, roster marks a
    holiday as a working day for this one employee — the calendar stays HOLIDAY, but the shift
    is treated as operating, so a full day's punches evaluate to PRESENT +
    `worked_on_holiday`."""
    punches = [_punch(3, 30, "IN", day=10), _punch(12, 30, "OUT", day=10)]
    result = evaluate_day(
        _base_input(
            calendar_day_type="HOLIDAY",
            holiday_name="Test Holiday",
            roster_holiday_working_override=True,
            punches=punches,
        )
    )
    assert result.attendance_status == "PRESENT"
    assert result.worked_on_holiday is True
    assert result.calendar_day_type == "HOLIDAY"


def test_evaluate_day_roster_holiday_working_override_no_punches_still_not_expected() -> None:
    """`roster_holiday_working_override` is wired through exactly like the existing
    `shift.operates_on_holiday` flag it's OR'd alongside (`shift_operates`) — including that
    flag's existing zero-punch behaviour: `_resolve_primary_status`'s worked_minutes==0 branch
    keys off `not_expected` alone (day_type-derived), not `shift_operates`, so an "operates on
    holiday" shift with nobody actually punching in is still NOT_EXPECTED today, override or
    not. This is pre-existing W4 engine behaviour (same for a non-roster
    `operates_on_holiday=True` shift), not something W5 changes — this test pins it so a
    future change to that precedence doesn't silently regress unnoticed."""
    result = evaluate_day(
        _base_input(
            calendar_day_type="HOLIDAY",
            holiday_name="Test Holiday",
            roster_holiday_working_override=True,
            punches=[],
        )
    )
    assert result.attendance_status == "NOT_EXPECTED"


# ---------------------------------------------------------------------------
# Break matching
# ---------------------------------------------------------------------------


def test_unpaid_break_gap_already_excluded_not_double_subtracted() -> None:
    """§10.2: PAIR_ALL's `gross_minutes` only sums clocked-in intervals — an unpaid break gap
    between two pairs is already excluded by construction, so `worked_minutes` must equal the
    sum of the worked intervals exactly, not that sum minus the gap again."""
    shift = _shift(
        breaks=[
            ShiftBreakData(
                id=uuid4(),
                break_kind="FIXED_WINDOW",
                start_time=time(8, 0),
                end_time=time(9, 0),
                window_start=None,
                window_end=None,
                min_minutes=None,
                max_minutes=60,
                is_paid=False,
                is_mandatory=True,
            )
        ]
    )
    punches = [
        _punch(3, 30, "IN", day=10),
        _punch(8, 30, "OUT", day=10),
        _punch(9, 30, "IN", day=10),
        _punch(12, 30, "OUT", day=10),
    ]
    result = evaluate_day(
        _base_input(
            shift=shift,
            punches=punches,
            timezone="UTC",
            scheduled_start=datetime(2026, 8, 10, 3, 30, tzinfo=UTC),
            scheduled_end=datetime(2026, 8, 10, 12, 30, tzinfo=UTC),
        )
    )
    assert result.unpaid_break_minutes == 60
    # 5h (3:30-8:30) + 3h (9:30-12:30) = 480m worked; the 60m gap is unpaid but never counted
    # toward `gross_minutes` in the first place (PAIR_ALL), so no further subtraction applies.
    assert result.worked_minutes == 480


def test_paid_break_gap_added_back_to_worked_minutes() -> None:
    """§10.2: "paid break minutes are included" — a paid break gap must be added *back* to
    `worked_minutes` even though the employee was punched out for it."""
    shift = _shift(
        breaks=[
            ShiftBreakData(
                id=uuid4(),
                break_kind="FIXED_WINDOW",
                start_time=time(8, 0),
                end_time=time(8, 15),
                window_start=None,
                window_end=None,
                min_minutes=None,
                max_minutes=15,
                is_paid=True,
                is_mandatory=False,
            )
        ]
    )
    punches = [
        _punch(3, 30, "IN", day=10),
        _punch(8, 0, "OUT", day=10),
        _punch(8, 15, "IN", day=10),
        _punch(12, 30, "OUT", day=10),
    ]
    result = evaluate_day(
        _base_input(
            shift=shift,
            punches=punches,
            timezone="UTC",
            scheduled_start=datetime(2026, 8, 10, 3, 30, tzinfo=UTC),
            scheduled_end=datetime(2026, 8, 10, 12, 30, tzinfo=UTC),
        )
    )
    assert result.paid_break_minutes == 15
    # 4.5h (3:30-8:00) + 4h15m (8:15-12:30) = 525m clocked-in, plus the 15m paid break = 540m —
    # the same as if the employee had never punched out for the paid break at all.
    assert result.worked_minutes == 540


# ---------------------------------------------------------------------------
# SPLIT-shift overtime detection (W7, WD-29 decision 5 — previously always 0/never detected)
# ---------------------------------------------------------------------------


def test_evaluate_day_split_shift_detects_overtime() -> None:
    shift = _shift(
        shift_type="SPLIT",
        duty_blocks=[
            ShiftDutyBlockData(
                sequence=1, start_time=time(9, 0), end_time=time(13, 0), crosses_midnight=False
            ),
            ShiftDutyBlockData(
                sequence=2, start_time=time(14, 0), end_time=time(18, 0), crosses_midnight=False
            ),
        ],
        required_minutes=480,
    )
    punches = [
        _punch(9, 0, "IN", day=10),
        _punch(13, 0, "OUT", day=10),
        _punch(14, 0, "IN", day=10),
        _punch(20, 0, "OUT", day=10),  # 2h past the second block's 18:00 end
    ]
    result = evaluate_day(
        _base_input(
            shift=shift,
            punches=punches,
            timezone="UTC",
            scheduled_start=None,
            scheduled_end=None,
            ot_policy=_ot_policy(),
        )
    )
    assert result.attendance_status == "PRESENT"
    assert result.worked_minutes == 600  # both blocks fully worked (240m + 360m), no gap credit
    assert result.is_overtime is True
    assert result.ot_minutes_detected == 120  # 600 worked - 480 required
    assert result.ot_day_class == "NORMAL"


def test_evaluate_day_split_shift_no_overtime_policy_detects_nothing() -> None:
    """Confirms the SPLIT-shift fix is additive, not a silent behaviour change when no OT
    policy resolves at all (`ot_policy=None`, the pre-W7 default)."""
    shift = _shift(
        shift_type="SPLIT",
        duty_blocks=[
            ShiftDutyBlockData(
                sequence=1, start_time=time(9, 0), end_time=time(13, 0), crosses_midnight=False
            ),
        ],
        required_minutes=240,
    )
    punches = [_punch(9, 0, "IN", day=10), _punch(15, 0, "OUT", day=10)]
    result = evaluate_day(
        _base_input(
            shift=shift,
            punches=punches,
            timezone="UTC",
            scheduled_start=None,
            scheduled_end=None,
            ot_policy=None,
        )
    )
    assert result.is_overtime is False
    assert result.ot_minutes_detected == 0
    assert result.ot_day_class is None


# ---------------------------------------------------------------------------
# WD-32 — core-hours breach (decision 1)
# ---------------------------------------------------------------------------


def test_core_hours_breach_half_day_forces_status() -> None:
    """FLEX shift, core hours 11:00-16:00 UTC; employee leaves at 13:00, well before core_end —
    a breach, and `core_hours_breach_behaviour=HALF_DAY` forces the day to Half-Day even though
    hours worked alone would say Present."""
    shift = _shift(shift_type="FLEXIBLE", core_start=time(11, 0), core_end=time(16, 0))
    policy = _policy(core_hours_breach_behaviour="HALF_DAY")
    punches = [_punch(9, 0, "IN", day=10), _punch(13, 0, "OUT", day=10)]
    result = evaluate_day(
        _base_input(
            shift=shift,
            policy=policy,
            punches=punches,
            timezone="UTC",
            scheduled_start=datetime(2026, 8, 10, 9, 0, tzinfo=UTC),
            scheduled_end=datetime(2026, 8, 10, 18, 0, tzinfo=UTC),
        )
    )
    assert result.is_core_hours_breach is True
    assert result.attendance_status == "HALF_DAY"


def test_core_hours_breach_flag_only_no_status_change() -> None:
    """Same breach, but the default `FLAG` behaviour only records the fact — status is
    unaffected."""
    shift = _shift(shift_type="FLEXIBLE", core_start=time(11, 0), core_end=time(16, 0))
    policy = _policy(core_hours_breach_behaviour="FLAG")
    punches = [_punch(9, 0, "IN", day=10), _punch(13, 0, "OUT", day=10)]
    result = evaluate_day(
        _base_input(
            shift=shift,
            policy=policy,
            punches=punches,
            timezone="UTC",
            scheduled_start=datetime(2026, 8, 10, 9, 0, tzinfo=UTC),
            scheduled_end=datetime(2026, 8, 10, 18, 0, tzinfo=UTC),
        )
    )
    assert result.is_core_hours_breach is True
    assert result.attendance_status == "PRESENT"


def test_core_hours_no_breach_when_fully_covered() -> None:
    """Presence spans the whole core window — no breach, regardless of behaviour."""
    shift = _shift(shift_type="FLEXIBLE", core_start=time(11, 0), core_end=time(16, 0))
    policy = _policy(core_hours_breach_behaviour="HALF_DAY")
    punches = [_punch(9, 0, "IN", day=10), _punch(18, 0, "OUT", day=10)]
    result = evaluate_day(
        _base_input(
            shift=shift,
            policy=policy,
            punches=punches,
            timezone="UTC",
            scheduled_start=datetime(2026, 8, 10, 9, 0, tzinfo=UTC),
            scheduled_end=datetime(2026, 8, 10, 18, 0, tzinfo=UTC),
        )
    )
    assert result.is_core_hours_breach is False
    assert result.attendance_status == "PRESENT"


def test_core_hours_ignored_on_fixed_shift() -> None:
    """§11.8: core hours is a FLEX-only concept — a FIXED shift with core_start/core_end set
    (should never happen via the API, but the engine must not misbehave) is simply not checked."""
    shift = _shift(shift_type="FIXED", core_start=time(11, 0), core_end=time(16, 0))
    policy = _policy(core_hours_breach_behaviour="HALF_DAY")
    punches = [_punch(9, 0, "IN", day=10), _punch(13, 0, "OUT", day=10)]
    result = evaluate_day(
        _base_input(
            shift=shift,
            policy=policy,
            punches=punches,
            timezone="UTC",
            scheduled_start=datetime(2026, 8, 10, 9, 0, tzinfo=UTC),
            scheduled_end=datetime(2026, 8, 10, 18, 0, tzinfo=UTC),
        )
    )
    assert result.is_core_hours_breach is False


# ---------------------------------------------------------------------------
# WD-32 — cumulative repeated-lateness (decision 3) and excess-break-days (decision 2)
# ---------------------------------------------------------------------------


def test_cumulative_lateness_forces_half_day_once_threshold_crossed() -> None:
    """Threshold is 3; two prior qualifying days already counted this window, and today is
    late too — the third crossing forces Half-Day even though hours worked alone say Present."""
    policy = _policy(lates_to_half_day_count=3)
    punches = [_punch(4, 0, "IN", day=10), _punch(12, 30, "OUT", day=10)]  # 20 min late
    result = evaluate_day(_base_input(policy=policy, punches=punches, prior_late_days_in_window=2))
    assert result.is_late is True
    assert result.attendance_status == "HALF_DAY"


def test_cumulative_lateness_below_threshold_no_override() -> None:
    """Same policy, but only one prior late day — today's lateness makes two, still under the
    threshold of three, so status is unaffected by the cumulative rule."""
    policy = _policy(lates_to_half_day_count=3)
    punches = [_punch(4, 0, "IN", day=10), _punch(12, 30, "OUT", day=10)]  # 20 min late
    result = evaluate_day(_base_input(policy=policy, punches=punches, prior_late_days_in_window=1))
    assert result.is_late is True
    assert result.attendance_status == "PRESENT"


def test_cumulative_lateness_not_configured_is_a_no_op() -> None:
    """`lates_to_half_day_count=None` (default) — the cumulative rule never engages, regardless
    of how many prior late days are passed in."""
    policy = _policy(lates_to_half_day_count=None)
    punches = [_punch(4, 0, "IN", day=10), _punch(12, 30, "OUT", day=10)]
    result = evaluate_day(_base_input(policy=policy, punches=punches, prior_late_days_in_window=10))
    assert result.attendance_status == "PRESENT"


def test_cumulative_excess_break_days_forces_half_day_once_threshold_crossed() -> None:
    """Threshold is 2; one prior qualifying day already counted, and today's break overruns its
    configured maximum too — the second crossing forces Half-Day."""
    shift = _shift(
        breaks=[
            ShiftBreakData(
                id=uuid4(),
                break_kind="FIXED_WINDOW",
                start_time=time(8, 0),
                end_time=time(9, 0),
                window_start=None,
                window_end=None,
                min_minutes=None,
                max_minutes=30,
                is_paid=False,
                is_mandatory=True,
            )
        ]
    )
    policy = _policy(excess_break_days_to_half_day_count=2)
    punches = [
        _punch(3, 30, "IN", day=10),
        _punch(8, 0, "OUT", day=10),
        _punch(9, 30, "IN", day=10),  # 90-min gap against a 30-min-max break -> excess
        _punch(12, 30, "OUT", day=10),
    ]
    result = evaluate_day(
        _base_input(
            shift=shift,
            policy=policy,
            punches=punches,
            timezone="UTC",
            scheduled_start=datetime(2026, 8, 10, 3, 30, tzinfo=UTC),
            scheduled_end=datetime(2026, 8, 10, 12, 30, tzinfo=UTC),
            prior_excess_break_days_in_window=1,
        )
    )
    assert result.excess_break_minutes > 0
    assert result.attendance_status == "HALF_DAY"


# ---------------------------------------------------------------------------
# WD-32 — early-departure pre-approval (decision 5)
# ---------------------------------------------------------------------------


def test_early_departure_requires_approval_forces_harshest_band_when_missing() -> None:
    """Policy requires pre-approval; none is on file. Raw early-departure minutes would only
    land in the lower `EARLY_DEPARTURE` band, but with no approval the day is forced to the
    harshest *configured* band (`ABSENT` here) instead of the graduated one."""
    policy = _policy(early_departure_requires_approval=True)
    early_bands = [
        BandData(min_minutes=0, max_minutes=59, classification="EARLY_DEPARTURE"),
        BandData(min_minutes=60, max_minutes=None, classification="ABSENT"),
    ]
    punches = [_punch(3, 30, "IN", day=10), _punch(12, 0, "OUT", day=10)]  # 20 min early
    result = evaluate_day(
        _base_input(
            policy=policy,
            early_bands=early_bands,
            punches=punches,
            early_departure_pre_approved=False,
        )
    )
    assert result.attendance_status == "ABSENT"


def test_early_departure_pre_approved_uses_normal_graduated_bands() -> None:
    """Same situation, but an approved pre-clearance is on file — the raw minutes are evaluated
    against the graduated bands normally, not forced to the harshest one."""
    policy = _policy(early_departure_requires_approval=True)
    early_bands = [
        BandData(min_minutes=0, max_minutes=59, classification="EARLY_DEPARTURE"),
        BandData(min_minutes=60, max_minutes=None, classification="ABSENT"),
    ]
    punches = [_punch(3, 30, "IN", day=10), _punch(12, 0, "OUT", day=10)]  # 20 min early
    result = evaluate_day(
        _base_input(
            policy=policy,
            early_bands=early_bands,
            punches=punches,
            early_departure_pre_approved=True,
        )
    )
    assert result.early_departure_classification == "EARLY_DEPARTURE"
    assert result.attendance_status == "PRESENT"


def test_early_departure_approval_not_required_is_unaffected() -> None:
    """Default policy (`early_departure_requires_approval=False`) — the pre-approval machinery
    never engages, identical to pre-WD-32 behaviour."""
    policy = _policy(early_departure_requires_approval=False)
    early_bands = [BandData(min_minutes=0, max_minutes=None, classification="EARLY_DEPARTURE")]
    punches = [_punch(3, 30, "IN", day=10), _punch(12, 0, "OUT", day=10)]
    result = evaluate_day(
        _base_input(
            policy=policy,
            early_bands=early_bands,
            punches=punches,
            early_departure_pre_approved=False,
        )
    )
    assert result.early_departure_classification == "EARLY_DEPARTURE"


# ---------------------------------------------------------------------------
# WD-32 — real ON_DUTY status (decision 6)
# ---------------------------------------------------------------------------


def test_on_duty_approved_no_punch_required_short_circuits_status() -> None:
    """`on_duty_requires_punch=False` (default) — an approved ON_DUTY request alone produces
    the status outright, full paid day, no punches needed."""
    policy = _policy(on_duty_requires_punch=False)
    result = evaluate_day(_base_input(policy=policy, punches=[], on_duty_approved=True))
    assert result.attendance_status == "ON_DUTY"
    assert result.paid_day_fraction == "1.00"
    assert result.lop_fraction == "0.00"


def test_on_duty_requires_punch_keeps_punch_status_and_flags() -> None:
    """`on_duty_requires_punch=True` — the punch-derived status is kept as-is, and
    `is_on_duty_flagged` is raised for reporting instead of overriding the status."""
    policy = _policy(on_duty_requires_punch=True)
    punches = [_punch(3, 25, "IN", day=10), _punch(12, 35, "OUT", day=10)]
    result = evaluate_day(_base_input(policy=policy, punches=punches, on_duty_approved=True))
    assert result.attendance_status == "PRESENT"
    assert result.is_on_duty_flagged is True


def test_on_duty_not_approved_is_a_no_op() -> None:
    """No approved ON_DUTY request on file — the overlay never engages, identical to
    pre-WD-32 behaviour."""
    result = evaluate_day(_base_input(punches=[], on_duty_approved=False))
    assert result.attendance_status == "INCOMPLETE"
    assert result.is_on_duty_flagged is False


def test_on_duty_overlay_does_not_apply_to_not_joined() -> None:
    """Population gate still ranks above ON_DUTY — an approved request cannot resurrect a
    NOT_JOINED day."""
    result = evaluate_day(_base_input(population_status="NOT_JOINED", on_duty_approved=True))
    assert result.attendance_status == "NOT_JOINED"
