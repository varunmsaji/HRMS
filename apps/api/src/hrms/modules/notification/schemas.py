from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class NotificationRead(BaseModel):
    id: UUID
    type: str
    category: str
    priority: str
    title: str
    body: str
    entity_type: str | None = None
    entity_id: UUID | None = None
    action_url: str | None = None
    action_label: str | None = None
    metadata: dict[str, Any]
    is_read: bool
    read_at: datetime | None = None
    created_at: datetime
    expires_at: datetime | None = None


class UnreadCountRead(BaseModel):
    unread_count: int


class ReadAllRead(BaseModel):
    updated: int
    unread_count: int
