# QA environment provisioning plan

Status: not approved. Do not run this sequence until a human approves it and blocker B1 is cleared (at least 4 GiB free on `/`). This file does not create containers, databases, or processes.

Batch 0 and Batch S stay unapproved. After provisioning, the next human gate is isolation proof, then those two batches only.

## Before the first command

1. `df -B1 -P /` shows at least `4294967296` bytes available. If available falls below `2147483648` bytes at any later step, stop. Do not delete developer volumes to get under the wire during the run.
2. `docker ps` still shows `hrms-postgres`, `hrms-redis`, and `hrms-minio` running. Their container IDs are recorded. Later steps must not recreate those IDs.
3. Working directory for every QA command is `docs/qa/comprehensive_hrms/runtime`, created empty, with no `.env` file in it. `apps/api/.env` is not copied and not sourced.
4. `qa.env` is created in that runtime directory, gitignored, mode `0600`. Passwords are generated there and are not written into this markdown file. `CI` and `HRMS_TEST_ALLOW_SHARED_DEV` are absent.

## Create only these resources

Use a compose project name `hrms-qa`, not `hrms`. Do not pass `-f docker-compose.yml` of the repository root. Do not mount `infra/docker/postgres/init`. That directory's `002_app_role.sh` is a grant script and stays out of this step.

1. Network `hrms-qa-net`.
2. Volume `hrms_qa_pg_20261026` on container `hrms-qa-postgres`, image `postgres:16-alpine` (already local), publish `127.0.0.1:15433:5432`, `POSTGRES_DB=hrms_qa_20261026`. No other database name.
3. Volume is not used for Redis. Container `hrms-qa-redis`, image `redis:7-alpine` (already local), publish `127.0.0.1:16380:6379`, command `redis-server --save "" --appendonly no` so it does not write a dump of developer data. This container has no volume from `hrms_redis_data`.
4. Volume `hrms_qa_minio_20261026` on container `hrms-qa-minio`, image `pgsty/silo:latest` (already local), publish `127.0.0.1:19000:9000` and `127.0.0.1:19001:9001`.
5. One `mc` command against `http://127.0.0.1:19000` creates bucket `hrms-qa-20261026` and sets anonymous access off. The alias URL is checked for port `19000` before the command runs.

Do not `docker compose up` the repository compose file. Do not `docker restart` any `hrms-*` container that is not in the list above.

## Processes, after the containers are healthy

Source `qa.env` with `set -a` from the runtime directory only.

1. API: `uvicorn` from a virtualenv that already exists, cwd = runtime directory, bind `127.0.0.1:18000`, no reload. Record the PID.
2. Worker: not started for Batch 0 or Batch S. The command, when a later batch approves it, is `celery -A hrms.core.celery_app worker` with the same sourced file, cwd = runtime directory. Until then the isolation line is `CELERY_WORKER=not-started`.
3. Runner: not pytest, not vitest, not flutter. For a later Batch 0 the command is one HTTP GET to `http://127.0.0.1:18000/health` after isolation is proved. Batch S is still waiting on migrations and tenant setup, which this plan does not perform.

`LOG_TO_FILES=false` so the API does not create `apps/api/logs`.

SMTP egress is disabled by configuration: provider `logging`, empty SMTP host, empty mail tokens, outbox dispatch `none`. No firewall rule is changed on the host. Proof is the process environment and the absence of connections to ports `25`, `465`, and `587` from the API PID.

## Isolation proof, in order

Stop on the first failure. Print `ISOLATION BLOCKED` and the failing line. Print `ISOLATION PROVED` only after all of them pass.

1. Disk still at least 3 GiB free.
2. Container names and host ports match the table in `QA_ENVIRONMENT_DESIGN.md`. `docker inspect` of `hrms-postgres` still shows port `5433` and the same container ID recorded at the start.
3. API cwd is the runtime directory. Environ host, port, and database name match `hrms_qa_20261026` on `15433`. Token variables are present and empty. `EMAIL_PROVIDER` is `logging`. `FACE_VERIFICATION_PROVIDER` is `disabled`.
4. `ss` shows `15433` owned by `hrms-qa-postgres`.
5. `SELECT current_database()` against `127.0.0.1:15433` only, expected `hrms_qa_20261026`. No client is opened to `5433`.
6. `redis-cli -h 127.0.0.1 -p 16380 PING` returns `PONG`. No client is opened to `6380`.
7. Bucket list against port `19000` contains `hrms-qa-20261026` and the command string does not contain `9000` or `hrms-documents`.
8. Worker is `not-started`. Runner command is the single health GET, not a suite.

## Monitoring and interruption

Before each process start, record `df -B1` and `MemAvailable`. While a process from this plan is running, sample both every 60 seconds. If free disk drops below 2 GiB or `MemAvailable` drops below 256 MiB, stop only PIDs recorded in this run and the containers named `hrms-qa-postgres`, `hrms-qa-redis`, and `hrms-qa-minio`. Do not stop `hrms-postgres`, `hrms-redis`, or `hrms-minio`.

If setup stops halfway:

- Leave the `hrms-qa-*` containers in place if their names match this plan. Do not drop them as part of a failed health check.
- Do not delete `hrms_postgres_data`, `hrms_redis_data`, or `hrms_minio_data`.
- Mark the in-flight case `INCONCLUSIVE`.
- A later cleanup may remove only containers, volumes, network, and bucket whose names are exactly those in the design table, and only after a human says the run is finished. `qa.env` is removed in that same cleanup because it holds generated passwords. Evidence files under `docs/qa/comprehensive_hrms/` stay.

## Explicitly not in this sequence

Migrations, grant scripts, `TRUNCATE`, tenant registration, pytest, vitest, browser tests, Celery tasks, `GET /health` during this preparation, and any connection to the shared database.
