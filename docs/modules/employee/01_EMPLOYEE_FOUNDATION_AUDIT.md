# Employee Foundation (E-01) — Implementation Audit

Status: **Read-only audit — no code, migrations, or schema changed by this document.** Scope is
narrower than `00_EMPLOYEE_AUDIT.md`: this checks exactly what E-01 (Employee identity foundation,
`01_EMPLOYEE_MODULE_PLAN.md` §2 "E-01") needs against what actually exists in the repository today,
so the implementation that follows extends real code instead of assuming the broader audit's
findings are still current. Every item below was re-verified directly against the live database
(`psql` against the dev instance) and the current `main` branch source, not recalled from the prior
audit.

---

## 1. What already exists

### 1.1 Database — `employee` table (live, verified via `\d employee` on the dev DB)

```
id, company_id, user_id, employee_code, first_name, last_name, date_of_birth, gender,
custom_fields, created_at, updated_at, deleted_at, version
```

- PK on `id`; `UNIQUE (company_id, employee_code)`; index on `company_id`.
- FKs: `company_id → company.id ON DELETE RESTRICT`, `user_id → user.id ON DELETE SET NULL`.
- RLS: `FORCE ROW LEVEL SECURITY` + `tenant_isolation` policy already active (verified live, not
  just in the migration source).
- Referenced by: `department.head_employee_id`, `employee_assignment.employee_id`,
  `employee_compensation.employee_id`, `employment.employee_id` — all live FKs.
- **Row count: 0** (verified). No production data exists in any employee-domain table — this
  migration carries zero data-loss risk.
- **No `is_active` column.** Every other organisation-module entity (Grade, Branch, Department,
  Designation, Shift) has `is_active BOOLEAN`; `employee` does not. E-01 needs one, since
  `01_EMPLOYEE_MODULE_PLAN.md` §E-01 explicitly specifies "create/get/list/deactivate/reactivate,
  following the organisation module's soft-deactivate + optimistic-concurrency pattern exactly" —
  that pattern *is* the `is_active` flip. Adding it is in scope for this migration (§3).

### 1.2 Database — `employment` / `employee_assignment` / `employee_compensation` (live, out of E-01 scope)

All three exist with the exact shape `00_EMPLOYEE_AUDIT.md §3.2-3.4` already documented — re-verified
live, unchanged since that audit. **None of these three tables are touched by this slice.** They
belong to E-03/E-04/E-06 respectively, per `01_EMPLOYEE_MODULE_PLAN.md` and this task's explicit
instruction not to implement employment episodes yet. Confirmed for the record only:
- `employee_assignment`/`employee_compensation` already carry the GiST no-overlap exclusion
  constraint at the DB level (unaffected by this migration).
- `employment` still has no `version` column (locked decision A7 in
  `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` — add it when E-03 builds this table, not now).

### 1.3 ORM models — none exist

`grep -rn "class Employee" apps/api/src` returns nothing. No `Employee`, `Employment`,
`EmployeeAssignment`, or `EmployeeCompensation` SQLAlchemy model exists anywhere in
`organisation/models.py` or elsewhere. The four live tables above have no ORM mapping at all today —
confirmed unchanged from `00_EMPLOYEE_AUDIT.md §2.1`.

### 1.4 Module package — does not exist

No `apps/api/src/hrms/modules/employee/` directory. The only module packages today are `identity`,
`health`, `organisation`. This slice creates the package from scratch, per locked decision #7.

### 1.5 Auth/JWT/RBAC integration seams already wired, waiting for Employee

- `AuthenticatedUser.employee_id: UUID | None` (`core/auth/types.py:10`) — real field, always `None`
  at runtime since nothing sets it. **Not touched by E-01** — nothing in E-01 populates this; a
  `user_id`↔`employee_id` link exists at the DB level (`employee.user_id`) but wiring the JWT claim
  to a real value would mean changing `identity/service.py`'s login flow, which is out of scope for
  an identity-only foundation slice (there is no requirement anywhere that E-01 must do this — flagged
  as a **known limitation**, not a gap in E-01 itself).
- `core/auth/jwt.py::create_access_token` already accepts and encodes an `employee_id` parameter;
  `identity/service.py:210` passes `employee_id=None` unconditionally at login/refresh. Same
  reasoning as above — this stays `None` after E-01 ships; wiring it up is a future decision (likely
  tied to ESS, not named in any E-01 source document).
