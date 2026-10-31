from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.auth.dependencies import get_current_user
from hrms.core.auth.types import AuthenticatedUser
from hrms.core.db.repositories.identity import IdentityRepository
from hrms.core.db.session import get_session, set_rls_company_id
from hrms.core.errors.base import NotFoundError
from hrms.core.observability.security_events import security_event
from hrms.core.tenancy.context import TenantContext, set_tenant


def _parse_company_header(value: str) -> UUID | None:
    """The header as a UUID, or `None` when it is not one. Compared as UUID values, so the same
    company written in another case (or without hyphens) is the same company; anything that does
    not parse can never match a token's company and is rejected like a mismatch."""
    try:
        return UUID(value)
    except ValueError:
        return None


async def get_tenant_context(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
    x_company_id: Annotated[str | None, Header(alias="X-Company-Id")] = None,
) -> TenantContext:
    if x_company_id is not None and _parse_company_header(x_company_id) != user.company_id:
        # LOG-07 — an authenticated caller naming a company other than the one its token is
        # bound to (or sending something that is not a UUID at all). The requested value is
        # attacker-controlled, so it is not logged.
        security_event(
            "tenant.rejected",
            level="warning",
            reason="company_header_mismatch",
            user_id=str(user.user_id),
            company_id=str(user.company_id),
        )
        raise NotFoundError("Resource not found")

    repo = IdentityRepository()
    membership = await repo.get_user_company(
        session, user_id=user.user_id, company_id=user.company_id
    )
    if membership is None:
        security_event(
            "tenant.rejected",
            level="warning",
            reason="no_membership",
            user_id=str(user.user_id),
            company_id=str(user.company_id),
        )
        raise NotFoundError("Resource not found")

    ctx = TenantContext(company_id=user.company_id, user_id=user.user_id)
    set_tenant(ctx)
    # `get_current_user` already set the RLS GUC from the signed token claim; set it again here
    # from the now fully verified company id (the header, if any, matched it above), because the
    # session may have committed since, and the tenant ContextVar is only populated from this
    # point on.
    await set_rls_company_id(session, str(ctx.company_id))
    return ctx
