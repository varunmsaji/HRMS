# Repository Architecture Audit (Sprint 0)

**Date:** 2026-08-03  
**Scope:** Post-migration cleanup — FastAPI canonical backend at `apps/api/`

---

## 1. Executive summary

| Area | Status | Notes |
|------|--------|-------|
| Backend runtime code | **OK** | Python/FastAPI in `apps/api/src/hrms/` |
| Legacy NestJS backend | **Removed** | No `package.json`, Prisma, or Nest `src/` under `apps/api/` |
| Duplicate `apps/api-py/` | **Removed** | Was empty scaffold |
| Root npm workspace | **Removed** | Stale `node_modules/` + `package-lock.json` deleted |
| Frontend | **OK** | `apps/web/` — Next.js 14 |
| Product specs | **OK** | `docs/product/` v2.0 (FastAPI); v1.0 archived in `docs/archive/superseded-v1-nestjs/` |
| CI | **OK** | `.github/workflows/ci.yml` — ruff, mypy, import-linter, pytest |
| Docker | **OK** | Postgres 5433, Redis 6380, MinIO 9000/9001 |
| Developer docs (`docs/`) | **This sprint** | Architecture, database, security, development guides |

---

## 2. Folder structure (current)

```text
HRMS/
├── apps/
│   ├── api/                 # Python backend (canonical)
│   │   ├── entrypoints/     # api, ingestion, worker, beat
│   │   ├── src/hrms/        # application package
│   │   ├── alembic/
│   │   ├── scripts/sql/
│   │   ├── tests/
│   │   └── pyproject.toml
│   └── web/                 # Next.js frontend
├── docs/
│   ├── product/             # Product + engineering spec (source of truth)
│   ├── adr/                 # Architecture Decision Records
│   └── (architecture, design, development, security, sprints...)
├── infra/                   # Postgres init scripts
├── scripts/dev.sh           # One-command local start
└── docker-compose.yml
```

---

## 3. Search results — legacy stack references

| Pattern | Where found | Action |
|---------|-------------|--------|
| NestJS / Nest | `docs/product/` migration docs, `README.md` historical notes | **Keep** — documents migration; not implementation |
| Prisma | `docs/product/`, `docs/adr/0013–0015`, one Alembic comment | **Keep in ADRs**; comment is historical |
| BullMQ | `docs/product/`, `docs/adr/0014` | **Keep** — explains Celery choice |
| `apps/api-py/` | — | **Removed** |
| `@hrms/api` npm package | — | **Removed** with root `node_modules` |
| `dependency-cruiser` | `docs/product/`, superseded v1 | Replaced by `import-linter` in CI |
| TypeScript **backend** | None in `apps/api/` | N/A — frontend TS is correct |

**No actionable NestJS/Prisma runtime artifacts remain in the codebase.**

---

## 4. Configuration audit

| File | Status |
|------|--------|
| `apps/api/.env.example` | OK — pydantic-settings vars |
| `apps/api/.env` | Local only (gitignored) |
| `apps/api/env/*.example` | OK — deployment tier templates |
| `apps/web/.env.local.example` | OK — `NEXT_PUBLIC_API_URL` |
| `docker-compose.yml` | OK — postgres, redis, minio |
| `apps/api/Dockerfile` | OK — multi-stage Python image |
| `apps/api/.importlinter` | OK — module layer contract |

---

## 5. Gaps (intentional — not Sprint 0 blockers)

| Gap | Planned in |
|-----|------------|
| `core/auth/`, `core/rbac/` code | Block B1 (identity) |
| HR modules (`identity`, `employee`, …) | Blocks B1–B12 |
| Seed script (permissions, demo tenant) | Block B1/B2 |
| Cross-tenant security test suite in CI | Block B1 |
| OpenAPI contract snapshot gate | Block B1 |
| Celery worker in `npm run dev` | Optional enhancement |
| `apps/api/env/` templates fully aligned to pydantic field names | B1 |

---

## 6. Recommendations

1. **Do not** recreate `apps/api-py` or a second Python package.
2. **Do not** add NestJS, Prisma, or BullMQ.
3. **Use** `docs/` for how-to-build; **use** `docs/product/` for what-to-build.
4. **Next sprint:** Block B1 — `modules/identity/` + `core/auth/` per [Auth Architecture](../security/Auth_Architecture.md).
