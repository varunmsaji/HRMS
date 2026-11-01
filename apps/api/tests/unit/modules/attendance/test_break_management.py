"""Break management V1 in the pure calculation engine (`attendance/calculation.py`) — no DB.

Times are written in Asia/Kolkata (the base shift is 09:00–18:00 IST) and converted to UTC."""

from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID, uuid4

import pytest

from hrms.modules.attendance.calculation import (
    AttendanceCalculationInput,
    BandData,
    BreakEventData,
    OvertimePolicyInputs,
    PolicyInputs,
    PunchData,
    ShiftBreakData,
    ShiftInputs,
    effective_break_events,
    evaluate_day,
    pair_break_events,
)

IST = timedelta(hours=5, minutes=30)


def ist(hour: int, minute: int = 0, day: int = 10) -> datetime:
    return datetime(2026, 8, day, hour, minute, tzinfo=UTC) - IST


def punch(hour: int, minute: int, direction: str, day: int = 10) -> PunchData:
    return PunchData(id=uuid4(), punch_time=ist(hour, minute, day), direction=direction)


def policy(**overrides: object) -> PolicyInputs:
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


def rule(
    name: str = "Lunch",
    *,
    mode: str | None = "AUTO_DEDUCT",
    start: time = time(13, 0),
    end: time = time(14, 0),
    paid: bool = False,
    minutes: int | None = 60,
    max_minutes: int | None = None,
    **overrides: object,
) -> ShiftBreakData:
    defaults: dict[str, object] = dict(
        id=uuid4(),
        break_kind="FIXED_WINDOW",
        start_time=start,
        end_time=end,
        window_start=None,
        window_end=None,
        min_minutes=None,
        max_minutes=max_minutes,
        is_paid=paid,
        is_mandatory=True,
        name=name,
        mode=mode,
        scheduled_minutes=minutes,
    )
    defaults.update(overrides)
    return ShiftBreakData(**defaults)  # type: ignore[arg-type]


def make_input(
    breaks: list[ShiftBreakData],
    punches: list[PunchData],
    events: list[BreakEventData] | None = None,
    **overrides: object,
) -> AttendanceCalculationInput:
    shift = ShiftInputs(
        shift_type="FIXED",
        is_ot_eligible=bool(overrides.pop("ot", False)),
        operates_on_holiday=False,
        operates_on_weekly_off=False,
        is_cross_midnight=False,
        breaks=breaks,
    )
    defaults: dict[str, object] = dict(
        employee_id=uuid4(),
        attendance_date=date(2026, 8, 10),
        timezone="Asia/Kolkata",
        population_status="ACTIVE",
        calendar_day_type="WORKING",
        holiday_name=None,
        holiday_on_weekly_off=False,
        shift=shift,
        scheduled_start=ist(9),
        scheduled_end=ist(18),
        policy=policy(),
        hour_bands=[
            BandData(min_minutes=0, max_minutes=239, classification="HALF_DAY"),
            BandData(min_minutes=240, max_minutes=None, classification="PRESENT"),
        ],
        punches=punches,
        break_events=events or [],
    )
    defaults.update(overrides)
    return AttendanceCalculationInput(**defaults)  # type: ignore[arg-type]


def ev(
    kind: str,
    when: datetime,
    name: str | None = "Lunch",
    *,
    supersedes: UUID | None = None,
    approved: bool = False,
    event_id: UUID | None = None,
) -> BreakEventData:
    return BreakEventData(
        id=event_id or uuid4(),
        event_type=kind,
        event_time=when,
        break_name=name,
        supersedes_event_id=supersedes,
        approved=approved,
    )


FULL_DAY = [punch(9, 0, "IN"), punch(18, 0, "OUT")]


# --- automatic deduction ------------------------------------------------------------------


def test_auto_deduct_full_shift_deducts_the_configured_hour() -> None:
    result = evaluate_day(make_input([rule()], FULL_DAY))
    assert result.worked_minutes == 480
    assert result.gross_elapsed_minutes == 540
    assert result.unpaid_break_minutes == 60
    assert result.auto_deducted_break_minutes == 60
    assert result.actual_break_minutes == 0
    (brk,) = result.breaks
    assert brk.kind == "AUTO_DEDUCTED" and brk.deducted_minutes == 60
    assert brk.rule_source == "SHIFT" and brk.name == "Lunch"
    assert result.attendance_status == "PRESENT"


