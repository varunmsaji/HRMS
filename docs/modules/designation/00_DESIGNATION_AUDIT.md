# Designation Module — Pre-Implementation Audit

Status: **Audit only — no code changed.** Follows the same audit-then-build discipline used
for Legal Entity, Branch, and Department (`docs/modules/department/00_DEPARTMENT_AUDIT.md`).
This document inspects the current DB, the completed Department slice (the pattern to
replicate), and all Designation references across product docs, then states exactly what
Designation needs, what's already there, and what decisions are needed before writing code.

---

## 1. Current state

**Designation has zero application code.** No ORM model, no repository/service/router
methods, no Pydantic schemas, no permission code, no frontend page, no dedicated test file.
Confirmed by a repo-wide search: no `apps/api/src/hrms/**/*.py` file references
"designation" anywhere today — the exact same zero-code starting point Department was in.

The only things that exist today:

- A **DB-level stub table** `designation`, created in the original baseline schema
  (`apps/api/scripts/sql/001_init_schema.sql:174-184`) — present since the first migration,
  never touched since. Columns: `id, company_id, department_id (nullable), title,
  created_at, updated_at, deleted_at`. No `code`, no `grade_id`, no `is_active`, no
  `version`.
- Indexes today: `designation_company_id_idx` only (line 344).
- FK constraints today: `designation_company_id_fkey → company(id) ON DELETE RESTRICT`
  (line 419) and `designation_department_id_fkey → department(id) ON DELETE SET NULL`
  (line 422) — the `department_id` FK is nullable at both schema and FK level, confirming a
  Designation does not require a Department.
- Referenced by: `employee_assignment.designation_id` (column only, line 264 — Employee is
  out of scope), and by name only (no FK) in `requisition.designation_id`,
  `candidate.current_designation`, `offer.designation_id` — all Recruitment-module tables,
  themselves out of scope.
- **RLS**: `designation` is included in the generic tenant-isolation loop embedded directly
  in `001_init_schema.sql:467-483` (alongside `department`, `branch`, etc.) and independently
  named in the standalone `apps/api/scripts/sql/002_row_level_security.sql:18`. **Same
  caveat carried over from all three prior audits, verbatim**: neither of these files is the
  live RLS registry for any environment where the table predates an edit to them — Legal
  Entity, Branch, and Department's own migrations all re-asserted RLS idempotently
  regardless of this nominal coverage. §3 below carries this forward as required, not
  optional, for Designation too.
- **Frontend**: no Designation screen exists. No `designation_count` field exists on
  `CompanyDashboardSummary` at all (unlike `department_count`, which pre-existed as a
  `None`-returning placeholder before Department shipped) — see §9.4.
- **Documentation**: no `docs/modules/designation/` directory existed before this audit.
  Designation is discussed only inside broader docs (SRS FR-ORG-006/FR-ORG-014, Database
  Architecture §4, RBAC matrix, API Standards' endpoint table, and the Sprint 3 plan's
  Feature 3.3).

**The good news**: the Department slice, which just shipped, is a complete, current
reference implementation of the exact pattern Designation must follow — same module
(`organisation`), same layering, same conventions (optional parent-like FK ownership
validation, soft deactivation, optimistic concurrency, audit events). It is the primary
source for "how" in this audit. The Sprint 3 plan and Database Architecture doc are the
primary sources for "what," with the same important caveat Department's own audit flagged
(§9 below): the Sprint 3 plan's Task 3.3.1–3.3.3 scope is **broader** than this task's own
instructions — most importantly, it bundles **Grade** into the same feature — and this audit
follows this task's explicit instructions where the two disagree, flagging every such
divergence.

---

## 2. Database state

### 2.1 What exists today

`designation` table (`apps/api/scripts/sql/001_init_schema.sql:174-184`):

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | PK, `gen_random_uuid()` default |
| `company_id` | UUID NOT NULL | FK'd (`designation_company_id_fkey → company(id) ON DELETE RESTRICT ON UPDATE CASCADE`, line 419) |
| `department_id` | UUID (nullable) | FK'd (`designation_department_id_fkey → department(id) ON DELETE SET NULL ON UPDATE CASCADE`, line 422) — **nullable at both schema and FK level, confirming a Designation does not require a Department** |
| `title` | VARCHAR(150) NOT NULL | the Designation's "name" field — already called `title`, not `name`, at the DB level |
| `created_at` / `updated_at` | TIMESTAMPTZ NOT NULL | |
| `deleted_at` | TIMESTAMPTZ | reserved, unused |

