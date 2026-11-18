"""Invariant C: a change that alters an already-calculated day queues its recalculation, and the
processor brings the stored day up to date. Before, the stored day kept its old result until a
punch, the 3-day trailing sweep or a manual range recalculation happened to touch it."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.test_attendance_day import (
    _cleanup_attendance_day,
    _register_tenant,
)
from tests.integration.modules.attendance.test_shift_window import _make_shift, _sql, _wire
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.attendance import recalc

pytestmark = pytest.mark.asyncio

# Older than the trailing sweep's 3-day window, so only the queue can repair it.
DAY = (datetime.now(UTC) - timedelta(days=5)).date().isoformat()


@pytest.fixture
async def tenant(
    client: AsyncClient, seeded_plan_catalogue: None
) -> AsyncIterator[tuple[dict[str, str], UUID]]:
    headers, company_id, user_id = await _register_tenant(client)
    yield headers, company_id
    await _cleanup_attendance_day(company_id=company_id)
    await _cleanup(company_id=company_id, user_id=user_id)


async def _calculate(client: AsyncClient, headers: dict[str, str], employee_id: str) -> Any:
    response = await client.post(
        "/v1/attendance/days/calculate",
        headers=headers,
        params={"employee_id": employee_id, "date": DAY},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def _stored_status(company_id: UUID, employee_id: str) -> str:
    rows = await _sql(
        company_id,
        "SELECT attendance_status FROM attendance_day "
        "WHERE company_id = :cid AND employee_id = :eid AND attendance_date = :d",
        eid=employee_id,
        d=datetime.fromisoformat(DAY).date(),
    )
    return str(rows[0][0])


async def _pending(company_id: UUID) -> list[Any]:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        result = await session.execute(
            text(
                "SELECT reason, employee_id, shift_id, date_from, date_to "
                "FROM attendance_recalc_request "
                "WHERE company_id = :cid AND processed_at IS NULL ORDER BY created_at"
            ),
            {"cid": str(company_id)},
        )
        return list(result.all())


async def test_a_published_roster_day_off_recalculates_the_stored_day(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID]
) -> None:
    headers, company_id = tenant
    wired = await _wire(client, headers, allowance=None)
    employee_id = wired["employee_id"]
    first = await _calculate(client, headers, employee_id)
    assert first["attendance_status"] != "NOT_EXPECTED"
    # Setup (shift publish, assignment, policy assignments) queued its own requests; process them
    # so only the roster's request is left.
    await recalc.process_company_requests(company_id)
    assert await _pending(company_id) == []

    # A draft roster row changes nothing and queues nothing.
    created = await client.post(
        "/v1/rosters",
        headers=headers,
        json={"employee_id": employee_id, "roster_date": DAY, "is_week_off_override": True},
    )
    assert created.status_code == 201, created.text
    assert await _pending(company_id) == []
    published = await client.post(
        f"/v1/rosters/{created.json()['data']['id']}/publish",
        headers={**headers, "If-Match": "1"},
        json={},
    )
    assert published.status_code == 200, published.text

    pending = await _pending(company_id)
    assert [(r.reason, str(r.employee_id), r.date_from.isoformat()) for r in pending] == [
        ("ROSTER_CHANGED", employee_id, DAY)
    ]
    # Stale until the processor runs.
    assert await _stored_status(company_id, employee_id) == first["attendance_status"]

    totals = await recalc.process_company_requests(company_id)
    assert totals["requests"] == 1
    assert totals["calculated"] == 1
    assert await _stored_status(company_id, employee_id) == "NOT_EXPECTED"
    assert await _pending(company_id) == []


async def test_a_new_shift_version_recalculates_days_on_that_shift_only(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID]
) -> None:
    headers, company_id = tenant
    wired = await _wire(client, headers, allowance=None)
    employee_id, shift_id = wired["employee_id"], wired["shift_id"]
    await _calculate(client, headers, employee_id)
    other_shift = await _make_shift(client, headers, "OTHER", "06:00", "14:00")
    await recalc.process_company_requests(company_id)
    assert await _pending(company_id) == []

    versions = (await client.get(f"/v1/shifts/{shift_id}/versions", headers=headers)).json()["data"]
    current = next(v for v in versions if v["status"] == "PUBLISHED")
    draft = await client.post(
        f"/v1/shifts/{shift_id}/versions",
        headers=headers,
        json={
            "shift_type": "FIXED",
            "effective_from": DAY,
            "start_time": "10:00",
            "end_time": "19:00",
            "timezone": "UTC",
        },
    )
    assert draft.status_code == 201, draft.text
    published = await client.post(
        f"/v1/shifts/{shift_id}/versions/{draft.json()['data']['id']}/publish",
        headers={**headers, "If-Match": str(draft.json()["data"]["version"])},
        json={"expected_previous_version": current["version"]},
    )
    assert published.status_code == 200, published.text

    pending = await _pending(company_id)
    assert len(pending) == 1
    assert pending[0].reason == "SHIFT_VERSION_PUBLISHED"
    assert str(pending[0].shift_id) == shift_id
    assert pending[0].employee_id is None
    assert pending[0].date_from.isoformat() == DAY
    assert str(pending[0].shift_id) != other_shift

    totals = await recalc.process_company_requests(company_id)
    assert totals == {"requests": 1, "calculated": 1, "skipped_locked": 0, "failed": 0}
    rows = await _sql(
        company_id,
        "SELECT shift_version_id FROM attendance_day WHERE company_id = :cid AND employee_id = :e",
        e=employee_id,
    )
    assert str(rows[0][0]) == draft.json()["data"]["id"]


async def test_a_change_dated_in_the_future_queues_nothing(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID]
) -> None:
    headers, company_id = tenant
    wired = await _wire(client, headers, allowance=None)
    await recalc.process_company_requests(company_id)
    future = (datetime.now(UTC) + timedelta(days=10)).date().isoformat()
    created = await client.post(
        "/v1/rosters",
        headers=headers,
        json={
            "employee_id": wired["employee_id"],
            "roster_date": future,
            "is_week_off_override": True,
        },
    )
    assert created.status_code == 201, created.text
    published = await client.post(
        f"/v1/rosters/{created.json()['data']['id']}/publish",
        headers={**headers, "If-Match": "1"},
        json={},
    )
    assert published.status_code == 200, published.text
    assert await _pending(company_id) == []
