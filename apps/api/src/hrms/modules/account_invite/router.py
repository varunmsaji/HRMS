"""Authenticated HTTP routes for the account-invite module — issuing invites and assigning roles.
The public accept-side routes live in `account_invite.public_router`, same split as onboarding's
`router.py`/`public_router.py`."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from hrms.core.rbac.dependencies import require_permission
from hrms.core.rbac.types import DataScope
from hrms.core.tenancy.context import TenantContext, current_request_id
from hrms.core.tenancy.dependencies import get_tenant_context
from hrms.modules.account_invite.dependencies import get_account_invite_service
from hrms.modules.account_invite.schemas import (
    AccountInviteRead,
    RoleAssignmentRequest,
    UserInviteRequest,
    UserSummary,
)
from hrms.modules.account_invite.service import AccountInviteService
from hrms.modules.employee.permissions import EMPLOYEE_INVITE
from hrms.modules.identity.permissions import SETTINGS_ROLE_MANAGE, SETTINGS_USER_MANAGE
from hrms.modules.identity.schemas import build_meta
from hrms.shared.pagination import (
    DataEnvelope,
    ListEnvelope,
    PageParams,
    build_pagination_meta,
    pagination_params,
)

router = APIRouter(tags=["account-invite"])


@router.post("/employees/{employee_id}/invite", status_code=status.HTTP_201_CREATED)
async def invite_employee(
    employee_id: UUID,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_INVITE))],
    service: Annotated[AccountInviteService, Depends(get_account_invite_service)],
) -> DataEnvelope[AccountInviteRead]:
    data = await service.issue_for_employee(
        tenant.company_id,
        employee_id,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/users", status_code=status.HTTP_200_OK)
async def list_users(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[DataScope, Depends(require_permission(SETTINGS_USER_MANAGE))],
    service: Annotated[AccountInviteService, Depends(get_account_invite_service)],
    page: Annotated[PageParams, Depends(pagination_params)],
) -> ListEnvelope[UserSummary]:
    data, total = await service.list_users(tenant.company_id, page=page)
    return ListEnvelope(
        data=data,
        pagination=build_pagination_meta(page, total=total),
        meta=build_meta(current_request_id() or "unknown"),
    )


@router.post("/users/invite", status_code=status.HTTP_201_CREATED)
async def invite_user(
    body: UserInviteRequest,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[DataScope, Depends(require_permission(SETTINGS_USER_MANAGE))],
    service: Annotated[AccountInviteService, Depends(get_account_invite_service)],
) -> DataEnvelope[AccountInviteRead]:
    data = await service.issue_for_user(
        tenant.company_id,
        body,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.patch("/users/{user_id}/roles", status_code=status.HTTP_200_OK)
async def assign_user_roles(
    user_id: UUID,
    body: RoleAssignmentRequest,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[DataScope, Depends(require_permission(SETTINGS_ROLE_MANAGE))],
    service: Annotated[AccountInviteService, Depends(get_account_invite_service)],
) -> DataEnvelope[dict[str, list[str]]]:
    role_codes = await service.assign_roles(
        tenant.company_id,
        user_id,
        body,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(
        data={"role_codes": role_codes}, meta=build_meta(current_request_id() or "unknown")
    )
