# Employment Lifecycle (E-03) — Implementation Report

Closeout report for the Employment Lifecycle vertical slice
(`01_EMPLOYEE_MODULE_PLAN.md` §2 "E-03"), narrowed to the exact scope authorized for this task
(see §16 below). Builds directly on E-01 (Employee Foundation, COMPLETE, 345/345 tests
verified before this task started — `06_EMPLOYEE_FOUNDATION_IMPLEMENTATION_REPORT.md`).

---

## 1. E-03 status

**COMPLETE**, for the scope authorized by this task. `employment.status`'s value set — the
decision `07_EMPLOYMENT_STATUS_DECISION.md` investigated but left as **BLOCKED** pending
product sign-off — was resolved by this task's own authoritative instruction, not re-derived
here: exactly two stored values, `ACTIVE`/`TERMINATED`; no stored `ON_NOTICE`; `TERMINATED`,
not `EXITED`. This matches that document's own "Option B" recommendation (§6) exactly.

Confirmation/probation workflow (FR-EMP-010, `.CONFIRM`), inter-entity transfer (FR-EMP-011),
and the rejoin-linking wizard UX are **not** part of this task's authorized scope (the task's
own "at minimum verify" list covers create/read/update/terminate/rehire only) and were not
built — flagged as a known limitation (§16), not silently dropped.

## 2. Files created

```
apps/api/alembic/versions/20260814090000_employment_lifecycle.py
apps/api/tests/unit/modules/employee/test_employment_service.py
apps/api/tests/integration/modules/employee/test_employment.py
docs/modules/employee/08_EMPLOYMENT_LIFECYCLE_IMPLEMENTATION_REPORT.md  (this document)
```

## 3. Files modified

```
apps/api/src/hrms/modules/employee/models.py        (+ Employment ORM model)
apps/api/src/hrms/modules/employee/schemas.py        (+ Employment* schemas)
apps/api/src/hrms/modules/employee/repository.py     (+ EmploymentRepository)
apps/api/src/hrms/modules/employee/service.py        (+ EmploymentService)
apps/api/src/hrms/modules/employee/router.py         (+ 5 employment routes)
apps/api/src/hrms/modules/employee/exceptions.py     (+ 4 exception classes)
apps/api/src/hrms/modules/employee/permissions.py    (+ EMPLOYEE.TERMINATE)
apps/api/src/hrms/modules/employee/dependencies.py   (+ get_employment_service)
apps/api/tests/integration/modules/organisation/test_registration_flow.py
    (permission-set assertion updated to include the new EMPLOYEE.TERMINATE code —
    the same one-line-per-code update E-01 made to this same test for its own four codes)
```

No file inside `modules/organisation/`, `modules/identity/`, or `apps/web/` was modified
beyond that one assertion. `app.py` and `seed/bootstrap.py` required **no changes** — the
employment routes live in the already-registered `employee_router`, and
`EMPLOYEE_PERMISSIONS`/`register_company`'s permission grant both iterate the module's
permission list dynamically, so the new `EMPLOYEE.TERMINATE` code was picked up automatically.

## 4. Database changes

One migration, `20260814090000_employment_lifecycle.py`, applied and verified against the dev
database (`employment` had zero rows at write time — confirmed — so every change was safe to
apply directly, no data transform needed):

