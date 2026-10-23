"""Platform console routes (`/v1/platform/*`). Authenticated with a *platform* token only; a
tenant access token is rejected here and a platform token is rejected by every tenant route."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.db.session import get_session
from hrms.core.tenancy.context import current_request_id
from hrms.modules.identity.schemas import build_meta
from hrms.modules.platform.schemas import (
    CompanyDetail,
    CompanyListItem,
    CompanyStatus,
    DashboardData,
    OptionalReasonRequest,
    PlanItem,
    PlatformAdminCreate,
    PlatformAdminItem,
    PlatformAdminPasswordReset,
    PlatformAuditEntry,
    PlatformLoginRequest,
    PlatformMe,
    PlatformTokenData,
    ReasonRequest,
    SubscriptionPatch,
    TerminateRequest,
)
from hrms.modules.platform.security import PlatformPrincipal, get_current_platform_admin
from hrms.modules.platform.service import PlatformService, RequestInfo
from hrms.shared.pagination import (
    DataEnvelope,
    ListEnvelope,
    PageParams,
    build_pagination_meta,
    pagination_params,
)
from hrms.shared.rate_limit import rate_limit

router = APIRouter(prefix="/platform", tags=["platform"])

_login_rate_limit = rate_limit("platform_login", limit=10, window_seconds=60)

Principal = Annotated[PlatformPrincipal, Depends(get_current_platform_admin)]


def get_platform_service(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> PlatformService:
    return PlatformService(session)


Service = Annotated[PlatformService, Depends(get_platform_service)]


def _info(request: Request) -> RequestInfo:
    return RequestInfo(
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )


def _meta() -> object:
    return build_meta(current_request_id() or "unknown")


@router.post("/auth/login", status_code=status.HTTP_200_OK)
async def login(
    body: PlatformLoginRequest,
    request: Request,
    _rl: Annotated[None, Depends(_login_rate_limit)],
    service: Service,
) -> DataEnvelope[PlatformTokenData]:
    data = await service.login(body, _info(request))
    return DataEnvelope(data=data, meta=_meta())  # type: ignore[arg-type]


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, principal: Principal, service: Service) -> None:
    await service.logout(principal, _info(request))


@router.get("/auth/me")
async def me(principal: Principal) -> DataEnvelope[PlatformMe]:
    return DataEnvelope(data=PlatformMe(username=principal.username), meta=_meta())  # type: ignore[arg-type]


@router.get("/dashboard")
async def dashboard(_p: Principal, service: Service) -> DataEnvelope[DashboardData]:
    return DataEnvelope(data=await service.dashboard(), meta=_meta())  # type: ignore[arg-type]


@router.get("/companies")
async def list_companies(
    _p: Principal,
    service: Service,
    page: Annotated[PageParams, Depends(pagination_params)],
    status_filter: Annotated[CompanyStatus | None, Query(alias="status")] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> ListEnvelope[CompanyListItem]:
    items, total = await service.list_companies(
        status=status_filter, query=q, limit=page.limit, offset=page.offset
    )
    return ListEnvelope(
        data=items,
        pagination=build_pagination_meta(page, total=total),
        meta=_meta(),  # type: ignore[arg-type]
    )


@router.get("/companies/{company_id}")
async def get_company(
    company_id: UUID, _p: Principal, service: Service
) -> DataEnvelope[CompanyDetail]:
    return DataEnvelope(data=await service.get_company(company_id), meta=_meta())  # type: ignore[arg-type]


@router.post("/companies/{company_id}/approve")
async def approve_company(
    company_id: UUID,
    body: OptionalReasonRequest,
    request: Request,
    principal: Principal,
    service: Service,
) -> DataEnvelope[CompanyDetail]:
    data = await service.change_status(
        "approve", company_id, principal, _info(request), reason=body.reason
    )
    return DataEnvelope(data=data, meta=_meta())  # type: ignore[arg-type]


@router.post("/companies/{company_id}/reject")
async def reject_company(
    company_id: UUID, body: ReasonRequest, request: Request, principal: Principal, service: Service
) -> DataEnvelope[CompanyDetail]:
    data = await service.change_status(
        "reject", company_id, principal, _info(request), reason=body.reason
    )
    return DataEnvelope(data=data, meta=_meta())  # type: ignore[arg-type]


@router.post("/companies/{company_id}/suspend")
async def suspend_company(
    company_id: UUID, body: ReasonRequest, request: Request, principal: Principal, service: Service
) -> DataEnvelope[CompanyDetail]:
    data = await service.change_status(
        "suspend", company_id, principal, _info(request), reason=body.reason
    )
    return DataEnvelope(data=data, meta=_meta())  # type: ignore[arg-type]


@router.post("/companies/{company_id}/reactivate")
async def reactivate_company(
    company_id: UUID,
    body: OptionalReasonRequest,
    request: Request,
    principal: Principal,
    service: Service,
) -> DataEnvelope[CompanyDetail]:
    data = await service.change_status(
        "reactivate", company_id, principal, _info(request), reason=body.reason
    )
    return DataEnvelope(data=data, meta=_meta())  # type: ignore[arg-type]


@router.post("/companies/{company_id}/terminate")
async def terminate_company(
    company_id: UUID,
    body: TerminateRequest,
    request: Request,
    principal: Principal,
    service: Service,
) -> DataEnvelope[CompanyDetail]:
    data = await service.change_status(
        "terminate",
        company_id,
        principal,
        _info(request),
        reason=body.reason,
        confirm_name=body.confirm_name,
    )
    return DataEnvelope(data=data, meta=_meta())  # type: ignore[arg-type]


@router.patch("/companies/{company_id}/subscription")
async def patch_subscription(
    company_id: UUID,
    body: SubscriptionPatch,
    request: Request,
    principal: Principal,
    service: Service,
) -> DataEnvelope[CompanyDetail]:
    data = await service.update_subscription(company_id, body, principal, _info(request))
    return DataEnvelope(data=data, meta=_meta())  # type: ignore[arg-type]


@router.post("/companies/{company_id}/admin/unlock")
async def unlock_admin(
    company_id: UUID, request: Request, principal: Principal, service: Service
) -> DataEnvelope[CompanyDetail]:
    data = await service.unlock_company_admin(company_id, principal, _info(request))
    return DataEnvelope(data=data, meta=_meta())  # type: ignore[arg-type]


@router.get("/audit-log")
async def audit_log(
    _p: Principal,
    service: Service,
    page: Annotated[PageParams, Depends(pagination_params)],
    company_id: UUID | None = None,
    action: Annotated[str | None, Query(max_length=60)] = None,
) -> ListEnvelope[PlatformAuditEntry]:
    items, total = await service.list_audit(
        company_id=company_id, action=action, limit=page.limit, offset=page.offset
    )
    return ListEnvelope(
        data=items,
        pagination=build_pagination_meta(page, total=total),
        meta=_meta(),  # type: ignore[arg-type]
    )


@router.get("/plans")
async def list_plans(_p: Principal, service: Service) -> DataEnvelope[list[PlanItem]]:
    return DataEnvelope(data=await service.list_plans(), meta=_meta())  # type: ignore[arg-type]


@router.post("/companies/{company_id}/admin/resend-verification")
async def resend_admin_verification(
    company_id: UUID, request: Request, principal: Principal, service: Service
) -> DataEnvelope[CompanyDetail]:
    data = await service.resend_admin_verification(company_id, principal, _info(request))
    return DataEnvelope(data=data, meta=_meta())  # type: ignore[arg-type]


@router.get("/admins")
async def list_admins(
    principal: Principal, service: Service
) -> DataEnvelope[list[PlatformAdminItem]]:
    return DataEnvelope(data=await service.list_admins(principal), meta=_meta())  # type: ignore[arg-type]


@router.post("/admins", status_code=status.HTTP_201_CREATED)
async def create_admin(
    body: PlatformAdminCreate, request: Request, principal: Principal, service: Service
) -> DataEnvelope[PlatformAdminItem]:
    data = await service.create_admin(body.username, body.password, principal, _info(request))
    return DataEnvelope(data=data, meta=_meta())  # type: ignore[arg-type]


@router.post("/admins/{admin_id}/disable")
async def disable_admin(
    admin_id: UUID, request: Request, principal: Principal, service: Service
) -> DataEnvelope[PlatformAdminItem]:
    data = await service.set_admin_status(admin_id, "DISABLED", principal, _info(request))
    return DataEnvelope(data=data, meta=_meta())  # type: ignore[arg-type]


@router.post("/admins/{admin_id}/enable")
async def enable_admin(
    admin_id: UUID, request: Request, principal: Principal, service: Service
) -> DataEnvelope[PlatformAdminItem]:
    data = await service.set_admin_status(admin_id, "ACTIVE", principal, _info(request))
    return DataEnvelope(data=data, meta=_meta())  # type: ignore[arg-type]


@router.post("/admins/{admin_id}/reset-password")
async def reset_admin_password(
    admin_id: UUID,
    body: PlatformAdminPasswordReset,
    request: Request,
    principal: Principal,
    service: Service,
) -> DataEnvelope[PlatformAdminItem]:
    data = await service.reset_admin_password(admin_id, body.password, principal, _info(request))
    return DataEnvelope(data=data, meta=_meta())  # type: ignore[arg-type]
