# Reporting Manager Security Hardening — Implementation Report

**Status:** COMPLETE.

**Date:** 2026-08-15

**Scope shipped:** a single, unconditional guard in `EmployeeAssignmentService.create_assignment` —
`reporting_manager_id` may never be set to the acting user's own `employee_id`, regardless of which
permission or data-scope authorized the write. Closes the self-elevation gap named and demonstrated
(as an accepted `xfail`) by `docs/modules/employee/26_EMPLOYEE_RBAC_DATA_SCOPE_IMPLEMENTATION_REPORT.md`
§6/§14/§16. Full investigation: `docs/modules/employee/27_REPORTING_MANAGER_SECURITY_AUDIT.md`.

---

## 1. Vulnerability

`POST /v1/employees/{employee_id}/assignments` accepted a caller-supplied `reporting_manager_id`
with no check on **who** the caller was naming as the new manager. Since `reporting_manager_id` is
the sole data source for `EMPLOYEE.VIEW`'s `REPORTEES`/`REPORTEE_TREE` data-scope resolution, a
caller holding an unscoped `EMPLOYEE.TRANSFER` grant (the normal, documented shape of that
permission — assignment writes are not data-scoped anywhere in this codebase) plus a narrower
`REPORTEES`-scoped `EMPLOYEE.VIEW` grant could name **themselves** as an unrelated employee's
manager, and thereby self-grant `EMPLOYEE.VIEW` visibility they were never assigned by any role — a
write on one permission silently expanding what a completely different permission resolves to.

## 2. Root Cause

`_assert_manager_reference` (`service.py`) validated only that `reporting_manager_id` referenced an
existing, same-tenant `Employee`, and was not the assignment's own `employee_id` (a narrow, existing
direct-self-reference guard: "an employee cannot manage themselves"). It never compared the
referenced id against the **caller's** own `employee_id`. Because the assignment write path (unlike
the two `GET` routes hardened in the prior slice) checks its permission via a raw boolean
`rbac.has_permission(...)`, not `require_permission()`, no `DataScope` is resolved for this route at
all — there was no scope-aware backstop of any kind on this field.

**Incidental finding:** the existing `xfail` test that was meant to demonstrate this never actually
reached the vulnerable code path — it failed first with an unrelated `NO_ACTIVE_EMPLOYMENT` (409),
because the test's `target` employee had no `Employment` episode covering the write's
`effective_from`, and `create_assignment` requires one before validating `reporting_manager_id` at
all. `xfail(strict=False)` silently absorbed this, masking the real defect. Confirmed by running the
test with `--runxfail` before any fix was applied (`27_...AUDIT.md` §6).

## 3. Fix

One guard, in `EmployeeAssignmentService.create_assignment` (`service.py:839-851`), evaluated before
any other business-rule check or DB write:

```python
if (
    body.reporting_manager_id is not None
    and caller_employee_id is not None
    and body.reporting_manager_id == caller_employee_id
):
    raise InvalidReportingManagerError(
        field="reporting_manager_id",
        message="reporting_manager_id cannot be set to the acting user's own employee_id",
    )
```

- Fires only when the request body **explicitly** sets `reporting_manager_id` — a value silently
  carried forward from the current row (an omitted field on an unrelated update, e.g. a pure branch
  transfer) never triggers it, so no legitimate no-op update is affected.
- Fires on both the "first assignment" (`current is None`, `change_type=INITIAL`) and "update an
  existing assignment" (`MANAGER_CHANGE`/`TRANSFER`/etc.) code paths — placed before the
  `current`-vs-`None` branch entirely.
- Reuses the existing `InvalidReportingManagerError` (422, `INVALID_REPORTING_MANAGER`) rather than
  introducing a new error type — the same error the pre-existing "can't be your own manager"
  self-reference guard already raises; this is one more disallowed value on the same field, not a
  new concept.
- `caller_employee_id` is threaded from `AuthenticatedUser.employee_id` (already decoded from the
  JWT at authentication time, already injected into the router for the permission check) through
  `router.py`'s `create_assignment` → `service.create_assignment(..., caller_employee_id=user.employee_id)`.
  New parameter, keyword-only, defaulting to `None` — non-breaking for the method's only call site.
- Does **not** apply to `dotted_line_manager_id` — not part of `REPORTEES`/`REPORTEE_TREE`'s
  definition, so has no data-scope consequence to guard against (`27_...AUDIT.md` §14).

