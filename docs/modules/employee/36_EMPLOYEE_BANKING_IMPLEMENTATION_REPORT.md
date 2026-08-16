# Employee Banking (E-08) — Implementation Report

Closeout report for the Employee Banking vertical slice, built per
`33_EMPLOYEE_BANKING_IMPLEMENTATION_PLAN.md` (the investigation/plan that preceded this task).
Builds directly on E-01 (Employee Foundation), E-03 (Employment Lifecycle), E-04 (Employee
Assignment), E-06 (Employee Compensation), E-07 (Employee Statutory), and the RBAC data-scope
(`24`-`26`) and reporting-manager-security (`27`-`28`) slices.

**Note on starting state**: at the start of this task, the working tree already carried
uncommitted changes from E-07 and the prior RBAC-data-scope/reporting-manager-security work (per
`git status` at session start: `models.py`, `repository.py`, `schemas.py`, `service.py`,
`permissions.py`, `router.py`, `dependencies.py`, `exceptions.py`, and several test files were
already modified with E-07's own Statutory implementation; the migrations
`20260815120000_role_permission_data_scope.py`/`20260815130000_employee_statutory.py` and their
tests were already new/untracked, as was `33_EMPLOYEE_BANKING_IMPLEMENTATION_PLAN.md` itself).
This report describes only what **this task** added on top of that baseline.

---

## 1. Status

**COMPLETE**, for the scope authorized by the plan and the task instructions. `EmployeeBank` ORM
model, repository, service, router, schemas, exceptions, and permissions are all implemented; the
migration is applied and verified against the dev database (upgrade → schema inspection →
downgrade → schema inspection → upgrade, clean and repeatable); 52 new tests (23 unit + 29
integration) pass; the full backend suite (607 tests: 555 pre-existing + 52 new) passes; `ruff
check`, `ruff format --check`, `mypy src/hrms`, and `lint-imports` all pass clean against the
whole repo.

Two gates named in the task instructions as potential stop conditions were resolved without
blocking implementation — both are restated in full at §8/§9 below, not silently assumed:

1. **PD-1 (data-scope posture)**: `RBAC_DATA_SCOPE_DECISIONS.md` Decision E is **LOCKED** and
   explicitly names `SELF`-scoped self-service as Banking's intended default. This is not merely
   the plan's own recommendation (§15 PD-1 Option 2) — it is an actual locked cross-cutting
   decision, so this slice implements it directly rather than treating it as an open question.
2. **PD-4 (encryption)**: confirmed by direct search — no encryption mechanism (KMS,
   `TypeDecorator`, Fernet) exists anywhere in this codebase, and `employee.pan_number_enc`/
   `aadhaar_number_enc` are already plaintext. Building a real encryption mechanism is explicitly
   named as out of this slice's scope by the plan itself (§23). The only option available within
   scope is therefore Decision D-2's Option 2 (ship the plaintext column, documented as an
   accepted, non-blocking risk on *production data*, not on *code*) — which is what this slice
   does. **No fake encryption, base64 encoding, or hashing was used anywhere.**

Frontend (E-09), Payroll (any module), and E-10's `sensitive_access_log` are **not** part of this
task and were not built — confirmed by the scope audit in §19/§20 below.

## 2. Files created

```
apps/api/alembic/versions/20260815140000_employee_bank.py
apps/api/tests/unit/modules/employee/test_employee_bank_service.py
apps/api/tests/integration/modules/employee/test_employee_banking.py
docs/modules/employee/34_EMPLOYEE_BANKING_MODULE.md
docs/modules/employee/35_EMPLOYEE_BANKING_API.md
docs/modules/employee/36_EMPLOYEE_BANKING_IMPLEMENTATION_REPORT.md  (this document)
```

(`docs/modules/employee/33_EMPLOYEE_BANKING_IMPLEMENTATION_PLAN.md` was already present in the
working tree at session start, per the `<ide_selection>` this task opened with — created by the
prior investigation task, not this one; listed here only for completeness of the paper trail.)

## 3. Files modified

All eight `modules/employee/*.py` files already carried E-07's own uncommitted changes at session
start; this task's additions are layered on top of that baseline, described precisely:

