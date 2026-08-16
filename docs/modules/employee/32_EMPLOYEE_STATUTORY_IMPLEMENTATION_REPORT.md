# Employee Statutory (E-07) — Implementation Report

Closeout report for the Employee Statutory vertical slice, built per
`29_EMPLOYEE_STATUTORY_IMPLEMENTATION_PLAN.md` (the investigation/plan that preceded this task).
Builds directly on E-01 (Employee Foundation), E-03 (Employment Lifecycle), E-04 (Employee
Assignment), E-06 (Employee Compensation), and the RBAC data-scope (`24`-`26`) and
reporting-manager-security (`27`-`28`) slices.

**Note on starting state**: at the start of this task, the working tree already carried
uncommitted changes from the prior RBAC-data-scope/reporting-manager-security work (per
`git status` at session start: `core/db/models/identity.py`, `core/rbac/*`,
`modules/employee/exceptions.py`, `.repository.py`, `.router.py`, `.service.py`, and
`tests/unit/modules/employee/test_employment_service.py` were already modified; the RBAC
migration `20260815120000_role_permission_data_scope.py` and `test_employee_data_scope.py` were
already new/untracked). This report describes only what **this task** added on top of that
baseline — §2/§3 below separate the two clearly per file.

---

## 1. E-07 status

**COMPLETE**, for the scope authorized by the plan. `EmployeeStatutory` ORM model, repository,
service, router, schemas, exceptions, and permissions are all implemented; the migration is
applied and verified against the dev database (upgrade → downgrade → upgrade, clean); 48 new
tests (20 unit + 28 integration) pass; the full backend suite (555 tests: 507 pre-existing +
48 new) passes; `ruff check`, `ruff format --check`, `mypy src/hrms`, and `lint-imports` all pass
clean against the whole repo.

Banking (E-08), the frontend (E-09), Payroll (any module), and E-10's `sensitive_access_log` are
**not** part of this task and were not built — confirmed by the scope audit in §19/§20 below.

## 2. Files created

```
apps/api/alembic/versions/20260815130000_employee_statutory.py
apps/api/tests/unit/modules/employee/test_employee_statutory_service.py
apps/api/tests/integration/modules/employee/test_employee_statutory.py
docs/modules/employee/30_EMPLOYEE_STATUTORY_MODULE.md
docs/modules/employee/31_EMPLOYEE_STATUTORY_API.md
docs/modules/employee/32_EMPLOYEE_STATUTORY_IMPLEMENTATION_REPORT.md  (this document)
```

(`docs/modules/employee/29_EMPLOYEE_STATUTORY_IMPLEMENTATION_PLAN.md` was created by the prior
investigation task, not this one — listed here only for completeness of the paper trail.)

## 3. Files modified

Four files had **no** pre-existing uncommitted changes before this task — their entire diff is
this task's own work:

```
apps/api/src/hrms/modules/employee/models.py        (+ EmployeeStatutory ORM model, 39 lines)
apps/api/src/hrms/modules/employee/schemas.py        (+ StatutoryCreate/Read + helpers, 87 lines)
apps/api/src/hrms/modules/employee/permissions.py    (+ EMPLOYEE.VIEW_STATUTORY, .UPDATE_SENSITIVE)
apps/api/src/hrms/modules/employee/dependencies.py   (+ get_employee_statutory_service)
```

Five files already carried pre-existing uncommitted changes from the prior RBAC-data-scope/
reporting-manager-security work at session start; this task's additions are layered on top of
that baseline, described precisely:

```
apps/api/src/hrms/modules/employee/exceptions.py
    (this task added: StatutoryDatesOverlapError, StatutoryVersionRequiredError,
    TaxRegimeSwitchNotAllowedError — 3 new exception classes)
apps/api/src/hrms/modules/employee/repository.py
    (this task added: EmployeeStatutoryRepository — insert_statutory, get_current_statutory,
    get_statutory_as_of, list_statutories, get_statutory, close_statutory)
apps/api/src/hrms/modules/employee/router.py
    (this task added: list_statutories/get_statutory/create_statutory routes under
    /v1/employees/{employee_id}/statutory*)
apps/api/src/hrms/modules/employee/service.py
    (this task added: EmployeeStatutoryService, the _fiscal_year helper, and — inside the
    pre-existing EmploymentService.terminate_employment — the statutory-row-closing block,
    mirroring the existing assignment/compensation closing blocks, per plan §9's "last row
    closed" requirement)
apps/api/tests/unit/modules/employee/test_employment_service.py
    (this task added: `svc._statutory_repo = AsyncMock()` and
    `svc._statutory_repo.get_current_statutory.return_value = None` to the `service` fixture —
    required because EmploymentService now depends on EmployeeStatutoryRepository; without this,
    every existing termination test failed with `TypeError: object MagicMock can't be used in
    'await' expression`. Smallest possible fix — no test logic changed.)
```

