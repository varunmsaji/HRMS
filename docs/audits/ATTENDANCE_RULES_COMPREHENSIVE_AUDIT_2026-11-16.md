# Attendance Rules and Policy — Comprehensive Audit

**Date:** 16 November 2026 · **Branch:** `test` at `dd71571` **plus the uncommitted remediation in the
working tree** (15 modified files, 5 new test files, 1 new migration, `leave/reconciliation.py`) ·
**Engine version 15** · **No application code, test, fixture or migration was changed. Nothing was
committed.**

> **Update, 16 November 2026 (later the same day).** This report describes engine 15. AR-01 … AR-14
> have since been addressed in the working tree (engine 16, uncommitted); see
> `ATTENDANCE_RULES_REMEDIATION_2026-11-16.md` for what changed, what was only partly resolved and
> the test results. The findings below are kept as written so the "before" behaviour stays on record.

Scope: shift, roster, grace, overtime, leave, work calendar, holiday, weekly off, breaks,
regularization, ON_DUTY, the attendance engine, recalculation and period close. Payroll is out of
scope.

**What was audited is the working tree, not a commit.** The AC-01 … AC-09 remediation exists only
as uncommitted changes. Every result below describes that state.

## Evidence levels

| Label | Meaning |
|---|---|
| **REPRODUCED (API)** | Shown through the HTTP API against the isolated `hrms_test` database |
| **REPRODUCED (engine)** | Shown by running the pure engine (`calculation.evaluate_day`) in memory |
| **CODE-CONFIRMED** | Every write path read; not run end to end |
| **PLAUSIBLE RISK** | The code allows it; not demonstrated. Not counted as a bug |
| **PASS** | Inspected and exercised successfully |
| **NOT VERIFIED** | Not enough evidence either way |

Probe inputs and outputs are in Appendix A so each result can be rerun.

---

## Part 1 — Executive summary

**Verdict: ATTENDANCE RULES NOT VERIFIED — IMPORTANT ISSUES REMAIN.**

The remediation fixed most of what the last audit found. Decided overtime now follows corrections,
calendar and policy changes queue recalculation, overtime on an incomplete day is held, and period
close has three new blockers. The calculation core remains deterministic for a given set of inputs.

It is not yet safe to hand to a payroll audit, for four reasons:

1. **One previous finding is not fixed in practice (AC-06).** A roster week-off row cannot carry a
   shift, so work on it runs through the no-shift path: no overtime, no weekly-off class. The fix
   sits in code the service never reaches (AR-01).
2. **The grace model has a one-minute cliff on the shipped policy templates.** On "Standard office"
   (grace 10, full day 8 h) with an 8-hour net shift, arriving at 09:11 and leaving on time is a
   half day of loss of pay. On a half-day-leave day the same minute loses the entire worked half
   (AR-02).
3. **The remediation introduced new defects.** Overtime rejected by the system at lock stays
   rejected after the period is reopened and the day corrected (AR-03). The half-day-leave flag
   fires on ordinary early arrival and blocks period close (AR-07).
4. **Several rules still depend on order or are applied to one shift type only** (AR-04 … AR-06,
   AR-12 … AR-14).

| | Count |
|---|---|
| Confirmed defects (reproduced) | 12 |
| Confirmed defects (code-confirmed) | 2 |
| Plausible risks | 4 |
| Areas not verified | 6 |
| Previous findings AC-01 … AC-09: fixed | 5 (AC-01, AC-04, AC-07, AC-09, AC-08 on web) |
| Previous findings: partly fixed | 3 (AC-02, AC-03, AC-05) |
| Previous findings: not fixed in practice | 1 (AC-06) |
| Shift audit decisions still open | 8 of 8 (P-01, P-04, P-05, P-07, P-10, P-11, P-12, P-14) |
| Leave audit findings LV-01 … LV-13 | all still open (`leave/service.py` is unchanged) |

**Blockers before the payroll audit:** AR-01, AR-02, AR-03, and the decision on AR-04. AR-05 … AR-07
should be fixed in the same pass because they change the same engine code.

---

## Part 2 — Architecture and calculation flow

Unchanged in shape from the previous audit (§2 of `ATTENDANCE_CALENDAR_OVERTIME_AUDIT_2026-11-16.md`).
Confirmed again by reading the current code:

| Step | Source of truth | Code |
|---|---|---|
| Employment gate | `employment` | `EmploymentService.get_employment_as_of` |
| Schedule | published `shift_roster` row > `employee_assignment.shift_id` > none. A roster row with no shift means **no shift** | `work_schedule.WorkScheduleResolver.resolve` |
| Calendar | exception > holiday > weekly off > working, via `WORK_CALENDAR` (+ optional `WEEKLY_OFF`) policy assignment; fails closed | `calendar_resolution.resolve_for_employee` |
| Policies | 8-level scope walk, employee → company; fails closed | `resolve_policy_assignment` |
| Leave | active `leave_day_projection` rows | `LeaveProjectionService` |
| Punch ownership | one owner per punch, compared with ±neighbour days | `punch_ownership.assign_owners` |
| Day result | pure function | `calculation.evaluate_day` |
| Overtime decision | `overtime_record` | `service._resolve_ot_decision`, `_sync_overtime_record` |
| Recalculation | `attendance_recalc_request` queue, daily sweep, period close | `recalc.py`, `tasks.py` |
| Period close | recalculate unlocked days → validate → resolve INCOMPLETE → lock | `AttendancePeriodService.finalize` |

**Engine order (verified):** employment gate → timezone check → calendar/policy config errors →
roster week-off with no punches → no-shift path → not-expected with no punches → punch evaluation
(FIXED/FLEX or SPLIT) → off-day pay → half weekly off → ON_DUTY → leave (leave wins).

**Rules implemented in more than one place**

| Rule | Places | Consistent? |
|---|---|---|
| Working share of a date | engine `_work_not_expected`; leave `_working_shares` | Yes, same precedence |
| Duplicate / stray folding | engine `collapse_duplicate_punches`, `drop_stray_punches`; ownership `build_sessions` | Yes (mirrored by hand; no shared code) |
| Overtime basis for a half day | `_evaluate_fixed_or_flex` only | **No** — `_evaluate_split` has none (AR-06) |
| Weekly-off class | `_worked_on_weekly_off` (shift path); `_evaluate_no_schedule` (calendar only) | **No** (AR-01) |
| Punch-to-day display | web and mobile now read `computation_snapshot.inputs.punch_ids` | Yes |

---

## Part 3 — Module-by-module findings

Issue details are in Part 9. This part records what was checked and the result.

### Shift and roster

