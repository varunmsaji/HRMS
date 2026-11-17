# Attendance Cross-Module Scenario Matrix — 16 November 2026

Companion to `MASTER_ATTENDANCE_SYSTEM_AUDIT_2026-11-16.md`. Every scenario was run against the
**working tree** (engine 16, uncommitted) on databases created only for this audit. No development,
staging or production database was used.

## How to read this

**Result values**

| Result | Meaning |
|---|---|
| PASS | Ran in this audit and matched the expected result |
| FINDING | Ran in this audit; the result is wrong or incomplete. The finding id explains it |
| DECISION REQUIRED | Ran in this audit, but no approved product rule says what the result should be. The table shows what the code does; it does not call that right or wrong |
| CODE-CONFIRMED | Not run end to end; the outcome follows from code that was read |
| NOT EXECUTED | Neither run nor fully traced |

**Evidence sources**

- **Engine `<id>`:** the pure engine probe (`evaluate_day` with built inputs). 86 cases, run under
  server timezones UTC, Asia/Kolkata, America/New_York, America/Los_Angeles and Pacific/Kiritimati.
  The output was identical byte for byte in all of them.
- **API `IP<n>` / `C1-*`:** probe tests that call the HTTP API against an isolated database through
  the project's own test fixtures. They were kept outside the repository and deleted afterwards.
- **Suite `<file>::<test>`:** an existing repository test that ran and passed in this audit's
  integration run (section 14 of the master report).

**Common setup unless stated:** company in `Asia/Kolkata`; FIXED shift 09:00–18:00 with a 60-minute
unpaid lunch (480 expected minutes); grace 10 minutes at each end; standard hour bands (ABSENT under
240, HALF_DAY 240–479, PRESENT 480 and over); Monday–Friday work calendar; one active employment;
policies assigned at company scope.

## Summary

| Result | Count |
|---|---|
| PASS | 13 (3, 4, 5, 6, 17, 19, 20, 21, 24, 29, 30, 32, 33) |
| FINDING | 14 (1, 7, 8, 9, 10, 13, 16, 18, 23, 25, 26, 27, 28, 31) |
| DECISION REQUIRED | 4 (2, 11, 22, 34) |
| CODE-CONFIRMED | 1 (14) |
| NOT EXECUTED | 3 (12, 15, 35) |

A scenario that passes its main path but shows a defect on a secondary path is counted as FINDING.
Scenario 34 also shows a finding but is counted under its open decision.

---

## The 35 scenarios

### 1. Late arrival + grace + early departure — FINDING (MA-09) · DECISION REQUIRED (R-2)

- **Setup:** policy G1 has late and early "mark" bands for 1–59 minutes. Policy G2 has no late or
  early bands.
- **Punches and actual results (engine G1, G2):**

| Punches | G1 (mark bands) | G2 (no bands) |
|---|---|---|
| In 09:10 | PRESENT, 1.00 paid | PRESENT, 1.00 paid |
| In 09:11 | PRESENT, 1.00 paid, late 1 | HALF_DAY, 0.50 loss of pay |
| In 09:59, out 17:01 (both marks, 362 minutes worked) | PRESENT, 1.00 paid | HALF_DAY, 0.50 loss of pay |
| In 10:09 (late 59 after grace) | **HALF_DAY, 0.50 loss of pay** | HALF_DAY |

- **Expected:** no double penalty (met: two marks give one HALF_DAY, never ABSENT). A late
  arrival inside the "mark" band costs nothing.
- **Difference:** the band ceiling of 59 minutes is compared with lateness measured from shift
  start, including the grace, so arriving 50–59 minutes after grace ends still costs half a day
  (MA-09). In G2, one minute past grace costs half a day (the cliff, decision R-2).
- **Also:** in G1, 362 minutes worked is a full paid day, because mark   bands decide before hour
  bands. Whether this is intended is not on record (register D-01b).

### 2. Late arrival + half-day leave — DECISION REQUIRED

- **Setup:** half-day leave for the first half; the employee works the second half, arriving
  14:11 (grace + 1).
- **Actual:** with late bands (engine L8): HALF_DAY, 1.00 paid. Without late bands (engine L7):
  **HALF_DAY, 0.75 paid, 0.25 loss of pay.** The lateness cliff is applied to the worked half and
  costs a quarter day.
