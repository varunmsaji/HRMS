# Staging validation checklist — logging, error handling and reliability

> **Scope.** Controlled validation of the logging / error-handling / reliability work on an
> **authorised staging environment**. Nothing here may be run against production. Nothing here
> proves production readiness: that needs the staging evidence below *and* the approvals in the
> readiness report (§11).
>
> **Two parts.** Part A are checks that already run locally in CI-style test suites (listed so
> staging can skip re-deriving them, not so they can be skipped *in* staging if the environment
> differs). Part B are checks that need real infrastructure, a real device, or a real provider.

**Rules for the person running Part B**

- Use a staging company with fake employees. No real personal data, no production credentials.
- Email: the `logging` provider, or a real provider pointed only at a mailbox you own.
- Run fault injection one fault at a time; restore before the next. Record the time of each
  action (UTC) so log lines can be matched.
- Evidence is a saved file or screenshot with a timestamp and the request ID, not a statement.
- A scenario passes only if **every** expected item is observed. If a log or alert is expected and
  absent, that is a failure.

---

## Part A — runs locally (no staging needed)

Prerequisites: Postgres, Redis and MinIO available on the dev ports used by the test suite;
isolation is forced by `tests/conftest.py` (logging email provider, face provider disabled,
Celery broker in Redis DB 15). From `apps/api`:

```bash
.venv/bin/python -m pytest <path> -q -p no:cacheprovider
```

| ID | Scenario | Test(s) | What it proves |
|---|---|---|---|
| A-01 | Request correlation, one access event per request, 5xx behaviour | `tests/integration/core/test_http_access_event.py`, `test_request_context_and_error_logging.py` | `request_id` in header, body, log and audit row; 5xx body is generic; raw path never logged |
| A-02 | CORS and security headers on error responses | `tests/unit/core/test_cors_middleware.py`, `tests/security/test_security_headers.py` | Headers present on 4xx/5xx |
| A-03 | Sensitive URL and log redaction | `tests/unit/core/test_log_redaction.py`, `tests/integration/core/test_token_path_redaction.py` | Tokens, passwords, addresses never reach logs |
| A-04 | Authentication/authorisation failures | `tests/integration/auth/test_security_events.py`, `test_auth_security.py` | `security.*` events, no secrets, lockout survives a broken log sink |
| A-05 | Database timeout, pool, lock, lost connection | `tests/integration/core/test_db_failure_classification.py`, `tests/unit/core/test_db_error_handler.py` | `503 DATABASE_BUSY` + `Retry-After`; lost connection stays 500 |
| A-06 | Readiness with database or Redis unreachable | `tests/integration/core/test_job_health_and_readiness.py` | 503, which dependency failed is logged; **MinIO reachability is not probed** (documented gap) |
| A-07 | Rate-limiter outage | `tests/unit/shared/test_onboarding_upload_rate_limit_middleware.py`, `test_request_context_and_error_logging.py` | `RATE_LIMITER_UNAVAILABLE` |
| A-08 | Email provider rejection/timeout classification | `tests/unit/modules/onboarding/test_email_failure_classification.py`, `test_email_sender.py` | `failure_class`, `outcome=not_sent|unknown`, no address in logs |
| A-09 | Celery failure, retry, lifecycle, time limits | `tests/unit/core/test_celery_task_lifecycle_logging.py`, `test_celery_task_failure_logging.py`, `test_task_hardening.py` | `celery_task_finished/retry/failed`; every task has a hard limit |
| A-10 | Scheduler heartbeat and job health thresholds | `tests/unit/ops/test_job_health.py`, `tests/integration/core/test_job_health_and_readiness.py` | stale/missing heartbeat, depth, oldest age, unknown age, exit 2 on Redis down |
| A-11 | Host monitor: every signal, recovery, alert interface, read-only | `tests/unit/ops/test_host_monitor.py` (32 tests, fake `docker`) | each check fails/recovers; missing/invalid/hung alert command; allow-listed commands only |
| A-12 | Employee-import claim and reconciliation | `tests/integration/modules/employee_import/*`, `tests/unit/ops/test_import_backlog.py` | no double processing; report is read-only |
| A-13 | Self-punch and face-punch duplicate retries | `tests/integration/modules/attendance/test_face_punch_idempotency.py`, `test_face_punch.py`; Flutter `test/core/punch_idempotency_test.dart`, `test/face_punch_card_test.dart` | one punch per key; concurrent; failure leaves key reusable; tenant isolation; key never logged |
| A-14 | Refresh-token rotation, reuse, concurrency | `tests/integration/auth/test_refresh_token_reuse.py` | single winner, durable family revocation, unrelated sessions untouched |
| A-15 | Next.js error boundaries and API client | `apps/web`: `npx vitest run` (`route-error.test.tsx`, `client.test.ts`, `client-cross-tab.test.ts`, `errors.test.ts`) | component and client behaviour (**not** a browser run) |
| A-17 | Log sink failure is non-fatal and observable | `tests/unit/core/test_resilient_log_sink.py` | closed stdout is dropped and counted; one `log_writes_dropped` event on recovery |
| A-18 | Import enqueue failure | `test_import_idempotency.py::test_a_failed_enqueue_closes_the_batch_instead_of_leaving_it_pending` | 503 `IMPORT_QUEUE_UNAVAILABLE`, batch `FAILED`, `employee_import.batch.enqueue_failed` |
| A-16 | Flutter network/timeout/auth handling | `apps/mobile`: `flutter test` (`test/core/api_error_handling_test.dart`) | error mapping and diagnostics (**not** a device run) |

