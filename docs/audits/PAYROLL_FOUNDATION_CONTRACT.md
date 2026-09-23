# Payroll Foundation Contract

| Field | Value |
|---|---|
| Audit date | 2026-09-10 |
| Commit | `e33fcdb` |
| Status | **Draft — not yet satisfiable.** Four guarantee clauses are false today; the payload gaps are larger (see Part D). |
| Parent document | [`PRE_PAYROLL_PRODUCTION_READINESS_AUDIT.md`](./PRE_PAYROLL_PRODUCTION_READINESS_AUDIT.md) |

This document defines exactly what the Payroll module is permitted to assume from Attendance, Leave,
Employee, and Organisation — and what it must never assume.

**Every clause below is either marked ✅ VERIFIED (with evidence gathered during this audit) or
❌ NOT YET TRUE (with the blocker that must be closed first).** Nothing is asserted on the strength of
documentation alone.

---

## Part A — Payroll MAY assume

### A1. Locking and immutability

| # | Assumption | Verified? | Evidence | Risk if false |
|---|---|---|---|---|
| A1.1 | A `CLOSED` `AttendancePeriod`'s `AttendanceDay` rows cannot be modified | ✅ | `bulk_lock` sets `is_locked=true` for the whole range (`attendance/repository.py:1222-1246`); `replace_derived_fields` filters `WHERE is_locked = false` (`:1104`); `calculate()` raises `AttendanceDayLockedError` (`service.py:2511`) | Already-paid figures change retroactively |
| A1.2 | No punch can be recorded into a closed period | ✅ | `PunchService.record_punch` → `_ensure_date_open` (`service.py:2361`) | Attendance changes after payroll |
| A1.3 | No roster row can be written into a closed period | ✅ | `ShiftRosterService` mutations → `_ensure_date_open` | Schedule changes after payroll |
| A1.4 | No regularization can be submitted or applied into a closed period | ✅ | `RegularizationRequestService.submit` → `_ensure_date_open` (`service.py:3491` and `:3583`) — **unconditional**, independent of `blocked_when_locked` | Corrections after payroll |
| A1.5 | No overtime decision can be made for a closed period | ✅ | `OvertimeRecordService.approve`/`reject` → `_ensure_date_open` | OT changes after payroll |
| A1.6 | **No leave approval or cancellation can affect a closed period** | ✅ | `LeaveProjectionService.sync` (`service.py:5254`) and `.cancel` (`:5384`) both call `_ensure_date_open`. The whole leave-approval transaction rolls back if any day is locked (`leave/service.py:2410-2415`). | Leave changes after payroll |
| A1.7 | Reopening a closed period requires a distinct, stronger permission, a mandatory reason, and is fully audited | ✅ | `ATTENDANCE.UNLOCK` (`attendance/router.py:1436`); `reopen` writes `reopen_reason`, an `attendance_period_action` row, and an `audit_log` row (`service.py:5176-5219`) | Silent unlock |
| A1.8 | Re-finalizing after a reopen regenerates a **completely fresh** summary, never a stale leftover | ✅ | `AttendancePeriodSummaryRepository.replace_for_period` is a full delete/recreate | Mixed-vintage figures |

### A2. Effective dating and version snapshots

