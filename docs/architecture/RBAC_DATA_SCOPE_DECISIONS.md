# RBAC Data-Scope — Product Decision Record

**Status:** Decision record. No application code, migrations, schema, tests, or frontend code
were created or modified to produce this document. Nothing was committed.

**Date:** 2026-08-15

**Relationship to prior documents:** This record resolves the product decisions that
`docs/modules/employee/24_EMPLOYEE_RBAC_DATA_SCOPE_AUDIT.md` (the "Audit") identified but
deliberately declined to resolve (`PD-RBAC-1` through `PD-RBAC-5`), plus the additional
decisions (A–J) requested for this task. The Audit's factual findings were independently
re-verified against the running code before any decision below was made — see "Audit
Verification" at the end of this document. Nothing here overrides or contradicts a FACT finding
in the Audit; this document only adds judgment calls on top of it.

**Legend:**
- **LOCKED (this document)** — a recommendation made here with enough evidence to act on. Still
  subject to product sign-off before implementation starts, but this document takes a position
  rather than leaving it blank.
- **OPEN — PRODUCT DECISION REQUIRED** — genuinely cannot be resolved from any existing document
  or from the code; requires real operational input (customer org shapes, HR policy) this audit
  process does not have access to.

---

## Decision A — Where does scope belong? (role / user-role / hybrid)

**LOCKED: scope attaches to the `(role, permission)` grant — a new column on `role_permission`,
not on `role` and not on `user_role`.**

**Reasoning:** The Audit's own Section 10 finding is the deciding evidence here, not a fresh
consideration: Doc 19's `BR-12` requires that a Reporting Manager can see an employee's identity
(`EMPLOYEE.VIEW`) **without** automatically seeing that employee's compensation
(`EMPLOYEE.VIEW_COMPENSATION`) — "hidden from reporting managers by default." If scope lived on
the `role` (option A) or on the `user_role` assignment (option B) as a single value, every
permission a role holds would share one scope, and there would be no way to express "REPORTEES
for identity, but nothing at all for compensation" without a second role. Attaching scope to the
specific permission grant is what makes the audit's Decision F recommendation (below) expressible
at all.

**Comparison:**

| | Role definition | User-role assignment | Role×Permission grant (chosen) |
|---|---|---|---|
| Simplicity | High | Medium | High (same migration size as role-level) |
| Flexibility | Low — one scope for every permission the role holds | High — but per-user, harder to reason about | Medium-high — per-permission, same for every holder of the role |
| Security | Coarse — can't separate identity visibility from compensation visibility | Fine-grained but easy to misconfigure per-user | Matches the catalogue's own `VIEW`/`VIEW_COMPENSATION` split |
| Admin usability | Simple mental model ("this role = this scope") | Confusing ("why does Bob see more than Alice, they're both Reporting Managers?") | Simple mental model, and matches how the permission catalogue is already organized |
| Auditability | Easy | Harder (scope drifts per-user, silently) | Easy — reviewable directly from `role_permission` |
| Multi-role users | Union of role scopes, cleanly additive | Union of role scopes, cleanly additive | Union of role scopes, cleanly additive (same for all three) |
| Future branch/dept managers | Needs per-user assignment eventually (Decision B) | Already there, but pays the cost today for a need that doesn't exist yet | Deferred cleanly — extension point below |

**Consequence of choosing it:** every holder of a given role gets identical scope for a given
permission — "two Reporting Managers, one additionally responsible for a second branch" is not
expressible without a second role. This is accepted deliberately: no current document or role
requirement needs that case yet (Decision B, `DEPARTMENT`/`BRANCH`/`LEGAL_ENTITY`, is explicitly
deferred — see Decision C), and building per-user override storage now would be exactly the kind
of "generic, config-driven scope engine before a second consumer exists to validate it" the
project's own stated convention (`HRMS_SYSTEM_DESIGN_BASELINE.md §5`, restated in Audit §19)
warns against.

