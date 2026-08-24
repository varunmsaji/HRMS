# Workforce Attendance — Complete Business Rules & Scenario Specification (Combined)

**Generated:** 2026-08-20

This file concatenates the full document set for offline reading. Individual files remain the maintained sources:

- README.md
- 01_ATTENDANCE_BUSINESS_RULES.md
- 02_ATTENDANCE_PRECEDENCE_MATRIX.md
- 03_ATTENDANCE_SCENARIO_CATALOG.md
- 04_ATTENDANCE_CONFIGURATION_CATALOG.md
- 05_ATTENDANCE_CONFLICT_SCENARIOS.md
- 06_ATTENDANCE_INDIAN_HR_SCENARIOS.md
- 07_ATTENDANCE_GAP_ANALYSIS.md
- 08_ATTENDANCE_OPEN_PRODUCT_DECISIONS.md

---


<!-- ============================================================ -->
<!-- SOURCE FILE: README.md -->
<!-- ============================================================ -->

# Workforce Attendance — Business Rules Document Set

**Status:** Documentation only. Produced by studying the live W1–W9 implementation and architecture. No application code was changed to produce these documents.

**Date:** 2026-08-20

**Source of truth priority:**

1. Live code (`apps/api/src/hrms/modules/attendance/*`, `organisation/calendar_resolution.py`, organisation shift/calendar models, related tests)
2. Architecture + decision log (`docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md`, `WORKFORCE_ATTENDANCE_DECISION_LOG.md`)
3. W1–W9 implementation reports (claims only; contradicted by code when they diverge)

If documentation and code disagree, **these business-rules documents record the difference** and describe **current code behaviour**. They do not silently “fix” the product by rewriting either side.

---

## Purpose

This set answers, at business level:

- What happens on every kind of attendance day?
- What can HR/Admin configure today?
- Which rule wins when multiple rules apply?
- What do Employee / Manager / HR see?
- What happens when leave, holiday, weekly-off, shift, roster, punches, regularization, overtime, and period lock interact?
- What is missing, unused, or still an open product decision?

It is **not** a UI design, implementation plan, or W10+ build brief.

---

## Document map (what is authoritative for what)

| Doc | Authoritative for |
|---|---|
| [`01_ATTENDANCE_BUSINESS_RULES.md`](./01_ATTENDANCE_BUSINESS_RULES.md) | End-to-end calculation flow; calendar / shift / break / policy / leave / OT / regularization / lock rules; actor views; fail-closed states; historical/effective dating |
| [`02_ATTENDANCE_PRECEDENCE_MATRIX.md`](./02_ATTENDANCE_PRECEDENCE_MATRIX.md) | Per-family precedence tables + master “what overrides what” matrix |
| [`03_ATTENDANCE_SCENARIO_CATALOG.md`](./03_ATTENDANCE_SCENARIO_CATALOG.md) | ≥30 realistic employee scenarios with inputs → calculation → views → payroll facts |
| [`04_ATTENDANCE_CONFIGURATION_CATALOG.md`](./04_ATTENDANCE_CONFIGURATION_CATALOG.md) | Every setting HR/Admin can configure **today** (API + UI where present); marks stored-but-unused fields |
| [`05_ATTENDANCE_CONFLICT_SCENARIOS.md`](./05_ATTENDANCE_CONFLICT_SCENARIOS.md) | Conflict matrix (calendar × shift × leave × OT × lock × regularization) |
| [`06_ATTENDANCE_INDIAN_HR_SCENARIOS.md`](./06_ATTENDANCE_INDIAN_HR_SCENARIOS.md) | India-oriented scenarios; marks FUTURE where not supported |
| [`07_ATTENDANCE_GAP_ANALYSIS.md`](./07_ATTENDANCE_GAP_ANALYSIS.md) | Complete today / configurable / stored-unused / architectural / open / future / uncovered edges |
| [`08_ATTENDANCE_OPEN_PRODUCT_DECISIONS.md`](./08_ATTENDANCE_OPEN_PRODUCT_DECISIONS.md) | Open decisions + recommended business rules requiring product sign-off |

**Reading order for product/client review:** README → 01 → 02 → 05 → 03/06 → 04 → 07 → 08.

**Reading order for engineers:** README → 01 (flow) → 02 → 04 (unused fields) → 07 → 05.

---

## Rule classification legend (used in every document)

Every rule is tagged with exactly one category:

| Tag | Meaning |
|---|---|
| **A. CURRENTLY IMPLEMENTED** | Behaviour exists in code today and runs in the calculation / workflow path |
| **B. CONFIGURABLE BY THE USER** | Admin/HR can set it via live API and (where listed) UI; the setting is also consumed by behaviour, unless explicitly marked “stored only” |
| **C. ARCHITECTURALLY DEFINED BUT NOT YET IMPLEMENTED** | Named in architecture / decision log; no working behaviour yet |
| **D. OPEN PRODUCT DECISION** | Explicitly unresolved (PD-* / recommended decisions) |
| **E. FUTURE MODULE RESPONSIBILITY** | Owned by Leave, Payroll, Device, Workflow Engine, or later workforce slices (W10+) |

A field that is **stored and editable** but **not read by the engine** is listed under **B (API/UI)** and immediately flagged **STORED BUT NOT USED** — it is **not** described as working behaviour.

---

## Current W1–W9 status

| Slice | Scope | Status in code |
|---|---|---|
| **W1** | Work Calendar + Holiday Calendar + Weekly-Off + PolicyAssignment (calendar kinds) + day-type resolution | Implemented |
| **W2** | ShiftVersion + Breaks + Duty Blocks (FIXED / FLEXIBLE / SPLIT) | Implemented |
| **W3** | Attendance / Overtime / Regularization policies + assignment + resolution | Implemented (policy storage + publish); engine consumes a **subset** of fields |
| **W4** | Punch + AttendanceDay calculation engine | Implemented |
| **W5** | ShiftRoster (per-employee-date; DRAFT/PUBLISHED; week-off / holiday-working overrides) | Implemented (no rotation generator — deferred W11) |
| **W6** | Regularization request workflow | Implemented (corrections = synthetic punches ± roster shift) |
| **W7** | OvertimeRecord detection sync + approval + caps + comp-off facts | Implemented |
| **W8** | AttendancePeriod OPEN→CLOSED lock + summaries | Implemented (two states only; no persisted CLOSING) |
| **W9** | LeaveDayProjection adapter + leave overlay in engine | Implemented (Attendance-owned mirror; no Leave ledger module) |

**Not in this programme:** full Leave module, Payroll, Device ingestion, generic workflow engine, AttendanceAdjustment, ShiftRotationPattern, money/OT pay calculation.

---

## What is implemented (capability snapshot)

- Employment population gate (`NOT_JOINED` / `ACTIVE` / `EXITED`)
- Assignment as-of (branch, dept, designation, grade, managers, default `shift_id`)
- Calendar day types: `WORKING`, `WEEKLY_OFF`, `HOLIDAY`, `SPECIAL_WORKING`, `SHUTDOWN`
- Shift schedule via published `ShiftVersion` (FIXED / FLEXIBLE / SPLIT) with breaks and duty blocks
- Published roster overrides assignment shift and can force week-off or holiday working
- Attendance / OT / Regularization policy resolution on 8-level scope chain
- Punch ingest (immutable) + day recompute
- Late / early / hour bands / missing punch / multi-punch pairing
- OT detection with min / round / daily·weekly·monthly caps + approval chains + comp-off facts
- Regularization submit / approve / reject / cancel with local chains
- Period validate / finalize / reopen; day-level lock after close
- Leave projection sync/cancel with overlay into `AttendanceDay`

## What is configurable today

Configured via backend APIs; UI screens exist under `/app/*` for calendars, holidays, weekly-off, shifts, rosters, policies, policy assignments, attendance days, regularizations, overtime, attendance periods (see Configuration Catalog). Leave projection is **API-only** (no dedicated nav page).

## What remains future work (high level)

- Leave ledger, balances, accrual, cancel-leave-from-punch
- Payroll consumption of locked summaries / OT pay
- Device punch ingestion pipeline
- Generic workflow engine (ADR-0008 deferred; V1 uses local chains)
- AttendanceAdjustment / arrears after lock
- Shift rotation pattern generator (W11)
- Consuming stored-but-unused policy fields (punch rounding, WFH/ON_DUTY day statuses, night OT windows, late-count→half-day, etc.)

---

## FINAL REPORT (sign-off summary)

### CURRENT ATTENDANCE CAPABILITY

The system can resolve “what kind of day”, “what was scheduled”, “what punches say”, overlay approved leave projections, detect OT, allow regularization corrections, and freeze a company period into payroll-facing day facts + period summaries. Population, timezone, calendar, shift version, and attendance policy are hard prerequisites (fail closed as `CONFIG_ERROR` when calendar or attendance policy is missing).

### CONFIGURATION CAPABILITY

