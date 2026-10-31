# Deployment readiness

Evidence: repository files and the CSP browser run in document 07. No stack was deployed. No container was started or stopped. The existing dev containers (`hrms-postgres` on 5433, `hrms-redis` on 6380, `hrms-minio` on 9000–9001) were observed and not used.

## What the repo actually ships

`docker-compose.prod.yml` is the production shape: Postgres 16, Redis 7, MinIO-compatible object storage, a one-off `migrate` service, `api` (gunicorn), one `worker`, one `beat`, Next.js `web`, Nginx on 80/443, Certbot. Postgres, Redis, and object storage do not publish host ports. API image `TZ=UTC`, non-root, healthcheck `GET /health/live`. Web image builds with `output: "standalone"` and runs `node server.js` (`apps/web/Dockerfile` 50–52). `NEXT_PUBLIC_API_URL` is an image build arg. Changing it requires a rebuild (Dockerfile lines 20–23).

Nginx (`infra/nginx/conf.d/hrms.conf.template`): vhosts for web, API, and storage. `/metrics` returns 404. `/health/ready` is proxied. No `limit_req` zone was found in the template.

There are no systemd units. Backups are shell scripts (`infra/backup/pg_backup.sh`, `pg_restore.sh`, `minio_backup.sh`, `minio_restore.sh`) plus a crontab example in `docs/deployment/PRODUCTION_DEPLOYMENT.md`. That cron is not a file in the repo.

`docs/deployment/HOSTINGER_DEPLOYMENT_RUNBOOK.md` line 3 says nothing there has been executed. `HOSTINGER_SELF_HOSTING_ARCHITECTURE.md` is marked as a plan. `PRODUCTION_DEPLOYMENT.md` still says the product is not ready for a public release. This audit agrees, for the reasons in document 09, and does not treat payroll as the reason.

Dev compose publishes host ports. The Hostinger docs say not to use it on the VPS because Docker bypasses UFW for published ports. That warning is correct and was not re-tested.

## CSP

### ATT-CSP-001 — Local production server passes; the Docker and Nginx path was not run

- Severity: Medium as residual risk. Not a confirmed hydration blocker.
- Evidence, executed: Playwright + system Chrome, 15 passed, 3 skipped. Details in document 07.
- What passed: nonce on every script, unique nonce per response, `no-store` HTML, strict `script-src` without `unsafe-inline` or `unsafe-eval`, hydration of login, register, and `/app/dashboard`, login and register interaction, blocked foreign fetch / inline handler / eval.
- What did not run: Nginx TLS (`CSP_E2E_BASE_URL` unset). The container command `node server.js`. The test logged that `next start` does not match `output: "standalone"`, and the tests still passed under `next start`.
- The Dockerfile healthcheck comment still calls `/login` a statically prerendered route (lines 45–46). The CSP responses had no `x-nextjs-prerender` header and `cache-control: no-store`. The comment is stale. The probe can still expect HTTP 200.
- `style-src 'unsafe-inline'` remains. `img-src` is `'self' data:`. A logo on another host will not load.
- `connect-src` is the build-time API origin. A wrong `NEXT_PUBLIC_API_URL` at image build time blocks the API in the browser even when the container env is later fixed.
- Blocks deployment: the old “CSP prevents hydration” defect is **not** what this local production build does. Do not deploy until the same checks pass through the real Nginx hostname. That is a release gate, not a reason to weaken CSP.

## Environment gates (ATT-OPS-001)

| Setting | If left at the code default | Required for this release |
|---|---|---|
| `ENVIRONMENT` | `development` (docs, OpenAPI, weaker boot guards) | `production` |
| JWT and `PII_MASTER_KEY` | Example placeholders, rejected outside development | Unique secrets, not the example file |
| `DATABASE_URL` | Example password is not rejected at boot | Real password, app role `hrms_app` with `NOBYPASSRLS` |
| `TRUSTED_PROXY_HOSTS` | Empty. Refresh cookie may not be `Secure`. Rate limits share the proxy IP. | The Nginx address only |
| `CORS` | Local origins in development | The real web origin, credentials on, not `*` |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | `https://` API origin, baked into the web image |
| Mobile `API_BASE_URL` | `http://localhost:8000` | `https://` API origin at Flutter build time |
| Face provider | Disabled | Leave disabled |
| Geofence mode | `DISABLED` | Leave disabled until web can send a location or only mobile punches |

## Health and logs

| Check | Behaviour |
|---|---|
| `GET /health/live` | Process up. Docker uses this. |
| `GET /health` | Database only. Skips Redis. |
| `GET /health/ready` | 503 unless Postgres, Redis, and object-storage config are ok. Nginx proxies it. |
| Worker | `celery inspect ping`. |
| Beat | Healthcheck disabled in compose. A 60-second `health.scheduler_heartbeat` is what `hrms.ops.job_health` watches. One replica only. |
| Logs | structlog JSON, `X-Request-Id`, Nginx JSON access log with token path segments redacted. Container logs json-file, 10 MB × 5. |
| Metrics | `/metrics` is hidden by Nginx (404). |

An attendance failure can be investigated from the request id and the punch audit row without putting the password in the log. Face images and tokens must stay out of logs; the mobile client does not print tokens. This audit did not tail a production log.

Minimum monitoring before the first company:

1. Alert if `/health/ready` fails.
2. Alert if beat heartbeat is stale (otherwise missing days stay `no_record` and look like an empty office).
3. Alert on 5xx rate and on `PUNCH_REJECTED` / calculation-exception log lines.
4. Alert if the backup script did not write a fresh dump.

There is an optional `docker-compose.monitoring.yml`. It is not part of the default stack. No evidence it is running on a host.

## Backups (ATT-OPS-002)

`docs/deployment/HRMS_BACKUP_AND_DISASTER_RECOVERY.md` states there is no evidence a restore has been tested, and says not to claim recoverability until a game day is recorded in that file. `DISASTER_RECOVERY.md` describes a quarterly drill and does not record one. Dumps stay on the same VPS. pgBackRest, off-site copy, and backup encryption are proposed, not implemented as running jobs.

`pg_restore.sh` restores into a **new** database name, which is the right shape. It has not been shown to succeed.

Data-loss exposure today: everything since the last successful dump, and the whole database if the VPS disk is lost. Redis is not backed up (rate-limit and broker state only). Losing `PII_MASTER_KEY` makes encrypted identity fields unreadable even if the dump is restored. Attendance punches are not a substitute for that key, but employee documents and statutory identifiers are.

This audit did not restore anything.

Blocks deployment of real employee data: yes. A pilot with disposable data can proceed only after one restore into an empty database is timed and written down. That is still a gate, not a paperwork nicety.

## Payroll and startup

The API process imports payroll at startup (`app.py` 212, 226). The current tree imports cleanly enough that unit tests loaded the app’s calculation modules, and `tsc` passed with payroll pages present. A future broken payroll import will take the API down, including attendance. Do not delete the package to “simplify” the release. Do not need a pay run to record a punch.

## Android and web URL check

Neither client defaults to a production URL. Both default to `http://localhost:8000`. A production web image built without the build arg, and a Flutter binary built without `--dart-define`, will not reach the API. Release Android also refuses cleartext, so the localhost default cannot work on a release APK (ATT-MOB-001).
