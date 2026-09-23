"""Integration tests for leave balance safety, step 2 — closing the attendance period locks leave
for its dates (`docs/audits/PAYROLL_BUSINESS_DECISIONS.md` PD-3).

Apply, approve, and cancelling approved leave on a date inside a `CLOSED` period are refused
with `LEAVE_APPLICATION_PERIOD_CLOSED`. Withdrawing a still-pending application stays allowed —
it never touched attendance, and blocking it would strand the application."""

from typing import Any

import pytest
from httpx import AsyncClient
from tests.integration.modules.attendance.test_attendance_period import (
    _cleanup_attendance_period,
    _insert_closed_period,
)
from tests.integration.modules.leave.test_leave_application import (
    _get_balance,
    _register_tenant,
    _setup_full,
    _submit,
    _teardown,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

pytestmark = pytest.mark.asyncio


def _assert_period_closed(response: Any, *, period_start: str, period_end: str) -> None:
    assert response.status_code == 409, response.text
    error = response.json()["error"]
    assert error["code"] == "LEAVE_APPLICATION_PERIOD_CLOSED"
    assert error["details"][0]["context"] == {
        "period_start": period_start,
        "period_end": period_end,
    }


async def test_apply_refused_when_any_date_is_in_a_closed_period(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers)
        employee_id = ctx["employee"]["id"]
        await _insert_closed_period(
            company_id=company_id, period_start="2026-08-01", period_end="2026-08-31"
        )

        # Only the first day falls in the closed period — the whole application is refused.
        refused = await _submit(
            client,
            headers,
            employee_id=employee_id,
            leave_type_id=ctx["leave_type"]["id"],
            start_date="2026-08-31",
            end_date="2026-09-01",
        )
        _assert_period_closed(refused, period_start="2026-08-01", period_end="2026-08-31")
        assert await _get_balance(client, headers, employee_id) == "20.00"

        # The next period is still open.
        allowed = await _submit(
            client,
            headers,
            employee_id=employee_id,
            leave_type_id=ctx["leave_type"]["id"],
            start_date="2026-09-01",
            end_date="2026-09-01",
        )
        assert allowed.status_code == 201, allowed.text
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_another_legal_entitys_closed_period_does_not_block_leave(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Decision 14 — periods are per legal entity; only the employee's own entity's closed
    period locks their leave."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers)
        employee_id = ctx["employee"]["id"]
        other_entity = await client.post(
            "/v1/legal-entities", headers=headers, json={"name": "Other LE"}
        )
        assert other_entity.status_code == 201, other_entity.text
        await _insert_closed_period(
            company_id=company_id,
            period_start="2026-08-01",
            period_end="2026-08-31",
            legal_entity_id=other_entity.json()["data"]["id"],
        )

        allowed = await _submit(
            client,
            headers,
            employee_id=employee_id,
            leave_type_id=ctx["leave_type"]["id"],
            start_date="2026-08-20",
            end_date="2026-08-20",
        )
        assert allowed.status_code == 201, allowed.text
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_approve_refused_after_the_period_closes_but_withdraw_allowed(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, approval_chain="HR")
        employee_id = ctx["employee"]["id"]
        submitted = await _submit(
            client, headers, employee_id=employee_id, leave_type_id=ctx["leave_type"]["id"]
        )
        assert submitted.status_code == 201, submitted.text
        pending = submitted.json()["data"]
        assert pending["status"] == "SUBMITTED"

        await _insert_closed_period(
            company_id=company_id, period_start="2026-09-01", period_end="2026-09-30"
        )
        refused = await client.post(
            f"/v1/leave-applications/{pending['id']}/approve",
            headers={**headers, "If-Match": str(pending["version"])},
            json={},
        )
        _assert_period_closed(refused, period_start="2026-09-01", period_end="2026-09-30")
        assert await _get_balance(client, headers, employee_id) == "20.00"

        withdrawn = await client.post(
            f"/v1/leave-applications/{pending['id']}/cancel",
            headers={**headers, "If-Match": str(pending["version"])},
        )
        assert withdrawn.status_code == 200, withdrawn.text
        assert withdrawn.json()["data"]["status"] == "CANCELLED"
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_cancel_of_approved_leave_refused_after_the_period_closes(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Even HR, with a reason: a correction after close flows as arrears (decision 15), or via
    reopening the period before payroll is finalized."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers)
        employee_id = ctx["employee"]["id"]
        submitted = await _submit(
            client, headers, employee_id=employee_id, leave_type_id=ctx["leave_type"]["id"]
        )
        approved = submitted.json()["data"]
        assert approved["status"] == "APPROVED"

        await _insert_closed_period(
            company_id=company_id, period_start="2026-09-01", period_end="2026-09-30"
        )
        refused = await client.post(
            f"/v1/leave-applications/{approved['id']}/cancel",
            headers={**headers, "If-Match": str(approved["version"])},
            json={"reason": "Employee was on duty"},
        )
        _assert_period_closed(refused, period_start="2026-09-01", period_end="2026-09-30")
        assert await _get_balance(client, headers, employee_id) == "19.00"
        still = await client.get(f"/v1/leave-applications/{approved['id']}", headers=headers)
        assert still.json()["data"]["status"] == "APPROVED"
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
