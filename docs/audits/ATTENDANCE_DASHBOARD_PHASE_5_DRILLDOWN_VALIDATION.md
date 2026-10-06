# Attendance Dashboard — Phase 5 Drill-Down & Detail Consistency Validation Report

## 1. Executive Verdict

**PASS WITH FINDINGS**

Every KPI-card and status-chart drill-down — the mechanisms that narrow the "Today's attendance" /
"Attendance on `<date>`" list in direct response to a click on a *focus-date* figure — produces
exactly the correct, independently-SQL-verified set of rows, with no date leakage, no filter
leakage, and no cross-tenant exposure. The F-1 fix (terminated employees no longer counted as
"not checked in" on "today") continues to hold under drill-down testing.

However, this phase found one **high-severity, previously-undocumented, confirmed, reproducible
defect (F5-1)**: every "View all →" action in the **Needs Attention** panel for a *whole-range*
item (Missing punches, Incomplete attendance, Late arrivals, Early departures, Days pending
approval, Work on approved leave, Configuration errors) sets the exact same `bucket`/`flag`
drill-down filter used by the focus-date KPI cards — which only ever filters `focusRows`, i.e. the
single focus date (`range.to`). The Needs Attention count itself is computed over the *entire
selected range* (`rangeRows`). The result: clicking "View all" on "Missing punches — 27 days · 22
employees affected" for a week-long range produces a list of **1** employee, not 22, with no
indication that 21 of the 22 affected employees (and 26 of the 27 affected days) have been silently
dropped. This was reproduced twice, independently SQL-verified both times, and is a direct, material
violation of Phase 5's own first and second success criteria ("the list... is exactly the set that
should have produced that number" / "preserves the correct date context").

A second, lower-severity but also confirmed finding (F5-2): the two "return to the dashboard"
affordances reachable from the employee profile page — the in-page "Attendance" breadcrumb link and
the browser's Back button — behave inconsistently. Back restores the exact prior filter/range state;
the breadcrumb link always discards it and lands on a bare, filter-free "Today" view. A related,
lower-severity observation (F5-3): the employee profile page always opens on the real current
calendar month, never the month relevant to the drill-down that led there, so investigating a
historical exception requires an extra manual step every time.

Several further low/informational findings round out a largely sound drill-down layer: the Overtime
*panel* (whole-range) has no in-page drill-down at all (only an external, unparameterized link),
unlike the Overtime *card* (focus-date), which drills correctly in-page; the Trend chart is not
interactive despite the task brief's assumption that trend points are clickable; the Reports panel's
row-level employee names are plain text (not links) in every report except Payroll; and one drill
target (`Repeat absence`) re-scopes the *entire* dashboard population rather than narrowing the list
below, unlike every other drill-down, without the scroll-to-list behavior the others share.

No data was modified. No dashboard or backend code was changed. No commits were made.

## 2. Environment

- Tenant: Validation Co
- Tenant ID: `c8592c12-eaf2-45f9-af98-f5366665a14f`
- User: `hr.admin3@validation.example` (COMPANY_ADMIN)
- Frontend: Next.js dev server, `apps/web`, `http://localhost:3000` (restarted once this phase after
  a stale `.next` cache — caused by this phase's own `npm run build` run into the same `.next`
  directory the dev server was using — produced a stuck "Loading your workspace…" screen; cleared via
  `rm -rf .next` and restarted cleanly. This is routine dev-server hygiene, not an application or
  data change, consistent with the precedent set in Phase 4.)
- Backend: FastAPI dev server (`uvicorn --reload`), `apps/api`, `http://localhost:8000` (untouched,
  left running from a prior session)
- Database: PostgreSQL, `postgresql://hrms:***@localhost:5433/hrms_dev` — read-only `SELECT`s only
- Real wall-clock date at test time: **2026-10-05** (one day past the dataset's last populated day,
  2026-10-04 — expected, per F-1/Phase 3/Phase 4)

## 3. Drill-Down Inventory

