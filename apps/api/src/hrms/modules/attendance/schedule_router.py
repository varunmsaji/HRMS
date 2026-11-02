"""HTTP routes for the weekly operational schedule and shift-swap requests.

Reads are `ATTENDANCE.VIEW` (data-scoped); creating and deciding swaps needs
`ATTENDANCE.ROSTER_MANAGE`.
"""

from datetime import date, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.auth.dependencies import get_current_user
from hrms.core.auth.types import AuthenticatedUser
from hrms.core.db.session import get_session
from hrms.core.rbac.dependencies import require_permission
from hrms.core.rbac.types import DataScope
from hrms.core.tenancy.context import TenantContext, current_request_id
from hrms.core.tenancy.dependencies import get_tenant_context
from hrms.modules.attendance.permissions import ATTENDANCE_ROSTER_MANAGE, ATTENDANCE_VIEW
from hrms.modules.attendance.schedule_service import (
    RosterScheduleService,
    SwapDecision,
    SwapRequestCreate,
    SwapRequestRead,
    WeeklySchedule,
)
from hrms.modules.identity.schemas import build_meta
from hrms.shared.pagination import DataEnvelope, ListEnvelope

router = APIRouter(tags=["attendance-roster-schedule"])


def _service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> RosterScheduleService:
    return RosterScheduleService(session)


@router.get("/rosters/weekly-schedule")
async def weekly_schedule(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_VIEW))],
    service: Annotated[RosterScheduleService, Depends(_service)],
    week_start: Annotated[date | None, Query()] = None,
    branch_id: Annotated[UUID | None, Query()] = None,
    department_id: Annotated[UUID | None, Query()] = None,
) -> DataEnvelope[WeeklySchedule]:
    """Headcount per shift per day for the Monday-based week containing `week_start`."""
    if week_start is None:
        week_start = date.today()
    monday = week_start - timedelta(days=week_start.weekday())
    data = await service.weekly_schedule(
        tenant.company_id,
        week_start=monday,
        branch_id=branch_id,
        department_id=department_id,
        scope=scope,
        caller_employee_id=user.employee_id,
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/rosters/swap-requests")
async def list_swap_requests(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_VIEW))],
    service: Annotated[RosterScheduleService, Depends(_service)],
    swap_status: Annotated[
        str | None, Query(alias="status", pattern="^(PENDING|APPROVED|DECLINED)$")
    ] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
) -> ListEnvelope[SwapRequestRead]:
    data = await service.list_swaps(
        tenant.company_id,
        status=swap_status,
        date_from=date_from,
        date_to=date_to,
        scope=scope,
        caller_employee_id=user.employee_id,
    )
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/rosters/swap-requests", status_code=201)
async def create_swap_request(
    body: SwapRequestCreate,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_ROSTER_MANAGE))],
    service: Annotated[RosterScheduleService, Depends(_service)],
) -> DataEnvelope[SwapRequestRead]:
    data = await service.create_swap(
        tenant.company_id,
        body,
        scope=scope,
        caller_employee_id=user.employee_id,
        actor_user_id=tenant.user_id,
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


async def _decide(
    swap_id: UUID,
    body: SwapDecision,
    approve: bool,
    tenant: TenantContext,
    user: AuthenticatedUser,
    scope: DataScope,
    service: RosterScheduleService,
) -> DataEnvelope[SwapRequestRead]:
    data = await service.decide(
        tenant.company_id,
        swap_id,
        approve=approve,
        note=body.note,
        scope=scope,
        caller_employee_id=user.employee_id,
        actor_user_id=tenant.user_id,
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/rosters/swap-requests/{swap_id}/approve")
async def approve_swap_request(
    swap_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_ROSTER_MANAGE))],
    service: Annotated[RosterScheduleService, Depends(_service)],
    body: SwapDecision | None = None,
) -> DataEnvelope[SwapRequestRead]:
    return await _decide(swap_id, body or SwapDecision(), True, tenant, user, scope, service)


@router.post("/rosters/swap-requests/{swap_id}/decline")
async def decline_swap_request(
    swap_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(ATTENDANCE_ROSTER_MANAGE))],
    service: Annotated[RosterScheduleService, Depends(_service)],
    body: SwapDecision | None = None,
) -> DataEnvelope[SwapRequestRead]:
    return await _decide(swap_id, body or SwapDecision(), False, tenant, user, scope, service)
