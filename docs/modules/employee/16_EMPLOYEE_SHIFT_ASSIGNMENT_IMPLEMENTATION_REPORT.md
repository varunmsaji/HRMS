# Employee Shift Assignment (E-05) — Implementation Report

Closeout report for the Employee Shift Assignment vertical slice, built per
`13_EMPLOYEE_SHIFT_ASSIGNMENT_IMPLEMENTATION_PLAN.md` (the investigation/plan that preceded this
task — verdict: no blocking product decision). Builds directly on E-04 (Employee Assignment,
COMPLETE, 439 tests passing before this task started).

---

## 1. E-05 status

**COMPLETE.** `employee_assignment.shift_id`, the `SHIFT_CHANGE` change type, shift
ownership/tenant validation, tests, and documentation are all implemented. The migration is
applied and verified against the dev database; 5 new unit tests + 10 new integration tests pass;
the full backend suite (439 tests) passes; `ruff check`, `ruff format --check`, `mypy src/hrms`,
and `lint-imports` all pass clean.

Compensation (E-06), Statutory (E-07), Banking (E-08), the Employee frontend (E-09), RBAC/
data-scope hardening (E-10), and the BR-14 shift/notice-period override chain are **not** part of
this task and were not built — confirmed by the scope inspection in §15/§16 below.

## 2. Files created

```
apps/api/alembic/versions/20260814110000_employee_shift_assignment.py
docs/modules/employee/14_EMPLOYEE_SHIFT_ASSIGNMENT_MODULE.md
docs/modules/employee/15_EMPLOYEE_SHIFT_ASSIGNMENT_API.md
docs/modules/employee/16_EMPLOYEE_SHIFT_ASSIGNMENT_IMPLEMENTATION_REPORT.md  (this document)
```

(`docs/modules/employee/13_EMPLOYEE_SHIFT_ASSIGNMENT_IMPLEMENTATION_PLAN.md` was created by the
prior investigation task, not this one.)

## 3. Files modified

```
apps/api/src/hrms/modules/employee/models.py        (+ EmployeeAssignment.shift_id)
apps/api/src/hrms/modules/employee/exceptions.py     (+ InvalidShiftReferenceError, ShiftIdRequiredError)
apps/api/src/hrms/modules/employee/schemas.py        (+ SHIFT_CHANGE, AssignmentCreate/Read.shift_id)
apps/api/src/hrms/modules/employee/service.py        (+ _assert_shift_ownership, carry-forward, required-on-SHIFT_CHANGE)
apps/api/src/hrms/modules/employee/permissions.py    (docstring update only — no new code)
apps/api/tests/unit/modules/employee/test_employee_assignment_service.py    (+ 9 tests)
apps/api/tests/integration/modules/employee/test_employee_assignment.py     (+ 12 tests)
```

No file inside `modules/organisation/`, `modules/identity/`, `router.py`, `repository.py`,
`dependencies.py`, or `apps/web/` was modified. `router.py` required no change (§8) —
`repository.py` required no change, since `insert_assignment` already takes a generic
`dict[str, Any]` and every read method already selects the whole ORM row rather than enumerating
columns (the same generic-by-construction property E-04's plan flagged in advance, §6.3 of
`13_..._PLAN.md`). `permissions.py` was touched for a docstring clarification only — no new
permission constant was added.

## 4. Database changes

One migration, `20260814110000_employee_shift_assignment.py`, applied and verified against the
dev database (`employee_assignment` had zero rows at write time):

- One new column: `shift_id UUID`, nullable.
- One new FK constraint, `employee_assignment_shift_id_fkey`, `ON DELETE SET NULL`, matching
  every other optional reference FK on this table.
- No new index — no source calls for one; consistent with E-04's own precedent of not adding
  speculative indexes.
- RLS, the `employee_assignment_no_overlap` GiST exclusion constraint, and `version`-based
  optimistic concurrency were untouched — already live and correct, not exercised by this
  migration.

Verified live against the dev database (`\d employee_assignment`) after `alembic upgrade head`:

```
shift_id | uuid | | |
...
Foreign-key constraints:
    "employee_assignment_shift_id_fkey" FOREIGN KEY (shift_id) REFERENCES shift(id) ON DELETE SET NULL
Policies (forced row security enabled):
    POLICY "tenant_isolation" USING ((company_id = (current_setting('app.company_id'::text, true))::uuid))
```

Every other column, FK, index, and the GiST exclusion constraint remained exactly as before this
migration. `shift` (the Shift Rules master table) was not touched.

## 5. ORM model

