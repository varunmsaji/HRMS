# Employee Vertical — Production Readiness & Security Audit

**Date:** 2026-08-16
**Status:** Audit only. No application code, migration, test, or database change was made to produce
this document.
**Scope:** Employee Foundation, Employment Lifecycle, Assignment, Shift, Compensation, Statutory,
Banking, RBAC/data-scope, the Employee frontend, and their combined readiness to serve as the
foundation for Attendance, Leave, and Payroll.

**Method — how this audit differs from prior ones.** A prior document
(`docs/modules/employee/37_EMPLOYEE_DOMAIN_INTEGRATION_AUDIT.md`) already made extensive claims
about this system. Per explicit instruction, **that document's claims were not trusted** — every
finding below was independently re-derived this session by five parallel research passes, each
reading the actual current working-tree code (`git status` shows the Employee module, its
migrations, and its tests are largely uncommitted/modified — this audit read the working tree, not
git history), running the real test suite against the live dev database
(`postgresql://hrms:***@localhost:5433/hrms_dev`), and querying that database directly. Two
material discoveries in this session were **not** present in any prior document:

1. The application's Postgres connection role is a **superuser with `BYPASSRLS`**, which makes
   every Row-Level-Security policy in the schema a complete no-op — a strictly more severe finding
   than the "RLS-timing" observation in the prior audit, which assumed RLS was a working backstop
   and only questioned *when* its GUC was set.
2. **Compensation has the identical "resolve-then-discard" data-scope bug previously attributed
   only to Statutory** — the prior audit's own data-scope matrix listed Compensation as merely
   "not yet scope-narrowed" without identifying that the resolved scope is actively computed and
   then thrown away, in direct contradiction of a second LOCKED architecture decision.

Every finding carries a severity (P0–P3), file:line evidence, an explicit affected module, and an
explicit statement of whether it blocks Attendance, Leave, Payroll, and/or production.

---

## 1. Executive Summary

