# Attendance, Work Calendar, Weekly-Off and Overtime — Combined Audit

**Date:** 16 November 2026 · **Branch:** `test` at `dd71571` (engine version 14) · **No code changed.**

Builds on `SHIFT_MANAGEMENT_AUDIT_2026-11-15.md` and `SHIFT_REMEDIATION_PLAN_2026-11-15.md`.
Everything those fixed (one resolved schedule, punch ownership, the recalculation queue, N-02/N-03)
was re-checked here and is not repeated as a finding.

**Evidence levels used below**

- **Reproduced** — shown by running the code: an integration probe through the HTTP API against the
  isolated `hrms_test` database, or a probe of the pure engine (`calculation.evaluate_day`).
- **Code** — confirmed by reading every write path involved; not run end to end.
- **Plausible** — a risk the code allows but that was not reproduced. Never counted as a bug.

The probe scripts were temporary and have been removed; the engine probe is described in Appendix A
so it can be rerun.

---

## 1. Executive summary

The **calculation core is in good shape**. For one employee-date, the engine now has one resolved
schedule, one calendar answer, deterministic punch ownership, a clear overlay order, and
period-close checks that fail closed. Locked periods do not change silently, and a period whose
payroll is finalised cannot be reopened. Timezone handling is correct for Asia/Kolkata.

The weak point is **what happens after a day has been calculated once**. Four confirmed defects
let payroll inputs drift from reality:

| ID | Severity | One line |
|---|---|---|
| AC-01 | **Critical** | Once overtime is decided (including auto-approved), later corrections never change it. Approved minutes can exceed detected minutes, and they are paid at the day's *new* rate class. |
| AC-02 | **High** | Holiday, weekly-off pattern, work-calendar and calendar-exception changes queue no recalculation. Days stay wrong until period close. |
| AC-03 | **High** | Leave day breakdowns are fixed when the leave is submitted. A later holiday change charges leave on a holiday, or leaves an unpaid gap inside approved leave. |
| AC-04 | **High** | A day that ends `INCOMPLETE` still earns overtime, and keeps it when lock resolves the day as absent (full loss of pay plus overtime pay). |

**Answer to the final question:** not yet. Section 11 lists what must be fixed first.

---

## 2. Architecture and data flow

### 2.1 Pipeline for one employee-date

| Step | Source of truth | Code | Output |
|---|---|---|---|
| Employment gate | `employment` | `EmploymentService.get_employment_as_of` | `ACTIVE` / `NOT_JOINED` / `EXITED` |
| Resolved schedule | `shift_roster` (published) > `employee_assignment.shift_id` > none | `work_schedule.WorkScheduleResolver.resolve` | shift version, timings, timezone, roster overrides |
| Calendar context | `work_calendar` + `holiday_calendar`/`holiday` + `weekly_off_pattern` + `calendar_exception`, via `policy_assignment` | `organisation/calendar_resolution.classify_work_calendar_date`, `resolve_for_employee` | `WORKING`/`SPECIAL_WORKING`/`HOLIDAY`/`WEEKLY_OFF`/`SHUTDOWN`, off fraction, holiday type and paid flag |
| Expected to work? | calendar + shift `operates_on_*` + roster overrides | `calculation._work_not_expected`, `_shift_operates` | `not_expected` |
| Policies | `policy_assignment` → published versions | `attendance/resolution.py` | attendance, overtime and regularization policy versions |
| Leave | `leave_day_projection` (active) | `LeaveProjectionService.sync`, `repository.list_active_for_employee_date` | fraction, half, paid flag |
| Punch ownership | `punch` (not superseded) | `punch_ownership.py`, `ownership_service.PunchOwnershipService` | the punches this date owns |
| Pairing and time | owned punches | `collapse_duplicate_punches` → `drop_stray_punches` → `pair_punches` → `evaluate_presence_and_breaks` | worked, break, late and early minutes |
| Status | bands + overrides | `_resolve_primary_status`, `_paid_lop_fraction` | status, paid / LOP / unpaid-off fractions |
| Overtime detection | overtime policy + sibling-day caps | `detect_overtime`, `resolve_is_night_ot` | detected minutes, day class |
| Overlays | | `_apply_overlays`: off-day pay → half weekly off → ON_DUTY → leave | final day result |
| Overtime decision | `overtime_record` | `service._resolve_ot_decision`, `_sync_overtime_record` | `PENDING` / `AUTO_APPROVED` / `APPROVED` / `REJECTED` |
| Store | `attendance_day`, `attendance_break`, `overtime_record` | `AttendanceDayService._calculate` | row with `computation_snapshot` and `engine_version` |
| Period close | `attendance_period` | `AttendancePeriodService.finalize` | recalculates unlocked days, validates, resolves `INCOMPLETE`, locks, writes `attendance_period_summary` |
| Payroll | locked days + summary | `PayrollPeriodInputs`; `list_payable_overtime_for_period` | days, LOP, overtime minutes by multiplier |

