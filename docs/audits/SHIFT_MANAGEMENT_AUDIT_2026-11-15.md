# Shift Management Audit — 15 November 2026

Scope: shift masters and versions, breaks, employee shift assignment, rosters and swaps, and
everything downstream that reads a shift (punch acceptance, day calculation, overtime, leave,
period close). Backend, web and mobile were read. No code was changed.

**How findings were verified.** Every finding was traced in the code at commit `f4f81ae`
(engine version 12). Findings marked *probe* were also reproduced by running the pure
calculation engine (`calculation.evaluate_day`) with constructed inputs, applying the same
punch-load window the service applies. Nothing was run against a database, and the web and
mobile apps were read, not clicked through. Where a finding repeats an entry in
`POLICY_DECISION_MAP_2026-11-09.md`, the earlier ID is given; those entries are still open in
the code today.

---

## 1. Executive summary

**Answer to the audit question: not yet.** The system handles a fixed day shift with ordinary
hours correctly. It produces wrong attendance, and therefore wrong pay, in several situations
that real companies meet every week.

The design is sound: shift identity is separate from effective-dated versions, published
versions are immutable, every calculated day stores the version it used, closed periods are
locked, tenant isolation is enforced, and the engine is a pure function with good test
coverage. The defects are in specific rules, not the structure.

The six that matter most:

| # | Problem | Who is hit | Result |
|---|---|---|---|
| SH-01 | A checkout two hours or more after shift end is never read | Anyone doing long overtime | Day shows "missing punch", becomes loss of pay at period close, overtime lost |
| SH-03 | On a holiday the shift operates, a no-show is paid in full and a short day is loss of pay | 24x7 and retail shifts | Pay is backwards |
| SH-04 | Split shifts never earn overtime; a block after midnight is always "missed" | Split-shift staff | No overtime; half day for a full shift |
| SH-08 | An employee with no shift is absent or incomplete on Sundays and holidays | New joiners before a shift is assigned | Loss of pay on days off |
| SH-05 | A night worker's checkout does not update the day it belongs to until 09:30 | All overnight staff | "Missing checkout" shown for hours; needless correction requests |
| SH-06 | A shift version accepts any timezone, not only Asia/Kolkata | Any shift saved with another zone | Every day of that shift is attributed 5½ hours or more off |

Counts: 2 critical, 7 high, 9 medium, 4 low confirmed bugs; 14 open policy decisions; 8 future
risks.

Recommendation: fix Phase 1 (section 9) before the Attendance and Payroll audits, because
SH-01, SH-02 and SH-08 change which punches a day sees and would distort every result those
audits measure.

---

## 2. Current architecture

### 2.1 Data model

| Table | Purpose | Key rules |
|---|---|---|
| `shift` | Identity: name, auto code (`SHF-001`), active flag, `min_staff` | Legacy timing, break and grace columns exist but are always written as zero and never read |
| `shift_version` | Effective-dated schedule. `DRAFT` or `PUBLISHED` | One open draft per shift (unique index); published date ranges cannot overlap (GiST exclusion); published rows are immutable except `effective_to` |
| `shift_break` | Breaks of one version | Replaced in full on every draft save; frozen at publish |
| `shift_duty_block` | Working blocks of a SPLIT version | Sequence unique per version |
| `employee_assignment.shift_id` | The employee's default shift | Part of the effective-dated placement row; ranges cannot overlap (GiST exclusion) |
| `shift_roster` | Per-employee, per-date override: a shift, a day off, or "working this holiday" | One row per employee-date; only `PUBLISHED` rows count |
| `shift_swap_request` | Two employees exchange rostered shifts on one date | Approval rewrites both roster rows |
| `employee_break_override` | Per-employee break rules layered over the shift's | Dated |
| `attendance_day` | The calculated day | Stores `shift_id`, `shift_version_id`, scheduled start and end, policy version ids, engine version and a full snapshot |

There is no shift assignment by department, team or location, no rotation pattern, and no
default shift for a company or branch. A shift reaches an employee only through their own
assignment row or a roster row.

Grace, late and early bands, hour bands, half-day rules and the early punch-in limit live on
the **attendance policy**, not the shift. A policy can be assigned at SHIFT scope.

### 2.2 End-to-end flow

