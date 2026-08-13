# Legal Entity Module

Status: **Implemented** (Sprint 3A vertical slice). This is a single consolidated document
covering purpose, data model, API, permissions, business rules, tenant isolation, frontend
flow, audit behavior, and future relationships — mirroring the topics covered by the 7-file
`docs/modules/company/` set, but kept as one file for this slice given its smaller surface
area. Split into the same 7-file structure if/when this module grows (e.g. once Branch is
added to it).

## 1. Purpose

A **Legal Entity** is the legally registered company that employs a workforce and is
responsible for payroll, statutory compliance, and employment contracts (PF/ESI/TAN/PAN/GST
registrations). It sits between Company (tenant) and Branch in the organisation hierarchy:

```
Company (tenant)
    └── Legal Entity        ← this module
         └── Branch          (not yet built — Branch/Department/etc. are out of scope)
              └── Department
                   └── Designation / Grade
                        └── Employee
```

A company may own more than one Legal Entity (e.g. `ABC Technologies Pvt Ltd` and
`ABC Services Pvt Ltd` under one `ABC Group` company tenant). For a small customer there is
typically exactly one.

**Not built in this slice** (per task scope): Branch, Department, Designation, Grade,
Employee, Employment, Payroll, Attendance, Leave. `Employee`/`Employment` do not exist yet;
when they do, `employment.legal_entity_id` will FK to this table (already declared at the DB
level — see §3).

## 2. Domain model

