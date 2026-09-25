"""SEC-11 (RELEASE_HARDENING_PHASE_3A_SECURITY_REMEDIATION.md) — before this fix, a `RedisError`
raised out of `client.incr`/`client.expire` inside `rate_limit`/`rate_limit_by_ip_and_email`
propagated unhandled and was only ever caught by the generic `Exception` handler
(`core/errors/handlers.py`), returning an indistinguishable `INTERNAL_ERROR` 500. These tests
prove both `Depends()`-based limiters now fail closed with a purpose-built, clean
`RATE_LIMITER_UNAVAILABLE` 503 instead — mirroring `OnboardingUploadRateLimitMiddleware`'s
already-correct policy for the middleware-based limiter."""

import json
from collections.abc import Callable, Coroutine
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import Request
from redis.exceptions import RedisError

from hrms.shared import rate_limit as rate_limit_module
from hrms.shared.rate_limit import (
    RateLimiterUnavailableError,
    rate_limit,
    rate_limit_by_ip_and_email,
)


def _request(client_ip: str, email: str | None = None) -> Request:
    body = json.dumps({"email": email} if email else {}).encode()

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {"type": "http", "client": (client_ip, 555), "headers": []}
    return Request(scope, receive=receive)


@pytest.fixture
def broken_redis_client(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Replaces `_get_client()` with a fake client whose `incr` raises `RedisError` — simulating
    an unreachable/timed-out Redis without needing to actually stop the real instance."""
    fake_client = AsyncMock()
    fake_client.incr.side_effect = RedisError("Connection refused")

    def _fake_get_client() -> AsyncMock:
        return fake_client

    monkeypatch.setattr(rate_limit_module, "_get_client", _fake_get_client)
    return fake_client


@pytest.mark.asyncio
async def test_plain_rate_limit_fails_closed_with_clean_503_on_redis_outage(
    broken_redis_client: AsyncMock,
) -> None:
    dep: Callable[[Request], Coroutine[Any, Any, None]] = rate_limit(
        "test-redis-outage", limit=10, window_seconds=60
    )
    with pytest.raises(RateLimiterUnavailableError) as exc_info:
        await dep(_request("9.9.9.250"))
    assert exc_info.value.status_code == 503
    assert exc_info.value.code == "RATE_LIMITER_UNAVAILABLE"


@pytest.mark.asyncio
async def test_dual_bucket_rate_limit_fails_closed_with_clean_503_on_redis_outage(
    broken_redis_client: AsyncMock,
) -> None:
    dep: Callable[[Request], Coroutine[Any, Any, None]] = rate_limit_by_ip_and_email(
        "test-redis-outage-dual", limit=10, window_seconds=60
    )
    with pytest.raises(RateLimiterUnavailableError) as exc_info:
        await dep(_request("9.9.9.251", "someone@example.com"))
    assert exc_info.value.status_code == 503
    assert exc_info.value.code == "RATE_LIMITER_UNAVAILABLE"
