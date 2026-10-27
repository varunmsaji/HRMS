"""SQLAlchemy queries for the Payroll module. Every query carries a `company_id` predicate; RLS is
the backstop.

Pay runs (Phase 5.2): a `FINALISED`/`PAID` run is immutable (ADR-0005, decision 15). Every write in
`PayRunRepository` that touches a run's employees or lines, or the run itself, is conditioned on
the run's status (`_MUTABLE`), so no code path can change a finalised run — only
`mark_paid` moves `FINALISED → PAID`."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.audit.models import AuditLog
from hrms.modules.payroll.models import (
    EmployeeSalary,
    PayAdjustment,
    PayrollSetting,
    PayRun,
    PayRunArrear,
    PayRunEmployee,
    PayRunLine,
    SalaryComponent,
    SalaryStructure,
    SalaryStructureLine,
    SalaryStructureVersion,
    StatutoryRate,
)
from hrms.shared.pagination import PageParams, fetch_page


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

    async def page_for_company(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        page: PageParams,
        legal_entity_id: UUID | None = None,
        status: str | None = None,
    ) -> tuple[list[PayRun], int]:
        """Bounded variant of `list_for_company` (API audit H-1); `id` makes the order total."""
        conditions = [PayRun.company_id == company_id]
        if legal_entity_id is not None:
            conditions.append(PayRun.legal_entity_id == legal_entity_id)
        if status is not None:
            conditions.append(PayRun.status == status)
        stmt = (
            select(PayRun)
            .where(*conditions)
            .order_by(PayRun.period_month.desc(), PayRun.created_at.desc(), PayRun.id)
        )
        return await fetch_page(session, stmt, page)

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

    async def page_employees(
        self, session: AsyncSession, *, company_id: UUID, run_id: UUID, page: PageParams
    ) -> tuple[list[PayRunEmployee], int]:
        stmt = (
            select(PayRunEmployee)
            .where(PayRunEmployee.company_id == company_id, PayRunEmployee.pay_run_id == run_id)
            .order_by(PayRunEmployee.employee_code, PayRunEmployee.employee_name, PayRunEmployee.id)
        )
        return await fetch_page(session, stmt, page)

    async def list_final_for_employee(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID
    ) -> list[tuple[PayRun, PayRunEmployee]]:
        """Payroll 5.4 — the employee's rows in `FINALISED`/`PAID` runs, newest month first."""
        stmt = (
            select(PayRun, PayRunEmployee)
            .join(PayRunEmployee, PayRunEmployee.pay_run_id == PayRun.id)
            .where(
                PayRun.company_id == company_id,
                PayRun.status.in_(("FINALISED", "PAID")),
                PayRunEmployee.employee_id == employee_id,
            )
            .order_by(PayRun.period_month.desc())
        )
        return [(run, row) for run, row in (await session.execute(stmt)).all()]

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

    async def ytd_income_tax_totals(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        legal_entity_id: UUID,
        employee_id: UUID,
        fy_start: date,
        before_month: date,
    ) -> dict[str, int]:
        """Phase 5.6 — gross earnings actually paid and TDS actually deducted for this employee
        in this legal entity's `FINALISED`/`PAID` runs from `fy_start` up to (not including)
        `before_month` — what Section 192's average-rate method needs as "already paid so far
        this year". Reads `pay_run_line` (not `pay_run_arrear`) because arrears are themselves
        materialised as ordinary lines in the run that pays them — correct under cash-basis TDS,
        since money is taxed in the month it is actually received."""
        stmt = (
            select(
                PayRunLine.line_type, PayRunLine.component_code, func.sum(PayRunLine.amount_minor)
            )  # fmt: skip
            .join(PayRun, PayRun.id == PayRunLine.pay_run_id)
            .where(
                PayRunLine.company_id == company_id,
                PayRun.legal_entity_id == legal_entity_id,
                PayRunLine.employee_id == employee_id,
                PayRun.period_month >= fy_start,
                PayRun.period_month < before_month,
                PayRun.status.in_(("FINALISED", "PAID")),
            )
            .group_by(PayRunLine.line_type, PayRunLine.component_code)
        )
        gross_minor = 0
        tds_minor = 0
        for line_type, code, total in (await session.execute(stmt)).all():
            if line_type == "EARNING":
                gross_minor += int(total)
            if code == "TDS_EMPLOYEE":
                tds_minor += int(total)
        return {"gross_minor": gross_minor, "tds_minor": tds_minor}


# ---------------------------------------------------------------------------
# Phase 5.3 — statutory rates
# ---------------------------------------------------------------------------


