"""HTTP routes for geofence administration and review.

* Workplace geofences are `Branch` rows; their coordinates/radius are edited on the branch screen
  (`organisation` module). This router adds the attendance-side view with usage counts, the
  administrator-managed extra workplace authorisations, and review of recorded location attempts.
* Authorisation is enforced here, server-side: configuration is `ATTENDANCE.POLICY_MANAGE`
  (COMPANY scope), attempt review is `ATTENDANCE.VIEW_ALL`. The company always comes from the
  authenticated tenant context, never from a request field.
"""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.auth.dependencies import get_current_user
from hrms.core.auth.types import AuthenticatedUser
from hrms.core.db.session import get_session
from hrms.core.errors.base import ValidationError
from hrms.core.rbac.dependencies import require_permission
from hrms.core.rbac.types import DataScope
from hrms.core.tenancy.context import TenantContext, current_request_id
from hrms.core.tenancy.dependencies import get_tenant_context
from hrms.modules.attendance.geofence_schemas import (
    GeofenceAttemptRead,
    GeofencePolicyMeRead,
    GeofenceWorkplaceRead,
    WorkplaceAuthorizationCreate,
    WorkplaceAuthorizationRead,
    attempt_to_read,
    authorization_to_read,
)
from hrms.modules.attendance.geofence_service import GeofenceService
from hrms.modules.attendance.permissions import (
    ATTENDANCE_POLICY_MANAGE,
    ATTENDANCE_PUNCH,
    ATTENDANCE_VIEW_ALL,
)
from hrms.modules.identity.schemas import build_meta
from hrms.shared.pagination import (
    DataEnvelope,
    ListEnvelope,
    PageParams,
    bounded_pagination_params,
    build_pagination_meta,
)

router = APIRouter(tags=["attendance-geofence"])


def _service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> GeofenceService:
    return GeofenceService(session)


Service = Annotated[GeofenceService, Depends(_service)]


@router.get("/attendance/geofence-policy/me", status_code=status.HTTP_200_OK)
async def get_my_geofence_policy(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_PUNCH))],
    service: Service,
) -> DataEnvelope[GeofencePolicyMeRead]:
    """Whether the caller's resolved attendance policy asks for a location on self-service
    punches. Resolved from the authenticated employee only — no employee id is accepted."""
    if user.employee_id is None:
        raise ValidationError("The caller has no linked employee record")
    policy = await service.resolve_policy(tenant.company_id, user.employee_id, datetime.now(UTC))
    return DataEnvelope(
        data=GeofencePolicyMeRead(
            mode=policy.mode,
            max_accuracy_m=policy.max_accuracy_m,
            max_age_seconds=policy.max_age_seconds,
        ),
        meta=build_meta(current_request_id() or "unknown"),
    )


@router.get("/attendance/geofences", status_code=status.HTTP_200_OK)
async def list_geofences(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Service,
) -> ListEnvelope[GeofenceWorkplaceRead]:
    data = await service.list_workplaces(tenant.company_id)
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/attendance/workplace-authorizations", status_code=status.HTTP_200_OK)
async def list_workplace_authorizations(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Service,
    page: Annotated[PageParams, Depends(bounded_pagination_params)],
    employee_id: Annotated[UUID | None, Query()] = None,
    branch_id: Annotated[UUID | None, Query()] = None,
) -> ListEnvelope[WorkplaceAuthorizationRead]:
    rows, total = await service.list_authorizations(
        company_id=tenant.company_id,
        employee_id=employee_id,
        branch_id=branch_id,
        limit=page.limit,
        offset=page.offset,
    )
    return ListEnvelope(
        data=[authorization_to_read(r) for r in rows],
        pagination=build_pagination_meta(page, total=total),
        meta=build_meta(current_request_id() or "unknown"),
    )


@router.post("/attendance/workplace-authorizations", status_code=status.HTTP_201_CREATED)
async def add_workplace_authorization(
    body: WorkplaceAuthorizationCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Service,
) -> DataEnvelope[WorkplaceAuthorizationRead]:
    row = await service.add_authorization(
        tenant.company_id,
        employee_id=body.employee_id,
        branch_id=body.branch_id,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(
        data=authorization_to_read(row), meta=build_meta(current_request_id() or "unknown")
    )


@router.delete(
    "/attendance/workplace-authorizations/{authorization_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_workplace_authorization(
    authorization_id: UUID,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_POLICY_MANAGE))],
    service: Service,
) -> Response:
    await service.remove_authorization(
        tenant.company_id,
        authorization_id,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/attendance/geofence-attempts", status_code=status.HTTP_200_OK)
async def list_geofence_attempts(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_VIEW_ALL))],
    service: Service,
    page: Annotated[PageParams, Depends(bounded_pagination_params)],
    employee_id: Annotated[UUID | None, Query()] = None,
    accepted: Annotated[bool | None, Query()] = None,
    outcome: Annotated[str | None, Query(max_length=40)] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
) -> ListEnvelope[GeofenceAttemptRead]:
    """Recorded location evaluations, newest first — including rejected attempts HR may need to
    review. A rejection is never turned into attendance here: a legitimate case is corrected
    through the existing regularization workflow (reason mandatory, approval audited)."""
    rows, total = await service.list_attempts(
        company_id=tenant.company_id,
        scope=scope,
        caller_employee_id=user.employee_id,
        employee_id=employee_id,
        accepted=accepted,
        outcome=outcome,
        since=since,
        until=until,
        limit=page.limit,
        offset=page.offset,
    )
    return ListEnvelope(
        data=[attempt_to_read(r) for r in rows],
        pagination=build_pagination_meta(page, total=total),
        meta=build_meta(current_request_id() or "unknown"),
    )
