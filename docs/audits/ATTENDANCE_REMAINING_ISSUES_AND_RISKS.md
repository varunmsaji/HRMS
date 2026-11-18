# Attendance Remaining Issues and Risks — 16 November 2026

Companion to `MASTER_ATTENDANCE_SYSTEM_AUDIT_2026-11-16.md`, which holds the full write-up of every
finding (root cause, reproduction, correction, regression test). This document is the ordered work
list. It describes the **uncommitted working tree** (engine 16).

**Evidence words.** REPRODUCED: shown by a probe or test that ran in this audit. CODE-CONFIRMED:
the code path was read end to end and is unambiguous, but not executed. PLAUSIBLE RISK: reported by
a code reading and not confirmed by this audit; it may be wrong. DECISION: the product owner must
choose before anyone can call the behaviour right or wrong.

**Impact letters.** A = attendance status, P = paid-day or loss-of-pay fraction, L = leave balance,
O = overtime or comp-off, C = period close blocked or not blocked.

---

## 1. Before attendance can feed a payroll audit

These can put a wrong paid-day fraction, leave balance or overtime figure into a period that then
closes without any blocker, or stop a period from closing with no supported remedy.

| Order | ID | Issue | Evidence | Impact | Needs |
|---|---|---|---|---|---|
| 1 | MA-01 | Hour bands with a gap or not starting at zero: uncovered minutes are `PRESENT`, full pay. 30 minutes worked = full day | REPRODUCED (API IP1; engine H1, H2) | A, P | Fix (refuse at publish; no band = configuration error). Decision H-01. List published versions with gaps |
| 2 | MA-02 | Under `TREAT_PRESENT`, a no-show is paid in full at lock | REPRODUCED (API IP2) | A, P | Decision H-02, then fix |
| 3 | MA-03 | Comp-off credit never follows overtime corrections; a re-detected record earns a second credit (180 min credited 0.38, removed, 30 min re-detected: balance 0.44) | REPRODUCED (API IP10) | L, O | Decision H-03, then fix. Integrity query for existing credits |
| 4 | MA-04 | A shift-scoped work calendar or attendance policy does not resolve on a roster week-off: `CONFIG_ERROR`, blocks close | REPRODUCED (API IP3; engine O8) | A, C | Decision H-04, then fix |
| 5 | MA-05 | Part-time shifts judged by full-day bands: full attendance = `HALF_DAY`, 0.50 loss of pay | REPRODUCED (engine O20) | A, P | Decision P-05 |
| 6 | MA-27 | A leave shortfall stays open after its leave is cancelled; it keeps blocking close and the reconciliation operation shows nothing to apply | REPRODUCED (API C1-SHORTFALL-CANCEL) | C, L | Fix (close shortfalls on cancel and withdraw; filter by application status) |
| 7 | MA-34 | Overtime at the manager stage can only be decided by the snapshotted manager; no reassignment or HR override. A departed manager's records block close | CODE-CONFIRMED | C, O | Decision O-19, then fix |
| 8 | MA-06 | A punch accepted after close and owned by a locked day is counted nowhere and reported nowhere | REPRODUCED (API IP5, IP9b) | A, P | Fix (report it; blocker or HR queue) |
| 9 | MA-07 | A schedule change recalculates only its own date; the neighbour keeps punches it no longer owns | REPRODUCED (API IP7, IP7b, IP7c) | A, P, O | Fix (widen by the ownership neighbourhood) |
| 10 | MA-10 | Pay-basis and legal-entity edits queue no recalculation; the legal-entity edit has no closed-period guard | CODE-CONFIRMED | A, P, C | Fix |
| 11 | — | Commit engine 16 with its three migrations; migrate the dev database (four behind); run Flutter in CI | Verified state | all | Operational |

## 2. Wrong by rule, needing a decision first

