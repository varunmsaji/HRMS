"""Unit tests for the CTC → component breakup (payroll plan Phase 5.1, decisions D1/D2). No
DB/HTTP."""

from decimal import Decimal

import pytest

from hrms.modules.payroll.breakup import (
    BreakupError,
    StructureLine,
    compute_breakup,
    monthly_from_annual,
)


def _standard(hra: str = "40") -> list[StructureLine]:
    """D1 default: Basic 50 % of gross, HRA 40 % of Basic, Special Allowance balancing; D2 —
    employer PF (12 % of Basic, capped at ₹1,800) inside CTC for PF-applicable employees."""
    return [
        StructureLine(
            "BASIC", "Basic", "EARNING", "PERCENTAGE_OF_GROSS", Decimal("50"), display_order=10
        ),
        StructureLine(
            "HRA",
            "HRA",
            "EARNING",
            "PERCENTAGE_OF_COMPONENT",
            Decimal(hra),
            base_component_code="BASIC",
            display_order=20,
        ),
        StructureLine("SPECIAL", "Special Allowance", "EARNING", "BALANCING", display_order=30),
        StructureLine(
            "EMPLOYER_PF",
            "Employer PF",
            "EMPLOYER_CONTRIBUTION",
            "PERCENTAGE_OF_COMPONENT",
            Decimal("12"),
            base_component_code="BASIC",
            max_monthly_minor=180_000,
            applies_when="PF_APPLICABLE",
            display_order=90,
        ),
    ]


def _amounts(breakup) -> dict[str, int]:  # type: ignore[no-untyped-def]
    return {line.component_code: line.monthly_minor for line in breakup.lines}


def test_standard_breakup_with_pf_capped() -> None:
    # ₹12,00,000 a year = ₹1,00,000 a month.
    breakup = compute_breakup(
        _standard(), annual_ctc_minor=120_000_000, pf_applicable=True, esi_applicable=False
    )
    amounts = _amounts(breakup)
    assert amounts["EMPLOYER_PF"] == 180_000  # 12 % of Basic exceeds the ₹1,800 cap
    assert breakup.gross_monthly_minor == 10_000_000 - 180_000
    assert amounts["BASIC"] == 4_910_000  # 50 % of ₹98,200
    assert amounts["HRA"] == 1_964_000  # 40 % of Basic
    assert amounts["SPECIAL"] == breakup.gross_monthly_minor - 4_910_000 - 1_964_000
    assert breakup.gross_monthly_minor + breakup.employer_contributions_monthly_minor == (
        breakup.monthly_ctc_minor
    )


def test_uncapped_pf_is_solved_against_gross() -> None:
    # ₹3,00,000 a year = ₹25,000 a month: Basic = 50 % g, PF = 6 % g → g ≈ 25,000 / 1.06.
    breakup = compute_breakup(
        _standard(), annual_ctc_minor=30_000_000, pf_applicable=True, esi_applicable=False
    )
    amounts = _amounts(breakup)
    assert amounts["EMPLOYER_PF"] < 180_000
    assert amounts["EMPLOYER_PF"] == round(amounts["BASIC"] * 0.12 / 100) * 100
    assert breakup.gross_monthly_minor + amounts["EMPLOYER_PF"] == 2_500_000
    assert amounts["BASIC"] + amounts["HRA"] + amounts["SPECIAL"] == breakup.gross_monthly_minor
    assert amounts["SPECIAL"] >= 0


def test_pf_line_skipped_when_not_applicable() -> None:
    breakup = compute_breakup(
        _standard(), annual_ctc_minor=120_000_000, pf_applicable=False, esi_applicable=False
    )
    assert "EMPLOYER_PF" not in _amounts(breakup)
    assert breakup.gross_monthly_minor == breakup.monthly_ctc_minor
    assert _amounts(breakup)["BASIC"] == 5_000_000


