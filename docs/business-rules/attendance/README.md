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