## 4. Authorization Model

Unchanged. No new permission code, no new `DataScopeLevel`, no scope resolution added to the
assignment write path. `EMPLOYEE.TRANSFER`/`.PROMOTE` remain company-wide, unscoped, exactly as
before — the fix is a field-level write-time validation rule, not a new authorization layer, per the
task's explicit instruction not to build a generic authorization framework.

## 5. Self-Elevation Behavior

- A caller can never cause `reporting_manager_id == <their own employee_id>` to be written, for any
  employee, on any code path, under any permission/scope combination — verified by
  `test_reportees_scope_cannot_be_widened_via_self_assignment` (update path) and
  `test_self_elevation_guard_applies_to_first_assignment` (create path).
- A caller reassigning a **third party's** manager to a **different third party** is entirely
  unaffected — verified by `test_legitimate_manager_change_to_third_party_still_succeeds` (succeeds,
  correct response body, correct `ASSIGNMENT_CHANGED` audit row).

## 6. Hierarchy Behavior

- The pre-existing direct self-reference guard (`manager_id == employee_id`, "an employee cannot
  manage themselves") is untouched — still enforced, still covered by
  `test_create_assignment_reporting_manager_self_reference_rejected` (unmodified, still passing).
- Full cycle detection (A→B→C→A) beyond direct self-reference is **not** added — unchanged,
  pre-existing, already-documented limitation (`REPORTEE_TREE`'s depth cap bounds query cost, not
  correctness — `26_...REPORT.md` §3/§6). Not newly introduced or newly closed by this fix; this
  task's title and scope name self-elevation specifically, not general cycle prevention.

## 7. Tenant Isolation

Unaffected, re-verified. `_assert_manager_reference`'s existing tenant-scoped `Employee` lookup
already rejected a cross-tenant `reporting_manager_id` before this fix; a new regression test,
`test_cannot_reference_other_tenant_reporting_manager`, makes this explicit (previously untested by
name, though covered incidentally by the same code path as `test_cannot_reference_other_tenant_branch`).

## 8. Audit Behavior

Unaffected. The guard raises before any DB write, so no audit row is written for a rejected
self-elevation attempt — matching the existing convention for every other validation error on this
endpoint (e.g. `InvalidBranchReferenceError`, the pre-existing self-reference guard) — none of them
write a `sensitive_access_log`/audit entry either. Legitimate writes continue to produce exactly the
same `ASSIGNMENT_CHANGED` audit event as before, unchanged code path, verified by
`test_legitimate_manager_change_to_third_party_still_succeeds`.

## 9. Tests

**New** (`tests/integration/modules/employee/test_employee_data_scope.py`):
- `test_reportees_scope_cannot_be_widened_via_self_assignment` — converted from the prior slice's
  `xfail`. Fixture gap fixed (added a direct-inserted `Employment` row via the new
  `_setup_active_employment` helper, so the write actually reaches manager-reference validation).
  Now asserts the write itself is rejected (`422`/`INVALID_REPORTING_MANAGER`), not merely that
  post-write visibility is unchanged.
- `test_self_elevation_guard_applies_to_first_assignment` — same attack on the `change_type=INITIAL`
  path.
- `test_legitimate_manager_change_to_third_party_still_succeeds` — regression: an employee-actor
  holding `EMPLOYEE.TRANSFER` reassigns a different employee's manager to a third employee; succeeds,
  correct audit event, correct response body.

**New** (`tests/integration/modules/employee/test_employee_assignment.py`):
- `test_cannot_reference_other_tenant_reporting_manager` — cross-tenant regression, named explicitly
  (previously only incidentally covered).

**Unmodified, still passing:**
`test_create_assignment_reporting_manager_self_reference_rejected` and the full pre-existing
Employee Assignment / RBAC data-scope suites — no existing assertion was weakened, deleted, or
changed.

**Results:**
```
tests/integration/modules/employee/test_employee_data_scope.py:  15 passed (was 12 passed, 1 xfailed)
tests/integration/modules/employee/test_employee_assignment.py:  32 passed (was 31 passed)
Full backend suite:                                              507 passed, 0 failed, 0 xfailed
                                                                   (was 503 passed, 1 xfailed)
```

No existing test was modified, weakened, or deleted. The known-gap `xfail` is gone — it is now a
genuine passing security test.

## 10. Validation

```
pytest (full suite):        507 passed, 0 failed, 0 xfailed
ruff check:                 All checks passed
ruff format --check:        156 files already formatted
mypy (src):                 Success: no issues found in 73 source files
lint-imports:                1 kept, 0 broken
```

Development database: no migration was required for this fix (no schema change — the guard is
pure application-layer validation), so no migration/schema check applies.

## 11. Files Changed

**New:**
```
docs/modules/employee/27_REPORTING_MANAGER_SECURITY_AUDIT.md
docs/modules/employee/28_REPORTING_MANAGER_SECURITY_IMPLEMENTATION_REPORT.md (this document)
```

**Modified, this task:**
```
apps/api/src/hrms/modules/employee/service.py     (+13 lines — self-elevation guard, +1 param)
apps/api/src/hrms/modules/employee/router.py       (+1 line — caller_employee_id passthrough)
apps/api/src/hrms/modules/employee/exceptions.py  (docstring update only, no behavior change)
apps/api/tests/integration/modules/employee/test_employee_data_scope.py
  (xfail converted to passing test + fixture fix + 2 new tests + helper + cleanup extension)
apps/api/tests/integration/modules/employee/test_employee_assignment.py (+1 new test)
```

**Confirmed untouched by this task** (verified via `git diff` against this session's own edits):
every other Employee route/service/repository method, every non-Employee module, every frontend
file, `organisation/service.py`, `seed/bootstrap.py`. No migration file was added or modified. Every
file shown as already modified/untracked in `git status` at the start of this task (the prior RBAC
data-scope slice's own uncommitted work — `identity.py`, `rbac/*`, `employee/repository.py`, the
compensation/employment test files, the architecture docs) was pre-existing and is not part of this
task's diff.

## 12. Known Limitations

- The unconditional rule also blocks a legitimate real-world pattern — a manager onboarding a new
  hire directly under themselves, or a `COMPANY_ADMIN` who is informally someone's own manager
  recording that fact via this endpoint. No document defines an exception for this; the fail-closed
  default was chosen deliberately (`27_...AUDIT.md` §11) over inventing an undocumented carve-out.
- General data-scoping of the Employee Assignment write path (any field other than
  `reporting_manager_id`) is unchanged — `EMPLOYEE.TRANSFER`/`.PROMOTE` remain company-wide for
  every existing role, exactly as before this task and before the prior RBAC data-scope slice.
- Full cycle detection beyond direct self-reference is not implemented — pre-existing, unchanged,
  already-documented limitation (§6 above).
- The general (non-self-elevation) fact that a future-`effective_from` assignment becomes "current"
  for `REPORTEES`/`REPORTEE_TREE` resolution immediately upon insert (no `effective_from <= today`
  predicate in the resolver) is unchanged. For the specific self-elevation attack this task targets,
  blocking `reporting_manager_id == caller` closes it regardless of `effective_from` timing, since
  the caller can never be named as manager at all through this endpoint. The general early-activation
  behavior for legitimate (non-self) reassignments remains an accepted, pre-existing limitation of
  not implementing `as_of` scope resolution (`25_...PLAN.md` §22, `26_...REPORT.md` §13) — not a new
  path introduced or newly closed by this fix.

## 13. Open Decisions

None block this fix. One is flagged for product, non-blocking (`27_...AUDIT.md` §11): whether a
narrower, explicitly-authorized self-assignment path should exist for the legitimate "manager
onboards their own new report" pattern named in §12 above. Absent a product decision, the fail-closed
default (never via this endpoint) stands.

## 14. Explicit Exclusions

Restated from the task's own instructions and `27_...AUDIT.md` §14 — none of the following were
built or changed:
- New permissions, new `DataScopeLevel` values, any generic/config-driven authorization framework.
- Data-scoping of the Employee Assignment write path for fields other than `reporting_manager_id`.
- Full cycle detection (only the pre-existing direct self-reference check remains).
- `as_of`/historical data-scope resolution.
- Any RBAC redesign, any frontend change, any Statutory/Banking/Attendance/Leave/Payroll module work.
- No commit was made — working tree left as-is per the task's instruction.

## 15. Recommended Next Step

If product wants managers to be able to onboard direct reports under themselves through this
endpoint (§12/§13), that is new, separately-scoped work: likely a narrower rule such as "self-
assignment is allowed only on an employee's very first assignment (`current is None`), never on an
existing employee being reassigned" — but this is a genuine product decision, not something this
task should infer. Absent that decision, no further action is required to close the vulnerability
this task targeted.
