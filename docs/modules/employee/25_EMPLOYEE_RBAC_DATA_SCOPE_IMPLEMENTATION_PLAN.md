# Employee RBAC Data-Scope — Implementation Plan (SELF / REPORTEES / REPORTEE_TREE)

**Status:** Implementation plan, locking the exact design before code is written. No application
code, migrations, or tests exist yet at the time this document was written.

**Date:** 2026-08-15

**Inputs treated as authoritative:**
- `docs/modules/employee/24_EMPLOYEE_RBAC_DATA_SCOPE_AUDIT.md` — the FACT findings (re-verified
  independently, not re-verified a third time here).
- `docs/architecture/RBAC_DATA_SCOPE_DECISIONS.md` — resolves the product decisions this
  implementation depends on (scope attaches to `role_permission`, `SELF`/`REPORTEES`/
  `REPORTEE_TREE` derive from Employee Assignment, `404` not `403` on scope violation, etc.).
  This document does not re-litigate those decisions.
- `docs/architecture/RBAC_DATA_SCOPE_IMPLEMENTATION_PLAN.md` — the architecture-level plan
  written from the same decisions. **One correction to that document's design is made here**,
  found only while inspecting `apps/api/.importlinter` during this implementation pass — see
  §7 below. Everything else in that document is carried forward unchanged.

No unresolved product decision blocks this implementation — `PD-RBAC-1` (scope location) and
the portion of `PD-RBAC-2` needed for `SELF`/`REPORTEES`/`REPORTEE_TREE` (derived from own
assignment) are both resolved in the Decisions document. The only decision left genuinely open
(`DEPARTMENT`/`BRANCH`/`LEGAL_ENTITY` derivation) is out of this task's scope entirely (Decision
C), so it does not block anything below.

---

## 1. Current Architecture

```
JWT → get_current_user()               (core/auth — decodes employee_id from JWT, unchanged)
    → get_tenant_context()             (core/tenancy — 404 on header/JWT company mismatch, unchanged)
    → require_permission(code)         (core/rbac — DB-backed permission check, unchanged gate)
        → returns DataScope(level=COMPANY)   ← hard-coded, unconditional, unused
    → repository query filtered by company_id only
```

Verified directly (not assumed from the Audit):
- `RbacRepository.get_permission_codes_for_user`
  (`apps/api/src/hrms/core/rbac/service.py:10-30`) joins
  `permission → role_permission → role → user_role → user_company`, filtered by
  `user_company.status = 'ACTIVE'`. This is the join `resolve_data_scope` (§7) extends, not
  replaces.
- `_check_permission` (`apps/api/src/hrms/core/rbac/dependencies.py:19-29`) calls
  `rbac.has_permission(...)`, raises `PermissionDeniedError` (`403`) on failure, and on success
  returns the literal constant `DataScope(level=DataScopeLevel.COMPANY)` — line 29, not computed.
- Every router binds that return value to `_scope: Annotated[object, Depends(require_permission(...))]`
  and never reads it again (confirmed by grep across `employee/router.py`,
  `organisation/router.py`, `identity/router.py`).
- `AuthenticatedUser.employee_id` (`core/auth/types.py:10`) is decoded from the JWT
  (`core/auth/dependencies.py:27`) on every request but is never read by any authorization check
  today.
- `employee_assignment.reporting_manager_id` / `.dotted_line_manager_id`
  (`employee/models.py:138-143`) are populated and FK-validated but appear in no `WHERE` clause
  anywhere in the codebase except the write-path FK-existence check (`service.py:713-730`).

---

## 2. Current Failure Mode

`GET /v1/employees/{id}` requires only `EMPLOYEE.VIEW`; `GET /v1/employees` requires only
`EMPLOYEE.VIEW_ALL`. Neither route consults the target employee's relationship to the caller.
Concretely: any role holding `EMPLOYEE.VIEW` — including a role intended as a narrow "Reporting
Manager" grant — can fetch **any** employee record in the company by ID, and any role holding
`EMPLOYEE.VIEW_ALL` can list **every** employee in the company, regardless of what that role's
name or intent implies. This is not a partial/edge-case gap; it is the complete absence of the
third authorization layer (`authentication` → `permission` → **`data scope`**, Audit §1).