### 2.2 Recalculation triggers (Part 11)

| Event | Affected days | Recalculated? | How |
|---|---|---|---|
| Punch created (live or on behalf) | punch's local date + its owner | Yes | immediate, best effort (`_try_immediate_calculate`) |
| Regularization applied | the request's date | Yes | in the approval transaction |
| Leave approved / cancelled | each leave date | Yes | `LeaveProjectionService.sync` / `cancel` |
| Shift version published | days on that shift from `effective_from` | Yes | `attendance_recalc_request` queue |
| Assignment, roster, swap | employee dates | Yes | queue |
| Policy *assignment* created / ended | scope from `effective_from` | Yes | queue |
| Attendance-policy *version* published | all days it covers | **No** | AC-07 |
| Overtime-policy *version* published | all days it covers | **No** | AC-07 |
| Holiday created / edited / deactivated | that date, every employee on the calendar | **No** | AC-02 |
| Holiday calendar validity edited | its date range | **No** | AC-02 |
| Weekly-off pattern edited | every matching date | **No** | AC-02 |
| Work calendar edited (pattern, linked holiday calendars) | everyone on it | **No** | AC-02 |
| Calendar exception created / edited | that date | **No** | AC-02 |
| Any of the above → leave breakdown | approved leave in range | **No** | AC-03 |
| Daily sweep | today and the 2 days before | Yes | Beat, 09:30 IST |
| Period finalize | every unlocked day of the period | Yes | `_recalculate_open_days` (R-09) |

The queue only recalculates **existing, unlocked** rows. It is idempotent: processing a request
twice costs time, not correctness.

---

## 3. Policy decision map

### Decided and implemented

| Area | Rule in force | Where |
|---|---|---|
| Schedule precedence | published roster row > assignment shift > none; a roster row with no shift means no shift | `work_schedule.py` |
| Calendar precedence | calendar exception > holiday (first linked list wins; `WORKING_HOLIDAY` is a working day) > weekly off > working | `classify_work_calendar_date` |
| Holiday on a weekly off | counted once, as the holiday | same |
| Shift operates on holiday / weekly off | ordinary working day: no-show follows the missing-punch rule, work is NORMAL class, leave charges the day (P-02) | `_work_not_expected` |
| No shift | hour bands only; no late, early or overtime; a holiday/weekly off with no punches is a day off (P-06) | `_evaluate_no_schedule` |
| Work on a day off the shift does not operate | never costs pay; every minute is overtime (D-1) | `_off_day_overtime_basis`, `_off_day_work_pay` |
| Paid days off | Monthly: every day off is paid. Daily wage: only `PUBLIC`/`SUBSTITUTE` holidays. A holiday with `is_paid=false` is unpaid for everyone (BUS-001) | `_off_day_is_paid` |
| Early arrival on a FIXED shift | recorded, not credited, not overtime | `clamp_pairs_to_start` |
| Grace | forgives late/early minutes; credited to the hour-band lookup only (N-02) | `grace_band_credit` |
| Full-day leave | wins over everything except the employment gate; overtime zeroed; punches raise `work_on_leave_flagged`, which blocks close (BUS-011/012) | `_apply_leave_overlay` |
| Sandwich rule | days off between two leave days are charged as leave, within one application and across applications of the same type (R-02) | `leave/service._compute_day_breakdown` |
| Unresolved `INCOMPLETE` at close | per policy: `TREAT_ABSENT` (default) / `TREAT_PRESENT` / `KEEP_INCOMPLETE` (blocks close) | `_apply_incomplete_lock_resolution` |
| Decided overtime | frozen; never revised by a recompute (WD-29 decision 2) | `_resolve_ot_decision` — see AC-01 |

### Open — carried over from the shift audit

P-01 (holiday at the end of an overnight shift), P-04 (early arrival as overtime), P-05 (bands for
short shifts), P-07 (grace model), P-10 (night flexible shifts), P-11 (split-shift late/early),
P-12 (roster change after leave), P-14 (two shifts per day).

### New decisions required by this audit — see section 7.

---

## 4. Precedence matrix

Monthly-paid employee, FIXED 09:00–18:00 shift, hour bands ABSENT <4h, HALF_DAY 4–8h, PRESENT ≥8h,
overtime eligible, `missing_punch_behaviour = INCOMPLETE`, `TREAT_ABSENT` at lock. "OT" means
detected overtime minutes and day class.

