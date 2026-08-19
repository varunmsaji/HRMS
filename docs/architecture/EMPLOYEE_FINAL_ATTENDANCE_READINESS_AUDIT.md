# Employee Foundation — Final Attendance-Readiness Audit

**Date:** 2026-08-16
**Type:** Independent, read-only production-readiness gate. No application code, migration,
schema, test, or frontend file was modified to produce this document. Nothing was committed by
this audit.
**Method:** Every claim below was independently re-derived from the current repository state at
`HEAD = 7a8ff30` ("feat(employee): close RBAC data-scope enforcement gaps end-to-end (F4/F8/F9)",
working tree clean), the current test suite, the live dev database (`hrms_dev`, port 5433), and
direct code reads — not from trusting any prior report's claims. Three independent research
passes (router/service code, test files, RLS+data-model) were run in parallel and cross-checked
against my own direct reads of `models.py`, `repository.py`, the shift-rules module doc, the SRS,
and the master audit; where they agree, that is stated as confirmed; the one new observation
(§11) was not asked for by any prior document and is flagged as such.

---

## 1. Executive Summary

The Employee vertical — Identity, Employment, Assignment, Shift (master), Compensation,
Statutory, Banking, effective-dating, audit logging, RLS/tenant isolation, and RBAC/DataScope
enforcement — is **structurally complete and independently verified correct** as of this session.
The two outstanding P0/P1 items named by the prior master audit
(`EMPLOYEE_VERTICAL_PRODUCTION_READINESS_AUDIT.md`, written earlier in the day) that were specific
to Attendance-readiness — **F1 (RLS inert)** and **F8/F9 (read/write data-scope gaps)** — are both
**independently re-confirmed fixed** in this session, not merely claimed fixed by the reports that
did the work.

**Verdict: READY.** Attendance can begin design and implementation against the Employee
foundation today. No P0 or P1 finding remains open against Employee that blocks Attendance's own
read-only consumption of `get_employment_as_of`/`get_assignment_as_of`/employee identity. The
items still open (§11–§13) are either genuine product decisions Employee's own write-permission
holders would need resolved, low-severity P2/P3 polish, or squarely Attendance's own future build
scope (extending the Shift master, seeding Attendance's own manager-visibility roles) — none of
which gate starting Attendance's system design.

One incidental finding outside Employee's scope was surfaced during RLS verification (§11.6,
`refresh_token`/`session` tables have no RLS policy) — flagged for a separate ticket, not an
Employee or Attendance blocker.

---

## 2. Current Employee Capabilities

Independently verified present and working end-to-end (router → service → repository → DB),
backed by the full passing test suite (§18) and direct code reads:

- **Identity** (`Employee`): create, update, deactivate/reactivate, `employee_code` permanent
  across rehire (`models.py:21-62`).
- **Employment lifecycle** (`Employment`): hire, rehire (via `previous_employment_id` self-FK, no
  mutation of a closed spell), terminate (`last_working_day` DB-`CHECK`-tied to
  `status='TERMINATED'`), at-most-one-`ACTIVE`-spell guaranteed by a GiST exclusion constraint
  (`employment_no_overlap`) — a database-level guarantee, not an application check
  (`models.py:65-101`).
- **Organisation assignment** (`EmployeeAssignment`): branch/department/designation/grade/cost
  centre/reporting manager/dotted-line manager/shift/work-location-type, effective-dated,
  GiST-exclusion-protected against overlap, keyed on `employee_id` (not `employment_id`) so a
  rehire gap needs no special-casing (`models.py:104-155`).
- **Shift assignment**: `shift_id` is one field on `EmployeeAssignment`, changed the same way any
  other assignment field changes (a new effective-dated row) — there is no separate
  shift-assignment table.
- **Compensation / Statutory / Banking**: insert-only, effective-dated sub-resources, same overlap
  protection, same optimistic-concurrency (`version`+`If-Match`) and audit-logging pattern as
  Employment/Assignment.
- **Effective-dated history**: every one of the four sub-resources plus Employment/Assignment
  supports `GET .../{resource}` (full history) and `GET .../{resource}?as_of=<date>` (point-in-time
  snapshot).
