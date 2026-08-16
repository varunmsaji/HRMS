# Employee RBAC Data-Scope Enforcement — Audit

**Status:** Investigation and planning only. No application code, migrations, database schema,
frontend code, or tests were created or modified to produce this document. Nothing was committed.

**Date:** 2026-08-15

**Scope:** Employee (`modules/employee/` — covers Employee identity, Employment, Employee
Assignment, Employee Compensation; E-01/E-03/E-04/E-05/E-06 plus the termination-lifecycle fix).
Statutory (E-07) and Banking (E-08) are referenced only where they change the analysis (they do
not exist in code today).

**Relationship to existing documents:** this audit does not re-derive the system-wide architecture
review already completed today in `docs/architecture/00_HRMS_SYSTEM_ARCHITECTURE.md`,
`docs/architecture/00_SYSTEM_ARCHITECTURE_AUDIT.md`, and
`docs/architecture/HRMS_SYSTEM_DESIGN_BASELINE.md`. Those three documents already identified RBAC
data-scope as the single largest over-granting risk in the system (baseline §11, §18 H-1, §21 #2,
§22) and this audit's own investigation — done independently, then cross-checked against them —
confirms every finding in that trilogy. What this document adds: Employee-specific detail at the
endpoint level, a permission-by-permission matrix, an explicit "who can act on which records"
statement per operation, and a scoped recommendation and sequencing for closing the gap.

**Legend (matches the convention already established in the baseline documents):**
- **FACT** — observed directly in code, schema, migrations, or tests, with a citation.
- **DOC** — stated in an authoritative product/architecture document; not independently verified in
  code, or explicitly not yet built.
- **DISCREPANCY** — DOC and FACT disagree; both are stated, neither is silently resolved.
- **UNDEFINED / REQUIRES PRODUCT DECISION** — no authoritative document defines this; it is not
  invented here.
- **RECOMMENDATION** — a proposed next action, not a locked rule.

---

## 1. Executive Summary

The Employee module has a real, working **permission** layer (JWT auth → DB-backed
`require_permission()` check → 403 on failure) and a real, working **tenant-isolation** layer
(company-scoped RLS + explicit `company_id` filtering in every repository query, cross-tenant
access always `404`). Both are FACT, tested, and correctly implemented for what they claim to do.

Neither of those is **data-scope** enforcement, and the distinction is not cosmetic:

- **Authentication** answers "who is this."
- **Permission** answers "can this user perform this *kind* of action, anywhere in the tenant."
- **Data scope** answers "on *which specific records* can this user perform it."

The system today implements the first two and **does not implement the third at all**. This is not
a partially-built feature with edge-case gaps — it is a hard-coded stub. `require_permission()`
unconditionally returns `DataScope(level=DataScopeLevel.COMPANY)` regardless of the caller's role
(`apps/api/src/hrms/core/rbac/dependencies.py:29`), and every router in the codebase binds that
return value to a variable that is never read again. **Any user holding `EMPLOYEE.VIEW` can read
any employee record in the company by ID. Any user holding `EMPLOYEE.VIEW_COMPENSATION` can read
any employee's full compensation history in the company. There is no code path anywhere —
`core/rbac`, `core/auth`, or the Employee module itself — that narrows a query by branch,
department, legal entity, or manager/reporting relationship.** This is confirmed independently by
four separate research passes (documentation, Employee-module docs, core auth/RBAC/RLS code,
Employee-module code + frontend) in this audit, and matches the pre-existing architecture-audit
trilogy's own finding verbatim.

