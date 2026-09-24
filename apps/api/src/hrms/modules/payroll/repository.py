"""SQLAlchemy queries for the Payroll module. Every query carries a `company_id` predicate; RLS is
the backstop.

Pay runs (Phase 5.2): a `FINALISED`/`PAID` run is immutable (ADR-0005, decision 15). Every write in
`PayRunRepository` that touches a run's employees or lines, or the run itself, is conditioned on
the run's status (`_MUTABLE`), so no code path can change a finalised run — only
`mark_paid` moves `FINALISED → PAID`."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.modules.payroll.models import (
    EmployeeSalary,
    PayrollSetting,
    PayRun,
    PayRunEmployee,
    PayRunLine,
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


# ---------------------------------------------------------------------------
# Phase 5.2 — settings and pay runs
# ---------------------------------------------------------------------------

_MUTABLE = ("DRAFT", "INPUTS_LOCKED", "COMPUTED", "APPROVED")


class PayrollSettingRepository:
    async def get_or_create(
        self, session: AsyncSession, *, company_id: UUID, now: datetime
    ) -> PayrollSetting:
        await session.execute(
            pg_insert(PayrollSetting)
            .values(company_id=company_id, version=1, created_at=now, updated_at=now)
            .on_conflict_do_nothing(index_elements=["company_id"])
        )
        stmt = select(PayrollSetting).where(PayrollSetting.company_id == company_id)
        return (await session.execute(stmt)).scalar_one()

    async def update(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        values: dict[str, Any],
        expected_version: int,
        now: datetime,
    ) -> PayrollSetting | None:
        stmt = (
            update(PayrollSetting)
            .where(
                PayrollSetting.company_id == company_id,
                PayrollSetting.version == expected_version,
            )
            .values(**values, version=expected_version + 1, updated_at=now)
            .returning(PayrollSetting)
        )
        return (await session.execute(stmt)).scalar_one_or_none()


class PayRunRepository:
    # -- run --

    async def insert(self, session: AsyncSession, *, data: dict[str, Any]) -> PayRun:
        row = PayRun(**data)
        session.add(row)
        await session.flush()
        return row

    async def get(self, session: AsyncSession, *, company_id: UUID, run_id: UUID) -> PayRun | None:
        stmt = select(PayRun).where(PayRun.id == run_id, PayRun.company_id == company_id)
        return (await session.execute(stmt)).scalar_one_or_none()

    async def list_for_company(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        legal_entity_id: UUID | None = None,
        status: str | None = None,
    ) -> list[PayRun]:
        conditions = [PayRun.company_id == company_id]
        if legal_entity_id is not None:
            conditions.append(PayRun.legal_entity_id == legal_entity_id)
        if status is not None:
            conditions.append(PayRun.status == status)
        stmt = (
            select(PayRun)
            .where(*conditions)
            .order_by(PayRun.period_month.desc(), PayRun.created_at.desc())
        )
        return list((await session.execute(stmt)).scalars().all())

    async def get_previous_finalised(
        self, session: AsyncSession, *, company_id: UUID, legal_entity_id: UUID, before: date
    ) -> PayRun | None:
        """The latest `FINALISED`/`PAID` run of the entity for a month before `before` — the
        variance baseline (FR-PAY-014)."""
        stmt = (
            select(PayRun)
            .where(
                PayRun.company_id == company_id,
                PayRun.legal_entity_id == legal_entity_id,
                PayRun.period_month < before,
                PayRun.status.in_(("FINALISED", "PAID")),
            )
            .order_by(PayRun.period_month.desc())
            .limit(1)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def has_finalised_for_period(
        self, session: AsyncSession, *, company_id: UUID, attendance_period_id: UUID
    ) -> bool:
        stmt = (
            select(PayRun.id)
            .where(
                PayRun.company_id == company_id,
                PayRun.attendance_period_id == attendance_period_id,
                PayRun.status.in_(("FINALISED", "PAID")),
            )
            .limit(1)
        )
        return (await session.execute(stmt)).first() is not None

    async def update(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        run_id: UUID,
        values: dict[str, Any],
        expected_version: int | None,
        now: datetime,
        from_statuses: tuple[str, ...] = _MUTABLE,
    ) -> PayRun | None:
        """Version-guarded (when `expected_version` is given) and status-guarded: `None` when the
        run moved on or is not in one of `from_statuses`. Never matches a finalised run unless the
        caller names `FINALISED` explicitly (only `mark_paid` does)."""
        conditions = [
            PayRun.id == run_id,
            PayRun.company_id == company_id,
            PayRun.status.in_(from_statuses),
        ]
        if expected_version is not None:
            conditions.append(PayRun.version == expected_version)
        stmt = (
            update(PayRun)
            .where(*conditions)
            .values(**values, version=PayRun.version + 1, updated_at=now)
            .returning(PayRun)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def delete_draft(self, session: AsyncSession, *, company_id: UUID, run_id: UUID) -> bool:
        stmt = delete(PayRun).where(
            PayRun.id == run_id, PayRun.company_id == company_id, PayRun.status == "DRAFT"
        )
        result = await session.execute(stmt)
        return bool(getattr(result, "rowcount", 0))

    # -- employees --

    async def insert_employees(self, session: AsyncSession, *, rows: list[dict[str, Any]]) -> None:
        if rows:
            session.add_all([PayRunEmployee(**row) for row in rows])
            await session.flush()

    async def list_employees(
        self, session: AsyncSession, *, company_id: UUID, run_id: UUID
    ) -> list[PayRunEmployee]:
        stmt = (
            select(PayRunEmployee)
            .where(PayRunEmployee.company_id == company_id, PayRunEmployee.pay_run_id == run_id)
            .order_by(PayRunEmployee.employee_code, PayRunEmployee.employee_name)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def get_employee(
        self, session: AsyncSession, *, company_id: UUID, run_id: UUID, employee_id: UUID
    ) -> PayRunEmployee | None:
        stmt = select(PayRunEmployee).where(
            PayRunEmployee.company_id == company_id,
            PayRunEmployee.pay_run_id == run_id,
            PayRunEmployee.employee_id == employee_id,
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    def _run_mutable(self, run_id: UUID) -> Any:
        return select(PayRun.id).where(PayRun.id == run_id, PayRun.status.in_(_MUTABLE))

    async def update_employee(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        run_id: UUID,
        row_id: UUID,
        values: dict[str, Any],
        now: datetime,
    ) -> PayRunEmployee | None:
        stmt = (
            update(PayRunEmployee)
            .where(
                PayRunEmployee.id == row_id,
                PayRunEmployee.company_id == company_id,
                PayRunEmployee.pay_run_id.in_(self._run_mutable(run_id)),
            )
            .values(**values, updated_at=now)
            .returning(PayRunEmployee)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def delete_employees(
        self, session: AsyncSession, *, company_id: UUID, run_id: UUID
    ) -> None:
        await session.execute(
            delete(PayRunEmployee).where(
                PayRunEmployee.company_id == company_id,
                PayRunEmployee.pay_run_id.in_(self._run_mutable(run_id)),
            )
        )

    # -- lines --

    async def replace_lines(
        self, session: AsyncSession, *, company_id: UUID, run_id: UUID, rows: list[dict[str, Any]]
    ) -> None:
        await self.delete_lines(session, company_id=company_id, run_id=run_id)
        if rows:
            session.add_all([PayRunLine(**row) for row in rows])
            await session.flush()

    async def delete_lines(self, session: AsyncSession, *, company_id: UUID, run_id: UUID) -> None:
        await session.execute(
            delete(PayRunLine).where(
                PayRunLine.company_id == company_id,
                PayRunLine.pay_run_id.in_(self._run_mutable(run_id)),
            )
        )

    async def list_lines(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        run_id: UUID,
        employee_id: UUID | None = None,
    ) -> list[PayRunLine]:
        conditions = [PayRunLine.company_id == company_id, PayRunLine.pay_run_id == run_id]
        if employee_id is not None:
            conditions.append(PayRunLine.employee_id == employee_id)
        stmt = (
            select(PayRunLine)
            .where(*conditions)
            .order_by(PayRunLine.employee_id, PayRunLine.display_order, PayRunLine.component_code)
        )
        return list((await session.execute(stmt)).scalars().all())
