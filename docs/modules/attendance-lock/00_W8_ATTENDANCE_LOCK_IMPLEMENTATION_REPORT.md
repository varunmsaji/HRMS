# W8 — Attendance Lock, Period Closing & Finalization: Implementation Report

**Date:** 2026-08-20
**Companion documents:** `docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md` §4.2/§11.4/§13.4/
§22/§23/§32, decision log `docs/architecture/WORKFORCE_ATTENDANCE_DECISION_LOG.md` **WD-30** (new
entry added by this slice).

---

## 1. Status

**W8 is implemented, tested, and live-verified end to end**, against the scope actually named by
the task brief: attendance period lifecycle, finalization validation, locking, and payroll-facing
final-fact protection. Backend (models, migration, repository, service, router, permissions,
exceptions), frontend (list, detail, create/finalize/reopen dialogs, nav entry), and tests (21
new backend integration tests plus 14 new frontend tests, both fully passing) are all in place.

A full live pass was performed against a real running API server, real Postgres, and a real
headless-Chromium browser — not just the test suite — covering the complete
create → validate (BLOCKED) → resolve → finalize → lock → reject-mutations → reopen cycle. See
§20.

---

## 2. Pre-Implementation Audit

Before writing any code, the architecture document (full §1-33), the decision log (WD-01 through
WD-29), and the actual attendance module source (`models.py`, `service.py` — then 4,266 lines,
`repository.py`, `router.py`, `schemas.py`, `calculation.py`, `exceptions.py`, `permissions.py`,
`dependencies.py`) were read directly, plus the relevant seams in the `employee` and
`organisation` modules. Key findings that shaped the design:

- **`AttendanceDay.is_locked`/`locked_at`/`locked_by` already exist**, shipped in W4 with an
  explicit docstring naming this exact seam as W8's ("nothing in W4 can set `is_locked=true` —
  the `AttendanceLock` period-lock entity and its `/attendance-locks` API are W8"). Confirmed by
  direct read of `models.py` line 475 and `service.py`'s `AttendanceDayService.calculate()`,
  which already refuses a locked day (`AttendanceDayLockedError`) but had no writer.
- **`RegularizationPolicyVersion.blocked_when_locked`** (W3) already gates
  `RegularizationRequestService.submit()`'s day-level lock check — but only when an
  `AttendanceDay` row already exists, and only conditionally on that policy flag.
- **`AttendancePolicyVersion.incomplete_at_lock_behaviour`** (W3, default `TREAT_ABSENT`) is
  declared on `calculation.PolicyInputs` but **never read anywhere in the calculation engine** —
  confirmed by grep across `calculation.py`. Architecture §11.4 names this column's exact purpose
  ("lock-time default for still-INCOMPLETE") — a dead seam this slice is the first to consume.
- **No W1-W7 code path could ever set `is_locked=true`.** Three services had zero lock awareness
  at all: `PunchService.record_punch`, all four `ShiftRosterService` mutating methods (create,
  update, publish, delete), and `OvertimeRecordService.approve`/`reject` — the last of which
  writes `AttendanceDay.ot_minutes_approved`/`comp_off_minutes_earned` **directly**, entirely
  outside `AttendanceDayService.calculate()`, so the pre-existing `is_locked` check could never
  have protected it even once a lock mechanism existed.
- **`AttendanceLock` (architecture §4.2) and `AttendancePeriodSummary`** were both greenfield —
  no table, no migration, no API surface anywhere.
- **PD-LOCK-1** (lock grain: company/legal-entity/pay-cycle) was already an **explicitly open**
  architecture decision (§32) with a stated conditional default: legal-entity grain *only if*
  Payroll will be LE-scoped. Payroll does not exist in this codebase yet, so that condition is
  unevaluable — the other half of the same documented default (company grain) is what ships.
- **No `AttendanceAdjustment` entity exists** (confirmed via the W6 implementation report and a
  fresh grep — still absent). Architecture §13.4's own stated default for post-lock correction is
  "reject with a clear error; pending-arrears is an explicit HR action" — the reject half is what
  this slice implements; the arrears half needs an entity with no assigned owning slice and an
  unspecified rule set (see §21, PD-LOCK-2, OPEN).
- **`EmploymentService`/`EmploymentRepository`** had no bulk "list employment spans overlapping a
  date range, company-wide" method — needed for the `EMPLOYEES_WITHOUT_ATTENDANCE` finalization
  check. Adding it required a small, precedented, three-line repository method plus a thin service
  passthrough returning primitive tuples (never the `Employment` ORM row) — **Module Standard §2**
  ("cross-module callers use `.service` only, never `.repository`/`.models`") is directly quoted
  in `EmploymentService`'s own existing docstring and was followed exactly, not improvised.

No architectural contradiction was found. No W1-W7 code was redesigned. The one genuinely open
product question this slice could not honestly resolve from the architecture — whether
`AttendanceAdjustment`/an arrears path should exist — is recorded as **OPEN (PD-LOCK-2)** in
WD-30, not invented.

---

## 3. Existing W1-W7 Contracts Reused

