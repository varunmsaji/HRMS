"""Admin endpoints for shadow face-provider comparison (see `face_comparison.py`). All require
`ATTENDANCE.FACE_ENROLLMENT_MANAGE`; none is reachable by an ordinary employee, and none can alter
a punch or an attendance record."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from pydantic import BaseModel

from hrms.core.auth.dependencies import get_current_user
from hrms.core.auth.types import AuthenticatedUser
from hrms.core.rbac.dependencies import require_permission
from hrms.core.rbac.types import DataScope
from hrms.core.tenancy.context import TenantContext, current_request_id
from hrms.core.tenancy.dependencies import get_tenant_context
from hrms.core.uploads import read_upload_bounded
from hrms.modules.attendance.dependencies import get_face_comparison_admin_service
from hrms.modules.attendance.face_comparison_admin import (
    ComparisonRead,
    ComparisonSummary,
    FaceComparisonAdminService,
    ShadowEnrollmentRead,
)
from hrms.modules.attendance.permissions import ATTENDANCE_FACE_ENROLLMENT_MANAGE
from hrms.modules.attendance.schemas import FACE_IMAGE_MAX_BYTES
from hrms.modules.identity.schemas import build_meta
from hrms.shared.pagination import (
    DataEnvelope,
    ListEnvelope,
    PageParams,
    ResponseMeta,
    bounded_pagination_params,
    build_pagination_meta,
)

router = APIRouter(tags=["attendance"])

Manage = Annotated[DataScope, Depends(require_permission(ATTENDANCE_FACE_ENROLLMENT_MANAGE))]
Service = Annotated[FaceComparisonAdminService, Depends(get_face_comparison_admin_service)]
Tenant = Annotated[TenantContext, Depends(get_tenant_context)]
User = Annotated[AuthenticatedUser, Depends(get_current_user)]


class GroundTruthInput(BaseModel):
    ground_truth: Literal["GENUINE", "IMPOSTOR"] | None


def _meta() -> ResponseMeta:
    return build_meta(current_request_id() or "unknown")


@router.get("/attendance/face-verification-comparisons", status_code=status.HTTP_200_OK)
async def list_face_comparisons(
    tenant: Tenant,
    user: User,
    scope: Manage,
    service: Service,
    page: Annotated[PageParams, Depends(bounded_pagination_params)],
    date_from: Annotated[datetime | None, Query()] = None,
    date_to: Annotated[datetime | None, Query()] = None,
    employee_id: Annotated[UUID | None, Query()] = None,
    primary_provider: Annotated[
        Literal["opensource", "facepp", "azure", "compreface"] | None, Query()
    ] = None,
    shadow_provider: Annotated[
        Literal["opensource", "facepp", "azure", "compreface"] | None, Query()
    ] = None,
    agreement: Annotated[Literal["agree", "disagree"] | None, Query()] = None,
    errors_only: Annotated[bool, Query()] = False,
) -> ListEnvelope[ComparisonRead]:
    data, total = await service.list_comparisons(
        tenant.company_id,
        page,
        scope=scope,
        caller_employee_id=user.employee_id,
        date_from=date_from,
        date_to=date_to,
        employee_id=employee_id,
        primary_provider=primary_provider,
        shadow_provider=shadow_provider,
        agreement=agreement,
        errors_only=errors_only,
    )
    return ListEnvelope(
        data=data, pagination=build_pagination_meta(page, total=total), meta=_meta()
    )


@router.get("/attendance/face-verification-comparisons/summary", status_code=status.HTTP_200_OK)
async def face_comparison_summary(
    tenant: Tenant,
    user: User,
    scope: Manage,
    service: Service,
    date_from: Annotated[datetime | None, Query()] = None,
    date_to: Annotated[datetime | None, Query()] = None,
    employee_id: Annotated[UUID | None, Query()] = None,
    primary_provider: Annotated[
        Literal["opensource", "facepp", "azure", "compreface"] | None, Query()
    ] = None,
    shadow_provider: Annotated[
        Literal["opensource", "facepp", "azure", "compreface"] | None, Query()
    ] = None,
    agreement: Annotated[Literal["agree", "disagree"] | None, Query()] = None,
    errors_only: Annotated[bool, Query()] = False,
) -> DataEnvelope[ComparisonSummary]:
    data = await service.summary(
        tenant.company_id,
        scope=scope,
        caller_employee_id=user.employee_id,
        date_from=date_from,
        date_to=date_to,
        employee_id=employee_id,
        primary_provider=primary_provider,
        shadow_provider=shadow_provider,
        agreement=agreement,
        errors_only=errors_only,
    )
    return DataEnvelope(data=data, meta=_meta())


@router.patch(
    "/attendance/face-verification-comparisons/{comparison_id}/ground-truth",
    status_code=status.HTTP_200_OK,
)
async def label_face_comparison(
    comparison_id: UUID,
    body: GroundTruthInput,
    tenant: Tenant,
    user: User,
    scope: Manage,
    service: Service,
) -> DataEnvelope[ComparisonRead]:
    data = await service.label(
        tenant.company_id,
        comparison_id,
        body.ground_truth,
        scope=scope,
        caller_employee_id=user.employee_id,
    )
    return DataEnvelope(data=data, meta=_meta())


@router.get("/attendance/face-shadow-enrollments", status_code=status.HTTP_200_OK)
async def list_face_shadow_enrollments(
    tenant: Tenant, user: User, scope: Manage, service: Service
) -> DataEnvelope[list[ShadowEnrollmentRead]]:
    return DataEnvelope(
        data=await service.list_shadow(
            tenant.company_id, scope=scope, caller_employee_id=user.employee_id
        ),
        meta=_meta(),
    )


@router.post(
    "/attendance/face-shadow-enrollments/{employee_id}", status_code=status.HTTP_201_CREATED
)
async def create_face_shadow_enrollment(
    employee_id: UUID,
    photos: Annotated[list[UploadFile], File()],
    consent_confirmed: Annotated[bool, Form()],
    tenant: Tenant,
    user: User,
    scope: Manage,
    service: Service,
) -> DataEnvelope[ShadowEnrollmentRead]:
    """Enrols a consenting test participant with the SHADOW provider only (1-8 photos). Used to
    prepare a comparison trial; it does not create, alter or approve a production face profile."""
    images = [await read_upload_bounded(p, max_bytes=FACE_IMAGE_MAX_BYTES) for p in photos[:9]]
    data = await service.enroll_shadow(
        tenant.company_id,
        employee_id,
        photos=images,
        consent_confirmed=consent_confirmed,
        scope=scope,
        caller_employee_id=user.employee_id,
        actor_user_id=tenant.user_id,
    )
    return DataEnvelope(data=data, meta=_meta())


@router.delete(
    "/attendance/face-shadow-enrollments/{employee_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_face_shadow_enrollment(
    employee_id: UUID,
    tenant: Tenant,
    user: User,
    scope: Manage,
    service: Service,
) -> None:
    await service.delete_shadow(
        tenant.company_id, employee_id, scope=scope, caller_employee_id=user.employee_id
    )
