from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.auth.dependencies import get_current_user
from hrms.core.auth.types import AuthenticatedUser
from hrms.core.db.repositories.identity import IdentityRepository
from hrms.core.db.session import get_session
from hrms.core.errors.base import NotFoundError
from hrms.core.tenancy.context import TenantContext, set_tenant


async def get_tenant_context(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
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
    return ctx
