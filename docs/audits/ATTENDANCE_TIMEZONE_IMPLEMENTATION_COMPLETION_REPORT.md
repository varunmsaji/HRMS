# Attendance/Timezone Remediation — Implementation Completion Report

**Prepared:** 2026-09-15
**Programme:** [`ATTENDANCE_TIMEZONE_FINAL_DECISION_AND_EXECUTION_GATE.md`](./ATTENDANCE_TIMEZONE_FINAL_DECISION_AND_EXECUTION_GATE.md) (the authoritative spec — §0 decision register, §21 phase plan)
**Phases covered by this report:** 0 through 9 (all phases in the plan). Phase 10 (staging/UAT) and production are explicitly **not** covered — see *Remaining risks*.
**Code changed:** YES · **Schema changed:** NO · **Migrations added:** NO · **Tests changed:** YES · **CI changed:** YES (Phase 0-CI, prior session)

---

## 1. Executive result

> ## READY FOR STAGING. NOT READY FOR PRODUCTION.

Every phase in the plan (0 through 9) is implemented, tested, and passing. All eight `CD-` client
decisions and the fourteen `DEC-TZ-` register entries this programme depends on were selected before
implementation began (§0 of the gate document) and were not re-litigated — this report is an execution
record, not a second decision pass.

Three facts block production specifically, and **none of them is closable from this repository**:
a production timezone inventory (`B4`), a production access-log check for third-party callers of the
punch endpoint this programme split in two (`B5`), and a PII retention sign-off for punch-submission
evidence that this implementation deliberately does not yet capture (`B8`). These are listed in full
under *Remaining risks*, not glossed over.

---

## 2. Changes by phase

| Phase | What shipped | Status |
|---|---|---|
| **0 — CI + baseline** | Backend/web baselines measured; dev-DB timezone inventory (`DH-1`) run; 4 pre-existing `mypy` errors fixed; 15 pre-existing `ruff format` files found (not fixed, unrelated) | Done, with **`B4`/`B5` left open** — see below |
| **0-CI** | `ci.yml` rewritten: postgres+redis services, RLS role verification, migrations applied, unit/integration+security split, new `web` job | Done |
| **1 — Input/timestamp security** | Split `/attendance/punches/me` (self, server clock) from `/attendance/punches` (on-behalf, validated client timestamp); `AwareIsoDatetime`; future/pre-employment punch rejection; server-assigned `source` | Done |
| **2 — India timezone invariant** | `shared/timezone.py`; `ShiftVersion`/`Branch` timezone validation (closes the `IST`-typo-500 bug); company timezone allow-list (`Asia/Kolkata` only) at registration and profile update | Done |
| **3 — Historical integrity** | `_assert_timezone_change_allowed` implemented for real (was a no-op stub) and wired into **both** `update_company_profile` and `update_branch`; branch-scope resolved via full `EmployeeAssignment` history | Done |
| **4 — Attendance date / period lock** | `shared/business_time.py` (`business_today`/`business_month_start`); period-lock basis moved from the punch's UTC date to "local date OR previous local date open" (`DEC-TZ-05`/`CD-1`); `todayIso()` deleted, replaced by `businessToday(company_timezone)` at 8 web call sites | Done |
| **5 — Cross-midnight breaks** | `_break_window_contains` — wrap-aware break matching, replacing the non-wrap-aware `start <= t <= end` comparison that silently unpaid every midnight-spanning break | Done |
| **6 — UI timezone** | `formatClockTime`/`formatDateTime` require an explicit `tz`; `zoneLabel()`; every rendered attendance time carries a zone label; **`DEC-010` amended** (this session — see §3) | Done |
| **7 — Leave job `as_of`** *(this session)* | `leave/tasks.py`'s three per-company async wrappers (`_accrue_company_async`, `_sweep_comp_off_expiry_async`, `_run_year_end_async`) now derive `as_of` via `business_today(company.timezone)` — all three fire at 01:00/01:30/02:00 IST under Celery Beat's own `Asia/Kolkata` timezone config, squarely inside the 00:00–05:29 IST window where the old `datetime.now(UTC).date()` was silently one day behind | Done |
| **8 — Calculation trigger & concurrency** *(this session)* | Best-effort immediate calculate after every punch insert; `SELECT ... FOR UPDATE` + savepoint-based insert-race recovery in `AttendanceDayService.calculate()`; `attendance.run_daily_calculation` Beat task (09:30 IST, trailing 3 days); orphan-punch report (`AttendanceDayService.list_orphaned_punches`, `SR-14`-aware) | Done |
| **9 — Final regression & this report** *(this session)* | Full backend + web suites re-run; `mypy`/`ruff`/import-linter re-run tree-wide; `git diff` reviewed; this report written | Done |

