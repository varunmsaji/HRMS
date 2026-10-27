# Observability architecture

Status: implemented in code and verified locally (2026-10-25); **not deployed to any shared environment**. Companion documents: [audit](../audits/PRODUCTION_OBSERVABILITY_AUDIT.md), [runbook](../operations/OBSERVABILITY_RUNBOOK.md), [alert catalog](../operations/OBSERVABILITY_ALERT_CATALOG.md), [dashboard catalog](../operations/OBSERVABILITY_DASHBOARD_CATALOG.md), [logging guide](../operations/LOGGING_GUIDE.md).

## 1. Constraints that shaped the design

| Constraint | Consequence |
|---|---|
| One self-hosted VPS (Hostinger) running Postgres, Redis, MinIO, API (gunicorn x2), worker (x2), beat, web, Nginx | No room for a Loki/Tempo/Elastic stack; every added container must justify its RAM |
| Multi-process: gunicorn workers, Celery prefork children, Beat - in **three containers** | Metrics must aggregate across processes *and* containers; file logs already do (flock) |
| Multi-tenant HRMS with sensitive data | Metric labels carry no tenant/employee identifier; tenants are found through logs, access-controlled |
| No approved paid vendor, alert destination, or scraper | Everything ships **disabled / inert** until a decision is made |
| Existing, tested structured logging (see audit) | Build on it; do not replace it |

## 2. Layers

```
                       +----------------------------------------------------+
 HTTP --> Nginx -----> | RequestContextMiddleware (outermost)               |
 (edge request id)     |  request_id + trace_id/span_id -> log context      |
                       |  http_request event + hrms_http_* metrics          |
                       +-----------------------+----------------------------+
                                               |
   service layer: @logged_operation  ----> operation event + hrms_operations_*
   audit/business events (after commit) -> business.audit_recorded + hrms_committed_events_total
   security_event()  ------------------->  security.* event  + hrms_security_events_total
   SQLAlchemy engine listeners ---------> hrms_db_* (timings only; no SQL text)
   provider adapters (email, Face++) ---> hrms_dependency_*
                                               |
   Celery publish (before_task_publish) -> hrms_request_id, hrms_traceparent, hrms_enqueued_at headers
   Worker signals (prerun/postrun/...) --> hrms_celery_* + task_id/trace_id in log context
                                               |
   stdout JSON  -> Docker json-file (10 MB x 5)        file sink -> /app/logs/<channel>.log (flock, rotated)
   counters/histograms -> mmap files in $PROMETHEUS_MULTIPROC_DIR (volume shared by api, worker, beat)
                                               |
   GET /metrics (bearer token, private network only) = aggregate of all mmap files
        + scrape-time probes (DB SELECT 1, Redis PING/INFO, LLEN/LINDEX queue age, heartbeat age, log-disk space)
```

## 3. Minimum viable vs extended

**Minimum viable production observability** (what this change delivers; no new always-on component is *required*):

1. Structured JSON logs, per-module files, redaction, correlation ids (already present, extended with trace ids).
2. `/metrics` in the API process (closed unless `METRICS_TOKEN` is set).
3. Health: `/health/live`, `/health/ready`, `python -m hrms.ops.job_health`, `hrms_monitor.sh` (already present).
4. Alert rules and dashboards **as code**, tested with `promtool`, ready to load into a Prometheus/Grafana that is *not yet approved*.

Until a scraper exists the metrics can still be read by hand (`curl` with the token) and the existing cron monitor remains the only automated alerter.

**Extended observability** (optional, each needs a decision - section 9): Prometheus + Alertmanager (+ node_exporter) for history and alert delivery; Grafana for dashboards; a log backend (Loki) for search across days; real distributed tracing (OpenTelemetry + a backend) if cross-service latency questions appear.

## 4. Component comparison

Resource figures are order-of-magnitude planning values from the vendors' typical footprints for a system of ~6 k series / ~1 GB logs; they were **not measured here**.

| Component | Adds | RAM | CPU | Disk | Complexity / failure mode | Verdict |
|---|---|---|---|---|---|---|
| `prometheus_client` in the app | `/metrics` | ~1 MB/proc + 64 KB mmap/proc | 1.6-3.8 us per recorded HTTP request (measured) | negligible | none external; metric failures swallowed | **Adopted** |
| Prometheus | history, alert rules | 100-250 MB | low at 30 s scrape | ~30 MB/day (15 d ~ 0.4 GB, capped 2 GB) | one more container; if down, no history (app unaffected) | **Prepared, optional** (`docker-compose.monitoring.yml`, memory-capped, no published port) |
| Alertmanager | routing/dedup/silencing | ~30 MB | negligible | negligible | needs the unresolved routing decision | **Not added** - config prepared as comments only |
| node_exporter | host CPU/RAM/disk | ~20 MB | low | none | `pid: host` + read-only `/` mount | **Prepared, optional** (collectors limited) |
| Grafana | dashboards | 100-200 MB | low | small | another login surface to secure | **Definitions only** (JSON in repo) - the same queries work in Prometheus' UI |
| Loki (+ Promtail/Alloy) | cross-day log search | 300 MB-1 GB | medium (indexing) | logs x retention | heavy for a 1 VPS; storage growth | **Rejected for MVP.** JSON logs + `jq`/`grep` + Platform console log viewer cover investigation; revisit when retention needs exceed rotation |
| Tempo / Jaeger + OTel Collector | span storage and UI | 300 MB+ | medium | traces x retention | many moving parts; value is low in a modular monolith (few network hops) | **Rejected for MVP**; design in section 7 |
| Sentry / Datadog / New Relic | managed errors/APM | external | external | external | vendor, data-protection review of employee data leaving the VPS | **Not added** (paid/vendor - needs approval) |
| `cAdvisor` | per-container stats | ~50 MB | medium | none | not needed: Docker healthchecks + `hrms_monitor.sh` restart counts cover the need | **Rejected** |

