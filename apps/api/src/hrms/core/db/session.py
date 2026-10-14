from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from hrms.core.config.settings import Settings, get_settings
from hrms.core.tenancy.context import current_tenant_company_id

_engine: AsyncEngine | None = None
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
            await session.rollback()
            raise


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
            await session.rollback()
            raise


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
