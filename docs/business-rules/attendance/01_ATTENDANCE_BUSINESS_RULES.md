# 01 — Attendance Business Rules

**Category legend:** A Implemented · B Configurable (and consumed unless noted) · C Architectural not built · D Open product decision · E Future module

**Authority:** Live calculation orchestration in `AttendanceDayService` + pure engine `evaluate_day` (`calculation.py`). Calendar classification in `calendar_resolution.py`.

---

## 1. Concept split (locked product model)

| Concept | Responsibility | Category |
|---|---|---|
| Calendar | Day type (WORKING / WEEKLY_OFF / HOLIDAY / SPECIAL_WORKING / SHUTDOWN) | A |
| Shift (+ ShiftVersion) | Schedule (when to work, breaks, duty blocks, OT eligibility flags) | A / B |
| Attendance Policy | How presence is evaluated (grace, bands, missing punch, multi-punch, leave overlay behaviour, lock incomplete behaviour) | A / B |
| Overtime Policy | OT eligibility, min/round/caps, approval, comp-off fact flags, day-class rate rows (informational multiplier) | A / B |
| Regularization Policy | Who may request, windows, allowed types, approval chain | A / B |
| Leave (projection) | Approved leave facts projected onto a date | A (mirror) / E (ledger) |
| Payroll | Money from locked attendance/OT/leave facts | E |
| Roster | Per-employee-date schedule override | A / B |

**Shift does not define:** grace evaluation, half-day hour bands, missing-punch behaviour, OT caps, regularization windows. Legacy `Shift` master still stores grace/thresholds historically; **W4+ engine reads `ShiftVersion` only** for schedule (A; legacy columns are leftover — C cleanup).

---

## 2. Complete calculation flow (verified)

Actual orchestration order (service then engine):

```
Period / day lock gate
        ↓
Employment as-of → population_status (ACTIVE | NOT_JOINED | EXITED)
        ↓
Assignment as-of → org placement, default shift_id, managers, branch timezone
        ↓
Published ShiftRoster for date (if any) → shift_id + week-off / holiday-working overrides
        ↓
ShiftVersion as-of (PUBLISHED covering date)
        ↓
Timezone: ShiftVersion.timezone > Branch.timezone > Company.timezone
        ↓
Schedule window (FIXED / FLEX / SPLIT) + punch load window
        ↓
Work Calendar resolution → calendar_day_type (+ holiday flags)
        ↓
Policy resolution (ATTENDANCE_POLICY, OVERTIME_POLICY, REGULARIZATION_POLICY) — independent walks
        ↓
Load punches in load window + active LeaveDayProjection rows
        ↓
evaluate_day (pure):
   population gate
   → CONFIG_ERROR if no calendar / no attendance policy
   → roster week-off (no punches) → NOT_EXPECTED
   → missing shift behaviour
   → expected vs not-expected (calendar + operates_on_* + roster holiday working)
   → collapse duplicates → pair punches
   → FIXED/FLEX or SPLIT evaluation (worked minutes, breaks, late/early, status, OT detect)
   → leave overlay
        ↓
Sync OvertimeRecord (approval / freeze) + write AttendanceDay + AttendanceBreak rows
        ↓
(Later) AttendancePeriod finalize → incomplete paid/LOP resolution → lock → PeriodSummary
```

**Regularization is not a stage inside `evaluate_day`.** Approved regularization inserts punches (`source=REGULARIZATION`) and may publish a roster shift, then calls `calculate()` again (A).

---

## 3. Population and assignment

### Employment gate — A

Uses `get_employment_as_of` only (not `employee.status` / `is_active`).

| Condition | `population_status` | Day status |
|---|---|---|
| No employment on/before date | NOT_JOINED | `NOT_JOINED` |
| Employment ended before date | EXITED | `EXITED` |
| Joining ≤ date and (no LWD or LWD ≥ date) | ACTIVE | continues |

