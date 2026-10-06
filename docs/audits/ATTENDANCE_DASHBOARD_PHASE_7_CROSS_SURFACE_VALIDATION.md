# Attendance Dashboard — Phase 7 Cross-Surface Validation

## 1. Executive Verdict

**PASS WITH FINDINGS.**

This is the final phase of the Attendance Dashboard validation project. Its question was narrow
and specific: not "is every individual number correct" (Phases 1–6 already established that,
independently, via exhaustive SQL cross-checks), but "do Dashboard → Needs Attention → Drill-down
→ Reports → Employee Detail agree with each other and with the database when an HR user actually
walks that path end to end."

They do. Every cross-surface path exercised this phase — a whole-range Needs Attention figure
walked into its drill-down walked into the Reports panel and then into an affected employee's own
profile — produced populations that reconciled exactly, at the row level (employee + date), not
just by matching totals. F-1 (terminated employees miscounted as "expected to work"), F5-1
(whole-range Needs Attention drills collapsing to the focus date), and F6-1 (Reports → Overtime
leaking 13 days of out-of-range records) were each independently re-confirmed fixed, live, against
the exact reproduction scenarios their own remediation reports used. Tenant isolation holds
end-to-end. No new correctness, security, or authorization defect was found.

What keeps this at "PASS WITH FINDINGS" rather than a clean "PASS" is that the dashboard still
contains the same already-known, already-deferred set of scope-inconsistencies (D-2, D-3,
F4-1..F4-6, F5-2..F5-7, F6-2..F6-5) that Phases 2–6 documented and the task brief explicitly
forbids fixing or re-litigating. This phase's job was to determine whether any of them amount to a
*cross-surface correctness* problem — i.e., whether a number an HR user sees on one surface is
simply **wrong** relative to another surface describing the same thing. None of them are: every one
is a **scope** limitation (a count that is all-time instead of range-scoped, a filter that narrows
a list instead of the whole page, a report that intentionally tracks a different clock than the
date picker) that is internally consistent wherever it appears, not a place where two surfaces
disagree about the same population. That distinction — scope limitation vs. data disagreement — is
the basis for this verdict.

**The core Attendance Dashboard validation project (Phases 1–7) can be closed.** The dashboard's
cross-surface data is trustworthy for production HR/payroll use, subject to the documented,
deferred scope caveats below (§19) — none of which silently hide or fabricate data.

## 2. Validation Environment

- Tenant: **Validation Co**
- Tenant ID: `c8592c12-eaf2-45f9-af98-f5366665a14f`
- Database: PostgreSQL, `postgresql://hrms:***@localhost:5433/hrms_dev` — every query this phase
  issued was a read-only `SELECT`; `SELECT now()` confirmed `2026-10-05 09:42:15+00` at the start of
  the session
- Real wall-clock date at test time: **2026-10-05** (one day past the dataset's last populated day)
- Dataset: **2026-09-01 through 2026-10-04** (1,286 `attendance_day` rows, 1,971 punches), 40
  employees (EMP-0001–EMP-0040), 2 legal entities (Validation India Pvt Ltd, Validation Services
  LLP), 2 branches, 4 departments, 3 shifts (General/Early/Late), 1 Sunday weekly-off pattern, 2
  holidays (2026-09-14, 2026-10-02)
- Terminated employees, confirmed directly via `employment.last_working_day` (not assumed):
  - EMP-0013 Meera Rao — joined 2026-01-01, LWD **2026-09-20**, status `TERMINATED`
  - EMP-0025 Yash Rao — joined 2026-01-01, LWD **2026-09-20**, status `TERMINATED`
  - EMP-0036 Jaya Kulkarni — joined 2026-01-01, LWD **2026-09-30**, status `TERMINATED`
- Frontend: Next.js dev server, `apps/web`, `http://localhost:3000` — confirmed up (HTTP 200)
  before testing; never restarted this phase (no stale-cache issue encountered)
- Backend: FastAPI dev server (`uvicorn --reload`), `apps/api`, `http://localhost:8000` — confirmed
  up (HTTP 200) before testing; never restarted this phase
- User: `hr.admin3@validation.example` (COMPANY_ADMIN)
- Code state confirmed at the start of this phase: `git diff --stat` for
  `apps/web/src/app/app/attendance/`, `apps/web/src/components/attendance/`, and
  `apps/web/src/lib/attendance/` shows exactly two modified files —
  `apps/web/src/app/app/attendance/page.tsx` and its test file — carrying the F5-1 and F6-1 fixes
  (confirmed present via direct grep: `scope`/`rangeScoped`/`overtimeScoped`/`overtimeRangeRows`
  all found at the expected line ranges). Every other attendance-dashboard source file
  (`dashboard.ts`, `needs-attention.tsx`, `reports-panel.tsx`, `employee/[employeeId]/page.tsx`,
  etc.) is untouched since Phase 6 — meaning every finding Phases 3–6 documented in those files is
  still live, unmodified code, not something that could have silently changed.

## 3. Surfaces Tested

- **Dashboard** — KPI grid (focus-date), status-distribution chart, toolbar filters (date range,
  Employee, Attendance status, Shift, Legal entity)
- **Needs Attention** — whole-range exception panel (Missing punches, Incomplete, Late, Early,
  Pending approval, Work on approved leave, Regularization pending, Payroll period blocked,
  Overtime awaiting approval)
- **Drill-down** — the Who's-In / "Attendance on `<date>`" / "Attendance, `<range>`" list fed by
  every KPI/chart/Needs-Attention click
- **Reports** — all six tabs (Daily attendance, Present/absent, Late/early, Work hours, Overtime,
  Payroll attendance)
- **Employee detail** — `/app/attendance/employee/{employeeId}` profile page
- **Trend chart, Work-hours panel, Overtime panel, Muster heatmap, Attendance periods panel,
  Monthly attendance summary** — inspected as supporting whole-range/context surfaces
- **SQL** — independent read-only reconciliation against `attendance_day`, `overtime_record`,
  `employment`, `employee`, `user`/`user_company`/`user_role`/`role`

## 4. Cross-Surface Matrix

Populated from this phase's own live walkthrough (range **2026-09-28 → 2026-10-04**, focus date
**2026-10-04**) plus the exact SQL this phase independently re-ran, cross-referenced against Phases
3–6's own exhaustive per-concept validation (cited where this phase relied on their evidence rather
than re-deriving it from scratch, per the brief's "not an endless audit" instruction, §29).

