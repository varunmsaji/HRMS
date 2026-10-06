"""FastAPI `Depends()` wiring for the organisation module's services."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.config.settings import get_settings
from hrms.core.db.session import get_session
from hrms.modules.organisation.service import OrganisationService


def get_organisation_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> OrganisationService:
    return OrganisationService(session, get_settings())
