"""Unit tests for the pure statutory computation (payroll plan Phase 5.3, FR-PAY-005/006)."""

from datetime import date
from decimal import Decimal
from typing import Any

from hrms.modules.payroll.statutory import StatutoryResult, compute_statutory

_PF = {
    "employee_percent": "12",
    "employer_percent": "12",
    "eps_percent": "8.33",
    "wage_ceiling_minor": 1_500_000,
    "edli_percent": "0.5",
    "admin_percent": "0.5",
    "eps_age_limit": 58,
}
_ESI = {
    "employee_percent": "0.75",
    "employer_percent": "3.25",
    "wage_ceiling_minor": 2_100_000,
    "employee_exempt_daily_wage_minor": 17_600,
}
_PT_MH = {
    "slabs": [
        {"min_minor": 0, "max_minor": 750_000, "amount_minor": 0, "gender": "MALE"},
        {"min_minor": 750_001, "max_minor": 1_000_000, "amount_minor": 17_500, "gender": "MALE"},
        {"min_minor": 1_000_001, "max_minor": None, "amount_minor": 20_000, "gender": "MALE",
         "month_amounts": {"2": 30_000}},
        {"min_minor": 0, "max_minor": 2_500_000, "amount_minor": 0, "gender": "FEMALE"},
        {"min_minor": 2_500_001, "max_minor": None, "amount_minor": 20_000, "gender": "FEMALE",
         "month_amounts": {"2": 30_000}},
    ]
}  # fmt: skip
_LWF = {
    "months": [6, 12],
    "slabs": [
        {"min_minor": 0, "max_minor": None, "employee_minor": 1_200, "employer_minor": 3_600}
    ],
}


def _rate(parameters: dict[str, Any], *, verified: bool = True) -> dict[str, Any]:
    return {"id": "r", "verified": verified, "parameters": parameters}


def _run(
    *,
    profile: dict[str, Any],
    gross: int = 3_000_000,
    pf_wages: int = 3_000_000,
    esi_wages: int = 0,
    paid_days: str = "30",
    month_end: date = date(2026, 9, 30),
    employee: dict[str, Any] | None = None,
    rates: dict[str, Any] | None = None,
) -> StatutoryResult:
    return compute_statutory(
        month_end=month_end,
        paid_days=Decimal(paid_days),
        gross_minor=gross,
        pf_wages_minor=pf_wages,
        esi_wages_minor=esi_wages,
        profile=profile,
        employee=employee if employee is not None else {"uan_number": "100200300400"},
        rates=rates if rates is not None else {"PF": _rate(_PF), "ESI": _rate(_ESI)},
    )


def _amounts(result: StatutoryResult) -> dict[str, int]:
    return {line.component_code: line.amount_minor for line in result.lines}


def _codes(result: StatutoryResult) -> set[str]:
    return {issue.code for issue in result.issues}


def test_pf_on_wages_capped_at_the_ceiling() -> None:
    result = _run(profile={"is_pf_applicable": True})
    assert _amounts(result) == {
        "PF_EMPLOYEE": 180_000,  # 12 % of ₹15,000
        "EPS_EMPLOYER": 125_000,  # 8.33 % of ₹15,000 = ₹1,249.50 → ₹1,250
        "EPF_EMPLOYER": 55_000,  # ₹1,800 − ₹1,250
        "PF_EDLI": 7_500,
        "PF_ADMIN": 7_500,
    }
    assert not result.issues


def test_pf_on_higher_wages_when_the_ceiling_is_opted_out() -> None:
    result = _run(profile={"is_pf_applicable": True, "pf_wage_ceiling_opt_out": True})
    amounts = _amounts(result)
    assert amounts["PF_EMPLOYEE"] == 360_000
    assert amounts["EPS_EMPLOYER"] == 125_000  # pension stays on the ceiling
    assert amounts["EPF_EMPLOYER"] == 235_000
    assert amounts["PF_ADMIN"] == 15_000


def test_no_pension_from_age_58() -> None:
    result = _run(
        profile={"is_pf_applicable": True},
        employee={"uan_number": "1", "date_of_birth": date(1968, 9, 1)},
    )
    amounts = _amounts(result)
    assert amounts["EPS_EMPLOYER"] == 0
    assert amounts["EPF_EMPLOYER"] == 180_000


