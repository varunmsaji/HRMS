"""Unit tests for `OnboardingUploadRateLimitMiddleware` (SEC-03,
docs/audits/UPLOAD_BATCH_C_RATE_LIMITING.md) — the ASGI-level pieces that are impractical to
exercise end-to-end: path/method scoping, the Redis-failure (SEC-11 boundary) response, and that
no internal detail leaks into the public response body. Behavioural coverage of the actual
sliding-window counters against real Redis lives in the integration suite
(`tests/integration/modules/onboarding/test_onboarding_upload_rate_limit.py`), same split as
`rate_limit_by_ip_and_email`'s own unit vs. integration tests.
"""

import hashlib
import json
from typing import Any

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from hrms.shared import rate_limit as rate_limit_module
from hrms.shared.rate_limit import OnboardingUploadRateLimitMiddleware

pytestmark = pytest.mark.asyncio


class _DownstreamApp:
    def __init__(self) -> None:
        self.called = False

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        self.called = True
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


class _BrokenRedisClient:
    """Stands in for a Redis client that can't reach the server at all."""

    async def incr(self, _key: str) -> int:
        raise RedisConnectionError("connection refused")

    async def expire(self, _key: str, _seconds: int) -> None:
        raise RedisConnectionError("connection refused")

    async def ttl(self, _key: str) -> int:
        raise RedisConnectionError("connection refused")


def _scope(
    *,
    method: str = "POST",
    path: str = "/v1/public/onboarding/tok-abc/documents",
    client: tuple[str, int] | None = ("203.0.113.5", 4000),
) -> dict:
    scope: dict[str, Any] = {"type": "http", "method": method, "path": path, "headers": []}
    if client is not None:
        scope["client"] = client
    return scope


async def _receive() -> dict:
    return {"type": "http.request", "body": b"", "more_body": False}


class _Capture:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def __call__(self, message: dict) -> None:
        self.messages.append(message)

    @property
    def status(self) -> int | None:
        for message in self.messages:
            if message["type"] == "http.response.start":
                return message["status"]
        return None

    @property
    def headers(self) -> dict[bytes, bytes]:
        for message in self.messages:
            if message["type"] == "http.response.start":
                return dict(message["headers"])
        return {}

    @property
    def body(self) -> bytes:
        return b"".join(
            m.get("body", b"") for m in self.messages if m["type"] == "http.response.body"
        )


async def _clear_bucket(*keys: str) -> None:
    import redis.asyncio as redis

    from hrms.core.config.settings import get_settings

    client = redis.from_url(get_settings().redis_url, decode_responses=True)
    for key in keys:
        await client.delete(key)
    await client.aclose()


class TestPathAndMethodScoping:
    async def test_get_requests_to_the_same_path_pass_through_untouched(self) -> None:
        downstream = _DownstreamApp()
        middleware = OnboardingUploadRateLimitMiddleware(
            downstream, ip_limit=1, token_limit=1, window_seconds=60
        )
        capture = _Capture()
        await middleware(
            _scope(method="GET", path="/v1/public/onboarding/tok-abc/documents"),
            _receive,
            capture,
        )
        assert downstream.called is True
        assert capture.status == 200

    async def test_delete_of_a_specific_document_passes_through_untouched(self) -> None:
        downstream = _DownstreamApp()
        middleware = OnboardingUploadRateLimitMiddleware(
            downstream, ip_limit=1, token_limit=1, window_seconds=60
        )
        capture = _Capture()
        await middleware(
            _scope(
                method="DELETE",
                path="/v1/public/onboarding/tok-abc/documents/11111111-1111-1111-1111-111111111111",
            ),
            _receive,
            capture,
        )
        assert downstream.called is True

    async def test_unrelated_authenticated_routes_pass_through_untouched(self) -> None:
        downstream = _DownstreamApp()
        middleware = OnboardingUploadRateLimitMiddleware(
            downstream, ip_limit=1, token_limit=1, window_seconds=60
        )
        capture = _Capture()
        await middleware(_scope(method="POST", path="/v1/employee-imports"), _receive, capture)
        assert downstream.called is True

    async def test_non_http_scope_passes_through_untouched(self) -> None:
        downstream = _DownstreamApp()
        middleware = OnboardingUploadRateLimitMiddleware(
            downstream, ip_limit=1, token_limit=1, window_seconds=60
        )
        capture = _Capture()
        await middleware({"type": "lifespan"}, _receive, capture)
        assert downstream.called is True


class TestRedisFailurePolicy:
    async def test_redis_outage_fails_closed_with_503_and_never_calls_downstream(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(rate_limit_module, "_get_client", lambda: _BrokenRedisClient())
        downstream = _DownstreamApp()
        middleware = OnboardingUploadRateLimitMiddleware(
            downstream, ip_limit=30, token_limit=10, window_seconds=60
        )
        capture = _Capture()
        await middleware(_scope(), _receive, capture)

        assert downstream.called is False
        assert capture.status == 503
        body = capture.body.decode()
        assert "RATE_LIMITER_UNAVAILABLE" in body
        # Never leak the underlying Redis exception text to a public, unauthenticated caller.
        assert "connection refused" not in body.lower()

    async def test_redis_outage_response_is_the_standard_error_envelope_shape(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(rate_limit_module, "_get_client", lambda: _BrokenRedisClient())
        middleware = OnboardingUploadRateLimitMiddleware(
            _DownstreamApp(), ip_limit=30, token_limit=10, window_seconds=60
        )
        capture = _Capture()
        await middleware(_scope(), _receive, capture)
        payload = json.loads(capture.body)
        assert payload["error"]["code"] == "RATE_LIMITER_UNAVAILABLE"
        assert "request_id" in payload["error"]


class TestTokenNeverLoggedOrKeyedInRaw:
    async def test_the_raw_token_never_appears_in_a_rejected_response_body(self) -> None:
        try:
            middleware = OnboardingUploadRateLimitMiddleware(
                _DownstreamApp(), ip_limit=1, token_limit=1, window_seconds=60
            )
            scope = _scope(path="/v1/public/onboarding/super-secret-token/documents")
            # Trip the IP bucket first so the second call is rejected.
            await middleware(scope, _receive, _Capture())
            capture = _Capture()
            await middleware(scope, _receive, capture)
            assert capture.status == 429
            assert b"super-secret-token" not in capture.body
        finally:
            await _clear_bucket(
                "ratelimit:onboarding_upload:ip:203.0.113.5",
                f"ratelimit:onboarding_upload:token:"
                f"{hashlib.sha256(b'super-secret-token').hexdigest()}",
            )

    async def test_missing_client_falls_back_to_unknown_without_crashing(self) -> None:
        middleware = OnboardingUploadRateLimitMiddleware(
            _DownstreamApp(), ip_limit=5, token_limit=5, window_seconds=60
        )
        capture = _Capture()
        try:
            await middleware(_scope(client=None), _receive, capture)
        finally:
            await _clear_bucket(
                "ratelimit:onboarding_upload:ip:unknown",
                f"ratelimit:onboarding_upload:token:{hashlib.sha256(b'tok-abc').hexdigest()}",
            )
        assert capture.status == 200
