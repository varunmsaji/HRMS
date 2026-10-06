# F-1 Remediation Report

## 1. Root Cause

`employeesWithoutRecord()` (`apps/web/src/lib/attendance/dashboard.ts`) builds the "no attendance
row yet" bucket that inflates `Total Employees`/`Not Checked In` whenever the selected focus date
equals the app's live `businessToday()` (gated at the call site in
`apps/web/src/app/app/attendance/page.tsx` via `focusIsToday`). Before this fix, the function's
only employment-status check was:

```ts
if (employee.is_active === false) return false;
```

`Employee.is_active` and `Employee.status` are **not** updated when an employee is terminated —
termination is recorded exclusively on the `Employment` row (`status='TERMINATED'`,
`last_working_day` set). `Employee.status` only ever transitions `PRE_JOINING → PROBATION →
ACTIVE` (confirmed from the model's own docstring in
`apps/api/src/hrms/modules/employee/models.py`: *"No other transition (e.g. into `EXITED`,
`SUSPENDED`) is wired yet"*) and `is_active` is only flipped by the separate, manual
`deactivate_employee` action — never by `EmploymentService.terminate_employment`. This is the
already-known D-1 gap. Because of it, a terminated employee with no attendance row on "today"
passed the only check `employeesWithoutRecord()` performed, and was therefore added to the
"hasn't checked in yet" bucket exactly as if they were a genuinely active employee running late.

For any **historical** (non-today) date, this function is never invoked at all, so the bug never
manifested there — the backend's daily attendance job simply stops producing `attendance_day`
rows once an employee's employment spell ends (confirmed in
`apps/api/src/hrms/modules/attendance/service.py` / `tasks.py`, which already gate row generation
on `joining_date <= date <= (last_working_day or ∞)`), so "no row on a historical date" already
correctly meant "not employed that day." The frontend's `employeesWithoutRecord()` never
applied — or needed — the same check, which is exactly why the *same* calendar date (2026-10-04)
gave different `Total Employees` figures depending only on whether the real wall clock had or had
not yet passed it: while it was "today," the buggy inference ran and over-counted; the moment it
became "yesterday," the (already correct) historical path took over and the terminated employees
quietly disappeared from the denominator. Same data, two different code paths, two different
answers — that inconsistency, not either path in isolation, was F-1.

## 2. Existing Semantics

The canonical "is this employee employed on date X" rule already exists, in multiple places, on
the backend:

- `apps/api/src/hrms/modules/employee/models.py` — `Employment.joining_date` /
  `Employment.last_working_day`, one row per continuous spell, `employment_no_overlap` GiST
  exclusion constraint guarantees spells for one employee never overlap.
- `apps/api/src/hrms/modules/employee/repository.py` — `EmploymentRepository.get_employment_as_of`
  already implements `joining_date <= as_of <= (last_working_day or ∞)` for a single
  employee/date.
- `apps/api/src/hrms/modules/attendance/service.py:2019-2032` and `tasks.py:208-214` — the daily
  attendance-row generator already walks each employee's employment spans with exactly
  `joining_date <= target_date and (last_working_day is None or target_date <= last_working_day)`
  to decide which dates get a row at all.

