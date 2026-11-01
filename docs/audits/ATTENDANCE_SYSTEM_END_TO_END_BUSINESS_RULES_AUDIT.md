# Attendance System — End-to-End Business Rules Audit

Read-only audit. No application code, tests, migrations or git state were changed. The only artefact
created is this file. A throw-away probe script was run **outside the repo** (scratchpad) against the
pure engine `calculation.evaluate_day` to turn suspicions into evidence; it wrote nothing.

- Branch `main`, HEAD `efd342b`. Working tree: 19 modified + 17 untracked files (break management V1,
  early-punch credit clamp, flexible OT, shift-form UI, `pending task.md`). Nothing was touched.
- Evidence labels: **VERIFIED** (read in code and/or reproduced with the probe), **INFERRED** (follows
  from code, not executed), **NOT VERIFIED** (not examined).
- Location labels: **HEAD**, **WT** (working tree only), **BOTH**.
- Probe = `evaluate_day` run with Asia/Kolkata, policy grace-in 10 / grace-out 5, hour bands
  <240 ABSENT, 240–419 HALF_DAY, ≥420 PRESENT, a 60-min auto-deducted unpaid lunch, OT policy
  `ALWAYS`, `requires_post_approval=True`. Shift 09:30–18:30 unless stated.

## Scope honesty (what this audit did NOT cover)

NOT VERIFIED: web UI behaviour (only grep-level), mobile beyond the day-detail/history widgets,
DST transitions, router-level permission matrix (relied on service guards + prior security audit in
`docs/audits/attendance-only-production-readiness/05`), Celery beat schedule contents, payroll module
consumption of attendance figures, integration tests (not run; a DB is required), leave-balance ledger
maths (only the attendance projection seam was read). Where a conclusion depends on these it says so.

---

## 1. Executive summary

| | |
|---|---|
| **Maturity** | **6.5 / 10** — strong structure (pure engine, snapshots, period locks, frozen OT, self-approval blocks), but several payroll-relevant rules are wrong or undecided. |
| **Production readiness** | **READY WITH CONDITIONS** — not safe for payroll use until P0 items in §21 are fixed or consciously accepted. |

Counts: confirmed bugs **9** · business decisions required **7** · payroll risks **6** · security risks **0 confirmed** (2 not verified) · UX problems **6**.

Top priority before release:
1. Off-day work (weekly off / holiday) is run through the *working-day* hour bands → a short shift on a paid weekly off becomes **ABSENT + 1.00 LOP** (B-01).
2. Approved overtime survives a later full-day leave approval and is still written to the day row (B-02).
3. `requires_pre_approval` on the OT policy is stored and never enforced — OT is always created from raw presence (B-03).
4. Flexible shifts flag lateness against the *start* of the window, so arriving mid-window is "late" (B-04).
5. Early punch credit clamp covers FIXED only; SPLIT early arrival still becomes overtime (B-05); nothing at all in HEAD.

Positive findings worth keeping: raw vs credited punches are kept separate (VERIFIED, probe A); break
deductions are unioned over presence so nothing is deducted twice (probe F); recompute of one date is
idempotent for the same inputs (`_calculate` is full-replace, WD-10); locked periods are refused by two
independent guards; approval stages match the snapshotted approver, self-approval is blocked for both
regularization and OT.

---

## 2. Architecture map (traced)

| # | Stage | Code | Notes / enforcement |
|---|---|---|---|
| 1 | Punch request | `router.py` self route → `PunchService.record_punch_outcome` `service.py:2776` | Server clock is the punch time for self-service (`requested_punch_time=None`); on-behalf must be ≤ now (`FuturePunchTimeError`). Server-side. |
| 2 | Employee visibility | `_ensure_employee_visible` | Scope + company check before anything else. Server-side. |
| 3 | Face / liveness | `_ensure_plain_punch_allowed` `:3208`; `face_service.py`, `liveness.py` | ENROLLED employees can't use plain WEB punch. Server-side. |
| 4 | Geofence | `GeofenceService.enforce` (WEB, FACE only) | HR/ADMIN/REGULARIZATION sources skip it. |
| 5 | Shift window | `enforce_shift_window` `:2966`, `shift_window.py` | Only refuses punch-IN earlier than `shift start − early_in_allowance`. Everything else is accepted. Fails open on any ambiguity. Server-side. **HEAD + WT** (policy column from migration `20261102090000`). |
| 6 | Employment / period gate | `_ensure_not_after_last_working_day`, `_ensure_punch_date_open` | Accepts if local date **or** previous date is open. |
| 7 | Punch storage | `Punch` append-only, idempotency key | Never edited. |
| 8 | Immediate calc | `_try_immediate_calculate` in a SAVEPOINT, errors swallowed | Date = **company-timezone** local date of the punch (not shift-owner date). |
| 9 | Input build | `_build_calculation_input` `:4050` | Roster(PUBLISHED) > assignment shift; branch tz → company tz; calendar; policies; leave projections; OT caps; sibling-day counters. |
| 10 | Punch load window | `calc.resolve_schedule_window` | FIXED ±2 h; FLEXIBLE −2 h/+12 h; SPLIT ±2 h; no shift = calendar day. |
| 11 | Collapse / pair | `collapse_duplicate_punches`, `pair_punches` | Orphan IN/OUT → `missing_punch`. |
| 12 | Credit | `credit_cutoff_for`, `clip_pairs_at`, `clamp_pairs_to_start` | **WT only.** Clamp is FIXED only. |
| 13 | Breaks | `compute_breaks` | **WT only** (V1). Legacy mode-less breaks keep gap matching. |
| 14 | Worked time | `worked_minutes_from_gross` | PAIR_ALL excludes gaps; FIRST_IN_LAST_OUT subtracts. |
| 15 | Late / early-out | `_evaluate_fixed_or_flex` | `first_in` / `last_out` are **raw** (not credited). |
| 16 | Status | `_resolve_primary_status` | Hour bands → late/early/core/cumulative overrides. |
| 17 | OT detection | `detect_overtime` | `max(0, worked − net scheduled)`; rounding, caps. |
| 18 | Overlays | `_apply_overlays`: off-day pay → half weekly off → ON_DUTY → leave | Leave wins. |
| 19 | OT decision | `_resolve_ot_decision` / `_sync_overtime_record` | Frozen once not PENDING. |
| 20 | Persist | `AttendanceDayService._calculate` | `FOR UPDATE`, bounded lock timeouts, full replace. |
| 21 | Approval | `OvertimeRecordService.approve/reject`, `RegularizationRequestService` | Version-checked, approver identity matched, self-approval blocked. |
| 22 | Lock | `AttendancePeriodService.finalize/reopen`, `_ensure_date_open` | Period per legal entity. |