| Contract | Reused exactly as-is |
|---|---|
| `AttendanceDay.is_locked`/`locked_at`/`locked_by` (W4) | The only columns this slice's `bulk_lock`/`bulk_unlock` ever write; every other service's *check* of this flag (`AttendanceDayService.calculate()`) is unchanged |
| `AttendancePolicyVersion.incomplete_at_lock_behaviour` (W3) | Consulted for the first time, exactly as architecture §11.4 describes, inside `finalize`'s own resolution step — no new policy field added |
| `RegularizationPolicyVersion.blocked_when_locked` (W3) | Unchanged; still the day-level check inside `RegularizationRequestService.submit`, now supplemented (not replaced) by the new period-level check |
| `AttendanceDayRepository.list_filtered` / `AttendanceRegularizationRequestRepository.list_filtered` / `OvertimeRecordRepository.list_filtered` / `ShiftRosterRepository.list_filtered` | Every finalization-validation query reuses these existing, already-shipped methods (`visible_employee_ids=None` = company-wide) — no duplicate query paths were written |
| `AttendancePolicyRepository.get_version`-family pattern | `get_versions_by_ids` added following the exact same shape |
| `EmployeeAssignmentService`/`EmployeeService` cross-module-import convention | `EmploymentService.list_spans_overlapping` added and consumed the same way `RegularizationRequestService`/`OvertimeRecordService` already import `EmployeeAssignmentService` |
| `AuditService.record` | Every lifecycle transition (open/finalize/reopen), same call shape as every other attendance mutation |
| `require_permission` / `rbac.resolve_data_scope` (core RBAC) | Static-gate pattern (`ATTENDANCE_POLICY_MANAGE`'s own posture) — a period has no `employee_id`, so no `DataScope` resolution is needed for any period route |
| `DataEnvelope`/`ListEnvelope`/`ErrorEnvelope`, `If-Match` conditional-update convention | Unchanged, identical shape to every other attendance endpoint |
| `hrms_app` RLS role, `company_id` + `FORCE ROW LEVEL SECURITY` + `tenant_isolation` policy | Applied to all three new tables, identical clause to every existing table |
| Append-only per-entity action-timeline pattern (`AttendanceRegularizationAction`/`OvertimeAction`, WD-28 decision 7) | `AttendancePeriodAction` follows the same shape |

**Nothing new was built that already existed.** No second lock-flag mechanism, no second
audit system, no new `DataScopeLevel`, no generic workflow engine, no new JSONB column.

---

## 4. Product Decisions Made

Recorded formally as decision log **WD-30**. Summary (full reasoning and rejected alternatives in
the decision log itself):

| # | Decision |
|---|---|
| 1 | Two persisted states only — `OPEN`/`CLOSED`. `CLOSED` *is* locked. No separate "open" action; create opens immediately. No durable `CLOSING` state (synchronous finalization has no code path that would ever observe one). |
| 2 | The period, not `AttendanceDay.is_locked`, is the authoritative lock source of truth. A new `_ensure_date_open()` helper is the period-level check every mutating service consults; the pre-existing `is_locked` check stays as a narrower, defence-in-depth guard for the already-computed-row case. |
| 3 | Lock grain: **company only** in V1 (PD-LOCK-1's own stated default, given Payroll doesn't exist to be LE-scoped). A reserved, unused `legal_entity_id` column ships for a future slice. |
| 4 | `incomplete_at_lock_behaviour` is resolved *at finalize*, not treated as a blanket blocker — `KEEP_INCOMPLETE` blocks; `TREAT_ABSENT`/`TREAT_PRESENT` auto-resolve `paid_day_fraction`/`lop_fraction`, never `attendance_status` itself. |
| 5 | Six typed, fail-closed finalization-blocking reason codes (§8). |
| 6 | `AttendancePeriodSummary` is a full delete/recreate snapshot, written exactly once per successful finalize; the `OPEN`-state view is a live, unpersisted per-request aggregation, never a second continuously-updated cache table. |
| 7 | `ATTENDANCE.LOCK` (create/validate/finalize) and `ATTENDANCE.UNLOCK` (reopen) — exactly architecture §23.2's two named codes, no third read code. |
| 8 | No `AttendanceAdjustment`/arrears path in this slice — the reject-by-default half of architecture §13.4 is implemented; the arrears half has no assigned owning slice and an unspecified rule set, so it is not invented. |

**Two decisions are formally recorded as still open**, not silently resolved:

- **PD-LOCK-1** (pre-existing, architecture §32): whether a future slice should switch lock grain
  to legal-entity once Payroll is LE-scoped.
- **PD-LOCK-2** (new): whether `AttendanceAdjustment`/an `APPROVED_PENDING_ARREARS` path should
  ever be built for controlled post-lock correction without a full period reopen.

---

## 5. Database Changes

One new migration, `20260824090000_attendance_period.py`, `down_revision` chained onto W7's
`20260823090000_overtime_record`. Verified `upgrade → downgrade → upgrade` against the real dev
Postgres 16 instance, and separately verified end-to-end from an **empty** database (a throwaway
`hrms_w8_fresh_check` database created on the same Postgres server specifically for this check,
migrated through the full W0→W8 chain, RLS/FORCE RLS confirmed on all three new tables, then
dropped — §19).

Three new tables, each with `company_id` + `ENABLE`/`FORCE ROW LEVEL SECURITY` + `tenant_isolation`
policy identical to every other tenant table in this codebase:

- **`attendance_period`** — the period lifecycle + lock entity. FKs to `company`, optional
  (reserved, unused) `legal_entity`, and three nullable `user` FKs (opened/closed/reopened by).
  `CHECK` constraints on `status` (`OPEN`/`CLOSED`), `last_validation_status`
  (`READY`/`BLOCKED`/`NULL`), and `period_end >= period_start`. A GiST exclusion constraint
  (`company_id WITH =, daterange(period_start, period_end, '[]') WITH &&`) makes "no two periods
  for the same company ever overlap" a database-level guarantee, not just an application check —
  and is what makes `AttendancePeriodRepository.get_covering()`'s lookup unambiguous.
- **`attendance_period_action`** — append-only per-period timeline (`OPENED`/`VALIDATED`/
  `VALIDATION_FAILED`/`CLOSED`/`REOPENED`), mirroring `AttendanceRegularizationAction`/
  `OvertimeAction`.
- **`attendance_period_summary`** — the payroll-facing per-employee roll-up, unique on
  `(attendance_period_id, employee_id)`.

**No W1-W7 migration was modified.**

---

## 6. Domain Model

```text
attendance_period
  id, company_id, legal_entity_id (reserved, unused)
  period_start, period_end (inclusive-inclusive), label
  status (OPEN|CLOSED)
  opened_by_user_id, opened_at
  last_validated_at, last_validation_status (READY|BLOCKED|NULL — informational cache only)
  closed_by_user_id, closed_at
  reopened_by_user_id, reopened_at, reopen_reason
  version (optimistic concurrency)

attendance_period_action   (append-only)
  id, company_id, attendance_period_id, action, actor_user_id, comment, created_at

attendance_period_summary   (frozen once written; full delete/recreate on each finalize)
  id, company_id, attendance_period_id, employee_id
  present_days, absent_days, leave_days, holiday_days, weekly_off_days, half_days, lop_days
  ot_minutes_normal, ot_minutes_weekly_off, ot_minutes_holiday, ot_minutes_night
  comp_off_minutes_earned, late_count, worked_minutes_total
  generated_at
```

`CLOSED` is the only locked state — there is no separate "closed but not yet locked" status,
matching how architecture's own `AttendanceLock` entity never describes one either (WD-30
decision 1).