| ID | Issue | Evidence | Impact | Decision |
|---|---|---|---|---|
| MA-08 | Half-day leave on a day that became a day off shows 0.50 loss of pay until HR reconciles | REPRODUCED (API IP8; engine L1–L3) | P | H-08 |
| MA-09 | Late-mark ceiling measured from shift start, grace included: a "mark" of 50–59 minutes costs half a day; template text says marks cost nothing | REPRODUCED (engine G1) | A, P | D-01a, R-2 |
| MA-13 | Grace lowers every hour-band threshold, even when hours were missed (239 minutes is `HALF_DAY` under "absent below 240") | REPRODUCED (engine H3) | A, P | H-05 |
| MA-20 | FIXED shift: work wholly before the shift counts zero minutes; day is `ABSENT` | REPRODUCED (API IP7c) | A, P | P-04 |
| MA-28 | Deactivating a holiday calendar, work calendar or weekly-off pattern changes nothing; its holidays still exclude leave days | REPRODUCED (API C1-INACTIVE-HOLIDAY-CAL) | A, L | H-30 |
| H-29 | Lateness in the worked half of a half-day leave, with no late bands, costs a quarter day | REPRODUCED (engine L7) | P | H-29 |
| O-15 | A policy republish re-prices approved overtime but keeps the old comp-off choice | CODE-CONFIRMED | O | O-15 |
| AR-15 | `work_on_leave_behaviour` is accepted, stored and ignored | CODE-CONFIRMED | — | L-13 |

## 3. Medium

| ID | Issue | Evidence | Impact | Correction |
|---|---|---|---|---|
| MA-11 | Accrual and other credits do not resolve an open leave shortfall; only an HR credit does | CODE-CONFIRMED | C, L | Run the shortfall pass after any credit, or document the HR step |
| MA-12 | Recalculation queue: no deduplication; requests abandoned after 5 attempts are only logged | CODE-CONFIRMED; duplication observed (IP4) | — | Coalesce; surface abandoned requests |
| MA-29 | Regularization may add punches a day either side, but approval recalculates only its own date | CODE-CONFIRMED | A, P | Recalculate both dates |
| MA-33 | A `PENDING` overtime record is rewritten on every recalculation (version raised, action and audit row added), so approvers hit stale-version errors after any sweep | CODE-CONFIRMED | O (operational) | Rewrite only on change |
| MA-26 | Cascades and close-time checks scale poorly (quadratic cascade, company-wide calendar ranges, per-date claim resolution at validation) | CODE-CONFIRMED; not measured | — | See master section 12 |
| MA-36 | No screen for leave reconciliation or orphan-punch handling, yet both calendar setup screens tell HR to "run leave reconciliation" (web `work-calendars/setup/page.tsx:405`, mobile `work_calendar_setup_screen.dart:349`) | CODE-CONFIRMED | C | Build the screen or change the text |
| MA-14 | Weekly-off overtime net of breaks; roster week-off overtime gross | REPRODUCED (engine O1, O2) | O | Decision O-06 |

## 4. Low

