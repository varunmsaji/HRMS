"""Integration tests for a company's opt-out of the attendance digest emails.

`GET/PUT /v1/attendance/digest-settings` and what the opt-out does to the two digests: a company
that switches one off receives nothing of it, however the deployment is configured, and nothing
else about the other digest changes. Also the table's row-level security.
"""

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.test_attendance_day import _cleanup_attendance_day
from tests.integration.modules.attendance.test_attendance_digests import (
    RecordingSender,
    _email_of,
    _report_to,
    _run,
)
from tests.integration.modules.attendance.test_attendance_summary import _company, _forget_users
from tests.integration.modules.attendance.test_company_attendance_overview import TZ, _setup
from tests.integration.modules.leave.test_leave_notifications import _login_for

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.attendance.digests import HrWeeklyDigestService, ManagerDailyDigestService
from hrms.modules.attendance.permissions import ATTENDANCE_VIEW, ATTENDANCE_VIEW_ALL
from hrms.shared.business_time import business_today

pytestmark = pytest.mark.asyncio

URL = "/v1/attendance/digest-settings"


async def _cleanup(*company_ids: UUID) -> None:
    """Removes what a test created for its companies: the saved digest settings, then the same
    attendance/master data every other attendance test removes. Without this the legal entities
    (and the rest) stay behind, and a test that lists them across the database - the integration
    runner connects as a role that bypasses row-level security - sees other tests' rows."""
    for company_id in company_ids:
        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(company_id))
            await session.execute(
                text("DELETE FROM attendance_digest_setting WHERE company_id = :c"),
                {"c": company_id},
            )
            await session.commit()
        await _cleanup_attendance_day(company_id=company_id)


async def _put(client: AsyncClient, headers: dict[str, str], manager: bool, hr: bool) -> Any:
    return await client.put(
        URL, headers=headers, json={"manager_daily_enabled": manager, "hr_weekly_enabled": hr}
    )


async def test_the_defaults_are_both_on_and_a_change_is_saved_and_audited(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    ctx = await _setup(client)
    other = await _setup(client)
    try:
        first = (await client.get(URL, headers=ctx["headers"])).json()["data"]
        assert first["manager_daily_enabled"] is True and first["hr_weekly_enabled"] is True
        assert first["deployment_enabled"] is False  # the shipped default
        assert first["updated_at"] is None  # nothing saved yet

        saved = await _put(client, ctx["headers"], False, True)
        assert saved.status_code == 200, saved.text
        body = saved.json()["data"]
        assert (body["manager_daily_enabled"], body["hr_weekly_enabled"]) == (False, True)
        assert body["updated_at"] is not None
        assert (await client.get(URL, headers=ctx["headers"])).json()["data"] == body

        # Saving again changes the same row; saving the same values again is harmless.
        assert (await _put(client, ctx["headers"], False, False)).status_code == 200
        assert (await _put(client, ctx["headers"], False, False)).status_code == 200
        after = (await client.get(URL, headers=ctx["headers"])).json()["data"]
        assert (after["manager_daily_enabled"], after["hr_weekly_enabled"]) == (False, False)

        # Another company is untouched.
        theirs = (await client.get(URL, headers=other["headers"])).json()["data"]
        assert theirs["manager_daily_enabled"] is True and theirs["hr_weekly_enabled"] is True

        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(ctx["company_id"]))
            rows = (
                await session.execute(
                    text(
                        "SELECT before_json, after_json FROM audit_log WHERE company_id = :c "
                        "AND action = 'ATTENDANCE_DIGEST_SETTINGS_CHANGED' ORDER BY occurred_at"
                    ),
                    {"c": ctx["company_id"]},
                )
            ).all()
        assert len(rows) == 3
        assert rows[0].before_json == {"manager_daily_enabled": True, "hr_weekly_enabled": True}
        assert rows[0].after_json == {"manager_daily_enabled": False, "hr_weekly_enabled": True}
    finally:
        await _cleanup(ctx["company_id"], other["company_id"])


async def test_only_someone_who_manages_attendance_policy_can_read_or_change_it(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    ctx = await _company(client)
    created: list[UUID] = []
    try:
        viewer, viewer_user = await _login_for(
            ctx["company_id"], ctx["asha"], [ATTENDANCE_VIEW], "COMPANY"
        )
        created.append(viewer_user)
        assert (await client.get(URL, headers=viewer)).status_code == 403
        assert (await _put(client, viewer, False, False)).status_code == 403
        assert (await client.get(URL)).status_code in (401, 403)

        bad = await client.put(URL, headers=ctx["headers"], json={"manager_daily_enabled": False})
        assert bad.status_code == 422  # both settings are always given
        extra = await client.put(
            URL,
            headers=ctx["headers"],
            json={"manager_daily_enabled": True, "hr_weekly_enabled": True, "other": 1},
        )
        assert extra.status_code == 422
    finally:
        await _forget_users(ctx["company_id"], created)
        await _cleanup_attendance_day(company_id=ctx["company_id"])


async def test_an_opted_out_company_receives_that_digest_and_only_that_one(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    ctx = await _company(client)
    cid, today = ctx["company_id"], business_today(TZ)
    created: list[UUID] = []
    try:
        _, chitra_user = await _login_for(cid, ctx["chitra"], [ATTENDANCE_VIEW], "SELF")
        _, hr_user = await _login_for(cid, ctx["asha"], [ATTENDANCE_VIEW_ALL], "COMPANY")
        created += [chitra_user, hr_user]
        await _report_to(cid, ctx["chitra"], [ctx["asha"], ctx["bala"]])

        # Managers opted out: nothing for them, and the run is not recorded as sent.
        assert (await _put(client, ctx["headers"], False, True)).status_code == 200
        off = RecordingSender()
        result = await _run(ManagerDailyDigestService, cid, off, today=today)
        assert result.skipped_opted_out and off.sent == [] and result.sent == 0

        # The HR digest still goes out.
        hr = RecordingSender()
        hr_result = await _run(HrWeeklyDigestService, cid, hr, today=today)
        assert not hr_result.skipped_opted_out
        assert await _email_of(hr_user) in {m["to"] for m in hr.sent}

        # Switching managers back on sends their digest the same day (opting out recorded nothing).
        assert (await _put(client, ctx["headers"], True, False)).status_code == 200
        on = RecordingSender()
        again = await _run(ManagerDailyDigestService, cid, on, today=today)
        assert not again.skipped_opted_out and again.sent == 1
        assert [m["to"] for m in on.sent] == [await _email_of(chitra_user)]

        # And now HR is the one opted out.
        hr_off = RecordingSender()
        hr_again = await _run(HrWeeklyDigestService, cid, hr_off, today=today)
        assert hr_again.skipped_opted_out and hr_off.sent == []
    finally:
        await _forget_users(cid, created)
        await _cleanup(cid)


async def test_the_table_is_tenant_isolated(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    ctx = await _setup(client)
    try:
        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(ctx["company_id"]))
            flags = (
                await session.execute(
                    text(
                        "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                        "WHERE relname = 'attendance_digest_setting'"
                    )
                )
            ).one()
            policy = (
                await session.execute(
                    text(
                        "SELECT count(*) FROM pg_policies "
                        "WHERE tablename = 'attendance_digest_setting' "
                        "AND policyname = 'tenant_isolation'"
                    )
                )
            ).scalar_one()
        assert tuple(flags) == (True, True)
        assert policy == 1
    finally:
        await _cleanup(ctx["company_id"])
