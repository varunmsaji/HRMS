"""Integration tests for PAY-006's pre-cutoff reminders (`attendance/reminders.py`,
`docs/audits/PAYROLL_BUSINESS_DECISIONS.md` decision 16).

Drives `IncompleteDayReminderService` directly with an explicit `today` and a capturing sender —
the Celery wrapper only resolves the company's business date and the configured sender."""

from datetime import date
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.account_invite.uac_helpers import Tenant as UacTenant
from tests.integration.modules.account_invite.uac_helpers import onboard, teardown
from tests.integration.modules.attendance.test_attendance_day import (
    _build_wired_employee,
    _cleanup_attendance_day,
    _punch,
    _register_tenant,
)
from tests.integration.modules.attendance.test_attendance_period import (
    _DAY,
    _cleanup_attendance_period,
    _create_period,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.core.config.settings import get_settings
from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.attendance.reminders import IncompleteDayReminderService, PeriodReminderResult

pytestmark = pytest.mark.asyncio


class _CapturingSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    async def send(self, *, to: str, subject: str, html_body: str, text_body: str) -> None:
        del html_body
        self.sent.append((to, subject, text_body))


async def _run(
    company_id: UUID, sender: _CapturingSender, *, today: date
) -> list[PeriodReminderResult]:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        results = await IncompleteDayReminderService(
            session, get_settings(), sender
        ).send_for_company(company_id, today=today)
        await session.commit()
    return results


async def _link_employee_to_user(
    *, company_id: UUID, employee_id: str, user_id: UUID | None
) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        await session.execute(
            text("UPDATE employee SET user_id = :uid WHERE id = :eid"),
            {"uid": str(user_id) if user_id else None, "eid": employee_id},
        )
        await session.commit()


async def test_incomplete_day_reminds_employee_and_hr_once_per_day(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    employee_id: str | None = None
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _punch(client, headers, employee_id=employee_id, hour=9, minute=0, direction="IN")
        calculated = await client.post(
            "/v1/attendance/days/calculate",
            headers=headers,
            params={"employee_id": employee_id, "date": _DAY},
        )
        assert calculated.json()["data"]["attendance_status"] == "INCOMPLETE"
        period = await _create_period(client, headers)
        # The registering admin doubles as the employee's login — one user, both emails.
        await _link_employee_to_user(
            company_id=company_id, employee_id=employee_id, user_id=user_id
        )

        # The day itself is not reminded about — it is still in progress.
        sender = _CapturingSender()
        assert await _run(company_id, sender, today=date.fromisoformat(_DAY)) == []
        assert sender.sent == []

        [result] = await _run(company_id, sender, today=date(2026, 8, 11))
        assert result.incomplete_days == 1
        assert result.employees_notified == 1
        assert result.hr_recipients == 1
        assert len(sender.sent) == 2
        reminder = next(s for s in sender.sent if s[1].startswith("Action needed"))
        assert "Mon 10 Aug 2026" in reminder[2]
        assert "/app/regularizations" in reminder[2]
        digest = next(s for s in sender.sent if not s[1].startswith("Action needed"))
        assert "1 employees have 1 incomplete attendance days" in digest[2]
        assert period["id"] in digest[2]

        # A second Beat firing the same business day (OPS-006) sends nothing.
        [again] = await _run(company_id, sender, today=date(2026, 8, 11))
        assert again.skipped_already_sent is True
        assert len(sender.sent) == 2

        # Once the period is closed, no more reminders.
        finalized = await client.post(
            f"/v1/attendance-periods/{period['id']}/finalize",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert finalized.status_code == 200, finalized.text
        assert await _run(company_id, sender, today=date(2026, 8, 12)) == []
    finally:
        if employee_id is not None:
            await _link_employee_to_user(
                company_id=company_id, employee_id=employee_id, user_id=None
            )
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_period_far_from_its_end_is_not_reminded(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _punch(client, headers, employee_id=employee_id, hour=9, minute=0, direction="IN")
        await client.post(
            "/v1/attendance/days/calculate",
            headers=headers,
            params={"employee_id": employee_id, "date": _DAY},
        )
        await _create_period(client, headers, period_end="2026-08-31")

        sender = _CapturingSender()
        lead = get_settings().attendance_incomplete_reminder_lead_days
        assert await _run(company_id, sender, today=date(2026, 8, 27 - lead)) == []
        [result] = await _run(company_id, sender, today=date(2026, 8, 31 - lead))
        # No login email: counted for HR, never sent.
        assert result.employees == 1
        assert result.employees_without_email == 1
        assert result.employees_notified == 0
        assert result.hr_recipients == 1
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_day_page_explains_the_deadline_of_an_incomplete_day(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """R-C02: the explanation's deadline is the end of the open period the reminders use."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _punch(client, headers, employee_id=employee_id, hour=9, minute=0, direction="IN")
        calculated = await client.post(
            "/v1/attendance/days/calculate",
            headers=headers,
            params={"employee_id": employee_id, "date": _DAY},
        )
        day = calculated.json()["data"]
        assert day["attendance_status"] == "INCOMPLETE"
        day_url = f"/v1/attendance/days/{day['id']}"

        # No open period yet: the action is there, the deadline is not.
        before = (await client.get(day_url, headers=headers)).json()["data"]["explanation"]
        assert before["action"]["kind"] == "REQUEST_CORRECTION"
        assert before["action"]["deadline"] is None

        period = await _create_period(client, headers)
        after = (await client.get(day_url, headers=headers)).json()["data"]["explanation"]
        assert after["action"]["deadline"] == period["period_end"]
        assert "Fix it by" in after["reason"]
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def _grant_lock_to_hr_admin(company_id: UUID) -> None:
    """HR_ADMIN does not hold ATTENDANCE.LOCK by default; a tenant that gave it to HR is the case
    where the digest used to leak company-wide counts to a branch-restricted HR."""
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        await session.execute(
            text(
                "INSERT INTO role_permission(role_id, permission_id, data_scope) "
                "SELECT r.id, p.id, 'COMPANY' FROM role r, permission p "
                "WHERE r.company_id = :c AND r.code = 'HR_ADMIN' AND p.code = 'ATTENDANCE.LOCK' "
                "ON CONFLICT DO NOTHING"
            ),
            {"c": str(company_id)},
        )
        await session.commit()


async def test_hr_digest_counts_only_the_employees_of_the_recipients_branches(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    tenant = UacTenant(headers=headers, company_id=company_id, admin_user_id=user_id, emails=[])
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        employee_branch = wired["branch"]["id"]
        await _punch(client, headers, employee_id=employee_id, hour=9, minute=0, direction="IN")
        await client.post(
            "/v1/attendance/days/calculate",
            headers=headers,
            params={"employee_id": employee_id, "date": _DAY},
        )
        await _create_period(client, headers)
        await _grant_lock_to_hr_admin(company_id)

        # `onboard` gives an HR_ADMIN a branch other than the employee's; the second one is then
        # reassigned to the employee's branch through the user-management API.
        elsewhere = await onboard(client, tenant, "HR_ADMIN")
        same = await onboard(client, tenant, "HR_ADMIN")
        put = await client.put(
            f"/v1/users/{same.user_id}/branches",
            headers=headers,
            json={"branch_ids": [employee_branch]},
        )
        assert put.status_code == 200, put.text

        sender = _CapturingSender()
        [result] = await _run(company_id, sender, today=date(2026, 8, 11))
        digests = {
            to: body for to, subject, body in sender.sent if not subject.startswith("Action needed")
        }
        # company admin (everyone) and the HR of the employee's branch; the HR of another branch
        # is not sent counts for employees they cannot open.
        assert elsewhere.email not in digests
        assert same.email in digests
        assert "1 employees have 1 incomplete attendance days" in digests[same.email]
        assert result.hr_recipients == 2
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await teardown(tenant)
