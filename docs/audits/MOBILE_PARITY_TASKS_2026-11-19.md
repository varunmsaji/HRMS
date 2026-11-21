# Mobile parity task list (2026-11-19)

Comes from `WEB_VS_MOBILE_PARITY_2026-11-19.md`. Every item is a change to `apps/mobile` only, to bring
the app level with the web redesigns of 2026-11-18. Nothing here is a missing feature: the data and the
actions already exist on mobile. The work is layout and navigation.

Sizes: S = under half a day, M = about a day, L = several days. These are rough guesses, not measured.

## Order and why

Do PAR-01 first: it is self-contained and fixes the most visible difference. PAR-02 to PAR-05 are one piece
of work on one file (`attendance_insights_screen.dart`, 862 lines) and should be done together by one
person, in that order. PAR-06 and PAR-07 are independent. PAR-08 and PAR-09 are small and can go anywhere.

| ID | Task | Size | Needs a decision first? |
|---|---|---|---|
| PAR-01 | One Shift Rosters hub | M | Yes (D1) |
| PAR-02 | Insights split into Today, Trends and Reports | L | Yes (D2) |
| PAR-03 | Rate-and-tiles summary block | M | No |
| PAR-04 | Trends cut to six cards | S | No |
| PAR-05 | Period panels leave Insights | S | Yes (D3) |
| PAR-06 | Type-to-find employee box on Team attendance | S | No |
| PAR-07 | Muster as a list/grid switch | M | Yes (D4) |
| PAR-08 | Fix stale "mirrors web" comments | S | No |
| PAR-09 | Check two endpoint calls web uses and mobile may not | S | No |

## Tasks

### PAR-01. One Shift Rosters hub
**Web:** one navigation with Coverage and Schedule, and inside Schedule a switcher for Week, Month, Day and
List (`components/shift-roster/roster-nav.tsx`).
**Mobile now:** five separate screens. The board, grid and calendar are reachable only through three app-bar
icons on `rosters_screen.dart` (lines 173 to 175). `core/nav/nav_entries.dart` lists "Shift Rosters" (line 89),
"Schedule Coverage" (line 90), "Shift Swaps" (line 91) and, separately, "Roster Calendar" (line 119).
**Do:** one "Shift Rosters" menu entry that opens a hub with Coverage and a Week / Month / Day / List switcher,
reusing the existing screens (`weekly_schedule_screen`, `workforce_roster_screen`, `roster_calendar_screen`,
`shift_board_screen`, `rosters_screen`). Match web's names and its "opens on Coverage" behaviour.
**Keep working:** the old routes (`/app/rosters/board`, `/app/rosters/grid`, `/app/roster-calendar`,
`/app/schedule`, `/app/shift-swaps`), because notifications and links use them; the alias at
`notifications/domain/app_notification.dart:58`; and the permission rules (the board needs the roster,
employee-directory and shift-list grants; the grid needs the roster and employee-directory grants). A view the
user cannot open should not appear in the switcher.
**Done when:** a manager can reach all five views from one entry without hunting for icons; an employee with
only Shift Swaps still sees just that; existing roster tests pass; one new widget test covers the switcher.

### PAR-02. Insights split into Today, Trends and Reports
**Web:** the HR attendance page has three tabs: Today, Trends, Reports (`app/app/attendance/page.tsx`).
**Mobile now:** `attendance_insights_screen.dart` is one long page; Reports is a separate screen
(`attendance_reports_screen.dart`) opened from a card at the bottom.
**Do:** put the existing sections under three tabs. Today: summary, needs attention, payroll readiness, and the
link to the day's list. Trends: the trend cards (PAR-04). Reports: the six reports (reuse the existing screen's
body rather than copying it). Keep each section loading on its own, as it does now (`_section`).
**Done when:** the three tabs render, the selected range and filters carry across tabs, and one failing section
still does not blank the others.

### PAR-03. Rate-and-tiles summary block
**Web:** one block with the attendance rate beside five clickable tiles (present, absent, on leave, late, not
checked in). The headcount is a line of text. Tapping a tile filters the list.
**Mobile now:** `_pulse()` and `_kpis()` in `attendance_insights_screen.dart`, plus `attendance_summary.dart`.
**Do:** match the block, with the same five buckets and wording (`bucketOf` and `BUCKET_LABELS` already mirror
web). Tapping a tile opens Team attendance filtered to that bucket; `attendance_summary.dart` already has
`onBucketTap`.
**Done when:** the five figures match the web for the same day and company, and each tile opens the filtered list.
Update the golden images this changes (`flutter test test/screens_golden_test.dart --update-goldens`, look at
each image, then delete `test/failures/`).

