# Attendance implementation roadmap

19 November 2026. Planning only. Findings: `ATTENDANCE_COMPLETE_AUDIT_REPORT.md` (AUD-xx) and the 16 Nov
engine reports (MA-xx). UI detail: `ATTENDANCE_UI_UX_IMPROVEMENT_PLAN.md`. Scenarios: `ATTENDANCE_TEST_SCENARIO_MATRIX.md` (S-xx).

Complexity: S = under a day, M = 1–3 days, L = a week or more including verification.
Every task follows `AGENTS.md`: work on `test`, checks from `.github/workflows/ci.yml`, PR to `main`.
Tasks touching `apps/api/alembic/` need a person to merge.

## Order and dependencies

```
Owner decisions (Group A sheet + D-AUD-1..4 below)
        │
        ▼
Phase A  engine accuracy (MA-xx)  ──────────────┐
        │                                       │
Phase B  one aggregation layer (R-B01..B04) ────┤  B can start in parallel with A:
        │                                       │  it only regroups stored rows
        ▼                                       │
Phase C  explanation contract (R-C01..C03) ◄────┘  needs A's rules to be settled
        │
        ├──► Phase D web (R-D01..D07)
        ├──► Phase E mobile (R-E01..E05)    D and E in parallel, same contract
        ▼
Phase F  reports and payroll consistency (R-F01..F03)  needs B
Phase G  tests: written alongside each task; G01–G03 gate the end
```

Quick wins that need no decision and no new contract, which can go first: **R-D01** (holiday headline),
**R-D02** (no verdict while working, web), **R-B04** (calculated-at), **R-G01** (consistency test, written failing).

## Decisions needed (new from this audit)

| ID | Question | Blocks |
|---|---|---|
| D-AUD-1 | What is a half day worth in the attendance rate? (Recommend 0.5.) | R-B01 |
| D-AUD-2 | Is a `HALF_DAY` "present" on the home dashboard? (Recommend: show it as its own figure, weighted 0.5 in rates.) | R-B01 |
| D-AUD-3 | Support WFH as a real status, or remove the type and the Remote figures? | R-B05 |
| D-AUD-4 | Is offline punching wanted on mobile? | R-E05 |
| Group A | H-01, H-02, H-03, H-04, P-05, P-04, D-01a/b, H-05, H-07/08, H-29, O-19, L-06, L-09, H-30 (`ATTENDANCE_DECISION_SHEET_GROUP_A_2026-11-18.md`) | Phase A |

---

## Phase A: critical accuracy and data integrity

These are the engine and recalc defects already reproduced on 16 Nov. They are listed here so the order is in
one place. Each needs its decision first, then an impact report on any locked day (none in production yet,
per the decision sheet; re-check).

| Task | Problem | Files | Depends | Approach | Risk | Pri | Size |
|---|---|---|---|---|---|---|---|
| R-A01 | MA-01: band gaps pay full day | `calculation.py` band lookup; policy publish validation in `service.py` | H-01 | Refuse gappy bands at publish; uncovered minutes → `CONFIG_ERROR`; list existing gappy versions | High | P0 | M |
| R-A02 | MA-02: no-show paid at lock under `TREAT_PRESENT` | finalize path `service.py` ~8319-8430 | H-02 | Per decision | High | P0 | M |
| R-A03 | MA-06: punch after close owned by locked day counted nowhere | `service.py` punch intake, `punch_ownership.py` | — | Report as close blocker / HR queue | High | P0 | M |
| R-A04 | MA-07: schedule change recalcs one date only | `recalc.py`, `ownership_service.py` | — | Widen recalc to the ownership neighbourhood (±1 day) | Med | P0 | M |
| R-A05 | MA-10: pay-basis / legal-entity edits queue no recalc | employee service hooks → `AttendanceRecalcRequest` | — | Enqueue; add closed-period guard | Med | P1 | S |
| R-A06 | MA-03: comp-off does not follow OT corrections | OT / leave credit | H-03 | Per decision | Med | P1 | M |
| R-A07 | MA-04, MA-05, MA-09, MA-13, MA-20, H-29 | `calculation.py` | respective decisions | Per decision, one engine version bump for the batch | High | P1 | L |

**Acceptance for Phase A:** each MA scenario in the matrix (S-30 to S-38) gives its decided outcome in the
engine unit tests and in one API integration test; `ENGINE_VERSION` bumped once; recalc impact query run on
the dev database and reviewed.

---

## Phase B: one source of truth for aggregates