| # | Shift | Holiday | Weekly off | Leave | Punches | Result (actual code) |
|---|---|---|---|---|---|---|
| 1 | yes | – | – | – | none | INCOMPLETE → LOP 1.00 at lock |
| 2 | yes | – | – | – | 09–18 | PRESENT, 1.00 paid |
| 3 | yes, not operating | yes | – | – | none | NOT_EXPECTED, 1.00 paid (daily wage: only PUBLIC/SUBSTITUTE paid) |
| 4 | yes, not operating | yes | – | – | 2h | PRESENT, 1.00 paid, OT 120 HOLIDAY |
| 5 | yes, not operating | yes | – | – | IN only | NOT_EXPECTED, paid, flagged missing punch |
| 6 | operates on holiday | yes | – | – | none | INCOMPLETE → LOP at lock (P-02) |
| 7 | operates on holiday | yes | – | – | 3h | ABSENT (bands), LOP 1.00 (P-02) |
| 8 | yes | – | full | – | none | NOT_EXPECTED, paid |
| 9 | yes | – | full | – | 09–18 | PRESENT, paid, OT 540 WEEKLY_OFF |
| 10 | yes | – | half (0.50) | – | none | 0.50 paid, 0.50 LOP |
| 11 | yes | – | half | – | 09–13 | PRESENT, 1.00 paid |
| 12 | yes | – | half | – | 09–18 | PRESENT, 1.00 paid, **OT 0** (P-A) |
| 13 | any | yes | yes (same day) | – | – | treated as the holiday, counted once |
| 14 | yes | – | – | full, paid | none | LEAVE, 1.00 paid |
| 15 | yes | – | – | full | 09–18 | LEAVE, OT 0, `work_on_leave_flagged` (blocks close) |
| 16 | yes | – | – | half, paid | other half worked | HALF_DAY status, 1.00 paid |
| 17 | yes | – | – | half, paid | none | LEAVE, 0.50 paid, 0.50 LOP |
| 18 | yes | yes | – | full projection (sandwich or stale) | none | LEAVE; paid only if the leave type is paid (AC-03) |
| 19 | none | yes, or weekly off | – | – | none | NOT_EXPECTED, paid |
| 20 | none | – | – | – | none | INCOMPLETE or ABSENT (`missing_shift_behaviour`) |
| 21 | none | any | – | – | punches | hour bands; no late/OT; on a day off always PRESENT, paid |
| 22 | roster week-off | – | – | – | none | NOT_EXPECTED, paid |
| 23 | roster week-off | – | – | – | 09–18 | PRESENT, paid, OT 540 **NORMAL** (AC-06) |
| 24 | roster "working this holiday" | yes | – | – | – | ordinary working day (as row 6) |
| 25 | any | – | – | – | ON_DUTY approved | ON_DUTY, 1.00 paid, OT 0 (unless the policy requires punches) |
| 26 | – | – | – | – | before joining / after exit | NOT_JOINED / EXITED: not paid, not LOP |

Overlay order inside the engine: employment gate → configuration errors → roster week-off with no
punches → no-shift path → not-expected with no punches → punch evaluation → off-day pay → half
weekly off → ON_DUTY → leave (leave wins).

---

## 5. Use-case coverage matrix

"Engine" = pure-engine probe (Appendix A). "API" = integration probe. "Code" = by reading.

