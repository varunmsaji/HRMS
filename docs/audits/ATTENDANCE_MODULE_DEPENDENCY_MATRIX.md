# Attendance Module Dependency Matrix — 16 November 2026

**Written for:** architect and engineering team. Part of
`MASTER_ATTENDANCE_SYSTEM_AUDIT_2026-11-16.md`. Describes the uncommitted working tree (engine 16).

Every module and operation that can change an attendance result, with what it should trigger and
what it triggers today. The mechanics of each trigger (transaction, queue, retry) are in
`ATTENDANCE_RECALCULATION_TRIGGER_AUDIT.md`.

**Status words:** OK = implemented and read in code (R = also exercised by a probe or a test that
ran in this audit). GAP = missing or incomplete, with the finding id. BY DESIGN = deliberately not
done, recorded as a decision.

**Column key:** Recalc = attendance recalculation of affected existing rows. Leave = approved
leave must be re-derived. OT = overtime decisions or caps may move. Close = what period close does
about it.

---

## 1. How each module feeds a day's result

| Module | Supplies | Read by | Stored on the day row |
|---|---|---|---|
| Employment | population gate, pay basis, legal entity (period ownership) | `_build_calculation_input`, `_PeriodScope` | status `NOT_JOINED`/`EXITED`; pay basis in snapshot |
| Employee assignment | shift, branch (timezone), department, designation, grade (policy scope), manager (overtime approver) | `WorkScheduleResolver`, `_scope_candidates`, `_resolve_ot_decision` | `shift_id`, `shift_version_id`, `timezone` |
| Shift and shift version | type, times, breaks, duty blocks, operates-on flags, overtime and night flags, timezone | `resolve_shift_schedule` | `shift_version_id`, scheduled start, end, minutes |
| Roster | shift of the date, week-off, working-this-holiday | `WorkScheduleResolver`, `_working_shares` | flags in snapshot |
| Shift swap | rewrites two roster rows on approval | `schedule_service` | through roster |
| Work calendar, holiday calendars, holidays, weekly-off pattern, exceptions | day type, holiday type and paid flag, weekly-off fraction | `CalendarResolutionService` | `work_calendar_id`, `calendar_day_type`, holiday name |
| Policy assignment | which calendar, weekly-off pattern, attendance, overtime, regularization, leave policy applies | `resolve_policy_assignment` | resolved version ids |
| Attendance policy version | grace, bands, punch limits, missing-punch and lock behaviour, cumulative rules | engine | `attendance_policy_version_id` |
| Overtime policy version | eligibility, minimum, rounding, caps, chain, comp-off, night mode, rate rows | engine, `_resolve_ot_decision` | `overtime_policy_version_id` |
| Regularization policy version | who may request and approve | regularization service | `regularization_policy_version_id` |
| Punches, dismissals | presence | `PunchOwnershipService` | punch ids in snapshot |
| Break events, break overrides | break figures | `break_service`, engine | `attendance_break` rows |
| Regularization | synthetic punches; ON_DUTY; early-departure approval | regularization service, engine inputs | `on_duty_regularization_id`, regularized flag |
| Leave | approved day projections (fraction, half, paid) | `LeaveProjectionService`, engine overlay | `leave_fraction` |
| Overtime decisions | approved minutes, comp-off | `OvertimeRecordService` | overtime columns |
| Sibling days | late and excess-break counts in the month; overtime counted earlier in week and month | repositories | `derived_inputs` in snapshot |
| Period | lock, lock-time resolution of `INCOMPLETE` | `AttendancePeriodService` | `is_locked`, period id, paid / LOP fractions |
| Notifications | none (output only) | — | — |
| Payroll | none (reads a closed period only; a finalized run forbids reopen) | — | — |

---

## 2. Mutation matrix

### Employment and employee

| Operation | People | Dates | Recalc | Leave | OT | Close | Status |
|---|---|---|---|---|---|---|---|
| Create employment (incl. rehire) | the employee | joining date → today | queued `EMPLOYMENT_CREATED` | — | — | recalculates in-period days | OK (R, IP4) |
| Terminate employment | the employee | day after last working day → today | queued `EMPLOYMENT_TERMINATED` | refused if leave exists after the date | records on exited days are re-derived | post-exit punches raise `ORPHAN_PUNCHES` | OK (R, IP4). No closed-period guard: GAP MA-21 |
| Edit employment: pay basis | the employee | whole spell | **none** | — | — | recalculates in-period days | GAP MA-10 (R, IP5) |
| Edit employment: legal entity | the employee | whole spell, including locked days | **none** | — | — | ownership of every date moves to another entity's periods | GAP MA-10 |
| Edit employment: probation end | the employee | — | not needed | accrual of later months | — | — | OK |
| Deactivate employee | the employee | — | none; the daily sweep skips inactive employees | — | — | missing rows raise `EMPLOYEES_WITHOUT_ATTENDANCE` | Plausible risk (reported by a code reading, not reproduced): a deactivated but still employed person blocks close until HR runs `calculate-range`; a terminated employee who stays `is_active` gets an `EXITED` row every day |
| New assignment (transfer, shift, grade, manager) | the employee | `effective_from` → end of the split range | queued `ASSIGNMENT_CREATED` | **none** (drift → blocker) | via recalculation | recalculates | OK for recalc; neighbour day GAP MA-07; leave BY DESIGN (P-12) |
| Manager change | the employee | — | none | pending approvals keep their approver; leave has a reassignment path | pending overtime keeps its approver; **no reassignment, no HR override at the manager stage** | a departed manager's records block `PENDING_OVERTIME_APPROVAL` | GAP MA-34 (code-confirmed) |