One file, clean before this task, was modified for a permission-set assertion update (the same
one-line-per-code update every prior slice made to this same test for its own new codes):

```
apps/api/tests/integration/modules/organisation/test_registration_flow.py
    (added EMPLOYEE.VIEW_STATUTORY, EMPLOYEE.UPDATE_SENSITIVE to the expected COMPANY_ADMIN
    permission set — register_company grants every EMPLOYEE_PERMISSIONS code automatically, so
    the newly registered company's admin now also holds these two)
```

No file inside `modules/organisation/`, `modules/identity/`, or `apps/web/` was modified beyond
that one assertion. `app.py` required no change — `employee_router` was already registered by
E-01; `seed/bootstrap.py` required no change — `EMPLOYEE_PERMISSIONS` is iterated dynamically by
both the bootstrap seed and `OrganisationService.register_company`, so the two new codes were
picked up automatically, the same mechanism every prior slice relied on for its own new codes.

## 4. Database changes

One migration, `20260815130000_employee_statutory.py`, revising `20260815120000` (the head
confirmed live in the dev database before this task started). Applied and verified against the
dev database:

**Pre-migration state** (confirmed by direct `psql` inspection before writing the migration):
`employee_statutory` did not exist (`\dt employee_statutory` returned no rows).

**Migration content** — a genuine foundational `CREATE TABLE` (plan §4/§20/§25 — this table has
no pre-existing skeleton, unlike Compensation): the full column set from plan §7, plus one column
beyond the plan's literal DDL, `revision_reason TEXT` (added per plan §16/§27 item 7's explicit
requirement that `revision_reason` be required on every write — a persisted column is needed for
it to be visible in `StatutoryRead`/the audit trail, mirroring
`employee_compensation.revision_reason` exactly; this is the one deviation from plan §7's literal
column list, named explicitly here per the plan's own "flag any necessary expansion" instruction
rather than silently added). Plus:
- `employee_statutory_no_overlap` GiST exclusion constraint on `(employee_id, daterange(...))`.
- Two indexes: `employee_statutory_company_id_idx`, `employee_statutory_employee_id_effective_from_idx`.
- FKs to `company(id)` and `employee(id)`, both `ON DELETE RESTRICT`.
- RLS: `ENABLE`/`FORCE ROW LEVEL SECURITY` + `tenant_isolation` policy on `company_id`.

**Post-migration verification** (`\d employee_statutory`, this session): all 21 columns present
with correct types/defaults/nullability; primary key on `id`; both FKs present; GiST exclusion
constraint present with the exact `employee_id WITH =, daterange(...) WITH &&` shape; both
indexes present; RLS forced with the `tenant_isolation` policy present.

**Idempotency proof**: `alembic upgrade head` → `alembic downgrade -1` (table dropped, confirmed
by `\dt employee_statutory` returning no rows) → `alembic upgrade head` (table recreated, schema
re-verified identical). `SELECT count(*) FROM employee_statutory` returned `0` after the final
upgrade — no test rows were left behind.

**Orphaned permission pre-flight check** (plan §4/§24 item 5, required before wiring the route):
`SELECT code, domain, description FROM permission WHERE code = 'EMPLOYEE.UPDATE_SENSITIVE'`
confirmed exactly one row (`domain=EMPLOYEE`, `description="Edit PAN/Aadhaar/bank/statutory"`,
verbatim what `EMPLOYEE_PERMISSIONS` now seeds), and a join against `role_permission` confirmed
**zero roles** held it, both before and after `EMPLOYEE_PERMISSIONS`/`seed_b1_foundation` were
updated to include it — the idempotent `SELECT ... WHERE code = :code` check in
`seed_b1_foundation` adopted the existing row rather than creating a duplicate, exactly as the
plan predicted.

