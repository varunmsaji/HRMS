"""A database lock/statement timeout is a retryable 503 with no internals leaked."""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import DBAPIError

from hrms.core.errors.handlers import register_exception_handlers

pytestmark = pytest.mark.asyncio


class LockNotAvailableError(Exception):
    sqlstate = "55P03"


class QueryCanceledError(Exception):
    sqlstate = "57014"


class SomethingElseError(Exception):
    sqlstate = "XX000"


def _wrapped(driver_exc: Exception) -> DBAPIError:
    orig = Exception("adapter")
    orig.__cause__ = driver_exc
    return DBAPIError("SELECT secret_table", {}, orig)


def _app(exc: Exception) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom() -> None:
        raise exc

    return app


@pytest.mark.parametrize("cause", [LockNotAvailableError("lock"), QueryCanceledError("cancel")])
async def test_timeouts_are_a_retryable_503(cause: Exception) -> None:
    transport = ASGITransport(app=_app(_wrapped(cause)))
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        response = await client.get("/boom")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DATABASE_BUSY"
    assert response.headers["retry-after"] == "2"
    assert "secret_table" not in response.text and "55P03" not in response.text


async def test_other_database_errors_stay_a_generic_500() -> None:
    transport = ASGITransport(app=_app(_wrapped(SomethingElseError("x"))))
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        response = await client.get("/boom")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
