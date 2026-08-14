# Employee Assignment (E-04) — Implementation Plan

Investigation-and-plan document for the vertical slice named `01_EMPLOYEE_MODULE_PLAN.md` §"E-04 —
Employee assignment (org placement + reporting line)". Written per this task's own instruction:
investigate only, no application code or migrations in this task. Every claim below traces to an
authoritative document, the live database, or the live codebase — nothing here invents a
requirement absent from those sources.

**Verdict up front: no blocking product decision exists for E-04.** `00_EMPLOYEE_AUDIT.md` and
`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` already resolved every product-level question E-04 depends
on (Part B3 specifically decides Employee Assignment's shape) before this task started. What
remains are ordinary engineering decisions, made explicit below (§14) so they're reviewable, not
silently assumed. Per Phase 7 of this task's brief, this is therefore the implementation-plan
document, not a decision-gate document.

---

## 1. Scope

**In scope for E-04** (`01_EMPLOYEE_MODULE_PLAN.md` §"E-04", `00_EMPLOYEE_AUDIT.md` §16 row E-04):

- `EmployeeAssignment` ORM model + migration extending the live `employee_assignment` stub table.
- The as-of-date read helper (`get_assignment_as_of`) as a shared service method — the pattern
  Attendance/Leave/Payroll will later import.
- Insert-only effective-dated write path: initial placement, transfer (branch/department/manager
  change), promotion (designation/grade change) — each an insert of a new row, never a column
  update, per ADR-0003.
- FK constraints on the five currently-unconstrained columns (`department_id`, `designation_id`,
  `grade_id`, `reporting_manager_id`, `branch_id`).
- New columns documented but missing from the live table: `dotted_line_manager_id`,
  `cost_centre_id`, `work_location_type`, `change_reason`, `change_type`.
- `EMPLOYEE.TRANSFER` / `EMPLOYEE.PROMOTE` permissions (already named in the locked catalogue,
  `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part B9 — not yet seeded in code).
- `ASSIGNMENT_CHANGED` audit event.

**Explicitly NOT in scope for E-04** (confirmed against `00_EMPLOYEE_AUDIT.md` Appendix and
`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part G):

- `shift_id` — a separate migration/slice, E-05, "kept separate so Shift's own dependency is
  explicit and reviewable on its own" (`01_EMPLOYEE_MODULE_PLAN.md` §"E-04").
- The BR-14/FR-EMP-018 shift-and-notice-period override-chain cascading-resolution mechanism
  (Part A3/B8/G1) — a separate, later, cross-module decision.
- Compensation, Statutory, Banking (E-06/E-07/E-08).
- Attendance, Leave, Payroll, ATS/Recruitment, Workflow automation (all out of Employee's
  aggregate entirely).
- Inter-entity transfer's employment-closing mechanics (FR-EMP-011's "closes one employment and
  opens another, carrying leave balance... and handling PF transfer/settlement") — this is an
  `Employment`-level operation (a new `employment` row, per Part C's "legal entity change... is
  modelled as a *new* `employment` row, not a mutation"), and its leave/PF legs depend on modules
  that don't exist yet. E-04 ships intra-entity transfer only (branch/department/manager/
  designation/grade changes within the current employment episode); inter-entity transfer is
  flagged as a known limitation (§18), not built here.
- Promotion letters (FR-EMP-012's "generating a promotion letter") — E-09.
- Approval-routing / reassignment of pending approvals on manager change (FR-EMP-013) — the
  approval-routing engine doesn't exist yet; store the fact of a manager change, do not attempt to
  reassign approvals (mirrors Part G item 8's treatment of `approval_request_id`).
- Org chart visualization screen — frontend, deferred to its own task alongside/after E-09.

---

## 2. What already exists (verified against the live dev database and live code)

### 2.1 Database — `employee_assignment` (`\d employee_assignment`, verified 2026-08-14)

```
id                    uuid            PK
company_id            uuid            NOT NULL
employee_id           uuid            NOT NULL   FK -> employee.id ON UPDATE CASCADE ON DELETE RESTRICT
department_id         uuid            nullable, NO FK
designation_id        uuid            nullable, NO FK
grade_id              uuid            nullable, NO FK
reporting_manager_id  uuid            nullable, NO FK
branch_id             uuid            nullable, NO FK
effective_from        date            NOT NULL
effective_to          date            nullable
created_at            timestamptz     NOT NULL
updated_at            timestamptz     NOT NULL
deleted_at            timestamptz     nullable
version               integer         NOT NULL DEFAULT 1
```

- Indexes: `employee_assignment_pkey`, `employee_assignment_company_id_idx`,
  `employee_assignment_employee_id_effective_from_idx (employee_id, effective_from)`.
- **GiST exclusion constraint** `employee_assignment_no_overlap` on
  `(employee_id WITH =, daterange(effective_from, COALESCE(effective_to,'infinity'),'[]') WITH &&)`
  — already live, already makes two overlapping "current" rows for one employee structurally
  impossible.
- RLS: `tenant_isolation` policy, forced.
- **Confirmed gap**: only `employee_id` has a DB-level FK. `department_id`, `designation_id`,
  `grade_id`, `reporting_manager_id`, `branch_id` are plain nullable UUID columns — exactly the
  five relationship columns this task flagged for special attention. This is not new information;
  `00_EMPLOYEE_AUDIT.md §3.3`/§5 row 8 identified this in the pre-implementation audit and it has
  not been touched since (no migration references `employee_assignment` except the original
  `001_init_schema.sql`; confirmed via `grep -rl employee_assignment apps/api/alembic/versions/`
  returning only `20260814090000_employment_lifecycle.py`, which does not modify this table).
- **Confirmed gap**: `dotted_line_manager_id`, `shift_id`, `cost_centre_id`, `work_location_type`,
  `change_reason`, `change_type` — none exist on the live table.
- Row count: **0** — table is empty in the dev database, same as `employee`/`employment`. Every
  change below is additive/safe with no data migration needed (same situation E-03 confirmed and
  relied on for its own migration).

### 2.2 Code — `apps/api/src/hrms/modules/employee/`

- `models.py` docstring states explicitly: *"`EmployeeAssignment`/`EmployeeCompensation` still
  belong to later slices (E-04/E-06...) and are not mapped here."* Confirmed — no
  `EmployeeAssignment` class exists (`grep -n "class EmployeeAssignment"` → no results).
- `Employee` (E-01) and `Employment` (E-03) models, repositories, services, router, exceptions,
  and permissions are complete and tested (383/383 backend tests per prior verification).
- `permissions.py` has 5 codes seeded: `EMPLOYEE.VIEW` (identity module), `.VIEW_ALL`, `.CREATE`,
  `.UPDATE`, `.DEACTIVATE`, `.TERMINATE`. **`.TRANSFER`/`.PROMOTE` are not yet seeded anywhere** —
  confirmed by reading the file in full; the module docstring itself says these "belong to later
  slices (E-02/E-04/E-06/...)".
- `EmploymentRepository`/`EmploymentService` already establish the exact patterns E-04 must
  replicate: `get_employment_as_of(employee_id, as_of)` (repository.py:152-167) is the working
  precedent for `get_assignment_as_of`; `StaleResourceError`/`update_employment`'s
  `WHERE version == expected_version ... RETURNING` is the precedent for assignment's optimistic
  concurrency; `IntegrityError` → domain-specific `*DatesOverlapError` translation
  (service.py:294-315) is the precedent for the GiST exclusion constraint's friendly-error
  backstop.
- Module is its own package (`modules/employee/`, confirmed distinct from `organisation/`, per the
  already-locked decision A8) — E-04 continues inside this same package, no new package boundary
  question.
- `organisation` module (Branch/Department/Grade/Designation) verified read: `Branch.legal_entity_id`
  (NOT NULL), `Department.branch_id` (nullable), `Designation.department_id`/`.grade_id` (both
  nullable). **The organisation module itself does not enforce cross-entity consistency** (e.g. a
  Department is not required to belong to a specific Branch's legal entity chain in any DB
  constraint) — relevant to §14's validation-scope decision below.

---

## 3. The business role of Employee Assignment

Per `docs/product/02_PRD.md §11` (quoted in `00_EMPLOYEE_AUDIT.md §6`) and locked in
`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part B3/C:

> **Assignment**: "The current position: department, designation, grade, reporting manager,
> location, shift. **Time-versioned.**"

Assignment answers one question, as of any date: *"Where in the org does this employee sit, under
whom, and where do they physically/notionally work?"* It is the effective-dated child table that
makes the brief's own worked example correct (2027: Department A / Grade 2; 2028: Department B /
Grade 3 — two rows, not one mutated row).

### 3.1 Relationship chain

```
Employee (permanent identity)
 └── Employment[]            1:N — which Legal Entity, which continuous spell
 └── Employee Assignment[]   1:N — keyed on employee_id directly, NOT employment_id
       ├── branch_id             -> Branch            (required at first placement)
       ├── department_id         -> Department         (required at first placement)
       ├── designation_id        -> Designation         (required at first placement)
       ├── grade_id               -> Grade               (optional)
       ├── reporting_manager_id   -> Employee (self-ref) (optional — nullable for CEO-level)
       ├── dotted_line_manager_id -> Employee (self-ref) (optional, new in E-04)
       ├── cost_centre_id         (opaque UUID column, no referenced table exists yet — new in E-04)
       ├── work_location_type     (OFFICE/WFH/HYBRID/FIELD enum string, new in E-04)
       └── shift_id               -> Shift               (NOT added in E-04 — ships in E-05)
```

**Not every relationship is mandatory.** Per `02_EMPLOYEE_DATA_MODEL.md §2` section D (the
field-by-field inventory), only `branch_id`/`department_id`/`designation_id` are "required (at
creation)"; `grade_id`, `reporting_manager_id`, `dotted_line_manager_id`, `cost_centre_id`,
`work_location_type` are all optional. `reporting_manager_id` is explicitly nullable "for CEO"
(FR-EMP-002) — the org's top of the reporting tree has no manager.

### 3.2 Employee vs. Employment as the parent

**Locked, not a decision this plan makes**: Assignment is keyed on `employee_id`, not
`employment_id` (`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part B3, reconfirmed by the live schema's
own FK — `employee_assignment.employee_id -> employee.id` is the only FK that already exists).
This is deliberate, not an oversight: assignment/compensation history spans the whole identity, not
one employment spell, which is what makes a rehire correct without special-case code (Part C: "This
is what makes the rehire scenario correct without any special-case code — these histories span the
whole identity, continuous across an employment gap in the data model").

**Multiple assignments can and do exist** — one row per period, `effective_from`/`effective_to`.
**Assignments cannot overlap** for the same employee — DB-enforced by the GiST exclusion
constraint already live. **There is at most one current assignment** per employee at any moment —
the same constraint guarantees this (`effective_to IS NULL` is unique per `employee_id` by
construction, since two `NULL`-`effective_to` rows would both extend to infinity and always
overlap).

**Historical assignments** are simply prior rows — `effective_to` set, `deleted_at` still `NULL`
(never soft-deleted, only closed) — queryable via `WHERE employee_id = :id ORDER BY
effective_from`.

---

## 4. Rehire compatibility

Answering this task's six explicit questions, all sourced from `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md`
Part C ("Employee Assignment" subsection) and Part D (the fully worked rehire timeline):

1. **Does a rehire require a new assignment?** Yes, in practice — an employee has zero open
   employment during the gap, so (per §14's validation rule below) no assignment can be open
   either. The rejoin's new `employment` row must be followed by a new `employee_assignment` row
   before the employee has any org placement again. Nothing forces this automatically; it's a
   separate `POST .../assignments` call, same as any other placement.
2. **Can an old assignment remain historical?** Yes — old rows are never deleted or mutated beyond
   their `effective_to` being closed at the original exit date. They remain permanently queryable.
3. **Should assignment history be linked only through `employee_id`?** Yes — locked (§3.2 above).
   This is what lets one query ("full assignment history for this employee") return rows from both
   before and after a multi-year gap without any rehire-specific logic.
4. **How does effective dating prevent overlap?** The GiST exclusion constraint is unconditional —
   it doesn't know or care about employment episodes, only about `employee_id` + date-range overlap.
   Since the pre-exit assignment row was closed at the original exit date and no assignment exists
   during the gap, the rehire's new row (opening at the new joining date, which is after the old
   `effective_to`) cannot overlap anything — success by construction, not by an extra check.
5. **What happens when an employee returns to the same department/branch?** Nothing is inferred or
   carried forward automatically — per `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part C: "nothing
   carries forward automatically — department/designation/grade must be re-specified at rehire,
   consistent with FR-EMP-002's creation-time requirements." Even an identical placement is a
   fresh, fully-specified row, not a reference back to the old one.
6. **What happens when they return to a different organisational structure?** No different
   handling — it's the same insert-a-fresh-row operation either way; "different structure" has no
   special code path because "same structure" doesn't either.

**Consequence for E-04's design**: the "first assignment for this employment episode" case (no
currently-open assignment row to close) is not actually a rehire-specific case — it is the same
code path as a brand-new employee's very first assignment. The service does not need to
distinguish "first ever assignment" from "first assignment of a new episode after a gap"; both are
simply "no current row exists yet, so insert without a preceding close." This symmetry is a design
simplification worth calling out (§5 below), not a new requirement.

---

## 5. Shift relationship

Per this task's explicit instruction not to build BR-14 and to determine the shift relationship
without touching Shift Rules:

- **Column**: `employee_assignment.shift_id` — no separate shift-assignment table
  (`02_EMPLOYEE_DATA_MODEL.md §2` section E: "No separate shift-assignment table — shift is one
  column on the same `employee_assignment` row"). Confirmed this is the only documented shape;
  nothing suggests a `shift_id` on `employment` or a standalone join table.
- **NOT added in E-04.** `01_EMPLOYEE_MODULE_PLAN.md` §"E-04" is explicit: "**Does not add
  `shift_id`** in this slice — that's E-05, kept separate so Shift's own dependency is explicit and
  reviewable on its own." E-04's migration must not touch `shift_id` or the `shift` table at all.
- **Mandatory/optional**: when it does ship (E-05), nullable — `02_EMPLOYEE_DATA_MODEL.md §2`
  section E: "no (§00 §7.2 — override chain unresolved)".
- **Effective-dated**: yes, same row as the rest of assignment — a shift change is
  `change_type = SHIFT_CHANGE` on a new assignment row (E-05 concern).
- **Inherited/overridden**: explicitly deferred (Part A3/B8) — no cascading default from
  company/branch/department/grade is built anywhere in this codebase yet. An employee with no
  `shift_id` simply has no shift; this is the confirmed, locked position, not an open question.
- Shift Rules module itself (`organisation/models.py` `Shift` class) is **not modified** by this
  investigation and should not be modified by E-04 — E-04 only prepares the FK target
  (`department_id`/`designation_id`/`grade_id`/`branch_id`/`reporting_manager_id` FKs) that already
  exists; `shift` is untouched until E-05 explicitly adds the column and its FK.

---

## 6. Database changes (E-04's migration)

One new migration, `apps/api/alembic/versions/<timestamp>_employee_assignment.py`, following the
exact `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` + `ADD CONSTRAINT` pattern E-03's migration and
`02_EMPLOYEE_DATA_MODEL.md §3` both already used/proposed:

```sql
ALTER TABLE employee_assignment
  ADD COLUMN IF NOT EXISTS dotted_line_manager_id UUID,
  ADD COLUMN IF NOT EXISTS cost_centre_id UUID,
  ADD COLUMN IF NOT EXISTS work_location_type VARCHAR(20),
  ADD COLUMN IF NOT EXISTS change_reason TEXT,
  ADD COLUMN IF NOT EXISTS change_type VARCHAR(30);

-- NOT shift_id — E-05's own migration, deliberately excluded here (§5)

ALTER TABLE employee_assignment
  ADD CONSTRAINT employee_assignment_department_id_fkey
    FOREIGN KEY (department_id) REFERENCES department(id) ON DELETE SET NULL,
  ADD CONSTRAINT employee_assignment_designation_id_fkey
    FOREIGN KEY (designation_id) REFERENCES designation(id) ON DELETE SET NULL,
  ADD CONSTRAINT employee_assignment_grade_id_fkey
    FOREIGN KEY (grade_id) REFERENCES grade(id) ON DELETE SET NULL,
  ADD CONSTRAINT employee_assignment_branch_id_fkey
    FOREIGN KEY (branch_id) REFERENCES branch(id) ON DELETE SET NULL,
  ADD CONSTRAINT employee_assignment_reporting_manager_id_fkey
    FOREIGN KEY (reporting_manager_id) REFERENCES employee(id) ON DELETE SET NULL,
  ADD CONSTRAINT employee_assignment_dotted_line_manager_id_fkey
    FOREIGN KEY (dotted_line_manager_id) REFERENCES employee(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS employee_assignment_current_idx
  ON employee_assignment (company_id, employee_id, effective_from DESC);
CREATE INDEX IF NOT EXISTS employee_assignment_manager_idx
  ON employee_assignment (company_id, reporting_manager_id) WHERE effective_to IS NULL;
```

Notes/deviations from `02_EMPLOYEE_DATA_MODEL.md §3`'s proposed DDL, with reasoning:

- **`ON DELETE SET NULL`, not `RESTRICT`**, for all five reference FKs — matches the data model
  doc's own proposal exactly and the organisation module's stated convention for optional
  references (`00_EMPLOYEE_AUDIT.md §5` row 8: "matching the organisation module's own convention
  for optional references"). Deactivating/deleting a Department must not be blocked by historical
  assignment rows pointing at it.
- **`reporting_manager_id`/`dotted_line_manager_id` reference `employee(id)`**, not `employment` —
  a manager is an identity, not a spell; this is a self-referential FK on the aggregate root,
  mirroring `Designation.next_designation_id`'s existing precedent for self-reference.
- **No `NOT NULL` added to `branch_id`/`department_id`/`designation_id`** at the DB layer, despite
  being "required at creation" per the data model doc. This is a deliberate engineering choice
  (§14.3) consistent with how `Employment`'s own required-at-creation fields
  (`legal_entity_id NOT NULL`) are still handled — but here, unlike Employment, a later transfer's
  POST body only carries *changed* fields (§7 below), so the column-level constraint cannot express
  "required only on the first row." Enforced instead in the Pydantic schema for the create case and
  in the service for the carry-forward case (§14.3).
- **`cost_centre_id` has no FK** — no `cost_centre` table exists anywhere in this codebase (only
  the audit's gap list names it as a documented-but-unbuilt column, `00_EMPLOYEE_AUDIT.md §3.3`).
  Kept as an opaque UUID exactly as documented; adding a FK to a table that doesn't exist isn't
  possible and isn't asked for.
- **`work_location_type`/`change_type`** are `VARCHAR`, not a Postgres enum type — matches the
  house rule "enums as lookup tables, not PG enum types" is not literally followed either
  (no lookup table for these two is documented) — instead validated at the Pydantic layer against a
  fixed literal set, the same treatment `employment.status` already received (a `CHECK` constraint
  string set, not a lookup table, not a PG enum). Flagged as consistent with `employment`'s own
  precedent, not a new pattern.
- **`employment_no_overlap`-style GiST constraint**: no change needed — `employee_assignment_no_overlap`
  already exists exactly as required.

RLS is already live and correct on this table (`FORCE ROW LEVEL SECURITY`, `tenant_isolation`
policy) — no change needed, only re-assert idempotently per house convention if the migration
touches the table at all (matches every prior migration's own habit).

---

## 7. ORM model

New `EmployeeAssignment` class in `apps/api/src/hrms/modules/employee/models.py`, alongside
`Employee`/`Employment`/`NumberSeries`:

```python
class EmployeeAssignment(Base, TimestampMixin):
    __tablename__ = "employee_assignment"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True)
    employee_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employee.id"), index=True)
    branch_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("branch.id"), nullable=True)
    department_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("department.id"), nullable=True)
    designation_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("designation.id"), nullable=True)
    grade_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("grade.id"), nullable=True)
    reporting_manager_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employee.id"), nullable=True)
    dotted_line_manager_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employee.id"), nullable=True)
    cost_centre_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    work_location_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    change_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    change_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
