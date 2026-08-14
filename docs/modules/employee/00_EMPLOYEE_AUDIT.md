# Employee Module — Pre-Implementation Audit

Status: **Audit only — no application code, migrations, or frontend changed.** Employee is the
central dependency for Attendance, Leave, Payroll, ESS, onboarding and offboarding, so this audit
is deliberately wider and more conservative than the Company/Legal Entity/Branch/Department/
Designation/Grade/Shift Rules audits that preceded it. It follows the same audit-then-build
discipline (`docs/modules/grade/00_GRADE_AUDIT.md`, `docs/modules/shift-rules/00_SHIFT_RULES_AUDIT.md`)
but, per this audit's brief, does not propose a single vertical slice — it produces a full design
review of the Employee aggregate, ending in an open-decisions list and a recommended implementation
order.

Companion documents (unchanged by this consolidation, referenced throughout for field/endpoint-level
detail): `01_EMPLOYEE_MODULE_PLAN.md` (vertical-slice sequencing, E-01…E-10), `02_EMPLOYEE_DATA_MODEL.md`
(full ~90-field inventory with sensitivity/permission classification), `03_EMPLOYEE_API_PLAN.md`
(proposed endpoint surface), `04_EMPLOYEE_UX_PLAN.md` (tab structure, wizard, workflow screens).
`docs/design/screens/01_Employee_List_Directory.md` is a pre-existing, fully specified screen-level
UX contract for the Directory.

**Method note.** Findings are sourced from a full repository grep (backend, frontend, docs,
migrations, archive), a full read of the organisation module's shipped code
(`apps/api/src/hrms/modules/organisation/`), a full read of the frontend's shipped organisation
routes/components (`apps/web/src/app/app/{branches,departments,...}`), and a full read of the
relevant product/ADR documentation. Every claim is cited to a `file:line`. Where documentation and
code disagree, or two documents disagree with each other, both are stated and flagged — nothing is
silently resolved (§5).

---

## 1. Executive summary

Employee is **not a clean slate**. The database, auth layer, RBAC seed, and UX design already
assume Employee's existence in several concrete, load-bearing ways, but **zero application code
exists** — no ORM model, repository, service, router, schema, permission module, or test.

Four tables (`employee`, `employment`, `employee_assignment`, `employee_compensation`) have lived
in the database since the very first migration, with RLS and (for the two effective-dated tables) a
GiST no-overlap constraint already enforced — but each table has materially fewer columns than the
documented target, and `employee_assignment`'s five FK-shaped columns have no actual FK constraint.
Two documented tables (`employee_statutory`, `employee_bank`) don't exist at all, which blocks
Payroll if not addressed inside Employee's own build. The frontend has no Employee routes, no
`Tabs`/`Timeline` component to build a 360° profile with, and no proactive permission-gating
pattern (`usePermission`/`PermissionGate`) — only a reactive 403-toast pattern used today.

The core product question — **does a rehired employee keep the same Employee ID** — is
architecturally supported by the existing schema and documentation (`employee` = permanent
identity, `employment` = one row per time-bounded spell, explicitly designed to "support rehire...
as separate employment rows for one employee"), but the mechanics (does `employee_code` literally
never change, what closes the prior `employee_assignment`/`employee_compensation` rows, what status
represents "identity exists, not currently employed") are unspecified and need product sign-off
before Employee's first migration is written (§17).

**Recommendation**: adopt the `employee` (identity) → `employment` (1:N, time-bounded spells) →
`assignment`/`compensation`/`statutory`/`bank`/... (1:N, effective-dated) model exactly as already
documented and already shaped in the live schema — no invented "Person" layer, no single flat
employee row holding all history. Build in the ten-slice sequence in §16, resolving the nine
decisions in §17 before the slices that depend on them (flagged per-slice).

---

## 2. Current repository state

### 2.1 What does not exist
- No `apps/api/src/hrms/modules/employee/` package — the only module directories today are
  `identity`, `health`, `organisation`.
- No Employee ORM model, repository, service, router, schemas, permissions module, or tests.
  `grep -rn "class Employee" apps/api/src` returns nothing; the only `Employee`-referencing code is
  comments explaining why a real FK/model can't be used yet (§2.3).
- No Employee frontend route, page, component, or API client. `find apps/web -iname "*employee*"`
  (excluding `node_modules`/`.next`) returns **zero results** — no `apps/web/src/app/app/employees`,
  no `lib/employee/`, no `components/employee/`.
- No employee/employment fixtures or factories in `apps/api/tests` (no `factories` directory exists
  anywhere under `apps/api/tests`; `conftest.py` files are company/user/role/legal-entity/branch
  scoped only).
- No seeded Employee rows anywhere (seed data seeds roles/permissions/plans only).

### 2.2 The organisation module — the pattern Employee must replicate or deliberately deviate from
`apps/api/src/hrms/modules/organisation/` (`dependencies.py`, `events.py`, `exceptions.py`(288),
`models.py`(280), `permissions.py`(58), `repository.py`(692), `router.py`(637), `schemas.py`(1078),
`service.py`(1703), `tasks.py`) is the only shipped vertical-slice reference in this codebase.
Established conventions:
- **Layering**: thin `router.py` (`Depends(get_organisation_service)`, `Depends(require_permission(CODE))`)
  → fat `service.py` (all business rules) → pure-query `repository.py` ("no business rules",
  `repository.py:1`) → `models.py`.
- **RBAC**: permission codes as plain string constants (`"ORG.<ENTITY>.MANAGE"` shape), one
  permission gates both view and manage for these simple CRUD entities — a shortcut appropriate for
  config data, **not** the pattern Employee's own RBAC doc calls for (§13).
- **Tenant isolation**: repository queries explicitly filter `company_id`, backstopped by Postgres
  RLS — `core/db/session.py` runs `SELECT set_config('app.company_id', :company_id, true)` at the
  start of every session, sourced from a `TenancyMiddleware`-populated `ContextVar`.
- **Audit logging**: `AuditService.record(session, company_id, actor_user_id, action, entity_type,
  entity_id, before, after, ...)` called from the service layer inside the same transaction as the
  write; CI-enforced via an `ast`-based lint rule requiring every mutating service method to call
  `audit.record` (`docs/product/07_Backend_Architecture.md:314-333`).
- **Optimistic concurrency**: every mutable organisation table carries `version INTEGER DEFAULT 1`;
  updates are gated on `WHERE ... version == expected_version`, and a `None` result triggers a
  re-fetch + `StaleResourceError` (409) carrying `current=<entity>_to_audit_dict(...)`.
- **Soft delete / deactivation**: no hard deletes; `deleted_at` + `is_active`; deactivation blocked
  while active children reference the row (e.g. `BranchDeactivationBlockedError`).

### 2.3 Integration seams already wired, waiting for Employee to exist
- `AuthenticatedUser.employee_id: UUID | None` (`core/auth/types.py:10`) — a real field on every
  authenticated request context, always `None` today. The JWT payload always carries an
  `employee_id` claim end-to-end (`core/auth/jwt.py:20,30`, `core/auth/dependencies.py:27,46`);
  `modules/identity/service.py:210` passes `employee_id=None` unconditionally at login.
- `EMPLOYEE_VIEW = "EMPLOYEE.VIEW"` is already seeded (`modules/identity/permissions.py:5,10`), and
  a system role `EMPLOYEE_VIEWER` is seeded and granted it (`seed/bootstrap.py:70-83`) — the only
  one of 14 documented `EMPLOYEE.*` codes seeded so far (§13.1).
- `SEAT_LIMIT_FEATURE_CODE = "EMPLOYEE_SEATS"` (`seed/plan_catalogue.py:11-19`) — every plan
  (FREE/STARTER/PROFESSIONAL/ENTERPRISE) already carries an `employee_seat_limit`
  (5/25/100/unlimited). **No code enforces this anywhere** — must be enforced by whatever creates
  Employee rows (§17.6).
