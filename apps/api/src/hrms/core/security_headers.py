"""SEC-05 (PLATFORM_READINESS_SECURITY_AUDIT_2026-09-17 §5) — baseline production security
headers for every response. This is a pure JSON API (the only HTML it ever serves is Swagger
UI/ReDoc at `/docs`/`/redoc`, and OPS-06 already disables both outside development), so the CSP
here is deliberately the strictest possible: `default-src 'none'` with no exceptions, since a
JSON API response has no scripts, styles, images or fonts of its own to allow. `/docs`/`/redoc`
are exempted from that CSP line only, because Swagger UI/ReDoc load their own JS/CSS bundles from
a CDN — they still get every other header below, and they only exist at all in development
(OPS-06)."""

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

_DOCS_PATHS = ("/docs", "/redoc")

_API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        )
        if not request.url.path.startswith(_DOCS_PATHS):
            response.headers["Content-Security-Policy"] = _API_CSP

        # HSTS is only ever safe to send on a response that was actually served over HTTPS — a
        # request reaching this process over plain HTTP (every local/dev request, and any
        # deployment that hasn't wired up TLS termination yet) must never receive it: browsers
        # that honor HSTS refuse *all* future HTTP connections to the host for `max-age`, which
        # would lock out access rather than protect it. `request.url.scheme` already reflects
        # `ProxyHeadersMiddleware`'s (OPS-02) trusted-proxy-resolved `X-Forwarded-Proto`, so this
        # requires no new configuration: HSTS starts being sent automatically the day a trusted
        # reverse proxy in front of this app actually terminates TLS, and not one moment before.
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"

        return response