- **Revisions**: handled by insert-only rows, never in-place mutation of a closed period —
  verified structurally correct (§21 of the master audit names this "must not be changed," and
  nothing in this session's changes touched it).
- **RBAC/DataScope**: SELF/REPORTEES/REPORTEE_TREE/COMPANY, now enforced on every GET and write
  route in the module (§6–§7).
- **Tenant isolation**: PostgreSQL RLS, genuinely enforced under a non-superuser,
  non-`BYPASSRLS` runtime role (§8).
- **Frontend**: full Employee UI (list, create, 6 detail tabs), verified to treat the backend as
  sole authority with no client-side scope assumption (§9 of research pass 2, confirmed).

---

## 3. Employee Lifecycle Verification

The full lifecycle `REGISTER COMPANY → CREATE EMPLOYEE → HIRE → ASSIGN → ASSIGN SHIFT →
COMPENSATION → STATUTORY → BANKING → TERMINATE → REHIRE` is exercised, in this order, by the
existing integration test suite (`test_employee.py`, `test_employment.py`,
`test_employee_assignment.py`, `test_employee_compensation.py`, `test_employee_statutory.py`,
`test_employee_banking.py`) — all passing in the full run (§18). Historical boundaries were
specifically checked:

- **Hire after an attendance date** → `get_employment_as_of` returns `None` for any date before
  `joining_date` (`repository.py:191-206`, inclusive lower bound `joining_date <= as_of`).
- **Terminated before an attendance date** → returns `None` for any date after
  `last_working_day` (inclusive upper bound, `NULL` = open-ended).
- **Rehire after a gap** → each `Employment` row independently covers only its own
  `[joining_date, last_working_day]` window; the `employment_no_overlap` GiST exclusion
  constraint guarantees the two spells cannot overlap, so a gap date returns `None` with **no
  special-case code required** — this is a structural property of the schema, not application
  logic that could drift.
- **Assignment/shift change, historical shift, future-dated assignment** — identical
  inclusive-inclusive boundary logic on `EmployeeAssignment.effective_from`/`effective_to`
  (`repository.py:333-350`), independently re-derived by direct read, not assumed.
- **Compensation changes not affecting Attendance** — confirmed: Compensation is its own
  independently effective-dated table with no FK relationship to Assignment or Attendance's
  future concerns; nothing in Attendance's needed contract (§4) touches Compensation.

---

## 4. Attendance Dependencies

What Attendance can reliably obtain from Employee today, confirmed by direct code read:

| Need | Source | Status |
|---|---|---|
| Employee identity, permanent code | `Employee.employee_code`/`display_name` (never reissued) | Ready |
| Employee active/lifecycle status | `Employee.is_active`, `Employment.status` via `get_employment_as_of` | Ready |
| Employment start date / last working day | `Employment.joining_date`/`last_working_day` | Ready |
| Branch / department / designation / grade | `EmployeeAssignment` fields, via `get_assignment_as_of` | Ready |
| Reporting manager (direct + dotted-line) | `EmployeeAssignment.reporting_manager_id`/`dotted_line_manager_id` | Ready |
| Shift assignment (which shift, which dates) | `EmployeeAssignment.shift_id` + `effective_from`/`effective_to`, via `get_assignment_as_of` | Ready |
| Shift timing / grace / break / OT-eligible flag | `Shift` master (`organisation/models.py:231-260`) | Ready, **definitional-only** — see §14 |
| Shift active/inactive state | `Shift.is_active` — plain boolean, **not itself effective-dated** | Ready, with the caveat below |
| Effective-dated assignment / employment | `get_assignment_as_of(employee_id, date)` / `get_employment_as_of(employee_id, date)` | Ready, tested (§5) |

**Caveat on Shift active/inactive:** `Shift.is_active` is a simple boolean on the master record —
there is no `effective_from`/`effective_to` on `Shift` itself. "Which shift did employee X have on
date Y" is answered entirely by `EmployeeAssignment.shift_id` + its own effective-dating, not by
any date-based state on `Shift`. This means deactivating a shift does not retroactively affect a
past `EmployeeAssignment` row that referenced it (the FK and the historical `shift_id` value
persist); it only prevents new assignments from selecting it. **This is documented, deliberate
behavior** (`docs/architecture/EMPLOYEE_VERTICAL_PRODUCTION_READINESS_AUDIT.md` F15 — "inactive
shifts remain assignable... deliberate, consistent, tested — flag for product sign-off on
intent"), re-confirmed by this session, not a defect Attendance needs to work around beyond being
aware of it.

**APIs/services Attendance should consume** — see §10.

---

## 5. Effective-Dating Verification

Independently re-derived (not assumed from any report) by reading
`EmploymentRepository.get_employment_as_of` (`repository.py:191-206`) and
`EmployeeAssignmentRepository.get_assignment_as_of` (`repository.py:333-350`):

```sql
-- Employment
joining_date <= :as_of AND (last_working_day IS NULL OR last_working_day >= :as_of)

-- Assignment (and, identically shaped, Compensation/Statutory/Bank)
effective_from <= :as_of AND (effective_to IS NULL OR effective_to >= :as_of)
```

Both boundaries are **inclusive on both ends**, `NULL` on the open end means "still open." This
correctly resolves every scenario the task brief asks to check:

- **Hired after the attendance date** → no row satisfies `joining_date <= as_of` → `None`.
- **Terminated before the attendance date** → `last_working_day < as_of` fails the upper bound →
  `None`.
- **Rehire after a gap** → each spell only covers its own range; the exclusion constraint
  guarantees no overlap; a gap date matches neither spell → `None`. No union/merge logic exists
  or is needed.
- **Assignment change / historical shift** → the historical row is returned for dates within its
  own `[effective_from, effective_to]` window; a superseding row's `effective_from` becomes the
  prior row's `effective_to` at write time (enforced by the exclusion constraint, not by
  convention).
- **Future-dated assignment / shift** → a row with `effective_from` in the future simply does not
  match `as_of = today`; `get_assignment_as_of(employee_id, today)` correctly returns the
  currently-effective row, not the future one, until that future date arrives.
- **Compensation changes that should not affect Attendance** — confirmed structurally impossible
  to leak: Compensation has its own independent `get_compensation_as_of` seam; nothing in the
  Assignment/Employment `as_of` path reads from or is influenced by Compensation.

Boundary + rehire-gap test coverage was independently located and confirmed present in
`tests/unit/modules/employee/test_employment_service.py`,
`test_employee_assignment_service.py`, and siblings for Compensation/Statutory/Bank.

**The correct "as-of" contract for Attendance to use:** `get_employment_as_of(employee_id, date)`
to gate whether an attendance day should be expected at all, and
`get_assignment_as_of(employee_id, date)` to resolve shift/branch/manager for that date — exactly
the two seams that already exist, already tested, and are explicitly documented in-code
(`repository.py:337-339`) as "the shared cross-module contract other modules (Attendance/Leave/
Payroll) will later call."

