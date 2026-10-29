"""Persistence for geofencing: extra workplace authorisations and the attempt log.

Every query carries an explicit `company_id` filter in addition to row-level security."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.modules.attendance.models import EmployeeWorkplaceAuthorization, GeofenceAttempt


class GeofenceRepository:
    # -- authorisations ----------------------------------------------------------------------

    async def list_authorizations(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        employee_id: UUID | None = None,
        branch_id: UUID | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[EmployeeWorkplaceAuthorization], int]:
        stmt = select(EmployeeWorkplaceAuthorization).where(
            EmployeeWorkplaceAuthorization.company_id == company_id
        )
        if employee_id is not None:
            stmt = stmt.where(EmployeeWorkplaceAuthorization.employee_id == employee_id)
        if branch_id is not None:
            stmt = stmt.where(EmployeeWorkplaceAuthorization.branch_id == branch_id)
        total = (
            await session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        stmt = (
            stmt.order_by(
                EmployeeWorkplaceAuthorization.created_at, EmployeeWorkplaceAuthorization.id
            )
            .limit(limit)
            .offset(offset)
        )
        return list((await session.execute(stmt)).scalars()), total

    async def authorized_branch_ids(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID
    ) -> list[UUID]:
        stmt = select(EmployeeWorkplaceAuthorization.branch_id).where(
            EmployeeWorkplaceAuthorization.company_id == company_id,
            EmployeeWorkplaceAuthorization.employee_id == employee_id,
        )
        return list((await session.execute(stmt)).scalars())

    async def get_authorization(
        self, session: AsyncSession, *, company_id: UUID, authorization_id: UUID
    ) -> EmployeeWorkplaceAuthorization | None:
        stmt = select(EmployeeWorkplaceAuthorization).where(
            EmployeeWorkplaceAuthorization.company_id == company_id,
            EmployeeWorkplaceAuthorization.id == authorization_id,
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def insert_authorization(
        self, session: AsyncSession, *, data: dict[str, Any]
    ) -> EmployeeWorkplaceAuthorization:
        row = EmployeeWorkplaceAuthorization(**data)
        session.add(row)
        await session.flush()
        return row

    async def delete_authorization(
        self, session: AsyncSession, *, company_id: UUID, authorization_id: UUID
    ) -> None:
        await session.execute(
            delete(EmployeeWorkplaceAuthorization).where(
                EmployeeWorkplaceAuthorization.company_id == company_id,
                EmployeeWorkplaceAuthorization.id == authorization_id,
            )
        )

    async def authorization_counts_by_branch(
        self, session: AsyncSession, *, company_id: UUID
    ) -> dict[UUID, int]:
        stmt = (
            select(EmployeeWorkplaceAuthorization.branch_id, func.count())
            .where(EmployeeWorkplaceAuthorization.company_id == company_id)
            .group_by(EmployeeWorkplaceAuthorization.branch_id)
        )
        return {branch_id: count for branch_id, count in (await session.execute(stmt)).all()}

    # -- attempts ----------------------------------------------------------------------------

    async def insert_attempt(
        self, session: AsyncSession, *, data: dict[str, Any]
    ) -> GeofenceAttempt:
        row = GeofenceAttempt(**data)
        session.add(row)
        await session.flush()
        return row

    async def list_attempts(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        employee_id: UUID | None = None,
        visible_employee_ids: frozenset[UUID] | None = None,
        accepted: bool | None = None,
        outcome: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[GeofenceAttempt], int]:
        conditions = [GeofenceAttempt.company_id == company_id]
        if employee_id is not None:
            conditions.append(GeofenceAttempt.employee_id == employee_id)
        if visible_employee_ids is not None:
            # None = COMPANY scope (no filter); an empty set sees nothing.
            conditions.append(GeofenceAttempt.employee_id.in_(visible_employee_ids))
        if accepted is not None:
            conditions.append(GeofenceAttempt.accepted == accepted)
        if outcome is not None:
            conditions.append(GeofenceAttempt.outcome == outcome)
        if since is not None:
            conditions.append(GeofenceAttempt.created_at >= since)
        if until is not None:
            conditions.append(GeofenceAttempt.created_at < until)
        base = select(GeofenceAttempt).where(and_(*conditions))
        total = (
            await session.execute(select(func.count()).select_from(base.subquery()))
        ).scalar_one()
        stmt = (
            base.order_by(GeofenceAttempt.created_at.desc(), GeofenceAttempt.id)
            .limit(limit)
            .offset(offset)
        )
        return list((await session.execute(stmt)).scalars()), total

    async def purge_attempts_before(
        self, session: AsyncSession, *, company_id: UUID, cutoff: datetime
    ) -> int:
        result = await session.execute(
            delete(GeofenceAttempt).where(
                GeofenceAttempt.company_id == company_id, GeofenceAttempt.created_at < cutoff
            )
        )
        return int(result.rowcount or 0)  # type: ignore[attr-defined]