def test_auto_deduct_is_not_applied_when_employee_arrives_after_the_break() -> None:
    result = evaluate_day(make_input([rule()], [punch(14, 30, "IN"), punch(18, 0, "OUT")]))
    assert result.worked_minutes == 210
    assert result.auto_deducted_break_minutes == 0
    assert result.breaks == []
    assert result.snapshot["breaks"]["auto_not_eligible"] == ["Lunch"]


@pytest.mark.parametrize(
    ("arrive", "leave", "deducted"),
    [((13, 30), (18, 0), 30), ((9, 0), (13, 20), 20), ((13, 15), (13, 45), 30)],
)
def test_auto_deduct_is_prorated_to_the_time_worked_inside_the_window(
    arrive: tuple[int, int], leave: tuple[int, int], deducted: int
) -> None:
    result = evaluate_day(make_input([rule()], [punch(*arrive, "IN"), punch(*leave, "OUT")]))
    assert result.auto_deducted_break_minutes == deducted


def test_auto_deduct_full_flag_deducts_the_whole_duration_for_a_partial_overlap() -> None:
    result = evaluate_day(
        make_input([rule(auto_deduct_full=True)], [punch(13, 30, "IN"), punch(18, 0, "OUT")])
    )
    assert result.auto_deducted_break_minutes == 60


def test_auto_deduct_never_exceeds_the_configured_duration() -> None:
    wide = rule(start=time(12, 0), end=time(15, 0), minutes=45)
    result = evaluate_day(make_input([wide], FULL_DAY))
    assert result.auto_deducted_break_minutes == 45


def test_paid_auto_break_is_reported_but_not_deducted() -> None:
    result = evaluate_day(
        make_input([rule("Tea", paid=True, start=time(11), end=time(11, 15), minutes=15)], FULL_DAY)
    )
    assert result.worked_minutes == 540
    assert result.paid_break_minutes == 15
    assert result.unpaid_break_minutes == 0
    assert result.auto_deducted_break_minutes == 0


def test_multiple_breaks_paid_and_unpaid() -> None:
    breaks = [
        rule("Morning tea", paid=True, start=time(11), end=time(11, 15), minutes=15),
        rule("Lunch"),
        rule("Evening tea", paid=False, start=time(16), end=time(16, 15), minutes=15),
    ]
    result = evaluate_day(make_input(breaks, FULL_DAY))
    assert result.worked_minutes == 540 - 60 - 15
    assert result.paid_break_minutes == 15
    assert result.unpaid_break_minutes == 75
    assert sorted(b.name for b in result.breaks) == ["Evening tea", "Lunch", "Morning tea"]


def test_disabled_break_is_ignored() -> None:
    result = evaluate_day(make_input([rule(is_enabled=False)], FULL_DAY))
    assert result.worked_minutes == 540 and result.breaks == []


def test_legacy_break_without_a_gap_is_still_not_deducted() -> None:
    result = evaluate_day(make_input([rule(mode=None)], FULL_DAY))
    assert result.worked_minutes == 540 and result.breaks == []


def test_legacy_break_is_still_matched_against_a_punch_gap() -> None:
    punches = [
        punch(9, 0, "IN"),
        punch(13, 0, "OUT"),
        punch(14, 0, "IN"),
        punch(18, 0, "OUT"),
    ]
    result = evaluate_day(make_input([rule(mode=None)], punches))
    (brk,) = result.breaks
    assert brk.kind == "PUNCHED_GAP" and brk.minutes == 60 and not brk.is_paid
    assert result.worked_minutes == 480


# --- explicit events ----------------------------------------------------------------------