| ID | Issue | Evidence |
|---|---|---|
| MA-15 | Holiday on a weekly off pays the weekly-off overtime class | REPRODUCED (engine O4) |
| MA-16 | No-shift day: forgotten checkout pairs with the next day's (33-hour session) | REPRODUCED (engine T8) |
| MA-17 | A future date can be calculated | REPRODUCED (API IP6) |
| MA-18 | `punch`, `overtime_action`, `punch_dismissal`, `attendance_period_action` are not append-only for the runtime role. The init script grants UPDATE/DELETE on all tables; migration `20261009090000` revokes them only for `leave_ledger`, `leave_application_action`, `audit_log` | CODE-CONFIRMED (init script and migration read) |
| MA-19 | Status label and paid fraction disagree on several day kinds | REPRODUCED |
| MA-21 | Termination or joining dated inside a closed period accepted | CODE-CONFIRMED |
| MA-22 | Punch, regularization and overtime decisions do not take the period-close lock | PLAUSIBLE RISK |
| MA-23 | Excess-break exceptions awaiting approval do not block close | CODE-CONFIRMED |
| MA-24 | Server-date fallbacks that can be a day early between 00:00 and 05:30 IST on a UTC server: `leave/decision_center.py:114`, `organisation/dashboard_insights.py:155`, `employee/schemas.py:100, 367` (date-of-birth and joining-date validation). Harmless: `organisation/service.py:1431, 4476` (only when the company row is missing) and `organisation/repository.py:734` (`CURRENT_DATE` in an informational count of a shift's active employees) | CODE-CONFIRMED |
| MA-30 | Break-override revocation recalculates from today only; past open days stay stale | CODE-CONFIRMED |
| MA-31 | A second ON_DUTY or early-departure approval for one date is accepted at submit and fails with HTTP 500 on approve | REPRODUCED (API C1-DOUBLE-ON-DUTY) |
| MA-32 | Overtime withdrawn at lock does not hand its cap budget to later days | CODE-CONFIRMED |
| MA-35 | Web blocker labels miss five codes (`PENDING_LEAVE`, `OVERTIME_INTEGRITY`, `LEAVE_BALANCE_SHORTFALL`, `LEAVE_CALENDAR_MISMATCH`, `ORPHAN_PUNCHES`) in `attendance-period/types.ts`; mobile reported the same | CODE-CONFIRMED (web); mobile reported, not read |
| C-14 | No revoke for an approved regularization | CODE-CONFIRMED |
| C-17 | Break-correction recalculation failure is logged only; nothing queued | CODE-CONFIRMED |

## 5. Plausible risks not confirmed by this audit

Reported by code readings during the audit. Each needs a probe before it is treated as a defect.

| Risk | Where to look |
|---|---|
| A deactivated but still employed person blocks close (`EMPLOYEES_WITHOUT_ATTENDANCE`) because the sweep skips them | daily sweep, `_run_validation` |
| A terminated employee who stays `is_active` gets an `EXITED` row written every day | daily sweep |
| The daily sweep uses the company timezone, not the branch timezone | `tasks.py` sweep |
| The engine ignores `Shift.is_active`; deactivating a shift queues nothing; swaps do not check it | `resolve_shift_schedule`, `schedule_service` |
| An assignment expiring under a roster row drops shift-scoped policy resolution | `_scope_candidates` |
| `ShiftRosterUpdate` can store a week-off together with a `shift_id` | roster schemas |
| A legal-entity change through a branch move changes policy scope but not period ownership | `_PeriodScope` |
| A comp-off credit can coexist with paid overtime after `comp_off_instead_of_pay` is switched off (follows from O-15) | `_resolve_ot_decision`, day summary |
| Comp-off credits whose overtime record is gone never expire | comp-off expiry sweep |
| A failure in the cap cascade rolls back the original calculation | `_recompute_later_days_of_month` |
| `delete_for_day` removes a `PENDING` record and its action history without an audit entry | `OvertimeRecordRepository.delete_for_day` |
| Mobile offers a "present, cancel leave" hint that does nothing; mobile insights sum detected rather than approved overtime; clients show all punches when the snapshot is missing | mobile attendance features |
| Leave findings LV-01 to LV-03 and LV-05 to LV-13 | carried from `LEAVE_MANAGEMENT_AUDIT_2026-11-16.md`; code unchanged, not re-reproduced |

## 6. What was not verified at all

- **Flutter:** `flutter analyze` and `flutter test` were not run; Flutter is not installed. Dart code
  was read only.
- **Production-like volumes:** no load or timing test. Performance statements are from code.
- **Concurrency beyond the suite:** two-session races were not run except those in existing tests.
- **Integrity report on real data:** `scripts/sql/attendance_integrity_report.sql` was not run
  against any database holding real or production-like data; none was available to this audit.
- **Year boundary:** cap cascades and leave across 31 December were not tested.
- **Scenarios 12, 15 and 35** of the cross-module matrix were not executed.

## 7. Residual risk if released as is

- Configurations that the API accepts today (MA-01, MA-02, MA-04, MA-05) produce wrong pay with no
  warning. A tenant that uses any of them gets wrong paid-day inputs.
- Comp-off balances can exceed the overtime actually approved (MA-03) and nothing reports it.
- Period close can be blocked with no supported remedy in the product UI (MA-27, MA-34, MA-36).
- Stale results between a change and period close (MA-06, MA-07, MA-10, MA-29, MA-30). Close
  repairs most of them; MA-06 it does not.
- About 30 business rules apply without an owner decision on record
  (`ATTENDANCE_POLICY_DECISION_REGISTER.md`).