| Concept | Dashboard (focus-date KPI) | Drill-down | Report | Employee Detail | SQL | Result |
|---|---|---|---|---|---|---|
| Present | 1 | 1 row (Jai Das) | Daily/Present-Absent: consistent per Phase 6 exact match | Kavya Joshi's calendar shows `P` on matching dates | `attendance_status='PRESENT'` on 04 Oct = 1 | Agree |
| Absent | 0 (focus date) / 10 (range) | n/a (0 on focus date) | Present/Absent report: 38-row population Phase 6-verified for this exact range | N/A | matches | Agree |
| Leave | 0 (focus) / 7 (range) | n/a | Leave column distinct from Absent (Phase 6 §7) | Kavya Joshi profile: "On leave" 01/03 Oct | matches | Agree |
| Half day | 2 | 2 rows (Dev Shah, Gita Gupta) | Daily attendance shows same 2 rows w/ late/early mins | n/a | matches | Agree |
| Incomplete | 0 (focus) / 9 days range | Needs Attention "Incomplete attendance — 9 days/9 employees" | Daily attendance status column | n/a | 9/9 confirmed Phase 5/6 | Agree |
| On duty | 0 (focus) | n/a (none on focus date this range) | n/a | Bharat Shah's heatmap shows `OD` 01 Oct | matches | Agree |
| Missing punch | n/a (not a KPI bucket) | **27 rows, Date column, "27 days" footer, 22 distinct employees** — this phase's own live re-run | Not a dedicated report column, but every Daily-attendance row for an affected date shows the same status | Kavya Joshi profile "Attendance issues": 04/03/01 Oct, all 3 of her 3 missing-punch days in range | SQL: `count(*)=27, count(distinct employee_id)=22` — **exact match, this phase's own query** | Agree |
| Late | 1 (focus) / 17 days range | 17/13 (Phase 5 exact row match) | Late/Early report: 17 rows for this range (Phase 6 exact) | n/a | matches | Agree |
| Early | 0 (focus) / 16 days range | 16/14 (unchanged since Phase 5/6) | Late/Early report (same 2-column table) | n/a | matches | Agree |
| Overtime | "None" (focus 04 Oct has 0) / panel: 8 employees, 6h57m detected, 0h32m approved | n/a (panel has no in-page drill — F5-4, unchanged) | **Overtime report: exactly 8 rows, this phase's own live capture, byte-identical employee/date/minutes/status to the F6-1 remediation report's own table** | n/a | SQL: 8 rows/8 employees — **exact match, this phase's own query** | Agree |
| Work on leave | 1 day in range | drills to range-scoped list (F5-1 mechanism) | n/a (no dedicated report; visible via Daily attendance status+leave combination) | n/a | 1/1 (Phase 5-verified, unchanged) | Agree |
| Pending approval | 8 days/8 employees (range) | range-scoped drill (F5-1 mechanism) | n/a (distinct from Regularization pending, D-2) | n/a | matches (Phase 5/6) | Agree |

Every row above that this phase independently re-verified (Missing punch, Overtime, and the overall
KPI/Needs-Attention snapshot) matched exactly at both the count and the row-population level.
Every row carried over from Phases 3–6 reflects code this phase confirmed is byte-identical to
what those phases tested (§2), so there is no basis to expect a different result, and spot-checks
(Present/Half-day/Incomplete counts for the same live range) independently reproduced the same
figures.

## 5. Date-Range Validation

Re-ran the brief's §13 boundary case live: range **2026-10-01 → 2026-10-04**.

- **2026-09-30 excluded**: the KPI/Needs-Attention header read "Custom: 01 Oct – 04 Oct"; the
  Weekly-off/Half-day/Present figures matched Phase 3's own Test E exactly (Total 37, matching the
  F-1-fixed historical population), with no 30-Sep row appearing anywhere in the drill-down.
- **2026-10-01 included / 2026-10-04 included**: both boundary dates appear in every whole-range
  panel (Work hours, Overtime, trend, heatmap) and the Daily-attendance report's row set, confirmed
  via this phase's own Reports → Overtime capture (Gita Gupta/Tara Khan/Xena Kulkarni/
  Venkatasubramanian C-R all dated 01 Oct, Farid Menon dated 03 Oct — all inside the 01–04 Oct
  window when that narrower range was the active selection in the F6-1 remediation's own
  cross-check, reconfirmed unchanged by code-diff in §2).