```
SHIFT CONFIGURATION            organisation/service.py
  create shift (name) + empty draft version
  edit draft: type FIXED | FLEXIBLE | SPLIT, times, breaks, flags, timezone, effective_from
  publish: validate → close previous version at effective_from − 1 → status PUBLISHED
        │
SHIFT ASSIGNMENT               employee/service.py · attendance/service.py (ShiftRosterService)
  default: employee_assignment.shift_id (new row closes the previous one)
  override: shift_roster row for one date, DRAFT → PUBLISHED
  swap: approved request exchanges two published roster rows
        │
WHICH SHIFT APPLIES ON DATE D  attendance/service.py::_build_calculation_input
  published roster row for D, else the assignment covering D, else none
  version = the published version whose date range covers D
  timezone = version > branch > company
        │
PUNCH                          attendance/service.py::PunchService.record_punch_outcome
  self-service: server clock; geofence; face check; early punch-in limit (shift window)
  on-behalf / manual / regularization: supplied time, not window-checked
  stored as an immutable row with no attendance date
        │
DAY CALCULATION                attendance/service.py::_calculate → calculation.py::evaluate_day
  triggers: each punch (punch's local date only) · break event · regularization approval ·
            leave sync · manual request · daily sweep 09:30 IST (today and 2 days back) ·
            HR range backfill · period close (every unlocked day of the period)
  load punches inside the day's window:
     FIXED / SPLIT  shift start − 2h … shift end + 2h
     FLEXIBLE       window start − 2h … window end + 12h
     no shift       local midnight … midnight
  pair IN/OUT → presence → breaks → worked minutes
  late = first IN − start − grace ; early = end − last OUT − grace
  status from hour bands, late/early bands, counters → overlays: off-day pay, on-duty, leave
        │
OVERTIME                       calculation.py::detect_overtime · service.py::_sync_overtime_record
  worked − scheduled, on the shift's start date; eligibility, minimum, rounding, caps
  overtime_record created PENDING or auto-approved
        │
PERIOD CLOSE → PAYROLL         AttendancePeriodService.finalize
  recalculate every unlocked day → validate → lock rows → period summary feeds payroll
```

### 2.3 Background jobs

| Job | When | What |
|---|---|---|
| `attendance.run_daily_calculation` | 09:30 IST daily | Recalculates today and the two days before, for every active employee |
| `attendance.run_incomplete_reminders` | 10:00 IST daily | Emails employees with unresolved incomplete days |
| `attendance.calculate_range` | On HR request | Backfills a date range |

Nothing recalculates a day when a shift version is published, a roster row is published,
changed or deleted, a swap is approved, or an assignment is changed. Those days change at
the next sweep (if within three days) or at period close.

---

## 3. Policy and decision map (what the code does today)

### Shift definition

| Rule | Behaviour | Where |
|---|---|---|
| Types | FIXED (start, end), FLEXIBLE (start window, required minutes, optional core hours), SPLIT (two or more duty blocks) | `ShiftVersion` |
| Start equals end | Rejected at publish (FIXED and each duty block) | `_validate_and_derive_for_publish` |
| Overnight | FIXED: end earlier than start. Derived by the server, never set by the client. FLEXIBLE cannot cross midnight | `_derive_cross_midnight` |
| Maximum length | None. 09:00–08:59 (23h 59m) publishes | — |
| Editing a published version | Not possible. A change is a new version with `effective_from` later than the current version's | `publish_shift_version` |
| Backdating a version | Allowed to any date after the current version's start, unless that date is in a closed period | `publish_shift_version` → `assert_date_open` |
| Deactivate | Blocked while active employees are assigned | `_assert_master_not_in_use` |
| Delete | Soft delete; blocked if the shift was ever assigned, rostered, used in a calculated day or a regularization request; needs typed name and reason | `delete_shift` |
| Who may manage | `ORG.SHIFT.MANAGE` for every shift route, including reads | `organisation/router.py` |

### Assignment and roster

| Rule | Behaviour |
|---|---|
| Precedence | Published roster row, else the assignment's shift |
| Assignment change | New row; `effective_from` must be after the current row's; previous row closed the day before |
| Clearing a shift | Not possible. A null `shift_id` means "keep the current shift" |
| Roster row | Blocked in a closed period; DRAFT rows are ignored by calculation; an unpublished row blocks period close |
| Roster day off | Day is not expected even if the calendar says working |
| Roster holiday-working | Treated like a shift that operates on that off day |
| Swap | Both need a published roster row with different shifts; colleague consents; a roster manager approves |

### Ownership and time

| Rule | Behaviour |
|---|---|
| Date that owns a shift | The shift's start date, including all hours after midnight |
| Overtime, holiday class, weekly and monthly caps, payroll period | All follow that same start date |
| Holiday or weekly-off test | Applied to the start date only |
| Timezone | Company is restricted to Asia/Kolkata; a shift version may override it |

### Grace, lateness, early departure

| Rule | Behaviour |
|---|---|
| Grace | Forgiven minutes: late = raw − grace. Grace 10, arrive 09:40 → 30 late *(probe)* |
| Boundary | Whole minutes. Grace 10: 09:10 on time, 09:11 one minute late *(probe)* |
| Scope | Daily. No monthly allowance. Arrivals inside grace are never counted |
| Repeated lateness | Every Nth late day in a calendar month becomes a half day, if configured |
| Grace and worked time | Grace does not add worked minutes; hour bands see the real minutes |
| Flexible | Late from the end of the start window; early departure effectively never detected |
| Split | Late and early never computed |

### Breaks and worked time

| Rule | Behaviour |
|---|---|
| Legacy break (no mode) | Only a punched gap counts, matched to a break by the gap's **start** time. Unmatched gap is unpaid |
| Break modes (AUTO_DEDUCT, MANDATORY_PUNCH, OPTIONAL_PUNCH) | Implemented in the engine; not reachable from web or mobile (SH-15) |
| Time before shift start | Not credited on a FIXED working day |
| Time after shift end | Credited in full, up to the two-hour load limit |

