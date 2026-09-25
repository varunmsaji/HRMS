"""SEC-05 (PLATFORM_READINESS_SECURITY_AUDIT_2026-09-17 §5) — baseline security headers on every
response: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`,
`Content-Security-Policy`, and an HTTPS-only `Strict-Transport-Security`."""

import pytest
from httpx import ASGITransport, AsyncClient

from hrms.app import create_app

pytestmark = pytest.mark.asyncio


async def test_security_headers_present_on_a_normal_response() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "camera=()" in response.headers["Permissions-Policy"]
    assert (
        response.headers["Content-Security-Policy"]
        == "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    )


async def test_security_headers_present_on_an_error_response() -> None:
    """The headers must not depend on the route succeeding — an `AppError`-driven 401 gets them
    too, same as any 200."""
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/auth/login", json={"email": "nobody@example.com", "password": "wrong-password"}
        )

    assert response.status_code == 401
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"


async def test_no_hsts_header_over_plain_http() -> None:
    """A request that arrives as plain HTTP (every local/dev request, and any deployment without
    TLS termination wired up yet) must never receive HSTS — sending it would make browsers refuse
    all future HTTP connections to the host, which is a lockout, not a protection."""
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")

    assert "Strict-Transport-Security" not in response.headers


async def test_hsts_header_present_once_the_request_is_confirmed_https() -> None:
    """`SecurityHeadersMiddleware` reads `request.url.scheme`, which reflects whatever scheme the
    request actually arrived as (in production, resolved from `X-Forwarded-Proto` by the trusted-
    proxy-aware `ProxyHeadersMiddleware`, OPS-02). Constructing the test client against an
    `https://` base URL is the most direct way to prove the *conditional* itself is correct,
    independent of proxy trust configuration."""
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client:
        response = await client.get("/health")

    assert response.headers["Strict-Transport-Security"] == "max-age=63072000; includeSubDomains"
