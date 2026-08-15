# Employee Compensation (E-06) — Implementation Report

Closeout report for the Employee Compensation vertical slice, built per
`17_EMPLOYEE_COMPENSATION_IMPLEMENTATION_PLAN.md` (the investigation/plan that preceded this
task). Builds directly on E-01 (Employee Foundation), E-03 (Employment Lifecycle), E-04
(Employee Assignment), and E-05 (Employee Shift Assignment) — all COMPLETE, 476 backend tests
passing before this task started (439 pre-existing, confirmed by the plan's own audit).

---

## 1. E-06 status

**COMPLETE**, for the scope authorized by the plan. `EmployeeCompensation` ORM model,
repository, service, router, schemas, exceptions, and permissions are all implemented; the
migration is applied and verified against the dev database; 37 new tests (15 unit + 22
integration) pass; the full backend suite (476 tests: 439 pre-existing + 37 new) passes; `ruff
check`, `ruff format --check`, `mypy src/hrms`, and `lint-imports` all pass clean.

Statutory (E-07), Banking (E-08), the frontend (E-09), Payroll (any module), and the RBAC/
`sensitive_access_log`/data-scope hardening (E-10) are **not** part of this task and were not
built — confirmed by the scope audit in §16/§17 below.

## 2. Files created

```
apps/api/alembic/versions/20260814120000_employee_compensation.py
apps/api/tests/unit/modules/employee/test_employee_compensation_service.py
apps/api/tests/integration/modules/employee/test_employee_compensation.py
docs/modules/employee/18_EMPLOYEE_COMPENSATION_MODULE.md
docs/modules/employee/19_EMPLOYEE_COMPENSATION_API.md
docs/modules/employee/20_EMPLOYEE_COMPENSATION_IMPLEMENTATION_REPORT.md  (this document)
```

(`docs/modules/employee/17_EMPLOYEE_COMPENSATION_IMPLEMENTATION_PLAN.md` was created by the
prior investigation task, not this one — listed here only for completeness of the paper trail.)

## 3. Files modified

```
apps/api/src/hrms/modules/employee/models.py        (+ EmployeeCompensation ORM model, 41 lines)
apps/api/src/hrms/modules/employee/exceptions.py     (+ 2 exception classes, 48 lines)
apps/api/src/hrms/modules/employee/repository.py     (+ EmployeeCompensationRepository, 110 lines)
apps/api/src/hrms/modules/employee/schemas.py        (+ CompensationCreate/Read + helpers, 72 lines)
apps/api/src/hrms/modules/employee/service.py        (+ EmployeeCompensationService, 174 lines)
apps/api/src/hrms/modules/employee/permissions.py    (+ EMPLOYEE.VIEW_COMPENSATION, .UPDATE_COMPENSATION)
apps/api/src/hrms/modules/employee/dependencies.py   (+ get_employee_compensation_service)
apps/api/src/hrms/modules/employee/router.py         (+ 3 compensation routes)
apps/api/tests/integration/modules/organisation/test_registration_flow.py
    (permission-set assertion updated to include EMPLOYEE.VIEW_COMPENSATION/
    .UPDATE_COMPENSATION — the same one-line-per-code update every prior slice made to this
    same test for its own new codes)
```

9 files changed, 545 insertions(+), 16 deletions(-) (`git diff --stat`, confirmed this session).
No file inside `modules/organisation/`, `modules/identity/`, or `apps/web/` was modified beyond
that one assertion. `app.py` required no change — `employee_router` was already registered by
E-01; `seed/bootstrap.py` required no change — `EMPLOYEE_PERMISSIONS` is iterated dynamically by
both the bootstrap seed and `OrganisationService.register_company`, so the two new codes were
picked up automatically, the same mechanism E-03/E-04 relied on for their own new codes.

## 4. Database changes

One migration, `20260814120000_employee_compensation.py`, applied and verified against the dev
database (`employee_compensation` had zero rows both before and after — confirmed by direct
`psql` query both times):

- Two new columns: `revision_type` (`VARCHAR(20) NOT NULL DEFAULT 'JOINING'`), `revision_reason`
  (nullable `TEXT`). The `DEFAULT` is safe only because the table had zero rows — it exists so
  the column could be declared `NOT NULL` in one statement, no backfill step needed.
- No new index — the live `employee_compensation_employee_id_effective_from_idx` and the GiST
  exclusion constraint already covered every query shape this slice's repository needs.
- No new FK — this slice added no reference column.
- `employee_compensation_no_overlap` (the GiST exclusion constraint) and RLS were already live
  and correct — untouched except for RLS's idempotent re-assertion.

Verified live against the dev database (`\d+ employee_compensation`) both before writing the
migration and after applying it — every pre-existing column, index, FK, and the GiST exclusion
constraint are unchanged; the two new columns match the migration exactly.

`employee`, `employment`, `employee_assignment`, `grade`, and every other table were **not**
touched by this migration.

## 5. ORM model

`EmployeeCompensation` added to `apps/api/src/hrms/modules/employee/models.py`, alongside
`Employee`/`Employment`/`EmployeeAssignment`/`NumberSeries`; the module docstring's stale "not
mapped here" sentence about `EmployeeCompensation` was removed. Same field shape as the live
table plus the two new migration columns. `annual_ctc_minor` is mapped as `BigInteger`
(matching the live `BIGINT` column and `Grade.min_ctc`/`max_ctc`'s own `BigInteger` mapping),
not `Integer`.

## 6. Repository

`EmployeeCompensationRepository`, mirroring `EmployeeAssignmentRepository`'s exact shape:
`insert_compensation`, `get_current_compensation` (`effective_to IS NULL`),
`get_compensation_as_of` (the shared as-of-date contract), `list_compensations`,
`get_compensation`, `close_compensation` (the one allowed mutation — sets only `effective_to`,
version-gated). No general `update_compensation(values=...)` method exists — deliberate, since
no document names a path that edits a historical row's business columns.

## 7. Service / business rules

`EmployeeCompensationService.create_compensation` is the single write operation. Steps, in
order:

1. Assert the employee exists and belongs to the tenant (`404` otherwise).
2. Resolve the covering employment episode via `EmploymentRepository.get_employment_as_of`
   (`409 NO_ACTIVE_EMPLOYMENT` if none covers `effective_from`).
3. Read the current compensation row, if any.
   - **No current row**: nothing conditionally required — `annual_ctc_minor`, `currency`,
     `revision_type`, `revision_reason` are all unconditionally required at the schema layer
     (unlike Assignment's conditionally-required placement fields).
   - **Current row exists**: `effective_from` must be strictly after the current row's own
     (`422 INVALID_EFFECTIVE_FROM` otherwise); `If-Match` is required
     (`422 COMPENSATION_VERSION_REQUIRED` otherwise).
4. No reference validation needed — `employee_compensation` has no reference columns beyond
   `employee_id` (already asserted in step 1). No Grade CTC-band check (§10 below).
5. If a current row exists, close it (`effective_to = new.effective_from - 1 day`),
   version-gated (`409 STALE_RESOURCE` on mismatch).
6. Insert the new row, translating an `IntegrityError` from the GiST exclusion constraint into
   `409 COMPENSATION_DATES_OVERLAP` (the race-condition backstop).
7. Record one `COMPENSATION_REVISED` audit event.

Plus read methods: `list_compensations` (full history or `as_of`), `get_compensation` (single
row), and `get_compensation_as_of` (the shared cross-module contract, deliberately not
asserting employee existence — a nonexistent `employee_id` simply yields no covering row).

## 8. API endpoints

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/v1/employees/{employee_id}/compensation` | `EMPLOYEE.VIEW_COMPENSATION` | Full history, or `?as_of=` for the covering row |
| GET | `/v1/employees/{employee_id}/compensation/{compensation_id}` | `EMPLOYEE.VIEW_COMPENSATION` | Single row by id |
| POST | `/v1/employees/{employee_id}/compensation` | `EMPLOYEE.UPDATE_COMPENSATION` | Closes current row (if any), inserts new row |

Full request/response/error-code reference: `19_EMPLOYEE_COMPENSATION_API.md`.

Unlike Assignment's `POST .../assignments`, no dynamic permission selection is needed —
`.VIEW_COMPENSATION`/`.UPDATE_COMPENSATION` map 1:1 to GET/POST via a single static
`Depends(require_permission(CODE))`, the simplest route wiring of any slice so far.

## 9. Permissions

| Code | Status before this slice | This slice |
|---|---|---|
| `EMPLOYEE.VIEW_COMPENSATION` | Named in the locked 14-code catalogue, not seeded | **Added** — gates both `GET` routes |
| `EMPLOYEE.UPDATE_COMPENSATION` | Named in the locked 14-code catalogue, not seeded | **Added** — gates the `POST` route |

Both codes were already named in the locked 14-code catalogue
(`docs/product/19_RBAC_and_Permission_Matrix.md §3.1`, lines 45-46) — not invented by this task,
and no naming-decision resolution (like E-03's `.TERMINATE`) was required. Granted to
`COMPANY_ADMIN` automatically at both bootstrap-seed and live registration time, via the same
dynamic `EMPLOYEE_PERMISSIONS` iteration every prior slice already relied on.

## 10. Business rules

- **Covering employment required**: mirrors `EmployeeAssignmentService`'s identical rule exactly
  (§7 step 2). Verified by `test_create_compensation_without_covering_employment_rejected`.
- **No carry-forward**: `annual_ctc_minor`, `currency`, `revision_type`, `revision_reason` are
  always required, on every write, including an employee's first row — a deliberate departure
  from Assignment's carry-forward pattern (plan §17.2). A caller wanting to record a
  `CORRECTION`-type revision that changes only `revision_reason` must re-state the same
  `annual_ctc_minor`; this trades a small UX cost for eliminating the risk of a stale CTC
  silently carrying forward by omission.
- **Grade `min_ctc`/`max_ctc` band — deliberately not enforced (PD-1)**: no document anywhere
  states that `annual_ctc_minor` must fall within the employee's current grade's CTC band, and
  Grade's own CTC fields are documented as informational bands only
  (`docs/modules/grade/01_Grade_Module.md:141`). This slice ships with no enforcement, per the
  plan's own recommended default (plan §16, PD-1) — verified explicitly by
  `test_grade_ctc_band_does_not_block_compensation`, which creates a grade with a
  `[1000000000, 1500000000]`-minor-unit band and successfully records compensation both far
  below and far above it.
- **Money validation**: `annual_ctc_minor: int = Field(ge=0)` — a negative CTC is rejected at
  the schema layer (`422`), verified by `test_create_compensation_negative_ctc_rejected` /
  `test_negative_annual_ctc_minor_rejected_at_schema_layer`. No upper bound, no currency-code
  membership validation, no cross-check against a company-level currency setting — none are
  named by any document.
- **`revision_type`**: validated as a Pydantic `Literal`
  (`JOINING`/`ANNUAL`/`PROMOTION`/`CORRECTION`/`MARKET`, the exact and only enum found in any
  document, `docs/product/08_Database_Architecture.md:242`), not a DB `CHECK` constraint or
  lookup table — matches the actually-shipped precedent (`employment.status`,
  `employee_assignment.change_type`). Verified by
  `test_create_compensation_invalid_revision_type_rejected`.

## 11. Effective-dating behaviour

Implements the pattern locked by `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part B7 exactly:
insert-never-update-in-place, close-then-insert in one transaction, current/as-of/full-history
read shapes identical to `Employment`/`EmployeeAssignment`'s own (field names substituted).
Verified end-to-end by the as-of-date boundary integration test
(`test_list_compensations_as_of_date_boundaries`), and by the raw-insert integration test
(`test_raw_overlapping_insert_rejected_at_database_level`) proving the GiST exclusion constraint
is the real backstop, not just an application-level check.

## 12. Audit behaviour

One event, `COMPENSATION_REVISED`, per `00_EMPLOYEE_AUDIT.md §13.4`'s own pre-named
recommendation. `before` is `null` for an employee's first compensation row, and the closed
row's snapshot otherwise. Verified by `test_create_first_compensation_success`. No
`sensitive_access_log` read-path logging was added — that table does not exist in this codebase,
and its build timing is already locked to E-10, not E-06
(`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part A9) — a real, named compliance gap for the period
between E-06 shipping and E-10 shipping, flagged here explicitly (see §17 item 3).

## 13. Tenant / RLS isolation

No RLS change was needed — already live and correct on `employee_compensation`
(`FORCE ROW LEVEL SECURITY`, `tenant_isolation` policy, live since the very first migration).
The repository continues the belt-and-suspenders convention of filtering `company_id` explicitly
in every query, not relying on RLS alone. Verified by
`test_cannot_get_compensation_from_other_tenant` and
`test_cannot_create_compensation_for_other_tenant_employee`.

## 14. Concurrency behaviour

Optimistic concurrency via `version` + `If-Match`, identical shape to
`Employment`/`EmployeeAssignment`: `If-Match` is required only when a current compensation row
exists (nothing to version-check for a first row); a stale `version` on the close step yields
`409 STALE_RESOURCE` with the current row's snapshot in `details[0].context.current`. Verified
by `test_create_compensation_missing_if_match_when_current_exists_rejected` and
`test_create_compensation_stale_version_conflict`.

## 15. Tests

**15 new unit tests**
(`tests/unit/modules/employee/test_employee_compensation_service.py`): first-compensation
success, no-covering-employment rejection, unknown-employee rejection, revision
close-then-insert, `If-Match` requirement, stale-effective-from rejection, stale-version
conflict, the GiST-overlap-to-domain-error translation, negative-CTC and mass-assignment schema
rejection, and four read-path cases (`list`/`get`/`as-of`, including that
`get_compensation_as_of` does not require an employee lookup).

**22 new integration tests**
(`tests/integration/modules/employee/test_employee_compensation.py`, against the real Postgres
dev database): first-compensation success (with audit-row verification), no-covering-employment
rejection, mass-assignment rejection, unknown-employee rejection, negative-CTC rejection,
invalid-`revision_type` rejection, missing-`revision_reason` rejection, empty list state,
not-found, as-of-date boundaries, a full revision scenario (close-then-insert with a new CTC and
`revision_type`), missing/stale `If-Match`, invalid effective-from, the raw-SQL
GiST-constraint-bypass test, the full rehire scenario, the PD-1 Grade-band-does-not-block test,
cross-tenant get/create rejection, and three permission-matrix tests (no
`.VIEW_COMPENSATION` at all; `.VIEW_COMPENSATION`-only against a `POST`; `.UPDATE_COMPENSATION`
succeeding on its own).

Every integration test tears down its own company/employee/employment/compensation/grade rows
in a `finally` block, in FK-safe order (`employee_compensation -> employment ->
employee/number_series -> grade -> legal_entity/company/roles/user` via the shared `_cleanup`
helper). Verified against the dev database after the full suite run:
`SELECT count(*) FROM employee_compensation` / `employee` / `company WHERE name LIKE 'Acme%'` /
`"user" WHERE email LIKE 'scoped-%'` all returned `0`.

## 16. Validation results

```
ruff check .              — All checks passed!
ruff format --check .     — 154 files already formatted (1 auto-reformatted during this task)
mypy src/hrms              — Success: no issues found in 73 source files
lint-imports                — Contracts: 1 kept, 0 broken
pytest                     — 476 passed (439 pre-existing + 37 new)
```

All five checks were run against the **whole backend**, not just this slice's own files. The
pre-existing Employee/Employment/Assignment/organisation suites all continue to pass unmodified
except the one permission-set assertion in `test_registration_flow.py` (§3), which needed the
two new codes added — the same one-line update every prior slice required for its own new codes.

No manual UI verification was performed or claimed — E-06 is backend-only per its own scope; no
`apps/web/` file was touched.

## 17. Known limitations

1. **Compensation rows are not auto-closed on employment termination** — the pre-exit row
   remains open until a subsequent `create_compensation` call closes it, at that call's
   `effective_from - 1 day`, not the original exit date. The identical, already-documented
   limitation E-04 has for `employee_assignment` (same root cause: no slice hooks into
   `EmploymentService.terminate_employment`). Verified/surfaced by
   `test_rehire_first_compensation_after_gap`, whose docstring documents this explicitly rather
   than asserting an idealized "closed exactly at exit" timeline.
2. **Grade `min_ctc`/`max_ctc` band is not enforced against `annual_ctc_minor`** (PD-1, §10) —
   a deliberate, documented decision with a plan-recommended safe default, not a silently missed
   requirement. Revisit only on explicit product direction; the change would be a pure
   service-layer addition with no schema change if ever wanted.
3. **No `sensitive_access_log` read-path logging** — CTC is `RESTRICTED`-classified
   (`docs/product/19_RBAC_and_Permission_Matrix.md §6`), but read-path logging beyond the
   ordinary write-path `AuditService` calls is out of scope: `sensitive_access_log` does not
   exist anywhere in this codebase, and its build timing is already locked to E-10
   (`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part A9). This is a real, named compliance gap for
   the period between E-06 and E-10 shipping.
4. **No combined promotion+compensation-revision transaction** — FR-EMP-012 names an "optional
   compensation revision" as part of a promotion workflow, but `create_assignment` (E-04) and
   `create_compensation` (E-06) remain two independent service calls with no shared transaction
   or cross-service coupling (plan §17.4). A future UI workflow (E-09) or thin orchestration
   endpoint would sequence both calls; not built here.
5. **Payroll-lock-period backdating enforcement (FR-EMP-004) is not implementable** — Payroll
   doesn't exist yet; any past `effective_from` is currently accepted without a lock-period
   check, the same known limitation Assignment/Employment already carry.
6. **No multi-currency cross-check against a company-level currency setting** — `currency`
   accepts any 3-letter code with no validation against ISO 4217 membership or a company-level
   setting; no document requires either.

## 18. Explicitly excluded scope

Confirmed by inspecting `git status`/`git diff --stat` before writing this report:

- **No Payroll** — no salary structure, salary component, CTC-to-gross-to-net breakup, arrears
  engine, or payroll-run code exists anywhere in this diff. `salary_structure_id`,
  `monthly_gross`, `is_arrears_processed`, and the `employee_compensation_component` child table
  were all deliberately not added (plan §4.2) — they depend on Payroll's own catalogue tables,
  which do not exist.
- **No Statutory (E-07), Banking (E-08)** — no `employee_statutory`/`employee_bank` code was
  added or modified.
- **No frontend (E-09)** — `apps/web/` is untouched.
- **No E-10 work** — no `sensitive_access_log` table/model/migration, no `SELF`/`REPORTEES`/
  `REPORTEE_TREE` data-scope resolver.
- **No Attendance, Leave, ATS, Recruitment, Performance, or Workflow automation** — no such
  modules or tables exist in this diff.
- **No BR-14 shift/notice-period override chain** — not referenced anywhere in this slice's
  code.
- **No approval-routing engine** — `approved_by`/`approval_request_id` were deliberately not
  added (plan §7/§13).
- **No `organisation`/`identity` module changes** beyond the one test assertion (§3).

The diff is confined to: `modules/employee/*` (models, exceptions, repository, schemas, service,
permissions, dependencies, router), one new Alembic migration, two new test files, one updated
test assertion, and three new documentation files — 9 files changed, 545 insertions(+), 16
deletions(-), plus the 3 new markdown files.

## 19. Grade min/max CTC decision (PD-1)

Per plan §16: no document states that `employee_compensation.annual_ctc_minor` should be
validated against the employee's current grade's `min_ctc`/`max_ctc` band. This implementation
adopted the plan's own recommended default — **no enforcement** — because (a) it required zero
new design work and is directly precedented by E-04's own declined cross-entity checks, (b)
`grade_id`/`min_ctc`/`max_ctc` are all nullable, so any enforcement rule would first need to
resolve several unstated sub-questions (null-grade behavior, null-bound behavior, retroactive
enforcement on band changes) that no document answers, and (c) it does not block Payroll or any
other downstream consumer. Verified explicitly by
`test_grade_ctc_band_does_not_block_compensation`. If product wants this enforced later, it is a
pure service-layer addition with no schema change.

## 20. Unresolved decisions

None blocking. PD-1 (§19) was the only genuine product-decision item the plan identified, and it
ships with the plan's own recommended safe, zero-schema-cost default. Every other choice made in
this implementation (no carry-forward, `revision_type=JOINING` unconditionally required, no
combined promotion+compensation transaction, exception naming) follows directly from a
plan-documented engineering decision (plan §17) with a cited precedent — nothing was invented
without a source.

## 21. Recommended next step

**E-07 — Statutory** (PF/ESI/PT amounts) is the next slice named in the locked sequence
(`01_EMPLOYEE_MODULE_PLAN.md` §2), following the same effective-dated,
`employee_id`-keyed pattern this slice, E-04, and E-03 all already established. Its own table
does not yet exist in the live schema (unlike Compensation and Assignment, which pre-dated their
own application-layer slices) — that investigation should start by confirming whether
`employee_statutory` needs to be created from scratch or already exists unmapped, the same first
question this slice's own plan (`17_...md §2`) answered for Compensation.
