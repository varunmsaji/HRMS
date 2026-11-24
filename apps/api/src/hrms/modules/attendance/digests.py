"""Attendance digest emails: a morning note to each manager and a Monday summary to HR.

**Manager daily digest.** For every manager with direct reports (the employees whose current
assignment names them), one email when something in that team's day needs a look: an absence, a
person not checked in yet, a late arrival, a missing punch, or a request waiting for a decision.
A day with nothing to say, a weekend and a holiday send nothing. Only the manager's direct
reports are named, read through the same day rules as the dashboard (`day_classification`).

**HR weekly digest.** On Monday, last week (Monday to Sunday) against the week before, to users
who see the whole company (`ATTENDANCE.VIEW_ALL` at company scope). Someone whose grant was
narrowed to branches is not sent company-wide figures.

Both are off unless `Settings.attendance_digests_enabled`, and each run is recorded as one
`ATTENDANCE_DIGEST_SENT` audit row carrying its business date, so a second run for the same date
(Beat has no leader election, `OPS-006`) is a no-op. Delivery is at-least-once: a run that dies
after sending and before it commits can send again, as the incomplete-day reminders can.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.audit.models import AuditLog
from hrms.core.audit.service import AuditService
from hrms.core.config.settings import Settings
from hrms.core.db.models.identity import User
from hrms.core.observability.logging import get_logger
from hrms.core.rbac.service import RbacRepository, RbacService
from hrms.core.rbac.types import DataScopeLevel
from hrms.modules.attendance.day_classification import is_expected
from hrms.modules.attendance.email_templates import (
    build_hr_weekly_digest_email,
    build_manager_daily_digest_email,
)
from hrms.modules.attendance.models import AttendanceRegularizationRequest, OvertimeRecord
from hrms.modules.attendance.muster_export import display_name
from hrms.modules.attendance.permissions import ATTENDANCE_VIEW_ALL
from hrms.modules.attendance.summary import AttendanceSummaryService, SummaryFilters
from hrms.modules.employee.models import Employee, EmployeeAssignment
from hrms.modules.onboarding.email_sender import EmailSender, log_email_failure

_logger = get_logger(__name__)

DIGEST_AUDIT_ACTION = "ATTENDANCE_DIGEST_SENT"
MANAGER_DAILY = "manager_daily"
HR_WEEKLY = "hr_weekly"
#: Rows read for one manager's team in one day: far above any team, and a bound all the same.
_TEAM_ROW_LIMIT = 5_000


@dataclass
class DigestResult:
    kind: str
    skipped_already_sent: bool = False
    recipients: int = 0
    sent: int = 0
    send_failures: int = 0


class _DigestBase:
    def __init__(self, session: AsyncSession, settings: Settings, sender: EmailSender) -> None:
        self._session = session
        self._settings = settings
        self._sender = sender

    @property
    def _app_url(self) -> str:
        return f"{self._settings.web_app_base_url.rstrip('/')}/app/attendance"

    async def _already_sent(self, company_id: UUID, kind: str, as_of: date) -> bool:
        stmt = select(AuditLog.id).where(
            AuditLog.company_id == company_id,
            AuditLog.action == DIGEST_AUDIT_ACTION,
            AuditLog.after_json["kind"].astext == kind,
            AuditLog.after_json["as_of"].astext == as_of.isoformat(),
        )
        return (await self._session.execute(stmt.limit(1))).first() is not None

    async def _record(self, company_id: UUID, result: DigestResult, as_of: date) -> None:
        await AuditService().record(
            self._session,
            company_id=company_id,
            actor_user_id=None,
            action=DIGEST_AUDIT_ACTION,
            entity_type="attendance_digest",
            after={
                "kind": result.kind,
                "as_of": as_of.isoformat(),
                "recipients": result.recipients,
                "sent": result.sent,
                "send_failures": result.send_failures,
            },
        )

    async def _send(
        self, to: str, message: tuple[str, str, str], *, kind: str, company_id: UUID
    ) -> bool:
        subject, html_body, text_body = message
        try:
            await self._sender.send(
                to=to, subject=subject, html_body=html_body, text_body=text_body
            )
        except Exception as exc:  # noqa: BLE001 - one bad address must not stop the other digests
            log_email_failure(kind, exc, company_id=str(company_id))  # identifiers only (LOG-06)
            return False
        return True

    async def _pending_counts(
        self, company_id: UUID, employee_ids: frozenset[UUID] | None
    ) -> tuple[int, int]:
        """Regularization requests submitted and overtime records pending, for `employee_ids`
        (`None` is everyone)."""
        regularizations = select(func.count()).where(
            AttendanceRegularizationRequest.company_id == company_id,
            AttendanceRegularizationRequest.status == "SUBMITTED",
        )
        overtime = select(func.count()).where(
            OvertimeRecord.company_id == company_id, OvertimeRecord.status == "PENDING"
        )
        if employee_ids is not None:
            regularizations = regularizations.where(
                AttendanceRegularizationRequest.employee_id.in_(employee_ids)
            )
            overtime = overtime.where(OvertimeRecord.employee_id.in_(employee_ids))
        return (
            int((await self._session.execute(regularizations)).scalar_one()),
            int((await self._session.execute(overtime)).scalar_one()),
        )

    async def _names(self, company_id: UUID, ids: set[UUID]) -> dict[UUID, str]:
        if not ids:
            return {}
        result = await self._session.execute(
            select(
                Employee.id,
                Employee.first_name,
                Employee.middle_name,
                Employee.last_name,
                Employee.display_name,
            ).where(Employee.company_id == company_id, Employee.id.in_(ids))
        )
        return {
            r.id: display_name(r.first_name, r.middle_name, r.last_name, r.display_name)
            for r in result
        }


class ManagerDailyDigestService(_DigestBase):
    async def send_for_company(
        self, company_id: UUID, *, today: date, timezone: str
    ) -> DigestResult:
        result = DigestResult(kind=MANAGER_DAILY)
        if await self._already_sent(company_id, MANAGER_DAILY, today):
            result.skipped_already_sent = True
            return result

        teams = await self._teams(company_id, today)
        managers = await self._manager_contacts(company_id, set(teams))
        result.recipients = len(managers)
        for manager_id, (email, first_name) in managers.items():
            team = frozenset(teams[manager_id])
            message = await self._build(
                company_id, team, first_name, today=today, timezone=timezone
            )
            if message is None:
                result.recipients -= 1  # nothing to say to this manager today
                continue
            if await self._send(
                email, message, kind="attendance_manager_digest", company_id=company_id
            ):
                result.sent += 1
            else:
                result.send_failures += 1
        await self._record(company_id, result, today)
        return result

    async def _teams(self, company_id: UUID, today: date) -> dict[UUID, list[UUID]]:
        """Each manager's current, active direct reports."""
        rows = await self._session.execute(
            select(EmployeeAssignment.reporting_manager_id, EmployeeAssignment.employee_id)
            .join(Employee, Employee.id == EmployeeAssignment.employee_id)
            .where(
                EmployeeAssignment.company_id == company_id,
                EmployeeAssignment.deleted_at.is_(None),
                EmployeeAssignment.reporting_manager_id.is_not(None),
                EmployeeAssignment.effective_from <= today,
                or_(
                    EmployeeAssignment.effective_to.is_(None),
                    EmployeeAssignment.effective_to >= today,
                ),
                Employee.company_id == company_id,
                Employee.deleted_at.is_(None),
                Employee.is_active.is_(True),
            )
        )
        teams: dict[UUID, list[UUID]] = defaultdict(list)
        for manager_id, employee_id in rows:
            if manager_id is not None and manager_id != employee_id:
                teams[manager_id].append(employee_id)
        return teams

    async def _manager_contacts(
        self, company_id: UUID, manager_ids: set[UUID]
    ) -> dict[UUID, tuple[str, str | None]]:
        """Managers who can be written to: active, with a login email."""
        if not manager_ids:
            return {}
        rows = await self._session.execute(
            select(Employee.id, Employee.first_name, User.email)
            .join(User, User.id == Employee.user_id)
            .where(
                Employee.company_id == company_id,
                Employee.id.in_(manager_ids),
                Employee.deleted_at.is_(None),
                Employee.is_active.is_(True),
                User.status == "ACTIVE",
                User.email.is_not(None),
            )
        )
        return {r.id: (r.email, r.first_name) for r in rows if r.email}

    async def _build(
        self,
        company_id: UUID,
        team: frozenset[UUID],
        first_name: str | None,
        *,
        today: date,
        timezone: str,
    ) -> tuple[str, str, str] | None:
        days = await AttendanceSummaryService(self._session).report_days(
            company_id,
            date_from=today,
            date_to=today,
            filters=SummaryFilters(visible_employee_ids=team),
            today=today,
            timezone=timezone,
            limit=_TEAM_ROW_LIMIT,
        )
        # No one is expected to work (a weekend, a holiday): there is no day to report on.
        if not any(is_expected(d.bucket) for d in days):
            return None
        names = await self._names(company_id, {d.employee_id for d in days})

        def who(ids: list[UUID]) -> list[str]:
            return sorted(names.get(i, "") for i in ids if names.get(i))

        absent = [d.employee_id for d in days if d.bucket == "ABSENT"]
        not_in = [d.employee_id for d in days if d.bucket == "NOT_CHECKED_IN"]
        late = [d.employee_id for d in days if d.is_late and d.first_in is not None]
        missing = [d.employee_id for d in days if d.bucket == "INCOMPLETE"]
        regularizations, overtime = await self._pending_counts(company_id, team)
        if not (absent or not_in or late or missing or regularizations or overtime):
            return None
        return build_manager_daily_digest_email(
            first_name=first_name,
            day=today,
            team_size=len(team),
            absent=who(absent),
            not_in_yet=who(not_in),
            late=who(late),
            missing_punch=who(missing),
            pending_regularizations=regularizations,
            pending_overtime=overtime,
            app_url=self._app_url,
        )


