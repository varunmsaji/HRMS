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

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.auth.dependencies import get_current_user
from hrms.core.auth.types import AuthenticatedUser
from hrms.core.db.session import get_session
from hrms.core.errors.base import PermissionDeniedError, ValidationError
from hrms.core.rbac.dependencies import get_rbac_service, require_permission
from hrms.core.rbac.service import RbacService
from hrms.core.rbac.types import DataScope
from hrms.core.tenancy.context import TenantContext, current_request_id
from hrms.core.tenancy.dependencies import get_tenant_context
from hrms.core.uploads import read_upload_bounded
from hrms.modules.attendance.dependencies import (
    get_attendance_day_service,
    get_attendance_period_service,
    get_attendance_service,
    get_face_enrollment_service,
    get_face_policy_service,
    get_face_punch_service,
    get_leave_projection_service,
    get_overtime_record_service,
    get_punch_service,
    get_regularization_request_service,
    get_shift_roster_service,
)
from hrms.modules.attendance.exceptions import FaceImageInvalidError
from hrms.modules.attendance.face_comparison_router import router as face_comparison_router
from hrms.modules.attendance.face_policy import (
    FaceEnrollmentPolicyRead,
    FaceEnrollmentPolicyUpdate,
    FacePolicyService,
)
from hrms.modules.attendance.face_rate_limit import (
    face_enrollment_rate_limit,
    face_punch_rate_limit,
    face_review_photo_rate_limit,
    punch_rate_limit,
)
from hrms.modules.attendance.face_service import FaceEnrollmentService, FacePunchService
from hrms.modules.attendance.geofence_form import parse_form_location
from hrms.modules.attendance.overview import AttendanceOverviewService
from hrms.modules.attendance.overview_schemas import AttendanceOverviewRead
from hrms.modules.attendance.permissions import (
    ATTENDANCE_FACE_ENROLLMENT_MANAGE,
    ATTENDANCE_LEAVE_PROJECTION_SYNC,
    ATTENDANCE_LOCK,
    ATTENDANCE_OVERTIME_APPROVE,
    ATTENDANCE_POLICY_MANAGE,
    ATTENDANCE_PUNCH,
    ATTENDANCE_PUNCH_ON_BEHALF,
    ATTENDANCE_RECOMPUTE,
    ATTENDANCE_REGULARIZATION_APPROVE,
    ATTENDANCE_REGULARIZATION_REQUEST,
    ATTENDANCE_REGULARIZATION_REQUEST_ON_BEHALF,
    ATTENDANCE_ROSTER_MANAGE,
    ATTENDANCE_UNLOCK,
    ATTENDANCE_VIEW,
    ATTENDANCE_VIEW_ALL,
)
from hrms.modules.attendance.policy_setup import (
    AttendancePolicySetupService,
    get_attendance_policy_setup_service,
)
from hrms.modules.attendance.regularization_decision_center import (
    RegularizationDecisionCenter,
    RegularizationTab,
    build_regularization_decision_center,
)
from hrms.modules.attendance.schemas import (
    FACE_IMAGE_MAX_BYTES,
    FACE_LIVENESS_FRAME_MAX_BYTES,
    FACE_LIVENESS_MAX_FRAMES,
    AttendanceDayRead,
    AttendancePeriodCreate,
    AttendancePeriodRead,
    AttendancePeriodReopenInput,
    AttendancePeriodSummaryRead,
    AttendancePeriodValidationRead,
    AttendancePolicyCreate,
    AttendancePolicyFormContext,
    AttendancePolicyRead,
    AttendancePolicySetup,
    AttendancePolicySetupRead,
    AttendancePolicyUpdate,
    AttendancePolicyVersionCreate,
    AttendancePolicyVersionPublishRequest,
    AttendancePolicyVersionRead,
    AttendancePolicyVersionUpdate,
    AttendanceRangeCalculateInput,
    AttendanceRangeCalculateQueued,
    FaceEnrollmentAngle,
    FaceEnrollmentStatusRead,
    FaceEnrollmentWindowRead,
    FaceLivenessSessionCreate,
    FaceLivenessSessionRead,
    FaceProfileRead,
    FaceProfileRejectInput,
    FacePunchRead,
    LeaveDayProjectionRead,
    LeaveProjectionCancelInput,
    LeaveProjectionSync,
    OvertimePolicyCreate,
    OvertimePolicyRead,
    OvertimePolicySetup,
    OvertimePolicySetupRead,
    OvertimePolicyUpdate,
    OvertimePolicyVersionCreate,
    OvertimePolicyVersionPublishRequest,
    OvertimePolicyVersionRead,
    OvertimePolicyVersionUpdate,
    OvertimeRecordRead,
    OvertimeReviewInput,
    PolicyResolutionRead,
    PunchCreateOnBehalf,
    PunchCreateSelf,
    PunchRead,
    RegularizationPolicyCreate,
    RegularizationPolicyRead,
    RegularizationPolicySetup,
    RegularizationPolicySetupRead,
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
    WorkOnLeaveKeepLeaveInput,
)
from hrms.modules.attendance.service import (
    AttendanceDayService,
    AttendancePeriodService,
    AttendanceService,
    LeaveProjectionService,
    OvertimeRecordService,
    PunchService,
    RegularizationRequestService,
    ShiftRosterService,
)
from hrms.modules.attendance.summary import AttendanceSummaryService, SummaryFilters
from hrms.modules.attendance.summary_schemas import AttendanceSummaryRead
from hrms.modules.identity.schemas import build_meta
from hrms.modules.organisation.permissions import DASHBOARD_COMPANY_VIEW
from hrms.shared.if_match import parse_if_match
from hrms.shared.pagination import (
    DataEnvelope,
    ListEnvelope,
    PageParams,
    bounded_pagination_params,
    build_pagination_meta,
)

router = APIRouter(tags=["attendance"])
router.include_router(face_comparison_router)


