"""Integration tests for Leave Combination Rules (LEAVE_DECISION_LOG.md LD-16, client spec §7).

Reuses `_create_employee`/`_create_legal_entity`/`_create_employment`/`_create_leave_type`/
`_setup_calendar`/`_setup_leave_policy`/`_give_balance`/`_register_tenant`/`_cleanup`/`_teardown`
from `test_leave_application.py` — the same cross-file reuse pattern every other Leave test file
in this suite already established. `approval_chain="HR"` throughout (no manager resolution
needed); dates are all Tuesdays/single days on the Sunday-off calendar `_setup_calendar` assigns.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from tests.integration.modules.leave.test_leave_application import (
    _cleanup,
    _create_employee,
    _create_employment,
    _create_leave_type,
    _create_legal_entity,
    _give_balance,
    _register_tenant,
    _setup_calendar,
    _setup_leave_policy,
    _teardown,
)

pytestmark = pytest.mark.asyncio


async def _setup_two_types(
    client: AsyncClient, headers: dict[str, str], *, cl_chain: str = "HR", sl_chain: str = "HR"
) -> dict[str, Any]:
    employee = await _create_employee(client, headers)
    legal_entity = await _create_legal_entity(client, headers)
    await _create_employment(
        client, headers, employee_id=employee["id"], legal_entity_id=legal_entity["id"]
    )
    await _setup_calendar(client, headers)
    cl = await _create_leave_type(client, headers, code="CL", name="Casual Leave")
    sl = await _create_leave_type(client, headers, code="SL", name="Sick Leave")
    await _setup_leave_policy(client, headers, leave_type_id=cl["id"], approval_chain=cl_chain)
    await _setup_leave_policy(client, headers, leave_type_id=sl["id"], approval_chain=sl_chain)
    await _give_balance(
        client, headers, employee_id=employee["id"], leave_type_id=cl["id"], amount="10.00"
    )
    await _give_balance(
        client, headers, employee_id=employee["id"], leave_type_id=sl["id"], amount="10.00"
    )
    return {"employee": employee, "cl": cl, "sl": sl}


async def _submit_on(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    employee_id: str,
    leave_type_id: str,
    day: str = "2026-09-08",
) -> Any:
    return await client.post(
        "/v1/leave-applications",
        headers=headers,
        json={
            "employee_id": employee_id,
            "leave_type_id": leave_type_id,
            "start_date": day,
            "end_date": day,
        },
    )


async def _create_rule(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    leave_type_id_a: str,
    leave_type_id_b: str,
    allowed: bool,
) -> Any:
    return await client.post(
        "/v1/leave-combination-rules",
        headers=headers,
        json={
            "leave_type_id_a": leave_type_id_a,
            "leave_type_id_b": leave_type_id_b,
            "allowed": allowed,
            "reason": "test",
        },
    )


async def test_no_rule_means_allowed(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_two_types(client, headers)
        employee_id = ctx["employee"]["id"]

        cl_app = await _submit_on(
            client, headers, employee_id=employee_id, leave_type_id=ctx["cl"]["id"]
        )
        assert cl_app.status_code == 201, cl_app.text

        sl_app = await _submit_on(
            client, headers, employee_id=employee_id, leave_type_id=ctx["sl"]["id"]
        )
        assert sl_app.status_code == 201, sl_app.text
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_explicit_not_allowed_rule_blocks_overlapping_submission(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_two_types(client, headers)
        employee_id = ctx["employee"]["id"]

        rule = await _create_rule(
            client,
            headers,
            leave_type_id_a=ctx["cl"]["id"],
            leave_type_id_b=ctx["sl"]["id"],
            allowed=False,
        )
        assert rule.status_code == 201, rule.text

        cl_app = await _submit_on(
            client, headers, employee_id=employee_id, leave_type_id=ctx["cl"]["id"]
        )
        assert cl_app.status_code == 201, cl_app.text

        # SL on the same day as an active CL application -> blocked by the rule.
        sl_app = await _submit_on(
            client, headers, employee_id=employee_id, leave_type_id=ctx["sl"]["id"]
        )
        assert sl_app.status_code == 422, sl_app.text
        assert sl_app.json()["error"]["code"] == "LEAVE_APPLICATION_COMBINATION_NOT_ALLOWED"

        # Same block applies in the reverse direction (SL first, then CL) — the pair is
        # unordered regardless of how the rule or the applications were created.
        different_day_sl = await _submit_on(
            client,
            headers,
            employee_id=employee_id,
            leave_type_id=ctx["sl"]["id"],
            day="2026-09-09",
        )
        assert different_day_sl.status_code == 201, different_day_sl.text
        blocked_cl = await _submit_on(
            client,
            headers,
            employee_id=employee_id,
            leave_type_id=ctx["cl"]["id"],
            day="2026-09-09",
        )
        assert blocked_cl.status_code == 422, blocked_cl.text
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_explicit_allowed_rule_permits_combination(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_two_types(client, headers)
        employee_id = ctx["employee"]["id"]

        rule = await _create_rule(
            client,
            headers,
            leave_type_id_a=ctx["cl"]["id"],
            leave_type_id_b=ctx["sl"]["id"],
            allowed=True,
        )
        assert rule.status_code == 201, rule.text

        cl_app = await _submit_on(
            client, headers, employee_id=employee_id, leave_type_id=ctx["cl"]["id"]
        )
        assert cl_app.status_code == 201, cl_app.text
        sl_app = await _submit_on(
            client, headers, employee_id=employee_id, leave_type_id=ctx["sl"]["id"]
        )
        assert sl_app.status_code == 201, sl_app.text
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_rejected_application_no_longer_blocks(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_two_types(client, headers)
        employee_id = ctx["employee"]["id"]

        rule = await _create_rule(
            client,
            headers,
            leave_type_id_a=ctx["cl"]["id"],
            leave_type_id_b=ctx["sl"]["id"],
            allowed=False,
        )
        assert rule.status_code == 201, rule.text

        cl_app = await _submit_on(
            client, headers, employee_id=employee_id, leave_type_id=ctx["cl"]["id"]
        )
        cl_id = cl_app.json()["data"]["id"]

        rejected = await client.post(
            f"/v1/leave-applications/{cl_id}/reject",
            headers={**headers, "If-Match": "1"},
            json={"rejection_reason": "test"},
        )
        assert rejected.status_code == 200, rejected.text

        # The CL application is REJECTED now, not active — SL on the same day is no longer
        # blocked.
        sl_app = await _submit_on(
            client, headers, employee_id=employee_id, leave_type_id=ctx["sl"]["id"]
        )
        assert sl_app.status_code == 201, sl_app.text
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_rule_crud_and_duplicate_pair_conflict(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_two_types(client, headers)

        created = await _create_rule(
            client,
            headers,
            leave_type_id_a=ctx["cl"]["id"],
            leave_type_id_b=ctx["sl"]["id"],
            allowed=False,
        )
        assert created.status_code == 201, created.text
        rule_id = created.json()["data"]["id"]

        listed = await client.get("/v1/leave-combination-rules", headers=headers)
        assert listed.status_code == 200, listed.text
        assert len(listed.json()["data"]) == 1

        # Same pair, opposite order -> conflicts with the existing rule (unordered pair, LD-16).
        duplicate = await _create_rule(
            client,
            headers,
            leave_type_id_a=ctx["sl"]["id"],
            leave_type_id_b=ctx["cl"]["id"],
            allowed=True,
        )
        assert duplicate.status_code == 409, duplicate.text
        assert duplicate.json()["error"]["code"] == "LEAVE_COMBINATION_RULE_ALREADY_EXISTS"

        deleted = await client.delete(f"/v1/leave-combination-rules/{rule_id}", headers=headers)
        assert deleted.status_code == 204, deleted.text

        # Already deleted -> not found.
        second_delete = await client.delete(
            f"/v1/leave-combination-rules/{rule_id}", headers=headers
        )
        assert second_delete.status_code == 404, second_delete.text

        listed_after = await client.get("/v1/leave-combination-rules", headers=headers)
        assert listed_after.json()["data"] == []
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
