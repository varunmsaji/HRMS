"""Integration tests for the attendance digest emails (`attendance/digests.py`).

A recording sender stands in for the mail provider, so what is under test is who is written to and
what the message says: a manager hears about their direct reports only, nothing is sent when there
is nothing to say, company figures go only to a company-wide grant, a second run for the same
business date sends nothing, and the scheduled entrypoints do nothing while the feature is off.
"""

from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.test_attendance_day import _cleanup_attendance_day
from tests.integration.modules.attendance.test_attendance_summary import _company, _forget_users
from tests.integration.modules.leave.test_leave_notifications import _login_for

from hrms.core.config.settings import get_settings
from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.attendance.digests import HrWeeklyDigestService, ManagerDailyDigestService
from hrms.modules.attendance.permissions import ATTENDANCE_VIEW, ATTENDANCE_VIEW_ALL
from hrms.shared.business_time import business_today

pytestmark = pytest.mark.asyncio

TZ = "Asia/Kolkata"


class RecordingSender:
    def __init__(self, fail_for: str | None = None) -> None:
        self.sent: list[dict[str, str]] = []
        self._fail_for = fail_for

    async def send(self, *, to: str, subject: str, html_body: str, text_body: str) -> None:
        if to == self._fail_for:
            raise RuntimeError("mailbox full")
        self.sent.append({"to": to, "subject": subject, "html": html_body, "text": text_body})


async def _run(service_class: Any, company_id: UUID, sender: RecordingSender, **kw: Any) -> Any:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        result = await service_class(session, get_settings(), sender).send_for_company(
            company_id, timezone=TZ, **kw
        )
        await session.commit()
    return result


async def _email_of(user_id: UUID) -> str:
    async with get_session_factory()() as session:
        row = await session.execute(text('SELECT email FROM "user" WHERE id = :u'), {"u": user_id})
        return str(row.scalar_one())


async def _report_to(company_id: UUID, manager: str, reports: list[str]) -> None:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        await session.execute(
            text(
                "UPDATE employee_assignment SET reporting_manager_id = :m "
                "WHERE company_id = :c AND employee_id = ANY(CAST(:r AS uuid[]))"
            ),
            {"m": manager, "c": company_id, "r": reports},
        )
        await session.commit()


