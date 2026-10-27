"""DEF-B6-02 - `GET /v1/attendance-periods/{id}/summary` carries one row per employee, so it must
honour the data scope of whoever asks. Previously the route bound the scope to an unused
parameter and returned every employee's row to every `ATTENDANCE.VIEW` holder.

Contract under test (service layer, `AttendancePeriodService.get_summary`):
* `ATTENDANCE.VIEW` is honoured at its granted scope (SELF / REPORTEES / REPORTEE_TREE / BRANCH /
  COMPANY); a caller with no linked employee sees nothing below COMPANY.
* `ATTENDANCE.VIEW_ALL` is a separate permission and is honoured independently: held at COMPANY
  it is company-wide, held at a lower scope it stays at that scope.
* The system HR_ADMIN role reads company-wide (OPEN preview and CLOSED frozen snapshot).
* Other tenants see nothing; the list/detail routes still return period metadata only.
"""

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from hrms.modules.attendance.permissions import ATTENDANCE_VIEW, ATTENDANCE_VIEW_ALL

from ...tenant_wipe import wipe_tenant
from ..account_invite.test_account_invite import (
    _cleanup_extra_user_row,
    _cleanup_extra_user_sessions,
    _extra_user_id,
)
from ..account_invite.uac_helpers import Tenant as UacTenant
from ..account_invite.uac_helpers import onboard
from ..employee.test_employee_data_scope import _setup_branches
from .test_attendance_day import _build_wired_employee, _register_tenant
from .test_attendance_period import _create_period, _first_legal_entity_id, _full_calculate
from .test_attendance_security import (
    _assign_branch,
    _cleanup_scoped_users,
    _create_permission_scoped_user,
)

pytestmark = pytest.mark.asyncio


@dataclass
class World:
    headers: dict[str, str]
    company_id: UUID
    user_id: UUID | None
    ids: dict[str, str]  # M manager, R direct report, G grandchild, S other branch
    period_id: str
    emails: list[str]


async def _hire(
    client: AsyncClient, headers: dict[str, str], wired: dict, name: str, manager_id: str | None
) -> str:
    """Employee employed in the wired legal entity, assigned to the wired branch (API path, so a
    real reporting line exists)."""
    employee = (
        await client.post("/v1/employees", headers=headers, json={"first_name": name})
    ).json()["data"]
    employment = await client.post(
        f"/v1/employees/{employee['id']}/employments",
        headers=headers,
        json={"legal_entity_id": wired["le_id"], "joining_date": "2026-01-01"},
    )
    assert employment.status_code == 201, employment.text
    if manager_id is not None:
        assignment = await client.post(
            f"/v1/employees/{employee['id']}/assignments",
            headers=headers,
            json={
                "effective_from": "2026-01-01",
                "change_type": "INITIAL",
                "branch_id": wired["branch"]["id"],
                "department_id": wired["dept_id"],
                "designation_id": wired["desig_id"],
                "shift_id": wired["shift"]["id"],
                "reporting_manager_id": manager_id,
            },
        )
        assert assignment.status_code == 201, assignment.text
    return str(employee["id"])


async def _world(client: AsyncClient) -> World:
    headers, company_id, user_id = await _register_tenant(client)
    wired = await _build_wired_employee(client, headers)
    wired["le_id"] = await _first_legal_entity_id(client, headers)
    dept = (
        await client.post(
            "/v1/departments",
            headers=headers,
            json={"name": "Ops", "branch_id": wired["branch"]["id"]},
        )
    ).json()["data"]
    desig = (
        await client.post(
            "/v1/designations",
            headers=headers,
            json={"title": "Analyst", "department_id": dept["id"]},
        )
    ).json()["data"]
    wired["dept_id"], wired["desig_id"] = dept["id"], desig["id"]
    m = wired["employee"]["id"]
    r = await _hire(client, headers, wired, "Reportee", m)
    g = await _hire(client, headers, wired, "Grandchild", r)
    s = await _hire(client, headers, wired, "OtherBranch", None)
    (branch_b,) = await _setup_branches(company_id=company_id, count=1)
    await _assign_branch(company_id=company_id, employee_id=UUID(s), branch_id=branch_b)
    for emp in (m, r, g, s):
        await _full_calculate(client, headers, employee_id=emp)
    period = await _create_period(client, headers, legal_entity_id=wired["le_id"])
    return World(headers, company_id, user_id, {"M": m, "R": r, "G": g, "S": s}, period["id"], [])


async def _teardown(w: World) -> None:
    ids = [uid for e in w.emails if (uid := await _extra_user_id(email=e))]
    for uid in ids:
        await _cleanup_extra_user_sessions(user_id=uid)
    await wipe_tenant(company_id=w.company_id, user_id=w.user_id)
    for uid in ids:
        await _cleanup_extra_user_row(user_id=uid)
    await _cleanup_scoped_users()


async def _rows(client: AsyncClient, w: World, headers: dict[str, str]) -> set[str] | int:
    response = await client.get(f"/v1/attendance-periods/{w.period_id}/summary", headers=headers)
    if response.status_code != 200:
        return response.status_code
    return {row["employee_id"] for row in response.json()["data"]}


async def _custom(w: World, perms: list[str], scope: str, caller: str | None) -> dict[str, str]:
    headers, _ = await _create_permission_scoped_user(
        company_id=w.company_id,
        permission_codes=perms,
        data_scope=scope,
        caller_employee_id=UUID(caller) if caller else None,
    )
    return headers


