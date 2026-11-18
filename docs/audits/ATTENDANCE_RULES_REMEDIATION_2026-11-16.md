# Attendance Rules Remediation — AR-01 to AR-14

**Date:** 16 November 2026 · **Branch:** `test` at `dd71571`, working tree only · **Engine 14 → 16 in the commit (engine 15 was never committed)** ·
**Nothing committed.** Source: `ATTENDANCE_RULES_COMPREHENSIVE_AUDIT_2026-11-16.md`.

Payroll code was not touched.

> **After the independent pre-commit review (same day).** Findings R-1 to R-8 were then fixed; this
> document is updated where they change what it says (R-2 in sections 2, 3, 5, 6, 7; engine
> numbering). Results, evidence and what remains: `ATTENDANCE_ENGINE_16_PRE_COMMIT_VERIFICATION_2026-11-16.md`.
> The test counts in section 4 are from before those fixes and are superseded by that report.

**Read this first.** The working tree also holds two earlier, uncommitted pieces of work that this
one builds on and did not change: the AC-01 … AC-09 remediation, and the AC-03 / P-E leave
reconciliation (another session was finishing it, and running its tests, while this work was
done). The files `attendance/service.py` and `attendance/recalc.py` carry changes from all three.

## 1. Status

**Attendance rules are not declared verified.** Every finding AR-01 … AR-14 has a code change and a
regression test except where stated below, and the four blockers are resolved in code. What keeps
the verdict open:

- The rules built for D-01 … D-04 contain choices the decisions did not spell out (section 3).
  They need the owner's confirmation.
- Existing attendance policies with no late or early bands keep the old one-minute cliff (AR-02).
  Only new policies made from the templates are protected.
- P-01, P-04, P-05, P-10, P-11, P-14 and LV-01 … LV-13 (except LV-04) are not decided and not
  changed.
- Mobile changes were not run: Flutter is not installed on this machine.
- Two tests in the full API suite still fail. Both failed before this work and neither concerns
  these rules (section 4).

## 2. Implementation mapping

| ID | Fix | Where | Regression tests |
|---|---|---|---|
| AR-01 | Work on a roster week-off is detected as overtime: every worked minute, class `WEEKLY_OFF` (a holiday stays `HOLIDAY`). `SHIFT_FLAG` eligibility reads the shift on the employee's assignment for that date. The overtime is always held for a person, even under an `AUTO` chain. | `calculation._evaluate_no_schedule`, new input `off_day_shift_ot_eligible`; `service._build_calculation_input`, `_resolve_ot_decision` | unit ×6; API `test_roster_week_off_work_is_weekly_off_overtime_held_for_approval` |
| AR-02 | **D-01:** minutes beyond grace that a late or early band classifies as a mark (`LATE`, `EARLY_DEPARTURE`, `NONE`) are credited to the hour-band lookup, so the mark is the verdict on them. **Bounded by review R-2:** the credit is at most `MARK_CREDIT_CEILING_MINUTES` (59) at each end, or the policy's own grace if larger; a broad band cannot pay for unworked time (see section 3, R-2). A mark can lift a day from half-day to present, never out of absent. **D-02:** on a half-day-leave day the worked half is paid by its own verdict: present = all of it, half-day = half of it (0.25 of the day), absent = none. Templates now ship a "1–59 minutes" late and early mark band. | `calculation.grace_band_credit`, `_is_late_mark`, `_evaluate_fixed_or_flex`, `_apply_leave_overlay`; web `templates.ts`; mobile `attendance_setup_configs.dart` | unit ×14 |
| AR-03 | A rejection written by period lock (no reviewer, fixed reason) is recognised and re-derived on the next calculation, like an automatic decision. A person's rejection is unchanged. | `service._is_lock_withdrawal`, `LOCK_WITHDRAWAL_REASON`, `_resolve_ot_decision` | API ×2 (close → reject → reopen → still incomplete → corrected; human rejection stays) |
| AR-04 | **D-04:** a day's weekly and monthly budget counts only **earlier** dates. When the minutes a day takes from the budget change, every later unlocked day of its week and month is recalculated in date order in the same transaction. | `service._build_calculation_input`, `_cap_minutes_counted`, `_recompute_later_days_of_month(include_week)` | API ×7 (four calculation orders, correction, locked later day, concurrent) |
| AR-05 | Final status is the harshest of the hour band and every late / early / core-hours / cumulative verdict. | `calculation._resolve_primary_status` | unit ×3 |
| AR-06 | **SPLIT:** blocks are divided at the middle of the span; on a half-day-leave day only the worked half's blocks are expected, overtime starts after them, and working the leave half's blocks is flagged. **FLEXIBLE:** working the full required minutes on a half-day-leave day is flagged and earns no overtime. | `calculation.HalfDayPlan`, `half_day_plan`, `split_shift_halves`, `_evaluate_split` | unit ×5 |
| AR-07 | Only the worked half is credited: presence in the leave half is recorded but is neither paid nor overtime. The day is flagged only when the employee was present for at least half of the leave half. Close-blocker text no longer says "full-day". | `calculation.evaluate_presence_and_breaks`, `_work_in_leave_half`; `service._run_validation` | unit ×6 |
| AR-08 | The trigger tests `model_fields_set`, so an explicit `null` pattern queues the recalculation. | `organisation/service.update_work_calendar` | API ×1 |
| AR-09 | Recalculation is queued when an employment is created or terminated and when a break override is created or revoked. | `employee/service`, `attendance/break_override_service` | API ×2 |
| AR-10 | Done by the AC-03 / P-E work (refund, debit, shortfall exception). Added here: **`PENDING_LEAVE`** close blocker (LV-04). Roster and shift changes still do not reconcile leave at the time of the change; the close blocker catches them. | `service._run_validation` | API ×1 |
| AR-11 | Overtime is held for a person on any day with an orphan punch, whatever status `missing_punch_behaviour` gives it. `AUTO_CLOSE` still closes nothing. | `service._resolve_ot_decision` | API ×1 |
| AR-12 | P-B no longer removes overtime when a half-day comes from the hour band alone and the employee worked the whole of the day's own schedule. An absent day still never pays overtime. The half-day status itself (P-05) is unchanged. | `calculation._overtime_forfeited` | unit ×2 |
| AR-13 | On a half-day weekly off nothing is measured as late or early. | `calculation._evaluate_fixed_or_flex`, `_evaluate_split` | unit ×3 |
| AR-14 | On a split shift an orphan punch makes the day `INCOMPLETE` before the missed-block rule, when the policy sends missing punches for review. | `calculation._evaluate_split` | unit ×3 |

