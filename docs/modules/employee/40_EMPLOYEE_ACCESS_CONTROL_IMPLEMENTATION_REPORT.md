# Employee Vertical — Access-Control Implementation Report (F4/F8/F9)

**Date:** 2026-08-16
**Status:** Implementation complete. Nothing committed — working tree left uncommitted for review,
per task instructions.
**Relationship to prior documents:** implements `docs/modules/employee/
39_EMPLOYEE_ACCESS_CONTROL_IMPLEMENTATION_PLAN.md` (Phases 1, 1B, 2 only — Phase 3 deliberately
**not** implemented, see §19). Does not reopen the plan's own architecture findings; where this
report deviates from or extends the plan's description of the starting state, that is called out
explicitly (§2).

---

## 1. Status

**Complete for Phases 1, 1B, and 2** of the plan. **Phase 3 (hierarchy-escalation-via-write) is
explicitly not implemented** — the plan's own instruction is to stop before it until Product
Decision 3 (§21 of the plan) is resolved, and it remains unresolved. This is not a partial or
blocked delivery; it is the plan's own scope boundary, honored as written.

## 2. Starting State Found (important deviation from a literal reading of the plan)

The plan's Finding A/B/C descriptions (§8–§13) describe `router.py` as never resolving a real
`DataScope` for Employment/Assignment GET or any write route. On inspection at the start of this
session, **the service layer (`service.py`) had already been substantially rewritten** by prior
work (per the user, done with another AI tool) to accept and enforce `scope`/`caller_employee_id`
parameters on every one of these methods — `EmploymentService.{create,list,get,update,
terminate}_employment`, `EmployeeAssignmentService.{create,list,get}_assignment`,
`EmployeeService.{update,deactivate}_employee`, `EmployeeCompensationService.create_compensation`,
`EmployeeStatutoryService.create_statutory` — all already had a working `_assert_employee_visible`
call wired to `EmployeeService.resolve_visible_employee_ids`, with docstrings explicitly citing
this plan document. **`router.py`, however, still bound every one of these to `_scope: Annotated[
object, ...]` (or, for `create_assignment`, a bare `rbac.has_permission()` boolean) — the resolved
scope was computed by the dependency but the router never read it, so the service-layer work was
entirely inert.** This is the "resolve-then-discard" bug shape the plan itself names as the
Compensation/Statutory F2/F3 precedent, reproduced across every remaining route.

**One additional, undocumented defect found and fixed**: `EmployeeBankService.create_bank` called
a method named `self._assert_employee_exists(...)` that **did not exist anywhere in the class** —
this was dead code that would have raised `AttributeError` on first invocation, not merely
"unscoped." (The full pytest suite did not catch this beforehand because no test exercised
`create_bank` on a real HTTP path with an out-of-scope condition serious enough to hit this — every
existing `create_bank` test used the tenant admin, whose `COMPANY`-scoped default write path never
required the scope-visibility branch.) Fixed in the same shape as `create_compensation`/
`create_statutory`, see §5.

The remainder of this report describes the work actually required and performed this session:
wiring `router.py` to pass the already-built service-layer scope enforcement through, fixing the
one broken write route, and adding the test coverage the plan's own §19/§23 identifies as
completely absent.

## 3. Scope Implemented

- **Phase 1** — Employment GET (`list_employments`, `get_employment`) now scope-enforced.
- **Phase 1B** — Assignment GET (`list_assignments`, `get_assignment`) now scope-enforced.
- **Phase 2** — every write route now scope-enforced: `update_employee`, `deactivate_employee`,
  `create_employment`, `update_employment`, `terminate_employment`, `create_assignment`,
  `create_compensation`, `create_statutory`, `create_bank`.
- **Phase 3 — explicitly not implemented** (§19).

## 4. Files Created

- `docs/modules/employee/40_EMPLOYEE_ACCESS_CONTROL_IMPLEMENTATION_REPORT.md` (this document).

No migration, schema, or frontend file was created or modified.

## 5. Files Modified

