# Employee Statutory (E-07) — Implementation Plan

Companion to `00_EMPLOYEE_AUDIT.md`, `02_EMPLOYEE_DATA_MODEL.md`, `03_EMPLOYEE_API_PLAN.md`,
`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md`, `01_EMPLOYEE_MODULE_PLAN.md`, and the E-06 Compensation
closeout set (`17`–`20`). **This document is investigation and planning only — no application
code, migrations, tests, or frontend code were written or modified to produce it.** It is written
so a future implementation task can execute E-07 without re-auditing the project.

---

## 1. Executive Summary

E-07 adds `employee_statutory` — the per-employee PF/ESI/PT/LWF/tax-regime profile Payroll will
read once it exists. The table does **not** exist in the live schema or in any migration; it is a
fully greenfield slice at the code level (confirmed by direct DB inspection and a repo-wide grep,
§4). The architecture is already locked in `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part B5/B7/Part
C: a new table, keyed on `employee_id` (not `employment_id`), effective-dated with the same GiST
exclusion pattern already live for `employee_assignment`/`employee_compensation`. E-07's nearest
sibling and pattern template is **E-06 Compensation**, the most recently completed slice — same
effective-dating shape, same insert-only write pattern, same whole-sub-resource permission gating,
same audit convention.

Two real gaps block a clean, silent implementation and must be resolved (with safe, documented
defaults recommended, not invented facts): (1) no permission code in the locked 14-code
`EMPLOYEE.*` catalogue names statutory data specifically — a dedicated `EMPLOYEE.VIEW_STATUTORY`
is recommended by the architecture-decisions doc itself but explicitly flagged as unconfirmed
(§14); (2) two source documents disagree on whether `uan` is a column on `employee_statutory` or
on `employee` — resolved here in favor of the live schema, which already has
`employee.uan_number` (§6, §10). Everything else needed to build E-07 — ownership, rehire
semantics, effective-dating mechanics, the Employee/Legal-Entity boundary, the Payroll boundary,
and the E-10 boundary — is already decided in the source documents and is not reopened here.

**Final readiness: READY TO IMPLEMENT, with flagged assumptions** (§27). No genuine architectural
blocker exists. The open items are naming and business-rule details with either a documented
recommended default or a clear, narrow product question — the same shape of gap E-03 (`.TERMINATE`)
and E-06 (view-permission wiring) each resolved by proceeding with a flagged assumption rather than
stalling, which is this codebase's own established discipline (`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md`
A9's own words: "a naming choice, not an architectural one — safe to finalize immediately... not a
blocker").

---

## 2. Current Implementation State

Completed Employee slices per the user's brief and confirmed against migration history: E-01
(foundation), E-03 (employment lifecycle), E-04 (assignment), E-05 (shift assignment), E-06
(compensation). **E-02 (identity/profile completion) has not shipped** — no `06`-series report
exists for it, no migration adds the E-02-scoped `employee_address`/`employee_emergency_contact`
tables, and `pan_number_enc`/`aadhaar_number_enc`/`uan_number` on `employee` have columns but no
write path (`apps/api/src/hrms/modules/employee/models.py` docstring, confirmed live). This matters
for E-07's boundary: E-02, not E-07, owns wiring a write path for PAN/Aadhaar/UAN on `employee`
(§9, §13).

Live migration head: `20260814120000_employee_compensation.py` (Alembic `alembic_version` =
`20260814120000`, confirmed by direct `psql` inspection). No `employee_statutory` migration exists.
A grep for "statutory" across `apps/api/src/hrms` and `apps/api/alembic` returns only: a comment in
`permissions.py` citing `.VIEW_STATUTORY`/`.VIEW_BANKING` as an *illustrative* example of the
unresolved-permission-naming pattern (not a real, wired code), a comment noting this task's scope
exclusion, and the `LegalEntity` model docstring ("owns statutory identifiers (PF/ESI/TAN/PAN/GST)")
— confirming zero prior code, model, or test touches `employee_statutory` today.

---

## 3. Authoritative Sources

| Document | What it authoritatively defines for E-07 |
|---|---|
| `docs/modules/employee/00_EMPLOYEE_AUDIT.md` | Data classification (§10), effective-dating strategy (§11), permission catalogue (§13.1), audit conventions (§13.4), the Payroll-blocking dependency (§10 row 3) |
| `docs/modules/employee/02_EMPLOYEE_DATA_MODEL.md` | Field inventory (§2 section F), the recommended `CREATE TABLE employee_statutory` DDL (§3), the view-permission gap (§2 section F) |
| `docs/modules/employee/03_EMPLOYEE_API_PLAN.md` | Proposed endpoint shape and the PATCH-vs-insert-only verb tension (§2.4) |
| `docs/modules/employee/05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` | Locked decisions: A2 (build now), A9 (permission gap + `sensitive_access_log` timing), B5 (statutory — DECIDED), B7 (effective-dating), Part C (conceptual model, rehire behavior), Part F (Payroll readiness), Part G (deferred decisions) |
| `docs/modules/employee/01_EMPLOYEE_MODULE_PLAN.md` | E-07's own slice definition, dependencies (E-01, E-03), and named risk (view-permission gap must be resolved before shipping) |
| `docs/modules/employee/17-20_EMPLOYEE_COMPENSATION_*.md` | The concrete pattern template — E-06 is E-07's nearest-shipped sibling |
| `docs/modules/legal-entity/01_Legal_Entity_Module.md`, live `legal_entity` schema | Employer-level statutory registration data, distinguished from employee-level statutory data (§9) |
| `docs/product/08_Database_Architecture.md`, `docs/database/Database_Architecture.md` | Global conventions: RLS, effective-dating, audit columns, encryption-at-rest, soft delete |
| `docs/product/19_RBAC_and_Permission_Matrix.md` | The locked `EMPLOYEE.*` catalogue (§3.1) and the field-classification tiers (§6) |
| `docs/product/17_SRS_Phase1_Core_Modules.md` | FR-PAY-006 (employee statutory profile fields), FR-EMP-015 (rehire/UAN), FR-AUD-003 (sensitive access log), FR-RBAC-004 |
| `docs/product/23_Non_Functional_Requirements_and_Compliance.md` | DPDP Act 2023 framing, statutory retention periods (PF 7 years post-exit, ESI 5 years) |
| `docs/product/26_Risk_Register_Open_Questions_and_Change_Control.md` | R-01, R-16 (statutory-rate risk), Q1/A1 (India-only payroll assumption, unconfirmed) |

---

## 4. Existing Database State

Confirmed by direct `psql` inspection against the local dev database
(`postgresql://hrms:hrms_dev_password@localhost:5433/hrms_dev`):

- **`employee_statutory` does not exist.** Full `\dt` listing (30 tables) contains no such table.
- No separate history/versioning table exists for any effective-dated Employee entity —
  `employee_compensation` and `employee_assignment` each hold their own history as rows with a
  closed (non-null) `effective_to`; there is no `*_history` table pattern to replicate.
