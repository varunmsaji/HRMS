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
