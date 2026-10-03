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
| A2 | An on-behalf punch dated after the employee's last working day is accepted (only a floor at joining is enforced). The calculation engine classifies the day as `EXITED`, so it stays an inert fact. | Low, decision | **Open, needs a business decision.** The code deliberately avoided adding this rule ("a punch requires an employment record"). Reject it only if you want that. |

## Verified working (now pinned by tests)

- A leaver mid-period: days after the last working day are `EXITED`, with 0 LOP. The period validates
  READY and finalizes, and the frozen summary reports them as not employed.
  Test: `test_leaver_period_finalizes_with_exited_days_not_blocking`.
- Self-approval is blocked on regularization and overtime. Locked periods block submit, recompute and OT approve.
  Existing tests cover this.

## Not yet covered (next pass)

Face punch end to end against Face++, regularization with a rehire gap, the overtime to leave comp-off
hand-off, the daily sweep across companies, the web attendance screens, and mobile punching.