## 5. Metrics design

### 5.1 Rules (enforced by tests)

* Labels come from closed vocabularies only. `ALLOWED_LABELS` in `core/observability/metrics.py` is the whole list; a unit test fails on any other label name and on any exposition containing `company_id=`, `employee_id=`, `user_id=`, `request_id=` or `email=`.
* HTTP `route` is the matched **template** (`/v1/employees/{employee_id}`), never the raw path; unmatched requests (404 scanners) collapse to `unmatched`. Unknown HTTP methods collapse to `OTHER`.
* Celery task name is a label only where it comes from the task's own registry; the name inside a *unknown-task* message (attacker/skew-controlled) is a log field, never a label.
* Metric recording helpers (`safe_count`, `safe_observe`, `record_http`) swallow every exception.
* A *successful* `/metrics` scrape and successful health probes are neither logged nor measured; a rejected scrape (401) is both logged and counted (corrected 2026-10-25 - it was previously invisible).

### 5.2 Multi-process model

`PROMETHEUS_MULTIPROC_DIR` (set in `docker-compose.prod.yml` for api, worker and beat to the shared `metrics_mp` volume) switches every counter/histogram to an mmap file named `<kind>_<hostname>-<pid>.db`. The hostname prefix prevents two containers' pid 7 from colliding. `/metrics` builds a fresh `MultiProcessCollector` per scrape. Verified with real separate interpreters (`test_metrics_multiprocess.py`) and with gunicorn x2 + a Celery worker (section 11 of the audit).

Deliberate omissions: no per-process "live" gauges (they need dead-pid cleanup hooks that the current `CMD` does not have) and therefore no in-flight-requests gauge; saturation is observed through latency, pool and error series instead. Point-in-time facts are computed at scrape time (`core/observability/scrape.py`), so a dead worker cannot leave a stale value. Connection-pool gauges describe only the worker that served the scrape; exhaustion is counted exactly in `hrms_errors_total{category="db_pool_exhausted"}`.

### 5.3 Series catalog

| Series | Labels | Emitted by | Meaning (attempt / committed / async) |
|---|---|---|---|
| `hrms_http_requests_total` | method, route, status_class | `RequestContextMiddleware._log_access` | response sent (committed outcome of the HTTP exchange) |
| `hrms_http_request_duration_seconds` | route | same | full request duration |
| `hrms_http_denials_total` | code (401/403/429) | same | access denials incl. rate limiting |
| `hrms_http_unhandled_exceptions_total` | category | `log_unhandled_exception` | exception reached the generic 500 |
| `hrms_errors_total` | source, category | HTTP handlers, `log_operation_outcome`, ... | server-side failure by stable `error_category` |
| `hrms_operations_total` | operation, outcome | `@logged_operation` | **attempt result**: `succeeded` = service method returned (transaction may still roll back); `rejected` = expected 4xx business/permission outcome (never counted as error); `failed` = 5xx/bug |
| `hrms_operation_duration_seconds` | operation | same | method duration |
| `hrms_committed_events_total` | event, entity_type | `emit_after_commit` -> `after_commit` | **committed** audited transition (dropped on rollback / savepoint rollback) |
| `hrms_security_events_total` | event, level | `security_event()` | auth/security decisions (`login.failed`, `account.locked`, `rate_limited`, `refresh.rejected`, ...) |
| `hrms_log_events_total` | level | log pipeline | volume by level (error-rate signal without parsing logs) |
| `hrms_log_dropped_writes_total` | source (stdout/file) | log sinks | **the signal that logs are being lost** |
| `hrms_db_query_duration_seconds` | - | engine listeners | statement latency; no SQL, no parameters |
| `hrms_db_rollbacks_total`, `hrms_db_connects_total` | - | engine listeners | rollback rate, connection churn |
| `hrms_dependency_calls_total`, `..._errors_total`, `..._call_duration_seconds` | dependency, outcome/category | e-mail sender, Face++ adapter, object storage (`core/storage.py`; categories `storage_full`, `storage_auth`, `storage_config`, `provider_error` derive only from the S3 error *code*; `NoSuchKey` counts as success) | external provider health (provider payloads never recorded) |
| `hrms_celery_tasks_published_total` | task | `before_task_publish` (API, tasks, Beat) | handed to broker |
| `hrms_celery_publish_failures_total` | task | `dispatch_per_company` | **never submitted** |
| `hrms_celery_tasks_started_total`, `..._finished_total{state}`, `..._task_retries_total`, `..._task_failures_total{category}`, `..._task_duration_seconds`, `..._task_queue_wait_seconds` | task (+state/category) | worker signals | **asynchronous result**; queue wait = start - `hrms_enqueued_at` |
| `hrms_celery_task_last_success_timestamp_seconds` | task | `task_postrun` SUCCESS | "did the daily job run" |
| `hrms_celery_messages_unroutable_total` | state | `task_unknown`/`task_rejected` | version skew |
| `hrms_dependency_up`, `hrms_dependency_probe_seconds` | dependency (database, redis) | scrape-time | availability + latency (2 s probe cap, cached 10 s) |
| `hrms_redis_*` | - | scrape-time `INFO` | memory, clients, evictions |
| `hrms_celery_queue_depth`, `..._queue_oldest_message_age_seconds`, `..._scheduler_heartbeat_age_seconds`, `hrms_jobs_probe_up` | queue | scrape-time via `hrms.ops.job_health` (read-only `LLEN`/`LINDEX`) | backlog, delay, scheduler liveness |
| `hrms_db_pool_*` | - | scrape-time | pool state of the serving worker |
| `hrms_log_filesystem_free_ratio`, `hrms_log_directory_bytes`, `hrms_metrics_directory_bytes` | - | scrape-time | disk pressure |