`EmployeeAssignment.shift_id: Mapped[UUID | None]` added to
`apps/api/src/hrms/modules/employee/models.py`, `ForeignKey("shift.id")`, nullable — same shape
as `grade_id`/`branch_id`/etc. The class docstring's stale "`shift_id` is deliberately absent —
ships in E-05" sentence was updated to describe the now-present field.

## 6. Repository

**No change.** `EmployeeAssignmentRepository.insert_assignment` already takes a generic
`data: dict[str, Any]` and does `EmployeeAssignment(**data)`; every read method (`get_current_
assignment`, `get_assignment_as_of`, `list_assignments`, `get_assignment`) already selects the
full ORM row. Adding `"shift_id"` to the service's own `data` dict was sufficient.

## 7. Service / business rules

`EmployeeAssignmentService.create_assignment`, extended:

1. **New early check**: if `change_type == "SHIFT_CHANGE"` and `shift_id is None`, raise
   `ShiftIdRequiredError` (`422 SHIFT_ID_REQUIRED`) — before the current-row lookup even runs.
   This is the one deliberate deviation from E-04's general "everything carries forward, nothing
   is conditionally required by `change_type`" rule, per this task's explicit instruction: a
   shift change naming no shift is meaningless.
2. **Carry-forward**: `shift_id = body.shift_id if body.shift_id is not None else
   current.shift_id` on the "current row exists" branch, and `shift_id = body.shift_id` (may be
   `None`) on the "no current row" branch — identical shape to every sibling field.
3. **New validation call**: `if shift_id is not None: await self._assert_shift_ownership(company_id,
   shift_id)`, alongside the five existing reference checks. `_assert_shift_ownership` mirrors
   `_assert_grade_ownership` exactly — lazily imports `OrganisationService`, calls `get_shift`,
   translates `NotFoundError` into `InvalidShiftReferenceError` (`422 INVALID_SHIFT`). Same-tenant
   enforcement happens here, at the service layer, not via a DB-level cross-table check —
   matching E-04's own documented precedent (`13_..._PLAN.md §7.3`).
4. **`shift_id` added to the `insert_assignment` data dict.**

No change to `list_assignments`/`get_assignment`/`get_assignment_as_of` — they already return
whatever `assignment_to_read` produces, which includes `shift_id` once added to the schema.

## 8. API endpoint

**No new endpoint.** `POST /v1/employees/{employee_id}/assignments` gained one optional field
(`shift_id`, conditionally required for `SHIFT_CHANGE`) and one `change_type` value
(`SHIFT_CHANGE`). The router's permission-selection line —

```python
required_permission = EMPLOYEE_PROMOTE if body.change_type == "PROMOTION" else EMPLOYEE_TRANSFER
```

— required **zero modification**: `SHIFT_CHANGE` falls into the existing `else` branch
automatically, since it was already written as a binary `if/else` rather than an exhaustive
match. Verified by `test_shift_change_with_transfer_permission_succeeds` and
`test_shift_change_without_transfer_permission_rejected`.

Full request/response/error-code reference: `15_EMPLOYEE_SHIFT_ASSIGNMENT_API.md`.

## 9. Permissions

**`EMPLOYEE.TRANSFER`** gates `SHIFT_CHANGE` — the locked decision for this task. No new
permission code was created; no change to `EMPLOYEE_PERMISSIONS`, the bootstrap seed, or
registration-time permission grants was required, since the code already existed (added by E-04)
and was already granted to `COMPANY_ADMIN`.

This resolves the one genuine documentation conflict the investigation plan flagged
(`13_..._PLAN.md §12`): `02_EMPLOYEE_DATA_MODEL.md §2` section E names `EMPLOYEE.UPDATE` for
shift's "Edit" cell, while `00_EMPLOYEE_AUDIT.md §16`'s own E-05 slice row says "(folds into
`.TRANSFER`)". `EMPLOYEE.TRANSFER` was chosen per this task's locked instructions — it is the
more specific, more recent source, it is what the already-shipped router does automatically with
zero code change, and it keeps the router's permission-selection mechanism binary rather than
requiring a three-way dispatch for a permission no code path on this endpoint currently checks.
If a reviewer prefers `EMPLOYEE.UPDATE` instead, the router's `if/else` line needs to become a
three-way branch — a larger, deliberately-not-made change, flagged here rather than decided
unilaterally.

## 10. Business rules implemented

1. `shift_id` is nullable at every point in an employee's assignment history except one: it is
   **required** when the request's `change_type = "SHIFT_CHANGE"`.
2. `shift_id` must reference an existing, non-deleted `Shift` belonging to the same `company_id`
   as the assignment — enforced at the service layer, not the database.
3. `shift_id` is **not** required to reference an *active* shift — existence + tenant-scope only,
   matching every sibling reference field's validation depth. Verified by
   `test_shift_change_deactivated_shift_succeeds`.
