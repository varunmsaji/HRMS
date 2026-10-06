"""Decision 13 - HR reassigns a stuck approval stage.

Only a pending MANAGER/HOD stage whose current approver can no longer act (not employed today, or
no active login with the approve grant) can be reassigned, by a holder of the company-wide
`LEAVE.APPLICATION_REASSIGN` grant, to an approver who satisfies the same eligibility rules, with a
mandatory reason, under the normal `If-Match` version check. Dates, balance and ledger do not move.
"""

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.test_attendance_edge_cases import _terminate
from tests.integration.modules.attendance.test_attendance_security import (
    _cleanup_scoped_users,
    _create_permission_scoped_user,
)
from tests.integration.modules.leave.test_leave_application import (
    _create_employee,
    _create_employment,
    _get_balance,
    _give_employee_a_manager,
    _register_tenant,
    _setup_full,
    _submit,
    _teardown,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.leave.permissions import (
    LEAVE_APPLICATION_APPROVE,
    LEAVE_APPLICATION_REASSIGN,
    LEAVE_APPLICATION_SUBMIT,
)

pytestmark = pytest.mark.asyncio

_SECRET = "knee surgery SECRET-REASON"


async def _approver(
    client: AsyncClient,
    headers: dict[str, str],
    company_id: UUID,
    legal_entity_id: str,
    name: str,
) -> tuple[dict[str, Any], dict[str, str], UUID]:
    """An employee with an employment, a login linked to them, and the approve grant."""
    employee = await _create_employee(client, headers, first_name=name)
    await _create_employment(
        client, headers, employee_id=employee["id"], legal_entity_id=legal_entity_id
    )
    approver_headers, user_id = await _create_permission_scoped_user(
        company_id=company_id,
        permission_codes=[LEAVE_APPLICATION_APPROVE],
        data_scope="REPORTEE_TREE",
        caller_employee_id=UUID(employee["id"]),
    )
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        await session.execute(
            text("UPDATE employee SET user_id = :u WHERE id = CAST(:e AS uuid)"),
            {"u": user_id, "e": employee["id"]},
        )
        await session.commit()
    return employee, approver_headers, user_id


async def _scene(client: AsyncClient) -> dict[str, Any]:
    headers, company_id, admin_id = await _register_tenant(client)
    ctx = await _setup_full(client, headers, approval_chain="MANAGER", balance="20.00")
    legal_entity_id = ctx["legal_entity"]["id"]
    manager, manager_headers, manager_user = await _approver(
        client, headers, company_id, legal_entity_id, "Manoj"
    )
    replacement, replacement_headers, _ = await _approver(
        client, headers, company_id, legal_entity_id, "Rita"
    )
    await _give_employee_a_manager(
        client,
        headers,
        employee_id=ctx["employee"]["id"],
        manager_employee_id=manager["id"],
        legal_entity_id=legal_entity_id,
    )
    hr_headers, _ = await _create_permission_scoped_user(
        company_id=company_id, permission_codes=[LEAVE_APPLICATION_REASSIGN], data_scope="COMPANY"
    )
    submitted = await _submit(
        client,
        headers,
        employee_id=ctx["employee"]["id"],
        leave_type_id=ctx["leave_type"]["id"],
        reason=_SECRET,
    )
    assert submitted.status_code == 201, submitted.text
    application = submitted.json()["data"]
    assert application["approval_stage"] == "MANAGER"
    assert application["resolved_approver_manager_id"] == manager["id"]
    return {
        "headers": headers,
        "company_id": company_id,
        "admin_id": admin_id,
        "ctx": ctx,
        "manager": manager,
        "manager_headers": manager_headers,
        "manager_user": manager_user,
        "replacement": replacement,
        "replacement_headers": replacement_headers,
        "hr_headers": hr_headers,
        "application": application,
    }


async def _finish(scene: dict[str, Any]) -> None:
    await _teardown(company_id=scene["company_id"])
    await _cleanup(company_id=scene["company_id"], user_id=scene["admin_id"])
    await _cleanup_scoped_users()


async def _reassign(
    client: AsyncClient,
    headers: dict[str, str],
    application: dict[str, Any],
    new_approver_id: str,
    *,
    reason: str | None = "Approver left the company",
    version: int | None = None,
) -> Any:
    body: dict[str, Any] = {"new_approver_employee_id": new_approver_id}
    if reason is not None:
        body["reason"] = reason
    return await client.post(
        f"/v1/leave-applications/{application['id']}/reassign-approver",
        headers={**headers, "If-Match": str(version or application["version"])},
        json=body,
    )


async def _approve(
    client: AsyncClient, headers: dict[str, str], application_id: str, v: int
) -> Any:
    return await client.post(
        f"/v1/leave-applications/{application_id}/approve",
        headers={**headers, "If-Match": str(v)},
        json={},
    )


async def _ledger_count(company_id: UUID, employee_id: str) -> int:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        row = await session.execute(
            text(
                "SELECT count(*) FROM leave_ledger WHERE company_id = CAST(:c AS uuid) "
                "AND employee_id = CAST(:e AS uuid)"
            ),
            {"c": str(company_id), "e": employee_id},
        )
        return int(row.scalar_one())


async def test_terminated_approver_is_replaced_and_only_the_new_approver_can_act(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    scene = await _scene(client)
    try:
        application = scene["application"]
        employee_id = scene["ctx"]["employee"]["id"]
        await _terminate(client, scene["headers"], scene["manager"]["id"], "2026-10-01")
        ledger_before = await _ledger_count(scene["company_id"], employee_id)

        response = await _reassign(
            client, scene["hr_headers"], application, scene["replacement"]["id"]
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["resolved_approver_manager_id"] == scene["replacement"]["id"]
        assert data["status"] == "SUBMITTED" and data["approval_stage"] == "MANAGER"
        assert data["version"] == application["version"] + 1
        # nothing about the leave itself moved
        assert (data["start_date"], data["end_date"], data["total_days"]) == (
            application["start_date"],
            application["end_date"],
            application["total_days"],
        )
        assert [d["calendar_date"] for d in data["days"]] == [
            d["calendar_date"] for d in application["days"]
        ]
        assert await _ledger_count(scene["company_id"], employee_id) == ledger_before
        assert await _get_balance(client, scene["headers"], employee_id) == "20.00"
        # the timeline records who did what and why
        entry = data["actions"][-1]
        assert entry["action"] == "APPROVER_REASSIGNED"
        assert entry["stage"] == "MANAGER"
        assert entry["comment"] == "Approver left the company"

        # the old approver can no longer act; the new one can, and then the leave is approved
        old = await _approve(client, scene["manager_headers"], application["id"], data["version"])
        # terminating the employment also ends the old approver's session (401); an approver who
        # still has a session is refused by the stage identity check (403)
        assert old.status_code in (401, 403), old.text
        new = await _approve(
            client, scene["replacement_headers"], application["id"], data["version"]
        )
        assert new.status_code == 200, new.text
        assert new.json()["data"]["status"] == "APPROVED"
        assert await _get_balance(client, scene["headers"], employee_id) == "19.00"
    finally:
        await _finish(scene)


async def test_deactivated_approver_can_be_replaced(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    scene = await _scene(client)
    try:
        # employment still active, but the login's membership is switched off
        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(scene["company_id"]))
            await session.execute(
                text("UPDATE user_company SET status = 'INACTIVE' WHERE user_id = :u"),
                {"u": scene["manager_user"]},
            )
            await session.commit()
        response = await _reassign(
            client, scene["hr_headers"], scene["application"], scene["replacement"]["id"]
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["resolved_approver_manager_id"] == scene["replacement"]["id"]
    finally:
        await _finish(scene)


async def test_an_eligible_current_approver_cannot_be_replaced(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    scene = await _scene(client)
    try:
        response = await _reassign(
            client, scene["hr_headers"], scene["application"], scene["replacement"]["id"]
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "LEAVE_APPROVER_STILL_ELIGIBLE"
    finally:
        await _finish(scene)


async def test_only_a_company_wide_reassign_grant_may_reassign(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    scene = await _scene(client)
    try:
        await _terminate(client, scene["headers"], scene["manager"]["id"], "2026-10-01")
        application, target = scene["application"], scene["replacement"]["id"]
        # the proposed new approver themself, an employee, and a scoped (non-company) grant
        employee_headers, _ = await _create_permission_scoped_user(
            company_id=scene["company_id"],
            permission_codes=[LEAVE_APPLICATION_SUBMIT],
            data_scope="SELF",
        )
        scoped_hr_headers, _ = await _create_permission_scoped_user(
            company_id=scene["company_id"],
            permission_codes=[LEAVE_APPLICATION_REASSIGN],
            data_scope="REPORTEE_TREE",
        )
        for headers in (scene["replacement_headers"], employee_headers, scoped_hr_headers):
            refused = await _reassign(client, headers, application, target)
            assert refused.status_code == 403, refused.text
        # unchanged
        fetched = await client.get(
            f"/v1/leave-applications/{application['id']}", headers=scene["headers"]
        )
        assert fetched.json()["data"]["resolved_approver_manager_id"] == scene["manager"]["id"]
        assert fetched.json()["data"]["version"] == application["version"]
    finally:
        await _finish(scene)


async def test_a_stale_version_gets_the_normal_conflict(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    scene = await _scene(client)
    try:
        await _terminate(client, scene["headers"], scene["manager"]["id"], "2026-10-01")
        application = scene["application"]
        first = await _reassign(
            client, scene["hr_headers"], application, scene["replacement"]["id"]
        )
        assert first.status_code == 200, first.text
        # a second HR user still holding the pre-reassignment version
        stale = await _reassign(
            client,
            scene["hr_headers"],
            application,
            scene["replacement"]["id"],
            version=application["version"],
        )
        assert stale.status_code == 409, stale.text
        assert stale.json()["error"]["code"] == "STALE_RESOURCE"
    finally:
        await _finish(scene)


async def test_the_new_approver_must_be_eligible_and_a_reason_is_mandatory(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    scene = await _scene(client)
    try:
        await _terminate(client, scene["headers"], scene["manager"]["id"], "2026-10-01")
        application = scene["application"]
        headers = scene["headers"]

        # no login at all
        nobody = await _create_employee(client, headers, first_name="Nobody")
        await _create_employment(
            client,
            headers,
            employee_id=nobody["id"],
            legal_entity_id=scene["ctx"]["legal_entity"]["id"],
        )
        refused = await _reassign(client, scene["hr_headers"], application, nobody["id"])
        assert refused.status_code == 422, refused.text
        assert refused.json()["error"]["code"] == "LEAVE_REASSIGN_APPROVER_NOT_ELIGIBLE"
        assert refused.json()["error"]["details"][0]["code"] == "APPROVER_HAS_NO_LOGIN"

        # proposing the approver who is already assigned changes nothing
        gone = await _reassign(client, scene["hr_headers"], application, scene["manager"]["id"])
        assert gone.status_code == 422
        assert gone.json()["error"]["details"][0]["code"] == "APPROVER_UNCHANGED"

        # not an employee of this company at all
        unknown = await _reassign(
            client, scene["hr_headers"], application, "00000000-0000-4000-8000-000000000001"
        )
        assert unknown.status_code == 422
        assert unknown.json()["error"]["details"][0]["code"] == "APPROVER_NOT_FOUND"

        # the applicant cannot approve their own leave
        own = await _reassign(
            client, scene["hr_headers"], application, scene["ctx"]["employee"]["id"]
        )
        assert own.status_code == 403
        assert own.json()["error"]["code"] == "LEAVE_APPLICATION_SELF_APPROVAL_NOT_ALLOWED"

        # reason is mandatory
        for reason in (None, "", "   "):
            missing = await _reassign(
                client, scene["hr_headers"], application, scene["replacement"]["id"], reason=reason
            )
            assert missing.status_code == 422, (reason, missing.text)
    finally:
        await _finish(scene)


async def test_only_a_pending_manager_or_hod_stage_can_be_reassigned(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    scene = await _scene(client)
    try:
        await _terminate(client, scene["headers"], scene["manager"]["id"], "2026-10-01")
        application = scene["application"]
        # a finished application has no stage to hand over
        withdrawn = await client.post(
            f"/v1/leave-applications/{application['id']}/cancel",
            headers={**scene["headers"], "If-Match": str(application["version"])},
            json={"reason": "no longer needed"},
        )
        assert withdrawn.status_code == 200, withdrawn.text
        response = await _reassign(
            client,
            scene["hr_headers"],
            withdrawn.json()["data"],
            scene["replacement"]["id"],
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "LEAVE_APPROVER_REASSIGN_NOT_APPLICABLE"
    finally:
        await _finish(scene)


async def test_reassignment_writes_a_structured_audit_entry_without_free_text(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    scene = await _scene(client)
    try:
        await _terminate(client, scene["headers"], scene["manager"]["id"], "2026-10-01")
        application = scene["application"]
        response = await _reassign(
            client,
            scene["hr_headers"],
            application,
            scene["replacement"]["id"],
            reason="Manager exited; routing to Rita",
        )
        assert response.status_code == 200, response.text
        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(scene["company_id"]))
            rows = (
                await session.execute(
                    text(
                        "SELECT action, before_json, after_json, actor_user_id, request_id "
                        "FROM audit_log WHERE entity_id = CAST(:a AS uuid) "
                        "AND action = 'LEAVE_APPLICATION_APPROVER_REASSIGNED'"
                    ),
                    {"a": application["id"]},
                )
            ).all()
        assert len(rows) == 1
        _action, before, after, actor, request_id = rows[0]
        assert before["stage"] == after["stage"] == "MANAGER"
        assert before["approver_employee_id"] == scene["manager"]["id"]
        assert after["approver_employee_id"] == scene["replacement"]["id"]
        assert before["version"] + 1 == after["version"]
        assert actor is not None and request_id
        # nothing free-text, not even the HR reason or the employee's own leave reason
        dumped = f"{before} {after}"
        assert "Manager exited" not in dumped
        assert _SECRET not in dumped
    finally:
        await _finish(scene)