- `organisation/service.py` returns `employee_count: int | None`, hardcoded `None`, in dashboard
  responses (`service.py:537,563,1023-1024,1202-1203,1375-1376`); `apps/web/src/lib/company/types.ts:101`
  and `apps/web/src/app/app/dashboard/page.tsx:151,251` already render an "Employees" stat tile
  bound to this always-null value, and placeholder copy ("Organisation structure, employees,
  attendance, leave, and payroll will appear...").
- Every Branch/Department/Designation/Grade deactivation check that FR-ORG-014 would otherwise
  require ("no active employees assigned") is explicitly skipped in code comments today "because
  Employee doesn't exist yet" — a retrofit into the organisation module once Employee ships, not
  part of Employee's own slices (§17.5).
- `department.head_employee_id UUID → employee.id ON DELETE SET NULL` is a **live DB-level FK**
  (`apps/api/alembic/versions/20260813140000_department_fields.py:47-50`), deliberately kept as a
  plain `UUID` column in the ORM — not `ForeignKey(...)` — because no `Employee` ORM class exists to
  resolve against (`organisation/models.py:164-168`, explicit comment). `designation.next_designation_id`
  is the analogous self-referential precedent (Designation → Designation, not Employee-facing).

### 2.4 Frontend conventions Employee should replicate
The six completed organisation entities (Legal Entity, Branch, Department, Designation, Grade,
Shift) all follow an identical **list page + `[id]` detail page** Next.js App Router shape
(`apps/web/src/app/app/<entity>/page.tsx` + `[id]/page.tsx`), each with a co-located `*-form.tsx`
component, a `lib/<entity>/types.ts` mirroring the backend Pydantic schema by comment convention,
and hand-rolled (no react-hook-form/zod) `validate-<entity>.ts` functions. Key conventions Employee
should reuse as-is:
- **Optimistic concurrency in the UI**: every entity carries `version`; every `PATCH`/`DELETE` sends
  `If-Match: String(entity.version)`; a `409 STALE_RESOURCE` response surfaces a dedicated inline
  banner ("This branch was changed by someone else." + **Reload latest** / **Cancel current
  changes** buttons), not a toast, because it needs a user decision
  (`apps/web/src/app/app/branches/[id]/page.tsx:142-146,264-276`). Domain-specific 409s (e.g.
  `BRANCH_HAS_ACTIVE_DEPARTMENTS`) are handled separately by `code`.
- **Data fetching**: no React Query/SWR anywhere in this codebase. Either hand-rolled
  `useState`/`useEffect`/`useCallback` in the page component (used by all organisation CRUD pages),
  or the shared `useApiResource<T>(path)` hook (`apps/web/src/hooks/use-api-resource.ts`, currently
  only used by the read-only dashboard) which treats a `404` as `notImplemented: true` rather than
  an error. All calls flow through one `apiClient` wrapper (`apps/web/src/lib/api/client.ts`) that
  injects `Authorization`/`X-Company-Id`/`X-Request-Id`, handles silent token refresh, and unwraps
  the `DataEnvelope`/throws a typed `ApiError`.
- **RBAC gating gap (a real gap, not a convention to copy)**: there is **no proactive permission
  gate on the frontend today** — no `usePermission` hook, no `PermissionGate` component. Every page
  instead catches a `403 ApiError` reactively and shows a toast or an inline error state
  (`apps/web/src/app/app/branches/page.tsx:107-111,144-148`). `UserProfile.permissions: string[]`
  is already returned by `/auth/me` (`apps/web/src/lib/auth/types.ts:24-29`) but nothing in
  `apps/web/src` reads it. Nav items are a static hardcoded array manually curated to be "absent,
  not disabled" (`components/layout/nav-items.ts:22-31`). **Employee will be the first module that
  needs real proactive gating** — an entire tab (Compensation) must be *absent*, not
  disabled-and-visible, for a caller without `EMPLOYEE.VIEW_COMPENSATION` (§13.3, §14) — this is a
  frontend infrastructure gap that should be designed once, not worked around per-tab. Flagged as
  §17.10.
- **No `Tabs`/`Timeline`/`DataTable` component exists** in `apps/web/src/components/ui/` today —
  `package.json` has no `@radix-ui/react-tabs` installed (it has `-dialog`, `-dropdown-menu`,
  `-label`, `-scroll-area`, `-separator`, `-slot`, `-tooltip`). A 360° profile with tabs and a
  history/timeline view is new frontend infrastructure, not a reuse of an existing primitive (§14).
- **Test conventions**: Vitest + Testing Library, co-located `page.test.tsx`, hand-built fixture
  objects, `vi.mock` for `next/navigation`/`auth-context`/`toast`/`apiClient`, assertions on the
  *exact* PATCH payload/diff and `If-Match` header, and a fixed per-entity checklist (load, 404,
  edit/cancel, save+If-Match, stale-resource conflict, status toggle, domain-specific conflict
  codes) — Employee's tests should replicate this checklist plus tab-switching coverage.

---

## 3. Existing database schema

The first migration (`apps/api/alembic/versions/20260803124757_init_schema.py`, running
`apps/api/scripts/sql/001_init_schema.sql`) already creates four employee-domain tables — live, not
aspirational. Two standalone files, `scripts/sql/002_row_level_security.sql` and
`003_effective_dating_constraints.sql`, duplicate parts of this content but are **not** invoked by
Alembic; they are reference-only and must not be treated as a second source of truth.

### 3.1 `employee` (`001_init_schema.sql:224-240`)
```sql
CREATE TABLE "employee" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "company_id" UUID NOT NULL,
    "user_id" UUID,
    "employee_code" VARCHAR(30) NOT NULL,
    "first_name" VARCHAR(100) NOT NULL,
    "last_name" VARCHAR(100),
    "date_of_birth" DATE,
    "gender" VARCHAR(20),
    "custom_fields" JSONB,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "deleted_at" TIMESTAMPTZ,
    "version" INTEGER NOT NULL DEFAULT 1,
    CONSTRAINT "employee_pkey" PRIMARY KEY ("id")
);
```
- Indexes: `employee_company_id_idx` (`:356`).
- Unique: `UNIQUE (company_id, employee_code)` — `employee_company_id_employee_code_key` (`:359`).
- FKs: `employee.company_id → company.id ON DELETE RESTRICT` (`:434`); `employee.user_id → user.id
  ON DELETE SET NULL` (`:437`).
- RLS: `tenant_isolation` policy, `FORCE ROW LEVEL SECURITY` (`:467-483`).
- **Not effective-dated** — correct, per ADR-0003: identity attributes don't need historical
  tracking, only the child tables do (§11).
- **Gap vs. documented target** (`docs/product/08_Database_Architecture.md §5.1`): live table has 8
  business columns; the target has ~20 — missing `middle_name`, `display_name`, `blood_group`,
  `marital_status`, `nationality`, `personal_email`, `personal_mobile`, `photo_url`,
  `pan_number_enc`, `aadhaar_number_enc`, `uan_number`, `status`.

### 3.2 `employment` (`001_init_schema.sql:243-256`)
```sql
CREATE TABLE "employment" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "company_id" UUID NOT NULL,
    "employee_id" UUID NOT NULL,
    "legal_entity_id" UUID NOT NULL,
    "joining_date" DATE NOT NULL,
    "exit_date" DATE,
    "status" VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "deleted_at" TIMESTAMPTZ,
    CONSTRAINT "employment_pkey" PRIMARY KEY ("id")
);
```
- Indexes: `employment_company_id_idx` (`:362`), `employment_employee_id_idx` (`:365`).
- FKs: `employment.employee_id → employee.id ON DELETE RESTRICT` (`:443`);
  `employment.legal_entity_id → legal_entity.id ON DELETE RESTRICT` (`:446`).
- RLS: applied, same shape as above.
- **No `version` column, no `is_active`** — the only employee-domain table that diverges from the
  `version`-everywhere convention every organisation-module table follows. A decision point for
  Employee's own migration (§17.7): add `version` to match convention, or leave as-is because
  `employment` rows are semantically append-mostly (a decision, not an oversight to silently fix).
- **Gap vs. target** (`docs/product/08 §5.2`): missing `employment_number`, `employment_type_id`,
  `date_of_confirmation`, `probation_end_date`, `notice_period_days`, `date_of_resignation`,
  `last_working_day`, `exit_type`, `exit_reason_id`, **`is_rehire`, `previous_employment_id`** — the
  last two are required for the rehire scenario in §8 and must be added before Employee's
  employment slice ships.

### 3.3 `employee_assignment` (`001_init_schema.sql:259-276`)
```sql
CREATE TABLE "employee_assignment" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "company_id" UUID NOT NULL,
    "employee_id" UUID NOT NULL,
    "department_id" UUID,
    "designation_id" UUID,
    "grade_id" UUID,
    "reporting_manager_id" UUID,
    "branch_id" UUID,
    "effective_from" DATE NOT NULL,
    "effective_to" DATE,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "deleted_at" TIMESTAMPTZ,
    "version" INTEGER NOT NULL DEFAULT 1,
    CONSTRAINT "employee_assignment_pkey" PRIMARY KEY ("id")
);
```
- Indexes: `employee_assignment_company_id_idx` (`:368`),
  `employee_assignment_employee_id_effective_from_idx` on `(employee_id, effective_from)` (`:371`).
- FKs: **only** `employee_id → employee.id` (`:449`) is a real constraint. `department_id`,
  `designation_id`, `grade_id`, `reporting_manager_id`, `branch_id` are **plain nullable UUID
  columns with no FK constraint at all** — a referential-integrity gap to close in Employee's own
  migration (§5, §17).
- **Effective-dated**, enforced by a GiST exclusion constraint (`:494-499`):
  ```sql
  ALTER TABLE employee_assignment
    ADD CONSTRAINT employee_assignment_no_overlap
    EXCLUDE USING gist (
      employee_id WITH =,
      daterange(effective_from, COALESCE(effective_to, 'infinity'::date), '[]') WITH &&
    );
  ```
  This makes two overlapping "current" rows for one employee structurally impossible.
- **Gap vs. target** (`docs/product/08 §5.3`): missing `dotted_line_manager_id`, **`shift_id`**,
  `cost_centre_id`, `work_location_type`, `change_reason`, `change_type`. `shift_id` specifically
  blocks the Attendance dependency contract (§15) until added.

### 3.4 `employee_compensation` (`001_init_schema.sql:279-293`)
```sql
CREATE TABLE "employee_compensation" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "company_id" UUID NOT NULL,
    "employee_id" UUID NOT NULL,
    "annual_ctc_minor" BIGINT NOT NULL,
    "currency" CHAR(3) NOT NULL DEFAULT 'INR',
    "effective_from" DATE NOT NULL,
    "effective_to" DATE,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "deleted_at" TIMESTAMPTZ,
    "version" INTEGER NOT NULL DEFAULT 1,
    CONSTRAINT "employee_compensation_pkey" PRIMARY KEY ("id")
);
```
- Indexes: `employee_compensation_company_id_idx` (`:374`),
  `employee_compensation_employee_id_effective_from_idx` (`:377`).
- FK: `employee_id → employee.id ON DELETE RESTRICT` (`:452`).
- **Effective-dated**, same GiST exclusion constraint shape as §3.3 (`:501-506`).
- Money already follows ADR-0006 (`annual_ctc_minor BIGINT` + `currency CHAR(3)`), consistent with
  house convention.
- **Gap vs. target** (`docs/product/08 §5.4`): missing `salary_structure_id`, `monthly_gross`,
  `revision_type`, `revision_reason`, `approved_by`, `approval_request_id`,
  `is_arrears_processed`; the child `employee_compensation_component` table does not exist.

### 3.5 Tables documented but entirely absent from the live schema
`employee_statutory` and `employee_bank` (`docs/product/08_Database_Architecture.md §5.5-5.6`) —
both effective-dated per the same ADR-0003 pattern, both named in the archived v1-predecessor
schema doc too (confirming they were always part of the intended design, not a new idea) — **do
not exist in any migration**. This blocks Payroll if not built as part of Employee's own scope
(§5 row 6, §17.2). Eight further supporting tables from the target schema
(`employee_document`, `employee_dependent`, `employee_education`, `employee_experience`,
`employee_skill`, `employee_address`, `employee_emergency_contact`, `employee_event`) also don't
exist yet — expected, since these are later vertical slices (§16, E-08).

### 3.6 Reverse-direction references already provisioned
- `department.head_employee_id → employee.id ON DELETE SET NULL` — live FK, not yet exposed by
  Department's schema/service/UI (§2.3).
- `designation.next_designation_id` — self-referential, not Employee-facing.

### 3.7 Indexing plan already specified for scale (`docs/product/08 §12`, not yet built)
```sql
CREATE INDEX ON employee (company_id, status) WHERE deleted_at IS NULL;
CREATE INDEX ON employee (company_id, employee_code);
CREATE INDEX ON employee USING gin (custom_fields);
CREATE INDEX ON employee_assignment (company_id, reporting_manager_id, effective_from DESC);
CREATE INDEX ON employee_assignment (company_id, employee_id, effective_from DESC)
  INCLUDE (department_id, designation_id, reporting_manager_id, shift_id);
CREATE INDEX ON employee_assignment (company_id, employee_id) WHERE effective_to IS NULL;
```
Worth building into Employee's own migrations rather than retrofitting after Attendance/Leave/
Payroll are live and query patterns are already in production.

---

## 4. Documentation requirements

Everything Employee must satisfy, per the currently-authoritative documents:

- **`docs/product/08_Database_Architecture.md §5`** ("Employee Domain") — the target schema for all
  nine employee-domain tables, quoted throughout §3 above. Global rules (§1 of that doc) that apply
  to every table Employee builds: `company_id` + RLS on every table; effective-dating via child
  table + GiST exclusion, never a mutable column; no hard deletes; enums as lookup tables, not PG
  enum types; every FK indexed; money as `BIGINT` minor units + `CHAR(3)` currency; `version INT`
  optimistic locking as a standard audit column.
- **`docs/product/17_SRS_Phase1_Core_Modules.md §4`** — FR-EMP-001 through FR-EMP-018 with
  acceptance criteria. Load-bearing requirements: FR-EMP-002 (mandatory creation fields), FR-EMP-003
  (assignment changes are always a new effective-dated row, previous row closed the day before),
  FR-EMP-004 (backdating blocked past a finalised payroll period without `PAYROLL.BACKDATE_OVERRIDE`),
  FR-EMP-009 (controlled vs. uncontrolled field edit distinction), FR-EMP-014 (10-state status
  machine), FR-EMP-015 (rehire matching, priority **S**/Should, not confirmed for V1 — §8.3),
  FR-EMP-018 (BR-14 override chain — named, not buildable yet, §15.2).
- **`docs/product/19_RBAC_and_Permission_Matrix.md §3.1, §5, §6`** — the 14-code `EMPLOYEE.*`
  permission catalogue, the `SELF/REPORTEES/REPORTEE_TREE/DEPARTMENT/BRANCH/LEGAL_ENTITY/COMPANY`
  data-scope model, and the four-tier field sensitivity classification (§10, §13).
- **`docs/product/VERSION_1_ROADMAP.md`** (dated 2026-08-04, self-declared "binding... until
  superseded") — the authoritative scope boundary: Employee Management in V1 = "Employee Directory
  · Employee 360 · Employee Documents · Employment Information · Reporting Structure · Employee
  Timeline · Employee Import" (§2, line 53) — **no onboarding/candidate-conversion row**.
  §6 states hard sequencing: "Organization must exist before Employee Management" and "**Employee
  Management must exist before Attendance, Leave, or Payroll**." §8/§10 place `modules/employee/`
  as backend item #3 and the Employee domain as database item #3, immediately after Organisation.
  §14's sprint table places "Employee core, lifecycle & import" as the sprint immediately following
  the current one (RBAC completion & Org setup) — consistent with this audit being commissioned now.
- **ADR-0002** (RLS multi-tenancy), **ADR-0003** (effective-dated modelling — titled specifically
  for Employee attributes), **ADR-0006** (money as integer minor units), **ADR-0011** (statutory
  rates as data, relevant to `employee_statutory`) — all directly govern Employee's schema shape.
- **`docs/product/02_PRD.md §11`** (Terminology & Naming Standard) — the explicit Employee/User/
  Employment/Assignment definitions quoted in full in §6 below; also explicitly rejects a "Person"
  concept.
- **`docs/design/screens/01_Employee_List_Directory.md`** — a complete, screen-level UX contract for
  the Directory (toolbar/filters/search/bulk actions/pagination, full PUBLIC/INTERNAL/SENSITIVE/
  RESTRICTED field-visibility matrix, accessibility requirements) — a real design contract, not a
  suggestion (§14).
- **`docs/product/09_API_Standards.md §3.2`** — already specifies Employee's API as sub-resource
  routes under `/employees/{id}/*` (23 routes), not a flat single-resource shape — the existing,
  authoritative endpoint catalogue (§03 companion doc follows it).
- **`docs/product/23_Non_Functional_Requirements_and_Compliance.md §4-5`** — DPDP Act 2023 privacy
  obligations and the India statutory compliance framework (PF/ESI/PT/LWF/Gratuity/Bonus/Maternity/
  POSH/Income Tax), with an explicit disclaimer that encoded rates are indicative and require a
  compliance consultant's sign-off (§10, §13).
- **House audit-doc template** (`docs/modules/shift-rules/00_SHIFT_RULES_AUDIT.md` and predecessors)
  — this document deliberately departs from that exact 11-section shape because the brief for
  Employee calls for a wider design review (contradictions table + decisions-required list) rather
  than a single vertical-slice audit — stated here explicitly so the deviation isn't mistaken for an
  oversight.

---

## 5. Conflicts between docs and code

| # | Issue | Evidence | Current state | Recommended resolution | Impact |
|---|---|---|---|---|---|
| 1 | Recruitment/ATS scoped as Phase 1 (MVP) in older docs vs. removed from V1 | `docs/product/02_PRD.md:133`, `docs/product/17 §8-9` describe candidate→offer→onboarding→employee conversion as Phase 1; `docs/product/VERSION_1_ROADMAP.md:29` reverses this and calls the older docs stale | Roadmap is dated later (2026-08-04) and self-declares authority | Treat `VERSION_1_ROADMAP.md` as authoritative; Employee's create flow has no ATS coupling (§12) | High — changes FR-EMP-001's creation-path count from 4 to 2 for V1 |
| 2 | BR-14 override-chain direction phrased inconsistently | PRD (top-down: Company→Branch→Department→Grade→Employee, omits Designation) vs. FR-EMP-018 (bottom-up: Employee→Grade→Designation→Department→Branch→Company) | Both describe "most specific wins," likely equivalent intent, but Designation's position differs | Confirm with product before building; do not assume ordering | Medium — affects shift/notice-period/probation/leave-entitlement resolution order |
| 3 | `employment.status` value set is undefined | `docs/product/08 §5.2` gives `employment` its own `status` column but never enumerates values; `employee.status` is explicitly pointed at the 10-value FR-EMP-014 list | Undocumented | Decide whether `employment.status` reuses the same enum or has a narrower set (e.g. ACTIVE/EXITED only) | Medium — needed before the `employment` schema can be finalized (blocks E-03) |
| 4 | `employee_education[]`/`certification[]` mismatch | SRS §4.1 lists 4 arrays; Doc 08 §5.7 defines 3 tables, folding certification into `employee_skill.is_certified` | Minor schema/spec drift | Adopt Document 08's 3-table shape | Low |
| 5 | Rehire (FR-EMP-015) is priority "Should," not scoped in V1's module table | Priority S; `VERSION_1_ROADMAP.md §5` rows for Employee Management/Exit don't mention rehire | Ambiguous — neither confirmed in nor explicitly deferred out of V1 | Confirm with product before Employee's first slice — affects the `employment` table shape | High — same table must be decided before migration is written |
| 6 | `employee_statutory`/`employee_bank` documented (ADR-0003, Doc 08 §5.5-5.6, archived v1 predecessor doc) but absent from every migration | See §3.5 | Not built anywhere | Build as part of Employee's own migrations — Payroll's dependency contract (§15) requires them and no later module is documented as owning them | High — blocks Payroll if deferred |
| 7 | `employee_assignment.shift_id`/`dotted_line_manager_id`/`cost_centre_id`/`work_location_type`/`change_reason`/`change_type` documented but absent from the live table | Doc 08 §5.3 vs. `001_init_schema.sql:259-276` | Live table has 5 of 11 documented columns | Add via migration as part of Employee's assignment slice | High — `shift_id` specifically blocks the Attendance contract (§15) |
| 8 | `employee_assignment`'s FK-shaped columns have no DB-level FK constraint | `001_init_schema.sql:259-276` | Referential integrity unenforced at the DB layer | Add FK constraints in Employee's migration, `ON DELETE SET NULL`, matching the organisation module's own convention for optional references | Medium |
| 9 | `employment` has no `version` column, unlike every other mutable table in this domain | §3.2 | Optimistic concurrency convention broken for this one table | Decide: add `version` for consistency, or document why `employment` is intentionally exempt | Medium — a silent inconsistency otherwise |
| 10 | Frontend has no proactive permission-gating primitive, but Employee's UX design requires whole-tab absence by permission | §2.4, `docs/design/screens/01_Employee_List_Directory.md`, `docs/product/24 §4.1` ("permission-gated tabs are absent, not disabled-and-visible") | `UserProfile.permissions` returned by API, unused by any frontend code | Design a `usePermission`/`PermissionGate` primitive as part of Employee's frontend foundation, not a per-tab workaround | Medium — affects every gated tab in §14 |

---

## 6. Employee identity model

The documentation gives an explicit, unambiguous answer (`docs/product/02_PRD.md §11`, Terminology
& Naming Standard):

> **Person**: "Not modelled. Avoid the word." — explicitly rejected as a concept.
> **User**: "An authenticatable identity... May or may not be an Employee."
> **Employee**: "An employment record inside one Company. Has employee_code, joining date, CTC. An
> Employee **may exist without a User** (blue-collar staff with no login)."
> **Employment**: "A time-bounded relationship between an Employee and a Legal Entity. Supports
> rehire and inter-entity transfer."
> **Assignment**: "The current position: department, designation, grade, reporting manager,
> location, shift. **Time-versioned.**"

Reinforced structurally in `docs/product/17_SRS §4.1`: "An employee is **not** a flat row. It is a
core identity plus a set of effective-dated histories."

**So the model is not `PERSON → EMPLOYEE → EMPLOYMENT → ASSIGNMENT`.** There is no Person layer. The
real hierarchy:

```
employee (identity — code, name, DOB, gender, personal contacts; does not change per se)
 └── employment[]      (1:N — a time-bounded Employee↔LegalEntity relationship;
      │                  supports rehire and inter-entity transfer as separate employment rows)
      └── (per-employment lifecycle: joining/confirmation/probation/exit dates, status)

employee (same identity row)
 ├── assignment[]       (effective-dated — department, designation, grade, manager, branch, shift)
 ├── compensation[]     (effective-dated — CTC, structure, revision)
 ├── statutory[]        (effective-dated — documented, not in live schema, §5 row 6)
 ├── bank[]             (effective-dated — documented, not in live schema, §5 row 6)
 └── document/dependent/education/experience/skill/address/emergency_contact/event[] (supporting)
```

`employee_assignment`/`employee_compensation` reference `employee_id` directly, **not**
`employment_id`. This is the detail that makes rehire correct by construction (§8): assignment and
compensation history spans the identity, not a single employment spell, so a rehired employee's new
assignment/compensation rows attach to the same `employee_id` as before, and the old ones remain
queryable.

**Recommendation**: adopt this model exactly as documented — no invented "Person" entity. It matches
the live DB schema's own shape and requires no architectural deviation from what's already
provisioned.

---

## 7. Employment episode model

**Employee identity and employment episode are separate concepts**, already separated in both the
schema and the documentation — this is not a design choice this audit is proposing, it's confirming
what's already built and filling in what's missing.

- `employee` = **identity**: one row per person per company, created once, never re-created.
- `employment` = **episode**: one row per continuous period at one legal entity. A person can have
  multiple `employment` rows over time — normal inter-entity transfer within a group creates a new
  one; so does a resignation-then-rehire five years later (§8).
- Assignment and compensation are properties of the **identity** (`employee_id`-scoped), not the
  episode — the current job (department/designation/grade/manager/branch/shift) is asked "as of a
  date" against the whole employee history, independent of which `employment` row was open at that
  time. This means the assignment/compensation timeline is continuous across an employment gap in
  the data model (nothing forces a gap in the timeline), even though in practice there will be no
  assignment/compensation rows *during* the years an employee is not employed, because there's
  nothing to assign or compensate.

**Do not implement a single employee row containing all employment history as columns.** The
existing schema already avoids this — `employment` is its own table, `1:N` from `employee` — and
this audit's recommendation is to keep it that way and complete the missing fields (`is_rehire`,
`previous_employment_id`, exit fields — §3.2), not to collapse it.

---

## 8. Rehire strategy

**Scenario** (from the brief): `EMP-000123` joins 2027-01-01, exits 2030-05-31. Five years later,
the same person returns. The system must not create a new employee id — the original identity
persists while both employment periods remain visible.

### 8.1 What the documentation supports
- `docs/product/02_PRD.md` (Employment definition): "**Supports rehire** and inter-entity transfer."
- `docs/product/08_Database_Architecture.md §5.2` (`employment` table): "`is_rehire,
  previous_employment_id`... Supports rehire and inter-entity transfer as separate employment rows
  for one employee." This is the load-bearing sentence — it directly confirms one `employee` row,
  multiple `employment` rows, exactly the model needed for the scenario: the original
  `employee.id`/`employee_code` is reused, and a new `employment` row is inserted with
  `is_rehire=true`, `previous_employment_id` pointing at the original employment row.
- `docs/product/17_SRS §4` (FR-EMP-015, **priority S, "Should," not "Must"**): "Rehire: on
  re-creating an employee with a matching PAN/Aadhaar/email, warn and offer to link to the prior
  record, preserving history and prior UAN."

### 8.2 What is genuinely unspecified — a real gap, not an interpretation choice
No document states:
- Whether `employee_code` is literally reused unchanged on rehire, or whether a rehire could ever
  mint a new code while linking history — both the PRD and FR-EMP-015's phrasing point toward
  reuse, but neither says so explicitly.
- Whether closing employment #1 (`exit_date = 2030-05-31`) requires closing the then-current
  `employee_assignment` row's `effective_to` at the same date (almost certainly yes, by the same
  ADR-0003 discipline applied everywhere else, but no document says so for the exit case
  specifically).
- What `employee.status` should read across the five-year gap between employments — none of the 10
  FR-EMP-014 states cleanly maps to "identity exists, not currently employed, no open employment
  row" (closest candidates `EXITED`/`RETIRED`, neither described as the rejoin-eligible waiting
  state).
- Whether leave balance, UAN, or other identity-linked state carries across the gap — FR-EMP-015
  says "preserving history and prior UAN" but says nothing about leave balance (the ledger model in
  FR-LEV-* suggests a fresh ledger scoped to the new employment, but this is an untested assumption,
  not a stated one).

### 8.3 Scope ambiguity
FR-EMP-015 is priority **S** (Should), not **M** (Must) — not confirmed as MVP-blocking.
`VERSION_1_ROADMAP.md`'s Employee Management/Exit rows don't call out rehire at all — it is silently
absorbed rather than explicitly scoped in or out for V1. **Treat rehire as unscoped/ambiguous for
V1, not confirmed in either direction** — this is decision §17.1.

### 8.4 Recommendation (flagged for product sign-off, not pre-decided)
1. `employee.id`/`employee_code` is the permanent identity anchor — **never** reissued on rehire.
2. A rehire is: a new `employment` row (`is_rehire=true`, `previous_employment_id` set to the
   employee's most recent prior `employment.id`), a new `employee_assignment` row effective from the
   new joining date, and a new `employee_compensation` row effective from the same date — all
   attached to the unchanged `employee_id`. Worked example (matching the brief's own
   `EMP-000123`/2027–2030/2034–2038 illustration):
   ```
   employee EMP-000123 (id unchanged across both spells)
    ├── employment #1  joining_date=2027-01-01  exit_date=2030-05-31  status=EXITED
    ├── employment #2  joining_date=2034-XX-XX  is_rehire=true  previous_employment_id=#1
    ├── employee_assignment  effective_from=2027-01-01  effective_to=2030-05-31  (closed at exit)
    ├── employee_assignment  effective_from=2034-XX-XX  effective_to=NULL         (new spell)
    └── employee_compensation  (same pattern — closed at exit, reopened at rehire)
   ```
3. The **live schema gap** for this (`employment.is_rehire`/`previous_employment_id` don't exist
   today, §3.2) must be closed by a migration as part of Employee's own first slice, since it's a
   documented field on the very first table Employee builds.
4. The re-creation/matching workflow in FR-EMP-015 ("on re-creating an employee with a matching PAN/
   Aadhaar/email, warn and offer to link") is a **UX/workflow feature**, separable from the
   underlying data-model support — it can ship later than the core rejoin data model without
   blocking Attendance/Leave/Payroll, which only need one `employee_id`, multiple `employment` rows,
   to be correct.

---

## 9. Employee ID strategy

- **Generation**: `docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md` documents a `number_series` table
  (`entity_type, prefix, separator, current_number, padding, reset_rule`), seeded with one
  `EMPLOYEE_CODE` row (prefix `EMP`, separator `-`, padding 4 → `EMP-0001`), and a race-safe
  `allocate_next_number()` repository method using `UPDATE ... RETURNING` (never `SELECT max()+1`,
  per `docs/product/08 §4`'s explicit warning). **Neither the table nor the method is implemented**
  — confirmed absent from `apps/api/src` and every migration. This must be built as new
  infrastructure in Employee's first slice (E-01) — no existing pattern to copy.
- **Immutability**: `employee.id` (UUID PK) and `employee_code` are the permanent identity anchor —
  never reissued, including on rehire (§8.4). No document contradicts this; it follows directly from
  the identity/episode separation in §6-7.
- **Scope**: company-scoped, not globally unique — `UNIQUE (company_id, employee_code)` is already
  the live constraint (§3.1). Consistent with every other coded entity in this codebase (branch
  code, department code, etc. are all company-scoped).
- **Survives resignation**: yes — the identity row is never deleted on exit, only `employment.status`
  transitions and `employment.exit_date` is set (§7).
- **Survives rehire**: yes — by design (§8.4); this is the central requirement the whole
  identity/episode split exists to satisfy.
- **Department/legal entity/branch/designation/grade/shift changes**: none of these ever change
  `employee_code` or `employee.id` — they are all effective-dated `employee_assignment` (or, for
  legal entity, `employment`) attributes. A legal-entity change specifically is modelled as a *new*
  `employment` row (inter-entity transfer, per the PRD's Employment definition), not a mutation of
  the existing one, since `employment.legal_entity_id` is fixed for a given spell — the same
  mechanism as rehire, just without a gap in between.

---

## 10. Data classification

Full field-by-field inventory (required/mutable/effective-dated/sensitivity/viewer/editor) for all
~90 documented fields is in `02_EMPLOYEE_DATA_MODEL.md §2` — every field traces to
`docs/product/08 §5` or a named FR-EMP-* requirement; none was invented. Summary mapping, per the
brief's nine categories:

| Category (brief) | Belongs to | Notes |
|---|---|---|
| 1. Identity (ID, legal name, preferred/display name, DOB, gender, photo) | `employee` | Mutable but not effective-dated — a name correction overwrites, it doesn't version (FR-EMP-009 distinguishes *controlled* fields needing a change-request workflow from freely-editable ones) |
| 2. Contact (personal email, work email, phone, address) | `employee` (personal email/mobile) + `employee_address` (structured address, not yet built) | Work email is typically sourced from `user`/identity, not duplicated on `employee` — confirm at implementation time |
| 3. Government/statutory (PAN, Aadhaar, UAN, PF, ESI, bank) | `employee` (PAN/Aadhaar/UAN — **encrypted at column level**, masked in API) + `employee_statutory` (PF/ESI/PT/tax regime, not yet built) + `employee_bank` (not yet built) | RESTRICTED classification (§13.3); blocks Payroll if not built (§5 row 6) |
| 4. Employment (joining date, status, type, probation, notice period, exit date/reason) | `employment` | Per-spell, not effective-dated within itself — a new spell is a new row, not a versioned attribute |
| 5. Organisation assignment (legal entity, branch, department, designation, grade, manager, shift) | `employment` (legal_entity_id) + `employee_assignment` (everything else, effective-dated) | See §6, §11 |
| 6. Compensation (CTC, salary structure, effective date) | `employee_compensation` | Effective-dated, RESTRICTED |
| 7. Documents (offer letter, joining docs, ID docs, education, experience, statutory docs) | `employee_document` (not yet built) | E-08 |
| 8. Emergency contacts | `employee_emergency_contact` (not yet built) | E-08, SENSITIVE |
| 9. Onboarding information | Not a separate table in the current design — captured as ordinary `employee`/`employment`/`employee_document` rows at creation time; no ATS/candidate-stage data model exists or is being proposed for V1 (§12) | |

Field-sensitivity tiers (`docs/product/19 §6`, detailed in §13.3):
`PUBLIC` (name, code, designation, department, work contact, photo) → `INTERNAL` (joining date,
manager, branch, shift, blood group) → `SENSITIVE` (personal mobile/email, address, DOB, emergency
contact, dependents) → `RESTRICTED` (CTC, salary components, bank account, PAN, Aadhaar, tax
declarations, disciplinary records — explicit permission only, always logged).

---

## 11. Effective-dating strategy

ADR-0003 (`docs/adr/0003-effective-dated-modelling.md`) is specific and titled for exactly this
domain: any employee attribute that changes over time lives in its own child table with
`effective_from DATE NOT NULL`, `effective_to DATE` (`NULL` = current), enforced by the GiST
exclusion constraint already live for `employee_assignment`/`employee_compensation` (§3.3-3.4). "A
change is always an **insert of a new row**, never an edit of an existing one's core values."

**Architecturally significant finding**: no module built so far (Company, Legal Entity, Branch,
Department, Designation, Grade, Shift) is effective-dated — every one is plain CRUD with
`is_active`/`deleted_at` + `version` + audit-log history
(`docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md:1258`: "None of this sprint's tables are
effective-dated... nothing in this sprint's scope changes over time in a way that needs history
preserved at the row level"). **Employee will be the first module in this codebase to actually
implement effective-dating in application code.** There is no existing repository/service pattern to
copy for "read the row effective on date X" or "close the current row and insert a new one" — this
must be designed from scratch, informed only by the DB-level exclusion constraint and ADR-0003's
prose.

### 11.1 Field placement
| Belongs on | Because | Examples |
|---|---|---|
| `employee` (mutable, not versioned) | Describes the person, not the job | name, DOB, gender, employee_code, photo, personal contact, PAN/Aadhaar (encrypted) |
| `employment` (per-spell, not effective-dated within itself) | Facts about one continuous period at one legal entity | legal_entity_id, joining_date, confirmation_date, probation_end_date, notice_period_days, exit_date, exit_type, status, is_rehire, previous_employment_id |
| `employee_assignment` (effective-dated) | "Current position" attributes that change over a career and must be historically queryable | branch, department, designation, grade, reporting_manager, dotted_line_manager, shift, cost_centre, work_location_type |
| `employee_compensation` (effective-dated) | Pay that changes on revision/promotion, must be reconstructable for any past payroll period | annual_ctc, salary_structure, revision_type/reason |
| `employee_statutory` / `employee_bank` (effective-dated, not yet built) | Statutory/banking facts that can change (PF opt-in, tax regime switch, bank account) and must be historically correct for payroll | PF/ESI/PT/tax_regime; account/IFSC/payment_mode |

### 11.2 Write pattern — insert, never update-in-place
1. Read the current row (`effective_to IS NULL`) for the employee.
2. `UPDATE ... SET effective_to = :new_effective_from - 1 day WHERE id = :current_row_id` — the one
   allowed "edit," touching only `effective_to`, never a business column.
3. `INSERT` a new row with `effective_from = :new_effective_from`, `effective_to = NULL`, the new
   business values.

Steps 2-3 happen in the same transaction. FR-EMP-003 states this explicitly for assignment changes.

### 11.3 Read pattern
- **Current**: `WHERE employee_id = :id AND effective_to IS NULL` (at most one row, by the exclusion
  constraint).
- **As of a date**: `WHERE employee_id = :id AND effective_from <= :date AND (effective_to IS NULL
  OR effective_to >= :date)` (at most one row).
- **Full history**: `WHERE employee_id = :id ORDER BY effective_from`.

**Recommendation**: implement this once as a shared repository/service helper
(`get_assignment_as_of(employee_id, date)`, `get_compensation_as_of(...)`), not re-derived ad hoc in
Attendance/Leave/Payroll — the "disciplined service-layer helper" ADR-0003's own consequences
section calls for. This satisfies the brief's own worked example directly: 2027 (Department A /
Grade 2 / Shift A) and 2028 (Department B / Grade 3 / Shift B) are two `employee_assignment` rows,
the 2027 row's `effective_to` set to the day before the 2028 row's `effective_from`, never
overwritten.

### 11.4 Backdating and future-dating (FR-EMP-004/005)
Future-dated changes are permitted — a row with a future `effective_from` can be inserted now; the
as-of-date read pattern already returns the right row for any date without a separate "activation"
step. Backdated changes are permitted only after the last finalised payroll period unless the actor
holds `PAYROLL.BACKDATE_OVERRIDE`.

---

## 12. Onboarding compatibility

`docs/product/02_PRD.md:133` and `docs/product/17_SRS §8-9` (full FR-REC-*, FR-ONB-*) still describe
candidate→offer→acceptance→onboarding→employee conversion as Phase 1/MVP scope in their body text.
**This is superseded.** `docs/product/VERSION_1_ROADMAP.md:29` explicitly reverses it: "Recruitment
(ATS)... is removed from Version 1 and moves to Version 2. Onboarding automation that is specifically
triggered by candidate-to-employee conversion moves with it," and states plainly that "Documents 00,
02, 17, 18 and 25 still describe Recruitment as Phase 1 in their body text — that is now stale...
this roadmap is the authority in the meantime." The roadmap is dated 2026-08-04 and declares itself
binding until superseded.

**Practical consequence for Employee's create flow**: per current authoritative scope, V1's Employee
Management group is "Employee Directory · Employee 360 · Employee Documents · Employment Information
· Reporting Structure · Employee Timeline · Employee Import" — no "Onboarding" or "candidate
conversion" row. FR-EMP-001's four creation paths ("manual form, candidate→employee conversion from
ATS, bulk Excel import, or API") reduce to **two** for V1: manual form and bulk Excel import (API
creation follows the same path as manual). Candidate-conversion (creating a `PRE_JOINING` employee
record from an accepted offer) is out of scope until V2's ATS ships.

**What must be designed now so a future onboarding flow doesn't require a rewrite**:
1. **Employee creation must not assume a candidate/offer precursor** — the manual-entry wizard and
   bulk import are both first-class, standalone creation paths (§14.3), not degraded fallbacks of an
   ATS-conversion path. A V2 ATS can add "convert from candidate" as an *additional* wizard variant
   that produces the same `employee`/`employment`/`employee_assignment`/`employee_compensation` rows
   the manual wizard does — it should not need a different underlying data shape.
2. **The `employee.status` state machine (FR-EMP-014) already includes `PRE_JOINING`** as one of its
   10 states — this means the identity/episode model already has room for a not-yet-started
   employee, which is exactly what an offer-accepted-but-not-yet-joined candidate would be. No
   change needed now; just don't build a status machine that omits this state.
3. **The rehire mechanism (§8) is itself the onboarding-compatibility mechanism for former
   employees** — "onboarding" for a returning employee is a rehire, not a new candidate flow. Get
   §8's data model right now and a future re-onboarding UX has something correct to build on.
4. **Document storage (E-08, `employee_document`) should not be ATS-specific** — offer letters,
   identity documents, education/experience documents are all just `employee_document` rows
   regardless of whether they arrived via manual upload or a future candidate portal. No separate
   "candidate document" table should be invented.

**Recommendation**: Employee's create flow (§16, `03_EMPLOYEE_API_PLAN.md`) should build no
candidate/offer/ATS coupling at all now. `docs/design/screens/01_Employee_List_Directory.md`'s
referenced 4-step Add-employee wizard is the manual-entry UX; bulk import is FR-EMP-006 (template
download, dry-run validation, all-or-nothing commit, 5,000-row cap). Both are V1-in-scope and
ATS-independent, and neither blocks a future onboarding build.

---

## 13. Permissions & security

### 13.1 Documented permission catalogue (`docs/product/19_RBAC_and_Permission_Matrix.md §3.1`)
14 codes: `EMPLOYEE.VIEW`, `.VIEW_ALL`, `.CREATE`, `.UPDATE`, `.UPDATE_SENSITIVE` ⚠, `.DEACTIVATE`,
`.VIEW_COMPENSATION` ⚠, `.UPDATE_COMPENSATION` ⚠, `.VIEW_DOCUMENTS`/`.UPLOAD_DOCUMENTS`/
`.VERIFY_DOCUMENTS`, `.VIEW_PERSONAL_CONTACT` ⚠, `.TRANSFER`/`.PROMOTE`/`.CONFIRM`,
`.IMPORT`/`.EXPORT` ⚠, `.GENERATE_LETTER`, `.VIEW_AUDIT`, `.BACKDATE_OVERRIDE` ⚠. Only
`EMPLOYEE.VIEW` is seeded in code today.

This is a **deliberately finer-grained catalogue** than the organisation module's own convention
(one `ORG.<ENTITY>.MANAGE` permission gating both view and manage). That convention suits simple
CRUD config entities; Employee's own RBAC doc specifies `VIEW` vs `VIEW_ALL` (self/team vs
company-wide) as a named, load-bearing distinction ("This distinction is what separates a Reporting
Manager from an HR Manager" — Doc 19 §2). **Recommendation: implement the full 14-code catalogue,
not the organisation module's single-permission shortcut** — collapsing it would silently regress a
documented, specific design decision (§17.4).

### 13.2 Data scope
`SELF`/`REPORTEES`/`REPORTEE_TREE`/`DEPARTMENT`/`BRANCH`/`LEGAL_ENTITY`/`COMPANY`/`ALL_COMPANIES`,
with a reference recursive-CTE implementation over `employee_assignment.reporting_manager_id WHERE
effective_to IS NULL`, Redis-cached 60s, invalidated on any `employee_assignment` write. This is
**new infrastructure** — `core/rbac`'s existing `DataScope`/`DataScopeLevel` type supports
`TEAM`/`SELF` in principle, but the organisation module never used anything but `COMPANY`
(hard-coded). Employee is the first real consumer of `SELF`/`REPORTEES`/`REPORTEE_TREE`.

### 13.3 Field-level security (`docs/product/19 §6`)
| Classification | Examples | Visible to |
|---|---|---|
| `PUBLIC` | name, employee_code, designation, department, work email/phone, photo | everyone in the company |
| `INTERNAL` | joining date, reporting manager, branch, shift, blood group | roles with `EMPLOYEE.VIEW` |
| `SENSITIVE` | personal mobile/email, address, DOB, emergency contact, dependents | HR roles + self |
| `RESTRICTED` | CTC, salary components, bank account, PAN, Aadhaar, tax declarations, disciplinary records | explicit permission only, always logged |

Masking formats: PAN `ABCDE****F`; Aadhaar `XXXX XXXX 1234`; Bank account `******7890`. Masked
fields are **omitted** from JSON, not sent as `null` (response-shape leak prevention). `RESTRICTED`
fields must never appear in an ordinary directory/list response; `SENSITIVE` fields are kept out of
Directory list columns even for roles that can see them elsewhere — surfaced only inside the 360°
profile. Special rules: a manager does not see salary by default; an HR Manager cannot edit their
own compensation/leave/attendance (self-service only, escalates to Company Admin).

### 13.4 Audit requirements
No document names literal audit-log `action` string constants for Employee — the pattern is the
same generic one the organisation module already implements:
`AuditService.record(entity_type, entity_id, action, before, after)`, called from the service layer
inside the same transaction as the write, CI-enforced. **Recommendation** (following the
organisation module's `<ENTITY>_CREATED/UPDATED/DEACTIVATED/REACTIVATED` convention):
- `employee`: `EMPLOYEE_CREATED`, `EMPLOYEE_UPDATED`, `EMPLOYEE_DEACTIVATED`, `EMPLOYEE_REACTIVATED`.
- `employment`: `EMPLOYMENT_STARTED`, `EMPLOYMENT_UPDATED`, `EMPLOYMENT_TERMINATED`,
  `EMPLOYMENT_REHIRED` (distinguishes a rejoin from a plain new hire in the audit trail).
- `employee_assignment`: `ASSIGNMENT_CHANGED` (single event, `change_type` carried in the `after`
  snapshot rather than fragmented into six action strings).
- `employee_compensation`: `COMPENSATION_REVISED`.

A separate `sensitive_access_log` table (FR-AUD-003) is specified for RESTRICTED-field *reads*, not
just writes — genuinely new, no existing pattern, no existing table. Flagged as decision §17.9: scope
it explicitly in/out of Employee's first slice rather than let it default to forgotten.

### 13.5 What to build, minimally
Per the brief's instruction not to invent a large permission system unnecessarily: the 14 codes are
already specified by product (not invented by this audit) and are the minimum the documented UX
(§14) requires — the Compensation tab alone needs at least `VIEW_COMPENSATION`/`UPDATE_COMPENSATION`
to be absent-not-disabled correctly. Do not add further codes beyond the 14 without a documented
need.

---

## 14. Frontend UX proposal

No UI is implemented here — this is a design proposal, reconciling the existing
`04_EMPLOYEE_UX_PLAN.md` design with the concrete frontend technical gaps found in this audit's
codebase read (§2.4).

### 14.1 Screen inventory (from `docs/product/24_UIUX_Screen_Inventory_and_Design_System.md §3.3`)
Directory (table + card view) · Filters panel · Employee 360° (tabbed profile) · Add-employee
wizard (4 steps) · Edit employee (reuses 360°'s tab-level edit, no separate page) · Transfer/
Promotion · Salary revision · Confirmation (within Employment tab) · Document upload/verification
queue · Bulk import (4 screens: upload → validate → preview → commit) · Import history · Letter
generation/templates · Org chart · Profile change requests · Employee export.

### 14.2 The 360° profile — tabs, not a giant form
Per `docs/product/24 §4.1`: a **persistent header** (photo, name, code, designation, department,
manager, status, quick actions) with **tabbed content below**. "Permission-gated tabs are absent,
not disabled-and-visible — showing a locked tab tells the user something exists that they cannot
see, which invites social-engineering requests to HR."

| Tab | Shows | Permission | Edit surface |
|---|---|---|---|
| **Profile** | Identity, Contact | `EMPLOYEE.VIEW` (self always visible) | `.UPDATE` for uncontrolled fields; controlled fields (name/DOB/bank/PAN/address, FR-EMP-009) submit a profile-change-request instead of writing directly |
| **Job** | Current + historical Assignment | `EMPLOYEE.VIEW` | `.TRANSFER`/`.PROMOTE` open a dedicated workflow (§14.4), not an inline field edit |
| **Compensation** | Current + historical Compensation (+ Statutory/Bank as a sub-section, pending a dedicated permission decision — §17.9) | `EMPLOYEE.VIEW_COMPENSATION` — **entire tab absent without it** | `.UPDATE_COMPENSATION` opens the salary-revision workflow |
| **Attendance** / **Leave** | out of scope — modules not built | — | tab hidden entirely, not a "coming soon" placeholder — "absent, not disabled" applied at the module-readiness level, not just the permission level |
| **Documents** | `employee_document` list | `EMPLOYEE.VIEW_DOCUMENTS` | `.UPLOAD_DOCUMENTS`/`.VERIFY_DOCUMENTS` |
| **Assets** / **Performance** | out of scope (V3) | — | hidden until built |
| **Timeline** | `employee_event` unified feed | `EMPLOYEE.VIEW` | system-generated only |

**Status indicators**: a status badge in the persistent header sourced from `employee.status`
(FR-EMP-014's 10-state machine) — reuse the existing `Badge` component's variant pattern, likely
needing new semantic variants beyond `default/secondary/destructive/outline` (e.g. a distinct color
for `PROBATION`/`ON_NOTICE`/`SUSPENDED` vs `ACTIVE` vs `EXITED`).

**Employment episode display**: where an employee has more than one `employment` row (rehire), the
header/Job tab should show which spell is current and make prior spells reachable — e.g. an
"Employment History" section listing each spell's date range and exit reason, distinct from the
Assignment history within a spell. This is new UX not covered by the existing 4-step wizard/tab
design and should be scoped explicitly in E-03/E-09 rather than assumed to fall out of the
generic history view.

**Assignment/compensation history**: a read-only timeline of past effective-dated rows, each showing
its `effective_from`/`effective_to` range and `change_reason` — satisfies the brief's own worked
example (2027 vs 2029 assignment) directly.

### 14.3 Add-employee wizard (4 steps)
1. **Identity & contact** — mandatory: first name (DOB not required, only joining date is).
2. **Employment & organisation** — mandatory: joining date, legal entity, branch, department,
   designation, employment type, reporting manager (nullable — explicitly allowed for a CEO-level
   hire per FR-EMP-002).
3. **Compensation** (permission-gated — step is skipped entirely, not shown-disabled, for a creator
   without `EMPLOYEE.UPDATE_COMPENSATION`).
4. **Review & confirm** — `employee_code` shown as system-allocated, not editable; submit creates
   `employee` + `employment` + first `employee_assignment` + first `employee_compensation` in one
   transaction.

No ATS/candidate step (§12). A match against an existing exited employee's PAN/Aadhaar/email during
step 1 should surface a non-blocking "Link to existing record" action that switches the wizard from
"create new employee" to "create new employment for `EMP-000123`" — buildable only once the rejoin
data-model decision (§17.1) is confirmed.

### 14.4 Transfer / Promotion / Salary revision — workflow screens, not inline edits
Because these are effective-dated inserts, not column updates, the UX differs from the plain
PATCH-and-save form used everywhere in the organisation module's frontend today:
- **Effective date picker** mandatory — the user is explicitly choosing when the new row starts.
- **"What changes" preview before submit** — old value → new value per field, plus the computed
  `effective_to` written onto the row being closed.
- **Backdating into a locked payroll period** should surface the `PAYROLL.BACKDATE_OVERRIDE` gate
  visibly (disabled submit + explanation) rather than a raw 403/422 after the fact — buildable only
  once Payroll's lock-period check exists; until then the screen should not attempt to enforce it
  client-side.

### 14.5 Technical foundations this module needs that don't exist yet
Reusable as-is from the organisation module (§2.4): `PageHeader`, `EmptyState`, `ErrorState`,
`LoadingState`, `useToast`, `FormField`, `Badge`, the `apiClient` wrapper, and the
`version`+`If-Match`+`STALE_RESOURCE`-banner optimistic-concurrency pattern (every editable
sub-resource — Profile, Job, Compensation — should carry its own `version` and reuse this exact
conflict-resolution UI).

**New, must be built once, not per-tab**:
- A `Tabs` primitive (`@radix-ui/react-tabs` is not yet installed; add it, consistent with the
  existing thin-Radix-wrapper-plus-`cva` convention used for `dialog.tsx`/`dropdown-menu.tsx`).
- A `Timeline`/history-list component for assignment/compensation/employment-episode history — no
  such component exists in `apps/web/src/components` today.
- A `usePermission`/`PermissionGate` primitive, since `UserProfile.permissions` is already returned
  by the API but nothing consumes it — this is what makes "tab absent, not disabled" actually
  implementable instead of a 403-after-click. Recommend building this now rather than reusing the
  reactive-403-toast pattern per-tab, since Employee is the first module where whole sections must
  be gated proactively (Compensation tab, RESTRICTED fields) rather than just individual write
  actions.
- Likely a `DataTable`/virtualized-list component for the Directory (current organisation-module
  list pages use a plain `<ul>`, adequate for dozens of rows, not the "1,000+ rows, virtualization-
  first" requirement `docs/design/screens/01_Employee_List_Directory.md §7` specifies).

### 14.6 Test conventions to replicate
Vitest + Testing Library, co-located `page.test.tsx`, hand-built fixtures, `vi.mock` for
`next/navigation`/`auth-context`/`toast`/`apiClient`, exact-payload assertions on PATCH/POST calls
including `If-Match`. Employee's detail-page tests should cover the same checklist every
organisation entity's tests do (load, 404, edit/cancel, save+If-Match, stale-resource conflict,
status toggle, domain-specific conflict codes) plus tab-switching and permission-gated-tab-absence
coverage specific to Employee.

---

## 15. Dependencies

### 15.1 What Employee depends on (all already shipped)
```
Company
 └── Legal Entity ──────────────┐
      └── Branch ───────────────┤
           └── Department ──────┤
                └── Designation ┤──▶ Employee (employee_assignment FKs: branch_id,
                └── Grade ──────┤              department_id, designation_id, grade_id)
      (company-wide) Shift ─────┘   (employee_assignment.shift_id — column not yet
                                      added to the live table, §3.3)
      (Employment.legal_entity_id — direct FK, already live)
```
Every one of these six modules is complete (317/317 backend tests, 227/227 frontend tests per the
Shift Rules closeout) and already exposes the IDs Employee's `employee_assignment`/`employment`
tables reference. No further organisation-module work is required before Employee's first slice
can begin, **except** the FR-ORG-014 retrofit (§2.3, §17.5), which is not a blocker for Employee
itself — it's a follow-up Employee's existence unblocks.

### 15.2 What Employee unlocks
```
Employee
 ├── Attendance   — needs: get_assignment_as_of() (branch, shift, manager), employment/employee
 │                   status, a stable employee_id across rejoin (§9)
 ├── Leave        — needs: employment.status, employment.joining_date, employee_assignment.
 │                   department_id, and (unresolved) the BR-14 policy-resolution override chain
 ├── Payroll      — needs: employment.legal_entity_id, employee_compensation (as-of pay period),
 │                   employee_statutory + employee_bank (§5 row 6 — not built, blocks Payroll if
 │                   deferred), employment.status for LOP/exit handling
 ├── ESS          — needs: Employee's own self-service surface (Profile tab edits, profile-change
 │                   requests) — largely satisfied by Employee's own slices, not a separate module
 ├── Manager workflows — needs: employee_assignment.reporting_manager_id (as-of-date), the
 │                   REPORTEE_TREE data-scope resolver (§13.2)
 ├── Onboarding (V2) — needs: the rehire/identity model (§8) already being correct; no ATS coupling
 │                   required from Employee itself (§12)
 └── Offboarding (minimal Exit, V1) — needs: employment.status → EXITED transition, exit_date/
                     exit_reason fields (present in the documented target, missing from the live
                     schema, §3.2); full F&F settlement additionally needs Payroll
