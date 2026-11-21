# Attendance module: complete audit report

19 November 2026. Read-only audit. No source code, configuration, schema, migration or data was changed.
The only files written are the five documents in this folder.

Companion documents in this folder:
`ATTENDANCE_AUDIT_EXECUTIVE_SUMMARY.md`, `ATTENDANCE_UI_UX_IMPROVEMENT_PLAN.md`,
`ATTENDANCE_IMPLEMENTATION_ROADMAP.md`, `ATTENDANCE_TEST_SCENARIO_MATRIX.md`.

---

## 0. Repository state and method

| Item | Value |
|---|---|
| Repository | `/media/varun/varun27/work/staff-spectrum/HRMS` (monorepo: `apps/api` FastAPI + SQLAlchemy + Celery, `apps/web` Next.js, `apps/mobile` Flutter) |
| Branch | `test`, head `977a5eb` |
| Engine | `ENGINE_VERSION = 16` (`apps/api/src/hrms/modules/attendance/calculation.py:99`). Last engine-area commit `3616272` (17 Nov). |
| Uncommitted work found (not mine, left alone) | `apps/mobile/lib/features/attendance/domain/hr_calendar.dart`, `presentation/attendance_calendar_screen.dart`, `test/attendance_calendar_test.dart` and four golden PNGs: a "needs a look first" sort for the mobile HR calendar list. Six untracked docs in `docs/audits/` dated 18–19 Nov. Another session is probably working on these. |

**How the audit was done.** I read the code paths that produce, aggregate and display a result, from
`calculation.py` to the web and mobile screens. Every finding below says how it was established:

- **CODE-CONFIRMED**: follows directly from the code I read; the line is cited. Not run.
- **NEEDS-RUNTIME**: the code strongly suggests it, but data or configuration could change the outcome.
- **CARRIED**: reproduced by an earlier audit (named), and the code it depends on has not changed since.

**What I did not do.** I did not run the apps, the tests or any database query. Flutter is not installed
on this machine. The engine's rule-level behaviour was audited in depth on 16 Nov
(`MASTER_ATTENDANCE_SYSTEM_AUDIT_2026-11-16.md`, `ATTENDANCE_REMAINING_ISSUES_AND_RISKS.md`,
`ATTENDANCE_POLICY_DECISION_REGISTER.md`, 17 owner decisions in
`ATTENDANCE_DECISION_SHEET_GROUP_A_2026-11-18.md`). I did not repeat that work; I link to it. This report
concentrates on what that work did not cover: **how a stored result becomes the number or word a person
sees, and whether every screen tells the same story.**

---

## 1. Architecture map

### 1.1 Lifecycle of one result

```
Punch (WEB / MOBILE / FACE / DEVICE / ADMIN / REGULARIZATION synthetic punch)
  -> PunchService (service.py)  geofence_service.py, face_verification.py, punch_ownership.py
  -> _try_immediate_calculate (service.py:3500)   on every punch, best effort
  -> AttendanceCalculationService.calculate (service.py:4113)
        resolves by date: shift version, roster, work calendar, attendance / OT / regularization
        policy versions (resolution.py, work_schedule.py, shift_window.py), leave projections
  -> calculation.calculate()  pure, in memory (calculation.py)  -> one AttendanceDay row, full replace
        + computation_snapshot (JSONB), + OvertimeRecord
  -> Celery: attendance.run_daily_calculation 09:30 Asia/Kolkata, today + 2 trailing days (tasks.py)
             attendance.run_recalc_requests every 5 min (recalc.py, AttendanceRecalcRequest queue)
             attendance.run_incomplete_reminders 10:00
  -> Reads:
        GET /attendance/days, /attendance/days/{id}      raw rows       -> day pages, calendars, lists
        GET /attendance/summary (summary.py)             aggregate A    -> web Attendance page, mobile Insights
        GET /dashboards/company/attendance-overview      aggregate B    -> web company home dashboard
              (overview.py)
        GET /attendance-periods/{id}/summary             aggregate C    -> Payroll (frozen at finalize)
              (service.py ~8040-8260, AttendancePeriodSummary)
  -> Client-side re-aggregation:
        web  lib/attendance/dashboard.ts  bucketOf, summarizeMonth, presenceOf
        web  lib/attendance/hr-calendar.ts buildHrCalendar
        mobile presentation/attendance_summary.dart attendanceBucketOf, domain/*.dart
  -> Payroll: payroll/engine.py reads paid_days, lop_days, ot_minutes_* from AttendancePeriodSummary
```

