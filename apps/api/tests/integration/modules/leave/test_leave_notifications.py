"""In-app notifications produced by the leave approval workflow: the reviewer of the current stage
is told a request is waiting, the employee is told the outcome, the person acting is never
notified about their own action, and a notification problem never fails the leave itself."""

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.test_attendance_security import (
    _create_permission_scoped_user,
)
from tests.integration.modules.leave.test_leave_application import (
    _create_employee,
    _give_employee_a_manager,
    _register_tenant,
    _setup_full,
    _submit,
    _teardown,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.leave.permissions import LEAVE_APPLICATION_APPROVE, LEAVE_APPLICATION_SUBMIT
from hrms.modules.notification.service import NotificationService

pytestmark = pytest.mark.asyncio


async def _login_for(
    company_id: UUID, employee_id: str, codes: list[str], scope: str
) -> tuple[dict[str, str], UUID]:
    """A login linked to `employee_id`, holding `codes` at `scope`."""
    headers, user_id = await _create_permission_scoped_user(
        company_id=company_id,
        permission_codes=codes,
        data_scope=scope,
        caller_employee_id=UUID(employee_id),
    )
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        await session.execute(
            text("UPDATE employee SET user_id = :u WHERE id = :e AND company_id = :c"),
            {"u": user_id, "e": employee_id, "c": company_id},
        )
        await session.commit()
    return headers, user_id


async def _feed(client: AsyncClient, headers: dict[str, str]) -> list[dict[str, Any]]:
    response = await client.get("/v1/notifications", headers=headers)
    assert response.status_code == 200, response.text
    return list(response.json()["data"])


async def _unread(client: AsyncClient, headers: dict[str, str]) -> int:
    response = await client.get("/v1/notifications/unread-count", headers=headers)
    assert response.status_code == 200, response.text
    return int(response.json()["data"]["unread_count"])


async def _drop_users(company_id: UUID, user_ids: list[UUID]) -> None:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        await session.execute(
            text("UPDATE employee SET user_id = NULL WHERE company_id = :c"), {"c": company_id}
        )
        await session.execute(
            text("DELETE FROM session WHERE user_id = ANY(:ids)"), {"ids": user_ids}
        )
        await session.execute(text('DELETE FROM "user" WHERE id = ANY(:ids)'), {"ids": user_ids})
        await session.commit()


async def test_hr_stage_reviewers_are_asked_and_the_employee_hears_the_outcome(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    admin, company_id, admin_user = await _register_tenant(client)
    created: list[UUID] = []
    try:
        ctx = await _setup_full(client, admin, approval_chain="HR")
        employee_id = ctx["employee"]["id"]
        employee, employee_user = await _login_for(
            company_id, employee_id, [LEAVE_APPLICATION_SUBMIT], "SELF"
        )
        hr_person = await _create_employee(client, admin, first_name="Harini")
        hr, hr_user = await _login_for(
            company_id, hr_person["id"], [LEAVE_APPLICATION_APPROVE], "COMPANY"
        )
        created += [employee_user, hr_user]

        submitted = await _submit(
            client, admin, employee_id=employee_id, leave_type_id=ctx["leave_type"]["id"]
        )
        assert submitted.status_code == 201, submitted.text
        application_id = submitted.json()["data"]["id"]

        [waiting] = await _feed(client, hr)
        assert waiting["type"] == "LEAVE_APPROVAL_REQUESTED"
        assert waiting["priority"] == "HIGH"
        assert waiting["title"] == "Leave request awaiting your approval"
        assert waiting["body"] == "Priya: 1 day of leave on 8 Sep 2026."
        assert waiting["action_url"] == f"/app/leave-applications/{application_id}"
        assert waiting["entity_id"] == application_id
        # The submitter (the admin) is never told about their own action, and the employee the
        # request is about is never asked to review it.
        assert await _feed(client, admin) == []
        assert await _feed(client, employee) == []

        approved = await client.post(
            f"/v1/leave-applications/{application_id}/approve",
            headers={**admin, "If-Match": "1"},
            json={},
        )
        assert approved.status_code == 200, approved.text

        [outcome] = await _feed(client, employee)
        assert outcome["type"] == "LEAVE_DECIDED"
        assert outcome["title"] == "Your leave request was approved"
        assert outcome["action_url"] == f"/app/leave-applications/{application_id}"
        # The request no longer needs HR: their call to action is settled, not left unread.
        assert await _unread(client, hr) == 0
        assert (await _feed(client, hr))[0]["is_read"] is True
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=admin_user)
        await _drop_users(company_id, created)


async def test_manager_stage_goes_to_the_manager_only(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    admin, company_id, admin_user = await _register_tenant(client)
    created: list[UUID] = []
    try:
        ctx = await _setup_full(client, admin, approval_chain="MANAGER")
        employee_id = ctx["employee"]["id"]
        manager_row = await _create_employee(client, admin, first_name="Manoj")
        await _give_employee_a_manager(
            client,
            admin,
            employee_id=employee_id,
            manager_employee_id=manager_row["id"],
            legal_entity_id=ctx["legal_entity"]["id"],
        )
        employee, employee_user = await _login_for(
            company_id, employee_id, [LEAVE_APPLICATION_SUBMIT], "SELF"
        )
        manager, manager_user = await _login_for(
            company_id, manager_row["id"], [LEAVE_APPLICATION_APPROVE], "REPORTEES"
        )
        hr_person = await _create_employee(client, admin, first_name="Harini")
        hr, hr_user = await _login_for(
            company_id, hr_person["id"], [LEAVE_APPLICATION_APPROVE], "COMPANY"
        )
        created += [employee_user, manager_user, hr_user]

        submitted = await _submit(
            client, admin, employee_id=employee_id, leave_type_id=ctx["leave_type"]["id"]
        )
        assert submitted.status_code == 201, submitted.text
        application_id = submitted.json()["data"]["id"]

        [waiting] = await _feed(client, manager)
        assert waiting["type"] == "LEAVE_APPROVAL_REQUESTED"
        assert waiting["metadata"] == {"stage": "MANAGER"}
        assert await _feed(client, hr) == []

        rejected = await client.post(
            f"/v1/leave-applications/{application_id}/reject",
            headers={**manager, "If-Match": "1"},
            json={"rejection_reason": "Team is short that week"},
        )
        assert rejected.status_code == 200, rejected.text

        [outcome] = await _feed(client, employee)
        assert outcome["title"] == "Your leave request was rejected"
        # The manager acted, so they get nothing new, and their request is settled.
        assert await _unread(client, manager) == 0
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=admin_user)
        await _drop_users(company_id, created)


async def test_a_failing_notification_never_fails_the_leave(
    client: AsyncClient, seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("notification store unavailable")

    admin, company_id, admin_user = await _register_tenant(client)
    created: list[UUID] = []
    try:
        ctx = await _setup_full(client, admin, approval_chain="HR")
        hr_person = await _create_employee(client, admin, first_name="Harini")
        hr, hr_user = await _login_for(
            company_id, hr_person["id"], [LEAVE_APPLICATION_APPROVE], "COMPANY"
        )
        created.append(hr_user)
        monkeypatch.setattr(NotificationService, "create_notification", boom)

        submitted = await _submit(
            client, admin, employee_id=ctx["employee"]["id"], leave_type_id=ctx["leave_type"]["id"]
        )
        assert submitted.status_code == 201, submitted.text
        assert submitted.json()["data"]["status"] == "SUBMITTED"
        assert await _feed(client, hr) == []
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=admin_user)
        await _drop_users(company_id, created)