---

## 3. Scope Model

Four `DataScopeLevel` values after this change: `SELF`, `REPORTEES`, `REPORTEE_TREE`, `COMPANY`
(Decisions doc, Decision C). `DEPARTMENT`/`BRANCH`/`LEGAL_ENTITY`/`ALL_COMPANIES` are **not**
added to the enum in this task — adding them now, even as unused placeholders, would be scope the
Strict Exclusions explicitly name (`branch scope`, `department scope`, `legal entity scope`,
`company scope redesign`). The enum can be extended again, cheaply, whenever those levels are
actually built.

Scope is attached per `(role, permission)` grant — a new `role_permission.data_scope` column
(Decisions doc, Decision A) — not per role and not per user. A single role can therefore grant
`EMPLOYEE.VIEW` at `REPORTEES` while granting `EMPLOYEE.VIEW_COMPENSATION` (unrelated to this
task, not touched) at a different or no scope at all — this granularity is why the column lives
on `role_permission`, not `role`.

---

## 4. `SELF` Semantics

- Resolves to exactly one employee ID: the caller's own `AuthenticatedUser.employee_id`.
- `GET /employees/{own_id}` → `200`. `GET /employees/{any_other_id}` → `404`.
- `GET /employees` under a `SELF`-scoped `EMPLOYEE.VIEW_ALL` grant → a one-item list containing
  only the caller's own record (not an error — a role that is unusually configured to hold
  `VIEW_ALL` at `SELF` scope still gets a well-defined, narrowed answer, not undefined behavior).
- `SELF` does **not** implicitly grant `REPORTEES` or vice versa — a role holding only `REPORTEES`
  cannot see its own holder's record through that grant (see §5). This matches Decision D's
  literal reading: "direct reports only," not "direct reports plus self."
- If the caller has no `employee_id` on their JWT (a user with no corresponding `Employee` row —
  e.g., a `COMPANY_ADMIN` who registered the company but was never entered as an employee) and
  some grant resolves to `SELF`, the resolved visible set for that grant is **empty**, never a
  wildcard and never `COMPANY` (§10, fail-closed).

---

## 5. `REPORTEES` Semantics

- Resolves to the set of employee IDs whose **current** `employee_assignment` row
  (`effective_to IS NULL`) has `reporting_manager_id` equal to the caller's `employee_id`.
- One level only — a report's own reports are not included (Phase 2's worked example: "A cannot
  see employees reporting to B or C").
- Does not include the caller's own record (see §4).
- An employee assignment row's `reporting_manager_id` is only ever compared against the
  **current** date in this task — the two in-scope routes (`GET /employees`, `GET /employees/{id}`)
  have no `as_of` parameter, unlike Employment/Assignment/Compensation's list endpoints. As-of
  (historical) scope resolution is explicitly out of scope here (§22) and is a straightforward,
  separately-sequenced follow-up once scope reaches those effective-dated endpoints.

---

## 6. `REPORTEE_TREE` Semantics

