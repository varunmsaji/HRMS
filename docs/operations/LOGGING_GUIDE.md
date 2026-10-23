# Logging Guide — Local Log Files

How the API, Celery worker and Celery Beat write **per-module log files on local disk**, and how
to read, rotate, retain and troubleshoot them. The pipeline itself (JSON contract, redaction,
event catalogue, correlation) is described in `LOGGING_AND_OBSERVABILITY.md`; this guide covers
only the file layer added on top of it. If code and this document disagree, the code is right
(`apps/api/src/hrms/core/observability/file_sink.py`, `logging.py`, `operations.py`).

## 1. Where the files are

| Run mode | Directory |
|---|---|
| Local development / bare metal / systemd | `apps/api/logs/` (the default `LOG_DIR=logs` is resolved against `apps/api`, **not** the working directory) |
| Docker (`docker-compose.prod.yml`) | `/app/logs` in the `api`, `worker` and `beat` containers, backed by the named volume `api_logs` |
| Anywhere else | Set `LOG_DIR` to an absolute path |

`logs/` is git-ignored. Every process (all gunicorn workers, all Celery pool processes, Beat)
appends to the **same** files; the `service` field (`api`, `worker`, `beat`) tells them apart.

## 2. The files

All files are JSON Lines — one JSON object per line, the same line that goes to stdout.

| File | What goes in it |
|---|---|
| `app.log` | **Every** event from every process (traceback replaced by a pointer — see §4). The place to follow one request or task end to end. |
| `errors.log` | Every ERROR-level event, **with its traceback**. The only file that contains stack traces. |
| `api.log` | `http_request` (one per request), `unhandled_exception`, `app_error`, error-handler events. |
| `auth.log` | `security.*` events (login, lockout, refresh-token reuse, authorization denials, rate limits, tenant rejections), identity and account-invite events. |
| `attendance.log` | Punches (incl. face punches), regularizations, overtime, day calculation, period reopen, face enrollment, attendance tasks. |
| `leave.log` | Leave submit/approve/reject/cancel, ledger adjustments, encashment, accrual, year-end, comp-off, leave tasks. |
| `payroll.log` | Pay-run create/lock/compute/approve/finalise/mark-paid/rollback, adjustments, payslip generation, audited payroll entities. |
| `employees.log` | Employee and employment create/update/terminate, employee imports, organisation master data. |
| `recruitment.log` | Candidate onboarding cases (create/submit/activate). *There is no separate recruitment module in this codebase; candidate onboarding is the closest feature.* |
| `documents.log` | Employee and onboarding document upload/delete/review outcomes, storage helpers. |
| `notifications.log` | `email.*` events (provider accepted, delivery failed). |
| `background_jobs.log` | `celery_*` lifecycle events, retries, final failures, fan-out incompleteness, and **every** event emitted inside a task. |
| `database.log` | `db_*` events (deadlock, pool exhausted, timeout, rollback failure), readiness dependency failures. |
| `platform.log` | Super-admin platform-console events. |

An event is written to its module file(s), `app.log`, and — if ERROR — `errors.log`. It is never
written twice to the same file.

### Routing rules (in priority order)

1. Event name: `security.*` → auth, `email.*` → notifications, `celery_*` → background_jobs,
   `db_*` → database.
2. `business.audit_recorded` → by `entity_type` (`pay_run` → payroll, `leave_application` →
   leave, `punch` → attendance, `employee_document` → documents, …).
3. Logger name prefix (`hrms.modules.attendance.*` → attendance, …). The table is
   `_LOGGER_PREFIXES` in `file_sink.py`.
4. Inside a Celery task (`task_name` bound): additionally `background_jobs`, and the module that
   owns the task (`attendance.*` → attendance, …).
5. A **failing** request (status ≥ 400, or WARNING+) is additionally written to the module that
   served it, derived from the route template (`/v1/payroll/...` → payroll).

Unknown loggers go to `app.log` only.

## 3. Record format

```json
{"outcome": "succeeded", "duration_ms": 14.2, "company_id": "…", "application_id": "…",
 "event": "leave.application.approve", "logger": "hrms.modules.leave.service",
 "request_id": "8c1f…", "level": "info", "timestamp": "2026-10-20T07:24:02.493806Z",
 "service": "api", "environment": "production"}
```

* `timestamp` is **UTC**, ISO-8601 with a trailing `Z`. Business dates in payloads use the
  company time zone separately.