### 1.2 Components

| Component | Path | Responsibility | Inputs → outputs | Consumers |
|---|---|---|---|---|
| Model | `attendance/models.py:862` `AttendanceDay` | One row per employee per attendance date; status, minutes, flags, pay fractions, OT, snapshot, lock | written only by `calculate()` | everything below |
| Engine | `attendance/calculation.py` (3,716 lines) | Pairing, breaks, hour/late/early bands, status precedence, leave overlay, OT, pay fractions | `AttendanceCalculationInput` → `AttendanceCalculationResult` + snapshot | `service.py` |
| Orchestration | `attendance/service.py` (9,054 lines) | Punch intake, calculate, recompute, periods, finalize/lock, period summary, regularization apply | DB → rows | routers, tasks |
| Recalc queue | `attendance/recalc.py` | Stale-day requests from shift / roster / policy / calendar edits | change events → recalc | beat every 5 min |
| Scheduled sweep | `attendance/tasks.py`, `core/celery_app.py:105` | Daily 09:30 IST calc of today and two prior days; reminders 10:00 | — | creates "today" rows for non-punchers |
| Summary aggregate A | `attendance/summary.py` | Window totals, rate, punctuality, weekday, department/branch | rows → `AttendanceSummaryRead` | web `/app/attendance`, mobile Insights |
| Overview aggregate B | `attendance/overview.py` | One-date company overview, time-aware | rows + clock → `AttendanceOverviewRead` | web company dashboard (`lib/dashboard/overview.ts`) |
| Period summary C | `service.py` ~8040–8260 → `AttendancePeriodSummary` | Fraction-based paid / LOP / leave / OT per employee per period | locked rows → frozen summary | `payroll/engine.py` |
| Day read schema | `attendance/schemas.py:1707` `AttendanceDayRead` | Exposes every row column incl. raw `computation_snapshot` | — | web + mobile |
| Web day page | `apps/web/src/app/app/attendance/[id]/page.tsx`, `components/attendance/day/*`, `lib/attendance/day-detail.ts` | Day summary, timeline, time summary, breaks, leave overlay, "Calculation details" | `AttendanceDay` | employee, manager, HR |
| Web dashboard | `app/app/attendance/page.tsx`, `components/attendance/dashboard/*`, `lib/attendance/{dashboard,summary,insights,mismatch}.ts` | Today / Trends / Reports, self view, month view | summary + days | HR, employees |
| Web calendars | `components/attendance/dashboard/month-calendar.tsx`, `app/app/attendance/calendar/page.tsx`, `lib/attendance/hr-calendar.ts` | Employee month grid; HR employee × day grid | days | |
| Mobile | `apps/mobile/lib/features/attendance/` (≈90 files) | Self screen, day detail, my calendar, HR calendar, team list, insights, reports, mismatches, punch (face, GPS) | days, summary | |

### 1.3 Where the same thing is decided more than once

| Decision | Places it is made | Do they agree? |
|---|---|---|
| Status → bucket | `summary.py:121` `_bucket_expr`; `overview.py:89` `bucket`; web `dashboard.ts:284` `bucketOf`; mobile `attendance_summary.dart:22` `attendanceBucketOf` | **No** (AUD-01) |
| Is the day "present"? | summary: PRESENT/REMOTE/ON_DUTY; overview: PRESENT + HALF_DAY (+ open punch in progress); HR calendar: HALF_DAY = 0.5; period summary: fractions | **No** (AUD-02, AUD-09) |
| Is it an exception? | `overview.py:113`; `summary.py:173`; web `day-detail.ts` `exceptionLabels` and `dashboard.ts` `hasException`; mobile `attendance_mismatch.dart` | **No** (AUD-10) |
| Is today still in progress? | `overview.py:84-101` (uses `scheduled_end` and the clock); mobile day detail `attendance_day_detail_screen.dart:407`; **not** summary, **not** web self view / day page | **No** (AUD-03) |
| Status label | web `types.ts:190` (status words) and `dashboard.ts:237` (bucket words); mobile `status_map.dart` / `dayBucketLabels` | **No** (AUD-11) |