| Task | Description |
|---|---|
| **R-B01** | **One bucket and exception definition.** |
| Problem | AUD-01, AUD-02, AUD-10: overview and summary bucket and count differently; clients have two more copies. |
| Files | `attendance/summary.py`, `attendance/overview.py`, new `attendance/day_classification.py`; consumers `web/src/lib/dashboard/overview.ts`, `web/src/lib/attendance/summary.ts` |
| Depends | D-AUD-1, D-AUD-2 |
| Approach | One SQL expression builder for bucket, `is_exception`, `in_progress` (clock-aware for today) and `weight` (1 / 0.5 / 0). `summary.py` and `overview.py` both import it. Keep the overview endpoint's response shape for one release and compute it from the summary service, or retire it and point the home dashboard at summary. |
| Outcome | Home dashboard and Attendance page show the same figures for the same date and filters. |
| Risk / Pri / Size | Medium / P0 / M |
| Tests | R-G01 consistency test; existing `test_attendance_summary.py` and `test_company_attendance_overview.py` extended with HALF_DAY, open punch today, CONFIG_ERROR, no-record past date. |
| Acceptance | For a seeded day with one of each status, both endpoints return identical present / absent / half-day / leave / not-in-yet / exception counts; rate uses the agreed half-day weight. |

| Task | Description |
|---|---|
| **R-B02** | **Display status from the backend.** Add `display: {code, label, tone, glyph, provisional}` to `AttendanceDayRead` (computed in `schemas.py` `attendance_day_to_read` from the same classifier as R-B01). Web `attendance-status-badge.tsx`, `dashboard.ts bucketOf`, mobile `attendanceBucketOf` read it, falling back to today's logic for old rows. Fixes AUD-11 and removes two client copies. Risk Low, P1, M. Acceptance: no screen shows "Not expected" for a holiday; web and mobile labels match for every status (snapshot test of the label table on both sides). |
| **R-B03** | **One month figure.** Expose the period-summary arithmetic (`service.py` ~8040-8260) as a function that can run on unlocked rows for any employee and month: `GET /attendance/employees/{id}/month-summary?month=` returning paid, LOP, leave, weekly off, holiday, half days, OT approved by class, late count. Web month view and HR calendar row totals use it. Fixes AUD-09. Risk Medium (perf on HR grid: batch endpoint for many employees). P1, M. Acceptance: for any employee and closed month, the month card equals the frozen `AttendancePeriodSummary`. |
| **R-B04** | **Freshness.** Add `calculated_through` (max `calculated_at` in the population) and `next_scheduled_run` to `AttendanceSummaryRead`. Fixes AUD-15. Risk Low, P1, S. |
| **R-B05** | **WFH.** After D-AUD-3: either implement `WFH` as an overlay in `calculation.py` (like ON_DUTY) or remove `WFH` from `_REGULARIZATION_TYPES` (`schemas.py:117`) and drop Remote tiles. First, verify what an approved WFH request writes today (S-27). Risk Medium if implemented (engine bump), Low if removed. P2, S–M. |
| **R-B06** | **Past-date missing rows.** Count `no_record` for any focus date in `summary.py:350` (not only today), labelled "Not calculated"; HR gets a Recalculate action (existing `calculate-range`). Fixes AUD-08. Risk Low, P1, S. |

---

## Phase C: result transparency

| Task | Problem | Approach | Depends | Risk | Pri | Size |
|---|---|---|---|---|---|---|
| **R-C01** | AUD-06: no reason for a verdict | Backend `explain(day, policy_version, shift_version, snapshot) -> Explanation` (shape in UI plan §4.1), pure function in `attendance/explanation.py`; templates per status (§4.2); returned on `GET /attendance/days/{id}` and optionally on list reads behind `?include=explanation`. Thresholds come from the policy version in force, never recomputed. | A for the rules it describes; can ship for settled rules first | Medium | P0 | L |
| R-C02 | AUD-07: incomplete → LOP surprise | `explanation.action` with deadline (period end) and consequence from the policy's lock behaviour; same text in `reminders.py` email | R-C01 | Low | P0 | S |
| R-C03 | AUD-14: OT shown ≠ OT paid | `explanation.overtime` with found / approved / pending / class label from `OvertimeRecord` | R-C01 | Low | P1 | S |
| R-C04 | AUD-06: raw details visible to employees | Gate "technical details" by permission; show policy versions by name and effective date | — | Low | P1 | S |

**Acceptance for C:** for every row in matrix section 2 (calculation scenarios) the explanation reason line
names the threshold that decided the status, with the policy's own values; a snapshot test per template.

---

## Phase D: web