| File | Change |
|---|---|
| `apps/api/src/hrms/modules/employee/router.py` | Every GET/write route listed in §3 changed from `_scope: Annotated[object, ...]` to `scope: Annotated[DataScope, ...]`, added `user: Annotated[AuthenticatedUser, ...]` where missing, and threaded `scope=scope, caller_employee_id=user.employee_id` into the corresponding service call. `create_assignment`'s permission check was converted from a bare `rbac.has_permission()` boolean to `rbac.resolve_data_scope()`, mirroring `core/rbac/dependencies.py`'s own `_check_permission` helper exactly (empty `.levels` → `403`; non-empty → both proof-of-permission and the scope to enforce). Module docstring and per-section comments updated to reflect the new state. |
| `apps/api/src/hrms/modules/employee/service.py` | One fix: `EmployeeBankService.create_bank` — replaced the call to the nonexistent `_assert_employee_exists` with `_assert_employee_visible` (the same helper `list_banks`/`get_bank` already used) and added `scope`/`caller_employee_id` parameters, matching `create_compensation`/`create_statutory`'s already-correct shape exactly. Updated `EmployeeBankService`'s class docstring, which had stated `create_bank` was intentionally unscoped. |
| `apps/api/tests/integration/modules/employee/test_employment.py` | Added a "Data-scope enforcement" read section (6 tests) and a write-path section (4 tests) — see §12. |
| `apps/api/tests/integration/modules/employee/test_employee_assignment.py` | Extended `_create_permission_scoped_user` with `data_scope`/`caller_employee_id` parameters (previously `COMPANY`-only, no linked employee); added a read section (6 tests) and a write-path section (2 tests). |
| `apps/api/tests/integration/modules/employee/test_employee_data_scope.py` | Added a write-path section (3 tests) covering `update_employee`/`deactivate_employee`. |
| `apps/api/tests/integration/modules/employee/test_employee_compensation.py` | Added a write-path section (2 tests) for `create_compensation`. |
| `apps/api/tests/integration/modules/employee/test_employee_statutory.py` | Added a write-path section (2 tests) for `create_statutory`. |
| `apps/api/tests/integration/modules/employee/test_employee_banking.py` | Added a write-path section (2 tests) for `create_bank`. |
| `apps/api/tests/unit/modules/employee/test_employee_assignment_service.py` | Fixed a **pre-existing regression**, unrelated to this session's router work: `test_create_assignment_unknown_reporting_manager_rejected`'s mocked `_get_employee` had a fixed 3-argument signature that didn't accept the `visible_employee_ids` keyword the already-modified `create_assignment` → `_assert_employee_visible` call site passes. This test failed on the very first full-suite run this session, before any router changes — caused by the prior session's service-layer edits, not by this session's own changes. Fixed by widening the mock's signature to accept the keyword (default `None`), which is all `_assert_employee_visible` requires. |

Every other file shown as modified/untracked by `git status` (RBAC core, tenancy, identity models,
Statutory/Banking permissions/models/exceptions/schemas, frontend files, and every `docs/` file
other than this one and `39_...PLAN.md`) predates this session and was **not touched** by this
work — confirmed by `git diff` inspection before editing anything.

## 6. Read-Path Changes

`list_employments`/`get_employment`/`list_assignments`/`get_assignment` now resolve the caller's
`DataScope` via `Depends(require_permission(EMPLOYEE_VIEW))` and pass it, plus `user.employee_id`,
to the service, which calls a new-to-the-router-but-already-implemented `_assert_employee_visible`
before branching on `as_of` — identical ordering to Compensation/Statutory/Bank, so `as_of` cannot
bypass scope (verified, §12). An out-of-scope target raises `NotFoundError` → `404`, identical to a
nonexistent or cross-tenant ID.

## 7. Write-Path Changes

Every write route now resolves scope the same way its permission's GET-route sibling does (or, for
identity/Employment/Assignment, the way Compensation/Statutory/Bank's GET routes already did) and
calls `_assert_employee_visible` (or, for `create_employee`, N/A — no target employee exists yet)
before performing the mutation. `create_assignment` is the one structurally different route: its
gating permission is chosen by `body.change_type` at runtime, so it cannot use a static
`Depends(require_permission(CODE))`; it now calls `rbac.resolve_data_scope()` directly and raises
the same `PermissionDeniedError` `require_permission` would on an empty scope, then passes the
resolved scope into `create_assignment` the same way every other write route does.

## 8. DataScope Behavior

