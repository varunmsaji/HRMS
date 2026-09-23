# Payroll Blocker Register

| Field | Value |
|---|---|
| Audit date | 2026-09-10 |
| Commit | `e33fcdb` |
| Parent document | [`PRE_PAYROLL_PRODUCTION_READINESS_AUDIT.md`](./PRE_PAYROLL_PRODUCTION_READINESS_AUDIT.md) |

**Severity scale**

| Badge | Meaning |
|---|---|
| 🔴 BLOCKER | Can cause incorrect payroll, data corruption, security breach, cross-tenant access, or catastrophic production failure |
| 🟠 CRITICAL | Must be fixed before Payroll depends on the affected behaviour |
| 🟡 HIGH | Significant production or business risk |
| 🔵 MEDIUM | Should be addressed; does not block Payroll |
| 🟢 LOW | Improvement / technical debt |

**Classification** — every item is tagged as one of:
`TECHNICAL FINDING` · `SECURITY FINDING` · `TEST GAP` · `DOCUMENTATION GAP` ·
`CLIENT BUSINESS DECISION` · `PRODUCT DECISION`

---

## Summary

| Severity | Count |
|---|---|
| 🔴 BLOCKER | 5 |
| 🟠 CRITICAL | 14 |
| 🟡 HIGH | 17 |
| 🔵 MEDIUM | 15 |
| 🟢 LOW | 8 |
| **Total** | **59** |

Plus **12 open client business decisions** and **3 open product decisions**, listed at the end.

---

## 🔴 BLOCKERS

### PAY-001 — No batch attendance generation; a period cannot be finalized in practice

| | |
|---|---|
| **Classification** | TECHNICAL FINDING |
| **Severity** | 🔴 BLOCKER |
| **Module** | attendance |

**Why it matters.** Payroll's input is the frozen `AttendancePeriodSummary`, produced only by
`AttendancePeriodService.finalize`. Finalization is gated on `EMPLOYEES_WITHOUT_ATTENDANCE`, which
requires an `AttendanceDay` row for **every calendar day of every employment spell** overlapping the
period. There is no way to create those rows in bulk.

**Evidence**

- `apps/api/src/hrms/modules/attendance/router.py:858` — `POST /v1/attendance/days/calculate` is the
  only creation path; it takes one `employee_id` and one `target_date`.
- `apps/api/src/hrms/modules/attendance/router.py:883` — `recompute` operates on one existing row.
- `grep -rn "@celery_app.task" src/` → tasks exist only in `health`, `employee_import`, and `leave`.
  **No attendance task exists.**
- `apps/api/src/hrms/modules/attendance/service.py:4744-4763` — the validation gate:
  `expected = (span_end - span_start).days + 1; if day_counts.get(employee_id, 0) < expected: missing`.

**Failure scenario.** A 100-employee company closes August. 100 employees × 31 days = 3 100 separate
HTTP calls, each issuing ~50–70 queries. A 1 000-employee company would need 31 000 calls. Finalization
is not achievable, so no frozen summary is ever produced, so Payroll has no input.

**Required fix.** Add `POST /v1/attendance/days/calculate-batch` (employee set × date range) plus a
Celery task for scheduled nightly generation. Resolve policies and calendars **once per (scope,
date-range)** rather than once per employee-day.

---

### PAY-002 — `AttendancePeriodSummary` contains no paid-days figure

| | |
|---|---|
| **Classification** | TECHNICAL FINDING |
| **Severity** | 🔴 BLOCKER |
| **Module** | attendance |

**Why it matters.** `AttendancePeriodSummary` is explicitly designed as the artifact Payroll reads
("the payroll-facing per-employee roll-up… the frozen snapshot Payroll will eventually read (ADR-0005)",
`attendance/models.py:929-936`). It carries no paid-days or payable-days column.

**Evidence** — `apps/api/src/hrms/modules/attendance/models.py:951-966`. Columns present:
`present_days`, `absent_days`, `leave_days`, `holiday_days`, `weekly_off_days`, `half_days`, `lop_days`,
`ot_minutes_normal/weekly_off/holiday/night`, `comp_off_minutes_earned`, `late_count`,
`worked_minutes_total`. **No `paid_days`. No `payable_days`.**

`attendance_day.paid_day_fraction` exists per row, but it is never aggregated into the frozen snapshot —
so Payroll would have to re-aggregate live day rows, defeating the entire purpose of freezing.