`employee`, `employment`, `employee_assignment`, `employee_compensation`, `legal_entity`, and
every other table were **not** touched by this migration.

## 5. ORM model

`EmployeeStatutory` added to `apps/api/src/hrms/modules/employee/models.py`, alongside
`Employee`/`Employment`/`EmployeeAssignment`/`EmployeeCompensation`/`NumberSeries`. Keyed on
`employee_id`, not `employment_id` (plan §7/§8) — no FK to `employment` or `legal_entity`.
`vpf_percentage` mapped as `Numeric(9, 4)` matching the live column exactly.

## 6. Repository

`EmployeeStatutoryRepository`, mirroring `EmployeeCompensationRepository`'s exact shape:
`insert_statutory`, `get_current_statutory` (`effective_to IS NULL`), `get_statutory_as_of` (the
shared as-of-date contract), `list_statutories`, `get_statutory`, `close_statutory` (the one
allowed mutation — sets only `effective_to`, version-gated). No general
`update_statutory(values=...)` method exists — deliberate, since no document names a path that
edits a historical row's business columns.

## 7. Service / business rules

`EmployeeStatutoryService.create_statutory` is the single write operation. Steps, in order:

1. Assert the employee exists and belongs to the tenant (`404` otherwise).
2. Resolve the covering employment episode via `EmploymentRepository.get_employment_as_of`
   (`409 NO_ACTIVE_EMPLOYMENT` if none covers `effective_from`).
3. Read the current statutory row, if any.
   - **No current row**: nothing conditionally required — every field is unconditionally
     required/defaulted at the schema layer.
   - **Current row exists**: `effective_from` must be strictly after the current row's own
     (`422 INVALID_EFFECTIVE_FROM` otherwise); `If-Match` is required
     (`422 STATUTORY_VERSION_REQUIRED` otherwise); if `tax_regime` differs from the current row's
     and both `effective_from` dates fall in the same April-March fiscal year, the write is
     rejected (`409 TAX_REGIME_SWITCH_NOT_ALLOWED`, FR-PAY-006, plan §26 item 5's own flagged
     assumption).
4. No reference validation beyond the employee existence check in step 1 — `employee_statutory`
   has no other reference columns. No PF/ESI applicability-vs-identifier correlation check, and
   no legal-entity-registration correlation check (plan §17/§26 items 6-7, deliberately open).
5. If a current row exists, close it (`effective_to = new.effective_from - 1 day`),
   version-gated (`409 STALE_RESOURCE` on mismatch).
6. Insert the new row, translating an `IntegrityError` from the GiST exclusion constraint into
   `409 STATUTORY_DATES_OVERLAP` (the race-condition backstop).
7. Record one `STATUTORY_REVISED` audit event.

Plus read methods: `list_statutories` (full history or `as_of`), `get_statutory` (single row),
and `get_statutory_as_of` (the shared cross-module contract, deliberately not asserting employee
existence — a nonexistent `employee_id` simply yields no covering row).

**Correction to `EmploymentService.terminate_employment`** (not `EmployeeStatutoryService`): the
plan's §9 states plainly that statutory rows have their "last row closed" on exit, the same
contract Assignment/Compensation already have. This task added a statutory-closing block to
`terminate_employment`, structurally identical to the existing assignment/compensation blocks —
closes the current statutory row (if its `effective_from <= last_working_day`) at
`effective_to = last_working_day`, version-gated, with its own `STATUTORY_REVISED` audit event.
This is the one change this task made outside `EmployeeStatutoryService` itself, made because the
plan explicitly requires this behavior, not invented independently.