---

## 6. RBAC Verification

Independently re-derived from `router.py` and `service.py` (not from the implementation report's
own claims):

- **All 25 permission-gated routes** in the module correctly bind
  `scope: Annotated[DataScope, Depends(require_permission(CODE))]` and thread `scope` +
  `caller_employee_id` into the corresponding service call. Citations (route → router.py line /
  service-call line): `list_employees` 98/102, `get_employee` 130/134, `update_employee`
  147/156-157, `deactivate_employee` 171/181-182, `create_employment` 202/213-214,
  `list_employments` 229/239-240, `get_employment` 254/261-262, `update_employment` 279/289-290,
  `terminate_employment` 309/321-322, `list_assignments` 348/358-359, `get_assignment` 373/380-381,
  `list_compensations` 455/466-467, `get_compensation` 481/488-489, `create_compensation`
  504/518-519, `list_statutories` 549/559-560, `get_statutory` 574/581-582, `create_statutory`
  597/611-612, `list_banks` 638/648-649, `get_bank` 663/670-671, `create_bank` 686/701-702.
- **The one remaining underscore-prefixed dependency** (`_scope: Annotated[object, ...]` at
  `router.py:112`, for `POST /employees`/`create_employee`) is **not a bug** — there is no target
  employee to scope against for a create-identity call (no `employee_id` path parameter exists),
  matching the module's own docstring (`router.py:22-23`). A full-module grep for the
  resolve-then-discard antipattern (`Depends(require_permission|resolve_data_scope|has_permission(`
  bound to an underscore-prefixed name) found **no other instance**.
- **`create_assignment`** (`router.py:390-429`), the one structurally different write route
  (permission chosen at runtime by `body.change_type`), is confirmed converted from a bare
  `rbac.has_permission()` boolean to `rbac.resolve_data_scope()` (line 413) with an explicit
  `if not scope.levels: raise PermissionDeniedError` (414-417) — identical fail-closed semantics to
  `require_permission`'s own dependency. **No bare `rbac.has_permission()` call remains anywhere
  in the module** (grep: zero matches).
- **`require_permission`/`_check_permission`** (`core/rbac/dependencies.py:19-45`): confirmed a
  single `resolve_data_scope()` call both proves the permission is held and returns the scope —
  an empty `.levels` raises `PermissionDeniedError` → `403` (29-33); a non-empty result is the
  dependency's return value directly, no separate permission check exists (34, 42).
  `core/rbac/service.py:77-91`'s `resolve_data_scope` itself fails closed on an empty raw-scope
  set — never falls back to `COMPANY`.
- **Tenant context** (`core/tenancy/dependencies.py:14-38`): a mismatched `X-Company-Id` header
  against the JWT's `company_id` is rejected with `404` (not `403`, deliberately not revealing
  tenant existence), active `UserCompany` membership is verified, and the RLS GUC is explicitly
  re-set from the now-verified company id — closing a documented TOCTOU window where an earlier
  `get_session()` call may have set the GUC from an unverified header-derived value.

**Conclusion: RBAC permission resolution is correctly enforced on every route, with the runtime
role check and the scope-vs-target-visibility check both fail-closed, independently confirmed by
direct code read.**

---

## 7. DataScope Verification

Independently re-derived from `service.py`:

- **Every scoped service method calls `_assert_employee_visible` as its first statement**, before
  any other logic — confirmed for all five independently-implemented (structurally identical)
  copies: `EmploymentService` (406-434, called at 463-465 in `create_employment`),
  `EmployeeAssignmentService` (884-912, called at 1000-1002 in `create_assignment` — **before**
  the self-elevation guard at 1010-1024), `EmployeeCompensationService` (1265-1292, called at
  1307-1309), `EmployeeStatutoryService` (1485-1512, called at 1527-1529),
  `EmployeeBankService` (1727-1754, called at 1769-1771 in `create_bank`).
- **The previously-broken `create_bank` call to a nonexistent `_assert_employee_exists`** is
  confirmed **fully removed** — a full-module grep for that string returns zero matches; the fix
  to `_assert_employee_visible` is real and load-bearing (there was previously no test that could
  have passed against a `REPORTEES`-scope grant, since the old code would have raised
  `AttributeError` before returning any status code).
