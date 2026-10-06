# Attendance Dashboard — F5-1 Remediation Report

## 1. Executive Verdict

**PASS.**

F5-1 (HIGH) is fixed: every whole-range Needs Attention item's "View all →" drill-down now
filters the same `rangeRows` population its own count was computed from, instead of silently
narrowing to the focus date (`range.to`) alone. Every focus-date drill source (KPI card, status
chart, toolbar "Attendance status" select) is unchanged and independently verified to still
drill into the focus date only, even with a multi-day range selected. No other finding (D-2, D-3,
F-1, F4-1..F4-6, F5-2..F5-7) was touched. No backend code, schema, or permissions were changed.
No commit, push, or merge was made.

## 2. F5-1 Root Cause

Every bucket/flag drill-down on the dashboard — KPI card, status-chart segment, toolbar select,
and Needs Attention's "View all" — funnelled into the exact same client-side function,
`drill({ bucket, flag })` in `apps/web/src/app/app/attendance/page.tsx`. That function only ever
set a URL filter consumed by `applyDrillFilters(focusRows, filters)`, where `focusRows` is
`rowsOn(population, range.to)` — the single last day of the selected range. Meanwhile, Needs
Attention's counts (`buildAttentionItems({ rows: rangeRows, ... })`) are computed over
`rangeRows` — the *entire* selected range. There was no code path that routed a Needs-Attention
drill into `rangeRows`; the drill-down target and the number that produced it were simply two
different populations wearing the same UI.

## 3. Exact Files Changed

- [apps/web/src/lib/attendance/dashboard.ts](../../apps/web/src/lib/attendance/dashboard.ts) — added `scope: "" | "range"` to `DashboardFilters`/`DEFAULT_FILTERS`, and round-tripped it through `parseFilters`/`serializeFilters` (new `scope` URL param, omitted when `""`).
- [apps/web/src/app/app/attendance/page.tsx](../../apps/web/src/app/app/attendance/page.tsx) — `drill()` now accepts and threads a `scope` field (always reset to `""` when the caller omits it); added a `rangeScoped` flag and `listSource` (picks `rangeRows` vs `focusRows`); `listRows`/`listTitle`/the `WhosInPanel` `showDate` prop all key off it; "no record yet" synthetic rows are suppressed when range-scoped (they have no `attendance_date`).
- [apps/web/src/components/attendance/dashboard/needs-attention.tsx](../../apps/web/src/components/attendance/dashboard/needs-attention.tsx) — "View all →" now calls `onDrill({ bucket, flag, scope: "range" })` instead of `onDrill({ bucket, flag })`.
- [apps/web/src/components/attendance/dashboard/whos-in-panel.tsx](../../apps/web/src/components/attendance/dashboard/whos-in-panel.tsx) — new optional `showDate` prop; adds a "Date" column (desktop table + mobile cards) when a drill can span more than one day; the row-count footer says "N days" instead of "N employees" in that case (a range-scoped drill can list the same employee more than once, so "employees" would misstate the count).
- [apps/web/src/components/attendance/dashboard/kpi-grid.tsx](../../apps/web/src/components/attendance/dashboard/kpi-grid.tsx) — a KPI card is never shown "active" while a range-scoped drill with the same bucket/flag is active (different, incomparable population).
- [apps/web/src/components/attendance/dashboard/status-chart.tsx](../../apps/web/src/components/attendance/dashboard/status-chart.tsx) — same "active" guard as kpi-grid.tsx, for the status-chart bucket rows.
- [apps/web/src/components/attendance/dashboard/toolbar.tsx](../../apps/web/src/components/attendance/dashboard/toolbar.tsx) — the "Attendance status" select and the bucket/flag filter-chip "×" buttons now also clear `scope`, so a focus-date-scoped control never inherits a leftover range-scoped drill.
- [apps/web/src/lib/attendance/dashboard.test.ts](../../apps/web/src/lib/attendance/dashboard.test.ts) — new test: `scope` round-trips through the URL and is omitted by default.
- [apps/web/src/app/app/attendance/page.test.tsx](../../apps/web/src/app/app/attendance/page.test.tsx) — two new tests: (a) a whole-range Needs Attention drill with employees on both ends of a multi-day range shows both, not just the one on the focus date; (b) a focus-date KPI drill stays scoped to the focus date even when the same multi-day range is selected.

