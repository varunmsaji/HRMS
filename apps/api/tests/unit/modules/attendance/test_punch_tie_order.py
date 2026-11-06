"""An OUT and an IN at the same instant (clocking out and straight back in) pair OUT first, however
the punches were loaded. Before this, the order of the two was left to the database, so the same
punches could pay a full day plus overtime or leave the morning IN unpaired."""

import pytest
from tests.unit.modules.attendance.test_calculation import _base_input, _ot_policy, _punch

from hrms.modules.attendance.calculation import evaluate_day


@pytest.mark.parametrize("in_first", [False, True])
def test_an_out_and_an_in_at_the_same_instant_pair_out_first(in_first: bool) -> None:
    # 09:00-19:00 and 19:00-19:30 IST against a 09:00-18:00 shift: 630 worked, 90 overtime.
    morning_in = _punch(3, 30, "IN", day=10)
    tied_out = _punch(13, 30, "OUT", day=10)
    tied_in = _punch(13, 30, "IN", day=10)
    evening_out = _punch(14, 0, "OUT", day=10)
    tie = [tied_in, tied_out] if in_first else [tied_out, tied_in]
    result = evaluate_day(
        _base_input(punches=[morning_in, *tie, evening_out], ot_policy=_ot_policy())
    )
    assert result.attendance_status == "PRESENT"
    assert result.worked_minutes == 630
    assert result.ot_minutes_detected == 90
