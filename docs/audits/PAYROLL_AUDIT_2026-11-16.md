# Payroll — End-to-End Financial Correctness Audit

**Date:** 16 November 2026 · **Branch:** `test` at `dd71571` · **No code changed.**

Builds on `ATTENDANCE_CALENDAR_OVERTIME_AUDIT_2026-11-16.md` (findings AC-01 … AC-09) and
`LEAVE_MANAGEMENT_AUDIT_2026-11-16.md`. Findings from those audits are referenced here, not
repeated.

**Evidence levels**

- **Reproduced** — shown by running the pure pay engine (`payroll/engine.py`, `income_tax.py`,
  `statutory.py`) with constructed inputs. No database involved. Appendix A lists the scenarios.
- **Code** — confirmed by reading every code path involved; not run end to end.
- **Plausible** — a risk the code allows but that was not reproduced. Never counted as a bug.

**What was not done.** The payroll integration tests could not be run in this session: on the
shared `hrms_test` database the test fixtures fail during setup (`invalid input syntax for type
uuid: ""` in a cleanup `DELETE FROM subscription`), before any payroll code runs. The 107 pure
unit tests pass. So everything that depends on the database — lifecycle transitions, concurrency
guards, the immutability triggers, tenant isolation — is **code-confirmed, not reproduced**.
Concurrency was not actively attacked. Web and mobile were checked only for client-side money
arithmetic and action coverage.

---

## 1. Executive summary

**Verdict: 🔴 NOT PAYROLL-READY as an end-to-end chain. The payroll module itself is close to
🟡.**

The payroll module is well built. One employee's pay is a pure function of a snapshot taken when
inputs are locked. Money is integer paise. There is no separate LOP line, so LOP cannot be
deducted twice. A finalised run is protected by status-guarded writes *and* database triggers.
Approval and finalisation rebuild the snapshot from live data and refuse if anything changed.
Arrears are paid once, guarded by a unique index. For every result the engine returns,
`gross − deductions = net` holds by construction.

It is not ready for real salaries for three reasons:

| # | Reason | Where |
|---|---|---|
| 1 | The overtime minutes payroll pays can exceed the overtime actually worked, and can be priced at the wrong rate class. Payroll trusts `attendance_day.ot_minutes_approved` with no cross-check. | AC-01, AC-04, AC-05 (attendance audit) → PY-02 |
| 2 | Income tax on arrears is deducted twice in effect: the arrears month's tax is recomputed and deducted as its own line, and that line is never counted in the year-to-date tax. | PY-01 (new, reproduced) |
| 3 | Money owed to, or by, someone who has left is never settled, and nothing except paid days can be corrected after finalisation. | PY-03, PY-06 (new, code) |

Seven further findings and twelve policy decisions follow. Section 11 lists exactly what must be
done before the first real run.

A company with **no overtime, no backdated salary changes, no day corrections and no taxable
employees** would get correct pay from the current code, subject to the statutory rates being
verified. That is a narrow case, and the system does not enforce it.

---

## 2. Architecture map

| Component | Source of truth | Table | Service | API | Calculation |
|---|---|---|---|---|---|
| Pay period | Calendar month per legal entity; unique per (entity, month) | `pay_run` | `PayRunService.create` | `POST /payroll/pay-runs` | `month_bounds` |
| Eligibility | Employment spans in the entity during the month, plus anyone in the attendance summary | `employment`, `attendance_period_summary` | `_build_snapshots` | lock-inputs | set union, one row per employee |
| CTC | Effective-dated compensation rows (insert-only) | `employee_compensation` | `EmployeeCompensationService` | employee module | — |
| Salary structure | Versioned template; published versions immutable, effective-dated | `salary_structure`, `_version`, `_line` | `SalaryStructureService` | `/payroll/salary-structures` | `breakup.compute_breakup` |
| Component master | Per company; **not** effective-dated | `salary_component` | `SalaryComponentService` | `/payroll/salary-components` | flags read at lock-inputs |
| Salary assignment | Effective-dated; structure (monthly) or daily rate (daily wage) | `employee_salary` | `EmployeeSalaryService` | `/employees/{id}/salary…` | — |
| Paid days / LOP | Frozen summary of a `CLOSED` attendance period for exactly that month | `attendance_period_summary` | `AttendancePeriodService.closed_period_for_month` | — | attendance engine |
| Overtime | Locked days: approved minutes, not converted to comp-off, grouped by day class and policy multiplier | `attendance_day`, `overtime_policy_rate_row` | `list_payable_overtime_for_period` | — | `engine` (D3) |
| Leave encashment | Ledger `ENCASHMENT` entries effective in the month | `leave_ledger` | `LeaveLedgerService.list_encashments_between` | — | `engine` (D4) |
| Statutory rates | Effective-dated, per company, must be verified by a second person | `statutory_rate` | `StatutoryRateService` | `/payroll/statutory-rates` | `statutory.compute_statutory` |
| Income tax | Statutory profile + year-to-date from finalised runs + TDS rate | `pay_run_line`, `statutory_rate` | `_income_tax` | — | `income_tax.compute_tds` |
| Arrears | Earlier finalised months, re-snapshotted with current salary data | `pay_run_arrear`, `pay_adjustment` | `_arrears_for` | `/payroll/adjustments` | `engine._arrears` |
| Run result | Snapshot + computed lines with trace | `pay_run_employee`, `pay_run_line` | `PayRunService.compute` | compute | `engine.compute_employee` |
| Payslip | Run lines + header facts frozen at finalise | `pay_run_employee.payslip_details` | `PayslipService` | `/me/payslips`, `/payroll/pay-runs/{id}/payslips/{emp}` | none (read-only) |
| Bank file | Built on demand from the snapshot's bank reference | — (not stored) | `PayslipService.bank_advice` | `GET …/bank-advice` | none |

