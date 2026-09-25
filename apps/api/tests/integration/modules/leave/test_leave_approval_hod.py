"""Integration tests for Leave's third approval level — `MANAGER_THEN_HOD_THEN_HR`
(LEAVE_DECISION_LOG.md LD-23) — the Department Head stage resolved from the employee's
assignment `department_id` -> `Department.head_employee_id`.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from tests.integration.modules.leave.test_leave_application import (
    _create_branch,
    _create_department,
    _create_designation,
    _create_employee,
    _register_tenant,
    _setup_full,
    _submit,
    _teardown,
)
from tests.integration.modules.organisation.test_registration_flow import _cleanup

pytestmark = pytest.mark.asyncio


async def _assign(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    employee_id: str,
    legal_entity_id: str,
    department_id: str | None,
    reporting_manager_id: str | None,
    effective_from: str = "2024-01-01",
) -> None:
    """Full control over `department_id`/`reporting_manager_id` — unlike
    `_give_employee_a_manager`, both may be independently `None` here so each stage's
    resolution can be tested in isolation."""
    branch = await _create_branch(client, headers, legal_entity_id=legal_entity_id)
    designation = await _create_designation(client, headers, department_id=department_id)
    body: dict[str, Any] = {
        "effective_from": effective_from,
        "change_type": "INITIAL",
        "branch_id": branch["id"],
        "designation_id": designation["id"],
    }
    if department_id is not None:
        body["department_id"] = department_id
    if reporting_manager_id is not None:
        body["reporting_manager_id"] = reporting_manager_id
    response = await client.post(
        f"/v1/employees/{employee_id}/assignments", headers=headers, json=body
    )
    assert response.status_code == 201, response.text


async def test_manager_then_hod_then_hr_neither_resolves_falls_back_to_hr(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """No assignment at all -> neither manager nor department head resolves -> single HR
    stage, same fallback LD-05 already established for the two-stage chain."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, approval_chain="MANAGER_THEN_HOD_THEN_HR")
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]

        submitted = await _submit(
            client, headers, employee_id=employee_id, leave_type_id=leave_type_id
        )
        assert submitted.status_code == 201, submitted.text
        data = submitted.json()["data"]
        assert data["approval_stage"] == "HR"
        assert data["resolved_approver_manager_id"] is None
        assert data["resolved_department_head_id"] is None

        approved = await client.post(
            f"/v1/leave-applications/{data['id']}/approve",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["data"]["status"] == "APPROVED"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_manager_then_hod_then_hr_skips_hod_when_no_department_head(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Manager resolves, but the department has no `head_employee_id` set -> HOD is dropped
    from this application's effective sequence, starting stage is MANAGER."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, approval_chain="MANAGER_THEN_HOD_THEN_HR")
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]

        manager = await _create_employee(client, headers, first_name="Manoj")
        department = await _create_department(client, headers)
        await _assign(
            client,
            headers,
            employee_id=employee_id,
            legal_entity_id=ctx["legal_entity"]["id"],
            department_id=department["id"],
            reporting_manager_id=manager["id"],
        )

        submitted = await _submit(
            client, headers, employee_id=employee_id, leave_type_id=leave_type_id
        )
        assert submitted.status_code == 201, submitted.text
        data = submitted.json()["data"]
        assert data["approval_stage"] == "MANAGER"
        assert data["resolved_approver_manager_id"] == manager["id"]
        assert data["resolved_department_head_id"] is None
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_manager_then_hod_then_hr_skips_manager_when_unresolved(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Department head resolves, but no manager is on record -> MANAGER is dropped, starting
    stage is HOD directly (not HR — HOD is still a valid reviewer for this application)."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, approval_chain="MANAGER_THEN_HOD_THEN_HR")
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]

        head = await _create_employee(client, headers, first_name="Heena")
        department = await _create_department(client, headers, head_employee_id=head["id"])
        await _assign(
            client,
            headers,
            employee_id=employee_id,
            legal_entity_id=ctx["legal_entity"]["id"],
            department_id=department["id"],
            reporting_manager_id=None,
        )

        submitted = await _submit(
            client, headers, employee_id=employee_id, leave_type_id=leave_type_id
        )
        assert submitted.status_code == 201, submitted.text
        data = submitted.json()["data"]
        assert data["approval_stage"] == "HOD"
        assert data["resolved_approver_manager_id"] is None
        assert data["resolved_department_head_id"] == head["id"]

        # Wrong-identity caller (company admin, no linked employee) must be rejected at the
        # HOD stage exactly like the MANAGER stage already is.
        mismatched = await client.post(
            f"/v1/leave-applications/{data['id']}/approve",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert mismatched.status_code == 403, mismatched.text
        assert mismatched.json()["error"]["code"] == "LEAVE_APPLICATION_APPROVER_MISMATCH"
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_manager_then_hod_then_hr_all_three_stages_resolve(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Both manager and department head resolve -> the full nominal three-stage sequence
    applies, starting at MANAGER."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, approval_chain="MANAGER_THEN_HOD_THEN_HR")
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]

        manager = await _create_employee(client, headers, first_name="Manoj")
        head = await _create_employee(client, headers, first_name="Heena")
        department = await _create_department(client, headers, head_employee_id=head["id"])
        await _assign(
            client,
            headers,
            employee_id=employee_id,
            legal_entity_id=ctx["legal_entity"]["id"],
            department_id=department["id"],
            reporting_manager_id=manager["id"],
        )

        submitted = await _submit(
            client, headers, employee_id=employee_id, leave_type_id=leave_type_id
        )
        assert submitted.status_code == 201, submitted.text
        data = submitted.json()["data"]
        assert data["approval_stage"] == "MANAGER"
        assert data["resolved_approver_manager_id"] == manager["id"]
        assert data["resolved_department_head_id"] == head["id"]
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_manager_then_hod_then_hr_self_head_loop_falls_back_to_hr(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """LD-23 decision 4 — the applicant is their own department's head. Without the guard this
    would resolve `resolved_department_head_id` to the employee's own id and (with no manager
    on record) leave the application permanently stuck at a stage only the applicant could act
    on, but self-approval is always blocked. It must instead be treated as unresolved and fall
    through to HR."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, approval_chain="MANAGER_THEN_HOD_THEN_HR")
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]

        department = await _create_department(client, headers, head_employee_id=employee_id)
        await _assign(
            client,
            headers,
            employee_id=employee_id,
            legal_entity_id=ctx["legal_entity"]["id"],
            department_id=department["id"],
            reporting_manager_id=None,
        )

        submitted = await _submit(
            client, headers, employee_id=employee_id, leave_type_id=leave_type_id
        )
        assert submitted.status_code == 201, submitted.text
        data = submitted.json()["data"]
        assert data["approval_stage"] == "HR"
        assert data["resolved_department_head_id"] is None

        approved = await client.post(
            f"/v1/leave-applications/{data['id']}/approve",
            headers={**headers, "If-Match": "1"},
            json={},
        )
        assert approved.status_code == 200, approved.text
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
