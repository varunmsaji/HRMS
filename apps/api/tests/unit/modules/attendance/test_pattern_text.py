"""The words used for a pattern alert in emails and lists."""

from datetime import date
from uuid import uuid4

from hrms.modules.attendance.patterns import PatternAlertRead, PatternThresholds, describe_alert

T = PatternThresholds(
    window_days=30,
    weekday_window_days=56,
    late_days=5,
    absent_days=4,
    incomplete_days=3,
    weekday_absences=3,
)


def _alert(kind: str, count: int, weekday: int | None = None) -> PatternAlertRead:
    return PatternAlertRead(
        employee_id=uuid4(),
        kind=kind,
        count=count,
        dates=[date(2026, 11, 24)],
        weekday=weekday,  # type: ignore[arg-type]
    )


def test_each_kind_is_described_with_its_count_and_window() -> None:
    assert describe_alert(_alert("repeat_late", 6), T) == "late on 6 days in the last 30"
    assert describe_alert(_alert("frequent_absence", 4), T) == "absent on 4 days in the last 30"
    assert (
        describe_alert(_alert("repeat_missing_punch", 3), T)
        == "missing a punch on 3 days in the last 30"
    )


def test_a_weekday_pattern_names_the_weekday_and_its_longer_window() -> None:
    assert (
        describe_alert(_alert("repeat_absent_weekday", 3, 0), T)
        == "absent on 3 Mondays in the last 56 days"
    )
    assert (
        describe_alert(_alert("repeat_absent_weekday", 4, 4), T)
        == "absent on 4 Fridays in the last 56 days"
    )
