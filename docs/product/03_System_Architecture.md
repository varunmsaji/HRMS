# Document 03 — System Architecture

**Version:** 2.0 — rewritten for the Python/FastAPI backend (Document 01 §2). Technology choices
now live in [Document 04](04_Technology_Stack.md); module-internal layering, dependency injection
and folder structure now live in [Document 06](06_Folder_Structure.md) and
[Document 07](07_Backend_Architecture.md). This document keeps the system-level architecture:
deployables, request lifecycle, multi-tenancy, the two highest-risk execution paths (attendance
ingestion, payroll), caching, resilience, and performance targets.

---

## 1. Architecture Overview

### 1.1 Style Decision: One Codebase, Four Deployables

**Decision, unchanged in substance from v1.0:** build a **modular monolith** — one Python codebase
with strictly enforced internal module boundaries (Document 07 §3) — and carve out separately
*deployed* processes only where scaling or failure profile genuinely differs, not where domain
boundaries are merely convenient to draw. What changes in this rewrite is that all four deployables
now come from the **same Python package**, not a two-language split:

| Deployable | Process | What it runs |
|---|---|---|
| **Core API** | `uvicorn` (behind Gunicorn) | The FastAPI app exposing all business-module routers — employee, attendance, leave, payroll, recruitment, workflow, etc. |
| **Device Ingestion service** | `uvicorn`, separate ASGI app, same codebase | A minimal FastAPI app mounting **only** the `/ingest/v1/*` routes (Document 09 §3.9) and their dependencies. Deployed and scaled independently so it survives Core API deploys and traffic spikes (ADR-0007, unchanged rationale). |
| **Worker** | `celery worker` | Consumes the Celery queues: payroll compute, attendance recompute, imports/exports, report generation, notification dispatch, AI batch jobs (Document 11). |
| **Beat / Scheduler** | `celery beat` (single leader-elected instance) | Fires the scheduled jobs in Document 16 §5 (accrual runs, absent-marking, roster generation, retention enforcement, etc.) onto the Celery queues. |

The **AI/ML functionality** (Document 12) is, by default, an **internal module** (`ai/`) inside the
Core API and Worker processes — not a fifth deployable — because it is now the same language and
can share SQLAlchemy models, the DB session, and the auth/tenancy context directly. It keeps an
explicit extraction seam (its own router prefix, its own service interface, no other module
importing its internals) so it can be pulled into a fifth, independently-scaled deployable later if
GPU workloads or LLM-call latency isolation ever require it (Document 12 §1) — exactly the same
"build the seam before you need the service" discipline the original architecture applied to
tenancy.

**Rationale for keeping four deployables instead of collapsing to one:** the reasons the original
architecture split these out were never about language — they were about scaling and failure
isolation, and those reasons are unchanged:
- **Ingestion** must accept biometric punches even while the Core API is mid-deploy or overloaded;
  losing punches means lost wages (Document 03 §5, unchanged).
- **Worker** processes are CPU-bursty (payroll compute) and must scale on queue depth independently
  of API request volume.
- **Beat** must run as exactly one instance; co-locating it with autoscaled API replicas would
  either fire jobs multiple times or require extra leader-election machinery for no benefit.

**Extraction candidates for Phase 3**, unchanged: Payroll engine (CPU-bound bursts), Reporting/
analytics (already on a read replica), Notification dispatcher, and — new in this rewrite — the AI
module if usage justifies dedicated infrastructure.

### 1.2 High-Level Diagram