- **Expected:** undefined. The policy says nothing about lateness in the worked half of a half-day
  leave. Register item H-29.

### 3. Early departure + half-day leave — PASS (with bands)

- **Setup:** half-day leave for the second half; out at 12:49 (grace + 1); early bands configured.
- **Actual (engine L9):** HALF_DAY, 1.00 paid, early 1.
- **Not run:** the same without early bands. By symmetry with scenario 2 it costs a quarter day.

### 4. Half-day leave + flexible shift — PASS

- **Engine F4, F5, F6:** first-half leave plus 14:00–18:00 worked gives HALF_DAY, 1.00 paid.
  Second-half leave plus 360 worked gives 1.00 paid and 120 overtime. Leave plus 480 worked gives
  1.00 paid.
- **Note:** a flexible shift never measures early departure (engine F3, decision P-10).

### 5. Half-day leave + split shift — PASS

- **Engine S4, S5:** first-half leave plus block 2 worked gives 1.00 paid. Both blocks worked gives
  1.00 paid, with no double credit.

### 6. Half-day leave + overnight shift — PASS

- **Engine N2, N3:** 22:00–06:00 shift. First-half leave plus 02:00–06:00 worked gives 1.00 paid.
  Second-half leave plus 22:00–02:00 worked gives 1.00 paid.

### 7. Holiday + approved leave + holiday removal — FINDING (MA-27)

- **Suite:** `test_leave_calendar_reconciliation.py::test_a_holiday_removed_inside_approved_leave_debits_the_day`
  and `::test_a_holiday_added_inside_approved_leave_refunds_the_day` pass. When the balance is
  short, the shortfall is recorded as an exception, not loss of pay
  (`::test_a_shortfall_is_an_exception_not_loss_of_pay_and_hr_resolves_it_with_balance`).
- **Difference (API C1-SHORTFALL-CANCEL):** if the employee's leave is then **cancelled**, the
  shortfall stays `OPEN`. `LEAVE_BALANCE_SHORTFALL` keeps blocking period close, and the
  reconciliation operation reports nothing to apply. See MA-27.

### 8. Weekly off + approved leave + roster change — FINDING (MA-08)

- **Setup:** half-day leave approved on a working day. A roster row then makes that day a week-off.
- **Actual (API IP8):** the day shows `LEAVE` with **0.50 loss of pay**. The balance is unchanged
  at 19.50, and `LEAVE_CALENDAR_MISMATCH` blocks close until HR runs the API-only reconciliation.
- **Expected:** no loss of pay on a day off; half a day refunded, or the leave flagged without a
  pay effect.
- **Suite:** the full-day version is refunded by HR through reconciliation
  (`test_leave_reconciliation_operation.py::test_a_published_roster_day_off_after_approval_is_refunded_by_hr`).

### 9. Roster weekly off + punches + overtime — FINDING (MA-04, MA-14)

- **Suite:** `test_attendance_rules_remediation.py::test_roster_week_off_work_is_weekly_off_overtime_held_for_approval`
  passes: work on a roster week-off is weekly-off overtime held for approval.
- **Difference 1 (API IP3, engine O8):** if the work calendar or attendance policy is assigned to
  the shift, the roster week-off has no shift, nothing resolves, and the day is `CONFIG_ERROR`,
  which blocks close (MA-04).
- **Difference 2 (engine O1, O2):** the same 09:00–18:00 punches give 480 overtime minutes on a
  calendar weekly off (lunch deducted) and 540 on a roster week-off (no lunch deducted) (MA-14).

### 10. Holiday + punches + overtime — FINDING (MA-15) · DECISION REQUIRED (P-D)

- **Engine O3:** holiday, 09:00–18:00 gives PRESENT, 480 overtime, class HOLIDAY. Pass.
- **Engine O4:** a holiday on a weekly off is paid at the weekly-off rate, not the holiday rate
  (MA-15).
- **Engine O5:** the shift is not overtime-eligible, so holiday work earns nothing (decision P-D).
- **Engine O6:** holiday, IN punch only gives `NOT_EXPECTED`, 1.00 paid. The forgotten checkout
  is not flagged.

