from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from hrms.core.auth.dependencies import get_current_user
from hrms.core.auth.types import AuthenticatedUser
from hrms.core.rbac.dependencies import require_permission
from hrms.core.tenancy.context import TenantContext, current_request_id
from hrms.core.tenancy.dependencies import get_tenant_context
from hrms.modules.identity.dependencies import get_identity_service
from hrms.modules.identity.permissions import SETTINGS_USER_MANAGE
from hrms.modules.identity.schemas import (
    CompanyDetail,
    ForgotPasswordRequest,
    LoginRequest,
    MeResponseData,
    RefreshRequest,
    ResetPasswordRequest,
    TokenResponseData,
    build_meta,
)
from hrms.modules.identity.service import IdentityService
from hrms.shared.pagination import DataEnvelope
from hrms.shared.rate_limit import rate_limit

router = APIRouter(prefix="/auth", tags=["auth"])

# Same "Auth endpoints: 10/min per IP" bucket registration reuses — both are unauthenticated,
# publicly reachable, account-affecting endpoints (Phase 5 hardening, doc 41 §8).
_password_rate_limit = rate_limit("auth", limit=10, window_seconds=60)


@router.post("/login", status_code=status.HTTP_200_OK)
async def login(
    body: LoginRequest,
    request: Request,
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> DataEnvelope[TokenResponseData]:
    data = await service.login(
        body,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/token/refresh", status_code=status.HTTP_200_OK)
async def refresh_token(
    body: RefreshRequest,
    request: Request,
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> DataEnvelope[TokenResponseData]:
    raw = body.refresh_token or request.cookies.get("hrms_refresh")
    if not raw:
        from hrms.core.errors.auth import InvalidTokenError

        raise InvalidTokenError("Refresh token is required")
    data = await service.refresh(raw)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/password/forgot", status_code=status.HTTP_202_ACCEPTED)
async def forgot_password(
    body: ForgotPasswordRequest,
    _rate_limit: Annotated[None, Depends(_password_rate_limit)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> DataEnvelope[dict[str, bool]]:
    await service.forgot_password(body.email)
    return DataEnvelope(
        data={"accepted": True}, meta=build_meta(current_request_id() or "unknown")
    )


@router.post("/password/reset", status_code=status.HTTP_200_OK)
async def reset_password(
    body: ResetPasswordRequest,
    _rate_limit: Annotated[None, Depends(_password_rate_limit)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> DataEnvelope[dict[str, bool]]:
    await service.reset_password(body.token, body.password)
    return DataEnvelope(data={"reset": True}, meta=build_meta(current_request_id() or "unknown"))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> None:
    await service.logout(user.session_id, user.user_id, user.company_id)


@router.get("/me", status_code=status.HTTP_200_OK)
async def get_me(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> DataEnvelope[MeResponseData]:
    if tenant.user_id is None:
        from hrms.core.errors.auth import UnauthorizedError

        raise UnauthorizedError("Authentication required")
    data = await service.get_me(tenant.user_id, tenant.company_id, user.employee_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.get("/admin/users-check", status_code=status.HTTP_200_OK)
async def admin_users_check(
    _scope: Annotated[object, Depends(require_permission(SETTINGS_USER_MANAGE))],
) -> DataEnvelope[dict[str, str]]:
    return DataEnvelope(
        data={"status": "ok"},
        meta=build_meta(current_request_id() or "unknown"),
    )


@router.get("/companies/{company_id}", status_code=status.HTTP_200_OK)
async def get_company(
    company_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> DataEnvelope[CompanyDetail]:
    if tenant.user_id is None:
        from hrms.core.errors.auth import UnauthorizedError

        raise UnauthorizedError("Authentication required")
    data = await service.get_company(company_id, tenant.company_id)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))
