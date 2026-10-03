"""Decisions: inactive master data in new assignments, deactivating in-use master data, CTC > 0,
company-currency compensation, and termination ending login access.

Dates are real-calendar relative (joining in 2020) so that closed history rows genuinely lie in the
past, which is what makes "deactivating a record only historical rows still point at" testable."""

from datetime import date, timedelta
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from hrms.core.db.session import get_session_factory, session_scope, set_rls_company_id
from hrms.modules.employee.service import EmploymentService
from hrms.shared.business_time import business_today

from ...tenant_wipe import wipe_tenant
from ..account_invite.uac_helpers import VALID_PASSWORD, register_tenant, teardown_all
from .conftest import seeded_plan_catalogue  # noqa: F401
from .test_employee_assignment import (
    _create_branch,
    _create_department,
    _create_designation,
    _create_employee,
    _create_employment,
    _create_grade,
    _create_legal_entity,
    _create_shift,
    _register_tenant,
    _setup_org_structure,
)
from .test_employee_lifecycle_and_concurrency import _provision_login

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("seeded_plan_catalogue")]

JOINING = "2020-01-01"
LATER = "2021-01-01"


# ----------------------------------------------------------------------------- helpers


async def _deactivate(client: AsyncClient, headers: dict, path: str, entity: dict) -> Any:
    return await client.patch(
        f"/v1/{path}/{entity['id']}",
        headers={**headers, "If-Match": str(entity["version"])},
        json={"is_active": False},
    )


async def _employee_in_org(client, headers, org, **extra) -> tuple[dict, dict]:
    employee = await _create_employee(client, headers)
    await _create_employment(
        client,
        headers,
        employee_id=employee["id"],
        legal_entity_id=org["legal_entity"]["id"],
        joining_date=JOINING,
    )
    body = {
        "effective_from": JOINING,
        "change_type": "INITIAL",
        "branch_id": org["branch"]["id"],
        "department_id": org["department"]["id"],
        "designation_id": org["designation"]["id"],
        **extra,
    }
    r = await client.post(f"/v1/employees/{employee['id']}/assignments", headers=headers, json=body)
    assert r.status_code == 201, r.text
    return employee, r.json()["data"]


# ------------------------------------------------- Decision 1: inactive master in new assignment