---

## 2. Calculation engine

The engine's rules were audited scenario by scenario on 16 Nov. Its open defects are **CARRIED** here
because the engine has not changed since (`3616272`, 17 Nov, a punch-lock fix). The ones that change
what employees are paid, from `ATTENDANCE_REMAINING_ISSUES_AND_RISKS.md`:

| ID (prior) | In one line | Waiting on |
|---|---|---|
| MA-01 | Hour bands with a gap: uncovered minutes count `PRESENT`, full pay | decision H-01 |
| MA-02 | Under `TREAT_PRESENT` a no-show is paid in full at lock | H-02 |
| MA-03 | Comp-off credit does not follow overtime corrections | H-03 |
| MA-04 | Shift-scoped calendar/policy does not resolve on a roster week-off → `CONFIG_ERROR` | H-04 |
| MA-05 | Part-time shifts judged by full-day bands → `HALF_DAY` for full attendance | P-05 |
| MA-06 | Punch accepted after close, owned by a locked day, counted nowhere | fix |
| MA-07 | Schedule change recalculates only its own date; neighbour keeps punches it no longer owns | fix |
| MA-09, MA-13, MA-20, H-29 | Grace / mark ceiling / pre-shift work / late in half-day leave | D-01a, H-05, P-04, H-29 |
| MA-10 | Pay-basis and legal-entity edits queue no recalc | fix |

What this audit adds about the engine, all **CODE-CONFIRMED**:

- **Status precedence** (`calculation.py:3655-3690`, docstring §19.4): population (NOT_JOINED / EXITED) →
  NOT_EXPECTED → CONFIG_ERROR → punch tier (missing punch → `INCOMPLETE`, or `ABSENT` if policy
  `missing_punch_behaviour = ABSENT`, or band status if `AUTO_CLOSE`) → hour band → late / early / core-hours /
  cumulative overrides to `HALF_DAY` → leave overlay → ON_DUTY overlay. One status per day; everything else is
  a flag (`is_late`, `is_early_out`, `missing_punch`, `is_overtime`, `is_regularized`, `is_pending_approval`,
  `worked_on_holiday`, `work_on_leave_flagged`, `is_core_hours_breach`, `on_duty`). **Status and flags coexist
  by design**; the screens must show both (see AUD-12).
- **The engine has no clock.** An open check-in today is `missing_punch = true` and therefore `INCOMPLETE`
  (or `ABSENT`). Only `overview.py` and the mobile day screen correct for this. See AUD-03.
- **`WFH` is never produced.** `calculation.py:3657`: "WFH remains a no-op". Yet `WFH` is an accepted
  regularization type (`schemas.py:117`) and a status the clients label. See AUD-13.
- **The snapshot explains the result, but nobody reads it.** `computation_snapshot` records `inputs`,
  `derived_inputs`, `pairing`, `presence`, `breaks`, `grace_band_credit`, `hour_band_gap`, `terminal_reason`,
  `half_day_leave`, `split_missed_blocks`, `roster_week_off_overtime` (`calculation.py:1600-3570`). The only
  client use is `inputs.punch_ids` (web `day-detail.ts:38`, mobile `day_timeline.dart:55`); otherwise it is
  shown as raw JSON. See AUD-06.

**Time zone.** Remediated in October (`ATTENDANCE_TIMEZONE_IMPLEMENTATION_COMPLETION_REPORT.md`). The
engine and summaries use the row's own `timezone` and `business_today()`. Remaining notes: the Celery beat is
fixed to `Asia/Kolkata` for every company (`celery_app.py:105`, fine for India-only, wrong local hour for any
other tenant), and some mobile date pickers fall back to device `DateTime.now()` (`rosters_screen.dart:120`,
`team_attendance_screen.dart:160`); low risk because they are only initial picker values.

---

## 3. Findings

Severity is about the effect on people and pay. "Type" uses the categories in the brief.