| Check | Result |
|---|---|
| One schedule per employee-date, roster > assignment > none | PASS (code; existing `test_resolved_work_schedule.py`) |
| FIXED normal day, late departure, early arrival not credited | PASS (engine B0, G9, P04) |
| Overnight 22:00–06:00: ownership, late OUT, early arrival, missing OUT | PASS (engine O1–O4; existing ownership tests) |
| Holiday at the start date of an overnight shift | Classified by the start date only (O5). P-01 still open |
| FLEXIBLE: required minutes, lateness from window end, early start counted | PASS (F0–F3). Early start **is** credited, unlike FIXED (P-04) |
| SPLIT: totals, overtime after last block, work between blocks | PASS (S0, S1, S7) |
| SPLIT: lateness per block | Not computed; hour bands only (S5, S9). P-11 still open |
| SPLIT: missing OUT in one block | **HALF_DAY, not INCOMPLETE** (AR-14) |
| Roster week-off, no punches | PASS (R3) |
| Roster week-off, worked | **No overtime** (AR-01) |
| Roster "working this holiday" | Ordinary working day, NORMAL class (HD5), as decided in P-02 |
| Short shift against standard hour bands | **Full attendance is a half day** (AR-12). P-05 still open |
| Two shifts in one day | Not supported. P-14 still open |
| Night flexible shift | NOT VERIFIED. P-10 still open |

### Grace

Grace is two numbers on the attendance policy version: `grace_in_minutes` and `grace_out_minutes`.
There is **no** monthly grace, instance count, reset rule or per-employee eligibility. Nothing is
persisted as "grace used", so recalculation cannot consume it twice and concurrency cannot exceed a
limit. The only cumulative rule is `lates_to_half_day_count` (month window only).

| Check | Result |
|---|---|
| Exactly at grace: late 0 | PASS (G1, G3) |
| Grace + 1: late 1 minute | Late minutes correct; **status is HALF_DAY on the shipped templates** (AR-02) |
| Late and early both inside grace | PASS, PRESENT (G5) |
| Grace forgives late minutes and credits the hour-band lookup only | PASS; worked minutes and overtime use real minutes (G10: 50 min OT, not 60) |
| Same minutes forgiven twice | Not found |
| Grace on half-day leave | Applied to the worked half (L8). One minute over loses the whole half (AR-02) |
| Grace on split shifts | Band credit at first start and last end only; no lateness (P-11) |
| Nth late day in the month → HALF_DAY, later days recomputed | PASS (PB2, PB3; `_recompute_later_days_of_month`; existing `test_cumulative_recompute.py`) |
| Half weekly off: working one half | **Recorded as 290 minutes late or early and counts as a late day** (AR-13) |

### Overtime

| Check | Result |
|---|---|
| Eligibility: `NEVER`, `SHIFT_FLAG`, `ALWAYS` | PASS (HD3). `GRADE_VIA_ASSIGNMENT` is accepted but the engine treats it as always eligible — NOT VERIFIED as intended |
| Net schedule basis, unpaid break not hidden | PASS |
| Holiday / weekly-off work on a non-operating shift: all minutes, correct class | PASS (W1, HD2) |
| Half-day leave, FIXED shift | PASS (L1) |
| Half-day leave, SPLIT and FLEXIBLE | **Wrong** (AR-06) |
| Half weekly off (P-A) | Overtime after the longer half, class NORMAL (W4). Awaiting owner confirmation |
| HALF_DAY / ABSENT day pays no overtime (P-B) | PASS as built (PB1, PB2). Side effect on short shifts (AR-12) |
| Auto-approved overtime follows a correction | PASS (API probe 3; `test_overtime_recalculation.py`) |
| Human-approved: reopen when it grows, cap when it shrinks | PASS (existing tests) |
| Overtime on an INCOMPLETE day held, rejected at lock under TREAT_ABSENT | PASS (API probe 2, first half) |
| Same, after reopen and correction | **Stays rejected** (AR-03) |
| Weekly / monthly cap | **Order-dependent and stale after a sibling correction** (AR-04) |
| `missing_punch_behaviour = AUTO_CLOSE` with an orphan punch | **Overtime auto-approved** (AR-11) |
| Recalculation idempotent | PASS (engine; `test_repeated_recalculation_changes_nothing`) |
| Comp-off facts skip unpayable days | PASS (code: `list_comp_off_facts_on_unpayable_day`) |

### Leave

`leave/service.py` has no changes since `LEAVE_MANAGEMENT_AUDIT_2026-11-16.md`, so LV-01 … LV-13
stand as written there. Two of them change attendance results directly:

- **LV-04** — a period can close with leave requests still pending; the days lock as absent.
  Re-checked: the blocker list (`service.py:7371–7673`) still has no pending-leave code.
- **LV-05** — the same half can be booked twice. Engine L13 shows the effect: two FIRST-half
  entries make a full-day `LEAVE`, and the afternoon the employee worked is flagged as work on leave.

Checked in this audit:

| Check | Result |
|---|---|
| Full-day leave wins; punches flagged; overtime zero | PASS (L14) |
| Half-day leave, other half worked / not worked / missing punch | PASS (L5, L11, L15) |
| Unpaid half-day leave | PASS (L12) |
| Leave approved or cancelled after attendance exists | PASS (code: `LeaveProjectionService.sync` / `cancel` recalculates in the same transaction; existing tests) |
| Holiday added or removed inside approved leave | **Detected and blocked at close only** (AR-10) |
| Roster or shift change after approval (P-12) | Same detector; nothing at the time of the change (AR-10) |
| Half-day leave + approved ON_DUTY | ON_DUTY, 1.00 paid, leave still debited (L16). Decision needed (D-07) |
| Hourly leave | Not supported |

### Work calendar, holiday, weekly off

| Check | Result |
|---|---|
| Precedence exception > holiday > weekly off > working; holiday on weekly off counted once | PASS (code; existing tests) |
| Holiday create / edit / move / deactivate queues recalculation for old and new date | PASS (code; `test_calendar_recalc_triggers.py`) |
| Holiday calendar validity or active flag | PASS (code) |
| Weekly-off pattern rules / kind / active | PASS (test) |
| Work calendar: pattern set or changed, holiday links, restricted flag, active | PASS (test) |
| Work calendar: pattern **removed** | **No recalculation queued** (AR-08) |
| Calendar exception create / edit | PASS (test) |
| Scope of the queued request | Employee- or shift-scoped assignments narrow it; anything wider queues the company. A superset, never a subset (code) |
| Paid / unpaid off day by pay basis and holiday flag | PASS (HD1, HD6, HD7) |

### Breaks, regularization, ON_DUTY, employment

| Check | Result |
|---|---|
| Break rules, overlap, cross-midnight, overrides | PASS (existing unit and integration suites; not re-probed) |
| Employee break override created or changed for past dates | **No recalculation queued** (AR-09) |
| Regularization approve → day recalculated in the same transaction | PASS (API probes 2 and 3) |
| Regularization into a closed period refused | PASS (existing tests) |
| ON_DUTY without punches: paid, overtime zero, decided overtime preserved | PASS (code; `test_on_duty_overtime.py`) |
| NOT_JOINED / EXITED: not paid, not LOP | PASS (existing tests) |
| Employment created, edited or terminated with a past date | **No recalculation queued** (AR-09) |
| Punch allowed after the last working day when it closes that day's shift | PASS — and it is why one existing test fails for six hours a day (TG-01) |

