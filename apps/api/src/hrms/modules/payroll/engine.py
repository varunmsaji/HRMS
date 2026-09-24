"""Pure pay-run computation (payroll plan Phase 5.2, `docs/modules/payroll/
00_PAYROLL_IMPLEMENTATION_PLAN.md` §3–4). No DB, no I/O: one employee's pay for one month is a
function of the inputs snapshotted when the run's inputs were locked (ADR-0005), so recomputing a
run always gives the same answer and every figure carries its trace (FR-PAY-024).

Rules applied here:

- **Proration by calendar days** (decision 17): a prorated component pays
  `monthly amount × paid days ÷ days in the month`. Loss of pay is therefore already excluded
  from every prorated earning — there is no separate LOP deduction line (it would count LOP
  twice). Not-employed days are neither paid nor LOP (decision 2).
- **Mid-month changes** (a CTC revision, a new structure version, a transfer between legal
  entities): the month is split into segments over which every input is constant. Paid days are
  apportioned to segments by their employed days; each segment pays its own monthly amounts.
- **Overtime** (D3): hourly rate = full-month Basic ÷ (days in month × 8); pay = hours × hourly
  rate × the multiplier of the overtime policy version that applied that day. A daily-wage
  employee's hourly rate is the daily rate ÷ 8. OT minutes with no multiplier configured are an
  error, never paid at a guessed rate.
- **Leave encashment** (D4): per day, full-month Basic ÷ days in month (a daily-wage employee's
  daily rate).
- **Daily-wage** (D5): daily rate × paid days.
- **No net rounding** (D8, decided 2026-09-24): net pay is paid to the paisa. Each line is
  rounded half-up to the paisa; nothing is rounded to the rupee.
- **D6**: statutory deductions arrive in Phase 5.3; until then an employee who is PF- or
  ESI-applicable in the month is an error, so such a run cannot be approved or finalised.

Money is integer paise; days and rates are `Decimal` until the final rounding to paise
(ROUND_HALF_UP)."""

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

ERROR = "ERROR"
WARNING = "WARNING"

_ZERO = Decimal(0)
_HOURS_PER_DAY = Decimal(8)
_MINUTES_PER_HOUR = Decimal(60)


@dataclass(frozen=True)
class Issue:
    code: str
    severity: str  # ERROR blocks approval; WARNING is shown only
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "severity": self.severity, "message": self.message}


@dataclass(frozen=True)
class SegmentLine:
    """One component of a segment's salary breakup, as a full-month amount."""

    component_code: str
    component_name: str
    component_type: str  # EARNING / EMPLOYER_CONTRIBUTION
    monthly_minor: int
    is_prorated: bool
    display_order: int


@dataclass(frozen=True)
class Segment:
    """Days in the month over which every pay input is constant. `valid` is False when the
    snapshot could not resolve a pay for it (an error was recorded then) — its days still count
    when apportioning paid days, so they are never paid at another segment's rate."""

    date_from: date
    date_to: date
    employed_days: int
    pay_basis: str | None  # MONTHLY / DAILY_WAGE
    valid: bool
    daily_rate_minor: int | None = None
    pf_applicable: bool = False
    esi_applicable: bool = False
    lines: tuple[SegmentLine, ...] = ()


@dataclass(frozen=True)
class OvertimeInput:
    day_class: str
    multiplier: Decimal | None
    minutes: int


@dataclass(frozen=True)
class EncashmentInput:
    ledger_entry_id: str
    days: Decimal
    effective_date: date


@dataclass(frozen=True)
class EmployeeInput:
    days_in_month: int
    paid_days: Decimal | None  # None: a summary frozen before PAY-002 — refused
    has_summary: bool
    segments: tuple[Segment, ...]
    overtime: tuple[OvertimeInput, ...] = ()
    encashments: tuple[EncashmentInput, ...] = ()
    bank: dict[str, Any] | None = None
    snapshot_issues: tuple[Issue, ...] = ()


