"""Stage 5 — BREAK_CORRECTION regularization: submit → HR approval → ADMIN END event, plus the
guard rails (never self-approving, validation, tenant isolation, closed/locked refusal)."""

from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient

from .test_attendance_day import _cleanup, _cleanup_attendance_day
from .test_break_events_api import (
    DAY,
    LUNCH,
    _cleanup_all,
    _day,
    _in,
    _out,
    _post,
    _setup,
    at,
    clock,  # noqa: F401  (fixture)
)
from .test_regularization import _cleanup_regularization, _create_regularization_policy

pytestmark = pytest.mark.asyncio


async def _unresolved_start(client: AsyncClient, ctx: dict[str, Any]) -> str:
    await _in(client, ctx)
    started = await _post(client, ctx, "start", break_name="Lunch")
    assert started.status_code == 200, started.text
    await _out(client, ctx)
    events = (
        await client.get(
            "/v1/attendance/breaks/events",
            headers=ctx["hr"],
            params={"date_from": DAY, "date_to": DAY},
        )
    ).json()["data"]
    return str(next(e["id"] for e in events if e["event_type"] == "START"))


async def _submit(
    client: AsyncClient, ctx: dict[str, Any], start_id: str | None, **extra: Any
) -> Any:
    body: dict[str, Any] = {
        "employee_id": ctx["employee_id"],
        "attendance_date": DAY,
        "request_type": "BREAK_CORRECTION",
        "reason": "forgot to end break",
        "break_start_event_id": start_id,
        **extra,
    }
    return await client.post("/v1/regularizations", headers=ctx["hr"], json=body)


async def _cleanup_everything(ctx: dict[str, Any]) -> None:
    await _cleanup_regularization(company_id=ctx["company_id"])
    await _cleanup_all(ctx)


async def test_break_correction_approved_by_hr_resolves_the_break(
    client: AsyncClient,
    seeded_plan_catalogue: None,
    clock: Any,  # noqa: F811
) -> None:
    ctx = await _setup(client, [LUNCH])
    try:
        await _create_regularization_policy(
            client, ctx["hr"], allowed_types=["BREAK_CORRECTION"], approval_chain="HR"
        )
        start_id = await _unresolved_start(client, ctx)
        clock(at(19, 0))
        created = await _submit(client, ctx, start_id, requested_break_minutes=60)
        assert created.status_code == 201, created.text
        request = created.json()["data"]
        assert request["status"] == "SUBMITTED" and request["break_start_event_id"] == start_id

        approved = await client.post(
            f"/v1/regularizations/{request['id']}/approve",
            headers={**ctx["hr"], "If-Match": str(request["version"])},
            json={},
        )
        assert approved.status_code == 200, approved.text
        data = approved.json()["data"]
        assert data["status"] == "APPROVED" and data["applied_at"] is not None

        stored = await client.get(
            f"/v1/attendance/days/{data['attendance_day_id']}", headers=ctx["hr"]
        )
        assert stored.json()["data"]["is_regularized"] is True

        day = await _day(client, ctx)
        assert not day["has_unresolved_break"]
        assert day["worked_minutes"] == 480 and day["attendance_status"] == "PRESENT"
    finally:
        await _cleanup_everything(ctx)


async def test_auto_chain_does_not_self_approve_a_break_correction(
    client: AsyncClient,
    seeded_plan_catalogue: None,
    clock: Any,  # noqa: F811
) -> None:
    ctx = await _setup(client, [LUNCH])
    try:
        await _create_regularization_policy(
            client, ctx["hr"], allowed_types=["BREAK_CORRECTION"], approval_chain="AUTO"
        )
        start_id = await _unresolved_start(client, ctx)
        clock(at(19, 0))
        created = await _submit(client, ctx, start_id, requested_break_minutes=60)
        assert created.status_code == 201, created.text
        data = created.json()["data"]
        assert data["status"] == "SUBMITTED" and data["approval_stage"] == "HR"
        assert data["applied_at"] is None
        assert (await _day(client, ctx))["has_unresolved_break"]
    finally:
        await _cleanup_everything(ctx)