| # | Assumption | Verified? | Evidence | Risk if false |
|---|---|---|---|---|
| A2.1 | Published policy versions are immutable | ✅ | Publish freezes the row; every service refuses to edit a `PUBLISHED` version; GiST exclusion prevents overlapping published ranges | Retroactive rule change |
| A2.2 | Every `AttendanceDay` records the exact versions used | ✅ | Six FKs: `shift_id`, `shift_version_id`, `work_calendar_id`, `attendance_policy_version_id`, `overtime_policy_version_id`, `regularization_policy_version_id` (`attendance/models.py:504-521`) | Unexplainable results |
| A2.3 | Employment, assignment, compensation, and shift versions are resolvable as-of any date | ✅ | `get_employment_as_of`, `get_assignment_as_of`, `resolve_shift_version_as_of`, `find_effective_as_of` | Wrong policy applied to a historical month |
| A2.4 | Employment spells never overlap; at most one is `ACTIVE` | ✅ | GiST `employment_no_overlap` (migration `20260814090000`) — a **database** guarantee, not an application check | Double-counted employment |
| A2.5 | `last_working_day` is set if and only if `status='TERMINATED'` | ✅ | DB CHECK constraint | Ambiguous exit |
| A2.6 | A leave application's review rules are those in force at submission | ✅ | `leave_application.leave_policy_version_id` snapshotted at submit (`leave/service.py:2079`) | In-flight rule change |
| A2.7 | A regularization request's review rules are those in force at submission | ✅ | `attendance_regularization_request.regularization_policy_version_id` + `approval_chain` snapshotted | Same |

### A3. Policy precedence determinism

| # | Assumption | Verified? | Evidence |
|---|---|---|---|
| A3.1 | Policy resolution follows one precedence chain, most-specific-wins, for every policy kind | ✅ | `EMPLOYEE > SHIFT > DESIGNATION > GRADE > DEPARTMENT > BRANCH > LEGAL_ENTITY > COMPANY` — implemented once in `calendar_resolution.py:288-315`, reused for all six policy kinds |
| A3.2 | Missing configuration **fails closed**, never defaults to a guess | ✅ | `config_incomplete=True` → `CONFIG_ERROR` status → blocks period finalization (WD-21) |
| A3.3 | Calendar classification precedence is fixed: exception > holiday union > weekly-off > working | ✅ | `classify_work_calendar_date:130-233` |
| A3.4 | Duplicate holidays across composed calendars resolve deterministically (first list wins) | ✅ | `:171-175` |
| A3.5 | Only `PUBLISHED` roster rows affect calculation; `DRAFT` is invisible | ✅ | `get_published_for_date` (`service.py:2758`) |
| A3.6 | Approved leave outranks the punch-derived outcome, except under `PRESENT_CANCEL_LEAVE_HINT` | ✅ | `_apply_leave_overlay:861-935` |
| A3.7 | The population gate (`NOT_JOINED`/`EXITED`) outranks everything | ✅ | `evaluate_day:767-769`, checked first |

### A4. Numeric and monetary safety

| # | Assumption | Verified? | Evidence |
|---|---|---|---|
| A4.1 | **No floating-point arithmetic touches any money or duration value** | ✅ | Every minute field is `Integer`; every fraction is `Numeric`/`Decimal`; `annual_ctc_minor` is `BigInteger` minor units (ADR-0006) |
| A4.2 | Attendance and Leave never compute money | ✅ | No rupee value, rate, or amount is produced anywhere in either module |
| A4.3 | The OT multiplier is a snapshotted **hint**, never applied | ✅ | `overtime_record.configured_multiplier` (`Numeric(5,4)`), captured at decision time; ADR-0006 and WD-03 §12.1 make this explicit |
| A4.4 | Leave accrual proration uses explicit `ROUND_HALF_UP` | ✅ | `_prorate_accrual` (`leave/service.py:1319`) |
| A4.5 | All durations reach Payroll as integer minutes | ✅ | No minutes→hours conversion exists in the audited code |

### A5. Ledger and audit