### 5.4 Histogram buckets (provisional)

HTTP: 25 ms ... 60 s (11 buckets; interactive routes live below 1 s, gunicorn kills at 60 s). DB: 1 ms ... 5 s. Task duration: 0.1 s ... 1800 s (company runs have a 1800 s hard limit). Queue wait: 0.1 s ... 900 s (heartbeat period is 60 s). Retune from observed percentiles after a baseline exists.

### 5.5 What the HRMS questions map to

| Question | Series |
|---|---|
| Are punches accepted, rejected or failing? | `hrms_operations_total{operation=~"attendance.*"}`: `rejected` is policy, `failed` is infrastructure; `hrms_dependency_*{dependency="face_provider"}` |
| Are leave approvals/accruals processed? | `hrms_operations_total{operation=~"leave.*"}`, `hrms_celery_task_last_success_timestamp_seconds{task=~"leave.*"}` |
| Payroll? | `hrms_operations_total{operation=~"payroll.*"}` + `hrms_operation_duration_seconds`. **Payroll is synchronous, there is no payroll Celery task**, so there is no queue to watch |
| Auth failures / rate limiting? | `hrms_security_events_total`, `hrms_http_denials_total` |
| Which organizations are affected? | not in metrics by design - `company_id` in `errors.log` (see runbook toolbox) |

## 6. Structured logging

Unchanged contract (JSON lines, redaction, per-module files, `flock` multi-process sink, `LOG_FILES_REQUIRED`), with additions: `trace_id`/`span_id` on every request and task line, `hrms_log_events_total`, `hrms_log_dropped_writes_total`. Field inventory: UTC `timestamp`, `level`, `logger`, `event`, `service` (api/worker/beat), `environment`, `request_id`, `trace_id`, `span_id`, `task_id`/`task_name`, `company_id`/`user_id` (membership-verified only), `operation`, `outcome`, `duration_ms`, `error_code`, `error_category`. Fields are never invented: a field appears only when its source exists.

## 7. Tracing

**Decision.** Implemented: *trace correlation* (zero cost). Not implemented: a tracing backend and span export.

* `core/observability/trace_context.py` honours a valid W3C `traceparent` from the caller, otherwise creates a trace; the ids are bound into the structlog context, so every log line of the request has them; `before_task_publish` stamps `hrms_traceparent` on the Celery message; the worker continues the trace with a new span id; a Beat-scheduled task starts its own trace. Malformed headers are ignored (never rejected); ids are random hex (no PII, no cardinality concern because they are log fields, not labels). Verified across processes at runtime: a trace id bound in one process appeared on the worker's `celery_task_finished` line.
* Why not full tracing now: the request path is a monolith with one database and one broker; the failure questions in the brief are answered by `request_id`/`trace_id` joins plus per-operation durations. A backend would add 300 MB+ and a new data-protection surface.
* **Implementation-ready design for later (disabled by default):** add `opentelemetry-sdk`, `opentelemetry-instrumentation-fastapi`/`-sqlalchemy`/`-celery`/`-httpx`; gate on `OTEL_ENABLED=true`; `ParentBased(TraceIdRatioBased(0.05))` sampling; `BatchSpanProcessor` with `max_queue_size=512`, `export_timeout=5s` (drops, never blocks); exporter to a local OTel Collector over OTLP; SQLAlchemy instrumentation with `enable_commenter=False` and statement capture off; span names = route template / task name / operation name; attributes limited to `http.route`, `http.status_code`, `hrms.operation`, `hrms.outcome`; no request/response bodies, no user or tenant ids on spans. Because the `traceparent` format is already used, switching on the SDK keeps existing ids valid.