### AUD-01: the two dashboard aggregates count the same day differently
- **Severity:** High. **Type:** Architectural weakness, confirmed inconsistency. **CODE-CONFIRMED.**
- **Where:** `attendance/summary.py:121-136` (`_bucket_expr`), `:173-184` (exception), `:524` (not checked in);
  `attendance/overview.py:89-120`.
- **Current:** for the same date and population:

  | Day | Overview (home dashboard) | Summary (Attendance page) |
  |---|---|---|
  | `HALF_DAY` | Present | Half day, **not** in the rate's numerator |
  | Today, open check-in, shift running | Present | Incomplete |
  | Today, no punch, shift not ended | Not checked in | Incomplete (and Not checked in) |
  | `CONFIG_ERROR` | Incomplete | Config error |
  | Exception | missing punch, pending approval, INCOMPLETE or CONFIG_ERROR status, unresolved or excess break, submitted regularization | missing punch, CONFIG_ERROR, pending approval, unresolved work-on-leave |
  | Employee with no row, past date | No record | not counted at all (AUD-08) |

- **Expected:** one definition, used by every surface.
- **Impact:** HR sees "Present 18" on the home dashboard and "Present 15, Half day 3, Incomplete 4" on the
  Attendance page for the same morning. Trust in every number drops.
- **Fix:** one bucket and exception definition in the backend, used by both endpoints (R-B01).

### AUD-02: a half day counts as zero in the attendance rate
- **Severity:** High. **Type:** Confirmed inconsistency; rule unclear. **CODE-CONFIRMED.**
- **Where:** `summary.py:77` `WORKING_BUCKETS = {PRESENT, REMOTE, ON_DUTY}`; rate at `:343`, `:491`.
- **Current:** a `HALF_DAY` is expected (denominator) and not working (numerator): weight 0. The HR calendar
  gives it 0.5 (`hr-calendar.ts:71`), the overview 1 (`overview.py:36`), the payroll summary its
  `paid_day_fraction`.
- **Decision needed:** what a half day is worth in the attendance rate (0.5 is the usual choice).
- **Impact:** departments with many half days look worse than they are; the rate disagrees with the calendar
  next to it.