- `EMPLOYEE.VIEW = "EMPLOYEE.VIEW"` already seeded (`identity/permissions.py:5`), granted to a
  seeded `EMPLOYEE_VIEWER` system role (`seed/bootstrap.py:70-83`). **Reusable as-is** — E-01 adds
  `CREATE`/`VIEW_ALL`/`UPDATE`/`DEACTIVATE` alongside it (§5).
- `SEAT_LIMIT_FEATURE_CODE = "EMPLOYEE_SEATS"` (`seed/plan_catalogue.py:11`) already seeded on every
  plan (FREE=5, STARTER=25, PROFESSIONAL=100, ENTERPRISE=unlimited). **No code enforces this
  anywhere** — confirmed still true. `OrganisationService.get_subscription_summary(company_id)`
  already resolves the *effective* seat limit (plan feature + company override), which E-01's create
  path can call directly rather than re-deriving the plan/subscription/feature-flag join logic.
- `department.head_employee_id` — live DB-level FK to `employee.id` (`ON DELETE SET NULL`), kept as
  a plain `UUID` column in `Department`'s ORM model with an explicit comment explaining why (no
  `Employee` ORM class exists to resolve against). **This audit does not change that column** — once
  an `Employee` ORM model exists after this slice, converting `Department.head_employee_id` to a
  real `ForeignKey(...)` becomes possible, but doing so means editing `organisation/models.py`, which
  is out of scope for "Employee Foundation Only." Flagged as a **future opportunity**, not part of
  this slice.

### 1.6 Number-series allocator — confirmed entirely unbuilt

`grep -rn "number_series\|NumberSeries\|allocate_next_number" apps/api/src apps/api/alembic
apps/api/scripts` returns **zero results**. `docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md` describes
this table and an `organisation/repository.py::allocate_next_number()` method as if built ("D7:
Number Series is built..."), but this describes planned Sprint 3 scope, not what actually landed —
the source tree contradicts the sprint doc. **The sprint doc also assigns this table to the
`organisation` module** (`organisation/models.py::NumberSeries`, permission
`ORG.NUMBER_SERIES.MANAGE`), which conflicts with this task's locked decision #7 ("Do NOT put
Employee implementation inside `organisation/`"). Resolution (documented here, applied in §3): build
`number_series` + the race-safe allocator **inside `modules/employee/`**, scoped to the one series
type (`EMPLOYEE_CODE`) Employee actually needs, rather than inside `organisation/`. This is a
deliberate deviation from the sprint doc's original placement, made to satisfy this task's explicit,
more recent instruction — noted so it isn't mistaken for an oversight. A future generic
multi-entity-type number-series need (candidate/offer/asset/ticket, per FR-ORG-011) can migrate this
into a shared location later; that migration is not this slice's concern.

### 1.7 Audit infrastructure — fully reusable, no gap

`AuditService.record(session, *, company_id, actor_user_id, action, entity_type, entity_id, before,
after, ip, user_agent)` (`core/audit/service.py`) is generic and already used by every
organisation-module write. **No Employee-specific change needed** — E-01 defines its own action
string constants (`EMPLOYEE_CREATED`/`_UPDATED`/`_DEACTIVATED`/`_REACTIVATED`, matching the
`<ENTITY>_CREATED/…` convention every other module follows) and calls the same shared service.

One documentation/reality gap worth recording: `docs/product/07_Backend_Architecture.md:314-333`
describes a CI-enforced, `ast`-based lint rule requiring every mutating service method to call
`audit.record`. **No such check exists in `.github/workflows/ci.yml`** — CI runs `ruff check`,
`ruff format --check`, `mypy`, `lint-imports`, and `pytest` only. This is a pre-existing gap, not
something this slice introduces or is asked to fix; E-01's code will call `audit.record` on every
mutation regardless, matching the documented intent even though no automated check enforces it.

### 1.8 Tenancy / RLS pattern — fully reusable, no gap

`TenancyMiddleware` → `TenantContext` (contextvar) → `session_scope`/`get_session` running
`SELECT set_config('app.company_id', ...)` at the start of every session → Postgres RLS policy. This
is table-agnostic; it already works correctly for `employee` today (verified: RLS is live and forced
on the table right now, with zero application code touching it yet). **No new tenancy work needed for
E-01** — every repository method just needs to filter `company_id` explicitly in addition to relying
on RLS, matching the organisation module's own "belt-and-suspenders" convention (`repository.py`
comments on `get_grade`, `get_designation`, etc.).

### 1.9 Optimistic locking pattern — fully reusable, no gap

