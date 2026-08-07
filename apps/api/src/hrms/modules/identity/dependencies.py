from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.config.settings import get_settings
from hrms.core.db.session import get_session
from hrms.modules.identity.service import IdentityService


def get_identity_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> IdentityService:
    return IdentityService(session, get_settings())
