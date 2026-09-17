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

E-06 (Employee Compensation) adds `EMPLOYEE.VIEW_COMPENSATION` and `EMPLOYEE.UPDATE_COMPENSATION`
— both already named in the locked 14-code catalogue
(`docs/product/19_RBAC_and_Permission_Matrix.md §3.1`, lines 45-46), not invented here. No naming
decision was required, unlike `.TERMINATE` above: this is the simplest permission addition of
any slice so far (`docs/modules/employee/17_EMPLOYEE_COMPENSATION_IMPLEMENTATION_PLAN.md` §12).
`.VIEW_COMPENSATION` gates both compensation read routes; `.UPDATE_COMPENSATION` gates the
compensation write route. The entire sub-resource is absent for a caller without
`.VIEW_COMPENSATION` — CTC is `RESTRICTED`-classified (`docs/product/
19_RBAC_and_Permission_Matrix.md §6`) — not an individually masked field.

E-07 (Employee Statutory) adds `EMPLOYEE.VIEW_STATUTORY` (**new** — not in the locked 14-code
catalogue, in code, or in the database; `docs/modules/employee/
29_EMPLOYEE_STATUTORY_IMPLEMENTATION_PLAN.md` §11.2/§14, carried forward from `05_
EMPLOYEE_ARCHITECTURE_DECISIONS.md` A9's own "safe to finalize immediately" framing) and
`EMPLOYEE.UPDATE_SENSITIVE` (named in the locked catalogue's write-only description, but present
in the live database only as an orphaned, unseeded row with zero role grants — adding it here as
a proper code constant lets `seed_b1_foundation`'s existing idempotent `INSERT ... WHERE NOT
EXISTS`-shaped check adopt that row cleanly, not create a duplicate, per plan §4/§24 item 5/§27
item 11). `.VIEW_STATUTORY` gates both statutory read routes; `.UPDATE_SENSITIVE` gates the
statutory write route only — **not** wired to `employee`'s PAN/Aadhaar/UAN fields (E-02) or
`employee_bank` (E-08), which do not exist yet (plan §14). Both codes discard their resolved
`DataScope` and remain `COMPANY`-scoped, matching Compensation's own routes exactly — a
deliberate, named posture (plan §11.3), not an oversight: no source document proposes `SELF`/
`REPORTEES`/`REPORTEE_TREE` visibility for PF/PAN-adjacent identifier data, and this codebase
already treats manager-linked data exposure as something to actively guard
(`27_REPORTING_MANAGER_SECURITY_AUDIT.md`), not default open.

E-08 (Employee Banking) adds `EMPLOYEE.VIEW_BANKING` (**new** — not in the locked 14-code
catalogue, in code, or in the database before this slice; `docs/modules/employee/
33_EMPLOYEE_BANKING_IMPLEMENTATION_PLAN.md` §8/§15 PD-1, carried forward from `05_
EMPLOYEE_ARCHITECTURE_DECISIONS.md` A9's same "safe to finalize immediately" framing E-07 used
for `.VIEW_STATUTORY`) and reuses `EMPLOYEE.UPDATE_SENSITIVE` (already added by E-07) on the
Banking write route — the same code, widened to a second consumer, exactly as that code's own
E-07 docstring anticipated ("Edit PAN/Aadhaar/bank/statutory" always named both together).

Unlike `.VIEW_STATUTORY`/`.UPDATE_SENSITIVE`, `.VIEW_BANKING` does **not** discard its resolved
`DataScope` — `RBAC_DATA_SCOPE_DECISIONS.md` Decision E is **LOCKED** and explicitly names
"Own statutory / banking (once built, E-07/E-08)... `SELF`-scoped by default so an employee can
verify their own PF number / bank account" as the intended default. Statutory shipped
`COMPANY`-only as a deliberate, named deviation from this same locked decision (plan §11.3);
Banking follows the locked decision directly instead of repeating that deviation a second time,
per the Banking plan's own PD-1 recommendation (§15 Option 2) — `GET .../banking` routes resolve
the caller's `DataScope` via `EmployeeService.resolve_visible_employee_ids` exactly like
`GET /employees`/`GET /employees/{id}` already do, so a caller holding `.VIEW_BANKING` with only
`SELF` scope sees just their own bank record. Managers hold no default grant
(`RBAC_DATA_SCOPE_DECISIONS.md` Decision F: "No, by default" for Statutory/Banking) — this is
unaffected by wiring `SELF`, since `REPORTEES`/`REPORTEE_TREE` is never *granted* to any
manager-shaped role for this code, not merely narrowed at read time.

Employee Confirmation adds `EMPLOYEE.CONFIRM` — this is the exact code named above as
deliberately-not-added by that earlier slice; added now that the confirmation action itself
exists (`POST /employees/{id}/confirm`, `PROBATION` -> `ACTIVE`). Deliberately minimal: no
reminders, no manager-recommendation routing, no auto-extend/auto-confirm rules, no letter
generation — see this feature's own plan/decision notes for the full FR-EMP-010 scope this does
*not* cover. `.VIEW_DOCUMENTS` remains unaddressed, still belonging to a later slice.

Bulk Employee Import adds `EMPLOYEE.BULK_IMPORT` (**new**) — gates the CSV upload/status/error
endpoints in `modules/employee_import/`. Not folded into `EMPLOYEE_CREATE`: bulk-creating up to a
thousand employees in one upload is a materially larger blast radius than a single interactive
create, which is this codebase's existing bar for a dedicated code (see `.TERMINATE` above).
Defined here rather than in `employee_import/permissions.py` so it's picked up automatically by
`OrganisationService.register_company`'s existing `EMPLOYEE_PERMISSIONS` grant loop and by
`seed/bootstrap.py` — both already iterate this list, so a new module-specific permissions file
and a second registration wire-up would duplicate that plumbing for one code.

Account Provisioning (`docs/modules/employee/41_...AUDIT_AND_PLAN.md`, Phase 2) adds
`EMPLOYEE.INVITE` (**new**) — gates `POST /employees/{id}/invite`, in
`modules/account_invite/`. Defined here for the same reason `.BULK_IMPORT` is: automatic pickup
by `register_company`'s grant loop (`COMPANY_ADMIN` and `HR_ADMIN` both get it; `EMPLOYEE` does
not — an ordinary employee cannot invite anyone, per Decision H).
"""

EMPLOYEE_VIEW_ALL = "EMPLOYEE.VIEW_ALL"
EMPLOYEE_CREATE = "EMPLOYEE.CREATE"
EMPLOYEE_UPDATE = "EMPLOYEE.UPDATE"
EMPLOYEE_DEACTIVATE = "EMPLOYEE.DEACTIVATE"
EMPLOYEE_TERMINATE = "EMPLOYEE.TERMINATE"
EMPLOYEE_TRANSFER = "EMPLOYEE.TRANSFER"
EMPLOYEE_PROMOTE = "EMPLOYEE.PROMOTE"
EMPLOYEE_VIEW_COMPENSATION = "EMPLOYEE.VIEW_COMPENSATION"
EMPLOYEE_UPDATE_COMPENSATION = "EMPLOYEE.UPDATE_COMPENSATION"
EMPLOYEE_VIEW_STATUTORY = "EMPLOYEE.VIEW_STATUTORY"
EMPLOYEE_UPDATE_SENSITIVE = "EMPLOYEE.UPDATE_SENSITIVE"
EMPLOYEE_VIEW_BANKING = "EMPLOYEE.VIEW_BANKING"
EMPLOYEE_BULK_IMPORT = "EMPLOYEE.BULK_IMPORT"
EMPLOYEE_CONFIRM = "EMPLOYEE.CONFIRM"
EMPLOYEE_INVITE = "EMPLOYEE.INVITE"

EMPLOYEE_PERMISSIONS = [
    (EMPLOYEE_VIEW_ALL, "EMPLOYEE", "View all employees in the company"),
    (EMPLOYEE_CREATE, "EMPLOYEE", "Create employee"),
    (EMPLOYEE_UPDATE, "EMPLOYEE", "Edit employee basic details"),
    (EMPLOYEE_DEACTIVATE, "EMPLOYEE", "Deactivate an employee record"),
    (EMPLOYEE_TERMINATE, "EMPLOYEE", "Terminate an employee's active employment"),
    (EMPLOYEE_TRANSFER, "EMPLOYEE", "Transfer an employee's branch, department, or manager"),
    (EMPLOYEE_PROMOTE, "EMPLOYEE", "Promote an employee's designation or grade"),
    (EMPLOYEE_VIEW_COMPENSATION, "EMPLOYEE", "View an employee's compensation history"),
    (EMPLOYEE_UPDATE_COMPENSATION, "EMPLOYEE", "Record a new compensation revision"),
    (EMPLOYEE_VIEW_STATUTORY, "EMPLOYEE", "View an employee's PF/ESI/PT/LWF/tax-regime profile"),
    (EMPLOYEE_UPDATE_SENSITIVE, "EMPLOYEE", "Edit PAN/Aadhaar/bank/statutory"),
    (EMPLOYEE_VIEW_BANKING, "EMPLOYEE", "View an employee's bank account details"),
    (EMPLOYEE_BULK_IMPORT, "EMPLOYEE", "Bulk-import employees from a CSV file"),
    (EMPLOYEE_CONFIRM, "EMPLOYEE", "Confirm an employee from probation to active"),
    (EMPLOYEE_INVITE, "EMPLOYEE", "Invite an employee to create their login account"),
]
