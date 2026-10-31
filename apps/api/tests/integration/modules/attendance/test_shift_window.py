"""Self-service punch-in shift window end to end: real app, database, RBAC, RLS and audit log.

The service clock is pinned (`_freeze`) so each case chooses the punch instant relative to a
09:30-18:30 UTC shift on a fixed date. Branch and shift timezones are UTC."""

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.conftest import FakeFaceProvider, FakeLivenessEngine
from tests.integration.modules.attendance.test_attendance_day import (
    _cleanup_attendance_day,
    _register_tenant,
)
from tests.integration.modules.attendance.test_attendance_security import (
    _cleanup_scoped_users,
    _create_permission_scoped_user,
)
from tests.integration.modules.attendance.test_face_enrollment import enroll_and_approve
from tests.integration.modules.attendance.test_face_punch import issue, submit
from tests.integration.modules.attendance.test_geofence import KOCHI, RADIUS, fix, north
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.attendance import face_service
from hrms.modules.attendance import service as attendance_service
from hrms.modules.attendance.permissions import (
    ATTENDANCE_PUNCH,
    ATTENDANCE_PUNCH_ON_BEHALF,
    ATTENDANCE_VIEW,
)

pytestmark = pytest.mark.asyncio

PUNCH = "/v1/attendance/punches/me"
# A past date so the frozen instants are never in the future and no period is open or locked.
TODAY = (datetime.now(UTC) - timedelta(days=2)).date()
CONTEXT_KEYS = {
    "shift_start",
    "shift_end",
    "grace_in_minutes",
    "grace_out_minutes",
    "early_in_allowance_minutes",
    "earliest_punch_in",
}


def at(hour: int, minute: int = 0, *, days: int = 0) -> datetime:
    return datetime(TODAY.year, TODAY.month, TODAY.day, hour, minute, tzinfo=UTC) + timedelta(
        days=days
    )