Triggers that recompute a day: new punch (immediate), nightly sweep (**trailing 3 days only**,
`tasks.py:58`), manual single/range recompute, regularization apply, break event/override change
(`break_service.py:740`), leave projection sync/cancel. **No** trigger exists for holiday, roster,
shift-version, assignment, or policy changes (VERIFIED by grep: no `.calculate(` call in
`organisation/`, `employee/`).

---

## 3. Business-rule map (tables → who decides what)

| Rule | Decided by | Server-enforced |
|---|---|---|
| Earliest punch-in | `early_in_allowance_minutes` (attendance policy version) | Yes, self-service WEB/FACE only |
| Late | `first_in − scheduled_start − grace_in`, then `late_bands` | Engine |
| Early out | `scheduled_end − last_out − grace_out`, then `early_bands` | Engine |
| Present / half / absent | `hour_bands` on worked minutes, plus late/early/core/cumulative overrides | Engine |
| Overtime | `worked − net scheduled`, OT policy eligibility, min, rounding, caps | Engine |
| OT approval | `approval_chain` + `requires_post_approval` | Service |
| Leave | `LeaveDayProjection` rows (adapter from Leave module) | Service |
| Locked | `AttendancePeriod` CLOSED + `AttendanceDay.is_locked` | Service |

Early-in allowance ≠ grace-in ≠ OT: **VERIFIED separate** — three different fields, three different code
sites (`shift_window.py`, `_evaluate_fixed_or_flex` late calc, `detect_overtime`). The only coupling is
that the clamp (WT) is what keeps the first from leaking into the third.

---

## 4. Attendance calculation flow

| Value | Source | Calculation | Stored | Used by |
|---|---|---|---|---|
| actual first in / last out | `presence_span(pairing.pairs)` over **raw** punches | first IN of first pair, last OUT of last pair | `actual_first_in/last_out` | late, early-out, UI |
| scheduled start/end | `resolve_schedule_window` | shift local time → UTC; FLEX = start *window*; SPLIT = first/last block | `scheduled_start/end` | late, early-out, clamp |
| gross elapsed | `last_out − first_in` | raw | `gross_elapsed_minutes` (WT) | UI, snapshot |
| credited pairs | `clip_pairs_at(cutoff)` then `clamp_pairs_to_start` (FIXED) | evaluation copy only | not stored | gross, breaks |
| gross minutes | `presence_span(credit_pairs)` | PAIR_ALL sum / FIRST_IN_LAST_OUT span | snapshot | worked |
| break minutes | `compute_breaks` | events replace scheduled deduction; union over presence | `unpaid/paid/excess/actual_break_minutes` | worked, status |
| worked minutes | gross ± breaks | `worked_minutes_from_gross − v1_deducted` | `worked_minutes` | bands, OT |
| late minutes | raw `first_in` vs `scheduled_start` | `max(0, diff − grace_in)` | `late_minutes` | bands, counters |
| early-out minutes | raw `last_out` vs `scheduled_end` | `max(0, diff − grace_out)` | `early_departure_minutes` | bands |
| OT minutes | worked vs net schedule | `max(0, worked − (sched − unpaid sched breaks))` | day + `overtime_record` | approval, payroll |
| status | `_resolve_primary_status` + overlays | see §10 | `attendance_status` | everything |

Raw vs credited mixing (VERIFIED, probe A/B/C/D): punch 09:00–18:30 on a 09:30–18:30 shift keeps
`actual_first_in=09:00`, late = 0, worked = 480 (570 − 30 early − 60 lunch), **OT = 0**. Early + stay late
(C) gives OT 60 = only the post-shift hour. Early + leave early (D) → 70 min early-out, HALF_DAY.
Late is correctly computed from the raw timestamp. **WT only** — in HEAD the clamp does not exist, so
case A produces 30 min of OT (inferred from `clamp_pairs_to_start` HEAD count = 0).

Observation: `worked_minutes` is *credited* net time and `gross_elapsed_minutes` is raw span; the API
exposes both but the mobile/web UI shows only first-in/last-out and worked (see §19).

---

## 5. Shift behaviour

Types: `FIXED`, `FLEXIBLE`, `SPLIT`; overnight is a flag (`is_cross_midnight`) on FIXED; rotation is the
roster (`ShiftRoster`). Resolution precedence (VERIFIED, `service.py:4099-4113` and `:3030-3040`):
**published roster entry > employee assignment shift > none** (→ `missing_shift_behaviour`). Draft rosters
never affect calculation. Shift version chosen by `resolve_shift_version_as_of(target_date)`; timezone
`shift version > branch > company`.