HR/Admin can configure work/holiday calendars, weekly-off patterns, calendar exceptions, shifts (versioned), rosters, three policy families, and policy assignments across EMPLOYEE→COMPANY scopes. Many policy columns are editable today but **not all are consumed** by the engine — see Gap Analysis.

### RULE PRECEDENCE

- **Policies/calendars:** `EMPLOYEE > SHIFT > DESIGNATION > GRADE > DEPARTMENT > BRANCH > LEGAL_ENTITY > COMPANY` (independent walk per `policy_kind`).
- **Schedule shift for a date:** published `ShiftRoster.shift_id` > `EmployeeAssignment.shift_id`.
- **Day type:** CalendarException > holiday union > weekly-off > WORKING.
- **Attendance status overlay order (simplified):** population gate → CONFIG_ERROR → punch/schedule evaluation → leave overlay. Regularization is **not** a status branch; it injects punches/roster then recomputes.
- **Important quirk:** SHIFT **policy** scope uses **assignment** `shift_id`, not the roster-resolved shift.

### MAJOR CONFLICT RULES

- Hard holiday on weekly-off → stays `WEEKLY_OFF` + `holiday_on_weekly_off` (no auto substitute).
- Roster week-off can make a calendar WORKING day `NOT_EXPECTED`.
- Roster holiday-working (or shift `operates_on_*`) can expect presence on holiday/WO.
- Full-day leave overlay typically forces `LEAVE` (or keeps punch outcome + `work_on_leave_flagged` under `PRESENT_CANCEL_LEAVE_HINT`).
- Terminal OT decisions freeze across recompute; pending OT blocks period finalize.

### LOCKING BEHAVIOUR

`AttendancePeriod`: `OPEN` | `CLOSED`. Finalize re-validates, closes, resolves incomplete paid/LOP fractions per policy, snapshots summaries, bulk-locks days. While closed (or day locked): punches, calculate, roster mutation, regularization submit, OT approve/reject, leave sync/cancel are refused. Reopen unlocks days; does **not** auto-recompute.

### LEAVE INTEGRATION

W9 is an Attendance-owned `LeaveDayProjection` mirror + overlay. No leave balances, accrual, or Leave UI. Attendance never cancels leave; it may only flag work-on-leave.

### OVERTIME BEHAVIOUR

Detected as excess over scheduled/required minutes after eligibility, min threshold, rounding, and caps. Approval via `AUTO` / `MANAGER` / `HR` / `MANAGER_THEN_HR`. Comp-off minutes (+ optional expiry date) are facts for Leave/Payroll — no money here. Night classification is incomplete vs policy knobs (see gaps).

### REGULARIZATION

Policy-gated request types and windows; local approval chains; apply path writes `source=REGULARIZATION` punches and optionally publishes a roster shift, then recalculates. Types `WFH` / `ON_DUTY` / `WRONG_STATUS` do **not** write those attendance statuses by themselves.

### KNOWN GAPS (selected)

Punch rounding unused; AUTO_CLOSE missing-punch does not synthesize OUT; WFH/ON_DUTY statuses never emitted; many attendance/OT policy fields stored only; night OT windows unused; `GRADE_VIA_ASSIGNMENT` OT eligibility does not check grade; roster vs SHIFT policy-scope mismatch; half-day leave is flat 0.50 overlay.

### OPEN DECISIONS

See `08_ATTENDANCE_OPEN_PRODUCT_DECISIONS.md` (PD-CAL-1/2, PD-LOCK-1, PD-WFH-1, PD-OT-1, unused-field consumption, leave-after-lock arrears, etc.).

### FUTURE MODULES

Leave, Payroll, Device ingestion, Workflow Engine, AttendanceAdjustment, ShiftRotationPattern (W11), richer night/WFH/flex evaluation.

---

## ATTENDANCE BUSINESS RULE SIGN-OFF CHECKLIST

Review these at product/client level (not every technical column):

1. **Day-type precedence** — exception > holiday > weekly-off > working; holiday-on-WO stays WO (no auto substitute unless explicit exception).
2. **Optional/Restricted holidays** — default working until Leave; WorkCalendar flag may treat as hard holiday.
3. **Shift vs Policy split** — Shift = schedule; Attendance Policy = evaluation; OT Policy = OT; Regularization Policy = correction rules.
4. **Roster beats assignment shift** for schedule; does **not** currently retarget SHIFT-scoped policy resolution.
5. **Fail closed** — missing calendar or attendance policy → `CONFIG_ERROR`; no silent WORKING / default policy.
6. **Missing punch default** — `INCOMPLETE` (not silent ABSENT) unless policy says ABSENT.
7. **Leave overlay** — full-day leave wins status (unless work-on-leave hint mode); Attendance does not manage leave balances.
8. **OT** — detection + approval + caps + comp-off facts only; no pay rates applied as money.
9. **Regularization** — corrections only via punches ± roster shift; no direct status overwrite.
10. **Period lock** — CLOSED freezes mutations; incomplete days resolved to paid/LOP fractions without changing status string; reopen does not auto-recompute.
11. **Stored-but-unused fields** — confirm whether to hide, implement, or drop (rounding, WFH punch rules, night windows, late-count caps, etc.).
12. **India patterns** — alternate Saturdays / nth Saturday / regional holiday calendars are supported via weekly-off rules + holiday calendars; state-specific statutory OT pay is **not** Attendance’s job.

---

## Related architecture docs

- `docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md`
- `docs/architecture/WORKFORCE_ATTENDANCE_DECISION_LOG.md`
- W1–W9 reports under `docs/modules/`



<!-- ============================================================ -->
<!-- SOURCE FILE: 01_ATTENDANCE_BUSINESS_RULES.md -->
<!-- ============================================================ -->

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

### Validate blockers — A

`EMPLOYEES_WITHOUT_ATTENDANCE`, `CONFIG_ERROR`, `INCOMPLETE_ATTENDANCE` (only KEEP_INCOMPLETE), `PENDING_REGULARIZATION`, `PENDING_OVERTIME_APPROVAL`, `UNPUBLISHED_ROSTER`.

### Finalize — A

Re-validate → close → resolve INCOMPLETE paid/lop → snapshot summaries → bulk_lock days.

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



<!-- ============================================================ -->
<!-- SOURCE FILE: 02_ATTENDANCE_PRECEDENCE_MATRIX.md -->
<!-- ============================================================ -->

# 02 — Attendance Precedence Matrix

**Authority:** `PolicyResolutionService`, `CalendarResolutionService`, `AttendanceDayService._build_calculation_input`, `evaluate_day`, period/OT/reg services.

---

## 1. Policy assignment hierarchy (WD-09)

```
EMPLOYEE → SHIFT → DESIGNATION → GRADE → DEPARTMENT → BRANCH → LEGAL_ENTITY → COMPANY
```

**Applies to** independent walks of:

| policy_kind | Resolves |
|---|---|
| WORK_CALENDAR | WorkCalendar |
| WEEKLY_OFF | WeeklyOffPattern (may override calendar’s attached pattern) |
| ATTENDANCE_POLICY | AttendancePolicy + published version as-of date |
| OVERTIME_POLICY | OvertimePolicy + version |
| REGULARIZATION_POLICY | RegularizationPolicy + version |

**Does not apply to:** Shift master identity, roster rows, leave projections, punches, period lock.

### Rules — A / B

| Topic | Behaviour |
|---|---|
| Most specific wins | First scope in order with an effective assignment |
| Independent kinds | Attendance policy resolution does not imply OT policy |
| No match | `config_incomplete=true`; for attendance/calendar → day `CONFIG_ERROR` |
| Overlapping assignments same scope | Prevented / rejected at write (effective dating) |
| Version | Published policy/shift version covering target date |
| SHIFT scope input | **`EmployeeAssignment.shift_id` only** — not roster-resolved shift (**divergence** from architecture comment “including roster”) |

---

## 2. Calendar precedence

| Priority | Rule | Winner | Category |
|---|---|---|---|
| 1 | CalendarException (active) | Exception type → day_type | A / B |
| 2 | Holiday union (first list wins name/type) | HOLIDAY / WORKING_HOLIDAY / soft names | A / B |
| 3 | Weekly-off rules (max off_fraction) | WEEKLY_OFF | A / B |
| 4 | Default | WORKING | A |

Special cases:

| Conflict | Result | Why |
|---|---|---|
| Hard holiday + weekly-off | WEEKLY_OFF + holiday_on_weekly_off | WD-05; no auto substitute (D: PD-CAL-2) |
| CANCEL_HOLIDAY + weekly-off | WEEKLY_OFF | Holiday stripped |
| CANCEL_HOLIDAY + not WO | WORKING | |
| SPECIAL_WORKING vs WO/holiday | SPECIAL_WORKING | Exception wins |
| SHUTDOWN vs anything same date | SHUTDOWN | Exception wins |
| Soft OPTIONAL/RH + flag false | WORKING (+ name fields) | PD-CAL-1 default |
| Soft + flag true | Hard holiday path | B |

Weekly-off PolicyAssignment vs WorkCalendar.weekly_off_pattern_id: assignment WEEKLY_OFF kind wins when resolved for employee (A).

