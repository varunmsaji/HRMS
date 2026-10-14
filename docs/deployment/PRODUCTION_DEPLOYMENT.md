# Production Deployment Runbook

RELEASE_HARDENING_PHASE_3B. Target: a single self-hosted Hostinger VPS running Docker Compose +
Nginx + Let's Encrypt — no AWS-managed services anywhere in this stack. Every command in this
runbook was actually run, against a real (locally simulated) production-mode stack, while writing
it — see `docs/audits/RELEASE_HARDENING_PHASE_3B_PRODUCTION_INFRASTRUCTURE.md` for the full
verification record and the bugs this process found and fixed along the way.

Production readiness status remains **NOT READY FOR PUBLIC RELEASE** — this runbook covers
*deployment infrastructure*, not the separate, still-open application-level release blockers
tracked in `docs/audits/RELEASE_HARDENING_PHASE_3A_SECURITY_REMEDIATION.md` §17 and
`docs/audits/PAYROLL_BLOCKER_REGISTER.md`.

## 1. Server prerequisites

- A VPS reachable at the domains you intend to use (§2), with ports **80** and **443** open to
  the internet and nothing else public-facing.
- Docker Engine + the Compose plugin (`docker compose version`) or the standalone `docker-compose`
  binary. Either works — every script in this repo (`infra/backup/*.sh`) auto-detects which one is
  present, matching `scripts/dev.py`'s own existing precedent for local dev.
- DNS: `A`/`AAAA` records for your web, API, and storage domains all pointing at this VPS's public
  IP, **before** you run the first Let's Encrypt issuance (§11) — HTTP-01 challenge validation
  needs them resolving already.
- Enough disk for Postgres + MinIO data, Docker images, and backups — see §16 for the ongoing
  monitoring/cleanup this needs, not just the initial provisioning size.

## 2. Choose your domains

This repo does not hardcode a domain anywhere — pick three (or reuse one VPS's IP with subdomains
of a domain you control):

| Purpose | Example | Routes to |
| --- | --- | --- |
| Frontend | `app.hrms.example.com` | `web` container (Next.js) |
| API | `api.hrms.example.com` | `api` container (FastAPI) |
| Object storage (presigned URLs only) | `storage.hrms.example.com` | `minio` container's S3 API |

These three feed `infra/nginx/conf.d/hrms.conf.template` via envsubst — see `docker-compose.prod.yml`'s
`nginx` service.

## 3. Environment configuration

Two separate `.env`-shaped files, **not merged**, both gitignored (never commit real values):

1. **Repo root `.env`** — copy from `.env.prod.example`. Drives `docker-compose.prod.yml`'s own
   variable substitution: Postgres/MinIO container credentials, the three domains from §2, and the
   frontend's build-time `NEXT_PUBLIC_API_URL`.
2. **`apps/api/env/.env.production`** — copy from `apps/api/env/.env.production.example`. Drives
   the application's full `Settings` (JWT secrets, `PII_MASTER_KEY`, CORS, rate limits, etc.) —
   referenced by the `api`/`worker`/`beat`/`migrate` services' `env_file:` in
   `docker-compose.prod.yml`. `WEB_APP_BASE_URL` in that file must be `https://` plus the same
   host as this compose file's `WEB_DOMAIN`. Verification, password-reset, invite, onboarding,
   and attendance emails embed it. The API refuses to boot in production when it is missing
   or still the development default `http://localhost:3000`. It is not derived from
   `NEXT_PUBLIC_API_URL` (that value is the API origin baked into the web image, not the
   site users open from an email).

**The Postgres and MinIO credentials must match between the two files** — `docker-compose.prod.yml`'s
`.env` sets the actual container credentials (`POSTGRES_PASSWORD`, `HRMS_APP_PASSWORD`,
`MINIO_ROOT_PASSWORD`); `apps/api/env/.env.production`'s `MIGRATIONS_DATABASE_URL`/`DATABASE_URL`/
`AWS_SECRET_ACCESS_KEY` must embed those same values. Nothing enforces this automatically; a
mismatch fails at container start (Postgres/MinIO auth failure), not silently.

**`POSTGRES_PASSWORD` and `HRMS_APP_PASSWORD` are two different passwords for two different
database roles** (RELEASE_HARDENING_PHASE_6A / Finding DB-01) — `POSTGRES_PASSWORD` is for `hrms`,
the schema-owner superuser role migrations run as (`MIGRATIONS_DATABASE_URL`); `HRMS_APP_PASSWORD`
is for `hrms_app`, the restricted, non-superuser role the running application actually connects as
(`DATABASE_URL`). Do not reuse one value for both — nothing prevents it, but it defeats the point of
having two roles with different privileges.