### Overtime

| Rule | Behaviour |
|---|---|
| Amount | Worked minus scheduled. Late arrival must be made up first |
| Before shift | Never (FIXED). After shift: automatic |
| Approval | Per overtime policy: pending or auto-approved |
| Off day the shift does not operate | Every worked minute is overtime; day stays paid |
| Off day the shift operates | Normal schedule applies; overtime only beyond it |
| Leave or on-duty day | No overtime |

---

## 4. Use-case coverage

PASS = behaves as a reasonable HR policy expects. FAIL = produces a wrong result.
PARTIAL = works within a limit stated in the row.

| Use case | Expected | Actual | Status |
|---|---|---|---|
| Fixed 09:00–17:00 or 09:00–18:00, punched on time | Present, scheduled minutes correct | As expected | PASS |
| Shift with no break | No deduction | As expected | PASS |
| One unpaid lunch, punched at the configured time | Lunch excluded | As expected | PASS |
| One unpaid lunch, not punched | Policy decision | Nothing deducted; an hour more worked time than a colleague who punches | PARTIAL (P-03) |
| Paid break taken 10 minutes early | Paid | Whole gap unpaid | FAIL (SH-10) |
| Paid break overrun (3h on a 60-minute break) | Excess not paid | All 3h paid | FAIL (SH-10) |
| Multiple breaks | Each matched | Works when each gap starts inside its window | PARTIAL |
| Very short shift (4h) with a company-wide 8h hour band | Present | Half day unless a separate policy is assigned to that shift | PARTIAL (P-05) |
| Long shift (12h) | Present | Works; no length limit | PASS |
| 23h 59m shift | Rejected or handled | Publishes; its load window overlaps the next day's | FAIL (SH-02, SH-21) |
| Overnight 22:00–06:00, 20:00–04:00, 23:00–07:00, on time | One day, owned by start date | As expected | PASS |
| Shift ending exactly at midnight (16:00–00:00) | 8h | As expected | PASS |
| Shift starting at midnight, punch-in 23:50 the day before | Counted | As expected | PASS |
| Overnight checkout | Day updates at once | Stale until the 09:30 sweep | FAIL (SH-05) |
| Overnight with 3h overtime (out 09:00) | 3h overtime | Checkout not read; day incomplete | FAIL (SH-01) |
| Night shift then day shift within 4 hours | Two clean days | Each day picks up the other's punch; both incomplete | FAIL (SH-02) |
| Overnight shift starting on a working day, ending on a holiday | Policy decision | Ordinary working day; no holiday treatment | PARTIAL (P-01) |
| Overnight shift starting on a holiday | Policy decision | All of it is holiday overtime | PARTIAL (P-01) |
| Half-day leave on a night shift | Other half judged alone | As expected | PASS |
| Employee with no shift, working day, no punch | Flagged | Incomplete or absent per policy | PASS |
| Employee with no shift, Sunday or holiday | Day off | Absent or incomplete | FAIL (SH-08) |
| Employee with no shift, one minute worked | Not a full day | Present, full day paid | FAIL (SH-08) |
| One permanent shift | Applied | As expected | PASS |
| Shift change from a future date | Old shift until then | As expected; past dates untouched | PASS |
| Second change dated before a pending future change | Allowed | Rejected: must be after the open row's start | FAIL (SH-13) |
| Backdated shift change | Controlled, recalculated | Accepted even into a closed period; no recalculation | FAIL (SH-13) |
| Removing an employee's shift | Possible | Not possible | FAIL (SH-13) |
| Overlapping or duplicate assignments | Rejected | Rejected by the database | PASS |
| Assigning a shift with no published schedule | Rejected | Accepted; days become "no shift" | FAIL (SH-13) |
| Shift deleted while assigned | Rejected | Rejected | PASS |
| Shift edited after use; last month's attendance | Unchanged | Unchanged for closed periods and for dates before the new version | PASS |
| Shift version backdated into an open past month | Warned and recalculated | Accepted silently; days change at close | PARTIAL (P-08) |
| Roster to a different shift for a day | That shift's rules apply | Times apply; a SHIFT-scoped policy still follows the default shift | FAIL (SH-07) |
| Arrive exactly at the grace limit | On time | On time | PASS |
| One minute past grace | Late | Late by one minute | PASS |
| Arrive 2h 15m early | Counted from shift start | Check-in not read; day incomplete | FAIL (SH-01) |
| Leave early beyond grace | Early departure | As expected | PASS |
| Duplicate punch within the window | Collapsed | As expected | PASS |
| Stray second IN within 30 minutes | Ignored | As expected | PASS |
| Stray OUT before the first IN | Ignored or flagged | Day incomplete though fully worked | PARTIAL |
| Forgot to punch out | Flagged | Incomplete; resolved at close | PASS |
| Work late 1h 59m | Overtime | Overtime | PASS |
| Arrive early | Policy decision | Never overtime | PARTIAL (P-04) |
| Work on a weekly off the shift does not operate | Overtime | All minutes overtime; day stays paid | PASS |
| No-show on a holiday the shift operates | Not paid as worked | Paid in full | FAIL (SH-03) |
| Two hours worked on a holiday the shift operates | Not worse than a no-show | Absent, loss of pay | FAIL (SH-03) |
| Split shift, both blocks same day | Present | Present; no late or early; no overtime ever | FAIL (SH-04) |
| Split shift with a block after midnight | Present | Block counted as missed | FAIL (SH-04) |
| Flexible shift with a 13:00–14:00 lunch | Publishable | Rejected: "break falls outside the shift's scheduled window" | FAIL (SH-11) |
| Flexible shift at night | Supported | Cannot be configured | PARTIAL (P-10) |
| Full-day leave, then punches | Leave stands, flagged | As expected | PASS |
| Leave approved or cancelled after calculation | Recalculated | Recalculated at once | PASS |
| Roster changed after leave was approved | Leave days re-checked | Not re-checked | PARTIAL (P-12) |
| Two admins publish the same shift | One wins | Second gets a stale-version error | PASS |
| Same punch sent twice | One punch | One punch (idempotency key, and duplicate collapse) | PASS |
| Sweep runs twice | Same result | Same result | PASS |
| Another company's shift id | Rejected | Rejected | PASS |

