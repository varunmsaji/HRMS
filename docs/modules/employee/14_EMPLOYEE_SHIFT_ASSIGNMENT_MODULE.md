# Employee Shift Assignment (E-05) — Module Reference

Companion to `13_EMPLOYEE_SHIFT_ASSIGNMENT_IMPLEMENTATION_PLAN.md` (the investigation/plan that
preceded this build) and `16_EMPLOYEE_SHIFT_ASSIGNMENT_IMPLEMENTATION_REPORT.md` (the closeout
report). Describes what E-05 *is*, as shipped — a small, additive extension of E-04
(`10_EMPLOYEE_ASSIGNMENT_MODULE.md`), not a new module.

---

## 1. What E-05 adds

One nullable column, one FK, and one `change_type` enum value on top of the E-04 assignment row
already documented in `10_EMPLOYEE_ASSIGNMENT_MODULE.md`:

```
Employee Assignment (E-04, extended)
 ├── branch_id / department_id / designation_id / grade_id / managers / cost_centre_id / ...
 └── shift_id               -> Shift              optional, effective-dated, carries forward
```

`shift_id` follows the exact same shape and rules every other optional reference field on
`employee_assignment` already follows — nullable, FK to the owning module's table, validated at
the service layer, carried forward unchanged when omitted from a subsequent write.

## 2. `SHIFT_CHANGE` — a fifth `change_type`

`AssignmentChangeType` is now `INITIAL | TRANSFER | PROMOTION | MANAGER_CHANGE | SHIFT_CHANGE`.
`SHIFT_CHANGE` is a pure shift change: `shift_id` set, every other field carried forward from
the current row — the same "one write path, distinguished only by `change_type`" model E-04
established (`10_EMPLOYEE_ASSIGNMENT_MODULE.md §3`).

**Deviation from the general carry-forward rule, by explicit instruction for this task**:
`shift_id` is **required** when `change_type = "SHIFT_CHANGE"` — a shift change with no shift
named is meaningless. This is narrower than every other field on this endpoint (none of which are
required conditionally on their own matching `change_type`), and is enforced before the "no
current row" / "current row exists" branch even runs, so it also rejects a first-ever assignment
submitted as `SHIFT_CHANGE` with no `shift_id`. Outside of `SHIFT_CHANGE`, `shift_id` remains
fully optional — an employee can have no shift from day one, and `shift_id` can also be set
silently as a side effect of any other `change_type` (e.g. a `TRANSFER` request that happens to
include `shift_id`), exactly as every other field already behaves (plan §8 item 5).

## 3. Shift ownership validation

`_assert_shift_ownership(company_id, shift_id)` mirrors `_assert_grade_ownership` exactly:
lazily imports `OrganisationService` (the only surface this module may import from —
`.repository`/`.models` never crossed, Module Standard §2), calls `get_shift(company_id,
shift_id)`, translates `NotFoundError` into `InvalidShiftReferenceError` (`422 INVALID_SHIFT`).

`get_shift` checks existence + tenant scope only — **not** `is_active`. `_assert_shift_ownership`
reuses it verbatim, so a **deactivated** shift can still be newly assigned. This is not a gap
specific to shift: `_assert_branch_ownership`/`_assert_department_ownership`/etc. have the same
property (E-04's own precedent, plan §7.4) — deviating for shift alone would make it
inconsistent with every sibling reference field for no documented reason.

## 4. Permission — `EMPLOYEE.TRANSFER`, not `EMPLOYEE.UPDATE`

`SHIFT_CHANGE` is gated by `EMPLOYEE.TRANSFER`. This is a locked decision for this task, not a
new permission code:

```python
required_permission = EMPLOYEE_PROMOTE if body.change_type == "PROMOTION" else EMPLOYEE_TRANSFER
```

`SHIFT_CHANGE` falls into the existing `else` branch automatically — **no router change was
required**. `02_EMPLOYEE_DATA_MODEL.md §2` section E names `EMPLOYEE.UPDATE` for shift's "Edit"
cell; that document predates E-04's dynamic `change_type`-selects-permission mechanism and is a
general field-attribute table, not a per-slice implementation decision. `00_EMPLOYEE_AUDIT.md
§16`'s own E-05 row — "(folds into `.TRANSFER`)" — is the more specific, more recent source, and
matches what the shipped router already does with zero code change. See
`13_..._PLAN.md §12` for the full reasoning; treated here as settled, not reopened.

## 5. Audit — reused, not extended

No new audit action. `ASSIGNMENT_CHANGED` continues to fire on every assignment write;
`before`/`after` snapshots are `AssignmentRead.model_dump(mode="json")` — already generic, so
`shift_id` appears in both automatically once added to `AssignmentRead`, with zero change to
`assignment_to_audit_dict` or the audit call site.

## 6. BR-14 — still deferred

The Company → Branch → Department → Grade → Employee cascading shift/notice-period default
override chain (BR-14 / FR-EMP-018) is **not** built. No `default_shift_id` column exists on
`branch`, `department`, `designation`, or `grade`. An employee with no `shift_id` set on their
current assignment simply has no shift — no default is ever synthesized. This remains a
separate, later, cross-module product decision.

## 7. Employment / termination — unchanged

E-05 does not touch `EmploymentService` or `EmploymentService.terminate_employment` in any way.
The known E-04 limitation — an employee's assignment row is not auto-closed when the covering
employment terminates (`12_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_REPORT.md §12/§17 item 1`) —
applies identically to whatever `shift_id` that row carries; E-05 neither fixes nor worsens it.

## 8. Frontend — still out of scope

No Employee UI exists in this codebase (`apps/app/app/` has no employee/assignment routes — only
the Shift *master* CRUD pages under `apps/web/src/app/app/shifts/`, unrelated to assignment).
E-05 adds no frontend code. A shift picker on an employee-assignment form is E-09's scope, not
started.

## 9. Cross-module contract — unchanged, now includes shift

`EmployeeAssignmentService.get_assignment_as_of(company_id, employee_id, as_of) ->
AssignmentRead | None` (E-04's existing cross-module contract for Attendance/Leave/Payroll) now
returns a `shift_id` in its result with no change to the method itself — the field flows through
automatically once present on `AssignmentRead`.
