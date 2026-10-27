"""Platform console: read-only view of every email the application sent (`/v1/platform/emails/*`).

Backed by the append-only `email_log` table. Opening an email's body is recorded as a
`security.platform.email_viewed` event so access to message content is traceable."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.db.session import get_session
from hrms.core.errors.base import AppError
from hrms.core.observability.security_events import security_event
from hrms.core.tenancy.context import current_request_id
from hrms.modules.identity.schemas import build_meta
from hrms.modules.platform.models import EmailLog
from hrms.modules.platform.security import PlatformPrincipal, get_current_platform_admin
from hrms.shared.pagination import (
    DataEnvelope,
    ListEnvelope,
    PageParams,
    build_pagination_meta,
    pagination_params,
)

router = APIRouter(prefix="/platform/emails", tags=["platform"])
Principal = Annotated[PlatformPrincipal, Depends(get_current_platform_admin)]
Session = Annotated[AsyncSession, Depends(get_session, scope="function")]


class EmailNotFoundError(AppError):
    code = "RESOURCE_NOT_FOUND"
    status_code = 404


class EmailLogItem(BaseModel):
    id: UUID
    created_at: datetime
    kind: str | None
    provider: str
    status: str
    recipient: str
    sender: str | None
    subject: str
    company_id: UUID | None
    request_id: str | None
    failure_class: str | None
    error_type: str | None
    status_code: int | None
    retryable: bool | None
    duration_ms: int | None


class EmailLogDetail(EmailLogItem):
    text_body: str | None
    html_body: str | None


def _meta() -> object:
    return build_meta(current_request_id() or "unknown")


@router.get("")
async def list_emails(
    _p: Principal,
    session: Session,
    page: Annotated[PageParams, Depends(pagination_params)],
    status: Annotated[str | None, Query(pattern=r"^(ACCEPTED|FAILED|LOGGED_ONLY)$")] = None,
    kind: Annotated[str | None, Query(max_length=80)] = None,
    company_id: UUID | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> ListEnvelope[EmailLogItem]:
    conditions: list[ColumnElement[bool]] = []
    if status:
        conditions.append(EmailLog.status == status)
    if kind:
        conditions.append(EmailLog.kind == kind)
    if company_id:
        conditions.append(EmailLog.company_id == company_id)
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{escaped}%"
        conditions.append(
            EmailLog.recipient.ilike(like, escape="\\") | EmailLog.subject.ilike(like, escape="\\")
        )
    total = (
        await session.execute(select(func.count()).select_from(EmailLog).where(*conditions))
    ).scalar_one()
    rows = (
        (
            await session.execute(
                select(EmailLog)
                .where(*conditions)
                .order_by(EmailLog.created_at.desc(), EmailLog.id)
                .limit(page.limit)
                .offset(page.offset)
            )
        )
        .scalars()
        .all()
    )
    return ListEnvelope(
        data=[EmailLogItem.model_validate(r, from_attributes=True) for r in rows],
        pagination=build_pagination_meta(page, total=int(total)),
        meta=_meta(),  # type: ignore[arg-type]
    )


@router.get("/{email_id}")
async def get_email(
    email_id: UUID, principal: Principal, session: Session
) -> DataEnvelope[EmailLogDetail]:
    row = await session.get(EmailLog, email_id)
    if row is None:
        raise EmailNotFoundError("Email not found.")
    security_event(
        "platform.email_viewed", platform_admin=principal.username, email_id=str(email_id)
    )
    return DataEnvelope(
        data=EmailLogDetail.model_validate(row, from_attributes=True),
        meta=_meta(),  # type: ignore[arg-type]
    )
