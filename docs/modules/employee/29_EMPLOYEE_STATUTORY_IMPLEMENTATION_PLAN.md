# Employee Statutory (E-07) — Implementation Plan

Companion to, and the authoritative successor of, `21_EMPLOYEE_STATUTORY_IMPLEMENTATION_PLAN.md`
(written 2026-08-14, before the RBAC data-scope slice landed). This document re-verifies every
claim in `21_` against the current codebase and database (2026-08-15, post `24`–`28`) and
supersedes it wherever the two disagree. **This document is investigation and planning only — no
application code, migrations, tests, or frontend code were written or modified to produce it.**

Do not read `21_` as authoritative on its own after this document exists — §1 below states exactly
what changed and why `21_` is superseded, not merely duplicated.

---

## 1. Executive Summary

E-07 adds `employee_statutory` — the per-employee PF/ESI/PT/LWF/tax-regime profile Payroll will
read once it exists. The table does not exist in the live schema or in any migration (reconfirmed
by direct `psql` inspection today, §4); it is a fully greenfield slice at the code level. The data
model, effective-dating mechanics, Employee/Legal-Entity boundary, and Payroll boundary are already
locked in `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` and are not reopened here — E-07's nearest
sibling and pattern template remains **E-06 Compensation**.

**What changed since `21_` and why this document supersedes it:**

1. **RBAC data-scope (`SELF`/`REPORTEES`/`REPORTEE_TREE`/`COMPANY`) now exists** (`24`–`26`), but is
   wired to exactly two routes (`GET /employees`, `GET /employees/{id}`). Every other Employee
   route — including Compensation's `GET`/`POST` — still resolves its permission through
   `require_permission()` but **discards** the returned `DataScope`, remaining `COMPANY`-scoped in
   effect. `21_` predates this infrastructure entirely and could not address it; this document adds
   a full analysis (§11, §17) of whether `EMPLOYEE.VIEW_STATUTORY` should behave like Compensation
   (ignore scope) or opt in to scope enforcement, and recommends the former with the gap named
   explicitly, not silently inherited.
2. **A reporting-manager self-elevation guard now exists** (`27`–`28`) on `POST
   .../assignments` — `reporting_manager_id` cannot be set to the acting caller's own
   `employee_id`, since it is the sole input to `REPORTEES`/`REPORTEE_TREE` resolution. This has no
   direct field-level analogue on `employee_statutory` (statutory has no manager-reference field),
   but the underlying principle — a write must not be able to expand the writer's own future data
   scope — is carried into this plan's stance in §11.
3. **A DB-state discrepancy `21_` did not have**: the live `permission` table already contains one
   row for `EMPLOYEE.UPDATE_SENSITIVE` (`domain=EMPLOYEE`, `description="Edit PAN/Aadhaar/bank/
   statutory"`, granted to zero roles) — but **no migration, seed script, or code constant produces
   it**. `21_` asserted this permission was "not yet seeded anywhere"; that is no longer accurate as
   a description of the live database, though it remains accurate as a description of the
   reproducible schema. §5 and §24 treat this as orphaned/manually-inserted data, not a foundation
   to build on.
4. **Everything else `21_` established is reconfirmed unchanged**: no `employee_statutory` table or
   code exists anywhere (§4); `employee.pan_number_enc`/`aadhaar_number_enc`/`uan_number` are still
   live columns with no write path; `legal_entity`'s statutory columns are unchanged; no Banking/E-08
   documentation exists in the repository (confirmed by a fresh search, §9); the only payroll-side
   document (`docs/adr/0005-payroll-snapshot-immutability.md`) adds one useful detail `21_` did not
   have — the exact pipeline stage that will consume `employee_statutory` (§16).

**Final readiness: READY TO IMPLEMENT, with flagged assumptions** (§30) — same overall verdict as
`21_`, carried forward on re-verified evidence, with two additional non-blocking items (data-scope
posture, the orphaned permission row) added to the assumption list.

---

## 2. Authoritative Sources

All sources `21_` §3 cites, reconfirmed still current, plus:

| Document | What it adds for this revision |
|---|---|
| `docs/modules/employee/24_EMPLOYEE_RBAC_DATA_SCOPE_AUDIT.md` | Confirms the pre-existing failure mode (every route ungated by scope) and the decision to fix only two routes first |
| `docs/modules/employee/25_EMPLOYEE_RBAC_DATA_SCOPE_IMPLEMENTATION_PLAN.md` | §22 explicitly excludes "Statutory" from this slice's scope by name — confirms E-07 inherits an *open*, not resolved, data-scope question |
| `docs/modules/employee/26_EMPLOYEE_RBAC_DATA_SCOPE_IMPLEMENTATION_REPORT.md` | Confirms exactly which two routes shipped scoped, and that `role_permission.data_scope` is now a column on *every* permission grant regardless of whether the consuming route reads it |
| `docs/modules/employee/27_REPORTING_MANAGER_SECURITY_AUDIT.md`, `28_REPORTING_MANAGER_SECURITY_IMPLEMENTATION_REPORT.md` | The self-elevation guard precedent applied to this plan's stance on statutory permission scope (§11) |
| `docs/architecture/RBAC_DATA_SCOPE_DECISIONS.md`, `RBAC_DATA_SCOPE_IMPLEMENTATION_PLAN.md` | Cross-cutting architecture record for the scope levels, `SELF`/`REPORTEES`/`REPORTEE_TREE` semantics (§4–§6) |
| `docs/adr/0005-payroll-snapshot-immutability.md` | The only live payroll-side document; names "statutory master versions" as one of the inputs snapshotted into `payrun_input_snapshot` before computation (§16) |
| `apps/api/src/hrms/modules/employee/router.py`, `service.py`, `repository.py`, `permissions.py`, `exceptions.py`, `dependencies.py`, `schemas.py` (current, 2026-08-15) | Re-read in full for this revision; confirms the exact shape E-07 must match (§4, §17–§20) |
| `apps/api/src/hrms/core/rbac/service.py`, `types.py`, `dependencies.py` | Re-read in full; confirms `require_permission()` always resolves and returns a `DataScope`, and that discarding it (typing the dependency result as `object`) is the established, intentional pattern for not-yet-scoped routes |
| `apps/api/src/hrms/seed/bootstrap.py` | The actual permission-seeding mechanism (`seed_b1_foundation`) — confirms `EMPLOYEE_PERMISSIONS` (the code list) is the single source of truth, and that the orphaned `EMPLOYEE.UPDATE_SENSITIVE` row did not come from it |

