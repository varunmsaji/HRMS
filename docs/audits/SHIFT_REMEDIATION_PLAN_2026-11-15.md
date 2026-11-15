# Shift Management Remediation Plan — 15 November 2026

Source of findings: `SHIFT_MANAGEMENT_AUDIT_2026-11-15.md` (SH-01 … SH-22, P-01 … P-14).
Branch `test`, starting commit `f4f81ae` (engine version 12).

---

## 1. Verification report

No commit has landed on `test` or `origin/test` since the audit, so every finding was verified
against the same code. Findings marked *probe* in the audit were re-run against the engine with
the same results.

| Issue | Reproduces | Existing test covering the area | Current behaviour (unchanged from audit) |
|---|---|---|---|
| SH-01 | Yes (probe) | `test_calculation.py` window tests assert the 2h pad | Punch ≥2h outside the shift not loaded; day INCOMPLETE |
| SH-02 | Yes (probe) | none | Overlapping windows; same punch on two days |
| SH-03 | Yes (probe) | `test_off_day_overtime.py`, `test_calculation.py` (operates flags) | Operating holiday: no-show paid, short day LOP |
| SH-04 | Yes (probe) | `test_calculation.py` split tests (same-day blocks only) | SPLIT: OT always 0; after-midnight block missed |
| SH-05 | Yes (code) | `test_attendance_day.py` immediate-calc tests (same-date only) | Overnight checkout recalculates the wrong date |
| SH-06 | Yes (code) | `test_shift_version.py` timezone tests accept any IANA zone | Shift version accepts any zone |
| SH-07 | Yes (code) | `test_calendar_policies.py` (assignment shift only) | SHIFT-scoped policy follows the assignment shift |
| SH-08 | Yes (probe) | `test_calculation.py` missing-shift tests | No shift: off day ABSENT/INCOMPLETE; 1 minute = full day |
| SH-09 | Yes (code) | `test_master_data_compensation_termination.py` | Night checkout after last working day refused |
| SH-10 … SH-12 | Yes (probe) | `test_break_management.py` | As audited |
| SH-13 | Yes (code) | `test_employee_assignment.py` asserts the "must be after current" rule | As audited |
| SH-14 | Yes (probe) | none | Dormant settings accepted |
| SH-15 | Yes (code) | `test_break_events_api.py`, `test_break_management_schema.py` (API only) | No client sets modes |
| SH-16 … SH-22 | Yes (code) | partial | As audited |

Baseline test runs (before any change):

- Unit: 1978 passed, 1 failed (`test_settings.py::test_development_has_no_explicit_origins_but_a_valid_fallback`,
  reads the local `.env`; unrelated to shifts).
- Integration (attendance, shift, shift version, assignment, leave): see section 8.

### Dependencies between findings

```
Resolved Work Schedule (new) ──┬─> SH-07 (policy scope)  ──> SH-03 Leave alignment
                               ├─> SH-16 (my shift, planner)
                               └─> Punch ownership (new) ──┬─> SH-01, SH-02
                                                           ├─> SH-05 (which days to recalc)
                                                           ├─> SH-09 (last working day)
                                                           └─> orphan check at period close
SH-04 split placement ─────────> Punch ownership (split spans) 
Impact queue (new) ────────────> SH-13, SH-18, shift version publish, policy assignment
SH-03, SH-08 engine changes ───> one ENGINE_VERSION bump with SH-01/02/04
```

---

## 2. Policy decisions

### Decided by the owner on 15 November 2026

| Ref | Decision |
|---|---|
| P-13 (SH-01/02) | Two new attendance-policy settings: maximum minutes a punch may be **before** shift start (default 240) and **after** shift end (default 720). The neighbouring day's shift always bounds a day's window as well. |
| P-02 (SH-03) | A shift that operates on a holiday or weekly off, or a roster "working this holiday" row, makes that day an **ordinary working day**: attendance expected, absence follows the missing-punch rule, work is ordinary pay with no holiday premium (overtime beyond the shift is NORMAL class). Leave charges a day. |
| P-06 (SH-08) | With no shift, worked minutes go through the attendance policy's **hour bands**; no late, early or overtime. A holiday or weekly off with no shift and no punches is a day off (NOT_EXPECTED). |
| SH-15 | Break modes are **hidden**: the API refuses `mode` on shift breaks and the break start/end endpoints while `SHIFT_BREAK_MODES_ENABLED` is false (default). Engine code stays. |