### 11. Leave + punches during leave — DECISION REQUIRED (AR-15)

- **Engine L13:** full-day leave with 09:00–20:00 punches gives LEAVE, 1.00 paid, no overtime.
  The day is flagged for HR (`WORK_ON_LEAVE_UNRESOLVED`).
- **Suite:** `test_leave_projection.py::test_full_day_leave_keep_leave_behaviour_overrides_punches`,
  `test_leave_overtime_interaction.py` (three tests) pass.
- **Undefined:** the policy field `work_on_leave_behaviour` is accepted and stored, but the engine
  ignores it (AR-15). Whether overtime is earned on a leave day is not decided.

### 12. Leave + regularization — NOT EXECUTED

- **From the code:** the leave overlay runs after punches are assembled, so a regularized punch on
  a full-day leave day produces `LEAVE` plus the work-on-leave flag, as in scenario 11.
  Regularization does not cancel leave. Not run end to end.

### 13. Leave cancellation after attendance calculation — FINDING (MA-27)

- **Attendance:** cancelling recalculates the days (suite: `test_leave_balance_races.py`,
  `test_leave_full_release_restoration.py`). Pass.
- **Difference:** an open balance shortfall for the cancelled leave is not closed (API
  C1-SHORTFALL-CANCEL). See scenario 7 and MA-27.

### 14. Leave balance shortfall + accrual — CODE-CONFIRMED (MA-11)

- `LeaveAccrualService` does not call the shortfall pass. Only a positive HR adjustment
  (`LeaveLedgerService.create_adjustment`) or a calendar edit resolves an open shortfall. The next
  monthly accrual leaves it open, and period close stays blocked.

### 15. Shift change + approved leave — NOT EXECUTED

- **From the code:** leave day counting uses the calendar and does not depend on the shift. It
  could change only when the work calendar is assigned by shift, in which case the leave goes
  through the same reconciliation as scenario 8. Not run.

### 16. Shift change + existing punches — FINDING (MA-07)

- **Setup (API IP7, IP7b, IP7c):** punches on Monday and Tuesday. A roster change moves Tuesday to
  a shift whose window claims Monday's late-night punches.
- **Actual:** only the changed date is recalculated. The neighbouring date keeps punches it no
  longer owns until something else recalculates it. In IP7c, Tuesday shows ABSENT, 0 worked, while
  Monday's later recalculation counts the punches (240 minutes).
- **Expected:** both dates whose punch ownership changes are recalculated together.

### 17. Roster change + overtime approval — PASS (mechanism)

- **Suite:** `test_overtime_recalculation.py::test_human_approved_overtime_is_capped_when_the_detection_shrinks`,
  `::test_human_approved_overtime_is_reopened_when_the_detection_grows`,
  `::test_rejected_overtime_stays_rejected_until_new_overtime_appears`,
  `::test_repeated_recalculation_changes_nothing` pass.
- **Not run:** a roster edit as the trigger. The supersede path is the same whatever caused the
  recalculation, so the mechanism is covered. The neighbour-date gap (MA-07) still applies.

### 18. Punch ownership transfer between dates — FINDING (MA-07, MA-29)

- **Roster or shift change:** see scenario 16.
- **Regularization:** a request may add punches up to one day either side of its date, but
  approval recalculates only the request's own date (`service.py`, approve, around line 6612).
  The other date keeps the old ownership until the next sweep or close (MA-29, code-confirmed).

### 19. Punch correction + weekly cap — PASS

- **Suite:** `test_attendance_rules_remediation.py::test_correcting_an_earlier_day_recalculates_the_later_days_of_the_week`,
  `::test_weekly_cap_goes_to_the_earliest_days_whatever_order_they_are_calculated_in`,
  `::test_a_locked_later_day_is_not_touched_by_an_earlier_correction`;
  `test_overtime_cap_reallocation.py` (R-5 partial approval, rejection, full approval).
- **Gap:** budget freed when overtime is withdrawn at period lock is not handed on (MA-32).

### 20. Punch correction + monthly cap — PASS

