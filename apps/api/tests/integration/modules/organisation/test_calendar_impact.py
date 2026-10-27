"""Work-calendar change-impact preview and safe confirmation (`/v1/work-calendar-changes/*`).

Needs the disposable integration stack (the root conftest refuses the shared dev stack).

September 2026: 1 Sep is a Tuesday; Sundays 6/13/20/27, Saturdays 5/12/19/26, Wed 9, Thu 10, Fri 11.
Company work calendar "A" has Sunday off and (here) one linked holiday calendar "H".
"""

import asyncio
import hashlib
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import event, text
from tests.integration.modules.leave.test_leave_application import (
    _cleanup,
    _create_employee,
    _create_employment,
    _register_tenant,
    _setup_full,
    _submit,
    _teardown,
)
from tests.integration.modules.leave.test_leave_rbac_matrix import _user_with_default_role

from hrms.core.db.session import get_engine, get_session_factory, set_rls_company_id

from .test_employee_calendar import _assign, _employee_calendar_b, _set_leave_status
from .test_workforce_calendar import (
    _cleanup_workforce_calendar,
    _create_holiday_calendar,
)

pytestmark = pytest.mark.asyncio

PREVIEW = "/v1/work-calendar-changes/preview"
CONFIRM = "/v1/work-calendar-changes/confirm"
WINDOW = {"window_from": "2026-09-01", "window_to": "2026-09-30"}

_TABLES = (
    "holiday",
    "calendar_exception",
    "policy_assignment",
    "weekly_off_rule",
    "work_calendar_holiday_calendar",
    "leave_application",
    "leave_application_day",
    "leave_ledger",
    "attendance_day",
    "attendance_period",
    "pay_run",
    "audit_log",
)


async def _state(company_id: UUID) -> dict[str, Any]:
    """Row counts for every table a preview must not touch, plus a content hash of the records a
    confirmation must not rewrite."""
    out: dict[str, Any] = {}
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        for table in _TABLES:
            out[table] = (
                await session.execute(
                    text(f"SELECT count(*) FROM {table} WHERE company_id = CAST(:c AS uuid)"),
                    {"c": str(company_id)},
                )
            ).scalar_one()
        for table in ("leave_application_day", "leave_application", "attendance_period", "pay_run"):
            out[f"{table}_hash"] = (
                await session.execute(
                    text(
                        f"SELECT coalesce(md5(string_agg(t::text, '|' ORDER BY t.id::text)), '') "
                        f"FROM {table} t WHERE company_id = CAST(:c AS uuid)"
                    ),
                    {"c": str(company_id)},
                )
            ).scalar_one()
    return out


async def _audit_count(company_id: UUID, action: str) -> int:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM audit_log WHERE company_id = CAST(:c AS uuid) "
                        "AND action = :a"
                    ),
                    {"c": str(company_id), "a": action},
                )
            ).scalar_one()
        )


class World:
    def __init__(self) -> None:
        self.admin: dict[str, str] = {}
        self.company_id: UUID
        self.user_id: UUID | None
        self.ctx: dict[str, Any] = {}
        self.calendar: dict[str, Any] = {}
        self.holidays: dict[str, Any] = {}
        self.other_employee: dict[str, Any] = {}

    @property
    def employee_id(self) -> str:
        return str(self.ctx["employee"]["id"])


async def _world(client: AsyncClient, *, other_joining: str = "2024-01-01") -> World:
    w = World()
    w.admin, w.company_id, w.user_id = await _register_tenant(client)
    w.ctx = await _setup_full(client, w.admin)
    calendars = await client.get("/v1/work-calendars", headers=w.admin)
    w.calendar = calendars.json()["data"][0]
    w.holidays = await _create_holiday_calendar(client, w.admin, name="H")
    link = await client.patch(
        f"/v1/work-calendars/{w.calendar['id']}",
        headers={**w.admin, "If-Match": str(w.calendar["version"])},
        json={"holiday_calendar_ids": [w.holidays["id"]]},
    )
    assert link.status_code == 200, link.text
    w.calendar = link.json()["data"]
    other = await _create_employee(client, w.admin, "Other")
    await _create_employment(
        client,
        w.admin,
        employee_id=other["id"],
        legal_entity_id=w.ctx["legal_entity"]["id"],
        joining_date=other_joining,
    )
    w.other_employee = other
    return w