### Not decided — current behaviour kept, recorded as open

P-01 (holiday at the end of an overnight shift), P-04 (early arrival as OT), P-05 (bands for short
shifts), P-07 (grace model), P-10 (night flexible shifts), P-11 (split-shift late/early and
partly-worked blocks), P-12 (roster change after leave), P-14 (two shifts per day).

### Chosen as engineering defaults (not pay policy)

- Orphan punches block period close; HR can dismiss one with a reason (audited).
- Shift length: 1 minute to 24 hours (start ≠ end already required); flexible `required_minutes`
  1–1440; total breaks shorter than the shift; split blocks placed in sequence within 24 hours.
- Pending swaps expire once their date has passed.
- Shift names unique per company (case-insensitive) among shifts not deleted.

---

## 3. Architecture

### 3.1 Resolved Work Schedule (Invariant A)

New module `attendance/work_schedule.py`:

```
resolve_work_schedule(session, company_id, employee_id, date) -> ResolvedWorkSchedule
  assignment         EmployeeAssignment covering the date (or None)
  roster_entry       PUBLISHED ShiftRoster row for the date (or None)
  shift_id           roster_entry.shift_id if a roster row exists, else assignment.shift_id
  source             ROSTER | ASSIGNMENT | NONE
  shift_version      published version covering the date (or None → "version missing")
  shift_inputs, tz_name, window (scheduled span)
  roster_week_off_override, roster_holiday_working_override
```

Precedence: **published roster row → assignment's shift → no shift.** A roster row with
`shift_id` NULL (pure day off) means no shift, it does not fall back to the assignment.

Every consumer calls it: day calculation, punch shift-window check, previous-day lookup, policy
and calendar scope resolution (SHIFT candidate), Leave working shares, "My shift", weekly
planner. A per-call memo avoids repeated queries inside one request.

### 3.2 Punch ownership (Invariant B)

Pure module `attendance/punch_ownership.py`.

Each candidate day claims a span:

| Day | Span used for ownership |
|---|---|
| FIXED | scheduled start … scheduled end |
| FLEXIBLE | window start … window end + required minutes |
| SPLIT | first block start … last block end (blocks placed in sequence, SH-04) |
| No shift / not active | the local calendar day, lowest priority |

and a window: `[span start − max_before, span end + max_after]`, using that day's own
attendance policy settings.

Algorithm, over the employee's punches for dates D−2 … D+2:

1. Sort, collapse duplicates and drop strays exactly as the engine does; each dropped punch
   follows the punch it was merged into.
2. Pair into sessions (IN→OUT; unpaired punches are single-point sessions).
3. A session is a candidate for every shift day whose window contains its first punch.
   It goes to the candidate whose span it **overlaps most**; with no overlap, the one it is
   **nearest** to; ties go to the earlier date. If no shift day claims it, the no-shift day on
   whose local date it starts takes it. Otherwise it is an **orphan**.
4. Day D receives exactly the raw punches of its sessions.

Properties (tested as invariants): every punch has zero or one owner; the result for D is the
same whichever day is being calculated; a session is never split.

This replaces `punch_window_utc` padding, `prior_day_window_end`, and the orphan report's
window reconstruction. `day_open` becomes "now ≤ ownership window end".

### 3.3 Impact set and recalculation (Invariant C)

New table `attendance_recalc_request` (company, optional employee, optional shift, date range,
reason, source entity, created/processed timestamps; RLS). Writers:

| Change | Impact recorded |
|---|---|
| Shift version published | shift, effective_from … today |
| Assignment created or inserted | employee, effective_from … today |
| Roster row published, updated or deleted | employee, that date |
| Swap approved | both employees, that date |
| Policy assignment created or ended | company (or employee), effective_from … today |

