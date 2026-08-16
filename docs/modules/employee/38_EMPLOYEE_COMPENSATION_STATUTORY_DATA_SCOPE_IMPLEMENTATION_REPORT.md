# Employee Compensation & Statutory — Data-Scope Enforcement (F2 + F3) — Implementation Report

**Status:** COMPLETE.

**Date:** 2026-08-16

**Numbering note:** the task requested this document at `37_...`. That number is already claimed
by a pre-existing, untracked `37_EMPLOYEE_DOMAIN_INTEGRATION_AUDIT.md` (present in the working
tree before this session started). This report is filed as `38_` instead to avoid a collision;
no other document was renamed or renumbered.

**Relationship to prior documents:** this is a security-remediation task, not a redesign, closing
Findings F2 and F3 from `docs/architecture/EMPLOYEE_VERTICAL_PRODUCTION_READINESS_AUDIT.md`
(dated 2026-08-16, read in full before any code was touched). That audit's own findings were
independently re-verified against the current working tree before implementation began — every
file:line citation below was re-checked, not copied from the audit.

---

## 1. Original Vulnerability

Both Compensation's and Statutory's `GET` routes resolved a caller's `DataScope` via
`require_permission(...)` and then discarded it — binding the return value to an
underscore-prefixed, unused parameter (`_scope: Annotated[object, ...]`) instead of passing it
into the service layer. Every query below that point filtered only by `company_id` and the
`employee_id` taken directly from the URL path, with no check that the *caller* was actually
allowed to see that specific employee's record.

**Concrete exploit scenario (proven by a test that existed before this task, asserting the
vulnerable behavior as intended — see §11):** a role granted `EMPLOYEE.VIEW_STATUTORY` at `SELF`
scope, held by a user with no linked `employee_id` at all (so a correctly-enforced `SELF` scope
would resolve to *nothing*), could nonetheless fetch **any other employee's** full PF/ESI/PT/LWF/
tax-regime/director-status record in the same company. The identical bug existed for
`EMPLOYEE.VIEW_COMPENSATION` — any grant, regardless of its configured scope, produced
company-wide CTC visibility.

**Why this was dormant, not yet actively exploited:** every seeded `role_permission` row for
`EMPLOYEE.VIEW_COMPENSATION`/`EMPLOYEE.VIEW_STATUTORY` in every registration path (`seed/
bootstrap.py`, `organisation/service.py:register_company`) defaults to `data_scope='COMPANY'` —
confirmed by grep, no call site passes a narrower value. So today's actual tenants are unaffected
in practice; the gap would activate the moment any tenant configured (or a future role-management
UI created) a narrower grant for either permission — the exact scenario the two locked
architecture decisions below already anticipate as the intended, common case.

## 2. Root Cause

A single, precisely-located defect pattern, independently confirmed by reading the code (not
assumed from the audit):

- **Statutory:** `router.py` (`list_statutories`/`get_statutory`) bound `_scope: Annotated[object,
  Depends(require_permission(EMPLOYEE_VIEW_STATUTORY))]` and never referenced it again;
  `EmployeeStatutoryService.list_statutories`/`.get_statutory` took no scope parameter at all —
  every internal query went through `_assert_employee_exists`, which has no scope concept.
- **Compensation:** the identical shape — `router.py` (`list_compensations`/`get_compensation`)
  bound the same `_scope: Annotated[object, ...]`; `EmployeeCompensationService`'s equivalent
  methods took no scope parameter.
