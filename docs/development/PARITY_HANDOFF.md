# Web / mobile parity: handoff

Written 3 Nov 2026, updated 8 Nov 2026. Say **"start this"** (or "continue the parity work from PARITY_HANDOFF.md") and begin at section 0.

Read first: [MOBILE_PARITY_PLAN.md](MOBILE_PARITY_PLAN.md) (the full plan and the parity matrix G1 to G14). This file records what is done, what is left, how to run things, and the traps.

## 0a. Audit on 8 Nov 2026 (newest; read first)

A full comparison of the committed code of both apps: routes, every API endpoint each app calls, form field keys, user-facing labels, and the screens side by side.

**At parity:** every web page has a mobile screen except the Settings guide and the platform console (`/platform/*`, web-only by design). Every endpoint web calls, mobile calls too. The policy, shift, organisation, employee and onboarding forms cover the same fields. Attendance insights, calendar change impact, manager-change impact, the attendance day fields and notifications match.

**Closed on 8 Nov (mobile):**

| Gap | Mobile now has | Main files (`apps/mobile/lib/features/attendance/`) |
|---|---|---|
| Corrections on the attendance day | Web's "Corrections" section: the requests raised for that day (tap to open) and "Request a correction" (own day with `REGULARIZATION_REQUEST`, anyone's with `_ON_BEHALF`; emphasised when the day has a missing punch, late, early out or is incomplete; hidden while one is open) | `presentation/attendance_day_detail_screen.dart` |
| One employee's attendance (HR) | Web's attendance profile: today's status, shift, check-in/out, worked, punches; the month calendar with web's nine figures, attendance issues and regularization requests. Opened from the attendance calendar and from names in insights, as on web. The record tab's panel gained quick ranges (default "Last 7 days", as on web) and the range summary | `presentation/employee_attendance_profile_screen.dart`, `presentation/employee_attendance_panel.dart`, `domain/employee_attendance_summary.dart` |
| Schedule coverage | Department and branch filters, web's four KPI cards with web's wording (rostered staff, coverage efficiency, night shift coverage, shift swap requests), the "What is schedule coverage?" note, and "No one is rostered for this week." | `presentation/weekly_schedule_screen.dart`, `domain/weekly_schedule.dart` |

**Still open, mobile behind web:**
- Company dashboard: "Today's Workforce Overview" (date, branch, department filters; late arrivals, not checked in), onboarding queues in pending approvals, quick actions, the month/year leave switch. Growth and the department table stay web-only on purpose (comment in `dashboard_screen.dart`).
- Employee home: recent days, recent leave, requests waiting on HR, worked hours this week. The earlier Home redesign dropped some of these on purpose; ask the owner before adding them back.
- Settings guide (`/app/settings/guide`): no mobile screen.

**Wording drift: fixed on 8 Nov, web's wording kept.** Mobile now uses web's labels on the leave, attendance, overtime, regularization and shift policy forms; the statutory, bank and assignment forms; the grade, branch, department, designation and legal-entity forms; the attendance day ("Calendar day type", "OT classification", "LOP fraction"); and the menu ("Corrections" for employees, "Company Profile"). Where web relies on a section heading mobile doesn't have, the heading is folded into the label ("Limit per day (minutes)", "Employees can ask for themselves", "Days before delivery (maternity, note only)"); "(HH:mm)" is dropped because mobile uses a time picker. Kept on purpose: mobile's "Shift type" (web "Type" under a heading), "Currency (3-letter code)", the legal entity's "Name" (web's "Company name" conflicts with the rework's "Legal Entities"), and "State code". The assignment form also gained web's "Cost centre ID" field. Not yet compared: the public onboarding wizard's labels.

**Waiting on the owner's uncommitted Settings rework:** "Who follows this" on mobile policies (needs the `policy_id` filter); web's new Settings module pages and regrouped menu, which mobile's More hub should follow; the web Shift swaps link in the employee menu.

## 0. State on 7 Nov 2026

A fresh comparison of both apps (routes, and the API endpoints each one calls) found mobile had a screen for nearly every web page but lacked features inside them. These were closed on 7 Nov, each ported from web's committed code with web's wording and rules:

| Area | Mobile now has | Main files (`apps/mobile/lib/`) |
|---|---|---|
| Employee directory | Summary cards, status and record-state filters, designation · department per row, CSV through the share sheet with web's columns | `features/employees/`, `core/export/csv_export.dart` |
| Attendance insights | Today's rate and change from last week, KPIs, payroll readiness, departments & branches, punctuality, absence by weekday, attendance periods, monthly summary; days fetched over the range widened to 14 days as on web | `features/attendance/domain/attendance_pulse.dart` |
| Attendance reports | Web's six read-only reports (search, sort, 15-row pages), from the insights screen | `attendance_reports_screen.dart`, `domain/attendance_reports.dart` |
| Shift delete | In-use check, typed name, reason, acknowledgement | `shift_delete_screen.dart`, `ResourceConfig.guardedDelete` |
| Policy assignments | "Set policies" tab: one group, every policy type, batch save, calendar impact previews | `set_policies_panel.dart`, `domain/policy_coverage.dart` |
| Face enrollment | Company requirement switch above Attendance Policies | `face_enrollment_policy_card.dart`, `ResourceConfig.listHeader` |
| Calendars | Work calendar month view, holiday year view (tap a day to add), guided work calendar setup at `/app/work-calendars/setup` | `features/organisation/presentation/` |

Corrections to earlier notes: web has **no** attendance-report CSV (only employees and pay-run files), so mobile has none either. Section 5 items 2 to 5 and the mobile half of item 8 are done.

Still open:
- "Who follows this" on each policy (mobile): needs the `policy_id` filter on `GET /policy-assignments`, which is in the owner's uncommitted Settings rework.
- Waiting on the same rework: web Shift swaps link in the employee menu (`nav-items.ts`), and mobile menu renames ("Correction Policies", "Rules by Group", "Check a Person's Rules").
- Done 7 Nov: web's employee record now has Identity, Experience, Education and Dependents tabs (`components/employee/record-list-panel.tsx`, `identity-panel.tsx`, `lib/employee/record-sections.ts`).
- Owner decision: web drops the middle name from employee names, mobile keeps it.
- Never `dart format` whole files: the repo uses a long-line hand style and the formatter rewrites untouched code.

## 1. The goal and the decisions already made

- Goal: web and mobile do the same jobs with the same data, rules, permissions and wording. Layout may differ (grid on web, agenda on a phone).
- **Paused by the owner:** payroll on mobile (`kPayrollInRelease = false` in `apps/mobile/lib/core/nav/nav_entries.dart`; leave it) and push notifications (no Firebase, no device tokens).
- **Shift swaps:** any employee may request a swap, the colleague must consent, a manager approves (decided, built).
- **Tablet layouts:** not decided; default is skip.
- Without push, approvers find requests in-app (the Shift swaps screen, and the pending-swaps count on the Schedule screen).

## 2. Done (all committed on `main`, nothing pushed)

| Commit | What |
|---|---|
| `5144650` | API: employee-initiated swaps. `GET /rosters/swap-candidates`, `POST /rosters/swap-requests/mine`, `/{id}/consent`, `/{id}/withdraw`. Approve now needs the colleague's consent (409 otherwise). Withdraw is stored as DECLINED with a note, so no migration. |
| `badc201` | Web: "Request a swap" dialog, Agree / Turn down / Withdraw on swap cards, Approve disabled until consent. |
| `ed5f3b4` | Mobile: Schedule coverage screen (`/app/schedule`) and Shift swaps screen (`/app/shift-swaps`) with request sheet; menu entries; models in `lib/features/attendance/domain/weekly_schedule.dart`, calls in `data/schedule_repository.dart`. |
| `2abf3a3` | Mobile tests updated to the redesigned Home, shell and month card (21 were failing). |
| `1a850d0` | Mobile defect fixes: "Try again" on Home status, leave tile retry, today's provisional ABSENT no longer counted in the month summary, notification bell on the no-record Home, month-card tile labels no longer clipped. |
| `b003591` | Web: shared `ScopeTabs` component on leave balances, leave applications, overtime, regularizations; company account (no employee record) no longer sees "My ..." tabs. |
| `18bab82`, `4714800` | Mobile: server-side employee search (`q`, debounced, "Load more" paging); no "Mine" scope for the company account on leave applications and the request lists. |

Earlier work in the same effort (also committed): web roster grid (click to edit, coverage footer, colours), dashboard entrance animation, attendance insights and HR calendar page, the weekly-schedule API, Azure face provider, employee `q` search API.

## 3. State of the checks (last run)

- Mobile: `flutter test` 986 passed, 2 skipped; `flutter analyze` 1 existing info hint (`employee_home_screen.dart` `use_key_in_widget_constructors`).
- Web: `tsc --noEmit` clean; `eslint` has **121 existing errors** (111 of them `react-hooks/set-state-in-effect`). Do not add new ones; the count must stay 121 or fall.
- API: swap tests pass (`test_weekly_schedule.py`, 5 tests); shift roster and attendance day tests pass.

