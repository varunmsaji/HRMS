# Initial QA gate — 2026-10-26T17:15:24+0530

Environment id: none. No `hrms_qa_*` database was found or created.

## Isolation

`ISOLATION BLOCKED`

`ISOLATION PROVED` was not printed.

| Point | Result | Evidence |
|---|---|---|
| 1 Database | Fail | Process environment has `DATABASE_URL`, `MIGRATIONS_DATABASE_URL`, and `HRMS_APP_DATABASE_URL` unset. `apps/api/.env` fallback is host `localhost`, port `5433`, database `hrms_dev`. Container `hrms-postgres` is up and publishes `5433`. No URL uses host `127.0.0.1` and a name starting with `hrms_qa_`. `SELECT current_database()` was not run, because the only configured database is the shared one. |
| 2 Redis and broker | Fail | `REDIS_URL`, `CELERY_BROKER_URL`, and `CELERY_RESULT_BACKEND` are unset in the process environment. `.env` fallback is `localhost:6380`, path empty (index 0). Container `hrms-redis` publishes `6380`. Ports `6379` and `6380` are both listening. No disposable broker answered `PING`. |
| 3 Bucket | Fail | `.env` fallback endpoint is `http://localhost:9000`, bucket `hrms-documents`. Container `hrms-minio` publishes `9000` and `9001`. No `hrms-qa-<run-id>` bucket was created. |
| 4 Email | Fail | `.env` `EMAIL_PROVIDER` is `hostinger`, not `logging`. Mail tokens are set. No capture probe was sent. |
| 5 API | Fail | Nothing is listening on port `8000`. No disposable API PID exists. Starting one from `apps/api` would load the `.env` fallback above. |
| 6 Celery | Not started | `CELERY_WORKER=not-started` would be allowed only for a batch that needs no worker, and only after the other points pass. They do not. No worker was started. |
| 7 Runner | Fail | No test command was started. A runner whose settings load `apps/api/.env` (2971 bytes, non-empty) would inherit the shared targets. |
| 8 Grants and schema | Not run | No `ALTER`, `CREATE`, `DROP`, grant script, or migration was executed. There is still no `hrms_qa_*` database they could target. |

Also observed and left untouched: system Postgres on `127.0.0.1:5432`, system Redis on `127.0.0.1:6379`, `FACE_VERIFICATION_PROVIDER=facepp`. `CI` and `HRMS_TEST_ALLOW_SHARED_DEV` are unset. Secret values were not printed.

Disk before any start: filesystem `/dev/nvme0n1p6`, available `3269398528` bytes (3.045 GiB). The 3 GiB gate is met. The margin above 3 GiB is about 46 MiB, so a new database or container was not created. Memory available about 6.4 GiB. No sample loop was needed because no batch started.

## Batch 0

| Case | Status | Expected | Actual |
|---|---|---|---|
| PLT-001 | BLOCKED | `GET /health` returns 200 and the body has no email, person name, or company list | Not requested. No disposable API URL exists. |

## Batch S

Approved read-only ids are `AUTH-004`, `AUTH-008`, `AUTH-009`, `SEC-001`, and `SEC-002` GET only. None were called.

| Case | Status | Why |
|---|---|---|
| AUTH-004 | BLOCKED | Isolation blocked. No company API was called. |
| AUTH-008 | BLOCKED | Needs a signed-in company A user. Setup was not approved, and isolation blocked. |
| AUTH-009 | BLOCKED | Needs tenant B. Setup was not approved, and isolation blocked. |
| SEC-001 | BLOCKED | Needs both tenants populated. No list was requested. |
| SEC-002 GET | BLOCKED | Needs an id from tenant A. The PATCH half of this case was not approved and was not sent. |

No response contained another tenant's data because no application request was made. No cross-tenant mutation was observed. No PATCH, punch POST, DELETE, raw SQL, or worker job was issued.

## Cleanup

No process was started by this gate. No database, Redis index, bucket, or container was created or removed. Existing containers `hrms-postgres`, `hrms-redis`, and `hrms-minio` were left running.

## Git at evidence time

Branch `main`, commit `436a2e5e35b97ae65b27f9553e2317e9b7f6f7b0`. `git status --porcelain=v1` had 263 lines and content hash `db2dc52f1f2ec8c7b8f6a4dba22bb60c730b1182` immediately before this file was added.
