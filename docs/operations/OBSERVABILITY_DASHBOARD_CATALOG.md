# Observability dashboard catalog

> **Status.** Definitions only. No Grafana is installed or approved. The five dashboards below are version-controlled as JSON in [`infra/monitoring/grafana/dashboards/`](../../infra/monitoring/grafana/dashboards/) (generated from [`generate_dashboards.py`](../../infra/monitoring/grafana/generate_dashboards.py) - edit the script, not the JSON). All 44 PromQL queries parse (`promtool check rules` over each expression, re-run 2026-10-25, exit 0). On 2026-10-25 all 44 were also **evaluated against a live Prometheus** scraping a real 2-worker API: 0 errors, 17 returned data, 27 were empty only because that run had no Celery worker, no `node_exporter` and no business traffic (every one of those needs a producer that was not running). Nothing has been rendered in Grafana or against production traffic, so **panel usefulness is NOT TESTED against real traffic**.

**Empty vs zero.** Panels that *count bad events* (5xx ratio, failing routes, denials, unhandled exceptions, dependency errors, task failures/retries/publish failures, attendance failures, provider errors, login failures) set `noValue: "0"`: a Prometheus counter has no series until its first increment, so a healthy system legitimately returns nothing. Panels that *measure a live value* (up, heartbeat age, queue depth, latency, node CPU/RAM/disk) deliberately keep Grafana's "No data" - there, empty means the telemetry is missing and must not be read as healthy. The distinction lives in `generate_dashboards.py` (`zero_when_empty`).

Import: Grafana -> Dashboards -> Import -> upload JSON, choose the Prometheus data source (the `DS_PROMETHEUS` variable). Prometheus must scrape the `hrms-api` job (and `node` for host panels) - see [`prometheus.yml`](../../infra/monitoring/prometheus/prometheus.yml).

Until Grafana exists, the same queries can be pasted into the Prometheus expression browser, and operators have today: `python -m hrms.ops.job_health`, `infra/monitoring/hrms_monitor.sh`, and the Platform console log/e-mail viewers.

Reading guide: `outcome="rejected"` is an expected business/policy result (validation, permission, conflict); only `outcome="failed"` is a server-side failure. `succeeded` means the service method returned - committed state is `hrms_committed_events_total`.

## A. System overview
File: `hrms-a-system-overview.json`

| Panel | Query | Notes |
|---|---|---|
| API up | `up{job="hrms-api"}` |  |
| Database up | `hrms_dependency_up{dependency="database"}` |  |
| Redis up | `hrms_dependency_up{dependency="redis"}` |  |
| Scheduler heartbeat age | `hrms_celery_scheduler_heartbeat_age_seconds` | Over 300 s means Beat/worker are not running. |
| Throughput | `sum(rate(hrms_http_requests_total[5m]))` |  |
| 5xx error ratio | `sum(rate(hrms_http_requests_total{status_class="5xx"}[5m])) / sum(rate(hrms_http_requests_total[5m]))` |  |
| Latency p50/p95/p99 | `histogram_quantile(0.5, sum by (le) (rate(hrms_http_request_duration_seconds_bucket{route!~"/health.*"}[5m]))) ; histogram_quantile(0.95, sum by (le) (rate(hrms_http_request_duration_seconds_bucket{route!~"/health.*"}[5m]))) ; histogram_quantile(0.99, sum by (le) (rate(hrms_http_request_duration_seconds_bucket{route!~"/health.*"}[5m])))` |  |
| CPU used | `1 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m]))` |  |
| Memory available | `node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes` |  |
| Disk free (host /) | `node_filesystem_avail_bytes{mountpoint="/host"} / node_filesystem_size_bytes{mountpoint="/host"} ; hrms_log_filesystem_free_ratio` |  |

## B. API performance
File: `hrms-b-api-performance.json`

| Panel | Query | Notes |
|---|---|---|
| Slowest routes (p95) | `topk(10, histogram_quantile(0.95, sum by (le, route) (rate(hrms_http_request_duration_seconds_bucket{route!~"/health.*"}[5m]))))` |  |
| Top failing routes (5xx/s) | `topk(10, sum by (route) (rate(hrms_http_requests_total{status_class="5xx"}[5m])))` |  |
| Status distribution | `sum by (status_class) (rate(hrms_http_requests_total[5m]))` |  |
| Busiest routes | `topk(10, sum by (route) (rate(hrms_http_requests_total[5m])))` |  |
| Access denials (401/403/429) | `sum by (code) (rate(hrms_http_denials_total[5m]))` |  |
| Unhandled exceptions | `sum by (category) (increase(hrms_http_unhandled_exceptions_total[15m]))` |  |
| DB query latency p95 | `histogram_quantile(0.95, sum by (le) (rate(hrms_db_query_duration_seconds_bucket[5m])))` |  |
| DB pool (serving worker) | `hrms_db_pool_checked_out ; hrms_db_pool_capacity` |  |
| Dependency errors | `sum by (dependency, category) (increase(hrms_dependency_errors_total[15m]))` |  |

