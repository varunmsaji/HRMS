"""DEF-B10-01 - `POST /v1/leave-ledger/adjustments` (and the sibling `/encashments`) must apply the
data scope `LEAVE.BALANCE_ADJUST` was granted with to the TARGET employee, before any mutation.

A denied request must be indistinguishable from an unknown employee (404), write no ledger row,
change no balance and leave no idempotency record - for a first attempt and for a replay of the
same key. In-scope targets still work. System roles hold the permission at COMPANY only, so their
behaviour is unchanged.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.test_attendance_security import (
    _assign_branch,
    _cleanup_scoped_users,
    _create_permission_scoped_user,
)
from tests.integration.modules.employee.test_employee_data_scope import _setup_branches
from tests.integration.modules.leave.test_leave_application import (
    _cleanup,
    _create_employee,
    _create_employment,
    _get_balance,
    _give_employee_a_manager,
    _register_tenant,
    _setup_full,
    _teardown,
)
from tests.integration.modules.leave.test_leave_rbac_matrix import _user_with_default_role

from hrms.core.db.session import get_session_factory, set_rls_company_id

pytestmark = pytest.mark.asyncio

ADJUST = "/v1/leave-ledger/adjustments"
ENCASH = "/v1/leave-ledger/encashments"
PERM = "LEAVE.BALANCE_ADJUST"


@dataclass
class World:
    admin: dict[str, str]
    company_id: UUID
    user_id: UUID | None
    leave_type_id: str
    le_id: str
    e: dict[str, str]  # employee ids: T target (no manager), M manager, R M's report, S stranger


async def _state(w: World, employee_id: str) -> dict[str, Any]:
    """Everything a denied request must leave untouched for one employee."""
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(w.company_id))
        ledger = (
            await session.execute(
                text(
                    "SELECT count(*) c, COALESCE(sum(amount), 0)::text s FROM leave_ledger "
                    "WHERE company_id = CAST(:c AS uuid) AND employee_id = CAST(:e AS uuid)"
                ),
                {"c": str(w.company_id), "e": employee_id},
            )
        ).one()
        idem = (
            await session.execute(
                text("SELECT count(*) FROM idempotency_key WHERE company_id = CAST(:c AS uuid)"),
                {"c": str(w.company_id)},
            )
        ).scalar_one()
        audit = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE company_id = CAST(:c AS uuid) "
                    "AND entity_type LIKE 'leave_ledger%'"
                ),
                {"c": str(w.company_id)},
            )
        ).scalar_one()
    return {"entries": ledger.c, "sum": ledger.s, "idempotency_rows": idem, "ledger_audit": audit}


async def _world(client: AsyncClient) -> World:
    admin, company_id, user_id = await _register_tenant(client)
    ctx = await _setup_full(
        client, admin, approval_chain="AUTO", balance="10.00", encashment_allowed=True
    )
    le_id = ctx["legal_entity"]["id"]
    target = ctx["employee"]["id"]
    ids = {"T": target}
    for key, name in (("M", "Manager"), ("R", "Report"), ("S", "Stranger")):
        emp = await _create_employee(client, admin, name)
        await _create_employment(client, admin, employee_id=emp["id"], legal_entity_id=le_id)
        ids[key] = emp["id"]
    await _give_employee_a_manager(
        client, admin, employee_id=ids["R"], manager_employee_id=ids["M"], legal_entity_id=le_id
    )
    return World(admin, company_id, user_id, ctx["leave_type"]["id"], le_id, ids)


def _body(w: World, employee_id: str, amount: str = "1.00") -> dict[str, Any]:
    return {
        "employee_id": employee_id,
        "leave_type_id": w.leave_type_id,
        "amount": amount,
        "effective_date": "2026-09-08",
        "reason": "scope regression",
    }


def _enc_body(w: World, employee_id: str) -> dict[str, Any]:
    return {
        "employee_id": employee_id,
        "leave_type_id": w.leave_type_id,
        "days": "1.00",
        "effective_date": "2026-09-08",
        "reason": "scope regression",
    }


async def _post(client: AsyncClient, path: str, headers: dict[str, str], body: dict, key: str):
    return await client.post(path, headers={**headers, "Idempotency-Key": key}, json=body)


async def _scoped(w: World, scope: str, caller: str | None) -> dict[str, str]:
    headers, _ = await _create_permission_scoped_user(
        company_id=w.company_id,
        permission_codes=[PERM],
        data_scope=scope,
        caller_employee_id=UUID(caller) if caller else None,
    )
    return headers


async def _assert_denied(client, w: World, headers, path: str, body: dict, target: str) -> None:
    """First attempt AND replay of the same key: 404, nothing written, nothing recorded."""
    before = await _state(w, target)
    balance = await _get_balance(client, w.admin, target)
    key = f"deny-{uuid4()}"
    for attempt in ("first", "replay"):
        denied = await _post(client, path, headers, body, key)
        assert denied.status_code == 404, (attempt, path, denied.status_code, denied.text)
    assert await _state(w, target) == before
    assert await _get_balance(client, w.admin, target) == balance


@pytest.mark.parametrize("path", [ADJUST, ENCASH])
async def test_out_of_scope_target_is_refused_for_self_reportees_branch(
    client: AsyncClient, seeded_plan_catalogue: None, path: str
) -> None:
    w = await _world(client)
    try:
        e = w.e
        body_for = (
            (lambda emp: _body(w, emp)) if path == ADJUST else (lambda emp: _enc_body(w, emp))
        )
        # give every candidate target a balance to encash from
        for emp in (e["M"], e["R"], e["S"]):
            seeded = await _post(client, ADJUST, w.admin, _body(w, emp, "5.00"), f"seed-{uuid4()}")
            assert seeded.status_code == 201, seeded.text

        self_caller = await _scoped(w, "SELF", e["S"])
        await _assert_denied(client, w, self_caller, path, body_for(e["T"]), e["T"])
        await _assert_denied(client, w, self_caller, path, body_for(e["M"]), e["M"])

        rep_caller = await _scoped(w, "REPORTEES", e["M"])
        await _assert_denied(client, w, rep_caller, path, body_for(e["T"]), e["T"])
        await _assert_denied(
            client, w, rep_caller, path, body_for(e["M"]), e["M"]
        )  # not own balance
        await _assert_denied(client, w, rep_caller, path, body_for(e["S"]), e["S"])

        tree_caller = await _scoped(w, "REPORTEE_TREE", e["M"])
        await _assert_denied(client, w, tree_caller, path, body_for(e["S"]), e["S"])

        # a caller with no linked employee holds no scope below COMPANY at all
        orphan = await _scoped(w, "SELF", None)
        await _assert_denied(client, w, orphan, path, body_for(e["T"]), e["T"])
        orphan_rep = await _scoped(w, "REPORTEES", None)
        await _assert_denied(client, w, orphan_rep, path, body_for(e["R"]), e["R"])

        # unknown employee id: same answer as out of scope
        unknown = await _post(client, path, self_caller, body_for(str(uuid4())), f"u-{uuid4()}")
        assert unknown.status_code == 404
    finally:
        await _teardown(company_id=w.company_id)
        await _cleanup(company_id=w.company_id, user_id=w.user_id)
        await _cleanup_scoped_users()


@pytest.mark.parametrize("path", [ADJUST, ENCASH])
async def test_in_scope_targets_still_work(
    client: AsyncClient, seeded_plan_catalogue: None, path: str
) -> None:
    w = await _world(client)
    try:
        e = w.e
        body_for = (
            (lambda emp: _body(w, emp)) if path == ADJUST else (lambda emp: _enc_body(w, emp))
        )
        for emp in (e["R"], e["S"]):
            assert (
                await _post(client, ADJUST, w.admin, _body(w, emp, "5.00"), f"s-{uuid4()}")
            ).status_code == 201

        # REPORTEES: the manager's direct report
        rep = await _scoped(w, "REPORTEES", e["M"])
        before = await _state(w, e["R"])
        ok = await _post(client, path, rep, body_for(e["R"]), f"ok-{uuid4()}")
        assert ok.status_code == 201, ok.text
        after = await _state(w, e["R"])
        assert after["entries"] == before["entries"] + 1
        assert after["idempotency_rows"] == before["idempotency_rows"] + 1

        # SELF: the boundary case - exactly the caller's own record (and nobody else's)
        own = await _scoped(w, "SELF", e["S"])
        assert (await _post(client, path, own, body_for(e["S"]), f"o-{uuid4()}")).status_code == 201

        # COMPANY (custom role and the real HR_ADMIN role): any employee of the company
        hr = await _user_with_default_role(w.company_id, "HR_ADMIN", UUID(e["M"]))
        company = await _scoped(w, "COMPANY", None)
        for headers in (hr, company):
            for emp in (e["R"], e["S"], e["T"]):
                response = await _post(client, path, headers, body_for(emp), f"c-{uuid4()}")
                assert response.status_code == 201, (path, emp, response.text)
    finally:
        await _teardown(company_id=w.company_id)
        await _cleanup(company_id=w.company_id, user_id=w.user_id)
        await _cleanup_scoped_users()


async def test_branch_scope_for_adjustments(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    admin, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, admin, approval_chain="AUTO", balance="10.00")
        le_id, lt = ctx["legal_entity"]["id"], ctx["leave_type"]["id"]
        w = World(admin, company_id, user_id, lt, le_id, {})
        people = {}
        for key in ("caller", "colleague", "elsewhere"):
            emp = await _create_employee(client, admin, key.title())
            await _create_employment(client, admin, employee_id=emp["id"], legal_entity_id=le_id)
            people[key] = emp["id"]
        branch_a, branch_b = await _setup_branches(company_id=company_id, count=2)
        await _assign_branch(
            company_id=company_id, employee_id=UUID(people["caller"]), branch_id=branch_a
        )
        await _assign_branch(
            company_id=company_id, employee_id=UUID(people["colleague"]), branch_id=branch_a
        )
        await _assign_branch(
            company_id=company_id, employee_id=UUID(people["elsewhere"]), branch_id=branch_b
        )

        headers = await _scoped(w, "BRANCH", people["caller"])
        await _assert_denied(
            client, w, headers, ADJUST, _body(w, people["elsewhere"]), people["elsewhere"]
        )
        await _assert_denied(
            client, w, headers, ADJUST, _body(w, ctx["employee"]["id"]), ctx["employee"]["id"]
        )
        for target in (people["colleague"], people["caller"]):
            ok = await _post(client, ADJUST, headers, _body(w, target), f"b-{uuid4()}")
            assert ok.status_code == 201, ok.text
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_cross_tenant_target_is_refused(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    a = await _world(client)
    b_admin, b_company, b_user = await _register_tenant(client)
    try:
        # B's company-wide admin names A's employee: 404 and A's books are untouched.
        before = await _state(a, a.e["T"])
        for path, body in ((ADJUST, _body(a, a.e["T"])), (ENCASH, _enc_body(a, a.e["T"]))):
            denied = await _post(client, path, b_admin, body, f"x-{uuid4()}")
            assert denied.status_code == 404, (path, denied.text)
        assert await _state(a, a.e["T"]) == before
    finally:
        await _cleanup(company_id=b_company, user_id=b_user)
        await _teardown(company_id=a.company_id)
        await _cleanup(company_id=a.company_id, user_id=a.user_id)
        await _cleanup_scoped_users()


async def test_replay_of_an_authorised_adjustment_is_still_idempotent(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client)
    try:
        key = f"idem-{uuid4()}"
        before = await _state(w, w.e["R"])
        first = await _post(client, ADJUST, w.admin, _body(w, w.e["R"], "2.00"), key)
        second = await _post(client, ADJUST, w.admin, _body(w, w.e["R"], "2.00"), key)
        assert first.status_code == 201 and second.status_code == 201
        assert first.json()["data"]["id"] == second.json()["data"]["id"]
        after = await _state(w, w.e["R"])
        assert after["entries"] == before["entries"] + 1
        assert Decimal(after["sum"]) == Decimal(before["sum"]) + Decimal("2.00")
    finally:
        await _teardown(company_id=w.company_id)
        await _cleanup(company_id=w.company_id, user_id=w.user_id)
