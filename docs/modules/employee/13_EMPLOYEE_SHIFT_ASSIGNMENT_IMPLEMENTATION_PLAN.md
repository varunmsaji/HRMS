# Employee Shift Assignment (E-05) — Implementation Plan

Investigation-and-plan document for the vertical slice named `01_EMPLOYEE_MODULE_PLAN.md` /
`00_EMPLOYEE_AUDIT.md §16` row "**E-05** Shift assignment". Written per this task's own
instruction: investigate only, no application code, migrations, or tests in this task. Every
claim below traces to an authoritative document, the live database, or the live codebase —
nothing here invents a requirement absent from those sources. Where no source settles a
question, this is stated explicitly and the recommendation is labeled as an engineering
recommendation, not a documented requirement.

**Verdict up front: no blocking product decision exists for E-05.** Every authoritative source
already agrees on E-05's shape — `shift_id` is a nullable, per-employee, effective-dated column
on the existing `employee_assignment` row, added by its own migration, written through the
existing `POST /v1/employees/{id}/assignments` endpoint under a new `change_type` value, with the
BR-14 override chain staying explicitly deferred. One genuine documentation conflict exists (the
edit-permission cell, §12 below) and is resolved here with a recommendation, not left open. See
§22 for the final readiness status.

---

## 1. Executive Summary

E-05 adds exactly one column (`employee_assignment.shift_id`, nullable UUID, FK to `shift.id`)
and exactly one new `change_type` enum value (`SHIFT_CHANGE`) to the module E-04 already shipped.
It does not add a new table, a new endpoint, a new permission, a new audit action, or any
frontend surface. The write path, read path, audit mechanism, and effective-dating discipline are
all already built by E-04 and require no structural change — only field-level extension.

The scope is intentionally narrow because two structurally larger pieces of work are explicitly
**not** part of E-05, confirmed by every source that discusses them:

1. **The BR-14/FR-EMP-018 shift-and-notice-period override chain** (Company → Branch → Department
   → Grade → Employee cascading default) — locked as deferred by
   `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part A3/B8/Part G item 1, re-confirmed by both
   `09_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_PLAN.md §1/§5` (E-04's own plan) and
   `00_SHIFT_RULES_AUDIT.md §3.1`. E-05 ships only the direct leg
   (`employee_assignment.shift_id`); no `default_shift_id` column is added to Branch, Department,
   Grade, or Designation.
2. **Attendance-side consumption** (grace-period math, late marking, cross-midnight day
   attribution, OT computation, weekly-off/holiday resolution, `shift_roster`/
   `shift_rotation_pattern`) — confirmed out of scope by `00_SHIFT_RULES_AUDIT.md §3.4` and
   `01_Shift_Rules_Module.md §12`; these are named Attendance-module concerns, a module that does
   not exist in this codebase.

E-05's entire deliverable is: one migration, one model field, one schema field + one enum value,
one service-layer ownership-validation method, one new exception class, and the corresponding
test extensions. No router change is required (§11 explains why). No frontend change is required
(§14). No new permission is required (§12).

---

## 2. Current State

Verified directly against the live dev database (`hrms_dev` on `localhost:5433`, 2026-08-14) and
the live codebase — not inferred from documentation alone.

### 2.1 `employee_assignment` — live schema

```
id                      uuid            PK
company_id              uuid            NOT NULL
employee_id             uuid            NOT NULL   FK -> employee.id ON UPDATE CASCADE ON DELETE RESTRICT
department_id           uuid            nullable   FK -> department.id ON DELETE SET NULL
designation_id          uuid            nullable   FK -> designation.id ON DELETE SET NULL
grade_id                uuid            nullable   FK -> grade.id ON DELETE SET NULL
reporting_manager_id    uuid            nullable   FK -> employee.id ON DELETE SET NULL
dotted_line_manager_id  uuid            nullable   FK -> employee.id ON DELETE SET NULL
branch_id               uuid            nullable   FK -> branch.id ON DELETE SET NULL
cost_centre_id          uuid            nullable   (no FK — no cost_centre table exists)
work_location_type      varchar(20)     nullable
change_reason           text            nullable
change_type             varchar(30)     nullable
effective_from          date            NOT NULL
effective_to            date            nullable
created_at              timestamptz     NOT NULL
updated_at              timestamptz     NOT NULL
deleted_at              timestamptz     nullable
version                 integer         NOT NULL DEFAULT 1
```

- **No `shift_id` column.** Confirmed absent from both the live table and
  `apps/api/src/hrms/modules/employee/models.py:104-153`.
- Indexes: `employee_assignment_pkey`, `employee_assignment_company_id_idx`,
  `employee_assignment_current_idx (company_id, employee_id, effective_from DESC)`,
  `employee_assignment_employee_id_effective_from_idx (employee_id, effective_from)`,
  `employee_assignment_manager_idx (company_id, reporting_manager_id) WHERE effective_to IS NULL`.
- **GiST exclusion constraint** `employee_assignment_no_overlap` on `(employee_id WITH =,
  daterange(effective_from, COALESCE(effective_to,'infinity'),'[]') WITH &&)` — live, structurally
  prevents two overlapping "current" rows per employee.
- **RLS**: `FORCE ROW LEVEL SECURITY`, `tenant_isolation` policy comparing `company_id` against
  `current_setting('app.company_id', true)::uuid`.
- **Row count: 0.** Confirmed live (`SELECT count(*) FROM employee_assignment` → 0). No data
  migration/backfill is needed for E-05's own migration.

### 2.2 `shift` — live schema

```
id                        uuid            PK
company_id                uuid            NOT NULL   FK -> company.id ON UPDATE CASCADE ON DELETE RESTRICT
name                      varchar(100)    NOT NULL
code                      varchar(30)     nullable
start_time                time            NOT NULL
end_time                  time            NOT NULL
break_minutes_paid        integer         NOT NULL DEFAULT 0
break_minutes_unpaid      integer         NOT NULL DEFAULT 0
grace_in_minutes          integer         NOT NULL DEFAULT 0
grace_out_minutes         integer         NOT NULL DEFAULT 0
half_day_threshold_hours  numeric(4,2)    nullable
min_hours_full_day        numeric(4,2)    nullable
is_night_shift            boolean         NOT NULL DEFAULT false
is_cross_midnight         boolean         NOT NULL DEFAULT false
is_ot_eligible            boolean         NOT NULL DEFAULT false
is_active                 boolean         NOT NULL DEFAULT true
deleted_at                timestamptz     nullable
version                   integer         NOT NULL DEFAULT 1
created_at                timestamptz     NOT NULL
updated_at                timestamptz     NOT NULL
```

- Indexes: `shift_pkey`, `shift_company_active_idx (company_id, is_active) WHERE deleted_at IS
  NULL`, `shift_company_id_idx`.
- **No inbound FK from any table.** `shift` is a standalone aggregate — nothing references it yet.
- RLS: same mechanism as `employee_assignment`.
- **Row count: 0.** Confirmed live.
- **Soft-deactivation only, never hard-deleted** — `DELETE /v1/shifts/{id}` flips `is_active` to
  `false` via the same code path as `PATCH {is_active: false}`
  (`organisation/service.py:1583-1646`). No document or code path hard-deletes a `Shift` row once
  created, so `shift_id`'s FK `ON DELETE` clause is effectively never exercised in practice — see
  §7.

### 2.3 Current Employee Assignment API (E-04, shipped)

One write endpoint, `POST /v1/employees/{employee_id}/assignments` (no `PATCH`/`DELETE` on an
individual row — history is never edited in place, only ever closed-and-superseded). Covers
`INITIAL`/`TRANSFER`/`PROMOTION`/`MANAGER_CHANGE` today, distinguished by the request's
`change_type`, which also selects the required permission:

```python
# apps/api/src/hrms/modules/employee/router.py:325
required_permission = EMPLOYEE_PROMOTE if body.change_type == "PROMOTION" else EMPLOYEE_TRANSFER
```

Two read endpoints (`GET .../assignments`, `GET .../assignments/{id}`), both gated on
`EMPLOYEE.VIEW`, no data-scope narrowing (E-10's scope, not built yet).

`AssignmentCreate`/`AssignmentRead` (schemas.py:244-309) are `extra="forbid"` Pydantic models with
every organisational reference field optional except at first placement (`branch_id`/
`department_id`/`designation_id` mandatory when no current row exists; every other field carries
forward unchanged from the current row when omitted). `AssignmentChangeType =
Literal["INITIAL", "TRANSFER", "PROMOTION", "MANAGER_CHANGE"]` — four values today.

### 2.4 Current Employee Assignment service (E-04, shipped)

`EmployeeAssignmentService.create_assignment` (service.py:607-766):
1. Asserts the employee exists (tenant-scoped).
2. Asserts a covering `Employment` episode exists on `effective_from`
   (`EmploymentRepository.get_employment_as_of`) — `409 NO_ACTIVE_EMPLOYMENT` otherwise.
3. Reads the current assignment row (`effective_to IS NULL`), if any.
4. If no current row: `branch_id`/`department_id`/`designation_id` are mandatory
   (`422 ASSIGNMENT_FIELDS_REQUIRED` otherwise); every other field takes the request value as-is.
5. If a current row exists: `effective_from` must be strictly after the current row's
   `effective_from` (`422 INVALID_EFFECTIVE_FROM`); `If-Match` is required
   (`422 ASSIGNMENT_VERSION_REQUIRED`); every omitted field carries forward from the current row.
6. Validates every non-null reference field against its owning module — `_assert_branch_ownership`
   / `_assert_department_ownership` / `_assert_designation_ownership` / `_assert_grade_ownership`,
   each a thin wrapper that lazily imports `OrganisationService` and calls its `get_<entity>`
   method, translating a `NotFoundError` (which `OrganisationService` already raises for both
   "doesn't exist" and "different tenant" — it never leaks cross-tenant existence) into a module-
   local `Invalid<Entity>ReferenceError` (`422 INVALID_<ENTITY>`).
7. Closes the current row (if any) and inserts a new row, in one transaction, with a GiST-exclusion
   race-condition backstop (`409 ASSIGNMENT_DATES_OVERLAP` on constraint violation).
8. Records one `ASSIGNMENT_CHANGED` audit event, `before`/`after` = generic `AssignmentRead.model_
   dump(mode="json")` snapshots (schemas.py:312-313) — **not a hand-maintained field list**, so any
   field added to `AssignmentRead` automatically appears in the audit snapshot with no further
   code change.

`EmployeeAssignmentRepository.insert_assignment` takes a generic `data: dict[str, Any]` and does
`EmployeeAssignment(**data)` — **not a hand-maintained field list either.** Both of these generic-
by-construction choices are why §6/§9 below show E-05's diff is unusually small: two of the four
layers (repository, audit snapshot) require zero code change for a new field.

### 2.5 Current Shift Rules module (shipped, `organisation` package)

Full CRUD + soft deactivate/reactivate on `/v1/shifts`, gated by a single permission
`ORG.SHIFT.MANAGE`, tenant-isolated the same way as every other organisation-module resource,
audited (`SHIFT_CREATED`/`SHIFT_UPDATED`/`SHIFT_DEACTIVATED`/`SHIFT_REACTIVATED`). `Shift` is a
standalone aggregate — no FK to Legal Entity/Branch/Department/Designation/Grade, and (per
`00_SHIFT_RULES_AUDIT.md §3.1`/§6.4 and `01_Shift_Rules_Module.md §13` item 8) **no deactivation-
blocking rule of any kind** — a shift can be deactivated with no check for existing references,
because at Shift's own build time Employee Assignment did not exist to reference it. This is a
carried-forward, still-current gap — see §7.

`OrganisationService.get_shift(company_id, shift_id)` (service.py:1577-1581) and
`OrganisationRepository.get_shift` (repository.py:658-669) mirror `get_branch`'s exact shape:
filter on `id`, `company_id`, and `deleted_at IS NULL` — **`is_active` is not part of the
existence check.** This is the load-bearing precedent for §7.2 below.

### 2.6 Current audit and permission mechanics

`AuditService.record` (already generic — `entity_type`/`before`/`after`/`ip`/`user_agent`) needs
no change. RBAC is checked via `RbacService.has_permission(user_id, company_id, code)`, called
explicitly in the router (not via `Depends(require_permission(...))`) precisely because the
required code depends on the parsed request body — this pattern already handles a `change_type`
value it doesn't recognize by falling through to `EMPLOYEE_TRANSFER` (the `else` branch), which is
directly relevant to §12.

---

## 3. Authoritative Requirements

Every source that names `employee_assignment.shift_id` or `SHIFT_CHANGE`, in order of how
specific/recent each is:

| Source | What it says |
|---|---|
| `docs/product/02_PRD.md §11` | Assignment = "department, designation, grade, reporting manager, location, shift. Time-versioned." |
| `docs/product/08_Database_Architecture.md §5.3` | `employee_assignment` columns include `shift_id`; `change_type` enum includes `SHIFT_CHANGE` (alongside `JOINING/PROMOTION/TRANSFER/MANAGER_CHANGE/CONFIRMATION`) |
| `docs/product/09_API_Standards.md §3.2` | `POST /employees` request example nests `"shift_id": "…"` inside the `assignment` sub-object (a *different*, combined-create endpoint than the one E-04/E-05 actually ship — see §11.3 for the reconciliation) |
| ADR-0003 (`docs/adr/0003-effective-dated-modelling.md`) | Names "shift" explicitly among the attributes `EmployeeAssignment` must model as effective-dated, alongside department/designation/manager/branch |
| `00_EMPLOYEE_AUDIT.md §16` (slice table) | E-05 row: "Adds `shift_id` to assignment \| `ALTER TABLE employee_assignment ADD COLUMN shift_id` + FK \| (folds into `.TRANSFER`) \| (folds into `ASSIGNMENT_CHANGED`, `change_type=SHIFT_CHANGE`) \| BR-14 override chain explicitly not built here" |
| `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part A3/B8 | Locks: ship the direct leg (`employee_assignment.shift_id`, nullable, settable) now; defer the BR-14 cascading-default chain to a separate, later, cross-module decision |
| `02_EMPLOYEE_DATA_MODEL.md §2` section E | `shift_id` — not required, mutable via new row (`change_type = SHIFT_CHANGE`), effective-dated yes, class INTERNAL, View `EMPLOYEE.VIEW`, Edit `EMPLOYEE.UPDATE` *(the one documented value this plan does not follow as-is — see §12)* |
| `09_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_PLAN.md §5` (E-04's own plan) | Confirms the column shape, confirms E-04 must not touch it, confirms it's nullable and deferred-override |
| `12_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_REPORT.md §20` | E-04's own "recommended next step" — the most implementation-precise single paragraph naming what E-05 does: `ALTER TABLE ... ADD COLUMN shift_id`, FK to `shift(id)`, settable on the same `POST .../assignments` endpoint, `change_type = SHIFT_CHANGE` as "a fifth enum value to add" |
| `00_SHIFT_RULES_AUDIT.md §3.3`, `01_Shift_Rules_Module.md §11` | Confirm the relationship is intentionally one-directional/forward-only from Shift's side; Shift ships first, references nothing back |
| `docs/product/17_SRS_Phase1_Core_Modules.md:123` | Documents the same `employee_assignment.shift_id`/`SHIFT_CHANGE` shape in the SRS's own field list |

**No source contradicts the core shape** (nullable column, same row, `SHIFT_CHANGE` change_type,
`ASSIGNMENT_CHANGED` audit action, BR-14 deferred). The one genuine conflict is narrower — see
§12.

---

## 4. Existing Shift Rules Integration

E-05's only integration point with the Shift Rules module is a **read-only, cross-module
existence/ownership check**, mirroring exactly how E-04 already validates `branch_id`/
`department_id`/`designation_id`/`grade_id` against `organisation.service` (never `.repository`/
`.models` directly, per `docs/architecture/02_Module_Standard.md §2`):

```python
async def _assert_shift_ownership(self, company_id: UUID, shift_id: UUID) -> None:
    from hrms.modules.organisation.service import OrganisationService

    organisation = OrganisationService(self._session, self._settings)
    try:
        await organisation.get_shift(company_id, shift_id)
    except NotFoundError as exc:
        raise InvalidShiftReferenceError() from exc
```

This is a direct copy of `_assert_grade_ownership`'s shape (service.py:579-586). No modification
to `organisation/models.py`, `organisation/service.py`, `organisation/repository.py`,
`organisation/router.py`, or `organisation/permissions.py` is required or in scope — Shift Rules
is consumed exactly as E-04 already consumes Branch/Department/Designation/Grade: as an
already-complete, unmodified dependency.

**Does `get_shift` check `is_active`?** No — confirmed in §2.5. This means E-05's ownership check,
by construction (reusing the existing `get_shift` method verbatim), does **not** reject an
inactive shift. See §7.2 for why this is the correct, precedent-consistent behavior rather than a
gap to close.

---

## 5. Employee Assignment Integration

`shift_id` becomes the ninth optional reference field on `AssignmentCreate`/`AssignmentRead`,
following the exact carry-forward rule every other optional field already follows:

- **First assignment (no current row)**: `shift_id` is optional (not in the mandatory
  `branch_id`/`department_id`/`designation_id` set) — an employee can have no shift from day one,
  consistent with `02_EMPLOYEE_DATA_MODEL.md §2` section E's "not required" and A3/B8's "NULL is a
  legitimate, expected value."
- **Subsequent assignment (current row exists)**: if `shift_id` is omitted from the request, it
  carries forward unchanged from the current row — identical treatment to `grade_id`/
  `work_location_type`/`cost_centre_id` today. If provided, it is validated (§4) and becomes the
  new row's value.
- **`SHIFT_CHANGE`**: a pure-shift change (no branch/department/designation/grade/manager change)
  is expressed as `change_type="SHIFT_CHANGE"` with only `shift_id` set in the request body; every
  other field carries forward from the current row exactly as a `MANAGER_CHANGE` request today
  only sets `reporting_manager_id`/`dotted_line_manager_id`.

No new endpoint. No new sub-resource. The single-write-operation model E-04 established
(`10_EMPLOYEE_ASSIGNMENT_MODULE.md §3`: "There is exactly one write path... distinguished only by
the request's `change_type`") extends cleanly to a fifth `change_type` value with zero structural
change.

---

## 6. Data Model Changes

### 6.1 ORM model (`apps/api/src/hrms/modules/employee/models.py`)

One field added to `EmployeeAssignment` (currently lines 104-153), in the same position the
column occupies in the documented DDL (`02_EMPLOYEE_DATA_MODEL.md §3`) — after
`dotted_line_manager_id`, before `cost_centre_id`:

```python
shift_id: Mapped[UUID | None] = mapped_column(
    PG_UUID(as_uuid=True), ForeignKey("shift.id"), nullable=True
)
```

The class docstring's existing sentence "`shift_id` is deliberately absent — ships in E-05..."
(models.py:114-116) must be updated/removed as part of this change — it will otherwise become a
stale comment describing a state the code no longer matches.

### 6.2 Schema changes (`apps/api/src/hrms/modules/employee/schemas.py`)

```python
AssignmentChangeType = Literal["INITIAL", "TRANSFER", "PROMOTION", "MANAGER_CHANGE", "SHIFT_CHANGE"]
```

`AssignmentCreate`: add `shift_id: UUID | None = None`.
`AssignmentRead`: add `shift_id: UUID | None`.
`assignment_to_read`: add `shift_id=assignment.shift_id`.

`ASSIGNMENT_CHANGE_TYPE_VALUES` (router.py:237, if still referenced) gets `"SHIFT_CHANGE"`
appended alongside the schema's `Literal`.

No change to `WorkLocationType`, `work_location_type`, or any other field.

### 6.3 Repository (`apps/api/src/hrms/modules/employee/repository.py`)

**No change required.** `insert_assignment` takes a generic `dict[str, Any]` (§2.4) — the service
layer including `shift_id` in the dict it builds is sufficient. `get_current_assignment`/
`get_assignment_as_of`/`list_assignments`/`get_assignment`/`close_assignment` all `SELECT
EmployeeAssignment` or operate on the ORM row directly — none enumerates columns by name.

### 6.4 Exceptions (`apps/api/src/hrms/modules/employee/exceptions.py`)

One new class, a direct copy of `InvalidGradeReferenceError`'s shape (exceptions.py:241-249):

```python
class InvalidShiftReferenceError(ValidationError):
    code = "INVALID_SHIFT"

    def __init__(self, message: str = "shift_id does not reference a valid shift") -> None:
        super().__init__(
            message, details=[{"field": "shift_id", "code": "INVALID_SHIFT", "message": message}]
        )
```

### 6.5 Service (`apps/api/src/hrms/modules/employee/service.py`)

In `EmployeeAssignmentService`:
- New method `_assert_shift_ownership` (§4).
- In `create_assignment`, in the "no current row" branch: `shift_id = body.shift_id`. In the "has
  current row" branch: `shift_id = body.shift_id if body.shift_id is not None else
  current.shift_id`.
- One new validation call alongside the five existing ones: `if shift_id is not None: await
  self._assert_shift_ownership(company_id, shift_id)`.
- Add `"shift_id": shift_id` to the `data` dict passed to `insert_assignment`.

No change to `list_assignments`/`get_assignment`/`get_assignment_as_of` — they already return
whatever `assignment_to_read` produces, which will include `shift_id` once §6.2 lands.

### 6.6 Router (`apps/api/src/hrms/modules/employee/router.py`)

**No change required.** The existing permission-selection line —

```python
required_permission = EMPLOYEE_PROMOTE if body.change_type == "PROMOTION" else EMPLOYEE_TRANSFER
```

— already routes every non-`PROMOTION` `change_type` (including a new `SHIFT_CHANGE` value) to
`EMPLOYEE_TRANSFER` with no code change, purely as a consequence of the binary `if/else` shape
E-04 already chose. See §12 for why this is also the recommended permission, not just the
accidental default.

---

## 7. Migration Plan

### 7.1 DDL

One new Alembic migration, `apps/api/alembic/versions/<timestamp>_employee_shift_assignment.py`,
following the exact `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` + `ADD CONSTRAINT` pattern E-03's
and E-04's migrations both used:

```sql
ALTER TABLE employee_assignment
  ADD COLUMN IF NOT EXISTS shift_id UUID;

ALTER TABLE employee_assignment
  ADD CONSTRAINT employee_assignment_shift_id_fkey
    FOREIGN KEY (shift_id) REFERENCES shift(id) ON DELETE SET NULL;
```

**No new index.** `02_EMPLOYEE_DATA_MODEL.md §3`'s own proposed DDL (the most detailed migration
sketch available) does not add a `shift_id`-specific index, and E-04 did not add the
department-scoped index that same document's earlier section suggested
(`(company_id, department_id, effective_from)`) either — E-04 shipped only
`employee_assignment_current_idx`/`employee_assignment_manager_idx`. Consistency with that
precedent argues against inventing a new index E-05's own sources don't call for. If Attendance's
future `shift_id`-keyed lookups need one, that is Attendance's own migration to add when it ships,
not a speculative addition here.

**No RLS change.** Already live and correct (`FORCE ROW LEVEL SECURITY`, `tenant_isolation`); if
the migration touches the table at all, re-assert idempotently per house convention (matches every
prior migration's habit), not because anything is actually missing.

**No data backfill.** `employee_assignment` has 0 rows, verified live (§2.1) — the column addition
is purely additive.

### 7.2 `ON DELETE SET NULL` — why, and why it's inert in practice

`02_EMPLOYEE_DATA_MODEL.md:290` proposes exactly this clause, matching the convention every other
optional reference FK on `employee_assignment` already uses (`department_id`, `designation_id`,
`grade_id`, `branch_id`, `reporting_manager_id`, `dotted_line_manager_id` are all `ON DELETE SET
NULL`). Deviating to `RESTRICT` for `shift_id` alone, with no document asking for it, would be an
invented inconsistency.

In practice this clause is very unlikely to ever fire: `Shift` is soft-deactivate-only (§2.2, §2.5
— `DELETE /v1/shifts/{id}` flips `is_active`, never issues a SQL `DELETE`), so no code path in
this codebase currently performs a hard delete of a `shift` row. The FK exists for referential
integrity and defensive correctness, not because a routine operation is expected to trigger it.

### 7.3 Should the shift FK be same-company-only? At the DB level, no — at the service level, yes

No `CHECK`/cross-table constraint enforces `employee_assignment.company_id = shift.company_id` at
the database layer — and none should be invented: `12_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_REPORT.md
§17` item 2 explicitly documents that E-04 has "no cross-entity consistency check" between its
five existing reference columns and the employee's own company either, "deliberate, matching the
organisation module's own precedent." `shift_id` follows the same precedent for consistency, not
because tenant safety is skipped — it isn't: `_assert_shift_ownership` (§4) performs the same-
company check at the **service** layer, via `OrganisationService.get_shift(company_id, shift_id)`,
which already scopes by `company_id` and returns `NotFoundError` (translated to `422
INVALID_SHIFT`, never a cross-tenant `200`) for a shift belonging to another company — mirroring
exactly how `_assert_branch_ownership`/`_assert_grade_ownership` etc. already behave, and verified
by E-04's own `test_cannot_reference_other_tenant_branch` test for the same pattern (§16.3).

### 7.4 Inactive-shift assignment — precedent-following recommendation, not a documented rule

**No document states whether a shift must be active on the assignment's effective date, or
whether an inactive shift can be newly assigned.** This question is genuinely open in every source
consulted. The recommendation here is derived from the established, already-shipped precedent
rather than invented fresh:

- `OrganisationService.get_shift`/`OrganisationRepository.get_shift` check existence and
  `deleted_at IS NULL` only — **not** `is_active` (§2.5, verified against live code).
- The same is true of `get_branch`, which E-04's `_assert_branch_ownership` already relies on —
  meaning **E-04 today permits assigning an employee to a deactivated Branch/Department/
  Designation/Grade**, since none of those ownership checks filter on `is_active` either. This is
  not a new gap E-05 introduces; it is an existing, symmetric property of the whole reference-
  validation pattern.
- **Recommendation**: `_assert_shift_ownership` should reuse `get_shift` verbatim (§4) — existence
  + tenant-scope only, no `is_active` gate — for consistency with every sibling reference field.
  Introducing an active-only rule for `shift_id` alone, with no document asking for it, would make
  Shift's reference-validation behavior inconsistent with Branch/Department/Designation/Grade's for
  no documented reason.
- **Consequence**: an inactive shift *can* be newly assigned. This should be flagged as a known,
  precedent-consistent behavior in the implementation report, not silently discovered later.

### 7.5 Historical assignments referencing an inactive shift — yes, and this is uncontroversial

Once an assignment row is written, it is never edited (ADR-0003) — only closed by a later
`effective_to`. If a `Shift` is deactivated after being referenced by a historical (already-
closed) or even current (open) assignment row, that assignment row is completely unaffected: no
document proposes any cascading effect, and the `ON DELETE SET NULL` clause only fires on a hard
delete, which deactivation is not (§7.2). Historical correctness is preserved by construction —
this is exactly what effective-dating is for.

### 7.6 Shift deactivation-blocking — explicitly out of scope for E-05

`00_SHIFT_RULES_AUDIT.md §6.4` and `01_Shift_Rules_Module.md §13` item 8 both flag "no
deactivation-blocking rule" as a known limitation of the *already-shipped* Shift Rules module, and
`03_Shift_Rules_Implementation_Report.md §16` lists "whether Shift deactivation should eventually
be blocked by active Employee-Assignment references, once Employee Assignment exists" as an
explicitly unresolved decision for a *future* task, not this one.

`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part A5 already established the governing precedent for
this exact shape of problem — the analogous FR-ORG-014 "block deactivation while actively
referenced" retrofit for Branch/Department/Designation/Grade is explicitly **not** bundled into
any Employee vertical slice; it is deferred to "a small, separate follow-up task against the
organisation module." Applying that same precedent here: **adding a deactivation-blocking check to
`Shift` (i.e., modifying `organisation/service.py::update_shift`) is out of scope for E-05.** This
is a recommendation by consistent application of an already-locked decision, not a literal
instruction naming Shift — flagged explicitly so it is a conscious scope decision, not a silent
gap. See §18 (Non-Goals) and §19 (Known Risks).

---

## 8. Business Rules

Consolidated from §4-§7 above:

1. `shift_id` is nullable at every point in an employee's assignment history — including the
   first-ever assignment row. No default is ever synthesized (BR-14 stays deferred).
2. `shift_id` must reference an existing, non-deleted `Shift` belonging to the same `company_id`
   as the assignment — enforced at the service layer (`_assert_shift_ownership`), not the DB.
3. `shift_id` is **not** required to reference an *active* `Shift` — existence + tenant-scope only,
   matching every sibling reference field's validation depth exactly (§7.4).
4. A shift change alone (no other field changing) is expressed as `change_type="SHIFT_CHANGE"`
   with only `shift_id` set in the request; every other field carries forward from the current
   row, per the existing carry-forward rule.
5. `shift_id` can also change silently as a side effect of any other `change_type`
   (`TRANSFER`/`PROMOTION`/`MANAGER_CHANGE`/`INITIAL`) if the caller happens to include it in that
   same request — nothing in E-04's design restricts which fields may accompany which
   `change_type`; `change_type` is a label for audit/permission purposes, not a field allow-list.
   This is existing E-04 behavior, unchanged by E-05.
6. Once a `Shift` is deactivated, existing assignment rows (historical or current) referencing it
   remain valid and are not retroactively affected.
7. A `Shift` can be deactivated while actively referenced by a current assignment row — no
   blocking check is added by E-05 (§7.6).

---

## 9. Effective-Dating Rules

`shift_id` follows exactly the same effective-dating discipline every other `employee_assignment`
field already follows (ADR-0003, `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part B7) — no new rule,
no special case:

**Worked example** (the brief's own scenario):

```
Jan 1 ──────────────── Mar 31   effective_from=2026-01-01  effective_to=2026-03-31  shift=General
Apr 1 ────────────────────────> effective_from=2026-04-01  effective_to=NULL         shift=Night
```

To produce this: `POST .../assignments` with `effective_from="2026-04-01"`,
`change_type="SHIFT_CHANGE"`, `shift_id=<night-shift-id>`, `If-Match: <version of the Jan-1 row>`.
`create_assignment` (§2.4 step 5/7):
1. Reads the current row (`effective_from=2026-01-01, effective_to=NULL`).
2. Validates `2026-04-01 > 2026-01-01` (passes).
3. Closes the current row: `UPDATE ... SET effective_to = '2026-03-31'` (i.e.
   `new.effective_from - 1 day`), version-gated by `If-Match`.
4. Inserts a new row: `effective_from='2026-04-01', effective_to=NULL, shift_id=<night>`, every
   other field carried forward unchanged from the closed row (branch/department/designation/
   grade/managers/cost_centre/work_location_type all identical to the Jan-1 row).
5. Both steps happen in one transaction; the GiST exclusion constraint is the race-condition
   backstop, exactly as for any other assignment change.

Confirms every sub-question the brief raises:
- **Existing assignment is automatically closed**: yes, by the same `close_assignment` call every
  other change type already uses.
- **A new row is created**: yes, always — there is no "shift-only patch" path; ADR-0003 forbids
  editing a row's business columns in place.
- **`effective_from` is the boundary; `effective_to` is calculated**: yes —
  `effective_to = new.effective_from - timedelta(days=1)` (service.py:705), unchanged mechanism.
- **Overlapping assignments prevented only by the DB constraint?** No — prevented by both an
  application-level check (`effective_from` must be strictly after the current row's) *and* the
  GiST exclusion constraint as a structural backstop. Both layers already exist; E-05 adds nothing
  here.
- **Same-day replacement**: not permitted — `effective_from` must be strictly greater than the
  current row's `effective_from` (`422 INVALID_EFFECTIVE_FROM` otherwise), same rule that already
  applies to every other change type. No document proposes a shift-specific exception.
- **Historical assignments edited?** Never — no `PATCH`/`DELETE` on an individual row exists or is
  proposed for E-05.

---

## 10. Rehire Behavior

Uses the already-locked E-03/E-04 rehire model verbatim — **E-05 introduces no shift-specific
rehire logic**, because none is warranted: `shift_id` is just one more field on the same row the
existing rehire mechanism already governs.

- **First hire**: the employee's first-ever assignment row is the "no current row" branch of
  `create_assignment` — `shift_id` optional, same as every other non-mandatory field.
- **Termination**: `EmploymentService.terminate_employment` (E-03) does **not** touch
  `employee_assignment` at all — confirmed by `12_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_REPORT.md
  §12/§17` item 1: the pre-exit assignment row (including whatever `shift_id` it carries) is
  **not** auto-closed on termination. It remains open (`effective_to IS NULL`) through the entire
  gap between employment episodes. This is a documented, already-shipped, already-known
  limitation of E-04 — not something E-05 needs to fix or is in scope to fix.
- **Rehire**: mechanically identical to first hire — "no special-case code exists" is a direct
  quote from `10_EMPLOYEE_ASSIGNMENT_MODULE.md §5`. The rehire's first `create_assignment` call
  finds the (still-open, pre-exit) row as its "current" row, and — because it *is* a current row
  from the service's point of view — follows the "has current row" branch: `If-Match` is required,
  and the pre-exit row is closed at `rehire.effective_from - 1 day` (not the original exit date —
  a documented data-quality imprecision, `12_..._REPORT.md §12`, unrelated to shift specifically).
- **First assignment after rehire — is shift carried forward?** By the existing carry-forward
  rule: if the rehire's `create_assignment` request omits `shift_id`, it carries forward from the
  (years-stale) pre-exit row's `shift_id` — same as branch/department/designation would also
  carry forward if omitted. **No document states this is desired** for shift specifically (a
  five-year-old shift assignment silently reappearing on rehire may not be the intended outcome),
  but this plan does not invent a shift-specific override of the carry-forward rule, because doing
  so would make `shift_id` behave inconsistently with every other field on the same rehire path
  for no documented reason. **Flagged as a known risk (§19), not resolved here** — the correct fix,
  if one is wanted, is an HR-workflow-level expectation that a rehire's first assignment call
  explicitly re-sets every field including `shift_id`, not a code-level special case for shift
  alone.

---

## 11. API Changes

### 11.1 `POST /v1/employees/{employee_id}/assignments`

No path change. Request/response body changes only:

- `AssignmentCreate` gains `shift_id: UUID | None = None`.
- `AssignmentChangeType` gains `"SHIFT_CHANGE"` as a fifth literal value.
- `AssignmentRead` gains `shift_id: UUID | None`.
- New `422 INVALID_SHIFT` error code: "Reference does not exist, is soft-deleted, or belongs to
  another tenant" — same shape/semantics as `INVALID_BRANCH`/`INVALID_GRADE`/etc.
  (`11_EMPLOYEE_ASSIGNMENT_API.md`'s existing error table gains one row).

### 11.2 `GET /v1/employees/{employee_id}/assignments` / `.../{assignment_id}`

No change beyond the new `shift_id` field appearing in `AssignmentRead` responses (including in
`?as_of=` results) — both routes already return whatever `assignment_to_read` produces.

### 11.3 Reconciling `docs/product/09_API_Standards.md §3.2`'s combined `POST /employees` example

That document's example request nests `"shift_id"` inside an `assignment` sub-object of a single
combined `POST /employees` call that creates identity + employment + assignment + compensation +
statutory in one request. **This combined-create endpoint does not exist in the shipped codebase**
— E-01 through E-04 (and this plan for E-05) all use the sub-resource pattern
(`POST /employees`, then separately `POST /employees/{id}/assignments`, etc.), which
`03_EMPLOYEE_API_PLAN.md §2.2` documents as the actual, shipped API shape. This is a pre-existing
divergence between an early product-level sketch and the module-level API plan that governs actual
implementation — not something E-05 introduces or needs to resolve; E-04's own implementation
already made this same choice for every other assignment field, and E-05 follows it for
consistency. Flagged here so it isn't mistaken for a new conflict.

### 11.4 No query/filter behavior change

`GET .../assignments` still supports only `?as_of=YYYY-MM-DD` — no `shift_id`-specific filter is
requested by any source, and no other list endpoint in this module supports field-value filtering
either.

---

## 12. Permission/RBAC Changes

**No new permission code.** This is the one point where two authoritative documents genuinely
disagree, resolved here explicitly rather than silently picking one:

- `02_EMPLOYEE_DATA_MODEL.md §2` section E lists shift_id's "Edit" permission as `EMPLOYEE.UPDATE`.
- `00_EMPLOYEE_AUDIT.md §16`'s slice table, describing E-05 specifically (not a general field-
  permission matrix, but the actual per-slice implementation summary), says permissions
  "(folds into `.TRANSFER`)".

**Resolution: `EMPLOYEE.TRANSFER`**, for three converging reasons, not just a coin flip:
1. It is the more specific source — a dedicated per-slice implementation-summary row about E-05,
   versus a general field-attribute table compiled before E-04's actual write-permission design
   (the dynamic `change_type`-selects-permission mechanism) existed in code.
2. It is what the **already-shipped code** does automatically, with zero additional code: the
   `EMPLOYEE_PROMOTE if change_type == "PROMOTION" else EMPLOYEE_TRANSFER` branch (§6.6) already
   routes a new `SHIFT_CHANGE` value to `EMPLOYEE_TRANSFER` the moment the `Literal` type is
   extended — no router change is required. Choosing `EMPLOYEE.UPDATE` instead would require
   introducing a *third* branch to a mechanism E-04 deliberately built as binary, a larger and
   less-precedented change for a permission no code path currently checks on this endpoint at all
   (`EMPLOYEE.UPDATE` is used elsewhere in the module — e.g. `PATCH /employees/{id}` — but never on
   the assignment-write endpoint today).
3. `EMPLOYEE.TRANSFER`'s catalogue description is "Transfer an employee's branch, department, or
   manager" (`permissions.py:37`) — narrower than "shift" literally, but `EMPLOYEE.PROMOTE`'s
   description ("Promote an employee's designation or grade") is equally narrow relative to what it
   already gates (grade *and* designation together), so this is consistent with how the catalogue's
   existing descriptions are already treated as illustrative, not exhaustive, allow-lists.

This is flagged as a **recommendation resolving a genuine documentation conflict**, not a
rubber-stamp of a single unambiguous source — a product owner could reasonably prefer
`EMPLOYEE.UPDATE` instead, in which case the router's binary branch would need to become a
three-way dispatch. If that preference exists, it should be stated before implementation begins
(see §22).

**Read-side**: `EMPLOYEE.VIEW` continues to gate both `GET` routes, unchanged — `02_EMPLOYEE_DATA_
MODEL.md §2` section E's "View: `EMPLOYEE.VIEW`" cell is not in conflict with anything and needs
no resolution.

**`ORG.SHIFT.MANAGE`** (the Shift Rules module's own permission) is untouched and irrelevant to
E-05 — it gates managing the shift *master* (`/v1/shifts/*`), a completely separate capability from
assigning an existing shift to an employee, which is what E-05 does.

---

## 13. Audit Requirements

**No new audit action.** Confirmed by `00_EMPLOYEE_AUDIT.md §16`'s own row: "(folds into
`ASSIGNMENT_CHANGED`, `change_type=SHIFT_CHANGE`)". E-05 reuses the single `ASSIGNMENT_CHANGED`
action E-04 already emits for every assignment write, exactly the same posture the audit
recommended for the whole module (`00_EMPLOYEE_AUDIT.md §13.4`: one event, change_type carried in
the snapshot, not fragmented into per-change-type action strings).

- **Action name**: `ASSIGNMENT_CHANGED` (unchanged).
- **Entity type**: `"employee_assignment"` (unchanged).
- **Before/after snapshot**: `AssignmentRead.model_dump(mode="json")` — because this is already
  generic (§2.4), `shift_id` appears in both `before` and `after` snapshots automatically the
  moment it's added to `AssignmentRead`, with zero additional code in `assignment_to_audit_dict`.
- **Old/new shift**: visible via `before.shift_id` vs `after.shift_id` in the same snapshot pair
  every other field change is already visible through — no separate "old shift"/"new shift" audit
  field is needed or proposed.
- **Effective date**: `after.effective_from` (unchanged mechanism).
- **Actor**: `actor_user_id` from `tenant.user_id`, passed through unchanged.
- **Tenant**: `company_id`, passed through unchanged; RLS + belt-and-suspenders filtering already
  cover this at read time.

---

## 14. Frontend Scope

**E-05 is backend-only.** Verified directly:

- `apps/web/src/app/app/` contains **no Employee, Employee Assignment, or Employee Directory
  routes at all** — only `apps/web/src/app/app/shifts/` (list + detail pages for the Shift
  *master* CRUD, i.e. `/v1/shifts`, not assignment) exists, alongside the organisation module's
  other entity pages (company/legal-entity/branch/department/designation/grade).
- E-04's own implementation report confirms zero `apps/web/` changes were made for Employee
  Assignment (`12_..._REPORT.md §18`: "No frontend changes — `apps/web/` is untouched").
- The Employee Directory/360° profile UI, including any shift picker, is E-09's scope
  (`00_EMPLOYEE_AUDIT.md §16` slice table) — a slice that has not started.

There is no Employee UI, no Assignment UI, and no shift picker to extend, and none should be
invented for E-05. This matches the task brief's own instruction not to create frontend
architecture that doesn't exist yet, and matches E-04's own precedent exactly (backend-only slice,
frontend deferred to E-09).

---

## 15. Test Plan

No tests are written by this task. The plan below extends E-04's existing test files
(`apps/api/tests/unit/modules/employee/test_employee_assignment_service.py` and
`apps/api/tests/integration/modules/employee/test_employee_assignment.py`) rather than creating
new files — E-05 adds fields/behavior to the same entity E-04 already tests exhaustively, so
extending is more consistent than a parallel new file, unlike E-04 itself (which introduced a
wholly new entity and rightly got its own files).

### 15.1 Unit tests (service layer, mocked repositories)
- First assignment with `shift_id` set → succeeds, `shift_id` persisted.
- First assignment with `shift_id` omitted → succeeds, `shift_id` is `NULL`.
- `SHIFT_CHANGE` with only `shift_id` set on a current-row-exists employee → every other field
  carries forward unchanged; new row's `change_type == "SHIFT_CHANGE"`.
- `shift_id` omitted on a `TRANSFER`/`PROMOTION`/`MANAGER_CHANGE` request with a current row →
  carries forward from the current row.
- Invalid/nonexistent `shift_id` → `InvalidShiftReferenceError` (`422 INVALID_SHIFT`), mocked
  `OrganisationService.get_shift` raising `NotFoundError`.
- `shift_id = None` explicitly (vs. omitted) on an update — confirm `None` is *not* treated as "no
  change" incorrectly if Pydantic's `exclude_unset`/`model_fields_set` semantics matter here (mirror
  whatever E-04's existing tests already do for `grade_id`/`cost_centre_id` to confirm the same
  omitted-vs-explicit-null distinction holds for `shift_id`).

### 15.2 Integration tests (real Postgres, real HTTP)
- `POST .../assignments` with `change_type="SHIFT_CHANGE"`, valid `shift_id` → `201`, response
  includes `shift_id`; a subsequent `GET` returns it; the previous row is closed with the correct
  `effective_to`.
- `POST .../assignments` referencing a `shift_id` from another tenant → `422 INVALID_SHIFT`, not a
  cross-tenant leak (mirrors `test_cannot_reference_other_tenant_branch` exactly).
- `POST .../assignments` referencing a nonexistent `shift_id` → `422 INVALID_SHIFT`.
- `POST .../assignments` referencing a **deactivated** (`is_active=false`) but still-existing,
  same-tenant `shift_id` → succeeds (`201`) per §7.4's recommendation — a test asserting the
  documented precedent-consistent behavior, not asserting a rejection.
- Effective-dating boundary test mirroring `test_list_assignments_as_of_date_boundaries`, using the
  brief's own Jan-1/Apr-1 General→Night worked example (§9) — confirms `?as_of=2026-02-01` returns
  General, `?as_of=2026-05-01` returns Night, `?as_of=2026-03-31` returns General (inclusive
  boundary), `?as_of=2026-04-01` returns Night (inclusive boundary).
- Overlap test: attempt (via the same raw-SQL-bypass technique
  `test_raw_overlapping_insert_rejected_at_database_level` already uses) to insert two overlapping
  rows differing only in `shift_id` → GiST exclusion constraint still rejects, proving the
  constraint is keyed on `(employee_id, daterange)` only and is indifferent to which columns
  differ.
- Permission-matrix tests, mirroring E-04's existing pair exactly: caller with no `.TRANSFER` at
  all attempting `change_type="SHIFT_CHANGE"` → `403`; caller with only `.PROMOTE` (no
  `.TRANSFER`) attempting `change_type="SHIFT_CHANGE"` → `403` (confirms `SHIFT_CHANGE` really did
  fall into the `.TRANSFER` branch, not `.PROMOTE`).
- Rehire scenario extended: give the pre-exit assignment a `shift_id`; after the rehire gap, assert
  the rehire's first assignment — if it omits `shift_id` — carries forward the years-stale
  `shift_id` from the pre-exit row (documenting §10's flagged behavior explicitly, not leaving it
  implicit).
- Mass-assignment test: `shift_id` sent alongside an unknown/forbidden field → `422` (existing
  `extra="forbid"` behavior, confirms it still holds with the new field present).
- Audit test: `SHIFT_CHANGE` assignment write produces one `ASSIGNMENT_CHANGED` audit row whose
  `after` snapshot contains the new `shift_id` and whose `before` snapshot contains the prior
  row's `shift_id` (or `null` for a first assignment).
- Cross-tenant `GET` test: existing `test_cannot_get_assignment_from_other_tenant` should be
  re-run/extended to confirm `shift_id` doesn't leak in a cross-tenant 404 response body (it
  shouldn't, since the whole response is suppressed, but worth an explicit assertion given
  `shift_id` is new).

### 15.3 Concurrency tests
- `If-Match` stale-version conflict on a `SHIFT_CHANGE` request — mirrors the existing
  `STALE_RESOURCE` test exactly, confirming the version-gate is field-agnostic (already true by
  construction, since `close_assignment` doesn't inspect which fields are changing).

### 15.4 What this test plan deliberately does not add
- No test asserting a BR-14 cascading default resolves when `shift_id IS NULL` — no such mechanism
  exists or is being built (§1).
- No test asserting shift deactivation is blocked by an active assignment reference — no such rule
  is being built (§7.6).
- No Attendance-side test of any kind (grace/late/OT/cross-midnight) — Attendance doesn't exist.

---

## 16. Security/Tenant Isolation

No new tenant-isolation surface is introduced — `shift_id` is validated through the same
`OrganisationService.get_shift(company_id, shift_id)` call every other reference field already
uses, which is already company-scoped and already returns `404`/`NotFoundError` (never a leak) for
a cross-tenant id. RLS on both `employee_assignment` and `shift` is unchanged and already forced.
The one new thing to verify (not build) is that the `422 INVALID_SHIFT` error path, like
`422 INVALID_BRANCH` etc. before it, never distinguishes "doesn't exist" from "exists in another
tenant" in its message or response shape — both must be indistinguishable to the caller, exactly
as `InvalidBranchReferenceError`'s existing generic message already is.

Mass-assignment protection is inherited unchanged: `AssignmentCreate`'s `extra="forbid"` already
rejects unknown fields; adding `shift_id` as a named, typed field is the opposite of a mass-
assignment risk — it's the deliberate, reviewed alternative to leaving it open-ended.

---

## 17. Error Handling

| HTTP | Code | Cause | Precedent |
|---|---|---|---|
| `422` | `INVALID_SHIFT` | `shift_id` does not exist, is soft-deleted, or belongs to another tenant | Identical shape to `INVALID_BRANCH`/`INVALID_DEPARTMENT`/`INVALID_DESIGNATION`/`INVALID_GRADE` |
| `422` | (FastAPI validation) | `shift_id` is not a valid UUID | Pydantic type validation, unchanged mechanism |
| `422` | `ASSIGNMENT_FIELDS_REQUIRED` | Unaffected — `shift_id` is never in the mandatory-at-first-placement set | No change |
| `409` | `NO_ACTIVE_EMPLOYMENT` | Unaffected — same covering-employment check runs regardless of which fields are set | No change |
| `409` | `ASSIGNMENT_DATES_OVERLAP` | Unaffected — GiST constraint is field-agnostic | No change |
| `403` | `PERMISSION_DENIED` | Caller lacks `EMPLOYEE.TRANSFER` (§12) when `change_type="SHIFT_CHANGE"` | Same mechanism as every other non-`PROMOTION` change |

No new error-handling *mechanism* is introduced — one new error *instance* (`INVALID_SHIFT`)
following the exact existing pattern.

---

## 18. Explicit Non-Goals

E-05 does **not** implement, and no authoritative source places inside E-05:

- **Attendance** — punches, `attendance_day`, grace/late/OT computation, shift-based day
  attribution. Confirmed out of scope by `00_SHIFT_RULES_AUDIT.md §3.4`; Attendance doesn't exist
  as a module.
- **Leave, Payroll, Compensation, Statutory, Banking** — untouched; no source places any of these
  inside E-05.
- **Employee Directory** — E-09's scope, not started (§14).
- **BR-14 / FR-EMP-018 override chain** — explicitly, repeatedly deferred by every source that
  discusses it (`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part A3/B8/G1, `00_SHIFT_RULES_AUDIT.md
  §3.1`, `00_EMPLOYEE_AUDIT.md §16`'s own E-05 row). No `default_shift_id` column is added to
  Branch, Department, Designation, or Grade.
- **Workflow automation / approval routing** — no approval gate on a shift change; matches E-04's
  own precedent for transfer/promotion (`FR-EMP-013` reassignment-of-pending-approvals is likewise
  not built for manager changes).
- **Roster/scheduling engine, shift rotation engine** (`shift_roster`/`shift_rotation_pattern`) —
  explicitly named as Attendance-module, Sprint-7-era concerns by `01_Shift_Rules_Module.md §2`
  and `00_SHIFT_RULES_AUDIT.md §3.4`.
- **Shift deactivation-blocking on active assignment reference** — explicitly deferred, §7.6.
- **Any change to the Shift Rules module itself** (`organisation/models.py::Shift`,
  `organisation/service.py`, `/v1/shifts/*`) — E-05 only reads it via the existing `get_shift`
  method; no field, validation rule, or endpoint on Shift changes.
- **`shift_type`/flexible/split-shift support, `week_off_pattern_id`, OT computation itself** — none
  of these exist on `Shift` today (`00_SHIFT_RULES_AUDIT.md §6.7`) and E-05 has no reason to add
  them; they are unrelated to the assignment relationship E-05 builds.
- **A combined single-request `POST /employees` that nests `assignment.shift_id`** — the sub-
  resource pattern (§11.3) is what E-01 through E-04 already ship; E-05 does not introduce the
  combined-create endpoint `docs/product/09_API_Standards.md §3.2` sketches.

---

## 19. Known Risks/Gaps

1. **Rehire carry-forward of a stale `shift_id`** (§10) — a rehire's first assignment, if it omits
   `shift_id`, silently carries forward a shift that may be years out of date and organizationally
   meaningless (the shift itself may since have been deactivated or repurposed). No document states
   the desired behavior; this plan does not special-case it, since doing so would make `shift_id`
   inconsistent with how every other carried-forward field already behaves on the same rehire path.
   Flagged for product input, not silently resolved.
2. **Permission conflict** (§12) — `02_EMPLOYEE_DATA_MODEL.md` says `EMPLOYEE.UPDATE`; this plan
   recommends `EMPLOYEE.TRANSFER`. If a reviewer disagrees, the router's binary permission-
   selection branch needs to become a three-way dispatch before implementation, which is a larger
   change than the rest of this plan.
3. **Inactive-shift assignment is permitted** (§7.4) — by design, following existing precedent, but
   worth restating as a deliberate choice: nothing stops an HR user from assigning a deactivated
   shift to an employee today (and, by the same precedent, nothing stops assigning a deactivated
   Branch/Department/Designation/Grade either — this is not a shift-specific gap).
4. **No deactivation-blocking on `Shift`** (§7.6) — once E-05 ships, `Shift` becomes a genuinely
   referenced entity for the first time, but its deactivation path still performs no reference
   check. This mirrors the FR-ORG-014 gap A5 already accepted for Branch/Department/Designation/
   Grade and defers it the same way, but the accumulated blast radius (five org-structure entities
   plus now Shift, all deactivable with no active-reference check) is worth surfacing to product as
   a cross-cutting item, not just an Employee-module footnote.
5. **`employee_assignment_shift_id_fkey`'s `ON DELETE SET NULL` is effectively untested in
   practice** (§7.2) — because nothing hard-deletes a `Shift` row today, this code path has no
   natural trigger; if a future admin/data-cleanup tool ever adds hard deletion of shifts, this
   clause's behavior (silently nulling historical assignments' `shift_id`) should be re-reviewed
   against whether that's still the desired outcome for *historical* rows specifically.
6. **BR-14 temptation, restated** — `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part H item 6 already
   named this risk for E-04; it applies equally to E-05, arguably more so, since E-05 is the slice
   that makes `shift_id` a real, settable value for the first time, which is exactly the moment the
   temptation to "just add the cascading default while we're here" is strongest. Resist it — it
   remains a separate, later, cross-module decision.

---

## 20. Implementation Sequence

1. **Migration** — add `shift_id` column + FK to `employee_assignment` (§7.1).
2. **Model** — add `shift_id` field to `EmployeeAssignment` ORM class; update/remove the stale
   docstring sentence (§6.1).
3. **Exceptions** — add `InvalidShiftReferenceError` (§6.4).
4. **Schemas** — extend `AssignmentChangeType` Literal, add `shift_id` to `AssignmentCreate`/
   `AssignmentRead`, update `assignment_to_read` (§6.2).
5. **Service** — add `_assert_shift_ownership`, extend the carry-forward logic and the
   `insert_assignment` data dict in `create_assignment` (§6.5).
6. **Router** — no change; verify (don't modify) that the existing permission-selection line
   behaves as expected for `SHIFT_CHANGE` (§6.6/§12).
7. **Tests** — extend `test_employee_assignment_service.py` and `test_employee_assignment.py` per
   §15.
8. **Validation** — `ruff check`, `ruff format --check`, `mypy src/hrms`, `lint-imports`, full
   `pytest` run (matches E-04's own closeout checklist, `12_..._REPORT.md §16`).
9. **Documentation** — companion module-reference and API-reference doc updates (mirroring
   `10_EMPLOYEE_ASSIGNMENT_MODULE.md`/`11_EMPLOYEE_ASSIGNMENT_API.md`'s own pattern, either as
   updates to those two documents or new sibling documents) plus a closeout implementation report
   (mirroring `12_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_REPORT.md`'s shape) — out of scope for *this*
   investigation task, but the next task's expected deliverable.

No step depends on frontend work (none exists to depend on, §14) and no step depends on a product
decision **except** step 5's permission choice if §12's recommendation is not accepted as-is.

---

## 21. Validation Checklist

For the implementation task that follows this plan:

- [ ] `shift_id` column exists on `employee_assignment`, nullable, FK to `shift.id`, `ON DELETE
      SET NULL`.
- [ ] No column, index, or constraint was added beyond what §6/§7 specify (no speculative
      `shift_id`-keyed index, no cross-table CHECK constraint).
- [ ] `EmployeeAssignment.shift_id` present on the ORM model; stale docstring sentence removed.
- [ ] `AssignmentChangeType` includes `"SHIFT_CHANGE"` as a fifth value.
- [ ] `AssignmentCreate`/`AssignmentRead` both carry `shift_id`; `extra="forbid"` still holds.
- [ ] First assignment: `shift_id` optional, not in the mandatory set.
- [ ] Subsequent assignment: `shift_id` carries forward when omitted, from any `change_type`, not
      just `SHIFT_CHANGE`.
- [ ] `_assert_shift_ownership` implemented, mirrors `_assert_grade_ownership` exactly; existence +
      tenant-scope only, no `is_active` check.
- [ ] `InvalidShiftReferenceError` / `422 INVALID_SHIFT` wired end-to-end (service raises, router
      surfaces, matches the shape of the other four `Invalid<Entity>ReferenceError` classes).
- [ ] No router change was required — confirm the existing permission-selection line already
      handles `SHIFT_CHANGE` correctly (routes to `EMPLOYEE.TRANSFER`) with zero modification.
- [ ] No new permission code was added.
- [ ] No new audit action was added — `ASSIGNMENT_CHANGED` continues to fire, `shift_id` appears in
      `before`/`after` automatically.
- [ ] No `apps/web/` file touched.
- [ ] No `organisation/` file touched beyond nothing (Shift Rules is consumed read-only via its
      existing `get_shift` method).
- [ ] No BR-14 column, table, or resolution logic added anywhere.
- [ ] Full backend test suite passes (424 pre-existing + new E-05 tests); `ruff`/`mypy`/
      `lint-imports` all clean.
- [ ] Cross-tenant shift reference returns `422 INVALID_SHIFT`, never a `200` or a distinguishable
      "exists elsewhere" signal.
- [ ] Deactivated-but-existing same-tenant shift reference succeeds (per §7.4's recommendation) —
      explicitly tested, not just untested-and-assumed.
- [ ] Rehire scenario test extended to document (not silently pass over) the stale-`shift_id`-
      carry-forward behavior (§10/§19 item 1).

---

## 22. Exact Next Implementation Task

**READY** — E-05 can proceed directly to implementation with no blocking product decision, subject
to one explicit confirmation:

> **Confirm before starting**: does `EMPLOYEE.TRANSFER` (this plan's recommendation, §12) correctly
> gate a pure `SHIFT_CHANGE` write, or should it require `EMPLOYEE.UPDATE` instead (per
> `02_EMPLOYEE_DATA_MODEL.md`'s literal field-permission cell)? If `EMPLOYEE.UPDATE` is preferred,
> the router's permission-selection line must become a three-way dispatch instead of the current
> binary one — flag this to whoever picks up implementation so it isn't silently decided either
> way.

Everything else in this plan — the column, the FK, the carry-forward behavior, the effective-
dating mechanics, the audit reuse, the frontend exclusion, the BR-14 exclusion — is settled by
convergent documentation and by direct extension of E-04's already-shipped, already-tested
pattern. The next task should implement exactly §6/§7 (data model + migration), §11 (API), and
§15 (tests), in the sequence given in §20, and produce a closeout report mirroring
`12_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_REPORT.md`'s shape.
