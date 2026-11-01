"""HTTP routes for break events (break management V1).

Authorization is static per route and enforced server-side:

* employee self-service start / end / state — `ATTENDANCE.PUNCH` (SELF); the employee is always
  the authenticated caller, the instant is the server clock, and the source is never a request
  field;
* review of events and the resolved rules — `ATTENDANCE.VIEW` (data-scoped);
* correcting an unresolved or disputed break — `ATTENDANCE.REGULARIZATION_APPROVE`, never the
  employee's own break. The company always comes from the authenticated tenant context.
"""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.auth.dependencies import get_current_user
from hrms.core.auth.types import AuthenticatedUser
from hrms.core.db.session import get_session
from hrms.core.errors.base import ValidationError
from hrms.core.rbac.dependencies import require_permission
from hrms.core.rbac.types import DataScope
from hrms.core.tenancy.context import TenantContext, current_request_id
from hrms.core.tenancy.dependencies import get_tenant_context
from hrms.modules.attendance.break_override_service import EmployeeBreakOverrideService
from hrms.modules.attendance.break_schemas import (
    BreakActionSelf,
    BreakDayRead,
    BreakEventRead,
    BreakResolveInput,
    BreakStateRead,
    EmployeeBreakOverrideCreate,
    EmployeeBreakOverrideRead,
    EmployeeBreakOverrideRevoke,
    ResolvedBreakRulesRead,
)
from hrms.modules.attendance.break_service import BreakEventService
from hrms.modules.attendance.permissions import (
    ATTENDANCE_PUNCH,
    ATTENDANCE_REGULARIZATION_APPROVE,
    ATTENDANCE_ROSTER_MANAGE,
    ATTENDANCE_VIEW,
)
from hrms.modules.identity.schemas import build_meta
from hrms.shared.pagination import DataEnvelope, ResponseMeta

router = APIRouter(tags=["attendance-breaks"])

_MAX_RANGE_DAYS = 62


def _service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> BreakEventService:
    return BreakEventService(session)


Service = Annotated[BreakEventService, Depends(_service)]


def _meta() -> ResponseMeta:
    return build_meta(current_request_id() or "unknown")


def _own_employee(user: AuthenticatedUser) -> UUID:
    if user.employee_id is None:
        raise ValidationError("The caller has no linked employee record")
    return user.employee_id


def _client(request: Request) -> tuple[str | None, str | None]:
    return (request.client.host if request.client else None, request.headers.get("User-Agent"))


@router.get("/attendance/breaks/me/state", status_code=status.HTTP_200_OK)
async def get_my_break_state(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_PUNCH))],
    service: Service,
) -> DataEnvelope[BreakStateRead]:
    employee_id = _own_employee(user)
    data = await service.get_state(
        tenant.company_id, employee_id, scope=scope, caller_employee_id=user.employee_id
    )
    return DataEnvelope(data=data, meta=_meta())


@router.post("/attendance/breaks/me/start", status_code=status.HTTP_200_OK)
async def start_my_break(
    body: BreakActionSelf,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_PUNCH))],
    service: Service,
) -> DataEnvelope[BreakStateRead]:
    ip, agent = _client(request)
    data = await service.start_break(
        tenant.company_id,
        _own_employee(user),
        body,
        scope=scope,
        caller_employee_id=user.employee_id,
        actor_user_id=tenant.user_id,
        ip_address=ip,
        user_agent=agent,
    )
    return DataEnvelope(data=data, meta=_meta())


@router.post("/attendance/breaks/me/end", status_code=status.HTTP_200_OK)
async def end_my_break(
    body: BreakActionSelf,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_PUNCH))],
    service: Service,
) -> DataEnvelope[BreakStateRead]:
    ip, agent = _client(request)
    data = await service.end_break(
        tenant.company_id,
        _own_employee(user),
        body,
        scope=scope,
        caller_employee_id=user.employee_id,
        actor_user_id=tenant.user_id,
        ip_address=ip,
        user_agent=agent,
    )
    return DataEnvelope(data=data, meta=_meta())


