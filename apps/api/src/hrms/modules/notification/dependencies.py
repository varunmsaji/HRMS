from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.db.session import get_session
from hrms.modules.notification.service import NotificationService


def get_notification_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> NotificationService:
    return NotificationService(session)
