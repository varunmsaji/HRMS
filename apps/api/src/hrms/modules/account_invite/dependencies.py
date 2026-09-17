"""FastAPI `Depends()` wiring for the account-invite module's service."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.config.settings import get_settings
from hrms.core.db.session import get_session
from hrms.modules.account_invite.service import AccountInviteService


def get_account_invite_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AccountInviteService:
    return AccountInviteService(session, get_settings())