async def test_summary_honours_every_scope_level(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client)
    try:
        i = w.ids
        everyone = set(i.values())
        before = await _rows(client, w, w.headers)
        assert before == everyone  # COMPANY_ADMIN: company-wide

        cases = [
            ("VIEW", [ATTENDANCE_VIEW], "SELF", i["M"], {i["M"]}),
            ("VIEW", [ATTENDANCE_VIEW], "SELF", i["S"], {i["S"]}),
            ("VIEW", [ATTENDANCE_VIEW], "REPORTEES", i["M"], {i["R"]}),
            ("VIEW", [ATTENDANCE_VIEW], "REPORTEE_TREE", i["M"], {i["R"], i["G"]}),
            ("VIEW", [ATTENDANCE_VIEW], "BRANCH", i["M"], {i["M"], i["R"], i["G"]}),
            ("VIEW", [ATTENDANCE_VIEW], "BRANCH", i["S"], {i["S"]}),
            ("VIEW", [ATTENDANCE_VIEW], "COMPANY", i["M"], everyone),
            # no linked employee: every scope below COMPANY resolves to nobody
            ("VIEW", [ATTENDANCE_VIEW], "SELF", None, set()),
            ("VIEW", [ATTENDANCE_VIEW], "REPORTEES", None, set()),
            ("VIEW", [ATTENDANCE_VIEW], "BRANCH", None, set()),
            # VIEW_ALL is independent: company-wide only when granted at COMPANY ...
            ("VIEW_ALL", [ATTENDANCE_VIEW_ALL], "COMPANY", None, everyone),
            ("VIEW_ALL", [ATTENDANCE_VIEW_ALL], "COMPANY", i["M"], everyone),
            # ... and a restricted VIEW_ALL grant stays restricted
            ("VIEW_ALL", [ATTENDANCE_VIEW_ALL], "SELF", i["M"], {i["M"]}),
            ("VIEW_ALL", [ATTENDANCE_VIEW_ALL], "REPORTEES", i["M"], {i["R"]}),
        ]
        for label, perms, scope, caller, expected in cases:
            headers = await _custom(w, perms, scope, caller)
            got = await _rows(client, w, headers)
            who = next((k for k, v in i.items() if v == caller), "no-employee")
            assert got == expected, f"{label}@{scope} caller={who}: {got} != {expected}"

        # Neither permission held -> 403, nothing leaked.
        nothing = await _custom(w, ["EMPLOYEE.VIEW"], "COMPANY", i["M"])
        assert await _rows(client, w, nothing) == 403
        # Read-only: the data did not change.
        assert await _rows(client, w, w.headers) == before
    finally:
        await _teardown(w)


async def test_hr_admin_reads_company_wide_summary_open_and_closed(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client)
    try:
        everyone = set(w.ids.values())
        tenant = UacTenant(
            headers=w.headers, company_id=w.company_id, admin_user_id=w.user_id, emails=w.emails
        )
        hr = await onboard(client, tenant, "HR_ADMIN")
        assert await _rows(client, w, hr.headers) == everyone  # live preview

        finalized = await client.post(
            f"/v1/attendance-periods/{w.period_id}/finalize",
            headers={**w.headers, "If-Match": "1"},
            json={},
        )
        assert finalized.status_code == 200, finalized.text
        frozen = await client.get(
            f"/v1/attendance-periods/{w.period_id}/summary", headers=hr.headers
        )
        assert frozen.status_code == 200
        assert {r["employee_id"] for r in frozen.json()["data"]} == everyone
        assert all(r["frozen"] for r in frozen.json()["data"])

        # CLOSED snapshot is filtered by scope too (frozen path, not only the live preview).
        scoped = await _custom(w, [ATTENDANCE_VIEW], "SELF", w.ids["R"])
        assert await _rows(client, w, scoped) == {w.ids["R"]}
        # HR_ADMIN stays read-only here: finalize/reopen (ATTENDANCE.LOCK/UNLOCK) are not granted.
        for action, body in (("finalize", {}), ("reopen", {"reason": "hr tries to reopen"})):
            denied = await client.post(
                f"/v1/attendance-periods/{w.period_id}/{action}",
                headers={**hr.headers, "If-Match": "2"},
                json=body,
            )
            assert denied.status_code == 403, (action, denied.text)
    finally:
        await _teardown(w)


async def test_cross_tenant_and_unknown_period_return_nothing(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    a = await _world(client)
    b_headers, b_company, b_user = await _register_tenant(client)
    try:
        # B's admin asks for A's period id: not found, no rows.
        foreign = await client.get(
            f"/v1/attendance-periods/{a.period_id}/summary", headers=b_headers
        )
        assert foreign.status_code == 404
        unknown = await client.get(f"/v1/attendance-periods/{uuid4()}/summary", headers=a.headers)
        assert unknown.status_code == 404
        # A forged company header is rejected before any scope logic.
        forged = await client.get(
            f"/v1/attendance-periods/{a.period_id}/summary",
            headers={**b_headers, "X-Company-Id": str(a.company_id)},
        )
        assert forged.status_code in (401, 403, 404)
    finally:
        await wipe_tenant(company_id=b_company, user_id=b_user)
        await _teardown(a)
