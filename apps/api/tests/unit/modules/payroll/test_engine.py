"""Unit tests for the pure pay-run engine (payroll plan Phase 5.2, decisions 2/17, D3–D8)."""

from datetime import date
from decimal import Decimal

from hrms.modules.payroll.engine import (
    ArrearsInput,
    EmployeeInput,
    EncashmentInput,
    OvertimeInput,
    PaidLine,
    Segment,
    SegmentLine,
    compute_employee,
    employee_input_from_snapshot,
)

_PF = {
    "employee_percent": "12",
    "employer_percent": "12",
    "eps_percent": "8.33",
    "wage_ceiling_minor": 1_500_000,
    "edli_percent": "0",
    "admin_percent": "0",
    "eps_age_limit": 58,
}

_BANK = {"payment_mode": "BANK", "account_last4": "1234"}
# A statutory block for an employee with no statutory profile — nothing deducted.
_NO_STATUTORY = {"month_end": date(2026, 9, 30), "profile": None, "employee": {}, "rates": {}}


def _lines(basic: int, hra: int, special: int, *, special_prorated: bool = True) -> tuple:
    return (
        SegmentLine("BASIC", "Basic", "EARNING", basic, True, 10),
        SegmentLine("HRA", "House Rent Allowance", "EARNING", hra, True, 20),
        SegmentLine("SPECIAL_ALLOWANCE", "Special Allowance", "EARNING", special,
                    special_prorated, 30),
    )  # fmt: skip


def _segment(
    start: date, end: date, lines: tuple, *, pf: bool = False, basis: str = "MONTHLY"
) -> Segment:
    return Segment(
        date_from=start,
        date_to=end,
        employed_days=(end - start).days + 1,
        pay_basis=basis,
        valid=True,
        pf_applicable=pf,
        lines=lines,
    )


def _september(lines: tuple, **kwargs: object) -> Segment:
    return _segment(date(2026, 9, 1), date(2026, 9, 30), lines, **kwargs)  # type: ignore[arg-type]


def _input(segments: tuple, paid: str | None, **kwargs: object) -> EmployeeInput:
    return EmployeeInput(
        days_in_month=30,
        paid_days=Decimal(paid) if paid is not None else None,
        has_summary=True,
        segments=segments,
        bank=kwargs.pop("bank", _BANK),  # type: ignore[arg-type]
        statutory=kwargs.pop("statutory", _NO_STATUTORY),  # type: ignore[arg-type]
        **kwargs,  # type: ignore[arg-type]
    )


def _amounts(result: object) -> dict[str, int]:
    return {line.component_code: line.amount_minor for line in result.lines}  # type: ignore[attr-defined]


def _codes(result: object) -> set[str]:
    return {issue.code for issue in result.issues}  # type: ignore[attr-defined]


def test_full_month_pays_the_monthly_amounts() -> None:
    result = compute_employee(_input((_september(_lines(3_000_000, 1_200_000, 1_800_000)),), "30"))
    assert _amounts(result) == {
        "BASIC": 3_000_000,
        "HRA": 1_200_000,
        "SPECIAL_ALLOWANCE": 1_800_000,
    }
    assert result.gross_minor == result.net_minor == 6_000_000
    assert result.rounding_minor == 0
    assert not result.issues


def test_lop_is_excluded_by_calendar_day_proration() -> None:
    """Decision 17 — monthly × paid days ÷ days in month; no separate LOP line."""
    result = compute_employee(_input((_september(_lines(3_000_000, 1_200_000, 1_800_000)),), "27"))
    amounts = _amounts(result)
    assert amounts["BASIC"] == 2_700_000
    assert amounts["HRA"] == 1_080_000
    assert amounts["SPECIAL_ALLOWANCE"] == 1_620_000
    assert "LOP" not in amounts
    basic = next(line for line in result.lines if line.component_code == "BASIC")
    assert basic.full_monthly_minor == 3_000_000
    assert basic.trace["paid_days"] == "27"


def test_mid_month_revision_pays_each_segment_at_its_own_rate() -> None:
    first = _segment(date(2026, 9, 1), date(2026, 9, 15), _lines(3_000_000, 0, 0))
    second = _segment(date(2026, 9, 16), date(2026, 9, 30), _lines(3_600_000, 0, 0))
    result = compute_employee(_input((first, second), "30"))
    # 3,000,000 × 15/30 + 3,600,000 × 15/30
    assert _amounts(result)["BASIC"] == 3_300_000
    basic = next(line for line in result.lines if line.component_code == "BASIC")
    assert len(basic.trace["parts"]) == 2


