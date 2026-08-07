# Document 27 — Architecture Migration Summary (NestJS → FastAPI)

**Version:** 1.0
**Date:** 2026-08-03
**Audience:** Developer, future contributors, AI coding assistants
**Purpose:** Single checklist of what changed in the v2.0 documentation set, every architectural
decision made during the migration, repo artefacts still pending code migration, and what to read
before writing the first line of production FastAPI code.

This document closes the documentation audit requested when the backend stack was changed from
NestJS/Node.js to Python/FastAPI. Documents 01–16 are the **updated source of truth**; v1.0
documents are archived at [`docs/archive/superseded-v1-nestjs/`](.superseded_v1/) and must not be used for
implementation.

---

## 1. Executive Summary

| Before (v1.0) | After (v2.0) |
|---|---|
| NestJS/Node.js core API + separate Python FastAPI AI service | **Single Python 3.12+ codebase** — API, workers, ingestion, AI/ML |
| Prisma + Prisma Migrate | **SQLAlchemy 2.x (async) + Alembic** |
| BullMQ on Redis | **Celery + Redis** (broker and result backend) |
| ESLint + dependency-cruiser + Jest + Supertest | **Ruff + import-linter + pytest + httpx** |
| `npm` / `package.json` backend deps | **`uv` / `pyproject.toml`** |
| 16 documents, shallow backend architecture detail | **27 documents** — backend architecture, auth, jobs, AI, DevOps, security, testing split for AI-assist clarity |
| 8–14 person team delivery model | **Single developer, AI-assisted** delivery model |

**Business scope, data model, API contracts, RBAC matrix, workflow engine, integrations, and NFR
targets are unchanged in substance.** Only implementation mechanics and delivery assumptions
changed.

---

## 2. Architectural Decisions (Official)

| ID | Decision | Rationale | Document / ADR |
|---|---|---|---|
| D-01 | Modular monolith, not microservices for Phase 1 | Payroll/leave/attendance transactional integrity; solo ops | Doc 03, ADR-0001 |
| D-02 | Python 3.12+ / FastAPI as sole backend language | Single developer, AI/ML native, existing expertise | Doc 01 §2, Doc 04, ADR-0013 |
| D-03 | SQLAlchemy 2.x async + `asyncpg` + Alembic | 100+ tables, raw SQL for payroll, RLS via hand migrations | Doc 08, ADR-0015 |
| D-04 | Celery + Redis (not ARQ/Dramatiq/RQ) | Payroll `chain`/`chord`, Flower monitoring, OTel instrumentation | Doc 04 §3, Doc 11, ADR-0014 |
| D-05 | One Docker image, four entrypoints | `api`, `ingestion`, `worker`, `beat` — same deps, one CI build | Doc 06 §2, Doc 13 §2 |
| D-06 | FastAPI `Depends()` dependency injection | Replaces NestJS guards/providers; session-per-request via `AsyncSession` | Doc 07 §2 |
| D-07 | Layered modules: router → service → repository → models | Enforced by `import-linter` | Doc 06 §3, Doc 07 §1 |
| D-08 | Multi-tenancy: `company_id` + Postgres RLS + `SET LOCAL` | Tenant context at lowest layer | Doc 03 §2, Doc 07 §5, ADR-0002 |
| D-09 | Outbox pattern for money/compliance events | At-least-once relay via Celery sweep task | Doc 07 §7, ADR-0012 |
| D-10 | Pydantic v2 for API + settings + value objects | Native FastAPI; replaces class-validator DTOs | Doc 04, Doc 07 §6 |
| D-11 | MinIO locally, S3 in cloud | Offline local dev without AWS account | Doc 04 §1, Doc 13 §5 |
| D-12 | OpenAPI auto-generated from FastAPI; contract tests in CI | Replaces hand-maintained spec drift risk | Doc 09 §8 |
| D-13 | AI modules in-process (same package), not separate HTTP service | Removes Node↔Python boundary (retired risk R-26) | Doc 12, Doc 21 |
| D-14 | Gunicorn + Uvicorn workers in production | Process supervision + async ASGI | Doc 04 §1 |
| D-15 | `structlog` JSON logs + `contextvars` correlation ID | API → Celery → worker trace in logs | Doc 07 §8, Doc 13 §3 |

