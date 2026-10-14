# Alerts and Runbooks

> **Status.** The checks below are implemented in `infra/monitoring/hrms_monitor.sh`. It is
> read-only, it is tested against a fake `docker` binary, and it emits one JSON report per run.
>
> **No alert destination or on-call owner is configured** in this repository. Delivery happens
> only when an operator sets `HRMS_ALERT_COMMAND` to their own notifier; choosing that notifier
> is open decision D1.
>
> **Every threshold is provisional.** None has been calibrated against production traffic. Run
> the monitor in report-only mode for two to four weeks, look at the distribution of each value,
> then tune the `HRMS_*` environment variables.

## 1. Deploying the monitor

```bash
# on the VPS, from the deployment directory (where docker-compose.prod.yml lives)
crontab -e
*/5 * * * * cd /opt/hrms && BACKUP_ROOT=/opt/hrms/backups HRMS_ALERT_COMMAND=/opt/hrms/bin/notify.sh infra/monitoring/hrms_monitor.sh >> /var/log/hrms-monitor.log 2>&1
```

**Prerequisites:**

- `bash`, `jq` and the docker compose plugin on the host;
- the monitor's user can run `docker`;
- the backup scripts are already scheduled.

**Exit codes:** `0` ok, `1` a check failed (the report is piped to `HRMS_ALERT_COMMAND`), `2` the
monitor could not run (for example, `jq` is missing).

**Alert delivery is always stated on stderr** as one JSON line, so it shows in `hrms-monitor.log`:

| Line | Meaning |
|---|---|
| `{"alert_delivery":"sent"}` | `HRMS_ALERT_COMMAND` exited 0. This proves the *command* ran, not that a person received anything. |
| `{"alert_delivery":"failed"}` | The command is missing, not executable, exited non-zero, or exceeded `HRMS_ALERT_TIMEOUT` (default 30 s). |
| `{"alert_delivery":"not_configured"}` | A check failed and `HRMS_ALERT_COMMAND` is unset: **nobody was notified.** |

The monitor is stateless: it alerts on every failing run (every 5 minutes while the fault lasts)
and sends no "recovered" message. The alert command's own stdout is discarded so it cannot corrupt
the JSON report. Real notifications are *not* proven until a configured destination has received a
deliberate test failure (staging checklist S-ALERT-1).

Silence from the monitor is itself a failure mode. Use an external uptime check (decision D1/D3)
that also polls `https://<api domain>/health/ready`, so that "the whole VPS is down" is detected
from outside.

### 1.1 Configuring and verifying a real alert destination

No destination is configured and none may be invented. When the owner authorises one:

1. Write a notifier script that reads the JSON report on stdin and delivers it, for example
   `/opt/hrms/bin/notify.sh` calling `<ALERT_WEBHOOK_URL>` (a chat webhook, a mail relay, a pager
   API). Keep the credential in a root-readable file or environment, never in the repository, the
   cron line or the report. The script must exit non-zero if the destination refuses the message.
2. Set `HRMS_ALERT_COMMAND=/opt/hrms/bin/notify.sh` in the cron line (§1).
3. **Delivery test (not just invocation).** On *staging*, cause one harmless failing check, for
   example `docker compose stop minio` for one cycle, and wait for a run. Pass only if all hold:
   - the cron log shows `{"alert_delivery":"sent"}`;
   - the **named recipient confirms receipt** (screenshot with timestamp) within the agreed time;
   - the message names the failing checks (`containers_not_running`) and the time, so it can be acted on.
4. Negative tests: revoke the webhook → `failed` in the log; unset the command → `not_configured`.
5. Re-run the test after any change to the script, the destination or the credential, and at least quarterly.

`sent` means the command exited 0. It is not proof that anyone saw the message.

## 2. Alert definitions

Severity guide:

- **Critical** — users cannot work, or data integrity is at risk. Page out of hours.
- **High** — degraded or failing silently. Act the same working day.
- **Medium** — investigate.