**Failure scenario.** Payroll either (a) reads unfrozen day rows, losing the immutability guarantee, or
(b) derives paid days from the buckets — which is impossible, because of PAY-003.

**Required fix.** Add `paid_days` (sum of `paid_day_fraction`) and `payable_days` to
`attendance_period_summary`, populated in `_aggregate_day_rows`.

---

### PAY-003 — Summary buckets double-count and under-cover; they do not reconcile

| | |
|---|---|
| **Classification** | TECHNICAL FINDING |
| **Severity** | 🔴 BLOCKER |
| **Module** | attendance |

**Evidence** — `apps/api/src/hrms/modules/attendance/service.py:4940-4951`:

```python
if   row.attendance_status == "PRESENT":  agg["present_days"] += 1
elif row.attendance_status == "HALF_DAY": agg["half_days"]    += 1
elif row.attendance_status == "ABSENT":   agg["absent_days"]  += 1
elif row.attendance_status == "LEAVE":    agg["leave_days"]   += 1

if   row.calendar_day_type == "HOLIDAY":     agg["holiday_days"]     += 1
elif row.calendar_day_type == "WEEKLY_OFF":  agg["weekly_off_days"]  += 1
```

Three defects:

1. **Double counting.** An employee who works on a holiday gets `attendance_status = "PRESENT"` **and**
   `calendar_day_type = "HOLIDAY"` — incrementing `present_days` *and* `holiday_days`. Any Payroll rule
   summing both overstates the month.
2. **Under-coverage.** Five statuses fall through every branch and land in no bucket:
   `INCOMPLETE`, `NOT_EXPECTED`, `CONFIG_ERROR`, `ON_DUTY`, `NOT_JOINED`, `EXITED`.
3. **Half-day leave is misfiled.** A half-day leave produces `attendance_status = "HALF_DAY"`
   (`calculation.py:928`), so it increments `half_days` and **never** `leave_days` — leave consumption is
   silently understated.

**Failure scenario.** A 31-day month with 4 worked holidays and 3 incomplete days:
`present_days + absent_days + leave_days + half_days + holiday_days + weekly_off_days` ≠ 31, and no
combination of buckets recovers the true payable figure.

**Required fix.** Make status buckets mutually exclusive; count `holiday_days`/`weekly_off_days` only for
`NOT_EXPECTED` days; add explicit `incomplete_days`, `on_duty_days`, `not_employed_days`; add a
reconciliation assertion that all buckets sum to the employment days in the period.

---

### PAY-004 — Days before joining are paid at 1.00

| | |
|---|---|
| **Classification** | TECHNICAL FINDING |
| **Severity** | 🔴 BLOCKER |
| **Module** | attendance |

**Evidence** — `apps/api/src/hrms/modules/attendance/calculation.py:984`:

```python
paid_fraction = "1.00" if status in ("NOT_JOINED", "NOT_EXPECTED") else "0.00"
```

`NOT_JOINED` is the population-gate result for a date before any employment spell begins
(`service.py:2739`). Any such day computed into an `AttendanceDay` carries `paid_day_fraction = 1.00`.

**Failure scenario.** An employee joins 15 August. An operator (or a future batch job) calculates the
full month 1–31 August. Days 1–14 are `NOT_JOINED` with `paid_day_fraction = 1.00`. Payroll summing
`paid_day_fraction` pays a full month to someone employed for half of it.

*Mitigating context:* the finalization gate only requires rows for employment days, so `NOT_JOINED` rows
are not mandatory. But nothing prevents them, and PAY-001's fix — a date-range batch job — makes their
creation the default outcome.

**Required fix.** `NOT_JOINED` → `paid_day_fraction = "0.00"`.

---

### TST-001 — CI does not run the integration or security test suites

| | |
|---|---|
| **Classification** | TEST GAP |
| **Severity** | 🔴 BLOCKER |
| **Module** | CI |

**Evidence** — `.github/workflows/ci.yml`:

- No `services:` block; no docker-compose step. **No PostgreSQL, no Redis.**
- Line 47: `DATABASE_URL: postgresql://hrms:hrms_dev_password@localhost:5433/hrms_dev`
- Line 51: `run: uv run pytest` — and `pyproject.toml:67` sets `testpaths = ["tests"]`.

**62 of 87 test files require a live PostgreSQL** (60 integration + 2 security). Locally, the full suite
passes:

```
$ .venv/bin/python -m pytest tests -q
1145 passed in 239.79s
```

In CI, none of the 783 integration tests can execute.

Two compounding problems in the same lines:

- The CI role is **`hrms`**, the superuser with `BYPASSRLS` that
  `infra/docker/postgres/init/002_app_role.sql:3-6` explicitly warns must never be the application's
  role. Even if a database were provisioned, RLS would be bypassed.
- No Redis, so the rate-limiter tests cannot pass either.

**Failure scenario.** Every finding in this register — the paid/LOP defects, the inert policy fields, the
leave balance hole — would have to be caught by review alone. No regression in business logic,
authorization, or tenant isolation is gated on merge.

**Required fix.** Add `services: postgres:16 / redis:7`, run `alembic upgrade head` and the app-role init
SQL, and point `DATABASE_URL` at **`hrms_app`**. Roughly fifteen lines of YAML — the highest-leverage fix
in this audit.

---

## 🟠 CRITICAL

### PAY-005 — Days after exit carry `lop_fraction = 1.00`

**Classification:** TECHNICAL FINDING · **Module:** attendance

`calculation.py:985-989` — `lop_fraction = "1.00" if status in ("ABSENT", "EXITED")`.
An employee leaving on 15 August, with days 16–31 computed, accrues 16 days of loss-of-pay. Payroll
deducting on `lop_days` would deduct against a final settlement.

**Fix:** `EXITED` → `lop_fraction = "0.00"`. Out of employment is not loss of pay.

---

### PAY-006 — INCOMPLETE days carry neither paid nor LOP until lock

**Classification:** TECHNICAL FINDING · **Module:** attendance

`calculation.py:1519` — `return "0.00", "0.00"  # INCOMPLETE / CONFIG_ERROR`.
Between calculation and finalization, an INCOMPLETE day contributes 0 to both paid and LOP, so
`paid + lop ≠ 1`. Resolution happens only inside `finalize`
(`_apply_incomplete_lock_resolution:5016`). Any Payroll preview, dashboard, or report reading unlocked
days sees a figure that will later change.

**Fix:** decide and implement the pre-lock semantics; enforce that Payroll reads only CLOSED periods.

---

### PAY-007 — The lock-time paid/LOP rewrite is unaudited and untested

**Classification:** TECHNICAL FINDING + TEST GAP · **Module:** attendance

`_apply_incomplete_lock_resolution` (`service.py:5016-5051`) silently rewrites `paid_day_fraction` and
`lop_fraction` on every INCOMPLETE day immediately before locking. Three problems:

1. **No audit row.** This is the most payroll-consequential mutation in the system and
   `AuditService.record` is never called for it.
2. **`attendance_status` stays `INCOMPLETE`** while the fractions say otherwise
   (`repository.py:1212-1215`) — a Payroll rule keyed on status disagrees with one keyed on fraction.
3. **Implicit ORM synchronization.** The repository issues a Core `update()` (`repository.py:1216-1220`);
   `finalize` then aggregates the *same in-memory ORM objects* four lines later (`service.py:5099` →
   `:5101`). Whether the frozen summary reflects the resolution depends on SQLAlchemy's
   `synchronize_session="auto"` behaviour. **No test asserts `summary.lop_days` after an INCOMPLETE
   resolution.**

**Fix:** resolve fractions in Python before aggregating (or re-read after the update), write an audit
row, and add the missing test.

---

### PAY-008 — Attendance results are not exactly reproducible

**Classification:** TECHNICAL FINDING · **Module:** attendance

Two independent causes:

1. **Sibling-day dependency.** `prior_late_days_in_window` and `prior_excess_break_days_in_window`
   (`service.py:2959-2981`) and `remaining_weekly_minutes` / `remaining_monthly_minutes`
   (`service.py:3009-3038`) are read live from sibling days at compute time and are **never written into
   `computation_snapshot`**. Recomputing an unchanged day can therefore produce a different
   `ot_minutes_detected` or a different status.
2. **No engine-version stamp.** `calculation_version` is a per-row recompute counter
   (`service.py:2569`), not an identifier of the algorithm. Once ATT-001…005 are fixed, old and new rows
   become indistinguishable.

Both are documented as accepted trade-offs (WD-29 decision 3, WD-32 decisions 2/3) — but neither was
assessed against a Payroll consumer that must defend a payslip.

**Fix:** persist the derived sibling-day inputs into `computation_snapshot`; add an `ENGINE_VERSION`
constant and an `attendance_day.engine_version` column.

---

### PAY-010 — Leave balance is checked at submit and never again

**Classification:** TECHNICAL FINDING · **Module:** leave