**Extension point, not built now:** if a genuine per-user override need surfaces later (this is
what Decision B's `DEPARTMENT`/`BRANCH`/`LEGAL_ENTITY` question is actually about), the clean
incremental path is an optional `user_role.scope_override` (nullable) that, when present, wins
over the `role_permission.data_scope` default for that specific user's holding of that role. This
is a hybrid, added later, without redesigning the role-level default. **Do not build this table
now.**

This resolves the Audit's **PD-RBAC-1**.

---

## Decision B — What determines a user's organizational scope?

**LOCKED for the scopes being implemented now (`SELF`/`REPORTEES`/`REPORTEE_TREE`): Model 2 —
derived from the user's own Employee Assignment.**

**OPEN — PRODUCT DECISION REQUIRED, for `DEPARTMENT`/`BRANCH`/`LEGAL_ENTITY` (deferred scopes,
not built in this pass — see Decision C):** whether those levels are derived-from-own-assignment
or explicitly per-user-assigned. This is the Audit's **PD-RBAC-2**, restated, not resolved. The
reason it stays open: it depends on real customer org-chart shapes (does an HR generalist's
scope always equal their own branch, or can it be "these three branches, none of which is mine")
that no document or code in this repository states. Guessing this now risks exactly the rework
the Audit warns about in its own Section 21.

**Reasoning for the LOCKED part:** for `SELF`, `REPORTEES`, and `REPORTEE_TREE`, Model 2 requires
zero new storage:
- `SELF` resolves to `AuthenticatedUser.employee_id` — already on every JWT
  (`apps/api/src/hrms/core/auth/types.py:10`), verified unused for authorization today.
- `REPORTEES`/`REPORTEE_TREE` resolve by walking `employee_assignment.reporting_manager_id` from
  the caller's own `employee_id` — already populated, already effective-dated, already
  FK-validated (`apps/api/src/hrms/modules/employee/models.py:138-143`).

Model 1 (explicit scope configuration) would require inventing new storage for information the
system already derives correctly from the org chart, for no benefit at these two levels — there
is no plausible case where a Reporting Manager's `REPORTEES` scope should be something other than
"whoever reports to them." Model 3 (hybrid) is the right eventual shape once `DEPARTMENT`/
`BRANCH`/`LEGAL_ENTITY` are built, but adopting it now, before those levels exist, is unjustified
complexity.

**One edge case this decision must handle explicitly:** a user can hold `UserCompany`/`UserRole`
without having a corresponding `Employee` row (e.g., a `COMPANY_ADMIN` who registered the company
but was never entered into the employee roster). If such a user's *effective* scope for some
permission resolves to `SELF` or `REPORTEES` (a misconfiguration — those levels shouldn't
normally be assigned to a non-employee user, but nothing prevents it structurally), the resolver
must fail to an **empty** result set (visible: nothing), not raise an unhandled error and not fall
back to `COMPANY`. Failing open here would silently reintroduce the over-grant this whole effort
exists to close.

---

## Decision C — Supported scope levels, now

**LOCKED: `COMPANY` (existing), `SELF`, `REPORTEES`, `REPORTEE_TREE`. Four levels total. Do not
build `DEPARTMENT`, `BRANCH`, `LEGAL_ENTITY`, or `ALL_COMPANIES` in this pass.**

| Level | Build now? | Why |
|---|---|---|
| `COMPANY` | Already exists | Needed for admin/HR-admin roles; zero-cost to keep as the default. |
| `SELF` | Yes | Cheapest to implement (JWT already carries `employee_id`); addresses the highest-volume real use case (an employee viewing their own record) before Attendance/Leave/Payroll self-service ships. |
| `REPORTEES` | Yes | This is literally the distinction Doc 19's `VIEW`/`VIEW_ALL` split was designed around ("what separates a Reporting Manager from an HR Manager," `19_RBAC_and_Permission_Matrix.md §2`) — building it is what finally makes the already-shipped permission catalogue mean what its own names say. |
| `REPORTEE_TREE` | Yes | Same resolver machinery as `REPORTEES` (one level vs. recursive), same source data, fully specified reference CTE already exists in Doc 19 §5 — near-zero marginal cost once `REPORTEES` is built, and needed for any manager more than one layer above their reports (a department head, not just a team lead). |
| `DEPARTMENT` / `BRANCH` / `LEGAL_ENTITY` | `BRANCH`: **Yes, as of 2026-09-23** (see Addendum below). `DEPARTMENT`/`LEGAL_ENTITY`: still No. | `BRANCH` was blocked on Decision B's genuinely open question (derived vs. explicitly-assigned) until a real customer need (multi-branch tenants managing each branch as its own unit) resolved it — see Addendum. `DEPARTMENT`/`LEGAL_ENTITY` remain blocked on the same open question, with no comparable need yet; building either interpretation now risks exactly the rework the Audit's Section 21 warns about. |
| `ALL_COMPANIES` | No | No Super Admin role or platform-level concept exists anywhere in the codebase today — this is materially different infrastructure (deliberately crossing the RLS tenant boundary), out of scope for a within-tenant data-scope fix. |

This matches, and locks, the Audit's own Section 18/19 recommendation.

---

## Decision D — Reporting hierarchy: `REPORTEES` and `REPORTEE_TREE`

**LOCKED**, defined precisely:

- **Direct reports (`REPORTEES`):** employees whose assignment row effective as of the query date
  (default: today) has `reporting_manager_id` equal to the caller's own `employee_id`. "Effective
  as of" means the existing effective-dating predicate already used elsewhere in this module:
  `effective_from <= as_of AND (effective_to IS NULL OR effective_to > as_of)`.
- **Recursive reports (`REPORTEE_TREE`):** the transitive closure of the same relation, computed
  by the recursive CTE Doc 19 §5 already fully specifies, depth-capped at 20. The depth cap bounds
  query cost; it does not detect or report a cycle — a cyclic or pathologically deep chain is
  silently truncated at depth 20, not rejected with an error. Cycle *prevention* is a separate,
  write-time concern (see Security Review, Implementation Plan §20) — the resolver's job is only
  to not hang, not to validate hierarchy correctness.
- **Effective-dated queries:** the resolver must accept the same optional `as_of` date the
  existing Employment/Assignment/Compensation list endpoints already accept, and must resolve the
  tree using assignment rows effective *as of that date*, not "today." A manager's tree as of a
  past date, after a later reporting-line change, must reflect who reported to them **then** —
  resolving against today's tree while querying historical records would produce answers that
  don't correspond to any real point in time.
- **Inactive employees (`Employee.is_active = false`, not terminated):** remain in the reporting
  tree. Deactivation does not sever the manager relationship in the data model — recommend they
  stay visible to the manager (administrative/historical continuity), since nothing about "not
  currently active" implies "was never really a report."
- **Terminated employees (`Employment.status = 'TERMINATED'`):** the termination-lifecycle fix
  already closes the employee's open `employee_assignment` row on termination (Audit §9, row 10:
  "cascades to close the employee's open assignment... rows"). This means a terminated employee
  has **no current** (`effective_to IS NULL`) assignment row — they drop out of a live `REPORTEES`/
  `REPORTEE_TREE` query automatically, with no special-case code needed. For an **as-of** query
  targeting a date before the termination, the (now-closed) assignment row is still the row
  effective on that date, so the historical tree correctly still includes them. This is a natural
  consequence of the effective-dating predicate above, not a separate rule.
