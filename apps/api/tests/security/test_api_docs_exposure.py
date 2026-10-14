"""OPS-06 (PLATFORM_READINESS_SECURITY_AUDIT_2026-09-17 §5, `app.py:30-32`) — Swagger UI, ReDoc
and the raw OpenAPI schema must only be reachable in development; every other environment must
return an ordinary 404 for all three, not a route that happens to be gated separately."""

import secrets

import pytest
from httpx import ASGITransport, AsyncClient

from hrms.app import create_app
from hrms.core.config.settings import Settings

pytestmark = pytest.mark.asyncio

_DOCS_PATHS = ("/docs", "/redoc", "/v1/openapi.json")

#: Enough to satisfy `Settings._guard_non_development_config`'s own requirements for a
#: non-development environment — real values are irrelevant here, only their presence/shape is.
_NON_DEV_KWARGS = {
    "jwt_access_secret": secrets.token_urlsafe(32),
    "jwt_refresh_secret": secrets.token_urlsafe(32),
    "cors_allowed_origins": ("https://app.example.com",),
    "s3_endpoint_url": "https://s3.example.com",
    "s3_bucket_documents": "docs-bucket",
    "aws_access_key_id": "AKIAEXAMPLE",
    "aws_secret_access_key": secrets.token_urlsafe(24),
    "pii_master_key": secrets.token_urlsafe(32),
    # RELEASE_HARDENING_PHASE_5A — production/staging refuse to boot with email_provider="logging".
    "email_provider": "smtp",
    "smtp_host": "smtp.example.com",
    "smtp_from_email": "onboarding@example.com",
    "smtp_use_tls": True,
    "web_app_base_url": "https://app.example.com",
}


async def test_docs_available_in_development() -> None:
    app = create_app(settings=Settings())  # field default is environment="development"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for path in _DOCS_PATHS:
            response = await client.get(path)
            assert response.status_code == 200, f"{path} should be reachable in development"


async def test_docs_unavailable_in_production() -> None:
    app = create_app(settings=Settings(environment="production", **_NON_DEV_KWARGS))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for path in _DOCS_PATHS:
            response = await client.get(path)
            assert response.status_code == 404, f"{path} must not be reachable in production"


async def test_docs_unavailable_in_staging() -> None:
    """Staging gets the same posture as production — `is_development` is the only boundary this
    codebase draws anywhere else (every other production-safety guard in `Settings` treats
    staging identically to production), so docs exposure follows the same line."""
    app = create_app(settings=Settings(environment="staging", **_NON_DEV_KWARGS))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for path in _DOCS_PATHS:
            response = await client.get(path)
            assert response.status_code == 404, f"{path} must not be reachable in staging"


async def test_schema_generation_still_works_in_development() -> None:
    """OPS-06 must not break schema generation for development/testing — `/v1/openapi.json`'s
    200 response above already proves this, but assert its actual shape too."""
    app = create_app(settings=Settings())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/openapi.json")

    schema = response.json()
    assert schema["info"]["title"] == "HRMS API"
    assert "/v1/auth/login" in schema["paths"]