def test_mandatory_break_events_are_deducted_by_their_actual_length() -> None:
    events = [ev("START", ist(13, 0)), ev("END", ist(13, 50))]
    result = evaluate_day(make_input([rule(mode="MANDATORY_PUNCH")], FULL_DAY, events))
    assert result.worked_minutes == 540 - 50
    assert result.actual_break_minutes == 50
    assert result.auto_deducted_break_minutes == 0
    (brk,) = result.breaks
    assert brk.kind == "EVENT" and brk.minutes == 50 and brk.deducted_minutes == 50


def test_mandatory_break_never_recorded_is_not_deducted_and_is_noted() -> None:
    result = evaluate_day(make_input([rule(mode="MANDATORY_PUNCH")], FULL_DAY))
    assert result.worked_minutes == 540
    assert result.snapshot["breaks"]["mandatory_not_recorded"] == ["Lunch"]
    assert not result.has_unresolved_break


def test_recorded_break_replaces_the_scheduled_deduction_instead_of_adding_to_it() -> None:
    """Scheduled 13:00–14:00, punched 13:05–14:00: 55 minutes, never 55 + 60."""
    events = [ev("START", ist(13, 5)), ev("END", ist(14, 0))]
    result = evaluate_day(make_input([rule(mode="AUTO_DEDUCT")], FULL_DAY, events))
    assert result.unpaid_break_minutes == 55
    assert result.worked_minutes == 540 - 55
    assert [b.kind for b in result.breaks] == ["EVENT"]


def test_overlapping_breaks_of_different_rules_do_not_deduct_the_same_minutes_twice() -> None:
    tea = rule("Tea", mode="MANDATORY_PUNCH", start=time(13, 30), end=time(13, 45), minutes=15)
    events = [ev("START", ist(13, 30), "Tea"), ev("END", ist(13, 45), "Tea")]
    result = evaluate_day(make_input([rule(), tea], FULL_DAY, events))
    # lunch auto 13:00–14:00 minus the 15 minutes the recorded tea already covers = 45, + 15 tea
    assert result.unpaid_break_minutes == 60
    assert result.worked_minutes == 480


def test_optional_break_unrecorded_means_no_deduction() -> None:
    result = evaluate_day(make_input([rule(mode="OPTIONAL_PUNCH")], FULL_DAY))
    assert result.worked_minutes == 540 and result.breaks == []


def test_optional_break_unrecorded_falls_back_to_schedule_when_configured() -> None:
    result = evaluate_day(
        make_input([rule(mode="OPTIONAL_PUNCH", optional_scheduled_fallback=True)], FULL_DAY)
    )
    assert result.worked_minutes == 480 and result.auto_deducted_break_minutes == 60


def test_optional_recorded_break_follows_the_recorded_deducts_flag() -> None:
    events = [ev("START", ist(13, 0)), ev("END", ist(13, 40))]
    deducts = evaluate_day(make_input([rule(mode="OPTIONAL_PUNCH")], FULL_DAY, events))
    assert deducts.worked_minutes == 540 - 40
    ignored = evaluate_day(
        make_input([rule(mode="OPTIONAL_PUNCH", optional_recorded_deducts=False)], FULL_DAY, events)
    )
    assert ignored.worked_minutes == 540
    assert ignored.actual_break_minutes == 40  # still recorded, just not deducted


def test_paid_recorded_break_does_not_reduce_working_time() -> None:
    events = [ev("START", ist(11, 0), "Tea"), ev("END", ist(11, 15), "Tea")]
    tea = rule("Tea", mode="MANDATORY_PUNCH", paid=True, start=time(11), end=time(11, 15))
    result = evaluate_day(make_input([tea], FULL_DAY, events))
    assert result.worked_minutes == 540
    assert result.paid_break_minutes == 15 and result.unpaid_break_minutes == 0


# --- unresolved breaks --------------------------------------------------------------------


def test_unresolved_break_stops_crediting_work_and_waits_for_review() -> None:
    events = [ev("START", ist(13, 0))]
    result = evaluate_day(make_input([rule(mode="MANDATORY_PUNCH")], FULL_DAY, events))
    assert result.worked_minutes == 240  # 09:00–13:00 only
    assert result.has_unresolved_break and result.unresolved_break_count == 1
    assert result.attendance_status == "INCOMPLETE"
    assert result.paid_day_fraction == "0.00" and result.lop_fraction == "0.00"
    (brk,) = result.breaks
    assert brk.kind == "UNRESOLVED" and brk.end is None and brk.needs_review
    assert result.actual_last_out == ist(18, 0)  # the real punch is not rewritten


