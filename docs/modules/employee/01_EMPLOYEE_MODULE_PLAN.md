# Employee Module — Implementation Plan

Companion to `00_EMPLOYEE_AUDIT.md`. This document proposes the vertical-slice sequence for
building Employee, and the readiness checklist Attendance needs before it can be built without
redesigning Employee. **No code is written as part of this plan** — it is the recommended
sequencing for a future implementation task, to be reviewed alongside the audit's decisions list
(`00_EMPLOYEE_AUDIT.md §15`) before any slice begins.

---

## 1. Module boundary

Per `docs/architecture/01_Backend_Structure.md:70` and `docs/product/VERSION_1_ROADMAP.md §8` item
3, Employee is its own package — `apps/api/src/hrms/modules/employee/` — not folded into the
existing `organisation` package the way Company/Legal Entity/Branch/Department/Designation/Grade/
Shift all are. This is confirmed by two independent documents and should be treated as settled
unless product says otherwise (`00_EMPLOYEE_AUDIT.md §15.8`). It follows the same
`router.py`/`service.py`/`repository.py`/`models.py`/`schemas.py`/`permissions.py`/`events.py`/
`exceptions.py`/`dependencies.py` shape mandated by `docs/architecture/02_Module_Standard.md`.

Cross-module imports: Employee's `service.py` is the only surface Attendance/Leave/Payroll may
import (`other_module.service`), never `employee.repository` or `employee.models` — enforced by
the same import-linter convention already governing the organisation module.

---

## 2. Vertical-slice sequence

Sequencing rule: each slice should be independently shippable and testable, and later slices
should not require re-migrating tables an earlier slice already built — this mirrors how
Designation/Grade were sequenced (Designation before Grade, then a small follow-up migration to
connect them) rather than trying to build the whole aggregate in one migration.

### E-01 — Employee foundation (identity + module scaffold)
- **Backend**: `employee/` package scaffold; `Employee` ORM model (extends the live `employee`
  stub, `02_EMPLOYEE_DATA_MODEL.md §3`); `EmployeeService`/`EmployeeRepository` with
  create/get/list/deactivate/reactivate, following the organisation module's soft-deactivate +
  optimistic-concurrency pattern exactly.
- **Database**: migration extending `employee` per `02_EMPLOYEE_DATA_MODEL.md §3`; FK constraints
  re-asserted; RLS re-asserted idempotently; `EMPLOYEE_CODE` number-series allocator built (the
  documented-but-missing `number_series` table + `allocate_next_number()`, `00_EMPLOYEE_AUDIT.md
  §1.4/§15.7`) — this is a genuine new-infrastructure item, not a copy of an existing pattern.
- **API**: `GET/POST /v1/employees`, `GET/PATCH/DELETE /v1/employees/{id}` (identity fields only —
  no employment/assignment yet, since those don't exist until E-03/E-04). *(Note: a standalone
  employee with no employment is not a realistic real-world state — E-01 and E-03 are likely to
  ship together in practice; kept separate here only to isolate the number-series/seat-limit
  infrastructure from the effective-dating infrastructure.)*
- **Frontend**: none yet — first usable screen ships with E-09.
- **Tests**: unit (service validation, seat-limit enforcement), integration (CRUD, RLS, cross-
  tenant isolation, code uniqueness/generation race-safety per AC-ORG-011.1's concurrent-creation
  acceptance criterion).
- **Dependencies**: none beyond already-shipped Organisation (branch/department/designation/grade
  exist as FK targets).
