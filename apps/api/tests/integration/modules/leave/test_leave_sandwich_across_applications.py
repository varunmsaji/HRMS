"""R-02 / D-12 — the sandwich rule across separate applications of the same leave type.

Calendar: Saturday and Sunday are weekly offs. Friday 2026-09-04 and Monday 2026-09-07 bracket the
weekend of 5-6 September. Applying for the two days separately must charge the weekend once, to
whichever application completes the sandwich, and releasing either side must give it back.
"""

import asyncio
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.leave.test_leave_application import (
    _create_employee,
    _create_employment,
    _create_leave_type,
    _create_legal_entity,
    _get_balance,
    _give_balance,
    _register_tenant,
    _setup_leave_policy,
    _submit,
    _teardown,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.leave.service import LeaveApplicationService

pytestmark = pytest.mark.asyncio

FRI, SAT, SUN, MON = "2026-09-04", "2026-09-05", "2026-09-06", "2026-09-07"


async def _setup(client: AsyncClient, headers: dict[str, str], **policy: Any) -> dict[str, Any]:
    employee = await _create_employee(client, headers)
    legal_entity = await _create_legal_entity(client, headers)
    await _create_employment(
        client, headers, employee_id=employee["id"], legal_entity_id=legal_entity["id"]
    )
    leave_type = await _create_leave_type(client, headers)
    pattern = await client.post(
        "/v1/weekly-off-patterns",
        headers=headers,
        json={
            "name": "Saturday and Sunday off",
            "pattern_kind": "FIXED_WEEKDAYS",
            "rules": [
                {"weekday": 5, "off_fraction": "1.00"},
                {"weekday": 6, "off_fraction": "1.00"},
            ],
        },
    )
    assert pattern.status_code == 201, pattern.text
    calendar = await client.post(
        "/v1/work-calendars",
        headers=headers,
        json={"name": "Five-day week", "weekly_off_pattern_id": pattern.json()["data"]["id"]},
    )
    assert calendar.status_code == 201, calendar.text
    assigned = await client.post(
        "/v1/policy-assignments",
        headers=headers,
        json={
            "policy_kind": "WORK_CALENDAR",
            "policy_id": calendar.json()["data"]["id"],
            "scope_type": "COMPANY",
            "effective_from": "2024-01-01",
        },
    )
    assert assigned.status_code == 201, assigned.text
    await _setup_leave_policy(client, headers, leave_type_id=leave_type["id"], **policy)
    await _give_balance(client, headers, employee_id=employee["id"], leave_type_id=leave_type["id"])
    return {"employee_id": employee["id"], "leave_type_id": leave_type["id"]}


async def _apply(
    client: AsyncClient, headers: dict[str, str], ctx: dict[str, Any], day: str, **extra: Any
) -> dict[str, Any]:
    response = await _submit(
        client,
        headers,
        employee_id=ctx["employee_id"],
        leave_type_id=extra.pop("leave_type_id", ctx["leave_type_id"]),
        start_date=day,
        end_date=day,
        **extra,
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _get(client: AsyncClient, headers: dict[str, str], application_id: str) -> dict[str, Any]:
    response = await client.get(f"/v1/leave-applications/{application_id}", headers=headers)
    assert response.status_code == 200, response.text
    return dict(response.json()["data"])


def _dates(application: dict[str, Any]) -> list[str]:
    return [day["calendar_date"] for day in application["days"]]


async def _cancel(
    client: AsyncClient, headers: dict[str, str], application: dict[str, Any]
) -> dict[str, Any]:
    response = await client.post(
        f"/v1/leave-applications/{application['id']}/cancel",
        headers={**headers, "If-Match": str(application["version"])},
        json={"reason": "Plans changed"},
    )
    assert response.status_code == 200, response.text
    return dict(response.json()["data"])


async def _projection_statuses(company_id: Any, application_id: str) -> dict[str, str]:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        rows = (
            await session.execute(
                text(
                    "SELECT attendance_date, status FROM leave_day_projection "
                    "WHERE company_id = :cid AND leave_application_id = :aid"
                ),
                {"cid": str(company_id), "aid": application_id},
            )
        ).all()
    return {row[0].isoformat(): row[1] for row in rows}


async def test_monday_after_friday_takes_the_weekend(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup(client, headers)
        friday = await _apply(client, headers, ctx, FRI)
        monday = await _apply(client, headers, ctx, MON)

        assert friday["total_days"] == "1.00"
        assert monday["total_days"] == "3.00"
        assert monday["start_date"] == SAT and monday["end_date"] == MON
        assert _dates(monday) == [SAT, SUN, MON]
        by_date = {d["calendar_date"]: d for d in monday["days"]}
        assert by_date[SAT]["is_sandwich_generated"] is True
        assert by_date[MON]["is_sandwich_generated"] is False
        assert await _get_balance(client, headers, ctx["employee_id"]) == "16.00"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_friday_after_monday_takes_the_weekend(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup(client, headers)
        monday = await _apply(client, headers, ctx, MON)
        friday = await _apply(client, headers, ctx, FRI)

        assert monday["total_days"] == "1.00"
        assert _dates(friday) == [FRI, SAT, SUN]
        assert friday["end_date"] == SUN
        assert await _get_balance(client, headers, ctx["employee_id"]) == "16.00"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_cancelling_the_anchor_releases_and_refunds_the_weekend(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup(client, headers)
        friday = await _apply(client, headers, ctx, FRI)
        monday = await _apply(client, headers, ctx, MON)
        assert await _get_balance(client, headers, ctx["employee_id"]) == "16.00"

        await _cancel(client, headers, friday)

        monday = await _get(client, headers, monday["id"])
        assert monday["status"] == "APPROVED"
        assert _dates(monday) == [MON]
        assert monday["total_days"] == "1.00"
        assert monday["start_date"] == MON
        # Friday's own day and the two released weekend days both come back.
        assert await _get_balance(client, headers, ctx["employee_id"]) == "19.00"
        statuses = await _projection_statuses(company_id, monday["id"])
        assert statuses[SAT] == "CANCELLED" and statuses[SUN] == "CANCELLED"
        assert statuses[MON] == "APPROVED"

        # Cancelling Monday afterwards refunds only what is still owed: no double refund.
        await _cancel(client, headers, monday)
        assert await _get_balance(client, headers, ctx["employee_id"]) == "20.00"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_cancelling_the_dependent_refunds_it_in_full_and_keeps_the_anchor(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup(client, headers)
        friday = await _apply(client, headers, ctx, FRI)
        monday = await _apply(client, headers, ctx, MON)

        await _cancel(client, headers, monday)

        friday = await _get(client, headers, friday["id"])
        assert friday["status"] == "APPROVED" and _dates(friday) == [FRI]
        assert await _get_balance(client, headers, ctx["employee_id"]) == "19.00"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_rejecting_a_pending_anchor_releases_the_weekend_from_a_pending_dependent(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup(client, headers, approval_chain="HR")
        friday = await _apply(client, headers, ctx, FRI)
        monday = await _apply(client, headers, ctx, MON)
        assert friday["status"] == "SUBMITTED" and monday["total_days"] == "3.00"

        rejected = await client.post(
            f"/v1/leave-applications/{friday['id']}/reject",
            headers={**headers, "If-Match": str(friday["version"])},
            json={"rejection_reason": "Team is short that day"},
        )
        assert rejected.status_code == 200, rejected.text

        monday = await _get(client, headers, monday["id"])
        assert monday["status"] == "SUBMITTED"
        assert _dates(monday) == [MON] and monday["total_days"] == "1.00"
        actions = [a["action"] for a in monday["actions"]]
        assert "SANDWICH_LINKED" in actions and "SANDWICH_RELEASED" in actions
        # Nothing was ever debited, so nothing moves.
        assert await _get_balance(client, headers, ctx["employee_id"]) == "20.00"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_cancelling_the_anchor_while_a_bridge_is_being_submitted_still_releases_it(
    client: AsyncClient, seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Monday's submission has found Friday as its anchor but not yet committed when Friday is
    cancelled. The cancellation must wait for it and then release the weekend; otherwise its scan
    sees no dependents and Monday commits a weekend charged to a cancelled anchor."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup(client, headers)
        friday = await _apply(client, headers, ctx, FRI)

        real = LeaveApplicationService._cross_application_bridges
        found = asyncio.Event()

        async def parked(self: Any, *args: Any, **kwargs: Any) -> Any:
            bridges = await real(self, *args, **kwargs)
            found.set()
            await asyncio.sleep(1.0)
            return bridges

        monkeypatch.setattr(LeaveApplicationService, "_cross_application_bridges", parked)
        submitting = asyncio.create_task(_apply(client, headers, ctx, MON))
        await asyncio.wait_for(found.wait(), timeout=10)
        monkeypatch.setattr(LeaveApplicationService, "_cross_application_bridges", real)
        await _cancel(client, headers, friday)
        monday = await submitting

        monday = await _get(client, headers, monday["id"])
        assert _dates(monday) == [MON] and monday["total_days"] == "1.00"
        assert await _get_balance(client, headers, ctx["employee_id"]) == "19.00"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_no_bridge_when_the_sandwich_rule_is_off(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup(client, headers, sandwich_rule_enabled=False)
        await _apply(client, headers, ctx, FRI)
        monday = await _apply(client, headers, ctx, MON)
        assert _dates(monday) == [MON]
        assert await _get_balance(client, headers, ctx["employee_id"]) == "18.00"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_no_bridge_from_a_half_day(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup(client, headers)
        await _apply(client, headers, ctx, FRI, half_day="SECOND_HALF")
        monday = await _apply(client, headers, ctx, MON)
        assert _dates(monday) == [MON]
        assert await _get_balance(client, headers, ctx["employee_id"]) == "18.50"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_no_bridge_from_another_leave_type(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup(client, headers)
        other = await _create_leave_type(client, headers, code="CL", name="Casual Leave")
        await _setup_leave_policy(client, headers, leave_type_id=other["id"])
        await _give_balance(
            client, headers, employee_id=ctx["employee_id"], leave_type_id=other["id"]
        )
        await _apply(client, headers, ctx, FRI, leave_type_id=other["id"])
        monday = await _apply(client, headers, ctx, MON)
        assert _dates(monday) == [MON]
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_one_application_over_the_weekend_is_unchanged(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup(client, headers)
        response = await _submit(
            client,
            headers,
            employee_id=ctx["employee_id"],
            leave_type_id=ctx["leave_type_id"],
            start_date=FRI,
            end_date=MON,
        )
        assert response.status_code == 201, response.text
        data = response.json()["data"]
        assert data["total_days"] == "4.00" and data["start_date"] == FRI
        assert await _get_balance(client, headers, ctx["employee_id"]) == "16.00"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_leave_on_the_first_day_of_the_calendar_is_not_refused(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The look-back for a bridge stops where the employee's calendar starts (2024-01-01, a
    Monday); it must not turn into a "calendar not resolved" refusal."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup(client, headers)
        first_day = await _apply(client, headers, ctx, "2024-01-01")
        assert _dates(first_day) == ["2024-01-01"]
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
