# Employee Foundation (E-01) — Implementation Report

Closeout report for the Employee Foundation vertical slice (`01_EMPLOYEE_MODULE_PLAN.md` §2
"E-01"). Scope: `employee` identity CRUD + the `EMPLOYEE_CODE` number-series allocator only. No
Employment, Assignment, Compensation, Statutory, Banking, Attendance, Leave, Payroll, ATS, ESS,
Workflow, or the BR-14 override chain were touched — confirmed in §15 below.

**Note on how this slice arrived**: the backend implementation, migration, and test suite already
existed in the working tree, uncommitted, when this task began (`01_EMPLOYEE_FOUNDATION_AUDIT.md`
had also already been written). This report is the result of independently re-verifying that work
against the authoritative docs, the live dev database, and the full validation suite — not
re-implementing it from scratch. Every claim below was checked directly, not assumed from the
pre-existing code's own comments.

---

## 1. What was implemented

- `apps/api/src/hrms/modules/employee/` package: `models.py`, `schemas.py`, `repository.py`,
  `service.py`, `router.py`, `permissions.py`, `exceptions.py`, `dependencies.py`, `__init__.py`.
- `Employee` ORM model extending the live `employee` table stub with the full identity field set
  from `02_EMPLOYEE_DATA_MODEL.md` §3, plus `is_active` (soft-deactivate parity with every other
  organisation-domain entity).
- `NumberSeries` ORM model + a race-safe `EMPLOYEE_CODE` allocator (`UPDATE ... RETURNING`, never
  `SELECT max()+1`), scoped to one company/entity-type pair per row, lazily created on first use.
- `EmployeeService`: `create_employee` (seat-limit check → code allocation → insert → audit),
  `list_employees`, `get_employee`, `update_employee` (optimistic-concurrency PATCH, deactivate/
  reactivate detection), `deactivate_employee` (soft-delete wrapper).
- Five REST endpoints (§4) wired into the app, gated by four new permission codes plus the
  pre-existing `EMPLOYEE.VIEW` (§5).
- One Alembic migration, applied and verified against the dev database (§10).
- 28 tests (11 unit + 17 integration), all passing (§10).

## 2. Database changes

One migration, `apps/api/alembic/versions/20260813180000_employee_foundation.py` (additive only,
`ADD COLUMN IF NOT EXISTS` throughout — zero rows existed in `employee` at write time, confirmed
against the dev DB, so there was no data to transform):

```sql
ALTER TABLE employee
  ADD COLUMN middle_name VARCHAR(100),
  ADD COLUMN display_name VARCHAR(200),
  ADD COLUMN blood_group VARCHAR(10),
  ADD COLUMN marital_status VARCHAR(20),
  ADD COLUMN nationality VARCHAR(80),
  ADD COLUMN personal_email VARCHAR(255),
  ADD COLUMN personal_mobile VARCHAR(20),
  ADD COLUMN photo_url TEXT,
  ADD COLUMN pan_number_enc TEXT,
  ADD COLUMN aadhaar_number_enc TEXT,
  ADD COLUMN uan_number VARCHAR(20),
  ADD COLUMN status VARCHAR(25) NOT NULL DEFAULT 'PRE_JOINING',
  ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT true;

CREATE INDEX employee_company_status_idx ON employee (company_id, status) WHERE deleted_at IS NULL;
CREATE INDEX employee_custom_fields_idx ON employee USING gin (custom_fields);
-- RLS re-asserted idempotently (already live before this migration)

CREATE TABLE number_series (
  id, company_id (FK company.id), entity_type, prefix, separator DEFAULT '-',
  current_number DEFAULT 0, padding DEFAULT 4, reset_rule DEFAULT 'NEVER', last_reset_at,
  created_at, updated_at
);
-- UNIQUE (company_id, entity_type); RLS enabled/forced with a tenant_isolation policy
```

**One documented deviation from `02_EMPLOYEE_DATA_MODEL.md` §3's proposed DDL**: `personal_email`
is `VARCHAR(255)`, not that doc's proposed `CITEXT`. The `citext` extension is not used anywhere
else in this codebase (`user.email` is plain `VARCHAR(255)`, validated at the Pydantic layer), and
data-model doc §3 explicitly labels its SQL "proposed shapes for review, not applied DDL" — this
migration follows the codebase's existing convention instead of introducing a new extension
dependency for one column. Flagged here as a deliberate, documented choice, not an oversight.