- **Risks**: number-series race-safety (`UPDATE...RETURNING`, never `SELECT max()+1` — Doc 08
  §4's explicit warning) is easy to get wrong under concurrent creation; `EMPLOYEE_SEATS`
  enforcement point needs product confirmation (`00_EMPLOYEE_AUDIT.md §15.6`) before this slice's
  create path is final.

### E-02 — Employee identity/profile completion
- **Backend**: full identity field set (§02 data model §A), `employee_address`,
  `employee_emergency_contact` tables/service methods; profile-change-request workflow (FR-EMP-009
  — controlled vs uncontrolled field distinction).
- **Database**: `employee_address`, `employee_emergency_contact` new tables (not effective-dated).
- **API**: PATCH for uncontrolled fields direct; `POST /profile-change-requests` for controlled
  fields.
- **Frontend**: Profile tab (`04_EMPLOYEE_UX_PLAN.md §2`).
- **Tests**: field-controllability enforcement, PII masking in responses.
- **Dependencies**: E-01.
- **Risks**: field-controllability list (which fields are "controlled") is named only by example
  in FR-EMP-009 ("name, DOB, bank, PAN, address") — needs a definitive, complete list before
  implementation, not an inferred one.

### E-03 — Employment lifecycle
- **Backend**: `Employment` ORM model (extends the live stub); status state-machine (FR-EMP-014,
  10 states, transitions enforced); confirmation/probation workflow (FR-EMP-010); exit-initiation
  hook (thin — full Exit module is a later, separate build per the roadmap, this slice only needs
  `employment.status → EXITED` and `last_working_day` to be settable).
- **Database**: migration extending `employment` (§02 data model §3) — including `is_rehire`/
  `previous_employment_id`, required for E-03 to support §3's rejoin scenario at all.
- **API**: employment fields folded into `POST /v1/employees` (nested `employment{}`); a rehire
  creates a new `employment` row against an existing `employee_id` — needs its own explicit
  entry point, not just `POST /v1/employees` (which today implies a brand-new employee) —
  **proposed but not settled**: `POST /v1/employees/{id}/employments` for the rehire case,
  pending confirmation this is the right shape.
- **Frontend**: Job tab's employment sub-section; rejoin-detection UX (`04_EMPLOYEE_UX_PLAN.md
  §5`) — deferred within this slice until `00_EMPLOYEE_AUDIT.md §15.1` is decided.
- **Tests**: state-machine transition matrix (valid/invalid transitions), rehire scenario
  end-to-end (exit → 5-year gap → rehire → both employment rows queryable under one
  `employee_id`) — this is the acceptance test for the brief's central scenario.
- **Dependencies**: E-01. **Blocks nothing downstream if `employment.status` value-set ambiguity
  (`00_EMPLOYEE_AUDIT.md §14` row 3) isn't resolved first — but should be resolved before this
  slice starts, since it's this slice's own primary table.**
- **Risks**: this is where the rejoin decision (§15.1) and the `employment.status` value-set
  decision (§14 row 3) must both be settled — starting E-03 before either is confirmed risks a
  second migration.

### E-04 — Employee assignment (org placement + reporting line)
- **Backend**: `EmployeeAssignment` ORM model; the as-of-date read helper
  (`02_EMPLOYEE_DATA_MODEL.md §1.3`) as a shared service method; transfer/promotion/manager-change
  workflows (FR-EMP-011/012/013), each an insert-a-new-row operation, never a column update.
- **Database**: migration extending `employee_assignment` (§02 data model §3) — adds
  `dotted_line_manager_id`, `cost_centre_id`, `work_location_type`, `change_reason`, `change_type`,
  and the FK constraints currently missing (`00_EMPLOYEE_AUDIT.md §14` row 8). **Does not add
  `shift_id`** in this slice — that's E-05, kept separate so Shift's own dependency is explicit and
  reviewable on its own.
- **API**: `GET/POST /v1/employees/{id}/assignments` (§03 API plan §2.2).
- **Frontend**: Job tab's assignment history + transfer/promotion workflow screens
  (`04_EMPLOYEE_UX_PLAN.md §4`); Org chart screen (reporting-tree visualization).
- **Tests**: GiST exclusion-constraint verification (attempt to insert an overlapping row, expect
  a DB-level rejection, not just an application-level check), as-of-date query correctness against
  the brief's own worked example (2027 vs 2029 assignment), manager-reassignment cascading to
  pending approvals (FR-EMP-013 — thin until the approval-routing engine exists).
- **Dependencies**: E-01, E-03 (an assignment implies an employment exists).
- **Risks**: this is the first effective-dated table Employee's application code actually writes
  to — the insert/close-row transaction pattern (`02_EMPLOYEE_DATA_MODEL.md §1.2`) has no
  precedent anywhere else in the codebase to copy; budget extra review time here specifically.

### E-05 — Shift assignment
- **Backend**: adds `shift_id` to `EmployeeAssignment` (separate migration from E-04, per
  `00_EMPLOYEE_AUDIT.md §7.3`'s recommendation to ship only the confirmed leg).
- **Database**: `ALTER TABLE employee_assignment ADD COLUMN shift_id`, FK to `shift(id)`.
- **API**: `shift_id` becomes a settable field on `POST /v1/employees/{id}/assignments`, with
  `change_type = SHIFT_CHANGE`.
- **Frontend**: shift field added to the transfer/assignment workflow screen.
- **Tests**: the `get_assignment_as_of` → `shift_id` contract Attendance needs (§00 §7.3/§9),
  verified end-to-end.
- **Dependencies**: E-04, Shift Rules module (already shipped).
- **Risks**: the BR-14 override-chain (company/branch/department/grade default shift resolution)
  is explicitly **not** built in this slice (`00_EMPLOYEE_AUDIT.md §15.3`) — an employee with no
  `shift_id` set has no shift, full stop, until that separate cross-module decision is made.
  Attendance consumers must handle a `null` shift_id, not assume one always resolves.

### E-06 — Compensation
- **Backend**: `EmployeeCompensation` ORM model extension, `employee_compensation_component` child
  table, revision workflow (FR-EMP-012's compensation-revision-in-promotion path, and standalone
  revision via E-03's separate endpoint).
- **Database**: migration extending `employee_compensation` (§02 data model §3).
- **API**: `GET/POST /v1/employees/{id}/compensation` (§03 API plan §2.3).
- **Frontend**: Compensation tab (`04_EMPLOYEE_UX_PLAN.md §2`, permission-gated absent).
- **Tests**: `EMPLOYEE.VIEW_COMPENSATION` gating (entire sub-resource absent without it, not just
  masked), arrears-relevant backdating behavior (best-effort until Payroll exists, §02 data model
  §1.4).
- **Dependencies**: E-01, E-03.
- **Risks**: `approval_request_id` implies an approval-routing dependency that doesn't exist yet
  (roadmap sequences approval routing *after* Employee, §00 §13) — this slice should store the
  field but cannot enforce an approval gate until that engine ships; ship without blocking, flag
  as a known gap in this slice's own closeout report.

### E-07 — Statutory information
- **Backend**: `EmployeeStatutory` new ORM model (new table, not extending a stub — none exists).
- **Database**: `CREATE TABLE employee_statutory` per `02_EMPLOYEE_DATA_MODEL.md §3`, same
  effective-dating pattern as assignment/compensation.
- **API**: `/v1/employees/{id}/statutory` — **flagged decision on verb** (`03_EMPLOYEE_API_PLAN.md
  §2.4`: doc says `PATCH`, ADR-0003 implies insert-only; recommend insert-only).
- **Frontend**: sub-section within Compensation tab pending a dedicated permission decision
  (`04_EMPLOYEE_UX_PLAN.md §2`).
- **Tests**: tax-regime once-per-FY switch rule (FR-PAY-006) — this rule belongs conceptually to
  Payroll but the *data* lives on Employee's table; the constraint should be enforced here since
  Employee owns the write path.
- **Dependencies**: E-01, E-03. **Blocks Payroll** (`00_EMPLOYEE_AUDIT.md §10`) if deferred.
- **Risks**: the view-permission gap (`02_EMPLOYEE_DATA_MODEL.md §2` section F) must be resolved
  before this ships, or the tab/endpoint has no confirmed access-control story.

### E-08 — Documents, dependents, education, experience, skills, banking
- **Backend**: `EmployeeDocument`, `EmployeeDependent`, `EmployeeEducation`, `EmployeeExperience`,
  `EmployeeSkill`, `EmployeeBank` new ORM models; document expiry-alert scheduling (FR-EMP-007's
  30/15/7-day alerts — depends on the notification engine, itself not yet built; store the dates,
  defer the alert firing).
- **Database**: `CREATE TABLE` for each, `employee_bank` using the effective-dating pattern
  (§02 data model §3), the rest as plain collections.
- **API**: §03 API plan §2.4/§2.5.
- **Frontend**: Documents tab, plus supporting sections within Profile.
- **Tests**: document verification workflow, bank-account masking, virus-scan hook (FR-EMP-007 —
  stub/interface only if no scanning service is wired up yet; flag as a known limitation rather
  than skip silently).
- **Dependencies**: E-01.
- **Risks**: virus scanning and expiry-alert notification are both named requirements with
  external-system dependencies not yet built elsewhere in the codebase — scope this slice to
  storage/CRUD and flag the alerting/scanning gap explicitly in its closeout report, per this
  audit's own "don't invent, flag gaps" discipline.

### E-09 — Employee directory / profile UI, bulk import/export, letters
- **Backend**: import/export job orchestration (Celery, per the existing `tasks.py` convention),
  letter-template rendering (11 non-offer templates, FR-EMP-016).
- **Database**: import batch/audit table if not covered by the generic audit log.
- **API**: §03 API plan §2.7/§2.8.
- **Frontend**: Directory (`docs/design/screens/01_Employee_List_Directory.md`, use as-is), Add-
  employee wizard (`04_EMPLOYEE_UX_PLAN.md §3`), bulk import flow, letter generation UI.
- **Tests**: dry-run all-or-nothing import (500-row file, 3 invalid rows → nothing committed,
  per AC-EMP-006.1), virtualized-list performance at 1,000+ rows.
- **Dependencies**: E-01 through E-08 (this is the consumption layer over the whole aggregate).
- **Risks**: the Directory spec's field-visibility/data-scope matrix (`00_EMPLOYEE_AUDIT.md
  §11.2/§11.3`) is the most detailed, most failure-prone part of this slice — a mistake here is a
  privacy leak, not a cosmetic bug; budget dedicated security review time.

### E-10 — Security / audit / integration hardening
- **Backend**: full 14-permission RBAC catalogue seeded and enforced (`00_EMPLOYEE_AUDIT.md
  §11.1`), `sensitive_access_log` (§00 §12, if scoped in), the `get_assignment_as_of`/
  compensation-as-of service methods finalized as the public contract Attendance/Leave/Payroll
  will import, FR-ORG-014 retrofit into Branch/Department/Designation/Grade
  (`00_EMPLOYEE_AUDIT.md §15.5` — a change to the *organisation* module, tracked here since it's
  Employee's existence that unblocks it, but implemented as its own small follow-up PR, not
  folded into E-01-E-09).
- **Database**: none new — this slice is enforcement/wiring, not schema.
- **API**: none new.
- **Frontend**: none new.
- **Tests**: full RBAC permission-matrix test (every role × every Employee endpoint), cross-tenant
  isolation suite (mirroring `test_cross_tenant_isolation.py`'s existing pattern), the G8-style
  acceptance walkthrough from `docs/product/VERSION_1_ROADMAP.md §3` adapted to Employee
  ("register → configure org → add 50 employees by import → confirm Attendance/Leave/Payroll's
  dependency contracts are satisfiable" — without those modules existing yet, this is a contract
  test against Employee's own service methods, not a full E2E).
- **Dependencies**: E-01 through E-09.
- **Risks**: this is the slice most likely to get compressed under schedule pressure since it adds
  no visible feature — treat it as non-optional given Employee's central-dependency role (per the
  brief's own framing).

---

## 3. What Employee must provide before Attendance can be built

Per the audit brief's Phase 15, this is the explicit readiness contract — Attendance implementation
should not require redesigning any of the following:

1. **`EmployeeService.get_assignment_as_of(employee_id, date) -> AssignmentRead | None`** —
   returns branch, department, shift_id, reporting_manager_id effective on a given date
   (`00_EMPLOYEE_AUDIT.md §9`, `02_EMPLOYEE_DATA_MODEL.md §1.3`). **Ships in E-04/E-05.**
2. **`employee.status` and `employment.status`, with a confirmed, enumerated value set for both**
   (`00_EMPLOYEE_AUDIT.md §14` row 3 must be resolved) — Attendance's status-resolution precedence
   ("Not joined/Exited > Approved leave > ...") reads these directly. **Ships in E-03**, blocked
   on the value-set decision.
3. **A deterministic answer to "does employee X have an active employment on date Y"** — derivable
   from `employment.joining_date`/`exit_date`/`status` once E-03 ships.
4. **`shift_id` on the current/as-of assignment row**, with a defined behavior for `null` (no
   default resolves) until the BR-14 override chain is a separate, later decision
   (`00_EMPLOYEE_AUDIT.md §15.3`) — Attendance must be built to tolerate `shift_id IS NULL`, not
   assume every employee always has a shift.
5. **Branch/work-location on the assignment**, for geofencing (FR-ATT-011) — `branch_id` ships in
   E-04; `work_location_type` (OFFICE/WFH/HYBRID/FIELD) also ships in E-04.
6. **A stable `employee_id` that survives rejoin** (`00_EMPLOYEE_AUDIT.md §3`) — so a rehired
   employee's new attendance records attach to the same identity as their pre-exit history,
   without Attendance needing any special-case logic for "this employee existed before."

Once E-01 through E-05 ship (with the §15.1/§15.3/§14-row-3 decisions resolved before E-03/E-05
start, not after), Attendance's own implementation can proceed against a stable contract. E-06
through E-10 (compensation, statutory, bank, documents, directory UI, hardening) are **not**
blocking for Attendance specifically, though E-10's RBAC/audit hardening should not be skipped
indefinitely just because Attendance doesn't need it — Leave and Payroll do (§00 §10).

---

## 4. Summary dependency graph

```
E-01 (foundation) ──┬──▶ E-02 (profile)
                     ├──▶ E-03 (employment) ──┬──▶ E-04 (assignment) ──┬──▶ E-05 (shift)
                     │                        │                        │
                     │                        └──▶ E-06 (compensation) │
                     │                                                 │
                     └──▶ E-07 (statutory) ◀── (needs E-03)            │
                     └──▶ E-08 (docs/dependents/bank)                  │
                                                                        ▼
                                                          E-09 (directory/UI/import) ◀── needs E-01..E-08
                                                                        │
                                                                        ▼
                                                          E-10 (security/audit hardening)

Attendance readiness (§3 above) = E-01 + E-03 + E-04 + E-05, with §00 §15.1/§15.3/§14-row-3 resolved.
```
