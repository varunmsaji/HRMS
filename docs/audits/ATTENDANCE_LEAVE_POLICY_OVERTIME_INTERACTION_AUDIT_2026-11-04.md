# Attendance × Leave × Policy × Overtime — Interaction Audit and Test Plan

| Field | Value |
|---|---|
| Date | 2026-11-04 |
| Branch / commit audited | `claude/tender-gauss-5xrf9z` at `f7272cf` (working tree, no uncommitted changes) |
| Mode | Read-only. No code, test, migration or configuration was changed. |
| Scope | How approved leave, attendance/overtime/regularization policy settings, overtime detection and approval, period lock and payroll hand-off affect one employee-date's attendance outcome. |
| Out of scope | Face/liveness, geofence, punch intake UX, web/mobile screens, RBAC/tenancy (already covered by the B6/B10/B11 QA passes), shift-swap/weekly-schedule UI. Break management is covered only where it changes status or overtime. |
| Supersedes | `docs/modules/attendance/ATTENDANCE_*` (2026-08-21) for the leave/OT rows — those were written before the Leave module, ON_DUTY, core hours, cumulative counters, the night-OT window and BUS-001…017 existed and are now out of date on exactly the topics this audit covers. |

Every claim below was checked against the current source, not against prior documentation. File references are `path:line` on the audited commit.

---

## 1. Executive summary

The engine is well structured (pure `calculation.py`, DB orchestration in `service.py`) and the
2026-09-23 payroll decisions (BUS-001…017) are implemented as documented. Most of the August
"stored but not used" gaps are now closed: night-OT window, core hours, cumulative lates/excess
breaks, early-departure approval, ON_DUTY, leave zeroing OT, half-day weekly offs, daily-wage pay
basis, per-legal-entity periods.

The audit found **3 defects that change money or block period close**, **4 behaviours that are
wrong in combination even though each piece is correct alone**, and **a set of product decisions
that are still open and already bite in realistic Indian-HR scenarios**. Nothing found is a
tenant-isolation or security issue.

| # | Finding | Severity | Money / close impact |
|---|---|---|---|
| F1 | FLEXIBLE shift lateness is measured from `window_start`, not `window_end` — anyone arriving inside the allowed window is "late" | **High** | Wrong LATE/HALF_DAY/ABSENT, feeds the lates-to-half-day counter |
| F2 | An overtime record approved *before* a backdated full-day leave is approved stays frozen; the LEAVE day still carries `ot_minutes_approved` and is paid OT at the NORMAL rate | **High** | Violates BUS-011 (no OT on a leave day); pays OT twice-rated wrong |
| F3 | ON_DUTY approved on an unpaid off day (daily-wage weekly off, unpaid holiday) produces paid 1.00 + unpaid-off 1.00 = 2.00 → `PAID_LOP_MISMATCH` blocks finalize with no HR remedy except revoking on-duty | **High** (close blocker) | Period cannot close |
| F4 | Half-day leave neutralises every penalty on the worked half (late/early band ABSENT, core-hours ABSENT, unapproved early exit) and converts an INCOMPLETE other half into immediate 0.50 LOP, bypassing `incomplete_at_lock_behaviour` | Medium | Over-pays and under-pays in opposite cases |
| F5 | FIRST_HALF leave marks the employee late for the whole morning (`is_late=True`, `late_minutes≈300`), which counts in `late_count` and in the lates-to-half-day counter for later days | Medium | Wrong penalty on a *later* day |
| F6 | Half-day leave + approved ON_DUTY on the same date → status LEAVE, 0.50 LOP (on-duty is discarded) | Medium | Under-pays |
| F7 | Leave never consults published roster week-off overrides, and calendar changes never re-evaluate approved leave: balance is debited and the day paid as LEAVE on a date the employee was never expected to work | Medium | Balance leak; wrong bucket |
| F8 | Overtime on a holiday / weekly off is only the minutes *beyond the shift length*; a full shift worked on Sunday yields 0 OT and 0 comp-off | Medium (open decision, COMPOFF D1/P1) | Under-pays off-day work; known, still undecided |
| F9 | `GRADE_VIA_ASSIGNMENT` OT eligibility behaves as `ALWAYS` (ND-07 / CL-09, still open; hidden in UI but any existing version keeps it) | Low–Medium | Over-eligibility |
| F10 | Approving a forward-dated `EARLY_DEPARTURE_APPROVAL` runs `calculate()` for a future date and marks that future day `is_regularized` | Low | Pre-created INCOMPLETE rows; self-heals |
| F11 | ON_DUTY overlay neither zeroes OT nor interacts with pay-basis fractions; ON_DUTY + punches + OT is paid both | Low (decide) | Possible double credit |

Section 4 has the detail and evidence; Section 6 has **84 test cases** (unit + integration) that
pin the correct behaviour, including the ones that fail today.

---

## 2. What actually runs today (verified pipeline)

This is the order of evaluation for one employee-date. Everything before step 9 is DB
resolution in `service.py:_build_calculation_input` (4213–4629); steps 9–19 are the pure engine
(`calculation.py:evaluate_day`, 1510–1647); 20+ is persistence and the OT decision.

| Step | What | Where | Notes that matter for interactions |
|---|---|---|---|
| 1 | Employment gate → `ACTIVE` / `NOT_JOINED` / `EXITED` | service 4236–4245; calc 1556–1558 | Gate statuses skip **every** overlay (leave, on-duty) |
| 2 | Assignment → branch tz, default shift, manager | service 4247–4256 | |
| 3 | Published roster row → shift override, week-off / holiday-working flags | service 4262–4276 | Draft rosters invisible |
| 4 | Shift version as-of date → `ShiftInputs`, schedule window | `_resolve_shift_schedule` 2747–2854; `resolve_schedule_window` 469–554 | **FLEXIBLE: `scheduled_start/end` = `window_start/window_end`** (516–526) |
| 5 | Employee break overrides layered on shift breaks | `break_service.apply_break_overrides` | |
| 6 | Calendar → day type, holiday type/paid flag, weekly-off fraction | service 4306–4325 | |
| 7 | Attendance policy version + hour/late/early bands + **prior late / excess-break day counts** for the calendar month | service 4327–4442 | Counters read `attendance_day.is_late` (repository 1368) |
| 8 | OT policy version + rate rows + **remaining weekly/monthly cap** from sibling `overtime_record`s (all statuses except REJECTED) | service 4444–4519; repository 2009–2037 | |
| 9 | Punches in the load window; break events; `day_open` | service 4530–4553 | |
| 10 | Active leave projections, approved `EARLY_DEPARTURE_APPROVAL`, approved `ON_DUTY` | service 4558–4587 | Re-resolved every recompute |
| 11 | CONFIG_ERROR gates (tz, calendar, policy) | calc 1566–1577 | Leave overlay skipped on CONFIG_ERROR |
| 12 | Roster week-off with no punches → NOT_EXPECTED (+overlays) | calc 1585–1589 | |
| 13 | Missing shift → `missing_shift_behaviour` or no-schedule evaluation (+overlays) | calc 1592–1602 | No late/early/OT ever on the no-schedule path |
| 14 | Half-day weekly off is evaluated as WORKING | calc 1606 | |
| 15 | Not-expected + shift doesn't operate + no punches → NOT_EXPECTED | calc 1612–1634 | |
| 16 | Pairing → presence → breaks (legacy gap matching + V1 events/auto-deduct) → `worked_minutes` | calc 1636–1645, 1243–1307 | FIXED only: presence before `scheduled_start` not credited (980–996) |
| 17 | Late/early vs grace → bands; unapproved early exit forced to harshest band; FLEX core hours; cumulative counters; `_resolve_primary_status`; unresolved break → INCOMPLETE | calc 2025–2110 | **Late uses `scheduled_start`** (2026) |
| 18 | OT: `worked − net schedule`, eligibility, min, rounding, daily/weekly/monthly caps, day class (holiday > weekly-off > night > normal), `requires_post_approval`, comp-off fact | calc 2119–2179, 1455–1502 | Net schedule = shift minus V1 unpaid breaks; FLEX uses `required_minutes` |
| 19 | Overlays, in this order: off-day pay (BUS-001) → half weekly off (PAY-012) → **ON_DUTY** → **LEAVE** | calc 1689–1695 | Leave wins over on-duty; full-day leave zeroes OT/late/early (1788–1810); half-day leave is a flat 0.50 (1812–1829) |
| 20 | OT decision: a non-PENDING `overtime_record` is **frozen** and its minutes override the day row regardless of what the engine just produced | service 3722–3749, 4648–4656 | **Also when the engine zeroed OT because of leave** |
| 21 | Day row written (insert or full replace), `overtime_record` upserted/deleted-if-pending, breaks replaced | service 3751–3859 | |
| 22 | Period validate: EMPLOYEES_WITHOUT_ATTENDANCE, CONFIG_ERROR, WORK_ON_LEAVE_UNRESOLVED, PAID_LOP_MISMATCH, INCOMPLETE (KEEP_INCOMPLETE only), PENDING_REGULARIZATION, PENDING_OVERTIME_APPROVAL, UNPUBLISHED_ROSTER | service 6467–6692 | |
| 23 | Finalize: INCOMPLETE → TREAT_ABSENT/TREAT_PRESENT (weekly-off-fraction aware), summary buckets, reconciliation assert, lock | service 6978–7176 | |
| 24 | Payroll reads only CLOSED periods; OT = `ot_minutes_approved` on locked days with `comp_off_minutes_earned = 0`, bucketed by `ot_day_class` (NULL → NORMAL) | repository 1438–1477; payroll engine 355–380 | **No `attendance_status` filter** |

