"""Database instrumentation against the real PostgreSQL the suite already uses: statement latency,
rollbacks, new connections, pool state, and the failure classification of an unreachable database
and an exhausted pool. Parameters and SQL text never reach a metric."""

import pytest
from prometheus_client import REGISTRY, generate_latest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from hrms.core.db.session import get_engine, session_scope
from hrms.core.observability.classification import error_category
from hrms.core.observability.db_metrics import pool_snapshot


def sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


async def test_statements_are_timed_without_recording_text_or_parameters() -> None:
    before = sample("hrms_db_query_duration_seconds_count")
    async with session_scope() as session:
        await session.execute(text("SELECT :secret"), {"secret": "salary-9999999"})
    assert sample("hrms_db_query_duration_seconds_count") > before
    assert b"salary-9999999" not in generate_latest(REGISTRY)
    assert b"SELECT" not in generate_latest(REGISTRY).replace(b"SELECT 1", b"")


async def test_a_failed_transaction_is_counted_as_a_rollback() -> None:
    before = sample("hrms_db_rollbacks_total")
    with pytest.raises(RuntimeError):
        async with session_scope() as session:
            await session.execute(text("SELECT 1"))
            raise RuntimeError("business failure after a query")
    assert sample("hrms_db_rollbacks_total") > before


async def test_pool_snapshot_reports_capacity_and_checkouts() -> None:
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
        snap = pool_snapshot(engine)
        assert snap is not None
        assert snap["checked_out"] >= 1
        assert snap["capacity"] >= snap["size"] >= 1


async def test_pool_exhaustion_and_connection_loss_have_distinct_categories() -> None:
    assert error_category(PoolTimeoutError("QueuePool limit of size 5 overflow 10 reached")) == (
        "db_pool_exhausted"
    )
    err = OperationalError("SELECT 1", {}, ConnectionRefusedError("refused"))
    assert error_category(err) in {"db_connection", "db_error", "dependency_unreachable"}