---

## Part B — needs an authorised staging environment, a real device, or a provider

Each scenario lists: **Pre** (preconditions), **Action**, **Expect-UI** (user-visible result),
**Expect-Log** (log / metric / alert), **Recover**, **Evidence** (needed to pass).

Common pre-conditions for all: staging deployed from the candidate build; `infra/monitoring/hrms_monitor.sh`
installed with `HRMS_COMPOSE_PROJECT` set for staging; the stack's log driver is reachable
(`docker compose logs`); a way to query logs by `request_id`.

### B-01 Request correlation and 5xx
- **Pre:** a staging user with a known email.
- **Action:** make a request that returns 5xx on purpose (for example stop `postgres` for 30 s, call an authenticated endpoint) and a request that returns 4xx.
- **Expect-UI:** web and mobile show a generic message with a "Reference: `<id>`". No stack trace, SQL or hostname.
- **Expect-Log:** one `http_request` event with the same `request_id` as the Reference and the `X-Request-ID` response header; `status_code` 5xx; for the DB outage `error_category=db_connection`.
- **Recover:** start `postgres`; confirm `/health/ready` returns 200.
- **Evidence:** response headers, screenshot of the Reference, the matching log line.
- **Safe for staging:** Yes (stopping `postgres` on staging only)
- **Human authorisation / external configuration:** Staging owner approves a 30 s database stop
- **Status:** `NOT RUN`


### B-02 CORS and security headers on errors
- **Action:** from the real web origin, trigger a 401, a 404 and a 5xx; inspect response headers (browser devtools or `curl -i -H 'Origin: ...'`). Also from a **non-allowed** origin.
- **Expect-UI:** the web app can read the error body for the allowed origin.
- **Expect-Log:** none required.
- **Evidence:** headers: `Access-Control-Allow-Origin` only for allowed origins, `X-Content-Type-Options`, `Strict-Transport-Security` (via Nginx, which local tests cannot cover), no `Server` version leakage.
- **Safe for staging:** Yes (read-only)
- **Human authorisation / external configuration:** None beyond staging access
- **Status:** `NOT RUN`


### B-03 Sensitive URL and log redaction (through Nginx)
- **Action:** perform password reset, email verification and onboarding-token flows; then `docker compose logs nginx api | grep` for the token value and for the test email address.
- **Expect-Log:** neither the token nor the address appears in Nginx or API logs; paths are templates.
- **Evidence:** the empty grep result with the command and time range. **Nginx access logs are outside the API redaction code; this check is the only coverage.**
- **Safe for staging:** Yes (read-only; uses fake test users)
- **Human authorisation / external configuration:** None beyond staging access and log read access
- **Status:** `NOT RUN`


### B-04 Authentication and authorisation failures
- **Action:** 6 wrong passwords; a user without a permission calling a guarded endpoint; a token for company A used with company B's `X-Company-Id`.
- **Expect-UI:** generic credentials error; lockout message; 403; no tenant data.
- **Expect-Log:** `security.login.failed` with reasons, `security.account.locked`, authorisation-denied and tenant-rejected events; `subject_hash`, never the address; monitor `account_lockouts` only above 10.
- **Recover:** wait out or clear the lockout through the documented admin path.
- **Evidence:** log lines, monitor report.
- **Safe for staging:** Yes (fake accounts; lockout is self-clearing after 15 min)
- **Human authorisation / external configuration:** None
- **Status:** `NOT RUN`


