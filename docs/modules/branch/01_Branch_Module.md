# Branch Module

Status: **Implemented** (Sprint 3 vertical slice, Tasks 3.1.1/3.1.2). This document covers
purpose, data model, business rules, permissions, audit behavior, tenant isolation, frontend
flow, known limitations, and the future Employee relationship — mirroring the shape of
`docs/modules/legal-entity/01_Legal_Entity_Module.md`. The full endpoint reference lives in
the sibling `02_Branch_API.md`.

## 1. Purpose

A **Branch** is a physical work location under a Legal Entity — the unit that (once
Attendance ships) enforces geofenced punches and that Departments/Employees will be assigned
to. It sits between Legal Entity and Department in the organisation hierarchy:

```
Company (tenant)
    └── Legal Entity
         └── Branch          ← this module
              └── Department  (not yet built — out of scope)
                   └── Designation / Grade
                        └── Employee
```

A Legal Entity may own more than one Branch (e.g. an HQ and one or more regional offices).
For a small customer there is typically exactly one.

**Not built in this slice** (per task scope): Department, Designation, Grade, Employee,
Employment, Attendance, Payroll, Leave, Shift Rules. In particular:
- The interactive geofence-radius map editor is deferred to the Attendance sprint, where
  geofencing is actually enforced against punches. This slice only stores coordinates via
  manual number entry + a documented future static preview.
- `holiday_calendar_id` and `week_off_pattern_id` are intentionally **not** columns on
  `branch` — deferred to Feature 4.1 (`holiday_calendar` expansion) and Task 3.1.3
  (`week_off_pattern`) respectively, per the sprint doc's own forward-reference sequencing.
- The `department.branch_id`-driven "active department blocks deactivation" half of
  FR-ORG-014 is implemented (raw SQL, since Department has no ORM model yet); the
  **employee** half of the same rule is out of scope (Employee does not exist).

## 2. Domain model

**Aggregate boundary**: `Branch` is its own aggregate, referencing both `company_id` (tenant)
and `legal_entity_id` (parent) — same convention as `LegalEntity` referencing `company_id`
rather than being nested inside another aggregate.

**Entity — `Branch`**

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `company_id` | UUID | FK → `company.id`, indexed |
| `legal_entity_id` | UUID | FK → `legal_entity.id` (`ON DELETE RESTRICT`), indexed; required, validated server-side |
| `name` | string (200) | Required |
| `code` | string (30) | Optional |
| `address_line1` / `address_line2` | string (200) | Optional |
| `city` | string (100) | Optional |
| `state_code` | string (10) | Optional; validated against `INDIA_STATE_CODES` (ISO 3166-2:IN) |
| `pincode` | string (10) | Optional; validated as a 6-digit Indian PIN code |
| `timezone` | string (50) | Optional; validated as an IANA timezone identifier when present |
| `latitude` | numeric(9,6) | Optional; range `-90..90` |
| `longitude` | numeric(9,6) | Optional; range `-180..180` |
| `geofence_radius_m` | integer | Optional; must be positive when present |
| `is_active` | boolean | Default `true` |
| `version` | integer | Optimistic concurrency (`If-Match`) |
| `created_at` / `updated_at` / `deleted_at` | timestamptz | `deleted_at` reserved, unused by this slice (deactivation ≠ deletion) |

Field list and types are sourced from `docs/product/08_Database_Architecture.md` §4 and
`docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md` Task 3.1.1 — no fields were invented beyond
what those documents specify. Geofence fields accept partial data (e.g. latitude/longitude
set without a radius) — no doc mandates all-or-nothing.

**`INDIA_STATE_CODES`** (`apps/api/src/hrms/modules/organisation/schemas.py`, mirrored in
`apps/web/src/lib/branch/validate-branch.ts`): a 36-entry static list (28 states + 8 union
territories), including the 2020 Dadra & Nagar Haveli/Daman & Diu merger and the 2019 Jammu &
Kashmir/Ladakh split. No such constant existed anywhere in the codebase before this slice.

## 3. Database

Table `branch` pre-existed as a stub (`id, company_id, legal_entity_id, name, state,
timezone, created_at, updated_at, deleted_at`) from the original baseline migration
(`apps/api/scripts/sql/001_init_schema.sql`), with `department.branch_id` already FK'd to it
(`ON DELETE SET NULL`) and `employee_assignment.branch_id` present as a bare column, even
though neither Department nor Employee has application code yet.

