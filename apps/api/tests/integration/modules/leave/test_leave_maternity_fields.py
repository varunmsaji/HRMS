"""Integration tests for maternity-specific informational fields (LEAVE_DECISION_LOG.md LD-17,
client spec §F).

Reuses `_setup_full`/`_submit`/`_register_tenant`/`_cleanup`/`_teardown` from
`test_leave_application.py` — the same cross-file reuse pattern every other Leave test file in
this suite already established. Both fields are purely informational (never read by day-
counting or balance logic), so these tests only confirm round-trip persistence, not any new
business rule.
"""

import pytest
from httpx import AsyncClient
from tests.integration.modules.leave.test_leave_application import (
    _cleanup,
    _register_tenant,
    _setup_full,
    _submit,
    _teardown,
)

pytestmark = pytest.mark.asyncio


async def test_pre_post_delivery_days_round_trip_on_policy_version(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(
            client,
            headers,
            approval_chain="HR",
            pre_delivery_days=42,
            post_delivery_days=84,
        )
        policy_id = ctx["policy"]["id"]

        versions = await client.get(f"/v1/leave-policies/{policy_id}/versions", headers=headers)
        assert versions.status_code == 200, versions.text
        version = versions.json()["data"][0]
        assert version["pre_delivery_days"] == 42
        assert version["post_delivery_days"] == 84
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_expected_delivery_date_round_trips_on_application(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, approval_chain="HR")
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]

        submitted = await _submit(
            client,
            headers,
            employee_id=employee_id,
            leave_type_id=leave_type_id,
            expected_delivery_date="2026-12-01",
        )
        assert submitted.status_code == 201, submitted.text
        data = submitted.json()["data"]
        assert data["expected_delivery_date"] == "2026-12-01"

        # Also round-trips on a plain GET, not just the creation response.
        fetched = await client.get(f"/v1/leave-applications/{data['id']}", headers=headers)
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["data"]["expected_delivery_date"] == "2026-12-01"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_expected_delivery_date_is_optional(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, approval_chain="HR")
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]

        submitted = await _submit(
            client, headers, employee_id=employee_id, leave_type_id=leave_type_id
        )
        assert submitted.status_code == 201, submitted.text
        assert submitted.json()["data"]["expected_delivery_date"] is None
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
