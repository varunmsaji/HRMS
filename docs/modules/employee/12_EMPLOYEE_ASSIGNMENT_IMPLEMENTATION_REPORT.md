# Employee Assignment (E-04) — Implementation Report

Closeout report for the Employee Assignment vertical slice, built per
`09_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_PLAN.md` (the investigation/plan that preceded this
task; no product decision blocked the plan, so no decision document was needed). Builds
directly on E-01 (Employee Foundation, COMPLETE) and E-03 (Employment Lifecycle, COMPLETE,
383/383 tests verified before this task started).

---

## 1. E-04 status

**COMPLETE**, for the scope authorized by the plan. `EmployeeAssignment` ORM model, repository,
service, router, schemas, exceptions, and permissions are all implemented; the migration is
applied and verified against the dev database; 41 new tests (20 unit + 21 integration) pass;
the full backend suite (424 tests) passes; `ruff check`, `ruff format --check`, `mypy
src/hrms`, and `lint-imports` all pass clean.

Shift assignment (E-05), Compensation (E-06), Statutory (E-07), Banking (E-08), the frontend
(E-09), and the RBAC/`sensitive_access_log`/data-scope hardening (E-10) are **not** part of
this task and were not built — confirmed by the scope audit in §16/§17 below.

## 2. Files created

```
apps/api/alembic/versions/20260814100000_employee_assignment.py
apps/api/tests/unit/modules/employee/test_employee_assignment_service.py
apps/api/tests/integration/modules/employee/test_employee_assignment.py
docs/modules/employee/10_EMPLOYEE_ASSIGNMENT_MODULE.md
docs/modules/employee/11_EMPLOYEE_ASSIGNMENT_API.md
docs/modules/employee/12_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_REPORT.md  (this document)
```

(`docs/modules/employee/09_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_PLAN.md` was created by the prior
investigation task, not this one — listed here only for completeness of the paper trail.)

## 3. Files modified

```
apps/api/src/hrms/modules/employee/models.py        (+ EmployeeAssignment ORM model)
apps/api/src/hrms/modules/employee/exceptions.py     (+ 9 exception classes)
apps/api/src/hrms/modules/employee/repository.py     (+ EmployeeAssignmentRepository)
apps/api/src/hrms/modules/employee/schemas.py        (+ AssignmentCreate/AssignmentRead + helpers)
apps/api/src/hrms/modules/employee/service.py        (+ EmployeeAssignmentService)
apps/api/src/hrms/modules/employee/permissions.py    (+ EMPLOYEE.TRANSFER, EMPLOYEE.PROMOTE)
apps/api/src/hrms/modules/employee/dependencies.py   (+ get_employee_assignment_service)
apps/api/src/hrms/modules/employee/router.py         (+ 3 assignment routes)
apps/api/tests/integration/modules/organisation/test_registration_flow.py
    (permission-set assertion updated to include EMPLOYEE.TRANSFER/.PROMOTE — the same
    one-line-per-code update E-01 and E-03 each made to this same test for their own codes)
```

No file inside `modules/organisation/`, `modules/identity/`, or `apps/web/` was modified beyond
that one assertion. `app.py` required no change — `employee_router` was already registered by
E-01; `seed/bootstrap.py` required no change — `EMPLOYEE_PERMISSIONS` is iterated dynamically by
both the bootstrap seed and `OrganisationService.register_company`, so the two new codes were
picked up automatically, the same mechanism E-03 relied on for `EMPLOYEE.TERMINATE`.

## 4. Database changes

One migration, `20260814100000_employee_assignment.py`, applied and verified against the dev
database (`employee_assignment` had zero rows at write time):

- Five new columns: `dotted_line_manager_id`, `cost_centre_id`, `work_location_type`,
  `change_reason`, `change_type`. `shift_id` was **not** added — that's E-05's own migration.
