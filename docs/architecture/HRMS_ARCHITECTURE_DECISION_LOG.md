# HRMS Architecture Decision Log

**Status:** Architecture review artifact. No application code, schema, migrations, or frontend
code were created or modified to produce this document.

**Date:** 2026-08-15

**Scope of this document:** only decisions that are **actually locked** — either accepted ADRs, or
decisions this codebase's own documentation and running code have already converged on with a
stated rationale. This is **not** a place to record new decisions or to resolve the OPEN items
listed in `docs/architecture/HRMS_SYSTEM_DESIGN_BASELINE.md §19`. Every entry below is either (a)
an existing accepted ADR, cited by number, or (b) a decision confirmed locked by cross-referencing
a `docs/modules/` planning document against the live implementation. Entries are numbered `DEC-NNN`
for stable reference from future implementation tasks.

**How to use this log:** a future implementation task may treat every entry here as settled
without re-deriving it. If an implementation task believes an entry should change, that is itself
a new decision requiring the same rigor as the original — document the proposed change and the
reason, do not silently diverge from a logged decision.

---

## Platform / Infrastructure Decisions

### DEC-001 — Modular monolith, not microservices
**Status:** LOCKED · **Source:** ADR-0001 (amended by ADR-0013)
**Decision:** One deployable Core API containing all business modules, with strictly enforced
internal module boundaries. Four deployables from one codebase (Core API, Device Ingestion,
Worker, Beat) share failure/scaling profiles that differ, not because domain boundaries are
uncertain.
**Scope:** Applies to every future module (Attendance, Leave, Payroll, etc.) — none get their own
service/deployable in Phase 1.

### DEC-002 — PostgreSQL with Row-Level Security for multi-tenancy
**Status:** LOCKED · **Source:** ADR-0002
**Decision:** Shared database, shared schema, `company_id` on every tenant-owned table, enforced by
PostgreSQL RLS as a backstop behind the application-layer predicate. Enterprise/regulated tenants
get a dedicated schema or database on the identical codebase — the connection-resolution strategy
changes, nothing else does.
**Scope:** Every tenant-owned table in every module, present and future.

### DEC-003 — Effective-dated (temporal) modelling for all time-varying employee attributes
**Status:** LOCKED · **Source:** ADR-0003
**Decision:** Any attribute that changes over time lives in its own child table with
`effective_from`/`effective_to`, never as a mutable column. A change is always an insert of a new
row, never an edit of an existing one's core values. Overlapping periods are made structurally
impossible via a GiST exclusion constraint. No generic effective-dating framework — the pattern is
hand-repeated per table.
**Scope:** `employee_assignment`, `employee_compensation` (built); `employee_statutory`,
`employee_bank` (planned, same pattern); any future module's own time-varying attributes.

### DEC-004 — Leave balance as an append-only ledger, never a stored counter
**Status:** LOCKED · **Source:** ADR-0004
**Decision:** `leave_ledger` is append-only — every accrual/deduction/adjustment/encashment/
carry-forward is its own immutable row. Displayed balance is a derived `SUM(days)` over the
ledger, never a column that is decremented/incremented in place.
**Scope:** Leave module (not yet built) — binding on its first implementation.

### DEC-005 — Payroll inputs snapshotted; finalised runs immutable
**Status:** LOCKED · **Source:** ADR-0005
**Decision:** Payroll execution is a checkpointed, resumable pipeline: CREATE RUN → SNAPSHOT INPUTS
→ COMPUTE → VALIDATE/VARIANCE → REVIEW (mandatory human gate) → FINALISE. Once finalised, a run's
results are frozen — corrections are arrears/adjustment components in a **later** run, never edits
to a finalised run's records.
**Scope:** Payroll module (not yet built) — binding on its first implementation.

### DEC-006 — Money as integer minor units + decimal-safe arithmetic, never floats
**Status:** LOCKED · **Source:** ADR-0006
**Decision:** Money is stored as `BIGINT` minor units with an explicit `currency` column. All
financial arithmetic is server-side, decimal-safe, with explicit documented rounding rules per
component. No client-side money computation of any kind.
**Scope:** Every money-bearing column in every module, present and future. Already applied
consistently: `employee_compensation.annual_ctc_minor`, `grade.{min_ctc,max_ctc,approval_limit}`.

