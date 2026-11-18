# Leave Management Audit — 16 Nov 2026

Read-only audit of the Leave module and everything it feeds (attendance, shift, holidays, overtime,
payroll, period close, web, mobile). Branch `test` at `dd71571`. No product code was changed.

**How findings were checked**

- **Reproduced**: run against the throwaway `hrms_test` database with a temporary probe test
  (deleted afterwards; the scenarios are in Appendix A).
- **Traced**: confirmed by reading the code path end to end, not executed.
- Baseline: the existing leave suites (leave integration + unit, half-day, projection, leave/overtime)
  pass — 427 tests.
- Not done: no live run of web or mobile screens, no live Celery beat run. Client findings come from
  reading the client code.

---

## 1. Executive summary

**Can Leave be the authoritative source for attendance and payroll today? No — not yet.**

The everyday path is sound: apply, approve, debit, project onto attendance, cancel, refund. Balances
are an append-only ledger, every check-then-write is serialised by locks, double approval and double
accrual are blocked, tenant isolation holds, and all scheduled jobs use the company's India business
date. Paid leave, unpaid leave and half-day leave reach payroll with the right paid and LOP days.

It fails in four places that matter for money:

1. **Year end** — the lapse / carry-forward cap is computed from the wrong balance in two common
   situations, so employees end the year with too many or too few days (LV-01, LV-02, LV-03).
2. **Period close** — a month can be closed while leave requests for it are still pending; those days
   then go to payroll as absent / loss of pay and can no longer be approved (LV-04).
3. **Balance correctness at the edges** — the same half day can be booked and debited twice (LV-05);
   comp-off expiry can remove freshly earned comp-off (LV-06).
4. **Accrual gaps** — the probation switch is ignored for yearly credit (LV-07), and an employee
   skipped in the monthly run is never caught up once the 5-day window passes (LV-08).

Fix LV-01 to LV-08 and settle the policy decisions marked **blocking** in section 7 before a payroll
month or a leave-year end is run on real data.

| | Count |
|---|---|
| Confirmed bugs | 13 (4 high, 6 medium, 3 low) |
| Reproduced on the test database | 7 |
| Policy decisions required | 15 (5 blocking) |

---

## 2. Current architecture

| Piece | Where | What it does |
|---|---|---|
| Leave type | `leave/models.py` `LeaveType` | Code, name, `is_paid_default`, `requires_balance` (false = LOP-style), `is_comp_off`, statutory category. Any number of custom types. |
| Leave policy + version | `LeavePolicy`, `LeavePolicyVersion` | One policy per leave type; versions are immutable once published and effective-dated. Holds every rule (section 3). |
| Policy scope | `organisation` `PolicyAssignment`, `CalendarResolutionService.resolve_policy_assignment` | First match wins: employee → shift → designation → grade → department → branch → legal entity → company, per leave type, as of a date. |
| Balance | `leave_ledger` (`LeaveLedgerEntry`) | Append-only. Balance = sum of all entries for employee + type. Entry types: ACCRUAL, APPLICATION, ADJUSTMENT, ENCASHMENT, CARRY_FORWARD, COMP_OFF_CREDIT. |
| Application | `LeaveApplication`, `LeaveApplicationDay`, `LeaveApplicationAction` | One row per request, one row per charged date, an action timeline. |
| Attendance link | `attendance` `LeaveDayProjection`, `LeaveProjectionService.sync/cancel` | One projection per approved leave date; each sync or cancel recalculates that attendance day immediately, in the same transaction. |
| Payroll link | `payroll/service.py` `_build_snapshots`, `engine.py` | Reads paid / LOP days from the closed attendance period summary; reads ENCASHMENT ledger entries dated inside the pay month; prints month-end balances on the payslip. |
| Jobs | `leave/tasks.py`, `core/celery_app.py` | Monthly accrual 01:00, comp-off expiry 01:30, year end 02:00 (all India time, daily), comp-off credit sweep. |

**How the available balance is calculated**

`balance = SUM(leave_ledger.amount)` for the employee and leave type, with **no date filter**
(`LeaveLedgerRepository.get_balance`, `repository.py:407`). Inputs:

- `+` ACCRUAL — monthly (dated month end, prorated by calendar days employed) or yearly (dated leave-year start, flat).
- `+` COMP_OFF_CREDIT — approved overtime minutes ÷ comp-off day length.
- `±` ADJUSTMENT — HR manual entry (reason mandatory), cancellation refund, comp-off expiry / reversal, closed-year lapse.
- `−` APPLICATION — one debit per approved application, dated on its **start date**, for `total_days − lop_days`.
- `−` ENCASHMENT — HR encashment or year-end "encash the excess".
- `−` CARRY_FORWARD — year-end lapse or amount above the carry-forward cap.

At submission: `balance (− pending requests, if the policy reserves) + negative floor ≥ days asked`.
At final approval the same check is repeated under a lock; a shortfall is refused unless the approver
chooses "excess as LOP".

Not supported at all: hourly leave, half day at the start or end of a multi-day leave, minimum
duration, notice period, partial cancellation, editing an application.

---

## 3. Leave policy and decision map

| Area | Setting | Affects the calculation? |
|---|---|---|
| Entitlement | `accrual_frequency` NONE / MONTHLY / YEARLY, `accrual_rate_per_cycle` | Yes |
| Entitlement | Statutory minimum per category | Yes — blocks publishing a policy below it |
| Accrual | `accrue_during_probation` | Monthly: yes. **Yearly: no (LV-07)** |
| Accrual | Pro-rata | Monthly by calendar days employed. Yearly: none (PD-01) |
| Deduction | `requires_balance`, `allow_negative_balance` + `negative_balance_floor`, `reserve_balance_on_submission` | Yes |
| Deduction | Excess as LOP at approval | Yes — latest days become unpaid |
| Carry forward | `year_end_action` CARRY_FORWARD / LAPSE / ENCASH_EXCESS, `max_carry_forward_days` | Yes, but on the wrong balance (LV-01/02) |
| Expiry | Comp-off expiry date from the overtime policy | Yes, with a defect (LV-06) |
| Encashment | `encashment_allowed`, `max_encashment_days`, `min_balance_after_encashment` | Yes for HR encashment. Year-end encashment does not read `encashment_allowed` (LV-12) |
| Encashment | `encashment_frequency`, `encashment_calculation_basis` | No — labelled "note only" in web and mobile |
| Holidays / weekly offs | Work calendar + published roster + shift "operates on holiday / weekly off" | Yes — off days are not charged; decided at submission and then frozen (PD-04) |
| Sandwich | `sandwich_rule_enabled` | Yes — inside one request, and across two requests of the same type |
| Half days | `half_day_allowed` | Yes — single-day requests only |
| Request rules | `max_backdated_days`, `max_consecutive_days`, `reason_required`, `attachment_required`, `allowed_during_probation` | Yes |
| Request rules | `max_requests_per_month` | Partly — counts requests of every leave type (LV-12) |
| Request rules | `allow_manager_request_on_behalf`, `allow_hr_request_on_behalf` | Not independently (LV-09) |
| Approval | `approval_chain` AUTO / MANAGER / HR / MANAGER_THEN_HR / MANAGER_THEN_HOD_THEN_HR | Yes |
| Combination | Leave combination rules (pairs of types) | Yes — at submission only |
| Leave year | CALENDAR / FINANCIAL / ANNIVERSARY / CUSTOM | Yes |
| Maternity | `pre_delivery_days`, `post_delivery_days` | No — "note only" |
| Attendance | Attendance policy `work_on_leave_behaviour` | **No — both options behave the same (LV-12)** |
| Payroll | `is_paid_default` on the leave type | Yes — paid leave counts as a paid day, unpaid as LOP |

---

## 4. Leave lifecycle

```
Policy (versioned, scoped)
   │  resolved per employee + leave type + date
   ▼
Entitlement ── monthly job (month end, prorated) ─┐
            ── yearly job (leave-year start)      ├─► Ledger (append-only) ─► Balance = SUM
            ── comp-off credit (approved OT)      │
            ── HR adjustment / encashment ────────┘
   ▼
Application  SUBMITTED ──approve (each stage)──► APPROVED ──cancel──► CANCELLED
      │            └──reject──► REJECTED              │
      │            └──withdraw──► CANCELLED           │
      ▼                                               ▼
 day rows frozen at submit          debit ledger + one projection per day
                                                      ▼
                                    Attendance day recalculated at once
                                                      ▼
                                    Period close ─► summary (paid / LOP days) ─► Pay run
```

