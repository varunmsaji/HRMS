# Attendance Scenario Matrix + Indian HR Requirements Audit

Companion to `ATTENDANCE_RULE_COMPLETENESS_AUDIT.md`. Covers spec Section 12 (scenario matrix)
and Section 13 (Indian HR requirements audit). Every scenario's expected outcome is derived
directly from `calculation.py`/`service.py` logic verified in this audit — not guessed. Where a
scenario touches a rule found to be non-functional (per `ATTENDANCE_CONFIGURATION_AUDIT.md`), the
"Expected" column states what the code *actually* produces, not what the setting's name implies.

Default policy assumptions unless stated otherwise: `grace_in/out=0`, `missing_punch_behaviour=
INCOMPLETE`, `multi_punch_mode=PAIR_ALL`, `work_on_leave_behaviour=KEEP_LEAVE`, OT `eligibility=
SHIFT_FLAG`, `requires_post_approval=True`, `approval_chain=MANAGER`, `night_ot_mode=SHIFT_FLAG`.

## Section 12 — Scenario Matrix

### Normal Days

| # | Setup | Rules involved | Order | Day type | Attendance status | Worked min | Paid | LOP | OT | Approval | HR modify? | After lock |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | FIXED 09:00-18:00 shift, punches 09:00/18:00 | grace, hour bands | pair→worked→bands→status | WORKING | PRESENT | 540 | 1.00 | 0.00 | 0 (no excess) | n/a | Yes (recompute) | Frozen, `is_locked=True` |
| 2 | Same shift, no punches at all | `missing_punch_behaviour` | not_expected=False→missing_punch=True→INCOMPLETE (default) | WORKING | INCOMPLETE | 0 | 0.00 | 0.00 | n/a | n/a | Yes | Resolved per `incomplete_at_lock_behaviour` at finalize (default TREAT_ABSENT → paid 0.00/lop 1.00) |
| 3 | Same, `missing_punch_behaviour=ABSENT` | same | — | WORKING | ABSENT | 0 | 0.00 | 1.00 | n/a | n/a | Yes | Frozen |
| 4 | IN 09:35 (grace_in=15) | grace, late bands | late_raw=35, late_minutes=20→band lookup | WORKING | PRESENT (unless late band maps to HALF_DAY/ABSENT) | full | 1.00 | 0.00 | 0 | n/a | Yes | Frozen |
| 5 | OUT 17:00 (scheduled end 18:00, grace_out=0) | early bands | early_minutes=60→band lookup | WORKING | Depends on early band; if unmapped, PRESENT with `is_early_out=True` | ~480 | per hour-band | per hour-band | 0 | n/a | Yes | Frozen |
| 6 | Worked 350 min against an hour band `[0,360)=HALF_DAY` | hour bands | `_resolve_primary_status` | WORKING | HALF_DAY | 350 | 0.50 | 0.50 | 0 | n/a | Yes | Frozen |
| 7 | Missing IN only (orphan OUT) | pairing, missing_punch | `pair_punches` orphans the OUT | WORKING | INCOMPLETE (default) | 0 | 0.00 | 0.00 | n/a | n/a | Yes (via regularization) | Blocks finalize if `incomplete_at_lock_behaviour=KEEP_INCOMPLETE` |
| 8 | Missing OUT only (orphan IN) | pairing | trailing open IN is orphan | WORKING | INCOMPLETE | 0 | 0.00 | 0.00 | n/a | n/a | Yes | Same as #7 |
| 9 | Duplicate IN punches 30s apart | duplicate collapsing | `collapse_duplicate_punches` (default window 60s) | WORKING | Collapses to one IN, normal evaluation | per punches | — | — | — | — | Yes | — |
| 10 | Two IN/OUT pairs in one day (lunch out-and-back not configured as a break) | `multi_punch_mode=PAIR_ALL` | both pairs summed, gap between excluded | WORKING | PRESENT (sum of both intervals) | sum of both | 1.00 | 0.00 | per excess | — | Yes | — |

### Shifts

