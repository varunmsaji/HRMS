# Designation Module

Status: **Implemented**, updated in the subsequent Grade slice to add `grade_id` (§1's
history note below). This document covers purpose, data model, API, permissions, business
rules, lifecycle, audit, tenant isolation, frontend behavior, known limitations, and
unresolved decisions — mirroring the shape of
`docs/modules/department/01_Department_Module.md`. The full endpoint reference lives in the
sibling `02_Designation_API.md`.

## 1. Purpose

A **Designation** is a job title/role — the layer employees will hold once Employee ships. It
sits below Department in the organisation hierarchy but does not require one, and can
optionally reference a Grade (compensation band):

```
Company (tenant)
    └── Legal Entity
         └── Branch
              └── Department
                   └── Designation      ← this module (optional department_id, optional grade_id)
                                              ↑
                                            Grade (independent master data, docs/modules/grade/)
```

Unlike Department's `parent_id` (self-referential hierarchy), a Designation's `department_id`
is **optional** — the DB schema's own nullable FK (`ON DELETE SET NULL`) and FR-ORG-006's own
"department (optional)" wording both confirm a designation does not need to belong to a
department (e.g. a company-wide role like "CEO"). A Designation has no hierarchy of its own
this slice — see §9.2 for `next_designation_id`'s more limited, passive treatment.

**History**: `grade_id` was originally excluded from this module's first implementation
because Grade did not exist yet (this task's own boundary at the time explicitly forbade
building Grade — see `docs/modules/designation/00_DESIGNATION_AUDIT.md` §5.7 for that
reasoning, preserved for the historical record). The subsequent Grade vertical slice added
`designation.grade_id` per FR-ORG-006/Database Architecture's own documented field set — see
`docs/modules/grade/00_GRADE_AUDIT.md` §3 and `docs/modules/grade/01_Grade_Module.md` §3 for
the full relationship analysis. This document now reflects that current state.

**Not built** (per task scope, both slices): Employee, Attendance, Shift Rules, Payroll,
Recruitment. In particular:
- **`jd_document_id`** is not a column — no document-management module exists to reference
  (stated explicitly in the Sprint 3 plan itself, not a decision either slice needed to
  make).
- **`next_designation_id`** exists at the DB/model level only (Sprint 3 Scope Decision D10)
  — not exposed by any schema, service method, or frontend field; see §9.2.

## 2. Domain model

**Aggregate boundary**: `Designation` is its own aggregate, referencing `company_id` and
optionally `department_id`/`grade_id` — same convention as Department referencing
`branch_id`.

**Entity — `Designation`**

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `company_id` | UUID | FK → `company.id`, indexed |
| `department_id` | UUID, nullable | FK → `department.id` (`ON DELETE SET NULL`), indexed; **optional** |
| `grade_id` | UUID, nullable | FK → `grade.id` (`ON DELETE SET NULL`), indexed; **optional** — added in the Grade slice |
| `title` | string (150) | Required — the "name" field, already called `title` at the DB level |
| `code` | string (30) | Optional |
| `next_designation_id` | UUID, nullable | **Schema/DB only** — not exposed via API/service/UI this slice (§9.2) |
| `is_active` | boolean | Default `true` |
| `version` | integer | Optimistic concurrency (`If-Match`) |
| `created_at` / `updated_at` / `deleted_at` | timestamptz | `deleted_at` reserved, unused (deactivation ≠ deletion) |

Field list sourced from `docs/product/08_Database_Architecture.md` §4 and FR-ORG-006 —
`jd_document_id` deliberately excluded, §1.

## 3. API