---

## 3. Shift / schedule precedence

| Priority | Source | Effect |
|---|---|---|
| 1 | Published ShiftRoster.shift_id | Schedule for that date |
| 2 | EmployeeAssignment.shift_id | Default schedule |
| — | NULL | No shift → missing_shift_behaviour |

Roster flags (expectation only; do not rewrite calendar_day_type):

| Flag | Effect |
|---|---|
| is_week_off_override | Treat as not expected (even on WORKING calendar) |
| is_holiday_working_override | Expect presence on holiday/WO/shutdown path like operates_on_* |

ShiftVersion `operates_on_holiday` / `operates_on_weekly_off`: schedule-level “this shift works those days” (A / B).

Timezone: ShiftVersion > Branch > Company (A).

---

## 4. Attendance evaluation precedence (status)

Inside `evaluate_day` after inputs resolved:

1. NOT_JOINED / EXITED (population) — absolute  
2. CONFIG_ERROR (no calendar / no attendance policy)  
3. Roster week-off + no punches → NOT_EXPECTED (then leave overlay)  
4. Missing shift branch  
5. Not-expected calendar/roster without operate flags + no punches → NOT_EXPECTED  
6. Punch/schedule evaluation → PRESENT / HALF_DAY / ABSENT / INCOMPLETE (+ late/early)  
7. Leave overlay (may force LEAVE / HALF_DAY / flag)

Regularization: upstream input rewrite, not a status tier.

Late/early ABSENT/HALF_DAY classifications override hour-band PRESENT.

---

## 5. Overtime precedence

| Topic | Rule |
|---|---|
| Eligibility | Policy eligibility + shift flag when SHIFT_FLAG |
| Minutes | After min → round → daily → weekly remaining → monthly remaining |
| Day class | HOLIDAY if worked_on_holiday else WEEKLY_OFF if worked_on_weekly_off else NIGHT (only if is_night ∧ mode∈{WINDOW,BOTH}) else NORMAL |
| Approval | AUTO chain or !requires_post_approval → auto; else PENDING |
| Frozen | Non-PENDING OvertimeRecord not revised by recompute |
| vs Attendance status | OT does not change PRESENT/ABSENT; parallel facts |
| vs Lock | Approve/reject blocked when period closed |

---

## 6. Regularization precedence

| Topic | Rule |
|---|---|
| Allowed | Policy allowed types + actor flags + windows + caps |
| vs Punch | Synthetic punches added; originals immutable |
| vs Roster | May publish/update roster shift |
| vs Day | Full recalculate |
| vs Lock | Submit blocked when locked (default) |
| vs Finalize | SUBMITTED requests block finalize |

---

## 7. Leave precedence

| Topic | Rule |
|---|---|
| vs Calendar | Overlay does not change calendar_day_type |
| vs NOT_EXPECTED | Full-day leave can still become LEAVE |
| vs Punches | KEEP_LEAVE wins status; hint mode keeps punches |
| vs OT | OT computed before overlay on punch path; leave overlay does not wipe OT fields in hint mode; KEEP_LEAVE replaces status but OT columns follow result replace — verify: `_apply_leave_overlay` only replaces listed fields, **does not zero OT** on KEEP_LEAVE path |
| vs Lock | Sync refused when closed |

**Code note (KEEP_LEAVE):** `replace(...)` sets status/paid/lop/late fields; `ot_*` and `worked_minutes` remain from punch-derived result unless callers overwrite later. Product should treat “leave day with residual OT columns” as a known edge — see Gap Analysis.

---

## 8. Period lock precedence

Lock outranks all mutating operational flows for dates in the closed period. Config masters outside the period remain editable. Reopen restores mutability without recalculating.

---

## 9. Master precedence table

| Scenario | Rule 1 | Rule 2 | Winning Rule | Why | Result | Configurable? | Scope | Versioned? | Can override? | Override authority | Locked-period behaviour |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Employee vs Company attendance policy | EMPLOYEE assignment | COMPANY assignment | EMPLOYEE | WD-09 | Employee policy version | Yes | PolicyAssignment | Policy versions | Yes | More specific assignment | Recalc blocked; historical snapshot remains |
| Shift-scope vs Dept policy | SHIFT | DEPARTMENT | SHIFT | WD-09 | Shift-scoped policy | Yes | assignment.shift_id | Yes | Yes | Higher scope | Same |
| Roster shift vs Assignment shift | Roster PUBLISHED | Assignment | Roster | §9.7 | Schedule from roster | Yes | employee-date | Roster status | Yes | Clear/publish roster | Roster mutation blocked |
| Roster vs SHIFT **policy** scope | Roster shift B | Policy assigned to shift A | **Policy still A** | Code uses assignment.shift_id | Possible schedule/policy mismatch | Partial | — | — | Only by changing assignment or SHIFT assignments | — |
| Calendar exception vs holiday | Exception | Holiday | Exception | §6.3 | Exception day_type | Yes | WorkCalendar date | No (deactivate/insert) | Yes | New exception | Recalc blocked |
| Special working vs weekly-off | SPECIAL_WORKING | WO | SPECIAL_WORKING | Exception | Expected working | Yes | Calendar | — | Yes | Cancel exception | — |
| Hard holiday vs weekly-off | Holiday | WO | WEEKLY_OFF + flag | WD-05 | Not expected (unless operate) | Flag/exceptions | Calendar | — | Explicit SUBSTITUTE_HOLIDAY | HR calendar | — |
| Soft RH vs working | RH | Default | WORKING unless flag | PD-CAL-1 | Working | Yes (flag) | WorkCalendar | — | Leave later (E) | — | — |
| Leave full-day vs absence | Leave projection | Zero punches | Leave | Overlay | LEAVE | Leave sync API | Employee-date | Projection status | Cancel projection | Leave adapter | Sync blocked |
| Leave vs holiday type | Leave | HOLIDAY calendar | Both | Calendar unchanged; status LEAVE | LEAVE on HOLIDAY type | — | — | — | — | — | — |
| Punch vs leave KEEP | Punches | Leave | Leave status | work_on_leave | LEAVE | Policy behaviour | Policy | Version | Hint mode | Policy publish | — |
| Regularization vs punch | Synthetic punch | Original punch | Both kept; pairing uses all | Immutable punches | Recalculated day | Reg policy | — | Request | Reject/cancel before apply | Approver | Submit blocked |
| OT vs attendance status | OT minutes | PRESENT | Parallel | WD-07 flags | Status + OT facts | OT policy | — | Version | Reject OT | Approver | Approve blocked |
| Pending OT vs finalize | PENDING OT | Finalize | Finalize blocked | W8 validation | Cannot close | Approval | Period | — | Approve/reject | Manager/HR | N/A |
| Lock vs any mutation | CLOSED | Punch/reg/OT/roster/calc/leave | Lock | WD-30 | Error | UNLOCK permission | Company period | Period version | Reopen | ATTENDANCE.UNLOCK | Mutations denied |

---

## 10. “What can override what?” matrix

| Question | Answer | Why |
|---|---|---|
| Can Employee-specific policy override Company policy? | **YES** | WD-09 |
| Can Shift-specific policy override Department policy? | **YES** | WD-09 |
| Can Roster override EmployeeAssignment shift? | **YES** (schedule) | Published roster |
| Does Roster retarget SHIFT-scoped **policy**? | **NO** (current code) | Uses assignment.shift_id |
| Can Calendar Exception override Holiday? | **YES** | §6.3 |
| Can Special Working Day override Weekly Off? | **YES** | Exception |
| Can Holiday override Weekly Off? | **NO** — WO wins with flag | WD-05 |
| Can Leave override Absence / NOT_EXPECTED? | **YES** (status) | Overlay |
| Can Leave override Holiday day_type? | **NO** | Calendar immutable by leave |
| Can Punch override Leave? | **CONDITIONAL** | Only under PRESENT_CANCEL_LEAVE_HINT (keeps punch status; does not cancel leave) |
| Can Regularization override Punch? | **CONDITIONAL** | Adds punches; cannot delete originals |
| Can OT override Attendance status? | **NO** | Parallel facts |
| Can Period Lock override all mutations? | **YES** (operational) | Closed period / day lock |
| Can DRAFT roster override live schedule? | **NO** | Only PUBLISHED |
| Can soft holiday override working? | **CONDITIONAL** | Only if restricted_holidays_are_off_by_default |



<!-- ============================================================ -->
<!-- SOURCE FILE: 03_ATTENDANCE_SCENARIO_CATALOG.md -->
<!-- ============================================================ -->

# 03 — Attendance Scenario Catalog

Each scenario: **INPUT → RULES → PRECEDENCE → CALCULATION → FINAL → EMPLOYEE VIEW → HR VIEW → PAYROLL FACT → CORRECTION**.  
Behaviour is **current implementation** unless marked FUTURE.

---