# ---------------------------------------------------------------------------
# Attendance Policies
# ---------------------------------------------------------------------------


@router.get("/attendance-policies", status_code=status.HTTP_200_OK)
async def list_attendance_policies(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Annotated[AttendanceService, Depends(get_attendance_service)],
    assignable: Annotated[bool, Query()] = False,
) -> ListEnvelope[AttendancePolicyRead]:
    data = await service.list_attendance_policies_with_status(
        tenant.company_id, assignable_only=assignable
    )
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/attendance-policies/form-context", status_code=status.HTTP_200_OK)
async def get_attendance_policy_form_context(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Annotated[AttendanceService, Depends(get_attendance_service)],
) -> DataEnvelope[AttendancePolicyFormContext]:
    data = await service.attendance_policy_form_context(tenant.company_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/attendance-policies/setup", status_code=status.HTTP_201_CREATED)
async def setup_attendance_policy(
    body: AttendancePolicySetup,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Annotated[AttendancePolicySetupService, Depends(get_attendance_policy_setup_service)],
) -> DataEnvelope[AttendancePolicySetupRead]:
    """Creates the policy and its rules, optionally publishing and assigning it, all or nothing."""
    data = await service.setup(
        tenant.company_id,
        body,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


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
        expected_version=parse_if_match(if_match),
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
        expected_version=parse_if_match(if_match),
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
        expected_version=parse_if_match(if_match),
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
        expected_version=parse_if_match(if_match),
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
    assignable: Annotated[bool, Query()] = False,
) -> ListEnvelope[OvertimePolicyRead]:
    data = await service.list_overtime_policies_with_status(
        tenant.company_id, assignable_only=assignable
    )
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/overtime-policies/setup", status_code=status.HTTP_201_CREATED)
async def setup_overtime_policy(
    body: OvertimePolicySetup,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Annotated[AttendancePolicySetupService, Depends(get_attendance_policy_setup_service)],
) -> DataEnvelope[OvertimePolicySetupRead]:
    """Creates the policy and its rules, optionally publishing and assigning it, all or nothing."""
    data = await service.setup_overtime(
        tenant.company_id,
        body,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


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
        expected_version=parse_if_match(if_match),
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
        expected_version=parse_if_match(if_match),
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
        expected_version=parse_if_match(if_match),
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
        expected_version=parse_if_match(if_match),
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
    assignable: Annotated[bool, Query()] = False,
) -> ListEnvelope[RegularizationPolicyRead]:
    data = await service.list_regularization_policies_with_status(
        tenant.company_id, assignable_only=assignable
    )
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/regularization-policies/setup", status_code=status.HTTP_201_CREATED)
async def setup_regularization_policy(
    body: RegularizationPolicySetup,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Annotated[AttendancePolicySetupService, Depends(get_attendance_policy_setup_service)],
) -> DataEnvelope[RegularizationPolicySetupRead]:
    """Creates the policy and its rules, optionally publishing and assigning it, all or nothing."""
    data = await service.setup_regularization(
        tenant.company_id,
        body,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


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
        expected_version=parse_if_match(if_match),
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
        expected_version=parse_if_match(if_match),
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
        expected_version=parse_if_match(if_match),
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
        expected_version=parse_if_match(if_match),
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


@router.post("/attendance/punches/me", status_code=status.HTTP_201_CREATED)
async def create_self_punch(
    body: PunchCreateSelf,
    request: Request,
    _rate_limit: Annotated[None, Depends(punch_rate_limit)],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_PUNCH))],
    service: Annotated[PunchService, Depends(get_punch_service)],
) -> DataEnvelope[PunchRead]:
    """Employee self-service punch (`ATTENDANCE.PUNCH`, SELF).

    **The permission is static** — `Depends(require_permission(...))` resolves it before the body
    is read, so no value a caller controls can route them into a different authorization branch.
    That is the security half of `ED-4`; the schema half is that `PunchCreateSelf` has no
    `punch_time`, `source`, or `employee_id` field to send.

    The punch instant is assigned by the server at receipt (`requested_punch_time=None`)."""
    if user.employee_id is None:
        raise ValidationError(
            "The caller has no linked employee record — use the on-behalf endpoint instead"
        )

    data = await service.record_punch(
        tenant.company_id,
        user.employee_id,
        direction=body.direction,
        # DEC-TZ-01 (SELECTED) — the server's clock, always. Not "the client's value if present":
        # there is no client value, by schema.
        requested_punch_time=None,
        source="WEB",
        reference=body.reference,
        idempotency_key=body.idempotency_key,
        scope=scope,
        caller_employee_id=user.employee_id,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
        location=body.location,
        location_error=body.location_error,
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/attendance/punches", status_code=status.HTTP_201_CREATED)
async def create_punch_on_behalf(
    body: PunchCreateOnBehalf,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_PUNCH_ON_BEHALF))],
    service: Annotated[PunchService, Depends(get_punch_service)],
) -> DataEnvelope[PunchRead]:
    """HR/admin entering a punch for an employee (`ATTENDANCE.PUNCH_ON_BEHALF`, COMPANY).

    This route previously served both acts and picked the required permission from
    `body.employee_id` — meaning FastAPI had to parse and trust a caller-controlled field before
    it could decide what the caller was allowed to do. Splitting the routes (`ED-4`) makes the
    requirement static: a caller holding only `ATTENDANCE.PUNCH` now gets a clean 403 here,
    regardless of what they put in the body.

    A caller naming *their own* `employee_id` here is accepted rather than redirected — they
    trivially hold the scope, and the resulting row is legitimately an `ADMIN`-source correction.

    `scope`/`caller_employee_id` still gate the *target* employee inside the service: holding the
    permission is not the same as being allowed to see this particular person."""
    data = await service.record_punch(
        tenant.company_id,
        body.employee_id,
        direction=body.direction,
        # Required and client-supplied here — that is the workflow's purpose — but bounded in the
        # service: not future, not before employment, not inside a CLOSED period.
        requested_punch_time=body.punch_time,
        source="ADMIN",
        reference=body.reference,
        idempotency_key=body.idempotency_key,
        scope=scope,
        caller_employee_id=user.employee_id,
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
    page: Annotated[PageParams, Depends(bounded_pagination_params)],
    employee_id: Annotated[UUID | None, Query()] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
) -> ListEnvelope[PunchRead]:
    data, total = await service.list_punches(
        tenant.company_id,
        scope=scope,
        caller_employee_id=user.employee_id,
        employee_id=employee_id,
        date_from=date_from,
        date_to=date_to,
        page=page,
    )
    return ListEnvelope(
        data=data,
        pagination=build_pagination_meta(page, total=total),
        meta=build_meta(current_request_id() or "unknown"),
    )


