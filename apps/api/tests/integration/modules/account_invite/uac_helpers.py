"""Shared helpers for the user-creation / access-control hardening suites in this directory
(`test_user_access_control.py`, `test_invite_accept_hardening.py`, `test_session_lifecycle.py`).
Built on the existing `test_account_invite.py` helpers (register tenant, teardown) rather than
replacing them: every user here is created through the real invite → accept flow, so the role
seeds and permission grants under test are the production ones, not hand-built fixtures."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import redis.asyncio as redis
from httpx import AsyncClient
from sqlalchemy import select, text

from hrms.core.config.settings import get_settings
from hrms.core.db.models.identity import User
from hrms.core.db.session import get_session_factory

from ..organisation.test_registration_flow import VALID_PASSWORD
from .test_account_invite import (
    _cleanup_extra_user_row,
    _cleanup_extra_user_sessions,
    _extra_user_id,
    _register_tenant,
    _teardown,
    _token_from_invite_url,
)

__all__ = [
    "VALID_PASSWORD",
    "Onboarded",
    "Tenant",
    "onboard",
    "register_tenant",
    "reset_auth_rate_limit",
    "set_sql",
    "teardown",
    "teardown_all",
    "user_id_for",
]

ALL_ROLES = ("COMPANY_ADMIN", "HR_ADMIN", "REPORTING_MANAGER", "BRANCH_MANAGER", "EMPLOYEE")


@dataclass
class Tenant:
    headers: dict[str, str]
    company_id: UUID
    admin_user_id: UUID | None
    emails: list[str]


@dataclass
class Onboarded:
    email: str
    user_id: UUID
    headers: dict[str, str]
    password: str
    role_code: str


async def register_tenant(client: AsyncClient) -> Tenant:
    headers, company_id, user_id = await _register_tenant(client)
    return Tenant(headers=headers, company_id=company_id, admin_user_id=user_id, emails=[])


async def teardown(tenant: Tenant) -> None:
    await _teardown(
        company_id=tenant.company_id, user_id=tenant.admin_user_id, extra_emails=tenant.emails
    )


async def user_id_for(email: str) -> UUID:
    factory = get_session_factory()
    async with factory() as session:
        return (await session.execute(select(User.id).where(User.email == email))).scalar_one()


async def onboard(
    client: AsyncClient,
    tenant: Tenant,
    role_code: str,
    *,
    password: str = VALID_PASSWORD,
    email: str | None = None,
) -> Onboarded:
    """Invite + accept through the public API. Registers the email on `tenant` so `teardown`
    removes the user row."""
    email = email or f"{role_code.lower()}-{uuid4().hex[:8]}@example.com"
    tenant.emails.append(email)
    invite = await client.post(
        "/v1/users/invite",
        headers=tenant.headers,
        json={"email": email, "role_code": role_code},
    )
    assert invite.status_code == 201, invite.text
    token = _token_from_invite_url(invite.json()["data"]["invite_url"])
    accept = await client.post(
        f"/v1/public/account-invites/{token}/accept", json={"password": password}
    )
    assert accept.status_code == 201, accept.text
    access = accept.json()["data"]["access_token"]
    return Onboarded(
        email=email,
        user_id=await user_id_for(email),
        headers={"Authorization": f"Bearer {access}", "X-Company-Id": str(tenant.company_id)},
        password=password,
        role_code=role_code,
    )


async def set_sql(statement: str, **params: Any) -> None:
    """Raw write used to put a user into a state no public endpoint can reach yet
    (deactivated, locked, soft-deleted) — there is no user-deactivation endpoint today."""
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(text(statement), {k: str(v) for k, v in params.items()})
        await session.commit()


async def teardown_all(*tenants: Tenant) -> None:
    """Teardown for tests where one `User` belongs to several tenants: `_teardown` per tenant
    would try to delete the shared `User` row while another tenant still references it. Sessions
    first (they FK to `company`), then each tenant's graph, then the user rows."""
    emails = [e for t in tenants for e in t.emails]
    user_ids = []
    for email in dict.fromkeys(emails):
        uid = await _extra_user_id(email=email)
        if uid:
            user_ids.append(uid)
    for uid in user_ids:
        await _cleanup_extra_user_sessions(user_id=uid)
    for t in tenants:
        await _teardown(company_id=t.company_id, user_id=t.admin_user_id, extra_emails=[])
    for uid in user_ids:
        await _cleanup_extra_user_row(user_id=uid)


async def reset_auth_rate_limit() -> None:
    """The public accept route shares the 10/min `auth` bucket; loops that probe many bodies
    must clear it between probes or they test the limiter instead of the validation."""
    client = redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        async for key in client.scan_iter(match="ratelimit:auth:*"):
            await client.delete(key)
    finally:
        await client.aclose()
