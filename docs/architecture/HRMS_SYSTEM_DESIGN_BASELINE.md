# HRMS System Design Baseline

**Status:** Architecture review only. No application code, database schema, migrations, frontend
code, or tests were created or modified to produce this document. Nothing was committed.

**Date:** 2026-08-15

**What this document is:** a synthesis layer, not a new source of truth. It cross-references
`docs/product/*`, `docs/architecture/*`, `docs/adr/*`, `docs/database/*`, `docs/modules/*`, and
`docs/design/*` against the actual implementation (`apps/api/src/hrms/`, `apps/api/alembic/`,
`apps/api/tests/`, `apps/web/src/`). It **does not silently override** any product document. Where
a product document and the running code disagree, both are stated, tagged, and left for a
conscious decision — never silently resolved in this document's own favor.

**This document builds directly on `docs/architecture/00_HRMS_SYSTEM_ARCHITECTURE.md`** (written
earlier the same day) and `docs/architecture/00_SYSTEM_ARCHITECTURE_AUDIT.md` (the original
Employee/Organisation FACT audit). It does not repeat their full evidence trails; it restructures
and extends them into the 22-section format requested for this review, going materially deeper on
the design-level architecture for Attendance, Leave, Payroll, Statutory, and Banking — modules
that exist only as documentation today. **Read `00_HRMS_SYSTEM_ARCHITECTURE.md` for the fuller
line-by-line evidence** behind every FACT claim below; this document cites it rather than
re-deriving it.