@router.get("/dashboards/company/attendance-overview", status_code=status.HTTP_200_OK)
async def get_company_attendance_overview(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
    _dashboard: Annotated[object, Depends(require_permission(DASHBOARD_COMPANY_VIEW))],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_VIEW))],
    attendance_date: Annotated[date | None, Query(alias="date")] = None,
    department_id: Annotated[UUID | None, Query()] = None,
    branch_id: Annotated[UUID | None, Query()] = None,
) -> DataEnvelope[AttendanceOverviewRead]:
    """Today's (or a past date's) workforce status, grouped from the persisted attendance days
    the calculation engine already wrote. Needs both the company-dashboard grant and attendance
    view; the headcount is limited to the employees the caller's attendance scope can see."""
    from hrms.modules.employee.service import EmployeeService
    from hrms.modules.organisation.service import OrganisationService

    company = await OrganisationService(session).get_company_profile(tenant.company_id)
    visible_ids = await EmployeeService(session).resolve_visible_employee_ids(
        tenant.company_id, scope, user.employee_id
    )
    data = await AttendanceOverviewService(session).overview(
        tenant.company_id,
        timezone=company.timezone,
        attendance_date=attendance_date,
        visible_employee_ids=visible_ids,
        department_id=department_id,
        branch_id=branch_id,
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


# ---------------------------------------------------------------------------
# W4 — Attendance Days (architecture §19.1, WD-10/WD-11)
# ---------------------------------------------------------------------------


@router.get("/attendance/days", status_code=status.HTTP_200_OK)
async def list_attendance_days(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    service: Annotated[AttendanceDayService, Depends(get_attendance_day_service)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_VIEW))],
    page: Annotated[PageParams, Depends(bounded_pagination_params)],
    employee_id: Annotated[UUID | None, Query()] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    attendance_status: Annotated[str | None, Query()] = None,
    break_filter: Annotated[
        Literal["UNRESOLVED", "ACTIVE", "EXCESS", "AUTO_DEDUCTED", "RECORDED", "ANY_EXCEPTION"]
        | None,
        Query(description="Restrict to days with a break exception or break activity"),
    ] = None,
) -> ListEnvelope[AttendanceDayRead]:
    data, total = await service.list_attendance_days(
        tenant.company_id,
        scope=scope,
        caller_employee_id=user.employee_id,
        employee_id=employee_id,
        date_from=date_from,
        date_to=date_to,
        status=attendance_status,
        break_filter=break_filter,
        page=page,
    )
    return ListEnvelope(
        data=data,
        pagination=build_pagination_meta(page, total=total),
        meta=build_meta(current_request_id() or "unknown"),
    )


@router.get("/attendance/summary", status_code=status.HTTP_200_OK)
async def get_attendance_summary(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_VIEW))],
    date_from: Annotated[date, Query()],
    date_to: Annotated[date, Query(description="Also the focus date of the KPIs and breakdown")],
    compare_date: Annotated[
        date | None, Query(description="Day to compare the focus date with; default a week earlier")
    ] = None,
    employee_id: Annotated[UUID | None, Query()] = None,
    shift_id: Annotated[UUID | None, Query()] = None,
    employee_status: Annotated[str | None, Query(max_length=25)] = None,
    department_id: Annotated[
        UUID | Literal["unassigned"] | None,
        Query(description='A department id, or "unassigned" for days with no department'),
    ] = None,
    branch_id: Annotated[
        UUID | Literal["unassigned"] | None,
        Query(description='A branch id, or "unassigned" for days with no branch'),
    ] = None,
) -> DataEnvelope[AttendanceSummaryRead]:
    """The attendance dashboard's totals for a window of up to 92 days, counted from the persisted
    attendance days over the employees the caller's attendance scope can see. Web and mobile both
    read these instead of adding up the rows themselves."""
    from hrms.modules.employee.service import EmployeeService
    from hrms.modules.organisation.service import OrganisationService
    from hrms.shared.business_time import business_today

    company = await OrganisationService(session).get_company_profile(tenant.company_id)
    visible_ids = await EmployeeService(session).resolve_visible_employee_ids(
        tenant.company_id, scope, user.employee_id
    )
    data = await AttendanceSummaryService(session).summary(
        tenant.company_id,
        date_from=date_from,
        date_to=date_to,
        today=business_today(company.timezone),
        compare_date=compare_date,
        filters=SummaryFilters(
            visible_employee_ids=visible_ids,
            employee_id=employee_id,
            shift_id=shift_id,
            employee_status=employee_status,
            department_id=department_id,
            branch_id=branch_id,
        ),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


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
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_VIEW_ALL))],
    service: Annotated[AttendanceDayService, Depends(get_attendance_day_service)],
    employee_id: Annotated[UUID, Query()],
    date_param: Annotated[date | None, Query(alias="date")] = None,
) -> DataEnvelope[AttendanceDayRead]:
    """On-demand calculation for one employee+date — creates the row if none exists yet, or
    fully replaces its derived fields if it does (WD-10). COMPANY-scoped
    (`ATTENDANCE.VIEW_ALL`) rather than `ATTENDANCE.RECOMPUTE`: this is the ordinary "compute
    today's attendance" path, not the privileged backdated-recompute act — see
    `POST /attendance/days/{id}/recompute` for that.

    `date` is now optional (`ED-2`, execution gate §9.3) — omitting it defaults server-side to
    `business_today(company_tz)`, so the client no longer has to compute "today" itself (the
    web client's own `todayIso()`, a UTC calendar date, was `NEW-02`). Passing an explicit date
    is unaffected and still honoured exactly as before."""
    data = await service.calculate(
        tenant.company_id,
        employee_id,
        date_param,
        scope=scope,
        caller_employee_id=user.employee_id,
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
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_RECOMPUTE))],
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
        scope=scope,
        caller_employee_id=user.employee_id,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/attendance/days/calculate-range", status_code=status.HTTP_202_ACCEPTED)
