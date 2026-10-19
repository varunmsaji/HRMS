"""The shared error contract for failures that do not come from a domain `AppError`:
framework `HTTPException`s, validation, and protocol headers (`WWW-Authenticate`, `Retry-After`,
`Allow`). Every response must carry the standard envelope — never a bare `{"detail": ...}`."""

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, field_validator

from hrms.core.errors.auth import InvalidTokenError
from hrms.core.errors.handlers import register_exception_handlers
from hrms.shared.rate_limit import RateLimiterUnavailableError, RateLimitExceededError

pytestmark = pytest.mark.asyncio


class _Body(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def _no_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Name cannot be blank")
        return value


def _app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/teapot")
    async def teapot() -> None:
        raise HTTPException(418, detail={"internal": "dict detail"})

    @app.get("/forbidden")
    async def forbidden() -> None:
        raise HTTPException(403, detail="Nope")

    @app.get("/gateway")
    async def gateway() -> None:
        raise HTTPException(502, detail="upstream db01.internal refused")

    @app.get("/unauth")
    async def unauth() -> None:
        raise InvalidTokenError("Access token is invalid or expired")

    @app.get("/limited")
    async def limited() -> None:
        raise RateLimitExceededError("Too many requests", retry_after_seconds=60)

    @app.get("/limiter-down")
    async def limiter_down() -> None:
        raise RateLimiterUnavailableError("down")

    @app.post("/items")
    async def items(body: _Body) -> dict[str, str]:
        return {"name": body.name}

    return app


async def _call(method: str, path: str, **kw):  # type: ignore[no-untyped-def]
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        return await c.request(method, path, **kw)


def _assert_envelope(r, status: int, code: str) -> dict:  # type: ignore[no-untyped-def]
    assert r.status_code == status
    body = r.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert body["error"]["request_id"]
    assert isinstance(body["error"]["details"], list)
    return body["error"]


async def test_unknown_route_is_a_stable_not_found() -> None:
    _assert_envelope(await _call("GET", "/nope"), 404, "NOT_FOUND")


async def test_wrong_method_keeps_the_allow_header() -> None:
    r = await _call("DELETE", "/forbidden")
    _assert_envelope(r, 405, "METHOD_NOT_ALLOWED")
    assert "GET" in r.headers["allow"]


async def test_http_exception_codes_follow_the_status() -> None:
    _assert_envelope(await _call("GET", "/forbidden"), 403, "FORBIDDEN")


async def test_non_string_http_exception_detail_is_not_echoed() -> None:
    err = _assert_envelope(await _call("GET", "/teapot"), 418, "CLIENT_ERROR")
    assert "internal" not in err["message"]


async def test_5xx_http_exception_text_is_never_forwarded() -> None:
    r = await _call("GET", "/gateway")
    err = _assert_envelope(r, 502, "BAD_GATEWAY")
    assert "db01" not in r.text and err["message"] == "An unexpected error occurred"


async def test_401_carries_www_authenticate() -> None:
    r = await _call("GET", "/unauth")
    _assert_envelope(r, 401, "INVALID_TOKEN")
    assert r.headers["www-authenticate"] == "Bearer"


async def test_429_carries_retry_after() -> None:
    r = await _call("GET", "/limited")
    _assert_envelope(r, 429, "RATE_LIMITED")
    assert r.headers["retry-after"] == "60"


async def test_rate_limiter_outage_is_a_retryable_503() -> None:
    r = await _call("GET", "/limiter-down")
    _assert_envelope(r, 503, "RATE_LIMITER_UNAVAILABLE")
    assert r.headers["retry-after"] == "5"


async def test_validation_errors_are_field_level_and_user_readable() -> None:
    r = await _call("POST", "/items", json={"name": "  "})
    err = _assert_envelope(r, 422, "REQUEST_VALIDATION_ERROR")
    [detail] = err["details"]
    assert detail["field"] == "body.name"
    assert detail["message"] == "Name cannot be blank"  # no "Value error, " prefix


async def test_malformed_json_is_a_422_envelope_not_a_crash() -> None:
    r = await _call(
        "POST", "/items", content=b"{not json", headers={"content-type": "application/json"}
    )
    _assert_envelope(r, 422, "REQUEST_VALIDATION_ERROR")