### Period close

| Check | Result |
|---|---|
| Recalculates every unlocked owned day before validating | PASS (code; API probe in `test_overtime_period_close.py`) |
| New blockers `OVERTIME_INTEGRITY`, `LEAVE_CALENDAR_MISMATCH`; half-day flag feeds `WORK_ON_LEAVE_UNRESOLVED` | PASS (tests) |
| Locked rows never recalculated; reopen refused after payroll finalised | PASS (code; existing tests) |
| Pending leave blocks close | **No** (LV-04) |
| Queue requests still pending at close | Not awaited; close recalculates the period's own days, so the closed period is correct |

---

## Part 4 — Policy decision register

**Status key:** *Decided* = recorded owner decision. *Default* = built as the audit's recommendation,
not owner-approved. *Inferred* = behaviour found in code with no recorded decision. *Open* = no rule.

### Configured policies

| Policy | Where set | Versioned | Assigned to | When none resolves | Change after calculation |
|---|---|---|---|---|---|
| Shift | shift version | Yes, effective-dated | employee assignment or roster row | "no shift" path | queue, from `effective_from` |
| Roster | dated rows, draft → published | No | employee-date | falls back to assignment | queue, that date |
| Work calendar | `work_calendar` + links | No (edited in place) | 8-level scope | `CONFIG_ERROR`, blocks close | queue (gap AR-08) |
| Weekly-off pattern | `weekly_off_pattern` | No (edited in place) | calendar, or direct `WEEKLY_OFF` assignment | calendar's own pattern, or none | queue |
| Attendance policy | version | Yes | 8-level scope | `CONFIG_ERROR` | queue on publish and on assignment |
| Overtime policy | version | Yes | 8-level scope | no overtime | queue on publish and on assignment |
| Regularization policy | version | Yes | 8-level scope | requests refused | not needed |
| Leave policy | version, per leave type | Yes | 8-level scope | leave refused | **none** (AR-10) |

Calendars and patterns are edited in place, so a past day recalculated today uses today's
calendar. That is intended, and it is why the leave detector exists.

### Rules in force

| ID | Rule | Status |
|---|---|---|
| P-02 | A shift that operates on a holiday / weekly off makes it an ordinary working day | Decided |
| P-06 | No shift: hour bands only; no lateness or overtime | Decided |
| D-1 | Work on a non-operating off day never costs pay; all minutes are overtime | Decided |
| BUS-001 | Off-day pay by pay basis and holiday flag | Decided |
| BUS-011/012 | Full-day leave wins; punches flagged; no overtime | Decided |
| R-02 | Sandwich rule, within and across applications | Decided |
| P-A | Half weekly off: overtime after the longer half | Default |
| P-B | HALF_DAY / ABSENT day pays no overtime | Default |
| P-C | Human overtime decision: reopen on growth or class change, cap on shrink | Default |
| AC-04 | Overtime on INCOMPLETE held; rejected at lock under TREAT_ABSENT | Default |
| AC-05 | Work in the leave half is flagged; tolerance = grace | Default |
| P-D | Non-eligible shift earns nothing on a day off | Inferred; policy screen does not say so |
| P-E | Leave balance after a calendar change | Open — detect and block only |

### Hardcoded values and hidden rules found

| Rule | Value | Where | Status |
|---|---|---|---|
| Neighbour days compared for punch ownership | fixed constant | `ownership_service.NEIGHBOUR_DAYS` | Inferred |
| Stray same-direction punch window | fixed minutes | `calculation.STRAY_PUNCH_WINDOW_MINUTES` | Inferred |
| Punch limits when no policy resolves | 240 early / 720 late | `ownership_service` defaults | Inferred |
| Late-count window | calendar month only | `late_count_window` accepts only `MONTH` | Inferred |
| Weekly cap week | Monday–Sunday | `_build_calculation_input` | Inferred |
| A `PENDING` overtime record reserves cap budget | detected minutes | `sum_minutes_counted_for_cap` | Inferred (N-5) |
| Daily sweep look-back | today and 2 days before | Beat | Inferred |
| Recalc request abandoned after | 5 failed attempts | `recalc.MAX_ATTEMPTS` | Inferred |
| Night class with no NIGHT rate row | paid as NORMAL | `detect_overtime` | Inferred |
| Holiday class beats weekly-off class beats night class | one class per day | `classify_ot_day` | Inferred |
| Milder late/early band overrides a harsher hour band | — | `_resolve_primary_status` | **Defect** (AR-05) |
| Missed split block outranks a missing punch | default `HALF_DAY` | `_evaluate_split` | Needs decision (AR-14) |

### Fields saved but not used by the engine

`punch_rounding`, `rounding_minutes` (attendance policy), `half_day_split`,
`half_day_boundary_minutes`, `early_out_uses_core_end`, `work_on_leave_behaviour`, and the
`AUTO_CLOSE` option of `missing_punch_behaviour` (it closes nothing; see AR-11).
`apply_rounding` exists in the engine and has no caller. The web form hides these (SH-14). **Mobile
still offers `work_on_leave_behaviour` as a select** (`policy_resources.dart:57`); it changes nothing.

### Decisions needed from the owner

| ID | Question | Blocks |
|---|---|---|
| D-01 (was P-07) | When someone is late beyond grace but inside the "late" band, should a full day need the full hours, or is the late mark enough? | AR-02 |
| D-02 | On a half-day-leave day, what does a short worked half pay — nothing (today), or in proportion? | AR-02 |
| D-03 | Roster week-off work: overtime at the weekly-off rate, comp-off, or nothing? | AR-01 |
| D-04 | Weekly / monthly cap: which days get the budget — earliest first? | AR-04 |
| D-05 | Confirm P-A, P-B, P-C and the AC-04 / AC-05 defaults | — |
| D-06 | P-E: refund leave automatically when a holiday is added? What if the balance is short when one is removed? | AR-10 |
| D-07 | Half-day leave plus ON_DUTY on the other half: is the leave still charged? | — |
| D-08 | P-D: confirm, and show it on the policy screen | — |
| D-09 | Split shift, missing punch in one block: half day or review? | AR-14 |
| D-10 | P-01, P-04, P-05, P-10, P-11, P-14 from the shift audit | AR-12 depends on P-05 |

---

## Part 5 — Previous audit regression

### AC-01 … AC-09

