# QA environment design

Status: design only. Nothing in this document has been created. The 2026-10-26 initial gate is `BLOCKED`, not passed. Evidence: `evidence_initial_2026-10-26/ISOLATION_AND_BATCHES.md`.

This design is for a later Batch 0 (`PLT-001`) and Batch S (`AUTH-004`, `AUTH-008`, `AUTH-009`, `SEC-001`, `SEC-002` GET only). It does not approve those batches, migrations, tenant setup, or any other batch.

## Why names are not enough

`apps/api/.env` is 2971 bytes and is loaded whenever a process starts with `apps/api` as its working directory. Pydantic settings prefer a real environment variable over that file, then the file over the code defaults. The code defaults themselves are the shared stack:

| Setting | Code default if neither env nor `.env` supplies it |
|---|---|
| `database_url` | `localhost:5433`, database name `hrms_dev` |
| `redis_url` | `localhost:6380`, index 0 |
| `celery_broker` / `celery_backend` | the Redis URL above, when the Celery URLs are unset |
| `s3_endpoint_url` | unset. In development the process still boots. A storage call with no endpoint is the AWS default, not MinIO |
| `s3_bucket_documents` | empty string |
| `email_provider` | `logging` |
| `email_outbox_dispatch` | `celery` |
| `face_verification_provider` | `disabled` |

The checked-in `.env` replaces the safe email and face defaults with `hostinger` and `facepp`, and points storage at bucket `hrms-documents` on port `9000`. A process that only sets `DATABASE_URL` still inherits those values from `.env` when its cwd is `apps/api`.

`tests/conftest.py` is a second fallback and is not the runner for this programme. If `DATABASE_URL` is unset it sets `localhost:5433/hrms_dev` and `redis://localhost:6380/0` before the isolation guard runs. It then forces `EMAIL_PROVIDER=logging`, but it derives the Celery URL from that Redis host and only changes the index (default 15). Index 15 on port `6380` is still container `hrms-redis`.

`alembic/env.py` reads `MIGRATIONS_DATABASE_URL` from the environment, then from `.env` in the cwd, then from `settings.database_url`. Migrations are not part of this design's execution. A later migration step must not rely on that fallback.

## Disposable names

All of these are proposals. None exist yet.

| Resource | Name | Host port | Must not be |
|---|---|---|---|
| Postgres container | `hrms-qa-postgres` | `127.0.0.1:15433` | `hrms-postgres`, ports `5432` and `5433` |
| Database | `hrms_qa_20261026` | inside that container only | `hrms_dev`, `hrms_test`, `postgres` |
| Volume | `hrms_qa_pg_20261026` | — | `hrms_postgres_data` |
| Redis container | `hrms-qa-redis` | `127.0.0.1:16380` | `hrms-redis`, ports `6379` and `6380` |
| App Redis index | `0` on port `16380` only | — | index 0 on `6380` or `6379` |
| Celery index | `1` on port `16380` only | — | any index on `6380` |
| Object storage | `hrms-qa-minio` | `127.0.0.1:19000` and `127.0.0.1:19001` | `hrms-minio`, ports `9000` and `9001` |
| Bucket | `hrms-qa-20261026` | — | `hrms-documents` |
| Volume | `hrms_qa_minio_20261026` | — | `hrms_minio_data` |
| API | process, not a compose service of project `hrms` | `127.0.0.1:18000` | port `8000`, any process whose cwd is `apps/api` |
| Worker | separate process, same env file | no host HTTP port | the developer worker, broker on `6380` |
| Network | `hrms-qa-net` | — | the `hrms` compose network |

Images already on the machine may be reused so a later provision does not pull: `postgres:16-alpine`, `redis:7-alpine`, `pgsty/silo:latest`, `pgsty/mc:latest`. Reuse does not attach the new containers to the existing volumes.

## Configuration file

Future file, not created now: `docs/qa/comprehensive_hrms/runtime/qa.env`. It must be gitignored before it is written. It holds generated passwords and is the only file the API, worker, and runner source.

Required assignments, values described rather than copied from `apps/api/.env`:

- `DATABASE_URL` and `HRMS_APP_DATABASE_URL` use host `127.0.0.1`, port `15433`, database `hrms_qa_20261026`.
- `MIGRATIONS_DATABASE_URL` is either unset and unused, or the same host and port and database. It is never `5433` and never `hrms_dev`. This preparation does not run Alembic.
- `REDIS_URL` is `redis://127.0.0.1:16380/0`.
- `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` are `redis://127.0.0.1:16380/1`.
- `S3_ENDPOINT_URL` and `S3_PUBLIC_ENDPOINT_URL` are `http://127.0.0.1:19000`.
- `S3_BUCKET_DOCUMENTS` is `hrms-qa-20261026`.
- `EMAIL_PROVIDER=logging`.
- `EMAIL_OUTBOX_DISPATCH=none`.
- `SMTP_HOST`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `MAILTRAP_API_TOKEN`, `HOSTINGER_MAIL_API_TOKEN`, and `HOSTINGER_MAIL_MAILBOX_ID` are empty.
- `FACE_VERIFICATION_PROVIDER=disabled`. `FACEPP_API_KEY` and `FACEPP_API_SECRET` are empty.
- `LOG_TO_FILES=false`.
- `CI` and `HRMS_TEST_ALLOW_SHARED_DEV` are unset.
- `ENVIRONMENT=development`.

No payment provider and no webhook URL exist in `Settings`. The control is: do not add one, do not set SMTP, and do not start a worker until its broker line has been checked. Batch 0 and Batch S do not need the worker. The worker block exists so a later start cannot inherit `hrms-redis`.

## How a future check avoids the shared database

Do not open a client to port `5432`, `5433`, `6379`, `6380`, `9000`, or `9001`.

1. Read `/proc/<api-pid>/cwd`. It must not be `apps/api`.
2. Read `/proc/<api-pid>/environ` and the same for the worker. Compare host, port, and database name. Do not print userinfo or tokens. Empty token variables must be present and length 0, so they override `.env` rather than leaving the key absent.
3. `docker inspect` only the `hrms-qa-*` containers and confirm the published host port. Separately, `docker inspect hrms-postgres` must still show port `5433` and must not have been recreated.
4. `ss -ltnp` must show `15433` owned by `hrms-qa-postgres`, not by `hrms-postgres`.
5. Only after those four agree, a client may run `SELECT current_database()` against `127.0.0.1:15433`. The expected text is `hrms_qa_20261026`. That statement is not run in this preparation.
6. Redis proof is `redis-cli -h 127.0.0.1 -p 16380 PING` and nothing on port `6380`.
7. Bucket proof uses an `mc` alias whose URL is `http://127.0.0.1:19000` only.
8. Email proof is the environ line `EMAIL_PROVIDER=logging` plus no connection from the API PID to ports `25`, `465`, or `587`.

`GET /health` runs `SELECT 1` through the process database URL. It is not a safe probe until steps 1–5 have passed. `/health/live` does not touch the database, but it also does not prove which database the process would use. Neither probe is run now.

## What Batch S still needs later

An empty `hrms_qa_20261026` database can answer `SELECT 1`. It does not contain tenants. Batch S's catalogue preconditions need tenant A and tenant B. Creating them is the unapproved Setup batch, and the schema comes from migrations, which are a separate approval. This design does not collapse those steps into provisioning.
