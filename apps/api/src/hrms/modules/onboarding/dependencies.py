"""FastAPI `Depends()` wiring for the onboarding module's services."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.config.settings import get_settings
from hrms.core.db.session import get_session
from hrms.modules.onboarding.service import (
    OnboardingCaseService,
    OnboardingDocumentService,
    OnboardingTokenContext,
    OnboardingTokenService,
)


def get_onboarding_case_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OnboardingCaseService:
    return OnboardingCaseService(session, get_settings())


def get_onboarding_document_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OnboardingDocumentService:
    return OnboardingDocumentService(session, get_settings())


def get_onboarding_token_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OnboardingTokenService:
    return OnboardingTokenService(session, get_settings())


async def get_onboarding_case_from_token(
    token: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OnboardingTokenContext:
    """The security boundary for every public onboarding route (plan §5) — resolves and
    validates the raw path-parameter token, sets the RLS `company_id` GUC from it, and returns
    only the two IDs a route needs. Deliberately does not go through `get_onboarding_token_service`
    (that factory exists for the future authenticated send-invite route, O3) — this dependency has
    no `AuthenticatedUser`/`TenantContext` to build on, so it constructs the service directly,
    mirroring `core.tenancy.dependencies.get_tenant_context`'s own shape for the JWT-authenticated
    case."""
    service = OnboardingTokenService(session, get_settings())
    return await service.resolve_and_touch(token)