| Transition | Who | Checks | Balance | Attendance | Reversible |
|---|---|---|---|---|---|
| Submit | Employee; HR on behalf | Employment covers dates, period open, combination rules, policy resolves, span, probation, half-day, backdating, monthly cap, calendar resolves, overlap, balance | None (optional reservation) | None | Withdraw |
| Stage approve | Snapshotted manager / department head / HR with company scope; never self | Version match, employment | None | None | — |
| Final approve | Same | Period open, balance re-checked under lock | Debit dated on start date | Projection + recalculation per day | Cancel |
| Reject | Reviewer | Version match | None | None | No |
| Withdraw (pending) | Submitter or the employee | — | None | None | No |
| Cancel approved | Employee before it starts; HR any time (reason needed once started) | Period open for the whole range | Refund dated today, plus closed-year rule | Projections cancelled + recalculation | No (apply again) |
| Reassign approver | HR, company scope | Current approver ineligible, new one eligible | None | None | Yes |
| HR adjustment / encashment | `LEAVE.BALANCE_ADJUST` within scope | Employment, period open, payroll not finalised, policy limits (encashment) | New ledger row | None | Opposite entry |

---

## 5. Use-case coverage

| Use case | Expected | Actual | Status |
|---|---|---|---|
| Paid leave | Balance debited, day paid | Debit on approval; attendance LEAVE, paid 1.00 | PASS |
| Unpaid leave / LOP type | No balance, day unpaid | No ledger row; LOP 1.00 flows to payroll proration | PASS |
| Excess as LOP | Uncovered days unpaid | Latest days marked LOP, rest debited | PASS |
| Half day (single day) | 0.5 debited, other half judged on punches | As expected; worked half is all-or-nothing (PD-13) | PASS |
| Same half day twice | Second request refused | Both accepted, 1.00 debited | **FAIL (LV-05)** |
| Half day inside a multi-day leave | Supported or clearly refused | Refused by API and both clients | PASS (not supported) |
| Holiday inside leave | Not charged unless sandwich | Not charged; charged under sandwich rule | PASS |
| Holiday declared after approval | Policy decides | Leave day stays charged; warning only | POLICY (PD-04) |
| Weekly off inside leave | Not charged unless sandwich | As expected, including roster and shift overrides | PASS |
| Sandwich, one request | Off days between leave days charged | As expected | PASS |
| Sandwich, two requests, same type | Charged to the later request, released if the other is cancelled | As expected | PASS |
| Sandwich, two different leave types | Policy decides | Not charged | POLICY (PD-05) |
| Cancellation before approval | No side effects | As expected | PASS |
| Cancellation after approval | Balance, attendance restored | As expected, with audit trail | PASS |
| Cancellation when part of the leave is in a closed month | Controlled correction | Refused entirely; no partial cancel | **GAP (PD-07)** |
| Monthly accrual | Once per month, prorated, India date | As expected; idempotent | PASS |
| Monthly accrual catch-up for one skipped employee | Caught up later | Never, after day 5 | **FAIL (LV-08)** |
| Yearly accrual | Credit at leave-year start | Credited; ignores probation switch; nothing for mid-year joiners | **FAIL (LV-07)** / POLICY (PD-01) |
| Year-end lapse / carry-forward | Applied to the old year's closing balance | Applied to the all-time balance | **FAIL (LV-01, LV-02, LV-03)** |
| Comp-off earn / use / cancel | Credit once, spend once | Credit and spend once; expiry defect | **FAIL (LV-06)** |
| Duplicate approval (two HR users) | One debit | Second gets a 409 | PASS |
| Two requests against 1 day of balance | Only one approved from balance | Second refused at approval, or approved as LOP | PASS |
| Accrual job retry / double run | No double credit | Unique index + cycle key | PASS |
| Leave after attendance exists | Day recalculated | Recalculated at once; punches on full-day leave are flagged and block close | PASS |
| Pending leave at period close | Close blocked or request resolved | Close allowed; request stranded | **FAIL (LV-04)** |
| Leave change after period close | Refused | Refused (approve, cancel, adjust, encash) | PASS |
| Leave change after payroll finalised | Refused | Refused; period cannot be reopened | PASS |
| UTC vs India date in jobs | India business date | `business_today(company.timezone)` everywhere | PASS |
| Cross-company access, self-approval | Blocked | Blocked | PASS |
| Exit with positive or negative balance | Settled | Nothing happens | POLICY (PD-08) |

