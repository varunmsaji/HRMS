# System Architecture Audit — HRMS Foundations for Attendance and Payroll

**Type:** Architecture discovery and audit only. No application code, schema, migrations, or tests were changed to produce this document.

**Date:** 2026-08-15

**Scope:** Determine whether Organisation + Employee foundations are coherent enough to continue toward Attendance → Leave → Payroll without a major rewrite.

**Method:** Cross-check product/architecture documents against live models, Alembic migrations, services, routers, tests, RLS, audit, RBAC, and the organisation frontend. Where documentation and implementation disagree, the implementation is treated as current fact and the document as intent.

**Legend:** **FACT** = observed in code/schema/tests. **DOC** = stated in an authoritative document. **DISCREPANCY** = DOC and FACT disagree. **RECOMMENDATION** = proposed next action, not a locked product rule.

---

## 1. Executive Summary

The system is a **modular monolith** (ADR-0001) with FastAPI, PostgreSQL, SQLAlchemy, Alembic, RLS, and a Next.js organisation UI. Organisation (Company → Legal Entity → Branch → Department → Designation → Grade → Shift) and Employee (identity, employment, assignment including `shift_id`, compensation) are implemented as vertical slices. Statutory, banking, Employee UI, Attendance, Leave, and Payroll are not implemented.

**The foundational concepts are consistent enough to keep building.** Identity, employment spells, effective-dated assignment, and effective-dated compensation are separated correctly, keyed on `employee_id` (not `employment_id`), overlap-protected with GiST exclusion constraints, and exposed via `get_*_as_of` helpers. That is the load-bearing design Attendance and Payroll need.

**The architecture is not yet safe to start Attendance.** One implemented behaviour contradicts the locked Employee lifecycle model and will produce wrong as-of answers in the employment gap:

- **FACT:** `EmploymentService.terminate_employment` closes only the employment spell. It does not close the open `employee_assignment` or `employee_compensation` rows (`apps/api/src/hrms/modules/employee/service.py` `terminate_employment`).
- **DOC:** `docs/modules/employee/05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part D requires assignment and compensation `effective_to` to be set to the exit date so no open row remains in the gap.
- **FACT:** Integration tests encode the opposite: after terminate, a later rehire assignment write is what closes the pre-exit row, with `effective_to` equal to the day before the *rehire* date, spanning the entire gap (`apps/api/tests/integration/modules/employee/test_employee_assignment.py` around the rehire assertions for `2034-01-31`).

Until terminate (or an equivalent orchestration) closes assignment and compensation at `last_working_day`, `get_assignment_as_of` / `get_compensation_as_of` will still return the last job/pay during a gap. Attendance that trusts those helpers without also intersecting employment coverage will mark terminated people as still on a shift.

Payroll is further blocked by missing `employee_statutory` and `employee_bank` (planned E-07/E-08; table absence confirmed). That is expected incompleteness, not a redesign.

**Rating: YELLOW** — continue Employee (Statutory → Banking), fix the terminate/history-close contract, then Attendance. Do not start Attendance or Payroll on the current terminate semantics.

---

## 2. Current System Map

```text
apps/web (Next.js)                    apps/api (FastAPI modular monolith)
  Organisation screens only             modules/identity
  No Employee Directory                 modules/organisation   (Company…Shift)
                                        modules/employee       (E-01, E-03…E-06)
                                        modules/health
                                        core: auth, rbac, audit, tenancy, db

PostgreSQL 16
  Shared schema + company_id + RLS
  GiST overlap: employment, employee_assignment, employee_compensation
  Stub tables from 001_init_schema.sql with no ORM/API yet:
    holiday_calendar, holiday, (and other dictionary tables in the init script)

Not present as modules: attendance, leave, payroll, workflow, notification, ai
Not present as tables: employee_statutory, employee_bank, employee_document,
  employee_address, sensitive_access_log, leave_ledger, payrun_*
```

**Deployable processes (DOC, `docs/architecture/03_System_Architecture.md`):** API, punch ingestion, Celery worker, Celery beat.

**FACT:** Only the API process is wired in `apps/api/src/hrms/app.py` (health, identity, organisation, employee routers). No `idempotency` package exists. Celery settings exist; outbox/event infrastructure is documented as planned, not used by Employee writes.

**Alembic head (FACT):** `20260814120000_employee_compensation` revises shift assignment → assignment → employment lifecycle → employee foundation.

---

## 3. Current Domain Boundaries

| Domain | Package | Owns (FACT) | May reference | Must not own | Boundary health |
|---|---|---|---|---|---|
| Platform / Identity | `modules/identity`, `core/` | Users, JWT, roles, permissions, tenant context, `audit_log` | Company membership | Employee identity, org structure | Clear |
| Organisation | `modules/organisation` | Company, plan/subscription, legal entity, branch, department, designation, grade, shift, setup progress, feature flags | `user.id` on flags; `department.head_employee_id` UUID **without ORM FK** | Employee history, attendance, payroll | Clear, with stale “Employee doesn’t exist” comments |
| Employee | `modules/employee` | `employee`, `employment`, `employee_assignment`, `employee_compensation`, `number_series` | Organisation via `organisation.service` only | Punch/roster, leave ledger, pay runs, salary-structure catalogue | Clear package; hire is split across HTTP calls |
| Attendance | *missing* | — | Employee as-of assignment + employment; Shift master; Branch timezone/geofence | Compensation, statutory, bank | — |
| Leave | *missing* | Ledger (ADR-0004, not built) | Employment, assignment/grade for policy later | Attendance punches as source of truth for presence | — |
| Payroll | *missing* | Runs, snapshots (ADR-0005, not built) | Compensation, statutory, bank, attendance summary, leave, legal entity | Mutating Employee history in place | — |
| Workflow / ESS / ATS / Performance | *missing* | — | — | — | Out of V1 ATS per `VERSION_1_ROADMAP.md` |

**Accidental coupling (FACT):**

- Employee services lazily import `OrganisationService` for FK existence checks. Allowed by Module Standard §2 (`docs/architecture/02_Module_Standard.md`).
- `department.head_employee_id` is a plain UUID; the model comment still says Employee does not exist (`organisation/models.py` Department). **DISCREPANCY:** Employee exists; the ORM FK was never added.
- Organisation deactivation still skips the active-employee half of FR-ORG-014 with comments “Employee doesn’t exist” (`organisation/service.py` around department/designation/grade/shift deactivate). **DISCREPANCY:** stale after E-01.
- Import-linter (`apps/api/.importlinter`) only enforces `modules → shared → core` layers, not “never import `other.repository`”. Cross-module discipline is convention, not CI teeth.

---

## 4. Canonical Entity Model

Authoritative **implemented** graph (not the full product dictionary):

```text
Company (tenant root)
  ├── LegalEntity (required parent of Branch; employer of Employment)
  │     └── Branch (required legal_entity_id)
  │           └── Department (optional branch_id, optional parent_id)
  ├── Grade
  ├── Designation (optional department_id, optional grade_id)
  └── Shift (company-scoped master; no assignment here)