- Six new FK constraints, `ON DELETE SET NULL`: `department_id -> department.id`,
  `designation_id -> designation.id`, `grade_id -> grade.id`, `branch_id -> branch.id`,
  `reporting_manager_id -> employee.id`, `dotted_line_manager_id -> employee.id`
  (self-referential, mirroring `designation.next_designation_id`'s existing precedent). Closes
  the exact gap this slice's own investigation flagged: previously only `employee_id` had a
  DB-level FK.
- Two new indexes: `employee_assignment_current_idx (company_id, employee_id, effective_from
  DESC)` and `employee_assignment_manager_idx (company_id, reporting_manager_id) WHERE
  effective_to IS NULL`.
- `employee_assignment_no_overlap` (the GiST exclusion constraint) and RLS were already live
  and correct — untouched except for RLS's idempotent re-assertion.

Verified live against the dev database (`\d employee_assignment`) — every column, FK, and index
matches the migration exactly (full output captured during the investigation and re-verified
after `alembic upgrade head`).

`employee`, `employment`, `employee_compensation` were **not** touched by this migration.

## 5. ORM model

`EmployeeAssignment` added to `apps/api/src/hrms/modules/employee/models.py`, alongside
`Employee`/`Employment`/`NumberSeries`. Same field shape as the live table; `shift_id`
deliberately absent (E-05's own model addition).

## 6. Repository

`EmployeeAssignmentRepository`, mirroring `EmploymentRepository`'s exact shape:
`insert_assignment`, `get_current_assignment` (`effective_to IS NULL`), `get_assignment_as_of`
(the shared as-of-date contract, same shape as `EmploymentRepository.get_employment_as_of`),
`list_assignments`, `get_assignment`, `close_assignment` (the one allowed mutation — sets only
`effective_to`, version-gated). No general `update_assignment(values=...)` method exists —
deliberate, since no document names a path that edits a historical row's business columns.

## 7. Service / business rules

`EmployeeAssignmentService.create_assignment` is the single write operation. Steps, in order:

1. Assert the employee exists and belongs to the tenant (`404` otherwise).
2. Resolve the covering employment episode via `EmploymentRepository.get_employment_as_of`
   (`409 NO_ACTIVE_EMPLOYMENT` if none covers `effective_from`).
3. Read the current assignment row, if any.
   - **No current row**: `branch_id`/`department_id`/`designation_id` are required
     (`422 ASSIGNMENT_FIELDS_REQUIRED` otherwise).
   - **Current row exists**: `effective_from` must be strictly after the current row's own
     (`422 INVALID_EFFECTIVE_FROM` otherwise); `If-Match` is required
     (`422 ASSIGNMENT_VERSION_REQUIRED` otherwise); every omitted field carries forward from the
     current row's value.
4. Validate every provided/carried-forward reference: `branch_id`/`department_id`/
   `designation_id`/`grade_id` via `organisation.service`'s public surface only (never
   `.repository`/`.models`, per the Module Standard) — `422 INVALID_BRANCH` /
   `INVALID_DEPARTMENT` / `INVALID_DESIGNATION` / `INVALID_GRADE`. `reporting_manager_id`/
   `dotted_line_manager_id` via `EmployeeRepository.get_employee` — must exist, same tenant,
   not soft-deleted, and not equal to the assignment's own `employee_id`
   (`422 INVALID_REPORTING_MANAGER`, a direct-self-reference guard only, not cycle detection).
5. If a current row exists, close it (`effective_to = new.effective_from - 1 day`),
   version-gated (`409 STALE_RESOURCE` on mismatch).
6. Insert the new row, translating an `IntegrityError` from the GiST exclusion constraint into
   `409 ASSIGNMENT_DATES_OVERLAP` (the race-condition backstop).
7. Record one `ASSIGNMENT_CHANGED` audit event, `change_type` carried in the `after` snapshot.

Plus read methods: `list_assignments` (full history or `as_of`), `get_assignment` (single row),
and `get_assignment_as_of` (the shared cross-module contract, deliberately not asserting
employee existence — a nonexistent `employee_id` simply yields no covering row).

## 8. API endpoints

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/v1/employees/{employee_id}/assignments` | `EMPLOYEE.VIEW` | Full history, or `?as_of=` for the covering row |
| GET | `/v1/employees/{employee_id}/assignments/{assignment_id}` | `EMPLOYEE.VIEW` | Single row by id |
| POST | `/v1/employees/{employee_id}/assignments` | `EMPLOYEE.PROMOTE` if `change_type=PROMOTION`, else `EMPLOYEE.TRANSFER` | Closes current row (if any), inserts new row |

Full request/response/error-code reference: `11_EMPLOYEE_ASSIGNMENT_API.md`.

The `POST` route's permission is the only one in this module selected dynamically from the
request body rather than a single static `Depends(require_permission(CODE))`. The check is
performed explicitly in the route handler, after the body is parsed, rather than via a
dependency that would need to re-parse the request body itself (avoiding FastAPI's
body-sharing-across-dependencies ambiguity).

## 9. Permissions

| Code | Status before this slice | This slice |
|---|---|---|
| `EMPLOYEE.TRANSFER` | Not seeded | **Added** — gates `INITIAL`/`TRANSFER`/`MANAGER_CHANGE` |
| `EMPLOYEE.PROMOTE` | Not seeded | **Added** — gates `PROMOTION` |
| `EMPLOYEE.VIEW` | Seeded (identity module) | Reused — gates both `GET` routes |

Both new codes were already named in the locked 14-code catalogue
(`00_EMPLOYEE_AUDIT.md §13.1`, `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part B9) — not invented
by this task. Granted to `COMPANY_ADMIN` automatically at both bootstrap-seed and live
registration time, via the same dynamic `EMPLOYEE_PERMISSIONS` iteration E-01/E-03 already
relied on.

