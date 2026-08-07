import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from hrms.core.tenancy.context import TenantContext, clear_context, set_request_id, set_tenant


class TenancyMiddleware(BaseHTTPMiddleware):
    """Resolves X-Request-Id and optional X-Company-Id into contextvars (Document 07 §5)."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        set_request_id(request_id)

        company_header = request.headers.get("X-Company-Id")
        if company_header:
            try:
                set_tenant(TenantContext(company_id=uuid.UUID(company_header)))
            except ValueError:
                pass

        try:
            response = await call_next(request)
        finally:
            clear_context()

        response.headers["X-Request-Id"] = request_id
        return response