Employee (permanent identity; UNIQUE (company_id, employee_code))
  ├── Employment[]  1:N  required legal_entity_id; joining_date; last_working_day iff TERMINATED
  ├── EmployeeAssignment[]  1:N on employee_id  (NOT employment_id)
  └── EmployeeCompensation[] 1:N on employee_id  (NOT employment_id)
```

| Relationship | Ownership | FK (FACT) | Required? | Effective-dated? | Notes |
|---|---|---|---|---|---|
| Company → Legal Entity | Organisation | `legal_entity.company_id` | Yes | No | Soft-delete + `is_active` |
| Legal Entity → Branch | Organisation | `branch.legal_entity_id` NOT NULL | Yes | No | |
| Branch → Department | Organisation | `department.branch_id` nullable | Optional | No | Hierarchy `parent_id`, cycles in service |
| Department → Designation | Organisation | `designation.department_id` nullable | Optional | No | |
| Grade → Designation | Organisation | `designation.grade_id` nullable | Optional | No | |
| Company → Shift | Organisation | `shift.company_id` | Yes | No | Timings/grace/OT flags only |
| Company → Employee | Employee | `employee.company_id` | Yes | No | Identity, not job |
| Employee → Employment | Employee | `employment.employee_id` | 1:N; employee can exist with zero spells | Spell-bounded, not `effective_*` | GiST `employment_no_overlap` on `[joining_date, last_working_day]` |
| Employment → Legal Entity | Employee | `employment.legal_entity_id` NOT NULL | Yes | No (spell is the version) | **PATCH can change LE in place** |
| Employee → Assignment | Employee | `employee_assignment.employee_id` | 1:N | Yes | GiST no overlap |
| Assignment → Branch/Dept/Desig/Grade/Shift/Managers | Employee | FKs `ON DELETE SET NULL` | First row: branch, dept, designation required in **service**, not DB | Yes | `cost_centre_id` **no FK** (no `cost_centre` table) |
| Employee → Compensation | Employee | `employee_compensation.employee_id` | 1:N | Yes | CTC + currency; no structure child table |
| Rehire link | Employee | `employment.previous_employment_id` → `employment.id` | Optional | n/a | **No `is_rehire` column** |

**Relationships only in application code, not DB:**

- First assignment requires `branch_id`/`department_id`/`designation_id` (service `AssignmentFieldsRequiredError`); columns are nullable in SQL.
- Assignment `change_type` and compensation `revision_type` are Pydantic `Literal`s, not CHECK constraints (unlike `employment.status`).
- Covering employment on assignment/compensation `effective_from` is a service check (`NoActiveEmploymentError`), not an FK to `employment`.
- Branch of assignment vs legal entity of employment is **not** cross-checked.
- Department.branch vs assignment.branch is **not** cross-checked.
- `EMPLOYEE_SEATS` vs `is_active` count is application-only (`EmployeeRepository.count_active_employees`).

**DOC vs FACT — `is_rehire`:** `02_EMPLOYEE_DATA_MODEL.md` §3 and `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part C specify `is_rehire`. Migration `20260814090000_employment_lifecycle.py` adds `previous_employment_id` + `version` only. Rehire is inferred (`previous_employment_id is not None` → audit action `EMPLOYMENT_REHIRED`). Functionally equivalent; column name never shipped.

---

## 5. Employee Lifecycle Model

| Event | How it is represented (FACT) | History preserved? |
|---|---|---|
| Create identity | `POST /v1/employees` → `status=PRE_JOINING`, `is_active=true`, allocated `employee_code` | Yes — new row |
| Hire (first spell) | Separate `POST .../employments` → `status=ACTIVE` | Yes — new employment row. **Does not** set `employee.status` to ACTIVE/PROBATION |
| Assignment | `POST .../assignments` close-and-insert | Yes — old `effective_to` only |
| Transfer / promotion / manager / shift change | Same POST; `change_type` selects `EMPLOYEE.TRANSFER` vs `.PROMOTE` | Yes |
| Compensation revision | `POST .../compensation` close-and-insert | Yes |
| Termination | `POST .../employments/{id}/terminate` → `TERMINATED` + `last_working_day` | Employment history yes. **Assignment/compensation left open** |
| Gap | Intended: no open employment. **Actual:** open assignment/comp still cover the gap via `effective_to IS NULL` | Employment gap query-correct; placement/pay as-of **incorrect** |
| Rehire | New employment; `previous_employment_id` set; same `employee.id`/`employee_code` | Yes |
| Soft deactivate | `DELETE /employees/{id}` → `is_active=false`; distinct from EXITED | Identity not deleted; employment unchanged |
| Inter-entity transfer | **Not** close/open employment. `PATCH` employment `legal_entity_id` in place | **Overwrites** employer of the spell |

**Identity vs episode vs placement vs pay (FACT):** correctly separated in tables. `employee.id` and `employee_code` are never reissued (unique index from init schema; allocator in `EmployeeRepository.allocate_employee_code`).

**`employee.status` vs `employment.status` vs `is_active` (FACT):**

- `EMPLOYEE_STATUS_VALUES` lists the FR-EMP-014 ten states in `schemas.py`; only `PRE_JOINING` is ever written.
- `employment.status` is CHECK-constrained to `ACTIVE`/`TERMINATED` (`20260814090000`). Notice is derived (`last_working_day` set iff TERMINATED) — E-03’s own decision, not product-signed in `07_EMPLOYMENT_STATUS_DECISION.md` (that doc left values open).
- `is_active` is an account lock, not lifecycle. Seat limits count `is_active`, so a terminated-but-still-active identity still occupies a seat.

**RECOMMENDATION:** Attendance and Payroll must treat **employment as-of date** as “was this person employed?”, not `employee.status` or `is_active`, until a real FR-EMP-014 machine exists. Product still needs to lock when `employee.status` flips (hire, notice, exit, rehire).

