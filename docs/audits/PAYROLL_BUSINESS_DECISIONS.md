# Payroll Business Decisions — Signed Off

| Field | Value |
|---|---|
| Decision date | 2026-09-23 |
| Approved by | varun (product owner) — all items approved as "go" |
| Basis | Industry-default answers (Keka / greytHR / Zoho / Darwinbox practice, Indian labour-law norms) proposed during the pre-payroll readiness audit |
| Resolves | `BUS-001`…`BUS-015`, `PAY-006` pre-lock semantics, `PD-1`…`PD-3` in [`PAYROLL_BLOCKER_REGISTER.md`](./PAYROLL_BLOCKER_REGISTER.md), plus two new decisions (`BUS-016`, `BUS-017`) |
| Status | **APPROVED** — implementation pending unless marked otherwise |

These are the authoritative answers to the open business questions that block Payroll. Any code
change touching paid days, LOP, leave balance, period close, or salary proration must follow this
document. Changing a decision here requires a new dated sign-off entry in the change log at the end.

---

## Summary

| # | ID | Question | Decision | Code impact |
|---|---|---|---|---|
| 1 | BUS-001 | Paid holidays / weekly offs by employee type | Monthly-salaried: both paid. Daily-wage: national & festival holidays paid, weekly offs unpaid | **New field** — employee pay basis (`MONTHLY` / `DAILY_WAGE`); calc reads it |
| 2 | BUS-002 | Days before joining / after exit | Neither paid nor LOP — "not employed"; salary prorated | Fix PAY-004 & PAY-005: `NOT_JOINED`/`EXITED` → paid `0.00`, LOP `0.00`; new `not_employed_days` bucket |
| 3 | BUS-003 | Half-day weekly offs | Supported: half off, half working; skipped working half = 0.5 LOP | Fix PAY-012: carry `off_fraction` through calendar resolution into the engine |
| 4 | BUS-011 | OT on a full-day leave day | Not payable. Employee must cancel the leave first, then OT applies normally | Suppress OT on full-day approved leave days |
| 5 | BUS-012 | Work on an approved-leave day | Flag the conflict; **period cannot close until HR resolves** — cancel leave (paid present, balance restored) or keep leave (punches ignored). Never paid twice | New blocking validation reason on period finalize + HR resolution action |
| 6 | BUS-009 | Restricted / optional holidays | Working day by default; employee avails via a leave application, capped per year (default 2) | Confirms current default; restricted-holiday leave type with annual cap |
| 7 | BUS-010 | Holiday on a weekly off | No automatic substitute; HR adds a `SUBSTITUTE_HOLIDAY` calendar exception where company/state law requires | No change — confirms current behaviour |
| 8 | BUS-005 | Negative leave balance | Not allowed by default; enable per leave type with a floor (e.g. SL to −3); recovered in F&F at exit | Fix PAY-011: make `allow_negative_balance` live + add a per-type floor |
| 9 | BUS-006 | Approval would overdraw balance | Approver sees the shortfall; must reject, or approve with excess days converted to LOP. Never silently negative | Fix PAY-010: re-check under row lock at approval; "excess → LOP" split |
| 10 | BUS-004 | Who can cancel approved leave | Employee: before the leave starts. After start: HR admin only, reason mandatory, audited. Manager: not after approval | Extend `cancel` authorization in `leave/service.py` |
| 11 | BUS-013 | Leave expiry at year end | Per leave type: CL lapses; SL carries forward to a cap; EL carries forward to a cap (30–45 days), excess encashed or lapsed per policy | Year-end rule per leave type (lapse / carry-forward cap / encash-excess) |
| 12 | BUS-014 | Advance leave | Not in v1 | None |
| 13 | BUS-015 | Comp-off day length | ≥ full shift hours worked = 1 day; ≥ half shift = 0.5 day; expiry 60 days | Default `comp_off_day_length_minutes` from the shift's scheduled minutes when unset; default expiry 60 days. **Step rule deferred** — needs the implementation decisions in [`COMPOFF_POLICY_SAFETY_REVIEW.md`](./COMPOFF_POLICY_SAFETY_REVIEW.md) §13 |
| 14 | BUS-007 | Payroll grain | **Per legal entity**, one monthly cycle each (PF/ESI/TDS are filed per entity) | Activate `attendance_period.legal_entity_id`; per-entity period non-overlap |
| 15 | BUS-008 | Corrections after payroll is paid | Finalized payroll month never reopens; late corrections flow as **arrears in next month's payroll**. Before payroll finalization, HR admin may reopen with a reason | Payroll-side arrears mechanism; block attendance reopen once payroll for the period is finalized |
| 16 | PAY-006 | Incomplete day (missing punch) at close | Reminders before cutoff; unresolved at close → **absent (LOP)**; genuine errors repaid as next-month arrears | Default `incomplete_at_lock_behaviour = TREAT_ABSENT` (current default); fix PAY-007 (audit + explicit re-aggregation); add pre-cutoff reminder |
| 17 | BUS-016 *(new)* | Salary proration basis | **Actual calendar days in the month**: monthly salary × paid days ÷ days in month (28/29/30/31) | Payroll engine rule; requires `paid_days`/`payable_days` in summary (PAY-002) |
| 18 | BUS-017 *(new)* | Attendance cycle | **Full calendar month** (1st – last day); payroll processed in the first week of the following month | Period creation defaults to calendar month |

