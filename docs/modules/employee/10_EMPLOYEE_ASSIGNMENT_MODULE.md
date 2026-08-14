# Employee Assignment (E-04) — Module Reference

Companion to `09_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_PLAN.md` (the investigation/plan that
preceded this build) and `12_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_REPORT.md` (the closeout
report). This document describes what E-04 *is*, as shipped, for readers who need the shape of
the module without the investigation trail or the build log.

---

## 1. What Employee Assignment represents

Per `docs/product/02_PRD.md §11`: "The current position: department, designation, grade,
reporting manager, location, shift. **Time-versioned.**" Assignment answers one question, as of
any date: *where in the org does this employee sit, under whom, and where do they work.*

```
Employee (permanent identity)
 ├── Employment[]            1:N — time-bounded spells at one legal entity
 └── Employee Assignment[]   1:N — effective-dated, keyed on employee_id (NOT employment_id)
       ├── branch_id             -> Branch            required at first placement
       ├── department_id         -> Department         required at first placement
       ├── designation_id        -> Designation         required at first placement
       ├── grade_id               -> Grade               optional
       ├── reporting_manager_id   -> Employee (self-ref) optional (nullable for CEO-level)
       ├── dotted_line_manager_id -> Employee (self-ref) optional
       ├── cost_centre_id         opaque UUID, no referenced table yet
       ├── work_location_type     OFFICE / WFH / HYBRID / FIELD
       └── shift_id               NOT present — ships in E-05
```

**Keyed on `employee_id`, not `employment_id`.** This is the load-bearing architectural fact,
locked before this slice started (`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part B3): assignment
history spans the whole identity, continuous across an employment gap, which is what makes
rehire correct without any special-case code.

## 2. Effective-dating

One shared pattern, matching `Employee`/`Employment`'s own tables:

- **Write**: close the current row (`effective_to = new.effective_from - 1 day`, the only
  allowed edit) and insert a new row, in the same transaction.
- **Read current**: `WHERE employee_id = :id AND effective_to IS NULL`.
- **Read as-of**: `WHERE employee_id = :id AND effective_from <= :date AND (effective_to IS NULL
  OR effective_to >= :date)`.
- **Full history**: `WHERE employee_id = :id ORDER BY effective_from`.

A GiST exclusion constraint (`employee_assignment_no_overlap`, live since the very first
migration) makes two overlapping "current" rows for one employee structurally impossible — this
is enforced at the database, not just in application code.

## 3. Write model — one operation, not several

There is exactly one write path, `POST /v1/employees/{employee_id}/assignments`. Initial
placement, transfer, promotion, and manager change are the *same* operation — an insert of a
new row — distinguished only by the request's `change_type`:

| `change_type` | Meaning | Permission required |
|---|---|---|
| `INITIAL` | First assignment (new employee, or after a rehire gap) | `EMPLOYEE.TRANSFER` |
| `TRANSFER` | Branch/department/manager change | `EMPLOYEE.TRANSFER` |
| `PROMOTION` | Designation and/or grade change | `EMPLOYEE.PROMOTE` |
| `MANAGER_CHANGE` | Reporting-line change only | `EMPLOYEE.TRANSFER` |

There is no `PATCH`/`DELETE` on an individual assignment row — history is never edited in place.

When a current row already exists, any field omitted from the request carries forward
unchanged from that row (`branch_id`, `department_id`, `designation_id`, `grade_id`,
`reporting_manager_id`, `dotted_line_manager_id`, `cost_centre_id`, `work_location_type`). When
no current row exists (the employee's very first assignment, or the first after a rehire gap),
`branch_id`/`department_id`/`designation_id` are mandatory.

## 4. Dependency on Employment

An assignment cannot be effective on a date the employee has no covering employment episode —
`create_assignment` checks `EmploymentRepository.get_employment_as_of(employee_id,
effective_from)` before doing anything else. This is a service-layer rule, not a DB constraint
(there is no `employment_id` column on `employee_assignment` to express it as a FK/CHECK).

## 5. Rehire behavior

A rehire's first assignment is mechanically identical to any employee's first assignment — no
special-case code exists. See `12_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_REPORT.md` §9 for the one
real limitation this produces (the pre-exit assignment row is not auto-closed when its
employment terminates).

## 6. Shift — explicitly out of this module

`shift_id` does not exist on `employee_assignment` after this slice. It ships in E-05, on its
own migration, so Shift's dependency stays explicit and reviewable on its own. The BR-14
shift/notice-period override chain remains an unbuilt, deferred cross-module decision.

## 7. Cross-module contract this module provides

`EmployeeAssignmentService.get_assignment_as_of(company_id, employee_id, as_of) ->
AssignmentRead | None` is the method Attendance/Leave/Payroll will import once they exist
(`employee.service` is the only surface any future module may import from — never
`.repository`/`.models`, per the Module Standard). It does not assert employee existence: a
nonexistent `employee_id` simply yields no covering row.
