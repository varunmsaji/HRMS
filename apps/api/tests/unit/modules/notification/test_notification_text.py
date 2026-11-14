"""Wording and registry rules for workflow notifications (no database)."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from hrms.modules.notification.approvals import (
    LEAVE_FLOW,
    OVERTIME_FLOW,
    REGULARIZATION_FLOW,
    fmt_date,
)
from hrms.modules.notification.types import CATEGORIES, PRIORITIES, REGISTRY


def test_every_registered_type_has_a_known_category_and_priority() -> None:
    for code, kind in REGISTRY.items():
        assert code == kind.code
        assert kind.category in CATEGORIES
        assert kind.priority in PRIORITIES
        assert len(code) <= 64  # notification.type is VARCHAR(64)


def test_every_flow_uses_registered_types() -> None:
    for flow in (LEAVE_FLOW, REGULARIZATION_FLOW, OVERTIME_FLOW):
        assert REGISTRY[flow.pending.code] is flow.pending
        assert REGISTRY[flow.decided.code] is flow.decided
        assert flow.path.startswith("/app/")


def test_dates_read_naturally() -> None:
    assert fmt_date(date(2026, 9, 8)) == "8 Sep 2026"


def test_leave_summary_single_day_range_and_half_day() -> None:
    def row(start: date, end: date, days: str) -> SimpleNamespace:
        return SimpleNamespace(start_date=start, end_date=end, total_days=Decimal(days))

    one = date(2026, 9, 8)
    assert LEAVE_FLOW.describe(row(one, one, "1.00")) == "1 day of leave on 8 Sep 2026"
    assert LEAVE_FLOW.describe(row(one, one, "0.50")) == "0.5 days of leave on 8 Sep 2026"
    assert (
        LEAVE_FLOW.describe(row(one, date(2026, 9, 10), "3.00"))
        == "3 days of leave, 8 Sep 2026 to 10 Sep 2026"
    )


def test_overtime_summary_shows_hours_and_minutes() -> None:
    def row(minutes: int) -> SimpleNamespace:
        return SimpleNamespace(attendance_date=date(2026, 9, 8), minutes_detected=minutes)

    assert OVERTIME_FLOW.describe(row(90)) == "1h 30m of overtime on 8 Sep 2026"
    assert OVERTIME_FLOW.describe(row(120)) == "2h of overtime on 8 Sep 2026"
    assert OVERTIME_FLOW.describe(row(45)) == "45m of overtime on 8 Sep 2026"