---

## 6. Effective-Dating Model

**Pattern (DOC ADR-0003, FACT in DB + services):** close old row’s `effective_to` = new_from − 1 day; insert new row with `effective_to` NULL; same transaction; GiST `daterange(..., '[]')` overlap forbidden.

| Table | `effective_from` / `effective_to` | As-of query | Overlap prevention | “Current” row | Concurrency |
|---|---|---|---|---|---|
| `employment` | `joining_date` / `last_working_day` | `get_employment_as_of` | `employment_no_overlap` | `last_working_day IS NULL` ≡ ACTIVE | `version` + GiST on insert |
| `employee_assignment` | yes | `get_assignment_as_of` | `employee_assignment_no_overlap` (init schema) | `get_current_assignment`: `effective_to IS NULL` | `If-Match` on close + GiST |
| `employee_compensation` | yes | `get_compensation_as_of` | `employee_compensation_no_overlap` | `effective_to IS NULL` | same |
| Future statutory/bank | DOC same shape; **not built** | planned | planned | planned | planned |
| Future attendance day | Not this pattern; one row per employee per date (SRS) | n/a | unique (employee, date) expected | n/a | idempotent punches |
| Future leave | ADR-0004 ledger, not effective-dated attributes | n/a | n/a | derived balance | n/a |
| Future payroll | ADR-0005 snapshots, not live as-of at pay time after finalise | snapshot copies as-of inputs | n/a | n/a | period lock |

**Current-row vs as-of (FACT, important):**

- Writes use **open-ended latest** (`effective_to IS NULL`), which may start in the **future**. That is valid for FR-EMP-005 future-dated changes.
- Reads for Attendance/Payroll **must** use as-of (`effective_from <= date AND (effective_to IS NULL OR effective_to >= date)`), never “the NULL row”.
- Helpers exist on the service as the documented cross-module contract (`get_assignment_as_of`, `get_compensation_as_of`). **RECOMMENDATION:** do not add a generic framework; repeat this repository method on statutory/bank. Add `get_employment_as_of` to the same public contract (already on `EmploymentRepository` / list API `?as_of=`).

**Future rows:** allowed by insert; no activation job needed (DOC `02_EMPLOYEE_DATA_MODEL.md` §1.4 interpretation). **FACT:** no Celery job exists.

**Historical rows:** business columns are not updated after insert (assignment/compensation). Employment **does** allow in-place `legal_entity_id` patch — exception to ADR-0003 spirit for spells.

**Reusable service vs current pattern:** Current per-table service methods are sufficient and match B7 (“no giant generic framework”). A shared mixin is optional polish, not a blocker.

---

## 7. Attendance Readiness

Worked backwards from “status for employee E on date D”.

| Question | Intended source | Ready? |
|---|---|---|
| Who is the person? | `employee.id` (stable across rehire) | **Yes** |
| Employed on D? | `get_employment_as_of(E, D)` | **Yes**, if callers use it |
| Shift? | `get_assignment_as_of(E, D).shift_id` → `organisation.get_shift` | **Column exists** (E-05). **NULL is allowed** (BR-14 cascade deferred). **Broken in gap** if assignment not closed on terminate |
| Branch? | assignment.branch_id | Same as-of / gap issue |
| Department / designation / grade / manager? | assignment | Same |
| Legal entity? | **employment.legal_entity_id as-of D**, not branch | Ready **if** Attendance does not infer LE from branch. **No invariant** that assignment.branch.legal_entity_id matches employment |
| Timezone / geofence? | `branch.timezone`, lat/long, `geofence_radius_m` | **Yes** on Branch |
| Shift definition (start/end, grace, night, OT)? | `shift` master | **Yes**. No roster table (intentionally Attendance-owned) |
| Week-off / holiday? | Branch `week_off_pattern_id` / `holiday_calendar_id` | **FACT: columns absent** on Branch; `holiday_calendar`/`holiday` exist in `001_init_schema.sql` with **no module** |
| Terminated? | employment TERMINATED + LWD | Employment query yes; assignment still “current” |
| Rehire? | new employment + new assignment from new joining_date | Identity yes; gap as-of wrong until close-on-exit |
| Device punches / ingestion service | ADR-0007 | **Not built** |

**How Attendance should resolve (RECOMMENDATION, matching locked docs):**

1. Require `get_employment_as_of` non-null (else not in population).
2. `get_assignment_as_of` for shift/branch/dept.
3. If `shift_id` is NULL → “no shift resolves” (A3/B8), do not invent cascade.
4. Load Shift + Branch for windows/timezone.
5. Do not use `employee.status` or `is_active` as the employment gate.

**Must exist before Attendance (foundation, not Attendance features):**

1. Close assignment (and compensation, for consistency) at terminate `last_working_day` **or** change tests/docs and force every consumer to intersect employment ∩ assignment (weaker; still leaves “current assignment” meaning “latest open row including after exit”).
2. Lock the legal-entity rule: employment as-of is SoT; optionally reject assignment.branch whose `legal_entity_id` differs.
3. Holiday calendar + week-off **or** an explicit Attendance-owned first slice for them — punches can start without holidays; **status resolution cannot** (SRS FR-ATT holiday/week-off). This can be the first Attendance slice rather than an Employee rewrite.
4. Do not start Attendance assuming `employee.status` is maintained.

**Not required before a first Attendance spike:** Employee Directory UI, statutory/bank, salary structure, data-scope SELF/REPORTEES, PermissionGate.

---

## 8. Payroll Readiness

| Question | Source | Ready? |
|---|---|---|
| Identity | `employee` | Yes (code/name). PAN/Aadhaar/UAN columns exist, **no write path**, no encryption-at-rest beyond storing `*_enc` text |
| Employment episode / LE / joining-exit | `employment` | Architecture yes. In-place LE patch **corrupts spell history**. Status machine incomplete |
| Salary | `employee_compensation.annual_ctc_minor` + `currency` | Gross CTC history yes. **No** `salary_structure_id`, components, monthly_gross (deferred in model docstring to Payroll catalogue) |
| Compensation as-of period | `get_compensation_as_of` | Yes **except gap-after-terminate** |
| Assignment / grade / branch as-of | assignment | Same gap issue. Grade min/max CTC **not** enforced on write (explicit PD-1) |
| Statutory identifiers / PF/ESI/tax regime | `employee_statutory` | **Missing table.** UAN also on `employee.uan_number` (DOC conflict; E-07 plan keeps UAN on employee) |
| Bank account | `employee_bank` | **Missing** |
| Attendance / leave | future modules | Missing; ADR-0005 says snapshot those inputs |
| Employer statutory (PF/ESI/TAN) | `legal_entity` | **Yes** (entity-level codes) |

