"""HTTP routes for the organisation module — thin layer only, per Module Standard §2."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status

from hrms.core.rbac.dependencies import require_permission
from hrms.core.tenancy.context import TenantContext, current_request_id
from hrms.core.tenancy.dependencies import get_tenant_context
from hrms.modules.identity.schemas import TokenResponseData, build_meta
from hrms.modules.organisation.dependencies import get_organisation_service
from hrms.modules.organisation.permissions import (
    DASHBOARD_COMPANY_VIEW,
    ORG_BRANCH_MANAGE,
    ORG_COMPANY_MANAGE,
    ORG_DEPARTMENT_MANAGE,
    ORG_DESIGNATION_MANAGE,
    ORG_GRADE_MANAGE,
    ORG_LEGAL_ENTITY_MANAGE,
)
from hrms.modules.organisation.schemas import (
    BranchCreate,
    BranchRead,
    BranchUpdate,
    CompanyDashboardSummary,
    CompanyProfileRead,
    CompanyProfileUpdate,
    CompanyRegistrationRequest,
    CompanySetupProgressSummary,
    DepartmentCreate,
    DepartmentRead,
    DepartmentUpdate,
    DesignationCreate,
    DesignationRead,
    DesignationUpdate,
    GradeCreate,
    GradeRead,
    GradeUpdate,
    LegalEntityCreate,
    LegalEntityRead,
    LegalEntityUpdate,
    SubscriptionSummary,
)
from hrms.modules.organisation.service import OrganisationService
from hrms.shared.pagination import DataEnvelope, ListEnvelope
from hrms.shared.rate_limit import rate_limit

router = APIRouter(tags=["organisation"])

# "Auth endpoints: 10/min per IP" (docs/product/09_API_Standards.md §1.9) — the existing
# bucket definition covering login, reused here; there is no per-account leg since no
# account exists yet at registration time.
_registration_rate_limit = rate_limit("auth", limit=10, window_seconds=60)


@router.post("/companies/register", status_code=status.HTTP_201_CREATED)
async def register_company(
    body: CompanyRegistrationRequest,
    request: Request,
    service: Annotated[OrganisationService, Depends(get_organisation_service)],
    _rate_limit: Annotated[None, Depends(_registration_rate_limit)],
) -> DataEnvelope[TokenResponseData]:
    data = await service.register_company(
        body,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


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
        expected_version=int(if_match),
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
        expected_version=int(if_match),
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
        expected_version=int(if_match),
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
        expected_version=int(if_match),
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
        expected_version=int(if_match),
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
        expected_version=int(if_match),
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
        expected_version=int(if_match),
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
        expected_version=int(if_match),
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
        expected_version=int(if_match),
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
        expected_version=int(if_match),
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
        expected_version=int(if_match),
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))
