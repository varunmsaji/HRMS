"""HR-stage approval for an HR assigned to branches (`user_branch_access`).

A genuine company-wide grant approves anyone. An `HR_ADMIN` without `COMPANY_ADMIN` approves only an
employee currently placed at one of their assigned branches; a `BRANCH_MANAGER` never clears the HR
stage. The attendance HR stage (regularisation and overtime) shares the same helper and is checked
directly below.
"""

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from tests.integration.modules.employee.test_assigned_branches_scope import (
    _cleanup_access,
    _restricted_actor,
)
from tests.integration.modules.employee.test_employee_data_scope import (
    _assign_manager,
    _cleanup_scoped_actors,
    _setup_branches,
)
from tests.integration.modules.leave.test_leave_application import (
    _register_tenant,
    _setup_full,
    _submit,
    _teardown,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.core.db.session import get_session_factory
from hrms.core.rbac.types import DataScope, DataScopeLevel
from hrms.modules.attendance.service import _hr_stage_allowed

pytestmark = pytest.mark.asyncio


async def _submitted_at_hr_stage(
    client: AsyncClient, headers: dict[str, str], company_id: UUID, branch_id: UUID
) -> str:
    ctx = await _setup_full(client, headers, approval_chain="MANAGER_THEN_HOD_THEN_HR")
    employee_id = ctx["employee"]["id"]
    await _assign_manager(
        company_id=company_id,
        employee_id=UUID(employee_id),
        reporting_manager_id=None,
        branch_id=branch_id,
    )
    submitted = await _submit(
        client, headers, employee_id=employee_id, leave_type_id=ctx["leave_type"]["id"]
    )
    assert submitted.status_code == 201, submitted.text
    assert submitted.json()["data"]["approval_stage"] == "HR"
    return str(submitted.json()["data"]["id"])


async def _approve(client: AsyncClient, actor: dict[str, str], application_id: str):  # type: ignore[no-untyped-def]
    return await client.post(
        f"/v1/leave-applications/{application_id}/approve",
        headers={**actor, "If-Match": "1"},
        json={},
    )


async def _done(company_id: UUID, user_id: UUID | None) -> None:
    await _cleanup_access(company_id)
    await _teardown(company_id=company_id)
    await _cleanup(company_id=company_id, user_id=user_id)
    await _cleanup_scoped_actors()


async def test_branch_hr_approves_the_hr_stage_only_for_an_assigned_branch(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        blr, mum = await _setup_branches(company_id=company_id, count=2)
        application = await _submitted_at_hr_stage(client, headers, company_id, blr)
        hr_mum, _ = await _restricted_actor(
            company_id=company_id, role_codes=["HR_ADMIN"], branch_ids=[mum]
        )
        hr_blr, _ = await _restricted_actor(
            company_id=company_id, role_codes=["HR_ADMIN"], branch_ids=[blr]
        )

        refused = await _approve(client, hr_mum, application)
        assert refused.status_code in (403, 404), refused.text
        # The refused attempt changed nothing: it is still waiting at the HR stage.
        approved = await _approve(client, hr_blr, application)
        assert approved.status_code == 200, approved.text
        assert approved.json()["data"]["status"] == "APPROVED"
    finally:
        await _done(company_id, user_id)


async def test_branch_manager_never_clears_the_hr_stage(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        (blr,) = await _setup_branches(company_id=company_id, count=1)
        application = await _submitted_at_hr_stage(client, headers, company_id, blr)
        bm, _ = await _restricted_actor(
            company_id=company_id, role_codes=["BRANCH_MANAGER"], branch_ids=[blr]
        )
        refused = await _approve(client, bm, application)
        assert refused.status_code in (403, 404), refused.text
    finally:
        await _done(company_id, user_id)


async def test_hr_stage_helper_matrix_for_attendance_requests(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The regularisation and overtime HR stages call this one helper."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        blr, mum = await _setup_branches(company_id=company_id, count=2)
        ctx = await _setup_full(client, headers)
        employee = UUID(ctx["employee"]["id"])
        await _assign_manager(
            company_id=company_id, employee_id=employee, reporting_manager_id=None, branch_id=blr
        )
        no_branch = uuid4()  # an employee id with no current assignment at all

        def narrowed(*branches: UUID, hr: bool = True) -> DataScope:
            return DataScope(
                levels=frozenset({DataScopeLevel.ASSIGNED_BRANCHES}),
                branch_ids=frozenset(branches),
                company_grant_restricted=hr,
            )

        company = DataScope(levels=frozenset({DataScopeLevel.COMPANY}))
        factory = get_session_factory()
        async with factory() as session:
            assert await _hr_stage_allowed(session, company_id, employee, company)
            assert await _hr_stage_allowed(session, company_id, employee, narrowed(blr, mum))
            assert not await _hr_stage_allowed(session, company_id, employee, narrowed(mum))
            assert not await _hr_stage_allowed(session, company_id, employee, narrowed())
            assert not await _hr_stage_allowed(session, company_id, no_branch, narrowed(blr))
            assert not await _hr_stage_allowed(
                session,
                company_id,
                employee,
                narrowed(blr, hr=False),  # branch manager
            )
    finally:
        await _done(company_id, user_id)
