"""Unit tests for the pure income-tax (TDS) computation (payroll plan Phase 5.6, FR-PAY-011,
new regime only — see `income_tax.py` for the full v1 scope)."""

from datetime import date
from typing import Any

from hrms.modules.payroll.income_tax import (
    compute_tds,
    financial_year_start,
    months_remaining_in_fy,
)

_TDS_NEW = {
    "regime": "NEW",
    "standard_deduction_minor": 7_500_000,
    "rebate_taxable_income_limit_minor": 120_000_000,
    "cess_percent": "4",
    "surcharge_warning_income_minor": 500_000_000,
    "slabs": [
        {"min_minor": 0, "max_minor": 40_000_000, "percent": "0"},
        {"min_minor": 40_000_000, "max_minor": 80_000_000, "percent": "5"},
        {"min_minor": 80_000_000, "max_minor": 120_000_000, "percent": "10"},
        {"min_minor": 120_000_000, "max_minor": 160_000_000, "percent": "15"},
        {"min_minor": 160_000_000, "max_minor": 200_000_000, "percent": "20"},
        {"min_minor": 200_000_000, "max_minor": 240_000_000, "percent": "25"},
        {"min_minor": 240_000_000, "max_minor": None, "percent": "30"},
    ],
}  # fmt: skip


def _rate(*, verified: bool = True, parameters: dict[str, Any] = _TDS_NEW) -> dict[str, Any]:
    return {"id": "tds-rate", "verified": verified, "parameters": parameters}


def _profile(*, regime: str | None = "NEW", has_pan: bool = True) -> dict[str, Any]:
    return {"tax_regime": regime, "has_pan": has_pan}


def test_financial_year_and_months_remaining() -> None:
    assert financial_year_start(date(2026, 9, 1)) == date(2026, 4, 1)
    assert financial_year_start(date(2026, 2, 1)) == date(2025, 4, 1)
    assert months_remaining_in_fy(date(2026, 4, 1)) == 12
    assert months_remaining_in_fy(date(2026, 9, 1)) == 7
    assert months_remaining_in_fy(date(2027, 3, 1)) == 1


def test_no_profile_is_silent() -> None:
    result = compute_tds(
        period_month=date(2026, 9, 1),
        this_month_taxable_earnings_minor=50_00_000_00,
        ytd_taxable_earnings_minor=0,
        ytd_tds_deducted_minor=0,
        profile=None,
        rate=_rate(),
    )
    assert result.lines == []
    assert result.issues == []


def test_below_rebate_threshold_owes_nothing_even_if_unverified() -> None:
    """A comfortably-under-threshold employee shouldn't be blocked by an unverified slab table
    they'll never actually need (mirrors why PF/ESI/PT only need verification when applicable)."""
    result = compute_tds(
        period_month=date(2026, 9, 1),
        this_month_taxable_earnings_minor=58_200_00,  # ~₹6,98,400/yr projected over 7 months
        ytd_taxable_earnings_minor=0,
        ytd_tds_deducted_minor=0,
        profile=_profile(),
        rate=_rate(verified=False),
    )
    assert result.lines == []
    assert result.issues == []


def test_above_threshold_is_taxed_with_cess() -> None:
    """₹3,00,000/month, first month of the FY: projected annual = 3,00,000 × 12 = ₹36,00,000,
    taxable after standard deduction = ₹35,25,000. Slab tax: 0 on 0-4L, 5%×4L=20,000, 10%×4L=
    40,000, 15%×4L=60,000, 20%×4L=80,000, 25%×4L=1,00,000, 30% on the remaining ₹11,25,000 =
    3,37,500 → slab tax ₹6,37,500; + 4% cess ₹25,500 = ₹6,63,000 annual tax. First month TDS =
    6,63,000 ÷ 12 = ₹55,250."""
    result = compute_tds(
        period_month=date(2026, 4, 1),
        this_month_taxable_earnings_minor=3_00_000_00,
        ytd_taxable_earnings_minor=0,
        ytd_tds_deducted_minor=0,
        profile=_profile(),
        rate=_rate(),
    )
    assert not result.issues
    assert len(result.lines) == 1
    line = result.lines[0]
    assert line.component_code == "TDS_EMPLOYEE"
    assert line.amount_minor == 55_250_00
    assert line.trace["annual_tax_minor"] == 6_63_000_00
    assert line.trace["rebate_applied"] is False