async def test_break_correction_validation(
    client: AsyncClient,
    seeded_plan_catalogue: None,
    clock: Any,  # noqa: F811
) -> None:
    ctx = await _setup(client, [LUNCH])
    try:
        await _create_regularization_policy(
            client,
            ctx["hr"],
            allowed_types=["BREAK_CORRECTION", "MISSING_PUNCH"],
            approval_chain="HR",
        )
        start_id = await _unresolved_start(client, ctx)
        clock(at(19, 0))
        # neither / both of end and minutes
        assert (await _submit(client, ctx, start_id)).status_code == 422
        both = await _submit(
            client,
            ctx,
            start_id,
            requested_break_minutes=30,
            requested_break_end="2026-08-10T14:00:00Z",
        )
        assert both.status_code == 422
        # missing start id
        assert (await _submit(client, ctx, None, requested_break_minutes=30)).status_code == 422
        # unknown event → 4xx, never 500
        unknown = await _submit(client, ctx, str(uuid4()), requested_break_minutes=30)
        assert unknown.status_code == 422
        # end before start
        early = await _submit(client, ctx, start_id, requested_break_end="2026-08-10T08:00:00Z")
        assert early.status_code == 422
        # break fields on another request type
        wrong = await client.post(
            "/v1/regularizations",
            headers=ctx["hr"],
            json={
                "employee_id": ctx["employee_id"],
                "attendance_date": DAY,
                "request_type": "MISSING_PUNCH",
                "break_start_event_id": start_id,
                "requested_punches": [{"direction": "IN", "requested_time": f"{DAY}T09:00:00Z"}],
            },
        )
        assert wrong.status_code == 422
    finally:
        await _cleanup_everything(ctx)


async def test_break_correction_is_tenant_isolated(
    client: AsyncClient,
    seeded_plan_catalogue: None,
    clock: Any,  # noqa: F811
) -> None:
    ctx = await _setup(client, [LUNCH])
    other = await _setup(client, [LUNCH])
    try:
        await _create_regularization_policy(
            client, other["hr"], allowed_types=["BREAK_CORRECTION"], approval_chain="HR"
        )
        start_id = await _unresolved_start(client, ctx)
        clock(at(19, 0))
        # tenant B cannot reference tenant A's break event
        response = await client.post(
            "/v1/regularizations",
            headers=other["hr"],
            json={
                "employee_id": other["employee_id"],
                "attendance_date": DAY,
                "request_type": "BREAK_CORRECTION",
                "break_start_event_id": start_id,
                "requested_break_minutes": 30,
            },
        )
        assert response.status_code == 422
    finally:
        await _cleanup_everything(ctx)  # also clears the employee login users of both tenants
        await _cleanup_regularization(company_id=other["company_id"])
        await _cleanup_attendance_day(company_id=other["company_id"])
        await _cleanup(company_id=other["company_id"], user_id=other["user_id"])


async def test_unresolved_break_is_listed_by_break_filter_and_summary_preview(
    client: AsyncClient,
    seeded_plan_catalogue: None,
    clock: Any,  # noqa: F811
) -> None:
    ctx = await _setup(client, [LUNCH])
    try:
        await _unresolved_start(client, ctx)
        await _day(client, ctx)

        listed = await client.get(
            "/v1/attendance/days",
            headers=ctx["hr"],
            params={"employee_id": ctx["employee_id"], "break_filter": "UNRESOLVED"},
        )
        assert listed.status_code == 200, listed.text
        rows = listed.json()["data"]
        assert len(rows) == 1 and rows[0]["has_unresolved_break"] is True

        none = await client.get(
            "/v1/attendance/days",
            headers=ctx["hr"],
            params={"employee_id": ctx["employee_id"], "break_filter": "EXCESS"},
        )
        assert none.json()["data"] == []
        bad = await client.get(
            "/v1/attendance/days", headers=ctx["hr"], params={"break_filter": "nope"}
        )
        assert bad.status_code == 422
    finally:
        await _cleanup_everything(ctx)
