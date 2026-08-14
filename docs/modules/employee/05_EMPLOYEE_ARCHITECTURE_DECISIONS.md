# Employee Architecture — Decision Record

Status: **Architecture decision gate — no application code, migrations, or frontend changed.**
Companion to `00_EMPLOYEE_AUDIT.md`, `01_EMPLOYEE_MODULE_PLAN.md`, `02_EMPLOYEE_DATA_MODEL.md`,
`03_EMPLOYEE_API_PLAN.md`, `04_EMPLOYEE_UX_PLAN.md`, `docs/design/screens/01_Employee_List_Directory.md`.
This document converts the audit's ten open product decisions (`00_EMPLOYEE_AUDIT.md §17`) into a
locked, implementation-ready position, and states the final conceptual model E-01 onward must build
against. Nothing here invents a requirement absent from the source documents; where the sources are
silent, that silence is stated explicitly rather than filled in.

Every decision below is tagged **DECIDED**, **DEFERRED**, or **REQUIRES PRODUCT DECISION**.

---

## Part A — The ten open decisions (`00_EMPLOYEE_AUDIT.md §17`), resolved

### A1. Rejoin mechanics

> `00_EMPLOYEE_AUDIT.md §17.1`: "confirm same `employee_id`/`employee_code` reuse, new `employment`
> row with `is_rehire`/`previous_employment_id`. *Recommendation: adopt as described in §8.4.*"

**Why it matters.** This is the single decision the entire Employee aggregate is organized around.
Every other table's FK shape (`employee_assignment.employee_id`, `employee_compensation.employee_id`,
not `*.employment_id`) only makes rehire correct *by construction* if this decision is confirmed
before E-03's migration is written. Reversing it later means migrating every child table's FK.

**Downstream dependents.** Attendance (stable identity across a rejoin gap), Leave (whether balance
resets), Payroll (whether UAN/statutory continuity is expected), ESS (whether a returning employee
sees their old profile or a blank one), Reporting (headcount/tenure calculations that span a gap).

**Options.**
1. Same `employee_id`/`employee_code`, new `employment` row (`is_rehire=true`,
   `previous_employment_id` set) — audit's documented recommendation, already schema-shaped.
2. New `employee_id` for the second spell, linked by a separate "prior identity" reference — rejected
   by the audit as contradicting the PRD's own Employment definition ("supports rehire... as separate
   employment rows for **one** employee") and the live schema's own FK shape.

**Recommendation.** Option 1, exactly as audited (`00_EMPLOYEE_AUDIT.md §8.4`). This is also §B/§A of
the brief's own locked direction (Part B below) — no contradiction found in the audit.

**Consequences.** `employee_assignment`/`employee_compensation`/`employee_statutory`/`employee_bank`
must all key off `employee_id`, never `employment_id` — this is now a binding schema constraint, not
a stylistic choice. A rehire's new assignment/compensation rows start fresh at the new joining date;
nothing is assumed to carry forward automatically (§ Part C, Employee Assignment).

**Timing: NOW.** Confirmed by the audit as blocking E-03's own migration (`employment.is_rehire`/
`previous_employment_id` are columns on the very first table E-03 extends).

**Residual open item inside this decision — REQUIRES PRODUCT DECISION.** `employment.status`'s value
set is undefined in every source document (`00_EMPLOYEE_AUDIT.md §5` conflict row 3): "`employment`
gives its own `status` column but never enumerates values." Neither `00_EMPLOYEE_AUDIT.md` nor its
companions contain the full FR-EMP-014 ten-state enumeration for `employee.status` either — it is
referenced by name and count only, never listed. This document does not invent either enumeration.
**Recommendation, not a substitute for product sign-off**: `employment.status` should be a narrow
subset scoped to one spell (e.g. `ACTIVE` / `ON_NOTICE` / `TERMINATED`), never a copy of the full
`employee.status` machine — an employment spell doesn't have a `PRE_JOINING` or `PROBATION` state
independent of the identity-level state, so duplicating the full enum would let the two disagree
(e.g. `employee.status = ACTIVE` while `employment.status = PRE_JOINING` is meaningless). This
narrowing principle is locked; the literal string values are not — obtain the FR-EMP-014 source
document's full 10-state list and the `employment.status` subset from product before E-03's migration
is finalized.

---

### A2. Build `employee_statutory`/`employee_bank` now, or defer?

> `00_EMPLOYEE_AUDIT.md §17.2`: "Payroll's dependency contract needs them; no later module is
> documented as owning them. *Recommendation: build as part of Employee's own migration set, even
> with no UI surface until Payroll ships.*"

**Why it matters.** These two tables don't exist in any migration today (`00_EMPLOYEE_AUDIT.md §3.5`).
If Employee ships without them, Payroll — a hard downstream dependency per
`VERSION_1_ROADMAP.md §6` ("Employee Management must exist before... Payroll") — has nowhere to read
PF/ESI/tax/bank data from, and no other module is documented as the owner who would build them
instead.

**Downstream dependents.** Payroll directly (§15.3 dependency-contract table: "Statutory jurisdiction,
PF/ESI/tax for a pay period" and "Bank account for payout" both cite these two tables by name as the
source). DPDP Act 2023 compliance (`docs/product/23 §4-5`, cited in `00_EMPLOYEE_AUDIT.md §4`) also
depends on these existing as their own access-controlled tables rather than columns bolted onto
`employee`.

**Options.**
1. Build both tables now, inside Employee's own slices (E-07/E-08), with no UI surface until Payroll
   ships — audit's recommendation.
2. Defer to a later, Payroll-owned migration.

**Recommendation.** Option 1. Deferring risks the exact failure mode the audit calls out: Payroll's
turn arrives and finds no foundation, forcing an emergency Employee-domain migration mid-Payroll-build
instead of a planned one inside Employee's own sequence.

**Consequences.** E-07 (Statutory) and E-08 (Documents/Bank, among others) are non-optional slices,
not stretch goals — cutting them under schedule pressure defers the cost onto Payroll's own timeline,
which is a worse place to discover it.

**Timing: NOW** (the decision to build them is locked; the exact permission code gating their view is
a separate, still-open decision — see A9 below).

---

### A3. The BR-14 / FR-EMP-018 override-chain mechanism