def test_unverified_rate_blocks_only_when_tax_is_actually_due() -> None:
    result = compute_tds(
        period_month=date(2026, 4, 1),
        this_month_taxable_earnings_minor=3_00_000_00,
        ytd_taxable_earnings_minor=0,
        ytd_tds_deducted_minor=0,
        profile=_profile(),
        rate=_rate(verified=False),
    )
    assert {i.code for i in result.issues} == {"STATUTORY_UNVERIFIED"}
    assert result.issues[0].severity == "ERROR"
    assert len(result.lines) == 1  # still shown, just blocks approval


def test_ytd_reduces_the_remaining_months_liability() -> None:
    """Same annual liability as the cess test (₹6,63,000), but ₹3,00,000 already deducted in
    earlier months and 6 months left (not 12) — the rest is spread over what remains."""
    result = compute_tds(
        period_month=date(2026, 10, 1),  # 6 months remain: Oct-Mar
        this_month_taxable_earnings_minor=3_00_000_00,
        ytd_taxable_earnings_minor=6 * 3_00_000_00,
        ytd_tds_deducted_minor=3_00_000_00,
        profile=_profile(),
        rate=_rate(),
    )
    assert not result.issues
    line = result.lines[0]
    assert line.trace["annual_tax_minor"] == 6_63_000_00
    assert line.amount_minor == (6_63_000_00 - 3_00_000_00) // 6


def test_old_regime_blocks_and_deducts_nothing() -> None:
    result = compute_tds(
        period_month=date(2026, 9, 1),
        this_month_taxable_earnings_minor=3_00_000_00,
        ytd_taxable_earnings_minor=0,
        ytd_tds_deducted_minor=0,
        profile=_profile(regime="OLD"),
        rate=_rate(),
    )
    assert result.lines == []
    assert {i.code for i in result.issues} == {"TDS_OLD_REGIME_NOT_SUPPORTED"}
    assert result.issues[0].severity == "ERROR"


def test_missing_pan_blocks_when_tax_is_due_but_not_when_it_isnt() -> None:
    taxed = compute_tds(
        period_month=date(2026, 4, 1),
        this_month_taxable_earnings_minor=3_00_000_00,
        ytd_taxable_earnings_minor=0,
        ytd_tds_deducted_minor=0,
        profile=_profile(has_pan=False),
        rate=_rate(),
    )
    assert "PAN_MISSING_FOR_TDS" in {i.code for i in taxed.issues}
    assert len(taxed.lines) == 1  # shown so HR can see what's owed, but blocks approval

    untaxed = compute_tds(
        period_month=date(2026, 9, 1),
        this_month_taxable_earnings_minor=58_200_00,
        ytd_taxable_earnings_minor=0,
        ytd_tds_deducted_minor=0,
        profile=_profile(has_pan=False),
        rate=_rate(),
    )
    assert untaxed.issues == []


def test_high_income_flags_surcharge_without_computing_it() -> None:
    result = compute_tds(
        period_month=date(2026, 4, 1),
        this_month_taxable_earnings_minor=6_00_000_00,  # projects to ₹72,00,000/yr
        ytd_taxable_earnings_minor=0,
        ytd_tds_deducted_minor=0,
        profile=_profile(),
        rate=_rate(),
    )
    assert "TDS_SURCHARGE_NOT_COMPUTED" in {i.code for i in result.issues}


def test_no_tax_regime_set_defaults_to_new_with_a_warning() -> None:
    result = compute_tds(
        period_month=date(2026, 9, 1),
        this_month_taxable_earnings_minor=58_200_00,
        ytd_taxable_earnings_minor=0,
        ytd_tds_deducted_minor=0,
        profile=_profile(regime=None),
        rate=_rate(),
    )
    assert {i.code for i in result.issues} == {"TDS_REGIME_NOT_SET"}
    assert result.issues[0].severity == "WARNING"