### 2.1 How leave reaches attendance

`leave/service.py:_apply_approval` (3212–3328) → for every `leave_application_day` →
`LeaveProjectionService.sync` (7281–7420) → `calculate()`. Projection values (fraction, half,
paid) are derived from Leave's own day rows (`_resolve_backing_leave_day`, 7422–7462), never
from the request. Cancel of an approved application reverses the ledger and cancels each
projection (3465–3542), each cancel recomputing the day. Both directions refuse a date inside a
CLOSED period of the employee's legal entity (PD-3). Leave day fractions come from the work
calendar only (`_compute_day_breakdown`, 2344–2416): 1.00 on a working day, 0.50 on a half-day
weekly off, 0.00 on off days unless sandwiched.

### 2.2 How overtime becomes money

Engine detects → `_resolve_ot_decision` creates PENDING / AUTO_APPROVED → manager/HR
approve/reject → `attendance_day.ot_minutes_approved` → period finalize locks the day →
`list_payable_overtime_for_period` → payroll run (rate × multiplier of the policy version that
applied that day). Comp-off minutes go to Leave's ledger via `LeaveCompOffService.credit_company`
instead of money.

---

## 3. Interaction matrix (current behaviour, verified)

Legend: ✅ correct and tested · ☑ correct by reading, **no test** · ⚠ defect or unintended · ❓ open product decision

### 3.1 Leave × attendance status

| Situation | Today | Verdict |
|---|---|---|
| Full-day paid leave, no punches | LEAVE, paid 1.00 | ✅ |
| Full-day unpaid / LOP leave, no punches | LEAVE, LOP 1.00 | ✅ |
| Full-day leave + punches (any `work_on_leave_behaviour`) | LEAVE, paid per leave, OT/late/early zeroed, `work_on_leave_flagged`, finalize blocked until HR keeps leave or cancels it | ✅ |
| Full-day leave on holiday / weekly off (sandwich) | LEAVE wins over NOT_EXPECTED; `calendar_day_type` unchanged | ✅ |
| Full-day leave on **roster** week-off day | LEAVE (balance debited for an off day — see F7) | ⚠ |
| Half-day leave, no punches | LEAVE, paid 0.50 / LOP 0.50 | ✅ |
| Half-day leave + full-day punches | HALF_DAY, paid 1.00 | ✅ |
| Half-day leave + 10 minutes of punches | HALF_DAY, paid 1.00 (`has_work` is `worked_minutes > 0`) | ⚠ F4 |
| Half-day leave + late band ABSENT / core-hours ABSENT / unapproved early exit | HALF_DAY, paid 1.00 (penalty discarded) | ⚠ F4 |
| Half-day leave + orphan punch (INCOMPLETE other half) | LEAVE, LOP 0.50 immediately; lock-time TREAT_PRESENT never consulted | ⚠ F4 |
| FIRST_HALF leave, employee arrives 14:00 | `is_late=True`, `late_minutes` ≈ 300, counted in `late_count` and lates-to-half-day | ⚠ F5 |
| Half-day leave on half-day weekly off | Fully paid, no LOP | ✅ |
| Leave on NOT_JOINED/EXITED/CONFIG_ERROR day | Overlay skipped; leave stays debited | ☑ fail-closed (acceptable) |
| Leave approved after period CLOSED | Refused, whole approval rolls back | ✅ |
| Leave cancelled after period CLOSED | Refused | ✅ |
| Leave approved for future dates | Creates `AttendanceDay` rows now; recomputed later by punches/sweep | ☑ |
| Termination before an approved future leave | Termination refused while leave exists (`_assert_no_leave_after`) | ✅ (employee module) |
| Calendar exception added after approval turns a leave day into a holiday | Leave day/projection untouched, balance stays debited, day shows LEAVE | ⚠ F7 |

### 3.2 Leave × overtime

| Situation | Today | Verdict |
|---|---|---|
| Full-day leave + OT punches, no prior OT record | Engine zeroes OT; stale PENDING record deleted | ✅ (`test_full_day_leave_with_overtime_punches_pays_leave_only_and_no_ot`) |
| Full-day leave + OT punches, OT record **PENDING** before leave sync | Decision `None` → `delete_if_pending` | ☑ no test |
| Full-day leave approved **after** OT record APPROVED / AUTO_APPROVED | Frozen minutes copied back onto the LEAVE day; `ot_day_class` NULL; payroll pays at NORMAL | ⚠ **F2** |
| Half-day leave + OT punches | OT detected against the full net schedule (no adjustment for the leave half) | ❓ decide, then test |
| Comp-off credit from an OT record on a day later turned into leave | Credit stays (ledger never reversed) | ⚠ part of F2 |

### 3.3 Policy settings × attendance (which ones are live)

| Attendance-policy field | Live? | Evidence |
|---|---|---|
| grace_in/out, late/early/hour bands, multi_punch_mode, duplicate window, missing_punch (INCOMPLETE/ABSENT), missing_shift, split missed-block, incomplete_at_lock, core_hours_breach (FLEX), lates_to_half_day_count, excess_break_days_to_half_day_count, early_departure_requires_approval, on_duty_requires_punch, excess_break_behaviour (as default per-break outcome) | Yes | calc 2025–2110, 1070–1072, service 6978–7063 |
| punch_rounding / rounding_minutes | No (hidden PD-1) | `apply_rounding` never called on punches |
| missing_punch_behaviour = AUTO_CLOSE | No distinct behaviour (falls to bands, `auto_closed` always False) | calc 2430–2431 |
| missing_punch_behaviour = REQUIRE_REGULARIZATION | Same as INCOMPLETE | calc 2432–2433 |
| half_day_split / boundary | No | declared only |
| work_on_leave_behaviour | Inert since BUS-012 (hidden) | calc 1755–1760 |
| early_out_uses_core_end | No | never read |
| late_count_window / excess_break_count_window | MONTH only (hard-coded month boundary) | service 4408–4418 |