### S01 — Normal 9–6 employee
**INPUT:** WORKING; FIXED 09:00–18:00; unpaid break matched 60m; IN 09:00 OUT 18:00; policy PRESENT≥480m.  
**RULES:** Calendar WORKING; shift FIXED; hour band PRESENT.  
**PRECEDENCE:** Standard path.  
**CALCULATION:** Worked ≈ scheduled; late 0; OT 0.  
**FINAL:** PRESENT; paid 1.00; lop 0.  
**EMPLOYEE:** Present day. **HR:** Present. **PAYROLL:** 1 paid day. **CORRECTION:** Reg if needed while open.

### S02 — 10 min late within grace (grace 15)
**INPUT:** IN 09:10.  
**CALCULATION:** late_raw 10 − 15 → late 0.  
**FINAL:** PRESENT (if hours ok); not late.  
**PAYROLL:** 1.00.

### S03 — 40 min late (grace 15; late band 30+ → HALF_DAY)
**INPUT:** IN 09:40.  
**CALCULATION:** late 25 → band HALF_DAY.  
**FINAL:** HALF_DAY; paid 0.50; lop 0.50 (if hours not ABSENT).  
**CORRECTION:** Regularization MISSING/WRONG punch or FULL_DAY.

### S04 — Early departure
**INPUT:** OUT 17:00; grace_out 10; early band → FLAG only.  
**CALCULATION:** early 50.  
**FINAL:** PRESENT + is_early_out (unless band forces HALF/ABSENT).  
**PAYROLL:** per status.

### S05 — Missing OUT
**INPUT:** IN only; missing_punch=INCOMPLETE.  
**FINAL:** INCOMPLETE; paid/lop 0 until lock TREAT_*.  
**EMPLOYEE:** Incomplete / needs regularization. **HR:** Same; blocks finalize if KEEP_INCOMPLETE.

### S06 — Multiple punches IN/OUT/IN/OUT
**INPUT:** PAIR_ALL.  
**CALCULATION:** Sum pair intervals; gaps → breaks.  
**FINAL:** Per worked minutes + bands.

### S07 — Night shift (cross-midnight)
**INPUT:** 22:00–06:00; attendance_date = start date; IN/OUT spanning midnight.  
**FINAL:** Evaluated on start date.  
**OT day_class:** Often NORMAL under default night_ot_mode=SHIFT_FLAG (gap).

### S08 — Cross-midnight ownership
**INPUT:** Work into next civil date.  
**RULE:** All facts on shift-start date.  
**PAYROLL:** One AttendanceDay for start date.

### S09 — Split shift
**INPUT:** Blocks 06–10 and 14–18; punches cover both.  
**FINAL:** PRESENT if hours/bands ok; late/early 0.  
**Missed afternoon block + behaviour HALF_DAY:** HALF_DAY.

### S10 — Weekly-off, no work
**INPUT:** WEEKLY_OFF; no operates; no punches.  
**FINAL:** NOT_EXPECTED; paid 1.00.

### S11 — Holiday, no work
**INPUT:** HOLIDAY; no operate; no punches.  
**FINAL:** NOT_EXPECTED; paid 1.00.

### S12 — Holiday on weekly-off
**INPUT:** Hard holiday Sunday + WO Sunday.  
**FINAL:** calendar WEEKLY_OFF; holiday_on_weekly_off=true; NOT_EXPECTED if no work.

### S13 — Holiday work + OT
**INPUT:** HOLIDAY; operates or roster holiday working; worked > scheduled; OT eligible.  
**CALCULATION:** worked_on_holiday; day_class HOLIDAY; OT detect.  
**FINAL:** PRESENT (typical) + OT PENDING/AUTO.  
**PAYROLL:** paid day + OT minutes/comp-off facts after approval.

### S14 — Paid full-day leave
**INPUT:** Projection fraction 1.00 is_paid true; no punches.  
**FINAL:** LEAVE; paid 1.00; lop 0.  
**Calendar:** unchanged.

### S15 — Unpaid full-day leave
**INPUT:** is_paid false.  
**FINAL:** LEAVE; paid 0; lop 1.00.

### S16 — Half-day leave + half work
**INPUT:** 0.50 paid leave; punches with worked_minutes>0.  
**FINAL:** HALF_DAY; paid ≈ 1.00 if leave paid + work half; lop from unpaid leave only.  
**Note:** Flat 0.50 overlay, not minute-level half-shift.

### S17 — Leave + punches (KEEP_LEAVE)
**INPUT:** Full leave + punches.  
**FINAL:** LEAVE; late cleared; worked_minutes may still show on row.  
**Hint mode:** punch status kept + work_on_leave_flagged.

### S18 — WFH day
**INPUT:** Desire WFH status.  
**CURRENT:** Engine never emits WFH. Regularization type WFH only helps if punches/shift supplied.  
**FUTURE:** Day overlay WD-17.

### S19 — On-duty day
Same as S18 for ON_DUTY.

### S20 — Roster changes shift A→B
**INPUT:** Assignment A; published roster B.  
**PRECEDENCE:** Schedule B.  
**POLICY quirk:** SHIFT-scoped attendance policy still keyed off assignment shift A.

### S21 — Employee requests regularization (missing OUT)
**INPUT:** Type MISSING_PUNCH; within backdate; allowed.  
**FINAL:** SUBMITTED; pending blocks period close.

### S22 — Manager approves regularization
**INPUT:** MANAGER chain; matching reporting_manager_id.  
**CALCULATION:** Synthetic OUT + recalculate → e.g. PRESENT.  
**AUDIT:** RegularizationAction + punch audit + day recompute.

### S23 — HR rejects regularization
**INPUT:** Reject with comment.  
**FINAL:** REJECTED; day unchanged; another request may be allowed per rules.

### S24 — OT requires manager approval
**INPUT:** requires_post_approval + MANAGER; excess OT.  
**FINAL:** OvertimeRecord PENDING; day ot_pending; blocks finalize.

### S25 — OT auto-approved
**INPUT:** approval_chain AUTO or requires_post_approval false.  
**FINAL:** AUTO_APPROVED; minutes_approved = detected.

### S26 — OT rejected
**INPUT:** Reject.  
**FINAL:** REJECTED; frozen; day OT approved minutes 0 path per sync rules.

### S27 — Comp-off earned
**INPUT:** comp_off_instead_of_pay true; OT approved/auto.  
**FINAL:** comp_off_minutes (+ expiry date); Leave redemption FUTURE.

### S28 — Period finalized
**INPUT:** Validation READY.  
**FINAL:** CLOSED; days locked; summaries frozen.  
**CORRECTION:** Not via normal paths; reopen + manual recompute or FUTURE adjustment.

### S29 — Late correction after period close
**INPUT:** Punch/reg after CLOSED.  
**FINAL:** Refused.  
**FUTURE:** AttendanceAdjustment / arrears.

### S30 — Leave arrives after attendance calculation
**INPUT:** Sync projection on open day.  
**FINAL:** Recalculate → LEAVE/HALF_DAY overlay.  
**If locked:** Sync refused.

### S31 — Employee changes department
**INPUT:** New assignment from D.  
**RULES:** Policy resolution uses new dept from D; prior days use old assignment as-of.

### S32 — Branch transfer (timezone)
**INPUT:** New branch TZ.  
**RULES:** TZ from branch unless shift version TZ set; day boundaries follow resolved TZ.

### S33 — Terminated employee
**INPUT:** Date after LWD.  
**FINAL:** EXITED; paid 0; lop 1.

### S34 — Rehired employee
**INPUT:** Gap then new employment.  
**FINAL:** Gap EXITED/NOT_JOINED as applicable; new spell ACTIVE.

### S35 — No assigned shift
**INPUT:** shift_id null; no roster; no punches; missing_shift=INCOMPLETE.  
**FINAL:** INCOMPLETE (or ABSENT if configured).

### S36 — Configuration missing (no calendar/policy)
**FINAL:** CONFIG_ERROR; blocks finalize.

### S37 — Policy change effective next month
**INPUT:** Version A until Aug 31; Version B from Sep 1.  
**RULES:** Each date uses covering published version; unlocked recalc uses current covering version.

### S38 — Holiday calendar changes after calc
**INPUT:** New holiday added; day unlocked.  
**RULES:** Recalc picks new classification. Locked: unchanged until reopen+recalc.

### S39 — Shift version changes
**INPUT:** New published version closes prior effective_to.  
**RULES:** Dates use version covering them; unlocked recalc updates.

### S40 — Employee-specific policy overrides company
**INPUT:** EMPLOYEE scope attendance policy.  
**PRECEDENCE:** Employee wins WD-09.  
**FINAL:** Employee bands/grace apply.

---

## Additional quick scenarios

| ID | Case | Final (typical) |
|---|---|---|
| S41 | Roster week-off on Wednesday | NOT_EXPECTED |
| S42 | SPECIAL_WORKING Sunday | Expected; evaluate punches |
| S43 | SHUTDOWN | NOT_EXPECTED unless forced work |
| S44 | IN IN OUT pairing | Orphan first IN; may INCOMPLETE |
| S45 | Duplicate device IN within 60s | Collapsed |
| S46 | Weekly OT cap exhausted | Detected OT clipped by remaining |
| S47 | Split OT | Uses required_minutes baseline |
| S48 | Finalize with TREAT_ABSENT incompletes | Status INCOMPLETE; paid 0 lop 1; locked |
| S49 | Optional holiday flag false | WORKING |
| S50 | WORKING_HOLIDAY | WORKING + name; expected |



