"""Pure-query repository for the employee module — no business rules (Module Standard §2),
mirroring `organisation/repository.py`'s own convention exactly."""

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.modules.employee.models import (
    Employee,
    EmployeeAssignment,
    EmployeeCompensation,
    Employment,
)


class EmployeeRepository:
    async def insert_employee(self, session: AsyncSession, *, data: dict[str, Any]) -> Employee:
        row = Employee(**data)
        session.add(row)
        await session.flush()
        return row

    async def list_employees(self, session: AsyncSession, *, company_id: UUID) -> list[Employee]:
        stmt = (
            select(Employee)
            .where(Employee.company_id == company_id, Employee.deleted_at.is_(None))
            .order_by(Employee.created_at)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def count_active_employees(self, session: AsyncSession, *, company_id: UUID) -> int:
        """Counts non-deleted, `is_active` employees — the population the `EMPLOYEE_SEATS`
        plan limit is checked against (`docs/modules/employee/
        05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part A6)."""
        stmt = select(func.count()).where(
            Employee.company_id == company_id,
            Employee.deleted_at.is_(None),
            Employee.is_active.is_(True),
        )
        return int((await session.execute(stmt)).scalar_one())

    async def get_employee(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID
    ) -> Employee | None:
        # `company_id` filtered explicitly, not just relied on via RLS — same
        # belt-and-suspenders convention as `OrganisationRepository.get_grade`.
        stmt = select(Employee).where(
            Employee.id == employee_id,
            Employee.company_id == company_id,
            Employee.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def update_employee(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        employee_id: UUID,
        values: dict[str, Any],
        expected_version: int,
        now: datetime,
    ) -> Employee | None:
        stmt = (
            update(Employee)
            .where(
                Employee.id == employee_id,
                Employee.company_id == company_id,
                Employee.version == expected_version,
                Employee.deleted_at.is_(None),
            )
            .values(**values, version=expected_version + 1, updated_at=now)
            .returning(Employee)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def allocate_employee_code(self, session: AsyncSession, *, company_id: UUID) -> str:
        """Race-safe `EMPLOYEE_CODE` allocation — `UPDATE ... RETURNING` inside the same
        transaction, never `SELECT max()+1` (`docs/product/08_Database_Architecture.md` §4's
        explicit warning). Lazily creates the company's `number_series` row on first use
        (`ON CONFLICT DO NOTHING`) rather than requiring `organisation`'s registration flow to
        seed it — this keeps the allocator fully self-contained inside the employee module
        (`01_EMPLOYEE_FOUNDATION_AUDIT.md` §1.6)."""
        await session.execute(
            text(
                """
                INSERT INTO number_series
                    (id, company_id, entity_type, prefix, separator, current_number, padding,
                     reset_rule, created_at, updated_at)
                VALUES
                    (:id, :company_id, 'EMPLOYEE_CODE', 'EMP', '-', 0, 4, 'NEVER', now(), now())
                ON CONFLICT (company_id, entity_type) DO NOTHING
                """
            ),
            {"id": str(uuid4()), "company_id": str(company_id)},
        )
        result = await session.execute(
            text(
                """
                UPDATE number_series
                SET current_number = current_number + 1, updated_at = now()
                WHERE company_id = :company_id AND entity_type = 'EMPLOYEE_CODE'
                RETURNING current_number, prefix, separator, padding
                """
            ),
            {"company_id": str(company_id)},
        )
        row = result.one()
        current_number, prefix, separator, padding = row
        return f"{prefix}{separator}{current_number:0{padding}d}"


class EmploymentRepository:
    async def insert_employment(self, session: AsyncSession, *, data: dict[str, Any]) -> Employment:
        row = Employment(**data)
        session.add(row)
        await session.flush()
        return row

    async def get_latest_employment(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID
    ) -> Employment | None:
        """Most recent employment row for this employee, by `joining_date` — the row a new
        insert should link to via `previous_employment_id` when one exists. Not filtered by
        `status`: by construction (the `employment_no_overlap` GiST exclusion constraint) this
        can only be `TERMINATED` whenever a new `ACTIVE` row is about to be inserted, since an
        `ACTIVE` row would make the new insert overlap and fail at the database."""
        stmt = (
            select(Employment)
            .where(
                Employment.company_id == company_id,
                Employment.employee_id == employee_id,
                Employment.deleted_at.is_(None),
            )
            .order_by(Employment.joining_date.desc())
            .limit(1)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def list_employments(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID
    ) -> list[Employment]:
        stmt = (
            select(Employment)
            .where(
                Employment.company_id == company_id,
                Employment.employee_id == employee_id,
                Employment.deleted_at.is_(None),
            )
            .order_by(Employment.joining_date)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def get_employment_as_of(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID, as_of: date
    ) -> Employment | None:
        """The employment episode (at most one, by the `employment_no_overlap` exclusion
        constraint) covering `as_of` — `joining_date <= as_of <= last_working_day`, treating a
        `NULL` `last_working_day` (an open/`ACTIVE` spell) as extending to infinity. This is
        the "does employee X have an active employment on date Y" contract
        (`docs/modules/employee/01_EMPLOYEE_MODULE_PLAN.md` §3 item 3)."""
        stmt = select(Employment).where(
            Employment.company_id == company_id,
            Employment.employee_id == employee_id,
            Employment.deleted_at.is_(None),
            Employment.joining_date <= as_of,
            or_(Employment.last_working_day.is_(None), Employment.last_working_day >= as_of),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def get_employment(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        employee_id: UUID,
        employment_id: UUID,
    ) -> Employment | None:
        stmt = select(Employment).where(
            Employment.id == employment_id,
            Employment.employee_id == employee_id,
            Employment.company_id == company_id,
            Employment.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def update_employment(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        employee_id: UUID,
        employment_id: UUID,
        values: dict[str, Any],
        expected_version: int,
        now: datetime,
    ) -> Employment | None:
        stmt = (
            update(Employment)
            .where(
                Employment.id == employment_id,
                Employment.employee_id == employee_id,
                Employment.company_id == company_id,
                Employment.version == expected_version,
                Employment.deleted_at.is_(None),
            )
            .values(**values, version=expected_version + 1, updated_at=now)
            .returning(Employment)
        )
        return (await session.execute(stmt)).scalar_one_or_none()


class EmployeeAssignmentRepository:
    """E-04 — mirrors `EmploymentRepository`'s shape. No general `update_assignment(values=...)`
    method exists — only `effective_to` is ever written after insert (ADR-0003: "never an edit
    of an existing one's core values"), enforced by `close_assignment` being the only mutation
    path."""

    async def insert_assignment(
        self, session: AsyncSession, *, data: dict[str, Any]
    ) -> EmployeeAssignment:
        row = EmployeeAssignment(**data)
        session.add(row)
        await session.flush()
        return row

    async def get_current_assignment(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID
    ) -> EmployeeAssignment | None:
        stmt = select(EmployeeAssignment).where(
            EmployeeAssignment.company_id == company_id,
            EmployeeAssignment.employee_id == employee_id,
            EmployeeAssignment.deleted_at.is_(None),
            EmployeeAssignment.effective_to.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def get_assignment_as_of(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID, as_of: date
    ) -> EmployeeAssignment | None:
        """The assignment row (at most one, by `employee_assignment_no_overlap`) covering
        `as_of` — the shared cross-module contract other modules (Attendance/Leave/Payroll)
        will later call via `employee.service`
        (`docs/modules/employee/05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part B7/E)."""
        stmt = select(EmployeeAssignment).where(
            EmployeeAssignment.company_id == company_id,
            EmployeeAssignment.employee_id == employee_id,
            EmployeeAssignment.deleted_at.is_(None),
            EmployeeAssignment.effective_from <= as_of,
            or_(
                EmployeeAssignment.effective_to.is_(None),
                EmployeeAssignment.effective_to >= as_of,
            ),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def list_assignments(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID
    ) -> list[EmployeeAssignment]:
        stmt = (
            select(EmployeeAssignment)
            .where(
                EmployeeAssignment.company_id == company_id,
                EmployeeAssignment.employee_id == employee_id,
                EmployeeAssignment.deleted_at.is_(None),
            )
            .order_by(EmployeeAssignment.effective_from)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def get_assignment(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        employee_id: UUID,
        assignment_id: UUID,
    ) -> EmployeeAssignment | None:
        stmt = select(EmployeeAssignment).where(
            EmployeeAssignment.id == assignment_id,
            EmployeeAssignment.employee_id == employee_id,
            EmployeeAssignment.company_id == company_id,
            EmployeeAssignment.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def close_assignment(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        employee_id: UUID,
        assignment_id: UUID,
        effective_to: date,
        expected_version: int,
        now: datetime,
    ) -> EmployeeAssignment | None:
        """The one allowed edit to an existing assignment row — closes it by setting
        `effective_to`, never touching a business column. `None` means either a stale
        `version` (the caller re-fetches to distinguish stale-vs-not-found) or the row no
        longer matches, mirroring `EmploymentRepository.update_employment`'s own contract."""
        stmt = (
            update(EmployeeAssignment)
            .where(
                EmployeeAssignment.id == assignment_id,
                EmployeeAssignment.employee_id == employee_id,
                EmployeeAssignment.company_id == company_id,
                EmployeeAssignment.version == expected_version,
                EmployeeAssignment.deleted_at.is_(None),
            )
            .values(effective_to=effective_to, version=expected_version + 1, updated_at=now)
            .returning(EmployeeAssignment)
        )
        return (await session.execute(stmt)).scalar_one_or_none()


class EmployeeCompensationRepository:
    """E-06 — mirrors `EmployeeAssignmentRepository`'s shape exactly. No general
    `update_compensation(values=...)` method exists — only `effective_to` is ever written after
    insert, enforced by `close_compensation` being the only mutation path
    (`docs/modules/employee/17_EMPLOYEE_COMPENSATION_IMPLEMENTATION_PLAN.md` §6)."""

    async def insert_compensation(
        self, session: AsyncSession, *, data: dict[str, Any]
    ) -> EmployeeCompensation:
        row = EmployeeCompensation(**data)
        session.add(row)
        await session.flush()
        return row

    async def get_current_compensation(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID
    ) -> EmployeeCompensation | None:
        stmt = select(EmployeeCompensation).where(
            EmployeeCompensation.company_id == company_id,
            EmployeeCompensation.employee_id == employee_id,
            EmployeeCompensation.deleted_at.is_(None),
            EmployeeCompensation.effective_to.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def get_compensation_as_of(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID, as_of: date
    ) -> EmployeeCompensation | None:
        """The compensation row (at most one, by `employee_compensation_no_overlap`) covering
        `as_of` — the shared cross-module contract other modules (Payroll) will later call via
        `employee.service` (`05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part B7/F)."""
        stmt = select(EmployeeCompensation).where(
            EmployeeCompensation.company_id == company_id,
            EmployeeCompensation.employee_id == employee_id,
            EmployeeCompensation.deleted_at.is_(None),
            EmployeeCompensation.effective_from <= as_of,
            or_(
                EmployeeCompensation.effective_to.is_(None),
                EmployeeCompensation.effective_to >= as_of,
            ),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def list_compensations(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID
    ) -> list[EmployeeCompensation]:
        stmt = (
            select(EmployeeCompensation)
            .where(
                EmployeeCompensation.company_id == company_id,
                EmployeeCompensation.employee_id == employee_id,
                EmployeeCompensation.deleted_at.is_(None),
            )
            .order_by(EmployeeCompensation.effective_from)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def get_compensation(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        employee_id: UUID,
        compensation_id: UUID,
    ) -> EmployeeCompensation | None:
        stmt = select(EmployeeCompensation).where(
            EmployeeCompensation.id == compensation_id,
            EmployeeCompensation.employee_id == employee_id,
            EmployeeCompensation.company_id == company_id,
            EmployeeCompensation.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def close_compensation(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        employee_id: UUID,
        compensation_id: UUID,
        effective_to: date,
        expected_version: int,
        now: datetime,
    ) -> EmployeeCompensation | None:
        """The one allowed edit to an existing compensation row — closes it by setting
        `effective_to`, never touching a business column. `None` means either a stale `version`
        (the caller re-fetches to distinguish stale-vs-not-found) or the row no longer matches,
        mirroring `EmployeeAssignmentRepository.close_assignment`'s own contract."""
        stmt = (
            update(EmployeeCompensation)
            .where(
                EmployeeCompensation.id == compensation_id,
                EmployeeCompensation.employee_id == employee_id,
                EmployeeCompensation.company_id == company_id,
                EmployeeCompensation.version == expected_version,
                EmployeeCompensation.deleted_at.is_(None),
            )
            .values(effective_to=effective_to, version=expected_version + 1, updated_at=now)
            .returning(EmployeeCompensation)
        )
        return (await session.execute(stmt)).scalar_one_or_none()