The default window is the last 5 minutes (`HRMS_MONITOR_WINDOW`).

| Check | Trigger (provisional) | Source | Sev. | False-positive notes |
|---|---|---|---|---|
| `api_ready` | `/health/ready` ≠ 200 | probe inside the api container | Critical | Brief failures during a deploy or restart. Alert only on 2 consecutive runs if this is noisy. |
| `job_health` | Scheduler heartbeat older than 300 s, any queue deeper than 100, or oldest message older than 600 s | `python -m hrms.ops.job_health` in the worker | High | Right after a deploy, the heartbeat key appears within a minute. A large legitimate import can raise depth briefly. |
| `containers_unhealthy` | Any `hrms-prod` container reported unhealthy | `docker ps --filter health=unhealthy` | Critical | Beat has no healthcheck by design; `job_health` covers it. |
| `containers_not_running` | Any compose service that is not `running` (exited, dead, restarting), except the one-shot services in `HRMS_ONESHOT_SERVICES` (default `minio-init migrate`) | `docker ps -a --format` | Critical | **This is how a stopped MinIO, worker, Redis or Beat is detected**: `/health/ready` proves MinIO is *configured*, not reachable, and a stopped container is not "unhealthy". An intentional `docker compose stop` during maintenance trips it; that is correct. |
| `log_writes_dropped` | Any `log_writes_dropped` event from api or worker in the window | API/worker logs | High | Emitted once, in-band, when stdout becomes writable again after lines were lost (closed pipe, full disk on a redirected stdout). Lines logged *during* the outage are gone; the event states how many. Check the log driver and disk. |
| `container_restarts` | Sum of `RestartCount` above 3 | `docker inspect` | High | The count is cumulative since the container was created; a redeploy resets it. Look at the trend, not one value. |
| `disk_usage_pct` | Any path in `HRMS_DISK_PATHS` above 85 % | `df` | High (Critical above 90 %) | Backups and image layers grow steadily. |
| `api_5xx` | More than 5 `http_request` events with status ≥ 500 | API logs | High | One client retrying a broken call can produce bursts. |
| `api_unhandled_exceptions` | At least 1 `unhandled_exception` | API logs | High | Each one is a bug until proven otherwise. |
| `db_connectivity_errors` | At least 1 event with `error_category` `db_connection` or `db_pool_exhausted` | API logs | Critical | A single Postgres restart. |
| `rate_limiter_unavailable` | At least 1 response with `RATE_LIMITER_UNAVAILABLE` | API logs | Critical | None: login is down while Redis is down. |
| `pii_integrity_errors` | At least 1 `app_error` with `DECRYPTION_FAILED`, `MALFORMED_CIPHERTEXT` or `UNKNOWN_KEY_VERSION` | API logs | Critical | None. |
| `refresh_token_reuse` | At least 1 `security.refresh_token_reuse_detected` | API logs | Medium | Two browser tabs refreshing at the same instant trigger it too (decision D-A). |
| `account_lockouts` | More than 10 `security.account.locked` | API logs | Medium | A forgotten password after a policy change. |
| `email_delivery_failures` | More than 5 `email.delivery.failed` | API and worker logs | High | Provider maintenance. |
| `task_failures` | At least 1 `celery_task_failed`, `celery_task_unknown` or `celery_fanout_incomplete` | Worker logs | High | A one-off broker hiccup. |
| `partial_runs` | At least 1 `*_incomplete` event (attendance calculation, leave accrual, year-end) | Worker logs | High (Critical before a payroll cut-off) | Per-employee data problems. |
| `storage_and_orphan_failures` | Import storage failure, or an orphaned face photo or provider person | API and worker logs | High | MinIO restart. |
| `backup_postgres`, `backup_minio` | No `SUCCESS` in 26 h, or `FAILED` after the last success | `$BACKUP_ROOT/*/backup.log` | High | The backup schedule drifted. |

**Not yet automated:**

