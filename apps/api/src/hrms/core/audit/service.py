from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.audit.models import AuditLog
from hrms.core.observability.business_events import emit_after_commit
from hrms.core.tenancy.context import current_request_id


def _status_of(snapshot: dict[str, Any] | None) -> str | None:
    """The entity's `status` if it is a fixed state code (e.g. `APPROVED`), else nothing — the
    only piece of before/after that is copied into the operational event."""
    value = snapshot.get("status") if isinstance(snapshot, dict) else None
    if isinstance(value, str) and len(value) <= 40 and value.replace("_", "").isalnum():
        return value
    return None


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
        # Mission Phase 5 — every audited business transition (employee lifecycle, leave and
        # regularization decisions, pay-run state changes, documents, ...) also leaves one slim
        # operational line, written only if this transaction commits. Identifiers and the state
        # transition only: `before`/`after`, IP and user agent stay in `audit_log` alone.
        emit_after_commit(
            session,
            "business.audit_recorded",
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id else None,
            company_id=str(company_id),
            actor_user_id=str(actor_user_id) if actor_user_id else None,
            from_status=_status_of(before),
            to_status=_status_of(after),
        )