class StatutoryRateRepository:
    async def insert(self, session: AsyncSession, *, data: dict[str, Any]) -> StatutoryRate:
        row = StatutoryRate(**data)
        session.add(row)
        await session.flush()
        return row

    async def get(
        self, session: AsyncSession, *, company_id: UUID, rate_id: UUID
    ) -> StatutoryRate | None:
        stmt = select(StatutoryRate).where(
            StatutoryRate.id == rate_id, StatutoryRate.company_id == company_id
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def list_for_company(
        self, session: AsyncSession, *, company_id: UUID, scheme: str | None = None
    ) -> list[StatutoryRate]:
        conditions = [StatutoryRate.company_id == company_id]
        if scheme is not None:
            conditions.append(StatutoryRate.scheme == scheme)
        stmt = (
            select(StatutoryRate)
            .where(*conditions)
            .order_by(
                StatutoryRate.scheme,
                StatutoryRate.state_code.nulls_first(),
                StatutoryRate.effective_from.desc(),
            )
        )
        return list((await session.execute(stmt)).scalars().all())

    async def get_as_of(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        scheme: str,
        state_code: str | None,
        as_of: date,
    ) -> StatutoryRate | None:
        stmt = select(StatutoryRate).where(
            StatutoryRate.company_id == company_id,
            StatutoryRate.scheme == scheme,
            (
                StatutoryRate.state_code.is_(None)
                if state_code is None
                else StatutoryRate.state_code == state_code
            ),
            StatutoryRate.effective_from <= as_of,
            or_(StatutoryRate.effective_to.is_(None), StatutoryRate.effective_to >= as_of),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def get_open(
        self, session: AsyncSession, *, company_id: UUID, scheme: str, state_code: str | None
    ) -> StatutoryRate | None:
        stmt = select(StatutoryRate).where(
            StatutoryRate.company_id == company_id,
            StatutoryRate.scheme == scheme,
            (
                StatutoryRate.state_code.is_(None)
                if state_code is None
                else StatutoryRate.state_code == state_code
            ),
            StatutoryRate.effective_to.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def update(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        rate_id: UUID,
        values: dict[str, Any],
        expected_version: int | None,
        now: datetime,
    ) -> StatutoryRate | None:
        conditions = [StatutoryRate.id == rate_id, StatutoryRate.company_id == company_id]
        if expected_version is not None:
            conditions.append(StatutoryRate.version == expected_version)
        stmt = (
            update(StatutoryRate)
            .where(*conditions)
            .values(**values, version=StatutoryRate.version + 1, updated_at=now)
            .returning(StatutoryRate)
        )
        return (await session.execute(stmt)).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Phase 5.5 — arrears
# ---------------------------------------------------------------------------


class PayAdjustmentRepository:
    async def insert(self, session: AsyncSession, *, data: dict[str, Any]) -> PayAdjustment:
        row = PayAdjustment(**data)
        session.add(row)
        await session.flush()
        return row

    async def get(
        self, session: AsyncSession, *, company_id: UUID, adjustment_id: UUID
    ) -> PayAdjustment | None:
        stmt = select(PayAdjustment).where(
            PayAdjustment.id == adjustment_id, PayAdjustment.company_id == company_id
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def list_filtered(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        legal_entity_id: UUID | None = None,
        source_pay_run_id: UUID | None = None,
        status: str | None = None,
        employee_id: UUID | None = None,
    ) -> list[PayAdjustment]:
        conditions = [PayAdjustment.company_id == company_id]
        if legal_entity_id is not None:
            conditions.append(PayAdjustment.legal_entity_id == legal_entity_id)
        if source_pay_run_id is not None:
            conditions.append(PayAdjustment.source_pay_run_id == source_pay_run_id)
        if status is not None:
            conditions.append(PayAdjustment.status == status)
        if employee_id is not None:
            conditions.append(PayAdjustment.employee_id == employee_id)
        stmt = (
            select(PayAdjustment)
            .where(*conditions)
            .order_by(PayAdjustment.for_month, PayAdjustment.created_at)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def page_filtered(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        page: PageParams,
        legal_entity_id: UUID | None = None,
        source_pay_run_id: UUID | None = None,
        status: str | None = None,
    ) -> tuple[list[PayAdjustment], int]:
        conditions = [PayAdjustment.company_id == company_id]
        if legal_entity_id is not None:
            conditions.append(PayAdjustment.legal_entity_id == legal_entity_id)
        if source_pay_run_id is not None:
            conditions.append(PayAdjustment.source_pay_run_id == source_pay_run_id)
        if status is not None:
            conditions.append(PayAdjustment.status == status)
        stmt = (
            select(PayAdjustment)
            .where(*conditions)
            .order_by(PayAdjustment.for_month, PayAdjustment.created_at, PayAdjustment.id)
        )
        return await fetch_page(session, stmt, page)

    async def delete_pending(
        self, session: AsyncSession, *, company_id: UUID, adjustment_id: UUID
    ) -> bool:
        result = await session.execute(
            delete(PayAdjustment).where(
                PayAdjustment.id == adjustment_id,
                PayAdjustment.company_id == company_id,
                PayAdjustment.status == "PENDING",
            )
        )
        return bool(getattr(result, "rowcount", 0))

    async def mark_applied(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        adjustment_ids: list[UUID],
        pay_run_id: UUID,
        now: datetime,
    ) -> int:
        """Only still-`PENDING` rows — the count tells the caller whether another run got there
        first."""
        if not adjustment_ids:
            return 0
        result = await session.execute(
            update(PayAdjustment)
            .where(
                PayAdjustment.company_id == company_id,
                PayAdjustment.id.in_(adjustment_ids),
                PayAdjustment.status == "PENDING",
            )
            .values(
                status="APPLIED",
                applied_pay_run_id=pay_run_id,
                version=PayAdjustment.version + 1,
                updated_at=now,
            )
        )
        return int(getattr(result, "rowcount", 0))


class PayRunArrearRepository:
    async def replace_for_run(
        self, session: AsyncSession, *, company_id: UUID, run_id: UUID, rows: list[dict[str, Any]]
    ) -> None:
        mutable = select(PayRun.id).where(PayRun.id == run_id, PayRun.status.in_(_MUTABLE))
        await session.execute(
            delete(PayRunArrear).where(
                PayRunArrear.company_id == company_id, PayRunArrear.pay_run_id.in_(mutable)
            )
        )
        if rows:
            session.add_all([PayRunArrear(**row) for row in rows])
            await session.flush()

    async def delete_for_run(
        self, session: AsyncSession, *, company_id: UUID, run_id: UUID
    ) -> None:
        await self.replace_for_run(session, company_id=company_id, run_id=run_id, rows=[])

    async def payment_counts(
        self, session: AsyncSession, *, company_id: UUID, source_run_ids: list[UUID]
    ) -> dict[tuple[UUID, UUID, str], int]:
        """Arrears payments already finalised per (employee, source run, component) — a run being
        computed numbers its own payments one higher."""
        if not source_run_ids:
            return {}
        stmt = (
            select(
                PayRunArrear.employee_id,
                PayRunArrear.source_pay_run_id,
                PayRunArrear.component_code,
                func.count(),
            )
            .where(
                PayRunArrear.company_id == company_id,
                PayRunArrear.source_pay_run_id.in_(source_run_ids),
                PayRunArrear.applied_at.is_not(None),
            )
            .group_by(
                PayRunArrear.employee_id,
                PayRunArrear.source_pay_run_id,
                PayRunArrear.component_code,
            )
        )
        return {(e, s, c): int(n) for e, s, c, n in (await session.execute(stmt)).all()}

    async def mark_applied(
        self, session: AsyncSession, *, company_id: UUID, run_id: UUID, now: datetime
    ) -> int:
        """PAY-A03 — stamps the run's arrears as paid. If another run already stamped the same
        payment number for the same (employee, source run, component), the unique index raises
        `IntegrityError`: this run read arrears that have since been paid."""
        result = await session.execute(
            update(PayRunArrear)
            .where(
                PayRunArrear.company_id == company_id,
                PayRunArrear.pay_run_id == run_id,
                PayRunArrear.applied_at.is_(None),
            )
            .values(applied_at=now)
        )
        return int(getattr(result, "rowcount", 0))

    async def paid_for_month(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID, for_month: date
    ) -> dict[str, int]:
        """Arrears already paid for `for_month`, per component, by `FINALISED`/`PAID` runs."""
        stmt = (
            select(PayRunArrear.component_code, func.sum(PayRunArrear.amount_minor))
            .join(PayRun, PayRun.id == PayRunArrear.pay_run_id)
            .where(
                PayRunArrear.company_id == company_id,
                PayRunArrear.employee_id == employee_id,
                PayRunArrear.for_month == for_month,
                PayRun.status.in_(("FINALISED", "PAID")),
            )
            .group_by(PayRunArrear.component_code)
        )
        return {code: int(total) for code, total in (await session.execute(stmt)).all()}


class StatutoryAuditReader:
    """Read-only view of `audit_log` for one statutory rate (separation of duties on verify)."""

    async def list_rate_events(
        self, session: AsyncSession, *, company_id: UUID, rate_id: UUID
    ) -> list[AuditLog]:
        stmt = (
            select(AuditLog)
            .where(
                AuditLog.company_id == company_id,
                AuditLog.entity_type == "statutory_rate",
                AuditLog.entity_id == rate_id,
            )
            .order_by(AuditLog.occurred_at, AuditLog.id)
        )
        return list((await session.execute(stmt)).scalars().all())