Paid/LOP for terminals: `NOT_JOINED` → paid 1.00 / lop 0.00; `EXITED` → paid 0.00 / lop 1.00.

### Assignment — A

`get_assignment_as_of` supplies branch, department, designation, grade, reporting manager, `shift_id`. Overlaps are prevented by GiST. `NULL` shift is legitimate (DEC-018) — no company→branch default shift cascade (D: PD-BR14-SHIFT deferred).

### Rehire / transfer / terminate — A / E interaction

- Transfer = new assignment row with closed previous; attendance uses as-of date.
- Terminate closes assignment at LWD; days after LWD → EXITED.
- Rehire = new Employment on same employee id; gap days have no employment → NOT_JOINED/EXITED logic as above.
- Compensation/statutory/banking: Attendance must not read (E / locked ADR).

---

## 4. Calendar rules

### 4.1 Work Calendar — A / B

Composes ordered HolidayCalendars + WeeklyOffPattern + CalendarExceptions. Assigned via `PolicyAssignment` kind `WORK_CALENDAR`.

Flag `restricted_holidays_are_off_by_default` (default **false**): when true, OPTIONAL/RESTRICTED holidays are treated as hard holidays (D: PD-CAL-1).

### 4.2 Day-type precedence — A

1. Active `CalendarException` for date  
2. Else first matching holiday in ordered holiday-calendar union  
3. Else weekly-off pattern  
4. Else `WORKING`

### 4.3 Exception types — A / B

| Type | Resulting day_type | Notes |
|---|---|---|
| SHUTDOWN | SHUTDOWN | Not expected unless roster/shift forces work |
| SPECIAL_WORKING | SPECIAL_WORKING | Treated as **expected** working day by engine |
| SUBSTITUTE_HOLIDAY | HOLIDAY | Explicit substitute (no auto-create) |
| CANCEL_HOLIDAY | strips holiday; then WO or WORKING | |

### 4.4 Holiday types — A / B

| Type | Behaviour |
|---|---|
| PUBLIC / COMPANY | Hard holiday (unless CANCEL_HOLIDAY) |
| OPTIONAL / RESTRICTED | Soft: WORKING (names exposed) unless WorkCalendar flag treats as hard |
| WORKING_HOLIDAY | day_type WORKING with holiday name |

Holiday on weekly-off (hard holiday): day stays **WEEKLY_OFF**, `holiday_on_weekly_off=true` (WD-05). No auto substitute (D: PD-CAL-2).

### 4.5 Weekly-off patterns — A / B

Typed rules (`WeeklyOffRule`), not JSON:

| Pattern capability | How encoded |
|---|---|
| Fixed weekdays | weekday only |
| Nth weekday | `nth_in_month` 1..5 |
| Last weekday | `nth_in_month = -1` |
| Alternate | `cycle_start_date` + `week_parity` (default EVEN = off on cycle-start week) |
| Custom | same child table, any combination |
| Off fraction | `off_fraction` (largest wins if multiple rules match) |

Separate `WEEKLY_OFF` PolicyAssignment can override the pattern attached to the WorkCalendar.

### 4.6 Calendar × expectation interactions — A

| Calendar | Shift/Roster | Punches | Typical status |
|---|---|---|---|
| HOLIDAY/WO/SHUTDOWN | does not operate, no holiday-working override | none | NOT_EXPECTED |
| same | operates_on_* or roster holiday working | evaluated | PRESENT/…/INCOMPLETE |
| WORKING / SPECIAL_WORKING | normal | none | INCOMPLETE or ABSENT per missing_punch |
| any | roster week-off | none | NOT_EXPECTED |

Roster overrides **never change** `calendar_day_type` (WD-27).

---

## 5. Shift rules

### 5.1 What Shift defines — A / B

Via published `ShiftVersion`:

- `shift_type`: FIXED | FLEXIBLE | SPLIT
- Timing: start/end **or** window_start/end **or** duty blocks
- `required_minutes` (especially FLEX/SPLIT)
- `is_cross_midnight`, `is_night_shift` (flag; engine night OT uses cross-midnight)
- `is_ot_eligible`, `operates_on_holiday`, `operates_on_weekly_off`
- Breaks, duty blocks, optional version timezone

### 5.2 What Shift does not define — A

Grace minutes for evaluation, hour/late/early bands, missing punch behaviour, multi-punch mode, OT caps, regularization — those are policies.

### 5.3 Overnight ownership — A

Attendance date = **shift-start date**. Cross-midnight end is on attendance_date+1. Punch load window follows schedule (± padding), not civil midnight (except null-shift calendar-day window).

Example: 22:00→06:00 on 20 Aug → attendance date **2026-08-20**.

### 5.4 FIXED — A

Scheduled start/end; late vs start after grace; early vs end after grace; OT vs scheduled span minutes.

### 5.5 FLEXIBLE — A (partial)

Schedule window = window_start–window_end; `required_minutes` used for OT baseline when needed. **Core hours** (`core_start`/`core_end`) and policy `core_hours_breach_behaviour` / `early_out_uses_core_end` are **loaded but unused** (STORED BUT NOT USED). Late is computed vs scheduled_start (window_start), not a separate flex rule.

### 5.6 SPLIT — A

≥2 duty blocks. Each block needs ≥1 overlapping IN–OUT pair. Missed blocks use `split_shift_missed_block_behaviour` (IGNORE / HALF_DAY / ABSENT / REQUIRE_REGULARIZATION→INCOMPLETE). Late/early forced to **0**. OT uses `required_minutes`. Partial minutes inside a block are not sub-scored (documented simplification).

### 5.7 Shift versioning — A / B

DRAFT editable; PUBLISHED immutable except `effective_to` when next version publishes. Calculation uses published version covering the attendance date. Unpublished draft never affects live calc.

---

## 6. Break rules — A / B (partial)

### Configured on ShiftVersion

- FIXED_WINDOW: start/end
- FLEXIBLE_DURATION: window + min/max minutes
- `is_paid` / `is_mandatory` / `allows_split` / `crosses_midnight`

### Consumed by engine

- Gaps between punch pairs matched to break windows
- Unpaid matched minutes deducted (PAIR_ALL: unpaid already outside gross; paid gaps added back)
- Excess over `max_minutes` → `is_excess` / `excess_break_minutes` counted
- **`excess_break_behaviour` not applied** (FLAG/etc. unused)
- **`is_mandatory` / `min_minutes` unused** — no auto-deduct of scheduled break with zero punched gap (known limitation)

### Concrete example

Shift 09:00–18:00 (9h = 540m), unpaid break 13:00–14:00 (60m).  
Punch 09:00–19:00, FIRST_IN_LAST_OUT, one gap 13:00–14:00 matched unpaid.

- Gross span: 600m  
- Unpaid break: 60m → worked ≈ 540m  
- Scheduled: 540m → OT excess 0 (before any OT eligibility)

If employee stayed until 19:00 with same unpaid break: worked 600−60=540 → still 0 OT vs 540 scheduled. If break unpaid not matched (no gap): PAIR_ALL/FILO may count full span as worked → OT possible — **engine does not invent the break**.

---

## 7. Attendance policy catalogue

### 7.1 Fields consumed by evaluation or finalize — A / B

| Field | Effect |
|---|---|
| `grace_in_minutes` / `grace_out_minutes` | Subtracted before late/early |
| `missing_punch_behaviour` | INCOMPLETE (default) / ABSENT / AUTO_CLOSE† / REQUIRE_REGULARIZATION→INCOMPLETE |
| `missing_shift_behaviour` | ABSENT or INCOMPLETE when no shift and no punches |
| `multi_punch_mode` | PAIR_ALL \| FIRST_IN_LAST_OUT |
| `duplicate_punch_window_seconds` | Collapse same-direction duplicates |
| `split_shift_missed_block_behaviour` | Missed duty block outcome |
| `work_on_leave_behaviour` | KEEP_LEAVE \| PRESENT_CANCEL_LEAVE_HINT |
| `incomplete_at_lock_behaviour` | TREAT_ABSENT / TREAT_PRESENT / KEEP_INCOMPLETE (finalize only) |
| Hour bands | worked minutes → PRESENT / HALF_DAY / ABSENT |
| Late / early bands | minutes → classification; ABSENT/HALF_DAY can force status |

