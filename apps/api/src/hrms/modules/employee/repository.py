"""Pure-query repository for the employee module — no business rules (Module Standard §2),
mirroring `organisation/repository.py`'s own convention exactly."""

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, literal, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from hrms.modules.employee.models import (
    Employee,
    EmployeeAssignment,
    EmployeeBank,
    EmployeeCompensation,
    EmployeeStatutory,
    Employment,
)

#: `REPORTEE_TREE` recursion depth cap — `docs/product/19_RBAC_and_Permission_Matrix.md §5`'s
#: reference implementation; bounds query cost against a malformed/cyclic hierarchy (no
#: write-time cycle guard exists yet, `docs/modules/employee/
#: 25_EMPLOYEE_RBAC_DATA_SCOPE_IMPLEMENTATION_PLAN.md` §17), does not detect or reject one.
REPORTEE_TREE_MAX_DEPTH = 20


class EmployeeRepository:
    async def insert_employee(self, session: AsyncSession, *, data: dict[str, Any]) -> Employee:
        row = Employee(**data)
        session.add(row)
        await session.flush()
        return row

    async def list_employees(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        visible_employee_ids: frozenset[UUID] | None = None,
    ) -> list[Employee]:
        """`visible_employee_ids=None` means `COMPANY` scope (or the caller didn't resolve a
        scope at all, e.g. non-data-scoped routes still calling this unchanged) — no extra
        predicate, identical to this method's pre-data-scope behavior. A non-`None` (possibly
        empty) set narrows the result to exactly those IDs — applied at the SQL layer, not as an
        in-Python filter, so it composes correctly once pagination exists
        (`docs/modules/employee/25_EMPLOYEE_RBAC_DATA_SCOPE_IMPLEMENTATION_PLAN.md` §15)."""
        conditions = [Employee.company_id == company_id, Employee.deleted_at.is_(None)]
        if visible_employee_ids is not None:
            conditions.append(Employee.id.in_(visible_employee_ids))
        stmt = select(Employee).where(*conditions).order_by(Employee.created_at)
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
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        employee_id: UUID,
        visible_employee_ids: frozenset[UUID] | None = None,
    ) -> Employee | None:
        # `company_id` filtered explicitly, not just relied on via RLS — same
        # belt-and-suspenders convention as `OrganisationRepository.get_grade`.
        #
        # `visible_employee_ids` (data-scope, `None` = `COMPANY`/unscoped) is applied in this
        # same query, not as a fetch-then-check — an out-of-scope target produces the identical
        # "no row" result a cross-tenant or nonexistent ID already produces, which the service
        # layer already turns into `404` with zero new branching
        # (`docs/modules/employee/25_EMPLOYEE_RBAC_DATA_SCOPE_IMPLEMENTATION_PLAN.md` §15).
        conditions = [
            Employee.id == employee_id,
            Employee.company_id == company_id,
            Employee.deleted_at.is_(None),
        ]
        if visible_employee_ids is not None:
            conditions.append(Employee.id.in_(visible_employee_ids))
        stmt = select(Employee).where(*conditions)
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

    async def get_direct_report_ids(
        self, session: AsyncSession, *, company_id: UUID, manager_employee_id: UUID
    ) -> set[UUID]:
        """`REPORTEES` resolution — employees whose *current* assignment row
        (`effective_to IS NULL`) reports to `manager_employee_id`. One level only; a report's own
        reports are not included (`docs/architecture/RBAC_DATA_SCOPE_DECISIONS.md` Decision D).
        Does not include `manager_employee_id` itself — `REPORTEES` never implies `SELF`
        (`25_EMPLOYEE_RBAC_DATA_SCOPE_IMPLEMENTATION_PLAN.md` §5)."""
        stmt = select(EmployeeAssignment.employee_id).where(
            EmployeeAssignment.company_id == company_id,
            EmployeeAssignment.reporting_manager_id == manager_employee_id,
            EmployeeAssignment.deleted_at.is_(None),
            EmployeeAssignment.effective_to.is_(None),
        )
        return set((await session.execute(stmt)).scalars().all())

    async def get_reportee_tree_ids(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        manager_employee_id: UUID,
        max_depth: int = REPORTEE_TREE_MAX_DEPTH,
    ) -> set[UUID]:
        """`REPORTEE_TREE` resolution — the transitive closure of `get_direct_report_ids`,
        walking `reporting_manager_id` outward via a recursive CTE, depth-capped at `max_depth`
        (reference shape: `docs/product/19_RBAC_and_Permission_Matrix.md §5`). The cap bounds
        query cost against a cyclic/malformed hierarchy; it does not detect or reject one — a
        cycle is silently truncated at `max_depth`, not rejected
        (`docs/architecture/RBAC_DATA_SCOPE_DECISIONS.md` Decision D; no write-time cycle guard
        exists yet, tracked as a known limitation). Every level is additionally filtered by
        `company_id` and "current" (`effective_to IS NULL`), matching `get_direct_report_ids`.
        Does not include `manager_employee_id` itself, same as `get_direct_report_ids`."""
        base = select(
            EmployeeAssignment.employee_id.label("employee_id"),
            literal(1).label("depth"),
        ).where(
            EmployeeAssignment.company_id == company_id,
            EmployeeAssignment.reporting_manager_id == manager_employee_id,
            EmployeeAssignment.deleted_at.is_(None),
            EmployeeAssignment.effective_to.is_(None),
        )
        tree = base.cte(name="reportee_tree", recursive=True)
        child = aliased(EmployeeAssignment, name="ea_child")
        recursive_step = select(
            child.employee_id.label("employee_id"),
            (tree.c.depth + 1).label("depth"),
        ).where(
            child.company_id == company_id,
            child.reporting_manager_id == tree.c.employee_id,
            child.deleted_at.is_(None),
            child.effective_to.is_(None),
            tree.c.depth < max_depth,
        )
        tree = tree.union_all(recursive_step)
        stmt = select(tree.c.employee_id).distinct()
        return set((await session.execute(stmt)).scalars().all())

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