| Scenario | Result | Evidence |
|---|---|---|
| FIXED early 30 min | not late, not OT, credit from start | probe A (WT) |
| FIXED late 60 + stay 60 | late 50 (after grace), OT 0 — lateness is *netted* against the extra hour | probe E |
| SPLIT early 30 min | **OT 30 pending** — clamp not applied | probe N (B-05) |
| FLEX window 09–10, arrives 09:30 | **late 20** | probe Q (B-04) |
| FLEX arrives 08:45, 9 h | not late, OT 60 vs 8 h required | probe U |
| Overnight 22–06, 21:30→06:00 | PRESENT, worked 480, OT 0 | probe R1 |
| Overnight 22:00→07:00 | OT 60, class NIGHT | probe R2 |
| Overnight with break 00:30–01:30 | worked 420, nothing wrongly attributed to next day | probe R3 |

Overnight date assignment (INFERRED): the immediate-calculate trigger uses the **company-local calendar
date of the punch** (`:3290`), so a 06:00 OUT is first computed for the *next* date, which loads its own
window; the day's own sweep (trailing 3 days) later corrects it. The engine itself assigns by shift-start
date. This is why an overnight worker can briefly see a wrong "today" status until the sweep (no data
loss, but see UX-02).

Punch-load window overlap (INFERRED, not reproduced): window = shift ±2 h (FLEX +12 h). A roster that puts
a night shift (to 06:00) before a day shift starting ≤ 08:00 the next day produces overlapping windows;
the 06:00 OUT is loaded by both dates. Risk is low for fixed single-shift employees, real for rotating
rosters (B-09).

Terminated / future / historical: `population_status` gate gives NOT_JOINED / EXITED before anything else;
`_ensure_not_after_last_working_day` blocks self punches after last working day. Shift change mid period:
each date resolves its own shift version, but **already-computed unlocked days are not recomputed**
(§12).

---

## 6. Break behaviour (WT only)

All break-management V1 code is uncommitted. Verified through code + probe F:

- Normal break auto-deducted (60 min) when no event recorded; a recorded event replaces the scheduled
  deduction (no 55+60 double count) — `compute_breaks` comment and code agree.
- Punch gaps vs V1 rules: a V1 rule (`mode` set) is never matched to a punch gap. A 2 h punched lunch
  with an AUTO_DEDUCT 13–14 rule gives worked 420 (the gap is excluded by PAIR_ALL; no second deduction
  because presence inside the window is 0). **But the excess lunch is not flagged** — only
  hours-based status reacts. (Business decision BD-04.)
- Open break START: while the day can still receive punches and no OUT follows it = *active* (presence
  keeps being credited); once the day closes or the employee punches out after it = `UNRESOLVED`, credit cut at the START, status forced `INCOMPLETE` (never half/absent) —
  VERIFIED in `_evaluate_fixed_or_flex:2106`.
- Negative durations: `actual = max(0, …)`; clip uses interval intersection, so break time outside
  presence deducts 0. No negative path found.
- Break during overtime: break is deducted from worked time wherever it falls, so a break in the extra
  hours reduces OT; OT compares against *net* schedule so a normal lunch does not create OT (comment at
  `:2127`).
- FIRST_IN_LAST_OUT mode (INFERRED, gap): gross spans the gaps, but V1 events only deduct inside
  *presence* (credit pairs), and V1 rules never match gaps → a punched-out gap is **not deducted** in this
  mode unless a legacy rule matches it. Check whether any policy uses FIRST_IN_LAST_OUT with V1 breaks
  (B-08).
- Midnight crossing: rules carry `crosses_midnight`; legacy matching uses wrap-aware containment
  (`_break_window_contains`). Probe R3 fine.

---

## 7. Overtime behaviour

| Q | Answer | Evidence |
|---|---|---|
| What creates OT? | `worked_minutes − net scheduled > min_ot_minutes` on any day where the OT policy's eligibility allows | `detect_overtime` |
| Authorization before work? | **No.** `requires_pre_approval` is stored on `OvertimePolicyVersion` and read nowhere (`grep` → only the create call `service.py:1059`) | VERIFIED (B-03) |
| Auto-approved? | If `requires_post_approval=False` **or** `approval_chain=AUTO` → `AUTO_APPROVED` immediately, even though the policy says post-approval is required | `_resolve_ot_decision:4531-4540` |
| Approval before/after calculation? | After. Approver approves `minutes_detected` as a whole — cannot adjust | `approve:5884` |
| Recalc changes pending OT? | Yes, in place (`replace_pending_for_day`) — a `DETECTED` action and audit row are appended **each recompute** | `_sync_overtime_record` |
| Recalc changes approved OT? | No — frozen (WD-29-2) | `:4485` |
| Historical OT silently changes? | Pending: yes, by design. Approved: no — but the *day row* can diverge from the frozen record (B-02, B-06) | |
| Early attendance → OT? | FIXED: no (WT). SPLIT: **yes** (B-05). HEAD: yes for all | probes A, N |
| OT without explicit authorization? | Yes — any eligible presence beyond schedule | |
| Holiday / weekly off? | OT = `worked − scheduled`. 9.5 h on a holiday → OT 30; **8 h on a weekly off → OT 0**, 4 h → ABSENT | probes I, H, G, T |

Payroll-relevant ranking: whole-day work on an off day earning no OT/comp-off (BD-01) is the largest
financial exposure.

Weekly/monthly cap (VERIFIED, `sum_minutes_detected_for_range`): remaining budget = cap − sum of all
other days in the **week/month, including later days**. Recomputing Monday after Wednesday has consumed
budget yields a *lower* Monday than the first calculation → results depend on calculation order, not just
inputs (B-07). Only pending/auto records are affected; approved ones are frozen.