## C. Background jobs
File: `hrms-c-background-jobs.json`

| Panel | Query | Notes |
|---|---|---|
| Tasks by outcome | `sum by (state) (rate(hrms_celery_tasks_finished_total[15m]))` |  |
| Failures by task | `sum by (task) (increase(hrms_celery_task_failures_total[1h]))` |  |
| Retries by task | `sum by (task) (increase(hrms_celery_task_retries_total[1h]))` |  |
| Task duration p95 | `histogram_quantile(0.95, sum by (le, task) (rate(hrms_celery_task_duration_seconds_bucket[1h])))` |  |
| Queue depth | `hrms_celery_queue_depth` |  |
| Oldest queued message | `hrms_celery_queue_oldest_message_age_seconds` |  |
| Queue wait p95 | `histogram_quantile(0.95, sum by (le, task) (rate(hrms_celery_task_queue_wait_seconds_bucket[1h])))` |  |
| Time since last success | `time() - hrms_celery_task_last_success_timestamp_seconds` | Scheduled jobs: daily jobs should stay under ~26 h. |
| Publish failures (never submitted) | `sum by (task) (increase(hrms_celery_publish_failures_total[1h]))` |  |
| Scheduler heartbeat age | `hrms_celery_scheduler_heartbeat_age_seconds` |  |

## D. HRMS operations
File: `hrms-d-hrms-operations.json`

| Panel | Query | Notes |
|---|---|---|
| Attendance operations | `sum by (operation, outcome) (increase(hrms_operations_total{operation=~"attendance\..*"}[1h]))` | rejected = policy outcome (expected); failed = server-side. |
| Attendance server-side failures | `sum(increase(hrms_operations_total{operation=~"attendance\..*",outcome="failed"}[15m]))` |  |
| Punch latency p95 | `histogram_quantile(0.95, sum by (le) (rate(hrms_operation_duration_seconds_bucket{operation=~"attendance\.(punch\|face)\..*"}[15m])))` |  |
| Leave operations | `sum by (operation, outcome) (increase(hrms_operations_total{operation=~"leave\..*"}[1h]))` |  |
| Leave accrual/expiry runs | `sum by (operation, outcome) (increase(hrms_operations_total{operation=~"leave\.(accrual\|comp_off\|year_end)\..*"}[24h]))` |  |
| Payroll operations | `sum by (operation, outcome) (increase(hrms_operations_total{operation=~"payroll\..*"}[24h]))` |  |
| Payroll compute duration p95 | `histogram_quantile(0.95, sum by (le) (rate(hrms_operation_duration_seconds_bucket{operation="payroll.pay_run.compute"}[24h])))` |  |
| Committed audited transitions | `topk(10, sum by (entity_type) (increase(hrms_committed_events_total[1h])))` |  |
| Employee-import tasks | `sum by (state) (increase(hrms_celery_tasks_finished_total{task=~"employee_import\..*"}[24h]))` |  |
| Email / face provider errors | `sum by (dependency, category) (increase(hrms_dependency_errors_total[1h]))` |  |
| Login failures / lockouts | `sum by (event) (increase(hrms_security_events_total{event=~"login.failed\|platform.login.failed\|account.locked\|rate_limited"}[1h]))` |  |

## E. Logs and incidents

**Not implemented as a Grafana dashboard.** It needs a log backend (Loki) that is deliberately not part of the minimum design. What exists today and covers the panel list:

| Need | Today |
|---|---|
| Error events | `logs/errors.log` (only file with tracebacks); Platform console log viewer (`/v1/platform/logs`, access recorded as `security.platform.logs_viewed`); `hrms_log_events_total{level="error"}` for the rate |
| Correlation | `request_id` (response header `X-Request-Id`) and `trace_id` appear on every line of a request and of the Celery task it dispatched: `grep -h '<id>' logs/*.log \| jq -c .` |
| Service / module filters | one file per module: `api auth attendance leave payroll employees recruitment documents notifications background_jobs database platform`; field `service` = `api` / `worker` / `beat` |
| Incident timeline | Prometheus `ALERTS` series (once deployed) + `grep` over `app.log` by `timestamp` |

If a log backend is later approved, Loki + Promtail (or Grafana Alloy) can ingest `/app/logs/*.log` unchanged - the lines are already JSON - and this dashboard would be: error rate by `logger`, a table of `errors.log` lines, and a `trace_id` / `request_id` search box.

## Final-gate re-verification (2026-10-25)

Newly executed on the current files: all 4 JSON files valid, 40 panels, 44 queries accepted by `promtool check rules` (exit 0), every referenced metric exported by the code. The live-data evaluation (0 errors, 17 of 44 with data) is carried forward from the earlier run; no observability file changed afterwards other than regenerating the dashboards to add `noValue`, which does not alter any query. Grafana rendering: NOT RUN.
