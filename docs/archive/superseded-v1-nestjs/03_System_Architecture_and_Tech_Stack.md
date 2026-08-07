# Document 03 — System Architecture & Technology Stack

---

## 1. Architecture Overview

### 1.1 Style Decision: Modular Monolith → Selective Services

**Decision:** Build a **modular monolith** for Phase 1, with three separately deployed services
carved out from day one because they have genuinely different scaling and failure profiles:

1. **Core API** (monolith, all business modules)
2. **Worker/Job service** (same codebase, different process — payroll runs, imports, reports, notifications)
3. **Device Ingestion service** (biometric push endpoints — high volume, must stay up when the API is deploying)
4. **AI service** (Python — resume parsing, ML scoring, LLM orchestration)

**Rationale.** Microservices for a 22-module HRMS built by a team of 8–14 is a well-documented way
to fail: distributed transactions across leave→attendance→payroll are brutal, and the domain
boundaries are not yet known. A modular monolith with **enforced internal module boundaries**
(each module exposes a service interface; cross-module DB access is banned and lint-enforced)
gives us the option to extract services later when we actually have the scaling evidence.

**Extraction candidates for Phase 3:** Payroll engine (CPU-bound bursts), Attendance ingestion
(already separate), Reporting/analytics (already on read replica), Notification dispatcher.

### 1.2 High-Level Diagram

```
                        ┌──────────────────────────────────────────┐
   Web (Next.js)        │              CloudFront CDN              │
   Mobile (RN)          └──────────────────┬───────────────────────┘
   Careers page                            │
   Biometric devices ──────────┐           ▼
   3rd-party webhooks ─────┐   │   ┌────────────────┐
                           │   └──▶│   WAF + ALB    │
                           │       └───────┬────────┘
                           │               │
              ┌────────────▼───────┐   ┌───▼──────────────┐   ┌──────────────────┐
              │ Device Ingestion   │   │   Core API       │   │  AI Service      │
              │ Service (Node)     │   │  (NestJS)        │◀─▶│  (FastAPI)       │
              │ - push protocol    │   │  22 modules      │   │  parsing/scoring │
              │ - dedupe, buffer   │   │  RBAC, tenancy   │   │  LLM gateway     │
              └────────┬───────────┘   └───┬──────────┬───┘   └────────┬─────────┘
                       │                   │          │                │
                       ▼                   ▼          ▼                ▼
                 ┌──────────────────────────────────────────────────────────┐
                 │            Redis  (cache · sessions · BullMQ)            │
                 └───────────────────────────┬──────────────────────────────┘
                                             │
              ┌──────────────────────────────▼───────────────────────────┐
              │   Worker Service (BullMQ consumers)                       │
              │   payroll · accrual · imports · reports · notifications   │
              │   device sync · scheduled jobs · AI batch                 │
              └──────────────────────────────┬───────────────────────────┘
                                             │
       ┌─────────────────────┬───────────────┼──────────────┬────────────────────┐
       ▼                     ▼               ▼              ▼                    ▼
┌─────────────┐      ┌──────────────┐  ┌───────────┐  ┌────────────┐   ┌─────────────────┐
│ PostgreSQL  │      │ Read Replica │  │    S3     │  │OpenSearch  │   │ External APIs   │
│  primary    │─────▶│  (reports)   │  │documents  │  │ (search,   │   │ SMS·WhatsApp·   │
│  + RLS      │      │              │  │  + KMS    │  │  logs)     │   │ Email·Payment·  │
└─────────────┘      └──────────────┘  └───────────┘  └────────────┘   │ Tally·Calendar  │
                                                                        └─────────────────┘
```

### 1.3 Request Lifecycle (every authenticated request)

