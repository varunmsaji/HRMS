"""OPS-02 (PLATFORM_READINESS_SECURITY_AUDIT_2026-09-17) — proves the trusted-proxy IP
resolution and the rate limiter actually compose correctly end to end: a tiny probe app wired
the same way `hrms.app.create_app` wires it (`CORSMiddleware` → `TenancyMiddleware` →
`ProxyHeadersMiddleware` added last, so it resolves `scope["client"]` before anything else runs)
routing into a real `rate_limit(...)` dependency. The full `create_app()` app is not reused here
because it needs a live Postgres/Redis at *import* time with whatever `trusted_proxy_hosts` was
current then; this test needs several different `Settings(trusted_proxy_hosts=...)` values
within one process.
"""

import redis.asyncio as redis
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from httpx import ASGITransport, AsyncClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from hrms.core.config.settings import Settings, get_settings
from hrms.core.errors.handlers import register_exception_handlers
from hrms.core.tenancy.middleware import TenancyMiddleware
from hrms.shared.rate_limit import rate_limit


def _build_probe_app(settings: Settings, *, bucket: str, limit: int) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    _limited = rate_limit(bucket, limit=limit, window_seconds=60)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.effective_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(TenancyMiddleware)
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=list(settings.trusted_proxy_hosts))

    @app.get("/whoami")
    async def whoami(request: Request) -> dict[str, str | None]:
        return {"client_ip": request.client.host if request.client else None}

    @app.get("/limited")
    async def limited(request: Request, _rl: None = Depends(_limited)) -> dict[str, bool]:
        return {"ok": True}

    return app


async def _clear_bucket(bucket: str, *ips: str) -> None:
    client = redis.from_url(get_settings().redis_url, decode_responses=True)
    for ip in ips:
        await client.delete(f"ratelimit:{bucket}:{ip}")
    await client.aclose()


# Case A
async def test_direct_untrusted_request_ignores_spoofed_forwarded_for() -> None:
    settings = Settings(environment="development", trusted_proxy_hosts=())
    app = _build_probe_app(settings, bucket="probe-a", limit=1000)
    transport = ASGITransport(app=app, client=("203.0.113.9", 40000))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/whoami", headers={"X-Forwarded-For": "10.10.10.10"})
    assert response.json()["client_ip"] == "203.0.113.9"


# Case B
async def test_trusted_proxy_uses_the_forwarded_client_ip() -> None:
    settings = Settings(environment="development", trusted_proxy_hosts=("10.0.0.5",))
    app = _build_probe_app(settings, bucket="probe-b", limit=1000)
    transport = ASGITransport(app=app, client=("10.0.0.5", 40000))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/whoami", headers={"X-Forwarded-For": "198.51.100.7"})
    assert response.json()["client_ip"] == "198.51.100.7"


# Case C
async def test_untrusted_proxy_forwarded_for_is_ignored() -> None:
    settings = Settings(environment="development", trusted_proxy_hosts=("10.0.0.5",))
    app = _build_probe_app(settings, bucket="probe-c", limit=1000)
    transport = ASGITransport(app=app, client=("10.0.0.77", 40000))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/whoami", headers={"X-Forwarded-For": "198.51.100.7"})
    assert response.json()["client_ip"] == "10.0.0.77"


# Case D — the one that actually matters for the rate limiter: two real clients behind the
# same trusted load balancer must land in separate buckets, not one shared balancer-IP bucket.
async def test_two_clients_behind_trusted_proxy_get_independent_rate_limit_buckets() -> None:
    settings = Settings(environment="development", trusted_proxy_hosts=("10.0.0.5",))
    app = _build_probe_app(settings, bucket="probe-d", limit=1)
    transport = ASGITransport(app=app, client=("10.0.0.5", 40000))
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first_client_r1 = await client.get(
                "/limited", headers={"X-Forwarded-For": "198.51.100.1"}
            )
            first_client_r2 = await client.get(
                "/limited", headers={"X-Forwarded-For": "198.51.100.1"}
            )
            second_client_r1 = await client.get(
                "/limited", headers={"X-Forwarded-For": "198.51.100.2"}
            )
        assert first_client_r1.status_code == 200
        # Same forwarded client hit the bucket a second time — blocked at limit=1.
        assert first_client_r2.status_code == 429
        # A *different* forwarded client behind the same proxy has its own untouched bucket.
        assert second_client_r1.status_code == 200
    finally:
        await _clear_bucket("probe-d", "198.51.100.1", "198.51.100.2")


async def test_without_trusted_proxy_config_the_balancer_ip_is_one_shared_bucket() -> None:
    """Negative control for Case D: with no `trusted_proxy_hosts` configured, every request
    behind the balancer collapses onto the balancer's own peer IP — this is the OPS-02 bug the
    trusted-proxy configuration exists to fix."""
    settings = Settings(environment="development", trusted_proxy_hosts=())
    app = _build_probe_app(settings, bucket="probe-negative", limit=1)
    transport = ASGITransport(app=app, client=("10.0.0.5", 40000))
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r1 = await client.get("/limited", headers={"X-Forwarded-For": "198.51.100.1"})
            r2 = await client.get("/limited", headers={"X-Forwarded-For": "198.51.100.2"})
        assert r1.status_code == 200
        # Both "different" forwarded clients are in fact the same untrusted balancer peer.
        assert r2.status_code == 429
    finally:
        await _clear_bucket("probe-negative", "10.0.0.5")