| Scenario | Expected | Actual | Status |
|---|---|---|---|
| Normal IN 09:00 → OUT 18:00 | PRESENT, no OT | PRESENT, OT 0 | PASS (engine) |
| Late departure, OUT 21:00 | 180 OT | 180 NORMAL | PASS (engine) |
| Early arrival, IN 07:30 | not OT (current rule) | 0 OT, worked 540 | PASS; P-04 open |
| Night 22:00–06:00, OUT 09:00 next day | owned by the start day, 180 OT NIGHT | as expected | PASS (engine) |
| Duplicate / stray same-direction punches | earliest IN, latest OUT kept | as expected; strays named in snapshot | PASS (code + existing tests) |
| IN → IN (5h apart) → OUT | INCOMPLETE for review | INCOMPLETE | PASS (code) |
| Forgotten OUT + next-morning OUT | not a 24-hour day | both days INCOMPLETE (N-03) | PASS (prior tests) |
| Grace boundary: IN 09:10 with 10-min grace | not late | late 0 | PASS (engine) |
| Grace + 1 minute | 1 late minute | late 1, PRESENT | PASS (engine) |
| Holiday, no shift operation, no-show | paid day off | NOT_EXPECTED, 1.00 | PASS (engine) |
| Holiday, works 2h | paid, OT per policy | 1.00 + 120 HOLIDAY OT | PASS (D-1) |
| Holiday, shift operates, 3h worked | per P-02 | ABSENT, LOP | PASS (as decided) |
| Holiday added after the day was calculated | day updates | **stays INCOMPLETE/WORKING** until manual recompute or close | **BUG AC-02** (API) |
| Holiday removed after holiday OT auto-approved | OT drops to 60 NORMAL | **day: 60 detected, 600 approved, class NORMAL; record: 600 HOLIDAY** | **BUG AC-01** (API) |
| OUT corrected 19:00 → 18:00 after auto-approved OT | OT 0 | **detected 0, approved 60** | **BUG AC-01** (API) |
| Holiday added inside approved leave | holiday not charged | leave still charged; day shows LEAVE | **BUG AC-03** (code + engine) |
| Holiday removed inside approved leave | day becomes a leave day | no projection; INCOMPLETE → LOP at lock | **BUG AC-03** (code) |
| Pair 09–20 then stray IN 20:45 | INCOMPLETE; no OT until resolved | INCOMPLETE **and 120 OT auto-approved** | **BUG AC-04** (engine) |
| Half-day leave (first half), works 14:00–22:00 | ~240 OT after shift end | **OT 0** | **BUG AC-05** (engine) |
| Half-day leave (second half), works 09:00–21:00 | work in leave half flagged | 1.00 paid + 180 OT, nothing flagged | **BUG AC-05** (engine) |
| Calendar weekly off vs roster week-off, both 09–18 worked | same rate class | WEEKLY_OFF vs **NORMAL** | **BUG AC-06** (engine) |
| Late 80 min (HALF_DAY band), stays to 21:00 | decision needed | 0.50 LOP **and** 90 OT | POLICY P-B (engine) |
| Half-day weekly off, full shift worked | decision needed | 1.00 paid, OT 0 | POLICY P-A (engine) |
| Daily wage, weekly off, full shift | paid once | unpaid-off 1.00 + 540 OT | PASS (BUS-001 design) |
| Unpaid leave sandwiched across a holiday | per sandwich rule | holiday = LEAVE, LOP 1.00 | PASS (R-02 design) |
| Full-day leave + punches | leave stands, flagged | LEAVE, OT 0, close blocked until resolved | PASS (existing tests) |
| Leave approved after attendance exists | day recalculated | recalculated in `sync` | PASS (code) |
| Period close with stale days | recalculated first | `_recalculate_open_days` | PASS (code) |
| Change into a locked or closed period | refused, or ignored for locked rows | locked rows never recalculated; leave/OT/punch writes refused | PASS (code) |
| Reopen after payroll finalised | refused | refused | PASS (code) |
| Midnight punch on a no-shift day | owned by start date | 20:00 → 00:00 = 240 min, start date | PASS (engine) |
| Business "today" | Asia/Kolkata | `business_today(company.timezone)` everywhere that matters | PASS (code) |

---

## 6. Confirmed bugs

### AC-01 — Decided overtime never follows corrections (Critical, reproduced)

**Root cause.** `AttendanceDayService._resolve_ot_decision` (`attendance/service.py:5066`) returns a
"frozen" decision for any `overtime_record` not in `PENDING`, and `_calculate` writes the frozen
`minutes_approved` onto the day row (`service.py:4093`). `AUTO_APPROVED` counts as decided, so with
`approval_chain = AUTO` or `requires_post_approval = false`, the **first** calculation that sees
overtime freezes it. No path reopens a decided record: regularization, holiday, shift and policy
changes all recompute the day, but never the decision. The day row's `ot_day_class` and
`overtime_policy_version_id` come from the fresh calculation; the minutes come from the frozen
record.

**Reproduction (API, `hrms_test`).**
1. FIXED 09:00–18:00 shift, overtime policy `approval_chain = AUTO`. Punch 09:00 and 19:00. Day:
   60 OT approved.
2. Approve a `WRONG_PUNCH` regularization moving the OUT to 18:00.
3. Day now: `worked 540, ot_minutes_detected 0, ot_minutes_approved 60, ot_day_class null`.

Second reproduction: holiday on the date, work 09:00–19:00 → 600 HOLIDAY OT auto-approved. Then
deactivate the holiday and recompute: day `detected 60, approved 600, ot_day_class NORMAL`;
record `600, HOLIDAY`.

**Impact.**
- `AttendanceDayRepository.list_payable_overtime_for_period` sums `attendance_day.ot_minutes_approved`
  grouped by the day row's `ot_day_class`, priced by the day row's policy version. In the second
  case payroll pays **600 minutes at the NORMAL multiplier** for 60 real overtime minutes. If no
  NORMAL multiplier is configured, payroll refuses instead.
