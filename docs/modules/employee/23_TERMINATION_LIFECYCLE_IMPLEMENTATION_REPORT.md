# Termination → Assignment/Compensation Closure — Implementation Report

**Status: IMPLEMENTED.** Follows
`docs/modules/employee/22_TERMINATION_ASSIGNMENT_COMPENSATION_PLAN.md` exactly. No migration, no
new repository method, no new permission, no API contract change — matching the plan's own §21
design. Nothing committed by this work (per task scope); all changes are in the working tree only.

**Date:** 2026-08-15

---

## 1. Status

Implemented and validated. Full backend suite green (491 tests), `ruff check`, `ruff format
--check`, `mypy src/hrms`, and `lint-imports` all pass with zero findings. Dev database verified
clean of test-created rows after the run (only pre-existing fixed-UUID seed/demo data remains,
untouched).

One product decision from the plan (OD-1, §8/§19) was resolved for this implementation by the
task owner, not invented here — see §16.

---

## 2. Problem Fixed

`EmploymentService.terminate_employment` updated only `employment.status`/`last_working_day`/
`version`. It never closed the employee's currently-open `employee_assignment`/
`employee_compensation` row. Consequence: after termination, an `as_of` query landing after the
exit date (including one issued by a future Attendance/Leave/Payroll module) still returned the
terminated employee's stale pre-exit placement and pay — indefinitely, if never rehired. On
rehire, the stale row was only closed by the rehire's own `create_assignment`/
`create_compensation` call, at `rehire.effective_from - 1 day`, corrupting the historical
boundary (proven by the two existing tests that positively asserted this wrong date).

---

## 3. Files Changed

| File | Change |
|---|---|
| `apps/api/src/hrms/modules/employee/service.py` | `EmploymentService.__init__` gains `_assignment_repo`/`_compensation_repo`; `terminate_employment` gains the two new close steps |
| `apps/api/tests/unit/modules/employee/test_employment_service.py` | 8 new unit tests + fixture updates (mocked repos) |
| `apps/api/tests/integration/modules/employee/test_employment.py` | 8 new integration tests (real DB) |
| `apps/api/tests/integration/modules/employee/test_employee_assignment.py` | `test_rehire_first_assignment_after_gap` corrected; `test_rehire_carries_forward_stale_shift_id` renamed/rewritten (see §16) |
| `apps/api/tests/integration/modules/employee/test_employee_compensation.py` | `test_rehire_first_compensation_after_gap` corrected |

**Not changed** (per plan §22/§23, verified against the actual diff, not assumed): `router.py`,
`permissions.py`, `repository.py`, `models.py`, `schemas.py`, `exceptions.py`, any Alembic
migration, any file outside `modules/employee/`.

---

## 4. Database Changes

None. No migration, no new column, no new table, no schema change of any kind. The fix reuses
`employee_assignment.effective_to`/`version` and `employee_compensation.effective_to`/`version`
exactly as they already exist.

---

## 5. Service Behavior

`EmploymentService.terminate_employment` (`service.py:465-640`) now runs, between the existing
validation and the existing `update_employment` call, inside the same request-scoped
transaction:

1. Read the employee's current `employee_assignment` row (`get_current_assignment`), if any.
2. If it exists and `effective_from <= last_working_day`: close it (`effective_to =
   last_working_day`, server-read `version`), then record `ASSIGNMENT_CHANGED`.
3. If it exists and `effective_from > last_working_day`: leave it open — see §13/§16.
4. Same two steps, independently, for `employee_compensation` / `COMPENSATION_REVISED`.
5. Existing `update_employment` call (unchanged) → `EMPLOYMENT_TERMINATED` audit (unchanged,
   last).

No change to `EmployeeAssignmentService`/`EmployeeCompensationService`'s own write paths — the
fix is entirely inside `EmploymentService`, reusing `EmployeeAssignmentRepository.
close_assignment`/`EmployeeCompensationRepository.close_compensation` verbatim (no duplicated
closure logic).

---

## 6. Assignment Closure Behavior

- Current row exists, `effective_from <= last_working_day` → closed at `effective_to =
  last_working_day`. Only `effective_to`/`version`/`updated_at` change; every business column
  (`branch_id`, `department_id`, etc.) is byte-for-byte identical before/after (verified at the
  audit-log level by
  `test_terminate_employment_closes_current_assignment_and_compensation`).