### DEC-007 — Separate Device Ingestion service for biometric punches
**Status:** LOCKED (design) · **Source:** ADR-0007
**Decision:** A dedicated Device Ingestion service, deployed and scaled independently from Core
API, sits in front of the biometric push path. Must accept punches even while Core API is
deploying. `punch` table partitioned by month; recompute debounced (60s window).
**Scope:** Attendance module (not yet built). Note: the *code scaffold* for this
(`ingestion/routes.py`) exists but is not mounted — the design decision is locked; the
implementation is not started (see baseline §1.1, §2.3).

### DEC-008 — Workflow/approval engine as one generic shared service
**Status:** LOCKED · **Source:** ADR-0008
**Decision:** One generic workflow/approval engine (`workflow_definition` →
`workflow_version` → `workflow_node` → `approval_request` → `approval_step` → `approval_action`),
configurable per tenant/flow. Every approval-driven flow (leave, attendance regularisation,
compensation revision, exit, etc.) is an instance of this engine, not a bespoke per-module
implementation. This is the one place a generic framework is the *correct* choice — the opposite
default from DEC-003's per-table effective-dating repetition.
**Scope:** Any future approval-gated flow across any module.

### DEC-009 — AI features are strictly non-blocking
**Status:** LOCKED · **Source:** ADR-0009
**Decision:** Every AI-touched workflow has a manual path that fully replaces it. No AI call sits
on the critical path of any core HR operation.
**Scope:** AI module (not yet built) and any future feature that touches it.

### DEC-010 — UTC storage, company-timezone rendering and business-day boundaries
**Status:** LOCKED · **Source:** ADR-0010
**Decision:** All timestamps stored in UTC. `company.timezone` is the single source of truth for
rendering and for computing business-day boundaries (attendance-day resolution, payroll-period
cutoffs) — never UTC midnight, never server-local time.
**Scope:** Attendance and Payroll modules specifically; any timestamp anywhere in the system
generally.

### DEC-011 — Statutory rates as effective-dated data, never code
**Status:** LOCKED · **Source:** ADR-0011
**Decision:** Statutory rates (PF/ESI/PT/TDS/Gratuity/Bonus/LWF) live in `statutory_master`,
itself effective-dated, keyed by jurisdiction and effective period. Payroll computation reads the
rate row effective for the pay period via the input snapshot — never a code constant. A rate
change is a reviewed data operation, not a code deploy.
**Scope:** Payroll module (not yet built) — binding on its first implementation.

### DEC-012 — Outbox pattern for domain events touching money or compliance
**Status:** LOCKED · **Source:** ADR-0012
**Decision:** Events that touch money or compliance are persisted in the same database transaction
as the state change (an outbox table), published to the queue afterward by a separate relay.
Never fire-and-forget for this category of event.
**Scope:** `PayRunFinalised`, `ExitFinalised`, and any similarly compliance-critical future event.
Not yet built (`outbox_event` table does not exist).

### DEC-013 — Python 3.12 / FastAPI backend
**Status:** LOCKED · **Source:** ADR-0013 (amends ADR-0001)
**Decision:** The entire backend — Core API, Worker/Beat, Device Ingestion, AI modules — runs from
one Python codebase. SQLAlchemy 2.x async + Alembic replace Prisma; Celery + Redis replace BullMQ.
An implementation-language decision, not a product or architecture-pattern change — every ADR from
0001–0012 remains in force, reasoning unchanged.
**Scope:** Whole codebase; already fully in effect.

### DEC-014 — Celery + Redis as the background job system
**Status:** LOCKED · **Source:** ADR-0014
**Decision:** Celery (canvas primitives for the payroll pipeline, Flower monitoring, OpenTelemetry
instrumentation, Beat scheduling) + Redis (broker and result backend, already required for
cache/sessions/rate-limiting).
**Scope:** Every future background job across every module. Not yet built beyond the Celery app
instance and one sample task.

### DEC-015 — SQLAlchemy 2.x (async) + Alembic, replacing Prisma
**Status:** LOCKED · **Source:** ADR-0015
**Decision:** SQLAlchemy 2.x in async mode with `asyncpg`, Alembic for migrations. RLS/GiST/
partitioning are hand-written raw DDL in migrations (not expressible in the ORM layer — true under
Prisma too, not a regression). SQLAlchemy Core used directly for payroll aggregation/reporting
queries that need raw SQL.
**Scope:** Whole codebase; already fully in effect.

---

## Employee Domain Decisions

