"""HTTP routes for the Payroll module — thin layer only, per Module Standard §2.

Phase 5.1: salary setup. Components, structures and salary assignment are COMPANY-scoped config
gated by `PAYROLL.SETUP_MANAGE`. An employee's salary history and breakup are compensation data,
read under `EMPLOYEE.VIEW_COMPENSATION` with its `DataScope` applied to the target employee."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, status

from hrms.core.auth.dependencies import get_current_user
from hrms.core.auth.types import AuthenticatedUser
from hrms.core.rbac.dependencies import require_permission
from hrms.core.rbac.types import DataScope
from hrms.core.tenancy.context import TenantContext, current_request_id
from hrms.core.tenancy.dependencies import get_tenant_context
from hrms.modules.employee.permissions import EMPLOYEE_VIEW_COMPENSATION
from hrms.modules.identity.schemas import build_meta
from hrms.modules.payroll.dependencies import (
    get_employee_salary_service,
    get_salary_component_service,
    get_salary_structure_service,
)
from hrms.modules.payroll.permissions import PAYROLL_SETUP_MANAGE
from hrms.modules.payroll.schemas import (
    EmployeeSalaryBreakupRead,
    EmployeeSalaryBulkAssign,
    EmployeeSalaryBulkResult,
    EmployeeSalaryCreate,
    EmployeeSalaryRead,
    SalaryBreakupPreviewInput,
    SalaryBreakupRead,
    SalaryComponentCreate,
    SalaryComponentRead,
    SalaryComponentUpdate,
    SalaryStructureCreate,
    SalaryStructureRead,
    SalaryStructureUpdate,
    SalaryStructureVersionCreate,
    SalaryStructureVersionLinesUpdate,
    SalaryStructureVersionPublish,
)
from hrms.modules.payroll.service import (
    EmployeeSalaryService,
    SalaryComponentService,
    SalaryStructureService,
)
from hrms.shared.pagination import DataEnvelope, ListEnvelope, ResponseMeta

router = APIRouter(tags=["payroll"])

_SetupScope = Annotated[object, Depends(require_permission(PAYROLL_SETUP_MANAGE))]
_Tenant = Annotated[TenantContext, Depends(get_tenant_context)]
_Components = Annotated[SalaryComponentService, Depends(get_salary_component_service)]
_Structures = Annotated[SalaryStructureService, Depends(get_salary_structure_service)]
_Salaries = Annotated[EmployeeSalaryService, Depends(get_employee_salary_service)]


def _meta() -> ResponseMeta:
    return build_meta(current_request_id() or "unknown")


def _client(request: Request) -> dict[str, str | None]:
    return {
        "ip_address": request.client.host if request.client else None,
        "user_agent": request.headers.get("User-Agent"),
    }


# ---------------------------------------------------------------------------
# Salary components
# ---------------------------------------------------------------------------


@router.get("/payroll/salary-components", status_code=status.HTTP_200_OK)
async def list_salary_components(
    tenant: _Tenant, _scope: _SetupScope, service: _Components
) -> ListEnvelope[SalaryComponentRead]:
    return ListEnvelope(data=await service.list_components(tenant.company_id), meta=_meta())


@router.post("/payroll/salary-components", status_code=status.HTTP_201_CREATED)
async def create_salary_component(
    body: SalaryComponentCreate,
    request: Request,
    tenant: _Tenant,
    _scope: _SetupScope,
    service: _Components,
) -> DataEnvelope[SalaryComponentRead]:
    data = await service.create(
        tenant.company_id, body, actor_user_id=tenant.user_id, **_client(request)
    )
    return DataEnvelope(data=data, meta=_meta())


@router.patch("/payroll/salary-components/{component_id}", status_code=status.HTTP_200_OK)
async def update_salary_component(
    component_id: UUID,
    body: SalaryComponentUpdate,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: _Tenant,
    _scope: _SetupScope,
    service: _Components,
) -> DataEnvelope[SalaryComponentRead]:
    data = await service.update(
        tenant.company_id,
        component_id,
        body,
        expected_version=int(if_match),
        actor_user_id=tenant.user_id,
        **_client(request),
    )
    return DataEnvelope(data=data, meta=_meta())


# ---------------------------------------------------------------------------
# Salary structures
# ---------------------------------------------------------------------------


@router.get("/payroll/salary-structures", status_code=status.HTTP_200_OK)
async def list_salary_structures(
    tenant: _Tenant, _scope: _SetupScope, service: _Structures
) -> ListEnvelope[SalaryStructureRead]:
    return ListEnvelope(data=await service.list_structures(tenant.company_id), meta=_meta())


@router.post("/payroll/salary-structures", status_code=status.HTTP_201_CREATED)
async def create_salary_structure(
    body: SalaryStructureCreate,
    request: Request,
    tenant: _Tenant,
    _scope: _SetupScope,
    service: _Structures,
) -> DataEnvelope[SalaryStructureRead]:
    data = await service.create(
        tenant.company_id, body, actor_user_id=tenant.user_id, **_client(request)
    )
    return DataEnvelope(data=data, meta=_meta())


@router.get("/payroll/salary-structures/{structure_id}", status_code=status.HTTP_200_OK)
async def get_salary_structure(
    structure_id: UUID, tenant: _Tenant, _scope: _SetupScope, service: _Structures
) -> DataEnvelope[SalaryStructureRead]:
    return DataEnvelope(data=await service.get(tenant.company_id, structure_id), meta=_meta())


@router.patch("/payroll/salary-structures/{structure_id}", status_code=status.HTTP_200_OK)
async def update_salary_structure(
    structure_id: UUID,
    body: SalaryStructureUpdate,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: _Tenant,
    _scope: _SetupScope,
    service: _Structures,
) -> DataEnvelope[SalaryStructureRead]:
    data = await service.update(
        tenant.company_id,
        structure_id,
        body,
        expected_version=int(if_match),
        actor_user_id=tenant.user_id,
        **_client(request),
    )
    return DataEnvelope(data=data, meta=_meta())


@router.post(
    "/payroll/salary-structures/{structure_id}/versions", status_code=status.HTTP_201_CREATED
)
async def create_salary_structure_version(
    structure_id: UUID,
    body: SalaryStructureVersionCreate,
    request: Request,
    tenant: _Tenant,
    _scope: _SetupScope,
    service: _Structures,
) -> DataEnvelope[SalaryStructureRead]:
    data = await service.create_version(
        tenant.company_id, structure_id, body, actor_user_id=tenant.user_id, **_client(request)
    )
    return DataEnvelope(data=data, meta=_meta())


@router.put(
    "/payroll/salary-structures/{structure_id}/versions/{version_id}/lines",
    status_code=status.HTTP_200_OK,
)
async def update_salary_structure_version_lines(
    structure_id: UUID,
    version_id: UUID,
    body: SalaryStructureVersionLinesUpdate,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: _Tenant,
    _scope: _SetupScope,
    service: _Structures,
) -> DataEnvelope[SalaryStructureRead]:
    data = await service.update_version_lines(
        tenant.company_id,
        structure_id,
        version_id,
        body.lines,
        expected_version=int(if_match),
        actor_user_id=tenant.user_id,
        **_client(request),
    )
    return DataEnvelope(data=data, meta=_meta())


@router.post(
    "/payroll/salary-structures/{structure_id}/versions/{version_id}/publish",
    status_code=status.HTTP_200_OK,
)
async def publish_salary_structure_version(
    structure_id: UUID,
    version_id: UUID,
    body: SalaryStructureVersionPublish,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: _Tenant,
    _scope: _SetupScope,
    service: _Structures,
) -> DataEnvelope[SalaryStructureRead]:
    data = await service.publish_version(
        tenant.company_id,
        structure_id,
        version_id,
        body,
        expected_version=int(if_match),
        actor_user_id=tenant.user_id,
        **_client(request),
    )
    return DataEnvelope(data=data, meta=_meta())


@router.delete(
    "/payroll/salary-structures/{structure_id}/versions/{version_id}",
    status_code=status.HTTP_200_OK,
)
async def discard_salary_structure_version(
    structure_id: UUID,
    version_id: UUID,
    request: Request,
    tenant: _Tenant,
    _scope: _SetupScope,
    service: _Structures,
) -> DataEnvelope[SalaryStructureRead]:
    data = await service.discard_version(
        tenant.company_id,
        structure_id,
        version_id,
        actor_user_id=tenant.user_id,
        **_client(request),
    )
    return DataEnvelope(data=data, meta=_meta())


@router.post(
    "/payroll/salary-structures/{structure_id}/versions/{version_id}/preview",
    status_code=status.HTTP_200_OK,
)
async def preview_salary_structure_version(
    structure_id: UUID,
    version_id: UUID,
    body: SalaryBreakupPreviewInput,
    tenant: _Tenant,
    _scope: _SetupScope,
    service: _Structures,
) -> DataEnvelope[SalaryBreakupRead]:
    data = await service.preview(tenant.company_id, structure_id, version_id, body)
    return DataEnvelope(data=data, meta=_meta())


# ---------------------------------------------------------------------------
# Employee salary
# ---------------------------------------------------------------------------


@router.get("/employees/{employee_id}/salary", status_code=status.HTTP_200_OK)
async def list_employee_salaries(
    employee_id: UUID,
    tenant: _Tenant,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_VIEW_COMPENSATION))],
    service: _Salaries,
) -> ListEnvelope[EmployeeSalaryRead]:
    data = await service.list_for_employee(
        tenant.company_id, employee_id, scope=scope, caller_employee_id=user.employee_id
    )
    return ListEnvelope(data=data, meta=_meta())


@router.post("/employees/{employee_id}/salary", status_code=status.HTTP_201_CREATED)
async def create_employee_salary(
    employee_id: UUID,
    body: EmployeeSalaryCreate,
    request: Request,
    tenant: _Tenant,
    _scope: _SetupScope,
    service: _Salaries,
) -> DataEnvelope[EmployeeSalaryRead]:
    data = await service.create(
        tenant.company_id, employee_id, body, actor_user_id=tenant.user_id, **_client(request)
    )
    return DataEnvelope(data=data, meta=_meta())


@router.get("/employees/{employee_id}/salary/breakup", status_code=status.HTTP_200_OK)
async def get_employee_salary_breakup(
    employee_id: UUID,
    tenant: _Tenant,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_VIEW_COMPENSATION))],
    service: _Salaries,
    as_of: Annotated[date | None, Query()] = None,
) -> DataEnvelope[EmployeeSalaryBreakupRead]:
    data = await service.breakup(
        tenant.company_id,
        employee_id,
        as_of=as_of,
        scope=scope,
        caller_employee_id=user.employee_id,
    )
    return DataEnvelope(data=data, meta=_meta())


@router.post("/payroll/salary-assignments/bulk", status_code=status.HTTP_200_OK)
async def bulk_assign_salary_structure(
    body: EmployeeSalaryBulkAssign,
    request: Request,
    tenant: _Tenant,
    _scope: _SetupScope,
    service: _Salaries,
) -> DataEnvelope[EmployeeSalaryBulkResult]:
    data = await service.bulk_assign(
        tenant.company_id, body, actor_user_id=tenant.user_id, **_client(request)
    )
    return DataEnvelope(data=data, meta=_meta())