**Not supported at all:** reimbursements, bonus, incentives, commission, loans and advances,
one-off earnings or deductions, structure-level deductions, final settlement (gratuity, notice
pay), off-cycle runs, salary holds, old tax regime, investment declarations, accounting export,
payment status per employee. There are no payroll background jobs; every action runs inside the
HTTP request.

---

## 3. Calculation formula map

`D` = days in the calendar month. Each line is rounded half-up to the paisa unless stated.

| Amount | Formula | Inputs | Source |
|---|---|---|---|
| Monthly CTC | annual CTC ÷ 12 | `employee_compensation.annual_ctc_minor` | `breakup.monthly_from_annual` |
| Component monthly amount | fixed, or % of CTC / gross / another component; rounded to the rupee; one balancing earning absorbs the rest so gross + employer lines = monthly CTC | structure version in force on the segment's first day | `breakup.compute_breakup` |
| Segment | Days over which employment, CTC, statutory profile, salary assignment and structure version are all constant | effective dates of those rows | `PayRunService._segments` |
| Paid days per segment | month's paid days × segment employed days ÷ total employed days | attendance summary | `engine.py:292` — see PY-04 |
| Prorated earning | Σ segments: monthly × segment paid days ÷ `D` | — | `engine.py:328` |
| Non-prorated earning | Σ segments: monthly × segment employed days ÷ total employed days | — | `engine.py:328` — see P-2 |
| Daily wages | daily rate × paid days | `employee_salary.daily_rate_minor` | engine |
| LOP | No line. Excluded by paid days. | — | by design (decision 17) |
| Overtime | minutes ÷ 60 × (full-month Basic ÷ (`D` × 8)) × multiplier. Daily wage: daily rate ÷ 8. No Basic: gross, with a warning. | locked days, policy multiplier | engine (D3) |
| Leave encashment | days × full-month Basic ÷ `D` | leave ledger | engine (D4) |
| PF employee | 12 % of PF wages, capped at the ceiling unless opted out; rupee | components flagged `is_pf_wage`; rate row | `statutory.py` |
| PF employer | 12 % split into EPS (8.33 % up to ceiling, none from age 58) and EPF; EDLI; admin | same | `statutory.py` |
| VPF | fixed amount or % of PF wages | statutory profile | `statutory.py` |
| ESI | employee 0.75 %, employer 3.25 % of ESI wages (flagged components + overtime), rounded **up** to the rupee; employee share waived at or below the daily-wage limit | statutory profile, rate row | `statutory.py` |
| Professional tax | state slab on the month's gross; gender slabs; month overrides | PT state, rate row | `statutory.py` |
| LWF | state slab, only in listed months | rate row | `statutory.py` |
| Arrears | per earlier month and component: recomputed amount − amount already paid (run + later arrears) | earlier snapshot + current salary data + day corrections | `engine._arrears` |
| Gross | Σ `EARNING` lines, including arrears earnings | — | engine |
| TDS | (tax on (YTD gross + this month's gross × months left) − TDS so far) ÷ months left; rupee | finalised runs of this entity, TDS rate | `income_tax.compute_tds` |
| Deductions | Σ `DEDUCTION` lines | — | engine |
| Net | gross − deductions. Not rounded (D8). | — | engine |
| Employer cost lines | Shown, never part of net | — | engine |

Rounding happens in four places only: the structure breakup (rupee), each pay line (paisa),
statutory amounts (rupee; ESI up), TDS (rupee). No floating point is used anywhere in the engine.
Web and mobile convert paise to rupees for display only.

---

## 4. Lifecycle

```
DRAFT → INPUTS_LOCKED → COMPUTED → APPROVED → FINALISED → PAID
          ↑______rollback (to DRAFT or INPUTS_LOCKED) from any state before FINALISED
```

| Transition | Permission | Checks | Repeat / concurrent call |
|---|---|---|---|
| create | `RUN_PROCESS` | active legal entity; unique (entity, month) | second insert → "already exists" |
| lock inputs | `RUN_PROCESS` | status `DRAFT`; attendance period for exactly the month is `CLOSED` | version + status guard; `UNIQUE (pay_run_id, employee_id)` |
| compute | `RUN_PROCESS` | `INPUTS_LOCKED` or `COMPUTED`; reads the snapshot only | recompute replaces lines; same snapshot → same result |
| acknowledge variance | `RUN_PROCESS` | `COMPUTED`; employee is flagged | idempotent |
| approve | `RUN_APPROVE` | no employee errors; no open variances; approver ≠ user who computed; attendance period unchanged; rebuilt snapshot equals stored snapshot | version guard |
| finalise | `RUN_APPROVE` | advisory locks (entity, then period); re-reads; arrears not already paid; snapshot still current; corrections applied exactly once; payslip header frozen | version guard; unique index on arrears payment number |
| mark paid | `RUN_APPROVE` | `FINALISED` | version guard; a flag only |
| rollback | `RUN_PROCESS` | before `FINALISED` only | version guard |
| delete | `RUN_PROCESS` | `DRAFT` only | — |

There is no reopen of a finalised run, by design. The attendance period cannot be reopened once
its run is finalised. Both rules are enforced.

---

## 5. Integration matrix

| Source | Payroll input | What happens when the source changes | Risk |
|---|---|---|---|
| Shift | None directly; through attendance days | Recalculation queue (fixed 15 Nov) before period close | Low |
| Holiday / weekly off | None directly; through attendance days | **No recalculation** until period close; close recalculates first | AC-02: correct at close, stale before |
| Leave | Paid/LOP fractions inside attendance days; encashment entries | Approval and cancellation recalculate the day. Refused in a closed period. | AC-03: leave charged on a later-added holiday, or LOP inside approved leave |
| Attendance | `paid_days`, `lop_days`, `payable_days` from the frozen summary | Run can lock only on a `CLOSED` period. Reopen changes the period version → approve and finalise refuse. | Low. Invariant `paid + lop + unpaid_off = payable` checked at close and again in the engine. |
| Overtime | `ot_minutes_approved`, day row's `ot_day_class`, day row's policy version multiplier | Frozen once the period is closed | **Critical** — AC-01, AC-04, AC-05, AC-06 (PY-02) |
| Salary / CTC / structure / statutory profile / bank | Snapshot at lock-inputs | Change after lock → approve and finalise refuse (`PayRunInputsChangedError`). Change after finalise → arrears in the next run. | PY-01, PY-03, PY-04 |
| Statutory rates | Snapshot at lock-inputs | Edit clears verification → run cannot be approved | Low |

---

## 6. Use-case coverage

| Scenario | Expected | Actual | Status |
|---|---|---|---|
| Full month, 60,000 gross | 60,000 | 60,000 | PASS (reproduced) |
| 1 LOP day in a 30-day month | 58,000 | 58,000; no LOP line | PASS (reproduced) |
| Half-day LOP | 59,000 | 59,000 | PASS (reproduced) |
| Join on the 15th, Basic 30,000 | 16,000 | 16,000 | PASS (reproduced) |
| Join on the last day | 1,000 | 1,000 | PASS (reproduced) |
| Exit mid-month | Paid to the last working day | Same proration; no final settlement | PASS; see P-6 |
| Revision on the 15th, no LOP | Each part at its own rate | As expected | PASS (existing test) |
| Revision on the 15th, 5 LOP days in the first half | 30,333.33 | **29,444.44** | **PY-04** (reproduced) |
| Non-prorated allowance, exit on the 1st | Decision needed | Full 5,000 paid | P-2 (reproduced) |
| Non-prorated allowance, zero paid days | Decision needed | Full 5,000 paid | P-2 (reproduced) |
| Zero paid days, PF/ESI employee | Zero pay, warning | Net 0, `ZERO_NET` warning | PASS (reproduced) |
| Deductions exceed earnings (fixed VPF, 2 paid days) | Decision needed | `NEGATIVE_NET` error; whole run cannot be approved | P-4 (reproduced) |
| Overtime 10 h × 2, Basic 30,000 | Depends on divisor | 2,678.57 in February; 2,419.35 in March | P-1 (reproduced) |
| Overtime with zero paid days | Decision needed | Overtime still paid | PASS as coded; see PY-02 |
| Overtime pending or rejected | Not paid | Not paid (`ot_minutes_approved > 0`) | PASS (code) |
| Overtime converted to comp-off | Not paid in money | Whole day excluded | PASS (code) |
| Overtime corrected after auto-approval | Follows the correction | **Frozen minutes paid** | **PY-02 / AC-01** |
| Holiday and weekly-off pay | From attendance | From `paid_days`; payroll adds nothing | PASS (code) |
| Paid days greater than employed days | Refused | `PAID_DAYS_EXCEED_EMPLOYED` | PASS (code) |
| No salary / no CTC / wrong pay basis | Refused | Error on the employee; run cannot be approved | PASS (code) |
| Future-dated revision | No effect now | Effective-dated lookup | PASS (code) |
| Backdated revision into a finalised month | Arrears next run, once | `ARR_*` lines; unique payment number | PASS (code); but PY-01 |
| Backdated revision, taxable employee | Tax once | **Extra 11,808 deducted and never credited** | **PY-01** (reproduced) |
| Day correction after finalise | Arrears next run | Works for paid days only | PASS; PY-06 |
| Missed overtime after finalise | Paid next run | **No mechanism** | **PY-06** |
| Correction or revision for someone who has left | Paid or recovered | **Never processed** | **PY-03** |
| Leave approved after inputs locked | Refused or run invalidated | Refused (period closed) | PASS (code) |
| Attendance reopened after inputs locked | Run invalidated | Approve and finalise refuse | PASS (code) |
| Salary changed after inputs locked | Run invalidated | Approve and finalise refuse | PASS (code) |
| Compute twice | Same result | Lines replaced, deterministic | PASS (code) |
| Finalise twice / two runs concurrently | One wins | Advisory lock + status guard | PASS (code) |
| Change a finalised run | Refused | Repository guard + triggers | PASS (code) |
| Payslip after profile change | Unchanged | Header frozen at finalise | PASS (code) |
| Employee reads another's payslip | Not found | Own employee id only, finalised runs only | PASS (code) |
| Annual income 12,75,600 (₹600 over the rebate line) | About ₹624 tax a year | **₹62,496 a year** | P-7 (reproduced) |
| February / leap year / year end | Correct month length | `calendar.monthrange` | PASS (code) |
| Financial-year boundary | April starts a new YTD | `financial_year_start` | PASS (existing tests) |
| Business date | Asia/Kolkata | `business_today(company.timezone)`; no `date.today()` in the module | PASS (code) |

---

## 7. Confirmed bugs

### PY-01 — Tax on arrears is deducted and then forgotten (High, reproduced)

**Where.** `PayRunService._arrears_for` (`payroll/service.py:2766`), `engine._arrears`,
`PayRunRepository.ytd_income_tax_totals` (`payroll/repository.py:730`).

**Root cause.** The design, stated in `income_tax.py` and in `EmployeeInput`, is that TDS is
never recomputed for a historical month: arrears are taxed in the month they are paid. But
`_arrears_for` builds the earlier month's snapshot as `{**row.snapshot, …}`, which carries that
month's `income_tax` block along. So the engine recomputes that month's TDS on the new gross and
emits the difference as an `ARR_TDS_EMPLOYEE` deduction. The current month's TDS is then computed
on a gross that already includes the arrears. Finally, the year-to-date query counts only lines
whose code is exactly `TDS_EMPLOYEE`, so the `ARR_TDS_EMPLOYEE` amount is never treated as tax
already deducted.

**Reproduction (engine).** April finalised at 1,50,000 a month, TDS 12,567. Salary revised to
2,00,000 from 1 April; May's run pays April's arrears.

- May: `ARR_BASIC` 50,000, `TDS_EMPLOYEE` 39,276, **`ARR_TDS_EMPLOYEE` 11,808**.
- Run the rest of the year at 2,00,000. Income 24,00,000. Correct annual tax: 2,92,500.
- Total actually deducted: **3,04,308** — over by exactly the 11,808.

**Expected.** One tax computation, in the month of payment. No `ARR_TDS_EMPLOYEE` line.

**Financial impact.** Every taxable employee who receives arrears is over-taxed by the arrears
month's recomputed difference, and it is never given back within the system. A downward day
correction does the reverse: a negative `ARR_TDS_EMPLOYEE` refunds tax that the year-to-date then
ignores, so the employee is under-taxed. Form 16 figures built from `TDS_EMPLOYEE` alone would
not match what was withheld.

**Related.** If the earlier run was locked before TDS existed (no `income_tax` block), the
recompute produces no TDS line while `paid` still holds one, so the whole of that month's TDS
would be refunded. This applies only if such runs exist in production data.

**Recommended fix.** In `_arrears_for`, set `income_tax` to `None` in the nested snapshot and
leave `TDS_EMPLOYEE` out of `paid` (both, or the second case above appears). Add an engine test
that an arrears item never yields an `ARR_TDS_*` line. If any run has already paid such a line,
find it with `component_code = 'ARR_TDS_EMPLOYEE'` and settle it by hand.

### PY-02 — Payroll pays whatever overtime the day row says (Critical, inherited; code)

**Where.** `AttendanceDayRepository.list_payable_overtime_for_period`
(`attendance/repository.py:1512`), consumed by `_build_snapshots`.

**Root cause.** Payroll sums `attendance_day.ot_minutes_approved`, grouped by the day row's
`ot_day_class`, priced by the day row's overtime policy version. It applies no check of its own.
The attendance audit showed this figure is unreliable:

- **AC-01:** approved minutes frozen after a correction, so approved can exceed detected, and the
  frozen minutes are priced at the day's *new* class.
- **AC-04:** overtime kept on a day resolved as absent at lock.
- **AC-05:** half-day leave overtime measured against the full shift.
- **AC-06:** roster day-off work priced as a normal day.

Nothing has changed in that code since (`dd71571`).

**Financial impact.** Overpayment or underpayment of overtime, flowing into ESI wages, gross,
professional tax slab and TDS. Example from AC-01: 600 minutes paid at the normal multiplier for
60 real minutes.

**Recommended fix.** Fix AC-01, AC-04 and AC-05 in attendance. Independently, add a guard on the
payroll side so the two modules cannot drift again: at lock-inputs, raise an employee error when
any locked day has `ot_minutes_approved > ot_minutes_detected`, or a day class different from its
`overtime_record`.

### PY-03 — Arrears and corrections for people who have left are never processed (High, code)

**Where.** `_build_snapshots` (`payroll/service.py:2837`), `engine.compute_employee`
(`engine.py:248`), `PayAdjustmentService.create`.

**Root cause.** A run includes an employee only if they have an employment span in the entity
during the run's month or a row in that month's attendance summary. Arrears are computed inside
that loop. Someone who left in an earlier month is in neither set. Even if they were, the engine
returns early when `total_employed == 0`, before the arrears step.

**Reproduction (by reading).**
1. September run finalised. The employee's last day was 20 September.
2. HR records a `+2` day correction against September, or a backdated revision covering it.
3. October's run does not contain the employee. The correction stays `PENDING` for ever. Creating
   it gives no warning.

**Financial impact.** Underpaid leavers are never paid; overpaid leavers are never recovered. The
same applies to a transfer out of the legal entity.

**Also.** A correction against a run more than 12 months old is accepted but never applied
(`ARREARS_LOOKBACK_MONTHS = 12`), again silently.

**Recommended fix.** See P-6. At minimum: refuse (or clearly warn on) a correction that no future
run can apply, and report pending corrections and unpaid revisions for leavers on the run
overview.

### PY-04 — LOP in a revision month is priced at a blended rate (Medium, reproduced)

**Where.** `engine.py:292` — `paid = inputs.paid_days * weight`.

**Root cause.** The attendance summary gives one paid-days figure for the month. When the month
is split into segments (a revision, a new structure version, a statutory profile change), paid
days are shared out in proportion to each segment's employed days, wherever the LOP actually
fell.

**Reproduction.** Basic 30,000 for 1–14 September, 40,000 from the 15th. Five LOP days, all in
the first half. Paid 25 of 30.

- Exact: 30,000 × 9/30 + 40,000 × 16/30 = **30,333.33**
- Engine: **29,444.44** — underpaid by 888.89.
- With the LOP in the second half the exact figure is 28,666.67, so the engine overpays by 777.77.

**Financial impact.** Small per case; only in months with both a mid-month change and LOP. It is
systematic and cannot be seen on the payslip.

**Recommended fix.** Have the closed attendance period provide paid days per date range (the
locked day rows hold the fractions), and snapshot paid days per segment. Until then, treat as
P-3.

### PY-05 — The "taxable" flag on a salary component does nothing (Medium, code)

**Where.** `salary_component.is_taxable`; `engine.py:475`.

**Root cause.** The flag is stored, editable through the API, and never read by any calculation.
TDS is computed on total gross.

**Financial impact.** A component marked non-taxable is taxed in full. In today's product this
matters less than it sounds, because only the new regime is supported and few exemptions apply to
it; but the screen promises something the engine does not do.

**Recommended fix.** Either use the flag (snapshot it on each segment line and exclude those
lines from the TDS base and the year-to-date), or remove it from the API and screens until it is
supported.

### PY-06 — Only paid days can be corrected after finalisation (Medium, code)

**Where.** `PayAdjustment` holds `paid_days_delta` and nothing else. The arrears recompute reuses
the earlier snapshot's `overtime` and `encashments` unchanged.

**Impact.** Missed or wrongly approved overtime in a finalised month cannot be paid or recovered
through the system. Neither can any one-off amount. The attendance period cannot be reopened
either, so the only route is outside payroll, with no record on the payslip.

**Recommended fix.** Extend corrections to carry overtime minutes (by day class) and a plain
amount with a component code, flowing through the same arrears path. See P-5.

### PY-07 — An unverified bank account does not stop payment (Low, code)

**Where.** `engine.py:508–516`; `PayslipService.bank_advice`.

The snapshot records `verification_status`, but the engine checks only that bank details exist
and that a bank-mode account has a number. The bank file includes every bank-mode employee with
positive net pay. If bank verification is meant to gate payment, it does not.

**Recommended fix.** Decide whether an unverified account is an error, a warning, or acceptable,
and code that.

---

## 8. Policy decisions required

None of these is a bug. Each needs an owner's decision; where a decision already exists it is
named and only needs confirming.

### P-1 — Overtime rate base and divisor

- **Now:** hourly rate = full-month **Basic only** ÷ (days in the month × **8**). The same ten
  hours pay 10.7 % more in February than in March. The 8 is fixed, whatever the shift length.
- **Options:** (a) keep; (b) fixed divisor (26 or 30 days); (c) base on Basic + DA, or on gross;
  (d) hours from the shift.
- **Financial impact:** every overtime payment.
- **Legal:** for staff under the Factories Act or a state Shops Act, overtime is at twice the
  "ordinary rate of wages", which is wider than Basic. **Needs legal verification.**
- **Affects:** payroll engine, overtime policy screen.

### P-2 — Components that are not prorated

- **Now:** paid in full whatever the paid days — including zero paid days and a single day of
  employment (5,000 paid to someone who exited on the 1st).
- **Options:** (a) keep; (b) full only when paid days > 0; (c) prorate by employed days but not
  by LOP.
- **Affects:** engine, component screen wording.

### P-3 — LOP in a month with a salary change (if PY-04 is not fixed)

Accept the blended rate, or require exact attribution.

### P-4 — Deductions greater than earnings

- **Now:** `NEGATIVE_NET` is an error. One such employee blocks approval of the whole run until
  the input (for example a fixed VPF) is changed.
- **Options:** (a) keep; (b) cap voluntary deductions at available pay and carry the rest
  forward; (c) allow the run to proceed with that employee excluded.
- **Affects:** engine, statutory profile, run screen. Also governs negative arrears (recovery
  larger than the month's pay).

### P-5 — Corrections after finalisation

Which corrections are allowed (paid days only today), whether they need a second approver of
their own, and whether an off-cycle run is needed. See PY-06.

### P-6 — Leavers and final settlement

How arrears, recoveries, leave encashment at exit, notice pay and gratuity are settled once the
person is no longer in a monthly run. Today: not at all. See PY-03.

### P-7 — Income tax scope

Each item is documented in `income_tax.py` as a version-1 limit. Each has a money effect:

| Limit | Effect |
|---|---|
| No marginal relief above the rebate threshold | Reproduced: ₹600 of income over the line costs ₹62,496 a year instead of about ₹624. **Needs legal verification and, almost certainly, a fix.** |
| No opening balances | A company going live mid-year, or a mid-year joiner, starts with zero year-to-date income and tax. Under-withholding. |
| Year-to-date is per legal entity | A transfer between entities resets it. |
| Projection = this month × months left | A month with arrears, encashment or heavy overtime is projected for the rest of the year: a 2,00,000 one-off on an 80,000 salary gave 38,350 TDS that month. It corrects itself in later months, but take-home swings. |
| A known exit date is ignored | Projection assumes employment to March. Over-withholding in the last months. |
| No surcharge; old regime blocks the run; no PAN blocks the run | Manual work outside the system. |

Decide which are acceptable for go-live.

### P-8 — CTC and the employer's statutory cost

The structure splits CTC using an `EMPLOYER_PF` line capped at ₹1,800. The run then ignores that
line and computes the real employer cost from the statute: PF, plus EDLI and admin charges, plus
employer ESI (3.25 %, which the default structures do not include), plus LWF. For a
ceiling-opt-out employee, employer PF is 12 % of full Basic. So the employer's actual cost can
exceed the CTC promised. Decide whether CTC is meant to include all of these.

### P-9 — Net pay to the paisa

Decided (D8, 24 Sep 2026): no rounding of net pay. Confirm that the bank accepts paise and that
payslips to the paisa are acceptable.

### P-10 — Separation of duties

- **Now:** the approver must differ from the user who last *computed*. The approver may be the
  person who locked the inputs, changed the salary, or recorded the day correction. One person
  with `RUN_APPROVE` can approve, finalise, mark paid and download the bank file.
- **Decide:** whether that is enough.

### P-11 — Month order

Runs can be created and finalised in any order. Finalising June before May means June's
year-to-date tax misses May (it catches up later) and the variance baseline is wrong. Decide
whether to enforce order.

### P-12 — Statutory figures to verify before use

The seeded rates are marked unverified and a run cannot be approved until a second person
verifies them, which is the right control. They still need checking against current law by
someone qualified:

| Item | Seeded value | Check |
|---|---|---|
| PF | 12 % / 12 %, EPS 8.33 %, ceiling ₹15,000, EDLI 0.5 %, admin 0.5 % (the ₹500 establishment minimum is not applied) | Current EPFO notifications |
| PF wage base | Components flagged `is_pf_wage`; Basic only by default | The Code on Wages definition of wages (the 50 % rule), if in force for the client |
| ESI | 0.75 % / 3.25 %, ceiling ₹21,000, exemption ₹176 a day | Contribution-period handling is manual (HR switches the profile flag) |
| Professional tax | Maharashtra and Karnataka only | Every state the client employs in; other states deduct nothing, with a warning only |
| LWF | Nothing seeded | Each state |
| Income tax | FY 2025-26 new-regime slabs, standard deduction ₹75,000, rebate to ₹12 lakh, cess 4 %, effective 1 Apr 2025 with no end date | Whether the same table is correct for FY 2026-27 |
| Not implemented | Gratuity, statutory bonus, minimum-wage check | Whether they are needed for go-live |

---

## 9. Financial data integrity risks

| Risk | Finding |
|---|---|
| Duplicate payroll for one month | Prevented: `UNIQUE (company_id, legal_entity_id, period_month)`. |
| Employee twice in a run | Prevented: `UNIQUE (pay_run_id, employee_id)`. Transfers between entities are split by span; the engine refuses paid days above employed days. |
| Component counted twice | Prevented: `UNIQUE (pay_run_employee_id, component_code)`; reserved codes refused at publish and again in the engine. |
| Double LOP | Not possible: there is no LOP line; proration is the only mechanism. |
| Duplicate overtime | Not from payroll (one sum per day class). Overstated overtime: PY-02. |
| Duplicate arrears | Prevented: finalisation lock, stale check against what has been paid, unique payment number. |
| Duplicate tax | **PY-01.** |
| Duplicate bank payment | **Not prevented by the system.** The bank file can be downloaded any number of times, in `FINALISED` and `PAID`. Each download is audited. "Paid" is a manual flag with no bank reference and no per-employee status. This is an operating-procedure risk. |
| Historical mutation | See section 10. |
| Races | Every transition is version- and status-guarded; finalisation and corrections take advisory locks. Not attacked in this audit. |

**Plausible risks (not reproduced).**

- **Long requests.** Lock-inputs, approve and finalise each build every employee's snapshot with
  several queries per employee, inside the request. Approve and finalise do it a second and third
  time. For a large entity this may exceed the request timeout. The transaction would roll back,
  so the risk is being unable to finalise, not corruption.
- **Component flags are not effective-dated.** Changing `is_prorated`, `is_pf_wage` or
  `is_esi_wage` blocks any run in flight (fail-closed), and changes how earlier months are
  recomputed the next time arrears are triggered for them.
- **Statutory profile is read once per month** (as of the last employed day) for PF, ESI and PT,
  even when it changed mid-month.

---

## 10. Historical integrity

**Is a finalised run immutable? Yes, as far as the code shows.**

- Every repository write is conditioned on the run not being `FINALISED` or `PAID`.
- Database triggers (`20261013090000`) refuse insert, update and delete on `pay_run_employee`,
  `pay_run_line` and `pay_run_arrear` under a finalised run, and allow only the `FINALISED → PAID`
  stamp on the run itself. Applied corrections are immutable too. The schema owner is exempt, for
  migrations and erasure.
- The attendance period under a finalised run cannot be reopened. Leave and ledger writes into it
  are refused.
- A later salary revision, holiday change or leave change cannot reach the stored lines. A
  revision produces arrears in a later run and leaves the original untouched.

**Is it reproducible? Mostly.**

- The snapshot holds everything the engine read: summary, segments with amounts and version ids,
  overtime, encashments, statutory profile and rates, tax inputs, arrears items. Each line holds a
  trace of how it was reached.
- **Gap:** no engine version is stored. If the engine's rules change, recomputing an old snapshot
  gives a new answer, and an arrears recompute of an old month uses today's rules. When a salary
  change or day correction triggers that recompute, any difference caused by the rule change is
  paid along with it, with nothing to tell the two apart. Attendance stores `engine_version`;
  payroll should too.
- Payslip header facts and leave balances are frozen at finalise. The bank file is rebuilt on
  demand from an insert-only bank record referenced by id, so it does not drift.

---

## 11. Remediation plan

### Phase 1 — Critical financial correctness
1. **PY-02:** fix AC-01, AC-04, AC-05 in attendance; add the payroll-side guard at lock-inputs.
2. **PY-01:** stop recomputing TDS for arrears months; exclude TDS from the arrears comparison;
   test; check production for `ARR_TDS_EMPLOYEE` lines.
3. **P-7 marginal relief:** verify and fix, or block go-live for employees near the threshold.

### Phase 2 — Attendance / leave / overtime integration
4. AC-03 (leave on holidays; LOP inside approved leave).
5. **PY-04:** paid days per segment from the closed period.
6. AC-06, and P-1 (overtime base and divisor).

### Phase 3 — Historical integrity and corrections
7. **PY-03 / P-6:** leavers — at least warn and report; ideally a settlement run.
8. **PY-06 / P-5:** corrections for overtime and one-off amounts.
9. Store an engine version on each run and in each arrears item.

### Phase 4 — Concurrency and idempotency
10. Get the payroll integration suite running again on a clean test database and run it.
11. Add concurrent tests for lock-inputs, compute and approve. Concurrency tests exist only in
    `test_p1_hardening.py` and `test_b04_adjustment_idempotency.py`; they were not run here.
12. Measure approve and finalise on a large entity; move the snapshot rebuild to a job if needed.

### Phase 5 — Policy and statutory
13. Decide P-1 … P-11.
14. P-12: verify every statutory rate; add the states the client needs.
15. **PY-05:** make the taxable flag real or remove it. Opening year-to-date balances.

### Phase 6 — Operations and UX
16. **PY-07** and the bank file: payment reference, per-employee status, a warning on repeat
    download.
17. Show pending corrections and their fate on the run overview.

---

## 12. Final answer

**Can this payroll module safely be used to calculate real employee salaries?**

### 🔴 NOT PAYROLL-READY

Against the seven success criteria:

| Criterion | Result |
|---|---|
| 1. Deterministic | Yes, for a given snapshot and engine. No engine version stored. |
| 2. Traceable | Yes. Every line carries its formula and inputs. |
| 3. No duplication | Yes for earnings, LOP and arrears. **No for tax on arrears (PY-01).** |
| 4. Correct integration | Attendance and leave: yes at period close. **Overtime: no (PY-02).** |
| 5. Historical integrity | Yes. |
| 6. Financial safety | Payroll records: yes. Bank payment: procedure only. |
| 7. Reconciliation | Yes. `gross − deductions = net` for every result, checked in every probe. |

**Must be complete before real payroll:**

1. AC-01, AC-04, AC-05 fixed, with the payroll-side overtime guard (PY-02).
2. PY-01 fixed.
3. Marginal relief verified and handled (P-7).
4. Statutory rates verified for every state in use (P-12).
5. Decisions recorded for P-1, P-2, P-4, P-6 and P-10.
6. The payroll integration tests running and green.

After those, the module is 🟡 **conditionally ready**: usable with PY-03, PY-04 and PY-06 handled
by written manual procedure until they are fixed.

---

## Appendix A — engine probes

Run as a standalone script with `PYTHONPATH=src`, importing `engine`, `income_tax` and
`statutory`. No database. The scripts were temporary and are not in the repository.

Setup: September 2026 (30 days) unless stated; Basic flagged as PF and ESI wage; PF, ESI,
Maharashtra PT and FY 2025-26 TDS rates as seeded, marked verified.

| Probe | Input | Result |
|---|---|---|
| P1 | 30,000 / 12,000 / 18,000; 29 and 29.5 paid days | 58,000; 59,000 |
| P2 | Basic 30,000 to the 14th, 40,000 after; 25 paid | 29,444.44 (exact 30,333.33 or 28,666.67) |
| P3 | Join 15th; join 30th | 16,000; 1,000 |
| P4 | Non-prorated 5,000; one employed day; zero paid days | 5,000 paid in both |
| P5 | 600 OT minutes × 2 on Basic 30,000 | 2,678.57 (28 days); 2,419.35 (31 days); paid with zero paid days |
| P6 | 20,000 gross, PF + ESI + PT | PF 1,200; ESI 150; PT 200; net 18,450; employer 1,950 |
| P6c | Same, fixed VPF 5,000, 2 paid days | Net −3,757.66, `NEGATIVE_NET` |
| P7 | Monthly gross 1,06,250 / 1,06,300 | TDS 0 / 5,208 a month |
| P7b | 80,000 a month, October gross 2,80,000 | October TDS 38,350 |
| P8 | PY-01 scenario | `ARR_TDS_EMPLOYEE` 11,808; year total 3,04,308 against 2,92,500 |

In every probe `gross − deductions = net` was asserted.
