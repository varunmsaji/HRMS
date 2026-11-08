"""S1/S2 — the nightly sweep no longer holds a company's worth of row locks in one transaction, and
attendance calculation waits are bounded.

Timings are printed (run with `-s`) so they can be compared with the audit's measurement: before
the change a punch for an employee the sweep had already processed waited the sweep's whole hold
(4.04 s against a 4.0 s hold). Assertions use generous margins so they stay stable on a slow CI box.
"""

import asyncio
import time
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import DBAPIError

from hrms.core.config.settings import get_settings
from hrms.core.db.session import session_scope
from hrms.modules.attendance import tasks as attendance_tasks
from hrms.modules.attendance.service import AttendanceDayService
from hrms.shared.business_time import business_today

from .test_attendance_day import (
    _build_wired_employee,
    _cleanup,
    _cleanup_attendance_day,
    _punch,
    _register_tenant,
)
from .test_attendance_security import _add_reportee_employee

pytestmark = pytest.mark.asyncio


class LockNotAvailableError(Exception):  # the name/sqlstate asyncpg gives lock_timeout
    sqlstate = "55P03"


def _timeout_error() -> DBAPIError:
    orig = Exception("adapter")
    orig.__cause__ = LockNotAvailableError("canceling statement due to lock timeout")
    return DBAPIError("SELECT ... FOR UPDATE", {}, orig)


async def _days(client: AsyncClient, headers: dict, employee_id: str) -> list[dict[str, Any]]:
    response = await client.get(
        "/v1/attendance/days", headers=headers, params={"employee_id": employee_id}
    )
    assert response.status_code == 200, response.text
    return list(response.json()["data"])


async def _two_employees(client: AsyncClient, headers: dict) -> tuple[str, str]:
    wired = await _build_wired_employee(client, headers)
    first = str(wired["employee"]["id"])
    second = await _add_reportee_employee(
        client, headers, wired=wired, first_name="Second", reporting_manager_id=None
    )
    return first, str(second["id"])


async def _hold_row_lock(company_id: UUID, employee_id: str, day, seconds: float, locked: Any):
    """Stands in for the old sweep: calculates the row (taking its `FOR UPDATE` lock) and keeps the
    transaction open for `seconds`."""
    async with session_scope(company_id=str(company_id)) as session:
        await AttendanceDayService(session).calculate(
            company_id, UUID(employee_id), day, actor_user_id=None
        )
        locked.set()
        await asyncio.sleep(seconds)


async def _prepare_locked_day(client: AsyncClient, headers: dict, employee_id: str) -> None:
    await _punch(client, headers, employee_id=employee_id, hour=9, minute=0, direction="IN")