| Source | Trigger | Destination | Date Scope Used | Filter Context Behavior | Fresh API Call or Client-Side? | Tested? |
|---|---|---|---|---|---|---|
| KPI card (Present/Absent/Leave/Late/Not-checked-in/Remote/Overtime/On-duty/Half-day/Holiday/Weekly-off/Incomplete) | Click | Narrows "Who's In"/"Attendance on `<date>`" list below, same page | **Focus date** (`range.to`) — correct, matches the KPI's own population | Inherits active Employee/Shift/Status/Entity filters (they were already applied upstream, to `population`) | Client-side (`applyDrillFilters` over already-fetched `focusRows`) | Yes |
| "Total employees" KPI card | Click | Clears any active bucket/flag drill | n/a (clear action) | n/a | Client-side | Yes |
| "Exceptions" KPI card | — | **No drill** — static count only, points reader to Needs Attention | n/a | n/a | n/a | Yes (code + live) |
| Status distribution chart segment | Click | Same mechanism as KPI card (`drill({bucket})`) | Focus date | Same as KPI card | Client-side | Yes |
| Toolbar "Attendance status" select | Select | Identical mechanism to the chart/KPI click (confirms/refines F4-1) | Focus date | Same as KPI card | Client-side | Yes (code-confirmed; live-reconfirmed per Phase 4) |
| Needs Attention — Configuration errors / Missing punches / Incomplete / Work on approved leave / Days pending approval / Late arrivals / Early departures | "View all →" | Narrows the **same** Who's-In/"Attendance on `<date>`" list | **Mislabeled**: item is computed over the **whole range**, but drilling filters only the **focus date** — see **F5-1** | Inherits active population filters only; drill itself ignores the range mismatch | Client-side | Yes — **defect found** |
| Needs Attention — Regularization pending | "Review/View →" | External module `/app/regularizations` | N/A (all-time, per D-2/F4-4, unchanged) | Not carried over (different module) | N/A — external link | Yes (code + reconfirmed) |
| Needs Attention — Overtime awaiting approval | "Review →" | External module `/app/overtime` | N/A (not date-scoped in the link) | Not carried over | N/A — external link | Yes (code) |
| Needs Attention — Payroll period blocked | "Open period →" | `/app/attendance-periods/{id}` (direct ID reference) | N/A — targets a specific period record, not date-derived | Not carried over (different module) | N/A — external link | Yes (code) |
| Who's-In row — employee name | Click | `/app/attendance/employee/{employeeId}` | Profile ignores the dashboard's date/range entirely; always opens on the real current month — see **F5-3** | Not carried over at all | Fresh API calls (`/employees/{id}`, `/attendance/days?employee_id=...`, `/attendance/punches`, `/regularizations`) | Yes |
| Repeat-absence employee name (Leave & Absence card) | Click | **Re-scopes the whole dashboard** via `updateFilters({employeeId})` — a population filter, not a list-narrowing drill | Whole range (repeat-absence itself is a whole-range figure) and now also the focus-date KPIs, both correctly recomputed for that one employee | Sets the dashboard's own Employee filter (persists, unlike bucket/flag drills) | Client-side | Yes (code; spot-checked) |
| Muster heatmap cell | Click | `/app/attendance/{day.id}` (attendance-day detail page) | Exactly that day — immune to range/window mismatches since it fetches by row ID, not by any dashboard state | N/A (independent fetch) | Fresh API call (`GET /attendance/days/{id}`) | Yes |
| Muster heatmap row employee name | Click | `/app/attendance/employee/{employeeId}` | Same as Who's-In row link | Not carried over | Fresh API calls | Yes (code) |
| Trend chart point | — | **Not interactive** — no click handler exists in `trend-chart.tsx` | N/A | N/A | N/A | Yes (code) |
| Overtime card (focus-date KPI) | Click | Narrows Who's-In list | Focus date — correct, matches the OT KPI's own population | Same as other KPI cards | Client-side | Yes — **verified correct** |
| Overtime panel (whole-range section) | — | **No in-page drill** — only "Open overtime records →", an unparameterized link to `/app/overtime` | N/A | Not carried over | N/A — external link | Yes (code) |
| Reports panel rows (Daily/Present-Absent/Late-Early/Hours/Overtime reports) | — | **No navigation** — employee names are plain text, not links | N/A | N/A (reads `rangeRows`/`overtime.data` directly, already correctly scoped) | N/A — read-only, client-side | Yes (code) |
| Reports panel — Payroll report | "Open period" link | `/app/attendance-periods/{id}` | N/A — specific period | Not carried over | N/A — external link | Yes (code) |
| Employee profile — "Full day detail →" | Click | `/app/attendance/{day.id}` | Exactly that one row | N/A | Fresh API call | Yes (code) |
| Employee profile — calendar day cells | Click | `/app/attendance/{day.id}` | Exactly that day | N/A | Fresh API call | Yes (code) |

## 4. KPI Card Drill-Downs

Baseline (today, 2026-10-05, no filters): Total 37, all focus-date KPIs zero, Not-checked-in 37 — 37
employees shown in "Today's attendance" all as "No record yet", consistent with the F-1-fixed
behavior (none of EMP-0013/EMP-0025/EMP-0036 present).

Tested the **Overtime** KPI card drill on range 2026-09-19→09-21 (focus date 21 Sep): the card read
"Overtime 2h 46m · 3 employees · 2h 14m approved". SQL independently confirmed, for `attendance_day`
rows on 2026-09-21 alone: `sum(ot_minutes_detected)=166` (2h46m), `sum(ot_minutes_approved)=134`
(2h14m), `count(*) FILTER (WHERE ot_minutes_detected>0)=3`. Clicking the card produced a drill-down
list of **exactly 3 employees** (Hema Das, Kavya Joshi, Neha Shah) — an exact match. **PASS** — this
card, like every other KPI card, is itself computed from `focusRows`, so its drill-down (also scoped
to `focusRows`) is always self-consistent by construction.

Clicking a different KPI without navigating away never left stale data from a previous click in any
test — every transition (Overtime → Missing-punch-flag → Late-flag, across different ranges)
produced a fully recomputed list and KPI highlight state each time, with the correct `active`/pressed
state following the click (confirmed via the "Clear drill-down" button appearing/disappearing and the
bucket/flag chip in the toolbar updating).

No case was found of a terminated or not-yet-joined employee leaking into a KPI-card drill-down list
(the drill-down source, `focusRows`, is the same already-correctly-scoped row set the KPIs themselves
are computed from — F-1's fix applies upstream of all drill-down filtering, not just to the KPI
numbers).

## 5. Status Chart Drill-Downs

`StatusChart`'s `onDrill` prop calls the page's `drill({ bucket })` — the identical function and
identical `bucket`/`flag` URL-filter mechanism the toolbar's "Attendance status" select and the KPI
cards use (`page.tsx:302`, `kpi-grid.tsx:193`, `toolbar.tsx`). This is not an independent code path;
it is the same drill-down entry point with three different triggers. This **reconfirms F4-1** exactly
as Phase 4 described it (a list-only drill-down, not a population filter) and additionally confirms
that **all three entry points** (KPI click, chart-bar click, toolbar select) converge on one
mechanism with identical scope and identical (correct) focus-date behavior — there is no scenario
where one entry point behaves differently from another for the same bucket. No new or different
behavior was found; this is the same mechanism Phase 4 already characterized, not a new finding.

## 6. Exception Drill-Downs

This is where this phase's central finding, **F5-1**, was found and confirmed twice:

**Test 1** — range 2026-09-28→2026-10-04 (focus date 04 Oct), no filters:
- Needs Attention showed "Missing punches — 27 days · 22 employees affected" (a *whole-range*
  figure, independently confirmed via SQL: `count(*)=27`, `count(DISTINCT employee_id)=22` for
  `attendance_date BETWEEN '2026-09-28' AND '2026-10-04' AND missing_punch`).
- Clicking "View all →" set `flag=missing_punch` and scrolled to "Attendance on 04 Oct — Missing
  punch", which showed **exactly 1 employee (Kavya Joshi)** — the SQL-confirmed count of
  missing-punch rows on **04 Oct alone** (`count(*)=1` for that single date).