- **`resolve_visible_employee_ids`** (`service.py:91-138`, the single seam every check above
  threads through — confirmed no duplicate resolver logic exists anywhere): `COMPANY` short-
  circuits to `None` (no ID filter); `SELF` adds `caller_employee_id` if non-`None`;
  `REPORTEE_TREE` takes priority over `REPORTEES` when both happen to be granted (a documented
  superset optimization) and calls a depth-capped (`REPORTEE_TREE_MAX_DEPTH = 20`,
  `repository.py:25`) recursive CTE (`get_reportee_tree_ids`, 280-320); `REPORTEES` alone calls a
  single-level `get_direct_report_ids` (264-278). If `caller_employee_id is None` and only
  `SELF`/`REPORTEES`/`REPORTEE_TREE` are granted (no `COMPANY`), every branch is skipped and the
  visible set stays an **empty `frozenset()`** — fails closed, never silently widens to `COMPANY`.
- **`REPORTEE_TREE` cycle handling**: a cyclic hierarchy is **silently truncated at depth 20, not
  detected/rejected** — confirmed by the resolver's own docstring and independently proven by a
  passing test (`test_reportee_tree_scope_terminates_on_cyclic_hierarchy`,
  `test_employee_data_scope.py:536`). This is a known, named limitation (master audit's F23, P3),
  not newly introduced, and does not affect correctness for any non-cyclic (i.e., real-world)
  hierarchy — flagged again here only because the audit brief asks for it explicitly.
- **Out-of-scope target → `404`, never `403`, for both read and write, on every route** — verified
  by the passing test suite (§18) and consistent with Decision I.

**Conclusion: DataScope resolution and enforcement is a single, non-duplicated, fail-closed
mechanism, correctly wired to every route in the module.**

---

## 8. RLS Verification

Independently re-verified against the **live** dev database (not assumed from the reports):

```
 rolname  | rolsuper | rolbypassrls | rolcreatedb | rolcreaterole
----------+----------+--------------+-------------+---------------
 hrms     | t        | t            | t           | t
 hrms_app | f        | f            | f           | f
```

`hrms_app` — the role `apps/api/.env`'s `DATABASE_URL` actually connects as for all application
traffic — is confirmed `NOSUPERUSER`/`NOBYPASSRLS`/`NOCREATEDB`/`NOCREATEROLE`, holding only DML
grants (`infra/docker/postgres/init/002_app_role.sql`). `hrms` (superuser+bypassrls) is used only
via the separate `MIGRATIONS_DATABASE_URL`, for Alembic DDL — a real separation, not a naming
convention.

```
        relname        | relrowsecurity | relforcerowsecurity
------------------------+----------------+---------------------
 employee               | t              | t
 employee_assignment    | t              | t
 employee_bank          | t              | t
 employee_compensation  | t              | t
 employee_statutory     | t              | t
 employment             | t              | t
 shift                  | t              | t
```

All confirmed `FORCE ROW LEVEL SECURITY`. 20 tables total carry an identical policy:

```sql
CREATE POLICY tenant_isolation ON <table>
  USING (company_id = current_setting('app.company_id', true)::uuid);
```

`role_permission` deliberately has no RLS (join table, no `company_id` column, scoped through its
parent `role` row — documented in `20260815120000_role_permission_data_scope.py:15-19`).
`company` has `FORCE ROW LEVEL SECURITY` set but no policy and `relrowsecurity=false` by design
(it is the tenant root; `scripts/sql/002_row_level_security.sql:10-11`).

`tests/security/test_rls_runtime_role.py` (read in full) proves this is not merely
configuration-correct but **actually enforced at runtime**: it repoints the app's engine at
`hrms_app` and shows (a) same-tenant CRUD across Employee/Employment/Compensation/Statutory/
Banking works, (b) cross-tenant `GET` returns `404` through the app, and — the strongest proof —
(c) via a **raw connection bypassing all application code**, direct `SELECT`/`UPDATE`/`DELETE`
against another tenant's row return/affect **zero rows**, and a forged cross-tenant `INSERT`
raises a `DBAPIError` matching `"row-level security"`. This closes the master audit's P0 finding
F1 ("RLS is completely inert... `hrms`'s `BYPASSRLS` meant every query bypassed the policy
regardless of whether the GUC was set") — independently re-confirmed fixed this session, both by
live query and by a passing, non-mocked test.

**Conclusion: RLS is genuinely active under the runtime application role. The prior P0 is closed.**

---

## 9. Security Verification

Explicit REAL / DOCUMENTED-LIMITATION / OUT-OF-SCOPE classification, as requested:

| Item | Classification | Detail |
|---|---|---|
| Resolve-then-discard on any GET/write route | **Not found** (re-verified, zero instances) | §6 |
| Cross-tenant access via API or raw SQL | **Not found** (re-verified, RLS + app filter both block it) | §8 |
| IDOR via unscoped Employment/Assignment GET (former F8) | **Fixed, re-verified** | §6–§7 |
| Write-path scope bypass (former F9) | **Fixed, re-verified** | §7 |
| Reporting-manager **direct** self-elevation (`manager_id == caller`) | **Fixed, unmodified this session, still correctly enforced** | `_assert_manager_reference`+guard, `service.py:968-985` (reference check) / `1010-1024` (self-elevation guard), tested |
| Reporting-manager **third-party proxy escalation** (reassign `X` to report to unrelated `Y`, expanding `Y`'s own visibility) | **DOCUMENTED LIMITATION / open PRODUCT DECISION**, not newly introduced | `_assert_manager_reference` only rejects direct self-reference (975-978) plus existence/tenant checks — no chain-walk, no third-party visibility check exists. This is Phase 3 of `39_...PLAN.md`, deliberately not implemented pending Product Decision 3. **Not reachable by Attendance** — Attendance never calls `create_assignment`. |
| `as_of` bypassing scope | **Not found** — `_assert_employee_visible` runs before every `as_of` branch, on every resource, verified by direct read and by `test_view_compensation_as_of_cannot_bypass_scope`-shaped tests | §5–§7 |
| Stale-version (`If-Match`) bypass | **Not evaluated as a new item this session** — GiST-exclusion/optimistic-concurrency pattern is named in the master audit's §21 "must not be changed" list; nothing in this session's diff touched it | Out of this audit's re-verification scope; no evidence of regression |
| Mass assignment | **Not found** — every write schema is an explicit Pydantic model, no `**kwargs`-style passthrough observed in the router/service methods read | — |
| Effective-date overlap bypass | **Not found** — GiST exclusion constraints are DB-enforced, not application-level, per the master audit's own raw-SQL bypass test (not re-run this session, but the constraint itself is unmodified) | — |
| `REPORTEE_TREE` cycle write-time prevention | **DOCUMENTED LIMITATION**, P3, unchanged | §7 |
| Banking `account_number_enc` plaintext | **DOCUMENTED LIMITATION**, out of this session's scope, an already-accepted named risk (Banking E-08) | Not re-litigated |
| `refresh_token`/`session` tables missing RLS policy | **NEW, incidental finding — OUT OF EMPLOYEE/ATTENDANCE SCOPE** | §11.6 |

---

## 10. API Contract for Attendance

**B. Exact Employee APIs/services Attendance should consume:**

- `EmploymentService.get_employment_as_of(company_id, employee_id, as_of) -> Employment | None`
  — "does this employee have active employment on date Y." Use to gate whether an attendance day
  is even expected.
- `EmployeeAssignmentService.get_assignment_as_of(company_id, employee_id, as_of) -> EmployeeAssignment | None`
  — resolves `shift_id`, `branch_id`, `reporting_manager_id`, `work_location_type` for a given
  date. This is the **documented, intended cross-module seam** (its own docstring names Attendance
  explicitly). Note (already flagged by the plan documents, re-confirmed here): this method
  deliberately does **not** assert employee existence or scope on its own — it is an internal
  contract for a caller that has already established the employee is real/visible (e.g. Attendance
  iterating its own already-scoped employee set), not a bare public entry point.
- `Employee.employee_code` / `Employee.display_name` / `Employee.id` for stable record linkage
  (never reissued, including across rehire).
- `Shift` (read-only, `organisation` module) for the shift's timing/grace/break/OT-eligible
  definition, keyed by the `shift_id` resolved above.
- `EmployeeService.resolve_visible_employee_ids` — **do not build a second resolver.** When
  Attendance needs "which employees can this manager see attendance for," it should call this
  exact seam (or, more precisely, replicate its calling *pattern* against Attendance's own new
  `ATTENDANCE.*` permission codes) rather than writing new hierarchy-walking logic.

**C. Employee fields Attendance should depend on:** see the table in §4.

**D. Effective-dating rules Attendance must respect:** see §5 — inclusive-inclusive boundaries,
`NULL` = open-ended, resolve via `as_of` never via manual date-range logic re-derived per caller.

**E. RBAC/data-scope contract Attendance must follow:** every Attendance route that exposes
another employee's data must resolve a real `DataScope` (never an underscore-discarded one — see
§6, and see §14's architectural-risk note on why this specific bug shape is worth guarding
against structurally, not just by convention) and call `resolve_visible_employee_ids` before
returning data, mirroring Employee's own (now-correct) pattern exactly. Out-of-scope target → `404`,
not `403`, matching Decision I's existing convention across the whole system.

**F. Employee information Attendance must NOT duplicate:** employee identity fields, employment
status/dates, org placement, reporting-manager linkage, shift assignment/definition — all of it
should be read live via the seams above, never copied into an Attendance-owned table. Attendance
should own only what is genuinely Attendance's: punches, derived attendance-day rows, and any
Attendance-specific extension of the Shift concept (§14).

---

## 11. Remaining Employee Limitations

1. **Third-party proxy-escalation gap** (`_assert_manager_reference`, `service.py:968-985`) —
   documented, open Product Decision 3. Does not block Attendance (Attendance never calls
   `create_assignment`).
2. **`REPORTEE_TREE` cycle truncation, not detection** (`repository.py:280-320`, P3). Inherited
   risk if/when Attendance builds its own manager-hierarchy views — same risk profile Employee
   already carries, not a new one Attendance introduces.
3. **Stale docstring in `permissions.py:56-61`** — still describes Statutory GET as
   "COMPANY-only, discarding scope," which is no longer true (Statutory GET is now correctly
   scope-enforced per §6-§7). Documentation drift only, zero behavioral impact — the router's own
   docstring (`router.py:528-538`) correctly describes current behavior.
4. **`GET /employees` has no pagination** (`router.py:95-104`, `repository.py:35-52` — unbounded
   query, docstring at `repository.py:46` explicitly acknowledges pending pagination). Not called
   by Attendance's `as_of` contracts; does not block Attendance.
5. **Write-scope defaults undefined** for `TERMINATE`/`TRANSFER`/`PROMOTE`/`UPDATE_COMPENSATION`/
   `UPDATE_SENSITIVE` (Product Decisions 1–2, `39_...PLAN.md` §21). Mechanism is correct regardless
   of the eventual default; does not block Attendance, which does not hold any of these
   permissions.
6. **`refresh_token`/`session` tables have a `company_id` column but no RLS policy** — surfaced
   incidentally during this session's live RLS query, not previously documented in any Employee
   report. This is an **auth-module gap, not an Employee or Attendance-data gap** — Attendance
   does not read or write these tables. Recommend a separate, dedicated ticket to investigate;
   explicitly out of this audit's scope to fix or investigate further here.
7. **No `tests/security/test_employee_security.py`** consolidating IDOR/self-elevation/
   cross-tenant coverage in one discoverable file (master audit F21, P3) — coverage exists, just
   scattered across per-resource integration files. Cosmetic, not a blocker.
8. **Role-seeding gap (master audit F5) remains open** — `seed/bootstrap.py` seeds exactly two
   roles per company (both `COMPANY`-scoped, confirmed by grep — no `REPORTING_MANAGER`-shaped
   role exists in seed data). This means Employee's own manager-visibility (`REPORTEES`/
   `REPORTEE_TREE`) features are correctly *implemented* but not yet *exercised* by any real
   tenant role. This is a genuine prerequisite for **Leave's** approval-routing work (per the
   master audit) but is **not** a blocker for Attendance to *begin* — Attendance's own
   manager-approval/team-view features (FR-ATT-013, FR-ESS-007) will need their own
   `ATTENDANCE.*` permission codes seeded at the appropriate scope as part of Attendance's own
   build, the same way Employee's codes eventually will be — this is FUTURE MODULE work, not an
   inherited defect.

