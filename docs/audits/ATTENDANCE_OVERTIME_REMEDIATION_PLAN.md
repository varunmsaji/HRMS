# Attendance, calendar, leave and overtime remediation — plan and status (16 Nov 2026)

Baseline: branch `test`, `dd71571`, engine 14. Audit: `ATTENDANCE_CALENDAR_OVERTIME_AUDIT_2026-11-16.md`.
Nothing was committed. Results and test evidence: `ATTENDANCE_OVERTIME_REMEDIATION_RESULTS.md`.

## Finding → fix

| ID | Root cause | Fix | Files |
|---|---|---|---|
| AC-01 | `_resolve_ot_decision` froze every non-`PENDING` record, `AUTO_APPROVED` included; the day row took its minutes from the frozen record but its class and policy version from the fresh calculation | `AUTO_APPROVED` is re-derived (identical figures → untouched, so repeats are idempotent; no overtime left → record withdrawn with an audit row). Human `APPROVED` reopens as `PENDING` when detected minutes grow or the class changes, else is capped at detected. Human `REJECTED` stays rejected unless overtime grows or changes class. `SUPERSEDED_BY_RECALCULATION` action keeps the earlier decision, reviewer and time; record `version` bumps so a stale approver is refused. Full-day leave / ON_DUTY still preserve the decision (BUS-011). New blocker `OVERTIME_INTEGRITY`. | `attendance/service.py` (`_resolve_ot_decision`, `_sync_overtime_record`, `_record_supersede`, validation), `attendance/repository.py` (`replace_for_day`, `delete_for_day`, `cap_decided`), migration `20261116090000` |
| AC-04 | detection ran whatever the status; lock rewrote only paid/LOP | Overtime on an `INCOMPLETE` day is held `PENDING` (stage HR) and never auto-approved. Lock under `TREAT_ABSENT` rejects it and zeroes the day's overtime; `TREAT_PRESENT` / `KEEP_INCOMPLETE` keep the close blocked until HR decides. | `service.py` (`_withdraw_overtime_at_lock`, `_apply_incomplete_lock_resolution`) |
| AC-05 | overtime compared with the full shift on a half-day leave | Overtime basis = net schedule of the worked half (halves and unpaid breaks respected, not 50%). Work inside the leave half sets `work_on_leave_flagged` and earns no overtime. | `calculation.py` (`scheduled_half_net_minutes`, `_half_day_overtime_basis`, `_work_in_leave_half`) |
| AC-06 | `worked_on_weekly_off` read only the calendar `day_type` | `roster_week_off_override` counts (a holiday stays a holiday). | `calculation.py` (`_worked_on_weekly_off`) |
| P-A / P-B | see decisions | built as the audit's recommendation | `calculation.py` |
| AC-02 | calendar mutations never queued | all of them do, scoped by assignment | `attendance/recalc.py` (`request_calendar_recalc`), `organisation/service.py` |
| AC-07 | policy publish never queued | queued from `effective_from`, scoped to the policy's assignments | `recalc.py` (`request_policy_version_recalc`), `attendance/service.py` |
| AC-03 | breakdown fixed at submit | P-E (approved): automatic refund / debit through new ledger entries on every calendar mutation; shortfall exception when the balance is short; close blockers `LEAVE_BALANCE_SHORTFALL` and `LEAVE_CALENDAR_MISMATCH` | `leave/reconciliation.py`, `leave/models.py`, `attendance/recalc.py`, `attendance/service.py` validation, `leave/service.py` (credit retries shortfalls), migration `20261116100000` |
| AC-08 | clients re-derived ownership | clients show `computation_snapshot.inputs.punch_ids` | web `day-detail.ts`, mobile `day_timeline.dart` |
| AC-09 | UTC date | `business_today(company.timezone)` | `calendar_setup.py` |
| lock order | review wrote record then day; calculation locks day then record | review locks the day row first | `service.py` (`_lock_day_first`) |
| failed immediate calc | best effort, nothing queued | durable `IMMEDIATE_CALCULATION_FAILED` request | `service.py` |

Engine version 14 → **15** (P-A, P-B, AC-05, AC-06 change results). **Correction (review R-8):
engine 15 was never committed or deployed; the commit that carries this work and the attendance
rules work moves the stored version 14 → 16.** Every "engine 15" below means "the P-A / P-B /
AC-05 / AC-06 rules, which ship as part of engine 16".

## Database / migration impact
`20261116090000_overtime_supersede_action`: widens the `overtime_action.action` check to allow
`SUPERSEDED_BY_RECALCULATION`. Additive; no row rewritten. Downgrade deletes those action rows.

`20261116100000_leave_balance_shortfall`: new table `leave_balance_shortfall` (RLS forced). Additive.

## Not done in this change (stated plainly)
* AC-03: roster / shift changes do not trigger leave reconciliation (caught at close only); an
  accrual does not retry an open shortfall; no shortfall list screen or endpoint.
* Re-ownership recalculation of the previous owner's day after a punch; sibling-day recalculation
  for weekly/monthly caps.
* Concurrency tests (approval vs recalculation, two approvers, queue reprocessing); the lock-order
  change is made but only exercised by the existing simultaneous approve/reject test.
* Property-based invariant tests; a full cross-module scenario test; timezone-boundary tests for
  00:00 / 05:30 IST on the new rules.
* Waiting on queued recalculation requests before finalize (finalize recalculates open days itself).
* Policy screen text for P-D.
* Mobile Dart change is unverified: Flutter is not installed on this machine.

## Operational steps after deploy
1. Apply the migration (`alembic upgrade head`).
2. Preview scope before recalculating: run `scripts/sql/attendance_integrity_report.sql` and the
   leave drift check; note affected employees and dates.
3. Recalculate unlocked days of open periods in bounded ranges with
   `POST /attendance/days/calculate-range` (idempotent; locked days are skipped). Engine 16 (which
   includes these rules) changes
   half-day-leave, half-weekly-off, roster-off and half-day/absent overtime, so expect overtime to
   change on those days only.
4. Re-run the report and review the period `validate` output before closing any period.
