# Data Integrity Audit

| Field | Value |
|---|---|
| Audit date | 2026-09-10 |
| Commit | `e33fcdb` |
| Scope | Database design · transactions · concurrency · idempotency · historical integrity · numeric safety |
| Parent document | [`PRE_PAYROLL_PRODUCTION_READINESS_AUDIT.md`](./PRE_PAYROLL_PRODUCTION_READINESS_AUDIT.md) |
| Verdict | 🟠 **NEEDS FIX BEFORE PAYROLL** — strong constraint design, two concrete correctness holes |

---

## Executive position

The database design is careful and, in several places, better than typical. Effective-dated entities are
protected by GiST exclusion constraints rather than application checks. Facts that should never change —
punches, ledger entries, audit rows, workflow timelines — have no update path at all. Money is stored as
integer minor units and no floating-point arithmetic touches any financial or duration value anywhere in
the audited code.

Two things break the picture, and both are narrow:

1. **The leave balance has no concurrency control.** It is verified at submission and never again, and
   accrual idempotency is a check-then-insert with no backing constraint.
2. **Attendance results are not exactly reproducible.** Version snapshots recover most of the picture,
   but sibling-day inputs are unpersisted and there is no engine-version stamp.

Everything else in this document is either a strength worth preserving or a bounded, low-effort fix.

---

## 1. Schema inventory

| Metric | Value |
|---|---|
| Tables | 79 |
| Alembic revisions | 61 |
| Tables with RLS | 70 |
| Tables with `company_id` | 70 |
| GiST exclusion constraints | 5+ (employment, policy assignment, published policy versions, attendance period, shift version) |
| Append-only tables (no update path) | 7 (`punch`, `leave_ledger`, `audit_log`, and four `*_action` timelines) |

---

## 2. Constraint design — verified strengths

### 2.1 GiST exclusion constraints

| Constraint | Guarantee | Evidence |
|---|---|---|
| `employment_no_overlap` | Two employment spells for the same employee cannot have overlapping `[joining_date, last_working_day]` ranges — which makes **"at most one ACTIVE employment"** a database guarantee, not an application check | migration `20260814090000`; `employee/models.py:82-86` |
| Policy version no-overlap | Two `PUBLISHED` versions of the same policy cannot cover the same date | migrations `20260819100000`/`110000`/`120000`, `20260830090000` |
| `PolicyAssignment` no-overlap | One scope cannot have two effective assignments for the same policy kind (and, for leave, the same leave type) | migration `20260818130000`, widened by `20260903090000` |
| `AttendancePeriod` no-overlap | Two periods for the same company cannot overlap | migration `20260824090000` |
| `ShiftVersion` no-overlap | Same shape as policy versions | migration `20260818140000` |

This is the correct tool for effective-dated data, and it is used consistently.

### 2.2 CHECK constraints encoding business invariants

| Constraint | Invariant |
|---|---|
| `employment` | `last_working_day IS NOT NULL` **iff** `status = 'TERMINATED'` |
| `leave_ledger` | `amount <> 0` — a zero entry has no ledger meaning |
| `shift_roster` | `is_week_off_override` and `is_holiday_working_override` are mutually exclusive |
| `policy_assignment.policy_kind` | Widened by explicit migration per policy kind, never left open |
| `leave_ledger.entry_type` | Fixed vocabulary: `ACCRUAL` · `APPLICATION` · `ADJUSTMENT` · `ENCASHMENT` · `CARRY_FORWARD` · `COMP_OFF_CREDIT` |
| `employment.status` | Exactly two stored values (`ACTIVE`, `TERMINATED`) — derived states like "on notice" are computed, never stored |

### 2.3 Partial unique indexes for natural keys

| Index | Purpose |
|---|---|
| `punch (company_id, idempotency_key)` | Insert-time replay protection |
| `leave_day_projection (company_id, employee_id, attendance_date, leave_application_id)` | Idempotent resync |
| `attendance_day (company_id, employee_id, attendance_date)` | One row per employee-date |
| `overtime_record (attendance_day_id)` UNIQUE | One OT record per day |
| `leave_combination_rule` over `LEAST/GREATEST` of the pair | At most one rule per unordered pair |
| `leave_type` where `is_comp_off` | At most one active comp-off type per company |
| `leave_year_setting (company_id)` | Singleton per company |
| `shift_roster (company_id, employee_id, roster_date)` | One roster row per employee-date |