---

## 12. P0/P1/P2 Findings (this session)

**P0:** None open. The prior P0 (F1, RLS inert) is independently re-verified fixed (§8).

**P1:** None open specific to Attendance-readiness. F2/F3/F8/F9 (Statutory/Compensation
resolve-then-discard, Employment/Assignment read gap, write-path gap) are all independently
re-verified fixed (§6-§7).

**P2 (should fix before Attendance ships to production, not before Attendance design starts):**
- Stale `permissions.py` docstring (§11.3) — trivial doc fix, avoids misleading a future engineer.
- `GET /employees` pagination (§11.4, master audit F10) — will matter once Attendance/other
  modules' UIs list large employee sets, not urgent for Attendance's own `as_of`-based reads.

**PRODUCT DECISION (not P0/P1/P2, requires a human decision, not code):**
- Third-party proxy-escalation (§11.1).
- Write-scope defaults for Employee's own write permissions (§11.5).
- Statutory's `SELF`-vs-`COMPANY`-only default (already named, not reopened here).

**FUTURE MODULE (belongs to Attendance/Leave/Payroll, not Employee):**
- Role-seeding for Attendance's own manager-visibility permission codes (§11.8).
- Shift master extension — `shift_type` (FIXED/FLEXIBLE/SPLIT/ROTATIONAL), break-window JSONB,
  week-off pattern, rotation/roster, OT threshold fields — all explicitly deferred by the
  Shift Rules module's own scope document (`docs/modules/shift-rules/01_Shift_Rules_Module.md`
  §2, "Not built this slice") to a future slice, matching FR-ATT-001-004 in the SRS. This is
  Attendance's own build scope, not a gap in what Employee currently promises.