def test_unresolved_break_is_never_half_day_or_absent_even_with_little_work() -> None:
    punches = [punch(9, 0, "IN"), punch(10, 0, "OUT")]
    events = [ev("START", ist(9, 30))]
    result = evaluate_day(make_input([rule(mode="MANDATORY_PUNCH")], punches, events))
    assert result.attendance_status == "INCOMPLETE"
    assert result.lop_fraction == "0.00"


def test_open_break_on_a_still_open_day_is_active_not_unresolved() -> None:
    events = [ev("START", ist(13, 0))]
    result = evaluate_day(
        make_input([rule(mode="MANDATORY_PUNCH")], [punch(9, 0, "IN")], events, day_open=True)
    )
    assert result.has_active_break and not result.has_unresolved_break
    (brk,) = result.breaks
    assert brk.is_active and not brk.needs_review


def test_open_break_on_a_closed_day_without_checkout_is_unresolved() -> None:
    events = [ev("START", ist(13, 0))]
    result = evaluate_day(
        make_input([rule(mode="MANDATORY_PUNCH")], [punch(9, 0, "IN")], events, day_open=False)
    )
    assert result.has_unresolved_break


def test_authorised_correction_resolves_the_break_and_keeps_the_originals() -> None:
    start = ev("START", ist(13, 0))
    corrected_end = ev("END", ist(14, 0), approved=True)
    result = evaluate_day(
        make_input([rule(mode="MANDATORY_PUNCH")], FULL_DAY, [start, corrected_end])
    )
    assert not result.has_unresolved_break
    assert result.worked_minutes == 480 and result.attendance_status == "PRESENT"
    assert result.breaks[0].is_approved


def test_superseded_events_are_ignored_but_listed_in_the_snapshot() -> None:
    start = ev("START", ist(13, 0))
    wrong_end = ev("END", ist(14, 30))
    fixed_end = ev("END", ist(14, 0), supersedes=wrong_end.id, approved=True)
    result = evaluate_day(
        make_input([rule(mode="MANDATORY_PUNCH")], FULL_DAY, [start, wrong_end, fixed_end])
    )
    assert result.actual_break_minutes == 60
    assert result.snapshot["breaks"]["superseded_event_ids"] == [str(wrong_end.id)]


# --- excess duration ----------------------------------------------------------------------


def _excess_input(outcome: str | None, *, paid: bool = False, approved: bool = False):
    events = [ev("START", ist(13, 0)), ev("END", ist(14, 0), approved=approved)]
    return make_input(
        [rule(mode="MANDATORY_PUNCH", max_minutes=45, excess_outcome=outcome, paid=paid)],
        FULL_DAY,
        events,
    )


def test_excess_break_creates_an_exception_and_keeps_the_actual_duration() -> None:
    result = evaluate_day(_excess_input("EXCEPTION"))
    assert result.excess_break_minutes == 15
    assert result.has_excess_break_exception
    assert result.breaks[0].minutes == 60  # never truncated to the maximum
    assert result.worked_minutes == 480  # the unpaid hour was already off the clock
    assert result.attendance_status == "PRESENT"


def test_excess_record_only_creates_no_exception() -> None:
    result = evaluate_day(_excess_input("RECORD_ONLY"))
    assert result.excess_break_minutes == 15 and not result.has_excess_break_exception


def test_excess_require_approval_flags_the_break_for_review() -> None:
    result = evaluate_day(_excess_input("REQUIRE_APPROVAL"))
    assert result.has_excess_break_exception and result.breaks[0].needs_review


