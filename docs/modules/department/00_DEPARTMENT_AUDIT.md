# Department Module — Pre-Implementation Audit

Status: **Audit only — no code changed.** Follows the same audit-then-build discipline used
for Legal Entity and Branch (`docs/modules/branch/00_BRANCH_AUDIT.md`). This document
inspects the current DB, the completed Branch slice (the pattern to replicate), and all
Department references across product docs, then states exactly what Department needs, what's
already there, and what decisions are needed before writing code.

---

## 1. Current state

**Department has zero application code.** No ORM model, no repository/service/router
methods, no Pydantic schemas, no permission code, no frontend page, no dedicated test file.

The only things that exist today:

- A **DB-level stub table** `department`, created in the original baseline schema
  (`apps/api/scripts/sql/001_init_schema.sql:159-171`) — present since the first migration,
  never touched since. Columns: `id, company_id, branch_id (nullable), name, code (nullable),
  parent_id (nullable, self-referential — no FK constraint declared), created_at, updated_at,
  deleted_at`. No `is_active`, no `version`.
- **Incidental, defensive references** from the Branch slice, which explicitly treats
  Department as "not yet built" and works around that (exactly mirroring how Legal Entity
  once treated Branch the same way):
  - `OrganisationRepository.count_active_departments_for_branch()`
    (`apps/api/src/hrms/modules/organisation/repository.py:434-448`) — raw SQL
    (`SELECT count(*) FROM department WHERE branch_id = :branch_id AND deleted_at IS NULL`)
    because "the Department module itself is out of scope for this slice (no ORM model
    yet)." **This raw SQL currently has no `is_active` filter** because `department` has no
    `is_active` column yet — exactly the same situation Branch was in before this slice, and
    the same class of bug: once this slice adds `department.is_active`, this query must gain
    `AND is_active = true` or a *deactivated* department will still incorrectly block Branch
    deactivation. This is a required fix in this slice (§5.2 below), not optional.
  - `BranchDeactivationBlockedError` (`.../organisation/exceptions.py:68-85`), code
    `BRANCH_HAS_ACTIVE_DEPARTMENTS`.
- **Frontend**: no Department screen exists. `CompanyDashboardSummary.department_count`
  (`.../organisation/schemas.py:504`) always returns `None` (`service.py:503`), same
  placeholder pattern `branch_count` had before Branch shipped (and still has — Branch's own
  slice explicitly left wiring the dashboard count out of scope; same call made here).
- **Documentation**: no `docs/modules/department/` directory existed before this audit.
  Department is discussed only inside broader docs (SRS FR-ORG-005/FR-ORG-014, Database
  Architecture §4, RBAC matrix, the Sprint 3 plan's Feature 3.2, and Branch's own module doc
  §10 "future Employee relationship" note).

**The good news**: the Branch slice, which just shipped, is a complete, current reference
implementation of the exact pattern Department must follow — same module (`organisation`),
same layering, same conventions. It is the primary source for "how" in this audit. The
Sprint 3 plan and Database Architecture doc are the primary sources for "what," with one
important caveat (§9 below): the Sprint 3 plan's Task 3.2.1–3.2.3 scope is **broader** than
this task's own instructions, and this audit follows this task's explicit instructions where
the two disagree, flagging every such divergence.

---

## 2. Database state

### 2.1 What exists today

`department` table (`apps/api/scripts/sql/001_init_schema.sql:159-171`):

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | PK, `gen_random_uuid()` default |
| `company_id` | UUID NOT NULL | FK'd (`department_company_id_fkey → company(id) ON DELETE RESTRICT ON UPDATE CASCADE`, line 413) |
| `branch_id` | UUID (nullable) | FK'd (`department_branch_id_fkey → branch(id) ON DELETE SET NULL ON UPDATE CASCADE`, line 416) — **nullable at both schema and FK level, confirming a Department does not require a Branch** |
| `name` | VARCHAR(150) NOT NULL | |
| `code` | VARCHAR(30) (nullable) | no uniqueness constraint |
| `parent_id` | UUID (nullable) | self-referential — **no FK constraint declared today** |
| `created_at` / `updated_at` | TIMESTAMPTZ NOT NULL | |
| `deleted_at` | TIMESTAMPTZ | reserved, unused |

