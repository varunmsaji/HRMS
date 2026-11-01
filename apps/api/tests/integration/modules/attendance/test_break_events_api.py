"""Stage 3 — break events over HTTP: start / end / state, validation, idempotency, tenant
isolation, and that recomputing never touches the event history.

The wired shift is 09:00–18:00 UTC. Self-service break routes read the server clock, so each test
pins `break_service.utcnow` to a fixed instant on 2026-08-10 (IN/OUT punches are staged through the
on-behalf route at fixed instants)."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.auth.test_employee_jwt_linkage import _PASSWORD, _link_user_to_employee

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.attendance import break_service
from hrms.modules.attendance.permissions import ATTENDANCE_PUNCH, ATTENDANCE_VIEW

from .test_attendance_day import (
    _build_wired_employee,
    _cleanup,
    _cleanup_attendance_day,
    _punch,
    _register_tenant,
)

pytestmark = pytest.mark.asyncio

DAY = "2026-08-10"
_EMPLOYEE_USERS: list[UUID] = []

LUNCH = {
    "name": "Lunch",
    "break_kind": "FIXED_WINDOW",
    "start_time": "13:00",
    "end_time": "14:00",
    "scheduled_minutes": 60,
    "max_minutes": 60,
    "is_paid": False,
    "mode": "MANDATORY_PUNCH",
    "break_type": "LUNCH",
    "excess_outcome": "EXCEPTION",
    "sort_order": 0,
}
TEA = {
    "name": "Tea",
    "break_kind": "FIXED_WINDOW",
    "start_time": "16:00",
    "end_time": "16:15",
    "scheduled_minutes": 15,
    "max_minutes": 20,
    "is_paid": True,
    "mode": "OPTIONAL_PUNCH",
    "break_type": "TEA",
    "sort_order": 1,
}
AUTO = {
    "name": "Prayer",
    "break_kind": "FIXED_WINDOW",
    "start_time": "11:00",
    "end_time": "11:15",
    "scheduled_minutes": 15,
    "is_paid": False,
    "mode": "AUTO_DEDUCT",
    "break_type": "PRAYER",
    "sort_order": 2,
}


def at(hour: int, minute: int = 0, day: int = 10) -> datetime:
    return datetime(2026, 8, day, hour, minute, tzinfo=UTC)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Any:
    state = {"now": at(13, 0)}
    monkeypatch.setattr(break_service, "utcnow", lambda: state["now"])

    def set_time(value: datetime) -> None:
        state["now"] = value

    return set_time


async def _employee_headers(
    client: AsyncClient, company_id: UUID, employee_id: str
) -> dict[str, str]:
    email = f"brk-{uuid4().hex[:10]}@example.com"
    ctx_user = await _link_user_to_employee(
        company_id=company_id,
        employee_id=UUID(employee_id),
        email=email,
        data_scope="SELF",
        permission_codes=(ATTENDANCE_PUNCH, ATTENDANCE_VIEW),
    )
    login = await client.post(
        "/v1/auth/login",
        json={"email": email, "password": _PASSWORD, "company_id": str(company_id)},
    )
    assert login.status_code == 200, login.text
    _EMPLOYEE_USERS.append(ctx_user)
    return {
        "Authorization": f"Bearer {login.json()['data']['access_token']}",
        "X-Company-Id": str(company_id),
    }


async def _setup(client: AsyncClient, breaks: list[dict[str, Any]]) -> dict[str, Any]:
    headers, company_id, user_id = await _register_tenant(client)
    wired = await _build_wired_employee(client, headers, breaks=breaks)
    employee_id = wired["employee"]["id"]
    return {
        "hr": headers,
        "company_id": company_id,
        "user_id": user_id,
        "employee_id": employee_id,
        "me": await _employee_headers(client, company_id, employee_id),
    }


async def _cleanup_all(ctx: dict[str, Any]) -> None:
    async with get_session_factory()() as session:
        while _EMPLOYEE_USERS:
            uid = _EMPLOYEE_USERS.pop()
            for table in ("refresh_token", "session"):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE user_id = :u"), {"u": str(uid)}
                )
        await session.commit()
    await _cleanup_attendance_day(company_id=ctx["company_id"])
    await _cleanup(company_id=ctx["company_id"], user_id=ctx["user_id"])


async def _in(client: AsyncClient, ctx: dict[str, Any], hour: int = 9) -> None:
    await _punch(
        client, ctx["hr"], employee_id=ctx["employee_id"], hour=hour, minute=0, direction="IN"
    )


async def _out(client: AsyncClient, ctx: dict[str, Any], hour: int = 18) -> None:
    await _punch(
        client, ctx["hr"], employee_id=ctx["employee_id"], hour=hour, minute=0, direction="OUT"
    )


async def _post(client: AsyncClient, ctx: dict[str, Any], action: str, **body: Any) -> Any:
    return await client.post(f"/v1/attendance/breaks/me/{action}", headers=ctx["me"], json=body)


async def _day(client: AsyncClient, ctx: dict[str, Any]) -> dict[str, Any]:
    response = await client.post(
        "/v1/attendance/days/calculate",
        headers=ctx["hr"],
        params={"employee_id": ctx["employee_id"], "date": DAY},
    )
    assert response.status_code == 200, response.text
    return dict(response.json()["data"])


async def _event_count(ctx: dict[str, Any]) -> int:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(ctx["company_id"]))
        return int(
            (await session.execute(text("SELECT count(*) FROM attendance_break_event"))).scalar()
        )


def _code(response: Any) -> str:
    return str(response.json()["error"]["code"])


async def test_mandatory_break_start_end_and_net_hours(
    client: AsyncClient, seeded_plan_catalogue: None, clock: Any
) -> None:
    ctx = await _setup(client, [LUNCH])
    try:
        await _in(client, ctx)
        clock(at(13, 0))
        started = await _post(client, ctx, "start", break_name="Lunch")
        assert started.status_code == 200, started.text
        state = started.json()["data"]
        assert state["active_break"]["break_name"] == "Lunch"
        assert state["can_end"] and not state["can_start"] and state["checked_in"]

        # a second start while one is active is refused by the server
        again = await _post(client, ctx, "start", break_name="Lunch")
        assert again.status_code == 409 and _code(again) == "BREAK_ALREADY_ACTIVE"

        clock(at(13, 50))
        ended = await _post(client, ctx, "end")
        assert ended.status_code == 200, ended.text
        data = ended.json()["data"]
        assert data["active_break"] is None
        assert data["completed"][0]["minutes"] == 50
        assert data["rules"][0]["taken"] is True and data["can_start"] is False

        await _out(client, ctx)
        day = await _day(client, ctx)
        assert day["gross_elapsed_minutes"] == 540
        assert day["actual_break_minutes"] == 50
        assert day["unpaid_break_minutes"] == 50
        assert day["worked_minutes"] == 490
        assert day["breaks"][0]["kind"] == "EVENT"
        assert day["breaks"][0]["rule_source"] == "SHIFT"
        assert not day["has_unresolved_break"]
    finally:
        await _cleanup_all(ctx)


async def test_state_is_read_from_the_backend_after_a_restart(
    client: AsyncClient, seeded_plan_catalogue: None, clock: Any
) -> None:
    ctx = await _setup(client, [LUNCH, AUTO])
    try:
        before = await client.get("/v1/attendance/breaks/me/state", headers=ctx["me"])
        assert before.json()["data"]["checked_in"] is False
        await _in(client, ctx)
        clock(at(13, 5))
        await _post(client, ctx, "start", break_name="Lunch")
        # "app restart": nothing local — a fresh state call still shows the active break
        state = (await client.get("/v1/attendance/breaks/me/state", headers=ctx["me"])).json()[
            "data"
        ]
        assert state["active_break"]["started_at"] == "2026-08-10T13:05:00Z"
        assert state["punching"] == "MANDATORY"
        auto = next(r for r in state["rules"] if r["name"] == "Prayer")
        assert auto["can_punch"] is False  # automatic breaks have no Start/End controls
    finally:
        await _cleanup_all(ctx)


async def test_validation_order_and_refusals(
    client: AsyncClient, seeded_plan_catalogue: None, clock: Any
) -> None:
    ctx = await _setup(client, [LUNCH, TEA, AUTO])
    try:
        clock(at(13, 0))
        # before check-in
        assert (
            _code(await _post(client, ctx, "start", break_name="Lunch")) == "BREAK_NOT_CHECKED_IN"
        )
        await _in(client, ctx)
        # ending without an active break
        assert _code(await _post(client, ctx, "end")) == "BREAK_NOT_ACTIVE"
        # unknown / automatic / unnamed
        unknown = await _post(client, ctx, "start", break_name="Nap")
        assert unknown.status_code == 422 and _code(unknown) == "BREAK_NOT_CONFIGURED"
        automatic = await _post(client, ctx, "start", break_name="Prayer")
        assert automatic.status_code == 422 and _code(automatic) == "BREAK_PUNCHING_NOT_ALLOWED"
        unnamed = await _post(client, ctx, "start")
        assert unnamed.status_code == 422 and _code(unnamed) == "BREAK_NAME_REQUIRED"
        # a break can be taken once
        await _post(client, ctx, "start", break_name="Lunch")
        clock(at(13, 30))
        assert (await _post(client, ctx, "end")).status_code == 200
        clock(at(13, 40))
        assert _code(await _post(client, ctx, "start", break_name="Lunch")) == "BREAK_ALREADY_TAKEN"
        # after check-out nothing can start
        await _out(client, ctx, hour=14)
        clock(at(14, 30))
        assert (
            _code(await _post(client, ctx, "start", break_name="Tea"))
            == "BREAK_ALREADY_CHECKED_OUT"
        )
    finally:
        await _cleanup_all(ctx)


async def test_client_cannot_choose_source_time_or_employee(
    client: AsyncClient, seeded_plan_catalogue: None, clock: Any
) -> None:
    ctx = await _setup(client, [LUNCH])
    try:
        await _in(client, ctx)
        for forbidden in (
            {"source": "ADMIN"},
            {"event_time": "2026-08-10T10:00:00Z"},
            {"employee_id": str(uuid4())},
        ):
            response = await _post(client, ctx, "start", break_name="Lunch", **forbidden)
            assert response.status_code == 422, forbidden
        assert await _event_count(ctx) == 0
    finally:
        await _cleanup_all(ctx)


async def test_duplicate_requests_are_idempotent(
    client: AsyncClient, seeded_plan_catalogue: None, clock: Any
) -> None:
    ctx = await _setup(client, [LUNCH])
    try:
        await _in(client, ctx)
        key = f"start-{uuid4().hex}"
        first = await _post(client, ctx, "start", break_name="Lunch", idempotency_key=key)
        replay = await _post(client, ctx, "start", break_name="Lunch", idempotency_key=key)
        assert first.status_code == replay.status_code == 200
        assert first.json()["data"]["active_break"] == replay.json()["data"]["active_break"]
        assert await _event_count(ctx) == 1

        clock(at(13, 40))
        end_key = f"end-{uuid4().hex}"
        await _post(client, ctx, "end", idempotency_key=end_key)
        await _post(client, ctx, "end", idempotency_key=end_key)
        assert await _event_count(ctx) == 2

        # the same key may not be reused for a different action
        reused = await _post(client, ctx, "start", break_name="Lunch", idempotency_key=end_key)
        assert _code(reused) == "BREAK_IDEMPOTENCY_KEY_REUSED"
    finally:
        await _cleanup_all(ctx)


async def test_recompute_does_not_duplicate_or_change_events(
    client: AsyncClient, seeded_plan_catalogue: None, clock: Any
) -> None:
    ctx = await _setup(client, [LUNCH])
    try:
        await _in(client, ctx)
        await _post(client, ctx, "start", break_name="Lunch")
        clock(at(13, 45))
        await _post(client, ctx, "end")
        await _out(client, ctx)

        async def snapshot() -> list[Any]:
            async with get_session_factory()() as session:
                await set_rls_company_id(session, str(ctx["company_id"]))
                rows = await session.execute(
                    text(
                        "SELECT id, event_type, event_time, source, break_name, created_at "
                        "FROM attendance_break_event ORDER BY event_time"
                    )
                )
                return [tuple(r) for r in rows]

        original = await snapshot()
        results = [await _day(client, ctx) for _ in range(4)]
        assert await snapshot() == original and len(original) == 2
        assert len({r["worked_minutes"] for r in results}) == 1
        assert all(len(r["breaks"]) == 1 for r in results)  # derived rows replaced, not appended
    finally:
        await _cleanup_all(ctx)


async def test_unresolved_break_after_checkout_needs_review_and_hr_resolves_it(
    client: AsyncClient, seeded_plan_catalogue: None, clock: Any
) -> None:
    ctx = await _setup(client, [LUNCH])
    try:
        await _in(client, ctx)
        await _post(client, ctx, "start", break_name="Lunch")
        await _out(client, ctx)
        day = await _day(client, ctx)
        assert day["has_unresolved_break"] and day["unresolved_break_count"] == 1
        assert day["attendance_status"] == "INCOMPLETE"
        assert day["worked_minutes"] == 240  # nothing credited after the break start
        assert day["breaks"][0]["kind"] == "UNRESOLVED" and day["breaks"][0]["needs_review"]

        # the employee cannot end it after checking out
        clock(at(19, 0))
        late = await _post(client, ctx, "end")
        assert _code(late) in ("BREAK_ENDED_AFTER_CHECKOUT", "BREAK_NOT_ACTIVE")

        events = (
            await client.get(
                "/v1/attendance/breaks/events",
                headers=ctx["hr"],
                params={"date_from": DAY, "date_to": DAY},
            )
        ).json()["data"]
        start_id = next(e["id"] for e in events if e["event_type"] == "START")

        # employees do not resolve their own breaks (no approve permission → 403)
        own = await client.post(
            "/v1/attendance/breaks/resolve",
            headers=ctx["me"],
            json={"start_event_id": start_id, "approved_minutes": 60, "reason": "my fault"},
        )
        assert own.status_code == 403

        resolved = await client.post(
            "/v1/attendance/breaks/resolve",
            headers=ctx["hr"],
            json={"start_event_id": start_id, "approved_minutes": 60, "reason": "forgot to end"},
        )
        assert resolved.status_code == 200, resolved.text
        end = next(e for e in resolved.json()["data"]["events"] if e["event_type"] == "END")
        assert end["source"] == "ADMIN" and end["approved_by_user_id"] is not None
        assert end["reason"] == "forgot to end"

        fixed = await _day(client, ctx)
        assert not fixed["has_unresolved_break"]
        assert fixed["worked_minutes"] == 480 and fixed["attendance_status"] == "PRESENT"
        # the original START is still there, untouched
        assert await _event_count(ctx) == 2
    finally:
        await _cleanup_all(ctx)


async def test_excess_break_flags_an_exception_and_keeps_the_actual_duration(
    client: AsyncClient, seeded_plan_catalogue: None, clock: Any
) -> None:
    ctx = await _setup(client, [LUNCH])
    try:
        await _in(client, ctx)
        await _post(client, ctx, "start", break_name="Lunch")
        clock(at(14, 20))
        await _post(client, ctx, "end")
        await _out(client, ctx)
        day = await _day(client, ctx)
        assert day["has_excess_break_exception"] and day["excess_break_minutes"] == 20
        assert day["breaks"][0]["minutes"] == 80 and day["breaks"][0]["is_excess"]
        assert day["attendance_status"] == "PRESENT"
    finally:
        await _cleanup_all(ctx)


async def test_auto_deduction_needs_no_punches(
    client: AsyncClient, seeded_plan_catalogue: None, clock: Any
) -> None:
    ctx = await _setup(client, [LUNCH | {"mode": "AUTO_DEDUCT"}, AUTO])
    try:
        await _in(client, ctx)
        await _out(client, ctx)
        day = await _day(client, ctx)
        assert day["auto_deducted_break_minutes"] == 75
        assert day["worked_minutes"] == 540 - 75
        assert {b["kind"] for b in day["breaks"]} == {"AUTO_DEDUCTED"}
    finally:
        await _cleanup_all(ctx)


async def test_other_tenants_cannot_see_or_resolve_events(
    client: AsyncClient, seeded_plan_catalogue: None, clock: Any
) -> None:
    ctx = await _setup(client, [LUNCH])
    other_headers, other_company, other_user = await _register_tenant(client)
    try:
        await _in(client, ctx)
        await _post(client, ctx, "start", break_name="Lunch")
        events = (
            await client.get(
                "/v1/attendance/breaks/events",
                headers=ctx["hr"],
                params={"date_from": DAY, "date_to": DAY},
            )
        ).json()["data"]
        start_id = events[0]["id"]

        seen = await client.get(
            "/v1/attendance/breaks/events",
            headers=other_headers,
            params={"date_from": DAY, "date_to": DAY},
        )
        assert seen.json()["data"] == []
        resolve = await client.post(
            "/v1/attendance/breaks/resolve",
            headers=other_headers,
            json={"start_event_id": start_id, "approved_minutes": 30, "reason": "not yours"},
        )
        assert resolve.status_code == 404
        by_employee = await client.get(
            "/v1/attendance/breaks/day",
            headers=other_headers,
            params={"employee_id": ctx["employee_id"], "date": DAY},
        )
        assert by_employee.status_code == 404
    finally:
        await _cleanup_all(ctx)
        await _cleanup_attendance_day(company_id=other_company)
        await _cleanup(company_id=other_company, user_id=other_user)


async def test_closed_period_refuses_new_break_events(
    client: AsyncClient, seeded_plan_catalogue: None, clock: Any
) -> None:
    ctx = await _setup(client, [LUNCH])
    try:
        await _in(client, ctx)
        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(ctx["company_id"]))
            from hrms.modules.attendance import service as attendance_service

            original = attendance_service._is_date_closed

        async def closed(*_a: Any, **_k: Any) -> bool:
            return True

        attendance_service._is_date_closed = closed  # type: ignore[assignment]
        try:
            refused = await _post(client, ctx, "start", break_name="Lunch")
        finally:
            attendance_service._is_date_closed = original  # type: ignore[assignment]
        assert refused.status_code == 409 and _code(refused) == "ATTENDANCE_PERIOD_CLOSED"
        assert await _event_count(ctx) == 0
    finally:
        await _cleanup_all(ctx)
