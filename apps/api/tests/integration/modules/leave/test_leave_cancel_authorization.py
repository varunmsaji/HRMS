"""Integration tests for leave balance safety, step 2 — who may cancel an approved leave
(`docs/audits/PAYROLL_BUSINESS_DECISIONS.md` decision 10).

The employee may cancel their own approved leave only before it starts; after that only a
company-scoped `LEAVE.APPLICATION_CANCEL_APPROVED` holder (HR) may, with a mandatory reason.
Managers never cancel approved leave — not even one they submitted.

"Started" is measured against the company's business date (today), so already-started leave
uses 2026-09-08 (the shared `_submit` default) and not-yet-started leave uses 2030-03-05."""

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from tests.integration.modules.attendance.test_attendance_security import (
    _cleanup_scoped_users,
    _create_permission_scoped_user,
)
from tests.integration.modules.leave.test_leave_application import (
    _get_balance,
    _register_tenant,
    _setup_full,
    _submit,
    _teardown,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.modules.leave.permissions import (
    LEAVE_APPLICATION_APPROVE,
    LEAVE_APPLICATION_CANCEL_APPROVED,
    LEAVE_APPLICATION_SUBMIT,
    LEAVE_APPLICATION_SUBMIT_ON_BEHALF,
)

pytestmark = pytest.mark.asyncio

_FUTURE_DAY = "2030-03-05"  # a Tuesday


async def _cancel(
    client: AsyncClient, headers: dict[str, str], application: dict[str, Any], **body: Any
) -> Any:
    return await client.post(
        f"/v1/leave-applications/{application['id']}/cancel",
        headers={**headers, "If-Match": str(application["version"])},
        json=body or None,
    )


async def _approved_leave(
    client: AsyncClient, headers: dict[str, str], ctx: dict[str, Any], *, day: str
) -> dict[str, Any]:
    submitted = await _submit(
        client,
        headers,
        employee_id=ctx["employee"]["id"],
        leave_type_id=ctx["leave_type"]["id"],
        start_date=day,
        end_date=day,
    )
    assert submitted.status_code == 201, submitted.text
    data = dict(submitted.json()["data"])
    assert data["status"] == "APPROVED"
    return data


async def _employee_headers(company_id: UUID, employee_id: str) -> dict[str, str]:
    headers, _ = await _create_permission_scoped_user(
        company_id=company_id,
        permission_codes=[LEAVE_APPLICATION_SUBMIT],
        data_scope="SELF",
        caller_employee_id=UUID(employee_id),
    )
    return headers


async def test_employee_cancels_own_approved_leave_before_it_starts(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers)
        employee_id = ctx["employee"]["id"]
        leave = await _approved_leave(client, headers, ctx, day=_FUTURE_DAY)
        assert await _get_balance(client, headers, employee_id) == "19.00"

        employee_headers = await _employee_headers(company_id, employee_id)
        cancelled = await _cancel(client, employee_headers, leave)
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["data"]["status"] == "CANCELLED"
        assert cancelled.json()["data"]["cancellation_reason"] is None
        assert await _get_balance(client, headers, employee_id) == "20.00"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_employee_cannot_cancel_own_approved_leave_after_it_starts(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers)
        employee_id = ctx["employee"]["id"]
        leave = await _approved_leave(client, headers, ctx, day="2026-09-08")

        employee_headers = await _employee_headers(company_id, employee_id)
        refused = await _cancel(client, employee_headers, leave, reason="Came to work")
        assert refused.status_code == 403, refused.text
        assert await _get_balance(client, headers, employee_id) == "19.00"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_manager_cannot_cancel_approved_leave_even_one_they_submitted(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Before decision 10 the original submitter could always cancel — a manager who applied on
    an employee's behalf could reverse approved leave. Now only the employee (before start) or
    HR may."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers)
        employee_id = ctx["employee"]["id"]
        manager_headers, _ = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[LEAVE_APPLICATION_SUBMIT_ON_BEHALF, LEAVE_APPLICATION_APPROVE],
        )
        leave = await _approved_leave(client, manager_headers, ctx, day=_FUTURE_DAY)

        refused = await _cancel(client, manager_headers, leave)
        assert refused.status_code == 403, refused.text
        assert await _get_balance(client, headers, employee_id) == "19.00"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_hr_cancels_started_leave_only_with_a_reason(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers)
        employee_id = ctx["employee"]["id"]
        leave = await _approved_leave(client, headers, ctx, day="2026-09-08")
        hr_headers, _ = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=[LEAVE_APPLICATION_CANCEL_APPROVED]
        )

        missing = await _cancel(client, hr_headers, leave)
        assert missing.status_code == 422, missing.text
        assert missing.json()["error"]["code"] == "LEAVE_APPLICATION_CANCEL_REASON_REQUIRED"
        blank = await _cancel(client, hr_headers, leave, reason="   ")
        assert blank.status_code == 422, blank.text
        assert await _get_balance(client, headers, employee_id) == "19.00"

        cancelled = await _cancel(client, hr_headers, leave, reason="Employee was on duty")
        assert cancelled.status_code == 200, cancelled.text
        data = cancelled.json()["data"]
        assert data["status"] == "CANCELLED"
        assert data["cancellation_reason"] == "Employee was on duty"
        cancel_actions = [a for a in data["actions"] if a["action"] == "CANCELLED"]
        assert cancel_actions[-1]["comment"] == "Employee was on duty"
        assert await _get_balance(client, headers, employee_id) == "20.00"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()