---

## 5. Bugs and issues (confirmed)

Each entry: what happens, why, how to reproduce, and the fix. "Trace" gives the path from the
client to the downstream effect.

### Critical

**SH-01 — Punches more than two hours outside the shift are never read** *(probe; earlier ATT-03, C-01)*

- **Trace:** any punch source → `PunchService.record_punch_outcome` stores the punch →
  `_build_calculation_input` (`attendance/service.py:5098`) loads only punches inside
  `window.load_start … load_end` → `calculation.punch_window_utc` (`calculation.py:421`,
  `lookback_hours=2`, `lookahead_hours=2`) → the lone IN is an orphan → INCOMPLETE → at period
  close `incomplete_at_lock_behaviour` decides, typically loss of pay.
- **Reproduce:** shift 09:00–18:00. IN 09:00, OUT 20:30. Result: 1 of 2 punches loaded,
  status INCOMPLETE, worked 0, overtime 0. OUT at 19:59 gives 119 minutes of overtime. Same
  for IN at 06:45, and for a 22:00–06:00 worker leaving at 09:00.
- **Why it is worse than it looks:** a regularization or HR manual punch entered at the true
  time (20:30) is outside the same window and is also ignored. The only way to fix the day is
  to enter a false time such as 19:59. The orphan-punch report lists these punches, but it is
  not a period-close check.
- **Expected:** the checkout is counted and the overtime detected.
- **Fix:** stop using a fixed pad. Extend each day's window forward to the start of the same
  employee's next shift window (bounded, for example 16 hours after shift end) and back to
  the previous shift's end. Add an orphan-punch check to period-close validation.

**SH-02 — One punch can be counted on two days** *(probe; earlier ATT-04, C-01)*

- **Trace:** same loading code. Day D's window and day D+1's window are computed
  independently and can overlap.
- **Reproduce:** D night shift 22:00–06:00 (window to 08:00 on D+1), D+1 day shift
  09:00–18:00 (window from 07:00). Punches: IN 22:00, OUT 07:30, IN 07:45, OUT 18:00. Day D
  loads the 07:45 IN as an orphan; day D+1 loads the 07:30 OUT as an orphan. Both days are
  INCOMPLETE, and D reports 90 minutes of overtime on a day flagged as missing a punch. Any
  shift of 20 hours or more overlaps its own next day.
- **Expected:** every punch belongs to exactly one day.
- **Fix:** same change as SH-01; make the windows of consecutive days meet without
  overlapping. `prior_day_window_end` already does this, but only when the later day has no
  shift.

### High

**SH-03 — On an off day the shift operates, a no-show is paid and a short day is loss of pay** *(probe)*

- **Trace:** `evaluate_day` sets `not_expected = True` for any HOLIDAY, WEEKLY_OFF or SHUTDOWN
  (`calculation.py:1719`) regardless of `operates_on_holiday`, `operates_on_weekly_off` or the
  roster's holiday-working flag. With no work, `_resolve_primary_status`
  (`calculation.py:2679`) returns NOT_EXPECTED, paid 1.00. With some work, the normal hour
  bands apply because `off_day_work` is false.
- **Reproduce:** shift 09:00–18:00 with `operates_on_holiday`, on a holiday. No punches →
  NOT_EXPECTED, paid 1.00. IN 09:00, OUT 11:00 → ABSENT, loss of pay 1.00. Full day → PRESENT,
  no overtime, no holiday classification.
- **Also:** Leave charges a full leave day for a rostered holiday-working date
  (`leave/service.py::_working_shares`), although attendance would have paid the absence
  anyway. The earlier decision map (C-04, D-05, X-11) says attendance marks these days
  absent; with no punches it does not.
