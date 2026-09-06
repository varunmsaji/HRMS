"""Integration tests for the Department API — Sprint 3 vertical slice.

Covers the `/v1/departments` surface: create, list, get, update, validation (branch
ownership, parent-department ownership, hierarchy cycle/depth rules, mass-assignment),
deactivation/reactivation (no dependency-blocking rule applies this slice — see
docs/modules/department/00_DEPARTMENT_AUDIT.md §5.3), audit records, and not-found
behavior. Tenant isolation and permission-matrix coverage live in the sibling
`test_cross_tenant_isolation.py` / `test_permission_matrix.py` files.
"""

from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from hrms.core.audit.models import AuditLog
from hrms.core.db.session import get_session_factory

from .test_registration_flow import _cleanup, _register


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


async def _create_branch(
    client: AsyncClient, headers: dict[str, str], name: str = "HQ Branch"
) -> str:
    entity = await client.post("/v1/legal-entities", headers=headers, json={"name": "Acme Pvt Ltd"})
    assert entity.status_code == 201
    branch = await client.post(
        "/v1/branches",
        headers=headers,
        json={"legal_entity_id": entity.json()["data"]["id"], "name": name},
    )
    assert branch.status_code == 201
    return str(branch.json()["data"]["id"])


async def _create_department(
    client: AsyncClient, headers: dict[str, str], name: str = "Engineering", **extra: Any
) -> dict[str, Any]:
    response = await client.post("/v1/departments", headers=headers, json={"name": name, **extra})
    assert response.status_code == 201
    return dict(response.json()["data"])


