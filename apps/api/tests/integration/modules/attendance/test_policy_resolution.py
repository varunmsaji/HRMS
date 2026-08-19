"""Integration tests for W3 policy resolution — `/v1/attendance-policy-resolution`.

Reuses the reusable `CalendarResolutionService.resolve_policy_assignment` precedence walk (WD-09)
already exercised for `WORK_CALENDAR` in `test_workforce_calendar.py`'s
`test_calendar_resolution_branch_scope_beats_company` — this file exercises the same machinery
for `ATTENDANCE_POLICY`, confirming EMPLOYEE beats COMPANY and fail-closed when nothing is
assigned (WD-21)."""

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.organisation.test_registration_flow import _cleanup, _register

from hrms.core.db.session import get_session_factory, set_rls_company_id


async def _register_tenant(
    client: AsyncClient, **overrides: Any
) -> tuple[dict[str, str], UUID, UUID | None]:
    response, company_id, user_id = await _register(client, **overrides)
    assert response.status_code == 201, response.text
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


async def _publish_attendance_policy(
    client: AsyncClient, headers: dict[str, str], name: str
) -> dict[str, Any]:
    policy = (
        await client.post("/v1/attendance-policies", headers=headers, json={"name": name})
    ).json()["data"]
    draft = (
        await client.post(
            f"/v1/attendance-policies/{policy['id']}/versions",
            headers=headers,
            json={
                "effective_from": "2026-01-01",
                "hour_bands": [
                    {"min_minutes": 0, "max_minutes": None, "result_status": "PRESENT"}
                ],
            },
        )
    ).json()["data"]
    published = await client.post(
        f"/v1/attendance-policies/{policy['id']}/versions/{draft['id']}/publish",
        headers={**headers, "If-Match": "1"},
        json={},
    )
    assert published.status_code == 200, published.text
    return policy


async def _cleanup_all(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        for table in (
            "employee_assignment",
            "employment",
            "employee",
            "number_series",
            "policy_assignment",
            "attendance_policy_version",
            "attendance_policy",
            "designation",
            "department",
            "branch",
            "legal_entity",
        ):
            await session.execute(
                text(f"DELETE FROM {table} WHERE company_id = :cid"), {"cid": str(company_id)}
            )
        await session.commit()


@pytest.mark.asyncio
async def test_resolution_config_incomplete_without_assignment(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = (
            await client.post("/v1/employees", headers=headers, json={"first_name": "Asha"})
        ).json()["data"]
        response = await client.get(
            "/v1/attendance-policy-resolution",
            headers=headers,
            params={
                "employee_id": employee["id"],
                "date": "2026-08-15",
                "policy_kind": "ATTENDANCE_POLICY",
            },
        )
        assert response.status_code == 200
        assert response.json()["data"]["config_incomplete"] is True
        assert response.json()["data"]["resolved_policy_id"] is None
    finally:
        await _cleanup_all(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_resolution_employee_scope_beats_company_scope(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = (
            await client.post("/v1/employees", headers=headers, json={"first_name": "Asha"})
        ).json()["data"]
        legal_entity = (
            await client.post("/v1/legal-entities", headers=headers, json={"name": "Acme LE"})
        ).json()["data"]
        branch = (
            await client.post(
                "/v1/branches",
                headers=headers,
                json={"legal_entity_id": legal_entity["id"], "name": "HQ"},
            )
        ).json()["data"]
        department = (
            await client.post(
                "/v1/departments",
                headers=headers,
                json={"name": "Engineering", "branch_id": branch["id"]},
            )
        ).json()["data"]
        designation = (
            await client.post(
                "/v1/designations",
                headers=headers,
                json={"title": "Software Engineer", "department_id": department["id"]},
            )
        ).json()["data"]
        await client.post(
            f"/v1/employees/{employee['id']}/employments",
            headers=headers,
            json={"legal_entity_id": legal_entity["id"], "joining_date": "2026-01-01"},
        )
        assignment = await client.post(
            f"/v1/employees/{employee['id']}/assignments",
            headers=headers,
            json={
                "effective_from": "2026-01-01",
                "change_type": "INITIAL",
                "branch_id": branch["id"],
                "department_id": department["id"],
                "designation_id": designation["id"],
            },
        )
        assert assignment.status_code == 201, assignment.text

        company_policy = await _publish_attendance_policy(client, headers, "Company Default")
        employee_policy = await _publish_attendance_policy(client, headers, "Special Case")

        company_assignment = await client.post(
            "/v1/policy-assignments",
            headers=headers,
            json={
                "policy_kind": "ATTENDANCE_POLICY",
                "policy_id": company_policy["id"],
                "scope_type": "COMPANY",
                "effective_from": "2026-01-01",
            },
        )
        assert company_assignment.status_code == 201, company_assignment.text

        # Before the employee-level override: resolves to COMPANY.
        before = await client.get(
            "/v1/attendance-policy-resolution",
            headers=headers,
            params={
                "employee_id": employee["id"],
                "date": "2026-08-15",
                "policy_kind": "ATTENDANCE_POLICY",
            },
        )
        assert before.json()["data"]["resolved_policy_id"] == company_policy["id"]
        assert before.json()["data"]["resolved_through"] == "COMPANY"

        employee_assignment = await client.post(
            "/v1/policy-assignments",
            headers=headers,
            json={
                "policy_kind": "ATTENDANCE_POLICY",
                "policy_id": employee_policy["id"],
                "scope_type": "EMPLOYEE",
                "scope_id": employee["id"],
                "effective_from": "2026-01-01",
            },
        )
        assert employee_assignment.status_code == 201, employee_assignment.text

        after = await client.get(
            "/v1/attendance-policy-resolution",
            headers=headers,
            params={
                "employee_id": employee["id"],
                "date": "2026-08-15",
                "policy_kind": "ATTENDANCE_POLICY",
            },
        )
        data = after.json()["data"]
        assert data["config_incomplete"] is False
        assert data["resolved_policy_id"] == employee_policy["id"]
        assert data["resolved_through"] == "EMPLOYEE"
    finally:
        await _cleanup_all(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_resolution_invalid_policy_kind_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = (
            await client.post("/v1/employees", headers=headers, json={"first_name": "Asha"})
        ).json()["data"]
        response = await client.get(
            "/v1/attendance-policy-resolution",
            headers=headers,
            params={
                "employee_id": employee["id"],
                "date": "2026-08-15",
                "policy_kind": "WORK_CALENDAR",
            },
        )
        assert response.status_code == 422
    finally:
        await _cleanup_all(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
