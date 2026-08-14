"""Permission codes owned by the employee module.

`docs/product/19_RBAC_and_Permission_Matrix.md §3.1` documents a 14-code `EMPLOYEE.*`
catalogue (locked decision #10, `docs/modules/employee/05_EMPLOYEE_ARCHITECTURE_DECISIONS.md`
Part B9). E-01 (identity foundation) added the four codes its own CRUD surface needed.
`EMPLOYEE.VIEW` already exists (`identity/permissions.py`, seeded and granted to the
`EMPLOYEE_VIEWER` system role before E-01) and is reused as-is, not redefined here.

E-03 (employment lifecycle) reuses `EMPLOYEE.CREATE` (creating an employment episode — first
hire or rehire — is gated the same as creating the employee identity itself; a standalone
employee with no employment is not a realistic state, `01_EMPLOYEE_MODULE_PLAN.md` §2's own
E-01 note) and `EMPLOYEE.UPDATE`/`EMPLOYEE.VIEW` for the employment sub-resource's own
update/read paths. It adds exactly one new code, `EMPLOYEE.TERMINATE`: no source document names
a permission for ending an employment (the documented 14-code catalogue has no
`.TERMINATE`/`.EXIT` entry at all — `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` A9 flags this
pattern of genuinely-undefined-but-needed codes and resolves it by adding a new one, e.g.
`.VIEW_STATUTORY`/`.VIEW_BANKING`; this follows the same resolution). Termination is
irreversible and at least as HR-sensitive as `EMPLOYEE.DEACTIVATE` (which already got its own
dedicated code in E-01 rather than folding into `.UPDATE`) — the same reasoning applies here.
This is this task's own naming decision, not sourced from any document; flagged explicitly in
the E-03 implementation report as an assumption, not asserted as settled. Rehire is
deliberately *not* given its own code — it is mechanically the same action as a first hire
(insert a new employment row) and is gated by the same `EMPLOYEE.CREATE`, distinguished only in
the audit trail (`EMPLOYMENT_REHIRED` vs `EMPLOYMENT_STARTED`).

E-04 (Employee Assignment) adds `EMPLOYEE.TRANSFER` and `EMPLOYEE.PROMOTE` — both already named
in the locked 14-code catalogue (`docs/product/19_RBAC_and_Permission_Matrix.md` §3.1,
`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part B9), not invented here. Which one gates a given
`POST .../assignments` call is selected by the request's `change_type`
(`09_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_PLAN.md` §14.2): `change_type=PROMOTION` requires
`.PROMOTE`; every other value (`INITIAL`/`TRANSFER`/`MANAGER_CHANGE`/`SHIFT_CHANGE`) requires
`.TRANSFER` — `SHIFT_CHANGE` (E-05) falls into this same `else` branch automatically, requiring no
router change (`docs/modules/employee/13_EMPLOYEE_SHIFT_ASSIGNMENT_IMPLEMENTATION_PLAN.md` §12).
`.VIEW`/`.VIEW_ALL` (already seeded) gate the read endpoints, same as `Employment`'s own reads.

The remaining codes not yet added (`UPDATE_SENSITIVE`, `VIEW_COMPENSATION`, `.VIEW_DOCUMENTS`,
`.CONFIRM`, etc.) belong to later slices (E-02/E-06/...) — this task's own scope explicitly
excludes Compensation/Statutory/Banking and the confirmation/probation workflow, so their
permission codes are not added here either.
"""

EMPLOYEE_VIEW_ALL = "EMPLOYEE.VIEW_ALL"
EMPLOYEE_CREATE = "EMPLOYEE.CREATE"
EMPLOYEE_UPDATE = "EMPLOYEE.UPDATE"
EMPLOYEE_DEACTIVATE = "EMPLOYEE.DEACTIVATE"
EMPLOYEE_TERMINATE = "EMPLOYEE.TERMINATE"
EMPLOYEE_TRANSFER = "EMPLOYEE.TRANSFER"
EMPLOYEE_PROMOTE = "EMPLOYEE.PROMOTE"

EMPLOYEE_PERMISSIONS = [
    (EMPLOYEE_VIEW_ALL, "EMPLOYEE", "View all employees in the company"),
    (EMPLOYEE_CREATE, "EMPLOYEE", "Create employee"),
    (EMPLOYEE_UPDATE, "EMPLOYEE", "Edit employee basic details"),
    (EMPLOYEE_DEACTIVATE, "EMPLOYEE", "Deactivate an employee record"),
    (EMPLOYEE_TERMINATE, "EMPLOYEE", "Terminate an employee's active employment"),
    (EMPLOYEE_TRANSFER, "EMPLOYEE", "Transfer an employee's branch, department, or manager"),
    (EMPLOYEE_PROMOTE, "EMPLOYEE", "Promote an employee's designation or grade"),
]