async def _cleanup_departments_and_branches(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("DELETE FROM department WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.execute(
            text("DELETE FROM branch WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.execute(
            text("DELETE FROM employee WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.execute(
            text("DELETE FROM number_series WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.commit()


async def _create_employee(
    client: AsyncClient, headers: dict[str, str], first_name: str = "Priya"
) -> dict[str, Any]:
    response = await client.post("/v1/employees", headers=headers, json={"first_name": first_name})
    assert response.status_code == 201
    return dict(response.json()["data"])


@pytest.mark.asyncio
async def test_list_departments_empty_state(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.get("/v1/departments", headers=headers)
        assert response.status_code == 200
        assert response.json()["data"] == []
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_department_success_without_branch(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.post(
            "/v1/departments", headers=headers, json={"name": "Engineering", "code": "ENG"}
        )
        assert response.status_code == 201
        data = response.json()["data"]
        assert data["name"] == "Engineering"
        assert data["branch_id"] is None
        assert data["parent_id"] is None
        assert data["is_active"] is True
        assert data["version"] == 1
        assert data["company_id"] == str(company_id)

        listed = await client.get("/v1/departments", headers=headers)
        assert len(listed.json()["data"]) == 1

        factory = get_session_factory()
        async with factory() as session:
            audit_rows = (
                (
                    await session.execute(
                        select(AuditLog).where(
                            AuditLog.company_id == company_id,
                            AuditLog.entity_type == "department",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(audit_rows) == 1
            assert audit_rows[0].action == "DEPARTMENT_CREATED"
    finally:
        await _cleanup_departments_and_branches(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_department_with_branch_success(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        branch_id = await _create_branch(client, headers)
        response = await client.post(
            "/v1/departments", headers=headers, json={"name": "Engineering", "branch_id": branch_id}
        )
        assert response.status_code == 201
        assert response.json()["data"]["branch_id"] == branch_id
    finally:
        await _cleanup_departments_and_branches(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_department_invalid_branch_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.post(
            "/v1/departments",
            headers=headers,
            json={"name": "Engineering", "branch_id": str(uuid4())},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_BRANCH"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_department_cross_tenant_branch_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        branch_b = await _create_branch(client, headers_b)

        response = await client.post(
            "/v1/departments",
            headers=headers_a,
            json={"name": "Engineering", "branch_id": branch_b},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_BRANCH"
    finally:
        await _cleanup_departments_and_branches(company_id=company_b)
        await _cleanup(company_id=company_a, user_id=user_a)
        await _cleanup(company_id=company_b, user_id=user_b)


@pytest.mark.asyncio
async def test_create_department_invalid_parent_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.post(
            "/v1/departments", headers=headers, json={"name": "Sub-team", "parent_id": str(uuid4())}
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_PARENT_DEPARTMENT"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_department_cross_tenant_parent_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        parent_b = await _create_department(client, headers_b, name="B Parent")

        response = await client.post(
            "/v1/departments",
            headers=headers_a,
            json={"name": "Sub-team", "parent_id": parent_b["id"]},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_PARENT_DEPARTMENT"
    finally:
        await _cleanup_departments_and_branches(company_id=company_b)
        await _cleanup(company_id=company_a, user_id=user_a)
        await _cleanup(company_id=company_b, user_id=user_b)


@pytest.mark.asyncio
async def test_department_hierarchy_success(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        parent = await _create_department(client, headers, name="Engineering")
        child = await _create_department(client, headers, name="Platform", parent_id=parent["id"])
        assert child["parent_id"] == parent["id"]
    finally:
        await _cleanup_departments_and_branches(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_update_department_self_parent_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        department = await _create_department(client, headers)
        response = await client.patch(
            f"/v1/departments/{department['id']}",
            headers={**headers, "If-Match": str(department["version"])},
            json={"parent_id": department["id"]},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "DEPARTMENT_CYCLE_DETECTED"
    finally:
        await _cleanup_departments_and_branches(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_update_department_ancestor_cycle_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        grandparent = await _create_department(client, headers, name="Grandparent")
        parent = await _create_department(
            client, headers, name="Parent", parent_id=grandparent["id"]
        )
        # Attempting to make `grandparent`'s parent be `parent` would create a cycle
        # (parent is already a descendant of grandparent).
        response = await client.patch(
            f"/v1/departments/{grandparent['id']}",
            headers={**headers, "If-Match": str(grandparent["version"])},
            json={"parent_id": parent["id"]},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "DEPARTMENT_CYCLE_DETECTED"
    finally:
        await _cleanup_departments_and_branches(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_department_hierarchy_max_depth_exceeded(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        current = await _create_department(client, headers, name="Level 1")
        # Levels 2..5 succeed (chain length 5 = max allowed).
        for level in range(2, 6):
            current = await _create_department(
                client, headers, name=f"Level {level}", parent_id=current["id"]
            )
        # Level 6 must be rejected — would exceed max depth of 5.
        response = await client.post(
            "/v1/departments",
            headers=headers,
            json={"name": "Level 6", "parent_id": current["id"]},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "DEPARTMENT_MAX_DEPTH_EXCEEDED"
    finally:
        await _cleanup_departments_and_branches(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_department_missing_name_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.post("/v1/departments", headers=headers, json={})
        assert response.status_code == 422
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_department_mass_assignment_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.post(
            "/v1/departments",
            headers=headers,
            json={"name": "Engineering", "is_active": False, "version": 99},
        )
        assert response.status_code == 422
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_update_department_mass_assignment_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        department = await _create_department(client, headers)
        response = await client.patch(
            f"/v1/departments/{department['id']}",
            headers={**headers, "If-Match": str(department["version"])},
            json={"id": str(uuid4()), "company_id": str(uuid4())},
        )
        assert response.status_code == 422

        after = await client.get(f"/v1/departments/{department['id']}", headers=headers)
        assert after.json()["data"]["id"] == department["id"]
        assert after.json()["data"]["company_id"] == str(company_id)
    finally:
        await _cleanup_departments_and_branches(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_get_department_not_found(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.get(f"/v1/departments/{uuid4()}", headers=headers)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_update_department_success(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        department = await _create_department(client, headers)
        response = await client.patch(
            f"/v1/departments/{department['id']}",
            headers={**headers, "If-Match": str(department["version"])},
            json={"code": "ENG"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["code"] == "ENG"
        assert data["version"] == 2
        assert data["name"] == "Engineering"
    finally:
        await _cleanup_departments_and_branches(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_update_department_stale_version_conflict(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        department = await _create_department(client, headers)
        response = await client.patch(
            f"/v1/departments/{department['id']}",
            headers={**headers, "If-Match": "999"},
            json={"name": "Renamed"},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "STALE_RESOURCE"
    finally:
        await _cleanup_departments_and_branches(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_deactivate_department_success(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        department = await _create_department(client, headers)
        response = await client.request(
            "DELETE",
            f"/v1/departments/{department['id']}",
            headers={**headers, "If-Match": str(department["version"])},
        )
        assert response.status_code == 200
        assert response.json()["data"]["is_active"] is False

        factory = get_session_factory()
        async with factory() as session:
            audit_rows = (
                (
                    await session.execute(
                        select(AuditLog).where(
                            AuditLog.entity_id == UUID(department["id"]),
                            AuditLog.action == "DEPARTMENT_DEACTIVATED",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(audit_rows) == 1
    finally:
        await _cleanup_departments_and_branches(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_deactivate_department_not_blocked_by_active_child(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """No documented dependency-blocking rule applies to Department deactivation this
    slice (see docs/modules/department/00_DEPARTMENT_AUDIT.md §5.3) — a department with
    an active sub-department can still be deactivated."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        parent = await _create_department(client, headers, name="Parent")
        await _create_department(client, headers, name="Child", parent_id=parent["id"])

        response = await client.request(
            "DELETE",
            f"/v1/departments/{parent['id']}",
            headers={**headers, "If-Match": str(parent["version"])},
        )
        assert response.status_code == 200
        assert response.json()["data"]["is_active"] is False
    finally:
        await _cleanup_departments_and_branches(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_reactivate_department_via_patch(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        department = await _create_department(client, headers)
        deactivated = await client.request(
            "DELETE",
            f"/v1/departments/{department['id']}",
            headers={**headers, "If-Match": str(department["version"])},
        )
        assert deactivated.json()["data"]["is_active"] is False
        version_after_deactivate = deactivated.json()["data"]["version"]

        reactivated = await client.patch(
            f"/v1/departments/{department['id']}",
            headers={**headers, "If-Match": str(version_after_deactivate)},
            json={"is_active": True},
        )
        assert reactivated.status_code == 200
        assert reactivated.json()["data"]["is_active"] is True

        factory = get_session_factory()
        async with factory() as session:
            audit_rows = (
                (
                    await session.execute(
                        select(AuditLog).where(
                            AuditLog.entity_id == UUID(department["id"]),
                            AuditLog.action == "DEPARTMENT_REACTIVATED",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(audit_rows) == 1
    finally:
        await _cleanup_departments_and_branches(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_deactivating_branch_not_blocked_by_inactive_department(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Regression coverage for the fix to `count_active_departments_for_branch`: a
    *deactivated* department must not block Branch deactivation (FR-ORG-014)."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        branch_id = await _create_branch(client, headers)
        department = await _create_department(client, headers, branch_id=branch_id)
        deactivated_department = await client.request(
            "DELETE",
            f"/v1/departments/{department['id']}",
            headers={**headers, "If-Match": str(department["version"])},
        )
        assert deactivated_department.json()["data"]["is_active"] is False

        branch = await client.get(f"/v1/branches/{branch_id}", headers=headers)
        response = await client.request(
            "DELETE",
            f"/v1/branches/{branch_id}",
            headers={**headers, "If-Match": str(branch.json()["data"]["version"])},
        )
        assert response.status_code == 200
        assert response.json()["data"]["is_active"] is False
    finally:
        await _cleanup_departments_and_branches(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_deactivating_branch_blocked_by_active_department(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Confirms Branch's own deactivation-blocking rule still works once Department has
    a real ORM-backed `is_active` column (previously a raw-SQL-only check)."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        branch_id = await _create_branch(client, headers)
        await _create_department(client, headers, branch_id=branch_id)

        branch = await client.get(f"/v1/branches/{branch_id}", headers=headers)
        response = await client.request(
            "DELETE",
            f"/v1/branches/{branch_id}",
            headers={**headers, "If-Match": str(branch.json()["data"]["version"])},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "BRANCH_HAS_ACTIVE_DEPARTMENTS"
    finally:
        await _cleanup_departments_and_branches(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_multiple_departments_supported(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        await _create_department(client, headers, name="Engineering")
        await _create_department(client, headers, name="Sales")
        listed = await client.get("/v1/departments", headers=headers)
        names = {row["name"] for row in listed.json()["data"]}
        assert names == {"Engineering", "Sales"}
    finally:
        await _cleanup_departments_and_branches(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# ---------------------------------------------------------------------------
# Department Head assignment (LEAVE_DECISION_LOG.md LD-23)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_department_with_head_employee_success(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        head = await _create_employee(client, headers, first_name="Heena")
        response = await client.post(
            "/v1/departments",
            headers=headers,
            json={"name": "Engineering", "head_employee_id": head["id"]},
        )
        assert response.status_code == 201, response.text
        assert response.json()["data"]["head_employee_id"] == head["id"]
    finally:
        await _cleanup_departments_and_branches(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_department_invalid_head_employee_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.post(
            "/v1/departments",
            headers=headers,
            json={"name": "Engineering", "head_employee_id": str(uuid4())},
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "INVALID_DEPARTMENT_HEAD"
    finally:
        await _cleanup_departments_and_branches(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_update_department_sets_and_clears_head_employee(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        head = await _create_employee(client, headers, first_name="Heena")
        department = await _create_department(client, headers)

        updated = await client.patch(
            f"/v1/departments/{department['id']}",
            headers={**headers, "If-Match": str(department["version"])},
            json={"head_employee_id": head["id"]},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["data"]["head_employee_id"] == head["id"]

        cleared = await client.patch(
            f"/v1/departments/{department['id']}",
            headers={**headers, "If-Match": str(updated.json()["data"]["version"])},
            json={"head_employee_id": None},
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["data"]["head_employee_id"] is None
    finally:
        await _cleanup_departments_and_branches(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_update_department_invalid_head_employee_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        department = await _create_department(client, headers)
        response = await client.patch(
            f"/v1/departments/{department['id']}",
            headers={**headers, "If-Match": str(department["version"])},
            json={"head_employee_id": str(uuid4())},
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "INVALID_DEPARTMENT_HEAD"
    finally:
        await _cleanup_departments_and_branches(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