Verified live against the dev database (`\d employee`, `\d number_series`) — column set, types,
defaults, indexes, FKs, and RLS policy all match the migration exactly; `alembic current` reports
this migration as head. `employment`, `employee_assignment`, `employee_compensation` were not
touched — confirmed by direct schema inspection and by grep (§15).

No column was renamed or dropped; the downgrade path reverses every change in the same idempotent
style as every prior migration in this series.

## 3. Backend changes (files)

New (`apps/api/src/hrms/modules/employee/`): `models.py`, `schemas.py`, `repository.py`,
`service.py`, `router.py`, `permissions.py`, `exceptions.py`, `dependencies.py`, `__init__.py`.

Modified, for wiring only:
- `apps/api/src/hrms/app.py` — registers `employee_router` under `/v1`.
- `apps/api/src/hrms/seed/bootstrap.py` — seeds `EMPLOYEE_PERMISSIONS`, grants the full set to
  demo Company A's `COMPANY_ADMIN` role (unchanged: only `EMPLOYEE.VIEW` goes to the seeded
  `EMPLOYEE_VIEWER` role, which pre-dates this slice).
- `apps/api/src/hrms/modules/organisation/service.py` — `register_company` (the live tenant
  registration path, distinct from the fixed-demo-company `bootstrap.py` seed) now also grants a
  newly registered company's admin role the four new `EMPLOYEE.*` codes plus `EMPLOYEE.VIEW`,
  mirroring how every other organisation-domain permission is already granted there. This file
  also carries unrelated, pre-existing uncommitted Shift Rules changes (§15) — only the
  Employee-permission-granting lines are E-01's.
- `apps/api/tests/integration/modules/organisation/test_registration_flow.py` — asserts the five
  `EMPLOYEE.*` codes are present in `test_registration_success_full_row_graph`'s permission-set
  assertion.

No file inside `modules/organisation/` was modified to add Employee *business logic* — only the
one permission-granting call in the registration flow, which is shared wiring, not a business
rule. `department.head_employee_id` remains a plain `UUID` column (not a real FK in the ORM) —
converting it is explicitly out of scope for this slice (`01_EMPLOYEE_FOUNDATION_AUDIT.md` §1.5).

## 4. API endpoints

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/v1/employees` | `EMPLOYEE.VIEW_ALL` | Unfiltered, unpaginated list — matches the organisation module's own list shape; pagination/search/filter are E-09 scope |
| POST | `/v1/employees` | `EMPLOYEE.CREATE` | Seat-limit checked, `employee_code` system-allocated |
| GET | `/v1/employees/{id}` | `EMPLOYEE.VIEW` | Not scoped to self/team — no `employee_assignment` data exists yet to resolve a scope against (known limitation, §12) |
| PATCH | `/v1/employees/{id}` | `EMPLOYEE.UPDATE` | `If-Match: <version>` required; identity fields only |
| DELETE | `/v1/employees/{id}` | `EMPLOYEE.DEACTIVATE` | Soft-deactivate (`is_active=false`), never a hard delete; `If-Match` required |

All five follow `03_EMPLOYEE_API_PLAN.md` §2.1 exactly for this slice's subset (no
employment/assignment/compensation sub-resources — those don't exist until E-03/E-04/E-06).
`DataEnvelope`/`ListEnvelope`, cross-tenant/not-found → `404` (never `403`), and `extra="forbid"`
on both `EmployeeCreate`/`EmployeeUpdate` all match the organisation module's conventions exactly.

## 5. Permissions

Four new codes added (`employee/permissions.py`), plus the pre-existing `EMPLOYEE.VIEW`
(`identity/permissions.py`) reused as-is:

| Code | Status before this slice | This slice |
|---|---|---|
| `EMPLOYEE.VIEW` | Seeded, granted to `EMPLOYEE_VIEWER` | Reused unchanged |
| `EMPLOYEE.VIEW_ALL` | Not seeded | Added |
| `EMPLOYEE.CREATE` | Not seeded | Added |
| `EMPLOYEE.UPDATE` | Not seeded | Added |
| `EMPLOYEE.DEACTIVATE` | Not seeded | Added |

This is a deliberate subset of the documented 14-code catalogue
(`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part B9) — the other ten (`UPDATE_SENSITIVE`,
`VIEW_COMPENSATION`, `.VIEW_DOCUMENTS`, etc.) belong to later slices and were not added, matching
`01_EMPLOYEE_MODULE_PLAN.md`'s own E-01 permission list exactly. Granted to the `COMPANY_ADMIN`
system role at both bootstrap-seed time and live registration time (§3); confirmed by
`test_registration_success_full_row_graph`.

