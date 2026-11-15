"""HR marks a whole day (IN + OUT) for one or more employees in one step.

`POST /v1/attendance/punches/day-entries[/preview]` — every punch goes through the single on-behalf
punch path, so its bounds still apply; on top, an employee who already has a punch that day is
refused, each employee is both-punches-or-neither, and a retried submission records nothing twice.
"""

from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.auth.test_employee_jwt_linkage import _PASSWORD, _link_user_to_employee

from hrms.core.db.session import get_session_factory, session_scope
from hrms.modules.attendance.permissions import (
    ATTENDANCE_PUNCH,
    ATTENDANCE_PUNCH_ON_BEHALF,
    ATTENDANCE_VIEW,
)

from .test_attendance_day import (
    _build_wired_employee,
    _cleanup,
    _cleanup_attendance_day,
    _punch,
    _register_tenant,
)
from .test_attendance_edge_cases import _terminate
from .test_attendance_period import _cleanup_attendance_period, _insert_closed_period

pytestmark = pytest.mark.asyncio

_DAY = "2026-08-10"
# The wired employee's shift is 09:00-18:00 in its branch zone, UTC. Both instants fall on the
# same company-local (IST) date too: 14:30 and 23:30.
_IN = f"{_DAY}T09:00:00Z"
_OUT = f"{_DAY}T18:00:00Z"


def _body(employee_ids: list[str], **overrides: Any) -> dict[str, Any]:
    return {
        "employee_ids": employee_ids,
        "punch_in_at": _IN,
        "punch_out_at": _OUT,
        "reason": "Biometric device was offline",
        **overrides,
    }


async def _preview(client: AsyncClient, headers: dict[str, str], body: dict[str, Any]):
    return await client.post(
        "/v1/attendance/punches/day-entries/preview", headers=headers, json=body
    )


async def _record(client: AsyncClient, headers: dict[str, str], body: dict[str, Any]):
    return await client.post("/v1/attendance/punches/day-entries", headers=headers, json=body)


async def _punches(client: AsyncClient, headers: dict[str, str], employee_id: str) -> list[dict]:
    response = await client.get(
        "/v1/attendance/punches", headers=headers, params={"employee_id": employee_id}
    )
    assert response.status_code == 200, response.text
    return list(response.json()["data"])


