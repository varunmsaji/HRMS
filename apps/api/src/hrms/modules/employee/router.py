"""HTTP routes for the employee module — thin layer only, per Module Standard §2.

Data-scope enforcement (`SELF`/`REPORTEES`/`REPORTEE_TREE`, `docs/product/
19_RBAC_and_Permission_Matrix.md` §5) is implemented for every GET and write route in this file
that targets a specific employee: `list_employees`/`get_employee`/`update_employee`/
`deactivate_employee` (Identity, `docs/modules/employee/
25_EMPLOYEE_RBAC_DATA_SCOPE_IMPLEMENTATION_PLAN.md`), every Compensation/Statutory/Bank GET route
(`37_EMPLOYEE_COMPENSATION_STATUTORY_DATA_SCOPE_IMPLEMENTATION_REPORT.md` /
`33_EMPLOYEE_BANKING_IMPLEMENTATION_PLAN.md` §8/§15 PD-1), and — per `docs/modules/employee/
39_EMPLOYEE_ACCESS_CONTROL_IMPLEMENTATION_PLAN.md` (F4/F8/F9) — every Employment/Assignment GET
route and every write route in this file (`create_employment`/`update_employment`/
`terminate_employment`/`create_assignment`/`create_compensation`/`create_statutory`/
`create_bank`). Every one of these routes resolves the caller's `DataScope` (via
`require_permission`, or — for `create_assignment` only, since its gating permission is chosen
dynamically by request body, §"Employee Assignment" below — a direct
`rbac.resolve_data_scope()` call) and passes it, plus the caller's own `employee_id` (from the
JWT), to the corresponding service, which narrows the result/target to
`SELF`/`REPORTEES`/`REPORTEE_TREE`/`COMPANY` as appropriate; an out-of-scope target returns
`404`, identical in shape to a nonexistent or cross-tenant ID, never `403` (which would reveal
the target's existence).

`create_employee` (`POST /employees`) has no target employee to scope against — permission alone
gates it, unchanged.
"""

from collections.abc import Awaitable
from datetime import date
from typing import Annotated
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
from hrms.core.errors.base import PermissionDeniedError
from hrms.core.idempotency import (
    mark_replay,
    optional_idempotency_key,
    request_fingerprint_fields,
    run_idempotent,
)
from hrms.core.rbac.dependencies import get_rbac_service, require_permission
from hrms.core.rbac.service import RbacService
from hrms.core.rbac.types import DataScope
from hrms.core.tenancy.context import TenantContext, current_request_id
from hrms.core.tenancy.dependencies import get_tenant_context
from hrms.core.uploads import read_upload_bounded
from hrms.modules.employee.dependencies import (
    get_employee_assignment_service,
    get_employee_bank_service,
    get_employee_compensation_service,
    get_employee_dependent_service,
    get_employee_document_service,
    get_employee_education_service,
    get_employee_experience_service,
    get_employee_service,
    get_employee_statutory_service,
    get_employment_service,
)
from hrms.modules.employee.permissions import (
    EMPLOYEE_CONFIRM,
    EMPLOYEE_CREATE,
    EMPLOYEE_DEACTIVATE,
    EMPLOYEE_PROMOTE,
    EMPLOYEE_TERMINATE,
    EMPLOYEE_TRANSFER,
    EMPLOYEE_UPDATE,
    EMPLOYEE_UPDATE_COMPENSATION,
    EMPLOYEE_UPDATE_SENSITIVE,
    EMPLOYEE_VIEW_ALL,
    EMPLOYEE_VIEW_BANKING,
    EMPLOYEE_VIEW_COMPENSATION,
    EMPLOYEE_VIEW_DOCUMENTS,
    EMPLOYEE_VIEW_EXPERIENCE,
    EMPLOYEE_VIEW_NOMINEE,
    EMPLOYEE_VIEW_SENSITIVE,
    EMPLOYEE_VIEW_STATUTORY,
)
from hrms.modules.employee.schemas import (
    EMPLOYEE_DOCUMENT_MAX_SIZE_BYTES,
    AssignmentCreate,
    AssignmentRead,
    BankCreate,
    BankRead,
    CompensationCreate,
    CompensationRead,
    EmployeeConfirmInput,
    EmployeeCreate,
    EmployeeDependentCreate,
    EmployeeDependentRead,
    EmployeeDocumentRead,
    EmployeeDocumentReviewRequest,
    EmployeeDocumentWithUrlRead,
    EmployeeEducationCreate,
    EmployeeEducationRead,
    EmployeeExperienceCreate,
    EmployeeExperienceRead,
    EmployeeIdentityRead,
    EmployeeIdentityUpdate,
    EmployeeRead,
    EmployeeUpdate,
    EmploymentCreate,
    EmploymentRead,
    EmploymentTerminate,
    EmploymentUpdate,
    StatutoryCreate,
    StatutoryRead,
)
from hrms.modules.employee.service import (
    EmployeeAssignmentService,
    EmployeeBankService,
    EmployeeCompensationService,
    EmployeeDependentService,
    EmployeeDocumentService,
    EmployeeEducationService,
    EmployeeExperienceService,
    EmployeeService,
    EmployeeStatutoryService,
    EmploymentService,
)
from hrms.modules.identity.permissions import EMPLOYEE_VIEW
from hrms.modules.identity.schemas import build_meta
from hrms.shared.if_match import parse_if_match
from hrms.shared.pagination import (
    DataEnvelope,
    ListEnvelope,
    PageParams,
    build_pagination_meta,
    pagination_params,
)

