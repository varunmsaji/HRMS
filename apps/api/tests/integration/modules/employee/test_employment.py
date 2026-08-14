"""Integration tests for the Employment API (E-03, employment lifecycle) —
`/v1/employees/{employee_id}/employments*`.

Follows the same checklist as `test_employee.py` (E-01): create, list, get, update,
mass-assignment rejection, stale-version conflict, cross-tenant isolation, permission matrix —
plus the scenarios specific to this slice: rehire (the central E-03 scenario), termination,
the `employment_no_overlap` GiST exclusion constraint's friendly-error surface, and the
as-of-date read pattern.
"""

from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from hrms.core.audit.models import AuditLog
from hrms.core.db.session import get_session_factory

from ..organisation.test_registration_flow import _cleanup, _register

pytestmark = pytest.mark.asyncio


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


async def _create_legal_entity(
    client: AsyncClient, headers: dict[str, str], name: str = "Acme Legal Entity"
) -> dict[str, Any]:
    response = await client.post("/v1/legal-entities", headers=headers, json={"name": name})
    assert response.status_code == 201
    return dict(response.json()["data"])


async def _create_employment(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    employee_id: str,
    legal_entity_id: str,
    joining_date: str = "2027-06-01",
) -> dict[str, Any]:
    response = await client.post(
        f"/v1/employees/{employee_id}/employments",
        headers=headers,
        json={"legal_entity_id": legal_entity_id, "joining_date": joining_date},
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _cleanup_employments(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("DELETE FROM employment WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.commit()


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


async def _teardown(*, company_id: UUID, user_id: UUID | None) -> None:
    """Full teardown in FK-safe order: employment (→ employee, legal_entity) → employee
    (→ number_series) → the rest (legal_entity/company/roles/user), matching
    `test_employee.py`'s own ordering plus the new `employment` leg."""
    await _cleanup_employments(company_id=company_id)
    await _cleanup_employees(company_id=company_id)
    await _cleanup(company_id=company_id, user_id=user_id)


async def _setup_employee_and_entity(
    client: AsyncClient, headers: dict[str, str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    employee = await _create_employee(client, headers)
    legal_entity = await _create_legal_entity(client, headers)
    return employee, legal_entity


# --- Create (first hire) ------------------------------------------------------------------


async def test_create_employment_success(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, legal_entity = await _setup_employee_and_entity(client, headers)
        employment = await _create_employment(
            client, headers, employee_id=employee["id"], legal_entity_id=legal_entity["id"]
        )

        assert employment["employee_id"] == employee["id"]
        assert employment["legal_entity_id"] == legal_entity["id"]
        assert employment["joining_date"] == "2027-06-01"
        assert employment["status"] == "ACTIVE"
        assert employment["last_working_day"] is None
        assert employment["previous_employment_id"] is None
        assert employment["version"] == 1

        factory = get_session_factory()
        async with factory() as session:
            audit_rows = (
                (
                    await session.execute(
                        select(AuditLog).where(
                            AuditLog.company_id == company_id,
                            AuditLog.entity_type == "employment",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(audit_rows) == 1
            assert audit_rows[0].action == "EMPLOYMENT_STARTED"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_employment_unknown_employee_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        legal_entity = await _create_legal_entity(client, headers)
        response = await client.post(
            f"/v1/employees/{uuid4()}/employments",
            headers=headers,
            json={"legal_entity_id": legal_entity["id"], "joining_date": "2027-06-01"},
        )
        assert response.status_code == 404
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_employment_invalid_legal_entity_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        response = await client.post(
            f"/v1/employees/{employee['id']}/employments",
            headers=headers,
            json={"legal_entity_id": str(uuid4()), "joining_date": "2027-06-01"},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_LEGAL_ENTITY"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_employment_mass_assignment_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, legal_entity = await _setup_employee_and_entity(client, headers)
        response = await client.post(
            f"/v1/employees/{employee['id']}/employments",
            headers=headers,
            json={
                "legal_entity_id": legal_entity["id"],
                "joining_date": "2027-06-01",
                "status": "TERMINATED",
                "previous_employment_id": str(uuid4()),
                "version": 99,
            },
        )
        assert response.status_code == 422
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_second_active_employment_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The `employment_no_overlap` GiST exclusion constraint blocks a second `ACTIVE`
    employment for the same employee — an employee must be terminated before a new employment
    row (rehire) can be created."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, legal_entity = await _setup_employee_and_entity(client, headers)
        await _create_employment(
            client, headers, employee_id=employee["id"], legal_entity_id=legal_entity["id"]
        )

        response = await client.post(
            f"/v1/employees/{employee['id']}/employments",
            headers=headers,
            json={"legal_entity_id": legal_entity["id"], "joining_date": "2028-01-01"},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "EMPLOYMENT_DATES_OVERLAP"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


# --- Read / list (incl. as-of) ------------------------------------------------------------


async def test_list_employments_empty_state(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        response = await client.get(f"/v1/employees/{employee['id']}/employments", headers=headers)
        assert response.status_code == 200
        assert response.json()["data"] == []
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_get_employment_success(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, legal_entity = await _setup_employee_and_entity(client, headers)
        employment = await _create_employment(
            client, headers, employee_id=employee["id"], legal_entity_id=legal_entity["id"]
        )

        response = await client.get(
            f"/v1/employees/{employee['id']}/employments/{employment['id']}", headers=headers
        )
        assert response.status_code == 200
        assert response.json()["data"]["id"] == employment["id"]
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_get_employment_not_found(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        response = await client.get(
            f"/v1/employees/{employee['id']}/employments/{uuid4()}", headers=headers
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_list_employments_as_of_date_boundaries(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The as-of-date read pattern (`docs/modules/employee/01_EMPLOYEE_MODULE_PLAN.md` §3 item
    3): "does employee X have an active employment on date Y" — checked at the exact
    `joining_date`/`last_working_day` boundaries and just outside them."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, legal_entity = await _setup_employee_and_entity(client, headers)
        employment = await _create_employment(
            client,
            headers,
            employee_id=employee["id"],
            legal_entity_id=legal_entity["id"],
            joining_date="2027-06-01",
        )
        terminate = await client.post(
            f"/v1/employees/{employee['id']}/employments/{employment['id']}/terminate",
            headers={**headers, "If-Match": str(employment["version"])},
            json={"last_working_day": "2030-09-30"},
        )
        assert terminate.status_code == 200

        async def _as_of(day: str) -> list[dict[str, Any]]:
            resp = await client.get(
                f"/v1/employees/{employee['id']}/employments",
                headers=headers,
                params={"as_of": day},
            )
            assert resp.status_code == 200
            return list(resp.json()["data"])

        assert len(await _as_of("2027-06-01")) == 1  # joining_date boundary, inclusive
        assert len(await _as_of("2029-01-01")) == 1  # mid-spell
        assert len(await _as_of("2030-09-30")) == 1  # last_working_day boundary, inclusive
        assert await _as_of("2027-05-31") == []  # one day before joining
        assert await _as_of("2030-10-01") == []  # one day after last_working_day
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


# --- Update ------------------------------------------------------------------------------


async def test_update_employment_success(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, legal_entity = await _setup_employee_and_entity(client, headers)
        employment = await _create_employment(
            client, headers, employee_id=employee["id"], legal_entity_id=legal_entity["id"]
        )
        new_entity = await _create_legal_entity(client, headers, name="Second Legal Entity")

        response = await client.patch(
            f"/v1/employees/{employee['id']}/employments/{employment['id']}",
            headers={**headers, "If-Match": str(employment["version"])},
            json={"legal_entity_id": new_entity["id"]},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["legal_entity_id"] == new_entity["id"]
        assert data["version"] == 2
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_update_employment_mass_assignment_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, legal_entity = await _setup_employee_and_entity(client, headers)
        employment = await _create_employment(
            client, headers, employee_id=employee["id"], legal_entity_id=legal_entity["id"]
        )
        response = await client.patch(
            f"/v1/employees/{employee['id']}/employments/{employment['id']}",
            headers={**headers, "If-Match": str(employment["version"])},
            json={"status": "TERMINATED", "last_working_day": "2027-07-01"},
        )
        assert response.status_code == 422
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_update_employment_stale_version_conflict(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, legal_entity = await _setup_employee_and_entity(client, headers)
        employment = await _create_employment(
            client, headers, employee_id=employee["id"], legal_entity_id=legal_entity["id"]
        )
        response = await client.patch(
            f"/v1/employees/{employee['id']}/employments/{employment['id']}",
            headers={**headers, "If-Match": "999"},
            json={"legal_entity_id": legal_entity["id"]},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "STALE_RESOURCE"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_update_terminated_employment_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, legal_entity = await _setup_employee_and_entity(client, headers)
        employment = await _create_employment(
            client, headers, employee_id=employee["id"], legal_entity_id=legal_entity["id"]
        )
        terminated = await client.post(
            f"/v1/employees/{employee['id']}/employments/{employment['id']}/terminate",
            headers={**headers, "If-Match": str(employment["version"])},
            json={"last_working_day": "2027-12-31"},
        )
        assert terminated.status_code == 200

        response = await client.patch(
            f"/v1/employees/{employee['id']}/employments/{employment['id']}",
            headers={**headers, "If-Match": str(terminated.json()["data"]["version"])},
            json={"legal_entity_id": legal_entity["id"]},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "EMPLOYMENT_NOT_ACTIVE"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


# --- Termination -------------------------------------------------------------------------


async def test_terminate_employment_success(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, legal_entity = await _setup_employee_and_entity(client, headers)
        employment = await _create_employment(
            client, headers, employee_id=employee["id"], legal_entity_id=legal_entity["id"]
        )

        response = await client.post(
            f"/v1/employees/{employee['id']}/employments/{employment['id']}/terminate",
            headers={**headers, "If-Match": str(employment["version"])},
            json={"last_working_day": "2030-09-30"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["status"] == "TERMINATED"
        assert data["last_working_day"] == "2030-09-30"
        assert data["version"] == 2

        factory = get_session_factory()
        async with factory() as session:
            audit_rows = (
                (
                    await session.execute(
                        select(AuditLog).where(
                            AuditLog.entity_id == UUID(employment["id"]),
                            AuditLog.action == "EMPLOYMENT_TERMINATED",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(audit_rows) == 1
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_terminate_employment_last_working_day_before_joining_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, legal_entity = await _setup_employee_and_entity(client, headers)
        employment = await _create_employment(
            client,
            headers,
            employee_id=employee["id"],
            legal_entity_id=legal_entity["id"],
            joining_date="2027-06-01",
        )
        response = await client.post(
            f"/v1/employees/{employee['id']}/employments/{employment['id']}/terminate",
            headers={**headers, "If-Match": str(employment["version"])},
            json={"last_working_day": "2027-01-01"},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_LAST_WORKING_DAY"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_terminate_already_terminated_employment_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, legal_entity = await _setup_employee_and_entity(client, headers)
        employment = await _create_employment(
            client, headers, employee_id=employee["id"], legal_entity_id=legal_entity["id"]
        )
        first = await client.post(
            f"/v1/employees/{employee['id']}/employments/{employment['id']}/terminate",
            headers={**headers, "If-Match": str(employment["version"])},
            json={"last_working_day": "2027-12-31"},
        )
        assert first.status_code == 200

        second = await client.post(
            f"/v1/employees/{employee['id']}/employments/{employment['id']}/terminate",
            headers={**headers, "If-Match": str(first.json()["data"]["version"])},
            json={"last_working_day": "2028-01-15"},
        )
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "EMPLOYMENT_NOT_ACTIVE"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_terminate_employment_stale_version_conflict(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, legal_entity = await _setup_employee_and_entity(client, headers)
        employment = await _create_employment(
            client, headers, employee_id=employee["id"], legal_entity_id=legal_entity["id"]
        )
        response = await client.post(
            f"/v1/employees/{employee['id']}/employments/{employment['id']}/terminate",
            headers={**headers, "If-Match": "999"},
            json={"last_working_day": "2030-09-30"},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "STALE_RESOURCE"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


# --- Rehire — the central E-03 scenario ---------------------------------------------------


async def test_rehire_creates_new_employment_linked_to_previous(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The brief's own worked example: an employee joins, exits, and — after a gap — rejoins.
    Same `employee.id`/`employee_code` throughout; a second `employment` row is created,
    linked to the first via `previous_employment_id`; the first row is never mutated to
    represent the rehire."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, legal_entity = await _setup_employee_and_entity(client, headers)

        first = await _create_employment(
            client,
            headers,
            employee_id=employee["id"],
            legal_entity_id=legal_entity["id"],
            joining_date="2027-06-01",
        )
        terminated = await client.post(
            f"/v1/employees/{employee['id']}/employments/{first['id']}/terminate",
            headers={**headers, "If-Match": str(first["version"])},
            json={"last_working_day": "2030-09-30"},
        )
        assert terminated.status_code == 200

        second = await _create_employment(
            client,
            headers,
            employee_id=employee["id"],
            legal_entity_id=legal_entity["id"],
            joining_date="2034-02-01",
        )

        assert second["previous_employment_id"] == first["id"]
        assert second["status"] == "ACTIVE"
        assert second["id"] != first["id"]

        # The first employment row was never mutated to represent the rehire — it remains
        # exactly as terminated, permanently queryable.
        first_after = await client.get(
            f"/v1/employees/{employee['id']}/employments/{first['id']}", headers=headers
        )
        assert first_after.json()["data"]["status"] == "TERMINATED"
        assert first_after.json()["data"]["last_working_day"] == "2030-09-30"
        assert first_after.json()["data"]["previous_employment_id"] is None

        # Employee identity is unaffected by rehire — same id, same employee_code.
        employee_after = await client.get(f"/v1/employees/{employee['id']}", headers=headers)
        assert employee_after.json()["data"]["id"] == employee["id"]
        assert employee_after.json()["data"]["employee_code"] == employee["employee_code"]

        history = await client.get(f"/v1/employees/{employee['id']}/employments", headers=headers)
        history_ids = [row["id"] for row in history.json()["data"]]
        assert history_ids == [first["id"], second["id"]]

        factory = get_session_factory()
        async with factory() as session:
            audit_rows = (
                (
                    await session.execute(
                        select(AuditLog).where(
                            AuditLog.entity_id == UUID(second["id"]),
                            AuditLog.action == "EMPLOYMENT_REHIRED",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(audit_rows) == 1
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


# --- Tenant isolation ----------------------------------------------------------------------


async def test_cannot_get_employment_from_other_tenant(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        employee_a, legal_entity_a = await _setup_employee_and_entity(client, headers_a)
        employment_a = await _create_employment(
            client, headers_a, employee_id=employee_a["id"], legal_entity_id=legal_entity_a["id"]
        )

        response = await client.get(
            f"/v1/employees/{employee_a['id']}/employments/{employment_a['id']}",
            headers=headers_b,
        )
        assert response.status_code == 404
    finally:
        await _teardown(company_id=company_a, user_id=user_a)
        await _teardown(company_id=company_b, user_id=user_b)


async def test_other_tenant_employments_not_listed(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        employee_a, legal_entity_a = await _setup_employee_and_entity(client, headers_a)
        await _create_employment(
            client, headers_a, employee_id=employee_a["id"], legal_entity_id=legal_entity_a["id"]
        )

        # Employee B trying to list employments under Employee A's id (not their own tenant's
        # employee) must 404, not leak Employee A's employment history.
        response = await client.get(
            f"/v1/employees/{employee_a['id']}/employments", headers=headers_b
        )
        assert response.status_code == 404
    finally:
        await _teardown(company_id=company_a, user_id=user_a)
        await _teardown(company_id=company_b, user_id=user_b)


# --- Permission matrix -----------------------------------------------------------------


async def test_create_employment_without_permission_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
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
        employee, legal_entity = await _setup_employee_and_entity(client, headers)

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
                    code="EMPLOYMENT_VIEW_ONLY_TEST_ROLE",
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
            f"/v1/employees/{employee['id']}/employments",
            headers=viewer_headers,
            json={"legal_entity_id": legal_entity["id"], "joining_date": "2027-06-01"},
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
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
