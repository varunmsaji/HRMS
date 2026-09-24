"""Pure statutory deductions and employer contributions (payroll plan Phase 5.3, FR-PAY-005/006).
No DB, no I/O — a function of the month's earned wages, the employee's statutory profile and the
effective-dated rates snapshotted with the run, so every figure is reproducible and traced.

Every number comes from the rate parameters (BR-10 — never hard-coded); the defaults the service
seeds are data, marked unverified until compliance signs them off. What is fixed here is only the
*shape* of each scheme:

- **PF** (EPF & MP Act): PF wages = earned components flagged `is_pf_wage` (Basic by default;
  a daily-wage employee's wages). Contributions are on PF wages capped at the wage ceiling unless
  the employee opted to contribute on higher wages (`pf_wage_ceiling_opt_out`). Employee share,
  employer share; of the employer share, EPS on wages up to the ceiling (none from age 58), the
  rest to EPF. EDLI on wages up to the ceiling; admin charges on PF wages. VPF on top, employee
  only. Each amount rounds half-up to the rupee.
- **ESI** (ESI Act): ESI wages = earned components flagged `is_esi_wage` plus overtime. Whether
  the employee is covered is the statutory profile's `is_esi_applicable` (coverage is fixed per
  contribution period, which HR manages); a gross above the ceiling is only a warning. Employee
  and employer shares round **up** to the next rupee; an employee whose average daily wage is at
  or below the exemption limit pays no employee share (the employer share is still due).
- **Professional tax**: by the employee's PT state; slabs on the month's gross, optionally by
  gender, with per-month overrides (e.g. a higher February instalment).
- **LWF**: by the same state, only in the months the rate lists; slabs on the month's gross give
  employee and employer amounts.

Money is integer paise; percentages are `Decimal`."""

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Any

_HUNDRED = Decimal(100)
_RUPEE = Decimal(100)


@dataclass(frozen=True)
class StatutoryLine:
    component_code: str
    component_name: str
    line_type: str  # DEDUCTION / EMPLOYER_CONTRIBUTION
    amount_minor: int
    display_order: int
    trace: dict[str, Any]


@dataclass(frozen=True)
class StatutoryIssue:
    code: str
    severity: str
    message: str


@dataclass(frozen=True)
class StatutoryResult:
    lines: list[StatutoryLine] = field(default_factory=list)
    issues: list[StatutoryIssue] = field(default_factory=list)


def _pct(percent: str | Decimal) -> Decimal:
    return Decimal(str(percent)) / _HUNDRED


def _to_rupee(value: Decimal) -> int:
    """Half-up to the whole rupee, in paise."""
    return int((value / _RUPEE).quantize(Decimal(1), rounding=ROUND_HALF_UP)) * 100


def _up_to_rupee(value: Decimal) -> int:
    """Up to the next whole rupee (ESI), in paise."""
    return int((value / _RUPEE).quantize(Decimal(1), rounding=ROUND_CEILING)) * 100


def _age_on(date_of_birth: date | None, on: date) -> int | None:
    if date_of_birth is None:
        return None
    years = on.year - date_of_birth.year
    if (on.month, on.day) < (date_of_birth.month, date_of_birth.day):
        years -= 1
    return years


def _slab(
    slabs: list[dict[str, Any]], amount_minor: int, gender: str | None
) -> dict[str, Any] | None:
    """The slab containing `amount_minor` (`min_minor <= x <= max_minor`, `max_minor` null =
    unbounded). A slab with a `gender` applies only to that gender and wins over a general one."""
    matches = [
        s
        for s in slabs
        if int(s.get("min_minor", 0)) <= amount_minor
        and (s.get("max_minor") is None or amount_minor <= int(s["max_minor"]))
        and (s.get("gender") in (None, gender))
    ]
    specific = [s for s in matches if s.get("gender") is not None]
    chosen = specific or matches
    return chosen[0] if chosen else None


def _line(
    code: str, name: str, line_type: str, amount: int, order: int, **trace: Any
) -> StatutoryLine:
    return StatutoryLine(code, name, line_type, amount, order, trace)


