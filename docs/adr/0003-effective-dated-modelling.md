# ADR-0003: Effective-Dated (Temporal) Modelling for All Employee Attributes

**Status:** Accepted

## Context

Salary, designation, manager, department, shift and location all change over time. Payroll run in
June for the March pay period must use March's compensation and assignment values, not whatever is
current today. If these attributes are stored as plain mutable columns on `employee`, an edit made
today silently rewrites history — a promotion backdated or corrected in June would change what
March's payroll *would have* looked like, with no way to reconstruct what was actually true on any
given past date. This is both a correctness bug and, for payroll specifically, a compliance
problem (Doc 04 §5.1, Doc 03 principle 1).

## Decision

Any employee attribute that changes over time lives in its own child table with
`effective_from DATE NOT NULL` and `effective_to DATE` (`NULL` = current) — never as a mutable
column on `employee` itself. `EmployeeAssignment` (department, designation, grade, manager,
branch, shift) and `EmployeeCompensation` (CTC) are the Sprint-0 examples; `employee_statutory`
and `employee_bank` follow the same pattern (Doc 04 §5.5-5.6). Overlapping periods for the same
employee are made **structurally impossible**, not merely discouraged, via a Postgres exclusion
constraint:

```sql
EXCLUDE USING gist (
  employee_id WITH =,
  daterange(effective_from, COALESCE(effective_to, 'infinity'::date), '[]') WITH &&
)
```

A change is always an **insert of a new row**, never an edit of an existing one's core values.

## Consequences

- **Positive:** any historical query ("what was this employee's manager on 15 March?") is a
  straightforward date-range lookup, and payroll computation is naturally correct by construction
  — it reads the row effective on the pay period's dates.
- **Positive:** the exclusion constraint means a bug that tries to create two overlapping
  "current" assignments fails at the database, not silently in production.
- **Negative:** every read of "the current value" requires a query with `effective_to IS NULL` (or
  a date filter) instead of a plain column read — application code and reporting queries must be
  written with this in mind consistently.
- **Negative:** more tables and more rows than a naive mutable-column model; requires disciplined
  service-layer helpers so every module doesn't reinvent effective-dated CRUD slightly differently.

## Alternatives Considered

- **Mutable columns + a separate audit/history table.** Rejected: the audit trail becomes an
  afterthought bolted onto business logic instead of the actual system of record, and "what was
  true on date X" becomes a reconstruction exercise across two tables instead of a single query
  against the record that was true.
- **Application-level date-range validation only, no DB constraint.** Rejected: matches ADR-0002's
  reasoning — a structural guarantee outlives any individual developer remembering to check for
  overlaps in every code path that writes these tables.