```
1. WAF / rate limit           → block abuse, per-IP and per-tenant limits
2. TLS termination at ALB
3. Auth middleware            → verify JWT, load user, resolve active company_id
4. Tenant context middleware  → set request-scoped tenant; SET LOCAL app.company_id (drives RLS)
5. Entitlement guard          → is this module enabled on the tenant's plan?
6. Permission guard           → does the role hold the required permission key?
7. Data-scope resolver        → compute the accessible employee-id set / org filter
8. Controller → Service       → business logic (module-internal only)
9. Repository                 → query with tenant + scope predicates; RLS as backstop
10. Field-level masking       → strip RESTRICTED fields the role cannot see
11. Response serialisation    → DTO, never raw entity
12. Audit interceptor         → write audit entry for mutations & sensitive reads
```

Layers 4, 6, 7 and 10 are the security core. Each is independently unit-tested and covered by an
automated cross-tenant leakage suite (Doc 13 §6).

---

## 2. Technology Stack

### 2.1 Recommended Stack

| Layer | Choice | Why |
|-------|--------|-----|
| **Language (backend)** | TypeScript / Node 20 LTS | One language across API, workers, web and mobile; large Indian hiring pool; excellent async I/O for a notification/integration-heavy product |
| **Backend framework** | NestJS 10 | Opinionated modular structure that *forces* the module boundaries this design depends on; DI, guards, interceptors map exactly to the request lifecycle above |
| **ORM** | Prisma (primary) or TypeORM | Prisma for type-safety and migrations; note: raw SQL used for payroll aggregation and reports |
| **Database** | PostgreSQL 16 | RLS for tenancy, JSONB for custom fields, window functions for attendance/payroll, exclusion constraints for effective-dated overlap prevention, partitioning for punches |
| **Cache / Queue** | Redis 7 + BullMQ | Session, permission cache, rate limiting, job queue with retries and scheduling |
| **Search** | OpenSearch | Employee & candidate search, resume full-text, log analytics |
| **File storage** | S3 + SSE-KMS | Documents, payslips, resumes; presigned URLs only |
| **AI service** | Python 3.12 + FastAPI | Ecosystem for parsing (spaCy, pdfplumber), ML (scikit-learn, XGBoost), and LLM SDKs |
| **Web frontend** | Next.js 14 (React 18) + TypeScript | SSR for the careers page (SEO), CSR for the app; mature ecosystem |
| **UI library** | Tailwind CSS + shadcn/ui + TanStack Table/Query | Fast, consistent, good data-grid support (HRMS is 60% tables) |
| **Mobile** | React Native (Expo bare) | Code sharing with web logic, one team; native modules where needed for biometric/geo |
| **PDF generation** | Puppeteer (HTML→PDF) in the worker | Payslips, letters, reports; template = HTML, easy for tenants to customise |
| **Excel** | ExcelJS (write), SheetJS (read) | Import/export |
| **Auth** | Custom JWT + Passport; SSO via SAML/OIDC libs | Full control over the multi-tenant session model |
| **Infrastructure** | AWS ap-south-1 (Mumbai), ECS Fargate or EKS, RDS, ElastiCache, S3, SQS/Redis, CloudFront | Data residency in India; managed services keep the ops team small |
| **IaC** | Terraform | Reproducible environments |
| **CI/CD** | GitHub Actions | Build, test, scan, deploy |
| **Observability** | OpenTelemetry → Grafana Cloud / Datadog; Sentry for errors | Tracing across API→worker→DB is essential for payroll debugging |

### 2.2 Alternative Stacks (if the client's team differs)

| If the team is… | Backend | Notes |
|---|---|---|
| PHP shop | **Laravel 11** + Filament for admin | Excellent for this domain; queues, scheduler, policies map well. Use Postgres, not MySQL, or lose RLS and exclusion constraints. |
| Java shop | **Spring Boot 3** + JPA | Best for enterprise/on-prem deals; heavier team cost |
| Python shop | **Django 5 + DRF** | Django admin accelerates internal tooling; Celery for jobs |
| .NET shop | **ASP.NET Core 8** | Fine; strong for enterprise on-prem |