- `exit_date` renamed to `last_working_day` (same fact the live column already held; the data
  model doc's proposed `ADD COLUMN last_working_day` alongside the pre-existing `exit_date`
  would have left two overlapping "end of spell" columns — a rename avoids that redundancy and
  adopts this task's own authoritative field name).
- `previous_employment_id UUID REFERENCES employment(id) ON DELETE SET NULL` (self-referential,
  mirroring `designation.next_designation_id`'s existing precedent) — always system-computed,
  never client-settable.
- `version INTEGER NOT NULL DEFAULT 1` — `employment` was the only employee-domain table
  without it (`00_EMPLOYEE_AUDIT.md` §3.2); now closed.
- Three `CHECK` constraints: `employment_status_check` (`status IN ('ACTIVE','TERMINATED')`),
  `employment_status_last_working_day_check` (`last_working_day` set if and only if
  `status = 'TERMINATED'`), `employment_last_working_day_after_joining_check`
  (`last_working_day >= joining_date`).
- `employment_no_overlap`, a GiST exclusion constraint (same `btree_gist`-backed pattern
  already live for `employee_assignment`/`employee_compensation`) on
  `(employee_id, daterange(joining_date, COALESCE(last_working_day, 'infinity'), '[]'))`.
  This single constraint enforces **both** "at most one `ACTIVE` employment per employee" and
  "no two historical spells overlap" — no separate partial-unique index was needed.
- `previous_employment_id` indexed (every FK indexed, per house convention).
- RLS re-asserted idempotently (already live, unchanged in substance).

Verified live against the dev database (`\d employment`) — column set, types, `CHECK`
constraints, the GiST exclusion constraint, FKs, and the RLS policy all match the migration
exactly; `alembic current` reports this migration as head.

`employee`, `employee_assignment`, `employee_compensation` were **not** touched by this
migration.

## 5. API endpoints

| Method | Path | Permission | Notes |
|---|---|---|---|
| POST | `/v1/employees/{employee_id}/employments` | `EMPLOYEE.CREATE` | First hire or rehire — server-detected, not client-specified. `previous_employment_id` always computed server-side. |
| GET | `/v1/employees/{employee_id}/employments` | `EMPLOYEE.VIEW` | Full history ordered by `joining_date`, or `?as_of=YYYY-MM-DD` for the single covering episode (empty list if none). |
| GET | `/v1/employees/{employee_id}/employments/{employment_id}` | `EMPLOYEE.VIEW` | Single episode by id. |
| PATCH | `/v1/employees/{employee_id}/employments/{employment_id}` | `EMPLOYEE.UPDATE` | `If-Match` required. Only `legal_entity_id` is correctable; blocked once `TERMINATED` (`EMPLOYMENT_NOT_ACTIVE`, 409). |
| POST | `/v1/employees/{employee_id}/employments/{employment_id}/terminate` | `EMPLOYEE.TERMINATE` | `If-Match` required. One-way `ACTIVE` → `TERMINATED`; never reversed. |

All five follow `03_EMPLOYEE_API_PLAN.md` §2.1's "proposed but not settled"
`POST /v1/employees/{id}/employments` shape for the rehire entry point, resolving that open
item by adopting it (a REST engineering choice, not a product decision, per
`07_EMPLOYMENT_STATUS_DECISION.md` §9's own framing of this exact item as non-blocking).
`DataEnvelope`/`ListEnvelope`, cross-tenant/not-found → `404`, `extra="forbid"` on every input
schema — all match the organisation module's and E-01's conventions exactly.

## 6. Permissions

| Code | Status before this slice | This slice |
|---|---|---|
| `EMPLOYEE.CREATE` | Seeded (E-01) | Reused — gates employment creation (first hire and rehire alike) |
| `EMPLOYEE.VIEW` | Seeded (identity module) | Reused — gates employment read/list |
| `EMPLOYEE.UPDATE` | Seeded (E-01) | Reused — gates the `legal_entity_id` correction PATCH |
| `EMPLOYEE.TERMINATE` | Not seeded | **Added** — gates the terminate action |

`EMPLOYEE.TERMINATE` is this task's own naming decision, not sourced from any document — the
documented 14-code catalogue has no `.TERMINATE`/`.EXIT` entry at all. Resolved the same way
`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` A9 resolved an analogous gap (adding
`.VIEW_STATUTORY`/`.VIEW_BANKING` when no code existed): termination is irreversible and at
least as HR-sensitive as `EMPLOYEE.DEACTIVATE` (which already got its own dedicated code in
E-01 rather than folding into `.UPDATE`), so the same reasoning applies. Rehire deliberately
was **not** given its own code — mechanically identical to a first hire (insert a new
employment row), gated by the same `EMPLOYEE.CREATE`, distinguished only in the audit trail.
This is flagged explicitly as an assumption, not asserted as settled (§17).

Granted to `COMPANY_ADMIN` automatically at both bootstrap-seed time and live registration
time, since both paths iterate `EMPLOYEE_PERMISSIONS` dynamically — no code change was needed
in `seed/bootstrap.py` or `organisation/service.py` beyond what E-01 already wired.

## 7. Employment lifecycle rules

1. **Create** — employee must exist and belong to the tenant (404 otherwise); `legal_entity_id`
   must reference a valid, same-tenant legal entity (`INVALID_LEGAL_ENTITY`, 422 otherwise);
   `status` always `ACTIVE`, `version` always `1` at creation — neither is client-settable.
2. **At most one `ACTIVE` employment per employee** — database-enforced via
   `employment_no_overlap`; a second create attempt while one is `ACTIVE` is rejected
   (`EMPLOYMENT_DATES_OVERLAP`, 409), including under a concurrent-request race (the GiST
   constraint is the source of truth; the service layer converts the resulting `IntegrityError`
   into this friendly error rather than leaking a 500).
3. **Update** — only `legal_entity_id` is correctable, and only while `ACTIVE`
   (`EMPLOYMENT_NOT_ACTIVE`, 409, once `TERMINATED`). `status`/`last_working_day` are excluded
   from the update schema entirely — reachable only via `terminate`, so the one-way transition
   can't be triggered through an unvalidated arbitrary-field PATCH.
4. **Terminate** — requires `status = ACTIVE` (409 otherwise) and
   `last_working_day >= joining_date` (`INVALID_LAST_WORKING_DAY`, 422 otherwise); transitions
   to `TERMINATED`, sets `last_working_day`, never mutates `joining_date`/`legal_entity_id`.
   Terminal — no action anywhere in this module reopens a `TERMINATED` row.
5. **Rehire** — mechanically the same `create` call as a first hire. The service looks up the
   employee's most recent employment row (by `joining_date`); if one exists, it is (by
   construction, via rule 2) `TERMINATED`, and its id becomes the new row's
   `previous_employment_id`. The prior row is never mutated. Employee identity
   (`employee.id`/`employee_code`) is untouched — reused as-is (verified by test).

## 8. Effective-dating behaviour

`Employment` is **not** effective-dated in the classic child-table sense
(`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part C: "a spell is not itself versioned"). The
as-of-date access pattern is still supported, per the task's Phase 3/4 instructions and
`01_EMPLOYEE_MODULE_PLAN.md` §3 item 3 ("does employee X have an active employment on date
Y"): `GET .../employments?as_of=YYYY-MM-DD` returns the single episode (if any) whose
`[joining_date, last_working_day]` range covers that date, treating a `NULL`
`last_working_day` as extending to infinity. Boundary conditions (exact `joining_date`, exact
`last_working_day`, one day outside each) are covered by
`test_list_employments_as_of_date_boundaries`. No generic effective-dating framework was
built — this is one repository method (`get_employment_as_of`), matching the scope the task's
Phase 4 instructions call for.

## 9. Rehire behaviour

Same `employee.id`/`employee_code` reused across both spells (never re-created, never
reissued); a new `employment` row is inserted (never an update to the original);
`previous_employment_id` links the new row to the immediately preceding one;
`employee_assignment`/`employee_compensation` are untouched (out of this task's scope — E-04/
E-06). Verified end-to-end by
`test_rehire_creates_new_employment_linked_to_previous`, which walks the brief's own worked
example (join → terminate → gap → rehire) and asserts: the new row's `previous_employment_id`,
the old row's unchanged `TERMINATED` state, the unchanged employee identity, and the audit
action name (`EMPLOYMENT_REHIRED` vs. `EMPLOYMENT_STARTED`).

## 10. Audit behaviour

`AuditService.record(...)` called inside the same transaction as every mutation, matching the
organisation module's and E-01's convention exactly, using exactly the action names
`00_EMPLOYEE_AUDIT.md` §13.4 recommends:

| Action | Fired on |
|---|---|
| `EMPLOYMENT_STARTED` | `POST .../employments` when the employee has no prior employment row |
| `EMPLOYMENT_REHIRED` | `POST .../employments` when a prior (necessarily `TERMINATED`) row exists |
| `EMPLOYMENT_UPDATED` | `PATCH .../employments/{id}` |
| `EMPLOYMENT_TERMINATED` | `POST .../employments/{id}/terminate` |

Verified by test: audit row count, `action` value, and entity linkage asserted for create
(both branches), update, and terminate paths.

## 11. Tenant/RLS behaviour

- **Tenant isolation**: every repository query filters `company_id` explicitly in addition to
  Postgres RLS (`FORCE ROW LEVEL SECURITY`, re-asserted by this migration) — same
  belt-and-suspenders convention as every other module. Cross-tenant reads return `404`, never
  a leaked row or a `403` (verified by test: `test_cannot_get_employment_from_other_tenant`,
  `test_other_tenant_employments_not_listed`).
- **Ownership validation**: `employee_id` and `legal_entity_id` are both verified to belong to
  the requesting tenant before any write (`InvalidLegalEntityReferenceError`,
  `NotFoundError`).
- **Optimistic concurrency**: `version` + `If-Match` on both `PATCH` and `terminate`; a `None`
  result from the `UPDATE ... WHERE version = :expected` re-fetches and raises
  `StaleResourceError` (409) — identical shape to `EmployeeService.update_employee`.
- **Mass-assignment protection**: `status`, `version`, `previous_employment_id`,
  `last_working_day` are all absent from `EmploymentCreate`/`EmploymentUpdate`; `extra="forbid"`
  rejects any attempt to set them (422, verified by test).
- **Permission enforcement**: every route gated by `require_permission(...)`; a caller holding
  only `EMPLOYEE.VIEW` is rejected with `403 PERMISSION_DENIED` on
  `POST /v1/employees/{id}/employments` (verified by test, built against a
  dynamically-registered tenant, not just the seeded demo role).

## 12. Frontend changes

**None.** Per `01_EMPLOYEE_MODULE_PLAN.md`'s own E-03 entry, the Job tab's employment
sub-section and rejoin-detection UX are explicitly frontend work, but E-01's precedent (and the
module plan's own sequencing note under E-01: "first usable screen ships with E-09") is that no
Employee frontend ships before the shared frontend infrastructure
(`Tabs`/`Timeline`/`PermissionGate`/`DataTable`, `00_EMPLOYEE_AUDIT.md` §14.5) exists — none of
which do yet, confirmed by `find apps/web/src -iname "*employee*"` returning zero results both
before and after this task. Building an employment-history screen now, ahead of that shared
infrastructure and ahead of E-04 (Assignment, needed for the full Job tab), would produce
Employee-specific one-off UI other modules would have to retrofit — the exact risk
`00_EMPLOYEE_AUDIT.md` §18 flags. No frontend work was done, and per this task's own Phase 8
instruction ("only implement the frontend if E-03's authoritative UX plan requires it"), none
was required to satisfy this task's own "at minimum verify" checklist (A–E), which is entirely
a backend API surface.

## 13. Tests added

**38 new tests, all passing** (17 unit + 21 integration):

- `apps/api/tests/unit/modules/employee/test_employment_service.py` (17): first-hire audit,
  rehire linking + audit, unknown-employee rejection, invalid-legal-entity rejection,
  overlap-race → domain error, as-of-date match/no-match, get-not-found, update-not-found,
  update-noop, update-on-terminated rejection, update-stale-version conflict,
  terminate-success + audit, terminate-already-terminated rejection,
  terminate-before-joining-date rejection, terminate-stale-version conflict.
- `apps/api/tests/integration/modules/employee/test_employment.py` (21): create success + audit,
  unknown employee (404), invalid legal entity (422), mass-assignment rejection (422),
  second-active-employment rejection (409, the GiST constraint's live behaviour, not just
  mocked), list empty state, get success/not-found, as-of-date boundary walk (5 boundary
  points), update success/mass-assignment/stale-version/on-terminated, terminate
  success+audit/before-joining-date/already-terminated/stale-version, the full rehire scenario
  end-to-end, cross-tenant get/list isolation, permission-denied create (403, dynamically
  registered view-only role).

**Regression**: `test_registration_success_full_row_graph`'s permission-set assertion updated
to include `EMPLOYEE.TERMINATE` (the only test affected by adding a new permission code to the
catalogue register_company grants) — same one-line update pattern E-01 made to this same test.

**Full backend suite: 383 passed, 0 failed** (`uv run pytest` from `apps/api/`) — confirms no
regression in `employee` (E-01), `organisation`, `identity`, or `health`.

## 14. Validation results

- `ruff check src tests` — all checks passed.
- `ruff format --check src tests` — 122 files formatted (one test file reformatted during
  development, confirmed clean afterward).
- `mypy src` — Success: no issues found in 73 source files.
- `lint-imports` — 1 contract kept, 0 broken (`modules → shared → core` layering intact;
  `EmploymentService`'s lazy `organisation.service` import follows the same pattern
  `EmployeeService._check_seat_limit` already established).
- **Migration**: verified applied against the running dev Postgres instance (`alembic current`
  → `20260814090000 (head)`); live `\d employment` output cross-checked column-by-column,
  constraint-by-constraint against the migration source (§4) — exact match.
- **Dev database cleanliness**: `employment`/`employee`/`legal_entity` row counts confirmed `0`
  after the full test run (company count `2`, matching the two fixed bootstrap-seed demo
  companies, not test pollution) — no orphaned test data left behind.
- No frontend validation was run (`vitest`/`tsc --noEmit`/`next build`) — no frontend code was
  written for this slice (§12), so there is nothing to validate.

## 15. Documentation

- This report (`08_EMPLOYMENT_LIFECYCLE_IMPLEMENTATION_REPORT.md`).
- `00_EMPLOYEE_AUDIT.md`, `01_EMPLOYEE_MODULE_PLAN.md`, `02_EMPLOYEE_DATA_MODEL.md`,
  `03_EMPLOYEE_API_PLAN.md`, `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md`,
  `06_EMPLOYEE_FOUNDATION_IMPLEMENTATION_REPORT.md`, `07_EMPLOYMENT_STATUS_DECISION.md` — read
  in full, not modified; no contradiction requiring a correction was found. Where
  `07_EMPLOYMENT_STATUS_DECISION.md` left a question open for product (§8 of that document),
  this task's own authoritative instruction supplied the answer and is treated as that product
  decision, cited throughout this report rather than re-argued.

## 16. Known limitations

1. **Confirmation/probation workflow (FR-EMP-010, `.CONFIRM`) not implemented** — named in the
   module plan's E-03 entry but not in this task's own "at minimum verify" list (A–E); no
   `date_of_confirmation`/`probation_end_date` columns were added.
2. **Inter-entity transfer (FR-EMP-011) not implemented** — `legal_entity_id` is correctable
   via `PATCH` only as a data-entry fix while `ACTIVE`; the documented "closes one employment,
   opens another" transfer flow is a distinct, unbuilt action.
3. **`employment_number`, `employment_type_id`, `notice_period_days`, `date_of_resignation`,
   `exit_type`, `exit_reason_id` were not added** — none are required by this task's locked
   decisions or its "at minimum verify" list; `exit_type` specifically is explicitly deferred to
   the later Exit module per this task's own instruction (item 8).
4. **`GET .../employments`/`GET .../employments/{id}` are not scoped to self/team** — same
   limitation E-01 carried forward for `GET /v1/employees/{id}`; `SELF`/`REPORTEES` scoping
   needs `employee_assignment.reporting_manager_id`, which doesn't exist until E-04.
5. **No frontend** — see §12.
6. **The rejoin-linking wizard UX** (PAN/Aadhaar/email match suggesting "link to existing
   record" during Add-Employee) is not built — it's a frontend feature with no frontend to
   attach to yet (§12), and was already flagged as deferred-until-frontend-exists by
   `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part G item 5.

## 17. Unresolved decisions

1. **`EMPLOYEE.TERMINATE`'s exact name** — this task's own naming decision (§6), not sourced
   from any document. A future product pass could rename it (e.g. to align with a future Exit
   module's own permission catalogue) without a data-model change — it gates one router
   dependency, nothing schema-level.
2. **Whether rehire should be gated by a permission distinct from `EMPLOYEE.CREATE`** — this
   report reused `EMPLOYEE.CREATE` for both first-hire and rehire (§6); a future product
   decision could split this if rehire is judged to warrant separate approval from ordinary
   employee creation.
3. **The `.CONFIRM` permission's exact scope, and confirmation/probation's own field set** —
   not resolved here since not in this task's scope (§16 item 1); `01_EMPLOYEE_MODULE_PLAN.md`
   names it for E-03 but this task's own instructions narrowed the slice.

## 18. Explicit scope confirmation

Verified by direct schema inspection (`\d employee_assignment`, `\d employee_compensation`
unchanged) and by grep across `apps/api/src/hrms/modules/employee/` and the new migration for
`assignment|compensation|statutory|banking|attendance|leave|payroll|br-?14|workflow` — every
match found is inside a docstring/comment stating the concept is explicitly **not** built in
this slice (e.g. "still belong to later slices", "this task's own scope explicitly excludes"),
none in executable code (§3 of this report shows the exact grep). Specifically **not**
implemented in this task, confirmed:

- **Assignment** — `employee_assignment` table and `EmployeeAssignment` ORM model untouched.
- **Compensation** — `employee_compensation` table untouched.
- **Statutory** — `employee_statutory` table does not exist (unchanged).
- **Banking** — `employee_bank` table does not exist (unchanged).
- **Attendance / Leave / Payroll** — no code anywhere references these domains outside
  explanatory comments about what a future slice will need from `employment` (e.g. the as-of
  read pattern's Attendance-readiness rationale, §8).
- **ATS / onboarding workflow** — no candidate/offer concept anywhere.
- **BR-14 override chain** — not implemented; no shift/notice-period cascading resolution
  logic anywhere in this diff.

No changes were committed — all work is staged as uncommitted working-tree changes, per this
task's own instruction.

## 19. Recommended next step

Per `01_EMPLOYEE_MODULE_PLAN.md` §4's dependency graph, **E-04 — Employee Assignment** is next
on the Attendance-readiness critical path (E-01 + E-03 + E-04 + E-05). Before starting it:

1. Confirm whether this report's two naming assumptions (§17 items 1–2 —
   `EMPLOYEE.TERMINATE`'s name, and reusing `EMPLOYEE.CREATE` for rehire) should stand or be
   revised — low-cost to change now, more disruptive once E-04's own permission surface is
   built alongside it.
2. E-04 is the first slice that writes to a genuinely effective-dated table in application code
   (`employee_assignment`) — budget the extra first-of-its-kind review time
   `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part H item 1 flags, distinct from `Employment`'s own
   (simpler) non-overlapping-spell model built in this slice.
3. If confirmation/probation (§16 item 1) or inter-entity transfer (§16 item 2) are wanted
   before E-04, they can be added as a small follow-up to this slice (same `employment` table,
   no new migration risk) rather than folded into E-04's own scope.