| # | Setup | Expected day type | Status | Worked min | OT | Notes |
|---|---|---|---|---|---|---|
| 11 | FIXED shift, standard | WORKING | per punches | as above | per excess | Baseline |
| 12 | FLEXIBLE shift, window 07:00-10:00, `required_minutes=480` | WORKING | Evaluated via `resolve_schedule_window`'s FLEXIBLE branch — **no dedicated test confirms the exact late/status outcome**; per code, `scheduled_start/end = window_start/window_end`, late compares IN against `window_end`+grace | per punches | uses `required_minutes` as OT baseline only if no fixed start/end resolved | **NOT TESTED — see Documentation Gaps.** Treat outcome as unverified, not merely "should work" |
| 13 | SPLIT shift, 2 duty blocks, both worked | WORKING | Normal status resolution (no missed blocks) | sum of pair minutes | detected via `shift.required_minutes` baseline | TESTED |
| 14 | SPLIT shift, one block missed, `split_shift_missed_block_behaviour=HALF_DAY` | WORKING | HALF_DAY | partial | still computed from worked minutes | Behaviour branch exists; not individually unit-tested by name (see Documentation Gaps) |
| 15 | Cross-midnight (overnight) shift 22:00-06:00 | WORKING | attendance_date = shift start date (the day the shift *begins*) | per punches | `is_night=True` internally, but OT day_class only becomes `NIGHT` if `night_ot_mode` is WINDOW/BOTH — **default (SHIFT_FLAG) never produces NIGHT** | TESTED for date attribution; NOT TESTED end-to-end for the NIGHT OT claim (see CT6) |
| 16 | Roster overrides assignment default shift | Whatever the roster's shift resolves to | — | — | — | TESTED — roster wins outright when PUBLISHED |
| 17 | No shift resolved (no assignment, no roster) and no punches | n/a (no schedule) | INCOMPLETE (default) or ABSENT (`missing_shift_behaviour=ABSENT`) | 0 | n/a | TESTED |
| 18 | No shift resolved, but punches exist | n/a | `_evaluate_no_schedule` — PRESENT if any gross minutes, else INCOMPLETE. **No late/early/OT ever computed in this path** (no schedule to compare against) | gross minutes | 0 (always — no OT is ever detected without a resolved schedule) | TESTED |

### Calendar

| # | Setup | Day type | Status (no punches) | Status (punches exist) | OT eligible on this day | Notes |
|---|---|---|---|---|---|---|
| 19 | Public holiday, shift doesn't operate | HOLIDAY | NOT_EXPECTED | Evaluated normally; `worked_on_holiday=True` if worked_minutes>0 | Yes, if shift is OT-eligible — `worked_on_holiday` feeds `day_class=HOLIDAY` | TESTED (weekly-off analogue confirmed directly; holiday shares the same code branch) |
| 20 | Weekly off (e.g. Sunday, Mon-Sat pattern) | WEEKLY_OFF | NOT_EXPECTED | `worked_on_weekly_off=True` if worked | Yes, `day_class=WEEKLY_OFF` | TESTED |
| 21 | Holiday landing on weekly-off day | WEEKLY_OFF, `holiday_on_weekly_off=True` | NOT_EXPECTED | Evaluated normally | Yes, `day_class` resolution: HOLIDAY beats WEEKLY_OFF in `classify_ot_day` (`calculation.py:642-650`) even though `calendar_day_type` reports WEEKLY_OFF | **OPEN PRODUCT DECISION** — no auto-substitute holiday granted elsewhere |
| 22 | Substitute holiday (manual exception) | HOLIDAY | NOT_EXPECTED | as #19 | as #19 | TESTED at the calendar-classification level (organisation module) |
| 23 | Special working day (exception) | SPECIAL_WORKING | Falls into the general "not `not_expected`" default (SPECIAL_WORKING is not in the `not_expected` tuple `("HOLIDAY","WEEKLY_OFF","SHUTDOWN")`, `calculation.py:767-768`) → presence IS expected | Evaluated normally | Yes | Confirms SPECIAL_WORKING behaves like an ordinary working day for attendance purposes |
| 24 | Shutdown day | SHUTDOWN | NOT_EXPECTED | Evaluated normally if punches exist | Yes | TESTED at the calendar-classification level |
| 25 | Cancelled holiday (exception removes the holiday match, date is not otherwise a weekly-off) | WORKING | INCOMPLETE/ABSENT per policy (ordinary working day now) | Evaluated normally | Yes | Confirmed via `calendar_resolution.py:164-180` |
| 26 | Optional/restricted holiday, `restricted_holidays_are_off_by_default=False` (default) | WORKING (soft — "working until Leave applies") | Ordinary working-day evaluation | Ordinary | Yes | PD-CAL-1 in code comment — the "only sanctioned per-company override" |

### Leave