async def test_a_manager_hears_about_their_own_team_only(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    ctx = await _company(client)
    cid, today = ctx["company_id"], business_today(TZ)
    created: list[UUID] = []
    try:
        # Chitra manages Asha (late today) and Bala (no punch yet); Dev is outside her team.
        _, chitra_user = await _login_for(cid, ctx["chitra"], [ATTENDANCE_VIEW], "SELF")
        created.append(chitra_user)
        await _report_to(cid, ctx["chitra"], [ctx["asha"], ctx["bala"]])

        sender = RecordingSender()
        result = await _run(ManagerDailyDigestService, cid, sender, today=today)
        assert (result.sent, result.send_failures) == (1, 0)
        (mail,) = sender.sent
        assert mail["to"] == await _email_of(chitra_user)
        assert "2 to look at" in mail["subject"]
        assert "Late (1): Asha" in mail["text"]
        assert "Not checked in yet (1): Bala" in mail["text"]
        body = mail["text"].split("\n\n", 1)[1]  # after the greeting, which names the manager
        assert "Dev" not in body and "Chitra" not in body
        assert "your team of 2" in mail["text"]

        # The same business date again sends nothing.
        again = RecordingSender()
        repeat = await _run(ManagerDailyDigestService, cid, again, today=today)
        assert repeat.skipped_already_sent and again.sent == []
    finally:
        await _forget_users(cid, created)
        await _cleanup_attendance_day(company_id=cid)


async def test_nothing_is_sent_when_there_is_nothing_to_say(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    ctx = await _company(client)
    cid, today = ctx["company_id"], business_today(TZ)
    created: list[UUID] = []
    try:
        # Dev reports to Chitra and was on time yesterday; there is no row for him today at all,
        # so for today his team has no absence, late arrival or request to report.
        _, chitra_user = await _login_for(cid, ctx["chitra"], [ATTENDANCE_VIEW], "SELF")
        created.append(chitra_user)
        await _report_to(cid, ctx["chitra"], [ctx["dev"]])
        sender = RecordingSender()
        result = await _run(ManagerDailyDigestService, cid, sender, today=today)
        assert sender.sent == [] and result.sent == 0
        # Yesterday Dev was on time and nothing else is open, so that day is quiet too.
        quiet = RecordingSender()
        await _run(ManagerDailyDigestService, cid, quiet, today=today - timedelta(days=1))
        assert quiet.sent == []
    finally:
        await _forget_users(cid, created)
        await _cleanup_attendance_day(company_id=cid)


async def test_one_failing_mailbox_does_not_stop_the_others(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    ctx = await _company(client)
    cid, today = ctx["company_id"], business_today(TZ)
    created: list[UUID] = []
    try:
        _, chitra_user = await _login_for(cid, ctx["chitra"], [ATTENDANCE_VIEW], "SELF")
        _, dev_user = await _login_for(cid, ctx["dev"], [ATTENDANCE_VIEW], "SELF")
        created += [chitra_user, dev_user]
        await _report_to(cid, ctx["chitra"], [ctx["asha"]])
        await _report_to(cid, ctx["dev"], [ctx["bala"]])
        sender = RecordingSender(fail_for=await _email_of(chitra_user))
        result = await _run(ManagerDailyDigestService, cid, sender, today=today)
        assert (result.sent, result.send_failures) == (1, 1)
        assert [m["to"] for m in sender.sent] == [await _email_of(dev_user)]
    finally:
        await _forget_users(cid, created)
        await _cleanup_attendance_day(company_id=cid)


async def test_company_figures_go_only_to_a_company_wide_grant(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    ctx = await _company(client)
    cid, today = ctx["company_id"], business_today(TZ)
    created: list[UUID] = []
    try:
        _, hr_user = await _login_for(cid, ctx["asha"], [ATTENDANCE_VIEW_ALL], "COMPANY")
        _, self_user = await _login_for(cid, ctx["bala"], [ATTENDANCE_VIEW_ALL], "SELF")
        created += [hr_user, self_user]
        # Run for the Monday after the week that holds yesterday's rows.
        yesterday = today - timedelta(days=1)
        monday = yesterday - timedelta(days=yesterday.weekday()) + timedelta(days=7)
        sender = RecordingSender()
        result = await _run(HrWeeklyDigestService, cid, sender, today=monday)
        # The company's own admin also holds a company-wide grant, so they are a recipient too.
        recipients = {m["to"] for m in sender.sent}
        assert await _email_of(hr_user) in recipients
        assert await _email_of(self_user) not in recipients  # self scope: not company figures
        assert result.sent == len(sender.sent) == result.recipients
        assert all(m["subject"].startswith("Attendance last week:") for m in sender.sent)
        assert sender.sent[0]["subject"].startswith("Attendance last week:")
        week_from = monday - timedelta(days=7)
        assert week_from.strftime("%d %b %Y") in sender.sent[0]["text"]

        again = RecordingSender()
        repeat = await _run(HrWeeklyDigestService, cid, again, today=monday)
        assert repeat.skipped_already_sent and again.sent == []
    finally:
        await _forget_users(cid, created)
        await _cleanup_attendance_day(company_id=cid)


async def test_the_scheduled_entrypoints_do_nothing_while_the_feature_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hrms.modules.attendance import tasks

    dispatched: list[str] = []
    monkeypatch.setattr(
        tasks, "dispatch_per_company", lambda task, ids: dispatched.append("x") or 1
    )
    settings = get_settings()
    assert settings.attendance_digests_enabled is False  # the shipped default
    assert tasks.run_manager_daily_digest() == 0
    assert tasks.run_hr_weekly_digest() == 0
    assert dispatched == []