```
                        ┌──────────────────────────────────────────┐
   Web (Next.js)        │              CloudFront CDN              │
   Mobile (RN/Expo)     └──────────────────┬───────────────────────┘
   Careers page                            │
   Biometric devices ──────────┐           ▼
   3rd-party webhooks ─────┐   │   ┌────────────────┐
                           │   └──▶│   WAF + ALB    │
                           │       └───────┬────────┘
                           │               │
              ┌────────────▼───────┐   ┌───▼──────────────────────┐
              │ Device Ingestion   │   │   Core API               │
              │ Service (FastAPI)  │   │  (FastAPI, Python 3.12)  │
              │ - push protocol    │   │  20+ modules             │
              │ - dedupe, buffer   │   │  RBAC · tenancy · AI     │
              └────────┬───────────┘   └───┬──────────┬──────────┘
                       │                   │          │
                       ▼                   ▼          ▼
                 ┌──────────────────────────────────────────────────────────┐
                 │            Redis 7  (cache · sessions · Celery broker)   │
                 └───────────────────────────┬──────────────────────────────┘
                                             │
              ┌──────────────────────────────▼───────────────────────────┐
              │   Celery Worker(s)  +  Celery Beat (scheduler)            │
              │   payroll · accrual · imports · reports · notifications   │
              │   device sync · scheduled jobs · AI batch                 │
              └──────────────────────────────┬───────────────────────────┘
                                             │
       ┌─────────────────────┬───────────────┼──────────────┬────────────────────┐
       ▼                     ▼               ▼              ▼                    ▼
┌─────────────┐      ┌──────────────┐  ┌───────────┐  ┌────────────┐   ┌─────────────────┐
│ PostgreSQL  │      │ Read Replica │  │ S3/MinIO  │  │OpenSearch  │   │ External APIs   │
│  16, + RLS  │──────▶  (reports)   │  │documents  │  │ (search,   │   │ SMS·WhatsApp·   │
│  + pgvector │      │              │  │  + KMS    │  │  logs)     │   │ Email·Payment·  │
└─────────────┘      └──────────────┘  └───────────┘  └────────────┘   │ Tally·Calendar· │
                                                                        │ OpenAI/Claude/  │
                                                                        │ Gemini          │
                                                                        └─────────────────┘
```

### 1.3 Request Lifecycle (every authenticated request)

```
1. WAF / rate limit           → block abuse, per-IP and per-tenant limits
2. TLS termination at ALB
3. Auth dependency            → verify JWT, load user, resolve active company_id (Document 10)
4. Tenant context middleware  → set request-scoped tenant; SET LOCAL app.company_id (drives RLS)
5. Entitlement dependency     → is this module enabled on the tenant's plan?
6. Permission dependency      → does the role hold the required permission key? (Document 19)
7. Data-scope resolver        → compute the accessible employee-id set / org filter
8. Router → Service layer     → business logic (module-internal only, Document 07 §2)
9. Repository (SQLAlchemy)    → query with tenant + scope predicates; RLS as backstop
10. Field-level masking       → strip RESTRICTED fields the role cannot see (Pydantic response model)
11. Response serialisation    → Pydantic schema, never the raw ORM model
12. Audit dependency/task     → write audit entry for mutations & sensitive reads
```

Layers 4, 6, 7 and 10 are the security core. Each is independently unit-tested and covered by an
automated cross-tenant leakage suite (Document 15 §6). In FastAPI, layers 3, 5, 6, 7 and 12 are
implemented as **dependencies** (`Depends(...)`) composed onto each router, and layer 4 as ASGI
middleware — the full mapping from this pipeline onto FastAPI constructs is in Document 07 §4.

---

## 2. Multi-Tenancy Design

### 2.1 Model: Shared DB, Shared Schema, Row-Level Security — Unchanged

Every tenant-owned table carries a non-null `company_id` with a foreign key and an index.
PostgreSQL RLS policies are enabled on every such table:

```sql
ALTER TABLE employee ENABLE ROW LEVEL SECURITY;
ALTER TABLE employee FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON employee
  USING (company_id = current_setting('app.company_id')::uuid);
```