### B-05 Database connection loss, pool and lock timeouts
- **Action:** (a) `docker compose stop postgres` 60 s; (b) terminate backends with `pg_terminate_backend` on a staging database only; (c) hold a row lock from a psql session and call the endpoint that needs it.
- **Expect-UI:** (a)/(b) 500 with Reference (outcome of a write is unknown); (c) 503 `DATABASE_BUSY` with `Retry-After`. Clients never auto-retry writes.
- **Expect-Log:** `error_category` of `db_connection` / `db_timeout`; monitor `api_ready`, `db_connectivity_errors` fail within one run.
- **Recover:** restart `postgres`; API reconnects without a restart (confirm). If it does not, that is a **finding**.
- **Evidence:** monitor JSON before/during/after, log excerpts, API recovery time.
- **Safe for staging:** Yes, **staging only** — service stop and backend termination
- **Human authorisation / external configuration:** Staging owner approves each fault; never run against a shared or production database
- **Status:** `NOT RUN`


### B-06 Redis and rate-limiter outage
- **Action:** `docker compose stop redis` 60 s; call login and a rate-limited endpoint.
- **Expect-UI:** documented behaviour (503 `RATE_LIMITER_UNAVAILABLE` for guarded routes). Record exactly which routes fail closed.
- **Expect-Log:** `rate_limiter_unavailable`, readiness `redis: error`, `job_health` exit 2 (`redis_unavailable`); monitor `api_ready`, `job_health`, `rate_limiter_unavailable` fail.
- **Recover:** start `redis`; worker reconnects (check it consumes a new task without restart).
- **Evidence:** monitor report, worker logs after recovery.
- **Safe for staging:** Yes, staging only — stops Redis
- **Human authorisation / external configuration:** Staging owner approval; confirm the broker is the staging Redis, not a shared one
- **Status:** `NOT RUN`


### B-07 Email provider rejection and timeout
- **Pre:** staging email provider configured to a sandbox; for fault injection, point `SMTP` host at a blackhole or a rejecting test server.
- **Action:** trigger a verification / invite email in each of: reject (5xx / auth fail), timeout.
- **Expect-UI:** the action succeeds as before (best-effort semantics, unchanged); no address shown in errors.
- **Expect-Log:** exactly one `email.delivery.failed` with `email_kind`, `failure_class`, `retryable`, `outcome` (`not_sent` for refusal, `unknown` for a read timeout); no recipient address; monitor `email_delivery_failures` above 5 per 5 min.
- **Recover:** restore the provider; resend manually where needed (no outbox exists: decision D4).
- **Evidence:** log lines, monitor report, confirmation that no email was lost silently.
- **Safe for staging:** Yes with a sandbox or blackhole SMTP target
- **Human authorisation / external configuration:** Provider sandbox credentials or a test SMTP sink (placeholder `<SMTP_TEST_HOST>`)
- **Status:** `NOT RUN`


### B-08 Celery task failure, retry and stuck-job visibility
- **Action:** make a staging task fail (for example a leave or attendance task against a company with bad config); stop the worker for 10 min with messages queued; start a long import.
- **Expect-Log:** `celery_task_failed` with `task_id` and `request_id`; retry events for Leave connection errors; `job_health` `queue_oldest_age` > 600 s and `scheduler_heartbeat` > 300 s while the worker is stopped; `containers_not_running` for the worker.
- **Recover:** start the worker; queue drains; heartbeat fresh within one minute.
- **Evidence:** `job_health` JSON in each state, monitor reports.
- **Safe for staging:** Yes, staging only — stops the worker
- **Human authorisation / external configuration:** Staging owner approval; queue must contain only staging test messages
- **Status:** `NOT RUN`


### B-09 Scheduler heartbeat and readiness
- **Action:** stop `beat` for 6 min.
- **Expect-Log:** `job_health.scheduler_heartbeat` fails (older than 300 s); `containers_not_running` lists `beat`.
- **Recover:** start `beat`; check passes within the next monitor run.
- **Evidence:** before/during/after JSON.
- **Safe for staging:** Yes, staging only — stops Beat
- **Human authorisation / external configuration:** Staging owner approval
- **Status:** `NOT RUN`