**Ownership ambiguity:** UAN (employee vs statutory), PAN (employee vs statutory), legal entity (employment vs branch), CTC vs grade band, `is_active` vs employed. E-07 plan already chooses live `employee.uan_number` over a second UAN column — **RECOMMENDATION:** keep that; do not duplicate.

Payroll cannot be built correctly until E-07/E-08 exist **and** terminate closes compensation at LWD **and** LE changes are new employment rows (or a documented correction-only patch with audit). Salary **structure** can wait for Payroll’s own catalogue (already deferred in E-06).

---

## 9. Data Ownership Matrix

| Field | Single source of truth (intended) | Implemented? | Duplicates / drift |
|---|---|---|---|
| Employee name | `employee` | Yes | `display_name` column unused (always null; not derived on write) |
| Employee code | `employee` + `number_series` | Yes | |
| Identity status | `employee.status` | Column only; stuck PRE_JOINING | Diverges from employment |
| Account lock | `employee.is_active` | Yes | Orthogonal to employment; seats use this |
| Employment status | `employment.status` | Yes ACTIVE/TERMINATED | |
| Joining / LWD | `employment` | Yes | Init schema `exit_date` renamed to `last_working_day` |
| Legal entity (employer) | `employment.legal_entity_id` | Yes | Branch also has `legal_entity_id` |
| Department / designation / grade / branch / manager / shift | `employee_assignment` | Yes | Designation also has `grade_id`/`department_id` (catalogue, not employee placement) |
| Shift master definition | `shift` | Yes | |
| CTC | `employee_compensation` | Yes | Grade `min_ctc`/`max_ctc` informational |
| PAN / Aadhaar | `employee.*_enc` | Columns; no API | Planned statutory must not copy |
| UAN | `employee.uan_number` (live) vs `employee_statutory.uan` (docs) | Column; no API | **DOC conflict** |
| PF/ESI/tax | `employee_statutory` | Missing | Legal entity holds employer codes — correct split |
| Bank | `employee_bank` | Missing | |
| Cost centre | `employee_assignment.cost_centre_id` | UUID, no table | |
| Dept head | `department.head_employee_id` | Unexposed | |

No duplicate **mutable** CTC on `employee`. That is healthy.

---

## 10. Security Architecture Assessment

| Control | FACT | Scales to named roles? |
|---|---|---|
| Tenant RLS | ENABLE + FORCE + `tenant_isolation` on org/employee/audit tables; session `set_config('app.company_id', …, true)` in `core/db/session.py` | Yes for tenant isolation |
| App `company_id` filter | Repositories filter `company_id` as well | Yes |
| RBAC | `require_permission`; always returns `DataScope(COMPANY)` (`core/rbac/dependencies.py`) | **No** for Manager/Employee/self — VIEW is company-wide if granted |
| Restricted fields | Compensation gated by dedicated permissions. PAN/Aadhaar not in `EmployeeRead`. Personal email/mobile **are** on `EmployeeRead` without `VIEW_PERSONAL_CONTACT` | Personal contact leak vs DOC §6 |
| Audit writes | `AuditService.record` same session as mutation | Yes for writes |
| `sensitive_access_log` | **Missing** | Required before Payroll/ESS reads of RESTRICTED data (FR-AUD-003) |
| Cross-tenant tests | Organisation has isolation tests; Employee tests exist under `tests/integration/modules/employee/` | Pattern exists |

**Privilege-escalation / over-grant risks (FACT):**

- `EMPLOYEE.VIEW` on get-by-id is not scoped to self/team (router docstring admits this). Anyone with VIEW can read any employee in the tenant.
- `EMPLOYEE.VIEW_ALL` gates the list; a user with VIEW but not VIEW_ALL can still open an ID if they know the UUID.
- Organisation uses a single `ORG.*.MANAGE` for view+write — too coarse for Auditor vs Admin, but acceptable until org read-only roles exist.
- Compensation audit snapshots store full CTC JSON in `audit_log` (`compensation_to_audit_dict` = full read model). Anyone with future `EMPLOYEE.VIEW_AUDIT` (not seeded) or DB access sees RESTRICTED data. RLS still tenant-bounds it.
- `EMPLOYEE.UPDATE` can PATCH `is_active` via `EmployeeUpdate`; dedicated `DEACTIVATE` exists on DELETE but UPDATE can also flip the flag if the client sends `is_active`. **RECOMMENDATION:** confirm whether UPDATE should be allowed to deactivate.

Will the model scale to HR Admin / HR Manager / Manager / Employee / Payroll Admin / Attendance Admin / Finance / Auditor / Company Admin? **Permission codes can.** **Data-scope and field-mask layers cannot yet.** Those are required before ESS and manager-team Attendance, not before an HR-admin-only Attendance MVP.

---

## 11. RBAC Assessment

**DOC catalogue** (`docs/product/19_RBAC_and_Permission_Matrix.md` §3.1): VIEW, VIEW_ALL, CREATE, UPDATE, UPDATE_SENSITIVE, DEACTIVATE, VIEW_COMPENSATION, UPDATE_COMPENSATION, document trio, VIEW_PERSONAL_CONTACT, TRANSFER, PROMOTE, CONFIRM, IMPORT, EXPORT, GENERATE_LETTER, VIEW_AUDIT, BACKDATE_OVERRIDE.

**FACT seeded in Employee module** (`employee/permissions.py`): VIEW_ALL, CREATE, UPDATE, DEACTIVATE, **TERMINATE** (not in the 14-code list), TRANSFER, PROMOTE, VIEW_COMPENSATION, UPDATE_COMPENSATION. `EMPLOYEE.VIEW` lives in `identity/permissions.py`.

**Shape:** resource/action codes (`EMPLOYEE.TRANSFER`) rather than one MANAGE blob — correct for Employee; Attendance/Payroll can follow `ATTENDANCE.*` / `PAYROLL.*` from Doc 19 without redesigning the engine.

**Gaps:**