| ID | Original root cause | Current implementation | Fixed? | Evidence | New issue / remaining edge |
|---|---|---|---|---|---|
| AC-01 | Every non-PENDING overtime record was frozen | `_resolve_ot_decision` re-derives AUTO_APPROVED, reopens or caps human decisions, writes `SUPERSEDED_BY_RECALCULATION`; `replace_for_day`, `cap_decided` | **Yes** | 6 tests in `test_overtime_recalculation.py`; API probe 3 (auto-approved 30 → 60 on recompute) | A system rejection at lock is treated as a human rejection (AR-03) |
| AC-02 | Calendar mutations queued nothing | `request_calendar_recalc` called from 7 mutation methods; deactivate routes go through the same update methods | **Mostly** | `test_calendar_recalc_triggers.py` (5 tests) | Removing a calendar's pattern queues nothing (AR-08) |
| AC-03 | Leave breakdown fixed at submit | Read-only detector + `LEAVE_CALENDAR_MISMATCH` close blocker | **Partly** | 3 tests | No reconciliation, no notice at the time of the change, cross-application bridge days skipped (AR-10) |
| AC-04 | Detection ran on INCOMPLETE; lock changed only pay | Held PENDING for HR; `_withdraw_overtime_at_lock` | **Yes** | API probe 2: before close `detected 60, approved 0, pending`; after close `LOP 1.00, approved 0, record REJECTED` | AR-03; `AUTO_CLOSE` path bypasses it (AR-11) |
| AC-05 | Overtime compared with the full shift | `_half_day_overtime_basis`, `_work_in_leave_half` | **FIXED shifts only** | Engine L1, L5; 6 unit tests | SPLIT and FLEXIBLE unchanged (AR-06); flag fires on early arrival (AR-07) |
| AC-06 | Class read only the calendar day type | `_worked_on_weekly_off` reads the roster flag | **Not in practice** | API probe 1: `shift_id null, ot_minutes_detected 0, worked_on_weekly_off false` | The unit tests pass a shift the service can never supply (AR-01) |
| AC-07 | Policy publish queued nothing | `request_policy_version_recalc` in both publish methods | **Yes** | Test for overtime policy; attendance policy by code (same function) | Nobody assigned → nothing queued (correct) |
| AC-08 | Clients re-derived ownership | Both clients filter by `computation_snapshot.inputs.punch_ids` | **Web: yes. Mobile: changed, not run** | Web `day-detail.test.ts` 10/10 pass. Flutter is not installed on this machine | A punch added after the last calculation is hidden until the row is recalculated (R-4) |
| AC-09 | UTC date in the warning | `business_today(company.timezone)` | **Yes** | Test | — |

### Shift audit decisions

| ID | Status | Why |
|---|---|---|
| P-01 Holiday at the end of an overnight shift | Open | The whole shift takes the start date's day type (engine O5) |
| P-04 Early arrival and overtime | Open, and inconsistent | FIXED: not credited (P04). FLEXIBLE: credited (F2). Half-day leave: credited up to the tolerance (N2: 10 min overtime) |
| P-05 Hour bands for short shifts | Open, now worse | Full attendance on a 4-hour shift is HALF_DAY, and P-B then removes all overtime (AR-12) |
| P-07 Grace model | Open | AR-02 |
| P-10 Night flexible shifts | Open | NOT VERIFIED |
| P-11 Split-shift late / early | Open | Engine S5, S9: no late minutes |
| P-12 Roster change after leave | Partly | Only the close blocker (AR-10) |
| P-14 Two shifts per day | Open | One roster row per employee-date |

---

## Part 6 — Cross-module scenarios

Standard setup unless stated: monthly paid, FIXED 09:00–18:00 with an unpaid 13:00–14:00 lunch
(net 480), grace 10/10, hour bands ABSENT < 240 / HALF_DAY 240–479 / PRESENT ≥ 480, late and early
bands 1–59 minor / ≥ 60 HALF_DAY, overtime always eligible and auto-approved.

| # | Scenario | Expected | Actual | Evidence | Result |
|---|---|---|---|---|---|
| 1 | Overnight shift + holiday + late OUT | Depends on P-01 | Whole shift HOLIDAY class by start date | Engine O5 | POLICY (P-01) |
| 2 | Overnight + weekly off + early arrival | Early arrival not credited | Not credited | Engine O3 | PASS |
| 3 | Half-day leave + overtime (FIXED) | 240 OT after the worked half | 240 | Engine L1 | PASS |
| 3b | Same, SPLIT shift | 120 OT | **0** | Engine S2 | **FAIL AR-06** |
| 3c | Same, FLEXIBLE, 10 h worked | Flag or decision | 360 OT + leave, no flag | Engine F5 | **FAIL AR-06** |
| 4 | Half-day leave + grace + late 1 min over | Decision D-02 | **Worked half fully LOP** | Engine T11 | **FAIL AR-02** |
| 5 | Half weekly off + full shift | Decision P-A | 240 OT, NORMAL | Engine W4 | POLICY (default) |
| 6 | Holiday + weekly off + roster override | Counted once as holiday; rostered = working day | As expected | Engine HD5; code | PASS |
| 7 | Shift change + approved leave | Leave re-derived or flagged | Flagged at close only | Code | **PARTIAL AR-10** |
| 8 | Roster change + calculated attendance | Day recalculated | Queued | Existing `test_recalc_queue.py` | PASS |
| 9 | Punch correction + auto-approved OT | Follows | Follows | API probe 3; existing test | PASS |
| 10 | Punch correction + human-approved OT | Reopen or cap | Reopen or cap | Existing tests | PASS (default P-C) |
| 11 | Incomplete + OT + lock | No OT on an absent day | LOP 1.00, OT 0 | API probe 2 | PASS |
| 11b | Then reopen and correct the day | OT returns | **PRESENT, detected 60, approved 0, REJECTED, validate READY** | API probe 2 | **FAIL AR-03** |
| 12 | Leave approved after calculation | Recalculated | Recalculated | Code; existing tests | PASS |
| 13 | Holiday inserted after leave approval | Not charged | Close blocked | Existing test | **PARTIAL AR-10** |
| 14 | Holiday removed after leave approval | Covered or flagged | Close blocked | Existing test | **PARTIAL AR-10** |
| 15 | Nth late day + overtime | HALF_DAY, no OT (P-B) | As expected; one day earlier is PRESENT + 165 OT | Engine PB2, PB3 | PASS (default) |
| 16 | Flexible + overnight + break | — | — | — | NOT VERIFIED |
| 17 | Split shift + missing punch | Decision D-09 | **HALF_DAY, not INCOMPLETE** | Engine S8 | **FAIL AR-14** |
| 18 | Regularization + leave + overtime | — | Parts pass separately | — | NOT VERIFIED combined |
| 19 | ON_DUTY + half-day leave | Decision D-07 | ON_DUTY 1.00, leave charged | Engine L16 | POLICY |
| 20 | Policy version published after calculation | Recalculated | Queued | Existing test | PASS |
| 21 | Employee moved between calendars | Recalculated from the start date | Queued by the assignment | Code | PASS (code) |
| 22 | Joining / exit date changed in an open period | Days recalculated | **Nothing queued** | Code | **FAIL AR-09** |
| 23 | Weekly cap after an earlier-day correction | Later day gets the freed budget | **Stays capped until recomputed** | API probe 3 | **FAIL AR-04** |
| 23b | Same punches, days calculated in a different order | Same result | **Mon 30 / Tue 60 vs Mon 60 / Tue 30** | API probe 3 | **FAIL AR-04** |
| 24 | Two simultaneous updates to one day | One wins cleanly | Existing concurrency tests pass | `test_attendance_concurrency.py`, `test_sweep_concurrency.py` | PASS; approval vs recalculation NOT VERIFIED |
| 25 | Repeated recalculation | No change | No change | Engine; existing test | PASS |
| 26 | Roster week-off worked 09–18 | Overtime, weekly-off class | **No overtime** | API probe 1 | **FAIL AR-01** |
| 27 | 11 minutes late on "Standard office" | Decision D-01 | **HALF_DAY, 0.50 LOP** | Engine T3, T6 | **FAIL AR-02** |
| 28 | 2 hours worked, early band HALF_DAY | ABSENT | **HALF_DAY, 0.50 paid** | Engine X1, X2 | **FAIL AR-05** |
| 29 | Half-day leave, arrives 20–30 min early | Normal day | **Flagged, OT zeroed, close blocked** | Engine L3, L4, N1 | **FAIL AR-07** |
| 30 | Work calendar's pattern removed | Sundays recalculated | **Stored day stays WEEKLY_OFF, paid** | API probe 4 | **FAIL AR-08** |

