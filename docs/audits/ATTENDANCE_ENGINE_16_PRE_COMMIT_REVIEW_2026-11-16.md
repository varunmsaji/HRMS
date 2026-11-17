# Independent pre-commit review — Attendance engine 16 (AC-01…AC-09, AR-01…AR-14, P-E)

**Date:** 16 November 2026 · **Branch:** `test` at `dd71571` (level with `origin/test`, fetched at review
time) · **Scope:** the whole uncommitted working tree, nothing staged · **Reviewer did not modify
application code, commit or push.** The only file added by this review is this report.

## 1. Verdict

**APPROVE WITH CONDITIONS.** The conditions in section 7 must be met **before the commit**. The change set is
not safe to commit as it stands: one defect in the leave reconciliation was reproduced (section 3,
R-1). An employee can lose a day's pay on a date they hold approved leave for, and no period-close
blocker catches it.

The rest of the attendance engine work is sound. The rule changes match the decision register, the
two sessions' edits to `attendance/service.py` and `recalc.py` fit together, both migrations
round-trip cleanly, and every test I ran passed except the known CORS settings test. Several
engine 16 results change pay on unlocked days, and one of them (R-2, wide late bands) needs an
owner decision before any historical recalculation.

## 2. Repository and change ownership

| Item | State |
|---|---|
| Branch / HEAD | `test` / `dd71571`, equal to `origin/test` after `git fetch` |
| Staged | nothing |
| Modified (tracked) | 26 files, +1,883 / −224 |
| Untracked | 24 files: 2 migrations, 1 SQL report, `leave/reconciliation.py`, 8 test files, 11 audit documents, `MOBILE_UX_NEXT_STEPS.md` |
| Engine version | `14` at HEAD → `16` in the working tree. Engine 15 was never committed, so this commit moves **14 → 16** |

Three pieces of work share the tree:

1. **AC-01…AC-09 overtime and calendar remediation** (engine 15). Touches `calculation.py`, `service.py`,
   `repository.py`, `recalc.py`, `organisation/service.py`, `calendar_setup.py`,
   `calendar_impact.py`, web `day-detail.ts`, mobile `day_timeline.dart`, migration `20261116090000`.
2. **AC-03 / P-E leave reconciliation.** Touches `leave/reconciliation.py` (new), `leave/models.py`,
   `leave/service.py`, `notification/types.py`, `recalc.py` (the `reconcile_after_calendar_change`
   call), `service.py` (`LEAVE_*` blockers), migration `20261116100000`.
3. **AR-01…AR-14 attendance rules** (engine 16). Touches `calculation.py`, `service.py`,
   `break_override_service.py`, `employee/service.py`, `organisation/service.py` (AR-08), web and
   mobile templates.

**Overlap points reviewed as one unit:**

- `service._resolve_ot_decision` combines AC-01 (re-derive auto approvals, P-C reopen or cap), AC-04 and
  AR-11 (hold on `INCOMPLETE` or an orphan punch), AR-03 (lock withdrawal re-derived) and D-03 (roster
  week-off always held). The paths are mutually consistent: a held decision always lands at
  `PENDING`/`HR`, and only a reopened human decision widens the `replace_for_day` status guard.
- `service._calculate` combines the AC-01 `preserve_existing` move with the D-04 cap cascade
  (`cap_minutes_before/after`, `include_week`).
- `AttendancePeriodService._run_validation` gains five blockers from three sessions:
  `OVERTIME_INTEGRITY`, `PENDING_LEAVE`, `LEAVE_BALANCE_SHORTFALL`, `LEAVE_CALENDAR_MISMATCH`,
  and the half-day `WORK_ON_LEAVE_UNRESOLVED` text. It also excludes `TREAT_ABSENT` incomplete days
  from `PENDING_OVERTIME_APPROVAL`. No two blockers contradict each other.
- `recalc.request_calendar_recalc` (AC-02) is also the P-E reconciliation entry point, for dated
  changes only.