The application sets `SET LOCAL app.company_id = '<uuid>'` at the start of every transaction —
implemented as a SQLAlchemy `AsyncSession` event hook that runs on transaction begin, sourced from
an async-context-local tenant context (`contextvars`, since Python's `asyncio` does not share
thread-locals across coroutines the way Node's `AsyncLocalStorage` or a synchronous framework's
thread-local would — this is the one place where the language change requires a materially
different implementation technique, detailed in Document 07 §5). If a developer forgets a
`WHERE company_id = ?`, RLS still returns zero rows. **Defence in depth:** application predicate +
RLS + a CI check (via `import-linter` and a schema-introspection test) that every new table has RLS
enabled + an automated leakage test suite (Document 15 §6).

### 2.2 Tenant Tiers — Unchanged

| Tier | Isolation | When |
|---|---|---|
| Standard | Shared DB + RLS | Default; SME |
| Dedicated schema | Separate schema, same cluster | Mid-market with contractual isolation clauses |
| Dedicated database | Separate RDS instance | Enterprise, regulated, or >10k employees |
| On-premise | Customer infrastructure | Phase 3 only, separate commercial SKU |

The codebase must be identical across tiers; only the connection-resolution strategy differs — a
SQLAlchemy async engine/session factory selected per tenant at request time. Build this **tenant
connection resolver** abstraction in Phase 1 even though only the standard tier ships.

### 2.3 Noisy-Neighbour Controls — Unchanged

- Per-tenant rate limits on API and on expensive operations (report generation, exports, AI calls)
- Payroll runs queued with per-tenant concurrency = 1 (a Celery queue-routing + rate-limit pattern), global concurrency capped
- Query timeouts: 5s for interactive (`statement_timeout` set per session), 15 min for background
- Storage and notification quotas per plan, enforced and alerted at 80%

---

## 3. Module Boundaries

Full detail — the layered architecture inside each module, the dependency-injection approach, and
the enforcement mechanism (`import-linter` contracts) — is in **Document 07**. Summary:

1. A module may import from `core/` and `shared/` freely.
2. A module may import **only the public service interface** of another module — never its
   repository, ORM models, or internal services.
3. No module may query another module's tables directly.
4. Cross-module side effects go through **domain events** on the Celery/outbox path, not direct
   calls, where the operation is asynchronous by nature (e.g. `LeaveApproved` → attendance recompute
   → payroll flag).
5. Circular module dependencies fail the CI build (`import-linter`).

The domain event catalogue (`EmployeeJoined`, `LeaveApproved`, `PayRunFinalised`, etc.) is unchanged
from v1.0 and is documented in full in Document 07 §7. Events are persisted (outbox pattern,
ADR-0012, unchanged) before publishing — never fire-and-forget for anything that touches money or
compliance.

---

## 4. Attendance Ingestion Architecture (the high-volume path)

Attendance punches are 10–100× the volume of any other write. They get their own path — unchanged
in design, now implemented as a lightweight FastAPI app rather than a NestJS service:

```
Biometric device ──HTTP push──▶ Ingestion Service ──▶ Redis Stream ──▶ Punch Writer (Celery task)
                                     │                                     │
                                 validate device key                  batch insert into
                                 dedupe (device+emp+ts)               punch (partitioned by month)
                                 buffer if DB slow                         │
                                                                           ▼
                                                              Attendance Day Recompute Task
                                                              (debounced per employee per date)
```

- `punch` table is **partitioned by month**; partitions older than 24 months move to cold storage.
- Recompute is **debounced**: multiple punches for the same employee/date within 60s trigger one
  Celery task, not five — implemented with a Redis-backed debounce key and `apply_async(countdown=…)`.
- The ingestion service must accept punches even when the Core API is deploying — devices do not
  retry indefinitely and lost punches are lost wages.
- Sizing: 5,000 employees × 4 punches/day ≈ 20k writes/day per tenant — trivial individually, but at
  500 tenants it is 10M/day, which is why this path is separated and partitioned from day one.

---