`version INTEGER DEFAULT 1` + `UPDATE ... WHERE id = :id AND version = :expected_version RETURNING
...` + `None` result → re-fetch → `StaleResourceError` (409, `current=<entity>_to_audit_dict(...)`).
`employee.version` **already exists** on the live table (default `1`) — no migration needed for this
column specifically. The pattern itself (`update_grade` in `repository.py`/`service.py`) is copied
mechanically for `employee`.

### 1.10 Error/envelope/pagination infrastructure — fully reusable, no gap

`AppError`/`NotFoundError`/`ValidationError`/`ConflictError`/`PermissionDeniedError`/`LockedError`
(`core/errors/base.py`), `DataEnvelope`/`ListEnvelope`/`ResponseMeta`/`build_meta`
(`shared/pagination.py`, `identity/schemas.py`). No Employee-specific extension needed beyond
defining Employee's own `AppError` subclasses (`exceptions.py`, mirroring
`GradeCodeAlreadyExistsError`'s shape) for domain-specific conflicts.

### 1.11 Import-boundary enforcement — weaker than the module plan assumes

`.importlinter`'s only contract is a **layers** contract: `hrms.modules → hrms.shared → hrms.core`.
This prevents `core` from importing `modules`, but does **not** prevent one module from importing
another module's `repository`/`models` directly — `01_EMPLOYEE_MODULE_PLAN.md §1`'s claim that
cross-module imports are "enforced by the same import-linter convention already governing the
organisation module" is **not accurate as written**; no such per-module contract exists in
`.importlinter` today. This doesn't block E-01 (which has no cross-module dependency at all except
the seat-limit read, §1.5/§2.4), but it's a real gap between documentation and enforcement worth
recording — not something this slice is asked to fix.

### 1.12 Test conventions — fully reusable, no gap

`apps/api/tests/integration/modules/organisation/test_grade.py` and
`.../test_grade_service.py` (unit) are complete, current templates: `_register_tenant`/`_create_*`
helpers, `seeded_plan_catalogue` fixture (`.../organisation/conftest.py`), `_cleanup_*` teardown
helpers, and a fixed checklist (create, list, get, duplicate, mass-assignment rejection, stale-version
conflict, deactivate, reactivate, audit-row assertions, cross-tenant isolation). E-01's tests follow
this exactly, in a sibling `tests/integration/modules/employee/` / `tests/unit/modules/employee/`
tree with their own small `conftest.py` (mirroring, not modifying, the organisation one).

---

## 2. Gap analysis vs. `02_EMPLOYEE_DATA_MODEL.md §3`

### 2.1 Schema gaps (employee table) — in scope for E-01

Comparing the live 13-column table (§1.1) against `02_EMPLOYEE_DATA_MODEL.md §3`'s proposed
`ALTER TABLE employee ADD COLUMN ...` block, twelve columns are missing:

