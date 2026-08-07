# HRMS Platform

Enterprise multi-tenant HRMS — modular monolith on **Python 3.12 / FastAPI**, PostgreSQL 16,
Redis 7, and Celery. The canonical specification lives in [`files/`](files/00_README_Document_Index.md).
Read the document index first; it maps every spec file and lists open client questions that block
specific modules.

**Developer architecture (Sprint 0):** [`docs/README.md`](docs/README.md) — how to build on FastAPI.  
**Product spec:** [`files/00_README_Document_Index.md`](files/00_README_Document_Index.md) — what to build.

**Stack decision (v2.0):** the backend is a single Python codebase (API, workers, device
ingestion, AI/ML) — not NestJS/Node.js. See [Product Vision §2](files/01_Product_Vision.md) and
[Migration Summary](files/27_Architecture_Migration_Summary.md).

## Read order for a new developer

1. [`files/00_README_Document_Index.md`](files/00_README_Document_Index.md) — map and assumptions
2. [`files/01_Product_Vision.md`](files/01_Product_Vision.md) — what and why
3. [`files/03_System_Architecture.md`](files/03_System_Architecture.md) — deployables and tenancy
4. [`files/04_Technology_Stack.md`](files/04_Technology_Stack.md) — official stack
5. [`files/06_Folder_Structure.md`](files/06_Folder_Structure.md) + [`07_Backend_Architecture.md`](files/07_Backend_Architecture.md)
6. [`files/08_Database_Architecture.md`](files/08_Database_Architecture.md) — data model
7. [`files/17_SRS_Phase1_Core_Modules.md`](files/17_SRS_Phase1_Core_Modules.md) — pick your module
8. [`files/09_API_Standards.md`](files/09_API_Standards.md) — REST conventions
9. [`files/19_RBAC_and_Permission_Matrix.md`](files/19_RBAC_and_Permission_Matrix.md) — permissions
10. [`files/13_DevOps_Architecture.md`](files/13_DevOps_Architecture.md) — CI/CD and local dev

Migrating from the archived NestJS docs? Start with [`files/27_Architecture_Migration_Summary.md`](files/27_Architecture_Migration_Summary.md).

## Repo layout (target — Document 06)

```
apps/
  api/          Python/FastAPI backend (sole backend — no NestJS / no api-py)
  web/          Next.js 14 frontend (local dev shell)
docs/adr/       Architecture Decision Records
infra/          Postgres init scripts, Terraform (Document 13)
files/          Canonical spec documents (change control: Document 00 §7)
```

### Scaffold status

`apps/api/` is the **Python/FastAPI Sprint 0 scaffold** (`src/hrms/`, `alembic/`, `entrypoints/`, `uv.lock`).
See [`apps/api/README.md`](apps/api/README.md) for setup and run commands.

## Prerequisites (local development)

- **Python 3.12+** and [`uv`](https://docs.astral.sh/uv/) (backend)
- **Docker** + Docker Compose (Postgres 16, Redis 7, MinIO)
- **Node.js 20+** and **npm** (Next.js frontend)

## One-command local start

Starts Docker (Postgres, Redis, MinIO), runs API migrations, and launches **both** the FastAPI
backend and Next.js frontend:

```bash
npm run dev
# or: ./scripts/dev.sh
```

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| API | http://localhost:8000 |
| OpenAPI | http://localhost:8000/docs |
| MinIO console | http://localhost:9001 |

Logs: `.dev-logs/api.log` and `.dev-logs/web.log`. Press Ctrl+C to stop API and web (Docker keeps
running). Stop infrastructure with `npm run dev:down`.

**Prerequisites:** Docker, `uv`, Node.js 20+, `npm`, `curl`.

## Manual setup (if you prefer step-by-step)

Start infrastructure with Docker Compose:

```bash
# Postgres (host port 5433) + Redis (6380) + MinIO (9000/9001)
npm run dev:up
# or: docker compose up -d
```

Postgres init scripts and RLS conventions: `infra/docker/postgres/init/` and Document 08.

**API setup:**

```bash
cd apps/api
uv sync
cp .env.example .env
uv run alembic upgrade head
uv run uvicorn entrypoints.api:app --reload --port 8000
```

Health check: `GET /health` → `200 {"status":"ok"}` when Postgres and Redis are reachable.

## Environment variables

Committed templates document every tier. Real secrets never go in git (Document 14 §1).

| Tier | Template | Notes |
|---|---|---|
| Local | `apps/api/.env.example` (target) | Wired to docker-compose services |
| Dev / QA / Staging / Prod | [`apps/api/env/`](apps/api/env/README.md) | Reference for SSM / Secrets Manager |

## Engineering principles (non-negotiable)

From Document 00 §6 — stack-independent:

1. **Effective-dated employee data** (ADR-0003)
2. **Immutable payroll outputs** (ADR-0005)
3. **Configuration over code**
4. **Audit every state change** (Document 07 §9)
5. **Tenant isolation at the lowest layer** — `company_id` + RLS (ADR-0002)

Additional repo conventions when Python scaffold lands:

- **Module boundaries** (Document 07 §3): import only another module's `service.py` — enforced by
  `import-linter` in CI.
- **Money** as integer minor units (`BIGINT`) + `currency` column — never floats (ADR-0006).
- **No hard deletes** — `deleted_at` / retention job only.

## Documentation

- Spec set: [`files/00_README_Document_Index.md`](files/00_README_Document_Index.md)
- ADRs: [`docs/adr/`](docs/adr/README.md)
- Archived v1.0 (NestJS) specs: [`files/.superseded_v1/`](files/.superseded_v1/) — do not implement
