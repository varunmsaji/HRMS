"""B12 regression - DEF-B11-06: `POST /v1/employees/{id}/confirm` after the employment ended.

Terminating an employment never moves `Employee.status` (the exit lifecycle is the future Exit
module), so a leaver is still `PROBATION` and the old endpoint confirmed them (PROBATION -> ACTIVE,
audited). The employment record is now consulted: confirmation needs a live employment.
"""

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.b12_support import audit_count, fingerprint
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

pytestmark = pytest.mark.asyncio


async def _employment_rows(company_id: UUID, employee_id: str) -> list[tuple[str, str | None]]:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        rows = await session.execute(
            text(
                "SELECT status, last_working_day::text FROM employment "
                "WHERE company_id=:c AND employee_id=:e ORDER BY joining_date"
            ),
            {"c": str(company_id), "e": employee_id},
        )
        return [(r[0], r[1]) for r in rows]


def _confirm(client: AsyncClient, headers: dict[str, str], employee_id: str, version: int):  # type: ignore[no-untyped-def]
    return client.post(
        f"/v1/employees/{employee_id}/confirm",
        headers={**headers, "If-Match": str(version)},
        json={},
    )


async def _probation_employee(client: AsyncClient, headers: dict[str, str]):  # type: ignore[no-untyped-def]
    employee = await _create_employee(client, headers)
    legal_entity = await _create_legal_entity(client, headers)
    employment = await _create_employment(
        client, headers, employee_id=employee["id"], legal_entity_id=legal_entity["id"]
    )
    return employee, legal_entity, employment


async def test_confirm_refused_after_termination_and_changes_nothing(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, _le, employment = await _probation_employee(client, headers)
        terminate = await client.post(
            f"/v1/employees/{employee['id']}/employments/{employment['id']}/terminate",
            headers={**headers, "If-Match": str(employment["version"])},
            json={"last_working_day": "2027-09-30"},
        )
        assert terminate.status_code == 200, terminate.text
        leaver = await _get_employee(client, headers, employee["id"])
        assert leaver["status"] == "PROBATION"  # the exit module is out of scope: still PROBATION

        before = await fingerprint(company_id)
        rows_before = await _employment_rows(company_id, employee["id"])
        denied = await _confirm(client, headers, employee["id"], leaver["version"])
        assert denied.status_code == 409, denied.text
        assert denied.json()["error"]["code"] == "EMPLOYMENT_NOT_ACTIVE"

        after = await _get_employee(client, headers, employee["id"])
        assert after["status"] == "PROBATION" and after["version"] == leaver["version"]
        assert await _employment_rows(company_id, employee["id"]) == rows_before
        assert await audit_count(company_id, "EMPLOYEE_CONFIRMED") == 0  # no misleading audit
        assert await fingerprint(company_id) == before
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_confirm_still_works_for_eligible_and_rehired_employees(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        # eligible: PROBATION with a live employment
        employee, _le, _emp = await _probation_employee(client, headers)
        current = await _get_employee(client, headers, employee["id"])
        ok = await _confirm(client, headers, employee["id"], current["version"])
        assert ok.status_code == 200, ok.text
        assert ok.json()["data"]["status"] == "ACTIVE"
        assert await audit_count(company_id, "EMPLOYEE_CONFIRMED") == 1

        # rehired: ended employment followed by a new live one -> confirmable again on PROBATION
        second, le2, emp2 = await _probation_employee(client, headers)
        await client.post(
            f"/v1/employees/{second['id']}/employments/{emp2['id']}/terminate",
            headers={**headers, "If-Match": str(emp2["version"])},
            json={"last_working_day": "2027-09-30"},
        )
        await _create_employment(
            client,
            headers,
            employee_id=second["id"],
            legal_entity_id=le2["id"],
            joining_date="2028-02-01",
        )
        rows = await _employment_rows(company_id, second["id"])
        assert [r[0] for r in rows] == ["TERMINATED", "ACTIVE"]
        current = await _get_employee(client, headers, second["id"])
        assert current["status"] == "PROBATION"
        rehired = await _confirm(client, headers, second["id"], current["version"])
        assert rehired.status_code == 200, rehired.text
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_confirm_invalid_states_are_still_refused_without_effect(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        # PRE_JOINING (no employment): not on probation
        pre = await _create_employee(client, headers)
        before = await fingerprint(company_id)
        r = await _confirm(client, headers, pre["id"], pre["version"])
        assert r.status_code == 409 and r.json()["error"]["code"] == "EMPLOYEE_NOT_ON_PROBATION"
        # already ACTIVE: twice
        employee, _le, _emp = await _probation_employee(client, headers)
        cur = await _get_employee(client, headers, employee["id"])
        first = await _confirm(client, headers, employee["id"], cur["version"])
        assert first.status_code == 200
        mid = await fingerprint(company_id)
        again = await _confirm(client, headers, employee["id"], first.json()["data"]["version"])
        assert again.status_code == 409
        assert again.json()["error"]["code"] == "EMPLOYEE_NOT_ON_PROBATION"
        assert await fingerprint(company_id) == mid
        # unknown id
        from uuid import uuid4

        unknown = await _confirm(client, headers, str(uuid4()), 1)
        assert unknown.status_code == 404
        assert before  # PRE_JOINING denial changed nothing either (fingerprint taken before it)
        assert await audit_count(company_id, "EMPLOYEE_CONFIRMED") == 1
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