> `00_EMPLOYEE_AUDIT.md §17.3`: "spans five already-shipped modules, no buildable spec exists
> anywhere. *Recommendation: Employee ships only the confirmed leg
> (`employee_assignment.shift_id`, a direct per-employee value); the cascading-default mechanism is a
> separate, later, cross-module decision.*"

**Why it matters.** The audit found the override-chain direction stated inconsistently between two
source documents (`00_EMPLOYEE_AUDIT.md §5` conflict row 2: PRD's top-down ordering omits
Designation; FR-EMP-018's bottom-up ordering includes it) — this is not a detail to resolve by
inference during Employee's build; it needs its own product/design decision, informed by Shift Rules'
actual shipped behavior, which Employee's audit did not re-litigate.

**Downstream dependents.** Attendance (shift resolution when `shift_id IS NULL`), Leave
(entitlement/notice-period resolution), any future policy-cascade UI.

**Options.**
1. Employee ships the direct leg only (`employee_assignment.shift_id`, settable, nullable) and
   Attendance is built to tolerate `NULL` — audit's recommendation.
2. Attempt to build the cascading resolution inside Employee's own assignment slice (E-04/E-05).

**Recommendation.** Option 1. Building option 2 now would mean inventing cross-module override
behavior the brief explicitly forbids ("Do NOT invent cross-module override behaviour").

**Consequences.** Every consumer of `shift_id` (Attendance foremost) must treat `NULL` as a legitimate,
expected value — "no shift resolves" — not an error state, until the override chain is designed as
its own cross-module decision involving Shift Rules, Attendance, and whichever module ends up owning
the cascade.

**Timing: DEFERRED**, exactly as the brief's item H instructs — record it, do not design it now.

---

### A4. RBAC granularity

> `00_EMPLOYEE_AUDIT.md §17.4`: "full 14-code catalogue vs. the organisation module's
> single-permission shortcut. *Recommendation: full catalogue — documented, specific, partially
> already seeded.*"

**Why it matters.** The organisation module's convention (one `ORG.<ENTITY>.MANAGE` permission gating
both view and manage) is explicitly called out by the audit as unsuitable for Employee: Employee's
own RBAC document specifies `VIEW` vs `VIEW_ALL` as "what separates a Reporting Manager from an HR
Manager" (`00_EMPLOYEE_AUDIT.md §13.1`) — collapsing that distinction isn't a simplification, it's a
silent regression of a named design decision.

**Downstream dependents.** Every future tabbed module built on the same 360° profile pattern
(Attendance, Leave, Payroll tabs) inherits whichever granularity Employee establishes; ESS's
self-service surface depends on `VIEW`-vs-`SELF` being real distinctions, not a single company-wide
switch.

**Options.**
1. Full 14-code catalogue (`EMPLOYEE.VIEW`, `.VIEW_ALL`, `.CREATE`, `.UPDATE`, `.UPDATE_SENSITIVE`,
   `.DEACTIVATE`, `.VIEW_COMPENSATION`, `.UPDATE_COMPENSATION`, `.VIEW_DOCUMENTS`,
   `.UPLOAD_DOCUMENTS`, `.VERIFY_DOCUMENTS`, `.VIEW_PERSONAL_CONTACT`, `.TRANSFER`, `.PROMOTE`,
   `.CONFIRM`, `.IMPORT`, `.EXPORT`, `.GENERATE_LETTER`, `.VIEW_AUDIT`, `.BACKDATE_OVERRIDE` — audit
   counts 14 named codes with some grouped; see `00_EMPLOYEE_AUDIT.md §13.1` for the exact list).
2. Organisation-module single-permission shortcut.

**Recommendation.** Option 1, as audited. Do not add codes beyond the 14 without a documented need
(`00_EMPLOYEE_AUDIT.md §13.5`).

**Consequences.** Data-scope resolution (`SELF`/`REPORTEES`/`REPORTEE_TREE`/`DEPARTMENT`/`BRANCH`/
`LEGAL_ENTITY`/`COMPANY`/`ALL_COMPANIES`) is genuinely new infrastructure — the existing
`DataScope`/`DataScopeLevel` type is unused beyond hard-coded `COMPANY` today
(`00_EMPLOYEE_AUDIT.md §13.2`). Budget this as new build, not a reuse.

**Timing: NOW** for the catalogue shape (it gates E-01's very first `CREATE`/`VIEW` permissions);
the two still-unnamed codes (statutory/banking view — A9 below) remain open within this decision.

---

### A5. FR-ORG-014 retrofit into Branch/Department/Designation/Grade

> `00_EMPLOYEE_AUDIT.md §17.5`: "once Employee exists, these four modules need an
> active-employee-count deactivation-blocking check added. *Recommendation: a small, separate
> follow-up task against the organisation module, not bundled into Employee's own vertical slices.*"

**Why it matters.** Every one of these four modules today explicitly skips this check in code
comments "because Employee doesn't exist yet" (`00_EMPLOYEE_AUDIT.md §2.3`) — Employee's existence is
what makes the skip incorrect, but the fix lives in someone else's module.

**Downstream dependents.** Organisation module's own deactivation safety (a Department with active
employees could otherwise be deactivated out from under them) — not a downstream *module*, but a
downstream *task* Employee's shipping unblocks.

**Options.** (1) Bundle into an Employee slice; (2) small standalone follow-up PR against
`organisation/` after Employee ships.

**Recommendation.** Option 2, as audited — this is scope discipline: Employee's slices build
Employee, not retrofit Organisation.

**Consequences.** Must be tracked so it doesn't silently stay "skipped because Employee doesn't exist"
forever after Employee does. Recommend filing as a tracked follow-up ticket at E-01's close, not an
implicit TODO.

**Timing: DEFERRED** — explicitly a post-Employee follow-up, not part of the ten-slice sequence.

---

### A6. `EMPLOYEE_SEATS` enforcement point

> `00_EMPLOYEE_AUDIT.md §17.6`: "no document specifies where/how the seat-limit check fires.
> *Recommendation: `EmployeeService.create_employee` counts active employees against
> `plan.employee_seat_limit` and rejects before insert...*"

