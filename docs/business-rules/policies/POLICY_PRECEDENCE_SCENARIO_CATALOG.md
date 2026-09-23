# Policy Precedence Scenario Catalog

**Status:** Audit document. Every scenario below is backed by either a passing test (cited) or an explicit code path (cited); none are hypothetical extrapolations beyond what the cited evidence shows.

---

## PP-001 — Approved Full-Day Leave vs. Attendance Punches

**Conditions:** Full-day leave approved for an employee; the employee also has valid IN/OUT punches covering the full shift that day.
**Policies involved:** `work_on_leave_behaviour` (ATT-POL-013), Leave approval (LEAVE-POL-027).
**Current system behaviour:** Default policy (`KEEP_LEAVE`): `attendance_status` stays `LEAVE`; `late_minutes`/`early_minutes` are zeroed; `work_on_leave_flagged=False`. If policy is set to `PRESENT_CANCEL_LEAVE_HINT`: `attendance_status=PRESENT` (punch-derived), `work_on_leave_flagged=True`; the leave application itself is **not** auto-cancelled.
**Documented intended behaviour:** Matches architecture §19.3/19.4 exactly — no discrepancy.
**Winner:** Leave (by default policy); punches only win under an explicit non-default policy setting, and even then don't touch the leave application.
**Status:** 🟢 Confirmed. Evidence: `test_full_day_leave_keep_leave_behaviour_overrides_punches`, `test_full_day_leave_present_cancel_leave_hint_flags_and_keeps_punch_status`.
**Decision required:** None.

## PP-002 — Half-Day Unpaid Leave + Full-Day Punches

**Conditions:** Employee applies half-day unpaid leave; also punches a full working day.
**Policies involved:** Half-day leave mechanics (LEAVE-POL-018), hour bands (ATT-POL-004).
**Current system behaviour:** `attendance_status=HALF_DAY`; `paid_day_fraction=0.50` (worked half), `lop_fraction=0.50` (unpaid leave half).
**Documented intended behaviour:** Matches architecture worked example.
**Winner:** Combined — the day is split proportionally, neither side unilaterally wins.
**Status:** 🟢 Confirmed. Evidence: `test_half_day_unpaid_leave_with_full_day_punches`.
**Decision required:** None.

## PP-003 — Approved Leave vs. Roster Week-Off (NOT_EXPECTED)

**Conditions:** Employee has a published roster week-off override for a date, and also has approved full-day leave covering that same date.
**Policies involved:** Roster week-off override (ATT-POL-044), leave overlay (ATT-POL-051).
**Current system behaviour:** `attendance_status=LEAVE`, but `calendar_day_type` stays whatever the roster/calendar said (untouched).
**Documented intended behaviour:** Matches architecture §19.4's stated precedence (leave ranks above calendar NOT_EXPECTED).
**Winner:** Leave (for `attendance_status`); Roster/Calendar (for `calendar_day_type`, which leave never touches).
**Status:** 🟢 Confirmed. Evidence: `test_leave_overrides_roster_week_off_not_expected`.
**Decision required:** None.

## PP-004 — Approved Leave vs. Overtime Detected the Same Day

**Conditions:** Employee has approved leave for a day, and also has punches that would independently trigger OT detection (e.g., a partial workday with excess hours before the leave was applied, or comp-off scenario).
**Policies involved:** Leave overlay, OT detection (ATT-POL-021).
**Current system behaviour:** Both facts coexist — `attendance_status=LEAVE` (or HALF_DAY) and `ot_minutes_detected` remains whatever the punch-derived pass computed; the leave overlay never clears it.
**Documented intended behaviour:** None found in either module.
**Winner:** No rule — undefined interaction.
**Status:** ⚠️ **POLICY DECISION REQUIRED** (PD-XMOD-001).
**Decision required:** Yes — should approved leave suppress/zero OT for that day, or should the two remain independent facts as today?

## PP-005 — Regularization Approved After Attendance Already Locked

**Conditions:** A regularization request is `SUBMITTED` for a date; before it's approved, the attendance period covering that date is finalized/locked.
**Policies involved:** Period lock (ATT-POL-036), regularization approval (ATT-POL-033).
**Current system behaviour:** `_ensure_date_open` blocks the approval outright — `AttendancePeriodClosedError` — regardless of `blocked_when_locked`'s configured value. The whole approval transaction rolls back; request stays `SUBMITTED`.
**Documented intended behaviour:** Consistent — WD-30: "Lock outranks every other mutating action for dates inside the locked range."
**Winner:** Period lock.
**Status:** 🟢 Confirmed. Evidence: `test_attendance_period.py` lock-enforcement tests; `service.py:3491-3496`.
**Decision required:** None for this scenario itself, but see PD-LOCK-2 (should any exception/arrears path exist).

## PP-006 — Leave Approved After Attendance Period Locked