- No current row → termination succeeds, nothing created, no `ASSIGNMENT_CHANGED` audit row.
- Historical (already-closed) rows are never read or written — only `get_current_assignment`'s
  single `effective_to IS NULL` row is ever touched.
- Current row's `effective_from > last_working_day` → left open (OD-1, §13/§16).

## 7. Compensation Closure Behavior

Structurally identical to §6, via `EmployeeCompensationRepository.close_compensation`.

---

## 8. Transaction Behavior

No explicit `BEGIN`/`COMMIT` — the fix is additive logic inside the same method, inheriting the
existing per-request session's commit-on-success/rollback-on-exception wrapper
(`core/db/session.py` `get_session`), identical to every other write path in this module. If the
assignment close fails (stale version), a `StaleResourceError` is raised immediately —
`employee_compensation` and `employment` are never reached. If the assignment close succeeds but
the compensation close then fails, `update_employment` is never reached and the whole request
rolls back, undoing the assignment close too (nothing was committed for it since no explicit
commit exists mid-method).

Verified two ways:
- Unit level (mocked repos):
  `test_terminate_employment_assignment_stale_version_raises` and
  `test_terminate_employment_compensation_stale_version_raises_after_assignment_closed` assert
  `update_employment`/subsequent repo calls are never awaited on the failure path.
- Integration level (real DB, real rollback):
  `test_terminate_employment_rolls_back_on_compensation_close_failure` runs the service directly
  inside `session_scope` (the same commit/rollback wrapper `get_session` uses) with
  `close_compensation` patched to return `None`, then re-queries via a **fresh** session/HTTP
  call and asserts `employment` is still `ACTIVE`, the assignment is still open, the
  compensation is still open, and no `ASSIGNMENT_CHANGED`/`COMPENSATION_REVISED`/
  `EMPLOYMENT_TERMINATED` row was added.

A genuine concurrent-request race (a real `POST .../assignments` transfer landing between this
method's read and its own close `UPDATE`) is not deterministically reproducible in a test; the
patched-repository approach reproduces the identical *outcome* (`close_* → None`) that such a
race would produce, which is what the transactional guarantee actually depends on.

---

## 9. Audit Behavior

Reuses the two existing action names, per plan §14 — no new audit event introduced:

| Action | Fired when | Before / After |
|---|---|---|
| `ASSIGNMENT_CHANGED` | Current assignment closed by termination | `before` = pre-close snapshot; `after` = same row post-close |
| `COMPENSATION_REVISED` | Current compensation closed by termination | Same shape |
| `EMPLOYMENT_TERMINATED` | Always, on success (existing, unchanged) | `employment` pre/post |

Ordering: assignment close → its audit; compensation close → its audit; employment update → its
audit (existing, last) — matching plan §14's interleaved-per-write recommendation.

Verified: `entity_id` on each row points at that table's own id (never all three pointing at
`employment.id`); `before`/`after` on the two new actions differ only in `effective_to` (plus
`version`/`updated_at`) — every business column identical, checked field-by-field in
`test_terminate_employment_closes_current_assignment_and_compensation`.

---

## 10. Concurrency Behavior

- `employment.version`/`If-Match`: unchanged — still the only client-supplied version, still
  guards `employment` alone (`test_terminate_employment_stale_version_conflict`, pre-existing,
  unmodified, still passes).
- `employee_assignment`/`employee_compensation` `version`: **server-read**, never
  client-supplied — read fresh inside the same transaction immediately before the close call,
  exactly per plan §11/§21. No new request field, no new `If-Match` semantics for this endpoint.
  Verified directly:
  `test_terminate_employment_closes_current_assignment_and_compensation` (unit) asserts the
  `expected_version` passed to `close_assignment`/`close_compensation` equals the value read off
  the current row, not any client input.
- Idempotency: unchanged. Retried termination hits the existing `status != ACTIVE` guard before
  reaching any of the new closing logic.

---

## 11. Tests Added/Changed

**Unit** (`test_employment_service.py`, mocked repositories) — 8 new:
1. `test_terminate_employment_closes_current_assignment_and_compensation` — normal case, both
   closes, server-read versions, audit action ordering and payloads.
2. `test_terminate_employment_no_current_assignment_succeeds`
3. `test_terminate_employment_no_current_compensation_succeeds`
4. `test_terminate_employment_future_dated_assignment_left_open`
5. `test_terminate_employment_future_dated_compensation_left_open`
6. `test_terminate_employment_assignment_stale_version_raises`
7. `test_terminate_employment_compensation_stale_version_raises_after_assignment_closed`