---

## 3. `DEC-010` amendment (`CD-3`)

[`docs/adr/0010-utc-storage-company-timezone-render.md`](../adr/0010-utc-storage-company-timezone-render.md)
now carries an **Amendment (2026-09-15)** section: the rendering source of truth for attendance
timestamps is the WD-06-resolved zone (`ShiftVersion > Branch > Company`, recorded per-row on
`attendance_day.timezone`), not the literal `company.timezone` column the ADR originally named.
`company.timezone` remains authoritative for every non-attendance timestamp and for business-day
boundaries where no more specific zone applies. For the current tenant base (all `Asia/Kolkata`, no
branch-level override in use) this changes no visible behaviour today — it is correct in advance of
the day a second timezone is onboarded, per `CD-3` (SELECTED, gate §13.3/§19).

`docs/business-rules/attendance/ATTENDANCE_TIMEZONE_DECISION_REGISTER.md`'s `DEC-TZ-10` entry already
carries its own `SUPERSEDED` marker (recorded in a prior session) noting the execution gate's §10
overrode its original recommendation — confirmed still accurate, no further edit needed.

---

## 4. Database changes

**None.** No migration was added or is required by this programme, Phase 0 through Phase 9. Every fix
was achievable through validation, application logic, or query changes against the existing schema.
`attendance_day.timezone`, `punch.raw_payload`, `punch.idempotency_key` and every other column this
programme reasons about already existed before this work began.

---

## 5. Behaviour changes (production-visible)

| Change | Old behaviour | New behaviour | Risk direction |
|---|---|---|---|
| Punch endpoint split | One endpoint, client-controlled `punch_time`/`source` for everyone | Two endpoints: self (`/me`, server clock, no `punch_time` field) and on-behalf (validated, permissioned) | **Breaking** for any caller of the old single endpoint — see `B5` |
| Company timezone | Free-text IANA string, unvalidated | Locked to `Asia/Kolkata` at registration/profile-update; `Branch`/`ShiftVersion` validate but stay unrestricted | Tightens; no known live company outside the allow-list (dev-DB inventory only, see `B4`) |
| Timezone change after attendance exists | Silent (a documented no-op stub) | Refused once any computed `attendance_day` exists for the scope, with a `TRIAL`/zero-days escape hatch | Tightens; closes a silent-history-rewrite hole |
| Period-lock basis for punches | Punch's raw UTC calendar date | Local (company-tz) date OR the previous local date — reject only if **both** are closed | Loosens slightly at period boundaries by design (`CD-1`) — trades a rare "recoverable false acceptance" against the old "unrecoverable false rejection" |
| Cross-midnight breaks | Silently unpaid, `worked_minutes`/OT under-counted | Correctly matched and paid | Corrects underpayment — **recompute of affected historical days is a separate, not-yet-scheduled operational step**, not part of this code change |
| UI attendance times | Rendered in the viewer's browser timezone, unlabelled | Rendered in the WD-06-resolved zone, always labelled (e.g. "IST") | Corrects a display bug; zero visible change while every tenant is `Asia/Kolkata` |
| `attendance_day` row creation | Only on an interactive `POST /calculate` call | Also fires automatically (best-effort) after every punch, and daily at 09:30 IST for the trailing 3 days | New: an employee who only punches IN now gets a visible (if incomplete) attendance row same-day, without a human pressing a button |
| Leave job `as_of` (monthly accrual, comp-off expiry, year-end sweep) | UTC calendar date at each job's scheduled instant (01:00/01:30/02:00 IST — all inside the skew window) | India business (IST) date | Corrects a real, live bug: every monthly accrual run was computing the previous month's 1st, silently, every month |

---

## 6. Security improvements

- **Authoritative clock (`DEC-TZ-01`).** Self-service punches are now server-stamped; the previous
  behaviour let any holder of the baseline punch permission set their own `late_minutes`/
  `worked_minutes`/`ot_minutes_detected`/`paid_day_fraction`/`lop_fraction` by typing a different time
  into an editable form field.
- **Server-assigned `source` (`DEC-TZ-05`).** A caller can no longer label a hand-typed web punch as
  `DEVICE`/`REGULARIZATION`, closing the audit-provenance forgery gap.