## 6. Business rules implemented

1. **`employee_code` immutability & uniqueness** — system-allocated only, `UNIQUE (company_id,
   employee_code)` (pre-existing DB constraint), never client-settable (absent from
   `EmployeeCreate`/`EmployeeUpdate`).
2. **Race-safe code allocation** — `UPDATE number_series SET current_number = current_number + 1
   ... RETURNING` inside the same transaction as the insert; verified gap-free under sequential
   creation and independently-seeded per company (tests in §10).
3. **`EMPLOYEE_SEATS` plan-limit enforcement** — `create_employee` counts active employees against
   `OrganisationService.get_subscription_summary(company_id).seat_limit` and rejects (409) before
   insert. Fails open only when no subscription is resolvable at all (a data-integrity anomaly
   unrelated to seat counting, not an actually-resolved limit) — a documented judgment call, not a
   sourced requirement (`01_EMPLOYEE_FOUNDATION_AUDIT.md` §2.4).
4. **Soft deactivate / reactivate, never hard delete** — `DELETE` and `PATCH {is_active: true}`
   both route through `update_employee`, distinguishing `EMPLOYEE_DEACTIVATED` from
   `EMPLOYEE_REACTIVATED` in the audit trail by comparing before/after state.
5. **Optimistic concurrency** — `version` + `If-Match`, `UPDATE ... WHERE version = :expected
   RETURNING`, `None` result → re-fetch → `StaleResourceError` (409, `current=...`), identical
   shape to `OrganisationService.update_grade`.
6. **Mass-assignment protection** — `employee_code`, `status`, `display_name`, `pan_number_enc`,
   `aadhaar_number_enc`, `uan_number`, `id`, `company_id`, `version` are all absent from
   `EmployeeCreate`/`EmployeeUpdate`; `extra="forbid"` rejects any attempt to set them via the API
   (422, verified by test).
7. **`status` defaults to `PRE_JOINING`** (FR-EMP-014) and has no write path or transition logic
   in this slice — correct for identity-only creation with no `employment` row yet.

## 7. Security / RLS

- **Tenant isolation**: every repository query filters `company_id` explicitly in addition to
  Postgres RLS (`FORCE ROW LEVEL SECURITY` + `tenant_isolation` policy, verified live on both
  `employee` and `number_series`) — the same belt-and-suspenders convention as the organisation
  module. Cross-tenant reads return `404`, never `403` or a leaked row (verified by test).
- **Permission enforcement**: every route gated by `require_permission(...)`; a caller holding
  only `EMPLOYEE.VIEW` is rejected with `403 PERMISSION_DENIED` on `POST /v1/employees` (verified
  by test built against a dynamically-registered tenant, not just the seeded demo role).
