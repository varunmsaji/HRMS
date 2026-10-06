# Attendance Dashboard — F6-1 Remediation Report

## 1. Executive Verdict

**PASS.**

F6-1 (HIGH) is fixed: the Reports panel's Overtime tab now shows exactly the `OvertimeRecord`
population inside the dashboard's selected date range — never a row from before the range start —
verified against independent SQL at the exact employee/date/minutes/status level, not just by
matching row counts. The dashboard's own Overtime KPI panel (which was already correct) is
provably unchanged. The 14-day trend-context window is provably unchanged (the underlying fetch's
network parameters are byte-identical to before the fix). No other finding (F6-2..F6-5, D-2, D-3,
F4-1..F4-6, F5-2..F5-7, F5-1) was touched. No backend code, schema, or permissions were changed. No
commit, push, or merge was made.

## 2. F6-1 Root Cause

`apps/web/src/app/app/attendance/page.tsx` calls `useDashboardData({ window: win, range: win, ... })`
— both parameters receive `win`, the widened 14-day trend-context window, not `range`, the actual
user-selected range. This is intentional for `window` (the `days` fetch needs the wide window for
the trend chart and muster heatmap), but `range` is `use-dashboard-data.ts`'s own parameter name
for what scopes the **overtime** fetch (`GET /overtime?date_from=range.from&date_to=range.to`) — so
the overtime fetch was *also* scoped to the wide window, not the user's actual selection.

This was already compensated for once, in `page.tsx`'s own `overtimeSummary` — the dashboard's
Overtime KPI panel never read `data.overtime.data` directly; it read an `inRange`-filtered copy
(`scoped.filter((r) => r.attendance_date >= range.from && r.attendance_date <= range.to)`). But the
Reports panel's Overtime tab was wired to the raw, uncompensated `data.overtime` object
(`overtime={data.overtime}` at the `<ReportsPanel>` call site), which `reports-panel.tsx` renders
directly as `overtime.data ?? []` — the one place on the page that read this fetched array without
ever applying the range correction every other consumer already had.

## 3. Exact Files Changed

- [apps/web/src/app/app/attendance/page.tsx](../../apps/web/src/app/app/attendance/page.tsx):
  - Replaced the single `overtimeSummary` memo with three memos: `overtimeScoped` (the existing
    employee/shift/employee-status population filter, unchanged logic, now extracted so it can be
    reused), `overtimeRangeRows` (new — `overtimeScoped` additionally filtered to `range`), and
    `overtimeSummary` (now built from those two, producing byte-identical output to before — same
    `summarizeOvertime(inRange, range)` for the summary fields, same `summarizeOvertime(scoped,
    win).trend` for the trend).
  - Changed the `<ReportsPanel>` call site from `overtime={data.overtime}` to
    `overtime={{ ...data.overtime, data: overtimeRangeRows }}` — the Reports panel now receives the
    same range-corrected, population-filtered array the dashboard's own Overtime panel always used,
    instead of the raw, wide-window, unfiltered fetch result.
  - **No other line changed.** The `useDashboardData({ window: win, range: win, ... })` call itself
    is untouched — the fetch still requests the wide window (required for the trend chart), and the
    fix is entirely in what `page.tsx` does with the result before handing it to each consumer.
- [apps/web/src/app/app/attendance/page.test.tsx](../../apps/web/src/app/app/attendance/page.test.tsx):
  added a new `describe("Overtime report date-range scoping (F6-1)")` block with 3 tests (§15).

No backend file was touched. No change was made to `use-dashboard-data.ts`, `reports-panel.tsx`,
`dashboard.ts`, or any other component.

## 4. Exact Behavior Before/After

- **Before**: Reports → Overtime showed every `OvertimeRecord` in the 14-day trend window ending
  at the range's last day, regardless of the selected range's start date — e.g. 20 rows for both a
  4-day and a 7-day range that happened to share the same end date, both wrong.
