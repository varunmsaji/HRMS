"""SQLAlchemy engine instrumentation: statement latency, rollbacks, new connections, pool state.

Only timings and counts are recorded. The statement text and its parameters are never read, so
nothing here can leak a bound value (the engine also runs with `hide_parameters=True`). Every
listener swallows its own failures - instrumentation must not touch a business transaction.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine

from hrms.core.observability.metrics import (
    DB_CONNECTS,
    DB_QUERY_DURATION,
    DB_ROLLBACKS,
    safe_count,
    safe_observe,
)

_STARTED = "hrms_query_started"


def instrument_engine(engine: AsyncEngine | Engine) -> None:
    """Idempotent: installing twice on the same engine registers the listeners once."""
    sync_engine = engine.sync_engine if isinstance(engine, AsyncEngine) else engine
    if getattr(sync_engine, "_hrms_instrumented", False):
        return
    sync_engine._hrms_instrumented = True  # type: ignore[attr-defined]

    @event.listens_for(sync_engine, "before_cursor_execute")
    def _before(
        conn: Any, _cursor: Any, _stmt: Any, _params: Any, context: Any, _many: Any
    ) -> None:
        try:
            context._hrms_started = time.perf_counter()
        except Exception:  # noqa: BLE001
            pass

    @event.listens_for(sync_engine, "after_cursor_execute")
    def _after(conn: Any, _cursor: Any, _stmt: Any, _params: Any, context: Any, _many: Any) -> None:
        started = getattr(context, "_hrms_started", None)
        if started is not None:
            safe_observe(DB_QUERY_DURATION, time.perf_counter() - started)

    @event.listens_for(sync_engine, "rollback")
    def _rollback(_conn: Any) -> None:
        safe_count(DB_ROLLBACKS)

    @event.listens_for(sync_engine.pool, "connect")
    def _connect(_dbapi: Any, _record: Any) -> None:
        safe_count(DB_CONNECTS)


def pool_snapshot(engine: AsyncEngine | Engine) -> dict[str, int] | None:
    """`size`, `checked_out`, `overflow` and `capacity` of a QueuePool; None for other pools."""
    sync_engine = engine.sync_engine if isinstance(engine, AsyncEngine) else engine
    pool = sync_engine.pool
    try:
        size, checked_out, overflow = pool.size(), pool.checkedout(), pool.overflow()  # type: ignore[attr-defined]
        max_overflow = int(pool._max_overflow)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 — not a QueuePool
        return None
    return {
        "size": int(size),
        "checked_out": int(checked_out),
        "overflow": max(0, int(overflow)),
        "capacity": int(size) + max(0, max_overflow),
    }
