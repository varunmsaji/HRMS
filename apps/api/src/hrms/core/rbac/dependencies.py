from collections.abc import Callable
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.auth.dependencies import get_current_user
from hrms.core.auth.types import AuthenticatedUser
from hrms.core.db.session import get_session
from hrms.core.errors.base import PermissionDeniedError
from hrms.core.rbac.service import RbacService
from hrms.core.rbac.types import DataScope, DataScopeLevel


def get_rbac_service(session: Annotated[AsyncSession, Depends(get_session)]) -> RbacService:
    return RbacService(session)


async def _check_permission(
    code: str,
    user: AuthenticatedUser,
    rbac: RbacService,
) -> DataScope:
    if not await rbac.has_permission(user.user_id, user.company_id, code):
        raise PermissionDeniedError(
            f"Permission {code} is required",
            code="PERMISSION_DENIED",
        )
    return DataScope(level=DataScopeLevel.COMPANY)


def require_permission(code: str) -> Callable[..., object]:
    async def dependency(
        user: Annotated[AuthenticatedUser, Depends(get_current_user)],
        rbac: Annotated[RbacService, Depends(get_rbac_service)],
    ) -> DataScope:
        return await _check_permission(code, user, rbac)

    return dependency
