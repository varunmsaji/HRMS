"""Integration tests for `GET /v1/attendance/reports/{report}/export`.

The reports read the same `attendance_day` rows and bucket rules as `/attendance/summary`, so the
rows are inserted directly (overtime records with a minimal draft policy). Under test: each of
the five files' columns and figures, the filters, the window rules, the caller's scope, the tenant
boundary and the audit trail.
"""

import csv
import io
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.test_attendance_day import _cleanup_attendance_day
from tests.integration.modules.attendance.test_attendance_summary import (
    _company,
    _forget_users,
)
from tests.integration.modules.attendance.test_company_attendance_overview import TZ, _setup
from tests.integration.modules.leave.test_leave_notifications import _login_for

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.attendance.models import (
    OvertimePolicy,
    OvertimePolicyVersion,
    OvertimeRecord,
)
from hrms.modules.attendance.permissions import ATTENDANCE_VIEW
from hrms.shared.business_time import business_today

pytestmark = pytest.mark.asyncio


def _url(report: str) -> str:
    return f"/v1/attendance/reports/{report}/export"


def _table(response: Any) -> tuple[list[str], list[dict[str, str]]]:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["cache-control"] == "no-store"
    assert "attachment" in response.headers["content-disposition"]
    body = response.content.decode("utf-8")
    assert body.startswith("﻿")
    rows = list(csv.reader(io.StringIO(body.lstrip("﻿"))))
    return rows[0], [dict(zip(rows[0], r, strict=True)) for r in rows[1:]]


async def _add_overtime(ctx: dict[str, Any]) -> None:
    """Asha's overtime today: 30 minutes found, 10 approved, still pending."""
    cid: UUID = ctx["company_id"]
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(cid))
        day_id = (
            await session.execute(
                text(
                    "SELECT id FROM attendance_day WHERE company_id = :c AND employee_id = :e "
                    "AND attendance_date = :d"
                ),
                {"c": cid, "e": UUID(ctx["asha"]), "d": ctx["today"]},
            )
        ).scalar_one()
        policy, version = uuid4(), uuid4()
        session.add(OvertimePolicy(id=policy, company_id=cid, name="Test OT"))
        await session.flush()
        session.add(
            OvertimePolicyVersion(
                id=version, company_id=cid, policy_id=policy, status="DRAFT", version=1
            )
        )
        await session.flush()
        session.add(
            OvertimeRecord(
                id=uuid4(),
                company_id=cid,
                employee_id=UUID(ctx["asha"]),
                attendance_day_id=day_id,
                attendance_date=ctx["today"],
                overtime_policy_version_id=version,
                day_class="NORMAL",
                minutes_detected=30,
                minutes_approved=10,
                status="PENDING",
                approval_chain="MANAGER",
            )
        )
        await session.commit()


async def _cleanup_overtime(company_id: UUID) -> None:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        for table in ("overtime_record", "overtime_policy_version", "overtime_policy"):
            await session.execute(
                text(f"DELETE FROM {table} WHERE company_id = :c"),  # noqa: S608
                {"c": company_id},
            )
        await session.commit()


