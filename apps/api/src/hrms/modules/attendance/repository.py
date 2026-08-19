"""Thin, session-passed-in repositories for the attendance module — one class per aggregate,
mirroring `organisation.repository`'s `ShiftVersionRepository` shape (identity CRUD + version
CRUD + full-replace typed children, no independent lifecycle for children)."""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.modules.attendance.models import (
    AttendanceBreak,
    AttendanceDay,
    AttendancePolicy,
    AttendancePolicyEarlyDepartureBand,
    AttendancePolicyHourBand,
    AttendancePolicyLateBand,
    AttendancePolicyVersion,
    OvertimePolicy,
    OvertimePolicyRateRow,
    OvertimePolicyVersion,
    Punch,
    RegularizationPolicy,
    RegularizationPolicyAllowedType,
    RegularizationPolicyVersion,
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
