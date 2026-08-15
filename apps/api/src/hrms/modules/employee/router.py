"""HTTP routes for the employee module — thin layer only, per Module Standard §2.

Data-scope enforcement (`SELF`/`REPORTEES`/`REPORTEE_TREE`, `docs/product/
19_RBAC_and_Permission_Matrix.md` §5) is not implemented in this slice — there is no
`employee_assignment`/reporting-manager data yet for a scope to resolve against (that's E-04).
Until then: `EMPLOYEE.VIEW_ALL` gates the company-wide list; `EMPLOYEE.VIEW` gates looking up a
single employee by id (not scoped to self/team — a known limitation, not a designed behavior,
`01_EMPLOYEE_FOUNDATION_AUDIT.md` §2.4/§6).

E-03 (employment lifecycle) adds the `/employees/{employee_id}/employments*` sub-resource
routes, same scoping caveat as above (`EMPLOYEE.VIEW`, not self/team-scoped).
"""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, status

from hrms.core.auth.dependencies import get_current_user
from hrms.core.auth.types import AuthenticatedUser
from hrms.core.errors.base import PermissionDeniedError
from hrms.core.rbac.dependencies import get_rbac_service, require_permission
from hrms.core.rbac.service import RbacService
from hrms.core.tenancy.context import TenantContext, current_request_id
from hrms.core.tenancy.dependencies import get_tenant_context
from hrms.modules.employee.dependencies import (
    get_employee_assignment_service,
    get_employee_compensation_service,
    get_employee_service,
    get_employment_service,
)
from hrms.modules.employee.permissions import (
    EMPLOYEE_CREATE,
    EMPLOYEE_DEACTIVATE,
    EMPLOYEE_PROMOTE,
    EMPLOYEE_TERMINATE,
    EMPLOYEE_TRANSFER,
    EMPLOYEE_UPDATE,
    EMPLOYEE_UPDATE_COMPENSATION,
    EMPLOYEE_VIEW_ALL,
    EMPLOYEE_VIEW_COMPENSATION,
)
from hrms.modules.employee.schemas import (
    AssignmentCreate,
    AssignmentRead,
    CompensationCreate,
    CompensationRead,
    EmployeeCreate,
    EmployeeRead,
    EmployeeUpdate,
    EmploymentCreate,
    EmploymentRead,
    EmploymentTerminate,
    EmploymentUpdate,
)
from hrms.modules.employee.service import (
    EmployeeAssignmentService,
    EmployeeCompensationService,
    EmployeeService,
    EmploymentService,
)
from hrms.modules.identity.permissions import EMPLOYEE_VIEW
from hrms.modules.identity.schemas import build_meta
from hrms.shared.pagination import DataEnvelope, ListEnvelope

router = APIRouter(tags=["employee"])