### 2.4 Append-only design

Seven tables have **no update path in the codebase** and no `updated_at` column, which makes the
immutability intent visible in the schema itself:

`punch` · `leave_ledger` · `audit_log` · `attendance_regularization_action` · `overtime_action` ·
`attendance_period_action` · `leave_application_action`

Corrections are always new rows: a wrong punch becomes a `source='REGULARIZATION'` punch; a wrong ledger
entry becomes an offsetting `ADJUSTMENT`. This matches ADR-0004 and ADR-0005 and is exactly the posture
Payroll needs.

### 2.5 Cascade and deletion safety

- **No `ON DELETE CASCADE` on any HR-fact table.** Verified across all migrations.
- Every `user.id` FK is `ON DELETE SET NULL` — deleting a user never cascades away an HR fact, only the
  attribution.
- Deletion is soft (`deleted_at`) throughout the config entities.
- Historical rows carry `RESTRICT` on the parent, preventing orphaning.

### 2.6 Timestamps and timezone

Every timestamp column in the audited modules is `DateTime(timezone=True)` → `TIMESTAMPTZ`.
**No naive timestamp column was found.** Business dates (`attendance_date`, `effective_date`,
`joining_date`, `roster_date`, `calendar_date`) are `DATE`, which is correct — a business date is not an
instant.

---

## 3. Data integrity findings

### DAT-001 🟠 CRITICAL — leave accrual idempotency has no database constraint

**Evidence** — `apps/api/src/hrms/modules/leave/service.py:1400-1435`:

```python
already_written = await self._ledger_repo.exists_for_cycle(
    self._session, company_id=..., employee_id=..., leave_type_id=...,
    entry_type="ACCRUAL", effective_date=period_end,
)
if already_written:
    continue
...
await self._ledger_repo.insert(self._session, data={...})
```

This is a textbook check-then-insert. There is **no unique index** on
`(company_id, employee_id, leave_type_id, entry_type, effective_date)`.

**Failure scenario.** Two `leave.accrue_company` tasks for the same company execute concurrently — which
is not hypothetical: **OPS-006** notes that Celery Beat has no leader election, so two beat replicas
double-fire `run_monthly_accrual` by design (`core/celery_app.py:29-33`). Both observe
`already_written = False`, both insert. Every employee is credited twice. Because the balance is
`SUM(amount)`, the error is silent and permanent — and it can be spent.

The same pattern applies to `CARRY_FORWARD` in `run_year_end_for_company` (`:1510-1537`).

**Fix.** Add a partial unique index for `entry_type IN ('ACCRUAL', 'CARRY_FORWARD')` and catch
`IntegrityError` as "already written". The check-then-insert can stay as the fast path.

---

### PAY-010 🟠 CRITICAL — the leave balance has no concurrency control at all

**Evidence.** `submit` verifies sufficiency (`leave/service.py:2002-2024`):

```python
if current_balance < total_days:
    raise LeaveApplicationInsufficientBalanceError()
```

`_apply_approval` then debits **unconditionally** (`leave/service.py:2465-2480`) — no re-check, no
`SELECT … FOR UPDATE`, no constraint, and no reference to `allow_negative_balance`.

**Failure scenario.** An employee with 5 days of balance submits two 5-day applications on Monday. Both
pass the submit check, because `reserve_balance_on_submission` defaults to `False`
(`leave/models.py:152`). A manager approves both on Tuesday. Balance: −5. Payroll pays 10 days of leave
that was never accrued.

This does not even require concurrency — sequential approvals of two separately-submitted applications
produce it. Concurrency simply makes it easier.

**Compounding.** `allow_negative_balance` — the policy field that exists precisely to govern this — has
**zero references** anywhere outside `leave/models.py:145`.

**Fix.** Re-check inside `_apply_approval` under a row lock on the employee's ledger rows for that leave
type, and honour `allow_negative_balance`.

