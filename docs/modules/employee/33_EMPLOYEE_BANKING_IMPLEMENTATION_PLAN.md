# Employee Banking (E-08) — Implementation Plan

**This document is investigation and planning only — no application code, migrations, tests, or
frontend code were written or modified to produce it.** It follows the same discipline
`29_EMPLOYEE_STATUTORY_IMPLEMENTATION_PLAN.md` established: every claim is checked directly
against the live repository/database, not assumed from an older document, and every proposed
field/rule is labelled by its actual authority (SOURCE, ENGINEERING DECISION, or OPEN PRODUCT
DECISION).

**Written 2026-08-15**, immediately after E-07 Employee Statutory shipped (uncommitted in the
working tree; `docs/modules/employee/32_EMPLOYEE_STATUTORY_IMPLEMENTATION_REPORT.md`). E-08 is
the next slice in the locked sequence
(`docs/architecture/00_HRMS_SYSTEM_ARCHITECTURE.md:1421`, `00_SYSTEM_ARCHITECTURE_AUDIT.md:492`).

---

## 1. Executive Summary

E-08 adds `employee_bank` — the employee's payout-account record Payroll will read to generate
bank advice files. The table does not exist in the live schema or in any migration (reconfirmed
today by direct `psql` inspection, §2); it is a fully greenfield slice at the code level, same
starting condition E-07 was in. The data model, effective-dating mechanics, and Employee/Payroll
boundary are **already fully specified** by four independent, mutually-consistent authoritative
documents (§3) — this is a materially better-documented starting point than Statutory had, which
is why this plan can be more prescriptive on schema/API shape than `29_` needed to be.

**What is genuinely different about Banking, not a copy-paste of Statutory's plan:**