---

## 8. Leave interaction

Overlay order (VERIFIED `_apply_overlays`): off-day pay → half weekly off → ON_DUTY → **leave**.

| Scenario | Result | Evidence |
|---|---|---|
| Full-day leave, no punches | LEAVE, paid per leave type, LOP if unpaid | code |
| Full-day leave + punches | LEAVE, worked kept (540), OT/late/early zeroed, `work_on_leave_flagged`; period close **blocked** until HR resolves | probe M, `keep_leave_over_punches` |
| Half-day leave + full day worked | HALF_DAY, paid 1.0 (leave 0.5 + work remainder) | probe K/L |
| Half-day leave (AM), arrives 13:30 | `late=230`, `is_late=True` — late is measured against the **full-day** shift start | probe K (B-06) |
| Leave on holiday / weekly off | LEAVE wins (leave projected redundantly); calendar type still reports HOLIDAY/WO | `_apply_leave_overlay` doc |
| Leave approved after attendance exists | `LeaveProjectionService.sync` → synchronous `calculate`; refused if period closed | `:7152`, `:7249` |
| Leave cancelled after approval | `cancel` → recompute; refused if period closed | `:7326`, `:7357` |
| Leave approved after OT was **approved** | day becomes LEAVE but `ot_minutes_approved` **keeps the frozen value** | B-02 |
| Leave approved with OT **pending** | pending record deleted (`decision None`) | correct |
| Backdated / future leave | Future: projection row only, day computed when reached. Backdated: allowed unless period closed | |
| Leave balance interplay | not verified (Leave module) | NOT VERIFIED |

Precedence matrix (VERIFIED from code):

| Priority | Condition | Final result |
|---:|---|---|
| 1 | Not employed on date | NOT_JOINED / EXITED (leave/OD overlays skipped) |
| 2 | Locked period / locked day | Calculation refused; row unchanged |
| 3 | CONFIG_ERROR (no tz/calendar/policy) | CONFIG_ERROR (overlays skipped) |
| 4 | Approved full-day leave | LEAVE (beats everything below, incl. ON_DUTY) |
| 5 | Approved ON_DUTY (no punch required) | ON_DUTY, paid 1.00 |
| 6 | Half-day leave | HALF_DAY if worked else LEAVE |
| 7 | Roster week-off override with no punches | NOT_EXPECTED |
| 8 | Holiday / weekly off / shutdown, no punches, shift not operating | NOT_EXPECTED (paid by BUS-001) |
| 9 | Punches | hour bands → overrides (B-01 applies here on off days) |
| 10 | No punches on working day | INCOMPLETE (default) or ABSENT (policy) |

---

## 9. Holiday / weekly-off interaction

- Unworked: `NOT_EXPECTED`, paid 1.00 for MONTHLY, unpaid weekly-off for DAILY_WAGE (BUS-001).
- Half-day weekly off: off half paid, working half paid only if worked (PAY-012).
- Worked: status comes from the **working-day hour bands** (no off-day branch):
  - 9 h on holiday → PRESENT, OT 30 (probe I)
  - 8 h on weekly off → PRESENT, OT 0 (probe H)
  - **3.5 h on weekly off → ABSENT, LOP 1.00, early-out 295** (probe G) and **3 h on holiday → ABSENT, LOP 1.00** (probe T) — B-01
- Double credit: not possible (PRESENT = 1.00 once). The opposite problem exists: the employee is
  paid the day off *and* nothing extra for working it (BD-01).
- Leave on an off day: leave overlay applies even though nothing would be deducted; Leave module is
  assumed not to consume balance (NOT VERIFIED).
- Employee/location-specific holidays: resolved by `CalendarResolutionService` (outside attendance;
  NOT VERIFIED).

---

## 10. Status model

Primary statuses (mutually exclusive column `attendance_status`): `PRESENT, ABSENT, HALF_DAY, LEAVE,
ON_DUTY, NOT_EXPECTED, NOT_JOINED, EXITED, INCOMPLETE, CONFIG_ERROR`. Flags (independent booleans):
`is_late, is_early_out, is_overtime, missing_punch, auto_closed, worked_on_holiday,
worked_on_weekly_off, work_on_leave_flagged, is_on_duty_flagged, is_core_hours_breach,
has_unresolved_break, has_active_break, has_excess_break_exception, is_regularized, is_pending_approval,
is_locked`. "LATE" and "EARLY_DEPARTURE" are flags, not statuses — consistent with the engine.

Contradiction scan:

| Pair | Possible? | Notes |
|---|---|---|
| PRESENT + ABSENT | No (single column) | |
| LEAVE + worked_minutes > 0 | **Yes, by design** | flagged, blocks period close |
| LEAVE + `ot_minutes_approved > 0` | **Yes, bug** | B-02 |
| HOLIDAY/WEEKLY_OFF calendar + ABSENT | **Yes, bug** | B-01 |
| HALF_DAY + full day worked | Yes if half-day leave or late band/cumulative counter overrides | by design; counter escalation is BD-05 |
| is_late on LEAVE (half) | Yes | B-06 |
| INCOMPLETE paid 0 / LOP 0 | By design; resolved at lock by `incomplete_at_lock_behaviour` | |

---

## 11. Regularization

Flow: submit (visibility, period open, not future, within employment, ±1 day punch times, policy and
allowed-type, backdate limit, monthly limit, duplicate-active guard, blocked-by-lock) → approver resolved
and snapshotted → manager/HR approve (identity-matched, self-approval blocked) → **synthetic punches**
inserted with `source=REGULARIZATION` → `calculate` → `mark_regularized` → audit. All in one
transaction; a locked day rolls the whole approval back (VERIFIED `_apply_correction` docstring + flow).

