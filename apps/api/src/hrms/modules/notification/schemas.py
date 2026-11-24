from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


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


class DeviceRegister(BaseModel):
    #: The FCM registration token the app got from Firebase.
    token: str = Field(min_length=20, max_length=4096)
    platform: Literal["android", "ios"]
    app_version: str | None = Field(default=None, max_length=32)


class DeviceUnregister(BaseModel):
    token: str = Field(min_length=20, max_length=4096)


class DeviceRead(BaseModel):
    id: UUID
    platform: str
    last_seen_at: datetime