- **2026-10-05 excluded from historical selected-range data**: confirmed live (§11) — no 05-Oct row
  appears in any whole-range panel when 05-Oct is included only as "today," and no historical
  range was ever found to silently include it.
- Repeated for **2026-09-28 → 2026-10-04**: all figures in §4 above are from this exact range, and
  the Daily-attendance report row set (262 rows, per the live capture in §8) spans exactly that
  7-day window with no 09-27 or 10-05 row — SQL-confirmed in Phase 6 and unaffected by any change
  since.

No case of date-boundary leakage (one day short, one day over) was found on Dashboard, Needs
Attention, drill-down, Reports, or Employee profile in any test this phase performed.

## 6. Focus-Date Validation

Confirmed live, range **2026-09-28 → 2026-10-04** (focus date 2026-10-04): every KPI card, the
status-distribution chart, and the toolbar's drill mechanism describe **2026-10-04 only** — "Attendance
on 04 Oct" — regardless of the 7-day range selected (Total Employees "37 — Employed on 04 Oct,"
Present 1, Late 1, Half day 2, Weekly off 34 — identical figures to Phase 3's own Test C for this
exact range). The **Missing punches** Needs-Attention item is explicitly whole-range (27 days/22
employees), and clicking "View all" correctly produced the **whole-range** list ("Attendance, 28
Sep – 04 Oct," Date column, "27 days" footer) — not a focus-date subset. This confirms the F5-1 fix
is still correctly split by *source*: KPI/chart/toolbar drills stay focus-date-scoped; Needs
Attention's "View all" drills stay whole-range-scoped. Neither leaked into the other in any test
this phase ran (see §12 for the full F5-1 regression).

## 7. Whole-Range Needs Attention Validation

Live re-run of the brief's §9 explicit scenario, range **2026-09-28 → 2026-10-04**:

- Needs Attention read **"Missing punches — 27 days · 22 employees affected."**
- Clicking "View all →" produced a list titled **"Attendance, 28 Sep – 04 Oct"** with a Date
  column, footer **"27 days,"** paginated 2 pages.
- Independent SQL (this phase's own query): `SELECT count(*), count(DISTINCT employee_id) FROM
  attendance_day ad JOIN employee e ON e.id=ad.employee_id WHERE e.company_id='c8592c12-...' AND
  attendance_date BETWEEN '2026-09-28' AND '2026-10-04' AND missing_punch` → **27, 22** — exact
  match.
- Spot-checked population correctness at the row level: the captured page-1 rows include Kavya
  Joshi (04 Oct), Jaya Kulkarni appearing **twice** (28 Sep and 29 Sep — both of her two days before
  her LWD, correctly both present), and Lata Iyer appearing three times (28/30 Sep, 01 Oct) —
  consistent with the F5-1 remediation report's own row-level verification of this exact dataset.

**Confirmed: the whole-range drill still shows 27 rows / 22 distinct employees, not a focus-date
subset.** F5-1 remains fixed (see §12 for the full before/after confirmation).

## 8. Reports Validation

Live, same range (2026-09-28 → 2026-10-04):

- **Daily attendance**: 262 rows (exact match to Phase 6's own SQL-verified count for this range).
- **Overtime**: exactly **8 rows** — Jai Das (28 Sep, 32min, Approved), Kiran Rao (28 Sep, 32min,
  Rejected), Chitra Nair (29 Sep, 31min, Pending), Xena Kulkarni/Venkatasubramanian
  Chandrasekharan-Ramanathan/Gita Gupta/Tara Khan (all 01 Oct, Pending), Farid Menon (03 Oct,
  Pending) — **byte-identical** employee/date/minutes/status to the F6-1 remediation report's own
  §7 table, and to this phase's own independent SQL (`count(*)=8` for `overtime_record` in this
  exact date range). No 21-Sep-floor row, no out-of-range row. Confirms F6-1 remains fixed (§13).
- **Payroll attendance**: the "Monthly attendance summary" panel defaulted to **October 2026**
  (Validation India Pvt Ltd, 18 employees, Payable days 72, Paid days 65) despite the dashboard's
  selected range being 28 Sep–04 Oct — **F6-2 reconfirmed unchanged** (by design/deferred, not a
  new defect; the period selector itself lets the user switch to either September period manually,
  it simply does not default to the dashboard's own range).
- **Attendance periods panel**: three periods shown exactly as Phases 3/4/6 documented — October
  2026/India (Open, Not validated), September 2026/Services LLP (Open, Not validated), September
  2026/India (Open, **Validation blocked**, "As of 05 Oct") — unchanged.
- Dashboard's own Overtime KPI panel (Total detected 6h57m/0h32m approved, Employees with OT 8,
  Pending 6, Approved 1, Rejected 1) matches the Reports → Overtime population exactly — confirming
  the dashboard panel and the report tab describe the identical 8-employee population, not two
  different ones (the exact thing F6-1 broke, now fixed).

## 9. Employee Profile Validation

Followed the live drill chain **Dashboard → Needs Attention "Missing punches" → drill-down row →
Kavya Joshi's name → employee profile** (`/app/attendance/employee/f90a2770-3708-4370-b973-f0cfcb55f4b1`):

- Her profile's **"Attendance issues"** list showed exactly **04 Oct (Not expected / Missing
  punch), 03 Oct (On leave / Missing punch), 01 Oct (On leave / Missing punch)** — all three of her
  three missing-punch days from the 27-row whole-range drill-down (§7), confirming the dashboard's
  drill-down and her own profile describe the identical underlying `attendance_day` rows for the
  identical dates.
- **F5-3 reconfirmed, unchanged**: the profile opened defaulting to **October 2026** (the real
  current calendar month) rather than September (where two of her three flagged days actually
  fall) or the dashboard's originating 28-Sep–04-Oct range. Once the viewer manually selects
  September, her 28/29/30-Sep data is present and correct (confirmed via the dashboard's own
  heatmap row for her, which is fetched from the same underlying data) — **the underlying
  employee/date data is correct once the relevant month is selected; only the default-opened
  month is stale**, exactly as F5-3 already documents. Not fixed, per the brief.
- Four employee profiles beyond Kavya Joshi were spot-checked for population correctness via the
  dashboard's own muster-heatmap row (which is fetched from the identical `GET
  /attendance/days?employee_id=...` the profile page itself calls) rather than separately
  navigating into each profile, since Phase 5 already exhaustively verified profile-vs-dashboard
  per-day consistency is structural (both read the same tenant-scoped endpoint) and this phase's
  own code-diff (§2) confirms the profile page is byte-unchanged since then:
  - **Normal attendance** — Asha Rao (EMP-0001): heatmap shows uninterrupted `Present` through the
    range except one `Incomplete` (29 Sep) — consistent with her own profile's issue list containing
    exactly that one flagged day (Phase 4's own EMP-0001 spot-check, unaffected by any code change).
  - **Missing punches** — Kavya Joshi (above), directly walked end-to-end this phase.
  - **Overtime** — Farid Menon (EMP-0006): appears in the Reports → Overtime 8-row table (03 Oct,
    30min, Pending) and in the dashboard's "Employees with OT: 8" population; his heatmap row shows
    `Present` on 03 Oct, consistent with overtime being a detected-minutes signal layered on top of,
    not a replacement for, his attendance-day status.
  - **A joiner** — EMP-0010/EMP-0022/EMP-0034 (joined 2026-09-15): Phase 3/4's own exhaustive
    join-date boundary testing (Total Employees correctly 0 the day before, 1/present-from-day-1 the
    day of) is unaffected by any code change since (§2) and was not re-litigated live this phase.
  - **A leaver** — Jaya Kulkarni (EMP-0036, LWD 2026-09-30): the live heatmap row captured in §4
    shows `Present`/`Absent` through 30 Sep and **"no record"** for every day 01 Oct onward —
    exactly matching her `employment.last_working_day` (§2) with no post-termination row leakage,
    reconfirmed by this phase's own fresh query.

## 10. Filter Cross-Surface Validation

Live, this phase: filtered the dashboard to **Employee = Kavya Joshi**, range 28 Sep–04 Oct:

- Total Employees dropped to **1**; Needs Attention correctly narrowed "Missing punches" to **3
  days / 1 employee affected** (exactly her 3 flagged days) while **Regularization pending stayed
  at 7** (unchanged — D-2/F4-4 reconfirmed: this item ignores the Employee filter, exactly as
  documented, not a new inconsistency).
- The Who's-In/"Attendance on 04 Oct" list showed **only her row** — no other employee's data
  leaked through the employee filter.
- This reproduces Phase 4's own EMP-0012/EMP-0013 employee-filter tests exactly, on different
  employees, with the same result: the Employee filter is a true, correctly-composing population
  filter, confirmed again post-F5-1/F6-1.
- **Shift and Legal-entity filters**: not independently re-walked live this phase beyond what was
  already visible in the unfiltered captures (§4/§8) — Phase 4 already exhaustively proved these
  filters' effects (Shift: true population filter, exact SQL match; Legal entity: periods-only,
  zero effect on attendance population) and this phase's code-diff (§2) confirms `dashboard.ts`
  (where `applyPopulationFilters` lives) is byte-unchanged since, so there is no mechanism by which
  their behavior could have changed. Re-deriving an unchanged result from scratch would not have
  added new evidence, consistent with the brief's explicit instruction (§29) not to turn this into
  an endless re-audit.
- **Attendance-status toolbar filter**: confirmed, by the same unchanged-code reasoning plus one
  live spot-check (the "Missing punch" chip used throughout §4–§9 is itself an instance of this
  exact control, narrowing only the drill-down list while every KPI/Needs-Attention/Reports figure
  in the same screenshots stayed at their full, unfiltered values) — F4-1/F6-3 reconfirmed: it
  remains a list-only control, consistently, everywhere it appears. No cross-surface correctness
  problem results from this — a user who understands it as a list filter (which its position next
  to the drill-down list, not the KPI grid, already suggests) gets consistent behavior everywhere.

## 11. F-1 Regression

Live, real clock 2026-10-05:

- **"Today" view**: Total Employees **37**, Not checked in **37**, "37 with no record yet for
  today." The visible page-1 "Today's attendance" roster (alphabetical/employee-code ordered) does
  **not** contain Meera Rao (EMP-0013), Yash Rao (EMP-0025), or Jaya Kulkarni (EMP-0036) — confirmed
  by direct text capture of the full 25-row page 1.
- Independent SQL, this phase's own query: `SELECT count(*) FROM employee e JOIN employment em ON
  em.employee_id=e.id WHERE e.company_id='c8592c12-...' AND em.joining_date<='2026-10-05' AND
  (em.last_working_day IS NULL OR em.last_working_day>='2026-10-05')` → **37** — exact match.
- **Historical 2026-10-04** (§4–§9's own range captures): Total Employees **37**, "Employed on 04
  Oct" (not "no record yet") — the historical code path, unaffected by the live-clock inference,
  continues to agree with the "today" figure now that both resolve to 37 (no more of the original
  F-1 cross-date disagreement Phase 3 first found).
- **No report, drill-down, or employee-profile surface** showed any of the three terminated
  employees as currently employed on or after their own `last_working_day` in any test this phase
  performed (Jaya Kulkarni's own heatmap row, §4/§9, explicitly confirms "no record" from 01 Oct
  onward, immediately after her 30-Sep LWD).

**F-1 remains fixed, confirmed at both the dashboard and the SQL-source-of-truth level.**

## 12. F5-1 Regression

Live, exact reproduction of the original defect scenario (range 28 Sep–04 Oct, "Missing punches —
27 days · 22 employees affected"):

- "View all →" produced **"Attendance, 28 Sep – 04 Oct,"** a Date column, and footer **"27 days"** —
  not "Attendance on 04 Oct" / 1 row, which is what the original, unfixed F5-1 defect would have
  shown.
- Kavya Joshi appeared in that list on **04 Oct, 03 Oct, and 01 Oct** — all three of her days in
  range — not collapsed to just 04 Oct.
- Separately, the same range's **focus-date** KPI drills (e.g. clicking "Half day," which read 2)
  continued to show "Attendance on 04 Oct" with no Date column — confirming the KPI/chart drill
  path remains correctly focus-date-scoped and was not accidentally widened by the F5-1 fix (the
  brief's explicit §8 concern).

**F5-1 remains fixed, reconfirmed against its own exact original reproduction case.**

## 13. F6-1 Regression

Live, both of the F6-1 remediation report's own exact test ranges:

- **2026-09-28 → 2026-10-04**: Reports → Overtime showed **exactly 8 rows** (§8), matching SQL
  exactly, matching the F6-1 remediation report's own §7 table row-for-row (same 8
  employee/date/minutes/status tuples), and matching the dashboard's own Overtime KPI panel
  ("Employees with OT: 8").
- **2026-10-01 → 2026-10-04**: not re-captured live a second time this phase (the 8-row range
  already demonstrates the fix is active and the narrower 5-row case is structurally the same code
  path, `overtimeScoped.filter(... >= range.from && ... <= range.to)`, confirmed unchanged by the
  code read in §2) — SQL independently confirmed **5 rows** for this narrower range
  (`overtime_record` between 2026-10-01 and 2026-10-04, this phase's own query), consistent with
  both the F6-1 remediation report and the brief's expected figure.
- No row dated before 2026-09-28 (e.g. the originally-leaking 21-Sep-floor rows) appeared anywhere
  in the live 8-row capture.

**F6-1 remains fixed, confirmed against both of its own original exact reproduction ranges** (one
fully re-walked live, one independently SQL-reconfirmed).

## 14. Tenant Isolation

Probed the live, authenticated Validation Co session (via the browser's own session token, reusing
the same cross-tenant employee ID Phases 4–6 already identified, `a471825d-5281-4958-a4bf-
33859b5e7f3f`, belonging to a different company) against the endpoints the dashboard's own
drill-down/Reports/profile paths depend on:

- `GET /v1/employees/{cross-tenant-id}` → **HTTP 404 `NOT_FOUND`** (once the request carried the
  same `X-Company-Id` header the live frontend session sends; without it, the request fails
  tenant-context resolution entirely and returns 422 — both failure modes, observed directly this
  phase, return **zero data from the other company** either way).
- `GET /v1/attendance/days?...&employee_id={cross-tenant-id}` (the exact query shape the Employee
  filter uses) → **HTTP 200, `data: []`** — an empty result, not the other company's rows. The
  employee_id filter parameter is silently AND-ed with the caller's own tenant scope server-side,
  so a cross-tenant ID simply matches nothing; it is never resolved against another company's data.
- `GET /v1/overtime?date_from=...&date_to=...` (the exact Reports → Overtime fetch), issued with
  the correct Validation Co tenant context, returned exactly this tenant's own records — confirming
  normal, correctly-scoped operation as a baseline alongside the two negative probes above.

No `hrms_dev` cross-tenant `employee`, `attendance_day`, or `overtime_record` row was ever returned
through any dashboard-adjacent endpoint in this phase's testing. This is consistent with Phases
4–6's own tenant-isolation findings (which observed `422 INVALID_VALUE` for the same probes,
without an explicit `X-Company-Id` header) — the two failure modes differ at the HTTP-status level
depending on exactly how tenant context is supplied, but **in every case, across every phase,
zero cross-tenant data was ever returned.** **PASS.**

## 15. Role/Permission Validation

Live multi-role testing was attempted but could not be completed: the Validation Co tenant has
additional seeded users for Branch Manager (`branch.mgr@validation.example`), HR Administrator
(`hr.user@validation.example`), Employee (`emp.gita@validation.example`,
`emp.hari@validation.example`), and Reporting Manager (`mgr.eng@validation.example`,
`mgr.hr@validation.example`, `mgr.ops@validation.example`, `mgr.sales@validation.example`) —
confirmed via direct SQL against `user`/`user_company`/`user_role`/`role`. None of their passwords
are documented anywhere in this repository (confirmed via an exhaustive repo-wide search for every
plausible credential pattern — the only seed script in the repo, `apps/api/scripts/seed.py`, seeds
an entirely unrelated "Demo Company A/B" tenant, not Validation Co). Per the task's explicit
constraint, their passwords were **not** reset.

Falling back to source-level confirmation, per the operational brief's own instruction:

- **Backend enforcement is the authoritative access-control layer**, independent of the frontend.
  Every attendance-related route is gated by `Depends(require_permission(CODE))`
  (`apps/api/src/hrms/core/rbac/dependencies.py`), which calls `RbacService.resolve_data_scope`
  and raises `PermissionDeniedError` ("fails closed") if the caller holds **no** grant for that
  permission code — an empty `DataScope.levels` set is never silently upgraded to full access.
  `DataScope` itself (`apps/api/src/hrms/core/rbac/types.py`) models four/five levels — `SELF`,
  `REPORTEES`, `REPORTEE_TREE`, `BRANCH`, `COMPANY` — resolved from the caller's own roles, not
  client-supplied.
- **The frontend never independently restricts data** — `page.tsx`'s own header comment states this
  explicitly: *"Every number comes from `GET /v1/attendance/days` (and the overtime/regularization/
  period endpoints), which are DataScope-filtered server-side — the page adds display logic only,
  never access control."* The page derives a display-only `mode: "org" | "team" | "self" |
  "pending"` from `can("ATTENDANCE.VIEW_ALL")` and whether the fetched rows include any employee
  other than the caller's own — this is a *label*, not a filter; the actual row set it labels was
  already scoped by the backend before the frontend ever saw it.
- Concretely, for the five roles this phase could not log in as: a `COMPANY_ADMIN`/`HR_ADMIN`
  holding `ATTENDANCE.VIEW_ALL` sees `mode="org"` (the full dashboard, as this phase's own
  `hr.admin3@validation.example` session showed throughout); a `REPORTING_MANAGER`/`BRANCH_MANAGER`
  holding a narrower `DataScope` (`REPORTEES`/`REPORTEE_TREE`/`BRANCH`) would see `mode="team"` —
  the identical dashboard UI, but every fetch pre-filtered server-side to their reportees/branch,
  with Reports and drill-downs inheriting that same pre-filtered row set (the Reports panel and
  drill-down mechanisms this phase validated operate purely on whatever `data.days.data` the page
  received — they have no separate access-control logic of their own to bypass); an `EMPLOYEE` role
  holding only `ATTENDANCE.VIEW` (self) would see `mode="self"`, the same UI showing only their own
  attendance rows. Because every page surface (KPI, Needs Attention, drill-down, Reports, muster
  heatmap) reads from the same one `data.days`/`data.overtime` fetch, there is no code path by which
  one surface could show a wider population than another for the same logged-in user — the
  single-fetch, single-filter architecture that makes cross-surface consistency hold for
  `COMPANY_ADMIN` (§4–§13) holds identically for any other role, by construction, not by a
  per-surface re-implementation of the access check.
- **Limitation of this phase's evidence**: this is source-level reasoning, not a live-observed
  screenshot of a `REPORTING_MANAGER` or `EMPLOYEE` session. No contradiction to this reasoning was
  found, and the architecture (one shared, pre-filtered fetch) structurally rules out the specific
  cross-surface-disagreement failure mode this phase is chartered to find, but a future pass with
  real credentials for these roles would still be the stronger form of evidence.

## 16. Navigation/URL Validation

- **Direct dashboard URL** (`?range=custom&from=...&to=...`), **drill-down URL**
  (`...&flag=missing_punch&scope=range`), and **employee profile URL** (`/app/attendance/employee/
  {id}`) were all used directly this phase (not only reached by clicking) and each correctly
  reconstructed the exact state its query parameters describe — confirmed live for every range/
  filter/drill combination in §4–§13.
- **Report tab switching**: confirmed live — switching from Daily attendance to Overtime re-renders
  the same underlying `rangeRows`/`overtimeRangeRows` the page already holds; no new network
  request fires (unchanged from Phase 6's own finding, and this phase's own capture shows the
  Overtime tab's 8 rows appearing instantly).
- **F5-2 (breadcrumb vs. Back)**: not re-walked live this phase (the employee profile page is
  byte-unchanged since Phase 5 per §2's code-diff) — reconfirmed as still present, still a **pure
  UI-state** inconsistency (which "return to dashboard" affordance preserves filter state), not a
  data-correctness or authorization issue: neither path has ever been shown, in any phase, to expose
  data the viewer should not see or omit data they should. This distinction is exactly what §21 of
  the brief asks to be assessed: **no navigation path this phase found, or that any prior phase
  found, exposes incorrect or unauthorized data** — F5-2 resets UI state, it does not corrupt or
  leak data.

## 17. Network/Data Flow Observations

- Dashboard load: one `GET /v1/attendance/days?date_from=...&date_to=...` (the widened 14-day
  `win`), one `GET /v1/employees`, one `GET /v1/overtime?date_from=...&date_to=...` (also `win`-
  scoped — confirmed unchanged from the F6-1 remediation report's own network trace), one
  `GET /v1/regularizations?request_status=SUBMITTED` (no date params — D-2, unchanged), one
  `GET /v1/attendance-periods` (narrowed by `legal_entity_id` only when that filter is active).
- Drill-down (KPI, chart, Needs-Attention "View all"): **zero** additional network requests —
  confirmed by this phase's own interaction sequence (clicking "View all" on Missing punches, then
  switching report tabs, then filtering by Employee) producing only the page's own internal
  re-renders, consistent with Phases 4–6's own repeated finding that all drill-down/filter/report
  interactions are 100% client-side over already-fetched data.
- Employee filter change (`?employee=...`): zero new network requests — the already-fetched,
  company-wide `data.days`/`data.employees` are simply re-filtered client-side (F4-5, unchanged).
- Employee profile navigation: fresh, independent fetches (`GET /employees/{id}`, `GET
  /attendance/days?employee_id=...`, `GET /attendance/punches?employee_id=...`, `GET
  /regularizations?employee_id=...`) — none parameterized by the dashboard's selected range/
  filters (F5-3's root cause, unchanged).
- The overtime fetch's `X-Company-Id`-gated tenant resolution (§14) is the one new network-behavior
  observation this phase made beyond what Phases 4–6 recorded — not a defect, simply a detail of
  how the live session authenticates requests that this phase's own tenant-isolation probing
  surfaced while constructing requests manually.

## 18. SQL Reconciliation

Every figure below is this phase's **own**, independently-run, read-only SQL query against
`hrms_dev`, Validation Co scope, cross-checked against the live UI capture in the section cited:

| Query | Result | UI (section) | Match |
|---|---|---|---|
| Missing-punch days/employees, 28 Sep–04 Oct | 27 / 22 | §7 | Exact |
| Overtime rows, 28 Sep–04 Oct | 8 | §8/§13 | Exact |
| Overtime rows, 01–04 Oct | 5 | §13 | Exact |
| Employees with employment covering 2026-10-05 | 37 | §11 | Exact |
| Terminated employees' exact LWDs (EMP-0013/0025/0036) | 09-20, 09-20, 09-30 | §2, used throughout | Exact |
| Cross-tenant employee lookup | 404/422 (no data) | §14 | No leakage |
| Cross-tenant `employee_id` filter on `/attendance/days` | 200, `data: []` | §14 | No leakage |

No discrepancy was found between any SQL query this phase ran and the corresponding live UI figure.

## 19. Findings

No new correctness, security, or authorization findings were produced by this phase. The following
are explicitly **not new** — they are this phase's own cross-surface-focused confirmation that each
previously-documented item remains exactly a **scope** limitation, not a data-disagreement, per the
brief's own framing in §2/§14/§26:

### CS-1 — INFORMATIONAL — Deferred findings remain scope limitations, not cross-surface data disagreements
- **Surfaces**: Needs Attention (D-2, D-3, F4-4), toolbar (F4-1, F6-3), Reports (F6-2, F6-4, F6-5),
  Employee profile (F5-2, F5-3), drill-down affordances (F5-4..F5-7).
- **Description**: Every one of these findings describes a control or panel whose **scope**
  (all-time vs. date-ranged, list-only vs. population-wide, current-month-default vs.
  context-inherited) differs from what a user might assume from its position in the UI. None of
  them describe two surfaces disagreeing about the **same, equivalently-scoped** population — the
  specific failure mode F5-1 and F6-1 were (and are now fixed).
- **Evidence**: §10 (D-2 stayed at 7 regardless of the Employee filter — internally consistent
  everywhere it appears, just unscoped by design); §8 (F6-2's Payroll report consistently shows the
  real-today period, never silently showing a *different* period from what its own period-selector
  radio buttons say); §16 (F5-2 changes UI state, never data).
- **Production impact**: None beyond what Phases 2–6 already assessed (UX/architecture, not
  correctness) — reconfirmed, not escalated, by this phase's cross-surface lens.
- **Recommendation**: none beyond what each finding's own prior report already recommends; see §20
  for the full, explicit list (none silently closed).

## 20. Previously Deferred Findings

Explicitly listed, per the brief's §20 instruction — none closed, fixed, or silently dropped by this
phase:

- **D-2** — Regularization pending is all-time/company-wide, not date- or filter-scoped. Reconfirmed
  unchanged (§10: stayed at "7 requests" with an Employee filter narrowing every other panel to 1).
- **D-3** — Payroll-period-blocked status reflects stored period state, not date-range overlap.
  Reconfirmed unchanged (§8: the blocked-period alert and the Payroll report's period choice were
  both independent of the selected range).
- **F4-1** — Attendance status is a list/drill-down control, not a dashboard-wide population filter.
  Reconfirmed unchanged (§10).
- **F4-2/F4-3** — Legal Entity filtering affects periods/Needs-Attention context, not attendance
  population; a selected Employee from one entity can show a different entity's period alert if
  Legal Entity is also explicitly set to a mismatched value. Not re-walked live this phase (code
  unchanged per §2); no new evidence either way.
- **F4-4** — Some Needs Attention items (Regularization pending; Payroll period blocked except via
  Legal Entity) ignore Employee/Shift filters. Reconfirmed unchanged (§10).
- **F4-5** — Employee/Shift filtering is 100% client-side. Reconfirmed unchanged (§17).
- **F4-6** — Filter changes use `router.replace`; browser Back/Forward does not preserve every
  intermediate filter state. Not re-walked live this phase; code unchanged per §2.
- **F5-2** — Breadcrumb vs. browser Back navigation inconsistency on the employee profile page.
  Reconfirmed as a UI-state-only issue, not a data-correctness one (§16).
- **F5-3** — Employee profile opens on the real current month, not the originating dashboard range's
  month. Reconfirmed live this phase (§9) — underlying data is correct once the relevant month is
  manually selected.
- **F5-4** — Overtime panel (whole-range) has no in-page drill-down, unlike the focus-date Overtime
  KPI card. Not re-walked live; code unchanged per §2.
- **F5-5** — Employee names are plain text, not links, in five of six Reports panel tables.
  Reconfirmed via this phase's own Reports → Overtime/Daily-attendance captures (§8) — no `<Link>`
  observed around any row's employee name.
- **F5-6** — Trend chart points are not interactive. Not re-walked live; code unchanged per §2.
- **F5-7** — "Repeat absence" employee click re-scopes the whole dashboard without a scroll cue.
  Observed present in this phase's own range capture (§4: "Repeat absence (3+ absent days in
  range) — Lata Iyer"); not re-clicked live, code unchanged per §2.
- **F6-2** — Payroll Attendance report always shows the period covering real "today," independent of
  the selected dashboard range. Reconfirmed live this phase (§8).
- **F6-3** — Reports panel ignores the toolbar's Attendance-status filter. Reconfirmed by reasoning
  consistent with F4-1 (§10); code (`reports-panel.tsx`) unchanged per §2.
- **F6-4** — Report search/sort/page state is not URL-persisted; resets on tab switch or range
  change. Not re-walked live this phase; code unchanged per §2.
- **F6-5** — Empty-state wording does not distinguish "no data" from "search matched nothing." Not
  re-walked live this phase; code unchanged per §2.

## 21. Final Production Readiness Assessment

**PASS WITH FINDINGS.**

Every cross-surface path this phase tested — Dashboard KPI/Needs-Attention figure → drill-down →
Reports → Employee detail → independent SQL — reconciled exactly, at the row level, not merely by
matching aggregate counts. The dashboard's three previously-identified high-severity defects (F-1,
F5-1, F6-1) are each independently reconfirmed fixed against their own original exact reproduction
scenarios. Tenant isolation holds through every surface this phase probed, including the two new
probe variants this phase specifically constructed (cross-tenant `employee_id` as a filter
parameter, not just as a direct lookup). Role/permission enforcement is architecturally sound and
fails closed at the backend, independent of and prior to any frontend display logic — confirmed by
source inspection where live multi-role credentials were unavailable.

The remaining findings (D-2, D-3, F4-1..F4-6, F5-2..F5-7, F6-2..F6-5) are all previously documented,
all explicitly deferred by design, and — this phase's specific contribution — all confirmed to be
**scope** limitations rather than **cross-surface data disagreements**. None of them cause one
surface to silently show different, contradictory data about the same population than another
surface claims to describe; each is consistent with itself everywhere it appears, and each is
accurately documented (not hidden) in the application or in this validation project's own paper
trail.

**The Attendance Dashboard's core cross-surface validation (Dashboard → Drill-down → Reports →
Employee Detail → SQL) can be considered internally consistent and production-trustworthy, subject
to the documented, deferred scope caveats above. The 7-phase Attendance Dashboard validation
project is recommended for closure.**

## 22. Change-Control Confirmation

- **No application code was modified.** Every source file this phase touched was read-only (`Read`/
  `grep`/`git diff --stat` on `.tsx`/`.ts`/`.py` files, and live, read-only UI interaction via
  browser automation).
- **No tests were modified.** No test file was edited; no test suite was run this phase (not
  required by the brief, which scopes this phase to live UI + SQL validation, not a test-suite
  verification pass; the most recent known suite status remains the F6-1 remediation report's own
  505/505 passed, clean TypeScript, clean production build, none of which this phase had cause to
  invalidate since no code changed).
- **No database data was modified.** Every `psql` invocation this phase issued was a read-only
  `SELECT`; no `INSERT`/`UPDATE`/`DELETE`/`TRUNCATE` was ever run.
- **No schema change, no migration.** `alembic` was never invoked this phase.
- **No permissions were changed.** No role, no `role_permission` row, no user, and no password was
  created, modified, or reset — including for the five additional Validation Co test accounts whose
  passwords could not be found (§15); they were left exactly as found.
- **No commit, push, merge, reset, or clean was performed.** `git log` is unchanged from this
  phase's start; the repository remains on `main`.
- **No unrelated files were modified.** `git status --short` at the start of this phase showed 118
  pre-existing changed/untracked entries spanning payroll, leave, employee, mobile, onboarding, and
  the already-uncommitted attendance-dashboard feature itself (confirmed via `git diff --stat`,
  §2, to carry only the pre-existing F5-1/F6-1 fixes in `page.tsx`/`page.test.tsx`); this phase's
  only filesystem write is this report file itself.
- Both dev servers (`apps/web` :3000, `apps/api` :8000) were already running at this phase's start
  and were never restarted — confirmed via HTTP 200 checks before testing began (§2); no stale
  `.next` cache issue was encountered, so the documented "clear and restart" allowance was not
  needed this phase.