- `alembic_version` = `20260814120000`, matching the E-06 compensation migration, the current head.
- `employee.uan_number VARCHAR(20)`, `employee.pan_number_enc TEXT`, `employee.aadhaar_number_enc
  TEXT` **already exist as live columns** on `employee` (added in the E-01 foundation migration),
  with no write path in application code yet (§2).
- `legal_entity` already has `pan`, `tan`, `cin`, `gstin`, `pf_code`, `esi_code`, `lwf_reg` — live,
  implemented columns (§9).
- The sibling pattern (`employee_compensation`) is: `id, company_id, employee_id, ...business
  columns..., effective_from DATE NOT NULL, effective_to DATE, created_at, updated_at, deleted_at,
  version INTEGER DEFAULT 1`, a GiST exclusion constraint
  `EXCLUDE USING gist (employee_id WITH =, daterange(effective_from, COALESCE(effective_to,
  'infinity'::date), '[]') WITH &&)`, an FK `employee_id → employee(id) ON DELETE RESTRICT`, and a
  single RLS policy `tenant_isolation USING (company_id = current_setting('app.company_id',
  true)::uuid)` under `FORCE ROW LEVEL SECURITY`. This is the exact shape `employee_statutory`
  should copy.

---

## 5. Target Data Model

Per `02_EMPLOYEE_DATA_MODEL.md §3`'s recommended DDL (the concrete, reviewed proposal — not the
field-inventory table in §2, which disagrees with it on one column; resolved in §6 below):

```sql
CREATE TABLE employee_statutory (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id UUID NOT NULL REFERENCES company(id),
  employee_id UUID NOT NULL REFERENCES employee(id),
  effective_from DATE NOT NULL,
  effective_to DATE,
  is_pf_applicable BOOLEAN NOT NULL DEFAULT false,
  pf_number VARCHAR(30),
  pf_wage_ceiling_opt_out BOOLEAN NOT NULL DEFAULT false,
  vpf_amount BIGINT,
  vpf_percentage NUMERIC(9,4),
  is_esi_applicable BOOLEAN NOT NULL DEFAULT false,
  esi_ip_number VARCHAR(30),
  pt_state_code VARCHAR(10),
  is_lwf_applicable BOOLEAN NOT NULL DEFAULT false,
  tax_regime VARCHAR(10),
  is_director BOOLEAN NOT NULL DEFAULT false,
  is_international_worker BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL,
  deleted_at TIMESTAMPTZ,
  version INTEGER NOT NULL DEFAULT 1
);

ALTER TABLE employee_statutory
  ADD CONSTRAINT employee_statutory_no_overlap
  EXCLUDE USING gist (
    employee_id WITH =,
    daterange(effective_from, COALESCE(effective_to, 'infinity'::date), '[]') WITH &&
  );

ALTER TABLE employee_statutory ENABLE ROW LEVEL SECURITY;
ALTER TABLE employee_statutory FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON employee_statutory
  USING (company_id = current_setting('app.company_id', true)::uuid);
```

Add, matching `employee_compensation`'s existing index shape (`employee_compensation_company_id_idx`,
`employee_compensation_employee_id_effective_from_idx`):

```sql
CREATE INDEX employee_statutory_company_id_idx ON employee_statutory (company_id);
CREATE INDEX employee_statutory_employee_id_effective_from_idx
  ON employee_statutory (employee_id, effective_from);
```

No changes are required to `employee`, `employment`, `legal_entity`, or `employee_compensation`.

---

## 6. Field-by-Field Analysis

Legend: Class = sensitivity tier per `docs/product/19_RBAC_and_Permission_Matrix.md §6`; "(inferred)"
= not stated explicitly for this exact field in the RBAC matrix's own RESTRICTED example list, but
classified by direct analogy (see §11).

| Field | Table | Storage | Class | List response | Detail response | Masking |
|---|---|---|---|---|---|---|
| `is_pf_applicable` | employee_statutory | plain boolean | RESTRICTED (inferred) | absent unless `.VIEW_STATUTORY` | included | none documented |
| `pf_number` | employee_statutory | plain string | RESTRICTED (inferred) | absent unless `.VIEW_STATUTORY` | included | none documented — flagged ambiguity, §11 |
| `pf_wage_ceiling_opt_out` | employee_statutory | plain boolean | RESTRICTED (inferred) | absent unless `.VIEW_STATUTORY` | included | none |
| `vpf_amount` / `vpf_percentage` | employee_statutory | plain numeric | RESTRICTED (inferred) | absent unless `.VIEW_STATUTORY` | included | none |
| `is_esi_applicable` | employee_statutory | plain boolean | RESTRICTED (inferred) | absent unless `.VIEW_STATUTORY` | included | none |
| `esi_ip_number` | employee_statutory | plain string | RESTRICTED (inferred) | absent unless `.VIEW_STATUTORY` | included | none documented — flagged ambiguity, §11 |
| `pt_state_code` | employee_statutory | plain string | RESTRICTED (inferred) | absent unless `.VIEW_STATUTORY` | included | none |
| `is_lwf_applicable` | employee_statutory | plain boolean | RESTRICTED (inferred) | absent unless `.VIEW_STATUTORY` | included | none |
| `tax_regime` | employee_statutory | plain string (OLD/NEW) | RESTRICTED (Payroll-facing per §2 table F) | absent unless `.VIEW_STATUTORY` | included | none |
| `is_director` / `is_international_worker` | employee_statutory | plain boolean | RESTRICTED (inferred) | absent unless `.VIEW_STATUTORY` | included | none |
| `uan_number` | **`employee`, not `employee_statutory`** | plain string (encryption not yet implemented despite `_enc`-style peers; see §11) | RESTRICTED (inferred, `02_EMPLOYEE_DATA_MODEL.md §2` row A) | out of E-07 scope (E-02 owns `employee`'s write path) | out of E-07 scope | "masked in API" required per Doc 08 §5.1, but **no format specified anywhere** — flagged product decision, out of E-07's scope to resolve since E-07 does not touch this column |

**Storage requirement**: plain columns, no encryption. Unlike `pan_number_enc`/`aadhaar_number_enc`
(named `_enc` and documented "encrypted at column level"), no source document requires
column-level encryption for `pf_number`, `esi_ip_number`, `pt_state_code`, or any other
`employee_statutory` field — the DDL in §5 (the reviewed, concrete proposal) declares them as plain
`VARCHAR`/`BOOLEAN`/`NUMERIC`, not `TEXT ... _enc`. Do not add encryption to these columns without a
documented requirement (§25 risk, §24 engineering decision).

**Read visibility / write permission**: see §14 (Permission Model).

**List vs. detail response**: no document distinguishes list-view fields from detail-view fields for
statutory data (unlike, say, salary-in-list-view being "bucketed" per `19_RBAC_and_Permission_Matrix.md
§6`). Recommended default, by direct analogy to Compensation's shipped behavior (§13 of
`17_EMPLOYEE_COMPENSATION_IMPLEMENTATION_PLAN.md`): the entire `employee_statutory` sub-resource is
either wholly present (full field set) or wholly absent (403 or omitted from an aggregate response),
gated by `EMPLOYEE.VIEW_STATUTORY` — not masked per field.