`submit` verifies `current_balance >= total_days` (`leave/service.py:2002-2024`).
`_apply_approval` then inserts the debit **unconditionally** (`leave/service.py:2465-2480`) — no
re-check, no row lock, no constraint.

**Failure scenario.** An employee with 5 days of balance submits two 5-day applications on Monday. Both
pass the submit check (`reserve_balance_on_submission` defaults to `False`). A manager approves both on
Tuesday. Balance: −5. Payroll then pays 10 days of leave that was never accrued.

**Fix:** re-check inside `_apply_approval` under `SELECT … FOR UPDATE` on the employee's ledger rows, and
honour `allow_negative_balance`.

---

### DAT-001 — Leave accrual idempotency has no database constraint

**Classification:** TECHNICAL FINDING · **Module:** leave

`run_for_company` does `exists_for_cycle(...)` then `insert(...)`
(`leave/service.py:1400-1435`) with no unique index on
`(company_id, employee_id, leave_type_id, entry_type, effective_date)`. Two concurrent
`leave.accrue_company` executions both observe "not yet written" and both insert.

Compounded by **OPS-006**: Celery Beat has no leader election, so two beat replicas double-fire
`run_monthly_accrual` by design.

**Fix:** partial unique index for `entry_type IN ('ACCRUAL','CARRY_FORWARD')`; catch `IntegrityError` and
treat it as "already written".

---

### SEC-001 — CORS makes the API unusable in production

**Classification:** SECURITY FINDING · **Module:** core

`apps/api/src/hrms/app.py:36-42`:

```python
allow_origins=["*"] if settings.is_development else [],
allow_credentials=True,
```

In production, `allow_origins` is an **empty list** — the deployed frontend cannot call the API at all.
In development, `["*"]` with `allow_credentials=True` is a combination browsers reject outright.

**Fix:** a `cors_allowed_origins` setting; fail boot if production resolves to an empty list.

---

### ATT-001 — Punch rounding is configured everywhere and applied nowhere

**Classification:** TECHNICAL FINDING + DOCUMENTATION GAP · **Module:** attendance

`apply_rounding()` (`calculation.py:637-644`) has **zero call sites**. Verified:

```
$ grep -rn "apply_rounding" src/
calculation.py:627:  (docstring reference)
calculation.py:637:  def apply_rounding(...)
```

`punch_rounding` and `rounding_minutes` are validated at publish, persisted on
`AttendancePolicyVersion`, exposed via the API and UI, plumbed into `PolicyInputs`
(`service.py:2895-2896`) — and never read. Late, early, and worked minutes are computed from raw punch
instants.

`docs/business-rules/ATTENDANCE_V1_CONFIGURATION_CATALOG.md` documents this behaviour as implemented.
**DOCUMENTATION / IMPLEMENTATION CONFLICT.**

**Fix:** implement it, or remove the fields and the UI and record the removal.

---

### ATT-002 — `missing_punch_behaviour = AUTO_CLOSE` does nothing

**Classification:** TECHNICAL FINDING · **Module:** attendance

`auto_close_after_minutes` and `auto_close_uses_shift_end` have **zero references** outside
`models.py`/`schemas.py`. `auto_closed` is hard-coded `False` (`calculation.py:1139` and `:1287`). The
`AUTO_CLOSE` branch (`calculation.py:1483`) falls through to band-based status **without synthesising a
closing OUT punch**, so worked minutes for the unpaired interval are zero — producing ABSENT or
INCOMPLETE rather than the auto-closed day the policy promises.

---

### ATT-003 — `half_day_split` / `half_day_boundary_minutes` never read

**Classification:** TECHNICAL FINDING · **Module:** attendance

Both are passed into `PolicyInputs` (`service.py:2899-2900`) and never referenced by the engine. Half-day
status comes exclusively from `AttendancePolicyHourBand` lookups. `BY_SHIFT_MIDPOINT` and
`BY_BOUNDARY_TIME` modes have no implementation.

---

### ATT-005 — `night_ot_mode = WINDOW` never evaluates the night window

**Classification:** TECHNICAL FINDING · **Module:** attendance

`is_night` is derived solely from `shift.is_cross_midnight` (`calculation.py:1237`, `:1388`).
`night_window_start` / `night_window_end` are carried into `OvertimePolicyInputs`
(`service.py:3048-3049`) and never read. `classify_ot_day` gates on `night_ot_mode in ("WINDOW","BOTH")`
(`calculation.py:691`) — but only when `is_night` is already true, which only happens for cross-midnight
shifts. A day shift with work inside the configured night window is never classified as NIGHT OT.