<!-- ============================================================ -->
<!-- SOURCE FILE: 04_ATTENDANCE_CONFIGURATION_CATALOG.md -->
<!-- ============================================================ -->

# 04 — Attendance Configuration Catalog

Only items configurable **today** via backend APIs are listed. UI routes exist where noted.  
**Consumed** = used by calculation/workflow. **Stored only** = editable but unused by engine.

Who can configure: holders of `ATTENDANCE.POLICY_MANAGE`, `ORG.SHIFT.MANAGE`, `ATTENDANCE.ROSTER_MANAGE`, `ATTENDANCE.LOCK` / `UNLOCK`, calendar/org manage permissions as seeded for company admin — exact RBAC is role×permission×data_scope.

---

## 1. Calendar

| Setting | Description | Values | Default | Scope | Effective | Versioned? | UI | Affects | Overrides / overridden by | Consumed? |
|---|---|---|---|---|---|---|---|---|---|---|
| WorkCalendar identity | Name/code/active | strings/bool | — | Company | Immediate | Optimistic version | `/app/work-calendars` | Resolution target | PolicyAssignment | Yes |
| weekly_off_pattern_id | Pattern link | UUID/null | null | WorkCalendar | When resolved | No | Yes | WO classification | WEEKLY_OFF PolicyAssignment may replace | Yes |
| restricted_holidays_are_off_by_default | Soft holidays hard? | bool | false | WorkCalendar | Next classify/recalc | No | Yes | OPTIONAL/RH | Exceptions | Yes |
| Holiday calendar composition | Ordered calendars | join rows | — | WorkCalendar | Next classify | Replace | Yes | Holiday union | First list wins ties | Yes |
| CalendarException | Dated override | SHUTDOWN, SPECIAL_WORKING, SUBSTITUTE_HOLIDAY, CANCEL_HOLIDAY | — | WorkCalendar+date | That date | Deactivate+insert | Yes | day_type | Wins over holiday/WO | Yes |

## 2. Holiday

| Setting | Description | Values | Default | Scope | UI | Consumed? |
|---|---|---|---|---|---|---|
| HolidayCalendar | Named calendar, year/state optional fields as implemented | — | Company | `/app/holiday-calendars` | Yes via composition |
| Holiday.date/name | Dated holiday | date, string | — | Calendar | Yes | Yes |
| holiday_type | PUBLIC, COMPANY, OPTIONAL, RESTRICTED, WORKING_HOLIDAY | — | — | Yes | Yes |

## 3. Weekly Off

| Setting | Description | Values | Default | UI | Consumed? |
|---|---|---|---|---|---|
| WeeklyOffPattern | Identity | name/code | `/app/weekly-off-patterns` | Yes |
| WeeklyOffRule.weekday | Mon=0…Sun=6 | 0–6 | — | Yes | Yes |
| nth_in_month | Nth or last (−1) | int/null | null | Yes | Yes |
| cycle_start_date / week_parity | Alternate weeks | date, EVEN/ODD | parity default EVEN | Yes | Yes |
| off_fraction | Partial off | decimal | 1 | Yes | Stored; day_type still WO when off |

## 4. Shift

| Setting | Description | Values | UI | Consumed? |
|---|---|---|---|---|
| Shift identity | name/code/active | `/app/shifts` | Identity only for assignment/roster |
| ShiftVersion.shift_type | FIXED/FLEXIBLE/SPLIT | Yes | Yes |
| start/end or window_* or duty blocks | Schedule | Yes | Yes |
| required_minutes | FLEX/SPLIT baseline | Yes | Yes (OT/SPLIT) |
| is_cross_midnight / is_ot_eligible / operates_on_* | Flags | Yes | Yes (night OT uses cross-midnight) |
| is_night_shift | Flag | Yes | **Stored only** for OT classify (engine uses is_cross_midnight) |
| timezone | IANA | Yes | Yes (highest TZ priority) |
| core_start/end | Flex core | Yes | **Stored only** |
| Breaks (kind, paid, max, windows) | Break definition | Yes | Partial (mandatory/min unused) |
| Publish version | DRAFT→PUBLISHED | Yes | Yes |

Legacy Shift grace/half-day fields: **not consumed** by W4 engine.

## 5. Roster

| Setting | Description | Values | Default | UI | Consumed? |
|---|---|---|---|---|---|
| shift_id | Override shift | UUID/null | null | `/app/rosters` | Yes if PUBLISHED |
| is_week_off_override | Force off | bool | false | Yes | Yes |
| is_holiday_working_override | Force work on holiday/WO | bool | false | Yes | Yes |
| status | DRAFT/PUBLISHED | DRAFT | Yes | Only PUBLISHED in calc; DRAFT blocks finalize |

## 6. Attendance Policy

| Setting | Consumed? | Notes |
|---|---|---|
| grace_in/out_minutes | Yes | |
| missing_punch_behaviour | Yes | AUTO_CLOSE incomplete |
| missing_shift_behaviour | Yes | |
| multi_punch_mode | Yes | |
| duplicate_punch_window_seconds | Yes | |
| split_shift_missed_block_behaviour | Yes | |
| work_on_leave_behaviour | Yes | |
| incomplete_at_lock_behaviour | Yes (finalize) | |
| hour / late / early bands | Yes | counts_toward_cap **No** |
| punch_rounding, rounding_minutes | **No** | Stored only |
| half_day_split, half_day_boundary_minutes | **No** | |
| core_hours_*, early_out_uses_core_end | **No** | |
| excess_break_behaviour | **No** | |
| auto_close_* | **No** | |
| split_shift_block_mandatory, allow_hours_compensation | **No** | |
| wfh_*/on_duty_* punch flags | **No** | |
| late_count_window, lates_to_half_day_count | **No** | |
| early_departure_requires_approval | **No** | |

UI: `/app/attendance-policies`. Scope via `/app/policy-assignments`. Effective dating on versions. Publish required.

## 7. Overtime Policy

| Setting | Consumed? |
|---|---|
| eligibility | Yes (GRADE path incomplete) |
| min_ot_minutes, rounding_*, daily/weekly/monthly caps | Yes |
| requires_post_approval, approval_chain | Yes |
| comp_off_instead_of_pay, comp_off_expiry_days | Yes (facts) |
| rate rows day_class → classification + multiplier | classification Yes; multiplier snapshot only (no money) |
| requires_pre_approval | **No** |
| night_ot_mode | Partial (see Business Rules) |
| night_window_start/end | **No** |

UI: `/app/overtime-policies`.

## 8. Regularization Policy

| Setting | Consumed? |
|---|---|
| allow_*_request | Yes |
| max_backdated_days, max_requests_per_month | Yes |
| reason_required, attachment_required | Yes |
| approval_chain | Yes |
| blocked_when_locked | Yes |
| allowed types | Yes |
| auto_approve_within_minutes | **No** |

UI: `/app/regularization-policies`.

## 9. Policy Assignment

| Setting | Values | UI | Consumed? |
|---|---|---|---|
| policy_kind | WORK_CALENDAR, WEEKLY_OFF, ATTENDANCE_POLICY, OVERTIME_POLICY, REGULARIZATION_POLICY | `/app/policy-assignments` | Yes |
| scope_type / scope_id | 8 scopes | Yes | Yes |
| effective_from / effective_to | dates | Yes | Yes |

Resolution preview: `/app/policy-resolution`.

## 10. Leave Projection

| Setting/API | Description | UI | Consumed? |
|---|---|---|---|
| POST sync projection | fraction, half, is_paid, leave_application_id | **No dedicated page** | Yes |
| Cancel | status CANCELLED | No | Yes |

Configurable by integration caller with `ATTENDANCE.LEAVE_PROJECTION_SYNC`, not end-user Leave admin (E).

## 11. Period Lock

| Setting | Description | UI | Consumed? |
|---|---|---|---|
| period_start/end, label | Create OPEN period | `/app/attendance-periods` | Yes |
| validate / finalize / reopen | Lifecycle | Yes | Yes |
| legal_entity_id | Reserved null | — | Not used (company grain) |

---

## Defaults that matter operationally

- missing_punch_behaviour = INCOMPLETE  
- incomplete_at_lock_behaviour = TREAT_ABSENT  
- work_on_leave_behaviour = KEEP_LEAVE  
- OT requires_post_approval = true, approval_chain = MANAGER  
- restricted_holidays_are_off_by_default = false  
- duplicate_punch_window_seconds = 60  
- multi_punch_mode = PAIR_ALL  



<!-- ============================================================ -->
<!-- SOURCE FILE: 05_ATTENDANCE_CONFLICT_SCENARIOS.md -->
<!-- ============================================================ -->

# 05 — Attendance Conflict Scenarios

