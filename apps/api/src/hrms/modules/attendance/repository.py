"""Thin, session-passed-in repositories for the attendance module — one class per aggregate,
mirroring `organisation.repository`'s `ShiftVersionRepository` shape (identity CRUD + version
CRUD + full-replace typed children, no independent lifecycle for children)."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.modules.attendance.models import (
    AttendanceBreak,
    AttendanceDay,
    AttendancePeriod,
    AttendancePeriodAction,
    AttendancePeriodSummary,
    AttendancePolicy,
    AttendancePolicyEarlyDepartureBand,
    AttendancePolicyHourBand,
    AttendancePolicyLateBand,
    AttendancePolicyVersion,
    AttendanceRegularizationAction,
    AttendanceRegularizationRequest,
    AttendanceRegularizationRequestedPunch,
    LeaveDayProjection,
    OvertimeAction,
    OvertimePolicy,
    OvertimePolicyRateRow,
    OvertimePolicyVersion,
    OvertimeRecord,
    Punch,
    RegularizationPolicy,
    RegularizationPolicyAllowedType,
    RegularizationPolicyVersion,
    ShiftRoster,
)


class AttendancePolicyRepository:
    # -- identity --

    async def insert_policy(
        self, session: AsyncSession, *, data: dict[str, Any]
    ) -> AttendancePolicy:
        row = AttendancePolicy(**data)
        session.add(row)
        await session.flush()
        return row

    async def get_policy(
        self, session: AsyncSession, *, company_id: UUID, policy_id: UUID
    ) -> AttendancePolicy | None:
        stmt = select(AttendancePolicy).where(
            AttendancePolicy.id == policy_id,
            AttendancePolicy.company_id == company_id,
            AttendancePolicy.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def list_policies(
        self, session: AsyncSession, *, company_id: UUID
    ) -> list[AttendancePolicy]:
        stmt = (
            select(AttendancePolicy)
            .where(AttendancePolicy.company_id == company_id, AttendancePolicy.deleted_at.is_(None))
            .order_by(AttendancePolicy.name)
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
    ) -> AttendancePolicy | None:
        stmt = (
            update(AttendancePolicy)
            .where(
                AttendancePolicy.id == policy_id,
                AttendancePolicy.company_id == company_id,
                AttendancePolicy.version == expected_version,
                AttendancePolicy.deleted_at.is_(None),
            )
            .values(**values, version=expected_version + 1, updated_at=now)
            .returning(AttendancePolicy)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    # -- versions --

    async def insert_version(
        self, session: AsyncSession, *, data: dict[str, Any]
    ) -> AttendancePolicyVersion:
        row = AttendancePolicyVersion(**data)
        session.add(row)
        await session.flush()
        return row

    async def list_versions(
        self, session: AsyncSession, *, company_id: UUID, policy_id: UUID
    ) -> list[AttendancePolicyVersion]:
        stmt = (
            select(AttendancePolicyVersion)
            .where(
                AttendancePolicyVersion.company_id == company_id,
                AttendancePolicyVersion.policy_id == policy_id,
                AttendancePolicyVersion.deleted_at.is_(None),
            )
            .order_by(AttendancePolicyVersion.created_at.desc())
        )
        return list((await session.execute(stmt)).scalars().all())

    async def get_version(
        self, session: AsyncSession, *, company_id: UUID, policy_id: UUID, version_id: UUID
    ) -> AttendancePolicyVersion | None:
        stmt = select(AttendancePolicyVersion).where(
            AttendancePolicyVersion.id == version_id,
            AttendancePolicyVersion.policy_id == policy_id,
            AttendancePolicyVersion.company_id == company_id,
            AttendancePolicyVersion.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def get_versions_by_ids(
        self, session: AsyncSession, *, company_id: UUID, version_ids: set[UUID]
    ) -> list[AttendancePolicyVersion]:
        """W8 finalization validation — resolves `incomplete_at_lock_behaviour` for every
        `INCOMPLETE` day's already-snapshotted `attendance_policy_version_id` in one query,
        rather than re-resolving by date (the day's own snapshot is what actually governed it,
        WD-11)."""
        if not version_ids:
            return []
        stmt = select(AttendancePolicyVersion).where(
            AttendancePolicyVersion.company_id == company_id,
            AttendancePolicyVersion.id.in_(version_ids),
        )
        return list((await session.execute(stmt)).scalars().all())

    async def get_open_draft(
        self, session: AsyncSession, *, company_id: UUID, policy_id: UUID
    ) -> AttendancePolicyVersion | None:
        stmt = select(AttendancePolicyVersion).where(
            AttendancePolicyVersion.company_id == company_id,
            AttendancePolicyVersion.policy_id == policy_id,
            AttendancePolicyVersion.status == "DRAFT",
            AttendancePolicyVersion.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def get_current_published(
        self, session: AsyncSession, *, company_id: UUID, policy_id: UUID
    ) -> AttendancePolicyVersion | None:
        stmt = select(AttendancePolicyVersion).where(
            AttendancePolicyVersion.company_id == company_id,
            AttendancePolicyVersion.policy_id == policy_id,
            AttendancePolicyVersion.status == "PUBLISHED",
            AttendancePolicyVersion.effective_to.is_(None),
            AttendancePolicyVersion.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def find_effective_as_of(
        self, session: AsyncSession, *, company_id: UUID, policy_id: UUID, as_of: date
    ) -> AttendancePolicyVersion | None:
        stmt = select(AttendancePolicyVersion).where(
            AttendancePolicyVersion.company_id == company_id,
            AttendancePolicyVersion.policy_id == policy_id,
            AttendancePolicyVersion.status == "PUBLISHED",
            AttendancePolicyVersion.deleted_at.is_(None),
            AttendancePolicyVersion.effective_from <= as_of,
            or_(
                AttendancePolicyVersion.effective_to.is_(None),
                AttendancePolicyVersion.effective_to >= as_of,
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
    ) -> AttendancePolicyVersion | None:
        stmt = (
            update(AttendancePolicyVersion)
            .where(
                AttendancePolicyVersion.id == version_id,
                AttendancePolicyVersion.policy_id == policy_id,
                AttendancePolicyVersion.company_id == company_id,
                AttendancePolicyVersion.version == expected_version,
                AttendancePolicyVersion.deleted_at.is_(None),
            )
            .values(**values, version=expected_version + 1, updated_at=now)
            .returning(AttendancePolicyVersion)
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
    ) -> AttendancePolicyVersion | None:
        stmt = (
            update(AttendancePolicyVersion)
            .where(
                AttendancePolicyVersion.id == version_id,
                AttendancePolicyVersion.company_id == company_id,
                AttendancePolicyVersion.version == expected_version,
                AttendancePolicyVersion.deleted_at.is_(None),
            )
            .values(effective_to=effective_to, version=expected_version + 1, updated_at=now)
            .returning(AttendancePolicyVersion)
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
    ) -> AttendancePolicyVersion | None:
        stmt = (
            update(AttendancePolicyVersion)
            .where(
                AttendancePolicyVersion.id == version_id,
                AttendancePolicyVersion.policy_id == policy_id,
                AttendancePolicyVersion.company_id == company_id,
                AttendancePolicyVersion.version == expected_version,
                AttendancePolicyVersion.deleted_at.is_(None),
            )
            .values(deleted_at=now, version=expected_version + 1, updated_at=now)
            .returning(AttendancePolicyVersion)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    # -- hour bands --

    async def list_hour_bands(
        self, session: AsyncSession, *, company_id: UUID, policy_version_id: UUID
    ) -> list[AttendancePolicyHourBand]:
        stmt = (
            select(AttendancePolicyHourBand)
            .where(
                AttendancePolicyHourBand.company_id == company_id,
                AttendancePolicyHourBand.policy_version_id == policy_version_id,
            )
            .order_by(AttendancePolicyHourBand.sort_order)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def replace_hour_bands(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        policy_version_id: UUID,
        rows: list[dict[str, Any]],
    ) -> list[AttendancePolicyHourBand]:
        await session.execute(
            delete(AttendancePolicyHourBand).where(
                AttendancePolicyHourBand.company_id == company_id,
                AttendancePolicyHourBand.policy_version_id == policy_version_id,
            )
        )
        created = [AttendancePolicyHourBand(**row) for row in rows]
        session.add_all(created)
        await session.flush()
        return created

    # -- late bands --

    async def list_late_bands(
        self, session: AsyncSession, *, company_id: UUID, policy_version_id: UUID
    ) -> list[AttendancePolicyLateBand]:
        stmt = (
            select(AttendancePolicyLateBand)
            .where(
                AttendancePolicyLateBand.company_id == company_id,
                AttendancePolicyLateBand.policy_version_id == policy_version_id,
            )
            .order_by(AttendancePolicyLateBand.sort_order)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def replace_late_bands(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        policy_version_id: UUID,
        rows: list[dict[str, Any]],
    ) -> list[AttendancePolicyLateBand]:
        await session.execute(
            delete(AttendancePolicyLateBand).where(
                AttendancePolicyLateBand.company_id == company_id,
                AttendancePolicyLateBand.policy_version_id == policy_version_id,
            )
        )
        created = [AttendancePolicyLateBand(**row) for row in rows]
        session.add_all(created)
        await session.flush()
        return created

    # -- early departure bands --

    async def list_early_departure_bands(
        self, session: AsyncSession, *, company_id: UUID, policy_version_id: UUID
    ) -> list[AttendancePolicyEarlyDepartureBand]:
        stmt = (
            select(AttendancePolicyEarlyDepartureBand)
            .where(
                AttendancePolicyEarlyDepartureBand.company_id == company_id,
                AttendancePolicyEarlyDepartureBand.policy_version_id == policy_version_id,
            )
            .order_by(AttendancePolicyEarlyDepartureBand.sort_order)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def replace_early_departure_bands(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        policy_version_id: UUID,
        rows: list[dict[str, Any]],
    ) -> list[AttendancePolicyEarlyDepartureBand]:
        await session.execute(
            delete(AttendancePolicyEarlyDepartureBand).where(
                AttendancePolicyEarlyDepartureBand.company_id == company_id,
                AttendancePolicyEarlyDepartureBand.policy_version_id == policy_version_id,
            )
        )
        created = [AttendancePolicyEarlyDepartureBand(**row) for row in rows]
        session.add_all(created)
        await session.flush()
        return created


class OvertimePolicyRepository:
    async def insert_policy(self, session: AsyncSession, *, data: dict[str, Any]) -> OvertimePolicy:
        row = OvertimePolicy(**data)
        session.add(row)
        await session.flush()
        return row

    async def get_policy(
        self, session: AsyncSession, *, company_id: UUID, policy_id: UUID
    ) -> OvertimePolicy | None:
        stmt = select(OvertimePolicy).where(
            OvertimePolicy.id == policy_id,
            OvertimePolicy.company_id == company_id,
            OvertimePolicy.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def list_policies(
        self, session: AsyncSession, *, company_id: UUID
    ) -> list[OvertimePolicy]:
        stmt = (
            select(OvertimePolicy)
            .where(OvertimePolicy.company_id == company_id, OvertimePolicy.deleted_at.is_(None))
            .order_by(OvertimePolicy.name)
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
    ) -> OvertimePolicy | None:
        stmt = (
            update(OvertimePolicy)
            .where(
                OvertimePolicy.id == policy_id,
                OvertimePolicy.company_id == company_id,
                OvertimePolicy.version == expected_version,
                OvertimePolicy.deleted_at.is_(None),
            )
            .values(**values, version=expected_version + 1, updated_at=now)
            .returning(OvertimePolicy)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def insert_version(
        self, session: AsyncSession, *, data: dict[str, Any]
    ) -> OvertimePolicyVersion:
        row = OvertimePolicyVersion(**data)
        session.add(row)
        await session.flush()
        return row

    async def list_versions(
        self, session: AsyncSession, *, company_id: UUID, policy_id: UUID
    ) -> list[OvertimePolicyVersion]:
        stmt = (
            select(OvertimePolicyVersion)
            .where(
                OvertimePolicyVersion.company_id == company_id,
                OvertimePolicyVersion.policy_id == policy_id,
                OvertimePolicyVersion.deleted_at.is_(None),
            )
            .order_by(OvertimePolicyVersion.created_at.desc())
        )
        return list((await session.execute(stmt)).scalars().all())

    async def get_version(
        self, session: AsyncSession, *, company_id: UUID, policy_id: UUID, version_id: UUID
    ) -> OvertimePolicyVersion | None:
        stmt = select(OvertimePolicyVersion).where(
            OvertimePolicyVersion.id == version_id,
            OvertimePolicyVersion.policy_id == policy_id,
            OvertimePolicyVersion.company_id == company_id,
            OvertimePolicyVersion.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def get_open_draft(
        self, session: AsyncSession, *, company_id: UUID, policy_id: UUID
    ) -> OvertimePolicyVersion | None:
        stmt = select(OvertimePolicyVersion).where(
            OvertimePolicyVersion.company_id == company_id,
            OvertimePolicyVersion.policy_id == policy_id,
            OvertimePolicyVersion.status == "DRAFT",
            OvertimePolicyVersion.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def get_current_published(
        self, session: AsyncSession, *, company_id: UUID, policy_id: UUID
    ) -> OvertimePolicyVersion | None:
        stmt = select(OvertimePolicyVersion).where(
            OvertimePolicyVersion.company_id == company_id,
            OvertimePolicyVersion.policy_id == policy_id,
            OvertimePolicyVersion.status == "PUBLISHED",
            OvertimePolicyVersion.effective_to.is_(None),
            OvertimePolicyVersion.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def find_effective_as_of(
        self, session: AsyncSession, *, company_id: UUID, policy_id: UUID, as_of: date
    ) -> OvertimePolicyVersion | None:
        stmt = select(OvertimePolicyVersion).where(
            OvertimePolicyVersion.company_id == company_id,
            OvertimePolicyVersion.policy_id == policy_id,
            OvertimePolicyVersion.status == "PUBLISHED",
            OvertimePolicyVersion.deleted_at.is_(None),
            OvertimePolicyVersion.effective_from <= as_of,
            or_(
                OvertimePolicyVersion.effective_to.is_(None),
                OvertimePolicyVersion.effective_to >= as_of,
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
    ) -> OvertimePolicyVersion | None:
        stmt = (
            update(OvertimePolicyVersion)
            .where(
                OvertimePolicyVersion.id == version_id,
                OvertimePolicyVersion.policy_id == policy_id,
                OvertimePolicyVersion.company_id == company_id,
                OvertimePolicyVersion.version == expected_version,
                OvertimePolicyVersion.deleted_at.is_(None),
            )
            .values(**values, version=expected_version + 1, updated_at=now)
            .returning(OvertimePolicyVersion)
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
    ) -> OvertimePolicyVersion | None:
        stmt = (
            update(OvertimePolicyVersion)
            .where(
                OvertimePolicyVersion.id == version_id,
                OvertimePolicyVersion.company_id == company_id,
                OvertimePolicyVersion.version == expected_version,
                OvertimePolicyVersion.deleted_at.is_(None),
            )
            .values(effective_to=effective_to, version=expected_version + 1, updated_at=now)
            .returning(OvertimePolicyVersion)
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
    ) -> OvertimePolicyVersion | None:
        stmt = (
            update(OvertimePolicyVersion)
            .where(
                OvertimePolicyVersion.id == version_id,
                OvertimePolicyVersion.policy_id == policy_id,
                OvertimePolicyVersion.company_id == company_id,
                OvertimePolicyVersion.version == expected_version,
                OvertimePolicyVersion.deleted_at.is_(None),
            )
            .values(deleted_at=now, version=expected_version + 1, updated_at=now)
            .returning(OvertimePolicyVersion)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def list_rate_rows(
        self, session: AsyncSession, *, company_id: UUID, policy_version_id: UUID
    ) -> list[OvertimePolicyRateRow]:
        stmt = (
            select(OvertimePolicyRateRow)
            .where(
                OvertimePolicyRateRow.company_id == company_id,
                OvertimePolicyRateRow.policy_version_id == policy_version_id,
            )
            .order_by(OvertimePolicyRateRow.sort_order)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def replace_rate_rows(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        policy_version_id: UUID,
        rows: list[dict[str, Any]],
    ) -> list[OvertimePolicyRateRow]:
        await session.execute(
            delete(OvertimePolicyRateRow).where(
                OvertimePolicyRateRow.company_id == company_id,
                OvertimePolicyRateRow.policy_version_id == policy_version_id,
            )
        )
        created = [OvertimePolicyRateRow(**row) for row in rows]
        session.add_all(created)
        await session.flush()
        return created


class RegularizationPolicyRepository:
    async def insert_policy(
        self, session: AsyncSession, *, data: dict[str, Any]
    ) -> RegularizationPolicy:
        row = RegularizationPolicy(**data)
        session.add(row)
        await session.flush()
        return row

    async def get_policy(
        self, session: AsyncSession, *, company_id: UUID, policy_id: UUID
    ) -> RegularizationPolicy | None:
        stmt = select(RegularizationPolicy).where(
            RegularizationPolicy.id == policy_id,
            RegularizationPolicy.company_id == company_id,
            RegularizationPolicy.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def list_policies(
        self, session: AsyncSession, *, company_id: UUID
    ) -> list[RegularizationPolicy]:
        stmt = (
            select(RegularizationPolicy)
            .where(
                RegularizationPolicy.company_id == company_id,
                RegularizationPolicy.deleted_at.is_(None),
            )
            .order_by(RegularizationPolicy.name)
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
    ) -> RegularizationPolicy | None:
        stmt = (
            update(RegularizationPolicy)
            .where(
                RegularizationPolicy.id == policy_id,
                RegularizationPolicy.company_id == company_id,
                RegularizationPolicy.version == expected_version,
                RegularizationPolicy.deleted_at.is_(None),
            )
            .values(**values, version=expected_version + 1, updated_at=now)
            .returning(RegularizationPolicy)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def insert_version(
        self, session: AsyncSession, *, data: dict[str, Any]
    ) -> RegularizationPolicyVersion:
        row = RegularizationPolicyVersion(**data)
        session.add(row)
        await session.flush()
        return row

    async def list_versions(
        self, session: AsyncSession, *, company_id: UUID, policy_id: UUID
    ) -> list[RegularizationPolicyVersion]:
        stmt = (
            select(RegularizationPolicyVersion)
            .where(
                RegularizationPolicyVersion.company_id == company_id,
                RegularizationPolicyVersion.policy_id == policy_id,
                RegularizationPolicyVersion.deleted_at.is_(None),
            )
            .order_by(RegularizationPolicyVersion.created_at.desc())
        )
        return list((await session.execute(stmt)).scalars().all())

    async def get_version(
        self, session: AsyncSession, *, company_id: UUID, policy_id: UUID, version_id: UUID
    ) -> RegularizationPolicyVersion | None:
        stmt = select(RegularizationPolicyVersion).where(
            RegularizationPolicyVersion.id == version_id,
            RegularizationPolicyVersion.policy_id == policy_id,
            RegularizationPolicyVersion.company_id == company_id,
            RegularizationPolicyVersion.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def get_open_draft(
        self, session: AsyncSession, *, company_id: UUID, policy_id: UUID
    ) -> RegularizationPolicyVersion | None:
        stmt = select(RegularizationPolicyVersion).where(
            RegularizationPolicyVersion.company_id == company_id,
            RegularizationPolicyVersion.policy_id == policy_id,
            RegularizationPolicyVersion.status == "DRAFT",
            RegularizationPolicyVersion.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def get_current_published(
        self, session: AsyncSession, *, company_id: UUID, policy_id: UUID
    ) -> RegularizationPolicyVersion | None:
        stmt = select(RegularizationPolicyVersion).where(
            RegularizationPolicyVersion.company_id == company_id,
            RegularizationPolicyVersion.policy_id == policy_id,
            RegularizationPolicyVersion.status == "PUBLISHED",
            RegularizationPolicyVersion.effective_to.is_(None),
            RegularizationPolicyVersion.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def find_effective_as_of(
        self, session: AsyncSession, *, company_id: UUID, policy_id: UUID, as_of: date
    ) -> RegularizationPolicyVersion | None:
        stmt = select(RegularizationPolicyVersion).where(
            RegularizationPolicyVersion.company_id == company_id,
            RegularizationPolicyVersion.policy_id == policy_id,
            RegularizationPolicyVersion.status == "PUBLISHED",
            RegularizationPolicyVersion.deleted_at.is_(None),
            RegularizationPolicyVersion.effective_from <= as_of,
            or_(
                RegularizationPolicyVersion.effective_to.is_(None),
                RegularizationPolicyVersion.effective_to >= as_of,
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
    ) -> RegularizationPolicyVersion | None:
        stmt = (
            update(RegularizationPolicyVersion)
            .where(
                RegularizationPolicyVersion.id == version_id,
                RegularizationPolicyVersion.policy_id == policy_id,
                RegularizationPolicyVersion.company_id == company_id,
                RegularizationPolicyVersion.version == expected_version,
                RegularizationPolicyVersion.deleted_at.is_(None),
            )
            .values(**values, version=expected_version + 1, updated_at=now)
            .returning(RegularizationPolicyVersion)
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
    ) -> RegularizationPolicyVersion | None:
        stmt = (
            update(RegularizationPolicyVersion)
            .where(
                RegularizationPolicyVersion.id == version_id,
                RegularizationPolicyVersion.company_id == company_id,
                RegularizationPolicyVersion.version == expected_version,
                RegularizationPolicyVersion.deleted_at.is_(None),
            )
            .values(effective_to=effective_to, version=expected_version + 1, updated_at=now)
            .returning(RegularizationPolicyVersion)
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
    ) -> RegularizationPolicyVersion | None:
        stmt = (
            update(RegularizationPolicyVersion)
            .where(
                RegularizationPolicyVersion.id == version_id,
                RegularizationPolicyVersion.policy_id == policy_id,
                RegularizationPolicyVersion.company_id == company_id,
                RegularizationPolicyVersion.version == expected_version,
                RegularizationPolicyVersion.deleted_at.is_(None),
            )
            .values(deleted_at=now, version=expected_version + 1, updated_at=now)
            .returning(RegularizationPolicyVersion)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def list_allowed_types(
        self, session: AsyncSession, *, company_id: UUID, policy_version_id: UUID
    ) -> list[RegularizationPolicyAllowedType]:
        stmt = (
            select(RegularizationPolicyAllowedType)
            .where(
                RegularizationPolicyAllowedType.company_id == company_id,
                RegularizationPolicyAllowedType.policy_version_id == policy_version_id,
            )
            .order_by(RegularizationPolicyAllowedType.sort_order)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def replace_allowed_types(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        policy_version_id: UUID,
        rows: list[dict[str, Any]],
    ) -> list[RegularizationPolicyAllowedType]:
        await session.execute(
            delete(RegularizationPolicyAllowedType).where(
                RegularizationPolicyAllowedType.company_id == company_id,
                RegularizationPolicyAllowedType.policy_version_id == policy_version_id,
            )
        )
        created = [RegularizationPolicyAllowedType(**row) for row in rows]
        session.add_all(created)
        await session.flush()
        return created


# ---------------------------------------------------------------------------
# W5 — ShiftRoster (mutable per-date override, WD-27)
# ---------------------------------------------------------------------------


class ShiftRosterRepository:
    async def insert(self, session: AsyncSession, *, data: dict[str, Any]) -> ShiftRoster:
        row = ShiftRoster(**data)
        session.add(row)
        await session.flush()
        return row

    async def get(
        self, session: AsyncSession, *, company_id: UUID, roster_id: UUID
    ) -> ShiftRoster | None:
        stmt = select(ShiftRoster).where(
            ShiftRoster.id == roster_id,
            ShiftRoster.company_id == company_id,
            ShiftRoster.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def get_for_date(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        employee_id: UUID,
        roster_date: date,
    ) -> ShiftRoster | None:
        stmt = select(ShiftRoster).where(
            ShiftRoster.company_id == company_id,
            ShiftRoster.employee_id == employee_id,
            ShiftRoster.roster_date == roster_date,
            ShiftRoster.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def get_published_for_date(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        employee_id: UUID,
        roster_date: date,
    ) -> ShiftRoster | None:
        """Resolution read used by the calculation engine (§9.7) — only `PUBLISHED` rows may
        ever influence a live attendance calculation; a staged `DRAFT` must not (WD-27)."""
        stmt = select(ShiftRoster).where(
            ShiftRoster.company_id == company_id,
            ShiftRoster.employee_id == employee_id,
            ShiftRoster.roster_date == roster_date,
            ShiftRoster.status == "PUBLISHED",
            ShiftRoster.deleted_at.is_(None),
        )
        return (await session.execute(stmt)).scalar_one_or_none()

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
    ) -> list[ShiftRoster]:
        """`visible_employee_ids=None` means COMPANY scope (no filter), mirroring
        `PunchRepository.list_filtered`'s convention exactly."""
        conditions = [ShiftRoster.company_id == company_id, ShiftRoster.deleted_at.is_(None)]
        if visible_employee_ids is not None:
            if not visible_employee_ids:
                return []
            conditions.append(ShiftRoster.employee_id.in_(visible_employee_ids))
        if employee_id is not None:
            conditions.append(ShiftRoster.employee_id == employee_id)
        if date_from is not None:
            conditions.append(ShiftRoster.roster_date >= date_from)
        if date_to is not None:
            conditions.append(ShiftRoster.roster_date <= date_to)
        if status is not None:
            conditions.append(ShiftRoster.status == status)
        stmt = select(ShiftRoster).where(*conditions).order_by(ShiftRoster.roster_date)
        return list((await session.execute(stmt)).scalars().all())

    async def update(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        roster_id: UUID,
        values: dict[str, Any],
        expected_version: int,
        now: datetime,
    ) -> ShiftRoster | None:
        stmt = (
            update(ShiftRoster)
            .where(
                ShiftRoster.id == roster_id,
                ShiftRoster.company_id == company_id,
                ShiftRoster.version == expected_version,
                ShiftRoster.deleted_at.is_(None),
            )
            .values(**values, version=expected_version + 1, updated_at=now)
            .returning(ShiftRoster)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def soft_delete(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        roster_id: UUID,
        expected_version: int,
        now: datetime,
    ) -> ShiftRoster | None:
        stmt = (
            update(ShiftRoster)
            .where(
                ShiftRoster.id == roster_id,
                ShiftRoster.company_id == company_id,
                ShiftRoster.version == expected_version,
                ShiftRoster.deleted_at.is_(None),
            )
            .values(deleted_at=now, version=expected_version + 1, updated_at=now)
            .returning(ShiftRoster)
        )
        return (await session.execute(stmt)).scalar_one_or_none()


# ---------------------------------------------------------------------------
# W4 — Punch (immutable, append-only, WD-11)
# ---------------------------------------------------------------------------


class PunchRepository:
    async def insert(self, session: AsyncSession, *, data: dict[str, Any]) -> Punch:
        row = Punch(**data)
        session.add(row)
        await session.flush()
        return row

    async def get_by_idempotency_key(
        self, session: AsyncSession, *, company_id: UUID, idempotency_key: str
    ) -> Punch | None:
        stmt = select(Punch).where(
            Punch.company_id == company_id, Punch.idempotency_key == idempotency_key
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def list_for_employee_window(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        employee_id: UUID,
        window_start: datetime,
        window_end: datetime,
    ) -> list[Punch]:
        """Punches for one employee within `[window_start, window_end)` UTC, sorted
        chronologically — the input to pairing (architecture §19.1 step 9)."""
        stmt = (
            select(Punch)
            .where(
                Punch.company_id == company_id,
                Punch.employee_id == employee_id,
                Punch.punch_time >= window_start,
                Punch.punch_time < window_end,
            )
            .order_by(Punch.punch_time)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def list_filtered(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        visible_employee_ids: frozenset[UUID] | None,
        employee_id: UUID | None,
        date_from: date | None,
        date_to: date | None,
    ) -> list[Punch]:
        """`visible_employee_ids=None` means COMPANY scope (no filter), mirroring
        `EmployeeRepository.list_employees`'s `visible_employee_ids` convention exactly.
        `date_from`/`date_to` are UTC calendar-day bounds on `punch_time` — a coarse listing
        filter, distinct from the timezone-aware `attendance_date` the calculation engine
        computes."""
        conditions = [Punch.company_id == company_id]
        if visible_employee_ids is not None:
            if not visible_employee_ids:
                return []
            conditions.append(Punch.employee_id.in_(visible_employee_ids))
        if employee_id is not None:
            conditions.append(Punch.employee_id == employee_id)
        if date_from is not None:
            start = datetime.combine(date_from, datetime.min.time(), tzinfo=UTC)
            conditions.append(Punch.punch_time >= start)
        if date_to is not None:
            end = datetime.combine(date_to, datetime.min.time(), tzinfo=UTC) + timedelta(days=1)
            conditions.append(Punch.punch_time < end)
        stmt = select(Punch).where(*conditions).order_by(Punch.punch_time.desc())
        return list((await session.execute(stmt)).scalars().all())


# ---------------------------------------------------------------------------
# W4 — AttendanceDay (derived, recomputable, WD-10/WD-11) + AttendanceBreak (child)
# ---------------------------------------------------------------------------


class AttendanceDayRepository:
    async def insert(self, session: AsyncSession, *, data: dict[str, Any]) -> AttendanceDay:
        row = AttendanceDay(**data)
        session.add(row)
        await session.flush()
        return row

    async def get(
        self, session: AsyncSession, *, company_id: UUID, attendance_day_id: UUID
    ) -> AttendanceDay | None:
        stmt = select(AttendanceDay).where(
            AttendanceDay.id == attendance_day_id, AttendanceDay.company_id == company_id
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def get_by_employee_date(
        self, session: AsyncSession, *, company_id: UUID, employee_id: UUID, attendance_date: date
    ) -> AttendanceDay | None:
        stmt = select(AttendanceDay).where(
            AttendanceDay.company_id == company_id,
            AttendanceDay.employee_id == employee_id,
            AttendanceDay.attendance_date == attendance_date,
        )
        return (await session.execute(stmt)).scalar_one_or_none()

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
    ) -> list[AttendanceDay]:
        conditions = [AttendanceDay.company_id == company_id]
        if visible_employee_ids is not None:
            if not visible_employee_ids:
                return []
            conditions.append(AttendanceDay.employee_id.in_(visible_employee_ids))
        if employee_id is not None:
            conditions.append(AttendanceDay.employee_id == employee_id)
        if date_from is not None:
            conditions.append(AttendanceDay.attendance_date >= date_from)
        if date_to is not None:
            conditions.append(AttendanceDay.attendance_date <= date_to)
        if status is not None:
            conditions.append(AttendanceDay.attendance_status == status)
        stmt = (
            select(AttendanceDay)
            .where(*conditions)
            .order_by(AttendanceDay.attendance_date.desc(), AttendanceDay.employee_id)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def replace_derived_fields(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        attendance_day_id: UUID,
        values: dict[str, Any],
        now: datetime,
    ) -> AttendanceDay | None:
        """Full replacement of every derived/computed column — never a partial patch (WD-10).
        Excludes `is_locked`/`locked_at`/`locked_by`, which only a future lock/unlock action
        (W8) may change."""
        stmt = (
            update(AttendanceDay)
            .where(
                AttendanceDay.id == attendance_day_id,
                AttendanceDay.company_id == company_id,
                AttendanceDay.is_locked.is_(False),
            )
            .values(**values, updated_at=now)
            .returning(AttendanceDay)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def count_flagged_days_in_window(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        employee_id: UUID,
        flag: str,  # "LATE" | "EXCESS_BREAK"
        window_start: date,
        window_end: date,
    ) -> int:
        """WD-32 decisions 2/3/4 — one shared counter for both cumulative-half-day rules
        (repeated lateness, repeated excess-break days), parameterized by which per-day signal
        it's counting rather than two near-identical queries. `window_end` is inclusive; the
        caller passes the day *before* the date being recomputed (mirrors
        `OvertimeRecordRepository.sum_minutes_detected_for_range`'s own exclude-today shape) so
        this day's own fresh computation, done by the pure engine, is never double-counted."""
        condition = (
            AttendanceDay.is_late if flag == "LATE" else AttendanceDay.excess_break_minutes > 0
        )
        stmt = (
            select(func.count())
            .select_from(AttendanceDay)
            .where(
                AttendanceDay.company_id == company_id,
                AttendanceDay.employee_id == employee_id,
                AttendanceDay.attendance_date >= window_start,
                AttendanceDay.attendance_date <= window_end,
                condition,
            )
        )
        return (await session.execute(stmt)).scalar_one()

    async def set_pending_approval(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        attendance_day_id: UUID,
        is_pending_approval: bool,
        now: datetime,
    ) -> None:
        """W6 (WD-28 decision 3) — set outside `evaluate_day`'s pure calculation, the same way
        `is_locked`/`locked_at` already exist on this row with no W4 writer. Touches only
        `is_pending_approval`, leaving `is_regularized` untouched, so a reject/cancel never
        overwrites a flag an *earlier* approved request may have already set true."""
        await session.execute(
            update(AttendanceDay)
            .where(AttendanceDay.id == attendance_day_id, AttendanceDay.company_id == company_id)
            .values(is_pending_approval=is_pending_approval, updated_at=now)
        )

    async def mark_regularized(
        self, session: AsyncSession, *, company_id: UUID, attendance_day_id: UUID, now: datetime
    ) -> None:
        """Called immediately after `AttendanceDayService.calculate()` applies an approved
        correction. Does not re-check `is_locked` because `calculate()` already refused to touch
        a locked day."""
        await session.execute(
            update(AttendanceDay)
            .where(AttendanceDay.id == attendance_day_id, AttendanceDay.company_id == company_id)
            .values(is_regularized=True, is_pending_approval=False, updated_at=now)
        )

    async def mark_ot_approved(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        attendance_day_id: UUID,
        minutes_approved: int,
        comp_off_minutes: int,
        now: datetime,
    ) -> None:
        """W7 (WD-29 decision 2) — out-of-band terminal write, mirrors `mark_regularized`.
        Called once an `OvertimeRecord` reaches `APPROVED`/`REJECTED`, pushing that terminal
        decision onto the day row's payroll-facing summary fields. `ot_pending` always clears —
        a decision has been made, whatever it was."""
        await session.execute(
            update(AttendanceDay)
            .where(AttendanceDay.id == attendance_day_id, AttendanceDay.company_id == company_id)
            .values(
                ot_minutes_approved=minutes_approved,
                comp_off_minutes_earned=comp_off_minutes,
                ot_pending=False,
                updated_at=now,
            )
        )

    async def set_lock_time_incomplete_resolution(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        attendance_day_id: UUID,
        paid_day_fraction: Decimal,
        lop_fraction: Decimal,
        now: datetime,
    ) -> None:
        """Architecture §11.4 — "lock-time default for still-INCOMPLETE" governed by the day's
        own already-snapshotted `AttendancePolicyVersion.incomplete_at_lock_behaviour`
        (`TREAT_ABSENT`/`TREAT_PRESENT`). Runs once, inside `AttendancePeriodService.finalize`,
        immediately before the day is locked — never touches `attendance_status` itself (the
        architecture table only names `paid_day_fraction`/`lop_fraction` for this resolution;
        the row remains visibly `INCOMPLETE` in its own status column, its payroll-facing facts
        now resolved)."""
        await session.execute(
            update(AttendanceDay)
            .where(AttendanceDay.id == attendance_day_id, AttendanceDay.company_id == company_id)
            .values(paid_day_fraction=paid_day_fraction, lop_fraction=lop_fraction, updated_at=now)
        )

    async def bulk_lock(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        date_from: date,
        date_to: date,
        locked_by: UUID | None,
        now: datetime,
    ) -> None:
        """W8 — the only writer that ever sets `is_locked=true` (models.py's own W4 docstring
        names this exact seam). Every row already in range is locked regardless of its current
        `attendance_status`, including `CONFIG_ERROR`/`INCOMPLETE` rows — finalize's own
        validation gate is what prevents those from ever reaching this point (a `CLOSED` period
        with an unresolved exception inside it should never be reachable, not silently skipped
        here)."""
        await session.execute(
            update(AttendanceDay)
            .where(
                AttendanceDay.company_id == company_id,
                AttendanceDay.attendance_date >= date_from,
                AttendanceDay.attendance_date <= date_to,
            )
            .values(is_locked=True, locked_at=now, locked_by=locked_by, updated_at=now)
        )

    async def bulk_unlock(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        date_from: date,
        date_to: date,
        now: datetime,
    ) -> None:
        """Reopen (`ATTENDANCE.UNLOCK`) — clears the denormalized flag this same repository set
        in `bulk_lock`. Does not recompute anything; a day made mutable again is only actually
        changed by a later, ordinary `calculate()`/regularization/adjustment call."""
        await session.execute(
            update(AttendanceDay)
            .where(
                AttendanceDay.company_id == company_id,
                AttendanceDay.attendance_date >= date_from,
                AttendanceDay.attendance_date <= date_to,
                AttendanceDay.is_locked.is_(True),
            )
            .values(is_locked=False, locked_at=None, locked_by=None, updated_at=now)
        )


class AttendanceBreakRepository:
    async def replace_breaks(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        attendance_day_id: UUID,
        rows: list[dict[str, Any]],
    ) -> list[AttendanceBreak]:
        await session.execute(
            delete(AttendanceBreak).where(
                AttendanceBreak.company_id == company_id,
                AttendanceBreak.attendance_day_id == attendance_day_id,
            )
        )
        created = [AttendanceBreak(**row) for row in rows]
        session.add_all(created)
        await session.flush()
        return created

    async def list_for_day(
        self, session: AsyncSession, *, company_id: UUID, attendance_day_id: UUID
    ) -> list[AttendanceBreak]:
        stmt = select(AttendanceBreak).where(
            AttendanceBreak.company_id == company_id,
            AttendanceBreak.attendance_day_id == attendance_day_id,
        )
        return list((await session.execute(stmt)).scalars().all())


# ---------------------------------------------------------------------------
# W6 — AttendanceRegularizationRequest / RequestedPunch / Action (WD-28)
# ---------------------------------------------------------------------------


class AttendanceRegularizationRequestRepository:
    async def insert(
        self, session: AsyncSession, *, data: dict[str, Any]
    ) -> AttendanceRegularizationRequest:
        row = AttendanceRegularizationRequest(**data)
        session.add(row)
        await session.flush()
        return row

    async def get(
        self, session: AsyncSession, *, company_id: UUID, request_id: UUID
    ) -> AttendanceRegularizationRequest | None:
        stmt = select(AttendanceRegularizationRequest).where(
            AttendanceRegularizationRequest.id == request_id,
            AttendanceRegularizationRequest.company_id == company_id,
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def get_active_for_date(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        employee_id: UUID,
        attendance_date: date,
    ) -> AttendanceRegularizationRequest | None:
        """ "Active" = `SUBMITTED` — the DB-level backstop for
        `RegularizationDuplicateActiveRequestError` mirrors the partial unique index."""
        stmt = select(AttendanceRegularizationRequest).where(
            AttendanceRegularizationRequest.company_id == company_id,
            AttendanceRegularizationRequest.employee_id == employee_id,
            AttendanceRegularizationRequest.attendance_date == attendance_date,
            AttendanceRegularizationRequest.status == "SUBMITTED",
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def get_approved_for_date_and_type(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        employee_id: UUID,
        attendance_date: date,
        request_type: str,
    ) -> AttendanceRegularizationRequest | None:
        """WD-32 decisions 5/6 — looks up an `APPROVED` request of a specific type covering this
        date. Consulted fresh on every `calculate()` call from `service.py`
        (`ON_DUTY`/`EARLY_DEPARTURE_APPROVAL`), the same "re-resolved every recompute, never
        cached on the day row's inputs" posture leave projections and roster overrides already
        use."""
        stmt = select(AttendanceRegularizationRequest).where(
            AttendanceRegularizationRequest.company_id == company_id,
            AttendanceRegularizationRequest.employee_id == employee_id,
            AttendanceRegularizationRequest.attendance_date == attendance_date,
            AttendanceRegularizationRequest.request_type == request_type,
            AttendanceRegularizationRequest.status == "APPROVED",
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
        """Monthly-cap count (`RegularizationPolicyVersion.max_requests_per_month`) — counts
        every request submitted since `since` except `CANCELLED` ones (a self-withdrawn request
        should not cost the employee a slot)."""
        stmt = select(AttendanceRegularizationRequest).where(
            AttendanceRegularizationRequest.company_id == company_id,
            AttendanceRegularizationRequest.employee_id == employee_id,
            AttendanceRegularizationRequest.submitted_at >= since,
            AttendanceRegularizationRequest.status.notin_(exclude_statuses),
        )
        return len((await session.execute(stmt)).scalars().all())

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
        request_type: str | None,
    ) -> list[AttendanceRegularizationRequest]:
        conditions = [AttendanceRegularizationRequest.company_id == company_id]
        if visible_employee_ids is not None:
            if not visible_employee_ids:
                return []
            conditions.append(AttendanceRegularizationRequest.employee_id.in_(visible_employee_ids))
        if employee_id is not None:
            conditions.append(AttendanceRegularizationRequest.employee_id == employee_id)
        if date_from is not None:
            conditions.append(AttendanceRegularizationRequest.attendance_date >= date_from)
        if date_to is not None:
            conditions.append(AttendanceRegularizationRequest.attendance_date <= date_to)
        if status is not None:
            conditions.append(AttendanceRegularizationRequest.status == status)
        if request_type is not None:
            conditions.append(AttendanceRegularizationRequest.request_type == request_type)
        stmt = (
            select(AttendanceRegularizationRequest)
            .where(*conditions)
            .order_by(AttendanceRegularizationRequest.submitted_at.desc())
        )
        return list((await session.execute(stmt)).scalars().all())

    async def update(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        request_id: UUID,
        values: dict[str, Any],
        expected_version: int,
        now: datetime,
    ) -> AttendanceRegularizationRequest | None:
        stmt = (
            update(AttendanceRegularizationRequest)
            .where(
                AttendanceRegularizationRequest.id == request_id,
                AttendanceRegularizationRequest.company_id == company_id,
                AttendanceRegularizationRequest.version == expected_version,
            )
            .values(**values, version=expected_version + 1, updated_at=now)
            .returning(AttendanceRegularizationRequest)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def mark_applied(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        request_id: UUID,
        attendance_day_id: UUID | None,
        now: datetime,
    ) -> None:
        """A plain follow-up write, not version-guarded — by the time this runs, the version
        -guarded `update()` that set `status='APPROVED'` has already uniquely succeeded, so no
        other transition can race this column. `attendance_day_id` backfills the request's
        reference the first time `calculate()` produces a row for this employee-date (WD-28
        model docstring); `None` leaves the existing value untouched. Returns nothing — callers
        re-fetch via `get()` rather than reuse a `.returning()` row, since a later bulk statement
        on the same PK would otherwise expire that in-memory object's attributes outside of an
        awaited context (`MissingGreenlet` on the next plain attribute access)."""
        values: dict[str, Any] = {"applied_at": now, "updated_at": now}
        if attendance_day_id is not None:
            values["attendance_day_id"] = attendance_day_id
        await session.execute(
            update(AttendanceRegularizationRequest)
            .where(
                AttendanceRegularizationRequest.id == request_id,
                AttendanceRegularizationRequest.company_id == company_id,
            )
            .values(**values)
        )


class AttendanceRegularizationRequestedPunchRepository:
    async def insert_many(
        self, session: AsyncSession, *, rows: list[dict[str, Any]]
    ) -> list[AttendanceRegularizationRequestedPunch]:
        created = [AttendanceRegularizationRequestedPunch(**row) for row in rows]
        session.add_all(created)
        await session.flush()
        return created

    async def list_for_request(
        self, session: AsyncSession, *, company_id: UUID, request_id: UUID
    ) -> list[AttendanceRegularizationRequestedPunch]:
        stmt = (
            select(AttendanceRegularizationRequestedPunch)
            .where(
                AttendanceRegularizationRequestedPunch.company_id == company_id,
                AttendanceRegularizationRequestedPunch.request_id == request_id,
            )
            .order_by(AttendanceRegularizationRequestedPunch.sort_order)
        )
        return list((await session.execute(stmt)).scalars().all())


class AttendanceRegularizationActionRepository:
    async def insert(
        self, session: AsyncSession, *, data: dict[str, Any]
    ) -> AttendanceRegularizationAction:
        row = AttendanceRegularizationAction(**data)
        session.add(row)
        await session.flush()
        return row

    async def list_for_request(
        self, session: AsyncSession, *, company_id: UUID, request_id: UUID
    ) -> list[AttendanceRegularizationAction]:
        stmt = (
            select(AttendanceRegularizationAction)
            .where(
                AttendanceRegularizationAction.company_id == company_id,
                AttendanceRegularizationAction.request_id == request_id,
            )
            .order_by(AttendanceRegularizationAction.created_at)
        )
        return list((await session.execute(stmt)).scalars().all())


# ---------------------------------------------------------------------------
# W7 — OvertimeRecord / OvertimeAction (architecture §12, decision log WD-29)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CompOffFactRow:
    """Result shape of `OvertimeRecordRepository.list_comp_off_eligible` — the read-only fact
    Leave's L5 comp-off credit engine consumes (LEAVE_DECISION_LOG.md LD-14). Leave never writes
    to attendance tables; this is the one seam it reads through."""

    overtime_record_id: UUID
    employee_id: UUID
    attendance_date: date
    comp_off_minutes: int
    comp_off_expiry_date: date | None
    comp_off_day_length_minutes: int | None


class OvertimeRecordRepository:
    async def insert(self, session: AsyncSession, *, data: dict[str, Any]) -> OvertimeRecord:
        row = OvertimeRecord(**data)
        session.add(row)
        await session.flush()
        return row

    async def get_by_id(
        self, session: AsyncSession, *, company_id: UUID, record_id: UUID
    ) -> OvertimeRecord | None:
        stmt = select(OvertimeRecord).where(
            OvertimeRecord.id == record_id, OvertimeRecord.company_id == company_id
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def get_by_attendance_day(
        self, session: AsyncSession, *, company_id: UUID, attendance_day_id: UUID
    ) -> OvertimeRecord | None:
        stmt = select(OvertimeRecord).where(
            OvertimeRecord.company_id == company_id,
            OvertimeRecord.attendance_day_id == attendance_day_id,
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def replace_pending_for_day(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        attendance_day_id: UUID,
        values: dict[str, Any],
        now: datetime,
    ) -> OvertimeRecord | None:
        """Full replace of a `PENDING` record's fields on recompute (WD-29 decision 2) — the
        `WHERE status='PENDING'` guard means this is a no-op against a terminal row even if a
        caller forgets to check first (defence in depth; the real gate is in `service.py`).
        Returns `None` if no `PENDING` row exists for this day, in which case the caller
        `insert`s a fresh one instead."""
        stmt = (
            update(OvertimeRecord)
            .where(
                OvertimeRecord.company_id == company_id,
                OvertimeRecord.attendance_day_id == attendance_day_id,
                OvertimeRecord.status == "PENDING",
            )
            .values(**values, updated_at=now)
            .returning(OvertimeRecord)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def delete_if_pending(
        self, session: AsyncSession, *, company_id: UUID, attendance_day_id: UUID
    ) -> None:
        """A recompute that now detects zero eligible OT removes a prior `PENDING` record
        outright — there is nothing left to decide (WD-29 decision 2). Never touches a terminal
        row."""
        await session.execute(
            delete(OvertimeRecord).where(
                OvertimeRecord.company_id == company_id,
                OvertimeRecord.attendance_day_id == attendance_day_id,
                OvertimeRecord.status == "PENDING",
            )
        )

    async def update(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        record_id: UUID,
        values: dict[str, Any],
        expected_version: int,
        now: datetime,
    ) -> OvertimeRecord | None:
        stmt = (
            update(OvertimeRecord)
            .where(
                OvertimeRecord.id == record_id,
                OvertimeRecord.company_id == company_id,
                OvertimeRecord.version == expected_version,
            )
            .values(**values, version=expected_version + 1, updated_at=now)
            .returning(OvertimeRecord)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

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
    ) -> list[OvertimeRecord]:
        conditions = [OvertimeRecord.company_id == company_id]
        if visible_employee_ids is not None:
            if not visible_employee_ids:
                return []
            conditions.append(OvertimeRecord.employee_id.in_(visible_employee_ids))
        if employee_id is not None:
            conditions.append(OvertimeRecord.employee_id == employee_id)
        if date_from is not None:
            conditions.append(OvertimeRecord.attendance_date >= date_from)
        if date_to is not None:
            conditions.append(OvertimeRecord.attendance_date <= date_to)
        if status is not None:
            conditions.append(OvertimeRecord.status == status)
        stmt = (
            select(OvertimeRecord)
            .where(*conditions)
            .order_by(OvertimeRecord.attendance_date.desc(), OvertimeRecord.employee_id)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def sum_minutes_detected_for_range(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        employee_id: UUID,
        date_from: date,
        date_to: date,
        exclude_date: date | None = None,
    ) -> int:
        """W7 (WD-29 decision 3) — the weekly/monthly cap budget already consumed by sibling
        days. Counts `PENDING`+`AUTO_APPROVED`+`APPROVED` minutes (everything except
        `REJECTED`), consistent with how the existing daily cap already clamps against detected,
        not yet approved, minutes. Excludes by `attendance_date`, not `attendance_day_id` — the
        day currently being calculated may not have an `AttendanceDay` row yet on its first
        calculation."""
        conditions = [
            OvertimeRecord.company_id == company_id,
            OvertimeRecord.employee_id == employee_id,
            OvertimeRecord.attendance_date >= date_from,
            OvertimeRecord.attendance_date <= date_to,
            OvertimeRecord.status != "REJECTED",
        ]
        if exclude_date is not None:
            conditions.append(OvertimeRecord.attendance_date != exclude_date)
        stmt = select(func.coalesce(func.sum(OvertimeRecord.minutes_detected), 0)).where(
            *conditions
        )
        return int((await session.execute(stmt)).scalar_one())

    async def list_comp_off_eligible(
        self, session: AsyncSession, *, company_id: UUID
    ) -> list[CompOffFactRow]:
        """LEAVE_DECISION_LOG.md LD-14 — the read-only fact feed for Leave's L5 comp-off credit
        engine. Every terminal (`AUTO_APPROVED`/`APPROVED`) record with `comp_off_minutes > 0`,
        joined with its `OvertimePolicyVersion` for the minutes-per-day conversion basis. No
        window/date filter — comp-off volume is low (mirrors `LeaveAccrualService`'s own
        low-volume assumption, ADR-0004), and idempotency against re-crediting an already-handled
        record is the caller's (Leave's) responsibility, keyed on `reference_id`, not this
        query's."""
        stmt = (
            select(
                OvertimeRecord.id,
                OvertimeRecord.employee_id,
                OvertimeRecord.attendance_date,
                OvertimeRecord.comp_off_minutes,
                OvertimeRecord.comp_off_expiry_date,
                OvertimePolicyVersion.comp_off_day_length_minutes,
            )
            .select_from(OvertimeRecord)
            .join(
                OvertimePolicyVersion,
                OvertimePolicyVersion.id == OvertimeRecord.overtime_policy_version_id,
            )
            .where(
                OvertimeRecord.company_id == company_id,
                OvertimeRecord.status.in_(("AUTO_APPROVED", "APPROVED")),
                OvertimeRecord.comp_off_minutes > 0,
            )
            .order_by(OvertimeRecord.attendance_date)
        )
        rows = (await session.execute(stmt)).all()
        return [
            CompOffFactRow(
                overtime_record_id=r[0],
                employee_id=r[1],
                attendance_date=r[2],
                comp_off_minutes=r[3],
                comp_off_expiry_date=r[4],
                comp_off_day_length_minutes=r[5],
            )
            for r in rows
        ]


class OvertimeActionRepository:
    async def insert(self, session: AsyncSession, *, data: dict[str, Any]) -> OvertimeAction:
        row = OvertimeAction(**data)
        session.add(row)
        await session.flush()
        return row

    async def list_for_record(
        self, session: AsyncSession, *, company_id: UUID, overtime_record_id: UUID
    ) -> list[OvertimeAction]:
        stmt = (
            select(OvertimeAction)
            .where(
                OvertimeAction.company_id == company_id,
                OvertimeAction.overtime_record_id == overtime_record_id,
            )
            .order_by(OvertimeAction.created_at)
        )
        return list((await session.execute(stmt)).scalars().all())


# ---------------------------------------------------------------------------
# W8 — AttendancePeriod / AttendancePeriodAction / AttendancePeriodSummary (WD-30)
# ---------------------------------------------------------------------------


class AttendancePeriodRepository:
    async def insert(self, session: AsyncSession, *, data: dict[str, Any]) -> AttendancePeriod:
        row = AttendancePeriod(**data)
        session.add(row)
        await session.flush()
        return row

    async def get(
        self, session: AsyncSession, *, company_id: UUID, period_id: UUID
    ) -> AttendancePeriod | None:
        stmt = select(AttendancePeriod).where(
            AttendancePeriod.id == period_id, AttendancePeriod.company_id == company_id
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def list_filtered(
        self, session: AsyncSession, *, company_id: UUID, status: str | None
    ) -> list[AttendancePeriod]:
        conditions = [AttendancePeriod.company_id == company_id]
        if status is not None:
            conditions.append(AttendancePeriod.status == status)
        stmt = (
            select(AttendancePeriod)
            .where(*conditions)
            .order_by(AttendancePeriod.period_start.desc())
        )
        return list((await session.execute(stmt)).scalars().all())

    async def get_covering(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        target_date: date,
        status: str | None = None,
    ) -> AttendancePeriod | None:
        """WD-30 — the authoritative period lookup every lock-enforcement check in this module
        consults. The GiST exclusion on `attendance_period` guarantees at most one row can ever
        match, for any `target_date`, regardless of `status`."""
        conditions = [
            AttendancePeriod.company_id == company_id,
            AttendancePeriod.period_start <= target_date,
            AttendancePeriod.period_end >= target_date,
        ]
        if status is not None:
            conditions.append(AttendancePeriod.status == status)
        stmt = select(AttendancePeriod).where(*conditions)
        return (await session.execute(stmt)).scalar_one_or_none()

    async def update(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        period_id: UUID,
        values: dict[str, Any],
        expected_version: int,
        now: datetime,
    ) -> AttendancePeriod | None:
        stmt = (
            update(AttendancePeriod)
            .where(
                AttendancePeriod.id == period_id,
                AttendancePeriod.company_id == company_id,
                AttendancePeriod.version == expected_version,
            )
            .values(**values, version=expected_version + 1, updated_at=now)
            .returning(AttendancePeriod)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def record_validation(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        period_id: UUID,
        status: str,
        now: datetime,
    ) -> None:
        """Informational cache only (`last_validated_at`/`last_validation_status`), deliberately
        *not* version-guarded and does not bump `version` — `POST .../validate` is a read-mostly
        diagnostic action, not a lifecycle transition, and `finalize` never trusts this cached
        value (it always re-validates fresh inside its own version-guarded transaction)."""
        await session.execute(
            update(AttendancePeriod)
            .where(AttendancePeriod.id == period_id, AttendancePeriod.company_id == company_id)
            .values(last_validated_at=now, last_validation_status=status, updated_at=now)
        )


class AttendancePeriodActionRepository:
    async def insert(
        self, session: AsyncSession, *, data: dict[str, Any]
    ) -> AttendancePeriodAction:
        row = AttendancePeriodAction(**data)
        session.add(row)
        await session.flush()
        return row

    async def list_for_period(
        self, session: AsyncSession, *, company_id: UUID, attendance_period_id: UUID
    ) -> list[AttendancePeriodAction]:
        stmt = (
            select(AttendancePeriodAction)
            .where(
                AttendancePeriodAction.company_id == company_id,
                AttendancePeriodAction.attendance_period_id == attendance_period_id,
            )
            .order_by(AttendancePeriodAction.created_at)
        )
        return list((await session.execute(stmt)).scalars().all())


class AttendancePeriodSummaryRepository:
    async def replace_for_period(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        attendance_period_id: UUID,
        rows: list[dict[str, Any]],
    ) -> list[AttendancePeriodSummary]:
        """Full delete/recreate on every finalize (WD-30 — mirrors `AttendanceBreak`'s
        no-independent-lifecycle posture). A period can be finalized more than once across its
        lifetime (finalize -> reopen-for-correction -> finalize again), and each finalize must
        produce a fresh, correct frozen snapshot, not silently keep a stale one from a previous
        close."""
        await session.execute(
            delete(AttendancePeriodSummary).where(
                AttendancePeriodSummary.company_id == company_id,
                AttendancePeriodSummary.attendance_period_id == attendance_period_id,
            )
        )
        created = [AttendancePeriodSummary(**row) for row in rows]
        session.add_all(created)
        await session.flush()
        return created

    async def list_for_period(
        self, session: AsyncSession, *, company_id: UUID, attendance_period_id: UUID
    ) -> list[AttendancePeriodSummary]:
        stmt = (
            select(AttendancePeriodSummary)
            .where(
                AttendancePeriodSummary.company_id == company_id,
                AttendancePeriodSummary.attendance_period_id == attendance_period_id,
            )
            .order_by(AttendancePeriodSummary.employee_id)
        )
        return list((await session.execute(stmt)).scalars().all())


# ---------------------------------------------------------------------------
# W9 — LeaveDayProjection (architecture §21, decision log WD-31)
# ---------------------------------------------------------------------------


class LeaveDayProjectionRepository:
    async def insert(self, session: AsyncSession, *, data: dict[str, Any]) -> LeaveDayProjection:
        row = LeaveDayProjection(**data)
        session.add(row)
        await session.flush()
        return row

    async def get(
        self, session: AsyncSession, *, company_id: UUID, projection_id: UUID
    ) -> LeaveDayProjection | None:
        stmt = select(LeaveDayProjection).where(
            LeaveDayProjection.id == projection_id,
            LeaveDayProjection.company_id == company_id,
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def get_by_natural_key(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        employee_id: UUID,
        attendance_date: date,
        leave_application_id: UUID,
    ) -> LeaveDayProjection | None:
        """A resync of the same `leave_application_id` for the same employee-date updates this
        row in place (idempotent republish) rather than accumulating duplicates."""
        stmt = select(LeaveDayProjection).where(
            LeaveDayProjection.company_id == company_id,
            LeaveDayProjection.employee_id == employee_id,
            LeaveDayProjection.attendance_date == attendance_date,
            LeaveDayProjection.leave_application_id == leave_application_id,
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def list_active_for_employee_date(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        employee_id: UUID,
        attendance_date: date,
    ) -> list[LeaveDayProjection]:
        """The calculation-engine read (`AttendanceDayService._build_calculation_input`) —
        only `APPROVED` rows are ever visible (architecture §21)."""
        stmt = select(LeaveDayProjection).where(
            LeaveDayProjection.company_id == company_id,
            LeaveDayProjection.employee_id == employee_id,
            LeaveDayProjection.attendance_date == attendance_date,
            LeaveDayProjection.status == "APPROVED",
        )
        return list((await session.execute(stmt)).scalars().all())

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
    ) -> list[LeaveDayProjection]:
        conditions = [LeaveDayProjection.company_id == company_id]
        if visible_employee_ids is not None:
            if not visible_employee_ids:
                return []
            conditions.append(LeaveDayProjection.employee_id.in_(visible_employee_ids))
        if employee_id is not None:
            conditions.append(LeaveDayProjection.employee_id == employee_id)
        if date_from is not None:
            conditions.append(LeaveDayProjection.attendance_date >= date_from)
        if date_to is not None:
            conditions.append(LeaveDayProjection.attendance_date <= date_to)
        if status is not None:
            conditions.append(LeaveDayProjection.status == status)
        stmt = (
            select(LeaveDayProjection)
            .where(*conditions)
            .order_by(LeaveDayProjection.attendance_date)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def update(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        projection_id: UUID,
        values: dict[str, Any],
        expected_version: int,
        now: datetime,
    ) -> LeaveDayProjection | None:
        stmt = (
            update(LeaveDayProjection)
            .where(
                LeaveDayProjection.id == projection_id,
                LeaveDayProjection.company_id == company_id,
                LeaveDayProjection.version == expected_version,
            )
            .values(**values, version=expected_version + 1, updated_at=now)
            .returning(LeaveDayProjection)
        )
        return (await session.execute(stmt)).scalar_one_or_none()
