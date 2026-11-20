"""`GET /v1/attendance/month-summary` (R-B03): one month of the payroll arithmetic, for one
employee or a grid, from the same code that finalizes a period.

The month is in the past so every row is settled. The rows are the cases the screens used to count
differently from payroll: a half-day leave with the other half worked, and a plain half day.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.test_attendance_day import _cleanup_attendance_day
from tests.integration.modules.attendance.test_attendance_period import (
    _cleanup_attendance_period,
    _create_period,
)
from tests.integration.modules.attendance.test_company_attendance_overview import (
    _add_day,
    _employee,
    _setup,
)

from hrms.core.db.session import get_session_factory, set_rls_company_id

pytestmark = pytest.mark.asyncio

URL = "/v1/attendance/month-summary"
MONTH = "2026-09"
START, END = date(2026, 9, 1), date(2026, 9, 30)


async def _emp(client: AsyncClient, ctx: dict[str, Any], name: str) -> str:
    return await _employee(
        client,
        ctx["headers"],
        name=name,
        legal_entity_id=ctx["le"],
        department_id=ctx["eng"],
        branch_id=ctx["branch"],
        designation_id=ctx["desig"],
    )


async def _seed_two(ctx: dict[str, Any], a: str, b: str) -> None:
    company_id = ctx["company_id"]
    # A: a full day, a half-day leave with the other half worked, a day of paid leave.
    await _add_day(
        company_id, a, date(2026, 9, 1), "PRESENT",
        paid_day_fraction=Decimal("1"), lop_fraction=Decimal("0"),
    )  # fmt: skip
    await _add_day(
        company_id, a, date(2026, 9, 2), "PRESENT",
        leave_fraction=Decimal("0.5"), paid_day_fraction=Decimal("1"), lop_fraction=Decimal("0"),
    )  # fmt: skip
    await _add_day(
        company_id, a, date(2026, 9, 3), "LEAVE",
        leave_fraction=Decimal("1"), paid_day_fraction=Decimal("1"), lop_fraction=Decimal("0"),
    )  # fmt: skip
    # B: a band half day (0.5 paid, 0.5 LOP) and an absent day.
    await _add_day(
        company_id, b, date(2026, 9, 1), "HALF_DAY",
        paid_day_fraction=Decimal("0.5"), lop_fraction=Decimal("0.5"),
    )  # fmt: skip
    await _add_day(
        company_id, b, date(2026, 9, 2), "ABSENT",
        paid_day_fraction=Decimal("0"), lop_fraction=Decimal("1"),
    )  # fmt: skip


async def test_live_month_matches_the_open_period_summary(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    ctx = await _setup(client)
    headers, company_id = ctx["headers"], ctx["company_id"]
    try:
        a, b = await _emp(client, ctx, "A"), await _emp(client, ctx, "B")
        await _seed_two(ctx, a, b)

        r = await client.get(
            URL, headers=headers, params=[("month", MONTH), ("employee_id", a), ("employee_id", b)]
        )
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["month"] == MONTH
        rows = {s["employee_id"]: s for s in data["summaries"]}
        assert set(rows) == {a, b}
        assert all(s["frozen"] is False for s in rows.values())

        # The AUD-09 example: half-day leave, other half worked -> 1.5 present, 1.5 leave
        # (payroll's split), not "1 present, 0 leave".
        assert Decimal(rows[a]["present_days"]) == Decimal("1.5")
        assert Decimal(rows[a]["leave_days"]) == Decimal("1.5")
        assert Decimal(rows[a]["paid_days"]) == Decimal("3")
        assert Decimal(rows[b]["half_days"]) == Decimal("1")
        assert Decimal(rows[b]["absent_days"]) == Decimal("1")
        assert Decimal(rows[b]["lop_days"]) == Decimal("1.5")

        # The same arithmetic the payroll period preview shows for the same month.
        period = await _create_period(
            client, headers, period_start=START.isoformat(), period_end=END.isoformat(),
            legal_entity_id=ctx["le"],
        )  # fmt: skip
        preview = await client.get(
            f"/v1/attendance-periods/{period['id']}/summary", headers=headers
        )
        assert preview.status_code == 200, preview.text
        for row in preview.json()["data"]:
            mine = rows[row["employee_id"]]
            for key, value in row.items():
                if key != "generated_at":
                    assert mine[key] == value, key
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)


async def test_closed_month_returns_the_frozen_summary(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    ctx = await _setup(client)
    headers, company_id = ctx["headers"], ctx["company_id"]
    try:
        a = await _emp(client, ctx, "A")
        await _seed_two(ctx, a, await _emp(client, ctx, "B"))
        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, str(company_id))
            period_id = uuid4()
            now = datetime.now(UTC)
            await session.execute(
                text(
                    "INSERT INTO attendance_period (id, company_id, legal_entity_id, period_start, "
                    "period_end, label, status, opened_at, closed_at, version, created_at, "
                    "updated_at) VALUES (:id, :cid, :le, :s, :e, 'closed', 'CLOSED', :now, :now, "
                    "1, :now, :now)"
                ),
                {
                    "id": period_id,
                    "cid": str(company_id),
                    "le": ctx["le"],
                    "s": START,
                    "e": END,
                    "now": now,
                },
            )
            # Deliberately unlike what the day rows add up to: the frozen row must win.
            await session.execute(
                text(
                    "INSERT INTO attendance_period_summary (id, company_id, attendance_period_id, "
                    "employee_id, present_days, absent_days, leave_days, holiday_days, "
                    "weekly_off_days, half_days, lop_days, on_duty_days, incomplete_days, "
                    "not_employed_days, unpaid_off_days, paid_days, payable_days, "
                    "ot_minutes_normal, ot_minutes_weekly_off, ot_minutes_holiday, "
                    "ot_minutes_night, comp_off_minutes_earned, late_count, worked_minutes_total, "
                    "generated_at, created_at, updated_at) VALUES (:id, :cid, :pid, :eid, 21, 1, "
                    "2, 4, 2, 0, 1, 0, 0, 0, 0, 26, 27, 0, 0, 0, 0, 0, 0, 0, :now, :now, :now)"
                ),
                {
                    "id": uuid4(),
                    "cid": str(company_id),
                    "pid": period_id,
                    "eid": UUID(a),
                    "now": now,
                },
            )
            await session.commit()

        r = await client.get(URL, headers=headers, params={"month": MONTH, "employee_id": a})
        assert r.status_code == 200, r.text
        (row,) = r.json()["data"]["summaries"]
        assert row["frozen"] is True
        assert Decimal(row["present_days"]) == Decimal("21")
        assert Decimal(row["paid_days"]) == Decimal("26")
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)


async def test_employee_without_days_has_no_entry_and_bad_month_is_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    ctx = await _setup(client)
    headers, company_id = ctx["headers"], ctx["company_id"]
    try:
        a = await _emp(client, ctx, "A")
        r = await client.get(URL, headers=headers, params={"month": MONTH, "employee_id": a})
        assert r.status_code == 200, r.text
        assert r.json()["data"]["summaries"] == []
        bad = await client.get(URL, headers=headers, params={"month": "2026-13", "employee_id": a})
        assert bad.status_code == 422
        none = await client.get(URL, headers=headers, params={"month": MONTH})
        assert none.status_code == 422
    finally:
        await _cleanup_attendance_day(company_id=company_id)
