"""A company's opt-out for the attendance digest emails.

Both digests are on by default. A company switches either off here; nothing is sent to a company
that has opted out, whatever the deployment's `ATTENDANCE_DIGESTS_ENABLED` says. The deployment
switch stays the master: a company cannot turn on what the operator has not.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.audit.service import AuditService
from hrms.modules.attendance.models import AttendanceDigestSetting


class DigestSettingsRead(BaseModel):
    #: The weekday-morning note to each manager about their team.
    manager_daily_enabled: bool = True
    #: The Monday summary of last week, to people who see the whole company.
    hr_weekly_enabled: bool = True
    #: Whether this deployment sends digests at all (`ATTENDANCE_DIGESTS_ENABLED`). When it does
    #: not, the two settings above are saved but nothing is sent.
    deployment_enabled: bool
    updated_at: datetime | None = None


class DigestSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manager_daily_enabled: bool
    hr_weekly_enabled: bool


class DigestSettingsService:
    def __init__(self, session: AsyncSession, *, deployment_enabled: bool) -> None:
        self._session = session
        self._deployment_enabled = deployment_enabled

    async def get(self, company_id: UUID) -> DigestSettingsRead:
        row = await self._session.get(AttendanceDigestSetting, company_id)
        return self._read(row)

    async def is_enabled(self, company_id: UUID, kind: str) -> bool:
        """Whether the company has left `kind` (`manager_daily` or `hr_weekly`) on."""
        row = await self._session.get(AttendanceDigestSetting, company_id)
        if row is None:
            return True
        return row.manager_daily_enabled if kind == "manager_daily" else row.hr_weekly_enabled

    async def update(
        self, company_id: UUID, body: DigestSettingsUpdate, *, actor_user_id: UUID | None
    ) -> DigestSettingsRead:
        row = await self._session.get(AttendanceDigestSetting, company_id)
        before = (
            {"manager_daily_enabled": True, "hr_weekly_enabled": True}
            if row is None
            else {
                "manager_daily_enabled": row.manager_daily_enabled,
                "hr_weekly_enabled": row.hr_weekly_enabled,
            }
        )
        if row is None:
            row = AttendanceDigestSetting(
                company_id=company_id,
                manager_daily_enabled=body.manager_daily_enabled,
                hr_weekly_enabled=body.hr_weekly_enabled,
                updated_by_user_id=actor_user_id,
            )
            self._session.add(row)
        else:
            row.manager_daily_enabled = body.manager_daily_enabled
            row.hr_weekly_enabled = body.hr_weekly_enabled
            row.updated_by_user_id = actor_user_id
        await self._session.flush()
        await self._session.refresh(row)
        await AuditService().record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="ATTENDANCE_DIGEST_SETTINGS_CHANGED",
            entity_type="attendance_digest_setting",
            entity_id=company_id,
            before=before,
            after=body.model_dump(),
        )
        return self._read(row)

    def _read(self, row: AttendanceDigestSetting | None) -> DigestSettingsRead:
        if row is None:
            return DigestSettingsRead(deployment_enabled=self._deployment_enabled)
        return DigestSettingsRead(
            manager_daily_enabled=row.manager_daily_enabled,
            hr_weekly_enabled=row.hr_weekly_enabled,
            deployment_enabled=self._deployment_enabled,
            updated_at=row.updated_at,
        )
