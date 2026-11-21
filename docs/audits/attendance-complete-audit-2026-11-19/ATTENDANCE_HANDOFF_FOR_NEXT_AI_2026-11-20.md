# Attendance work: handoff to the next AI

Written 20 November 2026. This document is self-contained: you do not need the earlier conversation.
Read it fully, then read the five audit documents in this folder for the evidence behind each task.

- `ATTENDANCE_COMPLETE_AUDIT_REPORT.md` — findings AUD-01..18 with file and line evidence
- `ATTENDANCE_IMPLEMENTATION_ROADMAP.md` — task ids R-A..R-G, dependencies, acceptance criteria
- `ATTENDANCE_UI_UX_IMPROVEMENT_PLAN.md` — target screens and the "why this result" contract
- `ATTENDANCE_TEST_SCENARIO_MATRIX.md` — scenarios S-01..S-45 and cross-surface checks X-01..X-09
- `ATTENDANCE_AUDIT_EXECUTIVE_SUMMARY.md` — one-page summary

---

## 1. Ground rules (from the repository's `AGENTS.md`; they apply to you)

- Repo: `/media/varun/varun27/work/staff-spectrum/HRMS` (monorepo: `apps/api` FastAPI + SQLAlchemy + Celery,
  `apps/web` Next.js, `apps/mobile` Flutter).
- `main` is the release branch. **Never commit or push to `main`.** All edits happen on `test`.
  Changes reach `main` only through a pull request from `test`; a local git hook refuses pushes to `main`.
- Before you start: `git status`, `git branch --show-current` (must be `test`), `git pull --ff-only origin test`.
  If the working tree has changes you did not make, leave them alone and tell the user.
- Stage files **by name**. Never `git add .` or `git add -A`. Never force-push. Never rewrite pushed history.
- Never skip or weaken a check (tests, lint, secret scan) to get a build passing. Ask the user first.
- Run the checks for the apps you changed (commands in `.github/workflows/ci.yml`), push `test`, open or update
  the PR from `test` to `main`. CI merges it when green. Do not merge it yourself.
- A PR that touches `.github/`, `.gitleaks.toml`, `AGENTS.md`, `CLAUDE.md` or `apps/api/alembic/` is merged by
  the user, not by CI. Say so and stop.
- **Do not commit or push until the user says to.** Everything below marked "uncommitted" is waiting on that.
- `apps/web/AGENTS.md` warns that this Next.js version has breaking changes: read the relevant guide in
  `apps/web/node_modules/next/dist/docs/` before writing web code that touches routing or rendering APIs.
- Another Claude session works in this same working tree (it has been committing mobile calendar and roster
  work: `571d4df`, `b700bb0`). Check `git status` and file modification times before editing shared files.
  Do not touch mobile calendar / roster files that you did not change.

## 2. How to run things on this machine

| What | Command |
|---|---|
| API integration tests (attendance) | `cd apps/api && FACE_PROVIDER_COMPARISON_ENABLED=false DATABASE_URL=postgresql://hrms:hrms_dev_password@localhost:5433/hrms_ar_test REDIS_URL=redis://localhost:6380/3 HRMS_TEST_CELERY_DB=12 .venv/bin/python -m pytest tests/integration/modules/attendance/test_attendance_summary.py -q -p no:cacheprovider` |
| API lint / types | `cd apps/api && .venv/bin/python -m ruff check <files> && .venv/bin/python -m ruff format --check <files> && .venv/bin/python -m mypy <files>` (the `.venv/bin/<tool>` shebangs are broken; always `python -m`) |
| Web tests | `cd apps/web && npx vitest run src/lib/attendance src/components/attendance src/app/app/attendance` |
| Web types / lint | `npx tsc --noEmit -p .` and `npx eslint <files>` |
| Mobile tests | `cd apps/mobile && ~/flutter/bin/flutter test <files>` (Flutter 3.29.2 is at `~/flutter/bin/flutter`, not on PATH) |
| Mobile analyze | `~/flutter/bin/flutter analyze <files>` |
| Mobile goldens | change a screen, run the golden tests, **look at `test/failures/*_masterImage.png` vs `*_testImage.png`**, then `flutter test <file> --plain-name "<name>" --update-goldens`, then delete `apps/mobile/test/failures/` |
| Dev servers | Claude desktop `preview_start` with names `api` (port 8000) and `web` (port 3000) from `.claude/launch.json`. The app needs a login; there is no test password in the repo. Ask the user to sign in. |