---

### PAY-008 🟠 CRITICAL — attendance results are not exactly reproducible

Two independent causes.

**1. Sibling-day dependency, unpersisted.**

Four values are computed from *other days'* state immediately before the pure engine runs, and none is
written into `computation_snapshot`:

| Input | Where computed | What it affects |
|---|---|---|
| `prior_late_days_in_window` | `service.py:2959-2967` | Can force `HALF_DAY` via the cumulative-late rule |
| `prior_excess_break_days_in_window` | `service.py:2972-2981` | Same, via the cumulative-excess-break rule |
| `remaining_weekly_minutes` | `service.py:3009-3021` | Caps `ot_minutes_detected` |
| `remaining_monthly_minutes` | `service.py:3022-3038` | Same |

Recomputing an unchanged day after a sibling day's OT record changes state therefore produces a
different answer, with no record of what the original inputs were.

This is documented as an accepted trade-off — `calculation.py:29-34` says so explicitly, and WD-29
decision 3 records the decision. **It was never assessed against a consumer that must defend a payslip.**

**2. No engine-version stamp.**

`calculation_version` (`attendance/models.py:589`) is incremented on every recompute
(`service.py:2569`) — it is a *how many times has this row been recomputed* counter, not an identifier
of the algorithm. Once ATT-001…ATT-005 are implemented, rows produced by the old and new engines become
indistinguishable.

**Fix.** Persist the four sibling-day inputs into `computation_snapshot`; add an `ENGINE_VERSION`
module constant and a corresponding `attendance_day.engine_version` column.

---

### PAY-007 🟠 CRITICAL — the lock-time paid/LOP rewrite is implicit, unaudited, and untested

`_apply_incomplete_lock_resolution` (`service.py:5016-5051`) is the last thing that touches
`paid_day_fraction` and `lop_fraction` before a period locks. It is the most payroll-consequential
mutation in the system, and it has three problems.

**(a) No audit row.** `AuditService.record` is never called
(`repository.py:set_lock_time_incomplete_resolution:1199-1220`).

**(b) Status and fractions disagree.** `attendance_status` deliberately stays `INCOMPLETE`
(`repository.py:1212-1215`) while the fractions now say `0.00 / 1.00`. A Payroll rule keyed on status
and one keyed on fraction give different answers for the same day.

**(c) Correctness depends on implicit ORM behaviour.** The sequence in `finalize` is:

```
5079  result, day_rows = await self._run_validation(...)   # loads ORM AttendanceDay objects
...
5099  await self._apply_incomplete_lock_resolution(company_id, day_rows)   # Core UPDATE
5101  aggregates = self._aggregate_day_rows(day_rows)      # reads the SAME in-memory objects
```

`set_lock_time_incomplete_resolution` issues a Core `update(AttendanceDay)` through `session.execute`.
Whether the in-memory `day_rows` reflect the new fractions when `_aggregate_day_rows` reads them four
lines later depends on SQLAlchemy 2.0's `synchronize_session="auto"` strategy resolving to `evaluate` for
this particular WHERE clause. It probably does. **But no test asserts the frozen summary's `lop_days`
after an INCOMPLETE resolution**, so nothing would catch it if it stopped.

Correctness of the number Payroll pays should not rest on an ORM default.

**Fix.** Compute the resolved fractions in Python and pass them to the aggregator explicitly (or re-read
the rows after the update); write an audit row; add the missing test.

---

### PAY-004 / PAY-005 🔴/🟠 — paid and LOP fractions are wrong outside the employment window

`calculation.py:984-989`:

```python
paid_fraction = "1.00" if status in ("NOT_JOINED", "NOT_EXPECTED") else "0.00"
lop_fraction  = ("0.00" if status in ("NOT_JOINED", "NOT_EXPECTED")
                 else ("1.00" if status in ("ABSENT", "EXITED") else "0.00"))
```

