"""Admin-assigned branch scope (`user_branch_access`) for HR_ADMIN and BRANCH_MANAGER.

Access comes from the list the company admin assigns, not from the holder's own job placement:
one person may cover several branches, several people may cover one branch, an HR with no employee
row still sees their branches, an empty list sees nobody, and a company admin always sees everyone.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from hrms.core.auth.jwt import create_access_token
from hrms.core.auth.passwords import hash_password
from hrms.core.db.models.identity import (
    Role,
    Session,
    User,
    UserBranchAccess,
    UserCompany,
    UserRole,
)
from hrms.core.db.session import get_session_factory
from hrms.core.rbac.service import RbacService
from hrms.core.rbac.types import DataScopeLevel
from hrms.modules.leave.permissions import LEAVE_APPLICATION_APPROVE

from ..organisation.test_registration_flow import _cleanup
from .test_employee_data_scope import (
    _assign_manager,
    _cleanup_employees,
    _cleanup_scoped_actors,
    _create_employee,
    _create_scoped_actor,
    _register_tenant,
    _setup_branches,
)

pytestmark = pytest.mark.asyncio

PAYROLL_RUN_VIEW = "PAYROLL.RUN_VIEW"
SETTINGS_USER_MANAGE = "SETTINGS.USER.MANAGE"


async def _restricted_actor(
    *,
    company_id: UUID,
    role_codes: list[str],
    branch_ids: list[UUID],
    employee_id: UUID | None = None,
    extra_grants: list[list[tuple[str, str]]] | None = None,
) -> tuple[dict[str, str], UUID]:
    """A user holding the company's real system roles (`HR_ADMIN`, `BRANCH_MANAGER`, ...) plus the
    given `user_branch_access` rows. `extra_grants` adds custom roles, as `_create_scoped_actor`."""
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
        for code in role_codes:
            role = (
                await session.execute(
                    select(Role).where(Role.company_id == company_id, Role.code == code)
                )
            ).scalar_one()
            session.add(UserRole(id=uuid4(), user_company_id=user_company.id, role_id=role.id))
        for branch_id in branch_ids:
            session.add(
                UserBranchAccess(
                    id=uuid4(),
                    company_id=company_id,
                    user_id=user_id,
                    branch_id=branch_id,
                    created_at=now,
                    updated_at=now,
                )
            )
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
    return {"Authorization": f"Bearer {token}", "X-Company-Id": str(company_id)}, user_id


async def _cleanup_access(company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("DELETE FROM user_branch_access WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.commit()


async def _at_branch(
    client: AsyncClient,
    headers: dict[str, str],
    company_id: UUID,
    name: str,
    branch_id: UUID | None,
) -> dict[str, str]:
    emp = await _create_employee(client, headers, first_name=name)
    if branch_id is not None:
        await _assign_manager(
            company_id=company_id,
            employee_id=UUID(emp["id"]),
            reporting_manager_id=None,
            branch_id=branch_id,
        )
    return emp


async def _listed(client: AsyncClient, headers: dict[str, str]) -> set[str]:
    response = await client.get("/v1/employees", headers=headers)
    assert response.status_code == 200, response.text
    return {row["id"] for row in response.json()["data"]}


async def _status(client: AsyncClient, headers: dict[str, str], employee: dict[str, str]) -> int:
    return (await client.get(f"/v1/employees/{employee['id']}", headers=headers)).status_code


async def _done(company_id: UUID, admin_id: UUID | None) -> None:
    await _cleanup_access(company_id)
    await _cleanup_employees(company_id=company_id)
    await _cleanup(company_id=company_id, user_id=admin_id)
    await _cleanup_scoped_actors()


async def test_two_hrs_with_disjoint_branches_each_see_only_their_own(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        blr, mum = await _setup_branches(company_id=company_id, count=2)
        in_blr = await _at_branch(client, headers, company_id, "InBengaluru", blr)
        in_mum = await _at_branch(client, headers, company_id, "InMumbai", mum)
        hr_blr, _ = await _restricted_actor(
            company_id=company_id, role_codes=["HR_ADMIN"], branch_ids=[blr]
        )
        hr_mum, _ = await _restricted_actor(
            company_id=company_id, role_codes=["HR_ADMIN"], branch_ids=[mum]
        )
        assert await _listed(client, hr_blr) == {in_blr["id"]}
        assert await _listed(client, hr_mum) == {in_mum["id"]}
        assert await _status(client, hr_blr, in_blr) == 200
        assert await _status(client, hr_blr, in_mum) == 404
        assert await _status(client, hr_mum, in_mum) == 200
        assert await _status(client, hr_mum, in_blr) == 404
    finally:
        await _done(company_id, admin_id)


async def test_one_hr_with_two_branches_sees_both_and_not_the_third(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        blr, mum, che = await _setup_branches(company_id=company_id, count=3)
        in_blr = await _at_branch(client, headers, company_id, "InBengaluru", blr)
        in_mum = await _at_branch(client, headers, company_id, "InMumbai", mum)
        in_che = await _at_branch(client, headers, company_id, "InChennai", che)
        hr, _ = await _restricted_actor(
            company_id=company_id, role_codes=["HR_ADMIN"], branch_ids=[mum, che]
        )
        assert await _listed(client, hr) == {in_mum["id"], in_che["id"]}
        assert await _status(client, hr, in_blr) == 404
    finally:
        await _done(company_id, admin_id)


async def test_two_users_assigned_the_same_branch_both_see_it(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        (blr,) = await _setup_branches(company_id=company_id, count=1)
        in_blr = await _at_branch(client, headers, company_id, "InBengaluru", blr)
        hr, _ = await _restricted_actor(
            company_id=company_id, role_codes=["HR_ADMIN"], branch_ids=[blr]
        )
        bm, _ = await _restricted_actor(
            company_id=company_id, role_codes=["BRANCH_MANAGER"], branch_ids=[blr]
        )
        assert await _listed(client, hr) == {in_blr["id"]}
        assert await _listed(client, bm) == {in_blr["id"]}
    finally:
        await _done(company_id, admin_id)


async def test_hr_with_no_employee_row_still_sees_the_assigned_branch(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        (blr,) = await _setup_branches(company_id=company_id, count=1)
        in_blr = await _at_branch(client, headers, company_id, "InBengaluru", blr)
        hr, _ = await _restricted_actor(
            company_id=company_id, role_codes=["HR_ADMIN"], branch_ids=[blr], employee_id=None
        )
        assert await _listed(client, hr) == {in_blr["id"]}
    finally:
        await _done(company_id, admin_id)


async def test_an_empty_list_sees_nobody_and_never_the_whole_company(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        (blr,) = await _setup_branches(company_id=company_id, count=1)
        in_blr = await _at_branch(client, headers, company_id, "InBengaluru", blr)
        # Even if the user's own job placement is at the branch: placement grants nothing.
        placed = await _at_branch(client, headers, company_id, "PlacedHr", blr)
        hr, _ = await _restricted_actor(
            company_id=company_id,
            role_codes=["HR_ADMIN"],
            branch_ids=[],
            employee_id=UUID(placed["id"]),
        )
        assert await _listed(client, hr) == set()
        assert await _status(client, hr, in_blr) == 404
    finally:
        await _done(company_id, admin_id)


async def test_employee_with_no_current_branch_is_invisible_to_a_branch_hr(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        (blr,) = await _setup_branches(company_id=company_id, count=1)
        in_blr = await _at_branch(client, headers, company_id, "InBengaluru", blr)
        no_branch = await _at_branch(client, headers, company_id, "NoBranch", None)
        hr, _ = await _restricted_actor(
            company_id=company_id, role_codes=["HR_ADMIN"], branch_ids=[blr]
        )
        assert await _listed(client, hr) == {in_blr["id"]}
        assert await _status(client, hr, no_branch) == 404
    finally:
        await _done(company_id, admin_id)


async def test_a_deactivated_branch_drops_out_of_the_set(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        blr, mum = await _setup_branches(company_id=company_id, count=2)
        in_blr = await _at_branch(client, headers, company_id, "InBengaluru", blr)
        in_mum = await _at_branch(client, headers, company_id, "InMumbai", mum)
        hr, _ = await _restricted_actor(
            company_id=company_id, role_codes=["HR_ADMIN"], branch_ids=[blr, mum]
        )
        assert await _listed(client, hr) == {in_blr["id"], in_mum["id"]}
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                text("UPDATE branch SET is_active = false WHERE id = :b"), {"b": str(mum)}
            )
            await session.commit()
        assert await _listed(client, hr) == {in_blr["id"]}
        assert await _status(client, hr, in_mum) == 404
    finally:
        await _done(company_id, admin_id)


async def test_company_admin_sees_everyone_with_no_branch_list(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        blr, mum = await _setup_branches(company_id=company_id, count=2)
        in_blr = await _at_branch(client, headers, company_id, "InBengaluru", blr)
        in_mum = await _at_branch(client, headers, company_id, "InMumbai", mum)
        no_branch = await _at_branch(client, headers, company_id, "NoBranch", None)
        assert await _listed(client, headers) == {in_blr["id"], in_mum["id"], no_branch["id"]}
    finally:
        await _done(company_id, admin_id)


async def test_company_admin_who_is_also_hr_keeps_the_whole_company(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        blr, mum = await _setup_branches(company_id=company_id, count=2)
        in_blr = await _at_branch(client, headers, company_id, "InBengaluru", blr)
        in_mum = await _at_branch(client, headers, company_id, "InMumbai", mum)
        both, _ = await _restricted_actor(
            company_id=company_id, role_codes=["COMPANY_ADMIN", "HR_ADMIN"], branch_ids=[blr]
        )
        assert await _listed(client, both) == {in_blr["id"], in_mum["id"]}
    finally:
        await _done(company_id, admin_id)


async def test_reporting_manager_without_a_branch_role_sees_only_their_reports(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        (blr,) = await _setup_branches(company_id=company_id, count=1)
        manager = await _at_branch(client, headers, company_id, "Manager", None)
        report = await _at_branch(client, headers, company_id, "Report", None)
        stranger = await _at_branch(client, headers, company_id, "Stranger", blr)
        await _assign_manager(
            company_id=company_id,
            employee_id=UUID(report["id"]),
            reporting_manager_id=UUID(manager["id"]),
            branch_id=None,
        )
        actor, _ = await _restricted_actor(
            company_id=company_id,
            role_codes=["REPORTING_MANAGER"],
            branch_ids=[blr],  # the list is ignored without a branch role
            employee_id=UUID(manager["id"]),
        )
        # A reporting manager has no list permission; single reads show the scope.
        assert await _status(client, actor, report) == 200
        assert await _status(client, actor, stranger) == 404
    finally:
        await _done(company_id, admin_id)


async def test_reporting_manager_plus_branch_manager_sees_the_union(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        blr, mum = await _setup_branches(company_id=company_id, count=2)
        manager = await _at_branch(client, headers, company_id, "Manager", mum)
        report = await _at_branch(client, headers, company_id, "Report", None)
        in_blr = await _at_branch(client, headers, company_id, "InBengaluru", blr)
        await _at_branch(client, headers, company_id, "InMumbaiOther", mum)
        await _assign_manager(
            company_id=company_id,
            employee_id=UUID(report["id"]),
            reporting_manager_id=UUID(manager["id"]),
            branch_id=blr,  # a report placed at the assigned branch is both: still one entry
        )
        actor, _ = await _restricted_actor(
            company_id=company_id,
            role_codes=["REPORTING_MANAGER", "BRANCH_MANAGER"],
            branch_ids=[blr],
            employee_id=UUID(manager["id"]),
        )
        # Assigned branch (Bengaluru: in_blr and the report) plus the reporting tree (the report).
        assert await _listed(client, actor) == {in_blr["id"], report["id"]}
    finally:
        await _done(company_id, admin_id)


async def test_resolve_data_scope_narrows_only_the_restricted_roles(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, admin_id = await _register_tenant(client)
    try:
        (blr,) = await _setup_branches(company_id=company_id, count=1)
        _, hr_id = await _restricted_actor(
            company_id=company_id, role_codes=["HR_ADMIN"], branch_ids=[blr]
        )
        _, bm_id = await _restricted_actor(
            company_id=company_id, role_codes=["BRANCH_MANAGER"], branch_ids=[blr]
        )
        _, both_id = await _restricted_actor(
            company_id=company_id, role_codes=["COMPANY_ADMIN", "HR_ADMIN"], branch_ids=[blr]
        )
        _, custom_id = await _create_scoped_actor(
            company_id=company_id,
            role_grants=[[(LEAVE_APPLICATION_APPROVE, "COMPANY")]],
            employee_id=None,
        )
        factory = get_session_factory()
        async with factory() as session:
            rbac = RbacService(session)
            hr = await rbac.resolve_data_scope(hr_id, company_id, LEAVE_APPLICATION_APPROVE)
            bm = await rbac.resolve_data_scope(bm_id, company_id, LEAVE_APPLICATION_APPROVE)
            both = await rbac.resolve_data_scope(both_id, company_id, LEAVE_APPLICATION_APPROVE)
            custom = await rbac.resolve_data_scope(custom_id, company_id, LEAVE_APPLICATION_APPROVE)
            hr_payroll = await rbac.resolve_data_scope(hr_id, company_id, PAYROLL_RUN_VIEW)

        # HR: narrowed, and marked so HR-stage approval accepts it for an assigned branch.
        assert hr.levels == {DataScopeLevel.ASSIGNED_BRANCHES}
        assert hr.branch_ids == {blr} and hr.company_grant_restricted
        # Branch manager: narrowed, but never accepted at the HR stage.
        assert bm.levels == {DataScopeLevel.ASSIGNED_BRANCHES}
        assert bm.branch_ids == {blr} and not bm.company_grant_restricted
        # Company admin wins over the list; a custom role's COMPANY grant is honoured as written.
        assert both.levels == {DataScopeLevel.COMPANY} and not both.branch_ids
        assert custom.levels == {DataScopeLevel.COMPANY} and not custom.company_grant_restricted
        # Payroll is outside the narrowed families until its own branch filtering ships.
        assert hr_payroll.levels == {DataScopeLevel.COMPANY}
    finally:
        await _done(company_id, admin_id)


async def test_union_keeps_the_branch_ids(client: AsyncClient) -> None:
    from hrms.core.rbac.types import DataScope

    b = uuid4()
    narrowed = DataScope(
        levels=frozenset({DataScopeLevel.ASSIGNED_BRANCHES}),
        branch_ids=frozenset({b}),
        company_grant_restricted=True,
    )
    own = DataScope(levels=frozenset({DataScopeLevel.SELF}))
    combined = DataScope.union(own, narrowed)
    assert combined.levels == {DataScopeLevel.SELF, DataScopeLevel.ASSIGNED_BRANCHES}
    assert combined.branch_ids == {b} and combined.company_grant_restricted