No `code`, `grade_id`, `next_designation_id`, `jd_document_id`, `is_active`, or `version`
columns exist yet.

### 2.2 What the spec requires

`docs/product/08_Database_Architecture.md:182` (§4, Organisation Master):

```
designation | id, company_id, code, title, grade_id, department_id NULL, jd_document_id, next_designation_id
```

`docs/product/17_SRS_Phase1_Core_Modules.md:97` (FR-ORG-006): "Designation: title, grade/band,
department (optional), job description reference, career-path next designation." (M priority)

`docs/product/17_SRS_Phase1_Core_Modules.md:105` (FR-ORG-014): "Deactivating an org unit
(branch/department/designation) is allowed only if no active employee is assigned; otherwise
show the blocking list. Never hard-delete." — the same literal org-wide rule Department's own
audit already analyzed; Employee doesn't exist, so this can't be checked for Designation
either (see §5.3).

`docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md` Feature 3.3 (Tasks 3.3.1–3.3.3) elaborates —
**and is the source of this audit's single most important scope conflict**:

- **D2** (binding scope decision, line 18): "**Grade is built alongside Designation, not
  deferred**... Designation reference `grade_id`, and the existing `designation`/`grade` stub
  tables are already FK-linked in the current schema. Building Designation without Grade
  would leave a dangling FK the UI can't populate." — **this directly conflicts with this
  task's own explicit instruction**: "Do NOT implement Employee, Attendance, Shift Rules,
  **Grade**, Payroll, or any unrelated module in this task" (stated twice in this task's own
  instructions, including in the OBJECTIVE and IMPORTANT SCOPE BOUNDARY sections). Per this
  audit's operating rule (§9), **this task's explicit boundary wins**: Grade is not built,
  and `grade_id` is not added to `designation` this slice. See §5.7/§8.1 for the full
  reasoning and the resulting treatment (parallel to how Department excluded
  `cost_centre_id`, not to how it included `head_employee_id`).
