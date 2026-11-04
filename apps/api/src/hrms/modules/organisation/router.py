"""HTTP routes for the organisation module — thin layer only, per Module Standard §2."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status

from hrms.core.auth.dependencies import get_current_user
from hrms.core.auth.refresh_cookie import set_refresh_cookie
from hrms.core.auth.types import AuthenticatedUser
from hrms.core.config.settings import get_settings
from hrms.core.errors.base import PermissionDeniedError, ValidationError
from hrms.core.rbac.dependencies import get_rbac_service, require_permission
from hrms.core.rbac.service import RbacService
from hrms.core.tenancy.context import TenantContext, current_request_id
from hrms.core.tenancy.dependencies import get_tenant_context
from hrms.modules.attendance.permissions import ATTENDANCE_VIEW
from hrms.modules.identity.schemas import (
    PublicTokenResponseData,
    build_meta,
    to_public_token_response,
)
from hrms.modules.organisation.calendar_impact import (
    HOLIDAY_CHANGE_TYPES,
    CalendarImpactService,
    ImpactConfirmed,
    ImpactConfirmRequest,
    ImpactPreview,
    ImpactPreviewRequest,
    get_calendar_impact_service,
)
from hrms.modules.organisation.calendar_setup import (
    WorkCalendarDaysRead,
    WorkCalendarSetupConfirmed,
    WorkCalendarSetupConfirmRequest,
    WorkCalendarSetupPreview,
    WorkCalendarSetupPreviewRequest,
    WorkCalendarSetupService,
    WorkCalendarSetupStatus,
    get_work_calendar_setup_service,
)
from hrms.modules.organisation.dashboard_insights import (
    CompanyDashboardInsights,
    LeaveScope,
    build_company_insights,
)
from hrms.modules.organisation.dependencies import get_organisation_service
from hrms.modules.organisation.employee_calendar import (
    EmployeeCalendarRead,
    EmployeeCalendarService,
    get_employee_calendar_service,
)
from hrms.modules.organisation.my_work_profile import (
    MyWorkProfileRead,
    MyWorkProfileService,
    get_my_work_profile_service,
)
from hrms.modules.organisation.permissions import (
    DASHBOARD_COMPANY_VIEW,
    ORG_BRANCH_MANAGE,
    ORG_CALENDAR_MANAGE,
    ORG_COMPANY_MANAGE,
    ORG_DEPARTMENT_MANAGE,
    ORG_DESIGNATION_MANAGE,
    ORG_GRADE_MANAGE,
    ORG_HOLIDAY_MANAGE,
    ORG_LEGAL_ENTITY_MANAGE,
    ORG_SHIFT_MANAGE,
)
from hrms.modules.organisation.policy_coverage import (
    ATTENDANCE_KINDS,
    CALENDAR_KINDS,
    LEAVE_KIND,
    PolicyCoverageService,
    get_policy_coverage_service,
)
from hrms.modules.organisation.schemas import (
    BranchCreate,
    BranchRead,
    BranchUpdate,
    CalendarExceptionCreate,
    CalendarExceptionRead,
    CalendarExceptionUpdate,
    CalendarResolutionRead,
    CompanyDashboardSummary,
    CompanyProfileRead,
    CompanyProfileUpdate,
    CompanyRegistrationRequest,
    CompanySetupProgressSummary,
    DayTypeRead,
    DepartmentCreate,
    DepartmentRead,
    DepartmentUpdate,
    DesignationCreate,
    DesignationRead,
    DesignationUpdate,
    GradeCreate,
    GradeRead,
    GradeUpdate,
    HolidayCalendarCreate,
    HolidayCalendarRead,
    HolidayCalendarUpdate,
    HolidayCreate,
    HolidayRead,
    HolidayUpdate,
    LegalEntityCreate,
    LegalEntityRead,
    LegalEntityUpdate,
    PolicyAssignmentBatch,
    PolicyAssignmentCreate,
    PolicyAssignmentEnd,
    PolicyAssignmentRead,
    PolicyCoverageRead,
    RegistrationConfigRead,
    ShiftCreate,
    ShiftDeleteRequest,
    ShiftDeletionCheck,
    ShiftRead,
    ShiftUpdate,
    ShiftVersionCreate,
    ShiftVersionPublishRequest,
    ShiftVersionRead,
    ShiftVersionUpdate,
    SubscriptionSummary,
    WeeklyOffPatternCreate,
    WeeklyOffPatternRead,
    WeeklyOffPatternUpdate,
    WorkCalendarCreate,
    WorkCalendarRead,
    WorkCalendarUpdate,
)
from hrms.modules.organisation.service import OrganisationService
from hrms.shared.if_match import parse_if_match
from hrms.shared.pagination import (
    DataEnvelope,
    ListEnvelope,
    PageParams,
    build_pagination_meta,
    pagination_params,
)
from hrms.shared.rate_limit import rate_limit

router = APIRouter(tags=["organisation"])

# "Auth endpoints: 10/min per IP" (docs/product/09_API_Standards.md §1.9) — the existing
# bucket definition covering login, reused here; there is no per-account leg since no
# account exists yet at registration time.
_registration_rate_limit = rate_limit("auth", limit=10, window_seconds=60)


@router.get("/companies/registration-config", status_code=status.HTTP_200_OK)
async def get_registration_config() -> DataEnvelope[RegistrationConfigRead]:
    """Public, unauthenticated — read-only. Lets the sign-up page (and the company-profile edit
    screen) narrow their timezone `<select>` to the server's actual allow-list instead of a
    second, hand-maintained TypeScript copy (execution gate §6.3). No rate limit beyond the
    default: this returns no tenant data and cannot be used to enumerate or affect anything."""
    settings = get_settings()
    return DataEnvelope(
        data=RegistrationConfigRead(
            allowed_company_timezones=list(settings.allowed_company_timezones)
        ),
        meta=build_meta(current_request_id() or "unknown"),
    )


@router.post("/companies/register", status_code=status.HTTP_201_CREATED)
async def register_company(
    body: CompanyRegistrationRequest,
    request: Request,
    response: Response,
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
    _rate_limit: Annotated[None, Depends(_registration_rate_limit)],
) -> DataEnvelope[PublicTokenResponseData]:
    data = await service.register_company(
        body,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    set_refresh_cookie(
        response, request, raw_refresh_token=data.refresh_token, settings=get_settings()
    )
    return DataEnvelope(
        data=to_public_token_response(data), meta=build_meta(current_request_id() or "unknown")
    )


@router.get("/companies/current", status_code=status.HTTP_200_OK)
async def get_company_profile(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_COMPANY_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[CompanyProfileRead]:
    data = await service.get_company_profile(tenant.company_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.patch("/companies/current", status_code=status.HTTP_200_OK)
async def update_company_profile(
    body: CompanyProfileUpdate,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_COMPANY_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[CompanyProfileRead]:
    data = await service.update_company_profile(
        tenant.company_id,
        body,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/companies/current/setup-progress", status_code=status.HTTP_200_OK)
async def get_setup_progress(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_COMPANY_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[CompanySetupProgressSummary]:
    data = await service.get_setup_progress(tenant.company_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/companies/current/subscription", status_code=status.HTTP_200_OK)
async def get_subscription_summary(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_COMPANY_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[SubscriptionSummary]:
    data = await service.get_subscription_summary(tenant.company_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/dashboards/company", status_code=status.HTTP_200_OK)
async def get_company_dashboard(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(DASHBOARD_COMPANY_VIEW))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[CompanyDashboardSummary]:
    data = await service.get_dashboard_summary(tenant.company_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/dashboards/company/insights", status_code=status.HTTP_200_OK)
async def get_company_dashboard_insights(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(DASHBOARD_COMPANY_VIEW))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
    growth_months: Annotated[int, Query(ge=3, le=12)] = 6,
    leave_scope: LeaveScope = "month",
) -> DataEnvelope[CompanyDashboardInsights]:
    data = await build_company_insights(
        service._session,  # noqa: SLF001 - read-only aggregation on the request's session
        tenant.company_id,
        growth_months=growth_months,
        leave_scope=leave_scope,
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/legal-entities", status_code=status.HTTP_200_OK)
async def list_legal_entities(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_LEGAL_ENTITY_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> ListEnvelope[LegalEntityRead]:
    data = await service.list_legal_entities(tenant.company_id)
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/legal-entities", status_code=status.HTTP_201_CREATED)
async def create_legal_entity(
    body: LegalEntityCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_LEGAL_ENTITY_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[LegalEntityRead]:
    data = await service.create_legal_entity(
        tenant.company_id,
        body,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/legal-entities/{entity_id}", status_code=status.HTTP_200_OK)
async def get_legal_entity(
    entity_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_LEGAL_ENTITY_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[LegalEntityRead]:
    data = await service.get_legal_entity(tenant.company_id, entity_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.patch("/legal-entities/{entity_id}", status_code=status.HTTP_200_OK)
async def update_legal_entity(
    entity_id: UUID,
    body: LegalEntityUpdate,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_LEGAL_ENTITY_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[LegalEntityRead]:
    data = await service.update_legal_entity(
        tenant.company_id,
        entity_id,
        body,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.delete("/legal-entities/{entity_id}", status_code=status.HTTP_200_OK)
async def deactivate_legal_entity(
    entity_id: UUID,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_LEGAL_ENTITY_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[LegalEntityRead]:
    """Soft deactivation only (FR-ORG-014 — never hard-delete); returns the updated
    resource with `is_active=false` rather than 204, matching this API's envelope
    convention (no bare-204 response exists elsewhere in this module)."""
    data = await service.deactivate_legal_entity(
        tenant.company_id,
        entity_id,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/branches", status_code=status.HTTP_200_OK)
async def list_branches(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_BRANCH_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> ListEnvelope[BranchRead]:
    data = await service.list_branches(tenant.company_id)
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/branches", status_code=status.HTTP_201_CREATED)
async def create_branch(
    body: BranchCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_BRANCH_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[BranchRead]:
    data = await service.create_branch(
        tenant.company_id,
        body,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/branches/{branch_id}", status_code=status.HTTP_200_OK)
async def get_branch(
    branch_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_BRANCH_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[BranchRead]:
    data = await service.get_branch(tenant.company_id, branch_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.patch("/branches/{branch_id}", status_code=status.HTTP_200_OK)
async def update_branch(
    branch_id: UUID,
    body: BranchUpdate,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_BRANCH_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[BranchRead]:
    data = await service.update_branch(
        tenant.company_id,
        branch_id,
        body,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.delete("/branches/{branch_id}", status_code=status.HTTP_200_OK)
async def deactivate_branch(
    branch_id: UUID,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_BRANCH_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[BranchRead]:
    """Soft deactivation only (FR-ORG-014 — never hard-delete); returns the updated
    resource with `is_active=false` rather than 204, matching this API's envelope
    convention."""
    data = await service.deactivate_branch(
        tenant.company_id,
        branch_id,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/departments", status_code=status.HTTP_200_OK)
async def list_departments(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_DEPARTMENT_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> ListEnvelope[DepartmentRead]:
    data = await service.list_departments(tenant.company_id)
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/departments", status_code=status.HTTP_201_CREATED)
async def create_department(
    body: DepartmentCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_DEPARTMENT_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[DepartmentRead]:
    data = await service.create_department(
        tenant.company_id,
        body,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/departments/{department_id}", status_code=status.HTTP_200_OK)
async def get_department(
    department_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_DEPARTMENT_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[DepartmentRead]:
    data = await service.get_department(tenant.company_id, department_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.patch("/departments/{department_id}", status_code=status.HTTP_200_OK)
async def update_department(
    department_id: UUID,
    body: DepartmentUpdate,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_DEPARTMENT_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[DepartmentRead]:
    data = await service.update_department(
        tenant.company_id,
        department_id,
        body,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.delete("/departments/{department_id}", status_code=status.HTTP_200_OK)
async def deactivate_department(
    department_id: UUID,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_DEPARTMENT_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[DepartmentRead]:
    """Soft deactivation only (FR-ORG-014 — never hard-delete); returns the updated
    resource with `is_active=false` rather than 204, matching this API's envelope
    convention."""
    data = await service.deactivate_department(
        tenant.company_id,
        department_id,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/designations", status_code=status.HTTP_200_OK)
async def list_designations(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_DESIGNATION_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> ListEnvelope[DesignationRead]:
    data = await service.list_designations(tenant.company_id)
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/designations", status_code=status.HTTP_201_CREATED)
async def create_designation(
    body: DesignationCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_DESIGNATION_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[DesignationRead]:
    data = await service.create_designation(
        tenant.company_id,
        body,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/designations/{designation_id}", status_code=status.HTTP_200_OK)
async def get_designation(
    designation_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_DESIGNATION_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[DesignationRead]:
    data = await service.get_designation(tenant.company_id, designation_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.patch("/designations/{designation_id}", status_code=status.HTTP_200_OK)
async def update_designation(
    designation_id: UUID,
    body: DesignationUpdate,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_DESIGNATION_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[DesignationRead]:
    data = await service.update_designation(
        tenant.company_id,
        designation_id,
        body,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.delete("/designations/{designation_id}", status_code=status.HTTP_200_OK)
async def deactivate_designation(
    designation_id: UUID,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_DESIGNATION_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[DesignationRead]:
    """Soft deactivation only (FR-ORG-014 — never hard-delete); returns the updated
    resource with `is_active=false` rather than 204, matching this API's envelope
    convention."""
    data = await service.deactivate_designation(
        tenant.company_id,
        designation_id,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/grades", status_code=status.HTTP_200_OK)
async def list_grades(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_GRADE_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> ListEnvelope[GradeRead]:
    data = await service.list_grades(tenant.company_id)
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/grades", status_code=status.HTTP_201_CREATED)
async def create_grade(
    body: GradeCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_GRADE_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[GradeRead]:
    data = await service.create_grade(
        tenant.company_id,
        body,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/grades/{grade_id}", status_code=status.HTTP_200_OK)
async def get_grade(
    grade_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_GRADE_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[GradeRead]:
    data = await service.get_grade(tenant.company_id, grade_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.patch("/grades/{grade_id}", status_code=status.HTTP_200_OK)
async def update_grade(
    grade_id: UUID,
    body: GradeUpdate,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_GRADE_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[GradeRead]:
    data = await service.update_grade(
        tenant.company_id,
        grade_id,
        body,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.delete("/grades/{grade_id}", status_code=status.HTTP_200_OK)
async def deactivate_grade(
    grade_id: UUID,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_GRADE_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[GradeRead]:
    """Soft deactivation only (FR-ORG-014 — never hard-delete); returns the updated
    resource with `is_active=false` rather than 204, matching this API's envelope
    convention."""
    data = await service.deactivate_grade(
        tenant.company_id,
        grade_id,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/shifts", status_code=status.HTTP_200_OK)
async def list_shifts(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_SHIFT_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> ListEnvelope[ShiftRead]:
    data = await service.list_shifts(tenant.company_id)
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/shifts", status_code=status.HTTP_201_CREATED)
async def create_shift(
    body: ShiftCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_SHIFT_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[ShiftRead]:
    data = await service.create_shift(
        tenant.company_id,
        body,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/shifts/{shift_id}", status_code=status.HTTP_200_OK)
async def get_shift(
    shift_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_SHIFT_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[ShiftRead]:
    data = await service.get_shift(tenant.company_id, shift_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.patch("/shifts/{shift_id}", status_code=status.HTTP_200_OK)
async def update_shift(
    shift_id: UUID,
    body: ShiftUpdate,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_SHIFT_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[ShiftRead]:
    data = await service.update_shift(
        tenant.company_id,
        shift_id,
        body,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.delete("/shifts/{shift_id}", status_code=status.HTTP_200_OK)
async def deactivate_shift(
    shift_id: UUID,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_SHIFT_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[ShiftRead]:
    """Soft deactivation only (FR-ORG-014 — never hard-delete); returns the updated
    resource with `is_active=false` rather than 204, matching this API's envelope
    convention."""
    data = await service.deactivate_shift(
        tenant.company_id,
        shift_id,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/shifts/{shift_id}/deletion-check", status_code=status.HTTP_200_OK)
async def check_shift_deletion(
    shift_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_SHIFT_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[ShiftDeletionCheck]:
    """Read-only preview of whether the shift can be deleted and, if not, every reason why."""
    data = await service.get_shift_deletion_check(tenant.company_id, shift_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/shifts/{shift_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
async def delete_shift(
    shift_id: UUID,
    body: ShiftDeleteRequest,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_SHIFT_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> Response:
    """Guarded, audited soft delete of a never-used, already-deactivated shift. A POST (not
    DELETE) because it carries a confirmation body; `DELETE /shifts/{id}` stays deactivation."""
    await service.delete_shift(
        tenant.company_id,
        shift_id,
        body,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Shift + Break System (W2) — ShiftVersion, ShiftBreak, ShiftDutyBlock.
# docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md §9-§10.
# ---------------------------------------------------------------------------


@router.get("/shifts/{shift_id}/versions", status_code=status.HTTP_200_OK)
async def list_shift_versions(
    shift_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_SHIFT_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
    page: Annotated[PageParams, Depends(pagination_params)],
) -> ListEnvelope[ShiftVersionRead]:
    data, total = await service.list_shift_versions(tenant.company_id, shift_id, page=page)
    return ListEnvelope(
        data=data,
        pagination=build_pagination_meta(page, total=total),
        meta=build_meta(current_request_id() or "unknown"),
    )


@router.post("/shifts/{shift_id}/versions", status_code=status.HTTP_201_CREATED)
async def create_shift_version(
    shift_id: UUID,
    body: ShiftVersionCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_SHIFT_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[ShiftVersionRead]:
    """409 `SHIFT_VERSION_DRAFT_ALREADY_EXISTS` if this shift already has an open draft — at
    most one open draft per shift (`shift_version_one_open_draft_idx`)."""
    data = await service.create_shift_version(
        tenant.company_id,
        shift_id,
        body,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/shifts/{shift_id}/versions/resolve", status_code=status.HTTP_200_OK)
async def resolve_shift_version(
    shift_id: UUID,
    as_of: Annotated[date, Query()],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_SHIFT_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[ShiftVersionRead]:
    """Registered ahead of `/versions/{version_id}` — a literal path segment must be matched
    before the parameterized route, or `as_of` would be parsed as a `version_id` UUID and
    404/422 instead of reaching this handler."""
    data = await service.resolve_shift_version_as_of(tenant.company_id, shift_id, as_of)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/shifts/{shift_id}/versions/{version_id}", status_code=status.HTTP_200_OK)
async def get_shift_version(
    shift_id: UUID,
    version_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_SHIFT_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[ShiftVersionRead]:
    data = await service.get_shift_version(tenant.company_id, shift_id, version_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.patch("/shifts/{shift_id}/versions/{version_id}", status_code=status.HTTP_200_OK)
async def update_shift_version(
    shift_id: UUID,
    version_id: UUID,
    body: ShiftVersionUpdate,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_SHIFT_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[ShiftVersionRead]:
    """Draft-only (409 `SHIFT_VERSION_NOT_DRAFT` once published). `breaks`/`duty_blocks`, when
    present, replace the entire nested collection atomically."""
    data = await service.update_shift_version(
        tenant.company_id,
        shift_id,
        version_id,
        body,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.delete("/shifts/{shift_id}/versions/{version_id}", status_code=status.HTTP_200_OK)
async def discard_shift_version(
    shift_id: UUID,
    version_id: UUID,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_SHIFT_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[ShiftVersionRead]:
    """Discards a DRAFT only (409 `SHIFT_VERSION_NOT_DRAFT` once published) — soft-deletes via
    `deleted_at`, never a hard delete; returns the discarded resource rather than 204, matching
    this API's envelope convention (no bare-204 response exists elsewhere in this module)."""
    data = await service.discard_shift_version(
        tenant.company_id,
        shift_id,
        version_id,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/shifts/{shift_id}/versions/{version_id}/publish", status_code=status.HTTP_200_OK)
async def publish_shift_version(
    shift_id: UUID,
    version_id: UUID,
    body: ShiftVersionPublishRequest,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_SHIFT_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[ShiftVersionRead]:
    """Two concurrency tokens: `If-Match` is the draft's own (`expected_version`, this
    endpoint's normal optimistic-concurrency check); `body.expected_previous_version` is the
    currently open PUBLISHED version's token, required only when one exists — mirrors
    `create_policy_assignment`'s insert-new/close-previous flow exactly, just with two rows
    being mutated instead of one. `ShiftVersionOverlapError` (409) is the GiST-exclusion
    race-condition backstop if another request published a conflicting date range in the
    interim."""
    data = await service.publish_shift_version(
        tenant.company_id,
        shift_id,
        version_id,
        body,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


# ---------------------------------------------------------------------------
# Workforce Calendar (W1) — HolidayCalendar
# ---------------------------------------------------------------------------


@router.get("/holiday-calendars", status_code=status.HTTP_200_OK)
async def list_holiday_calendars(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_HOLIDAY_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> ListEnvelope[HolidayCalendarRead]:
    data = await service.list_holiday_calendars(tenant.company_id)
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/holiday-calendars", status_code=status.HTTP_201_CREATED)
async def create_holiday_calendar(
    body: HolidayCalendarCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_HOLIDAY_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[HolidayCalendarRead]:
    data = await service.create_holiday_calendar(
        tenant.company_id,
        body,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/holiday-calendars/{calendar_id}", status_code=status.HTTP_200_OK)
async def get_holiday_calendar(
    calendar_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_HOLIDAY_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[HolidayCalendarRead]:
    data = await service.get_holiday_calendar(tenant.company_id, calendar_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.patch("/holiday-calendars/{calendar_id}", status_code=status.HTTP_200_OK)
async def update_holiday_calendar(
    calendar_id: UUID,
    body: HolidayCalendarUpdate,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_HOLIDAY_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[HolidayCalendarRead]:
    data = await service.update_holiday_calendar(
        tenant.company_id,
        calendar_id,
        body,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.delete("/holiday-calendars/{calendar_id}", status_code=status.HTTP_200_OK)
async def deactivate_holiday_calendar(
    calendar_id: UUID,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_HOLIDAY_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[HolidayCalendarRead]:
    data = await service.deactivate_holiday_calendar(
        tenant.company_id,
        calendar_id,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


# ---------------------------------------------------------------------------
# Workforce Calendar (W1) — Holiday (nested under HolidayCalendar)
# ---------------------------------------------------------------------------


@router.get("/holiday-calendars/{calendar_id}/holidays", status_code=status.HTTP_200_OK)
async def list_holidays(
    calendar_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_HOLIDAY_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
    page: Annotated[PageParams, Depends(pagination_params)],
    year: Annotated[int | None, Query()] = None,
) -> ListEnvelope[HolidayRead]:
    data, total = await service.list_holidays(tenant.company_id, calendar_id, year=year, page=page)
    return ListEnvelope(
        data=data,
        pagination=build_pagination_meta(page, total=total),
        meta=build_meta(current_request_id() or "unknown"),
    )


@router.post("/holiday-calendars/{calendar_id}/holidays", status_code=status.HTTP_201_CREATED)
async def create_holiday(
    calendar_id: UUID,
    body: HolidayCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_HOLIDAY_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[HolidayRead]:
    data = await service.create_holiday(
        tenant.company_id,
        calendar_id,
        body,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/holidays/{holiday_id}", status_code=status.HTTP_200_OK)
async def get_holiday(
    holiday_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_HOLIDAY_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[HolidayRead]:
    data = await service.get_holiday(tenant.company_id, holiday_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.patch("/holidays/{holiday_id}", status_code=status.HTTP_200_OK)
async def update_holiday(
    holiday_id: UUID,
    body: HolidayUpdate,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_HOLIDAY_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[HolidayRead]:
    """Never accepts `date`/`calendar_id` (`HolidayUpdate` — no PATCH of used dates,
    architecture §25); metadata (`name`, `holiday_type`, ...) and `is_active` only."""
    data = await service.update_holiday(
        tenant.company_id,
        holiday_id,
        body,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


# ---------------------------------------------------------------------------
# Workforce Calendar (W1) — WeeklyOffPattern
# ---------------------------------------------------------------------------


@router.get("/weekly-off-patterns", status_code=status.HTTP_200_OK)
async def list_weekly_off_patterns(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_CALENDAR_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> ListEnvelope[WeeklyOffPatternRead]:
    data = await service.list_weekly_off_patterns(tenant.company_id)
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/weekly-off-patterns", status_code=status.HTTP_201_CREATED)
async def create_weekly_off_pattern(
    body: WeeklyOffPatternCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_CALENDAR_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[WeeklyOffPatternRead]:
    data = await service.create_weekly_off_pattern(
        tenant.company_id,
        body,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/weekly-off-patterns/{pattern_id}", status_code=status.HTTP_200_OK)
async def get_weekly_off_pattern(
    pattern_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_CALENDAR_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[WeeklyOffPatternRead]:
    data = await service.get_weekly_off_pattern(tenant.company_id, pattern_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.patch("/weekly-off-patterns/{pattern_id}", status_code=status.HTTP_200_OK)
async def update_weekly_off_pattern(
    pattern_id: UUID,
    body: WeeklyOffPatternUpdate,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_CALENDAR_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[WeeklyOffPatternRead]:
    """`rules`, when present, replaces the entire rule set atomically."""
    data = await service.update_weekly_off_pattern(
        tenant.company_id,
        pattern_id,
        body,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.delete("/weekly-off-patterns/{pattern_id}", status_code=status.HTTP_200_OK)
async def deactivate_weekly_off_pattern(
    pattern_id: UUID,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_CALENDAR_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[WeeklyOffPatternRead]:
    data = await service.deactivate_weekly_off_pattern(
        tenant.company_id,
        pattern_id,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


# ---------------------------------------------------------------------------
# Workforce Calendar (W1) — WorkCalendar
# ---------------------------------------------------------------------------


@router.get("/work-calendars", status_code=status.HTTP_200_OK)
async def list_work_calendars(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_CALENDAR_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> ListEnvelope[WorkCalendarRead]:
    data = await service.list_work_calendars(tenant.company_id)
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/work-calendars", status_code=status.HTTP_201_CREATED)
async def create_work_calendar(
    body: WorkCalendarCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_CALENDAR_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[WorkCalendarRead]:
    data = await service.create_work_calendar(
        tenant.company_id,
        body,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/work-calendars/{work_calendar_id}", status_code=status.HTTP_200_OK)
async def get_work_calendar(
    work_calendar_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_CALENDAR_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[WorkCalendarRead]:
    data = await service.get_work_calendar(tenant.company_id, work_calendar_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.patch("/work-calendars/{work_calendar_id}", status_code=status.HTTP_200_OK)
async def update_work_calendar(
    work_calendar_id: UUID,
    body: WorkCalendarUpdate,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_CALENDAR_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[WorkCalendarRead]:
    """`holiday_calendar_ids`, when present, replaces the entire ordered composition."""
    data = await service.update_work_calendar(
        tenant.company_id,
        work_calendar_id,
        body,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.delete("/work-calendars/{work_calendar_id}", status_code=status.HTTP_200_OK)
async def deactivate_work_calendar(
    work_calendar_id: UUID,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_CALENDAR_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[WorkCalendarRead]:
    """Blocked while an active `PolicyAssignment` still points at this calendar (architecture
    §4.2), same posture as `BranchDeactivationBlockedError`."""
    data = await service.deactivate_work_calendar(
        tenant.company_id,
        work_calendar_id,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/work-calendars/{work_calendar_id}/day-type", status_code=status.HTTP_200_OK)
async def get_work_calendar_day_type(
    work_calendar_id: UUID,
    date_param: Annotated[date, Query(alias="date")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_CALENDAR_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[DayTypeRead]:
    """Calendar-level classification (no employee involved) — powers the month-view UI."""
    data = await service.get_work_calendar_day_type(tenant.company_id, work_calendar_id, date_param)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


# ---------------------------------------------------------------------------
# Workforce Calendar (W1) — CalendarException (nested under WorkCalendar)
# ---------------------------------------------------------------------------


@router.get("/work-calendars/{work_calendar_id}/exceptions", status_code=status.HTTP_200_OK)
async def list_calendar_exceptions(
    work_calendar_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_CALENDAR_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
    page: Annotated[PageParams, Depends(pagination_params)],
) -> ListEnvelope[CalendarExceptionRead]:
    data, total = await service.list_calendar_exceptions(
        tenant.company_id, work_calendar_id, page=page
    )
    return ListEnvelope(
        data=data,
        pagination=build_pagination_meta(page, total=total),
        meta=build_meta(current_request_id() or "unknown"),
    )


@router.post("/work-calendars/{work_calendar_id}/exceptions", status_code=status.HTTP_201_CREATED)
async def create_calendar_exception(
    work_calendar_id: UUID,
    body: CalendarExceptionCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_CALENDAR_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[CalendarExceptionRead]:
    data = await service.create_calendar_exception(
        tenant.company_id,
        work_calendar_id,
        body,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.patch("/calendar-exceptions/{exception_id}", status_code=status.HTTP_200_OK)
async def update_calendar_exception(
    exception_id: UUID,
    body: CalendarExceptionUpdate,
    request: Request,
    if_match: Annotated[str, Header(alias="If-Match")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_CALENDAR_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[CalendarExceptionRead]:
    """Never accepts `exception_date`/`exception_type` (`CalendarExceptionUpdate`) —
    corrections are deactivate-then-insert (architecture §7.3)."""
    data = await service.update_calendar_exception(
        tenant.company_id,
        exception_id,
        body,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


# ---------------------------------------------------------------------------
# Workforce Calendar (W1) + W3 — PolicyAssignment. `policy_kind` spans two permission domains
# (ORG.CALENDAR.MANAGE for WORK_CALENDAR/WEEKLY_OFF, ATTENDANCE.POLICY_MANAGE for the three W3
# kinds — WD-19); this single shared endpoint dispatches the permission check by `policy_kind`
# rather than duplicating CRUD under a second route (architecture §18: reuse one mechanism).
# ---------------------------------------------------------------------------

_CALENDAR_POLICY_KINDS = frozenset({"WORK_CALENDAR", "WEEKLY_OFF"})
_ATTENDANCE_POLICY_KINDS = frozenset(
    {"ATTENDANCE_POLICY", "OVERTIME_POLICY", "REGULARIZATION_POLICY"}
)


async def _require_policy_assignment_permission(
    policy_kind: str | None,
    user: "AuthenticatedUser",
    rbac: "RbacService",
) -> None:
    from hrms.modules.attendance.permissions import ATTENDANCE_POLICY_MANAGE

    if policy_kind in _CALENDAR_POLICY_KINDS:
        codes = [ORG_CALENDAR_MANAGE]
    elif policy_kind in _ATTENDANCE_POLICY_KINDS:
        codes = [ATTENDANCE_POLICY_MANAGE]
    else:
        # No filter given (a full cross-kind list) — least privilege: require both domains.
        codes = [ORG_CALENDAR_MANAGE, ATTENDANCE_POLICY_MANAGE]
    for code in codes:
        scope = await rbac.resolve_data_scope(user.user_id, user.company_id, code)
        if not scope.levels:
            raise PermissionDeniedError(f"Permission {code} is required", code="PERMISSION_DENIED")


@router.get("/policy-assignments", status_code=status.HTTP_200_OK)
async def list_policy_assignments(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated["AuthenticatedUser", Depends(get_current_user)],
    rbac: Annotated["RbacService", Depends(get_rbac_service)],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
    page: Annotated[PageParams, Depends(pagination_params)],
    policy_kind: Annotated[str | None, Query()] = None,
    scope_type: Annotated[str | None, Query()] = None,
    scope_id: Annotated[UUID | None, Query()] = None,
    leave_type_id: Annotated[UUID | None, Query()] = None,
    current_only: Annotated[bool, Query()] = False,
) -> ListEnvelope[PolicyAssignmentRead]:
    await _require_policy_assignment_permission(policy_kind, user, rbac)
    data, total = await service.list_policy_assignments(
        tenant.company_id,
        policy_kind=policy_kind,
        scope_type=scope_type,
        scope_id=scope_id,
        leave_type_id=leave_type_id,
        current_only=current_only,
        page=page,
    )
    return ListEnvelope(
        data=data,
        pagination=build_pagination_meta(page, total=total),
        meta=build_meta(current_request_id() or "unknown"),
    )


@router.post("/policy-assignments", status_code=status.HTTP_201_CREATED)
async def create_policy_assignment(
    body: PolicyAssignmentCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated["AuthenticatedUser", Depends(get_current_user)],
    rbac: Annotated["RbacService", Depends(get_rbac_service)],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> DataEnvelope[PolicyAssignmentRead]:
    """Insert-new/close-previous only — no PATCH endpoint exists for this resource
    (architecture §15.1). `If-Match` is required only when an open assignment already exists
    at the same `(policy_kind, scope_type, scope_id)` and must be closed first."""
    await _require_policy_assignment_permission(body.policy_kind, user, rbac)
    data = await service.create_policy_assignment(
        tenant.company_id,
        body,
        expected_version=parse_if_match(if_match) if if_match is not None else None,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


async def _coverage_kinds_for(user: "AuthenticatedUser", rbac: "RbacService") -> list[str]:
    """The kinds this user may see, by the same rule as listing them: calendars need the calendar
    grant, attendance kinds the attendance grant, and leave both."""
    from hrms.modules.attendance.permissions import ATTENDANCE_POLICY_MANAGE

    calendar = await rbac.resolve_data_scope(user.user_id, user.company_id, ORG_CALENDAR_MANAGE)
    attendance = await rbac.resolve_data_scope(
        user.user_id, user.company_id, ATTENDANCE_POLICY_MANAGE
    )
    kinds: list[str] = []
    if calendar.levels:
        kinds += CALENDAR_KINDS
    if attendance.levels:
        kinds += ATTENDANCE_KINDS
    if calendar.levels and attendance.levels:
        kinds.append(LEAVE_KIND)
    if not kinds:
        raise PermissionDeniedError(
            f"Permission {ATTENDANCE_POLICY_MANAGE} is required", code="PERMISSION_DENIED"
        )
    return kinds


@router.get("/policy-assignments/coverage", status_code=status.HTTP_200_OK)
async def get_policy_coverage(
    scope_type: Annotated[str, Query()],
    as_of: Annotated[date, Query()],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated["AuthenticatedUser", Depends(get_current_user)],
    rbac: Annotated["RbacService", Depends(get_rbac_service)],
    service: Annotated[PolicyCoverageService, Depends(get_policy_coverage_service)],
    scope_id: Annotated[UUID | None, Query()] = None,
) -> DataEnvelope[PolicyCoverageRead]:
    """For one scope: what is set there and what applies on `as_of`, one row per kind (per leave
    type for leave). Only the kinds this user may manage are returned."""
    kinds = await _coverage_kinds_for(user, rbac)
    data = await service.coverage(
        tenant.company_id, scope_type=scope_type, scope_id=scope_id, as_of=as_of, kinds=kinds
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/policy-assignments/batch", status_code=status.HTTP_201_CREATED)
async def save_policy_assignment_batch(
    body: PolicyAssignmentBatch,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated["AuthenticatedUser", Depends(get_current_user)],
    rbac: Annotated["RbacService", Depends(get_rbac_service)],
    service: Annotated[PolicyCoverageService, Depends(get_policy_coverage_service)],
) -> DataEnvelope[list[PolicyAssignmentRead]]:
    """Attendance, overtime, regularization and leave changes for one scope, all or nothing."""
    for kind in {change.policy_kind for change in body.changes}:
        await _require_policy_assignment_permission(kind, user, rbac)
    data = await service.save_batch(
        tenant.company_id,
        body,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/policy-assignments/{assignment_id}/end", status_code=status.HTTP_200_OK)
async def end_policy_assignment(
    assignment_id: UUID,
    body: PolicyAssignmentEnd,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated["AuthenticatedUser", Depends(get_current_user)],
    rbac: Annotated["RbacService", Depends(get_rbac_service)],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
    if_match: Annotated[str, Header(alias="If-Match")],
) -> DataEnvelope[PolicyAssignmentRead]:
    # Every kind that can be ended needs the attendance grant, so refuse before reading the row;
    # then apply the row's own kind rule, the same as creating one.
    await _require_policy_assignment_permission("ATTENDANCE_POLICY", user, rbac)
    assignment = await service.get_policy_assignment(tenant.company_id, assignment_id)
    await _require_policy_assignment_permission(assignment.policy_kind, user, rbac)
    data = await service.end_policy_assignment(
        tenant.company_id,
        assignment_id,
        body,
        expected_version=parse_if_match(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


# ---------------------------------------------------------------------------
# Workforce Calendar (W1) — resolution preview
# ---------------------------------------------------------------------------


@router.get("/calendar-resolution", status_code=status.HTTP_200_OK)
async def get_calendar_resolution(
    employee_id: Annotated[UUID, Query()],
    date_param: Annotated[date, Query(alias="date")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_CALENDAR_MANAGE))],
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
) -> DataEnvelope[CalendarResolutionRead]:
    """Admin preview of the WD-09 precedence walk for one employee+date (architecture §10).
    Gated by `ORG.CALENDAR.MANAGE` in W1 — self-service access gated by `ATTENDANCE.VIEW` is
    deferred to W4, since no `ATTENDANCE.*` permission codes exist yet (WD-19)."""
    data = await service.resolve_calendar_for_employee(tenant.company_id, employee_id, date_param)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


# ---------------------------------------------------------------------------
# Work calendar - month/range view and guided setup. All gated by `ORG.CALENDAR.MANAGE`; the
# company always comes from the authenticated tenant context, never from the request.
# ---------------------------------------------------------------------------


@router.get("/work-calendars/{work_calendar_id}/days", status_code=status.HTTP_200_OK)
async def get_work_calendar_days(
    work_calendar_id: UUID,
    from_date: Annotated[date, Query(alias="from")],
    to_date: Annotated[date, Query(alias="to")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_CALENDAR_MANAGE))],
    setup: Annotated[WorkCalendarSetupService, Depends(get_work_calendar_setup_service)],
) -> DataEnvelope[WorkCalendarDaysRead]:
    """Classifies a bounded inclusive range (at most 100 days) in a constant number of queries
    using the same classifier as `/day-type`."""
    data = await setup.get_calendar_days(tenant.company_id, work_calendar_id, from_date, to_date)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/work-calendar-setup", status_code=status.HTTP_200_OK)
async def get_work_calendar_setup_status(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_CALENDAR_MANAGE))],
    setup: Annotated[WorkCalendarSetupService, Depends(get_work_calendar_setup_service)],
) -> DataEnvelope[WorkCalendarSetupStatus]:
    """`SETUP_REQUIRED` carries an *unconfirmed* suggestion; nothing is active until confirm."""
    data = await setup.get_status(tenant.company_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/work-calendar-setup/preview", status_code=status.HTTP_200_OK)
async def preview_work_calendar_setup(
    body: WorkCalendarSetupPreviewRequest,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_CALENDAR_MANAGE))],
    setup: Annotated[WorkCalendarSetupService, Depends(get_work_calendar_setup_service)],
) -> DataEnvelope[WorkCalendarSetupPreview]:
    """POST only because the body is structured; performs no writes."""
    data = await setup.preview(tenant.company_id, body)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/work-calendar-setup/confirm", status_code=status.HTTP_201_CREATED)
async def confirm_work_calendar_setup(
    body: WorkCalendarSetupConfirmRequest,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ORG_CALENDAR_MANAGE))],
    setup: Annotated[WorkCalendarSetupService, Depends(get_work_calendar_setup_service)],
) -> DataEnvelope[WorkCalendarSetupConfirmed]:
    data = await setup.confirm(
        tenant.company_id,
        body,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


# ---------------------------------------------------------------------------
# Employee self-service calendar (read-only). The employee is always the authenticated caller's
# own linked record (JWT claim); there is deliberately no employee_id/company_id parameter.
# ---------------------------------------------------------------------------


@router.get("/employee-calendar/me", status_code=status.HTTP_200_OK)
async def get_my_calendar(
    from_date: Annotated[date, Query(alias="from")],
    to_date: Annotated[date, Query(alias="to")],
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_VIEW))],
    rbac: Annotated[RbacService, Depends(get_rbac_service)],
    service: Annotated[EmployeeCalendarService, Depends(get_employee_calendar_service)],
) -> DataEnvelope[EmployeeCalendarRead]:
    """The caller's own day classification (effective calendar via the WD-09 precedence walk) and
    their own approved/pending leave for a bounded inclusive range (at most 100 days). Leave is
    included only when the caller holds a leave-balance view grant; unresolved dates are returned
    with `configured=false` rather than defaulting to a working day."""
    if user.employee_id is None:
        raise ValidationError(
            "The caller has no linked employee record",
            details=[
                {
                    "field": "employee",
                    "code": "EMPLOYEE_RECORD_REQUIRED",
                    "message": "No employee record is linked to this account",
                }
            ],
        )
    from hrms.modules.leave.permissions import LEAVE_BALANCE_VIEW, LEAVE_BALANCE_VIEW_ALL

    own = await rbac.resolve_data_scope(user.user_id, user.company_id, LEAVE_BALANCE_VIEW)
    broad = await rbac.resolve_data_scope(user.user_id, user.company_id, LEAVE_BALANCE_VIEW_ALL)
    data = await service.get_my_calendar(
        tenant.company_id,
        user.employee_id,
        from_date,
        to_date,
        include_leave=bool(own.levels | broad.levels),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


# ---------------------------------------------------------------------------
# Work calendar - change-impact preview and safe confirmation. Preview writes nothing. Confirm is
# not authorised by a preview: it recomputes the impact under a lock and applies the change only
# if the caller's `impact_digest` still matches.
# ---------------------------------------------------------------------------


async def _require_calendar_change_permission(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    rbac: Annotated[RbacService, Depends(get_rbac_service)],
) -> None:
    for code in (ORG_CALENDAR_MANAGE, ORG_HOLIDAY_MANAGE):
        if await rbac.has_permission(user.user_id, user.company_id, code):
            return
    raise PermissionDeniedError(
        f"Permission {ORG_CALENDAR_MANAGE} is required", code="PERMISSION_DENIED"
    )


async def _require_permission_for_change(
    change_type: str, user: AuthenticatedUser, rbac: RbacService
) -> None:
    """Holiday edits need `ORG.HOLIDAY.MANAGE`, everything else `ORG.CALENDAR.MANAGE` - the same
    codes the ordinary create/update routes require."""
    code = ORG_HOLIDAY_MANAGE if change_type in HOLIDAY_CHANGE_TYPES else ORG_CALENDAR_MANAGE
    if not await rbac.has_permission(user.user_id, user.company_id, code):
        raise PermissionDeniedError(f"Permission {code} is required", code="PERMISSION_DENIED")


@router.post("/work-calendar-changes/preview", status_code=status.HTTP_200_OK)
async def preview_work_calendar_change(
    body: ImpactPreviewRequest,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    _gate: Annotated[None, Depends(_require_calendar_change_permission)],
    rbac: Annotated[RbacService, Depends(get_rbac_service)],
    service: Annotated[CalendarImpactService, Depends(get_calendar_impact_service)],
) -> DataEnvelope[ImpactPreview]:
    """POST only because the proposed change is structured. Performs no writes."""
    await _require_permission_for_change(body.change.change_type, user, rbac)
    data = await service.preview(tenant.company_id, body)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/work-calendar-changes/confirm", status_code=status.HTTP_201_CREATED)
async def confirm_work_calendar_change(
    body: ImpactConfirmRequest,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    _gate: Annotated[None, Depends(_require_calendar_change_permission)],
    rbac: Annotated[RbacService, Depends(get_rbac_service)],
    service: Annotated[CalendarImpactService, Depends(get_calendar_impact_service)],
) -> DataEnvelope[ImpactConfirmed]:
    await _require_permission_for_change(body.change.change_type, user, rbac)
    data = await service.confirm(
        tenant.company_id,
        body,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/employee-work-profile/me", status_code=status.HTTP_200_OK)
async def get_my_work_profile(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    _scope: Annotated[object, Depends(require_permission(ATTENDANCE_VIEW))],
    service: Annotated[MyWorkProfileService, Depends(get_my_work_profile_service)],
) -> DataEnvelope[MyWorkProfileRead]:
    """The caller's own current shift and work location (Home's "Shift assigned" / "Work
    location"). Each is `null` when the placement carries none."""
    if user.employee_id is None:
        raise ValidationError(
            "The caller has no linked employee record",
            details=[
                {
                    "field": "employee",
                    "code": "EMPLOYEE_RECORD_REQUIRED",
                    "message": "No employee record is linked to this account",
                }
            ],
        )
    data = await service.get_my_work_profile(tenant.company_id, user.employee_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))