- Navigating to Kavya Joshi's own employee profile page independently confirmed she actually has
  **three** missing-punch days inside this exact selected range (01 Oct, 03 Oct, 04 Oct — all
  visible in her profile's "Attendance issues" list) — two of which (01 Oct, 03 Oct) are silently
  absent from the "Missing punch" drill-down list the dashboard itself just produced for this exact
  employee, for this exact range, under this exact filter.

**Test 2** — range 2026-09-19→2026-09-21 (focus date 21 Sep), no filters:
- Needs Attention showed "Late arrivals — 11 days · 11 employees affected" (whole-range; SQL
  confirmed: `count(*)=11`, `count(DISTINCT employee_id)=11` for `is_late` across the 3-day range).
- Clicking "View all →" produced "Attendance on 21 Sep — Late arrivals", showing only the employees
  late **on 21 Sep specifically** (bounded by the page's own Late KPI for that date, SQL-confirmed
  `count(*)=7` for `is_late` on 2026-09-21 alone) — at most 7 of the 11 advertised employees, never
  the 4 who were late only on 19 or 20 Sep.

Both the "Incomplete attendance" (9 days/9 employees, whole-range) and "Work on approved leave",
"Days pending approval", and "Early departures" items in the same Needs Attention panel use the
identical `bucket`/`flag` → `drill()` → `focusRows`-filtered-list mechanism (confirmed by direct
source inspection of `buildAttentionItems` in `dashboard.ts:883-996` and the shared `onDrill` wiring
in `needs-attention.tsx:72`/`page.tsx:200-212`), so every one of them is subject to the same defect —
this is not specific to "Missing punches" or "Late arrivals", it is systemic to every whole-range
Needs Attention item that uses a `bucket`/`flag` drill rather than an external `href`.

**Configuration errors** (CONFIG_ERROR bucket) uses the same mechanism; none occurred in this
dataset in any range tested, so this specific bucket's drill could not be exercised with real data,
but the code path is identical to the others and is subject to the same defect by construction.

See **Finding F5-1** in §17.

## 7. Who's-In / Needs Attention Drill-Downs

"Who's-In" is not a separate list from the focus-date KPI/status-chart drill-down target — it *is*
the same `WhosInPanel`/"Attendance on `<date>`" list every bucket/flag drill feeds into. There is no
separate "Who's In, specifically" entry point distinct from §4/§5/§6 above.

Needs Attention's two D-2/D-3-derived items (Regularization pending, Payroll period blocked) and the
overtime-count item do **not** use the in-page drill mechanism at all — they render an `href` instead
of an `onDrill` button (`dashboard.ts:957-994`, `needs-attention.tsx:63-77`), and navigate to a wholly
separate module (`/app/regularizations`, `/app/overtime`, `/app/attendance-periods/{id}`) with no
date/range/filter context carried across. This is consistent with — and does not change — Phase 4's
F4-4 finding that these two items ignore every dashboard filter; Phase 5 adds the observation that,
unlike the other Needs Attention rows, these three never claim an in-page date scope in the first
place (they don't have a "View all" into the dashboard's own list), so they cannot mislead a viewer
about *this* page's scope the way the bucket/flag items in §6 do — their existing, known limitation is
that the **count itself** is unscoped (D-2/D-3/F4-4), not that a drill-down misrepresents it. This is
a meaningful distinction worth recording for §18: the whole-range items that use `bucket`/`flag` are
*more* dangerous than D-2/D-3 in one specific way — they display a seemingly precise, date-range-aware
number next to a "View all" action that quietly discards the range the moment it's clicked, whereas
D-2/D-3 at least show the same (inaccurate-to-range but at least *internally consistent*) number
regardless of what's clicked.

## 8. Overtime Drill-Downs (card vs panel)

Confirmed the asymmetry predicted by the Phase 3 focus-date/whole-range model, and found it is
*structural*, not just a scope difference:

- **Overtime card** (KPI grid, focus-date): drills in-page into the Who's-In list, filtered to
  `flag: "overtime"` over `focusRows`. Verified exact match against SQL in §4 (3/3 employees,
  166/134 minutes). This card's source is `attendance_day.ot_minutes_detected`/`is_overtime`.
- **Overtime panel** (whole-range section, below the KPI grid): has **no click-to-filter affordance
  of any kind** — not on the four stat tiles, not on the "By day class" bars, not on the trend
  column chart (`overtime-panel.tsx` contains zero `onClick`/`onDrill` wiring). Its only interactive
  element is a single static `Link` to `/app/overtime`, with no query parameters at all — it does not
  even pass the employee/date-range context that led there. This panel's source is the separate
  `OvertimeRecord` table (`data.overtime.data`), not `attendance_day`.
- Because the card and the panel read from two different tables (`attendance_day.ot_minutes_detected`
  vs `OvertimeRecord.minutes_detected`), a drill into the card can never show "pending/approved/
  rejected" status (that concept only exists on `OvertimeRecord`), and the panel has no drill at all
  to view the underlying days. An HR user who wants to click from "6 pending" (panel) to the actual
  pending records cannot do so from this page — they must follow the static link to the unfiltered
  `/app/overtime` list and search manually. This is a usability gap, not a correctness defect (no
  wrong data is ever shown), and is recorded as an informational finding (F5-4).
- Employee counts were independently SQL-verified for the card (§4) and match exactly; the panel's
  pending/approved/rejected counts were previously SQL-verified in Phase 3 (§12, unchanged since no
  code in this area has been touched) and were spot-confirmed unchanged in this phase's Test 1/Test 2
  ranges (6 pending/28-Sep-04-Oct Needs-Attention row and 2 pending/19-21-Sep row, both reflecting the
  OT panel's own range-scoped figures, both matching the "Overtime awaiting approval" Needs-Attention
  count for the same range).

## 9. Employee Profile Page Consistency

Visited Kavya Joshi's profile (`/app/attendance/employee/f90a2770-...`) via the Missing-punch
drill-down in §6. Findings:

- **Per-day consistency**: her profile's "Attendance issues" list showed `04 Oct: Not expected /
  Missing punch`, `03 Oct: On leave / Missing punch`, `01 Oct: On leave / Missing punch` — the 04 Oct
  entry is exactly consistent with what the dashboard's own drill-down showed for her (status "Not
  expected", "Missing punch" badge) on that date. No divergent/independently-recomputed figure was
  found for the one day both pages agreed to describe.
- **Date-context loss on arrival (F5-3)**: the profile page opened defaulting to **October 2026**
  (the real current calendar month, `today.slice(0, 7)` in `employee/[employeeId]/page.tsx:44`) —
  not September 2026, not the dashboard's selected range (28 Sep–04 Oct), and not any date carried
  from the drill-down that led here. This happens to overlap the drill-down's range in this specific
  test case (the range spanned into October), but it would not for a drill-down entirely inside a
  past month — the profile would still silently open on the *current* month, requiring the viewer to
  manually change the "Month" input to see the period they were actually investigating. The profile
  page takes no query parameters at all from its caller (confirmed: the Link in `whos-in-panel.tsx`,
  `muster-heatmap.tsx`, and `absence-insights.tsx` all construct a bare `/app/attendance/employee/
  {id}` URL with no date/range/filter information).
- **Origin independence**: the profile page's own content depends only on `employeeId` (from the
  route) and its own internal `month` state — never on how the link was reached. Since no drill-down
  origin (KPI click, Who's-In row, muster-heatmap row, repeat-absence click) passes any extra
  parameter, there is no origin-dependent inconsistency possible by construction — every origin leads
  to byte-identical initial profile content for the same employee. This satisfies Phase 5's "no
  origin-dependent inconsistency" criterion, though only because none of the origins attempt to pass
  context in the first place (there is nothing to be inconsistent *about*).
- **Employment-validity reflection**: not independently re-tested this phase for a terminated
  employee's profile page specifically (the F-1 remediation report and Phase 4 already exercised this
  for the dashboard's own population; the profile page's own "Today" section already correctly shows
  "No attendance record for today yet." for any employee/day with no row, and its month calendar
  correctly shows "no record" for dates outside the fetched window — no separate termination-specific
  code path exists on this page beyond what `GET /attendance/days?employee_id=...` already returns,
  which is itself the same server-side, employment-span-gated row generator Phase 3/F-1 already
  validated). No discrepancy was found or expected.
- **Return-to-dashboard inconsistency (F5-2)**: see §17 — confirmed live. Browser **Back** from the
  profile page restored the exact prior URL (`?range=custom&from=2026-09-28&to=2026-10-04&
  flag=missing_punch`), with all filters and the drill-down intact. Clicking the in-page
  **"Attendance" breadcrumb link** instead navigated to the bare `/app/attendance` (today, no
  filters) — confirmed directly via `window.location.href` before/after each action.

## 10. Reports Panel Drill-Downs

Contrary to the task brief's assumption of "expandable rows or detail links," the Reports panel
(`reports-panel.tsx`) has **no row-level navigation in five of its six reports** (Daily attendance,
Present/absent, Late/early, Work hours, Overtime) — employee names are rendered as plain `name(...)`
text via a local helper, never wrapped in a `Link`, confirmed by reading every `ReportTable` column
definition in the file (none use `<Link>`; compare to `whos-in-panel.tsx` and `muster-heatmap.tsx`,
both of which do). The only exception is the **Payroll attendance** report, which has one link —
"Open period" → `/app/attendance-periods/{id}` — scoped to the specific period record, not to any
individual employee row.

This means Reports panel rows cannot be drilled into at all in the sense Phase 5 is testing (no
navigation exists to verify date/filter-context preservation for, because there is no navigation).
What *can* be verified is that the report rows themselves are correctly scoped: all five
non-Payroll reports read directly from `rows` (= `rangeRows`, the whole-range, already-filtered
population) or `data.overtime.data`, both already proven correct by Phase 3's independent SQL
cross-checks, and this phase's own Test 1/Test 2 SQL checks (§6) which used the identical
`attendance_day` predicates the Reports panel's own `perEmployee`/`body` logic uses. No separate
computation path exists in Reports that could diverge from the dashboard's own figures — it is a
pure read-only view over data already validated elsewhere on the same page load.

Recorded as **Finding F5-5** (informational/low): employee names are clickable in some dashboard
surfaces (Who's-In, muster heatmap) and plain text in others (five of six Reports panel tables) —
an inconsistency in affordance, not a data-correctness defect.

## 11. Heatmap / Trend Drill-Downs

- **Muster heatmap cells**: each cell is a `Link` to `/app/attendance/{day.id}` — a direct reference
  to that exact `attendance_day` row's primary key, fetched independently via
  `GET /attendance/days/{id}` server-side (`attendance/[id]/page.tsx:60`). This makes muster cells
  immune by construction to every class of date/filter-scope defect found elsewhere in this phase:
  there is no client-side re-derivation of "which date does this cell mean" that could go wrong,
  because the link target is the row's own ID, not a reconstructed date/employee pair. Verified
  directly: Kavya Joshi's muster row and her profile's own calendar both link to the identical
  attendance-day IDs for the same dates (e.g. `04 Oct → decbe87f-04db-40e3-b6a3-aac463e831d4`
  appeared identically from both the muster heatmap and her own profile calendar). **No defect.**
  Context-window cells (the extra days before the selected range, shown only to give the heatmap/
  trend visual context per Phase 3's model) are exactly as clickable and exactly as correctly-scoped
  as in-range cells, since the scoping mechanism (fetch-by-ID) does not distinguish them. Clicking
  one does not alter the dashboard's own range/KPI state (it navigates away to a separate page
  entirely), so no corruption of whole-range totals is possible via this path.
- **Trend chart points**: **not interactive**. `trend-chart.tsx` contains only a metric selector
  (`NativeSelect`) and a daily/weekly toggle; the `LineChart` component it renders
  (`charts.tsx`) takes no click handler. The task brief's assumption that "a trend chart point" can
  be clicked into a detail view does not hold for the current implementation — there is no drill-down
  to test here, and no off-by-one date-boundary risk to check via clicking, since there is no click
  target. (Phase 3 already separately validated the trend's date-axis boundaries are exact, including
  no timezone off-by-one — unaffected by this.)

## 12. Date-Range Boundary Drill-Downs (join/termination/F-1 regression)

- **(a) 2026-09-19→09-21** (crosses EMP-0013/EMP-0025 termination, LWD 09-20): Total Employees
  correctly read **38** (40 − 2 terminated), matching Phase 3's Test H exactly. Drilled "Late
  arrivals" (whole-range, 11/11) and "Overtime" (KPI card, focus-date, 3/3) — both produced
  correctly-scoped-to-their-own-definition lists (focus-date for the KPI card per §4; the
  whole-range Needs-Attention item exhibited the same F5-1 mismatch described in §6, unrelated to
  the termination boundary itself). Neither EMP-0013 nor EMP-0025 appeared in either drill-down list
  (neither had a late arrival nor overtime on 21 Sep in this dataset) — no case of a terminated
  employee's row leaking into a drill-down for a date after their LWD was found.
- **(b) 2026-09-29→10-01** (crosses EMP-0036 termination, LWD 09-30): not independently re-walked
  this phase beyond what Phase 3/Phase 4 already established (Total 37 on focus date 01-Oct, her
  29/30-Sep rows correctly included in whole-range panels, correctly excluded from the focus-date
  population) — no code in the drill-down path has changed since those phases validated this
  boundary, and this phase's own Test 1 range (28 Sep–04 Oct) already spans the same boundary with
  the same (correct) result for Total Employees (37).
- **(c) 2026-09-14→09-16** (crosses the 2026-09-15 join date): not independently re-walked this phase
  (Phase 3 §7 and Phase 4 §15 already exhaustively validated no pre-join leakage into any KPI, list,
  or chart, under both the unfiltered population and the Employee filter) — no drill-down-specific
  code exists that could reintroduce this defect, since drill-downs filter the same already-correctly
  -scoped `focusRows`/`rangeRows` the KPIs themselves use.
- **(d) 2026-10-04 alone** (the exact F-1 regression scenario): reconfirmed via this phase's own Test
  1 (range ending 04 Oct, viewed as part of a 7-day range) — Total Employees 37 on the 04-Oct focus
  date (not 40), with the Who's-In/"Attendance on 04 Oct" list showing employee rows only, no
  "no-record" entries (since 04 Oct is historical, not "today", the `employeesWithoutRecord()`
  inference correctly never runs for it) — consistent with Phase 3 Test A and the F-1 remediation's
  own Phase-3-revalidation table. **No regression.**

## 13. Empty-State Drill-Downs

Two legitimate zero-result drill-downs were produced and verified clean:

1. **Holiday KPI card** (count 0) on range 2026-09-19→09-21 (no holiday in this 3-day window):
   clicking it produced "No attendance days match these filters." in the Who's-In panel — no stale
   rows from the prior drill-down (the panel had just shown the Overtime-flag 3-employee list
   immediately before this click), no loading spinner stuck, and the KPI grid above continued to
   correctly show the real (non-zeroed) population figures. **Clean.**
2. **2026-10-05 "Today" baseline** (re-confirmed from this phase's very first load, and previously
   established in Phase 3 §15/Phase 4 §13): zero attendance records for the live "today" view render
   explicit empty-state text ("No attendance records for this date." in the status chart) and
   "No record yet" rows (not a misleading non-empty or stale list) throughout — carried over from
   prior phases' testing, re-observed as still correct at the start of this phase's own session.

No instance of a stale previous-click's data surviving into a legitimate empty drill-down was found
in any transition performed this phase.

## 14. Tenant/Security Scope

- **Employee profile endpoint** (`GET /v1/employees/{id}`, used by the profile page and indirectly by
  every Who's-In/muster-heatmap employee link): the router handler requires
  `Depends(get_tenant_context)` + `Depends(require_permission(EMPLOYEE_VIEW))` and passes
  `tenant.company_id` explicitly into `EmployeeService.get_employee(...)` (confirmed by reading
  `apps/api/src/hrms/modules/employee/router.py:157-167`) — the service, not the client-supplied ID
  alone, determines scope.
- **Attendance-day detail endpoint** (`GET /v1/attendance/days/{id}`, used by every muster-heatmap
  cell and the employee profile's "Full day detail" link): identically structured —
  `Depends(get_tenant_context)` + `Depends(require_permission(ATTENDANCE_VIEW))`, with
  `tenant.company_id` passed into `AttendanceDayService.get_attendance_day(...)`
  (`apps/api/src/hrms/modules/attendance/router.py:911-924`).
- **Live probe** (read-only, via the already-authenticated Validation Co session, reusing the same
  pattern Phase 4's §18 used): requested `GET /v1/employees/a471825d-5281-4958-a4bf-33859b5e7f3f`
  (a real, pre-existing cross-tenant employee ID belonging to "Demo Company A", the same ID Phase 4
  already identified and tested) — returned **HTTP 422 `INVALID_VALUE`**, not the other company's
  employee record and not an ambiguous 200/404 that could be mistaken for "not found within scope."
  A second probe against a syntactically-valid but non-existent attendance-day ID returned the same
  422 shape. No `hrms_dev` data showed any other tenant's `attendance_day` rows exist at all (`SELECT
  count(*) FROM attendance_day ad JOIN employee e ON e.id=ad.employee_id WHERE e.company_id <>
  'c8592c12-...'` → `0`), so a genuine cross-tenant *attendance-day* ID could not be constructed from
  this dataset; the employee-ID probe plus the identical dependency-injection pattern on both
  endpoints is the strongest evidence obtainable without fabricating data.
- No scenario was found, across any drill-down surface (muster-heatmap link, Who's-In link, employee
  profile fetch), where a value sourced from the dashboard's own already-tenant-scoped API responses
  could resolve to another company's record. **No security issue found. PASS.**

## 15. Network Behavior

- Every KPI/status-chart/Needs-Attention `bucket`/`flag` drill-down is **100% client-side** — it only
  ever updates URL query params and re-filters `focusRows`/`rangeRows`, both already held in memory
  from the page's own `GET /v1/attendance/days` fetch. No additional network request is triggered by
  any of these drills (confirmed via `read_network_requests` across the Test 1/Test 2 drill
  sequences — the only requests observed around each click were the page's own unrelated polling/
  no new attendance-related GETs appeared).
- Navigating to the employee profile page (`/app/attendance/employee/{id}`) triggers **four fresh,
  independent API calls** (`GET /employees/{id}`, `GET /attendance/days?employee_id=...`,
  `GET /attendance/punches?employee_id=...`, `GET /regularizations?employee_id=...`) — none of them
  carry any parameter derived from the dashboard's selected range/filters (confirmed by source
  inspection of `employee/[employeeId]/page.tsx:48-73`; the `date_from`/`date_to` sent are always
  derived from the profile's own `month` state, defaulting to the real current month per F5-3).
- Navigating to a muster-heatmap cell or "Full day detail" link triggers exactly one fresh
  `GET /attendance/days/{id}` call, parameterized only by the row's own ID — no range/filter state is
  or could be involved.
- No duplicate or stale-response race was observed in any of this phase's drill-down transitions.

## 16. Findings

### F5-1 — HIGH — Needs Attention "View all" drill-downs for whole-range items silently narrow to the focus date only, dropping most of the affected employees/days without any indication
- **Drill-down surface**: Needs Attention panel — Missing punches, Incomplete attendance, Late
  arrivals, Early departures, Days pending approval, Work on approved leave, Configuration errors
  (every item that renders a "View all →" button rather than an external `href`).
- **Description**: These items are computed via `buildAttentionItems({ rows: rangeRows, ... })`
  (`page.tsx:174-183`) — a count over the *entire selected date range*. Clicking "View all" calls the
  exact same `drill({ bucket, flag })` function the focus-date KPI cards use
  (`needs-attention.tsx:72`), which sets a URL filter consumed only by `applyDrillFilters(focusRows,
  filters)` (`page.tsx:149`) — `focusRows` being `rowsOn(population, range.to)`, i.e. **only the last
  day of the range**. There is no code path that routes a Needs-Attention whole-range drill into
  `rangeRows` instead.
- **Expected**: A drill-down into a figure labelled "27 days · 22 employees affected" for a
  user-selected range should produce a list of (some reasonable representation of) those 22
  employees/27 days — or, at minimum, should not silently present a different, far smaller result set
  under the identical label and heading style used for a correctly-scoped focus-date drill.
- **Actual**: Reproduced twice, independently SQL-verified both times:
  - Range 28 Sep–04 Oct: "Missing punches — 27 days · 22 employees affected" → "View all" → list of
    **1** employee (Kavya Joshi). Her own profile page confirms she alone has 3 of the 27
    advertised days (01, 03, 04 Oct) inside this exact range — 2 of her own 3 matching days are
    missing from a drill-down ostensibly about her.
  - Range 19–21 Sep: "Late arrivals — 11 days · 11 employees affected" → "View all" → list bounded by
    the single-day Late KPI (7 on 21 Sep alone, SQL-confirmed) — at most 7 of the 11 advertised
    employees, never those late only on 19/20 Sep.
- **Evidence**: §6 above; SQL: `SELECT count(*), count(DISTINCT employee_id) FROM attendance_day ad
  JOIN employee e ON e.id=ad.employee_id WHERE e.company_id='c8592c12-...' AND attendance_date
  BETWEEN '2026-09-28' AND '2026-10-04' AND missing_punch` → `27, 22`; same predicate restricted to
  `attendance_date='2026-10-04'` → `1`. Live UI: "Attendance on 04 Oct — Missing punch" → 1 row.
- **Impact**: High. This is the one class of defect in this phase that directly violates Phase 5's
  own definition of success ("the list... is exactly the set that should have produced that number").
  An HR user investigating "22 employees with missing punches this week" via the obvious, only
  available UI action will be shown 1 employee and may reasonably (and wrongly) conclude the issue is
  resolved or trivial, when 21 other employees' missing-punch days are not shown anywhere reachable
  from this click. This is more actionable and more dangerous than D-2/D-3 (§7) precisely because it
  *looks* like a correctly-scoped, standard drill-down (same visual treatment as every correct KPI
  drill) rather than an openly-external, differently-styled link.
- **Recommendation** (not implemented): either (a) route whole-range Needs-Attention drills into a
  `rangeRows`-filtered list/table (which would need its own date column, since results could span
  multiple days — the current Who's-In list has no date column, only a single implicit focus date),
  or (b) scope these Needs-Attention items themselves to the focus date instead of the whole range
  (changing their meaning), or (c) at minimum, suppress or relabel the "View all" action for
  whole-range items so it cannot be mistaken for a complete drill-down (e.g. "View on `<focus date>`
  only (`<n>` of `<total>`)").

### F5-2 — MEDIUM — The employee profile page's two "return to dashboard" paths (browser Back vs. the in-page breadcrumb link) behave inconsistently
- **Drill-down surface**: Employee profile page (`/app/attendance/employee/{employeeId}`).
- **Description**: The profile page's "← Attendance" breadcrumb is a plain `<Link href="/app/
  attendance">` with no query string (`employee/[employeeId]/page.tsx:80-83`). The dashboard's own
  filter changes use `router.replace` (confirmed in Phase 4, F4-6), so browser Back from the profile
  page lands on the single history entry holding the dashboard's last filter state.
- **Expected**: Both affordances for "go back to the attendance dashboard" should either both
  preserve the prior filter/range state, or both reset it — Phase 5's brief explicitly allows either,
  provided it is consistent.
- **Actual**: Verified live, from the identical starting state (`?range=custom&from=2026-09-28&
  to=2026-10-04&flag=missing_punch`): browser **Back** restored that exact URL and filter state;
  clicking the **"Attendance" breadcrumb link** instead navigated to the bare `/app/attendance`
  (today, all filters cleared).
- **Evidence**: §9; `window.location.href` captured immediately after each action.
- **Impact**: Medium — a user who drilled several steps deep (custom range + employee/shift filter +
  bucket/flag drill) before clicking into an employee profile will lose all of that state if they use
  the in-page breadcrumb instead of their browser's Back button, with no visual cue that the two
  "back" options differ.
- **Recommendation** (not implemented): make the breadcrumb link use `router.back()` (or otherwise
  carry the referring dashboard URL), so both paths behave the same way.

### F5-3 — LOW — Employee profile page always opens on the real current calendar month, never the month relevant to the drill-down that led there
- **Drill-down surface**: Employee profile page, reached from any dashboard drill-down.
- **Description**: `month` state initializes to `today.slice(0, 7)` (`employee/[employeeId]/
  page.tsx:44`) regardless of which date/range on the dashboard the viewer was investigating; no
  caller passes a date hint.
- **Expected/Actual**: Consistent (always resets to the current month, from every origin) but
  potentially surprising: investigating a historical exception always requires one extra manual
  "Month" change on arrival.
- **Evidence**: §9 — Kavya Joshi's profile opened on October 2026 while the dashboard's range that
  led there was 28 Sep–04 Oct; the overlap in this specific test masked the issue somewhat, but a
  drill-down entirely inside a past month (e.g. August) would open on October regardless.
- **Impact**: Low — no data is wrong, only an added click; every origin is consistent with every
  other (§9), satisfying Phase 5's "no origin-dependent inconsistency" bar, just not the "preserves
  the correct date context" bar as well as it could.
- **Recommendation** (not implemented): pass the dashboard's focus date (or the relevant attendance
  day's date, when known) as a query parameter and default `month` to it when present.

### F5-4 — INFORMATIONAL — Overtime panel (whole-range) has no in-page drill-down; only the Overtime card (focus-date) does
- **Drill-down surface**: Overtime section (card in the KPI grid vs. panel below Needs Attention).
- **Description/Evidence**: see §8. The card drills correctly (verified exact SQL match, §4); the
  panel's only interactive element is a static, unparameterized link to `/app/overtime`.
- **Impact**: None on correctness (no wrong data shown); a usability gap — clicking "6 pending" in
  the Overtime panel cannot take a viewer to those 6 records from this page.
- **Recommendation** (not implemented): none required; could add `href="/app/overtime?status=
  PENDING&date_from=...&date_to=..."` if/when the overtime module supports query-param pre-filtering.

### F5-5 — LOW / INFORMATIONAL — Employee names are clickable in some dashboard surfaces, plain text in others
- **Drill-down surface**: Reports panel (five of its six report tables) vs. Who's-In panel / muster
  heatmap (both link employee names to the profile page).
- **Description/Evidence**: see §10.
- **Impact**: None on correctness — Reports panel figures are independently proven accurate; this is
  purely an affordance/consistency gap.
- **Recommendation** (not implemented): link employee names in the Reports panel's tables to the
  employee profile page, for consistency with the rest of the dashboard.

### F5-6 — INFORMATIONAL — Trend chart points are not interactive, contrary to the validation brief's assumption
- **Drill-down surface**: Attendance trend chart.
- **Description/Evidence**: see §11 — no click handler exists on `LineChart`/`TrendChart`.
- **Impact**: None — this is a documentation/expectation correction, not a defect. There is no
  date-boundary or scope risk to report for a drill-down that does not exist.
- **Recommendation**: none required of the application; future test briefs for this dashboard should
  not assume trend points are clickable.

### F5-7 — INFORMATIONAL — "Repeat absence" employee click re-scopes the whole dashboard (a population filter), unlike every bucket/flag drill, and does not scroll to show the effect
- **Drill-down surface**: Leave & Absence card, "Repeat absence" list.
- **Description**: `onDrillEmployee` calls `updateFilters({ employeeId: id })` (`page.tsx:345`) — the
  Employee *population* filter, which re-scopes the entire page (KPIs, charts, Needs Attention,
  trend, heatmap, reports), not just the Who's-In list, and persists until explicitly cleared/reset
  — unlike every `bucket`/`flag` drill in §4–§7, which only narrows the one list below and is clearly
  signposted via the "Clear drill-down" button and an automatic scroll to the Who's-In section
  (`page.tsx:209-212`). Clicking a repeat-absence name does **not** scroll anywhere, so the effect
  (the whole page silently re-scoping to one employee) is easy to miss.
- **Expected/Actual**: Functionally correct (verified by code: the Employee filter composes exactly
  as Phase 4 already validated for every other Employee-filter entry point) but behaviorally
  inconsistent with every other click target on this page that is visually presented the same way
  (a clickable name inside a card).
- **Impact**: Low — no wrong data, but a viewer could click a repeat-absence name expecting a
  focused list (like every other click on this page) and be surprised to find the entire dashboard,
  including the date-range-independent Needs Attention items, now describes only that one employee.
- **Recommendation** (not implemented): either scroll to the toolbar's Employee chip on click (so the
  re-scoping is visible), or show a confirmation/toast, or change this to a `bucket`/`flag`-style
  list-only drill if that was the original intent.

