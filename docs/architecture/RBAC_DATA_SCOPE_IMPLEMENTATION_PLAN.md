# RBAC Data-Scope — Implementation Plan

**Status:** Planning only. No application code, migrations, schema, tests, or frontend code were
created or modified to produce this document. Nothing was committed.

**Date:** 2026-08-15

**Depends on:** `docs/architecture/RBAC_DATA_SCOPE_DECISIONS.md` (all decisions A–J, PD-RBAC-1
through PD-RBAC-5 as resolved or left open there). This plan does not restate the reasoning behind
those decisions — only their consequences for implementation. Also depends on
`docs/modules/employee/24_EMPLOYEE_RBAC_DATA_SCOPE_AUDIT.md` for the underlying FACT findings,
independently re-verified in the Decisions document.

---

## 1. Objective

Make `require_permission()`'s returned `DataScope` real for the `SELF`/`REPORTEES`/
`REPORTEE_TREE`/`COMPANY` levels, and wire it into the two highest-traffic, most clearly
over-granted Employee read endpoints (`GET /v1/employees`, `GET /v1/employees/{id}`), without
disturbing `COMPANY_ADMIN`'s existing company-wide behavior. This closes the Audit's HIGH-severity
finding for those two routes and establishes the resolver/enforcement pattern every other Employee
endpoint (Section 10 below) and every future module (Attendance/Leave/Payroll) will reuse.

---

## 2. Current Architecture (as verified)

```
JWT → get_current_user()               (auth, unchanged)
    → get_tenant_context()             (tenant validation, 404 on mismatch, unchanged)
    → require_permission(code)         (permission check, unchanged — still gates 403)
        → returns DataScope(level=COMPANY)   ← always, hard-coded, discarded by every caller
    → repository query filtered by company_id only   ← the actual gap
```

`RbacService.has_permission` / `get_permission_codes` (`core/rbac/service.py`) already does the
`permission → role_permission → role → user_role → user_company` join, filtered by
`user_company.status = 'ACTIVE'`. This plan extends that same join, not replaces it.

---

## 3. Approved Scope Model (from the Decisions document)

- Levels: `COMPANY` (existing), `SELF`, `REPORTEES`, `REPORTEE_TREE` (Decision C). `DEPARTMENT`/
  `BRANCH`/`LEGAL_ENTITY`/`ALL_COMPANIES` are added to the enum for shape-completeness but wired
  to no resolver logic yet.
- Scope attaches to the `(role, permission)` grant — a new column on `role_permission`
  (Decision A).
- `SELF`/`REPORTEES`/`REPORTEE_TREE` are derived from `AuthenticatedUser.employee_id` and
  `employee_assignment.reporting_manager_id` — no per-user scope-assignment storage
  (Decision B, for these levels only).
- Scope violation on a single-record read → `404`; on a list → silent filtering, `COUNT` matches
  `SELECT` (Decision I/J).

---

## 4. Database Changes

**One column, one enum expansion. No new table.**

```
ALTER TABLE role_permission
  ADD COLUMN IF NOT EXISTS data_scope VARCHAR(20) NOT NULL DEFAULT 'COMPANY';

-- CHECK constraint restricting to the (expanded) DataScopeLevel values, e.g.:
ALTER TABLE role_permission
  ADD CONSTRAINT role_permission_data_scope_check
  CHECK (data_scope IN ('SELF','REPORTEES','REPORTEE_TREE','DEPARTMENT','BRANCH',
                         'LEGAL_ENTITY','COMPANY','ALL_COMPANIES'));
```

- **Purpose:** records, per role-permission grant, which scope level that grant carries.
- **Relationship/cardinality:** 1:1 with the existing `role_permission` composite PK
  (`role_id`, `permission_id`) — one scope value per grant, no new join table.