| Status | `paid_day_fraction` | `lop_fraction` | Correct? |
|---|---|---|---|
| `PRESENT` | 1.00 | 0.00 | ✅ |
| `HALF_DAY` | 0.50 | 0.50 | ✅ |
| `ABSENT` | 0.00 | 1.00 | ✅ |
| `NOT_EXPECTED` | 1.00 | 0.00 | 🟡 correct for monthly salary; a business question for daily wage (BUS-001) |
| **`NOT_JOINED`** | **1.00** | 0.00 | 🔴 **A day before joining is paid in full** |
| **`EXITED`** | 0.00 | **1.00** | 🟠 **A day after exit is a full loss-of-pay deduction** |
| `INCOMPLETE` | 0.00 | 0.00 | 🟠 Neither, until lock — `paid + lop ≠ 1` |
| `CONFIG_ERROR` | 0.00 | 0.00 | ✅ Blocks finalization by design |
| `LEAVE` | from the leave overlay | from the leave overlay | ✅ |
| `ON_DUTY` | 1.00 | 0.00 | ✅ |

---

### DAT-002 🟡 HIGH — no pagination anywhere

`PaginationMeta` is defined (`shared/pagination.py:14-20`) and `ListEnvelope` accepts it — but
`pagination=` is **never passed** at any of the ~45 `ListEnvelope(...)` construction sites, and no list
repository issues a `LIMIT`:

```
$ grep -rn "pagination=" src/          → (no results)
$ grep -rn "\.limit(" src/             → 3 results, all .limit(1) single-row lookups
```

`GET /v1/attendance/days` with a month range for a 1 000-employee company returns ~31 000 rows, each
triggering an additional break query (DAT-003a). This is both a performance problem and an
unauthenticated-resource-exhaustion surface for any authenticated user.

---

### DAT-003 🟡 HIGH — N+1 query patterns

| ID | Location | Pattern |
|---|---|---|
| DAT-003a | `attendance/service.py:2477` | One `list_for_day` break query per attendance-day row |
| DAT-003b | `calendar_resolution.py:301-314` | Up to 8 queries per policy kind, per employee-day; `_build_calculation_input` resolves 5 policy kinds → up to ~40 precedence queries per employee-day |
| DAT-003c | `leave/service.py:1365-1409` | Employees × leave types × (assignment walk + version lookup + exists check). 1 000 employees × 5 types ≈ 50 000+ queries in a single Celery task |
| DAT-003d | `identity/service.py:63-68` | One company query per membership, on every login and refresh |

Measured cost of a single `AttendanceDayService.calculate()`: **~50–70 queries**. See Part 27 of the main
audit for the full breakdown and scale projection.

---

### Minor findings

| ID | Finding | Severity | Evidence |
|---|---|---|---|
| DAT-004 | `_reverse_approval` writes `effective_date=date.today()` — server-local, not company timezone | 🔵 | `leave/service.py:2597` |
| DAT-005 | Backdating check uses `date.today()`; `max_requests_per_month` counts by UTC calendar month of `submitted_at` rather than by leave dates | 🔵 | `leave/service.py:1979`, `:1990` |
| DAT-006 | Same-leave-type overlapping applications are not blocked at submit — `list_active_overlapping_other_types` checks *other* types only; the collision surfaces late, at approve, as `LeaveProjectionOverlapError` | 🔵 | `leave/service.py:1911-1927` |
| DAT-007 | `EmployeeStatutory.vpf_percentage: Mapped[float \| None]` over a `Numeric(9,4)` column — the annotation is wrong (the runtime value is `Decimal`). Nothing computes with it yet. | 🔵 | `employee/models.py:228` |
| DAT-009 | `paid_day_fraction`/`lop_fraction` are `Numeric(3,2)` — adequate for 0.00–1.00, no headroom for quarter-day or >1 constructs | 🔵 | `attendance/models.py:580-581` |
| DAT-010 | No FK from `leave_day_projection.leave_application_id` to `leave_application.id` — deliberate (the table predates Leave), now an unenforced cross-module reference | 🔵 | `attendance/models.py:1012-1014` |
| DAT-011 | ~~`attendance_period.legal_entity_id` reserved, always NULL — period grain is company-wide (PD-LOCK-1 open)~~ **Fixed 2026-09-23** — per-legal-entity periods (decision 14, WD-34, migration `20261004104000`) | 🔵 | `attendance/models.py:872` |
| DAT-012 | No partitioning on `punch` or `attendance_day` — documented deferral (WD-26), correct at current volume | 🟢 | — |
| SEC-007 | `company` has `FORCE ROW LEVEL SECURITY` but RLS is never `ENABLE`d and no policy exists, so `FORCE` is a no-op | 🔵 | `scripts/sql/002_row_level_security.sql:10-11` |

