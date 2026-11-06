"""F11 (D-5): an on-duty day earns overtime only when the policy requires punches on it. When it
does not, the day is a fully paid ON_DUTY day and punches on it earn no overtime.

Audit case OD-08: shift 09:00-18:00 Asia/Kolkata (540 minutes), punches 09:00-20:00 IST, so 120
minutes beyond the shift. Punches are in UTC (IST - 5:30)."""

import pytest
from tests.unit.modules.attendance.test_calculation import (
    _base_input,
    _ot_policy,
    _policy,
    _punch,
)

from hrms.modules.attendance.calculation import ENGINE_VERSION, evaluate_day

_LONG_DAY = [_punch(3, 30, "IN", day=10), _punch(14, 30, "OUT", day=10)]


@pytest.mark.parametrize(
    ("requires_punch", "status", "overtime"),
    [
        (False, "ON_DUTY", 0),  # paid as on duty: no overtime on top
        (True, "PRESENT", 120),  # the punches decide the day, overtime included (must not change)
    ],
)
def test_on_duty_overtime_depends_on_whether_punches_are_required(
    requires_punch: bool, status: str, overtime: int
) -> None:
    result = evaluate_day(
        _base_input(
            policy=_policy(on_duty_requires_punch=requires_punch),
            punches=_LONG_DAY,
            on_duty_approved=True,
            ot_policy=_ot_policy(),
        )
    )
    assert result.attendance_status == status
    assert result.paid_day_fraction == "1.00"
    assert result.ot_minutes_detected == overtime
    assert result.is_overtime is (overtime > 0)
    if overtime == 0:
        assert result.ot_pending is False
        assert result.ot_day_class is None
        assert result.comp_off_minutes_earned == 0


def test_without_on_duty_the_same_day_earns_overtime() -> None:
    result = evaluate_day(_base_input(punches=_LONG_DAY, ot_policy=_ot_policy()))
    assert result.attendance_status == "PRESENT"
    assert result.ot_minutes_detected == 120


def test_engine_version_records_the_on_duty_overtime_change() -> None:
    assert ENGINE_VERSION >= 9