- `.TERMINATE` is an implementation-added code (flagged in permissions module docstring). Fits the catalogue’s lifecycle style. **RECOMMENDATION:** add it to Doc 19 rather than folding into UPDATE.
- `.VIEW_STATUTORY` / `.VIEW_BANKING` recommended in architecture decisions A9, not in Doc 19, not seeded. **Do not invent as fact.** Needed before those APIs.
- Sensitive field permissions (`UPDATE_SENSITIVE`, `VIEW_PERSONAL_CONTACT`) unused; personal contact still returned.
- Data-scope enum exists (`DataScopeLevel`) and is unused beyond hard-coded COMPANY.

Attendance/Payroll fit naturally as new code families on the same `has_permission` engine.

---

## 12. Audit Architecture Assessment

**FACT `AuditService`** (`core/audit/service.py`): insert-only `audit_log` with `company_id`, `actor_user_id`, `action`, `entity_type`, `entity_id`, `before_json`/`after_json`, `ip`, `user_agent`, `request_id` from `current_request_id()`, `occurred_at` server default.

**Employee actions observed:** `EMPLOYEE_CREATED`, `EMPLOYEE_UPDATED`, `EMPLOYEE_DEACTIVATED`, `EMPLOYEE_REACTIVATED`, `EMPLOYMENT_STARTED`, `EMPLOYMENT_REHIRED`, `EMPLOYMENT_UPDATED`, `EMPLOYMENT_TERMINATED`, `ASSIGNMENT_CHANGED`, `COMPENSATION_REVISED`.

**Not audited:** reads; PAN writes (no path); org FR-ORG-014 skips; failed auth (unknown here).

**Before/after:** writes that mutate send both; creates send `after` only; assignment/comp revisions send previous current row as `before` and **new row id** as `entity_id` (the closed row’s id is not the audit entity). Sufficient if consumers know `entity_id` is the new row.

**Architecturally sufficient for write audit?** **Yes** for continuing. **Not** sufficient for DPDP/RESTRICTED read logging. Payroll/attendance finalisation will need the same write pattern plus outbox (ADR-0012) for money events — AuditService does not replace outbox.

**Timestamp:** DB `now()`; not the business `effective_from`. Correct: audit is when the API happened; as-of is on the entity.

---

## 13. API Architecture Assessment

**Conventions (FACT vs `docs/product/09_API_Standards.md`):**

| Rule | Applied? |
|---|---|
| `/v1` + plural resources | Yes (`app.py` includes employee router) |
| Nest one level | Yes: `/employees/{id}/employments|assignments|compensation` |
| Verb sub-resource | Yes: `.../terminate` |
| Envelopes `DataEnvelope`/`ListEnvelope` | Yes |
| Pagination | **ListEnvelope.pagination always omitted** on employee lists |
| `If-Match` optimistic concurrency | Yes on PATCH/DELETE/terminate and on assignment/comp when a current row exists |
| `?as_of=` | Yes on employment, assignment, compensation lists |
| Error envelopes | Shared handlers |
| `Idempotency-Key` | **Not implemented** (standards say required on money/attendance POSTs) |
| Authorization | `Depends(require_permission)` except assignment POST (dynamic TRANSFER/PROMOTE) |

Future Attendance/Payroll **can** follow this: collections + `?as_of=` or date range, `POST .../finalise`, `If-Match` on mutable aggregates, RLS+permission. Attendance day resources should be `/attendance-days` (or similar) not nested deeper than one level.

**Hire is two POSTs**, not nested create on `POST /employees`. DOC `01_EMPLOYEE_MODULE_PLAN.md` E-03 wanted employment folded into create. **DISCREPANCY.** Fine for API purity; UI must orchestrate or a later hire facade added.

---

## 14. Database Architecture Assessment

**Consistent and strong:**

- UUID PKs, `company_id`, timestamps, `deleted_at`, `version` on mutable tables (employment gained `version` in E-03).
- RLS ENABLE+FORCE re-asserted per migration.
- Money as BIGINT (`annual_ctc_minor`, grade CTC).
- GiST overlap on the three temporal employee tables.
- Partial unique indexes on org codes; employee_code unique per company.
- FKs added in follow-up migrations (assignment → org entities, shift).

**Inconsistencies:**

- `employment.status` CHECK vs assignment `change_type` / compensation `revision_type` app-only.
- `is_rehire` never added.
- `cost_centre_id` unconstrained.
- `department.head_employee_id` DB FK (init) vs no ORM FK.
- Soft-delete columns exist on assignment/comp; no API path sets `deleted_at` (close via `effective_to` instead). GiST still includes soft-deleted rows — if someone sets `deleted_at` without removing the range, overlaps remain blocked. Low risk today.
- Init schema still the source of many dictionary tables (holiday) without later module migrations.

**Indexes:** assignment current covering index + manager partial index (E-04). Compensation relies on init `(employee_id, effective_from)` style indexes. Adequate for current volume.

---

## 15. Frontend Architecture Assessment

**FACT:** `apps/web` has Dashboard, Company, Legal Entities, Branches, Departments, Designations, Grades, Shifts, Setup (`nav-items.ts`). Shared primitives: `useApiResource`, `apiClient`, form components, page header, empty/error/loading, auth context. **No** Employee routes. **No** `usePermission` / `PermissionGate` (A10 still unimplemented). **No** Timeline or DataTable shared component.

**Can this support Directory / 360 / timelines / Attendance?** The **screen pattern** (list page + `[id]` + form lib + `useApiResource`) can be copied. It cannot yet:

- Hide tabs by permission (reactive 403 only).
- Render employment/assignment/compensation history (no Timeline).
- Page large directories (API also unpaginated).
- Show as-of point-in-time in the UI.

**Missing shared primitives (identify only):** PermissionGate/usePermission; paginated DataTable; as-of date control; Timeline; tabbed 360 layout; money formatting (minor units); sensitive-field masking.

Employee UI is correctly sequenced after Statutory/Banking **or** in parallel after the terminate-close fix; it is not an Attendance backend blocker.

---

## 16. Transaction Boundaries

Request-scoped `AsyncSession` commits at the end of the request (`get_session`). One HTTP call = one transaction.

