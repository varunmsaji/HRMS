# Web and mobile parity plan

Status: proposed, 3 Nov 2026. Replaces the 2 Nov draft.

**Out of scope (paused by decision):** payroll on mobile (`kPayrollInRelease` stays `false`; web payroll is unchanged) and push notifications (no Firebase, no device tokens, no tray alerts). Everything below must still work without them, so approvals are found in-app (badges and home cards) instead of by push.

**Goal:** an employee or HR user can do the same job on web or mobile. Layout may differ (a grid on web, an agenda on a phone), but the data, rules, permissions, labels and statuses must match.

## 1. Correction to the earlier review

A page-by-page check shows mobile is closer to web than the first review said. These already exist on mobile and need no work: shift breaks and duty blocks (`policy_resources.dart`), shift and policy versions, holidays, calendar exceptions and the single-day lookup (`org_resources.dart`), punch on behalf (`openPunchOnBehalf`), leave encashment, balance adjustment and ledger, roster entries and calendar, attendance insights, onboarding, users, setup, and the employee record sections (employment, assignment, compensation, statutory, bank, documents).

## 2. Parity matrix (what is actually different)

| # | Area | Web | Mobile | Gap |
|---|---|---|---|---|
| G1 | Schedule coverage | `rosters/schedule`: weekly shifts by day, min-staff targets, totals | none | Build |
| G2 | Shift swaps | list, approve, decline (manager) | none | Build, plus API for employee requests |
| G3 | Workforce roster overview | `rosters/grid` (click to edit, coverage totals) | entries list and calendar only | Build a day board |
| G4 | HR attendance calendar | `attendance/calendar` month grid plus detail drawer | team attendance list and insights | Build an agenda |
| G5 | My calendar | `me/calendar` (shifts, leave, holidays) | month card only | Build |
| G6 | Work calendar day grid and change impact | `day-grid.tsx`, `change-impact-dialog.tsx` | one-day lookup only | Build |
| G7 | Holiday year view | `holiday-year-calendar.tsx` | list only | Build |
| G8 | Geofences admin | `attendance-geofences` page | radius field on branch only (to confirm) | Confirm, then build |
| G9 | Attendance dashboard panels | today pulse, breakdown, delta chips, readiness, reports with CSV | insights screen, fewer panels | Align panels, add share |
| G10 | Exports | employees CSV, attendance reports CSV | none | Add via `share_plus` |
| G11 | Mine / Team toggle | per page, now hidden for the company account | per page | Align rule on both |
| G12 | Employee search | server `q` | unverified | Verify, wire |
| G13 | UI consistency | uses theme tokens | 69 hard-coded colors, uneven dark mode | Fix first |
| G14 | Web-only platform console | `/platform/*` | none | Leave as is (not an employee or HR task) |

Items G1 to G10 each need a "same data, same rules" check before closing (Section 6).

## 3. Working rules for every item

1. **One API contract.** Each feature is built against the same endpoint on both apps. If the API has to change, change it first, with tests, then both clients.
2. **Shared fixtures.** Save a real API response for each new endpoint under `apps/mobile/test/fixtures` and use the same JSON in a web test. If the shape changes, both fail.
3. **Same labels.** Status names, reasons and empty states come from the same wording. Put new strings in one place per app, and copy from web where it already exists.
4. **Same permissions.** Gate by the same permission code on both (`ATTENDANCE_VIEW`, `ATTENDANCE_ROSTER_MANAGE`, and so on). Mobile's `nav_entries.dart` mirrors web's `nav-items.ts`; keep that true.
5. **Company account rule.** Accounts with no linked employee never see "my" views on either app (done on web for leave; apply to mobile and re-check attendance, calendar, payslips).
6. **Definition of done:** tests pass on both, goldens reviewed by eye on mobile (320, 390, dark), `tsc` clean on web, one manual run through each flow.

## 4. Work packages

Order: WP0, WP1, WP2, then WP3 to WP8 in parallel pairs.

### WP0: confirm the open questions (0.5 day)
- Does mobile have a geofence management screen (G8)? Check `lib/features/organisation` and the router; `/app/attendance-geofences` is not in `app_router.dart`.
- Does the mobile employee list send `q` to `GET /employees` (G12)?
- Compare the web company dashboard with `dashboard_screen.dart` card by card and add any difference to G9.
- Decision D3 (below) on who can request a swap.

### WP1: mobile theme and tokens (2 to 3 days) (G13)
- Add `headerBar`, `onHeaderBar` and the dashboard accents to `employee_tokens.dart` / `app_colors.dart`, with dark values.
- Replace the 69 literals: `employee_home_screen.dart` (22), `dashboard_screen.dart` (17), `dashboard_design.dart` (12), `face_enrollment_screen.dart` (8), `ui.dart` (3), `dashboard_kit.dart` (3), and the navy bar in `app_theme.dart`.
- Add dark goldens for home, dashboard, attendance and leave. Add a test that fails on `Color(0x` outside `lib/core/theme/`.
- Add `pageTransitionsTheme` and a reusable staggered entrance (mirrors the web dashboard animation).

### WP2: shared pieces on both apps (3 days) (G11, G12, G10)
- Web: extract one `ScopeTabs` component (Mine / Team / Decisions) that hides "Mine" without an employee record. Use it in leave balances, leave applications and attendance.
- Mobile: same rule in `leave_balances_screen.dart`, `leave_applications_screen.dart`, attendance and calendar entry points.
- Mobile: send `q` from the employee list; add debounce.
- Mobile: a `shareFile` helper over `share_plus` for CSV (used by WP7).

