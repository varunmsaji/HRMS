# Observability runbook

How to investigate and recover the failures Krewoxa HRMS can actually have. Every section follows the same order: **symptoms, inspect first, logs and metrics, correlate, commands, healthy looks like, common causes, safe recovery, escalate when, verify after.**

> **Environment note.** Repository paths, log field names, metric names and the `python -m hrms.ops.job_health` command are verified against the code (2026-10-25). Commands that start with `docker compose -f docker-compose.prod.yml` assume the layout of `docker-compose.prod.yml` and a shell in the deployment directory; the production VPS has **not** been inspected, so treat them as *examples* and adjust service names / paths. Nothing here is a destructive command; recovery steps never delete data, flush Redis or purge a queue.

## 0. Toolbox (read once)

**Log files** (one JSON object per line; volume `api_logs` mounted at `/app/logs` in `api`, `worker`, `beat`): `api.log auth.log attendance.log leave.log payroll.log employees.log recruitment.log documents.log notifications.log background_jobs.log database.log platform.log`, plus `app.log` (everything, no tracebacks) and `errors.log` (ERROR+, the only file with tracebacks). Rotation: 10 MB x 5 backups per file (`LOG_FILE_MAX_BYTES`, `LOG_FILE_BACKUP_COUNT`). Details: [LOGGING_GUIDE.md](LOGGING_GUIDE.md).

**Correlation keys** (present on every line of a request and of the Celery task it dispatched):

| Key | Where it comes from |
|---|---|
| `request_id` | response header `X-Request-Id`; also in the error envelope `meta.request_id` and in `audit_log.request_id` |
| `trace_id`, `span_id` | the inbound `traceparent` header if valid, else generated; carried onto task messages (`hrms_traceparent`) |
| `task_id`, `task_name` | Celery, in the worker's log context |
| `company_id`, `user_id` | only when membership-verified; the way to learn *which tenants* are affected without reading their data |

```bash
# everything one request/trace did, across API and worker (example)
docker compose -f docker-compose.prod.yml exec -T api sh -c 'grep -h "<request-or-trace-id>" /app/logs/*.log' | jq -c '{timestamp,service,logger,event,level,status_code,error_code,error_category}'

# which tenants are affected by an error burst (counts only, no tenant data)
docker compose -f docker-compose.prod.yml exec -T api sh -c 'tail -n 5000 /app/logs/errors.log' | jq -r 'select(.company_id) | .company_id' | sort | uniq -c | sort -rn | head

# error categories in the last 5000 error lines
docker compose -f docker-compose.prod.yml exec -T api sh -c 'tail -n 5000 /app/logs/errors.log' | jq -r '.error_category // .event' | sort | uniq -c | sort -rn | head
```

**Metrics** (when Prometheus is deployed; otherwise scrape by hand, example):
`curl -s -H "Authorization: Bearer $METRICS_TOKEN" http://api:8000/metrics` from a container on the `data` network (`/metrics` is 404 from the internet and unless `METRICS_TOKEN` is set).

**Health:** `curl -s http://127.0.0.1:8000/health/live` (process only), `/health/ready` (Postgres + Redis + storage config; 503 when not ready), `python -m hrms.ops.job_health` in the worker (read-only; exit 0 ok / 1 check failed / 2 Redis unreachable), `infra/monitoring/hrms_monitor.sh` (host monitor).

**Reading outcomes:** an operation event `outcome=rejected` is an expected business result; `failed` is a server-side failure; `succeeded` means the method returned - the committed fact is `business.audit_recorded`.

<a id="api-5xx-503"></a>
## 1. API returning 500 or 503

**Symptoms.** Users see 'Something went wrong' / errors; `HrmsHigh5xxRate`, `HrmsUnhandledExceptions`, `HrmsApiDown` firing; Nginx 502/504.

**Inspect first.** Is it the whole API (`/health/live`) or particular routes? `/health/ready` tells whether Postgres/Redis are the cause (503 with `database`/`redis` = `error`).

**Logs and metrics.** Metric `hrms_http_requests_total{status_class="5xx"}` by `route`; `hrms_errors_total` by `source`/`category` (`http_unhandled` = bug, `http_db_error` = database, `http_app_error` = dependency); `hrms_dependency_up`. Logs: `errors.log` events `unhandled_exception`, `app_error`, `db_error`, `db_wait_timeout`.

**Correlate.** Take a `request_id` from a failing response (`X-Request-Id`) and grep it (toolbox). `unhandled_exception` carries the traceback; `error_category` says why.