---

## Product decisions

| ID | Question | Decision | Code impact |
|---|---|---|---|
| PD-1 | Inert policy settings (ATT-001…004, ATT-005, PAY-011) | **Build** night-OT window (ATT-005) and negative-balance switch (PAY-011) — they affect money and decisions 8/9 depend on them. **Hide from UI** until built: punch rounding (ATT-001), auto-close (ATT-002), half-day split (ATT-003), excess-break behaviour (ATT-004), and the other zero-reference fields (ATT-006) | Implement ATT-005 & PAY-011; remove the other fields from the policy forms (keep DB columns); update `ATTENDANCE_V1_CONFIGURATION_CATALOG.md` to match |
| PD-2 | May Payroll read an unclosed period? | **No — enforced in code.** Payroll refuses any period whose status is not `CLOSED` | Guard in the Payroll run service; test for it |
| PD-3 | Separate leave period close? | **No.** Closing the attendance period locks leave for those dates too | Extend existing lock guards so leave apply/approve/cancel for a closed date is refused |

---

## Derived rules for the attendance period summary

Following from decisions 2, 3, 5, 16 and 17, the frozen `attendance_period_summary` must satisfy
(fixes PAY-002 / PAY-003):

1. Every calendar day in the period falls into **exactly one** status bucket:
   `present`, `half_day`, `absent`, `leave`, `on_duty`, `holiday`, `weekly_off`, `not_employed`
   (`incomplete` is resolved to `absent` at close per decision 16, so it never survives finalize).
2. `holiday_days` / `weekly_off_days` count only non-worked off-days; working on a holiday or
   weekly off counts as `present` and is flagged via `worked_on_holiday` / `worked_on_weekly_off`.
3. Half-day leave counts 0.5 into `leave` and 0.5 into its worked/absent counterpart.
4. New columns: `paid_days` (Σ `paid_day_fraction`), `payable_days` (employment days in period),
   `not_employed_days`, `on_duty_days`.