Observations:
- Regularization bypasses the shift-window rule and geofence by design (`GEOFENCED_SOURCES` = WEB, FACE).
  An approved correction of 09:00 for a 09:30 shift is credited from 09:30 by the clamp (WT) — i.e. it
  does **not** bypass the credit rule. In HEAD it would.
- It can create overtime (synthetic punches are ordinary punches). With `approval_chain=AUTO` the OT is
  auto-approved straight away; otherwise it goes to the normal OT queue (INFERRED, code path clear).
- Regularization after **approved** OT: OT record is frozen; worked minutes can change underneath it
  (B-06).
- Correction on a leave day: punches appear, `work_on_leave_flagged` raised — correct.
- Break corrections never self-approve (`AUTO` chain is refused, see `submit`).
- Locked period: blocked at submit and at apply.

---

## 12. Recalculation and historical data

| Trigger | Day recomputed? | Locked? | Approved OT? | Evidence |
|---|---|---|---|---|
| New punch | Immediately (best-effort, swallowed errors) + nightly sweep | refused | frozen | `_try_immediate_calculate` |
| Regularization apply | Immediately, same txn | refused | frozen | |
| Leave approve / cancel | Immediately | refused | frozen | `:7249/:7357` |
| Break event / override | Immediately | refused | frozen | `break_service.py:740` |
| Manual recompute / range | On request | skipped | frozen | `tasks.py` |
| **Shift version publish / assignment / roster / holiday / policy change** | **No** — only if the date falls in the trailing 3 days of the nightly sweep, or HR runs a range recalc | n/a | n/a | grep (B-10) |
| Manager change | Not a trigger; PENDING OT keeps its original approver | | | `:4515` |

Idempotency: full replace per date (VERIFIED). Same inputs → same result **except** where the inputs
include sibling days: weekly/monthly OT caps (B-07) and `lates_to_half_day_count` /
`excess_break_days_to_half_day_count` (counts only *prior* days in the month). Regularizing an early-month
late day does not re-evaluate later days that were escalated to HALF_DAY by it unless they are in the
sweep window. Documented trade-off (WD-29/32), but it silently changes pay for a month's later days.
`calculation_version` increments each recompute and `computation_snapshot` pins punch ids, policy ids and
sibling-day inputs (PAY-008), so differences are *explainable*, though no screen shows the diff.

Sweep behaviour: per employee-date transaction, errors swallowed and counted. A persistent `failed`
count is only logged (`attendance_scheduled_calculate_incomplete`), not surfaced to HR (NOT VERIFIED
whether anything alerts on it).

---

## 13. User journeys

A. Normal day — arrives 09:00 for 09:30 shift with a 60 min allowance: punch accepted, work is credited
from 09:30. Employee sees `09:00 – 18:30 · 8h` (raw times, credited hours) with no explanation (UX-01).
Rejected before the allowance: `OUTSIDE_SHIFT_WINDOW` 422 with earliest time — good, mobile has a typed
handler (`outside_shift_window.dart`).

B. Late — late minutes beyond grace; band classification; clear. Late is *netted* by staying late (E):
employee late 60 who stays 60 shows late but no OT and PRESENT — fair, but an HR "late count" will show
lateness the pay doesn't reflect. (BD-05)

C. Too early — outside allowance rejected; inside allowance accepted and uncredited (WT).

D. Forgot punch-out — day `INCOMPLETE`, paid 0/0 until regularized or resolved at lock by
`incomplete_at_lock_behaviour` (default TREAT_ABSENT → LOP). The employee sees "no punch-out recorded"
(mobile detail screen). Recoverable via regularization within `max_backdated_days`.

E. Overtime — detected → PENDING → manager approves whole minutes → day row updated via
`mark_ot_approved`. Employee cannot see that OT is pending or why 30 early minutes weren't OT (UX-03).

F. Leave — LEAVE status; punching anyway raises HR-blocking flag the employee never sees.

G. Half-day leave + attendance — HALF_DAY, but flagged late (B-06).

H. Weekly-off work — see B-01/BD-01. This is the weakest journey.

I. Manager approving — approver identity must equal snapshotted reporting manager; if manager changed
since, the *old* manager is still the only valid approver (HR route only if no manager resolved).
Risk: approver leaves/rotates → request stuck until HR reroutes (is there a reassign? NOT VERIFIED).

J. HR correcting — HR can recompute, run range, keep-leave-over-punches, reopen period (with
`ATTENDANCE.UNLOCK`). Audit rows exist for each.

---

## 14. Security review

VERIFIED at service level:
- Every entry point I read calls `_ensure_employee_visible` (punch, calculate, recompute, leave
  projection) or checks scope (`queue_range_calculation` narrows to the visible set; foreign ids return
  the same `NotFoundError`).
- Idempotency key is per company; cross-employee reuse is refused (`DuplicatePunchIdempotencyKeyError`).
- OT/regularization: self-approval blocked, MANAGER stage requires identity match with snapshotted
  approver, HR stage requires COMPANY scope.
- Period lock is server-side and double-guarded.
- Early-punch window is server-side (not UI-only).

NOT VERIFIED: router-level permission codes for each route; RLS policies; admin override paths;
`ATTENDANCE.PUNCH_ON_BEHALF` abuse limits beyond "not in the future and within employment" (on-behalf can
backdate arbitrarily far until a period is closed — INFERRED, `record_punch_outcome:2881-2889`).
Prior audit: `docs/audits/attendance-only-production-readiness/05_DATABASE_AND_SECURITY_AUDIT.md`.