**Conditions:** A leave application reaches its final approval stage; the target date's attendance period is already `CLOSED`.
**Policies involved:** Period lock, leave approval/projection sync (LEAVE-POL-033).
**Current system behaviour:** `LeaveProjectionService.sync()` raises `ATTENDANCE_PERIOD_CLOSED`; because the sync call happens inside the same DB transaction as the leave approval write, the **entire leave approval fails** — the application is never left partially approved.
**Documented intended behaviour:** Explicit, LD-12: "no partial approval, no partially-synced application."
**Winner:** Period lock.
**Status:** 🟢 Confirmed. Evidence: `test_sync_refused_when_period_closed`.
**Decision required:** PD-XMOD-004 (should an arrears mechanism exist).

## PP-007 — Leave Cancellation After Attendance Finalization

**Conditions:** An `APPROVED` leave application (already synced into Attendance) is cancelled by the employee; the attendance period is now `CLOSED`.
**Policies involved:** Cancellation (LEAVE-POL-024), period lock.
**Current system behaviour:** `LeaveProjectionService.cancel()` is refused the same way as sync; the entire cancellation transaction (ledger credit-back + projection cancel) rolls back — the application stays `APPROVED`, balance stays debited.
**Documented intended behaviour:** Explicit test docstring: "§21 — Leave approved after payroll lock... default refuse," applying symmetrically to cancellation.
**Winner:** Period lock.
**Status:** 🟢 Confirmed. Evidence: `test_cancel_refused_when_period_closed`.
**Decision required:** Same as PP-006 (PD-XMOD-004) — the only remedy today is a full period reopen.

## PP-008 — Two Overlapping Leave Types on the Same Day (Combination Rule)

**Conditions:** Employee has a SUBMITTED/APPROVED application of Leave Type A covering a date; attempts to submit Leave Type B for an overlapping date, where an explicit `allowed=False` combination rule exists between A and B.
**Policies involved:** Leave combination rule (LEAVE-POL-006).
**Current system behaviour:** Second submission is blocked (422 `LEAVE_APPLICATION_COMBINATION_NOT_ALLOWED`), symmetric regardless of submission order. A `REJECTED` application no longer counts as "active" for this check.
**Documented intended behaviour:** LD-16, matches exactly.
**Winner:** The combination rule (blocks the second type).
**Status:** 🟢 Confirmed. Evidence: `test_explicit_not_allowed_rule_blocks_overlapping_submission`, `test_rejected_application_no_longer_blocks`.
**Decision required:** None for cross-type; see PP-009 for the same-type gap.

## PP-009 — Two Overlapping Applications of the SAME Leave Type

**Conditions:** Employee submits two separate applications of the same leave type with overlapping dates.
**Policies involved:** None found — the combination-rule mechanism only governs *different* types.
**Current system behaviour:** Not blocked by any code path found. Balance sufficiency is checked independently for each (unless `reserve_balance_on_submission=True`, in which case pending totals are netted).
**Documented intended behaviour:** None found.
**Winner:** Undefined — both submissions can succeed.
**Status:** 🔵 Implementation gap / ⚠️ **POLICY DECISION REQUIRED** (PD-LEAVE-001).
**Decision required:** Yes.

## PP-010 — Probation Employee Attempts to Apply for Leave

**Conditions:** New hire in `Employee.status=PROBATION`; applies for a leave type whose resolved policy has `allowed_during_probation=False`.
**Policies involved:** Probation restriction (LEAVE-POL-002).
**Current system behaviour:** Blocked, 422 `LEAVE_APPLICATION_NOT_ALLOWED_DURING_PROBATION`. Confirmed end-to-end: real `EmployeeService.create_employment` → PROBATION → blocked submission → `POST /employees/{id}/confirm` → ACTIVE → identical submission then succeeds.
**Documented intended behaviour:** LD-18, matches exactly.
**Winner:** Probation restriction (while PROBATION); Employee confirmation (SHARED-POL-002) is the only unblock path.
**Status:** 🟢 Confirmed. Evidence: `test_confirm_unblocks_probation_restricted_leave_type`.
**Decision required:** None.

## PP-011 — Holiday Landing on a Weekly-Off Day

**Conditions:** A configured public holiday falls on a date that is also a weekly-off day per the assigned pattern.
**Policies involved:** Holiday (ATT-POL-039), Weekly-off pattern (ATT-POL-042), precedence rule (ATT-POL-043).
**Current system behaviour:** Day is classified `WEEKLY_OFF`, with `holiday_on_weekly_off` flag raised — the holiday does not promote or substitute the day.
**Documented intended behaviour:** WD-05, matches.
**Winner:** Weekly Off.
**Status:** 🟢 Confirmed.
**Decision required:** PD-CAL-2 (should an auto-substitute-to-next-working-day mechanism exist) remains open.

## PP-012 — Employee's Base Shift Assignment vs. Roster Override for Policy Resolution

**Conditions:** Employee's base `EmployeeAssignment.shift_id` is Shift A; a published roster reassigns them to Shift B for a specific date; a `PolicyAssignment` exists scoped to Shift B with different grace/bands than the company default.
**Policies involved:** Roster (ATT-POL-044), 8-level policy resolution (SHARED-POL-001).
**Current system behaviour:** The employee **works** Shift B's schedule that day (roster wins for scheduling), but SHIFT-scoped **policy resolution** still resolves against Shift A (the base assignment) — the Shift-B-scoped policy is never picked up for that date.
**Documented intended behaviour:** Architecture text (§16) says SHIFT scope should include roster; code does not implement this.
**Winner:** Roster (schedule) / Base assignment (policy scope) — a genuine split, not a single consistent winner.
**Status:** 🟠 **DOCUMENTATION/IMPLEMENTATION CONFLICT** (= CONF-004, PD-XMOD-002).
**Decision required:** Yes.

