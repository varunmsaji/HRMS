"""Request-level flood limits for the face endpoints.

The employee-scoped controls (failed-attempt lockout, challenges per window, enrollment attempt
limit) stay the identity protections. These add a ceiling per (tenant, client IP) so one source —
a script, a misbehaving app build, a compromised account probing — cannot hammer the biometric
endpoints and, through them, the paid face provider and the liveness engine.

Why they are generous: an office commonly shares one NAT address, so a low per-IP limit would let
one person's failures (or just a busy shift start) block everyone behind it. The limits are
therefore flood ceilings, not lockout rules, they count requests whatever their outcome (a
provider outage neither raises nor lowers them), and they are keyed by tenant as well so one
company's traffic cannot spend another's budget.

The client IP is `request.client.host`. `ProxyHeadersMiddleware` (app.py) replaces it with the
`X-Forwarded-For` value only when the immediate peer is in `TRUSTED_PROXY_HOSTS`; from any other
peer the header is ignored, so a caller cannot choose their own bucket by sending one.

The dependency runs after authentication (it needs the verified tenant), so unauthenticated
traffic never creates buckets. Multipart bodies are parsed by the framework before dependencies
run; the limit's job is to stop the expensive work (liveness model, provider calls) behind them."""

from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, Request

from hrms.core.config.settings import get_settings
from hrms.core.tenancy.context import TenantContext
from hrms.core.tenancy.dependencies import get_tenant_context
from hrms.shared.rate_limit import enforce_rate_limit

_WINDOW_SECONDS = 60


def face_request_rate_limit(
    bucket: str, setting_name: str
) -> Callable[..., Coroutine[Any, Any, None]]:
    """`setting_name` is the `Settings` attribute holding the per-minute limit; it is read on every
    request, so the limit follows configuration rather than import time."""

    async def _dependency(
        request: Request, tenant: Annotated[TenantContext, Depends(get_tenant_context)]
    ) -> None:
        client_ip = request.client.host if request.client else "unknown"
        await enforce_rate_limit(
            bucket,
            subject=f"{tenant.company_id}:{client_ip}",
            limit=int(getattr(get_settings(), setting_name)),
            window_seconds=_WINDOW_SECONDS,
            client_ip=client_ip,
            company_id=str(tenant.company_id),
        )

    return _dependency


face_punch_rate_limit = face_request_rate_limit(
    "face_punch", "face_punch_requests_per_minute_per_ip"
)
face_enrollment_rate_limit = face_request_rate_limit(
    "face_enrollment", "face_enrollment_requests_per_minute_per_ip"
)
face_review_photo_rate_limit = face_request_rate_limit(
    "face_review_photo", "face_review_photo_requests_per_minute_per_ip"
)
punch_rate_limit = face_request_rate_limit("punch", "punch_requests_per_minute_per_ip")