- The transitive closure of the `REPORTEES` relation, computed by a recursive query over
  `employee_assignment.reporting_manager_id`, depth-capped at 20 (matches
  `docs/product/19_RBAC_and_Permission_Matrix.md §5`'s reference implementation).
- The depth cap bounds query cost; it does not detect or reject a cycle. A cyclic or
  pathologically deep chain is silently truncated at depth 20 — this is a safety property (query
  terminates, doesn't hang), not a correctness guarantee (Decisions doc, Decision D). No write-time
  cycle-prevention guard is added in this task (§22 — explicitly excluded, tracked as a known
  limitation).
- `REPORTEE_TREE` for a given root is always a superset of `REPORTEES` for the same root (depth 1
  is literally the `REPORTEES` result) — if a caller's resolved grants include both levels for the
  same permission, only the `REPORTEE_TREE` query needs to run.

---

## 7. Role-to-Scope Relationship, and the One Correction to the Architecture Plan

**Correction found during this implementation pass:** `docs/architecture/
RBAC_DATA_SCOPE_IMPLEMENTATION_PLAN.md §5` sketched `resolve_data_scope` as living entirely inside
`core/rbac` and running the `employee_assignment` recursive CTE itself. Inspecting
`apps/api/.importlinter` during this pass shows a `layers` contract —
`hrms.modules → hrms.shared → hrms.core` — meaning **`hrms.core` may not import anything from
`hrms.modules`**, checked directly (`hrms.core` was grepped for `from hrms.modules`; zero hits,
confirming the contract is respected everywhere today). `core/rbac` therefore cannot import
`EmployeeAssignment` (`hrms.modules.employee.models`) without breaking `lint-imports` in CI. The
corrected split:

- **`core/rbac`** resolves *which scope levels* a user's roles grant for a given permission code —
  purely from `role_permission`/`role`/`user_role`/`user_company`, exactly the tables it already
  queries. Returns `DataScope(levels=frozenset[DataScopeLevel])`. Knows nothing about
  `employee_assignment` or reporting hierarchies.
- **`hrms.modules.employee`** (which already depends on `core.rbac`, an allowed direction) is
  responsible for turning `DataScope.levels` + the caller's `employee_id` into a concrete set of
  visible employee IDs, since it — not `core` — owns the reporting-hierarchy data. This lives as a
  new `EmployeeService.resolve_visible_employee_ids(...)` method, public on the module's service
  layer, matching the Module Standard's "reusable via `other_module.service`" cross-module import
  rule — this is also exactly the shape a future Attendance/Leave/Payroll module would call
  (`employee.service.EmployeeService`, not `employee.repository`/`.models`) to resolve "which
  employee IDs is this caller allowed to see," reusing the same reporting-hierarchy logic without
  re-implementing it.

This is a **smaller** change than the architecture plan's original sketch (`core/rbac` stays
exactly as narrowly scoped as it is today; only `employee/service.py` and `employee/repository.py`
grow), not a redesign — it does not change any of the locked product decisions (A–J), only where
the SQL that walks `reporting_manager_id` physically lives.

**Role-to-scope, concretely:** a `role_permission` row's `data_scope` value is queried per
`(user, company, permission_code)` via `RbacService.resolve_data_scope`. A user's effective scope
for a given permission code is the **union** across every role that grants that code — see §12.

---

## 8. How `employee_id` Is Obtained From the Authenticated User

Already solved, no new plumbing: `AuthenticatedUser.employee_id` (`core/auth/types.py:10`) is
decoded from the JWT's `employee_id` claim at authentication time
(`core/auth/dependencies.py:27`), before `require_permission` even runs. The two in-scope routes
already receive `AuthenticatedUser` indirectly through `get_current_user`, but do not currently
inject it as a dependency (only the assignment-create route does, for its own reasons) — this
task adds that dependency to the two `GET` routes so `employee_id` is available where scope
resolution needs it (§17).

---

## 9. How `reporting_manager_id` Is Used

Two new read-only queries, both scoped by `company_id` (belt-and-suspenders, same convention as
every existing query in this repository) and by the effective-dating predicate
(`effective_from <= today AND (effective_to IS NULL OR effective_to > today)` — collapses to
`effective_to IS NULL` for "current," since there is no `as_of` parameter on these two routes):

1. **Direct reports** — `SELECT employee_id FROM employee_assignment WHERE company_id = :cid AND
   reporting_manager_id = :caller_employee_id AND effective_to IS NULL`.
2. **Reportee tree** — the same predicate as the root of a recursive CTE, walking
   `reporting_manager_id` outward, depth-capped at 20, `DISTINCT` on `employee_id` in the final
   projection (a `dotted_line_manager_id` employee could in principle appear via a different path
   than `reporting_manager_id`, but this task's tree walk is over `reporting_manager_id` only —
   `dotted_line_manager_id` is not part of `REPORTEES`/`REPORTEE_TREE`'s definition per Doc 19 §5,
   and is not touched by this plan).

`reporting_manager_id` is never written by this change — only read.

---

## 10. Behavior for Users Without Employee Records

A user can hold `UserCompany`/`UserRole` rows with no corresponding `Employee` row (the exact case
the Audit names for a `COMPANY_ADMIN` who registered the company but isn't in the employee
roster). If such a user's *effective* scope for some permission resolves to `SELF` or
`REPORTEES`/`REPORTEE_TREE` (an unusual role configuration — those levels normally belong to roles
held by actual employees, but nothing in the schema prevents assigning them to a non-employee
user), the resolver **fails closed**: `SELF` with `employee_id is None` contributes nothing;
`REPORTEES`/`REPORTEE_TREE` with `employee_id is None` also contribute nothing (there is no root
to walk the tree from). The net visible set is empty for that grant — never falls back to
`COMPANY`, and never raises an unhandled error. If the *only* grant such a user holds for a
permission is one of these three levels, they see nothing via that permission; if they also hold
a `COMPANY`-scoped grant for the same permission (e.g., via a second role), that grant still
applies normally (§12, union semantics — `COMPANY` short-circuits to "no filter" regardless of
what else is granted).

---

## 11. Behavior for `COMPANY_ADMIN`

**Preserved exactly, unchanged.** `COMPANY_ADMIN`'s existing `role_permission` rows (both the
demo-seed path and the real company-registration path, `organisation/service.py:register_company`)
are **not modified** by the migration — the new `data_scope` column is added with
`DEFAULT 'COMPANY'`, so every pre-existing row, including every `COMPANY_ADMIN` grant in every
tenant that exists before this ships, defaults to `'COMPANY'` automatically. `resolve_data_scope`
returns `DataScope(levels={COMPANY})` for such a grant, which the employee-module resolver
(§7) maps to "no `employee_ids` filter" — functionally and observably identical to today's
hard-coded `DataScope(level=COMPANY)`. No `COMPANY_ADMIN` row's scope is set to anything narrower
by this task. Verified against the actual seeding code
(`organisation/service.py:273-319`, `seed/bootstrap.py:68-88`) before writing this section — the
`COMPANY_ADMIN` role's permission grants are inserted via `insert_role_permission(role_id=...,
permission_id=...)` with no scope argument today, and this plan does not touch that call site at
all, relying entirely on the column default.

---

## 12. Behavior for Users With Multiple Roles

`resolve_data_scope` queries every `role_permission` row reachable from the user's roles that
grants the specific permission code being checked — a user with two roles, each separately
granting `EMPLOYEE.VIEW`, gets **both** rows' `data_scope` values back (`role_permission` has no
`DISTINCT`-by-permission constraint; the query naturally returns one row per matching
`(role, permission)` pair across every role the user holds). Resolution is **additive** (matches
`role_permission`'s existing purely-additive design — no `DENY` concept exists or is introduced):

1. If `COMPANY` is among the returned levels → short-circuit, `DataScope(levels={COMPANY})`, no
   further query needed (avoids ever materializing a company-sized ID set).
2. Otherwise, the employee-module resolver computes the **union** of the concrete ID sets implied
   by each distinct level present — not just "pick the broadest label." This distinction matters:
   `SELF` and `REPORTEES` are not nested (a manager's own ID is not a member of their own
   `REPORTEES` set), so a user holding both a `SELF`-scoped grant and a `REPORTEES`-scoped grant
   for the same permission (via two different roles) must see the union — their own record *and*
   their reports — not just the "wider-sounding" `REPORTEES` set alone, which would silently drop
   their own record. `REPORTEE_TREE` and `REPORTEES` from the same root are still computed as
   "run `REPORTEE_TREE` once, skip `REPORTEES`" since the former is already a superset for that
   root.

---

## 13. Interaction With Existing Company Tenant Isolation

Unaffected and unchanged. `get_tenant_context` (`core/tenancy/dependencies.py`) still runs before
`require_permission`, still 404s on a company/JWT mismatch before any permission or scope logic
executes. Every new query this task adds is additionally filtered by `company_id` (belt-and-
suspenders, matching every existing query in `employee/repository.py`) — scope is a narrowing
*within* an already-tenant-verified request, never a substitute for the tenant check, and never
evaluated before it.

---

## 14. Interaction With RLS

Unaffected. RLS's `tenant_isolation` policy (`company_id = current_setting('app.company_id',
true)::uuid`) remains the sole database-enforced backstop, keyed on the same session variable set
today. `role_permission` carries no RLS policy today (confirmed: `scripts/sql/001_init_schema.sql`
defines it with only a composite primary key on `(role_id, permission_id)`, no `company_id` column
and no `ENABLE ROW LEVEL SECURITY` statement anywhere for that table — it's a join table that
relies on its parent `role`'s tenant scoping, per the Audit's own §6 characterization of "join
tables... rely on parent-table's policy plus an application-layer join predicate"). Adding
`data_scope` to it does not change this — no RLS statement is added or needed by this migration.
`employee`/`employee_assignment` keep their existing `FORCE ROW LEVEL SECURITY` + single-predicate
policy, untouched.

---

## 15. Query Design

- **Permission + scope-level lookup** (`core/rbac`): one query, extending the existing
  `get_permission_codes_for_user` join shape to also `SELECT RolePermission.data_scope` (instead
  of just `Permission.code`), filtered additionally by `Permission.code == code`. One round trip,
  same join, no new table touched beyond the one new column.
- **`SELF` resolution**: no query — `{caller.employee_id}` if not `None`, else empty.
- **`REPORTEES` resolution**: one indexed lookup (§16) against `employee_assignment`, filtered by
  `company_id` + `reporting_manager_id` + `effective_to IS NULL`.
- **`REPORTEE_TREE` resolution**: one recursive CTE (SQLAlchemy Core `.cte(recursive=True)`, not
  raw string-interpolated SQL — every bound value goes through SQLAlchemy's normal parameter
  binding, avoiding manual UUID/string interpolation entirely), depth-capped at 20, same
  `company_id` + effective-dating predicate applied at every recursion level.
- **List query** (`GET /employees`): the resolved `employee_ids` (or `None` for `COMPANY`) is
  passed into `EmployeeRepository.list_employees` as an additional, optional filter — appends
  `Employee.id.in_(employee_ids)` to the existing `WHERE company_id = ... AND deleted_at IS NULL`
  clause when not `None`. No separate query, no in-Python filtering, no pagination-breaking
  post-filter (this repository has no pagination today, per Audit §9 — the predicate is still
  applied at the SQL layer so it composes correctly whenever pagination is added later).
- **Detail query** (`GET /employees/{id}`): identical addition to `EmployeeRepository.get_employee`
  — `Employee.id.in_(employee_ids)` alongside the existing `Employee.id == employee_id` predicate.
  An out-of-scope target naturally produces the same "no row" result the method already produces
  for a cross-tenant miss, which the service layer already turns into `404` — **zero new
  branching** in the service, confirmed by reading `EmployeeService.get_employee`
  (`service.py:159-165`) before writing this section.

---

## 16. Performance / Index Requirements

**Correction, found while writing the migration (§20) and verifying against the live schema —
no new index is needed.** `employee/models.py:120-124`'s ORM-level `index=True` declarations
cover only `company_id` and `employee_id`, which read as if `reporting_manager_id` were unindexed.
Querying `pg_indexes` directly against the live database before writing the migration showed
otherwise: `20260814100000_employee_assignment.py` (the E-04 migration) already created
`employee_assignment_manager_idx` on exactly `(company_id, reporting_manager_id) WHERE
effective_to IS NULL` — a raw-SQL index added directly in that migration, not mirrored in the ORM
model's `index=True` (SQLAlchemy doesn't require every DB index to be re-declared on the model;
the model only tracks indexes it manages itself). This is precisely the partial index the
`REPORTEES`/`REPORTEE_TREE` resolver's query shape needs (`company_id` + `reporting_manager_id` +
"current"), already in place, already exercised by every migration since E-04. **This task adds no
new index** — see §20's migration, which was edited to remove the originally-planned (redundant)
index once this was found. No index is added for `employee.id` (already the primary key) or
`employee.company_id` (already indexed, `models.py:35-37`) either, both unchanged by this task. No
index for a hypothetical `as_of` (historical) query is added, since neither in-scope route accepts
`as_of` (§5) — that would be speculative for work not being done here.

---

## 17. Security Risks

| Risk | Current state | Control added by this plan |
|---|---|---|
| IDOR — any `EMPLOYEE.VIEW` holder can fetch any employee by ID | Confirmed (Audit §9 row 3) | Scope predicate on `get_employee`; out-of-scope → `404` |
| Enumeration — a `403` on an out-of-scope-but-existing ID would disclose existence | N/A today (no scope check exists to leak through) | `404`, not `403`, for a scope miss — matches the existing cross-tenant convention exactly, no new disclosure channel introduced |
| List over-grant — any `EMPLOYEE.VIEW_ALL` holder lists the whole company | Confirmed (Audit §9 row 1) | Scope predicate on `list_employees` |
| Privilege escalation via hierarchy manipulation (a caller sets themself as someone's manager to gain `REPORTEES` visibility) | No cycle/self-elevation guard exists today (Audit §12) — **not closed by this plan** | Explicitly named as a known limitation (§22) — the write-time guard is a separate, not-yet-scoped fix; a test asserting the gap is written as an explicit `xfail`, not silently omitted (§19) |
| Cyclic/malformed hierarchy hangs a `REPORTEE_TREE` query | No cycle prevention at write time | Depth cap (20) bounds query cost regardless of write-time state — cost-safe, not correctness-guaranteed |
| Fail-open on missing `employee_id` | N/A (scope doesn't exist yet) | Explicit fail-closed handling (§10) — never defaults to `COMPANY` |
| Cross-tenant access | Already closed (RLS + `company_id` filters, tested) | Unaffected, verified unchanged (regression test, §19) |

---

## 18. API Behavior

- `GET /v1/employees/{id}`: in-scope → `200` with the existing `EmployeeRead` body, unchanged
  shape. Out-of-scope (but same tenant) → `404`, identical error shape to a nonexistent or
  cross-tenant ID (`{"error": {"code": "NOT_FOUND", ...}}`) — the client cannot distinguish
  "doesn't exist," "wrong tenant," and "exists but outside your scope."
- `GET /v1/employees`: returns only in-scope records. An empty scope (e.g., a `REPORTEES`-only
  manager with zero current reports) returns `[]`, `200` — not an error.
- No response schema change. No new query parameters. No change to `POST`/`PATCH`/`DELETE
  /employees*` or any Employment/Assignment/Compensation route (all still `COMPANY`-scoped,
  unchanged, per Strict Exclusions).

---

## 19. Test Strategy

New test module: `apps/api/tests/integration/modules/employee/test_employee_data_scope.py`,
following the exact fixture pattern already established in `test_employee.py`'s
`test_create_employee_without_permission_rejected` (inline `Role`/`RolePermission`/`User`/
`UserCompany`/`UserRole`/`Session` construction + `create_access_token(..., employee_id=...)`) —
this is the only pattern in the codebase for building a non-default-role test actor, and it
already supports attaching a specific `employee_id` to the JWT, which is exactly what `SELF`/
`REPORTEES` tests need.

- **`SELF`**: actor sees own record (`200`), cannot see an unrelated employee (`404`), list
  returns exactly one row (their own).
- **`REPORTEES`**: manager with 2 direct reports sees both (`200` each), cannot see an unrelated
  employee (`404`), cannot see a second-level report (someone reporting to one of their direct
  reports) — asserts the one-level boundary explicitly.
- **`REPORTEE_TREE`**: 3-level fixture (manager → sub-manager → leaf) — top manager sees every
  descendant (`200`), cannot see an employee in an unrelated branch (`404`).
- **Security**:
  - cross-tenant employee under a scoped role → `404` (regression against the existing tenant
    check, run with a scope-holding role this time, not just `COMPANY_ADMIN`).
  - forged/random UUID → `404`, identical to the existing not-found test.
  - detail endpoint cannot be used to bypass list scope (already implied by using the same
    resolver and predicate for both — asserted directly by calling detail on a list-excluded ID).
  - list scope cannot be widened by any client-supplied input — the two in-scope routes take no
    query parameters that touch scope at all, so this is asserted by absence (no such parameter
    exists to attempt).
- **Edge cases**: employee with `reporting_manager_id = NULL` (never appears in anyone's
  `REPORTEES`/`REPORTEE_TREE` — not an error); manager with zero current reports (`[]`, not an
  error); a fixture-constructed cyclic chain (direct DB insert bypassing the write-time guard that
  doesn't exist) — asserts the depth cap terminates the query rather than hanging; an inactive
  (`is_active=False`, not terminated) direct report — still visible (Decision D); a terminated
  direct report (assignment row closed by the termination cascade) — no longer appears in a
  *current* `REPORTEES` query (this task does not implement `as_of` scope resolution, so the
  "still visible as-of a past date" half of Decision D is **not** tested here — correctly out of
  scope, since neither in-scope route accepts `as_of`); actor with no `employee_id` and a
  `SELF`/`REPORTEES` grant → sees nothing (`404` on any ID, `[]` on list); `COMPANY_ADMIN`
  regression — unchanged company-wide access, proving zero behavior change for the existing role.
  Multi-role union — an actor holding both a `SELF`-scoped and a `REPORTEES`-scoped grant (via two
  roles) sees both their own record and their reports (§12).
- **Regression**: full existing Employee and Organisation integration/unit suites re-run, zero
  weakened or deleted assertions.

The write-time cycle/self-elevation guard test is written as an explicit `pytest.mark.xfail`
(strict=False, with a comment citing this document's §17/§22) rather than omitted, per the task's
own instruction not to silently skip a known gap.

---

## 20. Migration Requirements

One additive migration:

```sql
ALTER TABLE role_permission
  ADD COLUMN IF NOT EXISTS data_scope VARCHAR(20) NOT NULL DEFAULT 'COMPANY';