**Payroll impact:** night OT typically carries a different multiplier. Misclassification is money.

---

### PAY-013 — Timezone changes are unguarded; the guard written for this exact case is an empty function

**Classification:** TECHNICAL FINDING · **Module:** organisation

`organisation/service.py:601-608`:

```python
def _assert_timezone_change_allowed(self, company_id, current_timezone, new_timezone) -> None:
    """Documented no-op hook until Payroll/Attendance modules exist (Domain Model §5.5)."""
    _ = (company_id, current_timezone, new_timezone)
```

Called from `update_company_profile:598-599` on every timezone change. It is the **only remaining
placeholder of its kind** in the codebase — `grep -rn "documented no-op"` returns one hit.
`update_branch` (`:1005-1087`) has no equivalent hook at all.

**Why it matters.** Timezone resolution is `ShiftVersion.timezone > Branch.timezone > Company.timezone`
(`calculation.py:294-298`), and most shifts and branches leave it unset — so the company value is
load-bearing. It determines `_local_to_utc` for the scheduled span, the punch-load window, break-window
matching (local time-of-day, `calculation.py:585`), and core-hours evaluation.

**Failure scenario.** A company corrects its timezone from `Asia/Kolkata` to `Asia/Dubai`. Every unlocked
historical day, on its next recompute, resolves a scheduled start 90 minutes earlier in UTC — changing
late minutes, potentially crossing a late band, potentially changing status and paid days. Nothing warns
anyone.

**Partial mitigation.** `attendance_day.timezone` is stored, so the value used is recoverable — but
recompute re-resolves live rather than reading it, so the stored value changes too.

**Required fix.** Implement the hook: refuse when a `CLOSED` period or any calculated `AttendanceDay`
exists, or require explicit acknowledgement. Add the same guard to `update_branch`.

---

### PAY-014 — Onboarding activation creates no compensation record

**Classification:** TECHNICAL FINDING + DOCUMENTATION GAP · **Module:** onboarding

`OnboardingActivationService.activate_case` (`onboarding/service.py:864-1017`) writes
Employee → Employment → Assignment → (optional) Bank → (optional) Statutory. **It never writes
`employee_compensation`.**

```
$ grep -n "ompensation" src/hrms/modules/onboarding/*.py
src/hrms/modules/onboarding/schemas.py:17:  ...(§8.6/O7 only writes Employee/Employment/Assignment/
                                              Compensation/Statutory/Bank)...
```

The one mention is a docstring **stating that compensation is written**. It is not.
**DOCUMENTATION / IMPLEMENTATION CONFLICT.**

The bulk-import path *does* create it (`employee_import/service.py:_create_employee_row` →
`compensation_service.create_compensation`). So the same employee has a CTC if loaded from a spreadsheet
and no CTC if hired through the digital onboarding flow.

**Failure scenario.** A company onboards its next 40 hires through the wizard. Payroll launches and
encounters 40 employees with no `employee_compensation` row and no signal that anything is missing —
because compensation has no consumer until Payroll exists, nothing has ever detected it.

**Required fix.** Collect compensation during onboarding and write it at activation, or make activation
require an explicit compensation input. Correct the docstring either way.

---

### OPS-001 — No production deployment path exists

**Classification:** TECHNICAL FINDING · **Module:** infrastructure

No CD workflow, no web Dockerfile, no production compose/Helm/Terraform, no migration step in any
pipeline, no rollback procedure. The API container runs as **root**, as a single `uvicorn` process
(`gunicorn` is a declared but unused dependency), with no `HEALTHCHECK`.
`20260803124757.downgrade()` raises `NotImplementedError`.

---

### OPS-002 — No backups, no restore testing, no RPO/RTO

**Classification:** TECHNICAL FINDING · **Module:** infrastructure

Nothing in the repository configures, schedules, or documents a database or object-storage backup. Per
this audit's own rule, backups cannot be called reliable without a rehearsed restore — and no restore
procedure exists to rehearse. **Blocking for production, not for Payroll development.**

---

### OPS-003 — No monitoring, error tracking, metrics, or alerting

**Classification:** TECHNICAL FINDING · **Module:** infrastructure

Sentry is a comment (`core/errors/handlers.py:79`), and the unhandled exception is explicitly discarded
(`_ = exc`, line 80) — **not even logged**. `structlog` is configured but `get_logger` has no call sites
in any module. No metrics, no health probing of dependencies, no background-job monitoring, no alerts.