---

## 4. Transaction integrity

**Boundary.** One HTTP request = one `AsyncSession` = one transaction. Commit on success, rollback on any
exception (`core/db/session.py:63-68` for `session_scope`, `:78-83` for the FastAPI dependency). Celery
tasks use the same `session_scope`. Applied consistently — **no service opens its own transaction or
commits mid-request.**

### The critical multi-step path, traced end to end

> Leave approval → ledger debit → attendance projection. If the projection fails, what happens?

```
LeaveApplicationService.approve
  └─ _approve_internal                              (leave/service.py:2296)
       ├─ repo.update(status='APPROVED', expected_version=…)     ← optimistic lock
       ├─ _record_action("APPROVED")
       ├─ audit.record("LEAVE_APPLICATION_APPROVED")
       └─ _apply_approval                            (:2401)
            ├─ for each day: LeaveProjectionService.sync(...)     ← may raise
            │     ├─ _ensure_employee_visible
            │     ├─ _ensure_date_open  ──────────► AttendancePeriodClosedError
            │     ├─ overlap check      ──────────► LeaveProjectionOverlapError
            │     ├─ insert/update leave_day_projection
            │     ├─ audit.record
            │     └─ AttendanceDayService.calculate(...)   ← full recompute
            └─ ledger.insert(APPLICATION, -total_days)     ← debit LAST
```

**Verified answer: the entire transaction rolls back, including the `status='APPROVED'` write.** The
exception propagates through `get_session`'s `except` clause, which calls `session.rollback()`. There is
no partially-approved, partially-synced, partially-debited state.

The ordering is deliberate — projections first, ledger debit last — and documented at
`leave/service.py:2410-2415`. The same posture appears in
`AttendanceRegularizationRequestService._apply_correction` and `AttendancePeriodService.finalize`.

🟢 **This is correct and well designed.**

**The residual risk is in Celery tasks**, where a failure mid-fan-out leaves some companies processed and
others not, with no retry and no alert (OPS-006, OPS-010, OPS-003).

---

## 5. Concurrency control

| Mechanism | Where used | Assessment |
|---|---|---|
| Optimistic locking (`expected_version`) | Every workflow mutation: regularization, overtime, leave application, period, roster, leave projection | 🟢 Consistent |
| Version-guarded UPDATE | `UPDATE … WHERE id = :id AND version = :expected RETURNING *`; `None` → typed stale-version error | 🟢 Correct pattern |
| Unique constraints as a race backstop | `punch (company_id, idempotency_key)` → `IntegrityError` → typed error | 🟢 |
| Lock-guarded UPDATE | `replace_derived_fields` filters `WHERE is_locked = false` — a lock applied mid-flight makes the write a no-op, which the caller detects | 🟢 Correct |
| Finalization ordering | The version-guarded `status='CLOSED'` write happens **before** any day row is touched, so the losing concurrent finalize aborts cheaply | 🟢 Well thought through |
| **Pessimistic locking** | **Never used.** No `SELECT … FOR UPDATE` anywhere. | 🟠 |
| **Leave balance** | **No control at all** | 🟠 PAY-010 |
| **Accrual** | Check-then-insert, no constraint | 🟠 DAT-001 |
| Celery Beat | No leader election, no distributed lock | 🟠 OPS-006 |

**Test coverage: zero.** No test in the suite executes two operations in parallel. The optimistic-locking
paths are tested by passing a deliberately stale `expected_version` — which proves the guard exists, not
that it wins a real race.

---

## 6. Idempotency

