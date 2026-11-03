# Web / mobile parity: handoff

Written 3 Nov 2026. Say **"start this"** (or "continue the parity work from PARITY_HANDOFF.md") and begin at section 5.

Read first: [MOBILE_PARITY_PLAN.md](MOBILE_PARITY_PLAN.md) (the full plan and the parity matrix G1 to G14). This file records what is done, what is left, how to run things, and the traps.

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

1. **Leave balances picker (mobile).** `lib/features/leave/presentation/leave_balances_screen.dart` loads only the first page of employees for its picker (`listEmployees()`), the same flaw just fixed in the directory. Use `listEmployeesPage` with search. Also, for the company account it opens on the first employee; the web asks you to choose. Make it match.
2. **WP4: calendars (mobile).**
   - "My calendar": `GET /employee-calendar/me?from=&to=` (same as web `me/calendar`; types in `apps/web/src/lib/employee-calendar/types.ts`, month logic in `month.ts`). Month view with shift, leave, holiday markers; tap a day for detail. Reuse `attendance_month_card.dart` styling.
   - HR attendance agenda: date strip plus Present / Late / Absent / On leave groups from `GET /attendance/days` (web: `app/app/attendance/calendar/page.tsx`, `lib/attendance/hr-calendar.ts`), with branch/department filters and server search. Tap opens the existing day detail.
   - Holiday year view on the holiday calendar detail (web: `components/holiday-calendar/holiday-year-calendar.tsx`).
3. **WP5: work calendar day grid and change impact (mobile).** Web: `components/work-calendar/day-grid.tsx`, `change-impact-dialog.tsx`. Mobile today only has the one-day `DayTypeLookup`. First confirm the API behind the impact dialog.
4. **WP6: geofences admin (mobile).** Confirmed missing: mobile only has a radius field on branch. Web page: `app/app/attendance-geofences/page.tsx`, API `/attendance/geofences`. Build a `ResourceConfig`-style screen with "use my current location" (`geolocator` is already a dependency).
5. **WP7: attendance dashboard parity and exports.** Compare web panels (today pulse, breakdown, delta chips, readiness, reports with CSV) with `attendance_insights_screen.dart`. Add a share-sheet CSV helper with `share_plus` (already a dependency) for the employees list and attendance report; use the same columns as web. No payroll pieces.
6. **WP8: web follow-ups.** Roster grid (`rosters/grid/page.tsx`): server-side employee search (`q` exists), branch/department filters, fetch roster entries only for the visible employees. Reduce the `set-state-in-effect` lint errors using the shared load hook (`useApiResource`). Split the large pages (`onboarding/[token]` 1077 lines, `shifts/[id]` 930, `payroll/pay-runs/[id]` 924, `work-calendars/[id]` 919) with no behaviour change.
7. **WP1: mobile colour tokens (held back on purpose).** 69 `Color(0x...)` literals outside `lib/core/theme/` (worst: `employee_home_screen.dart` 22, `dashboard_screen.dart` 17, `dashboard_design.dart` 12, `face_enrollment_screen.dart` 8). Move them to `employee_tokens.dart` / `app_colors.dart` with dark values, add dark goldens, add a test that fails on new literals. Do it when the app can be looked at on a device or emulator, because it moves every golden.
8. **Final parity pass:** for each of G1 to G10, run the same scenario on both apps with the same data and compare counts, statuses, wording, permissions, results. Record it in a checklist in this folder.

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