---

## 7. Employee Relationship

**Decided, not reopened.** `employee_statutory` is keyed on `employee_id` directly, never
`employment_id` — the same load-bearing structural fact already established for
`employee_assignment` and `employee_compensation` (`00_EMPLOYEE_AUDIT.md §6`: "This is the detail
that makes rehire correct by construction... assignment and compensation history spans the
identity, not a single employment spell"; `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part C, "Employee
Statutory": "1:N, effective-dated, keyed on `employee_id`"). `employment_id` and `legal_entity_id`
are **not** foreign keys on `employee_statutory` — legal-entity context for statutory purposes is
resolved indirectly via the employee's currently-active `employment.legal_entity_id`, not stored
redundantly on the statutory row (no document states otherwise; storing it directly would be
inventing a field, so it is not proposed here).

---

## 8. Employment/Rehire Semantics

Per `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part C ("Employee Statutory") and Part D (rehire
walkthrough), and `02_EMPLOYEE_DATA_MODEL.md §1.2`:

- **Survives exit?** Yes. The last `employee_statutory` row is closed (`effective_to` set) at exit;
  it remains permanently queryable, never deleted or merged.
- **Survives rehire?** Old rows remain untouched. A **new** `employee_statutory` row opens at the
  rehire's new `effective_from` (the new employment's joining date), against the **same**
  `employee_id` — mechanically the same "insert a new row" operation as any other statutory change,
  no special-case rehire code required (mirroring Compensation's own rehire behavior,
  `18_EMPLOYEE_COMPENSATION_MODULE.md §5`).
- **UAN continuity is automatic, not a carry-forward rule E-07 must implement.** The architecture
  doc's Part C states "UAN is expected to be the *same* number carried into the new row (statutory
  continuity), not reissued" — but per §6/§10 of this document, UAN is **not** a column on
  `employee_statutory` at all; it lives on `employee.uan_number`, the permanent identity row that is
  never re-created on rehire (`00_EMPLOYEE_AUDIT.md §7`: "one row per person per company, created
  once, never re-created"). Once this placement discrepancy (§10) is resolved in favor of the live
  schema, UAN's rehire continuity is a **structural consequence of the identity model**, requiring
  zero rehire-specific logic in E-07 — it simply is not part of what E-07's rehire path writes.
- **PF/ESI applicability flags do not carry forward.** Part C is explicit: "other flags (PF/ESI
  applicability) are re-evaluated fresh at rejoin, since applicability can legitimately change" — a
  rehire's first statutory row should be entered fresh, the same way Compensation's first row on
  rehire has no CTC carry-forward (`18_EMPLOYEE_COMPENSATION_MODULE.md §5`).
- **`pf_number` carry-forward on rehire is an unresolved product question**, not decided by any
  source document (§22 item 4). Unlike UAN (universal, government-issued, tied to the person) a
  `pf_number` is historically an establishment-specific PF account number; whether the same
  `pf_number` should be pre-filled/reused when an employee rejoins the **same** legal entity is not
  stated anywhere. Do not invent a default; the write path should simply accept whatever the caller
  submits for a new row, exactly as any other statutory field, until product clarifies whether the
  UI/API should suggest a carried-forward value.

---

## 9. Legal Entity Relationship

`legal_entity` already stores employer/establishment-level statutory registration identifiers, live
and implemented (`docs/modules/legal-entity/01_Legal_Entity_Module.md §2`, confirmed against the
live DB schema): `pan`, `tan`, `cin`, `gstin`, `pf_code`, `esi_code`, `lwf_reg`,
`signatory_name`/`signatory_designation`/`signature_image_url`. These are the **employer's own**
registration numbers — one PF establishment code, one ESI code, one TAN per legal entity — purpose
statement: "A Legal Entity is the legally registered company that employs a workforce and is
responsible for payroll, statutory compliance, and employment contracts (PF/ESI/TAN/PAN/GST
registrations)" (`01_Legal_Entity_Module.md §1`).

`employee_statutory` is a categorically different layer: **individual employee enrollment/
identification data** — this employee's own `pf_number` (their account under the employer's PF
establishment), their own `esi_ip_number`, their elected `tax_regime`, their applicability flags.
There is **no field-level overlap or duplication risk** between the two tables — they describe
different entities (the employer vs. the individual). E-07 should not re-store any `legal_entity`
field, and no source document proposes doing so.

**Unaddressed by any document**: whether `employee_statutory.is_esi_applicable = true` should be
validated against the employee's active `employment.legal_entity_id` actually having a non-null
`legal_entity.esi_code` (i.e., can't mark ESI-applicable for an employee at a legal entity with no
ESI registration). This is a plausible business rule but is not stated anywhere — flagged as a
possible validation gap (§22), not invented as a hard constraint here.

---

## 10. Effective-Dating Analysis

**Decided.** Same pattern as Assignment/Compensation, fully specified and requiring no new design
(`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` B7: "fully-specified, not merely decided in principle").

- **Write pattern**: close the current row (`effective_to = new.effective_from - 1 day`, the one
  allowed edit, touching only `effective_to`) and insert a new row, same transaction
  (`02_EMPLOYEE_DATA_MODEL.md §1.2`).
- **Current**: `WHERE employee_id = :id AND effective_to IS NULL AND deleted_at IS NULL` (at most
  one row, enforced by the GiST exclusion constraint).
- **As of a date**: `WHERE employee_id = :id AND effective_from <= :date AND (effective_to IS NULL
  OR effective_to >= :date)`.
- **Full history**: `WHERE employee_id = :id ORDER BY effective_from`.
- **Multiple history records required?** Yes — every prior period remains a permanent row; there is
  no separate history table (§4).

**Resolved discrepancy — `uan` column placement.** Two source documents disagree:
- `02_EMPLOYEE_DATA_MODEL.md §2` section F (the field-inventory table) lists `uan` as a field *of*
  `employee_statutory`.
- `docs/product/08_Database_Architecture.md §5.5` (per cross-cutting research) also lists `uan`
  under `employee_statutory` in its field summary.
- But `02_EMPLOYEE_DATA_MODEL.md §3` — the same document's own **concrete, reviewed DDL** — omits
  `uan` from `employee_statutory` entirely and instead adds `uan_number VARCHAR(20)` to `employee`
  via `ALTER TABLE employee ADD COLUMN IF NOT EXISTS uan_number VARCHAR(20)`.
- The **live database already has `employee.uan_number`** (added in the E-01 migration) and has no
  `employee_statutory` table at all.

**Resolution for this plan**: follow the live schema and the concrete DDL (§3), not the narrative
field-inventory tables. `employee_statutory` should **not** have a `uan` column; UAN remains solely
on `employee.uan_number`. This is the only way to avoid a duplicate, driftable copy of the same
identifier across two tables, and it is consistent with UAN being a person-level (not
employment-period-level) identifier that does not need effective-dating — it does not change per
statutory period the way `tax_regime` or `is_pf_applicable` do. Flagged here explicitly rather than
silently picked, per this task's own instructions.

**"Current" statutory data** means the single row per employee with `effective_to IS NULL` — the
statutory facts (PF/ESI applicability, tax regime, PT state) in force as of today. This is
identical in shape to "current compensation" and "current assignment."

---

## 11. Sensitive Data Classification

No source document places PF number, UAN, ESI IP number, PT state code, or tax regime explicitly in
the RBAC matrix's own RESTRICTED example list (`docs/product/19_RBAC_and_Permission_Matrix.md §6`
names: "CTC, salary components, bank account, PAN, Aadhaar, tax declarations, disciplinary records,
PIP, background-check results, medical, POSH complaints"). The classification for
`employee_statutory`'s fields is therefore **inferred by strong analogy**, not directly documented:

1. `00_EMPLOYEE_AUDIT.md §10` row 3 groups "PAN, Aadhaar, UAN, PF, ESI, bank" together under one
   category, stating "RESTRICTED classification (§13.3)" for the whole group.
2. `02_EMPLOYEE_DATA_MODEL.md §2` section F classifies every `employee_statutory` field as
   "RESTRICTED (inferred)" — the document's own words, explicitly flagged as inferred, not sourced.
3. `docs/product/17_SRS_Phase1_Core_Modules.md` FR-RBAC-004 names only "Salary, bank account, PAN,
   Aadhaar, medical, disciplinary and background-check data" as RESTRICTED by default — PF/ESI/UAN
   are not literally named.
4. FR-AUD-003 (sensitive-access logging) similarly names only "salary, bank, PAN, Aadhaar and
   medical" fields, not PF/UAN/ESI IP number by name.

**This document's position**: treat every `employee_statutory` field as RESTRICTED by the same
analogy §00/§02 already draw, since these are government-issued financial/tax identifiers of the
same character as PAN/Aadhaar, and the risk of under-classifying is materially worse than the cost
of over-gating. This is an engineering judgment call consistent with the two documents that already
lean this way, not a new invention.

**Masking**: unlike PAN (`ABCDE****F`), Aadhaar (`XXXX XXXX 1234`), and bank account (`******7890`)
— each with an explicit masking format documented in `docs/product/19_RBAC_and_Permission_Matrix.md
§6` — **no masking format is documented anywhere for `pf_number`, `esi_ip_number`, `pt_state_code`,
or `tax_regime`.** This mirrors CTC, which is RESTRICTED but is **not** masked — it is
permission-gated at the whole-resource level instead (`19_EMPLOYEE_COMPENSATION_API.md`: "the
entire sub-resource is absent... not a response with masked/degraded fields"). Recommended default
for E-07 (engineering decision, §24): follow the CTC/Compensation precedent — gate the entire
`GET .../statutory` response behind `EMPLOYEE.VIEW_STATUTORY`, do not attempt per-field masking of
`pf_number`/`esi_ip_number`, since no format is specified and inventing one is out of scope. If
product later specifies a masking format, it can be added without a schema change.

**List responses**: statutory data does not belong in any list/directory response — it is
sub-resource data behind its own dedicated endpoint, exactly like Compensation, never surfaced in
`GET /v1/employees` or `GET /v1/employees/directory`.

**Detail responses**: `GET /v1/employees/{id}` (the identity/summary detail endpoint) should **not**
inline statutory data either — it belongs only under its own `GET
/v1/employees/{id}/statutory[...]` sub-resource route, matching Compensation's separation.

---

## 12. E-07 vs. E-10 Boundary

`sensitive_access_log` (read-path logging of RESTRICTED-field access, FR-AUD-003) is **locked to
E-10**, already decided and not reopened by E-07 (`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` A9:
"Build now, scoped to E-10 (not E-01)... The decision to build `sensitive_access_log` at all is
**DECIDED** (build in E-10); its schema is **DEFERRED** to E-10's own design").

**What E-07 implements now**: the `employee_statutory` table, model, repository (current/as-of/
history/close), service (validation + rehire-fresh-row + tax-regime-switch rule), router (view +
create endpoints), a mutation-only audit event (`STATUTORY_REVISED`, via the existing
`AuditService.record`, following `COMPENSATION_REVISED`'s exact shape), and permission gating via a
view code (`EMPLOYEE.VIEW_STATUTORY`, new) and the reused write code (`EMPLOYEE.UPDATE_SENSITIVE`).

**What E-10 will add later**: `sensitive_access_log` itself (read-path logging for every RESTRICTED
field read, including statutory fields), the full 14-permission RBAC enforcement sweep across every
Employee endpoint, the `SELF`/`REPORTEES`/`REPORTEE_TREE` data-scope resolver, and finalizing
`get_assignment_as_of`/`get_compensation_as_of`/(by extension) `get_statutory_as_of` as the public
cross-module contract other modules import.

**Can E-07 operate safely before E-10 exists?** Yes, with a named, accepted gap — exactly the
precedent E-06 already set. `20_EMPLOYEE_COMPENSATION_IMPLEMENTATION_REPORT.md §17` states this
explicitly for Compensation: "No `sensitive_access_log` read-path logging — CTC is
`RESTRICTED`-classified..., but read-path logging... is out of scope... This is a real, named
compliance gap for the period between E-06 and E-10 shipping." The identical statement applies to
E-07 without modification: PF number, ESI IP number, and tax regime reads will have **no** access
log entry until E-10 ships. This is not a new decision E-07 must make — it is the same,
already-accepted gap, and E-07's own closeout report should name it exactly as E-06's did, not treat
it as newly discovered.

---

## 13. E-07 vs. Payroll Boundary

Per `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part F (Payroll readiness table): "What statutory
information applies? | `employee_statutory` as-of pay period | **No** — table doesn't exist yet;
must ship in E-07 (B5)." And: "`employee_statutory` and `employee_bank` are the two hard blockers...
This is the single highest-leverage 'don't defer' decision in this entire record."

**E-07 owns** (now): the employee-level statutory identifiers and applicability flags (`is_pf_
applicable`, `pf_number`, `vpf_amount`/`vpf_percentage`, `is_esi_applicable`, `esi_ip_number`,
`pt_state_code`, `is_lwf_applicable`, `tax_regime`, `is_director`, `is_international_worker`), their
effective-dated write path, and (per `01_EMPLOYEE_MODULE_PLAN.md`'s E-07 "Tests" note) the
**tax-regime once-per-FY switch validation rule** (FR-PAY-006) — a Payroll-motivated rule enforced
here because Employee owns the only write path to this data: "this rule belongs conceptually to
Payroll but the *data* lives on Employee's table; the constraint should be enforced here since
Employee owns the write path."

**Payroll owns** (future, not built, not E-07's concern): monthly PF/ESI contribution calculation,
ECR filing, TDS computation against tax slabs, wage-ceiling arithmetic, and the **statutory rate
tables** themselves (PF %, ESI %, PT slabs, LWF amounts — ADR-0011, ​`docs/product/17_SRS_
Phase1_Core_Modules.md` FR-PAY-005, "Statutory master... All values are seeded as data and require
compliance sign-off before go-live"). This is a **distinct concern from `employee_statutory`**: the
rate tables describe what percentage/slab applies government-wide or state-wide; `employee_
statutory` describes one employee's applicability/identifiers within those rules. E-07 does not
touch the rate-table side at all.

**Cross-module contract**: E-07 should expose a `get_statutory_as_of(employee_id, date)` service
method, extending the already-named pattern (`get_assignment_as_of`, `get_compensation_as_of`) that
Payroll will import later (`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` B7). Payroll is a **consumer
only** — E-07 does not depend on Payroll existing, mirroring Compensation's own stated relationship
(`17_EMPLOYEE_COMPENSATION_IMPLEMENTATION_PLAN.md §15`: "Payroll (future) | Consumer, not a
dependency").

---

## 14. Permission Model

**Locked catalogue position** (`docs/product/19_RBAC_and_Permission_Matrix.md §3.1`, confirmed
identical in `apps/api/src/hrms/modules/identity/permissions.py`'s 14-code documentation and in the
employee module's own `permissions.py` docstring): the only permission code that names statutory
data at all is `EMPLOYEE.UPDATE_SENSITIVE` — "Edit PAN/Aadhaar/bank/statutory," a **write-only**
code, bundled across four different data categories. **There is no `EMPLOYEE.VIEW_STATUTORY` in the
locked 14-code catalogue.** This gap is independently flagged in three source documents
(`00_EMPLOYEE_AUDIT.md §13.1`, `02_EMPLOYEE_DATA_MODEL.md §2` section F, `01_EMPLOYEE_MODULE_PLAN.md`
E-07's own "Risks" line).

**Architectural resolution already recommended** (`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` A9/B9):
add two new codes beyond the 14 — `EMPLOYEE.VIEW_STATUTORY` and `EMPLOYEE.VIEW_BANKING` — rather
than bundling statutory/banking visibility under `EMPLOYEE.VIEW_COMPENSATION` (which the audit's own
tentative option would have done). Reasoning quoted: bundling "means anyone who can see CTC can see
bank account numbers, which is a *broader* grant than 'stricter,' not equal to it." The literal
code **names** are flagged "REQUIRES PRODUCT DECISION... a naming choice, not an architectural one
— safe to finalize immediately... not a blocker."

**Are statutory permissions separate from compensation?** Yes — decided. `EMPLOYEE.VIEW_STATUTORY`
is a distinct code from `EMPLOYEE.VIEW_COMPENSATION`; a caller with one does not automatically get
the other.

**Recommended for E-07** (engineering default per the precedent E-03 set for its own analogous
naming gap, `.TERMINATE` — proceed, document the assumption, do not block):
- `EMPLOYEE.VIEW_STATUTORY` (**new**, not yet in code) — gates both `GET` routes.
- `EMPLOYEE.UPDATE_SENSITIVE` (**new to code — not yet seeded anywhere**, though named in the
  locked 14-code catalogue) — gates the `POST` route. Add exactly one constant + one
  `EMPLOYEE_PERMISSIONS` entry in `permissions.py`, worded generically enough to cover its documented
  scope ("Edit PAN/Aadhaar/bank/statutory") since PAN/Aadhaar/bank writes are **not** part of E-07 —
  see boundary note below.

**Explicit scope boundary — do not let E-07 absorb E-02's/E-08's work.** `EMPLOYEE.UPDATE_SENSITIVE`
is documented as covering PAN, Aadhaar, bank, *and* statutory writes together. E-07 should add the
permission constant (since nothing else has yet) and wire it **only** to the `employee_statutory`
POST route. It should **not** also wire it to `PATCH /v1/employees/{id}` for
`pan_number_enc`/`aadhaar_number_enc`/`uan_number` (that write path is E-02's, unbuilt, out of
scope, §2) or to `employee_bank` (E-08's, unbuilt, out of scope). Adding the permission's write
target for those other tables prematurely would be scope creep into slices this task was not asked
to touch.

---

## 15. Audit Model

**Mutation-only**, using the existing, singular `AuditService.record(session, company_id,
actor_user_id, action, entity_type, entity_id, before, after, ip, user_agent)`
(`apps/api/src/hrms/core/audit/service.py`) — the same mechanism every prior slice uses, called
inside the same transaction as the write. There is no distinct "sensitive access" audit mechanism
in the codebase today (§12); only write-path logging exists.

**Recommended event**: a single action `STATUTORY_REVISED` (not fragmented per changed field),
`entity_type = "employee_statutory"`, mirroring Compensation's `COMPENSATION_REVISED` convention
exactly (`00_EMPLOYEE_AUDIT.md §13.4`'s own recommended naming scheme:
`<ENTITY>_CREATED/UPDATED/...`, generalized the same way Compensation generalized it to one event
per write regardless of what changed). `before` = the closed row's full snapshot (or `null` for an
employee's first-ever statutory row); `after` = the new row's full snapshot.

**Known limitation to flag, not silently inherit**: following the Compensation pattern exactly means
`pf_number`/`esi_ip_number`/`tax_regime` land in `audit_log.before_json`/`after_json` as plain,
unencrypted JSONB — the same design already accepted for CTC in E-06. This is a pre-existing
project-wide pattern (nothing in the codebase encrypts or redacts audit payloads for any entity),
not a new gap E-07 introduces, but it should be named explicitly in E-07's own closeout report, the
same way E-06's report named the read-path gap (§12), rather than passing over it silently.

**Read-path (`sensitive_access_log`) logging**: not built in E-07, locked to E-10 (§12).

---

## 16. API Plan

Following `03_EMPLOYEE_API_PLAN.md §2.4`'s own recommendation (insert-only despite the doc's
literal "PATCH" listing — ADR-0003 is the more specific, more recently reasoned source for
effective-dated data) and E-06's exact shipped shape:

| Method | Path | Permission | Response |
|---|---|---|---|
| GET | `/v1/employees/{employee_id}/statutory` (supports `?as_of=YYYY-MM-DD`) | `EMPLOYEE.VIEW_STATUTORY` | `200`, `ListEnvelope[StatutoryRead]` — full history, or single as-of row |
| GET | `/v1/employees/{employee_id}/statutory/{statutory_id}` | `EMPLOYEE.VIEW_STATUTORY` | `200`, `DataEnvelope[StatutoryRead]` |
| POST | `/v1/employees/{employee_id}/statutory` | `EMPLOYEE.UPDATE_SENSITIVE` | `201`, `DataEnvelope[StatutoryRead]` |

**Request body** (`StatutoryCreate`, `extra="forbid"`, mirroring `CompensationCreate`'s
no-carry-forward posture since these are compliance-sensitive fields where a silently stale value is
worse than requiring an explicit resubmission):
- `effective_from` (date, required)
- `is_pf_applicable` (bool, required)
- `pf_number` (string, optional)
- `pf_wage_ceiling_opt_out` (bool, default `false`)
- `vpf_amount` (int minor-units, optional)
- `vpf_percentage` (numeric, optional)
- `is_esi_applicable` (bool, required)
- `esi_ip_number` (string, optional)
- `pt_state_code` (string, optional)
- `is_lwf_applicable` (bool, required)
- `tax_regime` (enum `OLD`/`NEW`, required)
- `is_director` (bool, default `false`)
- `is_international_worker` (bool, default `false`)
- `revision_reason` (string) — **not explicitly required by any document**; recommended required,
  by direct analogy to Compensation's `revision_reason`, for audit-trail parity on RESTRICTED data
  (engineering decision, §24).

**Concurrency**: `If-Match: <version>` required only when the employee already has a current
statutory row (nothing to version-check on a first-ever row) — this is the pattern Compensation
actually shipped with (`19_EMPLOYEE_COMPENSATION_API.md`), not merely what the original API-plan
doc silently assumed. Stale version → `409 STALE_RESOURCE`. Missing `If-Match` when a current row
exists → `422 STATUTORY_VERSION_REQUIRED` (named by direct analogy to
`COMPENSATION_VERSION_REQUIRED`).

**Error cases**:
- `404 NOT_FOUND` — employee doesn't exist or is cross-tenant (never `403` for existence, per
  `03_EMPLOYEE_API_PLAN.md §1`'s cross-tenant convention).
- `409 NO_ACTIVE_EMPLOYMENT` — no covering `employment` row for `effective_from`, by direct analogy
  to Assignment's and Compensation's identical, undocumented-but-twice-precedented check
  (`EmploymentRepository.get_employment_as_of`). This is an engineering-decision pattern, not
  sourced from a document, applied by analogy exactly as the two prior slices applied it.
- `409 STATUTORY_DATES_OVERLAP` — GiST exclusion constraint violation translated to a domain error.
- `422 INVALID_EFFECTIVE_FROM` — malformed or out-of-order date.
- `422 STATUTORY_VERSION_REQUIRED` — see above.
- `409 STALE_RESOURCE` — version mismatch.
- `422 TAX_REGIME_SWITCH_NOT_ALLOWED` — the FR-PAY-006 once-per-FY rule violated (§17).
- `403 PERMISSION_DENIED`.

**Tenant behavior**: identical to every prior slice — `company_id` from `TenantContext`, RLS-forced,
repository-level `company_id` filter as belt-and-suspenders (§18).

**Sensitive-field behavior**: whole-sub-resource gating, not per-field masking (§11).

**Audit behavior**: see §15.

---

## 17. Validation Rules

**Documented**:
- `effective_from` required; a new row must not create an overlapping period for the same
  `employee_id` (GiST-enforced at the DB level, `02_EMPLOYEE_DATA_MODEL.md §1.1`).
- **Tax-regime once-per-FY switch rule** (FR-PAY-006, `docs/product/17_SRS_Phase1_Core_Modules.md`):
  an employee may change `tax_regime` only once per financial year. This rule is named but its exact
  mechanics are not specified — no document defines the system's fiscal-year boundary.

**Not documented — flagged, not invented**:
- **FY boundary definition.** India's standard fiscal year is April 1–March 31, and the "India-
  specific" framing of this whole table (§5's DDL, the SRS's PF/ESI/PT/LWF framing) makes this a
  reasonable *engineering assumption*, but no document states it as a system constant, and
  `docs/product/26_Risk_Register_...md` Q1/A1 records that "India-only payroll" is itself an
  **unconfirmed** assumption pending product sign-off. Do not hard-code April–March without flagging
  it as an assumption in the closeout report (§22 item 5).
- **Applicability/identifier correlation**: no document states whether `is_esi_applicable = true`
  must imply `esi_ip_number IS NOT NULL` (or the equivalent for `is_pf_applicable`/`pf_number`).
  Flagged as an open validation question (§22 item 6), not defaulted to a hard constraint here.
- **Legal-entity-registration correlation**: whether `is_esi_applicable`/`is_pf_applicable` should be
  validated against the active `legal_entity` actually having `esi_code`/`pf_code` set (§9) is
  plausible but undocumented.
- **Mass-assignment protection**: `extra="forbid"` on the Create schema, per project-wide convention
  (confirmed test pattern in `test_employee_compensation.py`).

---

## 18. Tenant/RLS Model

Identical, unmodified project convention (`docs/database/Database_Architecture.md`,
confirmed live for every existing Employee table):
- `ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY` on `employee_statutory`.
- Single policy `tenant_isolation ON employee_statutory USING (company_id =
  current_setting('app.company_id', true)::uuid)`.
- App-level: `set_config('app.company_id', ...)` set per-transaction via
  `hrms.core.db.session.set_rls_company_id`, populated from `TenantContext`.
- Repository queries additionally filter `company_id` explicitly ("belt-and-suspenders," an existing
  project convention, not new to E-07).
- Cross-tenant access → `404`, never `403` (existence itself is not disclosed).

---

## 19. Frontend Scope

Out of scope for this investigation per the task's explicit instructions (no frontend investigation
or code was performed). For completeness of the plan: `01_EMPLOYEE_MODULE_PLAN.md`'s own E-07 row
places frontend work as "a sub-section within the Compensation tab, pending a dedicated permission
decision (`04_EMPLOYEE_UX_PLAN.md §2`)" — i.e., no frontend ships as part of E-07 itself; the first
usable Employee screen is E-09 per the E-01 slice note ("first usable screen ships with E-09"). Any
statutory UI work is deferred until at minimum the permission-naming question (§14) is settled and
E-09 exists to host it.

---

## 20. Test Plan

Mirrors `apps/api/tests/integration/modules/employee/test_employee_compensation.py`'s established
pattern set exactly (confirmed by direct reading of that file):

1. **Create** — first statutory row for an employee with active employment succeeds, no `If-Match`
   required.
2. **Create — second revision** — closes the current row, inserts a new one; `If-Match` with the
   correct version required.
3. **Read** — current row, `?as_of=` a past/future date, full history, single row by id.
4. **List** — full history ordered by `effective_from`.
5. **Validation**:
   - Overlapping `effective_from`/`effective_to` rejected at the DB level (GiST) — proven directly,
     bypassing RLS with `SET LOCAL row_security = off` and asserting `IntegrityError`, not just an
     application-level check (matches the compensation test's own proof pattern).
   - `effective_from` before employment's `joining_date`, or with no covering employment episode at
     all → `409 NO_ACTIVE_EMPLOYMENT`.
   - Mass-assignment: posting `version`/`company_id`/`id` in the request body → `422`.
   - Tax-regime switch within the same FY (assumed boundary, §17) rejected → `422
     TAX_REGIME_SWITCH_NOT_ALLOWED`.
6. **Permissions**:
   - Caller with only `EMPLOYEE.VIEW_STATUTORY` can read but not write.
   - Caller with only `EMPLOYEE.UPDATE_SENSITIVE` can write but the sub-resource is absent on read
     without `.VIEW_STATUTORY`.
   - Caller with neither → `403`/absent, using the `_create_permission_scoped_user` helper pattern
     already established.
7. **Cross-tenant access**: GET/POST against another tenant's employee → `404`, not `403`.
8. **RLS**: forced-RLS behavior proven directly at the DB layer, not only through the API.
9. **Concurrency**: stale `If-Match` → `409 STALE_RESOURCE`; missing `If-Match` when a current row
   exists → `422 STATUTORY_VERSION_REQUIRED`.
10. **Unique constraint / GiST**: proven as in item 5.
11. **Effective-date rules**: as-of-date query correctness across a multi-revision history (mirrors
    Assignment's own as-of test against a worked multi-year example).
12. **Audit**: exactly one `AuditLog` row per write, `action == "STATUTORY_REVISED"`,
    `entity_type == "employee_statutory"`, `before_json is None` on the first-ever write,
    `before_json`/`after_json` populated on subsequent writes.
13. **Rehire scenario**: exit an employment → verify last statutory row closed → rehire (new
    `employment` row, same `employee_id`) → insert a new statutory row → assert old row(s) remain
    queryable, unmerged, and `employee.uan_number` (read from `employee`, not `employee_statutory`)
    is unaffected by the rehire.
14. **Legal Entity boundary**: no test asserts any duplication between `legal_entity.pf_code`/
    `esi_code` and `employee_statutory` fields — confirms they remain independent (a negative test,
    not a positive requirement from any document).
15. **Sensitive-field protection**: assert `pf_number`/`esi_ip_number`/`tax_regime` are absent (not
    null) from any response when the caller lacks `EMPLOYEE.VIEW_STATUTORY` — the same "raw JSON,
    not through a client" check `docs/product/19_RBAC_and_Permission_Matrix.md §8` mandates for
    every RESTRICTED field test.

---

## 21. Migration Plan

One new Alembic migration, following the exact structural precedent of
`20260814120000_employee_compensation.py`:

1. `CREATE TABLE employee_statutory` per §5's DDL (no `uan` column — §10).
2. GiST exclusion constraint `employee_statutory_no_overlap`.
3. Two indexes: `(company_id)` and `(employee_id, effective_from)`.
4. `ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY` + `tenant_isolation` policy, asserted
   idempotently in the same migration (matching every prior Employee migration's own convention,
   `01_EMPLOYEE_MODULE_PLAN.md §2` E-01's note: "RLS re-asserted idempotently").
5. No `ALTER TABLE` on `employee`, `employment`, `legal_entity`, or `employee_compensation` is
   required.
6. Permission seeding: add `EMPLOYEE_VIEW_STATUTORY` and `EMPLOYEE_UPDATE_SENSITIVE` constants +
   `EMPLOYEE_PERMISSIONS` entries in `apps/api/src/hrms/modules/employee/permissions.py`, following
   whatever mechanism already seeds `EMPLOYEE_VIEW_COMPENSATION`/`EMPLOYEE_UPDATE_COMPENSATION` into
   the live `permission` table (the implementing task should locate and reuse that exact mechanism
   rather than inventing a new one).

---

## 22. Product Decisions

Genuine decisions requiring explicit sign-off — not defaulted silently in this plan:

1. **Exact permission code literal names** for statutory view access (`EMPLOYEE.VIEW_STATUTORY` is
   this document's carried-forward recommendation from `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md`
   A9/B9, but the source document itself calls this "REQUIRES PRODUCT DECISION"). **Non-blocking**
   per the source's own framing ("safe to finalize immediately... not a blocker to starting") —
   recommend proceeding with the documented default and flagging it as an assumption, matching the
   `.TERMINATE` precedent (§14).
2. **Masking format (if any) for `pf_number`/`esi_ip_number`/`pt_state_code`/`tax_regime`.** No
   document specifies one; this plan's recommended default is "no masking, whole-resource gating"
   (§11), consistent with CTC's own precedent, but product has not confirmed this is sufficient for
   compliance purposes.
3. **UAN masking format.** `02_EMPLOYEE_DATA_MODEL.md §2` requires UAN be "masked in API" but no
   format is given anywhere (unlike PAN/Aadhaar/bank, which each have one). Not blocking for E-07
   itself (§6 — E-07 does not touch `employee.uan_number`), but should be resolved before E-02 ships.
4. **`pf_number` carry-forward on rehire.** No document states whether a rejoining employee's
   `pf_number` should be pre-filled/reused (especially when rejoining the same legal entity) or
   entered fresh every time (§8).
5. **Fiscal-year boundary for the once-per-FY tax-regime-switch rule** (FR-PAY-006). No document
   states the system's FY convention; April–March is a reasonable India-centric assumption but is
   tied to the still-unconfirmed "India-only payroll" scoping question (`docs/product/
   26_Risk_Register...md` Q1/A1) (§17).
6. **Applicability/identifier correlation rules** — whether `is_pf_applicable`/`is_esi_applicable`
   should hard-require their corresponding number fields, and whether applicability should be
   validated against the employing legal entity's own PF/ESI registration (§9, §17).
7. Whether `employee_statutory`'s fields should later be encrypted at rest like PAN/Aadhaar/bank
   (currently: no document requires this, and the reviewed DDL declares plain columns) — a
   compliance posture question, not decided here (§11, §25).

---

## 23. Engineering Decisions

Safe to proceed without further sign-off, each justified by direct precedent already shipped in this
codebase:

1. `employee_statutory` excludes a `uan` column; UAN stays solely on `employee.uan_number` — resolves
   the two-document DDL/field-inventory discrepancy in favor of the live schema and the concrete,
   reviewed DDL (§10).
2. `NO_ACTIVE_EMPLOYMENT` covering-employment check on every write, by direct analogy to Assignment
   and Compensation's identical, twice-precedented pattern (§16).
3. `If-Match` required only when a current row exists, matching Compensation's actual shipped
   behavior (not the earlier API-plan doc's silence on this point) (§16).
4. Audit action name `STATUTORY_REVISED`, `entity_type = "employee_statutory"`, by direct analogy to
   `COMPENSATION_REVISED` (§15).
5. No separate history table — reuse the same in-table effective-dating pattern as every other
   Employee child table (§10).
6. Static 1:1 route-to-permission wiring (`Depends(require_permission(...))`), matching
   Compensation's simplest-case pattern — no dynamic permission selection is needed, unlike
   Assignment's `change_type`-based branching (§16).
7. `revision_reason` required on every write, for audit-trail parity with Compensation (§16).
8. No per-field masking in the statutory response; whole sub-resource gated by
   `EMPLOYEE.VIEW_STATUTORY` (§11).
9. `EMPLOYEE.UPDATE_SENSITIVE`'s scope in E-07 is limited strictly to the `employee_statutory` POST
   route — it is not wired to `employee`'s PAN/Aadhaar/UAN fields (E-02) or `employee_bank` (E-08)
   even though the permission's documented description spans all of them (§14).

---

## 24. Risks and Known Limitations

1. **No read-path audit trail until E-10** — PF/ESI/tax-regime reads are unlogged between E-07
   shipping and E-10 shipping, an accepted, already-precedented gap (§12), not a new risk E-07
   introduces, but one its closeout report must name explicitly.
2. **Unencrypted audit payloads** — statutory identifiers will appear in plaintext in
   `audit_log.before_json`/`after_json`, a pre-existing, project-wide pattern (§15), not unique to
   E-07, but compounding as more RESTRICTED-tier tables ship.
3. **Inferred sensitivity classification** — no document explicitly places PF/ESI/PT/tax-regime
   fields in the RESTRICTED tier by name; this plan follows the audit's own inference rather than an
   explicit source (§11).
4. **India-only assumption is itself unconfirmed** (`docs/product/26_Risk_Register...md` Q1/A1) —
   if multi-country payroll is later required, the FY-boundary assumption (§17) and possibly the
   entire field set (India-specific PF/ESI/PT/LWF) will need redesign; E-07 as scoped here does not
   attempt a country-abstraction layer, matching the risk register's own framing of that as a
   separate, larger decision.
5. **`pf_number` rehire behavior is genuinely undecided** (§8, §22) — implementing without product
   input risks a UX assumption (auto-carry vs. fresh entry) that may need to be reversed later.
6. **Two-document DDL discrepancy resolved unilaterally in this plan** (§10) — this plan picks the
   live-schema-consistent interpretation, but the source documents themselves were never corrected;
   a future reader of `02_EMPLOYEE_DATA_MODEL.md §2` section F or `docs/product/
   08_Database_Architecture.md §5.5` in isolation could still be misled into adding a duplicate `uan`
   column. Recommend those two documents be corrected as a small follow-up, not left silently
   inconsistent.

---

## 25. Implementation Sequence

For the future implementation task, in order:

1. Confirm (or explicitly assume and flag) the two non-blocking product decisions this plan can
   safely default on: permission code name `EMPLOYEE.VIEW_STATUTORY`, no per-field masking.
2. Write the Alembic migration (§21): `CREATE TABLE employee_statutory`, GiST constraint, indexes,
   RLS policy.
3. Add `EmployeeStatutory` ORM model to `apps/api/src/hrms/modules/employee/models.py`, keyed on
   `employee_id`, matching `EmployeeCompensation`'s exact shape and docstring convention.
4. Add `EmployeeStatutoryRepository` methods to `repository.py`: `insert_statutory`,
   `get_current_statutory`, `get_statutory_as_of`, `list_statutories`, `get_statutory`,
   `close_statutory` — mirroring `EmployeeCompensationRepository` method-for-method.
5. Add `EMPLOYEE_VIEW_STATUTORY`/`EMPLOYEE_UPDATE_SENSITIVE` to `permissions.py`, with a docstring
   entry following the module's existing per-slice documentation convention (see the existing E-06
   paragraph as a template) and explicitly noting the scope boundary from §14.
6. Add `StatutoryCreate`/`StatutoryRead` schemas to `schemas.py` (`extra="forbid"` on Create), and
   `statutory_to_audit_dict`.
7. Add service-layer methods to `service.py`: create-revision (covering-employment check,
   close-current-row-then-insert, tax-regime-once-per-FY validation, audit call), get-current,
   get-as-of, list — mirroring the Compensation service methods.
8. Add router routes to `router.py`: `GET`/`GET-by-id`/`POST` under
   `/v1/employees/{employee_id}/statutory`, wired to the two permissions per §16.
9. Add exception classes to `exceptions.py` as needed
   (`StatutoryVersionRequiredError`/`TaxRegimeSwitchNotAllowedError`/etc.), mirroring
   `exceptions.py`'s existing Compensation-error shape.
10. Write the integration test file `apps/api/tests/integration/modules/employee/
    test_employee_statutory.py`, covering every item in §20.
11. Write the unit test file for service-layer validation logic, mirroring
    `apps/api/tests/unit/modules/employee/test_employee_compensation_service.py`.
12. Produce the closeout report (`22_EMPLOYEE_STATUTORY_IMPLEMENTATION_REPORT.md`), explicitly
    naming every assumption flagged in §22/§24, following E-06's own closeout report structure.

---

## 26. Definition of Done

- `employee_statutory` exists in the live schema with the exact shape in §5, RLS forced and proven
  by a direct DB-level test (bypassing app-level checks).
- All three endpoints (§16) implemented, permission-gated, returning the documented envelopes.
- Every test in §20 passes, including the DB-level GiST exclusion proof and the rehire scenario.
- `EMPLOYEE.VIEW_STATUTORY`/`EMPLOYEE.UPDATE_SENSITIVE` seeded and functioning, scoped exactly as
  §14 specifies (no leakage into E-02/E-08 write paths).
- Audit event `STATUTORY_REVISED` fires exactly once per write, verified by a direct `AuditLog`
  query.
- No `sensitive_access_log` work attempted (confirmed absent from the diff, matching E-06's own
  explicit exclusion).
- Closeout report written, naming every flagged assumption (§22) as an assumption, not asserting any
  of them as settled.
- No changes to `employee`, `employment`, `legal_entity`, or `employee_compensation` schemas.

---

## 27. Final Readiness Assessment

**READY TO IMPLEMENT, with flagged assumptions.**

No architectural blocker exists: ownership (`employee_id`), effective-dating mechanics, the
Employee/Legal-Entity boundary, the E-07/E-10 boundary, and the E-07/Payroll boundary are all
already decided in the source documents (§7, §9, §10, §12, §13) and are not reopened here. The
table does not yet exist in the live schema (§4) but its DDL is already fully specified and
reviewed (§5).

The remaining open items (§22) are, without exception, either (a) explicitly framed by their own
source document as "safe to finalize immediately... not a blocker" (the permission-code naming
gap), or (b) narrow business-rule/UX details (FY boundary, `pf_number` rehire carry-forward,
applicability-correlation validation, masking format) that this codebase's own established
discipline — demonstrated twice already, in E-03's `.TERMINATE` naming and E-06's
`sensitive_access_log` exclusion — resolves by proceeding with a documented, flagged default rather
than blocking, provided the implementing task states each one as an assumption in its closeout
report rather than a silently settled fact.

**Recommended implementation sequence**: §25, in order. **First action for the implementing agent**:
confirm §22 item 1 (the `EMPLOYEE.VIEW_STATUTORY` code name) with product if a fast answer is
available; if not, proceed with the recommended default and flag it, exactly as this plan does.
