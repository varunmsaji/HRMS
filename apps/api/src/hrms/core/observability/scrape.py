"""Point-in-time metrics, computed when `/metrics` is scraped.

Facts like "is Redis answering", "how deep is the queue" or "how old is the scheduler heartbeat"
are measured here rather than stored, so a crashed process can never leave a stale value behind
and nothing runs between scrapes (no background thread, no per-request cost).

Every probe has a hard timeout, failures become `up 0` (never an exception), and the whole result
is cached for `CACHE_SECONDS` so a misconfigured scraper cannot turn `/metrics` into a load
generator against Postgres or Redis. Probes read only: `SELECT 1`, Redis `PING`/`INFO`, and the
read-only `LLEN`/`LINDEX` of `hrms.ops.job_health`. No queue message is ever consumed.

Known limit, stated honestly: the connection-pool gauges describe the process that served the
scrape (gunicorn workers each own a pool), not the sum over workers. Pool *exhaustion* is counted
exactly in `hrms_errors_total{category="db_pool_exhausted"}`.
"""

from __future__ import annotations

import asyncio
import shutil
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Final

from prometheus_client import CollectorRegistry, generate_latest
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.metrics_core import Metric

from hrms.core.config.settings import get_settings
from hrms.core.observability.db_metrics import pool_snapshot
from hrms.core.observability.logging import dropped_log_writes, resolve_log_dir
from hrms.core.observability.metrics import build_registry, multiprocess_dir

CACHE_SECONDS: Final = 10.0
PROBE_TIMEOUT_SECONDS: Final = 2.0

_cache: tuple[float, list[Metric]] | None = None


class _Static:
    def __init__(self, families: Iterable[Metric]) -> None:
        self._families = list(families)

    def collect(self) -> Iterable[Metric]:
        return self._families

    def describe(self) -> Iterable[Metric]:
        return []


def _gauge(name: str, doc: str, value: float, labels: dict[str, str] | None = None) -> Metric:
    family = GaugeMetricFamily(name, doc, labels=list(labels or {}))
    family.add_metric(list((labels or {}).values()), value)
    return family


async def _probe_database() -> tuple[float | None, dict[str, int] | None]:
    from sqlalchemy import text

    from hrms.core.db.session import get_engine

    engine = get_engine()
    started = time.perf_counter()
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 — a failing probe is the metric, not an error
        return None, pool_snapshot(engine)
    return time.perf_counter() - started, pool_snapshot(engine)


def _probe_redis_sync(url: str) -> tuple[float, dict[str, Any]] | None:
    import redis

    client = redis.Redis.from_url(
        url, socket_timeout=PROBE_TIMEOUT_SECONDS, socket_connect_timeout=PROBE_TIMEOUT_SECONDS
    )
    try:
        started = time.perf_counter()
        client.ping()
        latency = time.perf_counter() - started
        info: dict[str, Any] = {**client.info("memory"), **client.info("clients")}  # type: ignore[dict-item]
        info.update(client.info("stats"))  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        return None
    else:
        return latency, info
    finally:
        client.close()


def _probe_jobs_sync() -> dict[str, Any] | None:
    import redis

    from hrms.ops.job_health import collect

    settings = get_settings()
    app_client = redis.Redis.from_url(settings.redis_url, socket_timeout=PROBE_TIMEOUT_SECONDS)
    broker_client = redis.Redis.from_url(
        settings.celery_broker, socket_timeout=PROBE_TIMEOUT_SECONDS
    )
    try:
        return collect(app_client=app_client, broker_client=broker_client)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        return None
    finally:
        app_client.close()
        broker_client.close()


def _directory_bytes(path: Path) -> int:
    total = 0
    try:
        for entry in path.iterdir():
            if entry.is_file():
                total += entry.stat().st_size
    except OSError:
        return 0
    return total


def _storage_families() -> list[Metric]:
    settings = get_settings()
    families: list[Metric] = []
    log_dir = resolve_log_dir(settings.log_dir)
    try:
        usage = shutil.disk_usage(log_dir if log_dir.exists() else log_dir.anchor or "/")
        families.append(
            _gauge("hrms_log_filesystem_free_ratio", "Free fraction of the log volume.",
                   usage.free / usage.total if usage.total else 0.0)
        )  # fmt: skip
    except OSError:
        pass
    families.append(
        _gauge("hrms_log_directory_bytes", "Bytes used by files in LOG_DIR.",
               _directory_bytes(log_dir))
    )  # fmt: skip
    mp_dir = multiprocess_dir()
    if mp_dir:
        families.append(
            _gauge("hrms_metrics_directory_bytes", "Bytes used by PROMETHEUS_MULTIPROC_DIR.",
                   _directory_bytes(Path(mp_dir)))
        )  # fmt: skip
    families.append(
        _gauge("hrms_log_stdout_dropped_writes", "Stdout log lines lost in this process.",
               dropped_log_writes())
    )  # fmt: skip
    return families


