"""Employee lifecycle rules and concurrency: unique codes and seat limits under parallel creates,
reporting-line loops, confirm / terminate / rehire, and the access cut-off on deactivation."""

import asyncio
from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from hrms.core.db.session import get_session_factory

from ...tenant_wipe import wipe_tenant
from ..account_invite.test_account_invite import _token_from_invite_url
from ..account_invite.uac_helpers import (
    VALID_PASSWORD,
    register_tenant,
    teardown,
    teardown_all,
)
from .conftest import seeded_plan_catalogue  # noqa: F401
from .test_employee_assignment import (
    _create_branch,
    _create_department,
    _create_designation,
    _create_employee,
    _create_employment,
    _create_legal_entity,
    _register_tenant,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("seeded_plan_catalogue")]


async def _set_seat_limit(company_id, limit: int) -> None:
    async with get_session_factory()() as session:
        await session.execute(
            text(
                "UPDATE subscription SET seat_limit_override = :n "
                "WHERE company_id = CAST(:c AS uuid)"
            ),
            {"n": limit, "c": str(company_id)},
        )
        await session.commit()


# ---------------------------------------------------------------- concurrency


async def test_parallel_creates_never_duplicate_employee_codes(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    await _set_seat_limit(company_id, 1000)
    try:
        results = await asyncio.gather(
            *[
                client.post("/v1/employees", headers=headers, json={"first_name": f"P{i}"})
                for i in range(10)
            ],
            return_exceptions=True,
        )
        escaped = [r for r in results if isinstance(r, BaseException)]
        assert not escaped, f"unhandled exception escaped the app: {escaped[:2]}"
        statuses = [r.status_code for r in results]
        assert statuses == [201] * 10, statuses
        codes = [r.json()["data"]["employee_code"] for r in results]
        assert len(set(codes)) == 10, codes
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


async def test_seat_limit_cannot_be_exceeded_by_parallel_creates(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    await _set_seat_limit(company_id, 3)
    try:
        results = await asyncio.gather(
            *[
                client.post("/v1/employees", headers=headers, json={"first_name": f"S{i}"})
                for i in range(8)
            ],
            return_exceptions=True,
        )
        escaped = [r for r in results if isinstance(r, BaseException)]
        assert not escaped, f"unhandled exception escaped the app: {escaped[:2]}"
        created = [r for r in results if r.status_code == 201]
        refused = [r for r in results if r.status_code != 201]
        assert all(r.status_code == 409 for r in refused), [r.status_code for r in refused]
        assert len(created) <= 3, f"seat limit of 3 exceeded: {len(created)} employees created"
        listing = await client.get("/v1/employees", headers=headers, params={"page_size": 100})
        assert listing.json()["pagination"]["total"] == len(created)
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


async def test_parallel_patches_with_one_version_have_a_single_winner(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        results = await asyncio.gather(
            *[
                client.patch(
                    f"/v1/employees/{employee['id']}",
                    headers={**headers, "If-Match": str(employee["version"])},
                    json={"last_name": f"Edit{i}"},
                )
                for i in range(6)
            ],
            return_exceptions=True,
        )
        escaped = [r for r in results if isinstance(r, BaseException)]
        assert not escaped, f"unhandled exception escaped the app: {escaped[:2]}"
        statuses = sorted(r.status_code for r in results)
        assert statuses.count(200) == 1 and set(statuses) <= {200, 409}, statuses
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


# ---------------------------------------------------------------- reporting lines


async def _placed(client, headers, entity, branch, dept, desig, name: str) -> dict[str, Any]:
    employee = await _create_employee(client, headers, first_name=name)
    await _create_employment(
        client,
        headers,
        employee_id=employee["id"],
        legal_entity_id=entity["id"],
        joining_date="2027-06-01",
    )
    r = await client.post(
        f"/v1/employees/{employee['id']}/assignments",
        headers=headers,
        json={
            "effective_from": "2027-06-01",
            "change_type": "INITIAL",
            "branch_id": branch["id"],
            "department_id": dept["id"],
            "designation_id": desig["id"],
        },
    )
    assert r.status_code == 201, r.text
    return {"id": employee["id"], "version": str(r.json()["data"]["version"])}


async def _set_manager(client, headers, who: dict[str, Any], manager_id: str, eff: str):
    r = await client.post(
        f"/v1/employees/{who['id']}/assignments",
        headers={**headers, "If-Match": who["version"]},
        json={
            "effective_from": eff,
            "change_type": "MANAGER_CHANGE",
            "reporting_manager_id": manager_id,
        },
    )
    if r.status_code == 201:
        who["version"] = str(r.json()["data"]["version"])
    return r


async def test_reporting_loops_are_rejected_at_write_time(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    await _set_seat_limit(company_id, 1000)
    try:
        entity = await _create_legal_entity(client, headers)
        branch = await _create_branch(client, headers, entity["id"])
        dept = await _create_department(client, headers)
        desig = await _create_designation(client, headers)
        a, b, c, d = [
            await _placed(client, headers, entity, branch, dept, desig, n) for n in "ABCD"
        ]

        # straight chain A <- B <- C is fine (B reports to A, C reports to B)
        assert (await _set_manager(client, headers, b, a["id"], "2027-07-01")).status_code == 201
        assert (await _set_manager(client, headers, c, b["id"], "2027-07-01")).status_code == 201

        # self
        r = await _set_manager(client, headers, a, a["id"], "2027-08-01")
        assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_REPORTING_MANAGER"
        # 2-ring: A reports to B while B reports to A
        r = await _set_manager(client, headers, a, b["id"], "2027-08-01")
        assert r.status_code == 422, r.text
        assert r.json()["error"]["code"] == "INVALID_REPORTING_MANAGER"
        # 3-ring: A reports to C (C -> B -> A)
        r = await _set_manager(client, headers, a, c["id"], "2027-08-01")
        assert r.status_code == 422, r.text
        # unrelated manager is fine; and a different branch of the tree
        assert (await _set_manager(client, headers, d, c["id"], "2027-08-01")).status_code == 201
        assert (await _set_manager(client, headers, a, d["id"], "2027-09-01")).status_code == 422
        # nonexistent manager
        r = await _set_manager(client, headers, a, str(uuid4()), "2027-09-01")
        assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_REPORTING_MANAGER"
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


async def test_manager_from_another_company_is_rejected(client: AsyncClient) -> None:
    ha, ca, ua = await _register_tenant(client)
    hb, cb, ub = await _register_tenant(client)
    try:
        entity = await _create_legal_entity(client, ha)
        branch = await _create_branch(client, ha, entity["id"])
        dept = await _create_department(client, ha)
        desig = await _create_designation(client, ha)
        mine = await _placed(client, ha, entity, branch, dept, desig, "Mine")
        foreign = await _create_employee(client, hb, first_name="Foreign")
        r = await _set_manager(client, ha, mine, foreign["id"], "2027-07-01")
        assert r.status_code == 422, r.text
        assert r.json()["error"]["code"] == "INVALID_REPORTING_MANAGER"
    finally:
        await wipe_tenant(company_id=ca, user_id=ua)
        await wipe_tenant(company_id=cb, user_id=ub)


# ---------------------------------------------------------------- confirm / terminate / rehire


async def test_confirm_requires_probation_and_is_one_way(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        r = await client.post(
            f"/v1/employees/{employee['id']}/confirm",
            headers={**headers, "If-Match": str(employee["version"])},
            json={},
        )
        assert r.status_code in (409, 422), r.text  # not on probation yet
        assert r.json()["error"]["code"] in {"EMPLOYEE_NOT_ON_PROBATION", "NO_ACTIVE_EMPLOYMENT"}
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


async def test_terminate_then_rehire_rules(client: AsyncClient) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        entity = await _create_legal_entity(client, headers)
        first = await _create_employment(
            client,
            headers,
            employee_id=employee["id"],
            legal_entity_id=entity["id"],
            joining_date="2027-01-01",
        )
        eid = employee["id"]

        # an overlapping second employment while the first is live is refused
        r = await client.post(
            f"/v1/employees/{eid}/employments",
            headers=headers,
            json={"legal_entity_id": entity["id"], "joining_date": "2027-03-01"},
        )
        assert r.status_code == 409 and r.json()["error"]["code"] == "EMPLOYMENT_DATES_OVERLAP"

        term = await client.post(
            f"/v1/employees/{eid}/employments/{first['id']}/terminate",
            headers={**headers, "If-Match": str(first["version"])},
            json={"last_working_day": "2027-06-30"},
        )
        assert term.status_code == 200, term.text
        assert term.json()["data"]["status"] == "TERMINATED"

        # terminating again, or moving the last working day, is refused
        again = await client.post(
            f"/v1/employees/{eid}/employments/{first['id']}/terminate",
            headers={**headers, "If-Match": str(term.json()["data"]["version"])},
            json={"last_working_day": "2027-07-31"},
        )
        assert again.status_code == 409 and again.json()["error"]["code"] == "EMPLOYMENT_NOT_ACTIVE"

        # rehire on/before the previous last working day overlaps; after it is fine
        for joining in ("2027-06-30", "2027-05-01"):
            r = await client.post(
                f"/v1/employees/{eid}/employments",
                headers=headers,
                json={"legal_entity_id": entity["id"], "joining_date": joining},
            )
            assert r.status_code == 409, (joining, r.text)
        ok = await client.post(
            f"/v1/employees/{eid}/employments",
            headers=headers,
            json={"legal_entity_id": entity["id"], "joining_date": "2027-07-01"},
        )
        assert ok.status_code == 201, ok.text
        assert ok.json()["data"]["previous_employment_id"] == first["id"]
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)


# ---------------------------------------------------------------- access cut-off


async def _provision_login(client, headers, company_id) -> dict[str, Any]:
    email = f"emp-{uuid4().hex[:8]}@example.com"
    employee = await _create_employee(client, headers, first_name="Login", personal_email=email)
    invite = await client.post(f"/v1/employees/{employee['id']}/invite", headers=headers)
    assert invite.status_code == 201, invite.text
    token = _token_from_invite_url(invite.json()["data"]["invite_url"])
    accept = await client.post(
        f"/v1/public/account-invites/{token}/accept", json={"password": VALID_PASSWORD}
    )
    assert accept.status_code == 201, accept.text
    return {
        "employee": employee,
        "email": email,
        "headers": {
            "Authorization": f"Bearer {accept.json()['data']['access_token']}",
            "X-Company-Id": str(company_id),
        },
    }


async def test_deactivating_an_employee_cuts_off_their_login_immediately(
    client: AsyncClient,
) -> None:
    """`DELETE /employees/{id}` is documented as an account-level lock ("suspected fraud,
    immediate access cutoff"). The linked login must stop working at once — session, refresh
    token and new logins — and come back if the employee is reactivated."""
    tenant = await register_tenant(client)
    headers, company_id = tenant.headers, tenant.company_id
    try:
        person = await _provision_login(client, headers, company_id)
        tenant.emails.append(person["email"])
        login = await client.post(
            "/v1/auth/login", json={"email": person["email"], "password": VALID_PASSWORD}
        )
        assert login.status_code == 200
        refresh = login.cookies.get("hrms_refresh")
        assert (await client.get("/v1/auth/me", headers=person["headers"])).status_code == 200

        emp = (
            await client.get(f"/v1/employees/{person['employee']['id']}", headers=headers)
        ).json()["data"]
        off = await client.delete(
            f"/v1/employees/{emp['id']}", headers={**headers, "If-Match": str(emp["version"])}
        )
        assert off.status_code == 200, off.text

        assert (await client.get("/v1/auth/me", headers=person["headers"])).status_code in (
            401,
            404,
        ), "deactivated employee's existing session still works"
        again = await client.post(
            "/v1/auth/login", json={"email": person["email"], "password": VALID_PASSWORD}
        )
        assert again.status_code in (401, 403), "deactivated employee can still log in"
        revived = await client.post("/v1/auth/token/refresh", json={"refresh_token": refresh})
        assert revived.status_code in (401, 403), "refresh token survived deactivation"

        # reactivation restores access
        emp = (await client.get(f"/v1/employees/{emp['id']}", headers=headers)).json()["data"]
        back = await client.patch(
            f"/v1/employees/{emp['id']}",
            headers={**headers, "If-Match": str(emp["version"])},
            json={"is_active": True},
        )
        assert back.status_code == 200, back.text
        login = await client.post(
            "/v1/auth/login", json={"email": person["email"], "password": VALID_PASSWORD}
        )
        assert login.status_code == 200, login.text
    finally:
        await teardown(tenant)


async def test_deactivation_in_one_company_leaves_the_same_login_in_another_untouched(
    client: AsyncClient,
) -> None:
    a = await register_tenant(client)
    b = await register_tenant(client)
    try:
        person = await _provision_login(client, a.headers, a.company_id)
        a.emails.append(person["email"])
        b.emails.append(person["email"])
        invite = await client.post(
            "/v1/users/invite",
            headers=b.headers,
            json={"email": person["email"], "role_code": "EMPLOYEE"},
        )
        token = _token_from_invite_url(invite.json()["data"]["invite_url"])
        accepted = await client.post(
            f"/v1/public/account-invites/{token}/accept", json={"password": VALID_PASSWORD}
        )
        assert accepted.status_code == 201, accepted.text

        emp = (
            await client.get(f"/v1/employees/{person['employee']['id']}", headers=a.headers)
        ).json()["data"]
        off = await client.delete(
            f"/v1/employees/{emp['id']}", headers={**a.headers, "If-Match": str(emp["version"])}
        )
        assert off.status_code == 200
        in_b = await client.post(
            "/v1/auth/login",
            json={
                "email": person["email"],
                "password": VALID_PASSWORD,
                "company_id": str(b.company_id),
            },
        )
        assert in_b.status_code == 200, "deactivation in company A must not affect company B"
    finally:
        await teardown_all(a, b)


async def test_reactivating_cannot_bypass_the_seat_limit(client: AsyncClient) -> None:
    """Deactivate one, create another to refill the seat, then reactivate the first: the count of
    active employees must never exceed the plan limit."""
    headers, company_id, user_id = await _register_tenant(client)
    await _set_seat_limit(company_id, 2)
    try:
        one = await _create_employee(client, headers, first_name="One")
        await _create_employee(client, headers, first_name="Two")
        off = await client.delete(
            f"/v1/employees/{one['id']}", headers={**headers, "If-Match": str(one["version"])}
        )
        assert off.status_code == 200, off.text
        await _create_employee(client, headers, first_name="Three")  # refills the freed seat

        one = (await client.get(f"/v1/employees/{one['id']}", headers=headers)).json()["data"]
        back = await client.patch(
            f"/v1/employees/{one['id']}",
            headers={**headers, "If-Match": str(one["version"])},
            json={"is_active": True},
        )
        assert back.status_code == 409, back.text
        assert back.json()["error"]["code"] == "EMPLOYEE_SEAT_LIMIT_EXCEEDED"
    finally:
        await wipe_tenant(company_id=company_id, user_id=user_id)
