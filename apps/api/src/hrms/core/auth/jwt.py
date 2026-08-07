from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from jose import JWTError, jwt

from hrms.core.config.settings import Settings, get_settings
from hrms.core.errors.auth import InvalidTokenError


def _utcnow() -> datetime:
    return datetime.now(UTC)


def create_access_token(
    *,
    user_id: UUID,
    company_id: UUID,
    session_id: UUID,
    employee_id: UUID | None,
    settings: Settings | None = None,
    ttl_minutes: int | None = None,
) -> str:
    cfg = settings or get_settings()
    expire = _utcnow() + timedelta(minutes=ttl_minutes or cfg.jwt_access_ttl_minutes)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "company_id": str(company_id),
        "session_id": str(session_id),
        "employee_id": str(employee_id) if employee_id else None,
        "exp": expire,
        "iat": _utcnow(),
        "type": "access",
    }
    return str(jwt.encode(payload, cfg.jwt_access_secret, algorithm="HS256"))


def decode_access_token(token: str, settings: Settings | None = None) -> dict[str, Any]:
    cfg = settings or get_settings()
    try:
        payload = jwt.decode(token, cfg.jwt_access_secret, algorithms=["HS256"])
    except JWTError as exc:
        raise InvalidTokenError("Access token is invalid or expired") from exc
    if payload.get("type") != "access":
        raise InvalidTokenError("Invalid token type")
    return cast(dict[str, Any], payload)
