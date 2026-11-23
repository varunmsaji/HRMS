"""A caller limited to their assigned branches (an HR administrator / branch manager without
`COMPANY_ADMIN`) may only place or move an employee into one of those branches.

Covers `EmployeeAssignmentService.create_assignment` (initial placement, transfer, promotion),
direct `POST /employees` (refused: the route carries no branch, so the employee would be invisible
to them) and bulk import (refused: it places employees in any branch)."""

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient

from ..organisation.test_registration_flow import _cleanup
from .test_assigned_branches_scope import _cleanup_access, _restricted_actor
from .test_employee_assignment import (
    _cleanup_assignments,
    _cleanup_employments,
    _cleanup_org_structure,
    _create_branch,
    _create_department,
    _create_designation,
    _create_employee,
    _create_employment,
    _create_legal_entity,
    _register_tenant,
)
from .test_employee_data_scope import _cleanup_employees, _cleanup_scoped_actors

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("seeded_plan_catalogue")]

JOINING = "2020-01-01"
CHANGE = "2021-01-01"


class _Org:
    def __init__(self) -> None:
        self.legal_entity: dict[str, Any] = {}
        self.branches: list[dict[str, Any]] = []
        self.department: dict[str, Any] = {}
        self.designation: dict[str, Any] = {}


async def _org(client: AsyncClient, headers: dict[str, str], branches: int = 3) -> _Org:
    org = _Org()
    org.legal_entity = await _create_legal_entity(client, headers)
    for i in range(branches):
        org.branches.append(
            await _create_branch(client, headers, org.legal_entity["id"], name=f"Branch {i}")
        )
    org.department = await _create_department(client, headers, branch_id=org.branches[0]["id"])
    org.designation = await _create_designation(client, headers, department_id=org.department["id"])
    return org


async def _placed_employee(
    client: AsyncClient, headers: dict[str, str], org: _Org, branch_index: int, name: str
) -> dict[str, Any]:
    """An employee with an employment and a current assignment at one branch (done as the company
    admin, who is never restricted)."""
    employee = await _create_employee(client, headers, first_name=name)
    await _create_employment(
        client,
        headers,
        employee_id=employee["id"],
        legal_entity_id=org.legal_entity["id"],
        joining_date=JOINING,
    )
    response = await client.post(
        f"/v1/employees/{employee['id']}/assignments",
        headers=headers,
        json={
            "effective_from": JOINING,
            "change_type": "INITIAL",
            "branch_id": org.branches[branch_index]["id"],
            "department_id": org.department["id"],
            "designation_id": org.designation["id"],
        },
    )
    assert response.status_code == 201, response.text
    return employee


async def _current_version(client: AsyncClient, headers: dict[str, str], employee_id: str) -> int:
    rows = (await client.get(f"/v1/employees/{employee_id}/assignments", headers=headers)).json()[
        "data"
    ]
    return int(next(r for r in rows if r["effective_to"] is None)["version"])


async def _post_assignment(
    client: AsyncClient, headers: dict[str, str], employee_id: str, **body: Any
) -> Any:
    version = await _current_version(client, headers, employee_id)
    return await client.post(
        f"/v1/employees/{employee_id}/assignments",
        headers={**headers, "If-Match": str(version)},
        json={"effective_from": CHANGE, **body},
    )


async def _done(company_id: UUID, admin_id: UUID | None) -> None:
    await _cleanup_access(company_id)
    await _cleanup_assignments(company_id=company_id)
    await _cleanup_employments(company_id=company_id)
    await _cleanup_employees(company_id=company_id)
    await _cleanup_org_structure(company_id=company_id)
    await _cleanup(company_id=company_id, user_id=admin_id)
    await _cleanup_scoped_actors()