Per this task's own instructions, matching `docs/product/09_API_Standards.md:245` exactly:

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/v1/designations` | `ORG.DESIGNATION.MANAGE` | List, company-scoped, unfiltered |
| POST | `/v1/designations` | `ORG.DESIGNATION.MANAGE` | Create; `is_active` always `true` |
| GET | `/v1/designations/{designation_id}` | `ORG.DESIGNATION.MANAGE` | 404 (never 403) cross-tenant or not-found |
| PATCH | `/v1/designations/{designation_id}` | `ORG.DESIGNATION.MANAGE` | `If-Match: <version>`; partial update |
| DELETE | `/v1/designations/{designation_id}` | `ORG.DESIGNATION.MANAGE` | Soft deactivation only; `If-Match`; `200 DataEnvelope<DesignationRead>`, not `204` |

Full field/error reference in `02_Designation_API.md`.

## 4. Business rules

1. **Department ownership** — `department_id`, when provided, must reference a Department
   belonging to the same tenant (`422 INVALID_DEPARTMENT`, same shape as Department's own
   `INVALID_BRANCH`).
2. **Grade ownership** — `grade_id`, when provided, must reference a Grade belonging to the
   same tenant (`422 INVALID_GRADE`, same shape as `INVALID_DEPARTMENT`). Added in the Grade
   slice; see `docs/modules/grade/01_Grade_Module.md` §3.
3. **No hierarchy/cycle logic** — unlike Department's `parent_id`, Designation's
   `department_id`/`grade_id` reference different entity types, not itself. The one
   genuinely self-referential field, `next_designation_id`, is not exposed this slice, so
   there is no settable self-reference to validate a cycle against.
4. **No documented deactivation-blocking rule.** FR-ORG-014's literal text blocks
   deactivation of an org unit "only if no active employee is assigned" — Employee doesn't
   exist, so this can't be checked. The Sprint 3 plan names one other blocker — "blocked if
   `next_designation_id` of another designation points to it" — but that rule presumes
   `next_designation_id` is settable, which D10 (the same decision that justifies adding the
   column at all) says it is not this slice. **This slice ships Designation
   deactivation/reactivation with no active-dependency check.** See
   `docs/modules/designation/00_DESIGNATION_AUDIT.md` §5.3/§5.4 for the full reasoning.
5. **Uniqueness** — not enforced on `code` or `title`. No product document specifies a
   uniqueness rule for either, so none was invented.
6. **Optimistic concurrency** — `version` + `If-Match`, identical mechanism to every other
   organisation-module resource.
7. **Soft deactivation only** — `DELETE` never hard-deletes; flips `is_active` to `false` via
   the same code path as `PATCH {is_active: false}`.

## 5. Permissions

Single permission, matching the Company/Legal Entity/Branch/Department precedent:

```
ORG.DESIGNATION.MANAGE
```

Confirmed against `docs/product/19_RBAC_and_Permission_Matrix.md:100` and
`docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md:1412` with no naming conflict. Granted to
`COMPANY_ADMIN` at company registration time, the same `get_or_create_permission` →
`insert_role_permission` pattern used for `ORG_DEPARTMENT_MANAGE`/`ORG_BRANCH_MANAGE`.

## 6. Audit

Uses the existing `AuditService`. Four events, mirroring Department's:

- `DESIGNATION_CREATED`
- `DESIGNATION_UPDATED`
- `DESIGNATION_DEACTIVATED`
- `DESIGNATION_REACTIVATED`

Each with `before_json`/`after_json` snapshots of the `DesignationRead` DTO (`entity_type =
"designation"`). No `RESTRICTED`-classified fields.

## 7. Tenant isolation

Identical mechanism to every other `organisation`-module resource: `TenancyMiddleware` +
`get_tenant_context`, belt-and-suspenders `company_id` filtering in every repository method,
RLS re-asserted idempotently in the migration. Cross-tenant access — including a guessed
`designation_id` or a cross-tenant `department_id` — returns `404`/`422` as appropriate,
never leaks. Covered by
`test_cross_tenant_designation_get_blocked`/`test_cross_tenant_designation_list_never_leaks`
in `test_cross_tenant_isolation.py`, and the department/grade cross-tenant rejection tests in
`test_designation.py`/`test_grade.py`.

## 8. Frontend behavior

- **Routes**: `apps/web/src/app/app/designations/page.tsx` (list + create-dialog) and
  `apps/web/src/app/app/designations/[id]/page.tsx` (detail + inline edit) — the same
  two-route shape Department established.
- **Nav**: "Designations" added to `NAV_ITEMS`, between Departments and Grades.
- **Department & Grade pickers**: the Designation form has two optional `<NativeSelect>`
  pickers, "Department" (from `GET /departments`) and "Grade" (from `GET /grades`, added in
  the Grade slice) — no exclusion logic needed for either (unlike Department's own "Parent
  department" picker), since Designation has no self-referential hierarchy this slice.
- **List display**: each row shows its department and grade names (resolved client-side from
  the already-loaded lists) alongside the active/inactive badge.
- **Lifecycle UI**: deactivate/reactivate confirmation dialog, stale-version handling — same
  as Department. No "blocked deactivation" toast exists for Designation (§4.4 — no rule to
  block on), and no cycle/depth-conflict error handling exists (Designation has no hierarchy
  to conflict on this slice).
- **Reused components**: `PageHeader`, `FormField`, `LoadingState`, `ErrorState`,
  `EmptyState`, `toast`, `Card`, `Button`, `Badge`, `Dialog`, `NativeSelect` — zero new
  primitives.

## 9. Known limitations

- **`next_designation_id`** exists at the DB level only; no UI, no API exposure, and the
  Sprint 3 plan's own "blocked if referenced by `next_designation_id`" deactivation rule is
  not implemented, since nothing can populate the column that rule would query (§4.4, audit
  §5.4).
- **No `jd_document_id`** — no document-management module exists to reference.
- **No uniqueness enforcement** on `code`/`title` — no document specifies a rule.
- **No deactivation-blocking rule** — see §4.4. A designation can be deactivated freely this
  slice regardless of any other row that might reference it.
- **No query-param filtering** on `GET /designations` (`department_id`/`status` named in the
  Sprint 3 plan's own API table) — no organisation-module list endpoint implements filtering
  yet; deferred module-wide, not invented per-resource.
- **`designation_count` does not exist on the Company dashboard** — unlike `department_count`
  (which pre-existed Department's own slice as a `None`-returning placeholder),
  `CompanyDashboardSummary` has no `designation_count` field at all; adding one is out of
  scope for a single-module vertical slice.

## 10. Unresolved product decisions

- Whether `next_designation_id` will ever get schema/UI exposure (career-path visualization),
  and if so, whether the Sprint 3 plan's "blocked if referenced" deactivation rule should be
  implemented at that point.
- Whether Designation deactivation should eventually be blocked by active Employee
  assignments (FR-ORG-014) once Employee ships — deferred, not decided here.
- Whether `code`/`title` uniqueness should be enforced — no product document currently
  specifies a rule either way.

## 11. Future Employee relationship

`employee_assignment.designation_id` and `employee_assignment.grade_id` already exist as bare
columns at the DB level (no FK constraint yet). Per FR-ORG-014, once Employee exists, an
active-employee count will need to be added to Designation's deactivation check (currently
absent, §4.4).