## 4. Not mine, left alone

Uncommitted in the tree and not part of this work: `apps/web/src/components/landing/landing.css` and `landing.tsx` (modified by the owner), `.dev-logs-start.out`, `docker-compose.vps.yml`, `pending task.md`, `stitch_hrms_employer_decision_dashboard (1)/`. Never include them in a commit unless asked.

## 5. What is left, in order

1. **Done (5 Nov 2026).** Leave balances picker, plus the other defects from the 5 Nov review: manager-change confirmation, calendar change impact review (`change_impact_screen.dart`), payroll hidden on Home and the employee record, placeholder Home labels removed, location check on the attendance policy form, and refreshed contract fixtures with a CI check. Calendar and policy items below that mention change impact or the policy location setting no longer need that part.
2. **WP4: calendars (mobile).**
   - "My calendar": done (`my_calendar_screen.dart`). Working days, weekly offs, holidays and leave, as on web; the API has no shift data for it.
   - HR attendance calendar: done (`attendance_calendar_screen.dart`), a month grid as on web rather than the agenda first planned, because Team attendance already gives the one-day list.
   - Holiday year view on the holiday calendar detail (web: `components/holiday-calendar/holiday-year-calendar.tsx`).
3. **WP5: work calendar day grid and change impact (mobile).** Web: `components/work-calendar/day-grid.tsx`, `change-impact-dialog.tsx`. Mobile today only has the one-day `DayTypeLookup`. First confirm the API behind the impact dialog.
4. **WP6: geofences admin (mobile).** Done (`geofences_screen.dart`): workplaces, extra workplaces per employee, location attempts, and "use my current location" (phone-only; requires 50 m accuracy or better).
5. **WP7: attendance dashboard parity and exports.** Compare web panels (today pulse, breakdown, delta chips, readiness, reports with CSV) with `attendance_insights_screen.dart`. Add a share-sheet CSV helper with `share_plus` (already a dependency) for the employees list and attendance report; use the same columns as web. No payroll pieces.
6. **WP8: web follow-ups.** Roster grid (`rosters/grid/page.tsx`): server-side employee search (`q` exists), branch/department filters, fetch roster entries only for the visible employees. Reduce the `set-state-in-effect` lint errors using the shared load hook (`useApiResource`). Split the large pages (`onboarding/[token]` 1077 lines, `shifts/[id]` 930, `payroll/pay-runs/[id]` 924, `work-calendars/[id]` 919) with no behaviour change.
7. **WP1: mobile colour tokens (held back on purpose).** 69 `Color(0x...)` literals outside `lib/core/theme/` (worst: `employee_home_screen.dart` 22, `dashboard_screen.dart` 17, `dashboard_design.dart` 12, `face_enrollment_screen.dart` 8). Move them to `employee_tokens.dart` / `app_colors.dart` with dark values, add dark goldens, add a test that fails on new literals. Do it when the app can be looked at on a device or emulator, because it moves every golden.
8. **Gaps found by the 5 Nov review, not yet scheduled (mobile):** shift delete with its safety check; setting several policy assignments at once; employee CSV and directory summary cards; company dashboard panels. Web is behind on two: no Shift swaps link in the employee menu, and no dependents or experience sections on the employee record.
9. **Final parity pass:** for each of G1 to G10, run the same scenario on both apps with the same data and compare counts, statuses, wording, permissions, results. Record it in a checklist in this folder.

Known small items from the review, still open: the redesigned Home dropped late/missing-punch chips, the work-location card, and takes the shift only from the work profile (treated as design choices, tests adjusted). Say if any should come back.

## 6. How to run things (this machine)