- `refresh_token`/`session` RLS gap (§11.6) — separate ticket, unrelated module.

---

## 13. Product Decisions Required (carried forward, not resolved here)

Unchanged from `39_EMPLOYEE_ACCESS_CONTROL_IMPLEMENTATION_PLAN.md` §21 and the master audit §22 —
re-confirmed still open, not reopened or resolved by this audit:

1. Should a `REPORTEES`-scoped `TRANSFER`/`PROMOTE`/`TERMINATE` grant ever exist, or should these
   always require `COMPANY` scope?
2. Should `UPDATE_COMPENSATION`/`UPDATE_SENSITIVE` ever be grantable below `COMPANY`?
3. Should reassigning `X` to report to `Y` require the caller to also have visibility over `Y`
   (the proxy-escalation question, §11.1)?
4. Statutory's `SELF`-by-default (Decision E) vs. shipped `COMPANY`-only default — still an
   accepted, named deviation, not reopened.

None of these four block Attendance.

---

## 14. Attendance Blockers

**None found that block starting Attendance design or implementation.**

Genuinely absent things worth naming so they are not mistaken for blockers-in-hiding:

- The `Shift` master is **definitional-only** today (start/end time, breaks, grace, half-day/
  full-day thresholds, night/cross-midnight/OT-eligible flags) — it has no `shift_type`, no
  flexible/split-shift fields, no roster/rotation, no week-off pattern, and (correctly) no OT
  *computation* logic (`is_ot_eligible` is a stored flag with "no OT computation exists in this
  codebase," per the Shift Rules module's own documentation). **This is not a blocker** — it is
  exactly the shape the SRS (`docs/product/17_SRS_Phase1_Core_Modules.md` §5) describes Attendance
  itself as responsible for building on top of (FR-ATT-001 through FR-ATT-004 describe fields the
  Shift Rules module's own scope doc explicitly defers to "a future Employee-Assignment/Attendance
  module"). Attendance's own system design must decide whether to extend the existing `Shift`
  table in place or layer a new Attendance-owned config on top of it — a real design decision, but
  not a prerequisite that stops the decision itself from being made.
- No `ATTENDANCE.*` permission codes or roles exist yet — expected; Attendance has not been built.

---

## 15. Attendance Readiness Decision

**READY.**

Not "READY WITH CONDITIONS" — every item that could plausibly be called a condition (§11-§13) is
either a product decision gating a *different* module's write paths (not Attendance's), or
squarely Attendance's own future build scope (Shift extension, its own role-seeding), not a gap
in what Employee currently promises to expose. The one item that is a genuine, general prerequisite
for a specific *feature* — role-seeding for manager-visibility (§11.8) — gates only Attendance's
manager-approval/team-view features, not Attendance's ability to begin design or to build its core
punch/attendance-day/status-resolution model against `get_employment_as_of`/`get_assignment_as_of`
today.

---

## 16. Recommended Attendance Architecture Starting Point

Grounded in the existing SRS (`docs/product/17_SRS_Phase1_Core_Modules.md` §5, FR-ATT-001–020,
read in full for this audit) and the Employee foundation just verified — not inventing new
requirements:

1. **Core model**, per the SRS's own stated shape: `Punch` (raw, immutable — source, timestamp,
   device/geo, direction, employee) and `AttendanceDay` (derived, recomputable — one row per
   employee per date: first-in, last-out, worked/break/OT hours, late/early minutes, resolved
   status, source of truth). Recomputation must be idempotent given the same punches + policies +
   leaves + holidays (SRS §5.1) — this is Attendance's own invariant to build and test, exactly as
   Employee built its own effective-dating invariants.