- **Expected:** if the shift operates on the day, absence is absence; in no case should
  working part of a day pay less than not coming.
- **Fix:** when the shift operates (or the roster says holiday-working), treat the day as
  expected: `not_expected = day is off AND shift does not operate`. Then align Leave to the
  same test. Needs decision P-02 first.

**SH-04 — Split shifts: no overtime, and a block after midnight is always missed** *(probe)*

- **Trace (overtime):** `_validate_shift_version_type_fields`
  (`organisation/service.py:2844`) rejects `required_minutes` on a SPLIT version;
  `_evaluate_split` (`calculation.py:2549`) uses only `shift.required_minutes` as the
  schedule; `ShiftVersion.scheduled_minutes` is stored but never passed to the engine. So the
  schedule is always unknown, overtime is always 0 on a working day, and
  `attendance_day.scheduled_minutes` is null.
- **Trace (midnight):** `_evaluate_split` (`calculation.py:2498`) places every block's start
  on the attendance date. A block 01:00–04:00 that belongs to the night of D is placed at
  01:00 on D, before the first block.
- **Reproduce:** blocks 08:00–12:00 and 16:00–20:00; work 08:00–12:00 and 16:00–21:59 →
  overtime 0. Blocks 20:00–23:00 and 01:00–04:00, both worked → one block missed, HALF_DAY.
- **Fix:** derive scheduled minutes from the sum of the blocks; place a block on the next
  day when its start is earlier than the previous block's end; validate block order at
  publish.

**SH-05 — An overnight checkout does not update the day it belongs to**

- **Trace:** `_try_immediate_calculate` (`attendance/service.py:3497`) calculates only the
  punch's own local date. For a 22:00–06:00 shift on D, the 06:00 checkout triggers D+1, whose
  window starts at 20:00, so nothing changes; D still shows an open check-in.
- **Effect:** D is INCOMPLETE with a missing punch until the 09:30 sweep. If the checkout is
  after 09:30 (a 02:00–10:00 shift, or night overtime), it stays wrong until 09:30 the next
  day. The mobile "today" panel and HR dashboard show it; the 10:00 reminder job can email
  the employee.
- **Fix:** in the immediate hook, also calculate the previous local date when that date's
  window contains the punch.

**SH-06 — A shift version accepts any timezone**

- **Trace:** web shift form timezone picker / mobile setup → `ShiftVersionCreate.validate_timezone`
  → `validate_iana_timezone` (`shared/timezone.py:30`), which checks only that the zone
  exists. The company profile uses `validate_allowed_company_timezone`; the shift does not.
  `resolve_timezone` then prefers the shift's zone, so the whole schedule window moves.
- **Reproduce:** publish a version with `timezone: "UTC"`. A 09:00–18:00 shift is evaluated
  as 14:30–23:30 IST; an on-time employee is absent or 5½ hours "early".
- **Fix:** validate the shift version's zone against `allowed_company_timezones`, or remove
  the field from the forms while the product is India-only. Check existing rows.

**SH-07 — A policy assigned to a shift follows the default shift, not the rostered one** *(earlier SHF-08, C-10)*

- **Trace:** `CalendarResolutionService._scope_candidates` (`calendar_resolution.py:423`)
  uses `assignment.shift_id`. Attendance, overtime and regularization policies, the work
  calendar and the weekly-off pattern all resolve through it.
- **Effect:** a day worker rostered onto the night shift keeps the day shift's grace, bands
  and overtime rules for that night.
- **Fix:** pass the resolved shift of the date (roster first) into scope resolution.

**SH-08 — With no shift, days off are absent and one minute is a full day** *(probe; earlier ATT-17, C-08)*

- **Trace:** `evaluate_day` checks "no shift" (`calculation.py:1699`) before it looks at the
  calendar day type. No punches → ABSENT or INCOMPLETE per `missing_shift_behaviour`, even on
  a holiday or weekly off. With punches, `_evaluate_no_schedule` pays a full day for any
  worked minute and never detects overtime or holiday work.
- **Reproduce:** no shift, HOLIDAY, policy ABSENT → ABSENT, loss of pay 1.00. No shift,
  IN 09:00, OUT 09:01 → PRESENT, paid 1.00.
- **Who:** every employee whose assignment has no shift, whose shift has no published
  version for the date (SH-13), or whose roster row carries no shift.
- **Fix:** on a non-working calendar day with no punches return NOT_EXPECTED before the
  missing-shift branch. The worked-minute rule needs decision P-06.

**SH-09 — Leaving on the last working day's night shift: checkout refused**

- **Trace:** `_ensure_not_after_last_working_day` (`attendance/service.py`) compares the
  punch's local date with the last working day and rejects anything later once the
  employment is TERMINATED.
- **Reproduce:** last working day the 15th, shift 22:00–06:00. The 06:00 checkout on the
  16th is refused; the 15th stays INCOMPLETE and feeds final settlement.
- **Fix:** accept a punch on the following date when it falls inside the last working
  day's shift window.