- **RESTRICTED fields never exposed**: `pan_number_enc`, `aadhaar_number_enc`, `uan_number` exist
  as DB columns (per `02_EMPLOYEE_DATA_MODEL.md` §3's target) but are absent from `EmployeeRead`
  entirely — not masked, not nulled, simply never serialized — because `EMPLOYEE.UPDATE_SENSITIVE`
  (the permission the data model doc gates them on) is out of E-01's scope. No read or write path
  exists for these three columns in this slice.
- **Immutable fields enforced**: `id`, `company_id`, `employee_code`, `status`, `display_name`,
  `version` cannot be set via `EmployeeCreate`/`EmployeeUpdate` regardless of request body content
  (422 on any attempt, verified by test).
- **No mass-assignment path**: both schemas use `extra="forbid"`; the service never binds a
  request body directly to the ORM model (`build_employee_update_values` only applies fields
  explicitly present in the patch).

## 8. Audit behaviour

`AuditService.record(...)` called inside the same transaction as every mutation, matching the
organisation module's convention exactly:

| Action | Fired on |
|---|---|
| `EMPLOYEE_CREATED` | `POST /v1/employees` |
| `EMPLOYEE_UPDATED` | `PATCH /v1/employees/{id}` (any field change other than an `is_active` flip) |
| `EMPLOYEE_DEACTIVATED` | `is_active: true → false` |
| `EMPLOYEE_REACTIVATED` | `is_active: false → true` |

Verified by test: audit row count, `action` value, and entity linkage all asserted for create and
deactivate paths.

## 9. Frontend changes

**None.** `01_EMPLOYEE_MODULE_PLAN.md`'s own E-01 description states "Frontend: none yet — first
usable screen ships with E-09," and `00_EMPLOYEE_AUDIT.md` §16 confirms E-01's frontend risk
column is empty. Confirmed no Employee frontend code exists anywhere in `apps/web/src`
(`find apps/web/src -iname "*employee*"` returns zero results). Building Directory/360°/wizard
screens now, ahead of Employment (E-03) and Assignment (E-04), would produce UI for an employee
that can never have a job, manager, or pay — explicitly the wrong order per the module plan's own
sequencing. No frontend work was done for this slice, and none was needed.

## 10. Tests & validation results

**Tests** — 28 total, all passing:

- `apps/api/tests/unit/modules/employee/test_employee_service.py` (11): create+audit, seat-limit
  exceeded/allowed/fail-open, get/update not-found, no-op patch, stale-version conflict,
  deactivate/reactivate distinct audit actions, deactivate-wraps-update.
- `apps/api/tests/integration/modules/employee/test_employee.py` (17): empty list, create success
  (incl. RESTRICTED-field absence from the response), gap-free code sequence, per-tenant
  independent sequence start, missing-required-field rejection (422), create/update
  mass-assignment rejection (422), get-not-found (404), update success, stale-version conflict
  (409), deactivate success + audit row, reactivate via PATCH + audit row, multi-employee list,
  cross-tenant get (404) and list (empty), permission-denied create (403, dynamically-registered
  view-only role), seat-limit enforcement (409 on the 6th create against the FREE plan's limit of
  5).

Full backend suite: **345 passed**, 0 failed (`uv run pytest` from `apps/api/`) — confirms no
regression in `organisation`/`identity`/`health` modules.

**Static checks**, all clean:
- `ruff check src tests` — all checks passed.
- `ruff format --check` — 14 employee-module files already formatted.
- `mypy src` — Success: no issues found in 73 source files.
- `lint-imports` — 1 contract kept, 0 broken (`modules → shared → core` layering intact).

**Migration**: verified applied against the running dev Postgres instance (`alembic current` →
`20260813180000 (head)`); live `\d employee` / `\d number_series` output cross-checked column-by-
column against the migration source (§2) — exact match, including RLS policy text.

No frontend validation was run (`vitest`/`tsc --noEmit`/`next build`) — no frontend code was
written for this slice (§9), so there is nothing to validate.

## 11. Documentation

- This report (`06_EMPLOYEE_FOUNDATION_IMPLEMENTATION_REPORT.md`).
- `01_EMPLOYEE_FOUNDATION_AUDIT.md` (pre-existing, the E-01-scoped audit this implementation was
  independently re-verified against — not modified by this task; no contradiction between it and
  the live repository state was found).
- `00_EMPLOYEE_AUDIT.md`, `01_EMPLOYEE_MODULE_PLAN.md`, `02_EMPLOYEE_DATA_MODEL.md`,
  `03_EMPLOYEE_API_PLAN.md`, `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` — read in full, not modified;
  no contradiction requiring a correction was found in any of them.

## 12. Known limitations (carried forward from the source docs, not newly discovered)

1. **`GET /v1/employees/{id}` is not scoped to self/team** — gated on company-wide `EMPLOYEE.VIEW`
   only. `SELF`/`REPORTEES`/`REPORTEE_TREE` scoping needs `employee_assignment.reporting_manager_id`
   data, which doesn't exist until E-04.
2. **`GET /v1/employees` has no pagination, search, or filter** — matches the organisation
   module's own list shape for this slice; the Directory's virtualization/search/filter/pagination
   contract (`docs/design/screens/01_Employee_List_Directory.md` §7) is E-09 scope.
3. **`AuthenticatedUser.employee_id` remains `None` for every login** — wiring a real
   `user_id ↔ employee_id` link into the JWT claim would mean changing `identity/service.py`'s
   login flow, which no E-01 source document asks for.
4. **Seat-limit check is not race-proof under concurrent creates** — the count-then-insert check
   in `_check_seat_limit` has no row-level lock; two simultaneous requests near the limit could
   both pass the check. The number-series allocator (the piece every source document explicitly
   calls out as needing race-safety) *is* race-safe (`UPDATE ... RETURNING`); the seat-limit count
   is a separate check with no documented atomicity requirement. Flagged here as a real,
   low-probability edge case, not silently ignored.
5. **PAN/Aadhaar/UAN have no write path yet** — columns exist; `EMPLOYEE.UPDATE_SENSITIVE` and its
   encryption-at-rest mechanism are out of scope until the slice that adds that permission (E-02
   per the module plan, or later).
6. **`department.head_employee_id` is still a plain `UUID` column in the ORM**, not a real
   `ForeignKey(Employee.id)` — now technically possible since an `Employee` ORM class exists, but
   changing it means editing `organisation/models.py`, out of scope for "Employee Foundation only."

## 13. Open decisions (unchanged by this slice — none were E-01's to resolve)

Per `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md`, the two decisions still open (`employment.status`'s
exact value set, and the `EMPLOYEE.VIEW_STATUTORY`/`.VIEW_BANKING` permission names) both belong
to `employment`/statutory/banking — none of which this slice touches. Nothing in E-01's own scope
was left undecided.

## 14. Explicit confirmation of untouched modules

Verified by direct schema inspection (`\d employment`, `\d employee_assignment`,
`\d employee_compensation` all unchanged) and by grep across `apps/api/src/hrms/modules/employee/`
and the migration for `employment|assignment|compensation|statutory|bank_account|attendance|
payroll|rehire|previous_employment|shift_id|reporting_manager` — every match found is inside a
docstring/comment explicitly stating the concept is **not** built in this slice, none in
executable code:

- **Employment / Rehire** — not implemented. `employment` table unchanged; no `Employment` ORM
  model.
- **Assignment** — not implemented. `employee_assignment` table unchanged; no `EmployeeAssignment`
  ORM model.
- **Compensation** — not implemented. `employee_compensation` table unchanged.
- **Statutory** — not implemented. `employee_statutory` table does not exist.
- **Banking** — not implemented. `employee_bank` table does not exist.
- **Attendance / Leave / Payroll** — not implemented; no code in this slice references any of
  these domains outside of explanatory comments.
- **ATS / ESS / Workflow** — not implemented; no candidate/offer/workflow-routing concept anywhere
  in this slice.
- **BR-14 override chain** — not implemented; `shift_id` does not exist on any table this slice
  touches.

Diff footprint outside `modules/employee/`, `tests/*/modules/employee/`, and the new migration:
`app.py` (+2 lines, router registration), `seed/bootstrap.py` (+7/-2, permission seeding),
`organisation/service.py` (permission-granting call in `register_company` only — the rest of that
file's diff is pre-existing, unrelated Shift Rules work), `test_registration_flow.py` (+13,
assertion update). No Employee business logic exists inside `modules/organisation/`.

## 15. Next step

Per `01_EMPLOYEE_MODULE_PLAN.md` §4 and `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part E, the next
slice is **E-03 — Employment lifecycle**, not E-02. Attendance readiness is defined as E-01 + E-03
+ E-04 + E-05; E-02 (profile completion — address, emergency contact, change-request workflow) is
not on that critical path and can be sequenced independently.

**E-03 is blocked on two product decisions that must be resolved before its migration is
written**, both already identified and *not* resolved by this task (per this task's own
instruction not to invent status values):

1. **`employment.status`'s exact value set** — undefined in every source document
   (`00_EMPLOYEE_AUDIT.md` §5 conflict row 3; `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` A1 confirms
   this is still open). The *narrowing principle* is locked (a small subset scoped to one spell,
   e.g. `ACTIVE`/`ON_NOTICE`/`TERMINATED` — never a copy of `employee.status`'s full 10-state
   machine), but the literal string values are not.
2. **Rejoin mechanics' remaining mechanical details** — the architecture (`employee_id` reused,
   new `employment` row with `is_rehire`/`previous_employment_id`) is locked
   (`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` A1/B2), but confirmation from product is still marked
   as the formal trigger before E-03's migration is finalized.

**Recommended exact next step**: obtain product sign-off on `employment.status`'s value set (a
narrow, spell-scoped enum — see above) before starting E-03. This is a decision to obtain, not a
slice to implement — E-03 itself should not begin until it lands, to avoid the second-migration
risk both `00_EMPLOYEE_AUDIT.md` §18 and `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part H flag
explicitly.
