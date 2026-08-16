# Reporting Manager Security Audit — `reporting_manager_id` Self-Elevation

**Status:** Investigation complete. Fix implemented (see
`docs/modules/employee/28_REPORTING_MANAGER_SECURITY_IMPLEMENTATION_REPORT.md`).

**Date:** 2026-08-15

**Inputs treated as authoritative:**
- `docs/modules/employee/26_EMPLOYEE_RBAC_DATA_SCOPE_IMPLEMENTATION_REPORT.md` §6/§14/§16 — names
  this exact gap and ships an explicit `xfail` test demonstrating it.
- `docs/modules/employee/25_EMPLOYEE_RBAC_DATA_SCOPE_IMPLEMENTATION_PLAN.md` §17/§22 — the same gap,
  named as explicitly excluded from that task's scope.
- `docs/modules/employee/05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` — Employee Assignment's conceptual
  model (Part C); no write-authorization rule for `reporting_manager_id` is stated there.
- `docs/product/19_RBAC_and_Permission_Matrix.md` — the permission catalogue and default role
  matrix; §5's reference scope-resolution query is what `reporting_manager_id` feeds.
- `docs/modules/employee/09_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_PLAN.md` §14.5 — the existing
  direct-self-reference guard (`manager_id != employee_id`) this task extends.

---

## 1. Exact Vulnerability

`POST /v1/employees/{employee_id}/assignments` accepts a caller-supplied `reporting_manager_id`
with no check on **who** the caller is naming as the new manager. `reporting_manager_id` is the
sole data source for `EMPLOYEE.VIEW`'s `REPORTEES`/`REPORTEE_TREE` data-scope resolution
(`26_...REPORT.md` §3, `EmployeeService.resolve_visible_employee_ids`). A caller who names
**themselves** in this field therefore manufactures a `REPORTEES` relationship over the target
employee, and that relationship is picked up immediately by any *other*, otherwise-correctly-scoped
`EMPLOYEE.VIEW` grant the caller separately holds — a write on one permission (`EMPLOYEE.TRANSFER`)
silently expands what a completely different permission (`EMPLOYEE.VIEW`) resolves to. This is a
horizontal privilege-escalation primitive, not a data-integrity nitpick: it lets a caller grant
*themselves* read access they were never assigned by any role.

## 2. Attack Scenario

1. Tenant has a custom role granting `EMPLOYEE.VIEW` at `REPORTEES` scope, and (the same or a
   second role) `EMPLOYEE.TRANSFER` at `COMPANY` scope (unscoped — assignment writes are not
   data-scoped anywhere in this codebase, per `26_...REPORT.md` §13/§5 last row).
2. The actor holding this role combination can see only their own direct reports via
   `GET /v1/employees` / `GET /v1/employees/{id}` — by design, `REPORTEES` should bound this to
   whatever the *current* reporting hierarchy says.
3. The actor calls `POST /employees/{target_id}/assignments` with
   `{"change_type": "MANAGER_CHANGE", "reporting_manager_id": "<actor's own employee_id>", ...}`
   for a `target_id` who is a complete stranger to them today.
4. Before this fix: the write succeeds (`EMPLOYEE.TRANSFER` is unscoped, so the actor is
   "authorized" to write *some* assignment somewhere); `target` now reports to the actor.
5. The actor's `REPORTEES` grant on `EMPLOYEE.VIEW` now resolves to include `target` — a record
   they had **zero** visibility into a moment earlier, self-granted with no HR/admin action in the
   loop.

This is exactly the scenario `26_...REPORT.md`'s `xfail` test
(`test_reportees_scope_cannot_be_widened_via_self_assignment`) was written to demonstrate.

## 3. Current Endpoint