def test_vpf_fixed_and_percentage() -> None:
    fixed = _run(profile={"is_pf_applicable": True, "vpf_amount": 50_000})
    assert _amounts(fixed)["VPF"] == 50_000
    percent = _run(profile={"is_pf_applicable": True, "vpf_percentage": 10.0})
    assert _amounts(percent)["VPF"] == 150_000  # 10 % of the ₹15,000 contribution base


def test_pf_warnings_and_errors() -> None:
    no_uan = _run(profile={"is_pf_applicable": True}, employee={})
    assert _codes(no_uan) == {"UAN_MISSING"}
    missing = _run(profile={"is_pf_applicable": True}, rates={})
    assert _codes(missing) == {"PF_RATE_MISSING"}
    assert missing.lines == []
    unverified = _run(profile={"is_pf_applicable": True}, rates={"PF": _rate(_PF, verified=False)})
    assert _codes(unverified) == {"STATUTORY_UNVERIFIED"}
    assert _amounts(unverified)["PF_EMPLOYEE"] == 180_000  # computed, but blocks approval


def test_esi_rounds_up_to_the_next_rupee() -> None:
    result = _run(
        profile={"is_esi_applicable": True, "esi_ip_number": "1"},
        gross=1_799_900,
        esi_wages=1_799_900,
    )
    amounts = _amounts(result)
    assert amounts["ESI_EMPLOYEE"] == 13_500  # ₹134.99 → ₹135
    assert amounts["ESI_EMPLOYER"] == 58_500  # ₹584.97 → ₹585
    assert not result.issues


def test_low_wage_employee_pays_no_esi_share() -> None:
    """Average daily wage ₹5,000 ÷ 30 = ₹166.67 ≤ ₹176 — employee exempt, employer still pays."""
    result = _run(
        profile={"is_esi_applicable": True, "esi_ip_number": "1"}, gross=500_000, esi_wages=500_000
    )
    amounts = _amounts(result)
    assert "ESI_EMPLOYEE" not in amounts
    assert amounts["ESI_EMPLOYER"] == 16_300  # ₹162.50 → ₹163


def test_esi_warnings() -> None:
    result = _run(profile={"is_esi_applicable": True}, gross=2_500_000, esi_wages=2_500_000)
    assert _codes(result) == {"ESI_ABOVE_CEILING", "ESI_IP_MISSING"}


def test_professional_tax_by_slab_gender_and_month() -> None:
    rates = {"PT": _rate(_PT_MH)}
    profile = {"pt_state_code": "MH"}
    male = _run(profile=profile, gross=1_200_000, rates=rates, employee={"gender": "MALE"})
    assert _amounts(male) == {"PT": 20_000}
    february = _run(
        profile=profile,
        gross=1_200_000,
        rates=rates,
        employee={"gender": "MALE"},
        month_end=date(2027, 2, 28),
    )
    assert _amounts(february) == {"PT": 30_000}
    woman_below = _run(profile=profile, gross=2_000_000, rates=rates, employee={"gender": "FEMALE"})
    assert _amounts(woman_below) == {}
    woman_above = _run(profile=profile, gross=3_000_000, rates=rates, employee={"gender": "FEMALE"})
    assert _amounts(woman_above) == {"PT": 20_000}


def test_professional_tax_without_rates_is_a_warning() -> None:
    result = _run(profile={"pt_state_code": "DL"}, rates={})
    assert _codes(result) == {"PT_RATE_MISSING"}
    assert result.lines == []


def test_lwf_only_in_its_months() -> None:
    profile = {"is_lwf_applicable": True, "pt_state_code": "MH"}
    rates = {"LWF": _rate(_LWF)}
    assert _amounts(_run(profile=profile, rates=rates)) == {}
    june = _run(profile=profile, rates=rates, month_end=date(2026, 6, 30))
    assert _amounts(june) == {"LWF_EMPLOYEE": 1_200, "LWF_EMPLOYER": 3_600}
    missing = _run(profile=profile, rates={})
    assert "LWF_RATE_MISSING" in _codes(missing)


def test_no_profile_means_nothing_deducted() -> None:
    result = compute_statutory(
        month_end=date(2026, 9, 30),
        paid_days=Decimal(30),
        gross_minor=3_000_000,
        pf_wages_minor=3_000_000,
        esi_wages_minor=0,
        profile=None,
        employee={},
        rates={},
    )
    assert result.lines == [] and result.issues == []
