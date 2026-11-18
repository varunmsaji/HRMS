# Attendance page (HR dashboard) UX audit — 18 Nov 2026

Read-only. Nothing was changed. Scope: web `/app/attendance` for HR (org mode), all four tabs.

**Evidence base.** The live page at a 1024 px window with the demo company (21 employees, no attendance rows for 18 Nov), plus the code in `apps/web/src/app/app/attendance/page.tsx` and `components/attendance/dashboard/{today-pulse,kpi-grid,toolbar,whos-in-panel,needs-attention,payroll-readiness}.tsx`.

**Not covered.** Mobile attendance, the employee self view, the Calendar view page, the report tables' contents, and any day that has real punches. Today had no rows, so the list's filled-in state was not seen. Rows marked *(demo data)* may look different with real data; the code path is noted where it matters.

## Status (18 Nov 2026)

**Fixed, uncommitted on `test`:** AP-08, AP-09, AP-11, AP-12, AP-13.
- AP-08 / AP-09: when no employee has a row for the focus day, the pulse says "Attendance for today hasn't been calculated yet." (or "No attendance records for <date>.") and no comparison chips show. Once any row exists the comparison returns. A day that is only partly punched in is still compared with a full day last week; that is not fixed (needs a decision on how to compare).
- AP-11: "Total employees" is no longer drawn as selected.
- AP-12: the Payroll readiness title and company wrap (two lines, full text on hover) instead of being cut off.
- AP-13: the list description ends with "Loaded at HH:MM". This is when the page fetched the figures, not when the attendance was calculated; the summary API returns no calculation time.
- Verified: 173 tests pass (4 new component tests, 2 new page tests), typecheck clean, and checked on the live page. The 3 lint errors in `use-dashboard-data.ts` exist in the committed file too.

**Decisions taken (18 Nov):** D1 morning check, D2 Muster becomes a List/Grid switch, D3 period management moves to Payroll, D4 no live view for now, D5 the five numbers are Present, Absent, On leave, Late, Not checked in.

**Today-tab restructure done, uncommitted on `test`:** AP-01, AP-02, AP-07, AP-10, AP-14, AP-15.
- One summary block: the attendance rate beside five clickable tiles. The "Who's who" chips are gone; "Total employees" is a line of text. Remaining statuses stay behind "More statuses".
- Needs attention sits directly under the summary, full width, with copy that says attendance items cover the range and pending requests are counted whatever their date.
- Payroll readiness is one line, shown only when something blocks the close, validation is blocked, or 3 or fewer days are left.
- The list opens with what HR must fix or chase (missing punch, incomplete, config error, then no record and absent, then late or early out, then the rest). Click Status to return to this order, Employee for A-Z.
- The 21 repeated "Mark present" buttons are replaced by tick boxes plus "Select all N" and "Mark N present", which opens the existing review dialog. Single-day lists only.
- Today tab height on the demo company: 2,717 px to 2,103 px; buttons 59 to 18.
- Verified: 198 tests pass (attendance, me and employees pages), typecheck clean, checked on the live page (dialog opened and closed, nothing saved).

**Filters, Trends and mismatch handling done, uncommitted on `test`:** AP-03, AP-04, AP-05, AP-16 and the new mismatch work.
- Filters: one command bar. Presets and date, then a type-to-find employee box (name or code, first 8 matches, keyboard works, chosen person shows as a pill with a clear button) and the status select, then More filters and Reset. The long employee dropdown is gone. On narrow screens it wraps and the drawer is unchanged.
- Trends: 9 cards to 6 (Departments & branches, Attendance trend, Punctuality, Absence & leave with the weekday chart inside, Work hours, Overtime). Status distribution is removed (the summary tiles drill the same way). The single-day absent / on-leave boxes are removed from Absence & leave (they repeat the Today tiles).
- Mismatch handling, in the list (all dates, all drill-downs): each problem row says what is wrong in one line and offers the fix in place.
  - Employee already raised a correction request: "Review correction request" (or "View" without approve rights) comes first.
  - Check-in with no check-out, or the reverse: "Add punch-out" / "Add punch-in" opens the punch dialog with the employee, direction and the shift's own start or end already filled (never a time in the future).
  - Nothing punched on a working day: "Mark present" opens the existing review dialog.
  - Punched on approved leave: "Keep leave" (needs recompute rights) and "Cancel leave" (goes to Leave).
  - Config error, waiting on approval: "Open day".
  - A banner counts the days that need fixing, with "Show only these".
  - After any fix, the list and the summary totals both reload (before, only the list did).
