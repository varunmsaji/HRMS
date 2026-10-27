# HRMS Architecture Inventory (audit, read-only)

Audit date: 2026-10-27. Scope: repository at `main` working tree (278 files modified/untracked vs `HEAD 436a2e5`, so findings describe the working tree, not a tagged release) plus **read-only catalog queries** against the local dev Postgres container `hrms-postgres`.

**Evidence levels used throughout the audit**

| Tag | Meaning |
|---|---|
| **[REPO]** | Verified by reading code / migrations / compose files |
| **[DEV-DB]** | Verified by catalog queries (no row data read, `default_transaction_read_only=on`) against the *dev* DB. The dev DB is **empty (0 rows)** and sits at migration `20261022090000`, four revisions behind repo head `20261027092000`. It proves schema shape, not data volume or query plans |
| **[UNVERIFIED]** | Needs a production-like database, load test or human decision |

No production database was available. Nothing was migrated, written or changed.

## 1. Stack (verified)

| Layer | Finding | Evidence |
|---|---|---|
| Backend | FastAPI ≥0.115, Python ≥3.12, modular monolith (`modules/*` with `router/service/repository/models/schemas`), import-linter boundaries | `apps/api/pyproject.toml`, `.importlinter` |
| Server | gunicorn + `UvicornWorker`, `GUNICORN_WORKERS` default **2**, timeout 60 | `apps/api/Dockerfile` CMD |
| DB | PostgreSQL **16** (`postgres:16-alpine`, 16.14 in dev), extensions `pgcrypto`, `btree_gist` | `docker-compose.prod.yml`, `infra/docker/postgres/init/001_extensions.sql`, [DEV-DB] |
| ORM/driver | SQLAlchemy 2 async + `asyncpg` (app), `psycopg` (Alembic) | `core/db/session.py`, `alembic/env.py` |
| Migrations | Alembic, **125** revisions (10.6k lines), first revision loads raw SQL `scripts/sql/001..003*.sql` | `alembic/versions/`, `20260803124757_init_schema.py` |
| Queue | Celery + Redis (broker and result backend); queues `default`, `reports_exports`; one `beat` | `core/celery_app.py`, `docker-compose.prod.yml` |
| Object store | S3 API; prod = MinIO fork `pgsty/silo` pinned by digest; private bucket (`mc anonymous set none`); presigned URLs via a public storage domain | `docker-compose.prod.yml`, `core/storage.py` |
| Auth | Argon2 (`argon2.PasswordHasher`), JWT (access+refresh, `pyjwt`), server-side `session` / `refresh_token` tables with hashed tokens and rotation/family revocation | `core/auth/passwords.py`, `core/db/repositories/identity.py` |
| PII | AES-256-GCM field encryption (PAN, Aadhaar, bank no.), DEKs wrapped by `PII_MASTER_KEY`, `encryption_keys` registry | `core/crypto/*`, `docs/deployment/DISASTER_RECOVERY.md` |
| Frontend | Next.js (`apps/web`), separate container behind Nginx | `docker-compose.prod.yml` |
| Edge | Nginx 1.27 + certbot webroot renewal; `/metrics` returns 404 publicly; 15 MB body cap | `infra/nginx/*` |
| Observability | structlog + file sink, Prometheus multiprocess metrics, Grafana/Prometheus compose file | `core/observability/*`, `docker-compose.monitoring.yml`, `infra/monitoring` |
| CI | GitHub Actions `ci.yml`: ruff, format, mypy, import-linter, Postgres 16 + Redis services, init scripts, `alembic upgrade head`, hrms_app NOBYPASSRLS assertion, unit then integration/security tests, MinIO-backed tests | `.github/workflows/ci.yml` |
| Tests | 283 test files (unit / integration / security) incl. `tests/security/test_rls_runtime_role.py`, `tests/integration/test_route_authorization_matrix.py` | `apps/api/tests` |

Not present [REPO]: Kubernetes, systemd units, PgBouncer, WAL archiving / PITR config, a `postgresql.conf` override, a CD pipeline (CI only), Hostinger-specific scripts, off-server backup upload.

Application modules: `identity`, `account_invite`, `organisation`, `employee`, `employee_import`, `onboarding`, `attendance` (incl. face verification), `leave`, `payroll`, `platform` (operator console), `health`. Core: `tenancy`, `rbac`, `auth`, `audit`, `crypto`, `db`, `observability`, `idempotency`, `storage`, `uploads`.

## 2. Request path (API → DB)

```
Client ─TLS─> Nginx (edge net) ─> gunicorn/Uvicorn (api)
   middleware: RequestContext → Tenancy (reads raw X-Company-Id → ContextVar) → SecurityHeaders → body-size limit
   FastAPI deps: get_current_user (JWT → AuthenticatedUser{user_id, company_id})
                 get_session  ── opens AsyncSession; set_config('app.company_id', <ctx>, is_local=true)
                 get_tenant_context ── header must equal token company; user_company membership checked;
                                       RLS GUC re-set from the *verified* company   (core/tenancy/dependencies.py:12-54)
                 RBAC dependencies (core/rbac) → permission + data-scope
   router → service → repository (SQLAlchemy) ── role hrms_app (NOSUPERUSER, NOBYPASSRLS) ──> Postgres
   RLS policy on 94 tables: company_id = current_setting('app.company_id', true)::uuid     [DEV-DB]
   commit at request end (get_session), then post-commit hooks (core/db/post_commit.py)
```

Background path: Celery task → `run_task()` (new event loop, engine disposed per task, `core/db/session.py:~120`) → list active companies from the (non-RLS) `company` table → `session_scope(company_id=…)` per company (e.g. `modules/leave/tasks.py:88-97`, `modules/attendance/tasks.py:61`).

Pre-login / pre-tenant lookups go through the `SECURITY DEFINER` function `login_lookup_user_companies` (`search_path=public`) [DEV-DB], migration `20260828090000`.

## 3. Deployment topology as coded

`docker-compose.prod.yml` (project `hrms-prod`): `postgres`, `redis` (AOF on), `minio` (+`minio-init`), `api`, `migrate` (profile `tools`, run explicitly), `worker` (concurrency default 2), `beat` (single), `web`, `nginx`, `certbot`. Two networks: `data` (postgres, redis, minio, api, worker, beat) and `edge` (nginx, api, web, minio). Only nginx publishes ports (80/443). Log rotation `10m × 5` per container. `docker-compose.yml` (dev) publishes 5433/6380/9000/9001 on the host — dev only.

## 4. Gaps recorded (verify before launch)

| # | Gap | How to verify |
|---|---|---|
| G1 | No production DB: row counts, bloat, slow queries, real plans unknown | Restore a staging copy; `pg_stat_statements`; `EXPLAIN (ANALYZE, BUFFERS)` |
| G2 | Working tree has 278 uncommitted changes incl. new migrations (`email_outbox`, `attendance_day_tenant_fk`) | Release only from a tagged clean commit; `alembic heads` in CI |
| G3 | Whether `get_current_user` reads any RLS table before membership is verified (GUC is set from the raw header in that window) | Read `core/auth/dependencies.py`; add test with mismatched header |
| G4 | Hostinger region, backup add-on, snapshot policy | Hostinger hPanel at purchase time |
| G5 | Celery `acks_late` is set per-task in `leave/tasks.py:55-56`; not confirmed for attendance/employee tasks | grep task decorators; crash test |