4. A shift change alone is expressed as `change_type="SHIFT_CHANGE"` with `shift_id` set; every
   other field carries forward from the current row, unchanged.
5. `shift_id` can also change silently as a side effect of any other `change_type` if the caller
   includes it in that request — unchanged E-04 behavior, not restricted by this slice.
6. A deactivated `Shift` does not retroactively affect any assignment row that already references
   it — no cascading effect exists or was added.
7. `Shift` deactivation is **not** blocked by an active assignment reference — no such check was
   added; explicitly out of scope (§16 item 3).

**Not implemented, by explicit instruction**: shift-must-be-active, shift-must-be-currently-
effective, shift-must-match-branch/department, notice-period restrictions, BR-14 cascading
defaults, and automatic assignment closure on termination. None of these are referenced anywhere
in the diff.

## 11. Audit behaviour

**No new audit action.** `ASSIGNMENT_CHANGED` continues to fire on every assignment write,
`entity_type = "employee_assignment"`, unchanged. `before`/`after` snapshots are
`AssignmentRead.model_dump(mode="json")` — already generic, so `shift_id` appeared in both the
instant it was added to `AssignmentRead`, with **zero code change** to `assignment_to_audit_dict`
or the audit call site in `create_assignment`. Verified by `test_shift_change_success`, which
asserts `before_json["shift_id"] is None` and `after_json["shift_id"] == shift["id"]` for a
`SHIFT_CHANGE` write against a real Postgres row.

## 12. Tenant / RLS isolation

No RLS change was needed on `employee_assignment` (already live, `FORCE ROW LEVEL SECURITY`,
untouched) or on `shift` (same, owned by the organisation module, not touched at all).
`_assert_shift_ownership` performs the same-tenant check via `OrganisationService.get_shift`,
which already scopes by `company_id` and returns `NotFoundError` (never a distinguishable
"exists elsewhere" signal) for a cross-tenant `shift_id`. Verified by
`test_shift_change_cross_tenant_shift_rejected`: a same-company employee cannot be assigned a
different tenant's shift — `422 INVALID_SHIFT`, not a leak.

## 13. Tests

**5 new unit tests** (`tests/unit/modules/employee/test_employee_assignment_service.py`):
`SHIFT_CHANGE` success (persisted `shift_id`, response field, audit `after` snapshot), missing-
`shift_id`-on-`SHIFT_CHANGE` rejection (and that it short-circuits before the current-row lookup),
invalid-shift rejection, first-assignment `shift_id`-optional, and `TRANSFER`-carries-forward-
`shift_id`-when-omitted.

**10 new integration tests** (`tests/integration/modules/employee/test_employee_assignment.py`,
against the real Postgres dev database): shift-change success with audit-row verification
(before/after `shift_id`), missing-`shift_id` rejection, invalid-shift rejection, cross-tenant-
shift rejection, deactivated-shift-succeeds (explicitly asserting the documented precedent, not
leaving it untested), mass-assignment protection still holding with `shift_id` present,
without-`.TRANSFER`-permission rejection, with-`.TRANSFER`-permission success, a rehire scenario
that documents the stale-`shift_id`-carry-forward behavior explicitly, and a check that no
`default_shift_id` column exists on Branch/Department/Designation/Grade (BR-14 non-introduction).

Every new integration test tears down its own rows in a `finally` block; `_teardown` was
extended with `_cleanup_shifts` (`DELETE FROM shift WHERE company_id = :cid`), run after
assignment/employment/employee/org-structure cleanup, mirroring `test_shift.py`'s own cleanup
helper. Verified against the dev database after the full suite run: `employee_assignment`,
`shift`, `employee`, and `employment` row counts are all `0`; only the two pre-existing seed
companies (`Demo Company A`/`B`) and their two users remain (fixed UUIDs, pre-dating this task).

## 14. Validation results

```
pytest                     — 439 passed (424 pre-existing + 15 new: 5 unit + 10 integration)
ruff check .                — All checks passed!
ruff format --check .       — All files already formatted
mypy src/hrms                — Success: no issues found in 73 source files
lint-imports                  — Contracts: 1 kept, 0 broken
```

All four checks were run against the **whole backend**, not just this slice's own files. No
pre-existing test needed modification — unlike E-04 (which added new permission codes requiring
a test-assertion update), E-05 reuses `EMPLOYEE.TRANSFER` verbatim, so
`test_registration_flow.py`'s permission-set assertion needed no change.

No frontend command was run and no `apps/web/` file was touched — there is no Employee UI to
verify manually (confirmed absent in §16 below).

## 15. Known limitations