No confirmed IDOR / tenant-isolation / approval-spoofing issue found.

---

## 15. Timezone review

Authority: shift-version tz > branch tz > company tz for schedule math (`resolve_timezone`, WD-06).
Immediate calculate and period-lock gates use the **company** tz date. `enforce_shift_window` resolves
branch/shift/company dates and fails open when they disagree. Mobile displays use `day.timezone`
(`formatClockTime(…, tz)`), which matches the calculation tz.

Mismatch risks (INFERRED): (1) company-date trigger vs shift-start attribution for overnight shifts until
the sweep runs (UX-02); (2) a branch tz different from the company tz makes the immediate trigger compute
the wrong date's day first; (3) DST: `_local_to_utc` uses `datetime.combine(..., tzinfo=ZoneInfo)` which is
correct for non-existent/ambiguous times only by `fold=0` default — NOT VERIFIED beyond that, no DST test
run. Existing timezone audit set (`ATTENDANCE_TIMEZONE_*`) covers most of this.

---

## 16. Code quality findings

- `service.py` is 7,426 lines and `calculation.py` 2,466; `_evaluate_fixed_or_flex` and `_evaluate_split`
  duplicate OT detection, night/OT classification and approval fields (~50 duplicated lines). SPLIT has
  no late/early-out, no clamp, and no counters — the two paths already diverged (B-05).
- Rounding: `apply_rounding` exists and is documented as used for late/early/worked math, but it is
  **never called** (grep: only definition). `punch_rounding` policy setting therefore has no effect
  (B-11, VERIFIED by grep).
- `pair_punches` pairs any consecutive IN/OUT regardless of how long — a forgotten OUT followed by the
  next morning's IN inside the same window forms a ~24 h pair only if both loaded in one window; windows
  limit this to ±2 h/+12 h for FLEX (INFERRED).
- Idempotent recompute appends `DETECTED` action + audit row on each recompute of a pending OT → audit
  noise (INFERRED from `_sync_overtime_record`).
- `_try_immediate_calculate` swallows every exception (by design) — correctness depends on the nightly
  sweep, whose failures are logged only.
- N+1 / index questions NOT VERIFIED (no query plans run).
- `scheduled_minutes` for FIXED is `end − start` gross while `worked_minutes` is net; the day row shows
  `scheduled 540 / worked 480` for a perfectly normal day — confusing to every consumer of the API.
- Naming: `ot_minutes_detected` on the day row is the engine's value, `minutes_detected` on the record may
  be older when frozen.

---

## 17. Bugs found

Severity: 🔴 critical · 🟠 high · 🟡 medium · 🔵 low. "Location" = HEAD / WT / BOTH.

### B-01 🟠 Off-day work is judged by working-day hour bands → ABSENT + LOP on a paid day off — BOTH (INFERRED for HEAD; function unchanged in structure)
- **Business impact:** an employee who comes in for 3–4 h on a weekly off/holiday loses the paid day off (paid 0.00, LOP 1.00).
- **Affected:** monthly-paid staff who are called in on off days.
- **Code path:** `evaluate_day` → `_evaluate_fixed_or_flex` → `_resolve_primary_status:2435` (`hour_band_status` ABSENT/HALF_DAY wins when `worked_minutes > 0`; `not_expected` only matters at 0 minutes) → `_paid_lop_fraction`.
- **Reproduce:** probe G/T: WEEKLY_OFF or HOLIDAY, punch 09:30–12:30 → `ABSENT`, `lop=1.00`.
- **Expected:** a paid off day stays paid; extra effort is OT/comp-off or a policy-chosen outcome.
- **Root cause:** no off-day branch in status resolution; bands and early-out apply on a day with no expectation.
- **Fix:** if `not_expected`, status = `PRESENT`/`NOT_EXPECTED` per policy, skip late/early/bands, pay off-day fraction + OT rules.
- **Regression risk:** medium — touches payroll fractions; needs business sign-off (BD-01).

### B-02 🟠 Approved OT survives a later full-day leave — BOTH
- **Impact:** employee paid leave **and** approved overtime for the same day (payroll).
- **Code:** `_resolve_ot_decision:4485` returns the frozen decision before looking at `result`; `_calculate:4578-4586` copies `minutes_approved`/`comp_off_minutes` into the day row after the leave overlay zeroed them.
- **Reproduce:** OT approved for day D → leave approved/projected for D → `calculate` → status LEAVE, `ot_minutes_approved` = old value, `ot_pending=False`. (INFERRED by code; leave overlay itself zeroing verified by probe M.)
- **Expected:** reopen/cancel OT for a leave day, or block leave projection when OT is approved.
- **Fix:** in `_resolve_ot_decision`, when `result` is a leave-day (`ot_minutes_detected==0` and leave covers 1.0) and record is non-terminal-rejected, raise a review flag; or block `sync` if an approved OT exists.
- **Regression risk:** medium.

### B-03 🟠 `requires_pre_approval` is never enforced — BOTH
- **Impact:** HR believes OT needs prior authorization; the system creates/auto-approves OT from presence alone. Policy UI/API lies.
- **Code:** only usage is the create call `service.py:1059`; `detect_overtime`/`_resolve_ot_decision` ignore it.
- **Expected:** OT exists only after an authorization, or the field is removed/disabled in UI.
- **Fix:** decide product rule (BD-02), then either implement an OT-request object or hide the field.
- **Regression risk:** high if implemented (new workflow, migration, web + mobile).