async def calculate_attendance_range(
    body: AttendanceRangeCalculateInput,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_RECOMPUTE))],
    service: Annotated[AttendanceDayService, Depends(get_attendance_day_service)],
) -> DataEnvelope[AttendanceRangeCalculateQueued]:
    """PAY-001 — queues calculation of every employed day in the range (at most 62 days, not
    past today) so a period can be finalized without one call per employee-date. Privileged
    (`ATTENDANCE.RECOMPUTE`, COMPANY). Locked days are skipped. Progress is visible through the
    period's `validate` verdict."""
    data = await service.queue_range_calculation(
        tenant.company_id,
        body,
        scope=scope,
        caller_employee_id=user.employee_id,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post(
    "/attendance/days/{attendance_day_id}/work-on-leave/keep-leave",
    status_code=status.HTTP_200_OK,
)
async def keep_leave_over_punches(
    attendance_day_id: UUID,
    body: WorkOnLeaveKeepLeaveInput,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_RECOMPUTE))],
    service: Annotated[AttendanceDayService, Depends(get_attendance_day_service)],
) -> DataEnvelope[AttendanceDayRead]:
    """BUS-012 — HR confirms an approved full-day leave stands over punches on the same day
    (same privileged `ATTENDANCE.RECOMPUTE` authority as recompute). Clears the
    `WORK_ON_LEAVE_UNRESOLVED` finalize blocker for this day. 409 if the day is locked or has no
    conflict to resolve."""
    data = await service.keep_leave_over_punches(
        tenant.company_id,
        attendance_day_id,
        body,
        scope=scope,
        caller_employee_id=user.employee_id,
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
    page: Annotated[PageParams, Depends(bounded_pagination_params)],
    employee_id: Annotated[UUID | None, Query()] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    roster_status: Annotated[str | None, Query(alias="status")] = None,
) -> ListEnvelope[ShiftRosterRead]:
    data, total = await service.list_roster_entries(
        tenant.company_id,
        scope=scope,
        caller_employee_id=user.employee_id,
        employee_id=employee_id,
        date_from=date_from,
        date_to=date_to,
        status=roster_status,
        page=page,
    )
    return ListEnvelope(
        data=data,
        pagination=build_pagination_meta(page, total=total),
        meta=build_meta(current_request_id() or "unknown"),
    )


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
        expected_version=parse_if_match(if_match),
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
        expected_version=parse_if_match(if_match),
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
        expected_version=parse_if_match(if_match),
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
    page: Annotated[PageParams, Depends(bounded_pagination_params)],
    employee_id: Annotated[UUID | None, Query()] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    request_status: Annotated[str | None, Query()] = None,
    request_type: Annotated[str | None, Query()] = None,
) -> ListEnvelope[RegularizationRequestRead]:
    data, total = await service.list(
        tenant.company_id,
        scope=scope,
        caller_employee_id=user.employee_id,
        employee_id=employee_id,
        date_from=date_from,
        date_to=date_to,
        status=request_status,
        request_type=request_type,
        page=page,
    )
    return ListEnvelope(
        data=data,
        pagination=build_pagination_meta(page, total=total),
        meta=build_meta(current_request_id() or "unknown"),
    )


@router.get("/regularizations/decision-center", status_code=status.HTTP_200_OK)
async def get_regularization_decision_center(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_REGULARIZATION_APPROVE))],
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
    tab: RegularizationTab = "pending",
) -> DataEnvelope[RegularizationDecisionCenter]:
    """Read-only approver screen data; approving/rejecting stays on the routes below."""
    from hrms.modules.employee.service import EmployeeService

    visible = await EmployeeService(session).resolve_visible_employee_ids(
        tenant.company_id, scope, user.employee_id
    )
    data = await build_regularization_decision_center(session, tenant.company_id, visible, tab=tab)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


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
        expected_version=parse_if_match(if_match),
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
        expected_version=parse_if_match(if_match),
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
        expected_version=parse_if_match(if_match),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


# ---------------------------------------------------------------------------
# W7 — Overtime records (architecture §12, decision log WD-29)
# ---------------------------------------------------------------------------


@router.get("/overtime", status_code=status.HTTP_200_OK)
async def list_overtime_records(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    service: Annotated[OvertimeRecordService, Depends(get_overtime_record_service)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_VIEW))],
    page: Annotated[PageParams, Depends(bounded_pagination_params)],
    employee_id: Annotated[UUID | None, Query()] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    record_status: Annotated[str | None, Query()] = None,
) -> ListEnvelope[OvertimeRecordRead]:
    data, total = await service.list(
        tenant.company_id,
        scope=scope,
        caller_employee_id=user.employee_id,
        employee_id=employee_id,
        date_from=date_from,
        date_to=date_to,
        status=record_status,
        page=page,
    )
    return ListEnvelope(
        data=data,
        pagination=build_pagination_meta(page, total=total),
        meta=build_meta(current_request_id() or "unknown"),
    )


