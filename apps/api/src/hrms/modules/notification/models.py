"""ORM model for the in-app notification feed. One row = one notification for one recipient."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from hrms.core.db.base import Base, TimestampMixin


class Notification(Base, TimestampMixin):
    __tablename__ = "notification"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    recipient_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE")
    )
    type: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(32))
    priority: Mapped[str] = mapped_column(String(16), default="NORMAL")
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    action_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    action_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    #: Non-sensitive, non-biometric context only (see `types.FORBIDDEN_METADATA_KEY_PARTS`).
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    #: Stable business-event identity, e.g. `FACE_ENROLLMENT_REQUESTED:<window id>`. Unique per
    #: recipient, so a retry or a lost race can never add a second notification.
    dedupe_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
