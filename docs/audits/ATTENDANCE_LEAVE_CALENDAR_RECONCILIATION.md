# Leave ↔ calendar reconciliation (AC-03, owner decision P-E approved 16 Nov 2026)

## Problem
A leave application's day breakdown is decided when it is submitted
(`LeaveApplicationService._compute_day_breakdown`). A calendar change made afterwards did not
rewrite it:

* **Over-charge** — a holiday added inside approved leave kept debiting the balance.
* **Under-charge** — a holiday removed inside approved leave left a working day with no leave day
  behind it: attendance saw no punches → `INCOMPLETE` → loss of pay at lock.

With the sandwich rule on (the default), a holiday *between* leave days is charged as a sandwich
day, so adding one there is not a difference; that is R-02 working as designed.

## What is implemented (`apps/api/src/hrms/modules/leave/reconciliation.py`)

**Detection** — `find_discrepancies` (read-only) re-derives each `APPROVED` application's breakdown
with the same `_compute_day_breakdown` submit used, against the current calendar, roster and shift
operating days, and compares it with the stored `leave_application_day` rows.

**Reconciliation** — `reconcile`, as decided in P-E:

| Case | Action |
|---|---|
| Holiday added inside approved leave | Projection cancelled, day row removed, debit refunded by a **new** `ADJUSTMENT` ledger entry referencing the application. Closed-leave-year rule applied as for any refund. |
| Holiday removed, balance sufficient | **New** `APPLICATION` ledger debit referencing the application; day row added; projection synced. |
| Holiday removed, balance short, leave policy allows a negative balance | Debited down to the policy's `negative_balance_floor`, as approval itself does. |
| Holiday removed, balance short, no negative balance allowed | `leave_balance_shortfall` exception opened. **Nothing is debited, no day is added, nothing becomes loss of pay.** |

**Trigger.** Automatic, inside the transaction of every *dated* calendar mutation - a holiday
created or edited, a calendar exception created or edited, and the impact `confirm` that calls
them - via `request_calendar_recalc(dates=...)`. Future leave is covered. It runs in a savepoint: if
it cannot complete, the calendar change still stands, nothing of the reconciliation is written, the
failure is logged, and period close stays blocked by `LEAVE_CALENDAR_MISMATCH`.

**Not automatic** (Work Calendar policy A is not retroactive): holiday-calendar validity, weekly-off
pattern, work calendar, assignment, roster and shift changes. Their drift is caught at period close
and resolved by HR with the operation in the next section (R-3).

**Resolving a shortfall.** HR grants balance (`POST /leave-ledger/adjustments`, a credit): the
waiting day is debited and projected and the exception closes as `DEBITED` in the same request. Or
HR cancels the leave, or the calendar change is undone: the exception closes as
`NO_LONGER_REQUIRED` at the next reconciliation.

**Period close.** Two blockers in `AttendancePeriodService._run_validation`:
`LEAVE_BALANCE_SHORTFALL` (open exceptions, with employee, application, date, days needed and
balance) and `LEAVE_CALENDAR_MISMATCH` (any other difference, e.g. one a failed run left behind).
A blocker stops the whole legal-entity period, which is how every attendance blocker works; the
sample lines name the affected employees.

## Mandatory controls — how each is met
| Control | How |
|---|---|
| Auditable | One `CALENDAR_RECONCILED` / `BALANCE_SHORTFALL` action on the application timeline, one audit-log row, ledger `reason` text naming the date and the application. |
| Idempotent | By state: once reconciled, the date no longer differs, so a repeat finds nothing and writes nothing. An already-open shortfall is refreshed, not re-announced. Tested by re-running after a second edit. |
| History never overwritten | Ledger entries are only inserted. Tested: earlier entries are byte-for-byte unchanged. |
| Original approval preserved | Status, approver, date range untouched; only `total_days` / `lop_days` follow the day rows. |
| Attendance recalculated | Through the existing projection `sync` / `cancel`, which recalculate the day; the calendar mutation also queues the attendance recalculation (AC-02). |
| Locked / finalized history protected | A date inside a closed attendance period is skipped and returned as `protected`. Tested. |
| Employee and HR notified | In-app notifications `LEAVE_BALANCE_RECONCILED` and `LEAVE_BALANCE_SHORTFALL` to the employee and company-wide leave approvers. |
| Effective dates respected | The breakdown is re-derived per date by the calendar resolver, which applies assignment and validity dates. |
| No payroll rules | No payroll code or figure is touched. |

## Database
Migration `20261116100000_leave_balance_shortfall`: new table, one row per application-date, RLS
forced. No new ledger entry type: refunds are `ADJUSTMENT`, debits are `APPLICATION`, both with
`reference_id` = the application, so cancelling the leave later refunds exactly what it debited
(tested).

## Limits (stated plainly)
* **Roster, shift, weekly-off-pattern and work-calendar changes do not trigger reconciliation**
  (P-12, policy A). They are caught at period close by `LEAVE_CALENDAR_MISMATCH`; HR resolves them
  with the preview / apply operation below.
* A balance that becomes sufficient through **accrual or carry-forward** does not retry an open
  shortfall by itself; an HR credit, or any calendar edit, does. There is no HR "retry" button or
  shortfall list screen/endpoint — HR sees them in the period validation and the notification.
* Cross-application sandwich bridge days (R-02) are skipped, not validated.
* A calendar-wide edit (pattern or work calendar) checks every approved application of the
  company in the request; fine at current volumes, not measured at scale.
