"""AC-01 / AC-04 (attendance + calendar + overtime audit, 16 Nov 2026) — what a recalculation does
to an earlier overtime decision, through the real API.

* `AUTO_APPROVED` follows the fresh detection (never a human judgement).
* A human `APPROVED` decision is reopened for HR when the detection grows or changes class, and
  capped when it only shrinks (P-C); the original decision stays on the record's timeline.
* A human `REJECTED` decision never becomes an approval by itself.
* Overtime on a day that ends INCOMPLETE is held, never auto-approved (AC-04).
* Repeating a recalculation changes nothing.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from tests.integration.modules.attendance.test_attendance_day import (
    _build_wired_employee,
    _cleanup_attendance_day,
    _punch,
    _register_tenant,
)
from tests.integration.modules.attendance.test_attendance_security import (
    _cleanup_scoped_users,
    _create_permission_scoped_user,
)
from tests.integration.modules.attendance.test_overtime_record import (
    _cleanup_overtime,
    _create_overtime_policy,
    _ot_calculate_day,
)
from tests.integration.modules.attendance.test_regularization import (
    _cleanup_regularization,
    _create_regularization_policy,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

pytestmark = pytest.mark.asyncio

DAY = "2026-08-10"


async def _correct_out(
    client: AsyncClient, headers: dict[str, str], employee_id: str, hhmm: str
) -> None:
    """Approved WRONG_PUNCH regularization moving the OUT punch to `hhmm` (AUTO chain)."""
    created = await client.post(
        "/v1/regularizations",
        headers=headers,
        json={
            "employee_id": employee_id,
            "attendance_date": DAY,
            "request_type": "WRONG_PUNCH",
            "reason": "Wrong OUT time",
            "requested_punches": [{"direction": "OUT", "requested_time": f"{DAY}T{hhmm}:00Z"}],
        },
    )
    assert created.status_code == 201, created.text


async def _day(client: AsyncClient, headers: dict[str, str], day_id: str) -> dict[str, Any]:
    read = await client.get(f"/v1/attendance/days/{day_id}", headers=headers)
    assert read.status_code == 200, read.text
    return dict(read.json()["data"])


async def _records(
    client: AsyncClient, headers: dict[str, str], employee_id: str
) -> list[dict[str, Any]]:
    listed = await client.get(
        "/v1/overtime",
        headers=headers,
        params={"employee_id": employee_id, "date_from": DAY, "date_to": DAY},
    )
    assert listed.status_code == 200, listed.text
    return [dict(r) for r in listed.json()["data"]]


async def _hr_headers(company_id: Any) -> dict[str, str]:
    from hrms.modules.attendance.permissions import ATTENDANCE_OVERTIME_APPROVE

    hr_headers, _ = await _create_permission_scoped_user(
        company_id=company_id,
        permission_codes=[ATTENDANCE_OVERTIME_APPROVE],
        data_scope="COMPANY",
        caller_employee_id=None,
    )
    return hr_headers


async def _cleanup_all(company_id: Any, user_id: Any) -> None:
    await _cleanup_regularization(company_id=company_id)
    await _cleanup_overtime(company_id=company_id)
    await _cleanup_attendance_day(company_id=company_id)
    await _cleanup(company_id=company_id, user_id=user_id)
    await _cleanup_scoped_users()


async def test_auto_approved_overtime_is_withdrawn_when_a_correction_removes_it(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = (await _build_wired_employee(client, headers))["employee"]["id"]
        await _create_overtime_policy(client, headers, approval_chain="AUTO")
        await _create_regularization_policy(client, headers, approval_chain="AUTO")
        day = await _ot_calculate_day(client, headers, employee_id=employee_id)
        assert day["ot_minutes_approved"] == 60

        await _correct_out(client, headers, employee_id, "18:00")

        after = await _day(client, headers, day["id"])
        assert after["ot_minutes_detected"] == 0
        assert after["ot_minutes_approved"] == 0  # the audit's reproduction left 60 here
        assert await _records(client, headers, employee_id) == []
    finally:
        await _cleanup_all(company_id, user_id)


async def test_human_approved_overtime_is_reopened_when_the_detection_grows(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = (await _build_wired_employee(client, headers))["employee"]["id"]
        await _create_overtime_policy(client, headers, approval_chain="HR")
        day = await _ot_calculate_day(client, headers, employee_id=employee_id)
        record = (await _records(client, headers, employee_id))[0]
        hr = await _hr_headers(company_id)
        approved = await client.post(
            f"/v1/overtime/{record['id']}/approve",
            headers={**hr, "If-Match": str(record["version"])},
            json={},
        )
        assert approved.status_code == 200, approved.text
        assert (await _day(client, headers, day["id"]))["ot_minutes_approved"] == 60

        await _punch(
            client, headers, employee_id=employee_id, hour=19, minute=10, direction="IN", day=DAY
        )
        await _punch(
            client, headers, employee_id=employee_id, hour=19, minute=50, direction="OUT", day=DAY
        )
        r = await client.post(f"/v1/attendance/days/{day['id']}/recompute", headers=headers)
        assert r.status_code == 200, r.text

        reopened = (await _records(client, headers, employee_id))[0]
        assert reopened["id"] == record["id"]
        assert reopened["status"] == "PENDING"
        assert reopened["minutes_detected"] == 100
        assert reopened["minutes_approved"] == 0
        after = await _day(client, headers, day["id"])
        assert after["ot_minutes_approved"] == 0 and after["ot_pending"] is True
        actions = [a["action"] for a in reopened["actions"]]
        assert "APPROVED" in actions and "SUPERSEDED_BY_RECALCULATION" in actions

        # The reviewer's old version can no longer approve the new minutes.
        stale = await client.post(
            f"/v1/overtime/{record['id']}/approve",
            headers={**hr, "If-Match": str(approved.json()["data"]["version"])},
            json={},
        )
        assert stale.status_code in (409, 412), stale.text
    finally:
        await _cleanup_all(company_id, user_id)


async def test_human_approved_overtime_is_capped_when_the_detection_shrinks(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = (await _build_wired_employee(client, headers))["employee"]["id"]
        await _create_overtime_policy(client, headers, approval_chain="HR")
        await _create_regularization_policy(client, headers, approval_chain="AUTO")
        day = await _ot_calculate_day(client, headers, employee_id=employee_id)
        record = (await _records(client, headers, employee_id))[0]
        hr = await _hr_headers(company_id)
        approved = await client.post(
            f"/v1/overtime/{record['id']}/approve",
            headers={**hr, "If-Match": str(record["version"])},
            json={},
        )
        assert approved.status_code == 200, approved.text

        await _correct_out(client, headers, employee_id, "18:30")

        capped = (await _records(client, headers, employee_id))[0]
        assert capped["status"] == "APPROVED"  # still the human's decision
        assert capped["minutes_detected"] == 30
        assert capped["minutes_approved"] == 30  # never above what the punches support
        after = await _day(client, headers, day["id"])
        assert after["ot_minutes_detected"] == 30 and after["ot_minutes_approved"] == 30
        assert "SUPERSEDED_BY_RECALCULATION" in [a["action"] for a in capped["actions"]]
    finally:
        await _cleanup_all(company_id, user_id)


async def test_rejected_overtime_stays_rejected_until_new_overtime_appears(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = (await _build_wired_employee(client, headers))["employee"]["id"]
        await _create_overtime_policy(client, headers, approval_chain="HR")
        day = await _ot_calculate_day(client, headers, employee_id=employee_id)
        record = (await _records(client, headers, employee_id))[0]
        hr = await _hr_headers(company_id)
        rejected = await client.post(
            f"/v1/overtime/{record['id']}/reject",
            headers={**hr, "If-Match": str(record["version"])},
            json={"reviewer_comment": "Not authorised", "rejection_reason": "Not authorised"},
        )
        assert rejected.status_code == 200, rejected.text

        r = await client.post(f"/v1/attendance/days/{day['id']}/recompute", headers=headers)
        assert r.status_code == 200, r.text
        same = (await _records(client, headers, employee_id))[0]
        assert same["status"] == "REJECTED" and same["minutes_approved"] == 0

        await _punch(
            client, headers, employee_id=employee_id, hour=19, minute=10, direction="IN", day=DAY
        )
        await _punch(
            client, headers, employee_id=employee_id, hour=19, minute=50, direction="OUT", day=DAY
        )
        r = await client.post(f"/v1/attendance/days/{day['id']}/recompute", headers=headers)
        assert r.status_code == 200, r.text
        reopened = (await _records(client, headers, employee_id))[0]
        assert reopened["status"] == "PENDING"  # new overtime nobody has judged
        assert (await _day(client, headers, day["id"]))["ot_minutes_approved"] == 0
    finally:
        await _cleanup_all(company_id, user_id)


async def test_repeated_recalculation_changes_nothing(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = (await _build_wired_employee(client, headers))["employee"]["id"]
        await _create_overtime_policy(client, headers, approval_chain="AUTO")
        day = await _ot_calculate_day(client, headers, employee_id=employee_id)
        first = (await _records(client, headers, employee_id))[0]
        for _ in range(3):
            r = await client.post(f"/v1/attendance/days/{day['id']}/recompute", headers=headers)
            assert r.status_code == 200, r.text
        records = await _records(client, headers, employee_id)
        assert len(records) == 1
        assert records[0]["id"] == first["id"]
        assert records[0]["version"] == first["version"]
        assert len(records[0]["actions"]) == len(first["actions"])
        assert records[0]["minutes_approved"] == 60
    finally:
        await _cleanup_all(company_id, user_id)


async def test_overtime_on_an_incomplete_day_is_held_not_auto_approved(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """AC-04 — IN 07:30, IN 09:00, OUT 19:00: the 07:30 IN has no OUT, so the day is INCOMPLETE
    although a complete pair gives 60 overtime minutes. Under an AUTO overtime chain those
    minutes must not be approved."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = (await _build_wired_employee(client, headers))["employee"]["id"]
        await _create_overtime_policy(client, headers, approval_chain="AUTO")
        for hour, minute, direction in ((7, 30, "IN"), (9, 0, "IN"), (19, 0, "OUT")):
            await _punch(
                client,
                headers,
                employee_id=employee_id,
                hour=hour,
                minute=minute,
                direction=direction,
                day=DAY,
            )
        calculated = await client.post(
            "/v1/attendance/days/calculate",
            headers=headers,
            params={"employee_id": employee_id, "date": DAY},
        )
        assert calculated.status_code == 200, calculated.text
        day = calculated.json()["data"]
        assert day["attendance_status"] == "INCOMPLETE"
        assert day["ot_minutes_detected"] == 60
        assert day["ot_minutes_approved"] == 0
        assert day["ot_pending"] is True
        record = (await _records(client, headers, employee_id))[0]
        assert record["status"] == "PENDING"
        assert record["approval_stage"] == "HR"
    finally:
        await _cleanup_all(company_id, user_id)
