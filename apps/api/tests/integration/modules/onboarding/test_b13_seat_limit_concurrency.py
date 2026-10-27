"""B13 Workstream E - the company seat limit under concurrent onboarding activation.

Implemented contract (not changed here): a seat is an `employee` row that is not soft-deleted and
has `is_active = true`; the limit is `subscription.seat_limit_override` if set, else the plan's
`EMPLOYEE_SEATS`. Deactivating (`DELETE /employees/{id}`) frees a seat. Terminating an employment
does NOT clear `is_active`, so a terminated employee keeps their seat until HR deactivates them -
asserted below so a change of that rule is a visible decision, not an accident.

Activation serialises on the onboarding-case row, which does not order two DIFFERENT cases; the
company-wide guard is the `employee-seats:<company>` advisory lock inside
`EmployeeService._check_seat_limit` (reached through `create_employee`). These tests race different
cases for the last seat on independent connections and in separate OS processes and read the
committed row counts straight from the tables.
"""

import asyncio
from datetime import date
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.b12_support import audit_count, run_in_processes, scalar
from tests.integration.modules.employee.test_employment import (
    _create_employment,
    _create_legal_entity,
)

from hrms.core.db.session import get_session_factory

from ..employee.test_employee_assignment import _create_employee
from .test_onboarding_activation import _full_teardown, _verified_case
from .test_onboarding_case import _register_tenant

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("seeded_plan_catalogue")]

SEAT_ERROR = "EMPLOYEE_SEAT_LIMIT_EXCEEDED"


async def _set_limit(company_id: UUID, limit: int) -> None:
    async with get_session_factory()() as session:
        await session.execute(
            text(
                "UPDATE subscription SET seat_limit_override=:n WHERE company_id=CAST(:c AS uuid)"
            ),
            {"n": limit, "c": str(company_id)},
        )
        await session.commit()


async def _seats_used(company_id: UUID) -> int:
    return int(
        await scalar(
            company_id,
            "SELECT count(*) FROM employee WHERE company_id=:cid AND deleted_at IS NULL "
            "AND is_active",
        )
    )


async def _case_status(company_id: UUID, case_id: str) -> str:
    return str(
        await scalar(
            company_id, "SELECT status FROM onboarding_case WHERE id=CAST(:i AS uuid)", i=case_id
        )
    )


async def _activated_audits(company_id: UUID) -> int:
    return await audit_count(company_id, "ONBOARDING_CASE_ACTIVATED")


def _activate_spec(headers: dict[str, str], case_id: str) -> dict[str, Any]:
    return {
        "method": "POST",
        "path": f"/v1/onboarding-cases/{case_id}/activate",
        "headers": headers,
    }


async def _cases(
    client: AsyncClient, headers: dict[str, str], company_id: UUID, n: int
) -> list[str]:
    return [
        (await _verified_case(client, headers, company_id, with_org=True))["id"] for _ in range(n)
    ]