† AUTO_CLOSE: falls through to hour bands; **does not synthesize OUT**; `auto_closed` always false today.

### 7.2 Copied into PolicyInputs but unused in functions — STORED BUT NOT USED

`punch_rounding`, `rounding_minutes`, `half_day_split`, `half_day_boundary_minutes`, `core_hours_breach_behaviour`, `early_out_uses_core_end`, `excess_break_behaviour`.

### 7.3 Stored on version / API, not in engine inputs — STORED BUT NOT USED

`auto_close_after_minutes`, `auto_close_uses_shift_end`, `split_shift_block_mandatory`, `split_shift_allow_hours_compensation`, `wfh_requires_punch`, `on_duty_requires_punch`, `wfh_uses_shift_hours`, `late_count_window`, `lates_to_half_day_count`, `early_departure_requires_approval`.

Band child `counts_toward_cap`: unused (no late-count→half-day engine).

### 7.4 Attendance statuses produced — A

`NOT_JOINED`, `EXITED`, `CONFIG_ERROR`, `NOT_EXPECTED`, `PRESENT`, `HALF_DAY`, `ABSENT`, `INCOMPLETE`, `LEAVE`.

Schema also allows `ON_DUTY`, `WFH` — **never emitted by `evaluate_day`** (C / STORED ENUM ONLY).

### 7.5 Paid / LOP fractions — A

| Status | paid | lop |
|---|---|---|
| PRESENT | 1.00 | 0.00 |
| HALF_DAY | 0.50 | 0.50 |
| ABSENT | 0.00 | 1.00 |
| NOT_EXPECTED / NOT_JOINED | 1.00 | 0.00 |
| EXITED | 0.00 | 1.00 |
| INCOMPLETE / CONFIG_ERROR | 0.00 | 0.00 (until lock resolution for INCOMPLETE) |
| LEAVE | from leave paid/unpaid fractions | |

At lock: INCOMPLETE + TREAT_ABSENT → paid 0 / lop 1; TREAT_PRESENT → paid 1 / lop 0; **status string stays INCOMPLETE**.

---

## 8. Late arrival — A / B

`late_minutes = max(0, (first_in − scheduled_start) − grace_in)`. Classification from late bands. If classification HALF_DAY/ABSENT, status forced accordingly (after hour-band baseline). SPLIT: late always 0.

### Grace examples (scheduled 09:00, grace 15)

| Punch IN | late_minutes |
|---|---|
| 09:05 | 0 |
| 09:15 | 0 |
| 09:16 | 1 |
| 09:30 | 15 |
| 10:00 | 45 |

Then band lookup decides FLAG/HALF_DAY/ABSENT (configured). Without matching band, late flag may still be true with null classification; status from hours.

### Combinations

| Combo | Current behaviour |
|---|---|
| Late + half-day band | Status HALF_DAY (if not ABSENT from hours/early) |
| Late + full leave KEEP_LEAVE | Status LEAVE; late zeroed |
| Late + PRESENT_CANCEL_LEAVE_HINT + work | Punch outcome kept; `work_on_leave_flagged` |
| Late + holiday/WO not expected, no operate | NOT_EXPECTED if no punches; if punches, evaluated |
| Late + flex | Late vs window_start |
| Late + split | Not computed |
| Late + regularization | Synthetic punches recompute late |
| Late + WFH status | N/A — engine never sets WFH |

---

