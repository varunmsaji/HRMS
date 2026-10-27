"""Prometheus-format metrics (docs/architecture/OBSERVABILITY_ARCHITECTURE.md).

Design rules, each enforced by `tests/unit/core/test_metrics.py`:

* **Low cardinality only.** Every label value comes from a closed vocabulary: an HTTP method, a
  route *template* (unmatched requests collapse to `unmatched`), a status *class*, a Celery task
  name, a `@logged_operation` name, an `error_category`, a `security.*` event name. Never a
  company/employee/user/request id, an email, a raw path, or exception text. `MetricLabels` below
  is the single list of allowed label names; the test fails on any other.
* **Multi-process safe.** The API runs several gunicorn workers and Celery runs prefork children
  in other containers. When `PROMETHEUS_MULTIPROC_DIR` is set (a volume shared by api, worker and
  beat) every counter/histogram is an mmap-backed value in that directory and `/metrics`
  aggregates all files. Files are named `<hostname>-<pid>` so two containers whose processes have
  the same pid never collide. Without the variable (tests, single-process dev) the default
  in-process registry is used.
* **Counters and histograms only in the shared registry.** Point-in-time facts (pool, Redis, queue
  depth, heartbeat age, log-disk space) are produced by `ScrapeCollector` at scrape time, so a
  dead worker can never leave a stale gauge behind.
* **Never an availability risk.** Recording helpers swallow every exception: a metrics failure
  must not change a response or a task result.
"""

from __future__ import annotations

import os
import socket
from typing import Any, Final

from prometheus_client import REGISTRY, CollectorRegistry, Counter, Gauge, Histogram, values
from prometheus_client.multiprocess import MultiProcessCollector

MULTIPROC_ENV: Final = "PROMETHEUS_MULTIPROC_DIR"


def multiprocess_dir() -> str | None:
    raw = os.environ.get(MULTIPROC_ENV)
    return raw or None


if multiprocess_dir() is not None:
    # Must happen before any metric below is constructed. Hostname-qualified ids keep files from
    # different containers apart; `values.MultiProcessValue` reads PROMETHEUS_MULTIPROC_DIR itself.
    values.ValueClass = values.MultiProcessValue(  # type: ignore[no-untyped-call]
        lambda: f"{socket.gethostname()}-{os.getpid()}"
    )

#: Every label name any metric in this module may use. Adding one is a deliberate act: it must be
#: bounded, and non-identifying.
ALLOWED_LABELS: Final = frozenset(
    {
        "method",
        "route",
        "status_class",
        "code",
        "category",
        "source",
        "operation",
        "outcome",
        "task",
        "state",
        "event",
        "entity_type",
        "level",
        "limiter",
        "dependency",
        "queue",
    }
)

#: Latency buckets (seconds). The API's interactive endpoints are expected well under a second; the
#: top buckets exist to show payroll/import work and the 60 s gunicorn timeout. Provisional until a
#: baseline exists (docs/architecture/OBSERVABILITY_ARCHITECTURE.md §6).
HTTP_BUCKETS: Final = (0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)
DB_BUCKETS: Final = (0.001, 0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 5.0)
#: Task durations run from sub-second sweeps to the 1800 s hard limit of per-company runs.
TASK_BUCKETS: Final = (0.1, 0.5, 1.0, 5.0, 15.0, 60.0, 300.0, 900.0, 1800.0)
#: Queue wait: the heartbeat runs every 60 s, so seconds-to-minutes is the meaningful range.
WAIT_BUCKETS: Final = (0.1, 0.5, 1.0, 5.0, 15.0, 60.0, 300.0, 900.0)