## 5. Payroll Execution Architecture

Payroll is the one place where correctness beats every other concern.

```
Finalise-safe pipeline (a Celery `chain`, each step checkpointed and resumable):

1. CREATE RUN         → lock period, snapshot employee list
2. SNAPSHOT INPUTS    → copy compensation, attendance summary, leave, arrears, loans,
                        statutory master versions INTO payrun_input_snapshot (immutable)
3. COMPUTE            → parallel across employee batches (Celery `group`, chunk 200), pure
                        functions, no shared mutable state; each result stores a calculation trace
4. VALIDATE           → run all statutory checks (Document 17); produce exception list
5. VARIANCE           → compare to previous run; flag > threshold
6. REVIEW              → human approval gate (cannot be skipped)
7. FINALISE            → write payslips, mark immutable, emit PayRunFinalised (outbox)
8. OUTPUTS             → payslip PDFs, bank file, statutory files, JV (all async, Celery `group`)
```

**Non-negotiables, unchanged:**
- Step 2's snapshot means a later change to a master record cannot silently alter a computed run.
- Computation is a **pure function** of the snapshot → deterministic, unit-testable against a
  golden dataset of real payroll cases (Document 15 §3).
- A crash mid-run is resumable from the last checkpoint (Celery `chain` with per-step state
  persisted to `pay_run.checkpoint`); a partially computed run is never visible.
- Every payslip line stores `{formula, inputs, intermediate, result}` for explainability.
- Target: 5,000 employees computed in ≤10 minutes (Document 23 §1).

---

## 6. Caching Strategy — Unchanged

| What | Where | TTL | Invalidation |
|---|---|---|---|
| User permissions & data scope | Redis | 60s | On role/assignment change |
| Tenant config & feature flags | Redis + in-process (`functools.lru_cache` scoped per request/tenant) | 5 min | On write, pub/sub broadcast |
| Org master data (dept, designation, branch) | In-process LRU | 10 min | On write |
| Statutory master (dated) | In-process | 1 hour | On write |
| Employee list for dropdowns | Redis | 5 min | On employee change |
| Report results | S3/MinIO + Redis pointer | Per report definition | Manual/scheduled |
| Session | Redis | Token lifetime | On logout/revoke |

**Never cache:** leave balances, attendance status for today, payroll figures, approval states.
These are the values employees dispute; stale reads create support tickets.

---

## 7. Failure Modes & Resilience — Unchanged

| Failure | Behaviour |
|---|---|
| Database primary down | API returns 503 with a maintenance page; workers pause; punches buffer in Redis Stream for up to 6 hours |
| Redis down | Sessions fall back to DB lookup (degraded); Celery halts with alert; punch ingestion writes direct to DB |
| S3/MinIO unavailable | Uploads fail gracefully with retry; existing document links degrade to a "temporarily unavailable" message |
| SMS/WhatsApp provider down | Tasks retry with backoff; failover to secondary provider; email fallback for critical notifications |
| AI service/module down or LLM provider unavailable | Resume parsing queues; ATS remains fully usable with manual entry — **no AI feature is on a critical path** (Document 12 §1) |
| Biometric device offline | Alert after 2 hours; punches replay on reconnect; employees may use the mobile app as fallback if policy allows |
| Payroll job crash | Resume from the last checkpoint; the run stays in a non-final state; alert to the tenant admin and platform ops |
| Third-party calendar/ERP failure | Queue and retry; surface a status indicator; never block the HR operation |

**Principle:** no external dependency may block a core HR operation. Degrade, queue, and alert.

---

## 8. Environments — Unchanged

| Env | Purpose | Data | Access |
|---|---|---|---|
| Local | Development | Seeded synthetic | Developer (solo — Document 25) |
| Dev | Integration of feature branches | Seeded synthetic | Developer + any contractors |
| QA/Test | Full regression, automation | Anonymised realistic dataset | Developer + QA (if contracted) |
| UAT/Staging | Client & pilot-customer acceptance; production-like infra | Anonymised client data | Client, developer |
| Production | Live | Real | Developer (break-glass), no direct DB write access |
| DR | Warm standby, cross-AZ + cross-region backups | Replica | Break-glass only |