No Banking/E-08 documentation exists anywhere in `docs/` (a repository-wide search for filenames
and content found none) — `21_`'s framing of Banking as "unbuilt, out of scope" is reconfirmed, now
by direct search rather than inference.

---

## 3. Current Implementation State

Unchanged from `21_` §2, reconfirmed: E-01/E-03/E-04/E-05/E-06 complete; E-02 (identity/profile
completion) not shipped — `pan_number_enc`/`aadhaar_number_enc`/`uan_number` on `employee` still
have columns but no write path. A fresh repo-wide grep for `statutory`/`employee_statutory` today
returns exactly the same three non-implementations `21_` found (a permission-naming comment, a
scope-exclusion comment, the `LegalEntity` docstring) — zero code, model, or test touches
`employee_statutory`.

**New since `21_`**: `apps/api/src/hrms/modules/employee/router.py`'s own module docstring now
documents, in its own words, that data-scope enforcement exists for exactly `list_employees`/
`get_employee` and that "every other route in this file... is still not data-scoped... a
deliberate, narrow first pass, not an oversight." This is the router's own explicit statement of
the boundary E-07 inherits (§11).

---

## 4. Current Database State

Reconfirmed today by direct `psql` inspection against `postgresql://hrms:hrms_dev_password@
localhost:5433/hrms_dev`:

- **`employee_statutory` does not exist** — no such table in `\dt`.
- **Migration head is now `20260815120000`** (`role_permission_data_scope`), one migration ahead of
  `21_`'s `20260814120000`. That migration is purely additive: `role_permission.data_scope
  VARCHAR(20) NOT NULL DEFAULT 'COMPANY'`, `CHECK (data_scope IN ('SELF','REPORTEES',
  'REPORTEE_TREE','COMPANY'))`. It touches no Employee table and adds no new permission rows.
- `employee.pan_number_enc` (`text`), `employee.aadhaar_number_enc` (`text`),
  `employee.uan_number` (`varchar(20)`) — still live, still no write path. Unchanged from `21_`.
- `legal_entity.pan`/`gstin`/`tan`/`cin`/`pf_code`/`esi_code`/`lwf_reg` — still live, unchanged.
- **`role_permission.data_scope` is now a column on every permission grant, not just
  `EMPLOYEE.VIEW`/`.VIEW_ALL`.** The `CHECK` constraint permits `SELF`/`REPORTEES`/
  `REPORTEE_TREE`/`COMPANY` for *any* code — nothing in the schema restricts which permissions may
  carry a non-`COMPANY` scope. This is a schema-level capability, not an application-level
  guarantee: whether a given route's *code* actually reads and applies the resolved `DataScope` is
  entirely up to that route (§11).
- **New finding, not in `21_`**: `permission` has exactly 34 rows. One of them is
  `EMPLOYEE.UPDATE_SENSITIVE` (`domain=EMPLOYEE`, `description="Edit PAN/Aadhaar/bank/statutory"` —
  verbatim the text `docs/product/19_RBAC_and_Permission_Matrix.md` line 43 already documents), and
  it is granted to **zero roles**. A search across every migration file, `apps/api/src/hrms/seed/
  bootstrap.py`, and full `git log -p` history of `permissions.py` finds no origin for this row — it
  has never been a code constant, and `seed_b1_foundation` (the only mechanism that inserts
  `Permission` rows, driven entirely by `B1_PERMISSIONS`/`ORGANISATION_PERMISSIONS`/
  `EMPLOYEE_PERMISSIONS`) cannot have produced it, since `EMPLOYEE_PERMISSIONS` does not name it.
  **Treat this as orphaned, manually-inserted data** — most plausibly a leftover from a prior
  investigation session's manual `psql` exploration, not a real seed. It does not satisfy any test,
  is not relied on by any code path today, and a schema rebuilt from migrations + seed alone would
  not reproduce it. E-07 must add this permission properly (as a code constant in
  `EMPLOYEE_PERMISSIONS`, seeded idempotently through `seed_b1_foundation`) rather than silently
  relying on the row already being present — the idempotent `INSERT ... WHERE NOT EXISTS`-shaped
  check in `seed_b1_foundation` (`select(Permission).where(Permission.code == code)).scalar_one_or_
  none()`) will simply adopt the existing row without creating a duplicate, so this is a
  documentation/cleanliness flag, not a migration hazard (§24).
- The sibling pattern (`employee_compensation`) is otherwise unchanged from `21_` §4's description,
  with one added nuance confirmed by reading its migration: `employee_compensation` has existed
  **structurally since `scripts/sql/001_init_schema.sql`**, the very first migration — E-06 only
  added `revision_type`/`revision_reason` via `ALTER TABLE`. `employee_statutory`, by contrast, has
  **no such foundational presence anywhere** — E-07's migration is a genuine `CREATE TABLE` from
  nothing, not an additive `ALTER TABLE` against a pre-existing skeleton. This does not change the
  target DDL (§7) but means E-07's migration risk profile is closer to E-01's foundational table
  creation than to E-06's incremental-column addition.

---

## 5. Scope Definition

Unchanged from `21_` §5–§9. Restated precisely:

- **`employee_statutory`** — a new table: the employee's own PF/ESI/PT/LWF applicability flags and
  identifiers, plus tax regime election, keyed on `employee_id`, effective-dated.
- **`employee`** — already owns `pan_number_enc`/`aadhaar_number_enc`/`uan_number` (E-02's write
  path, not E-07's). E-07 does not add or touch any `employee` column.
- **`employment`** — no statutory fields; only consulted read-only (covering-employment check).
- **`employee_compensation`** — no statutory fields; independent effective-dated table, no overlap.
- **`legal_entity`** — owns the *employer's* PF/ESI/TAN/PAN/GST registration numbers, a categorically
  different layer from the *employee's* enrollment data (`21_` §9, reconfirmed, no code change since).
- **Payroll** — owns rate tables (PF %, ESI %, PT slabs) and all calculation logic; consumes
  `employee_statutory` as one of several snapshotted inputs (§16), never computes against it live.
- **Fields explicitly NOT stored here**: `uan` (stays on `employee.uan_number`, not duplicated —
  `21_` §10's resolution, reconfirmed against the live schema today), any computed/derived payroll
  amount (PF contribution, ESI deduction, TDS), any rate-table value.

---

## 6. Field-by-Field Analysis

Unchanged from `21_` §6/§11. No source document has been added or edited since `21_` that touches
statutory field classification, so the same conclusions hold, restated:

| Field | Table | Type | Sensitivity | List response | Detail response |
|---|---|---|---|---|---|
| `is_pf_applicable` | employee_statutory | boolean | RESTRICTED (inferred) | absent | included |
| `pf_number` | employee_statutory | varchar(30) | RESTRICTED (inferred) | absent | included |
| `pf_wage_ceiling_opt_out` | employee_statutory | boolean | RESTRICTED (inferred) | absent | included |
| `vpf_amount` | employee_statutory | bigint (minor units) | RESTRICTED (inferred) | absent | included |
| `vpf_percentage` | employee_statutory | numeric(9,4) | RESTRICTED (inferred) | absent | included |
| `is_esi_applicable` | employee_statutory | boolean | RESTRICTED (inferred) | absent | included |
| `esi_ip_number` | employee_statutory | varchar(30) | RESTRICTED (inferred) | absent | included |
| `pt_state_code` | employee_statutory | varchar(10) | RESTRICTED (inferred) | absent | included |
| `is_lwf_applicable` | employee_statutory | boolean | RESTRICTED (inferred) | absent | included |
| `tax_regime` | employee_statutory | varchar(10), `OLD`/`NEW` | RESTRICTED (Payroll-facing) | absent | included |
| `is_director` | employee_statutory | boolean | RESTRICTED (inferred) | absent | included |
| `is_international_worker` | employee_statutory | boolean | RESTRICTED (inferred) | absent | included |
| `uan_number` | `employee` (existing) | varchar(20) | RESTRICTED (inferred) | out of E-07 scope | out of E-07 scope |

**Storage**: plain columns, no column-level encryption — no source document requires it for these
fields (unlike `pan_number_enc`/`aadhaar_number_enc`, named `_enc` deliberately). Do not add
encryption without a documented requirement.

**Masking**: no format documented anywhere for any of these fields (unlike PAN/Aadhaar/bank, each
with an explicit format in `docs/product/19_RBAC_and_Permission_Matrix.md §6`). Recommended:
whole-sub-resource gating (present entirely, or 403/absent), matching Compensation's own shipped
precedent, not per-field masking.

---

## 7. Data Model

Unchanged DDL from `21_` §5, re-verified against the live `employee_compensation` shape today
(§4) and still the correct template:

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

CREATE INDEX employee_statutory_company_id_idx ON employee_statutory (company_id);
CREATE INDEX employee_statutory_employee_id_effective_from_idx
  ON employee_statutory (employee_id, effective_from);

ALTER TABLE employee_statutory ENABLE ROW LEVEL SECURITY;
ALTER TABLE employee_statutory FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON employee_statutory
  USING (company_id = current_setting('app.company_id', true)::uuid);
```

