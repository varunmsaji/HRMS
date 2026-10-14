"""PAY-006 — pre-cutoff reminders for unresolved INCOMPLETE days
(`docs/audits/PAYROLL_BUSINESS_DECISIONS.md` decision 16: "reminders before cutoff; unresolved
at close → absent (LOP)").

For each attendance period that is not yet `CLOSED` and whose end is at most
`Settings.attendance_incomplete_reminder_lead_days` away (or already past), every employee with
an unlocked `INCOMPLETE` day in `[period_start, min(period_end, today - 1)]` gets one email
listing those dates, and every user holding `ATTENDANCE.LOCK` gets one digest per period. Today
itself is excluded — a day still in progress is routinely incomplete.

Runs once a day (`attendance.run_incomplete_reminders`). Beat has no leader election
(`OPS-006`), so each period's run is recorded as one `ATTENDANCE_INCOMPLETE_REMINDERS_SENT`
audit row carrying its business date, and a second run on the same date is a no-op."""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.audit.models import AuditLog
from hrms.core.audit.service import AuditService
from hrms.core.config.settings import Settings
from hrms.core.db.models.identity import User
from hrms.core.observability.logging import get_logger
from hrms.core.rbac.service import RbacRepository
from hrms.modules.attendance.email_templates import (
    build_incomplete_days_hr_digest_email,
    build_incomplete_days_reminder_email,
)
from hrms.modules.attendance.models import AttendanceDay, AttendancePeriod
from hrms.modules.attendance.permissions import ATTENDANCE_LOCK
from hrms.modules.employee.models import Employee, Employment
from hrms.modules.onboarding.email_sender import EmailSender, log_email_failure

_logger = get_logger(__name__)

REMINDER_AUDIT_ACTION = "ATTENDANCE_INCOMPLETE_REMINDERS_SENT"


@dataclass
class PeriodReminderResult:
    period_id: UUID
    skipped_already_sent: bool = False
    incomplete_days: int = 0
    employees: int = 0
    employees_notified: int = 0
    employees_without_email: int = 0
    hr_recipients: int = 0
    send_failures: int = 0
    notified_employee_ids: list[UUID] = field(default_factory=list)