class HrWeeklyDigestService(_DigestBase):
    async def send_for_company(
        self, company_id: UUID, *, today: date, timezone: str
    ) -> DigestResult:
        result = DigestResult(kind=HR_WEEKLY)
        # The week that has just ended, whichever day of the week this runs on.
        week_to = today - timedelta(days=today.weekday() + 1)
        week_from = week_to - timedelta(days=6)
        if await self._already_sent(company_id, HR_WEEKLY, week_from):
            result.skipped_already_sent = True
            return result

        audience = await self._audience(company_id)
        result.recipients = len(audience)
        if audience:
            message = await self._build(
                company_id, week_from=week_from, week_to=week_to, today=today, timezone=timezone
            )
            if message is not None:
                for email in audience:
                    if await self._send(
                        email, message, kind="attendance_hr_weekly_digest", company_id=company_id
                    ):
                        result.sent += 1
                    else:
                        result.send_failures += 1
        await self._record(company_id, result, week_from)
        return result

    async def _audience(self, company_id: UUID) -> list[str]:
        """Active users with a login email who see attendance for the whole company."""
        user_ids = await RbacRepository().list_user_ids_with_permission(
            self._session, company_id=company_id, code=ATTENDANCE_VIEW_ALL
        )
        if not user_ids:
            return []
        users = (
            await self._session.execute(
                select(User.id, User.email).where(
                    User.id.in_(user_ids), User.status == "ACTIVE", User.email.is_not(None)
                )
            )
        ).all()
        rbac = RbacService(self._session)
        audience: list[str] = []
        for user_id, email in users:
            if not email:
                continue
            scope = await rbac.resolve_data_scope(user_id, company_id, ATTENDANCE_VIEW_ALL)
            # Company-wide figures go only to a company-wide grant, never to a branch-narrowed one.
            if DataScopeLevel.COMPANY in scope.levels and not scope.company_grant_restricted:
                audience.append(email)
        return audience

    async def _build(
        self, company_id: UUID, *, week_from: date, week_to: date, today: date, timezone: str
    ) -> tuple[str, str, str] | None:
        service = AttendanceSummaryService(self._session)
        week = await service.summary(
            company_id, date_from=week_from, date_to=week_to, today=today, timezone=timezone
        )
        if week.row_count == 0:
            return None  # nothing was calculated for the week: a report of zeros would mislead
        earlier = await service.summary(
            company_id,
            date_from=week_from - timedelta(days=7),
            date_to=week_to - timedelta(days=7),
            today=today,
            timezone=timezone,
        )
        regularizations, overtime = await self._pending_counts(company_id, None)
        names = await self._names(company_id, {f.employee_id for f in week.frequent_late})
        return build_hr_weekly_digest_email(
            week_from=week_from,
            week_to=week_to,
            rate=_week_rate(week.daily),
            previous_rate=_week_rate(earlier.daily) if earlier.row_count else None,
            absent_days=sum(d.absent for d in week.daily),
            leave_days=sum(d.leave for d in week.daily),
            late_arrivals=week.punctuality.late,
            on_time_rate=week.punctuality.on_time_rate,
            frequent_late=[
                names[f.employee_id] for f in week.frequent_late if f.employee_id in names
            ],
            pending_regularizations=regularizations,
            pending_overtime=overtime,
            app_url=self._app_url,
        )


def _week_rate(daily: list[Any]) -> float | None:
    """Weighted present over expected across the week (a half day counts 0.5), 0-100."""
    expected = sum(d.expected for d in daily)
    if expected == 0:
        return None
    return float(sum(d.present + 0.5 * d.half_day for d in daily) / expected * 100)


__all__ = ["DigestResult", "HrWeeklyDigestService", "ManagerDailyDigestService"]