- **Suite:** `test_overtime_cap_reallocation.py::test_r4_a_correction_reallocates_a_week_that_spans_two_months_and_the_next_month`,
  `::test_r4_a_weekly_cap_alone_still_reaches_the_days_of_the_week_in_the_next_month`.

### 21. Overtime rejection + period reopening — PASS

- **Suite:** `test_attendance_rules_remediation.py::test_overtime_rejected_at_lock_returns_when_the_reopened_day_is_corrected`,
  `::test_a_human_rejection_is_still_not_reversed_by_a_recalculation`;
  `test_attendance_period.py::test_reopen_unlocks_days_and_refinalize_regenerates_summary`.

### 22. Overtime approval + later policy publication — DECISION REQUIRED

- **Suite:** `test_calendar_recalc_triggers.py::test_publishing_an_overtime_policy_version_queues_only_its_assignees`
  passes: only that policy's assignees are queued.
- **Undefined:** on recalculation, a human-approved record keeps its approved minutes, but its
  multiplier and policy version are taken from the new version (`_resolve_ot_decision`, outcome
  `POLICY_VERSION_CHANGED`). Its comp-off choice is **not** re-taken: `comp_off_minutes` stays
  non-zero if it was non-zero before, even when the new version no longer gives comp-off instead
  of pay (`service.py` around line 5372). Whether an approval stands for the minutes or for the price is not
  decided (register O-15).

### 23. Break override + overtime recalculation — FINDING (MA-30)

- **Suite:** `test_attendance_rules_remediation.py::test_a_backdated_break_override_recalculates_the_days_it_covers`
  passes.
- **Difference:** **revoking** an override queues recalculation from today
  (`break_override_service.revoke`). The revocation applies to every date
  (`list_in_force` drops revoked overrides), so past open days keep results computed with the
  override until the sweep or close (MA-30, code-confirmed).

### 24. Employment termination + overnight shift — PASS (main path) · NOT EXECUTED (overnight)

- **Suite:** `test_attendance_rules_remediation.py::test_a_backdated_termination_recalculates_the_days_after_the_last_working_day`;
  `test_leave_employment_validity.py` termination tests.
- **Not run:** an overnight shift starting on the last working day. By the ownership code the
  whole shift belongs to its start date, so it would count. Not executed.

### 25. Rejoining + historical attendance — PASS · FINDING (MA-21)

- **Suite:** `test_regularization_employment_period.py::test_regularization_respects_employment_gap_and_rehire`,
  `test_leave_employment_validity.py::test_balance_survives_termination_and_rehire_and_the_gap_accrues_nothing`,
  `test_comp_off_employee_lifecycle.py::test_comp_off_credit_survives_termination_and_rehire_and_expires_once`.
- **Difference:** a new employment or termination dated inside a closed period is accepted; locked
  days keep their old employment state (MA-21, code-confirmed).

### 26. ON_DUTY + leave overlap — PASS · FINDING (MA-31)

- **Engine L16, L17:** ON_DUTY plus half-day unpaid leave gives ON_DUTY, 0.50 paid, 0.50 loss of
  pay. ON_DUTY plus full paid leave gives LEAVE, 1.00 paid. Leave takes precedence.
- **Difference (API C1-DOUBLE-ON-DUTY):** a second ON_DUTY request for the same date is accepted.
  Approving it returns HTTP 500 and rolls back, leaving the first approval in place (MA-31).

### 27. Comp-off credit + overtime correction — FINDING (MA-03)

- **API IP10:** 180 minutes of auto-approved overtime credits 0.38 day of comp-off. A correction
  removes the overtime: the record is deleted and the credit stays at 0.38. A new correction gives
  30 minutes of overtime, which is credited again (0.06). The balance is 0.44 for 30 minutes of
  overtime.
- **Expected:** credit follows the current approved overtime, or is held until the period closes.

### 28. Holiday removal + leave shortfall — PASS · FINDING (MA-27, MA-11)

- **Suite:** `test_leave_calendar_reconciliation.py::test_a_shortfall_is_an_exception_not_loss_of_pay_and_hr_resolves_it_with_balance`,
  `::test_a_shortfall_closes_itself_when_the_holiday_comes_back`,
  `::test_a_negative_balance_is_used_only_where_the_policy_allows_it`.