router = APIRouter(tags=["employee"])


@router.get("/employees", status_code=status.HTTP_200_OK)
async def list_employees(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_VIEW_ALL))],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
    page: Annotated[PageParams, Depends(pagination_params)],
) -> ListEnvelope[EmployeeRead]:
    data, total = await service.list_employees(
        tenant.company_id, scope=scope, caller_employee_id=user.employee_id, page=page
    )
    return ListEnvelope(
        data=data,
        pagination=build_pagination_meta(page, total=total),
        meta=build_meta(current_request_id() or "unknown"),
    )


@router.post("/employees", status_code=status.HTTP_201_CREATED)
async def create_employee(
    body: EmployeeCreate,
    request: Request,
    response: Response,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(EMPLOYEE_CREATE))],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
    idempotency_key: Annotated[str | None, Depends(optional_idempotency_key)],
) -> DataEnvelope[EmployeeRead]:
    """`Idempotency-Key` is optional (API audit H-4): without it every call creates an employee;
    with it a retry after a lost response replays the first result (header
    `Idempotent-Replayed: true`) instead of creating a second employee."""

    def execute() -> Awaitable[EmployeeRead]:
        return service.create_employee(
            tenant.company_id,
            body,
            actor_user_id=tenant.user_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("User-Agent"),
        )

    if idempotency_key is None:
        return DataEnvelope(
            data=await execute(), meta=build_meta(current_request_id() or "unknown")
        )
    result = await run_idempotent(
        session,
        company_id=tenant.company_id,
        operation="employee.create",
        key=idempotency_key,
        fingerprint_fields=request_fingerprint_fields(body, tenant.user_id),
        response_model=EmployeeRead,
        status_code=status.HTTP_201_CREATED,
        execute=execute,
    )
    mark_replay(response, result.replayed, result.status_code)
    return DataEnvelope(data=result.data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/employees/{employee_id}", status_code=status.HTTP_200_OK)
async def get_employee(
    employee_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_VIEW))],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
) -> DataEnvelope[EmployeeRead]:
    data = await service.get_employee(
        tenant.company_id, employee_id, scope=scope, caller_employee_id=user.employee_id
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.patch("/employees/{employee_id}", status_code=status.HTTP_200_OK)
async def update_employee(
    employee_id: UUID,
    body: EmployeeUpdate,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_UPDATE))],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
) -> DataEnvelope[EmployeeRead]:
    data = await service.update_employee(
        tenant.company_id,
        employee_id,
        body,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        scope=scope,
        caller_employee_id=user.employee_id,
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
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_DEACTIVATE))],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
) -> DataEnvelope[EmployeeRead]:
    """Soft deactivation only — never a hard delete; returns the updated resource with
    `is_active=false` rather than 204, matching this API's envelope convention."""
    data = await service.deactivate_employee(
        tenant.company_id,
        employee_id,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        scope=scope,
        caller_employee_id=user.employee_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/employees/{employee_id}/confirm", status_code=status.HTTP_200_OK)
async def confirm_employee(
    employee_id: UUID,
    body: EmployeeConfirmInput,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_CONFIRM))],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
) -> DataEnvelope[EmployeeRead]:
    """Transitions `PROBATION` -> `ACTIVE` — one-way, never reversed. Minimal confirmation
    slice: no reminders, no manager-recommendation routing, no auto-extend/auto-confirm rules,
    no letter generation (full FR-EMP-010 scope, deliberately not built here)."""
    data = await service.confirm_employee(
        tenant.company_id,
        employee_id,
        body,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        scope=scope,
        caller_employee_id=user.employee_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


# --- Employee Identity (E-02) ---------------------------------------------------------------
#
# PAN/Aadhaar/UAN/father's-or-husband's-name — a plain update-in-place on `Employee` itself
# (like `update_employee` above), not an effective-dated history write like Statutory/Bank
# below. `.VIEW_SENSITIVE` gates the read (resolves `DataScope`, `SELF`-scoped for the base
# `EMPLOYEE` role — an employee can see their own PAN/Aadhaar/UAN, same posture as Banking);
# `.UPDATE_SENSITIVE` gates the write, reused as-is from Statutory/Bank rather than a new code.


@router.get(
    "/employees/{employee_id}/identity",
    status_code=status.HTTP_200_OK,
)
async def get_identity(
    employee_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_VIEW_SENSITIVE))],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
) -> DataEnvelope[EmployeeIdentityRead]:
    data = await service.get_identity(
        tenant.company_id,
        employee_id,
        scope=scope,
        caller_employee_id=user.employee_id,
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.patch(
    "/employees/{employee_id}/identity",
    status_code=status.HTTP_200_OK,
)
async def update_identity(
    employee_id: UUID,
    body: EmployeeIdentityUpdate,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_UPDATE_SENSITIVE))],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
) -> DataEnvelope[EmployeeIdentityRead]:
    data = await service.update_identity(
        tenant.company_id,
        employee_id,
        body,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        scope=scope,
        caller_employee_id=user.employee_id,
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
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_CREATE))],
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
        scope=scope,
        caller_employee_id=user.employee_id,
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
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_VIEW))],
    service: Annotated[EmploymentService, Depends(get_employment_service)],
    as_of: Annotated[date | None, Query()] = None,
) -> ListEnvelope[EmploymentRead]:
    """Full employment history for the employee, ordered by `joining_date`, or — with
    `?as_of=YYYY-MM-DD` — the single episode (if any) covering that date."""
    data = await service.list_employments(
        tenant.company_id,
        employee_id,
        as_of=as_of,
        scope=scope,
        caller_employee_id=user.employee_id,
    )
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get(
    "/employees/{employee_id}/employments/{employment_id}",
    status_code=status.HTTP_200_OK,
)
async def get_employment(
    employee_id: UUID,
    employment_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_VIEW))],
    service: Annotated[EmploymentService, Depends(get_employment_service)],
) -> DataEnvelope[EmploymentRead]:
    data = await service.get_employment(
        tenant.company_id,
        employee_id,
        employment_id,
        scope=scope,
        caller_employee_id=user.employee_id,
    )
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
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_UPDATE))],
    service: Annotated[EmploymentService, Depends(get_employment_service)],
) -> DataEnvelope[EmploymentRead]:
    data = await service.update_employment(
        tenant.company_id,
        employee_id,
        employment_id,
        body,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        scope=scope,
        caller_employee_id=user.employee_id,
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
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_TERMINATE))],
    service: Annotated[EmploymentService, Depends(get_employment_service)],
) -> DataEnvelope[EmploymentRead]:
    """Transitions the current episode `ACTIVE` → `TERMINATED` — one-way, never reversed. A
    later rejoin is a new `POST .../employments` call, not an action on this row."""
    data = await service.terminate_employment(
        tenant.company_id,
        employee_id,
        employment_id,
        body,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        scope=scope,
        caller_employee_id=user.employee_id,
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
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_VIEW))],
    service: Annotated[EmployeeAssignmentService, Depends(get_employee_assignment_service)],
    as_of: Annotated[date | None, Query()] = None,
) -> ListEnvelope[AssignmentRead]:
    """Full effective-dated assignment history for the employee, ordered by `effective_from`,
    or — with `?as_of=YYYY-MM-DD` — the single row (if any) covering that date."""
    data = await service.list_assignments(
        tenant.company_id,
        employee_id,
        as_of=as_of,
        scope=scope,
        caller_employee_id=user.employee_id,
    )
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get(
    "/employees/{employee_id}/assignments/{assignment_id}",
    status_code=status.HTTP_200_OK,
)
async def get_assignment(
    employee_id: UUID,
    assignment_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_VIEW))],
    service: Annotated[EmployeeAssignmentService, Depends(get_employee_assignment_service)],
) -> DataEnvelope[AssignmentRead]:
    data = await service.get_assignment(
        tenant.company_id,
        employee_id,
        assignment_id,
        scope=scope,
        caller_employee_id=user.employee_id,
    )
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
    version-check for an employee's very first assignment).

    Unlike every other write route in this module, the gating permission is selected by the
    request body's own `change_type` (module-header note above), so it cannot be expressed as a
    static `Depends(require_permission(CODE))` — `rbac.resolve_data_scope()` is called directly
    instead, mirroring `require_permission`'s own `_check_permission` helper
    (`core/rbac/dependencies.py`) exactly: an empty `DataScope.levels` means the permission is
    not held at all, `403`; a non-empty result both proves the permission is held and carries
    the scope `create_assignment` must enforce against the target employee."""
    required_permission = EMPLOYEE_PROMOTE if body.change_type == "PROMOTION" else EMPLOYEE_TRANSFER
    scope = await rbac.resolve_data_scope(user.user_id, user.company_id, required_permission)
    if not scope.levels:
        raise PermissionDeniedError(
            f"Permission {required_permission} is required", code="PERMISSION_DENIED"
        )
    data = await service.create_assignment(
        tenant.company_id,
        employee_id,
        body,
        expected_version=parse_if_match(if_match) if if_match is not None else None,
        actor_user_id=tenant.user_id,
        scope=scope,
        caller_employee_id=user.employee_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


# --- Employee Compensation (E-06) -----------------------------------------------------------
#
# Unlike Assignment's `POST .../assignments`, `.VIEW_COMPENSATION`/`.UPDATE_COMPENSATION` map
# 1:1 to GET/POST — no dynamic permission selection by request body is needed
# (`docs/modules/employee/17_EMPLOYEE_COMPENSATION_IMPLEMENTATION_PLAN.md` §23 step 9).
#
# The two GET routes resolve and apply the caller's `DataScope` (module docstring above) — fixed
# in `docs/modules/employee/
# 37_EMPLOYEE_COMPENSATION_STATUTORY_DATA_SCOPE_IMPLEMENTATION_REPORT.md`, closing the
# "resolve-then-discard" gap found in `docs/architecture/
# EMPLOYEE_VERTICAL_PRODUCTION_READINESS_AUDIT.md` Finding F3. `create_compensation` now also
# resolves and enforces `DataScope` against the target employee, closing Finding C/F9 per
# `docs/modules/employee/39_EMPLOYEE_ACCESS_CONTROL_IMPLEMENTATION_PLAN.md` Phase 2.


@router.get(
    "/employees/{employee_id}/compensation",
    status_code=status.HTTP_200_OK,
)
async def list_compensations(
    employee_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_VIEW_COMPENSATION))],
    service: Annotated[EmployeeCompensationService, Depends(get_employee_compensation_service)],
    as_of: Annotated[date | None, Query()] = None,
) -> ListEnvelope[CompensationRead]:
    """Full effective-dated compensation history for the employee, ordered by
    `effective_from`, or — with `?as_of=YYYY-MM-DD` — the single row (if any) covering that
    date."""
    data = await service.list_compensations(
        tenant.company_id,
        employee_id,
        as_of=as_of,
        scope=scope,
        caller_employee_id=user.employee_id,
    )
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get(
    "/employees/{employee_id}/compensation/{compensation_id}",
    status_code=status.HTTP_200_OK,
)
async def get_compensation(
    employee_id: UUID,
    compensation_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_VIEW_COMPENSATION))],
    service: Annotated[EmployeeCompensationService, Depends(get_employee_compensation_service)],
) -> DataEnvelope[CompensationRead]:
    data = await service.get_compensation(
        tenant.company_id,
        employee_id,
        compensation_id,
        scope=scope,
        caller_employee_id=user.employee_id,
    )
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
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_UPDATE_COMPENSATION))],
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
        expected_version=parse_if_match(if_match) if if_match is not None else None,
        actor_user_id=tenant.user_id,
        scope=scope,
        caller_employee_id=user.employee_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


# --- Employee Statutory (E-07) --------------------------------------------------------------
#
# `.VIEW_STATUTORY`/`.UPDATE_SENSITIVE` map 1:1 to GET/POST, same as Compensation. The two GET
# routes now resolve and apply the caller's `DataScope` (module docstring above), matching
# Compensation/Bank — the previous `COMPANY`-only posture (E-07 plan §11.3) contradicted the
# LOCKED `RBAC_DATA_SCOPE_DECISIONS.md` Decision E, which names `SELF`-scoped self-service as
# Statutory's intended default; this was the "resolve-then-discard" gap found in
# `docs/architecture/EMPLOYEE_VERTICAL_PRODUCTION_READINESS_AUDIT.md` Finding F2, fixed per
# `docs/modules/employee/37_EMPLOYEE_COMPENSATION_STATUTORY_DATA_SCOPE_IMPLEMENTATION_REPORT.md`.
# No seeded role currently grants `EMPLOYEE.VIEW_STATUTORY` at a non-`COMPANY` scope, so this is
# behaviorally a no-op for every existing tenant. `create_statutory` now also resolves and
# enforces `DataScope` against the target employee (Finding C/F9,
# `39_EMPLOYEE_ACCESS_CONTROL_IMPLEMENTATION_PLAN.md` Phase 2).


@router.get(
    "/employees/{employee_id}/statutory",
    status_code=status.HTTP_200_OK,
)
async def list_statutories(
    employee_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_VIEW_STATUTORY))],
    service: Annotated[EmployeeStatutoryService, Depends(get_employee_statutory_service)],
    as_of: Annotated[date | None, Query()] = None,
) -> ListEnvelope[StatutoryRead]:
    """Full effective-dated statutory history for the employee, ordered by `effective_from`,
    or — with `?as_of=YYYY-MM-DD` — the single row (if any) covering that date."""
    data = await service.list_statutories(
        tenant.company_id,
        employee_id,
        as_of=as_of,
        scope=scope,
        caller_employee_id=user.employee_id,
    )
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get(
    "/employees/{employee_id}/statutory/{statutory_id}",
    status_code=status.HTTP_200_OK,
)
async def get_statutory(
    employee_id: UUID,
    statutory_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_VIEW_STATUTORY))],
    service: Annotated[EmployeeStatutoryService, Depends(get_employee_statutory_service)],
) -> DataEnvelope[StatutoryRead]:
    data = await service.get_statutory(
        tenant.company_id,
        employee_id,
        statutory_id,
        scope=scope,
        caller_employee_id=user.employee_id,
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post(
    "/employees/{employee_id}/statutory",
    status_code=status.HTTP_201_CREATED,
)
async def create_statutory(
    employee_id: UUID,
    body: StatutoryCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_UPDATE_SENSITIVE))],
    service: Annotated[EmployeeStatutoryService, Depends(get_employee_statutory_service)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> DataEnvelope[StatutoryRead]:
    """Closes the employee's current statutory row (if any) and inserts a new one — covers an
    employee's first statutory profile and every later revision alike. `If-Match` is required
    only when a current row exists; nothing to version-check for an employee's very first
    statutory row."""
    data = await service.create_statutory(
        tenant.company_id,
        employee_id,
        body,
        expected_version=parse_if_match(if_match) if if_match is not None else None,
        actor_user_id=tenant.user_id,
        scope=scope,
        caller_employee_id=user.employee_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


# --- Employee Bank (E-08) -------------------------------------------------------------------
#
# `.VIEW_BANKING`'s `GET` routes resolve and bind the caller's `DataScope`, same as Compensation/
# Statutory now do — `RBAC_DATA_SCOPE_DECISIONS.md` Decision E is LOCKED and names `SELF`-scoped
# self-service as Banking's intended default (`docs/modules/employee/
# 33_EMPLOYEE_BANKING_IMPLEMENTATION_PLAN.md` §8/§15 PD-1 Option 2) — module docstring above.
# `create_bank` reuses `.UPDATE_SENSITIVE` (already added by E-07), widened to a second write
# route, and now also resolves and enforces `DataScope` against the target employee (Finding
# C/F9, `39_EMPLOYEE_ACCESS_CONTROL_IMPLEMENTATION_PLAN.md` Phase 2).


@router.get(
    "/employees/{employee_id}/bank",
    status_code=status.HTTP_200_OK,
)
async def list_banks(
    employee_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_VIEW_BANKING))],
    service: Annotated[EmployeeBankService, Depends(get_employee_bank_service)],
    as_of: Annotated[date | None, Query()] = None,
) -> ListEnvelope[BankRead]:
    """Full effective-dated bank history for the employee, ordered by `effective_from`, or —
    with `?as_of=YYYY-MM-DD` — the single row (if any) covering that date."""
    data = await service.list_banks(
        tenant.company_id,
        employee_id,
        as_of=as_of,
        scope=scope,
        caller_employee_id=user.employee_id,
    )
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get(
    "/employees/{employee_id}/bank/{bank_id}",
    status_code=status.HTTP_200_OK,
)
async def get_bank(
    employee_id: UUID,
    bank_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_VIEW_BANKING))],
    service: Annotated[EmployeeBankService, Depends(get_employee_bank_service)],
) -> DataEnvelope[BankRead]:
    data = await service.get_bank(
        tenant.company_id,
        employee_id,
        bank_id,
        scope=scope,
        caller_employee_id=user.employee_id,
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post(
    "/employees/{employee_id}/bank",
    status_code=status.HTTP_201_CREATED,
)
async def create_bank(
    employee_id: UUID,
    body: BankCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_UPDATE_SENSITIVE))],
    service: Annotated[EmployeeBankService, Depends(get_employee_bank_service)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> DataEnvelope[BankRead]:
    """Closes the employee's current bank row (if any) and inserts a new one — covers an
    employee's first bank account and every later revision alike. `If-Match` is required only
    when a current row exists; nothing to version-check for an employee's very first bank row.
    Unlike Statutory/Assignment/Compensation, this row is never closed by
    `terminate_employment` (plan §7) — it remains available for full-and-final settlement."""
    data = await service.create_bank(
        tenant.company_id,
        employee_id,
        body,
        expected_version=parse_if_match(if_match) if if_match is not None else None,
        actor_user_id=tenant.user_id,
        scope=scope,
        caller_employee_id=user.employee_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


# --- Employee Experience (market-parity onboarding-data pass, part 4) -----------------------
#
# Previous employment / PF continuity — a genuine one-to-many list (multiple past employers,
# concurrently valid), unlike Statutory/Bank's "insert-and-close-the-old-one" shape: `POST`
# always inserts a new independent row, and `DELETE` (not a second `POST`) is the row's only
# other mutation path. `.VIEW_EXPERIENCE` gates the reads (`SELF`-scoped for the base `EMPLOYEE`
# role); `.UPDATE_SENSITIVE` gates both writes, reused as-is rather than a new code.


@router.get(
    "/employees/{employee_id}/experience",
    status_code=status.HTTP_200_OK,
)
async def list_experiences(
    employee_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_VIEW_EXPERIENCE))],
    service: Annotated[EmployeeExperienceService, Depends(get_employee_experience_service)],
) -> ListEnvelope[EmployeeExperienceRead]:
    data = await service.list_experiences(
        tenant.company_id,
        employee_id,
        scope=scope,
        caller_employee_id=user.employee_id,
    )
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get(
    "/employees/{employee_id}/experience/{experience_id}",
    status_code=status.HTTP_200_OK,
)
async def get_experience(
    employee_id: UUID,
    experience_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_VIEW_EXPERIENCE))],
    service: Annotated[EmployeeExperienceService, Depends(get_employee_experience_service)],
) -> DataEnvelope[EmployeeExperienceRead]:
    data = await service.get_experience(
        tenant.company_id,
        employee_id,
        experience_id,
        scope=scope,
        caller_employee_id=user.employee_id,
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post(
    "/employees/{employee_id}/experience",
    status_code=status.HTTP_201_CREATED,
)
async def create_experience(
    employee_id: UUID,
    body: EmployeeExperienceCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_UPDATE_SENSITIVE))],
    service: Annotated[EmployeeExperienceService, Depends(get_employee_experience_service)],
) -> DataEnvelope[EmployeeExperienceRead]:
    """Always inserts a new independent row — a candidate/employee may have any number of past
    employers, all concurrently valid, so unlike Bank/Statutory this never closes an existing
    row and never needs `If-Match`."""
    data = await service.create_experience(
        tenant.company_id,
        employee_id,
        body,
        actor_user_id=tenant.user_id,
        scope=scope,
        caller_employee_id=user.employee_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.delete(
    "/employees/{employee_id}/experience/{experience_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_experience(
    employee_id: UUID,
    experience_id: UUID,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_UPDATE_SENSITIVE))],
    service: Annotated[EmployeeExperienceService, Depends(get_employee_experience_service)],
) -> None:
    await service.delete_experience(
        tenant.company_id,
        employee_id,
        experience_id,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        scope=scope,
        caller_employee_id=user.employee_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )


# --- Employee Education (market-parity onboarding-data pass, part 5) ------------------------
#
# Mirrors the Experience block above exactly — plain one-to-many list, `.VIEW_EXPERIENCE` gates
# reads (folded together with Experience under one code, per that permission's own docstring:
# "both are background data with the same sensitivity/visibility profile"), `.UPDATE_SENSITIVE`
# gates both writes.


@router.get(
    "/employees/{employee_id}/education",
    status_code=status.HTTP_200_OK,
)
async def list_educations(
    employee_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_VIEW_EXPERIENCE))],
    service: Annotated[EmployeeEducationService, Depends(get_employee_education_service)],
) -> ListEnvelope[EmployeeEducationRead]:
    data = await service.list_educations(
        tenant.company_id,
        employee_id,
        scope=scope,
        caller_employee_id=user.employee_id,
    )
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get(
    "/employees/{employee_id}/education/{education_id}",
    status_code=status.HTTP_200_OK,
)
async def get_education(
    employee_id: UUID,
    education_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_VIEW_EXPERIENCE))],
    service: Annotated[EmployeeEducationService, Depends(get_employee_education_service)],
) -> DataEnvelope[EmployeeEducationRead]:
    data = await service.get_education(
        tenant.company_id,
        employee_id,
        education_id,
        scope=scope,
        caller_employee_id=user.employee_id,
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post(
    "/employees/{employee_id}/education",
    status_code=status.HTTP_201_CREATED,
)
async def create_education(
    employee_id: UUID,
    body: EmployeeEducationCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_UPDATE_SENSITIVE))],
    service: Annotated[EmployeeEducationService, Depends(get_employee_education_service)],
) -> DataEnvelope[EmployeeEducationRead]:
    data = await service.create_education(
        tenant.company_id,
        employee_id,
        body,
        actor_user_id=tenant.user_id,
        scope=scope,
        caller_employee_id=user.employee_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.delete(
    "/employees/{employee_id}/education/{education_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_education(
    employee_id: UUID,
    education_id: UUID,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_UPDATE_SENSITIVE))],
    service: Annotated[EmployeeEducationService, Depends(get_employee_education_service)],
) -> None:
    await service.delete_education(
        tenant.company_id,
        employee_id,
        education_id,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        scope=scope,
        caller_employee_id=user.employee_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )


# --- Employee Dependent (market-parity onboarding-data pass, part 6) ------------------------
#
# PF/Gratuity nominee declaration + ESI family details — mirrors the Experience/Education blocks
# above exactly: plain one-to-many list, `POST` always inserts a new independent row, `DELETE`
# is the only other mutation path. `.VIEW_NOMINEE` gates reads (`SELF`-scoped for the base
# `EMPLOYEE` role); `.UPDATE_SENSITIVE` gates both writes, reused as-is — a dependent's Aadhaar
# is at least as sensitive as anything else that code already gates.


@router.get(
    "/employees/{employee_id}/dependents",
    status_code=status.HTTP_200_OK,
)
async def list_dependents(
    employee_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_VIEW_NOMINEE))],
    service: Annotated[EmployeeDependentService, Depends(get_employee_dependent_service)],
) -> ListEnvelope[EmployeeDependentRead]:
    data = await service.list_dependents(
        tenant.company_id,
        employee_id,
        scope=scope,
        caller_employee_id=user.employee_id,
    )
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get(
    "/employees/{employee_id}/dependents/{dependent_id}",
    status_code=status.HTTP_200_OK,
)
async def get_dependent(
    employee_id: UUID,
    dependent_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_VIEW_NOMINEE))],
    service: Annotated[EmployeeDependentService, Depends(get_employee_dependent_service)],
) -> DataEnvelope[EmployeeDependentRead]:
    data = await service.get_dependent(
        tenant.company_id,
        employee_id,
        dependent_id,
        scope=scope,
        caller_employee_id=user.employee_id,
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post(
    "/employees/{employee_id}/dependents",
    status_code=status.HTTP_201_CREATED,
)
async def create_dependent(
    employee_id: UUID,
    body: EmployeeDependentCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_UPDATE_SENSITIVE))],
    service: Annotated[EmployeeDependentService, Depends(get_employee_dependent_service)],
) -> DataEnvelope[EmployeeDependentRead]:
    """Always inserts a new independent row — an employee may declare any number of dependents,
    all concurrently valid, so unlike Bank/Statutory this never closes an existing row and never
    needs `If-Match`."""
    data = await service.create_dependent(
        tenant.company_id,
        employee_id,
        body,
        actor_user_id=tenant.user_id,
        scope=scope,
        caller_employee_id=user.employee_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.delete(
    "/employees/{employee_id}/dependents/{dependent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_dependent(
    employee_id: UUID,
    dependent_id: UUID,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_UPDATE_SENSITIVE))],
    service: Annotated[EmployeeDependentService, Depends(get_employee_dependent_service)],
) -> None:
    await service.delete_dependent(
        tenant.company_id,
        employee_id,
        dependent_id,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        scope=scope,
        caller_employee_id=user.employee_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )


# --- Employee Document (post-onboarding document management) --------------------------------
#
# An employee's ongoing document store, independent of onboarding's own, separate
# `OnboardingDocument` feature. Upload/delete/review are HR/Admin-only (`.UPDATE_SENSITIVE`,
# same code every other sensitive sub-resource write reuses in this module); list is gated by
# the new `.VIEW_DOCUMENTS` code, `SELF`-scoped for the base `EMPLOYEE` role so an employee can
# see (and download) their own documents read-only.


@router.post(
    "/employees/{employee_id}/documents",
    status_code=status.HTTP_201_CREATED,
)
async def upload_employee_document(
    employee_id: UUID,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_UPDATE_SENSITIVE))],
    service: Annotated[EmployeeDocumentService, Depends(get_employee_document_service)],
    document_type: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
) -> DataEnvelope[EmployeeDocumentRead]:
    body = await read_upload_bounded(file, max_bytes=EMPLOYEE_DOCUMENT_MAX_SIZE_BYTES)
    data = await service.upload_document(
        tenant.company_id,
        employee_id,
        document_type=document_type,
        filename=file.filename or "upload",
        content_type=file.content_type or "application/octet-stream",
        data=body,
        actor_user_id=tenant.user_id,
        scope=scope,
        caller_employee_id=user.employee_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get(
    "/employees/{employee_id}/documents",
    status_code=status.HTTP_200_OK,
)
async def list_employee_documents(
    employee_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_VIEW_DOCUMENTS))],
    service: Annotated[EmployeeDocumentService, Depends(get_employee_document_service)],
) -> ListEnvelope[EmployeeDocumentWithUrlRead]:
    data = await service.list_documents_with_urls(
        tenant.company_id,
        employee_id,
        scope=scope,
        caller_employee_id=user.employee_id,
    )
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.delete(
    "/employees/{employee_id}/documents/{document_id}",
    status_code=status.HTTP_200_OK,
)
async def delete_employee_document(
    employee_id: UUID,
    document_id: UUID,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_UPDATE_SENSITIVE))],
    service: Annotated[EmployeeDocumentService, Depends(get_employee_document_service)],
) -> DataEnvelope[dict[str, bool]]:
    await service.delete_document(
        tenant.company_id,
        employee_id,
        document_id,
        actor_user_id=tenant.user_id,
        scope=scope,
        caller_employee_id=user.employee_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data={"deleted": True}, meta=build_meta(current_request_id() or "unknown"))


@router.post(
    "/employees/{employee_id}/documents/{document_id}/review",
    status_code=status.HTTP_200_OK,
)
async def review_employee_document(
    employee_id: UUID,
    document_id: UUID,
    body: EmployeeDocumentReviewRequest,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    scope: Annotated[DataScope, Depends(require_permission(EMPLOYEE_UPDATE_SENSITIVE))],
    service: Annotated[EmployeeDocumentService, Depends(get_employee_document_service)],
) -> DataEnvelope[EmployeeDocumentRead]:
    data = await service.review_document(
        tenant.company_id,
        employee_id,
        document_id,
        status=body.status,
        rejection_reason=body.rejection_reason,
        actor_user_id=tenant.user_id,
        scope=scope,
        caller_employee_id=user.employee_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))
