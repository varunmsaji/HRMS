"""F7 (D-6): a published roster outranks the work calendar when Leave decides which days consume
leave, as it does in attendance. A draft roster changes nothing."""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.leave.test_leave_application import (
    _get_balance,
    _register_tenant,
    _setup_full,
    _submit,
    _teardown,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.core.db.session import get_session_factory, set_rls_company_id

pytestmark = pytest.mark.asyncio


async def _roster(
    client: AsyncClient,
    headers: dict[str, str],
    employee_id: str,
    day: str,
    *,
    publish: bool = True,
    **flags: bool,
) -> None:
    created = await client.post(
        "/v1/rosters",
        headers=headers,
        json={"employee_id": employee_id, "roster_date": day, "shift_id": None, **flags},
    )
    assert created.status_code == 201, created.text
    if publish:
        published = await client.post(
            f"/v1/rosters/{created.json()['data']['id']}/publish",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert published.status_code == 200, published.text


async def _drop_rosters(company_id: Any) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        await session.execute(
            text("DELETE FROM shift_roster WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.commit()


@pytest.mark.parametrize(
    ("publish", "total", "wednesday_charged"),
    [
        (True, "4.00", False),  # published roster day off: Wednesday is not leave
        (False, "5.00", True),  # a draft roster changes nothing (must not change)
    ],
)
async def test_a_roster_day_off_inside_leave_is_not_charged(
    client: AsyncClient,
    seeded_plan_catalogue: None,
    publish: bool,
    total: str,
    wednesday_charged: bool,
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, balance="10.00", sandwich_rule_enabled=False)
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]
        await _roster(
            client, headers, employee_id, "2026-09-09", publish=publish, is_week_off_override=True
        )

        # Monday 7 to Friday 11 September 2026.
        submitted = await _submit(
            client,
            headers,
            employee_id=employee_id,
            leave_type_id=leave_type_id,
            start_date="2026-09-07",
            end_date="2026-09-11",
        )
        assert submitted.status_code == 201, submitted.text
        data = submitted.json()["data"]
        assert data["total_days"] == total
        charged = {d["calendar_date"] for d in data["days"]}
        assert ("2026-09-09" in charged) is wednesday_charged
        assert await _get_balance(client, headers, employee_id) == f"{10 - float(total):.2f}"
    finally:
        await _drop_rosters(company_id)
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_a_rostered_working_day_on_a_weekly_off_is_charged(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Sunday is the calendar's weekly off, but the roster has the employee working it."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, balance="10.00")
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]
        await _roster(client, headers, employee_id, "2026-09-13", is_holiday_working_override=True)

        submitted = await _submit(
            client,
            headers,
            employee_id=employee_id,
            leave_type_id=leave_type_id,
            start_date="2026-09-13",
            end_date="2026-09-13",
        )
        assert submitted.status_code == 201, submitted.text
        data = submitted.json()["data"]
        assert data["total_days"] == "1.00"
        assert [d["calendar_date"] for d in data["days"]] == ["2026-09-13"]
    finally:
        await _drop_rosters(company_id)
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