---

## 7. Period Lifecycle

```text
(create) ──▶ OPEN ──finalize (fail-closed on any blocking reason)──▶ CLOSED
                ▲                                                       │
                └───────────────── reopen (ATTENDANCE.UNLOCK) ──────────┘
```

- **Who can open a period:** anyone holding `ATTENDANCE.LOCK` (COMPANY). Creating a period opens
  it immediately — there is no separate "open" action (WD-30 decision 1, mirrors WD-28's
  no-DRAFT-state precedent).
- **Who can close/finalize:** `ATTENDANCE.LOCK`, fail-closed unless a fresh validation is `READY`.
- **Incomplete attendance:** resolved per its own snapshotted policy's
  `incomplete_at_lock_behaviour` at finalize time (§8/§9), not an unconditional blocker.
- **Unresolved exceptions (pending regularization, pending OT approval, unpublished roster,
  config errors, missing calculated attendance):** all block closing, fail-closed, with typed
  reasons (§8).
- **Employees can still punch into an already-open current period** — `OPEN` places no
  restriction beyond the normal, pre-existing DataScope/permission checks. Only a `CLOSED` period
  refuses mutations.
- **Late-arriving punches / overnight shifts crossing the period boundary:** see §14 — this is the
  one area with a documented, deliberate approximation, not a silent gap.
- **Reopen (`ATTENDANCE.UNLOCK`):** architecturally sanctioned (§13.4 names `ATTENDANCE.UNLOCK`
  explicitly), a materially higher-risk action gated by its own permission, mandatory `reason`,
  unlocks every `AttendanceDay` in range. Does not itself recompute or restore anything — a day
  made mutable again only actually changes via a later, ordinary `calculate()`/regularization/
  adjustment call, and re-finalizing regenerates a fresh frozen summary (never a stale leftover).

---

## 8. Finalization Rules

`_run_validation()` always re-derives the verdict live — `finalize` never trusts a stale cached
`last_validation_status`. Fail-closed: any non-empty bucket blocks. Six typed reason codes:

| Code | Check | Lock-time resolution? |
|---|---|---|
| `EMPLOYEES_WITHOUT_ATTENDANCE` | An employment spell's day count vs. `AttendanceDay` row count in range | No — must be run before finalize |
| `CONFIG_ERROR` | `attendance_status='CONFIG_ERROR'` rows in range | No — no lock-time resolution mechanism exists for this in the architecture |
| `INCOMPLETE_ATTENDANCE` | `attendance_status='INCOMPLETE'` rows whose policy's `incomplete_at_lock_behaviour='KEEP_INCOMPLETE'` | Only the `KEEP_INCOMPLETE` subset blocks; `TREAT_ABSENT`/`TREAT_PRESENT` rows are auto-resolved by finalize itself (§9), not blockers |
| `PENDING_REGULARIZATION` | `AttendanceRegularizationRequest.status='SUBMITTED'` in range | No |
| `PENDING_OVERTIME_APPROVAL` | `OvertimeRecord.status='PENDING'` in range | No |
| `UNPUBLISHED_ROSTER` | `ShiftRoster.status='DRAFT'` in range | No |

Each blocking bucket carries `count` and up to 20 `sample` identifiers (`employee_id` or
`employee_id:date`) so a caller can navigate straight to the first few offenders.