Indexes today: `department_company_id_idx` only (line 341).

Referenced by: `designation.department_id` (FK, `ON DELETE SET NULL`, line 422 — Designation
is out of scope this slice, no application code exists for it either) and
`employee_assignment.department_id` (column only, line 263 — Employee is out of scope).

**RLS**: `department` is included in the generic tenant-isolation loop embedded directly in
`001_init_schema.sql:467-483` (`ENABLE`/`FORCE ROW LEVEL SECURITY` + a `tenant_isolation`
policy on `company_id`), alongside `legal_entity`, `branch`, etc. **Same caveat carried over
from both prior audits, verbatim**: this loop is not the live RLS registry for any
environment where the table predates an edit to that file — both Legal Entity's and Branch's
own migrations re-asserted RLS idempotently regardless of the loop's nominal coverage. §3
below carries this forward as required, not optional, for Department too.

### 2.2 What the spec requires

`docs/product/08_Database_Architecture.md:181` (§4, Organisation Master):

```
department | id, company_id, parent_id, code, name, head_employee_id, cost_centre_id, is_active
```

`docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md` Feature 3.2 (Tasks 3.2.1–3.2.3) elaborates:

- **Task 3.2.1 (Department backend)**: expand the stub to support FR-ORG-005's hierarchy
  rules (cycle rejection, max 5 levels) and the remaining §4 columns. Migration adds
  `head_employee_id UUID NULL` (FK → `employee`, per binding Scope Decision **D10**: "built
  as a nullable FK column but has no UI control this sprint... the column exists now so a
  later sprint doesn't need a migration to add it" — same forward-compatible-schema-now
  pattern as `number_series`/D7), `cost_centre_id UUID NULL` (FK → a **new** `cost_centre`
  table, built in the separate Task 3.2.2), `is_active BOOLEAN DEFAULT true`,
  `version INTEGER DEFAULT 1`. Self-referential `parent_id` FK. Service-layer cycle
  detection (walk the candidate parent's ancestor chain, depth-capped at 5; reject if the
  department's own id appears — `409 CONFLICT DEPARTMENT_CYCLE_DETECTED`; reject if depth
  would exceed 5). `GET /v1/departments/tree` (recursive CTE, nested JSON). Permission
  `ORG.DEPARTMENT.MANAGE`.
- **Task 3.2.2 (Cost Centre)**: a *separate* task building a new `cost_centre` table
  (`id, company_id, code, name, gl_code`), its own minimal CRUD, its own permission
  (`ORG.COST_CENTRE.MANAGE`), and *then* adding the deferred `department.cost_centre_id` FK.
- **Task 3.2.3 (Department frontend)**: a **tree view** screen (not a flat table — explicitly
  called out as "one of the two places... where a tree visualization is the primary UI"),
  built on `GET /v1/departments/tree`, with a `Sheet` drawer for create/edit and a
  parent-department `Combobox` that excludes the node's own descendants.

`docs/product/17_SRS_Phase1_Core_Modules.md:96` (FR-ORG-005): "Department: name, code, head
(employee), parent department, cost centre. Hierarchy must reject cycles." (M priority)

`docs/product/17_SRS_Phase1_Core_Modules.md:105` (FR-ORG-014): "Deactivating an org unit
(branch/department/designation) is allowed only if no active employee is assigned; otherwise
show the blocking list. Never hard-delete." — note this is the *literal* org-wide rule;
Branch's own task additionally glossed it as "blocked by active department" specifically for
Branch (an interpretive elaboration written into Branch's own sprint task, not a
generically-restated rule for every org unit — see §5.1 below for what this means for
Department specifically).

### 2.3 Gap: existing column vs. target