- **After**: Reports → Overtime shows only `OvertimeRecord` rows whose `attendance_date` falls
  inside the selected range — 8 rows for 28 Sep–04 Oct, 5 rows for 01 Oct–04 Oct (§6), each an exact
  match to independent SQL at the row level, not just the count.
- **Unchanged**: the dashboard's own Overtime KPI panel (Total detected/Employees with
  OT/Pending/Approved/Rejected/By day class/Overtime trend) — already correct before this fix,
  confirmed to still read identical input and produce identical output (§9).

## 5. Selected Range vs. 14-Day Context Range

These remain exactly two different windows, as they must:
- `range` — the user's actual selection (`resolveRange(filters, today)`). This is what the Reports
  panel's Overtime tab, and every other report/panel on the page, must be scoped to.
- `win` — `windowRange(range)`, which widens `range` backward to at least 14 days ending at
  `range.to`, purely so the trend chart and muster heatmap have context before the selected range
  starts. `win` is still what the underlying `/attendance/days` and `/overtime` fetches request
  (confirmed unchanged — see §9's network trace); it was never correct to *also* use it as the
  Reports panel's display scope, which is what F6-1 was.

## 6. Original Reproduction — Before vs. After

Both of Phase 6's exact reproduction cases, re-run live against the same Validation Co dataset:

| Range | SQL rows (`overtime_record`, read-only) | Phase 6 (before fix) | This fix (after) |
|---|---|---|---|
| 2026-09-28 – 2026-10-04 | **8** | 20 (identical 21-Sep-floor set) | **8** |
| 2026-10-01 – 2026-10-04 | **5** | 20 (identical 21-Sep-floor set) | **5** |
| 2026-09-21 – 2026-10-04 (the old, wrongly-used `win`) | 20 / 19 employees | n/a | n/a — no longer used as the report's scope |

Confirmed live before re-applying the fix (temporarily reverted just the one `<ReportsPanel
overtime={...}>` line, reran the new test, confirmed it fails exactly the way the original bug
would, then restored the fix and reran — see §15).

## 7. Post-Fix Results — Exact Employee/Date Population

**Range 2026-09-28–2026-10-04** (SQL, read-only `SELECT`, 8 rows):

| Date | Employee | Minutes detected | Status | In UI? |
|---|---|---|---|---|
| 2026-09-28 | Jai Das (EMP-0010) | 32 | APPROVED | ✓ exact match |
| 2026-09-28 | Kiran Rao (EMP-0037) | 32 | REJECTED | ✓ exact match |
| 2026-09-29 | Chitra Nair (EMP-0003) | 31 | PENDING | ✓ exact match |
| 2026-10-01 | Gita Gupta (EMP-0007) | 32 | PENDING | ✓ exact match |
| 2026-10-01 | Venkatasubramanian C-R (EMP-0012) | 95 | PENDING | ✓ exact match |
| 2026-10-01 | Tara Khan (EMP-0020) | 102 | PENDING | ✓ exact match |
| 2026-10-01 | Xena Kulkarni (EMP-0024) | 63 | PENDING | ✓ exact match |
| 2026-10-03 | Farid Menon (EMP-0006) | 30 | PENDING | ✓ exact match |

The live UI table showed these exact 8 rows, in this exact Date/Employee/Day-class/Detected/
Approved/Status shape (`28 Sep Jai Das Normal 0h 32m 0h 32m Approved`, etc.) — every field matches,
no extra row, no missing row, no 21-Sep-floor row anywhere.

**Range 2026-10-01–2026-10-04** (SQL, 5 rows): the same table minus the two 28/29-Sep rows (Jai Das,
Kiran Rao, Chitra Nair) — confirmed live: the UI table showed exactly Xena Kulkarni, Venkatasubramanian
C-R, Gita Gupta, Tara Khan (all 01 Oct) and Farid Menon (03 Oct) — **5/5 exact match**, inclusive-start
boundary correctly excludes 28/29 Sep.

## 8. Dashboard Overtime Regression Result

Live, both ranges: the dashboard's own Overtime panel showed "Employees with OT: 8" for
28 Sep–04 Oct and "Employees with OT: 5" for 01 Oct–04 Oct — both exact matches to the same SQL
population as the (now-fixed) report, confirming the panel was never broken and remains unaffected.
Automated regression: a new test (`leaves the dashboard's own Overtime panel unaffected...`) asserts
`overtimeSummary`'s "Total detected" figure counts only an in-range record, not an out-of-range one
planted in the same mock response — passes both before and after the fix (it was never broken), and
exists to catch any future change that breaks the shared `overtimeScoped`/`overtimeRangeRows`
extraction.

## 9. Boundary Test Results

- **01 Oct–04 Oct**: confirmed live — 2026-09-30 overtime (none exists in this dataset after 28/29
  Sep's rows, so this reduces to the 28/29-Sep exclusion already shown in §7) is excluded; 2026-10-01
  is included (4 rows); 2026-10-04 would be included were there a record on it (none exists, but the
  SQL/UI both agree there isn't one — no omission). 2026-10-05 cannot be tested live (today, future
  relative to the dataset) but the same inclusive `<=` predicate used for every other boundary
  (confirmed by code reading `attendance_date >= range.from && attendance_date <= range.to`) applies
  identically.
- **09-28–10-04**: confirmed live — 2026-09-27 has no overtime record in this dataset (unaffected
  either way); 2026-09-28 is included (2 rows: Jai Das, Kiran Rao); 2026-10-04 included (none exists,
  no omission).
- Automated: the new test `includes both range boundary dates (inclusive start and end)` plants one
  record exactly on `range.from` and one exactly on `range.to` and asserts both appear — passes.
- **Network-level confirmation that `win` itself is untouched**: `read_network_requests` during both
  live range tests showed the underlying fetch unchanged — `GET /v1/overtime?date_from=2026-09-21&
  date_to=2026-10-04` for the 28-Sep–04-Oct selection (the same 14-day-wide `win` as before this fix;
  only the client-side filtering of the *result* changed, never the request).

## 10. Search/Filter/Sort/Pagination Regression

- **Employee filter** (brief §11's explicit example — "selected range = Sep 28 → Oct 4, employee
  filter = Kavya" generalized to an employee who actually has an OT record in range): selected Farid
  Menon via the toolbar's Employee dropdown with range 28 Sep–04 Oct active. Reports → Overtime
  dropped from 8 rows to **1 row**, showing only Farid Menon's 03-Oct record — exact match. This also
  closes a related, previously-unflagged gap the Phase 6 audit table noted in passing (the Overtime
  report applied no population filter at all, range or otherwise) — fixed as a direct consequence of
  reusing `overtimeScoped`'s existing employee/shift/employee-status logic, not as separate new work.
- **Search, sort, pagination**: not modified (`reports-panel.tsx` untouched) and not expected to
  behave differently — they operate on whatever `rows` array `ReportTable` receives, which is now
  correctly scoped instead of incorrectly scoped, with no change to how search/sort/pagination
  themselves work. Not independently re-tested live this task (out of scope per the brief — these
  were already validated as correct in Phase 6 for every report, including Overtime's search/sort/
  paging mechanics, which are generic and shared across all six reports).

## 11. F-1 Regression

Live, real clock 2026-10-05, dataset ending 2026-10-04: "Today" view shows Total employees **37**
(not 40) — terminated employees (Meera Rao EMP-0013, Yash Rao EMP-0025, Jaya Kulkarni EMP-0036)
correctly excluded, unchanged from every prior phase's result. F6-1's fix touches only
`overtimeScoped`/`overtimeRangeRows`/`overtimeSummary`/the `<ReportsPanel overtime=...>` prop — none
of which intersect `employeesWithoutRecord()`, `isEmployedOn()`, or any other F-1 code path.
**No regression.**

## 12. Tenant Isolation

Unaffected by construction: this fix is 100% a client-side re-filter of data the page already had
in memory from one existing, already tenant-scoped fetch (`GET /v1/overtime?date_from=...&
date_to=...`, gated server-side by `get_tenant_context`/`require_permission`, unchanged — no backend
file was touched). Confirmed via `read_network_requests` live: the overtime fetch's URL and
parameters are byte-identical before and after this fix (`date_from=2026-09-21&date_to=2026-10-04`
for the 28-Sep–04-Oct selection, exactly the pre-fix value) — no new parameter, no new request, no
new code path that could reach the backend with a different scope. **No cross-tenant exposure is
possible through this change.**

## 13. Automated Tests

- **Focused** (`page.test.tsx`, `dashboard.test.ts`, employee profile, `[id]`,
  `components/attendance`): **122 passed** (8 test files) — 119 pre-existing (post-F5-1 baseline) +
  3 new F6-1 tests.
- **New tests, individually confirmed to catch the real regression**: temporarily reverted only the
  one `<ReportsPanel overtime={...}>` line (reintroducing the exact F6-1 bug) and reran — the primary
  test (`excludes an overtime row before the selected range...`) failed exactly as expected
  (`Asha Rao` — the out-of-range planted record — appeared when it should not have); the other two
  tests (inclusive-boundary, dashboard-panel-unaffected) correctly continued to pass, since they guard
  behavior that was never broken. Restored the fix; all 3 pass again.
- **Full frontend suite** (`npx vitest run`): **505 passed** (61 test files) — 502 pre-existing
  (post-F5-1 baseline) + 3 new. One unrelated test failed once mid-run on an unmodified file
  (`isolates a failing section: the rest of the dashboard still renders and offers a retry`) —
  reproduced in isolation (passed cleanly, 1/1 and 43/43 for the whole file) and on a second full-suite
  run (passed cleanly, 505/505) — confirmed as pre-existing cross-file test-runner flakiness unrelated
  to this change, not a regression.
- **TypeScript** (`npx tsc --noEmit -p tsconfig.json`): clean, zero errors.
- **Production build** (`npm run build`): succeeded, zero errors or warnings, all routes compiled.
- **Backend**: not applicable — no backend file was changed.

(As in the F5-1 remediation, `npm run build` wrote into the live dev server's shared `.next`
directory, causing the same previously-documented transient stuck-loading state. Fixed the same
way: stopped the dev server, `rm -rf .next`, restarted. Not a code or data change.)

## 14. Remaining Findings

**Explicitly not touched, not remediated by this task:**
- F6-2 (Payroll Attendance report always shows today's period, independent of selected range)
- F6-3 (Reports panel ignores the toolbar's "Attendance status" filter)
- F6-4 (report search/sort/page state not URL-persisted)
- F6-5 (empty-state wording doesn't distinguish "no data" from "search matched nothing")
- D-2, D-3, F4-1..F4-6, F5-2..F5-7 (all previously deferred/accepted findings, unchanged)
- F5-1 (previously fixed and closed in an earlier task; reconfirmed unaffected — the `rangeScoped`/
  `scope` mechanism it introduced is untouched by this change)

## 15. Change-Control Confirmation

- **No commit.** `git log -1` is unchanged (`7ba4ce7`) throughout this task.
- **No push, no merge, no branch change, no reset, no clean.** Still on `main`.
- **No data modification.** All database access was read-only `SELECT` against `hrms_dev`.
- **No migration, no schema change.**
- **No unrelated files modified.** Only `apps/web/src/app/app/attendance/page.tsx` and
  `apps/web/src/app/app/attendance/page.test.tsx` were touched (both already had pre-existing
  uncommitted changes from the earlier, separate F5-1 task — this task's edits were layered on top of
  those, not a reversion of them). Every other pre-existing uncommitted change in the working tree
  (payroll, leave, employee, mobile, onboarding modules, and Phase 6's own new report file) was left
  exactly as found.