class IncompleteDayReminderService:
    def __init__(self, session: AsyncSession, settings: Settings, sender: EmailSender) -> None:
        self._session = session
        self._settings = settings
        self._sender = sender

    async def send_for_company(
        self, company_id: UUID, *, today: date
    ) -> list[PeriodReminderResult]:
        lead_days = self._settings.attendance_incomplete_reminder_lead_days
        periods = (
            (
                await self._session.execute(
                    select(AttendancePeriod)
                    .where(
                        AttendancePeriod.company_id == company_id,
                        AttendancePeriod.status != "CLOSED",
                        AttendancePeriod.period_start < today,
                        AttendancePeriod.period_end <= today + timedelta(days=lead_days),
                    )
                    .order_by(AttendancePeriod.period_start)
                )
            )
            .scalars()
            .all()
        )
        return [await self._send_for_period(company_id, period, today=today) for period in periods]

    async def _send_for_period(
        self, company_id: UUID, period: AttendancePeriod, *, today: date
    ) -> PeriodReminderResult:
        result = PeriodReminderResult(period_id=period.id)
        if await self._already_sent(company_id, period.id, today):
            result.skipped_already_sent = True
            return result

        last_day = min(period.period_end, today - timedelta(days=1))
        rows = (
            await self._session.execute(
                select(
                    AttendanceDay.employee_id,
                    AttendanceDay.attendance_date,
                    Employee.first_name,
                    User.email,
                    User.status,
                )
                .join(Employee, Employee.id == AttendanceDay.employee_id)
                .outerjoin(User, User.id == Employee.user_id)
                .where(
                    AttendanceDay.company_id == company_id,
                    AttendanceDay.attendance_status == "INCOMPLETE",
                    AttendanceDay.is_locked.is_(False),
                    AttendanceDay.attendance_date >= period.period_start,
                    AttendanceDay.attendance_date <= last_day,
                    # Decision 14 — only this legal entity's employees. INCOMPLETE is only ever
                    # computed for an employed day, so the covering employment decides.
                    exists().where(
                        Employment.company_id == company_id,
                        Employment.employee_id == AttendanceDay.employee_id,
                        Employment.legal_entity_id == period.legal_entity_id,
                        Employment.deleted_at.is_(None),
                        Employment.joining_date <= AttendanceDay.attendance_date,
                        or_(
                            Employment.last_working_day.is_(None),
                            Employment.last_working_day >= AttendanceDay.attendance_date,
                        ),
                    ),
                )
                .order_by(AttendanceDay.employee_id, AttendanceDay.attendance_date)
            )
        ).all()

        by_employee: dict[UUID, dict[str, Any]] = {}
        for employee_id, attendance_date, first_name, email, user_status in rows:
            entry = by_employee.setdefault(
                employee_id,
                {
                    "first_name": first_name,
                    "email": email if user_status == "ACTIVE" else None,
                    "dates": [],
                },
            )
            entry["dates"].append(attendance_date)

        result.incomplete_days = len(rows)
        result.employees = len(by_employee)
        if not by_employee:
            return result

        period_label = period.label or (
            f"{period.period_start.isoformat()} to {period.period_end.isoformat()}"
        )
        base_url = self._settings.web_app_base_url.rstrip("/")
        for employee_id, entry in by_employee.items():
            if not entry["email"]:
                result.employees_without_email += 1
                continue
            subject, html_body, text_body = build_incomplete_days_reminder_email(
                first_name=entry["first_name"],
                period_label=period_label,
                period_end=period.period_end,
                incomplete_dates=entry["dates"],
                regularizations_url=f"{base_url}/app/regularizations",
            )
            if await self._send(
                entry["email"],
                subject,
                html_body,
                text_body,
                kind="attendance_incomplete_reminder",
                ids={"company_id": str(company_id), "employee_id": str(employee_id)},
            ):
                result.employees_notified += 1
                result.notified_employee_ids.append(employee_id)
            else:
                result.send_failures += 1

        hr_user_ids = await RbacRepository().list_user_ids_with_permission(
            self._session, company_id=company_id, code=ATTENDANCE_LOCK
        )
        hr_emails: list[str] = []
        if hr_user_ids:
            hr_emails = [
                email
                for email in (
                    await self._session.execute(
                        select(User.email).where(
                            User.id.in_(hr_user_ids),
                            User.status == "ACTIVE",
                            User.email.is_not(None),
                        )
                    )
                ).scalars()
                if email
            ]
        subject, html_body, text_body = build_incomplete_days_hr_digest_email(
            period_label=period_label,
            period_end=period.period_end,
            employee_count=result.employees,
            incomplete_day_count=result.incomplete_days,
            employees_without_email=result.employees_without_email,
            period_url=f"{base_url}/app/attendance-periods/{period.id}",
        )
        for email in hr_emails:
            if await self._send(
                email,
                subject,
                html_body,
                text_body,
                kind="attendance_incomplete_hr_digest",
                ids={"company_id": str(company_id), "period_id": str(period.id)},
            ):
                result.hr_recipients += 1
            else:
                result.send_failures += 1

        await AuditService().record(
            self._session,
            company_id=company_id,
            actor_user_id=None,
            action=REMINDER_AUDIT_ACTION,
            entity_type="attendance_period",
            entity_id=period.id,
            after={
                "as_of": today.isoformat(),
                "incomplete_days": result.incomplete_days,
                "employees": result.employees,
                "employees_notified": result.employees_notified,
                "employees_without_email": result.employees_without_email,
                "hr_recipients": result.hr_recipients,
                "send_failures": result.send_failures,
            },
        )
        return result

    async def _already_sent(self, company_id: UUID, period_id: UUID, today: date) -> bool:
        stmt = select(AuditLog.id).where(
            AuditLog.company_id == company_id,
            AuditLog.action == REMINDER_AUDIT_ACTION,
            AuditLog.entity_id == period_id,
            AuditLog.after_json["as_of"].astext == today.isoformat(),
        )
        return (await self._session.execute(stmt.limit(1))).first() is not None

    async def _send(
        self,
        to: str,
        subject: str,
        html_body: str,
        text_body: str,
        *,
        kind: str,
        ids: dict[str, str],
    ) -> bool:
        try:
            await self._sender.send(
                to=to, subject=subject, html_body=html_body, text_body=text_body
            )
        except Exception as exc:  # noqa: BLE001 - one bad address must not stop the other reminders
            # LOG-06 — identifiers only; the recipient address used to be logged here.
            log_email_failure(kind, exc, **ids)
            return False
        return True