## 8. API endpoints

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/v1/employees/{employee_id}/statutory` | `EMPLOYEE.VIEW_STATUTORY` | Full history, or `?as_of=` for the covering row |
| GET | `/v1/employees/{employee_id}/statutory/{statutory_id}` | `EMPLOYEE.VIEW_STATUTORY` | Single row by id |
| POST | `/v1/employees/{employee_id}/statutory` | `EMPLOYEE.UPDATE_SENSITIVE` | Closes current row (if any), inserts new row |

Full request/response/error-code reference: `31_EMPLOYEE_STATUTORY_API.md`.

Like Compensation, no dynamic permission selection is needed — `.VIEW_STATUTORY`/
`.UPDATE_SENSITIVE` map 1:1 to GET/POST via a single static `Depends(require_permission(CODE))`.
No `caller_employee_id`/`AuthenticatedUser`/`RbacService` dependency on the write route — unlike
`create_assignment`, statutory has no manager-reference field requiring the self-elevation check
(plan §16).

## 9. Permissions

| Code | Status before this slice | This slice |
|---|---|---|
| `EMPLOYEE.VIEW_STATUTORY` | Not in the locked catalogue, code, or database | **Added** — gates both `GET` routes |
| `EMPLOYEE.UPDATE_SENSITIVE` | Named in the locked catalogue's write-only description; live in the database only as an orphaned row granted to zero roles, produced by no migration/seed/code | **Added as a proper code constant** — the idempotent seed adopted the existing row rather than duplicating it (§4 above); gates the `POST` route only |

Both codes are new to `EMPLOYEE_PERMISSIONS`, granted to `COMPANY_ADMIN` automatically at both
bootstrap-seed and live registration time, via the same dynamic `EMPLOYEE_PERMISSIONS` iteration
every prior slice already relied on. `EMPLOYEE.UPDATE_SENSITIVE`'s scope in this slice is
strictly limited to the `employee_statutory` `POST` route — **not** wired to `employee`'s
PAN/Aadhaar/UAN fields (E-02, no write path exists) or `employee_bank` (E-08, does not exist).

## 10. Data scope

`EMPLOYEE.VIEW_STATUTORY` discards its resolved `DataScope` and remains `COMPANY`-scoped —
bound to `_scope: Annotated[object, Depends(require_permission(EMPLOYEE_VIEW_STATUTORY))]`,
identical to Compensation's own routes. This is plan §11.3's explicit, named recommendation
(posture 1 of three evaluated), not a default inherited without consideration: no source document
proposes `SELF`/`REPORTEES`/`REPORTEE_TREE` visibility for PF/PAN-adjacent identifier data, and
this codebase already treats manager-linked data exposure as something to actively guard
(`27_REPORTING_MANAGER_SECURITY_AUDIT.md`'s self-elevation guard), not default open. The gap this
leaves — a manager holding `EMPLOYEE.VIEW_STATUTORY` sees every employee's statutory data
company-wide, not just their own reports' — is the *same class* of gap Compensation already
carries, named and tracked as a cross-cutting follow-up in `25_...IMPLEMENTATION_PLAN.md` §22,
not a new gap this slice introduces.

**Positive proof, not just an assumption**: `test_view_statutory_ignores_non_company_data_scope`
grants a caller `EMPLOYEE.VIEW_STATUTORY` at `data_scope='SELF'` with no linked `employee_id` at
all (so `SELF` resolves to nothing) and confirms they still see another employee's statutory
record in full — proving `COMPANY`-wide access is actually granted by holding the permission,
regardless of the stored `data_scope` value, mirroring `test_employee_data_scope.py`'s own tests
for the routes that *do* enforce scope, applied here to prove the negative.

## 11. Effective dating

Implements the pattern locked by `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part B7 exactly:
insert-never-update-in-place, close-then-insert in one transaction, current/as-of/full-history
read shapes identical to `Employment`/`EmployeeAssignment`/`EmployeeCompensation`'s own (field
names substituted). Verified end-to-end by the as-of-date boundary integration test
(`test_list_statutories_as_of_date_boundaries`), and by the raw-insert integration test
(`test_raw_overlapping_insert_rejected_at_database_level`) proving the GiST exclusion constraint
is the real backstop, not just an application-level check.

## 12. Audit behaviour

One event, `STATUTORY_REVISED`, `entity_type="employee_statutory"`, mirroring
`COMPENSATION_REVISED` exactly, via the existing `AuditService.record(...)` call shape. `before`
is `null` for an employee's first statutory row, and the closed row's snapshot otherwise —
verified by `test_create_first_statutory_success`. The termination-triggered close (§7 above)
also records its own `STATUTORY_REVISED` event, mirroring the existing
`ASSIGNMENT_CHANGED`/`COMPENSATION_REVISED` events `terminate_employment` already records. No
`sensitive_access_log` read-path logging was added — that table does not exist in this codebase,
and its build timing is locked to E-10, not E-07 — a real, named compliance gap for the period
between E-07 shipping and E-10 shipping (same gap Compensation already carries), flagged here
explicitly (§17 item 3).

