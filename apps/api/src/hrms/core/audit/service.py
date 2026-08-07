from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.audit.models import AuditLog
from hrms.core.tenancy.context import current_request_id


class AuditService:
    async def record(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        actor_user_id: UUID | None,
        action: str,
        entity_type: str,
        entity_id: UUID | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        entry = AuditLog(
            id=uuid4(),
            company_id=company_id,
            actor_user_id=actor_user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before_json=before,
            after_json=after,
            ip=ip,
            user_agent=user_agent,
            request_id=current_request_id(),
        )
        session.add(entry)