def _freeze(monkeypatch: pytest.MonkeyPatch, instant: datetime, *modules: Any) -> None:
    class _Frozen(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
            return instant if tz is None else instant.astimezone(tz)

    monkeypatch.setattr(attendance_service, "datetime", _Frozen)
    for module in modules:
        monkeypatch.setattr(module, "datetime", _Frozen)


def _logged(out: str, event: str, reason: str) -> bool:
    for line in out.splitlines():
        if event not in line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            if reason in line:
                return True
            continue
        if payload.get("event") == event and payload.get("reason") == reason:
            return True
    return False


async def _sql(company_id: UUID, query: str, **params: Any) -> list[Any]:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        result = await session.execute(text(query), {"cid": str(company_id), **params})
        rows = list(result) if result.returns_rows else []
        await session.commit()
        return rows


async def _make_shift(
    client: AsyncClient,
    headers: dict[str, str],
    code: str,
    start: str,
    end: str,
    *,
    timezone: str = "UTC",
    **extra: Any,
) -> str:
    shift = (
        await client.post("/v1/shifts", headers=headers, json={"name": code, "code": code})
    ).json()["data"]
    draft_id = shift["draft_version_id"]
    patched = await client.patch(
        f"/v1/shifts/{shift['id']}/versions/{draft_id}",
        headers={**headers, "If-Match": "1"},
        json={
            "shift_type": "FIXED",
            "effective_from": "2026-01-01",
            "start_time": start,
            "end_time": end,
            "timezone": timezone,
            **extra,
        },
    )
    assert patched.status_code == 200, patched.text
    published = await client.post(
        f"/v1/shifts/{shift['id']}/versions/{draft_id}/publish",
        headers={**headers, "If-Match": "2"},
        json={},
    )
    assert published.status_code == 200, published.text
    return str(shift["id"])


async def _wire(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    allowance: int | None,
    shift: tuple[str, str] | None = ("09:30", "18:30"),
    grace_in: int = 10,
    grace_out: int = 15,
    missing_shift: str = "INCOMPLETE",
    branch_timezone: str = "UTC",
    shift_timezone: str = "UTC",
    shift_extra: dict[str, Any] | None = None,
    policy: bool = True,
    geofence: bool = False,
) -> dict[str, str]:
    """An employee assigned to `shift` (or none) under a company policy with the given grace and
    early-in allowance."""
    employee = (
        await client.post("/v1/employees", headers=headers, json={"first_name": "Asha"})
    ).json()["data"]
    legal_entity = (
        await client.post("/v1/legal-entities", headers=headers, json={"name": "LE"})
    ).json()["data"]
    branch = (
        await client.post(
            "/v1/branches",
            headers=headers,
            json={
                "legal_entity_id": legal_entity["id"],
                "name": "HQ",
                "timezone": branch_timezone,
                **(
                    {
                        "latitude": KOCHI[0],
                        "longitude": KOCHI[1],
                        "geofence_radius_m": RADIUS,
                    }
                    if geofence
                    else {}
                ),
            },
        )
    ).json()["data"]
    department = (
        await client.post(
            "/v1/departments", headers=headers, json={"name": "Eng", "branch_id": branch["id"]}
        )
    ).json()["data"]
    designation = (
        await client.post(
            "/v1/designations",
            headers=headers,
            json={"title": "Engineer", "department_id": department["id"]},
        )
    ).json()["data"]
    employment = await client.post(
        f"/v1/employees/{employee['id']}/employments",
        headers=headers,
        json={"legal_entity_id": legal_entity["id"], "joining_date": "2026-01-01"},
    )
    assert employment.status_code == 201, employment.text
    shift_id = (
        await _make_shift(
            client, headers, "DAY", *shift, timezone=shift_timezone, **(shift_extra or {})
        )
        if shift
        else None
    )
    assignment = await client.post(
        f"/v1/employees/{employee['id']}/assignments",
        headers=headers,
        json={
            "effective_from": "2026-01-01",
            "change_type": "INITIAL",
            "branch_id": branch["id"],
            "department_id": department["id"],
            "designation_id": designation["id"],
            "shift_id": shift_id,
        },
    )
    assert assignment.status_code == 201, assignment.text

    work_calendar = (
        await client.post("/v1/work-calendars", headers=headers, json={"name": "Default"})
    ).json()["data"]
    calendar_assignment = await client.post(
        "/v1/policy-assignments",
        headers=headers,
        json={
            "policy_kind": "WORK_CALENDAR",
            "policy_id": work_calendar["id"],
            "scope_type": "COMPANY",
            "effective_from": "2026-01-01",
        },
    )
    assert calendar_assignment.status_code == 201, calendar_assignment.text

    policy_id = ""
    if policy:
        created = (
            await client.post("/v1/attendance-policies", headers=headers, json={"name": "Window"})
        ).json()["data"]
        version_body: dict[str, Any] = {
            "effective_from": "2026-01-01",
            "grace_in_minutes": grace_in,
            "grace_out_minutes": grace_out,
            "early_in_allowance_minutes": allowance,
            "missing_shift_behaviour": missing_shift,
            "hour_bands": [{"min_minutes": 0, "max_minutes": None, "result_status": "PRESENT"}],
        }
        if geofence:
            version_body.update(
                geofence_mode="REQUIRED",
                geofence_max_accuracy_m=50,
                geofence_max_age_seconds=60,
            )
        draft = await client.post(
            f"/v1/attendance-policies/{created['id']}/versions",
            headers=headers,
            json=version_body,
        )
        assert draft.status_code == 201, draft.text
        assert draft.json()["data"]["early_in_allowance_minutes"] == allowance
        published = await client.post(
            f"/v1/attendance-policies/{created['id']}/versions/{draft.json()['data']['id']}/publish",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert published.status_code == 200, published.text
        pa = await client.post(
            "/v1/policy-assignments",
            headers=headers,
            json={
                "policy_kind": "ATTENDANCE_POLICY",
                "policy_id": created["id"],
                "scope_type": "COMPANY",
                "effective_from": "2026-01-01",
            },
        )
        assert pa.status_code == 201, pa.text
        policy_id = created["id"]
    return {
        "employee_id": employee["id"],
        "shift_id": shift_id or "",
        "work_calendar_id": work_calendar["id"],
        "work_calendar_version": str(work_calendar["version"]),
        "policy_id": policy_id,
        "branch_id": branch["id"],
    }


@pytest.fixture
async def tenant(
    client: AsyncClient, seeded_plan_catalogue: None
) -> AsyncIterator[tuple[dict[str, str], UUID]]:
    headers, company_id, user_id = await _register_tenant(client)
    yield headers, company_id
    # Off-day fixtures add calendar rows the attendance cleanup does not know about. Clear them
    # before it deletes `work_calendar` and before the company row itself goes.
    await _sql(
        company_id, "DELETE FROM work_calendar_holiday_calendar WHERE company_id = :cid"
    )
    await _sql(
        company_id,
        "UPDATE work_calendar SET weekly_off_pattern_id = NULL WHERE company_id = :cid",
    )
    await _sql(company_id, "DELETE FROM weekly_off_rule WHERE company_id = :cid")
    await _sql(company_id, "DELETE FROM weekly_off_pattern WHERE company_id = :cid")
    await _sql(company_id, "DELETE FROM holiday WHERE company_id = :cid")
    await _sql(company_id, "DELETE FROM holiday_calendar WHERE company_id = :cid")
    await _sql(company_id, "DELETE FROM geofence_attempt WHERE company_id = :cid")
    await _cleanup_attendance_day(company_id=company_id)
    await _cleanup(company_id=company_id, user_id=user_id)
    await _cleanup_scoped_users()


async def _self(company_id: UUID, employee_id: str) -> dict[str, str]:
    headers, _ = await _create_permission_scoped_user(
        company_id=company_id,
        permission_codes=[ATTENDANCE_PUNCH, ATTENDANCE_VIEW],
        data_scope="SELF",
        caller_employee_id=UUID(employee_id),
    )
    return headers


async def _punch(
    client: AsyncClient,
    headers: dict[str, str],
    direction: str = "IN",
    **extra: Any,
) -> Any:
    return await client.post(PUNCH, headers=headers, json={"direction": direction, **extra})


async def _punch_count(company_id: UUID, employee_id: str) -> int:
    rows = await _sql(
        company_id,
        "SELECT count(*) FROM punch WHERE company_id = :cid AND employee_id = :eid",
        eid=employee_id,
    )
    return int(rows[0][0])


async def _punch_audit_actions(company_id: UUID) -> list[str]:
    rows = await _sql(
        company_id,
        "SELECT action FROM audit_log WHERE company_id = :cid AND action LIKE 'PUNCH\\_%' "
        "ORDER BY occurred_at",
    )
    return [r[0] for r in rows]


# --- the refusal ----------------------------------------------------------------------------


async def test_too_early_is_refused_and_nothing_is_persisted(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, allowance=60)
    me = await _self(company_id, wired["employee_id"])
    _freeze(monkeypatch, at(8, 29))

    response = await _punch(client, me)

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["error"]["code"] == "OUTSIDE_SHIFT_WINDOW"
    context = body["error"]["details"][0]["context"]
    assert set(context) == CONTEXT_KEYS
    assert context == {
        "shift_start": at(9, 30).isoformat(),
        "shift_end": at(18, 30).isoformat(),
        "grace_in_minutes": 10,
        "grace_out_minutes": 15,
        "early_in_allowance_minutes": 60,
        "earliest_punch_in": at(8, 30).isoformat(),
    }
    assert wired["employee_id"] not in response.text
    assert await _punch_count(company_id, wired["employee_id"]) == 0
    days = await _sql(company_id, "SELECT count(*) FROM attendance_day WHERE company_id = :cid")
    assert days[0][0] == 0
    actions = await _punch_audit_actions(company_id)
    assert "PUNCH_CREATED" not in actions
    assert "PUNCH_REJECTED_OUTSIDE_SHIFT_WINDOW" in actions


@pytest.mark.parametrize(("hour", "minute"), [(8, 30), (9, 0), (9, 30)])
async def test_at_the_boundary_and_within_the_allowance_is_recorded(
    client: AsyncClient,
    tenant: tuple[dict[str, str], UUID],
    monkeypatch: pytest.MonkeyPatch,
    hour: int,
    minute: int,
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, allowance=60)
    me = await _self(company_id, wired["employee_id"])
    _freeze(monkeypatch, at(hour, minute))

    response = await _punch(client, me)

    assert response.status_code == 201, response.text
    assert await _punch_count(company_id, wired["employee_id"]) == 1


async def test_late_punch_is_recorded_and_marked_late_by_the_engine(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, allowance=60)
    me = await _self(company_id, wired["employee_id"])
    _freeze(monkeypatch, at(10, 30))  # 60 min after start, grace-in 10

    assert (await _punch(client, me)).status_code == 201
    _freeze(monkeypatch, at(18, 0))
    assert (await _punch(client, me, "OUT")).status_code == 201
    rows = await _sql(
        company_id,
        "SELECT late_minutes FROM attendance_day WHERE company_id = :cid AND employee_id = :eid",
        eid=wired["employee_id"],
    )
    assert rows and rows[0][0] == 50


async def test_punch_after_shift_end_plus_grace_out_is_recorded(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, allowance=60)
    me = await _self(company_id, wired["employee_id"])
    _freeze(monkeypatch, at(19, 0))

    assert (await _punch(client, me, "OUT")).status_code == 201
    assert (await _punch(client, me, "IN")).status_code == 201
    assert await _punch_count(company_id, wired["employee_id"]) == 2


async def test_punch_out_is_never_refused(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, allowance=60)
    me = await _self(company_id, wired["employee_id"])
    _freeze(monkeypatch, at(6, 0))

    assert (await _punch(client, me, "OUT")).status_code == 201


async def test_null_allowance_never_refuses(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, allowance=None)
    me = await _self(company_id, wired["employee_id"])
    _freeze(monkeypatch, at(3, 0))

    assert (await _punch(client, me)).status_code == 201


@pytest.mark.parametrize("behaviour", ["INCOMPLETE", "ABSENT"])
async def test_no_shift_is_recorded_whatever_the_missing_shift_behaviour(
    client: AsyncClient,
    tenant: tuple[dict[str, str], UUID],
    monkeypatch: pytest.MonkeyPatch,
    behaviour: str,
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, allowance=60, shift=None, missing_shift=behaviour)
    me = await _self(company_id, wired["employee_id"])
    _freeze(monkeypatch, at(3, 0))

    assert (await _punch(client, me)).status_code == 201
    rows = await _sql(
        company_id,
        "SELECT attendance_status FROM attendance_day "
        "WHERE company_id = :cid AND employee_id = :eid",
        eid=wired["employee_id"],
    )
    # The day was calculated normally (no shift is not a config error); the punch was not judged.
    assert rows and rows[0][0] != "CONFIG_ERROR"


async def test_published_roster_shift_overrides_the_assigned_shift(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, allowance=60)  # assigned 09:30-18:30
    afternoon = await _make_shift(client, admin, "AFT", "15:00", "23:00")
    created = await client.post(
        "/v1/rosters",
        headers=admin,
        json={
            "employee_id": wired["employee_id"],
            "roster_date": TODAY.isoformat(),
            "shift_id": afternoon,
        },
    )
    assert created.status_code == 201, created.text
    published = await client.post(
        f"/v1/rosters/{created.json()['data']['id']}/publish",
        headers={**admin, "If-Match": "1"},
        json={},
    )
    assert published.status_code == 200, published.text
    me = await _self(company_id, wired["employee_id"])
    _freeze(monkeypatch, at(12, 0))  # fine for 09:30, 2h early for 15:00

    response = await _punch(client, me)

    assert response.status_code == 422, response.text
    assert response.json()["error"]["details"][0]["context"]["shift_start"] == at(15).isoformat()


async def test_overnight_shift_uses_yesterdays_shift_after_midnight(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, allowance=60, shift=("22:00", "06:00"))
    me = await _self(company_id, wired["employee_id"])

    _freeze(monkeypatch, at(20, 30))  # before 21:00 on the shift's start date
    assert (await _punch(client, me)).status_code == 422

    _freeze(monkeypatch, at(21, 0))
    assert (await _punch(client, me)).status_code == 201

    # 00:30 the next day is inside the shift that started the evening before.
    _freeze(monkeypatch, at(0, 30, days=1))
    assert (await _punch(client, me)).status_code == 201


async def test_admin_on_behalf_punch_is_not_checked(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID]
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, allowance=60)
    headers, _ = await _create_permission_scoped_user(
        company_id=company_id,
        permission_codes=[ATTENDANCE_PUNCH_ON_BEHALF, ATTENDANCE_VIEW],
        data_scope="COMPANY",
    )

    response = await client.post(
        "/v1/attendance/punches",
        headers=headers,
        json={
            "employee_id": wired["employee_id"],
            "punch_time": at(3, 0).isoformat().replace("+00:00", "Z"),
            "direction": "IN",
            "reference": "correction",
        },
    )

    assert response.status_code == 201, response.text
    assert await _punch_count(company_id, wired["employee_id"]) == 1


async def test_policy_rejects_a_negative_allowance(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID]
) -> None:
    admin, _ = tenant
    policy = (
        await client.post("/v1/attendance-policies", headers=admin, json={"name": "Neg"})
    ).json()["data"]
    response = await client.post(
        f"/v1/attendance-policies/{policy['id']}/versions",
        headers=admin,
        json={"early_in_allowance_minutes": -1},
    )
    assert response.status_code == 422, response.text