---

## 6. Confirmed bugs

### LV-01 — Year end uses the all-time balance, so new-year leave shrinks the lapse · High · Reproduced

- **Root cause**: `_year_end_for_employee` reads `get_balance` (no date filter, `service.py:2091`),
  and an approved application is debited on its start date (`service.py:3988`). A January leave
  approved in December is already inside the balance the year-end rule looks at.
- **Reproduction**: balance 20, cap 5. Approve 3 days for 5–7 Jan before the year-end run. Run year end.
- **Expected**: 20 → capped to 5 on 1 Jan → 3 days taken → **2**.
- **Actual**: 17 → capped to 5 → **5**. The employee keeps 3 extra days. Under LAPSE the January leave
  is paid for entirely with days that should have lapsed.
- **Also affects**: any ledger entry dated on or after the year start that exists when the job runs
  (future-dated HR adjustments).
- **Fix**: compute the split from the balance dated before the year start
  (`get_balance_before(year_start)` already exists for R-12).

### LV-02 — Old-year leave approved after year end is taken from the new, capped balance · High · Reproduced

- **Root cause**: `_apply_closed_year_rule` corrects a **refund** into a closed year, but nothing
  corrects a **debit** into one. `_apply_approval` just writes the debit.
- **Reproduction**: balance 20, cap 5. Year end runs (lapses 15, balance 5). Then approve a backdated
  leave for 29–31 Dec.
- **Expected**: closing balance would have been 17 → lapse 12 → **5**.
- **Actual**: **2**. The employee loses 3 days. Normal case: December leave approved in the first week
  of January, before December is closed.
- **Fix**: at approval, when the debit date falls in a leave year whose year end has run, write back
  the part of the lapse that would not have happened. The encashed case needs a decision (PD-03).

### LV-03 — Leave across the leave-year boundary is charged wholly to the old year · Medium · Reproduced

- **Root cause**: one debit per application, dated on the start date.
- **Reproduction**: LAPSE policy, balance 20, leave 30 Dec – 2 Jan (4 days). Year end lapses 16; balance 0.
  The two January days were paid from the old year.
- **Fix**: split the debit by leave year (one ledger row per year). Which year should pay is PD-03.
- **Same root cause**: the payslip month-end balance shows a leave spanning two months entirely in the first.

### LV-04 — A month can be closed with leave requests still pending · High · Traced

- **Root cause**: the period-close blocker list (`attendance/service.py:7062–7245`) has
  `PENDING_REGULARIZATION` and `PENDING_OVERTIME_APPROVAL` but nothing for pending leave.
- **Scenario**: employee applies for 24–25 Nov; the manager has not acted; HR closes November.
- **Actual**: the two days are ABSENT → LOP in the pay run. Approval is now refused
  (`LEAVE_APPLICATION_PERIOD_CLOSED`); the request stays pending until withdrawn. After payroll is
  finalised the period cannot be reopened.
- **Expected**: close is blocked (or the requests are listed for a decision) the same way pending
  regularizations are.
- **Fix**: add a `PENDING_LEAVE` blocker for submitted applications with a day inside the period (PD-10).

### LV-05 — The same half day can be booked twice · Medium · Reproduced

- **Root cause**: the overlap check adds fractions per date and compares to the day's capacity
  (`service.py:3185–3196`); it never compares `half`. The projection check also only sums to ≤ 1.00.
- **Reproduction**: submit FIRST_HALF for 8 Sep twice (two separate requests). Both are approved;
  balance goes 20 → 19; attendance treats the day as full-day leave.
- **Expected**: the second request is refused as an overlap. The same applies across two leave types.
- **Note**: a retried identical request is protected by the idempotency key; this is two distinct requests.

### LV-06 — Comp-off expiry is all-or-nothing and can remove newly earned comp-off · Medium · Reproduced