| Column | Status |
|---|---|
| `id`, `company_id`, `branch_id`, `name`, `code`, `parent_id` | ✅ present, keep as-is (parent_id gains an FK constraint, currently missing) |
| `is_active`, `version` | ❌ missing — needed for the same soft-deactivate + optimistic-concurrency pattern Branch/Legal Entity use |
| `head_employee_id` | ❌ missing — **added this slice as a passive, unexposed schema column only**, per D10 and §9.1 below |
| `cost_centre_id` | ❌ missing — **intentionally deferred**, see §9.2 |

---

## 3. Required data model

### 3.1 ORM model — `organisation/models.py::Department`

Same file as `LegalEntity`/`Branch` (the `organisation` module owns the whole
Company→Employee hierarchy per `docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md`'s owning-module
column — no new `modules/department/` package).

```python
class Department(Base, TimestampMixin):
    __tablename__ = "department"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    branch_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("branch.id"), nullable=True, index=True
    )
    parent_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("department.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(150))
    code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    head_employee_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employee.id"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
```

`cost_centre_id` intentionally absent per §9.2. `head_employee_id` exists at the model/DB
level only — **not** exposed by any Pydantic schema, service method, or frontend field this
slice (§9.1).

### 3.2 Migration

New file, e.g. `apps/api/alembic/versions/20260813140000_department_fields.py`
(`down_revision = "20260813130000"`, chained after the Branch migration — current head).
Content mirrors the Branch/Legal Entity migrations' shape:

```sql
ALTER TABLE department
  ADD COLUMN IF NOT EXISTS head_employee_id UUID,
  ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;

ALTER TABLE department
  ADD CONSTRAINT department_parent_id_fkey
    FOREIGN KEY (parent_id) REFERENCES department(id) ON DELETE SET NULL ON UPDATE CASCADE;

ALTER TABLE department
  ADD CONSTRAINT department_head_employee_id_fkey
    FOREIGN KEY (head_employee_id) REFERENCES employee(id) ON DELETE SET NULL ON UPDATE CASCADE;

CREATE INDEX IF NOT EXISTS department_company_active_idx
  ON department (company_id, is_active) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS department_parent_id_idx ON department (company_id, parent_id);
CREATE INDEX IF NOT EXISTS department_branch_id_idx ON department (branch_id);

-- Re-assert RLS idempotently — see §2.1 caveat.
ALTER TABLE department ENABLE ROW LEVEL SECURITY;
ALTER TABLE department FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON department;
CREATE POLICY tenant_isolation ON department
  USING (company_id = current_setting('app.company_id', true)::uuid);
```

