"""Pure-query repository for the employee module — no business rules (Module Standard §2),
mirroring `organisation/repository.py`'s own convention exactly."""

from collections.abc import Sequence
from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, literal, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from hrms.core.db.models.identity import UserCompany
from hrms.modules.employee.models import (
    Employee,
    EmployeeAssignment,
    EmployeeBank,
    EmployeeCompensation,
    EmployeeDependent,
    EmployeeDocument,
    EmployeeEducation,
    EmployeeExperience,
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
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Employee]:
        """`visible_employee_ids=None` means `COMPANY` scope (or the caller didn't resolve a
        scope at all, e.g. non-data-scoped routes still calling this unchanged) — no extra
        predicate, identical to this method's pre-data-scope behavior. A non-`None` (possibly
        empty) set narrows the result to exactly those IDs — applied at the SQL layer, not as an
        in-Python filter, so it composes correctly with pagination
        (`docs/modules/employee/25_EMPLOYEE_RBAC_DATA_SCOPE_IMPLEMENTATION_PLAN.md` §15).

        `limit=None` (the default) returns every visible row unpaginated — preserves the exact
        pre-API-01 behavior for internal callers that still want the full set (e.g.
        `attendance/tasks.py`'s background job). `GET /employees` (API-01) always passes an
        explicit `limit`/`offset`, applied at the SQL layer via `LIMIT`/`OFFSET`, never by
        slicing a fully-materialized Python list."""
        conditions = [Employee.company_id == company_id, Employee.deleted_at.is_(None)]
        if visible_employee_ids is not None:
            conditions.append(Employee.id.in_(visible_employee_ids))
        # `id` is a stable secondary key — `created_at` alone can tie for rows inserted in the
        # same transaction/batch import, which would make page boundaries non-deterministic.
        stmt = select(Employee).where(*conditions).order_by(Employee.created_at, Employee.id)
        if limit is not None:
            stmt = stmt.limit(limit).offset(offset)
        return list((await session.execute(stmt)).scalars().all())

    async def count_employees(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        visible_employee_ids: frozenset[UUID] | None = None,
    ) -> int:
        """Same predicates as `list_employees`, no `ORDER BY`/`LIMIT` — the paired COUNT query
        for `GET /employees`'s `pagination.total` (API-01)."""
        conditions = [Employee.company_id == company_id, Employee.deleted_at.is_(None)]
        if visible_employee_ids is not None:
            conditions.append(Employee.id.in_(visible_employee_ids))
        stmt = select(func.count()).select_from(Employee).where(*conditions)
        return int((await session.execute(stmt)).scalar_one())

    async def lock_company_seats(self, session: AsyncSession, *, company_id: UUID) -> None:
        """Serialises every seat-consuming write (create, reactivate) for one company until the
        surrounding transaction ends. Without it, N parallel requests all read the same
        `count_active_employees` before any inserts, and each concludes there is room."""
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"employee-seats:{company_id}"},
        )

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

    async def get_employee_by_user_id(
        self, session: AsyncSession, *, company_id: UUID, user_id: UUID
    ) -> Employee | None:
        """Resolves the `Employee` a logged-in `User` is linked to, within one company —
        `Employee.user_id` has no DB-level uniqueness constraint, so this orders by
        `created_at` and takes the earliest match to stay deterministic if more than one row
        was ever mistakenly linked."""
        stmt = (
            select(Employee)
            .where(
                Employee.company_id == company_id,
                Employee.user_id == user_id,
                Employee.deleted_at.is_(None),
            )
            .order_by(Employee.created_at)
            .limit(1)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def link_user(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID, user_id: UUID
    ) -> None:
        """Sets `Employee.user_id` — the one write path for a column that has existed since the
        original schema but had no writer anywhere (`docs/modules/employee/
        41_EMPLOYEE_ACCOUNT_PROVISIONING_LOGIN_AUDIT_AND_PLAN.md` F1). Called once, from
        `AccountInviteService.accept` at invite-acceptance time — never re-linked afterward."""
        await session.execute(
            update(Employee)
            .where(Employee.id == employee_id, Employee.company_id == company_id)
            .values(user_id=user_id)
        )

    async def get_by_code_or_email(
        self, session: AsyncSession, *, company_id: UUID, value: str
    ) -> Employee | None:
        """Resolves a single employee by exact `employee_code` match, falling back to
        `personal_email` (case-insensitive) — built for `modules/employee_import`'s
        `reporting_manager` column, which accepts either. `employee_code` is unique per
        company; `personal_email` is not (no DB constraint, per `models.py`), so an ambiguous
        email match takes the earliest-created row, same determinism convention as
        `get_employee_by_user_id`."""
        stmt = (
            select(Employee)
            .where(
                Employee.company_id == company_id,
                Employee.deleted_at.is_(None),
                or_(
                    Employee.employee_code == value,
                    func.lower(Employee.personal_email) == value.lower(),
                ),
            )
            .order_by(Employee.created_at)
            .limit(1)
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

    async def list_spans_overlapping(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        date_from: date | None,
        date_to: date | None,
        employee_id: UUID | None = None,
    ) -> list[Employment]:
        """Every employment spell that overlaps `[date_from, date_to]` at all — i.e.
        `joining_date <= date_to AND (last_working_day IS NULL OR last_working_day >=
        date_from)`. Consumed by Attendance's period-finalization "employees without
        calculated attendance" check (W8) via `EmploymentService.list_spans_overlapping`, never
        by a direct model import (Module Standard §2 — cross-module callers use `.service`
        only). A `None` bound leaves that side of the range open."""
        conditions = [Employment.company_id == company_id, Employment.deleted_at.is_(None)]
        if date_to is not None:
            conditions.append(Employment.joining_date <= date_to)
        if date_from is not None:
            conditions.append(
                or_(Employment.last_working_day.is_(None), Employment.last_working_day >= date_from)
            )
        if employee_id is not None:
            conditions.append(Employment.employee_id == employee_id)
        stmt = select(Employment).where(*conditions)
        return list((await session.execute(stmt)).scalars().all())

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

    async def list_latest_employments(
        self, session: AsyncSession, *, company_id: UUID, employee_ids: Sequence[UUID]
    ) -> dict[UUID, Employment]:
        """Bulk form of `get_latest_employment` — one row per `employee_id` in `employee_ids`
        (the spell with the latest `joining_date`; ties broken by `id`), in a single query.
        Because `employment_no_overlap` guarantees spells for one employee never overlap, the
        latest-starting spell is the only one that could possibly cover "today" or any later
        date — an older spell necessarily ended (or was superseded) before this one began.

        Added for F-1 remediation (`docs/audits/ATTENDANCE_DASHBOARD_F1_REMEDIATION_REPORT.md`):
        `EmployeeService.list_employees` uses this to enrich `GET /employees`'s bulk response
        with employment boundaries, so a caller (the Attendance dashboard) can tell "currently
        employed, just hasn't punched in yet" from "no longer employed" without an N+1 fetch of
        `GET /employees/{id}/employments` per employee. Employees with no employment row at all
        (e.g. still `PRE_JOINING`) are simply absent from the returned mapping."""
        if not employee_ids:
            return {}
        stmt = (
            select(Employment)
            .distinct(Employment.employee_id)
            .where(
                Employment.company_id == company_id,
                Employment.employee_id.in_(employee_ids),
                Employment.deleted_at.is_(None),
            )
            .order_by(Employment.employee_id, Employment.joining_date.desc(), Employment.id.desc())
        )
        rows = (await session.execute(stmt)).scalars().all()
        return {row.employee_id: row for row in rows}

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

    async def get_latest_terminated_employment(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID
    ) -> Employment | None:
        stmt = (
            select(Employment)
            .where(
                Employment.company_id == company_id,
                Employment.employee_id == employee_id,
                Employment.status == "TERMINATED",
                Employment.deleted_at.is_(None),
            )
            .order_by(Employment.last_working_day.desc())
            .limit(1)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def list_elapsed_termination_logins(
        self, session: AsyncSession, *, company_id: UUID, as_of: date
    ) -> list[tuple[UUID, UUID]]:
        """`(employee_id, user_id)` for every employee whose last working day is strictly before
        `as_of`, who has no later `ACTIVE` employment (a rehire keeps their login), and whose
        linked login still has an `ACTIVE` membership of this company. Already-revoked accounts
        are excluded, which is what makes the sweep idempotent."""
        later = aliased(Employment)
        active_again = (
            select(later.id)
            .where(
                later.company_id == company_id,
                later.employee_id == Employee.id,
                later.status == "ACTIVE",
                later.deleted_at.is_(None),
            )
            .exists()
        )
        stmt = (
            select(Employee.id, Employee.user_id)
            .join(Employment, Employment.employee_id == Employee.id)
            .join(
                UserCompany,
                (UserCompany.user_id == Employee.user_id)
                & (UserCompany.company_id == Employee.company_id),
            )
            .where(
                Employee.company_id == company_id,
                Employee.user_id.is_not(None),
                Employee.deleted_at.is_(None),
                Employment.company_id == company_id,
                Employment.status == "TERMINATED",
                Employment.deleted_at.is_(None),
                Employment.last_working_day < as_of,
                UserCompany.status == "ACTIVE",
                ~active_again,
            )
            .distinct()
        )
        return [(row[0], row[1]) for row in (await session.execute(stmt)).all()]


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

    async def list_distinct_employee_ids_for_branch(
        self, session: AsyncSession, *, company_id: UUID, branch_id: UUID
    ) -> list[UUID]:
        """`ED-12` (execution gate §12.4) — every employee who has EVER been assigned to this
        branch, not just the current roster. Consumed by the branch-scope timezone-change guard:
        an employee who has since transferred away still has historical `attendance_day` rows
        computed under the branch's old timezone, and a current-roster-only check would miss
        exactly the case this guard exists to catch. Includes closed (`effective_to` set) rows
        deliberately — history, not current state. Excludes soft-deleted rows only, since those
        were erased as a data-entry correction, not a genuine placement."""
        stmt = (
            select(EmployeeAssignment.employee_id)
            .where(
                EmployeeAssignment.company_id == company_id,
                EmployeeAssignment.branch_id == branch_id,
                EmployeeAssignment.deleted_at.is_(None),
            )
            .distinct()
        )
        return list((await session.execute(stmt)).scalars().all())

    async def count_active_employees_for_master(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        column: str,
        master_id: UUID,
        as_of: date,
    ) -> int:
        """Active employees whose open or still-running (`effective_to` null or `>= as_of`)
        assignment row references `master_id` through `column`. Closed historical rows never
        count — only a live dependency blocks deactivating the master record."""
        stmt = (
            select(func.count(func.distinct(EmployeeAssignment.employee_id)))
            .join(Employee, Employee.id == EmployeeAssignment.employee_id)
            .where(
                EmployeeAssignment.company_id == company_id,
                getattr(EmployeeAssignment, column) == master_id,
                EmployeeAssignment.deleted_at.is_(None),
                or_(
                    EmployeeAssignment.effective_to.is_(None),
                    EmployeeAssignment.effective_to >= as_of,
                ),
                Employee.is_active.is_(True),
                Employee.deleted_at.is_(None),
            )
        )
        return int((await session.execute(stmt)).scalar_one())

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

    @staticmethod
    def _direct_report_conditions(
        *,
        company_id: UUID,
        manager_employee_id: UUID,
        visible_employee_ids: frozenset[UUID] | None,
        include_inactive: bool,
    ) -> list[Any]:
        """Shared by the page query and its COUNT so `total` can never disagree with the rows.
        "Direct report" is exactly what `get_direct_report_ids` (the `REPORTEES` scope) means —
        the employee's *current* assignment row names this manager — narrowed by the caller's own
        visible set, so a page can only ever hold rows the caller could read individually."""
        conditions: list[Any] = [
            EmployeeAssignment.company_id == company_id,
            EmployeeAssignment.reporting_manager_id == manager_employee_id,
            EmployeeAssignment.deleted_at.is_(None),
            EmployeeAssignment.effective_to.is_(None),
            Employee.company_id == company_id,
            Employee.deleted_at.is_(None),
        ]
        if not include_inactive:
            conditions.append(Employee.is_active.is_(True))
        if visible_employee_ids is not None:
            conditions.append(Employee.id.in_(visible_employee_ids))
        return conditions

    async def list_direct_reports(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        manager_employee_id: UUID,
        visible_employee_ids: frozenset[UUID] | None,
        include_inactive: bool,
        limit: int,
        offset: int,
    ) -> list[tuple[Employee, EmployeeAssignment]]:
        """One page of the manager's direct reports with the assignment row that links them.
        `visible_employee_ids=None` is `COMPANY` scope. Deterministic order (`created_at`, `id`)
        so page boundaries are stable, same as `EmployeeRepository.list_employees`."""
        stmt = (
            select(Employee, EmployeeAssignment)
            .join(EmployeeAssignment, EmployeeAssignment.employee_id == Employee.id)
            .where(
                *self._direct_report_conditions(
                    company_id=company_id,
                    manager_employee_id=manager_employee_id,
                    visible_employee_ids=visible_employee_ids,
                    include_inactive=include_inactive,
                )
            )
            .order_by(Employee.created_at, Employee.id)
            .limit(limit)
            .offset(offset)
        )
        return [(row[0], row[1]) for row in (await session.execute(stmt)).all()]

    async def count_direct_reports(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        manager_employee_id: UUID,
        visible_employee_ids: frozenset[UUID] | None,
        include_inactive: bool,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(Employee)
            .join(EmployeeAssignment, EmployeeAssignment.employee_id == Employee.id)
            .where(
                *self._direct_report_conditions(
                    company_id=company_id,
                    manager_employee_id=manager_employee_id,
                    visible_employee_ids=visible_employee_ids,
                    include_inactive=include_inactive,
                )
            )
        )
        return int((await session.execute(stmt)).scalar_one())

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

    async def get_branch_colleague_ids(
        self, session: AsyncSession, *, company_id: UUID, branch_id: UUID
    ) -> set[UUID]:
        """`BRANCH` resolution — employees whose *current* assignment row (`effective_to IS
        NULL`) has `branch_id` equal to the caller's own current branch. Same "current row only,
        no `as_of` support yet" posture as `get_direct_report_ids`
        (`docs/architecture/RBAC_DATA_SCOPE_DECISIONS.md` Decision C, `BRANCH` extension).
        Deliberately does not exclude the caller themself — unlike `REPORTEES` (a manager is
        never their own report), a branch manager *is* a colleague of their own branch, and
        callers needing `SELF` excluded already compose it via a separate `SELF` grant/union in
        `EmployeeService.resolve_visible_employee_ids`, same pattern as `REPORTEES`+`SELF`."""
        stmt = select(EmployeeAssignment.employee_id).where(
            EmployeeAssignment.company_id == company_id,
            EmployeeAssignment.branch_id == branch_id,
            EmployeeAssignment.deleted_at.is_(None),
            EmployeeAssignment.effective_to.is_(None),
        )
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


class EmployeeExperienceRepository:
    """Previous employment / PF continuity (market-parity onboarding-data pass, part 4) —
    a plain one-to-many list, not effective-dated history: `insert_experience` never closes an
    existing row (there is no "current" row to close), and `delete_experience` is the only
    mutation path after insert, mirroring `close_statutory`'s optimistic-lock shape but as a
    soft-delete rather than a field update."""

    async def insert_experience(
        self, session: AsyncSession, *, data: dict[str, Any]
    ) -> EmployeeExperience:
        row = EmployeeExperience(**data)
        session.add(row)
        await session.flush()
        return row

    async def list_experiences(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID
    ) -> list[EmployeeExperience]:
        stmt = (
            select(EmployeeExperience)
            .where(
                EmployeeExperience.company_id == company_id,
                EmployeeExperience.employee_id == employee_id,
                EmployeeExperience.deleted_at.is_(None),
            )
            .order_by(EmployeeExperience.from_date)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def get_experience(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID, experience_id: UUID
    ) -> EmployeeExperience | None:
        stmt = select(EmployeeExperience).where(
            EmployeeExperience.id == experience_id,
            EmployeeExperience.company_id == company_id,
            EmployeeExperience.employee_id == employee_id,
            EmployeeExperience.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def delete_experience(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        employee_id: UUID,
        experience_id: UUID,
        expected_version: int,
        now: datetime,
    ) -> EmployeeExperience | None:
        stmt = (
            update(EmployeeExperience)
            .where(
                EmployeeExperience.id == experience_id,
                EmployeeExperience.company_id == company_id,
                EmployeeExperience.employee_id == employee_id,
                EmployeeExperience.version == expected_version,
                EmployeeExperience.deleted_at.is_(None),
            )
            .values(deleted_at=now, version=expected_version + 1, updated_at=now)
            .returning(EmployeeExperience)
        )
        return (await session.execute(stmt)).scalar_one_or_none()


class EmployeeEducationRepository:
    """Education history (market-parity onboarding-data pass, part 5) — mirrors
    `EmployeeExperienceRepository`'s exact shape (plain list, soft-delete only mutation path)."""

    async def insert_education(
        self, session: AsyncSession, *, data: dict[str, Any]
    ) -> EmployeeEducation:
        row = EmployeeEducation(**data)
        session.add(row)
        await session.flush()
        return row

    async def list_educations(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID
    ) -> list[EmployeeEducation]:
        stmt = (
            select(EmployeeEducation)
            .where(
                EmployeeEducation.company_id == company_id,
                EmployeeEducation.employee_id == employee_id,
                EmployeeEducation.deleted_at.is_(None),
            )
            .order_by(EmployeeEducation.year_of_passing)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def get_education(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID, education_id: UUID
    ) -> EmployeeEducation | None:
        stmt = select(EmployeeEducation).where(
            EmployeeEducation.id == education_id,
            EmployeeEducation.company_id == company_id,
            EmployeeEducation.employee_id == employee_id,
            EmployeeEducation.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def delete_education(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        employee_id: UUID,
        education_id: UUID,
        expected_version: int,
        now: datetime,
    ) -> EmployeeEducation | None:
        stmt = (
            update(EmployeeEducation)
            .where(
                EmployeeEducation.id == education_id,
                EmployeeEducation.company_id == company_id,
                EmployeeEducation.employee_id == employee_id,
                EmployeeEducation.version == expected_version,
                EmployeeEducation.deleted_at.is_(None),
            )
            .values(deleted_at=now, version=expected_version + 1, updated_at=now)
            .returning(EmployeeEducation)
        )
        return (await session.execute(stmt)).scalar_one_or_none()


class EmployeeDependentRepository:
    """PF/Gratuity nominee declaration + ESI family details (market-parity onboarding-data pass,
    part 6) — mirrors `EmployeeEducationRepository`'s exact shape (plain list, soft-delete only
    mutation path after insert), plus `sum_pf_nominee_percentage`/`sum_gratuity_nominee_percentage`
    for `EmployeeDependentService`'s cross-row percentage validator (a DB `CHECK` cannot aggregate
    across sibling rows, so the service queries this sum itself before inserting)."""

    async def insert_dependent(
        self, session: AsyncSession, *, data: dict[str, Any]
    ) -> EmployeeDependent:
        row = EmployeeDependent(**data)
        session.add(row)
        await session.flush()
        return row

    async def list_dependents(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID
    ) -> list[EmployeeDependent]:
        stmt = (
            select(EmployeeDependent)
            .where(
                EmployeeDependent.company_id == company_id,
                EmployeeDependent.employee_id == employee_id,
                EmployeeDependent.deleted_at.is_(None),
            )
            .order_by(EmployeeDependent.created_at)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def get_dependent(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID, dependent_id: UUID
    ) -> EmployeeDependent | None:
        stmt = select(EmployeeDependent).where(
            EmployeeDependent.id == dependent_id,
            EmployeeDependent.company_id == company_id,
            EmployeeDependent.employee_id == employee_id,
            EmployeeDependent.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def delete_dependent(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        employee_id: UUID,
        dependent_id: UUID,
        expected_version: int,
        now: datetime,
    ) -> EmployeeDependent | None:
        stmt = (
            update(EmployeeDependent)
            .where(
                EmployeeDependent.id == dependent_id,
                EmployeeDependent.company_id == company_id,
                EmployeeDependent.employee_id == employee_id,
                EmployeeDependent.version == expected_version,
                EmployeeDependent.deleted_at.is_(None),
            )
            .values(deleted_at=now, version=expected_version + 1, updated_at=now)
            .returning(EmployeeDependent)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def sum_pf_nominee_percentage(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID
    ) -> float:
        stmt = select(
            func.coalesce(func.sum(EmployeeDependent.pf_nominee_share_percentage), 0)
        ).where(
            EmployeeDependent.company_id == company_id,
            EmployeeDependent.employee_id == employee_id,
            EmployeeDependent.is_pf_nominee.is_(True),
            EmployeeDependent.deleted_at.is_(None),
        )
        total = (await session.execute(stmt)).scalar_one()
        return float(total) if total is not None else 0.0

    async def sum_gratuity_nominee_percentage(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID
    ) -> float:
        stmt = select(
            func.coalesce(func.sum(EmployeeDependent.gratuity_nominee_share_percentage), 0)
        ).where(
            EmployeeDependent.company_id == company_id,
            EmployeeDependent.employee_id == employee_id,
            EmployeeDependent.is_gratuity_nominee.is_(True),
            EmployeeDependent.deleted_at.is_(None),
        )
        total = (await session.execute(stmt)).scalar_one()
        return float(total) if total is not None else 0.0


class EmployeeDocumentRepository:
    """Mirrors `OnboardingDocumentRepository` (`hrms.modules.onboarding.repository`) — hard
    delete, no soft-delete/no `version` column, ordered-by-`uploaded_at` listing."""

    async def insert_document(
        self, session: AsyncSession, *, data: dict[str, Any]
    ) -> EmployeeDocument:
        row = EmployeeDocument(**data)
        session.add(row)
        await session.flush()
        return row

    async def get_document(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID, document_id: UUID
    ) -> EmployeeDocument | None:
        stmt = select(EmployeeDocument).where(
            EmployeeDocument.id == document_id,
            EmployeeDocument.employee_id == employee_id,
            EmployeeDocument.company_id == company_id,
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def list_documents(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID
    ) -> list[EmployeeDocument]:
        stmt = (
            select(EmployeeDocument)
            .where(
                EmployeeDocument.company_id == company_id,
                EmployeeDocument.employee_id == employee_id,
            )
            .order_by(EmployeeDocument.uploaded_at)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def delete_document(self, session: AsyncSession, *, document: EmployeeDocument) -> None:
        await session.delete(document)
        await session.flush()

    async def update_review(
        self,
        session: AsyncSession,
        *,
        document: EmployeeDocument,
        status: str,
        rejection_reason: str | None,
        verified_by_user_id: UUID | None,
        now: datetime,
    ) -> EmployeeDocument:
        document.status = status
        document.rejection_reason = rejection_reason
        document.verified_by_user_id = verified_by_user_id
        document.verified_at = now
        document.updated_at = now
        await session.flush()
        return document
