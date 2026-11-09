"""HTTP routes for the Payroll module — thin layer only, per Module Standard §2.

Phase 5.1: salary setup. Components, structures and salary assignment are COMPANY-scoped config
gated by `PAYROLL.SETUP_MANAGE`. An employee's salary history and breakup are compensation data,
read under `EMPLOYEE.VIEW_COMPENSATION` with its `DataScope` applied to the target employee.

Phase 5.2: pay runs — `PAYROLL.RUN_VIEW` to read, `PAYROLL.RUN_PROCESS` to prepare,
`PAYROLL.RUN_APPROVE` to approve, finalise and mark paid. Lifecycle transitions carry `If-Match`.

Phase 5.3: the statutory rate master under `PAYROLL.STATUTORY_MANAGE`.

Phase 5.4: payslips — HR reads any computed run's payslips under `PAYROLL.RUN_VIEW`; an employee
reads only their own finalised ones under `/me/payslips` (`PAYROLL.PAYSLIP_VIEW_OWN`, the caller's
`employee_id` from the token, never a path parameter). The bank advice CSV needs
`PAYROLL.BANK_ADVICE_DOWNLOAD`.

Phase 5.5: day corrections to finalised months (`/payroll/adjustments`) — read under
`PAYROLL.RUN_VIEW`, recorded and withdrawn under `PAYROLL.RUN_PROCESS`; arrears themselves are
computed inside the pay run."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.auth.dependencies import get_current_user
from hrms.core.auth.types import AuthenticatedUser
from hrms.core.db.session import get_session
from hrms.core.idempotency import (
    mark_replay,
    request_fingerprint_fields,
    require_idempotency_key,
    run_idempotent,
)
from hrms.core.rbac.dependencies import require_permission
from hrms.core.rbac.types import DataScope
from hrms.core.tenancy.context import TenantContext, current_request_id
from hrms.core.tenancy.dependencies import get_tenant_context
from hrms.modules.employee.permissions import (
    EMPLOYEE_UPDATE_COMPENSATION,
    EMPLOYEE_VIEW_COMPENSATION,
)
from hrms.modules.identity.schemas import build_meta
from hrms.modules.payroll.dependencies import (
    get_employee_salary_service,
    get_pay_adjustment_service,
    get_pay_run_service,
    get_payroll_setting_service,
    get_payslip_service,
    get_salary_component_service,
    get_salary_structure_service,
    get_statutory_rate_service,
)
from hrms.modules.payroll.permissions import (
    PAYROLL_BANK_ADVICE_DOWNLOAD,
    PAYROLL_PAYSLIP_VIEW_OWN,
    PAYROLL_RUN_APPROVE,
    PAYROLL_RUN_PROCESS,
    PAYROLL_RUN_VIEW,
    PAYROLL_SETUP_MANAGE,
    PAYROLL_STATUTORY_MANAGE,
)
from hrms.modules.payroll.schemas import (
    EmployeeSalaryBreakupRead,
    EmployeeSalaryBulkAssign,
    EmployeeSalaryBulkResult,
    EmployeeSalaryCreate,
    EmployeeSalaryRead,
    EmployeeSalarySetupPreviewInput,
    EmployeeSalarySetupPreviewRead,
    EmployeeSalarySetupRead,
    EmployeeSalarySetupSave,
    PayAdjustmentCreate,
    PayAdjustmentRead,
    PayrollSettingRead,
    PayrollSettingUpdate,
    PayRunCreate,
    PayRunEmployeeDetailRead,
    PayRunEmployeeRead,
    PayRunRead,
    PayRunRollback,
    PayRunUpdate,
    PayRunVarianceAcknowledge,
    PayslipRead,
    PayslipSummaryRead,
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
    StatutoryRateCreate,
    StatutoryRateRead,
    StatutoryRateUpdate,
)
from hrms.modules.payroll.service import (
    EmployeeSalaryService,
    PayAdjustmentService,
    PayrollSettingService,
    PayRunService,
    PayslipService,
    SalaryComponentService,
    SalaryStructureService,
    StatutoryRateService,
)
from hrms.shared.if_match import parse_if_match
from hrms.shared.pagination import (
    DataEnvelope,
    ListEnvelope,
    PageParams,
    ResponseMeta,
    bounded_pagination_params,
    build_pagination_meta,
)

router = APIRouter(tags=["payroll"])

_SetupScope = Annotated[object, Depends(require_permission(PAYROLL_SETUP_MANAGE))]
_Tenant = Annotated[TenantContext, Depends(get_tenant_context)]
_Components = Annotated[SalaryComponentService, Depends(get_salary_component_service)]
_Structures = Annotated[SalaryStructureService, Depends(get_salary_structure_service)]
_Salaries = Annotated[EmployeeSalaryService, Depends(get_employee_salary_service)]
_Settings = Annotated[PayrollSettingService, Depends(get_payroll_setting_service)]
_Runs = Annotated[PayRunService, Depends(get_pay_run_service)]
_RunView = Annotated[object, Depends(require_permission(PAYROLL_RUN_VIEW))]
_RunProcess = Annotated[object, Depends(require_permission(PAYROLL_RUN_PROCESS))]
_RunApprove = Annotated[object, Depends(require_permission(PAYROLL_RUN_APPROVE))]
_IfMatch = Annotated[str, Header(alias="If-Match")]
_Statutory = Annotated[StatutoryRateService, Depends(get_statutory_rate_service)]
_StatutoryScope = Annotated[object, Depends(require_permission(PAYROLL_STATUTORY_MANAGE))]
_Payslips = Annotated[PayslipService, Depends(get_payslip_service)]
_OwnPayslipScope = Annotated[object, Depends(require_permission(PAYROLL_PAYSLIP_VIEW_OWN))]
_BankAdviceScope = Annotated[object, Depends(require_permission(PAYROLL_BANK_ADVICE_DOWNLOAD))]
_User = Annotated[AuthenticatedUser, Depends(get_current_user)]
_Adjustments = Annotated[PayAdjustmentService, Depends(get_pay_adjustment_service)]


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
        expected_version=parse_if_match(if_match),
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
        expected_version=parse_if_match(if_match),
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
        expected_version=parse_if_match(if_match),
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
        expected_version=parse_if_match(if_match),
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


@router.get("/employees/{employee_id}/salary/setup", status_code=status.HTTP_200_OK)
async def get_employee_salary_setup(
    employee_id: UUID,
    tenant: _Tenant,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_VIEW_COMPENSATION))],
    service: _Salaries,
    as_of: Annotated[date | None, Query()] = None,
) -> DataEnvelope[EmployeeSalarySetupRead]:
    data = await service.setup(
        tenant.company_id,
        employee_id,
        as_of=as_of,
        scope=scope,
        caller_employee_id=user.employee_id,
    )
    return DataEnvelope(data=data, meta=_meta())


@router.post("/employees/{employee_id}/salary/setup/preview", status_code=status.HTTP_200_OK)
async def preview_employee_salary_setup(
    employee_id: UUID,
    body: EmployeeSalarySetupPreviewInput,
    tenant: _Tenant,
    _scope: _SetupScope,
    service: _Salaries,
) -> DataEnvelope[EmployeeSalarySetupPreviewRead]:
    data = await service.setup_preview(tenant.company_id, employee_id, body)
    return DataEnvelope(data=data, meta=_meta())


@router.post("/employees/{employee_id}/salary/setup", status_code=status.HTTP_200_OK)
async def save_employee_salary_setup(
    employee_id: UUID,
    body: EmployeeSalarySetupSave,
    request: Request,
    tenant: _Tenant,
    _scope: _SetupScope,
    _compensation: Annotated[object, Depends(require_permission(EMPLOYEE_UPDATE_COMPENSATION))],
    service: _Salaries,
) -> DataEnvelope[EmployeeSalarySetupRead]:
    """Saves the CTC and the salary structure together — needs both `PAYROLL.SETUP_MANAGE` and
    `EMPLOYEE.UPDATE_COMPENSATION`."""
    data = await service.save_setup(
        tenant.company_id, employee_id, body, actor_user_id=tenant.user_id, **_client(request)
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


# ---------------------------------------------------------------------------
# Phase 5.2 — settings and pay runs
# ---------------------------------------------------------------------------


@router.get("/payroll/settings", status_code=status.HTTP_200_OK)
async def get_payroll_settings(
    tenant: _Tenant, _scope: _SetupScope, service: _Settings
) -> DataEnvelope[PayrollSettingRead]:
    return DataEnvelope(data=await service.get(tenant.company_id), meta=_meta())


@router.put("/payroll/settings", status_code=status.HTTP_200_OK)
async def update_payroll_settings(
    body: PayrollSettingUpdate,
    request: Request,
    if_match: _IfMatch,
    tenant: _Tenant,
    _scope: _SetupScope,
    service: _Settings,
) -> DataEnvelope[PayrollSettingRead]:
    data = await service.update(
        tenant.company_id,
        body,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        **_client(request),
    )
    return DataEnvelope(data=data, meta=_meta())


@router.get("/payroll/pay-runs", status_code=status.HTTP_200_OK)
async def list_pay_runs(
    tenant: _Tenant,
    _scope: _RunView,
    service: _Runs,
    page: Annotated[PageParams, Depends(bounded_pagination_params)],
    legal_entity_id: Annotated[UUID | None, Query()] = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> ListEnvelope[PayRunRead]:
    data, total = await service.list_runs(
        tenant.company_id, page=page, legal_entity_id=legal_entity_id, status=status_filter
    )
    return ListEnvelope(
        data=data, pagination=build_pagination_meta(page, total=total), meta=_meta()
    )


@router.post("/payroll/pay-runs", status_code=status.HTTP_201_CREATED)
async def create_pay_run(
    body: PayRunCreate,
    request: Request,
    tenant: _Tenant,
    _scope: _RunProcess,
    service: _Runs,
) -> DataEnvelope[PayRunRead]:
    data = await service.create(
        tenant.company_id, body, actor_user_id=tenant.user_id, **_client(request)
    )
    return DataEnvelope(data=data, meta=_meta())


@router.get("/payroll/pay-runs/{run_id}", status_code=status.HTTP_200_OK)
async def get_pay_run(
    run_id: UUID, tenant: _Tenant, _scope: _RunView, service: _Runs
) -> DataEnvelope[PayRunRead]:
    return DataEnvelope(data=await service.get(tenant.company_id, run_id), meta=_meta())


@router.patch("/payroll/pay-runs/{run_id}", status_code=status.HTTP_200_OK)
async def update_pay_run(
    run_id: UUID,
    body: PayRunUpdate,
    request: Request,
    if_match: _IfMatch,
    tenant: _Tenant,
    _scope: _RunProcess,
    service: _Runs,
) -> DataEnvelope[PayRunRead]:
    data = await service.update(
        tenant.company_id,
        run_id,
        body,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        **_client(request),
    )
    return DataEnvelope(data=data, meta=_meta())


@router.delete("/payroll/pay-runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pay_run(
    run_id: UUID, request: Request, tenant: _Tenant, _scope: _RunProcess, service: _Runs
) -> None:
    await service.delete(
        tenant.company_id, run_id, actor_user_id=tenant.user_id, **_client(request)
    )


@router.post("/payroll/pay-runs/{run_id}/lock-inputs", status_code=status.HTTP_200_OK)
async def lock_pay_run_inputs(
    run_id: UUID,
    request: Request,
    if_match: _IfMatch,
    tenant: _Tenant,
    _scope: _RunProcess,
    service: _Runs,
) -> DataEnvelope[PayRunRead]:
    data = await service.lock_inputs(
        tenant.company_id,
        run_id,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        **_client(request),
    )
    return DataEnvelope(data=data, meta=_meta())


@router.post("/payroll/pay-runs/{run_id}/compute", status_code=status.HTTP_200_OK)
async def compute_pay_run(
    run_id: UUID,
    request: Request,
    if_match: _IfMatch,
    tenant: _Tenant,
    _scope: _RunProcess,
    service: _Runs,
) -> DataEnvelope[PayRunRead]:
    data = await service.compute(
        tenant.company_id,
        run_id,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        **_client(request),
    )
    return DataEnvelope(data=data, meta=_meta())


@router.post("/payroll/pay-runs/{run_id}/approve", status_code=status.HTTP_200_OK)
async def approve_pay_run(
    run_id: UUID,
    request: Request,
    if_match: _IfMatch,
    tenant: _Tenant,
    _scope: _RunApprove,
    service: _Runs,
) -> DataEnvelope[PayRunRead]:
    data = await service.approve(
        tenant.company_id,
        run_id,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        **_client(request),
    )
    return DataEnvelope(data=data, meta=_meta())


@router.post("/payroll/pay-runs/{run_id}/finalise", status_code=status.HTTP_200_OK)
async def finalise_pay_run(
    run_id: UUID,
    request: Request,
    if_match: _IfMatch,
    tenant: _Tenant,
    _scope: _RunApprove,
    service: _Runs,
) -> DataEnvelope[PayRunRead]:
    data = await service.finalise(
        tenant.company_id,
        run_id,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        **_client(request),
    )
    return DataEnvelope(data=data, meta=_meta())


@router.post("/payroll/pay-runs/{run_id}/mark-paid", status_code=status.HTTP_200_OK)
async def mark_pay_run_paid(
    run_id: UUID,
    request: Request,
    if_match: _IfMatch,
    tenant: _Tenant,
    _scope: _RunApprove,
    service: _Runs,
) -> DataEnvelope[PayRunRead]:
    data = await service.mark_paid(
        tenant.company_id,
        run_id,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        **_client(request),
    )
    return DataEnvelope(data=data, meta=_meta())


@router.post("/payroll/pay-runs/{run_id}/rollback", status_code=status.HTTP_200_OK)
async def rollback_pay_run(
    run_id: UUID,
    body: PayRunRollback,
    request: Request,
    if_match: _IfMatch,
    tenant: _Tenant,
    _scope: _RunProcess,
    service: _Runs,
) -> DataEnvelope[PayRunRead]:
    data = await service.rollback(
        tenant.company_id,
        run_id,
        body,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        **_client(request),
    )
    return DataEnvelope(data=data, meta=_meta())


@router.get("/payroll/pay-runs/{run_id}/employees", status_code=status.HTTP_200_OK)
async def list_pay_run_employees(
    run_id: UUID,
    tenant: _Tenant,
    _scope: _RunView,
    service: _Runs,
    page: Annotated[PageParams, Depends(bounded_pagination_params)],
) -> ListEnvelope[PayRunEmployeeRead]:
    data, total = await service.list_employees(tenant.company_id, run_id, page=page)
    return ListEnvelope(
        data=data, pagination=build_pagination_meta(page, total=total), meta=_meta()
    )


@router.get("/payroll/pay-runs/{run_id}/employees/{employee_id}", status_code=status.HTTP_200_OK)
async def get_pay_run_employee(
    run_id: UUID, employee_id: UUID, tenant: _Tenant, _scope: _RunView, service: _Runs
) -> DataEnvelope[PayRunEmployeeDetailRead]:
    data = await service.get_employee(tenant.company_id, run_id, employee_id)
    return DataEnvelope(data=data, meta=_meta())


@router.post(
    "/payroll/pay-runs/{run_id}/employees/{employee_id}/acknowledge-variance",
    status_code=status.HTTP_200_OK,
)
async def acknowledge_pay_run_variance(
    run_id: UUID,
    employee_id: UUID,
    body: PayRunVarianceAcknowledge,
    request: Request,
    tenant: _Tenant,
    _scope: _RunProcess,
    service: _Runs,
) -> DataEnvelope[PayRunEmployeeRead]:
    data = await service.acknowledge_variance(
        tenant.company_id,
        run_id,
        employee_id,
        body,
        actor_user_id=tenant.user_id,
        **_client(request),
    )
    return DataEnvelope(data=data, meta=_meta())


# ---------------------------------------------------------------------------
# Phase 5.3 — statutory rates
# ---------------------------------------------------------------------------


@router.get("/payroll/statutory-rates", status_code=status.HTTP_200_OK)
async def list_statutory_rates(
    tenant: _Tenant,
    _scope: _StatutoryScope,
    service: _Statutory,
    scheme: Annotated[str | None, Query()] = None,
) -> ListEnvelope[StatutoryRateRead]:
    data = await service.list_rates(tenant.company_id, scheme=scheme)
    return ListEnvelope(data=data, meta=_meta())


@router.post("/payroll/statutory-rates", status_code=status.HTTP_201_CREATED)
async def create_statutory_rate(
    body: StatutoryRateCreate,
    request: Request,
    tenant: _Tenant,
    _scope: _StatutoryScope,
    service: _Statutory,
) -> DataEnvelope[StatutoryRateRead]:
    data = await service.create(
        tenant.company_id, body, actor_user_id=tenant.user_id, **_client(request)
    )
    return DataEnvelope(data=data, meta=_meta())


@router.patch("/payroll/statutory-rates/{rate_id}", status_code=status.HTTP_200_OK)
async def update_statutory_rate(
    rate_id: UUID,
    body: StatutoryRateUpdate,
    request: Request,
    if_match: _IfMatch,
    tenant: _Tenant,
    _scope: _StatutoryScope,
    service: _Statutory,
) -> DataEnvelope[StatutoryRateRead]:
    data = await service.update(
        tenant.company_id,
        rate_id,
        body,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        **_client(request),
    )
    return DataEnvelope(data=data, meta=_meta())


@router.post("/payroll/statutory-rates/{rate_id}/verify", status_code=status.HTTP_200_OK)
async def verify_statutory_rate(
    rate_id: UUID,
    request: Request,
    if_match: _IfMatch,
    tenant: _Tenant,
    _scope: _StatutoryScope,
    service: _Statutory,
) -> DataEnvelope[StatutoryRateRead]:
    data = await service.verify(
        tenant.company_id,
        rate_id,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        **_client(request),
    )
    return DataEnvelope(data=data, meta=_meta())


# ---------------------------------------------------------------------------
# Phase 5.4 — payslips and bank advice
# ---------------------------------------------------------------------------


@router.get(
    "/payroll/pay-runs/{run_id}/employees/{employee_id}/payslip", status_code=status.HTTP_200_OK
)
async def get_pay_run_payslip(
    run_id: UUID, employee_id: UUID, tenant: _Tenant, _scope: _RunView, service: _Payslips
) -> DataEnvelope[PayslipRead]:
    data = await service.get_for_run(tenant.company_id, run_id, employee_id)
    return DataEnvelope(data=data, meta=_meta())


@router.get("/payroll/pay-runs/{run_id}/bank-advice", status_code=status.HTTP_200_OK)
async def download_bank_advice(
    run_id: UUID,
    request: Request,
    tenant: _Tenant,
    _scope: _BankAdviceScope,
    service: _Payslips,
) -> Response:
    filename, content = await service.bank_advice(
        tenant.company_id, run_id, actor_user_id=tenant.user_id, **_client(request)
    )
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/me/payslips", status_code=status.HTTP_200_OK)
async def list_my_payslips(
    tenant: _Tenant, user: _User, _scope: _OwnPayslipScope, service: _Payslips
) -> ListEnvelope[PayslipSummaryRead]:
    data = await service.list_own(tenant.company_id, user.employee_id)
    return ListEnvelope(data=data, meta=_meta())


@router.get("/me/payslips/{run_id}", status_code=status.HTTP_200_OK)
async def get_my_payslip(
    run_id: UUID, tenant: _Tenant, user: _User, _scope: _OwnPayslipScope, service: _Payslips
) -> DataEnvelope[PayslipRead]:
    data = await service.get_own(tenant.company_id, run_id, user.employee_id)
    return DataEnvelope(data=data, meta=_meta())


# ---------------------------------------------------------------------------
# Phase 5.5 — day corrections (paid as arrears)
# ---------------------------------------------------------------------------


@router.get("/payroll/adjustments", status_code=status.HTTP_200_OK)
async def list_pay_adjustments(
    tenant: _Tenant,
    _scope: _RunView,
    service: _Adjustments,
    page: Annotated[PageParams, Depends(bounded_pagination_params)],
    source_pay_run_id: Annotated[UUID | None, Query()] = None,
    legal_entity_id: Annotated[UUID | None, Query()] = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> ListEnvelope[PayAdjustmentRead]:
    data, total = await service.list_adjustments(
        tenant.company_id,
        page=page,
        source_pay_run_id=source_pay_run_id,
        legal_entity_id=legal_entity_id,
        status=status_filter,
    )
    return ListEnvelope(
        data=data, pagination=build_pagination_meta(page, total=total), meta=_meta()
    )


@router.post("/payroll/adjustments", status_code=status.HTTP_201_CREATED)
async def create_pay_adjustment(
    body: PayAdjustmentCreate,
    request: Request,
    response: Response,
    tenant: _Tenant,
    _scope: _RunProcess,
    service: _Adjustments,
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> DataEnvelope[PayAdjustmentRead]:
    """Requires an `Idempotency-Key` (PAY-B04): a retry with the same key and body replays the
    original correction instead of recording a second one. A correction is a delta, so two
    corrections that look identical but carry different keys are two distinct corrections."""
    result = await run_idempotent(
        session,
        company_id=tenant.company_id,
        operation="payroll.adjustment.create",
        key=idempotency_key,
        fingerprint_fields=request_fingerprint_fields(body, tenant.user_id),
        response_model=PayAdjustmentRead,
        status_code=status.HTTP_201_CREATED,
        execute=lambda: service.create(
            tenant.company_id, body, actor_user_id=tenant.user_id, **_client(request)
        ),
    )
    mark_replay(response, result.replayed, result.status_code)
    return DataEnvelope(data=result.data, meta=_meta())


@router.delete("/payroll/adjustments/{adjustment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pay_adjustment(
    adjustment_id: UUID,
    request: Request,
    tenant: _Tenant,
    _scope: _RunProcess,
    service: _Adjustments,
) -> None:
    await service.delete(
        tenant.company_id, adjustment_id, actor_user_id=tenant.user_id, **_client(request)
    )