`POST .../validate` is a standalone, non-raising diagnostic call — it persists
`last_validated_at`/`last_validation_status` and records a `VALIDATED`/`VALIDATION_FAILED`
action. `POST .../finalize`'s own BLOCKED path deliberately does **not** persist either of those
(§9) — it raises inside the same transaction that would have written them, so they would be
rolled back anyway; a caller wanting a persisted, audited BLOCKED record ahead of attempting
finalize calls `POST .../validate` first.

---

## 9. Lock Enforcement

Backend enforcement is authoritative everywhere; the frontend never re-implements a check, only
surfaces the result. A shared `_ensure_date_open(session, company_id, target_date)` helper
(service.py) is the single period-level guard every mutating service consults:

| Service / method | Check added |
|---|---|
| `PunchService.record_punch` | Blocks a punch whose UTC calendar date falls in a `CLOSED` period (documented approximation, §14) |
| `ShiftRosterService.create_roster_entry`/`update_roster_entry`/`publish_roster_entry`/`delete_roster_entry` | Blocks any roster write for a `CLOSED` roster date |
| `RegularizationRequestService.submit` | Blocks unconditionally, independent of the pre-existing `blocked_when_locked` policy flag (that flag only ever gated the day-level check, when a day row already existed) |
| `OvertimeRecordService.approve`/`reject` | The **only** guard for this path — it writes `AttendanceDay` facts directly, entirely outside `calculate()`, so no pre-existing check could ever have covered it |
| `AttendanceDayService.calculate()` | Period check added *first*, ahead of the pre-existing `is_locked` check, closing the create-path gap (a date with no `AttendanceDay` row yet) |

Two distinct, precise error codes, both `409`:

- **`ATTENDANCE_PERIOD_CLOSED`** — the new period-level refusal, raised by every service above.
- **`ATTENDANCE_DAY_LOCKED`** — unchanged, the pre-existing, narrower error `calculate()` raises
  specifically when an already-computed row's own `is_locked` flag is true.

No alternate endpoint bypasses the lock — every write path into `AttendanceDay`/`Punch`/
`ShiftRoster`/`AttendanceRegularizationRequest`/`OvertimeRecord` for a given date was audited and
gated.

---

## 10. Post-Lock Behaviour

Per Phase 7's own instruction ("if `AttendanceAdjustment` is required but not sufficiently
defined, document the decision and stop that portion"):

- **Late punches, delayed device punches, manager corrections, overtime approval, regularization
  approval, after lock:** all rejected with `ATTENDANCE_PERIOD_CLOSED` (§9). No exception path.
- **The only sanctioned route back to mutability is `ATTENDANCE.UNLOCK` reopening the whole
  period** — a deliberately coarse, auditable, high-friction action, not a per-record override.
- **`AttendanceAdjustment`/an arrears path was not built** (§4, WD-30 decision 8, **OPEN
  PD-LOCK-2**) — architecture names it as a distinct entity (WD-18) but assigns it no owning
  slice and no concrete rule set for how it would interact with a closed period; inventing one
  here would be exactly the "silently invent an unresolved business rule" this task explicitly
  forbids.
- **Overnight shifts crossing a period boundary:** see §14.

---

## 11. Security / DataScope

`ATTENDANCE.LOCK` and `ATTENDANCE.UNLOCK` are both **COMPANY-scoped only** — an `AttendancePeriod`
has no `employee_id`, so there is no narrower `DataScope` to resolve against it (unlike every
other attendance entity in this module). Both are gated with the same static
`Depends(require_permission(...))` pattern `ATTENDANCE_POLICY_MANAGE` already uses for config
screens.

No new `DataScopeLevel` was added — `SELF`/`REPORTEES`/`REPORTEE_TREE`/`COMPANY` only (none of
which apply to a period-level entity beyond the COMPANY-scoped codes themselves).

**Cross-tenant access** — a forged/cross-tenant `period_id` on any route resolves to `404`,
verified by test (`test_cross_tenant_period_returns_404`).

**`EmploymentService.list_spans_overlapping`** (the one new cross-module read this slice needed)
never leaks the `Employment` ORM row across the module boundary — it returns primitive
`(employee_id, joining_date, last_working_day)` tuples, and is company-wide by design (an internal
fact query for finalization validation, not an API-facing employee list, so no `DataScope` applies
to it either).

---

## 12. Permissions

Two new codes, both generically registered to `COMPANY_ADMIN` at registration exactly like every
other `ATTENDANCE_PERMISSIONS` entry (no per-code wiring needed):

| Code | Scope | Purpose |
|---|---|---|
| `ATTENDANCE.LOCK` | COMPANY | Create, validate, and finalize/close attendance periods |
| `ATTENDANCE.UNLOCK` | COMPANY | Reopen a closed/locked attendance period |

Reads (list/get/summary) reuse `ATTENDANCE.VIEW`/`ATTENDANCE.VIEW_ALL` — no third code, mirroring
WD-28 decision 6 / WD-29 decision 6.

A **pre-existing gap was found and fixed** while auditing this area: the live-registration
permission-grant assertion in `test_registration_flow.py::test_registration_success_full_row_graph`
had never been updated for W6's or W7's own permission codes (it was missing
`ATTENDANCE.REGULARIZATION_REQUEST`/`_ON_BEHALF`/`.REGULARIZATION_APPROVE`/`.OVERTIME_APPROVE`
entirely, independent of anything W8 added) — confirmed failing before this session's W8
permission codes were even added to the expected set. Fixed by extending the same
already-established comment trail with W6/W7/W8's own additions, matching exactly what
`register_company` already grants (§17).

