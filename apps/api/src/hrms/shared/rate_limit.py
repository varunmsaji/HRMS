"""Redis-backed sliding-window rate limiter (Document 09 §1.9).

First real usage of `Settings.redis_url` for this purpose — the setting was already
provisioned but unused until this endpoint needed it. Applied as a `Depends()` per endpoint
(§1.9's documented pattern for per-endpoint buckets, as opposed to the per-tenant/global
limits that would be ASGI middleware instead).
"""

from collections.abc import Callable, Coroutine
from typing import Any

import redis.asyncio as redis
from fastapi import Request

from hrms.core.config.settings import get_settings
from hrms.core.errors.base import AppError

_client: redis.Redis | None = None


class RateLimitExceededError(AppError):
    code = "RATE_LIMITED"
    status_code = 429


def _get_client() -> redis.Redis:
    global _client
    if _client is None:
        # redis-py's `from_url` classmethod has no return type annotation upstream.
        _client = redis.from_url(  # type: ignore[no-untyped-call]
            get_settings().redis_url, decode_responses=True
        )
    return _client


async def close_rate_limiter() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def rate_limit(
    bucket: str, *, limit: int, window_seconds: int
) -> Callable[[Request], Coroutine[Any, Any, None]]:
    """FastAPI dependency factory — `limit` requests per `window_seconds`, keyed by client IP."""

    async def _dependency(request: Request) -> None:
        client_ip = request.client.host if request.client else "unknown"
        key = f"ratelimit:{bucket}:{client_ip}"
        client = _get_client()
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, window_seconds)
        if count > limit:
            raise RateLimitExceededError("Too many requests — please try again later")

    return _dependency