async def _finish(w: World) -> None:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(w.company_id))
        for table in ("pay_run", "attendance_period"):
            await session.execute(
                text(f"DELETE FROM {table} WHERE company_id = CAST(:c AS uuid)"),
                {"c": str(w.company_id)},
            )
        await session.commit()
    await _cleanup_workforce_calendar(company_id=w.company_id)
    await _teardown(company_id=w.company_id)
    await _cleanup(company_id=w.company_id, user_id=w.user_id)
    from tests.integration.modules.attendance.test_attendance_security import (
        _cleanup_scoped_users,
    )

    await _cleanup_scoped_users()


def _holiday(w: World, day: str, name: str = "Founders Day", **extra: Any) -> dict[str, Any]:
    return {
        "change_type": "HOLIDAY_CREATE",
        "holiday_calendar_id": w.holidays["id"],
        "body": {"date": day, "name": name, **extra},
    }


async def _preview(client, w: World, change: dict[str, Any], headers=None, **window) -> Any:
    return await client.post(
        PREVIEW, headers=headers or w.admin, json={"change": change, **(window or WINDOW)}
    )


async def _preview_ok(client, w: World, change: dict[str, Any], **window) -> dict[str, Any]:
    response = await _preview(client, w, change, **window)
    assert response.status_code == 200, response.text
    return dict(response.json()["data"])


async def _confirm(client, w: World, change, digest, *, ack=False, headers=None, **window) -> Any:
    return await client.post(
        CONFIRM,
        headers=headers or w.admin,
        json={
            "change": change,
            "impact_digest": digest,
            "acknowledge_protected_impact": ack,
            **(window or WINDOW),
        },
    )


# ---------------------------------------------------------------------------
# Preview: read-only, correct classification
# ---------------------------------------------------------------------------


async def test_holiday_preview_compares_current_and_proposed_and_writes_nothing(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client)
    try:
        before = await _state(w.company_id)
        data = await _preview_ok(client, w, _holiday(w, "2026-09-09"))
        assert await _state(w.company_id) == before  # no rows, no audit, nothing recalculated

        assert data["changed_date_count"] == 1
        assert data["affected_employee_count"] == 2
        assert data["population"] == {
            "employees_in_scope": 2,
            "employees_analysed": 2,
            "groups_analysed": 1,
            "complete": True,
        }
        (row,) = data["rows"]
        assert row["date"] == "2026-09-09"
        assert row["previous"]["day_type"] == "WORKING"
        assert row["proposed"]["day_type"] == "HOLIDAY"
        assert row["proposed"]["label"] == "Founders Day"
        assert row["affected_employee_count"] == 2
        assert len(data["impact_digest"]) == 64
        assert data["requires_acknowledgement"] is False
        assert {s["employee_code"] for s in data["employee_samples"]}
    finally:
        await _finish(w)


async def test_holiday_on_weekly_off_stays_weekly_off_with_a_warning(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client)
    try:
        data = await _preview_ok(client, w, _holiday(w, "2026-09-06"))  # a Sunday
        (row,) = data["rows"]
        assert row["previous"]["day_type"] == "WEEKLY_OFF"
        assert row["proposed"]["day_type"] == "WEEKLY_OFF"  # PD-CAL-2: no substitute day
        assert row["proposed"]["label"] == "Founders Day"
        assert "HOLIDAY_ON_WEEKLY_OFF" in {x["code"] for x in data["warnings"]}
    finally:
        await _finish(w)


async def test_optional_holiday_stays_working_and_is_labelled(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client)
    try:
        data = await _preview_ok(client, w, _holiday(w, "2026-09-09", holiday_type="OPTIONAL"))
        (row,) = data["rows"]
        assert row["previous"]["day_type"] == "WORKING"
        assert row["proposed"]["day_type"] == "WORKING"
        assert row["proposed"]["label"] == "Optional: Founders Day"
        assert "OPTIONAL_RESTRICTED_WORKING" in {x["code"] for x in data["warnings"]}

        # PD-CAL-1: the work-calendar flag is the only sanctioned override.
        flag = await _preview_ok(
            client,
            w,
            {
                "change_type": "WORK_CALENDAR_UPDATE",
                "work_calendar_id": w.calendar["id"],
                "expected_version": w.calendar["version"],
                "patch": {"restricted_holidays_are_off_by_default": True},
            },
        )
        assert flag["changed_date_count"] == 0  # no restricted/optional holiday exists yet
    finally:
        await _finish(w)


