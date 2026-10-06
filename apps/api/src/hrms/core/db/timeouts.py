"""Bounded lock and statement waits for individual operations.

PostgreSQL's `lock_timeout` and `statement_timeout` are set with `SET LOCAL`, so they apply only to
the current transaction and are reset to what they were when the guarded block finishes normally.
When the block fails, the surrounding savepoint (or transaction) rolls back and the settings revert
with it. Nothing here changes the database-wide or role-wide configuration.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

#: SQLSTATE 55P03 lock_not_available (`lock_timeout`), 57014 query_canceled (`statement_timeout`).
_WAIT_TIMEOUT_SQLSTATES = {"55P03", "57014"}
_WAIT_TIMEOUT_DRIVER_ERRORS = {"LockNotAvailableError", "QueryCanceledError"}


def is_wait_timeout(exc: BaseException) -> bool:
    """True when `exc` is a database lock or statement timeout (not any other DB failure)."""
    if not isinstance(exc, DBAPIError):
        return False
    cause = getattr(exc.orig, "__cause__", None) or exc.orig
    if type(cause).__name__ in _WAIT_TIMEOUT_DRIVER_ERRORS:
        return True
    return str(getattr(cause, "sqlstate", None) or "") in _WAIT_TIMEOUT_SQLSTATES


async def _current(session: AsyncSession, name: str) -> str:
    return str((await session.execute(text(f"SHOW {name}"))).scalar_one())


@asynccontextmanager
async def bounded_waits(
    session: AsyncSession, *, lock_timeout_ms: int, statement_timeout_ms: int
) -> AsyncIterator[None]:
    """Applies the two timeouts to the current transaction for the duration of the block."""
    previous_lock = await _current(session, "lock_timeout")
    previous_statement = await _current(session, "statement_timeout")
    await session.execute(
        text("SELECT set_config('lock_timeout', :v, true)"), {"v": f"{lock_timeout_ms}ms"}
    )
    await session.execute(
        text("SELECT set_config('statement_timeout', :v, true)"),
        {"v": f"{statement_timeout_ms}ms"},
    )
    yield
    # Only reached when the block succeeded; on failure the savepoint/transaction rollback above
    # this frame has already reverted both settings.
    await session.execute(text("SELECT set_config('lock_timeout', :v, true)"), {"v": previous_lock})
    await session.execute(
        text("SELECT set_config('statement_timeout', :v, true)"), {"v": previous_statement}
    )


@asynccontextmanager
async def bounded_lock_wait(session: AsyncSession, *, lock_timeout_ms: int) -> AsyncIterator[None]:
    """Like `bounded_waits` but for the lock wait alone: used around one blocking advisory-lock
    call so it fails with a retryable lock timeout instead of queuing indefinitely, while leaving
    the surrounding statement timeout (whatever it is) untouched."""
    previous_lock = await _current(session, "lock_timeout")
    await session.execute(
        text("SELECT set_config('lock_timeout', :v, true)"), {"v": f"{lock_timeout_ms}ms"}
    )
    yield
    await session.execute(text("SELECT set_config('lock_timeout', :v, true)"), {"v": previous_lock})
