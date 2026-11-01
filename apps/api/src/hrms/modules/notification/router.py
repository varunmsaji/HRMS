"""The caller's own notification feed. No path or body ever names a user: the recipient is always
the authenticated user from the token, in the token's company."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from hrms.core.errors.auth import UnauthorizedError
from hrms.core.tenancy.context import TenantContext, current_request_id
from hrms.core.tenancy.dependencies import get_tenant_context
from hrms.modules.identity.schemas import build_meta
from hrms.modules.notification.dependencies import get_notification_service
from hrms.modules.notification.schemas import NotificationRead, ReadAllRead, UnreadCountRead
from hrms.modules.notification.service import NotificationService
from hrms.shared.pagination import (
    DataEnvelope,
    ListEnvelope,
    PageParams,
    ResponseMeta,
    build_pagination_meta,
    pagination_params,
)


def _uid(tenant: TenantContext) -> UUID:
    # get_tenant_context always sets user_id for an authenticated request.
    if tenant.user_id is None:
        raise UnauthorizedError("Authentication required")
    return tenant.user_id


router = APIRouter(prefix="/notifications", tags=["notifications"])


def _meta() -> ResponseMeta:
    return build_meta(current_request_id() or "unknown")


@router.get("", status_code=status.HTTP_200_OK)
async def list_notifications(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    page: Annotated[PageParams, Depends(pagination_params)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
    unread_only: Annotated[bool, Query()] = False,
) -> ListEnvelope[NotificationRead]:
    rows, total = await service.list_notifications(
        tenant.company_id,
        _uid(tenant),
        unread_only=unread_only,
        limit=page.limit,
        offset=page.offset,
    )
    return ListEnvelope(
        data=rows, pagination=build_pagination_meta(page, total=total), meta=_meta()
    )


@router.get("/unread-count", status_code=status.HTTP_200_OK)
async def get_unread_count(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
) -> DataEnvelope[UnreadCountRead]:
    count = await service.get_unread_count(tenant.company_id, _uid(tenant))
    return DataEnvelope(data=UnreadCountRead(unread_count=count), meta=_meta())


@router.post("/read-all", status_code=status.HTTP_200_OK)
async def read_all(
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
) -> DataEnvelope[ReadAllRead]:
    updated = await service.mark_all_as_read(tenant.company_id, _uid(tenant))
    count = await service.get_unread_count(tenant.company_id, _uid(tenant))
    return DataEnvelope(data=ReadAllRead(updated=updated, unread_count=count), meta=_meta())


@router.patch("/{notification_id}/read", status_code=status.HTTP_200_OK)
async def mark_read(
    notification_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
) -> DataEnvelope[NotificationRead]:
    data = await service.mark_as_read(tenant.company_id, _uid(tenant), notification_id)
    return DataEnvelope(data=data, meta=_meta())


@router.post("/{notification_id}/dismiss", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss(
    notification_id: UUID,
    tenant: Annotated[TenantContext, Depends(get_tenant_context)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
) -> Response:
    await service.dismiss_notification(tenant.company_id, _uid(tenant), notification_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