**Coverage missing from the repository:** an integration test for roster week-off work; grace +1 on
the templates; hour band against late/early band; half-day leave on SPLIT and FLEXIBLE; reopen
after a lock rejection; cap redistribution; approval against recalculation; property tests.

---

## Part 7 — Recalculation and data integrity

### Trigger matrix

"Queue" = `attendance_recalc_request`. Every queued request recalculates only **existing, unlocked**
rows, is safe to retry, and commits with the change that caused it.

| Mutation | People | Dates | Triggered? | Leave sync needed? | Neighbour days? | Failure leaves stale data? |
|---|---|---|---|---|---|---|
| Punch created (self or on behalf) | employee | punch date + its owner | Immediate; on failure a durable request | No | Owner yes; **previous owner no** (R-1) | Covered by the request |
| Regularization approved | employee | request date | In the approval transaction | No | Late/break counters cascade; **overtime caps do not** (AR-04) | Rolls back together |
| Punch superseded by regularization | as above | as above | as above | — | — | — |
| Shift version published | days on that shift | from `effective_from` | Queue | Should be (AR-10) | No | Retried 5 times, then abandoned (R-2) |
| Assignment created | employee | from its start | Queue | Should be (AR-10) | No | Same |
| Roster published / edited / swap | employee | that date | Queue | Should be (AR-10) | No | Same |
| Policy assignment created / ended | scope | from the date | Queue (not leave or regularization policies) | — | No | Same |
| Attendance / overtime policy published | its assignees | from `effective_from` | Queue | No | No | Same |
| Holiday created / edited / moved / deactivated | calendars linking it | old and new date | Queue | Should be (AR-10) | No | Same |
| Holiday calendar validity / active | same | oldest unlocked day → today | Queue | Should be | No | Same |
| Weekly-off pattern edited | calendars using it + direct assignees | oldest unlocked day → today | Queue | Should be | No | Same |
| Work calendar edited | its assignees | oldest unlocked day → today | Queue — **except pattern removed** (AR-08) | Should be | No | Same |
| Calendar exception created / edited | calendar's assignees | that date | Queue | Should be | No | Same |
| Leave approved / cancelled / days released | employee | each leave date | Immediate, same transaction | It is the sync | No | Rolls back together |
| ON_DUTY approved | employee | that date | In the approval transaction | No | No | Rolls back together |
| Employee break override created / changed | employee | from its start | **No** (AR-09) | No | No | Until the sweep or close |
| Employment created / edited / terminated | employee | from the changed date | **No** (AR-09) | Possibly | No | Until the sweep or close |
| Daily sweep | everyone | today and 2 days before | Yes | — | — | — |
| Period finalize | period's legal entity | every unlocked owned day | Yes, in date order per employee | Detector only | — | Whole finalize rolls back |

Locked days are protected in every row: `_ensure_date_open`, the `is_locked` check under
`FOR UPDATE`, and `replace_derived_fields` refusing a locked row.

### Versioning and snapshots

`ENGINE_VERSION` is 15 and stored on each row with `computation_snapshot`. Bumping the constant
does not recalculate anything: unlocked days computed under engine 14 keep their results until a
trigger, `calculate-range` or period close touches them. The remediation plan lists this as a manual
step after deploy.

### Concurrency and lock order

- Day calculation: `FOR UPDATE` on the day row before inputs are read; savepoint on first insert.
  PASS (existing tests).
- Overtime review now locks the day row first (`_lock_day_first`), matching calculation. The
  deadlock the last audit described is closed by design. **NOT VERIFIED** by a test that runs
  approval against recalculation.
- A recalculation that changes a record bumps its `version`, so an approver holding the old version
  gets a stale-record error. PASS (code).

### Plausible risks (not reproduced)

| ID | Risk |
|---|---|
| R-1 | A punch that moves another session to a different owner leaves the previous owner's day stale until the sweep or close |
| R-2 | A recalculation request is closed after 5 failed attempts with only an error log; the days stay stale until close |
| R-3 | A company-wide request over "oldest unlocked day → today" recalculates every unlocked row; with periods left open for months this is a long job competing with punches |
| R-4 | Timelines show only punches listed in the stored snapshot, so a punch stored after a failed immediate calculation is invisible on the day screen until the queue runs |

---

## Part 8 — Web, mobile and API consistency

Checked by reading client code and running the one affected web test file. No screen was clicked
through and the mobile app was not run.

| Area | Result |
|---|---|
| Day timeline uses backend-owned punches | Web PASS (10 tests). Mobile changed the same way; **not run** |
| Attendance policy form hides fields the engine ignores | Web yes. Mobile shows `work_on_leave_behaviour` |
| "Standard office" and "Strict attendance" templates | Produce the AR-02 cliff on any shift whose net hours equal the full-day band. The template text ("8 hours for a full day") does not warn that a late arrival beyond grace must be made up the same day |
| Close blocker text for work on leave | Says "full-day leave"; it now also covers half-day leave (AR-07) |
| Calendar impact preview | Text updated: leave is not changed automatically and close will refuse |
| Roster week-off cell | Cannot carry a shift (422), which is what makes AR-01 unavoidable |
| Overtime policy screen | Does not state P-D |
| Web and mobile parity for the remaining screens (shift, roster, leave, overtime approval, regularization, period close) | NOT VERIFIED in this audit |