| Operation | Atomic today? | Should be atomic |
|---|---|---|
| Create employee (code allocate + insert + audit) | Yes, one request | Yes |
| Hire (identity + employment + first assignment + first CTC) | **No** — 2–4 HTTP calls | **RECOMMENDATION:** hire/rehire facade before UI; Attendance can tolerate PRE_JOINING with no employment if it uses as-of employment |
| Rehire | Employment insert only; caller must add assignment/comp | Same |
| Transfer / promotion / shift change | Yes — close + insert + audit | Yes |
| Compensation revision | Yes | Yes |
| Terminate | Employment only | **Must include** close assignment + close compensation (and later statutory/bank) at LWD |
| Inter-entity transfer | In-place LE patch | DOC FR-EMP-011: terminate/close spell + new employment (+ new assignment) in one transaction |

No distributed transactions. Cross-service is in-process `OrganisationService` in the same session — correct for a modular monolith.

---

## 17. Concurrency Model

| Race | Protection (FACT) |
|---|---|
| Concurrent employee create / codes | `UPDATE number_series … RETURNING` row lock |
| Seat limit | Check-then-insert; **TOCTOU** possible under concurrency (two creates both pass count). DB does not enforce seats. **MEDIUM** |
| Concurrent employment create | GiST overlap → `EmploymentDatesOverlapError` |
| Concurrent terminate | `version` / If-Match |
| Concurrent assignment/comp revision | If-Match on current row + GiST |
| Rehire vs still-active spell | GiST |
| Future attendance punches | Not built; needs idempotency keys (standard exists, code missing) |
| Future payroll | ADR-0005 snapshot + period lock — not built |

Optimistic concurrency is the project standard and is applied consistently on Employee writes that mutate existing rows. First assignment/comp insert has no If-Match (correct). Two concurrent “first assignment” inserts: GiST should fail one.

---

## 18. Integration Contracts

| From → To | Contract | Owner | Status |
|---|---|---|---|
| Employee → Attendance | `get_employment_as_of`, `get_assignment_as_of`; stable `employee.id` | Employee service public API | Methods exist; terminate-close **breaks** assignment contract |
| Shift → Attendance | Shift master timings; assignment.shift_id nullable | Organisation owns master; Employee owns assignment | Ready |
| Branch → Attendance | timezone, geofence | Organisation | Ready; holiday/week-off not on Branch |
| Employee → Leave | employment as-of; later grade/notice | Employee | Employment as-of ready |
| Employee → Payroll | identity, employment LE, `get_compensation_as_of`, later statutory/bank | Employee | Comp helper ready; statutory/bank missing; gap issue |
| Legal Entity → Payroll | Employer PF/ESI/TAN/PAN/GST | Organisation | Ready |
| Compensation → Payroll | CTC history; structure later | Employee / Payroll catalogue | Partial |
| Banking → Payroll | payout account as-of | Employee (not built) | Missing |
| Statutory → Payroll | PF/ESI/tax as-of | Employee (not built) | Missing |
| Attendance → Payroll | period attendance summary | Attendance | Missing |
| Leave → Payroll | ledger / LOP | Leave | Missing |
| Payroll → Employee | lock-period backdate reject (FR-EMP-004) | Payroll, enforced at Employee write | Explicitly skipped until Payroll exists |

Consumers **must** import `employee.service` only.

---

## 19. Architectural Debt

### CRITICAL

1. **Terminate does not close assignment/compensation; tests freeze the wrong gap semantics.** Will make Attendance/Payroll as-of wrong after exit. Sources: `EmploymentService.terminate_employment`; `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part D; `test_employee_assignment.py` rehire `effective_to == 2034-01-31`.

### HIGH

2. **`employee.status` never leaves `PRE_JOINING`.** Dual status with employment/`is_active` will confuse every UI and any consumer that trusts identity status.
3. **Inter-entity transfer is an in-place `legal_entity_id` patch**, contradicting FR-EMP-011 and payroll employer history.
4. **No `employee_statutory` / `employee_bank`.** Payroll-blocking by design (A2); still a hard gate.
5. **Assignment branch legal entity vs employment legal entity unconstrained.** Payroll LE and Attendance site can disagree.
6. **FR-ORG-014 active-employee deactivation skip still in Organisation** after Employee exists — can deactivate org units under active assignments (`ON DELETE SET NULL` would null FKs if hard-delete; deactivation is `is_active=false` so assignments still point at inactive dept/shift).
7. **RBAC data-scope unused; `EMPLOYEE.VIEW` is tenant-global.** ESS/manager surfaces unsafe.
8. **Personal contact on `EmployeeRead` without `VIEW_PERSONAL_CONTACT`.**

### MEDIUM

9. Hire not a single transaction/API; PRE_JOINING orphans possible.
10. Seat-limit check-then-insert race.
11. `EMPLOYEE.TERMINATE` / missing Doc 19 codes; statutory/banking view codes undecided.
12. Stale comments/ORM on `head_employee_id`; `VERSION_1_ROADMAP.md` §5 still says org/employee “not started”.
13. No pagination; no Idempotency-Key.
14. Audit stores full CTC; no sensitive_access_log.
15. `cost_centre_id` dangling; salary structure deferred (acceptable until Payroll).
16. Import-linter does not enforce module service-only imports.
17. Celery/outbox documented, unused — fine until jobs/payroll events.

### LOW

18. `display_name` never computed.
19. `is_rehire` column omitted (derived).
20. CHECK vs Literal inconsistency for enums.
21. Frontend PermissionGate missing (blocked only for E-09 UI).
22. Department/assignment branch consistency not validated.

Do **not** rewrite effective-dating, RLS, module layout, or identity/employment split. Those are not debt; they are the foundation.

---

## 20. Build-Order Assessment

**Documented order:** Organisation → Employee Foundation → Employment → Assignment → Shift Assignment → Compensation → Statutory → Banking → Employee UI → Attendance → Leave → Payroll.

**FACT:** Organisation + E-01, E-03, E-04, E-05, E-06 shipped. **E-02 skipped** (addresses, emergency contacts, PAN write path). Roadmap UI (E-09) not started.

**Verdict:** The order is **correct** for Attendance/Payroll dependencies, with these adjustments:

1. **Insert a terminate-orchestration fix** (close child histories) **before Attendance**, inside Employee, not inside Attendance.
2. Keep **Statutory → Banking before Payroll**; they are not required before Attendance.
3. **E-02** is not on the Attendance critical path except PAN encryption for later compliance; can stay deferred.
4. **Holiday calendar / week-off** should land as Organisation or first Attendance slice **before** attendance *status resolution*, after punch ingestion spike if needed.
5. **Approval engine** before Leave/regularisation/payroll sign-off (roadmap already says this); not before Employee statutory.
6. **Employee UI** can parallel Attendance APIs; do not block Attendance backend on Directory.
7. **FR-ORG-014 retrofit** soon after Employee, before production org deactivation with live staff.

Proposed dependency order:

```text
[done] Organisation masters (incl. Shift)
[done] Employee identity, employment, assignment+shift, compensation
[next] Fix terminate → close assignment/compensation (+ status policy)
     → E-07 Statutory → E-08 Banking
     → (parallel) Employee UI primitives + FR-ORG-014
     → Holiday/week-off (org or attendance)
     → Attendance capture + as-of resolution
     → Leave (ledger) + approval skeleton
     → Payroll policies/structure → pay run (ADR-0005)