async def test_capacity_available_then_exact_limit_then_refusal_and_retry(
    client: AsyncClient,
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        await _set_limit(company_id, 2)
        first = await _create_employee(client, headers, first_name="Existing")  # 1 of 2 used
        c1, c2 = await _cases(client, headers, company_id, 2)

        ok = await client.post(f"/v1/onboarding-cases/{c1}/activate", headers=headers)
        assert ok.status_code == 200, ok.text  # capacity available: takes the last seat
        assert await _seats_used(company_id) == 2  # exactly at the limit, not over

        before = await _activated_audits(company_id)
        denied = await client.post(f"/v1/onboarding-cases/{c2}/activate", headers=headers)
        assert denied.status_code == 409, denied.text
        assert denied.json()["error"]["code"] == SEAT_ERROR
        assert await _seats_used(company_id) == 2
        assert await _case_status(company_id, c2) == "VERIFIED"  # nothing half-done
        assert await _activated_audits(company_id) == before
        assert (
            int(await scalar(company_id, "SELECT count(*) FROM employee WHERE company_id=:cid"))
            == 2
        )

        # free a seat (deactivate the pre-existing employee) -> the same case now activates
        off = await client.delete(
            f"/v1/employees/{first['id']}", headers={**headers, "If-Match": str(first["version"])}
        )
        assert off.status_code == 200, off.text
        retry = await client.post(f"/v1/onboarding-cases/{c2}/activate", headers=headers)
        assert retry.status_code == 200, retry.text
        assert await _seats_used(company_id) == 2
        assert await _case_status(company_id, c2) == "ACTIVATED"
    finally:
        await _full_teardown(company_id=company_id, user_id=user_id)


async def test_inactive_frees_a_seat_but_terminated_still_holds_one(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        await _set_limit(company_id, 3)
        inactive = await _create_employee(client, headers, first_name="Inactive")
        leaver = await _create_employee(client, headers, first_name="Leaver")
        await _create_employee(client, headers, first_name="Active")
        assert await _seats_used(company_id) == 3

        off = await client.delete(
            f"/v1/employees/{inactive['id']}",
            headers={**headers, "If-Match": str(inactive["version"])},
        )
        assert off.status_code == 200, off.text
        assert await _seats_used(company_id) == 2  # inactive: seat released

        le = await _create_legal_entity(client, headers)
        employment = await _create_employment(
            client, headers, employee_id=leaver["id"], legal_entity_id=le["id"]
        )
        term = await client.post(
            f"/v1/employees/{leaver['id']}/employments/{employment['id']}/terminate",
            headers={**headers, "If-Match": str(employment["version"])},
            json={"last_working_day": date(2027, 9, 30).isoformat()},
        )
        assert term.status_code == 200, term.text
        assert await _seats_used(company_id) == 2  # terminated but not deactivated: seat kept

        c1, c2 = await _cases(client, headers, company_id, 2)
        assert (
            await client.post(f"/v1/onboarding-cases/{c1}/activate", headers=headers)
        ).status_code == 200
        assert await _seats_used(company_id) == 3
        full = await client.post(f"/v1/onboarding-cases/{c2}/activate", headers=headers)
        assert full.status_code == 409 and full.json()["error"]["code"] == SEAT_ERROR
        assert await _seats_used(company_id) == 3
    finally:
        await _full_teardown(company_id=company_id, user_id=user_id)


async def test_distinct_cases_race_for_the_last_seat_on_independent_connections(
    client: AsyncClient,
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        await _set_limit(company_id, 3)
        await _create_employee(client, headers, first_name="One")
        await _create_employee(client, headers, first_name="Two")  # 1 seat left
        ids = await _cases(client, headers, company_id, 6)

        results = await asyncio.gather(
            *[client.post(f"/v1/onboarding-cases/{i}/activate", headers=headers) for i in ids]
        )
        codes = sorted(r.status_code for r in results)
        assert codes == [200, 409, 409, 409, 409, 409], [r.text for r in results]
        assert all(r.json()["error"]["code"] == SEAT_ERROR for r in results if r.status_code == 409)
        assert await _seats_used(company_id) == 3
        statuses = [await _case_status(company_id, i) for i in ids]
        assert sorted(statuses) == ["ACTIVATED"] + ["VERIFIED"] * 5
        assert await _activated_audits(company_id) == 1
    finally:
        await _full_teardown(company_id=company_id, user_id=user_id)


async def test_distinct_cases_race_for_the_last_seat_in_separate_processes(
    client: AsyncClient,
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        await _set_limit(company_id, 3)
        await _create_employee(client, headers, first_name="One")
        await _create_employee(client, headers, first_name="Two")  # 1 seat left
        ids = await _cases(client, headers, company_id, 4)

        results = await run_in_processes([_activate_spec(headers, i) for i in ids])
        assert sorted(r["status"] for r in results) == [200, 409, 409, 409], results
        assert all(r["body"]["error"]["code"] == SEAT_ERROR for r in results if r["status"] == 409)
        assert await _seats_used(company_id) == 3
        statuses = [await _case_status(company_id, i) for i in ids]
        assert sorted(statuses) == ["ACTIVATED"] + ["VERIFIED"] * 3
        assert await _activated_audits(company_id) == 1

        # two seats free up -> the previously rejected cases can now be activated, never beyond
        listed = (await client.get("/v1/employees", headers=headers)).json()["data"]
        for emp in [e for e in listed if e["first_name"] in ("One", "Two")]:
            current = (await client.get(f"/v1/employees/{emp['id']}", headers=headers)).json()[
                "data"
            ]
            r = await client.delete(
                f"/v1/employees/{emp['id']}",
                headers={**headers, "If-Match": str(current["version"])},
            )
            assert r.status_code == 200, r.text
        pending = [i for i, s in zip(ids, statuses, strict=True) if s == "VERIFIED"]
        again = await run_in_processes([_activate_spec(headers, i) for i in pending])
        assert sorted(r["status"] for r in again) == [200, 200, 409], again
        assert await _seats_used(company_id) == 3
    finally:
        await _full_teardown(company_id=company_id, user_id=user_id)


async def test_activations_and_direct_creates_share_one_seat_budget_across_processes(
    client: AsyncClient,
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        await _set_limit(company_id, 4)
        ids = await _cases(client, headers, company_id, 3)
        specs = [_activate_spec(headers, i) for i in ids] + [
            {
                "method": "POST",
                "path": "/v1/employees",
                "headers": headers,
                "json": {"first_name": f"Direct{n}"},
            }
            for n in range(3)
        ]
        results = await run_in_processes(specs)
        assert sum(1 for r in results if r["status"] in (200, 201)) == 4, results
        assert all(
            r["body"]["error"]["code"] == SEAT_ERROR for r in results if r["status"] == 409
        ), results
        assert await _seats_used(company_id) == 4  # never over the limit
    finally:
        await _full_teardown(company_id=company_id, user_id=user_id)
