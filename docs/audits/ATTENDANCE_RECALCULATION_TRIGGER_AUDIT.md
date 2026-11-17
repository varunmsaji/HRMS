# Attendance Recalculation Trigger Audit — 16 November 2026

**Written for:** architect and engineering team. Part of
`MASTER_ATTENDANCE_SYSTEM_AUDIT_2026-11-16.md`. Describes the uncommitted working tree (engine 16).
It replaces nothing: `ATTENDANCE_RECALCULATION_TRIGGER_MATRIX.md` (the earlier remediation's
matrix) was checked against the code and is accurate for the rows it has; this document adds the
mechanics, the missing rows and the failure paths.

---

## 1. The three ways a day gets recalculated

| Path | Used by | Transaction | If it fails |
|---|---|---|---|
| **In-request, required** | leave approval and cancellation (`LeaveProjectionService.sync` / `cancel`), regularization approval, reconciliation, period finalize, HR overtime decision (cap re-allocation) | the caller's transaction; the change and the recalculation commit or roll back together | the whole request fails; nothing is half-written |
| **In-request, best effort** | punch creation (`PunchService._try_immediate_calculate`) | a savepoint inside the punch transaction; calculates the punch's local date and its owning date, oldest first | the punch is kept; a request `IMMEDIATE_CALCULATION_FAILED` is queued for the dates tried |
| **Queued** | every configuration change (`recalc.request_recalc`) | the request row is inserted in the caller's transaction; a Celery task is kicked after commit; Beat re-kicks every 5 minutes | the request stays pending and is retried, up to 5 attempts, then closed with an error |

Plus two sweeps: the daily calculation at 09:30 IST (today and two days back, every active
employee) and `finalize` (every unlocked day of the period, oldest first per employee).

### What the queue processor does (`recalc.process_company_requests`)

1. Reads up to 50 pending requests for the company, oldest first.
2. For each, selects **existing, unlocked** `attendance_day` rows in the date range, narrowed by
   `employee_id` and/or by `shift_id` (the shift the row was calculated against).
3. Calculates each employee's dates in date order, one transaction per employee-date
   (`tasks._calculate_employee_dates`). Locked days and closed periods are counted as skipped.
4. Marks the request processed when every day succeeded or was skipped; otherwise increments
   `attempts`.

Each `calculate` may cascade to later days of the month and week inside its own transaction when
the day's late flag, excess-break flag or cap contribution changed.

---

## 2. Mutation-to-recalculation matrix

Reason codes are the values written to `attendance_recalc_request.reason`.