@dataclass(frozen=True)
class ComputedLine:
    component_code: str
    component_name: str
    line_type: str  # EARNING / DEDUCTION / EMPLOYER_CONTRIBUTION / ROUNDING
    full_monthly_minor: int | None
    amount_minor: int
    display_order: int
    trace: dict[str, Any]


@dataclass(frozen=True)
class EmployeeResult:
    lines: list[ComputedLine] = field(default_factory=list)
    gross_minor: int = 0
    deductions_minor: int = 0
    employer_contributions_minor: int = 0
    net_before_rounding_minor: int = 0
    rounding_minor: int = 0
    net_minor: int = 0
    issues: list[Issue] = field(default_factory=list)

    @property
    def has_error(self) -> bool:
        return any(issue.severity == ERROR for issue in self.issues)


def _paise(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _num(value: Decimal) -> str:
    return format(value.normalize(), "f") if value != 0 else "0"


@dataclass
class _Accumulator:
    name: str
    line_type: str
    display_order: int
    full: Decimal = _ZERO
    amount: Decimal = _ZERO
    parts: list[dict[str, Any]] = field(default_factory=list)


def compute_employee(inputs: EmployeeInput) -> EmployeeResult:
    issues = list(inputs.snapshot_issues)
    days = Decimal(inputs.days_in_month)

    if not inputs.has_summary:
        return EmployeeResult(issues=issues)  # the snapshot already recorded why
    if inputs.paid_days is None:
        issues.append(Issue(
            "SUMMARY_UNUSABLE", ERROR,
            "The attendance summary has no paid days (frozen before paid days existed) — "
            "reopen and close the attendance period again",
        ))  # fmt: skip
        return EmployeeResult(issues=issues)

    total_employed = sum(s.employed_days for s in inputs.segments)
    if total_employed == 0:
        if inputs.paid_days > 0:
            issues.append(Issue(
                "NOT_EMPLOYED", ERROR,
                "The attendance summary has paid days but the employee has no employment in "
                "this legal entity during the month",
            ))  # fmt: skip
        return EmployeeResult(issues=issues)

    accumulators: dict[str, _Accumulator] = {}
    basic_full = _ZERO  # full-month Basic, weighted across segments (D3/D4 base)
    gross_full = _ZERO
    daily_rate: Decimal | None = None
    basis_of_last: str | None = None
    statutory = False

    for segment in inputs.segments:
        weight = Decimal(segment.employed_days) / Decimal(total_employed)
        paid = inputs.paid_days * weight
        if not segment.valid:
            continue
        basis_of_last = segment.pay_basis
        statutory = statutory or segment.pf_applicable or segment.esi_applicable
        span = {
            "from": segment.date_from.isoformat(),
            "to": segment.date_to.isoformat(),
            "employed_days": segment.employed_days,
            "paid_days": _num(paid),
        }
        if segment.pay_basis == "DAILY_WAGE":
            rate = Decimal(segment.daily_rate_minor or 0)
            daily_rate = rate
            acc = accumulators.setdefault("DAILY_WAGES", _Accumulator("Daily wages", "EARNING", 5))
            acc.amount += rate * paid
            acc.parts.append({**span, "daily_rate_minor": int(rate)})
            continue
        for line in segment.lines:
            monthly = Decimal(line.monthly_minor)
            acc = accumulators.setdefault(
                line.component_code,
                _Accumulator(line.component_name, line.component_type, line.display_order),
            )
            full = monthly * weight
            acc.full += full
            acc.amount += monthly * paid / days if line.is_prorated else full
            acc.parts.append({**span, "monthly_minor": line.monthly_minor,
                              "prorated": line.is_prorated})  # fmt: skip
            if line.component_type == "EARNING":
                gross_full += full
                if line.component_code == "BASIC":
                    basic_full += full

    if statutory:
        issues.append(Issue(
            "STATUTORY_PENDING", ERROR,
            "PF or ESI applies to this employee — statutory deductions are not available yet "
            "(Phase 5.3), so this run cannot be finalised (D6)",
        ))  # fmt: skip

    # Base for overtime and encashment rates.
    if basis_of_last == "DAILY_WAGE" and daily_rate is not None:
        hourly = daily_rate / _HOURS_PER_DAY
        day_rate = daily_rate
        rate_basis = "daily rate"
    else:
        base = basic_full
        rate_basis = "Basic"
        if base == 0 and gross_full > 0 and (inputs.overtime or inputs.encashments):
            base = gross_full
            rate_basis = "gross (no Basic component)"
            issues.append(Issue(
                "BASIC_MISSING", WARNING,
                "The salary structure has no BASIC component — overtime and encashment are "
                "paid on gross",
            ))  # fmt: skip
        hourly = base / (days * _HOURS_PER_DAY)
        day_rate = base / days

    overtime_parts: list[dict[str, Any]] = []
    overtime_amount = _ZERO
    for ot in inputs.overtime:
        if ot.minutes <= 0:
            continue
        if ot.multiplier is None:
            issues.append(Issue(
                "OT_MULTIPLIER_MISSING", ERROR,
                f"{ot.minutes} approved overtime minutes ({ot.day_class}) have no multiplier in "
                "the overtime policy — set one and lock the inputs again",
            ))  # fmt: skip
            continue
        amount = Decimal(ot.minutes) / _MINUTES_PER_HOUR * hourly * ot.multiplier
        overtime_amount += amount
        overtime_parts.append({
            "day_class": ot.day_class, "minutes": ot.minutes,
            "multiplier": _num(ot.multiplier), "amount_minor": _paise(amount),
        })  # fmt: skip
    if overtime_parts:
        accumulators["OVERTIME"] = _Accumulator(
            "Overtime", "EARNING", 80, amount=overtime_amount, parts=overtime_parts
        )

    encash_parts: list[dict[str, Any]] = []
    encash_amount = _ZERO
    for entry in inputs.encashments:
        amount = entry.days * day_rate
        encash_amount += amount
        encash_parts.append({
            "ledger_entry_id": entry.ledger_entry_id, "days": _num(entry.days),
            "effective_date": entry.effective_date.isoformat(), "amount_minor": _paise(amount),
        })  # fmt: skip
    if encash_parts:
        accumulators["LEAVE_ENCASHMENT"] = _Accumulator(
            "Leave encashment", "EARNING", 85, amount=encash_amount, parts=encash_parts
        )

    lines: list[ComputedLine] = []
    for code, acc in accumulators.items():
        if code == "OVERTIME":
            formula = f"hours × ({rate_basis} ÷ ({inputs.days_in_month} days × 8 h)) × multiplier"
            extra = {"hourly_rate_minor": _num(hourly.quantize(Decimal("0.0001")))}
        elif code == "LEAVE_ENCASHMENT":
            formula = f"days × ({rate_basis} ÷ {inputs.days_in_month} days)"
            extra = {"day_rate_minor": _num(day_rate.quantize(Decimal("0.0001")))}
        elif code == "DAILY_WAGES":
            formula = "daily rate × paid days"
            extra = {}
        else:
            formula = f"monthly amount × paid days ÷ {inputs.days_in_month} days"
            extra = {}
        is_monthly_component = code not in ("OVERTIME", "LEAVE_ENCASHMENT", "DAILY_WAGES")
        lines.append(ComputedLine(
            component_code=code,
            component_name=acc.name,
            line_type=acc.line_type,
            full_monthly_minor=_paise(acc.full) if is_monthly_component else None,
            amount_minor=_paise(acc.amount),
            display_order=acc.display_order,
            trace={"formula": formula, "days_in_month": inputs.days_in_month,
                   "paid_days": _num(inputs.paid_days), "parts": acc.parts, **extra},
        ))  # fmt: skip

    gross = sum(line.amount_minor for line in lines if line.line_type == "EARNING")
    deductions = sum(line.amount_minor for line in lines if line.line_type == "DEDUCTION")
    employer = sum(line.amount_minor for line in lines if line.line_type == "EMPLOYER_CONTRIBUTION")
    # D8 (2026-09-24): net pay is not rounded — it is paid to the paisa. `rounding_minor` and the
    # `ROUNDING` line type stay in the schema so rounding can be switched on later without a
    # migration.
    net_raw = gross - deductions
    net = net_raw
    rounding = 0
    lines.sort(key=lambda line: (line.display_order, line.component_code))

    if net < 0:
        issues.append(Issue("NEGATIVE_NET", ERROR, "Net pay is negative"))
    elif net == 0:
        issues.append(Issue("ZERO_NET", WARNING, "Net pay is zero for an employed employee"))

    if net > 0:
        bank = inputs.bank
        if bank is None:
            issues.append(Issue("BANK_MISSING", ERROR, "No bank or payment details on file"))
        elif bank.get("payment_mode") == "BANK" and not bank.get("account_last4"):
            issues.append(Issue(
                "BANK_ACCOUNT_MISSING", ERROR, "Paid by bank transfer but no account number"
            ))  # fmt: skip

    return EmployeeResult(
        lines=lines,
        gross_minor=gross,
        deductions_minor=deductions,
        employer_contributions_minor=employer,
        net_before_rounding_minor=net_raw,
        rounding_minor=rounding,
        net_minor=net,
        issues=issues,
    )


# ---------------------------------------------------------------------------
# Snapshot (JSONB) ⇄ engine input
# ---------------------------------------------------------------------------


def employee_input_from_snapshot(snapshot: dict[str, Any], days_in_month: int) -> EmployeeInput:
    """The inverse of what `PayRunService` writes at lock-inputs — kept next to the engine so the
    snapshot shape has one reader."""
    summary = snapshot.get("summary")
    paid = summary.get("paid_days") if summary else None
    return EmployeeInput(
        days_in_month=days_in_month,
        paid_days=Decimal(paid) if paid is not None else None,
        has_summary=summary is not None,
        segments=tuple(
            Segment(
                date_from=date.fromisoformat(s["from"]),
                date_to=date.fromisoformat(s["to"]),
                employed_days=int(s["employed_days"]),
                pay_basis=s.get("pay_basis"),
                valid=bool(s.get("valid")),
                daily_rate_minor=s.get("daily_rate_minor"),
                pf_applicable=bool(s.get("pf_applicable")),
                esi_applicable=bool(s.get("esi_applicable")),
                lines=tuple(
                    SegmentLine(
                        component_code=line["component_code"],
                        component_name=line["component_name"],
                        component_type=line["component_type"],
                        monthly_minor=int(line["monthly_minor"]),
                        is_prorated=bool(line["is_prorated"]),
                        display_order=int(line["display_order"]),
                    )
                    for line in s.get("lines", [])
                ),
            )
            for s in snapshot.get("segments", [])
        ),
        overtime=tuple(
            OvertimeInput(
                day_class=o["day_class"],
                multiplier=Decimal(o["multiplier"]) if o.get("multiplier") is not None else None,
                minutes=int(o["minutes"]),
            )
            for o in snapshot.get("overtime", [])
        ),
        encashments=tuple(
            EncashmentInput(
                ledger_entry_id=e["ledger_entry_id"],
                days=Decimal(e["days"]),
                effective_date=date.fromisoformat(e["effective_date"]),
            )
            for e in snapshot.get("encashments", [])
        ),
        bank=snapshot.get("bank"),
        snapshot_issues=tuple(
            Issue(i["code"], i["severity"], i["message"]) for i in snapshot.get("issues", [])
        ),
    )
