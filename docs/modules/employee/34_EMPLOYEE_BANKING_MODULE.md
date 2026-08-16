# Employee Banking (E-08) — Module Reference

Companion to `33_EMPLOYEE_BANKING_IMPLEMENTATION_PLAN.md` (the investigation/plan that preceded
this build) and `36_EMPLOYEE_BANKING_IMPLEMENTATION_REPORT.md` (the closeout report). This
document describes what E-08 *is*, as shipped, for readers who need the shape of the module
without the investigation trail or the build log.

---

## 1. What Employee Banking represents

The employee's own payout-account facts — effective-dated independently of Assignment/
Compensation/Statutory. Banking answers one question, as of any date: *which bank account should
this employee's salary be paid to on that date.* It is the Employee-owned input layer future
Payroll will read at bank-advice-generation time — it does not generate a bank advice file, verify
an account, or move money itself.

```
Employee (permanent identity)
 ├── Employment[]              1:N — time-bounded spells at one legal entity
 ├── Employee Assignment[]     1:N — effective-dated org placement (E-04)
 ├── Employee Compensation[]   1:N — effective-dated pay (E-06)
 ├── Employee Statutory[]      1:N — effective-dated PF/ESI/PT/LWF/tax-regime (E-07)
 └── Employee Bank[]           1:N — effective-dated payout account, keyed on
       ├── account_holder_name       employee_id (NOT employment_id)
       ├── account_number_enc        plain TEXT today — see §5
       ├── bank_name
       ├── ifsc
       ├── branch_name
       ├── payment_mode               BANK / CASH / CHEQUE / UPI
       ├── is_primary                 system-managed, always true (§3)
       ├── verification_status        system-managed, always PENDING (§3)
       ├── penny_drop_reference       system-managed, always null (§3)
       ├── effective_from / effective_to
       └── version                    optimistic concurrency
```

**Keyed on `employee_id`, not `employment_id`.** Same load-bearing architectural fact as
Assignment/Compensation/Statutory (`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part C, plan §6) — no
FK to `employment` or `legal_entity` exists.

**Genuinely new table.** `employee_bank` did not exist anywhere in the live schema or in any prior
migration before this slice (plan §2) — a foundational `CREATE TABLE`, not an additive `ALTER
TABLE`.

## 2. Effective-dating

Identical pattern to `Employment`/`EmployeeAssignment`/`EmployeeCompensation`/
`EmployeeStatutory`:

- **Write**: close the current row (`effective_to = new.effective_from - 1 day`, the only allowed
  edit) and insert a new row, in the same transaction.
- **Read current**: `WHERE employee_id = :id AND effective_to IS NULL`.
- **Read as-of**: `WHERE employee_id = :id AND effective_from <= :date AND (effective_to IS NULL
  OR effective_to >= :date)`.
- **Full history**: `WHERE employee_id = :id ORDER BY effective_from`.

A GiST exclusion constraint (`employee_bank_no_overlap`) makes two overlapping "current" rows for
one employee structurally impossible — enforced at the database, not just in application code.
This also concretely resolves `is_primary`'s otherwise-ambiguous documented meaning: with exactly
one current row per employee, there is never more than one account to be "primary" among — the
column is kept for schema parity with the documented target shape, system-set `true` on every
insert, and not client-writable.

## 3. Write model — one operation, three system-managed fields

There is exactly one write path, `POST /v1/employees/{employee_id}/bank`. An employee's first
bank account and every later revision are the *same* operation — an insert of a new row. There is
no `PATCH`/`DELETE` on an individual bank row — history is never edited in place. Unlike
Statutory, no field carries forward from the current row on a revision, and no `revision_reason`
field exists at all — no source document requires one for Banking (plan §5/§13).

`is_primary`, `verification_status`, and `penny_drop_reference` are never present in the request
body (`BankCreate` has no fields for them) — every insert sets `is_primary=true`,
`verification_status="PENDING"`, `penny_drop_reference=null` unconditionally. No code path in
this slice ever transitions `verification_status` away from `PENDING` — no penny-drop provider or
verification workflow exists anywhere in this codebase (plan §12).

## 4. Dependency on Employment

A bank row cannot be effective on a date the employee has no covering employment episode —
`create_bank` checks `EmploymentRepository.get_employment_as_of(employee_id, effective_from)`
before doing anything else, the identical rule Assignment/Compensation/Statutory already have
(plan §15 PD-2 Option 1, the smallest-diff choice). **Known limitation**: because
`get_employment_as_of` only resolves a date falling within an episode's
`[joining_date, last_working_day]` range, a bank correction dated *strictly after* an employee's
`last_working_day` — the literal full-and-final-settlement-correction-after-exit scenario §6's own
termination-survival rule anticipates needing — is still rejected with `409
NO_ACTIVE_EMPLOYMENT` under this slice's shipped behavior. A write dated on-or-before
`last_working_day` succeeds (it falls within the just-closed episode's range). This gap is named
explicitly, not silently accepted — plan §9/§15 PD-2 discusses two other options and recommends
against adopting either unilaterally, since no source document specifies the exact rule.

## 5. Encryption — `account_number_enc` is plaintext today, a named, non-blocking gap

`account_number_enc` is a plain, unencrypted `TEXT` column — the same posture
`employee.pan_number_enc`/`aadhaar_number_enc` already have. No encryption mechanism (KMS,
`TypeDecorator`, Fernet, or otherwise) exists anywhere in this codebase, confirmed by direct
search before this slice was built. `HRMS_SYSTEM_DESIGN_BASELINE.md` Decision D-2 names two
options — build real column-level encryption, or ship without it and document the gap as an
accepted, time-boxed risk — and this slice takes Option 2, matching this task's own explicit
scope exclusion (plan §23: building the encryption mechanism itself is not part of this plan).
**This is the one item in this module that gates real production data, not code**: this slice's
schema/service/tests are fully built and tested against synthetic values, but real account
numbers must not be written to `account_number_enc` in a production environment until either a
real encryption mechanism is built, or an explicit, documented compliance sign-off accepts the
gap with a stated remediation date.

## 6. Rehire and termination behavior — the load-bearing difference from every sibling

**Termination does *not* close the current bank row.** Unlike Assignment/Compensation/Statutory
(all three of which close their current row at `effective_to = last_working_day` inside
`terminate_employment`), Banking's current row remains open through and after exit — a locked
architecture decision (`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part C "Employee Bank") states the
row is still needed for full-and-final settlement payout *after* the employee has left. No change
was made to `EmploymentService.terminate_employment` for this slice.

