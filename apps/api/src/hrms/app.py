from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from hrms.core.config.settings import get_settings
from hrms.core.db.session import dispose_engine, get_engine
from hrms.core.errors.handlers import register_exception_handlers
from hrms.core.observability.logging import configure_logging
from hrms.core.tenancy.middleware import TenancyMiddleware
from hrms.modules.health.router import router as health_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    get_engine(settings)
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging()

    app = FastAPI(
        title="HRMS API",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/v1/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.is_development else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(TenancyMiddleware)

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

    app.include_router(health_router)
    app.include_router(identity_router, prefix="/v1")
    app.include_router(organisation_router, prefix="/v1")
    app.include_router(employee_router, prefix="/v1")
    app.include_router(employee_import_router, prefix="/v1")
    app.include_router(attendance_router, prefix="/v1")
    app.include_router(leave_router, prefix="/v1")
    app.include_router(onboarding_router, prefix="/v1")
    app.include_router(onboarding_public_router, prefix="/v1")
    app.include_router(account_invite_router, prefix="/v1")
    app.include_router(account_invite_public_router, prefix="/v1")

    return app