For each conflict: winning rule, status, worked minutes, paid/LOP, OT, actor views, correction, recalc, audit.

Legend answers use **current code**.

---

## 1. Calendar conflicts

### C1 — Holiday + Weekly Off
1. Rule: WD-05 hard holiday on WO. 2. Priority: WO wins type. 3. Status: NOT_EXPECTED (no work). 4–6. Worked 0; paid 1; lop 0. 7. OT 0. 8–9. Employee/HR see WEEKLY_OFF + holiday flag. 10. Correction: exception SUBSTITUTE if needed. 11. Recalc if unlocked. 12. Audit on calendar mutate only.

### C2 — Holiday + Roster Working
1. roster_holiday_working_override or operates_on_holiday. 2. Expectation override wins vs not_expected. 3. Evaluated PRESENT/…. 4. Worked from punches. 5–6. Per status. 7. OT may classify HOLIDAY if worked_on_holiday. 8–9. Working holiday attendance. 10. Reg/roster while open. 11. Yes on change. 12. Roster + day audit.

### C3 — Holiday + Roster Off
1. Week-off override. 2. Override expectation. 3. NOT_EXPECTED if no punches. 4–7. 0 / paid 1. 8–9. Off. 10–12. Roster edits while open.

### C4 — Holiday + Leave
1. Leave overlay + calendar HOLIDAY. 2. Status LEAVE; type HOLIDAY. 3. LEAVE. 4. Usually 0. 5–6. From leave paid flags. 7. OT columns may residual — see gap. 8–9. Leave on holiday date. 10. Cancel projection / leave module FUTURE. 11. Sync triggers calc. 12. Projection audit.

### C5 — Holiday + Punch (no operate)
1. Punches on not-expected day without operate → still evaluated (not short-circuit NOT_EXPECTED). 2. Presence path. 3. PRESENT/INCOMPLETE/…. 4. Worked >0. 5–6. Per status. 7. May set worked_on_holiday + OT. 8–9. Worked on holiday. 10. Reg. 11. Yes. 12. Punch audit.

---

## 2. Shift / roster conflicts

### C6 — Assignment Shift A + Roster Shift B
Winner: **B for schedule**. Policy SHIFT scope may still be A. Status per B schedule. Recalc on publish. Audit roster.

### C7 — Roster Shift + Holiday
Calendar HOLIDAY unchanged; expectation via operate/override. See C2/C5.

### C8 — Roster Shift + Weekly Off
Same pattern as holiday.

### C9 — Roster Shift + Leave
Leave overlay after schedule eval. Full leave → LEAVE.

### C10 — Roster + Regularization WRONG_SHIFT
Approval may publish roster to requested_shift_id then recalc. Winner: applied roster + synthetic punches.

---

## 3. Attendance conflicts

### C11 — Late + Leave (KEEP)
Leave wins status; late zeroed.

### C12 — Late + WFH
WFH status not produced; late rules N/A for WFH overlay.

### C13 — Late + Regularization
After approve, new punches recalc late.

### C14 — Early + Leave
Same as late under KEEP_LEAVE.

### C15 — Early + OT
Early reduces worked; OT from remaining excess only.

### C16 — Missing Punch + Leave
Full leave → LEAVE (even if incomplete punches). Half leave + missing → HALF_DAY or LEAVE per work minutes.

### C17 — Missing Punch + Regularization
Intended path: add OUT/IN via request → PRESENT/….

### C18 — Multi-punch + Regularization
Adds more punches; pairing uses full set; duplicates may collapse.

---

## 4. OT conflicts

### C19 — Holiday + OT
day_class HOLIDAY when worked_on_holiday.

### C20 — Weekly-off + OT
day_class WEEKLY_OFF when worked_on_weekly_off.

### C21 — Leave + OT
KEEP_LEAVE does not clear OT fields in overlay replace — **edge**. Product should decide.

### C22 — Night + OT
Classification NIGHT only under WINDOW/BOTH + is_cross_midnight; windows unused.

### C23 — Split + OT
OT vs required_minutes; late not computed.

### C24 — OT + Lock
Approve/reject blocked; pending blocks finalize.

### C25 — OT + Regularization
Recalc may change detected OT if still PENDING; terminal OT frozen (WD-29).

---

## 5. Leave conflicts

### C26 — Leave + Holiday — See C4
### C27 — Leave + Weekly Off — Status LEAVE; type WEEKLY_OFF
### C28 — Leave + Punch — KEEP vs HINT
### C29 — Leave + WFH — WFH not implemented
### C30 — Leave + Regularization — Reg still punch-based; leave overlay reapplies after calc
### C31 — Leave + OT — See C21
### C32 — Leave + Lock — Sync refused

---

## 6. Period conflicts

### C33 — Regularization + Finalization
SUBMITTED → BLOCKED finalize. Approve/reject first.

### C34 — OT Approval + Finalization
PENDING OT → BLOCKED.

### C35 — Punch + Finalization
Missing days → EMPLOYEES_WITHOUT_ATTENDANCE. After CLOSED punches refused.

### C36 — Roster Change + Finalization
DRAFT roster → UNPUBLISHED_ROSTER blocker. After close, mutation refused.

### C37 — Leave Projection + Finalization
Not a named blocker by itself; affects day status. After close, sync refused. CONFIG_ERROR/INCOMPLETE still apply.

---

## 7. Matrix (compact)

| ID | Winner | Status | Worked | Paid/LOP | OT | Emp/HR see | Correct? | Recalc? | Audit? |
|---|---|---|---|---|---|---|---|---|---|
| C1 Holiday+WO | WO type | NOT_EXPECTED | 0 | 1/0 | 0 | WO+flag | Exception | if open | calendar |
| C2 Hol+Roster work | Expectation | Present-like | >0 | per status | HOLIDAY class | worked holiday | Yes open | Yes | roster/day |
| C6 A vs B roster | Roster sched | per B | per B | per | per | Shift B | Yes | Yes | roster |
| C11 Late+Leave | Leave | LEAVE | may remain | leave | residual? | Leave | Leave/reg | Yes | leave/day |
| C17 Miss+Reg | Reg punches | Present-like | fixed | per | per | Corrected | Via reg | On approve | reg+punch |
| C24 OT+Lock | Lock | unchanged | — | — | frozen/block | Locked | Reopen/FUTURE | No while closed | period |
| C33 Reg+Finalize | Validation | — | — | — | — | Blocked close | Resolve regs | — | period validate |



<!-- ============================================================ -->
<!-- SOURCE FILE: 06_ATTENDANCE_INDIAN_HR_SCENARIOS.md -->
<!-- ============================================================ -->

# 06 — Attendance Indian HR Scenarios

Documents realistic Indian HRMS needs against **current** W1–W9 support.  
Unsupported items are marked **FUTURE / NOT CURRENTLY IMPLEMENTED**.

---

## Supported today (with configuration)

### I1 — Monday–Saturday working week
Configure weekly-off Sunday only (FIXED weekday). Calendar WORKING Mon–Sat. **Supported (A/B).**

### I2 — Alternate Saturdays off
WeeklyOffRule: Saturday + cycle_start_date + week_parity. **Supported (A/B).**

### I3 — 1st/3rd/5th Saturday off
nth_in_month 1 and 3 (and 5 when exists) on Saturday rules. **Supported (A/B).** Last Saturday: nth=-1.

### I4 — State / company holiday calendars
Multiple HolidayCalendars composed into WorkCalendars; PolicyAssignment per branch/employee. **Supported (A/B).**

### I5 — Kerala vs Maharashtra calendars
Two HolidayCalendars + two WorkCalendars assigned by BRANCH or EMPLOYEE. **Supported (A/B).** No built-in statutory pack — HR loads dates.

### I6 — Night / manufacturing shifts
FIXED cross-midnight ShiftVersion; roster for rotating crews. **Schedule supported.** Night OT classification incomplete (see gaps).

### I7 — IT flex schedules
FLEXIBLE shift_type + required_minutes + window. **Partial:** core-hours breach unused.

### I8 — Grace late coming / early going
Attendance policy grace + bands. **Supported.**

### I9 — Half-day by hours
Hour bands (e.g. 240–479 → HALF_DAY). **Supported.** half_day_boundary_minutes unused.

### I10 — LOP
lop_fraction on ABSENT/HALF_DAY/unpaid leave; lock TREAT_ABSENT. **Supported as fractions.** Payroll money **FUTURE (E).**

### I11 — Holiday / weekly-off OT
Work with operate/roster + OT policy rate rows day_class HOLIDAY/WEEKLY_OFF. **Detection + classification supported.** Pay multiplier not applied as money (ADR-0006).

### I12 — Comp-off fact
OT policy comp_off_instead_of_pay + expiry days. **Fact supported.** Balance/ledger/redemption **FUTURE Leave (E).**

### I13 — Half-day leave
LeaveDayProjection 0.50 + half FIRST/SECOND. **Projection supported**; FIRST/SECOND not used to split shift minutes (flat overlay).

### I14 — Multiple / biometric punches
Punch source DEVICE/IMPORT; duplicate window; PAIR_ALL. **Supported.** Full device gateway **FUTURE (E / ADR-0007).**