Cautions:
- `hrms_ar_test` (Redis db 3, Celery db 12) is the database for attendance test runs started by this work. `hrms_test`
  may belong to another session. **Never run two pytest processes against the same database** (shared fixtures collide).
- `apps/api/.env` turns face comparison on, which conflicts with the tests' forced "face disabled". Hence
  `FACE_PROVIDER_COMPARISON_ENABLED=false` for local runs. CI has no `.env`.
- The attendance engine is `ENGINE_VERSION = 16` (`apps/api/src/hrms/modules/attendance/calculation.py:99`).
  Nothing below changes the engine except Phase A, which needs owner decisions first.
- Never run commands that write to the dev database (`hrms_dev`). Tests create and clean their own tenants.

## 3. State right now

Branch `test`. Last pushed state is whatever `origin/test` has; **all of the following is uncommitted in the working tree**
(from `git status` on 20 Nov):

**API**
- `apps/api/src/hrms/modules/attendance/summary.py` — `no_record` is now counted for any focus date (was only today);
  new `calculated_at` column selected in `_rows` and `max()` of it for the focus date returned.
- `apps/api/src/hrms/modules/attendance/summary_schemas.py` — `AttendanceSummaryRead.calculated_at: datetime | None = None`.
- `apps/api/tests/integration/modules/attendance/test_attendance_summary.py` — asserts `calculated_at`, and that a past
  focus date counts the employee with no row (`no_record == 1`, `total_employees == 4`). Passes (7 tests with the overview file).

**Web**
- `apps/web/src/lib/attendance/day-detail.ts` — `offDayHeadline` (a holiday is named a holiday, never "Weekly off"),
  `isDayInProgress`, `summarizeDay(day, {inProgress})`, `payEffect`.
- `apps/web/src/lib/attendance/day-detail.test.ts` — tests for all four.
- `apps/web/src/components/attendance/day/day-summary.tsx` — "In progress" badge, no "Missing" while the shift runs.
- `apps/web/src/components/attendance/dashboard/self-view.tsx` — no status badge while the shift runs.
- `apps/web/src/components/attendance/dashboard/kpi-grid.tsx` — "N not calculated for <date>" wording on past dates.
- `apps/web/src/app/app/attendance/page.tsx` — no-record list for any focus date; "Last calculated" line.
- `apps/web/src/lib/attendance/summary.ts` — `calculated_at?: string | null` on the type.
- `apps/web/src/app/app/attendance/[id]/page.tsx` (+ `page.test.tsx`) — "Pay" field in words; "Calculation details" shown only with
  `ATTENDANCE.RECOMPUTE` or `ATTENDANCE.VIEW_ALL`.

**Mobile**
- `apps/mobile/lib/features/attendance/domain/pay_effect.dart` (new) + `test/pay_effect_test.dart` (new).
- `apps/mobile/lib/features/attendance/presentation/attendance_day_detail_screen.dart` — Pay row; technical details gated the same way.
- `apps/mobile/test/attendance_month_and_day_test.dart` and four golden PNGs `day_detail_incomplete_390`, `day_detail_no_punches_{320,360,390}`.

**Checks that passed on 19–20 Nov:** web 362 tests, `tsc` clean; API summary + overview tests 7 passed, ruff and mypy clean;
mobile 141 tests including goldens, analyzer clean. **Not done:** nobody has looked at these pages in a browser
(the user said they would check themselves). Known and pre-existing: ESLint reports `react-hooks/set-state-in-effect` in
`apps/web/src/app/app/attendance/[id]/page.tsx` — it is in the committed file too; not caused by this work.