### Medium

**SH-10 — Legacy breaks are matched by the gap's start time only** *(probe)*

- `match_breaks` (`calculation.py:768`). A paid 13:00–14:00 lunch taken 12:50–13:50 is fully
  unpaid (worked 480, not 540). A paid lunch stretched to 13:00–16:00 is fully paid; it is
  only flagged as excess.
- Fix: match on overlap, pay up to the break's maximum, treat the rest as unpaid or by the
  excess rule.

**SH-11 — A flexible shift cannot have a fixed lunch break**

- `_validate_breaks_boundaries_for_publish` (`organisation/service.py:2814`) checks a fixed
  break against the flexible shift's *start window* (for example 08:00–11:00), not the
  working day. The form offers the break type; publish fails.
- Fix: for FLEXIBLE, check against window start to window end plus required minutes, or skip
  the containment check.

**SH-12 — An automatic lunch deduction stacks on a punched lunch** *(probe)*

- `compute_breaks`. AUTO_DEDUCT 13:00–14:00, employee punches out 12:30–13:30: the punched
  hour is excluded and a further 30 minutes are deducted for the part of the window they
  were back at work. 90 minutes lost for a 60-minute lunch; 450 worked; HALF_DAY.
- Latent today because no client can set a break mode (SH-15). Fix before exposing modes:
  let a punched gap near the window satisfy the rule.

**SH-13 — Employee shift assignment gaps**

- `EmployeeAssignmentService.create_assignment` (`employee/service.py:1976`):
  - No closed-period check. A change dated inside a closed month is accepted; locked days
    keep the old shift while the history says otherwise.
  - No recalculation of days already calculated between the effective date and today.
  - `effective_from` must be after the open row's start (`:2056`), so once a future-dated
    change exists no earlier change can be made.
  - `shift_id` null means "no change" (`:2082`; web sends `shift_id: values.shiftId || null`),
    so a shift can never be removed.
  - `_assert_shift_ownership` (`:1867`) checks only that the shift exists and is active. A
    shift with no published version, or one starting in the future, is accepted. The web
    shift page says such a shift "cannot be assigned to employees until a draft is
    published"; the API does not enforce it, and the assignment form lists every shift.

**SH-14 — Dormant settings are accepted and stored** *(earlier ATT-15, C-07)*

- Still without effect: `punch_rounding` and `rounding_minutes` (*probe*: DOWN-15 at 09:11
  still gives 11 late), `missing_punch_behaviour = AUTO_CLOSE` (*probe*: nothing is closed),
  `half_day_split`, `half_day_boundary_minutes`, `early_out_uses_core_end`,
  `ShiftVersion.weekly_off_pattern_id`, `scheduled_minutes`, `min_scheduled_minutes`,
  `max_scheduled_minutes`, and the legacy columns on `shift`.
- The web shift form loads weekly-off patterns and saves the chosen one on the shift
  version. It changes nothing; weekly offs come from the work calendar and WEEKLY_OFF policy
  assignments.

**SH-15 — Break modes and break punching cannot be used from the product**

- `breakFormValueToPayload` (`web/src/lib/shift/validate-shift-version.ts`) and the mobile
  shift setup never send `mode`, so every break created in the product is a legacy break.
  No web or mobile screen calls `/attendance/breaks/me/start` or `/end`.
- Because breaks are replaced in full on each save, editing a shift in the web form would
  reset any mode set through the API.

**SH-16 — Employee and planner views disagree with calculation**

- `MyWorkProfileService` (`organisation/my_work_profile.py:78`) shows the assignment's
  shift and ignores today's roster row, so a rostered employee sees the wrong shift.
- `weekly_schedule` (`attendance/schedule_service.py`) counts only roster rows, so staff on
  their default shift are missing from coverage; timings are taken as of the week's first
  day; flexible and split shifts show no hours.

**SH-17 — Dates that do not use Asia/Kolkata**

- `PunchRepository.page_filtered`: `date_from` and `date_to` are UTC days. A punch at 01:00
  IST on the 10th is listed under the 9th. Mobile works around it; any other caller is off
  for punches between 00:00 and 05:30.
- `date.today()` (server date) in `schedule_service.py:568` (a swap for "yesterday" is
  accepted between 00:00 and 05:30 IST if the server runs in UTC), `schedule_router.py:56`,
  `regularization_decision_center.py:134`; `datetime.now(UTC).date()` in
  `break_override_service.py:227`.
- Mobile `outside_shift_window.dart`, `punch_warning.dart` and `face_punch_card.dart` use
  the device's zone (`toLocal()`), not the company's.

**SH-18 — Roster and swap changes are not validated against the day**

- A roster row can name an inactive shift or one with no published version for that date
  (`_ensure_shift_in_company` checks existence only); the day then calculates as "no shift".
- HR can create a swap for a past date; a pending swap never expires; approving it after
  the date rewrites past roster rows without recalculating either day.
- `decide` updates both roster rows without a version check, so a concurrent roster edit can
  be overwritten.

### Low