2. **Status resolution** consumes exactly the two `as_of` seams verified in §5/§10 —
   `get_employment_as_of` to gate whether a day is expected at all (excludes pre-joining/
   post-exit), `get_assignment_as_of` to resolve the day's shift and reporting line — plus a new,
   Attendance-owned `Shift`-consuming layer for grace/break/half-day math.
3. **Tenant isolation and RLS**: apply the identical `tenant_isolation` policy pattern (§8) to
   every new Attendance table from the first migration — do not defer RLS to a later remediation
   pass the way the original Employee build did (the master audit's F1 was exactly that deferred
   remediation).
4. **RBAC/DataScope**: define `ATTENDANCE.*` permission codes with their `SELF`/`REPORTEES`/
   `REPORTEE_TREE`/`COMPANY` defaults **decided and documented up front**, in an architecture
   decision log entry, before any router code is written — explicitly learning from Employee's own
   gap (§13 items 1-2, write-scope defaults were never decided until asked) rather than
   reproducing it a second time.
5. **Router discipline**: every Attendance route that resolves a `DataScope` must bind it to a
   real name and thread it into the service call — never an underscore-discarded one. The master
   audit's own §19 ("Architectural Risks") names this exact bug shape as "exactly as likely" to
   recur in any future module that copies Employee's router style; recommend treating this as a
   checklist item in Attendance's own code review, not just trusting convention.

---

## 17. Recommended Next Task

**A dedicated Attendance system-design document**, mirroring the precedent already set by
`docs/modules/employee/01_EMPLOYEE_MODULE_PLAN.md` / `02_EMPLOYEE_DATA_MODEL.md`, that resolves,
before any implementation code is written:

1. Shift-model extension approach (extend `organisation.Shift` in place vs. a new
   Attendance-owned layer referencing it) — a genuine open design question, not decided by this
   audit.
2. The `Punch`/`AttendanceDay` schema and the precise idempotent-recomputation contract (SRS
   §5.1, FR-ATT-019).
3. The precedence-ordered status resolution engine (FR-ATT-006: Not-joined/Exited > Approved
   leave > Holiday > Weekly off > Punch-derived).