5. Reconciliation invariant, asserted at finalize:
   `sum(all buckets) = calendar days in period` and
   `paid_days + lop_days + unpaid_off_days = payable_days` (`unpaid_off_days` — off days that are
   neither paid nor LOP, e.g. a daily-wage employee's weekly off; added with decision 1).

---

## Implementation order (agreed)

1. **Payroll input correctness:** PAY-002, PAY-003, PAY-004, PAY-005, PAY-006/007, PAY-012,
   ATT-005, date-range attendance backfill endpoint (completes PAY-001), employee pay-basis field
   (decision 1), work-on-leave close blocker (decision 5).
2. **Leave balance safety:** PAY-010, PAY-011 (+ floor), DAT-001, cancel authorization (decision
   10), year-end rules (decision 11), comp-off defaults (decision 13), leave lock on closed periods
   (PD-3).
3. **Period grain:** legal-entity periods (decision 14), calendar-month default (decision 18).
4. **UI cleanup:** hide inert settings (PD-1), update configuration catalogue.
5. **Payroll module:** built against these rules — reads only `CLOSED` periods (PD-2), calendar-day
   proration (decision 17), arrears for post-payroll corrections (decision 15).

---

## Implementation progress

| Date | Batch | Done | Migration |
|---|---|---|---|
| 2026-09-23 | Step 1a | PAY-004/PAY-005 (NOT_JOINED/EXITED → 0.00 paid / 0.00 LOP); PAY-002/PAY-003 (mutually exclusive summary buckets, new `paid_days`/`payable_days`/`on_duty_days`/`incomplete_days`/`not_employed_days`, `attendance_day.leave_fraction`, reconciliation asserted at finalize, `PAID_LOP_MISMATCH` blocking reason); PAY-007 (lock-time INCOMPLETE resolution applied explicitly to in-memory rows + one `ATTENDANCE_INCOMPLETE_RESOLVED_AT_LOCK` audit row per period); `EMPLOYEES_WITHOUT_ATTENDANCE` now compares exact dates (a NOT_JOINED row could previously mask a missing employed day) | `20261004090000` |
| 2026-09-23 | Step 1b | PAY-012 (half-day weekly off: evaluated as a working day, off half paid — `attendance_day.weekly_off_fraction`); ATT-005 (`night_ot_mode` honoured: `SHIFT_FLAG` = shift's `is_night_shift`, `WINDOW` = OT span overlaps the night window, `BOTH`; night OT without a NIGHT rate row falls back to the NORMAL rate code); decision 4 (no OT on a full-day leave day); decision 5 (full-day leave always wins over punches, day flagged, `WORK_ON_LEAVE_UNRESOLVED` blocks finalize until HR cancels the leave or calls `POST /attendance/days/{id}/work-on-leave/keep-leave`); PAY-001 completed (`POST /attendance/days/calculate-range`, ≤ 62 days, not past today, Celery job `attendance.calculate_range`, employed days only, one transaction per employee); decision 1 (`employment.pay_basis` MONTHLY/DAILY_WAGE; daily-wage paid only for PUBLIC/SUBSTITUTE holidays; `holiday.is_paid = false` now honoured for everyone; `attendance_day.unpaid_off_fraction` + summary `unpaid_off_days`, invariant `paid + lop + unpaid_off = payable`) | `20261004091000`, `20261004092000`, `20261004093000` |
| 2026-09-23 | Step 1c | Summary OT buckets fixed — `attendance_day.ot_day_class` (engine day class, backfilled from `overtime_record.day_class`) replaces matching the policy's rate code, so codes like `OT_NIGHT_2X` no longer all land in `ot_minutes_normal`; PAY-006 pre-cutoff reminders (daily 10:00 IST Celery job `attendance.run_incomplete_reminders`: from `attendance_incomplete_reminder_lead_days` (3) before an open period's end until it closes, each employee with unlocked INCOMPLETE days before today gets one email, users with `ATTENDANCE.LOCK` get a digest; once per period per business day via an `ATTENDANCE_INCOMPLETE_REMINDERS_SENT` audit row); PAY-008 (`calculation.ENGINE_VERSION = 2` stored in `attendance_day.engine_version` and the snapshot; sibling-day and cross-module inputs recorded in `computation_snapshot["derived_inputs"]`) | `20261004094000`, `20261004095000` |
| 2026-09-23 | Step 2 | PAY-011 / decision 8 (`allow_negative_balance` enforced at submit and approval, bounded by the new `leave_policy_version.negative_balance_floor`, required to publish with the switch on; NULL reads as 0); PAY-010 / decision 9 (balance re-checked at final approval under a per-employee, per-leave-type advisory lock; overdraw → 409 `LEAVE_APPLICATION_BALANCE_SHORTFALL` with the shortfall, or approve with `excess_as_lop: true` — the latest uncovered whole days become `leave_application_day.is_lop`, projected unpaid, `leave_application.lop_days` not debited, cancel credits back only what was debited; web review dialog shows the shortfall); DAT-001 (partial unique indexes on `ACCRUAL`/`CARRY_FORWARD` per cycle and `COMP_OFF_CREDIT` per overtime record, `INSERT … ON CONFLICT DO NOTHING`); decision 10 (new `LEAVE.APPLICATION_CANCEL_APPROVED`, COMPANY_ADMIN + HR_ADMIN at company scope: employee cancels own approved leave only before it starts, HR any time with a mandatory reason once started — `leave_application.cancellation_reason`, 422 `LEAVE_APPLICATION_CANCEL_REASON_REQUIRED`; managers and other submitters can no longer cancel approved leave); PD-3 (apply, approve and cancel-of-approved refused with 409 `LEAVE_APPLICATION_PERIOD_CLOSED` when any date is inside a CLOSED attendance period; withdrawing or rejecting a pending application stays allowed); decision 11 (`leave_policy_version.year_end_action` = `CARRY_FORWARD` (default, unchanged behaviour) / `LAPSE` (whole positive balance lapses) / `ENCASH_EXCESS` (excess over `max_carry_forward_days` written as a system `ENCASHMENT` for payroll, capped at `max_encashment_days` with the rest lapsing; cap required to publish); negative balances are never touched at year end); decision 13 defaults (comp-off day length falls back to the day's scheduled shift minutes, expiry to 60 days) | `20261004100000`, `20261004101000`, `20261004102000`, `20261004103000` |
| 2026-09-23 | Step 2 — comp-off safety review | [`COMPOFF_POLICY_SAFETY_REVIEW.md`](./COMPOFF_POLICY_SAFETY_REVIEW.md). Comp-off expiry made concurrency-safe (per-credit check-then-offset under the employee's comp-off balance advisory lock, credits ordered by employee). Decision 13's step rule deliberately **not** built (product call 2026-09-23: defer): on today's input it would only ever lower future credits and could never award a day for a full shift worked on a weekly off. No change to credit amounts, balances or historical ledger rows | none |

Step 1 is complete. Step 2 is complete except decision 13's step rule (see the follow-ups below).

Follow-ups found during step 1 (not yet done):

- `work_on_leave_behaviour = PRESENT_CANCEL_LEAVE_HINT` no longer changes the outcome (decision 5)
  — hide it with the other inert settings in step 4.
- `pay_basis` is set on employment create/PATCH and shown in the employment panel, but not yet
  collected by the onboarding wizard or the CSV import (both default to MONTHLY), and the web UI
  has no employment-edit dialog to correct it (API only).
- PAY-006 reminders reach only employees with an active login (`employee.user_id` → `user.email`);
  the others are counted in the HR digest. There is no in-app notification yet — the emails go
  through the onboarding `EmailSender` (logged, not sent, until `email_provider = "ses"`).

Follow-ups found during step 2 (not yet done):

- ~~Comp-off expiry `ADJUSTMENT`s are not concurrency-safe~~ — fixed in the comp-off safety
  review: the "already offset?" read and the offset now run under the employee's comp-off
  balance advisory lock (a reproduced double expiry is covered by
  `test_concurrent_expiry_sweeps_expire_a_credit_once`). Lock-based rather than a unique index:
  an index on `ADJUSTMENT.reference_id` would also constrain the leave-cancel `ADJUSTMENT`s
  (`reference_id` = application id) and need a migration, while the lock is code-only and also
  serialises the expiry against a concurrent approval spending the same balance.
- The approval shortfall split (decision 9) works in whole days: a day the remaining balance
  only partly covers (e.g. 0.5 left against a full day) becomes LOP in full, and the partial
  balance stays unused.
- Decision 13's step rule (≥ full shift = 1 day, ≥ half shift = 0.5, less = nothing) is **not**
  implemented — comp-off is still credited proportionally (`comp_off_minutes ÷ day length`,
  2 decimals). Only the two defaults above were built. Deferred on 2026-09-23 after the safety
  review found that `comp_off_minutes` is overtime *beyond the shift* even on weekly offs and
  holidays, so the rule can't mean "hours worked" without first deciding how off-day work is
  measured. Open decisions (basis, effective date, historical treatment, rounding of existing
  fractional balances) are listed in `COMPOFF_POLICY_SAFETY_REVIEW.md` §13.
- System year-end `ENCASHMENT` entries (decision 11) are balance debits only — the payroll
  module must pick up entries with a `reference_id` and pay them.
- `attendance_period` is company-grain today, so PD-3's lock is company-wide; step 3
  (decision 14, per legal entity) must narrow `AttendanceService.closed_period_overlapping` to
  the employee's legal entity.

---

## Change log

| Date | Change | Approved by |
|---|---|---|
| 2026-09-23 | Initial sign-off of all 18 business decisions and 3 product decisions | varun |
