"""R-05 — an extra punch next to one in the same direction must not make a worked day INCOMPLETE,
while a same-direction pair far apart may be a real missed punch. No DB/HTTP."""

from datetime import UTC, datetime
from typing import Any

import pytest
from tests.unit.modules.attendance.test_calculation import _base_input, _policy, _punch, _shift

from hrms.modules.attendance.calculation import AttendanceCalculationResult, evaluate_day


def _day(punches: list[tuple[int, int, str]], **overrides: Any) -> AttendanceCalculationResult:
    inputs: dict[str, Any] = dict(
        shift=_shift(),
        policy=_policy(grace_in_minutes=15, grace_out_minutes=15),
        timezone="UTC",
        scheduled_start=datetime(2026, 8, 10, 9, 0, tzinfo=UTC),
        scheduled_end=datetime(2026, 8, 10, 18, 0, tzinfo=UTC),
        punches=[_punch(h, m, direction, day=10) for h, m, direction in punches],
    )
    inputs.update(overrides)
    return evaluate_day(_base_input(**inputs))


@pytest.mark.parametrize(
    ("punches", "worked"),
    [
        ([(9, 0, "IN"), (9, 5, "IN"), (18, 0, "OUT")], 540),
        ([(9, 0, "IN"), (18, 0, "OUT"), (18, 5, "OUT")], 545),
        ([(9, 0, "IN"), (9, 30, "IN"), (17, 30, "OUT"), (18, 0, "OUT")], 540),
    ],
)
def test_a_stray_punch_keeps_the_earliest_in_and_latest_out(
    punches: list[tuple[int, int, str]], worked: int
) -> None:
    result = _day(punches)
    assert result.attendance_status == "PRESENT"
    assert result.missing_punch is False
    assert result.worked_minutes == worked
    assert len(result.snapshot["stray_punch_ids"]) == len(punches) - 2


def test_a_stray_punch_cannot_hide_lateness() -> None:
    assert _day([(9, 30, "IN"), (9, 35, "IN"), (18, 0, "OUT")]).late_minutes == 15


@pytest.mark.parametrize(
    "punches",
    [
        [(9, 0, "IN"), (14, 0, "IN"), (18, 0, "OUT")],
        [(9, 0, "IN"), (13, 0, "OUT"), (18, 0, "OUT")],
        [(9, 0, "IN"), (9, 5, "IN")],
        [(18, 0, "OUT"), (18, 5, "OUT")],
    ],
)
def test_a_real_missing_punch_stays_incomplete(punches: list[tuple[int, int, str]]) -> None:
    result = _day(punches)
    assert result.attendance_status == "INCOMPLETE"
    assert result.missing_punch is True