## 10. Effective-dating behaviour

Implements the pattern locked by `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part B7 exactly:
insert-never-update-in-place, close-then-insert in one transaction, current/as-of/full-history
read shapes identical to `Employment`'s own (field names substituted). Verified end-to-end by
the as-of-date boundary integration test (`test_list_assignments_as_of_date_boundaries`) against
the brief's own 2027/2028 worked example, and by the raw-insert integration test
(`test_raw_overlapping_insert_rejected_at_database_level`) proving the GiST exclusion constraint
is the real backstop, not just an application-level check.

## 11. Employment dependency

An assignment's `effective_from` must fall within a covering employment episode
(`EmploymentRepository.get_employment_as_of`) — enforced in the service layer only, since
`employee_assignment` has no `employment_id` column to express this as a DB constraint. Verified
by `test_create_assignment_without_covering_employment_rejected`.

## 12. Rehire behaviour

A rehire's first assignment is mechanically identical to any employee's first assignment — the
"no current row" branch of `create_assignment` handles both cases with no special-case code,
matching `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part C's own stated design. Verified end-to-end
by `test_rehire_first_assignment_after_gap`: employee joins, an assignment is placed, the
employment terminates, a gap follows, a new employment (rehire) starts, and a new assignment is
placed — the employee identity (`id`/`employee_code`) is unchanged throughout, and both
assignment rows are queryable under the one `employee_id`.

**Known limitation surfaced by this test, not silently glossed over** (see §16 item 1): the
pre-exit assignment row is not automatically closed when its covering employment terminates —
nothing in this slice hooks into `EmploymentService.terminate_employment` (E-03, already
complete, deliberately not modified — see §16). It remains open (`effective_to IS NULL`) until
the rehire's own `create_assignment` call closes it, at `rehire.effective_from - 1 day` — not
the original exit date. This is a data-quality imprecision in historical `effective_to` dating
across an employment gap, not a data-integrity bug: no overlapping rows are ever possible (the
GiST exclusion constraint still holds), and no orphaned or duplicate rows are created.

## 13. Audit behaviour

One event, `ASSIGNMENT_CHANGED`, per `00_EMPLOYEE_AUDIT.md §13.4`'s own recommendation (a single
event with `change_type` carried in the `after` snapshot, not fragmented into per-change-type
action strings). `before` is `null` for an employee's first assignment, and the closed row's
snapshot otherwise. Verified by `test_create_first_assignment_success`.

## 14. Tenant / RLS isolation