**Legend (used throughout, mandatory per this review's own instructions):**
- **FACT** — observed directly in code, schema, migrations, or tests.
- **DOC** — stated in an authoritative document; not yet built, or not independently verified in
  code.
- **DISCREPANCY** — DOC and FACT disagree. Never silently resolved — the disagreement itself is
  the finding.
- **OPEN** — genuinely unresolved; this document does not invent an answer.
- **RECOMMENDATION** — a proposed next action, not a locked rule. Locked rules live in
  `docs/architecture/HRMS_ARCHITECTURE_DECISION_LOG.md`.

**How to use this document:** future implementation tasks for E-07 through E-10, Attendance,
Leave, Payroll, and ESS should read this document first. If an implementation task discovers this
document is wrong or out of date, **the conflict must be written down** — in the task's own
closeout report, or as an update to this document — never silently coded around.

---

## Section 1 — Current System Architecture

### 1.1 Modular monolith structure — FACT

One Python codebase (`apps/api/src/hrms/`), one deployable in practice today. `docs/product/
03_System_Architecture.md §1.1` documents four deployables sharing this codebase (Core API,
Device Ingestion, Worker, Beat) — **DISCREPANCY**: only Core API is wired. `apps/api/src/hrms/
app.py` mounts `health`, `identity`, `organisation`, `employee` routers and nothing else.
`ingestion/routes.py` exists (one health endpoint) but is never imported by `app.py`.
`entrypoints/worker.py`/`beat.py` are not confirmed invoked by anything running. **Which should
become authoritative:** the DOC framing is the correct target architecture (ADR-0001, ADR-0007,
ADR-0014 all justify the four-deployable split on real, still-valid reasoning) — this is not a
case where code should override doc. **Product decision required:** no — this is a build-sequence
gap, not a design disagreement. It needs building, not deciding.

### 1.2 Backend architecture — FACT

Every module: `router.py` (HTTP only) → `service.py` (business logic, the only cross-module
import surface) → `repository.py` (SQLAlchemy, tenant predicate) → `models.py` → `schemas.py` →
`permissions.py` → `exceptions.py`. Confirmed identical across `identity`, `organisation`,
`employee`. `events.py`/`tasks.py` exist as filenames in the module-standard convention but are
empty/absent in every built module.

### 1.3 Frontend architecture — FACT

Next.js 14 App Router, React 18, TypeScript, Tailwind, shadcn/ui. Pages exist for every
Organisation entity only. Zero Employee UI. Detailed in Section 16.

### 1.4 Database architecture — FACT

PostgreSQL 16, SQLAlchemy 2.x async + `asyncpg`, Alembic. Shared schema, `company_id` + RLS per
tenant table. 20 baseline tables (`001_init_schema.sql`) + 18 additive migrations, head
`20260814120000_employee_compensation`. Detailed in Section 14.

### 1.5 Tenancy — FACT, with one OPEN item

`TenantContext` (frozen dataclass, `company_id` + `user_id`) lives in a `ContextVar`. **Two
independent population paths**, confirmed by direct code read:
1. `TenancyMiddleware.dispatch` — runs first, before auth — sets an **unverified** context from
   the raw `X-Company-Id` header, no membership check.
2. `get_tenant_context` dependency — runs after `get_current_user`, validates the header against
   the JWT's `company_id` claim + an active `UserCompany` row, then overwrites the context with a
   verified one.

**OPEN**, restated from `00_HRMS_SYSTEM_ARCHITECTURE.md §17`: whether every route's dependency
graph guarantees `get_tenant_context` resolves before `get_session()` opens its RLS-scoped
session was not independently verified per route in this or the prior review. This is the single
highest-value verification task to run *before* Payroll (a module where a scoping mistake has
financial consequences) adds write paths — not asserted broken, but not proven safe either.

### 1.6 RLS — FACT

`ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY` + a single `tenant_isolation` policy
(`company_id = current_setting('app.company_id', true)::uuid`) per tenant table, re-asserted
idempotently inline in every migration that touches that table. **DISCREPANCY:**
`docs/database/Database_Architecture.md §3/§9` cites `scripts/sql/002_row_level_security.sql` as
the live RLS mechanism; that file is **never invoked by Alembic** (confirmed by explicit comments
in every migration since `20260807150000`). **Authoritative:** the inline-per-migration pattern is
what actually runs — the dev-facing doc needs a correction, not the code.

### 1.7 Authentication — FACT + DISCREPANCY

JWT HS256, 15-minute access token, 30-day rotating refresh token with `token_family_id`-based
reuse detection (confirmed in `core/auth/`, `core/db/repositories/identity.py`,
`modules/identity/service.py:94-96`) — real, working code, not merely documented. Argon2id
password hashing (`core/auth/passwords.py`). **DISCREPANCY on MFA:** `docs/product/
10_Authentication_Architecture.md §3` documents a designed-but-Phase-2-enabled TOTP flow with
`user.mfa_secret_enc`/`.mfa_enabled` columns. FACT: `user.mfa_enabled` exists from
`001_init_schema.sql`; `mfa_secret_enc` was not confirmed added by any of the 19 migrations; zero
`mfa`/TOTP/`pyotp` code exists anywhere in `core/auth/`. Treat MFA as fully undesigned-in-code
today, not a partial build.

### 1.8 Authorization (RBAC) — FACT + DISCREPANCY, detailed in Section 11

`require_permission()` performs a real DB-backed permission check but **always returns
`DataScope(level=COMPANY)`** regardless of role — data-scope enforcement does not run. Detailed
in Section 11/18.

### 1.9 Audit — FACT

`AuditService.record()` — write-path only, insert-only `audit_log`, no commit of its own (relies
on caller's session). Every mutating service method across the three built modules calls it as
its last step. `sensitive_access_log` (read-path logging of RESTRICTED-field access) has **zero**
code anywhere — DOC only, locked to build in E-10.

### 1.10 API conventions — FACT, detailed in Section 13

`DataEnvelope`/`ListEnvelope`/`ErrorEnvelope`, `If-Match` optimistic concurrency, `?as_of=` on
effective-dated resources, cross-tenant → 404 never 403, `extra="forbid"` mass-assignment
rejection. **Pagination is entirely unimplemented** — `ListEnvelope.pagination` is always omitted;
the frontend's TS type has no pagination fields despite a comment claiming parity.

### 1.11 Background jobs — DOC only, FACT: one sample task exists

Celery + Redis chosen (ADR-0014). `core/celery_app.py` exists with a single `health.ping` task. No
module has a `tasks.py`. No `outbox_event` table. No Beat schedule. Everything else in this area
(queue topology, canvas pipelines, idempotent task design) is DOC only.

### 1.12 Caching — DOC only

`docs/product/03_System_Architecture.md §6` documents explicit TTLs (permissions 60s, tenant
config 5min, statutory master 1hr, etc.) and an explicit **never-cache list**: leave balances,
today's attendance status, payroll figures, approval states. **FACT:** no caching layer exists in
code at all — `RbacService.has_permission` does a fresh DB query every call, contradicting the
documented 60s Redis cache. Since no cache exists, the never-cache list is trivially satisfied
today — but it is the binding rule the moment any caching is introduced.

### 1.13 Object storage — DOC only

S3/MinIO via `aioboto3`, presigned URLs, virus-scan hook (`docs/product/07_Backend_Architecture.md
§6`). Local dev has MinIO in `docker-compose.yml` (FACT — confirmed by
`docs/architecture/00_Repository_Audit.md`), but no `shared/files/` wrapper code, no `file` table,
no upload endpoint exists anywhere yet.

### 1.14 Notifications — DOC only

Notification engine, multi-channel dispatch (email/SMS/WhatsApp/push), append-only
`notification_log` — all documented (`docs/product/20_Workflow_Approval_Notification_Engine.md`,
`docs/product/22_Integration_Specification.md §3`), zero code.

### 1.15 Integrations — DOC only

Biometric device ingestion, SMS/WhatsApp/email providers, accounting/ERP export, payment gateway
(billing only, explicitly never salary disbursement) — all documented in depth
(`docs/product/22_Integration_Specification.md`), zero integration code in this repo.

---

## Section 2 — Domain Boundaries

Canonical map, current + planned. "Allowed dependencies" always means "via `<module>.service`
only," per `docs/architecture/02_Module_Standard.md §2`.

| Domain | Status | Owns (entities/tables) | APIs | Allowed dependencies | Forbidden |
|---|---|---|---|---|---|
| **Platform** (`core/`) | Built | Nothing business-owned — `TenantContext`, RLS session plumbing, permission-check engine, audit sink, error hierarchy, JWT | none (not a router) | none — everything imports it | Business logic of any kind |
| **Identity** (`modules/identity/`) | Built | `user`, `user_company`, `role`, `permission`, `role_permission`, `user_role`, `session`, `refresh_token` | `/v1/auth/*`, `/v1/users/*` (partial) | `core/` only | — |
| **Organisation** (`modules/organisation/`) | Built | `company`, `legal_entity`, `branch`, `department`, `designation`, `grade`, `shift`, `subscription`, `plan`, `plan_feature`, `company_feature_flag`, `company_setup_progress` | `/v1/companies`, `/v1/legal-entities`, `/v1/branches`, `/v1/departments`, `/v1/designations`, `/v1/grades`, `/v1/shifts` | `core/`, `identity.service` (registration issues tokens) | `employee.*` (none needed today; a forward-looking rule, not a violation found) |
| **Employee** (`modules/employee/`) | Built (E-01, E-03–E-06) | `employee`, `employment`, `employee_assignment`, `employee_compensation`, `number_series` | `/v1/employees`, `/v1/employees/{id}/employments`, `/v1/employees/{id}/assignments`, `/v1/employees/{id}/compensation` | `core/`, `organisation.service` (FK existence checks) | `organisation.repository`/`.models` |
| **Attendance** | Not built | Planned: `shift_roster`, `punch`, `attendance_day`, `regularisation_request`, `ot_request`, `attendance_lock`, `attendance_device`, `geofence` | none | `employee.service` (as-of employment/assignment), `organisation.service` (shift master, branch geo/timezone) | Must not write to Employee tables; must not compute payroll |
| **Leave** | Not built | Planned: `leave_type`, `leave_policy`(+line/assignment), `leave_ledger`, `leave_application`, `comp_off_ledger` | none | `employee.service` (employment as-of, grade for policy resolution), `attendance.service` (planned, for LOP inputs later) | Must not store a mutable balance column (ADR-0004) |
| **Payroll** | Not built | Planned: `salary_component`, `salary_structure`(+component), `statutory_master`, `pay_run`, `pay_run_input_snapshot`, `payslip`(+line), `arrears`, `loan`(+schedule), `tax_declaration`, `tax_computation`, `bank_advice`, `statutory_filing`, `fnf_settlement` | none | `employee.service` (compensation, statutory, bank), `organisation.service` (legal entity statutory codes), `attendance.service` (planned, period summary), `leave.service` (planned, LOP) | Must never write back into Employee/Attendance/Leave source tables (ADR-0005) |
| **ESS** | Not built | No new tables — a permission-scoped view over Employee/Attendance/Leave/Payroll | none | Every module above, read-mostly, `SELF` data-scope only | Must not introduce a parallel write path around each module's own service |
| **Reports** | Not built | Planned: report definitions, possibly a read-replica-facing query layer | none | Every module's `service.py`, read-only | Must not query other modules' tables directly (defeats the point of a reporting layer if it does) |
| **Notifications** | Not built | Planned: `notification_event`, `notification_template`, `notification_log`, `notification_preference` | none | Consumed via domain events (outbox), not direct calls, per every module | Must not know business rules of the module that triggered it beyond the event payload |
| **Approval / Workflow** | Not built | Planned: `workflow_definition`(+version/node), `approval_request`(+step/action), `delegation` (ADR-0008 — one generic engine, not per-module logic) | none | Consumed by Leave/Compensation-revision/Exit/etc. as a generic service | Must not be reimplemented per-module — this is explicitly the one place a generic framework is the *correct* choice (ADR-0008), unlike effective-dating |
| **Audit** (`core/audit/`) | Built (write-path only) | `audit_log`; planned `sensitive_access_log` | none (not a router) | none — every module writes to it | Must remain append-only; no module may delete/edit an audit row |
| **RBAC** (`core/rbac/`) | Built (partial — see §11) | `permission`, `role_permission`, `user_role` (owned by Identity's schema, read by `core/rbac`) | none (not a router) | none — every module's routes depend on it | — |

**Circular dependencies found:** none in the built code (Organisation and Employee do not import
each other's services in a cycle — Employee reads Organisation, Organisation never reads
Employee). **Circular-dependency risk in the planned graph:** Attendance and Leave both plan to
read from each other conceptually (Leave needs Attendance presence data for LOP; Attendance needs
Leave's approved-leave status to mark a day `ON_LEAVE`). This is not necessarily a cycle if scoped
correctly — see Section 7 and Section 17 for the resolution (Attendance reads Leave's *approved
application* status via `leave.service`; Leave reads Attendance's *summary* via
`attendance.service` only at payroll-period-close time, not per-day — these are two different,
non-simultaneous read directions, not a live cycle).

---

## Section 3 — Canonical Entity Relationship Model

**Built (FACT):**

```text
Company
  ├── LegalEntity (required legal_entity_id on Branch and on Employment)
  │     └── Branch (required legal_entity_id; optional legal_entity match to employment — OPEN, §36
  │                 item 5 of 00_HRMS_SYSTEM_ARCHITECTURE.md)
  │           └── Department (optional branch_id; optional self-ref parent_id, depth ≤ 5)
  │                 └── Designation (optional department_id; optional grade_id; optional
  │                                  next_designation_id self-ref, passive/unexposed)
  ├── Grade (standalone; company_id only)
  └── Shift (standalone; company_id only; master definition only)

Employee (permanent identity)
  ├── Employment[]            1:N, keyed employee_id, spell-bounded, GiST no-overlap on
  │                           [joining_date, last_working_day]
  ├── EmployeeAssignment[]    1:N, keyed employee_id (NOT employment_id), effective-dated,
  │                           GiST no-overlap; FKs → branch/department/designation/grade/
  │                           reporting_manager(→employee)/dotted_line_manager(→employee)/
  │                           shift, all ON DELETE SET NULL; cost_centre_id has no FK target
  └── EmployeeCompensation[]  1:N, keyed employee_id, effective-dated, GiST no-overlap
```

**Documented, not built — using only fields named in `docs/product/08_Database_Architecture.md
§5` and the E-07 statutory plan, nothing invented:**

```text
Employee
  ├── EmployeeStatutory[]  1:N, keyed employee_id, effective-dated (planned E-07)
  │     Fields: is_pf_applicable, pf_number, pf_wage_ceiling_opt_out, vpf_amount/percentage,
  │     is_esi_applicable, esi_ip_number, pt_state_code, is_lwf_applicable, tax_regime,
  │     is_director, is_international_worker. NO uan column — UAN stays on
  │     employee.uan_number (a real doc/doc conflict, already resolved in the E-07 plan
  │     in favor of the live schema).
  ├── EmployeeBank[]       1:N, keyed employee_id, effective-dated (planned E-08)
  │     Fields: account_holder_name, account_number_enc, bank_name, ifsc, branch_name,
  │     payment_mode, is_primary, verification_status, penny_drop_reference.
  └── EmployeeDocument[], EmployeeDependent[], EmployeeEducation[], EmployeeExperience[],
      EmployeeSkill[], EmployeeAddress[], EmployeeEmergencyContact[], EmployeeEvent[]
      1:N, keyed employee_id, plain (non-effective-dated) collections (planned E-02/E-08)

Attendance (planned)
  ├── Punch[]           immutable append-only, employee_id + device/source, partitioned by month
  └── AttendanceDay[]   derived, UNIQUE(employee_id, attendance_date), reads employment-as-of +
                        assignment-as-of (branch/shift) + shift master + holiday/week-off

Leave (planned)
  ├── LeaveLedger[]      append-only, employee_id, signed days, never updated/deleted
  └── LeaveApplication[] employee_id, date range, status, references LeaveLedger entries on
                         approval

Payroll (planned)
  ├── PayRun                     company-scoped, period-scoped, not employee-keyed
  ├── PayRunInputSnapshot[]      one per employee per run, immutable JSONB copy of every input
  │                              listed in Section 8
  └── Payslip[]                  employee_id + pay_run_id, immutable once the run finalises
```

**Ownership boundaries (restated, load-bearing):** Legal Entity owns the **employer's own**
statutory registration numbers (PAN/TAN/CIN/GSTIN/PF code/ESI code/LWF registration — already
live). `employee_statutory` (planned) owns the **individual employee's own** enrollment/
identification data within those employer registrations (their own PF number, ESI IP number, tax
regime). These are two different entities and there is no field-level overlap or duplication risk
between them, confirmed by direct comparison of both field lists.

**Nullable relationships worth stating explicitly, because a future module will hit them:**
`employee_assignment.reporting_manager_id` is nullable (a CEO-level hire has no manager, FR-EMP-002
— this is intentional, not a data gap). `employee_assignment.shift_id` is nullable (BR-14's
override chain is deferred — `NULL` means "no shift resolves," not an error). `employment.
last_working_day` is nullable **and structurally required to be NULL unless status=TERMINATED**
(DB `CHECK`-enforced) — a query that treats `last_working_day IS NOT NULL` as "this spell is over"
is safe; a query that treats `last_working_day IS NULL` as "this spell is definitely still open"
is also safe, because the two are kept in lockstep by the constraint.

---

## Section 4 — Employee Lifecycle

(This section restates, at slightly higher altitude, `00_HRMS_SYSTEM_ARCHITECTURE.md §8` — see
that document for the full FACT/DOC citation trail per transition.)

**Creation → first employment → assignment → shift → compensation → transfer → promotion →
termination → rehire, traced:**

1. `POST /v1/employees` — `employee` row created, `employee.id` and `employee.employee_code`
   allocated once, **never reissued for the life of the tenant relationship, including across a
   rehire**. `employee.status = PRE_JOINING`. **No employment exists yet at this point** — a
   standalone identity with zero employment rows is a real, reachable state (FACT, by design, per
   the two-call hire flow).
2. `POST /v1/employees/{id}/employments` — first `employment` row, `status = ACTIVE`,
   `joining_date` set, `legal_entity_id` required.
3. First `employee_assignment` insert — branch/department/designation required at the service
   layer for the *first* row (not DB-enforced); grade/manager/shift optional.
4. Shift is one column (`shift_id`) on the same `employee_assignment` row, not a separate
   assignment table — set via the same `POST .../assignments` call with
   `change_type = SHIFT_CHANGE`.
5. First `employee_compensation` insert — independent transaction, independent table, no coupling
   to assignment.
6. Transfer/promotion/manager/shift change — all the same `POST .../assignments` shape,
   distinguished only by `change_type` (which also selects the gating permission —
   `PROMOTION`→`.PROMOTE`, everything else→`.TRANSFER`). Each is close-current-row +
   insert-new-row, same transaction.
7. Compensation revision — `POST .../compensation`, same close+insert shape, its own table,
   unaffected by assignment changes and vice versa.
8. **Termination** — `POST .../employments/{id}/terminate` sets `employment.status = TERMINATED`
   + `last_working_day`. **FACT, the one correctness defect in this entire lifecycle**: this does
   **not** close the open `employee_assignment`/`employee_compensation` rows. Historical
   correctness is **broken** for any as-of query landing inside the post-termination gap, until
   fixed — see Section 18, CRITICAL-1.
9. **Rehire** — new `employment` row, `previous_employment_id` set to the prior row's id, **same
   `employee.id`/`employee_code`**. New `employee_assignment`/`employee_compensation` rows open
   fresh at the new joining date; nothing carries forward automatically — department, designation,
   grade, shift, and CTC must all be re-entered. The old rows are untouched, permanently queryable.

**Exactly how a rehire works, stated once, precisely, because every future module depends on
getting this right:** `employee_assignment` and `employee_compensation` are keyed on
`employee_id`, **never `employment_id`**. This means a rehire produces **zero new FK relationships
to invent** — the existing child tables simply gain new rows against the same, never-changing
`employee_id`. A five-year gap between two `employment` rows produces a five-year gap with no
`employee_assignment`/`employee_compensation` rows in it (nothing to assign or pay during a period
with no active spell) — this is the correct, expected shape, not a data integrity problem, and no
special-case code is needed anywhere to make history queries "just work" across the gap.

**Historical correctness verdict:** **preserved for `employment` itself** (GiST-enforced,
correctly closed at exit). **Broken for `employee_assignment`/`employee_compensation` during the
post-termination gap** until the terminate fix lands (Section 18).

---

## Section 5 — Effective-Dating Architecture

**Canonical pattern, live today for `employee_assignment` and `employee_compensation` (FACT),
and the intended pattern for `employment`'s own overlap protection even though `employment` is
spell-bounded rather than effective-dated in the strict sense:**

```sql
-- Write: close current, insert new — same transaction, no exceptions
UPDATE <table> SET effective_to = :new_effective_from - 1 day WHERE id = :current_row_id;
INSERT INTO <table> (effective_from, effective_to, ...) VALUES (:new_effective_from, NULL, ...);

-- Structural overlap prevention
EXCLUDE USING gist (
  employee_id WITH =,
  daterange(effective_from, COALESCE(effective_to, 'infinity'::date), '[]') WITH &&
);

-- Current
WHERE employee_id = :id AND effective_to IS NULL AND deleted_at IS NULL;

-- As-of a date
WHERE employee_id = :id AND effective_from <= :date
  AND (effective_to IS NULL OR effective_to >= :date);

-- Full history
WHERE employee_id = :id ORDER BY effective_from;
```

`employment` uses the same GiST-overlap mechanism (`employment_no_overlap`, on
`[joining_date, COALESCE(last_working_day, 'infinity')]`) but is **not** effective-dated in the
same sense — a spell is a discrete episode, not a versioned attribute; a *new spell* is a new row,
never an update-with-history of an existing one (`docs/modules/employee/
05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part C).

**Concurrency:** `version` + `If-Match` guards the "close current row" half of every write, so two
concurrent transfer/revision requests race safely. First-ever insert needs no `If-Match`.

**The architectural rule future modules MUST follow, stated once, canonically:**

> Any attribute that changes over time and must be reconstructable as of a past or future date
> lives in its own child table, keyed on the identity that owns its history (`employee_id` for
> Employee's own children — the equivalent stable identity for other domains), with
> `effective_from`/`effective_to`, a GiST exclusion constraint preventing overlap, and a
> close-then-insert write pattern. Do not add a generic, config-driven, polymorphic
> effective-dating engine — this pattern is meant to be hand-repeated per table (ADR-0003's own
> stated trade-off, reconfirmed correct by every slice built so far).

**Where this pattern extends beyond Employee, already decided by ADR reference, not invented
here:**
- `employee_statutory`/`employee_bank` (planned E-07/E-08) — same shape, keyed `employee_id`.
- `statutory_master` (planned Payroll) — same shape, keyed by jurisdiction, not `employee_id`
  (ADR-0011).
- `leave_policy_assignment` (planned Leave) — same shape is the natural fit for
  "this policy applies to this scope from this date," though Leave's own core balance mechanism
  (the ledger, ADR-0004) is a **different** pattern — append-only, not effective-dated — see
  Section 7. Do not conflate the two.
- `shift_roster`/`attendance_day` (planned Attendance) — **not** this pattern. One row per
  employee per date is a different shape (a derived daily fact, not a versioned attribute) — see
  Section 6.

---

## Section 6 — Attendance Architecture

**Status: design-level analysis only, per this review's scope. Zero Attendance code exists.**
This section synthesizes ADR-0007, ADR-0010, `docs/product/03_System_Architecture.md §4`,
`docs/product/08_Database_Architecture.md §6`, `docs/product/17_SRS_Phase1_Core_Modules.md`
FR-ATT-*, `docs/product/22_Integration_Specification.md §2`, and `docs/product/
15_Testing_Strategy.md §4` into one coherent target architecture. All DOC unless noted.

### 6.1 The pipeline

```text
Raw event (punch)
   → ingestion (device push / mobile GPS / web / kiosk / manual entry / import)
   → idempotent write to `punch` (immutable, append-only, partitioned by month)
   → debounced recompute trigger (60s window per employee/date — multiple punches for the
     same employee/date within the window collapse into one recompute, not several)
   → `attendance_day` resolution (derived, one row per employee per date):
       1. employment-as-of(date) — population gate; absent = not in scope for the day
       2. assignment-as-of(date) — shift_id, branch_id (for geofence/timezone)
       3. shift master (grace minutes, cross-midnight flag, OT eligibility, half-day threshold)
       4. holiday/week-off for the date (branch's calendar/pattern — NOT YET BUILT, see §6.6)
       5. leave application status for the date (approved leave overrides presence-based status)
       6. punches for the date, matched against the shift window
   → attendance_day.status resolved: PRESENT/ABSENT/HALF_DAY/WEEKLY_OFF/HOLIDAY/ON_LEAVE/
      ON_DUTY/WFH/COMP_OFF/NOT_JOINED/EXITED
   → attendance_day feeds Leave (LOP source-of-truth) and Payroll (period summary) — read only,
      never written to by either
```

### 6.2 What is immutable

Every `punch` row, once written. A punch is never edited or deleted. Corrections are new punches
or a `regularisation_request` (a separate, auditable record proposing a correction), never a
mutation of the original punch — the same immutable-history principle that governs
`employee_assignment`/`employee_compensation` (Section 5), applied to a non-effective-dated table.

### 6.3 What can be corrected

`attendance_day` itself (a *derived* row) can be recomputed and can be manually overridden
(`is_manual_override`, per the documented column set) — but every override should itself be
audited (who, when, why, old value, new value) via the same `AuditService` write-path pattern
every other module uses, not a bespoke mechanism.

### 6.4 What is derived vs. what is recalculated

`attendance_day` is entirely derived — no field on it is a primary source of truth; every field is
computed from `punch` + `employment`-as-of + `assignment`-as-of + shift master + holiday/
week-off + leave status. It is **recalculated**, not incrementally patched, whenever any upstream
input changes within the recompute window (a late-arriving punch, a leave approval that lands
after the day was first resolved, a regularisation approval). `computation_trace` (documented
JSONB column) should record what the resolution actually read, mirroring Payroll's own
`calculation_trace` convention (Section 8) — auditable, reproducible, not a black box.

### 6.5 What is locked after payroll

Once a `pay_run` reaches its SNAPSHOT INPUTS step (Section 8), the `attendance_day` rows for that
period should become locked (`is_locked`, documented column) — a subsequent correction to a
locked day must not silently change a figure Payroll already snapshotted; it becomes an arrears
input for a **later** pay run, mirroring ADR-0005's own immutability posture applied one layer
upstream. This is the attendance-side half of the same principle Compensation/Assignment already
apply to Employee history: once a downstream consumer has committed to a value, the source module
does not retroactively rewrite it out from under that consumer.

### 6.6 Cross-cutting concerns, resolved by existing ADRs — do not re-litigate these

- **Timezone / midnight / cross-midnight shifts** — ADR-0010: storage is UTC; every business-day
  boundary computation uses `company.timezone`, never server-local or UTC midnight. A cross-
  midnight shift's punches belong to the shift's **start** date, not whichever calendar date the
  clock happens to read at punch time — this is a shift-master-driven attribution rule
  (`is_cross_midnight` on the shift record), not something Attendance invents per-punch.
- **Grace periods / half-days / OT** — all shift-master-owned configuration (`grace_in_minutes`,
  `grace_out_minutes`, `half_day_threshold_hours`, `min_hours_full_day`, `is_ot_eligible`) that
  Attendance reads, never redefines. Attendance's own tables should not duplicate these values.
- **Duplicate punches** — idempotency key `sha256(device_serial + biometric_id + timestamp)`
  (`docs/product/22_Integration_Specification.md §2`) rejects true duplicates at the ingestion
  boundary, before they ever reach `attendance_day` resolution.
- **Offline punches** — the on-prem agent pattern buffers locally (SQLite) and pushes once
  connectivity returns; `attendance_day` recompute must be idempotent to a late-arriving batch of
  offline punches, not just to a single live one.
- **NULL shift** — BR-14's cascading override chain is deliberately deferred (Section 5 of
  `00_HRMS_SYSTEM_ARCHITECTURE.md`, restated here because it is Attendance's single most load-
  bearing input assumption): `employee_assignment.shift_id IS NULL` means "no shift resolves,"
  full stop — Attendance must not invent a fallback cascade.

### 6.7 What Attendance genuinely lacks a foundation for today

**Holiday calendar and week-off** — `holiday_calendar`/`holiday` are unexpanded stubs from
`001_init_schema.sql`, never touched by any of the 18 additive migrations, unused by any code.
`branch.week_off_pattern_id` was never added (its target table, `week_off_pattern`, was never
built — deferred by Branch's own migration, never picked up since). **This is a genuine, structural
gap, not merely unbuilt Attendance code** — status resolution *cannot* distinguish a weekly off
from an absence without it. **RECOMMENDATION:** this should be either a small Organisation
follow-up slice, or Attendance's own explicit first sub-slice (before punch ingestion) — not
something a punch-ingestion-first implementation can quietly work around, because "was this a
week-off" is a precondition for "was this an absence," not an independent feature.

### 6.8 Attendance's dependency on the Employee terminate fix

Restated because it is the single most concrete, checkable blocker: `get_assignment_as_of`
returning stale data through a post-termination gap (Section 18, CRITICAL-1) means Attendance,
built naively against that helper, will mark a terminated employee as still assigned to a shift
and branch. This must be fixed in Employee before Attendance's first line of resolution logic is
written.

---

## Section 7 — Leave Architecture

**Status: design-level analysis only. Zero Leave code exists.** Synthesizes ADR-0004,
`docs/product/08_Database_Architecture.md §7`, `docs/product/17_SRS_Phase1_Core_Modules.md`
FR-LVE-*, `docs/product/02_PRD.md` BR-14, and `docs/product/15_Testing_Strategy.md §4`.

### 7.1 The conceptual flow

```text
leave_type (company-scoped master: accrual method, max balance, carry-forward rules,
            encashment rules, sandwich-rule flag, gender/marital-status applicability)
   → leave_policy + leave_policy_line (which leave_types, at what rates, for whom)
   → leave_policy_assignment (COMPANY/BRANCH/DEPARTMENT/GRADE/EMPLOYMENT_TYPE/EMPLOYEE scope,
                               priority — BR-14's "most specific wins" chain, ALREADY the
                               resolved mechanism per Grade's own audit, superseding the
                               originally-proposed grade.leave_policy_id single-FK model)
   → leave_ledger (append-only — every accrual/application/cancellation/encashment/
                    carry-forward is its own immutable row; balance = SUM(days), never a
                    stored counter — ADR-0004, non-negotiable)
   → leave_application (request, status machine, half-day handling, sandwich-rule day-counting)
   → approval (via the generic Workflow/Approval engine, ADR-0008 — not a Leave-specific
               approval implementation)
   → attendance impact: an approved leave_application should cause attendance_day.status
                         to resolve to ON_LEAVE for the covered dates, overriding a raw
                         "no punch" reading — this is Attendance READING Leave's approved-
                         application status, one direction only
   → payroll impact: LOP (loss of pay) days are computed from leave_ledger + attendance_day
                      as-of the pay period, read by Payroll's snapshot step — Leave does not
                      push a figure to Payroll; Payroll pulls at snapshot time (Section 8)
```

### 7.2 Ownership

Leave owns `leave_type`, `leave_policy`(+line/assignment), `leave_ledger`, `leave_application`,
`comp_off_ledger`. It does **not** own attendance data (reads it) and does **not** own payroll
figures (Payroll reads Leave, at snapshot time, not the reverse).

### 7.3 Historical requirements

The ledger itself **is** the history — no separate history table needed (matches the audit's own
reasoning for why an append-only ledger, not a mutable-counter-plus-audit-log, is the correct
shape: "the audit trail becomes the actual system of record, not an afterthought bolted onto
business logic"). `leave_policy_assignment` should follow the effective-dating pattern (Section 5)
since policy scope/rate assignment genuinely changes over time and must be reconstructable
as-of a past leave year for correct accrual recomputation.

### 7.4 The one genuinely unresolved piece, restated from the Grade audit

`grade.leave_policy_id` was **retracted** in the Grade module's own build (its audit explicitly
notes the Sprint plan's own later self-correction: "use `leave_policy_assignment` as the real
mechanism," not a single FK on Grade). This means the leave-entitlement leg of BR-14's override
chain has **no implemented column anywhere** to hang off of yet — Leave's first slice must build
`leave_policy_assignment` from scratch, it cannot assume a `grade.leave_policy_id` shortcut exists.

### 7.5 Interaction with Attendance — resolving the circular-dependency question raised in
Section 2

Not a true cycle: Attendance reads Leave's **approved application** status per-day (a narrow,
specific read — "is this date covered by an approved leave application for this employee?").
Leave reads Attendance's **summary** only when computing LOP at payroll-period-close time (a
different, batch-oriented read, not a per-request dependency). Both directions go through
`<module>.service`, never direct table access, and neither module needs the other to be "live" in
the request-handling sense at the same moment — this keeps the dependency real but acyclic in
practice.

---

## Section 8 — Payroll Architecture

**Status: design-level analysis only. Zero Payroll code exists. This is the most important
dependency review in this document**, per this review's own framing — Payroll is the
highest-effort, highest-risk module in the entire roadmap (`docs/product/
25_Project_Plan_Estimation_and_Team.md §3`: 17 weeks, the longest single build block, the
smallest AI-assisted effort compression of any module).

### 8.1 The canonical payroll input model, for a historical period

| Input | Source | Classification |
|---|---|---|
| Employee identity | `employee` | **Live configuration** (identity doesn't change per period, but is read fresh — no reason to snapshot a name) |
| Employment episode / legal entity | `employment` as-of the period | **Effective-dated configuration** (read as-of, not live-current) |
| Branch / department / designation / grade / shift | `employee_assignment` as-of the period | **Effective-dated configuration** |
| Compensation | `employee_compensation` as-of the period | **Effective-dated configuration** |
| Statutory profile (PF/ESI/PT/tax regime) | `employee_statutory` as-of the period (planned) | **Effective-dated configuration** |
| Bank account | `employee_bank` as-of the period (planned) | **Effective-dated configuration** |
| Statutory rates (PF %, ESI %, PT slabs, TDS slabs) | `statutory_master` as-of the period (planned, ADR-0011) | **Effective-dated configuration**, jurisdiction-keyed not employee-keyed |
| Attendance summary for the period | `attendance_day` (planned) | **Transaction data** (derived, but itself a source for Payroll — read, never re-derived by Payroll) |
| Leave / LOP for the period | `leave_ledger` + `attendance_day` (planned) | **Transaction data** |
| Arrears / loans / one-off adjustments | `arrears`, `loan`(+schedule) (planned) | **Transaction data** |
| Everything above, copied at computation time | `pay_run_input_snapshot` (planned) | **Snapshotted payroll data** — the boundary |
| Computed payslip lines | `payslip`(+line) (planned) | **Derived data**, immutable once the run finalises |

### 8.2 The snapshot boundary, stated precisely

**Payroll stops reading mutable/effective-dated source data the moment `pay_run` enters its
SNAPSHOT INPUTS step** (ADR-0005). From that instant, every subsequent computation step (COMPUTE,
VALIDATE, VARIANCE, REVIEW, FINALISE) reads **only** `pay_run_input_snapshot` — never Employee's
live tables, never Attendance's live `attendance_day` rows, never `statutory_master` directly. A
compensation correction made an hour after a run's inputs are snapshotted must not silently alter
a figure that run already computed — the snapshot is what computation actually read, and it is
preserved permanently alongside the payslip it produced. This is not a performance optimization;
it is a correctness and legal-defensibility requirement (a payslip must be reproducible from its
own snapshot, forever, independent of what the source tables look like today).

### 8.3 The pipeline (ADR-0005, restated as the target architecture)

```text
CREATE RUN      — lock the period, snapshot the employee list (who is in scope)
SNAPSHOT INPUTS — copy every row in the table above into pay_run_input_snapshot, immutable
COMPUTE         — pure function of the snapshot, parallel Celery batches, no shared mutable
                  state; every payslip line stores {formula, inputs, intermediate, result}
VALIDATE        — automated statutory/sanity checks
VARIANCE        — comparison against the previous run (flag anomalies before a human sees them)
REVIEW          — mandatory human approval gate; cannot be skipped, cannot be automated away
FINALISE        — write payslips, mark the run immutable, emit PayRunFinalised via the outbox
```

**A finalised run's records are frozen.** Any subsequent error is corrected with an arrears/
adjustment component in a **later** run — never by editing a finalised run's records. This is
Appendix A's invariant #5 in `00_HRMS_SYSTEM_ARCHITECTURE.md`, restated here as the specific
mechanical consequence for Payroll's own design.

### 8.4 What Payroll must never do, stated as a hard boundary

Payroll never writes back into Employee, Attendance, or Leave history. Corrections flow forward
as arrears in a later run. This is not a stylistic preference — it is what makes a payslip
reproducible and legally defensible after the fact.

### 8.5 Prerequisites, restated as a checklist

1. `employee_statutory`/`employee_bank` must exist (E-07/E-08).
2. The terminate fix (Section 18, CRITICAL-1) must be in place, or Payroll's compensation-as-of
   read will be wrong for anyone inside a post-termination gap.
3. Inter-entity transfer must stop being an in-place `legal_entity_id` mutation, or Payroll's
   employer-of-record history for a spell is corrupted by any correction made after the fact.
4. `statutory_master` must exist and be seeded, reviewed, and signed off by a compliance
   consultant before any real payroll run — this is explicitly **not** an engineering-only
   deliverable (`docs/product/23_Non_Functional_Requirements_and_Compliance.md §5`).
5. The payroll golden-dataset test suite (≥200 employee-months, ~20 documented scenario
   categories, verified by a compliance consultant, not the developer) is a release gate, not an
   optional nicety (`docs/product/15_Testing_Strategy.md §3`).

---

## Section 9 — Statutory Architecture

**Status: design-level analysis only, plus a fully-specified implementation plan already exists**
at `docs/modules/employee/21_EMPLOYEE_STATUTORY_IMPLEMENTATION_PLAN.md` — this section summarizes
its ownership resolution rather than re-deriving it.

### 9.1 Employee statutory profile vs. Legal Entity — the ownership split, already correctly
resolved by existing code + docs, not invented here

- **Legal Entity** (built, live) owns the **employer's own** statutory registration numbers — one
  PF establishment code, one ESI code, one TAN, one GSTIN per legal entity. This is
  employer-level, not per-employee, and already correctly separate from anything Employee owns.
- **`employee_statutory`** (planned E-07) owns the **individual employee's own** enrollment data
  within those employer registrations — their own `pf_number` (their account under the employer's
  PF establishment), their own `esi_ip_number`, their elected `tax_regime`, applicability flags
  (`is_pf_applicable`, `is_esi_applicable`, `is_lwf_applicable`), `pt_state_code`,
  `is_director`/`is_international_worker` (both affect applicability rules).
- **UAN** stays on `employee.uan_number` (already live), **not** duplicated onto
  `employee_statutory` — this is a real conflict between two source documents (one lists `uan` in
  `employee_statutory`'s field inventory, the other's own concrete DDL and the live schema agree
  it belongs on `employee` alone) already resolved in the E-07 plan in favor of the live schema.
  **RECOMMENDATION, restated:** do not reopen this — a second UAN column would create exactly the
  drift risk the resolution was written to prevent.

### 9.2 What belongs to Employee vs. what belongs to Payroll

Employee owns the **identifiers and applicability flags** — the facts about *this employee*.
Payroll owns the **rate tables and computation** — PF/ESI/PT/TDS percentages, slabs, ceilings, and
the actual monthly contribution arithmetic (`statutory_master`, ADR-0011: rates are effective-
dated data, never code). `employee_statutory` describes one employee's applicability/identifiers
within the rules Payroll's `statutory_master` defines; it does not itself compute anything.

### 9.3 The one Payroll-motivated rule Employee must enforce, because Employee owns the only
write path

The **tax-regime once-per-financial-year switch rule** (FR-PAY-006) belongs conceptually to
Payroll but the *data* lives on Employee's table — already correctly identified in the E-07 plan
as a validation Employee's own service layer must enforce, since Employee is the only module with
a write path to `employee_statutory.tax_regime`.

### 9.4 What is genuinely OPEN, not invented here

- The exact `EMPLOYEE.VIEW_STATUTORY` permission-code literal name (recommended, not confirmed).
- Whether `pf_number` carries forward on rehire to the same legal entity, or is entered fresh
  every time — no source document states this.
- The fiscal-year boundary for the once-per-FY switch rule (India-centric April–March assumed,
  not confirmed, itself downstream of the unconfirmed "India-only payroll" scoping question).

---

## Section 10 — Banking

**Status: design-level analysis only, plus the same E-07/E-08 plan family covers this.**

**Ownership:** `employee_bank` (planned E-08) — `account_holder_name`, `account_number_enc`,
`bank_name`, `ifsc`, `branch_name`, `payment_mode` (BANK/CASH/CHEQUE/UPI), `is_primary`,
`verification_status`, `penny_drop_reference`. Effective-dated (an employee can change their
salary account over a career; the old account remains historically queryable for reconciliation).

**Relationship to Payroll:** Payroll reads the employee's bank account **as-of the pay period**
(same effective-dating discipline as compensation) to generate `bank_advice` output files — it
does not own or duplicate the account data.

**Relationship to Attendance/Employment/Leave:** none directly — Banking is a pure Payroll-input
leaf, no other module reads it.

**Sensitive-data classification (DOC, `docs/product/19_RBAC_and_Permission_Matrix.md §6`):**
`RESTRICTED`, "the strictest permission gating in the aggregate" per the Employee architecture-
decisions doc's own framing (item F of the original brief). Masking format documented:
`******7890`.

**Access requirements — the gap this document must state plainly:** the recommended dedicated
`EMPLOYEE.VIEW_BANKING` permission code does not exist in the seeded catalogue (§11). Encryption
for `account_number_enc` does not exist in code (§14, §18 MEDIUM-13). Read-path access logging
via `sensitive_access_log` does not exist (§18 MEDIUM-12). **All three must be resolved — or
consciously, explicitly deferred with a stated compliance rationale — before E-08 ships real
account numbers into this column**, not discovered after the fact.

---

## Section 11 — RBAC

**FACT — what's actually seeded and enforced today, module by module:**

| Module | Permission shape | Granularity actually enforced |
|---|---|---|
| Organisation | One `ORG.<ENTITY>.MANAGE` per entity (7 codes), view+manage bundled | Module-level only — no field- or resource-instance-level distinction |
| Employee | 9 distinct action codes (`.VIEW_ALL`, `.CREATE`, `.UPDATE`, `.DEACTIVATE`, `.TERMINATE`, `.TRANSFER`, `.PROMOTE`, `.VIEW_COMPENSATION`, `.UPDATE_COMPENSATION`) + `.VIEW` from identity | Resource-action-level for most of Employee; **field-sensitive only for Compensation** (whole sub-resource gated, "absent not disabled") |
| Identity | 3 codes (`SETTINGS.USER.MANAGE`, `SETTINGS.ROLE.MANAGE`, `EMPLOYEE.VIEW`) | Module-level |

**None of this is module/resource/field-sensitive uniformly** — it is module-level for
Organisation, resource-action-level for most of Employee, and field-sensitive for exactly one
sub-resource (Compensation). This unevenness is not itself wrong (Organisation's low-stakes master
data genuinely doesn't need finer granularity yet) but it means **the field-sensitivity pattern
Compensation establishes has not yet been generalized** to Statutory/Banking/Attendance/Payroll,
and there is no shared mechanism to reuse — each future module will need to hand-implement the
same "gate the whole sub-resource, not individual fields" pattern Compensation already proves out.

**Over-granting risks, specific and confirmed:**

1. **Personal contact fields leak past their documented classification** — `personal_email`/
   `personal_mobile` are `SENSITIVE`-classified in `docs/product/19 §6`, meant to be gated by
   `EMPLOYEE.VIEW_PERSONAL_CONTACT`. That code doesn't exist in the seeded catalogue at all, and
   the fields are returned unconditionally on every `EmployeeRead`. **This is a live over-grant
   today**, not a future risk.
2. **Data scope is entirely unenforced** — any role with `EMPLOYEE.VIEW` sees every employee in
   the tenant, not just their own reports. The `VIEW` vs `VIEW_ALL` distinction the catalogue
   design claims separates "Reporting Manager" from "HR Manager" provides **no actual protection**
   today, because `require_permission()` always returns `COMPANY` scope. **This is the single
   largest RBAC over-granting risk in the system**, and it will get materially worse the moment
   Attendance/Leave/Payroll ship, because those modules' documented permission catalogues
   (`docs/product/19 §3.2–3.4`) lean on data-scope even more heavily than Employee's does (e.g.
   `PAYROLL.PAYSLIP.VIEW_ALL` is meant to be a narrow, elevated grant distinct from
   `PAYROLL.PAYSLIP.VIEW` — with scope unenforced, that distinction is currently theoretical for
   any module that ships against the current `core/rbac` implementation).
3. **No explicit-DENY capability exists in the database** — `role_permission` has no `effect`
   column. If a future requirement needs "grant X except for this one sub-scope," there is no
   mechanism to express it today.
4. **Salary/banking/statutory permission codes for the modules that need them most strictly don't
   exist yet** — `EMPLOYEE.VIEW_STATUTORY`/`.VIEW_BANKING` are recommended in the E-07 plan, not
   seeded. Until E-07/E-08 ship, this is dormant risk, not live — but the mechanism gap (no
   data-scope enforcement, no field masking beyond Compensation) is exactly what those two
   permission codes will need to lean on the moment they're seeded, and that mechanism doesn't
   exist yet either.

**RECOMMENDATION, not a decision this document locks:** treat data-scope enforcement as a
prerequisite for **any** module beyond Employee's current build — specifically, before Attendance/
Leave/Payroll ship a single `VIEW` permission whose catalogue design assumes `SELF`/`REPORTEES`
scoping is real. Building those modules against the current stub risks shipping the same
over-grant pattern at a much higher blast radius (payslips, not just contact numbers).

---

## Section 12 — Security

**RLS (FACT):** every tenant table `ENABLE`+`FORCE`d, single `tenant_isolation` policy,
re-asserted idempotently per migration. Backstopped by explicit `company_id` filtering in every
repository method (belt-and-suspenders, not RLS-alone).

**Tenant predicates and cross-tenant references (FACT):** cross-tenant access always returns
`404`, never `403` — existence is never disclosed. Confirmed consistent everywhere tested.

**Mass assignment (FACT):** `extra="forbid"` on every write schema, positively tested.

**Optimistic concurrency (FACT):** `version` + `If-Match` on every mutable-row write; GiST
exclusion as a second line of defence on effective-dated inserts.

**Audit logging (FACT + gap):** write-path complete and consistent. Read-path
(`sensitive_access_log`) does not exist — the single largest audit gap, and one that widens with
every new RESTRICTED table (Statutory, Banking) that ships without it.

**Sensitive data / PII / financial data (FACT + gap, restated from Section 10):** `_enc`-suffixed
columns (`pan_number_enc`, `aadhaar_number_enc`, planned `account_number_enc`) are **plain,
unencrypted string columns**. The naming convention implies a guarantee the code does not provide.
This must be resolved before any of E-02 (PAN/Aadhaar write path), E-07 (statutory), or E-08
(banking) ship real data into these columns.

**Security invariants every future module must follow, derived from what's actually enforced
today (not aspirational):**

1. Every tenant-owned table gets RLS `ENABLE`+`FORCE`, re-asserted inline in its own migration —
   never assumed inherited from an init-script loop or a standalone SQL file.
2. Every repository query filters `company_id` explicitly, even though RLS is also present —
   defence in depth, not either/or.
3. Cross-tenant access is always `404`.
4. Every write schema uses `extra="forbid"`.
5. Every mutable-row write is guarded by `version`/`If-Match`.
6. RESTRICTED-classified fields must be **omitted**, never returned as `null`, when the caller
   lacks the gating permission — matching Compensation's proven pattern, not inventing a new one.
7. Any new `_enc`-suffixed column must have a real encryption mechanism applied before real data
   is written to it — the naming convention alone is not a control.
8. Every state-changing write calls `AuditService.record()` as its last step, same transaction.

---

## Section 13 — API Architecture

**FACT vs. `docs/product/09_API_Standards.md`, restated from `00_HRMS_SYSTEM_ARCHITECTURE.md
§20` at a glance:**

| Pattern | Status |
|---|---|
| `/v1` + plural kebab-case, one-level nesting, verb sub-resources | Implemented |
| `DataEnvelope`/`ListEnvelope`/`ErrorEnvelope` | Implemented |
| `If-Match` optimistic concurrency | Implemented |
| `?as_of=` on effective-dated resources | Implemented |
| Cross-tenant → 404 | Implemented consistently |
| Field masking (omit, not null) | Implemented for Compensation only |
| Pagination | **Not implemented anywhere** |
| `Idempotency-Key` | **Not implemented anywhere** |
| Rate limiting | Registration endpoint only |
| CI-enforced "every route has an explicit permission dependency" check | **Not found** — documented, not built |

**Deviations already present, worth stating as the canonical shape a future module should
replicate or deliberately not replicate:**
- Hire is 2+ HTTP calls, not one nested create — a deliberate, documented deviation from the
  original module plan, kept for API purity. Future modules with a similarly multi-table "create"
  concept (e.g. a Payroll run's CREATE→SNAPSHOT→COMPUTE steps) should follow this same "separate
  calls, service-layer orchestration where atomicity is genuinely required" pattern rather than
  trying to force a single mega-endpoint.
- Effective-dated sub-resources are insert-only (`POST`, never `PATCH`), even where an earlier
  planning document literally named `PATCH` as the verb (the Statutory plan explicitly flags and
  overrides this for exactly this reason) — **canonical rule for every future effective-dated
  resource: `POST` only, `PATCH`/`DELETE` never exposed on an individual historical row.**

---

## Section 14 — Database Architecture

**FACT, canonical rules for future migrations, distilled from 19 migrations that all follow the
same shape without exception:**

1. UUID PKs, `company_id` + index on every tenant table.
2. `created_at`/`updated_at`/`deleted_at`/`version` on every mutable table (the many thin stub
   columns inherited from `001_init_schema.sql` are the historical exception, being closed out
   migration by migration, not the target shape).
3. Money = `BIGINT` minor units + a `currency` column — never `NUMERIC`, never a float.
4. Effective-dated tables get a GiST exclusion constraint in the **same** migration that creates
   them (not a follow-up).
5. RLS `ENABLE`+`FORCE`+policy re-asserted **inline, idempotently, in every migration that touches
   an RLS-protected table** — `DROP POLICY IF EXISTS` + `CREATE POLICY`, never assumed inherited.
   **Do not reference `scripts/sql/002_row_level_security.sql`/`003_effective_dating_constraints
   .sql` — both are dead files, never invoked by Alembic.**
6. `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` to expand existing tables — never drop-and-recreate
   a live table (the two documented exceptions, `branch.state`→`state_code` and
   `grade.rank`→`level`, were both explicit renames of columns confirmed to hold no real data at
   the time, not a general license to rename freely).
7. FKs use `ON DELETE SET NULL` for optional/soft relationships (most Assignment FKs) or
   `ON DELETE RESTRICT` for required ownership relationships (Company→LegalEntity, etc.) — never
   silently default to `CASCADE`.
8. JSONB reserved for genuinely tenant-defined, schema-less data (`custom_fields`) — never for
   core business attributes that have a known, fixed shape.
9. Soft delete (`deleted_at`) for business records — no hard deletes. Deactivation
   (`is_active = false`) is a separate, distinct concept from soft-delete, used for reversible
   lifecycle states.

**Column-name drift confirmed between `docs/product/08` and the live schema** (five instances —
`user_company.is_default`/`is_primary`, `permission.module`/`domain`, missing
`role_permission.effect`, missing `user_role` data-scope columns, `employee.custom_fields`/
`custom_fields_json` disagreement between the two DB docs themselves) — a documentation
correction, not a code defect; listed in full in `00_HRMS_SYSTEM_ARCHITECTURE.md §7`.

---

## Section 15 — Background Processing

**Where Celery/background jobs will genuinely be required, by module:**

| Module | Job | Idempotency requirement |
|---|---|---|
| Attendance | Debounced per-employee/date recompute after punch ingestion | Must collapse multiple triggers within the 60s window into one recompute; must be safe to re-run against the same punch set without double-counting |
| Attendance | Absent-marking (company-timezone-scheduled, e.g. 02:00 local) | Must not re-mark an already-resolved day; company-timezone-aware scheduling, not one global cron fire (ADR-0010) |
| Leave | Monthly/periodic accrual | Must be safe to re-run for the same employee/period without double-crediting — this is explicitly named as "rule 2" in the documented task-design rules (`docs/product/11_Background_Job_Architecture.md §2`) |
| Payroll | The full CREATE→SNAPSHOT→COMPUTE→VALIDATE→VARIANCE→REVIEW→FINALISE pipeline | Every step must be a resumable checkpoint (ADR-0005) — a crash mid-run resumes from the last checkpoint, never re-runs from scratch, and a partially-computed run must never be visible as if it were final |
| Notifications | Fan-out dispatch across channels on domain events | At-least-once delivery via the outbox pattern (ADR-0012) — consumers must be idempotent because outbox relay can redeliver after a crash mid-relay |
| Imports (bulk employee, etc.) | Dry-run validation + all-or-nothing commit | The whole batch either commits or doesn't — no partial-import state should ever be visible |
| Reports | Large/async export generation | Idempotent re-generation; should not double-charge any rate limit or quota on retry |

**FACT, restated:** none of this exists in code today beyond one sample Celery task. Every row in
the table above is DOC, synthesized from ADR-0005/0007/0012/0014 and `docs/product/
11_Background_Job_Architecture.md`, not invented for this review.

---

## Section 16 — Frontend Architecture

**FACT — what exists:** Organisation-only pages, each following list + `[id]` detail/edit + create
-dialog. Shared primitives: `apiClient`, `useApiResource` (GET-only), `AuthProvider`, and basic UI
atoms (`PageHeader`/`FormField`/`LoadingState`/`ErrorState`/`EmptyState`/`Card`/`Button`/`Badge`/
`Dialog`).

**Missing reusable primitives, and which should become shared infrastructure before Employee UI /
Attendance UI / Payroll UI (not built here, per this review's scope):**

| Primitive | Needed by | Priority |
|---|---|---|
| `PermissionGate`/`usePermission` | Every future module's UI — the "absent, not disabled" gating principle multiple design docs treat as mandatory is impossible to implement correctly without it. **`UserProfile.permissions` is already fetched into `AuthProvider`'s state and never read anywhere** — the data this primitive needs is one line away from being usable | **Highest** — build before E-09, not folded silently into it |
| Paginated `DataTable` | Employee Directory (hundreds–thousands of rows), Attendance matrix, Payslip lists, any report | **High** — but blocked on the backend actually sending pagination metadata first (§13) |
| As-of-date control | Employee 360° Job/Compensation tabs, any Attendance-day lookup, any Payroll-period view | High |
| Effective-dated history / Timeline component | Employee's Job/Compensation tabs (assignment/compensation history), any future module with the same pattern | High |
| Money display (minor units → formatted currency) | Compensation, Payroll, Statutory-adjacent fields | High — cheap to build, high blast radius if done inconsistently per-screen |
| Sensitive-field masking component | Statutory/Banking (once built), PAN/Aadhaar (once E-02 ships) | Medium-High |
| Audit viewer | Any `EMPLOYEE.VIEW_AUDIT`-gated screen, eventually a platform-wide audit search | Medium |
| Status badges | Every module — cheap, low-risk, no reason to defer | Low-Medium |
| Confirmation dialogs | Already partially covered by the existing `Dialog` primitive used for deactivate/reactivate flows | Low — mostly reuse, not new build |
| Form system beyond individual `FormField`s | Multi-step wizards (Add-employee, future onboarding), needed once E-09's 4-step wizard is built | Medium |
| Date-range controls | Attendance/Leave/Payroll period pickers | Medium |

**RECOMMENDATION, not a build instruction:** `PermissionGate`/`usePermission` and money display are
the two cheapest, highest-leverage primitives to build first — both are small, neither depends on
a backend change, and both prevent the same mistake (an inconsistent, per-screen reimplementation)
from being made four separate times across Employee/Attendance/Leave/Payroll UI.

---

## Section 17 — Cross-Module Dependency Graph

**Derived from the actual repository and documents, not the generic textbook shape:**

```text
core (db, tenancy, rbac, audit, auth, errors, observability, config)
  ▲  imported by everything
  │
identity ──► organisation ◄── employee
                  │                │
                  │ (FK targets:   │ (employee.service is the ONLY import
                  │  legal_entity, │  surface for every module below)
                  │  branch,       │
                  │  department,   │
                  │  designation,  │
                  │  grade, shift) │
                  ▼                ▼
         attendance (planned) ◄────┤
              │    ▲               │
              │    │ (Attendance   │
              │    │  reads Leave's│
              │    │  approved-    │
              │    │  application  │
              │    │  status,      │
              │    │  per-day)     │
              ▼    │               │
         leave (planned) ◄─────────┤
              │  (Leave reads      │
              │   Attendance's     │
              │   summary at       │
              │   period-close,    │
              │   batch-oriented — │
              │   see §7.5 for why │
              │   this is not a    │
              │   live cycle)      │
              ▼                    │
        payroll (planned) ◄────────┴─── organisation.service (legal entity statutory codes)
              │
              ▼
        ESS / Reports (planned) ◄── every module's service.py, read-mostly

notification / workflow-approval (planned) — consumed by Leave, Compensation-revision,
    Exit, etc. via domain events (outbox), never a direct synchronous call
```

**Hard dependencies:** Employee → Organisation (FK existence checks, cannot function without it).
Attendance/Leave/Payroll → Employee (as-of employment/assignment/compensation — cannot function
without `employee.service`'s public contract). Payroll → Statutory/Banking (cannot compute
correctly without them, per Section 8).

**Soft dependencies:** Attendance ↔ Leave (per-day read one direction, period-summary read the
other — real, but not simultaneous, not a live cycle per §7.5). ESS/Reports → everything (reads
only, degrades gracefully if a module isn't built yet — an ESS screen for a module that doesn't
exist should render "not yet available," not error).

**Circular dependencies:** none found in the built graph. The one place a naive implementation
could introduce a real cycle is Attendance/Leave — resolved architecturally in §7.5 by keeping the
two read directions asymmetric (per-day vs. batch-at-close), not by inventing a third module to
mediate.

**Modules that should expose a service API for others to consume, beyond what's already built:**
Attendance (`get_attendance_summary_for_period`, mirroring `get_assignment_as_of`'s shape),
Leave (`get_lop_days_for_period`), consistent with the established pattern (Section 5) rather than
each module inventing its own contract shape.

---

## Section 18 — Architectural Risks

Ranked CRITICAL → LOW. Each risk states what an expensive rewrite would look like if left
unaddressed, not merely "this is untidy."

### CRITICAL

**C-1. Terminate does not close assignment/compensation.** `EmploymentService.
terminate_employment` (`apps/api/src/hrms/modules/employee/service.py:463-503`) sets only
`employment.status`/`last_working_day`; `employee_assignment`/`employee_compensation` stay open
through the gap. **If Attendance/Payroll are built against `get_assignment_as_of`/
`get_compensation_as_of` before this is fixed, both modules will inherit the wrong assumption
into their own logic**, and the fix would then require touching Attendance/Payroll code as well as
Employee's — this is the one risk in this document where "fix it now, in one module, additively"
is cheap, and "discover it after two more modules are built on top of it" is expensive. See §36
item 1 of `00_HRMS_SYSTEM_ARCHITECTURE.md` for the full evidence trail.

### HIGH

**H-1. RBAC data-scope is a complete no-op** (§11). Every future module's documented permission
catalogue leans on `SELF`/`REPORTEES` scoping (Payroll's `VIEW` vs `VIEW_ALL` distinction most of
all). Building Attendance/Leave/Payroll's permission checks against the current stub means every
one of them ships with the same over-grant, at increasing financial/privacy stakes. **Rewriting
data-scope enforcement after three more modules depend on the stub is a much larger, more
coordinated change than fixing it once, now, in `core/rbac`.**

**H-2. No encryption on `_enc`-suffixed columns** (§10, §12). E-02/E-07/E-08 will each write real
PAN/Aadhaar/bank-account data into columns that provide no actual encryption. Retrofitting
encryption onto columns that already hold real data (key rotation, re-encryption migration,
downtime coordination) is materially more expensive than applying it before the first real row is
written.

**H-3. Inter-entity transfer is an in-place mutation** (§4, §8.5). If Payroll is built assuming
`employment.legal_entity_id` history is trustworthy, and this is fixed later, every payroll-history
query that trusted the old (wrong) assumption needs re-validation against real customer data —
expensive specifically because it's a *silent* correctness issue, not one that throws an error.

**H-4. Holiday calendar / week-off has no foundation** (§6.7). Attendance's status resolution is
structurally incomplete without it — building punch ingestion first and discovering this gap
second means Attendance ships an incomplete status engine, then needs a second pass once
holiday/week-off exists, rather than one coherent build.

**H-5. `sensitive_access_log` doesn't exist, and every new RESTRICTED table (Statutory, Banking)
widens the gap** (§9, §10, §12). Retrofitting read-path audit logging after Statutory/Banking ship
means going back and adding it to endpoints already in production use, plus a compliance
conversation about the gap period — cheaper to build once, before E-07/E-08, than to retrofit
across two modules plus whatever ships after them.

### MEDIUM

**M-1. Seat-limit TOCTOU race** (unchanged from `00_HRMS_SYSTEM_ARCHITECTURE.md §36` item 10) —
low blast radius today, worth a DB-level constraint before bulk import (E-09) increases concurrent
create volume.

**M-2. No CI-enforced per-module import contract** — convention-only cross-module boundary
discipline erodes silently as more modules are added by more contributors (or more AI-assisted
sessions) over time; cheap to add a per-module `.importlinter` contract now, more valuable the
more modules exist.

**M-3. No idempotency-key mechanism** — becomes materially more urgent the moment Attendance's
punch-ingestion path exists (documented as required specifically for money/attendance/approval
POSTs) — building Attendance without it first, then retrofitting, risks a period where duplicate
punches are a live production risk.

**M-4. Background jobs / outbox pattern entirely prospective** — fine today; becomes urgent the
moment any module needs its first genuinely-async side effect (Leave accrual, Attendance
recompute, Payroll's own pipeline) — better to design the outbox table and task-idempotency
convention once, deliberately, than to have three different modules each invent a slightly
different "how do I fire an async side effect safely" answer.

**M-5. Frontend has no `PermissionGate`/paginated `DataTable`/as-of control/Timeline** (§16) —
building E-09 (Employee Directory) without these first means either shipping without the "absent
not disabled" principle the design docs treat as mandatory, or building the primitives
mid-E-09 under time pressure rather than as clean, reusable infrastructure — cheaper to build
once, deliberately, ahead of the module that first needs it.

### LOW

Column-name drift between docs and schema; stale code comments referencing "Employee doesn't
exist yet"; `is_rehire` derived rather than stored; CHECK-vs-Pydantic-Literal inconsistency
between `employment.status` and `employee_assignment.change_type`. None of these compound into a
rewrite risk on their own — cleanup items, not architecture risks.

---

## Section 19 — Decisions Required

Only genuine product/architecture decisions — not build tasks, not things this document or an
existing plan document has already resolved with a stated rationale.

### D-1. RBAC data-scope enforcement — build now, or defer past Attendance/Leave/Payroll?

**Why it matters:** every future module's documented permission catalogue assumes `SELF`/
`REPORTEES` scoping is real (§11, §18 H-1). Deferring this compounds the retrofit cost with every
module built against the stub.

**Options:** (1) implement real data-scope enforcement in `core/rbac` now, before any new module
ships a permission check against it; (2) continue shipping modules with the current always-
`COMPANY`-scope stub and retrofit later.

**Recommended:** Option 1 — not because this document can order it, but because the cost curve is
asymmetric and gets worse with every module built on the stub.

**Impact if deferred:** every subsequent module (Attendance, Leave, Payroll, ESS) ships an
over-grant identical to Employee's current one, at progressively higher stakes (payslip visibility,
not just contact numbers).

### D-2. Encryption for `_enc`-suffixed columns — mechanism and timing

**Why it matters:** E-02/E-07/E-08 are the next scheduled slices and will each write real
sensitive data into currently-unencrypted columns.

**Options:** (1) implement column-level encryption (SQLAlchemy `TypeDecorator` + KMS) before
E-02/E-07/E-08 ship; (2) ship without it and document the gap as an accepted, time-boxed risk with
a committed remediation date.

**Recommended:** Option 1 for any column that will hold real PAN/Aadhaar/bank data before go-live
— this is closer to a compliance requirement than an engineering nicety given the DPDP framing
throughout the product docs.

**Impact if deferred:** real sensitive data lands in plaintext columns; remediation later requires
a re-encryption migration against live customer data, plus a disclosure conversation.

### D-3. Holiday calendar / week-off ownership and sequencing

**Why it matters:** Attendance's status resolution is structurally incomplete without it (§6.7,
§18 H-4).

**Options:** (1) a small Organisation follow-up slice (extends `branch`/`holiday_calendar`); (2)
Attendance's own first sub-slice, before punch ingestion.

**Recommended:** whichever is chosen, decide it explicitly before Attendance's first line of code
— this document takes no position on which team/slice should own it, only that it cannot be
silently deferred past Attendance's status-resolution logic.

**Impact if deferred:** Attendance ships a status engine that cannot distinguish a week-off from
an absence, then needs a second pass.

### D-4. Employment-legal-entity-vs-assignment-branch invariant

**Why it matters:** no constraint enforces that `employee_assignment.branch.legal_entity_id`
matches the employee's current `employment.legal_entity_id` (§3, §18). Payroll's employer-of-record
and Attendance's site can silently disagree.

**Options:** (1) add an application-layer (or DB trigger-level) invariant that rejects an
assignment whose branch belongs to a different legal entity than the current employment; (2)
explicitly permit "assigned to work from a branch under a different legal entity" as a real
business scenario and design around it deliberately.

**Recommended:** decide explicitly — this document does not have enough product context to pick a
side, and picking wrong silently would corrupt Payroll's employer-of-record logic in a way that's
hard to detect after the fact.

**Impact if deferred:** Payroll built on the current unconstrained state risks computing statutory
contributions against the wrong legal entity for any employee whose branch and employment
disagree.

### D-5. Whether `pf_number` carries forward on rehire

**Why it matters:** E-07's own plan explicitly leaves this open — implementing without product
input risks a UX assumption (auto-carry vs. fresh entry) that may need reversal later.

**Options:** (1) auto-carry when rejoining the same legal entity; (2) always enter fresh.

**Recommended:** no default invented here, per the E-07 plan's own discipline.

**Impact if deferred:** low — this can be decided at E-07 implementation time without blocking
anything else.

### D-6. Fiscal-year boundary for the tax-regime-switch rule, and the India-only-payroll scoping
question it depends on

**Why it matters:** downstream of a still-unconfirmed product scoping question
(`docs/product/26_Risk_Register_Open_Questions_and_Change_Control.md` Q1/A1) — deciding the FY
boundary without first confirming India-only scoping risks hard-coding an assumption that breaks
if multi-country payroll is ever required.

**Options:** (1) confirm India-only scoping first, then lock April–March; (2) design the FY
boundary as company-configurable from day one, deferring the India-specific default.

**Recommended:** confirm the scoping question first — this is a product decision this document
cannot make.

**Impact if deferred:** low near-term (E-07 can default to April–March and flag it as an
assumption, per its own plan); becomes expensive only if multi-country payroll is later added
without having designed for configurability.

---

## Section 20 — Architectural Invariants

Only rules actually supported by the running architecture — not aspirational ones.

1. **Every tenant-owned table has `company_id` + RLS** (`ENABLE`+`FORCE`+`tenant_isolation`
   policy), re-asserted inline in whichever migration touches it.
2. **No hard deletes for business records** — `deleted_at` + `is_active` (where applicable);
   deactivation is reversible, deletion is not attempted.
3. **Historical data is never overwritten.** Effective-dated writes close the current row's
   `effective_to` and insert a new row — business columns on a closed row are never touched again.
4. **Effective-dated records use structural (GiST) overlap prevention**, not merely an
   application-layer check.
5. **Money is `BIGINT` minor units + a `currency` column**, never a float, never computed
   client-side.
6. **A finalised payroll run is immutable; corrections are forward-only arrears in a later run.**
7. **Cross-module access occurs through `service.py` only** — never another module's `.repository`
   or `.models`.
8. **Every state-changing write is audited**, same transaction, via `AuditService.record()`.
9. **RESTRICTED-classified fields require explicit permission and are omitted (never `null`) when
   absent from the caller's grant** — Compensation is the one resource that already proves this
   pattern; every future RESTRICTED resource should copy it exactly.
10. **`employee.id`/`employee_code` are never reissued**, including across a rehire — the
    structural fact every downstream module's identity handling depends on.
11. **Effective-dated Employee child tables key on `employee_id`, never `employment_id`.**
12. **Statutory rates are effective-dated data, never a code constant** (once Payroll's
    `statutory_master` exists).
13. **Cross-tenant access is always `404`, never `403`.**

---

## Section 21 — Implementation Roadmap

**This section recommends the sequence that minimizes rewrites, not a re-statement of the
existing roadmap document.** Where it agrees with the existing plan, that is because the existing
plan is already correctly sequenced for the reasons stated; where this section adds an item, it is
called out explicitly.

| Order | Module/Task | Dependencies | Required decisions | Required shared infra | Risk if skipped/reordered |
|---|---|---|---|---|---|
| 1 | **Fix terminate** (close assignment+compensation) | none — additive, no schema change | none | none | CRITICAL — see §18 C-1 |
| 2 | **RBAC data-scope enforcement** (D-1) | none | D-1 | none | HIGH — compounds with every module built after it |
| 3 | **E-07 Statutory** | Employee (built), terminate fix (#1) | permission-code name (recommended, not blocking) | encryption mechanism (D-2) should land alongside, not after | Payroll-blocking if deferred further |
| 4 | **E-08 Banking** (+ docs/dependents/education/experience/skills) | E-07 pattern reuse | encryption mechanism (D-2), if not already done at #3 | same | Payroll-blocking if deferred further |
| 5 | **Frontend primitives** (`PermissionGate`, `DataTable`, as-of control, Timeline, money display) | RBAC data-scope (#2), pagination on the backend | none | this **is** the shared infra | E-09 either ships without "absent not disabled" or builds these ad hoc under time pressure |
| 6 | **E-09 Employee UI** | #1–#5 | none new | #5 | Medium — mostly a UX-completeness risk, not a correctness one |
| 7 | **FR-ORG-014 retrofit** (Branch/Department/Designation/Grade deactivation blocking) | Employee (built) | none | none | Low-medium, isolated to Organisation |
| 8 | **Holiday calendar / week-off** (D-3) | Organisation or Attendance-owned, decide explicitly | D-3 | none | HIGH if skipped — Attendance ships an incomplete status engine |
| 9 | **`sensitive_access_log`** (E-10 core) | Statutory/Banking existing (so there's something worth logging reads of) | none | none | HIGH, compounds — see §18 H-5 |
| 10 | **Attendance** | #1, #8, stable `get_assignment_as_of` contract | D-4 (legal-entity/branch invariant) | idempotency-key mechanism (§18 M-3) | See §6 in full |
| 11 | **Leave** | #10 (for LOP inputs), employment as-of | D-5 not blocking | outbox/background-job convention (§18 M-4) | See §7 in full |
| 12 | **Payroll** | #3, #4, #1, #10, #11, D-4 resolved | D-4, D-6 | full Celery pipeline, `statutory_master` seeded + compliance-reviewed | See §8 in full — highest-risk module in the roadmap |
| 13 | **ESS / Reports** | every module above | none new | read-only service contracts per module (§17) | Low — degrades gracefully per module readiness |

**Where this differs from a naive "just follow the existing E-07→E-10→Attendance→Leave→Payroll
order":** it inserts RBAC data-scope enforcement (#2) and frontend primitives (#5) as explicit,
named steps rather than letting them happen implicitly inside E-09/E-10 — both are cross-cutting
infrastructure that gets more expensive to retrofit the more modules are built without them, and
neither is naturally "owned" by any single Employee sub-slice, which is exactly the kind of item
that falls through the cracks between slice-scoped implementation tasks.

---

## Section 22 — Final Readiness

| Module | Verdict | Conditions (if applicable) |
|---|---|---|
| **E-07 Statutory** | **READY WITH CONDITIONS** | Terminate fix (C-1) should land first (not strictly blocking for Statutory's own correctness, since Statutory doesn't yet interact with the assignment/compensation gap — but it is blocking for anything that reads Statutory alongside Compensation/Assignment as-of a date). Encryption mechanism (D-2) must land before real PAN-adjacent/statutory data is written. |
| **E-08 Banking** | **READY WITH CONDITIONS** | Same as E-07: encryption (D-2) is the hard condition. `EMPLOYEE.VIEW_BANKING` permission code should be seeded alongside, not after. |
| **E-09 Employee UI** | **READY WITH CONDITIONS** | Frontend primitives (§16, §21 #5) should exist first, specifically `PermissionGate`/`usePermission` and a paginated `DataTable` — building E-09 without them means either an incomplete UX or an ad hoc mid-slice build of infrastructure that should be deliberate. |
| **E-10 Security/Audit hardening** | **NOT READY to be treated as optional; READY to start as scoped work** | This is the slice most likely to get cut under schedule pressure (already flagged in the Employee architecture-decisions doc's own risk list) — given the confirmed live gaps (data-scope stub, no `sensitive_access_log`, personal-contact over-grant), it should not be deferred past E-07/E-08. |
| **Attendance** | **NOT READY** | Blocked on: terminate fix (C-1, CRITICAL), holiday calendar/week-off (D-3), and a decided legal-entity-for-a-working-day rule (D-4). None of these are large, but all three are structural preconditions, not polish. |
| **Leave** | **NOT READY** | Blocked on Attendance existing (for LOP inputs) and `leave_policy_assignment` needing to be built from scratch (Grade's own retraction of the simpler `leave_policy_id` model, §7.4). |
| **Payroll** | **NOT READY** | Blocked on Statutory + Banking existing, the terminate fix, inter-entity transfer no longer being an in-place mutation (H-3/D-4), `statutory_master` seeded and compliance-reviewed, and the golden-dataset test suite existing before any real run. This is expected — Payroll is correctly sequenced last in every version of the roadmap, including this one. |

**Overall verdict, restated from `00_HRMS_SYSTEM_ARCHITECTURE.md` Appendix F: YELLOW.** The
foundational patterns (identity/episode/placement/pay separation, effective-dating with structural
overlap prevention, RLS tenant isolation, optimistic concurrency, module-boundary discipline) are
sound and should not be redesigned. The path to Attendance/Leave/Payroll is clear and does **not**
require a major architectural rewrite — it requires closing a small, well-defined set of gaps
(terminate fix, RBAC data-scope, encryption, holiday/week-off, `sensitive_access_log`) before, not
after, the next three modules are built on top of the current foundation.

---

**This document does not silently override `docs/product/*`, `docs/adr/*`, or any
`docs/modules/*` plan document.** Every DISCREPANCY above names both sides and states whether a
product decision is required. Where this document recommends an implementation sequence that
differs from an existing plan document, it says so explicitly (Section 21) rather than treating
its own recommendation as already-decided. Locked decisions — the subset of this document's
content that future implementation tasks may treat as settled without re-litigating — are
collected separately in `docs/architecture/HRMS_ARCHITECTURE_DECISION_LOG.md`.
