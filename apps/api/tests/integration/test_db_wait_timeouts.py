"""`bounded_waits`: real PostgreSQL lock and statement timeouts, scoped to the guarded block, with
a usable connection afterwards."""

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from hrms.core.db.session import get_session_factory
from hrms.core.db.timeouts import bounded_waits, is_wait_timeout

pytestmark = pytest.mark.asyncio


async def _show(session, name: str) -> str:
    return str((await session.execute(text(f"SHOW {name}"))).scalar_one())


async def test_statement_timeout_is_controlled_scoped_and_leaves_the_connection_usable() -> None:
    async with get_session_factory()() as session:
        before = await _show(session, "statement_timeout")
        with pytest.raises(DBAPIError) as raised:
            async with session.begin_nested():
                async with bounded_waits(session, lock_timeout_ms=5000, statement_timeout_ms=150):
                    await session.execute(text("SELECT pg_sleep(2)"))
        assert is_wait_timeout(raised.value)
        # the savepoint rollback reverted the setting and the transaction still works
        assert await _show(session, "statement_timeout") == before
        assert (await session.execute(text("SELECT 1"))).scalar_one() == 1


async def test_lock_timeout_is_controlled_and_does_not_wait_the_full_hold() -> None:
    factory = get_session_factory()
    holding = asyncio.Event()
    release = asyncio.Event()

    async def holder() -> None:
        async with factory() as session:
            await session.execute(text("SELECT pg_advisory_xact_lock(918273)"))
            holding.set()
            await release.wait()
            await session.rollback()

    task = asyncio.create_task(holder())
    await holding.wait()
    try:
        async with factory() as session:
            loop = asyncio.get_running_loop()
            started = loop.time()
            with pytest.raises(DBAPIError) as raised:
                async with session.begin_nested():
                    async with bounded_waits(
                        session, lock_timeout_ms=200, statement_timeout_ms=30000
                    ):
                        await session.execute(text("SELECT pg_advisory_xact_lock(918273)"))
            waited = loop.time() - started
            assert is_wait_timeout(raised.value)
            assert 0.15 < waited < 2.0
            assert (await session.execute(text("SELECT 1"))).scalar_one() == 1
    finally:
        release.set()
        await task


async def test_settings_are_restored_after_a_successful_block() -> None:
    async with get_session_factory()() as session:
        lock_before = await _show(session, "lock_timeout")
        statement_before = await _show(session, "statement_timeout")
        async with bounded_waits(session, lock_timeout_ms=1234, statement_timeout_ms=5678):
            assert await _show(session, "lock_timeout") == "1234ms"
            assert await _show(session, "statement_timeout") == "5678ms"
        assert await _show(session, "lock_timeout") == lock_before
        assert await _show(session, "statement_timeout") == statement_before


async def test_other_database_errors_are_not_mistaken_for_timeouts() -> None:
    async with get_session_factory()() as session:
        with pytest.raises(DBAPIError) as raised:
            await session.execute(text("SELECT 1/0"))
        assert not is_wait_timeout(raised.value)