| # | Assumption | Verified? | Evidence |
|---|---|---|---|
| A5.1 | The leave ledger is append-only; balance is always `SUM(amount)` | ✅ | `LeaveLedgerEntry` has no `updated_at`, no `version`, no update path; ADR-0004 |
| A5.2 | Corrections are new offsetting entries, never edits | ✅ | `_reverse_approval` writes an `ADJUSTMENT` credit (`leave/service.py:2588`) |
| A5.3 | Punches are immutable; corrections are new punches | ✅ | `Punch` has no update path; regularization writes `source='REGULARIZATION'` rows (WD-11, WD-28 d1) |
| A5.4 | Every workflow transition is recoverable stage-by-stage | ✅ | Four append-only timelines: `attendance_regularization_action`, `overtime_action`, `attendance_period_action`, `leave_application_action` |
| A5.5 | Every mutation writes an `audit_log` row with actor, before, after, ip, user agent, and request id | ✅ | `AuditService.record` called at every mutation — **with one exception: A5.6** |
| A5.6 | The lock-time paid/LOP resolution is audited | ❌ **NO** | `set_lock_time_incomplete_resolution` (`repository.py:1216-1220`) writes no audit row — **PAY-007** |
| A5.7 | Every activated employee has a compensation record | ❌ **NO** | Onboarding activation never writes one — **PAY-014** |
| A5.8 | The timezone a day was computed in cannot change afterwards | ❌ **NO** | Guard hook is an empty function; branch has none — **PAY-013** |

### A6. Security and tenancy

| # | Assumption | Verified? | Evidence |
|---|---|---|---|
| A6.1 | Every tenant table carries `company_id` and is protected by RLS | ⚠️ **Designed, weakly verified** | 70/79 tables have `ENABLE`+`FORCE ROW LEVEL SECURITY` + a `tenant_isolation` policy. **But the test suite runs as the BYPASSRLS superuser (TEN-002)**, so the backstop is largely unexercised. |
| A6.2 | The application connects as a non-superuser role with no BYPASSRLS | ✅ | `hrms_app`: `NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS` (`infra/docker/postgres/init/002_app_role.sql:16-23`) |
| A6.3 | Migrations run as a separate role the app process never loads | ✅ | `MIGRATIONS_DATABASE_URL`; `Settings` deliberately has no field for it (`alembic/env.py:16-29`) |
| A6.4 | A client-supplied tenant id is never trusted | ✅ | `X-Company-Id` must equal the JWT claim, else 404 (`core/tenancy/dependencies.py:19-20`); the RLS GUC is re-set from the verified value (`:37`) |
| A6.5 | Server-side authorization checks the **target object**, not merely permission possession | ✅ | `_ensure_employee_visible` on every write's target id, across attendance and leave |
| A6.6 | Out-of-scope and nonexistent resources are indistinguishable in the response | ✅ | Both return an identical 404 (`attendance/service.py:1904-1906`) |
| A6.7 | Payroll may reuse the existing permission + `DataScope` model as-is | ✅ | `core/rbac` is module-agnostic; permissions are module-owned constants seeded from code |

### A7. Transactional integrity

| # | Assumption | Verified? | Evidence |
|---|---|---|---|
| A7.1 | One HTTP request is one database transaction | ✅ | `get_session` commits on success, rolls back on any exception (`core/db/session.py:78-83`) |
| A7.2 | A cross-module failure rolls the whole operation back | ✅ | Traced end-to-end: leave approval → projection sync → attendance recompute → ledger debit. A locked-day refusal rolls back the `status='APPROVED'` write too. |
| A7.3 | Period finalization is atomic and race-safe | ✅ | Fresh re-validation → version-guarded `CLOSED` write **before** any day is touched → summary + lock, all in one transaction (`service.py:5063-5151`) |
| A7.4 | Concurrent workflow decisions cannot both win | ✅ | `expected_version` optimistic lock on every mutation; the loser receives a typed stale-version error |

---

## Part B — Payroll must NOT assume

Each rule is supported by a specific finding.

### B1. Do not assume current configuration equals historical configuration

A back-dated policy version publish **can** change an *unlocked* historical day. It is permission-gated
(`*.POLICY_MANAGE`) and audited (`published_by`, `publish_reason`), but it is possible.
The lock is the only thing that stops it. → **Read only `CLOSED` periods.**

### B2. Do not assume current policy applies to historical records

Always resolve by date. The attendance engine already does this correctly. Payroll must do the same for
its own rate cards and statutory rates (ADR-0011).

### B3. Do not assume attendance can always be recalculated to the same answer