### PAR-04. Trends cut to six cards
**Web:** Trends has six cards: Departments and branches, Attendance trend, Punctuality, Absence and leave
(with the weekday pattern), Work hours, Overtime. The duplicate status distribution and the single-day absent
and leave boxes are gone.
**Mobile now:** separate cards for each of these plus extras.
**Do:** match the six, and drop the duplicates. Do not drop any figure that appears nowhere else.
**Done when:** the Trends tab shows the same six sections, in the same order, as the web.

### PAR-05. Period panels leave Insights
**Web:** Period status and Monthly summary no longer render on the attendance page. They live under Payroll
(`8b6999c`).
**Mobile now:** `_periodStatus()` and `_monthlySummary()` at the bottom of Insights, and `/app/attendance-periods`
as its own route.
**Do:** remove both cards from Insights. Make sure `/app/attendance-periods` (which already uses the `/summary`
endpoint) shows the monthly summary, and list it under the Payroll group in `nav_entries.dart`.
**Done when:** Insights no longer fetches `/attendance-periods` unless something still needs it, and the
periods screen shows the monthly summary.

### PAR-06. Type-to-find employee box on Team attendance
**Web:** a type-to-find box (name or code) replaces a dropdown of everyone.
**Mobile now:** `team_attendance_screen.dart` uses the filter sheet with an employee list (`_openFilter`).
**Do:** use the existing `employees/presentation/employee_picker_sheet.dart` search for the employee filter.
**Done when:** typing part of a name or code finds the person without scrolling.

### PAR-07. Muster as a list/grid switch
**Web:** Muster is a List | Grid switch on the Today list, not its own section.
**Mobile now:** the muster heatmap is a card on Insights (`_heatmap()`, line 363).
**Do:** only if D4 says yes. See the decision below: this overlaps MOB-UX-048 in `MOBILE_UX_NEXT_STEPS.md`.
**Done when:** per D4.

### PAR-08. Fix stale comments
Several mobile files say they "mirror" web pages that no longer exist at that path.
`weekly_schedule_screen.dart:17` points at `rosters/schedule/page.tsx` (now a redirect to the Week view);
`shift_board_screen.dart:13`, `roster_calendar_screen.dart:19` and `workforce_roster_screen.dart:17` point at the
old `board`, `calendar` and `grid` pages (now redirects); `attendance_insights_screen.dart:39` describes the old
page order. Update them after PAR-01 and PAR-02 so they say what is true.

### PAR-09. Check two endpoint calls
The web calls `/shifts/{id}/versions/resolve` and `/employees/{id}/salary/setup/preview`. I found no mobile call
to either. Open `shift_*` and `salary_setup_screen.dart`, decide whether mobile works that out locally, and
either confirm that or add the call. No change is needed if mobile already gets the same answer.

## Decisions needed before building

- **D1 (PAR-01).** One hub with a switcher, or keep separate screens and just add a menu entry for each?
  Recommendation: a hub, because three unlabeled icons are the problem.
- **D2 (PAR-02).** Match the web's three tabs literally, or keep one scrolling page and only reorder? Recommendation:
  tabs. A phone benefits more from tabs than from one 862-line scroll.
- **D3 (PAR-05).** Move the periods out of Insights as the web did? Recommendation: yes, so both apps say the
  same thing. Needs HR to confirm they no longer want them in the attendance view.
- **D4 (PAR-07).** Web's muster grid is wide. `MOBILE_UX_NEXT_STEPS.md` (MOB-UX-048) already plans per-day lists
  instead of grids on phones. Recommendation: do the list as the default, keep the grid as an option, and do it
  once as part of that item instead of twice.

## Rules for whoever builds these

- All edits on `test`, staged by name, then a pull request to `main` (see `AGENTS.md`). Do not touch the files
  under `.github/`.
- Checks: `export PATH=$HOME/flutter/bin:$PATH`, then `flutter analyze` and `flutter test` in `apps/mobile`.
- None of the earlier mobile UX phases has been tried on a phone yet. Add this batch to that same
  "try it on a phone before release" checklist.

## Not on this list

- A web approvals page and the web punch message (PR #64) are web work, covered in the parity report.
- Camera, GPS and push notifications are mobile-only by design.

## Status (2026-11-19)

- PAR-01 to PAR-06: built (PRs #65, #66, #67).
- PAR-08: done. Roster screens now name the web view they match (List, Week, Day, Month, Coverage).
- PAR-09: no change needed. `/employees/{id}/salary/setup/preview` is called on mobile (`salary_setup_screen.dart`, as `'$_base/preview'`; my first search missed it because the path is built). `/shifts/{id}/versions/resolve` is not needed: the server's `/rosters/schedule` already resolves each shift's published version (`schedule_service.py`, "Published version covering `on`"), and no other mobile roster screen shows shift times.
- PAR-07: waiting on D4.