- **Flutter:** not on PATH. Use `export PATH=$PATH:/home/varun/flutter/bin` (Flutter 3.29.2). In `apps/mobile`: `flutter analyze`, `flutter test` (about 1 to 2 minutes), single file `flutter test test/x_test.dart`. Update goldens only for named tests: `flutter test test/screens_golden_test.dart --plain-name "month_card" --update-goldens`, and look at the images before committing. Failed goldens write to `test/failures/` (generated, delete it, never commit).
- **Web:** in `apps/web`: `npx tsc --noEmit -p .`, `npx vitest run <path>`, `npx eslint src`. This is a newer Next.js; `apps/web/AGENTS.md` says to read `node_modules/next/dist/docs/` before changing Next APIs.
- **API:** Python 3.12 venv at `apps/api/.venv` (do not use `uv run pytest`; a conda Python leaks in). `ruff check` and `ruff format --check` via `.venv/bin/ruff`. `test_shift_window.py` is already unformatted (not mine).
- **API integration tests must NOT run against `hrms_dev`** (the suite refuses, and raw runs truncate dev data; never set `HRMS_TEST_ALLOW_SHARED_DEV`). Use a disposable `hrms_test` database. A helper that does this for one file (save it outside the repo, run `python3 run_one.py tests/integration/modules/attendance/test_weekly_schedule.py` from the repo root; it writes full output to `out.txt` beside itself):

```python
import sys, subprocess, os
sys.path.insert(0, "/media/varun/varun20/work/staff-spectrum/HRMS")
import run_full_tests as r
runner = r.Runner(verbose=True)
try:
    for stage in (r.stage_setup_test_database, r.stage_migrations):
        res = stage(runner)
        print(res.name, res.status)
        if res.status != "PASS":
            sys.exit(1)
    env = os.environ.copy(); env.update(r.BACKEND_ENV)
    env["FACE_PROVIDER_COMPARISON_ENABLED"] = "false"   # the repo .env sets it and breaks Settings
    p = subprocess.run([r.venv_python(), "-m", "pytest", *sys.argv[1:], "-q", "-x", "-p", "no:cacheprovider"],
                       cwd=r.API_DIR, env=env, capture_output=True, text=True, timeout=900)
    open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "out.txt"), "w").write(p.stdout + p.stderr)
    print(p.stdout.splitlines()[-1])
finally:
    r.cleanup_test_database()
```

- Postgres, Redis and MinIO run in Docker (`hrms-postgres`, `hrms-redis`, `hrms-minio`); the test runner expects them up.

## 7. Conventions and traps

- **Commits:** small, separate per area (api / web / mobile / docs), detailed messages, end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Stage files by path, never `git add -A` (the tree holds the owner's uncommitted files). Do not push unless asked.
- **Mobile patterns:** screens read the API through a repository over `ApiClient` (`lib/features/*/data`), models and pure helpers in `domain`, Riverpod providers; generic admin CRUD uses `ResourceConfig` (`lib/core/resource/`); permissions in `lib/core/auth/permissions.dart`; the menu and the route guard come from one table, `lib/core/nav/nav_entries.dart`. Test fakes: `test/support/fake_api_client.dart` (`getList` ignores the query; subclass it to model paging or filtering) and `fake_auth.dart` (`fakeAuth(perms, employeeId: ...)`).
- **Shift times on `GET /shifts` are frozen legacy values** (`ShiftRead.start_time`, `end_time`, `is_night_shift`), so mobile's Shift board shows no times. Web's board still does.
- **Contract fixtures:** after any API schema change, run `apps/api/.venv/bin/python apps/mobile/tool/export_contract_fixtures.py` from the repo root and commit the result; CI fails otherwise. If a new request field is not on the form, add it or list it under `notInForm` in `contract_fixtures_test.dart`.
- **Mobile tests that matter when changing the menu:** `permission_matrix_test.dart` lists the exact employee menu entries.
- **Web patterns:** `apiClient.get/getList/post`, `useLatestRequest` for stale-answer protection, `usePermissions().can("...")`, `user?.employee_id` is null for the company account. Avoid setState directly inside `useEffect` (mount a form only while open, derive from state) so the lint count does not grow.
- **Company account rule:** an account with no linked employee record must never see "my" views (leave, overtime, regularizations, calendar, payslips, attendance). Check this for every new screen on both apps.
- **Swap rules (API):** requester needs a published, different shift than the colleague on that day; date not in the past; one PENDING swap per person per day; only the counterpart may consent; requester or counterpart may withdraw; non-parties get 404; approve needs consent and an unchanged roster.
- The generated `apps/mobile/test/failures/` folder and `out.txt` are throwaway.

## 8. First actions when told "start this"

1. `git status` and `git log --oneline -10` to confirm the state matches section 2; note any new uncommitted files that are not yours.
2. Run `flutter test` and `flutter analyze` (mobile) and `npx tsc --noEmit -p .` (web) to confirm the baselines in section 3.
3. Do section 5 item 1, then item 2 (WP4), committing after each item with tests.
4. Report back with what changed, test results, and anything not verified (neither app has been run on a device or in a browser in this effort).