### Shift, roster, swap

| Operation | People | Dates | Recalc | Leave | OT | Close | Status |
|---|---|---|---|---|---|---|---|
| Publish shift version | days calculated on that shift | `effective_from` → today | queued `SHIFT_VERSION_PUBLISHED` (by `shift_id`) | none (blocker) | via recalculation | recalculates | OK; days that did not use the shift before are not matched; neighbour GAP MA-07 |
| Deactivate shift | — | — | none | — | — | — | Plausible risk (code reading, not reproduced): the engine does not read `Shift.is_active`, so assignments and roster rows keep resolving the shift; swaps do not check it |
| Roster create / update / publish / delete (published rows) | the employee | the roster date | queued `ROSTER_CHANGED` | none (blocker `LEAVE_CALENDAR_MISMATCH`) | via recalculation; P-C for human decisions | recalculates; draft rows block | OK (R); neighbour GAP MA-07 (R, IP7c); shift-scoped policy GAP MA-04 (R, IP3) |
| Shift swap approved | both employees | both dates | queued `SWAP_APPROVED` | none | via recalculation | recalculates | OK (read) |

### Calendar

| Operation | People | Dates | Recalc | Leave | OT | Close | Status |
|---|---|---|---|---|---|---|---|
| Holiday create / edit / deactivate | assignments of calendars linking it (company-wide if scoped wider than employee or shift) | old and new date | queued `HOLIDAY_CHANGED` | **reconciled in the same transaction** (refund, debit, shortfall) | via recalculation | recalculates; shortfall blocks | OK (R) |
| Calendar exception create / edit | the calendar's assignments | the date(s) | queued `CALENDAR_EXCEPTION_CHANGED` | reconciled | via recalculation | same | OK (R) |
| Holiday calendar validity / active | linked calendars | oldest unlocked day → today | queued `HOLIDAY_CALENDAR_CHANGED` | none (blocker) | via recalculation | recalculates | Validity: OK; leave BY DESIGN ("policy A", open). **Active flag: queued, but the resolver ignores it, so nothing changes** (MA-28, reproduced: C1-INACTIVE-HOLIDAY-CAL). The same holds for the work calendar and pattern active flags |
| Weekly-off pattern rules / active | calendars using it + `WEEKLY_OFF` assignments | oldest unlocked day → today | queued `WEEKLY_OFF_PATTERN_CHANGED` | none (blocker) | via recalculation | recalculates | OK (R); leave BY DESIGN |
| Work calendar pattern / links / restricted flag / active | its assignments | oldest unlocked day → today | queued `WORK_CALENDAR_CHANGED` | none (blocker) | via recalculation | recalculates | OK (R) |
| Policy assignment create / change / end (any kind) | the scope | from the assignment's start | queued `POLICY_ASSIGNMENT_CHANGED` | none (blocker) | via recalculation | recalculates | OK (read) |
| `CalendarImpactService.confirm` | as the method it calls | — | as above | as above | — | — | OK |

### Policies

| Operation | People | Dates | Recalc | OT | Status |
|---|---|---|---|---|---|
| Publish attendance policy version | the policy's assignments | `effective_from` → today | queued `POLICY_VERSION_PUBLISHED` | via recalculation | OK (read; no dedicated test) |
| Publish overtime policy version | the policy's assignments | `effective_from` → today | queued | human-approved minutes re-priced (O-15) | OK (R) |
| Publish regularization policy version | — | — | none | — | OK (does not affect results) |
| Publish leave policy version | — | — | none | — | OK; existing applications keep their version |
| Break override create | the employee | override start → today | queued `BREAK_OVERRIDE_CHANGED` | via recalculation | OK (R) |
| Break override revoke | the employee | **today onwards only** (`max(effective_from, today)`) | queued | via recalculation | GAP MA-30: revocation applies to past dates too, so open past days stay stale until the sweep or close |
| Grace change | is an attendance policy version | — | as above | — | OK |

