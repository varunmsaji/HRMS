"""LM-14 — a leave projection must be backed by a real, APPROVED leave application.

`POST /v1/leave-projections` used to accept `leave_application_id` as an opaque UUID, so a caller
could publish APPROVED leave (and with it attendance paid/LOP fractions that Payroll reads) with no
leave application, ledger entry or approval behind it. These tests pin the invariant: the
application must exist for this company *and* employee, be `APPROVED`, carry a day row for the
date, and the projected values are Leave's, never the request body's.
"""

from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.test_attendance_day import (
    _build_wired_employee,
    _cleanup_attendance_day,
    _register_tenant,
)
from tests.integration.modules.attendance.test_leave_projection import (
    _DAY,
    _cleanup_leave_projection,
    _get_day,
    _seed_leave_application,
    _set_application_status,
    _sync,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.core.db.session import get_session_factory, set_rls_company_id

pytestmark = pytest.mark.asyncio


def _code(response: Any) -> str:
    return str(response.json()["error"]["code"])


async def _projection_count(company_id: UUID, *, status: str | None = None) -> int:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        sql = "SELECT count(*) FROM leave_day_projection WHERE company_id = :c"
        params: dict[str, Any] = {"c": str(company_id)}
        if status is not None:
            sql += " AND status = :s"
            params["s"] = status
        return int((await session.execute(text(sql), params)).scalar_one())


async def _second_employee(client: AsyncClient, headers: dict[str, str]) -> str:
    created = await client.post("/v1/employees", headers=headers, json={"first_name": "Ravi"})
    assert created.status_code == 201, created.text
    return str(created.json()["data"]["id"])


async def _teardown(company_id: UUID, user_id: UUID | None) -> None:
    await _cleanup_leave_projection(company_id=company_id)
    await _cleanup_attendance_day(company_id=company_id)
    await _cleanup(company_id=company_id, user_id=user_id)


# ----------------------------------------------------------- the rejections (B-H)


async def test_nonexistent_application_cannot_create_projection(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = (await _build_wired_employee(client, headers))["employee"]["id"]
        response = await _sync(
            client, headers, employee_id=employee_id, leave_application_id=str(uuid4())
        )
        assert response.status_code == 404, response.text
        assert _code(response) == "LEAVE_PROJECTION_APPLICATION_NOT_FOUND"
        assert await _projection_count(company_id) == 0
        # Payroll safety: no projection -> attendance carries no leave / payable-day effect.
        day = (
            await client.get(
                "/v1/attendance/days",
                headers=headers,
                params={"employee_id": employee_id, "date_from": _DAY, "date_to": _DAY},
            )
        ).json()["data"]
        assert all(d["attendance_status"] != "LEAVE" for d in day)
        assert all(d["paid_day_fraction"] == "0.00" for d in day)
    finally:
        await _teardown(company_id, user_id)


async def test_application_of_another_employee_same_company_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = (await _build_wired_employee(client, headers))["employee"]["id"]
        other = await _second_employee(client, headers)
        others_application = await _seed_leave_application(
            company_id=company_id, employee_id=other, days=[(_DAY, "1.00", None, False)]
        )
        response = await _sync(
            client, headers, employee_id=employee_id, leave_application_id=others_application
        )
        assert response.status_code == 404, response.text
        assert _code(response) == "LEAVE_PROJECTION_APPLICATION_NOT_FOUND"
        assert await _projection_count(company_id) == 0
    finally:
        await _teardown(company_id, user_id)


async def test_application_of_another_company_rejected_without_revealing_it(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        employee_a = (await _build_wired_employee(client, headers_a))["employee"]["id"]
        employee_b = await _second_employee(client, headers_b)
        foreign = await _seed_leave_application(
            company_id=company_b, employee_id=employee_b, days=[(_DAY, "1.00", None, False)]
        )
        existing_in_b = await _sync(
            client, headers_a, employee_id=employee_a, leave_application_id=foreign
        )
        missing = await _sync(
            client, headers_a, employee_id=employee_a, leave_application_id=str(uuid4())
        )
        # A foreign application is indistinguishable from a nonexistent one.
        assert existing_in_b.status_code == missing.status_code == 404
        assert _code(existing_in_b) == _code(missing) == "LEAVE_PROJECTION_APPLICATION_NOT_FOUND"
        assert existing_in_b.json()["error"]["message"] == missing.json()["error"]["message"]
        assert await _projection_count(company_a) == 0
    finally:
        await _teardown(company_a, user_a)
        await _teardown(company_b, user_b)


@pytest.mark.parametrize("status", ["REJECTED", "CANCELLED", "SUBMITTED"])
async def test_non_approved_application_cannot_create_projection(
    client: AsyncClient, seeded_plan_catalogue: None, status: str
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = (await _build_wired_employee(client, headers))["employee"]["id"]
        application = await _seed_leave_application(
            company_id=company_id,
            employee_id=employee_id,
            days=[(_DAY, "1.00", None, False)],
            status=status,
        )
        response = await _sync(
            client, headers, employee_id=employee_id, leave_application_id=application
        )
        assert response.status_code == 409, response.text
        assert _code(response) == "LEAVE_PROJECTION_APPLICATION_NOT_APPROVED"
        assert await _projection_count(company_id) == 0
        day = (
            await client.get(
                "/v1/attendance/days",
                headers=headers,
                params={"employee_id": employee_id, "date_from": _DAY, "date_to": _DAY},
            )
        ).json()["data"]
        assert all(d["attendance_status"] != "LEAVE" for d in day)
    finally:
        await _teardown(company_id, user_id)


async def test_approved_application_but_wrong_date_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = (await _build_wired_employee(client, headers))["employee"]["id"]
        application = await _seed_leave_application(
            company_id=company_id,
            employee_id=employee_id,
            days=[("2026-08-11", "1.00", None, False)],
        )
        response = await _sync(
            client,
            headers,
            employee_id=employee_id,
            leave_application_id=application,
            day=_DAY,
        )
        assert response.status_code == 422, response.text
        assert _code(response) == "LEAVE_PROJECTION_DATE_NOT_IN_APPLICATION"
        assert await _projection_count(company_id) == 0
    finally:
        await _teardown(company_id, user_id)


# --------------------------------------------- success + authoritative values (A, I-K)


async def test_valid_projection_mirrors_the_leave_day(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = (await _build_wired_employee(client, headers))["employee"]["id"]
        application = await _seed_leave_application(
            company_id=company_id,
            employee_id=employee_id,
            days=[(_DAY, "0.50", "SECOND_HALF", False)],
        )
        response = await _sync(
            client, headers, employee_id=employee_id, leave_application_id=application
        )
        assert response.status_code == 201, response.text
        data = response.json()["data"]
        assert data["employee_id"] == employee_id
        assert data["company_id"] == str(company_id)
        assert data["leave_application_id"] == application
        assert data["attendance_date"] == _DAY
        assert (data["fraction"], data["half"], data["is_paid"]) == ("0.50", "SECOND", True)
        assert data["leave_type_code"] is not None and data["leave_type_id"] is not None
        day = await _get_day(client, headers, employee_id=employee_id)
        assert (day["paid_day_fraction"], day["lop_fraction"]) == ("0.50", "0.50")
    finally:
        await _teardown(company_id, user_id)


async def test_request_cannot_override_authoritative_fraction_half_or_paid(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The approved day is a paid full day; a body claiming an unpaid half day cannot change it."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = (await _build_wired_employee(client, headers))["employee"]["id"]
        application = await _seed_leave_application(
            company_id=company_id, employee_id=employee_id, days=[(_DAY, "1.00", None, False)]
        )
        response = await _sync(
            client,
            headers,
            employee_id=employee_id,
            leave_application_id=application,
            fraction="0.50",
            half="FIRST",
            is_paid=False,
            send_values=True,
        )
        assert response.status_code == 201, response.text
        data = response.json()["data"]
        assert (data["fraction"], data["half"], data["is_paid"]) == ("1.00", None, True)
        day = await _get_day(client, headers, employee_id=employee_id)
        assert (day["paid_day_fraction"], day["lop_fraction"]) == ("1.00", "0.00")
    finally:
        await _teardown(company_id, user_id)


async def test_lop_day_and_unpaid_type_are_projected_unpaid_despite_paid_claim(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = (await _build_wired_employee(client, headers))["employee"]["id"]
        lop_application = await _seed_leave_application(
            company_id=company_id, employee_id=employee_id, days=[(_DAY, "1.00", None, True)]
        )
        response = await _sync(
            client,
            headers,
            employee_id=employee_id,
            leave_application_id=lop_application,
            is_paid=True,
            send_values=True,
        )
        assert response.status_code == 201, response.text
        assert response.json()["data"]["is_paid"] is False
        day = await _get_day(client, headers, employee_id=employee_id)
        assert (day["paid_day_fraction"], day["lop_fraction"]) == ("0.00", "1.00")
    finally:
        await _teardown(company_id, user_id)

    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = (await _build_wired_employee(client, headers))["employee"]["id"]
        unpaid_type = await _seed_leave_application(
            company_id=company_id,
            employee_id=employee_id,
            days=[(_DAY, "1.00", None, False)],
            is_paid_default=False,
        )
        response = await _sync(
            client,
            headers,
            employee_id=employee_id,
            leave_application_id=unpaid_type,
            is_paid=True,
            send_values=True,
        )
        assert response.json()["data"]["is_paid"] is False
    finally:
        await _teardown(company_id, user_id)


# ------------------------------------------------ cancel / resync / idempotency


async def test_cancelled_application_cannot_revive_a_cancelled_projection(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = (await _build_wired_employee(client, headers))["employee"]["id"]
        application = await _seed_leave_application(
            company_id=company_id, employee_id=employee_id, days=[(_DAY, "1.00", None, False)]
        )
        synced = await _sync(
            client, headers, employee_id=employee_id, leave_application_id=application
        )
        assert synced.status_code == 201, synced.text
        projection = synced.json()["data"]
        assert (await _get_day(client, headers, employee_id=employee_id))[
            "attendance_status"
        ] == "LEAVE"

        # The leave is cancelled: Leave cancels the projection and the application.
        cancelled = await client.post(
            f"/v1/leave-projections/{projection['id']}/cancel",
            headers={**headers, "If-Match": str(projection["version"])},
            json={"reason": "Leave application cancelled after approval"},
        )
        assert cancelled.status_code == 200, cancelled.text
        await _set_application_status(
            company_id=company_id, application_id=application, status="CANCELLED"
        )
        assert (await _get_day(client, headers, employee_id=employee_id))[
            "attendance_status"
        ] != "LEAVE"

        # cancelled application -> resync must not bring the projection back
        revive = await _sync(
            client, headers, employee_id=employee_id, leave_application_id=application
        )
        assert revive.status_code == 409, revive.text
        assert _code(revive) == "LEAVE_PROJECTION_APPLICATION_NOT_APPROVED"
        assert await _projection_count(company_id, status="APPROVED") == 0
        day = await _get_day(client, headers, employee_id=employee_id)
        assert day["attendance_status"] != "LEAVE"
        assert day["paid_day_fraction"] == "0.00"
    finally:
        await _teardown(company_id, user_id)


async def test_unrelated_application_cannot_revive_a_projection(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A cancelled projection's natural key includes its application; a different (even approved,
    same-employee) application does not touch it, and a non-covering one is refused."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = (await _build_wired_employee(client, headers))["employee"]["id"]
        original = await _seed_leave_application(
            company_id=company_id, employee_id=employee_id, days=[(_DAY, "1.00", None, False)]
        )
        synced = (
            await _sync(client, headers, employee_id=employee_id, leave_application_id=original)
        ).json()["data"]
        await client.post(
            f"/v1/leave-projections/{synced['id']}/cancel",
            headers={**headers, "If-Match": str(synced["version"])},
            json={"reason": "cancelled"},
        )
        await _set_application_status(
            company_id=company_id, application_id=original, status="CANCELLED"
        )
        unrelated = await _seed_leave_application(
            company_id=company_id,
            employee_id=employee_id,
            days=[("2026-08-12", "1.00", None, False)],
        )
        refused = await _sync(
            client, headers, employee_id=employee_id, leave_application_id=unrelated
        )
        assert refused.status_code == 422, refused.text
        assert await _projection_count(company_id, status="APPROVED") == 0
    finally:
        await _teardown(company_id, user_id)


async def test_repeated_sync_of_same_approved_day_is_idempotent(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = (await _build_wired_employee(client, headers))["employee"]["id"]
        application = await _seed_leave_application(
            company_id=company_id, employee_id=employee_id, days=[(_DAY, "1.00", None, False)]
        )
        first = await _sync(
            client, headers, employee_id=employee_id, leave_application_id=application
        )
        second = await _sync(
            client, headers, employee_id=employee_id, leave_application_id=application
        )
        assert first.status_code == second.status_code == 201
        assert first.json()["data"]["id"] == second.json()["data"]["id"]
        assert second.json()["data"]["source_version"] == 2
        assert await _projection_count(company_id) == 1
        day = await _get_day(client, headers, employee_id=employee_id)
        assert day["paid_day_fraction"] == "1.00"
    finally:
        await _teardown(company_id, user_id)
