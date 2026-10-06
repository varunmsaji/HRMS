# Phase 3 — Date-Range and Temporal Validation Report

## 1. Executive Verdict

**PASS WITH FINDINGS**

Every range-aggregation computation checked against independent SQL (missing punches, incomplete days, late/early counts, absent/leave days, overtime detected/approved/pending/rejected minutes and counts, work-on-leave, holiday/weekly-off/join-date/termination boundaries) matched exactly — the dashboard's own arithmetic over the data it fetches is correct. Focus-date vs. whole-range vs. context-window scoping is implemented exactly as Phase 2 documented and holds up under every range tested, including month and Sunday/holiday boundaries.

However, this phase surfaced one **new, confirmed, high-impact finding (F-1)** that Phase 2 could not have seen: wall-clock time has moved on since Phase 2 was run (system/business "today" is now **2026-10-05**, one day past the validation dataset's last day, **2026-10-04**). This exposed that the dashboard's notion of "Total employees" / "Not checked in" is **not a pure function of the selected date** — it silently depends on whether the selected date happens to equal the real-world current date at the moment you look at it. The exact same calendar day (2026-10-04) now reports **Total Employees = 37, Not checked in = 0** (viewed today, 2026-10-05) versus the **Total = 40, Not checked in = 3** that Phase 2 recorded while 2026-10-04 was still "today". No data changed between the two observations — only the wall clock did. This is a sharper, confirmed version of D-1, not a new independent bug, but it is severe enough to call out as its own finding because it means the same report re-run a day later gives different headcounts for a date that has not changed.

D-2 (regularization pending = 7, all-time/company-wide, unaffected by range) and D-3 (payroll period blocked, unaffected by range or even by whether the range overlaps the blocked period's own month) are both **CONFIRMED** with additional evidence beyond Phase 2.

## 2. Environment

- Tenant: Validation Co
- Tenant ID: `c8592c12-eaf2-45f9-af98-f5366665a14f`
- Frontend: Next.js dev server, `apps/web`, `http://localhost:3000`
- Backend: FastAPI dev server (`uvicorn --reload`), `apps/api`, `http://localhost:8000`
- Database: PostgreSQL, `postgresql://hrms:***@localhost:5433/hrms_dev`
- User used: `hr.admin3@validation.example` (COMPANY_ADMIN, Validation Co)
- **Real wall-clock date/time at test time: 2026-10-05 06:28 IST** (confirmed via `date`, `timedatectl`, and `SELECT now()`). The validation dataset's attendance data ends 2026-10-04. This one-day drift between "today" and the dataset's intended "today" is the proximate cause of finding F-1 below and is itself documented as a timezone/date-boundary finding (§18).

## 3. Date Range Matrix

All KPI/focus-date figures below were independently cross-checked against `attendance_day`, `overtime_record`, and `employment` via direct SQL (§18). "Charts"/"Heatmap" were visually inspected for correct date span and no duplicate/missing days. "Reports" column reflects the Reports panel's row count/date span.

| Test | Range | Focus Date | KPI | Range Metrics | Charts | Heatmap | Reports | Result |
|---|---|---|---|---|---|---|---|---|
| A. Today (as literal date) | 2026-10-04–2026-10-04 (via Custom, not the "Today" quick button) | 2026-10-04 | Total 37, Present 1, Late 1, Not checked in 0 | n/a (1-day range) | window 2026-09-21→10-04 (14d) | 1-day column | 1 row | PASS |
| A′. "Today" quick-select button | — (resolves to real today) | **2026-10-05** (not 2026-10-04) | Total 40, all-zero, "40 with no record yet for today" | — | window 2026-09-22→10-05 | empty day | "No attendance records for this date." | PASS (behaves correctly for its actual input) but **see F-1 / §18**: does not match the task brief's assumption that "Today" = 2026-10-04 |
| B. One day 2026-09-30 | 09-30–09-30 | 2026-09-30 | Total 38, Present 32, Absent 3, Leave 1, Late 3, Not checked in 4 | n/a | window 09-17→09-30 | 1-day column | 1 row | PASS |
| C. Week 2026-09-28→10-04 | 7 days, crosses month boundary | 2026-10-04 | Total 37, Present 1, Weekly off 34, Half day 2 (matches Phase 2's known 34/2/1) | Missing punches 27d/22emp (SQL: 27/22 ✓); OT detected 417min/8emp, pending 6, approved 1, rejected 1 (SQL ✓) | window 09-21→10-04 (range already ≥14d) | 7 columns, Sep/Oct both labeled correctly | 27-row "Missing punches" list consistent | PASS |
| D. Full September 2026-09-01→09-30 | 30 days | 2026-09-30 | identical focus KPIs to Test B (38/32/3/1/3/4) | Missing punches 61d/32emp (SQL ✓); Absent days in range 32 (SQL ✓); Leave days in range 11 (SQL ✓) | window = full range (30d ≥14d); trend chart tick labeled "31 Aug" — see §6 cosmetic note | 30 columns | consistent | PASS (1 cosmetic note) |
| E. October 1–4 | 2026-10-01→10-04 | 2026-10-04 | identical to Test A (37/1/1/0) | — | window 09-21→10-04 | 4 columns | consistent | PASS |
| F. Month boundary 2026-09-28→10-04 | same as Test C | 2026-10-04 | same as Test C | same as Test C | no duplicate/missing days across the Sep→Oct rollover | correct | correct | PASS |
| G. Join-date range 2026-09-14→09-16 | 3 days | 2026-09-16 | Total 40, Present 37, Not checked in 3 | — | — | 3 new joiners (EMP-0010/0022/0034) show "no record" before 09-15, present from 09-15 | correct | PASS |
| G′. Single day 2026-09-14 (pre-join, also a holiday) | — | 2026-09-14 | Total **37** (not 40 — 3 not-yet-joined excluded from denominator entirely, not counted absent/holiday) | — | — | — | — | PASS |
| G″. Single day 2026-09-15 (join day) | — | 2026-09-15 | Total 40, Present 36, Absent 2, Not checked in 2 (new joiners counted from day 1 of employment) | — | — | — | — | PASS |
| H. Termination range 2026-09-19→09-21 | 3 days, crosses EMP-0013/0025 LWD=09-20 | 09-21 | Total **38** (40 − 2 terminated, excluded entirely, no EXITED row ever generated) | — | — | EMP-0013/0025 show "no record" from 09-21 onward in heatmap | — | PASS (see F-1 for the "today" asymmetry) |
| H′. Single day 09-20 (LWD itself) | — | 09-20 | Total **40**, Weekly off 39, Half day 1 — terminated employees still counted (correctly) since they were employed through the end of their LWD | — | — | — | — | PASS |
| I. Second termination range 2026-09-29→10-01 | 3 days, crosses EMP-0036 LWD=09-30 | 10-01 | Total 37; whole-range: Missing punches 15d/14emp, Incomplete 5d/5emp, Late 11d/8emp, Early-out 7d/7emp, Work-on-leave-unresolved 1d, OT pending 5 (all SQL-matched exactly) | all matched | — | EMP-0036 Present on 09-30 (LWD, correctly included), absent from heatmap from 10-01 | — | PASS |
| J. Holiday 2026-10-02 | 1 day | 10-02 | Total 37, Holiday 36, Half day 1 (SQL: 36 NOT_EXPECTED/HOLIDAY + 1 HALF_DAY/HOLIDAY) | — | — | — | — | PASS |
| J′. Holiday 2026-09-14 (combined with join-date test) | 1 day | 09-14 | Total 37, Holiday 35, Present 2 (work-on-holiday) (SQL-matched) | — | — | — | — | PASS |
| K. Weekly off 2026-10-04 | 1 day (via Test C/E) | 10-04 | Weekly off 34, Half day 2, Present 1 — matches Phase 2's known figures exactly | — | — | — | — | PASS |
| L. Leave range 2026-09-20→09-23 | 4 days, contains EMP-0007 leave (09-22) and EMP-0019 leave (09-23) | 09-23 | On leave (focus) = **1** (EMP-0019 only — EMP-0007's leave on 09-22 correctly excluded from the focus-date KPI) | Leave days in range = **2** (both leaves counted) (SQL ✓) | — | — | — | PASS |
| M. Overtime range (Tests C and I) | 28 Sep–04 Oct and 29 Sep–01 Oct | — | OT card (focus date) separate from OT panel (range) per design | OT panel: detected/approved/pending/approved/rejected counts and minutes matched SQL exactly in both ranges | OT trend spans context window | — | — | PASS |
| N. Empty range 2026-10-05 (outside dataset) | 1 day | 10-05 | Total 40, all zero, "No attendance records for this date.", per-row "No record / No record yet" | Needs Attention still shows the two range-independent items (payroll blocked, regularization 7) | window 09-22→10-05 | "No attendance days to show." path not hit (muster still renders no-record cells) | n/a | PASS — clean empty-state, no stale data from previous range — **but see F-1**: terminated employees (e.g. Meera Rao, EMP-0013) appear in this "no record, expected to work" list despite leaving 2 weeks earlier |

## 4. Focus-Date Validation

Confirmed for every test above: KPI cards, Status distribution, Who's-In/"Attendance on `<date>`" list, and the Leave & Absence "Absent on `<date>`"/"On leave on `<date>`" tiles all use `range.to` exclusively, regardless of `range.from` or range width. The same focus date (e.g. 2026-10-04) produced byte-identical KPI numbers whether selected as a 1-day range (Test A), a 4-day range (Test E), a 7-day range (Test C), or a 10-day range — strong, repeated evidence this is a pure function of `range.to`. Source: `rowsOn(population, range.to)` in `apps/web/src/lib/attendance/dashboard.ts:429`, consumed by `focusRows`/`kpi` in `apps/web/src/app/app/attendance/page.tsx:139-144`.

## 5. Whole-Range Validation

Needs Attention, Absent/Leave days-in-range, Work hours, and the Overtime panel all use `rowsInRange(population, range)` (`page.tsx:138`), i.e. the **actual selected range**, not the widened context window — confirmed by inspecting `useDashboardData`'s `range` parameter being re-filtered down from the broader `win` fetch at `page.tsx:165` (`overtimeSummary`'s `inRange` filter) and `rangeRows` at `page.tsx:138`. Every one of the following was independently recomputed from `attendance_day`/`overtime_record` via SQL and matched the UI exactly, with zero discrepancies, across 5 different ranges (B/D single vs full-month, C week, I termination week, L leave window):
- Missing-punch day/employee counts (27/22, 61/32, 15/14)
- Incomplete-day counts (5/5)
- Late/early-out counts (11/8, 7/7)
- Absent/Leave days-in-range (32/11 for September; 2/2 for the leave-focused range; 10/7 for the week range)
- Overtime detected/approved minutes, pending/approved/rejected record counts, distinct employees (417min/8emp/6-pending/1-approved/1-rejected for the week range; matching figures for the termination range)
- Work-on-leave-unresolved day counts (1, matching SQL)

No case of range leakage (window-only data counted into a whole-range total) was found.

## 6. Context-Window Validation

`windowRange()` (`apps/web/src/lib/attendance/dashboard.ts:137-140`) widens the fetch window to `max(14 days ending at range.to, the selected range)` — confirmed via the actual `/v1/attendance/days` network requests captured for every test (e.g. range `2026-09-30`→`2026-09-30` fetched `2026-09-17`→`2026-09-30`; range `2026-09-01`→`2026-09-30` fetched exactly `2026-09-01`→`2026-09-30`, i.e. the window did **not** overreach past the explicit range when the range itself was already ≥14 days).

1. **KPI totals unaffected by the wider window**: confirmed — focus-date KPIs only ever reflect `range.to`, never anything from the extra context days (§4).
2. **No leakage into whole-range totals**: confirmed — `rangeRows`/`attention`/`overtimeSummary`'s "in-range" figures are explicitly re-filtered to `range.from`/`range.to`, not `win.from`/`win.to` (§5); SQL cross-checks against the *explicit* range, not the wider window, matched in every case, proving no window data leaked into range totals.
3. **Trend boundaries**: correct in every test — a 30-day range's trend chart used exactly `2026-09-01`→`2026-09-30` with no extra days (visually and per network request), and the week/day ranges correctly extended back 14 days.
4. **Heatmap boundaries**: correct — `musterDates()` caps at `MAX_MUSTER_DAYS=31` and otherwise mirrors the window dates; no duplicate or missing day columns observed across the Sep→Oct boundary (Test C/F).
5. **Month boundaries**: no duplicate/missing days — date arithmetic (`addDays`/`eachDate`) uses `Date.UTC` constructor math throughout, which correctly rolls over month/year boundaries; empirically confirmed via the exact SQL-matched day counts spanning 09-28→10-04 and 09-29→10-01.
6. **Selected range remains authoritative**: confirmed throughout §5.

**Cosmetic finding (not a data bug)**: for the full-September test (D), the trend chart's x-axis rendered a tick labeled "31 Aug" even though the actual `/v1/attendance/days` request was confirmed (via network log) to be exactly `date_from=2026-09-01&date_to=2026-09-30` — no data before Sep 1 was fetched or plotted. This is a charting-library axis-tick-interval artifact, not a date-range or data-scoping defect. See Finding F-5.

## 7. Join-Date Validation

EMP-0010, EMP-0022, EMP-0034 joined 2026-09-15 (confirmed via `employment.joining_date`). Tested 09-14/09-15/09-16:
- **09-14 (day before joining)**: Total Employees = **37**, correctly excluding all 3 not-yet-joined employees from the denominator entirely (not counted as absent, not counted as holiday, simply absent from the row set). SQL: exactly 37 `attendance_day` rows exist for that date.
- **09-15 (join day)**: Total Employees = **40**; new joiners appear and are counted from their first employed day.
- **09-16**: Total Employees = 40, consistent.

No case of an employee appearing (in KPIs, Who's-In, or the heatmap) before their join date was found. PASS.

## 8. Termination Validation (reassesses D-1)

Ground truth (`employment` table): EMP-0013 and EMP-0025, LWD 2026-09-20; EMP-0036, LWD 2026-09-30. None of the three ever receive an `EXITED`-status `attendance_day` row — the daily job simply **stops producing rows** for them after their LWD (confirmed via SQL: zero rows, zero `EXITED`/`NOT_JOINED` status rows, for all three past their LWD).

- **Day before LWD / LWD itself**: employee is still counted normally (e.g. EMP-0036 shows `PRESENT` on its own LWD 09-30; EMP-0013/0025 show `WEEKLY_OFF` on their LWD 09-20, which was a Sunday — correct, since they were still employed through the end of that day).
- **Day after LWD, viewed as a historical (non-"today") date**: the terminated employee has no row and is **cleanly excluded** from `Total Employees` (37 or 38, as appropriate) — not counted as absent, not counted as "not checked in". This matches "D-1 is a semantic question, not an obvious crash" — excluding a departed employee from a past day's headcount is defensible.
- **F-1 (the new, critical finding)**: the *same* exclusion logic does **not** apply when the viewed date happens to equal the application's live `businessToday()`. On that one date, `employeesWithoutRecord()` (`dashboard.ts:439-454`) adds every employee with no row — **without checking employment status** — into `noRecord`, which flows into both `Total Employees` and `Not checked in`. Verified directly: on 2026-10-05 (today), **Meera Rao (EMP-0013), terminated 2026-09-20,** appears in the "Who's in" / Who's-In-equivalent list with status "No record" / "No record yet", under a KPI that reads "40 with no record yet for today" / "Not checked in: 40 — Expected to work, no IN punch". The dashboard is, right now, telling HR that an employee who left two weeks ago is "expected to work" and "not checked in" today.
  - This also means: **the exact same calendar day produces different headcounts depending purely on when you look at it.** Phase 2 (run while real "today" = 2026-10-04) recorded Total=40/NotCheckedIn=3 for 2026-10-04. This phase (real "today" = 2026-10-05) recorded Total=37/NotCheckedIn=0 for that same 2026-10-04, now that it is no longer "today". No underlying data changed between the two observations.
  - Root cause: `employeesWithoutRecord()` filters only on `employee.is_active === false`; since (per the already-known D-1 condition) all 40 employees' `employee.status` is still `PROBATION` — including the three terminated ones — `is_active` is presumably still true for them, so they are never excluded from the "assume they just haven't been calculated yet" bucket.
- **Status distribution / filters / employee lists / reports**: none of these independently re-derive "is this employee currently employed" — they all key off the same `attendance_day` rows (or their absence), so they inherit exactly the same behavior described above.

**D-1 reassessed: CONFIRMED and sharpened.** It is not merely a "cross-date-boundary" cosmetic issue — it is a live, present-tense defect (right now, today, in this environment) whenever any employee has left the company and their `employee.status` has not been updated off the active-ish state.

## 9. Holiday Validation

Both configured holidays tested directly against SQL:
- 2026-09-14: 35 employees `NOT_EXPECTED`/`HOLIDAY` → bucketed `HOLIDAY`; 2 employees `PRESENT`/`HOLIDAY` (worked the holiday) → correctly bucketed `PRESENT`, not `HOLIDAY`. Dashboard: Holiday=35, Present=2, Total=37 (3 not-yet-joined correctly excluded). No holiday employee was counted absent or not-checked-in.
- 2026-10-02: 36 `NOT_EXPECTED`/`HOLIDAY`, 1 `HALF_DAY`/`HOLIDAY`. Dashboard: Holiday=36, Half day=1, Total=37. Matches exactly.

PASS — holiday employees are never misclassified as absent/not-checked-in merely for lacking punches.

## 10. Weekly-Off Validation

2026-10-04 (Sunday), tested as a 1-, 4-, and 7-day range ending on that date: **Weekly off = 34, Half day = 2, Present = 1** every time — exactly matching Phase 2's previously-validated figures. Work-on-weekly-off (the 1 Present + 2 Half-day employees who worked on the weekly off) remained visible and correctly classified in KPIs, the status chart, the trend ("Present %" on a weekly-off day correctly used only the employees who actually worked as the denominator, e.g. the trend showed a half-day worker's day as 0% present since `HALF_DAY` is counted as "expected" but not "attending"), and the heatmap. PASS.

## 11. Leave Validation

Constructed a direct test around two known leave rows: EMP-0007 on leave 2026-09-22, EMP-0019 on leave 2026-09-23. Range 2026-09-20→2026-09-23:
- Focus-date "On leave" KPI (focus = 09-23) = **1** (EMP-0019 only — EMP-0007's leave on a different day inside the range correctly did **not** leak into the focus-date count; EMP-0007 shows status `Present` in the Who's-In list for 09-23, which is accurate — she was present that day, only on leave the day before).
- Whole-range "Leave days in range" = **2** (both leave rows counted, SQL-matched).
- A "Work on approved leave" Needs-Attention item appeared in a different range test (09-29→10-01) scoped to exactly that range's 1 unresolved work-on-leave row (SQL-matched), i.e. work-on-leave stays tied to the correct date and range.

PASS — leave is included/excluded strictly by date, exactly as designed.

## 12. Overtime Validation

Confirmed the documented split holds and is not violated:
- **OT card** (focus-date KPI tile) reflects only overtime detected on `range.to`.
- **OT panel** (range section) reflects the whole selected range, independently fetched over the wider context window and then re-filtered client-side to the exact range (`page.tsx:160-167`).

Two ranges fully cross-checked against SQL:
- 2026-09-28→10-04: detected 417 min (6h57m) / approved 32 min (0h32m) / 8 employees / 6 pending / 1 approved / 1 rejected — **exact match**.
- 2026-09-29→10-01: 5 pending, 0 approved, 0 rejected in that narrower window — **exact match**.

No instance of the focus-card/range-panel split being violated (e.g. the panel never silently fell back to focus-date-only data, and the card never bled in range totals). PASS.

## 13. Regularization Validation (reassesses D-2)

"Regularization pending" was checked across **5 different ranges** (30-Sep single day; 28-Sep–04-Oct week; 01–30 Sep full month; 20–23 Sep leave window; 29-Sep–01-Oct termination window) and the empty 05-Oct range. It returned **exactly 7 requests, 7 employees** in every single case, including the empty range — because, per source (`use-dashboard-data.ts:136-140`), the underlying request is hardcoded as `GET /regularizations?request_status=SUBMITTED` with **no `date_from`/`date_to` parameters at all**, despite the endpoint itself supporting them (`router.py:1234-1256`).

**D-2 CONFIRMED**, with stronger evidence than Phase 2: the count is not merely "the same for every *tested* range" — it is architecturally incapable of varying with the range, because the HTTP request sent to the server never includes the date filter the server already supports. This is a real scope bug (the Needs-Attention panel claims to describe "`<rangeLabel>` — what HR should act on" while this one line item is actually all-time/company-wide), not a data coincidence.

## 14. Payroll Period Validation (reassesses D-3)

- `GET /attendance-periods` (no date filter in the frontend call; the endpoint only supports `status`/`legal_entity_id` — `router.py:1486-1497`) returns **all** periods for the company regardless of the dashboard's selected date range.
- "Payroll period blocked — 1 period" appeared, unchanged, in **every range tested**, including a range entirely inside October (2026-10-01→10-04) that has **zero date overlap** with the blocked period (September 2026, Validation India Pvt Ltd). This is the strongest possible evidence that the indicator is not scoped by date at all — it is a static "does any OPEN+BLOCKED period exist anywhere in the company" signal.
- Three periods exist: October 2026 (Validation India Pvt Ltd, Open/Not validated), September 2026 (Validation Services LLP, Open/Not validated), September 2026 (Validation India Pvt Ltd, Open/**Validation blocked**, "As of 05 Oct"). Legal entity does segment *which* periods exist (confirmed two different Sept rows, one per entity) but does **not** segment what the dashboard's Needs-Attention line shows — that line aggregates across all entities' blocked periods into one count regardless of the `legalEntityId` filter unless that filter is explicitly applied by the user (the filter does narrow the periods *list* panel itself, since `legal_entity_id` is passed to the API, but the blocked-period count in Needs Attention is derived from whichever periods were fetched — correct given the filter, but still never date-range-scoped).
- The dashboard reads the **stored** `last_validation_status` field only; it never calls `POST /attendance-periods/{id}/validate` itself (confirmed by source inspection; no such call exists in `use-dashboard-data.ts` or `page.tsx`). No payroll validation was invoked during this test, per the read-only mandate.

**D-3 CONFIRMED**, with the added evidence that the blocked-period alert is shown even for date ranges with literally no overlap with the blocked period, which is a stronger demonstration of the same underlying design (period status is a company-wide, not date-scoped, signal) than Phase 2 had evidence for.

## 15. Empty-State Validation

The in-dataset window (2026-09-01 through 2026-10-04) has no genuinely empty days for an active population, so the empty-range test used **2026-10-05** — the real current day, one day past the end of the dataset, found via this phase's own date-drift discovery (§18):
- KPI grid: Total 40 / all-zero counts, labelled "40 with no record yet for today" / "Expected to work, no IN punch" — correctly zeroed, no stale numbers carried over from whatever range was previously selected.
- Status distribution: explicit empty-state text, "No attendance records for this date."
- Who's-In / "Today's attendance" list: every employee row renders "No record" / "No record yet" rather than stale prior-range data.
- Needs Attention: correctly still shows the two range-independent items (payroll blocked, regularization pending) since those are not range-derived (§13, §14) — this is consistent with their documented (if debatable) design, not stale data.
- No chart/heatmap showed leftover data from a previously-selected range in any transition observed.

PASS for the empty-state *rendering* itself — clean, no stale values. (The *population* of that empty state, i.e. including a terminated employee as "expected to work", is Finding F-1/§8, not an empty-state defect per se.)

## 16. URL / State Validation

- Every filter change is mirrored into the URL via `router.replace` (`page.tsx:89-92`); confirmed directly via `window.location.href` after a live UI click ("This month" → `?range=month`) and via custom ranges (`?range=custom&from=...&to=...`).
- Full browser navigation to a URL with query params (equivalent to a hard refresh) correctly reconstructs the exact same filter state on load (`parseFilters` in `dashboard.ts:144-161`) — verified by navigating directly to `?range=month` and confirming "This month" was re-selected with the identical 01 Oct–05 Oct range and identical KPI numbers.
- No case was found of the range silently reverting after the API call completed, or of a filter change failing to update the URL.

PASS.

## 17. Network / Race Validation

- Inspected `/v1/attendance/days` requests across the full test sequence: every range change produced exactly one OPTIONS (CORS preflight) + one GET pair per distinct `(date_from, date_to)` window key, consistent with the `useSection` hook's keyed-effect design (`use-dashboard-data.ts:120-127`); no duplicate GETs for an unchanged window were observed.
- One transient zero/blank KPI render ("Total employees: 0 — No employees in scope") was observed once, during scripted automation that set the `From` and `To` native `<input type=date>` fields via two separate rapid tool calls. On deliberate, careful re-testing (typed keyboard input into the fields one at a time, and via direct URL navigation, which fully remounts the page) this did **not** reproduce. A second, closely related test — three rapid real UI clicks across Today → This week → This month — showed a harmless single-frame mixed-highlight artifact in an intermediate screenshot, but the **settled** state was correct and consistent every time. I cannot rule out a very narrow real race window where a human double-edits both date fields faster than React can commit the first change, but I was not able to reliably reproduce a case where **committed, settled** dashboard data was wrong — only a possible transient visual artifact. Recorded as **UNVERIFIED / low-confidence**, not a confirmed defect (Finding F-4).
- No evidence of old-range data being displayed after a new range had fully loaded (settled states were correct in all ~20 range changes performed).

## 18. Timezone / Date-Boundary Validation

This is where the phase's most significant finding originated.

- System clock confirmed via `date`, `timedatectl`, and `SELECT now()`: **2026-10-05 06:28 IST / 2026-10-05 00:58 UTC**, `Asia/Kolkata`, synchronized. The dataset's attendance data ends 2026-10-04.
- `businessToday()` (`apps/web/src/lib/attendance/format.ts:77-86`) correctly computes the India calendar date from `Intl.DateTimeFormat` with explicit `timeZone: "Asia/Kolkata"` — this is the *correct*, previously-hardened implementation (replacing the old UTC-`slice`-based `todayIso()` per the file's own header comments) and it is working exactly as designed: it returned `2026-10-05`, the correct India business date for the real current instant. **No UTC/local-time off-by-one bug was found in `businessToday()` itself.**
- The defect is not in the timezone conversion — it is in the fact that **wall-clock time has simply moved past the dataset's intended "today"**. Clicking the "Today" quick-select button, or using the "This week"/"This month" presets, resolves to 2026-10-05 (and the week/month containing it), not 2026-10-04 as this task brief's test matrix assumed. This was verified directly: the "Today" button showed `05 Oct`, zero attendance everywhere, "40 with no record yet for today".
- Checked the four dates the task specifically flagged for off-by-one risk:
  - **2026-09-30**: tested as a 1-day range and as the end of a full-September range; identical, correct figures both times (38/32/3/1/3/4). No shift observed.
  - **2026-10-01**: tested as a 1-day range, as the end of a 3-day range, and as the start of a 4-day range; Total Employees consistently 37 (correctly excluding the then-3 terminated employees) with no date shift.
  - **2026-10-02** (holiday): Holiday=36, Half day=1, Total=37 — matched SQL exactly, no shift into/out of 10-01 or 10-03.
  - **2026-10-04** (Sunday/weekly-off): Weekly off=34, Half day=2, Present=1 in every range tested that ended on this date — matched Phase 2's figures exactly, no shift.
  - No case of any date rendering, filtering, or aggregating under an adjacent calendar date was found anywhere in this phase's testing. All date arithmetic in `dashboard.ts` (`addDays`, `eachDate`, `weekStart`, `monthStart`) is implemented via `Date.UTC(...)` component construction (never raw ms arithmetic or local-time `Date` parsing), which is the correct approach and was not the source of any defect found.
- **The one real, confirmed date-boundary defect is F-1 (§8)**: because `businessToday()` is (correctly) tied to the real clock, and the "is this employee's missing row because they haven't checked in yet, or because they no longer work here" question is never asked, the dashboard's definition of "Total employees" effectively depends on *when you load the page*, not just *which date you selected*. This will recur every time any employee is terminated: the day after termination, if that day is still "today", they'll count as "not checked in"; a day later, once that date is history, they vanish from the denominator entirely. Both behaviors are individually explicable, but together they mean the same report, re-run a day apart, gives a different number for the same historical date — which is the exact kind of defect Phase 3 was commissioned to find.

## 19. Findings

### F-1 — CRITICAL — "Total employees"/"Not checked in" are not a pure function of the selected date; terminated employees are miscounted as "expected to work today"
- **Description**: `employeesWithoutRecord()` (only invoked when the selected focus date equals `businessToday()`) adds any employee lacking an attendance row for that date into the "no record" bucket, inflating `Total Employees` and `Not Checked In`, without checking whether that employee is still currently employed.
- **Evidence**: On 2026-10-05 (real "today"), Meera Rao (EMP-0013, terminated 2026-09-20 per `employment.last_working_day`) appears in the Who's-In list with status "No record"/"No record yet", and the KPI grid reads "Total employees: 40 — 40 with no record yet for today" / "Not checked in: 40 — Expected to work, no IN punch". The same three terminated employees (EMP-0013, EMP-0025, EMP-0036) were confirmed absent from this inflation once their date became historical: e.g. 2026-10-04 showed Total=37/Not-checked-in=0 when viewed on 2026-10-05, versus the Total=40/Not-checked-in=3 Phase 2 recorded for that identical date while it was still "today".
- **Expected**: A terminated employee should never be presented as "expected to work" / "not checked in" on or after their last working day, regardless of whether the viewed date is "today" or historical.
- **Actual**: They are included as "not checked in"/"expected to work" for exactly one day category (whenever the viewed date is the real current day) and silently excluded (with no visible explanation) for every other day.
- **Impact**: HR-facing headcount and "not checked in" alerts are actively wrong, today, for any company with a recent termination. The same date's figures are non-reproducible across time (a report re-run tomorrow for "today" will disagree with a report run today for "yesterday", for the identical calendar day), which undermines trust in the dashboard for exactly the audience (HR/payroll) it serves. Directly extends/sharpens the already-known D-1.
- **Recommended future action** (not implemented): `employeesWithoutRecord()` should exclude employees whose `employment.last_working_day` (or equivalent "effectively terminated" signal) is before the focus date, not just employees with `is_active === false`. More broadly, `employee.status` should be kept in sync with the `employment` record's `TERMINATED` status (the underlying condition already flagged as D-1) so that every consumer of `employee.status`/`is_active` — not just this one dashboard — sees a consistent signal.

### F-2 — CONFIRMED (extends D-2) — "Regularization pending" is an all-time, company-wide count, never scoped to the selected range
- **Description**: see §13.
- **Evidence**: Identical count (7 requests / 7 employees) returned across 5 structurally different ranges and the empty 2026-10-05 range; the network request is `GET /regularizations?request_status=SUBMITTED` with no date parameters, even though the endpoint accepts `date_from`/`date_to`.
- **Expected**: Either the Needs-Attention line should be scoped to the selected range (consistent with every other line in that panel), or its label/description should make the "all-time" scope explicit to the viewer.
- **Actual**: Presented under the heading "`<rangeLabel>` — what HR should act on", implying range-scoping that does not exist for this one line.
- **Impact**: Low-to-medium — the number itself is accurate (there genuinely are 7 pending requests, company-wide), but a viewer narrowing to a single day could reasonably assume all 7 belong to that day, which is false.
- **Recommended future action** (not implemented): pass `date_from`/`date_to` through to the `/regularizations` call (or relabel the line to indicate it is all-time).

### F-3 — CONFIRMED (extends D-3) — Payroll-period-blocked indicator is never date-scoped, even across months with zero overlap
- **Description**: see §14.
- **Evidence**: "Payroll period blocked — 1 period" appeared unchanged for a range entirely within October (2026-10-01→10-04), which has zero date overlap with the blocked period (September 2026).
- **Expected / Actual / Impact**: as D-3 already described; this phase's evidence is simply stronger (a non-overlapping range still triggers the same alert).
- **Recommended future action** (not implemented): either scope the Needs-Attention "payroll period blocked" item to periods overlapping the selected range, or relabel it as a standing/global alert independent of the date picker.

### F-4 — LOW / UNVERIFIED — Possible transient empty-KPI flash during very rapid, overlapping range-input changes
- **Description**: see §17. Observed once during scripted automation setting both date inputs in quick back-to-back calls; not reproduced under careful keyboard-driven or URL-navigation testing.
- **Evidence**: One screenshot showing "Total employees: 0 — No employees in scope" for range "21 Sep – 01 Oct" immediately after two rapid `form_input` calls; the next screenshot (2s later, after the state had settled) showed the correct value.
- **Expected**: No visible zero/empty flash during a legitimate state transition.
- **Actual**: Possibly a one-frame visual artifact; could not be confirmed as user-reachable.
- **Impact**: If real, cosmetic only (a sub-second flash) — no settled/committed incorrect state was found in any test.
- **Recommended future action** (not implemented): if a future validation pass can reproduce this reliably (e.g. with real OS-level rapid keystrokes), investigate whether `useSection`'s loading transition ever briefly renders with a stale/empty `allDays` before the new window's data lands.

### F-5 — LOW / COSMETIC — Trend chart axis occasionally labels a tick one day before the fetched window
- **Description**: see §6. For the full-September range, the trend chart's x-axis showed a "31 Aug" tick despite the confirmed network request being exactly `2026-09-01`→`2026-09-30`.
- **Evidence**: Network log showed only `date_from=2026-09-01&date_to=2026-09-30`; no earlier data was fetched or plotted.
- **Expected**: Axis ticks should not reference dates outside the fetched/plotted domain.
- **Actual**: One out-of-domain tick label rendered (charting-library tick-interval rounding, not a data bug).
- **Impact**: Cosmetic only.
- **Recommended future action** (not implemented): clamp the charting library's tick generation to the actual data domain.

### F-6 — INFORMATIONAL — "Today"/"This week"/"This month" quick-select presets reflect the real system clock, not the validation dataset's intended "current" date
- **Description**: Because the dataset was built assuming "today" = 2026-10-04 but the environment's clock has since advanced to 2026-10-05, every quick-select preset (not just custom ranges) now resolves one day later than the dataset's last populated day, surfacing the dataset's natural edge as an always-empty "Today" view.
- **Evidence**: §3 Test A′, §15, §18.
- **Expected / Actual**: This is correct, intended behavior for a production dashboard (today should always mean today); it is called out because it changes what "the obvious way to test 'today'" means for *this* fixed-date validation dataset, and because it is the proximate trigger for F-1.
- **Impact**: None for production correctness; relevant only to how this and future fixed-dataset validation passes should be run (date ranges intended to represent "today" must be entered explicitly via Custom, not via the Today/This week/This month buttons, once real time has moved past the dataset's horizon).
- **Recommended future action** (not implemented): none required of the application; future validation refreshes of this dataset should either regenerate it with a rolling "today", or document that Custom-range entry must be used once the dataset's horizon has passed.

## 20. Regression Tests

No frontend/TypeScript/build/backend test suites were run in this phase, per the task's explicit instruction and the CRITICAL data-safety rule in the operational setup (the `apps/api` pytest suite defaults to `hrms_dev` and would truncate the exact dataset under validation). All verification in this phase was performed via:
- Live UI interaction against the real dev servers (browser automation), and
- Independent, read-only SQL queries against `attendance_day`, `overtime_record`, and `employment` for every quantitative figure reported in §3–§14.

No code, schema, data, roles, or permissions were modified. No commits, pushes, or PRs were made. This file is the only artifact written during this phase.

## 21. Final Verdict

**PASS WITH FINDINGS.** The attendance dashboard's date-range machinery (focus date vs. whole range vs. context window) is implemented correctly and consistently, and every numeric aggregation checked against independent SQL matched exactly across single-day, week, month, and boundary-crossing ranges, including holiday, weekly-off, join-date, and termination edge cases. D-2 and D-3 from Phase 2 are both reconfirmed with stronger evidence. The one new, material issue this phase surfaced (F-1) is that "Total employees"/"Not checked in" silently change in value for a *fixed* historical date depending on whether that date happened to be "today" when calculated versus when viewed later — concretely demonstrated by this phase re-observing 2026-10-04 (Phase 2's "today") one day after the fact and getting a different, lower headcount with zero underlying data change, and by a currently-terminated employee still appearing as "expected to work today" in the live view. This is a real, user-facing defect worth fixing before relying on this dashboard's headcount figures for any company with employee turnover, but it does not indicate any broader breakage of the date-range/filtering system itself — every other mechanism tested held up under direct, independent verification.