| Column | Type (per data model doc) | Client-writable in E-01? |
|---|---|---|
| `middle_name` | `VARCHAR(100)` | yes (`UPDATE`) |
| `display_name` | `VARCHAR(200)` | no — derived, not directly editable |
| `blood_group` | `VARCHAR(10)` | yes (`UPDATE`) |
| `marital_status` | `VARCHAR(20)` | yes (`UPDATE`) |
| `nationality` | `VARCHAR(80)` | yes (`UPDATE`) |
| `personal_email` | `CITEXT` | yes (`UPDATE`) — data model marks this SENSITIVE/controlled long-term (FR-EMP-009), but no `VIEW_PERSONAL_CONTACT`/change-request workflow exists yet (that's E-02); E-01 treats it as a plain field, consistent with only four permissions (§5) being in scope this slice |
| `personal_mobile` | `VARCHAR(20)` | yes (`UPDATE`), same note as above |
| `photo_url` | `TEXT` | yes (`UPDATE`) — documented as uncontrolled (FR-EMP-009) |
| `pan_number_enc` | `TEXT` | **no** — see §2.2 |
| `aadhaar_number_enc` | `TEXT` | **no** — see §2.2 |
| `uan_number` | `VARCHAR(20)` | **no** — see §2.2 |
| `status` | `VARCHAR(25) NOT NULL DEFAULT 'PRE_JOINING'` | **no** — system-managed only (§2.3) |

`custom_fields` (JSONB) already exists on the live table — not a gap, carried forward unchanged.

### 2.2 PAN/Aadhaar/UAN — column added, write path deliberately deferred

`02_EMPLOYEE_DATA_MODEL.md §2` section A marks these three fields `Edit: EMPLOYEE.UPDATE_SENSITIVE`.
`01_EMPLOYEE_MODULE_PLAN.md`'s own E-01 permission list is `EMPLOYEE.CREATE/VIEW/VIEW_ALL/
UPDATE/DEACTIVATE` — it does **not** include `UPDATE_SENSITIVE`. Adding a fifth, out-of-plan
permission to E-01 to unlock three fields would be scope expansion beyond what this slice's own
source document specifies. **Resolution**: the migration adds all three columns (they belong to the
same `employee` table §3's ALTER TABLE targets), but E-01's `EmployeeCreate`/`EmployeeUpdate` schemas
omit them entirely — the columns exist and are queryable, but nothing in this slice can write to
them yet. This is recorded as a **known limitation**, not a silent gap: the write path (and
`EMPLOYEE.UPDATE_SENSITIVE`) ships whenever the slice that actually needs it is built (E-02 per the
module plan's own sequencing, or later).

### 2.3 `employee.status` — value set resolved (Phase 0), write path also deferred

Phase 0 (this task's own decision-verification step) found the authoritative 10-value enum in
`docs/product/17_SRS_Phase1_Core_Modules.md:151` (FR-EMP-014): `PRE_JOINING`, `PROBATION`, `ACTIVE`,
`ON_NOTICE`, `SUSPENDED`, `ON_LONG_LEAVE`, `EXITED`, `ABSCONDING`, `RETIRED`, `DECEASED`. The data
model doc's own migration DDL defaults this column to `'PRE_JOINING'`, which is also the correct
default for E-01's scope: an employee created via this slice's identity-only path has no `employment`
row yet (that's E-03), so "not yet actively employed" (`PRE_JOINING`) is the only state that makes
structural sense. Per `02_EMPLOYEE_DATA_MODEL.md §2` section A, `status` is "system-managed via
lifecycle actions, not direct edit" — so, like PAN/Aadhaar/UAN, it is **not** part of
`EmployeeCreate`/`EmployeeUpdate`'s writable field set. The full FR-EMP-014 state-machine transition
logic (which states can move to which) is out of scope for E-01 entirely — no lifecycle action
exists yet to transition it, and none is required by the module plan's E-01 description.

### 2.4 `EMPLOYEE_SEATS` enforcement — in scope, one cross-module read

Confirmed still unenforced anywhere (§1.5). `01_EMPLOYEE_MODULE_PLAN.md` names this as an E-01 risk
item requiring resolution "before this slice's create path is final," and
`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` (this task's own prior architecture-decision output, §A6)
marks it **DECIDED, timing NOW**: `EmployeeService.create_employee` counts active employees against
the plan's resolved seat limit and rejects before insert. The cleanest integration point is
`OrganisationService.get_subscription_summary(company_id).seat_limit` — already resolves plan feature
+ company-override precedence correctly; no need to re-derive that join. This is a
service-to-service call (`EmployeeService` constructs an `OrganisationService` instance and calls its
public method), never a reach into `organisation.repository`/`organisation.models` directly — the
same shape `OrganisationService` itself uses internally to call `IdentityService`. No changes to
`organisation/` are made; this is a read-only call against its existing public surface.

**Edge case, decided conservatively**: `get_subscription_summary` raises `NotFoundError` if a company
has no subscription row at all. No source document specifies what employee creation should do in
that anomalous state. This slice treats it as "cannot verify a limit → do not block creation"
(fail open on missing subscription data, not fail open on an actually-resolved limit) rather than
blocking all employee creation for a data-integrity anomaly unrelated to seats. Documented as a
judgment call, not sourced from any doc.

### 2.5 Indexing gaps vs. `docs/product/08_Database_Architecture.md §12`

Two of the six documented target indexes apply to columns E-01 actually adds:
- `CREATE INDEX ON employee (company_id, status) WHERE deleted_at IS NULL;` — missing, added in §3
  (now meaningful since `status` is being added).
- `CREATE INDEX ON employee USING gin (custom_fields);` — missing even though `custom_fields` already
  exists; added in §3 since it was never built despite the column already being live.
- `CREATE INDEX ON employee (company_id, employee_code);` — **already effectively satisfied**: the
  live `UNIQUE (company_id, employee_code)` index covers the same leading columns; adding a second,
  non-unique index over the identical columns would be redundant. Not added.
- The remaining three target indexes (`employee_assignment.reporting_manager_id`,
  `employee_assignment` composite/partial) apply to a table E-01 doesn't touch — out of scope here,
  carried forward as a note for E-04.

### 2.6 FK gaps

None within E-01's own scope. `employee.company_id`/`employee.user_id` FKs are already correct and
unaffected by this migration. The FK gaps `00_EMPLOYEE_AUDIT.md §3.3` identified
(`employee_assignment`'s five unconstrained FK-shaped columns) belong to `employee_assignment`, which
this slice does not touch.

### 2.7 Versioning gaps

None for E-01. `employee.version` already exists. `employment.version` (locked decision A7) is
E-03's concern, not this slice's.

### 2.8 RLS gaps

None. `employee` RLS is live, forced, and policy-correct today. The new `number_series` table (§1.6,
§3) needs its own fresh RLS block, following the identical idempotent pattern every prior migration
in this series uses.

---

## 3. Migration plan for this slice (summary — full DDL in the implementation)

One new Alembic migration, additive only (`ADD COLUMN IF NOT EXISTS` throughout, no renames, no
drops, no data transformation — zero rows exist to transform in any case, §1.1):

1. `ALTER TABLE employee ADD COLUMN ...` — the twelve columns in §2.1, plus `is_active BOOLEAN NOT
   NULL DEFAULT true` (§1.1's soft-deactivate gap).
2. Two new indexes per §2.5.
3. Idempotent RLS re-assertion on `employee` (already live; re-asserted for consistency with the
   established per-migration convention, not because it's currently missing).
4. `CREATE TABLE number_series (...)` per the shape `docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md`
   already specified (`id, company_id, entity_type, prefix, separator DEFAULT '-', current_number
   DEFAULT 0, padding DEFAULT 4, reset_rule, last_reset_at`), `UNIQUE (company_id, entity_type)`, own
   RLS block. Placed in Employee's own migration per §1.6's resolution, not `organisation`'s.

No column is renamed, no column is dropped, no existing row is touched (there are none). Downgrade
reverses all of the above in the same idempotent style every prior migration in this series uses.

---

## 4. What could affect Attendance or Payroll later (informational — not acted on in E-01)

- `employee.status`'s resolved value set (§2.3) is exactly what Attendance's status-resolution
  precedence will read (`00_EMPLOYEE_AUDIT.md §9`) — E-01 only adds the column and its default; no
  transition logic exists yet, which is correct for this slice but means Attendance still cannot be
  built against a *complete* status contract until a later slice adds transitions.
- The seat-limit check (§2.4) and `is_active` (§1.1) are Employee-identity-level only — they say
  nothing about whether an employee has an active `employment` row, which is what Attendance/Payroll
  actually need to gate on. That contract still depends entirely on E-03.
- `number_series` (§1.6) is built scoped to `EMPLOYEE_CODE` only, per this slice's actual need — a
  future series type (candidate/offer/asset/ticket, FR-ORG-011) is out of scope and not designed for
  here beyond the table already being generic enough (`entity_type` column) to add rows to later
  without a schema change.

---

## 5. Permission catalogue delta for this slice

| Code | Status before this slice | Action |
|---|---|---|
| `EMPLOYEE.VIEW` | Seeded, granted to `EMPLOYEE_VIEWER` | Reused as-is |
| `EMPLOYEE.VIEW_ALL` | Not seeded | Add |
| `EMPLOYEE.CREATE` | Not seeded | Add |
| `EMPLOYEE.UPDATE` | Not seeded | Add |
| `EMPLOYEE.DEACTIVATE` | Not seeded | Add |

No other code from the full 14-code catalogue (locked decision #10) is touched by this slice —
`UPDATE_SENSITIVE`, `VIEW_COMPENSATION`, etc. all belong to later slices per §2.2/§2.3's reasoning.

---

## 6. Conclusion — ready to implement E-01

No open decision blocks this slice specifically: `employee.status`'s value set is resolved (Phase 0),
the two genuinely open decisions from that phase (`employment.status`, `EMPLOYEE.VIEW_STATUTORY`/
`VIEW_BANKING`) belong to `employment`/statutory/banking, none of which this slice touches. All
infrastructure this slice depends on (audit, tenancy/RLS, optimistic locking, error/envelope
conventions, test fixtures) already exists and is directly reusable. The two genuinely new pieces of
infrastructure are the `employee/` module package itself and the `number_series` allocator — both
explicitly named as E-01's own new-infrastructure items by `01_EMPLOYEE_MODULE_PLAN.md`, not
surprises discovered here.