- **Rehires:** a rehire creates a new `Employment` episode but reuses the same `Employee.id`. Their
  `employee_assignment` history was closed at the prior termination; a fresh assignment row (a new
  `POST .../assignments` call, per the existing E-04 flow) is required before the rehired employee
  reappears in any manager's tree — the same or a different manager, determined entirely by that
  new assignment row's `reporting_manager_id`. No rehire-specific resolver logic is needed; this
  "just works" because the resolver always reads current-or-as-of assignment state, never
  employment-episode state.
- **Cycles:** the resolver does not need its own cycle-detection logic (the depth cap already
  bounds cost). What the Audit correctly flags as a real gap is that **nothing at write time**
  prevents a multi-hop cycle (`a → b → c → a`) from being created in the first place — only direct
  self-reference is blocked today (`service.py:713-730`). This should be closed as a write-path
  guard (walk the proposed new manager's chain up to depth 20 before accepting the write), tracked
  as a follow-up sequenced early (Implementation Plan §17), because a cyclic tree — even
  truncated safely — produces a *wrong*, not just slow, `REPORTEE_TREE` result.
- **Missing managers:** `reporting_manager_id = NULL` means "no manager on record" (e.g., a
  C-suite employee, or a genuine data-entry gap). This is not an error condition — such an
  employee simply cannot appear in anyone's `REPORTEES`/`REPORTEE_TREE`, matching the existing
  nullable-FK semantics already in the schema.

---

## Decision E — What a normal Employee (`SELF` scope) can see

**LOCKED:**

| Sub-resource | `SELF` can view own? | Reasoning |
|---|---|---|
| Own identity (`GET /employees/{own_id}`) | Yes | The core `SELF` use case. |
| `GET /employees` (list) | Returns only own record | An ordinary `EMPLOYEE` role should hold `EMPLOYEE.VIEW` with `SELF` scope, not `EMPLOYEE.VIEW_ALL` — but if a role is (unusually) configured to hold `VIEW_ALL` with `SELF` scope, the resolver must still narrow the list to just the caller's own record, not treat the combination as undefined behavior. |
| Own employment | Yes | Same self-service reasoning as identity — an employee should be able to see their own employment history/status. |
| Own assignment | Yes | Same reasoning — own branch/department/designation/manager is not sensitive relative to the employee themself. |
| Own compensation | Yes, but gated by a **separate** permission (`EMPLOYEE.VIEW_COMPENSATION`), which must **also** be granted, ideally itself `SELF`-scoped. Holding `SELF`-scoped `EMPLOYEE.VIEW` does **not**, by itself, grant compensation visibility. | This is the permission/scope independence principle (Decision I) applied to `SELF`: seeing your own identity is not the same authorization as seeing your own CTC. Whether an `EMPLOYEE` role is *granted* `EMPLOYEE.VIEW_COMPENSATION` (self-scoped) by default is an HR-policy choice, not an architectural one — the mechanism supports either default; Decision H recommends granting it. |
| Own statutory / banking (once built, E-07/E-08) | Yes, same pattern as compensation — own record, separate permission code (`EMPLOYEE.VIEW_STATUTORY`/`.VIEW_BANKING`), `SELF`-scoped by default so an employee can verify their own PF number / bank account. | An employee needs to verify their own statutory/bank data is correct; this is a standard self-service need, distinct from a manager or HR needing it. |

**Explicitly not assumed:** sensitive modules do not automatically inherit `SELF` access just
because identity does. Each is analyzed on its own permission code.

---

## Decision F — What managers (`REPORTEES`/`REPORTEE_TREE`) can see

**LOCKED:**

| Sub-resource | Manager (over their scope) can view? | Reasoning |
|---|---|---|
| Identity | Yes | The entire point of a "Reporting Manager" role in Doc 19's design. |
| Employment | Yes | Needed for ordinary people-management (who's active, who's on notice). |
| Assignment | Yes | Needed to see org placement of the team the manager runs. |
| Compensation | **No, by default.** Requires a separate, explicit `EMPLOYEE.VIEW_COMPENSATION` grant, and — critically — that grant should itself carry `REPORTEES`/`REPORTEE_TREE` scope when given to a manager role, **not** `COMPANY` scope. | Directly quotes Doc 19 §7: *"Manager sees salary? No by default... the tenant may override per role."* This is also the Audit's HIGH security risk (§16, first item) — closing it means a manager who *is* granted compensation visibility only ever sees their own team's compensation, never the whole company's. This is the practical payoff of Decision A (scope-per-permission-grant): the same role can hold `REPORTEES` for `EMPLOYEE.VIEW` and, if granted at all, `REPORTEES` (not `COMPANY`) for `EMPLOYEE.VIEW_COMPENSATION`. |
| Statutory / banking | **No, by default.** | Administrative/compliance data, not something a line manager needs to run their team day-to-day; default should exclude managers entirely (a permission-grant decision, independent of scope). |

**Data scope is not field/module permission — restated as the governing principle:** a manager's
`REPORTEES` scope for `EMPLOYEE.VIEW` says *which employees* they can look up. It says nothing
about *what data* about those employees they can see — that is decided permission-code by
permission-code (Decision G). Granting a scope level for one permission never implies the same or
any scope for a different permission code.

---

## Decision G — Sensitive data (Compensation, Statutory, Banking, PII fields)

**LOCKED**, analyzed separately as instructed:

| Field/module | Permission | Scope | Sensitive-log fit |
|---|---|---|---|
| Compensation (`RESTRICTED`) | `EMPLOYEE.VIEW_COMPENSATION` / `.UPDATE_COMPENSATION` (exist) | Whatever scope the grant carries for that role (Decision A/F) — same resolver, same `employee_ids` set as any other permission for that role, just evaluated against a different permission code's `role_permission` row. | Future `sensitive_access_log` write happens inside `EmployeeCompensationService` at the exact point the "absent, not disabled" whole-sub-resource gate already lives (`router.py:362,381,397` → service methods) — one call per successful read, logging `accessor_user_id`, `subject_employee_id`, `field_or_subresource="COMPENSATION"`, `timestamp`, `request_id`. Not built in this task; this is where it plugs in later. |
| Statutory (PF/ESI/PT/tax) | New `EMPLOYEE.VIEW_STATUTORY` (not yet seeded — module unbuilt) | Same pattern as Compensation once E-07 exists. | Same seam as Compensation, in the future Statutory service. |
| Banking | New `EMPLOYEE.VIEW_BANKING` (not yet seeded — module unbuilt) | Same pattern. | Same seam, in the future Banking service. |
| PAN / Aadhaar / UAN | No permission code exists; no read/write path exists at all today (`_enc` columns are unused, and the `_enc` suffix is misleading — they are plain unencrypted strings, per Audit §10). | N/A until a write path exists. | Out of this task's scope entirely — flagged, not fixed, matches the Audit. |
| `personal_email` / `personal_mobile` (`SENSITIVE`) | **Live gap, independent of data-scope**: no `EMPLOYEE.VIEW_PERSONAL_CONTACT` permission exists; these fields serialize unconditionally to anyone holding plain `EMPLOYEE.VIEW` today. | N/A — this is a field-visibility gap, not a record-visibility gap; fixing data-scope does not fix this. | Recommend as an independent, small, fast-follow fix (add the permission code, gate the two fields in `EmployeeRead` serialization) — cheap, high-value, but must not be bundled into the data-scope task, per the Audit's own "don't conflate these two fixes" framing (§10). |

**`sensitive_access_log` — exact future fit, defined now, not built now:** a single new table
(`sensitive_access_log`: `id`, `company_id`, `accessor_user_id`, `subject_employee_id`, `field_or_subresource`,
`accessed_at`, `request_id`) written to from the service layer, at the same call site each
RESTRICTED-tier sub-resource's existing "absent, not disabled" gate already sits, one row per
successful read (not per field). This is a read-path audit log, additive to (not replacing) the
existing write-path `AuditService`. **Not part of the next implementation task** (Implementation
Plan §17) — named here only so a future task knows exactly where it attaches.

---

## Decision H — Default roles

**LOCKED — smallest useful set, resolving Audit `PD-RBAC-4` with its own Option 1
(seed a small set of default roles at company-registration time):**

| Role | Status | Purpose | Broad permissions | Data scope | Sensitive access |
|---|---|---|---|---|---|
| `COMPANY_ADMIN` | **CURRENTLY IMPLEMENTED** | Tenant owner/setup | All Organisation + all Employee permission codes | `COMPANY` on everything (unchanged — see Migration/Rollout) | Full |
| `EMPLOYEE_VIEWER` | **CURRENTLY IMPLEMENTED, demo-seed only** (`seed/bootstrap.py`), not created by real company registration | Demo/reference role | `EMPLOYEE.VIEW` only | `COMPANY` (unchanged) | None |
| `EMPLOYEE` | **PROPOSED** | Every ordinary employee's baseline self-service role | `EMPLOYEE.VIEW`, `EMPLOYEE.VIEW_COMPENSATION`, (future) `.VIEW_STATUTORY`/`.VIEW_BANKING` — no write permissions at all | `SELF` on every granted permission | Own record only, per Decision E |
| `REPORTING_MANAGER` | **PROPOSED** | Line/department managers | `EMPLOYEE.VIEW` | `REPORTEE_TREE` (recommended over `REPORTEES` — see reasoning below) | None by default (no compensation/statutory/banking grant at all) |
| `HR_ADMIN` | **PROPOSED** | Runs HR operations without necessarily owning company/billing settings | Full Employee permission catalogue (`VIEW_ALL`/`CREATE`/`UPDATE`/`DEACTIVATE`/`TERMINATE`/`TRANSFER`/`PROMOTE`/`VIEW_COMPENSATION`/`UPDATE_COMPENSATION`, future `VIEW_STATUTORY`/`VIEW_BANKING`/`UPDATE_SENSITIVE`) | `COMPANY` on everything | Full |
| `BRANCH_MANAGER` | **IMPLEMENTED as of 2026-09-23/25** (see Addendum below) | Manages one branch as its own unit, for tenants that don't use `REPORTING_MANAGER`'s hierarchy to express that | `EMPLOYEE.VIEW`, `EMPLOYEE.VIEW_ALL`, `ATTENDANCE.VIEW` | `BRANCH` on every granted permission | None by default |

**Reasoning:**
- This was deliberately **not** a large role catalogue at the time this decision was locked
  (`HR_MANAGER`, `HR_EXECUTIVE`, `BRANCH_MANAGER` were **not** proposed) — none of them were needed
  to make the four `SELF`/`REPORTEES`/`REPORTEE_TREE`/`COMPANY` levels usable, and inventing roles
  ahead of a real customer need repeats the "config-driven engine before a second consumer" mistake
  this project's own convention warns against. `BRANCH_MANAGER` was added later, once a real need
  surfaced — see Addendum below for why this one crossed that bar and the others still haven't.
- `REPORTING_MANAGER` is given `REPORTEE_TREE`, not `REPORTEES`, as the default: Doc 19 frames
  this role as the headline `REPORTEES`/`REPORTEE_TREE` use case, and a department head with two
  layers of reports is a more common real shape than a single-level team lead — `REPORTEE_TREE`
  is a strict superset at near-zero extra resolver cost (Decision C), so defaulting to the wider,
  still-correctly-scoped option avoids under-provisioning a common case. A tenant that wants a
  narrower single-level manager can be given `REPORTEES` explicitly once role management exists.
- `HR_ADMIN` is separated from `COMPANY_ADMIN` so that "runs HR operations" and "owns company
  registration/billing/org structure" are not forced to be the same person/role forever — this
  is not required for the minimal implementation to work (Decision I doesn't depend on this
  split), but seeding it now avoids a second migration later purely to split a role that already
  needs splitting conceptually.
- `EMPLOYEE_VIEWER`'s status is unchanged by this decision — it remains demo-seed-only, matching
  today's behavior, until/unless a role-management UI supersedes the whole default-role-seeding
  approach.

**Consequence of choosing this:** company registration (`organisation/service.py:register_company`)
gains four new role-seeding calls beyond today's single `COMPANY_ADMIN` grant. The registering
admin user still gets `COMPANY_ADMIN` (unchanged) — these new roles exist so a `COMPANY_ADMIN` can
assign them to *other* users, which still requires a role-assignment flow (`SETTINGS.ROLE.MANAGE`
exists as a permission code today with no UI/endpoint behind it, per Audit §4) — seeding the roles
does not by itself close that separate, already-flagged gap.

---

## Decision I — Permission + scope interaction

**LOCKED. The authorization equation:**

```
Allowed = authenticated
          AND permission_granted            (existing require_permission() check)
          AND tenant_matches                (existing get_tenant_context() 404-on-mismatch)
          AND record_within_data_scope      (new — this document's subject)
```

**Order of evaluation, and why it matters for cost:** permission check runs first and short-
circuits on failure (`403`, unchanged) — scope is never resolved for a caller who doesn't hold the
permission at all, avoiding a wasted resolver query (recursive CTE) for a request that's going to
be rejected regardless.

**`permission = YES, scope = NO`: must not return the record.** Recommended, consistent semantics:

| Case | Response | Reasoning |
|---|---|---|
| Single-record `GET` (e.g. `GET /employees/{id}`), target outside scope | **`404`**, not `403` | Matches the existing cross-tenant convention exactly (`get_tenant_context` already returns `404`, never `403`, on a company mismatch — "existence isn't disclosed," Audit §5 step 4). A `403` here would leak "this record exists, you're just not allowed to see it" — a scope-based enumeration channel this codebase already treats as unacceptable one layer up (tenant). No reason for within-tenant scope to be less careful than cross-tenant. |
| List `GET` (e.g. `GET /employees`) | Out-of-scope records are **filtered out**, never appear, no distinct status code | Standard scoped-list behavior — "fewer rows returned" is the correct shape, not an error. |
| `permission = NO` (regardless of scope) | `403`, unchanged from today | Scope is irrelevant if the permission itself isn't held. |

This resolves Decision I as requested, and gives the exact implementation contract Implementation
Plan §7/§10 build against.

---

## Decision J — List endpoint behavior

**LOCKED, architecturally (no new pagination/filtering features are being added — this defines
how scope composes with what exists and with what's added later):**

```
permission check (existing require_permission)
  → resolve scope for that specific (user, permission_code) pair (new)
  → repository builds query: WHERE company_id = :company_id AND <scope predicate>
  → existing pagination/sort/filter/search, if any, applied on top of the already-scoped query
  → COUNT uses the identical WHERE clause (including the scope predicate) as the SELECT
```

- **Scope predicate is always co-applied to both `COUNT` and `SELECT`.** A list showing 5 rows
  out of a company-wide "20 total" (i.e., a count that ignores scope) would leak headcount outside
  the caller's scope even while correctly hiding the records themselves — a small but real
  disclosure. `COUNT` must reflect the *scoped* result.
- **`as_of` / effective-dated queries:** the scope resolution itself must use the **same** `as_of`
  date the query uses (Decision D). Resolving scope against "today" while querying historical
  records against a past date would produce an internally inconsistent answer — e.g., filtering a
  2024 assignment-history query by *today's* reporting tree instead of the 2024 tree.
- **Current API surface note:** `GET /employees` (`employee/repository.py:list_employees`) does
  not implement pagination/sort/filter/search today — this section is forward-looking guidance for
  when those are added, not a requirement to build them now. The scope predicate must compose
  cleanly with them whenever they arrive; it should not need to be redesigned when they do.

---

## Audit Verification

Independent re-verification against the running code (not assumed correct because the Audit
states it) — see chat transcript for full citations; summarized here per the task's required
classification:

| Claim (Audit section) | Verification | Verdict |
|---|---|---|
| `require_permission()` always returns `DataScope(level=COMPANY)`, hard-coded (§1, §5, §8) | Read `apps/api/src/hrms/core/rbac/dependencies.py:29` directly — literal constant, no branch produces another value. | **CONFIRMED** |
| Every router discards the `DataScope` return value into an unused variable (§1, §5) | Grepped every `require_permission(...)` call site across `employee/router.py`, `organisation/router.py`, `identity/router.py` — all bind to `_scope: Annotated[object, ...]`, never read again; one exception (`employee/router.py` assignment-create route) calls `rbac.has_permission()` directly and also never consumes a scope value. | **CONFIRMED** |
| `DataScopeLevel` enum has only `COMPANY/TEAM/SELF`, `REPORTEES` doesn't exist in code (§1) | Read `core/rbac/types.py` directly. | **CONFIRMED** |
| No branch/department/legal-entity/manager filtering exists in any query (§8, §11) | Grepped `employee/repository.py` — every method filters `company_id` only; `reporting_manager_id`/`dotted_line_manager_id` appear only in `_validate_manager` write-path FK checks, never in an authorization `WHERE` clause. | **CONFIRMED** |
| `AuthenticatedUser.employee_id` exists and is unused for authorization (§12, §15) | Read `core/auth/types.py` — field exists; grepped for consuming call sites in `core/rbac`/`core/auth`/`employee/` — none found. | **CONFIRMED** |
| `employee_assignment.reporting_manager_id`/`.dotted_line_manager_id` exist, effective-dated, FK-validated (§12, §15) | Read `employee/models.py:138-143` — both present, nullable FKs to `employee.id`; effective-dating columns (`effective_from`/`effective_to`) present on the same table. | **CONFIRMED** |
| Real company-registration flow grants a single `COMPANY_ADMIN` role with all Employee permissions; no narrower role is created (§4) | Read `organisation/service.py:register_company` — confirmed: seeds `ORG.*` + `EMPLOYEE_PERMISSIONS` (all 9 codes) onto one `COMPANY_ADMIN` role; no second role-insert call anywhere in the method. | **CONFIRMED** |
| Demo seed additionally creates `EMPLOYEE_VIEWER` (`EMPLOYEE.VIEW` only), not present in the real registration path (§4) | Read `seed/bootstrap.py:68-88` — both role codes present; confirmed `EMPLOYEE_VIEWER` does not appear anywhere in `organisation/service.py`. | **CONFIRMED** |
| `user_role`/`role_permission` carry no scope column today; documented `user_role.{data_scope,scope_ref_ids,valid_from,valid_to}` don't exist in the live schema (§21) | Read `core/db/models/identity.py` — `Role`, `Permission`, `RolePermission` (composite PK only), `UserRole` (`user_company_id` + `role_id` only) — no scope-shaped column on any of them. | **CONFIRMED** |
| No Employee-specific permission-matrix test exists; only Organisation's does (§20) | `find`'d `apps/api/tests` for `*permission_matrix*`/`*rbac*`/`*scope*` — only `tests/integration/modules/organisation/test_permission_matrix.py` exists. | **CONFIRMED** |
| No frontend permission-gating mechanism exists (`usePermission`/`PermissionGate`/`hasPermission`) and no Employee UI exists at all (§14) | Grepped `apps/web/src` for those identifiers (no matches) and for `*employee*`/`*compensation*` file names (no matches). | **CONFIRMED** |
| Doc 19 §5's 8-level scope table and §1's `CAN_ACCESS` equation are quoted accurately (§2) | Read `docs/product/19_RBAC_and_Permission_Matrix.md` directly — table (lines 170-179) and equation (line 10 area) match the Audit's quotes verbatim. | **CONFIRMED** |
| Doc 19 §7 "Manager sees salary? No by default... tenant may override per role" quoted accurately (§12, cited again in Decision F above) | Read `19_RBAC_and_Permission_Matrix.md:225` directly. | **CONFIRMED** |
| `HRMS_ARCHITECTURE_DECISION_LOG.md` `DEC-019` locks the full permission catalogue, not a bundled `EMPLOYEE.MANAGE` code (§2) | Read the decision log entry directly (lines 183-193). | **CONFIRMED** |
| `00_HRMS_SYSTEM_ARCHITECTURE.md` independently names the same `user_role.data_scope` column-drift gap (§21) | Grepped and read lines 97, 326, 574, 583 of that document — matches. | **CONFIRMED** |

No claim checked came back **PARTIALLY CONFIRMED**, **NOT CONFIRMED**, or **OUTDATED**. The Audit
is accurate as of this document's date. This document does not re-verify every one of the Audit's
~150 individual statements — the sample above covers every load-bearing FACT claim the decisions
above depend on.

---

## Addendum (2026-09-23/24/25) — `BRANCH` scope + `BRANCH_MANAGER` role

**Status note:** this addendum was written after the fact — `BRANCH` (`core/rbac/types.py`),
`EmployeeService.resolve_visible_employee_ids`'s `BRANCH` branch,
`EmployeeAssignmentRepository.get_branch_colleague_ids`, the `BRANCH_MANAGER` role seeded by
`organisation/service.py::register_company`, and migrations `20260923090000_branch_manager_role`
/ `20260924090000_branch_manager_attendance_view` /
`20260925090000_branch_manager_employee_view_all` were implemented and merged into the working
tree citing "this document's `BRANCH` extension" before any such extension existed here. This
addendum is the retroactive product decision that reconciles the code with the record, not a
plan written before implementation the way Decisions A–J were. Treat the gap itself as a process
lesson: a future scope-level addition should update this document in the same change, not after.

**LOCKED, closing Decision B's open question for `BRANCH` specifically (still open for
`DEPARTMENT`/`LEGAL_ENTITY`): Model 2 — derived from the user's own current `EmployeeAssignment`,
same as `REPORTEES`/`REPORTEE_TREE`.** `BRANCH` resolves to "every employee whose *current*
assignment row (`effective_to IS NULL`) has the same `branch_id` as the caller's own current
assignment," including the caller themself (a branch manager is a colleague of their own branch,
unlike `REPORTEES`, where a manager is never their own report). No `as_of` support, no per-user
explicit assignment table — identical posture to `REPORTEES`/`REPORTEE_TREE`'s "current row only"
resolution (Decision D).