---

## 13. API Endpoints

```text
POST   /attendance-periods                       create + open (ATTENDANCE.LOCK)
GET    /attendance-periods                        list (ATTENDANCE.VIEW/.VIEW_ALL)
GET    /attendance-periods/{id}                    detail incl. action timeline
GET    /attendance-periods/{id}/summary            live preview (OPEN) / frozen snapshot (CLOSED)
POST   /attendance-periods/{id}/validate           fail-closed READY/BLOCKED, persists cache + action
POST   /attendance-periods/{id}/finalize           validate + close + lock, If-Match
POST   /attendance-periods/{id}/reopen             ATTENDANCE.UNLOCK, mandatory reason, If-Match
```

Path (`/attendance-periods`) and verb shape follow the exact `DataEnvelope`/`ListEnvelope`/
`If-Match` conventions W1-W7 already established. `validate` is `POST`, not `GET`, since it also
records a persisted action/cache write (audit-visible, per Phase 10's "validation failure"
requirement) — a `GET` with a side effect would be inconsistent with every other read route in
this module.

---

## 14. Frontend Screens

`apps/web/src/app/app/attendance-periods/page.tsx` — list: label, range, status badge, last
validation, "New period" action (gated by `ATTENDANCE.LOCK`). Company-wide config/admin screen,
not employee-scoped — no My/Team toggle, mirroring the Policy list screens' single unfiltered
list rather than the Regularizations/Overtime dashboards' posture.

`apps/web/src/app/app/attendance-periods/[id]/page.tsx` — detail: period fields, a locked-state
banner ("Historical attendance in this range is immutable") when `CLOSED`, on-demand finalization
readiness (Validate button → typed blocking reasons), the per-employee summary table (labelled
"(live preview)" while `OPEN`, "(frozen)" while `CLOSED`), and the full action timeline. Finalize
and Reopen open dedicated confirmation dialogs; backend remains authoritative (a 409 from either
is handled and surfaced, never assumed away).

`apps/web/src/components/attendance-period/` — `create-period-dialog.tsx`,
`finalize-period-dialog.tsx` (surfaces `ATTENDANCE_FINALIZATION_BLOCKED`'s typed reasons inline,
no second round trip), `reopen-period-dialog.tsx` (mandatory reason field), and
`attendance-period-status-badge.tsx`.

