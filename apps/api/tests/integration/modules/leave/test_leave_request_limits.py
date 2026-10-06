"""Decision 15 / LM-10 - a leave request spans at most 90 calendar days (rejected at the schema,
before any per-day work) and at most the policy's `max_consecutive_days` (default 30, configurable
per policy version)."""

from datetime import date, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from tests.integration.modules.leave.test_leave_application import (
    _cleanup,
    _register_tenant,
    _setup_full,
    _submit,
    _teardown,
)

from hrms.modules.organisation.calendar_resolution import CalendarResolutionService

pytestmark = pytest.mark.asyncio

_START = date(2026, 9, 8)


def _span(days: int) -> dict[str, str]:
    """A request of exactly `days` calendar days starting 2026-09-08 (inclusive of both ends)."""
    return {
        "start_date": _START.isoformat(),
        "end_date": (_START + timedelta(days=days - 1)).isoformat(),
    }


async def _submit_span(
    client: AsyncClient, headers: dict[str, str], ctx: dict[str, Any], days: int
) -> Any:
    return await _submit(
        client,
        headers,
        employee_id=ctx["employee"]["id"],
        leave_type_id=ctx["leave_type"]["id"],
        **_span(days),
    )


async def test_ninety_days_pass_the_schema_and_ninety_one_do_not(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(
            client, headers, approval_chain="HR", balance="200.00", max_consecutive_days=90
        )
        accepted = await _submit_span(client, headers, ctx, 90)
        assert accepted.status_code == 201, accepted.text
        assert accepted.json()["data"]["end_date"] == "2026-12-06"

        refused = await _submit_span(client, headers, ctx, 91)
        assert refused.status_code == 422, refused.text
        error = refused.json()["error"]
        assert error["code"] == "REQUEST_VALIDATION_ERROR"
        assert "90" in str(error["details"])
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_an_oversized_range_is_refused_before_any_per_day_work(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, approval_chain="HR")
        original = CalendarResolutionService.resolve_for_employee
        calls = 0

        async def counting(self: Any, *args: Any, **kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            return await original(self, *args, **kwargs)

        with patch.object(CalendarResolutionService, "resolve_for_employee", counting):
            for days in (91, 400, 3653, 20000):
                response = await _submit_span(client, headers, ctx, days)
                assert response.status_code == 422, (days, response.text)
        assert calls == 0, "an oversized range must never reach per-day calendar resolution"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_default_policy_allows_thirty_consecutive_days_and_refuses_thirty_one(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, approval_chain="HR", balance="100.00")
        assert ctx["policy"] is not None
        versions = await client.get(
            f"/v1/leave-policies/{ctx['policy']['id']}/versions", headers=headers
        )
        assert versions.json()["data"][0]["max_consecutive_days"] == 30

        accepted = await _submit_span(client, headers, ctx, 30)
        assert accepted.status_code == 201, accepted.text
        # a different start so the 31-day request does not overlap the accepted one
        refused = await _submit(
            client,
            headers,
            employee_id=ctx["employee"]["id"],
            leave_type_id=ctx["leave_type"]["id"],
            start_date="2027-02-01",
            end_date="2027-03-03",
        )
        assert refused.status_code == 422, refused.text
        error = refused.json()["error"]
        assert error["code"] == "LEAVE_APPLICATION_MAX_CONSECUTIVE_EXCEEDED"
        assert error["details"][0]["context"] == {"limit": 30, "requested": 31}
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.parametrize(("limit", "ok_days", "bad_days"), [(1, 1, 2), (10, 10, 11), (60, 60, 61)])
async def test_the_cap_is_configurable_per_policy_version(
    client: AsyncClient, seeded_plan_catalogue: None, limit: int, ok_days: int, bad_days: int
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(
            client, headers, approval_chain="HR", balance="200.00", max_consecutive_days=limit
        )
        accepted = await _submit_span(client, headers, ctx, ok_days)
        assert accepted.status_code == 201, accepted.text
        refused = await _submit(
            client,
            headers,
            employee_id=ctx["employee"]["id"],
            leave_type_id=ctx["leave_type"]["id"],
            start_date="2027-02-01",
            end_date=(date(2027, 2, 1) + timedelta(days=bad_days - 1)).isoformat(),
        )
        assert refused.status_code == 422, refused.text
        assert refused.json()["error"]["code"] == "LEAVE_APPLICATION_MAX_CONSECUTIVE_EXCEEDED"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.parametrize("value", [0, -1, 91, 365])
async def test_the_policy_field_itself_is_bounded(
    client: AsyncClient, seeded_plan_catalogue: None, value: int
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers)
        response = await client.post(
            f"/v1/leave-policies/{ctx['policy']['id']}/versions",
            headers=headers,
            json={"effective_from": "2030-01-01", "max_consecutive_days": value},
        )
        assert response.status_code == 422, response.text
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