### B-10 MinIO upload/download failure
- **Pre:** staging documents bucket.
- **Action:** `docker compose stop minio`; upload an employee document, start an employee import, download a document. Then start MinIO.
- **Expect-UI:** readable error with Reference; import batch ends `FAILED`.
- **Expect-Log:** `employee_import.batch.storage_failed`, storage error classification; monitor `containers_not_running` (critical) and `storage_and_orphan_failures`. **`/health/ready` stays 200**: readiness proves configuration only. Do not accept a readiness-based MinIO alert.
- **Recover:** start MinIO; HR re-uploads the failed import.
- **Evidence:** monitor JSON, batch status, log lines.
- **Safe for staging:** Yes, staging only — stops MinIO
- **Human authorisation / external configuration:** Staging owner approval; staging bucket only
- **Status:** `NOT RUN`


### B-11 Employee-import state and recovery
- **Action:** run `python -m hrms.ops.import_backlog` (see `EMPLOYEE_IMPORT_BACKLOG_RECONCILIATION.md`) with a seeded set: fresh, stale, completed, failed batches; kill the worker mid-import; redeliver a message.
- **Expect:** report classes match; a redelivered message produces `employee_import.batch.skipped`, never a second set of employees; the killed batch appears as `PROCESSING` then `STALE_PROCESSING`.
- **Recover:** documented in the procedure; fresh import for missing rows.
- **Evidence:** before/after reports, employee counts.
- **Safe for staging:** Yes with seeded fake batches; never against a queue holding unreconciled production messages
- **Human authorisation / external configuration:** Staging owner approval; run `hrms.ops.import_backlog` first. Include the enqueue-failure case: stop Redis, upload a CSV, expect 503 `IMPORT_QUEUE_UNAVAILABLE` and a `FAILED` batch
- **Status:** `NOT RUN`


### B-12 Attendance self-punch and face-punch duplicate retries (real device)
- **Pre:** a real phone on the staging build; an enrolled and approved test employee; the **real** face provider in its sandbox, or the staging stub.
- **Action:** enable airplane mode just after tapping punch (or throttle so the response is lost), then restore the network and retry with the same screen state; repeat for self punch and face punch; also punch IN then OUT normally.
- **Expect-UI:** one "Punched in" result; the retry returns the original punch. The attendance day shows one IN.
- **Expect-Log:** `attendance.face_punch.replayed` with `key_ref` (never the key); no second `PUNCH_CREATED` audit row; provider called once.
- **Recover:** none needed. If two punches exist, capture both IDs and `idempotency_key` values: **failure**.
- **Evidence:** screen recording, punch list, log lines.
- **Safe for staging:** Yes (fake employee, real device)
- **Human authorisation / external configuration:** Test device, staging build, face-provider sandbox or stub
- **Status:** `NOT RUN`


### B-13 Next.js global and route error boundaries
- **Action:** in a staging browser build, force a render error in a route (a deliberately broken staging-only test route, or a patched API response), and a root-layout failure; use "Try again".
- **Expect-UI:** route boundary inside the navigation shell, global boundary otherwise; reference shown; no internal text; retry works once fixed.
- **Expect-Log:** none server-side (client-only); confirm the reference matches a request ID where applicable.
- **Evidence:** screenshots from a real browser. **Component tests are not a substitute.**
- **Safe for staging:** Yes
- **Human authorisation / external configuration:** A real browser and a staging-only way to force a render error
- **Status:** `NOT RUN`


### B-14 Flutter network, timeout and authentication handling (real device)
- **Action:** airplane mode; a slow network that exceeds the 30 s receive timeout; expire the refresh token; run a release build for global-error handling.
- **Expect-UI:** "can't connect" vs "timed out, outcome unknown" wording on writes; expired session returns to sign-in; release-mode `ErrorWidget` does not show a red screen or raw error.
- **Evidence:** screen recordings on Android and iOS.
- **Safe for staging:** Yes
- **Human authorisation / external configuration:** Android and iOS test devices; a release build
- **Status:** `NOT RUN`


