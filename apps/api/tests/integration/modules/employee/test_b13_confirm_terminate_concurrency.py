"""B13 Workstream D - `confirm` vs `terminate_employment` ordering.

B12 left a window: `confirm_employee` read the employments without a lock, so a confirmation that
ran while a termination was still uncommitted passed its "employment is live" check and then
committed `ACTIVE` over an employment that had just ended. Both transitions now take the
per-employee advisory lock `lock_employee_leave_dates` before reading (it is a Postgres lock, so it
holds across processes), and the loser re-reads the winner's committed state.

The interleavings are forced, not hoped for: one transition is run through the real service in a
test-owned session that stays UNCOMMITTED, the other is fired from a separate OS process
(`tests/integration/b13_mp.py`), and the test proves the second one waits and then decides on the
committed state. Final states and audit-event counts are read from the tables.
"""

import asyncio
import time
from datetime import date
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.b12_support import audit_count, run_in_processes
from tests.integration.modules.employee.test_employee_confirmation import (
    _create_employee,
    _get_employee,
    _teardown,
)
from tests.integration.modules.employee.test_employment import (
    _create_employment,
    _create_legal_entity,
    _register_tenant,
)

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.employee.schemas import EmployeeConfirmInput, EmploymentTerminate
from hrms.modules.employee.service import EmployeeService, EmploymentService

pytestmark = pytest.mark.asyncio

LWD = date(2027, 9, 30)
LEAD = 12.0  # seconds for the child processes to import the app before they are released