Plus fixture updates: `service` fixture now defaults `_assignment_repo.get_current_assignment`/
`_compensation_repo.get_current_compensation` to `None`, so the 16 pre-existing termination/
other unit tests continue to exercise the "no current row" path unchanged (verified: all
pre-existing tests still pass, unmodified in behavior).

**Integration** (`test_employment.py`, real DB) — 8 new:
1. `test_terminate_employment_closes_current_assignment_and_compensation` — end-to-end normal
   case, real GiST-constrained tables, real audit rows.
2. `test_terminate_employment_no_assignment_still_succeeds`
3. `test_terminate_employment_no_compensation_still_succeeds`
4. `test_terminate_employment_leaves_historical_rows_untouched` — two transfers/two revisions,
   only the current row closes, historical rows byte-for-byte identical.
5. `test_terminate_employment_future_dated_assignment_left_open`
6. `test_terminate_employment_future_dated_compensation_left_open`
7. `test_terminate_employment_rolls_back_on_compensation_close_failure` — real-DB rollback proof
   (§8).
8. `test_terminate_employment_does_not_affect_other_tenant_assignment_or_compensation`

**Corrected** (existing tests that encoded the bug, per plan §3/§17/§22):
- `test_employee_assignment.py::test_rehire_first_assignment_after_gap` — now asserts the
  pre-exit row closes at `employment_1.last_working_day` ("2030-09-30"), not
  `rehire.effective_from - 1` ("2034-01-31"); adds an explicit `get_current_assignment`-returns-
  nothing-during-the-gap assertion (`?as_of=` in the gap → `[]`); rehire's first `create_assignment`
  no longer supplies `If-Match` (no current row to conflict with).
- `test_employee_compensation.py::test_rehire_first_compensation_after_gap` — same shape, same
  reason.
- `test_employee_assignment.py::test_rehire_carries_forward_stale_shift_id` → renamed
  `test_rehire_first_assignment_does_not_carry_forward_stale_shift_id` — this test's *premise*
  depended on the same bug (pre-exit row staying open let the rehire's `create_assignment` take
  the "current row exists" carry-forward branch). Fixed, the rehire's first assignment now takes
  the "no current row" branch and does not carry `shift_id` forward; the test now asserts that,
  not the old value. Found by running the full suite, not named in the task brief — an
  "equivalent assertion" per the task's own instruction to find and fix those.

No test was weakened or deleted to make the suite pass — each corrected test's assertion moved
to the *authoritative* boundary, and each corrected test still verifies the same invariant
(historical boundary, carry-forward semantics) with the value that invariant now produces.

---

## 12. Full Validation Results

Run from `apps/api/`:

| Check | Result |
|---|---|
| `uv run pytest` (full suite) | **491 passed** |
| `uv run pytest tests/integration/modules/employee/` | 99 passed |
| `uv run pytest tests/unit/modules/employee/test_employment_service.py` | 32 passed |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 154 files already formatted |
| `uv run mypy src/hrms` | Success: no issues found in 73 source files |
| `uv run lint-imports` | Contracts: 1 kept, 0 broken |
| Dev DB post-run | `employee`/`employment`/`employee_assignment`/`employee_compensation`/org tables: 0 rows. Only pre-existing fixed-UUID seed data (2 companies, 2 users, 1 session, 1 audit row, all dated at DB init) remains, untouched by any test run. |

No regression in any other module (`organisation`, `identity`, `health`, the rest of
`employee`) — full suite green, not just the employee module.

---

## 13. Edge Cases

- **No current assignment / no current compensation / both missing** — termination succeeds,
  nothing created, no audit row for the missing sub-resource. Covered.
- **Multiple historical rows** — untouched; only the single `effective_to IS NULL` row per table
  is ever read or written. Covered.
- **Current row's `effective_from` in the past but still `<= last_working_day`** — closes
  normally (the ordinary case, not actually ambiguous per plan §8). Covered implicitly by every
  normal-case test.
- **Current row's `effective_from > last_working_day`** (a future transfer/raise already
  entered before an unexpected early exit) — genuinely open per the plan (OD-1); resolved for
  this implementation as "leave the row open, termination still succeeds" — see §16. Covered by
  4 tests (2 unit, 2 integration).
