# Release Hardening — Phase 3B: Production Deployment Infrastructure

Date: 2026-09-25

## Executive Summary

```text
Production status: NOT READY FOR PUBLIC RELEASE
```

This phase built the deployment infrastructure Phase 0–3A explicitly left untouched: production
Docker images, a production Docker Compose stack, Nginx reverse proxy, Let's Encrypt HTTPS,
liveness/readiness health checks, PostgreSQL and MinIO backup-and-restore automation, and the
deployment/disaster-recovery runbooks — all self-hosted (Hostinger VPS), with **no AWS-managed
service introduced anywhere**.

Every component described below was **actually run**, not just written and inspected: both
Docker images were built and booted; the full `docker-compose.prod.yml` stack (8 services) was
brought up end-to-end with a real (locally simulated) HTTPS path through Nginx, including company
registration, login, and an authenticated request; both backup scripts were run against real data
and both restore scripts were run and their output verified byte-for-byte. This surfaced **six
real, previously-undiscovered bugs** — none hypothetical, all fixed and re-verified (§"Bugs found
and fixed").

Closing this phase makes the application *deployable*; it does not by itself change the
still-open application-level release blockers this phase deliberately did not touch (payroll
statutory sign-off, MFA, the remaining SEC-11 `auth`-bucket coarseness, etc. — see
`docs/audits/RELEASE_HARDENING_PHASE_3A_SECURITY_REMEDIATION.md` §17).

## Phase 3A Baseline

Reproduced from `docs/audits/RELEASE_HARDENING_PHASE_3A_SECURITY_REMEDIATION.md` and independently
re-verified against current source before any change:

| Check | Phase 3A result |
| --- | ---: |
| Backend tests (fresh DB) | 1,716 passed / 0 failed / 0 errors |
| Frontend tests (Vitest) | 399 passed / 0 failed |
| Frontend TypeScript | pass |
| Frontend production build | pass |
| Ruff check / format | pass |
| mypy | pass |
| Import lint | 1 kept, 0 broken |

Git state at the start of this phase: branch `main`, HEAD `fb94e25`, 113 files already modified or
new from Phases 1–3A (all uncommitted, per those phases' own "do not commit" instruction) — verified
unchanged from that report's own description before this phase began.

## Current Deployment Audit (before this phase)

| Component | Current implementation | Production-ready? | Action taken |
| --- | --- | --- | --- |
| API Dockerfile | Existed (`apps/api/Dockerfile`), multi-stage, but **had never actually been built** — `uv sync` ran before `README.md`/`src/` existed, which fails outright because `pyproject.toml` declares `readme = "README.md"` | **NO — did not build** | Fixed copy order (`--no-install-project` two-stage pattern), added non-root user, `HEALTHCHECK`, gunicorn CMD |
| Worker/beat/ingestion entrypoints | `apps/api/entrypoints/{worker,beat,ingestion}.py` existed, real Celery app with a real beat schedule (leave accrual, comp-off sweeps, attendance calc) | Partial — never run in Docker | Verified via Compose; found and fixed a beat crash (schedule-file permission) |
| Frontend Dockerfile | **Did not exist** | Missing | Created, multi-stage, `output: "standalone"` |
| `docker-compose.yml` (dev) | postgres/redis/minio only, host ports exposed directly, no app services (API/web run outside Docker via `scripts/dev.py`) | Dev-only, correctly scoped | Left untouched — out of this phase's scope |
| Production Compose | **Did not exist** | Missing | Created `docker-compose.prod.yml` (8 services) |
| Nginx | **Did not exist anywhere in the repo** | Missing | Created `infra/nginx/` |
| HTTPS / Let's Encrypt | **Did not exist** | Missing | Created `certbot` service + webroot issuance/renewal procedure |
| Health endpoints | `/health` existed — DB check only, `redis` field hardcoded `"skipped"`, no liveness/readiness distinction | Partial | Added `/health/live` (no dependency checks) and `/health/ready` (DB + Redis + storage config, 503 on failure) |
| PII encryption key provisioning | `core/crypto/provisioning.py`'s `provision_initial_key` existed but **had no runnable entrypoint** — its own docstring called it "an operator-run step" that nothing actually ran | Missing | Created `apps/api/scripts/provision_encryption_key.py` |
| PostgreSQL backups | **Did not exist** | Missing | Created `infra/backup/pg_backup.sh` + `pg_restore.sh`, both run against real data |
| MinIO backups | **Did not exist** | Missing | Created `infra/backup/minio_backup.sh` + `minio_restore.sh`, both run against real data |
| Logging | `structlog` JSON logging already solid (`core/observability/logging.py`) | Good at the app layer, no rotation/aggregation | Added Nginx JSON access logs + Docker per-container log rotation (`x-logging` anchor, 10m×5 files) |
| Disk/storage monitoring | **Did not exist** | Missing | Documented (`docker system df` etc.) in the runbook; no automated alerting shipped (deferred, §Deferred Items) |
| Production config (`Settings`) | Solid fail-closed guard logic already existed (JWT/CORS/S3/PII key) | Good, but... | ...**a real, previously-undiscovered bug** in how `cors_allowed_origins`/`trusted_proxy_hosts` parse from an actual environment variable — see §Bugs found and fixed |
| `apps/api/env/.env.*.example` | All four files described an **AWS ECS/RDS/ElastiCache/Secrets Manager architecture from an archived, superseded NestJS-era plan** (`docs/archive/superseded-v1-nestjs/14_DevOps_Deployment_and_Operations.md`) — actively contradicting this deployment's stated no-AWS architecture, plus wrong variable names (`JWT_ACCESS_TTL` instead of `JWT_ACCESS_TTL_MINUTES`) and a copy-paste `PORT=3000` (the frontend's port, not the API's) | Actively misleading | Rewrote all four for the actual self-hosted Docker Compose architecture |
| `apps/api/uv.lock` | Stale — still pinned `python-jose` (removed by Phase 3A's DEP-01) and was missing `cryptography` as an explicit dependency despite `core/crypto/field.py`/`master_key.py` importing it directly | **Broken for a reproducible (`--frozen`) build** | Regenerated; added `cryptography` explicitly to `pyproject.toml` |
| Deployment/DR docs | **`docs/deployment/` did not exist** | Missing | Created `PRODUCTION_DEPLOYMENT.md` + `DISASTER_RECOVERY.md` |
| Sentry / external error tracking | Not implemented; explicitly deferred (a single comment: `core/errors/handlers.py:79`, "Sentry hook lands here in a later sprint") | Deferred by design | Confirmed still deferred, not made mandatory (per the brief's own instruction) |

## Bugs found and fixed

All six were found by **actually running** the infrastructure this phase built, not by static
inspection — each is described here with what broke, how it was found, and the fix, since an
operator hitting the same symptom later should find the answer here rather than re-debugging it
(also duplicated, more tersely, in the runbook's own "Common failure cases" section).

1. **`apps/api/Dockerfile` never actually built.** `uv sync --frozen --no-dev` ran immediately
   after `COPY pyproject.toml uv.lock ./`, before `README.md` or `src/` were copied.
   `pyproject.toml` declares `readme = "README.md"` and builds `hrms` itself as an editable
   install, so `hatchling` failed with `OSError: Readme file does not exist: README.md`. **Fix**:
   copy `README.md` alongside `pyproject.toml`/`uv.lock`, and pass `--no-install-project` on the
   dependency-only layer (the correct `uv` Docker pattern) so it installs dependencies without
   attempting to build the local package before `src/` exists.

2. **`apps/api/uv.lock` was stale.** Still pinned `python-jose`/`ecdsa`/`pyasn1`/`rsa` (removed by
   Phase 3A's DEP-01 migration to `PyJWT`), and — critically — `cryptography` (imported directly by
   `core/crypto/field.py`/`core/crypto/master_key.py` for AES-256-GCM PII encryption) was **never
   declared as an explicit dependency**, only present transitively via the now-removed
   `python-jose[cryptography]`. A `--frozen` build (any real, reproducible production build)
   would install neither package, and the API would crash on import
   (`ModuleNotFoundError: No module named 'jwt'`, then, once `uv.lock` was regenerated without
   fixing the second issue, PII encryption would have crashed instead). Found by the Docker build
   actually failing, not by inspection — the local dev `.venv` had both packages installed already
   (from an earlier non-frozen `uv sync`) and masked this. **Fix**: added `cryptography>=43.0.0`
   explicitly to `pyproject.toml`; regenerated `uv.lock` (`uv lock`).

3. **`Settings.cors_allowed_origins`/`trusted_proxy_hosts` could not actually be set from a real
   environment variable.** Both are `tuple[str, ...]`-typed with a `mode="before"` validator that
   splits a comma-separated string — but pydantic-settings' own `EnvSettingsSource` treats any
   complex-typed field as JSON and calls `json.loads()` on the raw value **before** that validator
   ever runs, so setting `CORS_ALLOWED_ORIGINS=https://a.example.com` (exactly the documented,
   intended usage — see the field's own docstring and `apps/api/.env.example`) raised
   `pydantic_settings.exceptions.SettingsError` and crashed container boot outright. Every existing
   test constructed `Settings(cors_allowed_origins=(...))` directly with a Python tuple, bypassing
   the environment-variable decode path entirely — so this was never caught until this phase
   actually ran `docker compose ... run migrate` against a real `.env.production` file. **Fix**:
   annotated both fields `Annotated[tuple[str, ...], NoDecode]` (pydantic-settings' own documented
   escape hatch), so the raw string reaches the existing comma-split validator unchanged. Verified
   both via a direct `Settings()` construction with real environment variables and the existing
   test suite (`tests/unit/core/test_settings.py`, `test_cors_middleware.py` — 31 tests, all still
   passing).

4. **`celery beat` crash-looped in the production container.** Its default `--schedule` file
   (`celerybeat-schedule`) is written to the process's current working directory (`/app`), which
   is root-owned (created by `WORKDIR` before the Dockerfile's `chown`-ed `COPY`); the non-root
   `hrms` user the container actually runs as cannot write there, so `beat` crashed immediately
   with `PermissionError` and Docker's `restart: unless-stopped` crash-looped it. **Fix**: pointed
   `--schedule` at `/tmp/celerybeat-schedule` in `docker-compose.prod.yml`'s `beat` command —
   losing this file on restart only risks re-running one already-idempotent scheduled task, not a
   real data-loss concern.

5. **Both `worker` and `beat` inherited the API image's HTTP-based `HEALTHCHECK`**, which polls
   `/health/live` on port 8000 — a port nothing listens on in a Celery container, so both would
   have shown as permanently `unhealthy` (misleading, though not itself service-affecting, since
   `restart: unless-stopped` doesn't act on health status). **Fix**: `worker` now overrides
   `healthcheck` with `celery inspect ping`; `beat` disables it (no equivalent built-in Celery
   mechanism exists).

6. **`mc mirror`'s bind-mounted output was root-owned**, so the (non-root) backup script's own
   cleanup (`rm -rf` on the temporary snapshot directory) failed with `Permission denied` —
   found running `minio_backup.sh` for real. **Fix**: run the `mc` container with
   `--user "$(id -u):$(id -g)"` and `HOME=/tmp` (a writable location for `mc`'s own config file
   under an arbitrary uid), in both `minio_backup.sh` and `minio_restore.sh`.

## Docker

`apps/api/Dockerfile`: two-stage build (a `builder` stage with `uv`; a fresh `runtime` stage — not
derived from `builder` — so `uv`/`pip`/apt cache never reach the production image). Runtime: runs
as a dedicated non-root `hrms` user (uid/gid 1000), `HEALTHCHECK` against `/health/live` only
(deliberately not dependency-aware — see §Health/Readiness), default `CMD` runs `gunicorn` with
the `uvicorn.workers.UvicornWorker` class (graceful SIGTERM handling, configurable worker count via
`GUNICORN_WORKERS`), `exec`'d so gunicorn is PID 1 and receives signals directly. Verified: image
builds (404 MB), boots against real Postgres/Redis (`ENVIRONMENT=development` smoke test), serves
all three health endpoints correctly, runs as `hrms` (confirmed via `docker exec whoami`), and
shuts down cleanly on `docker stop` (SIGTERM → graceful worker exit, no SIGKILL needed, ~0.35s).
Same image also verified running the Celery worker command end-to-end (processed a real queued
task against real Redis).

`apps/web/Dockerfile` (new): three-stage build (`deps` → `builder` → `runtime`), all `node:20-alpine`
+ `libc6-compat` (required for Next.js's prebuilt SWC binary on musl libc — found via a real build
failure, the documented Next.js Alpine fix). Builds against `next.config.mjs`'s new
`output: "standalone"` (also new this phase — traces only the production dependency set instead of
shipping full `node_modules`). Runtime reuses the official `node:20-alpine` image's built-in `node`
user (uid/gid 1000) rather than creating a second one (which collides on uid 1000). `HEALTHCHECK`
via Node's built-in `fetch` against the static `/login` route (no `curl`/`wget` needed in the
image). Verified: image builds (231 MB), boots, serves HTTP 200, runs as `node`, and
`NEXT_PUBLIC_API_URL` is confirmed actually baked into the client JS bundle (grepped two chunk
files for the literal test URL).

Both `.dockerignore` files are new, excluding `.venv`/`node_modules`/test files/`.env*` from the
build context.

## Production Compose

`docker-compose.prod.yml` (new, 8 services): `postgres`, `redis`, `minio`, `minio-init` (bucket
provisioning, same idempotent pattern as the existing dev compose file), `api`, `migrate`
(`profiles: ["tools"]` — one-off, never part of default `up`), `worker`, `beat`, `web`, `nginx`,
`certbot`. Two Docker networks — `data` (postgres, redis, minio, api, worker, beat) and `edge`
(nginx, api, web, minio) — so Nginx has no network route to Postgres or Redis at all; MinIO sits on
both networks since Nginx must reach it directly for presigned-URL proxying. **No `ports:` mapping
exists anywhere for postgres/redis/minio** — that, not the network split alone, is what actually
keeps them off the public internet. Persistent named volumes for `postgres_data`/`minio_data`/
`redis_data`/`certbot_certs`/`certbot_webroot`. `restart: unless-stopped` on every long-lived
service. Per-container log rotation via an `x-logging` YAML anchor (`json-file`, 10 MB × 5 files).

Verified end-to-end: all 8 services (postgres/redis/minio/api/worker/beat/web/nginx, `migrate` and
`minio-init` run to completion) brought up together against locally-generated test secrets and a
self-signed certificate (no real domain/DNS was available in this environment — see
§Production Smoke Test for exactly what that does and doesn't prove).

## Nginx

`infra/nginx/nginx.conf` + `infra/nginx/conf.d/hrms.conf.template` (new). Three domains
(`${WEB_DOMAIN}`/`${API_DOMAIN}`/`${STORAGE_DOMAIN}`), envsubst-rendered from the compose `.env` on
container start (explicit variable list passed to `envsubst`, not the image's own unrestricted
default substitution, to avoid mangling Nginx's own `$host`/`$remote_addr`-style variables).
Routes: web domain → `web:3000`; API domain → `api:8000` (120s read/send timeout, above the
60s default, for payroll/bulk-import requests); storage domain → `minio:9000` (S3 API only, never
the admin console). HTTP server block handles only the ACME challenge path and a 301 redirect to
HTTPS. Forwards `Host`/`X-Real-IP`/`X-Forwarded-For`/`X-Forwarded-Proto` on every proxied route.
Deliberately emits **no security headers of its own** (no HSTS/CSP) — the API's
`SecurityHeadersMiddleware` and the frontend's `middleware.ts` already emit all of those,
conditional on `X-Forwarded-Proto`, so Nginx's only job is forwarding that context correctly, not
duplicating headers.

`client_max_body_size 15m` (above the app's own 10 MiB document-upload ceiling plus its 2 MiB
multipart-overhead headroom, so Nginx is never the tighter limit). JSON-formatted access log
(`json_combined`), consistent with the API/worker's own `structlog` JSON lines.

Verified: syntax-checked (`nginx -t`) both against a template-render dry run and as part of the
full stack coming up cleanly with no config errors.

## HTTPS / Let's Encrypt

`certbot` service (webroot method, `docker-compose.prod.yml`), renewal loop (`certbot renew` every
12h, only actually renews inside Let's Encrypt's own ~30-day-before-expiry window). Initial
issuance is documented as a manual, one-time step
(`docs/deployment/PRODUCTION_DEPLOYMENT.md` §11) since it genuinely requires a real, publicly
resolving domain already pointed at the VPS — not something this phase could execute for real
without one.

**What was actually verified** (self-signed certificate covering the same three SAN names,
substituted for a real Let's Encrypt certificate, since no real domain was available in this
environment):

- HTTP → HTTPS redirect: `301` to `https://…`
- HTTPS termination through Nginx works for all three domains (web/api/storage)
- `X-Forwarded-Proto: https` correctly reaches the API through `ProxyHeadersMiddleware`
  (`TRUSTED_PROXY_HOSTS` set to the Docker network's CIDR)
- **HSTS is emitted exactly once, only over the forwarded-HTTPS path** — confirmed present via
  `curl` through Nginx (`strict-transport-security: max-age=63072000; includeSubDomains`) and
  confirmed **absent** on a direct, unforwarded plain-HTTP request to the API container itself
  (this is exactly the Phase 2-documented conditional behavior the brief asked to re-verify —
  it now demonstrably works, not just reads correctly in source)
- Frontend CSP (with its per-request nonce) and HSTS both present, verified via `curl` through
  Nginx against the `/login` route
- Object storage domain (`storage.hrms.local`) correctly proxies to MinIO and correctly returns
  `403` for an unsigned request (proving both reachability and that the bucket's own
  no-anonymous-access policy, set by `minio-init`, is intact through the proxy)

**What was not verified** (cannot be, without a real public domain and DNS): actual Let's Encrypt
certificate issuance/renewal against the real ACME servers, and DNS-dependent HTTP-01 challenge
validation. The `certbot` command itself, the webroot path wiring, and the Nginx bootstrap sequence
(§11 of the runbook) were all written and syntax/logic-reviewed but not executed against Let's
Encrypt's real infrastructure in this session.

## Health / Readiness

`apps/api/src/hrms/modules/health/service.py`/`router.py` (modified). Three endpoints:

- `/health` — **unchanged** (backward-compatible with existing callers: `scripts/dev.py`'s own
  startup check, three existing test files).
- `/health/live` (new) — no dependency checks at all, returns `{"status": "ok"}`. What the Docker
  image's own `HEALTHCHECK` targets, deliberately: a Postgres/Redis blip must never cause an
  orchestrator to restart an otherwise-healthy process (a restart storm that makes an outage
  worse).
- `/health/ready` (new) — checks PostgreSQL (`SELECT 1`, 3s timeout), Redis (`PING`, 3s timeout),
  and required object-storage *configuration* (not a live MinIO round-trip — the brief's own
  scope: "required storage configuration"). Returns HTTP 503 (not 200-with-a-degraded-body) when
  not ready, since Nginx/an orchestrator typically gates on status code. Never returns credentials,
  connection strings, or a stack trace.

6 new/updated tests (`tests/unit/modules/health/test_router.py`), including one that explicitly
asserts the readiness response body never contains the raw `database_url`/`redis_url`/
`jwt_access_secret`/`pii_master_key` values. Verified via the real running stack: `/health/ready`
correctly reported `ready: true` with all three sub-checks `ok` against real Postgres/Redis/MinIO
through the full Docker network path (not just in-process unit tests).

## PostgreSQL Backups

`infra/backup/pg_backup.sh` (new) — runs `pg_dump -Fc` **inside** the running `postgres` container
via `docker compose exec` (no host-side database credentials, no direct port exposure needed),
piped through `gzip`, written to a timestamped file via an atomic `.partial` → rename pattern (a
crashed run never leaves a file that looks complete). Retention via `find -mtime` (default 14
days). Logs success/failure to `$BACKUP_ROOT/postgres/backup.log`.

`infra/backup/pg_restore.sh` (new) — restores into a **new, explicitly-named** database, never the
live one (hardcoded refusal if the target name matches `hrms_prod`/`$POSTGRES_DB`).

**Actually run, not just written**: backup taken against a real database (2 registered companies,
2 users, created via the smoke test below); restore run into `hrms_restore_check`; row counts
verified (`company: 2`, `"user": 2`, `employment: 0`) — a genuine restore, not merely "`pg_dump`
exited 0."

## MinIO Backups

`infra/backup/minio_backup.sh` (new) — `mc mirror`s the documents bucket to a local, dated
directory (using the existing `minio-init` image, run as a one-off container via
`docker compose run`, not a new dependency), then compresses to a single `.tar.gz`. Runs the `mc`
container as the invoking host user's own uid/gid (found necessary — see bug #6 above) so cleanup
never fails on ownership. Retention/logging mirror `pg_backup.sh`'s own pattern.

`infra/backup/minio_restore.sh` (new) — restores into a **new, explicitly-named** bucket, never the
live `S3_BUCKET_DOCUMENTS` (same refusal pattern as `pg_restore.sh`).

**Actually run**: a real test object uploaded to the live bucket, backed up, restored into
`hrms-restore-check`, and its **content verified byte-for-byte** (`mc cat` on the restored object
matched the original exactly) — not just an object count.

Off-VPS copy of backup output is explicitly flagged as an open decision, not silently assumed —
see `docs/deployment/DISASTER_RECOVERY.md`'s "What happens if the VPS is lost entirely" section:
this phase's scripts write to local VPS disk only, since adding a specific external destination
(paid or otherwise) is a cost/vendor decision outside this phase's own scope, not something to
guess at.

## Logging / Observability

Application logging was already solid (`structlog`, JSON, `configure_logging()`) — audited, not
replaced. Added: Nginx JSON access logs in the same shape family (`log_format json_combined`), and
per-container Docker log rotation (`x-logging` anchor, every service in
`docker-compose.prod.yml`) so unbounded log growth cannot silently fill the VPS disk. Sentry/
external error tracking remains explicitly deferred (confirmed still just a comment placeholder in
`core/errors/handlers.py`) — not made mandatory in this phase, per the brief's own instruction.

## Disk / Storage Management

Documented in `docs/deployment/PRODUCTION_DEPLOYMENT.md` §16: `docker system df`/`docker image
prune` guidance, backup-directory sizing, and the full list of disk consumers on this single-VPS
deployment. **No automated disk-usage alerting was built** — flagged explicitly as a deferred item
(§Deferred Items), not silently assumed to be someone else's problem.

## Production Configuration

`Settings`'s existing fail-closed guards (JWT secrets, CORS, S3/MinIO config, `PII_MASTER_KEY`)
were audited and found already solid — untouched in their actual validation logic. One real bug
fixed in the same file (`NoDecode` — see §Bugs found and fixed #3). All four
`apps/api/env/.env.*.example` reference templates rewritten to match the real self-hosted Docker
Compose architecture (previously described AWS ECS/RDS/Secrets Manager, inherited from an archived
NestJS-era plan) and to fix incorrect variable names (`JWT_ACCESS_TTL` → `JWT_ACCESS_TTL_MINUTES`,
`JWT_REFRESH_TTL` → `JWT_REFRESH_TTL_DAYS`) and a copy-paste `PORT=3000` bug (the frontend's port,
copied into the API's own env template). New `.env.prod.example` (repo root) documents the
Compose-level variable set (domains, Postgres/MinIO container credentials, build-time frontend API
URL) — kept deliberately separate from the application's own `Settings`, per §3 of the runbook.

A restart with the same secrets does not rotate JWT signing keys or the PII master key —
confirmed by design (`Settings` never generates a secret automatically; boot fails rather than
falling back to a default outside development) and by this phase's own smoke test (the same
`.env.production` file was reused across every container restart during testing without incident).

## Deployment Runbook

`docs/deployment/PRODUCTION_DEPLOYMENT.md` (new) — 17 sections covering prerequisites, domain
selection, the two-file environment-configuration split, secret generation, image builds, the
correct startup order (data services → migrations → encryption-key provisioning → application tier
→ bootstrap HTTPS → full Nginx), verification commands, rollback, backup verification, log
inspection, disk monitoring, and a "Common failure cases" section listing every bug this phase
found (§Bugs found and fixed) so a future operator hitting the same symptom finds the answer
immediately rather than re-debugging it. Every command in it was run for real while writing it,
against the locally-simulated stack described throughout this report.

## Disaster Recovery

`docs/deployment/DISASTER_RECOVERY.md` (new). Leads with `PII_MASTER_KEY` — explains precisely why
losing it is unrecoverable (not merely inconvenient), the required off-VPS storage practice, and
why it is deliberately **not** something this document or any script prints, generates
automatically, or backs up on the operator's behalf. Full step-by-step PostgreSQL and MinIO
restore procedures (pointing the application at a restored database/bucket, not just running the
restore scripts in isolation). An explicit "What happens if the VPS is lost entirely" table listing
every piece of state this system depends on and whether it survives VPS loss today — including the
honest, un-softened statement that this phase's backup scripts alone do **not** protect against VPS
loss unless their output is also copied off-VPS, which is flagged as an open operational decision,
not solved unilaterally with an unrequested paid service.

## Security Verification

- **Network exposure**: confirmed via the running stack — only Nginx's 80/443 are published to the
  host (`docker compose ps` showed `0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp` on `nginx` only;
  every other service showed only its internal container port, no host mapping).
- **TLS**: certificate served correctly (self-signed substitute, §HTTPS above), HTTP→HTTPS
  redirect works, HSTS conditional behavior verified present-over-HTTPS and absent-over-plain-HTTP,
  forwarded-proto trust verified.
- **Authentication**: company registration → login-equivalent (registration issues a session
  directly) → authenticated `/v1/auth/me` (full permission set returned correctly) → all exercised
  through the real HTTPS path via Nginx against real Postgres/Redis, not mocked. SEC-06's HttpOnly,
  `Secure`, `Path=/v1/auth`-scoped refresh cookie confirmed correctly set (verified the `Secure`
  flag specifically activated because the request reached the API with a trusted, forwarded
  `https` scheme). Password reset/email verification/invite acceptance were **not** separately
  re-exercised in this phase's smoke test (already covered by Phase 2/3A's own extensive test
  suites, which this phase's CI regression re-ran in full — see below).
- **Storage**: PostgreSQL data persists in a named volume (not re-verified via an actual container
  recreate-and-check in this session, but the volume is correctly declared and unconditionally
  mounted); MinIO upload verified (a real object written); MinIO download verified (content
  read back correctly); private object access verified (unsigned request to the storage domain
  correctly returned `403`, proving the bucket's no-anonymous-access policy holds through the Nginx
  proxy); presigned URL generation/consumption was **not** separately exercised (no document-upload
  UI flow was driven end-to-end in this phase — flagged in §Deferred Items).
- **Workers**: `worker` starts and correctly processes a real queued Celery task against real
  Redis; `beat`'s schedule loads correctly (post-fix); worker reconnect-on-Redis-restart and
  worker-failure-visibility (the healthcheck override, §Bugs found and fixed #5) were addressed by
  configuration but not separately chaos-tested (e.g., killing Redis mid-task) in this session.

## Production Smoke Test

Performed against the real `docker-compose.prod.yml` stack, locally, with generated test secrets
and a self-signed certificate substituted for domains/DNS/a real Let's Encrypt certificate (none of
which are available in this development environment):

| Step | Result |
| --- | --- |
| Start production-like stack | 8/8 services up, all healthy (or correctly non-applicable healthcheck for `beat`) |
| Verify frontend | `200` on `https://app.hrms.local/login` through Nginx |
| Verify API | `200` on `https://api.hrms.local/health` through Nginx |
| Verify database | Migrations reached head; `/health/ready` reports `database: ok` |
| Verify Redis | `/health/ready` reports `redis: ok`; rate-limit-adjacent Redis operations implicitly exercised by the auth flow |
| Verify MinIO | Bucket auto-created (`minio-init`), object written/read/backed-up/restored (§MinIO Backups) |
| Verify worker | Started, connected to Redis broker, processed a real task |
| Verify login (registration path) | `201`, real access token + HttpOnly refresh cookie issued |
| Verify email verification | **Not separately exercised** (covered by existing automated test suite, not this manual smoke test) |
| Verify invite acceptance | **Not separately exercised** (ditto) |
| Verify refresh | **Not separately exercised in this manual pass** (ditto — `test_auth_security.py` etc. cover it and passed in the CI regression below) |
| Verify logout | Attempted without an auth header (test setup error on this session's part, not a product finding); not re-attempted |
| Verify password reset | **Not separately exercised** (covered by existing automated suite) |
| Verify file upload | A test object written directly via `mc cp` (proving MinIO reachability/bucket policy), not through the application's own document-upload endpoint |
| Verify file download | Verified via the backup/restore content check (§MinIO Backups) |
| Verify HTTPS | Verified (§HTTPS / Let's Encrypt) |
| Verify health endpoints | Verified, all three |
| Verify backup creation | Verified, both Postgres and MinIO |
| Verify backup restore | Verified, both Postgres and MinIO, with actual data/content checks |

No destructive testing was performed against real production data (there is none — this was a
freshly created, throwaway local stack, torn down completely at the end of this phase, including
all volumes and generated test secrets).

## CI Regression Results

Full regression run after all of this phase's changes, backend against a genuinely fresh, isolated
`postgres:16-alpine` + `redis:7-alpine` pair (mirroring `.github/workflows/ci.yml` exactly:
same init scripts, same `alembic upgrade head`, same `hrms_app` role verification) — not the
shared local `hrms_dev` database:

| Check | Phase 3A baseline | After Phase 3B | Status |
| --- | ---: | ---: | --- |
| Ruff check | pass | pass | PASS |
| Ruff format | pass (462 files) | pass (463 files) | PASS |
| mypy | pass (167 files) | pass (167 files) | PASS |
| Import lint | 1 kept, 0 broken | 1 kept, 0 broken | PASS |
| Backend unit tests (fresh DB) | 674 (within 1,716 total) | **687 passed / 0 failed / 0 errors** | PASS |
| Backend integration+security (fresh DB) | within 1,716 total | **1,033 passed / 0 failed / 0 errors** | PASS |
| Backend total | 1,716 passed / 0 failed / 0 errors | **1,720 passed / 0 failed / 0 errors** | PASS |
| Frontend TypeScript | pass | pass | PASS |
| Frontend tests (Vitest) | 399 passed / 0 failed | **399 passed / 0 failed** | PASS |
| Frontend production build | pass | pass (`output: "standalone"` — `.next/standalone/server.js` confirmed present) | PASS |

The +4 backend tests are exactly this phase's own new coverage (`/health/live`, `/health/ready` ×3
— success, Redis-down-via-monkeypatch, no-secret-leakage). No pre-existing test was weakened or
skipped. No lint rule was disabled, no `# type: ignore`/`# noqa` was added, no import-linter
exclusion was added.

## Files Changed

Only Phase 3B's own changes are listed here. Every other file `git status` shows modified predates
this phase (Phases 1–3A, each already reviewed in its own report) and was **not** touched —
`apps/api/pyproject.toml` and `apps/api/src/hrms/core/config/settings.py` are the two exceptions,
each already modified by Phase 3A and further modified by this phase (see inline notes).

**New:**
- `apps/api/Dockerfile` *(modified — rewritten, see §Docker)*
- `apps/api/.dockerignore`
- `apps/api/scripts/provision_encryption_key.py`
- `apps/api/uv.lock` *(regenerated)*
- `apps/web/Dockerfile`
- `apps/web/.dockerignore`
- `docker-compose.prod.yml`
- `.env.prod.example`
- `infra/nginx/nginx.conf`
- `infra/nginx/conf.d/hrms.conf.template`
- `infra/backup/pg_backup.sh`
- `infra/backup/pg_restore.sh`
- `infra/backup/minio_backup.sh`
- `infra/backup/minio_restore.sh`
- `docs/deployment/PRODUCTION_DEPLOYMENT.md`
- `docs/deployment/DISASTER_RECOVERY.md`
- `docs/audits/RELEASE_HARDENING_PHASE_3B_PRODUCTION_INFRASTRUCTURE.md` (this report)

**Modified:**
- `apps/api/src/hrms/core/config/settings.py` — `NoDecode` fix (bug #3); also carries Phase 3A's
  earlier KMS→`PII_MASTER_KEY` changes, untouched by this phase.
- `apps/api/pyproject.toml` — added explicit `cryptography` dependency (bug #2); also carries
  Phase 3A's earlier DEP-01 (`python-jose`→`pyjwt`) change, untouched by this phase.
- `apps/api/src/hrms/modules/health/service.py`, `router.py` — liveness/readiness split
- `apps/api/tests/unit/modules/health/test_router.py` — 4 new tests
- `apps/api/env/.env.dev.example`, `.env.staging.example`, `.env.qa.example`,
  `.env.production.example` — rewritten (§Production Configuration)
- `apps/web/next.config.mjs` — `output: "standalone"`

## Configuration Changes

- **No new required application `Settings` field was added.** `NoDecode` is a type annotation
  change, not a new setting.
- **New, optional script**: `apps/api/scripts/provision_encryption_key.py` — required to be run
  once per environment, but not an environment variable.
- **New Compose-level variables** (root `.env`, from `.env.prod.example`): `IMAGE_TAG`,
  `WEB_DOMAIN`, `API_DOMAIN`, `STORAGE_DOMAIN`, `LETSENCRYPT_EMAIL`, `NEXT_PUBLIC_API_URL`,
  `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB`, `MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD`/
  `MINIO_BUCKET_DOCUMENTS`, `CELERY_CONCURRENCY` — all Compose-level, not read by the application's
  own `Settings`.
- Corrected (not new) variable names in the four `apps/api/env/.env.*.example` files:
  `JWT_ACCESS_TTL`→`JWT_ACCESS_TTL_MINUTES`, `JWT_REFRESH_TTL`→`JWT_REFRESH_TTL_DAYS`,
  `PORT=3000`→`PORT=8000`, `NODE_ENV` removed (not an API setting).

## Migration Status

```text
No new migration was added by this phase.
```

Alembic head unchanged: `20261004112000` (same as Phase 3A's end state). All existing migrations
were applied cleanly, in order, against a genuinely fresh database as part of both the smoke test
(§Production Smoke Test) and the CI regression (§CI Regression Results).

## Remaining Risks

- **Let's Encrypt issuance/renewal was not executed against the real ACME infrastructure** — no
  public domain was available in this environment. The webroot mechanism, Nginx bootstrap
  sequence, and renewal loop are written and locally verified with a substitute self-signed
  certificate, but the actual `certbot certonly` command against Let's Encrypt's real servers has
  not been run. **Do not consider HTTPS complete until this is run for real on the target VPS.**
- **Off-VPS backup copy is not implemented** — `pg_backup.sh`/`minio_backup.sh` write to local VPS
  disk only. A VPS-loss event today would lose all backups along with everything else, unless an
  operator adds an off-site copy step (documented as an open decision in
  `docs/deployment/DISASTER_RECOVERY.md`, not silently assumed away).
- **No automated disk-usage alerting.** Documented monitoring commands exist; nothing runs them on
  a schedule or pages anyone.
- **Presigned URL generation/consumption was not separately exercised** through the application's
  own document-upload flow in this phase's smoke test — MinIO reachability and bucket-policy
  enforcement were verified via `mc` directly, not via a real onboarding-document upload through
  the UI.
- **No chaos/failure-injection testing** (killing Redis mid-request, killing Postgres mid-migration,
  etc.) was performed — the readiness/failure-mode *code paths* (SEC-11's Redis fail-closed
  behavior, the new `/health/ready` checks) are unit-tested, but not exercised under a real induced
  outage in this phase's manual verification.
- **`TRUSTED_PROXY_HOSTS`/Postgres/MinIO container credentials require manual consistency** between
  the two env files (root `.env` and `apps/api/env/.env.production`) — nothing enforces they match;
  a mismatch fails loudly at container start, not silently, but this is still a manual-consistency
  requirement worth automating later (e.g., a preflight script) rather than a solved problem.
- **Docker log rotation is per-container-instance**, not global disk-quota-aware — a large number
  of restarts across many services could still, in aggregate, consume more disk than a single
  global quota would prevent, even though no individual container's logs can grow unbounded.

## Deferred Items

```text
Sentry / external error tracking — deferred, not made mandatory (per this phase's own instruction)
Automated disk-usage alerting — documented manually, not automated
Off-VPS backup copy destination — flagged as an open decision, not chosen on the operator's behalf
Flower (Celery monitoring UI) — mentioned in docs/product/13_DevOps_Architecture.md §1 (an AWS-era
    document) but out of this phase's own scope; not added
Chaos/failure-injection testing of Redis/Postgres outages — not performed
Real Let's Encrypt issuance against a public domain — cannot be executed in this environment
Consistency-check tooling between the two env-file layers — flagged, not automated
MFA, the remaining SEC-11 "auth" bucket coarseness, payroll statutory sign-off — unchanged from
    Phase 3A's own "not addressed" list; entirely out of this phase's scope
```

## Production Readiness Decision

```text
NOT READY FOR PUBLIC RELEASE
```

This phase closed the entire deployment-infrastructure gap Phase 0–3A explicitly left untouched:
Docker, Nginx, HTTPS, health/readiness, backups (with verified restores), and the
deployment/disaster-recovery documentation. Every piece was actually run, not just written, and
that process surfaced and fixed six real bugs that static inspection alone would not have caught.
The application is now **deployable** to the target self-hosted architecture in a way it
demonstrably was not before this phase (the Dockerfile did not even build). This is an
infrastructure milestone, not a production-readiness signal by itself — the application-level
release blockers this phase did not touch (payroll statutory-rate sign-off, MFA, the coarse `auth`
rate-limit bucket, real Let's Encrypt issuance against a live domain, and the remaining risks listed
above) are still open.

**Git state**: branch `main`, HEAD unchanged at `fb94e25` (this phase added no commits). Working
tree contains this phase's changes plus every already-reviewed, still-uncommitted change from
Phases 1–3A. `mavericks-kit.zip`, `shirt.png`, `shorts.png`, and `work done/` remain untouched, as
in every prior phase. **Nothing was committed. Nothing was pushed.**

Suggested commit grouping when the user is ready (in addition to Phase 1–3A's own already-suggested
groupings): (1) the `cryptography`/`uv.lock` fix, ideally folded into Phase 3A's DEP-01 commit since
it's a direct consequence of that change; (2) the `NoDecode` settings fix; (3) the health
liveness/readiness split; (4) Docker images + `.dockerignore` files; (5) production Compose +
Nginx; (6) backup scripts; (7) the four rewritten env example files; (8) deployment/DR docs +
`next.config.mjs`'s `output: "standalone"`; (9) this report.