## 17. Relationship to Prior Findings

- **F-1** (terminated employees miscounted as "expected to work today") — **remains fixed**. Every
  drill-down tested this phase inherits `focusRows`/`population`, both already gated by
  `isEmployedOn()` upstream of any drill-down filtering; no drill-down surface reintroduces or
  bypasses this check. Reconfirmed directly: "today" (2026-10-05) baseline showed Total 37/
  Not-checked-in 37 with none of EMP-0013/EMP-0025/EMP-0036 present, and the 2026-10-04 boundary
  (§12d) showed the correct historical figure (37, no "no record" inflation) consistent with the F-1
  remediation report's own Phase-3-revalidation table.
- **D-1** (employee.status/is_active not kept in sync with termination) — unaffected by this phase;
  no drill-down surface reads `employee.status`/`is_active` directly for scoping (all derive from
  `isEmployedOn()`'s `employment_joining_date`/`employment_last_working_day` fields, per the F-1
  fix). Remains an out-of-scope, documented residual gap exactly as the F-1 remediation report left
  it.
- **D-2 / F4-4** (Regularization pending — all-time, unscoped by date or any filter) — **untouched,
  reconfirmed**. This phase additionally clarifies (§7) that this item's drill-down (an external
  `href`, not an in-page `bucket`/`flag` drill) cannot exhibit F5-1's specific defect, because it
  never claims an in-page date scope to begin with — its problem remains exactly what D-2/F4-4
  already described (the *count* is unscoped), not a drill-down inconsistency.
