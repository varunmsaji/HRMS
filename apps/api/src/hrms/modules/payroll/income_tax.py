"""Pure income-tax (TDS) computation (payroll plan Phase 5.6, FR-PAY-011) — **new regime only,
v1 scope**. No DB, no I/O: a function of this month's earned wages, what has actually been paid
and deducted so far this financial year (from the caller's YTD query over finalised runs), and
the effective-dated slab rate snapshotted with the run — the same "rate is data, verified before
use" shape as `statutory.py`.

Section 192's average-rate method: project the year's income from what has actually been paid so
far plus this month's rate continuing for the rest of the year, tax the projection, then divide
what is still owed by the months left to collect it.

**v1 scope — documented, not a bug** (mirrors how `statutory.py` documents its own known limits):

- **New tax regime only.** An employee on the old regime blocks the run (`TDS_OLD_REGIME_NOT_
  SUPPORTED`) rather than being silently mis-taxed — the old regime is close to meaningless
  without the Chapter VI-A declarations this version doesn't collect.
- **No declarations, no HRA/LTA exemption.** Taxable income is gross actually paid this year,
  minus the flat standard deduction only. The new regime itself disallows most Chapter VI-A
  deductions, which is what makes this a defensible first cut rather than a shortcut.
- **No previous-employer income (Form 12B).** An employee who joined mid-year from another
  employer is taxed only on what *this* employer has paid them — under-withholding relative to
  their true annual income unless HR handles it outside the system.
- **Section 87A rebate, no marginal relief.** Full rebate at or below the configured taxable-
  income threshold; no smoothing for income just above it.
- **No surcharge.** Only a warning above the configured high-income threshold — compute and
  adjust by hand.
- **Section 206AA (no PAN): blocked, not auto-penalised.** A run with tax due and no PAN on file
  refuses to approve rather than silently deducting the penal flat rate.
- **Arrears are not re-taxed for their original month.** Arrears money is added to the month it is
  actually paid (the engine includes it in that month's gross before this runs) — correct under
  cash-basis TDS — but this module is never invoked for the historical months `_arrears()`
  recomputes; only the outer, current month gets a TDS line.

Money is integer paise; percentages are `Decimal`."""

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

_HUNDRED = Decimal(100)
_RUPEE = Decimal(100)


@dataclass(frozen=True)
class TdsLine:
    component_code: str
    component_name: str
    line_type: str  # DEDUCTION
    amount_minor: int
    display_order: int
    trace: dict[str, Any]


@dataclass(frozen=True)
class TdsIssue:
    code: str
    severity: str
    message: str


@dataclass(frozen=True)
class TdsResult:
    lines: list[TdsLine] = field(default_factory=list)
    issues: list[TdsIssue] = field(default_factory=list)


def _pct(percent: str | Decimal) -> Decimal:
    return Decimal(str(percent)) / _HUNDRED


def _to_rupee(value: Decimal) -> int:
    """Half-up to the whole rupee, in paise."""
    return int((value / _RUPEE).quantize(Decimal(1), rounding=ROUND_HALF_UP)) * 100


def financial_year_start(period_month: date) -> date:
    """India's financial year: 1 April to 31 March."""
    year = period_month.year if period_month.month >= 4 else period_month.year - 1
    return date(year, 4, 1)


def months_remaining_in_fy(period_month: date) -> int:
    """Months from `period_month` through the following March, inclusive of `period_month`."""
    fy_start = financial_year_start(period_month)
    fy_end_year = fy_start.year + 1
    return (fy_end_year - period_month.year) * 12 + (3 - period_month.month) + 1


def _slab_tax(taxable_minor: int, slabs: list[dict[str, Any]]) -> Decimal:
    tax = Decimal(0)
    for slab in slabs:
        lo = int(slab["min_minor"])
        hi = slab.get("max_minor")
        hi = int(hi) if hi is not None else None
        if taxable_minor <= lo:
            continue
        upper = min(taxable_minor, hi) if hi is not None else taxable_minor
        band = max(0, upper - lo)
        tax += Decimal(band) * _pct(slab["percent"])
    return tax