| Overtime-policy field | Live? |
|---|---|
| eligibility NEVER / SHIFT_FLAG / ALWAYS | Yes |
| eligibility GRADE_VIA_ASSIGNMENT | **Behaves as ALWAYS** (F9) |
| min_ot_minutes, rounding, daily/weekly/monthly caps, requires_post_approval, approval_chain, comp_off_instead_of_pay, comp_off_expiry_days, night_ot_mode + window, rate rows | Yes |
| multiplier_decimal | Fact only in attendance; **applied as money by payroll** (engine 355–380) |

| Regularization-policy field | Live? |
|---|---|
| allow_*_request, max_backdated_days, max_requests_per_month, reason/attachment required, allowed types, approval_chain | Yes |
| blocked_when_locked | Only the day-level `is_locked` check (service 5127–5132); the period check is unconditional |
| auto_approve_within_minutes | No |

### 3.4 Regularization × leave × OT

| Situation | Today | Verdict |
|---|---|---|
| MISSING_PUNCH approved on a full-day leave day | Punches inserted, day stays LEAVE, `work_on_leave_flagged` → HR must resolve | ✅ (tested) — but nothing warns the approver |
| WRONG_SHIFT approved → roster row PUBLISHED → recompute | ✅ |
| ON_DUTY approved, `on_duty_requires_punch=False` | ON_DUTY, paid 1.00 | ✅ |
| ON_DUTY approved on daily-wage weekly off / unpaid holiday | paid 1.00 + unpaid_off 1.00 → `PAID_LOP_MISMATCH` | ⚠ **F3** |
| ON_DUTY + half-day leave | LEAVE, LOP 0.50 | ⚠ F6 |
| ON_DUTY + punches producing OT | ON_DUTY and OT both kept | ❓ F11 |
| EARLY_DEPARTURE_APPROVAL approved for a future date | `calculate()` runs for the future date | ⚠ F10 (low) |
| Regularization changes punches on a day with a frozen OT record | Record never revised (WD-29 decision 2) | ☑ documented; test pins it |
| BREAK_CORRECTION with AUTO chain | Rerouted to HR | ✅ |

### 3.5 Period lock × everything

All seven mutation surfaces (punch, roster, regularization submit, recompute, OT approve/reject,
leave sync, leave cancel) refuse a CLOSED period of the employee's legal entity — ✅ tested.
`finalize` holds the period-close advisory lock exclusively; leave approval/reversal hold it
shared — ✅. Payroll refuses a non-CLOSED period and re-checks `(status, version)` before
approve/finalise — ✅. Reopen does not recompute (ND-08, documented).

---

## 4. Findings in detail

### F1 — FLEXIBLE lateness measured from the wrong end of the window  (High)