def test_excess_on_a_paid_break_is_deducted_only_when_the_outcome_says_so() -> None:
    plain = evaluate_day(_excess_input("EXCEPTION", paid=True))
    assert plain.worked_minutes == 540
    deducted = evaluate_day(_excess_input("DEDUCT", paid=True))
    assert deducted.worked_minutes == 540 - 15
    approved = evaluate_day(_excess_input("DEDUCT", paid=True, approved=True))
    assert approved.worked_minutes == 540 and not approved.has_excess_break_exception


def test_excess_outcome_falls_back_to_the_policy_behaviour() -> None:
    flagged = evaluate_day(
        replace(_excess_input(None), policy=policy(excess_break_behaviour="FLAG"))
    )
    assert flagged.has_excess_break_exception
    ignored = evaluate_day(
        replace(_excess_input(None), policy=policy(excess_break_behaviour="IGNORE"))
    )
    assert not ignored.has_excess_break_exception


# --- overnight / midnight ----------------------------------------------------------------


def _night(
    breaks: list[ShiftBreakData],
    punches: list[PunchData],
    events: list[BreakEventData] | None = None,
    **kw: object,
):
    return make_input(
        breaks,
        punches,
        events,
        scheduled_start=ist(22),
        scheduled_end=ist(6, day=11),
        **kw,
    )


def test_break_after_midnight_on_a_night_shift_is_placed_on_the_next_day() -> None:
    lunch = rule("Meal", start=time(1, 0), end=time(2, 0))
    result = evaluate_day(_night([lunch], [punch(22, 0, "IN"), punch(6, 0, "OUT", day=11)]))
    assert result.auto_deducted_break_minutes == 60
    assert result.worked_minutes == 480 - 60


def test_break_crossing_midnight_is_deducted_once() -> None:
    meal = rule("Meal", start=time(23, 30), end=time(0, 30), minutes=60)
    result = evaluate_day(_night([meal], [punch(22, 0, "IN"), punch(6, 0, "OUT", day=11)]))
    assert result.auto_deducted_break_minutes == 60
    assert result.breaks[0].end - result.breaks[0].start == timedelta(minutes=60)


def test_recorded_break_crossing_midnight() -> None:
    meal = rule("Meal", mode="MANDATORY_PUNCH", start=time(23, 30), end=time(0, 30))
    events = [ev("START", ist(23, 40), "Meal"), ev("END", ist(0, 20, day=11), "Meal")]
    result = evaluate_day(_night([meal], [punch(22, 0, "IN"), punch(6, 0, "OUT", day=11)], events))
    assert result.actual_break_minutes == 40


# --- overtime, determinism ----------------------------------------------------------------


def test_overtime_uses_the_net_schedule_after_an_unpaid_break() -> None:
    ot = OvertimePolicyInputs(
        eligibility="SHIFT_FLAG",
        min_ot_minutes=0,
        rounding_minutes=None,
        rounding_mode="NONE",
        requires_post_approval=False,
        daily_cap_minutes=None,
        comp_off_instead_of_pay=False,
        night_ot_mode="SHIFT_FLAG",
        night_window_start=None,
        night_window_end=None,
    )
    punches = [punch(9, 0, "IN"), punch(19, 0, "OUT")]
    result = evaluate_day(make_input([rule()], punches, ot=True, ot_policy=ot))
    assert result.worked_minutes == 540
    assert result.ot_minutes_detected == 60  # not 0: 540 net vs a 480 net schedule


def test_recomputing_gives_the_same_result_and_leaves_events_untouched() -> None:
    events = [ev("START", ist(13, 0)), ev("END", ist(13, 50))]
    inputs = make_input([rule(mode="MANDATORY_PUNCH")], FULL_DAY, events)
    first, second = evaluate_day(inputs), evaluate_day(inputs)
    assert first.breaks == second.breaks and first.worked_minutes == second.worked_minutes
    assert inputs.break_events == events


def test_event_pairing_and_supersede_helpers() -> None:
    a, b, c = ev("START", ist(10)), ev("START", ist(11)), ev("END", ist(12))
    assert pair_break_events(effective_break_events([a, b, c])) == [(a, None), (b, c)]
    orphan_end = ev("END", ist(9))
    assert pair_break_events(effective_break_events([orphan_end])) == []