def compute_tds(
    *,
    period_month: date,
    this_month_taxable_earnings_minor: int,
    ytd_taxable_earnings_minor: int,
    ytd_tds_deducted_minor: int,
    profile: dict[str, Any] | None,
    rate: dict[str, Any] | None,
) -> TdsResult:
    """`profile` is `{"tax_regime": "NEW"/"OLD"/None, "has_pan": bool}` from the employee's
    statutory profile, or `None` when the employee has no statutory profile at all (mirrors
    `statutory.compute_statutory`'s own `profile is None` gate — nothing to compute yet).
    `rate` is the snapshotted `TDS` scheme rate — `{"id", "parameters", "verified"}` — or `None`."""
    if profile is None:
        return TdsResult()

    issues: list[TdsIssue] = []
    regime = profile.get("tax_regime")
    if regime is None:
        issues.append(TdsIssue(
            "TDS_REGIME_NOT_SET", "WARNING",
            "No tax regime is set on the employee's statutory profile — defaulting to the new "
            "regime",
        ))  # fmt: skip
        regime = "NEW"
    if regime == "OLD":
        issues.append(TdsIssue(
            "TDS_OLD_REGIME_NOT_SUPPORTED", "ERROR",
            "The old tax regime isn't supported yet — move the employee to the new regime or "
            "compute and record their TDS manually",
        ))  # fmt: skip
        return TdsResult(issues=issues)

    if rate is None:
        issues.append(TdsIssue(
            "TDS_RATE_MISSING", "ERROR",
            f"No income-tax slab rate is in force on {period_month.isoformat()}",
        ))  # fmt: skip
        return TdsResult(issues=issues)

    p = rate["parameters"]
    remaining = months_remaining_in_fy(period_month)
    projected_annual = ytd_taxable_earnings_minor + this_month_taxable_earnings_minor * remaining
    standard_deduction = int(p["standard_deduction_minor"])
    taxable = max(0, projected_annual - standard_deduction)

    rebate_limit = int(p["rebate_taxable_income_limit_minor"])
    rebate_applied = taxable <= rebate_limit
    tax = Decimal(0) if rebate_applied else _slab_tax(taxable, p["slabs"])
    cess = tax * _pct(p["cess_percent"])
    annual_tax_minor = _to_rupee(tax + cess)

    surcharge_threshold = int(p.get("surcharge_warning_income_minor", 0))
    if surcharge_threshold and projected_annual > surcharge_threshold:
        issues.append(TdsIssue(
            "TDS_SURCHARGE_NOT_COMPUTED", "WARNING",
            "Projected annual income is above the surcharge threshold — surcharge is not "
            "computed here; work it out and adjust manually",
        ))  # fmt: skip

    remaining_liability = max(0, annual_tax_minor - ytd_tds_deducted_minor)
    this_month_tds = _to_rupee(Decimal(remaining_liability) / remaining) if remaining > 0 else 0

    # Verification is required only once real tax is actually due — an employee comfortably
    # under the rebate threshold shouldn't block a run over an unverified slab table they'll
    # never touch (mirrors why PF/ESI/PT/LWF only need verification when `is_x_applicable`).
    if this_month_tds > 0 and not rate.get("verified"):
        issues.append(TdsIssue(
            "STATUTORY_UNVERIFIED", "ERROR",
            "The income-tax slab rate used has not been verified by compliance — verify it "
            "under Payroll → Statutory Rates",
        ))  # fmt: skip

    if this_month_tds > 0 and not profile.get("has_pan"):
        issues.append(TdsIssue(
            "PAN_MISSING_FOR_TDS", "ERROR",
            "Tax deduction applies but the employee has no PAN on file — capture it before "
            "finalising",
        ))  # fmt: skip

    lines: list[TdsLine] = []
    if this_month_tds > 0:
        lines.append(TdsLine(
            "TDS_EMPLOYEE", "Income tax (TDS)", "DEDUCTION", this_month_tds, 135,
            trace={
                "regime": regime,
                "formula": "(projected annual tax − TDS already deducted this year) ÷ months "
                "remaining in the financial year",
                "projected_annual_income_minor": projected_annual,
                "standard_deduction_minor": standard_deduction,
                "taxable_income_minor": taxable,
                "rebate_applied": rebate_applied,
                "rebate_taxable_income_limit_minor": rebate_limit,
                "slab_tax_minor": _to_rupee(tax),
                "cess_percent": str(p["cess_percent"]),
                "annual_tax_minor": annual_tax_minor,
                "ytd_taxable_earnings_minor": ytd_taxable_earnings_minor,
                "ytd_tds_deducted_minor": ytd_tds_deducted_minor,
                "months_remaining_in_fy": remaining,
                "rate_id": rate["id"],
            },
        ))  # fmt: skip
    return TdsResult(lines=lines, issues=issues)