**Docs (also uncommitted, untracked):** this folder, plus six unrelated untracked files in `docs/audits/` from other sessions —
do not add those.

## 4. Decisions: what is settled and what is not

The user **confirmed D-AUD-1, D-AUD-2 and D-AUD-3 on 2026-11-20**. Build on them; no need to ask again. D-AUD-3 is
confirmed on one condition: remove work from home only if the check in section 5.5 finds nothing uses it (stored
records, payroll, leave or policy settings). If something does, keep it and hide it in the UI instead.
The Group A engine decisions are still open.

| ID | Question | Decision | Status |
|---|---|---|---|
| D-AUD-1 | What is a half day worth in the attendance rate? | 0.5 | **Confirmed 2026-11-20** |
| D-AUD-2 | Is a half day "present" on the home dashboard? | No: its own figure on both pages; rate = (present + remote + on duty + 0.5 × half day) ÷ expected | **Confirmed 2026-11-20** |
| D-AUD-3 | Work-from-home as a status? | Remove for now, after first checking what an approved WFH regularization writes (scenario S-27) | **Confirmed 2026-11-20, conditional on the check** |
| Group A (17 engine decisions) | see `docs/audits/ATTENDANCE_DECISION_SHEET_GROUP_A_2026-11-18.md` | each has a recommendation | Awaiting the owner; **blocks Phase A** |

Do **not** start Phase A (engine rule changes, tasks R-A01..R-A07) without the matching Group A answer. Those change what employees are paid.

## 5. What is left, in the order to do it

Task ids are from `ATTENDANCE_IMPLEMENTATION_ROADMAP.md`. "Done" ones are listed so you do not redo them.

### 5.0 Done (uncommitted): R-D01, R-D02 (web), R-B06, R-B04 (API + web page), R-C04 (web + mobile)
Not covered by those: mobile does not show `calculated_at`; mobile day headline logic was not changed (it already handles "today in progress").

### 5.1 First: get the current work into a pull request (needs the user's go-ahead)
1. Re-run the checks in section 2 for API, web and mobile files you touch. Confirm nothing changed under you (`git status`, `git log`).
2. Stage **by name** only the files in section 3 (the audit folder is optional: ask the user whether the docs should go in the PR).
3. One commit (or small logical commits) on `test`; message style follows the log (`fix(attendance): ...`, `feat(web): ...`).
   End with the attribution line the harness gives you.
4. `git pull --ff-only origin test`, push, open or update the PR `test` → `main`. Do not merge.
5. If CI fails, fix the cause on `test`. Report it if you cannot.

### 5.2 R-B01 — one shared bucket and exception rule (the main item; waits on D-AUD-1/2)
**Problem (AUD-01, 02, 10).** `overview.py` and `summary.py` decide the same day differently.
- `apps/api/src/hrms/modules/attendance/overview.py` lines ~89–120: bucket `case`, `is_exception`, `in_progress` (uses `scheduled_end` and a clock).
  It counts `HALF_DAY` as PRESENT, shows today's open check-in as PRESENT and a no-punch day as NOT_CHECKED_IN.
- `apps/api/src/hrms/modules/attendance/summary.py` `_bucket_expr` (~121–136), `_rows` exception (~173–184), `_per_day` not_checked_in (~524):
  `HALF_DAY` is its own bucket and is **not** in `WORKING_BUCKETS` (rate numerator), and it has no clock so open days are INCOMPLETE.