async def _gather() -> list[Metric]:
    settings = get_settings()
    db_task = asyncio.create_task(_probe_database())
    redis_app = asyncio.to_thread(_probe_redis_sync, settings.redis_url)
    jobs = asyncio.to_thread(_probe_jobs_sync)
    (db_latency, pool), redis_result, job_report = await asyncio.gather(db_task, redis_app, jobs)

    up = GaugeMetricFamily("hrms_dependency_up", "1 if the probe succeeded.", labels=["dependency"])
    latency = GaugeMetricFamily(
        "hrms_dependency_probe_seconds", "Probe round-trip time.", labels=["dependency"]
    )
    up.add_metric(["database"], 1 if db_latency is not None else 0)
    up.add_metric(["redis"], 1 if redis_result is not None else 0)
    if db_latency is not None:
        latency.add_metric(["database"], db_latency)
    if redis_result is not None:
        latency.add_metric(["redis"], redis_result[0])
    families: list[Metric] = [up, latency]

    if pool is not None:
        for key, doc in (
            ("size", "Configured base pool size."),
            ("checked_out", "Connections currently checked out."),
            ("overflow", "Overflow connections in use."),
            ("capacity", "Base size plus max overflow."),
        ):
            families.append(
                _gauge(f"hrms_db_pool_{key}", f"{doc} (serving process only)", pool[key])
            )

    if redis_result is not None:
        info = redis_result[1]
        for name, key, doc in (
            ("hrms_redis_memory_used_bytes", "used_memory", "Redis memory in use."),
            ("hrms_redis_memory_max_bytes", "maxmemory", "Redis maxmemory (0 = unlimited)."),
            ("hrms_redis_connected_clients", "connected_clients", "Connected clients."),
            ("hrms_redis_evicted_keys", "evicted_keys", "Keys evicted since Redis start."),
            ("hrms_redis_rejected_connections", "rejected_connections", "Rejected connections."),
        ):
            value = info.get(key)
            if isinstance(value, (int, float)):
                families.append(_gauge(name, doc, float(value)))

    jobs_up = 1 if job_report is not None else 0
    families.append(
        _gauge("hrms_jobs_probe_up", "1 if the queue/heartbeat probe could read Redis.", jobs_up)
    )
    if job_report is not None:
        depth = GaugeMetricFamily("hrms_celery_queue_depth", "Messages waiting.", labels=["queue"])
        age = GaugeMetricFamily(
            "hrms_celery_queue_oldest_message_age_seconds",
            "Age of the oldest waiting message (absent when unknown).",
            labels=["queue"],
        )
        for queue, row in job_report["queues"].items():
            depth.add_metric([queue], row["depth"])
            if row["oldest_age_seconds"] is not None:
                age.add_metric([queue], row["oldest_age_seconds"])
        families.extend([depth, age])
        for check in job_report["checks"]:
            if check["name"] == "scheduler_heartbeat":
                # Absent (not 0) before the first heartbeat ever ran, so "never ran" and "ran
                # just now" cannot be confused; the alert uses absent() for the former.
                if check["value"] is not None:
                    families.append(
                        _gauge("hrms_celery_scheduler_heartbeat_age_seconds",
                               "Age of the last health.scheduler_heartbeat run.", check["value"])
                    )  # fmt: skip
    families.extend(_storage_families())
    families.append(
        _gauge("hrms_build_info", "Build/runtime identity.", 1,
               {"environment": settings.environment})
    )  # fmt: skip
    return families


async def render_metrics() -> bytes:
    """The full exposition: shared counters/histograms (all processes) + scrape-time gauges."""
    global _cache
    now = time.monotonic()
    if _cache is None or now - _cache[0] > CACHE_SECONDS:
        try:
            _cache = (now, await _gather())
        except Exception:  # noqa: BLE001 — still serve the counters
            _cache = (now, [])
    body = generate_latest(build_registry())
    if _cache[1]:
        scratch = CollectorRegistry()
        scratch.register(_Static(_cache[1]))
        body += generate_latest(scratch)
    return body


def reset_cache() -> None:
    """Test hook."""
    global _cache
    _cache = None
