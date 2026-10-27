#!/usr/bin/env python3
"""Generates the Grafana dashboards in ./dashboards from one source of truth.

Dashboards are *definitions for later deployment* (no Grafana is installed by this repository).
Every panel is a PromQL query over metrics documented in
docs/architecture/OBSERVABILITY_ARCHITECTURE.md; docs/operations/OBSERVABILITY_DASHBOARD_CATALOG.md
explains each panel. Re-run after editing:   python3 generate_dashboards.py
"""

import json
from pathlib import Path

OUT = Path(__file__).parent / "dashboards"
DS = {"type": "prometheus", "uid": "${DS_PROMETHEUS}"}

LAT = 'sum by (le) (rate(hrms_http_request_duration_seconds_bucket{{route!~"/health.*"{extra}}}[5m]))'


def panel(title, exprs, unit="short", kind="timeseries", desc="", zero_when_empty=False):
    """`zero_when_empty` is for panels that COUNT bad events (errors, failures, denials): a Prometheus
    counter has no series until its first increment, so a healthy system returns an empty result,
    which Grafana would show as "No data". Those panels read 0 instead. Panels that measure a live
    value (heartbeat age, queue depth, up) keep "No data" - there, empty means telemetry is missing
    and must stay distinguishable from a real zero."""
    defaults = {"unit": unit}
    if zero_when_empty:
        defaults["noValue"] = "0"
    return {
        "title": title,
        "type": kind,
        "description": desc,
        "datasource": DS,
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "targets": [
            {"expr": e, "legendFormat": legend, "refId": chr(65 + i)}
            for i, (e, legend) in enumerate(exprs)
        ],
    }