* `logger` is the Python logger name; `event` is the stable event name and is the contract.
* `request_id` (API, and tasks enqueued by a request), `task_id`/`task_name` (inside tasks),
  `company_id`/`user_id` (only after membership verification), `error_code`, `duration_ms`.
* **Operation lines** (from `@logged_operation`, e.g. `payroll.pay_run.finalise`) carry
  `outcome`:
  * `succeeded` (INFO) — the service method returned. The commit is confirmed separately by the
    post-commit `business.audit_recorded` line; if only the former appears, the transaction
    rolled back.
  * `rejected` (INFO; WARNING for 403/409) — an expected 4xx business/authorization outcome with
    its stable `error_code`.
  * `failed` (ERROR) — unexpected exception or 5xx. Compact, **no traceback**; the traceback is
    logged once by the request middleware / Celery.

### Severity rules

| Level | Use |
|---|---|
| INFO | Normal lifecycle, successful operations, ordinary 4xx rejections. |
| WARNING | Conflicts (409), authorization denials (403), retries, degraded/transient dependency failures, per-item failures in a batch. |
| ERROR | Unexpected failures, 5xx, final task failure, integrity problems, incomplete fan-outs. |

Expected validation errors are never ERROR.

### What is never logged

Passwords, OTPs, tokens, cookies, authorization headers, JWTs, presigned-URL signatures, e-mail
addresses, PAN, bank/salary/CTC fields, request/response bodies, face images or templates,
provider payloads, document contents. Enforced by the shared `redact_event` processor that runs
before **both** stdout and the file sink (`core/observability/redaction.py`), and by
`@logged_operation`, which only ever reads UUID arguments from a fixed name list plus a few short
scalars (`direction`, `as_of`, …). Do not add a field to a log call unless it is an identifier,
a fixed code or a count.

## 4. Why tracebacks are only in `errors.log`

An ERROR event with an exception appears in the module file and `app.log` with
`"exception": "[traceback in errors.log]"`, and in `errors.log` with the full traceback. One stack
trace per failure, not three. Find it by `request_id`/`task_id`:

```bash
grep '"request_id": "REQ"' logs/errors.log
```

(stdout/Docker logs still carry the traceback inline.)

## 5. Configuration

Set in the environment / `apps/api/.env` / `env/.env.<stage>`:

| Variable | Default | Meaning |
|---|---|---|
| `LOG_LEVEL` | `INFO` | Minimum level for stdout **and** files (also applied to the Celery worker; the `--loglevel` flag is ignored). Use `DEBUG` temporarily only — it is verbose. |
| `LOG_TO_FILES` | `true` | `false` disables the file sink (stdout only). The test-suite forces `false`. |
| `LOG_DIR` | `logs` | Relative paths are anchored at `apps/api` (`/app`), never the cwd. Created (with parents) at startup. |
| `LOG_FILE_MAX_BYTES` | `10485760` (10 MiB) | Rotate a file when the next line would exceed this. `0` = never rotate by size. |
| `LOG_FILE_BACKUP_COUNT` | `5` | Rotated files kept per channel (`x.log.1` newest … `x.log.N` oldest). `0` = truncate instead of keeping backups. |
| `LOG_RETENTION_DAYS` | `0` | Additionally delete rotated backups older than this many days (`0` = count-based only). |
| `LOG_FILES_REQUIRED` | `false` | `true` = refuse to start if the directory is not writable. `false` = log an error on stderr and continue with stdout only. |

To change the level without redeploying code: edit the env file and restart the service
(`docker compose -f docker-compose.prod.yml up -d api worker beat`, or restart the systemd unit).

### Disk budget

Worst case per channel = `LOG_FILE_MAX_BYTES × (LOG_FILE_BACKUP_COUNT + 1)`. With the defaults
that is 60 MiB × 14 files ≈ **840 MiB** maximum, plus Docker's own stdout bound (10 MiB × 5 per
container). Lower `LOG_FILE_MAX_BYTES` or the backup count on small disks. Because
`app.log` carries everything, it is the largest file; give it a larger limit only if you need
longer history.

## 6. Rotation, retention and multiple processes

* **Size-based rotation**, performed by the process that notices the limit: `x.log` →
  `x.log.1`, `x.log.1` → `x.log.2`, …, and `x.log.<N>` is deleted. Names are predictable.
