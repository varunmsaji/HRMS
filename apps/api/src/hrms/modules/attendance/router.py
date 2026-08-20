"""HTTP routes for the attendance module — thin layer only, per Module Standard §2.

Three policy families (Attendance/Overtime/Regularization) share an identical CRUD/versioning
route shape, mirroring `/shifts/{id}/versions*` (W2). All routes are COMPANY-scoped and gated by
`ATTENDANCE.POLICY_MANAGE` — config screens, no self-service (architecture §23.2).

W4 adds the operational routes (punches, attendance days, recompute) at the bottom of this file.
Every GET/list route there resolves the caller's `DataScope` and passes it to the service
(`ATTENDANCE.VIEW`/`ATTENDANCE.VIEW_ALL`), mirroring the F4/F8/F9 pattern already established in
`employee/router.py` — an out-of-scope target is a 404, identical in shape to a nonexistent or
cross-tenant id, never 403. `POST /attendance/punches`'s gating permission depends on whether the
caller is punching for themselves or on behalf of someone else, so — like
`employee/router.py::create_assignment` — it cannot be a static `Depends(require_permission(CODE))`
and instead calls `rbac.resolve_data_scope()` directly."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, status

from hrms.core.auth.dependencies import get_current_user
from hrms.core.auth.types import AuthenticatedUser
from hrms.core.errors.base import PermissionDeniedError, ValidationError
from hrms.core.rbac.dependencies import get_rbac_service, require_permission
from hrms.core.rbac.service import RbacService
from hrms.core.rbac.types import DataScope
from hrms.core.tenancy.context import TenantContext, current_request_id
from hrms.core.tenancy.dependencies import get_tenant_context
from hrms.modules.attendance.dependencies import (
    get_attendance_day_service,
    get_attendance_service,
    get_punch_service,
    get_regularization_request_service,
    get_shift_roster_service,
)
from hrms.modules.attendance.permissions import (
    ATTENDANCE_POLICY_MANAGE,
    ATTENDANCE_PUNCH,
    ATTENDANCE_PUNCH_ON_BEHALF,
    ATTENDANCE_RECOMPUTE,
    ATTENDANCE_REGULARIZATION_APPROVE,
    ATTENDANCE_REGULARIZATION_REQUEST,
    ATTENDANCE_REGULARIZATION_REQUEST_ON_BEHALF,
    ATTENDANCE_ROSTER_MANAGE,
    ATTENDANCE_VIEW,
    ATTENDANCE_VIEW_ALL,
)
from hrms.modules.attendance.schemas import (
    AttendanceDayRead,
    AttendancePolicyCreate,
    AttendancePolicyRead,
    AttendancePolicyUpdate,
    AttendancePolicyVersionCreate,
    AttendancePolicyVersionPublishRequest,
    AttendancePolicyVersionRead,
    AttendancePolicyVersionUpdate,
    OvertimePolicyCreate,
    OvertimePolicyRead,
    OvertimePolicyUpdate,
    OvertimePolicyVersionCreate,
    OvertimePolicyVersionPublishRequest,
    OvertimePolicyVersionRead,
    OvertimePolicyVersionUpdate,
    PolicyResolutionRead,
    PunchCreate,
    PunchRead,
    RegularizationPolicyCreate,
    RegularizationPolicyRead,
    RegularizationPolicyUpdate,
    RegularizationPolicyVersionCreate,
    RegularizationPolicyVersionPublishRequest,
    RegularizationPolicyVersionRead,
    RegularizationPolicyVersionUpdate,
    RegularizationRequestCreate,
    RegularizationRequestRead,
    RegularizationReviewInput,
    ShiftRosterBulkCreate,
    ShiftRosterCreate,
    ShiftRosterRead,
    ShiftRosterUpdate,
)
from hrms.modules.attendance.service import (
    AttendanceDayService,
    AttendanceService,
    PunchService,
    RegularizationRequestService,
    ShiftRosterService,
)
from hrms.modules.identity.schemas import build_meta
from hrms.shared.pagination import DataEnvelope, ListEnvelope

router = APIRouter(tags=["attendance"])


# ---------------------------------------------------------------------------
# Attendance Policies
# ---------------------------------------------------------------------------


@router.get("/attendance-policies", status_code=status.HTTP_200_OK)
async def list_attendance_policies(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Annotated[AttendanceService, Depends(get_attendance_service)],
) -> ListEnvelope[AttendancePolicyRead]:
    data = await service.list_attendance_policies(tenant.company_id)
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/attendance-policies", status_code=status.HTTP_201_CREATED)
async def create_attendance_policy(
    body: AttendancePolicyCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Annotated[AttendanceService, Depends(get_attendance_service)],
) -> DataEnvelope[AttendancePolicyRead]:
    data = await service.create_attendance_policy(
        tenant.company_id,
        body,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/attendance-policies/{policy_id}", status_code=status.HTTP_200_OK)
async def get_attendance_policy(
    policy_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Annotated[AttendanceService, Depends(get_attendance_service)],
) -> DataEnvelope[AttendancePolicyRead]:
    data = await service.get_attendance_policy(tenant.company_id, policy_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.patch("/attendance-policies/{policy_id}", status_code=status.HTTP_200_OK)
async def update_attendance_policy(
    policy_id: UUID,
    body: AttendancePolicyUpdate,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Annotated[AttendanceService, Depends(get_attendance_service)],
) -> DataEnvelope[AttendancePolicyRead]:
    data = await service.update_attendance_policy(
        tenant.company_id,
        policy_id,
        body,
        expected_version=int(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/attendance-policies/{policy_id}/versions", status_code=status.HTTP_200_OK)
async def list_attendance_policy_versions(
    policy_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Annotated[AttendanceService, Depends(get_attendance_service)],
) -> ListEnvelope[AttendancePolicyVersionRead]:
    data = await service.list_attendance_policy_versions(tenant.company_id, policy_id)
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/attendance-policies/{policy_id}/versions", status_code=status.HTTP_201_CREATED)
async def create_attendance_policy_version(
    policy_id: UUID,
    body: AttendancePolicyVersionCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Annotated[AttendanceService, Depends(get_attendance_service)],
) -> DataEnvelope[AttendancePolicyVersionRead]:
    data = await service.create_attendance_policy_version(
        tenant.company_id,
        policy_id,
        body,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/attendance-policies/{policy_id}/versions/resolve", status_code=status.HTTP_200_OK)
async def resolve_attendance_policy_version(
    policy_id: UUID,
    as_of: Annotated[date, Query()],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Annotated[AttendanceService, Depends(get_attendance_service)],
) -> DataEnvelope[AttendancePolicyVersionRead]:
    """Registered ahead of `{version_id}` — a literal path segment must be matched before the
    parameterized route (mirrors `/shifts/{id}/versions/resolve`)."""
    data = await service.resolve_attendance_policy_version_as_of(
        tenant.company_id, policy_id, as_of
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get(
    "/attendance-policies/{policy_id}/versions/{version_id}", status_code=status.HTTP_200_OK
)
async def get_attendance_policy_version(
    policy_id: UUID,
    version_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Annotated[AttendanceService, Depends(get_attendance_service)],
) -> DataEnvelope[AttendancePolicyVersionRead]:
    data = await service.get_attendance_policy_version(tenant.company_id, policy_id, version_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.patch(
    "/attendance-policies/{policy_id}/versions/{version_id}", status_code=status.HTTP_200_OK
)
async def update_attendance_policy_version(
    policy_id: UUID,
    version_id: UUID,
    body: AttendancePolicyVersionUpdate,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Annotated[AttendanceService, Depends(get_attendance_service)],
) -> DataEnvelope[AttendancePolicyVersionRead]:
    data = await service.update_attendance_policy_version(
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


@router.delete(
    "/attendance-policies/{policy_id}/versions/{version_id}", status_code=status.HTTP_200_OK
)
async def discard_attendance_policy_version(
    policy_id: UUID,
    version_id: UUID,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Annotated[AttendanceService, Depends(get_attendance_service)],
) -> DataEnvelope[AttendancePolicyVersionRead]:
    data = await service.discard_attendance_policy_version(
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
    "/attendance-policies/{policy_id}/versions/{version_id}/publish",
    status_code=status.HTTP_200_OK,
)
async def publish_attendance_policy_version(
    policy_id: UUID,
    version_id: UUID,
    body: AttendancePolicyVersionPublishRequest,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Annotated[AttendanceService, Depends(get_attendance_service)],
) -> DataEnvelope[AttendancePolicyVersionRead]:
    data = await service.publish_attendance_policy_version(
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


# ---------------------------------------------------------------------------
# Overtime Policies
# ---------------------------------------------------------------------------


@router.get("/overtime-policies", status_code=status.HTTP_200_OK)
async def list_overtime_policies(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Annotated[AttendanceService, Depends(get_attendance_service)],
) -> ListEnvelope[OvertimePolicyRead]:
    data = await service.list_overtime_policies(tenant.company_id)
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/overtime-policies", status_code=status.HTTP_201_CREATED)
async def create_overtime_policy(
    body: OvertimePolicyCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Annotated[AttendanceService, Depends(get_attendance_service)],
) -> DataEnvelope[OvertimePolicyRead]:
    data = await service.create_overtime_policy(
        tenant.company_id,
        body,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/overtime-policies/{policy_id}", status_code=status.HTTP_200_OK)
async def get_overtime_policy(
    policy_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Annotated[AttendanceService, Depends(get_attendance_service)],
) -> DataEnvelope[OvertimePolicyRead]:
    data = await service.get_overtime_policy(tenant.company_id, policy_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.patch("/overtime-policies/{policy_id}", status_code=status.HTTP_200_OK)
async def update_overtime_policy(
    policy_id: UUID,
    body: OvertimePolicyUpdate,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Annotated[AttendanceService, Depends(get_attendance_service)],
) -> DataEnvelope[OvertimePolicyRead]:
    data = await service.update_overtime_policy(
        tenant.company_id,
        policy_id,
        body,
        expected_version=int(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/overtime-policies/{policy_id}/versions", status_code=status.HTTP_200_OK)
async def list_overtime_policy_versions(
    policy_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Annotated[AttendanceService, Depends(get_attendance_service)],
) -> ListEnvelope[OvertimePolicyVersionRead]:
    data = await service.list_overtime_policy_versions(tenant.company_id, policy_id)
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/overtime-policies/{policy_id}/versions", status_code=status.HTTP_201_CREATED)
async def create_overtime_policy_version(
    policy_id: UUID,
    body: OvertimePolicyVersionCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Annotated[AttendanceService, Depends(get_attendance_service)],
) -> DataEnvelope[OvertimePolicyVersionRead]:
    data = await service.create_overtime_policy_version(
        tenant.company_id,
        policy_id,
        body,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/overtime-policies/{policy_id}/versions/resolve", status_code=status.HTTP_200_OK)
async def resolve_overtime_policy_version(
    policy_id: UUID,
    as_of: Annotated[date, Query()],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Annotated[AttendanceService, Depends(get_attendance_service)],
) -> DataEnvelope[OvertimePolicyVersionRead]:
    data = await service.resolve_overtime_policy_version_as_of(tenant.company_id, policy_id, as_of)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/overtime-policies/{policy_id}/versions/{version_id}", status_code=status.HTTP_200_OK)
async def get_overtime_policy_version(
    policy_id: UUID,
    version_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Annotated[AttendanceService, Depends(get_attendance_service)],
) -> DataEnvelope[OvertimePolicyVersionRead]:
    data = await service.get_overtime_policy_version(tenant.company_id, policy_id, version_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.patch(
    "/overtime-policies/{policy_id}/versions/{version_id}", status_code=status.HTTP_200_OK
)
async def update_overtime_policy_version(
    policy_id: UUID,
    version_id: UUID,
    body: OvertimePolicyVersionUpdate,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Annotated[AttendanceService, Depends(get_attendance_service)],
) -> DataEnvelope[OvertimePolicyVersionRead]:
    data = await service.update_overtime_policy_version(
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


@router.delete(
    "/overtime-policies/{policy_id}/versions/{version_id}", status_code=status.HTTP_200_OK
)
async def discard_overtime_policy_version(
    policy_id: UUID,
    version_id: UUID,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Annotated[AttendanceService, Depends(get_attendance_service)],
) -> DataEnvelope[OvertimePolicyVersionRead]:
    data = await service.discard_overtime_policy_version(
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
    "/overtime-policies/{policy_id}/versions/{version_id}/publish", status_code=status.HTTP_200_OK
)
async def publish_overtime_policy_version(
    policy_id: UUID,
    version_id: UUID,
    body: OvertimePolicyVersionPublishRequest,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Annotated[AttendanceService, Depends(get_attendance_service)],
) -> DataEnvelope[OvertimePolicyVersionRead]:
    data = await service.publish_overtime_policy_version(
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


# ---------------------------------------------------------------------------
# Regularization Policies
# ---------------------------------------------------------------------------


@router.get("/regularization-policies", status_code=status.HTTP_200_OK)
async def list_regularization_policies(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Annotated[AttendanceService, Depends(get_attendance_service)],
) -> ListEnvelope[RegularizationPolicyRead]:
    data = await service.list_regularization_policies(tenant.company_id)
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/regularization-policies", status_code=status.HTTP_201_CREATED)
async def create_regularization_policy(
    body: RegularizationPolicyCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Annotated[AttendanceService, Depends(get_attendance_service)],
) -> DataEnvelope[RegularizationPolicyRead]:
    data = await service.create_regularization_policy(
        tenant.company_id,
        body,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/regularization-policies/{policy_id}", status_code=status.HTTP_200_OK)
async def get_regularization_policy(
    policy_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Annotated[AttendanceService, Depends(get_attendance_service)],
) -> DataEnvelope[RegularizationPolicyRead]:
    data = await service.get_regularization_policy(tenant.company_id, policy_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.patch("/regularization-policies/{policy_id}", status_code=status.HTTP_200_OK)
async def update_regularization_policy(
    policy_id: UUID,
    body: RegularizationPolicyUpdate,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Annotated[AttendanceService, Depends(get_attendance_service)],
) -> DataEnvelope[RegularizationPolicyRead]:
    data = await service.update_regularization_policy(
        tenant.company_id,
        policy_id,
        body,
        expected_version=int(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/regularization-policies/{policy_id}/versions", status_code=status.HTTP_200_OK)
async def list_regularization_policy_versions(
    policy_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Annotated[AttendanceService, Depends(get_attendance_service)],
) -> ListEnvelope[RegularizationPolicyVersionRead]:
    data = await service.list_regularization_policy_versions(tenant.company_id, policy_id)
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/regularization-policies/{policy_id}/versions", status_code=status.HTTP_201_CREATED)
async def create_regularization_policy_version(
    policy_id: UUID,
    body: RegularizationPolicyVersionCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Annotated[AttendanceService, Depends(get_attendance_service)],
) -> DataEnvelope[RegularizationPolicyVersionRead]:
    data = await service.create_regularization_policy_version(
        tenant.company_id,
        policy_id,
        body,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/regularization-policies/{policy_id}/versions/resolve", status_code=status.HTTP_200_OK)
async def resolve_regularization_policy_version(
    policy_id: UUID,
    as_of: Annotated[date, Query()],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Annotated[AttendanceService, Depends(get_attendance_service)],
) -> DataEnvelope[RegularizationPolicyVersionRead]:
    data = await service.resolve_regularization_policy_version_as_of(
        tenant.company_id, policy_id, as_of
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get(
    "/regularization-policies/{policy_id}/versions/{version_id}", status_code=status.HTTP_200_OK
)
async def get_regularization_policy_version(
    policy_id: UUID,
    version_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Annotated[AttendanceService, Depends(get_attendance_service)],
) -> DataEnvelope[RegularizationPolicyVersionRead]:
    data = await service.get_regularization_policy_version(tenant.company_id, policy_id, version_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.patch(
    "/regularization-policies/{policy_id}/versions/{version_id}", status_code=status.HTTP_200_OK
)
async def update_regularization_policy_version(
    policy_id: UUID,
    version_id: UUID,
    body: RegularizationPolicyVersionUpdate,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Annotated[AttendanceService, Depends(get_attendance_service)],
) -> DataEnvelope[RegularizationPolicyVersionRead]:
    data = await service.update_regularization_policy_version(
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


@router.delete(
    "/regularization-policies/{policy_id}/versions/{version_id}", status_code=status.HTTP_200_OK
)
async def discard_regularization_policy_version(
    policy_id: UUID,
    version_id: UUID,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Annotated[AttendanceService, Depends(get_attendance_service)],
) -> DataEnvelope[RegularizationPolicyVersionRead]:
    data = await service.discard_regularization_policy_version(
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
    "/regularization-policies/{policy_id}/versions/{version_id}/publish",
    status_code=status.HTTP_200_OK,
)
async def publish_regularization_policy_version(
    policy_id: UUID,
    version_id: UUID,
    body: RegularizationPolicyVersionPublishRequest,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Annotated[AttendanceService, Depends(get_attendance_service)],
) -> DataEnvelope[RegularizationPolicyVersionRead]:
    data = await service.publish_regularization_policy_version(
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


# ---------------------------------------------------------------------------
# Policy resolution preview (architecture §19 step 7, §35 — HR-debugging explain view)
# ---------------------------------------------------------------------------

_RESOLUTION_KINDS = ("ATTENDANCE_POLICY", "OVERTIME_POLICY", "REGULARIZATION_POLICY")


@router.get("/attendance-policy-resolution", status_code=status.HTTP_200_OK)
async def get_policy_resolution(
    employee_id: Annotated[UUID, Query()],
    date_param: Annotated[date, Query(alias="date")],
    policy_kind: Annotated[str, Query()],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Annotated[AttendanceService, Depends(get_attendance_service)],
) -> DataEnvelope[PolicyResolutionRead]:
    """Admin preview of the WD-09 precedence walk for one employee+date+policy_kind — mirrors
    `/calendar-resolution` (W1). `policy_kind` must be one of `ATTENDANCE_POLICY`/
    `OVERTIME_POLICY`/`REGULARIZATION_POLICY`; anything else 422s via the service's fail-closed
    resolution (never guesses)."""
    if policy_kind not in _RESOLUTION_KINDS:
        raise ValidationError(f"policy_kind must be one of {_RESOLUTION_KINDS}")
    data = await service.resolve_policy(
        tenant.company_id, policy_kind, employee_id=employee_id, target_date=date_param
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


# ---------------------------------------------------------------------------
# W4 — Punches (architecture §19.1 step 9, WD-11)
# ---------------------------------------------------------------------------


@router.post("/attendance/punches", status_code=status.HTTP_201_CREATED)
async def create_punch(
    body: PunchCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    rbac: Annotated[RbacService, Depends(get_rbac_service)],
    service: Annotated[PunchService, Depends(get_punch_service)],
) -> DataEnvelope[PunchRead]:
    """Self-punch (`ATTENDANCE.PUNCH`, SELF) when `employee_id` is omitted or matches the
    caller's own; on-behalf (`ATTENDANCE.PUNCH_ON_BEHALF`, COMPANY) when it names someone else —
    the gating permission depends on the request body, so this mirrors
    `employee/router.py::create_assignment`'s direct `rbac.resolve_data_scope()` call rather
    than a static `Depends(require_permission(CODE))`."""
    target_employee_id = body.employee_id or user.employee_id
    if target_employee_id is None:
        raise ValidationError("employee_id is required — the caller has no linked employee record")

    on_behalf = body.employee_id is not None and body.employee_id != user.employee_id
    required_permission = ATTENDANCE_PUNCH_ON_BEHALF if on_behalf else ATTENDANCE_PUNCH
    scope = await rbac.resolve_data_scope(user.user_id, user.company_id, required_permission)
    if not scope.levels:
        raise PermissionDeniedError(
            f"Permission {required_permission} is required", code="PERMISSION_DENIED"
        )

    data = await service.record_punch(
        tenant.company_id,
        target_employee_id,
        body,
        scope=scope,
        caller_employee_id=user.employee_id,
        default_source="ADMIN" if on_behalf else "WEB",
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/attendance/punches", status_code=status.HTTP_200_OK)
async def list_punches(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    service: Annotated[PunchService, Depends(get_punch_service)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_VIEW))],
    employee_id: Annotated[UUID | None, Query()] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
) -> ListEnvelope[PunchRead]:
    data = await service.list_punches(
        tenant.company_id,
        scope=scope,
        caller_employee_id=user.employee_id,
        employee_id=employee_id,
        date_from=date_from,
        date_to=date_to,
    )
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


# ---------------------------------------------------------------------------
# W4 — Attendance Days (architecture §19.1, WD-10/WD-11)
# ---------------------------------------------------------------------------


@router.get("/attendance/days", status_code=status.HTTP_200_OK)
async def list_attendance_days(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    service: Annotated[AttendanceDayService, Depends(get_attendance_day_service)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_VIEW))],
    employee_id: Annotated[UUID | None, Query()] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    attendance_status: Annotated[str | None, Query()] = None,
) -> ListEnvelope[AttendanceDayRead]:
    data = await service.list_attendance_days(
        tenant.company_id,
        scope=scope,
        caller_employee_id=user.employee_id,
        employee_id=employee_id,
        date_from=date_from,
        date_to=date_to,
        status=attendance_status,
    )
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/attendance/days/{attendance_day_id}", status_code=status.HTTP_200_OK)
async def get_attendance_day(
    attendance_day_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    service: Annotated[AttendanceDayService, Depends(get_attendance_day_service)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_VIEW))],
) -> DataEnvelope[AttendanceDayRead]:
    data = await service.get_attendance_day(
        tenant.company_id,
        attendance_day_id,
        scope=scope,
        caller_employee_id=user.employee_id,
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/attendance/days/calculate", status_code=status.HTTP_200_OK)
async def calculate_attendance_day(
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_VIEW_ALL))],
    service: Annotated[AttendanceDayService, Depends(get_attendance_day_service)],
    employee_id: Annotated[UUID, Query()],
    date_param: Annotated[date, Query(alias="date")],
) -> DataEnvelope[AttendanceDayRead]:
    """On-demand calculation for one employee+date — creates the row if none exists yet, or
    fully replaces its derived fields if it does (WD-10). COMPANY-scoped
    (`ATTENDANCE.VIEW_ALL`) rather than `ATTENDANCE.RECOMPUTE`: this is the ordinary "compute
    today's attendance" path, not the privileged backdated-recompute act — see
    `POST /attendance/days/{id}/recompute` for that."""
    data = await service.calculate(
        tenant.company_id,
        employee_id,
        date_param,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/attendance/days/{attendance_day_id}/recompute", status_code=status.HTTP_200_OK)
async def recompute_attendance_day(
    attendance_day_id: UUID,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_RECOMPUTE))],
    service: Annotated[AttendanceDayService, Depends(get_attendance_day_service)],
) -> DataEnvelope[AttendanceDayRead]:
    """Privileged recompute (`ATTENDANCE.RECOMPUTE`, COMPANY) — architecture §18: backdated
    policy publishes or other after-the-fact corrections re-resolve versions by date and fully
    replace the day's derived fields. Refused on a locked day (`AttendanceDayLockedError`,
    409) — nothing in W4 can lock a day yet, so this path is exercised by tests only, ready for
    W8's `AttendanceLock`."""
    data = await service.recompute(
        tenant.company_id,
        attendance_day_id,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


# ---------------------------------------------------------------------------
# W5 — ShiftRoster (architecture §4.2/§9.7/§25, WD-27)
# ---------------------------------------------------------------------------


@router.post("/rosters", status_code=status.HTTP_201_CREATED)
async def create_roster_entry(
    body: ShiftRosterCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_ROSTER_MANAGE))],
    service: Annotated[ShiftRosterService, Depends(get_shift_roster_service)],
) -> DataEnvelope[ShiftRosterRead]:
    data = await service.create_roster_entry(
        tenant.company_id,
        body,
        scope=scope,
        caller_employee_id=user.employee_id,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/rosters/bulk", status_code=status.HTTP_201_CREATED)
async def bulk_create_roster_entries(
    body: ShiftRosterBulkCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_ROSTER_MANAGE))],
    service: Annotated[ShiftRosterService, Depends(get_shift_roster_service)],
) -> ListEnvelope[ShiftRosterRead]:
    """architecture §25 `/rosters bulk + per employee/date` — an explicit per-date entry list
    (fixed/monthly rosters), not a rotation-pattern generator (WD-27)."""
    data = await service.bulk_create(
        tenant.company_id,
        body,
        scope=scope,
        caller_employee_id=user.employee_id,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/rosters", status_code=status.HTTP_200_OK)
async def list_roster_entries(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_VIEW))],
    service: Annotated[ShiftRosterService, Depends(get_shift_roster_service)],
    employee_id: Annotated[UUID | None, Query()] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    roster_status: Annotated[str | None, Query(alias="status")] = None,
) -> ListEnvelope[ShiftRosterRead]:
    data = await service.list_roster_entries(
        tenant.company_id,
        scope=scope,
        caller_employee_id=user.employee_id,
        employee_id=employee_id,
        date_from=date_from,
        date_to=date_to,
        status=roster_status,
    )
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/rosters/{roster_id}", status_code=status.HTTP_200_OK)
async def get_roster_entry(
    roster_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_VIEW))],
    service: Annotated[ShiftRosterService, Depends(get_shift_roster_service)],
) -> DataEnvelope[ShiftRosterRead]:
    data = await service.get_roster_entry(
        tenant.company_id, roster_id, scope=scope, caller_employee_id=user.employee_id
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.patch("/rosters/{roster_id}", status_code=status.HTTP_200_OK)
async def update_roster_entry(
    roster_id: UUID,
    body: ShiftRosterUpdate,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_ROSTER_MANAGE))],
    service: Annotated[ShiftRosterService, Depends(get_shift_roster_service)],
) -> DataEnvelope[ShiftRosterRead]:
    data = await service.update_roster_entry(
        tenant.company_id,
        roster_id,
        body,
        expected_version=int(if_match),
        scope=scope,
        caller_employee_id=user.employee_id,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/rosters/{roster_id}/publish", status_code=status.HTTP_200_OK)
async def publish_roster_entry(
    roster_id: UUID,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_ROSTER_MANAGE))],
    service: Annotated[ShiftRosterService, Depends(get_shift_roster_service)],
) -> DataEnvelope[ShiftRosterRead]:
    data = await service.publish_roster_entry(
        tenant.company_id,
        roster_id,
        expected_version=int(if_match),
        scope=scope,
        caller_employee_id=user.employee_id,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.delete("/rosters/{roster_id}", status_code=status.HTTP_200_OK)
async def delete_roster_entry(
    roster_id: UUID,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_ROSTER_MANAGE))],
    service: Annotated[ShiftRosterService, Depends(get_shift_roster_service)],
) -> DataEnvelope[ShiftRosterRead]:
    data = await service.delete_roster_entry(
        tenant.company_id,
        roster_id,
        expected_version=int(if_match),
        scope=scope,
        caller_employee_id=user.employee_id,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


# ---------------------------------------------------------------------------
# W6 — Regularization requests (architecture §13/§14/§25, decision log WD-28)
# ---------------------------------------------------------------------------


@router.post("/regularizations", status_code=status.HTTP_201_CREATED)
async def create_regularization_request(
    body: RegularizationRequestCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    rbac: Annotated[RbacService, Depends(get_rbac_service)],
    service: Annotated[RegularizationRequestService, Depends(get_regularization_request_service)],
) -> DataEnvelope[RegularizationRequestRead]:
    """Self-submit (`ATTENDANCE.REGULARIZATION_REQUEST`, SELF) when `employee_id` is omitted or
    matches the caller's own; on-behalf (`ATTENDANCE.REGULARIZATION_REQUEST_ON_BEHALF`, COMPANY)
    when it names someone else — mirrors `create_punch`'s direct `rbac.resolve_data_scope()`
    call exactly, since the gating permission here also depends on the request body."""
    target_employee_id = body.employee_id or user.employee_id
    if target_employee_id is None:
        raise ValidationError("employee_id is required — the caller has no linked employee record")

    on_behalf = body.employee_id is not None and body.employee_id != user.employee_id
    required_permission = (
        ATTENDANCE_REGULARIZATION_REQUEST_ON_BEHALF
        if on_behalf
        else ATTENDANCE_REGULARIZATION_REQUEST
    )
    scope = await rbac.resolve_data_scope(user.user_id, user.company_id, required_permission)
    if not scope.levels:
        raise PermissionDeniedError(
            f"Permission {required_permission} is required", code="PERMISSION_DENIED"
        )

    data = await service.submit(
        tenant.company_id,
        target_employee_id,
        body,
        scope=scope,
        caller_employee_id=user.employee_id,
        on_behalf=on_behalf,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/regularizations", status_code=status.HTTP_200_OK)
async def list_regularization_requests(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    service: Annotated[RegularizationRequestService, Depends(get_regularization_request_service)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_VIEW))],
    employee_id: Annotated[UUID | None, Query()] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    request_status: Annotated[str | None, Query()] = None,
    request_type: Annotated[str | None, Query()] = None,
) -> ListEnvelope[RegularizationRequestRead]:
    data = await service.list(
        tenant.company_id,
        scope=scope,
        caller_employee_id=user.employee_id,
        employee_id=employee_id,
        date_from=date_from,
        date_to=date_to,
        status=request_status,
        request_type=request_type,
    )
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/regularizations/{request_id}", status_code=status.HTTP_200_OK)
async def get_regularization_request(
    request_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    service: Annotated[RegularizationRequestService, Depends(get_regularization_request_service)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_VIEW))],
) -> DataEnvelope[RegularizationRequestRead]:
    data = await service.get(
        tenant.company_id, request_id, scope=scope, caller_employee_id=user.employee_id
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/regularizations/{request_id}/cancel", status_code=status.HTTP_200_OK)
async def cancel_regularization_request(
    request_id: UUID,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    rbac: Annotated[RbacService, Depends(get_rbac_service)],
    service: Annotated[RegularizationRequestService, Depends(get_regularization_request_service)],
) -> DataEnvelope[RegularizationRequestRead]:
    """Only the original submitter may cancel (enforced in the service); this route accepts
    either submission permission since a cancel is available to whichever kind of submitter
    created the request — the service's `submitted_by_user_id` check is the real gate, this is
    only "does the caller hold some regularization-submission grant at all"."""
    self_scope = await rbac.resolve_data_scope(
        user.user_id, user.company_id, ATTENDANCE_REGULARIZATION_REQUEST
    )
    on_behalf_scope = await rbac.resolve_data_scope(
        user.user_id, user.company_id, ATTENDANCE_REGULARIZATION_REQUEST_ON_BEHALF
    )
    combined_scope = DataScope(levels=self_scope.levels | on_behalf_scope.levels)
    if not combined_scope.levels:
        raise PermissionDeniedError(
            f"Permission {ATTENDANCE_REGULARIZATION_REQUEST} is required", code="PERMISSION_DENIED"
        )

    data = await service.cancel(
        tenant.company_id,
        request_id,
        scope=combined_scope,
        caller_employee_id=user.employee_id,
        actor_user_id=tenant.user_id,
        expected_version=int(if_match),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/regularizations/{request_id}/approve", status_code=status.HTTP_200_OK)
async def approve_regularization_request(
    request_id: UUID,
    body: RegularizationReviewInput,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_REGULARIZATION_APPROVE))],
    service: Annotated[RegularizationRequestService, Depends(get_regularization_request_service)],
) -> DataEnvelope[RegularizationRequestRead]:
    """§14: `MANAGER` stage requires the caller to *be* the snapshotted
    `resolved_approver_manager_id`; `HR` stage requires a COMPANY-scoped grant — both checked in
    the service (`RegularizationRequestService._get_reviewable`), not here, since the correct
    check depends on the request's current stage."""
    data = await service.approve(
        tenant.company_id,
        request_id,
        body,
        scope=scope,
        caller_employee_id=user.employee_id,
        actor_user_id=tenant.user_id,
        expected_version=int(if_match),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/regularizations/{request_id}/reject", status_code=status.HTTP_200_OK)
async def reject_regularization_request(
    request_id: UUID,
    body: RegularizationReviewInput,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_REGULARIZATION_APPROVE))],
    service: Annotated[RegularizationRequestService, Depends(get_regularization_request_service)],
) -> DataEnvelope[RegularizationRequestRead]:
    data = await service.reject(
        tenant.company_id,
        request_id,
        body,
        scope=scope,
        caller_employee_id=user.employee_id,
        actor_user_id=tenant.user_id,
        expected_version=int(if_match),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))