DASHBOARDS = {
    "hrms-a-system-overview": ("HRMS - A. System overview", [
        panel("API up", [('up{job="hrms-api"}', "api")], kind="stat"),
        panel("Database up", [('hrms_dependency_up{dependency="database"}', "db")], kind="stat"),
        panel("Redis up", [('hrms_dependency_up{dependency="redis"}', "redis")], kind="stat"),
        panel("Scheduler heartbeat age", [("hrms_celery_scheduler_heartbeat_age_seconds", "age")], "s", "stat",
              "Over 300 s means Beat/worker are not running."),
        panel("Throughput", [("sum(rate(hrms_http_requests_total[5m]))", "req/s")], "reqps"),
        panel("5xx error ratio", [('sum(rate(hrms_http_requests_total{status_class="5xx"}[5m])) / sum(rate(hrms_http_requests_total[5m]))', "5xx")], "percentunit", zero_when_empty=True),
        panel("Latency p50/p95/p99", [(f"histogram_quantile({q}, {LAT.format(extra='')})", f"p{int(q*100)}") for q in (0.5, 0.95, 0.99)], "s"),
        panel("CPU used", [('1 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m]))', "cpu")], "percentunit"),
        panel("Memory available", [("node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes", "free")], "percentunit"),
        panel("Disk free (host /)", [('node_filesystem_avail_bytes{mountpoint="/host"} / node_filesystem_size_bytes{mountpoint="/host"}', "free"),
                                     ("hrms_log_filesystem_free_ratio", "log volume")], "percentunit"),
    ]),
    "hrms-b-api-performance": ("HRMS - B. API performance", [
        panel("Slowest routes (p95)", [(f'topk(10, histogram_quantile(0.95, sum by (le, route) (rate(hrms_http_request_duration_seconds_bucket{{route!~"/health.*"}}[5m]))))', "{{route}}")], "s"),
        panel("Top failing routes (5xx/s)", [('topk(10, sum by (route) (rate(hrms_http_requests_total{status_class="5xx"}[5m])))', "{{route}}")], "reqps", zero_when_empty=True),
        panel("Status distribution", [("sum by (status_class) (rate(hrms_http_requests_total[5m]))", "{{status_class}}")], "reqps"),
        panel("Busiest routes", [("topk(10, sum by (route) (rate(hrms_http_requests_total[5m])))", "{{route}}")], "reqps"),
        panel("Access denials (401/403/429)", [("sum by (code) (rate(hrms_http_denials_total[5m]))", "{{code}}")], "reqps", zero_when_empty=True),
        panel("Unhandled exceptions", [("sum by (category) (increase(hrms_http_unhandled_exceptions_total[15m]))", "{{category}}")], zero_when_empty=True),
        panel("DB query latency p95", [("histogram_quantile(0.95, sum by (le) (rate(hrms_db_query_duration_seconds_bucket[5m])))", "p95")], "s"),
        panel("DB pool (serving worker)", [("hrms_db_pool_checked_out", "checked out"), ("hrms_db_pool_capacity", "capacity")]),
        panel("Dependency errors", [("sum by (dependency, category) (increase(hrms_dependency_errors_total[15m]))", "{{dependency}}/{{category}}")], zero_when_empty=True),
    ]),
    "hrms-c-background-jobs": ("HRMS - C. Background jobs", [
        panel("Tasks by outcome", [("sum by (state) (rate(hrms_celery_tasks_finished_total[15m]))", "{{state}}")], "ops"),
        panel("Failures by task", [("sum by (task) (increase(hrms_celery_task_failures_total[1h]))", "{{task}}")], zero_when_empty=True),
        panel("Retries by task", [("sum by (task) (increase(hrms_celery_task_retries_total[1h]))", "{{task}}")], zero_when_empty=True),
        panel("Task duration p95", [("histogram_quantile(0.95, sum by (le, task) (rate(hrms_celery_task_duration_seconds_bucket[1h])))", "{{task}}")], "s"),
        panel("Queue depth", [("hrms_celery_queue_depth", "{{queue}}")]),
        panel("Oldest queued message", [("hrms_celery_queue_oldest_message_age_seconds", "{{queue}}")], "s"),
        panel("Queue wait p95", [("histogram_quantile(0.95, sum by (le, task) (rate(hrms_celery_task_queue_wait_seconds_bucket[1h])))", "{{task}}")], "s"),
        panel("Time since last success", [("time() - hrms_celery_task_last_success_timestamp_seconds", "{{task}}")], "s",
              desc="Scheduled jobs: daily jobs should stay under ~26 h."),
        panel("Publish failures (never submitted)", [("sum by (task) (increase(hrms_celery_publish_failures_total[1h]))", "{{task}}")], zero_when_empty=True),
        panel("Scheduler heartbeat age", [("hrms_celery_scheduler_heartbeat_age_seconds", "age")], "s"),
    ]),
    "hrms-d-hrms-operations": ("HRMS - D. HRMS operations", [
        panel("Attendance operations", [('sum by (operation, outcome) (increase(hrms_operations_total{operation=~"attendance\\\\..*"}[1h]))', "{{operation}} {{outcome}}")],
              desc="rejected = policy outcome (expected); failed = server-side."),
        panel("Attendance server-side failures", [('sum(increase(hrms_operations_total{operation=~"attendance\\\\..*",outcome="failed"}[15m]))', "failed")], zero_when_empty=True),
        panel("Punch latency p95", [('histogram_quantile(0.95, sum by (le) (rate(hrms_operation_duration_seconds_bucket{operation=~"attendance\\\\.(punch|face)\\\\..*"}[15m])))', "p95")], "s"),
        panel("Leave operations", [('sum by (operation, outcome) (increase(hrms_operations_total{operation=~"leave\\\\..*"}[1h]))', "{{operation}} {{outcome}}")]),
        panel("Leave accrual/expiry runs", [('sum by (operation, outcome) (increase(hrms_operations_total{operation=~"leave\\\\.(accrual|comp_off|year_end)\\\\..*"}[24h]))', "{{operation}} {{outcome}}")]),
        panel("Payroll operations", [('sum by (operation, outcome) (increase(hrms_operations_total{operation=~"payroll\\\\..*"}[24h]))', "{{operation}} {{outcome}}")]),
        panel("Payroll compute duration p95", [('histogram_quantile(0.95, sum by (le) (rate(hrms_operation_duration_seconds_bucket{operation="payroll.pay_run.compute"}[24h])))', "p95")], "s"),
        panel("Committed audited transitions", [("topk(10, sum by (entity_type) (increase(hrms_committed_events_total[1h])))", "{{entity_type}}")]),
        panel("Employee-import tasks", [('sum by (state) (increase(hrms_celery_tasks_finished_total{task=~"employee_import\\\\..*"}[24h]))', "{{state}}")]),
        panel("Email / face provider errors", [("sum by (dependency, category) (increase(hrms_dependency_errors_total[1h]))", "{{dependency}}/{{category}}")], zero_when_empty=True),
        panel("Login failures / lockouts", [('sum by (event) (increase(hrms_security_events_total{event=~"login.failed|platform.login.failed|account.locked|rate_limited"}[1h]))', "{{event}}")], zero_when_empty=True),
    ]),
}


def build(title, panels):
    out = []
    for i, p in enumerate(panels):
        stat = p["type"] == "stat"
        w, h = (6, 4) if stat else (12, 8)
        out.append({**p, "id": i + 1, "gridPos": {"x": (i * w) % 24, "y": (i // (24 // w)) * h, "w": w, "h": h}})
    return {
        "title": title, "uid": None,
        "schemaVersion": 39, "version": 1, "refresh": "30s", "time": {"from": "now-6h", "to": "now"},
        "templating": {"list": [{"name": "DS_PROMETHEUS", "type": "datasource", "query": "prometheus"}]},
        "panels": out, "tags": ["hrms"],
    }


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for uid, (title, panels) in DASHBOARDS.items():
        doc = build(title, panels)
        doc["uid"] = uid
        (OUT / f"{uid}.json").write_text(json.dumps(doc, indent=2) + "\n")
        print("wrote", uid, len(panels), "panels")