Migration `apps/api/alembic/versions/20260813130000_branch_fields.py`:
- Drops the free-text `state` column (safe pre-launch — only seed/test data existed) and adds
  `code`, `address_line1`, `address_line2`, `city`, `state_code`, `pincode`, `latitude`,
  `longitude`, `geofence_radius_m`, `is_active` (`NOT NULL DEFAULT true`), `version`
  (`NOT NULL DEFAULT 1`).
- Adds a partial index `branch_company_active_idx (company_id, is_active) WHERE deleted_at IS
  NULL` for the common "active branches for this company" query shape.
- Re-asserts RLS idempotently (`ENABLE`/`FORCE ROW LEVEL SECURITY` + `DROP POLICY IF EXISTS`
  + `CREATE POLICY tenant_isolation ... USING (company_id = current_setting('app.company_id',
  true)::uuid)`), exactly mirroring the Legal Entity migration's own reasoning: `branch` is
  nominally covered by the `001_init_schema.sql` RLS loop, but that loop is not the live RLS
  registry for any environment where the table predates an edit to that file — Alembic never
  invokes the standalone `scripts/sql/002_row_level_security.sql`.

`timezone` and the primary key/FK columns already existed and are unchanged in shape.

## 4. Business rules

1. **Legal Entity ownership** — `legal_entity_id` must reference a Legal Entity that exists,
   is not soft-deleted, and belongs to the same tenant. Violations return `422
   INVALID_LEGAL_ENTITY` rather than an opaque FK/500 or a cross-tenant leak. Checked on both
   create and on update (when `legal_entity_id` is included in the patch).
2. **Multiple branches per Legal Entity** — supported; no uniqueness constraint on the pair.
3. **Branch code / name uniqueness** — **not enforced**. No product document (SRS, Database
   Architecture, Sprint 3 plan, RBAC matrix) specifies a uniqueness rule for either
   `branch.code` or `branch.name`, so none was invented — same "don't invent business rules"
   posture as the rest of this slice. This is documented as a known gap in §11.