- **Concurrent transfer/compensation-revision racing termination** — whichever commits first
  wins; the loser's whole transaction rolls back (§8/§10 above). The failure *outcome* is
  covered (patched-repository rollback test); the literal two-request race is not
  deterministically reproducible in a test and is not separately simulated.
- **Repeated termination** — unchanged `409 EMPLOYMENT_NOT_ACTIVE`, existing test untouched and
  still passing; no new assignment/compensation writes are attempted on the second call (the
  `status != ACTIVE` guard fires first).
- **Tenant isolation** — the new repository calls are `(company_id, employee_id)`-filtered
  exactly like every other method on `EmployeeAssignmentRepository`/
  `EmployeeCompensationRepository`; no new cross-tenant surface. Covered by a dedicated
  two-tenant integration test.

---

## 14. Known Limitations

- **Retroactive gap (plan §19 OD-3, unresolved by design).** This fix is forward-only. Any
  employment already terminated under the old bug, in any environment with non-empty data
  (dev/staging included, if termination has been exercised there against real data before this
  change), keeps its stale open assignment/compensation row unless separately backfilled. No
  backfill script is included — this task was not authorized to write one (plan §23/§25), and
  the dev DB checked in §12 was empty of employee-module rows before this session's own test
  runs, so no backfill was needed *for this session*. Whether any other environment needs one is
  a separate, still-open decision (OD-3).
- **OD-1's "reject" alternative was not built.** The plan's own recommendation (§8, not locked)
  was to reject the terminate call in the future-dated-beyond-exit case. The task owner chose
  "leave the row open, termination still succeeds" instead (§16) — a legitimate, previously-
  documented alternative (plan §8 option 2), not an invented third option. If product later
  prefers "reject," that is a distinct, small follow-up change (a new validation error), not a
  revisit of this implementation's other behavior.
- **No literal two-request concurrency race is exercised.** The rollback/concurrency tests
  reproduce the *outcome* of a lost race (`close_* → None`) via a patched repository, not an
  actual interleaved second request. This is consistent with how this codebase's other
  concurrency tests are written (no `SELECT ... FOR UPDATE`, no other test in this module
  simulates true interleaving either).

---

## 15. Scope Explicitly Excluded

Per the task's own instructions, not touched: Employee frontend, Attendance, Leave, Payroll,
Recruitment, ATS, Performance, Workflow, BR-14, Shift Rules master module, any organisation
module. No migration. No new permission. No new endpoint. No change to
`EmployeeAssignmentService`/`EmployeeCompensationService`'s own write paths. Verified against the
actual `git diff` (§3) — five files changed, all inside `apps/api/src/hrms/modules/employee/` or
its test tree.

---

## 16. Remaining Decisions

**OD-1 resolution (this session):** the task owner was asked directly (the plan itself frames
this as requiring product/architecture sign-off before that one code path could be written) and
chose: when the current assignment/compensation row's `effective_from > last_working_day`,
**leave that row open and let termination succeed** — rather than rejecting the terminate call.
This is now the implemented, tested behavior (§6/§7/§13), not merely a recommendation. It is
recorded here as a decision made *for this implementation*, not as a `DEC-NNN` architecture-log
entry — that remains a separate step if the team wants it locked at that level.

**Still open, unchanged by this implementation:**
- **OD-3** (plan §19): whether any already-terminated employment in a shared dev/staging
  database needs a one-off backfill. Not applicable to the dev DB used for this session's own
  validation (verified empty of employee-module rows pre- and post-run), but not evaluated
  against any other environment.
- Whether OD-1's outcome should be promoted to a numbered `DEC-NNN` entry in
  `HRMS_ARCHITECTURE_DECISION_LOG.md`. Not done here — out of this task's stated scope
  (implementation, not architecture-log maintenance) — but flagged since a future reader of that
  log won't otherwise learn this was a conscious choice rather than an oversight.

---

## 17. Recommended Next Step

Per the plan's own §24 implementation sequence (step 7) and
`HRMS_SYSTEM_DESIGN_BASELINE.md §21`: resume the roadmap's next item — RBAC data-scope
enforcement — then E-07 Statutory. This lifecycle fix was the named blocker (`HRMS_SYSTEM_DESIGN_
BASELINE.md §18` CRITICAL-1) for Attendance/Leave/Payroll ever being built against
`get_assignment_as_of`/`get_compensation_as_of`; those modules can now be sequenced without
inheriting the stale-row bug into their own logic.