4. `ATTENDANCE.*` permission codes and their `DataScope` defaults, decided up front (§16 item 4).
5. Which capture sources (SRS §5.2 — biometric, mobile GPS, web, kiosk, QR, manual, bulk import,
   RFID) are in scope for the first slice, matching this project's own pattern of shipping a
   deliberately-scoped first slice per module (cf. the Shift Rules module's own "master-only"
   first slice).

This document does not attempt to answer any of these five questions — that is explicitly the
next task's job, not this audit's.

---

## 18. Validation Results

All commands actually re-run this session (`.venv/bin/...`, from `apps/api/`), not carried over
from any prior report:

```
$ .venv/bin/python -m pytest -q
645 passed in 79.37s (0:01:19)

$ .venv/bin/ruff check .
All checks passed!

$ .venv/bin/ruff format --check .
163 files already formatted

$ .venv/bin/mypy src/hrms
Success: no issues found in 73 source files

$ .venv/bin/lint-imports
Contracts: 1 kept, 0 broken.
```

Live database checks (independently re-run against `hrms_dev`, port 5433, via `hrms_app`'s own
connection and a raw `psql` session) — see §8 for full output. Runtime role confirmed
non-superuser/non-bypassrls; all sampled Employee-family tables confirmed
`relrowsecurity=t, relforcerowsecurity=t`.

No test was skipped, xfailed, or weakened to obtain these numbers. This is a genuine re-run, not a
citation of the 645-passed figure from the prior implementation report.

---

## 19. Files / Database Inspected

**Code** (read in full or in the relevant sections, across this session and three parallel
verification passes): `apps/api/src/hrms/modules/employee/{router,service,repository,models,
permissions,exceptions,dependencies,schemas}.py`; `apps/api/src/hrms/modules/organisation/
models.py` (`Shift`); `apps/api/src/hrms/core/rbac/{dependencies,service,types}.py`;
`apps/api/src/hrms/core/tenancy/dependencies.py`; `apps/api/src/hrms/seed/bootstrap.py`;
`apps/api/src/hrms/alembic/versions/*` (RLS-bearing migrations, `role_permission` data-scope
migration).

**Tests** (read in full, not sampled): all 6 files listed in `40_..._REPORT.md` §12
(`test_employment.py`, `test_employee_assignment.py`, `test_employee_data_scope.py`,
`test_employee_compensation.py`, `test_employee_statutory.py`, `test_employee_banking.py`);
`tests/security/test_rls_runtime_role.py`; relevant unit tests for `as_of` boundary/rehire-gap
coverage.

**Frontend**: `apps/web/src/app/app/employees/**`, `apps/web/src/components/employee/*`,
`apps/web/src/lib/employee/validate-bank.ts`, `apps/web/src/lib/auth/use-permissions.ts`.

**Docs**: `docs/modules/employee/39_...PLAN.md`, `40_...REPORT.md`, `37_...DOMAIN_INTEGRATION_
AUDIT.md` (§19-22, prior Attendance/Leave/Payroll dependency assessments), `38_...DATA_SCOPE_
REPORT.md`; `docs/architecture/EMPLOYEE_VERTICAL_PRODUCTION_READINESS_AUDIT.md` (full findings
list F1-F23, §15-23); `docs/architecture/POSTGRES_RLS_ROLE_MIGRATION_PLAN.md` and `..._REPORT.md`;
`docs/architecture/RBAC_DATA_SCOPE_DECISIONS.md`; `docs/modules/shift-rules/00_SHIFT_RULES_
AUDIT.md`, `01_Shift_Rules_Module.md`; `docs/product/17_SRS_Phase1_Core_Modules.md` §5 (Attendance
requirements, read in full); `docs/product/VERSION_1_ROADMAP.md`.

**Database**: `hrms_dev` (port 5433) — `pg_roles` (`hrms`, `hrms_app`), `pg_class`/`pg_policy` for
all RLS-bearing tables, `role_permission` join to `permission` for all `EMPLOYEE.*` codes.

**Repository-wide search**: confirmed no `attendance` module directory, model, service, or router
exists anywhere under `apps/`; confirmed no resolve-then-discard pattern remains anywhere in the
Employee module.

---

## 20. Final Sign-Off Statement

**The Employee foundation can be frozen and Attendance design can begin.**

Every claim in the prior implementation reports (`39_`, `40_`) that this audit set out to
independently verify was re-derived from current code, current tests, and the live database —
none of it was taken on trust — and every one of them held up. No P0 or P1 finding remains open
against Employee. RLS is genuinely enforced under a non-privileged runtime role, proven by a
non-mocked test that bypasses the application entirely. Data-scope enforcement is a single,
correctly-wired mechanism across every read and write route in the module, with no
resolve-then-discard instance left anywhere. The two `as_of` contracts Attendance needs
(`get_employment_as_of`, `get_assignment_as_of`) are correct, tested for every boundary condition
the task brief named, and already documented in-code as Attendance's intended entry point. The
items still open are either product decisions specific to Employee's own write permissions
(unreachable by Attendance), low-severity polish, or squarely Attendance's own future build scope
— none of them require Employee code to change before Attendance's system design can start.
