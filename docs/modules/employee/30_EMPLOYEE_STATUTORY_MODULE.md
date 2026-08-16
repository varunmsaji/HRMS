# Employee Statutory (E-07) — Module Reference

Companion to `29_EMPLOYEE_STATUTORY_IMPLEMENTATION_PLAN.md` (the investigation/plan that
preceded this build) and `32_EMPLOYEE_STATUTORY_IMPLEMENTATION_REPORT.md` (the closeout report).
This document describes what E-07 *is*, as shipped, for readers who need the shape of the module
without the investigation trail or the build log.

---

## 1. What Employee Statutory represents

The employee's own PF/ESI/PT/LWF applicability flags and identifiers, plus tax-regime election —
effective-dated independently of Assignment/Compensation. Statutory answers one question, as of
any date: *what was this employee's PF/ESI/PT/LWF/tax-regime profile on that date, and why did it
change.* It is the Employee-owned input layer future Payroll will snapshot from — it does not
compute anything itself.

```
Employee (permanent identity)
 ├── Employment[]              1:N — time-bounded spells at one legal entity
 ├── Employee Assignment[]     1:N — effective-dated org placement (E-04)
 ├── Employee Compensation[]   1:N — effective-dated pay (E-06)
 └── Employee Statutory[]      1:N — effective-dated PF/ESI/PT/LWF/tax-regime, keyed on
       ├── is_pf_applicable          employee_id (NOT employment_id)
       ├── pf_number
       ├── pf_wage_ceiling_opt_out
       ├── vpf_amount / vpf_percentage
       ├── is_esi_applicable
       ├── esi_ip_number
       ├── pt_state_code
       ├── is_lwf_applicable
       ├── tax_regime                 OLD / NEW
       ├── is_director
       ├── is_international_worker
       ├── revision_reason             free text, required
       ├── effective_from / effective_to
       └── version                    optimistic concurrency
```