```
apps/api/src/hrms/modules/employee/models.py
    (this task added: EmployeeBank ORM model, 33 lines + docstring)
apps/api/src/hrms/modules/employee/exceptions.py
    (this task added: BankDatesOverlapError, BankVersionRequiredError — 2 new exception classes)
apps/api/src/hrms/modules/employee/repository.py
    (this task added: EmployeeBankRepository — insert_bank, get_current_bank, get_bank_as_of,
    list_banks, get_bank, close_bank)
apps/api/src/hrms/modules/employee/schemas.py
    (this task added: BankCreate/BankRead + bank_to_read/bank_to_audit_dict, PAYMENT_MODE_VALUES)
apps/api/src/hrms/modules/employee/service.py
    (this task added: EmployeeBankService — create_bank, list_banks, get_bank, get_bank_as_of,
    plus the _assert_employee_visible data-scope helper. Deliberately did NOT modify
    EmploymentService.terminate_employment — see §11.)
apps/api/src/hrms/modules/employee/permissions.py
    (this task added: EMPLOYEE_VIEW_BANKING constant + EMPLOYEE_PERMISSIONS entry; widened
    EMPLOYEE_UPDATE_SENSITIVE's documented *usage*, not its definition, to the Banking POST route)
apps/api/src/hrms/modules/employee/router.py
    (this task added: list_banks/get_bank/create_bank routes under /v1/employees/{employee_id}/
    bank*, with the two GET routes resolving and passing the caller's DataScope — see §9)
apps/api/src/hrms/modules/employee/dependencies.py
    (this task added: get_employee_bank_service)
```

One file, already carrying E-07's own one-line-per-code update, received this task's own
identical mechanical update:

```
apps/api/tests/integration/modules/organisation/test_registration_flow.py
    (added EMPLOYEE.VIEW_BANKING to the expected COMPANY_ADMIN permission set — register_company
    grants every EMPLOYEE_PERMISSIONS code automatically, so the newly registered company's admin
    now also holds this one)
```

No file inside `modules/organisation/`, `modules/identity/`, `modules/statutory`-adjacent test
files, or `apps/web/` was modified. `app.py` required no change — `employee_router` was already
registered by E-01; `seed/bootstrap.py` required no change — `EMPLOYEE_PERMISSIONS` is iterated
dynamically, so the new code was picked up automatically, the same mechanism every prior slice
relied on for its own new codes.

## 4. Database changes

One migration, `20260815140000_employee_bank.py`, revising `20260815130000` (the Statutory
migration, confirmed as the live head in the dev database before this task started). Applied and
verified against the dev database.

**Pre-migration state** (confirmed by direct `information_schema.columns`/`\dt` inspection before
writing the migration): `employee_bank` did not exist; no column anywhere matched
`%bank%`/`%account%`/`%ifsc%`/`%payment%`/`%cheque%`.

**Migration content** — a genuine foundational `CREATE TABLE` (plan §2/§19/§22 — this table has
no pre-existing skeleton): the full column set from plan §6's literal DDL, with **no** deviation
(unlike Statutory, which added one column, `revision_reason`, beyond its own plan's literal DDL —
no source document requires an equivalent field for Banking, so none was added, per plan §5/§13).
Plus:
- `employee_bank_no_overlap` GiST exclusion constraint on `(employee_id, daterange(...))`.
- Two indexes: `employee_bank_company_id_idx`, `employee_bank_employee_id_effective_from_idx`.
- FKs to `company(id)` and `employee(id)`, both `ON DELETE RESTRICT`.
- RLS: `ENABLE`/`FORCE ROW LEVEL SECURITY` + `tenant_isolation` policy on `company_id`.

**Post-migration verification** (direct `information_schema`/`pg_constraint`/`pg_indexes`/
`pg_class` queries, this session): all 18 columns present with correct types/defaults/
nullability; primary key on `id`; both FKs present; GiST exclusion constraint present with the
exact `employee_id WITH =, daterange(...) WITH &&` shape; both indexes present (plus the
constraint-backing GiST index and the primary-key index — no redundant index was added beyond
what the constraint itself requires); RLS both enabled and forced with the `tenant_isolation`
policy present.