**Consequence for rehire**: because the pre-exit row is never auto-closed, a rehire's first bank
write is **not** guaranteed to take the "no current row" branch the way Compensation's/
Statutory's rehire write does. If the pre-exit row is still current (`effective_to IS NULL`) when
the employee rejoins — which it always is, since nothing ever closes it during the gap — the
rehire's first bank write takes the close-then-insert branch instead, requiring `If-Match` against
the pre-exit row's own `version`. This is a materially different rehire mechanic than every other
effective-dated Employee sub-resource, verified by
`test_rehire_first_bank_write_requires_if_match`.

## 7. Data-scope posture — `SELF`-scoped, implementing the locked decision directly

Unlike Statutory's `COMPANY`-only posture, `EMPLOYEE.VIEW_BANKING`'s two `GET` routes resolve and
bind the caller's `DataScope` via `EmployeeService.resolve_visible_employee_ids` — the same
mechanism `GET /employees`/`GET /employees/{id}` already use. `RBAC_DATA_SCOPE_DECISIONS.md`
Decision E is **LOCKED** and explicitly names `SELF`-scoped self-service as Banking's intended
default ("an employee needs to verify their own... bank account is correct"); this slice
implements that decision directly rather than repeating Statutory's own deliberate deviation from
it a second time (plan §8/§15 PD-1 Option 2). Managers hold no default grant
(`RBAC_DATA_SCOPE_DECISIONS.md` Decision F: "No, by default" for Statutory/Banking) — unaffected
by this wiring, since `REPORTEES`/`REPORTEE_TREE` is never *granted* to any manager-shaped role
for this code, only resolvable if a future role explicitly grants it. The write route
(`create_bank`) is not data-scoped, matching every other write route in this module.

This creates a visible, deliberate inconsistency with Statutory (`COMPANY`-only) for two
structurally identical RESTRICTED sub-resources — named explicitly here, not papered over. The
Banking plan's own recommendation (§15 PD-1) additionally suggests retrofitting
`EMPLOYEE.VIEW_STATUTORY` to the same `SELF`-scoped behavior as a fast-follow; that retrofit is
**not** made by this slice.

## 8. Deliberately NOT enforced or built (open product questions, plan §12/§13/§15)

- **Verification workflow**: no code path transitions `verification_status` away from `PENDING`;
  no endpoint writes `penny_drop_reference`. No provider integration exists or is proposed.
- **IFSC format validation**: no regex/format check on `ifsc` beyond its 15-character column
  bound — the well-known `^[A-Z]{4}0[A-Z0-9]{6}$` format is public banking-domain knowledge, not
  sourced from any document in this repository, and this slice does not invent the rule.
- **Masking format**: the documented `******7890` partial-masking format is not implemented —
  whole-sub-resource gating (present entirely, or absent/`403`) is used instead, matching every
  other RESTRICTED sub-resource's shipped precedent in this codebase.
- **Duplicate-account-number detection across employees** (FR-PAY-015): explicitly Payroll's own
  pre-finalise concern, not this slice's.

## 9. What this module does not do

- No Payroll logic — no `bank_advice` file generation, no NEFT/RTGS/IMPS format, no funds-transfer
  code of any kind.
- No bank/payment-provider integrations — no penny-drop verification, no NEFT/RTGS/UPI gateway.
- No salary or F&F calculation.
- No real column-level encryption (§5 above) — the schema/code/tests are built, but the mechanism
  itself is out of this slice's scope.
- No field-level masking (§8 above).
- No `sensitive_access_log` read-path logging — already-locked timing is E-10, not E-08.
- No frontend — E-09, per unbroken precedent from E-01 through E-07.
- No new RBAC scope levels — `DEPARTMENT`/`BRANCH`/`LEGAL_ENTITY`/`ALL_COMPANIES` remain absent.
- No change to `EmploymentService.terminate_employment` — explicitly, deliberately not made (§6).

## 10. Cross-module contract this module provides

`EmployeeBankService.get_bank_as_of(company_id, employee_id, as_of) -> BankRead | None` is the
method Payroll will call once it exists, at bank-advice-generation time (an engineering inference
from `docs/adr/0005-payroll-snapshot-immutability.md`'s own documented snapshot-input list, which
does not name bank account — plan §11; not confirmed by any document, not asserted as settled).
`employee.service` is the only surface any future module may import from — never
`.repository`/`.models`, per the Module Standard. It does not assert employee existence: a
nonexistent `employee_id` simply yields no covering row.