**SH-19 — Listing shifts needs the manage permission.** Roster, assignment and attendance
detail screens call `GET /shifts`, which requires `ORG.SHIFT.MANAGE`. A roster manager
without it gets an empty shift list (the error is swallowed).

**SH-20 — Swap reference race.** `SW-{200 + count + 1}` is computed from a row count; two
simultaneous requests collide on the unique index and one fails with a server error.

**SH-21 — Missing validation.** Duplicate shift names are allowed. `required_minutes` may be
0 or unbounded. `effective_from` has no bounds. Total break time may exceed the shift. A
flexible-duration break window cannot cross midnight. Split blocks need not be in time order.
There is no minimum or maximum shift length.

**SH-22 — Shift page copy.** The shifts list describes "timings, breaks, and grace periods";
grace is set on the attendance policy.

---

## 6. Missing business rules

### 6.1 Confirmed bugs

Listed in section 5: SH-01 to SH-22.

### 6.2 Policy decisions needed

These are not defects. The code makes a choice that nobody appears to have signed off, or
that conflicts with common practice. Each needs an owner's answer.

| ID | Question | Today |
|---|---|---|
| P-01 | Overnight shift crossing into or out of a holiday or weekly off: which date decides? | The start date decides everything |
| P-02 | What does "operates on holiday / weekly off" mean: is attendance required, and is the work paid extra? | No-show is paid; full day is ordinary pay with no holiday class (SH-03) |
| P-03 | Should an unpunched unpaid lunch be deducted automatically? | No, unless a break mode is set, which the product cannot do |
| P-04 | Is early arrival ever overtime? | Never on fixed shifts |
| P-05 | Hour bands for short and long shifts: fixed minutes or a share of the shift? | Fixed minutes on the attendance policy |
| P-06 | Pay for punches on a day with no shift | Any worked minute pays a full day |
| P-07 | Grace: threshold or forgiven minutes; daily only or a monthly allowance; should grace protect the hour band? | Forgiven minutes; daily; no (earlier C-02, C-12) |
| P-08 | May a shift version or assignment be backdated into an open past month, and should HR see the impact first? | Allowed silently; days change at period close |
| P-09 | Should shift, roster, swap and assignment changes recalculate affected days at once? | No; next sweep (3 days) or period close (earlier R-09 covers shift versions only) |
| P-10 | Flexible shifts at night, and early departure on flexible shifts | Not supported; never detected (earlier C-11) |
| P-11 | Split shifts: late, early, partly worked blocks | Not computed; any overlap counts as worked |
| P-12 | Roster changed after leave was approved, or a swap on a leave day | Not checked |
| P-13 | Maximum hours after shift end that still belong to the shift | Two hours, hardcoded (SH-01) |
| P-14 | Two shifts in one day, or a mid-day shift change | Not supported (earlier PD-SHIFT-1) |

### 6.3 Future risks

| ID | Risk |
|---|---|
| R-01 | No shift assignment by department, branch or team and no bulk assignment: each employee is set one at a time, which invites SH-08 for new joiners |
| R-02 | No rotation patterns: rotating crews need one roster row per employee per day |
| R-03 | The weekly schedule loads every pending swap of the company, and the swap list runs several queries per request row; both grow with volume |
| R-04 | Daylight saving: `_local_to_utc` uses plain `datetime.combine`; a non-existent or repeated local time is not handled. Irrelevant for India, relevant if SH-06 is left open or the product expands |
| R-05 | A shift may be assigned or rostered with no check that the employee's attendance policy, calendar and overtime policy resolve for that date; the gap appears only as CONFIG_ERROR at calculation |
| R-06 | Period-close recalculation runs every unlocked day in one transaction; long for a large company |
| R-07 | Self-service punch order rule looks back 18 hours: a night worker who forgot to check out at 06:00 cannot check in at 22:00 (earlier ATT-09) |
| R-08 | Mobile has no offline punch queue (none found in `lib/`); a punch attempted without network fails and must be repeated, and the server clock is the only clock |

---

## 7. Edge cases

| Scenario | Handled? | Note |
|---|---|---|
| Punch exactly at midnight | Yes | Half-open windows; no double count on shifts that end or start at 00:00 |
| Month or year boundary on an overnight shift | Yes | Whole shift belongs to the start date and its period |
| Overnight punch when the previous month is closed | Yes | Punch accepted if either the local date or the day before is open |
| Works 24 hours or more | No | Checkout outside the window; day incomplete (SH-01) |
| Device clock wrong | Yes | Self-service uses the server clock |
| Punch arrives late (network) | Partly | Recorded at arrival time, not at the tap; no offline queue |
| Duplicate request or retry | Yes | Idempotency key; duplicate collapse; minimum gap of 120 seconds |
| Same idempotency key from another employee | Yes | Refused |
| Shift version published after an employee punched in today | Partly | Today is recalculated with the new version at the next trigger; no warning |
| Shift deactivated while rostered in the future | No | Roster rows keep using it |
| Employee changes branch | Yes | Branch timezone and policies resolve by date |
| Two assignments at once | Yes | Blocked by the database |
| Draft roster left unpublished | Yes | Blocks period close |
| Roster day off with punches, shift present | Yes | All overtime |
| Roster day off with punches, no shift on the row | No | Present, full pay, no overtime *(probe)* |
| Leave on a rostered day off | Yes | No leave consumed |
| Stray OUT before the first IN | Partly | Day incomplete even though fully worked *(probe)* |
| Forgotten checkout, policy ABSENT | Partly | Marked absent while the shift is still running *(probe)*; the overview hides it for today |
| Unresolvable timezone on an old row | Yes | Day becomes CONFIG_ERROR instead of failing |
| Sweep and punch calculate the same day together | Yes | Row lock, savepoint retry |
| Two admins editing one draft | Yes | Version check |
| Cross-company shift id on roster or assignment | Yes | Company-scoped lookup before the write |