### B-04 🟠 Flexible-shift lateness measured from window start — BOTH
- **Impact:** a flex employee arriving at 09:30 in a 09:00–10:00 window gets `late=20`, may be pushed into late bands / cumulative half-day counters.
- **Code:** `resolve_schedule_window:516` sets `scheduled_start = window_start`; `_evaluate_fixed_or_flex:2026` uses it. The docstring (`:486-488`) says lateness is relative to `window_end`.
- **Reproduce:** probe Q.
- **Fix:** for FLEXIBLE, late = `first_in − window_end − grace`; required-minutes check already covers short days.
- **Regression risk:** medium (changes status for existing flex employees; engine-version bump).

### B-05 🟠 Early-punch credit clamp excludes SPLIT; HEAD has no clamp at all
- **Impact:** early arrival inside the allowance becomes overtime on SPLIT shifts (and on every shift type in HEAD).
- **Code:** `evaluate_presence_and_breaks:1253` only `shift_type == "FIXED"`; `_evaluate_split` has a scheduled start (first block) available.
- **Reproduce:** probe N: SPLIT 09–13/16–20, punch from 08:30 → `OT=30 pending`.
- **Location:** SPLIT gap = **WT**; whole feature absent in **HEAD** (`clamp_pairs_to_start` HEAD count 0).
- **Fix:** apply the clamp to SPLIT using `scheduled_start`; add test.
- **Regression risk:** low–medium. Must not ship the commit without it.

### B-06 🟡 Half-day leave: late/early-out computed against the full-day shift
- **Impact:** AM leave + arrival at 13:30 → `is_late=True`, 230 min; feeds `lates_to_half_day_count`, late bands, reports.
- **Code:** `_apply_leave_overlay` half-day branch leaves `late_*`, `early_*`, OT untouched; full-day branch zeroes them.
- **Probe:** K, L.
- **Fix:** shift the expected start/end by the leave half (FIRST_HALF → start at half boundary) or zero late/early for the leaved half.
- **Also:** OT on a half-leave day is compared with the whole-shift net schedule, so OT is undercounted (L: 390 worked, no OT) — consistent but surprising.

### B-07 🟡 Weekly/monthly OT caps are order-dependent
- **Code:** `_build_calculation_input:4309-4336` sums every other day in the week/month, past **and future**.
- **Impact:** recomputing an earlier day lowers its OT; historical pending OT silently shrinks.
- **Fix:** sum only earlier days (`< target_date`), or allocate caps chronologically in the sweep.

### B-08 🟡 FIRST_IN_LAST_OUT + V1 breaks: punched-out gaps not deducted (INFERRED)
- **Code:** `presence_span` FIRST_IN_LAST_OUT gross includes gaps; `compute_breaks` only deducts inside presence; legacy gap matching only for mode-less rules.
- **Impact:** over-credit when employee punches out for a break in that mode. Verify whether the mode is reachable with V1 shifts (NOT VERIFIED).

### B-09 🟡 Overlapping punch-load windows for rotating rosters (INFERRED)
- ±2 h padding can make adjacent dates load the same punch (night → early day shift). Mis-pairing risk.

### B-10 🟡 No recompute on holiday / shift / roster / assignment / policy change
- Days older than the sweep's 3-day window stay on stale facts until HR range-recalculates. Payroll could close on stale `PRESENT`/`ABSENT` if nobody does. Mitigation: `AttendancePeriodService.validate` before finalize (NOT VERIFIED whether it re-derives).

### B-11 🔵 `punch_rounding` / `rounding_minutes` policy has no effect
- `apply_rounding` is never called (grep). HR can configure rounding that silently does nothing.

### B-12 🔵 Audit noise: pending OT writes a new `DETECTED` action + audit entry on every recompute.

---

## 18. Business-rule conflicts

| Conflict | Current behaviour |
|---|---|
| Early-punch policy vs overtime | HEAD: early time → OT. WT: FIXED clamped; SPLIT not; FLEX n/a. |
| Leave vs attendance | Leave wins status; approved OT can survive (B-02); half-day leave judged against full shift (B-06). |
| Regularization vs approved OT | OT frozen at old minutes while worked time changes. |
| Shift change vs historical attendance | Past unlocked days not recomputed (B-10). |
| Holiday work vs overtime | Only the minutes beyond a *full* shift are OT; short work loses the day off (B-01). |
| Breaks vs overtime | Breaks reduce worked time everywhere; excess punched-out lunch not flagged. |
| Late vs OT | Late 60 + stay 60 → OT 0 (netting). Lateness still counts toward cumulative half-day. |
| Policy `requires_post_approval` vs `approval_chain=AUTO` | AUTO overrides the "requires approval" flag silently. |
| Pre-approval field vs engine | Field exists, engine ignores it. |
| Calendar day type vs status | Status ABSENT on WEEKLY_OFF possible. |

---

## 19. User-experience problems

- **UX-01** Employee sees raw first-in/last-out with credited hours; nothing explains "09:00 punch, credited from 09:30". `workedMinutes` vs `grossElapsedMinutes` are both in the API but UI lists only first-in/out and worked (`attendance_history.dart:20-23`, `attendance_day_detail_screen.dart:198-244`).
- **UX-02** Overnight worker: today's status may flicker until the nightly sweep (company-date trigger).
- **UX-03** OT: no employee-visible "pending / approved / why not OT" message; early time not counted gives no reason.
- **UX-04** `scheduled_minutes` is gross (540) next to net worked (480) → every normal day looks 60 min short.
- **UX-05** Work-on-leave flag blocks period close but is HR-only; employee never learns why.
- **UX-06** Typed `OUTSIDE_SHIFT_WINDOW` is good, but post-shift punches are silently accepted (`AFTER_SHIFT` is only logged) — a punch after shift end creates OT with no feedback.

---

## 20. Current vs recommended behaviour

