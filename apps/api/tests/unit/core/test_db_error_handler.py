"""The catch-all DB error handler: a value the database cannot store is the caller's fault (422);
any other database failure stays a generic 500 with no internals leaked."""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import DataError as SqlDataError
from sqlalchemy.exc import DBAPIError, OperationalError

from hrms.core.errors.handlers import register_exception_handlers

pytestmark = pytest.mark.asyncio


class DataError(Exception):  # same name asyncpg gives its client-side overflow error
    pass


class UniqueViolationError(Exception):
    sqlstate = "23505"


class NumericValueOutOfRangeError(Exception):
    sqlstate = "22003"


def _wrapped(driver_exc: Exception) -> DBAPIError:
    orig = Exception("adapter")
    orig.__cause__ = driver_exc
    return DBAPIError("INSERT ...", {}, orig)


def _app(exc: Exception) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom() -> None:
        raise exc

    return app


@pytest.mark.parametrize(
    "exc",
    [
        _wrapped(DataError("value out of int64 range")),
        _wrapped(NumericValueOutOfRangeError("integer out of range")),
        SqlDataError("INSERT", {}, Exception("22P02")),
    ],
)
async def test_unstorable_values_are_422(exc: Exception) -> None:
    async with AsyncClient(transport=ASGITransport(app=_app(exc)), base_url="http://t") as c:
        r = await c.get("/boom")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_VALUE"
    assert "int64" not in r.text and "INSERT" not in r.text


@pytest.mark.parametrize(
    "exc",
    [
        _wrapped(UniqueViolationError("duplicate key")),
        OperationalError("SELECT 1", {}, Exception("connection refused")),
    ],
)
async def test_other_database_errors_stay_a_generic_500(exc: Exception) -> None:
    async with AsyncClient(transport=ASGITransport(app=_app(exc)), base_url="http://t") as c:
        r = await c.get("/boom")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "duplicate" not in r.text and "refused" not in r.text