- **Naive-timestamp rejection (`DEC-TZ-04`).** `AwareIsoDatetime` closes the 5h30m dev/production
  divergence for an offset-less timestamp.
- **Future/pre-employment punch bounds (`DEC-TZ-03`, gate §8.2).** `2099-01-01Z` and `1900-01-01Z`
  (both previously accepted, verified) are now rejected.
- **Timezone-change guard (`DEC-TZ-13`).** Closes the silent historical-attendance-rewrite hole,
  `update_branch` included — the pre-existing stub had no call site there at all.

---

## 7. Historical integrity

- Every fix in Phases 1–6 that could alter *already-computed* attendance (break matching, timezone
  resolution) is guarded by the timezone-change lock (Phase 3) and by `calculate()`'s own
  unconditional refusal to touch a `is_locked=true` row.
- No bulk recompute of historical `attendance_day` rows was run or is included in this programme.
  The cross-midnight break fix (Phase 5) and any other correctness fix that changes computed values
  will only affect **future** calculations and any day a human or the new scheduled job explicitly
  recomputes — existing historical rows are unaffected until then.
- Phase 8's `SELECT ... FOR UPDATE` + savepoint insert-race recovery (execution gate §17.3) is
  verified by two dedicated concurrency tests (`test_attendance_concurrency.py`) proving two
  genuinely concurrent `calculate()` calls for the same employee-date — both the first-ever-insert
  race and the ordinary-recompute race — never produce duplicate rows or a lost update.

---

## 8. Tests

| Suite | Result |
|---|---|
| Backend unit + integration + security | **1228 passed, 19 failed** — the exact same 19 pre-existing failures documented at the Phase 0 baseline (RBAC default-roles-backfill migration interaction with test helpers, unrelated to this programme, out of scope). No growth in that count across any phase. |
| Backend `mypy` | `Success: no issues found in 134 source files` |
| Backend `ruff check` | `All checks passed!` |
| Backend `ruff format --check` (tree-wide) | 7 pre-existing files still need reformatting (down from 15 at the Phase 0 baseline — reduced incidentally as other phases touched some of those files for unrelated reasons). All 7 are in `onboarding`/`leave` modules this programme does not touch; none is in the diff this session produced. |
| Import-linter | `Contracts: 1 kept, 0 broken` |
| Web (`TZ=America/New_York npm test`) | **46 files, 356 tests passed** (up from the documented 45/342 baseline — net growth from `format.test.ts` expansion in Phase 6) |
| Web `tsc --noEmit` | Clean |

**New tests added this session (Phases 7–9):**

- `tests/integration/modules/leave/test_leave_tasks_business_time.py` — 4 tests, proving the leave
  job `as_of` fix at the exact instants those jobs are Beat-scheduled to fire.
- `tests/integration/modules/attendance/test_attendance_concurrency.py` — 2 tests, the first-ever-
  insert race and the ordinary-recompute race, both via genuinely concurrent HTTP requests.
- `tests/integration/modules/attendance/test_attendance_orphan_report.py` — 3 tests: a punch outside
  the padded window is reported, the same local time is *not* reported for a no-shift employee
  (`SR-14`), and a punch on a date with no `AttendanceDay` row at all is reported.
- `tests/integration/modules/attendance/test_attendance_tasks.py` — 3 tests: the scheduled task's
  date derivation, its survival of one locked-day exception mid-loop, and the fan-out mechanism.
- Two existing assertions in `test_attendance_day.py` were relaxed from exact `calculation_version`
  equality to monotonic-increase checks — a direct, correct consequence of Phase 8's immediate
  calculate hook now firing on every punch, not a loosened regression guard.

---

## 9. CI

Unchanged from the prior session's Phase 0-CI work. One known, documented deviation remains: CI's
integration+security job runs against the `hrms` (schema-owner, `BYPASSRLS`) role rather than
`hrms_app` (the runtime, `NOBYPASSRLS` role), because dozens of pre-existing fixture-teardown helpers
across the suite do raw cross-tenant `DELETE`s with no RLS GUC set and rely on `BYPASSRLS` to succeed.
RLS correctness itself is still proven — `tests/security/test_rls_runtime_role.py` repoints its own
engine to `hrms_app` specifically to prove it. This is flagged in `ci.yml` as an intentional deviation
from the gate document's own §18.4 checklist item 3, not something this session attempted to silently
"fix" by repointing `DATABASE_URL` (doing so was measured, in the prior session, to break 130 existing
tests).