---

## Part 9 — Remaining issues

### AR-01 — Work on a roster week-off earns no overtime (High · REPRODUCED, API)

- **Module:** roster, overtime.
- **Root cause:** `ShiftRosterCreate` and `ShiftRosterBulkCreateItem` reject a week-off row that
  carries a `shift_id` (`attendance/schemas.py:1286`, `:1302`). `work_schedule.shift_id_for` returns
  the roster row's shift, so the day has no shift. `evaluate_day` then takes `_evaluate_no_schedule`,
  which never detects overtime and reads only the calendar for `worked_on_weekly_off`. The AC-06
  fix (`_worked_on_weekly_off`) lives in `_evaluate_fixed_or_flex` / `_evaluate_split`, which this day
  never reaches.
- **Reproduction:** wired employee, overtime policy `AUTO`. Publish a roster row
  `{roster_date: 2026-08-10, is_week_off_override: true}`. Punch 09:00 and 18:00. Calculate.
  Result: `PRESENT, shift_id null, worked 540, ot_minutes_detected 0, ot_day_class null,
  worked_on_weekly_off false`; no overtime record. A row with both flags returns 422.
- **Impact:** rotating-roster staff who work their day off get nothing extra: no overtime, no
  comp-off, and no break deduction either. The four AC-06 unit tests pass because they hand the
  engine a shift the service cannot.