def test_metro_hra() -> None:
    breakup = compute_breakup(
        _standard(hra="50"),
        annual_ctc_minor=120_000_000,
        pf_applicable=False,
        esi_applicable=False,
    )
    amounts = _amounts(breakup)
    assert amounts["HRA"] == amounts["BASIC"] // 2


def test_lines_are_rupee_rounded_and_annual_is_twelve_months() -> None:
    breakup = compute_breakup(
        _standard(), annual_ctc_minor=77_777_700, pf_applicable=True, esi_applicable=False
    )
    for line in breakup.lines:
        if line.component_code != "SPECIAL":
            assert line.monthly_minor % 100 == 0
        assert line.annual_minor == line.monthly_minor * 12
    assert breakup.monthly_ctc_minor == monthly_from_annual(77_777_700)


def test_fixed_amounts_larger_than_ctc_rejected() -> None:
    lines = [
        StructureLine("BASIC", "Basic", "EARNING", "FIXED", amount_monthly_minor=5_000_000),
        StructureLine("SPECIAL", "Special", "EARNING", "BALANCING"),
    ]
    with pytest.raises(BreakupError, match="too small"):
        compute_breakup(
            lines, annual_ctc_minor=12_000_000, pf_applicable=False, esi_applicable=False
        )


@pytest.mark.parametrize(
    "lines, message",
    [
        (
            [StructureLine("BASIC", "Basic", "EARNING", "FIXED", amount_monthly_minor=1)],
            "exactly one BALANCING",
        ),
        (
            [
                StructureLine("A", "A", "EARNING", "BALANCING"),
                StructureLine("B", "B", "EARNING", "BALANCING"),
            ],
            "exactly one BALANCING",
        ),
        ([StructureLine("A", "A", "EMPLOYER_CONTRIBUTION", "BALANCING")], "must be an earning"),
        (
            [
                StructureLine("S", "S", "EARNING", "BALANCING"),
                StructureLine("D", "D", "DEDUCTION", "FIXED", amount_monthly_minor=1),
            ],
            "deductions",
        ),
        (
            [
                StructureLine("S", "S", "EARNING", "BALANCING"),
                StructureLine(
                    "H",
                    "H",
                    "EARNING",
                    "PERCENTAGE_OF_COMPONENT",
                    Decimal("10"),
                    base_component_code="MISSING",
                ),
            ],
            "not in this structure",
        ),
        (
            [
                StructureLine("S", "S", "EARNING", "BALANCING"),
                StructureLine(
                    "H",
                    "H",
                    "EARNING",
                    "PERCENTAGE_OF_COMPONENT",
                    Decimal("10"),
                    base_component_code="S",
                ),
            ],
            "non-balancing earning",
        ),
        (
            [
                StructureLine("S", "S", "EARNING", "BALANCING"),
                StructureLine(
                    "A",
                    "A",
                    "EARNING",
                    "PERCENTAGE_OF_COMPONENT",
                    Decimal("10"),
                    base_component_code="B",
                ),
                StructureLine(
                    "B",
                    "B",
                    "EARNING",
                    "PERCENTAGE_OF_COMPONENT",
                    Decimal("10"),
                    base_component_code="A",
                ),
            ],
            "cycle",
        ),
        (
            [
                StructureLine("S", "S", "EARNING", "BALANCING"),
                StructureLine("P", "P", "EARNING", "PERCENTAGE_OF_CTC", Decimal("120")),
            ],
            "0 to 100",
        ),
        (
            [
                StructureLine("S", "S", "EARNING", "BALANCING"),
                StructureLine(
                    "E", "E", "EMPLOYER_CONTRIBUTION", "PERCENTAGE_OF_GROSS", Decimal("3")
                ),
            ],
            "only an earning",
        ),
    ],
)
def test_invalid_structures_rejected(lines: list[StructureLine], message: str) -> None:
    with pytest.raises(BreakupError, match=message):
        compute_breakup(lines, annual_ctc_minor=12_000_000, pf_applicable=True, esi_applicable=True)
