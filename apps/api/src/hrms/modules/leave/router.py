"""HTTP routes for the Leave module — thin layer only, per Module Standard §2.

L1 only: leave types + leave policy identity/version CRUD. All routes are COMPANY-scoped and
gated by `LEAVE.TYPE_MANAGE`/`LEAVE.POLICY_MANAGE` — config screens, no self-service, mirroring
Attendance's own `.POLICY_MANAGE` posture (architecture §23.2: "Employee self-service never
manages policies")."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, status

from hrms.core.rbac.dependencies import require_permission
from hrms.core.tenancy.context import TenantContext, current_request_id
from hrms.core.tenancy.dependencies import get_tenant_context
from hrms.modules.identity.schemas import build_meta
from hrms.modules.leave.dependencies import get_leave_policy_service, get_leave_type_service
from hrms.modules.leave.permissions import LEAVE_POLICY_MANAGE, LEAVE_TYPE_MANAGE
from hrms.modules.leave.schemas import (
    LeavePolicyCreate,
    LeavePolicyRead,
    LeavePolicyUpdate,
    LeavePolicyVersionCreate,
    LeavePolicyVersionPublishRequest,
    LeavePolicyVersionRead,
    LeavePolicyVersionUpdate,
    LeaveTypeCreate,
    LeaveTypeRead,
    LeaveTypeUpdate,
)
from hrms.modules.leave.service import LeavePolicyService, LeaveTypeService
from hrms.shared.pagination import DataEnvelope, ListEnvelope

router = APIRouter(tags=["leave"])


# ---------------------------------------------------------------------------
# Leave Types
# ---------------------------------------------------------------------------


@router.get("/leave-types", status_code=status.HTTP_200_OK)
async def list_leave_types(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(LEAVE_TYPE_MANAGE))],
    service: Annotated[LeaveTypeService, Depends(get_leave_type_service)],
) -> ListEnvelope[LeaveTypeRead]:
    data = await service.list(tenant.company_id)
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/leave-types", status_code=status.HTTP_201_CREATED)
async def create_leave_type(
    body: LeaveTypeCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(LEAVE_TYPE_MANAGE))],
    service: Annotated[LeaveTypeService, Depends(get_leave_type_service)],
) -> DataEnvelope[LeaveTypeRead]:
    data = await service.create(
        tenant.company_id,
        body,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/leave-types/{leave_type_id}", status_code=status.HTTP_200_OK)
async def get_leave_type(
    leave_type_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(LEAVE_TYPE_MANAGE))],
    service: Annotated[LeaveTypeService, Depends(get_leave_type_service)],
) -> DataEnvelope[LeaveTypeRead]:
    data = await service.get(tenant.company_id, leave_type_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.patch("/leave-types/{leave_type_id}", status_code=status.HTTP_200_OK)
async def update_leave_type(
    leave_type_id: UUID,
    body: LeaveTypeUpdate,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(LEAVE_TYPE_MANAGE))],
    service: Annotated[LeaveTypeService, Depends(get_leave_type_service)],
) -> DataEnvelope[LeaveTypeRead]:
    data = await service.update(
        tenant.company_id,
        leave_type_id,
        body,
        expected_version=int(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


# ---------------------------------------------------------------------------
# Leave Policies
# ---------------------------------------------------------------------------


@router.get("/leave-policies", status_code=status.HTTP_200_OK)
async def list_leave_policies(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(LEAVE_POLICY_MANAGE))],
    service: Annotated[LeavePolicyService, Depends(get_leave_policy_service)],
) -> ListEnvelope[LeavePolicyRead]:
    data = await service.list_policies(tenant.company_id)
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/leave-policies", status_code=status.HTTP_201_CREATED)
async def create_leave_policy(
    body: LeavePolicyCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(LEAVE_POLICY_MANAGE))],
    service: Annotated[LeavePolicyService, Depends(get_leave_policy_service)],
) -> DataEnvelope[LeavePolicyRead]:
    data = await service.create_policy(
        tenant.company_id,
        body,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/leave-policies/{policy_id}", status_code=status.HTTP_200_OK)
async def get_leave_policy(
    policy_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(LEAVE_POLICY_MANAGE))],
    service: Annotated[LeavePolicyService, Depends(get_leave_policy_service)],
) -> DataEnvelope[LeavePolicyRead]:
    data = await service.get_policy(tenant.company_id, policy_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.patch("/leave-policies/{policy_id}", status_code=status.HTTP_200_OK)
async def update_leave_policy(
    policy_id: UUID,
    body: LeavePolicyUpdate,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(LEAVE_POLICY_MANAGE))],
    service: Annotated[LeavePolicyService, Depends(get_leave_policy_service)],
) -> DataEnvelope[LeavePolicyRead]:
    data = await service.update_policy(
        tenant.company_id,
        policy_id,
        body,
        expected_version=int(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/leave-policies/{policy_id}/versions", status_code=status.HTTP_200_OK)
async def list_leave_policy_versions(
    policy_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(LEAVE_POLICY_MANAGE))],
    service: Annotated[LeavePolicyService, Depends(get_leave_policy_service)],
) -> ListEnvelope[LeavePolicyVersionRead]:
    data = await service.list_versions(tenant.company_id, policy_id)
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/leave-policies/{policy_id}/versions", status_code=status.HTTP_201_CREATED)
async def create_leave_policy_version(
    policy_id: UUID,
    body: LeavePolicyVersionCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(LEAVE_POLICY_MANAGE))],
    service: Annotated[LeavePolicyService, Depends(get_leave_policy_service)],
) -> DataEnvelope[LeavePolicyVersionRead]:
    data = await service.create_version(
        tenant.company_id,
        policy_id,
        body,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/leave-policies/{policy_id}/versions/resolve", status_code=status.HTTP_200_OK)
async def resolve_leave_policy_version(
    policy_id: UUID,
    as_of: Annotated[date, Query()],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(LEAVE_POLICY_MANAGE))],
    service: Annotated[LeavePolicyService, Depends(get_leave_policy_service)],
) -> DataEnvelope[LeavePolicyVersionRead]:
    """Registered ahead of `{version_id}` — a literal path segment must be matched before the
    parameterized route (mirrors `/attendance-policies/{id}/versions/resolve`)."""
    data = await service.resolve_version_as_of(tenant.company_id, policy_id, as_of)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/leave-policies/{policy_id}/versions/{version_id}", status_code=status.HTTP_200_OK)
async def get_leave_policy_version(
    policy_id: UUID,
    version_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(LEAVE_POLICY_MANAGE))],
    service: Annotated[LeavePolicyService, Depends(get_leave_policy_service)],
) -> DataEnvelope[LeavePolicyVersionRead]:
    data = await service.get_version(tenant.company_id, policy_id, version_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.patch("/leave-policies/{policy_id}/versions/{version_id}", status_code=status.HTTP_200_OK)
async def update_leave_policy_version(
    policy_id: UUID,
    version_id: UUID,
    body: LeavePolicyVersionUpdate,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(LEAVE_POLICY_MANAGE))],
    service: Annotated[LeavePolicyService, Depends(get_leave_policy_service)],
) -> DataEnvelope[LeavePolicyVersionRead]:
    data = await service.update_version(
        tenant.company_id,
        policy_id,
        version_id,
        body,
        expected_version=int(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.delete("/leave-policies/{policy_id}/versions/{version_id}", status_code=status.HTTP_200_OK)
async def discard_leave_policy_version(
    policy_id: UUID,
    version_id: UUID,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(LEAVE_POLICY_MANAGE))],
    service: Annotated[LeavePolicyService, Depends(get_leave_policy_service)],
) -> DataEnvelope[LeavePolicyVersionRead]:
    data = await service.discard_version(
        tenant.company_id,
        policy_id,
        version_id,
        expected_version=int(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post(
    "/leave-policies/{policy_id}/versions/{version_id}/publish",
    status_code=status.HTTP_200_OK,
)
async def publish_leave_policy_version(
    policy_id: UUID,
    version_id: UUID,
    body: LeavePolicyVersionPublishRequest,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(LEAVE_POLICY_MANAGE))],
    service: Annotated[LeavePolicyService, Depends(get_leave_policy_service)],
) -> DataEnvelope[LeavePolicyVersionRead]:
    data = await service.publish_version(
        tenant.company_id,
        policy_id,
        version_id,
        body,
        expected_version=int(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))
