"""Stage 4 — employee break overrides: precedence over the shift template, effective dating,
shift-version changes, audit trail, authorization and tenant isolation."""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from hrms.core.db.session import get_session_factory, set_rls_company_id

from .test_attendance_day import (
    _cleanup,
    _cleanup_attendance_day,
    _punch,
    _register_tenant,
)
from .test_break_events_api import (
    AUTO,
    LUNCH,
    TEA,
    _cleanup_all,
    _setup,
)

pytestmark = pytest.mark.asyncio

AUTO_LUNCH = LUNCH | {"mode": "AUTO_DEDUCT", "max_minutes": None, "excess_outcome": None}


async def _override(client: AsyncClient, ctx: dict[str, Any], **body: Any) -> Any:
    return await client.post(
        "/v1/attendance/break-overrides",
        headers=ctx["hr"],
        json={"employee_id": ctx["employee_id"], "reason": "agreed with HR", **body},
    )


async def _day(client: AsyncClient, ctx: dict[str, Any], day: str) -> dict[str, Any]:
    for direction, hour in (("IN", 9), ("OUT", 18)):
        existing = await client.get(
            "/v1/attendance/punches",
            headers=ctx["hr"],
            params={"employee_id": ctx["employee_id"], "date_from": day, "date_to": day},
        )
        if len(existing.json()["data"]) >= 2:
            break
        await _punch(
            client,
            ctx["hr"],
            employee_id=ctx["employee_id"],
            hour=hour,
            minute=0,
            direction=direction,
            day=day,
        )
    response = await client.post(
        "/v1/attendance/days/calculate",
        headers=ctx["hr"],
        params={"employee_id": ctx["employee_id"], "date": day},
    )
    assert response.status_code == 200, response.text
    return dict(response.json()["data"])


async def _rules(client: AsyncClient, ctx: dict[str, Any], day: str) -> dict[str, Any]:
    response = await client.get(
        "/v1/attendance/breaks/resolved-rules",
        headers=ctx["hr"],
        params={"employee_id": ctx["employee_id"], "date": day},
    )
    assert response.status_code == 200, response.text
    return dict(response.json()["data"])


async def test_replace_applies_from_its_effective_date_and_shift_is_untouched(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    ctx = await _setup(client, [AUTO_LUNCH])
    try:
        created = await _override(
            client,
            ctx,
            action="REPLACE",
            target_break_name="Lunch",
            effective_from="2026-08-12",
            scheduled_minutes=30,
            end_time="13:30",
        )
        assert created.status_code == 201, created.text

        before = await _day(client, ctx, "2026-08-11")
        after = await _day(client, ctx, "2026-08-12")
        assert before["auto_deducted_break_minutes"] == 60
        assert before["breaks"][0]["rule_source"] == "SHIFT"
        assert after["auto_deducted_break_minutes"] == 30
        assert after["worked_minutes"] == 540 - 30
        brk = after["breaks"][0]
        assert brk["rule_source"] == "EMPLOYEE_OVERRIDE" and brk["override_id"] is not None
        assert after["computation_snapshot"]["breaks"]["provenance"] == [
            {"action": "REPLACE", "name": "Lunch", "override_id": created.json()["data"]["id"]}
        ]

        inherited = await _rules(client, ctx, "2026-08-11")
        overridden = await _rules(client, ctx, "2026-08-12")
        assert inherited["rules"][0]["rule_source"] == "SHIFT"
        assert overridden["rules"][0]["rule_source"] == "EMPLOYEE_OVERRIDE"
        assert overridden["rules"][0]["scheduled_minutes"] == 30

        # the shift template row itself was never edited
        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(ctx["company_id"]))
            minutes = (
                await session.execute(
                    text("SELECT scheduled_minutes FROM shift_break WHERE name = 'Lunch'")
                )
            ).scalar()
        assert minutes == 60
    finally:
        await _cleanup_all(ctx)