| # | Setup | Status | Paid | LOP | OT | Notes |
|---|---|---|---|---|---|---|
| 27 | Full-day paid leave, no punches | LEAVE | 1.00 | 0.00 | 0 | TESTED |
| 28 | Full-day unpaid leave, no punches | LEAVE | 0.00 | 1.00 | 0 | TESTED |
| 29 | Half-day paid leave, no punches | LEAVE (remaining half unworked → LOP for the working half) | 0.50 | 0.50 | 0 | TESTED |
| 30 | Half-day leave + full-day punches | HALF_DAY (has_work=True) | 1.00 (0.50 leave + 0.50 punch-derived work) | 0.00 | Whatever punches detect, **unaffected by the leave overlay** | TESTED for status; OT interaction NOT TESTED (CT9) |
| 31 | Full-day leave + punches, `KEEP_LEAVE` (default) | LEAVE (punches ignored for status) | per leave's paid flag | per leave's paid flag | **OT still computed from the punches and NOT cleared** (CT9) | TESTED for status; OT NOT TESTED |
| 32 | Full-day leave + punches, `PRESENT_CANCEL_LEAVE_HINT` | Punch-derived status kept; `work_on_leave_flagged=True` | per punch-derived outcome | per punch-derived outcome | per punch-derived outcome | TESTED |
| 33 | Leave on a holiday date | `calendar_day_type=HOLIDAY` unchanged; `attendance_status=LEAVE` if leave fraction ≥1.00 | per leave | per leave | 0 | TESTED (`test_leave_overrides_roster_week_off_not_expected` proves the analogous weekly-off case) |
| 34 | Leave on a weekly-off date | Same pattern | per leave | per leave | 0 | Same mechanism |
| 35 | Leave cancelled after being synced | Reverts to punch-derived outcome on next recompute | per punches | per punches | per punches | TESTED — `test_cancel_projection_reverts_attendance_to_punch_derived_outcome` |
| 36 | Leave sync/cancel attempted on a locked period | Refused | n/a | n/a | n/a | TESTED |

### Regularization

| # | Setup | Outcome | Approval state | After lock |
|---|---|---|---|---|
| 37 | Employee submits MISSING_PUNCH request, single-stage MANAGER chain | SUBMITTED → manager approves → synthetic punches inserted → day recomputed | PENDING→APPROVED | Locked periods refuse the initial submission entirely |
| 38 | WRONG_SHIFT request | On approval, creates/updates a `PUBLISHED` `ShiftRoster` row for that date, then recomputes | as above | Same |
| 39 | WFH/ON_DUTY-typed request | On approval, inserts synthetic punches (same as MISSING_PUNCH) — **does not produce `attendance_status=WFH`/`ON_DUTY`** (CT5) | as above | Same |
| 40 | Manager rejects | Attendance day left entirely unchanged | REJECTED | n/a |
| 41 | Employee tries to approve their own request | Refused (self-approval always blocked) | n/a | n/a |
| 42 | MANAGER_THEN_HR chain, manager approves stage 1 | `approval_stage` moves to HR, status stays SUBMITTED, no correction applied yet | STAGE_APPROVED (manager) → then HR must act | n/a |
| 43 | No manager resolved for employee | Routes straight to HR stage | PENDING(HR) | n/a |
| 44 | `AUTO` approval chain | Approved and applied immediately on submit, no human review | AUTO_APPROVED-equivalent | n/a |
| 45 | Backdated beyond `max_backdated_days` | Submission rejected outright | n/a | n/a |
| 46 | Beyond `max_requests_per_month` | Submission rejected outright | n/a | n/a |
| 47 | Request for a date in a locked period | Submission refused | n/a | Only a full `ATTENDANCE.UNLOCK` reopen re-enables correction |

### Overtime