**Keyed on `employee_id`, not `employment_id`.** Same load-bearing architectural fact as
Assignment/Compensation (`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part C, plan §7/§8) — this is
what makes a rehire correct without any special-case code.

**Genuinely new table.** Unlike Compensation (which existed structurally since the very first
migration), `employee_statutory` did not exist anywhere in the live schema or in any prior
migration before this slice (plan §4) — this is a foundational `CREATE TABLE`, not an additive
`ALTER TABLE`.

## 2. Effective-dating

Identical pattern to `Employment`/`EmployeeAssignment`/`EmployeeCompensation`:

- **Write**: close the current row (`effective_to = new.effective_from - 1 day`, the only
  allowed edit) and insert a new row, in the same transaction.
- **Read current**: `WHERE employee_id = :id AND effective_to IS NULL`.
- **Read as-of**: `WHERE employee_id = :id AND effective_from <= :date AND (effective_to IS NULL
  OR effective_to >= :date)`.
- **Full history**: `WHERE employee_id = :id ORDER BY effective_from`.

A GiST exclusion constraint (`employee_statutory_no_overlap`) makes two overlapping "current"
rows for one employee structurally impossible — enforced at the database, not just in
application code.

## 3. Write model — one operation, no carry-forward

There is exactly one write path, `POST /v1/employees/{employee_id}/statutory`. An employee's
first statutory profile and every later revision are the *same* operation — an insert of a new
row. There is no `PATCH`/`DELETE` on an individual statutory row — history is never edited in
place. No field carries forward from the current row on a revision, mirroring Compensation's own
"no carry-forward" posture, not Assignment's — every field is stated explicitly on every write,
and `revision_reason` is required (plan §16/§27 item 7).

## 4. Dependency on Employment

A statutory row cannot be effective on a date the employee has no covering employment episode —
`create_statutory` checks `EmploymentRepository.get_employment_as_of(employee_id,
effective_from)` before doing anything else, mirroring `EmployeeCompensationService`'s identical
rule exactly. This is a service-layer rule, not a DB constraint (there is no `employment_id`
column on `employee_statutory` to express it as a FK/CHECK).

## 5. Tax-regime once-per-FY switch rule (FR-PAY-006)

A revision that changes `tax_regime` relative to the current row is rejected
(`409 TAX_REGIME_SWITCH_NOT_ALLOWED`) when the current row's `effective_from` falls in the same
fiscal year as the new row's `effective_from`. Fiscal year is April-March, identified by its
starting calendar year — **this task's own engineering assumption** (plan §26 item 5); no source
document defines the FY boundary. A revision that leaves `tax_regime` unchanged is never subject
to this rule, regardless of how close together the two `effective_from` dates are.

## 6. Rehire and termination behavior

`EmploymentService.terminate_employment` closes the currently-open statutory row (if any) at
`effective_to = last_working_day`, the same "last row closed" contract Assignment/Compensation
already have (plan §9) — this is a change to `EmploymentService`, not `EmployeeStatutoryService`,
made because the plan explicitly states this behavior ("Statutory rows survive exit... last row
closed") and because leaving it unclosed would silently diverge from the precedent every other
effective-dated Employee sub-resource already follows.

A rehire's first statutory row is mechanically identical to any employee's first statutory row —
no special-case code exists. PF/ESI applicability flags are re-evaluated fresh at rejoin, with no
carry-forward from the pre-exit row (plan §9). `pf_number` carry-forward on rehire is a genuinely
undecided product question (plan §9/§26 item 4) — this slice does not invent an answer; the
rejoining caller simply states the full new row, same as any other write.

## 7. Deliberately NOT enforced (open product questions, plan §17/§26)

- **PF/ESI applicability vs. identifier correlation**: `is_pf_applicable=true` does not require
  `pf_number IS NOT NULL` (same for `is_esi_applicable`/`esi_ip_number`). No document requires
  this correlation; inventing it would be a business rule this slice does not have authority to
  add.
- **Legal-entity-registration correlation**: whether `is_pf_applicable`/`is_esi_applicable`
  should be validated against the employing legal entity's own `pf_code`/`esi_code` registration
  is an open, undocumented question — not enforced.
- **Masking format**: no field-level masking format is documented for any statutory field.
  Whole-sub-resource gating (present entirely, or absent/403) is used instead, matching
  Compensation's own shipped precedent.

## 8. Data-scope posture — `COMPANY`-only, a deliberate, named gap

`EMPLOYEE.VIEW_STATUTORY` discards its resolved `DataScope` and remains `COMPANY`-scoped, exactly
like Compensation's own routes — **not** an oversight (plan §11.3). No source document proposes
`SELF`/`REPORTEES`/`REPORTEE_TREE` visibility for this RESTRICTED, PF/PAN-adjacent sub-resource,
and this codebase already treats manager-linked data exposure as something to actively guard
(`27_REPORTING_MANAGER_SECURITY_AUDIT.md`'s self-elevation guard), not default open. This is the
same class of gap Compensation already carries and that `25_EMPLOYEE_RBAC_DATA_SCOPE_
IMPLEMENTATION_PLAN.md` §22 names as an accepted, tracked follow-up — not silently inherited here.
Verified by `test_view_statutory_ignores_non_company_data_scope`.

## 9. What this module does not do

- No UAN, PAN, Aadhaar, or bank fields — `uan_number` stays on `employee.uan_number`, never
  duplicated here (plan §5). PAN/Aadhaar/bank remain E-02/E-08's own concern.
- No tax/payroll calculation engine, PF/ESI/PT rate tables, or `payrun_*` construct — Payroll's
  own concern, consumed read-only via `get_statutory_as_of` at pay-run snapshot time (plan §13).
- No approval-workflow fields.
- No PF/ESI/legal-entity correlation enforcement (§7 above).
- No field-level masking (§7 above).
- No `sensitive_access_log` read-path logging — already-locked timing is E-10, not E-07.
- No frontend — E-09, per unbroken precedent from E-01 through E-06.
- No new RBAC scope levels — `DEPARTMENT`/`BRANCH`/`LEGAL_ENTITY`/`ALL_COMPANIES` remain absent.

## 10. Cross-module contract this module provides

`EmployeeStatutoryService.get_statutory_as_of(company_id, employee_id, as_of) -> StatutoryRead |
None` is the method Payroll will call once it exists, once per pay run at snapshot time
(`docs/adr/0005-payroll-snapshot-immutability.md`'s documented pipeline — snapshot inputs, then
compute as a pure function of the snapshot). `employee.service` is the only surface any future
module may import from — never `.repository`/`.models`, per the Module Standard. It does not
assert employee existence: a nonexistent `employee_id` simply yields no covering row.