## 13. Tenant / RLS isolation

`ENABLE`/`FORCE ROW LEVEL SECURITY` + `tenant_isolation` policy, applied fresh by this task's own
migration (§4) since this is a genuinely new table. The repository follows the belt-and-suspenders
convention of filtering `company_id` explicitly in every query, not relying on RLS alone. Verified
by `test_cannot_get_statutory_from_other_tenant`,
`test_cannot_create_statutory_for_other_tenant_employee`, and
`test_cannot_list_statutory_from_other_tenant_employee` (the last one confirming the list route
also returns `404`, not an empty list, for a cross-tenant `employee_id`).

## 14. Security review

Explicitly tested, all confirmed:

- **Cross-tenant employee access**: `test_cannot_create_statutory_for_other_tenant_employee` — a
  `POST` against another tenant's employee returns `404`.
- **Cross-tenant statutory access**: `test_cannot_get_statutory_from_other_tenant`,
  `test_cannot_list_statutory_from_other_tenant_employee`.
- **Missing employee_id**: `test_create_statutory_unknown_employee_rejected`,
  `test_get_statutory_not_found`.
- **Missing permission**: `test_list_statutory_without_view_permission_rejected` (zero
  permissions → `403`).
- **Wrong permission**: `test_create_statutory_without_update_sensitive_permission_rejected`
  (`.VIEW_STATUTORY` alone cannot write), `test_create_statutory_with_update_sensitive_permission_
  succeeds` (`.UPDATE_SENSITIVE` alone can write but the same caller then cannot read —
  independence of the two permissions proven in both directions).
- **Non-company scope behavior**: `test_view_statutory_ignores_non_company_data_scope` (§10).
- **Mass assignment**: `test_create_statutory_mass_assignment_rejected` (integration, `version`/
  `company_id` in body → `422`) and `test_statutory_create_mass_assignment_rejected` (unit,
  schema-layer `extra="forbid"`).
- **IDOR**: `test_cannot_list_statutory_from_other_tenant_employee` — list returns `404`, not an
  empty list, so a cross-tenant `employee_id` cannot be distinguished from a nonexistent one by
  response shape.
- **Historical record access**: `test_revision_closes_current_and_requires_full_new_values`
  confirms a closed historical row remains readable by id with its correct `effective_to`.
- **Audit behavior**: `test_create_first_statutory_success` (§12).

## 15. Tests

**20 new unit tests**
(`tests/unit/modules/employee/test_employee_statutory_service.py`): first-statutory success,
no-covering-employment rejection, unknown-employee rejection, revision close-then-insert,
`If-Match` requirement, stale-effective-from rejection, stale-version conflict, the
once-per-FY tax-regime rule (within-FY rejected, across-FY allowed, no-regime-change ignores the
rule), the GiST-overlap-to-domain-error translation, four schema-validation cases (mass
assignment, negative `vpf_amount`, invalid `tax_regime`, PF-applicable-without-`pf_number`
allowed), and four read-path cases (`list`/`get`/`as-of`, including that `get_statutory_as_of`
does not require an employee lookup).

**28 new integration tests**
(`tests/integration/modules/employee/test_employee_statutory.py`, against the real Postgres dev
database): first-statutory success (with audit-row verification), no-covering-employment
rejection, mass-assignment rejection, unknown-employee rejection, invalid-`tax_regime` rejection,
missing-`revision_reason` rejection, negative-`vpf_amount` rejection, PF-applicable-without-
`pf_number` success (proving the deliberate non-enforcement), empty list state, not-found,
as-of-date boundaries, a full revision scenario, missing/stale `If-Match`, invalid effective-from,
the once-per-FY tax-regime rule (within-FY rejected, across-FY allowed, no-regime-change allowed),
the raw-SQL GiST-constraint-bypass test, the full rehire scenario (including the termination-time
close), cross-tenant get/create/list rejection, and six permission-matrix/data-scope tests (no
`.VIEW_STATUTORY` at all; `.UPDATE_SENSITIVE`-only against a `GET`; `.VIEW_STATUTORY`-only cannot
write; `.UPDATE_SENSITIVE` succeeding on its own then failing to read; the `COMPANY`-only
data-scope-discard proof).

