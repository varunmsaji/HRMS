# Remediation results — 16 Nov 2026

Branch `test` from `dd71571`. Nothing committed. Plan: `ATTENDANCE_OVERTIME_REMEDIATION_PLAN.md`.

> **Superseded in part (independent pre-commit review R-8, 16 Nov 2026).** Engine 15 never shipped:
> the commit moves the engine **14 → 16**. "Sibling OT caps NOT FIXED" below is out of date: the
> caps are allocated in date order and re-allocated across the week, the month and a month boundary
> by AR-04 / D-04 and review R-4, R-5, R-6. "The full suite was not rerun" is superseded by the full
> runs recorded in `ATTENDANCE_RULES_REMEDIATION_2026-11-16.md` and
> `ATTENDANCE_ENGINE_16_PRE_COMMIT_VERIFICATION_2026-11-16.md`. The open policy-A conflict and the
> "no resolution path" gap are addressed by review R-3 (HR reconciliation operation).

## Test run
Full API suite (`tests/unit tests/integration tests/security`), isolated `hrms_test`, nothing else
running: **4,631 passed, 2 failed, 40 skipped, 1 xfailed, 26m10s.**
The 2 failures also fail on the untouched baseline (checked with `git stash`): the CORS settings
test (local `apps/api/.env`) and `test_punch_after_last_working_day` (depends on today's date).
A first run stopped early at 40 failures; those were interference from tests I ran concurrently on
the shared database, and all 270 tests in the affected files passed when rerun alone.
Also: `ruff check`, `ruff format`, `mypy src/hrms` clean. Web `day-detail` tests pass (10).
**Mobile (Dart) not run — Flutter is not installed here.**

## Update after P-E (leave reconciliation), same day
P-E was approved and built (`ATTENDANCE_LEAVE_CALENDAR_RECONCILIATION.md`). Full suite after it:
4,632 passed, 4 failed - the 2 baseline failures plus 2 tests pinning "calendar changes never
rewrite leave days". One (`test_stale_preview...`) was updated to P-E. The other pins Work Calendar
policy A (a weekly-off pattern change is not retroactive), so automatic reconciliation was limited
to **dated** changes (holidays, calendar exceptions); pattern / work-calendar / holiday-calendar
edits do not rewrite approved leave. After that change: organisation + leave + trigger suites
731 passed, 1 failed (`test_an_approval_arriving_during_finalisation_is_refused_cleanly`), which
fails on a `PENDING_LEAVE` (LV-04) close blocker added by other uncommitted work in the same
working tree, not by this remediation. **The full suite was not rerun after this last change.**
Open conflict for the owner: `LEAVE_CALENDAR_MISMATCH` still reports a leave day whose fraction
differs after a pattern change, which policy A says is legitimate.

## Status
| ID | Status |
|---|---|
| AC-01 | FIXED AND VERIFIED (integration + period close). Not covered: comp-off after correction, weekly/monthly cap interaction, policy-version-change cases, concurrency. |
| AC-02 | FIXED AND VERIFIED for holiday, calendar, pattern, exception triggers. Population scoping is a superset by design. |
| AC-03 | FIXED AND VERIFIED for holiday add / remove (P-E, 6 integration tests). Not covered: roster / shift changes, accrual retry of a shortfall, pattern changes (policy A conflict above). |
| AC-04 | FIXED AND VERIFIED (held overtime; `TREAT_ABSENT` at lock). `TREAT_PRESENT` and `KEEP_INCOMPLETE` paths are not tested. |
| AC-05 | FIXED AND VERIFIED at engine level (unit). One integration test. Overnight shift and leave-cancellation cases not tested. |
| AC-06 | FIXED AND VERIFIED at engine level. Payroll multiplier for roster-off work not tested end to end. |
| AC-07 | FIXED AND VERIFIED (overtime policy publish). Attendance policy publish uses the same code, not separately tested. |
| AC-08 | Web: FIXED AND VERIFIED. Mobile: IMPLEMENTED, TESTS PENDING. |
| AC-09 | FIXED AND VERIFIED. |
| P-A, P-B | IMPLEMENTED defaults (shipping as engine 16), unit-tested; owner confirmation pending. |
| Lock order (approve/reject) | IMPLEMENTED, TESTS PENDING — no concurrency test written. |
| Failed immediate calculation | FIXED AND VERIFIED. |
| Punch re-ownership | NOT FIXED. |
| Sibling OT caps | Was NOT FIXED here; fixed later by AR-04 / D-04 and review R-4, R-5, R-6 (see the banner above). |

## Tests added (all pass)
Unit `test_overtime_remediation.py` (13); integration `test_overtime_recalculation.py` (6),
`test_calendar_recalc_triggers.py` (5), `test_overtime_period_close.py` (2),
`leave/test_leave_calendar_reconciliation.py` (6); web (3 replaced). Four existing tests were
changed because they pinned behaviour the audit called a bug (frozen auto overtime, P-A,
roster night class, half-day-leave overtime).

## Remaining risks
* AC-03: pattern-change drift is reported at close although policy A allows it (owner decision needed).
* Held overtime under `TREAT_PRESENT` blocks close until HR decides.
* Stale previous-owner day after a re-owning punch; cap sibling days.
* Finalize does not wait for queued recalculation requests (it recalculates open days itself).
* No concurrency, property-based, cross-module or 00:00/05:30 IST boundary tests for the new rules.
* Policy screen text for P-D not updated. All P-decisions are unconfirmed defaults.

## Verdict
**Not payroll-ready.** The overtime defects (AC-01, AC-04, AC-05, AC-06) and trigger gaps are fixed
and tested, and period close now refuses inconsistent overtime and leave. But concurrency and invariant tests are missing, mobile is unverified, the policy
decisions are unconfirmed, and production data has not been checked with the integrity report.