### AUD-03: a person who is working is shown as "Incomplete" or "Absent"
- **Severity:** High. **Type:** Confirmed UX problem, presentation defect. **CODE-CONFIRMED** (wording depends on policy).
- **Where:** engine `calculation.py:3671-3683`; web `components/attendance/dashboard/self-view.tsx`
  (status badge next to `PRESENCE_LABELS`), `components/attendance/day/day-summary.tsx`; summary `summary.py:121`.
  Mobile handles it: `attendance_day_detail_screen.dart:405-410` ("Today's ABSENT/INCOMPLETE row is the 09:30
  sweep's placeholder, not a verdict").
- **Reproduce:** employee punches in at 09:10, opens web Attendance at 11:00. Badge: "Incomplete"
  (or "Absent" if the policy's missing-punch behaviour is `ABSENT`), next to "Working · In for 1 h 50 m".
- **Expected:** "Working since 09:10" with no verdict until the shift has ended.
- **Impact:** employees think they have been marked absent and raise corrections or call HR; the Attendance
  page's Incomplete tile is inflated every morning.

### AUD-04: holidays are described as weekly offs on the web day page
- **Severity:** Medium. **Type:** Confirmed bug (presentation). **CODE-CONFIRMED.**
- **Where:** `apps/web/src/lib/attendance/day-detail.ts` `summarizeDay`: the branch
  `attendance_status === "NOT_EXPECTED" || calendar_day_type === "WEEKLY_OFF"` runs before the `HOLIDAY` branch.
- **Reproduce:** any holiday with no punches (status `NOT_EXPECTED`, `calendar_day_type = HOLIDAY`). The
  headline reads "Weekly off — no work expected." The holiday name never shows. The same happens for any other
  non-working day type.
- **Fix:** test `calendar_day_type` first (HOLIDAY → name; WEEKLY_OFF; other → "Not a working day").

### AUD-05: web shows two different "worked" figures for an open day
- **Severity:** Medium. **Type:** Confirmed UX problem. **CODE-CONFIRMED.**
- **Where:** `self-view.tsx` "Worked today" tile = `worked_minutes` (last calculation, usually 0 for an open
  pair) beside "In for X since check-in" (client clock). `day-summary.tsx` "Worked" tile likewise. Mobile shows
  "—" for an open day (`attendance_day_detail_screen.dart:412`).
- **Expected:** one live figure ("3 h 20 m so far, 4 h 40 m left in shift") for an open day.

### AUD-06: the app cannot tell anyone why a result was produced
- **Severity:** High. **Type:** Missing functionality (transparency). **CODE-CONFIRMED.**
- **Where:** web `app/app/attendance/[id]/page.tsx:363-406` "Calculation details — for HR and support";
  mobile `attendance_day_detail_screen.dart:473-495`; API `schemas.py:1707` (no policy thresholds).
- **Current:** for a `HALF_DAY` the screens show worked minutes, scheduled minutes and a "Late classification"
  code. They do not show the band or threshold that applied, the grace, whether a late mark or core-hours
  breach forced the half day, or which part of the day leave covered. These facts exist in the snapshot
  (`grace_band_credit`, `hour_band_gap`, `half_day_leave`, `terminal_reason`), but they are shown only as a
  raw JSON dump. On web, the "Calculation details" block shows raw codes such as `WEEKLY_OFF` and the
  late / OT classification codes, decimal fractions ("0.50") and **policy version UUIDs**. Mobile
  prettifies the codes but shows the same fractions and ids. I found no permission check around the block in
  the web page, so employees appear to see it too (confirm with an employee login).
- **Expected:** a plain-language "Why this result" section built from a structured explanation the backend
  returns (UI plan §4).

### AUD-07: an "Incomplete" day silently becomes loss of pay at month close
- **Severity:** High. **Type:** Confirmed transparency gap with payroll impact. **CODE-CONFIRMED.**
- **Where:** finalize path `service.py` ~8319-8430 (`TREAT_ABSENT` default resolves INCOMPLETE as absent at lock;
  `ATTENDANCE_INCOMPLETE_RESOLVED_AT_LOCK`); display: amber "Incomplete" badge, web `attendance-status-badge.tsx`,
  self-view attention list ("Open a day to request a correction").
- **Current:** nothing tells the employee that the day will count as absent (unpaid) if not fixed before
  close, or by when.
- **Expected:** "Not fixed by <period end>: counts as absent (unpaid)" on the day, in the attention list
  and in the reminder email.
- **Payroll impact:** direct: LOP the employee did not see coming.

### AUD-08: on past dates, employees with no row disappear from the totals
- **Severity:** Medium. **Type:** Confirmed inconsistency. **CODE-CONFIRMED.**
- **Where:** `summary.py:350` `no_record = await self._no_record(...) if is_today else 0`. The overview counts
  `NO_RECORD` for any date (`overview.py:90`, left join from `Employee`).
- **Current:** choose yesterday on the Attendance page: an employee whose row was never calculated (sweep
  missed, `CONFIG_ERROR` before row creation, joined mid-window) is absent from "Total employees" and from the
  rate's denominator. The home dashboard for the same date lists them as "No record".
- **Impact:** a failing calculation is invisible exactly when HR looks back to check it.

### AUD-09: three different month totals for the same employee
- **Severity:** Medium (High at payroll time). **Type:** Confirmed inconsistency. **CODE-CONFIRMED;** the exact
  numbers depend on data (NEEDS-RUNTIME for examples).
- **Where:** web employee month view `dashboard.ts:1188` `summarizeMonth` (whole days by bucket); HR calendar
  `hr-calendar.ts:62-75` (present with HALF_DAY = 0.5, leave = whole LEAVE days); payroll period summary
  `service.py` ~8090-8125 (fractions: half-day leave splits 0.5 leave / 0.5 present, half weekly off, etc.).
  Mobile mirrors the client versions (`employee_attendance_summary.dart`, `hr_calendar.dart`).
- **Example:** half-day leave in the morning, worked the afternoon (status `PRESENT`, `leave_fraction 0.50`):
  month view counts Present 1, Leave 0; HR calendar Present 1, Leave 0; payroll Present 0.5, Leave 0.5.
- **Expected:** the employee month card and the HR calendar show the same "paid days / LOP days / leave days"
  that payroll will use, labelled as such.

### AUD-10: "exception" means four different things
- **Severity:** Medium. **Type:** Architectural weakness. **CODE-CONFIRMED.**
- **Where:** see §1.3 and AUD-01. Web `exceptionLabels` ignores late, early out, breaks and core-hours; the
  overview counts breaks and submitted regularizations; summary counts unresolved work-on-leave.
- **Impact:** the "Needs attention" count, the KPI "exceptions" and the mismatch banner can disagree.

### AUD-11: one day, two names
- **Severity:** Low. **Type:** Confirmed UX inconsistency. **CODE-CONFIRMED.**
- **Where:** web status badge (`types.ts:190`): "Not expected", "WFH", "Config error"; web bucket labels
  (`dashboard.ts:237`): "Holiday", "Weekly off", "Remote (WFH)", "Other non-working". The web day page header
  uses the badge ("Not expected"), the web calendar and mobile day header use buckets ("Holiday").
- **Fix:** one display vocabulary from the backend (R-B02).

### AUD-12: the calendar can show only one thing per day
- **Severity:** Medium. **Type:** Confirmed UX problem. **CODE-CONFIRMED.**
- **Where:** web `month-calendar.tsx` (one tone + one glyph per bucket; `title` is the bucket only); mobile
  `employee_analytics.dart:151` `CalendarCell` (one bucket).
- **Current:** late, missing punch, overtime, half-day leave, pending correction, worked on a holiday and
  locked are not visible on the cell. A late day with a missing punch looks the same as a perfect day if its
  status is PRESENT under `AUTO_CLOSE`. "No record" and (on web) future days share a dashed style
  (future handling on web NEEDS-RUNTIME; mobile has `isFuture`).
- **Fix:** UI plan §3 (status fill + up to two corner markers + split cell for half days).

### AUD-13: "Work from home" can be requested but never happens
- **Severity:** Low (Medium if a customer relies on it). **Type:** Potential bug, NEEDS-RUNTIME.
- **Where:** `schemas.py:117` (`WFH` regularization type), `calculation.py:3657` ("WFH remains a no-op"),
  REMOTE tiles and legends in web `kpi-grid.tsx` and mobile `attendance_pulse.dart`.
- **Unverified:** what an approved `WFH` regularization actually writes (it may apply synthetic punches like
  other types, making the day `PRESENT`, not `WFH`). Either way the Remote figure is always 0.
- **Decision needed:** support WFH as a status, or remove the type and the Remote tiles.

### AUD-14: overtime shown is not the overtime paid
- **Severity:** Medium. **Type:** Confirmed transparency gap. **CODE-CONFIRMED.**
- **Where:** payroll uses `ot_minutes_approved` by `ot_day_class` (`service.py:8144-8150`). Web day summary badge
  "Overtime 2 h" uses `ot_minutes_detected` (`day-detail.ts` `summarizeDay`). `ot_pending` is never worded for
  the employee. The day page "Time summary" does show "(x approved)".
- **Expected:** "Overtime: 2 h found · 1 h 30 m approved · 30 m waiting for approval", and the class
  (weekly off, holiday, night) in words.

### AUD-15: "as of" time is when the page loaded, and nothing is calculated before 09:30
- **Severity:** Medium. **Type:** Confirmed UX problem (part of AP-13, still open in substance). **CODE-CONFIRMED.**
- **Where:** `summary_schemas.py:109` has no `calculated_at`; the sweep runs at 09:30 IST (`celery_app.py:105`).
  Before 09:30, only people who punched have a row.
- **Expected:** "Calculated up to HH:MM; next refresh 09:30" and the morning view explained, not just a
  load time.

### AUD-16: no offline punching on mobile
- **Severity:** Low. **Type:** Missing functionality. CODE-CONFIRMED by search (no outbox / local queue in
  `features/attendance`; `punch_location_flow.dart:33` attempts the punch without location when the policy read
  fails).
- **Decision needed:** whether offline punches are wanted. They raise anti-fraud questions (device time,
  location age) that the backend's geofence and face checks would have to accept.

### AUD-17: tests do not cover the places where surfaces disagree
- **Severity:** Medium. **Type:** Test gap. **CODE-CONFIRMED.**
- `tests/integration/modules/attendance/test_attendance_summary.py` and `test_company_attendance_overview.py`
  contain no `HALF_DAY` case. No test feeds the same rows to summary, overview, period summary and the client
  bucket functions and compares the results. `apps/web/e2e/` has no attendance spec. Flutter tests cannot run
  in this environment (and, per the 16 Nov audit, not in CI).

### AUD-18: beat schedule fixed to India time
- **Severity:** Informational. `celery_app.py:105` runs at 09:30 `Asia/Kolkata` for every company. Correct for
  the target market. Record it as a constraint for any non-IST customer.

### Items carried from the 18 Nov UX audit (`ATTENDANCE_PAGE_UX_AUDIT_2026-11-18.md`)
Most were fixed and merged (`e632fcb`, `8b6999c`). Still open: **AP-09** (a partly punched-in day is compared
with a full day last week). The 18 Nov audit lists "mobile bulk mark" as not done, while the 19 Nov parity
report says mobile has bulk Mark attendance; check this on a device.

---

## 4. Employee experience checklist (brief 4.1)

| Can the employee immediately see… | Web | Mobile | Notes |
|---|---|---|---|
| Present or absent | Partly | Partly | Wrong word while working (AUD-03, web); verdicts unexplained (AUD-06) |
| Currently working | Yes | Yes | "Working / On break / Checked out" |
| Time worked so far | Conflicting | Not for open day | AUD-05 |
| Time left in shift | **No** | **No** | `scheduled_end` is available |
| Late, and by how much | Yes | Yes | Grace and scheduled start not shown side by side |
| Required hours met | **No** | **No** | band thresholds not exposed |
| Overtime eligibility / approved / pending | Partly | Partly | AUD-14 |
| Action required | Yes (past days) | Yes | Not told of the payroll consequence or deadline (AUD-07) |

## 5. HR experience checklist (brief 4.2)

Strong today: exception-first list with fixes on each row, typeahead filter, bulk mark (web), List/Grid
switch, department and branch breakdowns, mismatch banner, correction decision centre. Gaps: numbers disagree
between home and Attendance page (AUD-01/02/08); no "why" for a disputed day (AUD-06); no single month view
of paid / LOP days matching payroll before close (AUD-09); exception counts disagree (AUD-10).

## 6. Reports and payroll consistency (brief Phase 7)

| Figure | Source | Same as payroll? |
|---|---|---|
| Attendance page totals, rate, trends | `GET /attendance/summary` | No: whole-day buckets, half day = 0 |
| Home dashboard | `GET /dashboards/company/attendance-overview` | No: half day = present |
| Employee month card | client `summarizeMonth` | No: whole days |
| HR calendar counts | client `buildHrCalendar` | No: half day 0.5, fractional leave ignored |
| Monthly summary (Payroll → Attendance periods) | `GET /attendance-periods/{id}/summary` | **Yes**: this is the payroll input |
| Overtime on day screens | `ot_minutes_detected` | No: payroll pays approved |

Only one screen shows what payroll will use. Every other total is a different calculation under a
similar label.

## 7. Classification summary

| Type | Findings |
|---|---|
| Confirmed bug | AUD-04 |
| Confirmed inconsistency / data presentation | AUD-01, AUD-02, AUD-08, AUD-09, AUD-10, AUD-11 |
| Confirmed UX problem | AUD-03, AUD-05, AUD-12, AUD-15 |
| Missing functionality / transparency | AUD-06, AUD-07, AUD-14, AUD-16 |
| Potential bug (needs runtime) | AUD-13 |
| Test gap | AUD-17 |
| Informational | AUD-18 |
| Engine rule defects (carried) | MA-01 … MA-34, H-29, O-15, AR-15 (see 16 Nov reports) |

## 8. Confirmation

No source code, configuration, database schema, migration, dependency or application data was modified.
No command that writes data was run. Nothing was staged, committed or pushed. The uncommitted mobile calendar
changes and untracked documents that were already in the working tree were left as they were.