@router.get("/overtime/{record_id}", status_code=status.HTTP_200_OK)
async def get_overtime_record(
    record_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    service: Annotated[OvertimeRecordService, Depends(get_overtime_record_service)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_VIEW))],
) -> DataEnvelope[OvertimeRecordRead]:
    data = await service.get(
        tenant.company_id, record_id, scope=scope, caller_employee_id=user.employee_id
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/overtime/{record_id}/approve", status_code=status.HTTP_200_OK)
async def approve_overtime_record(
    record_id: UUID,
    body: OvertimeReviewInput,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_OVERTIME_APPROVE))],
    service: Annotated[OvertimeRecordService, Depends(get_overtime_record_service)],
) -> DataEnvelope[OvertimeRecordRead]:
    """Mirrors regularization's approve route: the `MANAGER`-vs-`HR` stage check happens in the
    service (`OvertimeRecordService._get_reviewable`), since the correct check depends on the
    record's current stage, not something a static route dependency can express."""
    data = await service.approve(
        tenant.company_id,
        record_id,
        body,
        scope=scope,
        caller_employee_id=user.employee_id,
        actor_user_id=tenant.user_id,
        expected_version=parse_if_match(if_match),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/overtime/{record_id}/reject", status_code=status.HTTP_200_OK)
async def reject_overtime_record(
    record_id: UUID,
    body: OvertimeReviewInput,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_OVERTIME_APPROVE))],
    service: Annotated[OvertimeRecordService, Depends(get_overtime_record_service)],
) -> DataEnvelope[OvertimeRecordRead]:
    data = await service.reject(
        tenant.company_id,
        record_id,
        body,
        scope=scope,
        caller_employee_id=user.employee_id,
        actor_user_id=tenant.user_id,
        expected_version=parse_if_match(if_match),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


# ---------------------------------------------------------------------------
# W8 — Attendance periods (architecture §4.2/§22, decision log WD-30)
# ---------------------------------------------------------------------------


@router.post("/attendance-periods", status_code=status.HTTP_201_CREATED)
async def create_attendance_period(
    body: AttendancePeriodCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_LOCK))],
    service: Annotated[AttendancePeriodService, Depends(get_attendance_period_service)],
) -> DataEnvelope[AttendancePeriodRead]:
    """Create always opens the period immediately — there is no separate "open" action
    (WD-30, mirrors WD-28's no-DRAFT-state precedent)."""
    data = await service.create(
        tenant.company_id,
        body,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/attendance-periods", status_code=status.HTTP_200_OK)
async def list_attendance_periods(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_VIEW))],
    service: Annotated[AttendancePeriodService, Depends(get_attendance_period_service)],
    page: Annotated[PageParams, Depends(bounded_pagination_params)],
    period_status: Annotated[str | None, Query()] = None,
    legal_entity_id: Annotated[UUID | None, Query()] = None,
) -> ListEnvelope[AttendancePeriodRead]:
    data, total = await service.list_periods(
        tenant.company_id, status=period_status, legal_entity_id=legal_entity_id, page=page
    )
    return ListEnvelope(
        data=data,
        pagination=build_pagination_meta(page, total=total),
        meta=build_meta(current_request_id() or "unknown"),
    )


