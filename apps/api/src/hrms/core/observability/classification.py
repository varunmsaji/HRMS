"""Stable failure categories for log events (mission Phase 4 / plan §E.3).

`error_category` is a small, fixed vocabulary an alert rule can key on without parsing exception
text or class names, and it is safe to log (never derived from a message). It classifies the
*cause* of a failure; it does not decide the HTTP response — the handlers do, and they only treat
a failure as retryable when Postgres guarantees nothing was committed.

| category                | meaning                                                         |
|-------------------------|-----------------------------------------------------------------|
| `db_timeout`            | lock_timeout / statement_timeout (55P03, 57014)                 |
| `db_pool_exhausted`     | no pooled connection became free within `pool_timeout`         |
| `db_deadlock`           | 40P01 — Postgres aborted one transaction to break a cycle      |
| `db_serialization`      | 40001 — serializable/repeatable-read conflict                  |
| `db_connection`         | SQLSTATE class 08, or the driver lost the connection            |
| `db_integrity`          | SQLSTATE class 23 (unique, FK, check, not-null)                 |
| `db_invalid_input`      | SQLSTATE class 22 (value does not fit the column)               |
| `db_error`              | any other database error                                        |
| `dependency_unreachable`| socket-level failure reaching any dependency (refused, DNS)     |
| `timeout`               | a non-database operation timed out                              |
| `unexpected`            | everything else — a bug until proven otherwise                  |
"""

import asyncio
import socket

from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

_CONNECTION_DRIVER_ERRORS = {
    "ConnectionDoesNotExistError",
    "ConnectionFailureError",
    "CannotConnectNowError",
    "AdminShutdownError",
}

#: Transient conflicts after which Postgres has rolled the whole transaction back, so retrying
#: the request cannot double-apply anything.
RETRYABLE_DB_CATEGORIES = frozenset({"db_pool_exhausted", "db_deadlock", "db_serialization"})


def _sqlstate(exc: DBAPIError) -> tuple[str, str]:
    cause = getattr(exc.orig, "__cause__", None) or exc.orig
    return str(getattr(cause, "sqlstate", None) or ""), type(cause).__name__


def error_category(exc: BaseException) -> str:
    if isinstance(exc, PoolTimeoutError):
        return "db_pool_exhausted"
    if isinstance(exc, DBAPIError):
        state, driver = _sqlstate(exc)
        if state in {"55P03", "57014"} or driver in {"LockNotAvailableError", "QueryCanceledError"}:
            return "db_timeout"
        if state == "40P01" or driver == "DeadlockDetectedError":
            return "db_deadlock"
        if state == "40001" or driver == "SerializationError":
            return "db_serialization"
        lost = exc.connection_invalidated or driver in _CONNECTION_DRIVER_ERRORS
        if state.startswith("08") or lost:
            return "db_connection"
        if state.startswith("23"):
            return "db_integrity"
        if state.startswith("22"):
            return "db_invalid_input"
        return "db_error"
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, socket.timeout)):
        return "timeout"
    if isinstance(exc, (ConnectionError, socket.gaierror)):
        return "dependency_unreachable"
    return "unexpected"