| Topic | Current | Recommended |
|---|---|---|
| Off-day work | working-day bands; may be ABSENT/LOP | off day stays paid; worked time → comp-off/OT per policy, never LOP |
| OT authorization | detected from presence | policy chooses: auto / post-approval / pre-approval request; remove unenforced field |
| Approved OT + leave | both | leave day cannot carry approved OT; surface conflict for HR |
| Flex lateness | vs window start | vs window end, required hours decide short days |
| Early credit | FIXED only (WT) | all shift types with a defined start |
| Half-day leave | whole-shift late | expected start/end shifted by leave half |
| Caps | order-dependent | chronological, earlier days only |
| Staleness | 3-day sweep | event-driven recompute on holiday/shift/roster/policy publish or an "affected dates" job |
| Explainability | raw times + worked | show raw, credited-from, break, OT status and reason |

Common industry practice (labelled as such, not codebase behaviour): weekly-off work usually earns comp-off
or a multiple; OT normally needs prior approval or an explicit request; flexible shifts measure lateness
against the end of the arrival window; leave plus punches is surfaced to HR rather than resolved silently.

---

## 21. Prioritised fix plan

| P | Item | Migration | Backend | Web | Mobile | Tests | Risk |
|---|---|---|---|---|---|---|---|
| **P0** | B-01 off-day status/pay | no | engine | – | – | unit matrix (WO/HOL × 0/2/4/8/10 h) | medium |
| **P0** | B-05 SPLIT clamp (+ don't ship WT without it) | no | engine | – | – | unit split early/late | low |
| **P0** | B-02 OT vs leave | no | OT decision + leave sync guard | HR flag | – | integration | medium |
| **P0** | BD-01 decide weekly-off/holiday work pay | maybe | engine/OT | policy copy | – | – | high |
| **P1** | B-03 pre-approval (decide first) | likely | OT policy + request | policy form, queue | OT request screen | integration | high |
| **P1** | B-04 flex lateness | no | engine, engine v4 | – | – | unit | medium |
| **P1** | B-10 event-driven recompute | maybe (job table) | publish hooks | – | – | integration | medium |
| **P1** | B-06 half-day leave late/early | no | engine | – | – | unit | low |
| **P2** | B-07 chronological caps; B-11 rounding; B-12 audit noise | no | repo/engine | – | – | unit | low |
| **P2** | UX-01/03/04 explainability | no | schema field | day detail | day detail | widget | low |
| **P2** | B-08/B-09 verify mode & roster windows | no | engine | – | – | unit | low |
| **P3** | Pre-approved OT workflow, comp-off UI, alerts when sweep fails | yes | | | | | |

### Business decisions required (blocking some P0/P1 items)
BD-01 off-day work pay · BD-02 OT authorization model · BD-03 is a punch after shift end + grace-out an OT
trigger without approval? · BD-04 flag/deduct excess punched lunch for V1 breaks · BD-05 lateness netted
by staying late, and does half-day-leave lateness count · BD-06 whether HR can partially approve OT minutes
· BD-07 who approves when the snapshotted manager has since left.

---

## 22. Final question — top 10 month-end risks (highest business risk first)

1. **Weekly-off/holiday call-in loses the paid day** (short stint → ABSENT + LOP) — direct pay loss, B-01.
2. **Full day worked on an off day earns no OT/comp-off** — unpaid labour or manual HR fix, BD-01.
3. **Approved OT retained on a leave day** — double payment, B-02.
4. **Early arrivals become paid overtime in HEAD / on SPLIT shifts** — systematic OT inflation, B-05.
5. **Unenforced "pre-approval"** — OT paid without authorization the policy claims to require, B-03.
6. **Stale unlocked days after shift/holiday/policy changes** — payroll closes on old facts, B-10.
7. **Flex employees marked late for normal arrivals**, escalating to half-days via counters, B-04.
8. **Sibling-day counters/caps make results depend on recompute order** — a regularization quietly changes other days, B-07 + BD-05.
9. **Half-day leave days flagged late and fed into late counters**, B-06.
10. **Employees cannot understand their day** (raw times vs credited hours, hidden flags) → disputes and reflexive regularizations, UX-01/03/04.

---

## Appendix — probe output (engine only, WT)

```
A  FIXED 09:00-18:30 (early 30m)       PRESENT worked=480 sched=540 late=0 OT=0
B  FIXED 09:30-19:30                   PRESENT worked=540 OT=60 pending
C  FIXED 09:00-19:30                   PRESENT worked=540 OT=60 pending
D  FIXED 09:00-17:15                   HALF_DAY worked=405 early_out=70 paid=0.50 lop=0.50
E  FIXED 10:30-19:30                   PRESENT worked=480 late=50 OT=0
F  2h punched lunch                    PRESENT worked=420 OT=0 (no excess-break flag)
G  WEEKLY_OFF 09:30-13:30              ABSENT  worked=210 paid=0.00 lop=1.00
H  WEEKLY_OFF 09:30-18:30              PRESENT worked=480 OT=0
I  HOLIDAY 09:30-19:00                 PRESENT worked=510 OT=30 pending
J  forgot out                          INCOMPLETE paid=0 lop=0
K  half-day leave AM, in 13:30         HALF_DAY late=230 paid=1.00
M  full-day leave + punches            LEAVE worked=540 work_on_leave_flagged paid=1.00
N  SPLIT early 08:30                   PRESENT worked=510 OT=30 pending
P/Q FLEX 09-10: 07-15 / 09:30-18:30    PRESENT late=0 / late=20, OT=60
R1/R2/R3 overnight                     PRESENT 480 / OT 60 NIGHT / 420
T  HOLIDAY 09:30-12:30                 ABSENT  worked=180 lop=1.00
```
