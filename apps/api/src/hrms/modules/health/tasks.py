from datetime import UTC, datetime

import redis

from hrms.core.celery_app import SCHEDULER_HEARTBEAT_KEY, celery_app
from hrms.core.config.settings import get_settings


@celery_app.task(name="health.ping", soft_time_limit=10, time_limit=20)  # type: ignore[untyped-decorator]
def ping() -> str:
    return "pong"


@celery_app.task(  # type: ignore[untyped-decorator]
    name="health.scheduler_heartbeat",
    # A heartbeat that waited in the queue is stale by definition; never let a backlog of them
    # pile up behind real work, and never let one run long.
    expires=120,
    soft_time_limit=10,
    time_limit=20,
)
def scheduler_heartbeat() -> str:
    now = datetime.now(UTC).isoformat()
    client = redis.Redis.from_url(get_settings().redis_url, socket_timeout=5)
    try:
        # Kept for a day so a long outage still shows *when* the last heartbeat ran.
        client.set(SCHEDULER_HEARTBEAT_KEY, now, ex=86_400)
    finally:
        client.close()
    return now