**Diagnostic commands (examples).**
```bash
docker compose -f docker-compose.prod.yml ps
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/health/live
curl -s http://127.0.0.1:8000/health/ready
docker compose -f docker-compose.prod.yml logs --since 15m api | jq -c 'select(.level=="error")' | head
```

**Healthy looks like.** `/health/live` 200, `/health/ready` 200 with `ready:true`, 5xx ratio under 1%, no `unhandled_exception` events.

**Common causes.** A bad deploy (new `unhandled_exception` type right after release); Postgres or Redis down (`readiness_dependency_failed`); pool exhaustion (`db_pool_exhausted`, see section 9); an unreachable provider (`app_error` 502/503/504).

**Safe recovery.** Fix or roll back the *code* with the normal deploy procedure; for a dependency, follow its section. Do not restart the API repeatedly - it hides the first traceback, which is in `errors.log` and survives restarts (volume).

**Escalate when.** `/health/live` itself fails, the container restart-loops (`restart_count` rising in `hrms_monitor.sh`), or the cause is not a dependency and not the last deploy.

**Verify after recovery.** 5xx ratio back under 1% for 10 minutes; `hrms_http_unhandled_exceptions_total` flat; `/health/ready` 200.

<a id="slow-requests"></a>
## 2. Slow API requests

**Symptoms.** Complaints of slowness; `HrmsLatencyP95Degraded` / `HrmsLatencyP99High`.

**Inspect first.** Which routes: panel *Slowest routes (p95)* or `histogram_quantile(0.95, sum by (le, route)(rate(hrms_http_request_duration_seconds_bucket[5m])))`.

**Logs and metrics.** `hrms_db_query_duration_seconds` (is the database slow?), `hrms_db_pool_checked_out`/`capacity` (waiting for connections?), `hrms_dependency_call_duration_seconds` (provider slow?), `hrms_operation_duration_seconds{operation}` (which business operation). Logs: `http_request` events with `duration_ms` >= threshold; `operation` events with `duration_ms`.

**Correlate.** Pick a slow `request_id` from `api.log` (`jq 'select(.event=="http_request" and .duration_ms>2000)'`) and read the other lines with the same id: the operation line and any `db_*`/provider line show where time went.

**Diagnostic commands (examples).**
```bash
docker compose -f docker-compose.prod.yml exec -T api sh -c 'tail -n 20000 /app/logs/api.log' | jq -c 'select(.event=="http_request" and .duration_ms>2000) | {http_path,duration_ms,status_code,request_id}' | head -20
```

**Healthy looks like.** p95 under 1 s for interactive routes; pool `checked_out` well under `capacity`.

**Common causes.** Missing index on a growing table; one company with a very large dataset on a report; the pool saturated by slow queries; a slow provider (Face++) on the punch path; payroll compute (synchronous, runs inside the request).

**Safe recovery.** Identify the route and the cause first. Read-only DB inspection (`EXPLAIN`) on a replica/staging copy is safe; do not add indexes or change DB settings on production without approval. If a provider is slow, nothing to do locally - see section 11.

**Escalate when.** p99 approaches the 60 s gunicorn timeout (requests are killed), or the slowness is database-wide.

**Verify after recovery.** Route p95 back to baseline for 20 minutes.

<a id="attendance-punch"></a>
## 3. Employee unable to punch attendance

**Symptoms.** An employee reports a failed punch; `HrmsAttendanceInfrastructureFailures`.

**Inspect first.** Is it one employee or many? One: a **business rejection** (policy, geofence, face mismatch, already punched) - not an outage. Many: infrastructure.

**Logs and metrics.** `hrms_operations_total{operation=~"attendance.punch.record|attendance.face.punch",outcome=...}`: `rejected` = policy (expected), `failed` = server-side. `hrms_dependency_errors_total{dependency="face_provider"}` and `hrms_dependency_call_duration_seconds` for face punches. Logs: `attendance.log` `attendance.punch.record` / `attendance.face.punch` (`outcome`, `error_code`, `error_category`); `auth.log` for `security.face_punch.rejected`.

**Correlate.** Ask for the time and read `attendance.log` around it for that employee's `user_id`, or use the `X-Request-Id` shown by the mobile app error. `error_code` is the stable API code (see docs/api/ERROR_CODES.md).