```

`shift_id` intentionally absent — E-05 adds it via its own migration + a one-line model addition,
not pre-declared here as a nullable placeholder (keeps E-04's model change reviewable against
exactly the columns its own migration adds).

---

## 8. Repository (`EmployeeAssignmentRepository`, new class in `repository.py`)

Mirrors `EmploymentRepository`'s shape exactly:

- `insert_assignment(session, *, data) -> EmployeeAssignment` — plain insert, same shape as
  `insert_employment`.
- `get_current_assignment(session, *, company_id, employee_id) -> EmployeeAssignment | None` —
  `WHERE employee_id = :id AND effective_to IS NULL` (at most one row, by the exclusion
  constraint). This is the row a transfer/promotion reads before closing it.
- `get_assignment_as_of(session, *, company_id, employee_id, as_of) -> EmployeeAssignment | None` —
  same shape as `get_employment_as_of` (repository.py:152-167), with the field name changed from
  `joining_date`/`last_working_day` to `effective_from`/`effective_to`. **This is the shared
  cross-module contract** (`get_assignment_as_of`) that Attendance/Leave/Payroll will later import
  via `employee.service`, per `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part B7/E.
- `list_assignments(session, *, company_id, employee_id) -> list[EmployeeAssignment]` — full
  history, `ORDER BY effective_from`.