```

### 15.3 Cross-module dependency contracts (the specific queries other modules need)
| Consumer needs | Employee provides | Source |
|---|---|---|
| Active employment on date Y? | `employment.status`, `joining_date`/`exit_date` range check | `employment` |
| Branch/shift/manager on date Y? | `get_assignment_as_of(employee_id, date)` (§11.3 pattern) | `employee_assignment` |
| Current employment status (Attendance's status-resolution precedence)? | `employee.status` (FR-EMP-014) | `employee` |
| Department-scoped leave calendar/policy | `employee_assignment.department_id` as-of-date | `employee_assignment` |
| Statutory jurisdiction, PF/ESI/tax for a pay period | `employment.legal_entity_id`, `employee_statutory` as-of pay period | `employment`, `employee_statutory` (not built) |
| Bank account for payout | `employee_bank` as-of pay period | `employee_bank` (not built) |
| Stable identity across a rejoin gap | unchanged `employee_id` | `employee` |

**Recommendation**: expose one canonical service method per as-of-date query
(`get_assignment_as_of`, `get_compensation_as_of`) rather than let each consumer re-derive the SQL —
per `docs/architecture/02_Module_Standard.md §2`, cross-module imports may only go through
`employee.service`, never `employee.repository`/`employee.models` directly.

---

## 16. Proposed vertical slices

Full detail (objective/backend/database/API/frontend/tests/dependencies/risks per slice) is in
`01_EMPLOYEE_MODULE_PLAN.md`; summarized here with each slice's database change, permission surface,
audit events, and primary risk.

| Slice | Objective | Database | Permissions | Audit events | Primary risk |
|---|---|---|---|---|---|
| **E-01** Foundation | `employee/` package scaffold; identity CRUD | Extend `employee`; build `number_series` + `EMPLOYEE_CODE` allocator (new infra) | `EMPLOYEE.CREATE/VIEW/VIEW_ALL/UPDATE/DEACTIVATE` | `EMPLOYEE_CREATED/UPDATED/DEACTIVATED/REACTIVATED` | Number-series race-safety; `EMPLOYEE_SEATS` enforcement point unconfirmed (§17.6) |
| **E-02** Profile completion | Full identity/contact fields, address, emergency contact, change-request workflow | `employee_address`, `employee_emergency_contact` (new tables) | `.UPDATE`, `.UPDATE_SENSITIVE`, `.VIEW_PERSONAL_CONTACT` | `EMPLOYEE_UPDATED` | Field-controllability list (FR-EMP-009) is example-only, not exhaustive |
| **E-03** Employment lifecycle | `Employment` model, FR-EMP-014 status machine, confirmation/probation, exit-initiation hook | Extend `employment` (incl. `is_rehire`/`previous_employment_id`) | `.CONFIRM` | `EMPLOYMENT_STARTED/UPDATED/TERMINATED/REHIRED` | Rejoin (§17.1) and `employment.status` value-set (§5 row 3) must both be settled before this starts |
| **E-04** Assignment | `EmployeeAssignment` model, as-of-date read helper, transfer/promotion/manager-change | Extend `employee_assignment` (adds `dotted_line_manager_id`, `cost_centre_id`, `work_location_type`, `change_reason`, `change_type`; adds missing FKs) | `.TRANSFER`, `.PROMOTE` | `ASSIGNMENT_CHANGED` | First effective-dated write path in this codebase — no precedent to copy, budget extra review |
| **E-05** Shift assignment | Adds `shift_id` to assignment | `ALTER TABLE employee_assignment ADD COLUMN shift_id` + FK | (folds into `.TRANSFER`) | (folds into `ASSIGNMENT_CHANGED`, `change_type=SHIFT_CHANGE`) | BR-14 override chain explicitly not built here — consumers must handle `shift_id IS NULL` |
| **E-06** Compensation | `EmployeeCompensation` extension, `employee_compensation_component` child table, revision workflow | Extend `employee_compensation` | `.VIEW_COMPENSATION`, `.UPDATE_COMPENSATION` | `COMPENSATION_REVISED` | `approval_request_id` implies an approval-routing engine that doesn't exist yet — store the field, don't enforce the gate |
| **E-07** Statutory | `EmployeeStatutory` new model | `CREATE TABLE employee_statutory` | (view/update gap — §17.9) | (new event) | Blocks Payroll if deferred; view-permission gap unresolved |
| **E-08** Documents/dependents/education/experience/skills/banking | New models for each | `CREATE TABLE` × 6, `employee_bank` effective-dated | `.VIEW_DOCUMENTS`/`.UPLOAD_DOCUMENTS`/`.VERIFY_DOCUMENTS` | (per-entity events) | Virus-scan and expiry-alert notification depend on infra not yet built — scope to storage/CRUD, flag the gap |
| **E-09** Directory/profile UI, import/export, letters | Frontend (Directory, 360°, wizard), bulk import/export, letter templates | import batch/audit table if needed | `.IMPORT`/`.EXPORT`, `.GENERATE_LETTER` | (import/export events) | Field-visibility/data-scope matrix is the most failure-prone part — a mistake here is a privacy leak |
| **E-10** Security/audit/integration hardening | Full 14-permission RBAC enforced, `sensitive_access_log` (if scoped in), `get_assignment_as_of` finalized as the public cross-module contract, FR-ORG-014 retrofit into org module | none new | `.VIEW_AUDIT`, `.BACKDATE_OVERRIDE` | (audit-log completeness verification) | Easiest slice to compress under schedule pressure — treat as non-optional given Employee's central-dependency role |

**Sequencing rule**: each slice independently shippable and testable; later slices never re-migrate
a table an earlier slice already built (mirrors how Designation→Grade were sequenced). Module
boundary: `apps/api/src/hrms/modules/employee/` is its own package (confirmed by two independent
docs — `docs/architecture/01_Backend_Structure.md:70`, `VERSION_1_ROADMAP.md §8`), not folded into
`organisation` — flagged for confirmation at §17.8 since it's a deviation from how Company through
Shift were all built.

---

## 17. Open product decisions

Each with a recommendation; none pre-decided in code.

1. **Rejoin mechanics** (§8): confirm same `employee_id`/`employee_code` reuse, new `employment` row
   with `is_rehire`/`previous_employment_id`. *Recommendation: adopt as described in §8.4.*
2. **Build `employee_statutory`/`employee_bank` now, or defer?** (§5 row 6, §15.3): Payroll's
   dependency contract needs them; no later module is documented as owning them.
   *Recommendation: build as part of Employee's own migration set, even with no UI surface until
   Payroll ships.*
3. **The BR-14/FR-EMP-018 override-chain mechanism** (§4, §14.2): spans five already-shipped modules,
   no buildable spec exists anywhere. *Recommendation: Employee ships only the confirmed leg
   (`employee_assignment.shift_id`, a direct per-employee value); the cascading-default mechanism is
   a separate, later, cross-module decision.*
4. **RBAC granularity** (§13.1): full 14-code catalogue vs. the organisation module's
   single-permission shortcut. *Recommendation: full catalogue — documented, specific, partially
   already seeded.*
5. **FR-ORG-014 retrofit into Branch/Department/Designation/Grade** (§2.3): once Employee exists,
   these four modules need an active-employee-count deactivation-blocking check added.
   *Recommendation: a small, separate follow-up task against the organisation module, not bundled
   into Employee's own vertical slices.*
6. **`EMPLOYEE_SEATS` enforcement** (§2.3): no document specifies where/how the seat-limit check
   fires. *Recommendation: `EmployeeService.create_employee` counts active employees against
   `plan.employee_seat_limit` and rejects before insert, mirroring how existing write-blocking
   errors gate writes elsewhere in the organisation module.*
7. **Migration approach for the four live stub tables** (§3): extend in place via `ALTER TABLE`
   (matching every organisation-module precedent) rather than drop-and-recreate.
   *Recommendation: extend in place.* Also decide whether to add `version` to `employment` for
   consistency (§5 row 9).
8. **Module location**: confirm `modules/employee/` as its own package, distinct from
   `organisation`. *Recommendation: confirm — Employee is large enough to justify its own module
   boundary, and the documentation already assumes it.*
9. **`sensitive_access_log`** (§13.4) and the **Statutory/Bank tab's view permission** (§14.2): both
   new, no existing pattern. *Recommendation: scope explicitly in/out of Employee's first slices
   rather than let either default to forgotten.*
10. **Frontend permission-gating primitive** (§2.4, §5 row 10): build a `usePermission`/
    `PermissionGate` now, or continue the reactive-403-only pattern. *Recommendation: build it now —
    Employee is the first module where whole sections (Compensation tab, RESTRICTED fields) must be
    proactively absent, not just individually write-protected.*

---

## 18. Risks

- **Effective-dating has no precedent in this codebase** (§11) — the insert/close-row transaction
  pattern must be designed and reviewed from scratch; get this wrong in E-04 (the first slice that
  writes to an effective-dated table) and every downstream consumer (Attendance/Leave/Payroll)
  inherits the bug.
- **Two decisions block E-03 from starting cleanly**: the rejoin mechanics (§17.1) and the
  `employment.status` value-set (§5 row 3) both touch `employment`, Employee's second table — an
  unresolved decision here risks a second migration shortly after the first.
- **Payroll-blocking gap**: `employee_statutory`/`employee_bank` don't exist; if their build is
  deferred past Employee's own slices, Payroll cannot be built correctly when its turn comes (§15.2,
  §17.2).
- **Privacy/security surface is large and new**: this is the first module in the codebase handling
  RESTRICTED-tier data (CTC, bank, PAN, Aadhaar) and the first needing proactive UI-level gating
  (§13.3, §14.5) — a mistake in the Directory's field-visibility matrix or the Compensation tab's
  gating is a privacy leak, not a cosmetic bug (flagged explicitly in E-09's own risk entry).
- **`EMPLOYEE_SEATS` and number-series are both unbuilt infrastructure** Employee's first slice
  depends on (§9, §17.6) — underestimating this as "just add a column" risks a rushed, race-unsafe
  implementation of the code allocator specifically (Doc 08 §4's own explicit warning against
  `SELECT max()+1`).
- **BR-14 override chain is a cross-cutting gap spanning five already-shipped modules** (§17.3) — a
  temptation to "just build it while we're in here" during Employee's assignment slice should be
  resisted; it's a separate architectural decision with its own review, not an Employee sub-task.
- **Frontend has no Tabs/Timeline/PermissionGate/DataTable primitives today** (§14.5) — building all
  four as one-offs inside Employee's own slices risks inconsistent, Employee-specific versions that
  later modules (Attendance/Leave tabs on the same profile) would need to either copy or retrofit;
  worth a small shared-component task ahead of E-09, not embedded silently inside it.
- **E-10 (security/audit hardening) is the easiest slice to cut under schedule pressure** because it
  ships no visible feature — given Employee's central-dependency role, treat it as non-optional
  rather than a stretch goal.
- **Scope-creep risk into Attendance/Leave/Payroll/Employee Assignment implementation** — this audit
  and its companions define *contracts* those modules will consume (§15.3); actually building them
  is explicitly out of scope for Employee's own slices and must not be pulled forward.

---

## 19. Recommended implementation order

```
Decisions gate (§17 items 1, 2, 3, 5, 7, 8 — resolve before writing Employee's first migration)
        │
        ▼
E-01 Foundation ──┬──▶ E-02 Profile
 (identity, code   │
  allocator, seat   ├──▶ E-03 Employment ──┬──▶ E-04 Assignment ──┬──▶ E-05 Shift
  limit)            │    (rejoin, status    │    (as-of-date read, │    (shift_id only,
                     │     machine — needs   │     transfer/promo)  │     BR-14 chain
                     │     §17.1/§5-row-3)   │                      │     deferred)
                     │                       └──▶ E-06 Compensation │
                     │                                              │
                     └──▶ E-07 Statutory ◀── (needs E-03)           │
                     └──▶ E-08 Documents/dependents/bank            │
                                                                     ▼
                                                       E-09 Directory/Profile UI/
                                                       Import/Export/Letters
                                                       (needs E-01..E-08; needs new
                                                        frontend primitives — Tabs,
                                                        Timeline, PermissionGate,
                                                        DataTable — built ahead of or
                                                        alongside this slice)
                                                                     │
                                                                     ▼
                                                       E-10 Security/Audit Hardening
                                                       (RBAC catalogue, sensitive_access_log,
                                                        FR-ORG-014 retrofit, finalize
                                                        cross-module service contract)
```

**Attendance readiness** = E-01 + E-03 + E-04 + E-05, with §17 items 1/3 resolved before E-03/E-05
start. E-06 through E-08 (compensation, statutory, bank, documents) are not blocking for Attendance
specifically, but Leave and Payroll need them (§15.2) — do not treat E-10's hardening as skippable
just because Attendance doesn't strictly require it.

**Immediately actionable, before any slice begins**: resolve the decisions gate above (§17), since
three of them (rejoin mechanics, `employment.status` values, migration approach) directly shape the
first table Employee's first migration touches.

---

## Appendix — Explicit out of scope (this audit and the resulting implementation)

ATS/Recruitment/Candidate/Requisition/Offer (including the offer-letter template), the onboarding
pre-boarding portal and task-pack automation, Performance/LMS/Asset/Expense/Visitor/Helpdesk, the
Workflow Builder (visual configurator), Attendance/Leave/Payroll implementation themselves (only
their dependency *contracts* on Employee are specified, §15), the BR-14 override-chain cascading-
resolution mechanism (§17.3) until product decides which module owns it, and any FR-ORG-014 retrofit
into Branch/Department/Designation/Grade (§17.5) — tracked as a follow-up, not part of Employee's
own slices.