**Why it matters.** Every plan (FREE/STARTER/PROFESSIONAL/ENTERPRISE) already carries a seat limit in
the seed data (`00_EMPLOYEE_AUDIT.md §2.3`), but **no code enforces it anywhere** today. Employee's
`create_employee` path is the first and only place this can be enforced, since Employee rows are the
thing being counted.

**Downstream dependents.** Billing/plan enforcement (Company module), bulk import (E-09 — a
5,000-row import must be checked against remaining seats before committing, not row-by-row after the
fact).

**Options.** (1) Enforce in `EmployeeService.create_employee`, single active-employee count check
before insert; (2) enforce at a higher layer (API gateway/billing service) Employee doesn't own.

**Recommendation.** Option 1, as audited — mirrors how existing write-blocking errors gate writes
elsewhere in the organisation module.

**Consequences.** Bulk import (E-09) must perform the same check against the *batch* size, not just
per-row, or a 5,000-row import could silently exceed the seat limit mid-batch. Flag this explicitly in
E-09's own design, not assumed to fall out of E-01's single-row check.

**Timing: NOW** — this is E-01's own create-path logic; cannot be deferred past the first slice that
creates an Employee row.

---

### A7. Migration approach for the four live stub tables (+ `employment.version`)

> `00_EMPLOYEE_AUDIT.md §17.7`: "extend in place via `ALTER TABLE`... rather than drop-and-recreate.
> *Recommendation: extend in place.* Also decide whether to add `version` to `employment` for
> consistency."