- It breaks the invariant *normal + overtime ≤ worked*.
- The reverse also loses pay. A day capped by the weekly or monthly limit and auto-approved stays
  capped after an earlier day's overtime is corrected down.
- Comp-off follows the record (`list_comp_off_facts`), so it is credited for the frozen minutes.

**Recommended fix.** When a recompute's detected minutes, day class or policy version differ from
a decided record's, do not keep the old decision silently:
- **AUTO decisions:** re-derive them (they were never a human judgement).
- **Human `APPROVED`/`REJECTED` decisions:** set the record back to `PENDING` and record a
  `SUPERSEDED_BY_RECALCULATION` action.
- Cap `ot_minutes_approved` at `ot_minutes_detected`.
- Take the day class from the record that is paid.
- Make period validation block on `ot_minutes_approved > ot_minutes_detected`.

The exact handling of a human approval is P-C.

### AC-02 — Calendar changes do not recalculate attendance (High, reproduced)

**Root cause.** `OrganisationService.create_holiday`, `update_holiday` (activate, deactivate, date,
type, paid), `update_holiday_calendar` (validity), `update_weekly_off_pattern`,
`update_work_calendar` and `create/update_calendar_exception` never call `request_recalc`. Neither
does `CalendarImpactService.confirm` (its docstring says so). Web
(`holiday-calendars/[id]/page.tsx:286`, `weekly-off-patterns/[id]/page.tsx:150`) and mobile
(`attendance_repository.dart:324`, `org_resources.dart:201`) call these endpoints directly, without
the preview.

**Reproduction (API).** Calculate 10 Aug 2026 with no punches → INCOMPLETE/WORKING. Add a holiday
on 10 Aug. `attendance_recalc_request` gains nothing and the day stays INCOMPLETE/WORKING,
`paid 0.00`. A manual recompute gives NOT_EXPECTED/HOLIDAY/1.00, so the calendar is right and only
the stored row is stale.

**Impact.**
- Days older than the 3-day sweep stay wrong until period finalize. Finalize does recalculate them
  (R-09), so the closed period itself is correct.
- In the meantime, wrong data reaches dashboards, the attendance overview, employee day views and
  the `INCOMPLETE` reminder emails (`reminders.py` reads stored rows), so people are told to fix
  holidays.
- A recompute through this path also runs into AC-01.

**Recommended fix.** Queue `request_recalc` from each mutation:
- **Holiday:** both the old and the new date, scoped to the work calendars that link the holiday
  calendar.
- **Pattern / work calendar:** `effective_from` (or the earliest affected date) to today, scoped to
  employees on those calendars.
- **Exception:** its date.

Reuse the impact service's population resolution for the scope.

### AC-03 — Leave breakdowns ignore later calendar and schedule changes (High, code-confirmed)

**Root cause.** `LeaveApplicationService._compute_day_breakdown` decides at **submit** time which
days consume leave (`_working_shares`), and approval projects exactly those days. Nothing
re-derives them when the calendar, an operating shift or a roster changes. Calendar changes
explicitly "never rewrite leave days" (`calendar_impact.py` docstring); P-12 is the roster version
of the same gap.

**Effects.**
- **Holiday added inside approved leave.** The projection stays (fraction 1.00). Full-day leave
  outranks NOT_EXPECTED (`_apply_leave_overlay`), so the day shows LEAVE and the leave balance stays
  debited for a holiday (engine probe E14).
- **Holiday removed inside approved leave.** No projection exists for that date. The day becomes
  WORKING with no punches → INCOMPLETE → **LOP 1.00 at lock**, in the middle of an approved leave.
- **Sandwich days** decided against the old calendar keep their old status.

**Impact.** Wrong leave balances, and loss of pay in the middle of approved leave. Period
validation does not detect either case.

**Recommended fix.** Whenever a calendar or schedule change touches dates inside approved leave:
recompute that leave's breakdown, release or add days with ledger entries (the `_release_days`
pattern already exists), then sync projections. That sync recalculates attendance. At minimum, add
a period-close blocker listing leave whose breakdown disagrees with the current calendar.

### AC-04 — Overtime on a day that ends INCOMPLETE (High, reproduced in engine + code)

**Root cause.** `_evaluate_fixed_or_flex` and `_evaluate_split` run `detect_overtime` whatever the
status, so an `INCOMPLETE` day (an orphan punch beside a complete pair) gets overtime and, under
AUTO, an `AUTO_APPROVED` record. At close, `_apply_incomplete_lock_resolution` rewrites only the
paid and LOP fractions. Validation blocks `PENDING_OVERTIME_APPROVAL` but not overtime on an
`INCOMPLETE` day.

