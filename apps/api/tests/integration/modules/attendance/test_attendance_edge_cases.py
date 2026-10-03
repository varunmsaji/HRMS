"""Module-audit regression tests for the attendance flows: punch idempotency and leaver periods."""

import pytest
from httpx import AsyncClient

from .test_attendance_day import (
    _build_wired_employee,
    _cleanup,
    _cleanup_attendance_day,
    _punch,
    _register_tenant,
)
from .test_attendance_period import _cleanup_attendance_period, _create_period, _full_calculate

pytestmark = pytest.mark.asyncio


async def _terminate(client: AsyncClient, headers: dict, employee_id: str, last_working_day: str):
    employment = (
        await client.get(f"/v1/employees/{employee_id}/employments", headers=headers)
    ).json()["data"][0]
    response = await client.post(
        f"/v1/employees/{employee_id}/employments/{employment['id']}/terminate",
        headers={**headers, "If-Match": str(employment["version"])},
        json={"last_working_day": last_working_day},
    )
    assert response.status_code == 200, response.text


async def test_idempotency_key_is_not_replayed_across_employees(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The key is unique per company. Reusing one employee's key for another used to return a
    201 carrying the first employee's punch and silently drop the second employee's."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        first = await _build_wired_employee(client, headers)
        other = (
            await client.post("/v1/employees", headers=headers, json={"first_name": "Bob"})
        ).json()["data"]
        original = await _punch(
            client,
            headers,
            employee_id=first["employee"]["id"],
            hour=9,
            minute=0,
            direction="IN",
            idempotency_key="shared-key",
        )

        clash = await client.post(
            "/v1/attendance/punches",
            headers=headers,
            json={
                "employee_id": other["id"],
                "punch_time": "2026-08-10T09:05:00Z",
                "direction": "IN",
                "reference": "clash",
                "idempotency_key": "shared-key",
            },
        )
        assert clash.status_code == 409, clash.text
        assert clash.json()["error"]["code"] == "DUPLICATE_PUNCH_IDEMPOTENCY_KEY"
        assert first["employee"]["id"] not in clash.text, "another employee's punch leaked"

        # the legitimate retry by the same employee still replays the original row
        again = await _punch(
            client,
            headers,
            employee_id=first["employee"]["id"],
            hour=9,
            minute=0,
            direction="IN",
            idempotency_key="shared-key",
        )
        assert again["id"] == original["id"]
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_leaver_period_finalizes_with_exited_days_not_blocking(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """An employee whose last working day falls mid-period: days after it are EXITED, never
    "missing attendance", and the frozen summary counts them as not employed (not LOP)."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _full_calculate(client, headers, employee_id=employee_id, day="2026-08-10")
        await _full_calculate(client, headers, employee_id=employee_id, day="2026-08-11")
        await _terminate(client, headers, employee_id, "2026-08-11")

        after = await client.post(
            "/v1/attendance/days/calculate",
            headers=headers,
            params={"employee_id": employee_id, "date": "2026-08-12"},
        )
        assert after.json()["data"]["attendance_status"] == "EXITED"
        assert after.json()["data"]["lop_fraction"] == "0.00"

        period = await _create_period(
            client, headers, period_start="2026-08-10", period_end="2026-08-12"
        )
        validated = await client.post(
            f"/v1/attendance-periods/{period['id']}/validate", headers=headers
        )
        assert validated.json()["data"]["status"] == "READY"
        finalized = await client.post(
            f"/v1/attendance-periods/{period['id']}/finalize",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert finalized.status_code == 200, finalized.text
        row = (
            await client.get(f"/v1/attendance-periods/{period['id']}/summary", headers=headers)
        ).json()["data"][0]
        assert (row["present_days"], row["not_employed_days"]) == ("2.00", "1.00")
        assert (row["payable_days"], row["lop_days"]) == ("2.00", "0.00")
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
