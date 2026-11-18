"""SH-04 — split shifts: blocks placed in sequence (a block after midnight belongs to the next
calendar day), scheduled minutes are the sum of the blocks, and overtime is measured against
them. Engine 13."""

from datetime import UTC, date, datetime, time, timedelta
from uuid import uuid4

from tests.unit.modules.attendance.test_calculation import _base_input, _ot_policy, _shift

from hrms.modules.attendance.calculation import (
    PunchData,
    ShiftDutyBlockData,
    evaluate_day,
    place_duty_blocks,
    resolve_schedule_window,
    split_scheduled_minutes,
)

DAY = date(2026, 8, 10)


def _block(seq: int, start: time, end: time) -> ShiftDutyBlockData:
    return ShiftDutyBlockData(
        sequence=seq, start_time=start, end_time=end, crosses_midnight=end <= start
    )


def _at(day_offset: int, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(DAY + timedelta(days=day_offset), time(hour, minute), tzinfo=UTC)


def _p(day_offset: int, hour: int, minute: int, direction: str) -> PunchData:
    return PunchData(id=uuid4(), punch_time=_at(day_offset, hour, minute), direction=direction)


def _evaluate(blocks: list[ShiftDutyBlockData], punches: list[PunchData], **overrides: object):
    shift = _shift(shift_type="SPLIT", duty_blocks=blocks, is_ot_eligible=True)
    window = resolve_schedule_window(
        attendance_date=DAY,
        tz_name="UTC",
        shift=shift,
        start_time=None,
        end_time=None,
        window_start=None,
        window_end=None,
    )
    return evaluate_day(
        _base_input(
            shift=shift,
            timezone="UTC",
            scheduled_start=window.scheduled_start,
            scheduled_end=window.scheduled_end,
            punches=punches,
            ot_policy=_ot_policy(),
            **overrides,
        )
    )


DAY_BLOCKS = [_block(1, time(8), time(12)), _block(2, time(16), time(20))]
NIGHT_BLOCKS = [_block(1, time(20), time(23)), _block(2, time(1), time(4))]


def test_after_midnight_block_is_placed_on_the_next_day() -> None:
    placed = place_duty_blocks(attendance_date=DAY, tz_name="UTC", blocks=NIGHT_BLOCKS)
    assert placed == [(_at(0, 20), _at(0, 23)), (_at(1, 1), _at(1, 4))]
    assert split_scheduled_minutes(placed) == 360


def test_block_crossing_midnight_then_another_block() -> None:
    blocks = [_block(1, time(22), time(2)), _block(2, time(3), time(6))]
    placed = place_duty_blocks(attendance_date=DAY, tz_name="UTC", blocks=blocks)
    assert placed == [(_at(0, 22), _at(1, 2)), (_at(1, 3), _at(1, 6))]


def test_blocks_are_placed_by_sequence_not_list_order() -> None:
    placed = place_duty_blocks(
        attendance_date=DAY, tz_name="UTC", blocks=list(reversed(DAY_BLOCKS))
    )
    assert placed[0] == (_at(0, 8), _at(0, 12))


def test_two_blocks_on_one_day_full_attendance() -> None:
    result = _evaluate(
        DAY_BLOCKS,
        [_p(0, 8, 0, "IN"), _p(0, 12, 0, "OUT"), _p(0, 16, 0, "IN"), _p(0, 20, 0, "OUT")],
    )
    assert result.attendance_status == "PRESENT"
    assert result.scheduled_minutes == 480
    assert result.worked_minutes == 480
    assert result.ot_minutes_detected == 0


def test_split_shift_calculates_scheduled_minutes_and_overtime() -> None:
    """Regression SH-04: overtime after the final block is detected (was always 0)."""
    result = _evaluate(
        DAY_BLOCKS,
        [_p(0, 8, 0, "IN"), _p(0, 12, 0, "OUT"), _p(0, 16, 0, "IN"), _p(0, 22, 0, "OUT")],
    )
    assert result.scheduled_minutes == 480
    assert result.worked_minutes == 600
    assert result.ot_minutes_detected == 120
    assert result.ot_day_class == "NORMAL"


def test_split_shift_with_block_after_midnight_is_fully_worked() -> None:
    """Regression SH-04: the 01:00-04:00 block was placed on the attendance date and missed."""
    result = _evaluate(
        NIGHT_BLOCKS,
        [_p(0, 20, 0, "IN"), _p(0, 23, 0, "OUT"), _p(1, 1, 0, "IN"), _p(1, 4, 0, "OUT")],
    )
    assert result.snapshot["split_missed_blocks"] == 0
    assert result.attendance_status == "PRESENT"
    assert result.scheduled_minutes == 360


def test_missing_one_block_applies_the_policy_behaviour() -> None:
    result = _evaluate(DAY_BLOCKS, [_p(0, 8, 0, "IN"), _p(0, 12, 0, "OUT")])
    assert result.snapshot["split_missed_blocks"] == 1
    assert result.attendance_status == "HALF_DAY"  # split_shift_missed_block_behaviour default


def test_partly_worked_block_counts_as_worked_open_policy_p11() -> None:
    """P-11 is undecided: a block with any overlap counts as attended. Worked minutes are real."""
    result = _evaluate(
        DAY_BLOCKS,
        [_p(0, 8, 0, "IN"), _p(0, 12, 0, "OUT"), _p(0, 18, 0, "IN"), _p(0, 20, 0, "OUT")],
    )
    assert result.snapshot["split_missed_blocks"] == 0
    assert result.worked_minutes == 360
    assert result.ot_minutes_detected == 0