**Reproduction (engine E2).** Punches 09:00 IN, 20:00 OUT, then a stray IN at 20:45 → `INCOMPLETE`,
120 overtime minutes approved. At lock under `TREAT_ABSENT`, the day becomes paid 0.00 / LOP 1.00
while the 120 overtime minutes stay payable.

**Impact.** The employee loses a full day's pay and is also paid overtime for that day.

**Recommended fix.** Hold overtime on an `INCOMPLETE` day as `PENDING`, and never auto-approve it.
Then either:
- block close when an `INCOMPLETE` day has overtime, or
- at lock, zero it under `TREAT_ABSENT` and keep it under `TREAT_PRESENT`.

### AC-05 — Overtime ignores half-day leave (Medium, reproduced in engine)

**Root cause.** On a half-day-leave day the engine judges lateness, early departure and hour bands
against the worked half (`_half_day_leave_half`, `grace_band_credit`). Overtime still compares
worked minutes with the **full** schedule (`ot_scheduled_minutes`, `calculation.py:2559`).

**Reproduction.**
- **E7b:** first half on leave; works 14:00–22:00, four hours past shift end → **0 overtime**.
- **E7c:** second half on leave; works 09:00–21:00 → 1.00 paid (0.50 leave + 0.50 work) **plus 180
  overtime**, and the work during the leave half is not flagged.

**Impact.**
- Legitimate overtime is lost.
- Leave time worked is paid twice: once as leave, once as work and overtime.

**Recommended fix.**
- Use half the net schedule as the overtime basis when one half is on leave.
- Flag punches inside the leave half the way `work_on_leave_flagged` does for a full day.

### AC-06 — Roster week-off work is priced as a normal day (Medium, reproduced in engine)

**Root cause.** `classify_ot_day` is fed `worked_on_weekly_off`, which reads the *calendar*
`day_type`. A roster week-off on a calendar working day is "not expected" (all minutes are
overtime) but classifies as `NORMAL`.

**Reproduction.** E13 vs E13b: the same 540 minutes worked → WEEKLY_OFF on a calendar weekly off,
NORMAL on a roster week-off.

**Impact.** Rotating-roster staff are paid the normal overtime rate for work on their day off.

**Recommended fix.** Treat `roster_week_off_override` as `WEEKLY_OFF` for the overtime class (and
for `worked_on_weekly_off`).

### AC-07 — Policy version publish does not recalculate (Medium, code-confirmed)

**Root cause.** `publish_attendance_policy_version` and `publish_overtime_policy_version` queue no
`attendance_recalc_request`. Only policy *assignment* changes do. This was already listed as "not
done" in the shift remediation results.

**Impact.**
- Like AC-02: days past the sweep window keep the old bands, grace and overtime rules until close.
- Overtime decided under the old version stays frozen (AC-01).

**Recommended fix.** Queue a recalculation scoped to the policy's assignments, from the version's
`effective_from`.

### AC-08 — Web and mobile re-derive punch ownership (Medium, code-confirmed)

**Root cause.**
- `web/src/lib/attendance/day-detail.ts:40` (`punchesForDay`) and
  `mobile/lib/features/attendance/domain/day_timeline.dart:58` show a day's punches as "within six
  hours of the scheduled span".
- On a day with no span, they use the punch's **UTC** date.
- The backend owns punches up to `max_late_punch_minutes` (default 720) after shift end, and
  decides by IST date on no-shift days.

**Impact.** Display only; the backend stays authoritative, but HR sees misleading timelines while
correcting days:
- An OUT 7–12 hours after shift end is counted by the backend but missing from the timeline.
- A neighbouring day's punch within six hours is shown on this day.
- An off-day punch between 00:00 and 05:30 IST is shown on the previous day.

**Recommended fix.** Render the punches listed in `computation_snapshot.inputs.punch_ids` (already
returned), or add an explicit `owned_punch_ids` field.

### AC-09 — Calendar setup "past date" warning uses the UTC date (Low, code)

`calendar_setup.py:325` compares `effective_from` with `datetime.now(UTC).date()`. Between 00:00
and 05:30 IST it misses the warning for yesterday. The warning text only; no data effect. Use
`business_today(company.timezone)`.

---

## 7. Policy decisions required

### P-A — Overtime on a half-day weekly off

- **Decision:** On a half-day weekly off (e.g. alternate Saturday 0.50), attendance expects only
  the working half, but overtime is measured against the full shift. Working the full shift (E6b)
  earns no overtime and no comp-off.
