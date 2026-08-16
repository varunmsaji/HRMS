# Employee RBAC Data-Scope — Implementation Report (SELF / REPORTEES / REPORTEE_TREE)

**Status:** COMPLETE for the scope defined in
`docs/modules/employee/25_EMPLOYEE_RBAC_DATA_SCOPE_IMPLEMENTATION_PLAN.md`.

**Date:** 2026-08-15

**Scope shipped:** `SELF`/`REPORTEES`/`REPORTEE_TREE`/`COMPANY` data-scope enforcement for exactly
two endpoints — `GET /v1/employees` and `GET /v1/employees/{id}`. No other endpoint, module, or
frontend code changed.

---

## 1. What Was Implemented

- A `role_permission.data_scope` column (`SELF`/`REPORTEES`/`REPORTEE_TREE`/`COMPANY`,
  `DEFAULT 'COMPANY'`) — the schema needed to attach a scope level to a specific `(role,
  permission)` grant.
- `RbacService.resolve_data_scope(user_id, company_id, code)` — resolves which scope level(s) a
  user's roles grant for one permission code. Lives entirely in `core/rbac`, knows nothing about
  `employee_assignment` or any module's domain data.
- `require_permission()` now returns this real, resolved `DataScope` instead of the previous
  hard-coded `DataScope(level=COMPANY)` constant — for every route in the codebase, not just
  Employee's. Every route except the two named above still discards the (now-real, still-always-
  `COMPANY`-for-them-since-no-role-was-given-a-narrower-grant) return value exactly as before —
  observably unchanged.
- `EmployeeService.resolve_visible_employee_ids(...)` — turns the core `DataScope` (levels only)
  plus the caller's own `employee_id` into a concrete, possibly-empty set of visible employee IDs,
  querying `employee_assignment.reporting_manager_id` (direct reports, and a depth-capped
  recursive CTE for the full tree). Public, reusable by future modules.
- `GET /v1/employees` and `GET /v1/employees/{id}` now resolve and apply this scope; an
  out-of-scope detail lookup returns `404`; an out-of-scope list row is silently omitted.

---

## 2. Architecture

```
JWT → get_current_user()          (unchanged — decodes employee_id)
    → get_tenant_context()        (unchanged — 404 on tenant mismatch)
    → require_permission(code)    (unchanged gate; now resolves a real DataScope)
        → core/rbac: RbacService.resolve_data_scope
              queries role_permission.data_scope, joined the same way
              get_permission_codes_for_user already was — returns DataScope(levels=...)
    → EmployeeService.resolve_visible_employee_ids(company_id, scope, caller_employee_id)
          COMPANY in scope.levels?      -> None (no filter — identical to pre-change behavior)
          SELF in scope.levels?         -> add caller_employee_id
          REPORTEE_TREE in scope.levels? -> union recursive-CTE result (superset of REPORTEES)
          REPORTEES in scope.levels?     -> union direct-report-id result
    → EmployeeRepository.get_employee / list_employees
          adds Employee.id.in_(visible_employee_ids) alongside the existing company_id filter,
          only when visible_employee_ids is not None
    → RLS tenant_isolation policy (unchanged, still the backstop)
```

**One correction made during implementation, not anticipated in the architecture-level plan
(`docs/architecture/RBAC_DATA_SCOPE_IMPLEMENTATION_PLAN.md §5`):** that document sketched the
resolver living entirely inside `core/rbac`, running the `employee_assignment` recursive CTE
itself. Inspecting `apps/api/.importlinter` during this task showed a `layers` contract
(`hrms.modules → hrms.shared → hrms.core`) that forbids `hrms.core` from importing
`hrms.modules.employee`. The corrected split — `core/rbac` resolves scope *levels* only;
`hrms.modules.employee` (which already legitimately depends on `core.rbac`) resolves levels into
concrete employee IDs — is documented in full in
`docs/modules/employee/25_EMPLOYEE_RBAC_DATA_SCOPE_IMPLEMENTATION_PLAN.md §7`. `lint-imports`
passes cleanly with this split (verified, §11 below).

