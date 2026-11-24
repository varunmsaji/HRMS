"""Integration tests for `GET /v1/attendance/export/muster`.

The register reads the same `attendance_day` rows and bucket rules as `/attendance/summary`, so the
rows are inserted directly. Under test: the file itself (one row per employee, one column per date,
codes, totals, blank for a missing day), the filters, the window rules, the caller's scope and the
tenant boundary, and that every download is audited.
"""

import csv
import io
from datetime import timedelta
from typing import Any
from uuid import UUID

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
from hrms.modules.attendance.muster_export import csv_text
from hrms.modules.attendance.permissions import ATTENDANCE_VIEW
from hrms.shared.business_time import business_today

URL = "/v1/attendance/export/muster"


def _rows(response: Any) -> list[list[str]]:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["cache-control"] == "no-store"
    body = response.content.decode("utf-8")
    assert body.startswith("﻿")
    return list(csv.reader(io.StringIO(body.lstrip("﻿"))))


def test_a_formula_looking_name_is_defused() -> None:
    assert csv_text("=cmd|' /C calc'!A0") == "'=cmd|' /C calc'!A0"
    assert csv_text("Asha") == "Asha"
    assert csv_text(None) == ""


@pytest.mark.asyncio
async def test_the_register_lists_one_row_per_employee(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    ctx = await _company(client)
    window = {"date_from": ctx["week_ago"].isoformat(), "date_to": ctx["today"].isoformat()}
    try:
        rows = _rows(await client.get(URL, headers=ctx["headers"], params=window))
        header = rows[0]
        assert header[:2] == ["Employee", "Code"]
        assert header[2:10] == [(ctx["week_ago"] + timedelta(days=i)).isoformat() for i in range(8)]
        assert header[10:] == [
            "Present", "Half day", "Absent", "Leave", "Weekly off", "Holiday", "Incomplete",
        ]  # fmt: skip
        people = {r[0]: r for r in rows[1:] if r and r[0] and len(r) == len(header)}
        assert set(people) == {"Asha", "Bala", "Chitra", "Dev"}

        def cell(name: str, day: Any) -> str:
            return people[name][2 + (day - ctx["week_ago"]).days]

        # A day with no stored record is blank, never absent.
        assert cell("Asha", ctx["week_ago"] + timedelta(days=1)) == ""
        assert cell("Asha", ctx["week_ago"]) == "P"
        assert cell("Bala", ctx["week_ago"]) == "A"
        assert cell("Chitra", ctx["yesterday"]) == "W"
        assert cell("Chitra", ctx["today"]) == "L"
        # Bala has no punch today and the shift is running: not yet absent.
        assert cell("Bala", ctx["today"]) == "NC"
        totals = dict(zip(header[10:], people["Asha"][10:], strict=True))
        assert totals["Present"] == "3" and totals["Absent"] == "0"
        assert rows[-1][0] == "NC" or any(r[:1] == ["Legend"] for r in rows)
    finally:
        await _cleanup_attendance_day(company_id=ctx["company_id"])


@pytest.mark.asyncio
async def test_filters_window_scope_tenant_and_audit(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    ctx = await _company(client)
    other = await _setup(client)
    window = {"date_from": ctx["week_ago"].isoformat(), "date_to": ctx["today"].isoformat()}
    today = business_today(TZ)
    created: list[UUID] = []
    try:
        hr = _rows(
            await client.get(
                URL, headers=ctx["headers"], params={**window, "department_id": ctx["hr"]}
            )
        )
        assert [r[0] for r in hr[1:] if len(r) == len(hr[0])] == ["Chitra"]

        for params in (
            {"date_from": today.isoformat(), "date_to": (today + timedelta(days=1)).isoformat()},
            {"date_from": today.isoformat(), "date_to": (today - timedelta(days=1)).isoformat()},
            {"date_from": (today - timedelta(days=366)).isoformat(), "date_to": today.isoformat()},
        ):
            bad = await client.get(URL, headers=ctx["headers"], params=params)
            assert bad.status_code == 422, (params, bad.text)
        ok = await client.get(
            URL,
            headers=ctx["headers"],
            params={
                "date_from": (today - timedelta(days=365)).isoformat(),
                "date_to": today.isoformat(),
            },
        )
        assert ok.status_code == 200

        # A caller who sees only their own attendance gets only their own row.
        own, own_user = await _login_for(ctx["company_id"], ctx["asha"], [ATTENDANCE_VIEW], "SELF")
        created.append(own_user)
        mine = _rows(await client.get(URL, headers=own, params=window))
        assert [r[0] for r in mine[1:] if len(r) == len(mine[0])] == ["Asha"]

        # Another company sees none of this company's people.
        theirs = _rows(
            await client.get(
                URL, headers=other["headers"], params={**window, "department_id": ctx["eng"]}
            )
        )
        assert [r for r in theirs[1:] if len(r) == len(theirs[0])] == []

        assert (await client.get(URL, params=window)).status_code in (401, 403)

        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(ctx["company_id"]))
            audited = (
                await session.execute(
                    text(
                        "SELECT count(*) FROM audit_log WHERE company_id = :c "
                        "AND action = 'ATTENDANCE_MUSTER_EXPORTED'"
                    ),
                    {"c": ctx["company_id"]},
                )
            ).scalar_one()
        assert audited >= 3  # hr filter, the year window, the self-scope download
    finally:
        # The test login's own download is audited, and the audit row names the user.
        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(ctx["company_id"]))
            await session.execute(
                text("DELETE FROM audit_log WHERE actor_user_id = ANY(:ids)"), {"ids": created}
            )
            await session.commit()
        await _forget_users(ctx["company_id"], created)
        await _cleanup_attendance_day(company_id=ctx["company_id"])
        await _cleanup_attendance_day(company_id=other["company_id"])