- **Task 3.3.1 (Grade backend)**: out of scope entirely (see above).
- **Task 3.3.2 (Designation backend)**: "Expand the existing `designation` stub... to the
  full `docs/product/08` §4 shape." Migration adds `code VARCHAR(30)`, `grade_id UUID NULL`
  (excluded, see above), `next_designation_id UUID NULL` (self FK, per **D10** — "no UI this
  sprint"; `jd_document_id` **explicitly not added** — "no document-management module exists
  to reference, deferred to whenever that module ships, not tracked as a forward-reference
  placeholder since unlike the others there's no concrete near-term consumer"), `is_active
  BOOLEAN DEFAULT true`, `version INTEGER DEFAULT 1`. Permission `ORG.DESIGNATION.MANAGE`.
  States a deactivation-blocking rule: "Deactivation blocked if referenced by an active
  employee (future) — for now, blocked if `next_designation_id` of another designation
  points to it (can't remove a career-path target still in use)." — see §5.4 for why this is
  **not implementable as stated** given `next_designation_id`'s own D10 treatment.
- **Task 3.3.3 (Designation & Grade frontend)**: a **combined** "Designations & Grades"
  screen — out of scope for the Grade half (§9.1); Designation's own half (list/create/edit,
  optional Department picker) is in scope and mirrors Department's own flat-list UI pattern.

`docs/product/09_API_Standards.md:245` independently confirms the endpoint shape with no
Grade coupling: `GET/POST /designations   GET/PATCH/DELETE /designations/{id}` — this matches
this task's own Phase 3 instructions exactly, with no ambiguity.

`docs/product/19_RBAC_and_Permission_Matrix.md:100` confirms the permission code exactly:
`ORG.DESIGNATION.MANAGE`, alongside `.DEPARTMENT.MANAGE`, `.GRADE.MANAGE` (Grade's own
permission, not needed this slice) — no naming conflict to reconcile.

### 2.3 Gap: existing column vs. target (this slice's target, per §9 scope resolution)

| Column | Status |
|---|---|
| `id`, `company_id`, `department_id`, `title` | ✅ present, keep as-is |
| `code` | ❌ missing — added this slice, per Database Architecture §4 |
| `is_active`, `version` | ❌ missing — needed for the same soft-deactivate + optimistic-concurrency pattern every other organisation-module resource uses |
| `next_designation_id` | ❌ missing — **added this slice as a passive, unexposed schema column only**, per D10 and §5.4/§8.2 below |
| `grade_id` | ❌ missing — **intentionally excluded this slice**, see §5.7/§8.1 |
| `jd_document_id` | ❌ missing — **intentionally excluded**, explicitly stated in the source doc itself (no document-management module exists); not a decision this audit needs to make |

---

## 3. Required data model

### 3.1 ORM model — `organisation/models.py::Designation`

Same file as `LegalEntity`/`Branch`/`Department` (the `organisation` module owns the whole
Company→Employee hierarchy).

```python
class Designation(Base, TimestampMixin):
    __tablename__ = "designation"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    department_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("department.id"), nullable=True, index=True
    )
    next_designation_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("designation.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(150))
    code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
```

`grade_id` and `jd_document_id` intentionally absent per §5.7/§9.1. Unlike Department's
`head_employee_id` (which could not be a real SQLAlchemy `ForeignKey` because no `Employee`
ORM model exists), `next_designation_id` **can** be a real `ForeignKey("designation.id")` —
it is self-referential to the very model being defined, which SQLAlchemy resolves fine.
`next_designation_id` exists at the model/DB level only — **not** exposed by any Pydantic
schema, service method, or frontend field this slice (§5.4).

### 3.2 Migration

New file, e.g. `apps/api/alembic/versions/20260813150000_designation_fields.py`
(`down_revision = "20260813140000"`, chained after the Department migration — current head).
Content mirrors the Department migration's shape:

```sql
ALTER TABLE designation
  ADD COLUMN IF NOT EXISTS code VARCHAR(30),
  ADD COLUMN IF NOT EXISTS next_designation_id UUID,
  ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;

ALTER TABLE designation
  ADD CONSTRAINT designation_next_designation_id_fkey
    FOREIGN KEY (next_designation_id) REFERENCES designation(id) ON DELETE SET NULL ON UPDATE CASCADE;

CREATE INDEX IF NOT EXISTS designation_company_active_idx
  ON designation (company_id, is_active) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS designation_department_id_idx ON designation (department_id);

-- Re-assert RLS idempotently — see §2.1 caveat.
ALTER TABLE designation ENABLE ROW LEVEL SECURITY;
ALTER TABLE designation FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON designation;
CREATE POLICY tenant_isolation ON designation
  USING (company_id = current_setting('app.company_id', true)::uuid);
```

`designation_department_id_fkey` already exists (§2.1) — no change needed there.

### 3.3 Schemas (`organisation/schemas.py`)

Add `DesignationCreate`, `DesignationUpdate`, `DesignationRead`, `designation_to_read`,
`designation_to_audit_dict`, `build_designation_update_values` — same shape as the
`Department*` quintet.

- `title: str` — required (mirrors Department's `name`), max length 150.
- `code: str | None` — optional, max length 30.
- `department_id: UUID | None` — optional; validated server-side (must belong to the same
  company — no hierarchy/cycle logic needed, unlike Department's self-referential
  `parent_id`, since a Designation references a *different* entity type, Department, not
  itself).
- `grade_id`, `next_designation_id`, `jd_document_id` — **not** schema fields at all this
  slice (§5.7, §5.4, §9.1).
- `is_active` server-controlled on create, client-settable via PATCH only — same rule as
  every other organisation-module resource.

---

## 4. API requirements

Per this task's own explicit instructions (Phase 3), which match
`docs/product/09_API_Standards.md:245` exactly and are narrower than the full Sprint 3 plan's
Task 3.3.1–3.3.3 (§9 flags the Grade-bundling divergence):

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/v1/designations` | `ORG.DESIGNATION.MANAGE` | List, company-scoped, unfiltered (same low-cardinality assumption Department's own list endpoint made — no `?department_id=`/`?grade_id=`/`?status=` filtering this slice, despite the Sprint plan's API table naming those filters, see §9.3) |
| POST | `/v1/designations` | `ORG.DESIGNATION.MANAGE` | Create; `is_active` always `true` |
| GET | `/v1/designations/{designation_id}` | `ORG.DESIGNATION.MANAGE` | 404 (never 403) cross-tenant or not-found |
| PATCH | `/v1/designations/{designation_id}` | `ORG.DESIGNATION.MANAGE` | `If-Match: <version>`; partial update |
| DELETE | `/v1/designations/{designation_id}` | `ORG.DESIGNATION.MANAGE` | Soft deactivation only; `If-Match`; returns `200 DataEnvelope<DesignationRead>`, not `204` (matches this API's actual shipped convention for every other organisation-module `DELETE`, not the Sprint 3 plan's `204` note — see §9.3, same resolution Department's own audit already made once) |

---

## 5. Business rules

### 5.1 Department ownership validation

`department_id`, when provided, must reference a Department belonging to the same company
(`422 INVALID_DEPARTMENT` on a bad/foreign id, not a raw FK/500) — same posture/shape as
Department's own `INVALID_BRANCH` check for its `branch_id`.

### 5.2 No hierarchy/cycle logic needed

Unlike Department's `parent_id` (self-referential, requiring cycle/depth checks),
Designation's `department_id` references a *different* entity. The one genuinely
self-referential field, `next_designation_id`, is not exposed this slice (§5.4), so there is
no settable self-reference to validate against cycles. **No cycle-detection code is needed
for Designation this slice** — a meaningful difference from Department's own pattern, not an
omission.

### 5.3 Deactivation blocking

FR-ORG-014's literal text blocks deactivation of an org unit "only if no active employee is
assigned." Employee does not exist, so this can't be checked — identical situation to
Department. **No document states that Designation deactivation is blocked by active
sub-Designations via `department_id`** (Designation doesn't have sub-Designations; that
relationship belongs to Department). The only other named blocker is the
`next_designation_id`-reference rule (§5.4), which is not buildable as stated this slice.

**Conclusion — do not invent an undocumented blocker.** This slice ships Designation
deactivation/reactivation with **no active-dependency check**, identical to Department's own
resolution. Flagged as a decision required in §8 rather than silently assumed.

### 5.4 The `next_designation_id`-referenced deactivation-blocking rule is not implementable as stated

Sprint 3 Task 3.3.2 names a specific rule: "blocked if `next_designation_id` of another
designation points to it (can't remove a career-path target still in use)." This rule
presumes `next_designation_id` is a *settable* field somewhere (otherwise nothing could ever
reference it, and the check would be permanently vacuous). But **D10** — the same binding
scope decision this Sprint doc uses to justify adding the column at all — says
`next_designation_id` "has no UI control this sprint," the identical treatment given to
Department's `head_employee_id`, which Department's own audit and implementation kept
completely unexposed (no schema field, no service method, no UI).

This is a genuine internal tension in the source document, not a fabricated one: D10 (binding
column-level decision) and Task 3.3.2's own deactivation-rule text (which assumes the column
is populatable) point in different directions. Resolution, consistent with how Department's
own audit resolved an analogous tension (§5.3 there — a named rule with no buildable
mechanism is not implemented, and is flagged rather than invented around): **add
`next_designation_id` as a passive, unexposed column per D10's literal instruction; do not
implement the reference-based deactivation-blocking check this slice**, since nothing can
ever populate the column that check would query. Flagged as a decision in §8.2 and a known
limitation in the module doc.

### 5.5 Uniqueness

**Not enforced.** No product document (SRS, Database Architecture, Sprint 3 plan, RBAC
matrix) specifies a uniqueness rule for `designation.code` or `designation.title` — same
"don't invent" posture Department took for its own `code`/`name`.

### 5.6 Optimistic concurrency

`version` + `If-Match`, identical mechanism to every other organisation-module resource.

### 5.7 Grade is out of scope — `grade_id` is not added

This task's own instructions state, twice, that Grade must not be implemented in this task.
The Sprint 3 plan's own Feature 3.3 treats Grade and Designation as a single bundled feature
(D2: "Grade is built alongside Designation, not deferred... Designation reference `grade_id`
... Building Designation without Grade would leave a dangling FK the UI can't populate").
This is a direct, explicit conflict between the two sources.

Per this audit's operating rule (§9, and the identical rule Department's own audit already
established), **this task's explicit boundary instructions win over the Sprint 3 plan when
they conflict**. Grade is not built. `grade_id` is therefore not added to `designation` this
slice — treated the same way Department treated `cost_centre_id` (a documented FK target
whose *own* owning entity doesn't exist and is out of scope this slice: excluded entirely,
not added as a passive/inert column), **not** the way Department treated `head_employee_id`
(added as a passive/inert column). The distinguishing factor: `head_employee_id`'s target
table (`employee`) already exists as a real DB table with a binding instruction (D10) to add
the passive column now; `grade_id`'s target table (`grade`) exists as a DB stub too, but no
binding instruction independent of the excluded Grade feature calls for adding `grade_id`
specifically — D2 bundles it with building Grade itself, which this task forbids. Excluding
it entirely, rather than inventing a new passive-column precedent unsupported by any
decision scoped to `grade_id` alone, is the more conservative, doc-following choice.

Consequence: `docs/product/08_Database_Architecture.md`'s full column list for `designation`
(`id, company_id, code, title, grade_id, department_id, jd_document_id,
next_designation_id`) is not fully implemented this slice — `grade_id` and `jd_document_id`
are both absent, for two different, independently-justified reasons (§5.7, and the source
doc's own explicit jd_document_id exclusion respectively).

---

## 6. Permission requirements

Single permission, matching the Company/Legal Entity/Branch/Department precedent exactly:

```python
ORG_DESIGNATION_MANAGE = "ORG.DESIGNATION.MANAGE"
```

Add to `ORGANISATION_PERMISSIONS` and grant it to the `COMPANY_ADMIN` system role at
registration time in `OrganisationService.register_company`, the same
`get_or_create_permission` → `insert_role_permission` pattern used for
`ORG_DEPARTMENT_MANAGE`/`ORG_BRANCH_MANAGE`/`ORG_LEGAL_ENTITY_MANAGE`.
`docs/product/19_RBAC_and_Permission_Matrix.md:100` and
`docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md:1412` both independently confirm the exact
code — no naming conflict to reconcile. No RBAC doc edit needed.

---

## 7. Tenant / RLS / audit requirements

Identical mechanism to every other `organisation`-module resource — `TenancyMiddleware` +
`get_tenant_context`, belt-and-suspenders `company_id` filtering in every repository method,
RLS re-asserted idempotently in the migration (§3.2). Cross-tenant access, including a
guessed `designation_id` or a cross-tenant `department_id` reference, must return `404`/`422`
as appropriate, never leak.

Audit events via the existing `AuditService`, mirroring Department's four:
`DESIGNATION_CREATED`, `DESIGNATION_UPDATED`, `DESIGNATION_DEACTIVATED`,
`DESIGNATION_REACTIVATED`, `entity_type = "designation"`, before/after `DesignationRead`
snapshots. No `RESTRICTED`-classified fields on this resource.

---

## 8. Decisions required from you

1. **Grade / `grade_id`** (§5.7): this task's explicit instructions forbid implementing
   Grade, which directly conflicts with the Sprint 3 plan's D2 ("Grade built alongside
   Designation, not deferred"). **Recommendation: follow this task's explicit boundary —
   exclude Grade and `grade_id` entirely this slice**, same resolution style Department used
   once for a doc/instruction divergence (§9 there). This is the single highest-impact
   decision in this audit; every other decision below is comparatively minor.
2. **`next_designation_id`** (§5.4): add as a passive, unexposed nullable self-FK column per
   D10 (parallel to Department's `head_employee_id`), but do **not** implement the
   reference-based deactivation-blocking rule Task 3.3.2 names, since D10 leaves the column
   unpopulatable this slice, making that check permanently vacuous if built.
   **Recommendation: add the column passively, skip the blocking check**, flagged as a known
   limitation.
3. **Deactivation blocking generally** (§5.3): ship with no active-dependency check this
   slice, identical to Department's own resolution. **Recommendation: yes, ship unblocked**,
   documented as a known gap, revisited once Employee (and Grade, if ever built) exist.
4. **`code`/`title` uniqueness** (§5.5): no doc specifies either. **Recommendation: don't
   enforce**, same as Department's `code`/`name`.
5. **Combined "Designations & Grades" frontend screen** (§9.1): the Sprint 3 plan names one
   combined screen; this task's instructions ask for Designation only. **Recommendation:
   build the Designation half only** — flat list + detail page, Department picker, mirroring
   Department's own UI pattern exactly, with no Grade sub-tab/split-pane.
6. **`designation_count` on the Company dashboard** (§9.4): does not exist as a field at all
   today (unlike `department_count`, which pre-existed Department's own slice).
   **Recommendation: do not add it** — same "out of scope for a single-module vertical
   slice" call Department's own audit made for wiring `department_count`.

---

## 9. Documentation inconsistencies / scope divergences found

1. **This task's instructions conflict with Sprint 3 plan Feature 3.3 on Grade** (§5.7,
   §8.1) — the most significant divergence found in this audit. The Sprint plan's own D2
   explicitly anticipates and rejects this exact split ("Building Designation without Grade
   would leave a dangling FK the UI can't populate") — this audit's resolution (§5.7) directly
   addresses that concern: no `grade_id` FK is added at all, so there is no dangling FK to
   populate. The plan's own worry does not apply once the FK itself is excluded.
2. **Internal tension between D10 and Task 3.3.2's deactivation rule for
   `next_designation_id`** (§5.4) — a rule that presumes a column D10 itself says has "no UI
   control this sprint" is populatable. Resolved by following D10 literally and not building
   the dependent check (§5.4, §8.2).
3. **`DELETE` response shape**: the Sprint 3 plan's own API table (line 1336) says `DELETE
   /designations/{id}` returns `204`; the actual, current, already-shipped convention for
   every other organisation-module `DELETE` (Legal Entity, Branch, Department) returns `200
   DataEnvelope<DesignationRead>` with `is_active: false`. Recommend following the real
   shipped convention, not the plan's `204` note — the same resolution Department's own audit
   already made once for this exact divergence.
4. **List-endpoint filtering**: the Sprint plan's API table (line 1332) names
   `department_id`, `grade_id`, `status` query filters on `GET /designations`; `grade_id`
   doesn't apply once Grade is excluded, and no other organisation-module list endpoint
   (Branch, Department) implements query filtering yet — Department's own audit explicitly
   declined to add `?branch_id=`/`?parent_id=` filtering "no filtering this slice." Recommend
   the same here for consistency, deferred to whenever query filtering is added
   module-wide, not invented per-resource.
5. **RLS "already there" is not reliable** — same trap as all three prior audits; re-assert
   idempotently regardless of `001_init_schema.sql`'s loop or `002_row_level_security.sql`'s
   nominal coverage (§2.1, §3.2).
6. No contradiction found on the base field set itself, once Grade/`jd_document_id` are
   excluded — Database Architecture (`08 §4`) and FR-ORG-006 agree with each other on
   `title, code, department_id` as the buildable field set.

---

## 10. Recommended implementation plan

Scoped to this task's own Phase 3–9 instructions (Designation CRUD, not the full Sprint 3
Task 3.3.1–3.3.3 breadth, and explicitly not Grade):

1. **Migration**: add `code`, `next_designation_id`, `is_active`, `version`; add
   `next_designation_id` FK; add indexes; re-assert RLS idempotently.
2. **Model**: `Designation` in `organisation/models.py`.
3. **Schemas**: `DesignationCreate`/`DesignationUpdate`/`DesignationRead` + mapper functions
   (no `grade_id`/`next_designation_id`/`jd_document_id` fields).
4. **Exceptions**: `InvalidDepartmentError` (mirrors `InvalidBranchError`).
5. **Repository**: `insert_designation`/`list_designations`/`get_designation`/
   `update_designation` (mirror the Department four; no ancestor-walk helper needed, §5.2).
6. **Service**: `create_designation`/`list_designations`/`get_designation`/
   `update_designation`/`deactivate_designation`, department ownership validation, audit
   calls for all four event types.
7. **Permissions**: `ORG_DESIGNATION_MANAGE`, granted to `COMPANY_ADMIN` at registration.
8. **Router**: five endpoints, same envelope/header conventions as Department.
9. **Frontend**: `lib/designation/{types,validate-designation}.ts(+.test.ts)`,
   `components/designation/designation-form.tsx` (Department picker only), `app/app/
   designations/{page,[id]/page}.tsx(+.test.tsx)`, nav item.
10. **Tests**: unit + integration for Designation (department ownership validation
    included), Designation cases added to the three shared suites
    (`test_cross_tenant_isolation.py`, `test_permission_matrix.py`,
    `test_organisation_security.py`), frontend component tests.
11. **Docs**: `docs/modules/designation/01_Designation_Module.md` +
    `02_Designation_API.md`, following Department's two-file shape.

## 11. Explicit out-of-scope items

Per this task's instructions and this audit's findings, **not** part of this slice: Grade
(and therefore `designation.grade_id`), `jd_document_id`, `next_designation_id` exposure/UI,
the `next_designation_id`-referenced deactivation-blocking check, Employee, Attendance, Shift
Rules, Payroll, Recruitment (`requisition`/`candidate`/`offer` designation references),
query-param filtering on `GET /designations`, the combined "Designations & Grades" screen,
and any active-dependency deactivation-blocking check (no documented, buildable rule to
implement — §5.3/§5.4/§8.2/§8.3).