**Rejected:** NestJS backend (superseded), Django REST (Doc 04 §2), RabbitMQ as Celery broker
Phase 1 (Doc 04 §3), separate AI microservice for Phase 1 (Doc 12 §2).

---

## 3. Document Change Register

### 3.1 Documents rewritten or newly created (backend migration)

| Doc | Title | Migration action | NestJS/Node assumptions removed |
|---|---|---|---|
| 00 | Document Index | Rewritten | Old read order, A6 stack, v1 file names |
| 01 | Product Vision | New (extracted) | Two-language backend rationale added |
| 03 | System Architecture | Rewritten | NestJS deployables diagram, BullMQ workers |
| 04 | Technology Stack | New (split) | NestJS/Prisma/BullMQ as official stack |
| 05 | Development Standards | New | ESLint/Jest/dependency-cruiser as backend standards |
| 06 | Folder Structure | New | NestJS `src/modules/*.module.ts` tree |
| 07 | Backend Architecture | New | Guards, modules, Prisma service injection |
| 08 | Database Architecture | Migrated + tooling | Prisma schema/migrate as primary path |
| 09 | API Standards | Migrated + FastAPI notes | NestJS interceptor/envelope implementation |
| 10 | Authentication Architecture | New | Passport guards, NestJS auth module |
| 11 | Background Job Architecture | New | BullMQ queues, repeatable jobs |
| 12 | AI Architecture | New | Separate FastAPI AI service boundary |
| 13 | DevOps Architecture | New (split) | `npm` CI, Node OTel packages |
| 14 | Security Architecture | New (split) | Prisma middleware encryption pattern |
| 15 | Testing Strategy | Full replacement | Jest/Supertest as backend test stack |
| 16 | Deployment Strategy | New (split) | Prisma migrate in deploy checklist |
| 27 | This summary | **New** | — |

### 3.2 Documents renumbered, substance unchanged (stack-independent)

| Doc | Title | Migration action |
|---|---|---|
| 02 | PRD | Renumbered from BRD §2–11; cross-refs updated |
| 17 | SRS Phase 1 | Renumbered from 02A |
| 18 | SRS Phase 2 & 3 | Renumbered from 02B |
| 19 | RBAC & Permission Matrix | Renumbered from 06 |
| 20 | Workflow Engine | Renumbered from 07; Celery dispatch notes only |
| 21 | AI Feature Spec | Renumbered from 08; §3 points to Doc 12 |
| 22 | Integration Specification | Renumbered from 09 |
| 23 | NFR & Compliance | Split from old Doc 10 |
| 24 | UI/UX & Design System | Renumbered from 11 (frontend unchanged) |
| 25 | Project Plan | Reworked for solo/AI delivery |
| 26 | Risk Register | Reworked; R-26 retired, R-24/R-25 added |

### 3.3 Archived (do not implement)

All files in [`docs/archive/superseded-v1-nestjs/`](.superseded_v1/) — original indices 00–15.

---

## 4. Per-Document Audit Notes (Condensed)

For each primary document, the audit found the following **categories of invalid content** under
v1.0 and how v2.0 addresses them.

### 01 Product Vision
- **Issues:** Vision tied to NestJS + separate AI service; team-scale delivery implicit.
- **Changes:** Stack decision as strategic product/engineering choice; solo + AI-assisted explicit.
- **Impact:** Sets context for Doc 25, 05, 26.

### 02 PRD
- **Issues:** None material (business layer).
- **Changes:** Renumbering and cross-references only.

### 03 System Architecture
- **Issues:** Multi-service diagram (Node ingestion, NestJS API, FastAPI AI); BullMQ worker box.
- **Changes:** Four Python entrypoints; Celery workers; unified package diagram.
- **Impact:** ADR-0013–0015; Doc 13 ECS task definitions.

### 04 Technology Stack
- **Issues:** NestJS/Prisma/BullMQ as official; no Python tooling section.
- **Changes:** Full stack table; Celery comparison matrix; `uv`/Ruff/mypy/import-linter.