- `close_assignment(session, *, company_id, employee_id, assignment_id, effective_to, expected_version, now) -> EmployeeAssignment | None` —
  the "one allowed edit" (`UPDATE ... SET effective_to = ...`), `WHERE version == expected_version`,
  `RETURNING`. Distinct from a generic `update_assignment` because **only `effective_to` is ever
  written this way** — no business column update path exists at all (ADR-0003: "never an edit of
  an existing one's core values"), so there is deliberately no `update_assignment(values=...)`
  method that could be misused to mutate a historical row's department/designation in place.
- `get_assignment(session, *, company_id, employee_id, assignment_id) -> EmployeeAssignment | None` —
  single row by id, for the `GET .../assignments/{id}` detail case if the API plan needs it (§9).

No `update_assignment(values=...)` general method — deliberate, matches §"no PATCH on an individual
assignment row" (§9 below).

---

## 9. Service (`EmployeeAssignmentService`, new class in `service.py`)

One method, `create_assignment` (transfer/promotion/manager-change/initial-placement are all the
same operation, distinguished only by `change_type` and which fields differ from the current row —
§4's symmetry point):

```
create_assignment(company_id, employee_id, body: AssignmentCreate, *, actor_user_id, ...) -> AssignmentRead
```

Steps:
1. `_assert_employee_exists` (mirrors `EmploymentService`'s own helper).
2. Resolve the covering employment episode: `EmploymentRepository.get_employment_as_of(employee_id,
   as_of=body.effective_from)`. If `None`, raise a new `NoActiveEmploymentError` (§14.1) — an
   assignment cannot be effective on a date the employee has no open employment episode.
3. Read the current assignment row (`get_current_assignment`). Two branches:
   - **No current row** (first assignment ever, or first assignment of a new episode after a
     rehire gap): every mandatory field (`branch_id`, `department_id`, `designation_id`) must be
     present in the request body — validated by the `AssignmentCreate` Pydantic schema requiring
     them when no current row exists (checked in the service, since the schema alone can't know
     whether a current row exists).
   - **Current row exists**: merge — any field omitted from the request body carries forward
     unchanged from the current row's value (§7 of `03_EMPLOYEE_API_PLAN.md`'s own documented
     behavior: "unchanged fields carry forward from the current row"). `effective_from` must be
     strictly after the current row's `effective_from`.
4. Validate each provided/carried-forward reference id exists, is not soft-deleted, and belongs to
   the same tenant — `branch_id` -> `organisation.service.get_branch`, `department_id` ->
   `get_department`, `designation_id` -> `get_designation`, `grade_id` -> `get_grade` (all via
   `organisation.service`'s public surface only, never `.repository`/`.models`, same cross-module
   rule `EmploymentService._assert_legal_entity_ownership` already follows). `reporting_manager_id`/
   `dotted_line_manager_id`, if provided, -> `EmployeeRepository.get_employee` (same module, no
   cross-import needed) — must exist, same tenant, not soft-deleted, and **must not equal
   `employee_id`** (no employee can be their own manager — a direct-self-reference guard, not full
   cycle detection; see §14.5).
5. If a current row exists: close it (`close_assignment`, `effective_to = body.effective_from -
   1 day`), inside the same transaction as the insert below.
6. Insert the new row (`insert_assignment`), wrapping in `try/except IntegrityError` to translate
   the GiST exclusion constraint's race-condition backstop into `AssignmentDatesOverlapError`
   (mirrors `EmploymentService.create_employment`'s exact pattern, service.py:294-315).
7. Audit: `action="ASSIGNMENT_CHANGED"`, `after` snapshot carries `change_type` — per
   `00_EMPLOYEE_AUDIT.md §13.4`'s own recommendation ("single event, `change_type` carried in the
   `after` snapshot rather than fragmented into six action strings").

Plus read methods: `list_assignments`, `get_assignment`, and the shared as-of-date helper exposed
publicly as `get_assignment_as_of(company_id, employee_id, as_of) -> AssignmentRead | None` — this
is the method other modules will call once Attendance/Leave/Payroll exist (not built now, but the
method's signature is what E-10 will finalize as the public contract per Part B7).

No `update_assignment`/`delete_assignment` service method — every change is `create_assignment`
with a new `change_type`; there is no other mutation path (§9 API plan confirms: "No `PATCH`/
`DELETE` on an individual assignment row").

---

## 10. API endpoints

Per `03_EMPLOYEE_API_PLAN.md §2.2`, already specified and not altered by this plan:

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/v1/employees/{employee_id}/assignments` | `EMPLOYEE.VIEW` | Full effective-dated history, or `?as_of=YYYY-MM-DD` for the single covering row |
| GET | `/v1/employees/{employee_id}/assignments/{assignment_id}` | `EMPLOYEE.VIEW` | Single row by id (engineering addition, mirrors `Employment`'s own single-item GET; not explicitly named in the API plan but consistent with its shape) |
| POST | `/v1/employees/{employee_id}/assignments` | `EMPLOYEE.TRANSFER` or `EMPLOYEE.PROMOTE` (selected by `change_type`, §14.2) | Closes the current row (if any), inserts a new row. Body: `effective_from`, `change_type`, `change_reason`, changed fields only |

No `PATCH`/`DELETE` — matches `03_EMPLOYEE_API_PLAN.md §2.2`'s explicit "No `PATCH`/`DELETE` on an
individual assignment row" rule exactly.

`DataEnvelope`/`ListEnvelope`, cross-tenant/not-found -> 404, `extra="forbid"` on the input schema —
all continuing the E-01/E-03 convention.

---

## 11. Permissions

Two new codes, both already named (not invented here) in the locked catalogue
(`00_EMPLOYEE_AUDIT.md §13.1`, `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part B9 table row
"Employee lifecycle management"):

```python
EMPLOYEE_TRANSFER = "EMPLOYEE.TRANSFER"
EMPLOYEE_PROMOTE = "EMPLOYEE.PROMOTE"
```

Added to `EMPLOYEE_PERMISSIONS` in `permissions.py`, granted to `COMPANY_ADMIN` automatically at
both bootstrap-seed and live-registration time (same dynamic-iteration mechanism E-01/E-03 already
rely on — no `seed/bootstrap.py` change needed, confirmed by reading how `EMPLOYEE.TERMINATE` was
picked up automatically in E-03's own closeout report).

**Which permission gates a given POST is decided by the request's `change_type`** (§14.2 — an
engineering decision, not a product one): `change_type = PROMOTION` requires `EMPLOYEE.PROMOTE`;
every other `change_type` (`INITIAL`, `TRANSFER`, `MANAGER_CHANGE`) requires `EMPLOYEE.TRANSFER`.

---

## 12. Audit events

One event, per `00_EMPLOYEE_AUDIT.md §13.4`'s own recommendation, not fragmented:

- `ASSIGNMENT_CHANGED` — `entity_type="employee_assignment"`, `entity_id=<new row's id>`, `before`
  = the closed row's snapshot (or `None` for the first-ever assignment), `after` = the new row's
  snapshot including `change_type`/`change_reason`.

No separate `sensitive_access_log` concern here — assignment fields (department, designation,
grade, manager) are `PUBLIC`/`INTERNAL` classification (`00_EMPLOYEE_AUDIT.md §13.3`), not
`RESTRICTED`; that concern belongs to Compensation/Statutory/Bank (E-06/E-07/E-08, per A9), not
E-04.

---

## 13. Effective-dating behavior

Fully specified already, not re-derived here — `02_EMPLOYEE_DATA_MODEL.md §1.1-1.3`, locked by
`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part B7:

- **Write**: read current row (if any) -> close it (`effective_to = new.effective_from - 1 day`,
  the only allowed edit, touching only `effective_to`) -> insert new row — same transaction.
- **Read "current"**: `WHERE employee_id = :id AND effective_to IS NULL`.
- **Read "as of date"**: `WHERE employee_id = :id AND effective_from <= :date AND (effective_to IS
  NULL OR effective_to >= :date)`.
- **Read "full history"**: `WHERE employee_id = :id ORDER BY effective_from`.
- **Future-dating**: permitted — a row with a future `effective_from` can be inserted now; no
  activation job is needed since the as-of-date read already returns the correct row for any date
  (`02_EMPLOYEE_DATA_MODEL.md §1.4`).
- **Backdating past a locked payroll period** (FR-EMP-004): **not enforceable** — Payroll doesn't
  exist yet. Flagged as a known limitation (§18), not silently skipped.

E-04 is the **first slice in this codebase to write application code against this pattern** — the
DB-level constraint already existed (E-03 also wrote to an effective-dated-shaped table,
`employment`, but via a spell-close/spell-open model on a table with its own distinct semantics,
not the canonical "insert, never update-in-place, business columns only in the new row" pattern
this plan follows exactly for the first time). Budget extra review time on the repository/service
split, per `00_EMPLOYEE_AUDIT.md §18`'s own flagged risk.

---

## 14. Validation rules and engineering decisions

Each classified per this task's Phase 6 instruction.

### 14.1 An assignment requires a covering employment episode — ENGINEERING DECISION (derived from a locked model, not invented)

**Rule**: `create_assignment` requires `EmploymentRepository.get_employment_as_of(employee_id,
as_of=effective_from)` to return a row; otherwise reject
(`NoActiveEmploymentError`/`422`).

**Why not a product decision**: `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part D's fully worked
timeline shows, as a directly stated consequence of the locked model, that assignment rows exist
*only* while an employment episode is open ("No `employee_assignment`... No open `employment` row"
during the gap; "Nothing to assign or pay during a gap, so nothing exists — this is expected, not a
data gap to fill"). This plan does not invent that behavior; it enforces it, since nothing else in
the schema (assignment has no `employment_id` FK — that's the whole point, §3.2) would otherwise
prevent an assignment existing during a gap by accident.

**Cannot be a DB constraint**: `employee_assignment` has no `employment_id` column (by design,
§3.2), so this cannot be expressed as a FK or a cross-table `CHECK`. It is enforced only in the
service layer — flagged explicitly so a future reviewer knows this integrity rule has no DB-level
backstop, unlike the no-overlap rule.

### 14.2 `change_type` enum and its permission mapping — ENGINEERING DECISION

No document enumerates literal `change_type` values. Proposed set, derived directly from the three
named workflows (FR-EMP-011/012/013) plus the "no current row" case:

```
INITIAL          — first assignment (new employee, or first assignment after a rehire gap)
TRANSFER         — branch/department/reporting_manager change without a designation/grade change
PROMOTION        — designation and/or grade change
MANAGER_CHANGE   — reporting_manager_id or dotted_line_manager_id change only
```

Caller-declared (the service does not infer `change_type` from which fields actually changed) —
matches how `Employment`'s `is_rehire`/`previous_employment_id` are the only auto-computed fields
in that slice; every other "what kind of change is this" signal in this codebase is caller-supplied
or system-fixed, never inferred from a diff. Permission required: `PROMOTION` -> `EMPLOYEE.PROMOTE`;
everything else -> `EMPLOYEE.TRANSFER`, including `INITIAL` (an initial placement is not a
promotion, and `EMPLOYEE.CREATE`-only callers who lack `EMPLOYEE.TRANSFER` are deliberately unable
to place a new employee without the more specific permission — mirrors how `EMPLOYEE.TERMINATE` was
kept separate from `.CREATE`/`.UPDATE` in E-03 rather than folded in).

### 14.3 `branch_id`/`department_id`/`designation_id` required only on the first row — ENGINEERING DECISION

Per `03_EMPLOYEE_API_PLAN.md §2.2`'s documented POST body shape ("changed fields only... unchanged
fields carry forward from the current row"), these three fields cannot be DB-`NOT NULL` (§6) but
must be present when there is no current row to carry forward from. Enforced in the service (§9
step 3), not the DB or a static Pydantic requirement, since "required" here is conditional on
server-side state the schema layer can't see.

### 14.4 No cross-entity consistency check between `branch_id`/`department_id`/`legal_entity_id` — ENGINEERING DECISION (deliberately not built)

Whether an assignment's `branch_id` must belong to the same `legal_entity_id` as the employee's
current `employment.legal_entity_id`, or whether `department_id` must belong to the chosen
`branch_id`, is **not stated in any authoritative document** read for this plan. Verified against
the live organisation module: `Department.branch_id` is nullable and no DB constraint ties
`Designation`/`Grade` to any branch/legal-entity chain either — **the organisation module itself
does not enforce this class of cross-entity consistency anywhere**. Building it into E-04 would be
inventing a validation rule stricter than the modules Employee depends on already enforce on
themselves, which the brief's "do not invent requirements" instruction argues against. **Recommendation:
do not build this check in E-04.** If product wants it, it should be scoped as a named requirement
against the organisation module's own data model, not bolted onto Employee's write path alone.

### 14.5 Reporting-manager self-reference guard only, no cycle detection — ENGINEERING DECISION

`reporting_manager_id != employee_id` is checked (an employee cannot directly manage themselves).
Multi-hop cycle detection (A manages B manages C manages A) is **not** built — no document requires
it, and building a graph-cycle check over an effective-dated table (a cycle could exist on one date
and not another, since assignments change independently) is a meaningfully larger feature than this
slice's scope. Flagged as a known limitation (§18), not silently omitted.

### 14.6 `EMPLOYEE.VIEW` scope for assignment reads — LOCKED, not decided here

`EMPLOYEE.VIEW` (self/scope) vs. `.VIEW_ALL` (company-wide) — the `SELF`/`REPORTEES`/
`REPORTEE_TREE`/... data-scope model (`00_EMPLOYEE_AUDIT.md §13.2`) is locked as *catalogue shape*
(Part A4/B9) but its resolver implementation is explicitly new infrastructure not yet built anywhere
in this codebase. **E-04 does not build the data-scope resolver** — this plan's `GET
.../assignments` endpoints gate on `EMPLOYEE.VIEW` exactly as `Employment`'s own GETs already do
(company-wide once granted, no `SELF`/`REPORTEES` narrowing yet), consistent with how E-01/E-03
already deferred this (confirmed: `EmploymentService`'s reads have no data-scope narrowing either).
Building the resolver is E-10's scope (`01_EMPLOYEE_MODULE_PLAN.md` §"E-10"), not E-04's — flagged
here so E-04 isn't mistakenly expected to deliver fine-grained view scoping it was never scheduled
to build.

---

## 15. Optimistic concurrency

`version` column, same convention as every other table in this domain. Only the "close current row"
write (`effective_to` only) is version-gated in the traditional sense — `WHERE version ==
expected_version ... RETURNING`, `None` result -> re-fetch + `StaleResourceError` (409), same shape
as `EmploymentService`'s existing handling. The new row inserted alongside it always starts at
`version = 1`, same as every other table's create path.

**Note**: the API body for `POST .../assignments` must carry the *current* row's `expected_version`
(via `If-Match`, matching every other mutable resource in this codebase) even though the operation
is semantically an insert — the version being checked is the row being closed, not the row being
created. This mirrors no exact precedent in E-01/E-03 (neither `Employee` nor `Employment` has a
"close-and-insert" operation) — flagged as the one genuinely new API-shape wrinkle E-04 introduces:
`If-Match` on a `POST`, not a `PATCH`. For the "no current row" case (§14.3), no `If-Match` is
required or meaningful — there is nothing to version-check.

---

## 16. RLS / tenant isolation

No change needed — already live and correct (`FORCE ROW LEVEL SECURITY`, `tenant_isolation` policy,
§2.1). Repository methods continue the belt-and-suspenders convention of filtering `company_id`
explicitly in every query, not relying on RLS alone (matches `EmployeeRepository`/
`EmploymentRepository`'s existing pattern).

---

## 17. Test plan

Mirrors `01_EMPLOYEE_MODULE_PLAN.md` §"E-04"'s own named risks plus the established
unit/integration split (`tests/unit/modules/employee/test_employment_service.py` +
`tests/integration/modules/employee/test_employment.py` precedent):

**Unit (service-layer)**
- No current row -> insert succeeds with all mandatory fields; missing `branch_id`/`department_id`/
  `designation_id` on a no-current-row create -> validation error.
- Current row exists -> unspecified fields carry forward correctly; specified fields override.
- No covering employment episode (§14.1) -> `NoActiveEmploymentError`.
- `change_type = PROMOTION` requires `EMPLOYEE.PROMOTE`; every other value requires
  `EMPLOYEE.TRANSFER` — permission-selection logic, not RBAC middleware itself.
- `reporting_manager_id == employee_id` -> rejected (§14.5).
- Invalid/soft-deleted/cross-tenant `branch_id`/`department_id`/`designation_id`/`grade_id`/
  `reporting_manager_id`/`dotted_line_manager_id` -> each own `422`.
- Stale `version` on the close step -> `StaleResourceError` (409), current snapshot attached.

**Integration (DB-level)**
- **GiST exclusion constraint verification** — attempt to insert an assignment row that overlaps an
  existing one for the same employee (bypassing the service's own close-first logic, to prove the
  DB constraint is the actual backstop, not just an application-level check) -> expect DB-level
  rejection, translated to `AssignmentDatesOverlapError`. This is `01_EMPLOYEE_MODULE_PLAN.md`
  §"E-04"'s own named first test.
- **As-of-date query correctness against the brief's own worked example** — insert rows matching
  the 2027 (Dept A/Grade 2) / 2028 (Dept B/Grade 3) scenario from `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md`
  Part D and `00_EMPLOYEE_AUDIT.md`'s own brief; query `as_of` various dates including exactly the
  boundary (`effective_from`/`effective_to`) and confirm the correct single row.
- **Full rehire scenario, end-to-end** — reusing E-03's rehire test fixture (exit -> gap -> rehire),
  extended to also close the pre-exit assignment at exit and open a fresh one at rehire; assert:
  `employee_id` unchanged across both assignment rows, no assignment rows exist during the gap
  (`get_assignment_as_of` during the gap returns `None`), full history query returns exactly the
  pre-exit and post-rehire rows with a visible gap.
- **FK constraint verification** — attempt a raw insert (bypassing the service) referencing a
  nonexistent `department_id`/`branch_id`/`grade_id`/`reporting_manager_id` -> expect a DB-level FK
  violation, confirming the migration's new constraints are actually enforced (the exact gap this
  investigation's Phase 2 was asked to check).
- **Cross-tenant isolation** — assignment referencing a department/branch/grade/designation
  belonging to a *different* company -> rejected (mirrors `EmploymentService`'s own
  `_assert_legal_entity_ownership` cross-tenant check pattern), verified both via the service-layer
  check and via RLS directly (matching the existing `test_cross_tenant_isolation.py` pattern named
  in `01_EMPLOYEE_MODULE_PLAN.md` §"E-10").
- **Manager-reassignment on pending approvals** — explicitly **not** tested beyond "the field is
  stored," since the approval-routing engine doesn't exist (`01_EMPLOYEE_MODULE_PLAN.md` §"E-04"
  itself calls this "thin until the approval-routing engine exists").

---

## 18. Known limitations (to state explicitly in E-04's own closeout report, not silently omit)

1. **Inter-entity transfer's full FR-EMP-011 workflow is not built** — E-04 ships intra-entity
   assignment changes only. An inter-entity transfer (which requires closing the current
   `employment` row and opening a new one, per Part C) is an `Employment`-level operation outside
   this slice's scope; nothing in E-04 wires the two together into a single guided workflow.
2. **BR-14 shift-override chain remains unbuilt** — not this slice's concern regardless (§5), but
   worth restating: `shift_id` itself doesn't exist until E-05, so this limitation is inherited, not
   introduced, by E-04.
3. **Payroll-lock-period backdating enforcement (FR-EMP-004) is not implementable** — Payroll
   doesn't exist. Any `effective_from` in the past is currently accepted without a lock-period
   check.
4. **Approval-routing reassignment on manager change (FR-EMP-013) is not built** — the
   `reporting_manager_id` change is recorded; no pending-approval reassignment occurs, because no
   approval-routing engine exists to reassign anything.
5. **No cycle detection on the reporting-manager chain** beyond direct self-reference (§14.5).
6. **No cross-entity consistency check** between `branch_id`/`department_id`/`legal_entity_id`
   (§14.4) — deliberate, matching the organisation module's own precedent of not enforcing this
   either.
7. **The `SELF`/`REPORTEES`/`REPORTEE_TREE` data-scope resolver is not built** — `GET
   .../assignments` is gated only on the coarse `EMPLOYEE.VIEW`/`.VIEW_ALL` distinction, same as
   `Employment`'s existing reads (§14.6). This is E-10's scope, not E-04's.
8. **Promotion letters are not generated** — `change_type=PROMOTION` is recorded; no document is
   produced (E-09).

---

## 19. Explicitly excluded features (Phase 8 scope confirmation)

This investigation, and the E-04 implementation it plans, do **not** implement:

- Compensation (E-06)
- Statutory (E-07)
- Banking (E-08)
- Attendance
- Leave
- Payroll
- ATS / Recruitment
- Workflow automation / approval-routing engine
- BR-14 shift/notice-period override chain
- Shift assignment (`shift_id` column itself — E-05)
- Inter-entity transfer's employment-closing mechanics (only the `employment`-level half of
  FR-EMP-011; the assignment-level half — branch/department/manager change within one episode — is
  in scope)

No application code, migration, or frontend file was changed by this investigation. No decision
requiring product sign-off was found; nothing here was escalated to a decision document because
none was necessary (Phase 6/7 gate).

---

## 20. Recommended implementation sequence

1. Migration: extend `employee_assignment` (§6) — new columns + 6 FK constraints (5 existing
   relationship columns + `dotted_line_manager_id`) + 2 new indexes. Verify against the dev DB with
   `\d employee_assignment` afterward, same discipline E-03's closeout report followed.
2. `EmployeeAssignment` ORM model (§7).
3. `EmployeeAssignmentRepository` (§8), including `get_assignment_as_of` — write this method first
   and test it in isolation, since it is the cross-module contract every later slice depends on.
4. Exceptions: `NoActiveEmploymentError`, `AssignmentDatesOverlapError`, plus one `Invalid<Entity>ReferenceError`
   per validated FK target (or a single parameterized error, an implementation-time call).
5. `EmployeeAssignmentService.create_assignment` (§9) + read methods.
6. Permissions: `EMPLOYEE.TRANSFER`, `EMPLOYEE.PROMOTE` (§11).
7. Schemas: `AssignmentCreate` (with the no-current-row-vs-carry-forward conditional-required
   handling), `AssignmentRead`.
8. Router: 3 endpoints (§10), wired into the existing `employee_router`.
9. Unit tests (§17), written alongside the service, not after.
10. Integration tests (§17), especially the GiST-constraint and rehire-scenario tests — these are
    the acceptance tests for this slice's two named risks (first effective-dated write path;
    rehire correctness).
11. Update `01_EMPLOYEE_MODULE_PLAN.md`/`00_EMPLOYEE_AUDIT.md` cross-references if their own E-04
    row needs a "COMPLETE" status update, mirroring E-03's own closeout-report convention
    (`08_EMPLOYMENT_LIFECYCLE_IMPLEMENTATION_REPORT.md`) — a new
    `docs/modules/employee/10_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_REPORT.md` at close, not edits to
    this plan document itself.

**Frontend scope for E-04 itself**: none. Per `01_EMPLOYEE_MODULE_PLAN.md` §"E-04", the Job tab's
assignment history UI and the Org chart screen are named in the frontend column, but E-09
("Directory/profile UI... needs E-01 through E-08") is where all Employee frontend work is
sequenced — building UI now, ahead of Tabs/Timeline/PermissionGate primitives (§00 §14.5, deferred
to immediately before E-09 per Part A10), would mean building throwaway or inconsistent UI. **No
frontend file should be touched by E-04's implementation** — this matches E-01/E-03's own precedent
(`apps/web/` was not touched by either).

---

## Summary answers (this task's Final Output checklist)

1. **E-04 readiness status**: Ready to implement. No blocking product decision found.
2. **What already exists**: `employee_assignment` table (partial — 5 of 11 documented business
   columns, GiST no-overlap constraint, RLS, only 1 of 6 relationship columns FK-constrained), fully
   shipped `Employee`/`Employment` (E-01/E-03), the `get_employment_as_of` pattern to mirror.
3. **What is missing**: `EmployeeAssignment` ORM model/repository/service/router/schemas/exceptions
   (none exist), `dotted_line_manager_id`/`cost_centre_id`/`work_location_type`/`change_reason`/
   `change_type` columns, 6 FK constraints, `EMPLOYEE.TRANSFER`/`.PROMOTE` permissions,
   `ASSIGNMENT_CHANGED` audit action.
4. **Database gaps**: §2.1/§6 — verified directly against the dev database, matches
   `00_EMPLOYEE_AUDIT.md §3.3`'s prior findings exactly, unchanged since.
5. **Relationship model**: §3 — `employee_id`-keyed, not `employment_id`-keyed; branch/department/
   designation required at first placement, grade/managers optional; `shift_id` excluded until E-05.
6. **Rehire implications**: §4 — no special-case code needed; a rehire's first assignment is
   mechanically identical to any employee's first assignment, gated only by §14.1's "must have a
   covering employment episode" rule.
7. **Shift implications**: §5 — column stays out of E-04 entirely; BR-14 stays deferred.
8. **Product decisions required**: none. Every decision E-04 depends on was already resolved in
   `00_EMPLOYEE_AUDIT.md`/`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` before this task began.
9. **Recommended design**: §6-§16, in full.
10. **Exact next implementation task**: §20 step 1 — write and apply the migration, verify against
    the dev database, then proceed through steps 2-11 in order.
11. **Documentation created/updated**: this document
    (`docs/modules/employee/09_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_PLAN.md`) only. No other file was
    modified by this investigation.