async def test_weekly_off_rule_change_and_half_day_warning(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client)
    try:
        pattern_id = w.calendar["weekly_off_pattern_id"]
        pattern = (
            await client.get(f"/v1/weekly-off-patterns/{pattern_id}", headers=w.admin)
        ).json()["data"]

        def change(saturday_fraction: str) -> dict[str, Any]:
            return {
                "change_type": "WEEKLY_OFF_PATTERN_UPDATE",
                "pattern_id": pattern_id,
                "expected_version": pattern["version"],
                "patch": {
                    "rules": [
                        {"weekday": 5, "off_fraction": saturday_fraction},
                        {"weekday": 6, "off_fraction": "1.00"},
                    ]
                },
            }

        full = await _preview_ok(client, w, change("1.00"))
        assert [r["date"] for r in full["rows"]] == [
            "2026-09-05",
            "2026-09-12",
            "2026-09-19",
            "2026-09-26",
        ]
        assert {r["proposed"]["day_type"] for r in full["rows"]} == {"WEEKLY_OFF"}
        assert "HALF_DAY_WEEKLY_OFF" not in {x["code"] for x in full["warnings"]}

        half = await _preview_ok(client, w, change("0.50"))
        assert {r["proposed"]["weekly_off_fraction"] for r in half["rows"]} == {"0.50"}
        assert "HALF_DAY_WEEKLY_OFF" in {x["code"] for x in half["warnings"]}
    finally:
        await _finish(w)


async def test_employee_specific_assignment_is_not_affected_by_company_pattern_change(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client)
    try:
        calendar_b = await _employee_calendar_b(client, w.admin)
        await _assign(
            client,
            w.admin,
            policy_kind="WORK_CALENDAR",
            policy_id=calendar_b["id"],
            scope_type="EMPLOYEE",
            scope_id=w.employee_id,
            effective_from="2026-09-01",
        )
        pattern_id = w.calendar["weekly_off_pattern_id"]
        pattern = (
            await client.get(f"/v1/weekly-off-patterns/{pattern_id}", headers=w.admin)
        ).json()["data"]
        data = await _preview_ok(
            client,
            w,
            {
                "change_type": "WEEKLY_OFF_PATTERN_UPDATE",
                "pattern_id": pattern_id,
                "expected_version": pattern["version"],
                "patch": {"rules": [{"weekday": 3, "off_fraction": "1.00"}]},  # Thursdays off
            },
        )
        # Only "Other" uses calendar A; the employee with their own calendar B is untouched.
        assert data["affected_employee_count"] == 1
        assert data["population"]["groups_analysed"] == 2
        assert data["employee_samples"][0]["employee_code"] == w.other_employee["employee_code"]
    finally:
        await _finish(w)


async def test_assignment_effective_date_boundary(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client)
    try:
        calendar_b = await _employee_calendar_b(client, w.admin)
        current = (await client.get("/v1/policy-assignments", headers=w.admin)).json()["data"]
        company_row = next(
            a
            for a in current
            if a["scope_type"] == "COMPANY" and a["policy_kind"] == "WORK_CALENDAR"
        )
        change = {
            "change_type": "ASSIGNMENT_CREATE",
            "expected_version": company_row["version"],
            "body": {
                "policy_kind": "WORK_CALENDAR",
                "policy_id": calendar_b["id"],
                "scope_type": "COMPANY",
                "effective_from": "2026-09-15",
            },
        }
        data = await _preview_ok(
            client, w, change, window_from="2026-09-10", window_to="2026-09-22"
        )
        dates = {r["date"]: r for r in data["rows"]}
        # Calendar B: Saturday off, Founders Day Wed 9 Sep, shutdown Mon 14 Sep - all before the
        # 15th except the Saturday swap. Nothing changes before the effective date.
        assert set(dates) == {"2026-09-19", "2026-09-20"}
        assert dates["2026-09-19"]["previous"]["day_type"] == "WORKING"
        assert dates["2026-09-19"]["proposed"]["day_type"] == "WEEKLY_OFF"
        assert dates["2026-09-20"]["previous"]["day_type"] == "WEEKLY_OFF"
        assert dates["2026-09-20"]["proposed"]["day_type"] == "WORKING"

        # Without the current assignment's version the change is invalid, not guessed.
        no_version = {k: v for k, v in change.items() if k != "expected_version"}
        bad = await _preview(
            client, w, no_version, window_from="2026-09-10", window_to="2026-09-22"
        )
        assert bad.status_code == 422
    finally:
        await _finish(w)


