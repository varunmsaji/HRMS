"""Integration tests for `GET /v1/attendance/employees/{id}/statement`.

The statement reads the same stored days and day rules as the dashboard. Under test: the day-by-day
rows and the totals, the three formats, the month rules, that a caller sees only the employees
their attendance scope allows (anyone else is the same 404 as a stranger), the tenant boundary and
the audit trail.
"""

import csv
import io
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from openpyxl import load_workbook
from sqlalchemy import text
from tests.integration.modules.attendance.test_attendance_day import _cleanup_attendance_day
from tests.integration.modules.attendance.test_attendance_summary import _company, _forget_users
from tests.integration.modules.attendance.test_company_attendance_overview import TZ, _setup
from tests.integration.modules.leave.test_leave_notifications import _login_for

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.attendance.permissions import ATTENDANCE_VIEW
from hrms.shared.business_time import business_today

pytestmark = pytest.mark.asyncio


def _url(employee_id: str | UUID) -> str:
    return f"/v1/attendance/employees/{employee_id}/statement"


def _csv(response: object) -> tuple[list[str], list[list[str]], list[str]]:
    assert response.status_code == 200, response.text  # type: ignore[attr-defined]
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8").lstrip("﻿"))))  # type: ignore[attr-defined]
    blank = rows.index([])
    return rows[0], rows[1:blank], [r[0] for r in rows[blank + 1 :]]


async def test_the_statement_lists_every_day_and_totals_the_month(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    ctx = await _company(client)
    today = business_today(TZ)
    month = today.strftime("%Y-%m")
    try:
        response = await client.get(
            _url(ctx["asha"]), headers=ctx["headers"], params={"month": month, "format": "csv"}
        )
        header, days, notes = _csv(response)
        assert header[:3] == ["Date", "Day", "Status"]
        # One row per calendar day, from the 1st to today.
        assert [d[0] for d in days] == [
            (today.replace(day=1) + timedelta(days=i)).isoformat() for i in range(today.day)
        ]
        by_date = {d[0]: d for d in days}
        asha_today = by_date[today.isoformat()]
        assert asha_today[2] == "Present" and asha_today[5] == "500" and asha_today[6] == "20"
        assert asha_today[8:10] == ["30", "10"]  # overtime found and approved
        # A day with no stored record is named, never guessed.
        assert any(d[2] == "No record" for d in days) or today.day <= 3
        in_month = [
            d for d in (today, ctx["yesterday"], ctx["week_ago"]) if d.strftime("%Y-%m") == month
        ]
        assert f"Present {len(in_month)}," in notes[1]
        assert "Late " in notes[2] and "Overtime: 30 min found, 10 min approved." in notes[3]
        assert "not of pay" in notes[4]
        assert response.headers["content-disposition"].endswith(f'_{month}.csv"')
        assert response.headers["cache-control"] == "no-store"

        # The default format is a PDF; Excel carries the same rows.
        pdf = await client.get(_url(ctx["asha"]), headers=ctx["headers"], params={"month": month})
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
        assert pdf.headers["content-type"] == "application/pdf"
        xlsx = await client.get(
            _url(ctx["asha"]), headers=ctx["headers"], params={"month": month, "format": "xlsx"}
        )
        sheet = load_workbook(io.BytesIO(xlsx.content)).active
        assert sheet is not None
        assert str(sheet.title).startswith("Attendance statement")
        subtitle = str(sheet.cell(row=2, column=1).value)
        assert subtitle.startswith("Asha (") and "," in subtitle  # name (code), company
        assert sheet.max_row >= 4 + today.day
    finally:
        await _cleanup_attendance_day(company_id=ctx["company_id"])


async def test_month_rules_scope_tenant_and_audit(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    ctx = await _company(client)
    other = await _setup(client)
    today = business_today(TZ)
    month = today.strftime("%Y-%m")
    created: list[UUID] = []
    try:
        for params in (
            {"month": "2026-13"},
            {"month": "November"},
            {"month": (today.replace(day=28) + timedelta(days=10)).strftime("%Y-%m")},  # not begun
        ):
            bad = await client.get(_url(ctx["asha"]), headers=ctx["headers"], params=params)
            assert bad.status_code == 422, (params, bad.text)
        assert (
            await client.get(
                _url(ctx["asha"]), headers=ctx["headers"], params={"month": month, "format": "docx"}
            )
        ).status_code == 422
        # A month long gone is a valid statement (all days "No record").
        old = await client.get(
            _url(ctx["asha"]), headers=ctx["headers"], params={"month": "2026-01", "format": "csv"}
        )
        _, old_days, _ = _csv(old)
        assert len(old_days) == 31 and {d[2] for d in old_days} == {"No record"}

        # Someone who sees only their own attendance gets their own statement, and no one else's.
        own, own_user = await _login_for(
            ctx["company_id"], ctx["chitra"], [ATTENDANCE_VIEW], "SELF"
        )
        created.append(own_user)
        mine = await client.get(
            _url(ctx["chitra"]), headers=own, params={"month": month, "format": "csv"}
        )
        assert mine.status_code == 200
        theirs = await client.get(_url(ctx["asha"]), headers=own, params={"month": month})
        stranger = await client.get(_url(uuid4()), headers=ctx["headers"], params={"month": month})
        assert theirs.status_code == 404 and stranger.status_code == 404
        assert theirs.json()["error"]["code"] == stranger.json()["error"]["code"]

        # Another company cannot read this company's employee.
        assert (
            await client.get(_url(ctx["asha"]), headers=other["headers"], params={"month": month})
        ).status_code == 404
        assert (await client.get(_url(ctx["asha"]), params={"month": month})).status_code in (
            401,
            403,
        )

        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(ctx["company_id"]))
            audited = (
                await session.execute(
                    text(
                        "SELECT count(*) FROM audit_log WHERE company_id = :c "
                        "AND action = 'ATTENDANCE_STATEMENT_DOWNLOADED'"
                    ),
                    {"c": ctx["company_id"]},
                )
            ).scalar_one()
        assert audited == 2  # the old month and the own statement; refusals leave no download
    finally:
        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(ctx["company_id"]))
            await session.execute(
                text("DELETE FROM audit_log WHERE actor_user_id = ANY(:ids)"), {"ids": created}
            )
            await session.commit()
        await _forget_users(ctx["company_id"], created)
        await _cleanup_attendance_day(company_id=ctx["company_id"])
        await _cleanup_attendance_day(company_id=other["company_id"])