async def test_add_and_disable_override_individual_employee_breaks(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    ctx = await _setup(client, [AUTO_LUNCH, AUTO])
    try:
        added = await _override(
            client,
            ctx,
            action="ADD",
            name="Rest",
            break_kind="FIXED_WINDOW",
            mode="AUTO_DEDUCT",
            start_time="15:00",
            end_time="15:15",
            scheduled_minutes=15,
            is_paid=True,
            break_type="REST",
            effective_from="2026-08-10",
        )
        assert added.status_code == 201, added.text
        disabled = await _override(
            client, ctx, action="DISABLE", target_break_name="Prayer", effective_from="2026-08-10"
        )
        assert disabled.status_code == 201, disabled.text
        day = await _day(client, ctx, "2026-08-10")
        assert day["paid_break_minutes"] == 15  # the extra paid rest break
        assert day["unpaid_break_minutes"] == 60  # lunch only: Prayer was disabled
        assert day["worked_minutes"] == 480
        names = {
            r["name"]: r["rule_source"] for r in (await _rules(client, ctx, "2026-08-10"))["rules"]
        }
        assert names == {"Lunch": "SHIFT", "Rest": "EMPLOYEE_OVERRIDE"}
    finally:
        await _cleanup_all(ctx)


async def test_revoking_restores_the_shift_default_and_everything_is_audited(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    ctx = await _setup(client, [AUTO_LUNCH])
    try:
        created = (
            await _override(
                client,
                ctx,
                action="DISABLE",
                target_break_name="Lunch",
                effective_from="2026-08-10",
            )
        ).json()["data"]
        assert (await _day(client, ctx, "2026-08-10"))["worked_minutes"] == 540

        revoked = await client.post(
            f"/v1/attendance/break-overrides/{created['id']}/revoke",
            headers=ctx["hr"],
            json={"reason": "no longer needed"},
        )
        assert revoked.status_code == 200, revoked.text
        assert revoked.json()["data"]["revoked_at"] is not None
        again = await client.post(
            f"/v1/attendance/break-overrides/{created['id']}/revoke",
            headers=ctx["hr"],
            json={"reason": "twice"},
        )
        assert again.status_code == 409

        recalculated = await client.post(
            "/v1/attendance/days/calculate",
            headers=ctx["hr"],
            params={"employee_id": ctx["employee_id"], "date": "2026-08-10"},
        )
        assert recalculated.json()["data"]["worked_minutes"] == 480

        listed = await client.get(
            "/v1/attendance/break-overrides",
            headers=ctx["hr"],
            params={"employee_id": ctx["employee_id"], "include_revoked": "true"},
        )
        assert [r["revoked_at"] is not None for r in listed.json()["data"]] == [True]
        live = await client.get(
            "/v1/attendance/break-overrides",
            headers=ctx["hr"],
            params={"employee_id": ctx["employee_id"]},
        )
        assert live.json()["data"] == []

        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(ctx["company_id"]))
            actions = (
                (
                    await session.execute(
                        text(
                            "SELECT action FROM audit_log"
                            " WHERE entity_type = 'employee_break_override'"
                            " ORDER BY occurred_at"
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert actions == ["BREAK_OVERRIDE_CREATED", "BREAK_OVERRIDE_REVOKED"]
    finally:
        await _cleanup_all(ctx)


async def test_invalid_and_conflicting_overrides_are_refused(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    ctx = await _setup(client, [AUTO_LUNCH, TEA | {"mode": "AUTO_DEDUCT"}])
    try:
        ok = await _override(
            client,
            ctx,
            action="REPLACE",
            target_break_name="Lunch",
            effective_from="2026-08-10",
            effective_to="2026-08-31",
            scheduled_minutes=45,
        )
        assert ok.status_code == 201, ok.text
        # same break, overlapping dates
        overlap = await _override(
            client, ctx, action="DISABLE", target_break_name="Lunch", effective_from="2026-08-20"
        )
        assert overlap.status_code == 409
        # breaks that do not exist / would collide / are malformed
        missing = await _override(
            client, ctx, action="DISABLE", target_break_name="Nap", effective_from="2026-09-10"
        )
        assert missing.status_code == 422
        clash = await _override(
            client,
            ctx,
            action="ADD",
            name="lunch",
            break_kind="FIXED_WINDOW",
            mode="AUTO_DEDUCT",
            start_time="12:00",
            end_time="12:30",
            effective_from="2026-09-10",
        )
        assert clash.status_code == 422
        overlapping_window = await _override(
            client,
            ctx,
            action="ADD",
            name="Chai",
            break_kind="FIXED_WINDOW",
            mode="AUTO_DEDUCT",
            start_time="13:30",
            end_time="13:45",
            scheduled_minutes=15,
            effective_from="2026-09-10",
        )
        assert overlapping_window.status_code == 422
        too_long = await _override(
            client,
            ctx,
            action="REPLACE",
            target_break_name="Tea",
            scheduled_minutes=60,
            effective_from="2026-09-10",
        )
        assert too_long.status_code == 422
        for bad in (
            {"action": "DISABLE", "target_break_name": "Tea", "max_minutes": 10},
            {"action": "REPLACE"},
            {"action": "ADD", "name": "X"},
            {"action": "PAUSE", "target_break_name": "Tea"},
            {"action": "DISABLE", "target_break_name": "Tea", "effective_to": "2026-01-01"},
        ):
            response = await _override(client, ctx, **{"effective_from": "2026-09-10", **bad})
            assert response.status_code == 422, bad
    finally:
        await _cleanup_all(ctx)


async def test_override_follows_the_break_by_name_across_a_shift_version_change(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    ctx = await _setup(client, [AUTO_LUNCH])
    try:
        shifts = (await client.get("/v1/shifts", headers=ctx["hr"])).json()["data"]
        shift = shifts[0]
        v1_id, shift_id = shift["current_version_id"], shift["id"]
        v1 = (
            await client.get(f"/v1/shifts/{shift_id}/versions/{v1_id}", headers=ctx["hr"])
        ).json()["data"]
        draft = (
            await client.post(f"/v1/shifts/{shift_id}/versions", headers=ctx["hr"], json={})
        ).json()["data"]
        patched = await client.patch(
            f"/v1/shifts/{shift_id}/versions/{draft['id']}",
            headers={**ctx["hr"], "If-Match": "1"},
            json={
                "shift_type": "FIXED",
                "effective_from": "2026-08-20",
                "start_time": "09:00",
                "end_time": "18:00",
                "timezone": "UTC",
                "breaks": [AUTO_LUNCH | {"scheduled_minutes": 45, "end_time": "13:45"}],
            },
        )
        assert patched.status_code == 200, patched.text
        published = await client.post(
            f"/v1/shifts/{shift_id}/versions/{draft['id']}/publish",
            headers={**ctx["hr"], "If-Match": "2"},
            json={"expected_previous_version": v1["version"]},
        )
        assert published.status_code == 200, published.text

        assert (await _day(client, ctx, "2026-08-11"))["auto_deducted_break_minutes"] == 60
        assert (await _day(client, ctx, "2026-08-21"))["auto_deducted_break_minutes"] == 45

        # an override dated across the version boundary applies to the break of whichever
        # version is effective on the day, because it addresses the break by name
        assert (
            await _override(
                client,
                ctx,
                action="REPLACE",
                target_break_name="Lunch",
                effective_from="2026-08-15",
                scheduled_minutes=20,
            )
        ).status_code == 201
        assert (await _day(client, ctx, "2026-08-14"))["auto_deducted_break_minutes"] == 60
        assert (await _day(client, ctx, "2026-08-16"))["auto_deducted_break_minutes"] == 20
        assert (await _day(client, ctx, "2026-08-22"))["auto_deducted_break_minutes"] == 20
    finally:
        await _cleanup_all(ctx)


async def test_authorization_and_tenant_isolation(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    ctx = await _setup(client, [AUTO_LUNCH])
    other_headers, other_company, other_user = await _register_tenant(client)
    try:
        # an employee holding only ATTENDANCE.PUNCH cannot create overrides
        denied = await client.post(
            "/v1/attendance/break-overrides",
            headers=ctx["me"],
            json={
                "employee_id": ctx["employee_id"],
                "action": "DISABLE",
                "target_break_name": "Lunch",
                "effective_from": "2026-08-10",
                "reason": "mine",
            },
        )
        assert denied.status_code == 403

        created = (
            await _override(
                client,
                ctx,
                action="DISABLE",
                target_break_name="Lunch",
                effective_from="2026-08-10",
            )
        ).json()["data"]
        # another tenant cannot see, list or revoke it, and cannot target this employee
        assert (
            await client.get(
                "/v1/attendance/break-overrides",
                headers=other_headers,
                params={"employee_id": ctx["employee_id"]},
            )
        ).status_code == 404
        assert (
            await client.post(
                f"/v1/attendance/break-overrides/{created['id']}/revoke",
                headers=other_headers,
                json={"reason": "not yours"},
            )
        ).status_code == 404
        cross = await client.post(
            "/v1/attendance/break-overrides",
            headers=other_headers,
            json={
                "employee_id": ctx["employee_id"],
                "action": "DISABLE",
                "target_break_name": "Lunch",
                "effective_from": "2026-08-10",
                "reason": "x" * 5,
            },
        )
        assert cross.status_code == 404
        assert (
            await client.get(
                "/v1/attendance/breaks/resolved-rules",
                headers=other_headers,
                params={"employee_id": ctx["employee_id"], "date": "2026-08-10"},
            )
        ).status_code == 404
    finally:
        await _cleanup_all(ctx)
        await _cleanup_attendance_day(company_id=other_company)
        await _cleanup(company_id=other_company, user_id=other_user)


async def test_shift_break_configuration_validation(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        shift = (await client.post("/v1/shifts", headers=headers, json={"name": "G"})).json()[
            "data"
        ]

        async def patch(breaks: list[dict[str, Any]]) -> Any:
            url = f"/v1/shifts/{shift['id']}/versions/{shift['draft_version_id']}"
            token = (await client.get(url, headers=headers)).json()["data"]["version"]
            return await client.patch(
                url,
                headers={**headers, "If-Match": str(token)},
                json={
                    "shift_type": "FIXED",
                    "effective_from": "2026-01-01",
                    "start_time": "09:00",
                    "end_time": "18:00",
                    "timezone": "UTC",
                    "breaks": breaks,
                },
            )

        assert (await patch([AUTO_LUNCH, TEA, AUTO])).status_code == 200
        assert (await patch([AUTO_LUNCH, AUTO_LUNCH])).status_code == 422  # duplicate name
        assert (await patch([AUTO_LUNCH | {"max_minutes": 30}])).status_code == 422  # sched > max
        assert (await patch([AUTO_LUNCH | {"max_minutes": 0}])).status_code == 422
        assert (
            await patch([AUTO_LUNCH | {"min_minutes": 90, "max_minutes": 60}])
        ).status_code == 422
        assert (await patch([AUTO_LUNCH | {"scheduled_minutes": 120}])).status_code == 422
        assert (await patch([AUTO_LUNCH | {"mode": "SOMETIMES"}])).status_code == 422
        assert (
            await patch([AUTO_LUNCH | {"start_time": "14:00", "end_time": "13:00"}])
        ).status_code in (
            200,
            422,
        )  # an end before the start is a midnight crossing for a fixed window
        overlapping = await patch([AUTO_LUNCH, AUTO | {"start_time": "13:30", "end_time": "13:45"}])
        assert overlapping.status_code == 422
        flexible_auto = {
            "name": "Meal",
            "break_kind": "FLEXIBLE_DURATION",
            "window_start": "12:00",
            "window_end": "15:00",
            "min_minutes": 20,
            "max_minutes": 60,
            "mode": "AUTO_DEDUCT",
        }
        assert (await patch([flexible_auto])).status_code == 422  # needs scheduled_minutes
        assert (await patch([flexible_auto | {"scheduled_minutes": 30}])).status_code == 200
        read = (
            await patch([AUTO_LUNCH | {"excess_outcome": "DEDUCT", "break_type": "LUNCH"}])
        ).json()["data"]["breaks"][0]
        assert read["mode"] == "AUTO_DEDUCT" and read["excess_outcome"] == "DEDUCT"
        assert read["is_enabled"] is True and read["break_type"] == "LUNCH"
    finally:
        from tests.integration.modules.organisation.test_shift_version import _cleanup_shifts

        await _cleanup_shifts(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