- **Fix:** on a roster week-off, resolve the shift the employee would otherwise have had (the
  assignment's) for eligibility and breaks, and treat all worked minutes as weekly-off overtime; or
  give `_evaluate_no_schedule` an off-day overtime rule. Needs D-03.
- **Tests:** API test for roster week-off work with and without an assignment shift.

### AR-02 — One minute past grace costs half a day, or the whole worked half (High · REPRODUCED, engine)

- **Module:** grace, hour bands, half-day leave.
- **Root cause:** `grace_band_credit` credits at most the grace minutes to the hour-band lookup.
  At grace + 1 the lookup is one minute short of the net schedule. When the PRESENT band starts at
  the net schedule (as `hourBands(480)` in `apps/web/src/lib/attendance-policy/templates.ts` does for
  an 8-hour net shift), the day is HALF_DAY. On a half-day-leave day `band_minutes` is doubled, and
  `_apply_leave_overlay` treats a HALF_DAY result as "worked half lost".
- **Reproduction (engine):**
  - Standard template, shift 09:00–17:00 no break: IN 09:10 → PRESENT; IN 09:11, OUT 17:00 →
    **HALF_DAY, 0.50 LOP**; IN 09:11, OUT 17:01 → PRESENT.
  - Same with 09:00–18:00 and an unpaid lunch (T6, T7).
  - Strict template (no grace): IN 09:01 → HALF_DAY.
  - First-half leave: IN 14:10 → paid 1.00; **IN 14:11, OUT 18:00 → status LEAVE, 0.50 LOP** for
    229 minutes worked; OUT 18:01 → paid 1.00.
- **Impact:** a routine late arrival removes half a day's pay unless the employee stays the exact
  number of minutes over. The late band the policy configured ("late", no penalty) is overridden by
  the hour band.
- **Fix:** needs D-01 and D-02. Options: let the late/early band decide when one matches; or keep
  hours-based bands and make the templates leave headroom; and pay a short worked half in proportion
  or send it for review instead of zero.
- **Dependencies:** P-07.

### AR-03 — Overtime rejected at lock stays rejected after reopen and correction (High · REPRODUCED, API)

- **Module:** overtime, period close.
- **Root cause:** `_withdraw_overtime_at_lock` writes `status = REJECTED` with no reviewer.
  `_resolve_ot_decision` treats every `REJECTED` record as a human decision and keeps it unless the
  detected minutes grow or the class changes (`service.py`, the `elif existing_ot_record.status ==
  "REJECTED": return frozen` branch). After a correction the minutes are the same, so it stays.
- **Reproduction:** punches 07:30 IN, 09:00 IN, 19:00 OUT → INCOMPLETE, 60 held. Finalize →
  LOP 1.00, record REJECTED. Reopen the period. Approve a `MISSING_PUNCH` regularization closing the
  stray IN. Result: `PRESENT, paid 1.00, ot_minutes_detected 60, ot_minutes_approved 0`, record
  `REJECTED`; `validate` returns `READY`.
- **Impact:** legitimate overtime is lost with no blocker and no pending item for anyone to act on.
- **Fix:** mark a system rejection as such (a distinct status or flag) and re-derive it like an
  automatic decision when the day is no longer INCOMPLETE.
- **Tests:** the probe above as a permanent test.

### AR-04 — Weekly and monthly overtime caps depend on calculation order and go stale (Medium, High where day classes differ · REPRODUCED, API)

- **Module:** overtime.
- **Root cause:** `sum_minutes_counted_for_cap` sums every other day of the week or month, earlier
  and later alike, as they stand in the database. Nothing recalculates sibling days when one day's
  overtime changes (`_recompute_later_days_of_month` runs only for the late and break counters).
- **Reproduction:** cap 90 a week; 60 minutes of overtime on Monday and Tuesday.
  - Calculated Tuesday then Monday: Monday 30, Tuesday 60. Calculated Monday then Tuesday: Monday
    60, Tuesday 30. Period close recalculates in date order and keeps whichever split it finds.
  - Correct Monday to no overtime: Tuesday stays at 30 with no request queued; a manual recompute
    gives 60. Period close repairs this case.
- **Impact:** the same punches can produce different approved minutes per day. When the days have
  different classes (a Sunday and a Monday) the amount paid differs.
- **Fix:** allocate the budget in date order (count only earlier days), and recalculate the later
  days of the week and month when a day's counted overtime changes. Needs D-04.

### AR-05 — A late or early band softens a harsher hour band (Medium · REPRODUCED, engine)

- **Root cause:** `_resolve_primary_status` takes the hour-band status, then returns `HALF_DAY`
  whenever a late or early classification is `HALF_DAY`, even if the hour band said `ABSENT`.
- **Reproduction:** worked 09:00–11:00 (120 minutes). With no early bands: ABSENT, LOP 1.00. With an
  early band "≥ 60 minutes = HALF_DAY": **HALF_DAY, 0.50 paid**. Same for a late arrival at 16:00.
- **Impact:** adding a penalty band pays more than having none.
- **Fix:** take the harshest of the hour-band status and the overrides.

### AR-06 — Half-day-leave overtime rules apply to FIXED shifts only (Medium · REPRODUCED, engine)

- **Root cause:** `_evaluate_split` has no half-day handling. For FLEXIBLE the basis is halved but
  `_half_interval` returns nothing, so work in the leave half cannot be detected.
- **Reproduction:**
  - SPLIT 09–13 and 17–21, first-half leave, worked 17:00–23:00 → **0 overtime** (expected 120).
  - SPLIT, second-half leave, both blocks worked → paid 1.00 with the leave still charged, no flag.
  - FLEXIBLE 480, half-day leave, worked 600 → 1.00 paid **and 360 overtime**, no flag.
- **Impact:** the two AC-05 failure modes (lost overtime, leave time paid twice) remain for these
  shift types.
- **Fix:** give SPLIT a per-block basis; for FLEXIBLE decide whether work beyond the halved
  requirement on a leave day is overtime or a conflict.

### AR-07 — The half-day-leave flag fires on ordinary early arrival (Medium · REPRODUCED, engine)

- **Root cause:** `_work_in_leave_half` measures raw punch overlap with the leave half against a
  tolerance equal to the grace minutes. Arriving early for the worked half is overlap.
- **Reproduction:** first-half leave, second half starts 14:00 (or 13:30 with no lunch):
  - IN 12:40, OUT 18:00 → flagged. IN 12:40, OUT 20:00 → flagged and **the 2 hours of overtime are
    removed**. IN 13:00 on the no-lunch shift → flagged.
  - Second-half leave, OUT 14:20 → flagged.
  - IN 13:20 (10 minutes early, inside the tolerance) → not flagged, and 10 minutes of overtime are
    credited for arriving early, which a FIXED shift never does otherwise (P-04).
- **Impact:** each flagged day blocks period close until HR opens it. The blocker text says
  "full-day leave". Confirming the leave keeps the overtime at zero; the only way to restore it is
  to cancel the leave.
- **Fix:** clamp presence to the worked half before measuring (as `clamp_pairs_to_start` does for
  the shift start), flag only substantial work in the leave half, and correct the message.

### AR-08 — Removing a work calendar's weekly-off pattern queues no recalculation (Medium · REPRODUCED, API)

- **Root cause:** `update_work_calendar` applies `weekly_off_pattern_id: null` (it checks
  `model_fields_set`), but the recalculation guard tests `patch.weekly_off_pattern_id is not None`
  (`organisation/service.py:4453`).
- **Reproduction:** calendar with a Sunday pattern; Sunday 9 Aug calculates `NOT_EXPECTED /
  WEEKLY_OFF / paid 1.00`. `PATCH {"weekly_off_pattern_id": null}` → 200, no request queued, stored
  day unchanged. A recompute gives `INCOMPLETE / WORKING`.
- **Fix:** test `"weekly_off_pattern_id" in patch.model_fields_set`.

### AR-09 — Employment and break-override changes queue no recalculation (Medium · CODE-CONFIRMED)

- **Root cause:** `request_recalc` has no caller in `create_employment`, `update_employment`,
  `terminate_employment` (`employee/service.py:1131`, `:1309`, `:1388`) or in
  `break_override_service.py`.
- **Impact:** a back-dated exit leaves days after the last working day as ABSENT or INCOMPLETE
  instead of `EXITED`; a corrected joining date leaves `NOT_JOINED` days. Stored rows are wrong on
  every screen and reminder until the sweep (3 days) or period close.
- **Fix:** queue from the changed date for that employee.

### AR-10 — Leave is still not reconciled with calendar or schedule changes (Medium · CODE-CONFIRMED; AC-03 partly fixed)

- **What exists:** `LeaveCalendarReconciliationService.find_discrepancies` and the
  `LEAVE_CALENDAR_MISMATCH` close blocker.
- **What is missing:**
  - No refund or re-debit; HR's only tool is to cancel the leave and apply again.
  - Nothing happens when the change is made, except the calendar preview's warning. Roster, shift
    and assignment changes give no warning at all (P-12).
  - Until close, the attendance day and the leave balance are both wrong.
  - Cross-application sandwich days are skipped, not checked.
  - Only `APPROVED` applications are examined; pending ones are LV-04.
- **Fix:** needs D-06. The proposed workflow in `ATTENDANCE_LEAVE_CALENDAR_RECONCILIATION.md` is sound.

### AR-11 — `AUTO_CLOSE` closes nothing and lets overtime through (Low–Medium · REPRODUCED, engine)

- **Reproduction:** pair 09:00–20:00 plus a stray IN at 20:45. Under `INCOMPLETE`: held. Under
  `AUTO_CLOSE`: **PRESENT, 120 overtime auto-approved**, `auto_closed false`. With only an IN,
  `AUTO_CLOSE` gives INCOMPLETE.
- **Impact:** limited — the web form offers the option only when a stored version already uses it.
  Any such version bypasses AC-04.
- **Fix:** remove the option or implement it.

### AR-12 — Short shifts: full attendance is a half day and overtime can never be earned (Medium · REPRODUCED, engine)

- **Reproduction:** shift 09:00–13:00 under the standard bands. Worked 09:00–13:00 → HALF_DAY,
  0.50 LOP. Worked 09:00–15:00 → HALF_DAY and **0 overtime**, because P-B removes overtime from any
  HALF_DAY day.
- **Fix:** needs P-05 (bands relative to the shift, or per-shift policies). Until then, P-B should
  not apply when the hour band alone caused the status on a shift shorter than the band.

### AR-13 — Half weekly off records the worked half as hours late or early (Low–Medium · REPRODUCED, engine)

- **Reproduction:** half weekly off. Worked 14:00–18:00 → PRESENT, paid 1.00, **late 290,
  `is_late` true**. Worked 09:00–13:00 → early 290.
- **Impact:** pay is right. The day counts toward `lates_to_half_day_count`, shows in late and
  early-departure reports, and would trigger `early_departure_requires_approval`.
- **Fix:** the policy needs to say which half is off, or lateness must not be measured on these days.

### AR-14 — Split shift: a missing punch in one block becomes a half day (Medium · REPRODUCED, engine)

- **Reproduction:** blocks 09–13 and 17–21; punches 09:00 IN, 13:00 OUT, 17:00 IN, no OUT. Result
  under the default `split_shift_missed_block_behaviour = HALF_DAY`: **HALF_DAY, 0.50 LOP,
  `missing_punch` true**. A FIXED shift with the same forgotten OUT is INCOMPLETE and reviewed.
- **Fix:** an orphan punch inside a block should make the day INCOMPLETE before the missed-block
  rule is applied. Needs D-09.

### Lower-priority items

| ID | Item | Evidence |
|---|---|---|
| AR-15 | Mobile shows `work_on_leave_behaviour`, which does nothing | Code |
| AR-16 | `ATTENDANCE_OVERTIME_REMEDIATION_PLAN.md` points to `ATTENDANCE_OVERTIME_REMEDIATION_RESULTS.md`, which does not exist; `leave/reconciliation.py` cites `docs/ATTENDANCE_LEAVE_CALENDAR_RECONCILIATION.md` (the file is under `docs/audits/`) | Code |
| AR-17 | Bumping `ENGINE_VERSION` recalculates nothing by itself | Code |
| LV-01 … LV-13 | Leave audit findings, unchanged | Leave audit |

### Test gaps

| ID | Gap |
|---|---|
| TG-01 | `test_self_punch_on_last_working_day_passes_and_after_it_is_rejected` fails when run between 00:00 and about 06:00 UTC: the OUT punch still belongs to yesterday's shift window. The product behaviour is correct; the test depends on the time of day |
| TG-02 | `tests/unit/core/test_settings.py::test_development_has_no_explicit_origins_but_a_valid_fallback` fails on this machine because the local `.env` sets CORS origins |
| TG-03 | AC-06 has unit tests only, with inputs the service cannot produce |
| TG-04 | No test runs overtime approval against a concurrent recalculation |
| TG-05 | No property-based tests for the invariants (approved ≤ detected, fractions sum to 1.00, idempotence, single owner per punch) |
| TG-06 | No 00:00 / 05:30 IST boundary tests for the engine-15 rules |
| TG-07 | Mobile Dart change not run (Flutter is not installed here) |

---

## Part 10 — Remediation roadmap

**Critical / High — before the payroll audit**
1. AR-01 roster week-off overtime (needs D-03).
2. AR-02 grace cliff and the half-day-leave case (needs D-01, D-02).
3. AR-03 system rejection at lock must not behave as a human rejection.
4. AR-04 cap allocation and sibling recalculation (needs D-04).

**Medium — same engine pass, one `ENGINE_VERSION` bump**
5. AR-05 harshest status wins.
6. AR-06 half-day leave on SPLIT and FLEXIBLE.
7. AR-07 early arrival is not work on leave; fix the blocker text.
8. AR-14 split-shift missing punch (needs D-09).
9. AR-12 short shifts (needs P-05).

**Medium — triggers and reconciliation**
10. AR-08 pattern removal.
11. AR-09 employment and break-override triggers.
12. AR-10 leave reconciliation (needs D-06), and LV-04 pending-leave blocker.

**Low**
13. AR-11, AR-13, AR-15, AR-16, AR-17.

**Policy decisions:** D-01 … D-10 (Part 4). D-01 to D-04 block items 1, 2 and 4.

**Tests:** TG-01 … TG-07, plus permanent versions of the four API probes and the engine cases
marked FAIL in Part 6.

After the engine changes: recalculate unlocked days of open periods with
`POST /attendance/days/calculate-range`, then run `scripts/sql/attendance_integrity_report.sql`.

---

## Part 11 — Final verdict

**ATTENDANCE RULES NOT VERIFIED — IMPORTANT ISSUES REMAIN.**

Can every combination of shift, roster, grace, leave, overtime, holiday, weekly off, break,
regularization and policy give one deterministic, explainable and correct result? **Not yet.**

- **Deterministic:** yes for the day result given its inputs. No for overtime under a weekly or
  monthly cap, where the result depends on the order days were calculated (AR-04).
- **Explainable:** mostly. The snapshot records inputs and derived values. The AR-02 result ("late
  one minute, half day lost") is explainable from the snapshot but not from the policy screen.
- **Correct:** no for roster week-off work (AR-01), grace + 1 on the shipped templates (AR-02),
  overtime after a reopened lock rejection (AR-03), hour band against late band (AR-05), half-day
  leave on split and flexible shifts (AR-06) and split-shift missing punches (AR-14).

What can be relied on now: one schedule and one calendar answer per employee-date; punch ownership;
FIXED-shift results on working days, holidays and full weekly offs; decided overtime following
corrections; the close sequence and its blockers; locked rows staying locked.

"Critical defects" was not chosen because none of the remaining issues corrupts a closed period
silently in the common FIXED-shift, calendar-weekly-off case; each affects a specific configuration
or sequence. "Mostly verified" was not chosen because AR-01 to AR-03 produce wrong pay inputs in
configurations the product ships or encourages.

---

## Appendix A — Tests and probes

### Environment

Database `hrms_test` on `localhost:5433` (isolated; at migration head `20261116090000`), Redis
`localhost:6380/1`, Celery DB 14, `TZ=UTC`. The development database was not touched.

```
DATABASE_URL=postgresql://hrms:…@localhost:5433/hrms_test  MIGRATIONS_DATABASE_URL=<same>
REDIS_URL=redis://localhost:6380/1  HRMS_TEST_CELERY_DB=14  FACE_PROVIDER_COMPARISON_ENABLED=false  TZ=UTC
```

### Existing suites

| Command | Result |
|---|---|
| `.venv/bin/python -m pytest tests/unit -q` | 2,079 tests: **2,078 passed, 1 failed** (TG-02) |
| `.venv/bin/python -m pytest tests/integration/modules/attendance tests/integration/modules/leave -q` | 1,017 tests: 988 passed, 5 failed, 24 errors on the first run |
| Re-run of the 27 distinct failed or errored tests alone | **26 passed, 1 failed** (TG-01) |
| `npx vitest run src/lib/attendance/day-detail.test.ts` (web) | 10 passed |

The 29 first-run failures were caused by this audit, not by the code: the probe file was run against
the same test database while the suite was running, and the two collided on shared fixture rows
(`plan` codes, `scoped-%` users). Run alone, all but TG-01 pass. **The suite was not re-run in full
after that, so "all 1,017 pass in one clean run" is not claimed.**

Not run: the organisation, payroll, employee and security integration suites; ruff, mypy and
import-boundary checks; the rest of the web tests; any mobile test; any property-based or new
concurrency test. No tests were skipped by pytest.

### Engine probe

In-memory, built on the unit-test helpers `_base_input`, `_policy`, `_shift` with the setup in
Part 6. About 110 cases; the IDs quoted in this report (B0, G1–G10, PB1–PB3, L1–L17, N1–N3, S0–S9,
F0–F6, W1–W10, HD1–HD7, R1–R7, I1–I5, SS1–SS2, O1–O5, X1–X2, T1–T13) are those cases. Template
cases T1–T13 use no late or early bands, as the templates do. The script was kept outside the
repository and is not part of this change.

### API probes

One temporary test file next to the attendance integration tests, reusing `_build_wired_employee`,
`_create_overtime_policy`, `_create_regularization_policy`, `_publish_roster`, `_create_period`. It
ran four probes (roster week-off work; lock rejection then reopen; weekly cap order and staleness;
calendar pattern removal), all of which completed, and was deleted afterwards. `git status` shows no
trace of it.

### Clean-up note

`hrms_test` held 11 `company` rows before this audit and 15 after: four tenants were left behind by
fixture teardowns that failed during the collision described above. They contain no attendance
days or overtime records. They are in the disposable test database only and were left in place
rather than deleted by hand.