@router.get("/attendance-periods/{period_id}", status_code=status.HTTP_200_OK)
async def get_attendance_period(
    period_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_VIEW))],
    service: Annotated[AttendancePeriodService, Depends(get_attendance_period_service)],
) -> DataEnvelope[AttendancePeriodRead]:
    data = await service.get(tenant.company_id, period_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


async def _attendance_view_scope(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    rbac: Annotated[RbacService, Depends(get_rbac_service)],
) -> DataScope:
    """Unions `ATTENDANCE.VIEW` (its assigned scope) with `ATTENDANCE.VIEW_ALL` (company-wide
    visibility, "ignoring reporting tree"). Each permission's own grant is honoured as granted:
    a VIEW_ALL grant below COMPANY stays below COMPANY. Neither held -> 403."""
    view = await rbac.resolve_data_scope(user.user_id, user.company_id, ATTENDANCE_VIEW)
    view_all = await rbac.resolve_data_scope(user.user_id, user.company_id, ATTENDANCE_VIEW_ALL)
    combined = DataScope(levels=view.levels | view_all.levels)
    if not combined.levels:
        raise PermissionDeniedError(
            f"Permission {ATTENDANCE_VIEW} is required", code="PERMISSION_DENIED"
        )
    return combined


@router.get("/attendance-periods/{period_id}/summary", status_code=status.HTTP_200_OK)
async def get_attendance_period_summary(
    period_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(_attendance_view_scope)],
    service: Annotated[AttendancePeriodService, Depends(get_attendance_period_service)],
) -> ListEnvelope[AttendancePeriodSummaryRead]:
    """A live, unpersisted preview while `OPEN`; the frozen snapshot once `CLOSED`
    (architecture §4.2 — "regenerated only while unlocked; frozen at lock/snapshot").
    Rows are limited to the employees `scope` allows (DEF-B6-02)."""
    data = await service.get_summary(
        tenant.company_id, period_id, scope=scope, caller_employee_id=user.employee_id
    )
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/attendance-periods/{period_id}/validate", status_code=status.HTTP_200_OK)
async def validate_attendance_period(
    period_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_LOCK))],
    service: Annotated[AttendancePeriodService, Depends(get_attendance_period_service)],
) -> DataEnvelope[AttendancePeriodValidationRead]:
    """Fail-closed finalization-readiness check (architecture §5) — always re-derives READY/
    BLOCKED live; never returns a stale cached result. `POST`, not `GET`, since it also records
    a `VALIDATED`/`VALIDATION_FAILED` action and refreshes the period's cached validation
    status (audit-visible, per Phase 10's "validation failure" requirement)."""
    data = await service.validate(tenant.company_id, period_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/attendance-periods/{period_id}/finalize", status_code=status.HTTP_200_OK)
async def finalize_attendance_period(
    period_id: UUID,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_LOCK))],
    service: Annotated[AttendancePeriodService, Depends(get_attendance_period_service)],
) -> DataEnvelope[AttendancePeriodRead]:
    """Closes and locks the period — `AttendanceDay.is_locked=true` across its whole range,
    a frozen `AttendancePeriodSummary` snapshot, and refuses fail-closed
    (`ATTENDANCE_FINALIZATION_BLOCKED`) unless a fresh validation is `READY`."""
    data = await service.finalize(
        tenant.company_id,
        period_id,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/attendance-periods/{period_id}/reopen", status_code=status.HTTP_200_OK)
async def reopen_attendance_period(
    period_id: UUID,
    body: AttendancePeriodReopenInput,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_UNLOCK))],
    service: Annotated[AttendancePeriodService, Depends(get_attendance_period_service)],
) -> DataEnvelope[AttendancePeriodRead]:
    """`ATTENDANCE.UNLOCK` — a materially higher-risk action than finalize, gated by its own
    permission (architecture §23.2), mandatory `reason`."""
    data = await service.reopen(
        tenant.company_id,
        period_id,
        body,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


# ---------------------------------------------------------------------------
# W9 — Leave projection adapter (architecture §21, decision log WD-31)
#
# A narrow, explicitly-internal seam: the Leave -> Attendance contract, not a Leave CRUD API.
# `ATTENDANCE.LEAVE_PROJECTION_SYNC` is the one gate for both mutating routes; reads reuse
# `ATTENDANCE.VIEW`/`ATTENDANCE.VIEW_ALL` per this file's established read-reuse convention.
# ---------------------------------------------------------------------------


@router.post("/leave-projections", status_code=status.HTTP_201_CREATED)
async def sync_leave_projection(
    body: LeaveProjectionSync,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_LEAVE_PROJECTION_SYNC))],
    service: Annotated[LeaveProjectionService, Depends(get_leave_projection_service)],
) -> DataEnvelope[LeaveDayProjectionRead]:
    """Publishes (or, for an already-known `leave_application_id`, republishes as a correction)
    one approved leave day projection and synchronously recomputes the affected `AttendanceDay`
    (architecture §21/§25 — an in-process call standing in for a real event bus)."""
    data = await service.sync(
        tenant.company_id,
        body,
        scope=scope,
        caller_employee_id=user.employee_id,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/leave-projections", status_code=status.HTTP_200_OK)
async def list_leave_projections(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_VIEW))],
    service: Annotated[LeaveProjectionService, Depends(get_leave_projection_service)],
    page: Annotated[PageParams, Depends(bounded_pagination_params)],
    employee_id: Annotated[UUID | None, Query()] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    projection_status: Annotated[str | None, Query(alias="status")] = None,
) -> ListEnvelope[LeaveDayProjectionRead]:
    data, total = await service.list_projections(
        tenant.company_id,
        scope=scope,
        caller_employee_id=user.employee_id,
        employee_id=employee_id,
        date_from=date_from,
        date_to=date_to,
        status=projection_status,
        page=page,
    )
    return ListEnvelope(
        data=data,
        pagination=build_pagination_meta(page, total=total),
        meta=build_meta(current_request_id() or "unknown"),
    )


@router.get("/leave-projections/{projection_id}", status_code=status.HTTP_200_OK)
async def get_leave_projection(
    projection_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_VIEW))],
    service: Annotated[LeaveProjectionService, Depends(get_leave_projection_service)],
) -> DataEnvelope[LeaveDayProjectionRead]:
    data = await service.get_projection(
        tenant.company_id, projection_id, scope=scope, caller_employee_id=user.employee_id
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/leave-projections/{projection_id}/cancel", status_code=status.HTTP_200_OK)
async def cancel_leave_projection(
    projection_id: UUID,
    body: LeaveProjectionCancelInput,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_LEAVE_PROJECTION_SYNC))],
    service: Annotated[LeaveProjectionService, Depends(get_leave_projection_service)],
) -> DataEnvelope[LeaveDayProjectionRead]:
    """Withdraws an approved projection (`status=CANCELLED`, never a delete — provenance is
    preserved) and synchronously recomputes the affected `AttendanceDay`. Refused with
    `ATTENDANCE_PERIOD_CLOSED` if the date's period is locked (architecture §21 — "default
    refuse"; the only correction path for a locked date is a full period reopen, PD-LOCK-2)."""
    data = await service.cancel(
        tenant.company_id,
        projection_id,
        body,
        expected_version=parse_if_match(if_match),
        scope=scope,
        caller_employee_id=user.employee_id,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


# ---------------------------------------------------------------------------
# Face attendance — enrollment (ATTENDANCE.FACE_ENROLLMENT_MANAGE, data-scoped)
# ---------------------------------------------------------------------------


def _client_meta(request: Request) -> dict[str, str | None]:
    return {
        "ip_address": request.client.host if request.client else None,
        "user_agent": request.headers.get("User-Agent"),
    }


@router.get("/attendance/face-enrollment-policy", status_code=status.HTTP_200_OK)
async def get_face_enrollment_policy(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_FACE_ENROLLMENT_MANAGE))],
    service: Annotated[FacePolicyService, Depends(get_face_policy_service)],
) -> DataEnvelope[FaceEnrollmentPolicyRead]:
    data = await service.get_policy(tenant.company_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.put("/attendance/face-enrollment-policy", status_code=status.HTTP_200_OK)
async def update_face_enrollment_policy(
    body: FaceEnrollmentPolicyUpdate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_FACE_ENROLLMENT_MANAGE))],
    service: Annotated[FacePolicyService, Depends(get_face_policy_service)],
) -> DataEnvelope[FaceEnrollmentPolicyRead]:
    """Whether face enrollment is a required onboarding step. Policy only: it never marks anyone
    enrolled, and turning it on does not lock existing employees out of attendance."""
    data = await service.set_policy(
        tenant.company_id, body, actor_user_id=tenant.user_id, **_client_meta(request)
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/attendance/face-profiles", status_code=status.HTTP_200_OK)
async def list_face_profiles(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_FACE_ENROLLMENT_MANAGE))],
    service: Annotated[FaceEnrollmentService, Depends(get_face_enrollment_service)],
    page: Annotated[PageParams, Depends(bounded_pagination_params)],
) -> ListEnvelope[FaceProfileRead]:
    data, total = await service.list_profiles(
        tenant.company_id, scope=scope, caller_employee_id=user.employee_id, page=page
    )
    return ListEnvelope(
        data=data,
        pagination=build_pagination_meta(page, total=total),
        meta=build_meta(current_request_id() or "unknown"),
    )