- **Difference:** cancellation does not close the shortfall (MA-27); accrual does not resolve it
  (MA-11).

### 29. Calendar change + closed attendance period — PASS

- **Suite:** `test_leave_calendar_reconciliation.py::test_leave_in_a_closed_attendance_period_is_never_changed`;
  `test_calendar_recalc_triggers.py`. Locked days are not recalculated. Leave in the closed period
  is not changed.
- **Related:** deactivating a holiday calendar does not stop its holidays from applying (MA-28,
  API C1-INACTIVE-HOLIDAY-CAL).

### 30. Two simultaneous reconciliation requests — PASS

- **Suite:** `test_leave_reconciliation_operation.py::test_two_hr_users_applying_the_same_preview_change_the_leave_once`.

### 31. Two simultaneous attendance recalculations — PASS · FINDING (MA-12, MA-33)

- **Suite:** `test_attendance_rules_remediation.py::test_concurrent_calculation_of_days_sharing_a_cap_ends_in_the_same_allocation`.
- **Difference:** the queue does not deduplicate. API IP4 queued five overlapping requests for one
  employee (MA-12). Each recalculation of a day with pending overtime raises the record version
  (MA-33).

### 32. Earlier-date correction + week crossing a month boundary — PASS

- **Suite:** `test_overtime_cap_reallocation.py::test_r4_a_correction_reallocates_a_week_that_spans_two_months_and_the_next_month`.
- **Not tested:** a week crossing a year boundary.

### 33. Multiple policy versions with overlapping effective dates — PASS

- Overlap is refused by database exclusion constraints and the publish API.
- **Suite:** `test_attendance_policy.py::test_publish_second_version_insert_new_close_previous`,
  `::test_published_version_immutable`; the same for leave policy.

### 34. Regularization approval after attendance period validation — DECISION REQUIRED · FINDING (MA-29)

- `validate` reads stored rows; `finalize` recalculates every open day before validating, so an
  approval made after `validate` is still counted at close. Approval on a closed date is refused.
- **Undefined:** whether a `READY` validation result should become invalid when anything changes
  afterwards. Today it does not (register V-06).
- **Difference:** the neighbour-date gap of MA-29 applies.

### 35. Roster publication after punches and overtime approval — NOT EXECUTED

- **Components covered:** neighbour-date ownership (scenario 16) and approved-overtime supersede
  (scenario 17). The combined sequence was not run.

---

## Scenarios this audit added

| ID | Scenario | Result | Evidence |
|---|---|---|---|
| X1 | Hour bands not starting at zero, 30 minutes worked | FINDING (MA-01): PRESENT, 1.00 paid | API IP1, engine H1, H2 |
| X2 | No-show under `TREAT_PRESENT`, then lock | FINDING (MA-02): INCOMPLETE locked with 1.00 paid | API IP2 |
| X3 | Checkout after close, owned by a locked day | FINDING (MA-06): counted nowhere, no blocker | API IP5 |
| X4 | Future date calculated | FINDING (MA-17): INCOMPLETE row written | API IP6 |
| X5 | Part-time 4-hour shift with 8-hour bands | FINDING (MA-05): HALF_DAY, 0.50 loss of pay | Engine O20 |
| X6 | Work wholly before a FIXED shift | FINDING (MA-20): ABSENT, 0 worked | API IP7c |
| X7 | Holiday on a deactivated holiday calendar inside a leave range | FINDING (MA-28): still excluded from leave | API C1-INACTIVE-HOLIDAY-CAL |
| X8 | Server timezone UTC, IST, New York, Los Angeles, UTC+14 | PASS: identical engine output; unit suite identical under IST and UTC+14 | Engine digest; unit runs |
| X9 | Day shift, checkout 23:59 / 00:00 / 00:01 / 05:29 / 05:30 / 06:01 next day | PASS: owned by the shift day up to the +12-hour limit, then split | Engine T1–T4b |
| X10 | Night shift, IN 23:59 / OUT 00:01 | PASS: one 2-minute session on the start date | Engine T6 |
| X11 | No shift, IN day 1, OUT day 2 | FINDING (MA-16): one 33-hour session | Engine T8 |
