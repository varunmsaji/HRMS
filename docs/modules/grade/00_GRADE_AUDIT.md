# Grade Module — Pre-Implementation Audit

Status: **Audit only — no code changed.** Follows the same audit-then-build discipline used
for Legal Entity, Branch, Department, and Designation
(`docs/modules/designation/00_DESIGNATION_AUDIT.md`). This document inspects the current DB,
the completed Designation slice (the pattern to replicate), and all Grade references across
product docs, then states exactly what Grade needs, what's already there, and the required
Grade↔Designation relationship, before writing code.

---

## 1. Current state

**Grade has zero application code.** No ORM model, no repository/service/router methods, no
Pydantic schemas, no permission code, no frontend page, no dedicated test file. Confirmed by
a repo-wide search: no `apps/api/src/**` or `apps/web/src/**` file references "grade"
anywhere today (case-insensitive, whole-word).

The only things that exist today:

- A **DB-level stub table** `grade`, created in the original baseline schema
  (`apps/api/scripts/sql/001_init_schema.sql:187-197`) — present since the first migration,
  never touched since. Columns: `id, company_id, code (NOT NULL), name (NOT NULL), rank
  (nullable), created_at, updated_at, deleted_at`. No `level` (the DB stub uses `rank`
  instead — a naming mismatch with the spec, see §2.3), no `min_ctc`/`max_ctc`, no
  `notice_period_days`/`probation_days`, no `approval_limit`, no `is_active`, no `version`.
- A **unique constraint already present**: `grade_company_id_code_key UNIQUE (company_id,
  code)` (line 347) — this is the **only** organisation-module table audited so far that
  already ships a DB-level uniqueness constraint on `code`. Unlike Department/Designation
  (where "no uniqueness documented, none invented" applied because no constraint existed
  either), here a real constraint already exists in the baseline schema and must be
  preserved, not silently dropped.
- FK constraint: `grade_company_id_fkey → company(id) ON DELETE RESTRICT` (line 425).
- Indexes: the unique index above serves as the lookup index; no separate `grade_company_id_idx`
  exists (unlike every other organisation table, which has a plain non-unique index — here
  the unique index covers the same access pattern).
- Referenced by (bare columns, no FK constraints declared): `employee_assignment.grade_id`
  (line 265), and by name only in Recruitment-module tables (`requisition.grade_id` — wait,
  not present; `offer.grade_id`) and `salary_structure.applicable_grade_ids UUID[]` — all
  Employee/Recruitment/Payroll tables, themselves out of scope this slice.
- **`designation.grade_id` does not exist yet** — confirmed by re-reading the live
  `Designation` ORM model shipped in the previous slice
  (`apps/api/src/hrms/modules/organisation/models.py::Designation`): it has no `grade_id`
  field. This was a **deliberate, explicitly-flagged exclusion** in
  `docs/modules/designation/00_DESIGNATION_AUDIT.md` §5.7 — Grade was out of scope for that
  task, so the FK to it was excluded entirely (not added as a passive/inert column, unlike
  `next_designation_id`). §3 below determines whether this task now adds it.
