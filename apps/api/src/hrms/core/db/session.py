import asyncio
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from hrms.core.config.settings import Settings, get_settings
from hrms.core.db.post_commit import run_post_commit
from hrms.core.observability.db_metrics import instrument_engine
from hrms.core.observability.logging import get_logger, safe_error, safe_log
from hrms.core.tenancy.context import current_tenant_company_id

_engine: AsyncEngine | None = None
_logger = get_logger(__name__)
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine(settings: Settings | None = None) -> AsyncEngine:
    global _engine
    if _engine is None:
        cfg = settings or get_settings()
        _engine = create_async_engine(
            cfg.database_url,
            pool_pre_ping=True,
            echo=cfg.is_development and cfg.log_level == "DEBUG",
            # LOG-02/LOG-08 — keeps bound values (names, emails, ciphertext, salary figures) out
            # of every `DBAPIError` message, and therefore out of the tracebacks the error
            # handlers and task-failure logs now record. The SQL text itself is still shown.
            hide_parameters=True,
        )
        instrument_engine(_engine)
    return _engine


def get_session_factory(settings: Settings | None = None) -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(settings),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


async def set_rls_company_id(session: AsyncSession, company_id: str | None) -> None:
    """Apply tenant RLS variable for the current transaction (Document 03 §2.1)."""
    if company_id is None:
        return
    await session.execute(
        text("SELECT set_config('app.company_id', :company_id, true)"),
        {"company_id": company_id},
    )


@asynccontextmanager
async def session_scope(
    settings: Settings | None = None,
    *,
    company_id: str | None = None,
) -> AsyncIterator[AsyncSession]:
    factory = get_session_factory(settings)
    async with factory() as session:
        tenant_id = company_id or current_tenant_company_id()
        if tenant_id:
            await set_rls_company_id(session, tenant_id)
        try:
            yield session
            await session.commit()
        except Exception:
            await _rollback_preserving_cause(session)
            raise
        # After the commit has returned (outside the try: a failure here must not roll back, or
        # report as failed, a transaction that is already durable) - see `core/db/post_commit.py`.
        await run_post_commit(session)


async def _rollback_preserving_cause(session: AsyncSession) -> None:
    """Rolls back after a failure without letting a *second* failure replace the first. When the
    connection itself is gone, `rollback()` raises too; before this, that rollback error
    propagated instead of the original one, so the handlers and logs described the symptom
    (`rollback on a closed connection`) rather than the cause. The original exception is
    re-raised by the caller; the rollback failure is recorded once here. The connection is
    invalidated by SQLAlchemy and never returned to the pool in a half-open transaction."""
    try:
        await session.rollback()
    except Exception as rollback_exc:  # noqa: BLE001 — the original exception wins, see above
        safe_log(_logger.warning, "db_rollback_failed", **safe_error(rollback_exc))


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency — yields a request-scoped session with tenant RLS applied."""
    factory = get_session_factory()
    async with factory() as session:
        tenant_id = current_tenant_company_id()
        if tenant_id:
            await set_rls_company_id(session, tenant_id)
        try:
            yield session
            await session.commit()
        except Exception:
            await _rollback_preserving_cause(session)
            raise
        # After the commit has returned (outside the try: a failure here must not roll back, or
        # report as failed, a transaction that is already durable) - see `core/db/post_commit.py`.
        await run_post_commit(session)


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None


def run_task[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run an async task body from a synchronous Celery task.

    Each Celery task body runs under its own `asyncio.run()` loop, but the engine (and its
    asyncpg pool) is process-global. Without this, a pooled connection created under one task's
    loop is reused under the next task's loop in the same worker process and fails with
    "attached to a different loop" / "Event loop is closed" - intermittently, depending on which
    task ran before it. Disposing the engine inside the task's own loop, before that loop closes,
    makes every task start with a fresh pool.
    """

    async def _runner() -> T:
        try:
            return await coro
        finally:
            await dispose_engine()

    return asyncio.run(_runner())