async def test_exception_preview(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    w = await _world(client)
    try:
        data = await _preview_ok(
            client,
            w,
            {
                "change_type": "EXCEPTION_CREATE",
                "work_calendar_id": w.calendar["id"],
                "body": {
                    "exception_date": "2026-09-13",
                    "exception_type": "SPECIAL_WORKING",
                    "name": "Stock take",
                },
            },
        )
        (row,) = data["rows"]
        assert row["previous"]["day_type"] == "WEEKLY_OFF"
        assert row["proposed"]["day_type"] == "SPECIAL_WORKING"
    finally:
        await _finish(w)


# ---------------------------------------------------------------------------
# Employment, incomplete configuration, population limits
# ---------------------------------------------------------------------------


async def test_dates_outside_employment_are_excluded(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client, other_joining="2026-09-20")
    try:
        data = await _preview_ok(client, w, _holiday(w, "2026-09-09"))
        assert data["affected_employee_count"] == 1  # "Other" joins after the holiday
        assert data["rows"][0]["affected_employee_count"] == 1
        assert data["excluded_not_employed_employee_dates"] == 1
    finally:
        await _finish(w)


async def test_unresolvable_calendar_is_reported_not_guessed(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client)
    try:
        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(w.company_id))
            await session.execute(
                text("DELETE FROM policy_assignment WHERE company_id = CAST(:c AS uuid)"),
                {"c": str(w.company_id)},
            )
            await session.commit()
        data = await _preview_ok(client, w, _holiday(w, "2026-09-09"))
        assert data["rows"] == []
        assert data["incomplete_configuration"] == {"employees": 2, "dates": 30}
        assert "INCOMPLETE_CONFIGURATION" in {x["code"] for x in data["warnings"]}
    finally:
        await _finish(w)


