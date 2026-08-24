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