(Source: `docs/modules/employee/05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part A/B — only the items
that document marks **DECIDED**, not the items it marks **REQUIRES PRODUCT DECISION**. Confirmed
still consistent with the live implementation as of this review.)

### DEC-016 — Rehire mechanics: same identity, new employment row
**Status:** LOCKED · **Source:** Employee Architecture Decisions A1/B1/B2, confirmed FACT
**Decision:** A rejoining employee reuses the same `employee.id`/`employee_code`. Rehire is a
**new** `employment` row (`previous_employment_id` linking to the prior spell), never a mutation
of the original row's dates. `employee_assignment`/`employee_compensation`/(planned)
`employee_statutory`/`employee_bank` all key on `employee_id`, never `employment_id` — this is
what makes rehire correct by construction.
**Scope:** Binding on every current and future Employee child table, and on Attendance/Leave/
Payroll's read contracts against Employee.

### DEC-017 — Build `employee_statutory`/`employee_bank` inside Employee's own migration
sequence, not deferred to Payroll
**Status:** LOCKED · **Source:** Employee Architecture Decisions A2/B5/B6
**Decision:** These two tables are built as Employee slices (E-07/E-08), even with no UI surface
until Payroll ships, because no other module is documented as their owner and Payroll cannot be
built correctly without them.
**Scope:** E-07/E-08 implementation, not yet built.

### DEC-018 — BR-14 shift/notice/leave override chain: Employee ships the direct leg only
**Status:** LOCKED · **Source:** Employee Architecture Decisions A3/B8
**Decision:** Employee ships `employee_assignment.shift_id` as a direct, nullable, per-employee
value (E-05). The cascading company→branch→department→grade→employee default-resolution
mechanism is explicitly deferred to a separate, later, cross-module decision — not designed or
built as part of Employee, Attendance, or any single module unilaterally.
**Scope:** Every future consumer of `shift_id` (Attendance foremost) must treat `NULL` as
legitimate — "no shift resolves" — not an error, until that separate decision is made.

### DEC-019 — Full 14-code Employee RBAC catalogue, not the Organisation-style single-permission
shortcut
**Status:** LOCKED · **Source:** Employee Architecture Decisions A4/B9
**Decision:** Employee uses a full resource/action permission catalogue
(`EMPLOYEE.VIEW`/`.VIEW_ALL`/`.CREATE`/`.UPDATE`/etc.), not one bundled `EMPLOYEE.MANAGE` code —
because Employee's own RBAC design explicitly relies on the `VIEW`/`VIEW_ALL` distinction to
separate a Reporting Manager from an HR Manager.
**Scope:** Employee module (built, 9 of the documented codes seeded). Sets precedent for
Attendance/Leave/Payroll's own catalogues, per `docs/product/19_RBAC_and_Permission_Matrix.md
§3.2–3.4`.

### DEC-020 — `EMPLOYEE_SEATS` enforcement point: `EmployeeService.create_employee`
**Status:** LOCKED · **Source:** Employee Architecture Decisions A6
**Decision:** Seat-limit enforcement happens in `EmployeeService.create_employee`, counting active
employees against `plan.employee_seat_limit`, rejecting before insert — not at a higher API-
gateway/billing layer.
**Scope:** Employee's create path (built, though with a known TOCTOU race — baseline §18 M-1, a
separate, still-open hardening item, not a reversal of this decision).

### DEC-021 — Migration approach: extend live stub tables in place, never drop-and-recreate
**Status:** LOCKED · **Source:** Employee Architecture Decisions A7
**Decision:** `employee`/`employment`/`employee_assignment`/`employee_compensation` (and every
Organisation entity before them) are extended via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`,
never dropped and recreated — consistent with every migration in the live history.
**Scope:** Every future migration touching an existing table.

### DEC-022 — `employment.version` added for optimistic concurrency
**Status:** LOCKED · **Source:** Employee Architecture Decisions A7 sub-decision, confirmed FACT
**Decision:** `employment` gets a `version` column like every other mutable table, because a
rehire/terminate is a real mutation needing the same concurrency protection, not an append-only
row.
**Scope:** `employment` table (built, live).

### DEC-023 — Employee is its own top-level module package
**Status:** LOCKED · **Source:** Employee Architecture Decisions A8, `docs/architecture/
01_Backend_Structure.md:70`, `VERSION_1_ROADMAP.md §8` item 3
**Decision:** `apps/api/src/hrms/modules/employee/`, standalone — not folded into `organisation/`.
**Scope:** Sets the structural precedent: Attendance/Leave/Payroll will each also be standalone
packages, not folded into `employee/` or `organisation/`.

### DEC-024 — No Person layer above Employee
**Status:** LOCKED · **Source:** `docs/product/02_PRD.md §11` ("Not modelled. Avoid the word."),
confirmed not reintroduced anywhere in the built code
**Decision:** Employee is the identity root. No separate Person/Candidate-unified table exists or
is planned for V1.
**Scope:** Whole system.

### DEC-025 — Employment status: two stored values, `ACTIVE`/`TERMINATED`; `ON_NOTICE` is
derived, not stored
**Status:** LOCKED (by code) · **Source:** `docs/modules/employee/07_EMPLOYMENT_STATUS_DECISION.md`
§5–§7 (Option B, the document's own recommendation), confirmed FACT — DB `CHECK` constraint on
migration `20260814090000`
**Decision:** `employment.status` is `CHECK`-constrained to exactly `ACTIVE`/`TERMINATED`.
"On notice" is computed from `last_working_day` being set but not yet reached, never a stored
third state. `last_working_day` is set if and only if `status = TERMINATED` (DB-enforced).
**Note on locking status:** the source document itself frames this as a recommendation pending
product sign-off, not originally a closed decision — but the code has already implemented exactly
this choice, and no later document has revised it. This log treats the **code's current behavior**
as locked (any change requires a migration, not a silent doc update); the underlying *product*
sign-off remains listed as still-open in `HRMS_SYSTEM_DESIGN_BASELINE.md §19` for completeness —
this entry resolves the technical shape, not the business sign-off.
**Scope:** `employment.status` everywhere it is read — every future module must not invent or
expect a stored `ON_NOTICE`, `EXITED`, or any value beyond these two.

### DEC-026 — `employee.status` vs. `employment.status` vs. `is_active` are three independent
concepts, never conflated
**Status:** LOCKED · **Source:** `docs/modules/employee/07_EMPLOYMENT_STATUS_DECISION.md §3`,
confirmed FACT
**Decision:** `employee.status` is identity-level (FR-EMP-014's 10-state machine, only
`PRE_JOINING` currently written). `employment.status` is spell-level (DEC-025). `is_active` is an
account lock, orthogonal to employment. No future module may substitute one for another.
**Scope:** Binding on Attendance/Leave/Payroll's population-gate logic — the correct gate is
`get_employment_as_of`, never `employee.status` or `is_active` (also stated as an invariant in
`HRMS_SYSTEM_DESIGN_BASELINE.md §20`).

### DEC-027 — UAN lives on `employee.uan_number` only, never duplicated onto
`employee_statutory`
**Status:** LOCKED · **Source:** `docs/modules/employee/21_EMPLOYEE_STATUTORY_IMPLEMENTATION_PLAN
.md §10`, resolving a genuine conflict between two source documents in favor of the live schema
**Decision:** `employee_statutory` (planned E-07) will **not** have a `uan` column. UAN is a
person-level identifier that does not change per statutory period, correctly modeled once on
`employee`.
**Scope:** E-07's implementation, binding when built.

### DEC-028 — Cross-tenant access always returns 404, never 403
**Status:** LOCKED · **Source:** `docs/product/09_API_Standards.md §1.4`, `docs/database/
Database_Architecture.md §2`, confirmed FACT everywhere tested
**Decision:** A request for a resource that doesn't exist, or belongs to another tenant, always
returns 404 — existence itself is never disclosed to a caller outside the tenant.
**Scope:** Every endpoint in every module, present and future.

### DEC-029 — Effective-dated sub-resources are insert-only via POST, never PATCH
**Status:** LOCKED · **Source:** ADR-0003's consequences, explicitly reconfirmed for Statutory in
`docs/modules/employee/03_EMPLOYEE_API_PLAN.md §2.4` and `21_EMPLOYEE_STATUTORY_IMPLEMENTATION_PLAN
.md §16` (overriding an earlier doc that literally named `PATCH`)
**Decision:** Every effective-dated child resource (Assignment, Compensation, and — when built —
Statutory, Bank) exposes only `POST` for a revision (close-current + insert-new). No `PATCH`/
`DELETE` on an individual historical row.
**Scope:** Every current and future effective-dated resource's API surface.

---

## Cross-Reference

For every decision **not** in this log — including the RBAC data-scope shape, the
`EMPLOYEE.VIEW_STATUTORY`/`.VIEW_BANKING` literal names, the legal-entity-vs-branch invariant, the
holiday/week-off ownership question, the `pf_number` rehire-carry-forward question, and the
fiscal-year-boundary/India-only-payroll scoping question — see
`docs/architecture/HRMS_SYSTEM_DESIGN_BASELINE.md §19` ("Decisions Required"). Those are
deliberately **not** logged here because they are not yet locked.
