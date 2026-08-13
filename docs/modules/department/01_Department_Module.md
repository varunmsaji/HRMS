# Department Module

Status: **Implemented** (Sprint 3 vertical slice, scoped per this task's own Phase 3–9
instructions — narrower than the full Sprint 3 plan's Task 3.2.1–3.2.3; see §9). This
document covers purpose, data model, hierarchy, API, permissions, business rules, lifecycle,
audit, tenant isolation, frontend behavior, known limitations, and the future Employee
relationship — mirroring the shape of `docs/modules/branch/01_Branch_Module.md`. The full
endpoint reference lives in the sibling `02_Department_API.md`.

## 1. Purpose

A **Department** is an organisational unit — the layer employees will be assigned to once
Employee ships. It sits between Branch and Designation in the organisation hierarchy, and can
also nest under a parent Department to model sub-teams:

```
Company (tenant)
    └── Legal Entity
         └── Branch
              └── Department          ← this module
                   ├── Sub-department (optional, max 5 levels)
                   └── Designation     (not yet built — out of scope)
```

Unlike Branch's required `legal_entity_id`, a Department's `branch_id` is **optional** — the
DB schema's own nullable FK (`ON DELETE SET NULL`) and Database Architecture's
`department (company_id, branch_id?)` annotation both confirm a department does not need to
belong to a branch. A Department's `parent_id` is also optional, self-referential, and capped
at 5 hierarchy levels with cycle rejection (FR-ORG-005).

**Not built in this slice** (per task scope): Designation, Grade, Holiday Calendar, Shift
Rules, Employee, Attendance, Leave, Payroll, Cost Centre. In particular:
- **`GET /v1/departments/tree` is not built.** The Sprint 3 plan names a recursive-CTE tree
  endpoint feeding a tree-view frontend; this task's own Phase 7 instructions instead ask for
  a flat list + detail page mirroring Branch's UI. Hierarchy is still fully enforced
  server-side (cycle/depth rules) and surfaced via "Branch"/"Parent department" fields in the
  list/detail views — see §8.
- **`cost_centre_id`** is not a column on `department` this slice — Cost Centre is a separate,
  not-yet-built table (Sprint 3 Task 3.2.2), out of scope here.
- **`head_employee_id`** exists at the DB/model level only (per Sprint 3's binding Scope
  Decision D10) — not exposed by any schema, service method, or frontend field.

## 2. Domain model

**Aggregate boundary**: `Department` is its own aggregate, referencing `company_id`,
optionally `branch_id`, and optionally `parent_id` (self-referential) — same convention as
Branch referencing `legal_entity_id`.

**Entity — `Department`**

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `company_id` | UUID | FK → `company.id`, indexed |
| `branch_id` | UUID, nullable | FK → `branch.id` (`ON DELETE SET NULL`), indexed; **optional** |
| `parent_id` | UUID, nullable | FK → `department.id` (`ON DELETE SET NULL`), indexed; **optional**, self-referential |
| `name` | string (150) | Required |
| `code` | string (30) | Optional |
| `head_employee_id` | UUID, nullable | **Schema/DB only** — not exposed via API/service/UI this slice (§1) |
| `is_active` | boolean | Default `true` |
| `version` | integer | Optimistic concurrency (`If-Match`) |
| `created_at` / `updated_at` / `deleted_at` | timestamptz | `deleted_at` reserved, unused (deactivation ≠ deletion) |

Field list sourced from `docs/product/08_Database_Architecture.md` §4 and FR-ORG-005 — no
fields invented beyond what those documents specify (`cost_centre_id` deliberately excluded,
§1).

## 3. Hierarchy (FR-ORG-005)

A Department's `parent_id`, when provided, is validated server-side on both create and
update:

1. **Ownership** — the candidate parent must exist, not be soft-deleted, and belong to the
   same tenant (`422 INVALID_PARENT_DEPARTMENT` otherwise — never a raw FK/500 or a
   cross-tenant leak).
2. **Cycle rejection** — a department can never become its own ancestor. Checked two ways:
   a direct self-reference (`parent_id == own_id`) is rejected immediately; an indirect cycle
   (setting a department's parent to one of its own current descendants) is rejected by
   walking the candidate parent's ancestor chain and checking whether the department's own id
   appears in it. Both return `409 CONFLICT DEPARTMENT_CYCLE_DETECTED`.
3. **Max depth** — the hierarchy is capped at 5 levels (root = depth 1). Assigning a parent
   whose own ancestor-chain length is already 5 is rejected with `409 CONFLICT
   DEPARTMENT_MAX_DEPTH_EXCEEDED`.

Implemented as a small iterative ancestor walk
(`OrganisationRepository.get_department_ancestor_chain`, bounded at 6 hops) rather than a SQL
recursive CTE — sufficient for a 5-hop-max bounded check, and this slice does not build the
`/tree` endpoint that would otherwise justify a CTE (§1, §9).

## 4. API

Per this task's own instructions:

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/v1/departments` | `ORG.DEPARTMENT.MANAGE` | List, company-scoped, unfiltered |
| POST | `/v1/departments` | `ORG.DEPARTMENT.MANAGE` | Create; `is_active` always `true` |
| GET | `/v1/departments/{department_id}` | `ORG.DEPARTMENT.MANAGE` | 404 (never 403) cross-tenant or not-found |
| PATCH | `/v1/departments/{department_id}` | `ORG.DEPARTMENT.MANAGE` | `If-Match: <version>`; partial update; hierarchy re-validated when `parent_id` changes |
| DELETE | `/v1/departments/{department_id}` | `ORG.DEPARTMENT.MANAGE` | Soft deactivation only; `If-Match`; `200 DataEnvelope<DepartmentRead>`, not `204` |

Full field/error reference in `02_Department_API.md`.

## 5. Business rules

1. **Branch ownership** — `branch_id`, when provided, must reference a Branch belonging to
   the same tenant (`422 INVALID_BRANCH`, same shape as Branch's own `INVALID_LEGAL_ENTITY`).
2. **Parent ownership + hierarchy** — see §3.
3. **No documented deactivation-blocking rule.** FR-ORG-014's literal text blocks
   deactivation of an org unit "only if no active employee is assigned" — Employee doesn't
   exist, so this can't be checked. No document states that Department deactivation is
   blocked by active sub-departments or Designations (unlike Branch, whose own sprint task
   explicitly named "blocked by active department"). **This slice ships Department
   deactivation/reactivation with no active-dependency check** — a department with active
   sub-departments can still be deactivated. See
   `docs/modules/department/00_DEPARTMENT_AUDIT.md` §5.3/§8.1 for the full reasoning; revisit
   once Employee (and possibly Designation) exist.
4. **Uniqueness** — not enforced on `code` or `name`. No product document specifies a
   uniqueness rule for either, so none was invented.
5. **Optimistic concurrency** — `version` + `If-Match`, identical mechanism to Legal Entity
   and Branch.
6. **Soft deactivation only** — `DELETE` never hard-deletes; flips `is_active` to `false` via
   the same code path as `PATCH {is_active: false}`.
7. **Branch's own bug fix** — `OrganisationRepository.count_active_departments_for_branch`
   (used by Branch's own FR-ORG-014 deactivation-blocking check) now filters `AND is_active =
   true` in addition to `deleted_at IS NULL`. Before this slice, `department` had no
   `is_active` column, so every non-deleted department was necessarily "active." Once this
   slice added the column, a *deactivated* department would otherwise still count as active
   and incorrectly block Branch deactivation — the same mechanical fix Branch's own slice
   made to Legal Entity's equivalent check. Covered by
   `test_deactivating_branch_not_blocked_by_inactive_department` in
   `apps/api/tests/integration/modules/organisation/test_department.py`.

## 6. Permissions

Single permission, matching the Company/Legal Entity/Branch precedent:

```
ORG.DEPARTMENT.MANAGE
```

Confirmed against `docs/product/19_RBAC_and_Permission_Matrix.md:100` with no naming
conflict. Granted to `COMPANY_ADMIN` at company registration time, the same
`get_or_create_permission` → `insert_role_permission` pattern used for
`ORG_BRANCH_MANAGE`/`ORG_LEGAL_ENTITY_MANAGE`.

## 7. Audit

Uses the existing `AuditService`. Four events, mirroring Branch's:

- `DEPARTMENT_CREATED`
- `DEPARTMENT_UPDATED`
- `DEPARTMENT_DEACTIVATED`
- `DEPARTMENT_REACTIVATED`

Each with `before_json`/`after_json` snapshots of the `DepartmentRead` DTO (`entity_type =
"department"`). No `RESTRICTED`-classified fields.

## 8. Tenant isolation

Identical mechanism to every other `organisation`-module resource: `TenancyMiddleware` +
`get_tenant_context`, belt-and-suspenders `company_id` filtering in every repository method,
RLS re-asserted idempotently in the migration. Cross-tenant access — including a guessed
`department_id`, a cross-tenant `branch_id`, or a cross-tenant `parent_id` — returns
`404`/`422` as appropriate, never leaks. Covered by
`test_cross_tenant_department_get_blocked`/`test_cross_tenant_department_list_never_leaks` in
`test_cross_tenant_isolation.py`, and the branch/parent cross-tenant rejection tests in
`test_department.py`.

## 9. Frontend behavior

- **Routes**: `apps/web/src/app/app/departments/page.tsx` (list + create-dialog) and
  `apps/web/src/app/app/departments/[id]/page.tsx` (detail + inline edit) — the same
  two-route shape Branch/Legal Entity established, **not** the Sprint 3 plan's tree-view +
  `Sheet`-drawer design (see §1's explicit scope note — this is a deliberate, documented
  divergence, not a silent omission).
- **Nav**: "Departments" added to `NAV_ITEMS`, between Branches and Setup.
- **Hierarchy in the UI**: the Department form has two optional `<NativeSelect>` pickers —
  "Branch" (from `GET /branches`) and "Parent department" (from `GET /departments`, the same
  flat list already loaded). When editing, the current department and all of its descendants
  are excluded from its own "Parent department" options, computed client-side from the flat
  list (`descendantIds()` in `lib/department/validate-department.ts`) — the same exclusion
  rule the Sprint 3 plan names for its tree combobox, applied here to a flat picker instead.
- **Hierarchy conflict errors**: `409 DEPARTMENT_CYCLE_DETECTED`/`409
  DEPARTMENT_MAX_DEPTH_EXCEEDED` from the API are surfaced as a field-level error on the
  "Parent department" picker, not a generic toast.
- **List display**: each row shows its branch name and parent department name (resolved
  client-side from the already-loaded branch/department lists) alongside the active/inactive
  badge.
- **Lifecycle UI**: deactivate/reactivate confirmation dialog, stale-version handling — same
  as Branch. No "blocked deactivation" toast exists for Department (§5.3 — no rule to block
  on).
- **Reused components**: `PageHeader`, `FormField`, `LoadingState`, `ErrorState`,
  `EmptyState`, `toast`, `Card`, `Button`, `Badge`, `Dialog`, `NativeSelect` — zero new
  primitives.

## 10. Known limitations

- **No `GET /v1/departments/tree` endpoint or tree-view UI** — flat list/detail pages instead,
  per this task's explicit Phase 7 instructions (§1, §9).
- **No Cost Centre** — `cost_centre_id` not added; Cost Centre is Sprint 3 Task 3.2.2,
  out of scope here.
- **No uniqueness enforcement** on `code`/`name` — no document specifies a rule.
- **No deactivation-blocking rule** — see §5.3. A department with active sub-departments can
  be deactivated freely this slice.
- **`head_employee_id`** exists at the DB level only; no UI, no API exposure, no validation
  against real employee rows (Employee doesn't exist).
- **Company dashboard's `department_count`** remains `null`, unchanged by this slice — same
  call Branch made for `branch_count`; wiring it is a Company-module change, out of scope for
  a Department-only vertical slice.

## 11. Future Employee relationship

`employee_assignment.department_id` already exists as a bare column at the DB level (no FK
constraint yet). `department.head_employee_id` already exists as a passive nullable FK column
(§1, per Scope Decision D10) — when Employee ships, a Department's head can be set through
that column without a further migration. Per FR-ORG-014, once Employee exists, an
active-employee count will need to be added to Department's deactivation check (currently
absent, §5.3), alongside whatever rule product specifies for active sub-departments/Designations
at that time.