| # | Mutation | Method | Path | Reason / call | Employees | Dates | Leave reconciled | Verdict |
|---|---|---|---|---|---|---|---|---|
| 1 | Shift version published | `OrganisationService.publish_shift_version` | queued | `SHIFT_VERSION_PUBLISHED` | rows on that shift | `effective_from` → today | no | Correct, with gaps A and B |
| 2 | Shift created / draft edited | — | none | — | — | — | — | Correct (a draft changes nothing) |
| 3 | Shift deactivated | — | none | — | — | — | — | Plausible risk: the engine never reads `Shift.is_active`, so nothing would change if it did recalculate (code reading, not reproduced) |
| 4 | Assignment created (shift, branch, department, designation, grade) | `EmployeeAssignmentService.create_assignment` | queued | `ASSIGNMENT_CREATED` | the employee | `effective_from` → end of range | no | Correct, with gap A |
| 5 | Assignment deleted / edited | no such operation (assignments are closed by a new one or by termination) | — | — | — | — | — | — |
| 6 | Roster row created / edited / published / deleted | `ShiftRosterService._queue_recalc` | queued | `ROSTER_CHANGED` | the employee | the roster date only | no | **Incomplete**: gap A (reproduced, IP7c) |
| 7 | Shift swap approved | `schedule_service` | queued | `SWAP_APPROVED` | both employees | both dates | no | Correct, with gap A |
| 8 | Holiday created | `create_holiday` | queued | `HOLIDAY_CHANGED` | calendars linking the holiday calendar | the date | **yes, same transaction** | Correct |
| 9 | Holiday edited / deactivated | `update_holiday` | queued | `HOLIDAY_CHANGED` | same | old and new date | yes | Correct |
| 10 | Holiday calendar validity / active | `update_holiday_calendar` | queued | `HOLIDAY_CALENDAR_CHANGED` | linked calendars | oldest unlocked day → today | no (blocker) | Validity: correct; wide (section 5). Active flag: queued but has no effect, because the resolver ignores it (MA-28, reproduced) |
| 11 | Weekly-off pattern rules / active | `update_weekly_off_pattern` | queued | `WEEKLY_OFF_PATTERN_CHANGED` | calendars using it and `WEEKLY_OFF` assignments | oldest unlocked day → today | no (blocker) | Correct; wide |
| 12 | Work calendar pattern (including set to none), holiday links, restricted flag, active | `update_work_calendar` | queued | `WORK_CALENDAR_CHANGED` | its assignments | oldest unlocked day → today | no (blocker) | Correct; wide |
| 13 | Calendar exception created / edited | `create_calendar_exception`, `update_calendar_exception` | queued | `CALENDAR_EXCEPTION_CHANGED` | the calendar's assignments | the date(s) | yes | Correct |
| 14 | Policy assignment created / changed / ended | `_queue_policy_recalc` | queued | `POLICY_ASSIGNMENT_CHANGED` | the scope | assignment start → today | no | Correct; duplicates (section 4) |
| 15 | Attendance policy version published (grace, bands, limits) | `publish_attendance_policy_version` | queued | `POLICY_VERSION_PUBLISHED` | the policy's assignments | `effective_from` → today | — | Correct |
| 16 | Overtime policy version published | `publish_overtime_policy_version` | queued | `POLICY_VERSION_PUBLISHED` | the policy's assignments | `effective_from` → today | — | Correct |
| 17 | Leave / regularization policy version published | — | none | — | — | — | — | Correct (no effect on stored results) |
| 18a | Break override created | `break_override_service.create` | queued | `BREAK_OVERRIDE_CHANGED` | the employee | override start → today | — | Correct |
| 18b | Break override revoked | `break_override_service.revoke` | queued | `BREAK_OVERRIDE_CHANGED` | the employee | **`max(effective_from, today)` → today** | — | **Incomplete** (MA-30): `list_in_force` drops a revoked override for every date, so open past days keep the old result |
| 19 | Employment created | `create_employment` | queued | `EMPLOYMENT_CREATED` | the employee | joining date → today | — | Correct |
| 20 | Employment terminated | `terminate_employment` | queued | `EMPLOYMENT_TERMINATED` | the employee | last working day + 1 → today | — | Correct (reproduced, IP4) |
| 21 | Employment edited: pay basis | `update_employment` | **none** | — | — | — | — | **Missing** (MA-10; IP5) |
| 22 | Employment edited: legal entity | `update_employment` | **none** | — | — | — | — | **Missing**, and unguarded against closed periods (MA-10) |
| 23 | Punch created | `PunchService` | best effort, then queued | direct; `IMMEDIATE_CALCULATION_FAILED` | the employee | local date and owning date | — | Correct, with gaps A and C |
| 24 | Punch corrected | through regularization (a superseding punch) | required | direct | the employee | the request's attendance date | — | **Incomplete** (MA-29, code-confirmed): requested punches may fall a day either side (`submit`, around line 5945); only the request's date is recalculated |
| 25 | Punch deleted | no such operation in the product | — | — | — | — | — | — |
| 26 | Orphan punch dismissed | `dismiss_orphan_punch` | none | — | — | — | — | Correct (it was owned by no day) |
| 27 | Regularization approved | `_apply_correction`, `_apply_break_correction` | required | direct | the employee | the attendance date | — | Correct for its date; see row 24 |
| 27b | Break event corrected (break module) | `BreakService._recalculate` | best effort | direct; **on failure only a warning log** | the employee | the date | — | **Weaker than punches** (C-17): no durable request; repaired only by the 3-day sweep or close |
| 28 | ON_DUTY approved / cancelled | regularization service | required | direct | the employee | the date | — | Correct |
| 29 | Leave approved | `_apply_approval` → `sync` | required | direct | the employee | each leave day | ledger debit | Correct |
| 30 | Leave cancelled | `_reverse_approval` → `cancel` | required | direct | the employee | each leave day | refund | Correct for days and ledger; **an open shortfall is not closed** (MA-27, reproduced) |
| 31 | Leave edited | no such operation (cancel and re-apply) | — | — | — | — | — | — |
| 32 | Leave accrual / carry-forward / comp-off credit | Celery sweeps | none | — | — | — | open shortfalls not re-checked | **Missing** for shortfalls (MA-11) |
| 33 | HR balance adjustment (credit) | `create_adjustment` | required | reconcile for open shortfalls | the employee | shortfall dates | yes | Correct |
| 34 | Leave reconciliation apply | `apply_reviewed` | required | direct | affected employees | affected leave days | yes | Correct |
| 35 | Overtime approved in full | `OvertimeRecordService.approve` | none needed | day row updated directly | — | — | — | Correct |
| 36 | Overtime approved partly / rejected | `approve`, `reject` | required | `reallocate_caps_after_decision` | the employee | later days of week / month, when a cap exists | — | Correct |
| 37 | Comp-off credited / expired | Celery sweeps | none | — | — | — | — | Correct for attendance; credit does not follow corrections (MA-03) |
| 38 | Period finalized | `finalize` | required | `recalculate_days_for_close` | owned employees | every unlocked day of the period | blockers | Correct, except: overtime withdrawn by `_apply_incomplete_lock_resolution` runs after the recalculation and does not re-allocate cap budget to later days (MA-32, code-confirmed) |
| 39 | Period reopened | `reopen` | none | unlock only | — | — | — | Correct by design |
| 40 | Engine version raised | — | none | — | — | — | — | By design (AR-17) |