- Also fixed in passing: the Mark attendance and Record punch dialogs from the header now refresh the totals too.
- Verified: 873 web tests pass (119 files), typecheck clean, lint clean on changed files, checked on the live page (punch dialog opened prefilled and closed without saving).
- Mobile: the month-card golden images (320, 360, 390) were regenerated after the self-dashboard change; the file passes.

**Mobile mismatch handling done, uncommitted on `test`:** same rules and fixes as web (`domain/attendance_mismatch.dart`, `presentation/mismatch_fixes.dart`).
- Team attendance (HR day list): each problem day says what is wrong and offers the fix on the tile (Review correction request, Add punch-in / punch-out with the form opened on the right direction and the shift's own start or end as the time, Mark present, Keep leave / Cancel leave, Open day). A banner counts the days that need fixing with "Show only these". Problem days are listed first; the server's order is kept otherwise.
- Insights, Needs attention: Configuration errors, Missing punches, Incomplete attendance, Work on approved leave and Days pending approval are now tappable and open "Days that need fixing" for the selected range (newest first, same fixes). Late and early-out days are only noted, so they stay as they were.
- Without the rights to fix, a problem day still says what is wrong and offers Open day only. You cannot fix your own day on someone's behalf; that path stays a correction request.
- The Keep leave reason dialog is now one shared function used by the day screen and the lists.
- Caught and fixed on the way: the month card's new Late / Punctuality / Hours cards (added earlier) showed twice on the HR employee profile, which has its own month grid. They are now off there.
- Verified: new tests for the rules (9), the screens (11) and the Needs-attention flags; existing attendance, insights, profile, month-card and golden tests pass.

**Muster and Periods done, uncommitted on `test`:** AP-06 and decisions D2 and D3.
- The page has three tabs now: Today, Trends, Reports. Muster is no longer a tab: the Today list has a List | Grid switch, and Grid is the employee × day status grid (follows the filters; remembered as `?layout=grid`). Clicking a summary tile or a Needs-attention item returns to the list, since those filter it. Old `?view=muster` and `?view=periods` links still work.
- Period panels left the Attendance page. The period list already lived at Attendance Periods (create, finalize, reopen, per-period summary), so nothing there was lost; the "Monthly attendance summary" (payable days, LOP, overtime, late count) moved onto that page, under the list. It is now listed in the sidebar under Leave & Payroll next to Payroll, its back link says Payroll, and the sidebar lights that entry (not Settings) on it. It also stays in the Settings hub and the Settings guide.
- Reports has a one-line pointer: "Closing the month? Periods and the monthly summary are in Payroll → Attendance periods."
- The Company filter moved with it: it was on the Periods tab and is now under More filters (shown only when there is more than one company).
- Dead code removed: `PeriodStatus` (now `monthly-summary.tsx` holds only the summary).
- Verified: 680 tests across the affected folders, typecheck clean, lint clean, checked live (grid switch, legacy links, periods page, sidebar highlight).
- Mobile was not changed: its Insights screen is one scroll of cards, not tabs, so it never had a Muster tab or a Periods tab to merge.

**Not done yet:** the "partly punched in" comparison gap from AP-09. Mobile bulk mark (web has tick boxes plus "Select all"). Everything above is uncommitted.

---

## A. Clutter and repetition

| ID | Finding | Evidence | Effort |
|---|---|---|---|
| AP-01 | The same status counts appear four times on the Today tab: the "Who's who" chips, the KPI tiles, the "More statuses" tiles, and the Status column of the list. Trends adds a fifth, "Status distribution". | `today-pulse.tsx` builds a chip per status with count and %. `kpi-grid.tsx` builds tiles for the same buckets. `page.tsx:559` adds the Status distribution card. | M |
| AP-02 | The Today tab is 2,717 px tall: pulse 216, KPI grid 326, Needs attention 345, list 1,758. The only thing HR must act on (Needs attention) sits under two summary blocks that say the same thing. | Measured in the browser. | M |
| AP-03 | The page puts roughly 250 px of controls (header buttons, date presets, two dropdowns, More filters, Reset) above the tabs, and every tab sits under them. | Screenshot. `toolbar.tsx`. | S |
| AP-04 | The Employee filter is a native `<select>` listing every employee. It will not scale: the page already carries a "names loaded for the first N of M employees" fallback note. | Page text lists all 21 names in the select. `page.tsx:425-431`. | S |
| AP-05 | Trends has 9 cards (1,685 px). Status distribution repeats Today, Leave & absence overlaps the KPI tiles, and "Absence by weekday" showed only "No weekday stands out" *(demo data)*. | Tab text. `page.tsx:534-632`. | M |
| AP-06 | Period state lives in two places: the Payroll readiness card on Today and Attendance periods plus Monthly summary on the Periods tab. The tab is also labelled "Reports" for non-org users. | `page.tsx:490`, `:650-676`, `:461`. | M |
| AP-07 | A "Mark present" button repeats on every no-record row (21 identical buttons), next to a "No record" badge and four empty "—" columns. | Screenshot. | S |

## B. Misleading or inconsistent information

| ID | Finding | Evidence | Effort |
|---|---|---|---|
| AP-08 | Two blocks contradict each other. The pulse says "Nobody was expected to work on this day", while the KPI tile says "Not checked in 21 — Expected to work, no IN punch". On a Wednesday with no calculated rows the pulse treats expected as 0. | Page text, 18 Nov *(demo data; the cause is that no day rows exist yet)*. | S |
| AP-09 | The comparison is partial-today against full-last-week. Present 0 shows a red "−14 vs last Wed" and Late shows "−4", before anyone could have checked in. A morning view will always look bad. | `kpi-grid.tsx:108` computes `now − before` with no time-of-day or "day not started" guard. | S |
| AP-10 | Needs attention is titled "18 Nov — what HR should act on", but its only item (Regularization pending, 6) is not date-scoped. Payroll readiness then lists the same 6 beside it and adds "Counts cover 18 Nov, not the whole period". Two cards say the same thing and neither is clear about its scope. | Screenshot and page text. | S |
| AP-11 | "Total employees" is drawn with a blue selected border by default, so it reads as an active filter. | Screenshot. | S |
| AP-12 | The Payroll readiness card truncates its own content ("November …", "Varun Company …") in the 1/3-width column. | Screenshot at 1024 px. | S |
| AP-13 | The subtitle promises "Who is working", but the list says "Snapshot … not a live presence feed", and no "as of" time is visible. HR cannot tell how stale the numbers are. | Page text. `page.tsx:504`. | S/M |

## C. Missing for daily use

| ID | Finding | Effort |
|---|---|---|
| AP-14 | The list is sorted by name by default. HR's real question is "who needs me": not checked in, late, incomplete, absent. Exceptions should come first, or be one click away. | S |
| AP-15 | There is no bulk action. Marking 21 people present is 21 dialogs. (Mobile has the same open gap: Mark attendance bulk.) | M |
| AP-16 | No search by name in the toolbar. Search exists only inside the list, and the Employee dropdown filters the whole dashboard instead. | S |

---

## Proposed direction (Today tab first)

1. **One summary strip instead of two.** Keep the rate and the five numbers HR acts on (Present, Absent, On leave, Late, Not checked in), each clickable. Drop the Who's who chips; keep the proportion bar as a thin line, or drop it. Remaining statuses go behind "More". Fixes AP-01, AP-02, AP-08, AP-11.
2. **Needs attention first**, full width, above the list. Payroll readiness becomes a one-line banner shown only when the period is close to ending or has blockers, linking to the Periods tab. Fixes AP-02, AP-06, AP-10, AP-12.
3. **Compare only when meaningful.** Show deltas once the shift day has started or has data; otherwise show no chip. Fixes AP-09.
4. **List: exceptions first.** Collapse no-record rows into one "21 not checked in" group with a bulk "Mark present". Show "as of HH:MM". Fixes AP-07, AP-13, AP-14, AP-15.
5. **Toolbar in one row.** Presets, date, name search (typeahead replacing the dropdown), and one Filters popover for status, shift, department and branch. Fixes AP-03, AP-04, AP-16.
6. **Trends from 9 cards to about 5.** Trend, Punctuality (with repeat-late), Absence (weekday plus repeat), Hours and overtime merged, Departments and branches. Drop Status distribution. Fixes AP-05.
7. **Periods tab.** Keep Reports. Payroll period management stays only if you want it in Attendance (decision D3).

## Decisions needed from the owner

- **D1.** Who is the page's main user, and when? Daily morning check (then the Today layout above) or month-end close (then Periods matters more)?
- **D2.** Keep Muster as its own tab, or make it a List / Grid switch on the Today list?
- **D3.** Should period open / close and the monthly summary stay in Attendance, or live under Payroll?
- **D4.** Is a true "who is in right now" view wanted? It needs live punch data, not the calculated snapshot.
- **D5.** Which five numbers matter most in the summary strip?

## Suggested order

1. Quick fixes with no layout change: AP-08, AP-09, AP-11, AP-12, AP-13 (small, safe, visible).
2. Today tab restructure: AP-01, AP-02, AP-10, AP-14, AP-07.
3. Toolbar: AP-03, AP-04, AP-16.
4. Bulk mark (AP-15) together with the matching mobile gap.
5. Trends cleanup (AP-05) and Periods (AP-06) once D2 and D3 are answered.