- **Tenant ownership:** inherited from `role.company_id`; `role_permission` itself carries no
  `company_id` (unchanged — it's a join row, not a tenant-owned entity).
- **Default `'COMPANY'`:** critical for backward compatibility — every existing `role_permission`
  row (including every `COMPANY_ADMIN` grant in every existing tenant) gets this default on
  migration and continues to behave **exactly** as it does today. No tenant's existing access
  changes as a result of this migration by itself.
- **Indexing:** none needed. `role_permission` is already looked up joined on `role_id` inside
  `RbacRepository.get_permission_codes_for_user`; the new column is read, not filtered, in that
  same query path.
- **RLS implications:** none — `role_permission` has no RLS policy today (it's a join table
  without its own `company_id`, relying on the parent `role`'s tenant scoping plus the
  application-layer join predicate already in `RbacRepository`). This migration doesn't change
  that.
- **Follow-on, this migration only:** seed the `EMPLOYEE`, `REPORTING_MANAGER`, `HR_ADMIN` roles
  (Decision H) in the real company-registration flow (`organisation/service.py:register_company`),
  each with `role_permission.data_scope` set per Decision H's table. `COMPANY_ADMIN`'s existing
  grants are **not** touched — they keep the `'COMPANY'` default.
- **`DataScopeLevel` enum** (`core/rbac/types.py`): expand from `COMPANY/TEAM/SELF` to
  `SELF/REPORTEES/REPORTEE_TREE/DEPARTMENT/BRANCH/LEGAL_ENTITY/COMPANY/ALL_COMPANIES` — retiring
  the ambiguous `TEAM` name. This is a pure Python enum change, no migration involved, but must
  land in the same PR as the DB `CHECK` constraint so the two never drift.

**Explicitly deferred (Decision B, `DEPARTMENT`/`BRANCH`/`LEGAL_ENTITY`):** no
`role_permission_scope_ref` (or equivalent per-user/per-target scope-assignment) table is
designed or built in this plan. If/when Decision B's open question is resolved, that table's
shape depends on the answer and should be designed then, not guessed now.

---

## 5. Backend Architecture

```
authenticate (JWT)
  → get_tenant_context()                          [unchanged — 404 on tenant mismatch]
  → require_permission(code)                        [unchanged signature — still 403s]
      → RbacService.resolve_data_scope(user, code)   [NEW — replaces the hard-coded return]
          1. Find every role_permission row matching this (user's roles, code) pair.
          2. If any row has data_scope = COMPANY → return DataScope(level=COMPANY, employee_ids=None)
             (widest wins — additive/union semantics, matches role_permission's existing
             purely-additive design; no DENY concept exists or is introduced).
          3. Else if any row has REPORTEE_TREE → resolve recursive CTE from user.employee_id,
             return DataScope(level=REPORTEE_TREE, employee_ids=<resolved set>).
          4. Else if any row has REPORTEES → resolve one-level query, same shape.
          5. Else if any row has SELF → DataScope(level=SELF, employee_ids={user.employee_id} or
             frozenset() if user.employee_id is None — fail EMPTY, never fail OPEN).
          6. No matching grant at all → unreachable in practice (require_permission already
             403'd if the permission itself wasn't held) — defensive empty-set return only.
  → repository call receives the resolved DataScope
      → adds `Employee.id.in_(scope.employee_ids)` when employee_ids is not None
      → adds no extra predicate when level == COMPANY (employee_ids is None) — identical to
        today's behavior
  → RLS company_id backstop still applies underneath, unchanged
```

**Where this lives:** extend `RbacService` (`core/rbac/service.py`) with the new
`resolve_data_scope` method, reusing its existing session/repository. Extend
`core/rbac/dependencies.py`'s `_check_permission`/`require_permission` to call it instead of
returning the hard-coded constant — **the dependency's call-site signature does not change**, so
every route that already depends on `require_permission(code)` continues to compile unchanged;
only the ~2 routes in this task's scope additionally *consume* the now-real return value.

**`DataScope` type change** (`core/rbac/types.py`):

```python
@dataclass(frozen=True, slots=True)
class DataScope:
    level: DataScopeLevel = DataScopeLevel.COMPANY
    employee_ids: frozenset[UUID] | None = None   # None = no predicate needed (COMPANY/ALL_COMPANIES)
```

**Recursive CTE (`REPORTEE_TREE`), reference shape** (from Doc 19 §5, unchanged, now actually
implemented):

```sql
WITH RECURSIVE tree AS (
  SELECT employee_id, 1 AS depth
    FROM employee_assignment
   WHERE company_id = :company_id
     AND reporting_manager_id = :root_employee_id
     AND effective_from <= :as_of AND (effective_to IS NULL OR effective_to > :as_of)
  UNION ALL
  SELECT ea.employee_id, tree.depth + 1
    FROM employee_assignment ea
    JOIN tree ON ea.reporting_manager_id = tree.employee_id
   WHERE ea.company_id = :company_id
     AND ea.effective_from <= :as_of AND (ea.effective_to IS NULL OR ea.effective_to > :as_of)
     AND tree.depth < 20
)
SELECT DISTINCT employee_id FROM tree;
```

`REPORTEES` is the same query with the recursive arm omitted (depth capped at 1).

**Where scope is enforced:** at the repository query layer, as an additional predicate alongside
the existing `company_id` filter — never as a post-query in-memory filter (would break pagination
semantics and Decision J's `COUNT`-matches-`SELECT` requirement).

---

## 6. Permission Interaction

Implements Decision I exactly:

- `require_permission(code)` still 403s first, unchanged, before any scope resolution happens
  (avoids a wasted recursive-CTE call for a request that's rejected anyway).
- A resolved scope that excludes the target record → the *service* layer's existing not-found
  path is reused (see §7) → `404`, never `403`, never a record with fields stripped.

---

## 7. Repository Changes

`apps/api/src/hrms/modules/employee/repository.py`:

- `get_employee(session, *, company_id, employee_id)` (currently `:45-55` per Audit citation) —
  add an optional `scope: DataScope | None = None` parameter; when `scope.employee_ids is not
  None`, add `Employee.id.in_(scope.employee_ids)` to the existing `WHERE` clause. A caller outside
  scope produces the same "no row found" result the method already produces for a cross-tenant
  miss — **the existing not-found handling in `EmployeeService.get_employee` needs zero new
  branching** to turn this into `404`; it already does that for the company-mismatch case.
- `list_employees(session, *, company_id)` — same addition: optional `scope` parameter, same
  conditional predicate. When `scope.employee_ids is not None`, the returned list is naturally
  just the caller's in-scope employees.
- No other repository methods change in this task (Employment/Assignment/Compensation repository
  methods are explicitly out of scope here — Section 10 below tracks them as follow-up work using
  the identical pattern).

---

## 8. Service Changes

`apps/api/src/hrms/modules/employee/service.py`:

- `EmployeeService.get_employee` / `list_employees` — accept the resolved `DataScope` (passed
  through from the router) and forward it to the repository call. No new business logic beyond
  passing the value through — the not-found/empty-list behavior for an out-of-scope target falls
  out of the repository change above.

---

## 9. Router Changes

`apps/api/src/hrms/modules/employee/router.py`:

- `list_employees` and `get_employee` — the `_scope` variable (currently `Annotated[object, ...]`,
  discarded) becomes `scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_VIEW_ALL))]`
  / `Depends(require_permission(EMPLOYEE_VIEW))` respectively, and is passed to the service call:
  `service.list_employees(tenant.company_id, scope=scope)` /
  `service.get_employee(tenant.company_id, employee_id, scope=scope)`.
- No other route in this router changes in this task. Every other route keeps its existing
  `_scope: Annotated[object, ...]` discard pattern for now (Section 10 tracks extending them).
- The router's own module docstring (lines 1-11, which currently states data-scope "is not
  implemented in this slice") must be updated to reflect the new state for these two routes and
  the still-unscoped state of the rest, so a future reader isn't misled either direction.

---

## 10. Employee Endpoint Matrix

| # | Endpoint | Permission | Data Scope (after this task) | Sensitive? | Required Change |
|---|---|---|---|---|---|
| 1 | `GET /v1/employees` | `EMPLOYEE.VIEW_ALL` | **Resolved** (`COMPANY`/`REPORTEES`/`REPORTEE_TREE`/`SELF`) | No | **In this task** — router + service + repository, §7-9 |
| 2 | `POST /v1/employees` | `EMPLOYEE.CREATE` | N/A (creates new identity) | No | None |
| 3 | `GET /v1/employees/{id}` | `EMPLOYEE.VIEW` | **Resolved** | No | **In this task** |
| 4 | `PATCH /v1/employees/{id}` | `EMPLOYEE.UPDATE` | Still `COMPANY` (unscoped) | No | Follow-up — same pattern, `EmployeeRepository.get_employee`-shaped write path needs the same scope check before mutation |
| 5 | `DELETE /v1/employees/{id}` (deactivate) | `EMPLOYEE.DEACTIVATE` | Still `COMPANY` | No | Follow-up |
| 6 | `POST .../employments` | `EMPLOYEE.CREATE` | Still `COMPANY` | No | Follow-up |
| 7 | `GET .../employments` (list/as-of) | `EMPLOYEE.VIEW` | Still `COMPANY` | No | Follow-up — same resolver, Employment repository needs the same optional-scope-predicate addition |
| 8 | `GET .../employments/{id}` | `EMPLOYEE.VIEW` | Still `COMPANY` | No | Follow-up |
| 9 | `PATCH .../employments/{id}` | `EMPLOYEE.UPDATE` | Still `COMPANY` | No | Follow-up |
| 10 | `POST .../employments/{id}/terminate` | `EMPLOYEE.TERMINATE` | Still `COMPANY` | No | Follow-up |
| 11 | `GET .../assignments` (list/as-of) | `EMPLOYEE.VIEW` | Still `COMPANY` | No | Follow-up — same resolver, Assignment repository |
| 12 | `GET .../assignments/{id}` | `EMPLOYEE.VIEW` | Still `COMPANY` | No | Follow-up |
| 13 | `POST .../assignments` | `EMPLOYEE.TRANSFER`/`.PROMOTE` (client-selected — separate known gap, Audit §9 row 13, §16) | Still `COMPANY` | No | Follow-up; the client-trusted `change_type` issue is tracked separately, not fixed by this plan |
| 14 | `GET .../compensation` (list/as-of) | `EMPLOYEE.VIEW_COMPENSATION` | Still `COMPANY` | **Yes — RESTRICTED** | Follow-up — highest-priority follow-up given Decision F's manager-compensation finding |
| 15 | `GET .../compensation/{id}` | `EMPLOYEE.VIEW_COMPENSATION` | Still `COMPANY` | **Yes** | Follow-up |
| 16 | `POST .../compensation` | `EMPLOYEE.UPDATE_COMPENSATION` | Still `COMPANY` | **Yes** | Follow-up |

**Future modules consuming the same resolver:** Attendance/Leave (`SELF` for "my own
attendance/leave," `REPORTEES`/`REPORTEE_TREE` for "my team's," matching approval-routing needs)
and Payroll (payslip visibility — the Audit explicitly flags this as leaning on `VIEW`/`VIEW_ALL`
scoping *more* heavily than Employee does, at higher financial stakes) will call
`RbacService.resolve_data_scope` exactly as this plan's two routes do — no new resolver design
work, only new call sites and new repository predicates in their own modules.

---

## 11. Sensitive-Data Model (restated for implementation, not built here)

- Compensation/Statutory/Banking each keep their own permission code; each, once a role grants it
  with a non-`COMPANY` scope, is narrowed by the exact same `employee_ids` set `resolve_data_scope`
  already produces for that role/permission pair — no separate sensitive-data-specific resolver.
- `sensitive_access_log` seam: a future single call (`SensitiveAccessLogger.log_read(...)`) at each
  RESTRICTED sub-resource's existing service-layer read method, once that table exists. Not built
  in this task (Decision G).

---

## 12. Frontend Implications (not implemented — recorded for a future task)

- A `usePermission`/`PermissionGate` primitive, consuming the already-fetched
  `UserProfile.permissions` array (`apps/web/src/lib/auth/types.ts`), can be built independently
  of this backend work — permission-code-only gating doesn't need real scope values.
- `useDataScope` (or equivalent scope-awareness in the same primitive) should wait until this
  backend task lands, so it has real scope semantics to consume rather than guessing a shape.
- Hidden navigation / disabled actions: UX only — the server-side `404`/filtered-list behavior
  (Decision I/J) remains the actual security boundary regardless of what the frontend hides.
- `403`/`404` handling: a direct-navigation attempt to an out-of-scope employee ID must degrade to
  the same "not found" UI state a genuinely-nonexistent ID would produce — this is a direct
  consequence of choosing `404` over `403` in Decision I, and the frontend should not try to
  distinguish the two cases (doing so would reintroduce the enumeration leak the `404` choice was
  meant to close).
- No Employee UI exists yet (Audit §14, re-confirmed) — this section is a requirements list for
  whenever that UI is built, not a currently-blocked task.

---

## 13. Migration Strategy

1. **Schema migration** (`role_permission.data_scope`, default `'COMPANY'`, `CHECK` constraint) —
   applies cleanly to every existing tenant with zero behavior change, per §4.
2. **`DataScopeLevel` enum expansion** — pure code change, ships in the same PR as the migration
   so the Python enum and the DB `CHECK` never disagree.
3. **Default-role seeding** (Decision H: `EMPLOYEE`, `REPORTING_MANAGER`, `HR_ADMIN`) added to
   `organisation/service.py:register_company` — affects only **newly registered** companies.
   Existing companies do not retroactively get these roles (no backfill migration for existing
   tenants' role sets is in scope here — a company that registered before this ships keeps
   exactly the roles it has today; seeding roles into *existing* tenants, if wanted, is a separate,
   explicit follow-up decision, not an automatic side effect of this migration).
4. **Resolver + two routes** (this plan's actual code change) — ships behind no feature flag;
   because `COMPANY_ADMIN` (and every pre-existing role/grant, via the default) keeps `COMPANY`
   scope, **no existing user's effective access changes** the moment this ships, except for users
   holding the newly-seeded narrower roles (which, per point 3, only exist for companies
   registering after this ships, or for tenants an operator manually assigns them to).

**`COMPANY_ADMIN` behavior must remain, and does remain, unchanged during and after rollout** —
this falls directly out of the `DEFAULT 'COMPANY'` migration choice, not out of any special-casing
of the `COMPANY_ADMIN` role.

---

## 14. Testing Strategy

Extend `test_permission_matrix.py`'s existing structure
(`apps/api/tests/integration/modules/organisation/test_permission_matrix.py`) with an
Employee-specific, scope-aware instance (none exists today — confirmed in Decisions doc's Audit
Verification table).

**Minimum matrix for this task's two routes:**

1. **`SELF` scope:** a role holding `EMPLOYEE.VIEW` at `SELF` scope — `GET /employees/{own_id}` →
   `200`; `GET /employees/{other_id}` → `404`.
2. **`REPORTEES` scope:** fixture with a manager and 2+ direct reports (current, effective-dated
   assignment rows) — manager can `GET` each direct report → `200`; manager cannot `GET` a
   sibling-branch employee outside their tree → `404`.
3. **`REPORTEE_TREE` scope:** fixture with a 3-4 level reporting tree — a manager at the top can
   `GET` every descendant → `200`; cannot `GET` an employee in an unrelated branch of the tree →
   `404`.
4. **Cycle-protection assertion:** a malformed/cyclic fixture (constructed directly via test
   fixtures, bypassing the not-yet-built write-time cycle guard) does not hang the `REPORTEE_TREE`
   query — asserts the depth cap terminates it.
5. **As-of variant:** a manager's tree membership as of a past date, after a later reporting-line
   change, resolves against the historical assignment row, not today's.
6. **`COMPANY` scope (regression):** `COMPANY_ADMIN` continues to `GET` any employee, list all
   employees — asserts this task introduces zero regression for the existing, unscoped role.
7. **List-count consistency:** a scoped list's `COUNT`/total matches the number of rows actually
   returned, not the tenant-wide count (Decision J).
8. **Terminated/rehire interaction:** a terminated direct report drops out of a *current* `REPORTEES`
   query but still appears in an *as-of* query targeting a date before termination; a rehired
   employee (new assignment row, possibly new manager) resolves correctly against the new row.
9. **Tenant isolation (regression):** existing cross-tenant `404` behavior
   (`test_auth_security.py:126-151`) is unaffected — scope is evaluated only after tenant matching
   already passed.
10. **Privilege-escalation (flagged, not necessarily blocking this task):** a caller cannot widen
    their own `REPORTEES` scope by manipulating `reporting_manager_id` on their own or another's
    assignment row via `EMPLOYEE.UPDATE`/assignment-write paths — depends on the write-time cycle/
    self-elevation guard from Decision D, which this plan does not build (see §17, item 2). If
    that guard isn't built in the same PR, this test should be written as an explicit **known-gap**
    test (marked skip/xfail with a citation to the tracked follow-up), not silently omitted.

**Not written as part of this document** — this section states what the implementation task must
deliver; consistent with this document's own "planning only" scope.

---

## 15. Security Testing

- **IDOR:** covered by tests 1-3 above — the exact vulnerability class this task closes for the
  two in-scope routes.
- **Enumeration:** covered by the `404`-not-`403` choice (Decision I) + test 1-3's assertions on
  status code, not just on data absence.
- **Privilege escalation via hierarchy manipulation:** flagged as test 10 above; real fix requires
  the write-time cycle/self-elevation guard (§17 follow-up, not built in this task).
- **Cross-tenant:** unaffected by this change (orthogonal layer, RLS + `company_id`, already
  tested) — test 9 is a regression check, not new coverage.
- **Scope manipulation:** the resolver computes scope entirely server-side from the JWT and the
  DB; no endpoint accepts a client-supplied scope value in this design, and none should ever be
  added — flagged explicitly as a constraint for any future route built on this pattern.
- **Role manipulation:** no role-management UI/API exists yet (Audit §4) — out of reach for this
  task; becomes relevant the moment a role-CRUD endpoint is built, at which point it must not allow
  a caller to grant themself a wider `data_scope` than their own role-management permission
  otherwise implies (a forward-looking note, not an action item now).

---

## 16. Performance Considerations

- **`resolve_data_scope` runs once per request** (called from the `require_permission` dependency,
  already a per-request dependency) — not per-row, no N+1 risk introduced.
- **Index recommendation, justified (the one addition, not a speculative set):** add
  `CREATE INDEX ON employee_assignment (company_id, reporting_manager_id) WHERE effective_to IS
  NULL` — a partial index matching the resolver's dominant query shape (current-assignment
  `REPORTEES`/`REPORTEE_TREE` walks, filtered by `company_id`, keyed on `reporting_manager_id`).
  Today, `employee_assignment` has indexes only on `employee_id` and `company_id`
  (`models.py:120-124` — `index=True` on those two columns only); `reporting_manager_id` is
  unindexed, and the recursive CTE's per-level join predicate is exactly this column. As-of
  (historical) queries fall outside the partial index's `WHERE effective_to IS NULL` condition and
  will use a normal (non-partial) plan — acceptable, since as-of scope resolution is expected to be
  materially rarer than "current" resolution.
- **List-query cost (`GET /employees` under `REPORTEE_TREE` scope):** the resolved `employee_ids`
  set is passed as an `IN (...)` predicate — fine at the expected team/department sizes for this
  module; if a future `COMPANY`-sized `employee_ids` set were ever produced by a misconfigured
  grant, `COMPANY` scope's `employee_ids=None` sentinel (§5) specifically avoids ever materializing
  a company-sized ID list, which is why that sentinel exists rather than "just always compute the
  set."
- **No other index additions recommended** — the depth cap (20) already bounds the recursive CTE's
  worst-case cost independent of indexing; adding indexes speculatively for `DEPARTMENT`/`BRANCH`/
  `LEGAL_ENTITY` scope is premature since those levels aren't being built (Decision C).

---

## 17. Rollout Strategy

**Phase 1 — Data model** (§4): migration + enum expansion. Zero behavior change on deploy
(default `'COMPANY'`).

**Phase 2 — Scope resolver** (§5): `RbacService.resolve_data_scope` implemented and unit-tested in
isolation (mocking the DB join), not yet wired into any route. Deployable independently — dead
code path until Phase 3.

**Phase 3 — Employee read endpoints** (§7-9): `GET /employees`, `GET /employees/{id}` wired to
consume the resolved scope. This is the phase that changes observable behavior — but only for
users holding a non-`COMPANY` scoped grant, which (per §13) means no existing user until the
default-role seeding (Phase 1's role-seed addition) produces one, or an operator manually assigns
one.

**Phase 4 — Employee write endpoints** (deferred past this task — §10 rows 4-6). Not this task's
scope; tracked as an explicit follow-up.

**Phase 5 — Employment/Assignment/Compensation** (deferred — §10 rows 7-16). Compensation
specifically should be prioritized within this phase given Decision F's finding (manager
compensation over-grant is the Audit's HIGH risk).

**Phase 6 — Future modules** (Attendance/Leave/Payroll) — consume the same resolver once built,
no new resolver design needed.

**Rollback strategy:** the migration is additive-only (`ADD COLUMN ... DEFAULT`, no data
transformation, no column removed or renamed elsewhere) — reverting the application code (Phases
2-3) to discard the resolved scope again is a pure code revert with no data cleanup required; the
`role_permission.data_scope` column can be left in place (harmless, unused) or dropped in a
follow-up migration, either way with zero risk to existing data. If the newly-seeded default roles
(Phase 1) need to be rolled back, they can be deleted directly (`is_system=True` roles created only
for companies registered after the deploy — bounded blast radius).

---

## 18. Known Limitations (explicitly, so a future reader doesn't mistake this for "done")

- Only `GET /employees` and `GET /employees/{id}` are scoped after this task — every other
  Employee endpoint (§10) remains company-wide, unchanged.
- `DEPARTMENT`/`BRANCH`/`LEGAL_ENTITY`/`ALL_COMPANIES` scope levels do not exist in the resolver,
  only in the enum shape.
- No write-time cycle/self-elevation guard on `reporting_manager_id` — `REPORTEE_TREE` is
  cost-bounded (depth cap) but not correctness-guaranteed against a maliciously or accidentally
  cyclic hierarchy.
- No `sensitive_access_log` — compensation/statutory/banking reads remain unaudited at the read
  path.
- `personal_email`/`personal_mobile` field-visibility gap is untouched by this plan (independent
  fix, Decision G).
- No RLS-level scope backstop — enforcement is application-layer only, by design (Decisions
  document, Decision-adjacent recommendation carried from the Audit §17).
- No per-user scope override / explicitly-assigned `DEPARTMENT`/`BRANCH` scope — blocked on
  Decision B's still-open question.

---

## 19. Future Extension Points

- `user_role.scope_override` (nullable) — the hybrid extension point named in Decision A, for if a
  genuine per-user (not per-role) scope override need surfaces.
- `role_permission_scope_ref` (or equivalent) — the table `DEPARTMENT`/`BRANCH`/`LEGAL_ENTITY`
  scope will need, shape contingent on Decision B's resolution.
- RLS-level scope backstop — `SET LOCAL app.company_id`'s mechanism could, in principle, be
  extended to pass a resolved scope value into the session; explicitly not built now (matches
  Audit §17's own recommendation).
- `sensitive_access_log` — seam defined in Decisions document, Decision G.

---

## 20. Exact File-Level Implementation Sequence

1. `apps/api/src/hrms/core/rbac/types.py` — expand `DataScopeLevel`; add `employee_ids` field to
   `DataScope`.
2. New Alembic migration — `role_permission.data_scope` column + `CHECK` constraint, following the
   existing `ADD COLUMN IF NOT EXISTS` convention.
3. `apps/api/src/hrms/core/rbac/service.py` — add `resolve_data_scope` to `RbacService` (and a
   corresponding repository method on `RbacRepository` for the role-permission-with-scope join and
   the recursive CTE).
4. `apps/api/src/hrms/core/rbac/dependencies.py` — `_check_permission` calls
   `resolve_data_scope` instead of returning the hard-coded constant.
5. `apps/api/src/hrms/modules/employee/repository.py` — add optional `scope` parameter to
   `get_employee` and `list_employees`, with the conditional `IN` predicate.
6. `apps/api/src/hrms/modules/employee/service.py` — thread the resolved scope through
   `EmployeeService.get_employee`/`list_employees`.
7. `apps/api/src/hrms/modules/employee/router.py` — consume the (now-typed) `DataScope` return
   value at the two routes; update the module docstring (lines 1-11).
8. `apps/api/src/hrms/modules/organisation/service.py` — seed `EMPLOYEE`/`REPORTING_MANAGER`/
   `HR_ADMIN` roles (Decision H) in `register_company`, each with the appropriate
   `role_permission.data_scope` values.
9. Tests — new Employee-specific, scope-aware permission-matrix test module, per §14.
10. Update `apps/api/src/hrms/modules/employee/permissions.py` and the router docstring to remove
    the "not implemented in this slice" language for the two now-scoped routes only.
11. Closeout report — `docs/modules/employee/25_RBAC_DATA_SCOPE_IMPLEMENTATION_REPORT.md`
    (numbering continues from `24_...AUDIT.md`), following the existing E-01 through E-06
    implementation-report format, explicitly restating the Known Limitations (§18 above) so a
    future reader doesn't mistake this narrow first pass for a complete data-scope
    implementation.

---

## 21. Validation Checklist

- [ ] `role_permission.data_scope` migration applies cleanly; every existing row defaults to
      `'COMPANY'`.
- [ ] `COMPANY_ADMIN` in an existing (pre-migration) tenant retains identical `GET /employees` /
      `GET /employees/{id}` behavior — verified by test 6 (§14).
- [ ] `SELF`, `REPORTEES`, `REPORTEE_TREE` resolve correctly against fixtures — tests 1-3.
- [ ] Out-of-scope single-record access returns `404`, not `403`, and not a `200` with a
      differently-shaped body.
- [ ] Out-of-scope list rows never appear; `COUNT` matches returned rows — test 7.
- [ ] As-of scope resolution matches as-of data queries — test 5.
- [ ] Terminated/rehire fixtures behave per Decision D — test 8.
- [ ] Cross-tenant `404` regression passes unchanged — test 9.
- [ ] Recursive CTE terminates on a cyclic fixture within the depth cap — test 4.
- [ ] No route outside `GET /employees`/`GET /employees/{id}` changes observable behavior.
- [ ] New roles seeded only for newly-registered companies; no existing tenant's role set changes.

## 22. Definition of Done

`GET /v1/employees` and `GET /v1/employees/{id}` enforce `SELF`/`REPORTEES`/`REPORTEE_TREE`/
`COMPANY` scope server-side, with `404` semantics for out-of-scope records; `COMPANY_ADMIN` and
every other pre-existing role's behavior is provably unchanged (test 6); the new resolver pattern
is documented and reusable (§5, §10) for every other Employee endpoint and every future module,
without those endpoints needing to be touched in this task; all items in §21 pass; a closeout
report exists.