* **Multi-process safe.** The API runs several gunicorn workers, the Celery worker is a prefork
  pool, and Beat is a separate process, all writing to the same files. Python's stock
  `RotatingFileHandler` is *not* safe for that (two processes rotate the same file and one keeps
  writing into the renamed one). This implementation takes an exclusive `flock` on a hidden
  sidecar `.<name>.log.lock` file around *check size → rotate → append*, re-checks that its file
  descriptor still points at the live file before each write, and re-opens descriptors after
  `fork`. Verified with 6 concurrent processes × 150 lines and continuous rotation: no line lost,
  none torn (`test_concurrent_processes_neither_lose_nor_interleave_lines`).
* **Retention** (`LOG_RETENTION_DAYS`) removes only rotated backups whose name is exactly
  `<channel>.log.<digits>` and whose age exceeds the limit — checked on rotation and at most
  hourly. It does not delete the live file and never touches other files in the directory. The
  size/count bound is the hard bound; a very quiet channel simply stays small.
* **Trade-offs.** The lock is advisory and requires a local POSIX filesystem. **Do not put
  `LOG_DIR` on NFS/SMB.** One lock acquisition per line adds microseconds, acceptable at this
  volume (health probes are not logged). `.lock` files are expected and tiny.

## 7. Failure behaviour (logging never takes the app down)

| Situation | Behaviour |
|---|---|
| Directory missing | Created at startup (`mkdir -p`). |
| Directory not writable at startup | Probe write fails → one JSON error line on **stderr** (`file_logging_unavailable`), stdout logging continues; with `LOG_FILES_REQUIRED=true` the process refuses to start. |
| Write fails later (disk full, volume gone, permissions changed) | That file copy is dropped and counted; the request/task is unaffected; stdout is unaffected; re-opening is retried at most every 5 s. When writing works again a `log_file_writes_dropped` line records how many lines were lost. |
| Redaction fails | Only structural fields are emitted (existing behaviour). |
| Logging call itself raises | Swallowed (`safe_log`); never replaces the business result. |

## 8. Everyday commands

Run from `apps/api` (or substitute your `LOG_DIR`; in Docker use
`docker compose -f docker-compose.prod.yml exec api sh` first, or see §10).

```bash
# follow a module live
tail -f logs/attendance.log
tail -f logs/leave.log
tail -f logs/payroll.log

# the last 50 errors, human readable (needs jq)
tail -n 50 logs/errors.log | jq -r '[.timestamp,.logger,.event,.error_code,.request_id]|@tsv'

# everything about one request or task (a client shows "Reference: <id>" on failures)
grep '"request_id": "REQUEST_ID"' logs/app.log | jq .
grep '"task_id": "TASK_ID"' logs/app.log | jq .

# an error code (stable envelope code) across the API log
grep '"error_code": "CONFLICT"' logs/api.log | tail

# one employee or company (identifiers only — never names/e-mails)
grep 'EMPLOYEE_UUID' logs/attendance.log logs/leave.log logs/payroll.log
grep '"company_id": "COMPANY_UUID"' logs/app.log | jq -c '[.timestamp,.event,.level]'

# include rotated history
zgrep -h 'REQUEST_ID' logs/app.log* 2>/dev/null || grep -h 'REQUEST_ID' logs/app.log*

# security signals
jq -c 'select(.event|startswith("security."))' logs/auth.log | tail
```

Searching by **employee e-mail is deliberately impossible**: e-mails are redacted. Look the user
up in the database, then search by `user_id`.

## 9. Investigation recipes

**A failed attendance punch / regularization / calculation**

1. Get the request ID (client "Reference", or the `X-Request-Id` response header).
2. `grep REQUEST_ID logs/app.log | jq .` — read the `attendance.*` operation line
   (`outcome`, `error_code`) and the `http_request` line (`status_code`).
3. `outcome=rejected` → business rule; the `error_code` names it. `outcome=failed` →
   `grep REQUEST_ID logs/errors.log` for the traceback. Check `database.log` at the same time for
   `db_*` events, and `background_jobs.log` for `attendance_scheduled_calculate_*` if the failure
   was in the nightly job.
4. A punch with `replayed=true` was an idempotent replay, not a duplicate.

**A failed leave operation** — same steps with `logs/leave.log`; `leave.application.*` operation
lines say who (`actor_user_id`), what (`application_id`) and outcome; accrual/year-end problems
show as `leave_accrual_*` / `leave_year_end_*` in `leave.log` and `background_jobs.log`.