@pytest.mark.parametrize("kind", ["branch", "department", "designation", "grade", "shift"])
async def test_new_assignment_rejects_inactive_master_record(
    client: AsyncClient, kind: str
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        org = await _setup_org_structure(client, headers)
        employee = await _create_employee(client, headers)
        await _create_employment(
            client,
            headers,
            employee_id=employee["id"],
            legal_entity_id=org["legal_entity"]["id"],
            joining_date=JOINING,
        )
        spare: dict[str, dict] = {
            "branch": await _create_branch(client, headers, org["legal_entity"]["id"]),
            "department": await _create_department(client, headers),
            "designation": await _create_designation(client, headers),
            "grade": await _create_grade(client, headers, code="SPARE"),
            "shift": await _create_shift(client, headers, code="SPARE"),
        }
        plural = {
            "branch": "branches",
            "department": "departments",
            "designation": "designations",
            "grade": "grades",
            "shift": "shifts",
        }[kind]
        off = await _deactivate(client, headers, plural, spare[kind])
        assert off.status_code == 200, off.text

        body: dict[str, Any] = {
            "effective_from": JOINING,
            "change_type": "INITIAL",
            "branch_id": org["branch"]["id"],
            "department_id": org["department"]["id"],
            "designation_id": org["designation"]["id"],
        }
        body[f"{kind}_id"] = spare[kind]["id"]
        r = await client.post(
            f"/v1/employees/{employee['id']}/assignments", headers=headers, json=body
        )
        assert r.status_code == 422, r.text
        assert r.json()["error"]["details"][0]["code"] == f"INACTIVE_{kind.upper()}"
        assert r.json()["error"]["details"][0]["field"] == f"{kind}_id"
        listing = await client.get(f"/v1/employees/{employee['id']}/assignments", headers=headers)
        assert listing.json()["data"] == [], "a rejected assignment must leave nothing behind"

        # the same request with the record active (or the org's own active one) is accepted
        body[f"{kind}_id"] = (
            org[kind]["id"] if kind in org else {"grade": None, "shift": None}[kind]
        )
        if body[f"{kind}_id"] is None:
            del body[f"{kind}_id"]
        ok = await client.post(
            f"/v1/employees/{employee['id']}/assignments", headers=headers, json=body
        )
        assert ok.status_code == 201, ok.text
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


async def test_effective_dated_change_rejects_inactive_record(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        org = await _setup_org_structure(client, headers)
        employee, first = await _employee_in_org(client, headers, org)
        other = await _create_department(client, headers)
        assert (await _deactivate(client, headers, "departments", other)).status_code == 200
        r = await client.post(
            f"/v1/employees/{employee['id']}/assignments",
            headers={**headers, "If-Match": str(first["version"])},
            json={"effective_from": LATER, "change_type": "TRANSFER", "department_id": other["id"]},
        )
        assert r.status_code == 422, r.text
        assert r.json()["error"]["details"][0]["code"] == "INACTIVE_DEPARTMENT"
        # the failed change did not close the current row
        current = (
            await client.get(f"/v1/employees/{employee['id']}/assignments", headers=headers)
        ).json()["data"]
        assert len(current) == 1 and current[0]["effective_to"] is None
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


# ---------------------------------------------- Decision 2: deactivating in-use master data

_CHANGE = {
    "department": ("departments", "TRANSFER"),
    "designation": ("designations", "PROMOTION"),
    "grade": ("grades", "PROMOTION"),
    "shift": ("shifts", "SHIFT_CHANGE"),
}


@pytest.mark.parametrize("kind", list(_CHANGE))
async def test_in_use_master_record_cannot_be_deactivated_until_reassigned(
    client: AsyncClient, kind: str
) -> None:
    plural, change_type = _CHANGE[kind]
    headers, company_id, user_id = await _register_tenant(client)
    try:
        org = await _setup_org_structure(client, headers)
        used = (
            org[kind]
            if kind in org
            else await _create_shift(client, headers, code="USED")
            if kind == "shift"
            else None
        )
        assert used is not None
        spare = {
            "department": lambda: _create_department(client, headers),
            "designation": lambda: _create_designation(client, headers),
            "grade": lambda: _create_grade(client, headers, code="SPARE"),
            "shift": lambda: _create_shift(client, headers, code="SPARE"),
        }[kind]
        unused = await spare()

        # an unused record deactivates freely
        assert (await _deactivate(client, headers, plural, unused)).status_code == 200

        extra = {f"{kind}_id": used["id"]} if kind in ("grade", "shift") else {}
        employee, first = await _employee_in_org(client, headers, org, **extra)
        if kind in ("department", "designation"):
            assert first[f"{kind}_id"] == used["id"]

        blocked = await _deactivate(client, headers, plural, used)
        assert blocked.status_code == 409, blocked.text
        err = blocked.json()["error"]
        assert err["code"] == "MASTER_DATA_HAS_ACTIVE_EMPLOYEES"
        assert err["details"][0]["context"]["active_employee_count"] == 1
        assert "reassign" in err["message"]
        still = await client.get(f"/v1/{plural}/{used['id']}", headers=headers)
        assert still.json()["data"]["is_active"] is True, "must not silently deactivate"
        # nothing was reassigned automatically
        rows = (
            await client.get(f"/v1/employees/{employee['id']}/assignments", headers=headers)
        ).json()["data"]
        assert len(rows) == 1 and rows[0][f"{kind}_id"] == used["id"]

        # reassign the employee (a *different*, active record) — history keeps pointing at the old
        replacement = await _make_replacement(client, headers, kind)
        moved = await client.post(
            f"/v1/employees/{employee['id']}/assignments",
            headers={**headers, "If-Match": str(first["version"])},
            json={
                "effective_from": LATER,
                "change_type": change_type,
                f"{kind}_id": replacement["id"],
            },
        )
        assert moved.status_code == 201, moved.text
        refreshed = (await client.get(f"/v1/{plural}/{used['id']}", headers=headers)).json()["data"]
        off = await _deactivate(client, headers, plural, refreshed)
        assert off.status_code == 200, off.text

        # historical assignment is still readable and unchanged
        history = (
            await client.get(f"/v1/employees/{employee['id']}/assignments", headers=headers)
        ).json()["data"]
        assert {r[f"{kind}_id"] for r in history} == {used["id"], replacement["id"]}
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


async def test_branch_with_active_employees_cannot_be_deactivated_until_they_move(
    client: AsyncClient,
) -> None:
    """FR-ORG-014's employee half: departments no longer block (this branch has none), but an
    active employee placed directly in the branch does. Nothing is reassigned automatically."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        org = await _setup_org_structure(client, headers)
        solo = await _create_branch(client, headers, org["legal_entity"]["id"], name="Solo")
        employee, first = await _employee_in_org(client, headers, org)
        moved = await client.post(
            f"/v1/employees/{employee['id']}/assignments",
            headers={**headers, "If-Match": str(first["version"])},
            json={"effective_from": LATER, "change_type": "TRANSFER", "branch_id": solo["id"]},
        )
        assert moved.status_code == 201, moved.text

        blocked = await _deactivate(client, headers, "branches", solo)
        assert blocked.status_code == 409, blocked.text
        err = blocked.json()["error"]
        assert err["code"] == "MASTER_DATA_HAS_ACTIVE_EMPLOYEES"
        assert err["details"][0]["context"] == {"kind": "branch", "active_employee_count": 1}
        still = (await client.get(f"/v1/branches/{solo['id']}", headers=headers)).json()["data"]
        assert still["is_active"] is True
        rows = (
            await client.get(f"/v1/employees/{employee['id']}/assignments", headers=headers)
        ).json()["data"]
        assert {r["branch_id"] for r in rows} == {org["branch"]["id"], solo["id"]}

        # an unused branch still deactivates freely
        spare = await _create_branch(client, headers, org["legal_entity"]["id"], name="Spare")
        assert (await _deactivate(client, headers, "branches", spare)).status_code == 200
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


async def _make_replacement(client, headers, kind: str) -> dict:
    if kind == "department":
        return await _create_department(client, headers, name="Replacement Dept")
    if kind == "designation":
        return await _create_designation(client, headers, title="Replacement Desig")
    if kind == "grade":
        return await _create_grade(client, headers, code="NEXT")
    return await _create_shift(client, headers, code="NEXT")


async def test_deactivated_employees_do_not_block_deactivation(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        org = await _setup_org_structure(client, headers)
        employee, _ = await _employee_in_org(client, headers, org)
        emp = (await client.get(f"/v1/employees/{employee['id']}", headers=headers)).json()["data"]
        off = await client.delete(
            f"/v1/employees/{emp['id']}", headers={**headers, "If-Match": str(emp["version"])}
        )
        assert off.status_code == 200
        dept = (
            await client.get(f"/v1/departments/{org['department']['id']}", headers=headers)
        ).json()["data"]
        assert (await _deactivate(client, headers, "departments", dept)).status_code == 200
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


# ------------------------------------------------------- Decisions 3 & 4: CTC and currency


async def _comp_ready_employee(client, headers) -> dict:
    employee = await _create_employee(client, headers)
    entity = await _create_legal_entity(client, headers)
    await _create_employment(
        client,
        headers,
        employee_id=employee["id"],
        legal_entity_id=entity["id"],
        joining_date=JOINING,
    )
    return employee


def _comp(**over: Any) -> dict:
    return {
        "effective_from": JOINING,
        "annual_ctc_minor": 1_200_000_00,
        "currency": "INR",
        "revision_type": "JOINING",
        "revision_reason": "Hire",
        **over,
    }


@pytest.mark.parametrize("ctc", [0, -1, -1_200_000_00])
async def test_ctc_must_be_strictly_positive(client: AsyncClient, ctc: int) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _comp_ready_employee(client, headers)
        r = await client.post(
            f"/v1/employees/{employee['id']}/compensation",
            headers=headers,
            json=_comp(annual_ctc_minor=ctc),
        )
        assert r.status_code == 422, r.text
        listing = await client.get(f"/v1/employees/{employee['id']}/compensation", headers=headers)
        assert listing.json()["data"] == []
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


async def test_positive_ctc_in_company_currency_is_accepted_and_foreign_currency_rejected(
    client: AsyncClient,
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        profile = (await client.get("/v1/companies/current", headers=headers)).json()["data"]
        assert profile["currency"] == "INR"
        employee = await _comp_ready_employee(client, headers)
        url = f"/v1/employees/{employee['id']}/compensation"

        usd = await client.post(url, headers=headers, json=_comp(currency="USD"))
        assert usd.status_code == 422, usd.text
        assert usd.json()["error"]["details"][0]["code"] == "COMPENSATION_CURRENCY_MISMATCH"
        assert (await client.get(url, headers=headers)).json()["data"] == []

        ok = await client.post(url, headers=headers, json=_comp(annual_ctc_minor=1))
        assert ok.status_code == 201, ok.text
        assert ok.json()["data"]["currency"] == "INR"

        # a revision is held to the same rules
        bad = await client.post(
            url,
            headers={**headers, "If-Match": str(ok.json()["data"]["version"])},
            json=_comp(effective_from=LATER, revision_type="HIKE", currency="USD"),
        )
        assert bad.status_code == 422, bad.text
        rows = (await client.get(url, headers=headers)).json()["data"]
        assert len(rows) == 1 and rows[0]["effective_to"] is None, "failed revision closed the row"
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


async def test_database_refuses_a_non_positive_ctc(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _comp_ready_employee(client, headers)
        ok = await client.post(
            f"/v1/employees/{employee['id']}/compensation", headers=headers, json=_comp()
        )
        assert ok.status_code == 201
        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, str(company_id))
            with pytest.raises(Exception, match="employee_compensation_ctc_positive"):
                await session.execute(
                    text("UPDATE employee_compensation SET annual_ctc_minor = 0 WHERE id = :i"),
                    {"i": ok.json()["data"]["id"]},
                )
            await session.rollback()
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


# ----------------------------------------------------------------------------- bulk import


async def test_bulk_import_rejects_bad_ctc_currency_and_inactive_master(
    client: AsyncClient,
) -> None:
    from hrms.modules.employee_import.service import EmployeeImportService

    from ..employee_import.test_employee_import import CSV_HEADER

    headers, company_id, user_id = await _register_tenant(client)
    try:
        org = await _setup_org_structure(client, headers)
        dead_branch = await _create_branch(
            client, headers, org["legal_entity"]["id"], name="Closed Branch"
        )
        assert (await _deactivate(client, headers, "branches", dead_branch)).status_code == 200
        le, br = org["legal_entity"]["name"], org["branch"]["name"]
        dp, ds = org["department"]["name"], org["designation"]["title"]

        def row(name, branch, ctc, cur):
            return (
                f",{name},,Test,1995-06-12,MALE,,,Indian,{name.lower()}@example.com,9876500001,"
                f"{le},{branch},{dp},{ds},,,OFFICE,2020-01-01,{ctc},{cur}"
            )

        csv_rows = [
            row("Good", br, 120000000, "INR"),
            row("ZeroCtc", br, 0, "INR"),
            row("Dollar", br, 120000000, "USD"),
            row("Dead", "Closed Branch", 120000000, "INR"),
        ]
        csv_bytes = (CSV_HEADER + "\n" + "\n".join(csv_rows) + "\n").encode()
        up = await client.post(
            "/v1/employee-imports",
            headers=headers,
            files={"file": ("e.csv", csv_bytes, "text/csv")},
        )
        assert up.status_code == 201, up.text
        batch_id = UUID(up.json()["data"]["id"])
        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(company_id))
            await EmployeeImportService(session).process_batch(company_id, batch_id, user_id)

        result = (await client.get(f"/v1/employee-imports/{batch_id}", headers=headers)).json()[
            "data"
        ]
        assert (result["success_count"], result["error_count"]) == (1, 3), result
        errors = {
            e["row_number"]: e
            for e in (
                await client.get(f"/v1/employee-imports/{batch_id}/errors", headers=headers)
            ).json()["data"]
        }
        assert set(errors) == {3, 4, 5}
        assert "annual_ctc_minor" in errors[3]["error_message"]
        assert errors[4]["error_code"] == "COMPENSATION_CURRENCY_MISMATCH"
        assert errors[5]["error_code"] == "INACTIVE_MASTER_DATA"
        people = (await client.get("/v1/employees", headers=headers)).json()["data"]
        assert {p["first_name"] for p in people} == {"Good"}, "failed rows left partial employees"
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


# ------------------------------------------------------------- Decision 5: termination access


async def _wipe(*tenants) -> None:
    """Login sessions/refresh tokens first (they FK to company), then each tenant's graph, then
    the invited users."""
    async with get_session_factory()() as session:
        for t in tenants:
            await set_rls_company_id(session, str(t.company_id))
            for table in ("refresh_token", "session"):
                await session.execute(
                    text(f'DELETE FROM "{table}" WHERE company_id = CAST(:c AS uuid)'),
                    {"c": str(t.company_id)},
                )
        await session.commit()
    for t in tenants:
        await wipe_tenant(company_id=t.company_id, user_id=t.admin_user_id)
    await teardown_all(*tenants)


async def _company_today(company_id: UUID) -> date:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        tz = (
            await session.execute(
                text("SELECT timezone FROM company WHERE id = :c"), {"c": str(company_id)}
            )
        ).scalar_one()
    return business_today(tz)


async def _sweep(company_id: UUID, as_of: date | None = None) -> int:
    async with session_scope(company_id=str(company_id)) as session:
        return await EmploymentService(session).enforce_elapsed_terminations(
            company_id, as_of=as_of
        )


async def _db_scalar(company_id: UUID, sql: str, **params: Any) -> Any:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        return (await session.execute(text(sql), params)).scalar_one()


async def _membership(company_id: UUID, email: str) -> str:
    return await _db_scalar(
        company_id,
        'SELECT uc.status FROM user_company uc JOIN "user" u ON u.id = uc.user_id '
        "WHERE u.email = :e AND uc.company_id = CAST(:c AS uuid)",
        e=email,
        c=str(company_id),
    )


async def _revocation_audits(company_id: UUID, employee_id: str) -> int:
    return await _db_scalar(
        company_id,
        "SELECT count(*) FROM audit_log WHERE action = 'EMPLOYEE_ACCESS_REVOKED' "
        "AND entity_id = CAST(:e AS uuid)",
        e=employee_id,
    )


async def _staffed_login(client, tenant, *, with_history: bool = True) -> dict:
    """A real invited login, with employment (2020), assignment and compensation history."""
    headers, company_id = tenant.headers, tenant.company_id
    person = await _provision_login(client, headers, company_id)
    tenant.emails.append(person["email"])
    org = await _setup_org_structure(client, headers) if with_history else None
    entity = org["legal_entity"] if org else await _create_legal_entity(client, headers)
    employment = await _create_employment(
        client,
        headers,
        employee_id=person["employee"]["id"],
        legal_entity_id=entity["id"],
        joining_date=JOINING,
    )
    if org:
        a = await client.post(
            f"/v1/employees/{person['employee']['id']}/assignments",
            headers=headers,
            json={
                "effective_from": JOINING,
                "change_type": "INITIAL",
                "branch_id": org["branch"]["id"],
                "department_id": org["department"]["id"],
                "designation_id": org["designation"]["id"],
            },
        )
        assert a.status_code == 201, a.text
        c = await client.post(
            f"/v1/employees/{person['employee']['id']}/compensation",
            headers=headers,
            json=_comp(),
        )
        assert c.status_code == 201, c.text
    person["employment"] = employment
    return person


async def _terminate(client, headers, person, last_working_day: date):
    return await client.post(
        f"/v1/employees/{person['employee']['id']}/employments/{person['employment']['id']}"
        "/terminate",
        headers={**headers, "If-Match": str(person["employment"]["version"])},
        json={"last_working_day": last_working_day.isoformat()},
    )


async def _can_login(client, email: str) -> bool:
    r = await client.post("/v1/auth/login", json={"email": email, "password": VALID_PASSWORD})
    return r.status_code == 200


async def test_immediate_termination_revokes_access_but_keeps_history(
    client: AsyncClient,
) -> None:
    tenant = await register_tenant(client)
    headers, company_id = tenant.headers, tenant.company_id
    try:
        person = await _staffed_login(client, tenant)
        eid, email = person["employee"]["id"], person["email"]
        login = await client.post(
            "/v1/auth/login", json={"email": email, "password": VALID_PASSWORD}
        )
        assert login.status_code == 200
        refresh = login.cookies.get("hrms_refresh")
        assert (await client.get("/v1/auth/me", headers=person["headers"])).status_code == 200

        # A last working day already behind us (company-local) cuts access at once.
        yesterday = (await _company_today(company_id)) - timedelta(days=1)
        r = await _terminate(client, headers, person, yesterday)
        assert r.status_code == 200, r.text

        # access gone: existing session, refresh token, new login, self-service API
        assert (await client.get("/v1/auth/me", headers=person["headers"])).status_code == 401
        assert (
            await client.get(f"/v1/employees/{eid}", headers=person["headers"])
        ).status_code in (
            401,
            403,
        )
        revived = await client.post("/v1/auth/token/refresh", json={"refresh_token": refresh})
        assert revived.status_code in (401, 403)
        assert not await _can_login(client, email)
        assert await _membership(company_id, email) == "INACTIVE"
        assert await _revocation_audits(company_id, eid) == 1

        # HR still sees the whole record
        emp = await client.get(f"/v1/employees/{eid}", headers=headers)
        assert emp.status_code == 200 and emp.json()["data"]["id"] == eid
        assert (
            len(
                (await client.get(f"/v1/employees/{eid}/assignments", headers=headers)).json()[
                    "data"
                ]
            )
            == 1
        )
        assert (
            len(
                (await client.get(f"/v1/employees/{eid}/compensation", headers=headers)).json()[
                    "data"
                ]
            )
            == 1
        )
        employments = (
            await client.get(f"/v1/employees/{eid}/employments", headers=headers)
        ).json()["data"]
        assert employments[0]["status"] == "TERMINATED"
        assert emp.json()["data"]["is_active"] is True, "termination must not deactivate the record"
        # an already-revoked account is not touched again
        assert await _sweep(company_id) == 0
        assert await _revocation_audits(company_id, eid) == 1
    finally:
        await _wipe(tenant)


async def test_future_termination_keeps_access_until_the_boundary_then_sweep_revokes(
    client: AsyncClient,
) -> None:
    tenant = await register_tenant(client)
    headers, company_id = tenant.headers, tenant.company_id
    try:
        person = await _staffed_login(client, tenant, with_history=False)
        eid, email = person["employee"]["id"], person["email"]
        today = await _company_today(company_id)
        lwd = today + timedelta(days=5)
        assert (await _terminate(client, headers, person, lwd)).status_code == 200

        # still employed and able to work: session, login, nothing audited
        assert (await client.get("/v1/auth/me", headers=person["headers"])).status_code == 200
        assert await _can_login(client, email)
        assert await _membership(company_id, email) == "ACTIVE"
        assert await _revocation_audits(company_id, eid) == 0

        # before the boundary, and exactly on the last working day: nothing happens
        assert await _sweep(company_id, as_of=lwd - timedelta(days=1)) == 0
        assert await _sweep(company_id, as_of=lwd) == 0
        assert await _sweep(company_id) == 0  # real "today" is still before the day
        assert await _membership(company_id, email) == "ACTIVE"
        assert (await client.get("/v1/auth/me", headers=person["headers"])).status_code == 200

        # the day after the last working day: access ends
        login = await client.post(
            "/v1/auth/login", json={"email": email, "password": VALID_PASSWORD}
        )
        refresh = login.cookies.get("hrms_refresh")
        assert await _sweep(company_id, as_of=lwd + timedelta(days=1)) == 1
        assert await _membership(company_id, email) == "INACTIVE"
        assert (await client.get("/v1/auth/me", headers=person["headers"])).status_code == 401
        assert (
            await client.post("/v1/auth/token/refresh", json={"refresh_token": refresh})
        ).status_code in (401, 403)
        assert not await _can_login(client, email)
        assert await _revocation_audits(company_id, eid) == 1

        # running it again — or much later — changes nothing and writes nothing
        assert await _sweep(company_id, as_of=lwd + timedelta(days=1)) == 0
        assert await _sweep(company_id, as_of=lwd + timedelta(days=30)) == 0
        assert await _revocation_audits(company_id, eid) == 1
        emp = await client.get(f"/v1/employees/{eid}", headers=headers)
        assert emp.status_code == 200
    finally:
        await _wipe(tenant)


async def test_sweep_only_touches_its_own_company_and_leaves_rehired_staff_alone(
    client: AsyncClient,
) -> None:
    a = await register_tenant(client)
    b = await register_tenant(client)
    try:
        pa = await _staffed_login(client, a, with_history=False)
        pb = await _staffed_login(client, b, with_history=False)
        for tenant, person in ((a, pa), (b, pb)):
            r = await _terminate(client, tenant.headers, person, date(2024, 1, 31))
            # an elapsed date revokes at once; reopen the membership to simulate "not yet swept"
            assert r.status_code == 200, r.text
        async with get_session_factory()() as session:
            await session.execute(text("UPDATE user_company SET status = 'ACTIVE'"))
            await session.commit()

        assert await _sweep(a.company_id) == 1
        assert await _membership(a.company_id, pa["email"]) == "INACTIVE"
        assert await _membership(b.company_id, pb["email"]) == "ACTIVE", "other tenant touched"
        assert await _sweep(b.company_id) == 1

        # a rehired employee (new ACTIVE employment) is never swept
        pc = await _staffed_login(client, a, with_history=False)
        rc = await _terminate(client, a.headers, pc, date(2024, 1, 31))
        assert rc.status_code == 200
        rehire = await client.post(
            f"/v1/employees/{pc['employee']['id']}/employments",
            headers=a.headers,
            json={
                "legal_entity_id": pc["employment"]["legal_entity_id"],
                "joining_date": "2024-06-01",
            },
        )
        assert rehire.status_code == 201, rehire.text
        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(a.company_id))
            await session.execute(
                text(
                    "UPDATE user_company SET status = 'ACTIVE' WHERE user_id = "
                    '(SELECT id FROM "user" WHERE email = :e)'
                ),
                {"e": pc["email"]},
            )
            await session.commit()
        assert await _sweep(a.company_id) == 0
        assert await _membership(a.company_id, pc["email"]) == "ACTIVE"
    finally:
        await _wipe(a, b)


async def test_access_is_kept_through_the_last_working_day_and_ends_the_day_after(
    client: AsyncClient,
) -> None:
    """Last working day == company-local today: the employee still has access all day; the
    sweep revokes from the following company-local day, never earlier."""
    tenant = await register_tenant(client)
    headers, company_id = tenant.headers, tenant.company_id
    try:
        person = await _staffed_login(client, tenant, with_history=False)
        eid, email = person["employee"]["id"], person["email"]
        today = await _company_today(company_id)
        assert (await _terminate(client, headers, person, today)).status_code == 200

        # the last working day itself: still allowed (session, login, membership, no audit)
        assert (await client.get("/v1/auth/me", headers=person["headers"])).status_code == 200
        assert await _can_login(client, email)
        assert await _membership(company_id, email) == "ACTIVE"
        assert await _sweep(company_id) == 0
        assert await _sweep(company_id, as_of=today) == 0
        assert await _revocation_audits(company_id, eid) == 0

        # before the last working day: allowed too
        assert await _sweep(company_id, as_of=today - timedelta(days=1)) == 0

        # the day after: revoked
        assert await _sweep(company_id, as_of=today + timedelta(days=1)) == 1
        assert await _membership(company_id, email) == "INACTIVE"
        assert (await client.get("/v1/auth/me", headers=person["headers"])).status_code == 401
        assert not await _can_login(client, email)
    finally:
        await _wipe(tenant)


# ------------------------------------------------------------------------------ rehire access


async def _role_ids(company_id: UUID, email: str) -> list[str]:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        rows = await session.execute(
            text(
                "SELECT ur.role_id::text FROM user_role ur "
                "JOIN user_company uc ON uc.id = ur.user_company_id "
                'JOIN "user" u ON u.id = uc.user_id '
                "WHERE u.email = :e AND uc.company_id = CAST(:c AS uuid) ORDER BY 1"
            ),
            {"e": email, "c": str(company_id)},
        )
        return [r[0] for r in rows.all()]


async def _restore_audits(company_id: UUID, employee_id: str) -> int:
    return await _db_scalar(
        company_id,
        "SELECT count(*) FROM audit_log WHERE action = 'EMPLOYEE_ACCESS_RESTORED' "
        "AND entity_id = CAST(:e AS uuid)",
        e=employee_id,
    )


async def _rehire(client, headers, person, joining_date: str):
    return await client.post(
        f"/v1/employees/{person['employee']['id']}/employments",
        headers=headers,
        json={
            "legal_entity_id": person["employment"]["legal_entity_id"],
            "joining_date": joining_date,
        },
    )


async def test_rehire_restores_the_same_membership_with_the_same_roles(
    client: AsyncClient,
) -> None:
    from hrms.core.db.repositories.identity import IdentityRepository

    tenant = await register_tenant(client)
    other = await register_tenant(client)
    headers, company_id = tenant.headers, tenant.company_id
    try:
        person = await _staffed_login(client, tenant, with_history=False)
        bystander = await _staffed_login(client, other, with_history=False)
        eid, email = person["employee"]["id"], person["email"]
        roles_before = await _role_ids(company_id, email)
        assert roles_before, "the invited login should carry a role"

        # 1. terminated -> no access
        assert (await _terminate(client, headers, person, date(2024, 1, 31))).status_code == 200
        assert await _membership(company_id, email) == "INACTIVE"
        assert not await _can_login(client, email)

        # 2./3. rehired -> access back, through the one membership row, nothing else changed
        rehire = await _rehire(client, headers, person, "2024-06-01")
        assert rehire.status_code == 201, rehire.text
        assert await _membership(company_id, email) == "ACTIVE"
        assert await _can_login(client, email)
        assert await _restore_audits(company_id, eid) == 1

        # 4. exactly the roles it had, no more
        assert await _role_ids(company_id, email) == roles_before

        # 5. tenant isolation: the other company's login is untouched, and the rehired login
        #    still has no standing in a company it never belonged to
        assert await _membership(other.company_id, bystander["email"]) == "ACTIVE"
        crossing = await client.get(
            "/v1/auth/me",
            headers={**person["headers"], "X-Company-Id": str(other.company_id)},
        )
        assert crossing.status_code in (401, 403, 404)

        # 6. idempotent: restoring again changes nothing and records nothing
        async with session_scope(company_id=str(company_id)) as session:
            user_id = (
                await session.execute(text('SELECT id FROM "user" WHERE email = :e'), {"e": email})
            ).scalar_one()
            assert (
                await IdentityRepository().restore_company_access(
                    session, user_id=user_id, company_id=company_id
                )
                is False
            )
        assert await _restore_audits(company_id, eid) == 1
        assert await _role_ids(company_id, email) == roles_before

        # a second terminate/rehire cycle restores once more, still with the same roles
        employment = rehire.json()["data"]
        again = await client.post(
            f"/v1/employees/{eid}/employments/{employment['id']}/terminate",
            headers={**headers, "If-Match": str(employment["version"])},
            json={"last_working_day": "2024-12-31"},
        )
        assert again.status_code == 200, again.text
        assert await _membership(company_id, email) == "INACTIVE"
        assert (await _rehire(client, headers, person, "2025-02-01")).status_code == 201
        assert await _membership(company_id, email) == "ACTIVE"
        assert await _restore_audits(company_id, eid) == 2
        assert await _role_ids(company_id, email) == roles_before
    finally:
        await _wipe(tenant, other)


async def test_rehire_does_not_unlock_a_deliberately_deactivated_employee(
    client: AsyncClient,
) -> None:
    tenant = await register_tenant(client)
    headers, company_id = tenant.headers, tenant.company_id
    try:
        person = await _staffed_login(client, tenant, with_history=False)
        eid, email = person["employee"]["id"], person["email"]
        assert (await _terminate(client, headers, person, date(2024, 1, 31))).status_code == 200
        emp = (await client.get(f"/v1/employees/{eid}", headers=headers)).json()["data"]
        off = await client.delete(
            f"/v1/employees/{eid}", headers={**headers, "If-Match": str(emp["version"])}
        )
        assert off.status_code == 200, off.text

        assert (await _rehire(client, headers, person, "2024-06-01")).status_code == 201
        assert await _membership(company_id, email) == "INACTIVE"
        assert not await _can_login(client, email)
        assert await _restore_audits(company_id, eid) == 0
    finally:
        await _wipe(tenant)
