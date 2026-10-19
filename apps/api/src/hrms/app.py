import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from hrms.core.config.settings import Settings, get_settings
from hrms.core.crypto.registry import EncryptionKeyRegistry
from hrms.core.db.session import dispose_engine, get_engine, session_scope
from hrms.core.errors.handlers import register_exception_handlers
from hrms.core.observability.logging import configure_logging
from hrms.core.observability.request_context import RequestContextMiddleware
from hrms.core.security_headers import SecurityHeadersMiddleware
from hrms.core.tenancy.middleware import TenancyMiddleware
from hrms.core.uploads import MaxUploadSizeMiddleware
from hrms.modules.attendance.face_verification import close_face_verification_providers
from hrms.modules.attendance.liveness import MiniFasNetLivenessEngine, get_liveness_engine
from hrms.modules.health.router import router as health_router
from hrms.shared.rate_limit import OnboardingUploadRateLimitMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    get_engine(settings)

    # DATA-01 (docs/audits/DATA_01_PII_ENCRYPTION_IMPLEMENTATION_PLAN.md §10.3) — the
    # database-backed half of the boot guard: `Settings._guard_non_development_config` already
    # requires a real `pii_master_key` outside development (a synchronous check, no DB access);
    # this is the complementary check that at least one `ACTIVE` `encryption_keys` row actually
    # exists, which requires a query and so cannot live in `Settings`. Mirrors SEC-01's "fail at
    # boot, not on first request" posture. Never runs in development (this repository's test
    # suite never triggers `lifespan()` at all — httpx's `ASGITransport` does not invoke it by
    # default — so this has no effect on the existing test suite regardless).
    if not settings.is_development:
        async with session_scope(settings) as session:
            active_count = await EncryptionKeyRegistry().count_active(session)
        if active_count != 1:
            raise RuntimeError(
                f"encryption_keys has {active_count} ACTIVE row(s) for environment="
                f"{settings.environment!r} — refusing to boot without exactly one. Run the "
                "DATA-01 initial key provisioning step "
                "(hrms.core.crypto.provisioning.provision_initial_key) before deploying."
            )

    # Face liveness: when enabled, load and checksum-verify the model now so a missing or
    # tampered asset stops the API from booting instead of surfacing as 503s on the first punch.
    # Disabled (the default) loads nothing.
    liveness_engine = get_liveness_engine(settings)
    if isinstance(liveness_engine, MiniFasNetLivenessEngine):
        await asyncio.to_thread(liveness_engine.warm_up)

    yield
    await close_face_verification_providers()
    await dispose_engine()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging()

    # OPS-06 (PLATFORM_READINESS_SECURITY_AUDIT_2026-09-17 §5) — Swagger UI, ReDoc and the raw
    # OpenAPI schema publish the full route surface (every path, every request/response shape)
    # to any unauthenticated caller. `is_development` is the same "everything but real
    # development is treated as production" boundary `Settings._guard_non_development_config`
    # already draws for every other production-safety guard — staging gets the same treatment
    # as production here, not a third posture. Passing `None` for all three is FastAPI's own
    # documented way to disable them: none of the three routes get registered, so a request to
    # any of them is an ordinary 404, not a custom auth check to maintain.
    docs_enabled = settings.is_development
    app = FastAPI(
        title="HRMS API",
        version="0.1.0",
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/v1/openapi.json" if docs_enabled else None,
        lifespan=lifespan,
    )

    # Shared with `RequestContextMiddleware` below, which replays an unhandled-error 500 through
    # an identically configured `CORSMiddleware` (LOG-01) — one definition, so the two can never
    # disagree about which origins may read an error.
    cors_options: dict[str, Any] = {
        "allow_origins": settings.effective_cors_origins,
        "allow_credentials": True,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
        # Lets browser code read the correlation id off any response (CORS hides non-safelisted
        # response headers from cross-origin JavaScript otherwise).
        "expose_headers": ["X-Request-Id"],
    }
    app.add_middleware(CORSMiddleware, **cors_options)
    # SEC-03 (docs/audits/UPLOAD_BATCH_B_FILE_VALIDATION.md) — the public, unauthenticated
    # onboarding document-upload endpoint is the finding's primary target; the authenticated
    # employee-import CSV upload shares the same `await file.read()`-before-size-check pattern
    # (hrms/core/uploads.py docstring) so it gets the same guard at a smaller ceiling. Scoped by
    # path prefix only — not a general request-body limiter for the rest of the API. Each ceiling
    # includes headroom above the corresponding per-file business-rule limit for multipart form
    # overhead (boundary markers, part headers, the `document_type`/other fields sharing the
    # request) — the exact per-file byte ceiling is still enforced by the existing
    # `OnboardingDocumentTooLargeError`/new `ImportFileTooLargeError` checks inside the request.
    from hrms.modules.employee_import.schemas import MAX_IMPORT_FILE_SIZE_BYTES
    from hrms.modules.onboarding.schemas import ONBOARDING_DOCUMENT_MAX_SIZE_BYTES

    app.add_middleware(
        MaxUploadSizeMiddleware,
        max_bytes=ONBOARDING_DOCUMENT_MAX_SIZE_BYTES + 2 * 1024 * 1024,
        path_prefixes=("/v1/public/onboarding/",),
    )
    app.add_middleware(
        MaxUploadSizeMiddleware,
        max_bytes=MAX_IMPORT_FILE_SIZE_BYTES + 1024 * 1024,
        path_prefixes=("/v1/employee-imports",),
    )
    from hrms.modules.employee.schemas import EMPLOYEE_DOCUMENT_MAX_SIZE_BYTES

    # Scoped to all of `/v1/employees` rather than just the `.../documents` sub-path — harmless,
    # since this is a ceiling (no other employee route accepts a body anywhere near this size),
    # and `MaxUploadSizeMiddleware` only matches by path prefix.
    app.add_middleware(
        MaxUploadSizeMiddleware,
        max_bytes=EMPLOYEE_DOCUMENT_MAX_SIZE_BYTES + 2 * 1024 * 1024,
        path_prefixes=("/v1/employees",),
    )
    from hrms.modules.attendance.schemas import (
        FACE_ENROLLMENT_ANGLES,
        FACE_IMAGE_MAX_BYTES,
        FACE_LIVENESS_FRAME_MAX_BYTES,
        FACE_LIVENESS_MAX_FRAMES,
    )

    # Face punch: up to FACE_LIVENESS_MAX_FRAMES liveness frames (per-frame cap enforced again
    # in the route), plus multipart overhead.
    app.add_middleware(
        MaxUploadSizeMiddleware,
        max_bytes=FACE_LIVENESS_MAX_FRAMES * FACE_LIVENESS_FRAME_MAX_BYTES + 1024 * 1024,
        path_prefixes=("/v1/attendance/face-punches",),
    )
    app.add_middleware(
        MaxUploadSizeMiddleware,
        max_bytes=len(FACE_ENROLLMENT_ANGLES) * FACE_IMAGE_MAX_BYTES + 1024 * 1024,
        path_prefixes=("/v1/attendance/face-enrollment",),
    )
    # SEC-03 (docs/audits/UPLOAD_BATCH_C_RATE_LIMITING.md) — abuse/DoS protection for the same
    # public, unauthenticated upload endpoint the middleware above already size-bounds. Added
    # ahead of `TenancyMiddleware` in this call order (so it ends up *inside* Tenancy/ProxyHeaders
    # in the actual request path — Starlette builds the stack in reverse add order) because it
    # needs the trusted-proxy-resolved `scope["client"]` OPS-02 already sets up, and it runs before
    # both `MaxUploadSizeMiddleware` registrations and all of FastAPI's own routing/multipart
    # parsing/DI, rejecting an over-limit request before any of that work starts. 30 requests per
    # IP and 10 per onboarding token per 60s are this batch's own engineering decision — no source
    # document names a number for this endpoint; see the report's §4 for the reasoning and the
    # explicit call-out that this needs product/security sign-off, not a claim that it already has
    # it.
    app.add_middleware(
        OnboardingUploadRateLimitMiddleware,
        ip_limit=30,
        token_limit=10,
        window_seconds=60,
    )
    app.add_middleware(TenancyMiddleware)
    # SEC-05 — added after Tenancy (so it wraps everything inner: rate limits, uploads, CORS,
    # routes/exception handlers, all get these headers on their response) but before
    # ProxyHeadersMiddleware below (so it stays one layer *inside* that — its own HSTS check
    # needs `request.url.scheme` already resolved from `X-Forwarded-Proto`, which only happens
    # once ProxyHeadersMiddleware, the actual outermost layer, has run first).
    app.add_middleware(SecurityHeadersMiddleware)
    # OPS-02 — added last so it is the outermost middleware (Starlette builds the stack in
    # reverse add order): it must resolve `scope["client"]` before CORS/Tenancy/rate-limit/
    # route code ever reads `request.client.host`. Trusts `X-Forwarded-For` only from the
    # configured `trusted_proxy_hosts`; with the empty default, every request's socket peer is
    # used as-is and forwarded headers from an untrusted source are never applied.
    app.add_middleware(
        ProxyHeadersMiddleware,
        trusted_hosts=list(settings.trusted_proxy_hosts),
    )
    # LOG-01/LOG-05 — added very last, so it wraps every other middleware: it owns the request id
    # (validated, bounded, always echoed as `X-Request-Id`) for the whole stack, and catches any
    # exception that escapes it, logging once and answering with the standard 500 envelope plus
    # CORS and security headers (`core/observability/request_context.py`). It does not read the
    # client address, so sitting outside ProxyHeadersMiddleware is harmless.
    app.add_middleware(RequestContextMiddleware, cors_options=cors_options)

    register_exception_handlers(app)

    from hrms.modules.account_invite.public_router import router as account_invite_public_router
    from hrms.modules.account_invite.router import router as account_invite_router
    from hrms.modules.attendance.router import router as attendance_router
    from hrms.modules.employee.router import router as employee_router
    from hrms.modules.employee_import.router import router as employee_import_router
    from hrms.modules.identity.router import router as identity_router
    from hrms.modules.leave.router import router as leave_router
    from hrms.modules.onboarding.public_router import router as onboarding_public_router
    from hrms.modules.onboarding.router import router as onboarding_router
    from hrms.modules.organisation.router import router as organisation_router
    from hrms.modules.payroll.router import router as payroll_router
    from hrms.modules.platform.router import router as platform_router

    app.include_router(health_router)
    app.include_router(identity_router, prefix="/v1")
    app.include_router(organisation_router, prefix="/v1")
    app.include_router(employee_router, prefix="/v1")
    app.include_router(employee_import_router, prefix="/v1")
    app.include_router(attendance_router, prefix="/v1")
    app.include_router(leave_router, prefix="/v1")
    app.include_router(payroll_router, prefix="/v1")
    app.include_router(onboarding_router, prefix="/v1")
    app.include_router(onboarding_public_router, prefix="/v1")
    app.include_router(account_invite_router, prefix="/v1")
    app.include_router(account_invite_public_router, prefix="/v1")
    app.include_router(platform_router, prefix="/v1")

    return app