**A second correction, found while writing the migration:** the plan document (§16) proposed a
new partial index on `employee_assignment (company_id, reporting_manager_id) WHERE effective_to
IS NULL`, reasoning from the ORM model's `index=True` declarations alone. Querying `pg_indexes`
against the live database before writing the migration showed an index with that *exact*
definition (`employee_assignment_manager_idx`) already exists, added by the E-04 migration
(`20260814100000_employee_assignment.py`) ahead of this task. The migration actually shipped adds
no index — see §12 below.

---

## 3. Scope Semantics

- **`SELF`**: caller's own `employee_id` only. Does not imply `REPORTEES`.
- **`REPORTEES`**: employees whose *current* (`effective_to IS NULL`) assignment row has
  `reporting_manager_id` equal to the caller's `employee_id`. One level only. Does not include the
  caller's own record.
- **`REPORTEE_TREE`**: transitive closure of `REPORTEES`, recursive CTE, depth-capped at 20 (no
  cycle detection — cost-bounded, not correctness-guaranteed against a malformed hierarchy).
- **`COMPANY`**: unchanged — no filter, full tenant visibility.
- **Multi-grant union**: if a user's roles grant more than one level for the same permission code
  (e.g. `SELF` via one role, `REPORTEES` via another), the effective visible set is the **union**
  of what each level resolves to — not just the "widest-sounding" level alone, since `SELF` and
  `REPORTEES` are not nested (a manager's own ID is never a member of their own `REPORTEES` set).
  `COMPANY`, if present anywhere in the granted set, always short-circuits to "no filter."
- **Fail-closed**: a caller with no `employee_id` (no `Employee` row) holding a `SELF`/
  `REPORTEES`/`REPORTEE_TREE` grant resolves to an empty visible set — never falls back to
  `COMPANY`, never raises an unhandled error.
- **As-of/historical resolution**: **not implemented.** Neither in-scope route accepts an `as_of`
  parameter; scope is always resolved against "now." A terminated employee's closed assignment row
  correctly drops out of a *current* `REPORTEES` query, but there is no way today to ask "who
  reported to me on date X" through these two routes specifically — an explicit, documented
  limitation (§14), not an oversight.

---

## 4. Role Mapping

No new roles were seeded. `COMPANY_ADMIN` (both the demo-seed path and the real
company-registration path) and the demo-only `EMPLOYEE_VIEWER` are **unchanged** — every existing
`role_permission` row defaults to `data_scope = 'COMPANY'` via the migration, verified directly
against the live database (21 pre-existing rows, all read back `'COMPANY'` after migrating).
`organisation/service.py:register_company` (the real registration flow) was **not** touched — a
real tenant still cannot reach a narrower scope level without direct database access, exactly as
before this task. This is named explicitly as a known limitation (§14), consistent with the plan's
own explicit exclusion (§22) — seeding a real, assignable narrower role was judged out of this
task's stated scope, not something the strict exclusions or the task instructions asked for.

Test fixtures construct scoped roles directly via the ORM (`RolePermission(..., data_scope=...)`),
mirroring the one existing pattern in this codebase for a non-default-role test actor
(`test_employee.py::test_create_employee_without_permission_rejected`).

---

## 5. API Behavior

| Route | Change |
|---|---|
| `GET /v1/employees` | Now resolves scope for `EMPLOYEE.VIEW_ALL`; returns only in-scope records. Empty scope → `[]`, `200` (not an error). |
| `GET /v1/employees/{id}` | Now resolves scope for `EMPLOYEE.VIEW`; out-of-scope target → `404`, identical shape (`{"error":{"code":"NOT_FOUND",...}}`) to a nonexistent or cross-tenant ID — a client cannot distinguish the three cases. |
| Every other route in `employee/router.py` | **Unchanged.** Still `_scope: Annotated[object, ...]`, discarded, `COMPANY`-wide behavior for every role (since no role in this system is granted a narrower scope on any other permission code). |
| Every route in `organisation/router.py`, `identity/router.py` | **Unchanged, verified by the full regression suite (§10).** `require_permission()`'s new resolver returns `DataScope(levels={COMPANY})` for every one of their grants (all default to `'COMPANY'`), functionally identical to the prior hard-coded constant. |

No response schema changed. No new request parameters were added.

---

## 6. Security Behavior

| Risk (from the audit / plan §17) | Outcome |
|---|---|
| IDOR — any `EMPLOYEE.VIEW` holder fetches any employee by ID | **Closed** for the two in-scope routes — verified by `test_reportees_scope_sees_direct_reports_only`, `test_self_scope_sees_own_record_only`, `test_reportee_tree_scope_sees_descendants_not_unrelated_branch`. |
| Enumeration via status-code leak | **Not introduced** — scope-miss returns `404`, identical to the existing cross-tenant/not-found response; verified by `test_scoped_actor_forged_id_returns_not_found` and every "unrelated employee" assertion across the new test module. |
| List over-grant | **Closed** for `GET /v1/employees` — verified by every list-assertion in the new test module, plus `test_reportees_scope_manager_with_no_reports_sees_empty_list` (empty scope, not an error). |
| Privilege escalation via `reporting_manager_id` self-assignment | **Not closed — known, pre-existing gap, explicitly demonstrated by an `xfail` test** (`test_reportees_scope_cannot_be_widened_via_self_assignment`), not silently omitted. See §14. |
| Cyclic hierarchy hangs `REPORTEE_TREE` | **Not possible** — depth cap (20) bounds query cost; verified by `test_reportee_tree_scope_terminates_on_cyclic_hierarchy` (a genuine 3-node cycle, inserted directly, resolves and returns within the test's normal timeout). |
| Fail-open on missing `employee_id` | **Does not happen** — verified by `test_self_scope_no_employee_id_sees_nothing` (empty visible set, `404` on any ID, `[]` on list, no error). |
| Cross-tenant access | **Unaffected**, verified unchanged by `test_scoped_actor_cannot_access_cross_tenant_employee` and the full existing tenant-isolation regression suite. |

---

## 7. Tenant Isolation

Unaffected. `get_tenant_context` still runs before `require_permission`, still `404`s on a
company/JWT mismatch before any permission or scope logic executes. Every new query added in this
task is additionally filtered by `company_id`, matching the existing belt-and-suspenders
convention in `employee/repository.py`.

---

## 8. RLS Interaction

Unaffected. `role_permission` carries no RLS policy (confirmed directly against
`scripts/sql/001_init_schema.sql` — composite PK only, no `company_id` column, no
`ENABLE ROW LEVEL SECURITY` statement) — this migration adds a column to it, nothing else.
`employee`/`employee_assignment` keep their existing `FORCE ROW LEVEL SECURITY` + single-predicate
`tenant_isolation` policy, untouched. No RLS-level scope backstop was added (deliberately, per the
plan and the audit's own recommendation).

---

## 9. Query Strategy

- Permission + scope-level lookup: one query (`RbacRepository.get_data_scopes_for_permission`),
  extending the existing `role_permission`/`role`/`user_role`/`user_company` join shape that
  already backed `get_permission_codes_for_user`, filtered additionally by `Permission.code`.
- **Combined with the permission check itself** — `_check_permission` now calls
  `resolve_data_scope` *once* and derives "permission held" from "at least one row returned,"
  rather than calling `has_permission` and `resolve_data_scope` as two separate round trips. This
  is a performance improvement over the architecture plan's original sketch, applying to **every**
  permission-gated route in the app, not just Employee's two.
- `SELF`: no query.
- `REPORTEES`: one indexed lookup against `employee_assignment` (`company_id` +
  `reporting_manager_id` + `effective_to IS NULL`).
- `REPORTEE_TREE`: one recursive CTE (SQLAlchemy Core `.cte(recursive=True)`, fully parameterized,
  no raw string interpolation of any value), depth-capped at 20, same predicate at every level.
- List/detail queries: the resolved `employee_ids` (or `None` for `COMPANY`) is applied as an
  additional `WHERE ... IN (...)` predicate at the SQL layer — never an in-Python post-filter.

---

## 10. Tests

**New:** `apps/api/tests/integration/modules/employee/test_employee_data_scope.py` — 13 tests:

- `SELF`: own record only (detail `200`/`404`, list scoped to one row); no-`employee_id` actor
  sees nothing.
- `REPORTEES`: direct reports visible, unrelated employee and second-level report invisible;
  manager with zero reports gets an empty list, not an error; a closed (simulated-terminated)
  assignment row excludes the employee from a *current* query; a deactivated-but-not-terminated
  employee remains visible.
- `REPORTEE_TREE`: multi-level descendants visible, unrelated branch invisible; a genuine 3-node
  cycle resolves without hanging.
- Security: cross-tenant access blocked (unaffected regression); forged/random UUID → `404`.
- `COMPANY_ADMIN` regression: unchanged company-wide access on both routes.
- Multi-role union: an actor holding `SELF` via one role and `REPORTEES` via another sees both
  their own record and their reports, not just one or the other.
- **`xfail`, not silently omitted**: `test_reportees_scope_cannot_be_widened_via_self_assignment`
  — demonstrates the known, pre-existing write-time cycle/self-elevation gap (§6, §14). Asserts the
  *secure* outcome and is marked `xfail(strict=False)` since the current code does not provide it.

**Results:**
```
tests/integration/modules/employee/test_employee_data_scope.py: 12 passed, 1 xfailed
tests/integration/modules/employee/ + tests/unit/modules/employee/
  + tests/integration/modules/organisation/ + tests/integration/auth/: 398 passed, 1 xfailed
Full backend suite: 503 passed, 1 xfailed, 0 failed
```

No existing test was modified, weakened, or deleted.

---

## 11. Migration

One migration: `apps/api/alembic/versions/20260815120000_role_permission_data_scope.py`.

- Adds `role_permission.data_scope VARCHAR(20) NOT NULL DEFAULT 'COMPANY'` +
  `CHECK (data_scope IN ('SELF','REPORTEES','REPORTEE_TREE','COMPANY'))`.
- **No index added** — see §2's second correction; an equivalent index already existed.
- **No RLS statement** — `role_permission` has none, by design.
- Verified: `alembic upgrade head` → `downgrade -1` → `upgrade head` all run cleanly against the
  live dev database (`hrms-postgres`, container `41378ead51ae`); post-migration schema inspection
  confirmed the column, constraint, and default; 21 pre-existing `role_permission` rows all read
  back `data_scope = 'COMPANY'`; `employee_assignment`'s index set confirmed to contain no
  duplicate after the fix.

---

## 12. Files Changed

**New:**
```
apps/api/alembic/versions/20260815120000_role_permission_data_scope.py
apps/api/tests/integration/modules/employee/test_employee_data_scope.py
docs/modules/employee/25_EMPLOYEE_RBAC_DATA_SCOPE_IMPLEMENTATION_PLAN.md
docs/modules/employee/26_EMPLOYEE_RBAC_DATA_SCOPE_IMPLEMENTATION_REPORT.md (this document)
```

**Modified:**
```
apps/api/src/hrms/core/db/models/identity.py     (+4 lines  — RolePermission.data_scope column)
apps/api/src/hrms/core/rbac/types.py             (DataScopeLevel expanded, DataScope reshaped)
apps/api/src/hrms/core/rbac/service.py           (+46 lines — get_data_scopes_for_permission, resolve_data_scope)
apps/api/src/hrms/core/rbac/dependencies.py      (_check_permission now resolves real scope)
apps/api/src/hrms/modules/employee/repository.py (+110 lines — get_direct_report_ids, get_reportee_tree_ids, scope predicates)
apps/api/src/hrms/modules/employee/service.py    (+200 lines — resolve_visible_employee_ids, get/list_employees scope params)
apps/api/src/hrms/modules/employee/router.py     (2 routes + module docstring)
```

**Confirmed untouched** (via `git status`/`git diff --stat` from repo root): every other Employee
route, `organisation/service.py` (registration flow), `seed/bootstrap.py`, every frontend file,
every other module. The four `tests/**/test_employee_*.py`/`test_employment_service.py` files
shown as modified in `git status` predate this task entirely (present in the working tree before
this session started) and were not touched by this implementation.

---

## 13. Limitations

- Only `GET /employees` and `GET /employees/{id}` are scoped. Every other Employee endpoint —
  create/update/deactivate, and every Employment/Assignment/Compensation route — remains
  `COMPANY`-scoped, unchanged, exactly as the task's Strict Scope Exclusions require.
- `DEPARTMENT`/`BRANCH`/`LEGAL_ENTITY`/`ALL_COMPANIES` scope levels do not exist, not even in the
  enum (deliberately not added — see plan §3).
- No write-time cycle/self-elevation guard on `reporting_manager_id` — demonstrated, not fixed, by
  an explicit `xfail` test (§10).
- No `as_of`/historical scope resolution — both in-scope routes always resolve against "now."
- No real tenant can reach a non-`COMPANY` scope today without direct database access — no default
  role seeding was added to the registration flow (§4), matching this task's stated scope.
- No `sensitive_access_log`. No change to Compensation/Statutory/Banking permission scoping (still
  `COMPANY`-wide, unchanged, out of scope per the task's strict exclusions).
- No frontend change of any kind.

---

## 14. Decisions Made

1. **Scope location**: `role_permission.data_scope` (per `(role, permission)` grant), not per
   `role` or per `user_role` — locked in `docs/architecture/RBAC_DATA_SCOPE_DECISIONS.md` Decision
   A, carried forward unchanged into this implementation.
2. **`core/rbac` vs. `employee` module split** (§2): `core/rbac` resolves scope *levels* only;
   `employee` module resolves levels into concrete employee IDs. Found necessary by inspecting
   `apps/api/.importlinter` during this task — not anticipated in the architecture-level plan.
   Documented as a correction, not silently applied.
3. **No new index** (§2, §11): found, during migration-writing, that the index the plan proposed
   already existed from the E-04 migration. The migration actually shipped adds none. Documented
   as a correction to the plan, with the finding traced to a specific pre-existing migration.
4. **`_check_permission` combines the permission check and scope resolution into one query**
   (§9) — a performance improvement over the architecture-level plan's original two-query sketch,
   applying to every permission-gated route in the app.
5. **Union, not "widest label," for multi-grant resolution** (§3): `SELF` and `REPORTEES` are not
   nested, so a user holding both grants must see the union of what each resolves to — verified by
   the multi-role-union test.
6. **Fail-closed for missing `employee_id`**: an actor with no `Employee` row holding a `SELF`/
   `REPORTEES`/`REPORTEE_TREE` grant sees nothing, never `COMPANY` — verified by test.
7. **Test fixtures insert `EmployeeAssignment` rows directly via the ORM**, not through
   `POST .../assignments`, to avoid needing full Legal Entity/Branch/Department/Designation/Grade
   org structure for every fixture — this test suite only needs `reporting_manager_id`/
   `effective_to` to be correct.
8. **`created_at`/`updated_at` passed explicitly in test fixtures**, not left to `server_default`
   — found necessary after an initial fixture attempt hit a `NotNullViolationError` relying on
   `TimestampMixin`'s server-side default at ORM-insert time; every other inline-fixture pattern
   already in this codebase passes these explicitly, and this implementation now matches that
   established convention rather than the (apparently unreliable, in this driver/session
   combination) alternative.
9. **Default-role seeding was not added** to `organisation/service.py:register_company` — judged
   out of this task's stated scope (the task names only the scope-resolution mechanism and the two
   routes as in-scope; it does not ask for a seeded, assignable role). Named explicitly as a
   limitation (§13), not silently left undone.

---

## 15. Decisions Still Open

Restated from `docs/architecture/RBAC_DATA_SCOPE_DECISIONS.md` — not re-litigated here, not
blocking this task:

- **PD-RBAC-2** (partial): for the *deferred* `DEPARTMENT`/`BRANCH`/`LEGAL_ENTITY` levels only —
  derived-from-own-assignment vs. explicitly-assigned-per-user. Out of this task's scope entirely.
- Whether a real, assignable narrower role should be seeded at company registration (Decisions
  doc, Decision H / Audit `PD-RBAC-4`) — this task's own limitation (§13), not resolved here.

---

## 16. Future `REPORTEE_TREE` Considerations

- The write-time cycle/self-elevation guard (§6, §14) is the highest-priority follow-up — without
  it, `REPORTEE_TREE`'s cost-safety (depth cap) is not matched by correctness-safety.
- `as_of` (historical) `REPORTEE_TREE` resolution, once scope extends to Employment/Assignment/
  Compensation's effective-dated list endpoints, needs the same recursive CTE parameterized by a
  historical date rather than "now" — the query shape is already correct for this; only the
  `as_of` plumbing from the route down to the resolver needs adding.
- `dotted_line_manager_id` is not part of `REPORTEES`/`REPORTEE_TREE` in this implementation
  (matches Doc 19 §5's definition) — if a future requirement wants dotted-line visibility folded
  into the tree, that is a distinct, separately-scoped design question, not an oversight here.

---

## 17. Future `DEPARTMENT`/`BRANCH`/`LEGAL_ENTITY` Scopes

Not built. Blocked on the still-open PD-RBAC-2 question (derived vs. explicitly-assigned). The
`role_permission.data_scope` column and `CHECK` constraint added in this task would need widening
(new allowed values) whenever those levels are built; `DataScopeLevel` (Python enum) would need
the same. No other part of this implementation needs to change to accommodate them — the
`resolve_visible_employee_ids` union pattern extends cleanly to a new level branch.

---

## 18. Frontend Implications

None acted on in this task (explicitly out of scope). The two in-scope routes' response shapes are
unchanged — no frontend code needs to change to keep working against them. A future frontend
implementing scope-aware UI (hiding a nav item or action for an out-of-scope employee) still has
nothing new to consume from these two endpoints beyond "a `404` now means the same three things it
always could" — no new field, header, or error code was introduced.

---

## 19. Rollback Strategy

- **Migration**: purely additive (`ADD COLUMN ... DEFAULT`, one `CHECK` constraint, no index) —
  `downgrade()` drops the constraint and column cleanly; verified (`upgrade` → `downgrade -1` →
  `upgrade` all succeed against the live database).
- **Application code**: reverting `core/rbac/dependencies.py`'s `_check_permission` back to the
  hard-coded `DataScope(level=COMPANY)` constant, and reverting the two router changes, restores
  the exact pre-task behavior; the `role_permission.data_scope` column can be left in place
  (inert) or dropped in a trivial follow-up migration — either way, zero data-loss risk, since no
  existing tenant's role configuration was changed by this task (§4).
- **No user-visible cleanup required on rollback** beyond what a normal code/migration revert
  already handles — no real tenant holds a non-`COMPANY` scoped grant as a result of this task
  (§4), so there is no "un-scope this role" step to perform.

---

## 20. Final Validation Summary

```
pytest (full suite):        503 passed, 1 xfailed, 0 failed
ruff check:                 All checks passed
ruff format --check:        156 files already formatted
mypy (src):                 Success: no issues found in 73 source files
lint-imports:                1 kept, 0 broken
alembic upgrade/downgrade:  clean, both directions, verified against live dev database
git status / diff --stat:   confirmed no file outside §12's list touched
```

No implementation was declared complete before every item above was independently re-run and
observed passing in this session.