---

## 3. Missing or incomplete triggers

### Gap A — neighbouring days after a schedule change (MA-07, reproduced)

Ownership compares a date with two days on each side, so changing the shift of date D can change
which punches D−1 and D+1 own. Rows 1, 4, 6 and 7 queue only D (or D onward). Probe IP7c: after a
roster change on Monday, Monday's snapshot listed four punches including Tuesday's two; Tuesday's
row was not recalculated and still listed the same two.

It is repaired by: any later calculation of the neighbour (a punch, the sweep within three days,
period close). It is not repaired when the neighbour is already locked in an earlier period.

### Gap B — shift-scoped requests match only rows already on that shift

`_affected_days` filters `attendance_day.shift_id == request.shift_id`. A row calculated with no
shift (a roster week-off, or a day when the shift had no published version) is not selected when a
version is published for that shift, or when a shift-scoped policy changes. Code-confirmed, not
reproduced.

### Gap C — a punch that re-pairs another day's session

A new punch recalculates its own local date and its owner. If it changes how an older lone punch
pairs, and that older punch moves to or from a third date, the third date is not recalculated.
Open since the shift audit; unchanged.

### Missing: employment edits (MA-10), accrual against shortfalls (MA-11), comp-off against overtime (MA-03)

See the master report.

### Silent: a punch owned by a locked day (MA-06, reproduced)

The immediate calculation fails, a request is queued, the processor skips the locked day and
closes the request as done. Nothing reports the punch.

---

## 4. Duplicate and unnecessary triggers

- **No coalescing.** `request_recalc` inserts unconditionally. Probe IP4: creating one employee
  with an employment, a shift version, an assignment and two policy assignments queued five
  requests, four of them from 1 January to today. Processing recalculated the same three rows five
  times. A bulk import or a calendar setup session multiplies this.
- **Company-wide supersets.** A change scoped wider than one employee or one shift queues the whole
  company (`_targets_for_assignments`). This is safe and can be very large (section 5).
- **Unconditional calendar ranges.** A pattern or work-calendar edit queues from the oldest
  unlocked day to today even when the edit changes nothing in the past (for example a future-dated
  cycle start).
- **Policy publish with unchanged values** queues a full range.
- **Cascade inside a queued run.** The processor calls `calculate` with the cascade on. When a day's
  late flag or cap contribution changes, the rest of the month is recalculated in that
  transaction, and then again as the processor reaches each of those days.

None of these produces a wrong result: recalculation is idempotent (identical inputs give an
identical row; automatic overtime approvals with identical figures are left untouched). The cost is
time, lock duration and audit-log volume (one `ATTENDANCE_DAY_RECOMPUTED` audit row per run).

One exception to "untouched": a **`PENDING`** overtime record is rewritten on every recalculation of
its day, even with identical figures (`OvertimeRecordRepository.replace_for_day` raises `version`;
the service adds a `DETECTED` action and an `OVERTIME_DETECTED` audit entry each time). An approver
who opened the record before the 09:30 sweep, a queued run or a punch gets a stale-version error on
approve (MA-33, code-confirmed).

