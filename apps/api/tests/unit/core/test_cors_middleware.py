"""OPS-01 (PLATFORM_READINESS_SECURITY_AUDIT_2026-09-17) — exercises the real
`starlette.middleware.cors.CORSMiddleware` wired exactly as `hrms.app.create_app` wires it
(`allow_origins=settings.effective_cors_origins`, `allow_credentials=True`), against a small
probe app rather than the full `create_app()` — the full app needs a live Postgres/Redis at
import time; CORS preflight behaviour does not depend on either, so this stays fast and
isolated while still exercising the identical middleware configuration `app.py` ships.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from httpx import ASGITransport, AsyncClient

from hrms.core.config.settings import Settings

_STRONG_ACCESS_SECRET = "Zx7!qP9$mK2#vL5^rT8&nB1@wD4%yF6*hJ0"
_STRONG_REFRESH_SECRET = "Qm3&zR8!kX1#pL6^bN9$vT2@yH5%wD0*jF4"
#: RELEASE_HARDENING_PHASE_3A — a strong (test-only) application master key, required outside
#: development since `Settings._guard_non_development_config` also validates `pii_master_key`.
_TEST_PII_MASTER_KEY = "Nb4$hK7!wQ2#xM9^rF3&tY6@pL1%vD8*sG5"

#: INFRA-01 — required outside development since `_guard_non_development_config` now also
#: validates the self-hosted MinIO endpoint/bucket/credentials. Explicit here (rather than relying
#: on a local `.env`) so this test passes in CI, where no `.env` file exists.
_TEST_S3_KWARGS: dict[str, object] = {
    "s3_endpoint_url": "http://minio:9000",
    "s3_bucket_documents": "hrms-test-documents",
    "aws_access_key_id": "test-access-key",
    "aws_secret_access_key": "test-secret-key",
    # RELEASE_HARDENING_PHASE_5A — required outside development since `_guard_non_development_
    # config` now also validates email_provider="smtp" (never the logging-only default).
    "email_provider": "smtp",
    "smtp_host": "smtp.example.com",
    "smtp_from_email": "onboarding@example.com",
    "smtp_use_tls": True,
    "web_app_base_url": "https://app.example.com",
}


def _build_app(settings: Settings) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.effective_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/ping")
    async def ping() -> dict[str, bool]:
        return {"ok": True}

    return app


async def test_development_preflight_allows_the_dev_fallback_origin() -> None:
    settings = Settings(environment="development", web_app_base_url="http://localhost:3000")
    app = _build_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.options(
            "/ping",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert response.headers["access-control-allow-credentials"] == "true"


async def test_staging_preflight_allows_the_configured_origin() -> None:
    settings = Settings(
        environment="staging",
        jwt_access_secret=_STRONG_ACCESS_SECRET,
        jwt_refresh_secret=_STRONG_REFRESH_SECRET,
        cors_allowed_origins=("https://staging.example.com",),
        pii_master_key=_TEST_PII_MASTER_KEY,
        **_TEST_S3_KWARGS,
    )
    app = _build_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.options(
            "/ping",
            headers={
                "Origin": "https://staging.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://staging.example.com"


async def test_production_preflight_allows_the_configured_origin() -> None:
    settings = Settings(
        environment="production",
        jwt_access_secret=_STRONG_ACCESS_SECRET,
        jwt_refresh_secret=_STRONG_REFRESH_SECRET,
        cors_allowed_origins=("https://app.example.com",),
        pii_master_key=_TEST_PII_MASTER_KEY,
        **_TEST_S3_KWARGS,
    )
    app = _build_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.options(
            "/ping",
            headers={
                "Origin": "https://app.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        actual = await client.get("/ping", headers={"Origin": "https://app.example.com"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://app.example.com"
    assert response.headers["access-control-allow-credentials"] == "true"
    assert actual.status_code == 200
    assert actual.headers["access-control-allow-origin"] == "https://app.example.com"


async def test_production_rejects_an_untrusted_origin() -> None:
    settings = Settings(
        environment="production",
        jwt_access_secret=_STRONG_ACCESS_SECRET,
        jwt_refresh_secret=_STRONG_REFRESH_SECRET,
        cors_allowed_origins=("https://app.example.com",),
        pii_master_key=_TEST_PII_MASTER_KEY,
        **_TEST_S3_KWARGS,
    )
    app = _build_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        preflight = await client.options(
            "/ping",
            headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        actual = await client.get("/ping", headers={"Origin": "https://evil.example.com"})
    # Starlette's CORSMiddleware answers a rejected preflight with 400 and omits the
    # allow-origin header entirely; the simple request still reaches the route (CORS is
    # enforced by the browser reading the response headers, not the server refusing the
    # request) but must not carry an allow-origin header a browser would honour.
    assert preflight.status_code == 400
    assert "access-control-allow-origin" not in preflight.headers
    assert actual.status_code == 200
    assert "access-control-allow-origin" not in actual.headers
