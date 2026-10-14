import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from hrms.core.tenancy.context import TenantContext, clear_tenant, set_tenant


class TenancyMiddleware(BaseHTTPMiddleware):
    """Resolves the optional X-Company-Id header into the tenant contextvar (Document 07 §5).

    The request id (`X-Request-Id`) used to be resolved here too. It moved to the outermost
    `RequestContextMiddleware` (LOG-01): this layer cleared it in its `finally`, before Starlette's
    outermost error handler ran, so every unhandled 500 was logged and returned with request id
    `"unknown"` and no `X-Request-Id` header. This layer now clears only the tenant it set."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        company_header = request.headers.get("X-Company-Id")
        if company_header:
            try:
                set_tenant(TenantContext(company_id=uuid.UUID(company_header)))
            except ValueError:
                pass

        try:
            return await call_next(request)
        finally:
            clear_tenant()