If attendance calculation starts failing in production, or leave accrual silently skips 500 employees, or
database errors spike — nobody finds out until a user complains.

---

## 🟡 HIGH

| ID | Finding | Classification | Evidence |
|---|---|---|---|
| PAY-011 | `allow_negative_balance` is never read anywhere; behaviour is hard-coded | TECHNICAL | `grep` → `leave/models.py:145` only |
| PAY-012 | Weekly-off `off_fraction` computed then discarded — half-day weekly offs become full | TECHNICAL | `calendar_resolution.py:140` `is_off, _fraction = …` |
| TEN-002 | Test suite runs as the BYPASSRLS superuser, so RLS is unverified except in one file | TEST GAP | `tests/conftest.py:9`, `ci.yml:47` vs `tests/security/test_rls_runtime_role.py:64` |
| DAT-002 | Zero pagination on ~45 list endpoints; no `LIMIT` in any list query | TECHNICAL | `shared/pagination.py:14` defined, never constructed |
| DAT-003 | N+1 queries: breaks per day row; 8-scope walk per policy kind; accrual per employee×type | TECHNICAL | `service.py:2477`; `calendar_resolution.py:301`; `leave/service.py:1365` |
| SEC-002 | Rate limiting on 1 of ~150 endpoints; login and public onboarding unlimited | SECURITY | `organisation/router.py:88` is the only `rate_limit(` call site |
| SEC-003 | Access **and refresh** tokens in `localStorage` | SECURITY | `web/src/lib/auth/token-storage.ts:3-13` (documented trade-off) |
| SEC-004 | No security headers, no `TrustedHostMiddleware`, no proxy-header handling | SECURITY | `app.py:36-45`; `shared/rate_limit.py:49` keys on `request.client.host` |
| OPS-004 | `/health` does not probe DB or Redis; no liveness/readiness split; no `HEALTHCHECK` | TECHNICAL | `modules/health/router.py`; `Dockerfile` |
| OPS-005 | Container runs as root; single uvicorn process; unused `gunicorn` dependency | TECHNICAL | `Dockerfile:21-27` |
| OPS-006 | Celery Beat has no leader election; duplicate firing is possible by design | TECHNICAL | `core/celery_app.py:29-50` |
| OPS-010 | No Celery task has a retry policy or logs anything | TECHNICAL | `leave/tasks.py` |
| TST-002 | No frontend CI at all — 45 vitest files, `tsc`, `next lint`, `next build` never run | TEST GAP | `.github/workflows/ci.yml` has one job |
| TST-003 | No coverage measurement or threshold | TEST GAP | No `pytest-cov` in `pyproject.toml` |
| TST-004 | No concurrency test anywhere; optimistic locking verified only via stale-version input | TEST GAP | Suite inspection |
| DOC-001 | Configuration catalogues document behaviour the engine does not implement | DOCUMENTATION | ATT-001…005 vs `ATTENDANCE_V1_CONFIGURATION_CATALOG.md` |
| ARC-001 | `attendance/service.py` 5 480 lines / 9 service classes | TECHNICAL | `wc -l` |
| ARC-002 | Module→module import edges unconstrained; `leave ↔ attendance` cycle hidden by function-scoped imports | TECHNICAL | `.importlinter` declares layers only |
| ARC-003 | `LeaveDayProjection` duplicates `LeaveApplicationDay` with no DB-level sync guarantee | TECHNICAL | `attendance/models.py:976` vs `leave/models.py:314` |
| SEED-1 | Demo seed has no environment guard — can create a known-credential super-admin in production | SECURITY | `apps/api/scripts/seed.py`; `docs/development/DEMO_SEED_CREDENTIALS.md` |
| IMP-001 | `process_batch` has **no re-entry guard**. Celery brokers redeliver at-least-once; a redelivery reruns the batch from row 1. Rows already committed stay committed. Auto-generated `employee_code`s would not collide → silent duplicate employees. | TECHNICAL | `employee_import/service.py:443`; `tasks.py:10-13` |
| IMP-002 | `create_batch` commits before enqueueing (deliberate). If `.delay()` fails, the batch is permanently `PENDING` with no retry, timeout, or detection. | TECHNICAL | `employee_import/service.py:157-166` |
| AUD-1 | No audit-log read API or UI; the trail is reachable only by direct SQL | TECHNICAL | No route references `AuditLog` |

---

## 🔵 MEDIUM