ALTER TABLE role_permission
  ADD CONSTRAINT role_permission_data_scope_check
  CHECK (data_scope IN ('SELF', 'REPORTEES', 'REPORTEE_TREE', 'COMPANY'));
```

No new index (§16 — an equivalent partial index already exists from the E-04 migration). No new
table. No RLS statement (§14). No backfill needed — `DEFAULT 'COMPANY'` fills every existing row,
preserving current behavior for every existing tenant/role by construction (§11).

---

## 21. Files Expected to Change

```
apps/api/alembic/versions/<timestamp>_role_permission_data_scope.py   (new)
apps/api/src/hrms/core/db/models/identity.py                          (RolePermission.data_scope — the ORM column mirroring the migration; not in the original sketch, needed the moment the migration adds the DB column)
apps/api/src/hrms/core/rbac/types.py                                  (DataScopeLevel, DataScope)
apps/api/src/hrms/core/rbac/service.py                                (RbacRepository, RbacService)
apps/api/src/hrms/core/rbac/dependencies.py                           (_check_permission)
apps/api/src/hrms/modules/employee/repository.py                     (EmployeeAssignmentRepository, EmployeeRepository)
apps/api/src/hrms/modules/employee/service.py                        (EmployeeService)
apps/api/src/hrms/modules/employee/router.py                         (2 routes + module docstring)
apps/api/tests/integration/modules/employee/test_employee_data_scope.py  (new)
docs/modules/employee/25_EMPLOYEE_RBAC_DATA_SCOPE_IMPLEMENTATION_PLAN.md  (this document)
docs/modules/employee/26_EMPLOYEE_RBAC_DATA_SCOPE_IMPLEMENTATION_REPORT.md  (closeout, written last)
```

No file outside these is expected to change. `organisation/service.py` (registration flow),
`seed/bootstrap.py`, any frontend file, and every other Employee endpoint/router file are not
touched.

---

## 22. Explicitly Excluded Scope

Restated from the task's own Strict Scope Exclusions, plus this plan's own narrowing:

- `DEPARTMENT`/`BRANCH`/`LEGAL_ENTITY`/`ALL_COMPANIES` scope — not built, not added to the enum.
- Any route other than `GET /employees` and `GET /employees/{id}` — Employment/Assignment/
  Compensation reads, and every Employee write route, remain `COMPANY`-scoped, unchanged.
- `as_of` (historical) scope resolution — the two in-scope routes have no `as_of` parameter; scope
  is always resolved against "now."
- Write-time cycle/self-elevation guard on `reporting_manager_id` — a real, separate gap (§17),
  tracked via an explicit `xfail` test, not fixed here.
- Default-role seeding in `organisation/service.py:register_company` (e.g., a real `EMPLOYEE`/
  `REPORTING_MANAGER` role a real tenant could assign) — not required by this task's stated scope,
  and adding it would touch a shared, unrelated service method beyond what's asked. Test fixtures
  construct scoped roles directly (§19), matching the existing test pattern; a real tenant still
  cannot reach this feature without manual role creation until that separate product decision
  (Decisions doc, Decision H) is acted on — explicitly named as a known limitation, not silently
  left unmentioned.
- `sensitive_access_log`, Statutory, Banking, Attendance, Leave, Payroll, frontend, approval
  workflows, any new organisational hierarchy, any generic/config-driven RBAC framework.

---

## 23. Rollback Considerations

- **Migration is purely additive** (`ADD COLUMN ... DEFAULT`, one `CHECK` constraint, no new
  index) — no data transformation, no column renamed or dropped elsewhere. Reverting the
  application code (repository/service/router changes) to stop consuming the column is a pure code
  revert; the column can be left in place (inert, unused) or dropped in a trivial follow-up
  migration, either way with zero data-loss risk.
- **No existing tenant's behavior changes** unless a test explicitly creates a non-`COMPANY`
  scoped role (§11, §19's fixtures) — a revert has no user-visible cleanup to perform beyond the
  test data itself, which the test suite's own `finally` blocks already tear down.
- **If the migration itself needs to be rolled back**, the `downgrade()` drops the constraint and
  column — safe only if no application code depends on the column existing at that point, which is
  guaranteed by reverting the application code first (standard "app code before schema" rollback
  ordering, consistent with every other migration in this series).

---

## 24. Acceptance Criteria

- `GET /v1/employees` and `GET /v1/employees/{id}` enforce `SELF`/`REPORTEES`/`REPORTEE_TREE`/
  `COMPANY` scope server-side.
- Scope violation on the detail route returns `404`, identical in shape to the existing
  not-found/cross-tenant response.
- Scope violation on the list route silently filters the row; no distinct status code, no error.
- `COMPANY_ADMIN`'s behavior on both routes is provably unchanged (regression test passes).
- A user with no `employee_id` sees nothing via a `SELF`/`REPORTEES`/`REPORTEE_TREE` grant — never
  errors, never falls back to company-wide access.
- A cyclic reporting-hierarchy fixture does not hang `REPORTEE_TREE` resolution.
- No route outside the two named above changes observable behavior.
- No file outside §21's list is modified.
- Full existing test suite (Employee + Organisation + RBAC-adjacent) passes unchanged, alongside
  the new test module.
- `pytest`, `ruff check`, `ruff format --check`, `mypy`, and `lint-imports` all pass.