**Rule, unchanged:** production data is never copied to a lower environment without irreversible
anonymisation (names, emails, phones, PAN, Aadhaar, bank, salary all synthesised — salary
especially, because it is the most damaging leak and the most commonly overlooked).

**MinIO note:** Local and Dev environments run MinIO instead of S3 (Document 04 §1), which means a
solo developer can run the entire stack — API, worker, beat, ingestion, Postgres, Redis, MinIO —
with `docker compose up` and no cloud account, closing the loop between "works locally" and "works
in CI" faster than a stack requiring live AWS credentials for local file storage would.

---

## 9. Performance Targets

Unchanged from v1.0 — the language change does not relax these targets; async Python with
`asyncpg` and connection pooling is capable of meeting them, and they remain the acceptance
criteria in Document 15 and Document 23.

| Operation | Target (p95) |
|---|---|
| Login | < 800 ms |
| Dashboard load | < 1.5 s |
| Employee list (50 rows, filtered) | < 600 ms |
| Employee 360° profile | < 1 s |
| Attendance matrix (200 employees × 31 days) | < 2 s |
| Punch ingestion ack | < 200 ms |
| Leave application submit | < 700 ms |
| Payroll compute, 500 employees | < 3 min |
| Payroll compute, 5,000 employees | < 10 min |
| Payslip PDF generation, 500 | < 5 min (async) |
| Report export, 50k rows | < 3 min (async, emailed) |
| Mobile app cold start | < 3 s |
| Mobile punch on 3G | < 2 s |

Concurrency target Phase 1: 500 tenants, 150,000 total employees, 3,000 concurrent users at peak
(9:00–10:00 AM punch spike), 200 requests/sec sustained.

---

## 10. Key Architecture Decision Records (ADR summary)

| ADR | Decision | Status |
|---|---|---|
| ADR-0001 | Modular monolith over microservices for Phase 1 | Accepted (amended — see ADR-0013) |
| ADR-0002 | PostgreSQL with RLS for multi-tenancy | Accepted |
| ADR-0003 | Effective-dated (temporal) modelling for all employee attributes | Accepted |
| ADR-0004 | Leave balance as an append-only ledger, never a stored counter | Accepted |
| ADR-0005 | Payroll inputs snapshotted; finalised runs immutable | Accepted |
| ADR-0006 | Money as integer minor units + decimal library, never floats | Accepted |
| ADR-0007 | Separate ingestion service for biometric punches | Accepted |
| ADR-0008 | Workflow engine as a generic shared service, not per-module approvals | Accepted |
| ADR-0009 | AI features are strictly non-blocking; every AI path has a manual fallback | Accepted |
| ADR-0010 | UTC storage, company-timezone rendering, company-timezone business-day boundaries | Accepted |
| ADR-0011 | Statutory rates as effective-dated data, never code | Accepted |
| ADR-0012 | Outbox pattern for domain events touching money or compliance | Accepted |
| ADR-0013 | Python 3.12 / FastAPI backend, replacing NestJS/Node.js | **Accepted (new)** |
| ADR-0014 | Celery + Redis as the official background job system, replacing BullMQ | **Accepted (new)** |
| ADR-0015 | SQLAlchemy 2.x (async) + Alembic, replacing Prisma | **Accepted (new)** |

ADR-0001 through ADR-0012 are business/architecture decisions that were correctly identified as
stack-independent in v1.0 and remain valid unedited in substance; only ADR-0001's supporting text
(which named NestJS) has been amended. ADR-0013 through ADR-0015 are new and document this
migration's reasoning in full (`/docs/adr/`).
