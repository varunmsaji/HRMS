# HRMS Backup & Disaster Recovery Plan

## 1. Current state (verified [REPO])

| Item | Today | Gap |
|---|---|---|
| Postgres | `infra/backup/pg_backup.sh`: `pg_dump -Fc | gzip` into `BACKUP_ROOT/postgres/` on the **same VPS**, 14-day local retention, partial-file cleanup | no encryption, no off-server copy, no checksum/verify step, no scheduler (cron/systemd timer) in repo, no WAL/PITR ⇒ RPO = time since last dump |
| Restore | `infra/backup/pg_restore.sh` restores into a **new** DB name; DR doc describes the procedure | **No evidence a restore has been tested on a production-like dump** — treat backups as unproven |
| Objects | `infra/backup/minio_backup.sh` / `minio_restore.sh` | no off-server target found |
| Secrets | `PII_MASTER_KEY` custody described in `DISASTER_RECOVERY.md` as a human control | no verified escrow; losing it makes PAN/Aadhaar/bank data unrecoverable |
| Snapshots | Hostinger snapshots possible | same provider/account; not DR |

## 2. Objectives (proposed, to be approved)

| Tier | RPO | RTO |
|---|---|---|
| Pilot (dumps only) | 24 h → hourly dumps = 1 h | 4 h |
| **Production (PITR)** | **≤ 5 min** (WAL archive) | **≤ 2 h** (new VPS from images + restore) |
| Documents | ≤ 24 h (versioned bucket replicated) | with DB |

## 3. Design

| Asset | Method | Frequency | Retention | Location | Encryption |
|---|---|---|---|---|---|
| PostgreSQL | pgBackRest (full weekly, diff daily, WAL continuous) to S3-compatible bucket **in another provider/account** | WAL continuous, diff daily 02:00 UTC | 35 d PITR window; weekly fulls 12 w; monthly 12 m | off-server | pgBackRest repo cipher `aes-256-cbc` + bucket SSE; key held in password manager/vault |
| PostgreSQL logical safety net | `pg_dump -Fc` nightly via `pg_backup.sh` + `age` encryption + upload; keep 7 locally | daily | 30 d offsite | off-server | `age` public key; private key offline |
| Documents bucket | bucket versioning + cross-account replication or nightly `rclone sync --immutable` to second bucket | continuous / nightly | 90 d noncurrent | second provider | SSE + client-side `rclone crypt` optional |
| Config | `.env` files, compose, nginx conf encrypted (`sops`/`age`) in a private repo or vault | on change | all versions | private repo + offline copy | yes |
| Secrets | `PII_MASTER_KEY`, JWT secrets, DB passwords: two independent custodians, vault + printed sealed copy | on change | – | not on VPS, not in backup bucket with the data | – |
| Redis | not backed up (broker/rate-limit state; AOF on volume only) | – | – | – | – |

Backup monitoring: job writes success timestamp; alert if last success >26 h (dumps) or WAL archive lag >10 min; `pgbackrest check` daily; alert on failure.

## 4. Verification & restore tests

| Test | Schedule | Pass criteria |
|---|---|---|
| Automated: restore latest dump into scratch container, run `alembic current`, row-count sanity, `SELECT` as `hrms_app` under RLS, tenant isolation smoke test | weekly (CI/cron on separate machine) | completes <30 min, counts within 1 % of expected |
| PITR drill: restore to a timestamp 1 h ago on a throwaway VPS | monthly | target time reached; data at that second |
| Full DR game day: new VPS from scratch (DB + objects + secrets) | quarterly, and before launch | measured RTO ≤ 2 h; document download works; login works; `PII_MASTER_KEY` decrypts a PAN |
| Key custody check: custodian produces `PII_MASTER_KEY` without VPS access | semi-annually | success |

**Do not claim recoverability until the pre-launch game day has passed and its timings are recorded here.**

## 5. Restore runbook (S1 – VPS lost / S2 – DB corrupted / S3 – bad deploy or accidental delete)

S1 – total loss
1. Provision replacement VPS (Runbook §A steps 1–4); point DNS (low TTL) when ready.
2. Retrieve secrets from vault (`PII_MASTER_KEY` first); recreate env files.
3. `docker compose up -d postgres` with an *empty* volume; stop nothing else yet.
4. `pgbackrest --stanza=hrms --type=time --target="<UTC time>" restore` (or latest); start Postgres in recovery, wait for promotion. Without PITR: `./infra/backup/pg_restore.sh <dump> hrms_prod_restored`, verify, rename.
5. Confirm roles exist (`hrms_app` NOBYPASSRLS – run init script `002_app_role.sh`); `alembic current` equals the deployed tag's head (if behind, run `migrate`).
6. Restore document bucket (re-point `S3_*` to replica or `rclone sync` back).
7. Start `redis`, `minio`(if used), `api`, `worker`, `beat`, `web`, `nginx`; reissue TLS certificate.
8. Verify: `/health/ready`, login for a test tenant, attendance record read, payslip PDF download, document download, Celery ping. Run `T-01` tenant-isolation test against the restored DB.
9. Declare recovery; record achieved RPO/RTO; post-incident review.

S2 – corruption/accidental deletion: restore PITR to a **new** DB at a timestamp before the incident, export the affected rows, merge into live DB inside a transaction after review; never overwrite production blindly.
S3 – bad deploy: Runbook §B steps 9–10.

## 6. Retention & privacy

Payroll/attendance retention per statutory requirement (confirm with counsel; commonly several years); backups of deleted employees persist until expiry – document in the privacy notice; encrypted backups only; restore access limited to two named admins; every restore logged.
