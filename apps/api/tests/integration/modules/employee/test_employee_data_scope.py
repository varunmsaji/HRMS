"""Integration tests for Employee RBAC data-scope (`SELF`/`REPORTEES`/`REPORTEE_TREE`) —
`GET /v1/employees` and `GET /v1/employees/{id}` only, per
`docs/modules/employee/25_EMPLOYEE_RBAC_DATA_SCOPE_IMPLEMENTATION_PLAN.md` §19.

Fixture pattern mirrors `test_employee.py::test_create_employee_without_permission_rejected` —
the only existing pattern in this codebase for a non-default-role test actor (inline
`Role`/`RolePermission`/`User`/`UserCompany`/`UserRole`/`Session` rows +
`create_access_token(..., employee_id=...)`). `EmployeeAssignment` fixture rows are inserted
directly via the ORM rather than through `POST .../assignments`, since this test suite only needs
`reporting_manager_id`/`effective_to` to be correct — going through the full API would require
building out Legal Entity/Branch/Department/Designation/Grade org structure for every fixture
(`test_employee_assignment.py::_setup_org_structure`) for no benefit to what's being tested here.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from hrms.core.auth.jwt import create_access_token
from hrms.core.auth.passwords import hash_password
from hrms.core.db.models.identity import (
    Permission,
    Role,
    RolePermission,
    Session,
    User,
    UserCompany,
    UserRole,
)
from hrms.core.db.session import get_session_factory
from hrms.modules.employee.models import EmployeeAssignment, Employment
from hrms.modules.employee.permissions import EMPLOYEE_TRANSFER, EMPLOYEE_VIEW_ALL
from hrms.modules.identity.permissions import EMPLOYEE_VIEW
from hrms.modules.organisation.models import Branch, LegalEntity

from ..organisation.test_registration_flow import _cleanup, _register

pytestmark = pytest.mark.asyncio


# --- Shared fixtures / helpers ------------------------------------------------------------


async def _register_tenant(
    client: AsyncClient, **overrides: Any
) -> tuple[dict[str, str], UUID, UUID | None]:
    response, company_id, user_id = await _register(client, **overrides)
    assert response.status_code == 201
    assert company_id is not None
    data = response.json()["data"]
    return (
        {
            "Authorization": f"Bearer {data['access_token']}",
            "X-Company-Id": str(company_id),
        },
        company_id,
        user_id,
    )


async def _create_employee(
    client: AsyncClient, headers: dict[str, str], first_name: str = "Asha", **extra: Any
) -> dict[str, Any]:
    response = await client.post(
        "/v1/employees", headers=headers, json={"first_name": first_name, **extra}
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _assign_manager(
    *,
    company_id: UUID,
    employee_id: UUID,
    reporting_manager_id: UUID | None,
    branch_id: UUID | None = None,
    effective_from: date = date(2027, 1, 1),
    effective_to: date | None = None,
) -> None:
    """Inserts a minimal `employee_assignment` row directly — only the columns the
    `REPORTEES`/`REPORTEE_TREE`/`BRANCH` resolvers read (`company_id`, `employee_id`,
    `reporting_manager_id`, `branch_id`, `effective_from`/`effective_to`) are set; every other
    column is left at its nullable/default value, matching the schema
    (`employee/models.py:126-154`). `created_at`/`updated_at` are passed explicitly, matching
    every other inline-fixture pattern in this codebase (`test_employee.py`'s inline
    `Role`/`User`/`Session` construction) rather than relying on `TimestampMixin`'s
    `server_default`."""
    factory = get_session_factory()
    async with factory() as session:
        now = datetime.now(UTC)
        session.add(
            EmployeeAssignment(
                id=uuid4(),
                company_id=company_id,
                employee_id=employee_id,
                reporting_manager_id=reporting_manager_id,
                branch_id=branch_id,
                effective_from=effective_from,
                effective_to=effective_to,
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()


async def _setup_branches(*, company_id: UUID, count: int) -> list[UUID]:
    """Inserts one `legal_entity` row plus `count` `branch` rows directly — `branch_id` is a real
    FK (`branch.id`), so the `BRANCH` scope tests need actual rows to reference, the same reason
    `_setup_active_employment` inserts a real `LegalEntity` for its own FK."""
    factory = get_session_factory()
    branch_ids = [uuid4() for _ in range(count)]
    async with factory() as session:
        now = datetime.now(UTC)
        legal_entity_id = uuid4()
        session.add(
            LegalEntity(
                id=legal_entity_id,
                company_id=company_id,
                name="Test Legal Entity",
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        for branch_id in branch_ids:
            session.add(
                Branch(
                    id=branch_id,
                    company_id=company_id,
                    legal_entity_id=legal_entity_id,
                    name=f"Test Branch {branch_id.hex[:8]}",
                    created_at=now,
                    updated_at=now,
                )
            )
        await session.commit()
    return branch_ids


async def _setup_active_employment(
    *, company_id: UUID, employee_id: UUID, joining_date: date = date(2027, 1, 1)
) -> None:
    """Inserts a minimal `legal_entity` + `employment` row directly, mirroring `_assign_manager`'s
    "just enough columns for the code path under test" pattern rather than going through the full
    `POST /legal-entities` + `POST .../employments` API.
    `EmployeeAssignmentService.create_assignment` requires a covering `Employment` episode
    (`NoActiveEmploymentError` otherwise,
    `service.py:836-837`) for any `effective_from` it's asked to write — needed by the
    self-elevation attack/regression tests below, which write through the real API to exercise
    `reporting_manager_id` validation, not by direct `EmployeeAssignment` inserts."""
    factory = get_session_factory()
    async with factory() as session:
        now = datetime.now(UTC)
        legal_entity_id = uuid4()
        session.add(
            LegalEntity(
                id=legal_entity_id,
                company_id=company_id,
                name="Test Legal Entity",
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        session.add(
            Employment(
                id=uuid4(),
                company_id=company_id,
                employee_id=employee_id,
                legal_entity_id=legal_entity_id,
                joining_date=joining_date,
                status="ACTIVE",
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()


async def _create_scoped_actor(
    *,
    company_id: UUID,
    role_grants: list[list[tuple[str, str]]],
    employee_id: UUID | None,
) -> tuple[dict[str, str], UUID]:
    """One role per entry in `role_grants`, each granting the listed `(permission_code,
    data_scope)` pairs — supports both the single-role and multi-role-union test cases (plan §12,
    §19)."""
    factory = get_session_factory()
    async with factory() as session:
        now = datetime.now(UTC)
        user_id = uuid4()
        session.add(
            User(
                id=user_id,
                email=f"actor-{user_id.hex[:8]}@example.com",
                password_hash=hash_password("CorrectHorse9"),
                status="ACTIVE",
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()

        user_company = UserCompany(
            id=uuid4(),
            user_id=user_id,
            company_id=company_id,
            is_primary=True,
            status="ACTIVE",
            created_at=now,
            updated_at=now,
        )
        session.add(user_company)
        await session.flush()

        for grants in role_grants:
            role_id = uuid4()
            session.add(
                Role(
                    id=role_id,
                    company_id=company_id,
                    code=f"TEST_SCOPED_ROLE_{role_id.hex[:8]}",
                    name="Test scoped role",
                    is_system=False,
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.flush()
            for code, data_scope in grants:
                permission = (
                    await session.execute(select(Permission).where(Permission.code == code))
                ).scalar_one()
                session.add(
                    RolePermission(
                        role_id=role_id, permission_id=permission.id, data_scope=data_scope
                    )
                )
            await session.flush()
            session.add(UserRole(id=uuid4(), user_company_id=user_company.id, role_id=role_id))

        session_id = uuid4()
        session.add(
            Session(
                id=session_id,
                user_id=user_id,
                company_id=company_id,
                expires_at=now + timedelta(days=1),
            )
        )
        await session.commit()

    token = create_access_token(
        user_id=user_id, company_id=company_id, session_id=session_id, employee_id=employee_id
    )
    headers = {"Authorization": f"Bearer {token}", "X-Company-Id": str(company_id)}
    return headers, user_id


async def _cleanup_employees(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("DELETE FROM employee_assignment WHERE company_id = :cid"),
            {"cid": str(company_id)},
        )
        await session.execute(
            text("DELETE FROM employment WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.execute(
            text("DELETE FROM employee WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.execute(
            text("DELETE FROM branch WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.execute(
            text("DELETE FROM legal_entity WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.execute(
            text("DELETE FROM number_series WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.commit()


async def _cleanup_scoped_actors() -> None:
    """Mirrors `test_employee.py`'s inline-viewer cleanup — `_cleanup(company_id=...)` already
    removes every `Role`/`RolePermission`/`UserCompany`/`UserRole` scoped to the company
    (including every role `_create_scoped_actor` adds), but only deletes the one admin `user_id`
    row itself, so the actor `User`/`Session` rows need their own cleanup, run after
    `_cleanup(...)` so the `UserCompany` FK reference is already gone."""
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text(
                "DELETE FROM session WHERE user_id IN "
                "(SELECT id FROM \"user\" WHERE email LIKE 'actor-%')"
            )
        )
        await session.execute(text("DELETE FROM \"user\" WHERE email LIKE 'actor-%'"))
        await session.commit()


# --- SELF ----------------------------------------------------------------------------------


async def test_self_scope_sees_own_record_only(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        self_employee = await _create_employee(client, headers, first_name="Self")
        other_employee = await _create_employee(client, headers, first_name="Other")

        actor_headers, _actor_id = await _create_scoped_actor(
            company_id=company_id,
            role_grants=[[(EMPLOYEE_VIEW, "SELF"), (EMPLOYEE_VIEW_ALL, "SELF")]],
            employee_id=UUID(self_employee["id"]),
        )

        own = await client.get(f"/v1/employees/{self_employee['id']}", headers=actor_headers)
        assert own.status_code == 200
        assert own.json()["data"]["id"] == self_employee["id"]

        other = await client.get(f"/v1/employees/{other_employee['id']}", headers=actor_headers)
        assert other.status_code == 404

        listed = await client.get("/v1/employees", headers=actor_headers)
        assert listed.status_code == 200
        assert [row["id"] for row in listed.json()["data"]] == [self_employee["id"]]
    finally:
        await _cleanup_employees(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=admin_id)
        await _cleanup_scoped_actors()


async def test_self_scope_no_employee_id_sees_nothing(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Decisions doc, Decision B edge case: a user with no `Employee` row holding a `SELF`-scoped
    grant must fail closed, never fall back to `COMPANY`."""
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)

        actor_headers, _actor_id = await _create_scoped_actor(
            company_id=company_id,
            role_grants=[[(EMPLOYEE_VIEW, "SELF"), (EMPLOYEE_VIEW_ALL, "SELF")]],
            employee_id=None,
        )

        detail = await client.get(f"/v1/employees/{employee['id']}", headers=actor_headers)
        assert detail.status_code == 404

        listed = await client.get("/v1/employees", headers=actor_headers)
        assert listed.status_code == 200
        assert listed.json()["data"] == []
    finally:
        await _cleanup_employees(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=admin_id)
        await _cleanup_scoped_actors()