**PAY-008.** Recomputing an unchanged day can produce a different `ot_minutes_detected` or a different
status, because the weekly/monthly OT budget and the late/excess-break day counters are read live from
sibling days at compute time and are not preserved in `computation_snapshot`. There is also no
engine-version stamp. → **Never recompute a day to "verify" a payslip. Read the frozen figure.**

### B4. Do not assume approved leave can never change

It can — until the period closes. Approval, cancellation, and resync are all permitted on open dates and
trigger a synchronous attendance recompute. After close, all three are refused. → The **lock**, not the
approval, is the guarantee.

### B5. Do not assume OT classification implies a monetary amount

`configured_multiplier` is a snapshot for Payroll to interpret. Attendance deliberately never applies it
(ADR-0006). Payroll owns the entire rate-application decision, including whether a multiplier applies at
all.

### B6. Do not assume a database field existing means the policy is implemented

**This is the single most important rule in this document.**

Approximately fifteen configurable policy fields are stored, validated at publish, exposed through the
API and UI, snapshotted onto every `AttendanceDay` — and **never read by any calculation**:

| Field | Module | Finding |
|---|---|---|
| `punch_rounding`, `rounding_minutes` | attendance policy | ATT-001 |
| `auto_close_after_minutes`, `auto_close_uses_shift_end` | attendance policy | ATT-002 |
| `half_day_split`, `half_day_boundary_minutes` | attendance policy | ATT-003 |
| `excess_break_behaviour` | attendance policy | ATT-004 |
| `night_window_start`, `night_window_end` | overtime policy | ATT-005 |
| `early_out_uses_core_end` | attendance policy | ATT-006 |
| `split_shift_block_mandatory`, `split_shift_allow_hours_compensation` | attendance policy | ATT-006 |
| `wfh_requires_punch`, `wfh_uses_shift_hours` | attendance policy | ATT-006 |
| `requires_pre_approval` | overtime policy | ATT-006 |
| `auto_approve_within_minutes` | regularization policy | ATT-006 |
| `late_count_window`, `excess_break_count_window` | attendance policy | ATT-007 (hard-coded to calendar month) |
| `allow_negative_balance` | leave policy | PAY-011 |
| `off_fraction` | weekly-off rule | PAY-012 (computed, then discarded) |
| `ShiftBreak.is_mandatory`, `min_minutes` | shift version | ATT-008 |

**Payroll must not read any of these and infer that the corresponding rule was applied to the attendance
result.** Until each is implemented or removed, treat them as absent.

### B7. Do not assume frontend restrictions guarantee authorization

They do not. Backend enforcement is separate — and in this codebase it is correct and consistent. But it
is the only control. Payroll must implement its own server-side permission checks.

### B8. Do not assume a successful API response means the transaction completed correctly

It does here, because one request is one transaction. Payroll must preserve that property in its own
writes, and must not split a payroll run across multiple transactions without an explicit compensation
design.

### B9. Do not assume summary buckets reconcile

**PAY-003.** `present_days + absent_days + leave_days + half_days + holiday_days + weekly_off_days` does
not equal the period length. A worked holiday is counted twice. Five statuses are counted zero times.

### B10. Do not assume `present_days + half_days` yields payable days

**PAY-002.** There is no paid-days figure in the frozen summary at all. Do not attempt to derive one from
the buckets.

### B11. Do not assume a leave balance is non-negative

**PAY-010.** Nothing enforces it at approval time. The balance is checked at submission and never again.

### B12. Do not assume a leave balance read today equals the one at period close

Leave has no closable period. The ledger accepts entries with any `effective_date`, including one inside
an already-closed attendance period. → If Payroll needs a frozen balance, **Payroll must snapshot it.**

### B13. Do not assume an unlocked period is safe to read

**PAY-006** (INCOMPLETE days carry neither paid nor LOP until lock) and **PAY-008** (non-reproducibility)
both apply only to the window between calculation and finalization. That window is unsafe.
→ **Recommendation: enforce `status = 'CLOSED'` in code, not in documentation.**

### B14a. Do not assume every employee has a compensation record

