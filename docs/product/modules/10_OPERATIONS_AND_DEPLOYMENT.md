# Module 10 — Operations, Observability & Deployment Tooling (internal/support)

> Part of [Staff Spectrum HRMS Functional Documentation](../STAFF_SPECTRUM_HRMS_FUNCTIONAL_DOCUMENTATION.md) · [Catalog](../STAFF_SPECTRUM_HRMS_MODULE_CATALOG.md)

**Audience:** operators and developers. No end-user UI. **Status:** Implemented (scripts and ops CLIs have unit tests: `tests/unit/ops/{test_job_health,test_import_backlog,test_host_monitor}.py`); **alert destination not configured by default** ("open operational decision" in the monitor's header); staging validation checklist exists but its completion is not evidenced here. `test_host_monitor.py` and `hrms_monitor.sh` have uncommitted modifications in the working tree.

## 1. Runtime topology (`docker-compose.prod.yml`, project `hrms-prod`)
Services: `postgres` (16, runtime role `hrms_app` NOSUPERUSER/NOBYPASSRLS provisioned by init script), `redis`, `minio` + `minio-init` (bucket), `api` (FastAPI), `migrate` (Alembic), `worker` (Celery; queues `default`, `reports_exports`), `beat` (scheduler), `web` (Next.js), `nginx` (TLS, proxy incl. public MinIO hostname for presigned URLs), `certbot`. Two networks: `data` (db/redis/minio/api/worker/beat) and `edge` (nginx/api/web/minio); no host port published for postgres/redis/minio. Secrets via two env files (compose `.env` and `apps/api/env/.env.production`); the API refuses to boot staging/production with development secrets, `EMAIL_PROVIDER=logging`, loopback/non-https `WEB_APP_BASE_URL`, or missing S3 endpoint. Local development: `docker-compose.yml` (postgres :5433, redis :6380, MinIO :9000).

## 2. Scheduled jobs (Celery beat, timezone `Asia/Kolkata`)
| Task | Schedule | Module |
|---|---|---|
| `leave.run_monthly_accrual` | daily 01:00 | Leave |
| `leave.run_comp_off_credit_sweep` | hourly :00 | Leave |
| `leave.run_comp_off_expiry_sweep` | daily 01:30 | Leave |
| `leave.run_year_end_sweep` | daily 02:00 | Leave |
| `attendance.run_face_cleanup` | daily 03:15 | Attendance |
| `attendance.run_daily_calculation` | daily 09:30 | Attendance |
| `attendance.run_incomplete_reminders` | daily 10:00 | Attendance |
| `employee.run_termination_access_sweep` | hourly :15 | Employee |
| `health.scheduler_heartbeat` | every 60 s | Ops |
Only companies with status `TRIAL`/`ACTIVE` are processed. Per-company fan-out isolates failures; limits: company task soft 1500 s / hard 1800 s, fan-out soft 120 s / hard 180 s; Leave tasks `acks_late` with retry on connection errors (3×, backoff). Beat has no leader election, so tasks are written to be idempotent. Task failures, retries, unknown/rejected tasks are logged as structured events. Request id propagates into tasks.

## 3. Health & monitoring
* `/health` (DB), `/health/live` (process), `/health/ready` (DB + Redis + storage configured; 503 when not ready).
* `python -m hrms.ops.job_health` (read-only): scheduler heartbeat age (default max 300 s), queue depth (100), oldest-message age (600 s); exit 0/1/2.
* `python -m hrms.ops.import_backlog [--company-id] [--stale-pending-hours]` (read-only, `SET TRANSACTION READ ONLY`): classifies queued import messages `ELIGIBLE_TO_RUN | SAFE_TO_DRAIN | MANUAL_REVIEW`.
* `infra/monitoring/hrms_monitor.sh` (cron, read-only): API readiness, job health, unhealthy/restarting containers, disk (85 %), 5-minute structured-log windows (5xx, unhandled exceptions, DB/limiter outages, security events, task failures, email/storage failures), backup recency; pipes a JSON report to `HRMS_ALERT_COMMAND` if set.
* `infra/backup/{pg,minio}_{backup,restore}.sh`; DR runbook `docs/deployment/DISASTER_RECOVERY.md`.
* Logging: JSON structured logs with redaction (`core/observability`), request-id header, security events (`login.failed`, `account.locked`, `refresh.rejected`, `rate_limited`, `face_punch.rejected` …), business audit events after commit. Runbooks: `docs/operations/{ALERTS_AND_RUNBOOKS,LOGGING_AND_OBSERVABILITY,STAGING_VALIDATION_CHECKLIST}.md`.

## 4. CI (`.github/workflows/ci.yml`)
API: ruff, format check, mypy, import-linter module boundaries, Alembic upgrade on a real Postgres with the runtime role verified NOSUPERUSER/NOBYPASSRLS, unit tests, integration + security tests with disposable MinIO; Web: lint, typecheck, vitest, build; Mobile job present. Passing CI is **not** end-to-end verification of business workflows.

## 5. Internal-only API surface
`/auth/admin/users-check` (permission probe), `/health*`. `seed/bootstrap.py` seeds demo companies/users for tests only (`admin@example.com` style demo data; not part of production registration).

## 6. Limitations
Alert delivery undefined by default; thresholds provisional; no application-level admin console (support/super-admin) — **no platform super administrator role or cross-tenant admin UI exists**; backups verified only by logs/scripts, restore drills not evidenced; face cleanup disabled by default; no metrics/APM stack (log-derived monitoring only).

## 7. Evidence
`docker-compose*.yml`, `infra/**`, `apps/api/src/hrms/{ops,core/celery_app.py,modules/health}`, `apps/api/Dockerfile`, `docs/deployment/*`, `docs/operations/*`, `.github/workflows/ci.yml`.
