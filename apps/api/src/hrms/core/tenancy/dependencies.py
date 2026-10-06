from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.auth.dependencies import get_current_user
from hrms.core.auth.types import AuthenticatedUser
from hrms.core.db.repositories.identity import IdentityRepository
from hrms.core.db.session import get_session, set_rls_company_id
from hrms.core.errors.base import NotFoundError
from hrms.core.tenancy.context import TenantContext, set_tenant


async def get_tenant_context(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
    x_company_id: Annotated[str | None, Header(alias="X-Company-Id")] = None,
) -> TenantContext:
    if x_company_id is not None and x_company_id != str(user.company_id):
        raise NotFoundError("Resource not found")

    repo = IdentityRepository()
    membership = await repo.get_user_company(
        session, user_id=user.user_id, company_id=user.company_id
    )
    if membership is None:
        raise NotFoundError("Resource not found")

    ctx = TenantContext(company_id=user.company_id, user_id=user.user_id)
    set_tenant(ctx)
    # `get_session()` (this function's own `session` dependency) already tried to set the RLS GUC,
    # but it read the tenant ContextVar *before* membership was verified above — from whatever
    # TenancyMiddleware set from the raw header (or nothing, if the header was omitted). Set it
    # again here, explicitly, from the now-verified company id, so every query issued after this
    # dependency resolves — which is every route in the app — is guaranteed correct regardless of
    # what the GUC held a moment ago.
    await set_rls_company_id(session, str(ctx.company_id))
    return ctx