None of this reached the frontend. `GET /employees` (`EmployeeRead`, consumed verbatim as
`EmployeeLite` by the dashboard's employee directory) carried no employment dates at all —
`Employee` deliberately excludes them by design (its own docstring: *"anything scoped to one
continuous spell (joining/exit dates — Employment, E-03)"*), and the only place employment dates
reach the API is the per-employee `GET /employees/{id}/employments` endpoint, which the dashboard
never calls (and calling it 40 times per page load would be the N+1 fetch the codebase
deliberately avoids — `use-dashboard-data.ts`'s own docstring: *"About 7 requests, never one per
employee"*). This was the actual gap: the data existed in the database and in backend logic, but
never reached the one client-side function that needed it.

## 3. Proposed Semantics

1. **Employee population for a selected date** = employees whose current/most-recent `Employment`
   spell covers that date: `joining_date <= date <= (last_working_day or ∞)` — identical to the
   backend's own existing rule, not a new one.
2. **Attendance record existing for that date** = an `attendance_day` row exists (unchanged,
   already correct — the backend's daily job only ever produces rows inside an employee's
   employment coverage).
3. **"No record yet" inference** = for `date === businessToday()` only: an employee who is in
   scope by (1) but has no row from (2) is assumed "not yet calculated/hasn't punched in" rather
   than absent. This must sit *on top of* (1), never substitute for it.

Before this fix, `employeesWithoutRecord()` only ever checked (3)'s own gate (`focusIsToday`,
unchanged) plus `is_active`, collapsing (1) into "whatever `is_active`/`status` happen to say" —
which, per D-1, is not a reliable employment signal. The fix makes (1) explicit and
backend-sourced, the same way the backend's own daily job already does.

Concretely: `GET /employees` now carries each employee's current employment spell's
`joining_date`/`last_working_day`, and `employeesWithoutRecord()` is made an explicit, pure
function of the focus date (passed in, not implicitly assumed to be "today") that additionally
requires the employee's employment to cover that date.

## 4. Implementation

### Backend — `apps/api/src/hrms/modules/employee`

The smallest change that surfaces already-existing `Employment` data through the already-existing
`GET /employees` bulk endpoint, with **no new endpoint and no DB schema change**:

- **`schemas.py`** — added two additive, optional fields to `EmployeeRead`:
  `employment_joining_date: date | None = None` and
  `employment_last_working_day: date | None = None`. `employee_to_read()` gained an optional
  `employment: Employment | None = None` parameter to populate them; every other call site
  (`create_employee`, `update_employee`, `deactivate_employee`, `confirm_employee`,
  `get_employee`) is untouched and keeps passing no `employment`, so those responses are
  byte-for-byte unchanged (`None`/`None`).
- **`repository.py`** — added `EmploymentRepository.list_latest_employments(session, *,
  company_id, employee_ids)`, a single bulk query (`SELECT DISTINCT ON (employee_id) ... ORDER BY
  employee_id, joining_date DESC, id DESC`) returning the latest (current/most-recent) spell per
  employee. One query for the whole page of employees — never N+1.
- **`service.py`** — `EmployeeService` now holds an `EmploymentRepository` instance;
  `list_employees()` (used only by `GET /employees`) does one extra bulk query via
  `list_latest_employments` and threads each employee's spell into `employee_to_read(employee,
  employments.get(employee.id))`. Both the paginated and unpaginated branches were updated
  identically.

Why "latest spell by `joining_date`" is sufficient for "is employed on date X": the
`employment_no_overlap` constraint guarantees spells for one employee never overlap, so an older
spell can never cover any date at or after the newest spell's own `joining_date` — the latest
spell is always the only one that could possibly cover "today" or any later date. (A full
as-of-date lookup per employee would require either N+1 calls or a new endpoint; this avoids
both, matching the task's explicit preference.)

### Frontend — `apps/web/src/lib`

- **`attendance/dashboard.ts`**:
  - `EmployeeLite` gained `employment_joining_date?: string | null` and
    `employment_last_working_day?: string | null`.
  - New exported pure function `isEmployedOn(employee, date)`: mirrors the backend's coverage
    rule exactly (`joining_date <= date AND (last_working_day == null OR date <= last_working_day)`;
    `false` if no employment data at all).
  - `employeesWithoutRecord(rowsOnFocus, employees, filters, date)` — added the `date` parameter
    (previously implicit/absent) and one new line, `if (!isEmployedOn(employee, date)) return
    false;`, alongside the existing `is_active`/filter checks. Making `date` an explicit parameter
    (rather than reading `businessToday()` internally) is what makes the function a pure,
    testable function of its inputs — the actual fix for "the same selected date must give the
    same answer regardless of wall-clock time."

- **`apps/web/src/app/app/attendance/page.tsx`**: updated the one call site to pass `range.to`
  (the focus date) as the new fourth argument. The existing `focusIsToday` gate controlling
  *when* this function runs at all is unchanged — historical dates still never invoke it, exactly
  as Phase 3 confirmed was already correct.

No other aggregation (overtime, regularization, payroll-period, trend, heatmap) was touched.

## 5. Files Changed

- `apps/api/src/hrms/modules/employee/schemas.py` — added `employment_joining_date`/
  `employment_last_working_day` to `EmployeeRead`; `employee_to_read()` takes an optional
  `employment` param.
- `apps/api/src/hrms/modules/employee/repository.py` — added
  `EmploymentRepository.list_latest_employments()` (bulk, one query per `GET /employees` call).
- `apps/api/src/hrms/modules/employee/service.py` — `EmployeeService.__init__` now builds an
  `EmploymentRepository`; `list_employees()` enriches both its paginated and unpaginated results
  with each employee's latest employment spell.
- `apps/api/tests/integration/modules/employee/test_employment.py` — added 4 new integration
  tests covering the new `GET /employees` fields (pre-hire, active, terminated, rehired/latest
  spell).
- `apps/web/src/lib/attendance/dashboard.ts` — added `isEmployedOn()`; extended `EmployeeLite`;
  `employeesWithoutRecord()` now takes an explicit `date` and checks employment coverage.
- `apps/web/src/lib/attendance/dashboard.test.ts` — updated the existing `employeesWithoutRecord`
  tests for the new signature/fixture shape; added a new `isEmployedOn` describe block and 4 new
  `employeesWithoutRecord` F-1 regression cases (terminated exclusion, active inclusion across two
  independent calls for the same date, join-date boundary, last-working-day boundary).
- `apps/web/src/app/app/attendance/page.tsx` — one call-site update: `employeesWithoutRecord(...,
  range.to)`.
- `apps/web/src/app/app/attendance/page.test.tsx` — added `employment_joining_date`/
  `employment_last_working_day` to the shared `EMPLOYEES` fixture (fixing a test that broke under
  the new, stricter employment check); added a new "F-1" describe block with 4 page-level
  integration tests (terminated exclusion despite active-looking `status`/`is_active`, not-yet-joined
  exclusion, cross-render determinism, historical date not using the today-only inference);
  loosened the `employees` prop's test type from `typeof EMPLOYEES` to `EmployeeLite[]` so mixed
  fixtures type-check.

No DB schema change. No new endpoint. No change to Payroll, Leave, overtime, regularization,
trend, heatmap, or D-2/D-3 code paths.

## 6. Tests Added/Changed

**Backend** (`apps/api/tests/integration/modules/employee/test_employment.py`):
- `test_list_employees_carries_no_employment_dates_before_hire` — `PRE_JOINING` employee → both
  fields `None`.
- `test_list_employees_carries_current_employment_dates` — hired employee → correct
  `joining_date`, `last_working_day: None` (open-ended).
- `test_list_employees_carries_last_working_day_after_termination` — terminated employee →
  correct `last_working_day`, while asserting `status`/`is_active` remain unchanged (documents
  D-1 directly against this new data).
- `test_list_employees_carries_latest_spell_after_rehire` — rehire (new `Employment` row) →
  `GET /employees` reports the *new* spell's dates, not the old, already-ended one.

**Frontend unit** (`apps/web/src/lib/attendance/dashboard.test.ts`):
- `isEmployedOn` describe block — joined-before/on/after, LWD boundary (inclusive) vs. day-after
  (excluded), open-ended ongoing, no-employment-data, and a rehire/multiple-spells case.
- `employeesWithoutRecord` — updated existing test for the new `date` param; added: terminated
  employee excluded on "today" despite `is_active`/`status` looking active (F-1's exact
  reproduction, Meera-Rao-shaped); genuinely active employee included, identically, across two
  independent calls with the same date (determinism); join-date boundary (excluded the day
  before, included on the day); last-working-day boundary (included on the LWD itself, excluded
  the day after).

**Frontend integration** (`apps/web/src/app/app/attendance/page.test.tsx`), new "F-1" describe
block:
- Terminated employee (status `PROBATION`, `is_active: true` — deliberately not kept in sync)
  excluded from `Total Employees`/`Not Checked In`/the attendance list on today's view.
- Not-yet-joined employee (`joining_date` 3 days in the future) excluded.
- Determinism: same employee data + same date, rendered via two independent, freshly-mocked
  mounts, produces the same `Total Employees` both times.
- Historical date (yesterday, via a custom range) does **not** apply the "no record yet"
  inference — a terminated/no-row employee contributes `0`, not inflating the count the way
  "today" deliberately does.

## 7. Targeted Test Results

All run against the dedicated `hrms_test` database (never `hrms_dev`), or via `vitest`/`tsc` for
the frontend — the live `hrms_dev` dataset was never touched by any test run.

- Backend, employee module, full targeted run:
  `apps/api/tests/integration/modules/employee/` → **369 passed**.
  (Includes the 4 new `GET /employees` tests, all passing, plus the full pre-existing
  `test_employee.py`, `test_employment.py` (44 tests, including the new ones),
  `test_employee_pagination.py`, `test_employee_data_scope.py`,
  `test_master_data_compensation_termination.py`, `test_employee_confirmation.py`,
  `test_employee_lifecycle_and_concurrency.py`.)
- Backend, attendance termination-boundary regression:
  `test_punch_after_last_working_day.py` → **passed** (part of the 369; also re-run standalone).
- Frontend unit/integration: `npx vitest run` → **499 passed (61 files)**, including the new F-1
  cases in `dashboard.test.ts` and `page.test.tsx`.
- Frontend typecheck: `npx tsc --noEmit -p tsconfig.json` → **clean, zero errors**.
- Frontend production build: `npm run build` → **succeeded**, all routes compiled, no errors.
- Backend syntax/import sanity (`ast.parse` on all three changed modules) → clean.

## 8. Phase 3 Revalidation Results

Live UI (logged in as `hr.admin3@validation.example`), cross-checked against independent SQL
against `hrms_dev` (read-only; `SELECT` only, per the data-safety rule). Real wall-clock/business
"today" at verification time: **2026-10-05**.

| Date viewed | Total Employees (UI) | Not Checked In (UI) | Independent SQL (`employment` coverage) | Match |
|---|---|---|---|---|
| **2026-10-05 ("Today")** | 37 | 37 | `SELECT count(*) FROM employee e JOIN employment em ON em.employee_id=e.id WHERE e.company_id=... AND em.joining_date<='2026-10-05' AND (em.last_working_day IS NULL OR em.last_working_day>='2026-10-05')` → 37 (40 − EMP-0013, EMP-0025 [LWD 09-20], EMP-0036 [LWD 09-30]); `attendance_day` rows for 2026-10-05 = 0, so all 37 are "no record yet" | ✓ |
| 2026-10-04 (now historical, Custom range) | 37 | 0 | Matches Phase 3's own Test A (37/1 Present/1 Late/0 Not-checked-in) exactly — unaffected by this fix, since historical dates never call `employeesWithoutRecord()` | ✓ (no regression) |
| 2026-09-20 (EMP-0013/0025's LWD itself) | 40 | — (Weekly off 39, Half day 1) | Matches Phase 3 Test H′ exactly — terminated employees still counted *through* their LWD | ✓ (no regression) |
| 2026-09-21 | 38 | 1 | Matches Phase 3 Test H exactly (40 − 2, EMP-0036 not yet terminated at this date) | ✓ (no regression) |
| 2026-09-30 | 38 | — | Matches Phase 3 Test B/D exactly | ✓ (no regression) |
| 2026-10-01 | 37 | — | Matches Phase 3 Test E exactly | ✓ (no regression) |

Direct employee-level check: filtering the dashboard to `Meera Rao (EMP-0013)` alone on today's
view now shows `Total Employees: 0`, "No attendance days match these filters" — she no longer
appears anywhere in "Today's attendance." Confirmed via the live `GET /v1/employees` response
(`employment_joining_date: 2026-01-01`, `employment_last_working_day: 2026-09-20`,
`status: PROBATION`, `is_active: true` — i.e. the fix reads the correct field and ignores the
stale `status`/`is_active`, as designed) that all three terminated employees (EMP-0013, EMP-0025,
EMP-0036) carry correct, non-null `employment_last_working_day` values matching the `employment`
table exactly.

"Needs Attention" (Payroll period blocked — 1 period; Regularization pending — 7 requests) is
unchanged on every date above, confirming D-2/D-3 were not touched.

## 9. Before/After Comparison

| Scenario | Before (F-1) | After (fixed) |
|---|---|---|
| Viewing "today" = 2026-10-04 (Phase 2, while wall clock was still 2026-10-04) | Total 40, Not checked in 3 — included 3 terminated employees | N/A — cannot be re-run (wall clock has moved on); analytically, the fixed function would now return noRecord=0 for this exact input (all 3 terminated employees' `last_working_day` < 2026-10-04 is false for EMP-0036 but irrelevant since they already had rows that day — see below), giving Total 37, matching "after" row below |
| Viewing "today" = 2026-10-05 (same dataset, one day later, before the fix) | Total 40, Not checked in 40, "40 with no record yet for today" — Meera Rao (EMP-0013, left 2+ weeks earlier) shown as "Expected to work, no IN punch" | **Total 37, Not checked in 37** — the 3 terminated employees are cleanly excluded; Meera Rao does not appear anywhere in "Today's attendance" |
| Viewing the historical date 2026-10-04 one day later (2026-10-05) | Total 37, Not checked in 0 (already correct — historical path) | Total 37, Not checked in 0 — **unchanged**, now consistent with the "today" figure instead of contradicting it |
| Same date, same data, evaluated on two different days | **40 vs. 37 — disagreed** (the core F-1 defect) | **37 vs. 37 — agree** |

The fix closes exactly the gap Phase 3 identified: the same calendar date no longer produces two
different headcounts depending on when it is viewed.

## 10. D-1 Status

**Partially resolved — the dashboard-facing symptom is fixed; the underlying data-sync gap
remains and is now explicitly documented, not silently relied upon.**

- D-1's original framing ("`employee.status`/`is_active` are not updated on termination") is
  **still true** and **out of scope for this task** (the task explicitly says not to add a new DB
  field or touch the employee lifecycle state machine). This fix does not make `Employee.status`
  transition to anything on termination, and does not set `is_active=false` on termination — it
  deliberately does not touch that at all.
- What *is* resolved: the Attendance dashboard (`Total Employees`, `Not Checked In`, "Today's
  attendance" list) no longer relies on `status`/`is_active` to detect termination. It now reads
  `Employment.last_working_day` directly (via the new `GET /employees` fields), which **is**
  correctly maintained by `EmploymentService.terminate_employment`. This is the dashboard's
  specific instance of D-1, and it is fixed.
- Residual risk: any **other** consumer of `Employee.status`/`is_active` that assumes it reflects
  current employment (outside Attendance) is still exposed to the original D-1 gap. The Phase 3
  report flagged "Status distribution / filters / employee lists / reports" as inheriting the same
  behavior because they "key off the same `attendance_day` rows (or their absence)" — those
  non-KPI consumers (e.g. the plain employee list page at `/app/employees`, which uses
  `Employee.status` directly as a column, not `employment_last_working_day`) were **not** touched
  by this fix and were out of scope (no such change was requested, and the task capped scope to
  the dashboard's KPI population). A future, separate piece of work should decide whether to (a)
  wire `Employee.status → EXITED` on termination (the structural fix D-1 originally recommended)
  or (b) have every other `status`/`is_active`-dependent view adopt the same
  `employment_joining_date`/`employment_last_working_day` fields this fix added to `EmployeeRead`.

## 11. Remaining Findings

- **D-2** (`Regularization pending` is all-time/company-wide, not date-scoped) — **unchanged,
  confirmed still present**. Not touched, per the hard constraint. Live-reverified: "Regularization
  pending — 7 requests" appeared identically across every date tested in §8.
- **D-3** (Payroll-period-blocked indicator is never date-scoped) — **unchanged, confirmed still
  present**. Not touched. Live-reverified: "Payroll period blocked — 1 period" appeared
  identically across every date tested in §8.
- **F-2/F-3** (Phase 3's renaming of D-2/D-3 with stronger evidence) — same status as D-2/D-3
  above; not touched.
- **F-4** (possible transient empty-KPI flash during very rapid range-input changes, LOW/
  UNVERIFIED) — not investigated or affected by this change; this fix touches none of the
  range/window-fetch timing code.
- **F-5** (trend chart axis cosmetic tick-label issue) — not touched; unrelated code path
  (charting library tick generation), not affected by this fix.
- **F-6** (informational — "Today" quick-select reflects the real clock, not the dataset's
  intended "today") — unaffected; this is correct, intended behavior and remains true after the
  fix (the fix changes *what* "today" counts, not *what date* "today" resolves to).
- **New observation (not a defect)**: `GET /employees` now does one additional bulk SQL query per
  call (`list_latest_employments`), for every caller of that endpoint, not just the Attendance
  dashboard — e.g. the plain Employee list page (`/app/employees`) will also now receive (and
  currently ignore) `employment_joining_date`/`employment_last_working_day` in its API response.
  This is harmless (additive fields, one extra indexed query, negligible cost at this dataset
  size) but worth noting for anyone reviewing `GET /employees`'s query plan at scale.

## 12. Regression Results

- Backend: **369/369** passed (`apps/api/tests/integration/modules/employee/`, run against
  `hrms_test`). No pre-existing test needed modification on the backend side — the new fields are
  purely additive.
- Frontend: **499/499** passed (`npx vitest run`, full suite, 61 files). One pre-existing test
  (`apps/web/src/app/app/attendance/page.test.tsx`'s "counts active employees with no attendance
  row yet as not checked in") initially failed after the fix because its shared `EMPLOYEES`
  fixture had no employment dates at all — under the new, stricter check this correctly excludes
  everyone, which is the intended tightening of behavior, not a bug. Fixed by adding
  `employment_joining_date`/`employment_last_working_day` to that fixture (all three test
  employees are genuinely still employed, so this is a faithful fixture update, not a weakened
  assertion).
- Frontend typecheck: clean. Frontend production build: succeeded.
- `hrms_dev` (the live validation dataset: 40 employees, 1,286 `attendance_day` rows, 1,971
  punches) was never written to by any test — all backend test runs used `hrms_test`; all
  `hrms_dev` interaction was read-only `SELECT`s and live, read-only UI navigation.

## 13. Final Verdict

**FIXED**
