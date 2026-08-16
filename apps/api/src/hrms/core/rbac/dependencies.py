from collections.abc import Callable
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.auth.dependencies import get_current_user
from hrms.core.auth.types import AuthenticatedUser
from hrms.core.db.session import get_session
from hrms.core.errors.base import PermissionDeniedError
from hrms.core.rbac.service import RbacService
from hrms.core.rbac.types import DataScope


def get_rbac_service(session: Annotated[AsyncSession, Depends(get_session)]) -> RbacService:
    return RbacService(session)


async def _check_permission(
    code: str,
    user: AuthenticatedUser,
    rbac: RbacService,
) -> DataScope:
    # One query does both jobs: `resolve_data_scope` already filters on `code`, so a returned
    # row *is* proof the permission is held (holding `code` and having zero rows for it are the
    # same condition) — checking `has_permission` first, then `resolve_data_scope` again, would
    # be two round trips for every permission-gated route in the app for no extra correctness.
    scope = await rbac.resolve_data_scope(user.user_id, user.company_id, code)
    if not scope.levels:
        raise PermissionDeniedError(
            f"Permission {code} is required",
            code="PERMISSION_DENIED",
        )
    return scope


def require_permission(code: str) -> Callable[..., object]:
    async def dependency(
        user: Annotated[AuthenticatedUser, Depends(get_current_user)],
        rbac: Annotated[RbacService, Depends(get_rbac_service)],
    ) -> DataScope:
        return await _check_permission(code, user, rbac)

    return dependency
