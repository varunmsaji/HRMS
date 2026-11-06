"""R-16 (owner, 6 Nov 2026): a day can be late and still earn overtime, but overtime is only time
worked beyond the shift's total hours. Arriving late and staying late first makes up the shift;
lateness is handled by the late rules, not by overtime. Overtime exists only with an overtime
policy.

Shift 09:00-18:00 Asia/Kolkata with no break: 540 scheduled minutes. Punches are in UTC
(IST - 5:30). These pin the current behaviour; they are not a change to it."""

import pytest
from tests.unit.modules.attendance.test_calculation import _base_input, _ot_policy, _punch

from hrms.modules.attendance.calculation import evaluate_day


@pytest.mark.parametrize(
    ("out_hour", "out_minute", "worked", "overtime"),
    [
        (13, 30, 540, 0),  # 10:00-19:00 IST: the late hour is made up, no overtime
        (14, 0, 570, 30),  # 10:00-19:30 IST: only the 30 minutes beyond 9 hours count
        (12, 30, 480, 0),  # 10:00-18:00 IST: short of the shift, no overtime
    ],
)
def test_a_late_day_earns_overtime_only_beyond_the_shift_hours(
    out_hour: int, out_minute: int, worked: int, overtime: int
) -> None:
    result = evaluate_day(
        _base_input(
            punches=[
                _punch(4, 30, "IN", day=10),  # 10:00 IST, an hour late
                _punch(out_hour, out_minute, "OUT", day=10),
            ],
            ot_policy=_ot_policy(),
        )
    )
    assert result.is_late is True
    assert result.late_minutes == 50  # an hour late, less the 10-minute grace
    assert result.worked_minutes == worked
    assert result.ot_minutes_detected == overtime
    assert result.is_overtime is (overtime > 0)


def test_without_an_overtime_policy_a_long_late_day_has_no_overtime() -> None:
    result = evaluate_day(
        _base_input(
            punches=[_punch(4, 30, "IN", day=10), _punch(14, 0, "OUT", day=10)],
            ot_policy=None,
        )
    )
    assert result.is_late is True
    assert result.worked_minutes == 570
    assert result.ot_minutes_detected == 0
    assert result.is_overtime is False