`SELF`/`REPORTEES`/`REPORTEE_TREE`/`COMPANY` all resolve via the existing, unmodified
`EmployeeService.resolve_visible_employee_ids` — no new resolver logic was written anywhere in this
session, exactly as the plan requires (§7 "Do not create a second scope-resolution
implementation"). Every out-of-scope target — read or write — returns `404`, never `403`,
regardless of `as_of`, matching Decision I's convention.

## 9. Permission Behavior

Unchanged. No permission code, no `DataScope` enum value, and no HTTP semantics were changed
except the specific out-of-scope-target `404` behavior this task exists to add. `create_assignment`
now performs the *same* permission check as before (holding `EMPLOYEE_TRANSFER`/`EMPLOYEE_PROMOTE`
by `change_type`), computed through a different RBAC method (`resolve_data_scope` instead of
`has_permission`) that returns strictly more information (the scope) for identical pass/fail
behavior on the permission question — verified by the full, unmodified `test_promotion_requires_
promote_not_transfer_permission`/`test_create_assignment_without_transfer_permission_rejected`
tests still passing unchanged.

## 10. Assignment/Manager Security Behavior

The direct reporting-manager self-elevation guard (`_assert_manager_reference` reject-on-
`manager_id == employee_id`, `service.py`) is **unmodified** and was not touched this session — its
existing regression suite (`test_employee_data_scope.py`'s `test_reportees_scope_cannot_be_
widened_via_self_assignment`, `test_self_elevation_guard_applies_to_first_assignment`,
`test_legitimate_manager_change_to_third_party_still_succeeds`) passes unchanged, proving the new
target-employee scope check composes with the guard correctly (guard still fires even when the
scope check would otherwise allow the write).

**Phase 3 (should reassigning `X` to report to a third party `Y` also require the caller to have
visibility over `Y`?) is explicitly not implemented** — the plan's Product Decision 3 (§21) is
unresolved, and the plan's own Phase 3 instruction is to stop, not invent a policy. Today's
behavior (unchanged from before this session): a scope-authorized write to an in-scope target `X`
naming an unrelated, tenant-valid `Y` as `reporting_manager_id` succeeds. This is a known, named,
pre-existing gap — not introduced or worsened by this session's changes, and not silently resolved
either.

## 11. Tenant/RLS Behavior

Untouched. No migration, model, or RLS-policy file was modified. `tests/security/
test_rls_runtime_role.py` (pre-existing, untouched) passes unchanged in the final full run (§14).
Every new cross-tenant test added this session (§12) independently reconfirms tenant isolation
composes correctly with the new scope checks — tenant mismatch is caught by `get_tenant_context`
before any scope resolution runs, for both read and write routes.

## 12. Tests Added

27 new integration tests, across 6 files, all following each file's existing fixture conventions
(no new test infrastructure or shared helper module introduced):

| File | New tests | Coverage |
|---|---|---|
| `test_employment.py` | 10 | GET: SELF (list+detail), SELF/no-employee-id, REPORTEES, COMPANY, as_of-cannot-bypass, cross-tenant+scope. Write: `create_employment`/`update_employment`/`terminate_employment` REPORTEES in-scope-succeeds/out-of-scope-404, `create_employment` cross-tenant+scope. |
| `test_employee_assignment.py` | 8 | GET: SELF (list+detail), SELF/no-employee-id, REPORTEES (incl. asserting no field leak on 404), COMPANY, as_of-cannot-bypass, cross-tenant+scope. Write: `create_assignment` REPORTEES in/out-of-scope (in-scope path exercises the `MANAGER_CHANGE` current-row-close branch, not just first-assignment), cross-tenant+scope. |
| `test_employee_data_scope.py` | 3 | Write: `update_employee`/`deactivate_employee` REPORTEES in/out-of-scope, `update_employee` cross-tenant+scope. |
| `test_employee_compensation.py` | 2 | Write: `create_compensation` REPORTEES in/out-of-scope, cross-tenant+scope. |
| `test_employee_statutory.py` | 2 | Write: `create_statutory` REPORTEES in/out-of-scope, cross-tenant+scope. |
| `test_employee_banking.py` | 2 | Write: `create_bank` REPORTEES in/out-of-scope, cross-tenant+scope (also the regression proof for the `_assert_employee_exists` bug fix — this route could not have passed a REPORTEES-scope test at all before the fix, since it would have raised `AttributeError`). |

Plus 1 pre-existing test fixed (not a new test): `test_employee_assignment_service.py::
test_create_assignment_unknown_reporting_manager_rejected` (§5).

`REPORTEE_TREE` was intentionally not added as a separate test for Employment/Assignment GET,
matching the plan's own stated priority (§19: `REPORTEE_TREE` is resolver-correctness risk, already
proven once via the Employee-identity route; re-testing it per-resource is redundant coverage, not
a gap) — the same posture the plan describes Compensation/Statutory already having.

## 13. Full Test Results

```
645 passed, 0 failed, 0 xfailed
```

Run: `.venv/bin/python -m pytest -q` (full suite, `apps/api/`). No test was skipped, xfailed, or
weakened to reach this result.

Targeted employee/RBAC/organisation subset (subsumed by the full run above, listed separately per
task instructions):

```
apps/api/tests/integration/modules/employee/  — 199+27 = included in full run, all passing
apps/api/tests/security/test_rls_runtime_role.py — included in full run, passing
apps/api/tests/integration/modules/organisation/ — included in full run, passing
```

## 14. Ruff Results

```
$ .venv/bin/ruff check .
All checks passed!

$ .venv/bin/ruff format --check .
163 files already formatted
```

Clean — zero findings, zero reformatting needed.

## 15. Mypy Results

```
$ .venv/bin/mypy src/hrms
Success: no issues found in 73 source files
```

Clean.

## 16. Import-Lint Results

```
$ .venv/bin/lint-imports
Contracts: 1 kept, 0 broken.
```

Clean — confirms no `core.rbac → modules.employee` (or any other prohibited) dependency was
introduced. `EmployeeService.resolve_visible_employee_ids` remains the single seam every fix
threads through; no logic was duplicated or moved across the `core/rbac` ↔ `modules.employee`
boundary.

## 17. Performance Considerations

No new query shape. Every fix in this session is "pass an already-resolved `DataScope` one hop
further" (router → service) or "call the already-existing `_assert_employee_visible` from one more
write-route call site" — the same single `resolve_visible_employee_ids` call every already-scoped
route already made, at the same point `_assert_employee_exists`-shaped checks already ran. No index
was added; none was needed. SQL shape was not independently re-profiled this session — the plan's
own §20 analysis (single depth-capped recursive CTE for `REPORTEE_TREE`, single indexed lookup for
`REPORTEES`) is unchanged by this session's work, since no resolver code was touched.

## 18. Known Limitations

- `EmployeeAssignmentService.get_assignment_as_of` (the internal cross-module contract for future
  Attendance/Leave/Payroll callers) deliberately still does not assert employee existence or scope
  — unchanged from before this session, matching the plan's own explicit carve-out (§9).
- The `create_assignment` in-scope write test (§12) exercises the `MANAGER_CHANGE`-shaped
  "current row exists" branch, not the `INITIAL`/no-current-row branch, for the REPORTEES-scope
  proof specifically (the manager-link fixture row already occupies the "current" slot) — the
  `INITIAL` branch's scope enforcement is still exercised (by the out-of-scope assertion, which
  uses a fresh `INITIAL` write against `unrelated`), just not paired with a positive in-scope
  `INITIAL` case in the same test. Not a coverage gap in practice: `_assert_employee_visible` runs
  identically before either branch, so this is redundant-path coverage risk, not enforcement risk.

## 19. Open Product Decisions

Carried forward from the plan (§21), not resolved by this implementation, in keeping with the
plan's own explicit instruction not to invent policy where a product decision is named as open:

1. **Write-scope defaults are undefined for every write permission** (should `EMPLOYEE.TERMINATE`/
   `.TRANSFER`/`.PROMOTE`/etc. ever be grantable below `COMPANY`?). The *mechanism* now correctly
   enforces whatever scope a grant carries — this implementation closes exactly that gap and no
   more, leaving the *default* question fully deferrable, as the plan intended.
2. Should `UPDATE_COMPENSATION`/`UPDATE_SENSITIVE` ever be grantable below `COMPANY`? Same
   "mechanism now correct, default still undecided" posture.
3. **Phase 3** — should reassigning `X` to report to `Y` require the caller to have visibility over
   `Y`? Not implemented this session (§10); requires a product decision before any code changes.
4. Statutory's `SELF`-by-default vs. shipped-`COMPANY`-only posture — unchanged, not reopened here
   (already a named, accepted deviation per the plan and the F2/F3 report before it).

## 20. Explicitly Excluded Scope

Everything the plan itself excludes (§24): RLS/superuser remediation, banking encryption,
`sensitive_access_log`, audit-log field redaction, role-seeding, pagination, frontend UX polish,
test non-determinism, `REPORTEE_TREE` read-time cycle detection. Also excluded, per the task
brief's own scope-discipline list: Attendance, Leave, Payroll, new RBAC scope levels,
department/branch/legal-entity scope, approval workflows, tax logic, unrelated hierarchy redesign.
No frontend file was read, modified, or needed to be — the plan's own §18 finding (frontend already
treats the backend as sole authority, no client-side scope assumption exists anywhere) was
re-verified true by inspection of `router.py`'s callers requiring no contract change, and not
independently re-audited beyond that, since no backend response shape or HTTP status contract this
session touches was already relied upon differently by the frontend.

## 21. Recommended Next Step

Per the plan's own sequencing (§22, §25): this work — plus the pre-existing Compensation/Statutory/
Banking/Identity read-side fixes — is now the complete precondition for the Audit's F5
(role-seeding) and Decision H (default `REPORTING_MANAGER`/manager-shaped roles). Do not seed any
non-`COMPANY` `role_permission` row until this change (or an equivalent) is deployed — seeding
before this lands would immediately convert every finding this document closes back into a live
one. Product Decision 3 (§19 item 3, Phase 3) should be resolved before any tenant-facing
role-management UI is built that could let a customer grant `EMPLOYEE.TRANSFER`/`.PROMOTE` at a
non-`COMPANY` scope, since that is the condition under which the still-open proxy-escalation
question becomes reachable in practice.
