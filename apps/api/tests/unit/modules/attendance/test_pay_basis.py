"""BUS-001 (`docs/audits/PAYROLL_BUSINESS_DECISIONS.md` #1) — which days off are paid, by pay
basis and holiday flags. No DB/HTTP."""

from decimal import Decimal

from tests.unit.modules.attendance.test_calculation import _base_input, _punch

from hrms.modules.attendance.calculation import evaluate_day


def _fractions(result: object) -> tuple[str, str, str]:
    return (
        result.paid_day_fraction,  # type: ignore[attr-defined]
        result.lop_fraction,  # type: ignore[attr-defined]
        result.unpaid_off_fraction,  # type: ignore[attr-defined]
    )


def test_monthly_weekly_off_and_holidays_paid() -> None:
    for day_type, holiday_type in (
        ("WEEKLY_OFF", None),
        ("HOLIDAY", "COMPANY"),
        ("SHUTDOWN", None),
    ):
        result = evaluate_day(_base_input(calendar_day_type=day_type, holiday_type=holiday_type))
        assert result.attendance_status == "NOT_EXPECTED"
        assert _fractions(result) == ("1.00", "0.00", "0.00"), day_type


def test_daily_wage_weekly_off_company_holiday_and_shutdown_unpaid() -> None:
    for day_type, holiday_type in (
        ("WEEKLY_OFF", None),
        ("HOLIDAY", "COMPANY"),
        ("SHUTDOWN", None),
    ):
        result = evaluate_day(
            _base_input(
                calendar_day_type=day_type, holiday_type=holiday_type, pay_basis="DAILY_WAGE"
            )
        )
        assert _fractions(result) == ("0.00", "0.00", "1.00"), day_type


def test_daily_wage_public_and_substitute_holidays_paid() -> None:
    for holiday_type in ("PUBLIC", "SUBSTITUTE"):
        result = evaluate_day(
            _base_input(
                calendar_day_type="HOLIDAY", holiday_type=holiday_type, pay_basis="DAILY_WAGE"
            )
        )
        assert _fractions(result) == ("1.00", "0.00", "0.00"), holiday_type


def test_daily_wage_public_holiday_on_weekly_off_follows_holiday_rule() -> None:
    result = evaluate_day(
        _base_input(
            calendar_day_type="WEEKLY_OFF",
            holiday_on_weekly_off=True,
            holiday_type="PUBLIC",
            pay_basis="DAILY_WAGE",
        )
    )
    assert _fractions(result) == ("1.00", "0.00", "0.00")


def test_holiday_marked_unpaid_is_unpaid_even_for_monthly() -> None:
    result = evaluate_day(
        _base_input(calendar_day_type="HOLIDAY", holiday_type="PUBLIC", holiday_is_paid=False)
    )
    assert _fractions(result) == ("0.00", "0.00", "1.00")


def test_daily_wage_worked_weekly_off_is_paid_for_the_work() -> None:
    from dataclasses import replace

    base = _base_input(
        calendar_day_type="WEEKLY_OFF",
        pay_basis="DAILY_WAGE",
        punches=[_punch(3, 30, "IN", day=10), _punch(12, 30, "OUT", day=10)],
    )
    result = evaluate_day(replace(base, shift=replace(base.shift, operates_on_weekly_off=True)))
    assert result.attendance_status == "PRESENT"
    assert _fractions(result) == ("1.00", "0.00", "0.00")


def test_daily_wage_half_weekly_off_off_half_unpaid() -> None:
    worked = evaluate_day(
        _base_input(
            calendar_day_type="WEEKLY_OFF",
            weekly_off_fraction="0.50",
            pay_basis="DAILY_WAGE",
            punches=[_punch(3, 30, "IN", day=10), _punch(8, 0, "OUT", day=10)],
        )
    )
    assert _fractions(worked) == ("0.50", "0.00", "0.50")
    for fractions in (_fractions(worked),):
        assert sum(Decimal(f) for f in fractions) == Decimal("1.00")