No RLS change was needed — already live and correct on `employee_assignment`
(`FORCE ROW LEVEL SECURITY`, `tenant_isolation` policy). The repository continues the
belt-and-suspenders convention of filtering `company_id` explicitly in every query, not relying
on RLS alone. Verified by `test_cannot_get_assignment_from_other_tenant` and
`test_cannot_reference_other_tenant_branch` (a same-company employee cannot be assigned to
another tenant's branch — `422 INVALID_BRANCH`, not a cross-tenant data leak).

## 15. Tests

**20 new unit tests** (`tests/unit/modules/employee/test_employee_assignment_service.py`):
first-assignment success/validation, no-covering-employment rejection, unknown-employee
rejection, transfer carry-forward, `If-Match` requirement, stale-effective-from rejection,
stale-version conflict, four reference-validation cases (branch/department/designation/grade),
self-reference and unknown-manager rejection, the GiST-overlap-to-domain-error translation, and
four read-path cases (`list`/`get`/`as-of`, including that `get_assignment_as_of` does not
require an employee lookup).

**21 new integration tests** (`tests/integration/modules/employee/test_employee_assignment.py`,
against the real Postgres dev database): first-assignment success (with audit-row verification),
missing-mandatory-field rejection, no-covering-employment rejection, mass-assignment rejection,
unknown-employee rejection, invalid-branch rejection, self-reference-manager rejection, empty
list state, not-found, as-of-date boundaries, transfer carry-forward, promotion, missing/stale
`If-Match`, invalid effective-from, the raw-SQL GiST-constraint-bypass test, the full rehire
scenario, cross-tenant get rejection, cross-tenant branch-reference rejection, and two
permission-matrix tests (no `.TRANSFER` at all; `.TRANSFER`-only against a `PROMOTION` request).

Every integration test tears down its own company/employee/assignment/org-structure rows in a
`finally` block, in FK-safe order (`employee_assignment -> employment -> employee/number_series
-> designation/grade/department/branch -> legal_entity/company/roles/user` via the shared
`_cleanup` helper). Verified against the dev database after the full suite run: `employee`,
`employment`, `employee_assignment`, and org-structure row counts are all `0`; only the two
pre-existing seed companies (`Demo Company A`/`B`) remain.

## 16. Validation results

```
ruff check .              — All checks passed!
ruff format --check .     — 150 files already formatted
mypy src/hrms              — Success: no issues found in 73 source files
lint-imports                — Contracts: 1 kept, 0 broken
pytest                     — 424 passed (383 pre-existing + 41 new)
```

All four checks were run against the **whole backend**, not just this slice's own files. The
pre-existing Employee/Employment/organisation suites all continue to pass unmodified except the
one permission-set assertion in `test_registration_flow.py` (§3), which needed the two new
codes added — the same one-line update E-01 and E-03 each required for their own new codes.

No manual UI verification was performed or claimed — E-04 is backend-only per its own scope; no
`apps/web/` file was touched.

## 17. Known limitations

1. **Assignment rows are not auto-closed on employment termination** (§12) — the pre-exit row
   remains open until a subsequent `create_assignment` call closes it. Not named as an E-04
   deliverable in the approved plan (`09_..._PLAN.md` §9 scopes `create_assignment` as the only
   mutation path); implementing auto-close would mean modifying `EmploymentService.terminate_
   employment` (E-03, already complete) — deliberately not done, per the instruction not to
   modify completed modules unnecessarily. Flagged here as a real gap for a future decision, not
   silently absorbed.
2. **No cross-entity consistency check** between `branch_id`/`department_id`/the employee's
   `employment.legal_entity_id` — deliberate, matching the organisation module's own precedent
   (it doesn't enforce this class of consistency on itself either); see plan §14.4.
3. **No cycle detection on the reporting-manager chain** beyond direct self-reference; see plan
   §14.5.
4. **No `SELF`/`REPORTEES`/`REPORTEE_TREE` data-scope resolver** — `GET` routes gate only on the
   coarse `EMPLOYEE.VIEW`/company-wide grant, same as `Employment`'s existing reads. E-10's
   scope, not E-04's.
5. **Payroll-lock-period backdating enforcement (FR-EMP-004) is not implementable** — Payroll
   doesn't exist yet; any past `effective_from` is currently accepted without a lock-period
   check.
6. **Approval-routing reassignment on manager change (FR-EMP-013) is not built** — the
   `reporting_manager_id` change is recorded; no pending-approval reassignment occurs, since no
   approval-routing engine exists.
7. **`change_type`/`work_location_type` are engineering-decided enumerations**, not literally
   named by any source document — see plan §14.2. Validated at the Pydantic layer (`Literal`
   types), not a lookup table or PG enum, matching `employment.status`'s own precedent.

## 18. Explicitly excluded scope

Confirmed by inspecting `git diff` before writing this report:

- **No E-05 (Shift Assignment)** — `shift_id` does not exist on `employee_assignment`; the
  `shift` table (`organisation/models.py`) was not touched.
- **No Compensation (E-06)**, **Statutory (E-07)**, **Banking (E-08)** — no `employee_
  compensation`/`employee_statutory`/`employee_bank` code was added or modified.
- **No Attendance, Leave, Payroll, or ATS** — no such modules or tables exist in this diff.
- **No Workflow automation / approval-routing engine.**
- **No BR-14 shift/notice-period override chain** — not referenced anywhere in this slice's
  code.
- **No frontend changes** — `apps/web/` is untouched.
- **No `organisation`/`identity` module changes** beyond the one test assertion (§3).

The diff is confined to: `modules/employee/*` (models, exceptions, repository, schemas, service,
permissions, dependencies, router), one new Alembic migration, two new test files, one updated
test assertion, and three new documentation files.

## 19. Assumptions made

All flagged inline in the relevant section above and in `09_..._PLAN.md` §14 (engineering
decisions, not product decisions): the `change_type`/`work_location_type` enumerations (§17
item 7), the permission-selection-by-`change_type` rule (§8), the "assignment requires covering
employment" rule (§11), the decision not to auto-close assignments on employment termination
(§17 item 1), and the decision not to build cross-entity consistency or cycle-detection checks
(§17 items 2–3). None of these required stopping — each was already anticipated and reasoned
through in the approved plan, or follows directly from a locked architectural decision.

No genuine undocumented **product** decision blocked this implementation. Nothing was assumed
past what the plan and the locked architecture decisions already settled.

## 20. Recommended next step

**E-05 — Shift assignment**: `ALTER TABLE employee_assignment ADD COLUMN shift_id`, FK to
`shift(id)`, `shift_id` becomes a settable field on the same `POST .../assignments` endpoint
with `change_type = SHIFT_CHANGE` (a fifth enum value to add), and the `get_assignment_as_of`
contract this slice already ships becomes the method Attendance will call for `shift_id`
specifically. Per `01_EMPLOYEE_MODULE_PLAN.md` §"E-05", the BR-14 override chain stays
explicitly deferred — an employee with no `shift_id` set has no shift, full stop, until that
separate cross-module decision is made.
