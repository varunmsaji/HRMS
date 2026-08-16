# HRMS System Architecture

**Status:** Authoritative implementation-level architecture record. Investigation only — no
application code, migrations, or frontend code were written or modified to produce this document.

**Date:** 2026-08-15

**Method:** Cross-checked every claim in `docs/product/`, `docs/modules/`, `docs/adr/`, and
`docs/architecture/` against the live implementation — Alembic migrations, ORM models, services,
routers, permission catalogues, RLS policies, audit code, tenancy code, and the frontend. Where
documentation and implementation disagree, this document says so explicitly rather than picking a
side silently. This document supersedes nothing; it is a synthesis layer on top of
`docs/architecture/00_SYSTEM_ARCHITECTURE_AUDIT.md` (Employee/Organisation FACT audit, same date)
and the full `docs/product/`, `docs/adr/`, `docs/modules/` tree, extended to cover every module —
built and unbuilt — and every cross-cutting concern (RBAC, RLS, audit, API, DB, jobs, security,
testing, deployment).

**Legend:** **FACT** = observed directly in code, schema, or tests. **DOC** = stated in an
authoritative document, not yet built. **DISCREPANCY** = DOC and FACT disagree. **OPEN** =
genuinely unresolved — this document does not invent an answer. **RECOMMENDATION** = a proposed
next action, not a locked rule.

**Audience:** A future AI coding agent (or human) picking up this codebase cold. This document
should make a fresh architectural audit unnecessary for any of the ground it covers.

---

## 1. Purpose and Architectural Goals

This is a multi-tenant SaaS HRMS (India-first, per `docs/product/17_SRS_Phase1_Core_Modules.md`
and the statutory-domain framing throughout) covering Organisation setup, Employee lifecycle,
Attendance, Leave, Payroll, Recruitment, Onboarding/Exit, ESS, and supporting platform concerns
(RBAC, audit, workflow, notifications, AI). Built solo, AI-assisted (`docs/product/
25_Project_Plan_Estimation_and_Team.md` §1, §5 — see §38 below), which is why several
architecture decisions favor a small, disciplined, repeatable pattern over a general framework
(ADR-0001, ADR-0003, ADR-0008).

**Goals this architecture optimizes for, in order:**

1. **Tenant data isolation is structurally guaranteed, not merely coded correctly** — Row-Level
   Security as a backstop behind every application-layer predicate (ADR-0002), so a missing
   `WHERE company_id = ?` degrades to a test failure or an empty result, never a cross-tenant leak.
2. **Historical correctness for anything that changes over time and is read for a past date** —
   effective-dated child tables with structural (GiST) overlap prevention (ADR-0003), because
   Payroll must compute March's pay from March's data even if queried in June.
3. **Money is never wrong** — integer minor units, never floats (ADR-0006); payroll runs are
   snapshotted and immutable once finalised (ADR-0005); statutory rates are data, not code
   (ADR-0011).
4. **Module boundaries are enforced, not just documented** — one Python package per business
   domain, cross-module access only through `service.py`, enforced by `import-linter` in CI
   (ADR-0001, `docs/architecture/02_Module_Standard.md`).