async def _plain_employee(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post("/v1/employees", headers=headers, json={"first_name": "Ravi"})
    assert response.status_code == 201, response.text
    return str(response.json()["data"]["id"])


async def _cleanup_attendance_day_punches(company_id: UUID) -> None:
    async with get_session_factory()() as session:
        await session.execute(
            text("DELETE FROM attendance_day WHERE company_id = :c"), {"c": str(company_id)}
        )
        await session.execute(
            text("DELETE FROM punch WHERE company_id = :c"), {"c": str(company_id)}
        )
        await session.commit()


def _by_employee(response: Any) -> dict[str, dict[str, Any]]:
    return {r["employee_id"]: r for r in response.json()["data"]["results"]}


async def test_preview_writes_nothing_then_record_stores_both_punches_and_calculates(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        eid = wired["employee"]["id"]
        other = await _plain_employee(client, headers)

        preview = await _preview(client, headers, _body([eid, other]))
        assert preview.status_code == 200, preview.text
        assert preview.json()["data"]["ready_count"] == 2
        assert {r["outcome"] for r in preview.json()["data"]["results"]} == {"READY"}
        assert await _punches(client, headers, eid) == [], "a preview must write nothing"

        recorded = await _record(client, headers, _body([eid, other]))
        assert recorded.status_code == 200, recorded.text
        data = recorded.json()["data"]
        assert data["recorded_count"] == 2 and data["blocked_count"] == 0
        # results come back in request order
        assert [r["employee_id"] for r in data["results"]] == [eid, other]

        stored = await _punches(client, headers, eid)
        assert sorted((p["direction"], p["punch_time"]) for p in stored) == [
            ("IN", _IN),
            ("OUT", _OUT),
        ]
        assert {p["source"] for p in stored} == {"ADMIN"}
        assert {p["reference"] for p in stored} == {"Biometric device was offline"}
        assert {p["recorded_by_user_id"] for p in stored} == {str(user_id)}

        day = await client.get(
            "/v1/attendance/days",
            headers=headers,
            params={"employee_id": eid, "date_from": _DAY, "date_to": _DAY},
        )
        assert day.status_code == 200, day.text
        assert day.json()["data"][0]["attendance_status"] == "PRESENT"

        async with session_scope(company_id=str(company_id)) as session:
            actions = (
                await session.execute(
                    text(
                        "SELECT action, count(*) FROM audit_log WHERE company_id = :c "
                        "AND action IN ('PUNCH_CREATED', 'ATTENDANCE_MANUAL_DAY_ENTRY') "
                        "GROUP BY action"
                    ),
                    {"c": str(company_id)},
                )
            ).all()
        assert dict(actions) == {"PUNCH_CREATED": 4, "ATTENDANCE_MANUAL_DAY_ENTRY": 1}
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_existing_punch_on_the_day_blocks_only_that_employee(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        eid = wired["employee"]["id"]
        other = await _plain_employee(client, headers)
        # 03:00Z is 08:30 IST on the same company-local day
        await _punch(client, headers, employee_id=eid, hour=3, minute=0, direction="IN")

        preview = _by_employee(await _preview(client, headers, _body([eid, other])))
        assert preview[eid]["outcome"] == "BLOCKED"
        assert preview[eid]["code"] == "EXISTING_PUNCHES"
        assert len(preview[eid]["existing_punches"]) == 1
        assert preview[other]["outcome"] == "READY"

        recorded = _by_employee(await _record(client, headers, _body([eid, other])))
        assert recorded[eid]["outcome"] == "BLOCKED"
        assert recorded[eid]["code"] == "EXISTING_PUNCHES"
        assert recorded[other]["outcome"] == "RECORDED"
        assert len(await _punches(client, headers, eid)) == 1, "nothing stacked on a partial day"
        assert len(await _punches(client, headers, other)) == 2
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_closed_period_blocks_and_stores_neither_punch(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        eid = wired["employee"]["id"]
        # Only the 10th is closed. The single on-behalf punch would still accept a punch here
        # (ingestion refuses only when the day before is closed too); a manual day must not.
        await _insert_closed_period(company_id=company_id, period_start=_DAY, period_end=_DAY)
        single = await client.post(
            "/v1/attendance/punches",
            headers=headers,
            json={"employee_id": eid, "punch_time": _IN, "direction": "IN", "reference": "x"},
        )
        assert single.status_code == 201, "precondition: ingestion's lenient rule still applies"
        await _cleanup_attendance_day_punches(company_id)

        preview = _by_employee(await _preview(client, headers, _body([eid])))
        assert preview[eid]["code"] == "ATTENDANCE_PERIOD_CLOSED"

        recorded = _by_employee(await _record(client, headers, _body([eid])))
        assert recorded[eid]["outcome"] == "BLOCKED"
        assert recorded[eid]["code"] == "ATTENDANCE_PERIOD_CLOSED"
        assert await _punches(client, headers, eid) == []
    finally:
        await _cleanup_attendance_period(company_id=company_id)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_out_punch_refusal_rolls_back_the_in_punch(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The IN would be accepted on its own; the OUT lands after the last working day. The
    employee's pair is one unit, so the IN must not be left behind."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        eid = wired["employee"]["id"]
        await _terminate(client, headers, eid, _DAY)
        # 22:00 IST on the 10th -> 06:00 IST on the 11th, the day after the last working day
        body = _body([eid], punch_in_at=f"{_DAY}T16:30:00Z", punch_out_at="2026-08-11T00:30:00Z")
        recorded = _by_employee(await _record(client, headers, body))
        assert recorded[eid]["outcome"] == "BLOCKED"
        assert recorded[eid]["code"] == "EMPLOYEE_TERMINATED"
        assert await _punches(client, headers, eid) == []
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_retry_with_same_key_replays_and_stores_nothing_twice(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        eid = wired["employee"]["id"]
        body = _body([eid], idempotency_key=uuid4().hex)

        first = _by_employee(await _record(client, headers, body))
        second = _by_employee(await _record(client, headers, body))
        assert first[eid]["outcome"] == "RECORDED" and first[eid]["replayed"] is False
        assert second[eid]["outcome"] == "RECORDED" and second[eid]["replayed"] is True
        assert {p["id"] for p in first[eid]["punches"]} == {p["id"] for p in second[eid]["punches"]}
        assert len(await _punches(client, headers, eid)) == 2

        # a new submission (no key) for the same day is now refused: the day already has punches
        again = _by_employee(await _record(client, headers, _body([eid])))
        assert again[eid]["code"] == "EXISTING_PUNCHES"
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_future_unknown_and_invalid_requests(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        eid = wired["employee"]["id"]

        future = _by_employee(
            await _record(
                client,
                headers,
                _body(
                    [eid], punch_in_at="2099-01-01T03:30:00Z", punch_out_at="2099-01-01T12:30:00Z"
                ),
            )
        )
        assert future[eid]["code"] == "PUNCH_TIME_IN_FUTURE"

        stranger = str(uuid4())
        unknown = _by_employee(await _record(client, headers, _body([stranger])))
        assert unknown[stranger]["outcome"] == "BLOCKED"
        assert unknown[stranger]["code"] == "NOT_FOUND"

        for bad in (
            _body([eid], punch_out_at=_IN, punch_in_at=_OUT),  # OUT before IN
            _body([eid], punch_out_at="2026-08-11T09:00:00Z"),  # 24h span, cap is 20h
            _body([eid, eid]),  # duplicate employee
            _body([eid], reason="  "),  # blank reason
            _body([]),  # nobody
            _body([str(uuid4()) for _ in range(51)]),  # over the cap
            _body([eid], source="WEB"),  # unknown field
        ):
            response = await _record(client, headers, bad)
            assert response.status_code == 422, (bad, response.text)
        assert await _punches(client, headers, eid) == []
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_employee_without_on_behalf_permission_is_refused(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, admin_user_id = await _register_tenant(client)
    employee_user_id: UUID | None = None
    try:
        wired = await _build_wired_employee(client, headers)
        eid = wired["employee"]["id"]
        email = f"manual-day-{uuid4().hex[:8]}@example.com"
        employee_user_id = await _link_user_to_employee(
            company_id=company_id,
            employee_id=UUID(eid),
            email=email,
            data_scope="SELF",
            permission_codes=(ATTENDANCE_PUNCH, ATTENDANCE_VIEW),
        )
        login = await client.post(
            "/v1/auth/login",
            json={"email": email, "password": _PASSWORD, "company_id": str(company_id)},
        )
        self_headers = {
            "Authorization": f"Bearer {login.json()['data']['access_token']}",
            "X-Company-Id": str(company_id),
        }
        # not even for their own day: backdating your own attendance is exactly what is guarded
        assert (await _preview(client, self_headers, _body([eid]))).status_code == 403
        assert (await _record(client, self_headers, _body([eid]))).status_code == 403
        assert await _punches(client, headers, eid) == []
    finally:
        async with get_session_factory()() as session:
            if employee_user_id is not None:
                for table in ("refresh_token", "session"):
                    await session.execute(
                        text(f"DELETE FROM {table} WHERE user_id = :u"),
                        {"u": str(employee_user_id)},
                    )
                await session.commit()
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=admin_user_id)
        if employee_user_id is not None:
            async with get_session_factory()() as session:
                await session.execute(
                    text('DELETE FROM "user" WHERE id = :u'), {"u": str(employee_user_id)}
                )
                await session.commit()


async def test_hr_cannot_mark_their_own_attendance(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Separation of duties: the caller holds `PUNCH_ON_BEHALF` at COMPANY scope, yet their own
    employee record is refused while a colleague in the same request is recorded."""
    headers, company_id, admin_user_id = await _register_tenant(client)
    hr_user_id: UUID | None = None
    try:
        wired = await _build_wired_employee(client, headers)
        hr_eid = wired["employee"]["id"]
        colleague = await _plain_employee(client, headers)
        email = f"manual-day-hr-{uuid4().hex[:8]}@example.com"
        hr_user_id = await _link_user_to_employee(
            company_id=company_id,
            employee_id=UUID(hr_eid),
            email=email,
            data_scope="COMPANY",
            permission_codes=(ATTENDANCE_PUNCH_ON_BEHALF, ATTENDANCE_VIEW),
        )
        login = await client.post(
            "/v1/auth/login",
            json={"email": email, "password": _PASSWORD, "company_id": str(company_id)},
        )
        hr_headers = {
            "Authorization": f"Bearer {login.json()['data']['access_token']}",
            "X-Company-Id": str(company_id),
        }
        preview = _by_employee(await _preview(client, hr_headers, _body([hr_eid, colleague])))
        assert preview[hr_eid]["code"] == "SELF_ENTRY_NOT_ALLOWED"
        assert preview[colleague]["outcome"] == "READY"

        recorded = _by_employee(await _record(client, hr_headers, _body([hr_eid, colleague])))
        assert recorded[hr_eid]["outcome"] == "BLOCKED"
        assert recorded[hr_eid]["code"] == "SELF_ENTRY_NOT_ALLOWED"
        assert recorded[colleague]["outcome"] == "RECORDED"
        assert await _punches(client, headers, hr_eid) == []
    finally:
        async with get_session_factory()() as session:
            if hr_user_id is not None:
                for table in ("refresh_token", "session"):
                    await session.execute(
                        text(f"DELETE FROM {table} WHERE user_id = :u"), {"u": str(hr_user_id)}
                    )
                await session.commit()
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=admin_user_id)
        if hr_user_id is not None:
            async with get_session_factory()() as session:
                await session.execute(
                    text('DELETE FROM "user" WHERE id = :u'), {"u": str(hr_user_id)}
                )
                await session.commit()