**Diagnostic commands (examples).**
```bash
docker compose -f docker-compose.prod.yml exec -T api sh -c 'tail -n 5000 /app/logs/attendance.log' | jq -c 'select(.outcome=="failed" or .outcome=="rejected") | {timestamp,event,outcome,error_code,error_category,request_id}' | tail -20
```

**Healthy looks like.** `succeeded` dominates; `rejected` has a stable mix of codes; no `failed`.

**Common causes.** `rejected` + `error_code`: user/policy (outside shift, geofence, device) - tell HR, not engineering. `failed`: database timeout/deadlock/pool, Redis down (rate limiter/idempotency), Face++ timeout.

**Safe recovery.** For a policy rejection, HR can correct via regularization. For infrastructure, follow sections 9 / 10 / 11. A retry that reuses the same `idempotency_key` is recognised as the same punch (a *different* punch with a reused key is rejected); a retry without a key is subject to the policy's duplicate-punch window.

**Escalate when.** More than one tenant affected by `failed`, or punches are being lost (client says success but no row).

**Verify after recovery.** A test punch succeeds and `attendance.punch.record outcome=succeeded` plus `business.audit_recorded` appear.

<a id="attendance-calculation"></a>
## 4. Attendance calculation not completing

**Symptoms.** Day records not updated; daily summary stale; `HrmsAttendanceRunDailyCalculationMissed`.

**Inspect first.** Beat -> worker path alive? (`hrms_celery_scheduler_heartbeat_age_seconds`).

**Logs and metrics.** `hrms_celery_task_last_success_timestamp_seconds{task="attendance.run_daily_calculation"}` (scheduled 09:30 app time), `hrms_celery_tasks_finished_total{task=...,state=...}`, `hrms_celery_task_failures_total`. Logs: `background_jobs.log` `celery_task_finished`, `celery_task_failed`, `celery_fanout_incomplete`; `attendance.log` `attendance.day.calculate`.

**Correlate.** `task_id` from the failed line; the same id groups every line the run wrote.

**Diagnostic commands (examples).**
```bash
docker compose -f docker-compose.prod.yml exec -T worker python -m hrms.ops.job_health
docker compose -f docker-compose.prod.yml exec -T api sh -c 'grep -h "attendance.run_daily_calculation" /app/logs/background_jobs.log | tail -5' | jq -c .
```

**Healthy looks like.** One `celery_task_finished state=SUCCESS` per day for the fan-out plus one per company; no `celery_fanout_incomplete`.

**Common causes.** Beat stopped (no heartbeat); queue backlog (section 7); `SoftTimeLimitExceeded` for a very large company; an exception in one company's data (the run isolates companies).

**Safe recovery.** Restarting `beat`/`worker` is safe (idempotent tasks). The calculation covers a trailing 3 days, so a missed day is repaired by the next run; an immediate re-run can be dispatched by an operator with the normal task invocation after approval.

**Escalate when.** Two consecutive days missing, or the same company fails repeatedly.

**Verify after recovery.** `last_success_timestamp` updates; day records for the affected date show recalculated.

<a id="leave-failure"></a>
## 5. Leave approval or accrual failure

**Symptoms.** Approval returns an error; balances wrong or not accrued; `HrmsLeaveOperationFailures`, `HrmsLeaveRunMonthlyAccrualMissed`.

**Inspect first.** Approval (request path) or accrual (scheduled)? Approval errors are usually `rejected` (e.g. insufficient balance, conflict) - read `error_code`.

**Logs and metrics.** `hrms_operations_total{operation=~"leave\\..*"}` (`leave.application.approve`, `leave.accrual.run_company`, ...), `hrms_celery_task_*` for `leave.run_monthly_accrual` / comp-off / year-end. Logs: `leave.log` (`operation` events), `business.audit_recorded` for committed decisions.

**Correlate.** `request_id` for approvals; `task_id` for sweeps. The per-company run logs `leave.accrual.run_company` with `company_id`.

**Diagnostic commands (examples).**
```bash
docker compose -f docker-compose.prod.yml exec -T api sh -c 'tail -n 5000 /app/logs/leave.log' | jq -c 'select(.outcome=="failed") | {timestamp,event,company_id,error_category,task_id,request_id}' | tail
```

**Healthy looks like.** Daily `run_monthly_accrual` success; accrual idempotent (re-runs are no-ops).

**Common causes.** Deadlock/lock timeout on the ledger (`db_deadlock`, `db_timeout`, retryable), bad policy data in one company, worker down.