- **D-3 / F4-2 / F4-3** (Payroll period blocked — not date-scoped; legal-entity-scoped only when
  filtered) — **untouched, reconfirmed**. Its drill-down (`/app/attendance-periods/{id}`) targets a
  specific period record directly, so it is immune to F5-1's class of defect for the same reason as
  D-2's link.
- **F4-1** (toolbar "Attendance status" is a list-only drill-down, not a population filter) —
  **reconfirmed and extended**: this phase's source-level trace (§5) confirms the toolbar select, the
  status-chart bars, and every KPI card all converge on the exact same `drill()` function — not
  merely "behaves like" a drill-down, but is *literally the same code path*. No new finding; this
  strengthens F4-1's existing evidence rather than changing it.
- **F4-4** (Employee/Shift filters are true population filters; Regularization/Payroll-blocked ignore
  them) — unaffected; this phase's drill-down testing (§6, §12) always inherited whichever population
  filters were active, exactly as F4-4 already described, with no new interaction found between
  population filters and the newly-discovered F5-1 drill-down defect (F5-1 occurs identically with or
  without an active Employee/Shift filter, since both filters act on `population` upstream of both
  `focusRows` and `rangeRows`).
- **F4-5** (Employee/Shift filtering is 100% client-side) — consistent with this phase's §15 finding
  that every `bucket`/`flag` drill-down is also 100% client-side; no new network behavior was found.