async def test_sweep_does_not_hold_other_employees_locks(
    client: AsyncClient, seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    real = AttendanceDayService.calculate
    sweep: asyncio.Task[int] | None = None
    try:
        first, second = await _two_employees(client, headers)
        second_started = asyncio.Event()
        slow_seconds = 2.5

        async def slow_for_second(self, company, employee, target, **kwargs):  # type: ignore[no-untyped-def]
            result = await real(self, company, employee, target, **kwargs)
            if str(employee) == second and not second_started.is_set():
                second_started.set()
                await asyncio.sleep(slow_seconds)  # a slow employee, mid-transaction
            return result

        monkeypatch.setattr(AttendanceDayService, "calculate", slow_for_second)
        sweep_started = time.perf_counter()
        sweep = asyncio.create_task(attendance_tasks._calculate_company_async(company_id))
        await second_started.wait()
        # The sweep is now inside the slow employee's transaction. The first employee's rows were
        # committed already, so a punch for them must not queue behind it.
        monkeypatch.setattr(AttendanceDayService, "calculate", real)
        # the sweep calculates the oldest trailing date first, so that is the row it is holding;
        # it is inside the trailing window, so the first employee's same-date row was committed
        yesterday = (business_today("Asia/Kolkata") - timedelta(days=2)).isoformat()
        started = time.perf_counter()
        await _punch(
            client, headers, employee_id=first, hour=9, minute=0, direction="IN", day=yesterday
        )
        other_latency = time.perf_counter() - started
        print(f"S1 different-employee punch latency during slow sweep: {other_latency:.3f}s")
        assert other_latency < 1.0, "a punch for an already-processed employee waited on the sweep"

        # The employee being swept is still serialised, but only for the bounded lock wait.
        # Rows exist after the first calculate, so this punch contends with the sweep's lock.
        started = time.perf_counter()
        await _punch(
            client, headers, employee_id=second, hour=9, minute=5, direction="IN", day=yesterday
        )
        same_latency = time.perf_counter() - started
        print(f"S1 same-employee punch latency during slow sweep: {same_latency:.3f}s")
        assert same_latency < slow_seconds, "punch waited out the whole slow transaction"
        timeout_s = get_settings().attendance_punch_calc_lock_timeout_ms / 1000
        assert same_latency > timeout_s * 0.8, "expected contention on the row being swept"

        # A different date of the employee being swept is untouched too (and, with one
        # transaction per employee-date, cannot form a lock cycle with the sweep - an earlier
        # per-employee scope produced a deadlock here).
        next_day = (business_today("Asia/Kolkata") - timedelta(days=1)).isoformat()
        started = time.perf_counter()
        await _punch(
            client, headers, employee_id=second, hour=9, minute=10, direction="IN", day=next_day
        )
        other_date_latency = time.perf_counter() - started
        print(f"S1 same-employee, other-date punch latency: {other_date_latency:.3f}s")
        assert other_date_latency < 0.8

        calculated = await sweep
        print(
            f"S1 sweep wall time with one slow employee: {time.perf_counter() - sweep_started:.2f}s"
        )
        assert calculated == 2 * attendance_tasks.TRAILING_DAYS
    finally:
        monkeypatch.setattr(AttendanceDayService, "calculate", real)
        # If an assertion above failed, the sweep is still writing attendance days. Let it finish
        # before deleting the company, or the cleanup hits a foreign-key error, leaves rows behind,
        # and later tests that count rows fail too.
        if sweep is not None:
            await asyncio.gather(sweep, return_exceptions=True)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_same_employee_punch_waits_for_a_short_lock_then_is_calculated(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = str(wired["employee"]["id"])
        await _prepare_locked_day(client, headers, employee_id)
        day = business_today("UTC").replace(year=2026, month=8, day=10)

        locked = asyncio.Event()
        holder = asyncio.create_task(_hold_row_lock(company_id, employee_id, day, 0.4, locked))
        await locked.wait()
        started = time.perf_counter()
        await _punch(client, headers, employee_id=employee_id, hour=18, minute=0, direction="OUT")
        latency = time.perf_counter() - started
        await holder
        print(f"S1 same-employee punch behind a 0.4s lock: {latency:.3f}s")

        # serialised behind the lock, not dropped: the day reflects both punches
        assert 0.25 < latency < 1.2
        row = (await _days(client, headers, employee_id))[0]
        assert row["worked_minutes"] == 540
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_punch_gives_up_on_a_long_lock_but_is_stored_and_recalculated_later(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = str(wired["employee"]["id"])
        await _prepare_locked_day(client, headers, employee_id)
        day = business_today("UTC").replace(year=2026, month=8, day=10)

        hold = 4.0
        locked = asyncio.Event()
        holder = asyncio.create_task(_hold_row_lock(company_id, employee_id, day, hold, locked))
        await locked.wait()
        started = time.perf_counter()
        punch = await _punch(
            client, headers, employee_id=employee_id, hour=18, minute=0, direction="OUT"
        )
        latency = time.perf_counter() - started
        await holder
        print(f"S2 punch against a {hold}s lock (audit baseline 4.04s): {latency:.3f}s")

        timeout_s = get_settings().attendance_punch_calc_lock_timeout_ms / 1000
        assert latency < hold - 1.0, "the punch should return near the lock timeout, not the hold"
        assert timeout_s * 0.8 < latency < timeout_s + 1.5
        listed = await client.get(
            "/v1/attendance/punches", headers=headers, params={"employee_id": employee_id}
        )
        assert punch["id"] in {p["id"] for p in listed.json()["data"]}, "the punch must be stored"

        # the immediate calculation was skipped; the next calculation (the sweep) picks it up
        recalculated = await client.post(
            "/v1/attendance/days/calculate",
            headers=headers,
            params={"employee_id": employee_id, "date": "2026-08-10"},
        )
        assert recalculated.status_code == 200, recalculated.text
        assert recalculated.json()["data"]["worked_minutes"] == 540
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_calculate_endpoint_returns_a_controlled_503_on_lock_timeout_and_recovers(
    client: AsyncClient, seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = str(wired["employee"]["id"])
        await _prepare_locked_day(client, headers, employee_id)
        day = business_today("UTC").replace(year=2026, month=8, day=10)

        short = get_settings().model_copy(update={"attendance_lock_timeout_ms": 300})
        monkeypatch.setattr("hrms.modules.attendance.service.get_settings", lambda: short)

        locked = asyncio.Event()
        holder = asyncio.create_task(_hold_row_lock(company_id, employee_id, day, 2.0, locked))
        await locked.wait()
        started = time.perf_counter()
        blocked = await client.post(
            "/v1/attendance/days/calculate",
            headers=headers,
            params={"employee_id": employee_id, "date": "2026-08-10"},
        )
        elapsed = time.perf_counter() - started
        await holder
        print(f"S2 calculate endpoint, 300ms lock timeout: {blocked.status_code} in {elapsed:.3f}s")

        assert blocked.status_code == 503, blocked.text
        error = blocked.json()["error"]
        assert error["code"] == "DATABASE_BUSY"
        assert "lock" not in blocked.text.lower() and "postgres" not in blocked.text.lower()
        assert blocked.headers.get("retry-after") == "2"
        assert elapsed < 1.5

        # the connection pool is healthy and the same request succeeds once the lock is gone
        again = await client.post(
            "/v1/attendance/days/calculate",
            headers=headers,
            params={"employee_id": employee_id, "date": "2026-08-10"},
        )
        assert again.status_code == 200, again.text
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_one_employees_failure_does_not_stop_the_company_sweep(
    client: AsyncClient, seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        first, second = await _two_employees(client, headers)
        real = AttendanceDayService.calculate

        async def failing_for_first(self, company, employee, target, **kwargs):  # type: ignore[no-untyped-def]
            if str(employee) == first:
                raise RuntimeError("boom")
            return await real(self, company, employee, target, **kwargs)

        monkeypatch.setattr(AttendanceDayService, "calculate", failing_for_first)
        calculated = await attendance_tasks._calculate_company_async(company_id)
        monkeypatch.setattr(AttendanceDayService, "calculate", real)

        assert calculated == attendance_tasks.TRAILING_DAYS  # only the healthy employee's dates
        assert await _days(client, headers, first) == []
        assert len(await _days(client, headers, second)) == attendance_tasks.TRAILING_DAYS
    finally:
        monkeypatch.setattr(AttendanceDayService, "calculate", real)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_a_timed_out_employee_is_skipped_and_others_commit(
    client: AsyncClient, seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        first, second = await _two_employees(client, headers)
        real = AttendanceDayService.calculate

        async def timing_out_for_first(self, company, employee, target, **kwargs):  # type: ignore[no-untyped-def]
            if str(employee) == first:
                raise _timeout_error()
            return await real(self, company, employee, target, **kwargs)

        monkeypatch.setattr(AttendanceDayService, "calculate", timing_out_for_first)
        counts = await attendance_tasks._calculate_employee_dates(
            company_id,
            UUID(first),
            [business_today("UTC") - timedelta(days=1)],
            actor_user_id=None,
        )
        assert counts == {"calculated": 0, "skipped_locked": 0, "timed_out": 1, "failed": 0}
        calculated = await attendance_tasks._calculate_company_async(company_id)
        monkeypatch.setattr(AttendanceDayService, "calculate", real)
        assert calculated == attendance_tasks.TRAILING_DAYS
        assert len(await _days(client, headers, second)) == attendance_tasks.TRAILING_DAYS
    finally:
        monkeypatch.setattr(AttendanceDayService, "calculate", real)
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_a_failing_company_does_not_affect_another_company(
    client: AsyncClient, seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    a_headers, a_company, a_user = await _register_tenant(client)
    b_headers, b_company, b_user = await _register_tenant(client)
    real = AttendanceDayService.calculate
    try:
        a_employee = str((await _build_wired_employee(client, a_headers))["employee"]["id"])
        b_employee = str((await _build_wired_employee(client, b_headers))["employee"]["id"])

        async def failing_for_company_a(self, company, employee, target, **kwargs):  # type: ignore[no-untyped-def]
            if company == a_company:
                raise _timeout_error()
            return await real(self, company, employee, target, **kwargs)

        monkeypatch.setattr(AttendanceDayService, "calculate", failing_for_company_a)
        results = await asyncio.gather(
            attendance_tasks._calculate_company_async(a_company),
            attendance_tasks._calculate_company_async(b_company),
        )
        monkeypatch.setattr(AttendanceDayService, "calculate", real)

        assert results == [0, attendance_tasks.TRAILING_DAYS]
        assert await _days(client, a_headers, a_employee) == []
        assert len(await _days(client, b_headers, b_employee)) == attendance_tasks.TRAILING_DAYS
    finally:
        monkeypatch.setattr(AttendanceDayService, "calculate", real)
        await _cleanup_attendance_day(company_id=a_company)
        await _cleanup_attendance_day(company_id=b_company)
        await _cleanup(company_id=a_company, user_id=a_user)
        await _cleanup(company_id=b_company, user_id=b_user)


async def test_rerunning_and_overlapping_sweeps_are_idempotent(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        first, second = await _two_employees(client, headers)
        await attendance_tasks._calculate_company_async(company_id)
        before = {e: {d["id"] for d in await _days(client, headers, e)} for e in (first, second)}

        # two overlapping sweeps (duplicate Beat firing) plus a later re-run
        overlapped = await asyncio.gather(
            attendance_tasks._calculate_company_async(company_id),
            attendance_tasks._calculate_company_async(company_id),
        )
        again = await attendance_tasks._calculate_company_async(company_id)

        full = 2 * attendance_tasks.TRAILING_DAYS
        assert overlapped == [full, full] and again == full
        after = {e: {d["id"] for d in await _days(client, headers, e)} for e in (first, second)}
        assert after == before, "a re-run created or replaced attendance_day rows"
        assert all(len(ids) == attendance_tasks.TRAILING_DAYS for ids in after.values())
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