Existing tests changed because they pinned a superseded rule (2):
`test_grace_band_credit.py::test_half_day_leave_short_worked_half_is_paid_in_proportion` (was
"…still lost…", D-02) and
`test_overtime_remediation.py::test_a_short_overstay_into_the_leave_half_is_not_a_conflict_and_is_not_credited`
(was "…flagged beyond grace", AR-07).

## 3. Decision register

### Approved and implemented

| ID | Decision | How it was built | Choice made here that needs confirmation |
|---|---|---|---|
| D-01 | Separate lateness / grace from full-day eligibility | A late or early **mark** band is the verdict on those minutes; the hour band no longer counts them against the day | (a) Applies only where a band covers the minutes. A policy with no late bands still judges by hours alone. (b) The template band is 1–59 minutes. (c) A mark never lifts an absent day |
| D-02 | Proportional credit on a half-day-leave day | Worked half paid 100 % / 50 % / 0 % by its present / half-day / absent verdict | Three steps, using the policy's own bands, not minute-by-minute proportion |
| D-03 | Roster week-off work is weekly-off overtime with approval; not both overtime and comp-off | Held `PENDING` always; class `WEEKLY_OFF`. Pay or comp-off follows the policy's existing `comp_off_instead_of_pay`, and payroll's overtime query already excludes comp-off days | No break is deducted (the day has no shift). All minutes are gross presence |
| D-04 | Caps allocated to the earliest dates first | Budget counts earlier dates only; later days recalculated when an earlier day changes | A `PENDING` record on an earlier day still reserves its detected minutes (existing rule N-5) |
| P-E | Leave balance after a calendar change | Built by the AC-03 work, see `ATTENDANCE_LEAVE_CALENDAR_RECONCILIATION.md` | — |

### Built as defaults, awaiting confirmation