- **RLS**: `grade` is included in the generic tenant-isolation loop embedded directly in
  `001_init_schema.sql:467-483` (alongside `designation`, `department`, etc.) but is **not**
  independently named in the standalone `apps/api/scripts/sql/002_row_level_security.sql`
  (that file names `'user_company', 'role', 'legal_entity', 'branch', 'department',
  'designation', 'grade'` — actually it *is* named there too, at line 18, identical list to
  the one Designation's own audit found). **Same caveat carried over from all four prior
  audits, verbatim**: neither file is the live RLS registry for any environment where the
  table predates an edit to them — every prior slice's own migration re-asserted RLS
  idempotently regardless of this nominal coverage. §4 below carries this forward as
  required, not optional, for Grade too.
- **Frontend**: no Grade screen exists.
- **Documentation**: no `docs/modules/grade/` directory existed before this audit. Grade is
  discussed only inside broader docs (SRS FR-ORG-007/FR-ORG-014, PRD BR-14, Database
  Architecture §4, RBAC matrix, API Standards' endpoint table, and the Sprint 3 plan's
  Feature 3.3 Task 3.3.1 — plus a later self-correction to that same task in Feature 4.3's
  own text, §2.4 below).

**The good news**: the Designation slice, which just shipped, is a complete, current
reference implementation of the exact pattern Grade must follow — same module
(`organisation`), same layering, same conventions (soft deactivation, optimistic
concurrency, audit events, `company_id` ownership validation). It is the primary source for
"how" in this audit. The Sprint 3 plan and Database Architecture doc are the primary sources
for "what."

---

## 2. Database state

### 2.1 What exists today

`grade` table (`apps/api/scripts/sql/001_init_schema.sql:187-197`):

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | PK, `gen_random_uuid()` default |
| `company_id` | UUID NOT NULL | FK'd (`grade_company_id_fkey → company(id) ON DELETE RESTRICT ON UPDATE CASCADE`, line 425) |
| `code` | VARCHAR(30) NOT NULL | **already unique per company** (`grade_company_id_code_key`, line 347) |
| `name` | VARCHAR(100) NOT NULL | |
| `rank` | INTEGER (nullable) | **naming mismatch with spec's `level`**, see §2.3 |
| `created_at` / `updated_at` | TIMESTAMPTZ NOT NULL | |
| `deleted_at` | TIMESTAMPTZ | reserved, unused |

### 2.2 What the spec requires

`docs/product/08_Database_Architecture.md:183` (§4, Organisation Master):

```
grade | id, company_id, code, name, level INT, min_ctc, max_ctc, notice_period_days, probation_days, leave_policy_id, approval_limit
```

`docs/product/17_SRS_Phase1_Core_Modules.md:98` (FR-ORG-007): "Grade/Band: code, level,
min/max CTC, leave entitlement override, notice period override, probation override,
approval-limit override." (M priority)

`docs/product/02_PRD.md:213` (BR-14): "Notice period, probation period, leave entitlement and
shift default at Company level, are overridable at Branch → Department → Grade → Employee
level; the most specific setting wins." — confirms Grade's override fields
(`notice_period_days`, `probation_days`) are part of a documented company-wide override
chain, not invented; `leave_policy_id`/leave entitlement is the "leave entitlement override"
named in the same chain.

`docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md` Feature 3.3, Task 3.3.1 (line 490) elaborates:

- **Objective**: "Expand the existing `grade` stub (`id, company_id, code, name, rank`) to
  the full `docs/product/08` §4 shape. **Built before Designation** since Designation FKs to
  it (per D2)." — this is the task-order confirmation: Designation was built *before* Grade
  in this actual implementation sequence (the reverse of the Sprint plan's own intended
  order), which is exactly why `designation.grade_id` doesn't exist yet and is this audit's
  central open item (§3).
- **Backend Work**: Migration adding `level INTEGER` — "rename/repurpose `rank` → `level` if
  semantically identical, or add `level` alongside and deprecate `rank` — implementer's
  call; **prefer a clean rename via `op.alter_column` since `rank` has no real data yet**."
  Also `min_ctc BIGINT NULL` (minor units per ADR-0006, nullable since grade can exist before
  compensation bands are decided), `max_ctc BIGINT NULL`, `notice_period_days INTEGER NULL`,
  `probation_days INTEGER NULL`, `leave_policy_id UUID NULL` (FK — see §2.4, ultimately
  **not** added), `approval_limit BIGINT NULL` (minor units), `is_active BOOLEAN DEFAULT
  true`, `version INTEGER DEFAULT 1`. `organisation/models.py::Grade`. Full CRUD.
  `permissions.py::ORG_GRADE_MANAGE`.
- **API Work**: `GET/POST /v1/grades`, `GET/PATCH/DELETE /v1/grades/{id}` — matches
  `docs/product/09_API_Standards.md:246` exactly, no ambiguity.
- **Testing Requirements**: "Unit: `min_ctc <= max_ctc` validated at the service layer when
  both present." — **this is a documented, buildable business rule**, not an invented one
  (§6.4). "Integration: full CRUD."

### 2.3 `rank` → `level` rename

The DB stub's `rank` column (nullable INTEGER) is semantically the same field the spec calls
`level` (also nullable INTEGER — grade can exist before its ordering is decided). The Sprint
plan itself recommends a clean rename via `op.alter_column`, noting `rank` has no real data
yet (confirmed: zero application code has ever written to this column). This audit adopts
that recommendation — `level` is the column name going forward; `rank` does not survive as a
separate/duplicate column.

### 2.4 `leave_policy_id` — documented, then explicitly un-documented

Task 3.3.1 initially names `leave_policy_id UUID NULL` as a deferred FK, "added as a
follow-up in Feature 4.3 once `leave_policy` exists." However, Feature 4.3's own text (Task
"4.3.3 — Leave Policy Assignment", `docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md:655,660`)
**explicitly overrides this**: "re-evaluate at implementation time whether
`grade.leave_policy_id` (single) or `leave_policy_assignment` (flexible, multi-scope) is the
actual assignment mechanism; **decision: use `leave_policy_assignment` as the real
mechanism**... and treat `grade.leave_policy_id` from the source table spec as **not
implemented** — drop it from Task 3.3.1's deferred-FK list." The doc's own acceptance
criteria for that later task states this must be "reflected as a correction note against Task
3.3.1's original deferred-column list, not silently diverge from it" — which is exactly what
this audit is doing here, explicitly, rather than silently.

