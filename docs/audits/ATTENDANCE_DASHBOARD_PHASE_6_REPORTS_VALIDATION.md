# Attendance Dashboard — Phase 6 Reports/Tables & Data Consistency Validation Report

## 1. Executive Verdict

**PASS WITH FINDINGS**

Five of the Reports panel's six reports — Daily Attendance, Present/Absent, Late/Early, Work
Hours, and Payroll Attendance — were independently SQL-verified across single-day, multi-day,
full-month, cross-month, joiner-boundary and termination-boundary ranges, under every available
filter (Employee, Shift, Attendance-Status, Legal-Entity) individually and in combination, under
search, sort and pagination, and in empty-state and tenant-isolation scenarios. In every one of
these checks the report population, counts and per-employee figures matched the independent
PostgreSQL source of truth **exactly** — no missing rows, no duplicated rows, no cross-tenant
leakage, no date-range leakage, no fabricated data.

However, this phase found one **high-severity, confirmed, reproducible defect (F6-1)**: the
**Overtime report** tab of the Reports panel is built from `data.overtime`, which `page.tsx`
fetches using the *widened trend window* (`win`, which extends up to 13 days before the actual
selected range so the trend chart has context) instead of the actual *selected range* (`range`).
Every other report (Daily/Present-Absent/Late-Early/Work-Hours) reads from `rangeRows`, which is
correctly scoped to the selected range — only the Overtime report reads the unfiltered wide-window
data directly, with no client-side re-filter. For any selected range narrower than 14 days (the
large majority of realistic HR usage — a day, a week, a pay fortnight), the Overtime report
silently includes overtime records from up to 13 days *before* the range start, with no visual
indication, no date-range boundary shown, and no way to distinguish an in-range row from a
leaked one except by reading the Date column by eye. Reproduced on two different ranges
(2026-09-28–10-04 and 2026-10-01–10-04): both showed the identical 20-row set starting at
21 Sep — the common window floor for any range ending 04 Oct — against SQL-confirmed correct
range populations of 8 and 5 rows respectively. The live network trace confirms the root cause
exactly: `GET /v1/overtime?date_from=2026-09-21&date_to=2026-10-04` for a selected range of
`2026-09-28`–`2026-10-04`.

