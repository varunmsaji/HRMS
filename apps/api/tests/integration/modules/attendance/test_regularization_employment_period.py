"""Regularization must only correct attendance that belongs to the employee's own employment
period: not after the last working day, not in a rehire gap, and its requested punches must stay
on (or next to) the attendance date and out of the future."""

import pytest
from httpx import AsyncClient

from .test_attendance_day import (
    _build_wired_employee,
    _cleanup,
    _cleanup_attendance_day,
    _register_tenant,
)
from .test_attendance_edge_cases import _terminate
from .test_regularization import (
    _cleanup_regularization,
    _create_regularization_policy,
    _requested_punches,
)

pytestmark = pytest.mark.asyncio


async def _submit(client: AsyncClient, headers: dict, employee_id: str, day: str, punches: list):
    return await client.post(
        "/v1/regularizations",
        headers=headers,
        json={
            "employee_id": employee_id,
            "attendance_date": day,
            "request_type": "MISSING_PUNCH",
            "reason": "forgot",
            "requested_punches": punches,
        },
    )


async def _stored_punch_count(client: AsyncClient, headers: dict, employee_id: str) -> int:
    listed = await client.get(
        "/v1/attendance/punches", headers=headers, params={"employee_id": employee_id}
    )
    return len(listed.json()["data"])


async def test_regularization_respects_employment_gap_and_rehire(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        eid = wired["employee"]["id"]
        await _create_regularization_policy(
            client,
            headers,
            approval_chain="AUTO",
            allow_hr_request=True,
            allow_manager_request=True,
        )
        entity_id = (await client.get(f"/v1/employees/{eid}/employments", headers=headers)).json()[
            "data"
        ][0]["legal_entity_id"]
        await _terminate(client, headers, eid, "2026-08-11")
        rehire = await client.post(
            f"/v1/employees/{eid}/employments",
            headers=headers,
            json={"legal_entity_id": entity_id, "joining_date": "2026-09-01"},
        )
        assert rehire.status_code == 201, rehire.text

        # old employment, last working day: allowed
        ok_old = await _submit(client, headers, eid, "2026-08-11", _requested_punches("2026-08-11"))
        assert ok_old.status_code == 201, ok_old.text
        assert ok_old.json()["data"]["status"] == "APPROVED"

        # the gap: rejected at submit, nothing written
        before = await _stored_punch_count(client, headers, eid)
        gap = await _submit(client, headers, eid, "2026-08-20", _requested_punches("2026-08-20"))
        assert gap.status_code == 422, gap.text
        assert gap.json()["error"]["code"] == "EMPLOYEE_TERMINATED"
        assert await _stored_punch_count(client, headers, eid) == before

        # a request on a gap-free date whose punches reach into the gap is refused too
        straddle = await _submit(
            client, headers, eid, "2026-08-11", _requested_punches("2026-08-25")
        )
        assert straddle.status_code == 422

        # new employment: allowed again
        ok_new = await _submit(client, headers, eid, "2026-09-02", _requested_punches("2026-09-02"))
        assert ok_new.status_code == 201, ok_new.text
    finally:
        await _cleanup_regularization(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_requested_punches_must_stay_near_the_attendance_date_and_out_of_the_future(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        eid = wired["employee"]["id"]
        await _create_regularization_policy(
            client,
            headers,
            approval_chain="AUTO",
            allow_hr_request=True,
            allow_manager_request=True,
        )

        elsewhere = await _submit(
            client, headers, eid, "2026-08-10", _requested_punches("2026-07-01")
        )
        assert elsewhere.status_code == 422, elsewhere.text
        future = await _submit(client, headers, eid, "2026-08-11", _requested_punches("2030-01-01"))
        assert future.status_code == 422, future.text
        assert await _stored_punch_count(client, headers, eid) == 0

        # an overnight pair straddling midnight is still fine
        overnight = await _submit(
            client,
            headers,
            eid,
            "2026-08-10",
            [
                {"direction": "IN", "requested_time": "2026-08-10T20:00:00Z"},
                {"direction": "OUT", "requested_time": "2026-08-11T04:00:00Z"},
            ],
        )
        assert overnight.status_code == 201, overnight.text
    finally:
        await _cleanup_regularization(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