### B-15 Refresh-token behaviour with simultaneous browser tabs
- **Pre:** staging web build that includes the cross-tab refresh lock (`refreshAcrossTabs` in `apps/web/src/lib/api/client.ts`); a test user.
- **Action:** log in; open the app in two tabs of the same browser profile; let the access token expire (or shorten it on staging); trigger an API call in both tabs within the same second. Repeat 20 times. Then repeat once in a browser or private window without Web Locks if one is available, and once from two different browser *profiles* (different cookie jars).
- **Expect:** same profile: both tabs recover, **no sign-out**, no `security.refresh_token_reuse_detected`. Different profiles are different sessions and are unaffected. Without Web Locks: the old behaviour (one tab may sign both out; reuse event logged).
- **Also verify the policy is unchanged:** replay a *captured* old refresh cookie with `curl` → 401 and the family revoked.
- **Record:** frequency of `refresh_token_reuse` events before/after.
- **Evidence:** log excerpts, screen recording of both tabs.
- **Safe for staging:** Yes
- **Human authorisation / external configuration:** Real browser(s) with two tabs; staging web build containing the lock
- **Status:** `NOT RUN`

### B-16 Monitor behaviour during recovery
- **Action:** with the monitor in cron, run B-05, B-06, B-09 and B-10 faults; watch `hrms-monitor.log`.
- **Expect:** failing run(s) while the fault lasts, then a passing run with `failing: []` within one interval after recovery; `alert_delivery` lines as configured; no service was restarted or modified by the monitor.
- **Evidence:** the log file excerpt with timestamps; `docker events` or container start times unchanged.
- **Safe for staging:** Yes, as long as the faults are those of B-05/06/09/10
- **Human authorisation / external configuration:** Staging owner approval; cron installed
- **Status:** `NOT RUN`


### B-17 Alert destination (S-ALERT-1)
- **Pre:** decision D1 made; an `HRMS_ALERT_COMMAND` script that delivers to the chosen destination; a named recipient who agrees to the test.
- **Action:** cause one safe failing check (stop `minio` for one cycle); wait for a run.
- **Expect:** `{"alert_delivery":"sent"}` **and** the recipient confirms receipt, within the target time, with enough context (failing check names, time) to act on.
- **Also test:** a failing destination (revoke the webhook) → `{"alert_delivery":"failed"}` visible in the log; the unset command → `not_configured`.
- **Evidence:** the recipient's screenshot with timestamp. **Until this passes, do not state that alerting works.**
- **Safe for staging:** Yes — a deliberate failing check on staging only
- **Human authorisation / external configuration:** **An authorised alert destination, a named recipient, and an `HRMS_ALERT_COMMAND` script.** Placeholders: `<ALERT_WEBHOOK_URL>`, `<ONCALL_RECIPIENT>`
- **Status:** `NOT RUN`


### B-18 Log output, retention and volume
- **Action:** run a representative day of staging traffic; measure `http_request` lines per day and Docker log size per container against the 50 MB cap.
- **Expect:** security events from the last 24 h are still present (decision D2 may require shipping logs elsewhere).
- **Evidence:** sizes, oldest retained line per container.
- **Safe for staging:** Yes (read-only measurement)
- **Human authorisation / external configuration:** Log access
- **Status:** `NOT RUN`


### B-19 Backup and restore
- **Pre:** staging backup scripts from `infra/backup/` scheduled.
- **Action:** confirm the monitor's `backup_postgres` / `backup_minio` checks pass; restore the latest Postgres backup into a **separate** scratch database and the MinIO backup into a scratch bucket; compare row counts and object counts; make a backup fail on purpose (no space on the backup path).
- **Expect:** restore completes and an application smoke test passes against the scratch database; a failed backup trips the monitor.
- **Evidence:** restore log, counts, monitor report.
- **Safe for staging:** Yes — restore only into a scratch database/bucket, never over staging data
- **Human authorisation / external configuration:** Backup access; scratch DB and bucket
- **Status:** `NOT RUN`


### B-20 Deployment pre-checks
- **Action:** apply migrations on staging; start the new worker and beat; verify heartbeat appears; verify no import backlog is drained before reconciliation (B-11); verify `jq` is installed; verify log-shape changes (saved queries updated).
- **Evidence:** `alembic current`, `job_health` output, release notes. (The face-punch change needs **no** migration.)
- **Safe for staging:** Yes, staging only
- **Human authorisation / external configuration:** Staging owner performs the deploy; migrations are applied by the owner, not by this tooling
- **Status:** `NOT RUN`


---

## Sign-off record (fill in per run)

| ID | Date (UTC) | Environment / build | Result (pass / fail / not run) | Evidence link | Notes / defects |
|---|---|---|---|---|---|
| B-01 | | | | | |
| B-02 | | | | | |
| … | | | | | |

A scenario with no evidence link is *not run*, whatever the result column says.