## 9. Early departure — A / B

Mirror of late vs `scheduled_end` and `grace_out_minutes`. Early + OT: OT is from worked vs scheduled; leaving early usually reduces worked minutes (less OT). `early_departure_requires_approval` unused.

---

## 10. Missing punch — A / B

Orphans from pairing or no first_in ⇒ `missing_punch=true`.

| Behaviour | Result |
|---|---|
| INCOMPLETE (default) | Status INCOMPLETE if missing and not overridden by ABSENT choice |
| ABSENT | ABSENT |
| REQUIRE_REGULARIZATION | INCOMPLETE |
| AUTO_CLOSE | Does **not** auto-create OUT; falls through to hour bands |

Missing both / no punches on expected day: INCOMPLETE or ABSENT per policy. Odd sequences produce orphans. Device duplicates collapsed by window. Manual/admin/regularization punches are ordinary punches with different `source`. Locked day: new punches refused.

---

## 11. Multi-punch — A / B

**Pairing:** IN opens; consecutive IN orphans prior; OUT without IN orphans; trailing IN orphan.

| Sequence | Pairs | Orphans |
|---|---|---|
| IN OUT IN OUT | 2 pairs | — |
| IN IN OUT | 1 pair (2nd IN–OUT) | first IN |
| IN OUT OUT | 1 pair | second OUT |
| IN OUT IN | 1 pair | trailing IN |

PAIR_ALL: sum pair intervals; gaps = break candidates.  
FIRST_IN_LAST_OUT: first IN→last OUT gross; unpaid gaps deducted.

---

## 12. Roster rules — A / B

Published roster for (employee, date):

- `shift_id` replaces assignment shift for **schedule**
- `is_week_off_override` XOR `is_holiday_working_override`
- DRAFT ignored by calculation; blocks period finalize if any DRAFT in range

| Situation | Behaviour |
|---|---|
| Assignment Shift A, roster Shift B | Schedule B |
| Roster no shift_id + week-off | NOT_EXPECTED (no punches) |
| Roster unpublished | Ignored for calc; finalize blocker |
| Roster vs holiday | calendar_day_type unchanged; expectation may change |
| Roster after calc | Recalc needed to apply |
| Roster after lock | Mutation refused |

**Policy SHIFT scope** still uses assignment.shift_id (doc/code divergence — see Precedence Matrix).

---

## 13. Leave rules (W9) — A / E

### Attendance projection (A)

`LeaveDayProjection`: fraction 0.50|1.00, half FIRST|SECOND for half-day, `is_paid`, status APPROVED|CANCELLED, opaque `leave_application_id`. Sync/cancel → `calculate()`. Active fractions on a date must sum ≤ 1.00.

### Overlay (A)

- Full-day (≥1.00): KEEP_LEAVE → LEAVE, late/early cleared; hint mode keeps punch status + flag
- Half-day: flat 0.50 leave contribution; status HALF_DAY if worked_minutes>0 else LEAVE
- Does not change calendar_day_type
- Skipped for NOT_JOINED / EXITED / CONFIG_ERROR

### Not implemented here (E)

Balances, accrual, approval of leave applications, cancel leave because of punch, statutory leave types beyond paid flag.

### Lock (A)

Leave sync/cancel refused when period closed for that date.

---

## 14. WFH / On-duty — C / STORED

- Day statuses exist in schema; engine never produces them
- Policy punch-requirement fields stored unused
- Regularization types WFH/ON_DUTY allowed by policy but apply path only punches ± shift
- Assignment `work_location_type` is placement hint only (WD-17); no auto WFH (D: PD-WFH-1)

---

## 15. Overtime rules — A / B (partial)

### Detection — A

```
eligible? (policy + SHIFT_FLAG)
excess = max(0, worked − scheduled_or_required)
if excess < min_ot → 0
round (if configured)
min(daily_cap, remaining_weekly, remaining_monthly)
classify day_class → lookup classification_code
```

