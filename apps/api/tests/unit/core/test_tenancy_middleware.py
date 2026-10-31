"""`TenancyMiddleware` must not turn the untrusted `X-Company-Id` header into tenant context
(P1 verification V-4a / V-4c)."""

from uuid import uuid4

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from hrms.core.tenancy.context import TenantContext, current_tenant_company_id, set_tenant
from hrms.core.tenancy.middleware import TenancyMiddleware


def _app() -> Starlette:
    async def seen(_: Request) -> JSONResponse:
        return JSONResponse({"tenant": current_tenant_company_id()})

    async def verified(_: Request) -> JSONResponse:
        set_tenant(TenantContext(company_id=uuid4(), user_id=uuid4()))  # what a dependency does
        return JSONResponse({"tenant": current_tenant_company_id()})

    app = Starlette(routes=[Route("/seen", seen), Route("/verified", verified)])
    app.add_middleware(TenancyMiddleware)
    return app


def test_raw_company_header_never_reaches_the_tenant_context() -> None:
    with TestClient(_app()) as client:
        for value in (str(uuid4()), "not-a-uuid", ""):
            assert client.get("/seen", headers={"X-Company-Id": value}).json() == {"tenant": None}


def test_a_dependency_set_tenant_is_visible_to_the_request_and_cleared_afterwards() -> None:
    with TestClient(_app()) as client:
        assert client.get("/verified").json()["tenant"] is not None
        assert client.get("/seen").json() == {"tenant": None}
