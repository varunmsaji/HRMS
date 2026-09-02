"""FastAPI `Depends()` wiring for the onboarding module's services."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.config.settings import get_settings
from hrms.core.db.session import get_session
from hrms.modules.onboarding.service import OnboardingCaseService


def get_onboarding_case_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OnboardingCaseService:
    return OnboardingCaseService(session, get_settings())