The **data model (Doc 04), API contracts (Doc 05) and RBAC design (Doc 06) are stack-independent**
and remain valid under any of these.

### 2.3 Explicitly Rejected

| Rejected | Reason |
|---|---|
| MongoDB as primary store | Payroll and attendance are relational and demand transactional integrity and constraint enforcement. Document DBs make effective-dated joins and audit reconciliation painful. |
| MySQL | No Row-Level Security, weaker exclusion constraints, weaker JSONB and window-function ergonomics for this workload. |
| Full microservices in Phase 1 | Team size and unknown domain boundaries; distributed transactions across leave→attendance→payroll. |
| Flutter *and* React Native | Pick one. RN recommended only because the web is React; if the mobile team is stronger in Flutter, choose Flutter and accept no code sharing. |
| Serverless (Lambda) for the core API | Payroll runs are long and CPU-bursty; cold starts and 15-min limits fight the workload. Fine for webhooks and scheduled tasks. |
| Client-side salary computation | Never. All money maths server-side. |

---

## 3. Multi-Tenancy Design

### 3.1 Model: Shared DB, Shared Schema, Row-Level Security

Every tenant-owned table carries a non-null `company_id` with a foreign key and an index.
PostgreSQL RLS policies are enabled on every such table:

```sql
ALTER TABLE employee ENABLE ROW LEVEL SECURITY;
ALTER TABLE employee FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON employee
  USING (company_id = current_setting('app.company_id')::uuid);
```

The application sets `SET LOCAL app.company_id = '<uuid>'` at the start of every transaction. If
a developer forgets a `WHERE company_id = ?`, RLS still returns zero rows. **Defence in depth:**
application predicate + RLS + a CI check that every new table has RLS enabled + an automated
leakage test suite.

### 3.2 Tenant Tiers

| Tier | Isolation | When |
|---|---|---|
| Standard | Shared DB + RLS | Default; SME |
| Dedicated schema | Separate schema, same cluster | Mid-market with contractual isolation clauses |
| Dedicated database | Separate RDS instance | Enterprise, regulated, or >10k employees |
| On-premise | Customer infrastructure | Phase 3 only, separate commercial SKU |

The codebase must be identical across tiers; only the connection-resolution strategy differs.
Build the **tenant connection resolver** abstraction in Phase 1 even though only the standard tier
ships — retrofitting it later is a rewrite.

### 3.3 Noisy-Neighbour Controls
- Per-tenant rate limits on API and on expensive operations (report generation, exports, AI calls)
- Payroll runs queued with per-tenant concurrency = 1, global concurrency capped
- Query timeouts: 5s for interactive, 15 min for background
- Storage and notification quotas per plan, enforced and alerted at 80%

---

## 4. Module Boundaries Inside the Monolith

```
src/
├── core/                  # framework: tenancy, auth, rbac, audit, config, errors
├── shared/                # value objects (Money, DateRange, EffectivePeriod), utils
├── modules/
│   ├── identity/          # users, sessions, mfa, sso
│   ├── organisation/      # company, entity, branch, department, designation, grade, holiday
│   ├── employee/          # employee, assignment, compensation, document, lifecycle
│   ├── recruitment/       # requisition, opening, candidate, interview, offer
│   ├── attendance/        # punch, shift, roster, attendance-day, regularisation, ot
│   ├── leave/             # type, policy, ledger, application, accrual
│   ├── payroll/           # component, structure, statutory, payrun, payslip, fnf
│   ├── onboarding/
│   ├── exit/
│   ├── performance/
│   ├── workflow/          # engine, definitions, instances, approvals
│   ├── notification/      # events, templates, channels, dispatch
│   ├── task/
│   ├── asset/ expense/ helpdesk/ learning/ visitor/ experience/
│   ├── reporting/         # report definitions, builder, exports
│   └── integration/       # device, accounting, calendar, messaging adapters
└── jobs/                  # BullMQ processors
```

