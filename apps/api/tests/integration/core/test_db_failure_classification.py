"""Mission Phase 4 — database failures are classified, logged once at the right level, and only
answered as retryable (`503 DATABASE_BUSY` + `Retry-After`) when Postgres guarantees nothing was
committed. Real failures go through the real engine where that is possible (a terminated backend,
a real unique violation carrying a sentinel value); the rest are injected at the route.

Log output is read from the real stdout pipe, as in `test_request_context_and_error_logging.py`."""

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest import CaptureFixture
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from hrms.app import create_app
from hrms.core.db.session import get_session_factory, session_scope
from hrms.core.observability.classification import error_category

SENTINEL_EMAIL = "dup-sentinel-7f3a@example.com"


def _events(raw: str) -> list[dict[str, Any]]:
    out = []
    for line in raw.splitlines():
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict) and "event" in parsed:
            out.append(parsed)
    return out


def _fake_db_error(sqlstate: str) -> DBAPIError:
    class _DriverError(Exception):
        pass

    _DriverError.sqlstate = sqlstate  # type: ignore[attr-defined]
    orig = Exception("adapter")
    orig.__cause__ = _DriverError("driver detail")
    return DBAPIError("UPDATE t SET x = 1", {}, orig)


@pytest.fixture
def client() -> Iterator[TestClient]:
    app: FastAPI = create_app()

    @app.get("/__t/pool")
    async def pool() -> None:
        raise PoolTimeoutError("QueuePool limit of size 5 overflow 10 reached")

    @app.get("/__t/sqlstate/{state}")
    async def sqlstate(state: str) -> None:
        raise _fake_db_error(state)

    @app.get("/__t/terminated")
    async def terminated() -> None:
        async with session_scope() as session:
            await session.execute(text("SELECT pg_terminate_backend(pg_backend_pid())"))

    @app.get("/__t/integrity")
    async def integrity() -> None:
        async with get_session_factory()() as session:
            await session.execute(text("CREATE TEMP TABLE t_dup (email text PRIMARY KEY)"))
            for _ in range(2):
                await session.execute(text("INSERT INTO t_dup VALUES (:e)"), {"e": SENTINEL_EMAIL})

    @app.get("/__t/refused")
    async def refused() -> None:
        raise ConnectionRefusedError(111, "Connect call failed ('10.0.0.9', 5432)")

    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize(
    ("path", "event", "category"),
    [
        ("/__t/pool", "db_pool_exhausted", "db_pool_exhausted"),
        ("/__t/sqlstate/40P01", "db_deadlock", "db_deadlock"),
        ("/__t/sqlstate/40001", "db_serialization", "db_serialization"),
        ("/__t/sqlstate/55P03", "db_wait_timeout", "db_timeout"),
    ],
)
def test_retryable_failures_are_503_busy_and_one_compact_warning(
    client: TestClient, capfd: CaptureFixture[str], path: str, event: str, category: str
) -> None:
    capfd.readouterr()
    r = client.get(path)
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "DATABASE_BUSY"
    assert r.headers["retry-after"] == "2"
    events = _events(capfd.readouterr().out)
    (logged,) = [e for e in events if e["event"] == event]
    assert logged["level"] == "warning"
    assert logged["error_category"] == category
    assert "exception" not in logged  # no traceback for a transient condition
    (access,) = [e for e in events if e["event"] == "http_request"]
    assert access["error_code"] == "DATABASE_BUSY"


def test_lost_connection_is_a_500_not_an_invitation_to_retry(
    client: TestClient, capfd: CaptureFixture[str]
) -> None:
    capfd.readouterr()
    r = client.get("/__t/terminated")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "retry-after" not in r.headers
    events = _events(capfd.readouterr().out)
    (db_error,) = [e for e in events if e["event"] == "db_error"]
    assert db_error["level"] == "error"
    assert db_error["error_category"] == "db_connection"
    assert db_error["sqlstate"] and db_error["sqlstate"].startswith("08")
    # The rollback on the dead connection failed too, but the ORIGINAL error is what reached
    # the handler (above) — the rollback failure is a separate, compact record.
    rollback = [e for e in events if e["event"] == "db_rollback_failed"]
    assert len(rollback) <= 1


def test_integrity_violation_is_classified_and_its_values_never_logged(
    client: TestClient, capfd: CaptureFixture[str]
) -> None:
    capfd.readouterr()
    r = client.get("/__t/integrity")
    raw = capfd.readouterr().out
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "DUPLICATE_RESOURCE"
    assert SENTINEL_EMAIL not in raw and SENTINEL_EMAIL not in r.text
    events = _events(raw)
    (db_error,) = [e for e in events if e["event"] == "db_error"]
    assert db_error["error_category"] == "db_integrity"
    assert db_error["sqlstate"] == "23505"
    assert db_error["level"] == "warning"
    # Traceback kept for diagnosis, with the constraint's DETAIL values masked.
    assert "Traceback" in db_error["exception"]


def test_refused_dependency_connection_is_categorised(
    client: TestClient, capfd: CaptureFixture[str]
) -> None:
    capfd.readouterr()
    r = client.get("/__t/refused")
    assert r.status_code == 500
    (logged,) = [e for e in _events(capfd.readouterr().out) if e["event"] == "unhandled_exception"]
    assert logged["error_category"] == "dependency_unreachable"


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (PoolTimeoutError("pool"), "db_pool_exhausted"),
        (_fake_db_error("57014"), "db_timeout"),
        (_fake_db_error("08006"), "db_connection"),
        (_fake_db_error("23503"), "db_integrity"),
        (_fake_db_error("22003"), "db_invalid_input"),
        (_fake_db_error("42P01"), "db_error"),
        (TimeoutError(), "timeout"),
        (ConnectionResetError(), "dependency_unreachable"),
        (ValueError("x"), "unexpected"),
    ],
)
def test_error_category_table(exc: BaseException, expected: str) -> None:
    assert error_category(exc) == expected


class _OriginalError(Exception):
    pass


async def test_failed_rollback_never_replaces_the_original_error(
    monkeypatch: pytest.MonkeyPatch, capfd: CaptureFixture[str]
) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    async def _broken_rollback(self: AsyncSession) -> None:
        raise ConnectionResetError("connection reset during rollback")

    monkeypatch.setattr(AsyncSession, "rollback", _broken_rollback)
    capfd.readouterr()
    with pytest.raises(_OriginalError):
        async with session_scope():
            raise _OriginalError("the real cause")
    (logged,) = [e for e in _events(capfd.readouterr().out) if e["event"] == "db_rollback_failed"]
    assert logged["exception_type"] == "ConnectionResetError"
    assert logged["error_category"] == "dependency_unreachable"