| Operation | Idempotent? | Mechanism |
|---|---|---|
| Attendance calculation | ⚠️ **Usually, not always** | Full replacement of derived fields, but sibling-day inputs can differ between runs (PAY-008) |
| Leave monthly accrual | ✅ sequential / ❌ concurrent | `exists_for_cycle`, no DB constraint (DAT-001) |
| Leave year-end sweep | ✅ / ❌ | Same |
| Leave balance | ✅ | Append-only; balance is always `SUM()` |
| Leave approval | ✅ | Version-guarded |
| OT record sync | ✅ | `PENDING` replaced on recompute; terminal frozen (WD-29 d2) |
| Regularization apply | ✅ | Version-guarded |
| Period finalization | ✅ | Version-guarded; `replace_for_period` is full delete/recreate |
| Period reopen | ✅ | Version-guarded |
| Comp-off credit | ✅ | Idempotent per `overtime_record_id` |
| Comp-off expiry | ✅ | Date-gated |
| Punch ingestion | ✅ with a key | Partial unique index; replays the original row |
| Leave projection sync | ✅ | Natural-key upsert, bumps `source_version` |

---

## 7. Historical integrity

> **If Payroll processes August today, can the same August attendance change tomorrow?**

**In a CLOSED period: no.** Verified across every mutation path — punch, roster, regularization, OT
decision, leave sync, leave cancel, and `calculate()` itself all refuse.

**In an OPEN period: yes**, in four ways:

| Vector | Mechanism | Control |
|---|---|---|
| Back-dated policy version publish | New version with an earlier `effective_from`; resolution is by date, so historical days re-resolve to it | Permission-gated (`*.POLICY_MANAGE`), audited (`published_by`, `publish_reason`) |
| **Roster row edit** | `ShiftRoster` is a **mutable master**, not an insert-new history (`attendance/models.py:388-394`). The previous value survives only in `audit_log`. | Permission-gated, audited |
| **Calendar / holiday edit** | `holiday` and `work_calendar` are mutable masters with no versioning | Permission-gated, audited |
| Recompute of an unchanged day | Sibling-day dependency (PAY-008) | None |

### Mechanisms present vs missing

| Mechanism | Present? |
|---|---|
| Policy versions | ✅ Identity + immutable published version, GiST no-overlap |
| Effective dates | ✅ Everywhere |
| Version-FK snapshots | ✅ Six FKs on `attendance_day` |
| Immutable finalized records | ✅ `is_locked` + `attendance_period_summary` |
| Calculation snapshot | ⚠️ Partial — punches, pairing, presence, terminal reason |
| **Roster/calendar fact snapshot** | ❌ Not captured |
| **Sibling-day input snapshot** | ❌ Not captured |
| **Engine-version stamp** | ❌ Absent |
| **Frozen leave balance** | ❌ Leave has no period concept |

**Conclusion.** Historical integrity is **strong once a period is CLOSED and weak while it is OPEN**. The
lock is the real guarantee, and it works. → **Payroll must read only CLOSED periods, and that should be
enforced in code rather than documented as a convention.**

---

## 8. Numeric safety

| Check | Finding | Status |
|---|---|---|
| Float in money | **None.** `annual_ctc_minor` and `vpf_amount` are `BigInteger` minor units (ADR-0006) | 🟢 |
| Float in durations | **None.** Every minute field is `Integer` | 🟢 |
| Float in fractions | **None.** `Numeric` columns, `Decimal` arithmetic (`calculation.py:893-935`) | 🟢 |
| Precision / scale | `Numeric(6,2)` ledger and summary days; `Numeric(5,4)` multipliers; `Numeric(3,2)` fractions | 🟢 |
| Accrual rounding | Explicit `Decimal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)` | 🟢 `leave/service.py:1319` |
| Leave overlay rounding | Explicit `.quantize(Decimal("0.01"))` | 🟢 `calculation.py:917-933` |
| **OT minute rounding** | `round_minutes` NEAREST uses Python's built-in `round()` → **banker's rounding**. `round(7.5) == 8` but `round(2.5) == 2`. | 🟡 ATT-011 |
| Currency | Explicit 3-letter code alongside every amount | 🟢 |
| Negative values | Ledger amounts signed with `CHECK amount <> 0`; negative balances structurally possible (PAY-010) | 🟠 |
| Multipliers | `Numeric(5,4)`, snapshotted, **never applied as money** (ADR-0006, WD-03 §12.1) | 🟢 Correct boundary |
| **Minutes → hours → money** | **Does not exist anywhere in Attendance or Leave** | 🟢 Exactly right |
| Typing inconsistency | `vpf_percentage` annotated `float` over `Numeric(9,4)` | 🔵 DAT-007 |

