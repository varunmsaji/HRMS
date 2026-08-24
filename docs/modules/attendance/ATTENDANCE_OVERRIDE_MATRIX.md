# Attendance Override Matrix

Companion to `ATTENDANCE_RULE_COMPLETENESS_AUDIT.md`. Covers spec Section 7. "Configurable?"
means whether the precedence itself (not the underlying values) can be changed by configuration.
"Current Status" cites the code that actually implements the precedence — every row was traced to
a specific line, not inferred from the architecture narrative alone.

| Rule A | Rule B | Winner | Why | Configurable? | Current Status |
|---|---|---|---|---|---|
| Employee-scope policy | Company-scope policy | Employee | 8-level scope walk `EMPLOYEE > SHIFT > DESIGNATION > GRADE > DEPARTMENT > BRANCH > LEGAL_ENTITY > COMPANY`; first matching `PolicyAssignment` wins | No — the order itself is hard-coded (`calendar_resolution.py:48-57`) | CURRENTLY WORKING |
| Employee-scope policy | Shift-scope policy | Employee | Same 8-level walk, EMPLOYEE ranks above SHIFT | No | CURRENTLY WORKING |
| Shift-scope policy | Designation-scope policy | Shift | Same walk | No | CURRENTLY WORKING |
| Designation-scope policy | Grade-scope policy | Designation | Same walk | No | CURRENTLY WORKING |
| Grade-scope policy | Department-scope policy | Grade | Same walk | No | CURRENTLY WORKING |
| Department-scope policy | Branch-scope policy | Department | Same walk | No | CURRENTLY WORKING |
| Branch-scope policy | Legal-entity-scope policy | Branch | Same walk | No | CURRENTLY WORKING |
| Legal-entity-scope policy | Company-scope policy | Legal entity | Same walk (last tier before company) | No | CURRENTLY WORKING |
| Roster shift | Assignment shift | Roster (if `PUBLISHED`) | `service.py:2764-2768` — `shift_id = roster_entry.shift_id if roster_entry is not None else assignment.shift_id` | No — roster always wins when a `PUBLISHED` row exists for the date; no config flag to prefer assignment instead | CURRENTLY WORKING (W5) |
| Roster shift | Shift policy (resolved through the 8-level walk) | N/A — different axes | Roster determines *which shift ID* is used; the 8-level walk determines *which attendance/OT/regularization policy* applies. These are orthogonal, not competing, resolutions — a roster-assigned shift's own `is_ot_eligible`/`operates_on_holiday` flags still feed into whichever policy wins the separate policy-precedence walk | N/A | Not a real conflict — see note below |
| Calendar exception (SHUTDOWN/SPECIAL_WORKING/SUBSTITUTE_HOLIDAY) | Holiday | Exception | `calendar_resolution.py:138-163` — exception always wins first, before the holiday union is even consulted | No | CURRENTLY WORKING |
| Calendar exception (CANCEL_HOLIDAY) | Weekly Off | Falls through to weekly-off check | `calendar_resolution.py:164-167` — CANCEL_HOLIDAY removes the holiday match for that date only, then the ordinary weekly-off/working check runs | No | CURRENTLY WORKING |
| Holiday | Weekly Off | Weekly Off (holiday-on-weekly-off case) | `calendar_resolution.py:208-218` — a hard holiday landing on a weekly-off day stays `WEEKLY_OFF`, flagged `holiday_on_weekly_off=True`; **no auto-substitute** | **No — open product decision PD-CAL-2**, explicitly flagged in the code comment as having no configuration to change it | OPEN PRODUCT DECISION |
| Special Working Day | Holiday | Special Working Day | It's an exception type (`SPECIAL_WORKING`) that, per the precedence table above, is checked before the holiday union | No | CURRENTLY WORKING |
| Shutdown | Working Day | Shutdown | Exception wins over the default WORKING classification the same way | No | CURRENTLY WORKING |
| Cancelled Holiday | Weekly Off | Weekly Off (if the date also matches a weekly-off rule) | CANCEL_HOLIDAY only removes the holiday; if the date independently matches a weekly-off rule, it still resolves WEEKLY_OFF (`calendar_resolution.py:177-180`) | No | CURRENTLY WORKING |
| Substitute Holiday | Working Day | Substitute Holiday (becomes HOLIDAY) | `calendar_resolution.py:157-163` — an explicit `SUBSTITUTE_HOLIDAY` exception row always produces `day_type=HOLIDAY` | Yes, in the sense that HR must manually create the exception row (no automatic Sunday-holiday → Monday-substitute rule) | CURRENTLY WORKING, manually-triggered only |
| Leave (full-day) | Absence (ABSENT/INCOMPLETE) | Leave | `calculation.py:849-864` — full-day leave (`total_fraction >= 1.00`) replaces `attendance_status` with `LEAVE` and zeroes late/early regardless of what the punch-derived outcome would otherwise have been (unless `PRESENT_CANCEL_LEAVE_HINT`) | Yes — `work_on_leave_behaviour` policy field genuinely gates this (KEEP_LEAVE vs PRESENT_CANCEL_LEAVE_HINT) | CURRENTLY WORKING |
| Leave (full-day) | NOT_EXPECTED (calendar) | Leave | Explicitly documented in `calculation.py:812-817` — full-day leave ranks above calendar `NOT_EXPECTED`, so it can apply even on a holiday/weekly-off date Leave has (redundantly) projected as covered; `calendar_day_type` itself is untouched | No | CURRENTLY WORKING |
| Leave (full-day) | Holiday (calendar_day_type) | Leave overrides `attendance_status` only; `calendar_day_type` still reports HOLIDAY | Same mechanism as above — the overlay never touches `calendar_day_type`, only status/fractions | No | CURRENTLY WORKING (deliberate split: two different fields answer two different questions) |
| Leave (full-day) | Punch (presence) | Leave (KEEP_LEAVE, default) or Punch (PRESENT_CANCEL_LEAVE_HINT, non-default) | `calculation.py:846-864` | Yes | CURRENTLY WORKING |
| Leave | Overtime | No explicit precedence found | A day with `attendance_status=LEAVE` (full-day) never reaches `detect_overtime` in the fixed/flex/split paths because `_evaluate_fixed_or_flex`/`_evaluate_split` compute OT from the *punch-derived* `worked_minutes` **before** the leave overlay is applied (`evaluate_day` calls `_apply_leave_overlay` on the already-built `result`, which already carries `ot_minutes_detected`) — meaning OT detected from any punches on a full-day-leave date is **not cleared by the leave overlay** and can still show up in `ot_minutes_detected`/`ot_pending`, even though `attendance_status` was overwritten to LEAVE | No — this is unflagged in code as an explicit rule either way | **NO EXPLICIT PRECEDENCE HANDLING — flag for client decision.** (`_apply_leave_overlay`'s `replace()` calls never zero `ot_minutes_detected`/`ot_pending`/`ot_classification`, only late/early/status/fractions — see `calculation.py:849-864`.) |
| Regularization (approved) | Punch | Regularization becomes new punches, applied then recomputed | `service.py:3931-4057 _apply_correction` — approved correction inserts `source='REGULARIZATION'` punches, then calls `calculate()` | No | CURRENTLY WORKING |
| Regularization (approved) | Attendance result | Regularization wins (recompute replaces the day) | Same mechanism — the recompute after applying the correction fully replaces derived fields (WD-10) | No | CURRENTLY WORKING |
| Overtime (decision) | Attendance status | No direct interaction — orthogonal fields | OT approve/reject writes `AttendanceDay.ot_minutes_approved`/`comp_off_minutes_earned` directly (`service.py:4359-4366`), entirely outside `calculate()`; `attendance_status` itself is never touched by OT approval/rejection | N/A | CURRENTLY WORKING as designed — but see Contradictions doc for whether this split is documented consistently |
| Period Lock | Punch | Lock wins (blocks) | `service.py:2343 _ensure_date_open` | No | CURRENTLY WORKING |
| Period Lock | Regularization (submit) | Lock wins (blocks) | `service.py:3415` | No — and note `RegularizationPolicyVersion.blocked_when_locked` cannot override this (see Configuration Audit L10) | CURRENTLY WORKING |
| Period Lock | Overtime (approve/reject) | Lock wins (blocks) | `service.py:4295,4423` | No | CURRENTLY WORKING |
| Period Lock | Roster (create/update/publish/delete) | Lock wins (blocks) | `service.py:2027,2083,2150,2208` | No | CURRENTLY WORKING |
| Period Lock | Leave (sync/cancel) | Lock wins (blocks) | `service.py:5158,5288` | No | CURRENTLY WORKING |
| Period Lock | Recompute (`calculate()`) | Lock wins (blocks) | `service.py:2499` + row-level `is_locked` re-check at `2506-2507,2572-2575` | No | CURRENTLY WORKING (defence-in-depth: period-level and row-level checks both exist) |
| Draft Roster | Published Roster | Published (draft is invisible to calculation) | `service.py:2750-2752` — `get_published_for_date` only ever considers `status='PUBLISHED'` rows | No | CURRENTLY WORKING — confirmed by `test_draft_roster_does_not_affect_calculation` |
| Roster week-off override | Calendar (WORKING day) | Roster override wins | `calculation.py:742-746,767-769` — forces `NOT_EXPECTED` even on a calendar `WORKING` day (rotating-crew case) | Yes (per-employee-date, via roster) | CURRENTLY WORKING |
| Roster holiday-working override | Calendar (HOLIDAY/WEEKLY_OFF not-expected default) | Roster override wins | `calculation.py:772-774` — ORs with the shift's own `operates_on_holiday`/`operates_on_weekly_off` flags | Yes | CURRENTLY WORKING |
| Shift `operates_on_holiday` | Calendar HOLIDAY (not-expected default) | Shift flag wins if set | `calculation.py:770-772` | Yes | CURRENTLY WORKING |

## Combinations with NO explicit precedence handling in code

Flagged deliberately — these are gaps in the sense that no line of code, comment, or test decides
the outcome; behaviour is whatever falls out incidentally from execution order, which may not be
the intended business rule.

1. **Leave vs Overtime** (detailed above) — a full-day leave overlay does not clear
   `ot_minutes_detected`/`ot_pending` computed from punches that happened to exist on that date.
   No test in `test_leave_projection.py` or `test_overtime_record.py` exercises "employee is on
   approved full-day leave but also has punches that would trigger OT" — `test_full_day_leave_
   present_cancel_hint_flags_and_keeps_punch_status` gets closest but does not assert on OT fields.
   **Needs a client decision**: should OT ever be creditable/payable on a day the leave ledger will
   treat as a full paid/unpaid leave day?

2. **Regularization vs Overtime, when a regularization changes punches that affect a day with an
   already-`PENDING`/terminal `OvertimeRecord`** — `_apply_correction` calls `calculate()`, and
   `_resolve_ot_decision` explicitly freezes a terminal (`APPROVED`/`AUTO_APPROVED`/`REJECTED`)
   `OvertimeRecord` (`service.py:3089-3097`) even though the underlying punches (and therefore the
   "true" OT minutes) just changed via the regularization. This is *documented* as deliberate
   (WD-29 decision 2) but is nonetheless a case where two W6/W7 mechanisms can leave the OT record
   permanently out of sync with the corrected attendance day, with no reconciliation path other
   than a manual period reopen. Not silently undiscovered, but genuinely unresolved.

3. **Roster (published, mid-period change) vs an already-`PENDING` OvertimeRecord** — no code path
   was found that re-evaluates a pending OT record's `day_class`/eligibility when the underlying
   roster shift changes after the OT was first detected but before it's approved. The next
   `calculate()` call (e.g. triggered by any other correction) would refresh `AttendanceDay.
   ot_minutes_detected`/`ot_classification` "informationally" per the `_resolve_ot_decision` docstring, but the
   `OvertimeRecord` row itself is only replaced while `PENDING` (`service.py:3212-3219`) — so this
   specific combination does resolve, just not through an explicitly named "roster-change-affects-
   pending-OT" rule; it falls out of the general PENDING-replace mechanism.

4. **Two overlapping `PolicyAssignment` rows at the same scope tier** (e.g. two EMPLOYEE-scope
   attendance-policy assignments for the same employee with overlapping effective dates) — not
   re-examined in this pass (belongs to the organisation module's `PolicyAssignment` table, which
   predates W1); flagged here only because `resolution.py`/`calendar_resolution.py` assume exactly
   one match per scope tier and neither module was seen to defend against a duplicate.

5. **Excess break vs Overtime** — `excess_break_minutes` is computed and stored but (per the
   Configuration Audit) `excess_break_behaviour` has no runtime effect; there is consequently no
   rule anywhere for whether an excess unpaid break should reduce `worked_minutes` further than it
   already does, or whether excess time should itself ever be OT-eligible. No test, no code branch,
   no documented decision either way.

---

*All rows verified 2026-08-21 against the current working tree. See
`ATTENDANCE_MASTER_RULE_MATRIX.md` for the underlying per-rule evidence and
`ATTENDANCE_DOCUMENTATION_GAPS.md` for where this matrix disagrees with existing documentation.*
