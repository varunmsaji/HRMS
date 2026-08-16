# Employee Vertical — Access-Control Audit & Implementation Plan (F4/F8/F9)

**Date:** 2026-08-16
**Status:** Audit + implementation plan only. No application code, migration, database, test, or
frontend change was made to produce this document. Nothing was committed.
**Method:** Independently re-derived from the current working tree (not from any prior document's
claims), cross-checked against a live query of the dev database
(`postgresql://hrms:***@localhost:5433/hrms_dev`), and against the actual test suite's file
contents (test names/assertions read directly, not inferred).

**Relationship to prior documents:** `docs/architecture/EMPLOYEE_VERTICAL_PRODUCTION_READINESS_AUDIT.md`
("the Audit") already named these gaps as its own **F8** ("data-scope enforced on only 4 of 12 GET
routes") and **F9** ("write-path data-scope does not exist anywhere"), and recommended closing them
together, before role-seeding (its F5) ships. This document does not reopen or contradict that
audit's F1–F23 findings — it independently re-verifies F8/F9 in the depth this task (labeled
**F4/F8/F9** in the task brief) requires, adds findings the prior audit did not itemize at this
granularity (per-route IDOR shape, hierarchy-escalation-via-write, write-path architecture
inconsistency), and turns the result into a scoped implementation plan. Where this document's
findings overlap the Audit's F8/F9, that overlap is called out explicitly rather than silently
renumbered.

---

## 1. Executive Summary

The Employee vertical's **read path** for `Employee`, `Compensation`, `Statutory`, and `Bank` is
correctly data-scope-enforced today (SELF/REPORTEES/REPORTEE_TREE/COMPANY, 404-not-403 on
out-of-scope, tenant-safe). **Employment and Assignment GET routes are not** — they check only the
bare permission and tenant, with zero scope filtering, identical in shape to the pre-fix bug the
Compensation/Statutory F2/F3 remediation (`38_EMPLOYEE_COMPENSATION_STATUTORY_DATA_SCOPE_IMPLEMENTATION_REPORT.md`)
already closed elsewhere. **No write route in the entire module enforces data scope** — every
`POST`/`PATCH`/`DELETE`/`terminate` route is gated by permission alone, company-wide, regardless of
what scope value is actually attached to the caller's grant for that permission code.

**Why this is not live-exploitable today:** independently re-verified via a live database query
(§17) — all 13 audited `EMPLOYEE.*` permission codes are seeded at `data_scope = 'COMPANY'` for
every role in every tenant (no migration or code path has ever inserted a non-`COMPANY` row). The
gap is real, structural, and completely dormant. It activates the moment any role — seeded by a
future default-role rollout (Decision H) or created by a tenant admin through a not-yet-built
role-management UI — is granted `EMPLOYEE.VIEW`/`.TRANSFER`/`.PROMOTE`/`.TERMINATE`/`.UPDATE`/
`.UPDATE_COMPENSATION`/`.UPDATE_SENSITIVE` at anything other than `COMPANY` scope.

**Confirmed secure and out of this document's scope:** tenant isolation (RLS is now genuinely
enforced — the Audit's P0 **F1** is independently re-verified **fixed** this session, §17), the
`resolve_visible_employee_ids` resolver itself, the reporting-manager direct-self-elevation guard,
and every already-scoped GET route (`Employee`, `Compensation`, `Statutory`, `Bank`).

**Recommendation:** close the read-path gap (Employment/Assignment GET) and add write-path scope
enforcement across the module in one coordinated change, before any non-`COMPANY` grant is ever
seeded or configured — exactly the sequencing the Audit's own remediation plan already calls for.
Employee is otherwise ready to proceed to E-10/Attendance; this work should land first, but does not
block Attendance's own read-only `*_as_of` contract usage (§16 mirrors the Audit's own verdict).

---

## 2. Scope

In scope: every Employee-module HTTP route (Identity, Employment, Assignment, Compensation,
Statutory, Bank); the authorization chain (auth → permission → data-scope → caller identity →
target visibility → tenant → RLS → operation) for each; IDOR/enumeration behavior; hierarchy
self-elevation via write; effective-dating/as-of bypass risk; tenant/RLS interaction; frontend
alignment; test coverage; performance of the proposed fix.