**Safe recovery.** Accrual is idempotent and self-healing (daily run, window of days); wait for the next run or restart the worker if it is down. For a stuck approval, retry from the UI; the ledger uses idempotency keys.

**Escalate when.** Balances are wrong (not merely late) - stop and escalate to the leave module owner; do not hand-edit the ledger.

**Verify after recovery.** Accrual task `SUCCESS` and the `leave.accrual.run_company` events `succeeded`; the affected balance reconciles.

<a id="payroll-failing"></a>
## 6. Payroll run stuck or failing

**Symptoms.** A pay run cannot be computed/finalised; `HrmsPayrollRunFailing`.

**Inspect first.** **Payroll has no Celery task** - computation, finalisation and payslip generation run inside API requests (limit: gunicorn timeout 60 s). 'Stuck' means a request failed or timed out, not a queued job.

**Logs and metrics.** `hrms_operations_total{operation=~"payroll.pay_run.*|payroll.payslip.generate"}` with `outcome`, `hrms_operation_duration_seconds{operation="payroll.pay_run.compute"}`. Logs: `payroll.log` (`operation`, `outcome`, `error_code`, `run_id`); never contains amounts.

**Correlate.** Use the `run_id` field plus the `request_id` of the failing call.

**Diagnostic commands (examples).**
```bash
docker compose -f docker-compose.prod.yml exec -T api sh -c 'grep -h "<run_id>" /app/logs/payroll.log' | jq -c '{timestamp,event,outcome,error_code,error_category,duration_ms}'
```

**Healthy looks like.** `payroll.pay_run.compute outcome=succeeded` with a duration well below 60 s; finalisation `succeeded` followed by `business.audit_recorded`.

**Common causes.** `rejected` + code: validation (missing inputs, locked period) - fix the data, not the system. `failed` + `db_*`: database. Duration near 60 s: the request was killed (large company) - this is a capacity risk, not an outage.

**Safe recovery.** `pay_run.compute` is accepted from status `INPUTS_LOCKED` or `COMPUTED` (`payroll/service.py`), so a failed compute can be retried from the same state; confirm the run's status before retrying. Never re-run finalisation if `business.audit_recorded` for it is present. Do not edit pay-run rows by hand.

**Escalate when.** Any `failed` on `finalise`/`approve`/`mark_paid`, or compute duration trending to 60 s.

**Verify after recovery.** The run reaches the expected status and `business.audit_recorded` shows the transition.

<a id="worker-unavailable"></a>
## 7. Celery worker unavailable / Beat stopped

**Symptoms.** `HrmsSchedulerHeartbeatStale`/`Missing`; scheduled work not happening; emails/imports not processed.

**Inspect first.** Which container: `worker` (consumes) or `beat` (schedules)? The heartbeat proves the whole path; its age tells how long ago it last worked.

**Logs and metrics.** `hrms_celery_scheduler_heartbeat_age_seconds`, `hrms_celery_queue_depth`, `hrms_celery_messages_unroutable_total`. Logs: `background_jobs.log` (service `worker` / `beat`); Docker healthcheck of `worker` (`inspect ping`).

**Correlate.** Compare the last `celery_task_finished` timestamp with the first missing one.

**Diagnostic commands (examples).**
```bash
docker compose -f docker-compose.prod.yml ps worker beat
docker compose -f docker-compose.prod.yml exec -T worker python -m hrms.ops.job_health
docker compose -f docker-compose.prod.yml logs --since 30m worker | tail -50
docker compose -f docker-compose.prod.yml logs --since 30m beat | tail -50
```

**Healthy looks like.** Heartbeat age under 120 s; queue depth near 0; `inspect ping` answers.

**Common causes.** Container crashed/OOM-killed; Redis unreachable; the worker pool busy with a long task; image skew (`celery_task_unknown`: API enqueues a task the worker does not know).

**Safe recovery.** Restart is safe (all tasks are idempotent): `docker compose -f docker-compose.prod.yml restart worker` (and `beat`). Run exactly **one** `beat`. Do not purge the queue.

**Escalate when.** Crash loop, OOM kills, or messages in `hrms_celery_messages_unroutable_total` (deploy images together).

**Verify after recovery.** Heartbeat age resets under 120 s and queue depth drains.

<a id="queue-backlog"></a>
## 8. Queue backlog growing

**Symptoms.** `HrmsQueueBacklog`, `HrmsQueueOldestMessageOld`.