`POST /v1/employees/{employee_id}/assignments` → `EmployeeAssignmentService.create_assignment`
(`apps/api/src/hrms/modules/employee/service.py:820`). Covers `INITIAL`/`TRANSFER`/`PROMOTION`/
`MANAGER_CHANGE`/`SHIFT_CHANGE` alike — one write path, distinguished only by `change_type`
(`router.py`'s own comment, `03_EMPLOYEE_API_PLAN.md` §2.2).

## 4. Current Permission

`EMPLOYEE.PROMOTE` if `change_type == "PROMOTION"`, else `EMPLOYEE.TRANSFER`
(`router.py:343-347`) — checked via `rbac.has_permission(user.user_id, user.company_id, code)`, a
**boolean** check, not `require_permission()`. This is a distinct code path from every other route
in this module: because the permission code depends on the request body, the router cannot use the
`Depends(require_permission(CODE))` shape the two data-scoped `GET` routes use, so the resolved
`DataScope` this task's predecessor built (`resolve_data_scope`) is never even queried for this
route — the assignment write path has **no** data-scope concept applied to it at all, for any field,
not just `reporting_manager_id` (`25_...PLAN.md` §22, `router.py`'s own module docstring: "Every
other route ... is still not data-scoped").

## 5. Current Data-Scope Behavior

None, by explicit prior design (§4 above). `EMPLOYEE.TRANSFER`/`.PROMOTE` are company-wide for
every existing role (`role_permission.data_scope` defaults to `'COMPANY'`); a tenant *could*
configure a narrower `data_scope` on a `TRANSFER` grant via direct role administration, but nothing
in the write path would honor it even if they did — the column is read for `EMPLOYEE.VIEW`/
`.VIEW_ALL` only, never for `.TRANSFER`/`.PROMOTE`. Extending scope-aware authorization to the
assignment write path in general is explicitly out of this task's scope (see §14, Explicitly
Excluded Scope) — this audit targets only the `reporting_manager_id` field's specific interaction
with `EMPLOYEE.VIEW`'s scope resolution, not a general scoped-write redesign.

## 6. Current Assignment Rules

`EmployeeAssignmentService._assert_manager_reference` (`service.py:801-818`) validates
`reporting_manager_id`/`dotted_line_manager_id` identically: the referenced id must resolve to an
existing, same-tenant, non-deleted `Employee`, and must not equal the assignment's own
`employee_id` (a direct self-reference guard — "an employee cannot manage themselves"). This is the
**only** restriction on the field before this fix. It says nothing about who the *caller* is
relative to the *value being written* — the gap this audit closes.

**A second finding, incidental to this audit:** the existing `xfail` test itself does not actually
reach the vulnerable code path — verified by running it with `--runxfail`. It fails first with
`NO_ACTIVE_EMPLOYMENT` (409), because `target` (created via `POST /employees` only) has no
`Employment` episode covering the write's `effective_from`, and `create_assignment` requires one
(`covering_employment` check, `service.py:833-837`) before validating `reporting_manager_id` at
all. Because the test is `xfail(strict=False)`, this masked the real defect: the test has always
xfailed for the wrong reason, never actually exercising the manager-reference write. The fix
(§ Phase 4 below) corrects the fixture (adds a minimal direct-inserted `Employment` row, mirroring
the file's existing `_assign_manager` direct-insert pattern for `EmployeeAssignment`) so the test
genuinely exercises the attack path.

## 7. Authoritative Documentation Evidence

- `docs/product/19_RBAC_and_Permission_Matrix.md` §5 defines `REPORTEES`/`REPORTEE_TREE` purely in
  terms of `reporting_manager_id` on the *current* `employee_assignment` row — it says nothing
  about who may set that value.
- `docs/product/19_RBAC_and_Permission_Matrix.md` §4's default role matrix shows `EMPLOYEE.TRANSFER`
  -class ("Employee create/edit") access as `●` only for Super Admin/Company Admin/HR Manager/HR
  Executive, and `—` (none) for Reporting Mgr/Team Leader/Employee — suggestive that roles carrying
  narrow `VIEW` scopes (`REPORTEES`/`REPORTEE_TREE`, the "Reporting Mgr"/"Team Leader" rows) are not
  intended to also hold `TRANSFER`. This is a **default-matrix convention**, not a system-enforced
  invariant — `role_permission` is purely additive with no `DENY` concept
  (`26_...REPORT.md` §3 "Multi-grant union"), so nothing stops a tenant from configuring the
  combination the attack scenario requires. The matrix documents an intended default, not a
  constraint the schema or code enforces.
- No document (`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md`, `09_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_PLAN.md`,
  `12_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_REPORT.md`) states a rule for "who may set
  `reporting_manager_id` to what value." This is a genuine documentation silence, not a rule this
  audit is choosing to ignore.

## 8. Authorization or Validation Defect?

**Both, but the actionable fix is a validation-layer guard, not a new authorization mechanism.**
Root cause is an authorization gap in the strict sense — the permission model has no way to express
"may restructure the org chart, but may not name themselves as a beneficiary of that restructuring"
— but closing it with a new permission/scope concept would be exactly the "generic authorization
framework" the task instructs against building, and there is no unresolved ambiguity about the one
case that must always be rejected: **a caller can never have a legitimate reason to name themselves
as `reporting_manager_id` on someone else's — or their own — assignment through this endpoint.**
Every real "I am now Bob's manager" business event is entered by HR/an admin acting *on* the
org chart, not asserted unilaterally by the person who benefits from it — the same reasoning
`09_...PLAN.md` §14.5 already applied to the narrower "can't be your own manager" case. This audit
extends that established, narrow, self-reference-guard pattern by one more disallowed value
(the *caller's* id, not just the *target's* id) rather than inventing new scope/permission
machinery.

## 9. Candidate Fixes

1. **Unconditionally reject `reporting_manager_id == caller_employee_id`** at the point of write,
   regardless of permission/scope held. Extends the existing `_assert_manager_reference` self-
   reference pattern by one case. No new permission, no new scope level, no change to who may call
   the endpoint at all for any other field.
2. Require the caller's `EMPLOYEE.VIEW` grant to already be `COMPANY`-scoped before allowing any
   `reporting_manager_id` write — rejected: this invents a cross-permission coupling
   (`.TRANSFER`'s authority conditioned on `.VIEW`'s scope) that is not in the permission model
   today, is a broad authorization-framework change, and would still not stop a `COMPANY`-scoped-
   `VIEW` actor from self-assigning (they already see everyone — no escalation possible for them,
   but the rule as stated is a coincidence of that case, not a principled fix for the general one).
3. Add a new dedicated permission (e.g. `EMPLOYEE.SET_OWN_AS_MANAGER`) that must be held in addition
   to `.TRANSFER`/`.PROMOTE` — rejected per the task's explicit instruction not to add a permission
   unless the existing model genuinely cannot express the rule; option 1 expresses it without one.
4. Scope the entire assignment write path by data-scope (require the target to be within the
   caller's resolved `.TRANSFER` scope) — rejected: far larger blast radius than this audit's
   subject (would change behavior for every field, not just `reporting_manager_id`), explicitly
   named out of scope by the task ("Do NOT implement new data-scope levels" / preserve existing
   Assignment behavior "where authorized"), and does not, by itself, close the self-elevation gap
   for any role holding a `COMPANY`-scoped `.TRANSFER` grant (the exact configuration in the
   demonstrated attack) — the self-reference guard is still required even if this were also built.

## 10. Recommended Fix

**Option 1.** Reject `reporting_manager_id == caller_employee_id` unconditionally, at write time, in
`EmployeeAssignmentService.create_assignment`, mirroring the existing `manager_id == employee_id`
self-reference guard exactly (same error type, same "field-level validation" placement, same
"direct-reference guard only, not full cycle detection" scope). Applies only to
`reporting_manager_id`, not `dotted_line_manager_id` (which is not part of `REPORTEES`/
`REPORTEE_TREE`'s definition — `26_...REPORT.md` §16 — so has no data-scope consequence to guard
against).

## 11. Product Decisions Required

**None block this fix.** One is flagged as a residual, explicitly-open question for product, not a
blocker: the unconditional rule also prevents a legitimate real-world pattern — a manager onboarding
a new hire directly under themselves, or a `COMPANY_ADMIN` who is also, informally, someone's
manager, recording that fact themselves. Absent any document defining an exception, this audit
recommends the fail-closed default (never allow it via this endpoint; such assignments are entered
by a second party — HR/admin — as today's `INITIAL`/`MANAGER_CHANGE` flows already assume in every
non-attack scenario). If product later wants a narrower, explicitly-authorized self-assignment path,
that is new, separately-scoped work, not a gap in this fix.

## 12. Security Acceptance Criteria

- A caller can never cause `reporting_manager_id == <their own employee_id>` to be written, on any
  employee's assignment, regardless of the permission/scope combination they hold.
- A caller reassigning a *third party's* `reporting_manager_id` to a *different* third party
  continues to succeed exactly as before (no regression to legitimate `TRANSFER`/`MANAGER_CHANGE`
  behavior).
- The existing direct-self-reference guard (`manager_id == employee_id`) is unaffected.
- Cross-tenant `reporting_manager_id` references remain rejected (pre-existing behavior, unaffected
  by this fix, re-verified).
- No change to `EMPLOYEE.VIEW`/`.VIEW_ALL` scope resolution, no new `DataScopeLevel`, no new
  permission code.

## 13. Test Strategy

- Convert the existing `xfail` (`test_reportees_scope_cannot_be_widened_via_self_assignment`) into a
  real passing test — first fixing the fixture gap found in §6 (add a minimal `Employment` row so
  the write reaches the manager-reference check), then asserting the write itself is rejected
  (`422`/`INVALID_REPORTING_MANAGER`), not merely that post-write visibility didn't change.
- Add a first-assignment (`change_type=INITIAL`, no prior current row) variant of the same attack —
  the guard must apply on both the "first assignment" and "update existing assignment" code paths.
- Add a "legitimate manager change" regression test: an employee-actor holding `TRANSFER` reassigns
  a *different* employee's manager to a *third* employee (never themselves) — must still succeed,
  with a correct audit event and effective-dated row.
- Add a cross-tenant `reporting_manager_id` regression test (mirrors the existing
  `test_cannot_reference_other_tenant_branch` pattern) — confirms this pre-existing protection is
  unaffected.
- Re-run the full Employee Assignment and RBAC data-scope suites for regressions.

## 14. Explicitly Excluded Scope

- General data-scoping of the Employee Assignment write path (any field other than
  `reporting_manager_id`) — unchanged, still company-wide for every `TRANSFER`/`PROMOTE` grant.
- `dotted_line_manager_id` — not part of `REPORTEES`/`REPORTEE_TREE`, no guard added.
- Full cycle detection (A→B→C→A) beyond the existing direct self-reference check — unchanged, still
  bounded only by `REPORTEE_TREE`'s depth cap (cost-safe, not correctness-guaranteed,
  `26_...REPORT.md` §3/§6), a pre-existing, already-documented limitation, not newly introduced or
  newly closed by this fix.
- `as_of`/historical scope resolution, including the general (non-self-elevation-specific) fact that
  a future-`effective_from` assignment becomes "current" for `REPORTEES` resolution immediately upon
  insert (no `effective_from <= today` predicate in `get_direct_report_ids`/`get_reportee_tree_ids`).
  This pre-existing gap is **not** a new escalation path introduced by this fix — for the specific
  self-elevation attack, blocking `reporting_manager_id == caller` closes it regardless of
  `effective_from` timing, since the caller can never be named at all. The general early-activation
  behavior for *legitimate* (non-self) reassignments is unchanged and remains an accepted limitation
  of not implementing `as_of` scope resolution (`25_...PLAN.md` §22, `26_...REPORT.md` §13).
- New permissions, new `DataScopeLevel` values, any frontend change, any non-Employee module.
