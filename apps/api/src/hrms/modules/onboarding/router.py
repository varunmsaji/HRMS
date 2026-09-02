"""HTTP routes for the onboarding module — thin layer only, per Module Standard §2.

O1 only: `POST /onboarding-cases`, `GET /onboarding-cases`, `GET /onboarding-cases/{id}`. No
`DataScope` narrowing is applied — `require_permission`'s resolved scope is discarded, same
posture as `EMPLOYEE.VIEW_STATUTORY`/`.VIEW_COMPENSATION` (module docstring,
`hrms.modules.employee.router`): no source document proposes `SELF`/`REPORTEES`/`REPORTEE_TREE`
visibility for onboarding cases, which have no employee yet to scope against. Tenant isolation is
still fully enforced via `company_id` + Postgres RLS, same as every other route in this app."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from hrms.core.rbac.dependencies import require_permission
from hrms.core.tenancy.context import TenantContext, current_request_id
from hrms.core.tenancy.dependencies import get_tenant_context
from hrms.modules.identity.schemas import build_meta
from hrms.modules.onboarding.dependencies import get_onboarding_case_service
from hrms.modules.onboarding.permissions import ONBOARDING_CREATE, ONBOARDING_VIEW
from hrms.modules.onboarding.schemas import OnboardingCaseCreate, OnboardingCaseRead
from hrms.modules.onboarding.service import OnboardingCaseService
from hrms.shared.pagination import DataEnvelope, ListEnvelope

router = APIRouter(tags=["onboarding"])


@router.post("/onboarding-cases", status_code=status.HTTP_201_CREATED)
async def create_onboarding_case(
    body: OnboardingCaseCreate,
    request: Request,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ONBOARDING_CREATE))],
    service: Annotated[OnboardingCaseService, Depends(get_onboarding_case_service)],
) -> DataEnvelope[OnboardingCaseRead]:
    data = await service.create_case(
        tenant.company_id,
        body,
        actor_user_id=tenant.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/onboarding-cases", status_code=status.HTTP_200_OK)
async def list_onboarding_cases(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ONBOARDING_VIEW))],
    service: Annotated[OnboardingCaseService, Depends(get_onboarding_case_service)],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> ListEnvelope[OnboardingCaseRead]:
    data = await service.list_cases(tenant.company_id, status=status_filter)
    return ListEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/onboarding-cases/{case_id}", status_code=status.HTTP_200_OK)
async def get_onboarding_case(
    case_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    _scope: Annotated[object, Depends(require_permission(ONBOARDING_VIEW))],
    service: Annotated[OnboardingCaseService, Depends(get_onboarding_case_service)],
) -> DataEnvelope[OnboardingCaseRead]:
    data = await service.get_case(tenant.company_id, case_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))