| Task | Description | Finding | Depends | Pri | Size |
|---|---|---|---|---|---|
| **R-D01** | Fix the day headline order in `lib/attendance/day-detail.ts summarizeDay`: holiday → name, weekly off, other non-working. Unit test for each `calendar_day_type`. | AUD-04 | — | P0 | S |
| **R-D02** | No verdict while the shift is running: in `self-view.tsx` and `day-summary.tsx`, when today and `actual_last_out` is null and `scheduled_end` is in the future (or not set and the day is not over), hide the status badge and show "Working since…" (as mobile does). Replace with `display.provisional` after R-B02. | AUD-03 | — | P0 | S |
| R-D03 | One live worked figure for an open day, plus time left in shift | AUD-05 | — | P1 | S |
| R-D04 | "Why this result" panel on the day page and day sheet, from `explanation` | AUD-06 | R-C01 | P0 | M |
| R-D05 | Calendar redesign (UI plan §3): markers, split cells, future vs no-record, full legend, day sheet, month header from R-B03 | AUD-12, AUD-09 | R-B02, R-B03 | P1 | M |
| R-D06 | HR: freshness line, "Not calculated" count with Recalculate, close-readiness view | AUD-15, AUD-08, AUD-07 | R-B04, R-B06, R-B03 | P1 | M |
| R-D07 | AP-09: delta chips compare like with like (same time last week) or hide before shift start | AP-09 | R-B01 | P2 | S |

## Phase E: mobile

| Task | Description | Depends | Pri | Size |
|---|---|---|---|---|
| R-E01 | Use backend `display` and month summary in `attendance_summary.dart`, `employee_attendance_summary.dart`, `hr_calendar.dart` (coordinate with the uncommitted calendar sort work) | R-B02, R-B03 | P1 | M |
| R-E02 | "Why this result" section in `attendance_day_detail_screen.dart`; move version ids into gated technical details | R-C01 | P0 | M |
| R-E03 | Calendar cell markers and day bottom sheet (`my_calendar_screen.dart`, `attendance_calendar_screen.dart`) | R-B02 | P1 | M |
| R-E04 | Today card: time left in shift, break allowance, reason when punching is blocked on the button | — | P2 | S |
| R-E05 | Offline punches, only if D-AUD-4 says yes: local outbox, device-time and location-age fields, server acceptance rules | D-AUD-4 | P3 | L |

All mobile tasks: golden tests at 320/360/390, and a device check, since Flutter cannot run on this machine.

## Phase F: reports, analytics, payroll

| Task | Description | Depends | Pri | Size |
|---|---|---|---|---|
| R-F01 | Reports and CSV exports state their basis ("whole days" vs "payroll days") and use R-B03 for any paid / LOP column | R-B03 | P1 | S |
| R-F02 | Period finalize preview lists days that will be resolved as absent at lock, by employee, with links | R-C02 | P1 | S |
| R-F03 | OT reports show found / approved / pending / paid class consistently with payroll's `ot_minutes_*` | R-C03 | P2 | S |

## Phase G: testing and verification

| Task | Description | Pri | Size |
|---|---|---|---|
| **R-G01** | **Cross-surface consistency test** (API integration): seed one company with a day of each status and flag; assert summary, overview (or its replacement), month summary and frozen period summary agree; assert web `bucketOf` and mobile `attendanceBucketOf` tables match the backend's (shared JSON fixture). Write it first; it should fail today on AUD-01/02/08. | P0 | M |
| R-G02 | Web e2e (Playwright, `apps/web/e2e/`): employee self view while working, after punch-out, holiday day page, HR Today tab totals vs home dashboard | P1 | M |
| R-G03 | Run Flutter tests in CI (carried from 16 Nov) | P1 | S |
| R-G04 | Scenario matrix rows S-01..S-45 each linked to a test id; untested rows listed in the matrix | P1 | M |
| R-G05 | Performance: summary and month-summary endpoints on 1,000 employees × 31 days under 500 ms (p95) on staging | P2 | S |

## Suggested sprints

1. **Week 1:** owner decisions D-AUD-1..3 and Group A session 1; R-D01, R-D02, R-B04, R-B06, R-G01 (failing), R-C04.
2. **Week 2:** R-B01, R-B02, R-A01..A04.
3. **Week 3:** R-C01..C03, R-B03, R-A05..A07 as decisions land.
4. **Week 4:** R-D03..D06, R-E01..E03, R-F01..F02, R-G02..G04.
5. Then R-D07, R-E04, R-F03, R-G05; R-E05 only if decided.
