"""Notification service.

Two audiences, deliberately separate:

* `create_notification` is the *internal* producer API for other modules. The recipient is passed
  by server code (never taken from a request) and is verified to be an active member of the same
  company, so a producer bug cannot leak a notification across tenants.
* list / unread count / read / read-all / dismiss are the *consumer* API. They only ever act on
  the authenticated caller's own rows (`company_id` + `recipient_user_id` come from the token).

Audit policy: reading or dismissing a notification is not audited (it is UI state, and would be
pure noise). The business event that caused the notification (e.g. FACE_ENROLLMENT_OPENED) stays
the authoritative audit record; this table is only a delivery record.
"""

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.errors.base import NotFoundError, ValidationError
from hrms.modules.notification.models import Notification
from hrms.modules.notification.repository import NotificationRepository
from hrms.modules.notification.schemas import NotificationRead
from hrms.modules.notification.types import (
    FORBIDDEN_METADATA_KEY_PARTS,
    MAX_METADATA_BYTES,
    REGISTRY,
    NotificationType,
)


def to_read(row: Notification) -> NotificationRead:
    return NotificationRead(
        id=row.id,
        type=row.type,
        category=row.category,
        priority=row.priority,
        title=row.title,
        body=row.body,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        action_url=row.action_url,
        action_label=row.action_label,
        metadata=row.meta or {},
        is_read=row.read_at is not None,
        read_at=row.read_at,
        created_at=row.created_at,
        expires_at=row.expires_at,
    )


def _check_metadata_keys(value: Any) -> None:
    if isinstance(value, dict):
        for key, inner in value.items():
            lowered = str(key).lower()
            if any(part in lowered for part in FORBIDDEN_METADATA_KEY_PARTS):
                raise ValueError(f"notification metadata key {key!r} is not allowed")
            _check_metadata_keys(inner)
    elif isinstance(value, list):
        for inner in value:
            _check_metadata_keys(inner)


def validate_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Producer-side guard: JSON-only, small, and free of biometric / secret-looking keys."""
    meta = metadata or {}
    _check_metadata_keys(meta)
    if len(json.dumps(meta, default=str).encode()) > MAX_METADATA_BYTES:
        raise ValueError("notification metadata is too large")
    return meta


def _check_action_url(url: str | None) -> None:
    # App-relative only: a notification can never send a user to another origin.
    if url is not None and (not url.startswith("/") or url.startswith("//") or "://" in url):
        raise ValueError("action_url must be an app-relative path")


class NotificationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = NotificationRepository()

    # --- producer API (server-side callers only; there is no HTTP route for it) --------------

    async def create_notification(
        self,
        *,
        company_id: UUID,
        recipient_user_id: UUID,
        type: NotificationType,
        title: str,
        body: str,
        entity_type: str | None = None,
        entity_id: UUID | None = None,
        action_url: str | None = None,
        action_label: str | None = None,
        metadata: dict[str, Any] | None = None,
        dedupe_key: str | None = None,
        expires_at: datetime | None = None,
    ) -> Notification | None:
        """Creates one notification. Returns None when `dedupe_key` already exists for this
        recipient (the event was already notified) or the recipient is not an active member of
        the company. Runs in the caller's transaction; wrap in a savepoint when the notification
        must never be able to fail the business operation."""
        if REGISTRY.get(type.code) is not type:
            raise ValueError(f"unregistered notification type {type.code!r}")
        meta = validate_metadata(metadata)
        _check_action_url(action_url)
        member = (
            await self._session.execute(
                text(
                    'SELECT 1 FROM user_company uc JOIN "user" u ON u.id = uc.user_id'
                    " WHERE uc.company_id = :cid AND uc.user_id = :uid"
                    " AND uc.status = 'ACTIVE' AND u.status = 'ACTIVE' AND u.deleted_at IS NULL"
                ),
                {"cid": company_id, "uid": recipient_user_id},
            )
        ).first()
        if member is None:
            return None
        return await self._repo.insert_once(
            self._session,
            values={
                "id": uuid4(),
                "company_id": company_id,
                "recipient_user_id": recipient_user_id,
                "type": type.code,
                "category": type.category,
                "priority": type.priority,
                "title": title[:200],
                "body": body,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "action_url": action_url,
                "action_label": action_label,
                "meta": meta,
                "dedupe_key": dedupe_key,
                "expires_at": expires_at,
            },
        )

    # --- consumer API (always the caller's own rows) -----------------------------------------

    async def list_notifications(
        self,
        company_id: UUID,
        user_id: UUID,
        *,
        unread_only: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[NotificationRead], int]:
        rows, total = await self._repo.list(
            self._session,
            company_id=company_id,
            user_id=user_id,
            now=datetime.now(UTC),
            unread_only=unread_only,
            limit=limit,
            offset=offset,
        )
        return [to_read(r) for r in rows], total

    async def get_unread_count(self, company_id: UUID, user_id: UUID) -> int:
        return await self._repo.unread_count(
            self._session, company_id=company_id, user_id=user_id, now=datetime.now(UTC)
        )

    async def mark_as_read(
        self, company_id: UUID, user_id: UUID, notification_id: UUID
    ) -> NotificationRead:
        """Idempotent: a second call leaves the original `read_at` untouched."""
        row = await self._repo.get_owned(
            self._session,
            company_id=company_id,
            user_id=user_id,
            notification_id=notification_id,
            for_update=True,
        )
        if row is None:
            raise NotFoundError("Notification not found")
        if row.read_at is None:
            row.read_at = datetime.now(UTC)
            await self._session.flush()
        return to_read(row)

    async def mark_all_as_read(self, company_id: UUID, user_id: UUID) -> int:
        return await self._repo.mark_all_read(
            self._session, company_id=company_id, user_id=user_id, now=datetime.now(UTC)
        )

    async def dismiss_notification(
        self, company_id: UUID, user_id: UUID, notification_id: UUID
    ) -> None:
        """Soft-dismiss: hidden from the feed and the count, the row is retained."""
        row = await self._repo.get_owned(
            self._session,
            company_id=company_id,
            user_id=user_id,
            notification_id=notification_id,
            for_update=True,
        )
        if row is None:
            raise NotFoundError("Notification not found")
        now = datetime.now(UTC)
        row.dismissed_at = now
        if row.read_at is None:
            row.read_at = now
        await self._session.flush()


__all__ = ["NotificationService", "to_read", "validate_metadata", "ValidationError"]
