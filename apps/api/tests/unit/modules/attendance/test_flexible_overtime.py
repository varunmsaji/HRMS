"""FLEXIBLE overtime is measured against `required_minutes` (net work), never against the
length of the start-time window. Window 08:00-10:00 IST (02:30-04:30 UTC), required 480."""

from datetime import UTC, date, datetime, time, timedelta
from uuid import uuid4

from hrms.modules.attendance.calculation import (
    AttendanceCalculationInput,
    BandData,
    BreakEventData,
    OvertimePolicyInputs,
    PolicyInputs,
    PunchData,
    ShiftBreakData,
    ShiftInputs,
    evaluate_day,
)

D = date(2026, 8, 10)
WIN_START = datetime(2026, 8, 10, 2, 30, tzinfo=UTC)  # 08:00 IST
WIN_END = datetime(2026, 8, 10, 4, 30, tzinfo=UTC)  # 10:00 IST


def _t(h: int, m: int = 0) -> datetime:
    return (
        datetime(2026, 8, 10, tzinfo=UTC)
        + timedelta(hours=h, minutes=m)
        - timedelta(hours=5, minutes=30)
    )


def _p(h: int, m: int, d: str) -> PunchData:
    return PunchData(id=uuid4(), punch_time=_t(h, m), direction=d)


def _policy() -> PolicyInputs:
    return PolicyInputs(
        grace_in_minutes=15,
        grace_out_minutes=15,
        punch_rounding="NONE",
        rounding_minutes=None,
        missing_punch_behaviour="INCOMPLETE",
        missing_shift_behaviour="INCOMPLETE",
        half_day_split="BY_HOURS",
        half_day_boundary_minutes=None,
        multi_punch_mode="PAIR_ALL",
        duplicate_punch_window_seconds=60,
        core_hours_breach_behaviour="IGNORE",
        early_out_uses_core_end=False,
        split_shift_missed_block_behaviour="HALF_DAY",
        excess_break_behaviour="FLAG",
        incomplete_at_lock_behaviour="TREAT_ABSENT",
        work_on_leave_behaviour="KEEP_LEAVE",
    )


OT = OvertimePolicyInputs(
    eligibility="ALWAYS",
    min_ot_minutes=15,
    rounding_minutes=None,
    rounding_mode="NONE",
    requires_post_approval=True,
    daily_cap_minutes=None,
    comp_off_instead_of_pay=False,
    night_ot_mode="SHIFT_FLAG",
    night_window_start=None,
    night_window_end=None,
)


def _run(punches, breaks=None, events=None, required=480):  # type: ignore[no-untyped-def]
    return evaluate_day(
        AttendanceCalculationInput(
            employee_id=uuid4(),
            attendance_date=D,
            timezone="Asia/Kolkata",
            population_status="ACTIVE",
            calendar_day_type="WORKING",
            holiday_name=None,
            holiday_on_weekly_off=False,
            shift=ShiftInputs(
                shift_type="FLEXIBLE",
                is_ot_eligible=True,
                operates_on_holiday=False,
                operates_on_weekly_off=False,
                is_cross_midnight=False,
                breaks=breaks or [],
                required_minutes=required,
            ),
            scheduled_start=WIN_START,
            scheduled_end=WIN_END,
            policy=_policy(),
            hour_bands=[BandData(0, None, "PRESENT")],
            ot_policy=OT,
            punches=punches,
            break_events=events or [],
            day_open=False,
        )
    )


def test_required_duration_met_early_middle_late_start_has_no_overtime() -> None:
    for start in ((8, 30), (9, 0), (9, 45)):
        end = (start[0] + 8, start[1])
        r = _run([_p(*start, "IN"), _p(*end, "OUT")])
        assert r.worked_minutes == 480, start
        assert r.ot_minutes_detected == 0 and not r.ot_pending, start
        assert r.scheduled_minutes == 480


def test_exceeding_required_duration_gives_overtime_for_the_excess_only() -> None:
    r = _run([_p(9, 30, "IN"), _p(19, 0, "OUT")])
    assert r.worked_minutes == 570
    assert r.ot_minutes_detected == 90 and r.ot_pending


def test_shorter_than_required_has_no_overtime() -> None:
    assert _run([_p(9, 0, "IN"), _p(16, 0, "OUT")]).ot_minutes_detected == 0