**Inspect first.** Which queue (`default` or `reports_exports`) and is the worker consuming it (it must start without `-Q`, or with both).

**Logs and metrics.** `hrms_celery_queue_depth`, `hrms_celery_queue_oldest_message_age_seconds`, `hrms_celery_task_queue_wait_seconds`, task durations and `hrms_celery_tasks_started_total` rate vs `hrms_celery_tasks_published_total` rate.

**Correlate.** Which `task` dominates the published counter; read its `celery_task_finished` durations.

**Diagnostic commands (examples).**
```bash
docker compose -f docker-compose.prod.yml exec -T worker python -m hrms.ops.job_health | jq .
redis-cli -h redis LLEN default   # read-only
```

**Healthy looks like.** Depth near 0 outside bulk imports; oldest message under a few minutes.

**Common causes.** A bulk employee import (`employee_import.process_batch` on `reports_exports`); a slow/failed task retrying; worker concurrency 2 saturated by long per-company tasks; worker down (section 7).

**Safe recovery.** Wait if started/published rates show it is draining. To add capacity temporarily raise `CELERY_CONCURRENCY` and restart the worker (check RAM first). **Never** `FLUSHDB`, `DEL` or purge a queue: pending messages may be real work (see EMPLOYEE_IMPORT_BACKLOG_RECONCILIATION.md).

**Escalate when.** The backlog grows for 30 minutes with the worker healthy, or messages are older than an hour.

**Verify after recovery.** Depth and oldest-age trend to baseline; `queue wait` p95 back under a minute.

<a id="database-exhaustion"></a>
## 9. Database connection exhaustion / database down

**Symptoms.** `HrmsDatabaseDown`, `HrmsDbPoolExhausted`, `HrmsDbPoolSaturated`; 503 with `db_pool_exhausted`/`db_wait_timeout`.

**Inspect first.** Down or saturated? `hrms_dependency_up{dependency="database"}` 0 = unreachable; 1 with pool errors = saturation.

**Logs and metrics.** `hrms_errors_total{category=~"db_.*"}`, `hrms_db_pool_checked_out` vs `capacity` (sample of one worker; pool is 5 + 10 overflow per worker, default timeout 30 s), `hrms_db_query_duration_seconds`, `hrms_db_rollbacks_total`, `hrms_db_connects_total` (a high connect rate means churn). Logs: `database.log`, `readiness_dependency_failed`.

**Correlate.** `error_category` on the 5xx events; the `request_id`s of requests that waited.

**Diagnostic commands (examples).**
```bash
docker compose -f docker-compose.prod.yml ps postgres
docker compose -f docker-compose.prod.yml exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select state, count(*) from pg_stat_activity group by 1"   # read-only
docker compose -f docker-compose.prod.yml exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select pid, now()-xact_start as age, state, left(query, 60) from pg_stat_activity where xact_start is not null order by age desc limit 5"   # query text may contain data: do not paste into tickets
```

**Healthy looks like.** Connections well under `max_connections` (100 in the dev image); no idle-in-transaction sessions older than a minute.

**Common causes.** Slow queries holding connections; a worker holding transactions open; `workers x (pool 5 + overflow 10)` plus Celery plus migrations approaching `max_connections`; Postgres restarting/out of disk.

**Safe recovery.** Find and fix the slow operation (section 2). Terminating a backend (`pg_terminate_backend`) is a last resort that needs a human decision - it rolls back that transaction. Do not raise pool sizes without checking `max_connections`.

**Escalate when.** Postgres itself is down, disk full, or `max_connections` is genuinely insufficient.

**Verify after recovery.** `hrms_dependency_up` 1, no new `db_pool_exhausted`, `checked_out` back to a small fraction of capacity.