async def test_population_cap_is_reported_as_incomplete(
    client: AsyncClient, seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hrms.modules.organisation.calendar_impact as impact

    w = await _world(client)
    try:
        for i in range(3):
            extra = await _create_employee(client, w.admin, f"Extra{i}")
            await _create_employment(
                client,
                w.admin,
                employee_id=extra["id"],
                legal_entity_id=w.ctx["legal_entity"]["id"],
            )
        monkeypatch.setattr(impact, "MAX_PREVIEW_EMPLOYEES", 3)
        data = await _preview_ok(client, w, _holiday(w, "2026-09-09"))
        assert data["population"]["complete"] is False
        assert data["population"]["employees_analysed"] == 3
        assert data["affected_employee_count"] == 3  # a lower bound, flagged below
        assert "POPULATION_INCOMPLETE" in {x["code"] for x in data["warnings"]}
    finally:
        await _finish(w)


async def test_query_count_does_not_grow_with_employee_count(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client)
    statements: list[str] = []

    def count(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        statements.append(statement)

    try:
        await _preview_ok(client, w, _holiday(w, "2026-09-09"))  # warm
        engine = get_engine().sync_engine
        event.listen(engine, "before_cursor_execute", count)
        try:
            await _preview_ok(client, w, _holiday(w, "2026-09-09"))
            small = len(statements)
            for i in range(3):
                extra = await _create_employee(client, w.admin, f"Bulk{i}")
                await _create_employment(
                    client,
                    w.admin,
                    employee_id=extra["id"],
                    legal_entity_id=w.ctx["legal_entity"]["id"],
                )
            statements.clear()
            data = await _preview_ok(client, w, _holiday(w, "2026-09-09"))
            large = len(statements)
        finally:
            event.remove(engine, "before_cursor_execute", count)
        assert data["affected_employee_count"] == 5
        assert large <= small + 2, (small, large)
    finally:
        await _finish(w)


# ---------------------------------------------------------------------------
# Leave, attendance and payroll protection
# ---------------------------------------------------------------------------


async def _leave_for(client, w: World, day: str, status: str | None = None) -> str:
    response = await _submit(
        client,
        w.admin,
        employee_id=w.employee_id,
        leave_type_id=w.ctx["leave_type"]["id"],
        start_date=day,
        end_date=day,
        reason="private reason",
    )
    assert response.status_code == 201, response.text
    application_id = str(response.json()["data"]["id"])
    if status:
        await _set_leave_status(application_id, status)
    return application_id


async def test_leave_impact_is_reported_and_leave_records_stay_untouched(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client)
    try:
        approved = await _leave_for(client, w, "2026-09-09")  # Wed, approved
        pending = await _leave_for(client, w, "2026-09-10", "SUBMITTED")
        await _leave_for(client, w, "2026-09-11", "CANCELLED")
        await _leave_for(client, w, "2026-09-14", "REJECTED")  # not part of the change anyway

        changes = [
            _holiday(w, "2026-09-09", name="A"),
            _holiday(w, "2026-09-10", name="B"),
            _holiday(w, "2026-09-11", name="C"),
        ]
        # Make three separate holidays via one calendar update path: preview each date at once by
        # confirming the first two, then previewing the third.
        data = await _preview_ok(client, w, changes[0])
        assert data["leave_impact"]["approved_day_records"] == 1
        assert data["leave_impact"]["pending_day_records"] == 0
        assert data["requires_acknowledgement"] is True
        item = data["leave_impact"]["items"][0]
        assert item["application_id"] == approved and item["status"] == "APPROVED"
        assert item["proposed_day_type"] == "HOLIDAY"
        assert "LEAVE_NOT_RECALCULATED" in {x["code"] for x in data["warnings"]}
        assert "private reason" not in str(data)

        pending_data = await _preview_ok(client, w, changes[1])
        assert pending_data["leave_impact"]["pending_day_records"] == 1
        assert pending_data["leave_impact"]["items"][0]["application_id"] == pending

        cancelled = await _preview_ok(client, w, changes[2])
        assert cancelled["leave_impact"]["approved_day_records"] == 0
        assert cancelled["leave_impact"]["pending_day_records"] == 0
        assert cancelled["requires_acknowledgement"] is False
    finally:
        await _finish(w)


async def test_protected_attendance_and_payroll_are_reported_and_not_modified(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    from hrms.modules.attendance.models import AttendancePeriod
    from hrms.modules.payroll.models import PayRun

    w = await _world(client)
    try:
        now = datetime.now(UTC)
        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(w.company_id))
            period = AttendancePeriod(
                id=uuid4(),
                company_id=w.company_id,
                legal_entity_id=UUID(w.ctx["legal_entity"]["id"]),
                period_start=date(2026, 9, 1),
                period_end=date(2026, 9, 30),
                status="CLOSED",
                opened_at=now,
                created_at=now,
                updated_at=now,
            )
            session.add(period)
            await session.flush()
            session.add(
                PayRun(
                    id=uuid4(),
                    company_id=w.company_id,
                    legal_entity_id=UUID(w.ctx["legal_entity"]["id"]),
                    period_month=date(2026, 9, 1),
                    period_start=date(2026, 9, 1),
                    period_end=date(2026, 9, 30),
                    days_in_month=30,
                    status="FINALISED",
                    pay_date=date(2026, 10, 1),
                    attendance_period_id=period.id,
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.commit()

        before = await _state(w.company_id)
        change = _holiday(w, "2026-09-09")
        data = await _preview_ok(client, w, change)
        kinds = {(p["kind"], p["status"]) for p in data["protected_periods"]}
        assert kinds == {("ATTENDANCE_PERIOD", "CLOSED"), ("PAY_RUN", "FINALISED")}
        assert all(p["changed_dates_in_period"] == 1 for p in data["protected_periods"])
        assert data["requires_acknowledgement"] is True
        assert "PROTECTED_PERIODS" in {x["code"] for x in data["warnings"]}

        # Unacknowledged confirmation is refused; acknowledged one applies the config only.
        refused = await _confirm(client, w, change, data["impact_digest"])
        assert refused.status_code == 422
        assert refused.json()["error"]["details"][0]["code"] == (
            "CALENDAR_IMPACT_ACKNOWLEDGEMENT_REQUIRED"
        )
        assert await _state(w.company_id) == before
        ok = await _confirm(client, w, change, data["impact_digest"], ack=True)
        assert ok.status_code == 201, ok.text
        after = await _state(w.company_id)
        for key in ("attendance_period_hash", "pay_run_hash", "attendance_day", "leave_ledger"):
            assert after[key] == before[key], key
    finally:
        await _finish(w)


async def _row_hashes(company_id: UUID) -> dict[str, tuple[int, str]]:
    """(row count, md5 of every column of every row) for each history table a calendar change
    must never rewrite - stronger than the count-only `_state`."""
    out: dict[str, tuple[int, str]] = {}
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        for table in (
            "leave_application",
            "leave_application_day",
            "leave_ledger",
            "attendance_day",
            "attendance_period",
            "pay_run",
        ):
            row = (
                await session.execute(
                    text(
                        f"SELECT count(*), coalesce(md5(string_agg(t::text, '|' "
                        f"ORDER BY t.id::text)), '') FROM {table} t "
                        f"WHERE company_id = CAST(:c AS uuid)"
                    ),
                    {"c": str(company_id)},
                )
            ).one()
            out[table] = (int(row[0]), str(row[1]))
    return out


async def test_confirmed_change_leaves_leave_locked_attendance_and_payroll_untouched(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    from hrms.modules.attendance.models import AttendancePeriod
    from hrms.modules.payroll.models import PayRun

    w = await _world(client)
    try:
        leave_id = await _leave_for(client, w, "2026-09-09")  # approved, Wednesday
        now = datetime.now(UTC)
        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(w.company_id))
            period = AttendancePeriod(
                id=uuid4(),
                company_id=w.company_id,
                legal_entity_id=UUID(w.ctx["legal_entity"]["id"]),
                period_start=date(2026, 9, 1),
                period_end=date(2026, 9, 30),
                status="CLOSED",
                opened_at=now,
                created_at=now,
                updated_at=now,
            )
            session.add(period)
            await session.flush()
            session.add(
                PayRun(
                    id=uuid4(),
                    company_id=w.company_id,
                    legal_entity_id=UUID(w.ctx["legal_entity"]["id"]),
                    period_month=date(2026, 9, 1),
                    period_start=date(2026, 9, 1),
                    period_end=date(2026, 9, 30),
                    days_in_month=30,
                    status="FINALISED",
                    pay_date=date(2026, 10, 1),
                    attendance_period_id=period.id,
                    created_at=now,
                    updated_at=now,
                )
            )
            # Approving the leave already calculated that day; lock it into the closed period.
            locked = await session.execute(
                text(
                    "UPDATE attendance_day SET is_locked = true, locked_period_id = :p "
                    "WHERE company_id = CAST(:c AS uuid) AND employee_id = CAST(:e AS uuid) "
                    "AND attendance_date = :d"
                ),
                {
                    "c": str(w.company_id),
                    "e": str(w.employee_id),
                    "d": date(2026, 9, 9),
                    "p": period.id,
                },
            )
            assert locked.rowcount == 1
            await session.commit()

        before = await _row_hashes(w.company_id)
        assert before["leave_application_day"][0] == 1
        assert before["attendance_day"][0] == 1 and before["pay_run"][0] == 1

        change = _holiday(w, "2026-09-09")  # the same date as the leave and the locked day
        data = await _preview_ok(client, w, change)
        assert data["leave_impact"]["approved_day_records"] == 1
        assert {p["kind"] for p in data["protected_periods"]} == {"ATTENDANCE_PERIOD", "PAY_RUN"}
        assert await _row_hashes(w.company_id) == before  # preview wrote nothing

        ok = await _confirm(client, w, change, data["impact_digest"], ack=True)
        assert ok.status_code == 201, ok.text
        # The new configuration is live...
        listed = await client.get(
            f"/v1/holiday-calendars/{w.holidays['id']}/holidays", headers=w.admin
        )
        assert [h["date"] for h in listed.json()["data"]] == ["2026-09-09"]
        # ...and every historical record is byte-identical.
        assert await _row_hashes(w.company_id) == before
        assert leave_id  # the approved application still exists
    finally:
        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(w.company_id))
            await session.execute(
                text("DELETE FROM attendance_day WHERE company_id = CAST(:c AS uuid)"),
                {"c": str(w.company_id)},
            )
            await session.commit()
        await _finish(w)


# ---------------------------------------------------------------------------
# Confirmation: stale previews, repeats, concurrency, audit, rollback
# ---------------------------------------------------------------------------


async def test_confirm_applies_once_audits_once_and_repeats_are_refused(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client)
    try:
        change = _holiday(w, "2026-09-09")
        data = await _preview_ok(client, w, change)
        assert await _audit_count(w.company_id, "WORK_CALENDAR_CHANGE_CONFIRMED") == 0  # preview

        ok = await _confirm(client, w, change, data["impact_digest"])
        assert ok.status_code == 201, ok.text
        body = ok.json()["data"]
        assert body["impact_digest"] == data["impact_digest"]
        assert body["affected_employee_count"] == 2
        assert await _audit_count(w.company_id, "WORK_CALENDAR_CHANGE_CONFIRMED") == 1
        assert await _audit_count(w.company_id, "HOLIDAY_CREATED") == 1

        listed = await client.get(
            f"/v1/holiday-calendars/{w.holidays['id']}/holidays", headers=w.admin
        )
        assert [h["date"] for h in listed.json()["data"]] == ["2026-09-09"]

        again = await _confirm(client, w, change, data["impact_digest"])
        assert again.status_code in (409, 422), again.text
        assert await _audit_count(w.company_id, "WORK_CALENDAR_CHANGE_CONFIRMED") == 1
        listed = await client.get(
            f"/v1/holiday-calendars/{w.holidays['id']}/holidays", headers=w.admin
        )
        assert len(listed.json()["data"]) == 1
    finally:
        await _finish(w)


async def test_stale_preview_is_rejected_and_a_forged_digest_is_not_accepted(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client)
    try:
        change = _holiday(w, "2026-09-09")
        data = await _preview_ok(client, w, change)
        forged = await _confirm(client, w, change, hashlib.sha256(b"x").hexdigest())
        assert forged.status_code == 409
        assert forged.json()["error"]["code"] == "CALENDAR_PREVIEW_STALE"

        # The world changes after the preview: approved leave now sits on the date.
        await _leave_for(client, w, "2026-09-09")
        before = await _state(w.company_id)
        stale = await _confirm(client, w, change, data["impact_digest"], ack=True)
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "CALENDAR_PREVIEW_STALE"
        assert await _state(w.company_id) == before  # nothing applied, nothing audited

        # Re-previewing shows the new leave impact and can then be confirmed.
        fresh = await _preview_ok(client, w, change)
        assert fresh["leave_impact"]["approved_day_records"] == 1
        no_ack = await _confirm(client, w, change, fresh["impact_digest"])
        assert no_ack.status_code == 422
        approved_hash = (await _state(w.company_id))["leave_application_day_hash"]
        ok = await _confirm(client, w, change, fresh["impact_digest"], ack=True)
        assert ok.status_code == 201, ok.text
        # Approved leave-day snapshots are byte-identical after confirmation.
        assert (await _state(w.company_id))["leave_application_day_hash"] == approved_hash
    finally:
        await _finish(w)


async def test_stale_entity_version_is_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client)
    try:
        holiday = (
            await client.post(
                f"/v1/holiday-calendars/{w.holidays['id']}/holidays",
                headers=w.admin,
                json={"date": "2026-09-09", "name": "Founders"},
            )
        ).json()["data"]
        change = {
            "change_type": "HOLIDAY_UPDATE",
            "holiday_id": holiday["id"],
            "expected_version": holiday["version"],
            "patch": {"is_active": False},
        }
        data = await _preview_ok(client, w, change)
        assert data["rows"][0]["previous"]["day_type"] == "HOLIDAY"
        assert data["rows"][0]["proposed"]["day_type"] == "WORKING"

        changed = await client.patch(
            f"/v1/holidays/{holiday['id']}",
            headers={**w.admin, "If-Match": str(holiday["version"])},
            json={"name": "Renamed"},
        )
        assert changed.status_code == 200, changed.text
        again = await _preview(client, w, change)
        assert again.status_code == 409, again.text
        confirm = await _confirm(client, w, change, data["impact_digest"])
        assert confirm.status_code == 409
    finally:
        await _finish(w)


async def test_concurrent_confirmations_apply_exactly_once(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client)
    try:
        change = _holiday(w, "2026-09-09")
        data = await _preview_ok(client, w, change)
        results = await asyncio.gather(
            *(_confirm(client, w, change, data["impact_digest"]) for _ in range(4))
        )
        codes = sorted(r.status_code for r in results)
        assert codes.count(201) == 1, [r.text for r in results]
        assert all(c in (201, 409, 422) for c in codes)
        listed = await client.get(
            f"/v1/holiday-calendars/{w.holidays['id']}/holidays", headers=w.admin
        )
        assert len(listed.json()["data"]) == 1
        assert await _audit_count(w.company_id, "WORK_CALENDAR_CHANGE_CONFIRMED") == 1
    finally:
        await _finish(w)


async def test_failure_after_apply_rolls_back_the_whole_change(
    client: AsyncClient, seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hrms.core.audit.service import AuditService

    w = await _world(client)
    try:
        change = _holiday(w, "2026-09-09")
        data = await _preview_ok(client, w, change)
        original = AuditService.record

        async def failing(self, session, **kwargs):  # noqa: ANN001, ANN003
            if kwargs.get("action") == "WORK_CALENDAR_CHANGE_CONFIRMED":
                raise RuntimeError("simulated failure after the change was applied")
            return await original(self, session, **kwargs)

        monkeypatch.setattr(AuditService, "record", failing)
        failed = await _confirm(client, w, change, data["impact_digest"])
        assert failed.status_code == 500
        monkeypatch.undo()

        listed = await client.get(
            f"/v1/holiday-calendars/{w.holidays['id']}/holidays", headers=w.admin
        )
        assert listed.json()["data"] == []  # the holiday insert rolled back with the audit
        assert await _audit_count(w.company_id, "HOLIDAY_CREATED") == 0
        # The same preview is still valid afterwards.
        retry = await _confirm(client, w, change, data["impact_digest"])
        assert retry.status_code == 201, retry.text
    finally:
        await _finish(w)


# ---------------------------------------------------------------------------
# Validation, tenancy and authorisation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "window",
    [
        {"window_from": "2026-09-10", "window_to": "2026-09-09"},
        {"window_from": "2026-01-01", "window_to": "2027-01-02"},  # 367 days
    ],
)
async def test_invalid_and_oversized_windows_are_rejected(
    client: AsyncClient, seeded_plan_catalogue: None, window: dict[str, str]
) -> None:
    w = await _world(client)
    try:
        response = await _preview(client, w, _holiday(w, "2026-09-09"), **window)
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "CALENDAR_PREVIEW_INVALID"
        # A full-year window is the allowed maximum.
        ok = await _preview(
            client, w, _holiday(w, "2026-09-09"), window_from="2026-01-01", window_to="2026-12-31"
        )
        assert ok.status_code == 200, ok.text
    finally:
        await _finish(w)


async def test_malformed_changes_are_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client)
    try:
        unknown = await _preview(client, w, {"change_type": "DROP_TABLES"})
        assert unknown.status_code == 422
        extra = await _preview(client, w, {**_holiday(w, "2026-09-09"), "company_id": str(uuid4())})
        assert extra.status_code == 422  # unknown fields (e.g. a client-supplied company) refused
        leave_kind = await _preview(
            client,
            w,
            {
                "change_type": "ASSIGNMENT_CREATE",
                "body": {
                    "policy_kind": "LEAVE_POLICY",
                    "policy_id": str(uuid4()),
                    "scope_type": "COMPANY",
                    "effective_from": "2026-10-01",
                },
            },
        )
        assert leave_kind.status_code == 422
    finally:
        await _finish(w)


async def test_other_tenants_records_are_not_visible_or_usable(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    a = await _world(client)
    b = await _world(client)
    try:
        foreign = _holiday(b, "2026-09-09")  # holiday calendar id belongs to tenant B
        response = await client.post(PREVIEW, headers=a.admin, json={"change": foreign, **WINDOW})
        assert response.status_code == 404, response.text
        before = await _state(b.company_id)
        confirm = await client.post(
            CONFIRM,
            headers=a.admin,
            json={"change": foreign, "impact_digest": "0" * 64, **WINDOW},
        )
        assert confirm.status_code == 404
        assert await _state(b.company_id) == before
    finally:
        await _finish(a)
        await _finish(b)


async def test_only_calendar_managers_can_preview_or_confirm(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client)
    try:
        change = _holiday(w, "2026-09-09")
        employee = UUID(w.employee_id)
        for role, allowed in (
            ("EMPLOYEE", False),
            ("REPORTING_MANAGER", False),
            ("HR_ADMIN", True),
        ):
            headers = await _user_with_default_role(w.company_id, role, employee)
            preview = await client.post(PREVIEW, headers=headers, json={"change": change, **WINDOW})
            assert (preview.status_code == 200) is allowed, (role, preview.status_code)
            if not allowed:
                assert preview.status_code == 403
                confirm = await client.post(
                    CONFIRM,
                    headers=headers,
                    json={"change": change, "impact_digest": "0" * 64, **WINDOW},
                )
                assert confirm.status_code == 403
        # Company admin (registered user) can; HR admin can apply too.
        data = await _preview_ok(client, w, change)
        hr = await _user_with_default_role(w.company_id, "HR_ADMIN", employee)
        ok = await _confirm(client, w, change, data["impact_digest"], headers=hr)
        assert ok.status_code == 201, ok.text
    finally:
        await _finish(w)
