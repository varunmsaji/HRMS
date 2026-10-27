# QA environment blockers

Measured 2026-10-26T17:22:24+0530. No cleanup was performed.

## Initial attempt

The initial gate is `BLOCKED`, not passed. `ISOLATION PROVED` was not printed. `PLT-001` and Batch S were not requested. Record: `evidence_initial_2026-10-26/ISOLATION_AND_BATCHES.md`.

## Blockers

| ID | Blocker | Why provisioning waits |
|---|---|---|
| B1 | Disk headroom | `/` has `3261480960` bytes free (3.038 GiB). That is `40255488` bytes, about 38 MiB, above the 3 GiB gate. It is not enough for a new volume, overlay metadata, logs, and a later cleanup margin. Provisioning does not start until free space is at least 4 GiB (`4294967296` bytes), so the 3 GiB gate still holds after the new volumes exist. Hard stop remains 2 GiB. |
| B2 | Shared stack is the only live data plane | `hrms-postgres` publishes `5433` and mounts `hrms_postgres_data`. `hrms-redis` publishes `6380` and mounts `hrms_redis_data`. `hrms-minio` publishes `9000-9001` and mounts `hrms_minio_data`. No `hrms-qa-*` container or `hrms_qa_*` database exists. |
| B3 | `.env` fallback | `apps/api/.env` selects database `hrms_dev`, Redis port `6380`, bucket `hrms-documents`, `EMAIL_PROVIDER=hostinger`, and `FACE_VERIFICATION_PROVIDER=facepp`. Mail and face tokens are non-empty. Settings load that file from the process cwd. |
| B4 | Code defaults match the shared stack | An empty environment still defaults `database_url` to `hrms_dev` on port `5433` and `redis_url` to `localhost:6380/0`. Celery uses those Redis URLs when its own URLs are unset. |
| B5 | Health is not a read-only local probe | `GET /health` executes `SELECT 1` on the configured database. It must not be called until the process URL is proved to be `127.0.0.1:15433/hrms_qa_20261026`. |
| B6 | Batch S data is a later approval | Tenant registration and migrations are not part of environment provisioning. Batch S stays blocked until those are separately approved, even after a disposable database exists. |
| B7 | No payment or webhook switch to turn off | `Settings` has no payment or webhook field. Safety is "do not configure SMTP or a live provider", not a flag that was found and set. |

Memory is not a blocker. `MemAvailable` was about 6.6 GiB. Swap free was about 1.3 GiB of 2.0 GiB.

## Disk recovery candidates

Nothing below was deleted. Ownership is not a licence to remove it.

Do not remove, in any later cleanup of this programme:

| Target | Owner | Reason |
|---|---|---|
| Containers `hrms-postgres`, `hrms-redis`, `hrms-minio` | this repo's `docker-compose.yml`, project `hrms`, running 12 hours | shared developer stack |
| Volumes `hrms_postgres_data`, `hrms_redis_data`, `hrms_minio_data` | those three containers | developer data |
| `apps/api/.env` | local developer config | contains the live shared targets and tokens |
| `docs/qa/comprehensive_hrms/evidence_initial_2026-10-26/` | this QA programme | blocked-run evidence |
| System Postgres on `127.0.0.1:5432` and system Redis on `127.0.0.1:6379` | other local projects | forbidden ports, not ours to stop |

Candidates a human can review. Sizes are Docker's reported figures, not a promise of how much `df` will recover:

| Candidate | Reported size | Ownership | Notes |
|---|---|---|---|
| 17 dangling images | part of 5.956 GiB image reclaim | Docker, no running container | Safest image reclaim if the human recognises them as untagged leftovers |
| Build cache, 1.001 GiB reclaimable of 3.886 GiB | Docker builder | Rebuilds will repopulate it | Do not prune the cache that belongs to an in-progress build |
| `hrms-api:prefinal-gate`, `hrms-api:liveness-local` | 724 MiB each | local tags from earlier HRMS image builds, not running | Recoverable only by rebuilding. Do not delete `hrms-api:latest` without a separate decision |
| `minio/minio:latest`, `quay.io/minio/mc:latest`, `bitnamilegacy/minio*` | hundreds of MiB | old images. The live MinIO is `pgsty/silo:latest` | Confirm no other project still starts the old image |
| Exited containers `prefinal-pg`, `prefinal-redis`, `prefinal-minio` and their anonymous volumes | small container layer, volume size not measured | a previous prefinal run, exited 7 days | Not proved disposable. Leave them |
| Exited `hopeful_poitras`, `peaceful_franklin`, `focused_sutherland`, `fervent_meninsky` | up to about 97 MiB writable layer on one of them | anonymous Docker names, exited 9 days to 4 weeks | Owner unknown. Do not remove |
| `hirico-db-test`, `hirico-test-postgres`, volume `hirico_pgdata` | unmeasured | name is another project, volume unmounted | Not HRMS QA's to delete |
| 39 unmounted anonymous volumes | part of 1.288 GiB volume reclaim | no current container mount | Owner not proved. Inspect labels before any removal |

The running HRMS volumes are the ones that must survive. Freeing the dangling images and the reclaimable build cache is the recovery path most likely to create the missing 1 GiB without touching developer data. That path still needs a human decision. This task did not run `docker system prune` or delete any volume.

## External side effects

`EMAIL_PROVIDER=hostinger` is active in `.env`. No message was sent. The designed QA file forces `logging`, an empty SMTP host, empty provider tokens, and `EMAIL_OUTBOX_DISPATCH=none`. Face verification is forced to `disabled`. No webhook or payment endpoint is configured.