| ID | Finding | Classification | Evidence |
|---|---|---|---|
| ATT-004 | `excess_break_behaviour` never read; FLAG/HALF_DAY/ABSENT/DEDUCT have no effect | TECHNICAL | `service.py:2906` passes it; engine never reads it |
| ATT-006 | Zero-reference fields: `early_out_uses_core_end`, `split_shift_block_mandatory`, `split_shift_allow_hours_compensation`, `wfh_requires_punch`, `wfh_uses_shift_hours`, `requires_pre_approval`, `auto_approve_within_minutes` | TECHNICAL | `grep` per field |
| ATT-007 | `late_count_window` / `excess_break_count_window` stored but the window is hard-coded to the calendar month | TECHNICAL | `service.py:2952-2957` |
| ATT-009 | `match_breaks` compares only the **gap start** time-of-day to break windows | TECHNICAL | `calculation.py:585-604` |
| ATT-010 | SPLIT shifts never compute late/early and never apply core-hours or cumulative overrides | TECHNICAL | `calculation.py:1424-1427`, `:1362-1371` |
| ATT-011 | `round_minutes` NEAREST uses Python `round()` → banker's rounding | TECHNICAL | `calculation.py:634` |
| ATT-013 | Half-day leave + work → status `HALF_DAY` but `paid_day_fraction = 1.00` | TECHNICAL | `calculation.py:929-935` |
| DAT-004 | `_reverse_approval` uses `date.today()` — server-local, not company timezone | TECHNICAL | `leave/service.py:2597` |
| DAT-005 | Backdating check uses `date.today()`; `max_requests_per_month` counts by UTC month of `submitted_at` | TECHNICAL | `leave/service.py:1979`, `:1990` |
| DAT-006 | Same-leave-type overlapping applications not blocked at submit; caught only at approve | TECHNICAL | `leave/service.py:1911` checks *other* types only |
| DAT-010 | No FK from `leave_day_projection.leave_application_id` | TECHNICAL | `attendance/models.py:1012-1014` |
| SEC-005 | Upload accepts and stores any client `content_type`; no MIME allow-list, no magic-byte check, unsanitised filename in the S3 key | SECURITY | `onboarding/service.py:571, 583` |
| SEC-006 | `await file.read()` buffers the whole upload before the size check | SECURITY | `public_router.py:94` → `service.py:566` |
| SEC-007 | `company` has `FORCE ROW LEVEL SECURITY` but RLS is never `ENABLE`d and no policy exists | SECURITY | `scripts/sql/002_row_level_security.sql:10-11` |
| SEC-011 | No dependency vulnerability scanning, SAST, or secret scanning in CI | SECURITY | `.github/workflows/ci.yml` |
| DOC-002 | `docs/business-rules/policies/` is untracked in git | DOCUMENTATION | `git status` → `?? docs/business-rules/policies/` |
| IMP-003 | `process_batch` commits every 25 rows; a crash leaves a batch stuck at `PROCESSING` with some employees created and no record of which rows succeeded beyond counters | TECHNICAL | `employee_import/service.py:331-334` |
| IMP-004 | Whole CSV buffered in memory at upload; `MAX_IMPORT_ROWS = 1000` enforced only after parsing the entire file; no `Content-Length` pre-check | TECHNICAL | `employee_import/router.py:28`; `service.py:181-182` |
| ERR-1 | Catch-all handler discards the exception without logging it | TECHNICAL | `core/errors/handlers.py:80` |

---

## 🟢 LOW

| ID | Finding | Classification |
|---|---|---|
| ATT-008 | Scheduled breaks with no punched gap are never deducted (documented limitation) | TECHNICAL |
| ATT-012 | `_evaluate_no_schedule` has a redundant `lop_fraction` conditional | TECHNICAL |
| DAT-007 | `vpf_percentage` annotated `float` over a `Numeric(9,4)` column | TECHNICAL |
| DAT-009 | `Numeric(3,2)` fractions leave no headroom for quarter-day constructs | TECHNICAL |
| DAT-012 | No partitioning on `punch` / `attendance_day` (documented deferral, WD-26) | TECHNICAL |
| SEC-010 | No password reset, email verification, or MFA; weak password policy | SECURITY |
| ARC-004 | Cross-module recompute is synchronous; ADR-0012 outbox unimplemented | TECHNICAL |
| DOC-004 | Untracked non-project artifacts at the repo root (`mavericks-kit.zip`, `jersouy/`, …) | DOCUMENTATION |
| DOC-005 | Superseded NestJS docs sit alongside current documentation | DOCUMENTATION |
| DEAD-1 | Dead code: `apply_rounding`, `ingestion/routes.py`, `PaginationMeta`, `MoneyAmount`, `get_logger`, `gunicorn` | TECHNICAL |
| FE-1 | No duplicate-submission guard, no unsaved-changes guard, no company-timezone renderer despite ADR-0010 | TECHNICAL |
| TZ-1 | No DST-transition test | TEST GAP |

