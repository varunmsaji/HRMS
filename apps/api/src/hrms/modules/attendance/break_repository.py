"""Persistence for break events and employee break overrides (break management V1).

Events are append-only: this repository only ever inserts them (the DB trigger refuses UPDATE).
Overrides are never edited in place either — `revoke` stamps `revoked_at`, a change inserts a
new row."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.modules.attendance.models import AttendanceBreakEvent, EmployeeBreakOverride


class BreakEventRepository:
    async def insert(self, session: AsyncSession, *, data: dict[str, Any]) -> AttendanceBreakEvent:
        row = AttendanceBreakEvent(**data)
        session.add(row)
        await session.flush()
        return row

    async def get(
        self, session: AsyncSession, *, company_id: UUID, event_id: UUID
    ) -> AttendanceBreakEvent | None:
        stmt = select(AttendanceBreakEvent).where(
            AttendanceBreakEvent.company_id == company_id, AttendanceBreakEvent.id == event_id
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def get_by_idempotency_key(
        self, session: AsyncSession, *, company_id: UUID, idempotency_key: str
    ) -> AttendanceBreakEvent | None:
        stmt = select(AttendanceBreakEvent).where(
            AttendanceBreakEvent.company_id == company_id,
            AttendanceBreakEvent.idempotency_key == idempotency_key,
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def list_for_date(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID, attendance_date: date
    ) -> list[AttendanceBreakEvent]:
        stmt = (
            select(AttendanceBreakEvent)
            .where(
                AttendanceBreakEvent.company_id == company_id,
                AttendanceBreakEvent.employee_id == employee_id,
                AttendanceBreakEvent.attendance_date == attendance_date,
            )
            .order_by(AttendanceBreakEvent.event_time, AttendanceBreakEvent.created_at)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def list_in_range(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        employee_ids: frozenset[UUID] | None,
        date_from: date,
        date_to: date,
        limit: int = 1000,
    ) -> list[AttendanceBreakEvent]:
        stmt = select(AttendanceBreakEvent).where(
            AttendanceBreakEvent.company_id == company_id,
            AttendanceBreakEvent.attendance_date >= date_from,
            AttendanceBreakEvent.attendance_date <= date_to,
        )
        if employee_ids is not None:
            stmt = stmt.where(AttendanceBreakEvent.employee_id.in_(employee_ids))
        stmt = stmt.order_by(
            AttendanceBreakEvent.attendance_date, AttendanceBreakEvent.event_time
        ).limit(limit)
        return list((await session.execute(stmt)).scalars().all())

    async def has_superseding_event(
        self, session: AsyncSession, *, company_id: UUID, event_id: UUID
    ) -> bool:
        stmt = select(AttendanceBreakEvent.id).where(
            AttendanceBreakEvent.company_id == company_id,
            AttendanceBreakEvent.supersedes_event_id == event_id,
        )
        return (await session.execute(stmt)).first() is not None


class EmployeeBreakOverrideRepository:
    async def insert(self, session: AsyncSession, *, data: dict[str, Any]) -> EmployeeBreakOverride:
        row = EmployeeBreakOverride(**data)
        session.add(row)
        await session.flush()
        return row

    async def get(
        self, session: AsyncSession, *, company_id: UUID, override_id: UUID
    ) -> EmployeeBreakOverride | None:
        stmt = select(EmployeeBreakOverride).where(
            EmployeeBreakOverride.company_id == company_id,
            EmployeeBreakOverride.id == override_id,
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def list_for_employee(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        employee_id: UUID,
        include_revoked: bool = False,
    ) -> list[EmployeeBreakOverride]:
        stmt = select(EmployeeBreakOverride).where(
            EmployeeBreakOverride.company_id == company_id,
            EmployeeBreakOverride.employee_id == employee_id,
        )
        if not include_revoked:
            stmt = stmt.where(EmployeeBreakOverride.revoked_at.is_(None))
        stmt = stmt.order_by(EmployeeBreakOverride.effective_from, EmployeeBreakOverride.id)
        return list((await session.execute(stmt)).scalars().all())

    async def list_in_force(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        employee_id: UUID,
        target_date: date,
    ) -> list[EmployeeBreakOverride]:
        stmt = (
            select(EmployeeBreakOverride)
            .where(
                EmployeeBreakOverride.company_id == company_id,
                EmployeeBreakOverride.employee_id == employee_id,
                EmployeeBreakOverride.revoked_at.is_(None),
                EmployeeBreakOverride.effective_from <= target_date,
                or_(
                    EmployeeBreakOverride.effective_to.is_(None),
                    and_(EmployeeBreakOverride.effective_to >= target_date),
                ),
            )
            .order_by(EmployeeBreakOverride.effective_from, EmployeeBreakOverride.id)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def revoke(
        self,
        session: AsyncSession,
        *,
        row: EmployeeBreakOverride,
        revoked_by: UUID | None,
        reason: str,
        now: datetime,
    ) -> EmployeeBreakOverride:
        row.revoked_at = now
        row.revoked_by = revoked_by
        row.revoke_reason = reason
        row.updated_at = now
        await session.flush()
        return row
