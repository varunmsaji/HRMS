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
from hrms.core.observability.logging import get_logger, safe_log
from hrms.core.observability.security_events import security_event, subject_hash
from hrms.core.tenancy.context import current_request_id

_client: redis.Redis | None = None
_logger = get_logger(__name__)


def _log_rate_limited(bucket: str, counts: dict[str, int], limit: int, **fields: object) -> None:
    """LOG-07 — a tripped limit is a security signal (credential stuffing, token guessing), but
    a client hammering past the limit must not flood the bounded log in turn: only the *first*
    over-limit request per key per window is logged (`count == limit + 1`); the rest are visible
    as 429s in the `http_request` access events and Nginx. `dimension` says which bucket(s)
    tripped. Never the raw email or token — `subject_hash`/token hash only."""
    tripped = [name for name, count in counts.items() if count > limit]
    if not any(counts[name] == limit + 1 for name in tripped):
        return
    security_event(
        "rate_limited",
        level="warning",
        bucket=bucket,
        dimension="+".join(tripped),
        limit=limit,
        **fields,
    )


class RateLimitExceededError(AppError):
    code = "RATE_LIMITED"
    status_code = 429

    def __init__(self, message: str, *, retry_after_seconds: int | None = None) -> None:
        # The counter window is an upper bound on the wait (the key expires at most that long
        # after its first hit), so it is a safe `Retry-After`.
        super().__init__(
            message,
            headers={"Retry-After": str(retry_after_seconds)} if retry_after_seconds else None,
        )


class RateLimiterUnavailableError(AppError):
    """SEC-11 (RELEASE_HARDENING_PHASE_3A) — raised when Redis itself is unreachable/times out,
    distinct from `RateLimitExceededError` (a normal, expected over-limit result). Before this,
    a `RedisError` from `client.incr`/`client.expire` propagated unhandled out of the `Depends()`
    dependency and was only ever caught by the generic `Exception` handler
    (`core/errors/handlers.py`), which returns a bare `INTERNAL_ERROR` 500 — indistinguishable
    from a real application bug and giving the caller no signal to retry. This mirrors
    `OnboardingUploadRateLimitMiddleware`'s own, already-correct `RATE_LIMITER_UNAVAILABLE` 503
    policy (below) for the middleware-based limiter — same failure semantics, now applied to
    every `Depends()`-based bucket (`auth`, `login`, `token_refresh`) too. Fails closed: the
    request is rejected, not silently admitted, when the limiter itself cannot be consulted."""

    code = "RATE_LIMITER_UNAVAILABLE"
    status_code = 503
    headers = {"Retry-After": "5"}


#: SEC-11 — a hung/unreachable Redis must fail fast (and therefore closed, via the 503 above)
#: rather than block the request indefinitely; redis-py applies no timeout by default.
_REDIS_SOCKET_TIMEOUT_SECONDS = 2.0


def _get_client() -> redis.Redis:
    global _client
    if _client is None:
        # redis-py's `from_url` classmethod has no return type annotation upstream.
        _client = redis.from_url(  # type: ignore[no-untyped-call]
            get_settings().redis_url,
            decode_responses=True,
            socket_timeout=_REDIS_SOCKET_TIMEOUT_SECONDS,
            socket_connect_timeout=_REDIS_SOCKET_TIMEOUT_SECONDS,
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
        try:
            count = await client.incr(key)
            if count == 1:
                await client.expire(key, window_seconds)
        except RedisError as exc:
            raise RateLimiterUnavailableError(
                "Rate limiter is temporarily unavailable — please try again shortly"
            ) from exc
        if count > limit:
            _log_rate_limited(bucket, {"ip": count}, limit, client_ip=client_ip)
            raise RateLimitExceededError(
                "Too many requests — please try again later", retry_after_seconds=window_seconds
            )

    return _dependency


async def enforce_rate_limit(
    bucket: str, *, subject: str, limit: int, window_seconds: int, **log_fields: object
) -> None:
    """One fixed-window counter for `subject` (the caller composes it, e.g. tenant + client IP).
    Same Redis primitive, failure policy (fail closed with 503) and log-once-per-window behaviour
    as `rate_limit`, for limiters whose key needs more than the client IP."""
    key = f"ratelimit:{bucket}:{subject}"
    client = _get_client()
    try:
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, window_seconds)
    except RedisError as exc:
        raise RateLimiterUnavailableError(
            "Rate limiter is temporarily unavailable — please try again shortly"
        ) from exc
    if count > limit:
        _log_rate_limited(bucket, {"subject": count}, limit, **log_fields)
        raise RateLimitExceededError(
            "Too many requests — please try again later", retry_after_seconds=window_seconds
        )


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

        try:
            ip_count = await client.incr(ip_key)
            if ip_count == 1:
                await client.expire(ip_key, window_seconds)

            identity_count = await client.incr(identity_key)
            if identity_count == 1:
                await client.expire(identity_key, window_seconds)
        except RedisError as exc:
            raise RateLimiterUnavailableError(
                "Rate limiter is temporarily unavailable — please try again shortly"
            ) from exc

        if ip_count > limit or identity_count > limit:
            _log_rate_limited(
                bucket,
                {"ip": ip_count, "email": identity_count},
                limit,
                client_ip=client_ip,
                subject_hash=subject_hash(identity) if identity != "unknown" else None,
            )
            raise RateLimitExceededError(
                "Too many requests — please try again later", retry_after_seconds=window_seconds
            )

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
        except RedisError as exc:
            # LOG-02 parity — this middleware answers directly (no `AppError`), so the 503 would
            # otherwise leave no server-side record of the Redis outage.
            safe_log(
                _logger.warning,
                "rate_limiter_unavailable",
                bucket="onboarding_upload",
                exception_type=type(exc).__name__,
            )
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
            if ip_count == self._ip_limit + 1:
                _log_rate_limited(
                    "onboarding_upload", {"ip": ip_count}, self._ip_limit, client_ip=client_ip
                )
            if token_count == self._token_limit + 1:
                _log_rate_limited(
                    "onboarding_upload",
                    {"token": token_count},
                    self._token_limit,
                    onboarding_ref=token_hash[:16],
                )
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