---

## 8. Downstream impact

| Issue | Attendance | Leave | Overtime | Payroll | Employee | HR |
|---|---|---|---|---|---|---|
| SH-01 | Worked days become incomplete | — | Long overtime lost entirely | Loss of pay for worked days | Sees "missing punch" after a 12-hour day | Must enter a false time to correct |
| SH-02 | Two days incomplete | — | Overtime on a flagged day | Both days at risk of loss of pay | Confusing | Manual correction of both days |
| SH-03 | No-show counted as day off; short day absent | Leave charged for a day that costs nothing | No holiday overtime on operating shifts | Pays absence, docks attendance | Unfair outcome | Cannot explain the result |
| SH-04 | Half day for a full split shift | — | None for split staff | Underpaid | Underpaid | — |
| SH-05 | Stale for hours | — | Overtime record delayed | None once swept | "Missing checkout", reminder email | Needless regularization requests |
| SH-06 | Every day wrong | Half-day halves misplaced | Wrong | Wrong | — | Hard to diagnose |
| SH-07 | Wrong grace and bands on rostered days | Wrong weekly offs if scoped by shift | Wrong overtime policy | Indirect | — | — |
| SH-08 | Absent on days off | — | No overtime | Loss of pay, or a full day for one minute | — | New joiners need a shift before day one |
| SH-09 | Final day incomplete | — | Lost | Final settlement short | — | Manual fix |
| SH-10 to SH-12 | Worked minutes off by a break | — | Threshold shifts | Half day or overpaid break | — | — |
| SH-13 | History and locked days disagree | — | — | Audit exposure | — | Cannot remove a shift |
| SH-14, SH-15 | Configured rule does nothing | — | — | Indirect | — | False confidence in settings |
| SH-16 | — | — | — | — | Sees the wrong shift | Coverage figures wrong |
| SH-17 | Punch lists off by a day at night | — | — | — | Wrong times on a device in another zone | — |

---

## 9. Recommended implementation plan

### Phase 1 — Critical correctness

1. SH-01, SH-02: replace the fixed two-hour pad with windows bounded by the neighbouring
   shifts; one punch, one day. Add orphan punches to period-close validation. Decide P-13.
2. SH-08: a non-working day with no shift and no punches is NOT_EXPECTED.
3. SH-03: make "shift operates on this off day" mean attendance is expected (after P-02).
4. SH-06: restrict the shift version timezone to the allowed list; check existing rows.
5. SH-05: recalculate the previous date when a punch falls inside its window.
6. SH-04: split-shift scheduled minutes and after-midnight blocks.

Each of these changes engine output, so bump `ENGINE_VERSION` and backfill open periods.

### Phase 2 — Policy gaps

7. Get decisions P-01 to P-14 signed; P-02, P-06 and P-07 block Phase 1 items or payroll.
8. SH-07: resolve SHIFT-scoped policies from the rostered shift.
9. SH-09: allow the last night shift's checkout.
10. SH-10, SH-11, SH-12: break matching by overlap; flexible-shift break validation; no
    stacking of automatic and punched breaks.

### Phase 3 — Data integrity

11. SH-13: closed-period guard on assignment changes; allow clearing a shift; require a
    published version covering the effective date; allow a change before a pending future
    row.
12. SH-18: validate roster and swap rows against the shift's published version and the
    date; version check in swap approval.
13. P-09: recalculate affected open days when a shift version, roster row, swap or
    assignment changes, or queue it.
14. SH-14: remove or implement each dormant setting; hide them in both clients meanwhile.

### Phase 4 — Edge-case hardening

15. SH-17: IST dates in the punch list, swaps and schedule routes; company zone in mobile.
16. SH-21: shift length limits, break totals, duplicate names, block order.
17. SH-20: swap reference from a sequence.
18. R-07: revisit the 18-hour punch-order rule for night workers.

### Phase 5 — UX and operations

19. SH-15: expose break modes and break punching, or remove them from the API surface.
20. SH-16: "my shift" from the roster; coverage that includes default-shift staff.
21. SH-19: a read-only shift list for roster managers.
22. R-01, R-02: bulk and scope-based shift assignment; rotation patterns.
23. An impact preview before publishing a backdated shift version (P-08).