**Consequence**: `grade.leave_policy_id` is not added, now or as a deferred/passive column —
the doc that would have justified adding it later has already retracted that plan in favor of
a different mechanism (`leave_policy_assignment`), which itself is out of scope this slice
(Leave is explicitly excluded from this task). FR-ORG-007's "leave entitlement override" and
BR-14's leave-entitlement link in the override chain are therefore **not implemented** this
slice — flagged as a known limitation (§9), not invented around.

### 2.5 Gap: existing column vs. target

| Column | Status |
|---|---|
| `id`, `company_id`, `code`, `name` | ✅ present, keep as-is |
| `rank` | ⚠️ renamed to `level` this slice, per §2.3 |
| `min_ctc`, `max_ctc`, `notice_period_days`, `probation_days`, `approval_limit` | ❌ missing — added this slice |
| `is_active`, `version` | ❌ missing — needed for the same soft-deactivate + optimistic-concurrency pattern every other organisation-module resource uses |
| `leave_policy_id` | ❌ **not added** — see §2.4, doc's own retraction |

---

## 3. Relationship with Designation — the central question this audit must answer

This task's Phase 3 poses four options. The documentation answers unambiguously:

**Option B — Designation references Grade — is correct.**

Evidence, independently converging from three separate documents:

1. `docs/product/08_Database_Architecture.md:182` — `designation` table's own column list:
   `id, company_id, code, title, grade_id, department_id NULL, jd_document_id,
   next_designation_id`. `grade_id` is a `designation` column, not the other way around.
2. `docs/product/17_SRS_Phase1_Core_Modules.md:97` (FR-ORG-006) — "Designation: title,
   grade/band, department (optional)..." — grade/band is named as one of *Designation's own*
   fields.
3. `docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md` D2 (Scope Decision, line 18): "**Grade is
   built alongside Designation, not deferred**... `docs/product/17` FR-ORG-006/007 makes
   Designation reference `grade_id`, and the existing `designation`/`grade` stub tables are
   already FK-linked in the current schema." — explicit, unambiguous: Designation → Grade.
4. Task 3.3.2 (Designation backend) independently confirms: "Migration adding: `code
   VARCHAR(30)`, `grade_id UUID NULL` (FK to `grade`)..."

No document supports option A (Grade referencing Designation), and no document supports
option C (Grade and Designation as fully independent, connected only through Employee
Assignment) — `employee_assignment.grade_id` and `employee_assignment.designation_id` both
exist as **separate, independent** bare columns at the DB level (line 265), which is a
distinct relationship (Employee Assignment references both entities directly, for the
time-versioned "current position" per ADR-0003) — it does **not** substitute for or
contradict `designation.grade_id`, which is a structural master-data relationship (a
Designation's *own* grade/band, independent of any specific employee's assignment).

**Consequence for this task**: `designation.grade_id` is a documented requirement that was
correctly identified and deliberately excluded by the *previous* slice only because this
task's own explicit boundary at the time forbade implementing Grade
(`docs/modules/designation/00_DESIGNATION_AUDIT.md` §5.7 — "Excluding it entirely, rather
than inventing a new passive-column precedent... is the more conservative, doc-following
choice" — a decision scoped to *that* task, not a permanent architectural stance). Now that
Grade is being built, per this task's own Phase 3 instructions ("If the correct architecture
requires adding `grade_id` to Designation, explicitly identify this before implementation" —
identified above — "If a migration is required to connect the two modules, document the
reason" — done here), **this slice adds `designation.grade_id` as a nullable FK, exposed in
the Designation schemas/service/UI**, completing the documented relationship. This is not
scope creep into Employee/Recruitment/Payroll — it is completing Designation's own
already-documented field set (FR-ORG-006 lists grade/band as one of Designation's fields,
same status as `title`/`department_id`), which could not be finished until Grade existed.

**What is explicitly NOT changed**: Designation's own hierarchy/deactivation/audit logic is
untouched; only `grade_id` is added as one more optional, ownership-validated field,
following the exact same pattern as `department_id` was added to Designation in the previous
slice (`422 INVALID_GRADE` mirroring `422 INVALID_DEPARTMENT`).

---

## 4. Required data model

### 4.1 ORM model — `organisation/models.py::Grade`

Same file as `LegalEntity`/`Branch`/`Department`/`Designation`.

```python
class Grade(Base, TimestampMixin):
    __tablename__ = "grade"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(100))
    level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_ctc: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    max_ctc: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    notice_period_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    probation_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approval_limit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