def test_partial_month_joiner_and_non_prorated_component() -> None:
    """Joined on the 21st: 10 employed days, all paid. A prorated component pays 10/30; a
    component that is not prorated pays in full."""
    segment = _segment(
        date(2026, 9, 21),
        date(2026, 9, 30),
        _lines(3_000_000, 0, 600_000, special_prorated=False),
    )
    result = compute_employee(_input((segment,), "10"))
    amounts = _amounts(result)
    assert amounts["BASIC"] == 1_000_000
    assert amounts["SPECIAL_ALLOWANCE"] == 600_000


def test_daily_wage_pays_rate_times_paid_days() -> None:
    segment = Segment(
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 30),
        employed_days=30,
        pay_basis="DAILY_WAGE",
        valid=True,
        daily_rate_minor=80_000,
    )
    result = compute_employee(_input((segment,), "24.5"))
    assert _amounts(result) == {"DAILY_WAGES": 1_960_000}
    assert result.net_minor == 1_960_000


def test_overtime_uses_basic_hourly_rate_and_multiplier() -> None:
    """D3 — Basic ₹30,000 over 30 days × 8 h = ₹125/h; 2 h at 2.0× = ₹500."""
    result = compute_employee(
        _input(
            (_september(_lines(3_000_000, 0, 0)),),
            "30",
            overtime=(OvertimeInput("NORMAL", Decimal("2"), 120),),
        )
    )
    assert _amounts(result)["OVERTIME"] == 50_000
    assert result.gross_minor == 3_050_000


def test_overtime_without_multiplier_is_an_error_and_unpaid() -> None:
    result = compute_employee(
        _input(
            (_september(_lines(3_000_000, 0, 0)),),
            "30",
            overtime=(OvertimeInput("HOLIDAY", None, 60),),
        )
    )
    assert "OVERTIME" not in _amounts(result)
    assert "OT_MULTIPLIER_MISSING" in _codes(result)
    assert result.has_error


def test_leave_encashment_uses_basic_per_day() -> None:
    """D4 — ₹30,000 ÷ 30 = ₹1,000 a day; 2.5 days = ₹2,500."""
    result = compute_employee(
        _input(
            (_september(_lines(3_000_000, 0, 0)),),
            "30",
            encashments=(EncashmentInput("e1", Decimal("2.5"), date(2026, 9, 1)),),
        )
    )
    assert _amounts(result)["LEAVE_ENCASHMENT"] == 250_000


def test_net_pay_is_not_rounded_to_the_rupee() -> None:
    """D8 (2026-09-24) — ₹10,000.00 × 29/30 = ₹9,666.67, paid to the paisa."""
    result = compute_employee(_input((_september(_lines(1_000_000, 0, 0)),), "29"))
    assert result.gross_minor == 966_667
    assert result.net_minor == 966_667
    assert result.rounding_minor == 0
    assert "NET_ROUNDING" not in _amounts(result)


def test_statutory_deductions_and_structure_employer_pf_is_replaced() -> None:
    """Phase 5.3 — the structure's EMPLOYER_PF line only splits CTC; the run computes PF from the
    statute on earned PF wages (Basic ₹30,000 → capped at ₹15,000)."""
    lines = (
        SegmentLine("BASIC", "Basic", "EARNING", 3_000_000, True, 10, is_pf_wage=True,
                    is_esi_wage=True),
        SegmentLine("EMPLOYER_PF", "Employer PF", "EMPLOYER_CONTRIBUTION", 180_000, True, 90),
    )  # fmt: skip
    statutory = {
        "month_end": date(2026, 9, 30),
        "profile": {"is_pf_applicable": True, "pt_state_code": None},
        "employee": {"uan_number": "100200300400"},
        "rates": {"PF": {"id": "pf", "verified": True, "parameters": _PF}},
    }
    result = compute_employee(_input((_september(lines),), "30", statutory=statutory))
    amounts = _amounts(result)
    assert "EMPLOYER_PF" not in amounts
    assert amounts["PF_EMPLOYEE"] == 180_000
    assert amounts["EPS_EMPLOYER"] == 125_000
    assert amounts["EPF_EMPLOYER"] == 55_000
    assert result.deductions_minor == 180_000
    assert result.net_minor == 3_000_000 - 180_000
    assert not result.issues