**Boundary rules (enforced by ESLint `no-restricted-imports` + a dependency-cruiser config in CI):**
1. A module may import from `core/` and `shared/` freely.
2. A module may import **only the public `*.service.ts` interface** of another module — never its
   repositories, entities or internal services.
3. No module may query another module's tables directly.
4. Cross-module side effects go through **domain events** on the queue, not direct calls, where the
   operation is asynchronous by nature (e.g. `LeaveApproved` → attendance recompute → payroll flag).
5. Circular module dependencies fail the build.

### 4.1 Key Domain Events

| Event | Emitted by | Consumed by |
|---|---|---|
| `EmployeeJoined` | employee | onboarding, leave (accrual), payroll, asset, notification |
| `LeaveApproved` / `LeaveCancelled` | leave | attendance (recompute), payroll (LOP), notification |
| `AttendanceDayRecomputed` | attendance | payroll (input staleness flag) |
| `PayRunFinalised` | payroll | notification (payslips), accounting export, leave (encashment ledger) |
| `OfferAccepted` | recruitment | onboarding, employee (pre-joining record) |
| `ExitFinalised` | exit | identity (disable), asset (recovery), payroll (F&F), workflow (reassign) |
| `CompensationRevised` | employee | payroll (arrears detection), notification |
| `WorkflowCompleted` | workflow | originating module callback |

Events are persisted (outbox pattern) before publishing — never fire-and-forget for anything that
touches money or compliance.

---

## 5. Attendance Ingestion Architecture (the high-volume path)

Attendance punches are 10–100× the volume of any other write. They get their own path.

```
Biometric device ──HTTP push──▶ Ingestion Service ──▶ Redis Stream ──▶ Punch Writer
                                     │                                     │
                                 validate device key                  batch insert into
                                 dedupe (device+emp+ts)               punch (partitioned by month)
                                 buffer if DB slow                         │
                                                                           ▼
                                                              Attendance Day Recompute Job
                                                              (debounced per employee per date)
```

- `punch` table is **partitioned by month**; partitions older than 24 months move to cold storage.
- Recompute is **debounced**: multiple punches for the same employee/date within 60s trigger one
  recompute, not five.
- The ingestion service must accept punches even when the core API is deploying — devices do not
  retry indefinitely and lost punches are lost wages.
- Sizing: 5,000 employees × 4 punches/day ≈ 20k writes/day per tenant — trivial individually, but at
  500 tenants it is 10M/day, which is why this path is separated and partitioned from day one.

---

## 6. Payroll Execution Architecture

Payroll is the one place where correctness beats every other concern.

```
Finalise-safe pipeline (each step checkpointed and resumable):

1. CREATE RUN         → lock period, snapshot employee list
2. SNAPSHOT INPUTS    → copy compensation, attendance summary, leave, arrears, loans,
                        statutory master versions INTO payrun_input_snapshot (immutable)
3. COMPUTE            → parallel across employee batches (chunk 200), pure functions,
                        no shared mutable state; each result stores a calculation trace
4. VALIDATE           → run all FR-PAY-015 checks; produce exception list
5. VARIANCE           → compare to previous run; flag > threshold
6. REVIEW             → human approval gate (cannot be skipped)
7. FINALISE           → write payslips, mark immutable, emit PayRunFinalised
8. OUTPUTS            → payslip PDFs, bank file, statutory files, JV (all async)
```

**Non-negotiables:**
- Step 2 snapshot means a later change to a master record cannot silently alter a computed run.
- Computation is a **pure function** of the snapshot → deterministic, unit-testable against a
  golden dataset of real payroll cases (BRD D1).
- A crash mid-run is resumable from the last checkpoint; a partially computed run is never visible.
- Every payslip line stores `{formula, inputs, intermediate, result}` for explainability (FR-PAY-024).
- Target: 5,000 employees computed in ≤10 minutes.

---

## 7. Caching Strategy

