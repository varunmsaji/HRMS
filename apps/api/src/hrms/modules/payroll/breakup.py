"""Pure CTC → component breakup (payroll plan Phase 5.1, `docs/modules/payroll/
00_PAYROLL_IMPLEMENTATION_PLAN.md`). No DB, no I/O — a function of the structure lines and the
employee's CTC and statutory applicability, so it is unit-testable and reusable unchanged by the
pay-run engine (5.2).

Money is integer paise throughout (`docs/audits/PAYROLL_FOUNDATION_CONTRACT.md` C7); percentages
are `Decimal`.

How a monthly CTC splits (D2 — employer contributions sit **inside** CTC):

    monthly CTC = gross (all EARNING lines) + employer contributions

Earning lines may depend on gross itself (D1 — Basic is a percentage of gross), and employer
contributions depend on earnings (employer PF is 12 % of Basic), so gross cannot be read off
directly. `f(g) = g + employer_contributions(g)` is non-decreasing in `g`, so the largest gross
with `f(g) <= monthly CTC` is found by bisection over whole paise; the one BALANCING earning line
then absorbs whatever remains, which makes `gross + employer = monthly CTC` exact.

Computed lines round to the whole rupee (Indian payslip convention); only the balancing line may
carry paise, and only when the CTC itself does."""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

CALCULATION_TYPES = (
    "FIXED",
    "PERCENTAGE_OF_CTC",
    "PERCENTAGE_OF_GROSS",
    "PERCENTAGE_OF_COMPONENT",
    "BALANCING",
)
COMPONENT_TYPES = ("EARNING", "DEDUCTION", "EMPLOYER_CONTRIBUTION")
# Which lines apply to an employee (a PF line is skipped for someone not PF-applicable).
APPLIES_WHEN = ("ALWAYS", "PF_APPLICABLE", "ESI_APPLICABLE")

#: Codes a pay run itself writes (PAY-B03): earnings it derives from attendance/encashment, the
#: statutory deductions and contributions of `statutory.py`, TDS (`income_tax.py`) and the
#: rounding line. A salary component may not use one — in a run it would silently collide with
#: (be overwritten by, or overwrite) the computed line. `EMPLOYER_PF` / `EMPLOYER_ESI` are NOT here:
#: they are supported structure lines that split CTC and are replaced by the statutory computation.
RUN_LINE_CODES = frozenset({
    "OVERTIME", "LEAVE_ENCASHMENT", "DAILY_WAGES", "ROUNDING",
    "PF_EMPLOYEE", "VPF", "EPF_EMPLOYER", "EPS_EMPLOYER", "PF_EDLI", "PF_ADMIN",
    "ESI_EMPLOYEE", "ESI_EMPLOYER", "PT", "LWF_EMPLOYEE", "LWF_EMPLOYER", "TDS_EMPLOYEE",
})  # fmt: skip
#: Arrears lines are `ARR_<component code>`; a component starting with this would collide.
ARREARS_PREFIX = "ARR_"

_HUNDRED = Decimal(100)
_RUPEE = 100  # paise


class BreakupError(ValueError):
    """The structure cannot produce a valid breakup — a configuration error (at publish) or a CTC
    too small for the structure's fixed amounts (at preview/assignment)."""


@dataclass(frozen=True)
class StructureLine:
    component_code: str
    component_name: str
    component_type: str
    calculation_type: str
    percentage: Decimal | None = None
    amount_monthly_minor: int | None = None
    base_component_code: str | None = None
    max_monthly_minor: int | None = None
    applies_when: str = "ALWAYS"
    display_order: int = 0


@dataclass(frozen=True)
class BreakupLine:
    component_code: str
    component_name: str
    component_type: str
    monthly_minor: int
    annual_minor: int
    # How the figure was reached, for the payslip/trace (FR-PAY-024).
    basis: str


@dataclass(frozen=True)
class Breakup:
    annual_ctc_minor: int
    monthly_ctc_minor: int
    gross_monthly_minor: int
    employer_contributions_monthly_minor: int
    lines: list[BreakupLine] = field(default_factory=list)


def _round_rupee(value: Decimal) -> int:
    rupees = (value / _RUPEE).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return int(rupees) * _RUPEE


def _pct(base: Decimal | int, percentage: Decimal) -> Decimal:
    return Decimal(base) * percentage / _HUNDRED


