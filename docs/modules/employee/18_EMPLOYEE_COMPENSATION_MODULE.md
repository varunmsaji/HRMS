# Employee Compensation (E-06) — Module Reference

Companion to `17_EMPLOYEE_COMPENSATION_IMPLEMENTATION_PLAN.md` (the investigation/plan that
preceded this build) and `20_EMPLOYEE_COMPENSATION_IMPLEMENTATION_REPORT.md` (the closeout
report). This document describes what E-06 *is*, as shipped, for readers who need the shape of
the module without the investigation trail or the build log.

---

## 1. What Employee Compensation represents

Pay, effective-dated independently of Assignment — a raise without a transfer, or a transfer
without a raise, are both representable without coupling the two tables
(`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part C "Employee Compensation"). Compensation answers
one question, as of any date: *what was this employee's CTC on that date, and why did it
change.*

```
Employee (permanent identity)
 ├── Employment[]              1:N — time-bounded spells at one legal entity
 ├── Employee Assignment[]     1:N — effective-dated org placement (E-04)
 └── Employee Compensation[]   1:N — effective-dated pay, keyed on employee_id (NOT employment_id)
       ├── annual_ctc_minor    BIGINT, minor units (ADR-0006), required
       ├── currency            CHAR(3), default INR
       ├── revision_type       JOINING / ANNUAL / PROMOTION / CORRECTION / MARKET
       ├── revision_reason     free text, required
       ├── effective_from / effective_to
       └── version             optimistic concurrency
```

**Keyed on `employee_id`, not `employment_id`.** Same load-bearing architectural fact as
Assignment (`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part B4/C, reconfirmed live: the table's
only FK is `employee_compensation_employee_id_fkey`) — this is what makes a rehire correct
without any special-case code.

The table itself pre-dates this slice — it has existed since the very first migration
(`scripts/sql/001_init_schema.sql:279-293`), fully RLS-forced and GiST-constrained, with zero
application code anywhere. E-06 is the application-layer build (model, repository, service,
schema, router, permissions, audit) plus one small additive migration
(`revision_type`/`revision_reason`) — not a new table.

## 2. Effective-dating

Identical pattern to `Employment`/`EmployeeAssignment`:

- **Write**: close the current row (`effective_to = new.effective_from - 1 day`, the only
  allowed edit) and insert a new row, in the same transaction.
- **Read current**: `WHERE employee_id = :id AND effective_to IS NULL`.
- **Read as-of**: `WHERE employee_id = :id AND effective_from <= :date AND (effective_to IS NULL
  OR effective_to >= :date)`.
- **Full history**: `WHERE employee_id = :id ORDER BY effective_from`.

A GiST exclusion constraint (`employee_compensation_no_overlap`, live since the very first
migration) makes two overlapping "current" rows for one employee structurally impossible — this
is enforced at the database, not just in application code.

## 3. Write model — one operation, no carry-forward

There is exactly one write path, `POST /v1/employees/{employee_id}/compensation`. An employee's
first CTC and every later revision are the *same* operation — an insert of a new row —
distinguished only by `revision_type`. There is no `PATCH`/`DELETE` on an individual
compensation row — history is never edited in place.

**Deliberate departure from Assignment's carry-forward pattern**: `AssignmentCreate` lets an
omitted field carry forward unchanged from the current row. `CompensationCreate` does not —
`annual_ctc_minor`, `currency`, `revision_type`, and `revision_reason` are always required, on
every write, including the very first row. A stale CTC silently carried forward by omission is
a materially worse failure mode (payroll-correctness/compliance risk) than a stale org-placement
field, so this slice requires the caller to state the full new value explicitly every time —
including `revision_type=JOINING` on the first row, since that value is always knowable in
advance (unlike Assignment's `branch_id`/etc., which have no sensible default on first
placement).

## 4. Dependency on Employment

A compensation row cannot be effective on a date the employee has no covering employment
episode — `create_compensation` checks `EmploymentRepository.get_employment_as_of(employee_id,
effective_from)` before doing anything else, mirroring `EmployeeAssignmentService`'s identical
rule exactly. This is a service-layer rule, not a DB constraint (there is no `employment_id`
column on `employee_compensation` to express it as a FK/CHECK).

## 5. Rehire behavior

A rehire's first compensation row is mechanically identical to any employee's first compensation
row — no special-case code exists. See `20_EMPLOYEE_COMPENSATION_IMPLEMENTATION_REPORT.md` for
the one real limitation this produces (the pre-exit compensation row is not auto-closed when its
employment terminates — the same limitation E-04 already has for `employee_assignment`).

## 6. Grade CTC band — explicitly not enforced (PD-1)

`Grade.min_ctc`/`max_ctc` are informational bands only. No document anywhere states that
`employee_compensation.annual_ctc_minor` must fall within the employee's current grade's
`[min_ctc, max_ctc]` range, and no such enforcement is built in this slice (plan §8/§16, PD-1).
A CTC far outside a defined grade band succeeds — this is a deliberate, documented decision, not
a gap that was missed. If product later wants this enforced, it is a pure service-layer addition
with no schema change, since both tables and both columns already exist.

## 7. What this module does not do

- No `salary_structure_id`, `monthly_gross`, `approved_by`, `approval_request_id`,
  `is_arrears_processed`, or component-breakdown child table — all depend on modules (Payroll's
  salary-structure catalogue, the approval-routing engine) that do not exist yet.
- No Grade CTC-band enforcement (§6 above).
- No combined promotion+compensation-revision transaction — `create_assignment` (E-04) and
  `create_compensation` (E-06) remain two independent service calls with no cross-service
  coupling, even though FR-EMP-012 names an "optional compensation revision" as part of a
  promotion workflow. A future UI workflow (E-09) sequences both calls; this slice does not
  build that orchestration.
- No `sensitive_access_log` read-path logging — already-locked timing is E-10, not E-06, despite
  CTC being `RESTRICTED`-classified.
- No frontend — E-09, per unbroken precedent from E-01 through E-05.

## 8. Cross-module contract this module provides

`EmployeeCompensationService.get_compensation_as_of(company_id, employee_id, as_of) ->
CompensationRead | None` is the method Payroll will import once it exists (`employee.service` is
the only surface any future module may import from — never `.repository`/`.models`, per the
Module Standard). It does not assert employee existence: a nonexistent `employee_id` simply
yields no covering row.