```

---

## 21. Required Architecture Decisions

### A. Already correctly decided (lock and keep)

- Modular monolith, FastAPI, Postgres, Alembic, RLS tenant isolation (ADRs 0001, 0002, 0013, 0015).
- No Person layer; Employee is the identity (`docs/product/02_PRD.md`).
- Rehire = same `employee.id`/`employee_code`, new `employment` row, children keyed on `employee_id`.
- Effective-dated assignment and compensation with GiST; insert-not-update; service `get_*_as_of`.
- Shift on `employee_assignment.shift_id`, nullable; no Employee-owned roster.
- Compensation independent of assignment.
- Money as integer minor units (ADR-0006).
- Leave as ledger (ADR-0004); payroll snapshot immutability (ADR-0005) — for when those modules exist.
- Employee as its own package; Attendance/Leave/Payroll will be too.
- Full-ish Employee permission catalogue vs org MANAGE shortcut.
- BR-14 cascade deferred; NULL shift means no shift.

### B. Can safely wait

- ATS/onboarding workflow (V2).
- Workflow builder (V3); even approval engine can wait until Leave.
- Salary component catalogue (with Payroll).
- `sensitive_access_log` schema until first RESTRICTED **read** API (Compensation reads exist — **borderline**; can wait until statutory/bank if compensation GET is HR-admin only).
- Generic effective-dating framework.
- Celery/outbox until notifications or pay-run events.
- Pagination until Directory.
- `is_rehire` boolean column.
- Grade CTC band enforcement.

### C. MUST be decided (or implemented to the locked decision) before Attendance

- **Terminate closes assignment (and compensation) at LWD** vs “consumers always intersect employment” — currently docs say close, code does not. This is the gate.
- Attendance population rule: employment as-of ∩ (optional) `is_active`? **RECOMMENDATION:** employment as-of only; `is_active` is access lock.
- NULL `shift_id` behaviour (already deferred as “no shift”) — confirm for status engine (absent vs default present).
- Legal entity SoT for a working day: employment vs branch.
- Whether `employee.status` is in/out of Attendance (out, until state machine).
- Holiday/week-off ownership (Organisation vs Attendance) — can be first Attendance slice but cannot be ignored in the status engine design.
- Punch identity mapping (`user_id`/`employee_id`/device) — not designed in Employee; Attendance must decide without changing Employee keys.

### D. MUST be decided before Payroll

- Build statutory + bank in Employee (already A2) including VIEW permission names.
- UAN/PAN ownership (follow live employee columns per E-07 plan).
- Inter-entity transfer as new employment row.
- What CTC means without salary structure (annual CTC only vs require structure before first pay run).
- Backdate vs payroll lock (FR-EMP-004) — Employee cannot enforce until Payroll lock exists; do not fake it.
- F&F vs Exit module vs terminate API — terminate today is a thin HR action, not FR-EXT.
- Snapshot contents (ADR-0005) once Attendance/Leave exist.

**Product decisions this audit does not silently make:** FR-EMP-014 transition table; whether ON_NOTICE is stored; India-only payroll (Q1 in risk register); seat-count definition (active identity vs active employment).

---

## 22. Recommended Target Architecture

Stay inside existing patterns:

```text
Organisation masters (Company…Shift, later HolidayCalendar/WeekOff)
Employee aggregate
  identity (employee)
  spells (employment) — one ACTIVE max, GiST
  placement (employee_assignment) — as-of, GiST, shift_id nullable
  pay (employee_compensation) — as-of, GiST
  statutory / bank — same as-of shape, keyed on employee_id
