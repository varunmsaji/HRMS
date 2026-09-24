"""Thin, session-passed-in repositories for the Leave module — mirrors
`attendance.repository`'s `AttendancePolicyRepository` shape (identity CRUD + version CRUD,
insert-new/close-previous publish)."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, delete, func, or_, select, true, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.modules.leave.models import (
    LeaveApplication,
    LeaveApplicationAction,
    LeaveApplicationDay,
    LeaveCombinationRule,
    LeaveLedgerEntry,
    LeavePolicy,
    LeavePolicyVersion,
    LeaveType,
    LeaveYearSetting,
    StatutoryLeaveMinimum,
)


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

    async def get_comp_off_type(
        self, session: AsyncSession, *, company_id: UUID
    ) -> LeaveType | None:
        """LD-14 — the one active `is_comp_off=true` leave type for this company, if HR has
        designated one yet. `None` is a valid, non-error state (not configured), matching the
        accrual engine's own "skip if not configured" posture for other unset policy fields."""
        stmt = select(LeaveType).where(
            LeaveType.company_id == company_id,
            LeaveType.is_comp_off.is_(True),
            LeaveType.is_active.is_(True),
            LeaveType.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

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

    async def get_version_by_id(
        self, session: AsyncSession, *, company_id: UUID, version_id: UUID
    ) -> LeavePolicyVersion | None:
        """By id alone — a leave application snapshots `leave_policy_version_id`, not the policy.
        Deliberately includes soft-deleted versions: the application stays bound to it."""
        stmt = select(LeavePolicyVersion).where(
            LeavePolicyVersion.id == version_id,
            LeavePolicyVersion.company_id == company_id,
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

    async def list_encashments_between(
        self, session: AsyncSession, *, company_id: UUID, date_from: date, date_to: date
    ) -> list[LeaveLedgerEntry]:
        stmt = (
            select(LeaveLedgerEntry)
            .where(
                LeaveLedgerEntry.company_id == company_id,
                LeaveLedgerEntry.entry_type == "ENCASHMENT",
                LeaveLedgerEntry.effective_date >= date_from,
                LeaveLedgerEntry.effective_date <= date_to,
            )
            .order_by(LeaveLedgerEntry.effective_date, LeaveLedgerEntry.created_at)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def insert_if_absent(self, session: AsyncSession, *, data: dict[str, Any]) -> bool:
        """DAT-001 — for system-written entries guarded by a partial unique index (one
        `ACCRUAL`/`CARRY_FORWARD` per cycle, one `COMP_OFF_CREDIT` per overtime record). A
        concurrent duplicate run inserts nothing instead of double-crediting. Returns whether
        this call wrote the row."""
        stmt = (
            pg_insert(LeaveLedgerEntry)
            .values(**data)
            .on_conflict_do_nothing()
            .returning(LeaveLedgerEntry.id)
        )
        return (await session.execute(stmt)).first() is not None

    async def lock_balance(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID, leave_type_id: UUID
    ) -> None:
        """PAY-010 — serialises every check-then-debit on one employee's balance for one leave
        type until the transaction ends. A transaction-scoped advisory lock, not `FOR UPDATE`:
        the race is two transactions each *inserting* a debit, and row locks cannot block an
        insert of a row neither has seen."""
        key = f"leave-balance:{company_id}:{employee_id}:{leave_type_id}"
        await session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0))))

    async def get_balance(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID, leave_type_id: UUID
    ) -> Decimal:
        stmt = select(func.coalesce(func.sum(LeaveLedgerEntry.amount), 0)).where(
            LeaveLedgerEntry.company_id == company_id,
            LeaveLedgerEntry.employee_id == employee_id,
            LeaveLedgerEntry.leave_type_id == leave_type_id,
        )
        return Decimal((await session.execute(stmt)).scalar_one())

    async def list_for_employee(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        employee_id: UUID,
        leave_type_id: UUID | None = None,
        limit: int | None = None,
        offset: int = 0,
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
        if limit is not None:
            stmt = stmt.limit(limit).offset(offset)
        return list((await session.execute(stmt)).scalars().all())

    async def count_for_employee(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        employee_id: UUID,
        leave_type_id: UUID | None = None,
    ) -> int:
        """Same predicates as `list_for_employee`, no `ORDER BY`/`LIMIT` — the paired COUNT query
        for `GET /leave-ledger`'s `pagination.total` (API-01 §6)."""
        conditions = [
            LeaveLedgerEntry.company_id == company_id,
            LeaveLedgerEntry.employee_id == employee_id,
        ]
        if leave_type_id is not None:
            conditions.append(LeaveLedgerEntry.leave_type_id == leave_type_id)
        stmt = select(func.count()).select_from(LeaveLedgerEntry).where(*conditions)
        return int((await session.execute(stmt)).scalar_one())

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

    async def exists_with_reference(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        entry_type: str,
        reference_id: UUID,
    ) -> bool:
        """Idempotency guard for the L5 comp-off credit engine (LD-14) — mirrors
        `exists_for_cycle`'s role for accrual, but keyed on `reference_id` (the
        `overtime_record_id`) rather than a cycle date, since a comp-off credit is a one-off
        event, not a recurring cycle."""
        stmt = select(LeaveLedgerEntry.id).where(
            LeaveLedgerEntry.company_id == company_id,
            LeaveLedgerEntry.entry_type == entry_type,
            LeaveLedgerEntry.reference_id == reference_id,
        )
        return (await session.execute(stmt)).scalar_one_or_none() is not None

    async def list_credits_for_expiry(
        self, session: AsyncSession, *, company_id: UUID, leave_type_id: UUID
    ) -> list[LeaveLedgerEntry]:
        """All `COMP_OFF_CREDIT` entries for this leave type — the expiry sweep (LD-14)
        cross-references each one's `reference_id` (the source `overtime_record_id`) against
        Attendance's facts to find its expiry date, since `leave_ledger` itself has no
        `expiry_date` column (LD-02's locked shape). Ordered by employee so concurrent sweeps
        take per-employee balance locks in the same order."""
        stmt = (
            select(LeaveLedgerEntry)
            .where(
                LeaveLedgerEntry.company_id == company_id,
                LeaveLedgerEntry.leave_type_id == leave_type_id,
                LeaveLedgerEntry.entry_type == "COMP_OFF_CREDIT",
            )
            .order_by(
                LeaveLedgerEntry.employee_id,
                LeaveLedgerEntry.effective_date,
                LeaveLedgerEntry.id,
            )
        )
        return list((await session.execute(stmt)).scalars().all())

    async def get_balances(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        employee_id: UUID,
        as_of: date | None = None,
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
                & (LeaveLedgerEntry.company_id == company_id)
                # Payroll 5.4 — a payslip shows the balance on its last day.
                & (LeaveLedgerEntry.effective_date <= as_of if as_of is not None else true()),
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


# ---------------------------------------------------------------------------
# Leave Application — L4, mirrors `AttendanceRegularizationRequestRepository`'s shape (LD-05)
# ---------------------------------------------------------------------------


class LeaveApplicationRepository:
    async def insert(self, session: AsyncSession, *, data: dict[str, Any]) -> LeaveApplication:
        row = LeaveApplication(**data)
        session.add(row)
        await session.flush()
        return row

    async def get(
        self, session: AsyncSession, *, company_id: UUID, application_id: UUID
    ) -> LeaveApplication | None:
        stmt = select(LeaveApplication).where(
            LeaveApplication.id == application_id,
            LeaveApplication.company_id == company_id,
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def count_since(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        employee_id: UUID,
        since: datetime,
        exclude_statuses: tuple[str, ...] = ("CANCELLED",),
    ) -> int:
        """Monthly-cap count (`LeavePolicyVersion.max_requests_per_month`) — mirrors
        `AttendanceRegularizationRequestRepository.count_since` exactly: counts every
        application submitted since `since` except `CANCELLED` ones (a self-withdrawn
        application should not cost the employee a slot)."""
        stmt = select(LeaveApplication).where(
            LeaveApplication.company_id == company_id,
            LeaveApplication.employee_id == employee_id,
            LeaveApplication.submitted_at >= since,
            LeaveApplication.status.notin_(exclude_statuses),
        )
        return len((await session.execute(stmt)).scalars().all())

    async def sum_pending_for_type(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID, leave_type_id: UUID
    ) -> Decimal:
        """LD-15 — reserved balance for one leave type, derived live from every currently
        `SUBMITTED` application (never stored — no new ledger entry type). Used by `submit()`'s
        balance check when the resolved policy version has `reserve_balance_on_submission`
        enabled."""
        stmt = select(func.coalesce(func.sum(LeaveApplication.total_days), 0)).where(
            LeaveApplication.company_id == company_id,
            LeaveApplication.employee_id == employee_id,
            LeaveApplication.leave_type_id == leave_type_id,
            LeaveApplication.status == "SUBMITTED",
        )
        return (await session.execute(stmt)).scalar_one()

    async def sum_pending_by_leave_type(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID
    ) -> dict[UUID, Decimal]:
        """Same derivation as `sum_pending_for_type`, grouped across every leave type at once —
        backs the `/leave-balances` read (LD-15), which shows Reserved/Pending Balance for every
        type in one response rather than one call per type."""
        stmt = (
            select(
                LeaveApplication.leave_type_id,
                func.coalesce(func.sum(LeaveApplication.total_days), 0),
            )
            .where(
                LeaveApplication.company_id == company_id,
                LeaveApplication.employee_id == employee_id,
                LeaveApplication.status == "SUBMITTED",
            )
            .group_by(LeaveApplication.leave_type_id)
        )
        rows = (await session.execute(stmt)).all()
        return {r[0]: r[1] for r in rows}

    async def list_active_overlapping_other_types(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        employee_id: UUID,
        leave_type_id: UUID,
        start_date: date,
        end_date: date,
    ) -> list[UUID]:
        """LD-16 — distinct `leave_type_id`s (other than `leave_type_id`) with a currently
        active (`SUBMITTED` or `APPROVED`) application overlapping `[start_date, end_date]` for
        this employee. Backs `submit()`'s combination-rule check — `REJECTED`/`CANCELLED`
        applications are not "active" and never block a new submission."""
        stmt = (
            select(LeaveApplication.leave_type_id)
            .where(
                LeaveApplication.company_id == company_id,
                LeaveApplication.employee_id == employee_id,
                LeaveApplication.leave_type_id != leave_type_id,
                LeaveApplication.status.in_(("SUBMITTED", "APPROVED")),
                LeaveApplication.start_date <= end_date,
                LeaveApplication.end_date >= start_date,
            )
            .distinct()
        )
        return list((await session.execute(stmt)).scalars().all())

    def _filtered_conditions(
        self,
        *,
        company_id: UUID,
        visible_employee_ids: frozenset[UUID] | None,
        employee_id: UUID | None,
        date_from: date | None,
        date_to: date | None,
        status: str | None,
    ) -> list[Any] | None:
        """Shared WHERE predicates for `list_filtered`/`count_filtered` (API-01 §5) — kept
        identical between the two so pagination and the `total` it reports always agree.
        Returns `None` when an empty `visible_employee_ids` already proves the result is empty,
        letting both callers short-circuit without issuing a query."""
        if visible_employee_ids is not None and not visible_employee_ids:
            return None
        conditions = [LeaveApplication.company_id == company_id]
        if visible_employee_ids is not None:
            conditions.append(LeaveApplication.employee_id.in_(visible_employee_ids))
        if employee_id is not None:
            conditions.append(LeaveApplication.employee_id == employee_id)
        if date_from is not None:
            conditions.append(LeaveApplication.end_date >= date_from)
        if date_to is not None:
            conditions.append(LeaveApplication.start_date <= date_to)
        if status is not None:
            conditions.append(LeaveApplication.status == status)
        return conditions

    async def list_filtered(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        visible_employee_ids: frozenset[UUID] | None,
        employee_id: UUID | None,
        date_from: date | None,
        date_to: date | None,
        status: str | None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[LeaveApplication]:
        conditions = self._filtered_conditions(
            company_id=company_id,
            visible_employee_ids=visible_employee_ids,
            employee_id=employee_id,
            date_from=date_from,
            date_to=date_to,
            status=status,
        )
        if conditions is None:
            return []
        # `id` is a stable secondary key — `submitted_at` alone can tie for applications
        # submitted in the same request burst, which would make page boundaries
        # non-deterministic.
        stmt = (
            select(LeaveApplication)
            .where(*conditions)
            .order_by(LeaveApplication.submitted_at.desc(), LeaveApplication.id.desc())
        )
        if limit is not None:
            stmt = stmt.limit(limit).offset(offset)
        return list((await session.execute(stmt)).scalars().all())

    async def count_filtered(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        visible_employee_ids: frozenset[UUID] | None,
        employee_id: UUID | None,
        date_from: date | None,
        date_to: date | None,
        status: str | None,
    ) -> int:
        """Same predicates as `list_filtered`, no `ORDER BY`/`LIMIT` — the paired COUNT query for
        `GET /leave-applications`'s `pagination.total` (API-01 §5)."""
        conditions = self._filtered_conditions(
            company_id=company_id,
            visible_employee_ids=visible_employee_ids,
            employee_id=employee_id,
            date_from=date_from,
            date_to=date_to,
            status=status,
        )
        if conditions is None:
            return 0
        stmt = select(func.count()).select_from(LeaveApplication).where(*conditions)
        return int((await session.execute(stmt)).scalar_one())

    async def update(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        application_id: UUID,
        values: dict[str, Any],
        expected_version: int,
        now: datetime,
    ) -> LeaveApplication | None:
        stmt = (
            update(LeaveApplication)
            .where(
                LeaveApplication.id == application_id,
                LeaveApplication.company_id == company_id,
                LeaveApplication.version == expected_version,
            )
            .values(**values, version=expected_version + 1, updated_at=now)
            .returning(LeaveApplication)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def set_lop_days(
        self, session: AsyncSession, *, company_id: UUID, application_id: UUID, lop_days: Decimal
    ) -> LeaveApplication:
        stmt = (
            update(LeaveApplication)
            .where(
                LeaveApplication.id == application_id,
                LeaveApplication.company_id == company_id,
            )
            .values(lop_days=lop_days)
            .returning(LeaveApplication)
        )
        return (await session.execute(stmt)).scalar_one()


class LeaveApplicationDayRepository:
    async def insert_many(
        self, session: AsyncSession, *, rows: list[dict[str, Any]]
    ) -> list[LeaveApplicationDay]:
        created = [LeaveApplicationDay(**row) for row in rows]
        session.add_all(created)
        await session.flush()
        return created

    async def list_for_application(
        self, session: AsyncSession, *, company_id: UUID, leave_application_id: UUID
    ) -> list[LeaveApplicationDay]:
        stmt = (
            select(LeaveApplicationDay)
            .where(
                LeaveApplicationDay.company_id == company_id,
                LeaveApplicationDay.leave_application_id == leave_application_id,
            )
            .order_by(LeaveApplicationDay.calendar_date)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def list_for_applications(
        self, session: AsyncSession, *, company_id: UUID, leave_application_ids: list[UUID]
    ) -> list[LeaveApplicationDay]:
        """Batch form of `list_for_application` — one bounded query for every day row across a
        whole *page* of applications (API-01 §5), replacing the per-application N+1 query.
        Caller groups the flat result by `.leave_application_id`; `order_by` here is preserved
        per-application because `calendar_date` is the primary key, `leave_application_id` the
        secondary — rows for the same application stay in calendar order after grouping."""
        if not leave_application_ids:
            return []
        stmt = (
            select(LeaveApplicationDay)
            .where(
                LeaveApplicationDay.company_id == company_id,
                LeaveApplicationDay.leave_application_id.in_(leave_application_ids),
            )
            .order_by(LeaveApplicationDay.leave_application_id, LeaveApplicationDay.calendar_date)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def set_projection_id(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        day_id: UUID,
        leave_day_projection_id: UUID,
        now: datetime,
    ) -> None:
        """A plain follow-up write, not version-guarded — mirrors
        `AttendanceRegularizationRequestRepository.mark_applied`'s exact rationale: by the time
        this runs inside the same approval transaction, the day row's identity is already fixed
        and nothing else concurrently writes to it."""
        await session.execute(
            update(LeaveApplicationDay)
            .where(
                LeaveApplicationDay.id == day_id,
                LeaveApplicationDay.company_id == company_id,
            )
            .values(leave_day_projection_id=leave_day_projection_id, updated_at=now)
        )

    async def mark_lop(
        self, session: AsyncSession, *, company_id: UUID, day_ids: list[UUID], now: datetime
    ) -> None:
        """PAY-010 — flags the days an "approve with excess as LOP" decision left uncovered.
        Same not-version-guarded posture as `set_projection_id`."""
        if not day_ids:
            return
        await session.execute(
            update(LeaveApplicationDay)
            .where(
                LeaveApplicationDay.id.in_(day_ids),
                LeaveApplicationDay.company_id == company_id,
            )
            .values(is_lop=True, updated_at=now)
        )


class LeaveApplicationActionRepository:
    async def insert(
        self, session: AsyncSession, *, data: dict[str, Any]
    ) -> LeaveApplicationAction:
        row = LeaveApplicationAction(**data)
        session.add(row)
        await session.flush()
        return row

    async def list_for_application(
        self, session: AsyncSession, *, company_id: UUID, leave_application_id: UUID
    ) -> list[LeaveApplicationAction]:
        stmt = (
            select(LeaveApplicationAction)
            .where(
                LeaveApplicationAction.company_id == company_id,
                LeaveApplicationAction.leave_application_id == leave_application_id,
            )
            .order_by(LeaveApplicationAction.created_at)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def list_for_applications(
        self, session: AsyncSession, *, company_id: UUID, leave_application_ids: list[UUID]
    ) -> list[LeaveApplicationAction]:
        """Batch form of `list_for_application` — see
        `LeaveApplicationDayRepository.list_for_applications` (API-01 §5); same grouping
        contract, ordered by `leave_application_id` then `created_at`."""
        if not leave_application_ids:
            return []
        stmt = (
            select(LeaveApplicationAction)
            .where(
                LeaveApplicationAction.company_id == company_id,
                LeaveApplicationAction.leave_application_id.in_(leave_application_ids),
            )
            .order_by(
                LeaveApplicationAction.leave_application_id, LeaveApplicationAction.created_at
            )
        )
        return list((await session.execute(stmt)).scalars().all())


# ---------------------------------------------------------------------------
# Leave Combination Rule — client spec §7 (LD-16)
# ---------------------------------------------------------------------------


class LeaveCombinationRuleRepository:
    async def insert(
        self, session: AsyncSession, *, data: dict[str, Any]
    ) -> LeaveCombinationRule:
        row = LeaveCombinationRule(**data)
        session.add(row)
        await session.flush()
        return row

    async def list(
        self, session: AsyncSession, *, company_id: UUID
    ) -> list[LeaveCombinationRule]:
        stmt = (
            select(LeaveCombinationRule)
            .where(LeaveCombinationRule.company_id == company_id)
            .order_by(LeaveCombinationRule.created_at)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def get(
        self, session: AsyncSession, *, company_id: UUID, rule_id: UUID
    ) -> LeaveCombinationRule | None:
        stmt = select(LeaveCombinationRule).where(
            LeaveCombinationRule.id == rule_id, LeaveCombinationRule.company_id == company_id
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def get_by_pair(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        leave_type_id_a: UUID,
        leave_type_id_b: UUID,
    ) -> LeaveCombinationRule | None:
        """Order-independent lookup — a rule stored as (A, B) governs a submission checking
        (B, A) just as much (LD-16: the pair is unordered)."""
        stmt = select(LeaveCombinationRule).where(
            LeaveCombinationRule.company_id == company_id,
            or_(
                (LeaveCombinationRule.leave_type_id_a == leave_type_id_a)
                & (LeaveCombinationRule.leave_type_id_b == leave_type_id_b),
                (LeaveCombinationRule.leave_type_id_a == leave_type_id_b)
                & (LeaveCombinationRule.leave_type_id_b == leave_type_id_a),
            ),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def delete(self, session: AsyncSession, *, company_id: UUID, rule_id: UUID) -> bool:
        result = await session.execute(
            delete(LeaveCombinationRule).where(
                LeaveCombinationRule.id == rule_id, LeaveCombinationRule.company_id == company_id
            )
        )
        # `AsyncSession.execute` is typed as returning `Result[Any]`, which has no
        # `rowcount`; a DML statement returns a `CursorResult` at runtime. Narrowing here
        # rather than silencing the error keeps the `> 0` comparison type-checked.
        return cast(CursorResult[Any], result).rowcount > 0


# ---------------------------------------------------------------------------
# Leave Year Setting — client spec §10 (LD-20), singleton per company
# ---------------------------------------------------------------------------


class LeaveYearSettingRepository:
    async def get(
        self, session: AsyncSession, *, company_id: UUID
    ) -> LeaveYearSetting | None:
        stmt = select(LeaveYearSetting).where(LeaveYearSetting.company_id == company_id)
        return (await session.execute(stmt)).scalar_one_or_none()

    async def insert(
        self, session: AsyncSession, *, data: dict[str, Any]
    ) -> LeaveYearSetting:
        row = LeaveYearSetting(**data)
        session.add(row)
        await session.flush()
        return row

    async def update(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        values: dict[str, Any],
        expected_version: int,
        now: datetime,
    ) -> LeaveYearSetting | None:
        stmt = (
            update(LeaveYearSetting)
            .where(
                LeaveYearSetting.company_id == company_id,
                LeaveYearSetting.version == expected_version,
            )
            .values(**values, version=expected_version + 1, updated_at=now)
            .returning(LeaveYearSetting)
        )
        return (await session.execute(stmt)).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Statutory Leave Minimum — client spec §16 (LD-22), legal compliance floor
# ---------------------------------------------------------------------------


class StatutoryLeaveMinimumRepository:
    async def insert(
        self, session: AsyncSession, *, data: dict[str, Any]
    ) -> StatutoryLeaveMinimum:
        row = StatutoryLeaveMinimum(**data)
        session.add(row)
        await session.flush()
        return row

    async def list(
        self, session: AsyncSession, *, company_id: UUID
    ) -> list[StatutoryLeaveMinimum]:
        stmt = (
            select(StatutoryLeaveMinimum)
            .where(StatutoryLeaveMinimum.company_id == company_id)
            .order_by(StatutoryLeaveMinimum.created_at)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def get(
        self, session: AsyncSession, *, company_id: UUID, minimum_id: UUID
    ) -> StatutoryLeaveMinimum | None:
        stmt = select(StatutoryLeaveMinimum).where(
            StatutoryLeaveMinimum.id == minimum_id,
            StatutoryLeaveMinimum.company_id == company_id,
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def delete(
        self, session: AsyncSession, *, company_id: UUID, minimum_id: UUID
    ) -> bool:
        result = await session.execute(
            delete(StatutoryLeaveMinimum).where(
                StatutoryLeaveMinimum.id == minimum_id,
                StatutoryLeaveMinimum.company_id == company_id,
            )
        )
        # `AsyncSession.execute` is typed as returning `Result[Any]`, which has no
        # `rowcount`; a DML statement returns a `CursorResult` at runtime. Narrowing here
        # rather than silencing the error keeps the `> 0` comparison type-checked.
        return cast(CursorResult[Any], result).rowcount > 0

    async def max_min_days_per_year(
        self, session: AsyncSession, *, company_id: UUID, leave_category: str
    ) -> Decimal | None:
        """LD-22 — the strictest configured floor for this category, since the publish-time
        check doesn't know which state/establishment_type a policy will end up assigned to yet
        (fail-safe: a policy can never publish below the toughest applicable minimum)."""
        stmt = select(func.max(StatutoryLeaveMinimum.min_days_per_year)).where(
            StatutoryLeaveMinimum.company_id == company_id,
            StatutoryLeaveMinimum.leave_category == leave_category,
        )
        return (await session.execute(stmt)).scalar_one_or_none()