- **F4-6** (filter changes use `router.replace`; Back/Forward skip filter history) — **this phase
  found a direct, practical consequence of F4-6** that Phase 4 did not test: because filter changes
  never create new history entries, browser Back from a page reached via a `push` navigation (like
  the employee profile page) lands precisely on the dashboard's last filter state — which is exactly
  why F5-2's inconsistency (Back preserves state, the breadcrumb link does not) is observable at all.
  This is additional evidence *for* F4-6's existing characterization, not a contradiction of it.
- **F4-7** (mobile-viewport scrollWidth artifact) — out of scope for this phase; not re-tested.

## 18. Regression Tests

- Frontend, targeted attendance suite: `npx vitest run src/lib/attendance/dashboard.test.ts
  src/app/app/attendance/page.test.tsx src/app/app/attendance/employee src/app/app/attendance/\[id\]
  src/components/attendance` → **116 passed (8 test files)**.
- Frontend, full suite: `npx vitest run` → **499 passed (61 test files)** — identical pass count to
  the Phase 4 and F-1-remediation reports' own full-suite runs, confirming no regression since either
  of those (no application code was changed in this phase).
- Frontend typecheck: `npx tsc --noEmit -p tsconfig.json` → **clean, zero errors**.
- Frontend production build: `npm run build` → **succeeded**, all routes compiled including
  `/app/attendance`, `/app/attendance/[id]`, and `/app/attendance/employee/[employeeId]`, no errors.
  (This build run into the live dev server's shared `.next` directory did cause a transient "stuck
  loading" state in the already-open dev-server tab — resolved via `rm -rf .next` + dev-server
  restart, pure build-artifact hygiene, not a code or data change; see §2.)
