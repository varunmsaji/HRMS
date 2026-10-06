"""A2 — a punch can never be created after the employee's last working day, on any path.

The last working day itself is a working day. The comparison uses the company-local calendar
date of the punch instant (never the server's or UTC's), so a rehire gap is also closed.
"""

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.auth.test_employee_jwt_linkage import _PASSWORD, _link_user_to_employee

from hrms.core.db.session import get_session_factory, session_scope
from hrms.core.errors.base import AppError
from hrms.core.rbac.types import DataScope, DataScopeLevel
from hrms.modules.attendance.permissions import ATTENDANCE_PUNCH, ATTENDANCE_VIEW
from hrms.modules.attendance.service import PunchService
from hrms.shared.business_time import business_today

from .test_attendance_day import (
    _build_wired_employee,
    _cleanup,
    _cleanup_attendance_day,
    _punch,
    _register_tenant,
)
from .test_attendance_edge_cases import _terminate

pytestmark = pytest.mark.asyncio


async def _on_behalf(client: AsyncClient, headers: dict, employee_id: str, instant: str):
    return await client.post(
        "/v1/attendance/punches",
        headers=headers,
        json={
            "employee_id": employee_id,
            "punch_time": instant,
            "direction": "IN",
            "reference": "a2 test",
        },
    )


async def _company_timezone(client: AsyncClient, headers: dict) -> str:
    return str(
        (await client.get("/v1/companies/current", headers=headers)).json()["data"]["timezone"]
    )


async def test_on_behalf_punch_allowed_on_last_working_day_rejected_after(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        eid = wired["employee"]["id"]
        await _terminate(client, headers, eid, "2026-08-11")

        on_day = await _on_behalf(client, headers, eid, "2026-08-11T10:00:00Z")
        assert on_day.status_code == 201, on_day.text

        after = await _on_behalf(client, headers, eid, "2026-08-12T10:00:00Z")
        assert after.status_code == 422, after.text
        error = after.json()["error"]
        assert error["code"] == "EMPLOYEE_TERMINATED"
        assert error["details"][0]["context"] == {"last_working_day": "2026-08-11"}
        assert "last working day" in error["message"]

        listed = await client.get(
            "/v1/attendance/punches", headers=headers, params={"employee_id": eid}
        )
        assert len(listed.json()["data"]) == 1, "the rejected punch must not be stored"
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_company_local_midnight_decides_the_boundary_not_utc(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        assert await _company_timezone(client, headers) == "Asia/Kolkata"  # UTC+05:30
        wired = await _build_wired_employee(client, headers)
        eid = wired["employee"]["id"]
        await _terminate(client, headers, eid, "2026-08-11")

        # 23:59 IST on the 11th is 18:29Z — still the last working day
        last_minute = await _on_behalf(client, headers, eid, "2026-08-11T18:29:00Z")
        assert last_minute.status_code == 201, last_minute.text
        # 00:00 IST on the 12th is 18:30Z on the 11th in UTC terms, but already the next day here
        midnight = await _on_behalf(client, headers, eid, "2026-08-11T18:30:00Z")
        assert midnight.status_code == 422, midnight.text
        assert midnight.json()["error"]["code"] == "EMPLOYEE_TERMINATED"
        # early morning IST of the 12th (UTC still the 11th) is rejected too
        early = await _on_behalf(client, headers, eid, "2026-08-11T20:00:00Z")
        assert early.status_code == 422
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_rehire_gap_is_rejected_and_new_employment_accepted(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        eid = wired["employee"]["id"]
        entity_id = (await client.get(f"/v1/employees/{eid}/employments", headers=headers)).json()[
            "data"
        ][0]["legal_entity_id"]
        await _terminate(client, headers, eid, "2026-08-11")
        rehire = await client.post(
            f"/v1/employees/{eid}/employments",
            headers=headers,
            json={"legal_entity_id": entity_id, "joining_date": "2026-09-01"},
        )
        assert rehire.status_code == 201, rehire.text

        assert (await _on_behalf(client, headers, eid, "2026-08-10T10:00:00Z")).status_code == 201
        gap = await _on_behalf(client, headers, eid, "2026-08-20T10:00:00Z")
        assert gap.status_code == 422 and gap.json()["error"]["code"] == "EMPLOYEE_TERMINATED"
        assert (await _on_behalf(client, headers, eid, "2026-09-02T10:00:00Z")).status_code == 201
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_self_punch_on_last_working_day_passes_and_after_it_is_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, admin_user_id = await _register_tenant(client)
    employee_user_id: UUID | None = None
    try:
        wired = await _build_wired_employee(client, headers)
        eid = wired["employee"]["id"]
        email = f"a2-{uuid4().hex[:8]}@example.com"
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
        async with session_scope(company_id=str(company_id)) as session:
            today = business_today(
                (
                    await session.execute(
                        text("SELECT timezone FROM company WHERE id = CAST(:c AS uuid)"),
                        {"c": str(company_id)},
                    )
                ).scalar_one()
            )

        # last working day == today (company-local): still working today, the HTTP route works
        await _terminate(client, headers, eid, today.isoformat())
        on_day = await client.post(
            "/v1/attendance/punches/me", headers=self_headers, json={"direction": "IN"}
        )
        assert on_day.status_code == 201, on_day.text

        # Move the last working day back a day directly (login revocation is the termination
        # flow's job; this isolates the punch rule on the self-service service path, which is
        # defence in depth behind that revocation).
        yesterday = today - timedelta(days=1)
        async with get_session_factory()() as session:
            await session.execute(
                text(
                    "UPDATE employment SET last_working_day = :d "
                    "WHERE employee_id = CAST(:e AS uuid)"
                ),
                {"d": yesterday, "e": eid},
            )
            await session.commit()
        async with session_scope(company_id=str(company_id)) as session:
            with pytest.raises(AppError) as raised:
                await PunchService(session).record_punch(
                    company_id,
                    UUID(eid),
                    direction="OUT",
                    requested_punch_time=None,
                    source="WEB",
                    reference=None,
                    idempotency_key=None,
                    scope=DataScope(levels=frozenset({DataScopeLevel.SELF})),
                    caller_employee_id=UUID(eid),
                    actor_user_id=None,
                )
        assert raised.value.code == "EMPLOYEE_TERMINATED"
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


async def test_existing_exited_calculation_and_idempotency_are_unchanged(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        eid = wired["employee"]["id"]
        other = (
            await client.post("/v1/employees", headers=headers, json={"first_name": "B"})
        ).json()["data"]
        first = await _punch(
            client, headers, employee_id=eid, hour=9, minute=0, direction="IN", idempotency_key="k1"
        )
        await _terminate(client, headers, eid, "2026-08-11")

        # a replay of a punch created before termination still replays (it creates nothing new)
        replay = await _punch(
            client, headers, employee_id=eid, hour=9, minute=0, direction="IN", idempotency_key="k1"
        )
        assert replay["id"] == first["id"]
        clash = await client.post(
            "/v1/attendance/punches",
            headers=headers,
            json={
                "employee_id": other["id"],
                "punch_time": "2026-08-10T09:00:00Z",
                "direction": "IN",
                "reference": "x",
                "idempotency_key": "k1",
            },
        )
        assert clash.status_code == 409
        assert clash.json()["error"]["code"] == "DUPLICATE_PUNCH_IDEMPOTENCY_KEY"

        # historical calculation after the last working day is still EXITED
        day = await client.post(
            "/v1/attendance/days/calculate",
            headers=headers,
            params={"employee_id": eid, "date": "2026-08-12"},
        )
        assert day.json()["data"]["attendance_status"] == "EXITED"
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
