import pytest
import redis.asyncio as redis
from fastapi import Request
from httpx import AsyncClient

from hrms.core.config.settings import get_settings
from hrms.modules.organisation.router import _registration_rate_limit
from hrms.modules.organisation.router import router as organisation_router
from hrms.shared.rate_limit import RateLimitExceededError, rate_limit


def test_registration_route_has_rate_limit_dependency_attached() -> None:
    """Structural check: the same dependency instance mounted on the route is the one
    module-level `_registration_rate_limit` object the router defines for this bucket."""
    route = next(r for r in organisation_router.routes if r.path == "/companies/register")  # type: ignore[attr-defined]
    dependency_callables = [dep.call for dep in route.dependant.dependencies]  # type: ignore[attr-defined]
    assert _registration_rate_limit in dependency_callables


@pytest.mark.asyncio
async def test_rate_limit_dependency_blocks_after_threshold() -> None:
    """Behavioural check against the real Redis instance (available in this environment,
    same as the Postgres integration tests) — exercises the actual sliding-window counter,
    not just its wiring."""
    dep = rate_limit("test-rl-bucket", limit=3, window_seconds=60)
    scope = {"type": "http", "client": ("127.0.0.1", 555), "headers": []}
    request = Request(scope)

    client = redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        await client.delete("ratelimit:test-rl-bucket:127.0.0.1")
        for _ in range(3):
            await dep(request)
        with pytest.raises(RateLimitExceededError):
            await dep(request)
    finally:
        await client.delete("ratelimit:test-rl-bucket:127.0.0.1")
        await client.aclose()


@pytest.mark.asyncio
async def test_registration_endpoint_returns_429_past_configured_limit(
    client: AsyncClient,
) -> None:
    """End-to-end against the real mounted route with its real configured bucket (10/min per
    IP). Sends intentionally invalid bodies (missing `name`) so no DB work happens on the way
    — the rate-limit dependency runs before body validation, so this still exercises the
    real limiter attached to the real endpoint."""
    responses = [await client.post("/v1/companies/register", json={}) for _ in range(11)]
    assert responses[-1].status_code == 429
    assert responses[-1].json()["error"]["code"] == "RATE_LIMITED"
    assert all(r.status_code == 422 for r in responses[:10])