No FK to `employment` or `legal_entity`. No changes to `employee`, `employment`, `legal_entity`, or
`employee_compensation`. Because this is a genuine `CREATE TABLE` (§4's new finding, not an `ALTER
TABLE` against a foundational skeleton), the migration should follow the shape of a foundational
migration like `20260813180000_employee_foundation.py`, not the additive shape of
`20260814120000_employee_compensation.py`.

---

## 8. Relationships

Unchanged from `21_` §7/§9. `employee_id` is the only FK; `employment_id`/`legal_entity_id` are
deliberately absent — legal-entity context is resolved indirectly via the employee's active
`employment.legal_entity_id` at read time, never stored redundantly. No overlap or duplication risk
with `legal_entity`'s employer-level statutory registration fields.

---

## 9. Employment/Rehire Semantics

Unchanged from `21_` §8. Statutory rows survive exit (last row closed, never deleted/merged);
rehire opens a new row against the same `employee_id`; UAN continuity is a structural consequence of
`employee.uan_number` never being re-created (not statutory's concern); PF/ESI applicability flags
are re-evaluated fresh at rejoin, no carry-forward; `pf_number` carry-forward on rehire remains a
genuinely undecided product question (§26 item 4).

No Banking/E-08 documentation exists (§2, reconfirmed by fresh search) to compare statutory's
rehire behavior against — `21_`'s instruction to check this boundary is satisfied by confirming
there is nothing to conflict with yet.

---

## 10. Legal Entity Relationship

Unchanged from `21_` §9. `legal_entity`'s `pf_code`/`esi_code`/`tan`/`pan`/`gstin`/`cin`/`lwf_reg`
are live, reconfirmed today, and describe the employer, not the employee. The plausible-but-
undocumented validation ("can an employee be `is_esi_applicable=true` at a legal entity with no
`esi_code`?") remains open (§26 item 6).

---

## 11. Sensitivity Classification, RBAC, and Data-Scope Model

This section supersedes `21_` §11/§14 — the permission *naming* conclusions are unchanged, but this
revision adds the data-scope analysis `21_` could not perform (the infrastructure did not exist
when it was written).

### 11.1 Sensitivity (unchanged)

Every `employee_statutory` field is treated as RESTRICTED by the same analogy `00_EMPLOYEE_AUDIT.md
§10` and `02_EMPLOYEE_DATA_MODEL.md §2` already draw for PF/ESI/UAN alongside PAN/Aadhaar/bank — not
independently documented by name in the RBAC matrix's own RESTRICTED list, but the safer and
consistent inference. Whole-sub-resource gating, not per-field masking (§6).

### 11.2 Permission catalogue status (reconfirmed, unchanged conclusion)

Reconfirmed today against both `docs/product/19_RBAC_and_Permission_Matrix.md` (line 43, unchanged
since `21_`) and the live `permission` table (§4): the locked catalogue still names only
`EMPLOYEE.UPDATE_SENSITIVE` for statutory data — write-only, bundled across PAN/Aadhaar/bank/
statutory. **There is still no `EMPLOYEE.VIEW_STATUTORY` in the locked catalogue, in code, or in
the database.** This is a genuine, unresolved product/architecture gap, exactly as `21_` found —
re-verification changed nothing here except confirming the orphaned `UPDATE_SENSITIVE` row (§4)
does not change this conclusion, since it grants zero roles and is not wired to any route.

**Recommended** (unchanged from `21_`, re-endorsed): add `EMPLOYEE.VIEW_STATUTORY` as a new code,
gating both `GET` routes; add `EMPLOYEE.UPDATE_SENSITIVE` as a proper code constant (it is
currently a stray database row, not a code-backed permission — §4) scoped **only** to the
`employee_statutory` `POST` route, explicitly not wired to `employee`'s PAN/Aadhaar/UAN fields
(E-02) or `employee_bank` (E-08, which does not exist).

### 11.3 Data-scope posture — new analysis, not present in `21_`

The task brief is explicit: *"Do not assume that compensation scope automatically equals statutory
scope."* Here is that determination, made directly rather than by default:

**What the infrastructure actually offers today.** `require_permission(code)` (`core/rbac/
dependencies.py`) always resolves a `DataScope` for `code` from `role_permission.data_scope`,
regardless of which code is passed — the column and the resolution query are generic, not
special-cased to `EMPLOYEE.VIEW`/`.VIEW_ALL`. Whether a route *uses* the returned `DataScope` is
entirely the route's own choice: `list_employees`/`get_employee` bind it to a typed `DataScope` and
pass it into `EmployeeService.resolve_visible_employee_ids`; every other route (including both
Compensation reads) binds the identical dependency's return value to `_scope: Annotated[object,
...]` — a deliberate discard, confirmed by the router module's own docstring (§3). Nothing prevents
`EMPLOYEE.VIEW_STATUTORY` from being wired either way; the choice is a genuine design decision for
E-07, not a constraint the framework imposes.

**The three plausible postures, evaluated:**

1. **`COMPANY`-only (ignore `DataScope`), matching Compensation exactly.** Simplest, requires zero
   new plumbing beyond what E-06 already shipped, and keeps E-07 consistent with its own stated
   template ("E-07's nearest sibling... is E-06 Compensation," `21_` §1). The gap this leaves (a
   manager with `EMPLOYEE.VIEW_STATUTORY` sees every employee's PF/PAN-adjacent data company-wide,
   not just their reports') is the *same class* of gap Compensation already carries today, named and
   accepted as a known follow-up in `25_...IMPLEMENTATION_PLAN.md` §22 ("Any route other than `GET
   /employees` and `GET /employees/{id}`... remain `COMPANY`-scoped, unchanged").
2. **Wire `SELF` only** (an employee viewing their own PF number/tax regime — self-service). Plausible
   and arguably higher-value than for Compensation, but **no route in this codebase implements
   employee self-service access to their own sub-resource data today** — not Compensation, not
   Assignment, not even `employee` itself beyond the two already-scoped routes. Building `SELF`-scope
   support for Statutory alone, while Compensation (a materially similar RESTRICTED sub-resource)
   has none, would be an unexplained asymmetry, not a documented requirement. `04_EMPLOYEE_UX_PLAN.md`
   places the first usable Employee screen at E-09, after E-07 — self-service is a UI-driven need
   that does not yet have a consumer.
3. **Wire `REPORTEES`/`REPORTEE_TREE`** (a manager seeing reports' PF/PAN-adjacent data). No source
   document proposes or requires this, and it is a materially different risk than Compensation's own
   `REPORTEES` question (CTC visibility to a manager is a common, unremarkable HR pattern; PF/PAN-
   adjacent identifier visibility to a manager who is not HR is not a pattern any source document
   endorses). Recommend explicitly **against** enabling this without a product decision — the
   self-elevation-guard precedent (§1 item 2, `27_`) demonstrates this codebase already treats
   manager-linked data exposure as something to actively guard, not default open.

**Recommendation**: posture 1 — `EMPLOYEE.VIEW_STATUTORY` gates the whole sub-resource at
`COMPANY` scope only, discarding the resolved `DataScope` exactly as Compensation's routes do today
(`_scope: Annotated[object, Depends(require_permission(EMPLOYEE_VIEW_STATUTORY))]`). This is an
**engineering decision** (§27), not a blocking product question, because it inherits rather than
invents a gap, and the gap is already named and tracked as a cross-cutting follow-up
(`25_...IMPLEMENTATION_PLAN.md` §22) that a future slice can close for Statutory and Compensation
together, not separately. It should **not** be silently equated with "statutory scope was
considered and rejected" — the closeout report must name this exactly as Compensation's own report
named its read-path audit gap, not pass over it.

**List/detail placement**: unchanged from `21_` §11 — never inlined into `GET /v1/employees` or
`GET /v1/employees/{id}`, only under its own `GET .../statutory` sub-resource, matching Compensation.

---

## 12. E-07 vs. E-10 Boundary

Unchanged from `21_` §12. `sensitive_access_log` remains locked to E-10, not reopened by this
revision. E-07 can ship with the same accepted, named gap E-06 already established (no read-path
audit trail for RESTRICTED-tier reads until E-10 exists).

---

## 13. E-07 vs. Payroll Boundary

Unchanged core conclusion from `21_` §13, with one detail this revision adds from `docs/adr/
0005-payroll-snapshot-immutability.md` (the only live payroll document, not available/read in
`21_`'s own citation list beyond a general reference):

**Payroll's own documented pipeline** is: create run → **snapshot inputs** (compensation,
attendance, leave, arrears, loans, "statutory master versions" copied into an immutable
`payrun_input_snapshot`) → compute (a pure function of the snapshot) → validate → review → finalise.
This confirms precisely *where* `employee_statutory` will be consumed: **at snapshot time**, once
per pay run, not read live during computation. `get_statutory_as_of(employee_id, date)` (the
cross-module contract E-07 should expose, mirroring `get_compensation_as_of`) is therefore the
method Payroll's snapshot step will call — E-07 does not need to design for live/repeated reads
during a computation window, only for a single as-of read per employee per run. This does not change
E-07's implementation, but sharpens the contract's purpose statement in the service docstring.

Rate tables (PF %, ESI %, PT slabs, LWF amounts) remain entirely Payroll's concern, untouched by
E-07, as `21_` already established.

---

## 14. Permission Model — Implementation Detail

Restated precisely from §11.2/§11.3, in the form the implementation task needs:

- `EMPLOYEE.VIEW_STATUTORY` — **new** code, not in the locked 14-code catalogue, not in the
  database. Add as a code constant + `EMPLOYEE_PERMISSIONS` entry. Gates both `GET` routes.
  `COMPANY` scope only (§11.3) — bound to `_scope: Annotated[object, ...]`, discarded, matching
  Compensation.
- `EMPLOYEE.UPDATE_SENSITIVE` — named in the locked catalogue's write-only description, **currently
  present in the database only as an orphaned, unseeded row** (§4) — add as a proper code constant +
  `EMPLOYEE_PERMISSIONS` entry (the idempotent seed will adopt the existing row, not duplicate it).
  Gates the `POST` route only. Scope strictly limited to `employee_statutory`'s own write path — not
  wired to `employee`'s PAN/Aadhaar/UAN fields (E-02) or `employee_bank` (E-08).
- Neither code should be granted to any system role by this task beyond whatever
  `seed_b1_foundation` already grants `COMPANY_ADMIN` (which receives every seeded permission
  unconditionally, per its existing loop over `permission_rows.values()`) — no new role, and no
  change to `EMPLOYEE_VIEWER`'s existing single-permission grant.

---

## 15. Audit Model

Unchanged from `21_` §15. Mutation-only, via the existing `AuditService.record(...)` signature
(reconfirmed against every current call site in `service.py` today — `session, company_id,
actor_user_id, action, entity_type, entity_id, before, after, ip, user_agent`, unchanged). Single
event `STATUTORY_REVISED`, `entity_type="employee_statutory"`, mirroring `COMPENSATION_REVISED`
exactly. Same pre-existing, project-wide limitation applies and must be named, not silently
inherited: audit payloads are plain JSONB, unencrypted, for every entity in this codebase today, not
a new gap E-07 introduces.

---

## 16. API Design

Unchanged endpoint shape from `21_` §16, reconfirmed against the current router's exact patterns for
Compensation (read fully today, §2):

| Method | Path | Permission | Response |
|---|---|---|---|
| GET | `/v1/employees/{employee_id}/statutory` (`?as_of=YYYY-MM-DD`) | `EMPLOYEE.VIEW_STATUTORY` | `ListEnvelope[StatutoryRead]` |
| GET | `/v1/employees/{employee_id}/statutory/{statutory_id}` | `EMPLOYEE.VIEW_STATUTORY` | `DataEnvelope[StatutoryRead]` |
| POST | `/v1/employees/{employee_id}/statutory` | `EMPLOYEE.UPDATE_SENSITIVE` | `DataEnvelope[StatutoryRead]`, `201` |

Route bodies should mirror `create_compensation`'s exact current shape (§2): `tenant`,
`_scope: Annotated[object, Depends(require_permission(...))]` (§11.3), `service`, optional
`if_match: str | None = None` header. No `caller_employee_id`/`user` dependency is needed on the
write route — unlike `create_assignment`, statutory has no manager-reference field requiring the
self-elevation check (§1 item 2), so no `AuthenticatedUser`/`RbacService` dependency is required
beyond what `require_permission` already resolves.

**Request body** (`StatutoryCreate`, `extra="forbid"`): `effective_from` (required),
`is_pf_applicable` (required), `pf_number` (optional), `pf_wage_ceiling_opt_out` (default `false`),
`vpf_amount`/`vpf_percentage` (optional), `is_esi_applicable` (required), `esi_ip_number`
(optional), `pt_state_code` (optional), `is_lwf_applicable` (required), `tax_regime` (enum
`OLD`/`NEW`, required), `is_director`/`is_international_worker` (default `false`),
`revision_reason` (recommended required, for audit-trail parity with Compensation — engineering
decision, §27).

**Concurrency**: `If-Match` required only when a current row exists — matches
`create_compensation`'s exact current behavior (`if_match: Annotated[str | None, Header(alias=
"If-Match")] = None`, then `expected_version=int(if_match) if if_match is not None else None`).

**Error cases** (unchanged from `21_` §16): `404` cross-tenant/nonexistent employee; `409
NO_ACTIVE_EMPLOYMENT`; `409 STATUTORY_DATES_OVERLAP` (GiST translation); `422
INVALID_EFFECTIVE_FROM`; `422 STATUTORY_VERSION_REQUIRED`; `409 STALE_RESOURCE`; `422
TAX_REGIME_SWITCH_NOT_ALLOWED`; `403 PERMISSION_DENIED`. Every one of these has a direct, already-
shipped exception-class template in `exceptions.py` today (`CompensationDatesOverlapError`,
`CompensationVersionRequiredError`, `StaleResourceError`, `NoActiveEmploymentError`,
`InvalidEffectiveFromError`) — the new `Statutory*` classes should copy each one's exact shape.

---

## 17. Validation Rules

Unchanged from `21_` §17. `effective_from` required and GiST-enforced non-overlapping. Tax-regime
once-per-FY switch rule (FR-PAY-006) named but its FY boundary is not defined by any document — do
not hard-code April–March without flagging it as an assumption (§26 item 5). Applicability/
identifier correlation (`is_esi_applicable=true` implying `esi_ip_number IS NOT NULL`) and
legal-entity-registration correlation both remain open, undocumented questions (§26 items 6–7).
`extra="forbid"` mass-assignment protection, matching every other Create schema in this module.

---

## 18. Tenant/RLS Model

Unchanged, reconfirmed against the live `employee_compensation` RLS policy today (§4):
`ENABLE`/`FORCE ROW LEVEL SECURITY` + single `tenant_isolation` policy on `company_id`, app-level
`set_config('app.company_id', ...)`, repository-level `company_id` filter as belt-and-suspenders,
cross-tenant → `404` never `403`.

---

## 19. Concurrency

Unchanged from `21_` §16's concurrency note: `If-Match` required only when a current row exists,
`409 STALE_RESOURCE` on mismatch, `422 STATUTORY_VERSION_REQUIRED` when missing and a current row
exists. No separate concurrency design needed — this is the exact, already-shipped
`close_compensation`/version pattern.

---

## 20. Data Model — Implementation Sequence Detail

Building on §7's DDL and §4's finding that this is a genuine `CREATE TABLE`, not an additive
`ALTER TABLE`:

1. `EmployeeStatutory` ORM model in `models.py`, keyed on `employee_id`, matching
   `EmployeeCompensation`'s exact shape/docstring convention (§7 of `models.py`, read in full today).
2. `EmployeeStatutoryRepository` in `repository.py`: `insert_statutory`, `get_current_statutory`,
   `get_statutory_as_of`, `list_statutories`, `get_statutory`, `close_statutory` — a
   method-for-method mirror of `EmployeeCompensationRepository` (§4 of `repository.py`, read in full
   today; every method signature above is a direct copy target).
3. `StatutoryCreate`/`StatutoryRead` schemas + `statutory_to_audit_dict`/`statutory_to_read` in
   `schemas.py`.
4. Service-layer `EmployeeStatutoryService` in `service.py`: `create_revision` (covering-employment
   check via `EmploymentRepository.get_employment_as_of`, close-current-then-insert, tax-regime-
   once-per-FY validation, audit call), `get_current`, `get_as_of`, `list`.
5. Router routes in `router.py` per §16.
6. New exception classes in `exceptions.py` per §16's error-case table.
7. `dependencies.py`: `get_employee_statutory_service`, mirroring the four existing factory
   functions exactly.
8. `permissions.py`: add `EMPLOYEE_VIEW_STATUTORY`/`EMPLOYEE_UPDATE_SENSITIVE` constants +
   `EMPLOYEE_PERMISSIONS` entries (§14) — this is also what makes `seed_b1_foundation` adopt the
   orphaned database row cleanly (§4).
9. One Alembic migration per §7's DDL, structured as a foundational `CREATE TABLE` (§4), not an
   additive `ALTER TABLE`.

---

## 21. Test Strategy

Unchanged core plan from `21_` §20, retargeted against the current test file this module actually
has today (`apps/api/tests/integration/modules/employee/test_employee_compensation.py`, the direct
template) plus the new `test_employee_data_scope.py` (confirms the pattern for constructing
scope-bearing roles, even though §11.3 recommends Statutory not use non-`COMPANY` scope itself).

**Functional**: create (first row, no `If-Match`); create (revision, closes current, requires
`If-Match`); read (current, `as_of`, full history, single-by-id); list ordered by `effective_from`.

**Validation**: GiST overlap rejected at the DB level (bypass RLS with `SET LOCAL row_security =
off`, assert `IntegrityError`, matching the compensation test's own proof pattern, not just an
application-level check); `effective_from` before joining date / no covering employment →
`409 NO_ACTIVE_EMPLOYMENT`; mass-assignment (`version`/`company_id`/`id` in body) → `422`;
tax-regime switch within assumed FY → `422 TAX_REGIME_SWITCH_NOT_ALLOWED`.

**Security/permissions**: caller with only `.VIEW_STATUTORY` reads, cannot write; caller with only
`.UPDATE_SENSITIVE` writes, sub-resource absent on read without `.VIEW_STATUTORY`; caller with
neither → `403`/absent. Cross-tenant GET/POST → `404`. RLS proven directly at the DB layer.
**New, not in `21_`**: an explicit test asserting `EMPLOYEE.VIEW_STATUTORY` remains `COMPANY`-scoped
even when a role grants it with `data_scope='SELF'`/`'REPORTEES'` in `role_permission` — i.e., a
positive proof that §11.3's chosen posture (discard `DataScope`) actually holds, not merely assumed.
This is the direct counterpart to `test_employee_data_scope.py`'s own tests for the two routes that
*do* enforce scope, applied here to prove the negative for the one that deliberately does not.

**Sensitive-field protection**: `pf_number`/`esi_ip_number`/`tax_regime`/etc. absent (not null) from
any response when the caller lacks `.VIEW_STATUTORY` — raw-JSON assertion, matching
`docs/product/19_RBAC_and_Permission_Matrix.md §8`'s mandated check shape for every RESTRICTED field.

**Concurrency**: stale `If-Match` → `409`; missing `If-Match` with a current row → `422`.

**Rehire**: exit → last row closed; rehire → new row against same `employee_id`; old rows remain
queryable, unmerged; `employee.uan_number` (read from `employee`, unaffected by this module) is
unchanged by the rehire.

**Audit**: exactly one `AuditLog` row per write, `action=="STATUTORY_REVISED"`,
`entity_type=="employee_statutory"`, `before_json is None` on first write.

**Payroll boundary**: no test in this suite should exercise or reference any calculation, rate
table, or `payrun_*` construct — a negative test confirming `get_statutory_as_of` returns raw data
only, consistent with §13's snapshot-time-only consumption model.

---

## 22. Concurrency & Optimistic Locking — Cross-check

Confirmed by reading `EmployeeCompensationRepository.close_compensation` in full today: the
`UPDATE ... WHERE version = :expected_version ... RETURNING` pattern is the sole optimistic-lock
mechanism, with `None` meaning either a stale version or a vanished row (disambiguated by a
follow-up read). `EmployeeStatutoryRepository.close_statutory` should copy this exact SQL shape —
no new locking primitive needed.

---

## 23. Frontend Implications

Unchanged from `21_` §19 — out of scope for this investigation, no frontend code or research was
performed. `01_EMPLOYEE_MODULE_PLAN.md` places E-07's eventual UI as a sub-section within the
Compensation tab, pending the permission-naming decision (§11) and E-09 (the first usable Employee
screen) existing to host it. For the future UI's own planning purposes only: it will need to (a)
show/hide the entire statutory section based on `EMPLOYEE.VIEW_STATUTORY`, (b) gate the edit action
on `EMPLOYEE.UPDATE_SENSITIVE`, (c) require a `revision_reason` field on every write, (d) surface
`409`/`422` error codes from §16 as field-level messages, (e) since §11.3 recommends `COMPANY`-only
scope, the UI does not need to design for a partial/masked statutory view — it is binary
(full section, or none).

---

## 24. Security Risks

1. **No read-path audit trail until E-10** — same accepted, already-precedented gap as Compensation
   (§12), not new to E-07, must be named in its closeout report.
2. **Unencrypted audit payloads** — pre-existing, project-wide (§15), not unique to E-07.
3. **Inferred sensitivity classification** — no document explicitly places PF/ESI/tax-regime fields
   in the RESTRICTED tier by name (§6, §11.1).
4. **`COMPANY`-only data-scope posture (§11.3) is a deliberate, named gap, not an oversight** — but
   it must be named exactly that way, not silently inherited as if Compensation's precedent settles
   the question on its own. A future reviewer who assumes E-07 "just follows E-06" without reading
   §11.3 could miss that this was an explicit, considered choice with two rejected alternatives.
5. **The orphaned `EMPLOYEE.UPDATE_SENSITIVE` database row (§4)** is a small but real hygiene risk:
   if a future task grants it to a role directly via `psql` or an ad hoc script (as whatever produced
   it evidently did once already) before E-07 wires a route to it, that grant would be silently inert
   today (no route checks this code) but would become live and unreviewed the moment E-07 ships the
   `POST` route — a namespace collision risk between "this task's careful permission rollout" and
   "leftover manual test data," not a security hole by itself but worth a one-line check at
   implementation time (confirm zero roles hold it immediately before wiring the route).
6. **India-only assumption remains unconfirmed** (`docs/product/26_Risk_Register...md` Q1/A1),
   unchanged from `21_` §24 item 4 — affects the FY-boundary assumption and the entire India-specific
   field set if ever revisited.
7. **`pf_number` rehire behavior remains genuinely undecided** (§9, §26 item 4).

---

## 25. Migration Strategy

Unchanged plan from `21_` §21, refined by §4/§20's finding that this is a foundational `CREATE
TABLE`: one new Alembic migration — table + GiST constraint + two indexes + RLS (idempotently
asserted) — no `ALTER TABLE` on any other Employee table. Permission seeding
(`EMPLOYEE_VIEW_STATUTORY`/`EMPLOYEE_UPDATE_SENSITIVE`) happens through `EMPLOYEE_PERMISSIONS` +
`seed_b1_foundation`, the same mechanism every prior slice used — not a new mechanism, and not a
raw `INSERT` in the migration itself (permissions are seeded by the seed script, not by migrations,
confirmed by every existing migration in this series containing zero `INSERT INTO permission`
statements).

**Rollback**: purely additive at the schema level (`CREATE TABLE` → `DROP TABLE` on downgrade,
standard for a genuinely new table with a genuinely new business meaning — unlike Compensation's
`ADD COLUMN`/`DROP COLUMN` reversibility, a `DROP TABLE` downgrade is safe only if no data has been
written yet, which will be true immediately after this migration ships and remains E-07's own
concern to re-verify before any downgrade is actually run in a populated environment).

---

## 26. Product Decisions

Genuine decisions requiring explicit sign-off:

1. **Exact permission code literal names** (`EMPLOYEE.VIEW_STATUTORY` is the carried-forward
   recommendation, `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` A9/B9's own framing: "safe to finalize
   immediately... not a blocker"). Non-blocking.
2. **Data-scope posture for `EMPLOYEE.VIEW_STATUTORY`** (§11.3) — this document recommends
   `COMPANY`-only, explicitly rejecting `SELF`/`REPORTEES`/`REPORTEE_TREE` without a documented
   requirement. Non-blocking, but flagged more prominently than in `21_` since the infrastructure to
   do otherwise now exists and a reviewer could reasonably ask why it isn't used.
3. **Masking format (if any)** for `pf_number`/`esi_ip_number`/`pt_state_code`/`tax_regime`. No
   format specified anywhere; recommended default is whole-resource gating, no masking.
4. **`pf_number` carry-forward on rehire.** Undecided by any document (§9).
5. **Fiscal-year boundary** for the once-per-FY tax-regime-switch rule (FR-PAY-006). April–March is
   a reasonable India-centric assumption, not a documented constant.
6. **Applicability/identifier correlation rules** — whether `is_pf_applicable`/`is_esi_applicable`
   should hard-require their corresponding number fields.
7. **Legal-entity-registration correlation** — whether applicability should be validated against the
   employing legal entity's own PF/ESI registration (§10).
8. **Encryption at rest** for `employee_statutory` fields — not currently required by any document;
   a compliance posture question, not decided here.

---

## 27. Engineering Decisions

Safe to proceed without further sign-off:

1. `employee_statutory` excludes a `uan` column (§5).
2. `NO_ACTIVE_EMPLOYMENT` covering-employment check on every write, by direct analogy to Assignment
   and Compensation.
3. `If-Match` required only when a current row exists, matching Compensation's actual shipped
   behavior.
4. Audit action `STATUTORY_REVISED`, `entity_type="employee_statutory"`.
5. No separate history table — in-table effective-dating, matching every sibling.
6. Static 1:1 route-to-permission wiring, no dynamic permission selection (unlike Assignment).
7. `revision_reason` required on every write.
8. No per-field masking; whole sub-resource gated.
9. `EMPLOYEE.UPDATE_SENSITIVE`'s scope in E-07 strictly limited to the `employee_statutory` `POST`
   route.
10. **New**: `EMPLOYEE.VIEW_STATUTORY` discards its resolved `DataScope`, remaining `COMPANY`-scoped
    — the specific implementation of decision §26 item 2's recommended default (§11.3).
11. **New**: the orphaned `EMPLOYEE.UPDATE_SENSITIVE` database row (§4) is adopted, not deleted or
    worked around — adding the proper code constant lets the existing idempotent seed logic claim it
    cleanly, with a one-line pre-flight check (§24 item 5) that it is not already granted to any role.

---

## 28. Explicit Exclusions

Restated from the task's own strict exclusions, confirmed still applicable after this investigation:
Banking/E-08 (confirmed non-existent, §2), Payroll (confirmed only ADR-0005 exists, consumed
read-only via §13's contract), Attendance, Leave, Exit, ATS, Recruitment, Performance, Workflow,
Employee frontend, E-10's `sensitive_access_log` implementation, new RBAC scope levels (`DEPARTMENT`/
`BRANCH`/`LEGAL_ENTITY`/`ALL_COMPANIES` — confirmed still absent from `DataScopeLevel`, §4), tax
calculation, payroll calculation, approval workflows, undocumented statutory fields.

---

## 29. Acceptance Criteria & Implementation Sequence

**Acceptance criteria** (unchanged from `21_` §26, reconfirmed applicable):
- `employee_statutory` exists in the live schema exactly per §7, RLS forced and proven by a
  DB-level test.
- All three endpoints (§16) implemented, permission-gated per §14, `COMPANY`-scoped per §11.3.
- Every test in §21 passes, including the GiST-overlap proof and the rehire scenario.
- `EMPLOYEE.VIEW_STATUTORY`/`EMPLOYEE.UPDATE_SENSITIVE` seeded via `EMPLOYEE_PERMISSIONS` +
  `seed_b1_foundation`, not via a raw insert — and the pre-existing orphaned row (§4) is confirmed
  ungranted before the route ships.
- `STATUTORY_REVISED` audit event fires exactly once per write.
- No `sensitive_access_log` work attempted.
- Closeout report names every flagged assumption (§26) as an assumption, and explicitly names the
  data-scope posture (§11.3) and the orphaned-permission finding (§4) as things this task discovered
  and handled, not silently absorbed.
- No changes to `employee`, `employment`, `legal_entity`, or `employee_compensation` schemas.

**Implementation sequence**: §20, in order, preceded by confirming (or flagging and defaulting on)
§26 items 1–2 with product if a fast answer is available.

---

## 30. Final Readiness Assessment

**READY TO IMPLEMENT, with flagged assumptions.**

No architectural blocker exists, and none of the changes since `21_` (RBAC data-scope, the
reporting-manager guard) introduce one — they add one genuine new design question (§11.3, the
data-scope posture) which this document resolves with a recommended default and a named,
non-blocking rationale, following the same discipline `21_` itself followed for the permission-
naming gap. The `employee_statutory` table still does not exist (§4); its DDL is unchanged and
fully specified (§7); the Employee/Legal-Entity boundary, effective-dating mechanics, and Payroll
boundary remain decided and unreopened (§8–§10, §13).

**What a re-verification pass added that `21_` could not have known**: the RBAC data-scope
infrastructure now exists but E-07 should deliberately not use it beyond `COMPANY` scope (§11.3);
one orphaned, non-code-backed permission row already sits in the live database and must be adopted
rather than duplicated or ignored (§4); and Payroll's own snapshot-pipeline document sharpens
exactly when `get_statutory_as_of` will be called (§13).

**First action for the implementing agent**: confirm §26 items 1–2 with product if a fast answer is
available; if not, proceed with this document's recommended defaults (`EMPLOYEE.VIEW_STATUTORY`,
`COMPANY`-only scope) and flag both explicitly in the closeout report, exactly as this document does.