- **Root cause**: `expire_company` (`service.py:2459–2483`) skips a lapsed credit while the balance is
  below the credit's full amount and retries every day. When a new credit later lifts the balance, the
  old credit is expired in full.
- **Reproduction**: earn 0.13, use 0.10 (0.03 left), pass the expiry date — nothing expires. Earn 1.00
  (balance 1.03). Next sweep expires 0.13 → **0.90**.
- **Expected**: only the unused 0.03 of the old credit expires → **1.00**.
- **Fix**: track consumption oldest-first and expire only the unused remainder, once.

### LV-07 — Yearly accrual ignores "accrue during probation" · Medium · Reproduced

- **Root cause**: the YEARLY branch (`service.py:2156–2185`) never reads `accrue_during_probation`;
  only the monthly path does.
- **Reproduction**: yearly policy 12 days, switch off, employee on probation → credited **12**; expected 0.

### LV-08 — An employee skipped by monthly accrual is not caught up after day 5 · Medium · Traced

- **Root cause**: catch-up in `run_due_months` (`service.py:1713–1738`) is keyed on the company's newest
  accrual date. Once any employee has accrued for a month, that month is never run again after the window.
- **Ways to be skipped**: status still PROBATION at run time although the probation end date has passed
  (`service.py:1856` reads today's status, not the date); employee or policy assignment entered late
  with a back date; a per-employee failure that persists beyond day 5 (it is only logged).
- **Actual**: that month's accrual is lost silently; HR must add it by hand.
- **Fix**: key catch-up per employee and leave type, and judge probation by date.

### LV-09 — "On behalf" switches do not work independently · Medium · Reproduced

- **Root cause**: `submit` allows on-behalf when **either** switch is on (`service.py:3116–3123`) and
  never checks who the caller is. The default manager role has no on-behalf permission at all.
- **Reproduction**: HR-on-behalf off, manager-on-behalf on → a company admin's on-behalf request is accepted (201).
- **Actual**: turning off HR-on-behalf does nothing while the manager switch is on; turning on
  manager-on-behalf does not let managers apply.

### LV-10 — Leavers on a department / branch / grade policy get no final-month accrual · Medium · Traced

- **Root cause**: monthly accrual resolves the policy as of month end (`service.py:1833–1849`).
  Termination closes the employee's assignment on the last working day, so after it only employee-level
  and company-level policies resolve.
- **Actual**: an employee leaving on the 20th under a department-scoped policy accrues nothing for that
  month; under a company-wide policy they get the prorated share.
- **Fix**: resolve as of the last employed day inside the month.

### LV-11 — Year-end encashment can be dated in a month already paid · Low · Traced

- **Root cause**: year-end rows are dated on the leave-year start whenever the job runs, with no check
  on period state; payroll picks encashments by date inside the pay month.
- **Scenario**: operator recovery of a missed year start after January payroll is finalised → the
  encashment is deducted from the balance and never paid.
- **Fix**: date a late encashment in the first open period, as the closed-year rule already does.

### LV-12 — Settings that do not do what they say · Low · Traced

- `work_on_leave_behaviour` (attendance policy): both options give the same result since BUS-012, yet
  web and mobile still offer the choice.
- `max_requests_per_month`: set per leave policy but counts the employee's requests of every leave
  type, rejected ones included (`repository.py:731`).
- `encashment_allowed`: not read by year-end ENCASH_EXCESS.

### LV-13 — A deactivated leave type can still be applied for through the API · Low · Traced

- `submit` checks only that the type exists (`service.py:3035`). Accrual, year end and the balance list
  skip inactive types, so the request debits a balance nobody can see.

---

## 7. Policy decisions required

Not bugs. The system does something definite today; the owner must confirm or change it.
**Blocking** = decide before real payroll or a real year end.

| ID | Decision | What happens today | Options | Recommended | Risk if left |
|---|---|---|---|---|---|
| PD-01 **Blocking** | Yearly credit for mid-year joiners | Nothing until the next leave-year start (LD-21 decision 3). A 2 Jan joiner gets zero for the year | Pro-rata on joining; full on joining; none | Pro-rata by remaining months | HR hand-credits every joiner |
| PD-02 | Monthly leave: usable in advance or in arrears | Credited at month end, usable next month | Arrears; credit at month start | Confirm arrears | New joiners cannot take leave in month one |
| PD-03 **Blocking** | Which leave year pays for leave across the boundary, and for late old-year leave when the excess was already encashed | Old year pays all (accident of LV-03) | Split by date; old year; new year | Split by date | Wrong carry-forward |
| PD-04 **Blocking** | Holiday, weekly off, roster or shift changes after a leave is submitted | Day rows are frozen at submission, not even refreshed at approval. A warning is shown on calendar changes | Keep; re-count pending requests at approval; re-count approved leave and refund | Re-count at approval; refund approved leave when a holiday is added | Employee charged leave for a holiday |
| PD-05 | Sandwich rule scope | Same leave type only; not across types; not for a half day; not when leave is on one side only; applies to LOP types too | Extend across types; keep | Decide per client | Rule avoided by using two leave types |
| PD-06 | Half day at the ends of a multi-day leave; hourly leave | Not supported | Add; keep | Add half-day ends later | Employees file two requests |
| PD-07 **Blocking** | Early return and leave that touches a closed month | Whole request must be cancelled; refused if any day is in a closed period | Add "shorten / cancel remaining days" | Add it, open days only | Balance and attendance cannot be corrected |
| PD-08 **Blocking** | Balance at exit | Nothing: no encashment, no recovery of a negative balance, no lapse | Encash on final pay; recover negative; manual | Build with final settlement | Money owed either way is missed |
| PD-09 | Comp-off details | Fractions such as 0.13 day cannot be spent (leave is 0.5 or 1). Comp-off stays if the worked day is later regularized away (overtime record is frozen) | Round to half days; revoke on change | Round down to 0.5 steps; revoke | Dead balances; unearned comp-off |
| PD-10 | Pending leave at month close | See LV-04 | Block close; auto-reject; allow late approval through arrears | Block close | Wrong LOP |
| PD-11 | Policy change or transfer | Balance stays with the leave type. If the new scope has no policy for that type, the balance is stuck: cannot be used, never lapses. Accrual uses the month-end policy for the whole month | Transfer rules; lapse; keep | Document and add a report | Orphan balances |
| PD-12 | Notice period, maximum advance booking, minimum duration, eligibility by gender or tenure | None exist | Add as policy fields | Add notice + eligibility | Maternity leave open to anyone |
| PD-13 | Worked half on a half-day leave falls short | The whole other half becomes LOP | All-or-nothing; proportional | Confirm | Harsh LOP for a 30-minute early exit |
| PD-14 | HR adjustment below zero | Allowed without limit, regardless of the policy's negative floor | Allow; cap at the floor | Warn in the UI | Accidental negative balance |
| PD-15 | Backdated leave | Unlimited unless `max_backdated_days` is set (bounded only by period close) | Default limit | Default 30 days | Late retro leave feeds LV-02 |

---

## 8. Data integrity risks

| Risk | State |
|---|---|
| Duplicate accrual, job retry, job run twice | **Safe** — unique index per cycle, `ON CONFLICT DO NOTHING`, year-end marker table, per-employee savepoints |
| Two approvals of one request | **Safe** — version check; second gets 409 |
| Two requests racing for one balance | **Safe** — balance lock, re-check at final approval |
| Approval racing a cancel, termination or period close | **Safe** — per-employee date lock, shared period-close lock |
| Double submit, network retry | **Safe** — idempotency key required; both clients reuse the key on retry |
| Mobile offline replay | **Not applicable** — the app has no offline queue |
| Refund twice | **Safe** — refund is "debited minus already refunded" |
| Same half day twice | **Open** — LV-05 |
| Year-end figures | **Open** — LV-01, LV-02, LV-03 |
| Comp-off expiry | **Open** — LV-06 |
| Silent loss of one employee's accrual | **Open** — LV-08, LV-10 (logged only) |
| Closed period changed by leave | **Safe** — approve, cancel, adjust, encash all refused; reopen refused after payroll is finalised |
| Closed period closed too early | **Open** — LV-04 |
| Ledger dates vs. creation dates | **Watch** — a debit is dated on the leave start, a refund on today. Month-end and year-end balances "as of" a date can differ from what was shown at the time |
| Adjustment audit | Reason, actor, timestamp and audit row are recorded. Balance before / after is not stored (it can be derived) |
| Frozen day rows | **Watch** — PD-04 |

---

## 9. Downstream impact

| Issue | Shift | Attendance | Overtime | Holidays | Payroll | Employee | HR |
|---|---|---|---|---|---|---|---|
| LV-01/02/03 year end | — | — | — | — | Wrong ENCASH_EXCESS amount; wrong balance on payslip | Days gained or lost | Manual corrections each January |
| LV-04 pending at close | — | Day closed as ABSENT | — | — | LOP deducted for applied leave | Pay cut, request stuck | Needs arrears or reopen |
| LV-05 same half twice | — | Day shown as full leave | OT zeroed on that day | — | Day paid as leave | 0.5 day lost | Cancel and refund by hand |
| LV-06 comp-off expiry | — | — | Earned comp-off removed | — | — | Comp-off lost | Disputes |
| LV-07/08/10 accrual | — | — | — | — | Later LOP when balance runs short | Fewer days than entitled | Hand adjustments |
| PD-04 frozen days | Shift or roster change not reflected | LEAVE on a holiday | — | Holiday charged as leave | Neutral for paid leave; LOP for unpaid leave | Day lost | Cancel and re-apply |
| PD-08 exit | — | — | — | — | Encashment or recovery missing from final pay | Under- or over-paid | Manual settlement |

---

## 10. Remediation plan

**Phase 1 — balance integrity (before any real year end)**
1. LV-01: year-end split from the pre-year-start balance.
2. LV-02 + LV-03: debit per leave year; closed-year rule for late debits (needs PD-03).
3. LV-05: refuse a second request for the same half.
4. LV-06: comp-off expiry by unused remainder.

**Phase 2 — attendance and payroll**
5. LV-04: pending-leave blocker at period close (PD-10).
6. PD-07: shorten / cancel remaining days.
7. LV-11: late year-end encashment dated in an open period.
8. PD-08: exit settlement of leave.

**Phase 3 — effective dating and history**
9. LV-08: per-employee accrual catch-up; probation judged by date.
10. LV-07: probation switch for yearly accrual; PD-01 joiner pro-rata.
11. LV-10: resolve policy on the last employed day.
12. PD-04: re-count days at approval; refund on calendar change.

**Phase 4 — hardening**
13. LV-09 on-behalf switches; LV-12 dead or misleading settings; LV-13 inactive type.
14. PD-05, PD-09, PD-11, PD-12, PD-14, PD-15.

**Phase 5 — web and mobile**
15. Show the days that will be charged (sandwich days included) before submitting — needs a preview endpoint.
16. Show "available" as balance minus pending requests.
17. Pending-leave list on the period-close screen.

Web and mobile are otherwise consistent with the backend: same fields, half day limited to a single
day, cancel rules match, no leave arithmetic in the clients.

---

## Appendix A — reproduced scenarios

All on a fresh tenant: one employee joined 2020-01-01, Sunday weekly off, one leave type, AUTO approval,
opening balance 20 dated 2025-06-01. Year end run with `run_year_end_for_company(as_of=2026-01-01)`.

| # | Steps | Result |
|---|---|---|
| P1 (LV-05) | Submit FIRST_HALF 2026-09-08 twice | 201, 201; ledger −0.50, −0.50; balance 19.00 |
| P2 (LV-01) | Cap 5. Approve 2026-01-05..07, then year end | CARRY_FORWARD −12; balance 5.00 (expected 2.00) |
| P3 (LV-02) | Cap 5. Year end (−15), then approve 2025-12-29..31 | Balance 2.00 (expected 5.00) |
| P4 (LV-07) | YEARLY 12, accrue_during_probation off, status PROBATION, year end | Balance 12.00 (expected 0) |
| P5 (LV-09) | HR-on-behalf off, manager-on-behalf on; admin applies on behalf | 201 |
| P6 (LV-03) | LAPSE. Approve 2025-12-30..2026-01-02 (4 days), then year end | One debit −4 dated 2025-12-30; CARRY_FORWARD −16; balance 0 |
| P7 (LV-06) | Comp-off 0.13 earned 2026-08-10; adjust −0.10; expire 2026-12-01 → nothing; adjust +1.00; expire 2026-12-02 | Balance 0.90 (expected 1.00) |