1. **Termination behavior is the opposite of Statutory/Assignment/Compensation.** A locked
   architecture decision (`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part C "Employee Bank",
   quoted in full at §7) states the current bank row must **remain open** through and after exit
   — it is needed for full-and-final settlement payout *after* the employee has left. This plan
   recommends **not** adding a bank-closing block to `EmploymentService.terminate_employment`,
   the opposite of what this task's own prior slice (E-07) just did for Statutory.
2. **A masking format is actually documented** for the account number (`******7890`, cited in
   three independent documents, §11) — Statutory had no masking format documented anywhere.
   Whether to build partial-value masking (new infrastructure, zero precedent anywhere in this
   codebase) or continue the established whole-sub-resource-gating pattern is a genuine, newly
   live product/engineering decision (§15 PD-3).
3. **A locked data-scope decision recommends `SELF` scope** for an employee's own banking read
   (`RBAC_DATA_SCOPE_DECISIONS.md` Decision E, "LOCKED", §8) — directly contradicting the
   `COMPANY`-only posture E-07 actually shipped for Statutory (itself a documented, deliberate
   deviation from this same locked decision). This is a real, unresolved tension between two
   authoritative sources this plan surfaces rather than silently resolves either way (§8, §15
   PD-1).
4. **Encryption is an explicitly named, unresolved precondition**, not a "no document requires
   it" situation like Statutory's fields. `account_number_enc`'s own naming, and the most recent
   architecture audit (`HRMS_SYSTEM_DESIGN_BASELINE.md` Decision D-2, §14), both treat real
   encryption as something that must be resolved — or consciously, explicitly deferred with a
   compliance rationale — before real account numbers are written. This is the plan's single
   most important flagged precondition (§15 PD-4, §22).

**Final readiness: READY TO IMPLEMENT the schema/code/tests exactly as this plan specifies, with
one condition that gates production data, not code**: a resolved encryption decision (§15 PD-4,
§22) — matching Statutory's own precedent of shipping with named, non-blocking flagged
assumptions, except this one item is not merely "flagged," it is the one item an authoritative,
recent audit explicitly says must be resolved-or-consciously-deferred before real data lands.

---

## 2. Current Database State

Directly verified against `postgresql://hrms:hrms_dev_password@localhost:5433/hrms_dev` today:

- **`employee_bank` does not exist** — absent from `\dt` (31 tables total; the full list is
  organisation/identity tables plus `employee`, `employment`, `employee_assignment`,
  `employee_compensation`, `employee_statutory`, `number_series`).
- **No column anywhere in the schema** matches `%bank%`, `%account%`, `%ifsc%`, `%payment%`, or
  `%cheque%` (`information_schema.columns` search, zero rows).
- **Migration head is `20260815130000`** (`employee_statutory`, this task's immediately-prior
  slice). Purely additive, touches no other table.
- **`permission` table** has exactly one banking-adjacent row: `EMPLOYEE.UPDATE_SENSITIVE`
  (`domain=EMPLOYEE`, `description="Edit PAN/Aadhaar/bank/statutory"`) — now a proper code
  constant as of E-07 (`EMPLOYEE_PERMISSIONS`), granted only to `COMPANY_ADMIN`. **No**
  `EMPLOYEE.VIEW_BANKING` row exists anywhere — not in the database, not in any code constant.
  (The `permission` table also carries orphaned `PAYROLL.*`/`ATTENDANCE.*`/`LEAVE.*` rows
  produced by no code constant anywhere — the same class of finding E-07 made for
  `UPDATE_SENSITIVE` before it was adopted, noted here only as context: it is not
  Banking-specific and this plan takes no position on those other domains.)
- **`employee.pan_number_enc`/`aadhaar_number_enc`/`uan_number`** — still live, still no write
  path (E-02 unbuilt). Unrelated to Banking directly, but the same "`_enc` suffix implies a
  guarantee the code does not provide" finding applies verbatim to the column this plan proposes
  (`account_number_enc`, §14).
- `employee`, `employment`, `employee_assignment`, `employee_compensation`, `employee_statutory`
  are otherwise unaffected by anything this investigation found — no source document proposes a
  Banking-driven change to any of them.

**Conclusion: `employee_bank` DOES NOT EXIST** at either the database or code level. Nothing here
is "planned but partially built" — this is the same greenfield starting condition Statutory was
in before E-07.

---

## 3. Authoritative Sources

Four independent documents describe `employee_bank`'s target shape, and — notably, unlike some of
Statutory's source material — **agree with each other on every field name and type**:

| Document | What it establishes |
|---|---|
| `docs/product/08_Database_Architecture.md` §5.6 | Field list: `employee_id, effective_from, effective_to, account_holder_name, account_number_enc, bank_name, ifsc, branch_name, payment_mode (BANK/CASH/CHEQUE/UPI), is_primary, verification_status, penny_drop_reference` |
| `docs/modules/employee/02_EMPLOYEE_DATA_MODEL.md` §2G, §3 | Same field list, plus the exact target DDL (`CREATE TABLE employee_bank ...`, GiST exclusion, RLS) — quoted in full at §6 below |
| `docs/modules/employee/05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part C "Employee Bank" | The locked purpose/relationship/effective-dating/exit/rehire decisions — quoted in full at §7 |
| `docs/architecture/HRMS_SYSTEM_DESIGN_BASELINE.md` §10 | Restates the same shape, adds the explicit encryption/permission/audit-logging preconditions (§14, §15 PD-4) |

Also read in full for this plan: `docs/product/17_SRS_Phase1_Core_Modules.md` (FR-EMP-009,
FR-PAY-015, FR-PAY-018, FR-AUD-003), `docs/product/19_RBAC_and_Permission_Matrix.md` (§3.1, §5,
§6), `docs/architecture/RBAC_DATA_SCOPE_DECISIONS.md` (Decisions E/F/G/H), `docs/adr/
0005-payroll-snapshot-immutability.md`, `docs/architecture/00_HRMS_SYSTEM_ARCHITECTURE.md`,
`00_SYSTEM_ARCHITECTURE_AUDIT.md`, `docs/modules/employee/04_EMPLOYEE_UX_PLAN.md`,
`docs/design/screens/01_Employee_List_Directory.md`, `docs/architecture/
HRMS_FRONTEND_CAPABILITY_AUDIT.md`, and the actual shipped code for E-04/E-06/E-07
(`apps/api/src/hrms/modules/employee/{models,repository,schemas,service,router,exceptions,
permissions,dependencies}.py`), re-read in full today, current as of E-07.

**No document disagrees with another on Banking's field list or DDL shape.** The genuine
tensions this plan surfaces (§1 items 1/3/4) are not inter-document disagreements about
*Banking* — they are tensions between a locked cross-cutting RBAC decision and what the
*previous* slice (Statutory) actually shipped, and between a stated compliance expectation
(encryption) and the fact that no encryption mechanism exists anywhere in the codebase yet.

---

## 4. The Banking Boundary

**Belongs to Employee (this slice):** the employee's own payout-account facts —
`account_holder_name`, `account_number_enc`, `bank_name`, `ifsc`, `branch_name`, `payment_mode`,
`is_primary`, `verification_status`, `penny_drop_reference`, effective-dated, keyed on
`employee_id`. Nothing else (`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part C: "this table is a
self-contained financial-instrument reference").

**Does NOT belong here — Payroll payment processing:** `bank_advice` file generation
(NEFT/RTGS/IMPS formats, FR-PAY-018), which banks/formats a tenant supports, encrypted-download
access logs for the advice file itself. Payroll's own planned table
(`HRMS_SYSTEM_DESIGN_BASELINE.md` §182: `bank_advice`) reads `employee_bank` as-of the pay
period; it does not live inside Employee.

**Does NOT belong here — payment execution:** no module in this codebase or its documentation
initiates an actual funds transfer. Every source document describes generating a *file*
(NEFT/RTGS/IMPS format, or a generic CSV) that the tenant's own banking relationship executes
outside this system (`00_HRMS_SYSTEM_ARCHITECTURE.md:973`: "Salaries move via customer-generated
bank advice files").

**Does NOT belong here — salary calculation:** net pay, gross-to-net breakup, and every
Payroll-owned computation are untouched by this slice, same boundary Statutory already
established.

**Does NOT belong here — bank/payment-provider integrations:** no penny-drop verification
provider, no NEFT/RTGS gateway, no UPI provider integration exists anywhere in this codebase or
its documentation. `verification_status`/`penny_drop_reference` are documented *columns*, not a
documented *integration* — §12/§20 treat the verification workflow as explicitly out of scope for
this slice, matching the "system-managed" language `02_EMPLOYEE_DATA_MODEL.md` §2G already uses
for these three columns.

Banking remains an Employee module. No document proposes otherwise.

---

## 5. Field-by-Field Analysis

| Field | Type | Authority | Notes |
|---|---|---|---|
| `id`, `company_id`, `employee_id` | UUID | SOURCE | Standard shape, every sibling table |
| `effective_from` / `effective_to` | DATE | SOURCE | Same effective-dating pattern as Assignment/Compensation/Statutory |
| `account_holder_name` | VARCHAR(150) | SOURCE | `02_EMPLOYEE_DATA_MODEL.md` §3 DDL |
| `account_number_enc` | TEXT | SOURCE (name/column), OPEN PRODUCT DECISION (whether it is *actually* encrypted, §14/§15 PD-4) | The one column in this table whose own name asserts a guarantee — see §14 |
| `bank_name` | VARCHAR(150) | SOURCE | |
| `ifsc` | VARCHAR(15) | SOURCE (column + length); ENGINEERING INFERENCE if a format regex is added (§13) | No document specifies the 11-character `AAAA0NNNNNN` format — that is public banking-domain knowledge, not sourced from this repo's own documents |
| `branch_name` | VARCHAR(150) | SOURCE | |
| `payment_mode` | VARCHAR(10), enum `BANK`/`CASH`/`CHEQUE`/`UPI` | SOURCE | Exact enum from `08_Database_Architecture.md` §5.6 |
| `is_primary` | BOOLEAN, default `true` | SOURCE (column exists), ENGINEERING DECISION (its actual semantics under a single-current-row model, §6 note) | System-managed, per `02_EMPLOYEE_DATA_MODEL.md` §2G's own "system-managed" classification — not client-settable in this slice |
| `verification_status` | VARCHAR(20), default `PENDING` | SOURCE (column), OPEN PRODUCT DECISION (any transition path — §12/§20, no verification provider exists) | System-managed; this slice provides no code path that changes it away from `PENDING` |
| `penny_drop_reference` | VARCHAR(60), nullable | SOURCE (column), OUT OF SCOPE (no provider integration exists, §4/§12) | Column exists for schema parity with the documented shape; never populated by this slice |
| `revision_reason` | — | ENGINEERING DECISION, **not adding it** | Unlike Statutory (where this plan's own precedent, `29_`, added it beyond the literal DDL because plan §16/§27 explicitly required it), **no source document requires a `revision_reason` for Banking**, and this plan does not invent one — see §13 |
| `version`, `created_at`, `updated_at`, `deleted_at` | — | SOURCE / ENGINEERING (module standard) | Standard audit/version columns, matching every sibling table |

**Fields explicitly NOT stored here** (confirmed absent from every source document): UAN, PAN,
Aadhaar (stay on `employee`, E-02's concern); `employment_id` (no FK — see §6); any Payroll rate,
calculation, or `bank_advice`-generation field; any actual NEFT/RTGS/UPI provider credential or
API token.

---

## 6. Data Model

**Target DDL**, taken verbatim from `02_EMPLOYEE_DATA_MODEL.md` §3 (re-verified against the live
`employee_statutory` shape this task's own prior slice just shipped, confirming the pattern is
current, not stale):

```sql
CREATE TABLE employee_bank (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id UUID NOT NULL REFERENCES company(id),
  employee_id UUID NOT NULL REFERENCES employee(id),
  effective_from DATE NOT NULL,
  effective_to DATE,
  account_holder_name VARCHAR(150),
  account_number_enc TEXT,
  bank_name VARCHAR(150),
  ifsc VARCHAR(15),
  branch_name VARCHAR(150),
  payment_mode VARCHAR(10),
  is_primary BOOLEAN NOT NULL DEFAULT true,
  verification_status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
  penny_drop_reference VARCHAR(60),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL,
  deleted_at TIMESTAMPTZ,
  version INTEGER NOT NULL DEFAULT 1
);

ALTER TABLE employee_bank
  ADD CONSTRAINT employee_bank_no_overlap
  EXCLUDE USING gist (
    employee_id WITH =,
    daterange(effective_from, COALESCE(effective_to, 'infinity'::date), '[]') WITH &&
  );

CREATE INDEX employee_bank_company_id_idx ON employee_bank (company_id);
CREATE INDEX employee_bank_employee_id_effective_from_idx
  ON employee_bank (employee_id, effective_from);

ALTER TABLE employee_bank ENABLE ROW LEVEL SECURITY;
ALTER TABLE employee_bank FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON employee_bank
  USING (company_id = current_setting('app.company_id', true)::uuid);
```

**Single current row, not multiple concurrent accounts.** The `employee_bank_no_overlap` GiST
exclusion constraint — identical shape to `employee_statutory_no_overlap`/
`employee_compensation_no_overlap` — makes two "current" (`effective_to IS NULL`) rows for the
same `employee_id` structurally impossible. This resolves §5's `is_primary` question concretely:
**this slice does not support multiple concurrent bank accounts** (e.g., a primary salary account
plus a separate reimbursement account held open at the same time) — there is exactly one current
row per employee, same shape as every other effective-dated Employee sub-resource.

**Named inconsistency in the source documents, not invented here**: `is_primary` is documented as
a column (§5, all four sources) despite the documented DDL making "primary among several" a
structurally meaningless question — with only one row ever current, that row is trivially always
"the" account, not "a" primary among alternatives. This plan's reading: `is_primary` is kept for
schema parity with the documented shape and as a forward-compatible seam if a future slice adds
genuine multi-account support (a change no document requests today), defaulted `true`,
system-set, and **not** exposed as a client-writable field in `BankCreate` — mirroring how
`02_EMPLOYEE_DATA_MODEL.md` §2G itself classifies it as "system-managed," not "yes" under the
"Edit" column. If a future product decision wants genuine multiple-concurrent-accounts support,
that is a materially different table shape (dropping the exclusion constraint's implicit
single-row invariant, or scoping it differently) — out of this plan's scope, and this plan
recommends against inventing it now given zero source document asks for it.

**No FK to `employment` or `legal_entity`.** Keyed on `employee_id` only, identical rehire-safety
reasoning as Assignment/Compensation/Statutory (§7).

---

## 7. Rehire and Termination Behavior — the load-bearing difference from every prior slice

Quoted in full, `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part C, "Employee Bank" (LOCKED):

> - **Relationship to Employee.** 1:N, effective-dated, keyed on `employee_id`.
> - **Effective-dated?** Yes (an employee can change their salary account over a career).
> - **Survives exit?** Last row remains — needed for full-and-final settlement payout even after
>   exit.
> - **Survives rehire?** Old rows remain; typically a new row is added at rehire (re-verification
>   is a reasonable default even if the account is unchanged, since a multi-year gap is long
>   enough that bank details plausibly changed).

**This is the opposite of Assignment/Compensation/Statutory**, all three of which close their
current row at `effective_to = last_working_day` inside `EmploymentService.terminate_employment`
(Assignment/Compensation: shipped in the termination-lifecycle fix; Statutory: added by this
task's own immediately-prior slice, `service.py:700-737`, per `29_EMPLOYEE_STATUTORY_
IMPLEMENTATION_PLAN.md` §9's "last row closed" requirement). Banking's own locked decision states
plainly that the row must **not** close at exit — F&F settlement is a payout that happens *after*
the employment record shows `TERMINATED`, and a closed bank row (no current row) would leave
nothing for that payout to reference via the same `get_bank_as_of`/current-row read path every
other consumer uses.

**Recommendation, stated as the plan's own engineering decision, directly informed by the locked
architecture decision above**: do **not** add a bank-closing block to
`EmploymentService.terminate_employment`. This is a real, deliberate divergence from the pattern
this task's own prior slice (E-07) just established for Statutory — named explicitly here so a
future reviewer does not assume "of course Banking closes at exit too, just like everything
else." No code change to `EmploymentService` is proposed by this plan at all.

**Consequence for the covering-employment write check (§9) — a genuine open question, not
resolved by the architecture-decisions doc**: Assignment/Compensation/Statutory all require
`EmploymentRepository.get_employment_as_of(employee_id, effective_from)` to return non-`None`
before permitting a write (`409 NO_ACTIVE_EMPLOYMENT` otherwise). If Banking's row must remain
correctable *after* exit (to fix a typo before an F&F payout goes out, per the exit-survival
rationale above), a literal reuse of that same check would block exactly the correction the
architecture decision's own rationale anticipates needing. No document resolves this — flagged
as **OPEN PRODUCT DECISION PD-2** (§15).

**Rehire**: "typically a new row is added" (not "always," and not "carries forward unchanged") —
same "no carry-forward, state the full new row" posture as Compensation/Statutory, not
Assignment's carry-forward pattern. Because the pre-exit row is never auto-closed, a rehire's
first bank write is **not** guaranteed to take the "no current row" branch the way Compensation's/
Statutory's rehire write does — if the pre-exit row was never subsequently closed by any write
during the gap, it is still "current" (`effective_to IS NULL`) when the employee rejoins, meaning
the rehire's first bank write **will** take the "current row exists, close-then-insert, `If-Match`
required" branch, referencing a row whose `version` the caller must know. This is a materially
different rehire mechanic than every other effective-dated sub-resource in this module and must
be tested explicitly (§18) and documented plainly in the module reference, not silently inherited
from the Compensation/Statutory template.

---

## 8. RBAC / Security — data scope is this plan's central open decision

**Sensitivity**: `RESTRICTED`, explicitly named (not inferred, unlike most of Statutory's fields)
— `docs/product/19_RBAC_and_Permission_Matrix.md` §6: "CTC, salary components, **bank account**,
PAN, Aadhaar...". `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part C additionally calls Banking "the
strictest permission gating in the aggregate per the brief's explicit instruction."

**Permission codes**:
- `EMPLOYEE.UPDATE_SENSITIVE` — already exists as a code constant (added by E-07), currently
  scoped only to the `employee_statutory` `POST` route (`permissions.py`'s own docstring already
  names `employee_bank` as the anticipated second consumer: *"not wired to... `employee_bank`
  (E-08), which do not exist yet"*). This plan recommends **widening its usage** (not its
  definition) to also gate the Banking `POST` route — the same code, reused across both write
  paths, matching the locked catalogue's own description ("Edit PAN/Aadhaar/**bank**/statutory")
  which always named both together.
- `EMPLOYEE.VIEW_BANKING` — **new** code, not in the locked 14-code catalogue, not in the
  database, not in any code constant. Recommended and named consistently across every
  architecture document that discusses it (`RBAC_DATA_SCOPE_DECISIONS.md`, `00_HRMS_SYSTEM_
  ARCHITECTURE.md`, `HRMS_SYSTEM_DESIGN_BASELINE.md`) — the literal name is not in dispute, only
  its scope behavior is (below).

**Data scope — the genuine, unresolved tension (OPEN PRODUCT DECISION PD-1, §15):**

`RBAC_DATA_SCOPE_DECISIONS.md` Decision E is marked **LOCKED** and states directly:

> Own statutory / banking (once built, E-07/E-08) | Yes, same pattern as compensation — own
> record, separate permission code (`EMPLOYEE.VIEW_STATUTORY`/`.VIEW_BANKING`), `SELF`-scoped by
> default so an employee can verify their own PF number / bank account. | An employee needs to
> verify their own statutory/bank data is correct; this is a standard self-service need, distinct
> from a manager or HR needing it.

Decision G additionally describes the *mechanism* as already generic and reusable: "same
resolver, same `employee_ids` set as any other permission for that role, just evaluated against a
different permission code's `role_permission` row" — i.e., the locked design intends
`EMPLOYEE.VIEW_STATUTORY`/`.VIEW_BANKING` to bind their resolved `DataScope` into
`EmployeeService.resolve_visible_employee_ids` exactly like `EMPLOYEE.VIEW`/`.VIEW_ALL` already
do, not to discard it.

**What E-07 actually shipped** (`32_EMPLOYEE_STATUTORY_IMPLEMENTATION_REPORT.md` §10): the
opposite — `EMPLOYEE.VIEW_STATUTORY` **discards** its resolved `DataScope` and remains
`COMPANY`-scoped unconditionally, matching Compensation's own (also non-compliant-with-Decision-E)
precedent. E-07's own plan (`29_` §11.3) discussed this exact tension and chose `COMPANY`-only,
reasoning that no route in this codebase implements employee self-service *routes* today. That
reasoning is weaker than it first appears: the *mechanism* Decision E asks for
(`resolve_visible_employee_ids`, `SELF`/`caller_employee_id` resolution) already exists, is
already tested, and is already live on exactly two routes (`GET /employees`,
`GET /employees/{id}`) — what's actually missing is not infrastructure, only that Compensation's
and Statutory's routes choose to discard the resolved scope rather than pass it through.

**This plan does not resolve this tension unilaterally** (per this task's own instruction: "Do
NOT invent a security model"). It presents both options at §15 PD-1 with a recommendation, and
flags explicitly that whichever way Banking goes, the resulting inconsistency with Statutory (one
`COMPANY`-only, one `SELF`-wired, for structurally identical permission shapes) is itself worth a
product decision, not an accident to paper over.

**Managers (`REPORTEES`/`REPORTEE_TREE`)**: Decision F is unambiguous and uncontroversial —
**"No, by default"** for Statutory/Banking. No document anywhere argues a line manager needs
their reports' bank details for day-to-day people management. This plan follows Decision F
without reservation: no default grant to any manager-shaped role, and no code path that would
make `REPORTEES`/`REPORTEE_TREE` produce a *wider* result than `COMPANY` for this permission (the
existing `resolve_visible_employee_ids` mechanism already fails this safely today — union
semantics, never wider than granted — so this is a "do not grant it," not a "build a guard,"
recommendation).

**`sensitive_access_log` (E-10) fit**: Decision G names the exact future seam — one row per
successful read, `field_or_subresource="BANKING"`, written from inside the service layer at the
same "absent, not disabled" gate the router already provides. **Not built in this task** — E-10
remains out of scope, matching Statutory's own explicitly-named gap (§17 item 3 of the Statutory
report). `HRMS_SYSTEM_DESIGN_BASELINE.md` H-5 flags this as a compounding risk with every new
RESTRICTED table that ships without it — noted, not fixed, here.

---

## 9. Employment Requirement — genuinely open, not a copy of Statutory's rule

Every prior effective-dated write (Assignment/Compensation/Statutory) requires
`EmploymentRepository.get_employment_as_of(employee_id, effective_from)` to resolve before
permitting the write. Whether Banking should carry the identical `409 NO_ACTIVE_EMPLOYMENT` rule
is **not** a mechanical copy-paste decision here, because of §7's exit-survival requirement:

- **If the covering-employment check applies unconditionally**: a bank-detail correction dated
  *after* an employee's `last_working_day` (exactly the F&F-settlement-correction scenario the
  architecture decision's own rationale anticipates) would be rejected with
  `409 NO_ACTIVE_EMPLOYMENT`, since no employment episode covers a post-exit date.
- **If the check is dropped entirely**: any employee record, including one that has never had an
  active employment episode at all, could receive a bank write — a materially different posture
  than every sibling sub-resource, and one no document explicitly requests either.

**Recommended engineering default, presented as a recommendation for product/engineering
sign-off, not asserted as settled**: keep the covering-employment check for the *general* case
(the common path — an active employee updating their salary account), but do not require the
`effective_from` to fall within a *currently active* (`status='ACTIVE'`) employment specifically —
reuse `get_employment_as_of` exactly as Statutory does, which already resolves against *any*
episode (past or present) covering the given date, `ACTIVE` or `TERMINATED`. Concretely: a bank
write dated on-or-before the employee's `last_working_day` succeeds (it falls within the
just-closed episode's `[joining_date, last_working_day]` range); a bank write dated *after*
`last_working_day` — the literal F&F-correction-after-exit scenario — still has no covering
episode and would still be rejected under a literal reuse of the existing method. This narrows,
but does not fully close, the tension: it resolves "can I backdate a correction to before my exit
date" (yes) but not "can I correct my account the week after I've left, before the F&F run pays
out" (no, under the literal existing check). Flagged as **OPEN PRODUCT DECISION PD-2** (§15) —
this plan does not invent a new "employment ever existed" check to fully resolve it, since no
document asks for one.

---

## 10. Effective Dating

Identical mechanics to Assignment/Compensation/Statutory — no generic framework, one more
instance of the same established pattern:

- **Write**: close the current row (`effective_to = new.effective_from - 1 day`) and insert a new
  row, in the same transaction — except, per §7, this close-then-insert only happens on the
  *next* write, never automatically at termination.
- **Read current**: `WHERE employee_id = :id AND effective_to IS NULL`.
- **Read as-of**: `WHERE employee_id = :id AND effective_from <= :date AND (effective_to IS NULL
  OR effective_to >= :date)` — the `get_bank_as_of(employee_id, date)` contract (§11).
- **Full history**: `WHERE employee_id = :id ORDER BY effective_from`.
- **Overlap prevention**: `employee_bank_no_overlap` GiST exclusion constraint (§6).
- **`If-Match`**: required only when a current row exists — identical contract to Compensation/
  Statutory. Per §7's rehire finding, this means a rehire's first bank write is **more likely**
  to require `If-Match` than Compensation's/Statutory's own rehire writes, since the pre-exit row
  is never auto-closed.

---

## 11. Payroll Contract

The clean Employee → Payroll boundary this slice must expose:
`EmployeeBankService.get_bank_as_of(company_id, employee_id, as_of) -> BankRead | None`, mirroring
`get_compensation_as_of`/`get_statutory_as_of` exactly (same signature shape, same
"does-not-assert-employee-existence" contract, `00_HRMS_SYSTEM_ARCHITECTURE.md:411`: *"
`get_statutory_as_of`/`get_bank_as_of` when E-07/E-08 ship; do not invent a different shape"*).

**When Payroll will call it — an inference, not confirmed by any document**: `docs/adr/
0005-payroll-snapshot-immutability.md`'s own documented snapshot-input list is explicit: "copy
compensation, attendance, leave, arrears, loans and statutory master versions into an immutable
`payrun_input_snapshot`" — **bank account is not named in that list.** This is a meaningful,
deliberate-looking omission: net-pay computation (ADR-0005 step 3, "a pure function of the
snapshot") does not need a payout account at all; only the *disbursement* step does. Combined
with `HRMS_SYSTEM_DESIGN_BASELINE.md` §10's own framing ("Payroll reads the employee's bank
account **as-of the pay period** ... to generate `bank_advice` output files"), this plan's
reading is that Payroll consumes `get_bank_as_of` at **bank-advice-file-generation time**
(FR-PAY-018, after finalisation), not at snapshot/computation time the way Compensation/Statutory
are consumed. No document confirms this explicitly — flagged as an engineering inference for
Payroll's own eventual implementation task to verify, not asserted as settled. It does not change
anything this slice builds: `get_bank_as_of`'s shape and contract are identical either way.

**FR-PAY-015's "duplicate bank accounts" check** (a pre-finalise Payroll validation: the same
account number used by two different employees) is explicitly **Payroll's** concern, not this
slice's — no document asks for a uniqueness constraint on `account_number_enc` at the Employee
layer, and adding one would be inventing a rule no source requests. Noted here only so a future
reviewer does not mistake its absence for an oversight.

No rate table, calculation, or `bank_advice`/`payrun_*` construct is added by this slice — same
boundary discipline as Statutory (`32_...REPORT.md` §18).

---

## 12. Verification Workflow — explicitly out of scope for this slice

`verification_status` (`PENDING` by default) and `penny_drop_reference` are documented columns
with no documented *provider* anywhere in this codebase — no penny-drop API integration, no
webhook receiver, no verification vendor is named in any source document. `02_EMPLOYEE_DATA_
MODEL.md` §2G classifies both as "system-managed" with a "system-managed / `EMPLOYEE.VERIFY_
DOCUMENTS`-adjacent" edit path — itself hedged ("-adjacent," not a confirmed permission).

**This plan's recommendation**: both columns exist in the schema (§6) for shape-parity with the
documented target and to avoid a future `ALTER TABLE`, but this slice provides **no** code path
that transitions `verification_status` away from `PENDING`, and **no** endpoint that writes
`penny_drop_reference`. Every row created by this slice's `POST` route is `verification_status
='PENDING'` unconditionally, system-set, not client-writable in `BankCreate`. Building a
verification workflow (manual "mark verified" action, or an actual penny-drop integration) is
future work with no current product requirement — explicitly named as excluded, not silently
dropped (§21).

---

## 13. Validation

| Rule | Authority |
|---|---|
| `effective_from` required, strictly after current row's `effective_from` on a revision | ENGINEERING (module standard, mirrors every sibling) |
| GiST-enforced non-overlap | SOURCE (§6 DDL) |
| `payment_mode` ∈ `BANK`/`CASH`/`CHEQUE`/`UPI` | SOURCE (`08_Database_Architecture.md` §5.6) — validated as a Pydantic `Literal`, matching `tax_regime`/`revision_type`'s own precedent, not a DB `CHECK` |
| `account_holder_name`/`bank_name`/`branch_name` free text, bounded by column length | SOURCE (length), ENGINEERING (no other format rule documented) |
| `ifsc` bounded to 15 chars | SOURCE (column length) |
| `ifsc` format regex (`^[A-Z]{4}0[A-Z0-9]{6}$`) | ENGINEERING INFERENCE, **not recommended for this slice** — well-known public banking-domain format, but not sourced from any document in this repository; adding it would be inventing a validation rule beyond what any source requests, the same restraint Statutory's plan applied to PF/ESI correlation rules |
| `account_number_enc` — no format/length rule at the plaintext level | Not documented anywhere (Indian account numbers vary 9-18 digits by bank) — no rule proposed |
| `is_primary` / `verification_status` / `penny_drop_reference` not client-writable | SOURCE (`02_EMPLOYEE_DATA_MODEL.md` §2G "system-managed") — enforced by simply omitting them from `BankCreate` |
| `revision_reason` | **Not added** — see §5; no document requires it for Banking, unlike Statutory where plan §16/§27 explicitly did |
| `extra="forbid"` mass-assignment protection | ENGINEERING (module standard, every Create schema in this module) |
| Multiple concurrent accounts | Structurally prevented by the GiST exclusion constraint (§6) — not a validation rule to write, a schema-level fact |
| Applicability/identifier correlation (none exists for Banking — no `is_bank_applicable` flag) | N/A — Banking has no boolean-applicability field the way Statutory's `is_pf_applicable`/`is_esi_applicable` do; every field describes one account, not a flag-plus-optional-identifier pair |

---

## 14. Encryption — the precondition this plan cannot resolve on its own

`account_number_enc`'s naming is the one place in this entire investigation where a column name
itself asserts a control. Verified directly (`00_HRMS_SYSTEM_ARCHITECTURE.md:100`,
`HRMS_SYSTEM_DESIGN_BASELINE.md` §12/§18 H-2/§19 D-2, all read in full for this plan): **no
encryption mechanism exists anywhere in this codebase.** `pan_number_enc`/`aadhaar_number_enc`
are plain, unencrypted `TEXT` columns today — confirmed by grep, no `TypeDecorator`/Fernet/AES/KMS
wrapper anywhere in `core/` or `modules/`. If `employee_bank.account_number_enc` is built the same
way, it would be the third `_enc`-suffixed column in this codebase making a promise the code does
not keep.

**This is materially different from every open item in Statutory's own plan.** Statutory's
fields carry no `_enc` suffix and no document anywhere required encryption for them (`29_` §6:
"no source document requires it for these fields"). Banking's `account_number_enc` is the
opposite case: the naming convention, and the most recent architecture audit
(`HRMS_SYSTEM_DESIGN_BASELINE.md` Decision D-2), both treat encryption as expected, not merely
nice-to-have.

**Decision D-2, quoted directly:**

> **Options:** (1) implement column-level encryption (SQLAlchemy `TypeDecorator` + KMS) before
> E-02/E-07/E-08 ship; (2) ship without it and document the gap as an accepted, time-boxed risk
> with a committed remediation date.
> **Recommended:** Option 1 for any column that will hold real PAN/Aadhaar/bank data before
> go-live — this is closer to a compliance requirement than an engineering nicety given the DPDP
> framing throughout the product docs.
> **Impact if deferred:** real sensitive data lands in plaintext columns; remediation later
> requires a re-encryption migration against live customer data, plus a disclosure conversation.

`HRMS_SYSTEM_DESIGN_BASELINE.md`'s own readiness matrix marks E-08 "**READY WITH CONDITIONS**...
encryption (D-2) is the hard condition."

**This plan's position, stated precisely so it cannot be misread as either "blocked" or "cleared
to ship real data without encryption":** the schema, model, repository, service, API, and tests
this plan specifies can be built and merged exactly as Statutory's were, using synthetic values
in the dev database, with **zero new blocking dependency on Payroll, E-10, or the frontend** — the
same "ready to implement" posture as every other section of this plan. What this plan does
**not** clear is writing **real** account numbers into `account_number_enc` in a production
environment before either (a) a real encryption mechanism is built, or (b) an explicit,
documented compliance sign-off accepts the gap with a stated remediation date — exactly
Option 2's own condition, not a silent default. This is named as **OPEN PRODUCT DECISION PD-4**
(§15) and restated at the readiness verdict (§22) precisely because it is the one item in this
plan that is a genuine precondition on data, not a preference about code shape.

---

## 15. Product Decisions

Four decisions genuinely need product/engineering sign-off. Unlike Statutory's plan (where most
open items were low-stakes naming/FY-boundary questions), two of these four are substantive
enough that this plan recommends resolving them **before**, not during, implementation — named
explicitly in §22.

### PD-1 — Data-scope posture for `EMPLOYEE.VIEW_BANKING`

**Question**: does `EMPLOYEE.VIEW_BANKING` discard its resolved `DataScope` and remain
`COMPANY`-only (matching what Compensation/Statutory actually shipped), or does it bind the
resolved scope through `resolve_visible_employee_ids` (matching the LOCKED `RBAC_DATA_SCOPE_
DECISIONS.md` Decision E, which explicitly names `SELF`-scoped self-service for banking as the
intended default)?

**Options**:
1. `COMPANY`-only, discard scope. Zero new engineering, perfectly consistent with Statutory's
   actually-shipped behavior. Perpetuates the gap between the locked decision and shipped code
   for a third RESTRICTED sub-resource.
2. Bind the resolved scope generically (reuse `resolve_visible_employee_ids`, already built and
   tested). Implements the locked decision as originally specified. Costs roughly the same
   engineering effort as option 1 (the mechanism already exists) but creates a **visible
   inconsistency** with Statutory's `COMPANY`-only behavior unless Statutory is also retrofitted
   in the same change.

**Recommended**: Option 2 for the `GET` routes, specifically because "can I see my own salary
account" is one of the most obviously legitimate self-service needs in the entire system, the
underlying mechanism is already built and tested (not a "no infra exists" blocker, unlike what
Statutory's own plan implied), and the locked decision directly names this exact case. If Option
2 is chosen, this plan additionally recommends a **fast-follow, not a blocker**: retrofit
`EMPLOYEE.VIEW_STATUTORY` to the same behavior, so the two RESTRICTED sub-resources this module
now has stop diverging on a question neither one actually needed to diverge on. **Does not
block implementation** — Option 1 remains a fully coherent, shippable fallback if product prefers
consistency with the immediately-prior slice over implementing the locked decision now.

### PD-2 — Does a bank write require a covering employment episode, and does it extend past exit?

**Question**: see §9 in full. Does `create_bank` require `EmploymentRepository.get_employment_
as_of` to resolve (matching every sibling sub-resource), and if so, should post-exit corrections
(dated after `last_working_day`, needed for F&F-settlement accuracy per §7's own stated
rationale) be permitted at all — and if they should, by what rule?

**Options**:
1. Reuse `get_employment_as_of` exactly as Statutory does (resolves against any past-or-present
   episode covering the date). Simple, consistent, but does not fully satisfy the F&F-correction
   scenario for dates strictly after `last_working_day`.
2. Drop the covering-employment check for Banking entirely. Fully satisfies the F&F-correction
   scenario, but permits a bank write against an employee with no employment history at all — a
   materially looser invariant than every sibling sub-resource, not requested by any document.
3. Reuse `get_employment_as_of`, plus an additional allowance: if no *current* episode covers
   `effective_from` but the employee's *most recent* episode (regardless of status) has
   `last_working_day` on or before `effective_from`, permit the write anyway (a bank-specific
   "grace period" rule). Satisfies the F&F scenario precisely, but is a bespoke rule this plan
   would be inventing, not sourced from any document.

**Recommended**: Option 1, as the smallest-diff, most consistent-with-precedent choice, with the
F&F-correction gap named explicitly as a known limitation (not silently accepted) — Option 3 is
presented because it is the most likely eventual answer if product confirms the F&F scenario
matters in practice, but this plan does not adopt it unilaterally since no document requests it.
**Does not block implementation** of the rest of the slice; narrowly scopes what "known
limitation" means for the F&F-correction case specifically.

### PD-3 — Partial masking (`******7890`) vs. whole-sub-resource gating

**Question**: `docs/product/19_RBAC_and_Permission_Matrix.md` §6, `02_EMPLOYEE_DATA_MODEL.md`
§2G, and `docs/design/screens/01_Employee_List_Directory.md` all independently document a
partial-masking format for the bank account number. No RESTRICTED field in this codebase has ever
implemented partial masking — Compensation and Statutory both use binary whole-sub-resource
gating (full response, or `403`/absent) exclusively.

**Options**:
1. Whole-sub-resource gating only, matching every existing precedent exactly (no masking
   infrastructure exists anywhere in this codebase to build on). The documented `******7890`
   format remains a stated intention this slice does not implement, same as it already is today
   for every other mention of it across the four documents above.
2. Build a new masked-view tier: some permission (not yet named by any document) sees
   `******7890`-shaped output, `EMPLOYEE.UPDATE_SENSITIVE`/a hypothetical "view full" grant sees
   the raw value. This is genuinely new infrastructure — no document names which permission
   should get the masked view versus the full view, so this option cannot be built without first
   resolving that sub-question either.

**Recommended**: Option 1, for the same reason `29_` recommended it for Statutory: no document
resolves *which permission* gets the masked view versus the full view (a real, unresolved
sub-question even if masking-in-general is decided), and every existing precedent in this
codebase uses whole-resource gating exclusively. **Does not block implementation.**

### PD-4 — Encryption for `account_number_enc` (see §14 in full)

**Question**: build real column-level encryption before this slice writes real data, or ship the
schema/code now and defer encryption with an explicit, documented compliance sign-off?

**Recommended**: per Decision D-2 directly — encryption should land before real account numbers
are written to production, but this does **not** block building/merging the schema, code, and
tests in this plan (which can and should use synthetic dev-database values, same as every prior
Employee slice). **This is the one item in this plan that genuinely gates production data, not
code** — see §22 for exactly how this plan's readiness verdict accounts for it.

---

## 16. Security Threat Model

| Threat | Analysis | Requirement this plan imposes |
|---|---|---|
| IDOR (guessing another employee's `statutory_id`-equivalent) | Same shape as every sibling sub-resource — `bank_id` scoped by `employee_id` + `company_id` in every repository query | `get_bank`/`get_bank_as_of` must filter on all three, mirroring `EmployeeStatutoryRepository` exactly |
| Cross-tenant access | RLS + explicit `company_id` filtering, belt-and-suspenders, matching every table in this codebase | `404`, never `403`, for a cross-tenant `employee_id` or `bank_id` — verified by direct test, same as every prior slice |
| Manager access | Decision F: "No, by default" | No default grant of `.VIEW_BANKING` to any manager-shaped role in seed data; no code path lets `REPORTEES`/`REPORTEE_TREE` see wider than `COMPANY` for this permission |
| Employee self-access | Decision E: `SELF`-scoped by default — genuinely open, PD-1 | If PD-1 resolves to Option 2, self-access must be positively tested (a caller with only `SELF`-scoped `.VIEW_BANKING` and a matching `employee_id` claim sees their own row, and *only* their own row, never another employee's) |
| Privilege escalation | No manager-reference field exists on `employee_bank` (unlike Assignment's `reporting_manager_id`) — the self-elevation-guard precedent (`27_REPORTING_MANAGER_SECURITY_AUDIT.md`) has no direct analogue here, since there is nothing on this table whose value could expand the writer's own future data scope | No self-elevation guard needed on the write route, matching Statutory's own conclusion (`29_` §16) for the identical reason |
| Mass assignment | `extra="forbid"` on `BankCreate`; `id`/`company_id`/`employee_id`/`version`/`effective_to`/`is_primary`/`verification_status`/`penny_drop_reference` all system-set, never client-writable | Verified by a dedicated test, same as every sibling `Create` schema |
| Account-number leakage | Whole-sub-resource gating (PD-3 default) means the raw `account_number_enc` value is either fully present (caller holds `.VIEW_BANKING`) or fully absent (caller does not) — no intermediate leak surface unless PD-3 later chooses partial masking | Same "omitted, not null" convention as every RESTRICTED field in this codebase |
| API response leakage | Same Pydantic response-model convention as Compensation/Statutory — masked fields must be **omitted** from JSON, never sent as `null` | Verified by raw-JSON assertion in tests, matching `docs/product/19` §6's mandated check shape |
| Audit leakage | Write-path `AuditService.record()` payloads are plain JSONB, unencrypted, project-wide — same pre-existing limitation Compensation/Statutory already carry, not new to Banking | Must be named in the closeout report, not silently inherited |
| Enumeration | Same as every sibling — a nonexistent or cross-tenant `bank_id`/`employee_id` produces an identical `404` to a real one the caller cannot see, no distinguishing signal | Verified by test |
| Historical-record exposure | Closed (non-current) bank rows remain readable by id to any caller holding `.VIEW_BANKING` — same precedent as Compensation/Statutory's own historical-row visibility (no separate "archived record" permission tier exists anywhere in this codebase) | No new restriction proposed; matches existing precedent |
| Real sensitive data in a plaintext-despite-naming column | `account_number_enc` — see §14/PD-4 in full | The single highest-severity item in this threat model; not a code-level fix this plan can make alone |

---

## 17. Audit

Mirrors `STATUTORY_REVISED`/`COMPENSATION_REVISED` exactly: one event per write, via the existing
`AuditService.record(...)` signature. **Action name: `BANK_REVISED`**, `entity_type=
"employee_bank"` — following the `<TABLE-CONCEPT>_REVISED` naming convention every prior
effective-dated slice used (`COMPENSATION_REVISED` for `employee_compensation`, `STATUTORY_
REVISED` for `employee_statutory`). `before` is `null` for an employee's first bank row, and the
closed row's snapshot otherwise. Same pre-existing, project-wide limitation as every other slice:
audit payloads are plain JSONB, unencrypted — not a new gap, must be named, not silently
inherited (§16).

No termination-triggered audit event is added (unlike Statutory's own `BANK_REVISED`-on-close
that this plan explicitly does **not** propose, per §7) — there is no service-layer write at
termination time for Banking at all.

---

## 18. Test Plan

Full matrix, mirroring `29_` §21's structure, adjusted for Banking's own distinct behaviors (§7,
§9):

**Functional**: create (first row, no `If-Match`); create (revision, closes current, requires
`If-Match`); read (current, `as_of`, full history, single-by-id); list ordered by
`effective_from`.

**Effective dating**: GiST overlap rejected at the DB level (bypass RLS with `SET LOCAL
row_security = off`, assert `IntegrityError`, matching Compensation's/Statutory's own proof
pattern); `effective_from` not strictly after current row's own → `422 INVALID_EFFECTIVE_FROM`.

**Employment dependency (PD-2's resolved answer, §9)**: no covering employment episode at all →
`409 NO_ACTIVE_EMPLOYMENT`; a bank write dated on/before `last_working_day` for a terminated
employment succeeds (covered by the closed episode); a bank write dated strictly after
`last_working_day` — the named F&F-correction gap — behaves per whichever PD-2 option is chosen,
and the test must assert that behavior explicitly, not assume it.

**Termination interaction (§7, the load-bearing difference from every sibling)**: after
`terminate_employment`, the employee's current bank row remains **open** (`effective_to IS
NULL`) — a direct, explicit test asserting this, structured as the negative counterpart to
`test_rehire_first_statutory_after_gap`'s own positive "row gets closed" assertion. A rehire's
first bank write, because the pre-exit row was never auto-closed, must be tested as taking the
**close-then-insert** branch (`If-Match` required, referencing the pre-exit row's version) —
explicitly different from Compensation's/Statutory's own rehire tests, which take the "no current
row" branch.

**Concurrency**: stale `If-Match` → `409 STALE_RESOURCE`; missing `If-Match` with a current row →
`422` (a version-required error, name per implementation — mirrors `STATUTORY_VERSION_REQUIRED`).

**Mass assignment**: `version`/`company_id`/`is_primary`/`verification_status`/
`penny_drop_reference` in the request body → `422`.

**Permissions/data-scope**: caller with only `.VIEW_BANKING` reads, cannot write; caller with
only `.UPDATE_SENSITIVE` writes, cannot read without `.VIEW_BANKING`; caller with neither → `403`.
Cross-tenant `GET`/`POST`/list → `404`. RLS proven directly at the DB layer. **Depends on PD-1's
resolution**: if `COMPANY`-only, an explicit negative test proving a non-`COMPANY` `data_scope`
grant is still ignored (mirroring `test_view_statutory_ignores_non_company_data_scope`); if
`SELF`-wired, a positive test proving a `SELF`-scoped caller sees only their own row, and a
negative test proving they cannot see another employee's.

**Sensitive-field protection**: `account_number_enc`/`ifsc`/`account_holder_name`/etc. absent
(not null) from any response when the caller lacks `.VIEW_BANKING` — raw-JSON assertion, matching
every RESTRICTED-field precedent in this codebase.

**System-managed fields**: `is_primary`/`verification_status`/`penny_drop_reference` cannot be
set via the request body even when included (ignored or `422` under `extra="forbid"` — the
latter, matching every other system-set field's treatment in this module); every created row has
`verification_status == "PENDING"` unconditionally.

**Invalid input**: invalid `payment_mode` → `422`; oversized `ifsc`/`bank_name`/etc. beyond column
length → `422`.

**Cross-tenant references**: cross-tenant `employee_id` on `GET`/`POST` → `404`, matching every
sibling.

**Payroll contract (negative test)**: `get_bank_as_of` returns raw data only — no test in this
suite exercises or references any `bank_advice`, calculation, or `payrun_*` construct, mirroring
Statutory's own negative-scope test.

**Audit**: exactly one `AuditLog` row per write, `action == "BANK_REVISED"`, `entity_type ==
"employee_bank"`, `before_json is None` on first write.

Unit tests (`EmployeeBankService`, mirroring `test_employee_statutory_service.py`'s structure):
first-row success, no-covering-employment rejection, unknown-employee rejection, revision
close-then-insert, `If-Match` requirement, stale-effective-from rejection, stale-version conflict,
GiST-overlap-to-domain-error translation, mass-assignment/invalid-`payment_mode` schema
validation, and the read-path cases (`list`/`get`/`as-of`, including that `get_bank_as_of` does
not require an employee lookup).

---

## 19. Implementation Sequence

Adapted from `29_` §20, with the Employment-service change explicitly **removed** (§7 — no
`EmploymentService` change is proposed for Banking):

1. `EmployeeBank` ORM model in `models.py`, keyed on `employee_id`, matching `EmployeeStatutory`'s
   exact shape/docstring convention, adding a docstring note that explicitly states the
   termination-survival behavior (§7) so a future reader does not assume the closing pattern
   applies here too.
2. `EmployeeBankRepository` in `repository.py`: `insert_bank`, `get_current_bank`,
   `get_bank_as_of`, `list_banks`, `get_bank`, `close_bank` — method-for-method mirror of
   `EmployeeStatutoryRepository`.
3. `BankCreate`/`BankRead` schemas + `bank_to_audit_dict`/`bank_to_read` in `schemas.py`. No
   `revision_reason` field (§5/§13).
4. Service-layer `EmployeeBankService` in `service.py`: `create_bank` (covering-employment check
   per PD-2's resolution, close-current-then-insert, audit call — **no** termination-close logic
   added anywhere), `get_current`, `get_as_of`, `list`.
5. Router routes in `router.py` per §20 (below), including whichever data-scope wiring PD-1
   resolves to.
6. New exception classes in `exceptions.py`: `BankDatesOverlapError`, `BankVersionRequiredError`
   — direct copies of `StatutoryDatesOverlapError`/`StatutoryVersionRequiredError`'s shape. No
   `TaxRegimeSwitchNotAllowedError`-equivalent — Banking has no analogous once-per-period rule in
   any source document.
7. `dependencies.py`: `get_employee_bank_service`, mirroring the five existing factory functions.
8. `permissions.py`: add `EMPLOYEE_VIEW_BANKING` constant + `EMPLOYEE_PERMISSIONS` entry; widen
   `EMPLOYEE_UPDATE_SENSITIVE`'s *usage* (not its definition — the constant already exists) to
   also gate the Banking `POST` route.
9. One Alembic migration per §6's DDL, structured as a foundational `CREATE TABLE` (same
   reasoning as Statutory's own migration — this table has no pre-existing skeleton).
10. Encryption (PD-4) — resolved as its own tracked item, not silently bundled into step 9; if
    Option 1 (build real encryption) is chosen, it should land as a preceding or parallel task
    that both this migration and E-02's own eventual PAN/Aadhaar write path can share, not a
    Banking-specific one-off.

---

## 20. API Design

Exact routes, mirroring `31_EMPLOYEE_STATUTORY_API.md`'s shape:

| Method | Path | Permission | Response |
|---|---|---|---|
| GET | `/v1/employees/{employee_id}/bank` (`?as_of=YYYY-MM-DD`) | `EMPLOYEE.VIEW_BANKING` | `ListEnvelope[BankRead]` |
| GET | `/v1/employees/{employee_id}/bank/{bank_id}` | `EMPLOYEE.VIEW_BANKING` | `DataEnvelope[BankRead]` |
| POST | `/v1/employees/{employee_id}/bank` | `EMPLOYEE.UPDATE_SENSITIVE` | `DataEnvelope[BankRead]`, `201` |

No `PATCH`/`DELETE` — insert-only revision API, identical shape to Compensation/Statutory
(`HRMS_ARCHITECTURE_DECISION_LOG.md:279`: "Statutory, Bank) exposes only `POST` for a revision...
No `PATCH`/[DELETE]"). `If-Match` optional header, required only when a current row exists.

**Request body** (`BankCreate`, `extra="forbid"`): `effective_from` (required),
`account_holder_name`/`bank_name`/`branch_name` (optional strings), `account_number_enc`
(optional string — the plaintext value at the API boundary; §14 governs what happens to it at
rest), `ifsc` (optional string), `payment_mode` (enum `BANK`/`CASH`/`CHEQUE`/`UPI`, required — no
document states it optional, and a bank row without a stated payment mode is not a meaningful
record). No `revision_reason`, `is_primary`, `verification_status`, or `penny_drop_reference` —
none are client-writable (§13).

**Error cases**: `404` cross-tenant/nonexistent employee; `409 NO_ACTIVE_EMPLOYMENT` (PD-2);
`409 BANK_DATES_OVERLAP` (GiST translation); `422 INVALID_EFFECTIVE_FROM`; `422 BANK_VERSION_
REQUIRED`; `409 STALE_RESOURCE`; `403 PERMISSION_DENIED`. Every one has a direct template already
shipped in `exceptions.py` today.

---

## 21. Frontend Implications

Out of scope for this investigation — no frontend code exists or was researched beyond confirming
its absence (`HRMS_FRONTEND_CAPABILITY_AUDIT.md`: "**NO UI.** No employee banking router/module
under `apps/api/src/hrms/modules/`. **MISSING** frontend and backend" — itself now half-stale the
moment this plan's own backend slice ships).

For the future UI's own planning purposes only, per `04_EMPLOYEE_UX_PLAN.md`'s own explicit
recommendation (§64-69, written before E-07 shipped and not yet updated for it): Banking has no
tab of its own in the documented 9-tab profile view — recommend surfacing it as a sub-section
within the Compensation tab (same placement Statutory's own UX plan recommended), gated on
`EMPLOYEE.VIEW_BANKING` for visibility and `EMPLOYEE.UPDATE_SENSITIVE` for the edit action, until
product confirms a dedicated tab. The screen will need to:

1. Show/hide the entire section based on `EMPLOYEE.VIEW_BANKING` ("absent, not disabled").
2. Render the account number in the documented masked format (`******7890`) **if and only if**
   PD-3 resolves to building partial masking — otherwise render the full value only when present
   at all (binary gating), same as Compensation's/Statutory's own UI will need to.
3. Gate the edit action on `EMPLOYEE.UPDATE_SENSITIVE`.
4. Surface `409`/`422` error codes from §20 as field-level messages.
5. Since Banking rows remain open through and after termination (§7), the UI must **not** assume
   "current bank row absent" is a valid state for an exited employee the way it might for
   Assignment/Compensation — a design detail worth naming now so a future UI task does not
   silently assume the closing pattern applies here too.
6. If PD-1 resolves to `SELF`-scoped self-service, the employee's own profile view (not just the
   HR-facing 360° view) becomes a real consumer of this API for the first time in this module —
   worth flagging to whoever designs E-09, since no other RESTRICTED sub-resource currently has a
   genuine self-service consumer either.

---

## 22. Readiness Verdict

**READY TO IMPLEMENT** the schema, model, repository, service, router, permissions, migration,
and tests exactly as specified in this plan — with two items requiring an explicit product/
engineering decision **before** implementation starts (not blocking the *existence* of this plan,
but genuinely shaping what gets built):

1. **PD-4 (encryption, §14/§15)** — resolve whether real column-level encryption lands
   alongside this slice, or whether the gap is consciously deferred with a documented compliance
   rationale and remediation date. This is the one item this plan cannot respons­ibly default on
   its own, because the choice is a compliance posture, not an engineering preference — but it
   does **not** block building/testing the slice against synthetic dev-database values, exactly
   as every prior Employee slice has done.
2. **PD-1 (data-scope posture, §8/§15)** — resolve whether `EMPLOYEE.VIEW_BANKING` matches
   Statutory's `COMPANY`-only precedent or implements the LOCKED `SELF`-scope decision. Either
   answer is fully implementable; this plan recommends resolving it explicitly before coding
   starts specifically because it determines the router's dependency wiring (§19 step 5) and the
   test matrix's shape (§18), not because either option is itself risky.

PD-2 (covering-employment/F&F-correction scope, §9) and PD-3 (masking, §15) do **not** block
implementation — this plan's own recommended defaults (§15) are sufficient to proceed, with the
resulting behavior named explicitly in the eventual closeout report, matching how Statutory's own
open items were handled.

**First action for the implementing agent**: confirm PD-1 and PD-4 with product/engineering if a
fast answer is available; if not, proceed with this plan's recommended defaults (Option 2/`SELF`-
wired for PD-1, Option 1/build-encryption for PD-4 if time permits, otherwise Option 2/documented
deferral) and flag both explicitly in the closeout report, exactly as `29_`/`32_` did for their
own open items. The concrete first implementation step, once decisions are confirmed: the
`EmployeeBank` ORM model (§19 step 1), following `EmployeeStatutory`'s exact shape.

---

## 23. Explicit Scope Exclusions

Restated from this task's own strict exclusions, confirmed still applicable after this
investigation:

Payroll (`bank_advice` generation, NEFT/RTGS/IMPS file formats, FR-PAY-018 — confirmed no code or
migration exists), salary calculation, payment execution (no funds-transfer code exists or is
proposed anywhere), bank/payment-gateway integrations (no penny-drop provider, no NEFT/RTGS/UPI
gateway integration exists or is proposed), Attendance, Leave, Recruitment, ATS, Performance,
Workflow, E-10's `sensitive_access_log` implementation (the seam is named at §8, not built),
frontend implementation (§21 is planning-only), real column-level encryption implementation
(§14/PD-4 names the decision; building the `TypeDecorator`/KMS mechanism itself is not part of
this plan), any change to `EmploymentService.terminate_employment` (§7 explicitly recommends
**against** one), undocumented statutory/banking fields, a new generic effective-dating
framework, and a new RBAC scope level.

---

## Final Verification (this investigation)

Performed directly against the live repository/database while writing this plan, not assumed:

- `\dt` against the dev database confirms `employee_bank` does not exist (31 tables, none
  banking-related).
- `information_schema.columns` search confirms zero columns anywhere match
  `%bank%`/`%account%`/`%ifsc%`/`%payment%`/`%cheque%`.
- `alembic current` confirms the migration head is `20260815130000` (Statutory, this task's
  immediately-prior slice) — unchanged by this investigation.
- `permission` table confirms `EMPLOYEE.UPDATE_SENSITIVE` exists as a code-backed row (via E-07);
  `EMPLOYEE.VIEW_BANKING` does not exist anywhere, database or code.
- `grep` across `apps/api/src` and `apps/web` confirms zero lines of application code reference
  `employee_bank`, `EmployeeBank`, or `VIEW_BANKING` anywhere, other than this task's own prior
  slice's forward-looking docstring comments in `permissions.py`.
- `git status`/`git diff --stat` confirm this task modified **no** application code, migration,
  or test file — the only new file this task produced is this plan document itself.