`department_parent_id_idx` matches `docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md`'s own
Database Architecture appendix note ("`department` | `(company_id, parent_id)` | Tree-walk
queries") — useful for the cycle-detection ancestor walk (§5.1) even without a `/tree`
endpoint.

### 3.3 Schemas (`organisation/schemas.py`)

Add `DepartmentCreate`, `DepartmentUpdate`, `DepartmentRead`, `department_to_read`,
`build_department_update_values` — same shape as the `Branch*` quartet. Differences from
Branch's schema set:

- `branch_id: UUID | None` — **optional** on create (confirmed by the DB's own nullable FK
  and Database Architecture's `department (company_id, branch_id?)` annotation — a Department
  does not require a Branch, unlike Branch's own required `legal_entity_id`).
- `parent_id: UUID | None` — optional; validated server-side (must belong to the same
  company, must not create a cycle, must not exceed depth 5 — §5.1).
- `code`, `head_employee_id` — `code` optional per the DB stub; `head_employee_id` **not** a
  schema field at all this slice (§9.1).
- `is_active` server-controlled on create, client-settable via PATCH only — same rule as
  Branch/Legal Entity.

---

## 4. API requirements

Per this task's own explicit instructions (Phase 4), which are narrower than the full Sprint
3 plan's Task 3.2.1 (§9.3 flags this divergence explicitly):

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/v1/departments` | `ORG.DEPARTMENT.MANAGE` | List, company-scoped, unfiltered (same low-cardinality assumption as Branch/Legal Entity's own list endpoints — no `?branch_id=`/`?parent_id=` filtering this slice, see §9.3) |
| POST | `/v1/departments` | `ORG.DEPARTMENT.MANAGE` | Create; `is_active` always `true` |
| GET | `/v1/departments/{department_id}` | `ORG.DEPARTMENT.MANAGE` | 404 (never 403) cross-tenant or not-found |
| PATCH | `/v1/departments/{department_id}` | `ORG.DEPARTMENT.MANAGE` | `If-Match: <version>`; partial update; `is_active` togglable here; `parent_id` changes re-run cycle/depth checks |
| DELETE | `/v1/departments/{department_id}` | `ORG.DEPARTMENT.MANAGE` | Soft deactivation only; `If-Match`; returns `200 DataEnvelope<DepartmentRead>`, not `204` (matches this API's actual convention, not the Sprint 3 plan's `204` note — see §9.3) |

`GET /v1/departments/tree` is **not built this slice** — see §9.3.

---

## 5. Business rules

### 5.1 Hierarchy: cycle rejection + max depth 5 (FR-ORG-005)

Documented explicitly, so implemented: before setting/changing `parent_id` (on create or
update), walk the candidate parent's ancestor chain. Reject with `409 CONFLICT
DEPARTMENT_CYCLE_DETECTED` if the department's own id appears in that chain (only relevant on
update, since a department can't reference itself as parent on create before it has an id —
but a direct self-reference, `parent_id == own id`, is also rejected as a degenerate cycle).
Reject with `409 CONFLICT DEPARTMENT_MAX_DEPTH_EXCEEDED` if the resulting depth would exceed
5 levels. Implemented as a small iterative ancestor walk (bounded to 5 lookups) in the
repository/service, not a SQL recursive CTE — a CTE is unnecessary complexity for a
5-hop-max bounded walk, and this slice does not build the `/tree` endpoint that would
otherwise justify one (§9.3).

`parent_id`, when provided, must reference a Department belonging to the same company —
same cross-tenant-rejection posture as Branch's `legal_entity_id` check (`422
INVALID_PARENT_DEPARTMENT` on a bad/foreign id, not a raw FK/500).

### 5.2 A real bug this slice must fix in Branch's existing code

`OrganisationRepository.count_active_departments_for_branch`
(`repository.py:434-448`) currently counts departments by `deleted_at IS NULL` only — correct
*only* because `department` had no `is_active` column to distinguish "deactivated" from
"still active." Once this slice adds `department.is_active`, this query becomes wrong: a
**deactivated** department (`is_active = false`, `deleted_at` still `NULL`) would still count
as active and incorrectly block Branch deactivation. Must be updated to `AND is_active =
true AND deleted_at IS NULL` **as part of this slice** — the same mechanical, unavoidable
consequence Branch's own slice had for `count_active_branches_for_legal_entity`.

### 5.3 Deactivation blocking — what actually applies to Department

FR-ORG-014's literal text blocks deactivation of an org unit "only if no active employee is
assigned." **No document states that Department deactivation is blocked by active
sub-departments or by active Designations** — unlike Branch, whose own sprint task
explicitly glossed FR-ORG-014 as "blocked by active department." No equivalent explicit
gloss exists for Department in Task 3.2.1's text. Employee does not exist, so the one
documented blocker cannot be implemented at all this slice (exactly as Branch also deferred
"the employee half" of its own blocking rule).

**Conclusion — do not invent an undocumented blocker.** This slice ships Department
deactivation/reactivation with **no active-dependency check**: any Department can be
deactivated regardless of active sub-departments or (once it exists) Designations
referencing it. This is flagged as a decision required in §8 rather than silently assumed,
with the recommendation to ship it this way (safest minimal behavior — deactivation is
reversible via reactivation, and no other shipped module reads `department.is_active` yet,
so there is no real data-integrity exposure from leaving it unblocked this slice).

### 5.4 Uniqueness

**Not enforced.** No product document (SRS, Database Architecture, Sprint 3 plan, RBAC
matrix) specifies a uniqueness rule for `department.code` or `department.name` — same
"don't invent" posture Branch took for its own `code`/`name`. Flagged as a known gap, not
silently assumed either way.

### 5.5 Optimistic concurrency

`version` + `If-Match`, identical mechanism to Legal Entity, Branch, Company.

### 5.6 Branch/parent ownership validation

`branch_id`, when provided, must reference a Branch belonging to the same company (`422
INVALID_BRANCH` — same posture/shape as Branch's own `INVALID_LEGAL_ENTITY`). No rule
requires a sub-department's `branch_id` to match its parent's `branch_id` — not documented,
not invented.

---

## 6. Permission requirements

Single permission, matching the Company/Legal Entity/Branch precedent exactly:

```python
ORG_DEPARTMENT_MANAGE = "ORG.DEPARTMENT.MANAGE"
```

Add to `ORGANISATION_PERMISSIONS` and grant it to the `COMPANY_ADMIN` system role at
registration time in `OrganisationService.register_company`, the same
`get_or_create_permission` → `insert_role_permission` pattern used for
`ORG_BRANCH_MANAGE`/`ORG_LEGAL_ENTITY_MANAGE`. `docs/product/19_RBAC_and_Permission_Matrix.md:100`
independently confirms the exact code — no naming conflict to reconcile (unlike Legal
Entity's own `ORG.ENTITY.MANAGE` vs `ORG.LEGAL_ENTITY.MANAGE` mismatch). No RBAC doc edit
needed.

---

## 7. Tenant / RLS / audit requirements

Identical mechanism to every other `organisation`-module resource — `TenancyMiddleware` +
`get_tenant_context`, belt-and-suspenders `company_id` filtering in every repository method,
RLS re-asserted idempotently in the migration (§3.2). Cross-tenant access, including a
guessed `department_id` or a cross-tenant `branch_id`/`parent_id` reference, must return
`404`/`422` as appropriate, never leak.

Audit events via the existing `AuditService`, mirroring Branch's four:
`DEPARTMENT_CREATED`, `DEPARTMENT_UPDATED`, `DEPARTMENT_DEACTIVATED`,
`DEPARTMENT_REACTIVATED`, `entity_type = "department"`, before/after `DepartmentRead`
snapshots. No `RESTRICTED`-classified fields on this resource.

---

## 8. Decisions required from you

1. **Deactivation blocking** (§5.3): ship with no active-dependency check this slice (no
   documented blocker is buildable — Employee doesn't exist and no doc names
   sub-departments/Designations as blockers). **Recommendation: yes, ship unblocked**,
   documented as a known gap, revisited once Employee (and possibly Designation) exist.
2. **`head_employee_id`** (§3.1, §9.1): add as a passive, unexposed nullable FK column this
   migration (per binding Scope Decision D10), or omit entirely like Branch's
   `holiday_calendar_id`/`week_off_pattern_id`? **Recommendation: add it** — D10 is an
   explicit, already-made "binding — do not relitigate" call in the source doc, the FK target
   (`employee` table) already exists at the DB level, and the column stays completely inert
   (no schema/service/UI exposure) so it cannot leak or be misused without Employee's own
   application code.
3. **`GET /v1/departments/tree` + tree UI** (§9.3): this task's own Phase 7 explicitly asks
   for a flat list + detail page mirroring Branch's UI, not the Sprint 3 plan's tree/Sheet
   drawer UI. **Recommendation: follow this task's explicit instructions** — flat list/detail
   pages, no `/tree` endpoint, hierarchy still enforced server-side (cycle/depth rules) and
   surfaced via a "Parent department" field in the list/detail views, same treatment Branch
   gave its own Legal Entity relationship.
4. **Cost Centre** (§9.2): out of scope entirely this slice (separate Task 3.2.2, not named
   in this task's instructions). **Recommendation: exclude**, no `cost_centre_id` column, no
   inline combobox.
5. **`code`/`name` uniqueness** (§5.4): no doc specifies either. **Recommendation: don't
   enforce**, same as Branch.

---

## 9. Documentation inconsistencies / scope divergences found

1. **This task's instructions are narrower than Sprint 3 plan Task 3.2.1–3.2.3** in three
   ways, each treated as a deliberate, documented scope decision rather than a silent
   omission:
   - No `GET /v1/departments/tree` endpoint this slice (§4, §8.3).
   - No tree-view/Sheet-drawer frontend this slice — flat list/detail pages instead (§8.3).
   - No Cost Centre entity/FK this slice (§8.4).
2. **`head_employee_id` treatment differs from Branch's own deferred-FK precedent**
   (`holiday_calendar_id`/`week_off_pattern_id`, which were omitted entirely pending their
   own future migrations) — here the column *is* added now, per D10's explicit binding
   instruction rather than Branch's own default "omit until the target module ships"
   pattern. Both are legitimate, doc-sourced choices for their respective columns; this is
   not a contradiction, just a difference worth calling out explicitly so it isn't mistaken
   for an inconsistency in this audit's own reasoning.
3. **`DELETE` response shape**: the Sprint 3 plan's own API table (line 1329) says `DELETE
   /departments/{id}` returns `204`; the actual, current, already-shipped convention for
   every other organisation-module `DELETE` (Legal Entity, Branch) returns `200
   DataEnvelope<DepartmentRead>` with `is_active: false`. Recommend following the real
   shipped convention, not the plan's `204` note — same resolution style Legal Entity/Branch
   already used once each for their own doc/code path divergences.
4. **RLS "already there" is not reliable** — same trap as both prior audits; re-assert
   idempotently regardless of the `001_init_schema.sql` loop's nominal coverage (§2.1, §3.2).
5. No contradiction found on the base field set itself — Database Architecture (`08 §4`) and
   FR-ORG-005 agree with each other on `name, code, parent_id, head_employee_id,
   cost_centre_id, is_active`.

---

## 10. Recommended implementation plan

Scoped to this task's own Phase 3–9 instructions (Department CRUD + hierarchy, not the full
Sprint 3 Task 3.2.1–3.2.3 breadth):

1. **Migration**: add `head_employee_id`, `is_active`, `version`; add `parent_id` FK; add
   indexes; re-assert RLS idempotently.
2. **Model**: `Department` in `organisation/models.py`.
3. **Schemas**: `DepartmentCreate`/`DepartmentUpdate`/`DepartmentRead` + mapper functions
   (no `head_employee_id`/`cost_centre_id` fields).
4. **Exceptions**: `InvalidBranchError` (or reuse a generic pattern), `InvalidParentDepartmentError`,
   `DepartmentCycleDetectedError`, `DepartmentMaxDepthExceededError`.
5. **Repository**: `insert_department`/`list_departments`/`get_department`/`update_department`
   (mirror the Branch four) + an ancestor-walk helper for cycle/depth checks + the one-line
   fix to `count_active_departments_for_branch`'s `WHERE` clause.
6. **Service**: `create_department`/`list_departments`/`get_department`/`update_department`/
   `deactivate_department`, branch/parent ownership validation, cycle/depth enforcement,
   audit calls for all four event types.
7. **Permissions**: `ORG_DEPARTMENT_MANAGE`, granted to `COMPANY_ADMIN` at registration.
8. **Router**: five endpoints, same envelope/header conventions as Branch.
9. **Frontend**: `lib/department/{types,validate-department}.ts(+.test.ts)`,
   `components/department/department-form.tsx` (Branch + Parent Department pickers),
   `app/app/departments/{page,[id]/page}.tsx(+.test.tsx)`, nav item.
10. **Tests**: unit + integration for Department (cycle/depth/branch/parent validation
    included), Department cases added to the three shared suites
    (`test_cross_tenant_isolation.py`, `test_permission_matrix.py`,
    `test_organisation_security.py`), frontend component tests.
11. **Docs**: `docs/modules/department/01_Department_Module.md` +
    `02_Department_API.md`, following Branch's two-file shape.

## 11. Explicit out-of-scope items

Per this task's instructions and this audit's findings, **not** part of this slice:
Designation, Grade, Holiday Calendar, Shift Rules, Employee, Attendance, Leave, Payroll,
Cost Centre, `GET /v1/departments/tree`, the tree-view/Sheet-drawer frontend, and any
active-dependency deactivation-blocking check (no documented rule to implement — §5.3/§8.1).