| What | Where | TTL | Invalidation |
|---|---|---|---|
| User permissions & data scope | Redis | 60s | On role/assignment change |
| Tenant config & feature flags | Redis + in-process | 5 min | On write, pub/sub broadcast |
| Org master data (dept, designation, branch) | In-process LRU | 10 min | On write |
| Statutory master (dated) | In-process | 1 hour | On write |
| Employee list for dropdowns | Redis | 5 min | On employee change |
| Report results | S3 + Redis pointer | Per report definition | Manual/scheduled |
| Session | Redis | Token lifetime | On logout/revoke |

**Never cache:** leave balances, attendance status for today, payroll figures, approval states.
These are the values employees dispute; stale reads create support tickets.

---

## 8. Failure Modes & Resilience

| Failure | Behaviour |
|---|---|
| Database primary down | API returns 503 with a maintenance page; workers pause; punches buffer in Redis Stream for up to 6 hours |
| Redis down | Sessions fall back to DB lookup (degraded); job queue halts with alert; punch ingestion writes direct to DB |
| S3 unavailable | Uploads fail gracefully with retry; existing document links degrade to a "temporarily unavailable" message |
| SMS/WhatsApp provider down | Jobs retry with backoff; failover to secondary provider; email fallback for critical notifications |
| AI service down | Resume parsing queues; ATS remains fully usable with manual entry — **no AI feature is on a critical path** |
| Biometric device offline | Alert after 2 hours; punches replay on reconnect; employees may use the mobile app as fallback if policy allows |
| Payroll job crash | Resume from the last checkpoint; the run stays in a non-final state; alert to the tenant admin and platform ops |
| Third-party calendar/ERP failure | Queue and retry; surface a status indicator; never block the HR operation |

**Principle:** no external dependency may block a core HR operation. Degrade, queue, and alert.

---

## 9. Environments

| Env | Purpose | Data | Access |
|---|---|---|---|
| Local | Development | Seeded synthetic | Developers |
| Dev | Integration of feature branches | Seeded synthetic | Team |
| QA/Test | Full regression, automation | Anonymised realistic dataset | QA + devs |
| UAT/Staging | Client & pilot-customer acceptance; production-like infra | Anonymised client data | Client, QA, PM |
| Production | Live | Real | Ops (break-glass), no direct DB write access |
| DR | Warm standby, cross-AZ + cross-region backups | Replica | Ops only |

**Rule:** production data is never copied to a lower environment without irreversible anonymisation
(names, emails, phones, PAN, Aadhaar, bank, salary all synthesised — salary especially, because it
is the most damaging leak and the most commonly overlooked).

---

## 10. Performance Targets

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

## 11. Key Architecture Decision Records (ADR summary)

| ADR | Decision | Status |
|---|---|---|
| ADR-001 | Modular monolith over microservices for Phase 1 | Accepted |
| ADR-002 | PostgreSQL with RLS for multi-tenancy | Accepted |
| ADR-003 | Effective-dated (temporal) modelling for all employee attributes | Accepted |
| ADR-004 | Leave balance as an append-only ledger, never a stored counter | Accepted |
| ADR-005 | Payroll inputs snapshotted; finalised runs immutable | Accepted |
| ADR-006 | Money as integer minor units + decimal library, never floats | Accepted |
| ADR-007 | Separate ingestion service for biometric punches | Accepted |
| ADR-008 | Workflow engine as a generic shared service, not per-module approvals | Accepted |
| ADR-009 | AI features are strictly non-blocking; every AI path has a manual fallback | Accepted |
| ADR-010 | UTC storage, company-timezone rendering, company-timezone business-day boundaries | Accepted |
| ADR-011 | Statutory rates as effective-dated data, never code | Accepted |
| ADR-012 | Outbox pattern for domain events touching money or compliance | Accepted |

Each ADR should be written up in full (context / decision / consequences / alternatives) in
`/docs/adr/` in the repository during Sprint 0.