The Employee vertical (Identity → Employment → Assignment → Shift → Compensation → Statutory →
Banking, plus its RBAC/data-scope layer and its new frontend) is **functionally rich and, at the
core lifecycle level, genuinely well-built** — this was independently re-verified this session, not
assumed. Mass-assignment protection, tenant-filtered queries, race-safe employee-code allocation,
optimistic concurrency (version + `If-Match` → 409), GiST-enforced non-overlapping effective-dated
history, and atomic multi-table termination were all confirmed by reading the actual code and by
running the actual tests (not by trusting a prior report's numbers). The reporting-manager
self-elevation guard is real, tested, and closes a genuine privilege-escalation vector. The newly
built frontend mirrors the backend contract field-for-field and enum-for-enum with zero drift found
anywhere, and its `If-Match` handling is correct on every one of its 7 write call sites.

**It is not production-ready**, for reasons that go beyond what any prior document identified:

- **P0 — Row-Level Security provides zero actual protection.** The application's database role is
  a Postgres superuser with `rolbypassrls = true`. Per Postgres semantics this means every
  `FORCE ROW LEVEL SECURITY` policy on every tenant table (`employee`, `employment`,
  `employee_assignment`, `employee_compensation`, `employee_statutory`, `employee_bank`) is
  silently ignored for the app's own connection. This was proven empirically this session, not just
  read from configuration: a live request with no tenancy GUC set at all still returned correct,
  isolated data — solely because every repository method happens to also add an explicit
  `WHERE company_id = ...` filter by hand. Tenant isolation today is **100% application-code
  discipline with no database-level backstop whatsoever**. See §10, Finding F1.
- **P1 — Two RESTRICTED-tier resources silently discard the RBAC scope they resolve.** Both
  Statutory (previously flagged) and **Compensation (newly found this session)** compute a
  caller's `SELF`/`REPORTEES`/`REPORTEE_TREE`/`COMPANY` scope on every `GET`, bind it to a variable,
  and never pass it into the query — meaning any future role granted, say, `SELF`-scoped
  `EMPLOYEE.VIEW_STATUTORY` (the exact configuration this project's own **locked** architecture
  decision recommends as the default) silently becomes company-wide access to PF/ESI/tax/director
  data. Compensation's version of the bug contradicts a second locked decision recommending
  `REPORTEES` scope for manager compensation visibility. See §5, §9, Findings F2/F3.
- **P1 — Bank account numbers are genuinely, verifiably plaintext**, with no encryption mechanism
  anywhere in the codebase (grepped for every common crypto primitive — zero hits besides a code
  comment admitting the gap). This is a known, named, previously-accepted risk, but it remains
  fully unresolved and is a hard, already-self-imposed precondition for Payroll. See §6, Finding F4.
- **P1 — the test suite is non-deterministic.** A shared, function-scoped fixture that seeds global
  `Plan` catalogue rows with no per-test transaction isolation causes order-dependent
  `ForeignKeyViolationError`s that cascade into unrelated tests. Reproduced 4 times this session
  with 4 different pass/fail counts for the identical command against identical code — including
  one **false** `FAILED` in a Statutory test caused purely by fixture pollution. No "N/N tests
  pass" claim — in this document or any prior one — can be trusted as a stable signal until this is
  fixed. See §13, Finding F6.
- **P1 — the RBAC data-scope engine remains fully built, well-tested in isolation, and completely
  unreachable in production.** Re-confirmed this session: every `RolePermission` insertion path in
  the live codebase omits `data_scope`, defaulting to `COMPANY`; the live database has 66/66
  `role_permission` rows at `COMPANY` scope (correcting the prior audit's stated count of 24). See
  §5, Finding F5.
- **P1 — no read-path audit log (`sensitive_access_log`) exists anywhere in code**, confirmed by a
  repository-wide grep returning zero `.py` hits (only documentation references). Three
  RESTRICTED-tier read surfaces (Compensation, Statutory, Banking) have now shipped with no record
  of who read them. See §12, Finding F7.

**Bottom line:** Attendance and Leave can begin building against this vertical's stable,
well-tested `*_as_of` contracts today, but Leave's core approval-routing capability is blocked until
role-seeding (F5) ships, and role-seeding must not ship before the read/write scope gaps (F2, F3,
F8, F9) are closed, or it will immediately activate a live data-exposure bug. Payroll should not
begin against real data until the plaintext-banking (F4) and audit-logging (F7) gaps are resolved —
both are this project's own already-self-imposed conditions, re-confirmed unmet. No module should
be considered production-ready with real employee data until the P0 database-role finding (F1) is
fixed, since it is a single point of failure underneath every tenant-isolation guarantee this audit
otherwise confirms is correctly implemented in application code.

---

## 2. Current Employee Architecture

Six tables, three data shapes, layered under `hrms.core` (RBAC, audit, tenancy, db session) per a
one-way `hrms.modules → hrms.shared → hrms.core` import-linter contract:

1. **Identity, once** — `employee` (permanent `id`/`employee_code`, survives rehire).
2. **Spell-scoped, non-overlapping** — `employment` (one row per continuous stay at a legal entity;
   `previous_employment_id` self-link on rehire; GiST-enforced at most one `ACTIVE` row per
   employee).
3. **Effective-dated, insert-only, `employee_id`-keyed (not `employment_id`)** —
   `employee_assignment`, `employee_compensation`, `employee_statutory`, `employee_bank`. Each has
   its own GiST no-overlap exclusion constraint and its own `version` column; the only allowed
   mutation after insert is closing the current row via `effective_to` — confirmed structurally
   (no `update_*` method exists on any of the four repositories, verified by direct code read this
   session, not assumed from a docstring).

```mermaid
erDiagram
    EMPLOYEE ||--o{ EMPLOYMENT : "employee_id (spells)"
    EMPLOYEE ||--o{ EMPLOYEE_ASSIGNMENT : "employee_id (effective-dated)"
    EMPLOYEE ||--o{ EMPLOYEE_COMPENSATION : "employee_id (effective-dated)"
    EMPLOYEE ||--o{ EMPLOYEE_STATUTORY : "employee_id (effective-dated)"
    EMPLOYEE ||--o{ EMPLOYEE_BANK : "employee_id (effective-dated)"
    EMPLOYMENT ||--o| EMPLOYMENT : "previous_employment_id (rehire link)"
    EMPLOYEE_ASSIGNMENT }o--o| BRANCH : ""
    EMPLOYEE_ASSIGNMENT }o--o| SHIFT : ""
    EMPLOYMENT }o--|| LEGAL_ENTITY : ""
```

No `employment_id` FK exists on any of the four effective-dated sub-resources — confirmed
deliberate (verified consistent across all four models' docstrings and DDL this session), and this
is what makes rehire correct without orphaned-FK handling: a rehire gap simply produces zero rows
during the gap, at the cost of nothing at the database level preventing a sub-resource row from
being dated inside a gap where no employment was active (enforced only in the service layer via
`NoActiveEmploymentError`).

---

## 3. Module-by-Module Status

| Module | Status | Confidence |
|---|---|---|
| Employee Identity | Solid — mass-assignment blocked, tenant-filtered, race-safe code allocation, correct optimistic concurrency, correct audit events. One P2 gap (no pagination). | Re-verified against live code + passing tests this session |
| Employment | Solid — GiST-enforced no-overlap, DB-level CHECK constraints, atomic multi-table termination proven by a real rollback test (not mocked), correct rehire linkage. | Re-verified, real test run confirms rollback behavior |
| Assignment | Solid — effective dating, overlap prevention, and the reporting-manager self-elevation guard are all real and tested with non-tautological assertions. | Re-verified, 3 regression tests run directly and passed |
| Shift | Solid, one deliberate-but-flaggable behavior (inactive shifts remain assignable, consistent with sibling fields, explicitly tested). | Re-verified |
| Compensation | **Two-tier finding**: lifecycle mechanics (effective dating, termination, rehire, audit) are solid; **data-scope enforcement on GET is broken (F3, newly found)**. | Re-verified |
| Statutory | **Two-tier finding**: lifecycle mechanics solid; **data-scope enforcement on GET is deliberately, but riskily, absent (F2)**. | Re-verified |
| Banking | Mechanically the most correct sub-resource for RBAC (the only one that gets SELF-scope right) but carries the vertical's single worst sensitive-data finding (F4, plaintext account numbers, no encryption anywhere). | Re-verified |
| RBAC/Data-scope engine | Well-built and well-tested in isolation; **completely unreachable in production** (F5) and **only partially wired even where reachable** (F8, F9). | Re-verified against live DB queries this session |
| Frontend (E-09) | Correct backend-contract mirroring (schema fields, enums) with zero drift found; consistent 403 handling; correct `If-Match` sourcing on all 7 write paths. Real but non-security gaps in 422 mapping completeness and 409-recovery-UI consistency. | Re-verified against live source this session |
| Database | Migration-linear, GiST/CHECK constraints genuinely present — but **RLS is inert (F1)**, and two tables are missing a `company_id` FK present on their siblings (F17, P3). | Re-verified via live queries this session |
| Tests | 290 Employee-specific tests exist and individually pass; **full-suite runs are non-deterministic (F6)** due to shared fixture state, which is a genuinely new finding this session. | Re-run 4 times this session with 4 different outcomes |

---

## 4. API Security Audit

Every route in `apps/api/src/hrms/modules/employee/router.py` requires `Depends(get_tenant_context)`
(cross-validates `X-Company-Id` against the JWT's own `company_id`, 404s on mismatch — confirmed
this session the header can never override the JWT-derived company) and a `require_permission(...)`
dependency. Permission-to-route mapping was re-verified directly against `router.py` this session
and matches the codes actually referenced in `permissions.py` (not merely what a docstring claims).

**Mass-assignment protection (confirmed-good).** `EmployeeCreate`/`EmployeeUpdate`
(`apps/api/src/hrms/modules/employee/schemas.py:48-80`) use `model_config = ConfigDict(extra="forbid")`
and expose no `id`/`company_id`/`employee_code`/`status`/`version` fields. Test
`test_create_employee_mass_assignment_rejected` posts these fields and asserts `422` — confirmed
passing this session.

**Optimistic concurrency (confirmed-good, uniform).** All six mutable resources use the identical
`UPDATE ... WHERE version = :expected ... RETURNING` → `None` → re-fetch → `409 STALE_RESOURCE`
(with the fresh row embedded) pattern. `If-Match` is required by the router whenever a current row
exists.

**IDOR/enumeration behavior (confirmed, but inconsistent — see §5 for the scope dimension).** Every
route that does apply data-scope filtering collapses "out of scope," "cross-tenant," and
"nonexistent" into the identical `404` response shape (verified via
`test_scoped_actor_forged_id_returns_not_found` and
`test_scoped_actor_cannot_access_cross_tenant_employee`, both passing). The routes that do **not**
apply scope filtering (§5) still correctly 404 on cross-tenant/nonexistent IDs — the gap is scope,
not tenant, isolation on those routes.

---

## 5. RBAC / Data-Scope Audit

**Resolution mechanism (confirmed-good in isolation).**
`EmployeeService.resolve_visible_employee_ids` (`service.py:91-138`) unions ID sets per granted
scope level — `COMPANY` short-circuits to unfiltered, `SELF` adds the caller's own `employee_id`,
`REPORTEES` calls a one-level query (`repository.py:264-278`), `REPORTEE_TREE` walks a genuine
recursive CTE (`repository.py:280-320`). Multi-role union semantics are correct and tested
(`test_multi_role_union_sees_self_and_reportees` passes). A `SELF`-scoped caller with no linked
`employee_id` fails closed to an **empty set** (never falls back to `COMPANY`), confirmed by a
passing test.

**Finding F5 — [P1] Role-seeding gap re-confirmed.**
Grepped every `RolePermission`-inserting code path (`hrms/seed/bootstrap.py:178-190`,
`organisation/repository.py:134`) — none pass `data_scope`, so every grant defaults to the column's
`DEFAULT 'COMPANY'`. Live query this session: **66 of 66** `role_permission` rows are `COMPANY`
scope (correcting the prior audit's stated count of 24 — the qualitative "all COMPANY" claim was
right, the count was wrong). Only `COMPANY_ADMIN` (21 codes) and `EMPLOYEE_VIEWER` (`EMPLOYEE.VIEW`
only) hold any grant at all. `RBAC_DATA_SCOPE_DECISIONS.md` Decision H's three proposed roles
(`EMPLOYEE` self-service, `REPORTING_MANAGER` `REPORTEE_TREE`, `HR_ADMIN`) remain unseeded.
**Why it matters:** the entire resolver/self-elevation-guard/Banking-SELF-default apparatus is real
and tested but inert — nobody but an admin can do anything in this domain today.
**Affected module:** RBAC core, all of Employee.
**Recommended action:** seed the three roles per Decision H — but only *after* F8/F9 are closed (see
below), or seeding activates a live data-exposure bug rather than fixing one.
**Blocks:** Leave (directly — approval routing needs a real `REPORTING_MANAGER` role). Attendance
(partially — manager-visibility use cases only). Payroll: no direct dependency. Production: blocks
self-service/manager use cases specifically, not the admin-operated baseline.

**Finding F2 — [P1] Statutory GET routes resolve `DataScope` and discard it.**
`router.py:459-483`: `list_statutories`/`get_statutory` bind the resolved scope to `_scope`
(underscore — unused) and never pass it to `EmployeeStatutoryService`, whose methods
(`service.py:1424-1450`) and repository (`repository.py:515-617`) take no scope parameter at all —
every query is `company_id` + `employee_id` (from the URL), full stop. **Proven live, not
theoretical:** `test_view_statutory_ignores_non_company_data_scope`
(`tests/integration/modules/employee/test_employee_statutory.py:1062-1096`) is a *positive*
assertion that a caller granted `EMPLOYEE.VIEW_STATUTORY` at `SELF` scope with no linked employee
can successfully read another employee's full PF/ESI/tax/director record — ran this test in
isolation this session, it passes. This directly contradicts `RBAC_DATA_SCOPE_DECISIONS.md`
Decision E (**LOCKED**), which specifies `SELF` scope as the intended default for exactly this
resource.
**Why it matters:** the moment any tenant configures a role with `SELF`-scoped
`EMPLOYEE.VIEW_STATUTORY` — the configuration the project's own locked decision recommends — that
role silently gets company-wide access to RESTRICTED PF/ESI/tax/director data. No default seed
role holds this permission today (confirmed via grep), so there is no live exploit path yet — but
the gap activates the instant F5 is addressed for this specific permission, or any tenant-admin
configures it via a future role-management UI.
**Affected module:** Statutory (E-07). **Recommended action:** wire `scope`/`caller_employee_id`
through to the repository exactly as Banking does (§6), or make role-assignment reject a non-`COMPANY`
grant for this permission until the code is fixed, so misconfiguration fails loud instead of silently
widening. **Blocks:** Payroll (yes — RESTRICTED tier). Leave/Attendance: no direct coupling. Production:
yes, the moment any non-`COMPANY` grant for this permission exists.

**Finding F3 — [P1] Compensation GET routes have the identical bug — newly discovered this session.**
`router.py:390,409` binds `_scope` (discarded) for `list_compensations`/`get_compensation`;
`service.py:1239-1276` takes no scope parameter — same pattern as F2, independently found by reading
the code rather than by re-checking a claim from the prior audit (which had listed Compensation
only as "not yet scope-narrowed," not identified the resolve-then-discard mechanism). This
contradicts `RBAC_DATA_SCOPE_DECISIONS.md` Decision F, which recommends `REPORTEES` scope for
manager compensation visibility. **Same severity, mechanism, and remediation as F2** — treat both
as one coordinated fix, since the shared root cause (a `_scope` variable computed and then ignored)
suggests a copy-paste-shaped defect that could recur in future sub-resources unless the pattern
itself is corrected (see §17).

**Finding F8 — [P2] Data-scope is enforced on only 4 of 12 GET routes.**
Verified route-by-route this session:

| Route | Scope applied? |
|---|---|
| `GET /employees` | Yes |
| `GET /employees/{id}` | Yes |
| `GET /employees/{id}/bank`, `GET .../bank/{id}` | Yes |
| `GET .../employments`, `.../employments/{id}` | No |
| `GET .../assignments`, `.../assignments/{id}` | No |
| `GET .../compensation`, `.../compensation/{id}` | No (F3) |
| `GET .../statutory`, `.../statutory/{id}` | No (F2, deliberate) |

**Why it matters:** this is a dormant IDOR pattern wider than F2/F3 alone — even after F2/F3 are
fixed, Employment and Assignment history would still be fully readable by ID regardless of scope.
Currently unreachable (no live grant is non-`COMPANY`), but it will be a real hole the day F5 ships
without this also being fixed. **Recommended action:** apply the same scope-passing fix to
Employment/Assignment routes as part of the same coordinated change as F2/F3, before F5.
**Blocks:** Leave, Payroll (Compensation is one of the eight). Production: only in combination
with F5.

**Finding F9 — [P2] Write-path data-scope does not exist anywhere.**
Every `POST`/`PATCH`/`DELETE`/`terminate` route is gated by permission alone, company-wide, for
every resource — re-confirmed unchanged this session. Same activation condition and blocking
profile as F8; should be closed in the same pass, before F5.

**Finding F23 — [P3] `REPORTEE_TREE` recursion is depth-capped, not cycle-detected.**
`repository.py:25`: `REPORTEE_TREE_MAX_DEPTH = 20`, applied as `tree.c.depth < max_depth` inside the
recursive CTE step. A genuinely cyclic reporting hierarchy (A→B→A) is silently truncated at depth
20 rather than rejected or flagged. Confirmed non-hanging via a passing test
(`test_reportee_tree_scope_terminates_on_cyclic_hierarchy`). The most direct 2-node cycle is already
blocked by the self-elevation guard (Assignment can't name the caller as their own manager), but a
longer cycle assembled via legitimate third-party reassignments is theoretically possible and would
silently truncate rather than surface as a data-integrity error. **Recommended action:** low
priority; consider an explicit cycle-detection guard or at minimum an alert when the depth cap is
hit. Does not block any module.

---

## 6. Sensitive-Data Audit

| Field | Storage | Encrypted? | Permission | Data scope applied? | Masked? | In audit log? |
|---|---|---|---|---|---|---|
| `employee_bank.account_number_enc` | `TEXT`, plaintext | **No — confirmed, see F4** | `VIEW_BANKING` / `UPDATE_SENSITIVE` | **Yes** (the one correct case) | Client-render only; full value transits the network | Yes, plaintext (F11) |
| `employee_statutory.pf_number`, `esi_ip_number` | plain `VARCHAR` | N/A (not claimed encrypted) | `VIEW_STATUTORY` / `UPDATE_SENSITIVE` | **No — F2** | No | Yes, plaintext (F11) |
| `employee_compensation.annual_ctc_minor` | `BIGINT` | N/A | `VIEW_COMPENSATION` / `UPDATE_COMPENSATION` | **No — F3** | No | Yes, raw CTC (F11) |
| `employee.pan_number_enc`, `aadhaar_number_enc`, `uan_number` | `TEXT`/`VARCHAR`, plaintext | No | N/A | N/A | N/A | N/A |
| `employee.personal_email`, `personal_mobile` | plain columns | N/A | `EMPLOYEE.VIEW` only (no dedicated gate) | No | No | Yes |

**Finding F4 — [P1] `account_number_enc` is genuinely plaintext; no encryption exists anywhere in
the codebase.** Migration DDL (`alembic/versions/20260815140000_employee_bank.py:52`):
`"account_number_enc" TEXT` — no `pgcrypto`, no column-level encryption. Model
(`models.py:262`): plain `String`, nullable. A repository-wide grep for
`fernet|kms|encrypt|decrypt|pgcrypto|cryptography\.|Crypto\.|AES|cipher` across `apps/api/src`
returned **zero** hits besides the model's own docstring admitting the gap. Confirmed against a
live row: a 12-character value is stored exactly as submitted. The `_enc` suffix is aspirational
naming only. **Why it matters:** real bank account numbers, once entered, sit in cleartext at rest,
transit the network in cleartext (frontend masking is render-only, confirmed by the frontend audit
— §7), and are duplicated in cleartext into `audit_log` on every write (F11). This is a
previously-named, accepted risk (`HRMS_SYSTEM_DESIGN_BASELINE.md` Decision D-2), not a silent
oversight — but it remains fully unresolved. **Affected module:** Banking (E-08).
**Recommended action:** resolve Decision D-2's encryption mechanism before any real account number
is entered. **Blocks:** Payroll — explicitly, this project's own baseline document already states
encryption "must land before real PAN-adjacent/statutory data is written," and Payroll is the first
module that would need to read real account numbers to generate a bank advice file. Production: yes,
for any real (non-synthetic) data.

**Correction to scope assumption:** the Statutory model has **no PAN or Aadhaar fields** — those
live only on `Employee`, and (re-confirmed this session) have **no write path anywhere yet**
(`EmployeeCreate`/`EmployeeUpdate` don't expose them, no service method writes them). They are dead
columns, not a live leak — flagged as F22 (P3), not conflated with the live F4 finding.

**Finding F11 — [P2] Raw sensitive values are embedded unencrypted in `audit_log.before_json`/
`after_json`.** `AuditLog.before_json`/`after_json` are `JSONB`, no encryption
(`core/audit/models.py:24-25`). Every `*_to_audit_dict` helper (`schemas.py:395` Compensation,
`:485` Statutory, `:560` Banking) is a bare `model_dump(mode="json")` of the full response model —
confirmed by reading the actual functions, not inferred. A dedicated test,
`test_bank_audit_snapshot_uses_response_model_convention`, explicitly proves parity between the
audit snapshot and the API response — meaning this is a **named, tested convention**, not an
accident. **Why it matters:** `audit_log` becomes a second unencrypted at-rest store of RESTRICTED
data (raw CTC, raw PF number, raw bank account number) with no separately-verified access control
confirmed on the `audit_log` table itself in this session (flagged as **unable-to-verify**, follow-up
recommended). **Recommended action:** decide explicitly whether audit snapshots should exclude or
mask specific RESTRICTED fields, given the convention is otherwise reasonable (full before/after
state is genuinely useful for an audit trail). **Blocks:** contributes to the same Payroll blocker
cluster as F4/F7.

**Finding F7 — [P1] `sensitive_access_log` does not exist anywhere in code.**
`grep -rn sensitive_access_log apps/` → zero `.py` hits; only documentation references (30+ across
architecture/module docs, consistently described as "locked decision, deferred to E-10"). No model,
migration, table, or function under any plausible name exists in `apps/api/src`. No code path logs a
*read* of Compensation/Statutory/Banking data — only writes are audited. **Why it matters:** three
consecutive RESTRICTED-tier read surfaces (E-06, E-07, E-08) have now shipped with zero record of
who viewed them. **Recommended action:** this audit's judgment, consistent with prior documents'
framing, is that this should become mandatory before Payroll specifically, given Payroll would be
the fourth RESTRICTED-tier consumer. **Blocks:** Payroll. Does not block Attendance/Leave.

---

## 7. Banking Security Audit

- **Account holder / bank name / IFSC / branch / payment mode**: plain columns, no masking
  anywhere, correctly validated against enum (`payment_mode`: `BANK`/`CASH`/`CHEQUE`/`UPI`,
  confirmed byte-for-byte matching frontend and backend this session).
- **Verification status / primary flag**: exist as system-managed fields (`schemas.py:499-515`),
  correctly excluded from the client-writable `BankCreate` schema — confirmed the frontend payload
  builder never attempts to set them.
- **Encryption**: none — see F4.
- **Masking**: client-render only (`maskAccountNumber`) — the full value is present in every
  successful `GET` response body and in React state; confirmed via source read this session, not
  assumed.
- **SELF scope**: correctly enforced — the one sub-resource that gets this right. `router.py:525-568`
  binds `scope`+`caller_employee_id` and passes them through `resolve_visible_employee_ids` to the
  repository. Verified live via 3 passing tests: SELF sees own record only and 404s on others; SELF
  with no linked `employee_id` sees nothing (fails closed); COMPANY scope still works. **This is the
  reference implementation Statutory and Compensation should be brought in line with (F2/F3).**
- **Admin/company-wide access**: works as expected via `COMPANY`-scoped grants.
- **Tenant isolation**: enforced via explicit `company_id` filter (see F1 for the caveat that this
  is the *only* enforcement layer, RLS being inert).
- **Termination behavior (confirmed-good)**: grepped `terminate_employment`
  (`service.py:570-787`) for any Bank repository reference — none exists. The bank row genuinely
  survives termination by design (full-and-final settlement rationale), matching every prior
  document's claim and now independently re-confirmed against current code.
- **Rehire behavior (confirmed-good, and the one genuine asymmetry worth remembering)**: because
  the bank row is never closed on termination, it is still "current" at rehire — the rehire's first
  bank write takes the close-then-insert branch and *requires* `If-Match`, the opposite of every
  sibling sub-resource's rehire behavior (which takes the "no current row" branch, requiring no
  `If-Match`). Confirmed via a directly-named regression test.
- **Payroll bank-advice boundary**: `get_bank_as_of` exists and is documented as the intended
  integration point — present and callable, blocked from safe use by F4/F7, not by its own absence.

---

## 8. Statutory Security Audit

- **Fields**: `is_pf_applicable`, `pf_number`, `pf_wage_ceiling_opt_out`, `vpf_amount`,
  `vpf_percentage`, `is_esi_applicable`, `esi_ip_number`, `pt_state_code`, `is_lwf_applicable`,
  `tax_regime` (`OLD`/`NEW`), `is_director`, `is_international_worker` — all confirmed present in
  both the migration DDL and the model this session; all exposed raw/unmasked in the API response,
  no field-level masking anywhere.
- **Permission enforcement**: `EMPLOYEE_VIEW_STATUTORY` (read), `EMPLOYEE_UPDATE_SENSITIVE` (write)
  — confirmed as the actual codes checked in `router.py`, not merely documented.
- **Data scope**: discarded — see F2. This is the audit's most important Statutory-specific finding.
- **API response exposure**: full, unmasked, to any caller with the read permission (subject to the
  F2 gap widening who that practically includes).
- **Audit logging**: PF number and every other field land in `audit_log` in plaintext (F11); no
  read-path log exists (F7).
- **Termination behavior (confirmed-good)**: the current statutory row is closed at
  `last_working_day`, same pattern as Compensation, matching the documented contract.
- **Rehire behavior (confirmed-good)**: insert-only, no carry-forward — `StatutoryCreate` requires
  every field fresh on the rehire's first write. A tax-regime-switch-once-per-FY rule is correctly
  enforced and tested (`TaxRegimeSwitchNotAllowedError`, both within-FY-rejected and across-FY-allowed
  cases verified passing).
- **Payroll snapshot contract**: `get_statutory_as_of(employee_id, date)` exists, documented and
  callable, blocked from safe use by F2/F7, not by its own absence.

---

## 9. Compensation Security Audit

- **Effective dating / revision**: closes the current open row and inserts a new one under a GiST
  exclusion constraint backstop — confirmed insert-only, no `update_compensation` method exists.
- **Who can see salary**: gated by `EMPLOYEE_VIEW_COMPENSATION` — but see F3: scope is resolved and
  discarded, so in practice this is company-wide for any grant holder regardless of the scope value
  nominally attached to their role.
- **Audit content**: raw `annual_ctc_minor` present in both before/after JSON — confirmed by reading
  `compensation_to_audit_dict` directly (F11).
- **Termination behavior (confirmed-good)**: the open compensation row is closed at
  `last_working_day` if its `effective_from` predates it; left open if future-dated (a deliberately
  unresolved edge case, documented as such, not a bug).
- **Rehire behavior (confirmed-good)**: fresh CTC required on every write including the rehire's
  first — no silent carry-forward of a stale figure.

---

## 10. Tenant Isolation Audit

**Finding F1 — [P0] Row-Level Security is completely inert; tenant isolation has zero
database-level backstop.**

Live query this session: `SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname='hrms'`
→ `hrms | t | t`. The application's connecting Postgres role is both a **superuser** and has
**`BYPASSRLS`** explicitly set. Per Postgres's own documented semantics, superusers bypass row
security unconditionally, and `FORCE ROW LEVEL SECURITY` — confirmed present and enabled on all six
Employee tables (`relrowsecurity=t`, `relforcerowsecurity=t`) — does **not** change this for
superusers; `FORCE` only affects non-superuser table owners.

This was verified **empirically**, not just from role configuration: a probe traced the actual GUC
call chain (`current_tenant_company_id()`, `set_rls_company_id`) while issuing a real `GET
/v1/employees` request through the live ASGI app. The trace showed the tenancy GUC-setting function
was never invoked in a code path that mattered — yet the response returned correctly isolated,
company-scoped data. The **only** reason this worked is that every repository method in
`apps/api/src/hrms/modules/employee/repository.py` (and every module this pattern was spot-checked
against) independently adds an explicit `WHERE company_id = :company_id` predicate by hand — a
convention, not a guarantee.

**Why this is worse than the prior audit's related finding:** the prior document's §11 noted the
tenancy GUC is set from timing that occurs before `get_tenant_context` fully validates the header
against the JWT, and concluded this was "not exploitable today" because it assumed RLS was the
actual safety net being raced against. **RLS is not a safety net at all under this role** — the
entire question of GUC timing is moot, since the policy it feeds is never consulted for this
connection in the first place. This is a materially different, more severe conclusion than what
any prior document reached.

**Confirmed-good, and critical to preserve:** every repository query that was read this session
(across Employee's six tables and beyond, spot-checked in Organisation) does include the explicit
`company_id` filter. This is currently the *entire* tenant-isolation mechanism for this application
— it must not be weakened or assumed redundant with RLS while F1 remains open.

**Recommended action:** either (a) provision a dedicated, non-superuser, non-`BYPASSRLS` role for
the application's database connection so `FORCE ROW LEVEL SECURITY` actually applies, or (b)
explicitly document RLS as decorative in this deployment and stop citing it as a defense-in-depth
layer in future architecture docs, so nobody relies on a protection that isn't there. Option (a) is
strongly preferred — it costs a role/grant change, not an application rewrite, since every query
already carries the correct filter and RLS would then simply start actually backstopping it.

**Blocks:** Attendance, Leave, Payroll, and production — this is a cross-cutting infrastructure
finding, not specific to any one future module, but it underlies the tenant-isolation guarantee
every future module will depend on.

**Finding F17 — [P3] Minor FK-hygiene inconsistency.** `employee_assignment` and
`employee_compensation` have `company_id NOT NULL` but no FK constraint to `company(id)`, unlike
`employee`, `employment`, `employee_statutory`, and `employee_bank`, which all have one. Nothing at
the DB level stops an orphaned `company_id` on these two tables specifically. Low priority — flagged
as schema-hygiene drift between the E-04/E-06 migrations and the later E-07/E-08 ones, worth fixing
opportunistically rather than urgently.

---

## 11. Database Integrity Audit

Confirmed via live queries this session (not re-quoted from any prior document):

- **Migration head**: `alembic_version.version_num = 20260815140000`, matching the
  lexicographically-latest migration file. `alembic heads` returns a single head — linear history,
  no branching.
- **GiST exclusion constraints**: `employment_no_overlap`, `employee_assignment_no_overlap`,
  `employee_compensation_no_overlap`, `employee_statutory_no_overlap`, `employee_bank_no_overlap` —
  all present exactly as named, all `EXCLUDE USING gist (employee_id WITH =, daterange(...) WITH
  &&)`. These are genuinely DB-enforced — confirmed via a raw-SQL bypass test
  (`test_raw_overlapping_insert_rejected_at_database_level`) that disables RLS and inserts directly,
  proving the constraint itself (not just application logic) rejects an overlap.
- **CHECK constraints**: `employment_status_check`, `employment_last_working_day_after_joining_check`,
  `employment_status_last_working_day_check` — all present and correctly enforce the
  status/last-working-day invariants at the database layer as a backstop to the service-layer check.
- **RLS**: enabled and forced on all six tables at the schema level — but see F1: inert in practice
  due to the connecting role's privileges.
- **Sensitive column types**: `pan_number_enc`, `aadhaar_number_enc` (`employee`), `account_number_enc`
  (`employee_bank`), `pf_number`, `esi_ip_number` (`employee_statutory`) — all plain `TEXT`/`VARCHAR`,
  none `bytea`, confirmed via direct schema query. No column is genuinely encrypted (see F4/F22).
- **Row counts (dev)**: small, clearly synthetic test data (`employee:4, employment:2,
  employee_assignment:1, employee_compensation:1, employee_statutory:2, employee_bank:1`) — spot-checked
  values are test-shaped (e.g., a standard-format but obviously placeholder IFSC code, PF numbers
  prefixed `PF...`), not real PII.
- **`role_permission` live rows**: 66 total, all `data_scope = 'COMPANY'` — see F5 (this corrects
  the prior audit's stated count of 24).

**Note — leftover test data.** In the course of empirically verifying F1, the research agent
registered two throwaway companies via the live registration endpoint (`RlsProbe ...`) to trace the
GUC/RLS call chain under realistic conditions. Its own cleanup attempt was blocked by this
environment's safety controls before any deletion occurred, so **these two synthetic companies and
a handful of associated rows are still present in the dev database** (`hrms_dev`). They are harmless
synthetic data (no real employee information), but you may want to remove them manually — a
FK-safe deletion order was provided in the agent's report and is available on request; no destructive
action was taken automatically.

---

## 12. Audit Logging Audit

`AuditService.record()` (`core/audit/service.py:11-38`) writes one row per mutation with
`company_id`, `actor_user_id`, `action`, `entity_type`, `entity_id`, `before_json`, `after_json`,
`ip`, `user_agent`, `request_id`, server-defaulted `occurred_at` — structurally complete, and every
employee-domain mutation (`EMPLOYEE_CREATED/UPDATED/DEACTIVATED/REACTIVATED`,
`EMPLOYMENT_STARTED/REHIRED/UPDATED/TERMINATED`, `ASSIGNMENT_CHANGED`, `COMPENSATION_REVISED`,
`STATUTORY_REVISED`, `BANK_REVISED`) fires it — confirmed by reading `service.py` directly, no write
path was found skipping this call.

The gap is entirely on two other axes, both already covered above: raw sensitive values embedded
unencrypted in the before/after snapshots (F11), and the complete absence of any read-path log
(F7). No missing *write* event was found this session.

**Finding F16 — [P3] `StaleResourceError` (409 response) embeds the full raw `current` snapshot,
including sensitive fields, in its response body.** (`exceptions.py:15-27`). Low standalone risk —
only reachable by a caller who already holds the relevant write permission — but escalates in
combination with F2/F3/F8: a caller with a write permission scoped narrower than `COMPANY` (once
one exists) could trigger a 409 against an out-of-scope employee and receive their raw data in the
error body. Track alongside the F2/F3/F8 remediation rather than fixing in isolation.

---

## 13. Frontend/Backend Contract Audit

The Employee frontend (E-09) was independently re-read against the live backend contract this
session — every finding below is a direct file:line comparison, not a re-statement of a prior
claim.

**Confirmed-good, with zero drift found:**
- Every Create/Update payload builder (Employee, Employment, Assignment, Compensation, Statutory,
  Banking) sends exactly the fields the backend's `Create`/`Update` schema accepts — no extra field
  that would trip `extra="forbid"`, no missing required field.
- Every enum (`EmployeeStatus`, `EmploymentStatus`, `AssignmentChangeType`, `WorkLocationType`,
  `RevisionType`, `TaxRegime`, `PaymentMode`) is byte-for-byte identical between the frontend TS
  types and the backend Python enums.
- `If-Match` is correctly sourced from the currently-loaded resource's `version` on all 7 write call
  sites — no site was found sending a stale, hardcoded, or missing version where one was required.
- Deactivate/reactivate correctly mirrors the backend's asymmetric contract (`DELETE` = soft
  deactivate, `PATCH is_active:true` = reactivate).
- 403 handling is genuinely consistent across every panel and every write call site.

**Finding F18 — [P3] No client-side gating on the 6 detail tabs.** All six tabs (Overview/
Employment/Assignment/Compensation/Statutory/Banking) render unconditionally and rely entirely on
each panel's own `GET` returning a 403; `use-permissions.ts` documents this as intentional (server
is the real enforcement point). Cosmetic only — no content renders before the 403 resolves, so no
data is exposed, but a low-privilege viewer does see six populated-looking tab headers before
clicking into ones they can't use.

**Finding F12 — [P2] 422 field-error mapping is materially incomplete on 4 of 6 forms.**
Compensation is fully complete (5/5 fields mapped). Employee create/update maps 2/10 fields,
Assignment maps 8/12, Statutory maps 3/14, Banking maps 2/7 — the remaining fields fall through to
a generic toast with no inline highlight on a genuine 422. Not a security issue; a real production
UX defect.

**Finding F13 — [P2] 409 `STALE_RESOURCE` recovery UI is inconsistent.** 5 of 7 write paths show
the shared `ConcurrencyConflictBanner` (reload-latest / cancel-changes recovery); 2 (Employee
deactivate/reactivate toggle, Employment terminate) degrade to a toast-only message with no inline
recovery action. The underlying version-read-and-send mechanism itself is correct and consistent on
all 7 — only the recovery affordance differs.

**Finding F19 — [P3] `?as_of=` is confirmed never called anywhere in the frontend** (zero matches
on a full-tree grep for the literal string). A fully-built, tested backend capability on 5 list
endpoints with no UI entry point — every panel instead derives "current" client-side from the full
history. Functionally correct for "what's current," incapable of "what was true on a past date."

**Finding F20 — [P3] 5 backend sub-resource routes are unreachable from the frontend.** The four
single-record `GET .../{sub_resource}/{id}` routes, and `PATCH .../employments/{id}` (legal-entity
correction) — the latter even has a written-but-dead frontend payload builder
(`buildEmploymentCorrectionPatch`, confirmed never imported anywhere). No orphaned call was found in
the other direction (frontend calling a route that doesn't exist).

---

## 14. Test-Quality Audit

**Finding F6 — [P1] The test suite is non-deterministic; no pass/fail count in this or any prior
document should be trusted without re-verification.**

Re-run this session, identical command against identical code, 4 times:

| Run | Command | Result |
|---|---|---|
| 1 | `pytest tests/ -q` | 592 passed, 54 errors, 0 failed |
| 2 | employee-only subtree | 290 passed, 6 errors |
| 3 | same, immediate rerun | 290 passed, 0 errors (clean) |
| 4 | `pytest tests/ -q` (rerun) | 597 passed, **1 failed**, 14 errors |

**Root cause, confirmed by reading code, not guessed:** a function-scoped `seeded_plan_catalogue`
fixture (duplicated across `employee/`, `organisation/`, and `security/` `conftest.py` files)
upserts global `Plan` rows by fixed code with **no per-test database transaction rollback**. If any
test registers a `Subscription` referencing one of these rows outside a `try/finally` (or raises
before entering one), the row leaks; the next test file's attempt to delete/recreate the `Plan`
catalogue then throws `ForeignKeyViolationError`, and the specific tests that surface as `ERROR`
vary run-to-run depending on execution order. Run 4 produced one **genuinely false** `FAILED` —
`test_employee_statutory.py::test_tax_regime_switch_across_fy_allowed` — caused entirely by this
pollution, not by any defect in the Statutory logic under test.

**Why it matters:** this undermines the evidentiary basis of every other finding in this document
and every prior one that cites a specific pass/fail count. Individually-run tests were confirmed
reliable (every specific test cited elsewhere in this document was re-run in isolation and passed);
it is only full-suite/cross-file runs that are unstable.

**Recommended action:** real per-test database transaction isolation (rollback after each test), or
at minimum per-test-run-unique Plan codes, before treating this suite as a production readiness
gate. **Blocks:** production (as a trust-in-CI issue) — does not block Attendance/Leave/Payroll
development directly, but blocks confidently gating any of them on "tests pass."

**Finding F14 — [P2] Tests named for "race" conditions are pure exception-translation mocks, not
real concurrency tests.** Five tests (`test_create_{bank,assignment,compensation,employment,
statutory}_overlap_race_converted_to_domain_error`) mock a repository method's `IntegrityError`
`side_effect` and assert the service translates it to the correct domain error — a legitimate test
of error-translation logic, but the name overclaims: no test anywhere opens two real database
sessions and races a concurrent write. The one test that hits the real GiST constraint
(`test_raw_overlapping_insert_rejected_at_database_level`) is single-connection and exists only for
Assignment, not the other four sub-resources individually. **Recommended action:** rename to avoid
implying concurrency coverage that doesn't exist, and add at least one genuine two-connection test
for the mechanism that matters most (termination racing a concurrent sub-resource write).

**Other quality findings (confirmed-good):**
- No `skip`/`xfail` markers anywhere in the Employee test files; no tautological assertions found
  (`status_code in [...]`, bare `is not None` as the substantive check) — the handful of `is not
  None` hits are unrelated registration-helper boilerplate, not the tests' actual assertions.
- Real cross-tenant IDOR tests exist for every sub-resource (18 distinct tests found).
- Real 409 stale-version tests exist for every writable sub-resource.
- `tests/security/` contains exactly one file (`test_organisation_security.py`, 8 tests) — no
  `test_employee_security.py` exists (Finding F21, P3). Employee's own substantial security-relevant
  coverage (IDOR, permission, scope, self-elevation) is real and passes, just scattered across
  ordinary integration test files rather than consolidated for discoverability.

---

## 15. Production Blockers

### P0 — must fix before any real employee data

- **F1** — Application DB role is a superuser with `BYPASSRLS`; RLS provides zero actual protection;
  tenant isolation rests entirely on manual per-query filters with no database-level backstop.
  *Affected: all modules, cross-cutting. Blocks: Attendance, Leave, Payroll, production.*

### P1 — must fix before production

- **F2** — Statutory GET routes resolve then discard `DataScope`, contradicting locked Decision E.
  *Blocks: Payroll, production (once any non-COMPANY grant exists for this permission).*
- **F3** — Compensation has the identical bug, contradicting locked Decision F. *(Newly found this
  session.) Blocks: same as F2.*
- **F4** — `account_number_enc` is genuinely plaintext; no encryption exists anywhere in the
  codebase. *Blocks: Payroll (explicit, self-imposed precondition), production for real data.*
- **F5** — RBAC data-scope engine is fully built, tested in isolation, completely unreachable in
  production (0/66 role_permission rows use anything but COMPANY). *Blocks: Leave (directly),
  Attendance (partially).*
- **F6** — Test suite is non-deterministic due to shared, non-isolated fixture state; no pass/fail
  count can be trusted without re-verification. *(Newly found this session.) Blocks: production
  (as a CI-trust issue).*
- **F7** — `sensitive_access_log` does not exist anywhere in code; three RESTRICTED-tier read
  surfaces have shipped with zero read-audit trail. *Blocks: Payroll.*

### P2 — should fix before Payroll

- **F8** — Data-scope enforced on only 4 of 12 GET routes; Employment/Assignment/Compensation/
  Statutory history is readable by ID with no scope check (dormant IDOR, activates with F5).
- **F9** — Write-path data-scope does not exist anywhere in the module.
- **F10** — `GET /employees` has no pagination; unbounded full-company scan.
- **F11** — Raw CTC/PF/bank data embedded unencrypted in `audit_log` JSONB (named, tested
  convention, but a second unencrypted at-rest copy of RESTRICTED data).
- **F12** — 422 field-error mapping incomplete on 4 of 6 frontend forms.
- **F13** — 409 `STALE_RESOURCE` recovery UI inconsistent (banner vs. toast) on 2 of 7 write paths.
- **F14** — "Race" tests are mocks only; no genuine two-connection concurrency test exists anywhere.

### P3 — future improvement

- **F15** — Inactive shifts remain assignable (deliberate, consistent, tested — flag for product
  sign-off on intent).
- **F16** — `StaleResourceError` 409 body leaks raw sensitive snapshot (low standalone risk,
  escalates with F2/F3/F8).
- **F17** — `employee_assignment`/`employee_compensation` missing FK to `company(id)` present on
  sibling tables.
- **F18** — No client-side permission gating on the 6 detail tabs (cosmetic; no data exposure).
- **F19** — `?as_of=` never called anywhere in the frontend.
- **F20** — 5 backend sub-resource routes (incl. one PATCH with a dead frontend payload builder)
  are unreachable from the UI.
- **F21** — No dedicated `tests/security/test_employee_security.py`.
- **F22** — `pan_number_enc`/`aadhaar_number_enc`/`uan_number` remain dead, plaintext, unwritten
  columns.
- **F23** — `REPORTEE_TREE` recursion is depth-capped, not cycle-detected.

---

## 16. Attendance Readiness

**What Attendance needs:** `get_assignment_as_of` (shift, work location) and
`get_employment_as_of`/`Employment.status` (active-employment gating) — both re-confirmed this
session as real, tested, stable contracts with no drift.

**What must be fixed first:** nothing Attendance-specific in application code. It inherits the F5
role-seeding gap the moment it needs "a manager sees their team's attendance" (that's Attendance's
own future role-seeding work, not a defect in what Employee exposes today), and it inherits the F1
cross-cutting infrastructure gap like every other module.

**Verdict: Attendance development can begin against these contracts today**, with the caveat that
F1 must be resolved before any of it — Attendance included — handles real employee data in
production.

## 17. Leave Readiness

**What Leave needs:** the same `*_as_of` seam as Attendance, plus reporting-hierarchy data for
approval routing — mechanically ready (the `REPORTEES`/`REPORTEE_TREE` resolver already consumes
exactly this data).

**What must be fixed first:** F5 is a hard prerequisite for Leave specifically, more directly than
for any other planned module — an approval workflow is meaningless without a real
`REPORTING_MANAGER`-shaped role holding real `REPORTEE_TREE` visibility. F5 should not be closed,
however, before F8/F9 are closed alongside it (seeding roles onto an incompletely-scoped API surface
would immediately activate the dormant IDOR in F8).

**Verdict: Leave should not start its approval-routing implementation until F5 (sequenced after
F8/F9) lands.** Other Leave functionality not dependent on manager visibility could proceed in
parallel.

## 18. Payroll Readiness

**What Payroll needs:** `get_compensation_as_of`, `get_statutory_as_of`, `get_bank_as_of` — all
three exist, are documented as Payroll's intended entry points, and are individually well-tested.
Mechanically ready.

**What must be fixed first:** this audit's explicit recommendation, consistent with and reinforcing
this project's own prior self-imposed conditions, is that Payroll should **not** begin
implementation against real data until: F4 (banking encryption) and F7 (`sensitive_access_log`) are
resolved — both were already-locked preconditions this session re-confirms are unmet — and F2/F3
(Compensation/Statutory scope-discard) are fixed, since Payroll would otherwise be the fourth
RESTRICTED-tier consumer built on top of two known-broken read-scope gates.

**Verdict: Payroll is not ready to begin implementation against real data.** Development against
synthetic/test data using the `*_as_of` contracts is reasonable to start in parallel with the
above remediation.

---

## 19. Architectural Risks

**The F2/F3 shared root cause is the most consequential architectural risk for future modules.**
Both bugs have the identical shape: a route resolves a `DataScope` object, binds it to a
conventionally-underscore-prefixed unused variable, and never threads it into the service/repository
call. This is not two independent mistakes — it is one pattern that was applied correctly for
Employee and Banking and incorrectly for Statutory and Compensation. **Any future module
(Attendance, Leave, Payroll) that copies the Employee router's dependency-injection style for a new
RESTRICTED-tier resource is exactly as likely to reproduce this exact bug**, since nothing in the
code structure — no type, no lint rule, no test template — currently distinguishes "scope resolved
and correctly applied" from "scope resolved and silently discarded." Recommended (not proposing
the fix itself, per audit scope): a shared helper or type-level marker that makes an unapplied
`DataScope` impossible to compile/pass review, rather than relying on each router author remembering
to thread it through by hand.

**The audit-snapshot convention (`model_dump(mode="json")` with no field exclusion) is applied
identically across every `*_to_audit_dict` function in both Employee and Organisation.** This is
architecturally consistent (a genuine strength — no module diverges from the pattern), but it also
means any future RESTRICTED field added anywhere in the codebase will automatically flow into
`audit_log` in plaintext unless a developer remembers to special-case it. Worth a single documented
policy decision now, before more modules add more RESTRICTED fields.

No other duplicated-logic risk material enough to flag was found between Employee/Employment/
Assignment/Compensation/Statutory/Banking/RBAC this session — the effective-dating, optimistic-
concurrency, and audit-logging patterns are otherwise applied with genuine, verified consistency
across all six resources.

---

## 20. Recommended Remediation Sequence

1. **F1** — swap the application's Postgres connection role for a non-superuser, non-`BYPASSRLS`
   role. Small, mechanical, highest blast-radius fix in this audit; unblocks nothing by itself but
   removes the single point of failure under every other tenant-isolation claim.
2. **F2 + F3** together — wire `scope`/`caller_employee_id` through Statutory and Compensation's GET
   routes exactly as Banking already does. Same fix, same root cause, do together.
3. **F8 + F9** — extend the same scope-passing fix to Employment/Assignment's read routes and add
   write-path scope enforcement across the module, closing the dormant IDOR before it can activate.
4. **F5** — seed the three Decision H roles (`EMPLOYEE`, `REPORTING_MANAGER`, `HR_ADMIN`) — only
   after step 3, so seeding activates correct behavior rather than a live exposure.
5. **F6** — fix test isolation (per-test transaction rollback or unique fixture identifiers) before
   relying on any future "N/N tests pass" claim as a release gate.
6. **F4 + F7** — resolve the banking-encryption mechanism (Decision D-2) and build
   `sensitive_access_log` — both explicitly required before Payroll, independent of the above.
7. P2/P3 items — no hard ordering dependency on Attendance/Leave/Payroll; sequence
   opportunistically (pagination, 422 mapping completeness, 409-UI consistency, FK hygiene,
   client-side tab gating, `?as_of=` UI, dead-code cleanup).

---

## 21. What Must NOT Be Changed

These were independently re-verified this session as correctly implemented and load-bearing —
flagging explicitly so remediation work doesn't inadvertently regress them:

- The uniform optimistic-concurrency pattern (`version` + `If-Match` → 409 `STALE_RESOURCE`) across
  all six mutable resources.
- The GiST exclusion-constraint approach to effective-dated overlap prevention — genuinely
  DB-enforced, proven by a raw-SQL bypass test, not merely application-level.
- The insert-only, no-`update_*`-method structure of the four effective-dated sub-resources — this
  is what makes history immutable and is enforced structurally, not by convention.
- The absence of an `employment_id` FK on the four effective-dated sub-resources — this is what
  makes rehire work correctly without orphaned-FK handling; it is a deliberate tradeoff, not a gap.
- The reporting-manager self-elevation guard in Assignment (`InvalidReportingManagerError`) — closes
  a real, previously-identified privilege-escalation vector, verified via passing regression tests.
- Banking's `SELF`-scope implementation — the reference pattern F2/F3 should be brought in line
  with, not replaced.
- The explicit `company_id` filter present in every repository query — this is, as of F1, the
  *entire* tenant-isolation mechanism; do not remove or weaken it under the assumption RLS covers
  it.
- The frontend's schema/enum parity with the backend and its correct `If-Match`-sourcing on every
  write path — zero drift was found; any refactor should preserve this exact mirroring discipline.

---

## 22. Open Product Decisions

Carried forward as still-open, each independently re-confirmed unresolved this session:

1. `sensitive_access_log` exact schema — the decision to build it is locked; its shape is not (F7).
2. Encryption mechanism and timing for `_enc`-suffixed columns (Decision D-2) — locked as a
   Payroll precondition, mechanism itself not chosen (F4).
3. Whether `audit_log` should exclude/mask specific RESTRICTED fields, given the current
   full-snapshot convention is applied identically everywhere (F11).
4. Statutory's data-scope posture — Decision E says `SELF`-by-default; the shipped code
   contradicts it (F2). Needs an explicit decision: fix the code to match the decision, or revise
   the decision and document the deviation loud enough that it can't be missed at the API-consumer
   level (currently only visible in an inline code comment).
5. Whether `personal_email`/`personal_mobile` need field-level permission gating beyond plain
   `EMPLOYEE.VIEW` — recommended in a prior architecture document, not implemented, not re-verified
   in depth this session (out of this audit's specific scope, flagged for completeness).
6. Whether the application's database role change (F1 remediation) requires any other code path
   currently assuming superuser privileges to be adjusted — not identified in this session's scope,
   worth a dedicated check before making the role change.

---

## 23. Final Go/No-Go Recommendation

**No-go for production as-is.** The core Employee/Employment/Assignment/Shift lifecycle is
genuinely solid and independently re-verified this session — that part of the vertical earns real
confidence, not just a passing prior report. But this session found one P0 (RLS is completely
inert) and confirmed/discovered six P1s, two of which (F3, F6) were not present in any prior
document. None of the P0/P1 findings require a redesign — every one has a scoped, mechanical fix —
but none should be skipped before real employee PII enters this system.

```
STATUS:
P0: 1  (F1 — RLS inert, superuser+BYPASSRLS connection role)
P1: 6  (F2 Statutory scope-discard, F3 Compensation scope-discard [new], F4 plaintext banking,
        F5 role-seeding gap, F6 non-deterministic tests [new], F7 no sensitive_access_log)
P2: 7  (F8 partial scope coverage, F9 no write-path scope, F10 no pagination, F11 raw data in
        audit log, F12 incomplete 422 mapping, F13 inconsistent 409 UI, F14 mock-only race tests)
P3: 9  (F15 inactive shifts assignable, F16 409-body leak, F17 missing FK, F18 no tab gating,
        F19 as_of unused, F20 orphaned routes, F21 no dedicated security test file,
        F22 dead PAN/Aadhaar columns, F23 depth-capped cycle handling)

ATTENDANCE READY: YES (contracts stable; F1 must still be fixed before production)
LEAVE READY: NO (blocked on F5, sequenced after F8/F9)
PAYROLL READY: NO (blocked on F4, F7, F2, F3)
PRODUCTION READY: NO (blocked on F1)
```

**Single highest-priority next engineering task:** fix **F1** — replace the application's Postgres
connection role with a non-superuser, non-`BYPASSRLS` role. It is the smallest fix in this document
(an infrastructure/role change, not an application rewrite), it has the largest blast radius of any
finding (every table, every query, every future module inherits it), and unlike the RBAC
role-seeding gap it is not currently masked by "nothing exploits it today" — it is a standing,
unconditional absence of database-level defense-in-depth underneath every tenant-isolation guarantee
this audit otherwise confirms is correctly implemented in application code.