@router.get("/attendance/face-profiles/{employee_id}/enrollment", status_code=status.HTTP_200_OK)
async def get_face_enrollment_status(
    employee_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_FACE_ENROLLMENT_MANAGE))],
    service: Annotated[FaceEnrollmentService, Depends(get_face_enrollment_service)],
) -> DataEnvelope[FaceEnrollmentStatusRead]:
    data = await service.get_status(
        tenant.company_id, employee_id, scope=scope, caller_employee_id=user.employee_id
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post(
    "/attendance/face-profiles/{employee_id}/enrollment-window",
    status_code=status.HTTP_201_CREATED,
)
async def open_face_enrollment_window(
    employee_id: UUID,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_FACE_ENROLLMENT_MANAGE))],
    service: Annotated[FaceEnrollmentService, Depends(get_face_enrollment_service)],
) -> DataEnvelope[FaceEnrollmentWindowRead]:
    """Opens a one-time self-enrollment window for this employee (replacing any earlier one).
    The employee then captures their face in the mobile app; the window closes once used."""
    data = await service.open_window(
        tenant.company_id,
        employee_id,
        scope=scope,
        caller_employee_id=user.employee_id,
        actor_user_id=tenant.user_id,
        **_client_meta(request),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.delete(
    "/attendance/face-profiles/{employee_id}/enrollment-window",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def cancel_face_enrollment_window(
    employee_id: UUID,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_FACE_ENROLLMENT_MANAGE))],
    service: Annotated[FaceEnrollmentService, Depends(get_face_enrollment_service)],
) -> None:
    await service.cancel_window(
        tenant.company_id,
        employee_id,
        scope=scope,
        caller_employee_id=user.employee_id,
        actor_user_id=tenant.user_id,
        **_client_meta(request),
    )


@router.get("/attendance/face-profiles/{employee_id}/review-photo")
async def get_face_review_photo(
    request: Request,
    employee_id: UUID,
    _rate_limit: Annotated[None, Depends(face_review_photo_rate_limit)],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_FACE_ENROLLMENT_MANAGE))],
    service: Annotated[FaceEnrollmentService, Depends(get_face_enrollment_service)],
    angle: FaceEnrollmentAngle = "front",
) -> Response:
    """One of the five captures (`?angle=front|left|right|up|down`, default front) of a profile
    awaiting approval. The system keeps these only until HR decides."""
    image, content_type = await service.get_review_photo(
        tenant.company_id,
        employee_id,
        scope=scope,
        caller_employee_id=user.employee_id,
        angle=angle,
        actor_user_id=tenant.user_id,
        **_client_meta(request),
    )
    return Response(
        content=image, media_type=content_type, headers={"Cache-Control": "no-store, private"}
    )