**Verdict: numeric safety is one of the strongest areas of this codebase.** The discipline of keeping
Attendance in integer minutes and `Decimal` fractions, and refusing to apply the OT multiplier, is the
right foundation for Payroll. The single real defect is banker's rounding in OT minute rounding.

---

## 9. Findings summary

| ID | Finding | Severity | Category |
|---|---|---|---|
| PAY-010 | Leave balance never re-checked at approval; no lock, no constraint | 🟠 CRITICAL | Concurrency |
| DAT-001 | Accrual idempotency has no unique constraint | 🟠 CRITICAL | Concurrency |
| PAY-008 | Attendance not exactly reproducible (sibling-day inputs + no engine version) | 🟠 CRITICAL | Historical integrity |
| PAY-007 | Lock-time paid/LOP rewrite is implicit, unaudited, untested | 🟠 CRITICAL | Correctness |
| PAY-004 | `NOT_JOINED` → `paid_day_fraction = 1.00` | 🔴 BLOCKER | Correctness |
| PAY-005 | `EXITED` → `lop_fraction = 1.00` | 🟠 CRITICAL | Correctness |
| PAY-006 | `INCOMPLETE` → paid 0.00 / LOP 0.00 until lock | 🟠 CRITICAL | Correctness |
| DAT-002 | No pagination on ~45 list endpoints | 🟡 HIGH | Performance |
| DAT-003 | Four N+1 patterns; ~50–70 queries per employee-day | 🟡 HIGH | Performance |
| ATT-011 | Banker's rounding in OT minute rounding | 🔵 MEDIUM | Numeric |
| DAT-004/005 | `date.today()` used instead of company-timezone date | 🔵 MEDIUM | Timezone |
| DAT-006 | Same-type overlapping leave not blocked at submit | 🔵 MEDIUM | Validation |
| DAT-007 | `vpf_percentage` typed `float` over `Numeric` | 🔵 LOW | Typing |
| DAT-009 | `Numeric(3,2)` leaves no headroom for quarter-day fractions | 🔵 LOW | Schema |
| DAT-010 | No FK on `leave_day_projection.leave_application_id` | 🔵 MEDIUM | Referential |
| SEC-007 | `company` has `FORCE` RLS without `ENABLE` or a policy | 🔵 MEDIUM | Isolation |
| DAT-012 | No partitioning (documented deferral) | 🟢 LOW | Scalability |

---

## 10. What is genuinely strong — do not rebuild

1. **GiST exclusion constraints for effective dating.** Overlap prevention at the database layer, not in
   application code. `employment_no_overlap` makes "at most one active employment" a hard guarantee.
2. **Append-only facts.** Seven tables with no update path and no `updated_at` — the immutability intent
   is visible in the schema itself, not just in a docstring.
3. **The correction posture.** A wrong punch becomes a new punch. A wrong ledger entry becomes an
   offsetting entry. A wrong attendance status becomes a regularization that writes punches and triggers
   a recompute. **Nothing is ever edited in place.** This is exactly what Payroll needs underneath it.
4. **Version-FK snapshots.** Every `AttendanceDay` records the six versions actually used, and published
   versions are immutable — so "which rules produced this result" is answerable by join.
5. **Transaction discipline.** One request, one transaction, verified end-to-end on the most complex
   cross-module path in the system.
6. **Money and duration typing.** No float anywhere. Integer minor units. Integer minutes. No
   minutes-to-money conversion in Attendance at all.
7. **Fail-closed defaults.** Missing configuration produces `CONFIG_ERROR`, which blocks period
   finalization, which blocks Payroll — rather than silently defaulting to `WORKING` and paying someone
   incorrectly.

---

*No application code, schema, migration, test, or configuration was modified during this audit.*
