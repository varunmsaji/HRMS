"""Phase 8 — the one lock `AttendanceDayService.calculate()` takes (execution gate §17.3,
`ED-8`). Two genuinely concurrent HTTP requests, via `asyncio.gather` against the in-process
ASGI transport (each opens its own `AsyncSession`/transaction, exactly as two real requests
would), proving:

1. Two concurrent *first-ever* calculations for the same employee-date never produce two rows —
   the `SELECT ... FOR UPDATE` closes the ordinary recompute race, and the `IntegrityError`
   savepoint-recovery (§17.3 constraint 3) closes the first-insert race that `FOR UPDATE` alone
   cannot, since it locks nothing on a row that doesn't exist yet.
2. Both requests succeed (no 500s) and the row is left in a fully self-consistent state —
   `calculation_version=2`, not stuck mid-race.
3. A calculation that already has a row (the ordinary interleaved-recompute case) also survives
   two concurrent callers without error or data loss.
"""

import asyncio
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from tests.integration.modules.attendance.test_attendance_day import (
    _build_wired_employee,
    _cleanup_attendance_day,
    _punch,
    _register_tenant,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.attendance.models import AttendanceDay

pytestmark = pytest.mark.asyncio


async def _attendance_day_rows(company_id: UUID, employee_id: UUID) -> list[AttendanceDay]:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        stmt = select(AttendanceDay).where(
            AttendanceDay.company_id == company_id, AttendanceDay.employee_id == employee_id
        )
        return list((await session.execute(stmt)).scalars().all())


async def test_concurrent_first_calculate_produces_exactly_one_row(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        # Deliberately no punches on 2026-08-10 — Phase 8's best-effort immediate calculate
        # (execution gate §16.2) fires on punch insert, so any punched date already has a row by
        # the time an explicit call runs. Racing an unpunched date isolates the *first-ever
        # insert* race (§17.3 constraint 3) from that background trigger.
        responses = await asyncio.gather(
            client.post(
                "/v1/attendance/days/calculate",
                headers=headers,
                params={"employee_id": employee_id, "date": "2026-08-10"},
            ),
            client.post(
                "/v1/attendance/days/calculate",
                headers=headers,
                params={"employee_id": employee_id, "date": "2026-08-10"},
            ),
        )
        for response in responses:
            assert response.status_code == 200, response.text

        rows = await _attendance_day_rows(company_id, UUID(employee_id))
        assert len(rows) == 1, "concurrent first-ever calculate() must not create duplicate rows"
        assert rows[0].calculation_version == 2, (
            "the losing side must self-heal into a real recompute (version 2), not silently no-op"
        )
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_concurrent_recompute_on_existing_row_survives(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, headers)
        employee_id = wired["employee"]["id"]
        await _punch(client, headers, employee_id=employee_id, hour=9, minute=0, direction="IN")
        await _punch(client, headers, employee_id=employee_id, hour=18, minute=0, direction="OUT")

        first = await client.post(
            "/v1/attendance/days/calculate",
            headers=headers,
            params={"employee_id": employee_id, "date": "2026-08-10"},
        )
        assert first.status_code == 200, first.text
        # Phase 8's best-effort immediate calculate (execution gate §16.2) already fired once
        # per punch above, so this is a baseline to diff against, not necessarily version 1.
        baseline_version = first.json()["data"]["calculation_version"]

        responses = await asyncio.gather(
            client.post(
                "/v1/attendance/days/calculate",
                headers=headers,
                params={"employee_id": employee_id, "date": "2026-08-10"},
            ),
            client.post(
                "/v1/attendance/days/calculate",
                headers=headers,
                params={"employee_id": employee_id, "date": "2026-08-10"},
            ),
        )
        for response in responses:
            assert response.status_code == 200, response.text

        rows = await _attendance_day_rows(company_id, UUID(employee_id))
        assert len(rows) == 1
        # `FOR UPDATE` serialises the two recomputes; whichever runs second reads the first's
        # committed `calculation_version` before incrementing, so the row ends exactly two
        # versions past the baseline, not stuck mid-race from a lost update.
        assert rows[0].calculation_version == baseline_version + 2
    finally:
        await _cleanup_attendance_day(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