class EmployeeStatutoryRepository:
    """E-07 — mirrors `EmployeeCompensationRepository`'s shape exactly. No general
    `update_statutory(values=...)` method exists — only `effective_to` is ever written after
    insert, enforced by `close_statutory` being the only mutation path
    (`docs/modules/employee/29_EMPLOYEE_STATUTORY_IMPLEMENTATION_PLAN.md` §20)."""

    async def insert_statutory(
        self, session: AsyncSession, *, data: dict[str, Any]
    ) -> EmployeeStatutory:
        row = EmployeeStatutory(**data)
        session.add(row)
        await session.flush()
        return row

    async def get_current_statutory(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID
    ) -> EmployeeStatutory | None:
        stmt = select(EmployeeStatutory).where(
            EmployeeStatutory.company_id == company_id,
            EmployeeStatutory.employee_id == employee_id,
            EmployeeStatutory.deleted_at.is_(None),
            EmployeeStatutory.effective_to.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def get_statutory_as_of(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID, as_of: date
    ) -> EmployeeStatutory | None:
        """The statutory row (at most one, by `employee_statutory_no_overlap`) covering
        `as_of` — the cross-module contract Payroll will call at pay-run snapshot time (plan
        §13), mirroring `EmployeeCompensationRepository.get_compensation_as_of`'s exact
        contract."""
        stmt = select(EmployeeStatutory).where(
            EmployeeStatutory.company_id == company_id,
            EmployeeStatutory.employee_id == employee_id,
            EmployeeStatutory.deleted_at.is_(None),
            EmployeeStatutory.effective_from <= as_of,
            or_(
                EmployeeStatutory.effective_to.is_(None),
                EmployeeStatutory.effective_to >= as_of,
            ),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def list_statutories(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID
    ) -> list[EmployeeStatutory]:
        stmt = (
            select(EmployeeStatutory)
            .where(
                EmployeeStatutory.company_id == company_id,
                EmployeeStatutory.employee_id == employee_id,
                EmployeeStatutory.deleted_at.is_(None),
            )
            .order_by(EmployeeStatutory.effective_from)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def get_statutory(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        employee_id: UUID,
        statutory_id: UUID,
    ) -> EmployeeStatutory | None:
        stmt = select(EmployeeStatutory).where(
            EmployeeStatutory.id == statutory_id,
            EmployeeStatutory.employee_id == employee_id,
            EmployeeStatutory.company_id == company_id,
            EmployeeStatutory.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def close_statutory(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        employee_id: UUID,
        statutory_id: UUID,
        effective_to: date,
        expected_version: int,
        now: datetime,
    ) -> EmployeeStatutory | None:
        """The one allowed edit to an existing statutory row — closes it by setting
        `effective_to`, never touching a business column. `None` means either a stale `version`
        (the caller re-fetches to distinguish stale-vs-not-found) or the row no longer matches,
        mirroring `EmployeeCompensationRepository.close_compensation`'s exact contract."""
        stmt = (
            update(EmployeeStatutory)
            .where(
                EmployeeStatutory.id == statutory_id,
                EmployeeStatutory.employee_id == employee_id,
                EmployeeStatutory.company_id == company_id,
                EmployeeStatutory.version == expected_version,
                EmployeeStatutory.deleted_at.is_(None),
            )
            .values(effective_to=effective_to, version=expected_version + 1, updated_at=now)
            .returning(EmployeeStatutory)
        )
        return (await session.execute(stmt)).scalar_one_or_none()


class EmployeeBankRepository:
    """E-08 — mirrors `EmployeeStatutoryRepository`'s shape exactly. No general
    `update_bank(values=...)` method exists — only `effective_to` is ever written after insert,
    enforced by `close_bank` being the only mutation path
    (`docs/modules/employee/33_EMPLOYEE_BANKING_IMPLEMENTATION_PLAN.md` §19). Unlike
    `EmployeeStatutoryRepository`, `close_bank` is never called from
    `EmploymentService.terminate_employment` — the current bank row survives exit (plan §7)."""

    async def insert_bank(self, session: AsyncSession, *, data: dict[str, Any]) -> EmployeeBank:
        row = EmployeeBank(**data)
        session.add(row)
        await session.flush()
        return row

    async def get_current_bank(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID
    ) -> EmployeeBank | None:
        stmt = select(EmployeeBank).where(
            EmployeeBank.company_id == company_id,
            EmployeeBank.employee_id == employee_id,
            EmployeeBank.deleted_at.is_(None),
            EmployeeBank.effective_to.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def get_bank_as_of(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID, as_of: date
    ) -> EmployeeBank | None:
        """The bank row (at most one, by `employee_bank_no_overlap`) covering `as_of` — the
        cross-module contract Payroll will call at bank-advice-generation time (plan §11),
        mirroring `EmployeeStatutoryRepository.get_statutory_as_of`'s exact contract."""
        stmt = select(EmployeeBank).where(
            EmployeeBank.company_id == company_id,
            EmployeeBank.employee_id == employee_id,
            EmployeeBank.deleted_at.is_(None),
            EmployeeBank.effective_from <= as_of,
            or_(
                EmployeeBank.effective_to.is_(None),
                EmployeeBank.effective_to >= as_of,
            ),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def list_banks(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID
    ) -> list[EmployeeBank]:
        stmt = (
            select(EmployeeBank)
            .where(
                EmployeeBank.company_id == company_id,
                EmployeeBank.employee_id == employee_id,
                EmployeeBank.deleted_at.is_(None),
            )
            .order_by(EmployeeBank.effective_from)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def get_bank(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        employee_id: UUID,
        bank_id: UUID,
    ) -> EmployeeBank | None:
        stmt = select(EmployeeBank).where(
            EmployeeBank.id == bank_id,
            EmployeeBank.employee_id == employee_id,
            EmployeeBank.company_id == company_id,
            EmployeeBank.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def close_bank(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        employee_id: UUID,
        bank_id: UUID,
        effective_to: date,
        expected_version: int,
        now: datetime,
    ) -> EmployeeBank | None:
        """The one allowed edit to an existing bank row — closes it by setting `effective_to`,
        never touching a business column. `None` means either a stale `version` (the caller
        re-fetches to distinguish stale-vs-not-found) or the row no longer matches, mirroring
        `EmployeeStatutoryRepository.close_statutory`'s exact contract. Called only from
        `EmployeeBankService.create_bank`'s own close-then-insert revision path — never from
        `EmploymentService.terminate_employment` (plan §7)."""
        stmt = (
            update(EmployeeBank)
            .where(
                EmployeeBank.id == bank_id,
                EmployeeBank.employee_id == employee_id,
                EmployeeBank.company_id == company_id,
                EmployeeBank.version == expected_version,
                EmployeeBank.deleted_at.is_(None),
            )
            .values(effective_to=effective_to, version=expected_version + 1, updated_at=now)
            .returning(EmployeeBank)
        )
        return (await session.execute(stmt)).scalar_one_or_none()