async def _probation(
    client: AsyncClient, headers: dict[str, str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    employee = await _create_employee(client, headers)
    legal_entity = await _create_legal_entity(client, headers)
    employment = await _create_employment(
        client, headers, employee_id=employee["id"], legal_entity_id=legal_entity["id"]
    )
    return await _get_employee(client, headers, employee["id"]), employment


async def _state(company_id: UUID, employee_id: str) -> dict[str, Any]:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        row = (
            await session.execute(
                text(
                    "SELECT e.status, "
                    "(SELECT string_agg(m.status, ',' ORDER BY m.joining_date) FROM employment m "
                    " WHERE m.employee_id=e.id) "
                    "FROM employee e WHERE e.id=:e"
                ),
                {"e": employee_id},
            )
        ).one()
        audits = {
            action: int(
                (
                    await session.execute(
                        text(
                            "SELECT count(*) FROM audit_log a WHERE a.company_id=:c "
                            "AND a.action=:a AND a.entity_id IN (SELECT CAST(:e AS uuid) UNION "
                            "SELECT m.id FROM employment m WHERE m.employee_id=CAST(:e AS uuid))"
                        ),
                        {"c": str(company_id), "e": employee_id, "a": action},
                    )
                ).scalar_one()
            )
            for action in ("EMPLOYEE_CONFIRMED", "EMPLOYMENT_TERMINATED")
        }
    return {"employee": row[0], "employments": row[1], **audits}


def _confirm_spec(headers: dict[str, str], employee: dict[str, Any]) -> dict[str, Any]:
    return {
        "method": "POST",
        "path": f"/v1/employees/{employee['id']}/confirm",
        "headers": {**headers, "If-Match": str(employee["version"])},
        "json": {},
    }


def _terminate_spec(
    headers: dict[str, str], employee: dict[str, Any], employment: dict[str, Any]
) -> dict[str, Any]:
    return {
        "method": "POST",
        "path": f"/v1/employees/{employee['id']}/employments/{employment['id']}/terminate",
        "headers": {**headers, "If-Match": str(employment["version"])},
        "json": {"last_working_day": LWD.isoformat()},
    }


async def _hold_until_children_wait(task: "asyncio.Task[Any]") -> float:
    """Sleeps past the release instant of the child processes; they must still be blocked."""
    await asyncio.sleep(LEAD + 2.5)
    assert not task.done(), "the second transition did not wait for the in-flight one"
    return time.monotonic()


async def test_sequential_transitions(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        # confirm, then terminate: both valid, ends ACTIVE + TERMINATED
        employee, employment = await _probation(client, headers)
        c = _confirm_spec(headers, employee)
        r1 = await client.post(c["path"], headers=c["headers"], json={})
        assert r1.status_code == 200, r1.text
        t = _terminate_spec(headers, employee, employment)
        r2 = await client.post(t["path"], headers=t["headers"], json=t["json"])
        assert r2.status_code == 200, r2.text
        assert await _state(company_id, employee["id"]) == {
            "employee": "ACTIVE",
            "employments": "TERMINATED",
            "EMPLOYEE_CONFIRMED": 1,
            "EMPLOYMENT_TERMINATED": 1,
        }

        # terminate, then confirm: confirm refused with the established conflict, nothing written
        employee2, employment2 = await _probation(client, headers)
        t = _terminate_spec(headers, employee2, employment2)
        assert (
            await client.post(t["path"], headers=t["headers"], json=t["json"])
        ).status_code == 200
        c = _confirm_spec(headers, await _get_employee(client, headers, employee2["id"]))
        denied = await client.post(c["path"], headers=c["headers"], json={})
        assert (
            denied.status_code == 409 and denied.json()["error"]["code"] == "EMPLOYMENT_NOT_ACTIVE"
        )
        assert await _state(company_id, employee2["id"]) == {
            "employee": "PROBATION",
            "employments": "TERMINATED",
            "EMPLOYEE_CONFIRMED": 0,
            "EMPLOYMENT_TERMINATED": 1,
        }
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_confirm_waits_for_in_flight_termination_then_is_refused(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Termination has done its work but not committed; confirm (other OS process) must not read
    the still-ACTIVE employment and confirm over it."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, employment = await _probation(client, headers)
        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(company_id))
            await EmploymentService(session).terminate_employment(
                company_id,
                UUID(employee["id"]),
                UUID(employment["id"]),
                EmploymentTerminate(last_working_day=LWD),
                expected_version=employment["version"],
                actor_user_id=user_id,
            )
            child = asyncio.create_task(
                run_in_processes([_confirm_spec(headers, employee)], lead_seconds=LEAD)
            )
            await _hold_until_children_wait(child)
            await session.commit()
            (result,) = await child
        assert result["status"] == 409, result
        assert result["body"]["error"]["code"] == "EMPLOYMENT_NOT_ACTIVE"
        assert await _state(company_id, employee["id"]) == {
            "employee": "PROBATION",
            "employments": "TERMINATED",
            "EMPLOYEE_CONFIRMED": 0,
            "EMPLOYMENT_TERMINATED": 1,
        }
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_termination_waits_for_in_flight_confirmation_then_succeeds(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The mirror order is a valid history (confirmed, then left): terminate waits, then succeeds,
    and both audit events exist exactly once."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, employment = await _probation(client, headers)
        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(company_id))
            await EmployeeService(session).confirm_employee(
                company_id,
                UUID(employee["id"]),
                EmployeeConfirmInput(),
                expected_version=employee["version"],
                actor_user_id=user_id,
            )
            child = asyncio.create_task(
                run_in_processes(
                    [_terminate_spec(headers, employee, employment)], lead_seconds=LEAD
                )
            )
            await _hold_until_children_wait(child)
            await session.commit()
            (result,) = await child
        assert result["status"] == 200, result
        assert await _state(company_id, employee["id"]) == {
            "employee": "ACTIVE",
            "employments": "TERMINATED",
            "EMPLOYEE_CONFIRMED": 1,
            "EMPLOYMENT_TERMINATED": 1,
        }
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_free_running_race_in_two_processes_never_commits_an_invalid_state(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        for _round in range(3):
            employee, employment = await _probation(client, headers)
            confirm, terminate = await run_in_processes(
                [_confirm_spec(headers, employee), _terminate_spec(headers, employee, employment)],
                lead_seconds=LEAD,
            )
            assert terminate["status"] == 200, terminate
            state = await _state(company_id, employee["id"])
            assert state["employments"] == "TERMINATED" and state["EMPLOYMENT_TERMINATED"] == 1
            if confirm["status"] == 200:  # confirm went first: a valid history
                assert state["employee"] == "ACTIVE" and state["EMPLOYEE_CONFIRMED"] == 1
            else:  # terminate went first: confirm refused with the established conflict, no audit
                assert confirm["status"] == 409, confirm
                assert confirm["body"]["error"]["code"] == "EMPLOYMENT_NOT_ACTIVE"
                assert state["employee"] == "PROBATION" and state["EMPLOYEE_CONFIRMED"] == 0
        assert await audit_count(company_id, "EMPLOYMENT_TERMINATED") == 3
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