### 05 Development Standards
- **Issues:** TypeScript/NestJS coding standards only.
- **Changes:** Python style, async session rules, PR checklist, AI guardrails.

### 06 Folder Structure
- **Issues:** One-level NestJS sketch insufficient at scale.
- **Changes:** Full `apps/api/src/hrms/` module anatomy, `entrypoints/`, `alembic/`, `tests/`.

### 07 Backend Architecture
- **Issues:** No FastAPI DI, event bus, or `AsyncSession` lifecycle spec.
- **Changes:** Layer rules, `Depends` graph, outbox, audit interceptor pattern, error envelope.

### 08 Database Architecture
- **Issues:** Prisma-centric migration and model conventions.
- **Changes:** SQLAlchemy models, Alembic workflow, RLS SQL in migrations, lazy-load pitfalls.

### 09 API Standards
- **Issues:** Implementation assumed NestJS controllers/interceptors.
- **Changes:** Pydantic models, `APIRouter`, response_model, OpenAPI CI validation.

### 10 Authentication Architecture
- **Issues:** Passport/guards/JWT module as NestJS.
- **Changes:** `authlib`, `Depends(get_current_user)`, permission dependencies, SAML/OIDC flow.

### 11 Background Job Architecture
- **Issues:** BullMQ queues and repeatable jobs undocumented for Python.
- **Changes:** Celery queue topology, task design, beat schedule, Flower, idempotency keys.

### 12 AI Architecture
- **Issues:** Peer HTTP service from NestJS core.
- **Changes:** In-package `hrms/ai/` modules, shared DB session, model registry, cost controls.

### 13 DevOps Architecture
- **Issues:** `npm` CI, Node instrumentation, no MinIO in local topology.
- **Changes:** `uv` pipeline, Python OTel, docker-compose full backend stack.

### 14 Security Architecture
- **Issues:** Prisma middleware for field encryption.
- **Changes:** SQLAlchemy `TypeDecorator`, `cryptography` for PAN/Aadhaar columns.

### 15 Testing Strategy
- **Issues:** Jest/Supertest backend tests.
- **Changes:** pytest-asyncio, httpx ASGI client, Testcontainers, golden payroll datasets.

### 16 Deployment Strategy
- **Issues:** Prisma migrate in checklist; BullMQ health checks.
- **Changes:** Alembic review gate, Flower/Celery verification, solo deploy runbook.

---

## 5. ADR Updates

| ADR | Action |
|---|---|
| 0001 | Amended — modular monolith retained, NestJS text removed |
| 0012 | Amended — BullMQ → Celery/Redis in alternatives |
| 0013 | **New** — FastAPI backend decision |
| 0014 | **New** — Celery + Redis job queue |
| 0015 | **New** — SQLAlchemy + Alembic |

All ADRs indexed in [`docs/adr/README.md`](../../docs/adr/README.md).

---

## 6. Repo Artefacts — Current State

The repository matches the FastAPI architecture. Legacy NestJS code and the empty `apps/api-py`
skeleton have been removed.

| Artefact | State |
|---|---|
| `apps/api/` | Python FastAPI scaffold (Sprint 0) — **canonical backend** |
| `apps/web/` | Next.js dev shell |
| `apps/api-py/` | **Removed** (was empty duplicate layout) |
| Root `node_modules/` | **Removed** (stale NestJS npm workspace) |
| `.github/workflows/ci.yml` | Python: ruff, mypy, import-linter, pytest |
| `docker-compose.yml` | Postgres, Redis, MinIO |

Use **Alembic** only for schema changes (Document 08 §14). Do not reintroduce Prisma or a second
API package under `apps/`.

---

## 7. New Documentation Recommended Before Development

| Priority | Document | Why |
|---|---|---|
| P0 | Sprint 0 bootstrap runbook (could live in `apps/api/README.md`) | Step-by-step: `uv sync`, alembic upgrade, celery worker, health URLs |
| P0 | Golden payroll dataset specification (expand Doc 15 §3 into fixture files) | Blocks payroll module sign-off |
| P1 | OpenAPI export + contract-test wiring guide (Doc 09 §8 operational detail) | CI gate for 500+ endpoints |
| P1 | Statutory rates seed format (JSON schema for effective-dated rates) | Payroll + compliance consultant handoff |
| P2 | Contractor onboarding guide (Doc 16 §9 table) | When engaging second developer |
| P2 | Runbook 1 — Payroll failure (Doc 16 §8) | Highest operational risk |