**A failed payroll step** — `logs/payroll.log`: `payroll.pay_run.compute|approve|finalise|…` with
`run_id`, `outcome`, `error_code` (stable codes such as `PAY_RUN_INVALID_TRANSITION`; see `modules/payroll/exceptions.py`). A rejected finalise is expected when inputs
changed; a `failed` is a bug. No amounts or salary data are ever logged — read the run in the
application.

**A failed background task**

```bash
jq -c 'select(.event|test("^celery_task_(failed|retry|unknown|rejected)|fanout"))' logs/background_jobs.log | tail
grep '"task_id": "TASK_ID"' logs/app.log | jq -c '[.timestamp,.level,.event]'
grep '"task_id": "TASK_ID"' logs/errors.log   # the traceback
```

`celery_task_finished` has `state` and `duration_ms`; `celery_task_retry` shows retry progress;
`celery_task_failed` is the final failure. Task arguments are never logged. If a task started by
a request, the same `request_id` links the API and the worker lines.

**Login / authorization trouble** — `logs/auth.log`: `security.login.failed` (`reason`),
`security.authorization.denied`, `security.rate_limited`, `security.tenant.rejected`.

**Storage / document trouble** — `logs/documents.log` (`documents.employee_document.upload`
`outcome=failed`, `exception_type`) then `errors.log`.

## 10. Docker and persistence

* `docker compose logs` shows only stdout, bounded by Docker's `json-file` driver (10 MiB × 5);
  **it disappears when a container is re-created.**
* The files live on the named volume `api_logs`, shared by `api`, `worker` and `beat`, so they
  **survive restarts and re-creation** but **not** `docker compose down -v` or deleting the
  volume. The image creates `/app/logs` owned by the non-root `hrms` user (uid 1000) so a fresh
  volume is writable.
* To read them on the host:

  ```bash
  docker run --rm -v hrms-prod_api_logs:/logs:ro alpine sh -c 'ls -la /logs && tail -n 20 /logs/errors.log'
  docker compose -f docker-compose.prod.yml exec api tail -f /app/logs/attendance.log
  docker volume inspect hrms-prod_api_logs   # Mountpoint: readable by root on the host
  ```

* Prefer a host directory? Replace the volume with a bind mount
  (`- /var/log/hrms:/app/logs`) and `chown 1000:1000 /var/log/hrms` first.
* systemd / bare metal: set `LOG_DIR=/var/log/hrms` in the unit's `EnvironmentFile`, make the
  directory writable by the service user, and run `api`, `worker`, `beat` as the **same** user so
  that file ownership and the lock files match.

## 11. Verify after deployment

```bash
# 1. files exist and are growing
docker compose -f docker-compose.prod.yml exec api sh -c 'ls -la /app/logs'
# 2. a request lands in api.log with the id you sent
curl -s -o /dev/null -H 'X-Request-Id: smoke-check-1' https://$API_DOMAIN/v1/auth/me
docker compose -f docker-compose.prod.yml exec api grep smoke-check-1 /app/logs/api.log /app/logs/app.log
# 3. the worker writes too (service=worker) and Beat's heartbeat task is recorded
docker compose -f docker-compose.prod.yml exec api sh -c "grep -h '\"service\": \"worker\"' /app/logs/background_jobs.log | tail -n 3"
# 4. nothing is being dropped
docker compose -f docker-compose.prod.yml exec api sh -c "grep -l 'log_file_writes_dropped\|file_logging_unavailable' /app/logs/*.log /dev/null; true"
docker compose -f docker-compose.prod.yml logs --since 10m api | grep file_logging_unavailable
```

## 12. Limitations — read before relying on these files

* Local files are **not tamper-proof**: anyone with write access to the volume can edit them.
  They are not an audit trail — the Postgres `audit_log` remains the system of record for
  business changes.
* They are **not centrally searchable** (no aggregation across hosts) and **not backed up** unless
  you add that (the existing backup scripts do not include the log volume). Old data is deleted
  by rotation by design.
* Access control = filesystem permissions (files are created `0640`). Logs contain user IDs,
  company IDs, IP addresses and request paths, which are personal data; restrict who can read the
  volume and decide a retention period with compliance input (decision D2 in the observability
  plan).
* Timestamps come from the host clock (UTC); keep NTP running.
* Single-host only; no NFS; if the volume fills up, log lines are dropped (counted), the app keeps
  running — monitor disk space and `log_file_writes_dropped`.
* Sub-second ordering across processes follows lock acquisition order, not event time — sort by
  `timestamp` when reconstructing a sequence.