Processing: a request is queued in the same transaction as the change; after commit a Celery task
is kicked; a 5-minute Beat backstop picks up anything left. The processor recalculates existing,
unlocked `attendance_day` rows matching the request, one employee-date per transaction (same
shape as the daily sweep), then marks the request processed. Closed periods are refused at the
write (existing guards plus new ones for assignments); locked rows are never recalculated.

### 3.4 Truthful configuration (Invariant D)

See section 5.

---

## 4. Database changes (one migration, needs a person to merge)

- `attendance_policy_version.max_early_punch_minutes INT NOT NULL DEFAULT 240`,
  `max_late_punch_minutes INT NOT NULL DEFAULT 720` (CHECK 0–1440).
- `attendance_recalc_request` (RLS, FORCE).
- `punch_dismissal` (punch_id unique, reason, dismissed_by, dismissed_at; RLS).
- `shift_swap_request.status` CHECK gains `EXPIRED`.

No rewrite of existing rows. Data checks to run before deploy (read-only):

```sql
-- shift versions with a non-India timezone
SELECT company_id, shift_id, id, timezone FROM shift_version
 WHERE timezone IS NOT NULL AND timezone NOT IN ('Asia/Kolkata','Asia/Calcutta') AND deleted_at IS NULL;
-- assignments naming a shift with no published version on their start date
-- roster rows naming a shift with no published version on their date
-- open attendance days that will change (all unlocked rows: recalculated after deploy)
```

---

## 5. Configuration truthfulness

| Field | DB | API | Web | Mobile | Engine | Status | Action |
|---|---|---|---|---|---|---|---|
| `punch_rounding`, `rounding_minutes` | policy version | accepted | hidden | shown | not applied | DORMANT | API rejects non-NONE; mobile hides |
| `missing_punch_behaviour = AUTO_CLOSE` | | accepted | hidden | shown | treated as "keep band status" | DORMANT | API rejects AUTO_CLOSE |
| `half_day_split`, `half_day_boundary_minutes` | | accepted | hidden | shown | not read | DORMANT | mobile hides; API rejects non-default |
| `early_out_uses_core_end` | | accepted | hidden | shown | not read | DORMANT | same |
| `ShiftVersion.weekly_off_pattern_id` | | accepted | shown | shown | not read | DORMANT | API rejects non-null; clients hide |
| `scheduled_minutes`, `min_/max_scheduled_minutes` | | accepted | shown | shown | not read | DORMANT | API rejects non-null; clients hide |
| `ShiftBreak.mode` and related | | accepted | not sent | not sent | read | ACTIVE (hidden) | gated by setting (SH-15) |
| `Shift` legacy timing/grace/break columns | | read-only | — | — | not read | LEGACY | documented; not exposed for writing |

Stored values on existing rows are left as they are; they continue to have no effect.

---

## 6. Engine version

One bump to **13** covering SH-01/02 (ownership), SH-03, SH-04, SH-08, SH-10, SH-12. After
deploy, every unlocked day of open periods is recalculated (range backfill per open period).
Locked days keep their stored results and engine version.

---

## 7. Commit plan

| # | Commit | Main files | Tests |
|---|---|---|---|
| 1 | Plan document | this file | — |
| 2 | Resolved Work Schedule; use it everywhere | `work_schedule.py`, `service.py`, `calendar_resolution.py`, `my_work_profile.py`, `leave/service.py` | resolver precedence; SH-07 |
| 3 | Split-shift block placement and scheduled minutes (SH-04) | `calculation.py`, organisation validation | split matrix |
| 4 | Migration: policy window settings, recalc queue, punch dismissal, swap EXPIRED | alembic, models, schemas | migration test |
| 5 | Punch ownership (SH-01, SH-02, SH-05, SH-09, orphan check) | `punch_ownership.py`, `service.py` | invariant + regression |
| 6 | Engine: SH-03, SH-08 | `calculation.py`, `leave/service.py` | regression |
| 7 | Timezone restriction (SH-06) | schemas, web, mobile | regression |
| 8 | Impact queue and processing (Invariant C) | `recalc.py`, tasks, writers | integration |
| 9 | Assignment integrity (SH-13) | `employee/service.py`, web | timeline insertion |
| 10 | Roster and swap integrity (SH-18, SH-20) | `service.py`, `schedule_service.py` | integration |
| 11 | Breaks (SH-10, SH-11, SH-12, SH-15) | `calculation.py`, organisation validation | regression |
| 12 | Dormant configuration (SH-14) | schemas, web, mobile | API rejects |
| 13 | Dates in company timezone (SH-17) | several | regression |
| 14 | Validation (SH-21) | organisation service | API tests |
| 15 | UX (SH-16, SH-19, SH-22) | schedule service, web, mobile | integration |