Eligibility:

| Value | Behaviour today |
|---|---|
| NEVER | No OT |
| SHIFT_FLAG | Requires shift.is_ot_eligible |
| ALWAYS | Eligible (no shift flag check) |
| GRADE_VIA_ASSIGNMENT | **No grade check** — behaves like ALWAYS |

Holiday/WO OT day_class uses **worked_on_holiday / worked_on_weekly_off** (worked minutes > 0 on that calendar type).

On a holiday or weekly off, `excess` is still measured against the shift's scheduled minutes
(the schedule window does not depend on day type): with an 8 h shift, working 8 h on a weekly
off detects **0** OT, and working 10 h detects 120 min. Comp-off (`comp_off_minutes` =
detected OT when `comp_off_instead_of_pay`) inherits this, so off-day work up to a full shift
earns no comp-off today. Whether off-day work should count in full is an open decision — see
`docs/audits/COMPOFF_POLICY_SAFETY_REVIEW.md`.

### Night OT — gap

`is_night` = `shift.is_cross_midnight`.  
`classify_ot_day` returns NIGHT only if `is_night and night_ot_mode in (WINDOW, BOTH)`.  
Default `night_ot_mode=SHIFT_FLAG` therefore **never classifies NIGHT**.  
`night_window_start/end` unused.

### Approval — A / B

- `requires_post_approval` + chain ≠ AUTO → PENDING until approve/reject
- Chain AUTO or requires_post_approval false → AUTO_APPROVED with full detected minutes
- Approve sets minutes_approved = minutes_detected (no partial)
- Self-approval blocked; missing manager escalates stage to HR + APPROVER_UNRESOLVED
- Terminal statuses frozen on recompute
- `requires_pre_approval` stored unused

### Comp-off — A / E

If `comp_off_instead_of_pay`: minutes (+ expiry date from `comp_off_expiry_days`) stored as facts. Leave ledger redemption is E.

### Caps example

Detected raw excess 73; min 30 → keep; round 30 UP → 90; daily cap 120 → 90; if weekly remaining 60 → **60**.

---

## 16. Regularization — A / B

### Who / windows — B

Flags: allow employee/manager/HR request; `max_backdated_days`; `max_requests_per_month`; reason/attachment; allowed types list (empty = none); `blocked_when_locked`.

Types: MISSING_PUNCH, WRONG_PUNCH, WRONG_SHIFT, WRONG_STATUS, WFH, ON_DUTY, FULL_DAY.

### Chains — A

AUTO / MANAGER / HR / MANAGER_THEN_HR. Self-approval forbidden. `auto_approve_within_minutes` unused (AUTO chain is separate).

### Apply — A

Punches with source REGULARIZATION + optional roster PUBLISH for requested_shift_id → calculate → mark_regularized.  
**Note:** `calculate` writes `is_regularized=False`; flag only survives until next recompute after mark (implementation quirk).

### Lock — A

Submit blocked when locked if policy `blocked_when_locked` (default true). Pending SUBMITTED blocks finalize.

---

## 17. Period finalization and lock — A / B

States: **OPEN | CLOSED** (CLOSED = locked). No persisted CLOSING.

### Grain — A

**Per legal entity** (`PAYROLL_BUSINESS_DECISIONS.md` decision 14). Every period belongs to one legal entity; periods of the same entity cannot overlap, different entities' periods can. A period owns the employee-dates whose employment on that date is in its entity — an employee transferred mid-month is split between the two entities' periods. A date no employment covers belongs to the entity of the spell that ended before it (after exit, or a gap), else the spell starting after it (before joining).

Default cycle: **full calendar month** (decision 18) — create with `month: "YYYY-MM"`; an explicit start/end range is still accepted for an off-cycle period.

Everything below — validation blockers, summary, lock, reopen and the lock checks on punches, rosters, regularizations, overtime, calculation and leave — applies only to the employee-dates the period owns. Two company-wide changes still refuse when *any* entity's closed period covers the date: shift-version publish and the company timezone change.