@router.post("/attendance/face-profiles/{employee_id}/approve", status_code=status.HTTP_200_OK)
async def approve_face_profile(
    employee_id: UUID,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_FACE_ENROLLMENT_MANAGE))],
    service: Annotated[FaceEnrollmentService, Depends(get_face_enrollment_service)],
) -> DataEnvelope[FaceProfileRead]:
    data = await service.approve(
        tenant.company_id,
        employee_id,
        scope=scope,
        caller_employee_id=user.employee_id,
        actor_user_id=tenant.user_id,
        **_client_meta(request),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/attendance/face-profiles/{employee_id}/reject", status_code=status.HTTP_200_OK)
async def reject_face_profile(
    employee_id: UUID,
    body: FaceProfileRejectInput,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_FACE_ENROLLMENT_MANAGE))],
    service: Annotated[FaceEnrollmentService, Depends(get_face_enrollment_service)],
) -> DataEnvelope[FaceProfileRead]:
    data = await service.reject(
        tenant.company_id,
        employee_id,
        note=body.note,
        scope=scope,
        caller_employee_id=user.employee_id,
        actor_user_id=tenant.user_id,
        **_client_meta(request),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.delete("/attendance/face-profiles/{employee_id}", status_code=status.HTTP_200_OK)
async def revoke_face_profile(
    employee_id: UUID,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_FACE_ENROLLMENT_MANAGE))],
    service: Annotated[FaceEnrollmentService, Depends(get_face_enrollment_service)],
) -> DataEnvelope[FaceProfileRead]:
    """Deletes the employee's biometric record at the provider, then marks the profile REVOKED.
    The profile row itself is kept as the audit trail of consent and enrollment."""
    data = await service.revoke(
        tenant.company_id,
        employee_id,
        scope=scope,
        caller_employee_id=user.employee_id,
        actor_user_id=tenant.user_id,
        **_client_meta(request),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


# ---------------------------------------------------------------------------
# Face attendance — employee self-enrollment (ATTENDANCE.PUNCH, SELF)
# ---------------------------------------------------------------------------


@router.get("/attendance/face-enrollment/me", status_code=status.HTTP_200_OK)
async def get_my_face_enrollment(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    _scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_PUNCH))],
    service: Annotated[FaceEnrollmentService, Depends(get_face_enrollment_service)],
) -> DataEnvelope[FaceEnrollmentStatusRead]:
    if user.employee_id is None:
        raise ValidationError("The caller has no linked employee record")
    data = await service.get_status(
        tenant.company_id, user.employee_id, scope=None, caller_employee_id=user.employee_id
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/attendance/face-enrollment/me/window", status_code=status.HTTP_201_CREATED)
async def start_my_face_enrollment(
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    _scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_PUNCH))],
    service: Annotated[FaceEnrollmentService, Depends(get_face_enrollment_service)],
) -> DataEnvelope[FaceEnrollmentWindowRead]:
    """Self-service "Start face enrollment": opens the caller's own one-time window. The employee
    is the authenticated user's own record - there is no employee id in the request."""
    if user.employee_id is None:
        raise ValidationError("The caller has no linked employee record")
    data = await service.open_own_window(
        tenant.company_id, user.employee_id, actor_user_id=tenant.user_id, **_client_meta(request)
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/attendance/face-enrollment/me", status_code=status.HTTP_201_CREATED)
async def submit_my_face_enrollment(
    request: Request,
    _rate_limit: Annotated[None, Depends(face_enrollment_rate_limit)],
    front: Annotated[UploadFile, File()],
    left: Annotated[UploadFile, File()],
    right: Annotated[UploadFile, File()],
    up: Annotated[UploadFile, File()],
    down: Annotated[UploadFile, File()],
    consent_confirmed: Annotated[bool, Form()],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    _scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_PUNCH))],
    service: Annotated[FaceEnrollmentService, Depends(get_face_enrollment_service)],
) -> DataEnvelope[FaceProfileRead]:
    """Self-enrollment inside an HR-opened window. The front capture must pass liveness and
    every other angle must match it; the result waits for HR approval before it can punch."""
    if user.employee_id is None:
        raise ValidationError("The caller has no linked employee record")
    uploads = {"front": front, "left": left, "right": right, "up": up, "down": down}
    images = {
        angle: await read_upload_bounded(upload, max_bytes=FACE_IMAGE_MAX_BYTES)
        for angle, upload in uploads.items()
    }
    data = await service.submit_self(
        tenant.company_id,
        user.employee_id,
        images=images,
        consent_confirmed=consent_confirmed,
        actor_user_id=tenant.user_id,
        **_client_meta(request),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


# ---------------------------------------------------------------------------
# Face attendance — self-service face punch (ATTENDANCE.PUNCH, SELF)
# ---------------------------------------------------------------------------


@router.post("/attendance/face-punches/me/liveness-sessions", status_code=status.HTTP_201_CREATED)
async def create_face_liveness_session(
    body: FaceLivenessSessionCreate,
    _rate_limit: Annotated[None, Depends(face_punch_rate_limit)],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    _scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_PUNCH))],
    service: Annotated[FacePunchService, Depends(get_face_punch_service)],
) -> DataEnvelope[FaceLivenessSessionRead]:
    """Step 1 of a face punch: a short-lived, single-use liveness challenge for the caller's
    next punch in `direction`. Issuing one invalidates any earlier unused one. The app captures
    `frames_required` frames only after receiving it and presents its `session_id` with them."""
    if user.employee_id is None:
        raise ValidationError("The caller has no linked employee record")
    data = await service.issue_liveness_session(
        tenant.company_id,
        user.employee_id,
        direction=body.direction,
        actor_user_id=tenant.user_id,
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/attendance/face-punches/me", status_code=status.HTTP_201_CREATED)
async def create_face_punch(
    request: Request,
    _rate_limit: Annotated[None, Depends(face_punch_rate_limit)],
    direction: Annotated[Literal["IN", "OUT"], Form()],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_PUNCH))],
    service: Annotated[FacePunchService, Depends(get_face_punch_service)],
    frames: Annotated[list[UploadFile] | None, File()] = None,
    liveness_session_id: Annotated[UUID | None, Form()] = None,
    idempotency_key: Annotated[str | None, Form()] = None,
    location_latitude: Annotated[float | None, Form()] = None,
    location_longitude: Annotated[float | None, Form()] = None,
    location_accuracy_m: Annotated[float | None, Form()] = None,
    location_captured_at: Annotated[datetime | None, Form()] = None,
    location_error: Annotated[str | None, Form()] = None,
) -> DataEnvelope[FacePunchRead]:
    """Step 2 of a face punch. Same contract as `POST /attendance/punches/me` — no time, source
    or employee field; the server stamps the instant — plus `liveness_session_id` (from step 1)
    and exactly `frames_required` JPEG/PNG `frames` captured after it was issued. The server runs
    its own liveness model on every frame, then matches the best live frame against the
    caller's enrolled face; only then is a punch written. No client-side liveness result is
    accepted. A request without a challenge (an outdated app sending `photo`) is refused.

    `idempotency_key` (optional, 16-64 of `[A-Za-z0-9_-]`): resend the same key when retrying
    after a lost response (with a fresh challenge and capture) and the original result is
    returned instead of a second punch. The same key with a different direction is a 409."""
    if user.employee_id is None:
        raise ValidationError("The caller has no linked employee record")
    location = parse_form_location(
        latitude=location_latitude,
        longitude=location_longitude,
        accuracy_m=location_accuracy_m,
        captured_at=location_captured_at,
        error=location_error,
    )
    uploads = frames or []
    if len(uploads) > FACE_LIVENESS_MAX_FRAMES:
        raise FaceImageInvalidError(
            f"At most {FACE_LIVENESS_MAX_FRAMES} face frames may be sent", field="frames"
        )
    images = [
        await read_upload_bounded(upload, max_bytes=FACE_LIVENESS_FRAME_MAX_BYTES)
        for upload in uploads
    ]
    data = await service.punch_self(
        tenant.company_id,
        user.employee_id,
        frames=images,
        liveness_session_id=liveness_session_id,
        direction=direction,
        idempotency_key=idempotency_key,
        scope=scope,
        actor_user_id=tenant.user_id,
        location=location,
        location_error=location_error,
        **_client_meta(request),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))