- **Contrast with the one sub-resource that got this right:** `EmployeeBankService` (E-08,
  shipped the same day as Statutory) already implements the correct pattern — its two `GET`
  routes accept `scope: Annotated[DataScope, Depends(require_permission(...))]` and thread it,
  plus the caller's own `employee_id` from the JWT, into a `_assert_employee_visible` helper that
  calls `EmployeeService.resolve_visible_employee_ids` and passes the result into
  `EmployeeRepository.get_employee`'s existing `visible_employee_ids` parameter. This was the
  reference implementation this task reused verbatim for Compensation and Statutory, per
  `docs/architecture/EMPLOYEE_VERTICAL_PRODUCTION_READINESS_AUDIT.md` §20 step 2's explicit
  recommendation ("wire `scope`/`caller_employee_id` through Statutory and Compensation's GET
  routes exactly as Banking already does").

This is a single mechanical pattern applied correctly for Employee's own two routes (`GET
/employees`, `GET /employees/{id}`, per the earlier `25_.../26_...` slice) and Banking, and
incorrectly for Statutory and Compensation — not two independent bugs.

## 3. Whether Statutory's `COMPANY`-Only Posture Was a Real Lock

Investigated before writing any code, per the task's explicit instruction not to silently
"fix" a deliberate design decision.

- `docs/architecture/RBAC_DATA_SCOPE_DECISIONS.md` **Decision E (LOCKED)** states explicitly:
  *"Own statutory / banking (once built, E-07/E-08) — Yes, same pattern as compensation — own
  record, separate permission code (`EMPLOYEE.VIEW_STATUTORY`/`.VIEW_BANKING`), `SELF`-scoped by
  default so an employee can verify their own PF number / bank account."* This is the same
  document, same decision, Banking already implements.
- **Decision F (LOCKED)** states managers get **no** Statutory/Banking visibility by default (a
  permission-grant decision), and that Compensation, if granted to a manager role at all, should
  carry `REPORTEES`/`REPORTEE_TREE` scope, *not* `COMPANY` — directly quoting Doc 19 §7: "Manager
  sees salary? No by default... the tenant may override per role."
- Statutory's own E-07 implementation plan (`29_EMPLOYEE_STATUTORY_IMPLEMENTATION_PLAN.md` §11.3)
  chose `COMPANY`-only as a **plan-level, discretionary** deviation from Decision E — not a
  second, competing locked decision. The architecture-level document that actually carries the
  word "LOCKED" says the opposite.
- No database-level mechanism (`CHECK` constraint, code-level permission-specific override) locks
  `EMPLOYEE.VIEW_STATUTORY` to `COMPANY` specifically; the generic `role_permission.data_scope`
  `CHECK (data_scope IN ('SELF','REPORTEES','REPORTEE_TREE','COMPANY'))` constraint applies
  identically to every permission code. The "lock" was a router/service-layer choice to never
  apply whatever scope was resolved — exactly the resolve-then-discard bug this task exists to
  fix.

**Conclusion:** the task's own instruction — "eliminate the resolve-then-discard bug and
correctly enforce whatever scope the permission actually resolves to" — is the correct reading.
Statutory is now wired identically to Compensation and Banking. Because no seeded role currently
grants `EMPLOYEE.VIEW_STATUTORY` at a non-`COMPANY` scope (§8), this is a **behaviorally inert**
change for every real tenant today — it closes a dormant hole without changing any live actor's
access, exactly the "preserve current behavior" instruction's intent.

## 4. Exact Routes Affected

| Route | Before | After |
|---|---|---|
| `GET /v1/employees/{employee_id}/compensation` | `_scope` discarded; `company_id`-only filter | Resolves `DataScope`, filters via `resolve_visible_employee_ids` |
| `GET /v1/employees/{employee_id}/compensation/{compensation_id}` | Same | Same |
| `GET /v1/employees/{employee_id}/statutory` | Same | Same |
| `GET /v1/employees/{employee_id}/statutory/{statutory_id}` | Same | Same |
| `POST .../compensation`, `POST .../statutory` | `company_id`-only, unscoped | **Unchanged** — write-path scoping intentionally not added (§7) |
| Every Employment/Assignment route | `company_id`-only, unscoped | **Unchanged** — out of this task's scope (F8, tracked separately) |

## 5. Architecture Used

Exact reuse of the existing, already-implemented mechanism — no new resolver, no new scope
levels, no change to `core/rbac`:

```
require_permission(EMPLOYEE_VIEW_COMPENSATION | EMPLOYEE_VIEW_STATUTORY)
        |  (core/rbac, unchanged — RbacService.resolve_data_scope)
        v
    DataScope(levels=frozenset[...])
        |
        v  (router now passes `scope` + `user.employee_id`, previously discarded)
EmployeeCompensationService / EmployeeStatutoryService
        .list_*/.get_* (new `scope`, `caller_employee_id` kwargs, default None)
        |
        v
    _assert_employee_visible(...)          <- new, mirrors EmployeeBankService's method verbatim
        |
        v  (scope=None short-circuits to the exact pre-existing behavior for every other caller)
EmployeeService.resolve_visible_employee_ids(company_id, scope, caller_employee_id)
        COMPANY in scope.levels?       -> None (no filter)
        SELF in scope.levels?          -> add caller_employee_id
        REPORTEE_TREE in scope.levels? -> union recursive-CTE result
        REPORTEES in scope.levels?     -> union direct-report-id result
        |
        v
EmployeeRepository.get_employee(..., visible_employee_ids=...)
        WHERE company_id = :cid AND id = :employee_id
              AND id IN (:visible_ids)   -- only when not None
        |
        v
    None  ->  NotFoundError -> 404          (identical shape to cross-tenant/nonexistent)
    Employee -> proceed to the Compensation/Statutory repository query (unchanged, `company_id`+
                `employee_id` only — the scope check happens once, on the *employee*, before the
                sub-resource is ever queried)
```

No new SQL query was added to Compensation's or Statutory's own repositories — the scope check
is entirely a call to the already-existing `EmployeeRepository.get_employee(...,
visible_employee_ids=...)`, the same method `GET /employees/{id}` and Banking already use. Each
service now holds an `EmployeeService` instance (`self._employee_service =
EmployeeService(session, settings)`), matching `EmployeeBankService`'s existing pattern exactly.

## 6. Compensation Behavior by Scope

| Scope | Behavior |
|---|---|
| `SELF` | Sees only their own compensation record (requires their JWT `employee_id` to equal the path `employee_id`); any other employee -> `404`. |
| `REPORTEES` | Sees direct reports' compensation only (one level, current `reporting_manager_id`); does **not** implicitly include the caller's own record (`SELF` and `REPORTEES` are not nested — matches the existing, unmodified union semantics in `resolve_visible_employee_ids`). |
| `REPORTEE_TREE` | Transitive closure of `REPORTEES`, depth-capped at 20 (unchanged resolver, unmodified). |
| `COMPANY` | Unchanged — full tenant-wide visibility, identical to pre-fix behavior. |
| No `employee_id` on JWT + `SELF`/`REPORTEES`/`REPORTEE_TREE` grant | Fails closed — empty visible set, never falls back to `COMPANY` (unmodified `resolve_visible_employee_ids` behavior, now actually reachable through this route for the first time). |

No new semantics were invented: every behavior above is `resolve_visible_employee_ids`'s existing,
already-tested logic from the `25_...`/`33_...` slices, now reachable through two more routes.

## 7. Statutory Behavior by Scope

Identical table to §6 — Statutory now uses the exact same mechanism, with no Statutory-specific
branching. `RBAC_DATA_SCOPE_DECISIONS.md` Decision F recommends managers hold **no** Statutory
grant at all by default (a permission-*grant* decision, not enforced by this code change — no
role currently holds `EMPLOYEE.VIEW_STATUTORY` at any non-`COMPANY` scope, seeded or otherwise);
if a tenant does grant it at `REPORTEES`/`REPORTEE_TREE` anyway, the resolver now honors that
choice rather than silently widening it to `COMPANY` (proven by
`test_view_statutory_reportees_scope_cannot_see_unrelated_employee`, §11).

## 8. API Behavior for Out-of-Scope Records

Unchanged convention, verified still holds: an out-of-scope target on the detail route returns
`404`, identical in shape (`{"error":{"code":"NOT_FOUND",...}}`) to a nonexistent ID or a
cross-tenant ID — a client cannot distinguish the three cases, matching every other scoped route
in this module (`GET /employees/{id}`, Banking). The list route silently omits an out-of-scope
row — no distinct status code, no error, `[]` for an empty scope. No response schema changed; no
new request parameter was added. `as_of` continues to select *which historical row*, entirely
independent of the scope check, which runs first and unconditionally (§10) — an out-of-scope
caller supplying `as_of` still gets `404` before any effective-dating logic runs
(`test_view_compensation_as_of_cannot_bypass_scope`, §11).

## 9. Tenant/RLS Interaction

Unaffected. `get_tenant_context` still runs before `require_permission` on every route, still
404s on a company/JWT mismatch before any permission or scope logic executes. Every new/modified
query is still filtered by `company_id` explicitly (belt-and-suspenders, unchanged convention).
`role_permission` carries no RLS policy (a join table, relies on its parent `role`'s tenant
scoping) — this task did not add or need one. Verified against the live F1 role
(`SELECT current_user, rolsuper, rolbypassrls` — `hrms_app | f | f`, confirmed both before and
after the full test run, §14) that nothing in this change assumes or requires superuser/BYPASSRLS
privileges; every query added or modified goes through the same `AsyncSession` every other query
in this module already uses.

## 10. Query/Performance Approach

No N+1, no in-Python filtering, no loading of full Compensation/Statutory tables to filter after
the fact. The scope check is a single additional query — `EmployeeRepository.get_employee(...,
visible_employee_ids=...)` — which was already being called once per request by every one of
these four routes anyway, via `_assert_employee_exists`; this task only replaces that call with
`_assert_employee_visible`, which conditionally resolves `visible_employee_ids` (zero extra
queries for `SELF`, one indexed lookup for `REPORTEES`, one recursive CTE for `REPORTEE_TREE`,
zero for `COMPANY`) and passes it into the *same* `get_employee` call, which applies the
`Employee.id.in_(visible_employee_ids)` predicate at the SQL layer. No new index was needed — the
partial index this predicate's `REPORTEES`/`REPORTEE_TREE` resolution already relies on
(`employee_assignment_manager_idx`) was added by the E-04 migration and reused unchanged. The
Compensation/Statutory repositories themselves were not modified at all — their own queries are
unchanged, still filtered by `company_id` + `employee_id` only, since the scope check now happens
one layer up, on the employee itself, before either repository is ever touched.

## 11. Tests Added

**Modified (flipped from asserting the vulnerability to asserting the fix):**
- `tests/integration/modules/employee/test_employee_statutory.py`:
  `test_view_statutory_ignores_non_company_data_scope` — this test existed *before* this task and
  positively asserted the exploit (a `SELF`-scoped grant with no `employee_id` could read another
  employee's full statutory record, `200`). It has been replaced by
  `test_view_statutory_self_scope_no_employee_id_sees_nothing`, asserting the corrected, secure
  outcome (`404`) for the identical scenario. This is a direct instruction of this task (the
  security property under test flipped from "prove the bug" to "prove the fix"), not an
  unrelated weakening — no other assertion in the file was touched, and no other test was
  deleted.

**New — Statutory** (`test_employee_statutory.py`):
- `test_view_statutory_self_scope_sees_own_record_only` — own record visible (list + direct ID
  detail lookup), another employee's record `404`.
- `test_view_statutory_self_scope_no_employee_id_sees_nothing` — fail-closed, replaces the old
  vulnerable-behavior test (above).
- `test_view_statutory_reportees_scope_cannot_see_unrelated_employee` — a `REPORTEES`-scoped
  grant sees a direct report, not an unrelated employee, and not the manager's own record either.
- `test_view_statutory_company_scope_sees_any_employee` — `COMPANY` scope regression, unchanged.

**New — Compensation** (`test_employee_compensation.py`):
- `test_view_compensation_self_scope_sees_own_record_only` — same shape as Statutory's, plus an
  explicit direct-ID-lookup assertion.
- `test_view_compensation_self_scope_no_employee_id_sees_nothing` — fail-closed.
- `test_view_compensation_reportees_scope_sees_direct_reports_only` — `REPORTEES` scope,
  unrelated employee and the manager's own record both correctly `404`.
- `test_view_compensation_company_scope_sees_any_employee` — `COMPANY` scope regression.
- `test_view_compensation_as_of_cannot_bypass_scope` — `?as_of=` cannot be used to bypass an
  out-of-scope `404`.

Every new test exercises the **actual HTTP route** (`client.get(...)`) with a real registered
tenant, a real permission-scoped second user (JWT + DB-backed `Role`/`RolePermission`/`UserRole`),
and a real target employee — proving the security property end-to-end (`permission granted` +
`scope insufficient` = `resource inaccessible`), not just the underlying resolver function in
isolation (which was already tested by the `25_.../26_...` slice and is unmodified here). The
`REPORTEES` tests insert a minimal `EmployeeAssignment` row directly via the ORM, mirroring
`test_employee_data_scope.py::_assign_manager`'s established pattern, and clean it up in their own
`finally` block (`DELETE FROM employee_assignment WHERE company_id = :cid`) before the shared
`_teardown` helper runs, since neither test file's existing teardown touches that table.

**Cross-tenant regression:** `test_cannot_get_statutory_from_other_tenant`,
`test_cannot_list_statutory_from_other_tenant_employee`, and Compensation's equivalent pair —
pre-existing, unmodified, re-run and confirmed still passing (§14).

## 12. Full Validation Results

```
Targeted (Compensation + Statutory + Banking + Employee data-scope):
  102 passed, 0 failed

Employee + Organisation + RBAC-adjacent regression
  (tests/integration/modules/employee/, tests/unit/modules/employee/,
   tests/integration/modules/organisation/, tests/security/):
  522 passed, 0 failed

Full backend suite, run twice (determinism check, per F1's own "610 passed, deterministic"
baseline claim):
  Run 1: 618 passed, 0 failed
  Run 2: 618 passed, 0 failed
  (618 = 610 baseline + 8 net new: +4 Statutory [1 removed, 4 net-new (5 added - 1 removed)]
   + 5 Compensation added — net +8, both runs identical)

ruff check .            All checks passed
ruff format --check .   163 files already formatted
mypy src                Success: no issues found in 73 source files
lint-imports             1 kept, 0 broken

Runtime DB role (re-verified after the full test run):
  current_user       = hrms
  hrms_app.rolsuper     = f
  hrms_app.rolbypassrls = f
```

## 13. Files Changed

**Modified:**
```
apps/api/src/hrms/modules/employee/service.py
    EmployeeCompensationService: + _assert_employee_visible, + scope/caller_employee_id kwargs
        on list_compensations/get_compensation, + self._employee_service
    EmployeeStatutoryService: identical additions
    EmployeeBankService: docstring correction only (no behavior change) — removed a now-inaccurate
        "unlike Statutory" comparison

apps/api/src/hrms/modules/employee/router.py
    list_compensations/get_compensation/list_statutories/get_statutory: now inject
        AuthenticatedUser, bind DataScope (not object), pass scope + caller_employee_id through
    Module docstring + section comments: corrected to describe the fixed behavior

apps/api/tests/integration/modules/employee/test_employee_compensation.py
    + data_scope/caller_employee_id params on _create_permission_scoped_user
    + 5 new tests (§11)

apps/api/tests/integration/modules/employee/test_employee_statutory.py
    + data_scope param already present, reused
    1 test replaced (vulnerable-behavior assertion -> secure-behavior assertion)
    + 3 further new tests (§11)
    Module docstring: corrected to describe the fixed behavior
```

**New:**
```
docs/modules/employee/38_EMPLOYEE_COMPENSATION_STATUTORY_DATA_SCOPE_IMPLEMENTATION_REPORT.md
    (this document)
```

**No migration was created.** This was purely an application-layer fix — no schema change was
needed; `role_permission.data_scope` already existed from the `25_...` slice's migration, and
`EmployeeRepository.get_employee`'s `visible_employee_ids` parameter already existed from the same
slice, plus Banking's own reuse of it.

**Confirmed untouched** (`git diff --stat` re-checked after implementation): Banking, Assignment,
Employment, Employee identity, Payroll (does not exist), Attendance (does not exist), Leave (does
not exist), Exit, frontend, `sensitive_access_log` (does not exist), salary structure, payroll
calculations, `core/rbac` (no change to the resolver itself — only Employee's router/service
consume it differently), role seeding, permission catalogue, encryption. Every other file shown as
modified/untracked in `git status` at the start of this task (F1's role-separation work, the
E-06/E-07/E-08/E-09 slices, the RBAC data-scope slice, the Employee frontend) predates this session
and was not touched by it.

## 14. Known Limitations

- **Write-path scoping was deliberately not added.** `create_compensation`/`create_statutory`
  remain `COMPANY`-wide (permission-gated, not scope-gated), matching every other write route in
  this module (`create_bank`, `create_employee`, `update_employee`, Assignment/Employment
  writes). No source document requires write-scope enforcement for these two resources, and the
  task's own instructions direct against inventing it without an explicit requirement. This
  mirrors Finding F9 in the readiness audit — a known, separately-tracked gap, not newly
  introduced or newly closed by this task.
- **Every other Employment/Assignment `GET` route remains unscoped** (Finding F8) — this task's
  scope was explicitly limited to Compensation and Statutory reads; Employment/Assignment history
  is still readable by ID regardless of the caller's configured scope. Not touched, per the
  task's explicit exclusion list.
- **No seeded role currently grants `EMPLOYEE.VIEW_COMPENSATION`/`EMPLOYEE.VIEW_STATUTORY` at
  anything other than `COMPANY`** — this fix is dormant-hole-closing, not a live behavior change
  for any existing tenant (Finding F5's role-seeding gap remains fully open, unchanged, out of
  this task's scope).
- **`as_of`/historical scope resolution is not implemented** — scope is always resolved against
  "now," matching Employee's own two routes and Banking. A caller's *current* manager
  relationship gates a *historical* Compensation/Statutory row's visibility; there is no way to
  ask "who could see this record as of a past date" through these routes. Unchanged from the
  `25_...` slice's own stated limitation.
- **`sensitive_access_log` still does not exist** (Finding F7) — a successful, in-scope read of
  Compensation/Statutory data still produces no read-path audit record. Unaffected by this task.
- **Plaintext banking (Finding F4) and raw-value audit-log embedding (Finding F11)** are
  unaffected — this task did not touch Banking or the audit-snapshot convention.

## 15. Unrelated Security Findings Discovered But Not Fixed

None discovered beyond what `EMPLOYEE_VERTICAL_PRODUCTION_READINESS_AUDIT.md` already documents.
No new finding surfaced during this task's own code reading that isn't already tracked in that
audit under an existing F-number. Two items worth restating explicitly, since they were directly
adjacent to the code this task touched, but are out of this task's scope per its own instructions:

- **F8** — Employment/Assignment `GET` routes remain unscoped (same shape as F2/F3 was, one layer
  over in the same router file). Recommended next, per the audit's own remediation sequence.
- **F9** — no write-path scoping exists anywhere in this module, including the two write routes
  this task's services now sit next to (`create_compensation`, `create_statutory`).

## 16. Recommended Next Step

Per `EMPLOYEE_VERTICAL_PRODUCTION_READINESS_AUDIT.md` §20's own recommended sequence, this task
(step 2) is now complete. The next items in that sequence, in order:

1. **F8 + F9** — extend the identical `scope`/`caller_employee_id` pattern this task just applied
   to Employment/Assignment's `GET` routes, and add write-path scope enforcement across the
   module (Compensation/Statutory/Employment/Assignment write routes) — closing the dormant IDOR
   before F5 can safely ship.
2. **F5** — seed the three Decision H roles (`EMPLOYEE`, `REPORTING_MANAGER`, `HR_ADMIN`) — only
   after step 1, so seeding activates correct, already-enforced behavior rather than a live
   exposure through the still-open F8/F9 gaps.
3. **F6** — the test suite's shared, non-isolated `seeded_plan_catalogue` fixture; not
   independently re-reproduced in this task's own two full-suite runs (both deterministic at 618),
   but not re-verified fixed either — treat as still open.
4. **F4 + F7** — banking encryption and `sensitive_access_log`, both already-locked Payroll
   preconditions, unaffected by this task.