## 4. Secret generation

```bash
openssl rand -base64 32   # POSTGRES_PASSWORD, HRMS_APP_PASSWORD, MINIO_ROOT_PASSWORD
openssl rand -base64 48   # JWT_ACCESS_SECRET, JWT_REFRESH_SECRET, PII_MASTER_KEY
```

Generate **two separate** values for `POSTGRES_PASSWORD` and `HRMS_APP_PASSWORD` — do not reuse one
`openssl rand` output for both (see §3).

`PII_MASTER_KEY` is the most important secret in this system — see
`docs/deployment/DISASTER_RECOVERY.md` before you generate it, not after. Losing it makes every
already-encrypted PII field (PAN, Aadhaar, bank account numbers) permanently unrecoverable; it must
be stored somewhere that survives VPS loss, and it is intentionally **not** something this runbook
tells you to put in a password manager screenshot or a support ticket.

**`SMTP_USERNAME`/`SMTP_PASSWORD`** (RELEASE_HARDENING_PHASE_5A,
`docs/audits/RELEASE_HARDENING_PHASE_5A_EMAIL.md`) are not generated with `openssl` — they come
from whichever authenticated SMTP endpoint you choose (a transactional-email vendor's SMTP relay,
a self-hosted MTA, etc.; never AWS SES — this deployment avoids AWS-managed services). Obtain them
from that provider and put them straight into `apps/api/env/.env.production` alongside
`SMTP_HOST`/`SMTP_PORT`/`SMTP_FROM_EMAIL`. `EMAIL_PROVIDER=logging` (the development default)
refuses to boot in `production`/`staging` — see §17's common-failure-cases entry if you hit that.

## 5. Build the images

```bash
docker compose -f docker-compose.prod.yml build
```

Two images: `hrms-api` (one image, four entrypoints — `api`/`worker`/`beat`/`migrate` all run it
with a different `command:`, matching `docs/product/13_DevOps_Architecture.md` §2's existing
"one image, four entrypoints" principle) and `hrms-web`. `hrms-web`'s build **bakes
`NEXT_PUBLIC_API_URL` into the client JS bundle at build time** — changing that URL later requires
rebuilding and redeploying the image, not just restarting the container or editing an env file.

## 6. Start data services and wait for health

```bash
docker compose -f docker-compose.prod.yml up -d postgres redis minio minio-init
docker compose -f docker-compose.prod.yml ps
```

Confirm all three show `healthy` before continuing. `minio-init` runs once and exits 0 — it
creates the documents bucket and locks it to no anonymous access (`mc anonymous set none`); it is
safe to re-run (`--ignore-existing`) if you ever need to.

**Fresh volume vs. existing volume, for `HRMS_APP_PASSWORD`** (RELEASE_HARDENING_PHASE_6A /
Finding DB-01) — `infra/docker/postgres/init/002_app_role.sh`, which provisions the `hrms_app`
runtime role from `HRMS_APP_PASSWORD`, is a Postgres `docker-entrypoint-initdb.d` script: it only
runs the **first** time a container starts against an **empty** `postgres_data` volume. It does
**not** re-run just because you change `HRMS_APP_PASSWORD` in `.env` later and restart — Postgres
has no concept of "re-run init on an existing volume." If this is a brand-new deployment (empty
`postgres_data` volume), the value you put in `.env` before this first `up` is simply the role's
password from here on; nothing further to do. If you are rotating the password on an
**already-initialized** volume, see "Rotating the `hrms_app` database password" immediately below —
changing `.env` alone does nothing to the running database and will instead cause the same
authentication failure Finding DB-01 originally described.

### Rotating the `hrms_app` database password

For an existing `postgres_data` volume, changing the running role's password is a manual, explicit
step — there is no automation for this on purpose (rotating a live production credential should not
happen implicitly as a side effect of an `up` or a redeploy):

```bash
# 1. Generate the new password (see §4) and update it in the repo-root .env's HRMS_APP_PASSWORD.
#    Do NOT restart anything yet.

# 2. Apply it to the live role, authenticating as the schema-owner (hrms), not hrms_app itself:
docker compose -f docker-compose.prod.yml exec -e PGPASSWORD="$POSTGRES_PASSWORD" postgres \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
  -c "ALTER ROLE hrms_app PASSWORD '<the new HRMS_APP_PASSWORD value>';"

# 3. Update the same new value in apps/api/env/.env.production's DATABASE_URL, then restart the
#    containers that hold the old password in memory:
docker compose -f docker-compose.prod.yml up -d --force-recreate api worker beat
```