| # | Setup | day_class | Status | Approval | Cap interaction |
|---|---|---|---|---|---|
| 48 | Normal working day, 25 min excess over `min_ot_minutes=15` | NORMAL | PENDING (requires_post_approval=True, chain=MANAGER default) | Manager approves → `ot_minutes_approved` set on the day | none |
| 49 | Excess below `min_ot_minutes` | n/a | Not detected at all (`ot_minutes_detected=0`) | n/a | n/a |
| 50 | Worked on holiday | HOLIDAY | as #48 | as #48 | day_class = HOLIDAY, rate row lookup uses it |
| 51 | Worked on weekly-off | WEEKLY_OFF | as #48 | as #48 | day_class = WEEKLY_OFF |
| 52 | Genuinely overnight shift, default `night_ot_mode=SHIFT_FLAG` | **NORMAL, never NIGHT** (CT6) | as #48 | as #48 | Client expecting a night differential will see nothing distinguishing this from a normal day's OT |
| 53 | `night_ot_mode=WINDOW`, employee works past midnight | Still gated on `shift.is_cross_midnight` only, **not** on whether the actual minutes fall inside `night_window_start/end`; will read NIGHT for any cross-midnight shift with any excess minutes, correct or not | as #48 | as #48 | The window itself has zero effect (CT6) |
| 54 | SPLIT shift with excess in one block | Computed against `shift.required_minutes` baseline | as #48 | as #48 | TESTED (W7 addition) |
| 55 | Daily cap reached | Excess clamped to `daily_cap_minutes` | as #48 (clamped amount) | as #48 | TESTED |
| 56 | Weekly cap already consumed by an earlier day this week | `remaining_weekly_minutes` computed from sibling-day sums, clamps this day too — possibly to 0 even though the day's own excess is nonzero | STILL "eligible", just 0 minutes detected | n/a if 0 | TESTED — `test_detect_overtime_weekly_cap_exhausted_still_eligible_zero_minutes` |
| 57 | Monthly cap reached | Same pattern at month grain | as #56 | n/a | TESTED |
| 58 | `comp_off_instead_of_pay=True`, auto-approved | `comp_off_minutes_earned` set with expiry date | AUTO_APPROVED | Comp-off fact stored; **no expiry-lapse enforcement exists anywhere in this codebase** | TESTED for the fact; expiry enforcement is FUTURE MODULE |
| 59 | Comp-off while still PENDING | `comp_off_minutes_earned` on the day is **0** until the decision is made (the record itself always carries the computed fact) | PENDING | n/a | TESTED — `test_comp_off_not_credited_to_day_while_pending` |
| 60 | Rejected OT | `ot_minutes_approved`/`comp_off_minutes_earned` cleared to 0 on the day | REJECTED | Frozen — never revised by a later recompute | TESTED |
| 61 | Self-approval attempt | Refused | n/a | n/a | TESTED |
| 62 | `eligibility=NEVER` | No OT ever detected regardless of hours worked | n/a | n/a | Confirmed by code path (`calculation.py:668-669`); not individually named-tested but trivially implied by the eligibility gate structure |
| 63 | `eligibility=GRADE_VIA_ASSIGNMENT`, employee's grade is not meant to be OT-eligible | **Still detected — behaves exactly like ALWAYS** (CT7) | PENDING/AUTO per chain | This is a genuine payroll-risk scenario if a client relies on grade gating | NOT TESTED (no test proves the grade is even read) |

### Period / Lock

| # | Setup | Validation result | Outcome | Reopen |
|---|---|---|---|---|
| 64 | All days calculated, no pending anything | READY | Finalize succeeds, days locked, summary snapshot written | — |
| 65 | An employee has a date range with no `AttendanceDay` row | EMPLOYEES_WITHOUT_ATTENDANCE | Blocked | — |
| 66 | A day is `CONFIG_ERROR` | CONFIG_ERROR | Blocked, no lock-time auto-resolution exists (must fix and recompute) | — |
| 67 | A day is INCOMPLETE under `KEEP_INCOMPLETE` policy | INCOMPLETE_ATTENDANCE | Blocked | — |
| 68 | A day is INCOMPLETE under default `TREAT_ABSENT` policy | Not a blocker | Finalize succeeds; day auto-resolved to paid 0.00/lop 1.00 at finalize | — |
| 69 | A regularization request is still SUBMITTED | PENDING_REGULARIZATION | Blocked | — |
| 70 | An overtime record is still PENDING | PENDING_OVERTIME_APPROVAL | Blocked | — |
| 71 | A roster entry is still DRAFT | UNPUBLISHED_ROSTER | Blocked | — |
| 72 | Successful finalize | READY | Days locked, `AttendancePeriodSummary` rows frozen, period `status=CLOSED` | — |
| 73 | Any mutation attempted on a locked date (punch/roster/regularization-submit/recompute/OT-approve/leave-sync/leave-cancel) | n/a | All 7 refused | — |
| 74 | Reopen a CLOSED period | n/a | Days unlocked across the range; nothing recomputed automatically; a later ordinary `calculate()`/correction call is needed to actually change anything; re-finalize regenerates a fresh summary | Requires separate `ATTENDANCE.UNLOCK` permission |

## Section 13 — Indian HR Requirements Audit