* Locked-period differences are only returned by `reconcile` and by the read-only detector; there
  is no report screen. Correction follows `ATTENDANCE_PAYROLL_INTEGRITY_CHECK.md`.
* The 5 differences found in dev mock data on 16 Nov were not reconciled; nothing was run against
  the dev database.

## Tests
`tests/integration/modules/leave/test_leave_calendar_reconciliation.py` (6): refund with
idempotency and history preservation; debit, then cancel refunds everything; shortfall is an
exception and not loss of pay, blocks close, and an HR credit resolves it; shortfall closes when
the holiday returns; negative balance only where the policy allows; closed period never changed.
Sandwich-rule recalculation is not tested. The cases the original tests lacked are now covered by
the two files described in the next sections.

## Leave whose every day was released (review R-1, fixed)

**Defect.** `_release_day` deletes a day row when its date stops consuming leave. When *every* day
of an application was released (a single-day leave on a date that became a holiday, or a
multi-day leave covered by holidays) the application stayed `APPROVED` with no day rows, and
`_application_discrepancies` returned early on "no stored days". Removing the holiday again then
charged nothing, projected nothing and raised no `LEAVE_CALENDAR_MISMATCH`, so the employee lost a
day's pay on a date they held approved leave for. Reproduced by the review, and again here against
the unchanged code (4 of 5 new tests failed at the restoration step).

**Fix.** The application is the durable record, not its day rows:

* `leave_application.half_day` (migration `20261116110000_leave_application_half_day`, nullable,
  no CHECK because the day table has none and the dev data holds a legacy `FIRST`) stores which half
  a single-date application covers. It is written at submit. The migration backfills it from the
  stored day row of every single-date application that still has one.
* `_application_discrepancies` no longer returns early. With no day rows it re-derives the
  breakdown from the application's own range and half, so every date the calendar now makes a
  leave day is `UNDER_CHARGED` and is debited, projected or turned into a shortfall exception like
  any other.
* Applications whose days were already all released *before* the migration have no half to read; they
  are restored as full days. `attendance_integrity_report.sql` section 7 lists them.

Limits: a day that was approved as loss of pay (`is_lop`) and then released is restored as a normal
debit, not as LOP (as already happened for a partly released leave); if the balance cannot cover it
that becomes a shortfall exception, never LOP.

## HR reconciliation operation (review R-3)

`POST /v1/leave-reconciliation/preview` and `POST /v1/leave-reconciliation/apply`
(permission `LEAVE.BALANCE_ADJUST` at **company** scope; a narrower scope is refused).

* **Scope** - approved leave overlapping `[date_from, date_to]` (at most 400 days), optionally for
  up to 200 named employees. Only differences on dates inside the window are reported or changed.
* **Preview** (read-only) - each differing date with `kind` (`OVER_CHARGED` / `UNDER_CHARGED`), the
  stored and expected fraction and an `outcome`: `REFUND`, `RELEASE_ONLY` (nothing to refund: an LOP
  day), `DEBIT`, `ADD_ONLY` (leave type with no balance), `SHORTFALL` (the balance cannot cover it)
  or `PROTECTED` (inside a closed attendance period). The balance forecast follows the order the
  run works in, including refunds that fund later debits. The response carries a `digest` of the
  exact set of lines.
* **Apply** - requires the preview's `digest`, a reason (3-500 characters) and an
  `Idempotency-Key`. It takes the employee leave-date locks and the shared period-close lock,
  re-derives the preview from the state it finds under them and **refuses with 409
  `LEAVE_RECONCILIATION_PREVIEW_STALE`, writing nothing,** if that no longer matches the digest.
  When nothing actionable is left (a repeat, or only closed-period dates remain) it changes nothing
  and reports `noop: true` whatever the digest.
* **Transactional** - one request transaction; any failure rolls back ledger, days, projections and
  audit together (unlike the dated-calendar hook, which uses a savepoint so it can never fail a
  holiday edit).
* **Idempotent** - by state, by digest, and by `Idempotency-Key` (a retry replays the stored
  response).
* **Auditable** - the usual per-application timeline entry, audit row and notifications, now
  carrying the HR reason, plus one `LEAVE_CALENDAR_RECONCILIATION_RUN` audit row per call (actor,
  reason, window, digest, counts, whether it was a no-op).
* **Protected** - dates in a closed attendance period (and so a finalized payroll) are never
  changed; they are listed as `PROTECTED`.
* **No silent LOP** - a shortfall opens the same exception as the automatic path, blocks period
  close, and is resolved by granting balance, cancelling the leave or undoing the change.

Policy A caveat: running this over a pattern or work-calendar change applies the new calendar to
approved leave that was approved under the old one. That is HR's explicit, previewed choice, and
the owner decision on the `LEAVE_CALENDAR_MISMATCH` / policy A conflict (still open) decides
whether it should instead be the default.

There is **no screen** for this yet (API only), and no scheduled run.

### Tests added for R-1 and R-3
`test_leave_full_release_restoration.py` (5) - single full day, single half day, multi-day with every
day released and restored one at a time, repeated cycles and cancellation, cancel while fully
released. `test_leave_reconciliation_operation.py` (8) - weekly-off change refund (preview is
read-only, wrong digest refused, apply, replay, repeat is a no-op), shortfall stays an exception and
is never LOP, roster week-off refund, shift operating on the weekly off debit, stale preview,
closed-period protection, two concurrent applies change the leave once, authorization and window
bounds.
