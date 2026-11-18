"""LV-04 (leave audit) / attendance rules audit Part 3: an attendance period cannot be closed
while a leave request for it is still waiting for a decision. Before, the days locked as absent
(loss of pay) and the request could no longer be approved."""

from typing import Any

import pytest
from httpx import AsyncClient
from tests.integration.modules.attendance.test_attendance_period import (
    _cleanup_attendance_period,
    _create_period,
)
from tests.integration.modules.leave.test_leave_application import (
    _register_tenant,
    _setup_full,
    _submit,
    _teardown,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup
from tests.integration.modules.organisation.test_workforce_calendar import (
    _cleanup_workforce_calendar,
)

pytestmark = pytest.mark.asyncio


async def _blockers(
    client: AsyncClient, headers: dict[str, str], period: dict[str, Any]
) -> dict[str, Any]:
    validated = await client.post(
        f"/v1/attendance-periods/{period['id']}/validate", headers=headers
    )
    assert validated.status_code == 200, validated.text
    return {r["code"]: r for r in validated.json()["data"]["reasons"]}


async def test_a_pending_leave_request_blocks_the_close_until_it_is_decided_or_withdrawn(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, approval_chain="HR")
        september = await _create_period(
            client, headers, period_start="2026-09-01", period_end="2026-09-30", label="Sep"
        )
        october = await _create_period(
            client, headers, period_start="2026-10-01", period_end="2026-10-31", label="Oct"
        )
        assert "PENDING_LEAVE" not in await _blockers(client, headers, september)

        submitted = await _submit(
            client,
            headers,
            employee_id=ctx["employee"]["id"],
            leave_type_id=ctx["leave_type"]["id"],
            start_date="2026-09-29",
            end_date="2026-09-30",
        )
        assert submitted.status_code == 201, submitted.text
        application = submitted.json()["data"]
        assert application["status"] == "SUBMITTED"

        blocked = await _blockers(client, headers, september)
        assert blocked["PENDING_LEAVE"]["count"] == 1
        assert ctx["employee"]["id"] in blocked["PENDING_LEAVE"]["sample"][0]
        # Boundary: the request ends on the period's last day, so the next period is not held up.
        assert "PENDING_LEAVE" not in await _blockers(client, headers, october)

        finalize = await client.post(
            f"/v1/attendance-periods/{september['id']}/finalize",
            headers={**headers, "If-Match": str(september["version"])},
            json={},
        )
        assert finalize.status_code != 200
        assert "PENDING_LEAVE" in finalize.text

        withdrawn = await client.post(
            f"/v1/leave-applications/{application['id']}/cancel",
            headers={**headers, "If-Match": str(application["version"])},
        )
        assert withdrawn.status_code == 200, withdrawn.text
        assert "PENDING_LEAVE" not in await _blockers(client, headers, september)
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_workforce_calendar(company_id=company_id)
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