| ID | Rule |
|---|---|
| **R-2** (review) | A late / early mark credits at most 59 minutes (or the policy's grace if larger) at each end to the hour-band lookup. Beyond that the hours decide, as in engine 14. Nothing in any published policy version is edited. The ceiling is a constant, not a policy setting, and equals the shipped templates' "1-59 minutes" mark band. | Owner to confirm 59, or choose "no credit at all" (set the constant to 0: a mark then only records lateness and the one-minute cliff of engine 14 returns for every policy) or a per-policy setting (needs a schema change). |
| AR-07 threshold | "Worked the leave half" = present for at least half of that half's net schedule. Below that, the time is simply not credited and nobody is told |
| AR-06 flexible | A full day's required minutes on a half-day-leave day is the conflict |
| AR-11 | Overtime beside an orphan punch always waits for a person |
| AR-12 | Overtime kept on a completed short shift |
| D-09 / AR-14 | Split shift: orphan punch → review before the missed-block penalty |
| LV-04 | Pending leave blocks period close |
| P-A, P-B, P-C, AC-04 | Unchanged from `ATTENDANCE_OVERTIME_POLICY_DECISIONS.md` |

### Not decided, not changed

| ID | Question | Effect today |
|---|---|---|
| P-01 | Holiday at the end of an overnight shift | The whole shift takes the start date's day type |
| P-04 | Early arrival as overtime | FIXED: never. FLEXIBLE: counts |
| P-05 | Hour bands for short shifts | Full attendance on a short shift is a half-day (overtime is now kept, AR-12) |
| P-10 | Night flexible shifts | Not verified |
| P-11 | Late / early on split shifts | Not measured |
| P-12 | Roster or shift change after leave approval | Caught at close only |
| P-14 | Two shifts in a day | Not supported |
| P-D | Non-eligible shift on a day off earns nothing | Unchanged; not shown on the policy screen |
| D-07 | Half-day leave plus ON_DUTY | ON_DUTY, full pay, leave still charged |
| LV-01 … LV-13 except LV-04 | Leave audit findings | Unchanged |

## 4. Tests

All API runs used a database created for this work (`hrms_ar_test`, migrated to head
`20261116100000`, Redis index 3), with no other test process using it.

| Check | Result |
|---|---|
| `pytest tests/unit tests/integration tests/security` — final run, one uninterrupted pass | **4,704 passed, 2 failed, 40 skipped, 1 expected failure**, 24 min 29 s |
| `ruff check .`, `ruff format --check .`, `mypy src/hrms`, import boundaries | clean |
| Web: `tsc --noEmit`; `vitest` for the attendance-policy library, pages and components | clean; 33 passed |
| Mobile (Dart) | **not run** — Flutter is not installed here |
| Rest of the web test suite | not run |

The two failures, both present before this work and unrelated to it:

- `tests/unit/core/test_settings.py::test_development_has_no_explicit_origins_but_a_valid_fallback`
  — reads the local `apps/api/.env`, which sets CORS origins.
- `tests/integration/modules/attendance/test_punch_after_last_working_day.py::test_self_punch_on_last_working_day_passes_and_after_it_is_rejected`
  — depends on the time of day (audit TG-01); the product behaviour is correct.

An earlier full run, before the last test fixes, had 13 failures: those two; 8 employment unit
tests whose mocks needed the new recalculation trigger patched; 1 leave race test that pinned
"a period can close with leave pending" and now asserts the `PENDING_LEAVE` outcome; and 2
calendar tests that failed because of the AC-03 / P-E reconciliation, which that work's own
session updated.

Existing tests changed in this work, beyond the two named in section 2:
`tests/unit/modules/employee/test_employment_service.py` (fixture patches the new trigger) and
`tests/integration/modules/leave/test_leave_balance_races.py::test_an_approval_arriving_during_finalisation_waits_and_then_goes_through`
(renamed; new expected outcome).

New test files:

- `tests/unit/modules/attendance/test_attendance_rules_remediation.py` — 55 engine tests,
  including boundaries (grace, grace + 1, band edges, the 120-of-240-minute conflict threshold, the
  flexible full-requirement boundary), an overnight shift, Asia/Kolkata, and a fractions /
  idempotence invariant over eight scenarios.
- `tests/integration/modules/attendance/test_attendance_rules_remediation.py` — 11 API tests, 14 cases (the cap-order test runs for four calculation orders).
- `tests/integration/modules/leave/test_period_close_pending_leave.py` — 1 API test.

Each "before" value quoted in a test's docstring is the result the audit reproduced on the
previous implementation (audit Appendix A); the tests were not separately run against the old code.

Not covered by a test: roster week-off work across midnight or in Asia/Kolkata at the API level;
D-04 across a month boundary and for the monthly cap; a lock-timeout failure inside the
dependent-day pass; mobile.

## 5. Remaining risks and limitations

0. **Wide mark bands (R-2).** The first cut of D-01 credited *every* minute a mark band covered, so a broad band (`LATE` 31-240, found in the development policies) paid a full day for 240 worked minutes. Fixed by the ceiling above. Policies with broad bands are listed by `apps/api/scripts/sql/late_mark_band_impact_report.sql`; run it before any recalculation. Within the ceiling the policy still behaves as D-01 intends (a few minutes late is a mark, not half a day).
1. **Existing policies without late / early bands** still lose half a day at grace + 1 (and a
   quarter of a day on a half-day-leave day, down from half). Nothing warns the administrator.
2. **Silent non-credit.** Presence in the leave half below the conflict threshold is not paid and
   not flagged. It is visible in the day's snapshot (`half_day_leave.leave_half_presence_minutes`).
3. **Quarter days.** `paid_day_fraction` can now be 0.25 or 0.75. The period summary reconciles
   (tested through the existing invariant), but a half-day-leave day with a half-paid worked half
   is counted under `present_days` for its remaining 0.50 in the summary buckets. Payroll's paid
   and LOP totals are exact; the bucket label is approximate.
4. **Dependent-day pass.** A correction recalculates the rest of the employee's month inside the
   same request. If any later day cannot be locked in time the whole request fails and can be
   retried; nothing is half-written. On a busy day this makes corrections slower.
5. **Days outside the period being closed** are not recalculated by close, so a later day in the
   same week but the next period waits for its own trigger or close.
6. **Roster week-off overtime uses gross minutes** and ignores the usual shift's breaks.
7. **`AUTO_CLOSE`** still does not close anything.
8. Carried over unchanged: a punch that moves another session to a new owner day; a recalculation
   request abandoned after 5 failures; `ENGINE_VERSION` alone recalculates nothing.
9. Two sessions edited the same files in one working tree. The combined result passes the suites
   listed above, but it should be reviewed as one diff before it is committed.

## 6. Migration and data impact

- **No new migration in this work.** The lock rejection is recognised by its existing fields.
  The new recalculation reasons (`BREAK_OVERRIDE_CHANGED`, `EMPLOYMENT_CREATED`,
  `EMPLOYMENT_TERMINATED`) fit the existing `reason` column (40 characters, no check constraint).
- Three migrations are pending for any environment: `20261116090000_overtime_supersede_action`,
  `20261116100000_leave_balance_shortfall`, and (added by the independent review's R-1 fix)
  `20261116110000_leave_application_half_day`. Apply them **before** deploying the code.
- **Results that change when an unlocked day is recalculated under engine 16:**

| Days affected | Change |
|---|---|
| Late or early beyond grace, inside a mark band, **up to 59 minutes missed at that end** | half-day → present (D-01). Beyond 59 minutes the hours decide: half-day stays half-day (R-2) |
| Hour band absent and a late / early band half-day | half-day → absent (pays less) |
| Half-day leave, worked half judged half-day | 0.50 LOP → 0.25 LOP |
| Half-day leave with early arrival or overstay | flag removed; early minutes no longer credited; overtime may return |
| Half-day leave on split or flexible shifts | overtime and flags change |
| Roster week-off worked | overtime appears, pending approval |
| Any week or month with a cap | minutes move to the earliest days |
| Overtime beside an orphan punch (`AUTO_CLOSE`) | auto-approved → pending |
| Half-day weekly off | late / early minutes and late count drop to zero |
| Split shift with an orphan punch | half-day → incomplete |

- Locked days and finalized periods are never recalculated. Ledger entries, overtime actions and
  approval history are only added to.

## 7. Operational plan

1. Apply the two pending migrations (`alembic upgrade head`).
2. Before recalculating, record the current state: run
   `apps/api/scripts/sql/attendance_integrity_report.sql` (includes the R-1 check, section 7) and each
   open period's `validate`; and export `(employee_id, attendance_date, attendance_status,
   paid_day_fraction, lop_fraction, ot_minutes_detected, ot_minutes_approved, engine_version)` for
   every unlocked day of those periods so the result can be diffed afterwards.
3. For each company, recalculate unlocked days of open periods **in one range per period**, with
   `POST /attendance/days/calculate-range`. Date order within an employee matters for the caps and
   is what the range task does.
4. Expect new pending overtime (roster week-offs, orphan-punch days) and new close blockers
   (`PENDING_LEAVE`). Review them before closing any period.
5. Re-run the integrity report and `validate`. Compare paid and LOP totals per employee with step 2
   and explain each difference from the table in section 6.
6. Run `apps/api/scripts/sql/late_mark_band_impact_report.sql` (read-only) first: sections 1-2 list the policy versions with broad mark bands and the unlocked days on them; section 3 lists days the uncapped credit would have paid in full; section 4 lists days a mark within the ceiling will lift from half-day to present (expect those to change). Hold any company whose broad bands HR wants to treat differently until the owner has decided R-2.
7. Edit existing attendance policies that have no late / early bands (publish a new version with a
   mark band) if the D-01 behaviour is wanted for them. This is a policy change, not a data fix.
8. Do not reopen a period whose payroll is finalized. A difference found there is corrected by a
   signed adjustment in the next run, as in `ATTENDANCE_PAYROLL_INTEGRITY_CHECK.md`.
