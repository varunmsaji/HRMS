"""Integration tests for leave balance safety, step 2a — PAY-010 (balance re-checked at final
approval; overdraw → reject or "approve with excess as LOP") and PAY-011 (`allow_negative_balance`
enforced with a `negative_balance_floor`). Rules: `docs/audits/PAYROLL_BUSINESS_DECISIONS.md`
decisions 8 and 9.

Reuses `test_leave_application.py`'s setup helpers."""

from typing import Any

import pytest
from httpx import AsyncClient
from tests.integration.modules.leave.test_leave_application import (
    _create_leave_type,
    _get_balance,
    _register_tenant,
    _setup_full,
    _submit,
    _teardown,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

pytestmark = pytest.mark.asyncio


async def _approve(
    client: AsyncClient, headers: dict[str, str], application: dict[str, Any], **body: Any
) -> Any:
    return await client.post(
        f"/v1/leave-applications/{application['id']}/approve",
        headers={**headers, "If-Match": str(application["version"])},
        json=body,
    )


async def test_second_approval_that_would_overdraw_is_refused_with_the_shortfall(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """PAY-010's failure scenario: two applications both pass the submit-time check against the
    same balance; the second approval must not drive the balance negative."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, approval_chain="HR", balance="2.00")
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]

        first = await _submit(
            client,
            headers,
            employee_id=employee_id,
            leave_type_id=leave_type_id,
            start_date="2026-09-08",
            end_date="2026-09-09",
        )
        second = await _submit(
            client,
            headers,
            employee_id=employee_id,
            leave_type_id=leave_type_id,
            start_date="2026-09-10",
            end_date="2026-09-10",
        )
        assert first.status_code == 201, first.text
        assert second.status_code == 201, second.text

        approved = await _approve(client, headers, first.json()["data"])
        assert approved.status_code == 200, approved.text
        assert await _get_balance(client, headers, employee_id) == "0.00"

        refused = await _approve(client, headers, second.json()["data"])
        assert refused.status_code == 409, refused.text
        error = refused.json()["error"]
        assert error["code"] == "LEAVE_APPLICATION_BALANCE_SHORTFALL"
        assert error["details"][0]["context"]["shortfall"] == "1.00"
        # Nothing was written — the application is still waiting, the balance untouched.
        assert await _get_balance(client, headers, employee_id) == "0.00"
        still = await client.get(
            f"/v1/leave-applications/{second.json()['data']['id']}", headers=headers
        )
        assert still.json()["data"]["status"] == "SUBMITTED"

        # The approver chooses to approve the excess as loss of pay.
        as_lop = await _approve(client, headers, still.json()["data"], excess_as_lop=True)
        assert as_lop.status_code == 200, as_lop.text
        data = as_lop.json()["data"]
        assert data["status"] == "APPROVED"
        assert data["lop_days"] == "1.00"
        assert data["days"][0]["is_lop"] is True
        assert "EXCESS_AS_LOP" in [a["action"] for a in data["actions"]]
        assert await _get_balance(client, headers, employee_id) == "0.00"
        projection = await client.get(
            f"/v1/leave-projections/{data['days'][0]['leave_day_projection_id']}",
            headers=headers,
        )
        assert projection.json()["data"]["is_paid"] is False

        # Cancelling it credits back only what was debited — nothing.
        cancelled = await client.post(
            f"/v1/leave-applications/{data['id']}/cancel",
            headers={**headers, "If-Match": str(data["version"])},
            json={"reason": "Approved in error"},
        )
        assert cancelled.status_code == 200, cancelled.text
        assert await _get_balance(client, headers, employee_id) == "0.00"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_excess_as_lop_covers_the_earliest_days_first(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, approval_chain="HR", balance="3.00")
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]

        first = await _submit(client, headers, employee_id=employee_id, leave_type_id=leave_type_id)
        second = await _submit(
            client,
            headers,
            employee_id=employee_id,
            leave_type_id=leave_type_id,
            start_date="2026-09-09",
            end_date="2026-09-10",
        )
        assert (await _approve(client, headers, first.json()["data"])).status_code == 200
        # Balance now 2.00; top it down to 1.00 so the 2-day application is one day short.
        await _submit(
            client,
            headers,
            employee_id=employee_id,
            leave_type_id=leave_type_id,
            start_date="2026-09-14",
            end_date="2026-09-14",
        )
        listed = await client.get(
            "/v1/leave-applications",
            headers=headers,
            params={"employee_id": employee_id, "status": "SUBMITTED"},
        )
        third = next(a for a in listed.json()["data"] if a["start_date"] == "2026-09-14")
        assert (await _approve(client, headers, third)).status_code == 200
        assert await _get_balance(client, headers, employee_id) == "1.00"

        approved = await _approve(client, headers, second.json()["data"], excess_as_lop=True)
        assert approved.status_code == 200, approved.text
        data = approved.json()["data"]
        assert data["lop_days"] == "1.00"
        assert [(d["calendar_date"], d["is_lop"]) for d in data["days"]] == [
            ("2026-09-09", False),
            ("2026-09-10", True),
        ]
        assert await _get_balance(client, headers, employee_id) == "0.00"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_negative_balance_allowed_down_to_the_floor(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """PAY-011 / decision 8 — e.g. sick leave allowed down to −1."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(
            client,
            headers,
            balance="1.00",
            allow_negative_balance=True,
            negative_balance_floor="1.00",
        )
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]

        two_days = await _submit(
            client,
            headers,
            employee_id=employee_id,
            leave_type_id=leave_type_id,
            start_date="2026-09-08",
            end_date="2026-09-09",
        )
        assert two_days.status_code == 201, two_days.text
        assert two_days.json()["data"]["status"] == "APPROVED"  # AUTO chain
        assert await _get_balance(client, headers, employee_id) == "-1.00"

        beyond_floor = await _submit(
            client,
            headers,
            employee_id=employee_id,
            leave_type_id=leave_type_id,
            start_date="2026-09-10",
            end_date="2026-09-10",
        )
        assert beyond_floor.status_code == 422, beyond_floor.text
        assert beyond_floor.json()["error"]["code"] == "LEAVE_APPLICATION_INSUFFICIENT_BALANCE"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_publish_refuses_negative_balance_without_a_floor(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        leave_type = await _create_leave_type(client, headers)
        policy = await client.post(
            "/v1/leave-policies",
            headers=headers,
            json={"name": "Sick", "leave_type_id": leave_type["id"]},
        )
        policy_id = policy.json()["data"]["id"]
        draft = await client.post(
            f"/v1/leave-policies/{policy_id}/versions",
            headers=headers,
            json={"effective_from": "2024-01-01", "allow_negative_balance": True},
        )
        assert draft.status_code == 201, draft.text
        published = await client.post(
            f"/v1/leave-policies/{policy_id}/versions/{draft.json()['data']['id']}/publish",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert published.status_code == 422, published.text
        assert "negative_balance_floor" in published.json()["error"]["message"]
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
