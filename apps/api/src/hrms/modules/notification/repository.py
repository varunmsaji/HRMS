"""Every query here is scoped by BOTH company and recipient: ownership is part of the WHERE
clause, so another user's (or another tenant's) id is indistinguishable from a missing one."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.modules.notification.models import DeviceToken, Notification


def _visible(company_id: UUID, user_id: UUID, now: datetime) -> list[ColumnElement[bool]]:
    return [
        Notification.company_id == company_id,
        Notification.recipient_user_id == user_id,
        Notification.dismissed_at.is_(None),
        or_(Notification.expires_at.is_(None), Notification.expires_at > now),
    ]


class NotificationRepository:
    async def insert_once(
        self, session: AsyncSession, *, values: dict[str, Any]
    ) -> Notification | None:
        """INSERT ... ON CONFLICT DO NOTHING on the dedupe index; None when it already existed."""
        stmt = (
            pg_insert(Notification)
            .values(**values)
            .on_conflict_do_nothing()
            .returning(Notification)
        )
        return (await session.execute(stmt)).scalars().first()

    async def list(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        user_id: UUID,
        now: datetime,
        unread_only: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[Notification], int]:
        conds = _visible(company_id, user_id, now)
        if unread_only:
            conds.append(Notification.read_at.is_(None))
        total = (
            await session.execute(select(func.count()).select_from(Notification).where(*conds))
        ).scalar_one()
        rows = (
            (
                await session.execute(
                    select(Notification)
                    .where(*conds)
                    .order_by(Notification.created_at.desc(), Notification.id.desc())
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
        return list(rows), total

    async def unread_count(
        self, session: AsyncSession, *, company_id: UUID, user_id: UUID, now: datetime
    ) -> int:
        return (
            await session.execute(
                select(func.count())
                .select_from(Notification)
                .where(*_visible(company_id, user_id, now), Notification.read_at.is_(None))
            )
        ).scalar_one()

    async def get_owned(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        user_id: UUID,
        notification_id: UUID,
        for_update: bool = False,
    ) -> Notification | None:
        stmt = select(Notification).where(
            Notification.id == notification_id,
            Notification.company_id == company_id,
            Notification.recipient_user_id == user_id,
            Notification.dismissed_at.is_(None),
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await session.execute(stmt)).scalars().first()

    async def mark_all_read(
        self, session: AsyncSession, *, company_id: UUID, user_id: UUID, now: datetime
    ) -> int:
        result = await session.execute(
            update(Notification)
            .where(*_visible(company_id, user_id, now), Notification.read_at.is_(None))
            .values(read_at=now)
        )
        return int(getattr(result, "rowcount", 0) or 0)


class DeviceRepository:
    """Device tokens, always scoped by company (and by user where a user is acting)."""

    async def upsert(
        self,
        session: AsyncSession,
        *,
        values: dict[str, Any],
    ) -> DeviceToken:
        """Insert, or move an existing token to this user (a second person on the same phone)."""
        stmt = (
            pg_insert(DeviceToken)
            .values(**values)
            .on_conflict_do_update(
                index_elements=[DeviceToken.company_id, DeviceToken.token],
                set_={
                    "user_id": values["user_id"],
                    "platform": values["platform"],
                    "app_version": values["app_version"],
                    "last_seen_at": values["last_seen_at"],
                    "updated_at": values["last_seen_at"],
                },
            )
            .returning(DeviceToken)
        )
        return (await session.execute(stmt)).scalars().one()

    async def delete_own(
        self, session: AsyncSession, *, company_id: UUID, user_id: UUID, token: str
    ) -> int:
        result = await session.execute(
            delete(DeviceToken).where(
                DeviceToken.company_id == company_id,
                DeviceToken.user_id == user_id,
                DeviceToken.token == token,
            )
        )
        return int(getattr(result, "rowcount", 0) or 0)

    async def for_user(
        self, session: AsyncSession, *, company_id: UUID, user_id: UUID
    ) -> list[DeviceToken]:
        rows = await session.execute(
            select(DeviceToken).where(
                DeviceToken.company_id == company_id, DeviceToken.user_id == user_id
            )
        )
        return list(rows.scalars().all())

    async def delete_ids(self, session: AsyncSession, *, company_id: UUID, ids: list[UUID]) -> None:
        if ids:
            await session.execute(
                delete(DeviceToken).where(
                    DeviceToken.company_id == company_id, DeviceToken.id.in_(ids)
                )
            )