async def test_allowance_round_trips_through_create_update_and_read(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID]
) -> None:
    admin, _company_id = tenant
    policy = (
        await client.post("/v1/attendance-policies", headers=admin, json={"name": "Round trip"})
    ).json()["data"]
    created = await client.post(
        f"/v1/attendance-policies/{policy['id']}/versions",
        headers=admin,
        json={"effective_from": "2026-01-01", "early_in_allowance_minutes": 60},
    )
    assert created.status_code == 201, created.text
    version = created.json()["data"]
    path = f"/v1/attendance-policies/{policy['id']}/versions/{version['id']}"

    fetched = await client.get(path, headers=admin)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["data"]["early_in_allowance_minutes"] == 60

    zero = await client.patch(
        path,
        headers={**admin, "If-Match": str(version["version"])},
        json={"early_in_allowance_minutes": 0},
    )
    assert zero.status_code == 200, zero.text
    assert zero.json()["data"]["early_in_allowance_minutes"] == 0

    cleared = await client.patch(
        path,
        headers={**admin, "If-Match": str(zero.json()["data"]["version"])},
        json={"early_in_allowance_minutes": None},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["data"]["early_in_allowance_minutes"] is None
    again = await client.get(path, headers=admin)
    assert again.json()["data"]["early_in_allowance_minutes"] is None


async def test_company_date_across_midnight_does_not_replace_the_branch_date(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    """23:30 UTC is still today on a UTC branch and already the next morning in India.

    Tomorrow's shift has not started. Using the company date would refuse the punch. The branch
    date's shift has finished, so the punch is recorded.
    """
    admin, company_id = tenant
    wired = await _wire(client, admin, allowance=60)
    me = await _self(company_id, wired["employee_id"])
    punch = at(23, 30)
    assert punch.astimezone(ZoneInfo("Asia/Kolkata")).date() != punch.date()
    _freeze(monkeypatch, punch)

    response = await _punch(client, me)

    assert response.status_code == 201, response.text


def _utc(local: datetime) -> str:
    return local.astimezone(UTC).isoformat()


async def _patch_calendar(
    client: AsyncClient, headers: dict[str, str], wired: dict[str, str], body: dict[str, Any]
) -> None:
    response = await client.patch(
        f"/v1/work-calendars/{wired['work_calendar_id']}",
        headers={**headers, "If-Match": wired["work_calendar_version"]},
        json=body,
    )
    assert response.status_code == 200, response.text


async def _weekly_off_today(
    client: AsyncClient, headers: dict[str, str], wired: dict[str, str]
) -> None:
    pattern = await client.post(
        "/v1/weekly-off-patterns",
        headers=headers,
        json={
            "name": "Off today",
            "pattern_kind": "FIXED_WEEKDAYS",
            "rules": [{"weekday": TODAY.weekday(), "off_fraction": "1.00"}],
        },
    )
    assert pattern.status_code == 201, pattern.text
    await _patch_calendar(
        client, headers, wired, {"weekly_off_pattern_id": pattern.json()["data"]["id"]}
    )


async def _holiday_today(
    client: AsyncClient, headers: dict[str, str], wired: dict[str, str]
) -> None:
    calendar = await client.post("/v1/holiday-calendars", headers=headers, json={"name": "Closed"})
    assert calendar.status_code == 201, calendar.text
    calendar_id = calendar.json()["data"]["id"]
    holiday = await client.post(
        f"/v1/holiday-calendars/{calendar_id}/holidays",
        headers=headers,
        json={"date": TODAY.isoformat(), "name": "Closed"},
    )
    assert holiday.status_code == 201, holiday.text
    await _patch_calendar(client, headers, wired, {"holiday_calendar_ids": [calendar_id]})


async def _publish_roster(
    client: AsyncClient,
    headers: dict[str, str],
    employee_id: str,
    *,
    shift_id: str | None,
    **flags: bool,
) -> None:
    created = await client.post(
        "/v1/rosters",
        headers=headers,
        json={
            "employee_id": employee_id,
            "roster_date": TODAY.isoformat(),
            "shift_id": shift_id,
            **flags,
        },
    )
    assert created.status_code == 201, created.text
    published = await client.post(
        f"/v1/rosters/{created.json()['data']['id']}/publish",
        headers={**headers, "If-Match": "1"},
        json={},
    )
    assert published.status_code == 200, published.text


async def test_previous_day_finished_shift_does_not_excuse_an_early_punch_in(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, allowance=60)
    me = await _self(company_id, wired["employee_id"])
    _freeze(monkeypatch, at(7, 0))

    response = await _punch(client, me)

    assert response.status_code == 422, response.text
    assert await _punch_count(company_id, wired["employee_id"]) == 0


async def test_weekly_off_does_not_bypass_the_assigned_shift_window(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A calendar weekly off is not permission to punch early, and not a block on the shift."""
    admin, company_id = tenant
    wired = await _wire(client, admin, allowance=60)
    await _weekly_off_today(client, admin, wired)
    me = await _self(company_id, wired["employee_id"])

    _freeze(monkeypatch, at(8, 0))
    early = await _punch(client, me)
    assert early.status_code == 422, early.text
    assert early.json()["error"]["code"] == "OUTSIDE_SHIFT_WINDOW"

    _freeze(monkeypatch, at(9, 30))
    on_time = await _punch(client, me)
    assert on_time.status_code == 201, on_time.text


async def test_shift_that_operates_on_weekly_off_is_still_windowed(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, allowance=60, shift_extra={"operates_on_weekly_off": True})
    await _weekly_off_today(client, admin, wired)
    me = await _self(company_id, wired["employee_id"])
    _freeze(monkeypatch, at(8, 0))

    response = await _punch(client, me)

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "OUTSIDE_SHIFT_WINDOW"


async def test_assigned_shift_on_a_holiday_keeps_the_shift_window(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A standing assignment is authority to work that shift. The holiday does not reject it,
    and it does not open the punch to any time of day."""
    admin, company_id = tenant
    wired = await _wire(client, admin, allowance=60)
    await _holiday_today(client, admin, wired)
    me = await _self(company_id, wired["employee_id"])

    _freeze(monkeypatch, at(8, 0))
    early = await _punch(client, me)
    assert early.status_code == 422, early.text
    assert early.json()["error"]["code"] == "OUTSIDE_SHIFT_WINDOW"

    _freeze(monkeypatch, at(9, 30))
    allowed = await _punch(client, me)
    assert allowed.status_code == 201, allowed.text


async def test_holiday_working_roster_does_not_bypass_its_own_window(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, allowance=60)
    await _holiday_today(client, admin, wired)
    afternoon = await _make_shift(client, admin, "AFT", "15:00", "23:00")
    await _publish_roster(
        client,
        admin,
        wired["employee_id"],
        shift_id=afternoon,
        is_holiday_working_override=True,
    )
    me = await _self(company_id, wired["employee_id"])

    # 12:00 is inside the assigned 09:30 shift and early for the authorized 15:00 shift.
    _freeze(monkeypatch, at(12, 0))
    early = await _punch(client, me)
    assert early.status_code == 422, early.text
    context = early.json()["error"]["details"][0]["context"]
    assert context["shift_start"] == at(15).isoformat()

    _freeze(monkeypatch, at(14, 0))
    allowed = await _punch(client, me)
    assert allowed.status_code == 201, allowed.text


async def test_week_off_override_without_a_shift_is_accepted_as_no_shift(
    client: AsyncClient,
    tenant: tuple[dict[str, str], UUID],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An explicit week-off roster removes the shift. It does not waive the window for anyone
    who still has one — that case is the weekly-off test above."""
    admin, company_id = tenant
    wired = await _wire(client, admin, allowance=60)
    await _publish_roster(
        client, admin, wired["employee_id"], shift_id=None, is_week_off_override=True
    )
    me = await _self(company_id, wired["employee_id"])
    _freeze(monkeypatch, at(3, 0))
    capsys.readouterr()

    response = await _punch(client, me)

    assert response.status_code == 201, response.text
    assert _logged(capsys.readouterr().out, "punch_shift_window_skipped", "no_shift")


async def test_missing_policy_is_accepted_and_logged(
    client: AsyncClient,
    tenant: tuple[dict[str, str], UUID],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, allowance=60, policy=False)
    me = await _self(company_id, wired["employee_id"])
    _freeze(monkeypatch, at(3, 0))
    capsys.readouterr()

    response = await _punch(client, me)

    assert response.status_code == 201, response.text
    assert await _punch_count(company_id, wired["employee_id"]) == 1
    assert _logged(capsys.readouterr().out, "punch_shift_window_skipped", "no_policy")


async def test_missing_shift_is_accepted_and_logged(
    client: AsyncClient,
    tenant: tuple[dict[str, str], UUID],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, allowance=60, shift=None)
    me = await _self(company_id, wired["employee_id"])
    _freeze(monkeypatch, at(3, 0))
    capsys.readouterr()

    assert (await _punch(client, me)).status_code == 201
    assert _logged(capsys.readouterr().out, "punch_shift_window_skipped", "no_shift")


async def test_branch_timezone_across_midnight_uses_the_branch_date(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    """02:00 UTC is still the previous evening in Los Angeles and already morning in India.

    Judging the punch against the company date's shift would call it too early. The branch
    date's shift has already ended, so the punch is recorded.
    """
    admin, company_id = tenant
    wired = await _wire(
        client,
        admin,
        allowance=60,
        branch_timezone="America/Los_Angeles",
        shift_timezone="America/Los_Angeles",
    )
    me = await _self(company_id, wired["employee_id"])
    punch = at(2, 0)
    company_date = punch.astimezone(ZoneInfo("Asia/Kolkata")).date()
    branch_date = punch.astimezone(ZoneInfo("America/Los_Angeles")).date()
    assert company_date != branch_date
    _freeze(monkeypatch, punch)

    response = await _punch(client, me)

    assert response.status_code == 201, response.text


async def test_shift_timezone_across_midnight_does_not_false_reject(
    client: AsyncClient,
    tenant: tuple[dict[str, str], UUID],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The branch date's shift has not started; the shift-timezone date's shift has ended.
    Refusing would pick the wrong date. The punch is recorded and the disagreement is logged.
    """
    admin, company_id = tenant
    wired = await _wire(
        client,
        admin,
        allowance=60,
        branch_timezone="Asia/Kolkata",
        shift_timezone="America/Los_Angeles",
    )
    me = await _self(company_id, wired["employee_id"])
    punch = at(2, 0)
    kolkata = punch.astimezone(ZoneInfo("Asia/Kolkata")).date()
    los_angeles = punch.astimezone(ZoneInfo("America/Los_Angeles")).date()
    assert kolkata != los_angeles
    _freeze(monkeypatch, punch)
    capsys.readouterr()

    response = await _punch(client, me)

    assert response.status_code == 201, response.text
    out = capsys.readouterr().out
    assert _logged(out, "punch_shift_window_skipped", "timezone_date_disagreement")


async def test_shift_timezone_rejects_an_early_punch_on_the_shared_date(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    """14:00 UTC is 19:30 in India and 07:00 in Los Angeles — one date, early for the shift."""
    admin, company_id = tenant
    wired = await _wire(
        client,
        admin,
        allowance=60,
        branch_timezone="Asia/Kolkata",
        shift_timezone="America/Los_Angeles",
    )
    me = await _self(company_id, wired["employee_id"])
    punch = at(14, 0)
    zone = ZoneInfo("America/Los_Angeles")
    assert punch.astimezone(ZoneInfo("Asia/Kolkata")).date() == punch.astimezone(zone).date()
    _freeze(monkeypatch, punch)

    response = await _punch(client, me)

    assert response.status_code == 422, response.text
    start = datetime(TODAY.year, TODAY.month, TODAY.day, 9, 30, tzinfo=zone)
    assert response.json()["error"]["details"][0]["context"]["shift_start"] == _utc(start)


async def test_unresolvable_branch_timezone_fails_open(
    client: AsyncClient,
    tenant: tuple[dict[str, str], UUID],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, allowance=60)
    await _sql(
        company_id,
        "UPDATE branch SET timezone = 'Not/AZone' WHERE company_id = :cid AND id = :bid",
        bid=wired["branch_id"],
    )
    me = await _self(company_id, wired["employee_id"])
    _freeze(monkeypatch, at(3, 0))
    capsys.readouterr()

    response = await _punch(client, me)

    assert response.status_code == 201, response.text
    assert _logged(capsys.readouterr().out, "punch_shift_window_skipped", "unresolvable_timezone")


async def test_unresolvable_company_timezone_still_uses_a_valid_branch(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, allowance=60)
    await _sql(company_id, "UPDATE company SET timezone = 'Not/AZone' WHERE id = :cid")
    me = await _self(company_id, wired["employee_id"])
    _freeze(monkeypatch, at(3, 0))

    response = await _punch(client, me)

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "OUTSIDE_SHIFT_WINDOW"


async def test_unresolvable_shift_timezone_fails_open(
    client: AsyncClient,
    tenant: tuple[dict[str, str], UUID],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, allowance=60)
    await _sql(
        company_id,
        "UPDATE shift_version SET timezone = 'Not/AZone' WHERE company_id = :cid",
    )
    me = await _self(company_id, wired["employee_id"])
    _freeze(monkeypatch, at(3, 0))
    capsys.readouterr()

    response = await _punch(client, me)

    assert response.status_code == 201, response.text
    assert _logged(capsys.readouterr().out, "punch_shift_window_skipped", "unresolvable_timezone")


async def test_idempotent_replay_is_not_rejudged_against_a_later_clock(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, allowance=60)
    me = await _self(company_id, wired["employee_id"])
    key = "shift-window-replay-01"
    _freeze(monkeypatch, at(9, 0))
    first = await _punch(client, me, idempotency_key=key)
    assert first.status_code == 201, first.text
    _freeze(monkeypatch, at(3, 0))

    again = await _punch(client, me, idempotency_key=key)

    assert again.status_code == 201, again.text
    assert again.json()["data"]["id"] == first.json()["data"]["id"]
    assert await _punch_count(company_id, wired["employee_id"]) == 1
    actions = await _punch_audit_actions(company_id)
    assert "PUNCH_REJECTED_OUTSIDE_SHIFT_WINDOW" not in actions


async def test_rejected_early_punch_does_not_burn_the_idempotency_key(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, allowance=60)
    me = await _self(company_id, wired["employee_id"])
    key = "shift-window-retry-0001"
    _freeze(monkeypatch, at(3, 0))
    refused = await _punch(client, me, idempotency_key=key)
    assert refused.status_code == 422, refused.text
    _freeze(monkeypatch, at(9, 0))

    accepted = await _punch(client, me, idempotency_key=key)

    assert accepted.status_code == 201, accepted.text
    assert await _punch_count(company_id, wired["employee_id"]) == 1


async def test_geofence_refusal_happens_before_the_shift_window(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, allowance=60, geofence=True)
    me = await _self(company_id, wired["employee_id"])
    _freeze(monkeypatch, at(3, 0))

    response = await _punch(client, me, location=fix(north(2000)))

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "PUNCH_OUTSIDE_GEOFENCE"
    actions = await _punch_audit_actions(company_id)
    assert "PUNCH_REJECTED_GEOFENCE" in actions
    assert "PUNCH_REJECTED_OUTSIDE_SHIFT_WINDOW" not in actions
    assert await _punch_count(company_id, wired["employee_id"]) == 0


async def test_inside_the_geofence_an_early_punch_is_still_refused_with_no_writes(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, allowance=60, geofence=True)
    me = await _self(company_id, wired["employee_id"])
    _freeze(monkeypatch, at(3, 0))

    response = await _punch(client, me, location=fix(north(10)))

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "OUTSIDE_SHIFT_WINDOW"
    assert await _punch_count(company_id, wired["employee_id"]) == 0
    days = await _sql(company_id, "SELECT count(*) FROM attendance_day WHERE company_id = :cid")
    attempts = await _sql(
        company_id, "SELECT count(*) FROM geofence_attempt WHERE company_id = :cid"
    )
    assert days[0][0] == 0
    assert attempts[0][0] == 0
    assert "PUNCH_CREATED" not in await _punch_audit_actions(company_id)


async def test_inside_the_geofence_an_on_time_punch_is_recorded(
    client: AsyncClient, tenant: tuple[dict[str, str], UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, allowance=60, geofence=True)
    me = await _self(company_id, wired["employee_id"])
    _freeze(monkeypatch, at(9, 0))

    response = await _punch(client, me, location=fix(KOCHI))

    assert response.status_code == 201, response.text
    assert await _punch_count(company_id, wired["employee_id"]) == 1


async def test_rejected_early_punch_emits_the_security_event(
    client: AsyncClient,
    tenant: tuple[dict[str, str], UUID],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    admin, company_id = tenant
    wired = await _wire(client, admin, allowance=60)
    me = await _self(company_id, wired["employee_id"])
    _freeze(monkeypatch, at(3, 0))
    capsys.readouterr()

    response = await _punch(client, me)

    assert response.status_code == 422, response.text
    assert _logged(capsys.readouterr().out, "security.punch.rejected", "OUTSIDE_SHIFT_WINDOW")
    assert "PUNCH_REJECTED_OUTSIDE_SHIFT_WINDOW" in await _punch_audit_actions(company_id)
    assert await _punch_count(company_id, wired["employee_id"]) == 0


async def test_early_face_punch_does_not_consume_the_liveness_challenge(
    client: AsyncClient,
    face_tenant: tuple[dict[str, str], UUID],
    fake_face_provider: FakeFaceProvider,
    fake_liveness_engine: FakeLivenessEngine,
    fake_photo_storage: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    admin, company_id = face_tenant
    wired = await _wire(client, admin, allowance=60)
    me = await enroll_and_approve(client, admin, company_id, wired["employee_id"])
    session_id = await issue(client, me)
    fake_face_provider.calls.clear()
    fake_liveness_engine.calls.clear()
    _freeze(monkeypatch, at(8, 29), face_service)
    capsys.readouterr()

    refused = await submit(client, me, session_id=session_id)

    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["code"] == "OUTSIDE_SHIFT_WINDOW"
    assert fake_liveness_engine.calls == []
    assert fake_face_provider.calls == []
    status = await _sql(
        company_id, "SELECT status FROM face_liveness_session WHERE company_id = :cid"
    )
    assert [row[0] for row in status] == ["ISSUED"]
    attempts = await _sql(
        company_id, "SELECT count(*) FROM face_verification_attempt WHERE company_id = :cid"
    )
    days = await _sql(company_id, "SELECT count(*) FROM attendance_day WHERE company_id = :cid")
    assert attempts[0][0] == 0
    assert days[0][0] == 0
    assert await _punch_count(company_id, wired["employee_id"]) == 0
    assert "PUNCH_REJECTED_OUTSIDE_SHIFT_WINDOW" in await _punch_audit_actions(company_id)
    assert "PUNCH_CREATED" not in await _punch_audit_actions(company_id)
    assert _logged(capsys.readouterr().out, "security.punch.rejected", "OUTSIDE_SHIFT_WINDOW")

    _freeze(monkeypatch, at(9, 0), face_service)
    accepted = await submit(client, me, session_id=session_id)
    assert accepted.status_code == 201, accepted.text
    assert await _punch_count(company_id, wired["employee_id"]) == 1