- certificate expiry (certbot container logs; `openssl s_client -connect <domain>:443 | openssl x509 -noout -enddate`);
- host memory pressure (`free -m`, `dmesg | grep -i oom`);
- a stuck import batch. `employee_import_batch` is RLS-protected, so this needs an admin role — see §3.6.

## 3. Runbooks

General rules:

- **Never** clear a queue, delete records, or restart production blindly.
- Capture logs before any restart: `docker compose -f docker-compose.prod.yml logs --since 30m <svc> > /tmp/<svc>-$(date +%s).log`.
- Search by request id with `docker compose -f docker-compose.prod.yml logs api worker nginx | grep '<id>'`. For structured filtering, use `… logs --no-log-prefix api | jq -c 'select(.request_id=="<id>")'`.

### 3.1 A user reports an error with a reference

1. `grep` the reference across `api`, `worker` and `nginx` (above).
2. In the `http_request` event, read `http_path` (the route template), `status_code` and `error_code`.
3. For a 500, the matching `unhandled_exception`, `app_error` or `db_error` event holds the traceback (redacted).
4. Check `business.audit_recorded` for the same `request_id` to see what was committed.
5. **Escalate** to the development team with the reference and the event names. Never send the log excerpt to the user.

### 3.2 Database (`db_connectivity_errors`, `api_ready` with `database: error`)

**Symptom:** 500s carrying `error_category: db_connection`, `503 DATABASE_BUSY` from pool exhaustion, or readiness reporting `database: error`.

**Diagnose:**

- `docker compose ps postgres`
- `docker compose logs --since 15m postgres`
- `df -h`
- Connection count: `docker compose exec postgres psql -U hrms -c "select count(*), state from pg_stat_activity group by state"`.
- Long transactions: `select pid, now()-xact_start, state, left(query,80) from pg_stat_activity where xact_start < now()-interval '1 minute'`.

**Mitigate:**

- Disk full: free space (prune images, move old backups) **before** restarting Postgres.
- Pool exhaustion caused by a long-running sweep: let it finish, or cancel the single offending backend with `pg_cancel_backend(pid)` once you understand what it is.

**Verify:** `/health/ready` returns 200, `db_*` events stop, and `api_5xx` returns to baseline.

**Do not:**

- restart Postgres during a pay-run finalisation;
- edit rows to "unstick" anything;
- run migrations as a fix.

**Escalate** if not resolved in 15 minutes, or if any `pii_integrity_errors` appear.

### 3.3 Redis or rate limiter (`rate_limiter_unavailable`)

**Symptom:** login, refresh and password-reset return `503 RATE_LIMITER_UNAVAILABLE`, and the queues stop moving.

**Diagnose:**

- `docker compose ps redis`
- `docker compose logs --since 15m redis`
- `docker compose exec redis redis-cli INFO memory | grep used_memory_human`
- `docker compose exec redis redis-cli INFO persistence | grep aof`

**Mitigate:** restart the redis container only after capturing its logs. Its data is AOF-persisted.

**Do not** `FLUSHALL`/`FLUSHDB`. The same instance holds the Celery queues, including any import backlog awaiting reconciliation (decision D-B), and the rate-limit state.

**Verify:** a login succeeds, `job_health` is ok, and the `default` queue drains.

### 3.4 Background jobs (`job_health`, `task_failures`)

**Diagnose:**

- `docker compose exec -T worker python -m hrms.ops.job_health | jq .`
- `docker compose exec worker celery -A entrypoints.worker inspect ping`
- `docker compose logs --since 30m worker | jq -c 'select(.event=="celery_task_failed" or .event=="celery_task_retry")'`
- To see what is waiting (read-only): `docker compose exec redis redis-cli LLEN default` and `LLEN reports_exports`.

**Interpret:**

- A stale heartbeat with empty queues means Beat is not scheduling: `docker compose logs beat`.
- A stale heartbeat with growing queues means no worker is consuming.
- A high `oldest_age_seconds` on `reports_exports` means imports are waiting.
- `unknown_age: true` means the messages predate the enqueue-time header, which is exactly the historical backlog.