**Append-only grant check (run after any manual database work and after restoring a backup).** The runtime role must not be able to rewrite history. Expected: exactly the privileges shown.
```bash
docker compose -f docker-compose.prod.yml exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "select table_name, string_agg(privilege_type,',' order by privilege_type) from information_schema.role_table_grants where grantee='hrms_app' and table_schema='public' and table_name in ('leave_ledger','audit_log','email_log','leave_year_end_run','platform_audit_log') group by 1 order by 1"
# expected: every row is INSERT,SELECT   (idempotency_key may add UPDATE)
```
If any row shows `UPDATE` or `DELETE`, something re-ran `infra/docker/postgres/init/002_app_role.sh` (its blanket `GRANT ... ON ALL TABLES` overrides the migrations' `REVOKE`). Re-apply the revokes (re-run the relevant migration steps or `REVOKE UPDATE, DELETE, TRUNCATE ON <table> FROM hrms_app;`) and record the incident; there is currently no metric or alert for this (decision D11).

<a id="redis-outage"></a>
## 10. Redis outage

**Symptoms.** `HrmsRedisDown`, `HrmsTaskPublishFailures`; logins/uploads failing (rate limiter), tasks not enqueued.

**Inspect first.** Redis container health and memory.

**Logs and metrics.** `hrms_dependency_up{dependency="redis"}`, `hrms_redis_memory_used_bytes`/`_max_bytes`, `hrms_redis_evicted_keys`, `hrms_redis_connected_clients`, `hrms_celery_publish_failures_total`. Logs: `readiness_dependency_failed dependency=redis`, `celery_task_dispatch_failed`, 503s from the rate limiter.

**Correlate.** A failing request's `request_id`; `celery_fanout_incomplete` for a short fan-out.

**Diagnostic commands (examples).**
```bash
docker compose -f docker-compose.prod.yml ps redis
docker compose -f docker-compose.prod.yml exec -T redis redis-cli ping
docker compose -f docker-compose.prod.yml exec -T redis redis-cli info memory | grep -E 'used_memory_human|maxmemory_human'
```

**Healthy looks like.** `PONG`; memory far below the container limit; AOF enabled (`--appendonly yes` in compose).

**Common causes.** Container restart/OOM; disk full for AOF; connection limit.

**Safe recovery.** `docker compose -f docker-compose.prod.yml restart redis` is safe (AOF persists queues and counters). Tasks published during the outage were never submitted (`celery_task_dispatch_failed`): the idempotent sweeps repair themselves on the next run; user-triggered ones (imports) must be re-submitted by the user.

**Escalate when.** Redis data loss suspected (heartbeat key gone and queues empty after a crash) - verify imports/emails before declaring recovery.

**Verify after recovery.** `PONG`, `hrms_dependency_up{redis}` 1, heartbeat age resets, no new publish failures.

<a id="external-provider"></a>
## 11. External provider timeout (e-mail, Face++, object storage)

**Symptoms.** `HrmsExternalProviderErrors`; e-mails not arriving; face punches failing.

**Inspect first.** Only enabled providers matter (`EMAIL_PROVIDER`, `FACE_VERIFICATION_PROVIDER`).

**Logs and metrics.** `hrms_dependency_errors_total{dependency,category}` (e.g. `face_provider/timeout`, `email/network`), `hrms_dependency_calls_total` (denominator), `hrms_dependency_call_duration_seconds`. Logs: `notifications.log` (`email.delivery.failed` with `failure_class`, `retryable`, `outcome`), `attendance.log` (`face_provider_request_failed`). No provider payloads or keys are ever logged.

**Correlate.** `email_kind` plus opaque ids; never the recipient address. For e-mail the Platform console e-mail log shows delivery attempts.

**Diagnostic commands (examples).**
```bash
docker compose -f docker-compose.prod.yml exec -T api sh -c 'tail -n 2000 /app/logs/notifications.log' | jq -c 'select(.event=="email.delivery.failed") | {timestamp,provider,failure_class,retryable,outcome,email_kind}' | tail
```

**Healthy looks like.** Failure ratio near 0; `outcome=unknown` is rare (timeouts after send are ambiguous - the mail may have been delivered).

**Common causes.** Provider outage or rate limit; expired credentials (`failure_class=auth`); network egress blocked; DNS.

**Object storage (`dependency="storage"`).** Categories are bounded and come only from the S3 error *code*: `storage_full` (`XMinioStorageFull` - the volume is below MinIO's free-space threshold; every write is refused until space is freed), `storage_auth` (rejected credentials), `storage_config` (bucket missing), `provider_error` (anything else), plus the network categories. A missing object (`NoSuchKey`) is a normal answer and is counted as a success. `HrmsObjectStorageRejectingCalls` fires on the first three. For `storage_full`: `df -h` on the host and `docker system df`; free space from logs/old images/backups per the disk runbook (section 13); do not delete the MinIO data directory. Observed in practice on the dev machine (2026-10-25): root filesystem 100% full -> `XMinioStorageFull` -> 8 document-upload integration tests returning 500.

**Safe recovery.** Nothing to restart locally. For `auth`, rotate credentials through the normal secret procedure. Do not resend `outcome=unknown` e-mails blindly. Face punches fail closed with a clear error; attendance is not lost - employees can use regularization.

**Escalate when.** Provider status page shows no incident but errors persist; credentials rejected.

**Verify after recovery.** Error ratio returns to baseline; a test message/verification succeeds in staging.

<a id="missing-logs"></a>
## 12. Missing application logs

**Symptoms.** No lines in a log file, `HrmsLogWritesFailing`, `log_writes_dropped` / `log_file_writes_dropped` events, `file_logging_unavailable`.

**Inspect first.** stdout (Docker) vs files: `docker compose logs api` shows whether the app is logging at all.

**Logs and metrics.** `hrms_log_dropped_writes_total{source="file"|"stdout"}`, `hrms_log_directory_bytes`, `hrms_log_filesystem_free_ratio`, `hrms_log_events_total` (lines produced). The drop notice is emitted in-band once the sink recovers.

**Correlate.** Compare `hrms_log_events_total` growth with the lines actually in `app.log`.

**Diagnostic commands (examples).**
```bash
docker compose -f docker-compose.prod.yml exec -T api sh -c 'ls -la /app/logs; df -h /app/logs; id'
docker compose -f docker-compose.prod.yml logs --since 10m api | grep -E 'file_logging_unavailable|log_file_writes_dropped|log_writes_dropped'
```

**Healthy looks like.** All channel files growing; no drop events.

**Common causes.** Volume not mounted or read-only; wrong ownership (the app runs as uid 1000 `hrms`); disk full; `LOG_TO_FILES=false`; `LOG_DIR` misconfigured.

**Safe recovery.** Fix ownership/mount (a `chown` of the *log volume* only), free space (section 13). The app keeps serving; stdout logs are unaffected. `LOG_FILES_REQUIRED=true` would instead refuse to boot - decide deliberately.

**Escalate when.** Drops persist after the disk and permissions are fine.

**Verify after recovery.** New lines appear in `app.log`; drop counter stops increasing.

<a id="disk-nearly-full"></a>
## 13. Disk nearly full

**Symptoms.** `HrmsDiskLow`/`HrmsDiskCritical`, `hrms_monitor.sh` disk check.

**Inspect first.** What grows: logs, Docker json logs, Postgres, MinIO, backups, Prometheus TSDB.

**Logs and metrics.** `hrms_log_filesystem_free_ratio`, `hrms_log_directory_bytes`, `hrms_metrics_directory_bytes`, node_exporter filesystem series. Bounds: app logs <= 14 files x 10 MB x 6 = ~840 MB; Docker json-file <= ~10 containers x 10 MB x 5 = ~500 MB; Prometheus capped by `retention.size`.

**Correlate.** n/a

**Diagnostic commands (examples).**
```bash
df -h
docker system df
du -xhd1 /var/lib/docker 2>/dev/null | sort -h | tail
# example host commands, read-only
```

**Healthy looks like.** Under 70% used; log growth flat after rotation.

**Common causes.** Unbounded Docker logs on a service not using `*default-logging`; backups accumulating; MinIO uploads; Postgres WAL after a stuck replica/slot.

**Safe recovery.** Move or expire **old backups** per the backup policy; lower `LOG_FILE_BACKUP_COUNT` / `LOG_RETENTION_DAYS` and restart. Do not delete live data or logs by hand without authorization; expanding the volume is the safe fix.

**Escalate when.** Under 5% free: Postgres stops accepting writes when its disk fills - treat as an outage.

**Verify after recovery.** Free ratio above 30%; alerts resolve.

**Diagnosing a full filesystem (read-only, do this before deleting anything).** Capacity and inodes are different failures:
```bash
df -h /; df -i /                 # capacity vs inodes
du -xhd1 / 2>/dev/null | sort -rh | head      # -x stays on one filesystem; some dirs need root
docker system df                  # images / containers / volumes / build cache
journalctl --disk-usage
```
Do not assume Docker: on the dev machine on 2026-10-25 Docker was about 20 GB of a 526 GB used root, while 74 GB of local model files and 122 GB of downloads were the bulk. Never run `docker system prune -a --volumes` (it deletes named volumes that hold database and object data) or `git clean -fdx`; list candidates and get an owner to approve each. A full disk shows up in the application first as `hrms_dependency_errors_total{dependency="storage",category="storage_full"}` (MinIO stops accepting writes below its free-space threshold) - see section 11.

<a id="scheduled-task-failed"></a>
## 14. Failed or missed scheduled tasks

**Symptoms.** `Hrms...Missed`, `HrmsTaskFailures`, `HrmsRetryRateRising`.

**Inspect first.** Is Beat alive (section 7)? If yes, the task ran and failed, or did not run.

**Logs and metrics.** `hrms_celery_task_last_success_timestamp_seconds{task}`, `hrms_celery_tasks_published_total{task}` (Beat published it), `..._started_total` (a worker began), `..._finished_total{state}`, `..._failures_total{category}`, `..._retries_total`. Distinguish: **not published** (Beat), **published, not started** (queue/worker), **started, failed** (task).

**Correlate.** `task_id` of the failed run; Beat's own publish is in `background_jobs.log` with `service=beat`.

**Diagnostic commands (examples).**
```bash
docker compose -f docker-compose.prod.yml exec -T worker python -m hrms.ops.job_health
docker compose -f docker-compose.prod.yml exec -T api sh -c 'grep -h "<task_name>" /app/logs/background_jobs.log | tail -10' | jq -c .
```

**Healthy looks like.** Each scheduled task: published -> started -> finished SUCCESS at its cron time (see `core/celery_app.py` `beat_schedule`).

**Common causes.** Beat not running or its schedule file lost (`/tmp/celerybeat-schedule` - a lost file at worst re-runs an idempotent task); worker down; a per-company exception; time limits (1800 s soft/hard).

**Safe recovery.** Restart `beat`/`worker`; tasks are idempotent and repair on the next run. For a task failing every run, fix the cause (code/data) - restarting will not help.

**Escalate when.** Same task fails 3+ times in 30 minutes or a daily job misses twice.

**Verify after recovery.** `last_success_timestamp` advances at the next scheduled time.

<a id="auth-failures"></a>
## 15. Authentication failures or rate-limit surge

**Symptoms.** `HrmsLoginFailuresElevated`, `HrmsAccountLockouts`, `HrmsRateLimitingActive`.

**Inspect first.** One account/IP (user error or attack) vs broad (credential stuffing or a broken client release).

**Logs and metrics.** `hrms_security_events_total{event="login.failed"|"account.locked"|"rate_limited"|"refresh.rejected"|"access_token.rejected"}`, `hrms_http_denials_total{code}`. Logs: `auth.log` `security.*` events: `reason`, `subject_hash` (keyed pseudonym of the login id - never the e-mail), `client_ip`, `user_id`.

**Correlate.** Group by `subject_hash` and `client_ip` to tell many-attempts-on-one-account from one-attempt-on-many.

**Diagnostic commands (examples).**
```bash
docker compose -f docker-compose.prod.yml exec -T api sh -c 'tail -n 20000 /app/logs/auth.log' | jq -r 'select(.event=="security.login.failed") | [.client_ip, .reason] | @tsv' | sort | uniq -c | sort -rn | head
```

**Healthy looks like.** A low, steady background of `login.failed`; occasional `rate_limited`.

**Common causes.** Forgotten passwords after a holiday; an old mobile build looping on a stale token; credential stuffing.

**Safe recovery.** Rate limits and lockouts already protect accounts. For a hostile IP range, block at Nginx/firewall (needs approval). Never unlock accounts or reset passwords on the basis of a metric alone.

**Escalate when.** Lockouts across many unrelated accounts, or successes (`login.succeeded`) from an IP that just failed many times.

**Verify after recovery.** Rates return to baseline.

## 16. Recovery verification checklist (any incident)

1. `/health/ready` is 200 and `hrms_dependency_up` is 1 for every dependency.
2. 5xx ratio under 1% for 10 minutes; no new `unhandled_exception` in `errors.log`.
3. Heartbeat age under 120 s; queues near empty; the affected task's `last_success_timestamp` advanced.
4. The originating alert resolved (or, without Prometheus, `infra/monitoring/hrms_monitor.sh` exits 0).
5. Write down: first-seen time, cause, `request_id`/`trace_id` examples, and whether any user-visible data was affected.

## 17. Where metrics volumes live and how to reset them

Counters live in the `metrics_mp` volume (`/app/metrics`). They are small (about 64 KB per process ever started) and **safe to wipe during a full redeploy while api, worker and beat are stopped** - counters simply restart from zero, which Prometheus treats as a reset, and "last success" timestamps repopulate when the tasks next run (hence the 26 h grace on `HrmsScheduledTaskNeverSucceeded`). Wiping while the containers run is *not* safe; this runbook does not automate it.