**Why it matters.** `employee`/`employment`/`employee_assignment`/`employee_compensation` are live
tables with production-shaped constraints (RLS, GiST exclusion) already in the first migration.
Drop-and-recreate would be destructive and inconsistent with every organisation-module precedent
(Designation→Grade's own follow-up migration pattern, `00_EMPLOYEE_AUDIT.md §16`).

**Downstream dependents.** Every slice that touches these four tables (E-01 through E-06) inherits
whichever migration discipline is set here.

**Options.** (1) `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` per table, one migration per table,
matching `02_EMPLOYEE_DATA_MODEL.md §3`'s proposed DDL; (2) drop and recreate.

**Recommendation.** Option 1, exactly as `02_EMPLOYEE_DATA_MODEL.md §3` proposes.

**Sub-decision — `employment.version`: REQUIRES PRODUCT DECISION, leaning yes.** `employment` is the
only employee-domain table without `version` (`00_EMPLOYEE_AUDIT.md §3.2`). The audit frames this as a
genuine choice, not an oversight: "employment rows are semantically append-mostly" is a real argument
for exemption. But `employment` is not append-only in this decision record's own locked model — a
rehire closes a row's `exit_date`/`status` in place (Part B §4), which is a mutation needing the same
optimistic-concurrency protection every other mutable row gets. **Recommendation: add `version`**,
for the same reason every other mutable table in this domain has it — two concurrent exit-processing
requests against the same `employment` row are a realistic race (HR + a scheduled batch job both
finalizing an exit), and `version` is the codebase's only concurrency-safety mechanism.

**Consequences.** Adding `version` now (E-03) costs one column; adding it after concurrent-write bugs
surface in production costs a hotfix migration under pressure. Cheap to decide now, expensive to
retrofit.

**Timing: NOW** — this is columns on the second table Employee's first slices touch.

---

### A8. Module location

> `00_EMPLOYEE_AUDIT.md §17.8`: "confirm `modules/employee/` as its own package, distinct from
> `organisation`. *Recommendation: confirm...*"

**Why it matters.** Every prior module (Company through Shift) lives inside `organisation/`. Employee
would be the first standalone package — a structural precedent for Attendance/Leave/Payroll, which
will look at Employee's placement as the template.

**Downstream dependents.** Import-linter boundaries (cross-module imports may only go through
`employee.service`, never `.repository`/`.models`, `01_EMPLOYEE_MODULE_PLAN.md §1`) — this rule only
has teeth if Employee is genuinely its own package with its own enforced boundary.

**Options.** (1) `apps/api/src/hrms/modules/employee/`, standalone; (2) fold into `organisation/`.

**Recommendation.** Option 1 — confirmed by two independent documents
(`docs/architecture/01_Backend_Structure.md:70`, `VERSION_1_ROADMAP.md §8` item 3), not merely this
audit's own preference.

**Consequences.** Sets the precedent Attendance/Leave/Payroll will each also be standalone packages,
not folded into `employee/` — worth stating explicitly now so a later "should Attendance live inside
Employee?" debate has a documented precedent to point at.

**Timing: NOW** — this is E-01's package scaffold, the very first file Employee's implementation
creates.

---

### A9. `sensitive_access_log` and the Statutory/Bank view permission

> `00_EMPLOYEE_AUDIT.md §17.9`: "both new, no existing pattern. *Recommendation: scope explicitly
> in/out of Employee's first slices rather than let either default to forgotten.*"

**Why it matters.** Two distinct gaps bundled in one audit item:
1. `sensitive_access_log` (FR-AUD-003) — a table logging *reads* of RESTRICTED fields, not just
   writes. No existing pattern; the organisation module's `AuditService` only logs writes.
2. No permission code in the 14-code catalogue names statutory or banking data specifically
   (`02_EMPLOYEE_DATA_MODEL.md §2` sections F/G) — the closest is `EMPLOYEE.UPDATE_SENSITIVE`, with no
   corresponding `VIEW` code named anywhere.

**Downstream dependents.** Payroll (needs a defined view permission to read statutory/bank data at
all), DPDP compliance (`docs/product/23`), the Compensation tab's Statutory/Bank sub-section
(`04_EMPLOYEE_UX_PLAN.md §2`) — currently undesignable without a permission to gate it on.

**Options for the permission gap.**
1. Bundle statutory/bank *view* under `EMPLOYEE.VIEW_COMPENSATION` (adjacent-permission reuse — the
   audit's own tentative assumption, explicitly flagged as unconfirmed).
2. Add two new codes (`EMPLOYEE.VIEW_STATUTORY`, `EMPLOYEE.VIEW_BANKING`) to the catalogue.

**Recommendation.** Option 2. Banking data specifically is called out by the brief (item F) as
needing "stricter permissions than ordinary employee profile information" — bundling it under
`VIEW_COMPENSATION` means anyone who can see CTC can see bank account numbers, which is a *broader*
grant than "stricter," not equal to it. A dedicated `EMPLOYEE.VIEW_BANKING` (and, for symmetry,
`EMPLOYEE.VIEW_STATUTORY`) keeps Payroll's own service-account access scoped narrowly without also
implicitly granting compensation visibility, and vice versa. This is a deviation from the audit's own
tentative option 1 — flagged here as a recommendation this document introduces, not one the audit
itself settled, because the audit explicitly left this as "a gap, not resolved here."

**Options for `sensitive_access_log`.**
1. Build now, as part of E-01/E-10 (RESTRICTED-field reads logged from day one).
2. Defer until a compliance-driven trigger (audit request, DPDP incident) forces it.

**Recommendation.** Build now, scoped to E-10 (not E-01) — Employee is explicitly named as "the first
module in the codebase handling RESTRICTED-tier data" (`00_EMPLOYEE_AUDIT.md §18`); shipping without
read-logging means the first RESTRICTED-data module in the product has no read audit trail from day
one, which is a compliance gap `docs/product/23`'s DPDP framework is unlikely to tolerate once
Payroll (a heavier RESTRICTED-data consumer) goes live.

**Consequences.** Two new permission codes beyond the audited 14 — a deliberate, documented deviation,
not scope creep (§13.5's "don't add codes without documented need" is satisfied by the reasoning
above). `sensitive_access_log`'s exact schema is out of scope for this document; only the decision to
build it now, inside E-10, is locked.

**Timing: REQUIRES PRODUCT DECISION** on the exact permission-code names (a naming choice, not an
architectural one — safe to finalize immediately before E-01's permission seed, not a blocker to
starting E-01's other work). The decision to build `sensitive_access_log` at all is **DECIDED** (build
in E-10); its schema is **DEFERRED** to E-10's own design.

---

### A10. Frontend permission-gating primitive

> `00_EMPLOYEE_AUDIT.md §17.10`: "build a `usePermission`/`PermissionGate` now, or continue the
> reactive-403-only pattern. *Recommendation: build it now — Employee is the first module where whole
> sections... must be proactively absent, not just individually write-protected.*"

**Why it matters.** No frontend code today reads `UserProfile.permissions`, despite the API already
returning it (`00_EMPLOYEE_AUDIT.md §2.4`). The Directory spec and the 360° profile both require
"absent, not disabled" tab/column/action rendering (`docs/design/screens/01_Employee_List_Directory.md
§10`, `04_EMPLOYEE_UX_PLAN.md §2`) — impossible to implement correctly with only a reactive
403-then-toast pattern, since that pattern requires the user to attempt the action first.

**Downstream dependents.** Every future tabbed module on the same 360°-profile pattern (Attendance,
Leave, Payroll tabs) — building this primitive per-tab inside Employee's own slices would produce an
Employee-specific version other modules would have to copy or retrofit
(`00_EMPLOYEE_AUDIT.md §18`).

**Options.** (1) Build `usePermission`/`PermissionGate` once, ahead of or alongside E-09, as shared
frontend infrastructure; (2) continue the reactive-403-toast pattern per-tab.

**Recommendation.** Option 1, as audited.

**Consequences.** This is frontend infrastructure work with no Employee-specific business logic in it
— worth scoping as its own small task ahead of E-09 rather than embedding it silently inside E-09's
scope (mirrors the audit's own recommendation for `Tabs`/`Timeline`/`DataTable`, §18).

**Timing: NOW for the decision to build it** (locks E-09's frontend architecture); **DEFERRED for the
implementation** until immediately before E-09 starts, since nothing before E-09 needs it.

---

## Part B — Locked load-bearing decisions

Cross-checked against the audit; no contradiction was found for any of A–J below, so each is locked
as proposed. Where the audit adds a nuance beyond the brief's framing, it is noted.

### B1. Employee identity — DECIDED

Identity is permanent: `employee.id` (UUID PK) + `employee_code` (`UNIQUE (company_id,
employee_code)`) are never reissued, including across a rehire (`00_EMPLOYEE_AUDIT.md §9`). Matches
the brief's worked example exactly: `EMP-00125` → Former Employee → (4 years later) → Active Employee,
same code throughout. No document contradicts this; it is the direct consequence of the
identity/episode separation the schema already encodes.

### B2. Employment episodes — DECIDED

Rehire is never modeled by overwriting the original `employment` row. `employment` is `1:N` from
`employee`; a new spell is a new row (`is_rehire=true`, `previous_employment_id` → prior row's id),
never a mutation of the original's `joining_date`/`exit_date` (`00_EMPLOYEE_AUDIT.md §7-8`). The
original row is closed (`exit_date` set, `status → TERMINATED`/`EXITED`) and remains permanently
queryable.

### B3. Employee assignment — DECIDED

Department/designation/grade/branch/reporting-manager/shift are `employee_assignment` rows,
effective-dated, keyed on `employee_id` (not `employment_id`) — already enforced at the DB level by a
GiST exclusion constraint preventing two overlapping "current" rows
(`00_EMPLOYEE_AUDIT.md §3.3, §11`). Matches the brief's worked example (2027 vs. 2029 assignment)
exactly; the old row's `effective_to` is set, never its business columns.

### B4. Compensation — DECIDED

CTC/salary structure are `employee_compensation` rows, effective-dated, independently of assignment
changes — a raise can happen without a transfer and vice versa, because these are two separate child
tables, not one combined "current state" row (`00_EMPLOYEE_AUDIT.md §3.4, §11`). Same GiST exclusion
pattern as assignment.

### B5. Statutory data — DECIDED

Build `employee_statutory` as part of Employee's own migration set (A2 above), kept as its own table
— separate from `employee`'s identity columns — so its access can be permissioned independently
(`02_EMPLOYEE_DATA_MODEL.md §2` section F). The brief's phrasing ("separate sensitive statutory data
from the core Employee identity record") is already the audit's own design; no invented layer needed.

### B6. Banking data — DECIDED (architecture); permission code — REQUIRES PRODUCT DECISION (A9)

Build `employee_bank` now (A2), effective-dated, own table. The brief's instruction to require
"stricter permissions than ordinary employee profile information" is satisfied by locking a dedicated
`EMPLOYEE.VIEW_BANKING` code (A9's recommendation) rather than reusing `VIEW_COMPENSATION` — this is
this document's own addition to the audit's tentative position, flagged as such in A9.

### B7. Effective-dating — DECIDED

One shared pattern, implemented once as a service-layer helper
(`get_assignment_as_of(employee_id, date)`, `get_compensation_as_of(employee_id, date)`,
extendable to `get_statutory_as_of`/`get_bank_as_of`), not a generic framework
(`00_EMPLOYEE_AUDIT.md §11.3`, `02_EMPLOYEE_DATA_MODEL.md §1.3`). The write pattern (close current row's
`effective_to`, insert new row, same transaction) and read patterns (current / as-of-date / full
history) are fully specified in `02_EMPLOYEE_DATA_MODEL.md §1.2-1.3` and require no further design
work before E-04 starts — this is the one piece of this decision record that is already
fully-specified, not merely decided in principle. The brief's caution against "a giant generic
framework" is honored: no config-driven effective-dating engine, no polymorphic history table — just a
repeated, disciplined table shape (`effective_from`/`effective_to`/GiST exclusion) and a repeated
repository method shape, applied to each child table as it's built.

### B8. Shift overrides — DEFERRED

Confirmed by A3 above: ship `employee_assignment.shift_id` as a direct, nullable, per-employee value
in E-05; do not build the BR-14 cascading-default chain now or invent its resolution order. Recorded
as an explicit deferred decision (Part F), not a silent gap.

### B9. RBAC — DECIDED (catalogue shape); two code names — REQUIRES PRODUCT DECISION (A9)

Full 14-code catalogue (A4), plus the two additional view codes this document adds for statutory/
banking (A9). Checked against the brief's minimum-evaluate list:

| Brief's category | Catalogue code(s) |
|---|---|
| Employee view | `EMPLOYEE.VIEW`, `.VIEW_ALL` |
| Employee create/manage | `.CREATE`, `.UPDATE` |
| Employee lifecycle management | `.DEACTIVATE`, `.CONFIRM`, `.TRANSFER`, `.PROMOTE` |
| Employee sensitive data | `.UPDATE_SENSITIVE`, `.VIEW_PERSONAL_CONTACT` |
| Employee compensation | `.VIEW_COMPENSATION`, `.UPDATE_COMPENSATION` |
| Employee statutory data | `.VIEW_STATUTORY` *(new, A9)* / `.UPDATE_SENSITIVE` (write, reused) |
| Employee banking data | `.VIEW_BANKING` *(new, A9)* / `.UPDATE_SENSITIVE` (write, reused) |
| Employee documents | `.VIEW_DOCUMENTS`, `.UPLOAD_DOCUMENTS`, `.VERIFY_DOCUMENTS` |
| Employee onboarding | **no code** — onboarding workflow itself is out of V1 scope (B10 below); nothing to gate yet |

All nine of the brief's categories are covered except onboarding, which has no workflow to permission
yet — this is a scope fact, not a gap in the catalogue.

### B10. Onboarding / rehire compatibility — DECIDED (data model); DEFERRED (workflow)

The full flow (`Company → Offer → Candidate onboarding → Employee creation → Active employment → Exit
→ Former employee → Rehire → Same Employee identity`) is not blocked by anything in the locked model:
`employee.status` already reserves a `PRE_JOINING` state (`00_EMPLOYEE_AUDIT.md §12` item 2); the
rehire mechanism (B2) *is* the "years later" leg of this flow, not a separate mechanism a future ATS
would need to invent; Employee's creation path (manual wizard + bulk import,
`00_EMPLOYEE_AUDIT.md §12`) has no ATS coupling baked in, so a V2 "convert from candidate" wizard
variant can be added later without changing `employee`/`employment`/`employee_assignment`/
`employee_compensation`'s shape. No onboarding workflow, candidate/offer table, or ATS integration is
built now — confirmed out of scope by `VERSION_1_ROADMAP.md`, cited throughout
`00_EMPLOYEE_AUDIT.md §12`.

---

## Part C — Final conceptual data model

No "Person" layer — explicitly rejected by `docs/product/02_PRD.md §11` ("Not modelled. Avoid the
word.") and not reintroduced here.

```
Employee (permanent identity)
 ├── Employment[]            1:N, time-bounded spells (rehire = new row)
 ├── Employee Assignment[]   1:N, effective-dated, keyed on employee_id
 ├── Employee Compensation[] 1:N, effective-dated, keyed on employee_id
 ├── Employee Statutory[]    1:N, effective-dated, keyed on employee_id
 ├── Employee Bank[]         1:N, effective-dated, keyed on employee_id
 └── Employee Documents[]    1:N, plain collection (not effective-dated), keyed on employee_id
```

The load-bearing structural fact: **assignment, compensation, statutory, and bank all reference
`employee_id` directly, never `employment_id`.** This is what makes the rehire scenario correct
without any special-case code — these histories span the whole identity, continuous across an
employment gap in the data model (even though no rows exist *during* a gap, since there's nothing to
assign or pay).

### Employee

- **Purpose.** The permanent identity anchor for one person inside one company — exists once, never
  re-created.
- **Belongs here.** `employee_code`, `first_name`/`middle_name`/`last_name`, `display_name`,
  `date_of_birth`, `gender`, `blood_group`, `marital_status`, `nationality`, `photo_url`,
  `pan_number_enc`, `aadhaar_number_enc`, `uan_number`, `personal_email`, `personal_mobile`, `status`
  (identity-level lifecycle state), `custom_fields`, `user_id`.
- **Does NOT belong here.** Anything that changes with the job (department/designation/branch/
  manager/shift — Assignment), anything scoped to one continuous spell (joining/exit dates —
  Employment), pay (Compensation), PF/ESI/tax (Statutory), account details (Bank).
- **Relationship to Employee.** Is the Employee — the root of the aggregate.
- **Effective-dated?** No. Mutable, not versioned — a name correction overwrites in place (subject to
  FR-EMP-009's controlled/uncontrolled distinction governing *who* can make the correction, not
  *whether* history is kept).
- **Survives exit?** Yes — never deleted; only `status` transitions.
- **Survives rehire?** Yes, by definition — this is the row that persists across the entire scenario.

### Employment

- **Purpose.** One continuous spell at one legal entity. A person accumulates multiple rows over time
  — inter-entity transfer creates one, so does exit-then-rejoin.
- **Belongs here.** `legal_entity_id`, `employment_number`, `employment_type_id`, `joining_date`,
  `date_of_confirmation`, `probation_end_date`, `notice_period_days`, `date_of_resignation`,
  `last_working_day`, `exit_type`, `exit_reason_id`, `is_rehire`, `previous_employment_id`, `status`
  (spell-scoped — value set open, A1), `version` (recommended addition, A7).
- **Does NOT belong here.** Org placement (Assignment), pay (Compensation), PF/bank (Statutory/Bank).
- **Relationship to Employee.** 1:N.
- **Effective-dated?** No — a spell is not itself versioned; a *new spell* is a new row, not an
  update-with-history of an existing one.
- **Survives exit?** Yes — the row is closed (`exit_date`, `status`), never deleted.
- **Survives rehire?** The original row survives unchanged (closed, historical). Rehire creates a
  **new** Employment row; the two are linked via `previous_employment_id`, not merged.

### Employee Assignment

- **Purpose.** "Where in the org, under whom, on what shift" — the current position, versioned across
  a career, spanning employment gaps in the data model even though no row exists during an actual gap.
- **Belongs here.** `branch_id`, `department_id`, `designation_id`, `grade_id`,
  `reporting_manager_id`, `dotted_line_manager_id`, `cost_centre_id`, `work_location_type`,
  `shift_id`, `change_reason`, `change_type`, `effective_from`/`effective_to`.
- **Does NOT belong here.** Legal entity (Employment's own column — an inter-entity move is a new
  Employment row, not an Assignment change), pay (Compensation), PF/bank (Statutory/Bank).
- **Relationship to Employee.** 1:N, keyed on `employee_id` directly (not `employment_id`) — the
  load-bearing rehire-correctness detail.
- **Effective-dated?** Yes — GiST exclusion constraint already live, preventing overlapping "current"
  rows for one employee.
- **Survives exit?** The last row is closed (`effective_to` = exit date) and remains historically
  queryable.
- **Survives rehire?** Old rows remain, untouched. A **new** row opens at the new joining date with
  freshly-entered values — nothing carries forward automatically; department/designation/grade must be
  re-specified at rehire (consistent with FR-EMP-002's creation-time requirements).

### Employee Compensation

- **Purpose.** Pay, effective-dated independently of Assignment — a raise without a transfer, or a
  transfer without a raise, are both representable without coupling the two tables.
- **Belongs here.** `annual_ctc_minor`, `currency`, `salary_structure_id`, `monthly_gross`,
  `revision_type`, `revision_reason`, `approved_by`, `approval_request_id`, `is_arrears_processed`,
  `effective_from`/`effective_to`.
- **Does NOT belong here.** PF/ESI amounts (Statutory), bank account (Bank), org placement
  (Assignment).
- **Relationship to Employee.** 1:N, keyed on `employee_id` directly — same rehire-correctness
  reasoning as Assignment.
- **Effective-dated?** Yes — same GiST exclusion pattern.
- **Survives exit?** Last row closed at exit date; remains historically queryable (needed for
  full-and-final settlement and any later payroll audit).
- **Survives rehire?** Old rows remain; a new row opens at the rehire's new CTC. No CTC carries
  forward by default — it is set fresh, exactly like a new hire's first compensation row.

### Employee Statutory

- **Purpose.** PF/ESI/PT/LWF/tax-regime facts Payroll needs, held separately from `employee` so their
  access can be permissioned independently of ordinary profile data.
- **Belongs here.** `is_pf_applicable`, `pf_number`, `pf_wage_ceiling_opt_out`, `vpf_amount`/
  `vpf_percentage`, `is_esi_applicable`, `esi_ip_number`, `pt_state_code`, `is_lwf_applicable`,
  `tax_regime`, `is_director`, `is_international_worker`.
- **Does NOT belong here.** Bank account details (Bank), pay amount (Compensation).
- **Relationship to Employee.** 1:N, effective-dated, keyed on `employee_id`.
- **Effective-dated?** Yes (tax-regime switch, PF opt-in change over a career).
- **Survives exit?** Last row closed at exit; UAN/PF number history remains queryable (FR-EMP-015
  names "preserving... prior UAN" as a rehire expectation).
- **Survives rehire?** Old rows remain; a new row opens at rehire. UAN is expected to be the *same*
  number carried into the new row (statutory continuity), not reissued — other flags (PF/ESI
  applicability) are re-evaluated fresh at rejoin, since applicability can legitimately change.

### Employee Bank

- **Purpose.** Payout account for Payroll — RESTRICTED, with the strictest permission gating in the
  aggregate per the brief's explicit instruction (item F).
- **Belongs here.** `account_holder_name`, `account_number_enc`, `bank_name`, `ifsc`, `branch_name`,
  `payment_mode`, `is_primary`, `verification_status`, `penny_drop_reference`.
- **Does NOT belong here.** Nothing else — this table is a self-contained financial-instrument
  reference.
- **Relationship to Employee.** 1:N, effective-dated, keyed on `employee_id`.
- **Effective-dated?** Yes (an employee can change their salary account over a career).
- **Survives exit?** Last row remains — needed for full-and-final settlement payout even after exit.
- **Survives rehire?** Old rows remain; typically a new row is added at rehire (re-verification is a
  reasonable default even if the account is unchanged, since a multi-year gap is long enough that bank
  details plausibly changed).

### Employee Documents

- **Purpose.** Identity/education/experience/statutory document storage and verification — a single,
  ATS-independent table regardless of how a document arrived (manual upload today; a future candidate
  portal later, per the brief's onboarding-compatibility instruction).
- **Belongs here.** `document_type_id`, `document_number`, `issue_date`/`expiry_date`, `file_id`,
  `verification_status`/`verified_by`/`verified_at`/`rejection_reason`.
- **Does NOT belong here.** Nothing candidate/ATS-specific — no separate "candidate document" table,
  per `00_EMPLOYEE_AUDIT.md §12` item 4.
- **Relationship to Employee.** 1:N, plain collection, keyed on `employee_id`.
- **Effective-dated?** No — append/replace-on-reupload, not a time-versioned fact.
- **Survives exit?** Yes — retained for compliance/audit trail (e.g., exit clearance documents).
- **Survives rehire?** Yes — retained; new documents for the new spell are added alongside the old
  ones, never replacing them.

---

## Part D — Rehire scenario, walked through completely

**Given:**
- `EMP-00125` joins 2027-06-01.
- Over the spell: department, designation, grade, shift, and compensation each change at least once.
- Resigns 2030-09-30.
- Returns 2034-02-01.

**Records that exist at each point:**

| Date | Event | Records created / closed |
|---|---|---|
| 2027-06-01 | Joins | `employee` row created (`employee_code=EMP-00125`, `status=ACTIVE` or `PROBATION`). `employment #1` created (`joining_date=2027-06-01`, `legal_entity_id=X`, `status=ACTIVE`). `employee_assignment #1` created (`effective_from=2027-06-01`, `effective_to=NULL`, initial dept/designation/grade/shift). `employee_compensation #1` created (`effective_from=2027-06-01`, `effective_to=NULL`, initial CTC). |
| e.g. 2028-04-01 | Department change | `employee_assignment #1.effective_to = 2028-03-31` (closed). `employee_assignment #2` created (`effective_from=2028-04-01`, `effective_to=NULL`, new department; designation/grade/shift carried forward or changed together per the same insert). |
| e.g. 2029-01-01 | Compensation revision | `employee_compensation #1.effective_to = 2028-12-31` (closed). `employee_compensation #2` created (`effective_from=2029-01-01`, new CTC). **Independent of the assignment row above** — no assignment row is touched by a comp-only change, and vice versa. |
| e.g. 2029-07-01 | Designation/grade/shift change (promotion) | `employee_assignment #2.effective_to = 2029-06-30` (closed). `employee_assignment #3` created (`effective_from=2029-07-01`, `effective_to=NULL`, new designation/grade/shift). |
| 2030-09-30 | Resigns | `employment #1.exit_date = 2030-09-30`, `status → TERMINATED`/`EXITED`. `employee_assignment #3.effective_to = 2030-09-30` (closed — no open assignment row remains). `employee_compensation #2.effective_to = 2030-09-30` (closed — no open compensation row remains). `employee.status → EXITED` (or equivalent — exact value from FR-EMP-014's full enumeration, A1). |
| 2030-10-01 → 2034-01-31 | Gap | No `employee_assignment`, no `employee_compensation`, no open `employment` row. `employee` row persists, unchanged identity. Nothing to assign or pay, so nothing exists — this is expected, not a data gap to "fill." |
| 2034-02-01 | Rejoins | **Same `employee` row reused** (`employee_code` still `EMP-00125`, unchanged). `employment #2` created (`joining_date=2034-02-01`, `is_rehire=true`, `previous_employment_id = employment #1.id`, `status=ACTIVE`). `employee_assignment #4` created (`effective_from=2034-02-01`, `effective_to=NULL`, freshly-entered department/designation/grade/shift — nothing auto-carried from `#3`). `employee_compensation #3` created (`effective_from=2034-02-01`, freshly-entered CTC). `employee.status → ACTIVE`. |

**What this makes obvious:** at every point from 2027 through 2038 and beyond, `EMP-00125` is one
`employee` row. The five-year gap produces zero rows in the effective-dated child tables (nothing to
assign/pay during a gap) and exactly one closed `employment` row plus one new one — never a second
`employee` row, never a re-keyed identity. Querying "full assignment history for `EMP-00125`" returns
four rows spanning 2027–2030 and 2034–onward, with a visible, self-explanatory gap in between — not an
error, not a stitched-together illusion of continuity.

---

## Part E — Attendance readiness

**Question Attendance needs answered:** "Which employee was assigned to which shift, branch,
department, grade on a given date?" (brief's example: `2029-08-15 → EMP-00125 → Branch A / Department
B / Grade G2 / Shift Night-01`.)

**Architectural verification.** `get_assignment_as_of(employee_id, date)` (locked in B7) resolves this
directly: `WHERE employee_id = :id AND effective_from <= :date AND (effective_to IS NULL OR
effective_to >= :date)`, guaranteed to return at most one row by the GiST exclusion constraint. Against
the Part D timeline, a query for `2029-08-15` returns `employee_assignment #3` (post-promotion,
effective 2029-07-01 onward) — correct, unambiguous, and requires no special-case logic for the fact
that a rehire happens later in the same employee's history.

**What is NOT yet ready, at the column level (not the architecture level):**
- `shift_id` does not exist on the live `employee_assignment` table today (`00_EMPLOYEE_AUDIT.md §3.3`)
  — ships in E-05. Until then, the *pattern* is verified but the *column* Attendance needs is absent.
- `employment.status`/`employee.status` value sets are unresolved (A1) — Attendance's status-resolution
  precedence reads these directly and cannot be finalized until the enumerations exist.
- The BR-14 shift-override chain (A3/B8) is deferred — Attendance must be built to treat
  `shift_id IS NULL` as "no shift resolves," not assume a cascading default always exists.

**Verdict.** The *architecture* is Attendance-ready (as-of-date resolution, stable identity across
rejoin, per Part D). The *schema* is not yet — E-01 through E-05 must ship first, with A1's status
value sets resolved before E-03, exactly as `01_EMPLOYEE_MODULE_PLAN.md §3` already sequences.

---

## Part F — Payroll readiness

**Questions Payroll needs answered**, checked against the locked model:

| Question | Answered by | Ready? |
|---|---|---|
| Who is the employee? | `employee` | Yes, architecturally — table exists, needs field completion (E-01/E-02) |
| Which employment episode is active? | `employment.status`, `joining_date`/`exit_date` | Architecture yes; value-set decision open (A1) |
| What was the employee's bank account? | `employee_bank` as-of pay period | **No** — table doesn't exist yet; must ship in E-08 (B6) |
| What statutory information applies? | `employee_statutory` as-of pay period | **No** — table doesn't exist yet; must ship in E-07 (B5) |
| What compensation was effective during period X? | `employee_compensation` as-of pay period | Yes — table live, effective-dating pattern already enforced (B4/B7) |
| Which organisational assignment applied during that period? | `employee_assignment` as-of pay period | Yes — same as Attendance's answer (Part E), minus the `shift_id`-specific gap which doesn't block Payroll |

**Missing foundations, explicitly.** `employee_statutory` and `employee_bank` are the two hard blockers
— if E-07/E-08 are deferred past Employee's own build (contrary to A2's lock), Payroll cannot be built
correctly when its turn comes. This is the single highest-leverage "don't defer" decision in this
entire record.

**Verdict.** Payroll readiness = E-01 + E-03 + E-06 + E-07 + E-08, with A1's status/rejoin decisions
resolved before E-03. Not yet ready; on a clear path once those slices ship in sequence.

---

## Part G — Deferred decisions

| # | Decision | Deferred to |
|---|---|---|
| 1 | BR-14 / FR-EMP-018 shift-and-notice-period override-chain mechanism (A3/B8) | A separate cross-module decision involving Employee, Shift Rules, and Attendance once all three can be evaluated together |
| 2 | FR-ORG-014 active-employee-count retrofit into Branch/Department/Designation/Grade (A5) | Small standalone follow-up PR against `organisation/`, filed at E-01's close |
| 3 | `sensitive_access_log` exact schema (A9) | E-10's own design step (the decision to build it is not deferred — only its shape is) |
| 4 | Frontend `usePermission`/`PermissionGate` implementation (A10) | Immediately before E-09 starts (the decision to build it is not deferred — only the build timing is) |
| 5 | Rejoin-linking wizard UX (PAN/Aadhaar/email match during Add-employee step 1) | Buildable only after A1's rejoin data-model decision is fully confirmed by product, including the `employment.status` value set |
| 6 | Onboarding/ATS candidate-conversion workflow (B10) | V2, per `VERSION_1_ROADMAP.md` — data model already accommodates it, no rework anticipated |
| 7 | Payroll-lock-period backdating enforcement (FR-EMP-004) | Cannot be implemented until Payroll's own lock-period check exists; Employee's UI should not attempt client-side enforcement until then |
| 8 | Approval-routing gate on compensation/transfer workflows (`approval_request_id`) | Store the field now (E-04/E-06); enforce once the approval-routing engine ships, sequenced after Employee per the roadmap |

---

## Part H — Risks

Carried forward from `00_EMPLOYEE_AUDIT.md §18`, re-confirmed against this decision record:

1. **Effective-dating has no precedent in this codebase.** E-04 is the first slice that writes to an
   effective-dated table in application code — B7 specifies the pattern fully, but implementation
   still carries first-of-its-kind review risk.
2. **Two decisions gate E-03 cleanly starting**: A1's rejoin mechanics and the `employment.status`
   value set. Both are marked REQUIRES PRODUCT DECISION above for their literal values (the
   architecture is decided; the enum strings are not) — starting E-03 without them risks a second
   migration shortly after the first.
3. **Payroll-blocking gap** if E-07/E-08 (`employee_statutory`/`employee_bank`) are deferred past
   Employee's own slices — the single most expensive mistake available in this sequence (Part F).
4. **New RESTRICTED-tier privacy surface.** Employee is the first module handling CTC/bank/PAN/Aadhaar
   and the first needing proactive UI gating — a mistake in the Directory's field-visibility matrix or
   the Compensation/Statutory/Bank permission gates (A9) is a privacy leak, not a cosmetic bug.
5. **`EMPLOYEE_SEATS` and the number-series allocator are both unbuilt infrastructure** E-01 depends
   on — treat as new-infrastructure build, not "just add a column."
6. **BR-14 temptation.** Resist building the override chain "while already in the assignment slice" —
   it is a separate, later, cross-module decision (Part G item 1).
7. **E-10 is the easiest slice to cut** under schedule pressure because it ships no visible feature —
   given Employee's central-dependency role, and given this record's own addition of two new RBAC
   codes and `sensitive_access_log` to E-10's scope, treat it as non-optional.
8. **Scope creep into Attendance/Leave/Payroll/Employee Assignment implementation.** This record and
   its companions define *contracts*; building the consumer modules themselves is out of scope here.

---

## Part I — Final approved conceptual model

```
                         ┌────────────────────┐
                         │      Employee       │  permanent identity
                         │  employee_code,     │  never re-created, never
                         │  name, DOB, gender,  │  re-keyed on rehire
                         │  PAN/Aadhaar (enc),  │
                         │  status, custom      │
                         └─────────┬────────────┘
                                   │ employee_id (1:N, every child below)
        ┌──────────────┬──────────┼───────────┬──────────────┬──────────────┐
        ▼              ▼          ▼           ▼              ▼              ▼
  ┌───────────┐  ┌───────────┐ ┌────────┐ ┌──────────┐ ┌──────────┐  ┌───────────┐
  │ Employment │  │ Assignment │ │  Comp  │ │Statutory │ │   Bank   │  │ Documents │
  │  (spells)  │  │(eff-dated) │ │(eff-   │ │(eff-     │ │(eff-     │  │ (plain    │
  │  is_rehire,│  │ branch,    │ │ dated) │ │ dated)   │ │ dated)   │  │ collection│
  │  prev_id,  │  │ dept,      │ │ CTC,   │ │ PF/ESI/  │ │ account, │  │ )         │
  │  legal_    │  │ designat., │ │ salary │ │ PT/tax   │ │ IFSC     │  │           │
  │  entity_id │  │ grade,     │ │ struct │ │ regime   │ │          │  │           │
  │            │  │ manager,   │ │        │ │          │ │          │  │           │
  │            │  │ shift      │ │        │ │          │ │          │  │           │
  └───────────┘  └───────────┘ └────────┘ └──────────┘ └──────────┘  └───────────┘
   1 row per          effective-dated, GiST no-overlap enforced,        append/
   continuous         keyed on employee_id (NOT employment_id) —        replace,
   spell; new         this is what makes rehire correct without         not
   spell = new        special-case code                                 versioned
   row, never a
   mutation
```

Rehire produces: same `Employee` row · one closed `Employment` row + one new `Employment` row linked
by `previous_employment_id` · a visible gap with zero Assignment/Compensation/Statutory/Bank rows ·
full historical continuity on both sides of the gap · `Documents` accumulating across the whole
lifetime, exit and rejoin included.