```

`leave_policy_id` intentionally absent per §2.4. `min_ctc`/`max_ctc`/`approval_limit` are
`BIGINT` minor units per ADR-0006, with no per-row `currency` column — Company already owns a
single `currency` field (`hrms.core.db.models.identity.Company.currency`, locked after trial
via the existing `CurrencyLockedError`), and no document specifies a per-Grade currency
override; adding one would be inventing a column ADR-0006's general guidance doesn't force
onto every money column when a documented single-currency-per-company model already exists.

### 4.2 Migration

New file, e.g. `apps/api/alembic/versions/20260813160000_grade_fields.py`
(`down_revision = "20260813150000"`, chained after the Designation migration — current head).

```sql
ALTER TABLE grade RENAME COLUMN rank TO level;

ALTER TABLE grade
  ADD COLUMN IF NOT EXISTS min_ctc BIGINT,
  ADD COLUMN IF NOT EXISTS max_ctc BIGINT,
  ADD COLUMN IF NOT EXISTS notice_period_days INTEGER,
  ADD COLUMN IF NOT EXISTS probation_days INTEGER,
  ADD COLUMN IF NOT EXISTS approval_limit BIGINT,
  ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;

CREATE INDEX IF NOT EXISTS grade_company_active_idx
  ON grade (company_id, is_active) WHERE deleted_at IS NULL;

-- Connects Designation to Grade per §3 — documented in FR-ORG-006/Database Architecture,
-- deliberately deferred by the previous (Designation) slice only because Grade did not
-- exist yet.
ALTER TABLE designation ADD COLUMN IF NOT EXISTS grade_id UUID;
ALTER TABLE designation
  ADD CONSTRAINT designation_grade_id_fkey
    FOREIGN KEY (grade_id) REFERENCES grade(id) ON DELETE SET NULL ON UPDATE CASCADE;
CREATE INDEX IF NOT EXISTS designation_grade_id_idx ON designation (grade_id);

-- Re-assert RLS idempotently — see §2.1/§1 caveat, carried from every prior audit.
ALTER TABLE grade ENABLE ROW LEVEL SECURITY;
ALTER TABLE grade FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON grade;
CREATE POLICY tenant_isolation ON grade
  USING (company_id = current_setting('app.company_id', true)::uuid);
