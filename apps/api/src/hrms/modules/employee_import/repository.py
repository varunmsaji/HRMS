"""Pure-query repository for employee_import — no business rules (Module Standard §2)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.modules.employee_import.models import EmployeeImportBatch, EmployeeImportRowError


class EmployeeImportRepository:
    async def insert_batch(
        self, session: AsyncSession, *, data: dict[str, Any]
    ) -> EmployeeImportBatch:
        row = EmployeeImportBatch(**data)
        session.add(row)
        await session.flush()
        return row

    async def get_batch(
        self, session: AsyncSession, *, company_id: UUID, batch_id: UUID
    ) -> EmployeeImportBatch | None:
        stmt = select(EmployeeImportBatch).where(
            EmployeeImportBatch.id == batch_id,
            EmployeeImportBatch.company_id == company_id,
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def claim_pending_batch(
        self, session: AsyncSession, *, company_id: UUID, batch_id: UUID, now: datetime
    ) -> bool:
        """Atomically moves a batch PENDING -> PROCESSING; `False` if it was not PENDING (already
        claimed by another delivery, already finished, or missing). A concurrent claimant blocks
        on the row lock and then re-evaluates the predicate, so exactly one wins."""
        stmt = (
            update(EmployeeImportBatch)
            .where(
                EmployeeImportBatch.id == batch_id,
                EmployeeImportBatch.company_id == company_id,
                EmployeeImportBatch.status == "PENDING",
            )
            .values(
                status="PROCESSING",
                started_at=now,
                updated_at=now,
                version=EmployeeImportBatch.version + 1,
            )
            .returning(EmployeeImportBatch.id)
            .execution_options(synchronize_session="fetch")
        )
        return (await session.execute(stmt)).first() is not None

    async def update_batch_progress(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        batch_id: UUID,
        values: dict[str, Any],
        now: datetime,
    ) -> None:
        batch = await self.get_batch(session, company_id=company_id, batch_id=batch_id)
        if batch is None:
            return
        for field, value in values.items():
            setattr(batch, field, value)
        batch.updated_at = now
        batch.version += 1
        await session.flush()

    async def insert_row_error(
        self, session: AsyncSession, *, data: dict[str, Any]
    ) -> EmployeeImportRowError:
        row = EmployeeImportRowError(**data)
        session.add(row)
        await session.flush()
        return row

    async def list_row_errors(
        self, session: AsyncSession, *, company_id: UUID, batch_id: UUID
    ) -> list[EmployeeImportRowError]:
        stmt = (
            select(EmployeeImportRowError)
            .where(
                EmployeeImportRowError.company_id == company_id,
                EmployeeImportRowError.batch_id == batch_id,
            )
            .order_by(EmployeeImportRowError.row_number)
        )
        return list((await session.execute(stmt)).scalars().all())
