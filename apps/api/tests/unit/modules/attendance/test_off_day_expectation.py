"""SH-03 and SH-08 (engine 13).

SH-03 (owner decision P-02): a shift that operates on a holiday or weekly off — or a roster
"working this holiday" row — makes the day an ordinary working day: attendance expected, absence
follows the missing-punch rule, work is ordinary pay (no holiday premium class).

SH-08 (owner decision P-06): with no shift, a full day off with no punches is NOT_EXPECTED, and
worked minutes go through the hour bands."""

import pytest
from tests.unit.modules.attendance.test_calculation import (
    _base_input,
    _ot_policy,
    _policy,
    _punch,
    _shift,
)

from hrms.modules.attendance.calculation import BandData, OvertimeRateRowData, evaluate_day

BANDS = [
    BandData(min_minutes=0, max_minutes=239, classification="ABSENT"),
    BandData(min_minutes=240, max_minutes=479, classification="HALF_DAY"),
    BandData(min_minutes=480, max_minutes=None, classification="PRESENT"),
]
RATES = [
    OvertimeRateRowData(day_class="NORMAL", classification_code="OT-N"),
    OvertimeRateRowData(day_class="HOLIDAY", classification_code="OT-H"),
    OvertimeRateRowData(day_class="WEEKLY_OFF", classification_code="OT-W"),
]
# `_base_input` schedules 09:00-18:00 IST = 03:30-12:30 UTC on 10 Aug.
FULL_DAY = [_punch(3, 30, "IN", day=10), _punch(12, 30, "OUT", day=10)]
TWO_HOURS = [_punch(3, 30, "IN", day=10), _punch(5, 30, "OUT", day=10)]


def _operating(day_type: str, **overrides: object):
    shift = _shift(operates_on_holiday=True, operates_on_weekly_off=True, is_ot_eligible=True)
    return _base_input(
        calendar_day_type=day_type,
        shift=shift,
        hour_bands=BANDS,
        ot_policy=_ot_policy(rate_rows=RATES),
        **overrides,
    )


@pytest.mark.parametrize("day_type", ["HOLIDAY", "WEEKLY_OFF"])
def test_holiday_operating_shift_no_show_is_not_paid_as_day_off(day_type: str) -> None:
    result = evaluate_day(_operating(day_type, policy=_policy(missing_punch_behaviour="ABSENT")))
    assert result.attendance_status == "ABSENT"
    assert result.paid_day_fraction == "0.00"
    assert result.lop_fraction == "1.00"


@pytest.mark.parametrize("day_type", ["HOLIDAY", "WEEKLY_OFF"])
def test_partial_work_on_operating_off_day_is_never_worse_than_a_no_show(day_type: str) -> None:
    no_show = evaluate_day(_operating(day_type, policy=_policy(missing_punch_behaviour="ABSENT")))
    partial = evaluate_day(
        _operating(day_type, policy=_policy(missing_punch_behaviour="ABSENT"), punches=TWO_HOURS)
    )
    assert partial.attendance_status == "ABSENT"  # 120 minutes: the ABSENT band, like any day
    assert float(partial.paid_day_fraction) >= float(no_show.paid_day_fraction)


def test_full_work_on_operating_holiday_is_ordinary_pay_with_no_holiday_premium() -> None:
    extra = [_punch(3, 30, "IN", day=10), _punch(14, 30, "OUT", day=10)]  # 2h past the shift
    result = evaluate_day(_operating("HOLIDAY", punches=extra))
    assert result.attendance_status == "PRESENT"
    assert result.paid_day_fraction == "1.00"
    assert result.worked_on_holiday is True
    assert result.ot_minutes_detected == 120
    assert result.ot_day_class == "NORMAL"
    assert result.ot_classification == "OT-N"


def test_non_operating_holiday_work_stays_all_overtime_at_the_holiday_class() -> None:
    shift = _shift(is_ot_eligible=True)
    result = evaluate_day(
        _base_input(
            calendar_day_type="HOLIDAY",
            shift=shift,
            hour_bands=BANDS,
            ot_policy=_ot_policy(rate_rows=RATES),
            punches=FULL_DAY,
        )
    )
    assert result.ot_minutes_detected == 540
    assert result.ot_day_class == "HOLIDAY"
    assert result.paid_day_fraction == "1.00"


def test_roster_week_off_wins_over_an_operating_shift() -> None:
    result = evaluate_day(_operating("WEEKLY_OFF", roster_week_off_override=True))
    assert result.attendance_status == "NOT_EXPECTED"


# --- SH-08 -----------------------------------------------------------------------------------


def _no_shift(**overrides: object):
    defaults: dict[str, object] = dict(
        shift=None,
        scheduled_start=None,
        scheduled_end=None,
        hour_bands=BANDS,
        policy=_policy(missing_shift_behaviour="ABSENT"),
    )
    defaults.update(overrides)
    return _base_input(**defaults)


@pytest.mark.parametrize("day_type", ["HOLIDAY", "WEEKLY_OFF", "SHUTDOWN"])
def test_no_shift_on_holiday_without_work_is_not_expected(day_type: str) -> None:
    result = evaluate_day(_no_shift(calendar_day_type=day_type))
    assert result.attendance_status == "NOT_EXPECTED"
    assert result.paid_day_fraction == "1.00"
    assert result.lop_fraction == "0.00"


def test_no_shift_working_day_without_punches_follows_missing_shift_behaviour() -> None:
    assert evaluate_day(_no_shift()).attendance_status == "ABSENT"
    incomplete = _no_shift(policy=_policy(missing_shift_behaviour="INCOMPLETE"))
    assert evaluate_day(incomplete).attendance_status == "INCOMPLETE"


def test_no_shift_one_minute_of_work_is_not_a_full_paid_day() -> None:
    punches = [_punch(4, 0, "IN", day=10), _punch(4, 1, "OUT", day=10)]
    result = evaluate_day(_no_shift(punches=punches))
    assert result.attendance_status == "ABSENT"
    assert result.paid_day_fraction == "0.00"


@pytest.mark.parametrize(
    ("hours", "status", "paid"),
    [(5, "HALF_DAY", "0.50"), (9, "PRESENT", "1.00")],
)
def test_no_shift_worked_minutes_use_hour_bands(hours: int, status: str, paid: str) -> None:
    punches = [_punch(3, 0, "IN", day=10), _punch(3 + hours, 0, "OUT", day=10)]
    result = evaluate_day(_no_shift(punches=punches))
    assert result.attendance_status == status
    assert result.paid_day_fraction == paid
    assert result.ot_minutes_detected == 0
    assert result.late_minutes == 0


def test_no_shift_work_on_a_day_off_keeps_the_paid_day_off() -> None:
    punches = [_punch(4, 0, "IN", day=10), _punch(5, 0, "OUT", day=10)]
    result = evaluate_day(_no_shift(calendar_day_type="WEEKLY_OFF", punches=punches))
    assert result.attendance_status == "PRESENT"
    assert result.paid_day_fraction == "1.00"
    assert result.lop_fraction == "0.00"
    assert result.worked_on_weekly_off is True


def test_no_shift_snapshot_names_the_reason() -> None:
    result = evaluate_day(_no_shift(calendar_day_type="HOLIDAY"))
    assert result.snapshot["terminal_reason"] == "no_shift_on_day_off"