@router.get("/employees", status_code=status.HTTP_200_OK)
async def list_employees(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(EMPLOYEE_VIEW_ALL))],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
) -> ListEnvelope[EmployeeRead]:
    data = await service.list_employees(tenant.company_id)
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/employees", status_code=status.HTTP_201_CREATED)
async def create_employee(
    body: EmployeeCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(EMPLOYEE_CREATE))],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
) -> DataEnvelope[EmployeeRead]:
    data = await service.create_employee(
        tenant.company_id,
        body,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/employees/{employee_id}", status_code=status.HTTP_200_OK)
async def get_employee(
    employee_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(EMPLOYEE_VIEW))],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
) -> DataEnvelope[EmployeeRead]:
    data = await service.get_employee(tenant.company_id, employee_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.patch("/employees/{employee_id}", status_code=status.HTTP_200_OK)
async def update_employee(
    employee_id: UUID,
    body: EmployeeUpdate,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(EMPLOYEE_UPDATE))],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
) -> DataEnvelope[EmployeeRead]:
    data = await service.update_employee(
        tenant.company_id,
        employee_id,
        body,
        expected_version=int(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.delete("/employees/{employee_id}", status_code=status.HTTP_200_OK)
async def deactivate_employee(
    employee_id: UUID,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(EMPLOYEE_DEACTIVATE))],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
) -> DataEnvelope[EmployeeRead]:
    """Soft deactivation only — never a hard delete; returns the updated resource with
    `is_active=false` rather than 204, matching this API's envelope convention."""
    data = await service.deactivate_employee(
        tenant.company_id,
        employee_id,
        expected_version=int(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


# --- Employment (E-03) --------------------------------------------------------------------


@router.post(
    "/employees/{employee_id}/employments",
    status_code=status.HTTP_201_CREATED,
)
async def create_employment(
    employee_id: UUID,
    body: EmploymentCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(EMPLOYEE_CREATE))],
    service: Annotated[EmploymentService, Depends(get_employment_service)],
) -> DataEnvelope[EmploymentRead]:
    """Creates a new employment episode for an existing employee — covers both a first hire
    and a rehire (server-detected: `previous_employment_id` is populated automatically when
    the employee already has a prior, necessarily-terminated, episode)."""
    data = await service.create_employment(
        tenant.company_id,
        employee_id,
        body,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get(
    "/employees/{employee_id}/employments",
    status_code=status.HTTP_200_OK,
)
async def list_employments(
    employee_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(EMPLOYEE_VIEW))],
    service: Annotated[EmploymentService, Depends(get_employment_service)],
    as_of: Annotated[date | None, Query()] = None,
) -> ListEnvelope[EmploymentRead]:
    """Full employment history for the employee, ordered by `joining_date`, or — with
    `?as_of=YYYY-MM-DD` — the single episode (if any) covering that date."""
    data = await service.list_employments(tenant.company_id, employee_id, as_of=as_of)
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get(
    "/employees/{employee_id}/employments/{employment_id}",
    status_code=status.HTTP_200_OK,
)
async def get_employment(
    employee_id: UUID,
    employment_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(EMPLOYEE_VIEW))],
    service: Annotated[EmploymentService, Depends(get_employment_service)],
) -> DataEnvelope[EmploymentRead]:
    data = await service.get_employment(tenant.company_id, employee_id, employment_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.patch(
    "/employees/{employee_id}/employments/{employment_id}",
    status_code=status.HTTP_200_OK,
)
async def update_employment(
    employee_id: UUID,
    employment_id: UUID,
    body: EmploymentUpdate,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(EMPLOYEE_UPDATE))],
    service: Annotated[EmploymentService, Depends(get_employment_service)],
) -> DataEnvelope[EmploymentRead]:
    data = await service.update_employment(
        tenant.company_id,
        employee_id,
        employment_id,
        body,
        expected_version=int(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post(
    "/employees/{employee_id}/employments/{employment_id}/terminate",
    status_code=status.HTTP_200_OK,
)
async def terminate_employment(
    employee_id: UUID,
    employment_id: UUID,
    body: EmploymentTerminate,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(EMPLOYEE_TERMINATE))],
    service: Annotated[EmploymentService, Depends(get_employment_service)],
) -> DataEnvelope[EmploymentRead]:
    """Transitions the current episode `ACTIVE` → `TERMINATED` — one-way, never reversed. A
    later rejoin is a new `POST .../employments` call, not an action on this row."""
    data = await service.terminate_employment(
        tenant.company_id,
        employee_id,
        employment_id,
        body,
        expected_version=int(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


# --- Employee Assignment (E-04) ------------------------------------------------------------
#
# No `PATCH`/`DELETE` on an individual assignment row (`03_EMPLOYEE_API_PLAN.md` §2.2) — every
# change is `POST .../assignments` with a new `change_type`. Which permission gates the POST is
# selected by the request body's own `change_type`
# (`09_EMPLOYEE_ASSIGNMENT_IMPLEMENTATION_PLAN.md` §14.2), so — unlike every other route in this
# module — it cannot be expressed as a single static `Depends(require_permission(CODE))`; the
# check is performed explicitly below, after the body is parsed, rather than via a dependency
# that would need to re-parse the request body itself.


@router.get(
    "/employees/{employee_id}/assignments",
    status_code=status.HTTP_200_OK,
)
async def list_assignments(
    employee_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(EMPLOYEE_VIEW))],
    service: Annotated[EmployeeAssignmentService, Depends(get_employee_assignment_service)],
    as_of: Annotated[date | None, Query()] = None,
) -> ListEnvelope[AssignmentRead]:
    """Full effective-dated assignment history for the employee, ordered by `effective_from`,
    or — with `?as_of=YYYY-MM-DD` — the single row (if any) covering that date."""
    data = await service.list_assignments(tenant.company_id, employee_id, as_of=as_of)
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get(
    "/employees/{employee_id}/assignments/{assignment_id}",
    status_code=status.HTTP_200_OK,
)
async def get_assignment(
    employee_id: UUID,
    assignment_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(EMPLOYEE_VIEW))],
    service: Annotated[EmployeeAssignmentService, Depends(get_employee_assignment_service)],
) -> DataEnvelope[AssignmentRead]:
    data = await service.get_assignment(tenant.company_id, employee_id, assignment_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post(
    "/employees/{employee_id}/assignments",
    status_code=status.HTTP_201_CREATED,
)
async def create_assignment(
    employee_id: UUID,
    body: AssignmentCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    rbac: Annotated[RbacService, Depends(get_rbac_service)],
    service: Annotated[EmployeeAssignmentService, Depends(get_employee_assignment_service)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> DataEnvelope[AssignmentRead]:
    """Closes the employee's current assignment row (if any) and inserts a new one — covers
    initial placement, transfer, promotion, and manager change alike, distinguished only by
    `change_type`. `If-Match` is required only when a current row exists (nothing to
    version-check for an employee's very first assignment)."""
    required_permission = EMPLOYEE_PROMOTE if body.change_type == "PROMOTION" else EMPLOYEE_TRANSFER
    if not await rbac.has_permission(user.user_id, user.company_id, required_permission):
        raise PermissionDeniedError(
            f"Permission {required_permission} is required", code="PERMISSION_DENIED"
        )
    data = await service.create_assignment(
        tenant.company_id,
        employee_id,
        body,
        expected_version=int(if_match) if if_match is not None else None,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


# --- Employee Compensation (E-06) -----------------------------------------------------------
#
# Unlike Assignment's `POST .../assignments`, `.VIEW_COMPENSATION`/`.UPDATE_COMPENSATION` map
# 1:1 to GET/POST — no dynamic permission selection by request body is needed
# (`docs/modules/employee/17_EMPLOYEE_COMPENSATION_IMPLEMENTATION_PLAN.md` §23 step 9).


@router.get(
    "/employees/{employee_id}/compensation",
    status_code=status.HTTP_200_OK,
)
async def list_compensations(
    employee_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(EMPLOYEE_VIEW_COMPENSATION))],
    service: Annotated[EmployeeCompensationService, Depends(get_employee_compensation_service)],
    as_of: Annotated[date | None, Query()] = None,
) -> ListEnvelope[CompensationRead]:
    """Full effective-dated compensation history for the employee, ordered by
    `effective_from`, or — with `?as_of=YYYY-MM-DD` — the single row (if any) covering that
    date."""
    data = await service.list_compensations(tenant.company_id, employee_id, as_of=as_of)
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get(
    "/employees/{employee_id}/compensation/{compensation_id}",
    status_code=status.HTTP_200_OK,
)
async def get_compensation(
    employee_id: UUID,
    compensation_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(EMPLOYEE_VIEW_COMPENSATION))],
    service: Annotated[EmployeeCompensationService, Depends(get_employee_compensation_service)],
) -> DataEnvelope[CompensationRead]:
    data = await service.get_compensation(tenant.company_id, employee_id, compensation_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post(
    "/employees/{employee_id}/compensation",
    status_code=status.HTTP_201_CREATED,
)
async def create_compensation(
    employee_id: UUID,
    body: CompensationCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(EMPLOYEE_UPDATE_COMPENSATION))],
    service: Annotated[EmployeeCompensationService, Depends(get_employee_compensation_service)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> DataEnvelope[CompensationRead]:
    """Closes the employee's current compensation row (if any) and inserts a new one — covers
    an employee's first CTC and every later revision alike. `If-Match` is required only when a
    current row exists; nothing to version-check for an employee's very first compensation
    row."""
    data = await service.create_compensation(
        tenant.company_id,
        employee_id,
        body,
        expected_version=int(if_match) if if_match is not None else None,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))
