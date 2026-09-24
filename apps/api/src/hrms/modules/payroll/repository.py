"""SQLAlchemy queries for the Payroll module. Every query carries a `company_id` predicate; RLS is
the backstop."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.modules.payroll.models import (
    EmployeeSalary,
    SalaryComponent,
    SalaryStructure,
    SalaryStructureLine,
    SalaryStructureVersion,
)


class SalaryComponentRepository:
    async def insert(self, session: AsyncSession, *, data: dict[str, Any]) -> SalaryComponent:
        row = SalaryComponent(**data)
        session.add(row)
        await session.flush()
        return row

    async def insert_if_missing(self, session: AsyncSession, *, data: dict[str, Any]) -> None:
        """Seed insert — a concurrent seeding of the same code is a no-op, not an error."""
        stmt = (
            pg_insert(SalaryComponent)
            .values(**data)
            .on_conflict_do_nothing(
                index_elements=["company_id", "code"],
                index_where=SalaryComponent.deleted_at.is_(None),
            )
        )
        await session.execute(stmt)

    async def get(
        self, session: AsyncSession, *, company_id: UUID, component_id: UUID
    ) -> SalaryComponent | None:
        stmt = select(SalaryComponent).where(
            SalaryComponent.id == component_id,
            SalaryComponent.company_id == company_id,
            SalaryComponent.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def list_for_company(
        self, session: AsyncSession, *, company_id: UUID
    ) -> list[SalaryComponent]:
        stmt = (
            select(SalaryComponent)
            .where(SalaryComponent.company_id == company_id, SalaryComponent.deleted_at.is_(None))
            .order_by(SalaryComponent.display_order, SalaryComponent.code)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def get_many(
        self, session: AsyncSession, *, company_id: UUID, component_ids: set[UUID]
    ) -> dict[UUID, SalaryComponent]:
        if not component_ids:
            return {}
        stmt = select(SalaryComponent).where(
            SalaryComponent.company_id == company_id,
            SalaryComponent.id.in_(component_ids),
            SalaryComponent.deleted_at.is_(None),
        )
        return {row.id: row for row in (await session.execute(stmt)).scalars().all()}

    async def update(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        component_id: UUID,
        values: dict[str, Any],
        expected_version: int,
        now: datetime,
    ) -> SalaryComponent | None:
        stmt = (
            update(SalaryComponent)
            .where(
                SalaryComponent.id == component_id,
                SalaryComponent.company_id == company_id,
                SalaryComponent.version == expected_version,
                SalaryComponent.deleted_at.is_(None),
            )
            .values(**values, version=expected_version + 1, updated_at=now)
            .returning(SalaryComponent)
        )
        return (await session.execute(stmt)).scalar_one_or_none()


class SalaryStructureRepository:
    # -- identity --

    async def insert(self, session: AsyncSession, *, data: dict[str, Any]) -> SalaryStructure:
        row = SalaryStructure(**data)
        session.add(row)
        await session.flush()
        return row

    async def get(
        self, session: AsyncSession, *, company_id: UUID, structure_id: UUID
    ) -> SalaryStructure | None:
        stmt = select(SalaryStructure).where(
            SalaryStructure.id == structure_id,
            SalaryStructure.company_id == company_id,
            SalaryStructure.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def get_by_code(
        self, session: AsyncSession, *, company_id: UUID, code: str
    ) -> SalaryStructure | None:
        stmt = select(SalaryStructure).where(
            SalaryStructure.company_id == company_id,
            SalaryStructure.code == code,
            SalaryStructure.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def list_for_company(
        self, session: AsyncSession, *, company_id: UUID
    ) -> list[SalaryStructure]:
        stmt = (
            select(SalaryStructure)
            .where(SalaryStructure.company_id == company_id, SalaryStructure.deleted_at.is_(None))
            .order_by(SalaryStructure.name)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def update(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        structure_id: UUID,
        values: dict[str, Any],
        expected_version: int,
        now: datetime,
    ) -> SalaryStructure | None:
        stmt = (
            update(SalaryStructure)
            .where(
                SalaryStructure.id == structure_id,
                SalaryStructure.company_id == company_id,
                SalaryStructure.version == expected_version,
                SalaryStructure.deleted_at.is_(None),
            )
            .values(**values, version=expected_version + 1, updated_at=now)
            .returning(SalaryStructure)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    # -- versions --

    async def insert_version(
        self, session: AsyncSession, *, data: dict[str, Any]
    ) -> SalaryStructureVersion:
        row = SalaryStructureVersion(**data)
        session.add(row)
        await session.flush()
        return row

    async def get_version(
        self, session: AsyncSession, *, company_id: UUID, structure_id: UUID, version_id: UUID
    ) -> SalaryStructureVersion | None:
        stmt = select(SalaryStructureVersion).where(
            SalaryStructureVersion.id == version_id,
            SalaryStructureVersion.salary_structure_id == structure_id,
            SalaryStructureVersion.company_id == company_id,
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def list_versions(
        self, session: AsyncSession, *, company_id: UUID, structure_ids: list[UUID]
    ) -> list[SalaryStructureVersion]:
        if not structure_ids:
            return []
        stmt = (
            select(SalaryStructureVersion)
            .where(
                SalaryStructureVersion.company_id == company_id,
                SalaryStructureVersion.salary_structure_id.in_(structure_ids),
            )
            .order_by(SalaryStructureVersion.version_number.desc())
        )
        return list((await session.execute(stmt)).scalars().all())

    async def max_version_number(
        self, session: AsyncSession, *, company_id: UUID, structure_id: UUID
    ) -> int:
        versions = await self.list_versions(
            session, company_id=company_id, structure_ids=[structure_id]
        )
        return max((v.version_number for v in versions), default=0)

    async def get_published_as_of(
        self, session: AsyncSession, *, company_id: UUID, structure_id: UUID, as_of: date
    ) -> SalaryStructureVersion | None:
        stmt = select(SalaryStructureVersion).where(
            SalaryStructureVersion.company_id == company_id,
            SalaryStructureVersion.salary_structure_id == structure_id,
            SalaryStructureVersion.status == "PUBLISHED",
            SalaryStructureVersion.effective_from <= as_of,
            or_(
                SalaryStructureVersion.effective_to.is_(None),
                SalaryStructureVersion.effective_to >= as_of,
            ),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def get_open_published(
        self, session: AsyncSession, *, company_id: UUID, structure_id: UUID
    ) -> SalaryStructureVersion | None:
        stmt = select(SalaryStructureVersion).where(
            SalaryStructureVersion.company_id == company_id,
            SalaryStructureVersion.salary_structure_id == structure_id,
            SalaryStructureVersion.status == "PUBLISHED",
            SalaryStructureVersion.effective_to.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def update_version(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        version_id: UUID,
        values: dict[str, Any],
        expected_version: int | None,
        now: datetime,
    ) -> SalaryStructureVersion | None:
        conditions = [
            SalaryStructureVersion.id == version_id,
            SalaryStructureVersion.company_id == company_id,
        ]
        if expected_version is not None:
            conditions.append(SalaryStructureVersion.version == expected_version)
        stmt = (
            update(SalaryStructureVersion)
            .where(*conditions)
            .values(**values, version=SalaryStructureVersion.version + 1, updated_at=now)
            .returning(SalaryStructureVersion)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def delete_version(
        self, session: AsyncSession, *, company_id: UUID, version_id: UUID
    ) -> None:
        await session.execute(
            delete(SalaryStructureLine).where(
                SalaryStructureLine.company_id == company_id,
                SalaryStructureLine.salary_structure_version_id == version_id,
            )
        )
        await session.execute(
            delete(SalaryStructureVersion).where(
                SalaryStructureVersion.company_id == company_id,
                SalaryStructureVersion.id == version_id,
            )
        )

    # -- lines --

    async def list_lines(
        self, session: AsyncSession, *, company_id: UUID, version_ids: list[UUID]
    ) -> list[SalaryStructureLine]:
        if not version_ids:
            return []
        stmt = (
            select(SalaryStructureLine)
            .where(
                SalaryStructureLine.company_id == company_id,
                SalaryStructureLine.salary_structure_version_id.in_(version_ids),
            )
            .order_by(SalaryStructureLine.display_order)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def replace_lines(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        version_id: UUID,
        rows: list[dict[str, Any]],
    ) -> None:
        await session.execute(
            delete(SalaryStructureLine).where(
                SalaryStructureLine.company_id == company_id,
                SalaryStructureLine.salary_structure_version_id == version_id,
            )
        )
        for data in rows:
            session.add(SalaryStructureLine(**data))
        await session.flush()


class EmployeeSalaryRepository:
    async def insert(self, session: AsyncSession, *, data: dict[str, Any]) -> EmployeeSalary:
        row = EmployeeSalary(**data)
        session.add(row)
        await session.flush()
        return row

    async def list_for_employee(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID
    ) -> list[EmployeeSalary]:
        stmt = (
            select(EmployeeSalary)
            .where(
                EmployeeSalary.company_id == company_id,
                EmployeeSalary.employee_id == employee_id,
                EmployeeSalary.deleted_at.is_(None),
            )
            .order_by(EmployeeSalary.effective_from)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def get_as_of(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID, as_of: date
    ) -> EmployeeSalary | None:
        stmt = select(EmployeeSalary).where(
            EmployeeSalary.company_id == company_id,
            EmployeeSalary.employee_id == employee_id,
            EmployeeSalary.deleted_at.is_(None),
            EmployeeSalary.effective_from <= as_of,
            or_(EmployeeSalary.effective_to.is_(None), EmployeeSalary.effective_to >= as_of),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def list_employee_ids_covering(
        self, session: AsyncSession, *, company_id: UUID, as_of: date
    ) -> set[UUID]:
        stmt = select(EmployeeSalary.employee_id).where(
            EmployeeSalary.company_id == company_id,
            EmployeeSalary.deleted_at.is_(None),
            EmployeeSalary.effective_from <= as_of,
            or_(EmployeeSalary.effective_to.is_(None), EmployeeSalary.effective_to >= as_of),
        )
        return set((await session.execute(stmt)).scalars().all())

    async def get_open(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID
    ) -> EmployeeSalary | None:
        stmt = select(EmployeeSalary).where(
            EmployeeSalary.company_id == company_id,
            EmployeeSalary.employee_id == employee_id,
            EmployeeSalary.deleted_at.is_(None),
            EmployeeSalary.effective_to.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def close(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        salary_id: UUID,
        effective_to: date,
        now: datetime,
    ) -> None:
        await session.execute(
            update(EmployeeSalary)
            .where(EmployeeSalary.id == salary_id, EmployeeSalary.company_id == company_id)
            .values(
                effective_to=effective_to,
                version=EmployeeSalary.version + 1,
                updated_at=now,
            )
        )
