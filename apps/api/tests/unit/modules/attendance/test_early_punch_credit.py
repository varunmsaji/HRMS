"""Early punch-in allowance is a punch permission, not credited work or overtime.

Shift 09:30-18:30 IST (04:00-13:00 UTC). Credited presence starts at the scheduled start; the
punch and `actual_first_in` keep the real instant. Late arrival and late punch-out behave as
before (characterization tests at the bottom)."""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from hrms.modules.attendance.calculation import (
    AttendanceCalculationInput,
    BandData,
    OvertimePolicyInputs,
    PolicyInputs,
    PunchData,
    ShiftBreakData,
    ShiftInputs,
    clamp_pairs_to_start,
    evaluate_day,
)

D = date(2026, 8, 10)
START = datetime(2026, 8, 10, 4, 0, tzinfo=UTC)  # 09:30 IST
END = datetime(2026, 8, 10, 13, 0, tzinfo=UTC)  # 18:30 IST


def _t(ist_h: int, ist_m: int) -> datetime:
    return (
        datetime(2026, 8, 10, tzinfo=UTC)
        + timedelta(hours=ist_h, minutes=ist_m)
        - timedelta(hours=5, minutes=30)
    )


def _p(h: int, m: int, direction: str) -> PunchData:
    return PunchData(id=uuid4(), punch_time=_t(h, m), direction=direction)


def _policy(**kw: object) -> PolicyInputs:
    base: dict[str, object] = dict(
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
        core_hours_breach_behaviour="FLAG",
        early_out_uses_core_end=False,
        split_shift_missed_block_behaviour="HALF_DAY",
        excess_break_behaviour="FLAG",
        incomplete_at_lock_behaviour="TREAT_ABSENT",
        work_on_leave_behaviour="KEEP_LEAVE",
    )
    base.update(kw)
    return PolicyInputs(**base)  # type: ignore[arg-type]


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


def _run(punches: list[PunchData], shift_type: str = "FIXED", breaks: list | None = None):
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
                shift_type=shift_type,
                is_ot_eligible=True,
                operates_on_holiday=False,
                operates_on_weekly_off=False,
                is_cross_midnight=False,
                breaks=breaks or [],
            ),
            scheduled_start=START,
            scheduled_end=END,
            policy=_policy(),
            hour_bands=[BandData(0, None, "PRESENT")],
            ot_policy=OT,
            punches=punches,
        )
    )


def test_early_allowed_punch_not_credited_and_no_overtime() -> None:
    r = _run([_p(9, 0, "IN"), _p(18, 30, "OUT")])
    assert r.worked_minutes == 540
    assert r.ot_minutes_detected == 0 and not r.is_overtime and not r.ot_pending
    assert r.actual_first_in == _t(9, 0)  # real instant preserved
    assert r.scheduled_start == START  # baseline unchanged
    assert r.late_minutes == 0 and r.attendance_status == "PRESENT"


def test_punch_exactly_at_start_and_one_minute_early() -> None:
    assert _run([_p(9, 30, "IN"), _p(18, 30, "OUT")]).worked_minutes == 540
    assert _run([_p(9, 29, "IN"), _p(18, 30, "OUT")]).worked_minutes == 540


def test_far_early_in_window_still_not_credited() -> None:
    r = _run([_p(8, 0, "IN"), _p(18, 30, "OUT")])
    assert r.worked_minutes == 540 and r.ot_minutes_detected == 0


def test_pair_entirely_before_start_earns_nothing() -> None:
    r = _run([_p(8, 0, "IN"), _p(9, 0, "OUT"), _p(9, 30, "IN"), _p(18, 30, "OUT")])
    assert r.worked_minutes == 540


def test_late_punch_out_still_detects_overtime_from_shift_end() -> None:
    r = _run([_p(9, 0, "IN"), _p(20, 30, "OUT")])
    assert r.worked_minutes == 660
    assert r.ot_minutes_detected == 120 and r.ot_pending


def test_early_in_and_late_out_overtime_counts_only_after_shift() -> None:
    r = _run([_p(9, 0, "IN"), _p(19, 0, "OUT")])
    assert r.ot_minutes_detected == 30


def test_late_arrival_unchanged() -> None:
    on_time = _run([_p(9, 45, "IN"), _p(18, 30, "OUT")])
    late = _run([_p(9, 46, "IN"), _p(18, 30, "OUT")])
    assert on_time.late_minutes == 0 and late.late_minutes == 1
    assert late.worked_minutes == 524  # actual presence from the real punch


def test_break_cycle_unaffected_by_early_clamp() -> None:
    lunch = ShiftBreakData(
        id=uuid4(),
        break_kind="FIXED_WINDOW",
        start_time=_t(13, 0).time(),
        end_time=None,
        window_start=None,
        window_end=None,
        min_minutes=None,
        max_minutes=None,
        is_paid=False,
        is_mandatory=False,
    )
    r = _run([_p(9, 0, "IN"), _p(13, 0, "OUT"), _p(13, 30, "IN"), _p(18, 30, "OUT")], breaks=[])
    # 09:30-13:00 (210) + 13:30-18:30 (300) = 510; the gap is a deducted unpaid break.
    assert r.worked_minutes == 510
    assert r.unpaid_break_minutes == 30
    assert lunch is not None


def test_multiple_cycles_before_start() -> None:
    r = _run([_p(9, 0, "IN"), _p(9, 10, "OUT"), _p(9, 20, "IN"), _p(18, 30, "OUT")])
    assert r.worked_minutes == 540


def test_flexible_shift_not_clamped() -> None:
    r = _run([_p(9, 0, "IN"), _p(18, 30, "OUT")], shift_type="FLEXIBLE")
    assert r.worked_minutes == 570


def test_clamp_helper_no_start_is_identity() -> None:
    pairs = [(_p(9, 0, "IN"), _p(10, 0, "OUT"))]
    assert clamp_pairs_to_start(pairs, None) is pairs