Every integration test tears down its own company/employee/employment/statutory rows in a
`finally` block, in FK-safe order (`employee_statutory -> employment -> employee/number_series ->
legal_entity/company/roles/user`, mirroring the compensation test's own teardown shape). Verified
against the dev database after the full suite run: `SELECT count(*) FROM employee_statutory` /
`employee` / `company WHERE name LIKE 'Acme%'` / `"user" WHERE email LIKE 'scoped-stat-%'` all
returned `0`.

## 16. Validation results

```
ruff check .              — All checks passed!
ruff format --check .     — 159 files already formatted (2 auto-reformatted during this task)
mypy src/hrms              — Success: no issues found in 73 source files
lint-imports                — Contracts: 1 kept, 0 broken
pytest                     — 555 passed (507 pre-existing + 48 new)
```

All five checks were run against the **whole backend**, not just this slice's own files. The
pre-existing Employee/Employment/Assignment/Compensation/RBAC-data-scope/organisation suites all
continue to pass, with two required updates: the `EMPLOYEE_VIEW_STATUTORY`/
`EMPLOYEE_UPDATE_SENSITIVE` permission-set assertion in `test_registration_flow.py` (§3), and the
`_statutory_repo` mock addition to `test_employment_service.py`'s `service` fixture (§3) — both
the smallest possible fix for a real, correctly-caused failure (a new permission code; a new
repository dependency on `EmploymentService`), not a weakening of any existing assertion.

No manual UI verification was performed or claimed — E-07 is backend-only per its own scope; no
`apps/web/` file was touched.

## 17. Known limitations

1. **No `sensitive_access_log` read-path logging** — statutory data is treated as RESTRICTED by
   inference (no document names PF/ESI/tax-regime fields in the RBAC matrix's own RESTRICTED
   list by name, plan §6/§11.1), but read-path logging beyond the ordinary write-path
   `AuditService` calls is out of scope: `sensitive_access_log` does not exist anywhere in this
   codebase, and its build timing is locked to E-10. Same gap Compensation already carries.
2. **`COMPANY`-only data-scope posture is a deliberate, named gap, not an oversight** (§10) — but
   worth restating here per plan §24 item 4: a future reviewer who assumes E-07 "just follows
   E-06" without reading this section could miss that this was an explicit, considered choice
   with two rejected alternatives (`SELF`, `REPORTEES`/`REPORTEE_TREE`), not a default inherited
   unthinkingly.
3. **PF/ESI applicability-vs-identifier correlation is not enforced** — `is_pf_applicable=true`
   with `pf_number=null` succeeds; same for `is_esi_applicable`/`esi_ip_number`. Deliberate,
   per plan §17/§26 item 6 — no document requires this correlation.
4. **Legal-entity-registration correlation is not enforced** — whether `is_pf_applicable`/
   `is_esi_applicable` should be validated against the employing legal entity's own
   `pf_code`/`esi_code` is an open, undocumented question (plan §10/§26 item 7).
5. **`pf_number` carry-forward on rehire remains undecided** — a rejoining employee's first
   statutory row states its own `pf_number` explicitly (no carry-forward exists for any field on
   any write, by design), so this is not a functional gap, but the *product* question of whether
   the same PF number should be expected/pre-filled on rejoin is genuinely undecided (plan §9/§26
   item 4) and this slice does not invent an answer.
6. **Fiscal-year boundary (April-March) is this task's own engineering assumption** for the
   once-per-FY tax-regime-switch rule (FR-PAY-006) — no source document defines the FY boundary
   (plan §17/§26 item 5). If product defines a different boundary later, `_fiscal_year` in
   `service.py` is the single point of change.
7. **No masking format** for `pf_number`/`esi_ip_number`/`tax_regime`/etc. — whole-sub-resource
   gating only, per the plan's own recommended default (plan §6/§26 item 3).
8. **Payroll-lock-period backdating enforcement is not implementable** — Payroll doesn't exist
   yet; any past `effective_from` is currently accepted without a lock-period check, the same
   known limitation Assignment/Compensation/Employment already carry.

## 18. Payroll integration boundary

`EmployeeStatutoryService.get_statutory_as_of(company_id, employee_id, as_of) -> StatutoryRead |
None` is the sole contract this slice exposes to Payroll — mirrors `get_compensation_as_of`
exactly, does not assert employee existence. Per `docs/adr/0005-payroll-snapshot-immutability.md`'s
documented pipeline (create run → snapshot inputs, including "statutory master versions," into an
immutable `payrun_input_snapshot` → compute as a pure function of the snapshot → validate →
review → finalise), Payroll will call this method **once per pay run, at snapshot time only** —
not repeatedly during computation. No rate table, PF/ESI/PT percentage, tax slab, or any
calculation logic was added anywhere in this diff; `employee_statutory` stores only the raw
employee-owned inputs Payroll will snapshot from. No `payrun_*` table, model, or reference exists
in this codebase, and none was added here.

## 19. Explicit exclusions

Confirmed by inspecting `git status`/`git diff --stat` before writing this report:

- **No Banking (E-08)** — no `employee_bank` code was added or modified; no such table exists.
- **No frontend (E-09)** — `apps/web/` is untouched.
- **No E-10 work** — no `sensitive_access_log` table/model/migration.
- **No new RBAC scope levels** — `DEPARTMENT`/`BRANCH`/`LEGAL_ENTITY`/`ALL_COMPANIES` remain
  absent from `DataScopeLevel`; not referenced anywhere in this diff.
- **No approval-workflow fields** — no `approved_by`/`approval_request_id`-shaped column added.
- **No tax/payroll calculation engine** — confirmed by §18 above.
- **No UAN/PAN/Aadhaar/bank field** — `employee.uan_number`/`pan_number_enc`/
  `aadhaar_number_enc` are unchanged, untouched by this migration or any code in this diff.
- **No Attendance, Leave, Exit, ATS, Recruitment, Performance, or Workflow automation** — no such
  modules or tables exist in this diff.
- **No BR-14 shift/notice-period override chain** — not referenced anywhere in this slice's code.
- **No `organisation`/`identity` module changes** beyond the one test assertion (§3).
- **Employment lifecycle behavior was modified once, deliberately** (§7's
  `terminate_employment` addition) — because the plan explicitly requires "last row closed" on
  exit (plan §9), not as an unrequested expansion of scope. No other Employment lifecycle
  behavior was touched.

The diff this task is responsible for is confined to: `modules/employee/*` (models, exceptions,
repository, schemas, service, permissions, dependencies, router), one new Alembic migration, three
new test files (two unit-fixture-scale additions to pre-existing files), one updated permission-
set test assertion, and three new documentation files.

## 20. Open decisions

None blocking — every choice this task made either follows directly from a plan-documented
engineering decision (plan §27, cited by number throughout this report) or, where the plan named
a genuine product decision (plan §26), adopted the plan's own recommended default with the
rationale restated here (§10, §17 items 3-6). Nothing was invented without a source:

- Permission code names, `COMPANY`-only data-scope posture, no masking format, `pf_number`
  rehire-carry-forward, April-March FY boundary, and the two open correlation questions are all
  named explicitly in §17 as inherited-from-plan, non-blocking items — not silently resolved.

## 21. Recommended next step

**E-08 — Banking** is the next slice named in the locked sequence
(`01_EMPLOYEE_MODULE_PLAN.md` §2), following the same pattern E-07 just established. Its own
table does not yet exist in the live schema or in any documentation anywhere in this repository
(confirmed by a fresh search during this task's own investigation, plan §2/§9) — a genuinely
greenfield investigation, not a re-verification like this task's own `21_` → `29_` supersession.
Before starting, that investigation should confirm the same class of question this task's plan
resolved for Statutory: is `employee_bank` keyed on `employee_id` (matching Assignment/
Compensation/Statutory's own rehire-correctness shape) or something else, and what the
`EMPLOYEE.UPDATE_SENSITIVE` permission's scope should include once a second sub-resource shares
it with Statutory (this task deliberately scoped `.UPDATE_SENSITIVE` to the statutory `POST`
route only, per plan §14 — E-08 will need its own explicit decision about whether to reuse or
split this code).