### Validate blockers — A

`EMPLOYEES_WITHOUT_ATTENDANCE`, `CONFIG_ERROR`, `INCOMPLETE_ATTENDANCE` (only KEEP_INCOMPLETE), `PENDING_REGULARIZATION`, `PENDING_OVERTIME_APPROVAL`, `UNPUBLISHED_ROSTER`.

### Finalize — A

Re-validate → close → resolve INCOMPLETE paid/lop → snapshot summaries → lock the owned days (each records `locked_period_id`). Reopen unlocks exactly the days that period locked.

### Impossible after lock — A

| Action | Behaviour |
|---|---|
| Punch | Refusal (period closed / day locked) |
| Calculate / recompute | Refusal |
| Roster mutation | Refusal |
| Regularization submit | Refusal (policy) |
| OT approve/reject | Refusal |
| Leave projection sync/cancel | Refusal |
| Roster / policy config for future dates | Allowed if outside closed range |

Reopen (`ATTENDANCE.UNLOCK`): unlocks days; **no auto-recompute**. Arrears/adjustment entity not built (E / WD-18).

---

## 18. Actor views (capability, not UI design)

| Concern | Employee | Manager | HR/Admin |
|---|---|---|---|
| Own attendance / punches | VIEW (SELF scope) | — | VIEW_ALL / COMPANY |
| Team attendance | — | VIEW REPORTEES/TREE | VIEW_ALL |
| Request regularization | if policy allows | on-behalf if allowed | on-behalf |
| Approve regularization / OT | — | if snapshotted manager | HR stage / OVERTIME_APPROVE / REGULARIZATION_APPROVE |
| Configure calendars/shifts/policies | — | — | POLICY_MANAGE / ORG masters |
| Roster | — | if granted ROSTER_MANAGE | ROSTER_MANAGE |
| Finalize / unlock period | — | — | LOCK / UNLOCK |
| Leave projection sync | — | — | LEAVE_PROJECTION_SYNC (API) |

Exact screens: attendance, regularizations, overtime, attendance-periods, calendars, policies, rosters, shifts. No Leave UI.

---

## 19. Fail-closed rules — A

| Situation | Result |
|---|---|
| No work calendar resolved | CONFIG_ERROR (`no_calendar_resolved`) |
| No attendance policy version | CONFIG_ERROR (`no_policy_resolved`) |
| Missing OT / regularization policy | OT/reg features degrade/refuse; day can still calculate if attendance policy present |
| No shift + no punches | ABSENT or INCOMPLETE per missing_shift_behaviour |
| Unpublished shift version for date | Treated as no shift |
| DRAFT roster | Ignored in calc; blocks finalize |
| KEEP_INCOMPLETE at finalize | BLOCKED |
| CONFIG_ERROR days at finalize | BLOCKED |
| Closed period mutation | AttendancePeriodClosedError / day locked |

Resolution APIs expose `config_incomplete=true`; day status uses **`CONFIG_ERROR`** (not a status named CONFIG_INCOMPLETE).

---

## 20. Historical / effective-dated behaviour — A

| Change | Rule used for date D |
|---|---|
| Policy version effective_from/to | Published version covering D snapshotted onto AttendanceDay |
| Shift version | Published version covering D |
| Assignment | as-of D |
| Calendar exception / holiday | as classified when calculated; recompute picks current config unless locked |
| Roster | published row for D |
| Leave projection | active rows at calculate time |

**Reproducibility:** version FKs + `computation_snapshot` + immutable punches (WD-11). Recompute **can** change unlocked historical results if config/punches/leave/OT siblings changed. **Lock** prevents recompute. Frozen OT terminal decisions survive recompute even when unlocked.

Weekly/monthly OT remaining depends on sibling `OvertimeRecord` minutes — recompute of one day can change detected OT if siblings changed (documented W7 simplification).