5. **A repeatable pattern beats a generic framework** — the same effective-dating shape, the same
   soft-deactivate + optimistic-concurrency shape, the same permission-per-resource shape is
   copied module to module rather than abstracted into a config-driven engine (ADR-0003 B7,
   ADR-0008's workflow-engine exception aside).
6. **Every state change is audited; every RESTRICTED-tier read will be too**, once E-10 exists
   (§18, §19).

**This document's own operating rule**, carried forward from
`docs/architecture/00_SYSTEM_ARCHITECTURE_AUDIT.md`: do not rewrite effective-dating, RLS, module
layout, or the identity/employment split. Those are the foundation, not debt.

---

## 2. Current Implementation Baseline

### 2.1 What is actually implemented (FACT)

| Layer | Built |
|---|---|
| Backend modules | `modules/identity` (auth, users, roles/permissions engine), `modules/organisation` (Company, Legal Entity, Branch, Department, Designation, Grade, Shift), `modules/employee` (Employee identity, Employment, EmployeeAssignment incl. `shift_id`, EmployeeCompensation), `modules/health` |
| Core platform | `core/db` (async engine/session, RLS `SET LOCAL`), `core/tenancy` (ContextVar + middleware), `core/rbac` (permission check + a stub `DataScope`), `core/audit` (write-path `AuditService`), `core/auth` (JWT, Argon2id, refresh-token rotation), `core/errors` (exception hierarchy + envelope handlers), `core/observability` (structlog only), `core/config` (pydantic-settings), `core/celery_app.py` (Celery app instance, one sample task) |
| Database | 1 init script (`001_init_schema.sql`, 20 stub tables) + 18 additive Alembic migrations, head `20260814120000_employee_compensation` |
| Frontend | Next.js pages for every Organisation entity (Company, Legal Entities, Branches, Departments, Designations, Grades, Shifts, Setup, Dashboard) — **zero Employee UI** |
| Tests | Unit + integration for every shipped Organisation and Employee slice; one file under `tests/security/` (organisation-scoped: auth rejection, mass-assignment, IDOR path-param guard, password-not-in-audit) |
| Local dev | `docker-compose.yml` (Postgres 5433, Redis 6380, MinIO 9000/9001), `scripts/dev.sh` |

### 2.2 What is only documented (DOC, zero code)

Attendance, Leave, Payroll, Recruitment, Onboarding, Exit, Workflow/Approval engine,
Notification engine, AI module, Reporting module, Integration module. Employee sub-slices
E-02 (profile/address/emergency-contact/PAN write path), E-07 (Statutory), E-08
(Documents/Dependents/Education/Experience/Skills/Banking), E-09 (Directory UI, bulk
import/export, letters), E-10 (RBAC/audit hardening). `sensitive_access_log`, `outbox_event`,
`job_log`, `notification_log`, `import_batch` tables. Cloud deployment infrastructure
(Terraform/ECS) — `infra/` in this repo is Postgres init scripts only
(`docs/architecture/00_Repository_Audit.md` §2); no Terraform/AWS config exists in-repo as of
this audit.

### 2.3 What is partially implemented (FACT, narrower than DOC)

| Area | Documented shape | Actual shape |
|---|---|---|
| RBAC data scope | 8 levels: `SELF/REPORTEES/REPORTEE_TREE/DEPARTMENT/BRANCH/LEGAL_ENTITY/COMPANY/ALL_COMPANIES` (`docs/product/19_RBAC_and_Permission_Matrix.md §5`) | `core/rbac/types.py`: 3 levels — `COMPANY/TEAM/SELF`, no `REPORTEES` at all. `require_permission()` unconditionally returns `DataScope(level=COMPANY)` regardless of role. Every router binds the result to a discarded `_scope` variable. **Data-scope enforcement does not exist at runtime.** |
| Permission catalogue | ~250 codes (`docs/product/19 §3`) seeded via `docs/product/08 §14` | 14 codes total across `identity/permissions.py` (3) + `organisation/permissions.py` (8, one `ORG.<ENTITY>.MANAGE` per entity) + `employee/permissions.py` (9, note overlap — `EMPLOYEE.VIEW` lives in identity). Seeded in `seed/bootstrap.py`, not `core/rbac`. |
| Permission model — DENY | `role_permission.effect` ∈ `ALLOW/DENY` (`docs/product/08 §3`) | Live `role_permission` table has no `effect` column — composite PK only. **No explicit-deny capability exists in the database at all.** |
| Role-permission data scope | `user_role.data_scope`, `.scope_ref_ids`, `.valid_from`, `.valid_to` (`docs/product/08 §3`) | Live `user_role` table links via `user_company_id` + `role_id` only. None of the four documented columns exist. |
| Shift master | `shift_type` (FIXED/FLEXIBLE/SPLIT/ROTATIONAL), `break_windows` JSONB, flexible/split-shift timing fields, `week_off_pattern_id`, plus `shift_roster`/`shift_rotation_pattern` tables (`docs/product/08 §6.1`) | `shift` table (migration `20260813170000`) ships only the fixed-shift master subset (name, code, start/end time, paid/unpaid break minutes, grace in/out, half-day/min-hours thresholds, `is_night_shift`, `is_cross_midnight`, `is_ot_eligible`). No `week_off_pattern_id` (target table never built), no roster/rotation tables, no shift-type variants. |
| Sensitive-access audit | `sensitive_access_log` — read-path logging of RESTRICTED-field access (`docs/product/08 §11`, FR-AUD-003) | **Zero code references anywhere in `apps/api/src` or `apps/api/alembic`.** `AuditService` logs writes only. |
| Sensitive-field encryption | Column-level encryption for PAN/Aadhaar/bank/MFA secret (`docs/product/14_Security_Architecture.md §1`) | `employee.pan_number_enc`/`aadhaar_number_enc`, `employee_bank.account_number_enc` (documented) are plain `String`/`TEXT` columns at the ORM level — the `_enc` suffix is a *naming convention*, not an applied encryption mechanism. No `TypeDecorator`/Fernet/AES wrapper found anywhere in `core/` or `modules/`. |
| RLS SQL registry | `scripts/sql/002_row_level_security.sql` as the live RLS mechanism (`docs/database/Database_Architecture.md §3/§9` literally cites this file) | That file (and `003_effective_dating_constraints.sql`) is **never invoked by Alembic** — confirmed by explicit comments in every migration from `20260807150000` onward. RLS is instead re-asserted idempotently, inline, per migration. The dev-facing DB doc is itself stale on this point. |
| Idempotency-Key | Required on money/attendance/approval POSTs (`docs/product/09_API_Standards.md §1.6`) | No idempotency middleware/package exists anywhere in `core/`. |
| Rate limiting | Redis sliding-window, per-user/per-tenant/per-endpoint (`docs/product/09 §1.9`) | Only the registration endpoint (`POST /companies/register`) has a rate limiter, confirmed via `tests/security/conftest.py`'s Redis-bucket-reset fixture. No general limiter. |
| Device ingestion service | A separately deployed, separately scaled ASGI app for biometric punches (ADR-0007, `docs/product/09 §3.9`) | `apps/api/src/hrms/ingestion/routes.py` exists with **one** endpoint (`GET /ingestion/health`) and is **never imported or mounted by `app.py`** — confirmed by repo-wide grep. This is an empty scaffold, not a running service. |
| Background jobs / outbox | Celery `chain`/`group`/Beat pipelines, outbox-pattern event dispatch (ADR-0012, ADR-0014) | `core/celery_app.py` exists with one sample task (`health.ping`). No `outbox_event` table in any migration. No Beat schedule configured. No module has a `tasks.py`. |
| 4-deployable topology | Core API / Device Ingestion / Worker / Beat, one image, four entrypoints (`docs/product/03 §1.1`) | Only Core API is wired (`app.py` mounts health/identity/organisation/employee routers). `entrypoints/ingestion.py`, `entrypoints/worker.py`, `entrypoints/beat.py` are not confirmed as invoked by anything beyond documentation. |

### 2.4 What is missing entirely, confirmed by direct inspection

`employee_statutory`, `employee_bank`, `employee_document`, `employee_dependent`,
`employee_education`, `employee_experience`, `employee_skill`, `employee_address`,
`employee_emergency_contact`, `employee_event`, `cost_centre`, `week_off_pattern`,
`holiday`/`holiday_calendar` (present as unexpanded stubs from `001_init_schema.sql`, never
touched by any of the 18 additive migrations, unused by any application code), every Attendance/
Leave/Payroll/Recruitment/Workflow/Notification table, `sensitive_access_log`, `outbox_event`,
`job_log`.

---

## 3. System Context Diagram

```text
                                   ┌─────────────────────────┐
                                   │   Browser (HR Admin)     │
                                   │   apps/web — Next.js 14  │
                                   └────────────┬─────────────┘
                                                │ HTTPS + JWT + X-Company-Id + X-Request-Id
                                                ▼
┌───────────────────────────────────────────────────────────────────────────────────────┐
│                     apps/api — FastAPI "modular monolith" (ONE deployable, FACT)        │
│                                                                                          │
│  app.py: CORSMiddleware → TenancyMiddleware → routers:                                  │
│    health (no prefix) · identity (/v1) · organisation (/v1) · employee (/v1)            │
│                                                                                          │
│  core/: db (async engine+session, RLS SET LOCAL) · tenancy (ContextVar+middleware)       │
│         rbac (permission check, stub DataScope) · audit (write-path only)               │
│         auth (JWT HS256, Argon2id, refresh rotation) · errors · observability (logs only)│
│                                                                                          │
│  modules/: identity · organisation (Company→LegalEntity→Branch→Department→               │
│            Designation→Grade, Shift) · employee (Employee→Employment→Assignment→         │
│            Compensation) · health                                                        │
│                                                                                          │
│  DOCUMENTED, NOT PRESENT in this process or any other: attendance, leave, payroll,       │
│  recruitment, onboarding, exit, workflow, notification, ai, reporting, integration        │
└───────────────────────────────────┬─────────────────────────────────────────────────────┘
                                    │ AsyncSession + SET LOCAL app.company_id
                                    ▼
                     ┌───────────────────────────────┐        ┌───────────────────────┐
                     │   PostgreSQL 16 (single         │        │  Redis 7 (local dev)   │
                     │   cluster, shared schema, RLS)  │        │  Celery broker —       │
                     │   20 baseline tables +           │        │  configured, unused    │
                     │   18 additive migrations         │        │  beyond one sample task │
                     └───────────────────────────────┘        └───────────────────────┘

NOT PRESENT as running processes or code paths, despite being named in docs/product/03 §1.1:
  Device Ingestion service (routes.py exists, never mounted) · Celery Worker (no tasks.py
  anywhere) · Celery Beat (no schedule configured) · AI module · any cloud infra (Terraform/ECS)
```

---

## 4. Module Architecture

Every business module follows the mandatory shape in `docs/architecture/02_Module_Standard.md`:
`router.py` (HTTP only) → `service.py` (business logic, **the only cross-module import surface**)
→ `repository.py` (SQLAlchemy queries, tenant predicate) → `models.py` (ORM) → `schemas.py`
(Pydantic, never ORM in the API layer) → `permissions.py` → `exceptions.py`. `events.py`/
`dependencies.py`/`tasks.py` exist as conventions but are empty/unused in every module today
(FACT — no module has a populated `events.py` or `tasks.py`).

**Cross-module import rule (`docs/architecture/02_Module_Standard.md §2`):** allowed —
`other_module.service`, `other_module.schemas`, `other_module.events`. Forbidden —
`other_module.repository`, `other_module.models`, `other_module.router`.

**Enforcement — DISCREPANCY:** `apps/api/.importlinter` contains exactly **one** contract:

```ini
[importlinter:contract:layers]
name = Modules depend on shared and core only
type = layers
layers =
    hrms.modules
    hrms.shared
    hrms.core
```

This enforces the *layer* ordering (`modules → shared → core`) but has **no per-module contract**
forbidding `employee.service` from importing `organisation.repository`, or one module importing
another's `.models`. The "service.py only" rule is convention and code review today, not a CI
gate — a discrepancy against `docs/architecture/02_Module_Standard.md §2`'s claim that this is
"Enforced by import-linter — CI fails on violation."

**Module → package mapping (FACT):**

| Domain | Package | Status |
|---|---|---|
| Identity (auth, users, roles/permissions) | `modules/identity/` | Built |
| Company, Legal Entity, Branch, Department, Designation, Grade, Shift | `modules/organisation/` (one package — deliberate, "split only past 15 tables," `docs/modules/company/01_Company_Module_Overview.md §3`) | Built |
| Employee (identity, employment, assignment, compensation) | `modules/employee/` (own package, confirmed by two independent docs — `docs/architecture/01_Backend_Structure.md:70`, `VERSION_1_ROADMAP.md §8` item 3) | Built (E-01, E-03–E-06); E-02/E-07–E-10 not started |
| Attendance, Leave, Payroll, Recruitment, Onboarding, Exit, Workflow, Notification, AI, Reporting, Integration | `modules/<name>/` (planned, not created — `docs/architecture/01_Backend_Structure.md §3`) | Not started |

**Health module** (`modules/health/`) is the Sprint-0 sample module — kept as the template
reference for module anatomy.

---

## 5. Module Dependency Graph

```text
core/ (db, tenancy, rbac, audit, auth, errors, observability, config)
  ▲  imported by every module
  │
identity ──────────────────────────────────┐
  ▲ (Employee reuses password/JWT logic)    │
  │                                          │
organisation ◀── employee (via organisation.service — FK existence checks: legal_entity,
  │                        branch, department, designation, grade, shift)
  │
  └── attendance (planned) ◀── employee.service (get_assignment_as_of, get_employment_as_of),
  │                             organisation.service (shift, branch timezone/geofence)
  │
  └── leave (planned) ◀── employee.service (employment as-of, grade/notice for policy)
  │
  └── payroll (planned) ◀── employee.service (compensation, statutory[missing], bank[missing]),
  │                          organisation.service (legal entity statutory codes),
  │                          attendance (planned, summary), leave (planned, LOP)
  │
  └── recruitment/onboarding/exit (planned, deliberately NOT coupled to employee's creation
                                    path today — no ATS fields on Employee, no candidate table)
```

**Consumers must import `employee.service` only** — this is Employee's own documented contract
(`docs/modules/employee/01_EMPLOYEE_MODULE_PLAN.md §1`) and matches the general module rule (§4).

**Accidental coupling (FACT, carried from the Employee/Organisation audit):**
- `department.head_employee_id` is a real FK (`employee.id`, `ON DELETE SET NULL`, added by the
  Department migration) but the ORM docstring and FR-ORG-014 deactivation-blocking logic in
  `organisation/service.py` still contain "Employee doesn't exist yet" comments — stale now that
  Employee has shipped (§36 item 6).
- `employee_assignment.cost_centre_id` is a bare UUID column with no FK (`cost_centre` table
  doesn't exist).

---

## 6. Domain Ownership

| Data | Owning module | May read | May modify |
|---|---|---|---|
| Company profile, settings, subscription, feature flags | `organisation` (Company sub-domain) | Every module (via `organisation.service`) | `organisation` only |
| Legal Entity (PAN/TAN/CIN/GSTIN/PF/ESI/LWF codes — **employer's own** registration) | `organisation` | Employee (FK target), future Payroll | `organisation` only |
| Branch, Department, Designation, Grade, Shift (org master data) | `organisation` | Employee (FK targets for assignment), future Attendance | `organisation` only |
| Employee identity | `employee` | Every module (via `employee.service`) | `employee` only |
| Employment spells | `employee` | Attendance/Leave/Payroll (as-of queries) | `employee` only |
| Org placement (branch/dept/designation/grade/manager/shift, per employee) | `employee` (`employee_assignment`) | Attendance (branch/shift/timezone), Leave (grade for policy), Payroll (grade band) | `employee` only |
| Compensation (CTC) | `employee` (`employee_compensation`) | Payroll (planned) | `employee` only |
| Statutory identifiers (PF/ESI/PT/tax regime — **individual employee's own**, not built) | `employee` (planned `employee_statutory`) | Payroll (planned) | `employee` only, once built |
| Bank account (payout, not built) | `employee` (planned `employee_bank`) | Payroll (planned) | `employee` only, once built |
| Attendance punches/day resolution (not built) | `attendance` (planned) | Payroll (planned, period summary) | `attendance` only |
| Leave ledger/balance (not built, ADR-0004) | `leave` (planned) | Payroll (planned, LOP) | `leave` only |
| Payroll runs/snapshots/payslips (not built, ADR-0005) | `payroll` (planned) | Reporting (planned) | `payroll` only — **never writes back into Employee/Attendance/Leave history**, per ADR-0005 |
| Users, roles, permissions, sessions | `identity` | Every module (permission checks via `core.rbac`) | `identity` only |
| Audit trail | `core/audit` (platform, not a business module) | Every module writes; a future `EMPLOYEE.VIEW_AUDIT`-gated read | Append-only, no module deletes/edits |

**Rule, restated from the Company module's own boundary doc (`docs/modules/company/
01_Company_Module_Overview.md §6`):** if a requirement seems to belong to one module but touches
another module's tables, that is a signal the requirement belongs to the *other* module,
referencing the first by id — not a reason to reach across the boundary.

---

## 7. Core Entity Relationship Model

**Implemented graph (FACT), not the full product-wide data dictionary:**

```text
Company (tenant root, RLS root — FORCE ROW LEVEL SECURITY, no policy of its own)
  ├── LegalEntity (required parent of Branch; employer of Employment)
  │     └── Branch (required legal_entity_id)
  │           └── Department (optional branch_id, optional self-ref parent_id, max depth 5,
  │                           cycle-rejected in service layer)
  │                 └── Designation (optional department_id, optional grade_id,
  │                                  next_designation_id self-ref — passive, unexposed)
  ├── Grade (standalone; company_id-only; UNIQUE(company_id, code) — the one org entity with a
  │          real pre-existing DB uniqueness constraint)
  └── Shift (standalone; company_id-only; master definition only, no roster/assignment)

Employee (permanent identity; UNIQUE(company_id, employee_code); id/code never reissued)
  ├── Employment[]            1:N, spell-bounded (not effective-dated), GiST no-overlap on
  │                           [joining_date, last_working_day]; is_rehire inferred from
  │                           previous_employment_id (no literal is_rehire column, DISCREPANCY
  │                           vs docs — see §36 item 1)
  ├── EmployeeAssignment[]    1:N on employee_id (NOT employment_id) — effective-dated, GiST
  │                           no-overlap; FKs to branch/department/designation/grade/
  │                           reporting_manager/dotted_line_manager(all ON DELETE SET NULL)/
  │                           shift(E-05); cost_centre_id has no FK (no cost_centre table)
  ├── EmployeeCompensation[]  1:N on employee_id — effective-dated, GiST no-overlap;
  │                           annual_ctc_minor BIGINT + currency
  ├── EmployeeStatutory[]     DOCUMENTED ONLY — planned E-07, same effective-dating shape
  ├── EmployeeBank[]          DOCUMENTED ONLY — planned E-08, same effective-dating shape
  └── EmployeeDocument[] etc. DOCUMENTED ONLY — planned E-08, plain (non-effective-dated)
                               collections
```

**Load-bearing structural fact, repeated because every downstream module depends on it:**
`employee_assignment`/`employee_compensation`/(planned)`employee_statutory`/`employee_bank` are
all keyed on `employee_id`, **never `employment_id`**. This is what makes a rehire correct by
construction — a five-year gap between employment spells simply produces zero rows in the child
tables during the gap, not a data-integrity problem
(`docs/modules/employee/05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part C).

**GiST exclusion constraints actually live in the database (FACT, confirmed via migration
review):** `employee_assignment_no_overlap`, `employee_compensation_no_overlap` (both since
`001_init_schema.sql`), and `employment_no_overlap` (added by migration `20260814090000`, on
`[joining_date, COALESCE(last_working_day,'infinity')]`). This third constraint is **not
documented in `docs/product/08_Database_Architecture.md`**, which only names
assignment/compensation as GiST-constrained — a doc gap worth closing (§36).

**Column-name drift between `docs/product/08_Database_Architecture.md` and the live schema
(FACT, confirmed by direct migration/init-script inspection):**

| Doc says | Live schema has |
|---|---|
| `user_company.is_default` | `user_company.is_primary` |
| `permission.module` | `permission.domain` |
| `role_permission.effect` (ALLOW/DENY) | column does not exist |
| `user_role.{data_scope, scope_ref_ids, valid_from, valid_to}` | none of these columns exist; only `user_company_id` + `role_id` |
| `employee.custom_fields` (matches live) vs. `docs/database/Database_Architecture.md`'s own `employee.custom_fields_json` | live column is `custom_fields` — the two *docs* disagree with each other, live schema matches Doc 08, not the dev-guide companion doc |

---

## 8. Employee Lifecycle

All transitions below are FACT (verified in `employee/service.py`) except where marked DOC-only.

| Event | Mechanism | History preserved? |
|---|---|---|
| **Creation** | `POST /v1/employees` → `employee.status = PRE_JOINING`, `is_active = true`, `employee_code` allocated via race-safe `number_series` (`UPDATE ... RETURNING`, never `SELECT max()+1`) | New `employee` row |
| **Hire (first employment spell)** | Separate `POST /v1/employees/{id}/employments` → `employment.status = ACTIVE`. **Does not** set `employee.status` to anything but its default — `employee.status` is written once at creation and never transitions again (§9, §36 item 2) | New `employment` row |
| **Assignment (placement)** | `POST .../assignments`, close-and-insert | Old row's `effective_to` set; business columns never mutated |
| **Transfer / promotion / manager change / shift change** | Same `POST .../assignments`; `change_type` selects the gating permission — `PROMOTION` → `EMPLOYEE.PROMOTE`, everything else (`INITIAL`/`TRANSFER`/`MANAGER_CHANGE`/`SHIFT_CHANGE`) → `EMPLOYEE.TRANSFER` | New row each time |
| **Compensation revision** | `POST .../compensation`, close-and-insert, independent of assignment | New row |
| **Termination** | `POST .../employments/{id}/terminate` → `employment.status = TERMINATED`, `last_working_day` set | Employment history preserved. **Assignment/compensation are left open — see §36 item 1, the single most important finding in this document.** |
| **Employment gap** | Intended: no open `employment`, and (per `docs/modules/employee/05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part D) no open assignment/compensation either. **Actual:** `employment` closes correctly; assignment/compensation stay open (`effective_to IS NULL`) straight through the gap | Employment query-correct; placement/pay as-of **incorrect** during the gap |
| **Rehire** | New `employment` row, `previous_employment_id` set, same `employee.id`/`employee_code`. New `employee_assignment`/`employee_compensation` rows open fresh at the new joining date — nothing is auto-carried forward (department/designation/grade/CTC must be re-entered) | Old rows untouched; audit action `EMPLOYMENT_REHIRED` vs `EMPLOYMENT_STARTED` |
| **Soft deactivation** | `DELETE /employees/{id}` → `employee.is_active = false`. **Distinct from exit** — an account-level lock (e.g. suspected fraud), not the FR-EMP-014 lifecycle transition | Identity row untouched; employment unaffected |
| **Inter-entity transfer** | **DISCREPANCY**: FR-EMP-011 says this should close one `employment` row and open another. FACT: `employment.legal_entity_id` can be `PATCH`ed in place, silently overwriting the employer of record for the spell (§36 item 3) | — |

**`employee.status` vs `employment.status` vs `is_active` — three independent concepts (FACT,
locked by `docs/modules/employee/07_EMPLOYMENT_STATUS_DECISION.md`, this codebase's own
authoritative resolution of an otherwise-undocumented gap):**

- `employee.status`: identity-level, FR-EMP-014's 10-state machine (`PRE_JOINING`, `PROBATION`,
  `ACTIVE`, `ON_NOTICE`, `SUSPENDED`, `ON_LONG_LEAVE`, `EXITED`, `ABSCONDING`, `RETIRED`,
  `DECEASED`) — column exists, **only `PRE_JOINING` is ever written** (FACT — no lifecycle
  transition code exists for it).
- `employment.status`: spell-level, `CHECK` constrained to exactly `ACTIVE`/`TERMINATED` (migration
  `20260814090000`). No stored `ON_NOTICE` — this codebase's own decision, resolving the
  investigation's own recommended "Option B" (derive "on notice" from `last_working_day` being set
  but not yet reached, rather than storing a third state). `last_working_day` is set **iff**
  `status = TERMINATED` (DB `CHECK`-enforced).
- `is_active`: an account lock, orthogonal to employment. `EMPLOYEE_SEATS` billing enforcement
  counts `is_active` employees — so a terminated-but-still-`is_active` identity still occupies a
  paid seat (§36 item 8).

**RECOMMENDATION (restated from the Employee/Organisation audit, still the load-bearing guidance
for any future module):** Attendance and Payroll must treat **employment as-of date** as "was this
person employed on date D?" — never `employee.status`, never `is_active`.

---

## 9. Effective-Dating Architecture

**Pattern (ADR-0003, FACT — live in both schema and application code):**

- **Write**: close the current row (`UPDATE ... SET effective_to = new.effective_from - 1 day
  WHERE id = :current_row_id` — the *only* allowed edit, touches nothing but `effective_to`),
  then `INSERT` a new row (`effective_from = new.effective_from`, `effective_to = NULL`), same
  transaction.
- **Current**: `WHERE employee_id = :id AND effective_to IS NULL AND deleted_at IS NULL` — at
  most one row, structurally enforced.
- **As-of a date**: `WHERE employee_id = :id AND effective_from <= :date AND (effective_to IS
  NULL OR effective_to >= :date)`.
- **Full history**: `WHERE employee_id = :id ORDER BY effective_from`.
- **No-overlap**: `EXCLUDE USING gist (employee_id WITH =, daterange(effective_from,
  COALESCE(effective_to, 'infinity'::date), '[]') WITH &&)`.

**`employee_id`, never `employment_id` (§7)** — this is the single decision every effective-dated
Employee child table is organized around, confirmed as locked and irreversible-without-a-full-FK
migration by `docs/modules/employee/05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` A1.

**As-of vs. current — a distinction every future consumer must respect (DOC, correctly stated,
not yet violated because no consumer exists yet):** writes use open-ended "latest"
(`effective_to IS NULL`), which may start in the *future* (future-dated changes are valid,
FR-EMP-005). Reads for Attendance/Payroll **must** use the as-of pattern, never "the NULL row,"
because the NULL row is not necessarily in effect on the date being queried.

**Immutable history:** business columns on a closed row are never touched after insert. The one
documented exception is `employment.legal_entity_id`, which — contrary to this principle — can be
`PATCH`ed in place today (§8, §36 item 3).

**Concurrency:** `version` column + `If-Match` header on the "close current row" half of every
effective-dated write, so two concurrent transfer/revision requests against the same current row
race safely. First-ever insert for an employee (no current row yet) needs no `If-Match` — nothing
to race against.

**No generic effective-dating framework exists, deliberately** (ADR-0003 consequences, confirmed
as still true — no polymorphic history table, no config-driven engine). The pattern is
hand-repeated per table via service-layer helpers: `get_assignment_as_of(employee_id, date)`,
`get_compensation_as_of(employee_id, date)`. **This is the documented cross-module contract**
Attendance/Leave/Payroll will import once built — extend the same shape to
`get_statutory_as_of`/`get_bank_as_of` when E-07/E-08 ship; do not invent a different shape.

---

## 10. Organisation → Employee Relationship

- `employee.company_id` — required, tenant root.
- `employment.legal_entity_id` — required, **not** `employee.company_id` directly; an employee's
  employer of record is resolved via their current/as-of `employment`, not by walking up from
  identity.
- `employee_assignment.{branch_id, department_id, designation_id, grade_id, shift_id}` — all
  nullable FKs `ON DELETE SET NULL` to Organisation entities; first-ever assignment requires
  branch/department/designation in the **service layer** (`AssignmentFieldsRequiredError`), not
  the database (columns are nullable in SQL — an application-only invariant, §36).
- **No invariant that `employee_assignment.branch.legal_entity_id` matches
  `employment.legal_entity_id`** — an employee's assignment branch and their employment's legal
  entity can silently disagree today. Flagged as OPEN in §38.
- **FR-ORG-014 retrofit is still pending** (§36 item 6): Branch/Department/Designation/Grade
  deactivation still skips the "blocked if referenced by an active employee" check, with code
  comments still reading "Employee doesn't exist yet" — stale now that Employee has shipped. This
  was explicitly deferred to "a small standalone follow-up PR against `organisation/`, filed at
  E-01's close" (`docs/modules/employee/05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` A5) — that follow-up
  has not happened.

---

## 11. Employee → Attendance Dependency

Attendance does not exist. What it will need, and what is/isn't ready (from
`docs/modules/employee/01_EMPLOYEE_MODULE_PLAN.md §3` and `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md`
Part E, both confirmed still accurate against current code):

| Attendance needs | Source | Ready? |
|---|---|---|
| Stable identity across rejoin | `employee.id` | **Yes** |
| "Employed on date D?" | `get_employment_as_of(employee_id, date)` | **Yes, if callers use it** — not `employee.status`/`is_active` |
| Shift | `get_assignment_as_of(employee_id, date).shift_id` → `organisation.get_shift` | Column exists (E-05). **Broken in the post-termination gap** (§8, §36 item 1) until terminate closes assignment |
| Branch / geofence / timezone | `employee_assignment.branch_id` → `branch.timezone`/lat-long/`geofence_radius_m` | Same gap issue; Branch columns themselves are ready |
| Legal entity for the working day | `employment.legal_entity_id` as-of D, **not** inferred from branch | Ready if Attendance doesn't infer it from branch — no invariant enforces they agree (§10) |
| Week-off / holiday | `holiday_calendar`/`holiday` (init-script stubs, never expanded) or `branch.week_off_pattern_id` (never added — `week_off_pattern` itself was never built) | **Not ready — genuine gap**, not merely unbuilt Attendance code |
| NULL shift behavior | BR-14/FR-EMP-018 override chain (company→branch→department→grade→employee cascading default) | **Deliberately deferred** (A3/B8) — a NULL `shift_id` must be treated as "no shift resolves," never assumed to cascade |
| Device punch ingestion | ADR-0007 | **Not built** — and the scaffold that exists (`ingestion/routes.py`) isn't even mounted (§2.3) |

**Must exist before Attendance implementation starts (RECOMMENDATION, unchanged from the
Employee/Organisation audit):**
1. Fix terminate to close assignment (and compensation) at `last_working_day` (§36 item 1).
2. Decide the legal-entity-for-a-working-day rule (employment vs. branch) — currently unconstrained.
3. Build holiday calendar + week-off as either an Organisation follow-up or Attendance's own first
   slice.
4. Do not assume `employee.status` is maintained.

---

## 12. Employee → Payroll Dependency

| Payroll needs | Source | Ready? |
|---|---|---|
| Identity | `employee` | Architecturally yes; PAN/Aadhaar/UAN columns exist with **no write path** (E-02 not shipped) and **no encryption applied** despite `_enc` naming (§2.3) |
| Employment episode / legal entity / joining-exit | `employment` | Architecture yes. In-place `legal_entity_id` PATCH corrupts spell history if misused (§8). Status machine is minimal (`ACTIVE`/`TERMINATED` only) |
| Salary | `employee_compensation.annual_ctc_minor` + `currency` | Gross CTC history yes. No `salary_structure_id`/components/`monthly_gross` — deliberately deferred to Payroll's own catalogue |
| Compensation as-of a pay period | `get_compensation_as_of` | Yes, **except during the post-termination gap** (§36 item 1) |
| Assignment/grade/branch as-of a pay period | `employee_assignment` | Same gap issue. Grade `min_ctc`/`max_ctc` bands are **not enforced** on compensation write — informational only, a documented deliberate deferral |
| Statutory identifiers (PF/ESI/tax regime) | `employee_statutory` | **Missing table.** Fully specified in `docs/modules/employee/21_EMPLOYEE_STATUTORY_IMPLEMENTATION_PLAN.md` (§14 below); zero code |
| Bank account | `employee_bank` | **Missing table**, zero code |
| Attendance / leave summaries | future modules | Missing |
| Employer-level statutory (PF/ESI/TAN codes) | `legal_entity` | **Yes** — implemented, distinct from employee-level statutory data (§6) |

**`employee_statutory`/`employee_bank` are the two hard Payroll blockers** — this is the single
highest-leverage "don't defer" fact in this entire document
(`docs/modules/employee/05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part F). If E-07/E-08 are deferred
past Employee's own build sequence, Payroll cannot be built correctly when its turn comes.

---

## 13. Attendance Architecture Prerequisites

(All DOC — Attendance does not exist. Captured here so a future implementer doesn't have to
re-derive it from `docs/product/03_System_Architecture.md §4`, ADR-0007, ADR-0010, and the SRS.)

- **Ingestion is a separate concern from resolution.** ADR-0007: dedicated Device Ingestion
  service (own deploy lifecycle, own scaling), `punch` table partitioned by month, debounced
  recompute (60s window) so multiple punches for one employee/date trigger one recompute.
- **Business-day boundaries are company-timezone, never UTC** (ADR-0010) — storage is UTC;
  rendering and business-day-boundary computation (night-shift cross-midnight attribution, absent
  marking) use `company.timezone`.
- **`attendance_day` is a derived, one-row-per-employee-per-date table** (not effective-dated in
  the ADR-0003 sense) — `status` resolution reads: employment as-of (population gate) →
  assignment as-of (shift/branch) → shift master (grace/OT/cross-midnight rules) → punches for
  the date → holiday/week-off. Documented status values: `PRESENT/ABSENT/HALF_DAY/WEEKLY_OFF/
  HOLIDAY/ON_LEAVE/ON_DUTY/WFH/COMP_OFF/NOT_JOINED/EXITED`.
- **Idempotency is mandatory on the ingestion path** — dedupe key
  `sha256(device_serial + biometric_id + timestamp)` (`docs/product/22_Integration_Specification.md
  §2`), not yet built anywhere (no idempotency package exists, §2.3).
- **Punch corrections are new punches/regularisations, never edits** — matches the immutable-
  history principle (§9) applied to a non-effective-dated table.
- **Performance targets** (`docs/product/23_Non_Functional_Requirements_and_Compliance.md §1`):
  punch ack < 200ms, attendance recompute for 5,000 employee-days ≤ 2 min, 10,000 punches/min per
  tenant sustained ingestion.
- **Prerequisite from Employee (§11) must be resolved first**: terminate-closes-assignment, and a
  locked legal-entity-for-attendance rule.

---

## 14. Payroll Architecture Prerequisites

(All DOC. Payroll is the highest-risk, highest-effort module in the entire roadmap —
`docs/product/25_Project_Plan_Estimation_and_Team.md §3`/§4 flags it as the longest single build
block, 17 weeks, and the one with the smallest AI-assisted effort compression.)

- **Snapshot-then-compute-then-finalise, immutable once finalised** (ADR-0005): CREATE RUN (lock
  period, snapshot employee list) → SNAPSHOT INPUTS (`pay_run_input_snapshot`, immutable copy of
  compensation/attendance/leave/arrears/loans/statutory-master-as-of-computation-time) → COMPUTE
  (pure function of the snapshot, parallel Celery batches) → VALIDATE/VARIANCE → REVIEW (mandatory
  human approval gate, cannot be skipped) → FINALISE (immutable, emits `PayRunFinalised` via
  outbox). Corrections after finalisation are **arrears in a later run**, never an edit.
- **Statutory rates are data, never code** (ADR-0011): `statutory_master`, itself effective-dated,
  keyed by jurisdiction + effective period. A rate change is a reviewed data update, not a deploy.
- **Money is integer minor units + currency, server-side only** (ADR-0006). No client-side salary
  computation of any kind.
- **`employee_statutory`/`employee_bank` must exist first** (§12).
- **Terminate must close compensation at `last_working_day`** — same fix as §11, extended to
  Payroll's own read path (§36 item 1).
- **Payroll owns the lock-period/backdate contract** (FR-EMP-004): backdating an Employee write
  into an already-finalised payroll period should require `PAYROLL.BACKDATE_OVERRIDE` and trigger
  an arrears line. **Cannot be implemented until Payroll's own lock-period check exists** — do not
  fake this in Employee.
- **Payroll golden-dataset testing is non-negotiable** (`docs/product/15_Testing_Strategy.md §3`):
  ≥200 employee-months of anonymised real data across ~20 scenario categories, verified by a
  compliance consultant (not the developer), a single mismatched paisa fails the build. Two full
  parallel-run cycles against the customer's existing system before go-live, 100% match required.
- **Payroll never writes back into Employee/Attendance/Leave history** — it snapshots and reads,
  corrections are arrears flags forward, never mutation of the source modules' data (ADR-0005,
  §6).

---

## 15. Leave Architecture Prerequisites

(All DOC — Leave does not exist.)

- **Balance is an append-only ledger, never a stored counter** (ADR-0004): `leave_ledger` — every
  accrual/application/cancellation/encashment/carry-forward is its own immutable row
  (`entry_type`, signed `days`, `leave_year`, `expires_on`). Displayed balance = `SUM(days)` over
  the ledger, never a decremented/incremented column. `leave_balance_snapshot` (if built) is a
  rebuildable cache only, never the source of truth — never served from a stale cache
  (`docs/product/03_System_Architecture.md §6`: "never cache: leave balances").
- **Policy resolution follows the same BR-14 "most specific wins" chain** Grade/Employee already
  partially implement for notice/probation (`grade.notice_period_days`/`probation_days`) — the
  leave-entitlement leg of that chain is explicitly **not implemented** anywhere yet (Grade's own
  audit flags `leave_policy_id` as retracted in favor of a not-yet-built
  `leave_policy_assignment` table).
- **Leave depends on Employment as-of** (population/eligibility) and, later, on Attendance's
  presence data for LOP calculation — not the reverse.
- **Sandwich-rule, half-day, and accrual-idempotency scenarios are explicitly named test
  requirements** (`docs/product/15_Testing_Strategy.md §4`) — 16 documented leave test scenarios
  exist as a spec even though no Leave code exists yet.

---

## 16. RBAC Architecture

**Access-control equation (DOC, `docs/product/19_RBAC_and_Permission_Matrix.md §1`):**
`CAN_ACCESS = module_enabled_on_plan ∧ role_has_permission(no explicit DENY) ∧
record_within_data_scope ∧ field_visible_to_role ∧ not_blocked_by_state`. All five are meant to be
evaluated server-side.

**FACT — what actually runs today, term by term:**

| Term | FACT |
|---|---|
| `module_enabled_on_plan` | `plan_feature`/`company_feature_flag` tables exist; **not confirmed wired into `require_permission`'s check** — the permission dependency (`core/rbac/dependencies.py`) only checks `has_permission`, not plan entitlement |
| `role_has_permission(no explicit DENY)` | `RbacService.has_permission` does a **fresh DB query on every call** (`Permission → RolePermission → Role → UserRole → UserCompany`, filtered `UserCompany.status = ACTIVE`) — no caching (contradicts the documented 60s Redis cache, `docs/product/19 §5`, which is DOC-only). **No DENY exists** — `role_permission` has no `effect` column at all (§2.3) |
| `record_within_data_scope` | **Does not run.** `require_permission()` always returns `DataScope(level=COMPANY)`; every router discards the return value into `_scope` |
| `field_visible_to_role` | Only implemented for Compensation (`EMPLOYEE.VIEW_COMPENSATION` gates the whole sub-resource, matching the "absent not disabled" principle for that one resource). Personal contact fields (`personal_email`/`personal_mobile`) are **returned on `EmployeeRead` unconditionally** — confirmed via `schemas.py` — even though `docs/product/19 §6` classifies them `SENSITIVE`, view-gated by a `EMPLOYEE.VIEW_PERSONAL_CONTACT` code that **doesn't exist in the seeded catalogue at all** |
| `not_blocked_by_state` | No locked-period/state-gating mechanism exists (Payroll doesn't exist yet to lock anything) |

**Permission code shape (FACT, matches DOC):** `<MODULE>.<RESOURCE>.<ACTION>` for Organisation
(`ORG.<ENTITY>.MANAGE`, one code per entity, view+manage bundled) and `<MODULE>.<ACTION>` for
Employee (`EMPLOYEE.VIEW_ALL`, `.CREATE`, `.UPDATE`, `.DEACTIVATE`, `.TERMINATE`, `.TRANSFER`,
`.PROMOTE`, `.VIEW_COMPENSATION`, `.UPDATE_COMPENSATION`, plus `EMPLOYEE.VIEW` from `identity`).

**Deviations from the locked 14-code catalogue design, both already implemented and flagged in
their own module's permission file docstring:** `EMPLOYEE.TERMINATE` is **not** in the documented
14-code catalogue — added because no code names ending an employment, following the same
resolution pattern the architecture-decisions doc used for `.VIEW_STATUTORY`/`.VIEW_BANKING`
(still unseeded).

**Catalogue size — DISCREPANCY:** ~250 codes documented (`docs/product/19 §3`, covering every
planned module) vs. **14 seeded** (identity 3 + organisation 8 + employee 9, minus the 1 code
shared, `EMPLOYEE.VIEW`). This is expected incompleteness proportional to what's built, not a bug
— but the *mechanism* gaps above (no data scope, no DENY, no field masking beyond Compensation) are
gaps against what **is** built.

**Data-scope table — DISCREPANCY on the enum itself, not just enforcement:**
`docs/product/19_RBAC_and_Permission_Matrix.md §5` documents 8 levels (`SELF/REPORTEES/
REPORTEE_TREE/DEPARTMENT/BRANCH/LEGAL_ENTITY/COMPANY/ALL_COMPANIES`). `core/rbac/types.py`'s
`DataScopeLevel` has 3 (`COMPANY/TEAM/SELF`) — `REPORTEES` doesn't exist as a name anywhere in
code. Any future implementation of data-scope enforcement needs to decide whether to expand the
existing 3-level enum to the documented 8, or formally narrow the documented target to match — an
OPEN decision (§38).

**Testing requirement (DOC, `docs/product/19 §8`, `docs/product/15 §6`):** six blocking automated
suites — permission matrix (data-driven, ~2,500 assertions target), cross-tenant leakage (every
list/detail endpoint, auto-discovered from routes), data scope, field masking (raw JSON, not
through a client), privilege escalation, self-action blocking. "A failing RBAC test blocks the
release. No exceptions." **FACT:** `tests/security/test_organisation_security.py` covers auth
rejection, mass-assignment, IDOR path-param structure, and password-audit-log leakage for
Organisation only — it is not the exhaustive, auto-generated matrix the docs specify. Cross-tenant
isolation tests do exist per-module under `tests/integration/modules/{organisation,employee}/` —
narrower in scope than the documented auto-discovered suite but real and passing.

---

## 17. Tenant Isolation and RLS

**Mechanism (FACT, `ADR-0002`, confirmed in code):**

```sql
ALTER TABLE <table> ENABLE ROW LEVEL SECURITY;
ALTER TABLE <table> FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON <table>
  USING (company_id = current_setting('app.company_id', true)::uuid);
```

Applied per tenant-owned table, **re-asserted idempotently inline in every migration that touches
that table** — because `scripts/sql/002_row_level_security.sql` (the file the dev-facing DB doc
still cites as the live mechanism) is **never invoked by Alembic** (§2.3). This is documented
explicitly, repeatedly, in migration comments from `20260807150000` onward — treat that file as
dead code, not the RLS registry, for any future migration.

**Session-variable population — two independent code paths (FACT), worth understanding precisely
because they run at different points in the request lifecycle:**

1. **`TenancyMiddleware.dispatch`** (`core/tenancy/middleware.py`) — runs first, before any auth
   dependency. Reads the raw `X-Company-Id` header, builds an **unverified**
   `TenantContext(company_id=<header value>)` with no `user_id` and **no check that the caller is
   actually a member of that company**. Cleared in a `finally` block at request end.
2. **`get_tenant_context` dependency** (`core/tenancy/dependencies.py`) — runs after
   `get_current_user`. Validates the `X-Company-Id` header against the JWT's `company_id` claim
   (mismatch → `404`, never `403`, matching the documented cross-tenant convention), checks an
   active `UserCompany` membership row, then **overwrites** the context with a verified
   `TenantContext(company_id, user_id)`.

The actual `SET LOCAL app.company_id` call (`set_rls_company_id`, `core/db/session.py`) reads
whichever `TenantContext` is current at the moment `get_session()` runs, via
`current_tenant_company_id()`. **OPEN — flagged, not asserted as broken:** whether every route
guarantees `get_tenant_context` resolves before `get_session()` opens its RLS-scoped session (so
RLS is always keyed off the *verified* context, never the middleware's raw header value) was not
independently confirmed in this audit for every route. This is worth an explicit, direct check
before Attendance/Payroll add higher-stakes routes — see §38.

**Belt-and-suspenders (FACT):** every repository method also filters `company_id` explicitly in
its query, on top of RLS — not relying on RLS alone.

**Tables NOT RLS-protected (FACT, by design):** `company` (root — `FORCE`d with no policy of its
own), `user` (no `company_id` column — membership is via `user_company`), `session`,
`refresh_token`, `permission`, `role_permission`/`user_role` (join tables, rely on parent-table
RLS + application-layer join predicate), `plan`/`plan_feature` (global reference data, no
`company_id` at all), `holiday`/`role_permission`/`user_role` (one join away from `company_id`).

**Cross-tenant access convention (FACT, consistent everywhere it's been tested):** always `404`,
never `403` — existence itself is not disclosed to a caller outside the tenant.

---

## 18. Audit Architecture

**Mechanism (FACT):** `AuditService.record(session, *, company_id, actor_user_id, action,
entity_type, entity_id, before, after, ip, user_agent)` — inserts an `AuditLog` row into the same
session as the caller's write; **does not commit** (relies on the caller's transaction/session
scope). `audit_log` columns: `id, company_id, actor_user_id, action, entity_type, entity_id,
before_json, after_json, ip, user_agent, request_id, occurred_at`.

**Coverage (FACT):** every mutating service method across `identity`, `organisation`, `employee`
calls `record()` as its last step before returning. **Reads are never logged** — confirmed by
inspecting every `record()` call site; all are inside create/update/deactivate/terminate/transfer
methods, none inside a `GET`-serving method (including the `EMPLOYEE.VIEW_COMPENSATION`-gated
reads, which per DOC should be RESTRICTED-tier and thus read-logged once E-10 exists).

**`sensitive_access_log` — DISCREPANCY, the largest single audit gap:** zero code references
anywhere in the repository. `docs/product/07_Backend_Architecture.md §9` documents it as
synchronous, `Depends`-driven, firing on any `RESTRICTED`-classified field read. Locked as "build
in E-10" by `docs/modules/employee/05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` A9 — not built, and E-10
hasn't started.

**Write payloads are plaintext JSONB** — `before_json`/`after_json` store the full read-model
snapshot, including compensation figures once E-06's audit calls fire. No redaction/encryption of
audit payloads exists anywhere. This is a project-wide pattern, not unique to any one table, and
compounds as more RESTRICTED-tier tables (Statutory, Bank) ship without a corresponding audit
redaction strategy.

**DB-role-level protection** ("application DB role has no UPDATE/DELETE grant on `audit_log`," per
`docs/product/14_Security_Architecture.md §3`) is **documented only** — no raw SQL `REVOKE`/role
grant was found in any reviewed migration or SQL script.

---

## 19. Sensitive-Data Architecture

**Classification tiers (DOC, `docs/product/19_RBAC_and_Permission_Matrix.md §6`):** `PUBLIC` →
`INTERNAL` → `SENSITIVE` → `RESTRICTED`. RESTRICTED = CTC/salary components/bank
account/PAN/Aadhaar/tax declarations/disciplinary records/medical/POSH — explicit permission only,
always logged (once `sensitive_access_log` exists).

**FACT, what's actually gated today:**
- Compensation: whole-sub-resource gated by `EMPLOYEE.VIEW_COMPENSATION`/`.UPDATE_COMPENSATION` —
  the one resource that correctly implements "absent, not masked" for an unauthorized caller.
- PAN/Aadhaar: columns exist (`pan_number_enc`, `aadhaar_number_enc`), **no write path at all**
  (E-02 not shipped) and **not encrypted** despite the naming convention (§2.3).
- Personal contact (email/mobile): `SENSITIVE`-classified per doc, but returned unconditionally on
  `EmployeeRead` with no gating permission seeded (§16).
- Statutory/Bank: no code exists; the E-07 plan (§21 below) already resolves the "no
  `EMPLOYEE.VIEW_STATUTORY` code exists" gap with a recommended two-new-codes approach
  (`EMPLOYEE.VIEW_STATUTORY`, `EMPLOYEE.VIEW_BANKING`), not yet implemented.

**Masking formats (DOC, never implemented anywhere in code today):** PAN `ABCDE****F`, Aadhaar
`XXXX XXXX 1234`, bank account `******7890`. **RECOMMENDATION carried from the E-07 plan**: for
fields with no documented masking format (PF number, ESI IP number, tax regime), gate the whole
sub-resource rather than inventing a per-field mask — matching Compensation's own precedent, not
CTC-style bucketing.

**Encryption-at-rest — the largest concrete gap in this section:** no `TypeDecorator`, no Fernet/
AES wrapper, no KMS integration exists anywhere in `core/` or any module. Every `_enc`-suffixed
column is a plain `String`/`TEXT` column today. This must be resolved — or explicitly, consciously
deferred with a documented compliance rationale — before E-02 (PAN/Aadhaar write path) or E-07/E-08
(statutory/bank) ship real data into these columns.

---

## 20. API Architecture

**Conventions (FACT vs. `docs/product/09_API_Standards.md`):**

| Rule | Status |
|---|---|
| `/v1` + plural kebab-case resources | **Implemented** |
| Nest one level (`/employees/{id}/assignments`) | **Implemented** |
| Verb sub-resource (`.../terminate`) | **Implemented** |
| `DataEnvelope<T>`/`ListEnvelope<T>`/`ErrorEnvelope` | **Implemented** (`shared/pagination.py`, `core/errors/envelope.py`) |
| Pagination (`page`/`per_page`/cursor for high-volume tables) | **Not implemented** — `ListEnvelope.pagination` is always omitted on every list endpoint; the frontend's `DataEnvelope` TS type has no pagination fields at all despite a comment claiming parity |
| `If-Match` optimistic concurrency | **Implemented**, on every mutating call to a non-effective-dated resource and on the close-current-row half of effective-dated writes |
| `?as_of=` | **Implemented** on employment/assignment/compensation list endpoints |
| `Idempotency-Key` | **Not implemented** anywhere, despite being documented as required on money/attendance/approval POSTs |
| Rate limiting | **Only** on `POST /companies/register` |
| Cross-tenant → `404` never `403` | **Implemented consistently** |
| Field masking (omit, never `null`) | **Implemented for Compensation only** (§16, §19) |
| Declarative `Depends(require_permission(...))` per route, CI-enforced | **Implemented as a pattern**; the CI check that "an endpoint with no explicit permission dependency fails the build" (documented in `docs/product/09 §6`) was **not found** in this codebase — no such lint rule exists |
| Device Ingestion as a separate auth/deploy surface | **Not implemented** — orphaned, unmounted scaffold (§2.3) |

**Hire is two-or-more HTTP calls, not a single nested create — DISCREPANCY:**
`docs/modules/employee/01_EMPLOYEE_MODULE_PLAN.md` E-03 originally wanted employment folded into
`POST /employees`. FACT: `POST /v1/employees` creates identity only; `POST /v1/employees/{id}/
employments` is a separate call. This is a deliberate, documented deviation ("fine for API purity;
UI must orchestrate or a later hire facade added"), not an oversight — but it means a standalone
`employee` row with zero `employment` rows is a real, reachable state today, which no consumer
should treat as unusual.

---

## 21. Database Architecture

**Stack (DOC + FACT, unchanged from ADR-0002/0013/0015):** PostgreSQL 16, SQLAlchemy 2.x async +
`asyncpg`, Alembic. RLS + GiST exclusion constraints + (eventually) partitioning are hand-written
raw SQL in migrations — SQLAlchemy's model layer cannot express any of the three, by design, not a
regression from the prior Prisma-based design (ADR-0015).

**What's consistent and strong (FACT):** UUID PKs; `company_id` + index on every tenant table;
`created_at`/`updated_at`/`deleted_at`/`version` on every mutable table (except the many
still-thin stub columns inherited from `001_init_schema.sql` — see the drift table in §7); RLS
`ENABLE`+`FORCE` re-asserted per migration; money as `BIGINT` minor units + currency; GiST overlap
on the three temporal Employee tables plus `employment_no_overlap`; partial unique indexes on org
codes; FKs added in disciplined follow-up migrations, not the original stub.

**Migration history (FACT, 19 files total, head = `20260814120000_employee_compensation`):**
`001_init_schema.sql` (20 stub tables, executed by the first Alembic revision as raw SQL, not
autogenerate) → B1 auth/audit (`audit_log` table) → Company profile/setup-progress/plan/
subscription/feature-flag (5 migrations) → user registration fields → Legal Entity → Branch
(drops free-text `state`, adds `state_code` + geo columns) → Department (adds `head_employee_id`
passive FK, `parent_id` FK) → Designation (adds `next_designation_id` passive self-FK) → Grade
(renames `rank`→`level`, adds CTC-band columns, connects `designation.grade_id`) → Shift Rules
(brand-new `CREATE TABLE`, no stub) → Employee Foundation → Employment Lifecycle (renames
`exit_date`→`last_working_day`, adds `employment_no_overlap` GiST + status `CHECK`) → Employee
Assignment (6 new FKs) → Employee Shift Assignment (`shift_id` column) → Employee Compensation
(`revision_type`/`revision_reason`).

**Stub tables from `001_init_schema.sql`, never expanded, never touched by any of the 18
follow-up migrations, unused by any application code (FACT):** `holiday_calendar`, `holiday`.
These are real, empty architectural debt — present in the schema, invisible to every module.

**`002_row_level_security.sql` and `003_effective_dating_constraints.sql`:** dead files. Never
invoked by Alembic. Their content is duplicated inline in `001_init_schema.sql` and in each
migration's own idempotent RLS re-assertion. `docs/database/Database_Architecture.md §3/§9` still
cites `002_...` as if live — a doc inaccuracy to fix, not a code gap.

**Async session lifecycle (DOC + FACT):** request-scoped `AsyncSession` via `Depends(get_session)`,
commit on clean exit / rollback on exception, `expire_on_commit=False`. The documented hazard
(`docs/product/08_Database_Architecture.md §15`) — lazy-loading a relationship after the owning
session closes raises `DetachedInstanceError`, a new bug class relative to the prior
Prisma-generated-client model — is real and unmitigated by any code-level guard found in this
audit (no `lazy="raise"` setting confirmed on any model, contrary to what
`docs/database/Database_Architecture.md §10` claims); the mitigation is discipline (eager-load
what a response schema needs) plus, per doc, an N+1 query-count assertion in integration tests —
not independently verified as present for every endpoint in this audit.

**Indexing:** assignment has a "current row" covering index (`company_id, employee_id,
effective_from DESC`) and a partial manager index (`WHERE effective_to IS NULL`). Compensation
relies on the same shape. Adequate for current (near-zero) data volume; the documented
data-volume projections (§30) assume partitioning `punch`/`attendance_day`/`audit_log`/
`notification_log` by month — none of those tables exist yet, so partitioning is entirely
prospective.

---

## 22. Transaction Boundaries

One HTTP request = one `AsyncSession` = one transaction (`get_session`'s commit-on-success/
rollback-on-exception context manager). FACT, per operation:

| Operation | Atomic today? | Should be |
|---|---|---|
| Create employee (code allocation + insert + audit) | **Yes**, one request | Yes |
| Hire (identity + employment + first assignment + first compensation) | **No** — 2–4 separate HTTP calls | RECOMMENDATION: a hire/rehire facade endpoint before Employee UI (E-09) ships, not required for backend correctness today |
| Rehire | Employment insert only; caller must separately add assignment/compensation | Same as hire |
| Transfer / promotion / shift change | **Yes** — close + insert + audit, one transaction | Yes |
| Compensation revision | **Yes** | Yes |
| Terminate | Employment only | **Must include** closing assignment + compensation at `last_working_day` in the same transaction (§36 item 1) |
| Inter-entity transfer | In-place `legal_entity_id` PATCH, one transaction | Per FR-EMP-011, should be close-spell + open-new-spell (+ new assignment) in one transaction — not built this way today |

**Cross-service calls stay in-process, same session** — `employee.service` calling
`organisation.service` for FK existence checks happens inside the same request's `AsyncSession`,
correct for a modular monolith with no distributed-transaction need (ADR-0001).

---

## 23. Concurrency Strategy

Optimistic concurrency (`version` column + `If-Match`) is the project-wide standard, applied
consistently on every write that mutates an existing row. FACT, per race:

| Race | Protection |
|---|---|
| Concurrent employee-code allocation | `UPDATE number_series ... RETURNING`, row-locked — never `SELECT max()+1` |
| Seat-limit check at create time | Check-then-insert — **TOCTOU race exists**: two concurrent creates can both pass the count check before either inserts. Not DB-enforced. **MEDIUM severity, documented, not fixed** |
| Concurrent employment create | `employment_no_overlap` GiST → domain error |
| Concurrent terminate | `version`/`If-Match` |
| Concurrent assignment/compensation revision | `If-Match` on the current row + GiST as a second line of defence |
| Concurrent first-ever assignment/compensation insert | No `If-Match` needed (correct — nothing to race against yet); GiST still rejects a true double-insert race |
| Future: attendance punches | Needs idempotency keys — standard is documented, code doesn't exist |
| Future: payroll | Needs snapshot immutability + period lock — documented (ADR-0005), not built |

---

## 24. Error-Handling Strategy

**Hierarchy (FACT, `core/errors/`):** `AppError` base (`code="INTERNAL_ERROR"`, 500) →
`NotFoundError`(404), `ValidationError`(422), `ConflictError`(409), `PermissionDeniedError`(403),
`LockedError`(423); auth-specific: `UnauthorizedError`(401), `InvalidCredentialsError`,
`InvalidTokenError`, `AccountLockedError`(423). Module-specific exceptions (e.g.
`LegalEntityDeactivationBlockedError`, `EmploymentNotActiveError`,
`AssignmentFieldsRequiredError`) subclass this hierarchy — never bare tuples, never `None`-means-
error.

**Translation to HTTP (FACT):** four registered handlers in `handlers.py` —
`AppError`→its own status/envelope, `RequestValidationError`→422 `REQUEST_VALIDATION_ERROR`,
`StarletteHTTPException`→`HTTP_ERROR`, catch-all `Exception`→500 `INTERNAL_ERROR` (with a comment
noting Sentry integration is planned, not present). Routers never catch-and-translate themselves —
translation is centralized.

**Envelope (FACT, matches DOC):** `{error: {code, message, details, request_id,
documentation_url}}` — Pydantic models, machine-checkable via OpenAPI. Never leaks stack
traces/SQL/internal identifiers (not independently verified for every 500 path in this audit, but
the catch-all handler's shape supports it).

**Mass-assignment protection (FACT):** every write schema uses `extra="forbid"`; confirmed
positively tested in `tests/security/test_organisation_security.py`.

---

## 25. Frontend Architecture

**Stack (FACT):** Next.js 14 App Router, React 18, TypeScript, Tailwind, shadcn/ui primitives.

**What exists (FACT):** pages for every Organisation entity (`app/app/{company, legal-entities,
branches, departments, designations, grades, shifts, setup, dashboard}`), each following the same
list-page + `[id]` detail/edit page + create-dialog pattern, each with a matching `.test.tsx`.
Shared primitives: `apiClient` (`lib/api/client.ts` — thin `fetch` wrapper, attaches
`X-Request-Id`/`Authorization`/`X-Company-Id`/`If-Match`, single in-flight refresh-on-401 retry),
`useApiResource` (`hooks/use-api-resource.ts` — **GET-only**, fetch-on-mount, no mutation helpers,
no list/pagination state, treats 404 as a special "`notImplemented`" state rather than an error),
`AuthProvider`/`useAuth()` (`lib/auth/auth-context.tsx`), `PageHeader`/`FormField`/`LoadingState`/
`ErrorState`/`EmptyState`/`Card`/`Button`/`Badge`/`Dialog`.

**What does not exist (FACT, all confirmed by zero-hit repo-wide search):**
- **Zero Employee UI** — no route under `app/app/employees*` despite the Employee API existing.
- **No `PermissionGate`/`usePermission`/`useCan` component or hook anywhere.** `UserProfile.
  permissions: string[]` is fetched into `AuthProvider`'s state on every session load and **never
  read again anywhere in the frontend** — dead data, confirmed by grep. This directly contradicts
  the "absent, not disabled" tab/action-gating principle multiple design docs treat as mandatory
  for the Employee 360° profile (`docs/modules/employee/04_EMPLOYEE_UX_PLAN.md §2`) — the
  primitive to build it doesn't exist yet (locked as A10 in the architecture-decisions doc,
  timing: "before E-09 starts," not before).
- **No paginated `DataTable` component.** Every list page today renders a plain `<ul>` — acceptable
  at Organisation's low row counts (≤10s of branches/departments per company), **not** acceptable
  at Employee-directory scale (hundreds to thousands of rows), and the backend doesn't send
  pagination metadata to build one against yet (§20).
- **No as-of-date UI control, no Timeline component, no money-formatting helper (minor units → 
  display), no sensitive-field masking component.**
- **Nav is static and build-scope-gated, not permission-gated** (`components/layout/
  nav-items.ts` — a flat array; a doc comment states items are simply absent, not
  conditionally-disabled, when the feature "can't access yet" — i.e. gated by what's *built*, not
  by what the *current user* can do).

**Consequence for whoever builds E-09 (Employee Directory/360°/import):** the screen *pattern*
(list + `[id]` + form + `useApiResource`) can be copied from Organisation. It cannot yet: hide
tabs/actions by permission, page a large directory, show as-of point-in-time state, or render
effective-dated history as a timeline. All four are prerequisite infrastructure, not incidental
polish (§39).

---

## 26. Background Jobs / Asynchronous Processing

**Chosen system (DOC, ADR-0014):** Celery + Redis (broker and result backend). Rejected: BullMQ
(Node-specific, incompatible with the Python rewrite), Dramatiq/ARQ/RQ (weaker canvas/monitoring
for the payroll pipeline's chain/group/chord needs).

**FACT — what exists:** `core/celery_app.py` (the Celery application instance) with **one** sample
task, `health.ping`. **No module has a `tasks.py`.** No queue topology is configured beyond the
documented plan (`default`/`payroll`/`attendance`/`ai`/`reports`). No Beat schedule exists. No
`outbox_event` table exists in any migration — the outbox pattern (ADR-0012, required for any
money/compliance-touching event) is entirely prospective.

**Documented design, to be honored when jobs are actually built (DOC, `docs/architecture/
04_Background_Job_Architecture.md`):** `company_id` as the **first, explicit argument** to every
task (Celery tasks have no ambient request context — a `TenantContext` must be constructed inside
the task body, never assumed from a contextvar the way request-path code can). Task naming
`<module>.<verb_noun>`, no auto-discovery magic. Idempotent, resumable — retries must never
corrupt state. A dedicated `AsyncSession` opened per task, RLS `SET LOCAL`'d explicitly inside the
task, not inherited.

---

## 27. External Integrations

(All DOC — zero integration code exists in this repo. Captured because
`docs/product/22_Integration_Specification.md §12` calls Phase-1 integration effort "~20% of the
Phase 1 build, consistently underestimated," and biometric device integration + statutory file
generation are separately flagged as "the two highest-risk items in the entire project after
payroll computation itself.")

- **Biometric/access-control devices** — push/ADMS-HTTP pattern preferred (ZKTeco/eSSL, common in
  India); an on-prem agent bridges LAN-only devices, buffers offline in local SQLite, pushes to
  `/ingest/v1/punches` with HMAC device auth + idempotency keys. "Budget 3× your first time
  estimate" — devices are heterogeneous, poorly documented, often behind NAT.
- **Messaging** — Email (SES + SendGrid failover), SMS (India **DLT registration is a hard,
  1–3-week external lead-time dependency**, flagged as a common launch blocker), WhatsApp Business
  API (named "highest-value channel in the Indian SME market," template pre-approval 24–48h).
- **Accounting/ERP** — generic bank-payment-file + journal-voucher CSV/Excel export ships first
  ("covers 90% of customers without any API integration"); Tally/Zoho Books/SAP are later,
  scoped-per-deal integrations.
- **Payment gateway is subscription billing only** — explicitly, deliberately **not** used for
  salary disbursement: "Do not build salary disbursement; it is a regulated activity and a
  different business." Salaries move via customer-generated bank advice files.
- **SSO (SAML/OIDC)** and **SCIM 2.0** are designed in `docs/product/10_Authentication_Architecture
  .md §4` but Phase 2/3, not Phase 1.
- **Every integration must be optional/degradable** — core HR operations must complete without any
  one integration; adapter interface per category so provider swap is a config + one adapter
  class, not a rewrite (ADR-0009's non-blocking principle, generalized beyond AI).

---

## 28. Observability / Logging

**FACT:** `core/observability/logging.py` — `structlog`, JSON output to stdout, level from
settings. **This is the entire observability stack found in code.** No tracing (no OpenTelemetry
instrumentation found, despite being named throughout `docs/product/03_System_Architecture.md`),
no metrics export, no Sentry integration (the catch-all error handler's own comment says "Sentry
hook lands here in a later sprint" — not yet wired).

**Documented target (DOC, not built):** OpenTelemetry trace propagation from API → Celery queue →
worker → DB (`opentelemetry-instrumentation-celery`); Grafana dashboards (platform health, queue
health, business metrics, per-tenant, cost); Sentry with `request_id`/`company_id` tags on every
exception; Flower for Celery queue/worker visibility.

**`request_id`** is the one piece of this that *is* implemented end-to-end: generated client-side
(frontend `apiClient`), propagated via `X-Request-Id`, captured in a tenancy `ContextVar`
(`current_request_id()`), and stamped onto every `audit_log` row.

---

## 29. Security Architecture

**Implemented (FACT):** TLS termination assumed at the infra layer (not verifiable in-repo — no
infra config exists, §2.2); JWT HS256 access tokens (15-minute lifetime per config default),
Argon2id password hashing, refresh-token rotation with `token_family_id`-based reuse detection —
**FACT, confirmed directly in code**: `core/auth/tokens.py` generates/hashes the opaque refresh
token; `core/db/models/identity.py`'s `RefreshToken.token_family_id` plus
`core/db/repositories/identity.py` (family lookup) and `modules/identity/service.py:94-96`
(`if record.token_family_id: ... "REUSE_DETECTED"`) implement the actual reuse-detection and
revocation logic — this mechanism spans `core/auth`, `core/db`, and `modules/identity`, not a
single file. RLS tenant isolation (§17); `extra="forbid"` mass-assignment protection everywhere;
cross-tenant → 404 convention; Argon2 password hashing confirmed via `core/auth/passwords.py`.

**Documented, not implemented (DOC only):** column-level encryption for PAN/Aadhaar/bank/MFA
secret (§19); **MFA — DISCREPANCY, more incomplete than the docs suggest**: `user.mfa_enabled`
exists as a column from `001_init_schema.sql` (`BOOLEAN NOT NULL DEFAULT false`), but
`user.mfa_secret_enc` was not confirmed added by any of the 19 reviewed migrations, and a
repo-wide search of `core/auth/` found **zero** references to `mfa`/TOTP/`pyotp` anywhere — no
`/auth/mfa/*` endpoints, no secret generation/verification flow exists in code at all. Treat MFA
as fully DOC-only (design, not a partial build) despite the one schema column suggesting
otherwise; SSO/SAML/OIDC; break-glass impersonation controls (30-minute cap, banner, audit,
forbidden-action list); WAF/DDoS/CloudFront (infra-layer, no infra code in-repo). **CI — FACT,
confirmed directly**: `.github/workflows/ci.yml` runs Ruff lint, Ruff format check, Mypy (core
package), and pytest. No Semgrep/SAST, no OWASP ZAP/DAST, no `pip-audit`/`Safety`/dependency
scanning, no `detect-secrets`/`gitleaks` secret scanning step exists in the CI workflow — all
four are DOC only (`docs/product/14_Security_Architecture.md §2`), not merely unverified.
`sensitive_access_log` (§18); idempotency keys (§20); rate limiting beyond registration (§20).

**Impersonation, break-glass, and MFA are all Phase-1-scoped-but-unverified** — this audit did not
trace every claim in `docs/product/10_Authentication_Architecture.md` and `docs/product/
14_Security_Architecture.md` against code line-by-line; treat the auth *token model* (15-min
access / 30-day rotating refresh, family-based reuse detection) as FACT, and treat MFA/SSO/
break-glass specifics as DOC pending a dedicated follow-up check before relying on them.

---

## 30. Testing Architecture

**Coverage targets (DOC, `docs/product/15_Testing_Strategy.md §2`, `docs/product/05
_Development_Standards.md §4`):** 80% overall unit coverage; **95% for payroll calculation, leave
accrual, attendance resolution, RBAC/tenancy, and tax** — explicitly non-negotiable, "not where
time gets cut" even under schedule pressure. Not independently measured against the current
codebase in this audit.

**FACT — what exists:** unit + integration tests for every shipped Organisation and Employee slice
(mirroring `src/hrms/` 1:1 under `apps/api/tests/`), following a consistent pattern: mocked-repo
unit tests for service-layer business-rule branches, real-`AsyncSession`-against-Testcontainers-
Postgres integration tests for RLS/GiST/concurrency behavior proven at the DB level (not just
asserted at the application level). `tests/security/test_organisation_security.py` (one file,
Organisation-scoped, §16). Cross-tenant isolation tests exist per-module
(`test_cross_tenant_isolation.py` pattern) and permission-matrix tests exist per-module
(`test_permission_matrix.py` pattern) — narrower than the documented auto-generated, all-endpoint,
all-role suite, but real.

**Documented, not built (DOC only):** the payroll golden-dataset suite (§14) — cannot exist before
Payroll does; the auto-discovered cross-tenant leakage generator running over every route from the
OpenAPI spec; the ~2,500-assertion data-driven permission matrix; E2E suite (Playwright, 60
critical journeys); load testing (k6, 5 scenarios); accessibility testing (axe-core); mobile E2E
(Detox/Maestro).

**Six blocking security suites named in `docs/product/19 §8`** (permission matrix, cross-tenant
leakage, data scope, field masking, privilege escalation, self-action) exist today only in
partial, per-module form — not as the single exhaustive, CI-blocking suite the docs describe.

---

## 31. Migration Strategy

**FACT, established pattern (every migration since `20260807150000` follows it identically):**
1. `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` per column, never drop-and-recreate a live table
   (exception: `branch.state`→`state_code` and `grade.rank`→`level`, both explicit, documented,
   justified renames of columns with no real data at the time).
2. New FK constraints added in the same or a dedicated statement, `ON DELETE SET NULL`/`RESTRICT`
   as appropriate — never silently defaulting to `CASCADE`.
3. Indexes added alongside the columns they serve.
4. **RLS is re-asserted idempotently inline** in every migration touching an RLS-protected table
   (`DROP POLICY IF EXISTS` + `CREATE POLICY`) — never assumed already-present from
   `001_init_schema.sql`'s original loop or the dead `002_row_level_security.sql` file (§17).
5. Forward-only — no downgrade path is implemented for the init-schema migration (`downgrade()`
   raises `NotImplementedError`); later migrations follow standard Alembic reversibility.
6. New tables (e.g. `shift`, and eventually `employee_statutory`/`employee_bank`) are created with
   their GiST exclusion constraint, indexes, and RLS policy **in the same migration**, not a
   follow-up.

**RECOMMENDATION for every future migration:** follow this exact shape. Do not resurrect
`002_row_level_security.sql`/`003_effective_dating_constraints.sql` as a dependency — they are
dead files that happen to still describe a still-true pattern; copy the pattern, not the file
reference.

---

## 32. Data Lifecycle / Retention

**DOC only — no retention/archival job exists in code.** Documented requirements
(`docs/product/23_Non_Functional_Requirements_and_Compliance.md §4`, DPDP Act 2023 framing):

| Record class | Retention |
|---|---|
| Payroll and wage registers | 8 years |
| PF records | 7 years after exit |
| ESI records | 5 years |
| Income tax / TDS records | 8 years |
| Attendance / muster roll | 3 years (state-variance possible) |
| Recruitment records (unsuccessful candidates) | 6–12 months with consent, then delete |

Statutory retention **overrides** a data-subject erasure request — this must be explained to the
employee, never silently applied, per the documented DPDP right-to-erasure workflow. Non-prod
environments require **irreversible** anonymisation of names/contacts/PAN/Aadhaar/bank/salary
before any production-shaped data is copied down (`docs/product/03_System_Architecture.md §8`) —
no anonymisation tooling was found in this audit; also DOC-only.

`file.retention_until` (a documented column on the planned `file` table, §2.4) is the intended
mechanical hook for enforcing this — not built.

---

## 33. Failure and Recovery Strategy

**DOC only — no infra exists in-repo to verify against (§2.2).** Captured for when infra is
built:

- **RPO 5 minutes, RTO 2 hours** (`docs/product/16_Deployment_Strategy.md §6`); daily automated +
  point-in-time-recovery backups, 35-day retention, monthly automated restore test (never assumed
  — tested); annual full DR drill.
- **Payroll blackout window: 25th–5th of every month.** No planned deployments except hotfixes
  during this window (`docs/product/16 §5`); zero planned downtime during this window is an
  availability NFR (`docs/product/23 §2` A3), not merely an operational preference.
- **Failure-mode table** (`docs/product/03_System_Architecture.md §7`): every external dependency
  (DB, Redis, S3, SMS/WhatsApp, AI/LLM, biometric devices) has a documented degrade-queue-alert
  behavior — "no external dependency may block a core HR operation." AI failures in particular
  must never block a core operation (ADR-0009, generalized as a platform-wide principle in this
  table).
- **Payroll job crash resumes from its last checkpoint** (ADR-0005's pipeline design) — never
  silently re-runs from scratch, never exposes a partially-computed run as if it were final.
- **Rollback triggers** (any one → immediate rollback, `docs/product/16 §2`): error rate >2×
  baseline for 5 min; p95 latency >3× baseline; **any** payroll computation failure; **any**
  auth/authz failure spike; **any** report of cross-tenant data visibility.

---

## 34. Architectural Invariants

See Appendix A for the consolidated, numbered list. This section states the *reasoning*; Appendix
A is the checklist form.

1. **RLS is a backstop, never the only control** — every repository query still filters
   `company_id` explicitly (ADR-0002's "defence in depth," confirmed in every reviewed repository
   method).
2. **Effective-dated child tables are keyed on `employee_id`, never `employment_id`, and a change
   is always an insert, never an in-place edit of a business column** (ADR-0003, §7, §9).
3. **`employee.id`/`employee_code` are never reissued, including across a rehire** — this is the
   structural fact that makes a five-year employment gap a non-event for the data model, not a
   special case.
4. **Money is `BIGINT` minor units + a `currency` column, never a float, never client-computed**
   (ADR-0006).
5. **A finalised payroll run is immutable; corrections are arrears in a later run** (ADR-0005) —
   this invariant does not yet have code to violate, but must not be violated when Payroll is
   built.
6. **Statutory rates are effective-dated data, never a code constant** (ADR-0011) — same status as
   #5.
7. **Cross-tenant access is always `404`, never `403`** — existence is never disclosed outside a
   tenant.
8. **A module may import another module's `service.py`/`schemas.py`/`events.py` only — never
   `.repository`/`.models`/`.router`** — currently convention + code review, not yet a CI-enforced
   per-module contract (§4, gap flagged, not yet a violation anywhere found).
9. **No Person layer above Employee** — explicitly rejected by `docs/product/02_PRD.md §11`
   ("Not modelled. Avoid the word.") and not reintroduced anywhere in the built code.

---

## 35. Rules Future Developers MUST NOT Violate

See Appendix C for the "do not implement yet" list. This section is the narrower "do not ever do
this" set:

1. **Do not add a generic effective-dating framework** or a polymorphic history table. Repeat the
   ADR-0003 shape per table.
2. **Do not move assignment/compensation/statutory/bank onto `employment_id`.** This would break
   rehire correctness for every consumer built against the current shape.
3. **Do not let Payroll write back into Employee/Attendance/Leave history.** Corrections are
   forward-only arrears entries, never edits to source-module data.
4. **Do not compute money client-side**, ever, for any reason, including "just a preview."
5. **Do not treat `employee.status` or `is_active` as the "is this person currently employed"
   gate for Attendance/Leave/Payroll.** Use `get_employment_as_of`.
6. **Do not resurrect `scripts/sql/002_row_level_security.sql`/`003_effective_dating_constraints
   .sql` as a live dependency.** They are dead files; copy the RLS/GiST *pattern* inline into new
   migrations instead.
7. **Do not add a second UAN column.** `employee.uan_number` is the resolved single source of
   truth (§21 of the E-07 statutory plan, already reconciling a real doc/doc conflict) — do not
   add `employee_statutory.uan` when E-07 is built.
8. **Do not build Attendance's status resolution assuming a shift always resolves.** `shift_id
   IS NULL` is a legitimate, expected state (BR-14 override chain is deliberately deferred) —
   treat it as "no shift," not an error.
9. **Do not skip terminate's assignment/compensation-closing fix and proceed to build Attendance
   or Payroll on top of the current `terminate_employment` behavior** — see §36 item 1. This is
   the one gate this entire document treats as blocking.

---

## 36. Known Architectural Gaps

Ordered by severity, each with Decision / Current implementation / Evidence / Reason /
Consequence / Future impact where a decision is implicated.

### 1. CRITICAL — Terminate does not close assignment/compensation

- **Decision:** whether ending an employment must also close the employee's open assignment and
  compensation rows at `last_working_day`.
- **Current implementation:** `EmploymentService.terminate_employment`
  (`apps/api/src/hrms/modules/employee/service.py:463-503`) sets only `employment.status =
  "TERMINATED"` and `last_working_day`. It does not touch `employee_assignment` or
  `employee_compensation`.
- **Evidence:** confirmed by direct code read (service.py:495-503, `values={"status":
  "TERMINATED", "last_working_day": ...}` — no assignment/compensation repository calls anywhere
  in the method). Contradicted by `docs/modules/employee/05_EMPLOYEE_ARCHITECTURE_DECISIONS.md`
  Part D, which specifies both child tables' `effective_to` must be set at exit. Integration tests
  currently encode the *wrong* behavior — the gap is closed by the **rehire's** write (the new
  assignment row's insert sets the old row's `effective_to` to the day before the *rehire* date,
  spanning the entire gap), not by terminate itself.
- **Reason it exists:** terminate was implemented as a thin, employment-only action; the
  cross-table close was documented as part of the design but not carried into the first
  implementation pass.
- **Consequence:** `get_assignment_as_of`/`get_compensation_as_of` return the pre-exit
  branch/shift/CTC for any date inside the employment gap, because the row's `effective_to` is
  still `NULL`. Any Attendance/Payroll code that trusts these helpers without independently
  intersecting employment coverage will mark a terminated person as still on shift, still drawing
  pay.
- **Future impact:** this is the single blocking item before Attendance or Payroll implementation
  starts (§39, §40). Fixing it is additive (close two rows in the same transaction as the
  `TERMINATED` write) and low-to-medium risk — the risk is entirely in updating the rehire
  integration tests that currently assert the wrong gap-closing behavior, not in the schema.

### 2. HIGH — `employee.status` never transitions past `PRE_JOINING`

No lifecycle code writes to `employee.status` after creation. Three parallel "status" concepts
(`employee.status`, `employment.status`, `is_active`) exist with no reconciling logic. Any future
consumer that trusts `employee.status` for anything beyond "this identity was created" will be
wrong.

### 3. HIGH — Inter-entity transfer is an in-place `legal_entity_id` PATCH

Contradicts FR-EMP-011 ("closes one employment and opens another") and corrupts the historical
record of which legal entity employed a person during a given spell — a real problem for
Payroll's employer-of-record history once Payroll exists.

### 4. HIGH — `employee_statutory`/`employee_bank` don't exist

Payroll-blocking by design (locked decision A2), not an oversight — but still a hard gate. Fully
specified, zero code (§14, §21).

### 5. HIGH — Assignment-branch legal entity vs. employment legal entity is unconstrained

No invariant enforces that `employee_assignment.branch.legal_entity_id` matches the employee's
current `employment.legal_entity_id`. Payroll's employer-of-record and Attendance's site can
silently disagree.

### 6. HIGH — FR-ORG-014 retrofit still pending

Branch/Department/Designation/Grade deactivation still skips the "blocked by active employees"
check, with stale "Employee doesn't exist" comments in `organisation/service.py`, despite Employee
having shipped. Locked as a small follow-up PR (A5) that has not happened.

### 7. HIGH — RBAC data-scope is entirely unenforced

`require_permission()` always returns `DataScope(level=COMPANY)`; every route discards it. Any
role with `EMPLOYEE.VIEW` can read any employee in the tenant — there is no Reporting-Manager-
scoped-to-own-team behavior anywhere in the running system, despite it being the headline
distinction the RBAC catalogue design (`docs/product/19 §2`) claims `VIEW` vs `VIEW_ALL` provides.

### 8. HIGH — Personal contact fields leak past their documented classification

`personal_email`/`personal_mobile` are `SENSITIVE`-classified in `docs/product/19 §6`, gated by a
documented `EMPLOYEE.VIEW_PERSONAL_CONTACT` permission — that code doesn't exist in the seeded
catalogue, and the fields are returned on every `EmployeeRead` response unconditionally.

### 9. MEDIUM — Hire is not a single transaction

`PRE_JOINING` employees with zero `employment` rows are a reachable, realistic state given the
current two-call hire flow. Not incorrect, but worth a facade endpoint before Employee UI ships.

### 10. MEDIUM — Seat-limit enforcement has a TOCTOU race

Check-then-insert, no DB-level constraint. Two concurrent employee creates can both pass the seat
count check.

### 11. MEDIUM — No CI-enforced per-module import contract

`.importlinter` enforces the layer ordering (`modules → shared → core`) but nothing stops
`employee.service` from importing `organisation.repository` directly. Convention + review only.

### 12. MEDIUM — `sensitive_access_log` doesn't exist

Locked to build in E-10; zero code. Every RESTRICTED-field read (currently: Compensation) is
unlogged. This gap widens every time a new RESTRICTED table ships without it.

### 13. MEDIUM — No encryption applied to `_enc`-suffixed columns

`pan_number_enc`, `aadhaar_number_enc`, (planned) `account_number_enc` are plain string columns.
The naming convention implies a guarantee the code doesn't provide.

### 14. MEDIUM — No idempotency-key mechanism, no general rate limiting

Both documented as required (money/attendance/approval POSTs; per-user/per-tenant limits). Neither
exists beyond the one registration-endpoint rate limiter.

### 15. MEDIUM — Device Ingestion service is an unmounted scaffold

`ingestion/routes.py` exists, is never imported by `app.py`. The documented 4-deployable topology
is, in practice, a 1-deployable system today.

### 16. MEDIUM — Background jobs / outbox pattern is entirely prospective

No `outbox_event` table, no module `tasks.py`, no Beat schedule. Fine today (nothing needs async
side effects yet); will need real design attention the moment Leave/Attendance/Payroll introduce
their first genuinely-async side effect (accrual, notification fan-out, pay-run compute).

### 17. LOW — `display_name` never computed; `is_rehire` column omitted (derived from
`previous_employment_id` instead — functionally equivalent, a naming-only gap); CHECK-constraint
vs. Pydantic-`Literal` inconsistency between `employment.status` (DB-enforced) and
`employee_assignment.change_type`/`employee_compensation.revision_type` (application-enforced
only); `cost_centre_id` dangling with no FK target table; `holiday_calendar`/`holiday` stub tables
unused; doc/schema column-name drift (§7) not yet corrected in the source docs themselves.

---

## 37. Technical Debt

Distinct from architectural gaps (§36) in that these are cleanup items, not correctness risks:

- Stale "Employee doesn't exist" code comments in `organisation/service.py` and `LegalEntity`'s
  model docstring, now inaccurate.
- `docs/database/Database_Architecture.md` cites `scripts/sql/002_row_level_security.sql` as live
  — it isn't; the dev-facing companion doc has drifted from the authoritative
  `docs/product/08_Database_Architecture.md` and from actual practice.
- Column-name drift between `docs/product/08` and the live schema (§7 table) — five confirmed
  mismatches, none blocking, all worth a documentation correction pass.
- `docs/product/19_RBAC_and_Permission_Matrix.md`'s permission-code naming disagrees with shipped
  code in two already-resolved-in-favor-of-code instances (`ORG.ENTITY.MANAGE` vs. the shipped
  `ORG.LEGAL_ENTITY.MANAGE`; `ATTENDANCE.SHIFT_MANAGE` vs. the shipped `ORG.SHIFT.MANAGE`) — the
  doc itself should be corrected to match, not left silently inconsistent for a future reader who
  trusts the doc over the code.
- `docs/product/VERSION_1_ROADMAP.md §5` still describes Organisation/Employee as "not started" —
  stale against the current build state.

---

## 38. Product Decisions Still Required

See Appendix B for the consolidated list. Summarized by theme here:

- **Employment status vocabulary is locked in code** (`ACTIVE`/`TERMINATED`, no stored
  `ON_NOTICE`) via `docs/modules/employee/07_EMPLOYMENT_STATUS_DECISION.md`'s own recommended
  "Option B" — but that document itself frames this as a recommendation pending product sign-off,
  not a closed loop. Treat the *code* as the current fact; treat the *choice* as still
  product-owned if it needs to change.
- **`EMPLOYEE.VIEW_STATUTORY`/`EMPLOYEE.VIEW_BANKING` exact names** — recommended, not confirmed,
  by the architecture-decisions doc (A9) and the E-07 plan (§21 below); "safe to finalize
  immediately... not a blocker," per that document's own framing.
- **Legal-entity source of truth for a working day** — employment vs. branch, unconstrained today
  (§10, §36 item 5).
- **BR-14/FR-EMP-018 override-chain mechanism** (company→branch→department→grade→employee
  cascading default for shift/notice-period/leave-entitlement) — deliberately deferred, no
  buildable spec exists yet, spans five already-shipped modules plus Attendance/Leave.
- **`pf_number` carry-forward on rehire** — undecided (E-07 plan §8/§22 item 4); no default
  invented.
- **Fiscal-year boundary for the once-per-FY tax-regime-switch rule** — India-centric April–March
  assumed as a reasonable default but not confirmed, and itself downstream of the still-unconfirmed
  "India-only payroll" scoping question (`docs/product/26_Risk_Register_Open_Questions_and_Change
  _Control.md` Q1/A1).
- **Whether `EMPLOYEE.UPDATE` should be allowed to flip `is_active`** via the general PATCH path,
  given a dedicated `.DEACTIVATE` code already exists on `DELETE` — currently both paths work,
  unclear if intentional.
- **RLS-context resolution order across the middleware/dependency boundary** (§17's OPEN item) —
  worth an explicit, direct verification pass per route before higher-stakes modules (Payroll)
  add write paths.
- **Data-scope enum shape** — expand the live 3-level `DataScopeLevel` to the documented 8, or
  formally narrow the documented target to match reality (§16).

---

## 39. Recommended Implementation Sequence

Unchanged in substance from `docs/architecture/00_SYSTEM_ARCHITECTURE_AUDIT.md §20`, restated
here as the authoritative sequence for this document:

```text
[done]  Organisation masters: Company → Legal Entity → Branch → Department → Designation →
        Grade → Shift
[done]  Employee: identity (E-01), employment (E-03), assignment+shift (E-04/E-05),
        compensation (E-06)
[next]  Fix terminate → close assignment + compensation at last_working_day (§36 item 1) —
        service + test change only, no schema change required
        → E-07 Statutory (fully planned, docs/modules/employee/
          21_EMPLOYEE_STATUTORY_IMPLEMENTATION_PLAN.md — see §21 below)
        → E-08 Banking (+ documents/dependents/education/experience/skills)
        → (in parallel) Employee UI primitives: PermissionGate/usePermission, paginated
          DataTable, as-of control, Timeline — all prerequisite to E-09, none Employee-specific
        → FR-ORG-014 retrofit into Branch/Department/Designation/Grade (§36 item 6)
        → Holiday calendar + week-off (Organisation follow-up, or Attendance's own first slice)
        → Attendance capture + as-of status resolution
        → Leave (ledger) + approval-engine skeleton
        → Payroll (policies/structure → pay run, ADR-0005), gated on E-07/E-08 + the
          terminate fix
```

**Do not start Attendance before the terminate fix.** Do not start Payroll before E-07/E-08 exist
**and** the terminate fix is in place **and** inter-entity transfer is a new-employment-row
operation (or a documented, audited, correction-only exception is agreed).

---

## 40. Current Next Step

**Fix `EmploymentService.terminate_employment`** to close the current `employee_assignment` and
`employee_compensation` rows (`effective_to = last_working_day`) in the same transaction as the
`TERMINATED` status write, then update the rehire integration tests that currently assert the
opposite (gap-spanning `effective_to` set by the *next* write instead of by terminate itself).
This is additive, does not require a schema change (both tables already have `effective_to`), and
is the one item every downstream module (Attendance, Payroll) implicitly assumes is already true.

**Then, in order:** E-07 Statutory → E-08 Banking, using the already-fully-specified plan at
`docs/modules/employee/21_EMPLOYEE_STATUTORY_IMPLEMENTATION_PLAN.md` (its own first action:
confirm the `EMPLOYEE.VIEW_STATUTORY` permission-code name with product if a fast answer is
available, otherwise proceed with the documented default and flag it as an assumption — the same
discipline this document asks every future implementer to follow).

---

## Appendix A — Architectural Invariants

1. RLS is a backstop; every repository query also filters `company_id` explicitly.
2. Effective-dated child tables key on `employee_id`, never `employment_id`; a change is an
   insert, never an edit of a business column on an existing row.
3. `employee.id`/`employee_code` are never reissued.
4. Money is `BIGINT` minor units + `currency`, never a float, never computed client-side.
5. A finalised payroll run is immutable; corrections are forward-only arrears.
6. Statutory rates are effective-dated data, never a code constant.
7. Cross-tenant access is always `404`, never `403`.
8. Cross-module imports go through `service.py`/`schemas.py`/`events.py` only.
9. No Person layer above Employee.
10. GiST exclusion constraints make overlapping "current" rows structurally impossible for
    `employment`, `employee_assignment`, `employee_compensation` (and, once built,
    `employee_statutory`/`employee_bank`) — do not remove or work around these constraints at the
    application layer.

## Appendix B — Open Decisions

1. `employment.status` vocabulary — code has decided (`ACTIVE`/`TERMINATED`), product sign-off on
   that choice not independently confirmed.
2. `EMPLOYEE.VIEW_STATUTORY`/`EMPLOYEE.VIEW_BANKING` literal permission-code names.
3. Legal-entity source of truth for a working day (employment vs. branch) — currently
   unconstrained.
4. BR-14/FR-EMP-018 cascading-default override chain — mechanism, storage location, resolution
   order.
5. `pf_number` carry-forward behavior on rehire.
6. Fiscal-year boundary for the tax-regime-switch rule; downstream of the "India-only payroll"
   scoping question.
7. Whether `EMPLOYEE.UPDATE` should be permitted to flip `is_active` alongside the dedicated
   `.DEACTIVATE` code.
8. RLS-context resolution order guarantee across `TenancyMiddleware` → `get_tenant_context` →
   `get_session` for every route — needs an explicit verification pass, not assumed safe by this
   document.
9. Data-scope enum shape — reconcile the live 3-level `DataScopeLevel` against the documented
   8-level target.
10. Whether `is_active` (account lock) or `employment` as-of (employment fact) should gate
    `EMPLOYEE_SEATS` billing counts — currently `is_active`, meaning a terminated-but-still-active
    identity occupies a paid seat.

## Appendix C — Do Not Implement Yet

- A generic effective-dating framework or polymorphic history table.
- `employment_id`-keyed FKs on assignment/compensation/statutory/bank.
- The BR-14 cascading shift/notice/leave override chain (deferred, no spec).
- `sensitive_access_log`'s schema (the decision to build it in E-10 is locked; its shape is not).
- Payroll writing back into Employee/Attendance/Leave history for any reason.
- A second UAN column on `employee_statutory`.
- Client-side money computation of any kind.
- A hard-coded April–March fiscal-year boundary without flagging the India-only-payroll dependency.
- Attendance's holiday/week-off resolution assuming `holiday_calendar`/`holiday` are populated —
  they are empty stubs today.
- Salary disbursement via the payment-gateway integration (billing only, by explicit design).

## Appendix D — Next Implementation Steps

1. Fix `terminate_employment` to close assignment + compensation (§40).
2. E-07 Statutory (plan exists, zero code) — `docs/modules/employee/
   21_EMPLOYEE_STATUTORY_IMPLEMENTATION_PLAN.md`.
3. E-08 Banking + Documents/Dependents/Education/Experience/Skills.
4. Frontend primitives: `PermissionGate`/`usePermission`, paginated `DataTable`, as-of control,
   Timeline — before or in parallel with E-09, not folded silently into it.
5. FR-ORG-014 retrofit into Branch/Department/Designation/Grade.
6. Holiday calendar + week-off (Organisation follow-up or Attendance's first slice).
7. Attendance: population = employment-as-of; shift/branch = assignment-as-of; NULL shift = no
   shift, not an error.
8. Leave: ledger (ADR-0004), approval-engine skeleton.
9. Payroll: gated on E-07/E-08 existing, the terminate fix, and inter-entity transfer becoming a
   new-employment-row operation.

## Appendix E — Module Dependency Graph

(Reproduced from §5 for standalone reference.)

```text
core (db, tenancy, rbac, audit, auth, errors, observability, config)
  ▲
identity ──► organisation ◄── employee (via organisation.service)
                  │                │
                  ▼                ▼
         attendance (planned)  employee.service is the only import surface for
                  │             attendance/leave/payroll once they exist
                  ▼
            leave (planned)
                  │
                  ▼
           payroll (planned) ◄── employee.service, organisation.service,
                                  attendance (planned), leave (planned)
                                  — reads only, never writes back
```

## Appendix F — Current System Status

**Build state:** Organisation (Company→Shift, 7 entities) + Employee (identity, employment,
assignment+shift, compensation) are shipped, tested, and internally consistent. Employee's
sub-slices E-02/E-07/E-08/E-09/E-10 are unbuilt. Attendance, Leave, Payroll, Recruitment,
Onboarding, Exit, Workflow, Notification, AI, Reporting, Integration are entirely unbuilt — DOC
only. Frontend covers Organisation only; zero Employee screens.

**Readiness verdict:** **YELLOW.** Safe to continue Employee (Statutory → Banking) and to plan
Attendance's design. **Not yet safe to begin Attendance implementation** until the terminate/
history-close fix (§36 item 1, §40) lands — this is a real, code-level defect against the locked
lifecycle model, not a theoretical risk. Not yet safe to begin Payroll until E-07/E-08 exist, the
terminate fix is in place, and inter-entity transfer stops being an in-place mutation.

**Foundational patterns — GREEN.** Identity/episode/placement/pay separation, effective-dating
with structural overlap prevention, RLS tenant isolation, optimistic concurrency, and the
module-boundary discipline are coherent, consistently applied across every shipped slice, and
should not be redesigned. Everything else in this document is either "build it, following the
existing pattern" or "explicitly decide it, don't infer it."