HTTP_REQUESTS = Counter(
    "hrms_http_requests_total",
    "HTTP requests by route template and status class.",
    ["method", "route", "status_class"],
)
HTTP_DURATION = Histogram(
    "hrms_http_request_duration_seconds",
    "HTTP request duration by route template.",
    ["route"],
    buckets=HTTP_BUCKETS,
)
HTTP_DENIALS = Counter(
    "hrms_http_denials_total",
    "Responses that deny access: 401, 403, 429 (rate limited).",
    ["code"],
)
HTTP_UNHANDLED = Counter(
    "hrms_http_unhandled_exceptions_total",
    "Exceptions that escaped the whole stack and produced the generic 500.",
    ["category"],
)
ERRORS = Counter(
    "hrms_errors_total",
    "Failures by origin and stable error_category (core/observability/classification.py).",
    ["source", "category"],
)
OPERATIONS = Counter(
    "hrms_operations_total",
    "Service operations (@logged_operation). `succeeded` means the method returned, NOT that the "
    "transaction committed - see hrms_committed_events_total.",
    ["operation", "outcome"],
)
OPERATION_DURATION = Histogram(
    "hrms_operation_duration_seconds",
    "Service operation duration.",
    ["operation"],
    buckets=TASK_BUCKETS,
)
COMMITTED_EVENTS = Counter(
    "hrms_committed_events_total",
    "Audited business transitions, counted only after their transaction really committed.",
    ["event", "entity_type"],
)
SECURITY_EVENTS = Counter(
    "hrms_security_events_total",
    "security.* events (login failures, lockouts, rate limits, token rejections).",
    ["event", "level"],
)
LOG_EVENTS = Counter(
    "hrms_log_events_total",
    "Structured log events by level (an error-rate signal that needs no log parsing).",
    ["level"],
)
LOG_DROPPED = Counter(
    "hrms_log_dropped_writes_total",
    "Log lines lost because a sink (stdout or a log file) was unwritable.",
    ["source"],
)
DB_QUERY_DURATION = Histogram(
    "hrms_db_query_duration_seconds",
    "Statement execution time. No SQL text and no parameters are recorded.",
    buckets=DB_BUCKETS,
)
DB_ROLLBACKS = Counter("hrms_db_rollbacks_total", "Connection-level transaction rollbacks.")
DB_CONNECTS = Counter("hrms_db_connects_total", "New physical database connections opened.")
DEPENDENCY_ERRORS = Counter(
    "hrms_dependency_errors_total",
    "Failed calls to an external dependency (email, storage, face provider...).",
    ["dependency", "category"],
)
DEPENDENCY_CALLS = Counter(
    "hrms_dependency_calls_total",
    "Calls to an external dependency by outcome (success / failure) - the denominator for "
    "hrms_dependency_errors_total.",
    ["dependency", "outcome"],
)
DEPENDENCY_DURATION = Histogram(
    "hrms_dependency_call_duration_seconds",
    "External dependency round-trip time (provider call only; no payloads).",
    ["dependency"],
    buckets=HTTP_BUCKETS,
)
CELERY_PUBLISHED = Counter(
    "hrms_celery_tasks_published_total",
    "Tasks handed to the broker (by the API, a task, or Beat).",
    ["task"],
)
CELERY_PUBLISH_FAILURES = Counter(
    "hrms_celery_publish_failures_total",
    "Tasks that could not be handed to the broker (never submitted).",
    ["task"],
)
CELERY_STARTED = Counter("hrms_celery_tasks_started_total", "Tasks a worker began.", ["task"])
CELERY_FINISHED = Counter(
    "hrms_celery_tasks_finished_total",
    "Task runs by final Celery state (SUCCESS, FAILURE, RETRY, ...).",
    ["task", "state"],
)
CELERY_RETRIES = Counter("hrms_celery_task_retries_total", "Scheduled retries.", ["task"])
CELERY_FAILURES = Counter(
    "hrms_celery_task_failures_total", "Tasks that failed for good.", ["task", "category"]
)
CELERY_UNKNOWN = Counter(
    "hrms_celery_messages_unroutable_total",
    "Messages a worker discarded: unknown task name or rejected content.",
    ["state"],
)
CELERY_DURATION = Histogram(
    "hrms_celery_task_duration_seconds", "Task run time.", ["task"], buckets=TASK_BUCKETS
)
CELERY_QUEUE_WAIT = Histogram(
    "hrms_celery_task_queue_wait_seconds",
    "Time between publish and start (needs the hrms_enqueued_at header).",
    ["task"],
    buckets=WAIT_BUCKETS,
)
#: Non-live gauge mode: a dead worker's last value is kept, which is exactly right for "when did
#: this task last succeed" (the maximum across processes).
CELERY_LAST_SUCCESS = Gauge(
    "hrms_celery_task_last_success_timestamp_seconds",
    "Unix time of the last successful run.",
    ["task"],
    multiprocess_mode="max",
)

ALL_METRICS: tuple[Any, ...] = (
    HTTP_REQUESTS,
    HTTP_DURATION,
    HTTP_DENIALS,
    HTTP_UNHANDLED,
    ERRORS,
    OPERATIONS,
    OPERATION_DURATION,
    COMMITTED_EVENTS,
    SECURITY_EVENTS,
    LOG_EVENTS,
    LOG_DROPPED,
    DB_QUERY_DURATION,
    DB_ROLLBACKS,
    DB_CONNECTS,
    DEPENDENCY_ERRORS,
    DEPENDENCY_CALLS,
    DEPENDENCY_DURATION,
    CELERY_PUBLISHED,
    CELERY_PUBLISH_FAILURES,
    CELERY_STARTED,
    CELERY_FINISHED,
    CELERY_RETRIES,
    CELERY_FAILURES,
    CELERY_UNKNOWN,
    CELERY_DURATION,
    CELERY_QUEUE_WAIT,
    CELERY_LAST_SUCCESS,
)

_STATUS_CLASSES: Final = {1: "1xx", 2: "2xx", 3: "3xx", 4: "4xx", 5: "5xx"}
_DENIAL_CODES: Final = frozenset({401, 403, 429})
_METHODS: Final = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})


def status_class(status: int) -> str:
    return _STATUS_CLASSES.get(status // 100, "other")


def record_http(method: str | None, route: str, status: int, duration_seconds: float) -> None:
    """One finished HTTP request. `route` must already be a template or `unmatched`."""
    try:
        verb = method if method in _METHODS else "OTHER"
        HTTP_REQUESTS.labels(verb, route, status_class(status)).inc()
        HTTP_DURATION.labels(route).observe(duration_seconds)
        if status in _DENIAL_CODES:
            HTTP_DENIALS.labels(str(status)).inc()
    except Exception:  # noqa: BLE001 — metrics must never break a request
        pass


def safe_count(counter: Any, *labels: str, amount: float = 1) -> None:
    """Increment `counter` (labelled by `labels`) and swallow any failure."""
    try:
        (counter.labels(*labels) if labels else counter).inc(amount)
    except Exception:  # noqa: BLE001
        pass


def safe_observe(histogram: Any, value: float, *labels: str) -> None:
    try:
        (histogram.labels(*labels) if labels else histogram).observe(value)
    except Exception:  # noqa: BLE001
        pass


def build_registry() -> CollectorRegistry:
    """The registry one scrape renders. Multiprocess mode must build a fresh registry per scrape
    (prometheus_client requirement) that aggregates every process's files; otherwise the default
    in-process registry already holds the metrics above (plus the standard process collectors)."""
    if multiprocess_dir() is None:
        return REGISTRY
    registry = CollectorRegistry()
    MultiProcessCollector(registry)  # type: ignore[no-untyped-call]
    return registry