4. **Deactivation blocking (FR-ORG-014)** — deactivating a Branch (`is_active: false`) is
   blocked with `409 BRANCH_HAS_ACTIVE_DEPARTMENTS` while it has active Departments (raw SQL
   against `department.branch_id`, since Department has no ORM/`is_active` column yet — only
   `deleted_at`). The Employee half of the same rule is out of scope (Employee doesn't exist).
5. **Reactivation** — unblocked; flipping `is_active` back to `true` via `PATCH` is always
   allowed and recorded as a distinct audit action.
6. **Optimistic concurrency** — `version` + `If-Match`, identical mechanism to Company and
   Legal Entity; a mismatch returns `409 STALE_RESOURCE` with the current row snapshot.
7. **Soft deactivation only** — `DELETE /branches/{id}` never hard-deletes; it flips
   `is_active` to `false` via the same code path as `PATCH {is_active: false}` (including the
   department-blocking check and audit trail).
8. **Legal Entity deactivation bug fix** — `OrganisationRepository
   .count_active_branches_for_legal_entity` (used by Legal Entity's own deactivation-blocking
   check) now filters `AND is_active = true` in addition to `deleted_at IS NULL`. Before this
   slice, `branch` had no `is_active` column, so every non-deleted branch was necessarily
   "active" and the filter was unnecessary; once this slice added the column, a
   **deactivated** branch would otherwise still count as active and incorrectly block Legal
   Entity deactivation. Covered by
   `test_legal_entity_deactivation_not_blocked_by_inactive_branch` in
   `apps/api/tests/integration/modules/organisation/test_branch.py`.
9. **India-specific validation** — `state_code` (ISO 3166-2:IN), `pincode` (6-digit Indian PIN
   format), consistent with the same "validate what's named in a spec doc" posture Legal
   Entity used for PAN/GSTIN.

## 5. Permissions

Single permission, matching the Company/Legal Entity precedent (no view/manage split):

```
ORG.BRANCH.MANAGE
```

Confirmed against `docs/product/19_RBAC_and_Permission_Matrix.md:100`, which names this exact
code with no naming conflict (unlike Legal Entity's `ORG.ENTITY.MANAGE` vs.
`ORG.LEGAL_ENTITY.MANAGE` doc/code mismatch). Granted to the `COMPANY_ADMIN` system role at
company registration time (`OrganisationService.register_company`), the same
`get_or_create_permission` → `insert_role_permission` pattern used for
`ORG_LEGAL_ENTITY_MANAGE` — inline in `register_company`, not in `seed/bootstrap.py`.

## 6. Audit

Uses the existing `AuditService` — no new audit infrastructure. Four events, mirroring Legal
Entity's:

- `BRANCH_CREATED`
- `BRANCH_UPDATED`
- `BRANCH_DEACTIVATED`
- `BRANCH_REACTIVATED`

Each with `before_json`/`after_json` snapshots of the `BranchRead` DTO (`entity_type =
"branch"`). No `RESTRICTED`-classified fields on this resource, so no masking is needed.

## 7. Tenant isolation

Identical mechanism to every other `organisation`-module resource: `TenancyMiddleware` +
`get_tenant_context` set both the `TenantContext` contextvar and the Postgres
`app.company_id` session variable; repository queries filter explicitly by `company_id` in
addition to RLS (belt-and-suspenders, ADR-0002). Cross-tenant access — including guessing a
real `branch_id` — returns `404`, never `403` or a leak. Covered by
`test_cross_tenant_branch_get_blocked` / `test_cross_tenant_branch_list_never_leaks` in
`test_cross_tenant_isolation.py`, and `test_create_branch_cross_tenant_legal_entity_rejected`
in `test_branch.py` (a Legal Entity belonging to another tenant is treated as invalid, not
merely inaccessible).

## 8. Frontend flow

- **Routes**: `apps/web/src/app/app/branches/page.tsx` (list + create-dialog) and
  `apps/web/src/app/app/branches/[id]/page.tsx` (detail + inline edit) — the same two-route,
  create-via-dialog shape Legal Entity established, not the sprint doc's earlier
  three-route (`new/` + `[id]/`) draft.
- **Nav**: "Branches" added to `NAV_ITEMS`
  (`apps/web/src/components/layout/nav-items.ts`), between Legal Entities and Setup.
- **Legal Entity relationship in the UI**: the Branch form's first field is a required
  `<NativeSelect>` of the company's Legal Entities (`GET /legal-entities`, reused as-is). If
  no Legal Entity exists yet, the Branches list shows a dedicated empty state directing the
  user to `/app/legal-entities` first rather than a confusing "select a legal entity" error
  on an unusable form — no Legal Entity is ever auto-created.
- **Data fetching**: plain `useState`/`useEffect` + `apiClient`, no TanStack Query — same
  convention as Legal Entity.
- **Geofence entry**: manual latitude/longitude/radius number inputs only; no interactive map
  (see §1 — deferred to Attendance).
- **Lifecycle UI**: deactivate/reactivate confirmation dialog, stale-version ("changed by
  someone else" → reload/cancel), permission-aware error states (403/404), and a dedicated
  toast for the `BRANCH_HAS_ACTIVE_DEPARTMENTS` block — all mirroring Legal Entity's detail
  page exactly.
- **Reused components**: `PageHeader`, `FormField`, `LoadingState`, `ErrorState`,
  `EmptyState`, `toast`, `Card`, `Button`, `Badge`, `Dialog`, `NativeSelect` — zero new
  primitives needed.

## 9. Known limitations

- **No uniqueness enforcement** on `branch.code` or `branch.name`, per §4.3 — no document
  specifies a rule, so none was built. If product wants uniqueness (e.g. per Legal Entity),
  it should be scoped explicitly rather than assumed.
- **No `?legal_entity_id=` filtering** on `GET /branches` — the list is unfiltered client-side
  (same low-cardinality assumption as Legal Entity's own list endpoint). Sorted client-side by
  Legal Entity name if needed by the caller.
- **No interactive geofence map** — manual coordinate entry only (§1, §8).
- **No `holiday_calendar_id`/`week_off_pattern_id`** columns — intentionally deferred (§1).
- **Company dashboard's `branch_count`** (`CompanyDashboardSummary.branch_count`) is
  **unchanged** by this slice and still always returns `null` — wiring it to a real count is
  a Company-module change, out of scope for a Branch-only vertical slice per the task's "do
  not modify unrelated modules" instruction. A future small follow-up can add a
  `count_active_branches_for_company` repository method and a `BRANCHES` `SetupStepDefinition`
  entry, exactly as `service.py`'s existing comment already sketches.
- **E2E "create branch → appears in Departments' branch picker"** (named in the sprint doc) —
  not implementable this slice since Department doesn't exist; deferred to whenever Department
  ships.

## 10. Future Employee relationship

`employee_assignment.branch_id` already exists as a bare column at the DB level (no FK
constraint yet, `apps/api/scripts/sql/001_init_schema.sql`). When Employee ships, an
`Employee`'s current assignment will reference `branch_id`; this module's design does not
block that — `Branch` carries no assumption tying it to a single employee or point in time.
Per FR-ORG-014, once Employee exists, an active-employee count will need to be added
alongside the existing active-Department count in the deactivation-blocking check
(`OrganisationRepository.count_active_departments_for_branch` and the service-layer check in
`OrganisationService.update_branch`).