def monthly_from_annual(annual_minor: int) -> int:
    return int((Decimal(annual_minor) / 12).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def reserved_component_code_reason(code: str) -> str | None:
    """Why `code` cannot be a salary component code, or `None` if it can."""
    if code in RUN_LINE_CODES:
        return f"{code} is reserved: a pay run computes a line with that code itself"
    if code.startswith(ARREARS_PREFIX):
        return f"Codes starting with {ARREARS_PREFIX} are reserved for arrears lines"
    return None


def validate_structure(lines: list[StructureLine]) -> None:
    """Configuration rules, checked at publish and before every breakup:

    - exactly one BALANCING line, and it is an EARNING;
    - DEDUCTION components are not structure lines yet (statutory/recurring deductions arrive with
      the pay-run and statutory phases);
    - each line carries the fields its calculation type needs;
    - PERCENTAGE_OF_COMPONENT references a non-balancing EARNING line in the same structure, with
      no cycles; PERCENTAGE_OF_GROSS is allowed on earnings only (an employer contribution on
      gross would make gross depend on itself through the balancing line in a way bisection
      still handles, but no current rule needs it, so it stays out until one does)."""
    if not lines:
        raise BreakupError("A salary structure needs at least one line")
    codes = [line.component_code for line in lines]
    for code in codes:
        reason = reserved_component_code_reason(code)
        if reason is not None:
            raise BreakupError(reason)
    if len(codes) != len(set(codes)):
        raise BreakupError("A component may appear only once in a structure")
    balancing = [line for line in lines if line.calculation_type == "BALANCING"]
    if len(balancing) != 1:
        raise BreakupError("A salary structure needs exactly one BALANCING line")
    if balancing[0].component_type != "EARNING":
        raise BreakupError("The BALANCING line must be an earning")
    by_code = {line.component_code: line for line in lines}
    for line in lines:
        if line.component_type == "DEDUCTION":
            raise BreakupError(
                f"{line.component_code}: deductions are not part of a salary structure yet"
            )
        if line.calculation_type not in CALCULATION_TYPES:
            raise BreakupError(f"{line.component_code}: unknown calculation type")
        if line.applies_when not in APPLIES_WHEN:
            raise BreakupError(f"{line.component_code}: unknown applies_when")
        if line.calculation_type == "FIXED":
            if line.amount_monthly_minor is None or line.amount_monthly_minor < 0:
                raise BreakupError(f"{line.component_code}: a FIXED line needs an amount")
        elif line.calculation_type != "BALANCING":
            if line.percentage is None or not (Decimal(0) <= line.percentage <= _HUNDRED):
                raise BreakupError(
                    f"{line.component_code}: a percentage line needs a percentage from 0 to 100"
                )
        if line.calculation_type == "PERCENTAGE_OF_GROSS" and line.component_type != "EARNING":
            raise BreakupError(
                f"{line.component_code}: only an earning may be a percentage of gross"
            )
        if line.calculation_type == "PERCENTAGE_OF_COMPONENT":
            base = by_code.get(line.base_component_code or "")
            if base is None:
                raise BreakupError(
                    f"{line.component_code}: base component is not in this structure"
                )
            if base.component_type != "EARNING" or base.calculation_type == "BALANCING":
                raise BreakupError(
                    f"{line.component_code}: the base must be a non-balancing earning"
                )
        if line.max_monthly_minor is not None and line.max_monthly_minor < 0:
            raise BreakupError(f"{line.component_code}: the cap cannot be negative")
    _earning_order(lines)  # raises on a cycle


def _earning_order(lines: list[StructureLine]) -> list[StructureLine]:
    """Non-balancing earnings in dependency order (a base before the lines that use it)."""
    pending = {
        line.component_code: line
        for line in lines
        if line.component_type == "EARNING" and line.calculation_type != "BALANCING"
    }
    ordered: list[StructureLine] = []
    done: set[str] = set()
    while pending:
        ready = [
            line
            for line in pending.values()
            if line.calculation_type != "PERCENTAGE_OF_COMPONENT"
            or line.base_component_code in done
        ]
        if not ready:
            raise BreakupError("Salary structure components reference each other in a cycle")
        for line in sorted(ready, key=lambda item: (item.display_order, item.component_code)):
            ordered.append(line)
            done.add(line.component_code)
            del pending[line.component_code]
    return ordered


def _line_amount(
    line: StructureLine, *, monthly_ctc: int, gross: int, amounts: dict[str, int]
) -> tuple[int, str]:
    if line.calculation_type == "FIXED":
        value = Decimal(line.amount_monthly_minor or 0)
        basis = "fixed amount"
    elif line.calculation_type == "PERCENTAGE_OF_CTC":
        value = _pct(monthly_ctc, line.percentage or Decimal(0))
        basis = f"{line.percentage}% of monthly CTC"
    elif line.calculation_type == "PERCENTAGE_OF_GROSS":
        value = _pct(gross, line.percentage or Decimal(0))
        basis = f"{line.percentage}% of gross"
    else:  # PERCENTAGE_OF_COMPONENT
        value = _pct(amounts[line.base_component_code or ""], line.percentage or Decimal(0))
        basis = f"{line.percentage}% of {line.base_component_code}"
    amount = _round_rupee(value)
    if line.max_monthly_minor is not None and amount > line.max_monthly_minor:
        amount = line.max_monthly_minor
        basis += f", capped at {line.max_monthly_minor / _RUPEE:.2f}"
    return amount, basis


def _applies(line: StructureLine, *, pf_applicable: bool, esi_applicable: bool) -> bool:
    if line.applies_when == "PF_APPLICABLE":
        return pf_applicable
    if line.applies_when == "ESI_APPLICABLE":
        return esi_applicable
    return True


def _evaluate(
    earnings: list[StructureLine],
    employer: list[StructureLine],
    *,
    monthly_ctc: int,
    gross: int,
) -> tuple[dict[str, tuple[int, str]], int]:
    """Amounts for every non-balancing earning and employer line at a candidate gross."""
    results: dict[str, tuple[int, str]] = {}
    amounts: dict[str, int] = {}
    for line in earnings:
        amount, basis = _line_amount(line, monthly_ctc=monthly_ctc, gross=gross, amounts=amounts)
        results[line.component_code] = (amount, basis)
        amounts[line.component_code] = amount
    employer_total = 0
    for line in employer:
        amount, basis = _line_amount(line, monthly_ctc=monthly_ctc, gross=gross, amounts=amounts)
        results[line.component_code] = (amount, basis)
        employer_total += amount
    return results, employer_total


def compute_breakup(
    lines: list[StructureLine],
    *,
    annual_ctc_minor: int,
    pf_applicable: bool,
    esi_applicable: bool,
) -> Breakup:
    """The monthly and annual amount of every applicable component for one CTC."""
    validate_structure(lines)
    if annual_ctc_minor <= 0:
        raise BreakupError("CTC must be greater than zero")
    monthly_ctc = monthly_from_annual(annual_ctc_minor)
    applicable = [
        line
        for line in lines
        if _applies(line, pf_applicable=pf_applicable, esi_applicable=esi_applicable)
    ]
    balancing = next(line for line in lines if line.calculation_type == "BALANCING")
    earnings = [line for line in _earning_order(lines) if line in applicable]
    employer = [line for line in applicable if line.component_type == "EMPLOYER_CONTRIBUTION"]

    # Largest gross g with g + employer(g) <= monthly CTC.
    low, high = 0, monthly_ctc
    while low < high:
        mid = (low + high + 1) // 2
        _, employer_total = _evaluate(earnings, employer, monthly_ctc=monthly_ctc, gross=mid)
        if mid + employer_total <= monthly_ctc:
            low = mid
        else:
            high = mid - 1
    results, employer_total = _evaluate(earnings, employer, monthly_ctc=monthly_ctc, gross=low)
    gross = monthly_ctc - employer_total
    fixed_earnings = sum(results[line.component_code][0] for line in earnings)
    balancing_amount = gross - fixed_earnings
    if balancing_amount < 0:
        raise BreakupError(
            "This CTC is too small for the structure — its fixed components exceed it"
        )
    results[balancing.component_code] = (balancing_amount, "balance of gross")

    ordered = sorted(
        [line for line in lines if line.component_code in results],
        key=lambda item: (item.display_order, item.component_code),
    )
    return Breakup(
        annual_ctc_minor=annual_ctc_minor,
        monthly_ctc_minor=monthly_ctc,
        gross_monthly_minor=gross,
        employer_contributions_monthly_minor=employer_total,
        lines=[
            BreakupLine(
                component_code=line.component_code,
                component_name=line.component_name,
                component_type=line.component_type,
                monthly_minor=results[line.component_code][0],
                annual_minor=results[line.component_code][0] * 12,
                basis=results[line.component_code][1],
            )
            for line in ordered
        ],
    )