**Aggregate boundary**: `LegalEntity` is its own aggregate, referencing `company_id` — not
contained inside the `Company` aggregate (same convention as
`docs/modules/company/01_Company_Module_Overview.md` §3's aggregate-boundary rule).

**Entity — `LegalEntity`**

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `company_id` | UUID | FK → `company.id`, indexed |
| `name` | string (200) | Required |
| `registered_address` | text | Optional |
| `pan` | string (20) | Optional; validated `[A-Z]{5}[0-9]{4}[A-Z]` when provided |
| `tan` | string (20) | Optional |
| `cin` | string (30) | Optional |
| `gstin` | string (20) | Optional; validated 15-char GSTIN format when provided |
| `pf_code` | string (30) | Optional |
| `esi_code` | string (30) | Optional |
| `lwf_reg` | string (30) | Optional |
| `signatory_name` | string (150) | Optional |
| `signatory_designation` | string (150) | Optional |
| `signature_image_url` | text | Optional — schema field exists; **no upload UI built** (see §11) |
| `is_active` | boolean | Default `true` |
| `version` | integer | Optimistic concurrency (`If-Match`) |
| `created_at` / `updated_at` / `deleted_at` | timestamptz | `deleted_at` reserved, unused by this slice (deactivation ≠ deletion) |

Field list and types are sourced from `docs/product/08_Database_Architecture.md` §4 and
`docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md` Task 2.6.1 — no fields were invented beyond
what those documents specify.

**Employee/Employment forward-compatibility**: this module does not implement Employee or
Employment, but its design does not block the documented future model where `employee` is a
permanent identity and `employment` is a time-bounded FK to `legal_entity_id`
(`docs/product/17_SRS_Phase1_Core_Modules.md` §4.1, `docs/product/08_Database_Architecture.md`
§5.2). `LegalEntity` carries no assumption that ties it to a single employment period.

## 3. Database

Table `legal_entity` pre-existed as a stub (`id, company_id, name, pan, gstin, created_at,
updated_at, deleted_at`) from the original baseline migration
(`apps/api/scripts/sql/001_init_schema.sql`), with `branch.legal_entity_id` and
`employment.legal_entity_id` already FK'd to it (`ON DELETE RESTRICT`) even though neither
Branch nor Employment has application code yet.

Migration `apps/api/alembic/versions/20260813120000_legal_entity_fields.py` adds the
remaining columns from §2, an index (`legal_entity_company_active_idx` on
`(company_id, is_active) WHERE deleted_at IS NULL`), and enables RLS.

**RLS gap fixed by this slice**: the standalone `apps/api/scripts/sql/
002_row_level_security.sql` file (which lists `legal_entity` in its RLS loop) is **not**
invoked by any Alembic migration and was never the live RLS registry — this was already true
before this slice and remains true for tables not yet given their own inline-RLS migration.
Following the precedent set by `20260803200000_b1_auth_audit.py` (`audit_log`) and
`20260807150000_company_setup_progress.py`, this migration enables and forces RLS on
`legal_entity` directly, with an inline `tenant_isolation` policy
(`company_id = current_setting('app.company_id', true)::uuid`).

## 4. API

All routes live in the existing `organisation` module/router (not a new module), per
`docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md`'s stated owning-module column for the whole
Company→Employee hierarchy.

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/v1/legal-entities` | `ORG.LEGAL_ENTITY.MANAGE` | List, company-scoped, no pagination (low expected cardinality) |
| POST | `/v1/legal-entities` | `ORG.LEGAL_ENTITY.MANAGE` | Create; `is_active` always `true`, not client-settable |
| GET | `/v1/legal-entities/{entity_id}` | `ORG.LEGAL_ENTITY.MANAGE` | 404 (never 403) if not found or belongs to another tenant |
| PATCH | `/v1/legal-entities/{entity_id}` | `ORG.LEGAL_ENTITY.MANAGE` | Requires `If-Match: <version>`; partial update; `is_active` may be toggled here (reactivate) |
| DELETE | `/v1/legal-entities/{entity_id}` | `ORG.LEGAL_ENTITY.MANAGE` | **Soft deactivation only** — sets `is_active=false`, never a hard delete. Requires `If-Match`. Returns `200 DataEnvelope<LegalEntityRead>`, not `204` (no bare-204 response exists elsewhere in this API) |

Standard conventions reused unmodified: `DataEnvelope`/`ListEnvelope` response wrapper,
`ErrorEnvelope` error shape, `extra="forbid"` on write schemas (mass-assignment rejected with
422), tenant resolved only from `X-Company-Id` header + JWT (never a `{company_id}` URL
param — the entity's own id in the path, `{entity_id}`, is a normal resource identifier, not
a tenant-scoping mechanism, and is still checked against `company_id` server-side on every
query).

## 5. Permissions

Single permission `ORG.LEGAL_ENTITY.MANAGE` gates viewing **and** managing (create/update/
deactivate) — no separate view-only permission exists, matching the existing `Company`
module's precedent (`ORG.COMPANY.MANAGE` also gates both). This decision resolves a tension
in the task brief, which asked to "at minimum distinguish viewing vs. managing": no doc
defines a second, view-only permission code for this resource, and inventing one would
contradict the sibling Company convention. If a future requirement needs read-only viewers,
add `ORG.LEGAL_ENTITY.VIEW` then — not invented here.

**Naming conflict resolved**: `docs/product/19_RBAC_and_Permission_Matrix.md` §3.6 names this
resource `ORG.ENTITY.MANAGE`; `docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md` uses
`ORG.LEGAL_ENTITY.MANAGE` in five places. This slice implements `ORG.LEGAL_ENTITY.MANAGE`
(the sprint doc is the more recent, specific, implementation-precise source).
`docs/product/19_RBAC_and_Permission_Matrix.md` should be corrected to match in a follow-up
doc-only change.

Every company's `COMPANY_ADMIN` system role is granted `ORG.LEGAL_ENTITY.MANAGE` at
registration time (`OrganisationService.register_company`), alongside the pre-existing
`ORG.COMPANY.MANAGE` / `DASHBOARD.COMPANY.VIEW` grants.

## 6. Business rules implemented

- **Deactivation blocks on active branches** (FR-ORG-014, "never hard-delete"): `DELETE`/
  `PATCH {is_active:false}` is rejected with `409 LEGAL_ENTITY_HAS_ACTIVE_BRANCHES` if any
  `branch` row (checked via raw SQL against the existing `branch` table — no Branch ORM model
  exists yet) with `deleted_at IS NULL` still references the entity.
- **Reactivation**: no dedicated endpoint; `PATCH {is_active:true}` reverses a prior
  deactivation. No blocking rule applies to reactivation.
- **Optimistic concurrency**: `version` + `If-Match`, same as Company.
- **PAN / GSTIN format validation**: enforced server-side (and mirrored client-side) when
  provided; both fields remain optional.

**Explicitly not implemented — no doc basis found (documented gap, not invented)**:
- **Uniqueness of `name` / `pan` / `gstin` within a company.** No spec states this is
  required. Two legal entities with the same name (or PAN) can currently be created in the
  same company. If this trips up real usage, it needs a product decision (unique index +
  409 conflict) before being added — not assumed here.
- **Country-specific validation.** Only the Indian PAN/GSTIN formats are validated
  (the only formats named in `SPRINT_3_COMPANY_FOUNDATION.md`); no other country's statutory
  ID formats are specified, so none are validated.
- **Required-ness of individual statutory fields** beyond `name`. All of PAN/TAN/CIN/GSTIN/
  PF/ESI/LWF/signatory fields are optional — no doc marks any of them mandatory at create
  time.

## 7. Tenant isolation / RLS

Identical mechanism to every other `organisation`-module resource: `TenancyMiddleware` +
`get_tenant_context` dependency set both the `TenantContext` contextvar and the Postgres
`app.company_id` session variable; repository queries filter explicitly by `company_id` in
addition to relying on RLS as a backstop (belt-and-suspenders, per ADR-0002). Cross-tenant
access to another company's Legal Entity — including by guessing a real `entity_id` — returns
`404`, never `403` or a data leak, proven by
`tests/integration/modules/organisation/test_cross_tenant_isolation.py`.

## 8. Audit

Uses the existing `AuditService` — no second audit system. Events recorded:
`LEGAL_ENTITY_CREATED`, `LEGAL_ENTITY_UPDATED`, `LEGAL_ENTITY_DEACTIVATED`,
`LEGAL_ENTITY_REACTIVATED`, each with `before_json`/`after_json` snapshots of the
`LegalEntityRead` DTO (no secrets in this resource's fields).

## 9. Frontend

- **Routes**: `/app/legal-entities` (list + empty state + "Add Legal Entity" dialog),
  `/app/legal-entities/[id]` (view/edit toggle + deactivate/reactivate confirmation dialog),
  same view/edit-toggle pattern as `/app/company`.
- **Nav**: new "Legal Entities" item added to the existing flat `NAV_ITEMS` array
  (`components/layout/nav-items.ts`) — no "Organisation" grouping exists yet in the nav, so
  this is a top-level item like Company and Setup.
- **Data fetching**: plain `useState`/`useEffect` + the existing hand-rolled `apiClient` — no
  TanStack Query introduced, per the task's explicit instruction not to add it for this slice.
- **Reused components**: `PageHeader`, `FormField`, `LoadingState`, `ErrorState`,
  `EmptyState`, `toast`, `Card`, `Button`, `Badge`. `Dialog` primitives (previously unused in
  the app) are now wired up for the create flow and the deactivate/reactivate confirmation.
- **New, since nothing existed to reuse**: a plain `<ul>`/row list (no data-table component
  exists anywhere in the app yet — out of scope to build one for ~1-10 rows per company).
- **UX**: plain-language labels throughout ("Legal Entities", "Add Legal Entity", "PAN",
  "GSTIN" — the latter two are how HR admins already know these fields, not raw API/DB
  terms). Empty state copy matches the task brief's suggested wording verbatim.
- **`apiClient.delete`**: added (didn't exist before — Company never needed it).

## 10. Tests

Backend: `tests/unit/modules/organisation/test_legal_entity_service.py` (business-rule
branches against a mocked repo), `tests/integration/modules/organisation/test_legal_entity.py`
(full CRUD, validation, deactivation-blocked/allowed, reactivation, audit rows, stale-version
conflict, not-found, mass-assignment), plus Legal Entity cases added to the existing
`test_cross_tenant_isolation.py`, `test_permission_matrix.py`, and
`test_organisation_security.py` files rather than duplicating those suites. 143/143 backend
tests pass.

Frontend: `lib/legal-entity/validate-legal-entity.test.ts` (pure validation/patch-diff logic),
`app/app/legal-entities/page.test.tsx` and `app/app/legal-entities/[id]/page.test.tsx`
(loading, empty state, list rendering, create + validation + API-error paths, edit + stale
conflict, deactivate/reactivate + blocked-deactivation toast, forbidden/not-found states).
86/86 frontend tests pass (up from 60 before this slice).

## 11. Known limitations / deferred

- **`signature_image_url`** exists in the schema/API but has no upload UI — pasting a raw URL
  isn't appropriate for a non-technical HR admin, and no file-upload infrastructure exists in
  this codebase yet. Deferred until an upload component exists.
- **`CompanyProfileRead.primary_legal_entity`** remains `null` — **not** wired up to the new
  table. `docs/modules/company/03_Database_Design.md` §9 anticipates a future
  `legal_entity.is_primary` column + partial unique index to support this, but no document
  specifies how "primary" is determined (first created? explicitly designated? single-entity
  companies only?). Inventing that rule was out of scope for this slice — flagged as a gap
  for the Company module owner to resolve, not assumed here.
- **No auto-created default Legal Entity at registration** — confirmed as a product decision
  during this slice's audit phase (the docs contradicted themselves: `Task 2.1.3`/`D8` don't
  seed one, but a Company Profile screen-spec note assumed one existed post-registration).
  New companies now see the empty state and add their first Legal Entity manually. If product
  wants auto-creation later, it touches the registration transaction directly and should be
  scoped as its own change, not bundled here.
- **No uniqueness constraints** on name/PAN/GSTIN — see §6.
- **Country-specific validation** limited to India (PAN/GSTIN) — see §6.

## 12. Recommended next slice

**Branch** is the next Organisation Structure vertical slice by dependency order — `branch`
and its FK to `legal_entity_id` already exist at the DB level (used defensively in this
slice's deactivation-blocking check), and `docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md`
places it immediately after Legal Entity in its build order. Branch will also need to resolve
the deferred `primary_legal_entity` question once it exists, since Branch is the first
consumer of "which legal entity is this branch under" in a UI.