### I15 — Manager approvals
Local chains for regularization and OT. **Supported (WD-08).** Generic workflow engine **FUTURE.**

### I16 — Payroll period closing
AttendancePeriod finalize + summaries. **Supported at attendance grain.** Payroll import **FUTURE (E).**

### I17 — WFH / Hybrid placement
Assignment work_location_type exists. **Not attendance status.** Auto WFH **NOT IMPLEMENTED (D: PD-WFH-1).**

### I18 — On-duty / outdoor duty
Regularization type exists; status ON_DUTY **not emitted**. **NOT FULLY IMPLEMENTED.**

### I19 — Holiday substitute when festival on Sunday
Manual CalendarException SUBSTITUTE_HOLIDAY (+ CANCEL optional). **Supported manually.** Auto-substitute **NOT IMPLEMENTED (D: PD-CAL-2).**

### I20 — Optional / restricted holidays
Soft holidays default working; flag or Leave later. **Partial:** Leave application UX **FUTURE.**

---

## Explicitly NOT currently implemented

| Need | Status |
|---|---|
| Statutory OT wage calculation (2x etc. hardcoded) | Forbidden (ADR-0006/0011); multipliers informational only |
| PF/ESI/professional tax from attendance | E Payroll/Statutory |
| Leave balances, sandwich leave rules, CL/SL/PL ledgers | E Leave |
| Encashment | E |
| Geo-fencing enforcement on punch | Fields on branch exist historically; attendance punch geofence **not W4 behaviour** |
| Face/biometric vendor connectors | E Device |
| Arrears after payroll lock | E AttendanceAdjustment |
| Shift rotation auto-generator | C/W11 |
| Intra-day shift change | D: PD-SHIFT-1 not supported |
| Late-count → half-day (N lates/month) | Stored fields unused |
| Punch time rounding to nearest 15 min | Stored unused |

---

## Example month (India-flavoured)

Company: Mon–Fri + 1st/3rd Saturday off; Maharashtra holiday calendar; FIXED 09:30–18:30; grace 15; OT post-approval manager; period calendar month.

| Date | Event | Expected system |
|---|---|---|
| Working Tue | Normal punches | PRESENT |
| 1st Sat | WO rule | NOT_EXPECTED |
| Ganesh Chaturthi | HOLIDAY | NOT_EXPECTED |
| Festival on Sunday | WO + holiday flag | WEEKLY_OFF; HR adds Monday SUBSTITUTE if policy |
| Engineer flex | FLEXIBLE version | Hours vs required_minutes / window |
| Plant night | Cross-midnight | Day on start date |
| OT Diwali week | Caps + PENDING | Finalize blocked until approve |
| Month end | Finalize | Summaries frozen for payroll handoff |



<!-- ============================================================ -->
<!-- SOURCE FILE: 07_ATTENDANCE_GAP_ANALYSIS.md -->
<!-- ============================================================ -->

# 07 — Attendance Gap Analysis

Honest inventory after code review. Do not treat stored fields as working features.

---

## 1. COMPLETE TODAY

- Employment population gate; assignment as-of; rehire/terminate date behaviour
- WorkCalendar + HolidayCalendar + WeeklyOffPattern + Exceptions + day classification
- PolicyAssignment + 8-level resolution for calendar and three attendance policy families
- ShiftVersion FIXED/FLEXIBLE/SPLIT with breaks & duty blocks; publish/effective dating
- ShiftRoster PUBLISHED overrides + week-off / holiday-working flags
- Punch ingest (immutable) + AttendanceDay calculate/recompute
- Multi-punch collapse/pairing; PAIR_ALL / FIRST_IN_LAST_OUT
- Grace + hour/late/early bands (consumed subset)
- OT detection (min/round/daily/weekly/monthly) + OvertimeRecord approval + comp-off facts
- Regularization workflow (local chains) applying punches ± roster shift
- AttendancePeriod OPEN/CLOSED validate/finalize/reopen + summaries + day lock
- LeaveDayProjection sync/cancel + leave overlay
- Permissions catalogue ATTENDANCE.* operational + POLICY_MANAGE
- UI for calendars, shifts, rosters, policies, attendance, reg, OT, periods

---

## 2. CONFIGURABLE TODAY

See `04_ATTENDANCE_CONFIGURATION_CATALOG.md`.  
Includes many fields that are **editable but unused** — still “configurable” in the API/UI sense, but **not behavioural**.

---

## 3. STORED BUT NOT USED (critical)

### AttendancePolicyVersion
punch_rounding, rounding_minutes, half_day_split, half_day_boundary_minutes, core_hours_breach_behaviour, early_out_uses_core_end, excess_break_behaviour, auto_close_after_minutes, auto_close_uses_shift_end, split_shift_block_mandatory, split_shift_allow_hours_compensation, wfh_requires_punch, on_duty_requires_punch, wfh_uses_shift_hours, late_count_window, lates_to_half_day_count, early_departure_requires_approval.

### Bands
counts_toward_cap on late/early bands.

### OvertimePolicyVersion
requires_pre_approval; night_window_start/end; GRADE_VIA_ASSIGNMENT without grade logic; night_ot_mode=SHIFT_FLAG never yields NIGHT class.

### RegularizationPolicyVersion
auto_approve_within_minutes.

### Shift / ShiftVersion / Breaks
Legacy Shift grace/thresholds; ShiftVersion core_*; ShiftBreak is_mandatory, min_minutes, allows_split, crosses_midnight (matching limited); is_night_shift flag unused for classify.

### Schema statuses
ON_DUTY, WFH never emitted.

### Engine helpers
apply_rounding defined but never called in evaluate path; auto_closed always false.

### Misc quirks
is_regularized cleared on calculate; roster shift ignored for SHIFT policy scope; leave KEEP_LEAVE does not zero OT columns.

---

## 4. ARCHITECTURALLY DEFINED BUT NOT IMPLEMENTED

| Item | Reference |
|---|---|
| ShiftRotationPattern generator | W11 / WD-27 |
| AttendanceAdjustment / post-lock arrears | WD-18 |
| Generic workflow engine | ADR-0008 deferred; WD-08 V1 local |
| Partitioned punch/attendance_day | WD-26 deferred |
| Auto-deduct scheduled break without gap | §10.2 DEDUCT_SCHEDULED never columned |
| WFH/ON_DUTY day overlays | WD-17 |
| Device ingestion deployable | ADR-0007 |
| Legal-entity period grain usage | legal_entity_id reserved null; PD-LOCK-1 |
| Minute-accurate half-day leave half-of-shift | §19.4 simplified |

---

## 5. OPEN PRODUCT DECISIONS

See `08_ATTENDANCE_OPEN_PRODUCT_DECISIONS.md` (PD-CAL-*, PD-LOCK-1, PD-WFH-1, unused-field fate, leave+OT residual, roster vs SHIFT policy scope, night OT semantics).

---

## 6. FUTURE MODULES

| Module | Owns |
|---|---|
| Leave | Applications, balances, accrual, sandwich rules, redeem comp-off, cancel-leave-from-work |
| Payroll | Money, OT pay, LOP deduction amounts, payslip from frozen summaries |
| Device | Biometric connectors, clock servers |
| Workflow Engine | Long-term replacement for local approval chains |
| Workforce W10+ | Adjustments, richer analytics, rotation generator |

---

## 7. POTENTIAL EDGE CASES NOT YET COVERED / WEAK

1. Soft holiday + punches + no leave (working day with optional name only).  
2. Half-day leave FIRST vs SECOND (stored, not schedule-scoped).  
3. Multiple overlapping leave projections prevented by sum≤1 but UX not productized.  
4. OT on leave day residual minutes.  
5. Recompute after terminal OT with changed punches (OT frozen; day may disagree).  
6. Concurrent roster update during reg apply (documented weak race).  
7. FLEX lateness vs “core hours” expectations.  
8. SPLIT partial block credit.  
9. Unmatched unpaid gaps in FIRST_IN_LAST_OUT vs paid break add-back.  
10. Holiday work without operates_on / roster override (still evaluates if punches exist).  
11. Weekly off_fraction < 1 (day still classified WEEKLY_OFF; fraction not used in paid_day).  
12. Period reopen without forced recompute → stale locked facts until manual calc.  
13. Employee visible “is_regularized” unreliable across recalc.  
14. Night OT product meaning vs SHIFT_FLAG bug/gap.  
15. Config change mid-period with partial recalculation of only some employees.

---

## 8. Doc vs code contradictions (index)

| Claim | Reality |
|---|---|
| Architecture SHIFT scope includes roster | Code uses assignment.shift_id |
| Punch rounding policy | Not applied |
| AUTO_CLOSE missing punch | No synthetic OUT |
| Night OT WINDOW | Windows unused; SHIFT_FLAG never NIGHT class |
| GRADE_VIA_ASSIGNMENT | No grade check |
| WFH/ON_DUTY statuses | Never emitted |
| Period CLOSING state | Not persisted (OPEN/CLOSED only) |
| Permission REGULARISE_* spelling | Code REGULARIZATION_* |
| Mandatory break auto-deduct | Not implemented |
| incomplete_at_lock changes status | Only paid/lop fractions |