async def test_each_report_has_its_columns_and_figures(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    ctx = await _company(client)
    window = {"date_from": ctx["week_ago"].isoformat(), "date_to": ctx["today"].isoformat()}
    try:
        await _add_overtime(ctx)
        get = lambda report, **extra: client.get(  # noqa: E731
            _url(report), headers=ctx["headers"], params={**window, **extra}
        )

        header, rows = _table(await get("daily"))
        assert header == [
            "Date", "Employee", "Code", "Status", "In", "Out", "Worked (min)",
            "Late (min)", "Early out (min)",
        ]  # fmt: skip
        assert len(rows) == 10  # every stored day in the window
        assert [r["Date"] for r in rows] == sorted(r["Date"] for r in rows)
        asha_today = next(
            r for r in rows if r["Employee"] == "Asha" and r["Date"] == ctx["today"].isoformat()
        )
        assert asha_today["Status"] == "Present"
        assert asha_today["Late (min)"] == "20" and asha_today["Worked (min)"] == "500"
        assert asha_today["In"] != "" and asha_today["Out"] != ""
        bala_today = next(
            r for r in rows if r["Employee"] == "Bala" and r["Date"] == ctx["today"].isoformat()
        )
        assert bala_today["Status"] == "Not checked in yet" and bala_today["In"] == ""

        header, rows = _table(await get("late-early"))
        assert header == ["Date", "Employee", "Code", "Late (min)", "Early out (min)"]
        assert sorted((r["Employee"], r["Late (min)"]) for r in rows) == [
            ("Asha", "20"), ("Asha", "5"), ("Bala", "50"),
        ]  # fmt: skip

        header, rows = _table(await get("present-absent"))
        assert header[:2] == ["Employee", "Code"]
        by_name = {r["Employee"]: r for r in rows}
        assert list(by_name) == ["Asha", "Bala", "Chitra", "Dev"]  # by name
        assert by_name["Asha"]["Present"] == "3" and by_name["Bala"]["Absent"] == "1"
        assert by_name["Chitra"]["Leave"] == "1" and by_name["Chitra"]["Weekly off"] == "1"

        header, rows = _table(await get("hours"))
        assert header == [
            "Employee", "Code", "Days", "Worked (min)", "Average (min)", "Scheduled (min)",
        ]  # fmt: skip
        asha = next(r for r in rows if r["Employee"] == "Asha")
        assert int(asha["Days"]) == 3 and int(asha["Worked (min)"]) >= 500
        # Only days with a first punch count: Chitra punched in once, Bala once (yesterday, and
        # never checked out), and a day without a punch adds no hours.
        days = {r["Employee"]: int(r["Days"]) for r in rows}
        assert days == {"Asha": 3, "Bala": 1, "Chitra": 1, "Dev": 1}

        header, rows = _table(await get("overtime"))
        assert header == [
            "Date", "Employee", "Code", "Day class", "Detected (min)", "Approved (min)",
            "Pending (min)", "Status",
        ]  # fmt: skip
        assert len(rows) == 1
        assert rows[0]["Employee"] == "Asha" and rows[0]["Day class"] == "Normal"
        assert (rows[0]["Detected (min)"], rows[0]["Approved (min)"], rows[0]["Pending (min)"]) == (
            "30", "10", "20",
        )  # fmt: skip
        assert rows[0]["Status"] == "Pending"
    finally:
        await _cleanup_overtime(ctx["company_id"])
        await _cleanup_attendance_day(company_id=ctx["company_id"])


async def test_filters_window_scope_tenant_and_audit(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    ctx = await _company(client)
    other = await _setup(client)
    window = {"date_from": ctx["week_ago"].isoformat(), "date_to": ctx["today"].isoformat()}
    today = business_today(TZ)
    created: list[UUID] = []
    try:
        _, hr = _table(
            await client.get(
                _url("daily"), headers=ctx["headers"], params={**window, "department_id": ctx["hr"]}
            )
        )
        assert {r["Employee"] for r in hr} == {"Chitra"}

        for params in (
            {"date_from": today.isoformat(), "date_to": (today + timedelta(days=1)).isoformat()},
            {"date_from": today.isoformat(), "date_to": (today - timedelta(days=1)).isoformat()},
            {"date_from": (today - timedelta(days=366)).isoformat(), "date_to": today.isoformat()},
        ):
            bad = await client.get(_url("daily"), headers=ctx["headers"], params=params)
            assert bad.status_code == 422, (params, bad.text)
        unknown = await client.get(_url("payroll"), headers=ctx["headers"], params=window)
        assert unknown.status_code == 422
        year = {
            "date_from": (today - timedelta(days=365)).isoformat(),
            "date_to": today.isoformat(),
        }
        assert (
            await client.get(_url("hours"), headers=ctx["headers"], params=year)
        ).status_code == 200

        own, own_user = await _login_for(ctx["company_id"], ctx["asha"], [ATTENDANCE_VIEW], "SELF")
        created.append(own_user)
        _, mine = _table(await client.get(_url("daily"), headers=own, params=window))
        assert {r["Employee"] for r in mine} == {"Asha"}

        _, theirs = _table(
            await client.get(
                _url("daily"),
                headers=other["headers"],
                params={**window, "department_id": ctx["eng"]},
            )
        )
        assert theirs == []

        assert (await client.get(_url("daily"), params=window)).status_code in (401, 403)

        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(ctx["company_id"]))
            audited = (
                await session.execute(
                    text(
                        "SELECT count(*) FROM audit_log WHERE company_id = :c "
                        "AND action = 'ATTENDANCE_REPORT_EXPORTED' "
                        "AND after_json->>'report' IN ('daily', 'hours')"
                    ),
                    {"c": ctx["company_id"]},
                )
            ).scalar_one()
        assert audited >= 3  # hr filter, the year window, the self-scope download
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