def test_inputs_locked_before_statutory_are_refused() -> None:
    result = compute_employee(_input((_september(_lines(3_000_000, 0, 0)),), "30", statutory=None))
    assert "STATUTORY_NOT_SNAPSHOTTED" in _codes(result)


def test_income_tax_is_deducted_from_gross_including_arrears() -> None:
    """Phase 5.6 — wiring only (the tax math itself is `test_income_tax.py`): a high monthly
    gross produces a TDS_EMPLOYEE deduction line that reduces net pay."""
    income_tax = {
        "period_month": date(2026, 4, 1),
        "profile": {"tax_regime": "NEW", "has_pan": True},
        "ytd_taxable_earnings_minor": 0,
        "ytd_tds_deducted_minor": 0,
        "rate": {"id": "tds", "verified": True, "parameters": {
            "regime": "NEW", "standard_deduction_minor": 7_500_000,
            "rebate_taxable_income_limit_minor": 120_000_000, "cess_percent": "4",
            "surcharge_warning_income_minor": 500_000_000,
            "slabs": [
                {"min_minor": 0, "max_minor": 40_000_000, "percent": "0"},
                {"min_minor": 40_000_000, "max_minor": None, "percent": "30"},
            ],
        }},
    }  # fmt: skip
    lines = (_september(_lines(20_000_000, 0, 0)),)
    result = compute_employee(_input(lines, "30", income_tax=income_tax))
    assert not result.issues
    assert "TDS_EMPLOYEE" in _amounts(result)
    assert result.deductions_minor == _amounts(result)["TDS_EMPLOYEE"]
    assert result.net_minor == result.gross_minor - result.deductions_minor


def test_income_tax_absent_is_silent() -> None:
    """Unlike a missing `statutory` block, a missing `income_tax` block (inputs locked before
    this phase existed, or an arrears item's own historical month) is never an error."""
    result = compute_employee(_input((_september(_lines(3_000_000, 0, 0)),), "30"))
    assert "TDS_EMPLOYEE" not in _amounts(result)
    assert not any("INCOME_TAX" in issue.code for issue in result.issues)


def test_bank_details_are_required_unless_paid_in_cash() -> None:
    lines = (_september(_lines(3_000_000, 0, 0)),)
    assert "BANK_MISSING" in _codes(compute_employee(_input(lines, "30", bank=None)))
    no_account = compute_employee(_input(lines, "30", bank={"payment_mode": "BANK"}))
    assert "BANK_ACCOUNT_MISSING" in _codes(no_account)
    cash = compute_employee(_input(lines, "30", bank={"payment_mode": "CASH"}))
    assert not cash.issues


def test_zero_paid_days_is_a_warning() -> None:
    result = compute_employee(_input((_september(_lines(3_000_000, 0, 0)),), "0"))
    assert result.net_minor == 0
    assert "ZERO_NET" in _codes(result)
    assert not result.has_error


def test_summary_without_paid_days_is_refused() -> None:
    result = compute_employee(_input((_september(_lines(3_000_000, 0, 0)),), None))
    assert "SUMMARY_UNUSABLE" in _codes(result)
    assert result.net_minor == 0


def test_invalid_segment_days_are_never_paid_at_another_rate() -> None:
    """A segment whose pay could not be resolved still takes its share of paid days."""
    good = _segment(date(2026, 9, 1), date(2026, 9, 15), _lines(3_000_000, 0, 0))
    missing = Segment(
        date_from=date(2026, 9, 16),
        date_to=date(2026, 9, 30),
        employed_days=15,
        pay_basis="MONTHLY",
        valid=False,
    )
    result = compute_employee(_input((good, missing), "30"))
    assert _amounts(result)["BASIC"] == 1_500_000


