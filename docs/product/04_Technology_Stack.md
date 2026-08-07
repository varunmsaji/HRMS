# Document 04 — Technology Stack

**Version:** 2.0 — new document, split out from the original Document 03 §2 ("System Architecture &
Technology Stack") so that stack decisions can evolve independently of architecture narrative, per
the increased complexity of a 500+ API / 100+ table / 20+ module system. See
[Document 03 — System Architecture](03_System_Architecture.md) for how these pieces fit together and
[Document 00](00_README_Document_Index.md) for the full document map.

---

## 1. Official Stack

| Layer | Choice | Why |
|---|---|---|
| **Language (backend)** | Python 3.12+ | Single language across API, background workers, device ingestion and AI/ML — the entire backend surface (Document 01 §2). Python 3.12 brings meaningful async performance improvements over 3.10/3.11 and is the floor for current SQLAlchemy 2.x / FastAPI feature support. |
| **Backend framework** | FastAPI (latest stable, pinned) | Native async, dependency-injection model (`Depends`) that maps cleanly onto the guard/interceptor pipeline this design depends on (Document 07 §3), automatic OpenAPI generation from Pydantic models with zero extra annotation layer, and the best-in-class async ecosystem fit for a notification/integration-heavy product. |
| **ASGI server** | Uvicorn (worker processes) behind Gunicorn's process manager in production (`gunicorn -k uvicorn.workers.UvicornWorker`) | Gunicorn supervises worker processes (restart on crash, graceful reload); Uvicorn provides the actual ASGI event loop. Standard, boring, well-understood combination. |
| **ORM** | SQLAlchemy 2.x, async mode (`AsyncSession`, `asyncpg` driver) | The mature choice for complex relational schemas (100+ tables, effective-dated exclusion constraints, window functions, partitioned tables) — Document 08 needs raw SQL escape hatches for payroll aggregation and reporting, and SQLAlchemy Core gives that without leaving the ORM's transaction/session management. |
| **Migrations** | Alembic | The standard SQLAlchemy migration tool; autogenerate for routine schema changes, hand-written migrations for anything involving RLS policies, exclusion constraints, or partitioning (none of which Alembic autogenerate detects). |
| **Validation / serialisation** | Pydantic v2 | Native to FastAPI; used for request/response schemas, settings management (`pydantic-settings`), and internal domain value objects (Money, DateRange — Document 07 §6). Pydantic v2's Rust core (`pydantic-core`) makes validation fast enough for hot paths like punch ingestion. |
| **Database driver** | `asyncpg` | The fastest PostgreSQL driver available for async Python; used under SQLAlchemy's async engine. |
| **Database** | PostgreSQL 16 | Unchanged from v1.0: RLS for tenancy, JSONB for custom fields, window functions for attendance/payroll, exclusion constraints for effective-dated overlap prevention, partitioning for punches, **pgvector** for AI embeddings/RAG (Document 12). |
| **Cache** | Redis 7 | Session cache, permission/data-scope cache, rate limiting, distributed locks (Document 03 §7). |
| **Background jobs** | **Celery** + Redis (broker & result backend) | See §3 below for the full comparison. Chosen for monitoring maturity (Flower), first-class OpenTelemetry instrumentation, and canvas primitives (chains/groups/chords) that map directly onto the multi-step, checkpointed payroll pipeline (Document 08 §3) and the workflow engine's system-action chaining (Document 20 §7). |
| **Search** | OpenSearch | Unchanged: employee & candidate search, resume full-text, log analytics. |
| **File storage** | Amazon S3 (production) + **MinIO** (local development, S3-compatible) + SSE-KMS | Documents, payslips, resumes; presigned URLs only. MinIO lets a solo developer run a fully offline-capable local environment without an AWS account, via `boto3`/`aioboto3` against a MinIO endpoint using the same S3 API calls used in production — no storage-layer code fork between environments. |
| **AI / ML** | FastAPI (same codebase — see Document 12) + OpenAI, Claude and Gemini SDKs (hosted LLM APIs) + local models for classification/scoring + Sentence Transformers (embeddings) + scikit-learn / XGBoost (classical ML: matching, anomaly detection, attrition) + OCR (resume parsing) | Was always Python; now shares the same process family, dependency set, and — where appropriate — the same SQLAlchemy models and DB session as the rest of the backend (Document 12 §2). |
| **Web frontend** | Next.js 14 (React 18) + TypeScript | **Unchanged.** SSR for the careers page (SEO), CSR for the app; mature ecosystem. The frontend/backend language split (TS frontend, Python backend) is normal and not the complexity this migration targets — the complexity removed was *two backend languages*, not frontend/backend separation, which every serious web stack has. |
| **UI library** | Tailwind CSS + shadcn/ui + TanStack Table + TanStack Query | **Unchanged.** |
| **Mobile** | React Native (Expo, bare workflow) | **Unchanged.** |
| **PDF generation** | WeasyPrint or a headless-Chromium HTML→PDF service (Playwright's Python bindings), run inside a Celery task | Payslips, letters, reports; template = HTML/Jinja2, easy for tenants to customise. WeasyPrint is pure-Python and avoids shipping a Chromium binary in the worker image where template complexity allows; fall back to Playwright for templates needing full CSS/JS rendering fidelity. |
| **Excel** | `openpyxl` (write) / `polars` or `pandas` + `openpyxl`/`python-calamine` (read) | Import/export, bulk operations. |
| **Auth** | Custom JWT (`python-jose` or `authlib`) + `passlib`/`argon2-cffi` for password hashing; SAML/OIDC via `python3-saml` / `authlib` | Full control over the multi-tenant session model (Document 10). |
| **Infrastructure** | AWS ap-south-1 (Mumbai), ECS Fargate, RDS, ElastiCache, S3, CloudFront | **Unchanged.** Data residency in India; managed services keep the ops footprint small for a solo-maintained system. |
| **IaC** | Terraform | **Unchanged.** |
| **CI/CD** | GitHub Actions | **Unchanged** as the platform; pipeline steps change from `npm`/`jest` to `uv`/`pytest` (Document 13). |
| **Observability** | OpenTelemetry → Grafana Cloud (traces, metrics, dashboards); Sentry for error tracking | **Unchanged** as platforms. OpenTelemetry's Python auto-instrumentation for FastAPI, SQLAlchemy and Celery is mature and gives tracing across API→queue→worker→DB out of the box — this is essential for payroll debugging (Document 03 §1.3) and was one of the deciding factors for Celery over lighter-weight queues (§3). |

### 1.1 Python Tooling (new — did not exist in the v1.0 stack)

| Concern | Choice | Why |
|---|---|---|
| Dependency management | `uv` | Fast, single-binary, lockfile-based (`uv.lock`), replaces `pip` + `pip-tools` + `virtualenv` with one tool. `pyproject.toml` is the single source of truth for dependencies, matching the role `package.json` played before. |
| Linting & formatting | `Ruff` | Replaces ESLint + Prettier's role: one fast tool for linting and formatting, run in pre-commit and CI. |
| Static typing | `mypy` (strict mode on `core/`, `shared/`, and all new modules) | Python's type hints plus `mypy` give a meaningful fraction of what TypeScript's compiler gave the previous stack; not equivalent, but the closest practical substitute, and enforced in CI the same way `tsc --noEmit` was. |
| Module boundary enforcement | `import-linter` | Replaces `dependency-cruiser`. Contracts defined in `pyproject.toml` / `.importlinter` enforce the module boundary rules in Document 07 §3 (a module may import `core/` and `shared/` freely, and only another module's public service interface — never its repository or ORM model classes) — checked in CI, build fails on violation. |
| Testing | `pytest` + `pytest-asyncio` + `httpx.AsyncClient` (in-process ASGI testing) + `Testcontainers` (Python) for real Postgres/Redis in integration tests | Replaces Jest + Supertest. Document 15 has the full testing strategy. |
| Pre-commit hooks | `pre-commit` framework running Ruff, mypy (fast subset), and secret-scanning | Catches issues before they reach CI. |

---

## 2. Explicitly Rejected

| Rejected | Reason |
|---|---|
| **NestJS / Node.js / TypeScript backend** (the previous stack) | Superseded by this decision (Document 01 §2). Not rejected on technical merit — it was a sound choice for a multi-engineer team — but it is the wrong choice for a single Python-fluent developer building AI-heavy features, because it forces permanent context-switching between two languages, two type systems, and two dependency ecosystems for no benefit once there is no separate frontend/backend/ML team to divide along language lines. |
| **Django + Django REST Framework** | A credible alternative (Document 03 v1.0 listed it as the "Python shop" fallback). Rejected in favour of FastAPI because: native async support in DRF is still bolted-on rather than foundational; FastAPI's Pydantic-based validation and automatic OpenAPI generation are a better fit for a 500+ endpoint contract-first API; and Django's batteries (admin site, ORM, forms) solve problems this system already solves differently (a purpose-built RBAC/tenancy layer, not Django's admin or auth app). Django remains a reasonable choice for a team that values its admin site for internal tooling — noted for the record, not pursued. |
| **MongoDB / any document DB as the primary store** | Unchanged reasoning: payroll and attendance are relational and demand transactional integrity and constraint enforcement; document DBs make effective-dated joins and audit reconciliation painful. |
| **MySQL** | Unchanged reasoning: no Row-Level Security, weaker exclusion constraints, weaker JSONB and window-function ergonomics for this workload. |
| **Full microservices for Phase 1** | Unchanged reasoning, and *more* true for a solo developer: distributed transactions across leave→attendance→payroll and the operational overhead of running multiple services are both worse ideas with one person to operate them than with a team of 8–14. |
| **Django-Q, Huey, or a hand-rolled Redis queue** | Considered and rejected for the background-job role — see the comparison in §3. |
| **Serverless (Lambda) for the core API** | Unchanged reasoning: payroll runs are long and CPU-bursty; cold starts and execution-time limits fight the workload. Fine for occasional webhook receivers, not the core API. |
| **Client-side salary computation** | Never. All money maths server-side. Unchanged. |

---

## 3. Background Job System — Comparison and Decision

The original Node.js stack used BullMQ. Python has four realistic candidates. This system's
background workload includes CPU-bursty payroll computation with checkpointed multi-step pipelines
(Document 08 §3), high-volume notification fan-out (Document 20 §9), scheduled jobs (Document 11
§4), and AI batch processing (Document 12) — a genuinely demanding mix, not just "send an email
later."

| | **Celery** | Dramatiq | ARQ | RQ |
|---|---|---|---|---|
| Async-native | No (workers are process/thread-based; async tasks run via `asyncio.run` inside a sync worker) | Partial | Yes (built on `asyncio` + `redis.asyncio`) | No |
| Broker options | Redis, RabbitMQ, SQS, others | Redis, RabbitMQ | Redis only | Redis only |
| Complex workflows (chains, groups, fan-out/fan-in, retries with backoff) | **Best-in-class** — `canvas` primitives (`chain`, `group`, `chord`) purpose-built for exactly the checkpointed multi-step payroll pipeline this system needs | Good, less expressive than Celery's canvas | Minimal — designed for simple job queues, not workflow orchestration | Minimal |
| Scheduled/periodic tasks | `celery beat` — mature, supports database-backed schedules | Needs a separate scheduler (e.g. APScheduler) | Built-in cron-like scheduling | Needs `rq-scheduler` (community, less maintained) |
| Monitoring | **Flower** (web dashboard: task history, worker status, queue depth, retries) + first-class OpenTelemetry instrumentation | Basic; no equivalent to Flower | Minimal | `rq-dashboard` (basic) |
| Ecosystem / maturity | Oldest, most widely deployed in production Python systems; largest body of operational knowledge to draw on solo | Younger, smaller community | Younger still, smallest community | Mature but effectively in maintenance mode |
| Operational complexity | Higher — more configuration surface, more moving parts (result backend, broker, beat) | Lower | Lowest | Low |
| Fit for this system | **Best fit.** The payroll pipeline (create → snapshot → compute → validate → variance → review → finalise → outputs, Document 08 §3) is a textbook Celery `chain`; per-tenant concurrency=1 payroll queues are a `chord`/rate-limit pattern Celery handles natively; the notification fan-out is a `group`. | Good fit for simpler task needs; would need custom orchestration code for the payroll pipeline that Celery gives for free | Best fit if the workload were mostly simple async tasks with light orchestration — it is not | Not competitive for this workload |

**Decision: Celery + Redis (broker and result backend).** The added operational complexity relative
to ARQ or Dramatiq is real, but it buys exactly the three things this system needs most: monitoring
visibility for a solo operator who has no team to watch dashboards in shifts, mature multi-step
workflow orchestration for payroll and workflow-engine system actions, and first-class
OpenTelemetry tracing that lets a single developer debug a failure that spans API → queue → worker
→ database without guessing. If future evidence shows Celery's operational overhead is not earning
its keep for a specific narrow workload (e.g. simple fire-and-forget notification sends), that
workload can move to a lighter mechanism without disturbing the payroll/workflow pipelines — this
is a per-queue decision, not all-or-nothing.

RabbitMQ was considered as the broker instead of Redis and rejected for Phase 1: Redis is already a
required dependency (cache, sessions, rate limiting), and running one fewer stateful service matters
more for a solo-operated system than RabbitMQ's stronger delivery guarantees, which this system
compensates for via the outbox pattern (ADR-0012, unchanged) and idempotent task design
(Document 11 §5).

---

## 4. Stack-Independent Design Layers (unchanged by this migration)

The following remain true regardless of backend language, exactly as stated in the original
Document 03 v1.0 §2.2: **the data model (Document 08), API contracts (Document 09) and RBAC design
(Document 19) are stack-independent.** If a future strategic decision ever moves the backend again,
these three documents would not need to change in substance — only their implementation-detail
sections would.
