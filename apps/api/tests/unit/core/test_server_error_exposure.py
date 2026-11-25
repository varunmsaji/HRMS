"""EH-B-02 / EH-B-03 — a 5xx response never carries an exception's own text, and carries a
short support reference that the server log also records."""

import importlib
import pkgutil
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import hrms
from hrms.core.errors.base import GENERIC_SERVER_ERROR_MESSAGE, AppError
from hrms.core.errors.envelope import error_reference
from hrms.core.errors.handlers import register_exception_handlers

pytestmark = pytest.mark.asyncio

SENTINEL = "SENTINEL-secret-key-version-42 SELECT * FROM hidden_table"


def _all_app_error_subclasses() -> list[type[AppError]]:
    for module in pkgutil.walk_packages(hrms.__path__, "hrms."):
        try:
            importlib.import_module(module.name)
        except Exception:  # noqa: BLE001 - optional extras (cv2 etc.) may be missing in CI
            continue
    found: list[type[AppError]] = []
    stack = list(AppError.__subclasses__())
    while stack:
        cls = stack.pop()
        stack.extend(cls.__subclasses__())
        if cls.status_code >= 500:
            found.append(cls)
    return found


def _app_raising(exc: Exception) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom() -> None:
        raise exc

    return app


async def _get(exc: Exception) -> Any:
    transport = ASGITransport(app=_app_raising(exc), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        return await client.get("/boom")


async def test_there_are_5xx_app_errors_to_check() -> None:
    assert len(_all_app_error_subclasses()) >= 10


@pytest.mark.parametrize("cls", _all_app_error_subclasses(), ids=lambda c: c.__name__)
async def test_5xx_app_error_never_forwards_its_instance_message(cls: type[AppError]) -> None:
    try:
        exc = cls(SENTINEL)
    except TypeError:
        exc = cls()  # a subclass with a fixed constructor already cannot take caller text
    r = await _get(exc)
    assert r.status_code >= 500
    assert "SENTINEL" not in r.text and "hidden_table" not in r.text
    err = r.json()["error"]
    assert err["message"] == (cls.public_message or GENERIC_SERVER_ERROR_MESSAGE)
    assert err["details"] == []


async def test_5xx_app_error_details_are_dropped() -> None:
    class _Boom(AppError):  # noqa: N818
        status_code = 500

    r = await _get(_Boom("x", details=[{"field": "f", "message": SENTINEL}]))
    assert "SENTINEL" not in r.text


async def test_4xx_app_error_keeps_its_curated_message_and_has_no_reference() -> None:
    class _Nope(AppError):  # noqa: N818
        status_code = 409

    r = await _get(_Nope("Already exists"))
    err = r.json()["error"]
    assert err["message"] == "Already exists"
    assert "reference" not in err  # the key exists only on a 5xx


async def test_unhandled_exception_has_generic_text_and_a_reference() -> None:
    r = await _get(RuntimeError(SENTINEL))
    assert r.status_code == 500
    assert "SENTINEL" not in r.text
    err = r.json()["error"]
    assert err["message"] == GENERIC_SERVER_ERROR_MESSAGE
    assert err["reference"] == error_reference(err["request_id"])


async def test_reference_is_short_stable_and_not_the_request_id() -> None:
    ref = error_reference("abc")
    assert ref == error_reference("abc")
    assert ref != error_reference("abd")
    assert ref.startswith("ERR-") and len(ref) == 12 and ref.upper() == ref
    assert "abc" not in ref