**Nav:** `Attendance Periods` entry added to `nav-items.ts` (unfiltered static list, matching this
codebase's existing "items the role/build can't access yet are absent, not disabled" convention).

**No Payroll UI was built**, and the existing Attendance dashboard was not redesigned — both
explicitly out of scope.

---

## 15. Audit Events

`AuditService.record` is called once per state transition, `entity_type="attendance_period"`:
`ATTENDANCE_PERIOD_OPENED`, `ATTENDANCE_PERIOD_CLOSED`, `ATTENDANCE_PERIOD_REOPENED`.

**In addition** — not instead of — the append-only `AttendancePeriodAction` table
(`OPENED`/`VALIDATED`/`VALIDATION_FAILED`/`CLOSED`/`REOPENED`) gives the frontend timeline a
request-scoped read model, mirroring WD-28 decision 7's identical precedent for
`AttendanceRegularizationAction`.

`finalize`'s own BLOCKED path deliberately does not write a `VALIDATION_FAILED` action or the
validation cache (§8) — both would be rolled back with the rest of the failed transaction anyway,
so writing them would be dead code, not a missing audit trail; `POST .../validate` is the call
that persists a BLOCKED record when one is wanted ahead of a finalize attempt.

---

## 16. Concurrency

Every mutating endpoint requires `If-Match: <version>`, the repository's conditional
`UPDATE ... WHERE version = :expected_version` pattern (identical to every other attendance
mutation).

`finalize` wins the version-guarded `status='CLOSED'` write **before** touching any
`AttendanceDay`/`AttendancePeriodSummary` row — a losing concurrent finalize aborts cheaply,
before locking anything, and the whole request is one transaction, so any failure after the
version-guarded write rolls that write back too. Verified by test
(`test_simultaneous_finalize_only_one_wins`): two concurrent finalize calls against the same
`expected_version` — exactly one succeeds (`200`), the other fails (`409 STALE_RESOURCE`), and
the final persisted state (`CLOSED`, `version=2`) matches only the winner, never a mixed or
double-applied result. `test_stale_if_match_on_finalize_rejected` covers the simpler single-stale
case.

`AttendancePeriodRepository.record_validation` (the informational `last_validated_at`/
`last_validation_status` cache write) is deliberately **not** version-guarded and does not bump
`version` — it is a diagnostic side effect, not a lifecycle transition, and `finalize` never
trusts it regardless.

---

## 17. Backend Tests

`apps/api/tests/integration/modules/attendance/test_attendance_period.py`, **21 tests, all
passing** against a real Postgres 16 instance (real RLS, real `hrms_app` role, real HTTP through
the ASGI app). Some tests insert a `CLOSED` period directly via raw SQL to isolate one mutating
service's lock guard at a time (mirrors `test_attendance_day.py::test_locked_day_refuses_
recompute`'s identical raw-SQL-flip convention); the full real create→validate→finalize→verify→
reopen flow is covered separately, with no shortcut, by the end-to-end tests.

- **CRUD/security (5):** create opens immediately + lists + gets, overlapping period rejected
  (`ATTENDANCE_PERIOD_OVERLAP`), cross-tenant 404, unauthorized create rejected (403), reopen
  requires the separate `ATTENDANCE.UNLOCK` permission (403 with only `ATTENDANCE.LOCK`).
- **Finalization validation (8):** READY end-to-end with locked days + frozen summary, blocked on
  missing employee attendance, blocked on `CONFIG_ERROR`, blocked on `INCOMPLETE_ATTENDANCE` under
  a `KEEP_INCOMPLETE` policy, resolved (not blocked) under the default `TREAT_ABSENT` policy with
  the correct `paid_day_fraction`/`lop_fraction` asserted post-finalize, blocked on pending
  regularization, blocked on pending overtime approval, blocked on unpublished (DRAFT) roster.
- **Lock enforcement (5):** punch, roster create, regularization submit, and recompute all
  rejected with `ATTENDANCE_PERIOD_CLOSED` against a closed-period date; overtime approve rejected
  the same way (the one path with no other guard at all, since it bypasses `calculate()`
  entirely).
- **Reopen (1):** unlocks the day, permits recompute again, and re-finalizing regenerates a fresh
  frozen summary (not a stale leftover).
- **Concurrency (2):** stale If-Match rejected, simultaneous finalize race resolved to exactly one
  winner.

Also ran the **full pre-existing attendance module suite** (all files) together with the new one:
**109 passed**, **zero failures**, plus the same pre-existing, teardown-only test-infrastructure
cascade already documented and unrelated to attendance (§19). The **full backend test suite**
(`pytest tests/`, every module) was also run: **905 passed, 0 failed**, same teardown-only-error
pattern, confirmed pre-existing and unrelated (§19) via an isolated single-test reproduction
*before* any W8 test file existed.

**mypy:** `Success: no issues found in 85 source files` (whole `src/` tree, not just attendance).
**ruff check:** all checks passed, whole `src/`+`tests/` tree. **ruff format:** clean on every
file this slice touched (pre-existing, untouched formatting drift in two unrelated lines of
`repository.py` was left alone, not reformatted as a side effect). **import-linter:** 1 contract
kept, 0 broken (`hrms.modules` depends on `hrms.shared`/`hrms.core` only — verified with
`PYTHONPATH=src lint-imports` after discovering the project's own `.venv` console-script shebangs
were stale, pointing at a since-renamed project path; worked around by invoking tools via
`.venv/bin/python -m <tool>` instead, a pre-existing environment issue, not a W8 one).

---

## 18. Frontend Tests

**14 new tests, all passing.** Full suite: **333/333** (`npx vitest run`).

- `app/app/attendance-periods/page.test.tsx` (5): loading, empty, renders rows, "New period"
  action gated by `ATTENDANCE.LOCK`, permission-denied (403) message.
- `app/app/attendance-periods/[id]/page.test.tsx` (9): loading, not-found (404), `OPEN` period
  renders with live-preview summary and Finalize action, `CLOSED` period renders the locked
  banner + frozen summary + Reopen action (not Finalize), actions hidden without the matching
  permission, Validate runs and shows typed BLOCKED reasons, Finalize succeeds through the
  confirmation dialog (asserts the exact `If-Match` header sent), Finalize's blocked path shows
  the typed reasons inline from the `409` response, Reopen succeeds with a reason through its own
  dialog (asserts the exact payload/header sent).

**tsc --noEmit:** exit 0 (whole project). **`next build`:** compiles successfully; both new routes
(`/app/attendance-periods`, `/app/attendance-periods/[id]`) present in the route manifest.
**`next lint` (ESLint):** could not be run — this project has **no ESLint config file at all**
(`next lint` prompts for interactive first-time setup), confirmed pre-existing and unrelated to
W8 by checking for any `.eslintrc*`/`eslint.config.*` file anywhere in `apps/web` (none exist).
`tsc`+`vitest`+`next build` were used as the available quality gates instead.

---

## 19. Migration Verification

`20260824090000_attendance_period.py` verified on the real dev Postgres 16 instance:

```text
upgrade 20260823090000 -> 20260824090000   OK
downgrade 20260824090000 -> 20260823090000  OK  (all three new tables dropped cleanly)
upgrade 20260823090000 -> 20260824090000   OK  (re-applied cleanly)
```

Also verified the **entire migration chain from an empty database**: created a throwaway
`hrms_w8_fresh_check` database on the same Postgres server (never touching `hrms_dev`), ran
`alembic upgrade head` end to end (all 39 revisions, W0 through W8), confirmed `RLS`/`FORCE RLS`
both `true` on `attendance_period`/`attendance_period_action`/`attendance_period_summary` via a
direct `pg_class` query, then dropped the throwaway database.

**Pre-existing environment note, unrelated to the migration itself:** the project's committed
`.venv` had console-script shebangs (`mypy`, `lint-imports`) hardcoding a since-renamed absolute
project path (`/media/varun/varun4/...` vs. the current `/media/varun/varun5/...`), and `ruff`
resolved to a stale, too-old system install (0.7.1 vs. the `>=0.8.0` pinned in `pyproject.toml`).
Neither is a W8 regression — both were fixed locally for this session (upgrading `ruff` in place,
invoking tools via `.venv/bin/python -m <tool>` instead of the broken shebang scripts) and are
flagged here as worth a real environment fix, not something this session silently patched around
without saying so.

---

## 20. Live Verification

Both servers were started for real (`uvicorn entrypoints.api:app --port 8000`, `next dev --port
3000`) against the real Postgres dev stack, and driven two ways:

**Live API pass** (`httpx` against the real running server, real HTTP, not `TestClient`):
registered a real company, built a real org/employee/shift/calendar/attendance-policy/
regularization-policy graph via real HTTP calls, punched and calculated real attendance,
created a real attendance period, submitted a real pending regularization (an unresolved
exception), attempted finalize — **real `409 ATTENDANCE_FINALIZATION_BLOCKED`** with
`PENDING_REGULARIZATION` in the reasons — approved the regularization, finalized again —
**real `200`, `status=CLOSED`** — confirmed the attendance day's `is_locked=true` via a real
`GET`, then attempted a punch, a roster create, a regularization submit, and a recompute against
the now-locked date — **all four rejected with real `409 ATTENDANCE_PERIOD_CLOSED`** — then
reopened the period with a reason and confirmed the day's `is_locked` flipped back to `false`.
Every step's actual HTTP status and response body was asserted, not assumed.

**Live browser pass** (Python `playwright`, real headless Chromium — `chromium-cli` was
unavailable in this environment, so the skill's own documented fallback, a Playwright REPL
driver, was used, matching the W6 report's identical situation): a real browser session was
authenticated by writing a real token pair into `localStorage` (the same shape
`token-storage.ts` itself writes) and driven through:

1. `/app/attendance-periods` — list renders the created period, correct label/range/status.
2. `/app/attendance-periods/{id}` for an `OPEN` period with a pending exception — clicked the
   real **Validate** button, saw the real rendered **BLOCKED** badge and
   "Pending regularization requests — 1 / Some regularization requests in this period are still
   awaiting a decision" reason text.
3. Resolved the exception via a real API call (approve), then clicked the real **Finalize & lock**
   button, confirmed in the real dialog, and watched the page transition live to **"Closed &
   locked"** / **"Historical attendance in this range is immutable"**, the frozen summary table,
   and a real success toast ("Period finalized and locked") — no page reload, no mock.
4. A separately-created already-`CLOSED` period was screenshotted directly: locked banner, frozen
   summary, **Reopen** button present, **Finalize** button correctly absent.

**Zero browser console errors or page errors at any point in either pass.** Screenshots were
captured at each step (list, blocked-validation, finalized-via-dialog, closed-state).

**A real, non-W8 behavior was discovered and diagnosed during this pass, not hidden:** approving
the demo regularization (a `MISSING_PUNCH` correction against a day that already had complete
punches — an unrealistic scenario chosen only for test convenience) caused the day to become
`INCOMPLETE` after recompute, because the two near-duplicate `IN`/`OUT` punch pairs confused
`calculation.py`'s existing pairing logic. This is pre-existing W4/W6 punch-pairing-under-
duplicate-punches behavior (WD-28's own "corrections are always additive, original punches never
touched" design already implies this is possible), **not a W8 defect** — and it gave a genuine,
live confirmation that W8's own `incomplete_at_lock_behaviour` resolution (§9) worked correctly:
the `INCOMPLETE` day was not blocked (default `TREAT_ABSENT` policy), was correctly resolved to
`paid_day_fraction=0.00`/`lop_fraction=1.00` at finalize, and was correctly locked. Recorded in
decision log WD-30 for W6/W9 awareness, not silently fixed (out of this slice's scope boundary).

**Demo data left in the dev database:** live verification created several demo companies
(`W8 Live Verify …`, `W8 Browser Verify …`, `W8 Blocked Browser …`) in the shared dev Postgres
instance — harmless, RLS-isolated test-scoped data, matching the W6 report's own §19.5 precedent.
Not cleaned up given the time budget; flagged for whoever next resets that database. Both local
dev servers (`uvicorn`, `next dev`) were stopped cleanly at the end of this session.

**Not covered by this live pass, done via automated tests instead:** a restricted user without
`ATTENDANCE.LOCK`/`.UNLOCK` was verified via backend integration tests (`test_unauthorized_user_
cannot_create_period`, `test_unlock_requires_separate_permission`) and a frontend unit test
(action buttons hidden without the matching permission), not through a second live browser
session — recorded honestly rather than implied as browser-verified.

---

## 21. Known Limitations

### 21.1 Punch-lock check uses the punch's UTC calendar date, not its shift-attributed date

`PunchService.record_punch`'s period check uses `(body.punch_time or now).date()` in UTC — the
only date knowable *before* shift resolution, which itself depends on the date. For an overnight
shift, a punch a few minutes into the *next* UTC day, whose attendance actually attributes to the
*previous* shift-start date (FR-ATT-005), could in principle land just outside this check's
window at a period boundary. The backstop that never allows a locked historical fact to actually
change is unconditional regardless: `AttendanceDayService.calculate()` refuses a locked day
outright (§9), so a stray punch here is at worst an inert, orphaned row (WD-11 — additive, never
mutates facts), never a silent rewrite. Documented explicitly, not silently ignored; no test
exercises this specific overnight-boundary edge case (§21.3).

### 21.2 `AttendanceAdjustment`/arrears path not built (PD-LOCK-2, OPEN)

See §10/§4. The only correction path after lock is a full `ATTENDANCE.UNLOCK` reopen — coarse but
safe. A real product question for the team: does any launch customer need a narrower, per-record
post-lock correction without reopening the whole period?

### 21.3 Exotic scenarios not covered by automated tests

Per the task's own test list, month-boundary and overnight-shift-crossing-period-boundary
scenarios, Asia/Kolkata-specific timezone behavior, and effective-dated-assignment interactions
with period locking were not each given a dedicated test, given the scope already covered (21
backend + 14 frontend tests across every required category except these). None of these are
believed to be broken — the underlying mechanisms (`_ensure_date_open`, `bulk_lock`/`bulk_unlock`)
are date-range-based and timezone-agnostic at the SQL level — but this is stated as an honest gap,
not implied coverage.

### 21.4 Pre-existing environment issues found and worked around, not part of W8

- **`.venv` console-script shebangs stale** (hardcoded a since-renamed project path) — worked
  around per-session, not fixed at the repo level.
- **`ruff` resolved to a too-old system install** initially — upgraded in place for this session.
- **No ESLint config exists in `apps/web` at all** — `next lint` cannot run without interactive
  setup; `tsc`/`vitest`/`next build` used instead.
- **A pre-existing, unrelated teardown-only test-infrastructure cascade** (`seeded_plan_catalogue`
  fixture's `DELETE FROM plan` racing a still-referencing `subscription` row from a different
  test/fixture's session) produces `ERROR` (not `FAILED`) on the majority of tests across the
  *entire* backend suite, confirmed present and identical before any W8 code existed (isolated
  reproduction on `test_attendance_policy.py`, a file this slice never touches). Distinct from
  W6's own previously-documented RLS/`current_setting` bug — a second, separate pre-existing
  fragility in the same category. Not fixed (out of scope, not small/isolated/attendance-related
  per this task's own bar); every test-body assertion across 905 backend + 333 frontend tests
  still passed.
- **One genuinely stale pre-existing test assertion was found and fixed** (§12) — the live-
  registration permission-grant set in `test_registration_flow.py` had silently drifted out of
  sync since W6, independent of W8.

---

## 22. Explicit Exclusions

Per the task brief's own scope boundary, none of the following were touched:

- **Leave, Payroll, salary/statutory calculations, payslips, payroll periods.**
- **`AttendanceAdjustment`** — a distinct entity per WD-18, not built (§10/§21.2, OPEN PD-LOCK-2).
- **Biometric/device ingestion, GPS/geofencing, shift rotation, a generic workflow engine.**
- **Legal-entity lock grain** — PD-LOCK-1 remains open; only a reserved, unused column ships.
- **The pre-existing teardown-only test-infrastructure cascade** (§21.4) and the stale `.venv`
  environment issues — reported, not fixed, per the task's own smallness criterion.

---

## 23. Open Product Decisions

| ID | Question | Status |
|---|---|---|
| **PD-LOCK-1** (pre-existing, architecture §32) | Attendance lock grain: company, legal entity, or pay cycle? | Still open — company grain ships now per the architecture's own stated default (Payroll doesn't exist to be LE-scoped); reserved column for later |
| **PD-LOCK-2** (new) | Should `AttendanceAdjustment`/an `APPROVED_PENDING_ARREARS` path ever exist for controlled post-lock correction without a full reopen? | Open — default shipped is reject + full-period `ATTENDANCE.UNLOCK` reopen only |

---

## 24. Recommended Next Step

**W9 (Leave projection adapter) or W10 (Device ingestion) can both safely begin** — W8 does not
touch, block, or leave in an inconsistent state anything either would depend on.

Before either, two things are worth flagging to the team (not blocking, but real):

1. **PD-LOCK-2** (§23): is a narrower post-lock correction mechanism actually needed by any
   launch customer, or is "reopen the whole period" an acceptable operational cost? This decides
   whether `AttendanceAdjustment` needs its own scoped slice.
2. **The second pre-existing test-infrastructure cascade** (§21.4) — distinct from W6's own
   already-flagged RLS bug — is real, reproducible, and affects the great majority of this
   backend's test runs with `ERROR` (not `FAILED`) teardown noise. It doesn't hide a single actual
   regression in this session's own testing (every real assertion still ran and passed), but it
   makes every future session's own test output harder to read at a glance and should be triaged
   as its own ticket.

---

### Test counts (exact)

- Backend: **21/21** new (`test_attendance_period.py`), **109 passed** across the full attendance
  module suite (new + pre-existing), **905 passed / 0 failed** across the *entire* backend suite
  — plus the pre-existing, unrelated, teardown-only cascade documented in §21.4 (confirmed
  identical before this session's W8 code existed).
- Frontend: **14/14** new, **333/333** full suite.
- mypy: 0 issues (85 source files, whole `src/`). ruff: 0 issues (whole `src/`+`tests/`).
  import-linter: 1 contract kept, 0 broken. tsc: 0 errors. `next build`: succeeds.
- Migration: upgrade/downgrade/upgrade verified; full from-scratch chain verified on a throwaway
  database; RLS + FORCE RLS confirmed on all three new tables.
- Live verification: full create→blocked→resolve→finalize→lock→reject-mutations→reopen cycle
  confirmed against a real running server and real Postgres (API pass) and a real headless
  browser with zero console errors (browser pass) — both documented in full in §20, including one
  genuine, honestly-reported non-W8 behavior discovered along the way.
