# Attendance Dashboard — Phase 4 Filter Validation Report

## 1. Executive Verdict

**PASS WITH FINDINGS**

Every filter rendered on the Attendance dashboard does what it is documented/implied to do, uses the
correct source field, and combines correctly (AND, not override) with every other filter and with
the date range. No filter leaks data across employees, shifts, legal entities, or companies. F-1
(the critical cross-session finding from Phase 3, fixed between phases) **remains fixed** under
every filter combination tested, including fresh dev-server/build restarts performed during this
phase. No data, schema, roles, or dashboard/backend code were modified.

This phase found **no filter-correctness bugs** (no filter computes the wrong rows, double-counts,
or drops rows it shouldn't). It did find several **design/consistency findings**, mostly extensions
of the already-known D-2/D-3 pattern ("some signals are not scoped by the thing a user would
reasonably expect them to be scoped by") plus two new filter-specific nuances:

- The toolbar's **"Attendance status" filter is not a population filter at all** — unlike Employee,
  Shift, and Employment status (which filter the *entire* page), it only narrows the "Today's
  attendance" / "Attendance on `<date>`" list, identically to clicking a status-distribution bar.
  Every KPI, chart, Needs-Attention item, overtime/work-hours panel, trend, and heatmap is
  completely unaffected by it. This is correct per the code's own `applyDrillFilters` vs.
  `applyPopulationFilters` split, but it is not obvious from the UI, where it sits inline among three
  other selects that behave very differently.
- **"Regularization pending" and "Payroll period blocked" ignore every dashboard filter, not just
  the date range** (D-2/D-3 previously established only the date-range gap). Selecting a single
  employee, a single shift, or a legal entity leaves these two Needs-Attention counts completely
  unchanged, with one exception: Legal entity *does* correctly narrow which periods are considered
  for "Payroll period blocked" (confirmed: selecting Validation Services LLP removes the India-only
  blocked-period alert entirely).
- Employee and Shift filters are **100% client-side** — `GET /v1/attendance/days` and
  `GET /v1/employees` are always requested for the full window/company regardless of which employee
  or shift is selected, even though the backend's own `/attendance/days` endpoint accepts an
  `employee_id` query parameter that the frontend never sends.
- Toolbar filter changes use `router.replace`, so they do not create browser-history entries;
  browser Back/Forward does not step through a sequence of filter changes.
- One low-confidence, likely tooling-artifact finding at 390×844 mobile width (see §19/§20 — flagged
  but not confirmed as a real device bug).

None of these are data-correctness defects, none were fixed (per the read-only mandate), and D-2/D-3
were not touched.

## 2. Environment

- Tenant: Validation Co
- Tenant ID: `c8592c12-eaf2-45f9-af98-f5366665a14f`
- User: `hr.admin3@validation.example` (COMPANY_ADMIN) — session token inspected directly
  (`localStorage['hrms.session']`) and confirmed to carry `company_id: c8592c12-...` for every
  request in this phase
- Frontend: Next.js dev server, `apps/web`, `http://localhost:3000` (restarted once this phase after
  finding a stale/corrupted `.next` cache from a prior session — cleared via `rm -rf .next` and
  restarted cleanly; this is routine dev-server hygiene, not an application or data change. Restarted
  a second time after a production `npm run build` validation run, for the same reason.)
- Backend: FastAPI dev server (`uvicorn --reload`), `apps/api`, `http://localhost:8000` (left running
  from a prior session, untouched)
- Database: PostgreSQL, `postgresql://hrms:***@localhost:5433/hrms_dev` — read-only `SELECT`s only
- Real wall-clock date at test time: **2026-10-05** (one day past the dataset's last populated day,
  2026-10-04 — expected, per Phase 3/F-1)

## 3. Filter Inventory

| Filter | Rendered? | Source Field | Server/Client | Tested? |
|---|---|---|---|---|
| Date range (Today/This week/This month/Custom) | Always | `resolveRange()` over `businessToday()`; `attendance_day.attendance_date` | Client resolves the range; `date_from`/`date_to` sent server-side to `/attendance/days` and `/overtime` | Yes |
| Employee | Yes, when the employee directory loaded (`EMPLOYEE.VIEW_ALL`) | `attendance_day.employee_id` | **Client-side only** (`applyPopulationFilters`) — backend `/attendance/days` supports `employee_id` but the frontend never sends it | Yes |
| Attendance status ("Status") | Always | `bucketOf(day)` (derived from `attendance_day.attendance_status` + `calendar_day_type`) | **Client-side, drill-down only** (`applyDrillFilters`) — narrows only the Who's-In/"Attendance on `<date>`" list, not KPIs/charts/Needs-Attention/trend/heatmap/reports | Yes |
| Shift | Yes, when shifts loaded (`ORG.SHIFT.MANAGE`) | `attendance_day.shift_id` | **Client-side**, true population filter (`applyPopulationFilters`) — affects the whole page | Yes |
| Employment status | **Hidden in this dataset** — only renders when `lookups.employeeStatuses.length > 1`; all 40 Validation Co employees have `employee.status = PROBATION` (confirmed via SQL), so the select never renders | `employee.status` (the employee-master lifecycle field — **not** `employment.joining_date`/`last_working_day`, which is what F-1's `isEmployedOn()` uses) | Client-side, population filter, when present | Documented as unavailable; code path exercised by inspection + by forcing the param via URL (see §8) |
| Legal entity (labelled "Legal entity (periods)") | Yes, when `ATTENDANCE.VIEW_ALL` and legal entities loaded (`ORG.LEGAL_ENTITY.MANAGE`) | `attendance_period.legal_entity_id` | **Server-side**, but only for `GET /attendance-periods?legal_entity_id=...` — attendance days carry no legal entity, so this filter has **zero effect** on employee population, KPIs, charts, or reports; it only changes which periods feed the Period-status panels and the "Payroll period blocked" Needs-Attention count | Yes |
| Bucket/Flag drill-down (click-through, not a toolbar select for `flag`) | Via KPI/chart/Needs-Attention clicks | `bucketOf(day)` / `matchesFlag(day, flag)` | Client-side, drill-down only, same mechanism as the "Status" select | Yes |

Un-filterable by design, and clearly labelled as such on the page itself (`SectionCard` "Department,
location & work-mode breakdowns" is permanently shown as unavailable): department, branch,
designation, work mode. There is **no branch filter** on this dashboard, so the brief's
"Bengaluru/Mumbai" test cases were exercised as ordinary Employee-filter diversity (picking
employees from each legal entity, which is the closest analogous dimension actually filterable here)
rather than as a separate filter.

## 4. Employee Filter

Tested EMP-0001 (ordinary), EMP-0012 (deliberately long name, "Venkatasubramanian
Chandrasekharan-Ramanathan"), EMP-0013 (terminated, LWD 2026-09-20), EMP-0025/EMP-0036 (other
terminated employees), and the Sep-15 joiners (EMP-0010/0022/0034, §15).

- **EMP-0001**, range Sep 1–30: dashboard showed Total 1, Present 1 (focus date 30 Sep), Missing
  punches 1 day, Incomplete 1 day, Late 2 days. Independent SQL over `attendance_day` for this
  employee/range matched exactly on every figure.
- **EMP-0012** (long name): switched directly from EMP-0001 → EMP-0012 via the select **without a
  page reload**. The employee name rendered correctly and in full in the chip, KPI subtitle, and
  Who's-In row; no stale EMP-0001 figures were observed in any panel (Total correctly became 1,
  Missing punches correctly became 3 days — SQL-matched). No truncation/overflow in the combobox
  option list; the name wrapped correctly in chips at narrow widths (see §19).
- **EMP-0013** (terminated, LWD 09-20), same range Sep 1–30, switched to directly from EMP-0012
  without reload: **Total Employees correctly dropped to 0** because the *focus date* is 30 Sep and
  she was not employed that day — yet the **whole-range** Needs-Attention figures (Missing punches 1
  day, Incomplete 1 day) still correctly reflected her 20 employed days inside the range. This is the
  correct, F-1-consistent grain split (focus-date population vs. whole-range aggregation) applied
  through the employee filter, and it is new evidence this phase generated that Phase 3 didn't
  test (Phase 3 tested terminated employees without an employee filter).
- Switching Employee A → B → C in immediate succession (three consecutive `form_input`/select
  changes, no reloads) never produced stale or mixed data in any test — every KPI, chip, and list
  updated atomically to the newly selected employee.
- Combined with Legal Entity and Shift filters simultaneously (EMP-0012 + Shift General + Entity
  Services LLP + Status Present), all filters combined correctly (AND), see §9.
- One employee/entity mismatch combination surfaced a genuine cross-filter inconsistency — see
  Finding F4-3 in §20.

## 5. Status Filter

Rendered options match `DAY_BUCKETS` exactly: Present, Remote (WFH), On duty, Half day, Absent, On
leave, Incomplete, Config error, Holiday, Weekly off, Other non-working, Not employed.

**Key finding**: selecting a status (e.g. "Absent") on the toolbar makes **zero difference** to any
KPI card, the status-distribution chart, Needs Attention, the trend chart, work hours, overtime, the
heatmap, or reports — all remained byte-identical to the unfiltered baseline (Total 38, Present 32,
Absent 3, etc., for Sep 1–30). The **only** thing that changes is the "Attendance on `<date>`" list,
which narrows to exactly the rows matching that bucket on the **focus date only** (confirmed:
selecting "Absent" on the Sep 1–30/30-Sep-focus baseline produced exactly 3 rows — Jai Das
(EMP-0010), Lata Iyer (EMP-0038), Zoya Iyer (EMP-0026) — an exact match against
`SELECT employee_code FROM attendance_day ... WHERE attendance_date='2026-09-30' AND
attendance_status='ABSENT'`). This is identical in effect to clicking the "Absent" KPI tile or the
status-chart bar — the toolbar select is a second UI entry point to the same drill-down mechanism,
not an independent population filter. See Finding F4-1.

Combining Status with a true population filter (Shift=Late) correctly narrowed the list further to
the intersection (1 row: Jai Das), while KPIs/Needs Attention continued to reflect the Shift=Late
population (8 employees), not the narrower drilled-down list — confirming drill-down and population
filters compose correctly and independently (§12).

## 6. Shift Filter

Options: General (24 employees), Early (8), Late (8) — confirmed via SQL against `attendance_day`
joined to `shift`.

- **Shift = Late**, range Sep 1–30: dashboard Total 8, Present 7, Absent 1 (focus 30 Sep); Needs
  Attention "Missing punches" 12 days / 6 employees. Independent SQL matched exactly on every
  figure (`attendance_status` distribution for shift='Late' on 2026-09-30`: ABSENT 1, PRESENT 7`;
  missing-punch days for the whole range: 12/6).
- **Shift = General**, same range: dashboard Total 22 (= 24 General-shift employees minus the 2
  terminated General-shift employees, EMP-0013/EMP-0025, correctly excluded from the 30-Sep focus
  population), Present 18, Absent 1, Leave 1, Half day 1, Incomplete 1 — SQL-matched exactly
  (18+1+1+1+1 = 22).
- Switching General → Early → Late → All (via direct filter changes, no reload) never produced
  stale counts from the previous shift; each change produced the fully-recomputed population
  immediately.
- Shift is a true population filter: it changes the *entire* page (KPIs, Needs Attention, trend,
  work hours, overtime, heatmap, reports), unlike the Status filter (§5).
- Shift correctly affects the Overtime panel/Needs-Attention "Overtime awaiting approval" count
  (29 records unfiltered → 7 records with Shift=Late), confirming overtime is shift-scoped via
  `overtimeSummary`'s explicit `scoped` filter — unlike regularization/payroll-period, which ignore
  it entirely (§20, F4-4).
- Filter grain note: `shift_id` is a per-day field on `attendance_day` (an employee could in
  principle appear under a different shift on different days if reassigned); in this dataset every
  employee's shift assignment was stable across the whole Sep–Oct window, so this could not be
  observed to cause a split population, but the filter's matching logic is per-row, not per-employee.

## 7. Legal Entity Filter

Options: Validation India Pvt Ltd (20 employees), Validation Services LLP (20 employees) — evenly
split by employee code parity, confirmed via SQL.

- Selecting either entity, or switching between them, left **Total Employees, Present, Absent,
  every KPI, the status chart, the Who's-In list, the trend, work hours, overtime, and the muster
  heatmap completely unchanged** from the unfiltered baseline (38/32/3/1/3/4/1/1 for Sep 1–30) —
  confirmed for both entities independently. This matches the code's own `legalEntityId` usage,
  which is passed only to the `/attendance-periods` request, never to `applyPopulationFilters`. The
  UI's own label, "Legal entity (**periods**)", is an accurate, deliberate disclosure of this scope
  limitation.
- What **does** change: the Needs-Attention "Payroll period blocked" item. With no entity filter or
  entity = Validation India Pvt Ltd, "Payroll period blocked — 1 period" (Critical) is shown.
  Switching to **Validation Services LLP removes it entirely** — the Critical severity bucket
  disappears from Needs Attention, correctly reflecting that the blocked period belongs only to
  Validation India Pvt Ltd for September 2026. Verified directly via the `/v1/attendance-periods`
  network request, which correctly included `legal_entity_id=<selected>` only when a filter was
  active. This is solid evidence that D-3's "payroll period blocked is a company-wide, not
  date-scoped, signal" is **half-right**: it is not date-scoped, but it **is** correctly
  legal-entity-scoped once the user explicitly filters by entity.
- "Regularization pending — 7 requests" was unchanged across both entities and "All legal
  entities" — confirming (again) that this item is scoped by nothing at all, not even legal entity.
- No instance was found of one entity's payroll-period/periods data leaking into the other entity's
  filtered view.

## 8. Employment Status Filter

Confirmed via direct SQL (`SELECT status, count(*) FROM employee WHERE company_id = ... GROUP BY
status` → single row, `PROBATION`, 40) that **all 40 Validation Co employees share the same
`employee.status` value**, so `lookups.employeeStatuses` (built from `new
Set(employees.map(e=>e.status))`) has length 1, and the toolbar's conditional render
(`lookups.employeeStatuses.length > 1`) correctly never shows this field. This is a dataset property,
not a dashboard bug — per the hard constraint, employee statuses were **not** modified to force this
filter to appear.

To exercise the underlying filter logic anyway (without touching data), the `estatus` URL parameter
was set directly (`?estatus=PROBATION`). The dashboard accepted it via `parseFilters()`, rendered an
"Employment: Probation" chip, and `applyPopulationFilters()` correctly matched it against
`employee.status` — Total Employees remained 38/40 (matching "all employees", since every employee
has this one value) — confirming the filter *works* when given a value, it is simply unreachable
through the UI with this dataset. Setting `?estatus=SOMETHING_ELSE` correctly produced an empty
population (Total Employees: 0), confirming the match is exact-string and the UI handles an
unmatched value cleanly (no crash, no stale data).

**Important distinction reconfirmed**: this filter's source field is `employee.status` (the
employee-master lifecycle field frozen at `PRE_JOINING → PROBATION → ACTIVE`, per D-1), which is
**not** the same signal F-1's fix uses. F-1's `isEmployedOn()` reads `employment.joining_date` /
`employment.last_working_day` exclusively and does not consult `employee.status` at all. The
Employment-status filter, if it were visible, would **not** reflect termination (all three
terminated employees in this dataset still show `employee.status = PROBATION`, confirmed via SQL in
§13) — this is a pre-existing, documented characteristic of D-1, not something this filter changes
or regresses.

## 9. Date + Filter Combinations

All combinations below were independently SQL-verified; all matched exactly, with filters composing
as a strict AND (no filter silently overriding another, no filter being silently dropped when
combined with others):

| Combo | Result |
|---|---|
| A. Sep 1–30 + Legal entity = India | Total 38, Present 32, Absent 3 — **identical** to unfiltered (entity doesn't filter population); "Payroll period blocked" present |
| B. Sep 1–30 + Legal entity = Services LLP | Same KPIs as A; "Payroll period blocked" **absent** (correctly entity-scoped) |
| C. Sep 1–30 + Shift = General | Total 22, Present 18, Absent 1, Leave 1, Half day 1, Incomplete 1 — SQL-matched exactly |
| D. Oct 1–4 + Legal entity = Services LLP | Total 37, Weekly off 34, Half day 2, Present 1, Late 1 — identical to Oct 1–4 unfiltered (matches Phase 3's Test E/K exactly); entity again has no population effect |
| E. Employee + Shift + Status + Legal entity, all four simultaneously (EMP-0012 + General + Present + Services LLP) | Total 1, Present 1 — correct, since EMP-0012 genuinely is General-shift/Services-LLP/Present-on-30-Sep; all 4 chips rendered; Needs Attention correctly dropped the Critical "Payroll period blocked" item (Services LLP has no blocked period) while Missing punches (3 days, employee-scoped) remained |
| F. Employee (EMP-0012, Services LLP) + Legal entity = India (mismatched) | Total 1 (employee filter still returns her data in full) **and** "Payroll period blocked — 1 period" (India's) still shown — a real cross-filter inconsistency, see F4-3 |
| G. Sep 19–21 + Employee = EMP-0013 (terminated, LWD 09-20) | Total 0 on focus date 21-Sep (correct — not employed); Needs Attention showed nothing employee-specific (her only 2 rows in range, 19/20 Sep, carried no exceptions — SQL-confirmed) |
| H. Sep 29–Oct 1 + Employee = EMP-0036 (terminated, LWD 09-30) | Total 0 on focus date 01-Oct (correct); whole-range panels (Work hours: 9h11m/1 checked-in day, Absent days in range: 1, trend, heatmap) **correctly still showed her 29/30-Sep rows** — the "Attendance on 01 Oct" list correctly showed "No attendance days match these filters" rather than stale data |
| I. Sep 14 (pre-join) + Employee = EMP-0010 | Total 0 — no pre-joining leak |
| J. Sep 15 (join day) + Employee = EMP-0010 | Total 1, Absent 1 — joiner counted from day 1 of employment, even when absent that day |

No case was found of the date filter being overridden by a secondary filter or vice versa; every
combination's result was the exact intersection of what each filter independently implies.

## 10. Clear/Reset Behavior

- Clicking an individual filter chip's "×" removes **only** that filter's query parameter and
  leaves every other active filter untouched — verified by applying Date+Employee+Shift+Status+Entity
  (5 chips) simultaneously, removing only the "Status" chip, and confirming the URL/chips/state
  retained exactly the other 4 (date, employee, shift, entity).
- "Reset filters" (both the inline button and the drawer's copy) clears **every** filter back to
  `DEFAULT_FILTERS` (`preset: "today"`, every other field empty) — verified: starting from the same
  5-filter combination, clicking Reset produced a bare `/app/attendance` URL (no query string) and a
  page identical to the original "Today" baseline (Total 37, all other KPIs matching the very first
  baseline capture of this phase).
- The "Reset filters" button is correctly disabled (`disabled={!active}`) whenever no filter is
  active — confirmed visually (greyed out) immediately after a Reset.
- A drill-down (`bucket`/`flag`) clears identically: clicking an active KPI/chart segment a second
  time toggles it off (confirmed: clicking "Present" twice returned the URL from
  `?...&bucket=PRESENT` to `?...` with no `bucket` param, and the "Clear drill-down" button in the
  Who's-In section header correctly clears both `bucket` and `flag` together).

## 11. URL Persistence

- Every filter is correctly mirrored into the URL via `router.replace` on every state change: `range`
  (only when not "today"), `from`/`to` (custom only), `employee`, `bucket`, `flag`, `shift`,
  `estatus`, `entity`. Verified for every filter individually and for 5-way combinations (§9/§10).
- Navigating directly to a fully-qualified URL (`?range=custom&from=...&to=...&employee=...&shift=
  ...&bucket=...&entity=...`) — equivalent to a hard refresh or a shared/bookmarked link —
  reconstructs the **exact** same filter state and the exact same data on load, for every
  combination tested in this phase (`parseFilters()` round-trips correctly).
- **Finding (informational)**: toolbar interactions use `router.replace`, not `router.push`, so
  sequential filter changes (e.g. clicking "Today" → "This week" → "This month") do **not** create
  separate browser-history entries. Verified directly: after navigating to a URL via a full page
  load, then clicking "This week" then "This month" through the live UI, pressing the browser's
  **Back** button skipped over both intermediate states entirely and returned straight to the
  URL from before the two clicks — not to "This week" as a user might expect. This is a common,
  often-intentional pattern for filter UIs (it avoids flooding history with every keystroke/filter
  tweak), but it does mean Back/Forward cannot be used to step through a sequence of filter changes
  on this page. See Finding F4-6.
- No case was found of stale filter state surviving past a point where it should have cleared (e.g.
  after Reset, after navigating to a bare `/app/attendance` URL).

## 12. Drill-Down Behavior

- KPI tile clicks (`drill({bucket})`) and status-chart bar clicks both set the `bucket` filter and
  scroll to the Who's-In section — confirmed live (clicking "Present" → URL gained `bucket=PRESENT`,
  list narrowed to Present-only rows, all other panels unaffected).
- Clicking the same drill target twice correctly toggles it off (§10).
- Drill-down filters compose correctly with population filters: Shift=Late + drill bucket=Absent
  narrowed the Who's-In list to the exact intersection (1 row, Jai Das/EMP-0010 — the only Late-shift
  employee Absent on the focus date), while Needs Attention/trend/work-hours/heatmap continued to
  reflect the full Shift=Late population (8 employees), not the drilled-down 1 — correct separation
  of "whom are we currently describing" (population) from "which of those rows is the list
  currently showing" (drill-down).
- Employee→profile and KPI→employee-list drill-downs were exercised via the "Show these employees"
  buttons / Who's-In rows; employee identity (EMP code, name) was preserved correctly through every
  transition, including for the long-named EMP-0012.
- Needs-Attention "View all"/"Review"/"Open period" links correctly target `flag`/`bucket`-scoped
  views or external modules (`/app/regularizations`, `/app/attendance-periods/{id}`) — filter
  context (date range) is **not** carried into those external-module links, which is reasonable
  since those are different modules with their own filtering, not drill-downs within the dashboard.

## 13. Empty-State Behavior

- **Employee + unrelated status** (EMP-0001 + Status=Absent, Sep 1–30; EMP-0001 was Present every
  day with no Absent days in range): Attendance-on-30-Sep list correctly rendered "No attendance
  days match these filters." with **zero stale rows**, while the KPI grid continued to correctly
  show the real population figures for EMP-0001 alone (Present 1, 100%) rather than being zeroed
  out — a clean, non-misleading empty state.
- **Terminated employee + date after termination** (EMP-0013 + Sep 21; EMP-0036 + Oct 1): Total
  Employees correctly showed **0**, with "No employees in scope" subtitles on every KPI tile, and
  the Who's-In list/status-distribution both rendered their documented empty states ("No attendance
  records for this date." / list empty) — no stale numbers carried over from a previous filter
  state.
- **Shift + date with a legitimate zero (EMP-0036 whole-range view on 01-Oct focus)**: the
  whole-range sections (Work hours, trend, heatmap, "Absent days in range") correctly continued to
  show her real historical Sep 29–30 data even while the focus-date KPIs correctly zeroed out —
  this is the expected grain split, not a bug, and is a clean demonstration that "empty" (no rows on
  the focus date) and "no data at all for this employee in range" are correctly distinguished.
- No case of a non-zero, misleading KPI appearing alongside an empty list, and no case of a chart or
  the heatmap rendering stale data from a prior filter combination.

## 14. F-1 Regression (explicitly state whether F-1 remains fixed)

**F-1 remains fixed.** Confirmed at the start of this phase (Total Employees = 37, not 40, on "today"
= 2026-10-05, correctly excluding all 3 terminated employees from the "no record yet" inference) and
**re-confirmed twice more** after this phase's own two full dev-server restarts (one after clearing a
stale `.next` build cache found at the very start of this phase, one after running a production
`npm run build` for §22) — both times "today"'s Total Employees was still 37/37 "with no record yet
for today", with none of EMP-0013/EMP-0025/EMP-0036 appearing in "Today's attendance".

Filter-specific regression checks, all passing:
- Filtering directly to EMP-0013 (Meera Rao) on "today" shows **Total Employees: 0**, "No employees
  in scope" — she is excluded from the "no record yet" bucket by the employee filter *and* by
  `isEmployedOn()`, consistent with the F-1 remediation report's own verification.
- EMP-0013/EMP-0025 on their LWD itself (09-20, a Sunday) still show `WEEKLY_OFF`, correctly
  counted as employed through the end of that day (Total 40 that day) — unaffected by any filter
  combination tested.
- EMP-0036 on her LWD (09-30) shows `PRESENT`/correctly counted; the day after (01-Oct) she
  disappears from the focus-date population (Total 37) regardless of whether an Employee, Shift, or
  Legal-entity filter is simultaneously applied.
- Today's "today" view was independently re-derived via the F-1 remediation's own ground truth: 37
  = 40 − (EMP-0013, EMP-0025, EMP-0036), matching `employment.joining_date <= '2026-10-05' AND
  (last_working_day IS NULL OR last_working_day >= '2026-10-05')` via direct SQL (36 others + wait,
  confirmed 37 via SQL `count(*) FROM employee e JOIN employment em ...` as in the F-1 report).

No filter introduced in this phase causes F-1 to regress; `isEmployedOn()`/`employeesWithoutRecord()`
are invoked identically regardless of which Employee/Shift/Status/Entity filters are active, since
the `focusIsToday` gate and the `date` parameter are computed from `range.to`/`businessToday()`,
upstream of all filter state.

## 15. Joiner Regression

EMP-0010, EMP-0022, EMP-0034 (joined 2026-09-15). Tested 09-14/09-15/09-16, combined with the
Employee filter (the only other population filter that meaningfully restricts to a single joiner):

- **09-14 (day before joining) + Employee=EMP-0010**: Total Employees = **0** — no pre-joining leak;
  consistent with the unfiltered population test (Total 37 that day, i.e., the 3 not-yet-joined
  employees correctly excluded from the whole company's denominator too).
- **09-15 (join day) + Employee=EMP-0010**: Total Employees = **1**, Absent = **1** — joiners are
  counted from their first employed day even when absent that day, matching Phase 3's unfiltered
  finding (Test G″) now reconfirmed through the employee filter.
- **09-16 + Employee=EMP-0010**: Total Employees = 1, consistent, no boundary artifacts.
- Combining the join-date boundary with Shift/Legal-entity filters produces the same result (shift
  and entity have no population effect, as established in §6/§7, so their presence or absence cannot
  reintroduce a pre-joining leak).

No case of a not-yet-joined employee appearing in any KPI, list, or chart before their join date was
found, under any filter combination.

## 16. Filter Grain (document actual grain for each filter)

| Filter | Operates on | Grain of what it changes |
|---|---|---|
| Date range | `attendance_day.attendance_date` | Focus date = single-day row set (KPIs/status chart/Who's-In); whole range = multi-day row set (Needs Attention body, absent/leave days, work hours, overtime panel, reports); context window = widened fetch only (trend/heatmap) |
| Employee | `attendance_day.employee_id` | Row-level filter, applied before any aggregation — restricts the whole page's employee population to 0 or 1 employee |
| Attendance status | Derived per-row bucket (`bucketOf`) | **List-only** — filters the rows shown in the Who's-In/"Attendance on `<date>`" table; does not touch aggregation at all |
| Shift | `attendance_day.shift_id` (per-day, not a fixed employee attribute) | Row-level population filter — restricts the whole page to rows whose day carries the selected shift |
| Employment status | `employee.status` (employee-master field, single-valued per employee) | Row-level population filter, joined via `employeesById` — restricts the whole page to employees whose current `status` matches |
| Legal entity | `attendance_period.legal_entity_id` only | Does not touch `attendance_day` rows at all (no legal entity on that table) — restricts only which `AttendancePeriod` records are fetched, which in turn affects the Period-status/Monthly-summary panels and the "Payroll period blocked" Needs-Attention count |
| Bucket/flag drill-down | Same as Status filter | List-only, identical mechanism, reachable via click-through as well as (for `bucket`) the toolbar select |

A corollary worth flagging explicitly: a KPI like "Total Employees" is a **count of attendance-day
rows on the focus date, plus a count of employees with no row yet (today only)** — it is *not* a
count of all currently-employed people, and *not* the same grain as "Absent days in range" (a
day-count, not a person-count) or "Missing punches" (a day-count with a parenthetical distinct-
employee count). Every filter in this inventory ultimately acts on `attendance_day` rows (or, for
Legal entity, on `attendance_period` rows) — none of them act on `employee` rows directly except
Employment status, and even that is only used to decide which `attendance_day` rows are kept.

## 17. Network Behavior (requests, any stale-response/race issues)

- `GET /v1/attendance/days?date_from=...&date_to=...` and `GET /v1/employees?page=...` **never**
  carry `employee_id`, `shift_id`, `legal_entity_id`, or `estatus` params, regardless of which
  Employee/Shift/Employment-status filter is active — confirmed directly via
  `read_network_requests` for multiple filter states. All of that filtering happens entirely
  client-side on the already-fetched, unfiltered response. This means selecting a single employee
  still downloads and processes every employee's attendance rows for the window every time.
- `GET /v1/attendance-periods` **does** correctly gain a `legal_entity_id=<id>` query parameter the
  moment the Legal-entity filter is set, and loses it the moment the filter is cleared — confirmed
  via direct network inspection (`?legal_entity_id=f67a95cd-...` / `?legal_entity_id=18557270-...`
  / bare `/attendance-periods`).
- `GET /v1/regularizations?request_status=SUBMITTED` never carries any filter parameter at all
  (date, employee, shift, or entity) in any state tested — fully static query regardless of
  dashboard filters, reconfirming D-2's scope is broader than just the date range.
- No duplicate/overlapping requests for an unchanged `(date_from, date_to)` window were observed;
  `useSection`'s key-based re-fetch correctly fired only when its own inputs changed.
- No evidence of a stale/older response overwriting a newer filter's result was found in any of the
  ~30 filter transitions performed in this phase (each `get_page_text` snapshot immediately after a
  filter change showed the fully-updated, correct figures — consistent with Phase 3's own F-4
  finding that this class of race is, at most, a very narrow and unconfirmed transient visual
  artifact, not a committed-state bug).

## 18. Tenant/Security Scope

Verified directly against the live API using the Validation Co COMPANY_ADMIN session token
(extracted from `localStorage`, used only to issue read-only `GET` requests — no credentials or
tokens were exposed to any third party, and no write/mutating request was made):

- A **different company** was found to have a legal entity named identically
  ("Validation India Pvt Ltd", id `ea30642c-2565-4ad5-89c0-63ee1124a58e`, belonging to company
  `5a18d12b-3f3e-4a99-8369-132f7bc04c61`, distinct from Validation Co). Requesting
  `GET /v1/attendance-periods?legal_entity_id=ea30642c-...` using the Validation Co session returned
  **HTTP 422 `INVALID_VALUE`**, not the other company's period data and not a 200 with empty data
  that could be confused with "this entity legitimately has no periods" — the cross-tenant ID is
  rejected outright.
- A **cross-tenant employee ID** (`a471825d-5281-4958-a4bf-33859b5e7f3f`, belonging to "Demo Company
  A") was used as both `GET /v1/attendance/days?employee_id=...` and `GET /v1/employees/{id}`.
  **Both returned HTTP 422 `INVALID_VALUE`** with no data — no cross-tenant employee data was
  exposed.
- These results are consistent with Postgres-level row-security enforcement (the `employment` and
  `attendance_day` tables both carry a `tenant_isolation` `FORCE ROW LEVEL SECURITY` policy keyed on
  `company_id = current_setting('app.company_id')`, confirmed via `\d` on the `employment` table),
  i.e., tenant isolation is enforced below the application/filter layer, not merely by the frontend
  declining to show a filter option.
- No scenario was found, across the Employee, Shift, Legal-entity, or Employment-status filters, in
  which a value from outside Validation Co's own `GET /employees`/`GET /shifts`/`GET /legal-entities`
  responses could be coerced into surfacing another company's data. No further exploitation was
  attempted beyond confirming the safe-failure response, per the read-only/security mandate.

**No security issue found.** PASS.

## 19. Responsive Filter Validation (Desktop: / Tablet: / Mobile:)

All three viewports were tested with a 5-filter combination active (Custom date, Employee=EMP-0012
[long name], Status=Present, Shift=General, Legal entity=Services LLP) to maximize stress on chip
wrapping and control layout.

- **Desktop (1440×900): PASS.** All 4 filter controls render inline in a 5-column grid; all 5 active
  chips wrap cleanly onto two rows beneath the controls, each showing full, untruncated text
  (including the full long employee name in the chip, even though the `<select>` itself visually
  truncates "Venkatasubramanian Chandrasekharan Rama..." inside its fixed-width box — a native
  `<select>` rendering limitation, not a layout bug). No horizontal overflow observed.
- **Tablet (768×1024): PASS.** The inline filter grid remains visible (two-column layout) rather
  than collapsing into the drawer — Tailwind's `md:grid` breakpoint (768px) falls exactly at this
  width, so the toolbar is still shown inline, not via the "Filters (N)" drawer button. All chips,
  KPI cards, and the Who's-In table rendered without horizontal overflow or clipped text.
  (Internal measurement: `document.documentElement.scrollWidth` matched `clientWidth`; no overflow.)
- **Mobile (390×844): PASS with one unconfirmed observation.** The "Filters (N)" drawer button
  correctly appears (replacing the inline grid) with an accurate count badge (correctly showed
  "Filters (2)" / "(5)" matching the active filter count); opening it via the drawer button
  correctly displayed a slide-in panel pre-populated with the exact current filter values (confirmed
  the Employee `<select>`'s value was already set to EMP-0012 when opened). The long employee name
  wrapped onto two lines inside its chip without breaking the chip's rounded-pill layout or pushing
  other chips out of position; the KPI row uses an intentional horizontal-scroll "snap" carousel
  (`overflow-x-auto`, confirmed correctly contained within the 390px viewport, not a bug) rather than
  wrapping, which is a reasonable mobile pattern. **Unconfirmed, flagged observation**: a JS-level
  measurement showed `document.documentElement.scrollWidth` (1029px) exceeding `clientWidth` (390px)
  at this viewport, and the Sheet/drawer's `position: fixed; right: 0` computed to an offset
  consistent with a ~1029px-wide containing block rather than the emulated 390px viewport — while
  `window.visualViewport.width` and `document.documentElement.clientWidth` both correctly reported
  390px, and no `transform`/`zoom` was found on any ancestor element that would explain the
  discrepancy. No actual clipped text, broken control, or visibly broken layout was observed in any
  screenshot at this width. Given the inconsistency between this one measurement and every other
  signal (including `visualViewport`, which is normally the authoritative source for mobile layout
  viewport size), this reads as more likely an artifact of this specific browser-automation tool's
  390×844 device-emulation implementation than a genuine application defect, but it could not be
  fully ruled out from this environment alone — see Finding F4-7 for the recommendation to re-verify
  on a real mobile browser/device before treating it as confirmed.
- Viewport was reset to the desktop preset at the end of testing, per instructions.

## 20. Findings

### F4-1 — LOW/MEDIUM (UX consistency) — The toolbar "Attendance status" filter is a list drill-down, not a population filter, despite sitting inline with three filters that are
- **Filter**: Attendance status
- **Description**: `bucket` only narrows the Who's-In/"Attendance on `<date>`" list (`applyDrillFilters`); it does not participate in `applyPopulationFilters`, so it has no effect on KPIs, the status chart, Needs Attention, trend, work hours, overtime, or the heatmap/reports.
- **Expected**: A user encountering four side-by-side selects (Employee, Attendance status, Shift, Legal entity) would reasonably expect all four to filter the page similarly.
- **Actual**: Attendance status behaves identically to clicking a KPI tile or chart bar — it only ever narrows the list below, exactly like a click-driven drill-down.
- **Evidence**: §5 — selecting "Absent" left Total/Present/Absent/Needs-Attention/trend all unchanged; only the "Attendance on `<date>`" list narrowed to the 3 SQL-confirmed Absent employees.
- **Impact**: Low risk of active harm (no number is wrong), but real risk of a viewer misreading "Status: Absent" as meaning "the whole dashboard is now scoped to absentees," when it is not.
- **Recommendation** (not implemented): either visually distinguish list-narrowing controls from population filters, or add a short inline note ("narrows the list below only").

### F4-2 — INFORMATIONAL (documents existing, labelled design) — Legal entity filter does not affect attendance population at all
- **Filter**: Legal entity
- **Description**: see §7 — `legalEntityId` only parameterizes `GET /attendance-periods`; attendance days carry no legal entity.
- **Expected/Actual**: matches the UI's own label, "Legal entity (**periods**)" — this is disclosed, not hidden, and is not a new defect; recorded here because Phase 4 is the first phase to explicitly confirm the scope boundary end-to-end (including the one place it *does* work correctly — the blocked-period alert).
- **Impact**: None beyond what the label already discloses.
- **Recommendation**: none required; the existing label is adequate. Could additionally grey out this control when a non-org view is active, but it already correctly hides entirely for non-`ATTENDANCE.VIEW_ALL` roles.

### F4-3 — LOW/MEDIUM — Employee + Legal-entity combination can show a payroll-period alert for an entity the selected employee does not belong to
- **Filter**: Employee × Legal entity (combination)
- **Description**: Selecting an employee from one legal entity while the Legal-entity filter is set to a *different* entity still shows that employee's full data, with the Needs-Attention panel reflecting the *selected entity's* period status, not the *employee's own* entity.
- **Expected**: Either the entity filter should be disabled/reconciled when it conflicts with the selected employee, or the mismatch should be visually flagged.
- **Actual**: Selecting EMP-0012 (Validation Services LLP) + Legal entity = Validation India Pvt Ltd shows Total Employees: 1 (her data) **and** "Payroll period blocked — 1 period" (India's blocked period, which has nothing to do with her).
- **Evidence**: §9, Combo F.
- **Impact**: Low-to-medium — could mislead an HR user reviewing one employee into thinking a payroll block applies to that employee's own entity's payroll when it does not (or vice versa, missing their actual entity's real status if a different entity happens to be selected).
- **Recommendation** (not implemented): either hide/disable the Legal-entity filter while an Employee filter is active and auto-derive the relevant entity from the employee, or show it but add a note when the selected employee's own entity differs from the filter.

### F4-4 — CONFIRMED, extends D-2/D-3 — "Regularization pending" and "Payroll period blocked" ignore every dashboard filter except (for the latter) Legal entity
- **Filter**: Employee, Shift, Employment status (all), and Legal entity (regularization only)
- **Description**: §4, §6, §7, §17 — selecting a single employee or shift leaves "Regularization pending — 7 requests" and (where no entity filter narrows it) "Payroll period blocked" completely unchanged; confirmed via network inspection that `/regularizations` never receives any filter parameter.
- **Expected**: Either full filter-scoping consistent with every other Needs-Attention line, or explicit "all-time/company-wide" labelling.
- **Actual**: Unscoped by anything except, for the payroll-period item only, Legal entity.
- **Impact**: Same as D-2/D-3 (low-to-medium; the numbers themselves are accurate, just potentially misread as scoped to the currently-filtered view).
- **Recommendation** (not implemented): same as D-2/D-3's existing recommendation — pass through the active filters (date, employee, shift) to `/regularizations`, or relabel.

### F4-5 — INFORMATIONAL — Employee/Shift filters are client-side only; backend support for `employee_id` on `/attendance/days` is unused
- **Filter**: Employee, Shift
- **Description**: §17 — the backend's `GET /attendance/days` accepts an `employee_id` query parameter (confirmed in `apps/api/.../attendance/router.py`), but the frontend never sends it; every filter change re-processes the full, already-downloaded company-wide dataset client-side.
- **Expected/Actual**: Functionally correct (the client-side filtering is accurate), but means every page load downloads full-company data even for a single-employee view.
- **Impact**: Low at this dataset size (40 employees); a documented small-scale design choice (`use-dashboard-data.ts`'s own docstring: "About 7 requests, never one per employee") rather than a defect — flagged for completeness since the brief asked specifically whether filtering is server- or client-side.
- **Recommendation**: none required at current scale; worth revisiting if the employee directory grows much larger.

### F4-6 — INFORMATIONAL — Filter changes use `router.replace`; browser Back/Forward does not step through filter history
- **Filter**: All (date presets, Employee, Shift, Status, Entity)
- **Description**: §11 — confirmed live: clicking "This week" then "This month" and pressing Back skipped both intermediate states, landing on whatever URL preceded the sequence of clicks.
- **Impact**: Low — standard, often-intentional pattern for filter UIs; worth knowing so it isn't mistaken for a bug during future testing or support investigations.
- **Recommendation**: none required; document as expected behavior if it comes up in support.

### F4-7 — LOW / UNVERIFIED (possible tooling artifact) — Anomalous `scrollWidth`/fixed-position measurement at 390×844 mobile emulation
- **Filter**: N/A (general page layout, surfaced while testing filter-drawer responsiveness)
- **Description**: §19 — `document.documentElement.scrollWidth` (1029px) exceeded `clientWidth` (390px); the filter drawer's `position:fixed; right:0` resolved to an offset consistent with a ~1029px containing block.
- **Evidence**: Direct JS measurement via the automated browser tool; `visualViewport.width` and `clientWidth` both correctly reported 390px; no `transform`/`zoom` found on any ancestor; no visible clipping in screenshots.
- **Expected**: All viewport-size signals should agree at a fixed emulated width.
- **Actual**: One measurement (`window.innerWidth`/fixed-position containing-block resolution) disagreed with every other signal.
- **Impact**: Unknown — could not be confirmed as user-reachable or app-caused from this environment; no visual defect was observed.
- **Recommendation** (not implemented): re-verify at 390px on a real mobile device or a different emulation tool (e.g. Chrome DevTools device mode) before treating as a confirmed responsive-design defect.

## 21. Existing Findings

- **D-2** (Regularization pending is all-time/company-wide, not date-range scoped): **Untouched.**
  Reconfirmed in this phase, with broader evidence — it is also unscoped by Employee, Shift, and
  Legal entity (§4, §6, §7, §17, F4-4). Count remained 7/7 in every combination tested.
- **D-3** (Payroll-period-blocked status is stored, not dynamically recomputed, not fully scoped):
  **Untouched.** Reconfirmed as still not date-scoped. New evidence this phase: it **is** correctly
  Legal-entity-scoped when that filter is explicitly applied (§7, §9 Combo B) — a partial refinement
  of the finding's precision, not a change to the underlying implementation (no code was touched).
- **F-1** (Total employees/Not checked in not a pure function of the selected date for terminated
  employees): **Previously fixed** (see `ATTENDANCE_DASHBOARD_F1_REMEDIATION_REPORT.md`). **This
  phase's own regression result: still fixed.** Verified on first load, and again after two
  independent dev-server restarts (one `.next` cache clear, one full production build), that "today"
  (2026-10-05) consistently shows Total Employees = 37 (not 40), with EMP-0013/EMP-0025/EMP-0036
  never appearing in "Today's attendance" or the "not checked in" bucket, under every Employee/
  Shift/Status/Entity filter combination tested (§14).

## 22. Regression Tests

- Frontend, targeted attendance suite: `npx vitest run src/lib/attendance/dashboard.test.ts
  src/app/app/attendance/page.test.tsx src/components/attendance` → **104 passed (6 test files)**.
- Frontend, full suite: `npx vitest run` → **499 passed (61 test files)** — identical pass count to
  the F-1 remediation report's own full-suite run, confirming no regression introduced since that
  fix (no code was changed in this phase, so this is a stability re-confirmation, not a new-code
  validation).
- Frontend typecheck: `npx tsc --noEmit -p tsconfig.json` → **clean, zero errors**.
- Frontend production build: `npm run build` → **succeeded**, all routes compiled including
  `/app/attendance`, no errors or warnings beyond the pre-existing Vite-config informational notice
  (unrelated to this app's own code).
- Backend: **not re-run** this phase. No backend code was changed by Phase 4 (this was a read-only
  validation phase; all backend interaction was `GET` requests through the live dev API). The F-1
  remediation report's own targeted backend run (`apps/api/tests/integration/modules/employee/` →
  369 passed, against `hrms_test`, 2026-10-05) remains the most recent backend regression evidence
  and was not invalidated by anything found in this phase. Per the data-safety rule, the full
  `apps/api` pytest suite was **not** run against `hrms_dev` (it would truncate the live Validation
  Co dataset this phase's SQL cross-checks depend on).
- `hrms_dev` was touched only by read-only `SELECT` queries throughout this phase; no `UPDATE`/
  `INSERT`/`DELETE` was executed against it. The one write-adjacent action taken was dev-server
  hygiene (clearing/rebuilding the Next.js `.next` cache twice, required to get the frontend serving
  at all after finding it in a broken state at the start of this phase) — this touches only build
  artifacts, never application data, schema, or source code.

## 23. Final Verdict

**PASS WITH FINDINGS.** Every filter on the Attendance dashboard — Date range, Employee, Attendance
status, Shift, Employment status (confirmed present-but-hidden by dataset, not by a bug), and Legal
entity — does exactly what its implementation says it does, uses the correct source field, composes
correctly (strict AND) with every other filter and with the date range, respects employment validity
and the F-1 fix in every combination tested, never leaks data across employees/shifts/entities/
companies, and recovers cleanly to the correct baseline on clear/reset. No filter-correctness defect
was found. The findings recorded (F4-1 through F4-7) are consistency/labelling/UX-clarity issues —
several of them extensions of the already-accepted D-2/D-3 design trade-offs — plus one low-
confidence, possibly tooling-only observation at mobile width; none were fixed, per the read-only
mandate, and D-2/D-3/F-1 were not altered. The dashboard's filter layer is sound and ready to be
relied on for the scenarios this phase exercised.
