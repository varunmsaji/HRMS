from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.auth.company_access import assert_request_allowed
from hrms.core.auth.jwt import decode_access_token
from hrms.core.auth.types import AuthenticatedUser
from hrms.core.db.repositories.identity import IdentityRepository
from hrms.core.db.session import get_session
from hrms.core.errors.auth import InvalidTokenError, UnauthorizedError
from hrms.core.observability.security_events import security_event

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> AuthenticatedUser:
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError("Authentication required")
    payload = decode_access_token(credentials.credentials)
    # A correctly signed token is only ever minted by `create_access_token`, so a missing or
    # non-UUID claim means a token from an older/foreign issuer or a leaked-secret forgery — either
    # way a 401, never an unhandled KeyError/ValueError surfacing as a 500.
    try:
        user_id = UUID(payload["sub"])
        company_id = UUID(payload["company_id"])
        session_id = UUID(payload["session_id"])
        employee_id = UUID(payload["employee_id"]) if payload.get("employee_id") else None
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        # A *correctly signed* token with bad claims: foreign issuer or a leaked secret.
        security_event("access_token.rejected", level="warning", reason="malformed_claims")
        raise InvalidTokenError("Access token is invalid or expired") from exc

    repo = IdentityRepository()
    user = await repo.get_user_by_id(session, user_id)
    # LOG-07 — a validly signed, unexpired token refused because of server-side state. An
    # expired or badly signed token is routine and visible as a 401 in `http_request`; these
    # are the cases where an account, session or membership was ended while a token was live.
    if user is None or user.status != "ACTIVE" or user.deleted_at is not None:
        _access_rejected("inactive_account", user_id, company_id)
        raise InvalidTokenError("User is not active")

    db_session = await repo.get_session_by_id(session, session_id)
    if db_session is None or db_session.revoked_at is not None:
        _access_rejected("session_revoked", user_id, company_id)
        raise InvalidTokenError("Session is no longer valid")

    membership = await repo.get_user_company(session, user_id=user_id, company_id=company_id)
    if membership is None or membership.status != "ACTIVE":
        _access_rejected("membership_invalid", user_id, company_id)
        raise InvalidTokenError("Company membership is not valid")

    # Company lifecycle (platform console): evaluated on every request, so suspending, rejecting
    # or terminating a company takes effect immediately instead of when this token expires.
    company = await repo.get_company_by_id(session, company_id)
    if company is None:
        _access_rejected("company_missing", user_id, company_id)
        raise InvalidTokenError("Company membership is not valid")
    assert_request_allowed(company.status, method=request.method, path=request.url.path)

    return AuthenticatedUser(
        user_id=user_id,
        company_id=company_id,
        session_id=session_id,
        employee_id=employee_id,
    )


def _access_rejected(reason: str, user_id: UUID, company_id: UUID) -> None:
    security_event(
        "access_token.rejected",
        reason=reason,
        user_id=str(user_id),
        company_id=str(company_id),
    )


async def get_optional_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> AuthenticatedUser | None:
    if credentials is None or not credentials.credentials:
        return None
    try:
        return await get_current_user(request, credentials, session)
    except UnauthorizedError:
        return None