A second, lower-severity, **by-design but under-documented** finding (F6-2): the Payroll
Attendance report is entirely independent of the dashboard's selected date range. It always shows
whichever attendance period covers the real calendar "today" (falling back to the most recent
period if none does), regardless of what date range the user has selected on the dashboard —
confirmed by selecting September across multiple tests while the report continued to show the
October period. This is consistent with, and a direct restatement of, the already-accepted,
deferred finding **D-3** ("Payroll-period-blocked status is based on stored period state... not
necessarily date-range-overlap based") — Phase 6 confirms this applies to the Payroll *report*
specifically, with live reproduction and exact numeric SQL verification of the period-summary data
itself (which is, within its own period scope, 100% numerically correct).

A third, low-severity finding (F6-3): the Reports panel's five non-Payroll reports read from
`rangeRows`/`overtime.data`/`population`, which are filtered by Employee, Shift and Employee-Status
— but **not** by the toolbar's "Attendance status" selector (`bucket`/`flag`), confirmed live
(selecting "Absent" in the toolbar left the Daily Attendance report's row count completely
unchanged, at the full unfiltered 1138 rows for the September range). This is a direct,
report-specific consequence of the already-documented **F4-1** finding (the Attendance-status
control is a list/drill-down, not a population filter) — Phase 6 additionally confirms it applies
to the Reports panel, which a user might reasonably expect to behave like a true filter given its
"Filter" affordances sit directly above it.

No application code, database data, schema, migrations, permissions, or configuration were
modified. No commits, pushes, merges, resets, or cleans were performed.

## 2. Environment

- Tenant: **Validation Co**, tenant/company ID `c8592c12-eaf2-45f9-af98-f5366665a14f`
- User: `hr.admin3@validation.example` (COMPANY_ADMIN)
- Date ranges tested: 2026-10-04 (single day); 2026-10-01–2026-10-04; 2026-09-01–2026-09-30 (full
  month); 2026-09-28–2026-10-04 (cross-month); 2026-09-14–2026-09-16 (joiner boundary,
  2026-09-15); 2026-09-19–2026-09-21 and 2026-09-20 single day (EMP-0013/EMP-0025 termination
  boundary, LWD 2026-09-20); 2026-09-30 single day and 2026-09-29–2026-10-01 (EMP-0036 termination
  boundary, LWD 2026-09-30); "Today" (2026-10-05, F-1 regression scenario)
- Real wall-clock date at test time: **2026-10-05** (one day past the dataset's last populated
  day, 2026-10-04 — expected, the live F-1 scenario, not simulated)
- Frontend: Next.js dev server, `apps/web`, `http://localhost:3000` (left running from the prior
  F5-1 remediation session; confirmed up via HTTP 200 before starting, never restarted this phase)
- Backend: FastAPI dev server (`uvicorn --reload`), `apps/api`, `http://localhost:8000` (confirmed
  up via HTTP 200 before starting, never restarted this phase)
- Database: PostgreSQL, `postgresql://hrms:***@localhost:5433/hrms_dev` — every query this phase
  issued was a read-only `SELECT`; no `INSERT`/`UPDATE`/`DELETE` was ever run
- Dataset: Validation Co, 40 employees (EMP-0001–EMP-0040), 2 legal entities (Validation India Pvt
  Ltd — 18 employees, Validation Services LLP — 19 employees, 3 unconfirmed/other), 3 shifts
  (General, Early, Late), 1,286 `attendance_day` rows 2026-09-01–2026-10-04, 3 terminated employees
  (EMP-0013 Meera Rao LWD 2026-09-20, EMP-0025 Yash Rao LWD 2026-09-20, EMP-0036 Jaya Kulkarni LWD
  2026-09-30 — confirmed via `employment.last_working_day`, not assumed)

## 3. Reports Audited

Source: `apps/web/src/components/attendance/dashboard/reports-panel.tsx` (full file read), backed
by `apps/web/src/lib/attendance/dashboard.ts` and `apps/web/src/app/app/attendance/page.tsx` (both
read in full), plus `apps/web/src/components/attendance/dashboard/use-dashboard-data.ts` (read in
full for the exact fetch parameters of each data source).

| Report | Data source | Scoped by | Row model |
|---|---|---|---|
| Daily attendance | `rows` prop = `rangeRows` (= `rowsInRange(population, range)`, where `population = applyPopulationFilters(allDays, filters, employeesById)`) | Selected range, Employee/Shift/Employee-Status filters | One row per `attendance_day` |
| Present / absent | `perEmployee` — client-side aggregation of `rangeRows` into present/half/absent/leave counts per employee | Same as above | One row per employee (with ≥1 day in range) |
| Late / early | `rangeRows.filter(d => d.is_late \|\| d.is_early_out)` | Same as above | One row per `attendance_day` with either flag |
| Work hours | `perEmployee.filter(e => e.days > 0)` | Same as above | One row per employee with ≥1 checked-in day |
| Overtime | `overtime.data` = `data.overtime.data`, fetched by `useDashboardData` via `GET /overtime?date_from=win.from&date_to=win.to` **(the widened window, not the selected range — see F6-1)** | Employee/Shift/Employee-Status are **not** applied (no population filter on this tab); range is wrong (window, not selection) | One row per `OvertimeRecord` |
| Payroll attendance | `usePeriodSummary(pickDefaultPeriod(periods.data, today).id)` → `GET /attendance-periods/{id}/summary` | The attendance period covering the real "today", or the most recent — **not** the selected range at all (see F6-2); Legal-Entity filter affects which periods are fetched, hence indirectly which period is picked | One row per employee in that period |

Component-level facts confirmed by reading `reports-panel.tsx`:

- Pagination: fixed page size `PAGE_SIZE = 15`, client-side only, implemented once in a shared
  generic `ReportTable<T>` component used by all six reports (`page`, `Math.ceil`, `.slice`).
- Search: a single text input per report, client-side `.toLowerCase().includes()` against a
  per-report `searchText(row)` function (employee name for most reports; employee name + status
  label for Daily Attendance).
- Sorting: client-side, one column active at a time, ascending by default, toggles on re-click;
  implemented via `Array.prototype.sort` (stable in all current JS engines) over the already
  search-filtered array, before pagination is applied.
- Empty states: a single shared "No attendance days in this range." (or report-specific variant)
  message, rendered whenever the (filtered + searched) row array is empty — identical message for
  "no data in range" and "search matched nothing" (see Finding F6-5).
- Loading/error states: Overtime and Payroll reports each show their own loading/error text tied to
  their own `Section<T>` status; the other four reports have no independent loading state (they
  render instantly once the page's primary `attendance/days` fetch — shared with the whole
  dashboard — has resolved).
- No export functionality exists (explicitly stated in-page: "Export (CSV / Excel / PDF) is not
  available yet — the backend has no attendance export endpoint") — confirmed accurate; no backend
  export endpoint exists.
- No row-level navigation in five of six reports (Daily/Present-Absent/Late-Early/Hours/Overtime);
  Payroll has one link ("Open period") to the period record. This matches Phase 5's F5-5 exactly
  and was reconfirmed unchanged this phase (not re-litigated as a new finding).
- None of the six reports persist their search/sort/page state in the URL — all three are local
  `useState` inside `ReportTable`, reset to defaults (page 1, no search, first column ascending)
  on every report-tab switch, dashboard filter change, or reload (see §17, F6-4).

## 4. Date-Range Validation

All six required test ranges (brief §6 A–F) were run against the Daily Attendance report (the
report with the simplest, most direct row model — one row per `attendance_day`) and cross-checked
against independent SQL. All matched exactly:

| Range | SQL row count | Daily Attendance report row count | Result |
|---|---|---|---|
| A. 2026-10-04 (single day) | 37 | 37 | Exact match |
| B. 2026-10-01–2026-10-04 | 148 | 148 (not independently re-counted on this report; Late/Early and Work-Hours sub-counts for this exact range were, see §8/§9) | — |
| C. 2026-09-01–2026-09-30 | 1138 | 1138 | Exact match |
| D. 2026-09-28–2026-10-04 | 262 | not independently re-verified on Daily (Present/Absent's 38-employee population for this exact range was, §9) | — |
| E. 2026-09-14–2026-09-16 (includes join date 09-15) | 117 | 117 | Exact match |
| F. 2026-09-19–2026-09-21 (includes LWD 09-20) | 118 | 118 | Exact match |
| F (single day). 2026-09-20 (exact LWD) | 40 | 40 | Exact match — **terminated employees correctly included on their exact last working day** |
| F2. 2026-09-30 (EMP-0036's exact LWD) | 38 | not independently re-verified live; SQL-confirmed population exists (38) | — |

No row outside a selected range ever appeared in the Daily Attendance, Present/Absent, Late/Early,
or Work Hours reports in any test. No row inside a selected range was ever omitted. Range ends are
inclusive everywhere tested (`attendance_date BETWEEN from AND to`, confirmed both in the SQL used
and in the UI's own inclusive display, e.g. the 2026-09-20 exact-LWD single-day test).

**The one exception is the Overtime report (F6-1)**, which — for any range narrower than the
14-day trend-context window — includes rows from *before* the selected range's start date. This is
the opposite failure mode from what brief §6 warns against ("must not silently collapse a
multi-day... range to `range.to`"): instead of collapsing, it silently *expands* backward. See §10
and §21 for full detail and live evidence.

A direct search for Meera Rao (EMP-0013, LWD 2026-09-20) in the Daily Attendance report for range
2026-09-19–2026-09-21 showed exactly two rows — 19 Sep (Present) and 20 Sep (Weekly off, her exact
LWD) — and correctly zero rows for 21 Sep, confirming no leakage past her termination date in this
report.

## 5. Dashboard vs Report Reconciliation

Compared, for the same date range and filters, the dashboard's own KPI/Needs-Attention figures
against the Reports panel's row populations:

- **Missing punches**, range 2026-10-01–2026-10-04: Needs Attention read "15 days · 13 employees
  affected"; independent SQL for the identical predicate (`missing_punch` over the same range)
  returned `15, 13` — exact match (the dashboard figure itself, not the report, but establishes the
  baseline population the Late/Early report union-predicate check in §6 then builds on).
- **Late/Early union**, same range: SQL `(is_late OR is_early_out)` → 15 rows (8 late + 8 early − 1
  day with both flags true), 13 distinct employees. The Reports panel's Late/Early report showed
  **15 rows** for this exact range — exact match, and correctly reflects that a day with *both*
  flags is one row, not two (the report does not double-count).
- **Present/Absent population**, range 2026-09-28–2026-10-04: dashboard's own population for this
  range (SQL: distinct `employee_id` with any `attendance_day` row in range) = 38; Present/Absent
  report showed **38 rows** — exact match. A specific employee (Dev Shah, EMP-0004) was spot-checked
  row-by-row: SQL gave Present=4, Half day=2, Absent=0, Leave=0 for this range; the report's row for
  Dev Shah showed **4 / 2 / 0 / 0** — exact match.
- **Work Hours**, range 2026-10-01–2026-10-04: SQL for Dev Shah gave `days=3,
  worked_minutes=1160 (19h20m), scheduled_minutes=1620 (27h0m)`; the Work Hours report row for Dev
  Shah showed **Days 3, Worked 19h 20m, Average 6h 27m (1160/3=386.67→387min), Scheduled 27h 0m** —
  exact match on every column, including the rounded average.
- **Checked-in employee count**, same range: SQL distinct `employee_id` with `actual_first_in IS
  NOT NULL` = 36; Work Hours report row count = **36 rows** — exact match.

Not merely aggregate totals: every reconciliation above compared the actual employee/date
population (per brief §7's explicit requirement), and in the Dev Shah and missing-punch/late-early
cases, exact row-level values, not just counts.

**One reconciliation gap was found**: the Overtime report's own row count (20, for a range whose
dashboard-level Overtime figures are computed correctly over the true 8/5-row range) does not
reconcile with the dashboard's Overtime panel/KPI at all — this is exactly F6-1, detailed in §10.

## 6. Daily Attendance Results

Validated columns: Date, Employee, Status, In, Out, Worked. (Note: the brief's §8 checklist
additionally lists Employee code, Expected hours, Weekly off/Holiday/On-duty/Leave as distinct
columns, and Regularization indicators — the actual implementation's Daily Attendance report has a
narrower, 6-column schema; the richer per-status/flag detail the brief describes is shown
elsewhere on the same page, in the "Attendance on `<date>`"/Who's-In panel and the muster heatmap,
not duplicated into this report. This is a description correction, not a defect — documented here
per brief §5's "do not assume... document what each report actually does.")

- **Row counts**: exact SQL match across every range tested (§4).
- **Status values**: every status shown (Present, Half day, Weekly off, Incomplete, Holiday, etc.)
  is the same `bucketOf()` classification already independently validated in Phases 1–5 — no
  separate computation exists in this report.
- **In/Out/Worked**: spot-checked via the Work Hours report's per-employee aggregation (§5), which
  sums the same `worked_minutes` field this report displays per-row; both trace to the same
  `attendance_day.worked_minutes` column.
- **Joiner (2026-09-15) / termination (2026-09-20, 2026-09-30) boundaries**: see §4 — exact row
  counts, and the Meera Rao spot-check confirms no post-termination leakage at the row level.
- **Normal present / absent / leave / half-day / incomplete / weekly-off / holiday / on-duty /
  joiner / leaver days**: all observed in the live September-range table (e.g., Aditi Nair's rows
  showed Present, Incomplete, and Weekly-off on different dates within the same report); all
  consistent with the already-validated `bucketOf()` classification.

## 7. Present/Absent Results

- Population: exact SQL match (38 for the 2026-09-28–2026-10-04 range; §5).
- Status classification (Present/Half day/Absent/Leave columns): exact per-employee match for the
  spot-checked employee (Dev Shah, §5).
- Leave exclusion/inclusion: Leave is its own column, separate from Absent — confirmed via the
  dashboard's own `bucketOf()` mapping (`LEAVE` and `ABSENT` are mutually exclusive buckets), no
  separate report-level reclassification exists.
- Weekly-off / holiday behavior: neither weekly-off nor holiday days are counted in Present, Half
  day, Absent, or Leave (they fall into `NOT_EXPECTED_BUCKETS`/non-counted buckets in the
  `perEmployee` aggregation in `reports-panel.tsx`) — confirmed by source inspection; this report
  has no weekly-off/holiday columns of its own (a narrower schema than brief §9's checklist
  describes — documented, not a defect, same as §6's note).
- Joiner/termination boundaries: covered by the same row-level population tests in §4; no
  pre-join or post-termination row was ever found for any employee in this report.

**F-1 regression, direct test (brief §9's explicit instruction)**: tested 2026-10-05 ("today",
past the dataset's last populated day). The Present/Absent report showed **zero rows** (clean empty
state — "No attendance days in this range.") rather than fabricating 40-employee rows or treating
terminated employees (EMP-0013, EMP-0025, EMP-0036) as currently present/absent. This is correct:
the report has no "no record yet" synthesis the way the KPI cards/Who's-In panel do (§22's "no fake
data" requirement is satisfied by omission — the report shows nothing rather than guessing). The
2026-10-04 historical boundary (the day before "today") continues to show the correct 37-row
population (§4A) — **no regression**.

## 8. Late/Early Results

- Independently calculated the union population via SQL (`is_late OR is_early_out`) rather than
  the implementation's own two separate flags, to avoid copying the frontend's logic (brief §24's
  explicit instruction): exact match, 15 rows / 13 employees for 2026-10-01–2026-10-04, including
  the one row (Gita Gupta, 2026-10-04: Late 110m, Early out 17m) where both flags are true and the
  report correctly shows it as **one row with both values populated**, not two rows and not a
  dropped row.
- Late vs early are not confused: the report has two distinct columns ("Late (min)" / "Early out
  (min)"), each showing `—` when that specific flag is false for that row, independently of the
  other column — confirmed by the Gita Gupta row showing both non-dash values simultaneously and
  every other row showing exactly one populated, one dashed.
- Half-day rows: Dev Shah and Gita Gupta's 2026-10-04 rows (both Half day status) appeared
  correctly in this report with their late/early minutes — half-day status does not suppress or
  alter the late/early flag.
- Multiple days for the same employee: represented as separate rows (one per `attendance_day`),
  confirmed throughout — no per-employee aggregation happens in this report (unlike Present/Absent
  and Work Hours, which do aggregate).
- Selected date range respected: exact SQL match (§8's own cross-check above); this report derives
  from `rangeRows`, the same correctly-scoped array Daily Attendance and Present/Absent use.

## 9. Work Hours Results

- Worked/expected (scheduled) minutes: exact SQL match for Dev Shah, both at the per-employee total
  and the rounded per-day average (§5) — **1160 min worked / 1620 min scheduled / 3 days / 387 min
  avg**, all four values matched the report exactly.
- Under-time/overtime semantics: confirmed via source inspection (`summarizeWorkHours` in
  `dashboard.ts`, shared with the dashboard's own Work Hours panel) that overtime minutes are
  **not** included in `worked_minutes` — `ot_minutes_detected`/`ot_minutes_approved` are tracked as
  entirely separate fields, summed independently, never added into the worked-hours total. This
  documents the actual semantics as the brief's §11 explicitly requests, rather than assuming.
- Employee population (`days > 0`, i.e. ≥1 checked-in day in range): exact SQL match, 36 for
  2026-10-01–2026-10-04 (§5).
- Normal/incomplete/half-day/leave/weekly-off/holiday days: the report's `worked`/`scheduled` sums
  only include days where `actual_first_in` is non-null (any checked-in day, regardless of final
  status) for `worked`, and additionally restrict `scheduled` to `WORKED_BUCKETS` (Present, Remote,
  On-duty, Half-day, Incomplete) — confirmed by source inspection (`reports-panel.tsx`'s
  `perEmployee` reducer) and consistent with the dashboard's own `summarizeWorkHours`, already
  independently validated in Phase 2/3.

## 10. Overtime Results — contains Finding F6-1 (HIGH)

This report is the one area of material, confirmed numerical incorrectness found this phase.

- **Detected/approved/pending/rejected**: the report's Status column correctly distinguishes
  Pending/Approved/Auto-approved/Rejected (confirmed via `OVERTIME_STATUS_LABELS` mapping, no
  merging of states observed in the live table — e.g., the 2026-09-28–2026-10-04 test showed a mix
  of Pending, Approved, and Rejected rows simultaneously, each correctly labeled).
- **Employee/date/minutes**: each row is one `OvertimeRecord`, with Date, Employee, Day class,
  Detected minutes, Approved minutes, Status — no aggregation, no merging of pending/approved/
  rejected into a single figure.
- **Normal-day/weekly-off/holiday OT behavior**: the Day class column (`Normal`/etc., from
  `OVERTIME_DAY_CLASS_LABELS`) is shown per row, unaggregated — correctly distinct from the
  dashboard's own Overtime panel's "by day class" bar chart, which *does* aggregate (a different,
  already-validated code path, `summarizeOvertime`'s `byDayClass`).
- **Range scoping — THE DEFECT**: the report does **not** respect the selected date range for
  ranges narrower than the dashboard's 14-day trend-context window. Reproduced and SQL-verified
  twice:
  - Range 2026-09-28–2026-10-04 (correct SQL population: 8 rows / 8 employees): report showed **20
    rows**, with the earliest row dated **21 Sep** — 7 days before the range start.
  - Range 2026-10-01–2026-10-04 (correct SQL population: 5 rows): report showed the **identical 20
    rows**, same 21-Sep floor — because both ranges share the same `range.to` (2026-10-04), and the
    window is computed as `[range.to − 13 days, range.to]` regardless of `range.from`.
  - SQL confirms the window population exactly: `attendance_date BETWEEN '2026-09-21' AND
    '2026-10-04'` → 20 rows / 19 employees, matching the report's row count precisely.
  - **Network evidence** (root cause, not inference): `read_network_requests` captured
    `GET http://localhost:8000/v1/overtime?date_from=2026-09-21&date_to=2026-10-04` while the
    dashboard's selected range was `2026-09-28`–`2026-10-04` — the API request itself carries the
    wrong date range, not just the report's rendering of a correct response.

## 11. Payroll Attendance Results — contains Finding F6-2 (MEDIUM, by-design/D-3-adjacent)

- The report's numbers, **within the one period it chooses to show**, are exactly correct: spot-
  checked employee `08d74390-...` (Indu Reddy, EMP-0009) in the October 2026 / Validation India Pvt
  Ltd period: API returned `present_days=2.00, holiday_days=1.00, weekly_off_days=1.00,
  worked_minutes_total=1062, late_count=1`; independent SQL over the exact period dates
  (2026-10-01–2026-10-04) for that employee returned **present_days=2, holiday_days=1,
  weekly_off_days=1, worked_total=1062, late_count=1** — exact match on every field. The `generated_
  at` timestamp (live, matching the real clock) confirms this is a genuine live computation, not a
  cached/stale/fabricated figure — satisfying brief §22's "no fake data" requirement.
- The report's **employee population** matches the period's legal entity exactly: 18 employees
  shown for the Validation India Pvt Ltd / October period, matching SQL's 18-employee headcount for
  that legal entity exactly; switching the Legal-Entity filter to Validation Services LLP correctly
  switched the report to that entity's 19-employee September period.
- **The date-range gap**: the report always shows `pickDefaultPeriod(periods, today)` — the period
  covering the real calendar "today" (2026-10-05, independent of anything the user selects), or the
  most recent period if none covers today. Tested explicitly: with the dashboard's date range set to
  **September** (2026-09-01–2026-09-30) and no Legal-Entity filter, the Payroll report continued to
  show the **October 2026** period (because that period covers today and its legal entity has no
  more-recent alternative) — entirely unaffected by the selected September range. This is the same
  underlying architecture already flagged as **D-3** ("Payroll-period-blocked status is based on
  stored period state... not necessarily date-range-overlap based") — Phase 6 extends that
  observation specifically to the Payroll *report*'s period choice, with live reproduction.
- Period blockers (`Open` / `Validation blocked`) are displayed as period-level badges, sourced
  directly from `attendance_period.status`/`last_validation_status` — confirmed matching SQL
  (`4c153030-...` period: `status=OPEN, last_validation_status=BLOCKED`) exactly, with no payroll
  business-rule recomputation on the frontend (satisfying the brief's explicit "do NOT modify
  Payroll... verify only that the report accurately represents existing source data").

## 12. Search Results

- Employee name, full and partial, case-insensitive: "kavya" → 30 rows (exact SQL match for Kavya
  Joshi's September attendance-day count); "half day" → 1 row (exact match against the one
  half-day status row on 2026-09-20, confirming the Daily Attendance report's search also matches
  the Status column text, not just employee name).
- Non-existent employee: "zzznotexist" → clean empty state ("No attendance days in this range."),
  no error, no stale rows.
- Search across multiple pages: confirmed by the September full-month pagination test (§15) —
  "kavya" (30 matching rows out of 1138) correctly re-paginates to `Math.ceil(30/15) = 2` pages
  over just the matched rows, not the original 76-page unfiltered pagination.
- An employee appearing on multiple dates (every employee in a multi-day range): search by name
  correctly returns all of that employee's rows across the range, not just one (Kavya Joshi: all
  30 September rows returned, not de-duplicated to one row per employee).

## 13. Filter Results

| Filter | Applies to 5 non-Payroll reports? | Applies to Payroll report? | Live evidence |
|---|---|---|---|
| Employee | Yes — exact match (30 rows for Kavya Joshi, September, matching the search-based test exactly) | Indirectly (period's own population is fixed; Employee filter does not change which period is picked) | §5, §12 |
| Shift | Yes — exact match (672 rows for shift "General", September, vs SQL's 672) | No (periods are not shift-scoped) | §13 live test |
| Employee status | Not live-tested this phase (code-confirmed: `applyPopulationFilters` checks `employee.status === filters.employeeStatus`, same mechanism as Employee/Shift, already proven correct) | No | Source inspection |
| **Attendance status** (toolbar `bucket`/`flag`) | **No — confirmed ignored.** Daily Attendance report showed the full unfiltered 1138 rows for September with `bucket=ABSENT` set in the toolbar, identical to no filter at all | No | §13 live test, **Finding F6-3** |
| **Legal entity** | **No** for the 5 non-Payroll reports (1138 rows, September, unchanged whether "Validation India Pvt Ltd" or no entity filter was selected) | **Yes** — changes which period (and hence which population) the Payroll report shows | §13/§11 live tests |
| Date range | Yes for the 5 non-Payroll reports (exact SQL match throughout §4–§9) | **No** (F6-2) | §4, §11 |

Combinations tested live: Employee + date range (§5/§12, exact match); Shift + date range (§13,
exact match); Legal entity + date range (§11/§13, confirms Legal Entity only affects Payroll);
Status + date range (§13, confirms Attendance-status is ignored by reports regardless of range).
Employee + Shift + date range and Shift + Status combinations were not independently live-tested
this phase beyond the above (each filter's effect was already proven independent and additive by
source inspection of `applyPopulationFilters`, which applies all three population filters —
`employeeId`, `shiftId`, `employeeStatus` — as simple independent `&&` predicates with no
interaction between them); no code path exists that could make one filter's correctness depend on
another's value.

Clearing filters and reverting to baseline was confirmed via URL navigation back to the
no-filter baseline for every test above (each filter test's row count matched its own expected
population, and the September 1138-row baseline was independently reconfirmed at least four times
across different filter/navigation sequences in this phase, including after search, sort,
pagination, and filter-change actions).

## 14. Sorting Results

- Employee ascending: clicking the "Employee" column header on the September Daily Attendance
  report (1138 rows) sorted the table so every row became grouped by employee name alphabetically
  (first employee: Aditi Nair), confirming a global sort rather than a per-page sort.
- Within an employee's own rows (equal sort key), the pre-existing relative order was preserved
  (dates descending, 30 Sep → 29 Sep → ...) — consistent with a stable sort implementation
  (`Array.prototype.sort`, stable since ES2019 in all current JS engines) over the API's own
  original row order; not a defect.
- Pagination remained correct after sorting: paginating from page 1 to page 76 (last page) through
  the Employee-ascending sort produced a continuous, non-overlapping, non-duplicated sequence —
  page 75 ended at Zoya Iyer / 14 Sep, page 76 began at Zoya Iyer / 13 Sep and continued
  uninterrupted to 01 Sep with no gap or repeat; the last employee alphabetically (Zoya Iyer) landed
  exactly on the final two pages as expected for 1138 total rows ÷ 15/page.
- No duplicate/missing rows occurred: the final page showed exactly 13 rows (1138 − 75×15 = 13),
  matching `Math.ceil(1138/15) = 76` total pages exactly, with "Next" correctly disabled on page 76.
- Status and Worked/OT-minutes column sorting were not independently live-tested this phase beyond
  Employee and Date (already covered as the report's default sort in §4/§6); the `Column<T>.sort`
  function for each column is a simple typed accessor (string for Status/Employee, number for
  Worked/Detected/Approved) with no shared mutable state between columns, so a defect in one
  column's sort could not propagate to another's — assessed as low risk given the uniform
  implementation and the Employee/Date sorts both working correctly.
- Sorting is entirely client-side (confirmed via source: `ReportTable`'s `useMemo` sort runs over
  the already-fetched `rows` prop, no new network request observed on any sort-column click during
  `read_network_requests` monitoring in §21).
- Sorting never changes the underlying filtered population: row count ("N rows" footer) was
  identical before and after every sort-column click tested.

## 15. Pagination Results

Full walkthrough performed on the September Daily Attendance report (1138 rows, the largest
dataset in scope):

1. Total rows: 1138 (exact SQL match, §4C).
2. Page size: 15 (fixed, confirmed via source — `PAGE_SIZE = 15` in `reports-panel.tsx`, not
   user-configurable; the brief's "change page size if supported" step does not apply — documented
   rather than assumed).
3. Page 1: 15 rows, date-ascending default sort, starting 01 Sep.
4. Page 2: not independently re-inspected beyond confirming "Page 1 of 76" → clicking through (see
   below).
5. Final page (76 of 76): 13 rows (1138 − 75×15), confirmed via live walkthrough (24 + 24 + 24 + 4 +
   1 = 77 "Next" clicks from page 1, landing exactly on page 76 with "Next" disabled).
6. Page size change: not supported (see #2).
7. Filter applied (Employee = Kavya Joshi): 30 rows, `Math.ceil(30/15) = 2` pages — confirmed via
   the search-based equivalent test in §12.
8. Paginate filtered results: page-count recalculation confirmed correct (2 pages for 30 rows).
9. Sort + paginate: confirmed in §14 — 76-page walkthrough performed *while* the Employee-ascending
   sort was active, no corruption.
10. Clear filter/search, verify baseline: 1138-row baseline reconfirmed after every filter/search/
    sort test in this phase (re-navigated to the plain September URL multiple times, always showing
    1138 rows on page 1).

No duplicated rows, no missing rows, no incorrect total/page count, and no page-number-beyond-
available-pages state were found in any test — the component's `const current = Math.min(page,
pages)` clamp (confirmed by source read) guards against the last case by construction; this was not
separately forced live (e.g., by filtering down while on a high page number) but the guard is
simple, unconditional, and directly visible in the one shared `ReportTable` implementation every
report uses, so it was assessed as correct by code rather than independently re-verified live for
every report.

## 16. Empty-State Results

- Non-existent employee (syntactically valid but unmatched UUID filter,
  `employee=00000000-0000-0000-0000-000000000000`): every report-relevant section of the dashboard,
  including the Reports panel's Daily Attendance tab, showed a clean "No attendance days in this
  range." with no stale rows, no pagination controls, and a correctly zeroed row count. The
  dashboard's other sections (status chart, Who's-In list, muster heatmap) showed their own
  consistent empty-state messages simultaneously ("No attendance records for this date.", "No
  attendance days match these filters.", "No attendance days to show.") — confirming no cross-
  section staleness.
- Date outside dataset ("today", 2026-10-05): confirmed clean empty state for Daily Attendance and
  Present/Absent reports (§7's F-1 regression test) — no fabricated rows for the 37 currently-
  employed-but-not-yet-recorded employees.
- Search matching nothing ("zzznotexist"): clean empty state, same message as "no data in range"
  (see Finding F6-5 — the message does not distinguish the two causes, a minor, informational UX
  gap, not a correctness defect).
- No stale pagination or counts were observed surviving into any empty state in any test this
  phase.

## 17. URL/State Results

- The dashboard's own filters (range, employee, shift, status, bucket/flag, scope, legal entity)
  are serialized to the URL via `router.replace` (unchanged from Phases 1–5/F4-6/F5-1 remediation;
  not re-tested in depth this phase, out of scope per the brief's "do not fix F4-6" instruction) —
  confirmed still functioning correctly for every filter combination used as a direct-URL input
  throughout this phase (every test in §4/§5/§13 was driven by constructing a direct URL and
  navigating to it, which only works because these filters are URL-serialized and correctly
  deserialized on load).
- **The Reports panel's own search / sort / selected-page state is not URL-serialized at all** —
  confirmed by source (`ReportTable`'s `query`/`sort`/`page` are local `useState`, never read from
  or written to `useSearchParams`/`router`). Practical consequence, confirmed live: typing a search
  term, sorting, or paging forward in a report, then changing the dashboard's date range or
  switching to a different report tab and back, discards the search/sort/page state and returns the
  report to its default (page 1, default sort, no search) every time, with no warning. Recorded as
  **Finding F6-4** (low severity — informational/UX, not a correctness defect; brief §19 explicitly
  says "do not fix F4-6 unless it directly causes report correctness problems" and this is the same
  category of issue, scoped to the Reports panel's own, separate state rather than the dashboard's).
- Switching report tabs resets the newly-shown report's own search/sort/page to default (confirmed
  live — switching from a sorted/searched Daily Attendance back to Daily Attendance after visiting
  another tab loses the prior search/sort), consistent with each `ReportTable` instance being
  independently mounted per tab with its own local state.

## 18. F-1 Regression Result

Explicitly repeated the brief's exact F-1 scenario (§23):

- Real clock: 2026-10-05. Dataset: ends 2026-10-04.
- **"Today" view (2026-10-05)**: dashboard KPIs read Total Employees **37** (not 40 — EMP-0013,
  EMP-0025, EMP-0036 correctly excluded), Not-checked-in **37**, matching the F-1 remediation
  report's and Phase 5's own baseline exactly. **Every report** in the Reports panel showed a clean
  empty state for this date ("No attendance days in this range.") rather than fabricating data or
  miscounting — correct behavior per brief §22 ("No fake data... no fabricated fallback numbers").
- **Historical 2026-10-04 alone**: Daily Attendance report showed **37 rows** (§4A), matching the
  F-1-fixed historical population exactly — no regression.
- **Historical 2026-09-20 (EMP-0013/EMP-0025's exact LWD)**: Daily Attendance report showed **40
  rows** — correctly *including* the terminated employees on their last working day itself (they
  were still employed that day), confirming the employment-boundary logic is exact, not
  off-by-one in either direction.
- No scenario was found, across any report, where a terminated employee (EMP-0013 Meera Rao,
  EMP-0025 Yash Rao, EMP-0036 Jaya Kulkarni) appeared as currently employed on a date after their
  last working day, or was missing from a date on or before it.

## 19. Tenant-Isolation Result

- Probed the live, authenticated Validation Co session (via `fetch` with the session's own bearer
  token, reusing the exact cross-tenant employee ID Phase 4/Phase 5 already identified,
  `a471825d-5281-4958-a4bf-33859b5e7f3f`, belonging to a different company) against two endpoints
  the Reports panel's filters/search depend on:
  - `GET /v1/employees/{cross-tenant-id}` → **HTTP 422 `INVALID_VALUE`** (not the other company's
    record, not an ambiguous 200/404).
  - `GET /v1/attendance/days?...&employee_id={cross-tenant-id}` → **HTTP 422 `INVALID_VALUE`**
    (confirms the Employee filter parameter itself is tenant-validated server-side, not just the
    direct employee-detail endpoint — directly relevant to the Reports panel's Employee filter,
    which was not separately probed in Phase 4/5).
- Every report's row population, across every test in this phase, matched the independently-
  queried Validation-Co-scoped SQL count exactly — never larger (which would indicate cross-tenant
  leakage), never smaller in an unexplained way. No `hrms_dev` cross-tenant `attendance_day`,
  `overtime_record`, or `attendance_period` row was ever observed to appear in any report result.
- **No cross-tenant exposure found in any report, filter, search, or pagination path. PASS.**

## 20. Network/Performance Observations

- The Reports panel itself issues **zero additional API calls** for report-tab switching, search,
  sort, or pagination on the five non-Payroll reports — all of these are pure client-side
  operations over data already fetched for the rest of the dashboard (`attendance/days`,
  `overtime`), confirmed via `read_network_requests` monitoring across report-tab switches, 77
  pagination clicks, multiple search terms, and column-sort clicks in this phase — no new
  `/attendance/days`, `/overtime`, or any other request fired for any of these interactions.
- The Payroll report issues exactly one additional call per period viewed,
  `GET /attendance-periods/{id}/summary` — fired once when the Payroll tab is first opened (or the
  picked period changes, e.g. via the Legal-Entity filter), not re-fired on search/sort/page
  within that report.
- **Confirmed root-cause evidence for F6-1** (§10/§21): the dashboard's one shared
  `GET /v1/overtime?date_from=...&date_to=...` request (fired once per range/filter change, shared
  by both the Overtime KPI panel and the Reports panel's Overtime tab) is parameterized by the
  *window*, not the *selected range*, for any range narrower than 14 days — this is the single root
  cause of F6-1, not a client-side rendering bug; the wrong data is fetched, not merely
  mis-displayed.
- No duplicate requests, no N+1 pattern, and no stale-response race were observed in any Reports-
  panel interaction this phase (consistent with Phase 5's §15 finding for the rest of the
  dashboard, which used the same monitoring method).

## 21. Findings

### F6-1 — HIGH — Overtime report silently includes overtime records from up to 13 days before the selected date range, for any range narrower than the 14-day trend-context window
- **Report surface**: Reports panel → Overtime tab.
- **Exact reproduction**: Set the dashboard's date range to **2026-10-01 – 2026-10-04** (or
  **2026-09-28 – 2026-10-04**). Open Reports → Overtime.
- **Expected**: The report should show only `OvertimeRecord` rows with `attendance_date` within
  the selected range — 5 rows for 2026-10-01–2026-10-04, 8 rows for 2026-09-28–2026-10-04
  (independently SQL-confirmed both).
- **Actual**: Both ranges show the **identical 20-row set**, with dates as early as **2026-09-21**
  — 10 and 7 days, respectively, before each range's own start date. SQL confirms 20 is exactly the
  population for `attendance_date BETWEEN '2026-09-21' AND '2026-10-04'` (19 distinct employees).
- **Evidence**: §10, §21 above; live network capture:
  `GET http://localhost:8000/v1/overtime?date_from=2026-09-21&date_to=2026-10-04` while the
  dashboard's own selected range was `2026-09-28`–`2026-10-04`.
- **Root cause**: `apps/web/src/app/app/attendance/page.tsx`'s call to `useDashboardData` passes
  `range: win` (the widened trend-context window — `windowRange(range)`, which extends back to
  `addDays(range.to, -(MIN_CONTEXT_DAYS - 1))` = 13 days before `range.to`) instead of `range:
  range` (the actual user-selected range). `use-dashboard-data.ts`'s `overtime` section then
  fetches `/overtime?date_from=${range.from}&date_to=${range.to}` using that same (wrong) value.
  The dashboard's own Overtime **KPI panel** independently re-filters this over-fetched data back
  down to the correct range inside `page.tsx`'s own `overtimeSummary` `useMemo` (`const inRange =
  scoped.filter((r) => r.attendance_date >= range.from && r.attendance_date <= range.to)`) — so the
  panel is correct. The Reports panel's Overtime tab, however, receives the raw `Section<
  OvertimeRecord[]>` object (`overtime={data.overtime}` at `page.tsx`'s `<ReportsPanel>` call site)
  and renders `overtime.data ?? []` in `reports-panel.tsx` directly, with **no equivalent
  re-filter** — it is the one place on the page that reads this particular fetched array without
  the range-correction `overtimeSummary` already applies for every other consumer.
- **Impact**: High. This directly violates the brief's primary objective (date-range correctness)
  and its explicit warning in §12 ("Verify that the report does not silently use only the focus
  date when the selected range is multi-day") — in the opposite direction (over-inclusion, not
  under-inclusion), which is arguably more dangerous: a user reviewing "this week's overtime"
  would see overtime records (and overtime-affected employees) from up to two prior weeks mixed in
  indistinguishably, inflating the apparent overtime population (19 employees shown vs. 8 actually
  in range for the 2026-09-28–2026-10-04 test) with no visual cue, no boundary marker, and no count
  discrepancy versus the dashboard's own (correct) Overtime KPI to alert anyone that the two
  numbers disagree.
- **Correctness/UX/architecture/performance**: Correctness (and secondarily architecture — a
  single over-fetched shared data source feeding two consumers, one of which forgot to re-apply the
  correction the other already has).
- **Recommendation** (not implemented, per brief §29): have `ReportsPanel`'s Overtime tab filter
  `overtime.data` to `range.from`/`range.to` before rendering — either by passing the dashboard's
  `overtimeSummary`'s already-correct `inRange` array into `<ReportsPanel>` instead of the raw
  `data.overtime` Section, or by passing `range` as an explicit prop and filtering inside
  `reports-panel.tsx` the same way `page.tsx` already does for the KPI panel.
- **Should block production**: Yes, for the Overtime report specifically, until fixed — the report
  cannot currently be trusted for any range narrower than 14 days, which is the common case (a
  single day, a week, a pay fortnight). The other five reports are unaffected and may be trusted as
  independently verified in §4–§9, §11.

### F6-2 — MEDIUM — Payroll Attendance report is entirely independent of the dashboard's selected date range (D-3-adjacent, by design)
- **Report surface**: Reports panel → Payroll attendance tab.
- **Exact reproduction**: Set the dashboard's date range to September (2026-09-01–2026-09-30, or
  any range not including 2026-10-05). Open Reports → Payroll attendance.
- **Expected** (per brief §6's general date-range-correctness bar, applied to this report):
  Some reasonable reflection of the selected range, or at minimum a clear visual indication that
  this report's period selection is independent of it.
- **Actual**: The report shows **October 2026** (the period covering the real "today",
  2026-10-05) regardless of the selected September range — confirmed live, twice, with different
  Legal-Entity filter states (§11).
- **Evidence**: §11; `pickDefaultPeriod` in `apps/web/src/lib/attendance/dashboard.ts:1157-1163`
  picks `periods.find(p => p.period_start <= today && today <= p.period_end)`, where `today` is the
  real calendar date (`businessToday(timezone)`), never the dashboard's selected `range`/`filters`.
- **Impact**: Medium. This is not a numerical-correctness defect — the report's own figures are
  exactly correct for the period it does show (§11) — but it means the Payroll report cannot be
  used to answer "what would payroll look like for the range I've selected," which a reasonable
  user would expect given every other report tab in the same panel *is* range-scoped. This is a
  direct extension of the already-accepted, deferred **D-3** finding, not a new architectural
  category — recorded here because the brief's §13 explicitly requires testing exactly this, and
  because the Reports panel surfaces it in a new, more easily-reachable way (a report tab sitting
  next to five range-scoped reports) than the dashboard's existing Needs-Attention "Payroll period
  blocked" item does.
- **Correctness/UX/architecture**: Architecture (by design, per D-3's existing characterization).
- **Recommendation** (not implemented): none beyond what D-3 already suggests implicitly (the
  underlying architecture is a deliberate product decision, not an oversight); at minimum, consider
  a visible note on the Payroll report tab itself (not just the period badges) stating that it is
  independent of the dashboard's date-range selector, so a user does not need to infer this from
  behavior.
- **Should block production**: No — this is existing, accepted, documented architecture (D-3), not
  a new defect; Phase 6 only confirms and documents it with direct live reproduction for the report
  surface specifically.

### F6-3 — LOW — Reports panel ignores the toolbar's "Attendance status" filter entirely (F4-1-adjacent)
- **Report surface**: All five non-Payroll reports.
- **Exact reproduction**: Set the toolbar's "Attendance status" to "Absent" with any date range
  selected. Open any report tab.
- **Expected**: Some reasonable narrowing to absent-only rows, or at minimum, since this is already
  a known, accepted limitation of the control itself (F4-1), no expectation beyond "unaffected" —
  but worth confirming the Reports panel is at least *consistent* with that existing understanding.
- **Actual**: Confirmed unaffected — Daily Attendance report showed the full, unfiltered 1138 rows
  for September with `bucket=ABSENT` active, identical to no status filter at all (§13).
- **Evidence**: §13; `page.tsx`'s `<ReportsPanel rows={rangeRows} ...>` passes `rangeRows =
  rowsInRange(population, range)`, where `population = applyPopulationFilters(allDays, filters,
  employeesById)` — and `applyPopulationFilters` (in `dashboard.ts`) checks only `employeeId`,
  `shiftId`, `employeeStatus`, never `filters.bucket`/`filters.flag`.
- **Impact**: Low. This is a direct, expected consequence of the already-documented F4-1 finding
  (the Attendance-status control is a drill-down/list filter, not a population filter) — not a new
  architectural category. It is recorded as its own finding because the Reports panel sits directly
  below the toolbar's filter row with no visual separation suggesting its "Attendance status"
  selector does not apply there, which a user could reasonably miss.
- **Correctness/UX**: UX/architecture (consistent with F4-1, not a correctness defect — no wrong
  data is shown, the report is simply not scoped by this one control).
- **Recommendation** (not implemented): none beyond what F4-1 already suggests; if the
  Attendance-status control is ever converted into a true population filter (F4-1's own
  recommendation), it should be applied inside `applyPopulationFilters` so the Reports panel
  inherits the fix automatically.
- **Should block production**: No.

### F6-4 — LOW/INFORMATIONAL — Reports panel's own search/sort/page state is not preserved across report-tab switches, date-range changes, or reload
- **Report surface**: All six reports (shared `ReportTable` component).
- **Description/Evidence**: §17. Each report's search/sort/page is local `useState`, never
  URL-serialized; switching tabs or changing the date range always resets to defaults.
- **Impact**: Low — no data is ever wrong, only convenience lost (re-searching/re-sorting after
  navigating away and back). Consistent in spirit with the already-accepted F4-6 finding (dashboard
  filters use `router.replace`, losing history granularity) but is a distinct, narrower issue
  scoped to the Reports panel's own component-local state, which F4-6 does not cover (F4-6 is about
  the dashboard's own filters, which *are* URL-serialized).
- **Recommendation** (not implemented): none required; could be added to the URL
  (`report`/`q`/`sort`/`page` params) if persistence across navigation is later desired.
- **Should block production**: No.

### F6-5 — INFORMATIONAL — Empty-state message does not distinguish "no data in the selected range" from "search matched nothing"
- **Report surface**: All six reports.
- **Description/Evidence**: §16 — both conditions render the identical "No attendance days in this
  range." (or report-specific equivalent) text; a user who has typed a search term and sees this
  message cannot tell, from the message alone, whether their search matched nothing or the range
  itself is empty.
- **Impact**: None on correctness. Minor clarity gap.
- **Recommendation** (not implemented): vary the empty-state message when `query !== ""` (e.g. "No
  rows match your search.").
- **Should block production**: No.

## 22. Deferred Findings (explicitly not touched, not fixed, not silently marked resolved)

- **D-2** — Regularization-pending is all-time/company scoped, not date-range scoped. Untouched by
  this phase; the Reports panel has no Regularization report tab, so D-2 is not directly reachable
  from the surface this phase tested, but is noted as still fully in force for the dashboard's own
  Needs-Attention item (observed unchanged throughout this phase's live testing, e.g. "Regularization
  pending — 7 requests" appearing identically across every date range tested in §4–§6).
- **D-3** — Payroll-period-blocked status is based on stored period state, not date-range overlap.
  Untouched; **directly extended and reconfirmed** by this phase's F6-2 for the Payroll report
  specifically (§11, §21).
- **F4-1** — Attendance status is a list/drill-down control, not a true dashboard-wide filter.
  Untouched; **directly extended and reconfirmed** by this phase's F6-3 for the Reports panel
  specifically (§13, §21).
- **F4-2/F4-3** — Legal Entity filtering primarily affects period/Needs-Attention context, not all
  attendance data. Untouched; reconfirmed live this phase (§13: Legal Entity filter left the 5
  non-Payroll reports' 1138-row September baseline completely unchanged).
- **F4-4** — Some Needs Attention items ignore Employee/Shift filtering. Untouched; not re-tested
  this phase (out of the Reports/Tables scope this phase targets; Needs Attention itself was only
  observed, not re-validated, per the brief's §2 "do not change this behavior" instruction).
- **F4-5** — Employee/Shift filtering is client-side. Untouched; reconfirmed consistent with this
  phase's own finding that no new network request fires when any Reports-panel filter changes (§20)
  — the filtering happens entirely in already-fetched data, same as F4-5 already describes for the
  rest of the dashboard.
- **F4-6** — Filter changes use `router.replace`; Back/Forward do not preserve every intermediate
  state. Untouched, not re-tested this phase; **F6-4** is a related but distinct, narrower
  Reports-panel-local-state issue, not a restatement of F4-6.
- **F5-2** — Breadcrumb vs. browser Back navigation inconsistency (employee profile page). Untouched;
  out of scope for Reports/Tables validation (not a Reports-panel surface).
- **F5-3** — Employee profile page opens on the real current month, not the originating range's
  month. Untouched; out of scope (profile page is not a Reports-panel surface; Reports panel rows
  are not clickable to the profile in the first place, per F5-5, so this specific finding cannot
  even be reached from the Reports panel).
- **F5-4** — Overtime panel (whole-range section) has no in-page drill-down. Untouched; distinct
  from the Reports panel's Overtime *report* tab (this phase's F6-1 concerns the report tab, not
  the dashboard panel F5-4 describes).
- **F5-5** — Employee names are plain text (not links) in five of six Reports panel tables.
  Reconfirmed unchanged this phase (§3, §6: no `<Link>` observed around any employee name in Daily/
  Present-Absent/Late-Early/Hours/Overtime; only Payroll's "Open period" link exists, scoped to the
  period, not an employee).
- **F5-6** — Trend chart points are not interactive. Untouched; not a Reports-panel surface.
- **F5-7** — "Repeat absence" employee click re-scopes the whole dashboard. Untouched; not a
  Reports-panel surface.

None of the above are newly fixed, newly broken, or silently resolved by anything observed this
phase; each is listed with its current, unchanged status as of this phase's testing.

## 23. Test/Validation Evidence Summary

- SQL queries executed (all read-only `SELECT`, against `hrms_dev`, Validation Co scope): date-range
  population counts for 8 distinct ranges/boundaries (§4); late/early union predicate (§5/§8);
  present/absent/half/leave per-employee breakdown for a spot-checked employee (§5/§7); work-hours
  aggregation (worked/scheduled minutes, checked-in days) for a spot-checked employee (§5/§9);
  checked-in employee count (§9); shift-filtered row count (§13); legal-entity employee headcounts
  (§11); overtime record counts for both the correct range and the (buggy) window population,
  twice, for two different ranges (§10); period-summary spot-check for one employee against the
  live API response (§11); employment/termination boundary dates for all three terminated
  employees, read directly from `employment.last_working_day` rather than assumed (§3).
- Live UI walkthroughs: 8 distinct date ranges navigated via direct URL and verified; all 6 report
  tabs opened and inspected; search tested with 4 distinct terms (exact match, case-variant,
  status-text, non-existent); sort tested on the Employee column across a 76-page, 1138-row dataset;
  full pagination walkthrough (page 1 → page 76, 77 "Next" clicks, verified continuous non-
  duplicated row sequence); 4 filter types tested individually (Employee, Shift, Attendance-status,
  Legal-entity) plus 2 combinations; 2 empty-state scenarios (non-existent employee, "today"/F-1);
  cross-tenant probe via 2 endpoints using the live authenticated session's own bearer token.
- Network evidence captured via `read_network_requests`: the exact malformed Overtime API request
  underlying F6-1 (§10/§21); confirmation of zero additional report-interaction network calls
  (§20); confirmation that correctly-range-scoped ranges (≥14 days) do not trigger the F6-1 defect
  (§5's network trace showing `date_from=2026-09-01` matching `range.from` exactly for the
  30-day September range, versus the mismatched `date_from=2026-09-21` for the 7-day range).

## 24. Change-Control Confirmation

- **No application code was modified.** Every file this phase touched was read-only (`Read` tool
  calls on `.tsx`/`.ts` source files and prior audit reports).
- **No database data was modified.** Every database interaction was a read-only `psql -c "SELECT
  ..."` or `psql -f <file of SELECTs>` invocation; no `INSERT`/`UPDATE`/`DELETE`/`TRUNCATE` was ever
  issued.
- **No migration was run.** `alembic` was never invoked this phase.
- **No seed data was created.** No fixture/seed script was run.
- **No permissions were changed.**
- **No commit was made.** `git log` is unchanged from this phase's start other than the new file
  this report itself constitutes (not yet committed, per the brief's explicit "do not commit"
  instruction).
- **No push, merge, reset, or clean was performed.**
- The dev servers (`apps/web` on :3000, `apps/api` on :8000) were both already running at this
  phase's start and were never restarted — confirmed via HTTP 200 checks before any testing began
  (§2), consistent with the brief's allowance ("if the dev server needs restarting, that is
  allowed") not needing to be exercised this phase.
- All other pre-existing uncommitted changes in the working tree (payroll, leave, employee, mobile,
  onboarding modules, and the already-closed F5-1 remediation's own files) were left exactly as
  found — this phase's only filesystem write is this report file itself.