def test_snapshot_round_trip() -> None:
    snapshot = {
        "summary": {"paid_days": "30.00"},
        "segments": [
            {
                "from": "2026-09-01",
                "to": "2026-09-30",
                "employed_days": 30,
                "pay_basis": "MONTHLY",
                "valid": True,
                "pf_applicable": False,
                "esi_applicable": False,
                "lines": [
                    {
                        "component_code": "BASIC",
                        "component_name": "Basic",
                        "component_type": "EARNING",
                        "monthly_minor": 3_000_000,
                        "is_prorated": True,
                        "display_order": 10,
                    }
                ],
            }
        ],
        "overtime": [{"day_class": "NORMAL", "multiplier": "1.5", "minutes": 60}],
        "encashments": [],
        "bank": _BANK,
        "issues": [],
        "statutory": {"month_end": "2026-09-30", "profile": None, "employee": {}, "rates": {}},
    }
    result = compute_employee(employee_input_from_snapshot(snapshot, 30))
    # Basic ₹30,000 + 1 h × ₹125 × 1.5 = ₹187.50, not rounded (D8).
    assert _amounts(result)["OVERTIME"] == 18_750
    assert result.net_minor == 3_018_750

    missing = compute_employee(
        employee_input_from_snapshot(
            {
                **snapshot,
                "summary": None,
                "issues": [{"code": "NOT_IN_ATTENDANCE", "severity": "ERROR", "message": "x"}],
            },
            30,
        )  # fmt: skip
    )
    assert _codes(missing) == {"NOT_IN_ATTENDANCE"}


def _august(basic: int, paid: str = "31") -> EmployeeInput:
    segment = _segment(date(2026, 8, 1), date(2026, 8, 31), _lines(basic, 0, 0))
    return EmployeeInput(
        days_in_month=31,
        paid_days=Decimal(paid),
        has_summary=True,
        segments=(segment,),
        bank=_BANK,
        statutory={**_NO_STATUTORY, "month_end": date(2026, 8, 31)},
    )


def test_arrears_pay_the_difference_for_an_earlier_month() -> None:
    """A backdated raise: August was paid on Basic ₹30,000; it should have been ₹31,000."""
    paid = {"BASIC": PaidLine(3_000_000, "EARNING", "Basic", 10)}
    arrears = (ArrearsInput("2026-08", "run-aug", ("SALARY_REVISED",), _august(3_100_000), paid),)
    result = compute_employee(_input((_september(_lines(3_100_000, 0, 0)),), "30", arrears=arrears))
    amounts = _amounts(result)
    assert amounts["ARR_BASIC"] == 100_000
    assert result.gross_minor == 3_200_000
    line = next(line for line in result.lines if line.component_code == "ARR_BASIC")
    assert line.component_name == "Basic arrears"
    assert line.trace["parts"][0]["month"] == "2026-08"
    assert line.trace["parts"][0]["paid_minor"] == 3_000_000


def test_arrears_for_a_day_correction_and_nothing_when_already_paid() -> None:
    """A day correction: August recomputed with 31 paid days instead of 30 (LOP reversed)."""
    paid = {"BASIC": PaidLine(3_000_000 * 30 // 31, "EARNING", "Basic", 10)}
    arrears = (ArrearsInput("2026-08", "run-aug", ("DAYS_CORRECTED",), _august(3_000_000), paid),)
    result = compute_employee(_input((_september(_lines(3_000_000, 0, 0)),), "30", arrears=arrears))
    assert _amounts(result)["ARR_BASIC"] == 3_000_000 - 3_000_000 * 30 // 31

    settled = {"BASIC": PaidLine(3_000_000, "EARNING", "Basic", 10)}
    none_due = compute_employee(_input(
        (_september(_lines(3_000_000, 0, 0)),), "30",
        arrears=(ArrearsInput("2026-08", "run-aug", (), _august(3_000_000), settled),),
    ))  # fmt: skip
    assert not any(code.startswith("ARR_") for code in _amounts(none_due))


def test_arrears_recover_an_overpayment_and_a_removed_component() -> None:
    paid = {
        "BASIC": PaidLine(3_000_000, "EARNING", "Basic", 10),
        "HRA": PaidLine(500_000, "EARNING", "House Rent Allowance", 20),
    }
    arrears = (ArrearsInput("2026-08", "run-aug", (), _august(2_900_000), paid),)
    result = compute_employee(_input((_september(_lines(3_000_000, 0, 0)),), "30", arrears=arrears))
    amounts = _amounts(result)
    assert amounts["ARR_BASIC"] == -100_000
    assert amounts["ARR_HRA"] == -500_000
    assert result.net_minor == 3_000_000 - 600_000