def test_unpaid_gap_break_reduces_worked_time_before_overtime() -> None:
    r = _run([_p(9, 0, "IN"), _p(13, 0, "OUT"), _p(14, 0, "IN"), _p(18, 30, "OUT")])
    assert r.worked_minutes == 510  # 240 + 270; the one-hour gap is not work
    assert r.ot_minutes_detected == 30


def test_multiple_cycles_use_net_worked_time() -> None:
    r = _run(
        [
            _p(9, 0, "IN"),
            _p(11, 0, "OUT"),
            _p(11, 15, "IN"),
            _p(13, 0, "OUT"),
            _p(14, 0, "IN"),
            _p(19, 0, "OUT"),
        ]
    )
    # 120 + 105 + 300 = 525 worked of a 600-minute presence span.
    assert r.worked_minutes == 525
    assert r.ot_minutes_detected == 45


def test_long_break_is_not_counted_as_work_or_overtime() -> None:
    r = _run([_p(9, 0, "IN"), _p(12, 0, "OUT"), _p(15, 0, "IN"), _p(20, 0, "OUT")])
    assert r.worked_minutes == 480  # 180 + 300
    assert r.ot_minutes_detected == 0


def test_auto_deducted_break_is_not_subtracted_from_required_minutes_twice() -> None:
    lunch = ShiftBreakData(
        id=uuid4(),
        break_kind="FIXED_WINDOW",
        start_time=time(13, 0),
        end_time=time(14, 0),
        window_start=None,
        window_end=None,
        min_minutes=None,
        max_minutes=60,
        is_paid=False,
        is_mandatory=True,
        name="Lunch",
        mode="AUTO_DEDUCT",
        scheduled_minutes=60,
    )
    # 09:00-18:00 = 540 presence, minus the 60-minute lunch = 480 net = required: no overtime.
    r = _run([_p(9, 0, "IN"), _p(18, 0, "OUT")], breaks=[lunch])
    assert r.worked_minutes == 480
    assert r.ot_minutes_detected == 0


def test_recorded_break_event_reduces_worked_time() -> None:
    lunch = ShiftBreakData(
        id=uuid4(),
        break_kind="FIXED_WINDOW",
        start_time=time(13, 0),
        end_time=time(14, 0),
        window_start=None,
        window_end=None,
        min_minutes=None,
        max_minutes=60,
        is_paid=False,
        is_mandatory=True,
        name="Lunch",
        mode="MANDATORY_PUNCH",
        scheduled_minutes=60,
    )
    events = [
        BreakEventData(uuid4(), "START", _t(13, 0), "Lunch", lunch.id),
        BreakEventData(uuid4(), "END", _t(13, 30), "Lunch", lunch.id),
    ]
    r = _run([_p(9, 0, "IN"), _p(18, 0, "OUT")], breaks=[lunch], events=events)
    assert r.worked_minutes == 510
    assert r.ot_minutes_detected == 30  # against 480 required, not 480 minus the lunch again


def test_missing_punch_out_detects_no_overtime() -> None:
    r = _run([_p(9, 0, "IN")])
    assert r.attendance_status == "INCOMPLETE" and r.ot_minutes_detected == 0


def test_recalculation_is_deterministic() -> None:
    punches = [_p(9, 30, "IN"), _p(19, 0, "OUT")]
    a, b = _run(punches), _run(punches)
    assert (a.worked_minutes, a.ot_minutes_detected) == (b.worked_minutes, b.ot_minutes_detected)


def test_fixed_shift_overtime_is_unchanged() -> None:
    fixed = ShiftInputs(
        shift_type="FIXED",
        is_ot_eligible=True,
        operates_on_holiday=False,
        operates_on_weekly_off=False,
        is_cross_midnight=False,
        required_minutes=480,
    )
    r = evaluate_day(
        AttendanceCalculationInput(
            employee_id=uuid4(),
            attendance_date=D,
            timezone="Asia/Kolkata",
            population_status="ACTIVE",
            calendar_day_type="WORKING",
            holiday_name=None,
            holiday_on_weekly_off=False,
            shift=fixed,
            scheduled_start=_t(9, 30),
            scheduled_end=_t(18, 30),
            policy=_policy(),
            hour_bands=[BandData(0, None, "PRESENT")],
            ot_policy=OT,
            punches=[_p(9, 30, "IN"), _p(19, 30, "OUT")],
        )
    )
    # Scheduled span (540), not required_minutes (480), is the FIXED baseline.
    assert r.scheduled_minutes == 540 and r.ot_minutes_detected == 60
