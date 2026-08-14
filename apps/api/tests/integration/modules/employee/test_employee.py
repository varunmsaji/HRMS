"""Integration tests for the Employee API (E-01, identity foundation) — `/v1/employees`.

Follows the exact checklist established by
`tests/integration/modules/organisation/test_grade.py`: create, list, get, mass-assignment
rejection, stale-version conflict, deactivate, reactivate, audit-row assertions, cross-tenant
isolation, permission matrix. No "duplicate code rejected" case — unlike Grade's `code`,
`employee_code` is system-generated (number-series allocated), never client-supplied, so there is
no client input that could collide.
"""

from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from hrms.core.audit.models import AuditLog
from hrms.core.db.session import get_session_factory

from ..organisation.test_registration_flow import _cleanup, _register


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
    assert response.status_code == 201
    return dict(response.json()["data"])


async def _cleanup_employees(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("DELETE FROM employee WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.execute(
            text("DELETE FROM number_series WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.commit()


@pytest.mark.asyncio
async def test_list_employees_empty_state(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.get("/v1/employees", headers=headers)
        assert response.status_code == 200
        assert response.json()["data"] == []
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_employee_success(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.post(
            "/v1/employees",
            headers=headers,
            json={"first_name": "Asha", "last_name": "Verma", "gender": "FEMALE"},
        )
        assert response.status_code == 201
        data = response.json()["data"]
        assert data["first_name"] == "Asha"
        assert data["last_name"] == "Verma"
        assert data["employee_code"] == "EMP-0001"
        assert data["status"] == "PRE_JOINING"
        assert data["is_active"] is True
        assert data["version"] == 1
        assert data["company_id"] == str(company_id)
        # PAN/Aadhaar/UAN/status are not writable in this slice — never present as request
        # fields, and always absent-or-null in the response regardless of what's sent.
        assert "pan_number_enc" not in data
        assert "aadhaar_number_enc" not in data

        listed = await client.get("/v1/employees", headers=headers)
        assert len(listed.json()["data"]) == 1

        factory = get_session_factory()
        async with factory() as session:
            audit_rows = (
                (
                    await session.execute(
                        select(AuditLog).where(
                            AuditLog.company_id == company_id,
                            AuditLog.entity_type == "employee",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(audit_rows) == 1
            assert audit_rows[0].action == "EMPLOYEE_CREATED"
    finally:
        await _cleanup_employees(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_employee_code_sequence_gap_free(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        first = await _create_employee(client, headers, first_name="Asha")
        second = await _create_employee(client, headers, first_name="Rahul")
        assert first["employee_code"] == "EMP-0001"
        assert second["employee_code"] == "EMP-0002"
    finally:
        await _cleanup_employees(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_employee_same_sequence_start_different_tenant(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Each company gets its own `number_series` row — a second tenant's first employee also
    starts at `EMP-0001`, proving the sequence is company-scoped, not global."""
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        employee_a = await _create_employee(client, headers_a)
        employee_b = await _create_employee(client, headers_b)
        assert employee_a["employee_code"] == "EMP-0001"
        assert employee_b["employee_code"] == "EMP-0001"
    finally:
        await _cleanup_employees(company_id=company_a)
        await _cleanup_employees(company_id=company_b)
        await _cleanup(company_id=company_a, user_id=user_a)
        await _cleanup(company_id=company_b, user_id=user_b)


@pytest.mark.asyncio
async def test_create_employee_missing_required_fields_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.post("/v1/employees", headers=headers, json={})
        assert response.status_code == 422
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_create_employee_mass_assignment_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.post(
            "/v1/employees",
            headers=headers,
            json={
                "first_name": "Asha",
                "employee_code": "EMP-9999",
                "status": "ACTIVE",
                "is_active": False,
                "version": 99,
            },
        )
        assert response.status_code == 422
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_update_employee_mass_assignment_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        response = await client.patch(
            f"/v1/employees/{employee['id']}",
            headers={**headers, "If-Match": str(employee["version"])},
            json={"id": str(uuid4()), "employee_code": "EMP-9999", "status": "ACTIVE"},
        )
        assert response.status_code == 422

        after = await client.get(f"/v1/employees/{employee['id']}", headers=headers)
        assert after.json()["data"]["id"] == employee["id"]
        assert after.json()["data"]["employee_code"] == employee["employee_code"]
    finally:
        await _cleanup_employees(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_get_employee_not_found(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        response = await client.get(f"/v1/employees/{uuid4()}", headers=headers)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_update_employee_success(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        response = await client.patch(
            f"/v1/employees/{employee['id']}",
            headers={**headers, "If-Match": str(employee["version"])},
            json={"last_name": "Rao", "blood_group": "O+"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["last_name"] == "Rao"
        assert data["blood_group"] == "O+"
        assert data["version"] == 2
        assert data["employee_code"] == employee["employee_code"]
    finally:
        await _cleanup_employees(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_update_employee_stale_version_conflict(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        response = await client.patch(
            f"/v1/employees/{employee['id']}",
            headers={**headers, "If-Match": "999"},
            json={"last_name": "Renamed"},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "STALE_RESOURCE"
    finally:
        await _cleanup_employees(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_deactivate_employee_success(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        response = await client.request(
            "DELETE",
            f"/v1/employees/{employee['id']}",
            headers={**headers, "If-Match": str(employee["version"])},
        )
        assert response.status_code == 200
        assert response.json()["data"]["is_active"] is False

        factory = get_session_factory()
        async with factory() as session:
            audit_rows = (
                (
                    await session.execute(
                        select(AuditLog).where(
                            AuditLog.entity_id == UUID(employee["id"]),
                            AuditLog.action == "EMPLOYEE_DEACTIVATED",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(audit_rows) == 1
    finally:
        await _cleanup_employees(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_reactivate_employee_via_patch(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        deactivated = await client.request(
            "DELETE",
            f"/v1/employees/{employee['id']}",
            headers={**headers, "If-Match": str(employee["version"])},
        )
        version_after_deactivate = deactivated.json()["data"]["version"]

        reactivated = await client.patch(
            f"/v1/employees/{employee['id']}",
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
                            AuditLog.entity_id == UUID(employee["id"]),
                            AuditLog.action == "EMPLOYEE_REACTIVATED",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(audit_rows) == 1
    finally:
        await _cleanup_employees(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_multiple_employees_supported(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        await _create_employee(client, headers, first_name="Asha")
        await _create_employee(client, headers, first_name="Rahul")
        listed = await client.get("/v1/employees", headers=headers)
        names = {row["first_name"] for row in listed.json()["data"]}
        assert names == {"Asha", "Rahul"}
    finally:
        await _cleanup_employees(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


# --- Tenant isolation --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cannot_get_employee_from_other_tenant(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        employee_a = await _create_employee(client, headers_a)
        response = await client.get(f"/v1/employees/{employee_a['id']}", headers=headers_b)
        assert response.status_code == 404
    finally:
        await _cleanup_employees(company_id=company_a)
        await _cleanup(company_id=company_a, user_id=user_a)
        await _cleanup(company_id=company_b, user_id=user_b)


@pytest.mark.asyncio
async def test_other_tenant_employees_not_listed(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        await _create_employee(client, headers_a)
        listed_b = await client.get("/v1/employees", headers=headers_b)
        assert listed_b.json()["data"] == []
    finally:
        await _cleanup_employees(company_id=company_a)
        await _cleanup(company_id=company_a, user_id=user_a)
        await _cleanup(company_id=company_b, user_id=user_b)


# --- Permission matrix -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_employee_without_permission_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A role holding only `EMPLOYEE.VIEW` must not be able to `POST /v1/employees`. Built
    inline rather than relying on the seeded `EMPLOYEE_VIEWER` system role — that role only
    exists for the two fixed demo companies `seed/bootstrap.py` seeds, not for a company
    dynamically created via `/v1/companies/register` (this test's own tenant)."""
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4 as _uuid4

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
    from hrms.modules.identity.permissions import EMPLOYEE_VIEW

    headers, company_id, user_id = await _register_tenant(client)
    try:
        factory = get_session_factory()
        async with factory() as session:
            view_permission = (
                await session.execute(select(Permission).where(Permission.code == EMPLOYEE_VIEW))
            ).scalar_one()

            now = datetime.now(UTC)
            view_only_role_id = _uuid4()
            session.add(
                Role(
                    id=view_only_role_id,
                    company_id=company_id,
                    code="EMPLOYEE_VIEW_ONLY_TEST_ROLE",
                    name="View-only test role",
                    is_system=False,
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.flush()
            session.add(RolePermission(role_id=view_only_role_id, permission_id=view_permission.id))

            viewer_user_id = _uuid4()
            session.add(
                User(
                    id=viewer_user_id,
                    email=f"viewer-{viewer_user_id.hex[:8]}@example.com",
                    password_hash=hash_password("CorrectHorse9"),
                    status="ACTIVE",
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.flush()
            user_company = UserCompany(
                id=_uuid4(),
                user_id=viewer_user_id,
                company_id=company_id,
                is_primary=True,
                status="ACTIVE",
                created_at=now,
                updated_at=now,
            )
            session.add(user_company)
            await session.flush()
            session.add(
                UserRole(id=_uuid4(), user_company_id=user_company.id, role_id=view_only_role_id)
            )
            viewer_session_id = _uuid4()
            session.add(
                Session(
                    id=viewer_session_id,
                    user_id=viewer_user_id,
                    company_id=company_id,
                    expires_at=now + timedelta(days=1),
                )
            )
            await session.commit()

        token = create_access_token(
            user_id=viewer_user_id,
            company_id=company_id,
            session_id=viewer_session_id,
            employee_id=None,
        )
        viewer_headers = {"Authorization": f"Bearer {token}", "X-Company-Id": str(company_id)}

        response = await client.post(
            "/v1/employees", headers=viewer_headers, json={"first_name": "Asha"}
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"
    finally:
        await _cleanup_employees(company_id=company_id)
        # `_cleanup(company_id=...)` removes every Role/RolePermission/UserCompany/UserRole
        # scoped to this company (including the inline test role and the viewer's
        # UserCompany/UserRole rows above) but only deletes the admin `user_id` row itself —
        # run it first so the viewer's `UserCompany` FK reference is gone, then delete the
        # now-unreferenced standalone viewer `User` row.
        await _cleanup(company_id=company_id, user_id=user_id)
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                text(
                    "DELETE FROM session WHERE user_id IN "
                    "(SELECT id FROM \"user\" WHERE email LIKE 'viewer-%')"
                )
            )
            await session.execute(text("DELETE FROM \"user\" WHERE email LIKE 'viewer-%'"))
            await session.commit()


@pytest.mark.asyncio
async def test_create_employee_seat_limit_enforced(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """FREE plan seat limit is 5 (`seed/plan_catalogue.py`); the 6th create must be rejected."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        for i in range(5):
            await _create_employee(client, headers, first_name=f"Employee{i}")

        response = await client.post(
            "/v1/employees", headers=headers, json={"first_name": "OneTooMany"}
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "EMPLOYEE_SEAT_LIMIT_EXCEEDED"

        listed = await client.get("/v1/employees", headers=headers)
        assert len(listed.json()["data"]) == 5
    finally:
        await _cleanup_employees(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
