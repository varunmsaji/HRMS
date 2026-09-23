"""PAY-008 — every result records the engine version and the inputs `service.py` derived from
sibling days / other modules, so a recompute that differs can be explained. No DB/HTTP."""

from dataclasses import replace

from tests.unit.modules.attendance.test_calculation import _base_input
from tests.unit.modules.attendance.test_night_ot import _policy as _ot_policy

from hrms.modules.attendance.calculation import ENGINE_VERSION, LeaveOverlayEntry, evaluate_day


def test_snapshot_records_engine_version_and_derived_inputs() -> None:
    ot_policy = replace(
        _ot_policy("SHIFT_FLAG"), remaining_weekly_minutes=90, remaining_monthly_minutes=300
    )
    result = evaluate_day(
        _base_input(
            ot_policy=ot_policy,
            prior_late_days_in_window=2,
            prior_excess_break_days_in_window=1,
            leave_entries=[LeaveOverlayEntry(fraction="0.50", is_paid=True, half="FIRST")],
            pay_basis="DAILY_WAGE",
            on_duty_approved=True,
        )
    )
    assert result.snapshot["engine_version"] == ENGINE_VERSION
    derived = result.snapshot["derived_inputs"]
    assert derived["prior_late_days_in_window"] == 2
    assert derived["prior_excess_break_days_in_window"] == 1
    assert derived["remaining_weekly_ot_minutes"] == 90
    assert derived["remaining_monthly_ot_minutes"] == 300
    assert derived["leave_entries"] == [{"fraction": "0.50", "is_paid": True, "half": "FIRST"}]
    assert derived["pay_basis"] == "DAILY_WAGE"
    assert derived["on_duty_approved"] is True


def test_terminal_results_carry_the_snapshot_too() -> None:
    result = evaluate_day(_base_input(population_status="NOT_JOINED"))
    assert result.snapshot["engine_version"] == ENGINE_VERSION
    assert result.snapshot["derived_inputs"]["remaining_weekly_ot_minutes"] is None
