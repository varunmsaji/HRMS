from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from hrms.core.tenancy.context import clear_tenant


class TenancyMiddleware(BaseHTTPMiddleware):
    """Resets the tenant contextvar around each request.

    It deliberately does NOT read `X-Company-Id`. That header is untrusted input: it used to be
    copied here into the tenant contextvar, which `get_session` then turned into the
    `app.company_id` RLS variable before the caller was authenticated, and which `email_log`
    attribution read as if it were verified. The tenant is now established only from the signed
    token (`get_current_user`) and confirmed against the membership row and the header
    (`get_tenant_context`, which also rejects a header naming a different company).

    The request id (`X-Request-Id`) is resolved by the outermost `RequestContextMiddleware`
    (LOG-01); this layer only clears the tenant that a dependency may set for the request."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        try:
            return await call_next(request)
        finally:
            clear_tenant()
