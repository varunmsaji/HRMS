"""HR-stage notifications reach only the people who can act on the request.

A request from an employee in Bengaluru tells the Bengaluru HR and anyone with company-wide
approval, and not an HR limited to Mumbai: they could not open it. An employee with no branch is
reachable only by company-wide approvers, matching what the approval endpoints allow."""

from uuid import UUID

import pytest
from httpx import AsyncClient
from tests.integration.branch_access_support import place_at_one_branch
from tests.integration.modules.employee.test_assigned_branches_scope import (
    _cleanup_access,
    _restricted_actor,
)
from tests.integration.modules.employee.test_employee_data_scope import (
    _cleanup_scoped_actors,
    _setup_branches,
)
from tests.integration.modules.leave.test_leave_application import (
    _create_employee,
    _register_tenant,
    _setup_full,
    _submit,
    _teardown,
)
from tests.integration.modules.leave.test_leave_notifications import (
    _drop_users,
    _feed,
    _login_for,
)
from tests.integration.modules.onboarding.test_onboarding_branch_scope import _delete_branches
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.modules.leave.permissions import LEAVE_APPLICATION_APPROVE

pytestmark = pytest.mark.asyncio


async def _awaiting(client: AsyncClient, headers: dict[str, str]) -> list[dict]:
    return [n for n in await _feed(client, headers) if n["type"] == "LEAVE_APPROVAL_REQUESTED"]


async def _done(company_id: UUID, admin_user: UUID | None, created: list[UUID]) -> None:
    await _teardown(company_id=company_id)
    await _cleanup_access(company_id)
    await _delete_branches(company_id)
    await _cleanup(company_id=company_id, user_id=admin_user)
    await _drop_users(company_id, created)
    await _cleanup_scoped_actors()


async def test_request_in_one_branch_notifies_that_branchs_hr_and_company_wide_approvers(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    admin, company_id, admin_user = await _register_tenant(client)
    created: list[UUID] = []
    try:
        ctx = await _setup_full(client, admin, approval_chain="HR")
        employee_id = ctx["employee"]["id"]
        bengaluru = await place_at_one_branch(company_id, [UUID(employee_id)])
        (mumbai,) = await _setup_branches(company_id=company_id, count=1)

        hr_bengaluru, _ = await _restricted_actor(
            company_id=company_id, role_codes=["HR_ADMIN"], branch_ids=[bengaluru]
        )
        hr_mumbai, _ = await _restricted_actor(
            company_id=company_id, role_codes=["HR_ADMIN"], branch_ids=[mumbai]
        )
        approver_person = await _create_employee(client, admin, first_name="Harini")
        approver, approver_user = await _login_for(
            company_id, approver_person["id"], [LEAVE_APPLICATION_APPROVE], "COMPANY"
        )
        created.append(approver_user)

        submitted = await _submit(
            client, admin, employee_id=employee_id, leave_type_id=ctx["leave_type"]["id"]
        )
        assert submitted.status_code == 201, submitted.text

        assert len(await _awaiting(client, hr_bengaluru)) == 1
        assert len(await _awaiting(client, approver)) == 1
        assert await _awaiting(client, hr_mumbai) == []
    finally:
        await _done(company_id, admin_user, created)


async def test_employee_with_no_branch_notifies_company_wide_approvers_only(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    admin, company_id, admin_user = await _register_tenant(client)
    created: list[UUID] = []
    try:
        ctx = await _setup_full(client, admin, approval_chain="HR")
        (branch,) = await _setup_branches(company_id=company_id, count=1)
        hr, _ = await _restricted_actor(
            company_id=company_id, role_codes=["HR_ADMIN"], branch_ids=[branch]
        )
        approver_person = await _create_employee(client, admin, first_name="Harini")
        approver, approver_user = await _login_for(
            company_id, approver_person["id"], [LEAVE_APPLICATION_APPROVE], "COMPANY"
        )
        created.append(approver_user)

        submitted = await _submit(
            client, admin, employee_id=ctx["employee"]["id"], leave_type_id=ctx["leave_type"]["id"]
        )
        assert submitted.status_code == 201, submitted.text

        assert len(await _awaiting(client, approver)) == 1
        assert await _awaiting(client, hr) == []
    finally:
        await _done(company_id, admin_user, created)
