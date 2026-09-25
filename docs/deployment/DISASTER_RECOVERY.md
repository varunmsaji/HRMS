# Disaster Recovery

RELEASE_HARDENING_PHASE_3B. Companion to `docs/deployment/PRODUCTION_DEPLOYMENT.md` (normal
deployment) — this document covers recovery from loss or corruption of the VPS, the database, the
object store, or a critical secret.

## The one thing that matters most: `PII_MASTER_KEY`

Every PAN, Aadhaar, and bank account number in this system is stored as AES-256-GCM ciphertext,
with the data-encryption key (DEK) itself wrapped under `PII_MASTER_KEY`
(`apps/api/src/hrms/core/crypto/master_key.py`, RELEASE_HARDENING_PHASE_3A §9). **If this key is
lost, every existing PII field becomes permanently, mathematically unrecoverable — not merely
inconvenient to restore, but gone.** It is not stored in the database (only a one-way SHA-256
fingerprint of it is, in `encryption_keys.wrapping_key_id`, for record-keeping only — the
fingerprint cannot be reversed back into the key), not in the application image, not in this
repository, and this document does not print it or ask you to.

**Required operational practice** (not automated by anything in this repo — a deliberate,
human-owned control, since automating "back up the master encryption key" tends to mean "put it
somewhere an attacker who compromises the VPS can also read it," defeating the point):

1. Generate it once, at first deployment (`docs/deployment/PRODUCTION_DEPLOYMENT.md` §4).
2. Store it in a secrets manager, password manager, or offline vault **that is not this VPS** and
   not a backup that lives on this VPS either — losing the VPS must not also lose this key.
3. Restrict access to the smallest number of people/systems that genuinely need it.
4. Never rotate it casually — rotation requires the DEK-rewrap procedure
   (`hrms.core.crypto.provisioning.rotate_key`), not just generating a new value and swapping the
   environment variable (that would make every *existing* DEK, wrapped under the old key,
   unreadable).
5. Test recovery periodically: can the person/system responsible for holding this key actually
   produce it within your target recovery time, without the VPS?

If you lose this key with no copy elsewhere, the honest recovery procedure is: rotate to a new key
for all *future* data, and treat existing PAN/Aadhaar/bank fields as unrecoverable — there is no
cryptographic way around this, by design (that is what "encrypted at rest" means).

## JWT signing secrets

`JWT_ACCESS_SECRET`/`JWT_REFRESH_SECRET` are lower-stakes than `PII_MASTER_KEY` — losing them does
**not** lose any data, only invalidates every currently-issued access/refresh token (every user
gets logged out and must log in again). Store them the same way as `PII_MASTER_KEY` (§ above) for
convenience, but a loss here is a user-experience incident, not a data-loss incident. A restart
with the **same** secret does not log anyone out; a restart with a **different** secret does — this
is why `apps/api/env/.env.production` must be a stable, persisted file, not regenerated on every
deploy (`Settings` never generates a secret automatically — see
`Settings._guard_non_development_config`, which fails boot rather than falling back to a random or
default value).

## PostgreSQL restore

Full step-by-step restore procedure (not a test-only restore — this is the real-outage path):

```bash
# 1. Stand up a fresh Postgres container if the VPS itself was lost (docs/deployment/
#    PRODUCTION_DEPLOYMENT.md §5-6 on the new VPS), otherwise skip to step 2.

# 2. Restore into a NEW database name first — never directly into the name the application
#    points at — using infra/backup/pg_restore.sh (same script used for routine restore
#    verification, docs/deployment/PRODUCTION_DEPLOYMENT.md §14):
./infra/backup/pg_restore.sh /opt/hrms/backups/postgres/<chosen-backup>.dump.gz hrms_prod_restored

# 3. Once you've confirmed the restored database looks right (row counts, spot-check recent
#    records — the restore script already prints row counts for company/user/employment), point
#    the application at it: update apps/api/env/.env.production's DATABASE_URL/
#    MIGRATIONS_DATABASE_URL to the restored database name, OR rename databases inside Postgres
#    (DROP the broken one, ALTER DATABASE hrms_prod_restored RENAME TO hrms_prod) if you'd rather
#    not touch the env file. Either is safe; renaming is fewer moving parts.

# 4. Run migrations to catch the restored database up to the currently-deployed code's expected
#    schema, if the backup predates a migration that has since shipped:
docker compose -f docker-compose.prod.yml --profile tools run --rm migrate

# 5. Restart the application tier:
docker compose -f docker-compose.prod.yml up -d api worker beat
```

**Recovery point**: data since the last successful `pg_backup.sh` run is lost (default: up to 24h,
if backups run nightly per the cron example in the deployment runbook — tune
`PG_BACKUP_RETENTION_DAYS`/backup frequency to your actual acceptable data-loss window; this repo
ships a working backup mechanism, not a specific RPO commitment, since that's a business decision
this phase's own scope doesn't make on your behalf).

## MinIO (document storage) restore

```bash
./infra/backup/minio_restore.sh /opt/hrms/backups/minio/<chosen-backup>.tar.gz hrms-prod-documents-restored
```

Then either update `apps/api/env/.env.production`'s `S3_BUCKET_DOCUMENTS` to the restored bucket
name, or (simpler) `mc mv`/re-mirror the restored objects into the bucket name the application
already expects, after first confirming the original bucket is actually gone/corrupted (don't
overwrite a bucket that's merely *suspected* damaged without checking first).

**Important**: Postgres and MinIO backups are not taken atomically together. A document uploaded
between the two backup runs can end up referenced in Postgres (an `employee.*_document_key`
column) with no matching object in a MinIO restore taken from a slightly earlier point, or vice
versa. This is an accepted, documented gap for a single-VPS deployment without a distributed
transaction mechanism across two independent storage systems — not a hidden defect. Minimize the
window by running both backup scripts back-to-back (see the cron example in the deployment
runbook, which schedules them 30 minutes apart deliberately to avoid overlapping load, not because
a wider gap is desirable).

## Encryption master-key recovery

Covered above (§"The one thing that matters most"). There is no separate technical recovery
procedure beyond "produce the key from wherever it was stored" — that is the entire point of
storing it outside the VPS.

## JWT secret recovery

Generate new values (`openssl rand -base64 48`) and update `apps/api/env/.env.production`, then
restart `api`/`worker`/`beat`. Every existing session is invalidated; no data is lost. Communicate
to users that they'll need to log in again if this happens outside a planned rotation.

## Application restart

```bash
docker compose -f docker-compose.prod.yml restart api worker web
```

`beat` should usually restart too if `worker`/`api` did (same deploy), but never run more than one
`beat` replica — restart it alone if it's the only one that crashed, don't scale it.

## Migration recovery

If a migration itself fails partway (rare with this codebase's expand-contract discipline, but
possible): `alembic` migrations in this repo each run in their own transaction by default (standard
Alembic/PostgreSQL behavior — DDL is transactional in Postgres, unlike MySQL), so a failed
migration rolls back cleanly rather than leaving the schema half-migrated. Check
`alembic current` against `alembic heads` inside the `migrate` service to confirm where the
database actually landed, fix whatever caused the failure, and re-run
`docker compose -f docker-compose.prod.yml --profile tools run --rm migrate`.

## Rollback

See `docs/deployment/PRODUCTION_DEPLOYMENT.md` §13 — covered there since it's a routine operational
procedure, not strictly a disaster-recovery one, but the same command applies during an incident.

## What happens if the VPS is lost entirely

Everything the application needs to run again lives in exactly three places, and only one of them
is required to live *outside* the VPS:

| What | Where it lives today | Survives VPS loss? |
| --- | --- | --- |
| Application code | This Git repository (pushed to a remote) | Yes |
| Postgres data | `postgres_data` Docker volume, on the VPS's own disk | **No** — restore from the latest `pg_backup.sh` output, which must itself live off-VPS (§ below) |
| MinIO document data | `minio_data` Docker volume, on the VPS's own disk | **No** — restore from the latest `minio_backup.sh` output, same off-VPS requirement |
| `PII_MASTER_KEY` | Wherever you stored it per this document's first section | **Only if you followed that section** |
| `JWT_ACCESS_SECRET`/`JWT_REFRESH_SECRET` | `apps/api/env/.env.production`, on the VPS's own disk | **No**, but losing them is not a data-loss event (see above) — regenerate |
| Let's Encrypt certificates | `certbot_certs` Docker volume | No, but trivially re-obtained (docs/deployment/PRODUCTION_DEPLOYMENT.md §11) once DNS points at a new VPS |

**This means: `infra/backup/pg_backup.sh` and `infra/backup/minio_backup.sh`'s output directory
(`$BACKUP_ROOT`) must itself be copied somewhere off this VPS on a schedule** — this repository's
backup scripts write to local disk only (by design: no AWS S3, no paid external destination added
without a decision to spend on one — see the cost/operational note below). A single-VPS deployment
where backups only ever live on that same VPS's disk protects against data corruption/accidental
deletion but **not** against VPS loss (hardware failure, provider account loss, etc.) — closing
that gap requires one of:

- A cheap, non-AWS off-site copy: `rsync`/`rclone` to a second, small VPS or a self-hosted target
  you control, on a cron schedule after each backup script completes.
- A backup-focused object storage provider (e.g. Backblaze B2, Hetzner Storage Box) — not AWS S3,
  consistent with this deployment's cost-constrained, no-AWS architecture, but still a real
  recurring cost this phase does not commit you to without you choosing it.

This repository does not pick one of these for you — it is flagged here, and in the Phase 3B audit
report's Remaining Risks, as a deliberate, currently-open decision rather than something silently
assumed to be handled.

## Recovery drill

Run this periodically (recommended: quarterly), and always after any significant infrastructure
change:

1. `./infra/backup/pg_restore.sh` the most recent backup into a scratch database — confirm row
   counts look plausible for current data volume.
2. `./infra/backup/minio_restore.sh` the most recent backup into a scratch bucket — confirm object
   count and spot-check one document's content.
3. Confirm whoever holds `PII_MASTER_KEY` can actually produce it on request, within your target
   time.
4. Time the whole exercise — that's your actual, current recovery time, not an estimate.