### WP3: schedule coverage and swaps (7 to 9 days) (G1, G2, G3)
**API (2 to 3 days).** Today swaps are manager-only: `POST /rosters/swap-requests` needs `ATTENDANCE_ROSTER_MANAGE` and takes both employee ids. Add:
- `POST /rosters/swap-requests/mine` (requester = caller; body `counterpart_employee_id`, `swap_date`, `reason`; both must be rostered that day on different shifts).
- `POST /rosters/swap-requests/{id}/consent` (counterpart only) and `/withdraw` (requester only, while PENDING).
- Manager approve requires `counterpart_consented`. Keep the existing manager create.
- Integration tests: tenant isolation, wrong user, double decision, coverage_ok.

**Web (1 to 2 days).** In `swap-requests.tsx` add "Request a swap" and a consent action for employees, and show consent state. The Schedule coverage page already exists.

**Mobile (4 days).**
- `weekly_schedule.dart` model and `attendance_repository.dart` call to `GET /rosters/weekly-schedule` (params `week_start`, `branch_id`, `department_id`).
- `weekly_schedule_screen.dart`: week picker, three KPI tiles (coverage %, cells below target, pending swaps), a Mon to Sun day strip, per-shift cards with headcount against `min_staff` and a below-target chip, tap for people.
- Swaps: "Request a swap" from a roster day, "My swaps", a consent prompt, and a manager list with approve and decline plus note.
- In-app awareness without push: a badge on the Schedule entry and a home card when a swap needs the user.
- Add nav entry (same permission as Shift Rosters), route, tests, goldens.
- G3: a "Day board" tab on the rosters screen: pick a date, list each shift with who is on it, tap to edit an entry (reuses `openRosterForm`).

### WP4: calendars (5 to 6 days) (G4, G5, G7)
- Mobile "My calendar": `GET /employee-calendar/me?from&to` (same as web `me/calendar`). Month view with shift, leave and holiday markers, tap a day for detail. Reuse `attendance_month_card.dart` styling.
- Mobile HR attendance agenda: date strip, filters (branch, department, status), groups Present / Late / Absent / On leave from `GET /attendance/days`, search via `q`. Tap opens the existing day detail.
- Mobile holiday year view: month tiles with holiday dots, tap to see the day, on the holiday calendar detail.
- Web: add a "My calendar" entry point where mobile has one on the home screen, if missing.

### WP5: work calendar day grid and change impact (4 to 5 days) (G6)
- Check the API behind web `change-impact-dialog.tsx` (which employees or days a calendar change affects) and `day-grid.tsx` (month of day types).
- Mobile: month view on the work calendar detail showing each day's type (working, off, holiday, exception); tapping a day opens the existing exception form; before saving a change, show the same impact summary as web and require confirmation.
- Keep `DayTypeLookup` as the quick check.

### WP6: geofences (2 to 3 days, depends on WP0) (G8)
- If mobile has no management screen: `ResourceConfig` for geofences (list, create, edit, deactivate) with radius and coordinates, plus "use my current location" to fill coordinates (`geolocator` is already present).
- Align validation (radius limits) with web.

### WP7: attendance dashboard and exports (4 to 5 days) (G9, G10)
- Compare web panels with `attendance_insights_screen.dart`; add missing ones that make sense on a phone: today pulse, delta versus last period, period status and readiness, breakdown.
- CSV export on mobile for employees and the attendance report, through the share sheet. Reuse the same column set as web.
- Do not add payroll pieces.

### WP8: web follow-ups so web is not behind (3 to 4 days)
- Roster grid: server-side search and department and branch filters; fetch roster entries only for the 50 visible employees.
- Clear the `react-hooks/set-state-in-effect` lint errors by using the shared load hook (111 today).
- Split the largest pages (`onboarding/[token]` 1077 lines, `shifts/[id]` 930, `pay-runs/[id]` 924, `work-calendars/[id]` 919) into panels, with no behaviour change.

## 5. Schedule

| Week | Work |
|---|---|
| 1 | WP0, WP1, WP2 |
| 2 | WP3 API, WP3 web, WP3 mobile starts |
| 3 | WP3 mobile finishes, WP4 starts |
| 4 | WP4, WP5 |
| 5 | WP6, WP7, WP8 |
| 6 | Parity pass (Section 6), fixes, release candidate |

About 5 to 6 weeks for one developer; WP8 and parts of WP4 and WP5 can run alongside if a second person is available.

## 6. Parity pass before sign-off

For each of G1 to G10, run the same scenario on both apps with the same seed data and compare: counts, statuses, wording, who can see or do what, and the result after a change (for example, approving a swap updates both rosters). Record the result in a checklist in this folder. Any difference is fixed or written down as intentional.

## 7. Decisions still needed

1. **D3, swap requests:** may any employee request a swap with consent and manager approval (recommended), or stay manager-only? This sets the API work in WP3.
2. **Tablet layouts:** skip for now (recommended) or include two-pane admin screens as a later package.
3. **Geofence and day-grid scope:** WP0 will say whether these are full builds or small additions.

## 8. Risks

- **Goldens:** WP1 changes many images. Review them visually; do not regenerate blindly.
- **Swap rules:** the API change alters who can create swaps, so get D3 confirmed first.
- **Without push,** approvers only learn about requests by opening the app. The badges and home cards in WP3 are what make that workable; test them.
- **Hidden payroll code** can drift while paused. Keep its tests running so it stays buildable.
- **Estimates** assume the endpoints behind change impact and geofences already exist. WP0 confirms this.

## 9. Not verified

This plan comes from reading code and routes. Flutter was not available in the session, so mobile was not analyzed or run, and neither app was exercised in a browser or emulator.
