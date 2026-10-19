"""Platform-admin tokens and the FastAPI dependency that authenticates them.

A platform token is a JWT with `type: "platform"` and `aud: "platform"`. Tenant access tokens carry
`type: "access"`, and `decode_access_token` rejects anything else, so neither token kind is
accepted by the other side's dependency. The session row is checked on every request (revocation
and expiry take effect immediately)."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.config.settings import Settings, get_settings
from hrms.core.db.session import get_session
from hrms.core.errors.auth import InvalidTokenError, UnauthorizedError
from hrms.modules.platform.repository import PlatformRepository

_bearer = HTTPBearer(auto_error=False)
_AUDIENCE = "platform"


@dataclass(frozen=True)
class PlatformPrincipal:
    admin_id: UUID
    username: str
    session_id: UUID


def create_platform_token(
    *, admin_id: UUID, session_id: UUID, settings: Settings | None = None
) -> tuple[str, datetime]:
    cfg = settings or get_settings()
    now = datetime.now(UTC)
    expires = now + timedelta(minutes=cfg.platform_access_ttl_minutes)
    token = jwt.encode(
        {
            "sub": str(admin_id),
            "session_id": str(session_id),
            "type": "platform",
            "aud": _AUDIENCE,
            "iat": now,
            "exp": expires,
        },
        cfg.jwt_access_secret,
        algorithm="HS256",
    )
    return token, expires


def _decode(token: str, settings: Settings) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token, settings.jwt_access_secret, algorithms=["HS256"], audience=_AUDIENCE
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError("Access token is invalid or expired") from exc
    if payload.get("type") != "platform":
        raise InvalidTokenError("Invalid token type")
    return payload


async def get_current_platform_admin(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> PlatformPrincipal:
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError("Authentication required")
    payload = _decode(credentials.credentials, get_settings())
    try:
        admin_id = UUID(payload["sub"])
        session_id = UUID(payload["session_id"])
    except (KeyError, ValueError, TypeError) as exc:
        raise InvalidTokenError("Access token is invalid or expired") from exc

    repo = PlatformRepository()
    admin = await repo.get_admin(session, admin_id)
    if admin is None or admin.status != "ACTIVE":
        raise InvalidTokenError("Account is not active")
    record = await repo.get_session(session, session_id)
    now = datetime.now(UTC)
    if (
        record is None
        or record.platform_admin_id != admin_id
        or record.revoked_at is not None
        or record.expires_at <= now
    ):
        raise InvalidTokenError("Session is no longer valid")
    return PlatformPrincipal(admin_id=admin.id, username=admin.username, session_id=record.id)
