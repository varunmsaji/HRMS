"""Redis-backed sliding-window rate limiter (Document 09 §1.9).

First real usage of `Settings.redis_url` for this purpose — the setting was already
provisioned but unused until this endpoint needed it. Applied as a `Depends()` per endpoint
(§1.9's documented pattern for per-endpoint buckets, as opposed to the per-tenant/global
limits that would be ASGI middleware instead).
"""

import hashlib
import json
import re
from collections.abc import Callable, Coroutine
from typing import Any

import redis.asyncio as redis
from fastapi import Request
from redis.exceptions import RedisError
from starlette.types import ASGIApp, Receive, Scope, Send

from hrms.core.config.settings import get_settings
from hrms.core.errors.base import AppError
from hrms.core.errors.envelope import ErrorBody, ErrorEnvelope
from hrms.core.tenancy.context import current_request_id

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


async def _extract_login_identity(request: Request) -> str:
    """Best-effort `email` from the raw JSON body — `Request.json()` caches the parsed body
    on the `Request` instance, so this read is free for the endpoint's own `LoginRequest`
    body param (SEC-02): no double-consumption of the ASGI receive channel."""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 — malformed/absent body just falls back to "unknown"
        return "unknown"
    if isinstance(body, dict):
        email = body.get("email")
        if isinstance(email, str) and email.strip():
            return email.strip().lower()
    return "unknown"


def rate_limit_by_ip_and_email(
    bucket: str, *, limit: int, window_seconds: int
) -> Callable[[Request], Coroutine[Any, Any, None]]:
    """Dual-bucket variant of `rate_limit` for credential endpoints (SEC-02). A single IP
    bucket alone lets an attacker spray many accounts from one address; a single email bucket
    alone lets an attacker distribute a credential-stuffing run against one known account
    across many addresses. Keying independently on client IP *and* the request body's `email`
    closes both gaps with the same Redis-backed sliding-window primitive `rate_limit` already
    uses — no second limiter, no change to what happens on a Redis outage (tracked separately,
    SEC-11)."""

    async def _dependency(request: Request) -> None:
        client_ip = request.client.host if request.client else "unknown"
        identity = await _extract_login_identity(request)
        client = _get_client()

        ip_key = f"ratelimit:{bucket}:ip:{client_ip}"
        identity_key = f"ratelimit:{bucket}:email:{identity}"

        ip_count = await client.incr(ip_key)
        if ip_count == 1:
            await client.expire(ip_key, window_seconds)

        identity_count = await client.incr(identity_key)
        if identity_count == 1:
            await client.expire(identity_key, window_seconds)

        if ip_count > limit or identity_count > limit:
            raise RateLimitExceededError("Too many requests — please try again later")

    return _dependency


class OnboardingUploadRateLimitMiddleware:
    """ASGI-level dual-bucket limiter for `POST /public/onboarding/{token}/documents` (SEC-03,
    docs/audits/UPLOAD_BATCH_C_RATE_LIMITING.md).

    Deliberately not a `Depends()` like every other limiter in this module: FastAPI's own
    `get_request_handler` calls `await request.form()` to fully parse and spool the multipart
    body *before* `solve_dependencies` ever runs (verified against the pinned fastapi version —
    see `hrms.core.uploads`'s module docstring, which the same framework behaviour already
    forced `MaxUploadSizeMiddleware` to be ASGI-level rather than a dependency). A per-route
    dependency therefore cannot reject a request ahead of the multipart parse or the DB query
    `get_onboarding_case_from_token` performs to resolve the token — only middleware, positioned
    ahead of routing in `app.py` (the same position `MaxUploadSizeMiddleware` already occupies
    for this exact endpoint), can.

    Two independent counters, same rationale as `rate_limit_by_ip_and_email` (SEC-02): the IP
    bucket bounds one source hammering the endpoint regardless of which token it sends (including
    garbage/guessed tokens that never reach `get_onboarding_case_from_token`); the token bucket
    bounds the worst-case request volume against one onboarding case regardless of how many
    source IPs it's spread across. The raw token is never used as a Redis key or logged — only
    its SHA-256 hash — since it is a bearer credential for that case (plan §5).

    Redis-failure policy is an explicit, local decision (§7 of the report above), independent of
    SEC-11's still-open, separately-tracked failure behaviour for the other (`Depends()`-based)
    limiters in this module: this endpoint fails *closed* (503) rather than silently admitting
    unlimited uploads, and the failure is scoped to this one route — every other endpoint,
    including the rest of the onboarding module, is unaffected by a Redis outage here.
    """

    _PATH_RE = re.compile(r"^/v1/public/onboarding/(?P<token>[^/]+)/documents/?$")

    def __init__(
        self,
        app: ASGIApp,
        *,
        ip_limit: int,
        token_limit: int,
        window_seconds: int,
    ) -> None:
        self._app = app
        self._ip_limit = ip_limit
        self._token_limit = token_limit
        self._window_seconds = window_seconds

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "POST":
            await self._app(scope, receive, send)
            return
        match = self._PATH_RE.match(scope["path"])
        if match is None:
            await self._app(scope, receive, send)
            return

        client = scope.get("client")
        client_ip = client[0] if client else "unknown"
        token_hash = hashlib.sha256(match.group("token").encode()).hexdigest()

        try:
            retry_after_seconds = await self._check_and_increment(client_ip, token_hash)
        except RedisError:
            await self._send(
                send,
                503,
                "RATE_LIMITER_UNAVAILABLE",
                "Upload temporarily unavailable — please try again shortly",
            )
            return

        if retry_after_seconds is not None:
            await self._send(
                send,
                429,
                "RATE_LIMITED",
                "Too many upload attempts — please try again later",
                retry_after_seconds=retry_after_seconds,
            )
            return

        await self._app(scope, receive, send)

    async def _check_and_increment(self, client_ip: str, token_hash: str) -> int | None:
        """Returns the seconds the caller should wait before retrying if either bucket is over
        its limit, otherwise `None`."""
        client = _get_client()
        ip_key = f"ratelimit:onboarding_upload:ip:{client_ip}"
        token_key = f"ratelimit:onboarding_upload:token:{token_hash}"

        ip_count = await client.incr(ip_key)
        if ip_count == 1:
            await client.expire(ip_key, self._window_seconds)

        token_count = await client.incr(token_key)
        if token_count == 1:
            await client.expire(token_key, self._window_seconds)

        if ip_count > self._ip_limit or token_count > self._token_limit:
            over_key = ip_key if ip_count > self._ip_limit else token_key
            ttl = await client.ttl(over_key)
            return ttl if ttl and ttl > 0 else self._window_seconds
        return None

    async def _send(
        self,
        send: Send,
        status_code: int,
        code: str,
        message: str,
        *,
        retry_after_seconds: int | None = None,
    ) -> None:
        # Never leak Redis connection details/internal keys to a public, unauthenticated caller
        # — `message` above is always a fixed, generic string, never built from the caught
        # exception.
        envelope = ErrorEnvelope(
            error=ErrorBody(
                code=code,
                message=message,
                details=[],
                request_id=current_request_id() or "unknown",
            )
        )
        body = json.dumps(envelope.model_dump(mode="json")).encode("utf-8")
        headers = [(b"content-type", b"application/json")]
        if retry_after_seconds is not None:
            headers.append((b"retry-after", str(retry_after_seconds).encode()))
        await send({"type": "http.response.start", "status": status_code, "headers": headers})
        await send({"type": "http.response.body", "body": body})