---

## 8. Results

Status on 15 Nov 2026 (branch `test`, not pushed). Engine version 13.

### Fixed

| Issue | What changed | Where |
|---|---|---|
| SH-01, SH-02, SH-05, SH-09 | Punch ownership: each punch belongs to exactly one day, inside a window set by `max_early_punch_minutes` (240) and `max_late_punch_minutes` (720) and bounded by the neighbouring shift. Orphan punches are listed, block period close and can be dismissed. | `punch_ownership.py`, `ownership_service.py` |
| SH-03 | A holiday or weekly off the shift operates on (or a roster "working this holiday" row) is an ordinary working day: no-show follows the missing-punch rule, overtime is NORMAL class, leave charges the day. | `calculation.py`, `leave/service.py` |
| SH-04 | Split-shift blocks placed in sequence; scheduled minutes are the sum of the blocks; overtime is detected. | `calculation.py` |
| SH-06 | Branch and shift-version timezones are held to `allowed_company_timezones`, at write and at publish. Web and mobile pickers offer only the allowed zones. | organisation schemas/service, web, mobile |
| SH-07, SH-16 (partial) | One resolved work schedule (roster, else assignment) used by calculation, punch window, SHIFT-scoped policy, calendar and My Shift. | `work_schedule.py` |
| SH-08 | No shift: worked minutes go through the hour bands; a holiday or weekly off with no shift and no punches is NOT_EXPECTED. | `calculation.py` |
| SH-10 | A punched gap matches the break it overlaps most; under `excess_break_behaviour = DEDUCT` a paid break pays up to its maximum. | `calculation.py` |
| SH-11 | A FLEXIBLE shift's fixed break is checked against window start to window end + required minutes. | organisation service |
| SH-12 | A punched gap overlapping an AUTO_DEDUCT window counts toward that deduction. | `calculation.py` |
| SH-13 | Assignment: refused in a closed period; `clear_shift` flag ("No shift" in web, a toggle in mobile); a chosen shift needs a published version on the start date; a change can be dated before a future-dated row (the covering row is split). | `employee/service.py`, web, mobile |
| SH-14 | The API refuses non-default dormant settings (punch rounding, AUTO_CLOSE, half-day split, `early_out_uses_core_end`, shift-version weekly-off pattern and scheduled minutes). Web and mobile no longer show or send them. | schemas, web, mobile |
| SH-15 | Break modes and break start/end are refused unless `SHIFT_BREAK_MODES_ENABLED` (default off; on in the test env). | settings, break router/schemas |
| SH-17 | Company-zone "today" for the weekly planner default, swap dates, break-override revoke and geofence workplaces; punch-list date filter uses company days; mobile shows punch-refusal and enrollment times in the company zone. | several |
| SH-18, SH-20 | Roster rows need an active shift with a published version on the date. Swaps: past dates refused (company zone, HR and self-service), stale pending swaps expire, approval locks both roster rows in a fixed order, references numbered under an advisory lock. | `service.py`, `schedule_service.py`, `core/db/locks.py` |
| SH-21 | Shift names unique per company ignoring case; `required_minutes` 1-1440; breaks together shorter than the shift. | organisation service/schemas |
| Invariant C | Shift publish, assignment, published roster change, approved swap and policy assignment queue an `attendance_recalc_request`; a Celery task (kicked after commit, plus a 5-minute Beat) recalculates the existing unlocked days in range. | `recalc.py`, `tasks.py`, `celery_app.py` |