- Backend: **not re-run** this phase (no backend code was changed; this was a read-only validation
  phase using only `GET` requests against the live dev API plus independent read-only SQL). The F-1
  remediation report's own targeted backend run (`apps/api/tests/integration/modules/employee/` →
  369 passed, against `hrms_test`) remains the most recent backend regression evidence and is
  unaffected by anything found in this phase.
- `hrms_dev` (the live Validation Co dataset: 40 employees, 1,286 `attendance_day` rows, 1,971
  punches) was touched only by read-only `SELECT` queries throughout this phase; no `INSERT`/
  `UPDATE`/`DELETE` was executed against it, and the full `apps/api` pytest suite was never run
  against it, per the data-safety rule.

## 19. Final Verdict

**PASS WITH FINDINGS.** The Attendance dashboard's focus-date drill-downs (every KPI card and every
status-chart segment) are correct, self-consistent, and immune to date/filter/tenant leakage in
every test performed, including range-boundary, join-date, and termination-boundary cases, and the
F-1 fix holds under drill-down testing exactly as it did under Phase 3/4's direct KPI testing. Muster
heatmap cells and employee-profile per-day links are correctly, robustly scoped by construction
(fetch-by-row-ID). However, this phase surfaced one **high-severity, newly-confirmed, reproducible
defect (F5-1)**: every whole-range Needs-Attention item's "View all" action silently narrows to the
focus date only, dropping the large majority of the employees/days the item's own count described,
with no visual indication that this has happened — independently reproduced and SQL-verified twice,
against two different flags and two different ranges. This is a genuine violation of what a
drill-down is supposed to guarantee (the list matches the number it came from) and is more
actionable than the already-accepted D-2/D-3 unscoped-count findings, because it looks exactly like a
correct, scoped drill-down rather than an openly external or unscoped one. A second, medium-severity
finding (F5-2, inconsistent "return to dashboard" behavior between browser Back and the in-page
breadcrumb) and several lower-severity/informational findings (F5-3 through F5-7) round out an
otherwise sound drill-down layer. No data, schema, roles, or application code were modified; no
commits were made.