# --- REPORTEES -------------------------------------------------------------------------------


async def test_reportees_scope_sees_direct_reports_only(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        manager = await _create_employee(client, headers, first_name="Manager")
        report_1 = await _create_employee(client, headers, first_name="ReportOne")
        report_2 = await _create_employee(client, headers, first_name="ReportTwo")
        unrelated = await _create_employee(client, headers, first_name="Unrelated")
        second_level = await _create_employee(client, headers, first_name="SecondLevel")

        await _assign_manager(
            company_id=company_id,
            employee_id=UUID(report_1["id"]),
            reporting_manager_id=UUID(manager["id"]),
        )
        await _assign_manager(
            company_id=company_id,
            employee_id=UUID(report_2["id"]),
            reporting_manager_id=UUID(manager["id"]),
        )
        # Reports to report_1, not to manager directly — must stay invisible under REPORTEES.
        await _assign_manager(
            company_id=company_id,
            employee_id=UUID(second_level["id"]),
            reporting_manager_id=UUID(report_1["id"]),
        )

        actor_headers, _actor_id = await _create_scoped_actor(
            company_id=company_id,
            role_grants=[[(EMPLOYEE_VIEW, "REPORTEES"), (EMPLOYEE_VIEW_ALL, "REPORTEES")]],
            employee_id=UUID(manager["id"]),
        )

        for emp in (report_1, report_2):
            response = await client.get(f"/v1/employees/{emp['id']}", headers=actor_headers)
            assert response.status_code == 200, emp

        for emp in (unrelated, second_level, manager):
            response = await client.get(f"/v1/employees/{emp['id']}", headers=actor_headers)
            assert response.status_code == 404, emp

        listed = await client.get("/v1/employees", headers=actor_headers)
        assert {row["id"] for row in listed.json()["data"]} == {report_1["id"], report_2["id"]}
    finally:
        await _cleanup_employees(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=admin_id)
        await _cleanup_scoped_actors()


async def test_reportees_scope_manager_with_no_reports_sees_empty_list(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        manager = await _create_employee(client, headers, first_name="LonelyManager")
        actor_headers, _actor_id = await _create_scoped_actor(
            company_id=company_id,
            role_grants=[[(EMPLOYEE_VIEW_ALL, "REPORTEES")]],
            employee_id=UUID(manager["id"]),
        )
        listed = await client.get("/v1/employees", headers=actor_headers)
        assert listed.status_code == 200
        assert listed.json()["data"] == []
    finally:
        await _cleanup_employees(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=admin_id)
        await _cleanup_scoped_actors()


async def test_reportees_scope_excludes_terminated_assignment(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A closed (`effective_to` set) assignment row — the shape a termination cascade leaves
    behind — no longer counts as a *current* report. `as_of` (historical) resolution is out of
    this task's scope (plan §5/§22); only the "current" half of Decision D is asserted here."""
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        manager = await _create_employee(client, headers, first_name="Manager")
        formerly_reported = await _create_employee(client, headers, first_name="FormerReport")

        await _assign_manager(
            company_id=company_id,
            employee_id=UUID(formerly_reported["id"]),
            reporting_manager_id=UUID(manager["id"]),
            effective_from=date(2026, 1, 1),
            effective_to=date(2026, 6, 1),
        )

        actor_headers, _actor_id = await _create_scoped_actor(
            company_id=company_id,
            role_grants=[[(EMPLOYEE_VIEW, "REPORTEES"), (EMPLOYEE_VIEW_ALL, "REPORTEES")]],
            employee_id=UUID(manager["id"]),
        )

        response = await client.get(
            f"/v1/employees/{formerly_reported['id']}", headers=actor_headers
        )
        assert response.status_code == 404

        listed = await client.get("/v1/employees", headers=actor_headers)
        assert listed.json()["data"] == []
    finally:
        await _cleanup_employees(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=admin_id)
        await _cleanup_scoped_actors()


async def test_reportees_scope_includes_inactive_but_not_deactivated_employee(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Decisions doc, Decision D: deactivation does not sever the manager relationship."""
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        manager = await _create_employee(client, headers, first_name="Manager")
        report = await _create_employee(client, headers, first_name="Report")
        await _assign_manager(
            company_id=company_id,
            employee_id=UUID(report["id"]),
            reporting_manager_id=UUID(manager["id"]),
        )

        deactivate = await client.request(
            "DELETE",
            f"/v1/employees/{report['id']}",
            headers={**headers, "If-Match": str(report["version"])},
        )
        assert deactivate.status_code == 200
        assert deactivate.json()["data"]["is_active"] is False

        actor_headers, _actor_id = await _create_scoped_actor(
            company_id=company_id,
            role_grants=[[(EMPLOYEE_VIEW, "REPORTEES")]],
            employee_id=UUID(manager["id"]),
        )
        response = await client.get(f"/v1/employees/{report['id']}", headers=actor_headers)
        assert response.status_code == 200
    finally:
        await _cleanup_employees(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=admin_id)
        await _cleanup_scoped_actors()


# --- BRANCH -----------------------------------------------------------------------------------


async def test_branch_scope_sees_branch_colleagues_only(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Unlike `REPORTEES`, `BRANCH` includes the caller themself — a branch manager is a
    colleague of their own branch, not excluded from it (`core/rbac/types.py`
    `DataScopeLevel.BRANCH` docstring)."""
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        branch_a, branch_b = await _setup_branches(company_id=company_id, count=2)

        manager = await _create_employee(client, headers, first_name="BranchManager")
        colleague = await _create_employee(client, headers, first_name="BranchColleague")
        other_branch = await _create_employee(client, headers, first_name="OtherBranch")
        no_branch = await _create_employee(client, headers, first_name="NoBranch")

        await _assign_manager(
            company_id=company_id,
            employee_id=UUID(manager["id"]),
            reporting_manager_id=None,
            branch_id=branch_a,
        )
        await _assign_manager(
            company_id=company_id,
            employee_id=UUID(colleague["id"]),
            reporting_manager_id=None,
            branch_id=branch_a,
        )
        await _assign_manager(
            company_id=company_id,
            employee_id=UUID(other_branch["id"]),
            reporting_manager_id=None,
            branch_id=branch_b,
        )
        # `no_branch` deliberately has no assignment row at all.

        actor_headers, _actor_id = await _create_scoped_actor(
            company_id=company_id,
            role_grants=[[(EMPLOYEE_VIEW, "BRANCH"), (EMPLOYEE_VIEW_ALL, "BRANCH")]],
            employee_id=UUID(manager["id"]),
        )

        for emp in (manager, colleague):
            response = await client.get(f"/v1/employees/{emp['id']}", headers=actor_headers)
            assert response.status_code == 200, emp

        for emp in (other_branch, no_branch):
            response = await client.get(f"/v1/employees/{emp['id']}", headers=actor_headers)
            assert response.status_code == 404, emp

        listed = await client.get("/v1/employees", headers=actor_headers)
        assert {row["id"] for row in listed.json()["data"]} == {manager["id"], colleague["id"]}
    finally:
        await _cleanup_employees(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=admin_id)
        await _cleanup_scoped_actors()


async def test_branch_scope_caller_with_no_branch_sees_nothing(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Fails closed: a caller with no current assignment (or one with `branch_id IS NULL`)
    resolves to an empty visible set, never `COMPANY` (Decision B edge case, extended to
    `BRANCH`)."""
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        manager = await _create_employee(client, headers, first_name="UnassignedManager")
        actor_headers, _actor_id = await _create_scoped_actor(
            company_id=company_id,
            role_grants=[[(EMPLOYEE_VIEW_ALL, "BRANCH")]],
            employee_id=UUID(manager["id"]),
        )
        listed = await client.get("/v1/employees", headers=actor_headers)
        assert listed.status_code == 200
        assert listed.json()["data"] == []
    finally:
        await _cleanup_employees(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=admin_id)
        await _cleanup_scoped_actors()


async def test_branch_scope_excludes_terminated_assignment(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A closed (`effective_to` set) assignment row no longer counts as the caller's *current*
    branch — same "current row only" posture as `REPORTEES` (Decision D)."""
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        (branch_a,) = await _setup_branches(company_id=company_id, count=1)

        manager = await _create_employee(client, headers, first_name="FormerBranchManager")
        formerly_colleague = await _create_employee(client, headers, first_name="FormerColleague")

        await _assign_manager(
            company_id=company_id,
            employee_id=UUID(manager["id"]),
            reporting_manager_id=None,
            branch_id=branch_a,
            effective_from=date(2026, 1, 1),
            effective_to=date(2026, 6, 1),
        )
        await _assign_manager(
            company_id=company_id,
            employee_id=UUID(formerly_colleague["id"]),
            reporting_manager_id=None,
            branch_id=branch_a,
            effective_from=date(2026, 1, 1),
            effective_to=date(2026, 6, 1),
        )

        actor_headers, _actor_id = await _create_scoped_actor(
            company_id=company_id,
            role_grants=[[(EMPLOYEE_VIEW_ALL, "BRANCH")]],
            employee_id=UUID(manager["id"]),
        )

        listed = await client.get("/v1/employees", headers=actor_headers)
        assert listed.status_code == 200
        assert listed.json()["data"] == []
    finally:
        await _cleanup_employees(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=admin_id)
        await _cleanup_scoped_actors()


# --- REPORTEE_TREE ---------------------------------------------------------------------------


async def test_reportee_tree_scope_sees_descendants_not_unrelated_branch(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`docs/product/19_RBAC_and_Permission_Matrix.md §5`'s worked example, transposed:
    top (A) -> sub_manager (B) -> leaf_1 (C), leaf_2 (D). An unrelated branch (X, reporting to
    nobody in this tree) must stay invisible. Kept to 5 employees total — the `FREE` plan's seat
    limit (`seed/plan_catalogue.py`,
    `test_employee.py::test_create_employee_seat_limit_enforced`)."""
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        top = await _create_employee(client, headers, first_name="Top")
        sub_manager = await _create_employee(client, headers, first_name="SubManager")
        leaf_1 = await _create_employee(client, headers, first_name="LeafOne")
        leaf_2 = await _create_employee(client, headers, first_name="LeafTwo")
        unrelated = await _create_employee(client, headers, first_name="Unrelated")

        await _assign_manager(
            company_id=company_id,
            employee_id=UUID(sub_manager["id"]),
            reporting_manager_id=UUID(top["id"]),
        )
        await _assign_manager(
            company_id=company_id,
            employee_id=UUID(leaf_1["id"]),
            reporting_manager_id=UUID(sub_manager["id"]),
        )
        await _assign_manager(
            company_id=company_id,
            employee_id=UUID(leaf_2["id"]),
            reporting_manager_id=UUID(sub_manager["id"]),
        )

        actor_headers, _actor_id = await _create_scoped_actor(
            company_id=company_id,
            role_grants=[[(EMPLOYEE_VIEW, "REPORTEE_TREE"), (EMPLOYEE_VIEW_ALL, "REPORTEE_TREE")]],
            employee_id=UUID(top["id"]),
        )

        for emp in (sub_manager, leaf_1, leaf_2):
            response = await client.get(f"/v1/employees/{emp['id']}", headers=actor_headers)
            assert response.status_code == 200, emp

        for emp in (unrelated, top):
            response = await client.get(f"/v1/employees/{emp['id']}", headers=actor_headers)
            assert response.status_code == 404, emp

        listed = await client.get("/v1/employees", headers=actor_headers)
        assert {row["id"] for row in listed.json()["data"]} == {
            sub_manager["id"],
            leaf_1["id"],
            leaf_2["id"],
        }
    finally:
        await _cleanup_employees(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=admin_id)
        await _cleanup_scoped_actors()


async def test_reportee_tree_scope_terminates_on_cyclic_hierarchy(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """No write-time cycle guard exists yet (plan §17) — this asserts the depth cap makes the
    query terminate (test completes, `200` returned) rather than hang, not that the resulting
    membership is semantically "correct" for a malformed hierarchy."""
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        p = await _create_employee(client, headers, first_name="P")
        q = await _create_employee(client, headers, first_name="Q")
        r = await _create_employee(client, headers, first_name="R")

        # P -> Q -> R -> P (cyclic, bypasses the (non-existent) write-time guard by direct insert)
        await _assign_manager(
            company_id=company_id, employee_id=UUID(q["id"]), reporting_manager_id=UUID(p["id"])
        )
        await _assign_manager(
            company_id=company_id, employee_id=UUID(r["id"]), reporting_manager_id=UUID(q["id"])
        )
        await _assign_manager(
            company_id=company_id, employee_id=UUID(p["id"]), reporting_manager_id=UUID(r["id"])
        )

        actor_headers, _actor_id = await _create_scoped_actor(
            company_id=company_id,
            role_grants=[[(EMPLOYEE_VIEW_ALL, "REPORTEE_TREE")]],
            employee_id=UUID(p["id"]),
        )

        listed = await client.get("/v1/employees", headers=actor_headers)
        assert listed.status_code == 200
        returned_ids = {row["id"] for row in listed.json()["data"]}
        assert returned_ids.issubset({p["id"], q["id"], r["id"]})
        assert {q["id"], r["id"]}.issubset(returned_ids)
    finally:
        await _cleanup_employees(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=admin_id)
        await _cleanup_scoped_actors()


# --- Security ------------------------------------------------------------------------------


async def test_scoped_actor_cannot_access_cross_tenant_employee(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, admin_a = await _register_tenant(client)
    headers_b, company_b, admin_b = await _register_tenant(client)
    try:
        employee_b = await _create_employee(client, headers_b, first_name="TenantBEmployee")
        self_employee_a = await _create_employee(client, headers_a, first_name="TenantAEmployee")

        actor_headers, _actor_id = await _create_scoped_actor(
            company_id=company_a,
            role_grants=[[(EMPLOYEE_VIEW, "SELF")]],
            employee_id=UUID(self_employee_a["id"]),
        )

        # Tenant mismatch is caught before scope even runs (`get_tenant_context`) — still 404.
        response = await client.get(
            f"/v1/employees/{employee_b['id']}",
            headers={**actor_headers, "X-Company-Id": str(company_a)},
        )
        assert response.status_code == 404
    finally:
        await _cleanup_employees(company_id=company_a)
        await _cleanup_employees(company_id=company_b)
        await _cleanup(company_id=company_a, user_id=admin_a)
        await _cleanup(company_id=company_b, user_id=admin_b)
        await _cleanup_scoped_actors()


async def test_scoped_actor_forged_id_returns_not_found(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        self_employee = await _create_employee(client, headers)
        actor_headers, _actor_id = await _create_scoped_actor(
            company_id=company_id,
            role_grants=[[(EMPLOYEE_VIEW, "SELF")]],
            employee_id=UUID(self_employee["id"]),
        )
        response = await client.get(f"/v1/employees/{uuid4()}", headers=actor_headers)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"
    finally:
        await _cleanup_employees(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=admin_id)
        await _cleanup_scoped_actors()


# --- COMPANY_ADMIN regression -----------------------------------------------------------------


async def test_company_admin_scope_unchanged(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`docs/architecture/RBAC_DATA_SCOPE_DECISIONS.md` Decision H /
    `25_...IMPLEMENTATION_PLAN.md` §11 — `COMPANY_ADMIN`'s `role_permission` rows default to
    `'COMPANY'` on migration; this proves zero observable behavior change for the existing role."""
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        employee_1 = await _create_employee(client, headers, first_name="One")
        employee_2 = await _create_employee(client, headers, first_name="Two")

        for emp in (employee_1, employee_2):
            response = await client.get(f"/v1/employees/{emp['id']}", headers=headers)
            assert response.status_code == 200

        listed = await client.get("/v1/employees", headers=headers)
        assert {row["id"] for row in listed.json()["data"]} == {employee_1["id"], employee_2["id"]}
    finally:
        await _cleanup_employees(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=admin_id)


# --- Write-path data-scope enforcement (Finding C / F9) --------------------------------------
#
# `docs/modules/employee/39_EMPLOYEE_ACCESS_CONTROL_IMPLEMENTATION_PLAN.md` Phase 2:
# `update_employee`/`deactivate_employee` used to bind `_scope: Annotated[object, ...]` — the
# resolved `DataScope` was thrown away, making every `EMPLOYEE.UPDATE`/`.DEACTIVATE` grant
# company-wide regardless of its stored `data_scope`. Fixed per Phase 2 — a caller now needs the
# target employee within their resolved visible set, exactly as every GET route above already
# requires; an out-of-scope target behaves exactly like a nonexistent one (`404`, not `403`).


async def test_update_employee_reportees_scope_target_visibility(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A caller holding `EMPLOYEE.UPDATE` at `REPORTEES` scope can update a direct report, but
    an unrelated employee is invisible (`404`) — the exact write-path scenario
    `39_...PLAN.md` §13 names as the concrete risk."""
    from hrms.modules.employee.permissions import EMPLOYEE_UPDATE

    headers, company_id, admin_id = await _register_tenant(client)
    try:
        manager = await _create_employee(client, headers, first_name="Manager")
        report = await _create_employee(client, headers, first_name="Report")
        unrelated = await _create_employee(client, headers, first_name="Unrelated")
        await _assign_manager(
            company_id=company_id,
            employee_id=UUID(report["id"]),
            reporting_manager_id=UUID(manager["id"]),
        )

        actor_headers, _actor_id = await _create_scoped_actor(
            company_id=company_id,
            role_grants=[[(EMPLOYEE_UPDATE, "REPORTEES")]],
            employee_id=UUID(manager["id"]),
        )

        in_scope = await client.patch(
            f"/v1/employees/{report['id']}",
            headers={**actor_headers, "If-Match": str(report["version"])},
            json={"first_name": "ReportRenamed"},
        )
        assert in_scope.status_code == 200, in_scope.text

        out_of_scope = await client.patch(
            f"/v1/employees/{unrelated['id']}",
            headers={**actor_headers, "If-Match": str(unrelated["version"])},
            json={"first_name": "UnrelatedRenamed"},
        )
        assert out_of_scope.status_code == 404
    finally:
        await _cleanup_employees(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=admin_id)
        await _cleanup_scoped_actors()


async def test_deactivate_employee_reportees_scope_target_visibility(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A caller holding `EMPLOYEE.DEACTIVATE` at `REPORTEES` scope can deactivate a direct
    report, but an unrelated employee is invisible (`404`), never `403`."""
    from hrms.modules.employee.permissions import EMPLOYEE_DEACTIVATE

    headers, company_id, admin_id = await _register_tenant(client)
    try:
        manager = await _create_employee(client, headers, first_name="Manager")
        report = await _create_employee(client, headers, first_name="Report")
        unrelated = await _create_employee(client, headers, first_name="Unrelated")
        await _assign_manager(
            company_id=company_id,
            employee_id=UUID(report["id"]),
            reporting_manager_id=UUID(manager["id"]),
        )

        actor_headers, _actor_id = await _create_scoped_actor(
            company_id=company_id,
            role_grants=[[(EMPLOYEE_DEACTIVATE, "REPORTEES")]],
            employee_id=UUID(manager["id"]),
        )

        out_of_scope = await client.request(
            "DELETE",
            f"/v1/employees/{unrelated['id']}",
            headers={**actor_headers, "If-Match": str(unrelated["version"])},
        )
        assert out_of_scope.status_code == 404

        in_scope = await client.request(
            "DELETE",
            f"/v1/employees/{report['id']}",
            headers={**actor_headers, "If-Match": str(report["version"])},
        )
        assert in_scope.status_code == 200, in_scope.text
        assert in_scope.json()["data"]["is_active"] is False
    finally:
        await _cleanup_employees(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=admin_id)
        await _cleanup_scoped_actors()


async def test_update_employee_cross_tenant_scoped_actor_denied(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Cross-tenant + data-scope composed on a write route: a `COMPANY`-scoped actor in tenant A
    cannot update tenant B's employee, tenant isolation wins first."""
    from hrms.modules.employee.permissions import EMPLOYEE_UPDATE

    headers_a, company_a, admin_a = await _register_tenant(client)
    headers_b, company_b, admin_b = await _register_tenant(client)
    try:
        _self_employee_a = await _create_employee(client, headers_a, first_name="TenantAEmployee")
        employee_b = await _create_employee(client, headers_b, first_name="TenantBEmployee")

        actor_headers, _actor_id = await _create_scoped_actor(
            company_id=company_a,
            role_grants=[[(EMPLOYEE_UPDATE, "COMPANY")]],
            employee_id=None,
        )

        response = await client.patch(
            f"/v1/employees/{employee_b['id']}",
            headers={
                **actor_headers,
                "X-Company-Id": str(company_a),
                "If-Match": str(employee_b["version"]),
            },
            json={"first_name": "ShouldNotWork"},
        )
        assert response.status_code == 404
    finally:
        await _cleanup_employees(company_id=company_a)
        await _cleanup_employees(company_id=company_b)
        await _cleanup(company_id=company_a, user_id=admin_a)
        await _cleanup(company_id=company_b, user_id=admin_b)
        await _cleanup_scoped_actors()


# --- Reporting-manager self-elevation guard -------------------------------------------------
#
# `docs/modules/employee/27_REPORTING_MANAGER_SECURITY_AUDIT.md` — previously an accepted
# `xfail` (`25_...PLAN.md` §17/§22); `reporting_manager_id == caller_employee_id` is now rejected
# unconditionally by `EmployeeAssignmentService.create_assignment`, regardless of which
# permission/scope combination authorized the write.


async def test_reportees_scope_cannot_be_widened_via_self_assignment(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The exact attack `27_...AUDIT.md` §2 describes: an actor holding `EMPLOYEE.VIEW` at
    `REPORTEES` scope plus company-wide `EMPLOYEE.TRANSFER` cannot name themselves as an
    unrelated employee's manager to self-grant `REPORTEES` visibility over them. The write
    itself must be rejected — not merely leave post-write visibility unchanged — so this also
    asserts on the `POST` response, not just the follow-up `GET`."""
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        actor_employee = await _create_employee(client, headers, first_name="Actor")
        target = await _create_employee(client, headers, first_name="Target")
        await _setup_active_employment(company_id=company_id, employee_id=UUID(target["id"]))
        await _assign_manager(
            company_id=company_id, employee_id=UUID(target["id"]), reporting_manager_id=None
        )

        actor_headers, _actor_id = await _create_scoped_actor(
            company_id=company_id,
            role_grants=[
                [(EMPLOYEE_VIEW, "REPORTEES"), (EMPLOYEE_TRANSFER, "COMPANY")],
            ],
            employee_id=UUID(actor_employee["id"]),
        )

        before = await client.get(f"/v1/employees/{target['id']}", headers=actor_headers)
        assert before.status_code == 404

        factory = get_session_factory()
        async with factory() as session:
            current = (
                await session.execute(
                    select(EmployeeAssignment).where(
                        EmployeeAssignment.employee_id == UUID(target["id"]),
                        EmployeeAssignment.effective_to.is_(None),
                    )
                )
            ).scalar_one()
            current_version = current.version

        response = await client.post(
            f"/v1/employees/{target['id']}/assignments",
            headers={**actor_headers, "If-Match": str(current_version)},
            json={
                "effective_from": "2027-07-01",
                "change_type": "MANAGER_CHANGE",
                "reporting_manager_id": str(actor_employee["id"]),
            },
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "INVALID_REPORTING_MANAGER"

        after = await client.get(f"/v1/employees/{target['id']}", headers=actor_headers)
        assert after.status_code == 404, "self-elevation via reporting_manager_id must be blocked"
    finally:
        await _cleanup_employees(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=admin_id)
        await _cleanup_scoped_actors()


async def test_self_elevation_guard_applies_to_first_assignment(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`27_...AUDIT.md` §10 — the guard applies on the `current is None` (very first assignment,
    `change_type=INITIAL`) code path too, not only the `MANAGER_CHANGE`-on-an-existing-row path
    covered above. Fires before the `AssignmentFieldsRequiredError`/branch-ownership checks, so no
    org structure needs to exist for this test to reach it."""
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        actor_employee = await _create_employee(client, headers, first_name="Actor")
        target = await _create_employee(client, headers, first_name="Target")
        await _setup_active_employment(company_id=company_id, employee_id=UUID(target["id"]))

        actor_headers, _actor_id = await _create_scoped_actor(
            company_id=company_id,
            role_grants=[[(EMPLOYEE_TRANSFER, "COMPANY")]],
            employee_id=UUID(actor_employee["id"]),
        )

        response = await client.post(
            f"/v1/employees/{target['id']}/assignments",
            headers=actor_headers,
            json={
                "effective_from": "2027-07-01",
                "change_type": "INITIAL",
                "reporting_manager_id": str(actor_employee["id"]),
            },
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "INVALID_REPORTING_MANAGER"
    finally:
        await _cleanup_employees(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=admin_id)
        await _cleanup_scoped_actors()


async def test_legitimate_manager_change_to_third_party_still_succeeds(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`27_...AUDIT.md` §12 acceptance criterion — the guard must not regress ordinary
    `TRANSFER`/`MANAGER_CHANGE` behavior: an employee-actor holding `EMPLOYEE.TRANSFER` reassigns
    a *different* employee's manager to a *third* employee (never the actor). Must succeed, with a
    correct audit event and effective-dated row — exactly as before this fix."""
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        actor_employee = await _create_employee(client, headers, first_name="Actor")
        target = await _create_employee(client, headers, first_name="Target")
        new_manager = await _create_employee(client, headers, first_name="NewManager")
        await _setup_active_employment(company_id=company_id, employee_id=UUID(target["id"]))
        await _assign_manager(
            company_id=company_id, employee_id=UUID(target["id"]), reporting_manager_id=None
        )

        actor_headers, _actor_id = await _create_scoped_actor(
            company_id=company_id,
            role_grants=[[(EMPLOYEE_TRANSFER, "COMPANY")]],
            employee_id=UUID(actor_employee["id"]),
        )

        factory = get_session_factory()
        async with factory() as session:
            current = (
                await session.execute(
                    select(EmployeeAssignment).where(
                        EmployeeAssignment.employee_id == UUID(target["id"]),
                        EmployeeAssignment.effective_to.is_(None),
                    )
                )
            ).scalar_one()
            current_version = current.version

        response = await client.post(
            f"/v1/employees/{target['id']}/assignments",
            headers={**actor_headers, "If-Match": str(current_version)},
            json={
                "effective_from": "2027-07-01",
                "change_type": "MANAGER_CHANGE",
                "reporting_manager_id": new_manager["id"],
            },
        )
        assert response.status_code == 201, response.text
        assert response.json()["data"]["reporting_manager_id"] == new_manager["id"]

        async with factory() as session:
            audit_rows = (
                (
                    await session.execute(
                        text(
                            "SELECT action FROM audit_log WHERE company_id = :cid "
                            "AND entity_type = 'employee_assignment'"
                        ),
                        {"cid": str(company_id)},
                    )
                )
                .scalars()
                .all()
            )
            assert "ASSIGNMENT_CHANGED" in audit_rows
    finally:
        await _cleanup_employees(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=admin_id)
        await _cleanup_scoped_actors()


# --- Multi-role union ------------------------------------------------------------------------


async def test_multi_role_union_sees_self_and_reportees(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Plan §12: `SELF` and `REPORTEES` are not nested — a user holding both grants (via two
    separate roles) must see the union, not just the "widest-sounding" level alone."""
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        manager = await _create_employee(client, headers, first_name="Manager")
        report = await _create_employee(client, headers, first_name="Report")
        unrelated = await _create_employee(client, headers, first_name="Unrelated")
        await _assign_manager(
            company_id=company_id,
            employee_id=UUID(report["id"]),
            reporting_manager_id=UUID(manager["id"]),
        )

        actor_headers, _actor_id = await _create_scoped_actor(
            company_id=company_id,
            role_grants=[
                [(EMPLOYEE_VIEW, "SELF"), (EMPLOYEE_VIEW_ALL, "SELF")],
                [(EMPLOYEE_VIEW, "REPORTEES"), (EMPLOYEE_VIEW_ALL, "REPORTEES")],
            ],
            employee_id=UUID(manager["id"]),
        )

        own = await client.get(f"/v1/employees/{manager['id']}", headers=actor_headers)
        assert own.status_code == 200

        via_reportees = await client.get(f"/v1/employees/{report['id']}", headers=actor_headers)
        assert via_reportees.status_code == 200

        out_of_scope = await client.get(f"/v1/employees/{unrelated['id']}", headers=actor_headers)
        assert out_of_scope.status_code == 404

        listed = await client.get("/v1/employees", headers=actor_headers)
        assert {row["id"] for row in listed.json()["data"]} == {manager["id"], report["id"]}
    finally:
        await _cleanup_employees(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=admin_id)
        await _cleanup_scoped_actors()