*Where:* `calculation.py:2025–2029` uses `inputs.scheduled_start`; for a FLEXIBLE shift
`resolve_schedule_window` sets `scheduled_start = window_start` (516–526). Its own docstring
(486–488) and architecture §11.8 (`WORKFORCE_ATTENDANCE_ARCHITECTURE.md:1021`, "IN after
`window_end` + grace; IN inside the window is never late") both say lateness starts at
`window_end`.

*Effect:* window 08:00–10:00, grace 15, IN at 09:30 → `late_minutes = 75` → late band may yield
HALF_DAY/ABSENT, `is_late=True`, counted toward `lates_to_half_day_count` and `late_count`.
(Early departure compares the *last* OUT with `window_end`; since the last OUT of a real
working day is always after the window, that side is effectively inert for FLEX and is not a
defect — FX-09 pins it.)

*Tests:* no unit or integration test asserts a FLEXIBLE-shift `late_minutes`/`is_late`
(`test_flexible_overtime.py` only asserts OT and worked minutes). This matches the August audit's
"FLEXIBLE evaluation unverified" warning, which was never closed.

### F2 — Frozen approved OT survives a later full-day leave  (High, payroll)

*Sequence:* day computed with OT → OT APPROVED (record now non-PENDING) → HR approves a
backdated leave covering that date (allowed while the period is open) → projection sync →
`calculate()` → engine returns `LEAVE` with `ot_minutes_* = 0`, `ot_day_class = None`,
`comp_off_minutes_earned = 0` (calc 1788–1810) → `_resolve_ot_decision` sees the non-PENDING
record and returns `frozen` (service 4648–4656) → `_calculate` writes
`ot_minutes_approved = record.minutes_approved`, `comp_off_minutes_earned = record.comp_off_minutes`
onto the LEAVE row (3741–3749). `ot_day_class` is written from the engine result (`None`,
4206). The day is flagged `work_on_leave_flagged`; HR "keeps leave"; the period closes;
`list_payable_overtime_for_period` (repository 1438–1477) has no status filter and maps a NULL
day class to `NORMAL`, so payroll pays the OT at the NORMAL multiplier even if it was holiday
OT.

*Violates:* BUS-011 ("OT on a full-day leave day is not payable"). The engine-level test for
BUS-011 passes because it never creates an approved record first.

*Also:* a comp-off credit already written by `credit_company` for that record is never reversed.

*Fix direction (not applied):* in `_calculate`, when `result.attendance_status == "LEAVE"` and
`result.leave_fraction == "1.00"`, do not copy frozen minutes onto the day (or add
`attendance_status != 'LEAVE'` to the payable query and the summary aggregation), and surface a
`WORK_ON_LEAVE` sub-reason so HR knows an approved OT record exists.

### F3 — ON_DUTY on an unpaid off day cannot be closed  (High, close blocker)

*Where:* `_apply_off_day_pay` (calc 1671–1680) sets `paid 0.00 / lop 0.00 / unpaid_off 1.00` for
a NOT_EXPECTED day that `_off_day_is_paid` says is unpaid (daily-wage weekly off, any holiday
with `is_paid=false`). `_apply_on_duty_overlay` (1832–1865) then sets `paid 1.00 / lop 0.00`
but never touches `unpaid_off_fraction`. The day stores `1.00 + 0.00 + 1.00 = 2.00`;
`_run_validation` raises `PAID_LOP_MISMATCH` (6546–6573) whose message says "recompute them",
which will not help.

*Realistic trigger:* daily-wage field staff sent on duty on a Sunday — exactly the population
BUS-001 was written for.

*Related:* on a *paid* weekly off (monthly staff) ON_DUTY works but moves the day from
`weekly_off_days` to `on_duty_days`; whether an on-duty Sunday should earn an extra day or
comp-off is undecided (see §5).

### F4 — Half-day leave neutralises penalties and bypasses lock-time resolution  (Medium)

*Where:* `_apply_leave_overlay` half-day branch (calc 1812–1829): `has_work = worked_minutes > 0`;
`work_paid = remaining if has_work else 0`; status forced to HALF_DAY/LEAVE regardless of the
punch-derived status.

Consequences:

1. Late band ABSENT, early band ABSENT, core-hours ABSENT, unapproved early exit forced to
   ABSENT, hour-band ABSENT (e.g. 20 minutes worked) → all become `HALF_DAY, paid 1.00`.
2. Missing OUT (INCOMPLETE, `worked_minutes = 0`) → `LEAVE, LOP 0.50` *immediately*. The
   INCOMPLETE semantics ("not paid, not LOP, resolved at lock per `incomplete_at_lock_behaviour`")
   and the PAY-006 reminder flow are bypassed because the stored status is LEAVE.
3. Cumulative counters still see the day (see F5).

ND-09 records the "flat 0.50" simplification, but not these three consequences; the first two
move money.

### F5 — FIRST_HALF leave produces a bogus late  (Medium)

`half` is carried for provenance only (calc 210–219). Lateness is computed against the shift
start (2025–2029) before the overlay, and the half-day branch does not zero `late_minutes` /
`is_late` (unlike the full-day branch, 1799–1803). A FIRST_HALF leave with a 14:00 IN stores
`is_late = True, late_minutes ≈ 300`. `count_flagged_days_in_window` (repository 1368) counts
`is_late` rows, so the next late-beyond-grace day can be forced to HALF_DAY by
`lates_to_half_day_count` (calc 2077–2083), and `late_count` in the frozen summary is inflated.
Symmetrically a SECOND_HALF leave with a 13:00 OUT stores `is_early_out = True`.

### F6 — Half-day leave + ON_DUTY  (Medium)

Overlay order is ON_DUTY then LEAVE (calc 1695). ON_DUTY sets paid 1.00 (no punches). The
half-day leave branch recomputes from `has_work` (False) → `LEAVE, paid 0.50, LOP 0.50`.
Realistic: half-day CL in the morning, client visit (on-duty) in the afternoon.

### F7 — Leave does not see rosters or later calendar changes  (Medium)

* `_compute_day_breakdown` (leave 2344–2416) uses `CalendarResolutionService` only. A published
  `ShiftRoster.is_week_off_override` day (rotating-crew Wednesday off) is WORKING to Leave →
  fraction 1.00, balance debited, projection synced → attendance shows LEAVE (overlay outranks
  NOT_EXPECTED, 1746–1749). Conversely a roster `is_holiday_working_override` day is an off day
  to Leave → 0.00 → "no leave-consuming days" even though the employee is rostered to work.
* `calendar_impact.py:12` is explicit: "Calendar changes never rewrite leave days". Adding a
  SUBSTITUTE_HOLIDAY / SHUTDOWN exception, or a holiday, after approval leaves the debit and the
  LEAVE status in place. The impact preview warns HR, but there is no "release leave on this
  date" action.

### F8 — Off-day overtime is only "beyond the shift"  (Medium, open decision)

`detect_overtime` (1475) always subtracts the net schedule, including on HOLIDAY/WEEKLY_OFF days
where presence was not expected. A full 9-hour Sunday shift gives `worked_on_weekly_off = True`,
`ot_minutes_detected = 0`, no comp-off. `COMPOFF_POLICY_SAFETY_REVIEW.md` §13 D1/§14 P1
already flags this and it is still undecided; the step rule for comp-off (BUS-015) is blocked on
it. Listed here because it is the single most common Indian-HR expectation ("Sunday work =
comp-off or double pay") and today's output is silently zero.

### F9 — GRADE_VIA_ASSIGNMENT  (Low–Medium)

`detect_overtime` (1468–1473) has branches for NEVER and SHIFT_FLAG only. Hidden from new
policy versions (PD-1 step 4) but still honoured on existing ones. ND-07 / CL-09 open.

### F10 — Forward-dated early-departure approval pre-creates the day  (Low)

`submit` allows a future `attendance_date` for `EARLY_DEPARTURE_APPROVAL` (5030–5031);
`_apply_correction` always ends with `calculate()` (5709) and `mark_regularized` (5717);
`_calculate` has no future-date guard. A row for next Friday is created now as INCOMPLETE with
`is_regularized = True`. It is recomputed by the first punch or the trailing sweep, so the
final figures are right; the interim row is visible in listings and dashboards.

### F11 — ON_DUTY and overtime  (Low, decide)

`_apply_on_duty_overlay` leaves `ot_*` untouched. ON_DUTY with punches that exceed the shift
gives a full paid day *and* OT. Probably intended for "on duty at a client site, worked late",
but it is undocumented and untested.

### Documented limitations re-confirmed (no change in status, tests proposed to pin them)

* Frozen terminal OT after a regularization changes punches (WD-29 d.2).
* Weekly/monthly OT caps consume PENDING minutes (WD-29 d.3) — a rejected day frees budget only
  after a recompute of the sibling day.
* Half-day leave is a flat 0.50 (ND-09).
* Reopen does not recompute (ND-08).
* Missing-punch AUTO_CLOSE / REQUIRE_REGULARIZATION have no distinct behaviour (hidden).
* Unresolved break END → INCOMPLETE → default TREAT_ABSENT at close = a full day's LOP for a
  forgotten "end break" unless a BREAK_CORRECTION is approved. Reminders cover it (PAY-006).

---

## 5. Decisions needed from the product owner

These cannot be fixed by engineering alone; each has a recommended default so a one-word answer
is enough.

| ID | Question | Recommended default |
|---|---|---|
| D-1 | Off-day work: is OT on a holiday/weekly off *all* minutes worked, or only beyond the shift? (F8, COMPOFF D1) | All minutes worked on a non-operating off day; "beyond shift" only when the shift operates that day (`operates_on_*` / roster holiday-working) |
| D-2 | Half-day leave: does the worked half keep its own late/early/core-hours penalties? (F4) | Yes — apply the punch-derived status to the worked half: PRESENT→0.50 paid, HALF_DAY/ABSENT→0.50 LOP, INCOMPLETE→stay INCOMPLETE until lock |
| D-3 | Half-day leave: should lateness/early-out be measured from the shift midpoint for FIRST_HALF / SECOND_HALF? (F5, ND-09) | Yes (shift midpoint, or `half_day_boundary_minutes` if that field is revived) |
| D-4 | ON_DUTY on an unpaid off day: paid day, unpaid off day, or comp-off? (F3) | Paid day (`unpaid_off = 0`), no OT |
| D-5 | ON_DUTY + overtime from punches: pay both? (F11) | Pay both only when `on_duty_requires_punch = True`; otherwise ON_DUTY implies no OT |
| D-6 | Should Leave treat a published roster week-off as a non-consuming day, and a roster holiday-working day as consuming? (F7) | Yes to both |
| D-7 | When a calendar change turns an approved leave day into a holiday/shutdown: auto-release, HR action, or leave as is? (F7) | HR action from the impact preview ("release N leave days") |
| D-8 | OT approved before a backdated leave: auto-void the OT record (and reverse comp-off credit) or block the leave approval? (F2) | Void the OT record with an `OVERTIME_VOIDED_BY_LEAVE` action; reverse any comp-off credit |
| D-9 | Remove `GRADE_VIA_ASSIGNMENT` or implement it? (F9) | Reject on publish; migrate existing versions to ALWAYS with an audit row |

---

## 6. Test cases

Conventions: **Unit** = `tests/unit/modules/attendance/test_calculation.py` style (build
`AttendanceCalculationInput`, call `evaluate_day`). **Int** = integration via the real HTTP app
and Postgres, using the existing helpers (`_build_wired_employee_with_leave_behaviour`,
`_seed_leave_application`, `_sync`, `_get_day` in `test_leave_projection.py`;
`_create_overtime_policy`, `_ot_calculate_day`, `_get_overtime_record_for_day` in
`test_overtime_record.py`; `_setup_full`, `_submit`, `_give_balance` in
`leave/test_leave_application.py`). Default fixture unless stated: FIXED shift 09:00–18:00
Asia/Kolkata, grace 15/15, hour bands `[0,240)=ABSENT, [240,420)=HALF_DAY, [420,∞)=PRESENT`,
late bands `[1,60]=LATE, [61,180]=HALF_DAY, [181,∞)=ABSENT`, early bands same shape,
`missing_punch_behaviour=INCOMPLETE`, `incomplete_at_lock_behaviour=TREAT_ABSENT`, OT policy
`eligibility=ALWAYS, min 15, requires_post_approval=True, chain=MANAGER`, monthly pay basis,
calendar Mon–Sat with Sunday off.

**Today** column: `PASS` = expected to pass on the audited commit · `FAIL` = fails today
(the finding) · `DECIDE` = write after the §5 decision; the expected result shown is the
recommended default · `PIN` = passes today and exists to pin a documented limitation.

### 6.1 Leave overlay — full day

| ID | Level | Setup | Steps | Expected | Today |
|---|---|---|---|---|---|
| LV-01 | Int | Paid CL type, balance 5 | Approve 1-day leave on a working day; no punches | `LEAVE`, paid 1.00, LOP 0.00, `leave_fraction 1.00`, projection APPROVED, ledger −1 | PASS (exists) |
| LV-02 | Int | LOP-type leave (`is_paid_default=false`) | Approve 1 day | `LEAVE`, paid 0.00, LOP 1.00, no ledger debit | PASS (exists) |
| LV-03 | Int | Paid leave; employee punches 09:00/18:00 the same day | Approve leave *after* punches exist | `LEAVE`, paid 1.00, `work_on_leave_flagged=true`, `late_minutes=0`, `ot_minutes_detected=0`; validate → `WORK_ON_LEAVE_UNRESOLVED`; `keep-leave` → READY | PASS (exists) |
| LV-04 | Int | As LV-03 | HR cancels the leave instead | Projection CANCELLED, day recomputed to `PRESENT`, flag cleared, ledger +1 `ADJUSTMENT` | PASS (exists partly: cancel path) |
| LV-05 | Int | Paid leave Fri–Mon, sandwich rule **on** | Approve | Sat (half/none) and Sun get fraction 1.00 `is_sandwich_generated`; attendance Sun = `LEAVE` paid 1.00, `calendar_day_type=WEEKLY_OFF`; `leave_days` += 1 for Sun | PASS |
| LV-06 | Int | Same, sandwich **off** | Approve | Sun has no leave day; attendance Sun = `NOT_EXPECTED`, `weekly_off_days` += 1 | PASS |
| LV-07 | Int | Leave on a date in a CLOSED period | Approve | 409 `LEAVE_APPLICATION_PERIOD_CLOSED`; application still SUBMITTED; no projection row | PASS (exists) |
| LV-08 | Int | Approved leave, period then CLOSED | HR cancel | 409; projection still APPROVED; day locked | PASS (exists) |
| LV-09 | Int | Leave approved for dates next month | Approve | `AttendanceDay` rows exist for those dates with `LEAVE`; later punch on one of them recomputes to `LEAVE` + flagged | PASS |
| LV-10 | Int | Employee assignment has **no shift**, `missing_shift_behaviour=INCOMPLETE` | Approve leave | `LEAVE` paid 1.00 (overlay applies to terminal INCOMPLETE) | PASS |
| LV-11 | Int | No attendance policy assigned (CONFIG_ERROR) | Approve leave | Day stays `CONFIG_ERROR`; ledger debited; validate → `CONFIG_ERROR` | PASS (document as fail-closed) |
| LV-12 | Int | Daily-wage employee; leave on Sunday via sandwich | Approve | `LEAVE` paid per type; `unpaid_off_fraction 0.00`; sum = 1.00; finalize READY | PASS |
| LV-13 | Int | Published roster `is_week_off_override` on Wed; paid leave Mon–Fri | Approve | **Expected (D-6):** Wed not leave-consuming, total 4 days. **Today:** 5 days debited, Wed = `LEAVE` | DECIDE / FAIL |
| LV-14 | Int | Approved leave on Tue; then HR adds `SUBSTITUTE_HOLIDAY` exception for Tue | Recompute day | **Expected (D-7):** impact preview lists the application; HR release action exists. **Today:** day `LEAVE`, `calendar_day_type=HOLIDAY`, balance still −1 | DECIDE / FAIL |
| LV-15 | Int | Leave Mon–Wed approved; Tue later becomes SHUTDOWN exception | Recompute | As LV-14 | DECIDE |
| LV-16 | Int | Leave approved; employee terminated with `last_working_day` before the leave | Terminate | 409 `EmploymentChangeConflictsWithLeaveError` (cannot terminate across approved leave) | PASS |
| LV-17 | Int | Two applications, FIRST_HALF CL + SECOND_HALF SL, same date | Approve both | Two projections, fractions sum 1.00; day `LEAVE`, paid 1.00, `leave_fraction 1.00` | PASS (exists) |
| LV-18 | Int | Third half-day on the same date | Approve | 409 `LEAVE_PROJECTION_OVERLAP`; approval rolls back | PASS (exists) |

### 6.2 Leave overlay — half day

| ID | Level | Setup | Steps | Expected | Today |
|---|---|---|---|---|---|
| LH-01 | Unit | Half-day paid leave, no punches | evaluate | `LEAVE`, paid 0.50, LOP 0.50, `leave_fraction 0.50` | PASS |
| LH-02 | Unit | SECOND_HALF paid leave; punches 09:00–13:30 (270 min) | evaluate | `HALF_DAY`, paid 1.00, LOP 0.00, `is_early_out=False`, `early_departure_minutes=0` | **FAIL today** (early 270 → band ABSENT recorded; paid 1.00 is right but flags wrong) |
| LH-03 | Unit | FIRST_HALF paid leave; punches 14:00–18:00 | evaluate | `HALF_DAY`, paid 1.00, `is_late=False`, `late_minutes=0` | **FAIL today** (F5: `is_late=True`, late ≈ 285) |
| LH-04 | Int | As LH-03 on day 1; `lates_to_half_day_count=2`; day 2 IN at 09:20 | Calculate day 2 | Day 2 = `PRESENT` with `is_late` (1 real late so far) | **FAIL today** (day 2 forced HALF_DAY: counter sees 2) |
| LH-05 | Int | As LH-03; finalize month | Read frozen summary | `late_count` excludes the leave day | **FAIL today** |
| LH-06 | Unit | Half-day paid leave; punches 09:00–09:20 (20 min) | evaluate | **Expected (D-2):** `HALF_DAY`, paid 0.50, LOP 0.50. **Today:** paid 1.00 | DECIDE / FAIL |
| LH-07 | Unit | SECOND_HALF leave; IN at 12:30 (late 195 → band ABSENT) ; OUT 13:30 | evaluate | **Expected (D-2/D-3):** worked half judged on its own (late measured from shift start → ABSENT → 0.50 LOP). **Today:** paid 1.00 | DECIDE / FAIL |
| LH-08 | Unit | FLEX shift with core hours 11–16, `core_hours_breach_behaviour=ABSENT`, FIRST_HALF leave, IN 14:00 OUT 18:30 | evaluate | **Expected:** core-hours check limited to the worked half (no breach) or documented. **Today:** breach computed, then overridden to paid 1.00 | DECIDE |
| LH-09 | Unit | `early_departure_requires_approval=True`, no approval, SECOND_HALF leave, OUT 13:30 | evaluate | **Expected:** no early-departure penalty (leave covers it). **Today:** harshest band recorded, then overridden to paid 1.00 | DECIDE / FAIL |
| LH-10 | Unit | Half-day leave; single IN 09:00, no OUT | evaluate | **Expected (D-2):** `INCOMPLETE`, paid 0.50 / LOP 0.00 / remainder resolved at lock. **Today:** `LEAVE`, LOP 0.50 | DECIDE / FAIL |
| LH-11 | Int | As LH-10, policy `incomplete_at_lock_behaviour=TREAT_PRESENT`, finalize | Finalize | **Expected:** paid 1.00. **Today:** paid 0.50 / LOP 0.50 and no `ATTENDANCE_INCOMPLETE_RESOLVED_AT_LOCK` entry for the day | DECIDE / FAIL |
| LH-12 | Int | As LH-10; run the PAY-006 reminder job | Job | **Expected:** employee reminded (missing OUT). **Today:** not reminded (status LEAVE) | DECIDE / FAIL |
| LH-13 | Unit | Half-day weekly off (Sat 0.50) + half-day leave, no punches | evaluate | paid 1.00, LOP 0.00, `weekly_off_fraction 0.50`, `leave_fraction 0.50` | PASS (exists) |
| LH-14 | Unit | Half-day leave + punches 09:00–19:30 (OT 90 beyond 540) | evaluate | **Expected (decide):** OT measured against half the net schedule, or documented "full schedule". Record the decision. **Today:** `ot_minutes_detected=90` | DECIDE |
| LH-15 | Unit | Half-day leave on daily-wage half weekly off | evaluate | paid 0.50 (leave) / LOP 0 / unpaid_off 0.50; sum 1.00 | PASS (`test_daily_wage_half_weekly_off_off_half_unpaid` analogue) |

### 6.3 Leave × overtime

| ID | Level | Setup | Steps | Expected | Today |
|---|---|---|---|---|---|
| LO-01 | Unit | Full-day leave + punches 09:00–20:00 | evaluate | `LEAVE`; `ot_minutes_detected=0`, `ot_pending=False`, `ot_day_class=None`, `comp_off_minutes_earned=0` | PASS (exists) |
| LO-02 | Int | Punches 09:00–20:00, calculate → OT PENDING; then approve leave | Read day + OT record | Day `LEAVE`, `ot_minutes_approved=0`, `ot_pending=False`; `overtime_record` for the day **deleted**; validate has no `PENDING_OVERTIME_APPROVAL` | PASS (by reading `delete_if_pending`) — add test |
| LO-03 | Int | Punches 09:00–20:00 → OT PENDING → **manager approves OT** → HR approves leave for that date | Read day | **Expected (D-8):** `ot_minutes_approved=0`, OT record `VOIDED`/`REJECTED` with reason, day `LEAVE` flagged. **Today:** `ot_minutes_approved=120`, record APPROVED, `ot_day_class=NULL` | **FAIL** (F2) |
| LO-04 | Int | As LO-03; HR keeps leave; finalize; create pay run; lock inputs | Read snapshot | **Expected:** 0 OT minutes for the employee. **Today:** 120 minutes at NORMAL multiplier | **FAIL** (F2) |
| LO-05 | Int | As LO-03 but the OT day was a **holiday** with HOLIDAY rate row 2.0× | Finalize + pay run | **Expected:** 0. **Today:** paid at NORMAL (NULL day class), not even the holiday rate | **FAIL** (F2) |
| LO-06 | Int | OT policy `comp_off_instead_of_pay=True`, AUTO chain; day earns comp-off; `credit_company` runs; then leave approved on that date | Read ledger | **Expected (D-8):** `COMP_OFF_CREDIT` offset by an `ADJUSTMENT`. **Today:** credit stays | **FAIL** |
| LO-07 | Int | Leave approved; then HR cancels leave; recompute | Read day | OT re-detected from punches as a fresh PENDING record | PASS |
| LO-08 | Int | OT APPROVED; leave approved then cancelled on the same day | Read | Frozen record unchanged throughout; day returns to `PRESENT` with the approved minutes | PASS (pins WD-29) |
| LO-09 | Int | Weekly cap 300; Mon OT 200 PENDING; Tue leave + punches (OT would be 200) | Calculate Tue | Tue `LEAVE`, 0 OT; Wed OT budget still 100 (Tue consumed nothing) | PASS — add test |

### 6.4 FLEXIBLE shift

| ID | Level | Setup | Steps | Expected | Today |
|---|---|---|---|---|---|
| FX-01 | Unit | FLEX window 08:00–10:00, required 480, grace 15; IN 09:30 OUT 17:30 | evaluate | `PRESENT`, `late_minutes=0`, `is_late=False` | **FAIL** (F1: late 75) |
| FX-02 | Unit | Same; IN 10:10 OUT 18:10 | evaluate | `late_minutes=0` (inside grace after `window_end`) | **FAIL** (late 115) |
| FX-03 | Unit | Same; IN 10:30 OUT 18:30 | evaluate | `late_minutes=15`, band LATE, `PRESENT` | **FAIL** (late 135 → HALF_DAY) |
| FX-04 | Unit | Same; IN 13:30 OUT 21:30 (late 195 after grace) | evaluate | band ABSENT → `ABSENT`, `late_minutes=195` | FAIL today only in the minute value (315) |
| FX-05 | Unit | Same; IN 09:00 OUT 09:50 then IN 10:30 OUT 18:30 | evaluate | `is_early_out=False` (early departure is judged on the last OUT), `is_late=False` | FAIL today only on `is_late` (same root cause as FX-01) |
| FX-06 | Int | FLEX shift employee, `lates_to_half_day_count=3`, arrives 09:30 on 3 days | Calculate day 3 | `PRESENT` | **FAIL** (forced HALF_DAY) |
| FX-07 | Unit | FLEX, required 480, IN 09:00 OUT 18:00 with 60-min unpaid AUTO_DEDUCT break | evaluate | worked 480, OT 0 | PASS (exists) |
| FX-08 | Unit | FLEX core 11–16, `core_hours_breach_behaviour=HALF_DAY`, IN 11:30 OUT 20:00 | evaluate | `HALF_DAY`, `is_core_hours_breach=True` | PASS (exists) |
| FX-09 | Unit | FLEX + `early_departure_requires_approval=True`, OUT 17:00 after 8 h from 09:00 | evaluate | **Expected:** no early-departure concept for FLEX (document) — today compares to `window_end` so 0; pin it | PIN |

### 6.5 ON_DUTY

| ID | Level | Setup | Steps | Expected | Today |
|---|---|---|---|---|---|
| OD-01 | Int | Approve ON_DUTY (`on_duty_requires_punch=False`), no punches, working day | Read day | `ON_DUTY`, paid 1.00, `on_duty=True`, `on_duty_regularization_id` set | PASS (exists) |
| OD-02 | Unit | `on_duty_requires_punch=True`, approved, no punches | evaluate | `INCOMPLETE`, `is_on_duty_flagged=True` | PASS (exists) |
| OD-03 | Unit | **Daily-wage**, Sunday (unpaid weekly off), ON_DUTY approved, no punches | evaluate | **Expected (D-4):** `ON_DUTY`, paid 1.00, `unpaid_off_fraction 0.00`; `paid+lop+unpaid_off = 1.00` | **FAIL** (F3: unpaid_off stays 1.00) |
| OD-04 | Int | As OD-03; validate period | Validate | **Expected:** READY. **Today:** `PAID_LOP_MISMATCH` | **FAIL** (F3) |
| OD-05 | Unit | Monthly, holiday with `is_paid=false`, ON_DUTY approved | evaluate | As OD-03 | **FAIL** (F3) |
| OD-06 | Unit | Monthly, Sunday (paid off), ON_DUTY approved | evaluate | `ON_DUTY`, paid 1.00, sum 1.00; summary bucket `on_duty_days` | PASS — add test (bucket choice is a product question: record it) |
| OD-07 | Unit | Half-day leave FIRST_HALF + ON_DUTY approved, no punches | evaluate | **Expected:** paid 1.00 (0.50 leave + 0.50 on-duty), status `HALF_DAY` or `ON_DUTY`, LOP 0. **Today:** `LEAVE`, LOP 0.50 | **FAIL** (F6) |
| OD-08 | Unit | ON_DUTY + punches 09:00–20:00 | evaluate | **Expected (D-5):** `ON_DUTY`, OT 0 when `on_duty_requires_punch=False`. **Today:** OT 120 pending | DECIDE |
| OD-09 | Unit | ON_DUTY approved on NOT_JOINED day | evaluate | `NOT_JOINED` unchanged | PASS (exists) |
| OD-10 | Int | ON_DUTY approved; later full-day leave approved same date | Read | `LEAVE` wins; `on_duty=False` | PASS — add test |
| OD-11 | Int | Half weekly off (Sat 0.50) + ON_DUTY, no punches | evaluate | paid 1.00, `weekly_off_fraction 0.50`; summary `on_duty 0.5 + weekly_off 0.5` | PASS — add test |

### 6.6 Overtime detection and policy

| ID | Level | Setup | Steps | Expected | Today |
|---|---|---|---|---|---|
| OT-01 | Unit | Sunday, shift does not operate, punches 09:00–18:00 (full shift) | evaluate | **Expected (D-1):** `ot_minutes_detected=540`, class WEEKLY_OFF, `worked_on_weekly_off=True`. **Today:** 0 | DECIDE / FAIL |
| OT-02 | Unit | Sunday, `operates_on_weekly_off=True`, punches 09:00–20:00 | evaluate | OT 120 (beyond shift), class WEEKLY_OFF — shift operates, so "beyond" is right | PASS |
| OT-03 | Unit | Holiday, roster `is_holiday_working_override`, punches 09:00–18:00 | evaluate | **D-1:** 0 OT if "operates" semantics, else 540. Record decision | DECIDE |
| OT-04 | Unit | `eligibility=GRADE_VIA_ASSIGNMENT` | evaluate | **Expected (D-9):** publish refused / treated per grade. **Today:** identical to ALWAYS | DECIDE / PIN |
| OT-05 | Unit | `eligibility=SHIFT_FLAG`, shift `is_ot_eligible=False`, 2 h extra | evaluate | 0 OT, not eligible | PASS (exists) |
| OT-06 | Unit | `night_ot_mode=SHIFT_FLAG`, `is_night_shift=True`, OT 60 | evaluate | class NIGHT; summary `ot_minutes_night` | PASS (exists) |
| OT-07 | Unit | `night_ot_mode=WINDOW` 22:00–06:00, day shift 09–18, OUT 22:30 | evaluate | NIGHT | PASS (exists) |
| OT-08 | Unit | NIGHT with no NIGHT rate row | evaluate | classification falls back to NORMAL row; `ot_day_class` still NIGHT | PASS (exists) |
| OT-09 | Unit | FIXED 09–18 with 60-min unpaid AUTO_DEDUCT lunch; punches 09:00–18:00 | evaluate | worked 480, net schedule 480, OT 0 | PASS |
| OT-10 | Unit | Same; punches 09:00–19:00 | evaluate | OT 60 (not hidden by the deducted lunch) | PASS |
| OT-11 | Unit | Legacy (mode-less) unpaid break 13–14, PAIR_ALL, punches 09–13, 14–19 | evaluate | worked 540, schedule 540 (legacy breaks don't reduce the schedule), OT 0 | PASS (exists) |
| OT-12 | Int | Weekly cap 300; Mon 200 APPROVED, Tue 200 → clamped 100; manager **rejects** Mon | Recompute Tue | Tue still 100 until recomputed; after recompute 200 | PIN (WD-29 d.3) |
| OT-13 | Int | OT APPROVED; employee's MISSING_PUNCH regularization adds an earlier IN (more OT) approved | Read | OT record unchanged (frozen); `ot_minutes_detected` on the day updated informationally | PIN (WD-29 d.2) |
| OT-14 | Int | OT REJECTED; later regularization removes the extra hours | Read | Record stays REJECTED; day `ot_minutes_approved=0` | PIN |
| OT-15 | Int | `requires_post_approval=False`, chain MANAGER | Calculate | AUTO_APPROVED immediately, `ot_minutes_approved` set | PASS (exists) |
| OT-16 | Int | Manager changed (dated before the OT day) while record PENDING; recompute | Read | `resolved_approver_manager_id` unchanged | PASS (code comment 4674–4684) — add test |
| OT-17 | Unit | `min_ot_minutes=30`, excess 29 | evaluate | 0, not eligible flag `False` | PASS (exists) |
| OT-18 | Unit | Daily cap 120, excess 200, rounding UP 15 | evaluate | 120 | PASS (exists) |
| OT-19 | Int | Comp-off policy, AUTO; `credit_company`; `expire_company` after 60 days | Ledger | credit then full offset | PASS (leave suite) |
| OT-20 | Unit | SPLIT shift, both blocks worked plus 90 min | evaluate | OT 90 against `required_minutes` net of V1 unpaid breaks | PASS (exists) |

### 6.7 Attendance policy settings in combination

| ID | Level | Setup | Steps | Expected | Today |
|---|---|---|---|---|---|
| AP-01 | Unit | `lates_to_half_day_count=3`, `prior_late_days_in_window=2`, IN 09:20 | evaluate | `HALF_DAY` | PASS (exists) |
| AP-02 | Int | Same policy; two lates in September, one on 1 October | Calculate 1 Oct | `PRESENT` (window is the calendar month) | PASS — add test |
| AP-03 | Int | Same; full-day leave on a day with punches at 09:30 | Later day | Leave day not counted (`is_late` zeroed) | PASS — add test |
| AP-04 | Unit | `early_departure_requires_approval=True`, approved request on file, OUT 17:00 | evaluate | graduated band (LATE-equivalent), not harshest | PASS (exists) |
| AP-05 | Int | Approve `EARLY_DEPARTURE_APPROVAL` for next Friday | Read days list | **Expected:** no `AttendanceDay` row before the date (or a row without `is_regularized`). **Today:** INCOMPLETE row created now, `is_regularized=True` | **FAIL** (F10, low) |
| AP-06 | Int | As AP-05; Friday arrives, punches 09:00–16:00 | Recompute | `PRESENT`, early 105 → graduated band, `is_regularized=True` | PASS |
| AP-07 | Unit | `missing_punch_behaviour=ABSENT`, IN 09:00 no OUT | evaluate | `ABSENT`, LOP 1.00 | PASS (exists) |
| AP-08 | Unit | `missing_punch_behaviour=AUTO_CLOSE`, IN 09:00 no OUT | evaluate | **Today:** `INCOMPLETE`-like outcome via bands with `worked_minutes=0` → INCOMPLETE; pin that AUTO_CLOSE ≡ INCOMPLETE | PIN |
| AP-09 | Unit | `excess_break_days_to_half_day_count=2`, prior 1, excess break today with `excess_outcome=EXCEPTION` | evaluate | `HALF_DAY` | PASS (exists) |
| AP-10 | Unit | Same but break rule `excess_outcome=RECORD_ONLY` | evaluate | No override (`counter_excess_minutes=0`) | PASS — add test |
| AP-11 | Unit | Unresolved break START, day closed, punches 09:00–18:00 | evaluate | `INCOMPLETE`, presence credited only up to the START | PASS (exists) |
| AP-12 | Int | As AP-11; finalize with TREAT_ABSENT | Finalize | LOP 1.00 for that day; `ATTENDANCE_INCOMPLETE_RESOLVED_AT_LOCK` lists it | PASS — add test (documents the business impact) |
| AP-13 | Int | Policy version A (grace 0) published; day computed; version B (grace 30) published effective yesterday | Recompute day | Day re-resolves to version B (recompute always re-resolves as-of date) | PASS — add test (mid-period policy change was never tested) |
| AP-14 | Int | Assignment shift changed mid-month (effective 15th) | Calculate 14th and 15th | 14th uses old shift, 15th new; both snapshot their `shift_version_id` | PASS — add test |
| AP-15 | Int | Branch timezone changed with computed days | PATCH branch | Refused while computed attendance exists (`has_computed_attendance_blocking_timezone_change`) | PASS (exists elsewhere) |
| AP-16 | Unit | DST-zone shift (e.g. `Europe/London`, 31 Mar) 22:00–06:00 cross-midnight | evaluate | `scheduled_minutes=420` (clock change honoured) | ☑ never tested — add |

### 6.8 Regularization × leave / OT / lock

| ID | Level | Setup | Steps | Expected | Today |
|---|---|---|---|---|---|
| RG-01 | Int | Full-day leave approved; employee submits MISSING_PUNCH for that date | Submit | **Expected (UX):** 409 or warning "date is on approved leave". **Today:** accepted; on approval the day is flagged for HR | DECIDE (low) |
| RG-02 | Int | MISSING_PUNCH approved on a leave day | Approve | `LEAVE`, `work_on_leave_flagged`, validate blocked | PASS (exists) |
| RG-03 | Int | WRONG_SHIFT to a night shift on a date with PENDING OT | Approve | Roster PUBLISHED; recompute replaces the PENDING record with the new day class | PASS — add test |
| RG-04 | Int | Regularization submitted; leave approved for the same date before the manager acts | Approve regularization | Punches applied; day `LEAVE` flagged; `PENDING_REGULARIZATION` cleared | PASS — add test |
| RG-05 | Int | Policy `blocked_when_locked=False`; date inside a CLOSED period | Submit | Still refused with `ATTENDANCE_PERIOD_CLOSED` (the flag cannot opt out of the period lock) | PASS — add test (pins CT8/L10) |
| RG-06 | Int | Request for a date before joining | Submit | 422 outside employment | PASS (exists) |
| RG-07 | Int | BREAK_CORRECTION, policy chain AUTO | Submit | Rerouted to HR stage | PASS (exists) |

### 6.9 Period finalize and payroll hand-off

| ID | Level | Setup | Steps | Expected | Today |
|---|---|---|---|---|---|
| PF-01 | Int | Month with: 20 present, 1 half-day leave + worked half, 1 full leave, 4 Sundays, 1 holiday, 2 INCOMPLETE (TREAT_ABSENT), 1 ON_DUTY | Finalize | Buckets sum to days in month; `paid+lop+unpaid_off = payable`; `leave_days 1.5`, `present 20.5`, `absent 2`, `holiday 1`, `weekly_off 4`, `on_duty 1` | PASS (unit `test_period_summary` analogues) — add one integration run |
| PF-02 | Int | Employee transferred to legal entity B on the 16th | Finalize A and B | A owns 1–15, B owns 16–31; each summary `payable_days` matches; neither blocks on the other's rows | PASS (exists partly) |
| PF-03 | Int | Day with `paid 1.00 + unpaid_off 1.00` (OD-03) | Validate | **Expected:** READY after fix. **Today:** `PAID_LOP_MISMATCH` | **FAIL** (F3) |
| PF-04 | Int | LEAVE day carrying frozen `ot_minutes_approved` (LO-03) | Finalize → `closed_period_for_month` | **Expected:** 0 OT rows. **Today:** OT row, class NORMAL | **FAIL** (F2) |
| PF-05 | Int | Period CLOSED; pay run INPUTS_LOCKED; HR reopens period | Reopen | Refused once the run is FINALISED; allowed before (run must be rolled back) | PASS (payroll suite) |
| PF-06 | Int | Reopen; cancel a leave; re-finalize | Summary | New summary reflects the recompute; old rows replaced | PASS (exists) |
| PF-07 | Int | Daily-wage employee month | Finalize | `unpaid_off_days` = Sundays; paid days exclude them; payroll prorates on `paid_days` | PASS (exists unit) — add integration |
| PF-08 | Int | Comp-off OT day (`comp_off_minutes_earned>0`) | Pay run | Not in payable OT; present in Leave ledger | PASS (query filter) — add test |

### 6.10 Suggested unit fixture additions

To make the above cheap to write, `test_calculation.py` would benefit from one shared builder
with keyword overrides for: `shift_type`, `window_start/end`, `core_start/end`,
`leave_entries`, `on_duty_approved`, `pay_basis`, `calendar_day_type`, `holiday_type/is_paid`,
`weekly_off_fraction`, `prior_late_days_in_window`, `early_departure_pre_approved`. The
flexible-overtime test module already has 80% of it (`_run`).

---

## 7. Coverage summary against the existing suite (967 attendance tests)

| Area | Existing | Gap |
|---|---|---|
| Full-day leave overlay | 24 integration + unit | OT-approved-before-leave (F2); PENDING OT deleted on leave sync; comp-off reversal |
| Half-day leave | 5 | Every penalty/INCOMPLETE/late-counter interaction (LH-02…LH-12) |
| ON_DUTY | 4 unit + 1 integration | Off-day pay basis (F3), + leave (F6), + OT, + half weekly off |
| FLEXIBLE | 11 unit (OT only) | **Zero** lateness/early assertions (F1) |
| OT caps/chains/night | 21 integration + 10 unit | Off-day full-shift OT (D-1), approver pinning on recompute |
| Cumulative counters | 4 unit | Month boundary, leave-day exclusion, RECORD_ONLY exclusion |
| Period finalize | 25 | Integration-level mixed-month reconciliation; F2/F3 blockers |
| Mid-period changes (policy/shift/assignment) | 0 | AP-13, AP-14 |
| DST | 0 | AP-16 |

---

## 8. Recommended order of work (after decisions)

1. **F2** (leave after approved OT) — payroll-visible, no decision strictly needed to stop
   paying: filter `attendance_status = 'LEAVE'` out of the payable query and summary, then do
   the proper void per D-8.
2. **F3** (ON_DUTY unpaid off day) — one line in `_apply_on_duty_overlay`
   (`unpaid_off_fraction="0.00", weekly_off_fraction` preserved) once D-4 is confirmed.
3. **F1** (FLEX lateness) — compute `late_raw` against `window_end` for FLEX; add FX-01…FX-06.
4. **F4/F5/F6** (half-day leave) — needs D-2/D-3; implement half-aware evaluation or at least
   stop overriding ABSENT/INCOMPLETE and zero late/early for the leave half.
5. **F7** (leave vs roster/calendar) — D-6/D-7; Leave should call the same roster lookup
   attendance uses.
6. **F8/D-1** — off-day OT basis; unblocks BUS-015's comp-off step rule as well.
7. Pin the documented limitations (OT-12…14, AP-08) so future refactors cannot silently
   change them.

*No code was changed for this audit. All findings are reproducible from the cited lines; the
"FAIL today" test cases are the reproduction recipes.*