1. **Rehire carry-forward of a stale `shift_id`** — a rehire's first assignment, if it omits
   `shift_id`, silently carries forward the pre-exit row's `shift_id`, which may be years out of
   date. No document states the desired behavior; not special-cased, since doing so would make
   `shift_id` inconsistent with every other carried-forward field on the same rehire path.
   Explicitly documented by `test_rehire_carries_forward_stale_shift_id`, not silently glossed
   over.
2. **Inactive-shift assignment is permitted** — by design, following existing precedent
   (`_assert_shift_ownership` does not gate on `is_active`), matching Branch/Department/
   Designation/Grade's identical existing behavior. Explicitly tested, not just assumed.
3. **No deactivation-blocking on `Shift`** — `Shift` can be deactivated while actively referenced
   by a current assignment row; no check was added (mirrors the same accepted, deferred gap on
   Branch/Department/Designation/Grade).
4. **Assignment rows are not auto-closed on employment termination** — unchanged, pre-existing
   E-04 limitation; E-05 neither fixes nor worsens it, since `shift_id` is just one more field on
   the same row that limitation already applies to.
5. **`employee_assignment_shift_id_fkey`'s `ON DELETE SET NULL` is untested in practice** —
   nothing in this codebase hard-deletes a `Shift` row (only soft-deactivates), so this FK clause
   has no natural trigger to exercise; carried forward as a known, inert-by-construction
   characteristic, same as every sibling FK on this table.

## 16. Explicitly excluded scope

Confirmed by inspecting `git diff` before writing this report — only these files were
created/modified by this task:

```
apps/api/alembic/versions/20260814110000_employee_shift_assignment.py   (new)
apps/api/src/hrms/modules/employee/models.py
apps/api/src/hrms/modules/employee/exceptions.py
apps/api/src/hrms/modules/employee/schemas.py
apps/api/src/hrms/modules/employee/service.py
apps/api/src/hrms/modules/employee/permissions.py   (docstring only)
apps/api/tests/unit/modules/employee/test_employee_assignment_service.py
apps/api/tests/integration/modules/employee/test_employee_assignment.py
docs/modules/employee/14_EMPLOYEE_SHIFT_ASSIGNMENT_MODULE.md            (new)
docs/modules/employee/15_EMPLOYEE_SHIFT_ASSIGNMENT_API.md               (new)
docs/modules/employee/16_EMPLOYEE_SHIFT_ASSIGNMENT_IMPLEMENTATION_REPORT.md  (new, this document)
```

- **No BR-14** — no `default_shift_id` column on Branch/Department/Designation/Grade; no
  cascading-default resolution logic anywhere in the diff.
- **No Employment lifecycle change** — `EmploymentService`/`terminate_employment` untouched.
- **No Employee frontend / `apps/web/` change** — confirmed via `git status`; the only
  `apps/web/` changes present in the working tree predate this task (Shift Rules master-data UI
  and unrelated `.next` build artifacts) and were not touched by this task.
- **No Compensation, Statutory, Banking** — no `employee_compensation`/`employee_statutory`/
  `employee_bank` code exists or was added.
- **No Attendance, Leave, Payroll, Employee Exit, ATS, Recruitment, Performance, or Workflow
  automation** — none of these modules exist anywhere in `apps/api/src/hrms/modules/` (only
  `employee`, `health`, `identity`, `organisation` exist); nothing to accidentally touch.
- **No `organisation`/`identity`/`router.py`/`repository.py`/`dependencies.py` change** —
  `Shift` is consumed exclusively via `OrganisationService.get_shift`, its existing public
  method; no field, validation rule, or endpoint on `Shift` was modified.
- **No new dependency added** — `pyproject.toml`/lockfiles untouched.
- **No unrelated pre-existing issue fixed** — the diff is confined to the field/enum/validation
  additions this slice requires.

## 17. Unresolved decisions

None block completion. One decision was explicitly locked by this task's own instructions rather
than left open: `EMPLOYEE.TRANSFER` (not `EMPLOYEE.UPDATE`) gates `SHIFT_CHANGE` — documented in
§9 for a future reviewer who wants to revisit it.

## 18. Recommended next step

**E-06 — Compensation.** Per `01_EMPLOYEE_MODULE_PLAN.md`, Compensation is the next vertical
slice in sequence. `EmployeeAssignmentService.get_assignment_as_of` (E-04, extended by this task
to include `shift_id`) remains the cross-module contract future modules — Attendance in
particular, for shift-based grace/late/OT computation — will call once they exist; no further
change to that contract was needed here. The BR-14 override chain remains a separate, later,
cross-module product decision, not scheduled by this report.

This task implements **only E-05** — no E-06 code was started or scoped in.
