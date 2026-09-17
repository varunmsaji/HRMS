"""Public, unauthenticated HTTP routes for the account-invite module. No JWT, no `X-Company-Id`
header, no `require_permission` — every route resolves its own token internally via
`AccountInviteService`, same shape as `onboarding.public_router`. Rate-limited identically to
`POST /companies/register` — an unauthenticated, publicly reachable endpoint that creates
accounts is exactly the threat model that limiter already covers."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from hrms.core.tenancy.context import current_request_id
from hrms.modules.account_invite.dependencies import get_account_invite_service
from hrms.modules.account_invite.schemas import AcceptInviteRequest, PublicAccountInviteRead
from hrms.modules.account_invite.service import AccountInviteService
from hrms.modules.identity.schemas import TokenResponseData, build_meta
from hrms.shared.pagination import DataEnvelope
from hrms.shared.rate_limit import rate_limit

router = APIRouter(prefix="/public/account-invites", tags=["account-invite-public"])

_accept_rate_limit = rate_limit("auth", limit=10, window_seconds=60)


@router.get("/{token}", status_code=status.HTTP_200_OK)
async def get_public_account_invite(
    token: str,
    service: Annotated[AccountInviteService, Depends(get_account_invite_service)],
) -> DataEnvelope[PublicAccountInviteRead]:
    data = await service.resolve(token)
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))


@router.post("/{token}/accept", status_code=status.HTTP_201_CREATED)
async def accept_account_invite(
    token: str,
    body: AcceptInviteRequest,
    request: Request,
    _rate_limit: Annotated[None, Depends(_accept_rate_limit)],
    service: Annotated[AccountInviteService, Depends(get_account_invite_service)],
) -> DataEnvelope[TokenResponseData]:
    data = await service.accept(
        token,
        body.password,
        first_name=body.first_name,
        last_name=body.last_name,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return DataEnvelope(data=data, meta=build_meta(current_request_id() or "unknown"))