None of these block reading the architecture; they block **safe payroll go-live** and **CI
enforcement** respectively.

---

## 8. Developer Read Order (Post-Migration)

1. [00 Index](00_README_Document_Index.md) → [01 Vision](01_Product_Vision.md) → [02 PRD](02_PRD.md)
2. [03 Architecture](03_System_Architecture.md) → [04 Stack](04_Technology_Stack.md)
3. [06 Folder Structure](06_Folder_Structure.md) → [07 Backend](07_Backend_Architecture.md)
4. Module tables in [08 Database](08_Database_Architecture.md) + SRS [17](17_SRS_Phase1_Core_Modules.md)/[18](18_SRS_Phase2_Phase3_Modules.md)
5. [09 API](09_API_Standards.md) → [19 RBAC](19_RBAC_and_Permission_Matrix.md) → [05 Standards](05_Development_Standards.md)
6. [10 Auth](10_Authentication_Architecture.md) → [11 Jobs](11_Background_Job_Architecture.md) as needed
7. [13 DevOps](13_DevOps_Architecture.md) → [15 Testing](15_Testing_Strategy.md) → [16 Deploy](16_Deployment_Strategy.md)

---

## 9. Migration Notes for Implementers

### 9.1 NestJS concept → FastAPI equivalent

| NestJS | FastAPI / Python |
|---|---|
| `@Module()` | Python package + `APIRouter` registration in `app.py` |
| `@Injectable()` service | Plain class or function; wired via `Depends` |
| `@UseGuards(JwtAuthGuard)` | `Depends(get_current_user)` / `Depends(require_permission(...))` |
| `@Controller()` | `APIRouter` with route decorators |
| Interceptor (response envelope) | Middleware or dependency wrapping response builder |
| Prisma Client | `AsyncSession` + repositories |
| BullMQ queue | Celery task + named queue |
| `class-validator` DTO | Pydantic `BaseModel` |
| `npm run test` | `uv run pytest` |

### 9.2 What not to port

- NestJS module graph and `*.module.ts` files — use Doc 06 layout instead.
- Prisma schema as source of truth — port **table definitions** to SQLAlchemy models; RLS stays in
  Alembic SQL (Doc 08 §1.3).
- BullMQ job definitions — rewrite as Celery tasks with explicit `queue` and `task_id` strategy
  (Doc 11 §5).
- Separate AI HTTP service — implement as `hrms/ai/` submodules (Doc 12 §2).

### 9.3 API contract stability

External clients (web, mobile, integrations) depend on **URLs, request/response JSON, and error
codes** defined in Doc 09 — not on backend language. The v2.0 migration does not change those
contracts unless explicitly noted in Doc 09 change log.

---

## 10. Verification Checklist (Documentation Complete?)

- [x] All 16 requested architecture documents exist in v2.0 form under `docs/product/`
- [x] Stack-independent business docs renumbered and cross-referenced
- [x] ADRs 0013–0015 accepted; 0001 and 0012 amended
- [x] v1.0 archived under `docs/archive/superseded-v1-nestjs/`
- [x] Celery chosen with documented comparison (Doc 04 §3)
- [x] Enterprise FastAPI folder structure and DI specified (Doc 06, 07)
- [x] Multi-tenancy, audit, events, jobs, auth mechanics documented
- [x] Repo scaffold matches docs (Python `apps/api`)
- [x] CI pipeline matches Doc 13 (ruff, mypy, import-linter, pytest)
- [ ] Local docker-compose includes api/worker/beat services — infra only; run API via `uv run uvicorn` locally

---

## 11. Change Log

| Version | Date | Author | Change |
|---|---|---|---|
| 1.0 | 2026-08-03 | — | Initial migration summary closing the NestJS → FastAPI documentation audit |