### Punches, regularization, ON_DUTY

| Operation | Dates recalculated | How | OT | Close | Status |
|---|---|---|---|---|---|
| Punch created (self, on-behalf, face, manual day) | the punch's local date and its owning date | in-request, best effort; on failure queued `IMMEDIATE_CALCULATION_FAILED` | re-derived; caps cascade to later days | — | OK. A third day whose session changed owner: GAP (open since the shift audit). Punch owned by a locked day: GAP MA-06 (R, IP9b) |
| Orphan punch dismissed | none | — | — | clears `ORPHAN_PUNCHES` | OK (a dismissed punch was owned by no day) |
| Regularization approved (missing punch, correction, break correction) | the request's attendance date | in-request, required to succeed | re-derived; P-C | refused on a closed date | OK (R) for its own date. GAP MA-29 (code-confirmed): requested punches may be up to a day either side, and the other date is not recalculated. No revoke of an approved request (C-14) |
| Break correction applied | the date | in-request, best effort; on failure only logged | re-derived | — | GAP C-17: unlike a punch, a failure queues nothing |
| Regularization ON_DUTY / early-departure approval | the date | in-request | ON_DUTY zeroes overtime; decision kept dormant | — | OK (R). A second approved request of the same type for the date fails with HTTP 500 (MA-31, reproduced) |
| Regularization cancelled or rejected | — | nothing applied | — | pending ones block | OK |

### Leave

| Operation | Dates recalculated | Ledger | Projection | Close | Status |
|---|---|---|---|---|---|
| Leave approved (incl. AUTO chain at submit) | every leave day, in-request | one debit dated at start date | one per day | approval refused on a closed day; shares the close lock | OK (R) |
| Leave cancelled / reversed | every leave day, in-request | refund of what was debited | cancelled | refused on a closed day | OK (R) for days and ledger. GAP MA-27 (reproduced): an open shortfall for the leave stays open and keeps blocking close |
| Leave rejected / withdrawn | none | none | none | pending blocks | OK |
| HR balance credit | days of open shortfalls | adjustment; then debit of waiting days | added | clears `LEAVE_BALANCE_SHORTFALL` | OK (R) |
| Monthly accrual, carry-forward, comp-off credit | none | credit | none | open shortfalls stay open | GAP MA-11 |
| Reconciliation preview / apply | affected leave days | refund / debit / shortfall | synced | clears `LEAVE_CALENDAR_MISMATCH`; closed periods protected | OK (R); API only, no screen |
| Year-end sweep | none | carry-forward, lapse, encashment | — | — | LV-01…LV-03 open |

### Overtime and comp-off

| Operation | Effect on other days | Comp-off | Status |
|---|---|---|---|
| Approve in full | none | credit by hourly sweep | OK |
| Approve fewer minutes / reject | later days of the week and month re-allocated in the same transaction when a cap exists | — | OK (R) |
| Recalculation changes a decided record | supersede action; later days cascade | **credit not adjusted** | GAP MA-03 (reproduced, IP10) |
| Recalculation of a day with a `PENDING` record | record rewritten and version raised every time, even unchanged | — | GAP MA-33 |
| Withdrawn at lock | **freed cap budget not handed to later days** | **credit not reversed** | GAP MA-03, MA-32 |

### Period

| Operation | Effect | Status |
|---|---|---|
| Validate | reads stored rows; reports blockers | OK; can say `READY` on stale rows (finalize does not trust it) |
| Finalize | recalculates unlocked owned days, validates, resolves `INCOMPLETE`, freezes summary, locks | OK (R); `TREAT_PRESENT` GAP MA-02 |
| Reopen | unlocks; nothing recalculated until the next change or finalize | OK (R) |

---

## 3. Dependencies with no trigger at all

1. Employment pay-basis and legal-entity edits (MA-10).
2. A neighbouring day whose punches change owner after a schedule change (MA-07).
3. Accrual and other credits against an open leave shortfall (MA-11).
4. Comp-off credit against a changed overtime record (MA-03).
5. A punch owned by a locked day (MA-06).
6. Raising `ENGINE_VERSION` (by design; a range recalculation is the documented step).
7. Days with no row: the queue never creates one; the sweep covers three days back.
8. Past open days after a break override is revoked (MA-30).
9. The second date touched by a cross-date regularization (MA-29).
10. Later days of a capped week or month when overtime is withdrawn at lock (MA-32).
11. A leave shortfall after its leave is cancelled (MA-27).
12. Deactivating a holiday calendar, work calendar or weekly-off pattern: a recalculation is queued
    but resolves to the same result, because the active flag is ignored (MA-28).

Revised by a second, independent pass on the same day: items 8–12 and the rows that cite MA-27 to
MA-34 were added. Nothing this pass read contradicted the other rows.