- **Options:**
  - (a) overtime beyond the half-shift;
  - (b) keep the current rule;
  - (c) the off half earns comp-off only.
- **Affects:** engine, payroll, leave (comp-off).
- **Recommended:** (a), for consistency with how the day is paid.

### P-B — Late (or early) half-day plus overtime on the same day

- **Decision:** An arrival late enough for the HALF_DAY late band, followed by staying late, gives
  0.50 LOP **and** overtime (E1: late 80 minutes, out 21:00 → HALF_DAY + 90 OT).
- **Options:**
  - (a) overtime only after the scheduled minutes are made up — this is the current behaviour, and
    the half-day penalty stays;
  - (b) no overtime on a HALF_DAY/ABSENT-by-band day;
  - (c) late minutes are made up first, and only the remainder is overtime, with no half day.
- **Affects:** engine, payroll.
- **Recommended:** (b). It is easy to explain and avoids paying a penalty and a premium on the same
  day.

### P-C — What a correction does to a human-approved overtime decision (needed for AC-01)

- **Options:**
  - (a) reopen it as PENDING with the new minutes;
  - (b) keep the approval but cap it at the new detected minutes, and re-class it;
  - (c) keep it, and block period close until HR confirms.
- **Recommended:** (a) when minutes go up or the class changes; (b) when they only go down.

### P-D — Overtime when the shift is not overtime-eligible but work falls on a day off

- **Decision:** With `eligibility = SHIFT_FLAG` and a non-eligible shift, holiday or weekly-off work
  earns nothing extra: no overtime and no comp-off (E10c pattern). This is lawful for some staff
  categories but should be a deliberate choice.
- **Options:**
  - (a) keep it;
  - (b) day-off work always earns comp-off or overtime regardless of the shift flag.
- **Recommended:** confirm (a) with the owner, and say so on the policy screen.

### P-E — Leave balance on calendar changes (needed for AC-03)

- **Decision:** When a holiday is added inside approved leave, should the day be refunded
  automatically, or held for HR?
- **Recommended:** refund automatically, record the change in the leave history, and notify the
  employee.

P-01, P-04, P-05, P-07, P-10, P-11, P-12 and P-14 remain open from the shift audit.

---

## 8. Cross-module integration failures

| Pair | Failure | ID |
|---|---|---|
| Calendar ↔ Attendance | Stored days disagree with the calendar after any calendar edit until close | AC-02 |
| Calendar ↔ Leave | Leave days decided against an old calendar | AC-03 |
| Leave ↔ Attendance | Half-day leave: overtime basis and leave-half work | AC-05 |
| Attendance ↔ Overtime | Approved > detected; class on day ≠ class on record; overtime on INCOMPLETE days | AC-01, AC-04 |
| Overtime ↔ Payroll | Payroll prices by the day row's class and policy version, not the decided record's | AC-01 |
| Roster ↔ Overtime | Roster day off priced as a normal day | AC-06 |
| Policy ↔ Attendance | New policy versions not applied to computed days until close | AC-07 |
| Backend ↔ Web/Mobile | Different punch-to-day rule in the day timeline | AC-08 |
| Shift ↔ Attendance | No new failures: one resolver is used everywhere (fixed 15 Nov) | — |

---

## 9. Data integrity and recalculation risks

**Stale records.** AC-02 and AC-07: the only safety net is finalize. Any report, dashboard or
reminder read before close may be wrong. The recalc queue covers only existing rows; a missing row
is created by the sweep, a punch or `calculate-range`, and close blocks with
`EMPLOYEES_WITHOUT_ATTENDANCE` until it exists.

**Closed-period mutation.** No silent change found:
- Locked rows are never recalculated.
- Leave, overtime approval, punches and assignments refuse closed dates.
- Reopen is refused after payroll is finalised.
- A holiday *can* be added to a closed period's date. It has no effect until the period is
  reopened, and is then applied at the next close. Acceptable, but the calendar preview should
  name the closed period, as it does for protected payroll statuses.

**Plausible risks (not reproduced).**
- **Lock-order inversion between overtime approval and recalculation.** `OvertimeRecordService.approve`
  updates `overtime_record`, then `attendance_day` (`mark_ot_approved`). `_calculate` locks
  `attendance_day` `FOR UPDATE`, then updates `overtime_record`. Run concurrently on one day, they
  can deadlock. Postgres aborts one; no corruption, but one action fails with a 500 or a retry.
- **Re-ownership after a punch.** The immediate calculation after a punch covers the punch's date
  and its owner. A punch that moves *another* session to a different owner leaves the previous
  owner day stale until the sweep or close.
- **Best-effort immediate calculation.** When it fails for a back-dated on-behalf punch, nothing is
  queued; only close repairs it.