## PP-013 — Backdated Leave Application for a Date Whose Attendance Period Is Already Closed

**Conditions:** Employee submits a leave application today for a date 20 days ago; that date's attendance period was finalized 15 days ago; the leave policy's `max_backdated_days` is 30 (so submission itself is within window).
**Policies involved:** Backdating window (LEAVE-POL-020), period lock (indirectly, at approval time only).
**Current system behaviour:** Submission succeeds (no lock check at submission). Approval later fails once someone attempts final-stage approval, because the sync is refused for the closed period.
**Documented intended behaviour:** None found addressing this specific ordering.
**Winner:** Submission is unguarded; approval is where the lock actually bites.
**Status:** 🔵 Implementation gap (= HD-015, PD-XMOD-003).
**Decision required:** Yes.

## PP-014 — Manager-Then-HR Regularization Chain, HR Rejects After Manager Approved

**Conditions:** `MANAGER_THEN_HR` chain; manager approves (stage advances to HR); HR then rejects.
**Policies involved:** Regularization approval chain (ATT-POL-033).
**Current system behaviour:** HR's rejection is terminal — `status=REJECTED` regardless of the manager's earlier stage-approval; no correction is applied; the day's attendance is left unchanged (as if never regularized).
**Documented intended behaviour:** Matches — rejection is terminal from any stage, in both Attendance and Leave.
**Winner:** The last decision-maker in the chain (HR, since it's the final stage) — a later-stage rejection always overrides an earlier-stage approval.
**Status:** 🟢 Confirmed. Evidence: `test_manager_then_hr_two_stage_chain` (regularization); analogous leave test `test_manager_then_hr_two_stage_approval`.
**Decision required:** None.

## PP-015 — Comp-Off Credit When Day-Length Basis Is Not Configured

**Conditions:** An approved `OvertimeRecord` has `comp_off_minutes > 0`; the resolved `OvertimePolicyVersion.comp_off_day_length_minutes` is `NULL`.
**Policies involved:** Comp-off credit (LEAVE-POL-012).
**Current system behaviour:** Credit sweep skips this record entirely — no ledger row is written, no guess is made about a conversion basis.
**Documented intended behaviour:** Explicit, matches: "never guesses a conversion basis."
**Winner:** Neither — the fact is simply not converted until HR configures the basis.
**Status:** 🟢 Confirmed. Evidence: `test_credit_skipped_when_day_length_not_configured`.
**Decision required:** None (fail-closed is the confirmed design).

## PP-016 — Statutory Minimum Blocks Publishing a Compliant-Enough Policy

**Conditions:** HR tries to publish a `LeavePolicyVersion` for a `SICK`-category leave type with an annual entitlement of 12 days; two `StatutoryLeaveMinimum` rows exist for `SICK` (10 days in one state, 15 in another).
**Policies involved:** Statutory minimum enforcement (LEAVE-POL-014).
**Current system behaviour:** Publish is blocked (12 < 15, the strictest configured minimum), even though the policy might only ever be assigned to employees in the 10-day state.
**Documented intended behaviour:** Explicit rationale given: "publish-time enforcement doesn't know final state/establishment assignment, so it uses the strictest bound."
**Winner:** The strictest configured minimum, always.
**Status:** 🟢 Confirmed current behaviour; ⚠️ **POLICY DECISION REQUIRED** on whether this is the right tradeoff (PD-LEAVE-002).
**Decision required:** Yes.

## PP-017 — Reopening a Locked Attendance Period After a Policy Changed

**Conditions:** Period P was locked in January under Policy v1. In February, Policy v2 publishes with different grace minutes. In March, HR reopens Period P to fix an unrelated missing-punch issue.
**Policies involved:** Period reopen (ATT-POL-036), policy versioning (SHARED-POL-003).
**Current system behaviour:** Reopen only removes the lock — it does not recompute anything. Any day HR doesn't manually recompute stays exactly as it was calculated under Policy v1, even though the day is now technically mutable and Policy v2 is current. If HR does trigger a recompute, that day now resolves against whichever version's effective range covers it by date — if v2's `effective_from` predates the day, the day would recompute under v2, potentially changing already-reported numbers.
**Documented intended behaviour:** Explicit, WD-30: "a deliberate payroll-safety choice, so numbers already reported externally don't silently change" — but this only holds if HR doesn't manually recompute; the system provides no warning either way.
**Winner:** Whichever action HR happens to take next — no system-enforced safeguard beyond "don't recompute."
**Status:** 🔵 Implementation gap (= ND-08/CD-016, PD-EFFDATE-3).
**Decision required:** Yes — should reopening surface a warning, require explicit confirmation before recompute, or auto-recompute?