Out of scope (per task brief, and per the Audit's own already-locked/already-tracked items, not
reopened here): RLS/superuser role remediation (Audit F1 — independently re-verified fixed, §17,
not re-litigated), banking encryption (F4 in the Audit's numbering), `sensitive_access_log` (F7),
audit-log field redaction (F11), role-seeding itself (F5 — this document is a precondition for it,
not the seeding work), pagination (F10), frontend UX polish (F12/F13/F18/F19/F20), test
non-determinism (F6), `REPORTEE_TREE` cycle *detection* at read time (F23 — the write-time guard gap
is in scope, §14, because it is a write-path finding).

---

## 3. Sources Inspected

Code (current working tree, not git history — the module is substantially uncommitted per `git
status`): `employee/router.py`, `service.py`, `repository.py`, `permissions.py`, `exceptions.py`,
`dependencies.py`, `models.py`, `schemas.py`; `core/rbac/{dependencies,service,types}.py`;
`core/tenancy/{dependencies,context}.py`; `core/db/session.py`; `core/db/models/identity.py`;
`organisation/service.py` (`register_company`); `seed/bootstrap.py`.

Tests (read in full, not sampled): `tests/integration/modules/employee/test_employee_assignment.py`,
`test_employee_compensation.py`, `test_employment.py`, `test_employee_banking.py`,
`test_employee_data_scope.py`, `test_employee_statutory.py`; `tests/security/test_rls_runtime_role.py`;
`tests/unit/modules/employee/test_employment_service.py`, `test_employee_bank_service.py`,
`test_employee_statutory_service.py`.

Frontend: `apps/web/src/app/app/employees/`, `apps/web/src/components/employee/*`,
`apps/web/src/lib/employee/validate-bank.ts`, `apps/web/src/lib/auth/use-permissions.ts`.

Docs: `docs/architecture/RBAC_DATA_SCOPE_DECISIONS.md` (LOCKED decisions A–J),
`docs/architecture/EMPLOYEE_VERTICAL_PRODUCTION_READINESS_AUDIT.md`, `docs/architecture/
POSTGRES_RLS_ROLE_MIGRATION_PLAN.md`, `docs/modules/employee/25_..._IMPLEMENTATION_PLAN.md`,
`27_REPORTING_MANAGER_SECURITY_AUDIT.md`, `38_..._IMPLEMENTATION_REPORT.md`.

Live database (`hrms_dev`, port 5433): `pg_roles`, `pg_class` (RLS flags), `role_permission` joined
to `permission` for every `EMPLOYEE.*` code — queried directly this session (§17).

---

## 4. Current Architecture (authorization chain, as designed)

```
Authenticated request (JWT: user_id, company_id, employee_id|null)
  → get_tenant_context: X-Company-Id must equal JWT company_id or 404; verifies live UserCompany
      membership; sets the RLS GUC (app.company_id) explicitly, post-verification
  → require_permission(CODE): resolve_data_scope(user, company, CODE) — one query, empty result
      → 403; a non-empty result IS proof the permission is held (no separate has_permission call)
  → [only on the 4 already-fixed GET routes + assignment-create's ad hoc check] resolver turns
      DataScope.levels into a concrete employee_id set via EmployeeService.
      resolve_visible_employee_ids (SELF ∪ REPORTEES ∪ REPORTEE_TREE, or None for COMPANY)
  → repository query: WHERE company_id = :company_id [AND id IN visible_ids] — company_id filter
      always present by hand; RLS now backstops it at the database layer (§17)
  → PostgreSQL RLS (FORCE ROW LEVEL SECURITY, all 6 tables) — now actually enforced (§17)
```

`resolve_visible_employee_ids` (`service.py:91-138`) is the single, reusable seam every fix in this
document threads through — it already exists, is already correct, and is already the pattern
`Employee`/`Compensation`/`Statutory`/`Bank` GET routes use. No new resolver logic is proposed
anywhere in this plan; every fix below is "call the seam that already exists, from a call site that
currently skips it."

---

## 5. Complete Employee Route Inventory

| Method | Route | Permission | Perm. scope source | Caller `employee_id` available | DataScope resolved | DataScope enforced | Target visibility checked | Tenant filter | RLS | If-Match | Audit event | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| GET | `/employees` | `VIEW_ALL` | role_permission | Yes | Yes | Yes | Yes (list-filtered) | Yes | Yes | — | read (none) | ✅ Secure |
| POST | `/employees` | `CREATE` | role_permission | N/A (no target) | No | N/A | N/A | Yes | Yes | — | `EMPLOYEE_CREATED` | ✅ (no target-scope concept applies) |
| GET | `/employees/{id}` | `VIEW` | role_permission | Yes | Yes | Yes | Yes (404 out-of-scope) | Yes | Yes | — | none | ✅ Secure |
| PATCH | `/employees/{id}` | `UPDATE` | role_permission | Yes | **No** | **No** | **No** | Yes | Yes | Required | `EMPLOYEE_UPDATED`/`_DEACTIVATED`/`_REACTIVATED` | ⚠️ **Finding C** |
| DELETE | `/employees/{id}` | `DEACTIVATE` | role_permission | Yes | **No** | **No** | **No** | Yes | Yes | Required | `EMPLOYEE_DEACTIVATED` | ⚠️ **Finding C** |
| POST | `/employees/{id}/employments` | `CREATE` | role_permission | Yes | **No** | **No** | **No** | Yes | Yes | — | `EMPLOYMENT_STARTED`/`_REHIRED` | ⚠️ **Finding C** |
| GET | `/employees/{id}/employments` | `VIEW` | role_permission | Yes | **No** | **No** | **No** | Yes | Yes | — | none | ⚠️ **Finding A (=F4)** |
| GET | `/employees/{id}/employments/{eid}` | `VIEW` | role_permission | Yes | **No** | **No** | **No** | Yes | Yes | — | none | ⚠️ **Finding A (=F4)** |
| PATCH | `/employees/{id}/employments/{eid}` | `UPDATE` | role_permission | Yes | **No** | **No** | **No** | Yes | Yes | Required | `EMPLOYMENT_UPDATED` | ⚠️ **Finding C** |
| POST | `/employees/{id}/employments/{eid}/terminate` | `TERMINATE` | role_permission | Yes | **No** | **No** | **No** | Yes | Yes | Required | `EMPLOYMENT_TERMINATED` (+cascades) | ⚠️ **Finding C** |
| GET | `/employees/{id}/assignments` | `VIEW` | role_permission | Yes | **No** | **No** | **No** | Yes | Yes | — | none | ⚠️ **Finding B (=F8)** |
| GET | `/employees/{id}/assignments/{aid}` | `VIEW` | role_permission | Yes | **No** | **No** | **No** | Yes | Yes | — | none | ⚠️ **Finding B (=F8)** |
| POST | `/employees/{id}/assignments` | `TRANSFER` or `PROMOTE` (by body) | **`rbac.has_permission()` direct call — no `DataScope` object ever exists** | Yes | **No — not even resolved** | **No** | **No** (only direct-self-elevation guard) | Yes | Yes | Conditional | `ASSIGNMENT_CHANGED` | ⚠️ **Finding C + D** |
| GET | `/employees/{id}/compensation` | `VIEW_COMPENSATION` | role_permission | Yes | Yes | Yes (fixed, F2/F3) | Yes | Yes | Yes | — | none | ✅ Secure |
| GET | `/employees/{id}/compensation/{cid}` | `VIEW_COMPENSATION` | role_permission | Yes | Yes | Yes | Yes | Yes | Yes | — | none | ✅ Secure |
| POST | `/employees/{id}/compensation` | `UPDATE_COMPENSATION` | role_permission | Yes | **No** | **No** | **No** | Yes | Yes | Conditional | `COMPENSATION_REVISED` | ⚠️ **Finding C** |
| GET | `/employees/{id}/statutory` | `VIEW_STATUTORY` | role_permission | Yes | Yes | Yes (fixed, F2/F3) | Yes | Yes | Yes | — | none | ✅ Secure |
| GET | `/employees/{id}/statutory/{sid}` | `VIEW_STATUTORY` | role_permission | Yes | Yes | Yes | Yes | Yes | Yes | — | none | ✅ Secure |
| POST | `/employees/{id}/statutory` | `UPDATE_SENSITIVE` | role_permission | Yes | **No** | **No** | **No** | Yes | Yes | Conditional | `STATUTORY_REVISED` | ⚠️ **Finding C** |
| GET | `/employees/{id}/bank` | `VIEW_BANKING` | role_permission | Yes | Yes | Yes | Yes | Yes | Yes | — | none | ✅ Secure |
| GET | `/employees/{id}/bank/{bid}` | `VIEW_BANKING` | role_permission | Yes | Yes | Yes | Yes | Yes | Yes | — | none | ✅ Secure |
| POST | `/employees/{id}/bank` | `UPDATE_SENSITIVE` | role_permission | Yes | **No** | **No** | **No** | Yes | Yes | Conditional | `BANK_REVISED` | ⚠️ **Finding C** |

**8 of 20 target-bearing routes are scope-secure. 12 are not** (4 GET + 8 write) — a larger count
than the Audit's own "4 of 12 GET routes" framing because this inventory also counts every write
route, which the Audit's F9 named qualitatively but did not tabulate route-by-route.

---

## 6. Permission Matrix

13 `EMPLOYEE.*`/`EMPLOYEE.VIEW` codes are in play (`permissions.py:90-101`, plus `identity.EMPLOYEE_VIEW`
reused as-is). All 13 are currently seeded at `data_scope = 'COMPANY'` for every role that holds
them, in every tenant — see §17 for the live-verified table (this is the fact that makes every
finding in this document dormant rather than live).

No role currently grants `EMPLOYEE.VIEW_STATUTORY`/`.VIEW_BANKING` at a scope other than `COMPANY`
either — consistent with `permissions.py`'s own docstring noting no seeded role holds these two
codes outside `COMPANY_ADMIN`/`HR_ADMIN`-shaped grants.

---

## 7. DataScope Matrix

| Resource | READ scope enforced? | WRITE scope enforced? | Read permission | Write permission | Decision source |
|---|---|---|---|---|---|
| Employee (identity) | **Yes** | **No** (Finding C) | `VIEW`/`VIEW_ALL` | `UPDATE`/`DEACTIVATE` | Decision E/F name identity as `SELF`/`REPORTEES` visible; **no decision addresses write-scope** — OPEN (§21) |
| Employment | **No** (Finding A/F4) | **No** (Finding C) | `VIEW` | `CREATE`/`UPDATE`/`TERMINATE` | Decision F says managers should see Employment (`REPORTEES`) — read side unimplemented; **write-scope not addressed anywhere** — OPEN |
| Assignment | **No** (Finding B/F8) | **No** (Finding C/D) | `VIEW` | `TRANSFER`/`PROMOTE` | Decision F says managers should see Assignment (`REPORTEES`) — read side unimplemented; **write-scope not addressed anywhere** — OPEN |
| Compensation | **Yes** (fixed) | **No** (Finding C) | `VIEW_COMPENSATION` | `UPDATE_COMPENSATION` | Decision F: `REPORTEES`/`REPORTEE_TREE` when granted to managers — read implements it; **write-scope not addressed** — OPEN |
| Statutory | **Yes** (fixed) | **No** (Finding C) | `VIEW_STATUTORY` | `UPDATE_SENSITIVE` | Decision E: `SELF`-default intended, `COMPANY`-only shipped as a *named* deviation (`permissions.py:57-61`) — read now correctly *resolves* scope (any grant would be honored); **write-scope not addressed** — OPEN |
| Bank | **Yes** | **No** (Finding C) | `VIEW_BANKING` | `UPDATE_SENSITIVE` | Decision E: `SELF`-default — read matches it exactly (reference implementation); **write-scope not addressed** — OPEN |

**Pattern:** every LOCKED decision (E, F) addresses *read* visibility only. **No architecture
document anywhere states what write-scope should be** for any Employee write permission — this is
not an oversight in this audit, it is a genuine gap in the decision record itself, carried into §21
as explicit open product decisions rather than resolved by assumption here.

---

## 8. Employment Findings (F4)

**Finding A — Employment GET routes have zero data-scope enforcement.**
`router.py:215-236`: `list_employments`/`get_employment` bind `_scope: Annotated[object,
Depends(require_permission(EMPLOYEE_VIEW))]` — the underscore prefix means the resolved `DataScope`
is thrown away at the dependency-injection boundary itself. `EmploymentService.list_employments`/
`get_employment` (`service.py:468-494`) take no `scope`/`caller_employee_id` parameter at all — this
is a stricter absence than Compensation/Statutory's pre-fix "resolve, bind, discard" bug; Employment
never resolves a scope in the first place. `EmploymentRepository.get_employment`/`list_employments`
(`repository.py:177-222`) filter only `company_id` + `employee_id` (from the URL) +
`deleted_at IS NULL`.

**Concrete scenario (conceptually tested, matches Decision F's own reasoning for why this matters):**
a `REPORTING_MANAGER`-shaped role holding `EMPLOYEE.VIEW` at `REPORTEE_TREE` scope (Decision H's own
proposed default) can, today in the code, call `GET /employees/{any-employee-in-tenant}/employments`
for an employee anywhere in the company — not just their own reports — and receive the full
employment history (joining date, legal entity, status, last working day) with a `200`, not a `404`.

**As-of bypass:** moot for this route specifically — since the base (non-`as_of`) call already has
no scope check, `?as_of=` cannot "bypass" a check that never runs. Once Finding A is fixed (§22), the
fix must resolve scope *before* branching on `as_of`, exactly mirroring how `Compensation`/
`Statutory`/`Bank` already do it (`_assert_employee_visible` runs first, then the `as_of`/`list`
branch reads from the now-known-visible employee) — `test_view_compensation_as_of_cannot_bypass_scope`
is the existing reference test to mirror.

**Cross-tenant:** correctly 404s today (`test_cannot_get_employment_from_other_tenant`,
`test_other_tenant_employments_not_listed`) — the gap is scope, not tenant, isolation, consistent
with the Audit's own framing of F8.

---

## 9. Assignment Findings (F8)

**Finding B — Assignment GET routes have zero data-scope enforcement**, identical shape and root
cause to Finding A: `router.py:314-339` binds `_scope: object` for both `list_assignments`/
`get_assignment`; `EmployeeAssignmentService.list_assignments`/`get_assignment`
(`service.py:1071-1097`) take no scope parameter; `EmployeeAssignmentRepository` filters only
`company_id` + `employee_id` + `deleted_at IS NULL`.

**Wider blast radius than Employment.** `AssignmentRead` (`schemas.py:284-303`) exposes
`branch_id`, `department_id`, `designation_id`, `grade_id`, `reporting_manager_id`,
`dotted_line_manager_id`, `cost_centre_id`, `shift_id`, `work_location_type` — the complete org
placement and full reporting line (both direct and dotted) for any employee in the tenant, to any
caller holding bare `EMPLOYEE.VIEW`, regardless of scope. This is a materially richer
organizational-mapping/enumeration surface than Employment's status/date fields — a caller could
reconstruct the entire company's reporting hierarchy one `GET .../assignments` call at a time,
something Decision D and the reporting-manager self-elevation guard (`27_REPORTING_MANAGER_SECURITY_AUDIT.md`)
both treat as sensitive enough to actively guard on the *write* side, but which is currently wide
open on the *read* side.

**Cross-tenant:** correctly 404s (`test_cannot_get_assignment_from_other_tenant:1238`) — again, scope
is the gap, not tenant isolation.

**`get_assignment_as_of`** (`service.py:1099-1111`) is documented as an internal cross-module
contract (future Attendance/Leave/Payroll callers), not itself HTTP-exposed as a bare endpoint —
deliberately does not assert employee existence "callers resolving a bulk operation should not pay
for that check per call." This is fine for its stated internal-contract role; flagged only so a
future module author does not mistake it for a scope-checked public entry point.

---

## 10. Compensation Findings

**No new finding.** Confirmed secure, matching the already-shipped F2/F3 fix
(`38_EMPLOYEE_COMPENSATION_STATUTORY_DATA_SCOPE_IMPLEMENTATION_REPORT.md`): both GET routes resolve
and enforce scope via `_assert_employee_visible` → `resolve_visible_employee_ids`
(`service.py:1144-1170`), `as_of` cannot bypass it (`_assert_employee_visible` runs before the
`as_of` branch, and `test_view_compensation_as_of_cannot_bypass_scope` proves it), and `SELF`/
`REPORTEES`/`COMPANY` are each independently tested at the HTTP level.

**Write path (`create_compensation`) is Finding C** (§13) — same as every other write route in the
module, not a Compensation-specific defect.

---

## 11. Statutory Findings

**No new finding on the read side.** Confirmed secure and matching the F2/F3 fix exactly, same
pattern as Compensation (`_assert_employee_visible`, `service.py:1366-1392`), tested for `SELF`/
`REPORTEES`/`COMPANY` at the HTTP level (`test_employee_statutory.py:1065-1276`).

**One residual product-decision note, not a defect:** `permissions.py:46-61`'s docstring records
that Statutory shipped `COMPANY`-only as a **deliberate, named deviation** from Decision E's
`SELF`-by-default recommendation, "no source document proposes `SELF`/`REPORTEES`/`REPORTEE_TREE`
visibility for PF/PAN-adjacent identifier data." The F2/F3 fix means the *mechanism* now correctly
honors whatever scope is granted — but no role is actually granted a non-`COMPANY` scope for this
code today, so the deviation is currently moot in practice; it becomes live the day this permission
is ever granted at `SELF` (an OPEN PRODUCT DECISION already carried in the Audit, restated at §21
item 4, not re-litigated here).

**Write path (`create_statutory`) is Finding C.**

---

## 12. Banking Findings

**No new finding.** Banking remains the reference implementation — `SELF`-scoped GET is correctly
wired (`_assert_employee_visible`, `service.py:1611-1637`), tested for `SELF`/`COMPANY` (no
`REPORTEES` test exists, but no role is ever granted `VIEW_BANKING` at `REPORTEES` either, so this is
a coverage gap, not a live risk — tracked in §18).

**Write path (`create_bank`) is Finding C.**

---

## 13. Write-Path Findings (F9) — Finding C

**Every write route in the module is permission-gated only, company-wide, full stop** — re-confirmed
by direct code read of every service write method (`create_employee`, `update_employee`,
`deactivate_employee`, `create_employment`, `update_employment`, `terminate_employment`,
`create_assignment`, `create_compensation`, `create_statutory`, `create_bank`): **none accept a
`scope`/`caller_employee_id` parameter**, and none call `resolve_visible_employee_ids`. The target
employee's existence and tenant are checked (`_assert_employee_exists`); the caller's *authorization
over that specific target* is not.

**Concrete scenario:** a role granted `EMPLOYEE.TERMINATE` at `REPORTEES` scope (a plausible future
grant — nothing in Decision H rules it out for a custom tenant-defined role) can, in the code today,
terminate the employment of *any* employee in the company, not just their own direct reports —
identical in shape to the example vulnerability the task brief names.

**Architectural inconsistency worth flagging on its own (not a separate severity, but a
remediation-design note):** `create_assignment` (`router.py:342-375`) does not even follow the
"resolve-and-discard" pattern every other write route uses — it bypasses `require_permission()`
entirely and calls `rbac.has_permission(user.user_id, user.company_id, required_permission)`
directly, a bare boolean. **No `DataScope` object is ever constructed for this route.** A future fix
that greps for `_scope: Annotated[object, ...]` (the pattern every other write route uses) would
silently miss this route. Any remediation for Finding C must handle `create_assignment` as its own
call site, not assume the same one-line fix pattern applies uniformly.

**Why this is dormant, precisely:** confirmed via live query (§17) that zero `role_permission` rows
for any of these seven write-permission codes carry a non-`COMPANY` `data_scope` in the current
database, and confirmed via code read that no product surface exists yet that would let a tenant
admin create such a grant (`SETTINGS.ROLE.MANAGE` exists as a permission code with no endpoint/UI
behind it — the Audit's own §4 finding, not re-litigated here). The gap is real and load-bearing the
day either (a) a future default-role rollout grants any of these seven codes below `COMPANY`, or (b)
a role-management UI is built without this fix landing first.

---

## 14. Hierarchy / Self-Elevation Findings — Finding D

**Confirmed secure, unchanged, not modified by this audit:** the direct self-elevation guard
(`service.py:905-919`) — `reporting_manager_id == caller_employee_id` is rejected unconditionally,
regardless of which permission authorized the write. Verified via passing tests
(`test_reportees_scope_cannot_be_widened_via_self_assignment`, `test_self_elevation_guard_applies_to_first_assignment`).

**Confirmed theoretical risk, not newly exploitable, already named in the locked decision record —
not re-litigated as a new finding, restated here because the task brief asks explicitly:** Decision D
(`RBAC_DATA_SCOPE_DECISIONS.md`) already states plainly that "nothing at write time prevents a
multi-hop cycle (`a → b → c → a`)... only direct self-reference is blocked today," and names the fix
(a write-time chain walk up to depth 20) as a tracked, sequenced follow-up, not something this audit
needs to invent. Independently re-confirmed against current code: `_assert_manager_reference`
(`service.py:866-883`) checks only `manager_id == employee_id` and manager existence/tenancy — no
chain walk exists. Impact if exploited: `get_reportee_tree_ids`'s recursive CTE (`repository.py:280-320`)
is depth-capped (`REPORTEE_TREE_MAX_DEPTH = 20`) and ends in a `DISTINCT`, so a cycle degrades to
wasted CTE iterations and a correctness question about tree membership, not a hang or a crash —
consistent with the Audit's own F23 classification (P3).

**Newly identified this session, distinct from the guard above — Finding D proper:** the guard only
blocks the caller naming *themself*. It does **not** block the caller naming an unrelated third
party `Y` as `reporting_manager_id` for target employee `X` — this silently *expands `Y`'s own*
`REPORTEES`/`REPORTEE_TREE` visibility (a proxy escalation on `Y`'s behalf, not the caller's own).
Because `create_assignment` has no target-employee scope check at all (Finding C), this is currently
reachable by anyone holding `EMPLOYEE.TRANSFER`/`.PROMOTE` at any scope, for any two employees in the
company. **This is a consequence of Finding C, not a separate vulnerability** — once C is fixed (the
caller must be authorized over the *target* `X`), the remaining open question is a genuine, currently
undecided product question, not a defect: *should reassigning `X` to report to `Y` also require the
caller to have visibility/authority over `Y`?* No document answers this — carried to §21 as an open
product decision, not assumed here.

---

## 15. Effective-Dating / As-Of Security Findings

**Compensation/Statutory/Bank:** confirmed no bypass. Each service's `list_*`/`get_*` calls
`_assert_employee_visible` (scope check) **before** branching on `as_of` — the `as_of` lookup only
ever runs against an employee already confirmed visible. `test_view_compensation_as_of_cannot_bypass_scope`
is a direct, passing regression test for exactly this property.

**Employment/Assignment:** the question is moot, not "secure" — there is no scope check to bypass in
the first place (Findings A/B). Once fixed, the fix must adopt the identical
"visibility-check-before-as_of-branch" ordering Compensation already uses, or it would reintroduce
exactly the bypass this section confirms is currently absent elsewhere.

**Historical/future-dated rows:** none of the four effective-dated resources filter by
`effective_from`/`effective_to` as part of the *scope* decision — scope is resolved once, against the
*employee*, and then every row for that already-visible employee (past, current, future-dated) is
returned. This is correct and matches Decision D's own framing (scope answers "can I see this
employee," not "can I see this specific historical row") — no separate row-level scope exists or is
proposed anywhere.

---

## 16. Tenant / RLS Findings

**Independently re-verified this session — Audit's F1 (P0, "RLS is completely inert") is fixed, not
merely claimed fixed:**

```
hrms_dev=# SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname IN ('hrms','hrms_app');
 rolname  | rolsuper | rolbypassrls
----------+----------+--------------
 hrms     | t        | t
 hrms_app | f        | f
```

`hrms` (superuser+bypassrls) remains the migrations/schema-owner role (`MIGRATIONS_DATABASE_URL`,
`env/.env.dev.example`) — correct and expected, migrations must own and alter the schema.
`hrms_app` (the runtime role the application actually connects as — `DATABASE_URL`,
`env/.env.dev.example`) is confirmed `NOSUPERUSER`/`NOBYPASSRLS`. All six Employee tables confirmed
`relrowsecurity=t, relforcerowsecurity=t`. `tests/security/test_rls_runtime_role.py` exercises this
at the real HTTP layer under the restricted role (cross-tenant SELECT/INSERT/UPDATE/DELETE blocked,
proven twice — once through the app, once via a raw connection bypassing the app's own `WHERE
company_id` predicate entirely) and passes. **This closes the Audit's P0; it is not reopened here.**

**Data scope can never widen beyond the tenant, confirmed by construction:** every repository method
`resolve_visible_employee_ids` feeds (`get_employee`, `get_direct_report_ids`,
`get_reportee_tree_ids`, and every sub-resource's `_assert_employee_visible` → `get_employee`)
`AND`s the scope's `id IN (visible_ids)` predicate together with an explicit, separate
`company_id = :company_id` predicate — never `OR`, never a fallback. `SELF`/`REPORTEES`/`COMPANY`
combined with a cross-tenant target ID is covered by existing passing tests
(`test_scoped_actor_cannot_access_cross_tenant_employee`, plus the runtime-role test's own
cross-tenant probes for compensation/statutory/bank, `test_rls_runtime_role.py:264-266`) and, as of
the F1 fix, is now backstopped at the database layer too, not just by the application's own filter.

---

## 17. Live Verification — Role-Permission Seed State (why every finding above is dormant)

```
SELECT p.code, rp.data_scope, count(*)
FROM role_permission rp JOIN permission p ON p.id = rp.permission_id
WHERE p.code LIKE 'EMPLOYEE.%'
GROUP BY p.code, rp.data_scope ORDER BY p.code;

             code             | data_scope | count
------------------------------+------------+-------
 EMPLOYEE.CREATE              | COMPANY    |     1
 EMPLOYEE.DEACTIVATE          | COMPANY    |     1
 EMPLOYEE.PROMOTE             | COMPANY    |     1
 EMPLOYEE.TERMINATE           | COMPANY    |     1
 EMPLOYEE.TRANSFER            | COMPANY    |     1
 EMPLOYEE.UPDATE              | COMPANY    |     1
 EMPLOYEE.UPDATE_COMPENSATION | COMPANY    |     1
 EMPLOYEE.UPDATE_SENSITIVE    | COMPANY    |     1
 EMPLOYEE.VIEW                | COMPANY    |     2
 EMPLOYEE.VIEW_ALL            | COMPANY    |     1
 EMPLOYEE.VIEW_BANKING        | COMPANY    |     1
 EMPLOYEE.VIEW_COMPENSATION   | COMPANY    |     1
 EMPLOYEE.VIEW_STATUTORY      | COMPANY    |     1
```

**13 of 13 audited codes: 100% `COMPANY` scope, in the live database, right now.** Confirmed by
independent code read this session, this is not incidental — it is the only value any live code path
has ever written: `RolePermission`'s ORM default is `COMPANY`
(`core/db/models/identity.py:140`), `seed/bootstrap.py`'s `_ensure_role_permission()` and
`organisation/repository.py`'s `insert_role_permission()` (called from the real tenant-registration
flow, `organisation/service.py:299-329`) both omit `data_scope` entirely, and a repo-wide grep for
`data_scope=` in application code returns zero matches. The one migration that touches this column
(`alembic/versions/20260815120000_role_permission_data_scope.py`) only added it with a `DEFAULT
'COMPANY'`; it changed no row's value.

**Consequence:** none of Findings A/B/C/D is exploitable against any current tenant. All four are
structural authorization-chain gaps that will activate, without any further code change, the instant
a non-`COMPANY` grant exists for the affected permission — which is precisely what the Audit's own
Finding F5 (role-seeding) and Decision H (three proposed default roles) are aimed at introducing next.
**This is the entire reason this document exists as a precondition, not a suggestion.**

---

## 18. Frontend Findings

Independently re-verified against current source (`apps/web/src/app/app/employees/`,
`apps/web/src/components/employee/*`) — **no frontend defect found**; every check below is a
confirmation, not a new gap:

- **No client-side scope assumption.** The detail page gates all six sub-resource tabs
  (Employment/Assignment/Compensation/Statutory/Banking/Overview) behind a successful
  `GET /employees/{id}` first (`employees/[id]/page.tsx:279-338`) — the one route that *is*
  scope-enforced. A UI user therefore cannot reach an out-of-scope employee's tabs at all through
  normal navigation, even though Employment/Assignment's own GET routes are unscoped
  (Findings A/B) — **a direct API call bypassing the UI would still succeed against those two
  routes**; this is a backend gap the frontend does not trigger or worsen, not a frontend mitigation
  that makes the backend gap acceptable.
- **404 handling does not leak existence vs. access.** `employees/[id]/page.tsx:279-283` shows the
  identical "This employee could not be found, or you don't have access to it" copy for both cases,
  matching Decision I's own 404-not-403 contract; no panel anywhere in the module differentiates the
  two.
- **Masking is render-only, as already named and accepted:** `maskAccountNumber()`
  (`lib/employee/validate-bank.ts:55-60`) masks the *rendered* bank account number only — the full
  value is present in the API response/React state regardless. PF/ESI numbers and CTC render
  unmasked entirely (`statutory-panel.tsx:205,211`, `compensation-panel.tsx:40-42,196`). This matches
  the Audit's own F4/plaintext-banking framing — not a new finding, restated only because the task
  brief asks the question directly.
- **Every write-triggering button is conditionally rendered behind `usePermissions().can()`** — none
  rely solely on a backend 403 as their only gate (table of 10 action/permission/citation pairs
  verified directly, e.g. terminate → `EMPLOYEE.TERMINATE` at `employment-panel.tsx:201,240`,
  compensation revision → `EMPLOYEE.UPDATE_COMPENSATION` at `compensation-panel.tsx:82,185`). Every
  write handler additionally has its own 403 toast as defense-in-depth, consistent with
  `use-permissions.ts`'s own documented stance that it "never blocks a request itself" and the
  backend is the sole authority.

**No frontend change is required by this plan.** The frontend already treats the backend as
authoritative everywhere; fixing Findings A–D is a pure backend change with zero frontend follow-up
needed, beyond the existing, already-correct 403/404 handling continuing to apply once more routes
start returning those codes for out-of-scope targets.

---

## 19. Test Coverage Gaps

Required matrix (HTTP-level tests only — unit tests that construct a service directly, bypassing
`require_permission`, do not count, see note below):

| Resource | READ: SELF | READ: REPORTEES | READ: TREE | READ: COMPANY | READ: cross-tenant | WRITE: any scope | WRITE: cross-tenant |
|---|---|---|---|---|---|---|---|
| Employee (identity) | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ none | ✅ (permission-presence only) |
| Employment | ❌ none | ❌ none | ❌ none | ❌ none (untested — every call uses an unscoped default) | ✅ | ❌ none | ✅ |
| Assignment | ❌ none | ❌ none | ❌ none | ❌ none | ✅ | ❌ none (self-elevation guard tested; scope is not) | ✅ |
| Compensation | ✅ | ✅ | ❌ none (only SELF/REPORTEES/COMPANY tested) | ✅ | ✅ | ❌ none | ✅ |
| Statutory | ✅ | ✅ | ❌ none | ✅ | ✅ | ❌ none | ✅ |
| Bank | ✅ | ❌ none (only SELF/COMPANY tested) | ❌ none | ✅ | ✅ | ❌ none | ✅ |

**Gaps, precisely:**
- Employment/Assignment have **zero** scope tests of any kind — consistent with there being nothing
  implemented to test (Findings A/B). This is not "missing test coverage of working code"; it is the
  expected absence of a red test for an unimplemented control.
- **No test anywhere in the suite exercises write-path scope enforcement** — no test grants a
  write permission (`UPDATE`/`DEACTIVATE`/`TERMINATE`/`TRANSFER`/`PROMOTE`/`UPDATE_COMPENSATION`/
  `UPDATE_SENSITIVE`) at `REPORTEES`/`REPORTEE_TREE`/`SELF` scope and asserts a write to an
  out-of-scope employee is rejected. `test_reportees_scope_cannot_be_widened_via_self_assignment` and
  `test_self_elevation_guard_applies_to_first_assignment` are the closest existing tests but they
  test the *self-elevation guard* (a `COMPANY`-scoped actor naming themself as manager), not scope
  enforcement against the target employee — a materially different property.
- `REPORTEE_TREE` is untested for Compensation/Statutory/Bank GET (only `SELF`/`REPORTEES`/`COMPANY`
  are exercised for those three); `REPORTEES` is untested for Bank GET specifically. Low priority —
  the resolver itself is already fully tested for `REPORTEE_TREE` via the Employee-identity route
  (`test_reportee_tree_scope_sees_descendants_not_unrelated_branch`), so this is redundant-coverage
  risk, not resolver-correctness risk.
- **Unit tests do not substitute for HTTP-level coverage.** `test_employment_service.py`,
  `test_employee_bank_service.py`, `test_employee_statutory_service.py` instantiate the service class
  directly against a mocked/in-memory session — no `AsyncClient`, no router, `require_permission`
  never runs. The bank/statutory unit files do unit-test the scope-*filtering* logic in isolation
  (passing a `scope`/`visible_ids` argument straight to a service method), which is useful but does
  not prove the HTTP dependency chain (`require_permission` → `resolve_data_scope` → router →
  service) actually wires it through — that proof only exists at the integration-test layer, and per
  the finding above, does not yet exist for any write route.
- No `tests/security/test_employee_security.py` exists (matches the Audit's own F21) — Employee's
  real security-relevant coverage (IDOR, self-elevation, cross-tenant) is genuine but scattered
  across ordinary integration files rather than consolidated. Not blocking, worth doing alongside
  this remediation for discoverability, not before it.

---

## 20. Performance Considerations

**No new query-shape risk.** The fix for Findings A/B is "call the already-existing
`resolve_visible_employee_ids` from two more GET call sites" — the exact same resolver call
Employee/Compensation/Statutory/Bank already make once per request. `REPORTEE_TREE` resolution is a
single, depth-capped (20) recursive CTE per request, not per-row; `REPORTEES` is a single indexed
lookup against `employee_assignment_manager_idx` (a partial index on `(company_id,
reporting_manager_id) WHERE effective_to IS NULL`, already created for exactly this query shape by
`20260814100000_employee_assignment.py`, confirmed present and reused, not proposed as new work).

**The fix for Finding C** adds one resolver call per write request, at the same point
`_assert_employee_exists` already runs (an existing query on the same table, same row) — no N+1, no
new index need, no materially different cost profile than what every write route already pays.

**No premature optimization proposed or needed** — this is a "wire the existing seam through more
call sites" change, not new resolver machinery.

---

## 21. Product Decisions Required

Only decisions genuinely unresolved by any existing document — where a decision already exists, it
is cited and not reopened:

1. **Write-scope defaults are undefined for every write permission.** Decisions E/F lock *read*
   visibility defaults (`SELF` for self-service, `REPORTEES`/`REPORTEE_TREE` conditionally for
   managers, `COMPANY` for admins) but say nothing about `UPDATE`/`DEACTIVATE`/`TERMINATE`/
   `TRANSFER`/`PROMOTE`/`UPDATE_COMPENSATION`/`UPDATE_SENSITIVE`. Concretely: **should a
   `REPORTEES`-scoped `EMPLOYEE.TERMINATE` grant ever exist**, or should termination always require
   `COMPANY` scope regardless of role? Same question for `TRANSFER`/`PROMOTE` (Decision H's proposed
   `REPORTING_MANAGER` role is not granted these codes at all today, but nothing in the architecture
   forbids a tenant-defined custom role from being granted them at `REPORTEES` scope once
   role-management ships). **Recommendation, not a decision:** implement the *mechanism* (Finding C's
   fix) to correctly enforce whatever scope a grant carries, exactly mirroring how the read-side
   mechanism already works for any scope value — this makes the product decision about *defaults*
   fully deferrable without blocking the *enforcement* fix, the same separation Decision A already
   established for read scope.
2. **Should `UPDATE_COMPENSATION`/`UPDATE_SENSITIVE` (compensation/statutory/bank writes) ever be
   grantable below `COMPANY`?** Decision F recommends `REPORTEES`/`REPORTEE_TREE` for the
   *read* side of compensation when granted to managers at all; it is silent on whether a manager
   should ever be able to *write* a report's compensation without an HR admin's involvement. Same
   open question for Statutory/Bank writes, which Decision F says managers should not see
   (`COMPANY`-admin/HR-only by default) — if that read-side "no by default" is also the intended
   write-side default, it should be stated explicitly rather than left implicit.
3. **Should reassigning an employee's `reporting_manager_id` to a third party require the caller to
   also have scope/visibility over that third party** (Finding D's proxy-escalation question, §14)?
   No document answers this. Recommendation: at minimum, once Finding C's target-scope check exists,
   also require the *new* manager to be within the caller's own visible-employee set when the caller
   is not `COMPANY`-scoped — but this is a recommendation, not assumed as settled here.
4. Statutory's data-scope posture (Decision E says `SELF`-by-default; the shipped default grant is
   `COMPANY`, a **named, already-flagged deviation**, `permissions.py:57-61`) — carried forward from
   the Audit's own §22 item 4, not reopened here; the F2/F3 mechanism fix means this is now purely a
   "what should the seeded default be" question, not a "the code ignores the decision" question.

---

## 22. Recommended Implementation Phases

**Phase 1 — Employment/Assignment GET scope parity (closes Findings A/B).** Thread `scope`/
`caller_employee_id` through `list_employments`/`get_employment`/`list_assignments`/`get_assignment`
exactly as `Compensation`/`Statutory`/`Bank` already do: router binds `scope: Annotated[DataScope,
Depends(require_permission(EMPLOYEE_VIEW))]` (not `_scope: object`), passes it plus
`user.employee_id` to the service, service calls (a new) `_assert_employee_visible` (mirroring the
existing three sub-resource services' identical helper, itself calling
`EmployeeService.resolve_visible_employee_ids`) before the `as_of`/`list` branch. Out-of-scope target
→ `NotFoundError` → `404`, identical shape to nonexistent/cross-tenant, matching Decision I. Smallest,
most mechanical phase — same pattern applied twice, zero new resolver logic.

**Phase 2 — Write-path scope enforcement (closes Finding C).** For every write route
(`update_employee`, `deactivate_employee`, `create_employment`, `update_employment`,
`terminate_employment`, `create_assignment`, `create_compensation`, `create_statutory`,
`create_bank`): router changes `_scope: object` → `scope: DataScope` (and, uniquely for
`create_assignment`, replace the bare `rbac.has_permission()` call with
`rbac.resolve_data_scope()`, since no `DataScope` object exists there today at all); service adds a
target-visibility check (reusing `resolve_visible_employee_ids`) before performing the write,
raising `404` for an out-of-scope target — consistent with the read-side 404-not-403 convention, and
because a write permission implies at least the read-equivalent visibility. Sequence this after
Phase 1 (same resolver call, same pattern, lower risk once proven twice on the read side).

**Phase 3 — Hierarchy-escalation-via-write follow-up (Finding D).** Only after Product Decision 3
(§21) is resolved: add the "new manager must be within caller's visible set" check to
`_assert_manager_reference` for non-`COMPANY`-scoped callers. Do not implement speculatively before
the product decision — the current direct-self-elevation guard remains the only enforced rule until
then, and remains correct and unaffected regardless of when Phase 3 lands.

**Do not seed any non-`COMPANY` role-permission grant (Audit's F5) until Phases 1–2 are merged.**
This is the single hard sequencing constraint this entire document exists to state: seeding before
this lands would immediately convert every dormant finding above into a live one.

---

## 23. Required Regression Tests

For Phase 1 (mirror the existing Compensation/Statutory test shapes exactly, same fixtures):
- `test_list_employments_self_scope_sees_own_only`, `..._reportees_scope_sees_direct_reports_only`,
  `..._company_scope_sees_any_employee`, `..._as_of_cannot_bypass_scope` — and the `GET .../{id}`
  single-record equivalents (404 on out-of-scope, matching `test_scoped_actor_forged_id_returns_not_found`'s
  pattern).
- Identical set for Assignment, plus one added test asserting an out-of-scope caller cannot infer
  `reporting_manager_id`/org-placement fields via the single-record route either.

For Phase 2 (new shape — the currently-entirely-missing category, §19):
- For each write route: a caller holding the relevant permission at `REPORTEES` scope, targeting an
  employee **outside** their reportee set → expect `404` (not `403`, matching read-side convention).
  A second caller holding the same permission at `REPORTEES` scope, targeting an employee **inside**
  their reportee set → expect success (the positive case, proving the fix doesn't over-restrict a
  legitimately-scoped write).
- Explicit test for `create_assignment`'s unique architecture: a `REPORTEES`-scoped `EMPLOYEE.TRANSFER`
  holder attempting to transfer an out-of-scope employee → `404`, and the existing self-elevation
  guard test suite re-run to confirm the new scope check does not change that guard's own behavior
  (guard must still fire even for a `COMPANY`-scoped, fully-in-scope caller).
- Cross-tenant + scope combined, mirroring `test_rls_runtime_role.py`'s existing pattern, for at least
  one write route, to confirm the two checks compose correctly (tenant filter always wins/matches
  first, scope narrows further within-tenant).

For Phase 3 (only once built): a caller with `REPORTEES` scope reassigning employee `X` (in-scope) to
report to employee `Y` (out-of-scope third party) → rejected per whatever Product Decision 3
resolves to; a legitimate same-scope third-party reassignment (both `X` and `Y` in-scope) → succeeds,
mirroring the existing `test_legitimate_manager_change_to_third_party_still_succeeds`'s intent.

---

## 24. Explicit Exclusions

Not addressed by this document, by design (per task brief and per already-tracked-elsewhere status):
RLS/superuser remediation (independently re-verified fixed, §17); banking encryption; 
`sensitive_access_log`; audit-log field redaction; role-seeding itself (this document is its
precondition, not its implementation); pagination; frontend UX polish items (422 mapping, 409-UI
consistency, tab gating, `as_of` UI, orphaned routes); test-suite non-determinism; `REPORTEE_TREE`
read-time cycle *detection* (the write-time guard gap, Finding D, is in scope; read-time depth-cap
behavior is not). No application code, migration, schema, test, or frontend file was modified to
produce this document.

---

## 25. Definition of Done

For this document: complete when it accurately reflects independently-verified current state
(done — every claim above was checked against live code, a live database query, or an actually-read
test file, not assumed from a prior document).

For the implementation work this document specifies (future, separate task): Phase 1 done when
Employment/Assignment GET routes pass the same scope-matrix tests Compensation/Statutory already
pass, with zero change to any currently-passing test. Phase 2 done when every write route rejects an
out-of-scope target with `404` under a synthetic `REPORTEES`-scoped grant (proving the mechanism
works before any such grant is ever seeded for real), with the existing self-elevation guard and all
currently-passing lifecycle/concurrency/audit tests unchanged. Neither phase is done if it requires
seeding any non-`COMPANY` role-permission row in a real migration — the fix must be provably correct
under a *test-constructed* scoped grant first, exactly as `test_employee_data_scope.py` already
does for the Employee-identity route, with real-role seeding (F5) explicitly sequenced after, not
alongside.
