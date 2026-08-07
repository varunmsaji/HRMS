from typing import Annotated
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.auth.jwt import decode_access_token
from hrms.core.auth.types import AuthenticatedUser
from hrms.core.db.repositories.identity import IdentityRepository
from hrms.core.db.session import get_session
from hrms.core.errors.auth import InvalidTokenError, UnauthorizedError

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AuthenticatedUser:
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError("Authentication required")
    payload = decode_access_token(credentials.credentials)
    user_id = UUID(payload["sub"])
    company_id = UUID(payload["company_id"])
    session_id = UUID(payload["session_id"])
    employee_id = UUID(payload["employee_id"]) if payload.get("employee_id") else None

    repo = IdentityRepository()
    user = await repo.get_user_by_id(session, user_id)
    if user is None or user.status != "ACTIVE" or user.deleted_at is not None:
        raise InvalidTokenError("User is not active")

    db_session = await repo.get_session_by_id(session, session_id)
    if db_session is None or db_session.revoked_at is not None:
        raise InvalidTokenError("Session is no longer valid")

    membership = await repo.get_user_company(session, user_id=user_id, company_id=company_id)
    if membership is None or membership.status != "ACTIVE":
        raise InvalidTokenError("Company membership is not valid")

    return AuthenticatedUser(
        user_id=user_id,
        company_id=company_id,
        session_id=session_id,
        employee_id=employee_id,
    )


async def get_optional_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AuthenticatedUser | None:
    if credentials is None or not credentials.credentials:
        return None
    try:
        return await get_current_user(credentials, session)
    except UnauthorizedError:
        return None