The documented design (`docs/product/19_RBAC_and_Permission_Matrix.md`) is considerably more
mature than what's built: an 8-level data-scope model (`SELF/REPORTEES/REPORTEE_TREE/DEPARTMENT/
BRANCH/LEGAL_ENTITY/COMPANY/ALL_COMPANIES`), a `VIEW` vs `VIEW_ALL` distinction meant to separate a
Reporting Manager from an HR Manager, and a field-sensitivity classification tier
(`PUBLIC/INTERNAL/SENSITIVE/RESTRICTED`) independent of record-level scope. None of the data-scope
levels beyond `COMPANY` exist in running code. The live `DataScopeLevel` enum has three values
(`COMPANY/TEAM/SELF`) — `REPORTEES` does not exist as a name anywhere in code — and even those
three are moot, since only `COMPANY` is ever produced.

**This is the correct point in the roadmap to fix it.** Employee is the first module to depend on
data-scope, and it is the *only* module built on the stub so far. Attendance, Leave, and Payroll —
next in the roadmap — have documented permission catalogues that lean on `SELF`/`REPORTEES` scoping
more heavily than Employee's own does (payslip visibility, not just employee-directory visibility).
Building those against the current stub would replicate today's over-grant at materially higher
financial/privacy stakes, and retrofitting scope enforcement after three more modules depend on the
stub is a substantially larger, more coordinated change than fixing it once, now, in `core/rbac`.

**This audit does not recommend implementing data-scope enforcement as part of closing out this
task.** Per the task's own instructions, this is investigation and planning only. Section 18 states
what a minimal implementation would need to contain; Section 24 states the exact next task.

---

## 2. Authoritative Requirements

Requirements are drawn only from documents that define them; nothing below is inferred design.

**`docs/product/19_RBAC_and_Permission_Matrix.md`** is the single authoritative source for both the
permission catalogue and the data-scope model. Its access-control equation (§1), quoted verbatim:

> `CAN_ACCESS = module_enabled_on_plan ∧ role_has_permission (with no explicit DENY) ∧
> record_within_data_scope ∧ field_visible_to_role ∧ (not blocked by state, e.g. locked payroll
> period)`
>
> "All five conditions are evaluated server-side. The UI hides what the user cannot do, but the UI
> is never the enforcement point."

This equation is the canonical statement that permission and data-scope are **two independent,
separately-evaluated conditions**, not one check that implies the other. The document's data-scope
table (§5) defines eight levels:

| Scope | Resolves to |
|---|---|
| `SELF` | Only the user's own employee record |
| `REPORTEES` | Direct reports only (one level) |
| `REPORTEE_TREE` | All descendants in the reporting tree (recursive CTE, depth-capped at 20) |
| `DEPARTMENT` | All employees in the specified department(s), including sub-departments |
| `BRANCH` | All employees at the specified branch(es) |
| `LEGAL_ENTITY` | All employees in the specified legal entity |
| `COMPANY` | All employees in the tenant |
| `ALL_COMPANIES` | Cross-tenant — Super Admin only |

`VIEW` vs `VIEW_ALL` (§2): "`VIEW` = within own data scope. `VIEW_ALL` = company-wide, ignoring the
reporting tree. This distinction is what separates a Reporting Manager from an HR Manager." The
14-code Employee permission catalogue is defined in §3.1 (reproduced in Section 3 below), and the
field-sensitivity tiers in §6 (reproduced in Section 10 below).

**`docs/product/02_PRD.md`** cross-cutting business rules (§7):
- BR-01: "An employee's data belongs to exactly one Company; cross-company visibility requires an
  explicit Multi-Company grant."
- BR-11: "An employee sees only their own data; a manager sees their reporting tree; HR sees their
  assigned scope (branch/department/entity)."
- BR-12: "Salary/CTC of any employee is visible only to roles holding the explicit
  `PAYROLL_VIEW_SENSITIVE` permission — including hiding it from reporting managers by default."
  **Note, not resolved by any document read:** this permission-code name does not match Doc 19's
  catalogue (`EMPLOYEE.VIEW_COMPENSATION`) — a naming inconsistency between two product documents,
  restated here rather than silently resolved.

**`docs/adr/0002-postgres-rls-multitenancy.md`** — RLS is scoped explicitly to **company/tenant**
isolation only. It says nothing about within-tenant scoping (branch/department/reporting-line) —
this is not a gap in the ADR, it is simply outside what RLS, as designed, is meant to do. Within-
tenant data-scope is a separate, application-layer concept per Doc 19 §5, not an RLS
responsibility.

**`docs/security/Auth_Architecture.md` §4** independently confirms the permission/scope split as
two distinct rows in its developer-facing table ("Route guard" vs. "Data scope"), though its own
summary of scope levels ("self, team, branch, company," four levels) is internally inconsistent
with Doc 19's eight-level table it cites — a documentation drift between two current (non-
superseded) documents, not something this audit resolves.

**`docs/architecture/HRMS_ARCHITECTURE_DECISION_LOG.md`** (DEC-019) locks that Employee uses a full
resource/action permission catalogue, not one bundled `EMPLOYEE.MANAGE` code, specifically because
"Employee's own RBAC design explicitly relies on the `VIEW`/`VIEW_ALL` distinction to separate a
Reporting Manager from an HR Manager" — the decision log itself flags that the data-scope shape and
the `EMPLOYEE.VIEW_STATUTORY`/`.VIEW_BANKING` literal names are **not yet locked**.

**What no document defines** (flagged here, not invented): which specific roles map to which
specific data-scope level for Employee (the Role × Permission matrix in Doc 19 §4 gives directional
guidance — e.g. "Reporting Mgr ◐ tree," "HR Manager ●" — but does not enumerate a binding,
implementation-ready role list for this tenant's actual role catalogue, since real tenants create
their own roles); how department-scope should behave with the optional, nullable, ≤5-deep
department hierarchy (`docs/modules/employee/05_EMPLOYEE_ARCHITECTURE_DECISIONS.md`) — does
`DEPARTMENT` scope include sub-departments automatically, per Doc 19's own table text ("including
sub-departments"), and if so at what depth; and whether `BRANCH`/`LEGAL_ENTITY` scope is meant to
be assigned per-user (a list of branch IDs a given HR generalist is responsible for) or derived
from the user's own employee record's assignment. **All three are UNDEFINED / REQUIRES PRODUCT
DECISION** — see Section 22.

---

## 3. Current Permission Catalogue

**Seeded and enforced in code today** (confirmed by direct code read, not documentation):

| Code | Defined in | Gates |
|---|---|---|
| `EMPLOYEE.VIEW` | `apps/api/src/hrms/modules/identity/permissions.py:8` (lives in Identity, not Employee) | `GET /employees/{id}`, employment/assignment/compensation-adjacent GET routes below `.VIEW_COMPENSATION`'s own gate |
| `EMPLOYEE.VIEW_ALL` | `apps/api/src/hrms/modules/employee/permissions.py:33-41` | `GET /employees` (list) |
| `EMPLOYEE.CREATE` | same | `POST /employees`, `POST .../employments` |
| `EMPLOYEE.UPDATE` | same | `PATCH /employees/{id}`, `PATCH .../employments/{id}` |
| `EMPLOYEE.DEACTIVATE` | same | `DELETE /employees/{id}` (soft deactivate) |
| `EMPLOYEE.TERMINATE` | same | `POST .../employments/{id}/terminate` |
| `EMPLOYEE.TRANSFER` | same | `POST .../assignments` when `change_type != PROMOTION` |
| `EMPLOYEE.PROMOTE` | same | `POST .../assignments` when `change_type == PROMOTION` |
| `EMPLOYEE.VIEW_COMPENSATION` | same | `GET .../compensation`, `GET .../compensation/{id}` |
| `EMPLOYEE.UPDATE_COMPENSATION` | same | `POST .../compensation` |

10 distinct Employee-domain codes total. **`EMPLOYEE.TERMINATE` is not in the documented 14-code
catalogue** (Doc 19 §3.1) — it is an implementation-time addition, explicitly flagged as such in
the module's own docstring (`employee/permissions.py`). This is a DISCREPANCY worth a small
documentation-correction follow-up (add it to Doc 19), not a code defect.

**Documented in Doc 19 §3.1 but not seeded/enforced anywhere in code:**

| Code | Documented intent | Status |
|---|---|---|
| `EMPLOYEE.UPDATE_SENSITIVE` | Edit PAN/Aadhaar/bank/statutory | Not seeded. Recommended (not confirmed) for E-07. |
| `EMPLOYEE.VIEW_DOCUMENTS` / `.UPLOAD_DOCUMENTS` / `.VERIFY_DOCUMENTS` | Document management | Not seeded — no document sub-resource exists (E-08 scope, unbuilt). |
| `EMPLOYEE.VIEW_PERSONAL_CONTACT` | Personal email/phone/address | **Not seeded — and the fields it's meant to gate (`personal_email`/`personal_mobile`) are returned unconditionally today.** See Section 10. |
| `EMPLOYEE.TRANSFER` / `.PROMOTE` / `.CONFIRM` | Lifecycle actions | `.TRANSFER`/`.PROMOTE` seeded; `.CONFIRM` (confirmation/probation) not seeded — no confirmation workflow exists. |
| `EMPLOYEE.IMPORT` / `.EXPORT` | Bulk operations | Not seeded — no bulk import/export exists (E-09 scope, unbuilt). |
| `EMPLOYEE.GENERATE_LETTER` | Issue letters | Not seeded — unbuilt (E-09). |
| `EMPLOYEE.VIEW_AUDIT` | View change history | Not seeded — no audit-read endpoint exists. |
| `EMPLOYEE.BACKDATE_OVERRIDE` | Change records in a closed payroll period | Not seeded — meaningless until Payroll exists. |

**Named only in a planning document (not Doc 19's own catalogue), and not seeded:**
- `EMPLOYEE.VIEW_STATUTORY` — recommended in `docs/modules/employee/
  21_EMPLOYEE_STATUTORY_IMPLEMENTATION_PLAN.md` (a plan-only document; no implementation report
  exists for E-07 anywhere).
- `EMPLOYEE.VIEW_BANKING` — recommended only in `docs/modules/employee/
  05_EMPLOYEE_ARCHITECTURE_DECISIONS.md`; no E-08 plan or implementation exists at all, and no
  `employee_bank` table exists.

**Enforcement location, mechanism, and data-scope meaning for every seeded code:** enforcement is a
single FastAPI dependency, `require_permission(code)`
(`apps/api/src/hrms/core/rbac/dependencies.py:32-39`), applied per-route. Mechanism: a fresh DB
query per call (`core/rbac/service.py:10-45`, no caching despite a documented 60-second Redis
cache) checking whether the code is attached, via `role → role_permission → user_role →
user_company`, to the caller's `(user_id, company_id)` pair with `user_company.status = 'ACTIVE'`.
**Data-scope meaning: none for any of the 10 codes.** Every successful check returns
`DataScope(level=DataScopeLevel.COMPANY)` unconditionally (`core/rbac/dependencies.py:29`), and
every router discards that return value into an unused, `object`-typed variable. `EMPLOYEE.VIEW`'s
own description ("View employees within scope") is the one place the code's own comment implies
scoping was intended — it is the single largest gap between what a permission's name/description
promises and what it actually enforces.

---

## 4. Current Roles

Company-scoped `Role` rows (`role.company_id` non-null — every role is per-tenant, not global).
Two separate role-provisioning code paths exist, and they diverge in a way worth stating plainly:

**Demo/seed data** (`apps/api/src/hrms/seed/bootstrap.py:68-88`):
- `COMPANY_ADMIN` — every permission in the full catalogue (identity + organisation + employee).
- `EMPLOYEE_VIEWER` — `EMPLOYEE.VIEW` only.

**Real company-registration flow** (`apps/api/src/hrms/modules/organisation/service.py:116,
273-319`) — the path every actual tenant/customer goes through today:
- `COMPANY_ADMIN` — every organisation-management code plus **all** Employee permission codes
  (`service.py:273-289`).
- **No second, narrower role is created.** `EMPLOYEE_VIEWER` (or any equivalent restricted role)
  only exists in the demo seed, not in the live registration path.

**FACT, worth surfacing as its own finding, not previously called out in the baseline trilogy:**
every real tenant's first (and, absent a role-management UI, likely only) user is a
`COMPANY_ADMIN` with company-wide access to every Employee permission, including compensation.
`SETTINGS.ROLE.MANAGE` exists as a permission code (identity module), implying a role-management
capability is intended, but this audit did not find a role-CRUD endpoint or UI to exercise it —
meaning that, as the system stands, **creating a narrower role (e.g. a Reporting Manager who should
only see their own team) requires direct database access, not a self-serve flow.** This compounds
the data-scope gap: even the coarse `VIEW` vs `VIEW_ALL` distinction Doc 19 describes as separating
a Reporting Manager from an HR Manager cannot currently be assigned to a real user without manual
intervention, because the only role a real tenant's registration flow produces already holds
`VIEW_ALL`.

---

## 5. Current Authorization Flow

Traced end-to-end, HTTP request → response, with file:line citations.

1. **ASGI middleware (pre-authentication):** `TenancyMiddleware.dispatch`
   (`apps/api/src/hrms/core/tenancy/middleware.py:13-34`) reads the raw `X-Company-Id` header — no
   membership check yet, since authentication hasn't run — and sets an **unverified**
   `TenantContext` into a `ContextVar`. Absent/invalid header → no context set (silently passed).
2. **Authentication:** `get_current_user`
   (`apps/api/src/hrms/core/auth/dependencies.py:17-47`) decodes the JWT (`sub`, `company_id`,
   `session_id`, optional `employee_id` — **no roles/permissions claim**), then re-fetches `User`
   (must be `ACTIVE`), `Session` (must not be revoked), and `UserCompany` (must be `ACTIVE`) from
   the database — three DB round-trips, not a stateless-JWT-only check.
3. **DB session / RLS variable:** `get_session()`
   (`apps/api/src/hrms/core/db/session.py:71-83`) reads the `ContextVar` set in step 1 and runs
   `SELECT set_config('app.company_id', :company_id, true)` for that transaction. **This is the
   value RLS policies key off**, and it is populated from step 1 (the raw, unverified header), not
   from the JWT resolved in step 2 — see Section 6 for why this matters and what is/isn't verified
   about it.
4. **Tenant validation:** `get_tenant_context`
   (`apps/api/src/hrms/core/tenancy/dependencies.py:14-31`) compares the header value against the
   *JWT-verified* `user.company_id`; mismatch → `404` (never `403` — existence isn't disclosed).
   On match, it re-derives `TenantContext` from the JWT-verified value and calls `set_tenant`
   again — this corrects the **application-layer** `company_id` used for explicit repository
   filtering (step 6), but does not re-run `set_config` on a DB session opened earlier in the same
   request under a different value.
5. **Permission check:** `require_permission(code)`
   (`apps/api/src/hrms/core/rbac/dependencies.py:32-39`) calls `RbacService.has_permission`, a
   fresh DB query joining `permission → role_permission → role → user_role → user_company`,
   filtered by `user_id`, `company_id`, `user_company.status = 'ACTIVE'`. Failure →
   `PermissionDeniedError` → `403`. Success → returns `DataScope(level=COMPANY)`, **always**,
   discarded by the caller.
6. **Repository query:** every Employee repository method takes `company_id` as an explicit
   parameter and adds it to the `WHERE` clause (e.g. `apps/api/src/hrms/modules/employee/
   repository.py:45-55` for `get_employee`) — filtered by company only. **No branch, department,
   legal-entity, or manager predicate is ever added.**
7. **Service layer:** business rules (optimistic-concurrency `version`/`If-Match`, FK-existence
   checks against Organisation, effective-dating close-then-insert) — none of which are data-scope
   checks.
8. **Response:** `DataEnvelope`/`ListEnvelope`, RESTRICTED fields (Compensation only) omitted
   entirely if the caller's permission check failed upstream (never reached this point), never
   masked-and-returned.

**Where data scope is enforced in this flow: nowhere.** Step 5 is the only point in the entire
chain where scope *could* be produced, and it is hard-coded to the broadest possible value.

---

## 6. Current Tenant Isolation

**FACT — this layer works and is well-tested**, independent of the data-scope gap:

- Every tenant-owned table (`employee`, `employment`, `employee_assignment`,
  `employee_compensation`, and 15+ others) has `ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL
  SECURITY` + a single `tenant_isolation` policy comparing `company_id =
  current_setting('app.company_id', true)::uuid`, re-asserted idempotently inline in every Alembic
  migration that touches the table (confirmed by direct grep of all 19 migrations — not via
  `apps/api/scripts/sql/002_row_level_security.sql`, which is dead code, never invoked by Alembic,
  and should not be treated as the live registry by a future reader).
- Every repository method **also** filters `company_id` explicitly in its own query — belt-and-
  suspenders, not RLS-alone.
- Cross-tenant access is always `404`, never `403` — verified by test in every Employee
  implementation report and in `tests/integration/auth/test_auth_security.py:126-151`.
- Mass-assignment protection (`extra="forbid"` on every write schema) is verified by test.

**OPEN item, not asserted broken, flagged for verification before it matters more:** the RLS
session variable (`app.company_id`, step 3 above) is populated from the **raw, unauthenticated**
`X-Company-Id` header set by `TenancyMiddleware` before authentication runs — not directly from the
JWT. `get_tenant_context` (step 4) validates the header against the JWT and 404s on mismatch, and
that 404 does correctly prevent a response from ever being returned to a header-spoofing caller —
but whether `get_session()`'s dependency resolution is *guaranteed* to happen only after
`get_tenant_context` has run and corrected the context, on every single route, was not
independently re-verified route-by-route in this audit (nor in the prior architecture audit, which
raised the identical open item). Because the application-layer check (step 4, JWT-derived) still
gates the final response with a `404`, this is **not** a demonstrated data leak — but it means the
RLS backstop, for at least part of the request lifecycle, may be keyed off a value an attacker
controls, rather than the value the JWT actually authorizes. **RECOMMENDATION:** verify this
ordering explicitly, per route, before Payroll (where a scoping mistake has direct financial
consequences) adds write paths — this is restated, not newly discovered, from
`HRMS_SYSTEM_DESIGN_BASELINE.md §1.5`.

**What tenant isolation does NOT do, stated plainly because it is easy to conflate with data
scope:** RLS and the explicit `company_id` filters answer "is this record in the caller's
company." They do not, and were never designed to, answer "is this record in the caller's branch,
department, or reporting line." Every RLS policy in this codebase has exactly one predicate
(`company_id`) — confirmed by grepping every `CREATE POLICY` statement in every migration; none
adds a second column.

---

## 7. Current RLS Behavior

**What RLS protects (FACT):** cross-tenant reads and writes on every table listed in Section 6.
`FORCE ROW LEVEL SECURITY` means even the table owner's queries are subject to the policy (not just
non-owner roles) — a meaningfully stronger guarantee than `ENABLE` alone.

**What RLS does not protect, and was never designed to (by ADR-0002's own stated scope):**
- Branch-level, department-level, legal-entity-level, or manager/reporting-line-level visibility
  within a single tenant. A `COMPANY_ADMIN` and an `EMPLOYEE_VIEWER` in the same tenant see
  identical row sets from RLS's perspective — RLS cannot express "this branch, not that one,"
  because no policy anywhere carries a second predicate.
- Field-level visibility (RESTRICTED-classified fields) — this is handled, where it's handled at
  all, at the application/schema-serialization layer (Compensation's whole-sub-resource gating),
  not by RLS.

**Tables deliberately without a tenant-isolation policy, and why (FACT):** `company` (the tenant
root — `FORCE`d but no policy of its own, since it has no parent tenant to filter against), `user`/
`session`/`refresh_token` (no `company_id` column — identity is a platform-level concept, a user
can belong to multiple companies via `user_company`), `permission` (global catalogue), `role_permission`/
`user_role` (join tables — rely on their parent table's policy plus an application-layer join
predicate), `plan`/`plan_feature` (global reference data, explicitly documented as such in
migration `20260807160000_plan_and_plan_feature.py`).

**Conclusion, stated once for downstream sections to build on:** RLS is a correctly-implemented,
correctly-tested tenant boundary. It is not, and cannot become, a data-scope mechanism without
adding new predicates and new session-variable plumbing (e.g. a caller's resolved branch/department
set) that does not exist today. Any future data-scope implementation is an **application-layer**
concern primarily, though Section 17 discusses whether an RLS-level backstop is worth adding once
the application-layer scope model is designed.

---

## 8. Current Data-Scope Behavior

Restated precisely, because the entire audit turns on this: **data-scope behavior, as distinct
from tenant isolation, does not exist in running code.** This is not a hedge — it is verified
independently by:

- Direct read of `core/rbac/dependencies.py:29` — `DataScope(level=DataScopeLevel.COMPANY)` is a
  literal constant, not a computed value; no branch of any code path produces `TEAM` or `SELF`.
- Grep of `core/rbac/` and `core/auth/` for `branch_id|department_id|legal_entity_id|manager_id|
  reporting_manager|scope|direct_report|owns` — zero matches for any FK/scope-based filtering
  logic. The only matches are the (unused) `DataScopeLevel` enum values themselves.
- Grep of the Employee module's service/repository layer for the same terms —
  `reporting_manager_id`/`dotted_line_manager_id` appear only in `_validate_manager`
  (`apps/api/src/hrms/modules/employee/service.py:713-730`), which confirms the manager ID resolves
  to a real employee in the same company and isn't self-referential. **This is FK validity
  checking, not access control** — it never appears in a `WHERE` clause that restricts which
  records a *caller* (as opposed to the record being written) can see or touch.
- Every Employee implementation report (E-01 through E-06, and the termination fix) states, in its
  own words, that the endpoints it shipped are "not scoped to self/team" and defers the resolver to
  E-10 — a slice that was never built. `23_TERMINATION_LIFECYCLE_IMPLEMENTATION_REPORT.md`'s own
  closing section names "RBAC data-scope enforcement" as the explicit next step, confirming this is
  a known, acknowledged gap at every point in the module's build history, not a surprise.

**Practical consequence, stated as who-can-see-what today:** any user whose role holds
`EMPLOYEE.VIEW` can fetch any single employee record in the company by ID — including a Reporting
Manager who, per Doc 19's own design intent, should only be able to see their direct/indirect
reports. Any user holding `EMPLOYEE.VIEW_ALL` can list every employee in the company. Any user
holding `EMPLOYEE.VIEW_COMPENSATION` can view every employee's compensation history in the company,
not just their own team's. The `VIEW`/`VIEW_ALL` distinction the catalogue design is built around
currently has **zero behavioral difference** beyond "can this caller list, vs. only look up by ID"
— both grant company-wide visibility once held.

---

## 9. Employee Permission Matrix

**"Who can perform the action?" + "On which employee records?"** — stated per endpoint, per the
critical rule this audit was scoped against. All entries below are FACT (verified by code read),
not documentation.

| # | Endpoint | Who can perform it (permission) | On which records (scope) |
|---|---|---|---|
| 1 | `GET /v1/employees` (list) | `EMPLOYEE.VIEW_ALL` | Every employee in the company. No narrowing. |
| 2 | `POST /v1/employees` (create) | `EMPLOYEE.CREATE` | N/A (creates a new identity) |
| 3 | `GET /v1/employees/{id}` | `EMPLOYEE.VIEW` | **Any** employee in the company, by ID — not self, not reportees, not same-branch/department. |
| 4 | `PATCH /v1/employees/{id}` | `EMPLOYEE.UPDATE` | Any employee in the company. |
| 5 | `DELETE /v1/employees/{id}` (deactivate) | `EMPLOYEE.DEACTIVATE` | Any employee in the company. |
| 6 | `POST /v1/employees/{id}/employments` | `EMPLOYEE.CREATE` | Any employee in the company (target must exist in-company; legal entity must belong to the company). |
| 7 | `GET .../employments` (list/as-of) | `EMPLOYEE.VIEW` | Any employee in the company. |
| 8 | `GET .../employments/{id}` | `EMPLOYEE.VIEW` | Any employee in the company. |
| 9 | `PATCH .../employments/{id}` (legal-entity correction only) | `EMPLOYEE.UPDATE` | Any employee in the company; blocked if the employment isn't `ACTIVE`. |
| 10 | `POST .../employments/{id}/terminate` | `EMPLOYEE.TERMINATE` | Any employee in the company. Cascades to close the employee's open assignment and compensation rows (post-fix). |
| 11 | `GET .../assignments` (list/as-of) | `EMPLOYEE.VIEW` | Any employee in the company. |
| 12 | `GET .../assignments/{id}` | `EMPLOYEE.VIEW` | Any employee in the company. |
| 13 | `POST .../assignments` (transfer/promotion/manager-change/shift-change) | `EMPLOYEE.PROMOTE` if `change_type == PROMOTION`, else `EMPLOYEE.TRANSFER` — selected by the **caller-supplied** `change_type`, not independently re-derived server-side | Any employee in the company. The new branch/department/designation/grade/shift/manager are validated only for existing-in-company — not for whether the *caller* has authority over that branch/department, and not for whether the assigned manager is a legitimate manager in any organizational sense. |
| 14 | `GET .../compensation` (list/as-of) | `EMPLOYEE.VIEW_COMPENSATION` | Any employee in the company — a distinct permission *code*, but the same company-wide *scope* as everything else in this table. |
| 15 | `GET .../compensation/{id}` | `EMPLOYEE.VIEW_COMPENSATION` | Any employee in the company. |
| 16 | `POST .../compensation` (new CTC revision) | `EMPLOYEE.UPDATE_COMPENSATION` | Any employee in the company. No grade CTC-band validation (documented as a deliberate non-enforcement, PD-1 in the E-06 plan — a separate, business-rule gap, not a permission gap). |

**Pattern, stated once:** every row in this table has the identical shape — a company-wide
permission gate, zero record-level narrowing. Row 13 additionally has a secondary, narrower issue:
the permission selected depends on client-supplied input (`change_type`) rather than a server-side
re-derivation (e.g. comparing old vs. new grade to confirm a promotion is actually upward) — this
is a business-logic trust boundary worth noting for Section 16, distinct from the data-scope
finding that dominates every other row.

---

## 10. Sensitive-Data Access Analysis

**Field-sensitivity tiers, as documented** (`docs/product/19_RBAC_and_Permission_Matrix.md §6`):

| Tier | Examples | Meant to be visible to |
|---|---|---|
| `PUBLIC` | Name, employee code, designation, department, work email/phone, photo | Everyone in the company |
| `INTERNAL` | Joining date, reporting manager, branch, shift, blood group | Roles with `EMPLOYEE.VIEW` |
| `SENSITIVE` | Personal mobile/email, address, DOB, emergency contact, dependents | HR roles + self |
| `RESTRICTED` | CTC, salary components, bank account, PAN, Aadhaar, tax declarations, disciplinary records | Explicit permission only, always logged |

"Masked fields are **omitted** from the JSON (not sent as `null`), so that a client bug cannot leak
them and so that response shape reveals nothing" — Doc 19 §6.

**Compensation (RESTRICTED) — implemented correctly for field-gating, not for scope:**
`EMPLOYEE.VIEW_COMPENSATION`/`.UPDATE_COMPENSATION` gate the entire compensation sub-resource —
absent, not masked, for a caller lacking the permission (`apps/api/src/hrms/modules/employee/
router.py:362,381,397`). This is a genuinely well-built pattern and the one place in the module
where field-sensitivity is handled correctly. **What it does not do:** narrow *which employees'*
compensation a caller with the permission can see — once granted, the caller sees every employee's
compensation history in the company (Section 9, rows 14-15). There is also **no read-path audit
log** for compensation access — `sensitive_access_log`, the table meant to record every RESTRICTED-
field read, does not exist anywhere in code (locked to E-10, never built). CTC values are captured
in full in `audit_log`'s write-path snapshots (via `compensation_to_audit_dict`), which means
anyone with future `EMPLOYEE.VIEW_AUDIT` (not seeded) or direct database access can see historical
CTC there — RLS still tenant-bounds this, but it is a second place RESTRICTED data lands without
its own dedicated access control.

**PAN / Aadhaar / UAN (RESTRICTED) — no exposure today, but no protection mechanism either:**
`pan_number_enc`, `aadhaar_number_enc` columns exist on the `employee` table
(`apps/api/src/hrms/modules/employee/models.py`) but have **no read or write path in any shipped
schema** — absent from `EmployeeCreate`/`EmployeeUpdate`/`EmployeeRead` entirely, not masked, never
serialized. This is currently safe by omission, not by design enforcement — the moment E-02
(profile completion, unbuilt) adds a write path, whatever permission gate it uses will be the first
real test of this pattern for these fields. **The `_enc` suffix is misleading**: these are plain,
unencrypted string columns in the schema today; the naming convention implies a guarantee the code
does not provide. This must be resolved before real PAN/Aadhaar data is written, independent of the
data-scope question this audit is centered on.

**Personal contact fields (`personal_email`/`personal_mobile`) — a live over-grant, not a future
risk:** classified `SENSITIVE` in Doc 19 §6, meant to be gated by a documented
`EMPLOYEE.VIEW_PERSONAL_CONTACT` permission. That permission code **does not exist in the seeded
catalogue at all**, and the fields are returned unconditionally on every `EmployeeRead` response
today to anyone holding plain `EMPLOYEE.VIEW`. This is independent of the data-scope gap — it would
still be a problem even if data-scope were fully fixed, because it's a field-visibility gap, not a
record-visibility gap. Flagged here because Section 9's row 3 (`GET /employees/{id}`) is exactly
where this field leaks, and a reader of this audit should not conflate "fix data scope" with "fix
this" — they are two separate fixes.

**Statutory (PF/ESI/PT/tax regime) and Banking — neither exists yet, so neither is a live risk, but
both inherit every gap above the moment they ship:** no `employee_statutory`/`employee_bank` table
exists in the schema. The statutory plan (`21_EMPLOYEE_STATUTORY_IMPLEMENTATION_PLAN.md`) itself
states its RESTRICTED classification for these fields is "inferred by strong analogy," not directly
sourced from any RBAC document — a real, named gap in the source documentation, not merely in the
implementation. Whichever permission codes eventually gate these fields (`EMPLOYEE.VIEW_STATUTORY`,
`EMPLOYEE.VIEW_BANKING` — recommended, not locked) will, if built today, inherit the exact same
company-wide-only scope every other Employee permission has, plus the same missing
`sensitive_access_log` read-path audit gap, unless both are fixed first.

---

## 11. Organisation Hierarchy Scope Analysis

The organisation hierarchy (`Company → Legal Entity → Branch → Department → Designation`) is fully
built and richly modeled (department nesting up to depth 5, branch required legal-entity FK,
designation optional department/grade FKs) — but **none of it is consumed for access-control
purposes anywhere in the codebase.**

- **Legal entity scope:** `employment.legal_entity_id` is a required FK, validated for existence-
  in-company on write (`service.py:288-301`). Never used to restrict which employments/employees a
  caller can see. `LEGAL_ENTITY` data-scope (Doc 19 §5) is entirely unbuilt.
- **Branch scope:** `employee_assignment.branch_id` is nullable-in-schema but required at the
  service layer for the first assignment row. Never used to restrict visibility. `BRANCH`
  data-scope is entirely unbuilt.
- **Department scope:** `employee_assignment.department_id`, same pattern — validated for FK
  existence only. `DEPARTMENT` data-scope is entirely unbuilt. The nested (≤5-deep) department
  hierarchy adds a genuinely UNDEFINED question the moment this is built: does department-scope
  automatically include sub-departments (Doc 19's table text says "including sub-departments," but
  no document specifies the recursion behavior or depth-limit interaction with the existing ≤5
  constraint) — see Section 22.
- **No cross-entity consistency check exists** between an assignment's branch and the employee's
  current employment's legal entity (`docs/modules/employee/
  09_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_PLAN.md §14.4`, confirmed as deliberate, matching
  Organisation's own precedent of not self-enforcing this). This is a data-integrity question
  distinct from the access-scope question this audit centers on, but it matters for scope design:
  if `LEGAL_ENTITY` scope is ever built, it cannot safely assume `employee_assignment.branch`'s
  legal entity matches `employment.legal_entity_id`, because nothing guarantees that today.

**Conclusion:** the organisation hierarchy is a complete, correct *data model*. It is not, today, a
*scoping mechanism* — every FK described above exists purely as business data, validated for
referential integrity, never consulted by an authorization check.

---

## 12. Manager/Self Scope Analysis

- **Self-scope (`SELF`):** `AuthenticatedUser` carries an optional `employee_id` claim from the JWT
  (`apps/api/src/hrms/core/auth/types.py`), meaning the plumbing to know "which employee record is
  *this caller*" already exists at the authentication layer. **It is never used for authorization**
  — no endpoint compares `user.employee_id` to the target `employee_id` in a path parameter to
  grant/restrict access. An employee viewing their own record today does so only because they
  happen to hold `EMPLOYEE.VIEW` (company-wide), not because the system recognizes "this is their
  own record" as a distinct, narrower grant. Doc 19 §7's stated rule — "an HR Manager cannot edit
  their own compensation... self-service actions only; changes route to Company Admin" — has **no
  enforcement anywhere**: nothing prevents a holder of `EMPLOYEE.UPDATE_COMPENSATION` from revising
  their own CTC.
- **Reportee/manager-scope (`REPORTEES`/`REPORTEE_TREE`):** `employee_assignment.
  reporting_manager_id` and `.dotted_line_manager_id` are the only columns in the schema that could
  drive this. Both exist, both are populated on write, and both are validated **only** for FK
  existence and not-self (`service.py:713-730`) — never read back for an authorization decision.
  The documented reference implementation (a recursive CTE over `reporting_manager_id WHERE
  effective_to IS NULL`, depth-capped at 20 to prevent cycles) exists only in Doc 19 §5 and the
  superseded v1 equivalent — it has never been implemented in this codebase at any point in the
  module's build history.
- **Cycle protection:** only a direct self-reference guard exists (a manager cannot be set to the
  employee themself). No multi-hop cycle detection exists — a → b → c → a is not currently
  prevented at the data layer, which would need resolving before a recursive `REPORTEE_TREE` query
  could be trusted not to loop.
- **Self-approval:** Doc 19 §7's "a user can never approve their own request" rule is not
  applicable to Employee today (no approval workflow exists in this module — that's Workflow/
  Approval, ADR-0008, unbuilt) but is worth flagging as a rule that will need the same enforcement
  Employee currently lacks the moment an approval step is added to any Employee action.

---

## 13. Backend Enforcement Gaps

Consolidated, deduplicated list — every item below is FACT (a verified absence in code), not
speculation:

1. **Data-scope is a hard-coded no-op.** `require_permission()` always returns `COMPANY`; no code
   path produces `TEAM`, `SELF`, or any of the documented 8 levels. (Sections 5, 8)
2. **No branch/department/legal-entity/manager filtering exists in any query.** Confirmed by grep
   of `core/rbac`, `core/auth`, and the Employee module's service/repository layer. (Section 8, 11,
   12)
3. **`DataScopeLevel` enum (3 values: `COMPANY/TEAM/SELF`) does not match the documented model (8
   values, including `REPORTEES`/`REPORTEE_TREE`/`DEPARTMENT`/`BRANCH`/`LEGAL_ENTITY`/
   `ALL_COMPANIES`)** — a future implementation needs to decide whether to expand the existing enum
   or replace it; this audit does not decide that here (Section 17 discusses the tradeoff).
4. **No explicit-DENY capability exists in the database.** `role_permission` has no `effect`
   column — every grant is additive; there is no way to express "grant X except this one sub-
   scope" today, which matters if a future data-scope design wants a DENY-style override rather
   than a purely additive scope-narrowing model.
5. **No self/team-vs-record ownership check anywhere**, including for the one case (`SELF` scope)
   where the JWT already carries the exact identifier (`employee_id`) needed to implement it
   cheaply. (Section 12)
6. **Personal-contact fields (`personal_email`/`personal_mobile`) are a live field-visibility over-
   grant**, independent of the data-scope gap. (Section 10)
7. **No `sensitive_access_log` (read-path audit for RESTRICTED fields)** — every Compensation read
   today is unlogged beyond the ordinary write-path `AuditService` calls, which only cover
   mutations, not reads. (Section 10)
8. **No real role-management flow for real tenants** — the only role a live company-registration
   produces holds every Employee permission; a narrower role requires manual DB intervention.
   (Section 4)
9. **The transfer/promotion permission selection trusts client input** (`change_type`) rather than
   independently re-deriving whether a change is actually a promotion server-side. (Section 9, row
   13) — a narrower, business-logic-adjacent gap, listed here for completeness but distinct in kind
   from the data-scope gap.
10. **No CI-enforced "every route has an explicit permission dependency" check** — documented (Doc
    9 §6) as a build requirement, not found anywhere in the codebase. This doesn't cause a gap by
    itself (every current route does have a permission dependency), but it is the kind of
    regression-prevention mechanism that becomes load-bearing the moment more routes and more
    contributors are added.
11. **RLS session-variable population ordering across every route was not independently re-verified
    in this audit** — restated from Section 6, an OPEN item rather than a confirmed gap.

---

## 14. Frontend Enforcement Gaps

**FACT:** grepping `apps/web/src` for `usePermission|PermissionGate|hasPermission|can(` returns
**zero matches**. No permission-gating mechanism — hook, component, or utility — exists anywhere in
the frontend today.

- `UserProfile.permissions: string[]` (`apps/web/src/lib/auth/types.ts`) is fetched into
  `AuthProvider`'s state on every session load, per the `/me` endpoint response, and is **never
  read anywhere else in the frontend codebase** — the data a future gating primitive would need is
  already being fetched; nothing currently consumes it.
- The sidebar nav (`apps/web/src/components/layout/nav-items.ts`) is a static, hardcoded array,
  filtered only by what's been *built* (Organisation entities today), not by what the current
  user's role permits. Its own code comment states this is deliberate build-scope gating, not
  RBAC-based hiding.
- **No Employee UI exists at all** — no directory, no profile screen, no compensation tab, nothing
  under `apps/web/src` matches `*employee*`/`*compensation*`. This means there is currently no
  salary field, no statutory field, no bank field, and no navigation item to hide, disable, or leak
  — the frontend gap is total absence of a gating mechanism, not a specific leaking screen, because
  there is no screen yet.

**What eventually needs to exist, per the design docs' own "absent, not disabled" principle**
(explicit in Doc 19 and the Employee API plan), stated as a requirements list, not an
implementation plan:
1. A `usePermission`/`PermissionGate` primitive, consuming the already-fetched
   `UserProfile.permissions` array, that can hide (not just disable) a nav item, tab, button, or
   field based on the current user's permission set.
2. The same primitive extended (once backend data-scope exists) to also account for scope — a
   button to edit an employee's compensation should be absent not just when the viewer lacks
   `EMPLOYEE.UPDATE_COMPENSATION`, but also when the target employee is outside the viewer's data
   scope, once that concept exists server-side. **Building the frontend primitive now, gated only
   on permission codes, and layering scope-awareness in once the backend produces real scope
   values, is a reasonable two-step sequence** — the primitive itself does not need to wait for
   Section 18's backend work, since permission-code gating alone is already worth building ahead of
   the first Employee UI screen.
3. Compensation, statutory, and bank fields specifically need field-level hiding, matching the
   backend's own "absent, not disabled" pattern for RESTRICTED sub-resources — a raw `403` from an
   API call is not an acceptable substitute for not rendering the field/tab in the first place, per
   the design docs' own stated principle that the server-side check is the enforcement point but
   the UI should never present an action the user cannot complete.
4. Direct-navigation guarding (a user typing `/employees/{id}` directly, for an employee outside
   their scope) needs to degrade gracefully to whatever the API returns (`403`/`404`) with a proper
   error state — this is the one piece that must remain enforced server-side regardless of any
   frontend gating, since client-side hiding is a UX improvement, never a security boundary.

**This audit does not implement any of the above** — per the task's own scope, this is a
requirements list for a future frontend task, not a build plan.

---

## 15. Existing Reusable Infrastructure

What already exists and should be built on, rather than replaced, by a future data-scope
implementation:

- **`DataScope`/`DataScopeLevel` type** (`apps/api/src/hrms/core/rbac/types.py`) — the shape is
  already there (a dataclass carrying a level), even though only one level is ever produced today.
  A future implementation can extend this type rather than inventing a new one, keeping
  `require_permission()`'s existing call signature stable for the ~10 routes that already depend on
  it.
- **`AuthenticatedUser.employee_id`** (`apps/api/src/hrms/core/auth/types.py`) — already carried on
  every authenticated request via the JWT; this is the one piece of information a `SELF` scope
  check needs and already has, at zero additional cost.
- **`employee_assignment.reporting_manager_id`/`.dotted_line_manager_id`** — already populated,
  already effective-dated (so an as-of query for "who was this person's manager on date X" is
  already possible using the existing effective-dating pattern), already FK-validated. The
  recursive-CTE reference implementation for `REPORTEE_TREE` is fully specified in Doc 19 §5 and
  needs no new design work, only implementation.
- **The existing `require_permission()` dependency shape** — every route already calls it and binds
  a `DataScope` return value (currently discarded). A future implementation can make that return
  value real without touching every route's call site — only the routers that need to *consume* the
  scope (add a `WHERE` predicate or an in-memory filter) need changes beyond `core/rbac` itself.
- **The effective-dating `as-of` query pattern** already used by Employment/Assignment/Compensation
  — any scope resolution that depends on "who was this person's manager/branch/department as of
  this date" (relevant for historical queries, not just current-state ones) can reuse this exact
  pattern rather than inventing a new one.
- **The Compensation module's "absent, not disabled" whole-sub-resource gating** — already proven
  out for field-sensitivity; the same pattern (gate the whole response, don't mask individual
  fields) is the right template for whatever Statutory/Banking build next, and arguably for how a
  scope-failure should also behave (a caller outside scope gets `404`, matching the existing cross-
  tenant convention, not a `200` with fewer fields).
- **RLS's session-variable mechanism** (`SET LOCAL app.company_id`) — the existing plumbing for
  passing one scoping value into the DB session could, in principle, be extended to pass additional
  values (e.g. a resolved set of visible branch/department IDs) if a future design wants an RLS-
  level backstop for data-scope, not just an application-layer one. This is a design option
  (Section 17), not a current capability — no such extension exists today.
- **No reusable "scope dependency" abstraction exists yet** (nothing analogous to
  `require_permission()` for scope) — this is exactly the piece Section 17 recommends building.

---

## 16. Security Risks

Ranked by severity, each stated as a concrete scenario, not an abstract description.

**HIGH — RBAC data-scope over-grant (the finding this audit is centered on).** A Reporting Manager
role, holding only `EMPLOYEE.VIEW` (not `.VIEW_ALL`), can nonetheless fetch any employee record in
the company by guessing/enumerating IDs, because `GET /employees/{id}` performs no scope check.
Concretely: a manager in the Sales branch can read the HR Director's employee record, home address,
and (if they also hold `EMPLOYEE.VIEW_COMPENSATION`, which many implementations would reasonably
grant to a "manager" role for their own team) every employee's compensation history company-wide.
The stakes compound: Payroll's documented catalogue leans on the identical `VIEW`/`VIEW_ALL`
pattern for payslip visibility — this is the same risk, at higher blast radius, the moment Payroll
ships against the current stub.

**HIGH — No real role for a restricted grant exists in production.** Because the live
company-registration flow only ever creates a `COMPANY_ADMIN` holding every permission, any tenant
that wants a Reporting-Manager-only or HR-generalist-only role today must have one hand-created via
direct database access — meaning, practically, most real tenants either operate with everyone as a
full admin, or don't have the role at all. This makes the data-scope gap **currently unreachable to
even partially mitigate** through today's available role configuration, since there's no
lesser-privileged role to assign in the first place.

**MEDIUM — Personal-contact-field over-grant.** `personal_email`/`personal_mobile`, documented
`SENSITIVE`, leak to anyone holding plain `EMPLOYEE.VIEW` today — a narrower, field-level version of
the same over-granting pattern, independent of the data-scope fix.

**MEDIUM — No read-path audit trail for RESTRICTED data.** If compensation data is read
inappropriately (whether via the data-scope gap above, or by a legitimately-scoped user simply
looking something up they shouldn't), there is no `sensitive_access_log` record of who read what,
when — only write-path mutations are logged. This matters for incident response: today, "who has
looked at this person's salary" is not an answerable question.

**LOW-MEDIUM — Client-trusted permission routing on transfer/promotion.** The choice between
`EMPLOYEE.TRANSFER` and `EMPLOYEE.PROMOTE` is driven by the caller's own `change_type` field rather
than a server-side comparison of old vs. new grade — a caller holding only `.TRANSFER` (not
`.PROMOTE`) could, in principle, submit a grade-increasing change labeled `MANAGER_CHANGE` and have
it accepted under the weaker permission, since the server does not cross-check the label against
the actual delta. This is a narrower, permission-selection-integrity issue, not a scope issue —
worth fixing, but out of this audit's centered scope.

**LOW — RLS session-variable ordering (Section 6's OPEN item).** Not a demonstrated leak (the
application-layer 404 still gates the final response), but an unverified assumption about
dependency-resolution order that should be confirmed explicitly rather than left implicit,
especially before Payroll adds write paths where a scoping mistake has direct financial
consequences.

---

## 17. Recommended Architecture

**Not a build instruction — this section states what a future implementation should look like,
for the next task (Section 24) to execute, not something implemented as part of this audit.**

**Where the check belongs:** extend `require_permission()`'s existing shape rather than replacing
it. Today it answers one question (does the caller hold this code); it should be extended to
optionally answer a second, related question (what scope does holding it grant this caller) and
return a real `DataScope` value that callers actually consume. This preserves every existing route's
call site shape and avoids a rewrite.

**Where scope resolution should live:** a new, single resolver function in `core/rbac` (e.g.
`resolve_data_scope(user, code) -> DataScope`), callable once per request, that:
1. Looks up the scope level associated with the caller's role/permission grant for this code (this
   requires the `user_role`/`role_permission` schema to actually carry a scope column — today it
   doesn't; see Migration Requirements, Section 21).
2. For `SELF` — returns the caller's own `employee_id` (already available on the JWT, zero extra
   query).
3. For `REPORTEES`/`REPORTEE_TREE` — runs the documented recursive CTE over
   `employee_assignment.reporting_manager_id`, scoped to the caller's own `employee_id` as the root,
   respecting `effective_to IS NULL` (current assignment only) unless an as-of date is supplied.
   Depth-capped (Doc 19 recommends 20) to bound a pathological cycle even though cycle prevention
   should also exist independently (Section 12).
4. For `DEPARTMENT`/`BRANCH`/`LEGAL_ENTITY` — resolves to a set of IDs, either derived from the
   caller's own current assignment (if scope is meant to be "my own branch/department") or from an
   explicit per-user scope assignment (if scope is meant to be "the branches this HR generalist is
   responsible for," which may not be their own). **This is the one place a product decision is
   required before implementation** (Section 22) — the resolver's shape differs materially between
   the two interpretations.
5. Returns `COMPANY`/`ALL_COMPANIES` unchanged from today's behavior for roles that should keep
   full company/cross-company visibility.

**Where scope should be enforced:** at the repository query layer, as an additional predicate
alongside the existing `company_id` filter — not as a post-query, in-memory filter (which would
defeat pagination once pagination exists, and would be needlessly expensive for `COMPANY`-scoped
list queries). Each Employee repository method that currently takes `company_id` should be extended
to optionally take a resolved scope (a set of allowed `employee_id`s, or a `(branch_ids,
department_ids)` tuple, depending on the level) and add the corresponding `WHERE` clause. This
mirrors the "belt-and-suspenders" pattern RLS/`company_id` already establishes — application-layer
enforcement first, with an optional RLS-level backstop considered separately.

**RLS backstop — optional, not required for a first implementation:** Section 15 notes the existing
`SET LOCAL app.company_id` mechanism could, in principle, be extended to pass a resolved scope
value into the session for an RLS policy to also check. **RECOMMENDATION: do not build this in the
first pass.** It adds meaningful complexity (a scope value that can be a set of IDs, not a single
UUID, doesn't fit the existing single-value `current_setting()` pattern cleanly) for a
defense-in-depth benefit that matters less than getting the application-layer enforcement correct
and shipped first. Revisit once the application-layer model is proven across a few endpoints.

**Response behavior for a scope violation:** match the existing cross-tenant convention — `404`,
not `403`, for a record outside the caller's scope but inside their tenant, consistent with "don't
disclose existence to a caller not authorized to know about it," which the codebase already applies
consistently for cross-tenant access.

**`DataScopeLevel` enum — expand or replace:** the live enum (`COMPANY/TEAM/SELF`) should be
expanded to match the documented 8-level model, retiring the ambiguous `TEAM` name in favor of the
documented `REPORTEES`/`REPORTEE_TREE` distinction (Doc 19's own two levels), since "team" doesn't
specify one-level-vs-recursive and the ambiguity would otherwise get resolved arbitrarily by
whichever implementation task builds it first.

---

## 18. Minimal Implementation Scope

**What "minimal" means here:** the smallest change that (a) makes `EMPLOYEE.VIEW`'s `VIEW`/
`VIEW_ALL` distinction real, since that's the one piece of the existing catalogue design already
built around the assumption scope exists, and (b) establishes the resolver/enforcement pattern
future modules (Attendance/Leave/Payroll) can reuse, without attempting all 8 documented scope
levels in one pass.

**In scope for a minimal first implementation:**
1. Add a scope column to whatever table associates a role (or role-grant) with a permission —
   schema change required, see Section 21.
2. Implement `SELF` and `REPORTEES`/`REPORTEE_TREE` resolution (reusing `AuthenticatedUser.
   employee_id` and the existing `reporting_manager_id` data — no new source data needed for
   either).
3. Wire `GET /employees` and `GET /employees/{id}` (the two highest-traffic, most obviously
   over-granted endpoints per Section 9) to consume the resolved scope.
4. Extend the existing permission-matrix test pattern (`test_permission_matrix.py`'s structure) to
   cover scope, not just allow/deny — see Section 20.
5. Expand `DataScopeLevel` to the documented shape (Section 17), even if `DEPARTMENT`/`BRANCH`/
   `LEGAL_ENTITY`/`ALL_COMPANIES` aren't wired to any endpoint yet — having the full enum in place
   now means a later task adding `BRANCH` scope doesn't need to touch the type definition again.

**Deliberately out of scope for a minimal first implementation** (see Section 19 for the fuller
list and reasoning): `DEPARTMENT`/`BRANCH`/`LEGAL_ENTITY` scope (blocked on the product decision in
Section 22 about per-user scope assignment vs. derived-from-own-assignment); extending scope
enforcement to Employment/Assignment/Compensation endpoints beyond the two `GET /employees*` routes
(same resolver, straightforward follow-up once the pattern is proven, but not needed to validate
the pattern itself); an RLS-level backstop (Section 17); the frontend `PermissionGate`/scope-aware
UI work (Section 14 — a separate task, not blocked on this one starting, though it benefits from
waiting for real scope values before wiring scope-aware hiding specifically).

---

## 19. What Must NOT Be Implemented Yet

Explicit "do not build this now" list, each with the reason:

- **`DEPARTMENT`/`BRANCH`/`LEGAL_ENTITY` scope resolution** — the product decision in Section 22
  (per-user assigned scope vs. derived-from-own-assignment) is genuinely unresolved; building
  either interpretation now risks a rework once the decision is made.
- **`ALL_COMPANIES` (Super Admin cross-tenant) scope** — no Super Admin role or platform-level
  concept exists anywhere in the current codebase; this is meaningfully different infrastructure
  (crossing RLS's own tenant boundary deliberately) and should not be bolted onto the same task as
  fixing within-tenant scope.
- **An RLS-level scope backstop** — explicitly deferred per Section 17's own recommendation; adds
  complexity disproportionate to a first implementation.
- **A generic, config-driven, cross-module scope engine** — matches the existing project-wide
  convention (stated explicitly in `HRMS_SYSTEM_DESIGN_BASELINE.md §5` for effective-dating, and
  applicable here by the same reasoning) of hand-implementing a pattern per consuming module rather
  than building a premature generic framework. Employee's `core/rbac` resolver should be built to
  be *reusable* by Attendance/Leave/Payroll, not generalized into a configuration language before a
  second consumer exists to validate the abstraction.
- **Retrofitting scope onto Statutory/Banking (E-07/E-08)** — those modules don't exist yet; scope
  enforcement should be designed once, in `core/rbac`, and then simply *used* by E-07/E-08 when
  they're built, not designed twice.
- **Any frontend scope-aware UI work** — Section 14 already separates the permission-code-only
  gating primitive (buildable now, independent of this task) from scope-aware hiding (which needs
  real backend scope values to exist first); do not block the frontend primitive on this backend
  work, and do not build the scope-aware half before this backend work lands.
- **A DENY-style override mechanism** (`role_permission.effect`) — named in Section 13 as a gap,
  but nothing in the current Employee catalogue design requires DENY semantics to express the
  documented 8-level scope model, which is purely additive (a role has a scope level, not a set of
  allows-minus-denies). Do not add this speculatively.

---

## 20. Test Strategy

Doc 19 §8 (and its unchanged v1-superseded predecessor) names six blocking suites: permission
matrix, cross-tenant leakage, data-scope, field-masking, privilege-escalation, self-action. Of
these, **cross-tenant leakage and a basic permission-matrix (allow/deny only, not scope-aware)
already exist and pass** (`test_auth_security.py`, `test_organisation_security.py`,
`test_permission_matrix.py` — Organisation-only today, no Employee-specific instance found).
**Data-scope, field-masking-for-Employee, privilege-escalation, and self-action tests do not exist
for Employee at all** — this is expected, since there is no scope behavior yet to test.

**For the minimal implementation in Section 18, test coverage must include, at minimum:**
1. A data-driven scope test, following the existing `test_permission_matrix.py` structure but
   extended with a scope dimension: given a role with `SELF` scope, `GET /employees/{other_id}`
   must return `404` (not `403` — matching the existing cross-tenant convention) for any employee
   other than the caller's own record, and `200` for their own.
2. The equivalent for `REPORTEES`/`REPORTEE_TREE`: a fixture with a 3-4-level reporting tree,
   asserting a manager can read their direct and indirect reports and cannot read a sibling branch
   of the tree, a cycle-protection assertion (the depth cap doesn't hang on a malformed/cyclic
   tree), and an as-of-date variant (a manager's tree membership as of a past date, after a
   reporting-line change, resolves correctly).
3. Extend the existing cross-tenant test pattern to also assert that a scope-out-of-bounds record
   in the caller's *own* tenant returns `404`, not merely that cross-tenant records do — the two
   are different code paths (tenant-boundary RLS vs. application-layer scope predicate) and should
   not be assumed to share a test.
4. A privilege-escalation test specific to scope: a caller cannot widen their own effective scope
   (e.g. by manipulating `reporting_manager_id` on their own assignment record, if they hold
   `EMPLOYEE.UPDATE` — this needs an explicit check that a user cannot make themself the manager of
   an employee to gain `REPORTEES` visibility over that employee, since Section 12 already notes no
   cycle/self-elevation protection exists today).
5. A self-action test: Doc 19 §7's "an HR Manager cannot edit their own compensation" rule, once
   `SELF` scope exists to build this check on top of — currently unenforceable because there's no
   scope concept to reference "am I acting on my own record."

**None of the above tests are written as part of this audit** — this section states what the future
implementation task must deliver, per the task's own explicit instruction not to add tests yet.

---

## 21. Migration Requirements, If Any

**A schema change is required** — this cannot be built as an application-layer-only change, because
today's `user_role` table has no column expressing a data-scope grant.
`00_HRMS_SYSTEM_ARCHITECTURE.md §7`'s own column-drift table already names this exact gap: the
documented `user_role.{data_scope, scope_ref_ids, valid_from, valid_to}` columns
(`docs/product/08_Database_Architecture.md §3`) do not exist in the live schema — `user_role` links
only via `user_company_id` + `role_id` today.

**What a future migration would need to add, stated as requirements, not a designed migration**
(this audit does not design the migration itself, per the task's explicit "do not create
migrations" instruction):
- A scope-level column somewhere in the permission-grant chain — either on `user_role` (a scope
  attached to a specific user's specific role assignment, allowing the same role to carry different
  scope for different users — closer to the documented `user_role.data_scope` shape) or on
  `role_permission`/`role` (a scope attached to the role definition itself, meaning every holder of
  that role gets the same scope). **This choice is itself a product/architecture decision** (does
  "Reporting Manager" always mean `REPORTEES`, or can a tenant configure it) — flagged for Section
  22, not resolved here.
- If per-user scope reference IDs are needed (e.g. "this HR generalist is scoped to these three
  specific branches," as opposed to "their own branch, derived from their assignment") — a
  `scope_ref_ids` array or a join table, matching the documented shape, would be required. Whether
  this is needed at all depends on the Section 22 product decision about derived-vs-assigned scope.
- Following every existing migration's own established convention (Section 14 of the baseline doc,
  restated here for this specific future change): `ADD COLUMN IF NOT EXISTS`, RLS
  `ENABLE`+`FORCE`+policy re-asserted inline if the new column lives on an RLS-protected table,
  never a drop-and-recreate.

**No migration is created as part of this audit**, per the task's explicit scope.

---

## 22. Product Decisions Required

Only genuine product/architecture decisions — not build tasks, and not anything already resolved by
an existing document with a stated rationale. Each is marked **UNDEFINED / REQUIRES PRODUCT
DECISION** because no authoritative document answers it.

**PD-RBAC-1. Is data-scope attached to the role definition, or to a specific user's assignment of
that role?**
Why it matters: determines the migration shape (Section 21) and the resolver's lookup path
(Section 17). If every "Reporting Manager" role always means `REPORTEES` scope, the scope can live
on the role/permission grant itself. If two different Reporting Managers in the same tenant could
have different scope (one scoped to their direct tree, another additionally granted a specific
branch), scope must be attached per-user, not per-role.
Options: (1) scope lives on the role/permission grant — simpler, matches Doc 19's Role × Permission
matrix framing directionally; (2) scope lives on the specific user's role assignment
(`user_role.data_scope`) — matches the documented column shape more literally, more flexible, more
migration/resolver complexity.
Recommended: no default invented here — this genuinely changes the resolver's shape, not just its
data source.

**PD-RBAC-2. For `DEPARTMENT`/`BRANCH`/`LEGAL_ENTITY` scope, is the scope derived from the caller's
own current assignment, or explicitly assigned per-user (a list of branch/department IDs this
specific user is responsible for, independent of their own assignment)?**
Why it matters: an HR generalist responsible for three branches, none of which is the branch they
personally sit in, needs explicitly-assigned scope; a branch manager whose scope is simply "my own
branch" needs derived scope. Both are plausible product requirements and the resolver's
implementation differs materially between them.
Options: (1) derived-only (simpler, no new reference-ID storage, but cannot express the HR-
generalist-across-three-branches case); (2) explicitly-assigned only (`scope_ref_ids`, matches
Doc 19's documented column, more flexible, needs a UI/API to manage the assignment); (3) both,
selectable per role.
Recommended: no default invented here — this is the single decision most likely to be wrong if
guessed, since it depends entirely on real customer org-chart shapes not described in any document
read for this audit.

**PD-RBAC-3. Does `DEPARTMENT` scope automatically include sub-departments, and to what depth,
given the existing ≤5-deep nullable self-referencing hierarchy?**
Why it matters: Doc 19's table text says "including sub-departments" but does not specify the
recursion behavior, and the existing department model (`docs/modules/employee/
05_EMPLOYEE_ARCHITECTURE_DECISIONS.md`) allows up to 5 levels of nesting.
Options: (1) always recursive, full depth; (2) exactly one level down; (3) configurable per policy.
Recommended: option 1 (always recursive, full depth) is the simplest reading of the documented text
and requires no new configuration surface — stated as a lean, not a locked recommendation, since no
document confirms it.

**PD-RBAC-4. Should the existing `COMPANY_ADMIN`-only real-registration role flow (Section 4) be
changed to also seed a narrower default role (e.g. `EMPLOYEE_VIEWER`, matching the demo seed), so
that real tenants have a lesser-privileged role available without manual DB intervention?**
Why it matters: today, real tenants cannot practically use any data-scope model once built, because
there is no role in their tenant that would hold anything other than full access. This decision is
adjacent to, not strictly part of, the data-scope implementation itself, but the data-scope work
delivers no practical value to a real tenant without it.
Options: (1) seed a small set of default roles (e.g. `COMPANY_ADMIN`, `HR_MANAGER`, `REPORTING_
MANAGER`, `EMPLOYEE`) at company-registration time, each with a sensible default scope; (2) leave
role creation entirely to a future role-management UI/API, unbuilt today, and treat this as blocking
on that instead.
Recommended: option 1, at minimum for a `REPORTING_MANAGER`-equivalent role with `REPORTEES` scope,
since it's the one scope level Doc 19 explicitly frames as the headline use case, and can be seeded
alongside the minimal implementation in Section 18 without waiting for a full role-management UI.

**PD-RBAC-5. Should `SELF`-scope's "cannot edit own compensation" rule (Doc 19 §7) be a hard,
un-overridable rule, or a per-tenant configurable one?**
Why it matters: Doc 19 §7 itself flags a related rule ("Manager sees salary? No by default... the
tenant may override per role") as something that "will be questioned by clients" — suggesting the
product's own authors anticipate this needs to be configurable, not hard-coded, for at least the
manager-visibility case. Whether the *self-edit* restriction (distinct from the manager-visibility
one) should have the same configurability is not addressed by any document.
Options: (1) hard rule, no override, matching how it's phrased in Doc 19 §7 ("enforced as a hard
rule, not a policy"); (2) tenant-configurable, matching the flagged uncertainty around the adjacent
manager-visibility rule.
Recommended: option 1 (hard rule) for the self-edit case specifically, since Doc 19's own language
for it ("hard rule, not a policy") is more definitive than its language for manager-visibility — but
this is a reading of existing text, not a new decision, and should be confirmed rather than assumed
correct.

---

## 23. Recommended Implementation Sequence

Restated and Employee-specific, consistent with (not duplicating) `HRMS_SYSTEM_DESIGN_BASELINE.md
§21`'s system-wide roadmap, where RBAC data-scope is already sequenced as step #2, immediately after
the terminate-close fix and before any new module:

1. **Resolve PD-RBAC-1 and PD-RBAC-2** (Section 22) — these determine the migration and resolver
   shape; starting the migration before they're answered risks a rework.
2. **Migration**: add the scope column(s) decided in step 1, following the existing `ADD COLUMN IF
   NOT EXISTS` + inline RLS-reassertion convention (Section 21). Seed at least one narrower default
   role per PD-RBAC-4's recommendation, so the new scope model has a real role to attach to.
3. **`core/rbac` resolver**: implement `SELF` and `REPORTEES`/`REPORTEE_TREE` (Section 18) — no new
   source data needed, reuses `AuthenticatedUser.employee_id` and existing `reporting_manager_id`.
   Expand `DataScopeLevel` to the full 8-value shape even though only 2-3 levels are wired yet.
4. **Wire `GET /employees` and `GET /employees/{id}`** to consume the resolved scope, returning
   `404` for out-of-scope records (matching the existing cross-tenant convention).
5. **Tests** (Section 20, items 1-2 minimum) — data-driven scope test extending the existing
   permission-matrix pattern, reporting-tree fixture with cycle-protection assertion.
6. **Extend to the remaining Employee GET endpoints** (Employment, Assignment, Compensation reads
   — Section 9's rows 7-8, 11-12, 14-15) using the same resolver, now that the pattern is proven on
   the two highest-traffic routes.
7. **Resolve PD-RBAC-3** and, if prioritized, add `DEPARTMENT`/`BRANCH`/`LEGAL_ENTITY` scope —
   deliberately sequenced after the `SELF`/`REPORTEES` pass validates the resolver pattern, per
   Section 19's "do not build all 8 levels in one pass" reasoning.
8. **Frontend `PermissionGate`/`usePermission`** (Section 14) — can start as early as step 1
   (permission-code-only gating doesn't depend on any of the above), with scope-aware hiding added
   once step 4 lands.
9. **Then, and only then**, per the system-wide roadmap this audit's findings reconfirm: E-07
   Statutory, E-08 Banking, and eventually Attendance/Leave/Payroll — each inheriting a real
   data-scope mechanism instead of the current stub.

This sequence deliberately does not attempt to fix every gap named in Section 13 in one task — items
6 (personal-contact field leak), 7 (`sensitive_access_log`), and the encryption gap (Section 10) are
real, but independent of data-scope and should not block or be blocked by this sequence; they are
each a smaller, separately-schedulable fix.

---

## 24. Exact Next Implementation Task

**Task name:** RBAC Data-Scope Enforcement — `SELF` and `REPORTEES`/`REPORTEE_TREE` for Employee
read endpoints.

**Precondition, blocking:** PD-RBAC-1 and PD-RBAC-2 (Section 22) must be answered by the product
owner before this task starts implementation — everything else in this task's scope follows
directly from those two answers, and starting the migration before they're resolved risks exactly
the kind of rework this audit's own "fix it now while only one module depends on it" reasoning is
meant to avoid.

**Task scope, once preconditions are resolved:**
1. One migration: the scope column(s) per PD-RBAC-1's answer, plus seeding at least one narrower
   default role (PD-RBAC-4) so the model has something to attach to in a real tenant.
2. `core/rbac` resolver implementing `SELF` and `REPORTEES`/`REPORTEE_TREE` only (not `DEPARTMENT`/
   `BRANCH`/`LEGAL_ENTITY` — deliberately deferred, Section 19).
3. Wire the resolver into `GET /v1/employees` and `GET /v1/employees/{id}` only (the two routes
   Section 9 identifies as highest-traffic and most directly tied to the documented `VIEW`/
   `VIEW_ALL` distinction) — not the full endpoint list in Section 9, which is an explicit,
   separate follow-up (Section 23 step 6).
4. Tests per Section 20 items 1-2, extending the existing `test_permission_matrix.py` pattern.
5. A closeout report following the same format as the E-01 through E-06 implementation reports
   already in `docs/modules/employee/`, explicitly stating what remains out of scope (matching this
   audit's own Section 19 list) so a future reader doesn't mistake a narrow first pass for a
   complete data-scope implementation.

**Explicitly not part of this next task**, restated once more for a future task-scoper reading only
this section: `DEPARTMENT`/`BRANCH`/`LEGAL_ENTITY`/`ALL_COMPANIES` scope; an RLS-level backstop;
any frontend work; extending scope to Employment/Assignment/Compensation endpoints; the personal-
contact field-visibility fix; `sensitive_access_log`; encryption for `_enc`-suffixed columns. Each
of these is real (Section 13, 16) and should be tracked as its own follow-up, not folded silently
into this one.
