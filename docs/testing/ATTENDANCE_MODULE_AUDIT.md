# Attendance module audit (pass 1)

Scope of this pass: the punch path, leaver handling in periods, and a review of the approval
guards. Existing coverage was inventoried first (about 200 integration tests across 20 files);
this pass looked for gaps rather than repeating it.

## User flows

| Flow | Actor | Path |
|---|---|---|
| Self punch | Employee | `POST /attendance/punches/me` (`ATTENDANCE.PUNCH`). The server clock is used, no client time. Needs a linked employee. |
| Face punch | Employee | `POST /attendance/face-punches/me`: attempt limit, enrolled, liveness, match, then a `FACE` punch. |
| Punch on behalf | HR | `POST /attendance/punches` (`PUNCH_ON_BEHALF`). Past only, not before employment, not in a closed period, reason mandatory. |
| Calculation | System / HR | An immediate best-effort calculate after each punch, a trailing daily sweep, and manual calculate/recompute. A locked day refuses. |
| Regularization | Employee, then manager and/or HR | Submit, then MANAGER, MANAGER_THEN_HR or HR chain, then approve or reject. Applies as synthetic punches or a roster row and recomputes. Self-approval is blocked. |
| Overtime | System, then manager/HR | Detected at calculation, approved per chain, comp-off credit. Self-approval is blocked. |
| Period close | HR | Create, validate, finalize (locks days, freezes the summary), reopen. Feeds payroll. |
| Face enrollment | HR + employee | HR opens a 48h window, the employee captures 5 angles, HR approves. |

## Findings

| # | Finding | Severity | Status |
|---|---|---|---|
| A1 | The punch idempotency key is unique per company, not per employee. Reusing a key for a different employee returned 201 with the first employee's punch (data leak) and silently dropped the second employee's punch. | High | **Fixed.** Cross-employee reuse now returns 409 `DUPLICATE_PUNCH_IDEMPOTENCY_KEY`; the same employee retrying still replays. Test: `test_idempotency_key_is_not_replayed_across_employees`. |
| A2 | A punch dated after the employee's last working day was accepted (only a floor at joining was enforced). | P2 | **Fixed in pass 2** (decision: reject). See below. |

## Verified working (now pinned by tests)

- A leaver mid-period: days after the last working day are `EXITED`, with 0 LOP. The period validates
  READY and finalizes, and the frozen summary reports them as not employed.
  Test: `test_leaver_period_finalizes_with_exited_days_not_blocking`.
- Self-approval is blocked on regularization and overtime. Locked periods block submit, recompute and OT approve.
  Existing tests cover this.

## Not yet covered (next pass)

Face punch end to end against Face++, regularization with a rehire gap, the overtime to leave comp-off
hand-off, the daily sweep across companies, the web attendance screens, and mobile punching.


# Pass 2

## A2 rule (implemented)

A punch from any source is rejected with `422 EMPLOYEE_TERMINATED` when its **company-local**
calendar date is after the last working day of the employment episode governing that date. The last
working day itself is allowed. A date in a rehire gap resolves to the earlier, terminated episode and
is rejected; a date inside the new episode is accepted. The check lives in `PunchService.record_punch`
(self, on-behalf and face punches all go through it) and in the regularization apply loop (the only
other code that inserts punches). `EXITED` calculation is unchanged.

## Findings

| ID | Severity | Finding | Status |
|---|---|---|---|
| A2 | P2 | Post-termination punches accepted | Fixed |
| R1 | P1 | A regularization request's `requested_punches` were not tied to its `attendance_date`. An approved request could write punches onto any other date: future, another month, or outside the employee's employment. They bypassed the future-punch and employment checks that the punch routes enforce. | Fixed: at submit, the date must be within employment, each requested punch must be within +/-1 day of the attendance date, and none may be in the future. |
| R2 | P3 | Regularization on a date before the employee's joining is refused only incidentally (no policy resolves). | Informational |
| S1 | P1 | Sweep held row locks for a whole company in one transaction. | **Fixed**: one transaction per employee-date. A punch for an already-swept employee no longer waits (0.07-0.10 s measured). |
| S2 | P2 | No lock or statement timeouts. | **Fixed**: `calculate()` bounds both (`attendance_lock_timeout_ms` 5000, `attendance_statement_timeout_ms` 30000; the punch's immediate calculation uses `attendance_punch_calc_lock_timeout_ms` 1000). A timeout is a 503 `DATABASE_BUSY` on requests and a counted, retried-next-run skip in the sweep. |
| S3 | P3 | The sweep has no retry or time limit, and an infrastructure failure rolls back the whole company. The next day's trailing-3-day window repairs it. | Informational |
| C1 | Informational | Comp-off credit and expiry are idempotent and concurrency-safe. Credits survive termination and rehire. There is no reversal path for an approved OT record. Expiry skips a credit whose balance was partly spent (documented LD-14 heuristic). System credits have a ledger row but no audit_log entry. | Tested, no change |
| W1 | P3 | The web on-behalf pickers load only the first 100 employees. | Open |
| W2 | P3 | `GET /attendance/days` and `/punches` are unbounded when no date range is sent, and `/attendance/days` runs one breaks query per row. The web page always sends a single date. | Open |
| M1 | P3 | Mobile self-punch sends no `idempotency_key`; a retry after a lost response can create a second punch (the calculation collapses duplicates). | Open |
| M2 | P2 | Mobile and web manual punch remains available next to face punch (known). | Open, product decision |
| F1 | Informational | Real Face++ validation with a real face on a real device was **not executed**. Anti-spoofing (single-image liveness) is a separate product and security decision. | Not executed |