---

## 10. Remaining risks — genuinely unclosable from this repository

| ID | Risk | Why it can't be closed here |
|---|---|---|
| **`B4`** | Production timezone inventory never run. Only the dev DB was inventoried (3 `Asia/Calcutta` `TRIAL` companies, 22 `UTC` branch/shift-version rows, all zero computed attendance — safe). Production's actual state is unknown. | Requires production database access this session does not have. |
| **`B5`** | Production access-log check for third-party callers of the old single punch endpoint (now split in two, Phase 1) was never run. If a third-party integration calls the old shape, Phase 1's breaking change needs a deprecation window, not a same-day cutover. | Requires production access/deployment logs this session does not have. |
| **`B8`** | PII retention sign-off for `punch.raw_payload` (would carry submitted offset, user-agent, client version, device id, IP — F-18) was never obtained. This column is **declared in the schema and still never written by anything in this implementation** — confirmed: `grep -rn "raw_payload" apps/api/src/hrms/modules/attendance/` returns only the model declaration. Deliberately left out of Phase 1's scope pending that sign-off. | Requires a legal/compliance decision, not an engineering one. |

None of these three block **staging**. All three block **production**.

### Residual, non-blocking gaps

- `ruff format`: 7 pre-existing files in `onboarding`/`leave` modules still need reformatting —
  unrelated to this programme, not fixed, not in this session's diff.
- No ESLint configuration exists for `apps/web` — the web CI job uses `tsc --noEmit` instead of
  `npm run lint`, documented in `ci.yml` as an intentional substitution (the ESLint setup prompt hangs
  interactively without one).
- **Live browser verification was not possible this session.** Ports 3000/8000 were occupied by
  another session's dev servers throughout — checked again at the start of Phase 9 and still occupied.
  This session did not force the issue by stopping another session's server. All UI timezone-label
  changes (Phase 6) are covered by unit tests (`formatClockTime`/`formatDateTime` under multiple
  `TZ` values) but have not been visually confirmed in a running browser.
- No bulk recompute of historical attendance was run for the cross-midnight break fix (Phase 5) or any
  other correctness change — see §7. This is a deliberate scope boundary, not an oversight: a bulk
  recompute is an operational decision with its own communication/notice requirements (per the gate
  document's own guidance on `F-04`/`F-06`-class fixes), not a same-session code change.

---

## 11. Rollback

Every change in this programme is additive at the schema level (no migrations) and behaviourally
reversible by reverting the relevant commits:

- **Phases 7–9 (this session)** are independent of Phases 1–6 at the code level (different files,
  aside from the shared `business_time.py`/`timezone.py` helpers Phase 4/2 already built) and can be
  reverted alone if needed — e.g., disabling `attendance.run_daily_calculation`'s Beat entry and
  removing the punch-insert hook's call in `PunchService.record_punch` fully restores the pre-Phase-8
  "calculation only on explicit request" behaviour, with zero data-layer consequence (no rows this
  hook creates are otherwise invalid — `calculate()`'s idempotency guarantees that).
- **Phase 1's endpoint split** is the one change in the whole programme with an external contract
  consequence (a caller of the old single endpoint breaks) — see `B5`.
- No change in this session is destructive to existing data; every write path remains append-only
  (punches) or full-row-replacement (attendance days, per `WD-10`).

---

## 12. Production recommendation

**Do not deploy to production until `B4`, `B5`, and `B8` are closed.** Staging/UAT (Phase 10) may
proceed now — nothing in this report's remaining risks blocks it. Recommended order:

1. Deploy to staging; run Phase 10's UAT against the full test matrix this programme already covers.
2. In parallel, close `B4` (production timezone inventory) and `B5` (production access-log check) —
   both are measurement tasks, not development tasks, and do not block staging.
3. Obtain `B8`'s PII retention sign-off before wiring `punch.raw_payload` in a follow-up change (out
   of this programme's scope by design — see Phase 1's own documented deferral).
4. Once `B4`/`B5`/`B8` are closed and staging sign-off is obtained, production deployment may proceed.

---

*Prepared 2026-09-15, continuing the same session's Phase 7–9 work atop the prior session's Phase 0–6
implementation. Every number in this report was measured directly (test runs, `mypy`/`ruff`/import-
linter invocations, `git diff`/`grep` against the working tree) during this session, not carried
forward from the handoff brief without verification.*