@router.get("/attendance/breaks/events", status_code=status.HTTP_200_OK)
async def list_break_events(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_VIEW))],
    service: Service,
    date_from: Annotated[date, Query()],
    date_to: Annotated[date, Query()],
    employee_id: Annotated[UUID | None, Query()] = None,
) -> DataEnvelope[list[BreakEventRead]]:
    if date_to < date_from or (date_to - date_from).days > _MAX_RANGE_DAYS:
        raise ValidationError(f"date range must be 0-{_MAX_RANGE_DAYS} days")
    data = await service.list_events(
        tenant.company_id,
        scope=scope,
        caller_employee_id=user.employee_id,
        employee_id=employee_id,
        date_from=date_from,
        date_to=date_to,
    )
    return DataEnvelope(data=data, meta=_meta())


@router.get("/attendance/breaks/day", status_code=status.HTTP_200_OK)
async def get_break_day(
    employee_id: Annotated[UUID, Query()],
    date_param: Annotated[date, Query(alias="date")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_VIEW))],
    service: Service,
) -> DataEnvelope[BreakDayRead]:
    data = await service.day_events(
        tenant.company_id,
        employee_id,
        date_param,
        scope=scope,
        caller_employee_id=user.employee_id,
    )
    return DataEnvelope(data=data, meta=_meta())


@router.get("/attendance/breaks/resolved-rules", status_code=status.HTTP_200_OK)
async def get_resolved_break_rules(
    employee_id: Annotated[UUID, Query()],
    date_param: Annotated[date, Query(alias="date")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_VIEW))],
    service: Service,
) -> DataEnvelope[ResolvedBreakRulesRead]:
    data = await service.resolved_rules(
        tenant.company_id,
        employee_id,
        date_param,
        scope=scope,
        caller_employee_id=user.employee_id,
    )
    return DataEnvelope(data=data, meta=_meta())


@router.post("/attendance/breaks/resolve", status_code=status.HTTP_200_OK)
async def resolve_break(
    body: BreakResolveInput,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_REGULARIZATION_APPROVE))],
    service: Service,
) -> DataEnvelope[BreakDayRead]:
    ip, agent = _client(request)
    data = await service.resolve_break(
        tenant.company_id,
        body,
        scope=scope,
        caller_employee_id=user.employee_id,
        actor_user_id=tenant.user_id,
        ip_address=ip,
        user_agent=agent,
    )
    return DataEnvelope(data=data, meta=_meta())


def _override_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> EmployeeBreakOverrideService:
    return EmployeeBreakOverrideService(session)


OverrideService = Annotated[EmployeeBreakOverrideService, Depends(_override_service)]


@router.post("/attendance/break-overrides", status_code=status.HTTP_201_CREATED)
async def create_break_override(
    body: EmployeeBreakOverrideCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_ROSTER_MANAGE))],
    service: OverrideService,
) -> DataEnvelope[EmployeeBreakOverrideRead]:
    ip, agent = _client(request)
    data = await service.create(
        tenant.company_id,
        body,
        scope=scope,
        caller_employee_id=user.employee_id,
        actor_user_id=tenant.user_id,
        ip_address=ip,
        user_agent=agent,
    )
    return DataEnvelope(data=data, meta=_meta())


@router.get("/attendance/break-overrides", status_code=status.HTTP_200_OK)
async def list_break_overrides(
    employee_id: Annotated[UUID, Query()],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_VIEW))],
    service: OverrideService,
    include_revoked: Annotated[bool, Query()] = False,
) -> DataEnvelope[list[EmployeeBreakOverrideRead]]:
    data = await service.list_for_employee(
        tenant.company_id,
        employee_id,
        include_revoked=include_revoked,
        scope=scope,
        caller_employee_id=user.employee_id,
    )
    return DataEnvelope(data=data, meta=_meta())


@router.post("/attendance/break-overrides/{override_id}/revoke", status_code=status.HTTP_200_OK)
async def revoke_break_override(
    override_id: UUID,
    body: EmployeeBreakOverrideRevoke,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_ROSTER_MANAGE))],
    service: OverrideService,
) -> DataEnvelope[EmployeeBreakOverrideRead]:
    ip, agent = _client(request)
    data = await service.revoke(
        tenant.company_id,
        override_id,
        body.reason,
        scope=scope,
        caller_employee_id=user.employee_id,
        actor_user_id=tenant.user_id,
        ip_address=ip,
        user_agent=agent,
    )
    return DataEnvelope(data=data, meta=_meta())