Also: the web and mobile attendance-policy forms now offer the two punch-window settings.

### Not done

- SH-16 (rest): weekly planner does not yet count staff on their default (assignment) shift, nor show per-day timings.
- SH-19: no read-only shift options endpoint for roster and assignment users.
- SH-22: shifts page copy ("grace" lives on the attendance policy).
- SH-21 caveat: the name check has no unique index, so two creates at the same moment can both pass.
- Attendance-policy version publish does not queue a recalculation (not in the commit plan).
- Awaiting owner decision, current behaviour kept: P-01, P-04, P-05, P-07, P-10, P-11, P-12, P-14.

### Migration

`20261115090000_shift_remediation.py` (additive). `attendance_recalc_request.employee_id` and
`shift_id` cascade on delete. A person must merge it.

### After deploy

1. Run the read-only data checks in section 4.
2. Recalculate unlocked days of open periods: `POST /attendance/days/calculate-range` per open
   period (engine 13 changes results for SH-03, SH-04, SH-08, SH-10, SH-12 and punch ownership).

### Test results

Run on 15 Nov 2026 against isolated test databases (`hrms_test`, `hrms_test2`).

| Suite | Result |
|---|---|
| API: organisation, employee, attendance, leave integration | 1843 run; 4 failures were test fixtures broken by the new rules (two shifts with one name in a tenant; an assignment before its shift's first version; an assignment dated before a future row, now allowed). Fixed and re-run green. |
| API: all other unit and integration tests | 2720 run; 29 failures were mock-session unit tests reaching the new database checks, and the job-health broker test seeing unconsumed recalculation kicks. Fixed and re-run green. 1 remaining failure, `test_settings.py::test_development_has_no_explicit_origins_but_a_valid_fallback`, comes from the local `.env` and is unrelated. |
| ruff (check + format), `mypy src/hrms`, import-linter | clean |
| Web: `tsc`, vitest | clean; 1044 passed |
| Mobile: `flutter analyze`, `flutter test` | clean; 1396 passed |

The SH-10 and SH-12 regression tests fail on the engine before this change. The roster and swap
tests (SH-18, SH-20) could not be checked against the old code separately: the old service files no
longer import with the new employee code.

---

## 9. Follow-up: N-02 and N-03 (engine version 14)

From `SHIFT_SCENARIO_MAP_2026-11-15.md` (findings N-02 and N-03). Same branch, not pushed.

| Finding | Change | Where |
|---|---|---|
| N-03 | A pair whose OUT lies at or beyond the end of its owning shift day's punch window is split into a lone IN and a lone OUT, each owned separately. A forgotten OUT plus a next-morning OUT no longer makes one 24-hour day with about 15 hours of overtime: both days are INCOMPLETE until corrected. Days without a shift are not split (no schedule to outrun). | `punch_ownership.py` (`assign_owners`, `split_pair`) |
| N-02 | Grace minutes (at most the grace, and no more than the minutes actually missed at that end) are credited to the **hour-band lookup only**, capped at the net scheduled minutes. Worked minutes, overtime, late and early minutes are unchanged. Applies to FIXED, FLEXIBLE, SPLIT and half-day-leave days; recorded as `snapshot.grace_band_credit`. | `calculation.py` (`grace_band_credit`) |

Known edge: the credit never covers more than the grace, so on a shift with no spare minutes an arrival one minute past grace is still a half day (scenario BRK-13).

Not included, by decision: the punch endpoint's stale-punch handling (the 18-hour order rule, R-07) stays a separate change after its own audit of stale punches and night shifts.

After deploy: recalculate unlocked days of open periods (`POST /attendance/days/calculate-range` per open period). Locked days keep their engine version.

Tests: `test_grace_band_credit.py` (27), `test_punch_ownership.py` (9 new, including a property test that no owned pair outlasts its day's window).