**PAY-014.** `OnboardingActivationService.activate_case` writes Employee, Employment, Assignment, Bank
and Statutory — but never `employee_compensation`. The bulk-import path does. So the presence of a
salary record depends on *how the employee was hired*, and nothing anywhere flags its absence.
→ Payroll must treat a missing compensation row as an explicit, surfaced error, never as zero.

### B14b. Do not assume the timezone used to compute a day is stable

**PAY-013.** `company.timezone` and `branch.timezone` are freely mutable. The guard hook written for
exactly this case (`organisation/service.py:601-608`) is an empty function. Changing either re-derives
UTC day boundaries on the next recompute of any unlocked day. `attendance_day.timezone` records what was
used, but recompute re-resolves live rather than reading it.
→ Another reason Payroll must read only `CLOSED` periods (B13).

### B15. Do not assume background jobs ran

**OPS-003, OPS-006, OPS-010.** No Celery task has a retry policy, logs anything, or is monitored. A
tenant can silently miss an entire month of leave accrual with no signal. → Payroll should validate that
expected accrual entries exist before running, rather than trusting the schedule.

### B16. Do not assume the tests passing means the rules are correct

**TST-001.** CI provisions no database, so 783 integration tests do not run as a merge gate. Green CI
currently proves that the code lints, type-checks, respects import boundaries, and passes 362 unit
tests — nothing more.

---

## Part C — Conditions Payroll development should impose

These are recommendations for how Payroll should be built given the above.

| # | Condition | Rationale |
|---|---|---|
| C1 | Payroll reads **only** `attendance_period.status = 'CLOSED'`, enforced in code | B13, B1, B3 |
| C2 | Payroll reads the **frozen summary**, never live `attendance_day` rows, for computation | A1.1, B9, B10 |
| C3 | Payroll snapshots the leave balance it used, into its own immutable run record | B12 |
| C4 | Payroll declares `leave_day_projection` its single leave-day source and never reads `leave_application_day` | ARC-003 |
| C5 | Payroll records the `engine_version` of every attendance row it consumed | B3 (requires the PAY-008 fix) |
| C6 | Payroll follows ADR-0005 — a finalized run is immutable; corrections are new arrears runs | Matches the ledger and lock posture already established |
| C7 | Payroll uses integer minor units and `Decimal` throughout, never `float` | A4 |
| C8 | Payroll reuses `core/rbac` permissions and `DataScope` rather than inventing a parallel model | A6.7 |
| C9 | Payroll's own period grain matches whatever BUS-007 decides — do not hard-code company grain | `attendance_period.legal_entity_id` is reserved for exactly this |
| C10 | Payroll writes an `audit_log` row for every run, approval, and reversal | A5.5 |

---

## Part D — Contract status

| Section | Clauses | ✅ Verified | ❌ Not yet true |
|---|---|---|---|
| A1 Locking | 8 | 8 | 0 |
| A2 Effective dating | 7 | 7 | 0 |
| A3 Precedence | 7 | 7 | 0 |
| A4 Numeric safety | 5 | 5 | 0 |
| A5 Ledger & audit | 8 | 5 | 3 (A5.6, A5.7, A5.8) |
| A6 Security & tenancy | 7 | 6 | 1 conditional (A6.1) |
| A7 Transactions | 4 | 4 | 0 |
| **Total** | **46** | **42** | **4** |

**The contract is 42/46 satisfied on its guarantee side.** The foundation Payroll needs — immutability,
effective dating, deterministic precedence, numeric safety, transactional integrity — is genuinely in
place and should not be rebuilt.

**What is missing is not the contract but the payload:** the six 🔴 items in
[`PAYROLL_INPUT_READINESS_MATRIX.md`](./PAYROLL_INPUT_READINESS_MATRIX.md), all of them in the
paid-days / LOP / summary chain, plus the batch generation that makes a closed period achievable at all.

**This contract becomes signable once the thirteen P0 items in Part 40 of the main audit are closed.**

---

*No application code, schema, migration, test, or configuration was modified during this audit.*