**Why `BRANCH` crossed the bar `DEPARTMENT`/`LEGAL_ENTITY` haven't:** the real customer need
Decision B's reasoning said this was blocked on has surfaced — tenants that manage each branch as
an operational unit in its own right, where the branch manager is not necessarily positioned in
the `reporting_manager_id` hierarchy `REPORTEES`/`REPORTEE_TREE` already covers (e.g., a
multi-location retail/services tenant where branch staff don't formally report to the branch
manager in the org chart, but the branch manager still needs to see who's currently posted to
their branch). `DEPARTMENT` and `LEGAL_ENTITY` have no equivalent stated need yet and remain
exactly as deferred as Decision C originally left them.

**What was actually granted, and why not more:** `BRANCH_MANAGER` holds `EMPLOYEE.VIEW`,
`EMPLOYEE.VIEW_ALL`, and `ATTENDANCE.VIEW`, all at `BRANCH` scope. `EMPLOYEE.VIEW_ALL` is needed
alongside `EMPLOYEE.VIEW` because `GET /v1/employees` (the list endpoint `/app/employees` calls)
gates on `.VIEW_ALL` while `GET /v1/employees/{id}` gates on plain `.VIEW`
(`employee/router.py`) — a gap only found once this role was verified end-to-end through the
actual UI, not from reading the seeding code alone. All three permissions' read paths resolve
scope generically through `EmployeeService.resolve_visible_employee_ids`, so `BRANCH` works for
them with no service-layer change beyond the scope resolver itself. `BRANCH_MANAGER` deliberately
does **not**
hold `ATTENDANCE.REGULARIZATION_APPROVE`, `ATTENDANCE.OVERTIME_APPROVE`, or
`LEAVE.APPLICATION_APPROVE`: those three services gate their `MANAGER`-stage approval on an exact
`resolved_approver_manager_id`/`resolved_department_head_id` identity match, and their `HR`-stage
fallback specifically requires `DataScopeLevel.COMPANY` — neither branch treats `BRANCH` as
satisfying anything today, so granting those codes at `BRANCH` scope would be a silent no-op (see
`organisation/service.py`'s `BRANCH_MANAGER_ROLE_CODE` comment). Making a branch manager a real
approver for those three workflows is a separate, not-yet-made product decision (does a branch
manager's authority over their branch's approvals bypass the actual reporting hierarchy, the way
`COMPANY` scope already bypasses it for HR? — this is materially the same shape as Decision B's
original open question, now one level higher in the approval chain) and is intentionally left
undone rather than guessed at here.

**Consequence:** `role_permission_data_scope_check` now allows `'BRANCH'` alongside `SELF`/
`REPORTEES`/`REPORTEE_TREE`/`COMPANY`. Every company registered before this shipped was backfilled
a `BRANCH_MANAGER` role (not assigned to any existing user) by the two migrations above, mirroring
`20260920090000_default_roles_backfill`'s own catch-up pattern for `HR_ADMIN`/`REPORTING_MANAGER`/
`EMPLOYEE`.
