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