**Do.**
1. New module `apps/api/src/hrms/modules/attendance/day_classification.py` with one SQL expression builder for: bucket (clock-aware for
   today, using `scheduled_end` or the company's local day end as `overview.py` does), `is_exception`, and a per-row weight
   (`1` for PRESENT/REMOTE/ON_DUTY, `0.5` for HALF_DAY, `0` otherwise).
2. Make both `overview.py` and `summary.py` use it. `summary.py` needs a `now` (it already receives `today`; add `now: datetime | None`
   and pass it from the router the way `overview.py` does).
3. Rate becomes `(weighted present) ÷ expected` in `daily[]`, the KPI comparison, `weekday_absence` is unaffected, and `_breakdown`/`GroupStat.rate`.
   Keep `present` an integer count of fully-present days; add a new field for the weighted figure or compute the rate only. Keep
   `half_day` as a separate count on both responses.
4. Keep both endpoint response shapes backward compatible for one release (add fields, do not remove). Check consumers:
   web `apps/web/src/lib/dashboard/overview.ts`, `apps/web/src/lib/attendance/summary.ts`; mobile
   `apps/mobile/lib/features/attendance/domain/attendance_totals.dart` and insights. `grep -rn "attendance-overview\|attendance/summary" apps/web/src apps/mobile/lib`.
5. Exception definition: one list. Start from the union used by `overview.py` (missing punch, pending approval, INCOMPLETE, CONFIG_ERROR,
   unresolved or excess break, submitted regularization for that date) plus `summary.py`'s unresolved work-on-leave. Document it in the module docstring.

**Tests.**
- Extend `tests/integration/modules/attendance/test_attendance_summary.py` and `test_company_attendance_overview.py` with: a `HALF_DAY` row,
  an open check-in today before shift end, a no-punch day today before shift end, a `CONFIG_ERROR`, a past date with a missing row.
  Neither file has a HALF_DAY case today.
- Add the consistency test R-G01 (section 5.9) and make it pass.

**Acceptance.** For the same date and filters, both endpoints return identical present / half-day / absent / leave / not-in-yet / exception counts and the same rate.

### 5.3 R-B02 — display status from the backend
Add `display: {code, label, tone, glyph, provisional}` to `AttendanceDayRead` (`apps/api/src/hrms/modules/attendance/schemas.py`, `attendance_day_to_read` ~line 1795),
from the same classifier as R-B01. Web `lib/attendance/dashboard.ts bucketOf` (line ~284), `components/attendance/attendance-status-badge.tsx`, and mobile
`attendance_summary.dart attendanceBucketOf` (line ~22) read it, falling back to today's logic when absent (old API). Fixes the "Not expected" vs "Holiday" naming difference (AUD-11).
Acceptance: web and mobile label tables match for every status (snapshot test on both sides).

### 5.4 R-B03 — one month figure that matches payroll (AUD-09)
Expose the arithmetic in `service.py` around lines 8040–8260 (the period summary: paid / LOP / leave / weekly-off / half days / OT by class) as a function that runs on
unlocked rows for any employee and month, e.g. `GET /attendance/employees/{id}/month-summary?month=YYYY-MM`, plus a batch form for the HR grid.
Web `summarizeMonth` (`dashboard.ts` ~1188) and `hr-calendar.ts buildHrCalendar` row totals, and mobile `employee_attendance_summary.dart` / `hr_calendar.dart`, use it.
Acceptance: for a closed month, the month card equals the frozen `AttendancePeriodSummary`. Watch performance for the HR grid (one batch call, not N).

### 5.5 R-B05 — work from home (D-AUD-3 confirmed, conditional on this check)
First **verify** what an approved `WFH` regularization writes (scenario S-27): `calculation.py:3657` says "WFH remains a no-op"; `schemas.py:117` accepts `WFH`.
If it writes nothing useful and no stored record, payroll or leave/policy setting uses it (confirmed by the user): remove `WFH` from `_REGULARIZATION_TYPES` and hide Remote tiles in web `kpi-grid.tsx` and mobile `attendance_pulse.dart`.
If the user wants it, implement as an overlay like ON_DUTY (engine bump, needs tests). Do not delete data or migrations.


**Check result (2026-11-21): do NOT remove WFH; hide it in the UI.** What the check found:
- The engine never writes status `WFH` (`calculation.py` resolves no WFH overlay; only `ON_DUTY` is an overlay). Dev DB: 0 `attendance_day` rows with `WFH`, 0 WFH regularization requests.
- An approved `WFH` request applies only its requested punches (like `MISSING_PUNCH`); it sets no work-from-home status.
- Stored policy settings still name it: 4 `regularization_policy_allowed_type` rows allow `WFH`, and 2 `attendance_policy_version` rows set non-default `wfh_requires_punch` / `wfh_uses_shift_hours` (those two columns are stored and edited but never read by the calculation).
- Payroll (`service.py` summary arithmetic) counts a `WFH` day as present, harmless; the DB CHECK constraints also list `WFH`.
- `employee.work_location_type = WFH` is a different thing (where someone works) and is untouched.
Done in R-B05: removed `WFH` from the correction pickers (web dialog, mobile form) and hid the Remote tiles while the count is 0 (web KPI grid, mobile insights). The home dashboard and mobile pulse already hid it at 0. Left alone on purpose: `_REGULARIZATION_TYPES`, migrations, the policy forms (including the two dead WFH flags). Open for the owner: whether to remove those two dead policy flags and the WFH allowed-type rows in a later migration.

### 5.6 R-C01..C03 — "why this result" (after R-B01; the biggest transparency item)
Build a pure backend function `explain(day, policy_version, shift_version, snapshot)` in `apps/api/src/hrms/modules/attendance/explanation.py`, returned on `GET /attendance/days/{id}`
(`router.py:1185`). Shape and wording templates are in `ATTENDANCE_UI_UX_IMPROVEMENT_PLAN.md` §4. Source of facts: `computation_snapshot` keys
(`grace_band_credit`, `hour_band_gap`, `half_day_leave`, `terminal_reason`, `pairing`, `presence`, `breaks`) and the policy version's thresholds; **never recompute** a verdict.
- R-C02: `action.deadline` and `consequence` for INCOMPLETE days from the policy's lock behaviour (`TREAT_ABSENT` default; code ~`service.py:8319-8430`); same words in `reminders.py`.
- R-C03: overtime found / approved / pending and class label from `OvertimeRecord` (payroll pays `ot_minutes_approved`, `service.py:8144-8150`).
Tests: one snapshot test per template, covering each row of matrix section 2. Needs the engine rules settled for the cases it describes; ship settled cases first.

### 5.7 Web and mobile screens (after R-B02, R-B03, R-C01)
- R-D03 one live "worked so far / time left in shift" figure for an open day (web `self-view.tsx`, `day-summary.tsx`).
- R-D04 "Why this result" panel on the web day page and a day drawer; R-E02 the same on mobile `attendance_day_detail_screen.dart`.
- R-D05 / R-E03 calendar redesign: status fill, up to two corner markers (needs action / late-early-OT), split cell for half-day leave, future vs no-record, full legend, day sheet, month header from R-B03. Web `month-calendar.tsx`, `hr-calendar/*`; mobile `my_calendar_screen.dart`, `attendance_calendar_screen.dart` (**the other session is editing the mobile calendar: coordinate, do not overwrite**).
- R-D06 HR: "Not calculated: N" with a Recalculate action (existing `POST /attendance/days/calculate-range`), close-readiness list (days that become absent at lock), freshness line already done.
- R-D07 AP-09: delta chips compare like with like or hide before shift start (`kpi-grid.tsx` ~line 108).
- R-E01 mobile reads backend `display` and month summary. R-E04 today card: time left, break allowance, reason on the blocked punch button. Show `calculated_at` on mobile Insights.
- R-E05 offline punching: **only if the user decides yes** (D-AUD-4). Otherwise skip.

### 5.8 Reports and payroll (after R-B03, R-C02, R-C03)
R-F01 reports and CSV exports state their basis ("whole days" vs "payroll days"); R-F02 finalize preview lists days that will be resolved absent at lock;
R-F03 OT reports show found / approved / pending consistently with payroll's `ot_minutes_*`.

### 5.9 Tests (write alongside each task)
- **R-G01** cross-surface consistency integration test: seed one company with a day of each status/flag; assert summary, overview, month summary and frozen period summary agree; assert web `bucketOf` and mobile `attendanceBucketOf` match the backend through a shared JSON fixture. Write it first (it fails today), then make it pass with R-B01.
- R-G02 Playwright (`apps/web/e2e/`): employee self view while working and after punch-out; holiday day page; HR Today totals vs home dashboard. No attendance e2e exists yet.
- R-G03 run Flutter tests in CI (`.github/workflows/ci.yml` already has a mobile job around line 505; check whether it runs `flutter test`). Touching `.github/` means the user must merge the PR.
- R-G04 link every scenario S-01..S-45 to a test id; R-G05 performance of summary and month summary on 1,000 employees × 31 days (p95 < 500 ms).
- Two scenarios need a **runtime probe before any fix**: S-13 (the same punch submitted twice) and S-44 (a punch during the 09:30 sweep).

### 5.10 Phase A — engine accuracy (blocked on owner decisions)
R-A01..R-A07 (band gaps, no-show under TREAT_PRESENT, late punch after close, schedule change recalc, pay-basis edit recalc, comp-off, part-time bands).
Details and probe ids: `docs/audits/ATTENDANCE_REMAINING_ISSUES_AND_RISKS.md`, `ATTENDANCE_DECISION_SHEET_GROUP_A_2026-11-18.md`.
Any engine change: bump `ENGINE_VERSION` once for the batch, add engine unit tests and one API integration test per case, run the impact query
(`apps/api/scripts/sql/attendance_pre_recalc_snapshot.sql`) on the dev database read-only, and expect a migration review by the user.

## 6. Traps that cost time already

- The engine has **no clock**: an open check-in today is stored as `missing_punch=true` / `INCOMPLETE` (or `ABSENT` under policy). Any "today" display must decide "in progress" itself (web `isDayInProgress`, backend `overview.py`, mobile day screen).
- `computation_snapshot` is shown raw in the web UI today. Do not render it to employees; build the explanation object instead.
- Web `attendance-status-badge.tsx` and `dashboard.ts BUCKET_LABELS` use different words for the same day. Do not add a third.
- Changing a golden image: always compare master vs test image first. Four day-detail goldens were updated for the hidden details tile; do not blanket `--update-goldens`.
- The day page test mocks permissions through a hoisted `auth` object (`page.test.tsx`); reuse that pattern for permission-dependent tests.
- Pydantic response fields added to `AttendanceSummaryRead` need a default (`= None`) so old callers and fixtures keep working.
- `summary.py` documents "No attendance rule lives here": keep rules in the engine; the classifier only groups stored rows.

## 7. Questions to put to the user before or while working

1. ~~Confirm D-AUD-1..3~~ Done 2026-11-20 (see section 4). If the WFH check finds something that uses it, tell the user before removing anything.
2. May the audit documents in this folder be included in the pull request?
3. Is offline punching on mobile wanted (D-AUD-4)?
4. Which Group A decisions (H-01, H-02, H-03, H-04 first) are answered? Without them, stop before Phase A.

## 8. Definition of done for each task

- Code change limited to the task's files; no unrelated refactor.
- Tests added or updated at every layer the task touches (API, web, mobile) and all of them pass with the commands in section 2.
- Lint, format and types clean for changed files (API: ruff, ruff format, mypy; web: tsc, eslint; mobile: flutter analyze).
- Web or mobile layout changes checked in the browser pane or on goldens at 320 / 360 / 390 px.
- A short note in the PR: what changed, what was not verified, and which decision it relies on.
- Update the roadmap's status or add a line to `docs/audits/attendance-complete-audit-2026-11-19/` (a new dated file; do not rewrite the five originals).

## 9. Safety statement for this handoff

Preparing this document changed no code, configuration, schema or data. It is a new file in the audit folder. The uncommitted changes listed in
section 3 came from earlier work in this conversation and are still uncommitted.