| Requirement | Support level | Evidence |
|---|---|---|
| Mon-Fri work week | **Support** | `WeeklyOffRuleData` with `FIXED_WEEKDAYS` covers any weekday set, including a 2-day weekend (organisation module, `calendar_resolution.py:72-117`) |
| Mon-Sat work week (single weekly off) | **Support** | Same mechanism, one weekday |
| Alternate Saturday off | **Support** | `ALTERNATE` rule kind, `cycle_start_date` + `week_parity` (`calendar_resolution.py:109-116`) — default parity for an unset `week_parity` is documented as an implementation choice, not a spec'd default (see Hidden Rules HR3-equivalent in Configuration Audit) |
| Nth/last Saturday off | **Support** | `NTH_WEEKDAY` with `nth_in_month=-1` for "last" (`calendar_resolution.py:105-108`) |
| Rotational weekly offs (different day per employee/week) | **Support** | `ShiftRoster.is_week_off_override` per employee-date is exactly this mechanism, explicitly motivated by "night-shift workers with a Wednesday off" per the architecture doc itself (line 730) |
| State/branch-specific holidays | **Support** | Branch carries `state_code`; multiple `WorkCalendar`s can be scoped and resolved through the same 8-level precedence walk used for policies (organisation module — not re-verified line-by-line in this pass, but the mechanism generalizes from the confirmed policy-resolution walk) |
| Optional/restricted holidays | **Support** | `holiday_type IN (OPTIONAL, RESTRICTED)`, `restricted_holidays_are_off_by_default` toggle (PD-CAL-1) |
| Holiday on Sunday (weekly-off collision) | **Partial — needs decision** | Stays WEEKLY_OFF with a flag; no automatic substitute holiday is granted (PD-CAL-2, open) |
| Compensatory holiday (substitute) | **Partial** | `SUBSTITUTE_HOLIDAY` exception type exists and works, but is entirely manual (HR must create the exception row) — no automatic trigger from the Sunday-holiday collision above |
| Night shifts | **Partial — needs decision** | Cross-midnight scheduling/date-attribution works correctly; NIGHT overtime classification does not reliably distinguish a genuine night shift and, by default, never classifies anything as NIGHT (CT6) |
| 24x7 operations | **Support** | `operates_on_holiday`/`operates_on_weekly_off` per-shift flags plus roster overrides cover continuous-operations shift patterns |
| Security/hospital/manufacturing shift patterns | **Partial** | The building blocks (cross-midnight, SPLIT shifts, roster overrides, 24x7 flags) all exist and are individually tested; no end-to-end scenario test combines them the way a real 3-shift rotating roster would, and the NIGHT OT gap (above) is most likely to bite this segment specifically |
| Split shifts | **Support (with documented simplification)** | Duty-block presence detection works; no partial-hours credit for a partially-worked block (documented limitation, not silent) |
| Flexible timings | **Partial — needs verification** | Window resolution exists in `resolve_schedule_window`, but core-hours enforcement (the feature that makes "flexible" meaningfully different from "just don't check lateness") is entirely unimplemented (CT3), and no test proves the FLEXIBLE path's actual late/status output |
| Work From Home (WFH) | **Not supported as a distinct status — Future module / needs decision** | CT5 — none of the architecture's 3 named mechanisms exist; only ordinary punch-based evaluation results |
| Field / On-duty | **Not supported as a distinct status — Future module / needs decision** | Same as WFH — `ON_DUTY` regularization type exists but produces ordinary punches, never a distinct status |
| Half-day leave | **Support** | W9 — full, tested, including multiple half-days summing to a full day |
| Late-coming policy (grace + bands) | **Support** | Grace minutes + ordered late bands, fully working and tested |
| Repeated-late penalties (N lates = half day) | **Not supported — Stored but not used** | `lates_to_half_day_count`/`late_count_window` are configurable in the UI but have zero runtime effect (H14) |
| OT on holiday/weekly-off | **Support** | `day_class` classification correctly distinguishes HOLIDAY/WEEKLY_OFF for rate-row lookup (informational multiplier, not money) |
| Comp-off | **Support (fact only, no expiry enforcement)** | `comp_off_minutes_earned`/`comp_off_expiry_date` computed and stored correctly; nothing in this codebase invalidates a comp-off once its expiry date passes — that enforcement would live in a future Leave/Payroll module |
| Monthly attendance closing | **Support** | `AttendancePeriod` finalize/lock (W8) is comprehensive — 6 validation blockers, atomic lock, frozen payroll-facing summary, reopen path, all thoroughly tested |

---

*Compiled 2026-08-21. Scenarios reference the exact policy defaults documented in
`ATTENDANCE_MASTER_RULE_MATRIX.md`; "NOT TESTED" markers were confirmed by grepping the full test
function name list in both the unit and integration attendance test suites on the same date.*
