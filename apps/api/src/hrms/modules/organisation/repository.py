"""SQLAlchemy queries for the organisation module — no business rules."""

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, delete, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.db.models.identity import (
    Company,
    Permission,
    Role,
    RolePermission,
    User,
    UserCompany,
    UserRole,
)
from hrms.modules.organisation.models import (
    Branch,
    CalendarException,
    CompanyFeatureFlag,
    CompanySetupProgress,
    Department,
    Designation,
    Grade,
    Holiday,
    HolidayCalendar,
    LegalEntity,
    Plan,
    PlanFeature,
    PolicyAssignment,
    Shift,
    ShiftBreak,
    ShiftDutyBlock,
    ShiftVersion,
    Subscription,
    WeeklyOffPattern,
    WeeklyOffRule,
    WorkCalendar,
    WorkCalendarHolidayCalendar,
)

_TERMINAL_SUBSCRIPTION_STATUSES = ("CANCELED", "EXPIRED")


class OrganisationRepository:
    async def insert_user(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        email: str,
        password_hash: str,
        first_name: str,
        last_name: str,
        now: datetime,
    ) -> User:
        row = User(
            id=user_id,
            email=email,
            password_hash=password_hash,
            first_name=first_name,
            last_name=last_name,
            status="ACTIVE",
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        await session.flush()
        return row

    async def insert_company(self, session: AsyncSession, *, data: dict[str, Any]) -> Company:
        row = Company(**data)
        session.add(row)
        await session.flush()
        return row

    async def insert_user_company(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        company_id: UUID,
        is_primary: bool,
        now: datetime,
    ) -> UserCompany:
        row = UserCompany(
            id=uuid4(),
            user_id=user_id,
            company_id=company_id,
            is_primary=is_primary,
            status="ACTIVE",
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        await session.flush()
        return row

    async def get_or_create_permission(
        self,
        session: AsyncSession,
        *,
        code: str,
        domain: str,
        description: str,
    ) -> Permission:
        row = (
            await session.execute(select(Permission).where(Permission.code == code))
        ).scalar_one_or_none()
        if row is not None:
            return row
        row = Permission(id=uuid4(), code=code, domain=domain, description=description)
        session.add(row)
        await session.flush()
        return row

    async def insert_role(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        code: str,
        name: str,
        is_system: bool,
        now: datetime,
    ) -> Role:
        row = Role(
            id=uuid4(),
            company_id=company_id,
            code=code,
            name=name,
            is_system=is_system,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        await session.flush()
        return row

    async def insert_role_permission(
        self, session: AsyncSession, *, role_id: UUID, permission_id: UUID
    ) -> None:
        session.add(RolePermission(role_id=role_id, permission_id=permission_id))
        await session.flush()

    async def insert_user_role(
        self, session: AsyncSession, *, user_company_id: UUID, role_id: UUID
    ) -> None:
        session.add(UserRole(id=uuid4(), user_company_id=user_company_id, role_id=role_id))
        await session.flush()

    async def insert_setup_progress(
        self, session: AsyncSession, *, company_id: UUID, now: datetime
    ) -> CompanySetupProgress:
        row = CompanySetupProgress(
            id=uuid4(),
            company_id=company_id,
            status="IN_PROGRESS",
            started_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        await session.flush()
        return row

    async def get_plan_by_code(self, session: AsyncSession, *, code: str) -> Plan | None:
        stmt = select(Plan).where(Plan.code == code, Plan.is_active.is_(True))
        return (await session.execute(stmt)).scalar_one_or_none()

    async def insert_subscription(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        plan_id: UUID,
        status: str,
        trial_ends_at: datetime | None,
        now: datetime,
    ) -> Subscription:
        row = Subscription(
            id=uuid4(),
            company_id=company_id,
            plan_id=plan_id,
            status=status,
            trial_ends_at=trial_ends_at,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        await session.flush()
        return row

    async def get_company(self, session: AsyncSession, *, company_id: UUID) -> Company | None:
        stmt = select(Company).where(Company.id == company_id, Company.deleted_at.is_(None))
        return (await session.execute(stmt)).scalar_one_or_none()

    async def update_company(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        values: dict[str, Any],
        expected_version: int,
        updated_by: UUID | None,
        now: datetime,
    ) -> Company | None:
        stmt = (
            update(Company)
            .where(
                Company.id == company_id,
                Company.version == expected_version,
                Company.deleted_at.is_(None),
            )
            .values(
                **values,
                version=expected_version + 1,
                updated_at=now,
                updated_by=updated_by,
            )
            .returning(Company)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def company_profile_is_complete(self, session: AsyncSession, *, company_id: UUID) -> bool:
        """Real, derived predicate — never a stored flag (Domain Model §2.2).

        Checks the same fields the domain's own validation rules (§5) require a Company
        to hold: a non-empty name, a valid currency/timezone, an in-range fiscal year
        start month, and at least one working day. Every successfully registered company
        satisfies this immediately (registration always sets valid defaults), which is why
        the API design documents this step as "implicitly complete once registration
        finishes" — but the predicate still reflects real row state, not a hardcoded True.
        """
        company = await self.get_company(session, company_id=company_id)
        if company is None:
            return False
        has_working_day = any(
            bool(entry.get("is_working")) for entry in company.working_days_pattern
        )
        return bool(
            company.name
            and company.name.strip()
            and company.currency
            and len(company.currency) == 3
            and company.timezone
            and company.fy_start_month is not None
            and 1 <= company.fy_start_month <= 12
            and has_working_day
        )

    async def get_setup_progress(
        self, session: AsyncSession, *, company_id: UUID
    ) -> CompanySetupProgress | None:
        stmt = select(CompanySetupProgress).where(CompanySetupProgress.company_id == company_id)
        return (await session.execute(stmt)).scalar_one_or_none()

    async def update_setup_progress(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        steps_completed: list[str],
        current_step: str | None,
        status: str,
        completed_at: datetime | None,
        now: datetime,
    ) -> CompanySetupProgress:
        """Recompute-and-persist — every write here is system-derived, never hand-edited
        (no `expected_version` from a caller, since no client ever supplies one; the
        `version` column still increments for the repository-wide optimistic-locking
        convention on any *other* concurrent reader/writer of this row)."""
        stmt = (
            update(CompanySetupProgress)
            .where(CompanySetupProgress.company_id == company_id)
            .values(
                steps_completed=steps_completed,
                current_step=current_step,
                status=status,
                completed_at=completed_at,
                updated_at=now,
                version=CompanySetupProgress.version + 1,
            )
            .returning(CompanySetupProgress)
        )
        return (await session.execute(stmt)).scalar_one()

    async def mark_company_onboarded(
        self, session: AsyncSession, *, company_id: UUID, onboarded_at: datetime
    ) -> None:
        """`Company.onboarded_at` — "set when setup progress first reaches COMPLETE"
        (Domain Model §2.1). Idempotent: only ever sets it once."""
        await session.execute(
            update(Company)
            .where(Company.id == company_id, Company.onboarded_at.is_(None))
            .values(onboarded_at=onboarded_at)
        )

    async def get_active_subscription(
        self, session: AsyncSession, *, company_id: UUID
    ) -> Subscription | None:
        """Live (non-terminal) subscription for the company, if any."""
        stmt = select(Subscription).where(
            Subscription.company_id == company_id,
            Subscription.deleted_at.is_(None),
            Subscription.status.notin_(_TERMINAL_SUBSCRIPTION_STATUSES),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def get_plan(self, session: AsyncSession, *, plan_id: UUID) -> Plan | None:
        stmt = select(Plan).where(Plan.id == plan_id)
        return (await session.execute(stmt)).scalar_one_or_none()

    async def get_plan_features(self, session: AsyncSession, *, plan_id: UUID) -> list[PlanFeature]:
        stmt = select(PlanFeature).where(PlanFeature.plan_id == plan_id)
        return list((await session.execute(stmt)).scalars().all())

    async def get_company_feature_flags(
        self, session: AsyncSession, *, company_id: UUID
    ) -> list[CompanyFeatureFlag]:
        stmt = select(CompanyFeatureFlag).where(CompanyFeatureFlag.company_id == company_id)
        return list((await session.execute(stmt)).scalars().all())

    async def insert_legal_entity(
        self, session: AsyncSession, *, data: dict[str, Any]
    ) -> LegalEntity:
        row = LegalEntity(**data)
        session.add(row)
        await session.flush()
        return row

    async def list_legal_entities(
        self, session: AsyncSession, *, company_id: UUID
    ) -> list[LegalEntity]:
        stmt = (
            select(LegalEntity)
            .where(LegalEntity.company_id == company_id, LegalEntity.deleted_at.is_(None))
            .order_by(LegalEntity.created_at)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def get_legal_entity(
        self, session: AsyncSession, *, company_id: UUID, entity_id: UUID
    ) -> LegalEntity | None:
        # `company_id` is filtered explicitly here (not just relied on via RLS) — the same
        # belt-and-suspenders convention as `get_company`/`update_company`, so a guessed
        # `{id}` for another tenant's row still resolves to nothing.
        stmt = select(LegalEntity).where(
            LegalEntity.id == entity_id,
            LegalEntity.company_id == company_id,
            LegalEntity.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def update_legal_entity(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        entity_id: UUID,
        values: dict[str, Any],
        expected_version: int,
        now: datetime,
    ) -> LegalEntity | None:
        stmt = (
            update(LegalEntity)
            .where(
                LegalEntity.id == entity_id,
                LegalEntity.company_id == company_id,
                LegalEntity.version == expected_version,
                LegalEntity.deleted_at.is_(None),
            )
            .values(**values, version=expected_version + 1, updated_at=now)
            .returning(LegalEntity)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def count_active_branches_for_legal_entity(
        self, session: AsyncSession, *, entity_id: UUID
    ) -> int:
        """FR-ORG-014's Legal-Entity-deactivation-blocking rule.

        `AND is_active = true` was added alongside the Branch slice's `branch.is_active`
        column — without it, a *deactivated* branch (`is_active=false`,
        `deleted_at IS NULL`, since deactivation is never a delete) would still count as
        "active" and incorrectly block Legal Entity deactivation.
        """
        result = await session.execute(
            text(
                "SELECT count(*) FROM branch "
                "WHERE legal_entity_id = :entity_id AND is_active = true AND deleted_at IS NULL"
            ),
            {"entity_id": str(entity_id)},
        )
        return int(result.scalar_one())

    async def insert_branch(self, session: AsyncSession, *, data: dict[str, Any]) -> Branch:
        row = Branch(**data)
        session.add(row)
        await session.flush()
        return row

    async def list_branches(self, session: AsyncSession, *, company_id: UUID) -> list[Branch]:
        stmt = (
            select(Branch)
            .where(Branch.company_id == company_id, Branch.deleted_at.is_(None))
            .order_by(Branch.created_at)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def get_branch(
        self, session: AsyncSession, *, company_id: UUID, branch_id: UUID
    ) -> Branch | None:
        # `company_id` is filtered explicitly here (not just relied on via RLS) — the same
        # belt-and-suspenders convention as `get_legal_entity`, so a guessed `{id}` for
        # another tenant's row still resolves to nothing.
        stmt = select(Branch).where(
            Branch.id == branch_id,
            Branch.company_id == company_id,
            Branch.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def update_branch(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        branch_id: UUID,
        values: dict[str, Any],
        expected_version: int,
        now: datetime,
    ) -> Branch | None:
        stmt = (
            update(Branch)
            .where(
                Branch.id == branch_id,
                Branch.company_id == company_id,
                Branch.version == expected_version,
                Branch.deleted_at.is_(None),
            )
            .values(**values, version=expected_version + 1, updated_at=now)
            .returning(Branch)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def count_active_departments_for_branch(
        self, session: AsyncSession, *, branch_id: UUID
    ) -> int:
        """FR-ORG-014's Branch-deactivation-blocking rule.

        `AND is_active = true` was added alongside the Department slice's
        `department.is_active` column — without it, a *deactivated* department
        (`is_active=false`, `deleted_at IS NULL`, since deactivation is never a delete)
        would still count as "active" and incorrectly block Branch deactivation.
        """
        result = await session.execute(
            text(
                "SELECT count(*) FROM department "
                "WHERE branch_id = :branch_id AND is_active = true AND deleted_at IS NULL"
            ),
            {"branch_id": str(branch_id)},
        )
        return int(result.scalar_one())

    async def insert_department(self, session: AsyncSession, *, data: dict[str, Any]) -> Department:
        row = Department(**data)
        session.add(row)
        await session.flush()
        return row

    async def list_departments(
        self, session: AsyncSession, *, company_id: UUID
    ) -> list[Department]:
        stmt = (
            select(Department)
            .where(Department.company_id == company_id, Department.deleted_at.is_(None))
            .order_by(Department.created_at)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def get_department(
        self, session: AsyncSession, *, company_id: UUID, department_id: UUID
    ) -> Department | None:
        # `company_id` is filtered explicitly here (not just relied on via RLS) — the same
        # belt-and-suspenders convention as `get_branch`, so a guessed `{id}` for another
        # tenant's row still resolves to nothing.
        stmt = select(Department).where(
            Department.id == department_id,
            Department.company_id == company_id,
            Department.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def update_department(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        department_id: UUID,
        values: dict[str, Any],
        expected_version: int,
        now: datetime,
    ) -> Department | None:
        stmt = (
            update(Department)
            .where(
                Department.id == department_id,
                Department.company_id == company_id,
                Department.version == expected_version,
                Department.deleted_at.is_(None),
            )
            .values(**values, version=expected_version + 1, updated_at=now)
            .returning(Department)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def get_department_ancestor_chain(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        start_id: UUID,
        max_hops: int = 6,
    ) -> list[UUID]:
        """Walk `parent_id` upward from `start_id`, inclusive, bounded at `max_hops` —
        FR-ORG-005's cycle-rejection + max-5-levels rule (`OrganisationService
        ._validate_department_parent`). A bounded iterative walk is sufficient here (no
        recursive CTE / `/tree` endpoint — this slice doesn't need the full nested tree,
        only "does this id appear in the chain" and "how deep is the chain")."""
        chain: list[UUID] = []
        visited: set[UUID] = set()
        current_id: UUID | None = start_id
        for _ in range(max_hops):
            if current_id is None or current_id in visited:
                break
            stmt = select(Department.id, Department.parent_id).where(
                Department.id == current_id, Department.company_id == company_id
            )
            row = (await session.execute(stmt)).first()
            if row is None:
                break
            dept_id, parent_id = row
            chain.append(dept_id)
            visited.add(dept_id)
            current_id = parent_id
        return chain

    async def insert_designation(
        self, session: AsyncSession, *, data: dict[str, Any]
    ) -> Designation:
        row = Designation(**data)
        session.add(row)
        await session.flush()
        return row

    async def list_designations(
        self, session: AsyncSession, *, company_id: UUID
    ) -> list[Designation]:
        stmt = (
            select(Designation)
            .where(Designation.company_id == company_id, Designation.deleted_at.is_(None))
            .order_by(Designation.created_at)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def get_designation(
        self, session: AsyncSession, *, company_id: UUID, designation_id: UUID
    ) -> Designation | None:
        # `company_id` is filtered explicitly here (not just relied on via RLS) — the same
        # belt-and-suspenders convention as `get_department`, so a guessed `{id}` for another
        # tenant's row still resolves to nothing.
        stmt = select(Designation).where(
            Designation.id == designation_id,
            Designation.company_id == company_id,
            Designation.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def update_designation(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        designation_id: UUID,
        values: dict[str, Any],
        expected_version: int,
        now: datetime,
    ) -> Designation | None:
        stmt = (
            update(Designation)
            .where(
                Designation.id == designation_id,
                Designation.company_id == company_id,
                Designation.version == expected_version,
                Designation.deleted_at.is_(None),
            )
            .values(**values, version=expected_version + 1, updated_at=now)
            .returning(Designation)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def insert_grade(self, session: AsyncSession, *, data: dict[str, Any]) -> Grade:
        row = Grade(**data)
        session.add(row)
        await session.flush()
        return row

    async def list_grades(self, session: AsyncSession, *, company_id: UUID) -> list[Grade]:
        stmt = (
            select(Grade)
            .where(Grade.company_id == company_id, Grade.deleted_at.is_(None))
            .order_by(Grade.created_at)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def get_grade(
        self, session: AsyncSession, *, company_id: UUID, grade_id: UUID
    ) -> Grade | None:
        # `company_id` is filtered explicitly here (not just relied on via RLS) — the same
        # belt-and-suspenders convention as `get_designation`, so a guessed `{id}` for
        # another tenant's row still resolves to nothing.
        stmt = select(Grade).where(
            Grade.id == grade_id,
            Grade.company_id == company_id,
            Grade.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def update_grade(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        grade_id: UUID,
        values: dict[str, Any],
        expected_version: int,
        now: datetime,
    ) -> Grade | None:
        stmt = (
            update(Grade)
            .where(
                Grade.id == grade_id,
                Grade.company_id == company_id,
                Grade.version == expected_version,
                Grade.deleted_at.is_(None),
            )
            .values(**values, version=expected_version + 1, updated_at=now)
            .returning(Grade)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def insert_shift(self, session: AsyncSession, *, data: dict[str, Any]) -> Shift:
        row = Shift(**data)
        session.add(row)
        await session.flush()
        return row

    async def list_shifts(self, session: AsyncSession, *, company_id: UUID) -> list[Shift]:
        stmt = (
            select(Shift)
            .where(Shift.company_id == company_id, Shift.deleted_at.is_(None))
            .order_by(Shift.created_at)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def get_shift(
        self, session: AsyncSession, *, company_id: UUID, shift_id: UUID
    ) -> Shift | None:
        # `company_id` is filtered explicitly here (not just relied on via RLS) — the same
        # belt-and-suspenders convention as `get_grade`, so a guessed `{id}` for another
        # tenant's row still resolves to nothing.
        stmt = select(Shift).where(
            Shift.id == shift_id,
            Shift.company_id == company_id,
            Shift.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def update_shift(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        shift_id: UUID,
        values: dict[str, Any],
        expected_version: int,
        now: datetime,
    ) -> Shift | None:
        stmt = (
            update(Shift)
            .where(
                Shift.id == shift_id,
                Shift.company_id == company_id,
                Shift.version == expected_version,
                Shift.deleted_at.is_(None),
            )
            .values(**values, version=expected_version + 1, updated_at=now)
            .returning(Shift)
        )
        return (await session.execute(stmt)).scalar_one_or_none()


class ShiftVersionRepository:
    """Mirrors `WeeklyOffPatternRepository`'s shape — a single repo class owns the parent
    (`ShiftVersion`) plus its typed, no-independent-lifecycle children (`ShiftBreak`,
    `ShiftDutyBlock`), full-replace on every draft PATCH (`replace_breaks`/
    `replace_duty_blocks`, mirroring `replace_rules`)."""

    async def insert(self, session: AsyncSession, *, data: dict[str, Any]) -> ShiftVersion:
        row = ShiftVersion(**data)
        session.add(row)
        await session.flush()
        return row

    async def list_versions(
        self, session: AsyncSession, *, company_id: UUID, shift_id: UUID
    ) -> list[ShiftVersion]:
        stmt = (
            select(ShiftVersion)
            .where(
                ShiftVersion.company_id == company_id,
                ShiftVersion.shift_id == shift_id,
                ShiftVersion.deleted_at.is_(None),
            )
            # `version` is per-row optimistic-concurrency (resets to 1 on every new row, same
            # as every other table in this module) — NOT a chronological sequence number, so
            # ordering by it would not put newer rows first. `created_at` is the actual
            # creation order.
            .order_by(ShiftVersion.created_at.desc())
        )
        return list((await session.execute(stmt)).scalars().all())

    async def get(
        self, session: AsyncSession, *, company_id: UUID, shift_id: UUID, version_id: UUID
    ) -> ShiftVersion | None:
        stmt = select(ShiftVersion).where(
            ShiftVersion.id == version_id,
            ShiftVersion.shift_id == shift_id,
            ShiftVersion.company_id == company_id,
            ShiftVersion.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def get_open_draft(
        self, session: AsyncSession, *, company_id: UUID, shift_id: UUID
    ) -> ShiftVersion | None:
        stmt = select(ShiftVersion).where(
            ShiftVersion.company_id == company_id,
            ShiftVersion.shift_id == shift_id,
            ShiftVersion.status == "DRAFT",
            ShiftVersion.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def get_current_published(
        self, session: AsyncSession, *, company_id: UUID, shift_id: UUID
    ) -> ShiftVersion | None:
        """The open (`effective_to IS NULL`) PUBLISHED version — at most one, by
        `shift_version_no_overlap`."""
        stmt = select(ShiftVersion).where(
            ShiftVersion.company_id == company_id,
            ShiftVersion.shift_id == shift_id,
            ShiftVersion.status == "PUBLISHED",
            ShiftVersion.effective_to.is_(None),
            ShiftVersion.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def find_effective_as_of(
        self, session: AsyncSession, *, company_id: UUID, shift_id: UUID, as_of: date
    ) -> ShiftVersion | None:
        stmt = select(ShiftVersion).where(
            ShiftVersion.company_id == company_id,
            ShiftVersion.shift_id == shift_id,
            ShiftVersion.status == "PUBLISHED",
            ShiftVersion.deleted_at.is_(None),
            ShiftVersion.effective_from <= as_of,
            or_(ShiftVersion.effective_to.is_(None), ShiftVersion.effective_to >= as_of),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def update(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        shift_id: UUID,
        version_id: UUID,
        values: dict[str, Any],
        expected_version: int,
        now: datetime,
    ) -> ShiftVersion | None:
        stmt = (
            update(ShiftVersion)
            .where(
                ShiftVersion.id == version_id,
                ShiftVersion.shift_id == shift_id,
                ShiftVersion.company_id == company_id,
                ShiftVersion.version == expected_version,
                ShiftVersion.deleted_at.is_(None),
            )
            .values(**values, version=expected_version + 1, updated_at=now)
            .returning(ShiftVersion)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def close(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        version_id: UUID,
        effective_to: date,
        expected_version: int,
        now: datetime,
    ) -> ShiftVersion | None:
        """Sets `effective_to` on a previously-open PUBLISHED version — the one permitted
        mutation to a published row, mirrors `PolicyAssignmentRepository.close`."""
        stmt = (
            update(ShiftVersion)
            .where(
                ShiftVersion.id == version_id,
                ShiftVersion.company_id == company_id,
                ShiftVersion.version == expected_version,
                ShiftVersion.deleted_at.is_(None),
            )
            .values(effective_to=effective_to, version=expected_version + 1, updated_at=now)
            .returning(ShiftVersion)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def discard(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        shift_id: UUID,
        version_id: UUID,
        expected_version: int,
        now: datetime,
    ) -> ShiftVersion | None:
        stmt = (
            update(ShiftVersion)
            .where(
                ShiftVersion.id == version_id,
                ShiftVersion.shift_id == shift_id,
                ShiftVersion.company_id == company_id,
                ShiftVersion.version == expected_version,
                ShiftVersion.deleted_at.is_(None),
            )
            .values(deleted_at=now, version=expected_version + 1, updated_at=now)
            .returning(ShiftVersion)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def list_breaks(
        self, session: AsyncSession, *, company_id: UUID, shift_version_id: UUID
    ) -> list[ShiftBreak]:
        stmt = (
            select(ShiftBreak)
            .where(
                ShiftBreak.company_id == company_id,
                ShiftBreak.shift_version_id == shift_version_id,
            )
            .order_by(ShiftBreak.sort_order)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def list_breaks_for_versions(
        self, session: AsyncSession, *, company_id: UUID, version_ids: list[UUID]
    ) -> list[ShiftBreak]:
        if not version_ids:
            return []
        stmt = (
            select(ShiftBreak)
            .where(
                ShiftBreak.company_id == company_id,
                ShiftBreak.shift_version_id.in_(version_ids),
            )
            .order_by(ShiftBreak.sort_order)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def replace_breaks(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        shift_version_id: UUID,
        rows: list[dict[str, Any]],
    ) -> list[ShiftBreak]:
        """Atomic replace-all — mirrors `WeeklyOffPatternRepository.replace_rules`."""
        await session.execute(
            delete(ShiftBreak).where(
                ShiftBreak.company_id == company_id,
                ShiftBreak.shift_version_id == shift_version_id,
            )
        )
        created = [ShiftBreak(**row) for row in rows]
        session.add_all(created)
        await session.flush()
        return created

    async def list_duty_blocks(
        self, session: AsyncSession, *, company_id: UUID, shift_version_id: UUID
    ) -> list[ShiftDutyBlock]:
        stmt = (
            select(ShiftDutyBlock)
            .where(
                ShiftDutyBlock.company_id == company_id,
                ShiftDutyBlock.shift_version_id == shift_version_id,
            )
            .order_by(ShiftDutyBlock.sequence)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def list_duty_blocks_for_versions(
        self, session: AsyncSession, *, company_id: UUID, version_ids: list[UUID]
    ) -> list[ShiftDutyBlock]:
        if not version_ids:
            return []
        stmt = (
            select(ShiftDutyBlock)
            .where(
                ShiftDutyBlock.company_id == company_id,
                ShiftDutyBlock.shift_version_id.in_(version_ids),
            )
            .order_by(ShiftDutyBlock.sequence)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def replace_duty_blocks(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        shift_version_id: UUID,
        rows: list[dict[str, Any]],
    ) -> list[ShiftDutyBlock]:
        await session.execute(
            delete(ShiftDutyBlock).where(
                ShiftDutyBlock.company_id == company_id,
                ShiftDutyBlock.shift_version_id == shift_version_id,
            )
        )
        created = [ShiftDutyBlock(**row) for row in rows]
        session.add_all(created)
        await session.flush()
        return created

    async def list_open_and_draft_for_shifts(
        self, session: AsyncSession, *, company_id: UUID, shift_ids: list[UUID]
    ) -> list[ShiftVersion]:
        """Batch lookup for `list_shifts` — the open (`effective_to IS NULL`) PUBLISHED
        version and/or the open DRAFT, per shift, in one query (avoids N+1)."""
        if not shift_ids:
            return []
        stmt = select(ShiftVersion).where(
            ShiftVersion.company_id == company_id,
            ShiftVersion.shift_id.in_(shift_ids),
            ShiftVersion.deleted_at.is_(None),
            or_(
                and_(ShiftVersion.status == "PUBLISHED", ShiftVersion.effective_to.is_(None)),
                ShiftVersion.status == "DRAFT",
            ),
        )
        return list((await session.execute(stmt)).scalars().all())


class HolidayCalendarRepository:
    async def insert(self, session: AsyncSession, *, data: dict[str, Any]) -> HolidayCalendar:
        row = HolidayCalendar(**data)
        session.add(row)
        await session.flush()
        return row

    async def list_calendars(
        self, session: AsyncSession, *, company_id: UUID
    ) -> list[HolidayCalendar]:
        stmt = (
            select(HolidayCalendar)
            .where(HolidayCalendar.company_id == company_id, HolidayCalendar.deleted_at.is_(None))
            .order_by(HolidayCalendar.created_at)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def get(
        self, session: AsyncSession, *, company_id: UUID, calendar_id: UUID
    ) -> HolidayCalendar | None:
        stmt = select(HolidayCalendar).where(
            HolidayCalendar.id == calendar_id,
            HolidayCalendar.company_id == company_id,
            HolidayCalendar.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def update(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        calendar_id: UUID,
        values: dict[str, Any],
        expected_version: int,
        now: datetime,
    ) -> HolidayCalendar | None:
        stmt = (
            update(HolidayCalendar)
            .where(
                HolidayCalendar.id == calendar_id,
                HolidayCalendar.company_id == company_id,
                HolidayCalendar.version == expected_version,
                HolidayCalendar.deleted_at.is_(None),
            )
            .values(**values, version=expected_version + 1, updated_at=now)
            .returning(HolidayCalendar)
        )
        return (await session.execute(stmt)).scalar_one_or_none()


class HolidayRepository:
    async def insert(self, session: AsyncSession, *, data: dict[str, Any]) -> Holiday:
        row = Holiday(**data)
        session.add(row)
        await session.flush()
        return row

    async def list_holidays(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        calendar_id: UUID,
        year: int | None = None,
    ) -> list[Holiday]:
        conditions: list[Any] = [
            Holiday.company_id == company_id,
            Holiday.calendar_id == calendar_id,
            Holiday.deleted_at.is_(None),
        ]
        if year is not None:
            conditions.append(text("EXTRACT(YEAR FROM date) = :year").bindparams(year=year))
        stmt = select(Holiday).where(*conditions).order_by(Holiday.date)
        return list((await session.execute(stmt)).scalars().all())

    async def list_for_calendars(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        calendar_ids: list[UUID],
    ) -> list[Holiday]:
        """Every active holiday across an ordered set of calendars — the composition read
        used by calendar resolution (architecture §6.3)."""
        if not calendar_ids:
            return []
        stmt = select(Holiday).where(
            Holiday.company_id == company_id,
            Holiday.calendar_id.in_(calendar_ids),
            Holiday.deleted_at.is_(None),
            Holiday.is_active.is_(True),
        )
        return list((await session.execute(stmt)).scalars().all())

    async def get(
        self, session: AsyncSession, *, company_id: UUID, holiday_id: UUID
    ) -> Holiday | None:
        stmt = select(Holiday).where(
            Holiday.id == holiday_id,
            Holiday.company_id == company_id,
            Holiday.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def update(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        holiday_id: UUID,
        values: dict[str, Any],
        expected_version: int,
        now: datetime,
    ) -> Holiday | None:
        stmt = (
            update(Holiday)
            .where(
                Holiday.id == holiday_id,
                Holiday.company_id == company_id,
                Holiday.version == expected_version,
                Holiday.deleted_at.is_(None),
            )
            .values(**values, version=expected_version + 1, updated_at=now)
            .returning(Holiday)
        )
        return (await session.execute(stmt)).scalar_one_or_none()


class WeeklyOffPatternRepository:
    async def insert(self, session: AsyncSession, *, data: dict[str, Any]) -> WeeklyOffPattern:
        row = WeeklyOffPattern(**data)
        session.add(row)
        await session.flush()
        return row

    async def list_patterns(
        self, session: AsyncSession, *, company_id: UUID
    ) -> list[WeeklyOffPattern]:
        stmt = (
            select(WeeklyOffPattern)
            .where(WeeklyOffPattern.company_id == company_id, WeeklyOffPattern.deleted_at.is_(None))
            .order_by(WeeklyOffPattern.created_at)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def get(
        self, session: AsyncSession, *, company_id: UUID, pattern_id: UUID
    ) -> WeeklyOffPattern | None:
        stmt = select(WeeklyOffPattern).where(
            WeeklyOffPattern.id == pattern_id,
            WeeklyOffPattern.company_id == company_id,
            WeeklyOffPattern.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def update(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        pattern_id: UUID,
        values: dict[str, Any],
        expected_version: int,
        now: datetime,
    ) -> WeeklyOffPattern | None:
        stmt = (
            update(WeeklyOffPattern)
            .where(
                WeeklyOffPattern.id == pattern_id,
                WeeklyOffPattern.company_id == company_id,
                WeeklyOffPattern.version == expected_version,
                WeeklyOffPattern.deleted_at.is_(None),
            )
            .values(**values, version=expected_version + 1, updated_at=now)
            .returning(WeeklyOffPattern)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def list_rules(
        self, session: AsyncSession, *, company_id: UUID, pattern_id: UUID
    ) -> list[WeeklyOffRule]:
        stmt = (
            select(WeeklyOffRule)
            .where(WeeklyOffRule.company_id == company_id, WeeklyOffRule.pattern_id == pattern_id)
            .order_by(WeeklyOffRule.weekday)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def list_rules_for_patterns(
        self, session: AsyncSession, *, company_id: UUID, pattern_ids: list[UUID]
    ) -> list[WeeklyOffRule]:
        if not pattern_ids:
            return []
        stmt = select(WeeklyOffRule).where(
            WeeklyOffRule.company_id == company_id,
            WeeklyOffRule.pattern_id.in_(pattern_ids),
        )
        return list((await session.execute(stmt)).scalars().all())

    async def replace_rules(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        pattern_id: UUID,
        rows: list[dict[str, Any]],
    ) -> list[WeeklyOffRule]:
        """Atomic replace-all — the whole rule set is small and typed, so diffing individual
        rows adds complexity with no real benefit (mirrors `WorkCalendarRepository
        .replace_holiday_calendar_links`)."""
        await session.execute(
            delete(WeeklyOffRule).where(
                WeeklyOffRule.company_id == company_id, WeeklyOffRule.pattern_id == pattern_id
            )
        )
        created = [WeeklyOffRule(**row) for row in rows]
        session.add_all(created)
        await session.flush()
        return created


class WorkCalendarRepository:
    async def insert(self, session: AsyncSession, *, data: dict[str, Any]) -> WorkCalendar:
        row = WorkCalendar(**data)
        session.add(row)
        await session.flush()
        return row

    async def list_work_calendars(
        self, session: AsyncSession, *, company_id: UUID
    ) -> list[WorkCalendar]:
        stmt = (
            select(WorkCalendar)
            .where(WorkCalendar.company_id == company_id, WorkCalendar.deleted_at.is_(None))
            .order_by(WorkCalendar.created_at)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def get(
        self, session: AsyncSession, *, company_id: UUID, work_calendar_id: UUID
    ) -> WorkCalendar | None:
        stmt = select(WorkCalendar).where(
            WorkCalendar.id == work_calendar_id,
            WorkCalendar.company_id == company_id,
            WorkCalendar.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def update(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        work_calendar_id: UUID,
        values: dict[str, Any],
        expected_version: int,
        now: datetime,
    ) -> WorkCalendar | None:
        stmt = (
            update(WorkCalendar)
            .where(
                WorkCalendar.id == work_calendar_id,
                WorkCalendar.company_id == company_id,
                WorkCalendar.version == expected_version,
                WorkCalendar.deleted_at.is_(None),
            )
            .values(**values, version=expected_version + 1, updated_at=now)
            .returning(WorkCalendar)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def list_holiday_calendar_links(
        self, session: AsyncSession, *, company_id: UUID, work_calendar_id: UUID
    ) -> list[WorkCalendarHolidayCalendar]:
        stmt = (
            select(WorkCalendarHolidayCalendar)
            .where(
                WorkCalendarHolidayCalendar.company_id == company_id,
                WorkCalendarHolidayCalendar.work_calendar_id == work_calendar_id,
            )
            .order_by(WorkCalendarHolidayCalendar.sort_order)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def replace_holiday_calendar_links(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        work_calendar_id: UUID,
        holiday_calendar_ids: list[UUID],
        now: datetime,
    ) -> None:
        await session.execute(
            delete(WorkCalendarHolidayCalendar).where(
                WorkCalendarHolidayCalendar.company_id == company_id,
                WorkCalendarHolidayCalendar.work_calendar_id == work_calendar_id,
            )
        )
        links = [
            WorkCalendarHolidayCalendar(
                id=uuid4(),
                company_id=company_id,
                work_calendar_id=work_calendar_id,
                holiday_calendar_id=holiday_calendar_id,
                sort_order=index,
                created_at=now,
            )
            for index, holiday_calendar_id in enumerate(holiday_calendar_ids)
        ]
        session.add_all(links)
        await session.flush()


class CalendarExceptionRepository:
    async def insert(self, session: AsyncSession, *, data: dict[str, Any]) -> CalendarException:
        row = CalendarException(**data)
        session.add(row)
        await session.flush()
        return row

    async def list_exceptions(
        self, session: AsyncSession, *, company_id: UUID, work_calendar_id: UUID
    ) -> list[CalendarException]:
        stmt = (
            select(CalendarException)
            .where(
                CalendarException.company_id == company_id,
                CalendarException.work_calendar_id == work_calendar_id,
                CalendarException.deleted_at.is_(None),
            )
            .order_by(CalendarException.exception_date)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def list_active_for_calendars(
        self, session: AsyncSession, *, company_id: UUID, work_calendar_ids: list[UUID]
    ) -> list[CalendarException]:
        if not work_calendar_ids:
            return []
        stmt = select(CalendarException).where(
            CalendarException.company_id == company_id,
            CalendarException.work_calendar_id.in_(work_calendar_ids),
            CalendarException.deleted_at.is_(None),
            CalendarException.is_active.is_(True),
        )
        return list((await session.execute(stmt)).scalars().all())

    async def get(
        self, session: AsyncSession, *, company_id: UUID, exception_id: UUID
    ) -> CalendarException | None:
        stmt = select(CalendarException).where(
            CalendarException.id == exception_id,
            CalendarException.company_id == company_id,
            CalendarException.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def update(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        exception_id: UUID,
        values: dict[str, Any],
        expected_version: int,
        now: datetime,
    ) -> CalendarException | None:
        stmt = (
            update(CalendarException)
            .where(
                CalendarException.id == exception_id,
                CalendarException.company_id == company_id,
                CalendarException.version == expected_version,
                CalendarException.deleted_at.is_(None),
            )
            .values(**values, version=expected_version + 1, updated_at=now)
            .returning(CalendarException)
        )
        return (await session.execute(stmt)).scalar_one_or_none()


class PolicyAssignmentRepository:
    """Insert-new/close-previous only — mirrors `EmployeeAssignmentRepository`
    (`hrms.modules.employee.repository`), but keyed on `(company_id, policy_kind, scope_type,
    scope_id)` rather than `employee_id`: there can be many concurrently-open rows across
    different scope tuples, not one "current" row per key."""

    async def insert(self, session: AsyncSession, *, data: dict[str, Any]) -> PolicyAssignment:
        row = PolicyAssignment(**data)
        session.add(row)
        await session.flush()
        return row

    async def get_current(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        policy_kind: str,
        scope_type: str,
        scope_id: UUID | None,
        leave_type_id: UUID | None = None,
    ) -> PolicyAssignment | None:
        stmt = select(PolicyAssignment).where(
            PolicyAssignment.company_id == company_id,
            PolicyAssignment.policy_kind == policy_kind,
            PolicyAssignment.leave_type_id == leave_type_id
            if leave_type_id is not None
            else PolicyAssignment.leave_type_id.is_(None),
            PolicyAssignment.scope_type == scope_type,
            PolicyAssignment.scope_id == scope_id
            if scope_id is not None
            else PolicyAssignment.scope_id.is_(None),
            PolicyAssignment.deleted_at.is_(None),
            PolicyAssignment.effective_to.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def get(
        self, session: AsyncSession, *, company_id: UUID, assignment_id: UUID
    ) -> PolicyAssignment | None:
        stmt = select(PolicyAssignment).where(
            PolicyAssignment.id == assignment_id,
            PolicyAssignment.company_id == company_id,
            PolicyAssignment.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def list_assignments(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        policy_kind: str | None = None,
        scope_type: str | None = None,
        scope_id: UUID | None = None,
    ) -> list[PolicyAssignment]:
        conditions = [
            PolicyAssignment.company_id == company_id,
            PolicyAssignment.deleted_at.is_(None),
        ]
        if policy_kind is not None:
            conditions.append(PolicyAssignment.policy_kind == policy_kind)
        if scope_type is not None:
            conditions.append(PolicyAssignment.scope_type == scope_type)
        if scope_id is not None:
            conditions.append(PolicyAssignment.scope_id == scope_id)
        stmt = (
            select(PolicyAssignment)
            .where(*conditions)
            .order_by(PolicyAssignment.effective_from.desc())
        )
        return list((await session.execute(stmt)).scalars().all())

    async def find_effective(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        policy_kind: str,
        scope_type: str,
        scope_id: UUID | None,
        as_of: date,
        leave_type_id: UUID | None = None,
    ) -> PolicyAssignment | None:
        """The row of the given kind/scope active on `as_of` — at most one, by
        `policy_assignment_no_overlap`. Used by `calendar_resolution.resolve_policy_assignment`
        for a single scope level in the WD-09 precedence walk. `leave_type_id` (LD-11) narrows
        further for `policy_kind="LEAVE_POLICY"`, where multiple assignments (one per leave type)
        can be simultaneously active at the same scope."""
        stmt = select(PolicyAssignment).where(
            PolicyAssignment.company_id == company_id,
            PolicyAssignment.policy_kind == policy_kind,
            PolicyAssignment.leave_type_id == leave_type_id
            if leave_type_id is not None
            else PolicyAssignment.leave_type_id.is_(None),
            PolicyAssignment.scope_type == scope_type,
            PolicyAssignment.scope_id == scope_id
            if scope_id is not None
            else PolicyAssignment.scope_id.is_(None),
            PolicyAssignment.deleted_at.is_(None),
            PolicyAssignment.is_active.is_(True),
            PolicyAssignment.effective_from <= as_of,
            or_(PolicyAssignment.effective_to.is_(None), PolicyAssignment.effective_to >= as_of),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def close(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        assignment_id: UUID,
        effective_to: date,
        expected_version: int,
        now: datetime,
    ) -> PolicyAssignment | None:
        stmt = (
            update(PolicyAssignment)
            .where(
                PolicyAssignment.id == assignment_id,
                PolicyAssignment.company_id == company_id,
                PolicyAssignment.version == expected_version,
                PolicyAssignment.deleted_at.is_(None),
            )
            .values(effective_to=effective_to, version=expected_version + 1, updated_at=now)
            .returning(PolicyAssignment)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def deactivate(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        assignment_id: UUID,
        expected_version: int,
        now: datetime,
    ) -> PolicyAssignment | None:
        stmt = (
            update(PolicyAssignment)
            .where(
                PolicyAssignment.id == assignment_id,
                PolicyAssignment.company_id == company_id,
                PolicyAssignment.version == expected_version,
                PolicyAssignment.deleted_at.is_(None),
            )
            .values(is_active=False, version=expected_version + 1, updated_at=now)
            .returning(PolicyAssignment)
        )
        return (await session.execute(stmt)).scalar_one_or_none()
