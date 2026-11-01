from datetime import UTC, datetime

from hrms.modules.attendance.regularization_decision_center import (
    RequestedPunch,
    requested_span_minutes,
)


def _t(h: int, m: int = 0) -> datetime:
    return datetime(2026, 10, 5, h, m, tzinfo=UTC)


def test_span_uses_requested_punches_over_recorded() -> None:
    punches = [
        RequestedPunch(direction="IN", time=_t(9)),
        RequestedPunch(direction="OUT", time=_t(18)),
    ]
    assert requested_span_minutes(punches, _t(10), _t(17)) == 540


def test_missing_side_falls_back_to_the_recorded_punch() -> None:
    punches = [RequestedPunch(direction="OUT", time=_t(18))]
    assert requested_span_minutes(punches, _t(9, 30), None) == 510


def test_unknown_side_or_non_positive_span_is_none() -> None:
    assert requested_span_minutes([], None, None) is None
    assert (
        requested_span_minutes([RequestedPunch(direction="OUT", time=_t(8))], _t(9), None) is None
    )