---

## 5. Date ranges and populations

| Check | Result |
|---|---|
| `date_to` is clamped to the company's business today | Correct. Future rows (MA-17) are never selected |
| Future-dated configuration (`date_from` > today) | No-op, correct: no row exists to repair |
| "Oldest unlocked day" for calendar-wide edits | Company-wide minimum. One old unlocked row (for example a never-closed month a year back) makes every calendar edit recalculate the whole span |
| Employee population for holiday changes | Calendars linking the holiday calendar → their assignments; company-wide when any assignment is wider than employee or shift. A superset, never a subset (verified by reading) |
| Policy publish population | The policy's own active assignments overlapping `effective_from`; none → nothing queued (correct) |
| Termination | From the day after the last working day. Correct |
| Roster | The roster date only: gap A |

---

## 6. Failure handling, retry and recovery

| Question | Answer |
|---|---|
| Can a request be lost? | No. It is a row committed with the change. The kick is at-most-once; Beat re-kicks every 5 minutes |
| What if the worker dies mid-request? | Days already calculated are committed one by one; the request stays pending and is run again from the start (idempotent) |
| What if a day keeps failing? | After 5 attempts the request is closed with `last_error` and one error log (`attendance_recalc_request_abandoned`). No screen, notification or blocker (MA-12) |
| What if the day is locked? | Skipped and counted; the request completes |
| Lock timeouts | `calculate` bounds lock and statement waits; a timeout counts as not done and is retried |
| Deadlocks | Not observed. Every path read takes row locks in ascending date order within one employee |
| Recalculation loops | None found. The cascade calls `_calculate` with the cascade switched off |
| Order within an employee | Ascending dates, which the cap allocation (D-04) and the cumulative counters need |
| Order across requests | Oldest request first; two requests for the same rows simply run twice |
| Concurrency of two processors for one company | Possible (kick plus Beat). Each `calculate` locks its row; the second waits or times out and retries. Not load-tested |
| Audit trail | Every recalculation writes an audit row with the full day; the request row keeps reason, source entity, requester, attempts, last error. There is no record of *which* days a request changed |

---

## 7. Previously reported R-1 to R-8, as triggers

| ID | Trigger aspect | State in the working tree |
|---|---|---|
| R-1 | Restoring a fully released leave after a holiday is removed | Re-derived from the application's own range and half; covered by the suite |
| R-3 | Undated calendar, roster and shift drift | No automatic trigger, by decision; HR runs preview and apply (API only) |
| R-4 | Cap cascade across a month boundary | The pass runs to the end of the second month when a monthly cap exists |
| R-5 | HR partial approval or rejection | Re-allocates later days in the reviewer's transaction |
| R-6 | Cascade without caps | Gated on a weekly or monthly cap being set |
| R-2, R-7, R-8 | Not trigger-related | See the master report |

---

## 8. Recommended changes, in order

1. Widen schedule-change requests by the ownership neighbourhood (gap A).
2. Queue on employment edits; guard the legal-entity edit (MA-10).
3. Report punches owned by a locked day (MA-06).
4. Coalesce pending requests per target and overlapping range; switch the cascade off inside the
   processor and rely on its date order (as `finalize` already does).
5. Surface abandoned requests to HR, or block period close while one overlaps the period.
6. Re-check open shortfalls after any credit entry (MA-11).
7. Make comp-off credit follow the overtime record (MA-03).
8. Drop the `shift_id` filter for rows with no shift, or queue by employee for shift changes (gap B).
9. Queue a break-override revocation from the override's own start date (MA-30).
10. Recalculate both dates of a cross-date regularization (MA-29).
11. Close a leave's open shortfalls when the leave is cancelled or withdrawn (MA-27).
12. Re-allocate cap budget after overtime is withdrawn at lock (MA-32).
13. Leave a `PENDING` overtime record untouched when nothing changed (MA-33).
14. Queue a durable request when a break-correction recalculation fails (C-17).

**Revision.** A second, independent pass on the same day added rows 18b and 27b, corrected rows 3,
10, 24, 30 and 38, and added items 9–14. The rest of this document was checked against `recalc.py`
(read in full) and the call sites it names.