**Idempotency proof**: `alembic upgrade head` → schema inspected (18 columns, 4 constraints, 4
indexes, RLS forced, as above) → `alembic downgrade -1` (table dropped, confirmed by a direct
`information_schema.tables` existence check returning `false`) → `alembic upgrade head` (table
recreated) → `alembic current` confirmed back at `20260815140000 (head)`. `SELECT count(*) FROM
employee_bank` returned `0` after the final upgrade and again after the full test suite ran — no
test rows were left behind.

`employee`, `employment`, `employee_assignment`, `employee_compensation`, `employee_statutory`,
`legal_entity`, and every other table were **not** touched by this migration.

## 5. ORM model

`EmployeeBank` added to `apps/api/src/hrms/modules/employee/models.py`, alongside
`Employee`/`Employment`/`EmployeeAssignment`/`EmployeeCompensation`/`EmployeeStatutory`/
`NumberSeries`. Keyed on `employee_id`, not `employment_id` (plan §6) — no FK to `employment` or
`legal_entity`. `account_number_enc` mapped as a plain `String` (`TEXT` at the DB layer) — see §8
for why this is not a code-level gap in this slice's own scope.

## 6. Repository

`EmployeeBankRepository`, mirroring `EmployeeStatutoryRepository`'s exact shape: `insert_bank`,
`get_current_bank` (`effective_to IS NULL`), `get_bank_as_of` (the shared as-of-date contract),
`list_banks`, `get_bank`, `close_bank` (the one allowed mutation — sets only `effective_to`,
version-gated). No general `update_bank(values=...)` method exists — deliberate, since no
document names a path that edits a historical row's business columns. `close_bank` exists on the
repository (used by `create_bank`'s own revision path) but is **never called** from
`EmploymentService.terminate_employment` — see §11.

## 7. Service / business rules

`EmployeeBankService.create_bank` is the single write operation. Steps, in order:

1. Assert the employee exists and belongs to the tenant (`404` otherwise).
2. Resolve the covering employment episode via `EmploymentRepository.get_employment_as_of`
   (`409 NO_ACTIVE_EMPLOYMENT` if none covers `effective_from`) — reused exactly as Statutory
   does (plan §15 PD-2 Option 1, the smallest-diff choice; see §12's known-limitation note for
   what this does *not* cover).
3. Read the current bank row, if any.
   - **No current row**: nothing conditionally required.
   - **Current row exists**: `effective_from` must be strictly after the current row's own
     (`422 INVALID_EFFECTIVE_FROM` otherwise); `If-Match` is required
     (`422 BANK_VERSION_REQUIRED` otherwise).
4. No reference validation beyond the employee existence check in step 1.
5. If a current row exists, close it (`effective_to = new.effective_from - 1 day`),
   version-gated (`409 STALE_RESOURCE` on mismatch).
6. Insert the new row — `is_primary=true`, `verification_status="PENDING"`,
   `penny_drop_reference=null` unconditionally, system-set (none of the three are accepted fields
   in `BankCreate` at all) — translating an `IntegrityError` from the GiST exclusion constraint
   into `409 BANK_DATES_OVERLAP` (the race-condition backstop).
7. Record one `BANK_REVISED` audit event.

Plus read methods: `list_banks` (full history or `as_of`, data-scope-aware — §9), `get_bank`
(single row, data-scope-aware), and `get_bank_as_of` (the shared cross-module contract,
deliberately not asserting employee existence — a nonexistent `employee_id` simply yields no
covering row, and this method is never data-scope-filtered, since it is an internal cross-module
contract, not a route).

## 8. Encryption decision (PD-4) — resolved without blocking implementation

Restated in full, since this is the task's own named stop-condition gate:

- **Investigated**: grepped `apps/api/src` for `Fernet|KMS|TypeDecorator|encrypt|
  ENCRYPTION_KEY|cryptography\.` — zero matches (the only `cryptography` reference in the repo is
  `python-jose[cryptography]`, JWT signing, unrelated). `employee.pan_number_enc`/
  `aadhaar_number_enc` are confirmed plain `String` columns in the live ORM, with no
  `TypeDecorator` wrapper anywhere.
- **No approved encryption mechanism exists.** Per the task's own instruction, this rules out
  building real encryption *as part of this slice* only insofar as the plan itself already scopes
  building the mechanism out (`33_...PLAN.md` §23: "real column-level encryption implementation
  (§14/PD-4 names the decision; building the `TypeDecorator`/KMS mechanism itself is not part of
  this plan)"). No fake encryption, base64 encoding, or hashing was substituted — `account_
  number_enc` is a plain `TEXT` column, named honestly for what it is in the migration's own
  docstring and this report.
- **Resolution applied**: `HRMS_SYSTEM_DESIGN_BASELINE.md` Decision D-2's Option 2 — ship the
  schema/code/tests now (against synthetic dev-database values only, exactly as every prior
  Employee slice has done), with the gap documented as an accepted, non-blocking risk that gates
  **production data**, not **this slice's code**. This is not a silent default: it is the only
  option available given (a) no mechanism exists, and (b) building one is explicitly out of this
  plan's scope.
- **What remains gated**: real account numbers must not be written to `account_number_enc` in a
  production environment until either a real encryption mechanism is built, or an explicit,
  documented compliance sign-off accepts the gap with a stated remediation date. This is named
  again at §17 (known limitations) and §18 (open decisions) — not buried here alone.

## 9. Data-scope decision (PD-1) — resolved via a locked decision, not a recommendation

Restated in full, since this is the task's own named stop-condition gate:

- **Investigated**: `RBAC_DATA_SCOPE_DECISIONS.md` Decision E, quoted in full — status
  **LOCKED**, table row for "Own statutory / banking (once built, E-07/E-08)": *"Yes, same
  pattern as compensation — own record, separate permission code (`EMPLOYEE.VIEW_STATUTORY`/
  `.VIEW_BANKING`), `SELF`-scoped by default so an employee can verify their own PF number / bank
  account."*
- **This is not merely the Banking plan's own recommendation** (though it agrees, §15 PD-1
  Option 2) — it is an actual locked cross-cutting architecture decision that predates this task.
  Per the task's own instruction ("If the repository/project already contains a locked product
  decision resolving PD-1, follow it"), this slice implements `SELF`-scoping directly rather than
  treating PD-1 as unresolved.
- **What was built**: `EMPLOYEE.VIEW_BANKING`'s two `GET` routes (`list_banks`, `get_bank`)
  resolve the caller's `DataScope` via `require_permission` and pass it, plus the caller's own
  `employee_id`, to `EmployeeBankService`, which binds it through
  `EmployeeService.resolve_visible_employee_ids` — the exact mechanism `GET /employees`/
  `GET /employees/{id}` already use, reused rather than re-derived. An out-of-scope
  `employee_id` in the path returns `404`, identical in shape to a nonexistent or cross-tenant
  id. `create_bank` (the write route) is **not** data-scoped — `COMPANY`-wide, matching every
  other write route in this module (data-scoping writes is separately-sequenced follow-up work
  per `25_EMPLOYEE_RBAC_DATA_SCOPE_IMPLEMENTATION_PLAN.md` §22, unrelated to this decision).
- **Consequence, named not hidden**: this creates a visible inconsistency with Statutory
  (`COMPANY`-only, per E-07's own deliberate, plan-documented deviation from this same locked
  decision). This slice does **not** retrofit `EMPLOYEE.VIEW_STATUTORY` to match — the Banking
  plan itself frames that retrofit as a fast-follow, not a blocker, and retrofitting a
  *different, already-shipped* slice's behavior is outside this task's own scope-control
  instructions ("do not modify unrelated modules unless absolutely required").
- **Positive and negative proof**: `test_view_banking_self_scope_sees_own_record_only` (a
  `SELF`-scoped caller sees their own record, not another employee's — `404`, not `403`),
  `test_view_banking_self_scope_no_employee_id_sees_nothing` (fails closed, never falls back to
  `COMPANY`), `test_view_banking_company_scope_sees_any_employee` (`COMPANY` scope is unaffected
  by wiring `SELF` for this code).

## 10. API endpoints

| Method | Path | Permission | Data scope | Notes |
|---|---|---|---|---|
| GET | `/v1/employees/{employee_id}/bank` | `EMPLOYEE.VIEW_BANKING` | `SELF`/`REPORTEES`/`REPORTEE_TREE`/`COMPANY`, resolved | Full history, or `?as_of=` for the covering row |
| GET | `/v1/employees/{employee_id}/bank/{bank_id}` | `EMPLOYEE.VIEW_BANKING` | Same as above | Single row by id |
| POST | `/v1/employees/{employee_id}/bank` | `EMPLOYEE.UPDATE_SENSITIVE` | Not scoped (`COMPANY`-wide) | Closes current row (if any), inserts new row |

Full request/response/error-code reference: `35_EMPLOYEE_BANKING_API.md`.

**Path naming — a deliberate deviation from this task's own inline "expected shape" text,
resolved in favor of the authoritative plan document.** This task's own instructions named the
route shape twice, inconsistently: the authoritative-plan pointer says "Implement the API exactly
as specified by: `33_EMPLOYEE_BANKING_IMPLEMENTATION_PLAN.md`," but the task's own inline
"Expected shape" text separately wrote `/employees/{employee_id}/banking`. The plan document
itself (§20, its own API Design section, and consistently throughout §1–§23) specifies
`/v1/employees/{employee_id}/bank` — a singular noun matching every sibling sub-resource's own
naming (`/statutory`, `/compensation`, `/assignments`, `/employments`), not a gerund. This report
follows the plan document's own explicit, repeated, internally-consistent path, treating the
task's inline paraphrase as the less authoritative of the two conflicting sources — named here
explicitly so a reviewer comparing this report against the original task text does not mistake
the choice for an oversight.

## 11. Termination / F&F behavior — the load-bearing difference from every sibling

**No change was made to `EmploymentService.terminate_employment`.** This is the task's own
explicit instruction, backed by a locked architecture decision
(`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part C "Employee Bank"): the current bank row must
remain open through and after exit, since it is still needed for full-and-final settlement payout
after the employee has left. Verified directly:
`test_bank_row_not_closed_by_terminate_employment` confirms the current row's `effective_to`
remains `null` and its `version` unchanged after `terminate_employment` runs, and that no
`BANK_REVISED` audit event is written by termination itself (exactly one audit row exists — the
original create).

**Consequence for rehire, verified explicitly**: because the pre-exit row is never auto-closed,
a rehire's first bank write does **not** take the "no current row" branch every other
effective-dated sub-resource's rehire write takes — it still finds the pre-exit row "current"
and must take the close-then-insert branch, requiring `If-Match` against the pre-exit row's own
version. `test_rehire_first_bank_write_requires_if_match` proves both halves: a rehire write
without `If-Match` is rejected (`422 BANK_VERSION_REQUIRED`), and the correct `If-Match` succeeds,
closing the pre-exit row at the day before the rehire's `effective_from`.

## 12. Known limitation carried from the plan — F&F correction-after-exit gap

`create_bank` reuses `EmploymentRepository.get_employment_as_of` unchanged (plan §15 PD-2 Option
1, this task's chosen default, the smallest-diff option). Consequence: a bank-detail correction
dated *strictly after* an employee's `last_working_day` — the literal full-and-final-settlement-
correction scenario §11's own termination-survival behavior anticipates needing — still finds no
covering employment episode and is rejected with `409 NO_ACTIVE_EMPLOYMENT` under this slice's
shipped behavior. A correction dated on-or-before `last_working_day` succeeds (it falls within
the just-closed episode's range). This is named as a known, non-blocking limitation, not silently
accepted — the plan's own PD-2 discusses two other options and does not adopt either
unilaterally, since no source document specifies a precise rule for the post-exit-correction case.

## 13. Audit behaviour

One event, `BANK_REVISED`, `entity_type="employee_bank"`, mirroring `STATUTORY_REVISED` exactly,
via the existing `AuditService.record(...)` call shape. `before` is `null` for an employee's
first bank row, and the closed row's snapshot otherwise — verified by
`test_create_first_bank_success`. Unlike Statutory, **no termination-triggered audit event
exists** for Banking, since termination never touches this table (§11) —
`test_bank_row_not_closed_by_terminate_employment` positively confirms exactly one audit row
exists after termination, not two. Audit `before`/`after` snapshots are built from the same
`BankRead` model the API itself returns (`bank_to_audit_dict`) — verified by
`test_bank_audit_snapshot_uses_response_model_convention` to contain no field beyond what the API
response itself would ever expose. Audit payloads remain plain JSONB, unencrypted — the same
pre-existing, project-wide limitation Compensation/Statutory already carry, not new to Banking.

## 14. Tenant / RLS isolation

`ENABLE`/`FORCE ROW LEVEL SECURITY` + `tenant_isolation` policy, applied fresh by this task's own
migration (§4), since this is a genuinely new table. The repository follows the
belt-and-suspenders convention of filtering `company_id` explicitly in every query, not relying
on RLS alone. Verified by `test_cannot_get_bank_from_other_tenant`,
`test_cannot_create_bank_for_other_tenant_employee`, and
`test_cannot_list_bank_from_other_tenant_employee` (the last confirming the list route also
returns `404`, not an empty list, for a cross-tenant `employee_id`).

## 15. Security review

Explicitly tested, all confirmed:

- **Cross-tenant employee access**: `test_cannot_create_bank_for_other_tenant_employee` — a
  `POST` against another tenant's employee returns `404`.
- **Cross-tenant bank access**: `test_cannot_get_bank_from_other_tenant`,
  `test_cannot_list_bank_from_other_tenant_employee`.
- **Missing employee_id**: `test_create_bank_unknown_employee_rejected`,
  `test_get_bank_not_found`.
- **Missing permission**: `test_list_bank_without_view_permission_rejected` (zero permissions →
  `403`).
- **Wrong permission**: `test_create_bank_without_update_sensitive_permission_rejected`
  (`.VIEW_BANKING` alone cannot write), `test_create_bank_with_update_sensitive_permission_
  succeeds` (`.UPDATE_SENSITIVE` alone can write but the same caller then cannot read —
  independence of the two permissions proven in both directions).
- **Data-scope wiring (the opposite direction from Statutory's own test)**:
  `test_view_banking_self_scope_sees_own_record_only`,
  `test_view_banking_self_scope_no_employee_id_sees_nothing`,
  `test_view_banking_company_scope_sees_any_employee` (§9).
- **Mass assignment**: `test_create_bank_mass_assignment_rejected` (integration, `version`/
  `is_primary`/`verification_status` in body → `422`) and three unit-level schema tests
  (`test_bank_create_mass_assignment_rejected`, `test_bank_create_is_primary_not_client_
  settable`, `test_bank_create_verification_status_not_client_settable`).
- **IDOR**: `test_cannot_list_bank_from_other_tenant_employee` — list returns `404`, not an empty
  list, so a cross-tenant `employee_id` cannot be distinguished from a nonexistent one by response
  shape.
- **Sensitive-field exposure**: `test_account_number_absent_without_view_banking_permission` —
  without `.VIEW_BANKING` the entire resource is `403`, and `account_number_enc` never appears in
  the response body text at all (whole-sub-resource gating, no partial-masking infrastructure
  exists or was built, matching every RESTRICTED-field precedent in this codebase).
- **Audit behavior / exposure**: `test_create_first_bank_success`,
  `test_bank_audit_snapshot_uses_response_model_convention` (§13).
- **Historical record access**: `test_revision_closes_current_and_inserts_new` confirms a closed
  historical row remains readable by id with its correct `effective_to`.

No plaintext account number is ever written to application logs — this slice adds no new logging
statement anywhere in `service.py`/`router.py`/`repository.py`; the only place
`account_number_enc` is read or written is the ORM row itself and the Pydantic
request/response models, neither of which this codebase logs.

## 16. Tests

**23 new unit tests**
(`tests/unit/modules/employee/test_employee_bank_service.py`): first-bank success (including the
system-managed-fields defaulting check), no-covering-employment rejection, unknown-employee
rejection, revision close-then-insert, `If-Match` requirement, stale-effective-from rejection,
stale-version conflict, the GiST-overlap-to-domain-error translation, six schema-validation cases
(mass assignment, `is_primary`/`verification_status` not client-settable, invalid/missing
`payment_mode`, minimal-fields-allowed), four read-path cases (`list`/`get`/`as-of`, including
that `get_bank_as_of` does not require an employee lookup), and three data-scope-wiring cases
(scope-`None` preserves unscoped behavior, `SELF` scope resolves and passes visible IDs, a
`SELF`-scoped caller sees their own record).

**29 new integration tests**
(`tests/integration/modules/employee/test_employee_banking.py`, against the real Postgres dev
database): first-bank success (with audit-row verification), no-covering-employment rejection,
mass-assignment rejection, unknown-employee rejection, invalid/missing-`payment_mode` rejection,
minimal-fields-allowed success, empty list state, not-found, as-of-date boundaries, a full
revision scenario, missing/stale `If-Match`, invalid effective-from, the raw-SQL
GiST-constraint-bypass test, the termination-survival test (§11), the full rehire scenario
requiring `If-Match` on the first post-rejoin write (§11), cross-tenant get/create/list
rejection, six permission-matrix tests, three data-scope tests (§9), and two sensitive-field/
audit-exposure tests (§15).

Every integration test tears down its own company/employee/employment/bank rows in a `finally`
block, in FK-safe order (`employee_bank -> employment -> employee/number_series ->
legal_entity/company/roles/user`, mirroring the statutory test's own teardown shape). Verified
against the dev database after the full suite run: `SELECT count(*) FROM employee_bank` returned
`0`; `SELECT count(*) FROM "user" WHERE email LIKE 'scoped-bank-%'` returned `0`.

## 17. Validation results

```
pytest                     — 607 passed (555 pre-existing + 52 new)
ruff check .                — All checks passed!
ruff format --check .       — 162 files already formatted (3 auto-reformatted during this task)
mypy src/hrms                — Success: no issues found in 73 source files
lint-imports                 — Contracts: 1 kept, 0 broken
```

All five checks were run against the **whole backend**, not just this slice's own files. The
pre-existing Employee/Employment/Assignment/Compensation/Statutory/RBAC-data-scope/organisation
suites all continue to pass, with one required update: the `EMPLOYEE_VIEW_BANKING` permission-set
assertion in `test_registration_flow.py` (§3) — the smallest possible fix for a real,
correctly-caused failure (a new permission code granted automatically to every registered
company's admin role), not a weakening of any existing assertion.

No manual UI verification was performed or claimed — E-08 is backend-only per its own scope; no
`apps/web/` file was touched.

## 18. Known limitations

1. **`account_number_enc` is plaintext** — the single most important item in this report, restated
   a third time deliberately: real account numbers must not be written to this column in
   production before either a real encryption mechanism is built, or an explicit, documented
   compliance sign-off accepts the gap with a stated remediation date (§8).
2. **F&F correction-after-exit gap** — a bank correction dated strictly after `last_working_day`
   is rejected with `409 NO_ACTIVE_EMPLOYMENT` under this slice's shipped behavior, even though
   the termination-survival design's own stated purpose is to support exactly that kind of
   post-exit correction (§12).
3. **`COMPANY`-vs-`SELF` inconsistency with Statutory is a real, visible product-facing gap**, not
   silently resolved — two structurally identical RESTRICTED sub-resources now behave differently
   on data-scope, deliberately, per §9. A fast-follow retrofit of `EMPLOYEE.VIEW_STATUTORY` to
   match is recommended by the Banking plan itself but explicitly not made by this task.
4. **No IFSC format validation** — only the 15-character column-length bound is enforced; the
   public `^[A-Z]{4}0[A-Z0-9]{6}$` format is not sourced from any document in this repository and
   was not invented here (plan §13).
5. **No masking format** for `account_number_enc`/etc. — whole-sub-resource gating only, per the
   plan's own recommended default (plan §15 PD-3).
6. **No verification workflow** — `verification_status` is always `PENDING`; no penny-drop
   provider or manual-verification action exists (plan §12).
7. **No `sensitive_access_log` read-path logging** — same gap Compensation/Statutory already
   carry; build timing is locked to E-10, not E-08.
8. **Payroll-lock-period backdating enforcement is not implementable** — Payroll doesn't exist
   yet; the same known limitation Assignment/Compensation/Statutory already carry.
9. **Duplicate-account-number detection across employees (FR-PAY-015)** — explicitly Payroll's
   own concern; no uniqueness constraint exists on `account_number_enc` at this layer.

## 19. Open decisions

None blocking implementation. Both decisions the task instructions named as potential stop
conditions (PD-1, PD-4) were resolved without inventing a new product decision — PD-1 by
following an already-locked cross-cutting decision (§9), PD-4 by applying the only in-scope
option given the plan's own explicit exclusion of building an encryption mechanism (§8). The
remaining named-but-non-blocking items from the plan (§15 PD-2 correction-after-exit rule, PD-3
masking format) retain the plan's own recommended defaults, restated at §12/§18 items 2/5 —
neither was silently resolved differently from what the plan itself proposed.

The genuinely product-facing consequence worth a real decision, not a code question: whether
`EMPLOYEE.VIEW_STATUTORY` should be retrofitted to `SELF`-scoping to match Banking (§18 item 3),
and whether/when the F&F-correction-after-exit gap (§18 item 2) should be closed with a
Banking-specific rule. Both are named, neither is invented here.

## 20. Explicit exclusions

Confirmed by inspecting `git status`/`git diff` before writing this report:

- **No Payroll** — no `bank_advice` generation, no NEFT/RTGS/IMPS file format, no funds-transfer
  code of any kind, anywhere in this diff.
- **No frontend (E-09)** — `apps/web/` is untouched.
- **No E-10 work** — no `sensitive_access_log` table/model/migration.
- **No new RBAC scope levels** — `DEPARTMENT`/`BRANCH`/`LEGAL_ENTITY`/`ALL_COMPANIES` remain
  absent from `DataScopeLevel`; not referenced anywhere in this diff.
- **No real encryption mechanism** — confirmed by §8; only the schema/code shape was built.
- **No approval-workflow fields**, no tax/payroll calculation, no bank/payment-provider
  integration, no penny-drop verification — none appear anywhere in this diff.
- **No Attendance, Leave, Exit, ATS, Recruitment, Performance, or Workflow automation** — no such
  modules or tables exist in this diff.
- **No BR-14 shift/notice-period override chain** — not referenced anywhere in this slice's code.
- **No `organisation`/`identity` module changes** beyond the one test assertion (§3).
- **`EmploymentService.terminate_employment` was explicitly NOT modified** (§11) — the one
  instruction this task was given not to do, verified by `git diff` showing zero changes inside
  that method's own body.

The diff this task is responsible for is confined to: `modules/employee/*` (models, exceptions,
repository, schemas, service, permissions, dependencies, router), one new Alembic migration, two
new test files, one updated permission-set test assertion, and three new documentation files.

## 21. Recommended next step

Per the locked sequencing (`HRMS_SYSTEM_DESIGN_BASELINE.md` §21 row 9), **`sensitive_access_log`
(E-10 core)** is next in line — its own stated dependency is "Statutory/Banking existing (so
there's something worth logging reads of)," which is now satisfied by this slice. Before starting
that work, two items from this report are worth resolving explicitly rather than carrying forward
silently a third time:

1. **PD-4's production-data gate (§8/§18 item 1)** — a real encryption mechanism, or an explicit,
   documented compliance sign-off accepting the plaintext-`account_number_enc` risk with a stated
   remediation date, should land before any real employee bank account numbers are written
   anywhere in a production environment. E-10's own read-path logging does not substitute for
   this — logging *who read* sensitive data does not protect the data itself at rest.
2. **The Statutory/Banking data-scope inconsistency (§9/§18 item 3)** — whether to retrofit
   `EMPLOYEE.VIEW_STATUTORY` to `SELF`-scoping (the Banking plan's own suggested fast-follow) is a
   small, cheap, and now-overdue product decision, since Banking's own precedent proves the
   underlying mechanism was never the blocker.