---

## CLIENT BUSINESS DECISIONS REQUIRED

These are **not** technical defects. Each is a genuine business question the code cannot answer, and each
changes what Payroll must compute. **BUSINESS DECISION REQUIRED** — none has been decided silently.

| ID | Decision | Current code behaviour | Why it matters for Payroll |
|---|---|---|---|
| BUS-001 | Are holidays and weekly offs paid days for **every** employment type? | `NOT_EXPECTED` → `paid_day_fraction = 1.00` unconditionally (`calculation.py:984`) | Monthly-salaried: correct. Daily-wage or contract: overpayment. |
| BUS-002 | How are days before joining and after exit treated inside a payroll period? | Before joining: paid 1.00 (PAY-004). After exit: LOP 1.00 (PAY-005). | Directly changes first and final settlements |
| BUS-003 | Are half-day weekly offs (e.g. alternate half-Saturdays) required? | Computed then discarded (PAY-012) | Half a day of pay per occurrence |
| BUS-004 | May HR cancel an employee's approved leave? | **No** — only the original submitter (`leave/service.py:2512-2513`) | An employee who leaves the company cannot have their leave cancelled |
| BUS-005 | Is a negative leave balance ever permitted, and under what approval? | Blocked at submit; unguarded at approve; the policy switch is inert (PAY-010, PAY-011) | Determines whether payroll recovers overdrawn leave |
| BUS-006 | If an approval would overdraw the balance: block it, or allow and recover in payroll? | Neither — it silently goes negative | Recovery mechanism must exist in Payroll if "allow" |
| BUS-007 | What is the payroll period grain — company, legal entity, or pay cycle? | Company only; `attendance_period.legal_entity_id` reserved and always NULL (PD-LOCK-1 open) | Multi-entity clients cannot close entities independently |
| BUS-008 | Who may reopen a closed period once payroll has consumed it, and what happens to already-paid figures? | `ATTENDANCE.UNLOCK` may reopen; **no arrears mechanism exists** (PD-LOCK-2 open) | Retrospective correction has no defined path |
| BUS-009 | Restricted / optional holidays default to **working** unless the calendar says otherwise (PD-CAL-1) | `restricted_holidays_are_off_by_default` per work calendar | Holiday pay eligibility |
| BUS-010 | A holiday falling on a weekly off stays a weekly off, with **no** compensatory day (WD-05, PD-CAL-2) | Flag set, no substitution | Lost holiday entitlement |
| BUS-011 | Overtime on a **full-day leave** day — is it payable? | OT is detected before the leave overlay, so a leave day can carry `ot_minutes_detected > 0` | Paying OT on a day already paid as leave |
| BUS-012 | Under `work_on_leave_behaviour = PRESENT_CANCEL_LEAVE_HINT`, the employee is paid as present **and** the leave day stays debited until HR acts | Flag raised; Attendance never cancels the leave | Double cost per occurrence |
| BUS-013 | Should ordinary leave expire, beyond the carry-forward cap? | Only comp-off expires; ordinary leave never lapses | Unbounded liability accrual |
| BUS-014 | Is advance leave (borrowing against future accrual) required? | Not implemented | — |
| BUS-015 | `comp_off_day_length_minutes` must be set per overtime policy, or **comp-off is never credited** | Unset → the credit engine skips the policy entirely (`attendance/models.py:262-266`) | Employees silently earn nothing |

---

## PRODUCT DECISIONS REQUIRED

| ID | Decision | Context |
|---|---|---|
| PD-1 | For each of the ~15 inert policy fields (ATT-001…007, PAY-011): **implement or remove?** Shipping a configuration screen that changes nothing is worse than not shipping it. | The catalogues document them as working |
| PD-2 | Should Payroll be **structurally prevented** from reading unlocked periods, or is that a documented convention? | Given PAY-006 and PAY-008, the audit recommends enforcement in code |
| PD-3 | Does Leave need its own closable period, or is the attendance period authoritative for both? | Leave balances currently move freely across a closed attendance period |

---

*No application code, schema, migration, test, or configuration was modified during this audit.*