def compute_statutory(
    *,
    month_end: date,
    paid_days: Decimal,
    gross_minor: int,
    pf_wages_minor: int,
    esi_wages_minor: int,
    profile: dict[str, Any] | None,
    employee: dict[str, Any],
    rates: dict[str, Any],
) -> StatutoryResult:
    """`rates` maps a scheme (`PF`, `ESI`, `PT`, `LWF`) to its snapshotted rate —
    `{"id", "parameters", "verified", "state_code"}` — or `None` when none is in force."""
    lines: list[StatutoryLine] = []
    issues: list[StatutoryIssue] = []
    if profile is None:
        return StatutoryResult(lines, issues)

    def need(scheme: str, label: str) -> dict[str, Any] | None:
        rate: dict[str, Any] | None = rates.get(scheme)
        if rate is None:
            issues.append(StatutoryIssue(
                f"{scheme}_RATE_MISSING", "ERROR",
                f"No {label} rate is in force on {month_end.isoformat()}",
            ))  # fmt: skip
            return None
        if not rate.get("verified"):
            issues.append(StatutoryIssue(
                "STATUTORY_UNVERIFIED", "ERROR",
                f"The {label} rate used has not been verified by compliance — verify it under "
                "Payroll → Statutory Rates",
            ))  # fmt: skip
        return rate

    # -- PF ------------------------------------------------------------------------------
    if profile.get("is_pf_applicable"):
        rate = need("PF", "PF")
        if rate is not None:
            p = rate["parameters"]
            ceiling = int(p["wage_ceiling_minor"])
            capped = min(pf_wages_minor, ceiling)
            base = pf_wages_minor if profile.get("pf_wage_ceiling_opt_out") else capped
            wages = Decimal(base)
            employee_pf = _to_rupee(wages * _pct(p["employee_percent"]))
            employer_total = _to_rupee(wages * _pct(p["employer_percent"]))
            age = _age_on(employee.get("date_of_birth"), month_end)
            eps_age_limit = int(p.get("eps_age_limit", 58))
            eps = (
                0
                if age is not None and age >= eps_age_limit
                else min(_to_rupee(Decimal(capped) * _pct(p["eps_percent"])), employer_total)
            )
            epf = employer_total - eps
            edli = _to_rupee(Decimal(capped) * _pct(p.get("edli_percent", "0")))
            admin = _to_rupee(wages * _pct(p.get("admin_percent", "0")))
            common = {"rate_id": rate["id"], "pf_wages_minor": pf_wages_minor,
                      "ceiling_minor": ceiling, "contribution_base_minor": base}  # fmt: skip
            lines.append(_line("PF_EMPLOYEE", "Provident Fund", "DEDUCTION", employee_pf, 110,
                               formula=f"{p['employee_percent']}% of PF wages"
                               + ("" if base == pf_wages_minor else " up to the ceiling"),
                               **common))  # fmt: skip
            vpf = 0
            if profile.get("vpf_amount"):
                vpf = int(profile["vpf_amount"])
                vpf_formula = "fixed monthly VPF"
            elif profile.get("vpf_percentage"):
                vpf = _to_rupee(wages * _pct(str(profile["vpf_percentage"])))
                vpf_formula = f"{profile['vpf_percentage']}% of PF wages"
            if vpf:
                lines.append(_line("VPF", "Voluntary Provident Fund", "DEDUCTION", vpf, 111,
                                   formula=vpf_formula, **common))  # fmt: skip
            lines.append(_line("EPF_EMPLOYER", "Employer PF (EPF)", "EMPLOYER_CONTRIBUTION", epf,
                               190, formula=f"{p['employer_percent']}% of PF wages less EPS",
                               **common))  # fmt: skip
            lines.append(_line("EPS_EMPLOYER", "Employer pension (EPS)", "EMPLOYER_CONTRIBUTION",
                               eps, 191, formula=(
                                   f"none from age {eps_age_limit}" if eps == 0 and age is not None
                                   and age >= eps_age_limit
                                   else f"{p['eps_percent']}% of PF wages up to the ceiling"),
                               age=age, **common))  # fmt: skip
            if edli:
                lines.append(_line("PF_EDLI", "EDLI contribution", "EMPLOYER_CONTRIBUTION", edli,
                                   192, formula=f"{p['edli_percent']}% of PF wages up to the "
                                   "ceiling", **common))  # fmt: skip
            if admin:
                lines.append(_line("PF_ADMIN", "PF admin charges", "EMPLOYER_CONTRIBUTION",
                                   admin, 193, formula=f"{p['admin_percent']}% of PF wages",
                                   **common))  # fmt: skip
            if not employee.get("uan_number"):
                issues.append(StatutoryIssue(
                    "UAN_MISSING", "WARNING", "PF applies but the employee has no UAN yet"
                ))  # fmt: skip

    # -- ESI -----------------------------------------------------------------------------
    if profile.get("is_esi_applicable"):
        rate = need("ESI", "ESI")
        if rate is not None:
            p = rate["parameters"]
            wages = Decimal(esi_wages_minor)
            exempt_limit = int(p.get("employee_exempt_daily_wage_minor", 0))
            average_daily = wages / paid_days if paid_days > 0 else Decimal(0)
            employee_exempt = exempt_limit > 0 and average_daily <= exempt_limit
            employee_esi = (
                0 if employee_exempt else _up_to_rupee(wages * _pct(p["employee_percent"]))
            )
            employer_esi = _up_to_rupee(wages * _pct(p["employer_percent"]))
            common = {"rate_id": rate["id"], "esi_wages_minor": esi_wages_minor}
            if employee_esi:
                lines.append(_line("ESI_EMPLOYEE", "ESI", "DEDUCTION", employee_esi, 120,
                                   formula=f"{p['employee_percent']}% of ESI wages, up to the "
                                   "next rupee", **common))  # fmt: skip
            lines.append(_line("ESI_EMPLOYER", "Employer ESI", "EMPLOYER_CONTRIBUTION",
                               employer_esi, 194, formula=f"{p['employer_percent']}% of ESI wages, "
                               "up to the next rupee", employee_share_exempt=employee_exempt,
                               **common))  # fmt: skip
            if gross_minor > int(p["wage_ceiling_minor"]):
                issues.append(StatutoryIssue(
                    "ESI_ABOVE_CEILING", "WARNING",
                    "Gross is above the ESI wage ceiling — ESI still applies until the end of the "
                    "contribution period; update the statutory profile after it",
                ))  # fmt: skip
            if not profile.get("esi_ip_number"):
                issues.append(StatutoryIssue(
                    "ESI_IP_MISSING", "WARNING", "ESI applies but the employee has no IP number"
                ))  # fmt: skip

    # -- Professional tax ----------------------------------------------------------------
    state = profile.get("pt_state_code")
    if state:
        rate = rates.get("PT")
        if rate is None:
            issues.append(StatutoryIssue(
                "PT_RATE_MISSING", "WARNING",
                f"No professional tax rates are set up for state {state} — no PT deducted. Add "
                "them (an empty slab list means the state levies none)",
            ))  # fmt: skip
        else:
            if not rate.get("verified"):
                issues.append(StatutoryIssue(
                    "STATUTORY_UNVERIFIED", "ERROR",
                    f"The professional tax rate for {state} has not been verified by compliance",
                ))  # fmt: skip
            slab = _slab(rate["parameters"].get("slabs", []), gross_minor, employee.get("gender"))
            if slab is not None:
                amount = int(slab.get("amount_minor", 0))
                override = (slab.get("month_amounts") or {}).get(str(month_end.month))
                if override is not None:
                    amount = int(override)
                if amount:
                    lines.append(_line("PT", "Professional tax", "DEDUCTION", amount, 130,
                                       formula=f"{state} slab on gross", rate_id=rate["id"],
                                       gross_minor=gross_minor, slab=slab))  # fmt: skip

    # -- LWF -----------------------------------------------------------------------------
    if profile.get("is_lwf_applicable"):
        rate = rates.get("LWF")
        if rate is None:
            issues.append(StatutoryIssue(
                "LWF_RATE_MISSING", "ERROR",
                f"LWF applies but no LWF rate is set up for state {state or '(none)'}",
            ))  # fmt: skip
        else:
            if not rate.get("verified"):
                issues.append(StatutoryIssue(
                    "STATUTORY_UNVERIFIED", "ERROR",
                    f"The LWF rate for {state} has not been verified by compliance",
                ))  # fmt: skip
            p = rate["parameters"]
            if month_end.month in [int(m) for m in p.get("months", [])]:
                slab = _slab(p.get("slabs", []), gross_minor, None)
                if slab is not None:
                    common = {"rate_id": rate["id"], "gross_minor": gross_minor, "slab": slab}
                    if int(slab.get("employee_minor", 0)):
                        lines.append(_line("LWF_EMPLOYEE", "Labour welfare fund", "DEDUCTION",
                                           int(slab["employee_minor"]), 140,
                                           formula=f"{state} LWF", **common))  # fmt: skip
                    if int(slab.get("employer_minor", 0)):
                        lines.append(_line("LWF_EMPLOYER", "Employer LWF",
                                           "EMPLOYER_CONTRIBUTION", int(slab["employer_minor"]),
                                           195, formula=f"{state} LWF", **common))  # fmt: skip

    # One STATUTORY_UNVERIFIED issue per scheme is enough to explain; drop exact duplicates.
    unique: list[StatutoryIssue] = []
    for issue in issues:
        if issue not in unique:
            unique.append(issue)
    return StatutoryResult(lines, unique)
