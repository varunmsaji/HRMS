"""Background-job health check for operators and the host monitor (mission Phases 7 and 10).

    docker compose -f docker-compose.prod.yml exec -T worker python -m hrms.ops.job_health

Prints one JSON document and exits 0 when every check passes, 1 when any check fails, and 2 when
the check itself could not run (Redis unreachable). It is strictly **read-only**: `LLEN` and
`LINDEX` never consume, move, or delete a message, so it is safe to run against a queue that
holds a backlog awaiting reconciliation (see the execution report, decision D-B).

Checks (thresholds are provisional until a production baseline exists; override by env):

* `scheduler_heartbeat` — age of the last `health.scheduler_heartbeat` run. Stale means Beat is
  not scheduling, the broker is not delivering, or no worker is consuming.
  `HRMS_HEARTBEAT_MAX_AGE_SECONDS` (default 300).
* `queue_depth:<queue>` — messages waiting. `HRMS_QUEUE_MAX_DEPTH` (default 100).
* `queue_oldest_age:<queue>` — age of the oldest waiting message, from the `hrms_enqueued_at`
  header the publisher adds. Messages published before that header existed report `null` age
  and are counted under `unknown_age`. `HRMS_QUEUE_MAX_AGE_SECONDS` (default 600).
"""

import json
import os
import sys
import time
from datetime import datetime
from typing import Any, Protocol, cast

import redis

from hrms.core.celery_app import ENQUEUED_AT_HEADER, SCHEDULER_HEARTBEAT_KEY, celery_app
from hrms.core.config.settings import get_settings


class _SyncRedis(Protocol):
    """The three read-only commands used here (redis-py's own stubs union every return type
    with `Awaitable`)."""

    def get(self, name: str) -> bytes | None: ...
    def llen(self, name: str) -> int: ...
    def lindex(self, name: str, index: int) -> bytes | None: ...


def _threshold(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _queue_names() -> list[str]:
    return sorted(q.name for q in (celery_app.conf.task_queues or ()))


def _oldest_age(client: _SyncRedis, queue: str, now: float) -> float | None:
    # kombu's Redis transport LPUSHes and BRPOPs, so the oldest message is the last element.
    raw = client.lindex(queue, -1)
    if raw is None:
        return None
    try:
        headers = json.loads(raw).get("headers") or {}
        enqueued = float(headers[ENQUEUED_AT_HEADER])
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    return round(max(0.0, now - enqueued), 1)


def collect(
    *,
    app_client: _SyncRedis,
    broker_client: _SyncRedis,
    now: float | None = None,
) -> dict[str, Any]:
    now = time.time() if now is None else now
    max_heartbeat = _threshold("HRMS_HEARTBEAT_MAX_AGE_SECONDS", 300)
    max_depth = _threshold("HRMS_QUEUE_MAX_DEPTH", 100)
    max_age = _threshold("HRMS_QUEUE_MAX_AGE_SECONDS", 600)
    checks: list[dict[str, Any]] = []

    raw_beat = app_client.get(SCHEDULER_HEARTBEAT_KEY)
    beat_age: float | None = None
    if raw_beat is not None:
        beat_age = round(now - datetime.fromisoformat(raw_beat.decode()).timestamp(), 1)
    checks.append({
        "name": "scheduler_heartbeat",
        "ok": beat_age is not None and beat_age <= max_heartbeat,
        "value": beat_age,
        "threshold": max_heartbeat,
    })  # fmt: skip

    queues: dict[str, Any] = {}
    for queue in _queue_names():
        depth = int(broker_client.llen(queue))
        oldest = _oldest_age(broker_client, queue, now) if depth else None
        queues[queue] = {
            "depth": depth,
            "oldest_age_seconds": oldest,
            "unknown_age": depth > 0 and oldest is None,
        }
        checks.append(
            {"name": f"queue_depth:{queue}", "ok": depth <= max_depth, "value": depth,
             "threshold": max_depth}
        )  # fmt: skip
        checks.append(
            {"name": f"queue_oldest_age:{queue}", "ok": oldest is None or oldest <= max_age,
             "value": oldest, "threshold": max_age}
        )  # fmt: skip

    return {
        "ok": all(c["ok"] for c in checks),
        "checked_at": datetime.fromtimestamp(now).astimezone().isoformat(),
        "checks": checks,
        "queues": queues,
    }


def main() -> int:
    settings = get_settings()
    app_client = redis.Redis.from_url(settings.redis_url, socket_timeout=5)
    broker_client = redis.Redis.from_url(settings.celery_broker, socket_timeout=5)
    try:
        report = collect(
            app_client=cast(_SyncRedis, app_client), broker_client=cast(_SyncRedis, broker_client)
        )
    except (redis.RedisError, OSError) as exc:
        print(json.dumps({"ok": False, "error": "redis_unavailable", "type": type(exc).__name__}))
        return 2
    finally:
        app_client.close()
        broker_client.close()
    print(json.dumps(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
