# HRMS API — Python / FastAPI backend

Sprint 0 scaffold per `files/06_Folder_Structure.md` and `files/07_Backend_Architecture.md`.
Architecture guides: [`docs/README.md`](../../docs/README.md).

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Docker (Postgres, Redis, MinIO from repo root `docker compose`)

## Setup

```bash
# From repo root — infrastructure
docker compose up -d

cd apps/api
cp .env.example .env
# Edit .env if your ports differ

uv sync
uv run alembic upgrade head
uv run python scripts/seed.py   # B1 demo users (admin@example.com / DemoPass123!)
```

## Run locally

```bash
# API (port 8000)
uv run uvicorn entrypoints.api:app --reload --port 8000

# Celery worker
uv run celery -A entrypoints.worker worker --loglevel=info

# Celery beat
uv run celery -A entrypoints.worker beat --loglevel=info

# Device ingestion (separate ASGI app)
uv run uvicorn entrypoints.ingestion:app --reload --port 8001
```

Health: `curl http://localhost:8000/health`

OpenAPI: http://localhost:8000/docs

## Quality gates

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/hrms
uv run lint-imports
uv run pytest
```

## Layout

See `files/06_Folder_Structure.md` — `src/hrms/` is the installable package;
`entrypoints/` are thin deployable roots.