**Mitigate:**

- Restart `beat` or `worker` only after capturing their logs.
- Idempotent tasks (leave, attendance calculation, termination sweep, reminders) can be re-run per company.
- Imports **cannot** be re-run blindly. The PENDING guard prevents a duplicate run of the same batch, but re-uploading a file creates a new batch.

**Do not** purge queues, and do not start an extra worker against a queue that holds an unreconciled import backlog.

### 3.5 Partial runs (`partial_runs`)

1. Find the failing employees: `docker compose logs --since 2h worker | jq -c 'select(.event|test("employee_failed|calculate_failed|calculate_timed_out"))'`. Each event carries `company_id`, `employee_id` and `error_category`.
2. Fix the data issue, then re-run the company task. All three tasks are idempotent.
3. **Before a payroll period close**, confirm the last run for every company has no `*_incomplete` event.
4. **Escalate** to payroll and HR operations if the period close is near.

### 3.6 Email (`email_delivery_failures`)

1. Group the failures by `failure_class` and `provider`:
   - `auth` — the API token has expired or been revoked. Rotate it; this needs a deploy.
   - `rate_limited` or `provider_error` — check the provider's status page.
   - `rejected` — the address is bad. This is per user.
   - `internal` — a bug. Read the traceback.
2. Treat `outcome: unknown` as possibly sent: do not resend without checking with the user.
3. There is no outbox. Lost emails are re-triggered from the product, for example "resend invite", "resend verification" or "forgot password".

### 3.7 Object storage and orphaned biometric data (`storage_and_orphan_failures`)

**`face_enrollment_orphaned_provider_person`.** A Face++ face set was created and not cleaned up. Delete it with the provider's console or API using `provider_person_id`. This is a privacy obligation.

**`face_review_photo_delete_failed`.** Delete `object_key` from the documents bucket with the `mc` client, after checking it is not referenced by `employee_face_profile.review_photo_key`.

**`employee_import.batch.storage_failed`.**

- Check `docker compose ps minio` and its logs.
- The batch is marked `FAILED`. HR re-uploads after storage recovers.

**Stuck import** (manual, admin role, read-only):

```sql
SELECT company_id, id, status, created_at, started_at FROM employee_import_batch
WHERE status IN ('PENDING','PROCESSING') AND created_at < now() - interval '30 minutes';
```

### 3.8 Disk (`disk_usage_pct`)

1. Find what is growing: `docker system df`, `du -sh /opt/hrms/backups/*`, and `du -sh /var/lib/docker/volumes/*`.
2. Safe to remove: dangling images (`docker image prune -f`), and backups older than the retention period that have already been verified as restorable.
3. **Do not** delete Docker volumes or Postgres WAL by hand.

### 3.9 Security signals

**`refresh_token_reuse`.** The session is already revoked server-side.

1. Contact the user (find them by `user_id`).
2. Check `security.login.*` for that user, and look for unfamiliar `client_ip` values.
3. Multi-tab false positives are a known trade-off (decision D-A).

**`account_lockouts`, or many `security.rate_limited` events.** Group by `client_ip` and `subject_hash`.

- A single IP is a likely credential-stuffing attempt. Consider an Nginx `deny` (change-controlled).
- Many IPs against one `subject_hash` is a targeted account. Contact its owner.

**`pii_integrity_errors`.** Stop any key rotation, check the `encryption_keys` table and the master-key configuration, and escalate to the security owner immediately.

## 4. Decisions still required

| ID | Decision | Effect |
|---|---|---|
| D1 | Alert destination and on-call owner | Without it, the monitor reports to its own log file only. |
| D2 | Log retention periods per stream | Today retention is bounded by size only. |
| D3 | Whether any third-party error tracker, uptime service or crash reporter is acceptable | Determines whether off-host uptime checking and mobile crash reporting exist. |