No backend file was touched (none was required — the drill-down was always 100% client-side,
filtering data already fetched and already tenant-scoped; see §9).

## 4. Exact Behavior Changed

- **Before**: clicking "View all →" on any whole-range Needs Attention item (missing punches,
  incomplete attendance, late arrivals, early departures, pending approval, work on approved
  leave, configuration errors) showed only the rows on the range's last day, under a list titled
  "Attendance on `<date>`" with no date column — silently representing a different, usually much
  smaller population than the count above it.
- **After**: the same click shows every row across the whole selected range, under a list titled
  "Attendance, `<range>`" with an added Date column (since the same employee can now appear more
  than once, on different days) and a footer reading "N days" instead of "N employees". The
  population size and distinct-employee count now always match the Needs Attention item's own
  count exactly (verified live and via SQL — §7).
- **Unchanged**: every focus-date drill (KPI card, status-chart segment, toolbar status select)
  still filters `focusRows` only, titled "Attendance on `<date>`", no date column, regardless of
  how wide the selected range is.

## 5. Confirmation: KPI Drill-Down Remains Focus-Date Scoped

Live test, Validation Co, range **28 Sep – 04 Oct 2026** (focus date 04 Oct): seeded via this
range, the "Late" KPI read **1** (Gita Gupta — the only late arrival *on 04 Oct specifically*).
Clicking it kept the list titled **"Attendance on 04 Oct"**, showed **exactly Gita Gupta**, no
Date column. This is the same behavior as before the fix — proven by the new regression test in
`page.test.tsx` ("keeps a focus-date KPI drill scoped to the focus date, not the whole selected
range"), which fails without the `scope` guard in `kpi-grid.tsx`'s active-state check being
absent, and passes with it.

## 6. Confirmation: Needs Attention Drill-Down Is Now Whole-Range Scoped

Same live range. Needs Attention read **"Missing punches — 27 days · 22 employees affected"**.
Clicking "View all →" now shows list titled **"Attendance, 28 Sep – 04 Oct"**, 27 rows across 2
pages, with a Date column — including Kavya Joshi appearing on **01 Oct, 03 Oct, and 04 Oct** (all
3 of her days in range — previously only 04 Oct showed, per the original Phase 5 finding).
Footer reads "27 days". Distinct employees across both pages: exactly 22.

## 7. Independent SQL Validation Results

All queries run read-only against `hrms_dev`, Validation Co (`c8592c12-eaf2-45f9-af98-f5366665a14f`),
range `2026-09-28`–`2026-10-04`:

| Item | SQL (days / employees) | Needs Attention panel | Drill-down population |
|---|---|---|---|
| Missing punches | 27 / 22 | 27 days · 22 employees | 27 rows (2 pages) / 22 distinct employees — **exact row-by-row match** against `SELECT employee_code, attendance_date ... ORDER BY` (verified every row, including Kavya Joshi's 01/03/04 Oct, Lata Iyer's 28/30 Sep + 01 Oct, Jaya Kulkarni's 28/29 Sep) |
| Late arrivals | 17 / 13 | 17 days · 13 employees | 17 rows / 13 distinct employees — exact match |
| Incomplete attendance (bucket-based, not flag-based — the other code path) | 9 / 9 | 9 days · 9 employees | 9 rows / 9 distinct employees — exact match |
| Early departures | 16 / 14 | 16 days · 14 employees | not independently drilled live; identical code path to the three above |
| Days pending approval | 8 / 8 | 8 days · 8 employees | not independently drilled live; identical code path |
| Work on approved leave | 1 / 1 | 1 day · 1 employee | drilled live: footer read "1 day", matching |
| Configuration errors | n/a (0 rows in this dataset, same as Phase 5) | not shown (0) | identical code path; could not be exercised with real data, same limitation Phase 5 noted |

Missing punches and late arrivals were verified at full row-level granularity (every
employee/date pair), not just the aggregate count, to rule out a coincidental count match hiding
a different population. Incomplete attendance exercises the `bucket`-based code path (the other
six items use `flag`), confirming the fix is generic rather than special-cased per item.

## 8. F-1 Regression Result

Live, Validation Co, real clock 2026-10-05 (dataset ends 2026-10-04):
- **"Today" view (2026-10-05)**: Total employees **37**, Not checked in **37** — identical to the
  Phase 5 baseline. Terminated employees (Meera Rao EMP-0013, Yash Rao EMP-0025, Jaya Kulkarni
  EMP-0036) do not appear.
- **Historical 2026-10-04 alone**: Total employees **37**, context reads "Employed on 04 Oct" (not
  "no record yet" — the today-only inference correctly never fires for a historical date).

Both match the F-1 remediation report's and Phase 5's own re-validation exactly. **No regression.**
F5-1's fix touches only which pre-filtered array (`rangeRows` vs `focusRows`) a drill-down reads
from — it does not touch `employeesWithoutRecord()`, `isEmployedOn()`, or any F-1 code path.

## 9. Tenant-Isolation Result

The drill-down (both before and after this fix) is 100% client-side: it filters `population`,
which is itself derived from the one `GET /v1/attendance/days?date_from=...&date_to=...` response
already fetched for the page, itself scoped server-side via `get_tenant_context` +
`require_permission` (unchanged — no backend file was touched). Confirmed live via
`read_network_requests` during a range-scoped drill: clicking "View all" only changes the page's
own URL query string (`&flag=missing_punch&scope=range`) and triggers Next.js's own internal RSC
navigation requests — no new `/v1/attendance/days` (or any other backend) call fires, and no
`scope`/`bucket`/`flag` parameter is ever sent to the API. There is no new mechanism by which a
URL parameter could reach the backend or widen the already tenant-scoped dataset. **No cross-tenant
exposure is possible through this change. PASS**, consistent with Phase 5's own tenant-scoping
finding, which remains valid since no backend code changed.

## 10. Tests

- **Focused** (`dashboard.test.ts`, `page.test.tsx`, employee profile, `[id]`, `components/attendance`): **119 passed** (8 test files) — 116 pre-existing + 3 new (1 in `dashboard.test.ts`, 2 in `page.test.tsx`).
- **Full frontend suite** (`npx vitest run`): **502 passed** (61 test files) — 499 pre-existing (Phase 5's own baseline) + 3 new. No test was weakened, skipped, or deleted.
- **TypeScript** (`npx tsc --noEmit -p tsconfig.json`): clean, zero errors.
- **Production build** (`npm run build`): succeeded, all routes compiled including `/app/attendance`, `/app/attendance/[id]`, `/app/attendance/employee/[employeeId]`, no errors or warnings.
- **Backend**: not applicable — no backend file was changed, so no backend tests were run.

(The dev server's `.next` cache went stale from running `npm run build` into the same directory
the dev server was using — the identical, already-documented hygiene issue Phase 5's own report
hit in its §2. Fixed the same way: stopped the dev server, `rm -rf .next`, restarted. Not a code
or data change.)

## 11. Remaining Findings

None newly introduced. All previously-deferred findings are explicitly untouched and out of scope
for this task, per the brief:
- D-2, D-3 (unscoped Regularization-pending / Payroll-period-blocked counts) — untouched.
- F4-1..F4-6 — untouched.
- F5-2 (breadcrumb vs. Back inconsistency), F5-3 (profile page month default), F5-4..F5-7
  (informational) — untouched, not remediated by this task.

One cosmetic side-effect of the fix was caught and corrected during live validation, not left as
a new finding: the Who's-In panel's row-count footer said "N employees" even when range-scoped
rows could repeat an employee across days (e.g., "27 employees" for 22 actual employees). Fixed
in `whos-in-panel.tsx` to read "N days" in that case (§3, §6).

## 12. Confirmation

- **No commit.** `git log` unchanged throughout this task.
- **No push, no merge, no branch change.** Still on `main`, same commit as before this task.
- **No unrelated changes.** Only the 9 files listed in §3 were touched. All other pre-existing
  uncommitted changes in the working tree (payroll, leave, employee, mobile, onboarding, etc. —
  present before this task started) were left exactly as found; `git status --short` before and
  after this task differs only in the 9 files above (2 newly modified-on-top-of-already-modified
  tracked files, 7 edited-on-top-of-already-untracked files) plus this new report file.
- **No data was modified.** All database access was read-only `SELECT`.
