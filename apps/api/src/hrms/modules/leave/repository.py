"""Thin, session-passed-in repositories for the Leave module — mirrors
`attendance.repository`'s `AttendancePolicyRepository` shape (identity CRUD + version CRUD,
insert-new/close-previous publish)."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.modules.leave.models import LeaveLedgerEntry, LeavePolicy, LeavePolicyVersion, LeaveType


class LeaveTypeRepository:
    async def insert(self, session: AsyncSession, *, data: dict[str, Any]) -> LeaveType:
        row = LeaveType(**data)
        session.add(row)
        await session.flush()
        return row

    async def get(
        self, session: AsyncSession, *, company_id: UUID, leave_type_id: UUID
    ) -> LeaveType | None:
        stmt = select(LeaveType).where(
            LeaveType.id == leave_type_id,
            LeaveType.company_id == company_id,
            LeaveType.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def list(self, session: AsyncSession, *, company_id: UUID) -> list[LeaveType]:
        stmt = (
            select(LeaveType)
            .where(LeaveType.company_id == company_id, LeaveType.deleted_at.is_(None))
            .order_by(LeaveType.name)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def update(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        leave_type_id: UUID,
        values: dict[str, Any],
        expected_version: int,
        now: datetime,
    ) -> LeaveType | None:
        stmt = (
            update(LeaveType)
            .where(
                LeaveType.id == leave_type_id,
                LeaveType.company_id == company_id,
                LeaveType.version == expected_version,
                LeaveType.deleted_at.is_(None),
            )
            .values(**values, version=expected_version + 1, updated_at=now)
            .returning(LeaveType)
        )
        return (await session.execute(stmt)).scalar_one_or_none()


class LeavePolicyRepository:
    # -- identity --

    async def insert_policy(self, session: AsyncSession, *, data: dict[str, Any]) -> LeavePolicy:
        row = LeavePolicy(**data)
        session.add(row)
        await session.flush()
        return row

    async def get_policy(
        self, session: AsyncSession, *, company_id: UUID, policy_id: UUID
    ) -> LeavePolicy | None:
        stmt = select(LeavePolicy).where(
            LeavePolicy.id == policy_id,
            LeavePolicy.company_id == company_id,
            LeavePolicy.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def list_policies(self, session: AsyncSession, *, company_id: UUID) -> list[LeavePolicy]:
        stmt = (
            select(LeavePolicy)
            .where(LeavePolicy.company_id == company_id, LeavePolicy.deleted_at.is_(None))
            .order_by(LeavePolicy.name)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def update_policy(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        policy_id: UUID,
        values: dict[str, Any],
        expected_version: int,
        now: datetime,
    ) -> LeavePolicy | None:
        stmt = (
            update(LeavePolicy)
            .where(
                LeavePolicy.id == policy_id,
                LeavePolicy.company_id == company_id,
                LeavePolicy.version == expected_version,
                LeavePolicy.deleted_at.is_(None),
            )
            .values(**values, version=expected_version + 1, updated_at=now)
            .returning(LeavePolicy)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    # -- versions --

    async def insert_version(
        self, session: AsyncSession, *, data: dict[str, Any]
    ) -> LeavePolicyVersion:
        row = LeavePolicyVersion(**data)
        session.add(row)
        await session.flush()
        return row

    async def list_versions(
        self, session: AsyncSession, *, company_id: UUID, policy_id: UUID
    ) -> list[LeavePolicyVersion]:
        stmt = (
            select(LeavePolicyVersion)
            .where(
                LeavePolicyVersion.company_id == company_id,
                LeavePolicyVersion.policy_id == policy_id,
                LeavePolicyVersion.deleted_at.is_(None),
            )
            .order_by(LeavePolicyVersion.created_at.desc())
        )
        return list((await session.execute(stmt)).scalars().all())

    async def get_version(
        self, session: AsyncSession, *, company_id: UUID, policy_id: UUID, version_id: UUID
    ) -> LeavePolicyVersion | None:
        stmt = select(LeavePolicyVersion).where(
            LeavePolicyVersion.id == version_id,
            LeavePolicyVersion.policy_id == policy_id,
            LeavePolicyVersion.company_id == company_id,
            LeavePolicyVersion.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def get_open_draft(
        self, session: AsyncSession, *, company_id: UUID, policy_id: UUID
    ) -> LeavePolicyVersion | None:
        stmt = select(LeavePolicyVersion).where(
            LeavePolicyVersion.company_id == company_id,
            LeavePolicyVersion.policy_id == policy_id,
            LeavePolicyVersion.status == "DRAFT",
            LeavePolicyVersion.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def get_current_published(
        self, session: AsyncSession, *, company_id: UUID, policy_id: UUID
    ) -> LeavePolicyVersion | None:
        stmt = select(LeavePolicyVersion).where(
            LeavePolicyVersion.company_id == company_id,
            LeavePolicyVersion.policy_id == policy_id,
            LeavePolicyVersion.status == "PUBLISHED",
            LeavePolicyVersion.effective_to.is_(None),
            LeavePolicyVersion.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def find_effective_as_of(
        self, session: AsyncSession, *, company_id: UUID, policy_id: UUID, as_of: date
    ) -> LeavePolicyVersion | None:
        stmt = select(LeavePolicyVersion).where(
            LeavePolicyVersion.company_id == company_id,
            LeavePolicyVersion.policy_id == policy_id,
            LeavePolicyVersion.status == "PUBLISHED",
            LeavePolicyVersion.deleted_at.is_(None),
            LeavePolicyVersion.effective_from <= as_of,
            or_(
                LeavePolicyVersion.effective_to.is_(None),
                LeavePolicyVersion.effective_to >= as_of,
            ),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def update_version(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        policy_id: UUID,
        version_id: UUID,
        values: dict[str, Any],
        expected_version: int,
        now: datetime,
    ) -> LeavePolicyVersion | None:
        stmt = (
            update(LeavePolicyVersion)
            .where(
                LeavePolicyVersion.id == version_id,
                LeavePolicyVersion.policy_id == policy_id,
                LeavePolicyVersion.company_id == company_id,
                LeavePolicyVersion.version == expected_version,
                LeavePolicyVersion.deleted_at.is_(None),
            )
            .values(**values, version=expected_version + 1, updated_at=now)
            .returning(LeavePolicyVersion)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def close_version(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        version_id: UUID,
        effective_to: date,
        expected_version: int,
        now: datetime,
    ) -> LeavePolicyVersion | None:
        stmt = (
            update(LeavePolicyVersion)
            .where(
                LeavePolicyVersion.id == version_id,
                LeavePolicyVersion.company_id == company_id,
                LeavePolicyVersion.version == expected_version,
                LeavePolicyVersion.deleted_at.is_(None),
            )
            .values(effective_to=effective_to, version=expected_version + 1, updated_at=now)
            .returning(LeavePolicyVersion)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def discard_version(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        policy_id: UUID,
        version_id: UUID,
        expected_version: int,
        now: datetime,
    ) -> LeavePolicyVersion | None:
        stmt = (
            update(LeavePolicyVersion)
            .where(
                LeavePolicyVersion.id == version_id,
                LeavePolicyVersion.policy_id == policy_id,
                LeavePolicyVersion.company_id == company_id,
                LeavePolicyVersion.version == expected_version,
                LeavePolicyVersion.deleted_at.is_(None),
            )
            .values(deleted_at=now, version=expected_version + 1, updated_at=now)
            .returning(LeavePolicyVersion)
        )
        return (await session.execute(stmt)).scalar_one_or_none()


@dataclass(frozen=True, slots=True)
class LeaveBalanceRow:
    """Result shape of `LeaveLedgerRepository.get_balances` — one row per `requires_balance`
    leave type, joined with its ledger sum (COALESCE'd to 0 for a type with no entries yet)."""

    leave_type_id: UUID
    leave_type_code: str
    leave_type_name: str
    balance: Decimal


class LeaveLedgerRepository:
    async def insert(self, session: AsyncSession, *, data: dict[str, Any]) -> LeaveLedgerEntry:
        row = LeaveLedgerEntry(**data)
        session.add(row)
        await session.flush()
        return row

    async def list_for_employee(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        employee_id: UUID,
        leave_type_id: UUID | None = None,
    ) -> list[LeaveLedgerEntry]:
        conditions = [
            LeaveLedgerEntry.company_id == company_id,
            LeaveLedgerEntry.employee_id == employee_id,
        ]
        if leave_type_id is not None:
            conditions.append(LeaveLedgerEntry.leave_type_id == leave_type_id)
        stmt = (
            select(LeaveLedgerEntry)
            .where(*conditions)
            .order_by(LeaveLedgerEntry.effective_date.desc(), LeaveLedgerEntry.created_at.desc())
        )
        return list((await session.execute(stmt)).scalars().all())

    async def exists_for_cycle(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        employee_id: UUID,
        leave_type_id: UUID,
        entry_type: str,
        effective_date: date,
    ) -> bool:
        """Idempotency guard for the accrual task (L3): has this exact
        (employee, leave_type, entry_type, effective_date) combination already been written?
        Append-only means a re-run must never write a duplicate `ACCRUAL` row for the same
        cycle."""
        stmt = select(LeaveLedgerEntry.id).where(
            LeaveLedgerEntry.company_id == company_id,
            LeaveLedgerEntry.employee_id == employee_id,
            LeaveLedgerEntry.leave_type_id == leave_type_id,
            LeaveLedgerEntry.entry_type == entry_type,
            LeaveLedgerEntry.effective_date == effective_date,
        )
        return (await session.execute(stmt)).scalar_one_or_none() is not None

    async def get_balances(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID
    ) -> list[LeaveBalanceRow]:
        """Every active, `requires_balance` leave type for the company, left-joined against this
        one employee's ledger entries and summed — a type with zero activity still appears, with
        `balance=0`, rather than being silently omitted (LD-03: balance is always the derived
        sum, computed fresh on every read, never cached)."""
        balance_sum = func.coalesce(func.sum(LeaveLedgerEntry.amount), 0).label("balance")
        stmt = (
            select(
                LeaveType.id,
                LeaveType.code,
                LeaveType.name,
                balance_sum,
            )
            .select_from(LeaveType)
            .outerjoin(
                LeaveLedgerEntry,
                (LeaveLedgerEntry.leave_type_id == LeaveType.id)
                & (LeaveLedgerEntry.employee_id == employee_id)
                & (LeaveLedgerEntry.company_id == company_id),
            )
            .where(
                LeaveType.company_id == company_id,
                LeaveType.requires_balance.is_(True),
                LeaveType.is_active.is_(True),
                LeaveType.deleted_at.is_(None),
            )
            .group_by(LeaveType.id, LeaveType.code, LeaveType.name)
            .order_by(LeaveType.name)
        )
        rows = (await session.execute(stmt)).all()
        return [
            LeaveBalanceRow(
                leave_type_id=r[0], leave_type_code=r[1], leave_type_name=r[2], balance=r[3]
            )
            for r in rows
        ]