## 8. Database observability

Implemented (application level, safe): statement latency histogram, rollback and connection counters, pool gauges, `db_*` error categories (`db_pool_exhausted`, `db_deadlock`, `db_timeout`, `db_connection`, ...), readiness `SELECT 1`, `hide_parameters=True` (pre-existing).

Found on the dev Postgres 16 container (read-only `pg_settings` query): `shared_preload_libraries=''` (no `pg_stat_statements`), `log_min_duration_statement=-1`, `log_lock_waits=off`, `statement_timeout=0`, `idle_in_transaction_session_timeout=0`, `max_connections=100`. **Recommended, requires approval (not applied):** `pg_stat_statements` (needs a restart; query text there can include literals - restrict access to the DBA role), `log_min_duration_statement=500ms`, `log_lock_waits=on`, `idle_in_transaction_session_timeout=60s`, and a sized `max_connections` check against `gunicorn workers x 15 + celery x 15`. Deadlocks/lock waits/long transactions are therefore **not observable today** except through application error categories.

## 9. Decisions required

> The one-line table below is the index. The prepared register - context, evidence, options, recommendation and the exact approval needed for D1, D5 and D8-D11 - is [section 15](#15-decision-register-prepared-for-approval-2026-10-25).

| ID | Decision | Alternatives | Recommendation |
|---|---|---|---|
| D1 | Alert destination and owner | e-mail relay (already have SMTP), chat webhook, pager | Start with e-mail to a shared ops mailbox via Alertmanager; add pager later. Needs a named owner |
| D2 | Deploy Prometheus (+node_exporter)? | stay on hand-scraped metrics + cron monitor | Yes, on the same VPS, 15 d / 2 GB cap, ~250 MB |
| D3 | Grafana? | Prometheus UI only | Later; dashboards are ready |
| D4 | Log backend? | files + `jq` | Defer until retention needs exceed section 10.1 |
| D5 | Postgres instrumentation settings (section 8) | none | Approve on staging first |
| D6 | External uptime probe for `/health/ready` | none | Yes - the only detector of "the whole VPS is down" |
| D7 | Tracing backend | correlation only | Defer |
| D8 | SLO targets, windows and error-budget policy (section 13) | none yet | Collect 2-4 weeks of staging/pilot baseline, then owner-approve targets |
| D9 | Leave reconciliation (see audit 2026-10-25 re-audit): add a ledger-vs-applications consistency check? | not needed (balance is derived) / report-only job / enforcement | Product decision: the balance is `SUM(leave_ledger.amount)`, so there is no second copy to drift. A check would reconcile *approved applications against ledger deductions* - a new business rule, not an instrumentation gap |
| D10 | Payroll execution model | stay synchronous / durable background job | Decide after a staging load test at realistic headcount (engine CPU is 13 us/employee, measured; the unmeasured cost is per-employee database work against the 60 s gunicorn limit) |
| D11 | Append-only grant regression check (section 14) | none / gauge / CI-only | Gauge, owner: DBA/security |

## 10. Capacity (estimates - assumptions stated, not measured production numbers)

### 10.1 Logs

Measured: one `http_request` line ~ 450-500 bytes. Each request is written to `api.log`, `app.log` and stdout (and `auth.log` when it is a security event) - about 3 copies, ~1.5 KB/request. Assumption: ~100 requests per employee per day (mobile polling + web).

| Scenario | Requests/day | Disk/day (all sinks) | `api.log` retention at default 10 MB x 6 files |
|---|---|---|---|
| Pilot, 50 employees | 5 k | ~7 MB | ~13 days |
| 500 employees | 50 k | ~75 MB | ~2.6 days |
| 1 000 employees | 100 k | ~150 MB | ~1.3 days |

Hard ceilings: app log files <= 14 files x 10 MB x 6 = **~840 MB**; Docker json-file <= ~10 containers x 10 MB x 5 = **~500 MB**. For more than a few days of history at 500+ employees raise `LOG_FILE_MAX_BYTES`/`LOG_FILE_BACKUP_COUNT` (still bounded) or adopt D4.

### 10.2 Metrics

Worst-case series (bounded by the 235 route templates / 335 operations in the OpenAPI document and the closed vocabularies): HTTP requests ~1.0 k, HTTP histograms ~3.3 k, operations ~0.7 k, Celery ~0.8 k, committed/security/errors/other ~0.4 k, scrape-time ~0.05 k: **~6 k series**. At 30 s: 6 k x 2 880 = 17 M samples/day, ~1.5 B/sample => **~27 MB/day, ~0.4 GB for 15 days**. `/metrics` response: ~6 k lines ~ 0.6 MB worst case (215 lines idle, measured). mmap files: ~64 KB x 2 per process ever started (wipe on redeploy). Prometheus head memory: roughly 3-6 KB/series => 20-40 MB plus runtime overhead; budget 512 MB cap.

### 10.3 Application overhead

Measured microbenchmark: `record_http` 1.6 us (single process) / 3.75 us (mmap multiprocess). Per-scrape cost (DB `SELECT 1`, Redis `PING`+`INFO`, `LLEN`/`LINDEX`) is bounded by 2 s timeouts and cached 10 s; not load-tested.

### 10.4 Storage-full behaviour

Log file write failure: line dropped, `hrms_log_dropped_writes_total{source="file"}` increments, in-band notice when it recovers, stdout copy unaffected, API keeps serving (`LOG_FILES_REQUIRED=true` makes it refuse to boot instead). Metrics file failure: recording is swallowed. Prometheus: oldest blocks deleted at `retention.size`.

## 11. Security and privacy

* `/metrics`: 404 unless `METRICS_TOKEN` (>= 24 chars) is set; bearer compare in constant time; not in OpenAPI; Nginx returns 404 for `/metrics` at the edge; Prometheus reaches `api:8000` on the private network. A rejected request is logged as an ordinary `http_request` event and counted in `hrms_http_denials_total` (401); only a successful scrape is left out. The path is not reachable from outside the private network, so the log-flood risk is limited to containers on it.
* No user JWT works on `/metrics` and the output contains no tenant data (tested: no UUID, no `@` in any sample line).
* Redaction pipeline, `subject_hash`, `hide_parameters` unchanged. Trace ids are random. No new field carries PII.
* Optional monitoring containers publish no ports and are memory-capped (tested).
* Access to log files: owner `hrms` inside the container, files `0640`; the Platform console log viewer is audited (`security.platform.logs_viewed`).

## 12. Failure modes

| Failure | Behaviour |
|---|---|
| Metrics volume unwritable / mmap error | recording swallowed, request unaffected (an unwritable dir at *import* would fail value creation - mitigated by the Dockerfile creating `/app/metrics` owned by `hrms`) |
| Scraper down | no history; app unaffected; `hrms_monitor.sh` continues independently |
| Redis/DB down during scrape | `hrms_dependency_up 0`; the scrape itself still succeeds |
| Prometheus restarts | counters resume from the files; resets are normal for Prometheus |

## 13. Service-level objectives (proposal; nothing here is adopted)

There is **no production baseline and no named service owner**, so no target is proposed - inventing one would be a guess presented as a commitment. What *can* be fixed now is what to measure, from series that already exist, and how to tell user-impacting failure from expected business rejection. Targets, windows and error-budget policy are owner decisions (D8).

| SLI | Good events / valid events | Excluded from "valid" | Series |
|---|---|---|---|
| API availability | responses not `5xx` / all responses | `4xx` (validation, authorization, rate limiting, `STALE_RESOURCE`) are the caller's outcome; health and `/metrics` | `hrms_http_requests_total{status_class}` |
| API latency | requests under a threshold / all requests | `/health*` | `hrms_http_request_duration_seconds_bucket{le}` (threshold must be one of the existing buckets: 0.5, 1, 2.5, 5, 10 s) |
| Critical workflow success (attendance, leave, payroll) | `outcome="succeeded"` / (`succeeded` + `failed`) | `outcome="rejected"` - a policy rejection is a correct answer, never an SLO miss | `hrms_operations_total{operation,outcome}` |
| Scheduled job freshness | jobs whose last success is younger than their period + slack | - | `hrms_celery_task_last_success_timestamp_seconds` |
| Dependency availability | probe successes / probes | - | `hrms_dependency_up` (a 2 s probe; sampled per scrape, not per request) |

Error-budget arithmetic, so the owner can choose with the cost in view (30-day month): 99.0% = 7 h 12 min, 99.5% = 3 h 36 min, 99.9% = 43 min, of full outage-equivalent. Burn-rate alerting (fast and slow window pair) should be added only after a target exists and 2-4 weeks of baseline show which one is achievable; it is **not implemented**. Caveats that affect any SLO: the pool gauge and probes describe the scraped worker only; a metric that has never been incremented has no series (use `or vector(0)` in SLI queries that must return 0); the internal probe cannot see an outage of the whole VPS (D6, external uptime probe, is the only detector).

## 14. Known limits found by the 2026-10-25 re-audit

* **Connection acquisition wait time is not measured.** Pool exhaustion is counted exactly (`hrms_errors_total{category="db_pool_exhausted"}`) and the pool gauge shows saturation for the serving worker, but the time a request spends waiting for a connection before the 30 s timeout is not a series. Add a `checkout`-event histogram only if saturation alerts prove too late (P3).
* **Celery `unacked` messages are invisible.** Queue depth/age use `LLEN`/`LINDEX` on the ready list; messages a worker has reserved but not acknowledged live elsewhere in Redis. A worker that crashes holding many prefetched tasks looks like a *shrinking* queue until the visibility timeout returns them. The task-level counters (`started` vs `finished`) are the cross-check.
* **Readiness does not test object-store capacity or credentials** (it checks configuration only, by design - a storage hiccup must not take the API out of rotation). A full or misconfigured store therefore surfaces only through `hrms_dependency_errors_total{dependency="storage"}` after the first failed call (`HrmsObjectStorageRejectingCalls`). Observed live on the dev machine the same day: root disk 100% -> MinIO `XMinioStorageFull` -> document uploads returned 500.
* **Only the log volume's free space is exported** (`hrms_log_filesystem_free_ratio`). The Postgres and MinIO volumes are covered only once `node_exporter` is deployed.
* **Database role grants can silently regress.** `infra/docker/postgres/init/002_app_role.sh` grants broad DML with `ALL TABLES` and default privileges; migrations then `REVOKE UPDATE, DELETE` on append-only tables (`leave_ledger`, ...). Re-running the script on an already-migrated database re-grants them (reproduced: `hrms_app` goes from `INSERT,SELECT` to `DELETE,INSERT,SELECT,UPDATE` on `leave_ledger`). In production the script only runs on first initialisation of an empty data directory, so the risk is operator error, not normal operation. Recommendation (not implemented, needs a DBA/security decision): a periodic or readiness-adjacent check that `hrms_app` has no `UPDATE`/`DELETE` on the append-only tables, exported as a gauge.

## 15. Decision register (prepared for approval, 2026-10-25)

Nothing below is approved, enabled or implemented unless it says so. No e-mail address, destination or threshold is invented; where a value needs a baseline it is marked **PROPOSAL**.

### D1 - Alert recipients and ownership

Decision needed: a named person or group per column below, a destination (D1 in section 9 recommends an e-mail relay via Alertmanager first), and an escalation rule. **Owner of the decision: the service owner / engineering lead.**

| Responsibility group | Alerts (count) | Why this group |
|---|---|---|
| Application operations | 23 | API, Celery, Redis, logs, disk, object storage, providers: things an operator on the VPS fixes |
| Database operations | 3 | `HrmsDatabaseDown`, `HrmsDbPoolExhausted`, `HrmsDbPoolSaturated` |
| Business workflow owners (HR operations / payroll) | 7 | `HrmsPayrollRunFailing`, the four "scheduled job missed" alerts, `HrmsAttendanceInfrastructureFailures`, `HrmsLeaveOperationFailures`: the *business* consequence lands on them, the fix on application ops |
| Security | 3 | `HrmsLoginFailuresElevated`, `HrmsAccountLockouts`, `HrmsRateLimitingActive` |

Response expectation, taken from each rule's own `severity` label (12 critical, 16 high, 8 warning = 36):

* **Immediate human action (critical, 12):** `HrmsApiDown`, `HrmsDatabaseDown`, `HrmsSchedulerHeartbeatStale`, `HrmsSchedulerHeartbeatMissing`, `HrmsPayrollRunFailing`, the four scheduled-job-missed alerts (`HrmsLeaveRunMonthlyAccrualMissed`, `HrmsLeaveRunCompOffExpirySweepMissed`, `HrmsLeaveRunYearEndSweepMissed`, `HrmsAttendanceRunDailyCalculationMissed`), `HrmsDiskCritical`, `HrmsLogWritesFailing`, `HrmsObjectStorageRejectingCalls`. Two of them (payroll, scheduled jobs) fire for a business reason, so the business owner must be told even if the fix is technical.
* **Same working day, within the hour in business hours (high, 16):** 5xx rate, unhandled exceptions, p99 latency, queue backlog/age, task failures/publish failures/unroutable, Redis down/memory, DB pool exhausted/saturated, attendance/leave failures, provider errors, `HrmsScheduledTaskNeverSucceeded`.
* **Routine review, daily (warning, 8):** `HrmsDiskLow`, p95 latency, retry rate, error-log rate, `HrmsProbeBlind`, and the three security-volume alerts (review for patterns, not for a page).

Prerequisites before any alert can notify: Alertmanager (not deployed), a destination, and an on-call schedule. Until then rules are visible only in the Prometheus UI, and `infra/monitoring/hrms_monitor.sh` remains the single implemented alerter.

### D5 - PostgreSQL observability settings (nothing applied)

**Approval needed:** the database/platform owner, on staging first. All settings are server-level; the compose file currently runs stock `postgres:16-alpine` with no custom configuration, so they would be added as `command: -c ...` arguments or `ALTER SYSTEM` (the exact placement is part of the approval).

| Setting | Purpose | Overhead | Security / privacy | Restart? | Rollback |
|---|---|---|---|---|---|
| `shared_preload_libraries='pg_stat_statements'` + `CREATE EXTENSION pg_stat_statements` | per-statement call count, total/mean time, rows - finds the slow statement, not just the slow request | typically low single-digit % CPU; shared memory about 5 MB at the default `pg_stat_statements.max=5000` | stores *normalised* statement text (constants replaced by `$n`), readable by superusers and `pg_read_all_stats`; no parameter values. Contrib ships in the official image | **yes** | remove from `shared_preload_libraries`, restart; `DROP EXTENSION` |
| `log_min_duration_statement` (**PROPOSAL** start 1000 ms; needs the D8 baseline) | slow-statement log lines | log volume proportional to slow statements; Docker log cap (10 MB x 5) bounds it | **statement logging can include bound parameter values (PII: names, salaries).** Must be paired with `log_parameter_max_length=0` (and `log_parameter_max_length_on_error=0`) so values are never written | no (reload) | `ALTER SYSTEM RESET log_min_duration_statement; SELECT pg_reload_conf();` |
| `log_lock_waits=on` (with the default `deadlock_timeout=1s`) | logs any lock wait longer than `deadlock_timeout`, plus deadlock details | negligible | same parameter caveat as above | no | reset + reload |
| `track_io_timing=on` | I/O time per statement in `pg_stat_statements` | small on modern Linux; verify with `pg_test_timing` first | none | no | reset + reload |
| `log_line_prefix` including `%m %p %u@%d` | joins a Postgres line to a connection and role | none | exposes role/database names (not secrets) | no | reset + reload |
| `idle_in_transaction_session_timeout`, `statement_timeout` (per-role on `hrms_app`, not global) | stops runaway sessions - **behaviour-changing, not observability** | none | none | no | `ALTER ROLE hrms_app RESET ...` |

**Verified on the local `postgres:16-alpine` (16.14) container, 2026-10-25 (read-only `pg_settings`):** `pg_stat_statements` ships with the image (extension files and library present) and `shared_preload_libraries` is empty; `log_min_duration_statement=-1`, `log_lock_waits=off`, `track_io_timing=off`, `statement_timeout=0`, `idle_in_transaction_session_timeout=0`, and - important - **`log_parameter_max_length=-1` (unlimited)**, so turning on slow-statement logging without also setting it to `0` *would* write bound parameter values to the log.

Not recommended now: `auto_explain` (logs plans, higher overhead and exposure), a `postgres_exporter` sidecar (another service to run; the application already exports pool and statement latency), `log_statement=all` (floods logs and leaks values). **Compatibility:** all settings above exist in PostgreSQL 16 (`log_parameter_max_length` since 13). **`statement_timeout` must be at least the 60 s gunicorn timeout** or it will cut payroll requests off first - set only after the D10 load test.

### D8 - SLO targets

Approach (the SLIs and error-budget table are in section 13):

1. **Evidence period:** at least 28 days of staging or pilot traffic with production-like usage (one full payroll cycle and one month-end if possible), recorded by the existing series; a shorter period cannot show weekly or monthly peaks (attendance punches cluster at shift start; payroll and leave accruals are monthly).
2. **Business inputs the owner must supply:** contractual or promised availability, support hours (is a 02:00 outage worth waking someone?), payroll deadlines (how late can a pay run finish?), punch-window tolerance (how long may a punch take before employees retry?), number of tenants and employees at pilot and at launch.
3. **Measure first, then choose:** compute the achieved SLI over the period, set the target slightly below what was achieved on healthy days, then tighten.
4. **Candidate targets - PROPOSALS ONLY, not baseline-backed and not approved:**

| SLO | Candidate | Reasoning / data needed |
|---|---|---|
| API availability (non-5xx / valid) | 99.5% over 30 days (error budget about 3 h 36 min) | a single-VPS deployment with no redundancy cannot credibly promise more; confirm against the support-hours decision |
| API latency | 95% of non-health requests under 1 s, 99% under 2.5 s | both are existing histogram buckets (1.0, 2.5); no measured baseline yet |
| Attendance punch workflow | 99.9% of `attendance.punch.*` operations `succeeded` among `succeeded + failed` (rejections excluded) | needs real punch volume |
| Background-job freshness | each daily scheduled task completes within 26 h of the previous success (this is the threshold the missed-job alerts already use) | evidence: `hrms_celery_task_last_success_timestamp_seconds` history |
| Queue freshness | oldest ready message under 10 min | alert currently uses 600 s, also provisional |
| Payroll run | compute completes within a window the payroll owner sets | depends on D10 measurement |

Burn-rate alerting is added only after targets are approved.

### D9 - Leave consistency check

Facts (verified): the balance is `SUM(leave_ledger.amount)`; there is no mutable balance column and no reconciliation workflow; the ledger is append-only (enforced by grants, D11).

Two different things are being asked for:

* **Instrumenting existing ledger operations** - counting and timing what already happens (`leave.*` operations, entries appended by `entry_type`, accrual/expiry task freshness). No new business meaning; safe to do now. Mostly present already via `hrms_operations_total` and the scheduled-job freshness alerts; an entries-by-type counter would be the only addition.
* **A new consistency check** - asserting that approved applications and ledger deductions agree. This *defines* what "agree" means, so it is a business-rule decision, not instrumentation. It cannot be written until finance/HR agree on at least: which application states create ledger rows (the model has a `reserved_balance`, so SUBMITTED may reserve and APPROVED may deduct); how half-days, sandwich days and loss-of-pay splits (`lop_days`) map to amounts; how cancellations before and after the start date restore balance; how comp-off credits, carry-forward, year-end lapse and encashment (which have no application) are excluded or matched; which leave-year the entry belongs to at a boundary; how policy changes mid-year and negative balances are treated; rounding tolerance; who owns a discrepancy and how it is corrected (only by appending a compensating entry, since the ledger is append-only); whether the check is report-only or blocks payroll (payslips snapshot leave balances at month end). Recommendation: first agree the written rules, then run a read-only report against a copy of real data, then decide whether it becomes a scheduled job with an alert. **Owner: HR/finance product owner with engineering.**

### D10 - Payroll execution model

Inspected call path (`modules/payroll/service.py`): `lock_inputs` builds one snapshot per employee then inserts them; `compute` runs as **one transaction inside one HTTP request**: status transition guarded by `If-Match` version and `from_statuses` first, then one `UPDATE ... RETURNING` per employee (sequential round trips), then one ORM insert of every pay line, then arrears rows and the audit record. A killed or timed-out request rolls back completely, so there is no partial state; a re-run replaces the lines, so it is idempotent; a duplicate run for the same entity and month is impossible (`pay_run_entity_month_uq`). The calculation itself is 13 microseconds per employee (measured). **Not measured:** database time per employee, snapshot build time, memory for N employees, which is where a 60 s limit would actually be hit.

Recommendation:

1. **Keep synchronous** for the small transitions (`approve`, `finalise`, `mark_paid`, `rollback`) - one row each.
2. **Do not move `lock_inputs`/`compute` yet.** First measure on staging with synthetic employees at realistic and 5-10x headcount (for example 500, 2 000, 5 000) using `hrms_operation_duration_seconds{operation="payroll.pay_run.compute"}`, and with the D5 statement statistics enabled to count statements.
3. **Cheap intermediate step before any redesign:** replace the per-employee `UPDATE` loop with a single set-based statement (one round trip instead of N). It keeps the semantics, the transaction and the API unchanged.
4. **Move to a durable background job** (Celery already runs; a dedicated queue avoids starving others) if measured p95 exceeds about one third of the 60 s limit at the *expected* headcount, or if headcount is expected to exceed the measured safe size. Design constraints: a `COMPUTING` status guarded by the same version check, a per-run lock so two workers cannot compute one run, `202 Accepted` plus polling, the same single transaction (so no partial results), failure recorded with a stable category, and the existing duration/failure metrics and alerts kept. **Requires explicit approval; execution semantics and API contract change.**

Nothing was run against real payroll data.

### D11 - Append-only database grants

Evidence (read-only query of the dev database, runtime role `hrms_app`, 113 public tables):

| Tables | Runtime role may |
|---|---|
| `audit_log`, `email_log`, `leave_application_action`, `leave_ledger`, `leave_year_end_run`, `platform_audit_log` | INSERT, SELECT only (no UPDATE, DELETE or TRUNCATE) - enforced |
| `idempotency_key` | INSERT, SELECT, UPDATE; no DELETE or TRUNCATE |
| **all 113 tables** | **never TRUNCATE** |
| `punch`, `attendance_regularization_action`, `attendance_period_action` | **UPDATE and DELETE are granted**, although their models document them as immutable / append-only (`punch`: "Never UPDATE'd or DELETE'd (WD-11)"). No code path mutates them (searched), so the documented rule is held by convention only |

Findings and recommendation (**owner: database/security owner; needs a migration and a staging run - not applied**):

1. Decide whether `punch` and the two attendance timeline tables should be enforced append-only like the leave equivalents. The code suggests yes; confirm no operational procedure (data correction, GDPR-style deletion, face-data retention) needs DELETE on them.
2. Keep one declarative list of append-only tables and assert it in CI. A guard test is added in this pass (`tests/integration/core/test_runtime_role_grants.py`): the six enforced tables have no UPDATE/DELETE/TRUNCATE for the runtime role, `idempotency_key` has no DELETE/TRUNCATE, and no public table can be truncated by the runtime role. It also fails if a listed table is renamed (so it cannot go vacuous). It runs in the existing CI integration step and in `run_full_tests.py`.
3. The regression this guards against was reproduced: re-running `infra/docker/postgres/init/002_app_role.sh` on a migrated database re-grants UPDATE/DELETE. The runner now recreates its test database; production runs that script only on first initialisation.
4. Once approved, add `punch` and the two timelines to the guard list in the same change as the migration.
5. Operational check for real environments: the query in the runbook (section 9). A periodic gauge is possible but optional; it needs the same owner.

No grant on any shared or production database was changed.