- **Weekly and monthly overtime caps.** They depend on sibling days. A change that frees budget
  does not recalculate later days, and combined with AC-01 the lower figure can become permanent.

**Idempotency and duplicates.**
- Day calculation is idempotent and race-safe: `FOR UPDATE`, and a savepoint on first insert.
- The queue is safe to run twice.
- Punch idempotency keys and duplicate collapse are in place.
- No duplicate overtime records: one per day; replacement only while `PENDING`.

---

## 10. Recommended remediation plan

**Phase 1 — Critical calculation correctness** (before payroll relies on these modules)
1. AC-01: decided overtime follows corrections. Re-derive AUTO decisions; reopen or cap human ones
   (P-C); cap approved at detected; class from the paid record; add a validation blocker.
2. AC-04: overtime on `INCOMPLETE` days is held and resolved at lock.
3. AC-05: half-day-leave overtime basis, and the leave-half work flag.

**Phase 2 — Cross-module resolution consistency**
4. AC-03: leave breakdown follows calendar and schedule changes (P-E, P-12), or at least blocks
   close.
5. AC-06: roster week-off overtime class.
6. Decide P-A and P-B, and implement them in the engine with an `ENGINE_VERSION` bump.

**Phase 3 — Recalculation and data integrity**
7. AC-02: queue recalculation from every calendar mutation, with population scoping.
8. AC-07: queue recalculation on policy version publish.
9. Make the overtime-approval lock order match calculation (lock the day row first).
10. Queue a recalc request when an immediate calculation fails, instead of relying on the sweep.

**Phase 4 — Policy gaps**
11. Close P-C, P-D, P-E and the carried-over P-01 … P-14.

**Phase 5 — Edge-case hardening**
12. Property test: for every computed day, `ot_minutes_approved ≤ ot_minutes_detected`, and
    `paid + lop + unpaid_off = 1.00` after lock.
13. Recalculate neighbour days whose owned punch set changed after a new punch.
14. Make the calendar preview name closed attendance periods.

**Phase 6 — Web/mobile UX consistency**
15. AC-08: timelines show the backend's owned punches.
16. AC-09: business date in the calendar-setup warning.

After Phases 1–3: bump `ENGINE_VERSION` and recalculate unlocked days of open periods
(`POST /attendance/days/calculate-range`). Decided overtime records also need a one-off review
query: `ot_minutes_approved > ot_minutes_detected`, or `ot_day_class` differing from
`overtime_record.day_class`.

---

## 11. Final answer

**Can Attendance, Holiday/Weekly-Off and Overtime together be trusted as an authoritative
calculation system for payroll? Not yet.**

What is already trustworthy:
- one schedule and one calendar answer per employee-date;
- deterministic punch ownership;
- the day result for a given set of inputs;
- period close: it recalculates, validates and locks, and fails closed;
- historical immutability after close;
- business dates in Asia/Kolkata.

What must be fixed before payroll relies on it:
1. **AC-01:** approved overtime must never exceed what the current punches support, and must be
   priced at the class and policy of the day as it now stands.
2. **AC-04:** a day resolved as absent at lock must not also pay overtime.
3. **AC-03:** leave must not be charged on holidays, and approved leave must not become loss of pay
   because a holiday moved.
4. **AC-05:** half-day-leave days must not lose overtime or pay leave time twice.

AC-02 and AC-07 do not corrupt a closed period, because finalize recalculates first. They should
still be fixed before go-live: until then, every screen and reminder before close can be wrong, and
every stale recompute feeds AC-01.

---

## Appendix A — how the probes were run

**Integration probes:** temporary test file next to `tests/integration/modules/attendance/`,
reusing `_build_wired_employee`, `_create_overtime_policy` and `_create_regularization_policy`.
Run with:

```
DATABASE_URL=…/hrms_test MIGRATIONS_DATABASE_URL=… HRMS_APP_DATABASE_URL=…/hrms_test
REDIS_URL=redis://localhost:6380/1 HRMS_TEST_CELERY_DB=14 FACE_PROVIDER_COMPARISON_ENABLED=false
.venv/bin/python -m pytest -s <probe file>
```

Removed after the run.

**Engine probe:** builds `AttendanceCalculationInput` directly. Setup: FIXED 09:00–18:00 IST with an
unpaid 13:00–14:00 window break; grace 10/10; hour bands ABSENT <240 / HALF_DAY 240–479 / PRESENT
≥480; late bands LATE 1–59 / HALF_DAY ≥60; overtime `ALWAYS`, no threshold, auto-approved. Results
quoted in sections 4–6 come from that run (scenarios B0, E1–E15).