Public EmployeeService helpers used by Attendance/Leave/Payroll
Attendance module — punches + day resolution; reads Employee/Org services; owns roster overrides
Leave module — ledger; reads Employee
Payroll module — snapshots of the above; never writes history back except arrears flags
RLS + permission codes per module; DataScope when ESS/managers land
AuditService for writes; sensitive_access_log for RESTRICTED reads
```

**Terminate (target, matching Part D):** one transaction: set employment TERMINATED+LWD; close open assignment and compensation (and later statutory/bank) with `effective_to = last_working_day` if they extend past LWD; optionally set `employee.status=EXITED`. Rehire opens new children at new joining_date with a real gap (as-of in the gap returns none).

**Hire (target, later UI):** optional facade POST that creates identity+employment+initial assignment+initial CTC atomically; keep current sub-resources for independent edits.

Do not introduce a Person table, a combined “current job” table, or employment_id FKs on assignment/compensation.

---

## 23. Migration / Refactoring Risks

| Change | Risk | Notes |
|---|---|---|
| Close assignment/comp on terminate | **Low–medium** | Additive service change. **Must update** rehire tests that expect gap-spanning `effective_to`. No schema change required if `effective_to` already exists |
| Backfill existing open rows after terminate | **Low** today (dev, empty/low data) | If any production-like data exists, script: for TERMINATED employment, if child `effective_to IS NULL` or `> LWD`, set `effective_to = LWD` without overlapping GiST |
| Inter-entity transfer = new employment | **Medium** | Removes or restricts PATCH `legal_entity_id`; any client using patch must switch |
| Drive `employee.status` | **Medium** | Need product transitions; wrong automation will fight Exit later |
| Add statutory/bank tables | **Low** | Same migration style as E-04/E-06; RLS+GiST already templated in `02_EMPLOYEE_DATA_MODEL.md` §3 |
| FK assignment.branch.legal_entity = employment.legal_entity | **Medium** | May reject legitimate multi-LE “work from other branch” if product wants that — **ask product** |
| DataScope | **Medium** | Needs reporting-manager tree from **current** assignment; do not block Attendance admin MVP |
| Rewriting effective-dating / moving FKs to employment_id | **Do not** | That would be a major rewrite; unnecessary |

No evidence that Attendance requires dropping GiST, merging assignment into employee, or splitting shift to a separate history table (roster overrides are a **new** Attendance table, not a replacement).

---

## 24. Final GREEN / YELLOW / RED Assessment

### YELLOW

**Architecture is safe to continue Employee and to plan Attendance, but specific issues must be resolved before Attendance implementation, and statutory/banking before Payroll.**

**Why not GREEN:** The terminate/history contract is wrong in code and tests relative to the locked lifecycle model. Identity status is inert. Payroll inputs (statutory/bank) are absent. Data-scope is a stub. Those are not theoretical nits; they are the exact as-of and ownership questions Attendance and Payroll will hit in the first week.

**Why not RED:** The bounded contexts, table shapes, overlap constraints, as-of helpers, RLS, optimistic concurrency, module layout, and rehire identity model are coherent and already used consistently across E-03–E-06. Fixing terminate-close and adding E-07/E-08 is **completion of the locked design**, not a redesign. Organisation masters (including Shift) are a valid substrate.

---

## 25. Recommended Next Step

**Do not start the Attendance module yet.**

**Next implementation slice (Employee, still):**

1. Align terminate with Part D: in `terminate_employment`, close current assignment and compensation at `last_working_day` (same session, version-safe), and update the rehire integration tests so the gap returns no as-of assignment/compensation.
2. Document (and optionally restrict) `PATCH employment.legal_entity_id` as correction-only until FR-EMP-011 transfer exists.
3. Proceed with **E-07 Statutory** then **E-08 Banking** using the E-06 pattern (`21_EMPLOYEE_STATUTORY_IMPLEMENTATION_PLAN.md`).
4. Track FR-ORG-014 employee-count checks as a small Organisation follow-up.
5. Only then spike Attendance against `get_employment_as_of` + `get_assignment_as_of` + Shift + Branch timezone, treating NULL shift as unresolved.

---

## Appendix A — Doc vs implementation discrepancies (index)

| Topic | Document | Implementation |
|---|---|---|
| Terminate closes assignment/comp | `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part D | `terminate_employment` does not; tests close on rehire |
| `is_rehire` column | Data model §3, decisions Part C | Only `previous_employment_id` |
| Hire nested in `POST /employees` | `01_EMPLOYEE_MODULE_PLAN.md` E-03 | Separate employment API |
| `employment.status` values | Decisions A1 / `07_*` left open; plan said EXITED | CHECK `ACTIVE`/`TERMINATED` |
| FR-ORG-014 employee blocker | Decisions A5 as follow-up when Employee exists | Still skipped in Organisation service |
| Department model “Employee doesn’t exist” | — | Stale comment + no ORM FK |
| `VERSION_1_ROADMAP.md` §5 org/employee not started | Roadmap 2026-08-04 | Org + Employee slices exist |
| Statutory/bank tables | Decisions B5/B6 “build now” | Not started (E-07 plan exists) |
| `sensitive_access_log` | Database architecture §6, A9 E-10 | Table absent |
| Idempotency-Key | API standards §1.2 | No code |
| DataScope | RBAC doc §5 | Always COMPANY |
| Shift override chain | PRD BR-14 / FR-EMP-018 | Explicitly not built; NULL allowed |
| UAN location | Data model statutory vs employee ALTER | `employee.uan_number` only |
| Celery/outbox | System architecture | Not used by these modules |
| Pagination | API standards | Employee lists unpaginated |
| Personal contact classification | RBAC §6 | Returned on EmployeeRead |

---

## Appendix B — Key file index

| Area | Paths |
|---|---|
| Models | `apps/api/src/hrms/modules/employee/models.py`, `.../organisation/models.py` |
| Services | `.../employee/service.py`, `.../organisation/service.py` |
| Repositories | `.../employee/repository.py` |
| API | `.../employee/router.py` |
| Permissions | `.../employee/permissions.py`, `hrms/core/rbac/dependencies.py` |
| Audit | `hrms/core/audit/service.py`, `models.py` |
| RLS session | `hrms/core/db/session.py` |
| Migrations | `apps/api/alembic/versions/20260813*.py`, `20260814*.py` |
| Init GiST/RLS | `apps/api/scripts/sql/001_init_schema.sql` |
| Decisions | `docs/modules/employee/05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` |
| ADRs | `docs/adr/0002-*.md`, `0003-*.md`, `0004-*.md`, `0005-*.md` |
| Frontend | `apps/web/src/components/layout/nav-items.ts`, `hooks/use-api-resource.ts` |

---

ARCHITECTURE STATUS: **YELLOW**

CRITICAL FINDINGS:
- Termination does not close assignment/compensation; as-of queries cover the employment gap; tests currently require that behaviour.
- `employee.status` is never transitioned; three parallel “status” concepts (`status`, `is_active`, `employment.status`).
- Payroll SoT tables `employee_statutory` and `employee_bank` do not exist.

MUST FIX BEFORE ATTENDANCE:
- Close (or otherwise invalidate) assignment at `last_working_day` so `get_assignment_as_of` is safe; update tests/docs together.
- Treat employment as-of as the employed-on-date gate; do not use `employee.status`.
- Decide legal-entity SoT (employment vs branch) and NULL shift = no shift.
- Holiday/week-off ownership before status-resolution (may be first Attendance slice).

MUST FIX BEFORE PAYROLL:
- E-07 Statutory and E-08 Banking with permission names locked.
- Same terminate-close for compensation (and statutory/bank).
- Stop in-place legal-entity mutation as the transfer mechanism.
- Payroll lock/backdate contract (can stub as “not enforced until Payroll” only if writes stay rare).
- Restricted-read audit before bank/statutory GET.

CAN DEFER:
- Employee Directory/360 UI and PermissionGate.
- E-02 addresses/emergency contacts.
- BR-14 shift cascade.
- Salary structure / components.
- DataScope SELF/REPORTEES (until manager/ESS).
- Celery, outbox, idempotency (until punches/pay runs).
- ATS, workflow builder, performance.
- Generic effective-dating framework.

RECOMMENDED NEXT ACTION:
- Implement terminate-side close of current assignment and compensation to `last_working_day` (service + tests only), then execute E-07 per `docs/modules/employee/21_EMPLOYEE_STATUTORY_IMPLEMENTATION_PLAN.md`.