<!-- ============================================================ -->
<!-- SOURCE FILE: 08_ATTENDANCE_OPEN_PRODUCT_DECISIONS.md -->
<!-- ============================================================ -->

# 08 — Open Product Decisions & Recommended Business Rules

This document separates **current behaviour** from **recommendations**.  
Recommendations do **not** change architecture silently; they require product sign-off before implementation.

---

## Part A — Existing open decisions (from architecture §32 / decision log)

| ID | Topic | Current default in code | Notes |
|---|---|---|---|
| PD-CAL-1 | Optional/RH off-by-default vs working-until-Leave | Working until Leave; WorkCalendar flag can harden | Flag implemented |
| PD-CAL-2 | Auto-substitute holiday on WO | No auto-substitute | Manual exceptions only |
| PD-APR-1 | Approver as-of attendance date vs current | As-of attendance date (assignment on that date) | Implemented for manager snapshot |
| PD-POL-1 | Configurable engine precedence in V1 | Engine order locked | Do not expose reorder UI |
| PD-POL-2 | Keep grace on Shift as well | Evaluation grace on Attendance Policy only | Legacy Shift columns unused by engine |
| PD-SHIFT-1 | Intra-day shift change | Not supported | One schedule per attendance date |
| PD-LOCK-1 | Lock grain LE vs company | Company period; legal_entity_id unused | |
| PD-WFH-1 | Auto WFH from assignment location | No | |
| PD-OT-1 | OT post-approval default | requires_post_approval=true | |
| PD-SCOPE-1 | Branch HR without BRANCH scope | COMPANY for HR roles (RBAC reality) | |
| PD-BR14-SHIFT | Default-shift cascade | Still deferred (DEC-018) | NULL shift fail-closed path |

---

## Part B — New decisions surfaced by implementation audit

### ND-01 — Fate of stored-but-unused policy fields

**Problem:** Many W3 fields are editable in UI but ignored by the engine → false confidence.  
**Choices:** (1) Implement behaviour, (2) Hide/disable in UI until implemented, (3) Remove columns later.  
**Recommended:** (2) short-term + backlog for true product needs (rounding, late-count, WFH).  
**Impact:** Employees—none until implemented; HR—honest config; Payroll—fewer surprise gaps.  
**Implementation:** UI/docs first; no silent engine guesses.

### ND-02 — Roster vs SHIFT policy scope

**Problem:** Roster changes schedule but SHIFT-scoped policies still key off assignment.shift_id.  
**Choices:** (1) Resolve SHIFT scope using roster shift for that date, (2) Document as intentional, (3) Disallow SHIFT scope.  
**Recommended:** (1) align with architecture comment “shift resolved for that date, including roster”.  
**Impact:** Correct policy when people temporarily change shift; HR fewer mismatches.  
**Implementation:** Change `_scope_candidates` / policy resolution input only; record WD entry.

### ND-03 — Night OT classification

**Problem:** Default `night_ot_mode=SHIFT_FLAG` never emits day_class NIGHT; windows unused.  
**Choices:** (1) Fix classify so SHIFT_FLAG + is_cross_midnight → NIGHT, (2) Implement WINDOW properly, (3) Drop NIGHT class until designed.  
**Recommended:** (1) + document WINDOW as future; keep no money.  
**Impact:** Correct OT classification for night plants; payroll handoff clearer.  
**Implementation:** One-line classify fix + tests; WINDOW later.

### ND-04 — Leave overlay residual OT / worked minutes

**Problem:** KEEP_LEAVE sets status LEAVE but leaves worked_minutes/OT fields from punch path.  
**Choices:** (1) Zero OT/worked on KEEP_LEAVE, (2) Keep as audit of presence on leave, (3) Force hint mode only when punches exist.  
**Recommended:** (1) for payroll-facing columns; retain raw punches immutable.  
**Impact:** Cleaner payroll facts; HR still sees punches separately.  
**Implementation:** Extend `_apply_leave_overlay` replace fields; snapshot retains detail.

### ND-05 — AUTO_CLOSE missing punch

**Problem:** Enum value suggests auto OUT; code does not create one.  
**Choices:** (1) Implement synthetic OUT at shift end / after N minutes, (2) Remove/rename enum, (3) Map AUTO_CLOSE → INCOMPLETE in UI.  
**Recommended:** (3) now; (1) only if clients demand with explicit rules.  
**Impact:** Avoid HR believing days auto-closed.  

### ND-06 — WFH / ON_DUTY

**Problem:** Types and statuses promised; engine never produces statuses.  
**Choices:** (1) Implement WD-17 overlays, (2) Remove from allowed regularization until ready, (3) Map WFH reg to punches-only documentation.  
**Recommended:** (2) in product copy + (1) scheduled slice.  
**Impact:** Honest employee/manager expectations.

### ND-07 — GRADE_VIA_ASSIGNMENT OT eligibility

**Problem:** Behaves like ALWAYS.  
**Choices:** (1) Implement grade flag/table, (2) Remove enum value, (3) Alias to ALWAYS in docs.  
**Recommended:** (2) or implement (1) if grade OT is a real India manufacturing need.  

### ND-08 — Period reopen recompute policy

**Problem:** Reopen unlocks without recalc → stale days possible.  
**Choices:** (1) Mandatory bulk recompute on reopen, (2) Explicit HR action checklist, (3) Version stamp “stale” flag.  
**Recommended:** (2) for V1; (1) optional gated job.  
**Impact:** Payroll safety after unlock.

### ND-09 — Half-day leave FIRST/SECOND

**Problem:** Stored but not used to limit evaluation window.  
**Choices:** (1) Evaluate only that half of shift, (2) Keep flat 0.50, (3) Drop half enum.  
**Recommended:** Keep (2) documented until Leave module defines contract; then (1).  

### ND-10 — Post-lock corrections

**Problem:** No AttendanceAdjustment; reopen is blunt.  
**Choices:** (1) Build WD-18 adjustment with payroll arrears, (2) Always reopen+recalc, (3) Manual payroll only.  
**Recommended:** (1) before first paid customer close.  

---

## Part C — Recommended Business Rules Requiring Product Decision

Format: Problem → Choices → Recommended → Why → Impacts → Implementation consequence.

### R1 — Holiday on weekly-off stays WO
**Problem:** Clients often expect next-day substitute automatically.  
**Choices:** Keep WD-05; or auto-create SUBSTITUTE.  
**Recommended:** Keep WD-05; provide HR playbook for exception pairs.  
**Why:** Matches locked decision; avoids silent calendar mutation.  
**Employees:** No surprise off; HR: manual substitute.  
**Payroll:** Predictable NOT_EXPECTED.  
**Impl:** None (docs/training).

### R2 — Fail closed on missing calendar/policy
**Problem:** Temptation to default WORKING/PRESENT.  
**Recommended:** Keep CONFIG_ERROR.  
**Why:** WD-21; wrong paid days worse than blocked close.  
**Impl:** None.

### R3 — Missing punch defaults to INCOMPLETE not ABSENT
**Recommended:** Keep default INCOMPLETE; ABSENT explicit.  
**Why:** Architecture §11.5.  
**Impl:** None.

### R4 — Regularization never deletes punches
**Recommended:** Keep additive punches only.  
**Why:** WD-18/WD-28 auditability.  
**Impl:** None.

### R5 — OT never computes money
**Recommended:** Keep facts + informational multiplier only.  
**Why:** ADR-0006.  
**Impl:** Payroll module later.

### R6 — Align SHIFT policy scope with roster
See ND-02 — **recommended change** after sign-off.

### R7 — Honest config surface
See ND-01 — hide unused fields until behaviour exists.

### R8 — Night OT semantics
See ND-03 — fix SHIFT_FLAG classification after sign-off.

### R9 — Leave day payroll columns
See ND-04 — zero OT/worked on KEEP_LEAVE after sign-off.

### R10 — Comp-off redemption is Leave’s job
**Recommended:** Attendance only emits facts (current).  
**Why:** ADR-0004.  
**Impl:** Leave module.

---

## Part D — Sign-off package (business, not technical)

Ask the client/product owner to confirm:

1. Calendar conflict rules (esp. holiday-on-WO, optional holidays).  
2. Shift vs Policy vs OT vs Regularization split.  
3. Fail-closed CONFIG_ERROR.  
4. INCOMPLETE vs ABSENT philosophy.  
5. Leave overlay KEEP vs hint.  
6. OT approval default and caps.  
7. Period close blockers and reopen behaviour.  
8. Whether unused policy fields should be hidden.  
9. Whether roster should drive SHIFT-scoped policies.  
10. WFH/ON_DUTY timeline.  
11. Post-lock correction approach.  
12. India patterns: alternate Saturdays, regional calendars, comp-off as fact only.

No approval is requested for ORM column names, permission string spellings, or migration IDs.