async def test_restricted_hr_transfers_into_an_assigned_branch_but_not_an_unassigned_one(
    client: AsyncClient,
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        org = await _org(client, headers)
        a, b, c = (UUID(x["id"]) for x in org.branches)
        employee = await _placed_employee(client, headers, org, 0, "Mover")
        hr, _ = await _restricted_actor(
            company_id=company_id, role_codes=["HR_ADMIN"], branch_ids=[a, b]
        )

        refused = await _post_assignment(
            client, hr, employee["id"], change_type="TRANSFER", branch_id=str(c)
        )
        assert refused.status_code == 403, refused.text
        assert refused.json()["error"]["code"] == "BRANCH_NOT_ASSIGNED"

        ok = await _post_assignment(
            client, hr, employee["id"], change_type="TRANSFER", branch_id=str(b)
        )
        assert ok.status_code == 201, ok.text
        assert ok.json()["data"]["branch_id"] == str(b)
    finally:
        await _done(company_id, admin_id)


async def test_restricted_hr_cannot_move_into_a_deactivated_assigned_branch(
    client: AsyncClient,
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        org = await _org(client, headers)
        a, b, _c = (UUID(x["id"]) for x in org.branches)
        employee = await _placed_employee(client, headers, org, 0, "Mover")
        hr, _ = await _restricted_actor(
            company_id=company_id, role_codes=["HR_ADMIN"], branch_ids=[a, b]
        )
        deactivated = await client.patch(
            f"/v1/branches/{b}",
            headers={**headers, "If-Match": str(org.branches[1]["version"])},
            json={"is_active": False},
        )
        assert deactivated.status_code == 200, deactivated.text

        refused = await _post_assignment(
            client, hr, employee["id"], change_type="TRANSFER", branch_id=str(b)
        )
        assert refused.status_code == 403, refused.text
        assert refused.json()["error"]["code"] == "BRANCH_NOT_ASSIGNED"
    finally:
        await _done(company_id, admin_id)


async def test_restricted_hr_cannot_place_an_employee_who_has_no_branch_yet(
    client: AsyncClient,
) -> None:
    """A first placement is only possible for someone the caller can already see, and an employee
    with no branch is invisible to a branch-restricted caller (existing rule), so this is a 404
    before any branch is looked at. Initial placement goes through the company admin or
    onboarding."""
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        org = await _org(client, headers)
        a = UUID(org.branches[0]["id"])
        employee = await _create_employee(client, headers, first_name="Unplaced")
        await _create_employment(
            client,
            headers,
            employee_id=employee["id"],
            legal_entity_id=org.legal_entity["id"],
            joining_date=JOINING,
        )
        hr, _ = await _restricted_actor(
            company_id=company_id, role_codes=["HR_ADMIN"], branch_ids=[a]
        )
        response = await client.post(
            f"/v1/employees/{employee['id']}/assignments",
            headers=hr,
            json={
                "effective_from": JOINING,
                "change_type": "INITIAL",
                "branch_id": str(a),
                "department_id": org.department["id"],
                "designation_id": org.designation["id"],
            },
        )
        assert response.status_code == 404, response.text

        placed = await client.post(
            f"/v1/employees/{employee['id']}/assignments",
            headers=headers,
            json={
                "effective_from": JOINING,
                "change_type": "INITIAL",
                "branch_id": str(a),
                "department_id": org.department["id"],
                "designation_id": org.designation["id"],
            },
        )
        assert placed.status_code == 201, placed.text
    finally:
        await _done(company_id, admin_id)


async def test_restricted_hr_can_change_a_manager_without_touching_the_branch(
    client: AsyncClient,
) -> None:
    """An assignment write that names no branch is not checked against the caller's list: the
    branch it carries forward is not their choice. (A visible employee is always in an assigned
    branch for an HR, so the case this guards, a reporting manager who is also a restricted HR
    editing a report in another branch, needs a custom role and is not
    reproduced here; `DataScope.is_branch_restricted` has its own unit tests.)"""
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        org = await _org(client, headers)
        a = UUID(org.branches[0]["id"])
        employee = await _placed_employee(client, headers, org, 0, "Report")
        manager = await _placed_employee(client, headers, org, 0, "Boss")
        hr, _ = await _restricted_actor(
            company_id=company_id, role_codes=["HR_ADMIN"], branch_ids=[a]
        )
        response = await _post_assignment(
            client,
            hr,
            employee["id"],
            change_type="MANAGER_CHANGE",
            reporting_manager_id=manager["id"],
        )
        assert response.status_code == 201, response.text
        assert response.json()["data"]["branch_id"] == str(a)
    finally:
        await _done(company_id, admin_id)


async def test_company_admin_is_unaffected_by_branch_limits(client: AsyncClient) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        org = await _org(client, headers)
        employee = await _placed_employee(client, headers, org, 0, "Mover")
        ok = await _post_assignment(
            client,
            headers,
            employee["id"],
            change_type="TRANSFER",
            branch_id=org.branches[2]["id"],
        )
        assert ok.status_code == 201, ok.text
        created = await client.post("/v1/employees", headers=headers, json={"first_name": "Direct"})
        assert created.status_code == 201, created.text
    finally:
        await _done(company_id, admin_id)


async def test_direct_employee_create_is_refused_for_a_restricted_hr(
    client: AsyncClient,
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        org = await _org(client, headers, branches=1)
        hr, _ = await _restricted_actor(
            company_id=company_id,
            role_codes=["HR_ADMIN"],
            branch_ids=[UUID(org.branches[0]["id"])],
        )
        response = await client.post("/v1/employees", headers=hr, json={"first_name": "Nope"})
        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "BRANCH_RESTRICTED_USE_ONBOARDING"
    finally:
        await _done(company_id, admin_id)


async def test_bulk_import_is_refused_for_a_restricted_hr_but_open_to_the_company_admin(
    client: AsyncClient,
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        org = await _org(client, headers, branches=1)
        hr, _ = await _restricted_actor(
            company_id=company_id,
            role_codes=["HR_ADMIN"],
            branch_ids=[UUID(org.branches[0]["id"])],
        )
        for path in ("/v1/employee-imports/template", "/v1/employee-imports/reference-data"):
            refused = await client.get(path, headers=hr)
            assert refused.status_code == 403, (path, refused.text)
            assert refused.json()["error"]["code"] == "BRANCH_RESTRICTED_IMPORT"
            assert (await client.get(path, headers=headers)).status_code == 200, path
        upload = await client.post(
            "/v1/employee-imports",
            headers=hr,
            files={"file": ("employees.csv", b"a,b\n", "text/csv")},
        )
        assert upload.status_code == 403, upload.text
    finally:
        await _done(company_id, admin_id)