`MOBILE_UX_NEXT_STEPS.md` is unrelated local notes ("not committed; delete it once the work is
finished") and must stay out of this commit.

## 3. Findings from this review

Severity: **Blocking** = must be fixed before the commit; **Decision** = needs an owner decision before
recalculating history; **Minor** = fix or record, not blocking.

### R-1 (Blocking): a leave whose stored days were all released is never re-charged

`LeaveCalendarReconciliationService._application_discrepancies` returns early when the application
has no stored day rows:

```python
# apps/api/src/hrms/modules/leave/reconciliation.py, lines 141-142
        if not stored:
            return [], {}
```

`_release_day` deletes the day row when a date stops consuming leave (`expected_fraction == 0`). So
when every day of an approved leave is released, for example a single-day leave on a date that
becomes a holiday, the application keeps status `APPROVED` with zero days. If the holiday is then
removed, the under-charge is never detected:

- nothing is debited and no day row or projection is added;
- the read-only detector (`find_discrepancies`) also returns nothing, so **period close raises no
  `LEAVE_CALENDAR_MISMATCH`**;
- attendance sees a working day with no leave behind it, which becomes `INCOMPLETE` and then absent
  (loss of pay) at lock under `TREAT_ABSENT`.

This is exactly the under-charge P-E exists to prevent, and the safety net misses it.

**Reproduced** with a throwaway integration test run from a copy of the test package against a cloned
test database. Same helpers as `test_leave_calendar_reconciliation.py`; single-day leave on
2026-09-09:

```text
after approval        balance 19.00
after holiday added   balance 20.00  total_days 0.00  days []
after holiday removed balance 20.00  APPROVED  total_days 0.00  days []
                      blockers: CONFIG_ERROR, EMPLOYEES_WITHOUT_ATTENDANCE (test setup only; no LEAVE_*)
```

The expected balance after removal is 19.00, with the day restored and projected. The existing
tests only use a three-day leave with one released day, so the gap is not covered.

The application row has no `half_day` column; the half is known only from the day rows. Fix
options: keep a zero-fraction day row (preserving `half`) instead of deleting it, or store the half
on the application. Both need a regression test for (a) a single full day, (b) a single half day,
and (c) a multi-day leave whose every day was released and then restored.

### R-2 (Decision): D-01 turns wide late/early mark bands into full-day pay

`grace_band_credit(late_judged=True)` credits **all** late minutes to the hour-band lookup when the
late band classifies them as `LATE`, `EARLY_DEPARTURE` or `NONE`. The only guard is that a day the
hour band calls `ABSENT` stays absent. A band does not need to be narrow.

**Reproduced** at engine level on a 09:00–18:00 shift with a 60-minute unpaid lunch, arriving at
13:00 and leaving at 18:00:

| Late bands | Worked | Late | Engine 16 result |
|---|---|---|---|
| none | 240 | 230 | `HALF_DAY`, 0.50 paid |
| `LATE` 31–240 | 240 | 230 | **`PRESENT`, 1.00 paid** |

Engine 14 gives `HALF_DAY` in both cases. The development database holds exactly such bands
(`LATE` 11–120 ×4, `LATE` 31–240 ×2, `EARLY_DEPARTURE` 16–120 and 31–240). The shipped templates
(1–59 minutes) are safe; existing policies are not. The AR remediation's change table lists this
case only as "half-day → present" for minutes inside a mark band, without saying that a band can
cover half a shift.

The owner must decide one of: (a) accept it as D-01 intends, (b) cap the credit (for example to the
mark band's upper bound or a fixed ceiling such as 59 minutes), or (c) audit and edit existing policies
before recalculating. Until then, do not run the historical recalculation for companies whose
policies have mark bands wider than an hour.

### R-3 (Decision, operational): `LEAVE_CALENDAR_MISMATCH` has no supported remedy for roster, shift or pattern drift

Only **dated** changes (holiday, calendar exception) reconcile leave automatically. A weekly-off
pattern, work-calendar, holiday-calendar validity, roster or shift change that alters an approved
leave's breakdown is caught by the period-close blocker. However, nothing in the API runs `reconcile`
on demand: the only callers are the dated calendar mutations and the HR balance credit. HR's only
remedy is to cancel and re-apply the leave, or to touch a calendar entry on each affected date.
Existing drift (5 cases in dev mock data) will block close for every period containing it from the
first deploy. The AC remediation results already record the policy-A conflict as open; this review
adds that the blocker has no resolution path.

### R-4 (Minor): D-04 cascade stops at the month boundary for a week that spans two months

When an earlier day's cap minutes change, `_recompute_later_days_of_month(include_week=True)`
recalculates up to `max(month_end, week_end)` with `recompute_later_days=False`. Days in the next
month inside that week change their own counted minutes, but the rest of the next month, whose
**monthly** budget depends on them, is not recalculated. "One pass in date order is enough" holds within
the month, not across it. The next period's close recalculates in date order and corrects it, so
nothing wrong is locked. Until then the open month's figures depend on calculation order. Not
tested (the authors list D-04 across a month boundary as not covered).

### R-5 (Minor): cap re-allocation does not follow HR decisions

`sum_minutes_counted_for_cap` counts `PENDING` at detected minutes and decided records at approved
minutes, so a partial approval or a rejection on Monday frees budget for later days. Approve and reject
write the record and day directly and do not recalculate later days. The freed minutes are
re-allocated only at the next recalculation or at close. At close, a later human-`APPROVED` day
whose detection grows is reopened as `PENDING` (P-C) and blocks the close. That is correct, but HR
should be told to expect it.

### R-6 (Minor): the D-04 cascade runs when the policy has no caps

`cap_minutes_after != cap_minutes_before` compares the day's counted overtime whether or not the
overtime policy has a weekly or monthly cap. Any overtime change on a past day, such as a
regularization approval, then recalculates the rest of the week and month inside that request. The
result is correct but slower, and holds more row locks. Gate it on
`weekly_cap_minutes`/`monthly_cap_minutes` being set.

### R-7 (Minor): a policy republish re-prices human-approved overtime under the label `CAPPED`

In `_resolve_ot_decision`, a human `APPROVED` record with unchanged minutes but a new
`overtime_policy_version_id` takes the `kind="cap"` path. That path rewrites `configured_multiplier`
and the version, and logs `SUPERSEDED_BY_RECALCULATION` with outcome `CAPPED`. The approver approved
minutes, not money, so this is defensible, but the outcome label is misleading in the audit trail.
Use a distinct outcome such as `POLICY_VERSION_CHANGED`.

### R-8 (Minor): user-facing and documentation text contradicts the code

| Where | Says | Code does |
|---|---|---|
| `calendar_impact.py` warning `LEAVE_NOT_RECALCULATED` | "Existing leave day records are not changed automatically … any balance adjustment is a separate leave action" | A holiday or calendar-exception change **does** rewrite approved leave and the balance automatically (P-E) |
| `ATTENDANCE_LEAVE_CALENDAR_RECONCILIATION.md` "Trigger" | Reconciles on "every calendar mutation (holiday, holiday calendar, weekly-off pattern, work calendar, …)" | Dated changes only |
| `ATTENDANCE_RECALCULATION_TRIGGER_MATRIX.md` | "every calendar mutation in the table also reconciles approved leave"; sibling caps "Not changed" | Dated only; sibling caps fixed by AR-04 / D-04. AR-09 triggers (employment create/terminate, break override) are missing from the table |
| `ATTENDANCE_OVERTIME_REMEDIATION_PLAN.md` / `_RESULTS.md` | Engine 14 → 15; "sibling OT caps NOT FIXED"; "full suite was not rerun" | Engine 15 never shipped (14 → 16); caps fixed by AR-04; the AR document's later full run supersedes the statement |
| `ATTENDANCE_RULES_REMEDIATION_2026-11-16.md` header | "Engine 15 → 16" | The commit is 14 → 16 |
| `attendance_integrity_report.sql` comment | `docs/ATTENDANCE_PAYROLL_INTEGRITY_CHECK.md` | `docs/audits/ATTENDANCE_PAYROLL_INTEGRITY_CHECK.md` |

### Other observations (no action required)

- AR-03 recognises a lock withdrawal by matching `rejection_reason` text with no reviewer. If that
  string is ever reworded, older rows stop being recognised. Acceptable; a dedicated action code
  would be sturdier.
- AR-01 under `SHIFT_FLAG`: a roster-only employee with no shift on their policy assignment gets
  `off_day_shift_ot_eligible = None`, so week-off work earns no overtime and nothing says why. Worth
  a snapshot note.
- AR-06: a SPLIT shift whose blocks all fall in one half has no `HalfDayPlan`, so on a half-day
  leave every block is still expected and the leave half's block can count as missed. This is an edge
  case and is documented in the `half_day_plan` docstring.
- `leave_balance_shortfall` foreign keys are `ON DELETE CASCADE`. `leave_application_action` uses
  `RESTRICT`. Employees and applications are not hard-deleted in normal flows, so this is consistent
  enough.

## 4. Finding-by-finding review

"Code" means the change was read and matches the stated fix. "Tests" means the regression tests were
read and pass in this review's own run (section 6).

| ID | Verdict | Notes |
|---|---|---|
| AC-01 | **Verified** (code, tests) | Auto approvals re-derived and idempotent when figures are identical. Human decisions reopen or cap per P-C, with history kept in `SUPERSEDED_BY_RECALCULATION` and the audit log. `replace_for_day` bumps `version` and clears review fields. `OVERTIME_INTEGRITY` blocker added. Caveats: R-5, R-7 |
| AC-02 | **Verified** (code, tests) | Holiday, holiday calendar, pattern, work calendar and exception all queue recalculation, scoped to a superset. Deactivations route through the update methods, so they are covered |
| AC-03 / P-E | **Not verified: defect** | Refund, debit, negative floor, shortfall, HR credit, cancellation and closed-period protection work as tested. **R-1** breaks re-debit after a full release. **R-3**: no remedy for undated drift |
| AC-04 | **Verified** (code, tests) | Held `PENDING`/HR; `TREAT_ABSENT` rejects at lock and zeroes the day. `TREAT_PRESENT` / `KEEP_INCOMPLETE` paths untested (authors state this) |
| AC-05 | **Verified** (code, tests) | Now superseded in detail by AR-06/AR-07 (credit clipped to the worked half; conflict at ≥ half of the leave half) |
| AC-06 | **Verified** (code, tests) | `_worked_on_weekly_off` counts a roster week-off; a holiday stays a holiday |
| AC-07 | **Verified** (code, tests) | Both attendance and overtime policy publishes queue from `effective_from`, scoped to the policy's assignments. Attendance publish is not separately tested |
| AC-08 | **Verified on web; mobile not run** | Both clients use `computation_snapshot.inputs.punch_ids` and fall back to the fetched list when a day has never been calculated. The web suite passes. Flutter is not installed on this machine; CI runs `flutter analyze` and `flutter test` |
| AC-09 | **Verified** (code) | `business_today(company.timezone)` |
| AR-01 | **Verified** (code, tests) | Every gross minute is `WEEKLY_OFF` overtime, capped through `detect_overtime`, always held for a person. Gross minutes with no break deduction is a D-03 choice awaiting confirmation |
| AR-02 | **Verified with a decision needed** | Templates, web and mobile match. Behaviour is as specified, but **R-2** shows wide bands pay a full day for half a day's work. The cliff remains for policies without bands (documented) |
| AR-03 | **Verified** (code, tests) | See the observation on text matching |
| AR-04 | **Verified within a month** | Earlier dates only; later days recalculated in date order; locked days skipped; four-order test passes. Gaps: R-4, R-5, R-6 |
| AR-05 | **Verified** (code, tests) | Harshest verdict wins. A cumulative `ABSENT` override is now honoured too (previously only `HALF_DAY`) |
| AR-06 | **Verified** (code, unit tests) | SPLIT halves by block midpoint; FLEXIBLE full requirement treated as the conflict |
| AR-07 | **Verified** (code, unit tests) | Silent non-credit below the threshold is documented and visible in the snapshot |
| AR-08 | **Verified** (code, test) | `model_fields_set` catches an explicit `null` |
| AR-09 | **Verified** (code, tests) | Employment create and terminate, break override create and revoke. Other employment edits were not reviewed |
| AR-10 | **Verified for LV-04** | `PENDING_LEAVE` blocker (status `SUBMITTED` is the only pending state). Roster and shift leave reconciliation is outstanding (P-12, R-3) |
| AR-11 | **Verified** (code, test) | Expect more `PENDING_OVERTIME_APPROVAL` blockers under `AUTO_CLOSE` |
| AR-12 | **Verified** (code, unit tests) | |
| AR-13 | **Verified** (code, unit tests) | |
| AR-14 | **Verified** (code, unit tests) | |

**Engine-version consistency.** `ENGINE_VERSION = 16` is written to every recalculated row
(`attendance_day.engine_version`) and to its snapshot; locked rows keep their old value. Nothing
else reads the version (payroll does not), and raising it recalculates nothing by itself.

**Determinism.** Within one employee-month, results no longer depend on calculation order (D-04;
the cumulative counters R-04 already did this). The exceptions are R-4 (week across a month
boundary) and R-5 (HR decisions); both converge at close because close recalculates every open day
oldest first.

## 5. Migration review

| | `20261116090000_overtime_supersede_action` | `20261116100000_leave_balance_shortfall` |
|---|---|---|
| Chain | `20261115090000` → this | `20261116090000` → this (head). Linear, no branches |
| Upgrade | Drop and re-add the `overtime_action.action` check with `SUPERSEDED_BY_RECALCULATION` | New table, FKs to company, employee, leave_application, leave_type; unique (application, date); status and resolution checks; partial index on open rows; `FORCE ROW LEVEL SECURITY` with the standard tenant policy |
| Downgrade | Deletes every `SUPERSEDED_BY_RECALCULATION` action (audit history is lost), then restores the old check | Drops the table (open exceptions are lost) |
| Tested here | Round trip on a clone of `hrms_ar_test`: `downgrade -2` → `20261115090000`, table gone; `upgrade head` → table back with RLS forced | Same run |
| Existing data | Additive; the check re-validation scans `overtime_action` under an exclusive lock (small table today; `NOT VALID` + `VALIDATE` would avoid the lock at scale) | Additive |
| Code/schema skew | Old code on the new schema is fine. **New code on the old schema fails**: the first supersede violates the check and rolls back the calculation, and period validation queries a missing table. Apply the migrations **before** deploying the code | |

Downgrade is only safe before the engine 16 recalculation runs. After it, downgrading deletes the
supersede history and open shortfalls.

Because the change touches `apps/api/alembic/`, the pull request will **not** auto-merge. The user
must merge it (`gh pr merge --merge`).

`alembic check` reports large model/schema drift (for example `pay_run_employee`,
`attendance_policy_hour_band`). This drift predates this change, and CI does not run that command.

## 6. Verification evidence

**Run by this review** (the cloned test database `hrms_review_20261116` was dropped afterwards; Redis
index 7 and Celery index 13; `FACE_PROVIDER_COMPARISON_ENABLED=false` set in the process because the
local `apps/api/.env` enables it while the test configuration disables the face provider, which
otherwise stops test collection):

| Check | Result |
|---|---|
| `ruff check .` / `ruff format --check .` | clean / 886 files formatted |
| `mypy src/hrms` | no issues, 287 files |
| `lint-imports` | 1 contract kept, 0 broken |
| Mobile contract fixtures (CI step), regenerated to a temp directory and diffed | identical |
| `pytest tests/unit` | **2,133 passed, 1 failed**: `test_settings.py::test_development_has_no_explicit_origins_but_a_valid_fallback` (local `.env` CORS, known) |
| Integration: the 10 new or modified files (attendance rules, calendar triggers, overtime period close, overtime recalculation, leave-overtime interaction, overtime record, leave calendar reconciliation, period-close pending leave, leave balance races, calendar impact) | **98 passed** |
| Web `tsc --noEmit` | clean |
| Web `vitest run` (whole suite) | **151 files, 1,045 tests passed** |
| ESLint on the three changed web files | clean |
| Migration round trip | passed (section 5) |
| R-1 and R-2 probes | reproduced (section 3) |

**Not run by this review:**

- The full `tests/integration tests/security` suite. The figure of 4,704 passed / 2 failed comes from
  the AR document and was not reproduced here.
- `test_punch_after_last_working_day`, the second known failure; it was outside the files run.
- Web `next build` and repository-wide ESLint.
- Flutter: not installed on this machine. CI runs `flutter analyze` and `flutter test`.

**Claims about the old implementation.** The tests' docstrings quote "before" values from the audits.
The AR document states plainly that the tests were not run against the old code. The AC results
document says the two baseline failures were checked with `git stash`; this review did not repeat
that.

**Known unrelated failures.** (1) The CORS settings test reads the local `.env`; reproduced here.
(2) `test_punch_after_last_working_day` depends on the time of day; not reproduced here. A third local
environment issue, the face-provider comparison flag in `.env`, prevents test collection unless it
is overridden.

**Scenario coverage still missing:** a concurrency test for two reconciliations at once; D-04 across
a month boundary and for the monthly cap; `TREAT_PRESENT` / `KEEP_INCOMPLETE` with held overtime; a
roster week-off over midnight and in Asia/Kolkata at the API level; pattern, work-calendar or
roster drift inside leave; R-1.

## 7. Required before commit

1. **Fix R-1** in `leave/reconciliation.py` and add regression tests for a single full day, a single
   half day, and a multi-day leave with every day released and then restored. Rerun
   `test_leave_calendar_reconciliation.py` and the period-close tests.
2. **Record R-2** in `ATTENDANCE_RULES_REMEDIATION_2026-11-16.md` (sections 5 and 6) as a result
   change needing HR review, and add it to the decision register.
3. **Correct the text in R-8**: the `LEAVE_NOT_RECALCULATED` warning in `calendar_impact.py`, and the
   five documents listed. State in the AR document that the commit moves the engine 14 → 16.
4. **Leave `MOBILE_UX_NEXT_STEPS.md` out of the commit.** Stage files by name.
5. Run `pytest tests/unit tests/integration tests/security` once more after the fixes, on an
   isolated database, and record the result. The two known failures stay as named in section 6.
6. Commit the migrations with the code, and tell the user that the pull request waits for a manual
   merge.

**Recommended, not blocking:** R-4 (extend the cascade across the month boundary for the monthly
cap), R-6 (gate the cascade on caps being configured), R-7 (a distinct outcome label), and a manual
or HR "reconcile this leave" action to close R-3.

## 8. Historical recalculation impact

**Protection.** `calculate()` refuses locked days; reconciliation skips dates inside closed
attendance periods (tested); a finalized payroll period cannot be reopened. Ledger entries, overtime
actions and leave application actions are only appended to.

**Idempotence and resumption.** Auto approvals with identical figures are left untouched, a P-C cap
with identical figures is left untouched, and reconciliation works by state. The range task commits
each employee-date separately and counts failures instead of raising them, so a failed or timed-out
run is resumed by running the same range again. There is no persisted progress marker; the whole
range is reprocessed, which is safe but slow.

**Results that will change on unlocked days**, beyond the table in the AR document's section 6:

| Change | Who should look |
|---|---|
| **R-2**: wide late/early mark bands, a half day becomes a full paid day | HR and owner, before recalculating |
| Human-approved overtime whose detection grows (AR-12 restores overtime, D-04 moves budget, AR-01 roster week-off) reopens as `PENDING` and blocks close | HR approvers |
| Auto-approved overtime on orphan-punch days (AR-11) and roster week-offs (D-03) becomes `PENDING` | HR approvers |
| `PENDING_LEAVE`, `LEAVE_CALENDAR_MISMATCH` (existing drift; 5 in dev) and `OVERTIME_INTEGRITY` blockers appear on the first validate | Payroll admin |
| Half-day-leave days at 0.25 / 0.75 paid | Payroll admin (summary bucket label is approximate) |

**Operational plan gap.** The AR document's section 7 covers the integrity report, `validate`,
execution with `calculate-range`, and re-validation. It has no real **preview**: neither the
integrity report nor `validate` shows what engine 16 will change. Before recalculating, export
`(employee_id, attendance_date, attendance_status, paid_day_fraction, lop_fraction,
ot_minutes_detected, ot_minutes_approved, engine_version)` for every unlocked day of the open
periods. Diff the same export afterwards and explain each change against the tables above. Run it per
company and per period, and hold companies affected by R-2 until it is decided.

## 9. Outstanding product decisions

New from this review: **R-2** (wide mark bands under D-01) and **R-3** (how HR resolves undated leave
drift; also the policy-A conflict recorded in the AC results).

Built as defaults, awaiting confirmation: P-A, P-B, P-C, AC-04 under `TREAT_PRESENT`, AC-05/AR-07
threshold, AR-06 flexible, AR-11, AR-12, D-09/AR-14, LV-04, D-03 gross minutes, D-04 `PENDING`
reservation, the D-01 template band (1–59), and what to do with existing policies that have no
late/early bands (the one-minute cliff remains).

Not decided: P-01, P-04, P-05, P-10, P-11, P-12, P-14, P-D (policy screen wording), D-07, LV-01…LV-13
except LV-04.