Until step 3 completes, `api`/`worker`/`beat` are still using the old password from their existing
process environment — restarting `postgres` alone does not affect them either way. Never destroy
and recreate the `postgres_data` volume to "apply" a password rotation; that discards the entire
production database.

## 7. Run migrations

```bash
docker compose -f docker-compose.prod.yml --profile tools run --rm migrate
```

This is a **one-off** run, not a long-lived service (`profiles: ["tools"]` deliberately keeps it
out of `docker compose up`'s default service set) — migrations must complete once, before
`api`/`worker`/`beat` start taking traffic, never racing against multiple containers running
`alembic upgrade head` concurrently.

## 8. Provision the initial PII encryption key

**Required, one-time, before the API's first boot in this environment** — `app.py`'s `lifespan()`
refuses to start any non-development environment without exactly one `ACTIVE` row in
`encryption_keys`:

```bash
docker compose -f docker-compose.prod.yml --profile tools run --rm migrate \
    python scripts/provision_encryption_key.py
```

This did not previously have a runnable entrypoint (`core/crypto/provisioning.py`'s own docstring
called it "an operator-run step" but shipped no script) — `apps/api/scripts/provision_encryption_key.py`
is new in this phase. Running it a second time against an environment that already has an active
key fails loudly (the database's own partial unique index), not silently.

## 9. Start the application tier

```bash
docker compose -f docker-compose.prod.yml up -d api worker beat web
```

`worker`'s `HEALTHCHECK` is `celery inspect ping` (overridden in `docker-compose.prod.yml` — the
image's own inherited HTTP-based healthcheck does not apply to a Celery container, see §16 for why
this matters). `beat` has healthcheck disabled entirely (no equivalent built-in Celery mechanism
exists); `restart: unless-stopped` still recovers it if the process itself crashes. **Never scale
`beat` beyond one replica** — two schedulers double-fire every scheduled task (leave accrual,
comp-off sweeps, attendance calculation).

## 10. Load self-signed / staging certs are NOT provided

`docker-compose.prod.yml`'s `nginx` service expects real certificates at
`/etc/letsencrypt/live/${WEB_DOMAIN}/{fullchain,privkey}.pem` inside the `certbot_certs` volume
before it can start successfully — §11 creates these. Do not start `nginx` before §11 completes.

## 11. Issue the initial Let's Encrypt certificate

Nginx needs to be running to serve the HTTP-01 challenge, but Nginx needs the certificate to start
its HTTPS server blocks — resolved with a temporary bootstrap: start Nginx with only its HTTP (port
80) behavior working, obtain the cert, then start it for real.

```bash
# 1. Start Nginx — it will fail to bind :443 (no cert yet) but that's fine for this step; the
#    :80 ACME-challenge location still serves.
docker compose -f docker-compose.prod.yml up -d nginx

# 2. Request the certificate (webroot method — infra/nginx/conf.d/hrms.conf.template's
#    /.well-known/acme-challenge/ location is what makes this work).
docker compose -f docker-compose.prod.yml run --rm certbot certonly \
    --webroot -w /var/www/certbot \
    -d "${WEB_DOMAIN}" -d "${API_DOMAIN}" -d "${STORAGE_DOMAIN}" \
    --email "${LETSENCRYPT_EMAIL}" --agree-tos --no-eff-email

# 3. Restart Nginx so it picks up the now-present certificate and serves HTTPS.
docker compose -f docker-compose.prod.yml restart nginx

# 4. Start the renewal daemon (auto-renews via a loop; --quiet, runs every 12h, only actually
#    renews within Let's Encrypt's own ~30-day-before-expiry window).
docker compose -f docker-compose.prod.yml up -d certbot
```

The certificate covers all three domains as SANs under `${WEB_DOMAIN}`'s `live/` directory — the
Nginx template references that path for all three server blocks (§2 table), so a renewal never
needs a config change.

## 12. Verify

```bash
curl -I https://${WEB_DOMAIN}/login          # 200, HSTS present, CSP with a nonce
curl -I https://${API_DOMAIN}/health         # 200, HSTS present
curl https://${API_DOMAIN}/health/ready      # {"data":{"ready":true,...}}
curl -I http://${WEB_DOMAIN}/                # 301 -> https://
```

If `/health/ready` reports `database`/`redis` as `"error"` rather than `"ok"`, check
`TRUSTED_PROXY_HOSTS` (§3) matches the actual Docker network Nginx runs on — a mismatch there is
also what silently disables HSTS (the API only trusts `X-Forwarded-Proto` from a trusted hop; an
untrusted Nginx means `request.url.scheme` is always seen as plain HTTP by the app).

## 13. Rollback procedure

Every deployable is a tagged image (`IMAGE_TAG` in the root `.env`). To roll back:

```bash
IMAGE_TAG=<previous-tag> docker compose -f docker-compose.prod.yml up -d api worker beat web
```

**Migrations do not automatically roll back.** Check whether the previous release's code is
compatible with the current (already-migrated) schema before rolling the *code* back — this
codebase's own migration discipline (expand-contract, per
`docs/product/13_DevOps_Architecture.md` §2's "Migration safety" note) is what makes this usually
safe; a migration that dropped a column the old code still reads is the one shape of rollback that
needs a database restore (`docs/deployment/DISASTER_RECOVERY.md`), not just a code rollback.

## 14. Backup verification

```bash
BACKUP_ROOT=/opt/hrms/backups ./infra/backup/pg_backup.sh
BACKUP_ROOT=/opt/hrms/backups ./infra/backup/minio_backup.sh
```

Both scripts log to `$BACKUP_ROOT/{postgres,minio}/backup.log` and delete their own backups older
than `PG_BACKUP_RETENTION_DAYS`/`MINIO_BACKUP_RETENTION_DAYS` (default 14 days each). **Cron**
(as the same user that can run `docker compose`, e.g. via `crontab -e`):

```cron
0 2 * * * BACKUP_ROOT=/opt/hrms/backups /opt/hrms/HRMS/infra/backup/pg_backup.sh >> /opt/hrms/backups/cron.log 2>&1
30 2 * * * BACKUP_ROOT=/opt/hrms/backups MINIO_ROOT_USER=... MINIO_ROOT_PASSWORD=... MINIO_BUCKET_DOCUMENTS=... /opt/hrms/HRMS/infra/backup/minio_backup.sh >> /opt/hrms/backups/cron.log 2>&1
```

(The Postgres script reads credentials from inside the running container's own environment and
needs none on the cron line; the MinIO script needs them in its own environment or the repo's root
`.env` — see the script's own comments.)

**A backup is not verified until it has been restored.** Periodically (recommended: monthly, and
always after any schema change that feels risky):

```bash
./infra/backup/pg_restore.sh /opt/hrms/backups/postgres/<latest>.dump.gz hrms_restore_check
./infra/backup/minio_restore.sh /opt/hrms/backups/minio/<latest>.tar.gz hrms-restore-check
```

Both scripts refuse to target the live database name / live bucket name, so this is safe to run
against production without any risk of overwriting real data. Both were actually run against a
locally simulated production stack while writing this runbook — see the Phase 3B audit report for
the real command output (object counts, row counts, byte-for-byte content verification of a
restored object).

## 15. Log inspection

```bash
docker compose -f docker-compose.prod.yml logs -f api worker beat nginx
```

API, worker and beat emit one JSON object per line (via `structlog`), each tagged
`"service": "api" | "worker" | "beat"`; worker and beat route Celery's own records (task received /
succeeded / failed, including the failed task's traceback) through the same JSON format. The only
plain-text lines are Celery's startup banner and shutdown notice, which Celery prints directly
rather than logging. The API's own access line (gunicorn/uvicorn) stays in uvicorn's plain-text
format. Nginx emits JSON access logs (`infra/nginx/nginx.conf`'s `json_combined` format).

**Finding everything for one request.** Every API response carries an `X-Request-Id` header, and
every error body carries the same value as `error.request_id`. Nginx generates the id when the
client sends none (or forwards the client's, which the API keeps only if it is 1–64 characters
of `A-Z a-z 0-9 . _ : -`, replacing it with a UUID otherwise). The id appears in the Nginx access
line, every API log event for the request, the `audit_log.request_id` column, and the worker log
lines of any Celery task the request enqueued:

```bash
docker compose -f docker-compose.prod.yml logs api worker nginx | grep '<request id>'
```

**Tokens are masked.** Onboarding, account-invite, password-reset and email-verification links
carry a token in the URL path. Nginx and the API access/error logs record that segment as
`[REDACTED]`, and Nginx logs paths without query strings (so presigned storage URLs never appear).
Errors log the route template (e.g. `/v1/public/onboarding/{token}`), not the raw path.

Both log streams are parseable by the same log pipeline. All
containers' logs are bounded (`docker-compose.prod.yml`'s `x-logging` anchor: `max-size: 10m,
max-file: 5` per container) so a runaway log volume cannot fill the VPS disk on its own; see §16
for the rest of the disk budget.

## 16. Disk / storage monitoring

Consumers on this VPS, roughly in order of growth rate: Postgres data (grows with tenant data and
`audit_log`/`punch` volume), MinIO data (grows with document uploads), Docker images (bounded —
old images accumulate across rebuilds unless pruned), container logs (bounded per-container by
`x-logging`, §15), backups (bounded by `*_BACKUP_RETENTION_DAYS`, §14).

```bash
docker system df                 # image/container/volume disk usage summary
docker image prune -f            # remove dangling (unreferenced) images after a rebuild
du -sh /opt/hrms/backups/*       # backup directory sizes
```

Set up a disk-usage alert (even a simple cron + `df` threshold check + email/webhook) — this
repository does not include one; it is flagged as a deferred item in the Phase 3B audit report, not
silently assumed to be someone else's problem.

## 17. Common failure cases (found and fixed during this phase — read before re-debugging them)

- **`SettingsError: error parsing value for field "cors_allowed_origins"`** — this was a real bug,
  fixed in `apps/api/src/hrms/core/config/settings.py` (the `NoDecode` annotation). If you see it
  again, you're likely running against an image built before this fix.
- **`celerybeat-schedule: Permission denied`, `beat` crash-looping** — fixed by pointing
  `--schedule` at `/tmp/celerybeat-schedule` in `docker-compose.prod.yml`'s `beat` command (`/app`
  is root-owned; the container runs as non-root `hrms`).
- **`docker build` fails on `uv sync` with `Readme file does not exist: README.md`** — fixed in
  `apps/api/Dockerfile` (README.md now copied before the first `uv sync`, which now also passes
  `--no-install-project`). If you see this, you're building from an unpatched Dockerfile.
- **`ModuleNotFoundError: No module named 'jwt'`** at API boot — `apps/api/uv.lock` was stale
  (still pinning the pre-DEP-01 `python-jose`); fixed by regenerating the lock file and adding the
  previously-undeclared-but-directly-imported `cryptography` dependency explicitly (was only
  present transitively before). If you see this, regenerate `uv.lock` (`cd apps/api && uv lock`)
  and rebuild.
- **`@next/swc-linux-x64-gnu` fails to load during `docker build` for the web image** — Alpine's
  musl libc needs `libc6-compat` (already added to `apps/web/Dockerfile`'s `deps`/`builder`
  stages). If you see this, you're building from an unpatched Dockerfile.
- **`/health/ready` reports `redis`/`database` as `"error"` even though those services are up** —
  usually `TRUSTED_PROXY_HOSTS` (§12) or a credential mismatch between the two env files (§3), not
  an actual Postgres/Redis outage. Check `docker compose logs api` for the specific exception
  before assuming a real dependency failure.
- **API refuses to boot: `email_provider must be 'smtp' for environment='production'`**
  (RELEASE_HARDENING_PHASE_5A) — `EMAIL_PROVIDER` in `apps/api/env/.env.production` is still
  `logging` (the development default) or unset. Set `EMAIL_PROVIDER=smtp` and the `SMTP_*`
  variables from your chosen SMTP provider (§4) — production/staging deliberately cannot boot with
  the logging-only sender, since it never delivers a real email.
- **API refuses to boot: `smtp_host must be set explicitly...` / `...must both be set, or both
  left empty...` / `...requires encrypted transport...`** — `EMAIL_PROVIDER=smtp` was set but one
  or more `SMTP_*` variables are missing, mismatched (a username with no password or vice versa),
  or both `SMTP_USE_TLS`/`SMTP_USE_SSL` are `false`. Fill in every `SMTP_*` value from §4 and
  enable exactly one of `SMTP_USE_TLS`/`SMTP_USE_SSL`.
- **`asyncpg.exceptions.InvalidPasswordError: password authentication failed for user "hrms_app"`,
  `api`/`migrate` crash-looping** (RELEASE_HARDENING_PHASE_6A / Finding DB-01, fixed) — the password
  segment of `apps/api/env/.env.production`'s `DATABASE_URL` doesn't match the repo root `.env`'s
  `HRMS_APP_PASSWORD` that was actually in effect when `postgres_data` was first initialized (§6).
  This is the same class of mismatch as the general credential-mismatch note in §3/§12, specific to
  this one role. If this is a fresh volume that hasn't been initialized yet, fix `.env`/
  `.env.production` to agree and recreate the volume; if `postgres_data` already has real data, use
  "Rotating the `hrms_app` database password" (§6) instead — do not recreate the volume.
