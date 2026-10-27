# Hostinger Deployment Runbook (proposed; supplements `PRODUCTION_DEPLOYMENT.md`)

Nothing here has been executed. Existing, previously exercised steps live in `docs/deployment/PRODUCTION_DEPLOYMENT.md`; this runbook adds the gates identified by the audit. `$` = on the VPS as the `deploy` user.

## A. One-time provisioning

1. Buy KVM 4, Ubuntu 24.04 LTS, region nearest the users; enable Hostinger firewall + weekly snapshots (convenience only).
2. Create `deploy` user, SSH key only; `PermitRootLogin no`; `PasswordAuthentication no`; `ufw default deny incoming; ufw allow 80,443/tcp; ufw allow from <admin-ip> to any port 22`; `apt install fail2ban unattended-upgrades`; set `TZ=UTC`.
3. Install Docker Engine + compose plugin; `daemon.json`: `{"log-driver":"json-file","log-opts":{"max-size":"10m","max-file":"5"},"live-restore":true}`.
4. DNS: `app.`, `api.`, `storage.` → VPS IP; CAA record.
5. Create files (mode 0600, **not in Git**): root `.env` (Postgres/MinIO/domains/`IMAGE_TAG`), `apps/api/env/.env.production`, **`apps/api/env/.env.migrate`** containing only `MIGRATIONS_DATABASE_URL` (requires the compose change in roadmap item R-01; until applied, do not go live).
6. Generate `PII_MASTER_KEY`, JWT secrets, DB passwords; store `PII_MASTER_KEY` offline immediately (DR doc).
7. Bring up data tier only: `$ docker compose -f docker-compose.prod.yml up -d postgres redis minio minio-init` ; confirm healthy.
8. Issue certificates (`PRODUCTION_DEPLOYMENT.md §11`), start nginx.
9. Configure backups (BACKUP/DR doc) and **run the first restore test before onboarding any customer**.

## B. Routine release

Preconditions: release tag `vX.Y.Z` built from a clean commit; CI green; staging smoke tests green; change reviewed for destructive migrations.

| # | Step | Command / check | Abort if |
|---|---|---|---|
| 1 | Announce window; set maintenance banner (optional) | – | – |
| 2 | Pull images | `$ IMAGE_TAG=vX.Y.Z docker compose -f docker-compose.prod.yml pull` (or build) | pull fails |
| 3 | Pre-migration backup | `$ ./infra/backup/pg_backup.sh` then verify with `pg_restore --list`; upload off-server | backup missing/<expected size |
| 4 | Pause async writers | `$ docker compose -f docker-compose.prod.yml stop beat worker` | – |
| 5 | Migrate once | `$ IMAGE_TAG=vX.Y.Z docker compose -f docker-compose.prod.yml --profile tools run --rm migrate` | non-zero exit (DB unchanged because single transaction → go to step 9) |
| 6 | Start app | `$ docker compose -f docker-compose.prod.yml up -d api worker beat web` | healthcheck failing >2 min |
| 7 | Verify | `curl -fsS https://api.<domain>/health/ready`; smoke: login, tenant switch rejected (404), punch in/out, leave apply/approve, payslip download, document download; Grafana error rate <1 % | any smoke failure |
| 8 | Close window; record release in log | – | – |
| 9 | Rollback (before step 5 committed or when migration failed) | `$ IMAGE_TAG=<previous> docker compose … up -d api worker beat web` — schema unchanged | – |
| 10 | Rollback after a committed migration | prefer **roll forward** with hotfix; restore the step-3 dump (to a new DB, then repoint) only for proven corruption; accept RPO = dump time | – |

Rules: never run `alembic` inside `api`/`worker` start commands; never scale `beat`; never `docker compose down -v`; never `up` the dev `docker-compose.yml`.

## C. Operations

* Daily: backup job success mail; disk <70 %; 5xx rate; Celery queue length.
* Weekly: `apt` patches/reboot window; review `pg_stat_statements` top 10; review security events log.
* Monthly: restore test (BACKUP/DR doc), dependency scan, rotate access tokens/keys per policy, review firewall rules.
* Log rotation: docker json-file (10 MB × 5) + `api_logs` volume (module file sink rotation, `docs/operations/LOGGING_GUIDE.md`).

## D. Incident quick reference

| Symptom | First actions |
|---|---|
| API 5xx spike | `docker compose logs --since 10m api`; check `/health/ready`; DB connections `SELECT count(*) FROM pg_stat_activity`; recent release? roll back images |
| DB connections exhausted | find idle-in-transaction; restart `worker`; verify pool settings; scale down concurrency |
| Disk full | `docker system df`; prune old images; check WAL archive backlog (archive_command failing) before deleting anything in `pg_wal` |
| Cross-tenant data report | Treat as P0: capture request IDs, disable affected route/feature flag, snapshot DB, review `audit_log` and `security_event` logs, notify per DPDP obligations |
| Lost server | DR doc scenario S1 |