```

The existing `grade_company_id_code_key UNIQUE (company_id, code)` constraint (§2.1) is left
untouched — it already enforces exactly the uniqueness the spec would otherwise have left
undocumented, so it is preserved, not dropped and not newly invented.

### 4.3 Schemas (`organisation/schemas.py`)

Add `GradeCreate`, `GradeUpdate`, `GradeRead`, `grade_to_read`, `grade_to_audit_dict`,
`build_grade_update_values` — same shape as the `Designation*` quintet, plus the additional
override/compensation fields.

- `code: str` — **required** (unlike Department/Designation's optional `code` — Grade's
  `code` is `NOT NULL` at the DB level today and already uniquely constrained; this is a
  genuine difference from the other three modules, not an inconsistency to fix).
- `name: str` — required, mirrors every other module's required "name"-shaped field.
- `level: int | None`, `min_ctc: int | None`, `max_ctc: int | None`,
  `notice_period_days: int | None`, `probation_days: int | None`, `approval_limit: int |
  None` — all optional, matching the DB's own nullability.
- `is_active` server-controlled on create, client-settable via PATCH only — same rule as
  every other organisation-module resource.

`DesignationCreate`/`DesignationUpdate`/`DesignationRead` gain one additional optional field,
`grade_id: UUID | None`, per §3.

---

## 5. API requirements

Per this task's own explicit instructions, matching `docs/product/09_API_Standards.md:246`
exactly:

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/v1/grades` | `ORG.GRADE.MANAGE` | List, company-scoped, unfiltered (same low-cardinality assumption every prior organisation list endpoint made) |
| POST | `/v1/grades` | `ORG.GRADE.MANAGE` | Create; `is_active` always `true` |
| GET | `/v1/grades/{grade_id}` | `ORG.GRADE.MANAGE` | 404 (never 403) cross-tenant or not-found |
| PATCH | `/v1/grades/{grade_id}` | `ORG.GRADE.MANAGE` | `If-Match: <version>`; partial update |
| DELETE | `/v1/grades/{grade_id}` | `ORG.GRADE.MANAGE` | Soft deactivation only; `If-Match`; `200 DataEnvelope<GradeRead>`, not `204` (same shipped-convention override every prior slice's audit already made once) |

---

## 6. Business rules

### 6.1 Company ownership

Identical mechanism to every other organisation-module resource — `company_id` filtering,
belt-and-suspenders in the repository, RLS as backstop.

### 6.2 Code uniqueness — already enforced, not invented

`grade_company_id_code_key UNIQUE (company_id, code)` already exists at the DB level (§2.1).
This is the **first** organisation-module resource in this series where a real uniqueness
constraint predates this slice. It is preserved as-is; the service layer surfaces the
resulting `IntegrityError` as a documented `409`/`422` (mirroring how every other module in
this codebase converts a unique-constraint violation into an `AppError`, not a raw 500 — see
`hrms.core.errors` conventions used elsewhere) rather than inventing a *pre-check* that could
race. No *new* uniqueness is invented for `name`, `level`, or any other field.

### 6.3 Active/inactive lifecycle

**No documented deactivation-blocking rule.** FR-ORG-014's literal text blocks deactivation
of an org unit "only if no active employee is assigned" — Employee doesn't exist, so this
can't be checked, identical to every prior module. No document names Designation as a
blocker on Grade deactivation (the reverse direction — Grade referenced by an active
Designation — is not named anywhere, unlike, say, Task 3.3.2's own `next_designation_id`
self-reference rule for Designation). **This slice ships Grade deactivation/reactivation with
no active-dependency check**, consistent with Department's and Designation's own resolution.

### 6.4 `min_ctc <= max_ctc` — documented, implemented

Task 3.3.1's own Testing Requirements explicitly name this: "Unit: `min_ctc <= max_ctc`
validated at the service layer when both present." This is the **first genuinely-documented,
buildable field-level business rule** encountered in this series beyond ownership/hierarchy
checks — implemented as a service-layer validation (`422 INVALID_CTC_RANGE` or equivalent)
when both `min_ctc` and `max_ctc` are provided and `min_ctc > max_ctc`. Not required when
either is absent (both are nullable).

### 6.5 Optimistic concurrency

`version` + `If-Match`, identical mechanism to every other organisation-module resource.

### 6.6 No invented rules

Per this task's own explicit instructions, the following are **not** implemented, because no
document specifies them: hierarchy/ordering enforcement beyond the plain `level` integer
(no min/max level range, no gap rules), salary-calculation rules, employee-dependency
deactivation blocking, payroll behavior of any kind, and `leave_policy_id`/leave-entitlement
override (§2.4).

### 6.7 Designation's `grade_id` — mirrors `department_id`'s own validation

`grade_id`, when provided on `DesignationCreate`/`DesignationUpdate`, must reference a Grade
belonging to the same tenant (`422 INVALID_GRADE`, same shape/posture as the existing `422
INVALID_DEPARTMENT`). No hierarchy/cycle logic applies (Grade has no self-reference).

---

## 7. Permission requirements

Single permission, matching the Company/Legal Entity/Branch/Department/Designation precedent
exactly:

```python
ORG_GRADE_MANAGE = "ORG.GRADE.MANAGE"
```

Add to `ORGANISATION_PERMISSIONS` and grant it to the `COMPANY_ADMIN` system role at
registration time in `OrganisationService.register_company`, the same
`get_or_create_permission` → `insert_role_permission` pattern used for every prior
organisation-module permission. `docs/product/19_RBAC_and_Permission_Matrix.md:100` already
names this exact code (`.GRADE.MANAGE`) with no naming conflict — no RBAC doc edit needed.

Designation's own `PATCH`/`POST` continues to require only `ORG.DESIGNATION.MANAGE` for
setting `grade_id` — same posture as `department_id` requiring only `ORG.DESIGNATION.MANAGE`,
not an additional cross-resource permission, mirroring how Department's own `branch_id` field
required only `ORG.DEPARTMENT.MANAGE`, not `ORG.BRANCH.MANAGE`, to set.

---

## 8. Tenant / RLS / audit requirements

Identical mechanism to every other organisation-module resource — `TenancyMiddleware` +
`get_tenant_context`, belt-and-suspenders `company_id` filtering in every repository method,
RLS re-asserted idempotently in the migration (§4.2). Cross-tenant access, including a guessed
`grade_id` or a cross-tenant `grade_id` referenced from Designation, must return `404`/`422`
as appropriate, never leak.

Audit events via the existing `AuditService`, mirroring Designation's four: `GRADE_CREATED`,
`GRADE_UPDATED`, `GRADE_DEACTIVATED`, `GRADE_REACTIVATED`, `entity_type = "grade"`,
before/after `GradeRead` snapshots. No `RESTRICTED`-classified fields — `min_ctc`/`max_ctc`
are compensation *bands* (a grade-level policy value, not an individual's salary), which is
the class of data FR-ORG-007 already documents as visible to whoever manages Grade; not
equivalent to an individual employee's actual compensation (which does not exist yet,
Employee being out of scope).

`designation_id` audit records gain `grade_id` in their before/after `DesignationRead`
snapshots automatically, once the field is added to that schema — no separate audit event
type needed for that change; it flows through the existing `DESIGNATION_UPDATED` action.

---

## 9. Known limitations (flagged now, not silently discovered later)

1. **No `leave_policy_id`** — the Sprint doc's own later self-correction (§2.4) retracts this
   column in favor of `leave_policy_assignment`, itself out of scope (Leave excluded this
   task). FR-ORG-007's "leave entitlement override" and BR-14's leave-entitlement link in the
   override chain are not implemented.
2. **No deactivation-blocking rule** (§6.3) — a Grade referenced by an active Designation (or,
   once it exists, an active Employee) can still be deactivated freely this slice.
3. **No per-Grade `currency` column** (§4.1) — money fields are assumed to be in the owning
   Company's single configured currency.
4. **No query-param filtering** on `GET /grades` — consistent with every prior
   organisation-module list endpoint.

---

## 10. Decisions required from you

1. **`designation.grade_id`** (§3): the documentation is unambiguous (Option B). This audit's
   recommendation is to implement it as part of this slice, since Designation's own
   FR-ORG-006 field set already names grade/band as one of its fields and the only reason it
   was missing was Grade's own prior nonexistence. **Recommendation: implement.**
2. **`rank` → `level` rename** (§2.3): the Sprint plan's own recommendation, and the column
   has no real data. **Recommendation: rename via `op.alter_column`, not a parallel column.**
3. **`leave_policy_id`** (§2.4): the source doc explicitly retracts this column in a later
   section of the same Sprint plan. **Recommendation: do not add it, not even as a passive
   column** — the doc itself calls the entire single-FK model superseded, not merely
   deferred.
4. **`min_ctc <= max_ctc` validation** (§6.4): explicitly named in the Sprint plan's own
   Testing Requirements for this exact task. **Recommendation: implement as a service-layer
   check.**
5. **Preserve existing `UNIQUE (company_id, code)`** (§6.2): a real constraint predates this
   slice. **Recommendation: keep it, surface violations as a documented `AppError`.**

---

## 11. Explicit out-of-scope items

Per this task's instructions and this audit's findings, **not** part of this slice:
`leave_policy_id`/leave-entitlement override, any employee-dependency deactivation-blocking
check, per-Grade currency, query-param filtering on `GET /grades`, Employee, Employee
Assignment, Attendance, Shift Rules, Leave, Payroll, Recruitment, ESS, Performance, Workflow
automation. `designation.grade_id` is **in scope** per §3's finding — it completes
Designation's own already-documented field set, not a new module.
