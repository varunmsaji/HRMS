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
from .test_employee_assignment import (
    _cleanup_assignments,
    _cleanup_org_structure,
    _create_assignment,
    _create_department,
    _setup_employee_with_employment,
)
from .test_employee_compensation import (
    _cleanup_compensations,
    _create_compensation,
    _joining_payload,
)

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


# --- Data-scope enforcement (Finding A / F4) --------------------------------------------------
#
# `docs/modules/employee/39_EMPLOYEE_ACCESS_CONTROL_IMPLEMENTATION_PLAN.md` Finding A: `list_
# employments`/`get_employment` used to bind `_scope: Annotated[object, ...]` — the resolved
# `DataScope` was thrown away, making every `EMPLOYEE.VIEW` grant company-wide regardless of its
# stored `data_scope`. Fixed per Phase 1 — these tests prove the resolved scope is now actually
# enforced, mirroring `test_employee_compensation.py`'s equivalent SELF/REPORTEES/COMPANY tests.
# Write-path scope (Finding C, `create_employment`/`update_employment`/`terminate_employment`) is
# covered further below, per Phase 2.


async def _create_permission_scoped_user(
    *,
    company_id: UUID,
    permission_codes: list[str],
    data_scope: str = "COMPANY",
    caller_employee_id: UUID | None = None,
) -> tuple[dict[str, str], UUID]:
    """Registers a second user in the same tenant, granted only the given permission codes at
    the given `data_scope` — mirrors `test_employee_compensation.py`'s own helper exactly."""
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

    factory = get_session_factory()
    async with factory() as session:
        permissions = (
            (await session.execute(select(Permission).where(Permission.code.in_(permission_codes))))
            .scalars()
            .all()
        )
        assert len(permissions) == len(permission_codes)

        now = datetime.now(UTC)
        role_id = _uuid4()
        session.add(
            Role(
                id=role_id,
                company_id=company_id,
                code=f"EMPLOYMENT_TEST_ROLE_{role_id.hex[:8]}",
                name="Employment test role",
                is_system=False,
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        for permission in permissions:
            session.add(
                RolePermission(role_id=role_id, permission_id=permission.id, data_scope=data_scope)
            )

        scoped_user_id = _uuid4()
        session.add(
            User(
                id=scoped_user_id,
                email=f"scoped-employment-{scoped_user_id.hex[:8]}@example.com",
                password_hash=hash_password("CorrectHorse9"),
                status="ACTIVE",
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        user_company = UserCompany(
            id=_uuid4(),
            user_id=scoped_user_id,
            company_id=company_id,
            is_primary=True,
            status="ACTIVE",
            created_at=now,
            updated_at=now,
        )
        session.add(user_company)
        await session.flush()
        session.add(UserRole(id=_uuid4(), user_company_id=user_company.id, role_id=role_id))
        scoped_session_id = _uuid4()
        session.add(
            Session(
                id=scoped_session_id,
                user_id=scoped_user_id,
                company_id=company_id,
                expires_at=now + timedelta(days=1),
            )
        )
        await session.commit()

    token = create_access_token(
        user_id=scoped_user_id,
        company_id=company_id,
        session_id=scoped_session_id,
        employee_id=caller_employee_id,
    )
    return (
        {"Authorization": f"Bearer {token}", "X-Company-Id": str(company_id)},
        scoped_user_id,
    )


async def _cleanup_scoped_users() -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text(
                "DELETE FROM session WHERE user_id IN "
                "(SELECT id FROM \"user\" WHERE email LIKE 'scoped-employment-%')"
            )
        )
        await session.execute(text("DELETE FROM \"user\" WHERE email LIKE 'scoped-employment-%'"))
        await session.commit()


async def test_list_employments_self_scope_sees_own_only(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A caller holding `EMPLOYEE.VIEW` at `SELF` scope sees their own employment history; a
    direct single-record lookup and the list route both agree, and another employee's history is
    invisible (`404`, not `403`, matching every other out-of-scope convention in this module)."""
    from hrms.modules.identity.permissions import EMPLOYEE_VIEW

    headers, company_id, user_id = await _register_tenant(client)
    try:
        self_employee, self_entity = await _setup_employee_and_entity(client, headers)
        self_employment = await _create_employment(
            client, headers, employee_id=self_employee["id"], legal_entity_id=self_entity["id"]
        )
        other_employee, other_entity = await _setup_employee_and_entity(client, headers)
        await _create_employment(
            client, headers, employee_id=other_employee["id"], legal_entity_id=other_entity["id"]
        )

        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[EMPLOYEE_VIEW],
            data_scope="SELF",
            caller_employee_id=UUID(self_employee["id"]),
        )

        own_list = await client.get(
            f"/v1/employees/{self_employee['id']}/employments", headers=scoped_headers
        )
        assert own_list.status_code == 200
        assert len(own_list.json()["data"]) == 1

        own_detail = await client.get(
            f"/v1/employees/{self_employee['id']}/employments/{self_employment['id']}",
            headers=scoped_headers,
        )
        assert own_detail.status_code == 200

        other_list = await client.get(
            f"/v1/employees/{other_employee['id']}/employments", headers=scoped_headers
        )
        assert other_list.status_code == 404
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_list_employments_self_scope_no_employee_id_sees_nothing(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A caller with a `SELF`-scoped `EMPLOYEE.VIEW` grant but no linked `employee_id` (JWT claim
    is `None`) fails closed — never falls back to `COMPANY`."""
    from hrms.modules.identity.permissions import EMPLOYEE_VIEW

    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, legal_entity = await _setup_employee_and_entity(client, headers)
        await _create_employment(
            client, headers, employee_id=employee["id"], legal_entity_id=legal_entity["id"]
        )

        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[EMPLOYEE_VIEW],
            data_scope="SELF",
            caller_employee_id=None,
        )

        response = await client.get(
            f"/v1/employees/{employee['id']}/employments", headers=scoped_headers
        )
        assert response.status_code == 404
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_list_employments_reportees_scope_sees_direct_reports_only(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`RBAC_DATA_SCOPE_DECISIONS.md` Decision F: a manager granted `EMPLOYEE.VIEW` at
    `REPORTEES` scope sees a direct report's employment history but not an unrelated employee's,
    and not their own (`REPORTEES` does not imply `SELF`)."""
    from datetime import UTC, date, datetime

    from hrms.modules.employee.models import EmployeeAssignment
    from hrms.modules.identity.permissions import EMPLOYEE_VIEW

    headers, company_id, user_id = await _register_tenant(client)
    try:
        manager, manager_entity = await _setup_employee_and_entity(client, headers)
        await _create_employment(
            client, headers, employee_id=manager["id"], legal_entity_id=manager_entity["id"]
        )
        report, report_entity = await _setup_employee_and_entity(client, headers)
        await _create_employment(
            client, headers, employee_id=report["id"], legal_entity_id=report_entity["id"]
        )
        unrelated, unrelated_entity = await _setup_employee_and_entity(client, headers)
        await _create_employment(
            client, headers, employee_id=unrelated["id"], legal_entity_id=unrelated_entity["id"]
        )

        factory = get_session_factory()
        async with factory() as session:
            now_ts = datetime.now(UTC)
            session.add(
                EmployeeAssignment(
                    id=uuid4(),
                    company_id=company_id,
                    employee_id=UUID(report["id"]),
                    reporting_manager_id=UUID(manager["id"]),
                    effective_from=date(2027, 6, 1),
                    effective_to=None,
                    created_at=now_ts,
                    updated_at=now_ts,
                )
            )
            await session.commit()

        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[EMPLOYEE_VIEW],
            data_scope="REPORTEES",
            caller_employee_id=UUID(manager["id"]),
        )

        report_resp = await client.get(
            f"/v1/employees/{report['id']}/employments", headers=scoped_headers
        )
        assert report_resp.status_code == 200

        unrelated_resp = await client.get(
            f"/v1/employees/{unrelated['id']}/employments", headers=scoped_headers
        )
        assert unrelated_resp.status_code == 404

        own_resp = await client.get(
            f"/v1/employees/{manager['id']}/employments", headers=scoped_headers
        )
        assert own_resp.status_code == 404
    finally:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                text("DELETE FROM employee_assignment WHERE company_id = :cid"),
                {"cid": str(company_id)},
            )
            await session.commit()
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_list_employments_company_scope_sees_any_employee(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`COMPANY` scope (the default for every existing seeded role) still sees every employee's
    employment history — the fix does not narrow `COMPANY`-scoped access at all."""
    from hrms.modules.identity.permissions import EMPLOYEE_VIEW

    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, legal_entity = await _setup_employee_and_entity(client, headers)
        await _create_employment(
            client, headers, employee_id=employee["id"], legal_entity_id=legal_entity["id"]
        )

        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[EMPLOYEE_VIEW],
            data_scope="COMPANY",
            caller_employee_id=None,
        )

        response = await client.get(
            f"/v1/employees/{employee['id']}/employments", headers=scoped_headers
        )
        assert response.status_code == 200
        assert len(response.json()["data"]) == 1
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_list_employments_as_of_cannot_bypass_scope(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`?as_of=` is a *which historical row*, not a *whose employee* concern — an out-of-scope
    caller cannot use `as_of` to bypass the scope check; the check runs before the `as_of`
    branch."""
    from hrms.modules.identity.permissions import EMPLOYEE_VIEW

    headers, company_id, user_id = await _register_tenant(client)
    try:
        self_employee, self_entity = await _setup_employee_and_entity(client, headers)
        other_employee, other_entity = await _setup_employee_and_entity(client, headers)
        await _create_employment(
            client, headers, employee_id=other_employee["id"], legal_entity_id=other_entity["id"]
        )

        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[EMPLOYEE_VIEW],
            data_scope="SELF",
            caller_employee_id=UUID(self_employee["id"]),
        )

        response = await client.get(
            f"/v1/employees/{other_employee['id']}/employments?as_of=2027-06-01",
            headers=scoped_headers,
        )
        assert response.status_code == 404
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_get_employment_cross_tenant_scoped_actor_denied(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Tenant mismatch is caught before scope even runs (`get_tenant_context`) — a scoped actor
    in tenant A cannot see tenant B's employment records by any scope value, cross-tenant check
    and data-scope check compose correctly."""
    from hrms.modules.identity.permissions import EMPLOYEE_VIEW

    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        self_employee_a, entity_a = await _setup_employee_and_entity(client, headers_a)
        employee_b, entity_b = await _setup_employee_and_entity(client, headers_b)
        employment_b = await _create_employment(
            client, headers_b, employee_id=employee_b["id"], legal_entity_id=entity_b["id"]
        )

        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_a,
            permission_codes=[EMPLOYEE_VIEW],
            data_scope="COMPANY",
            caller_employee_id=UUID(self_employee_a["id"]),
        )

        response = await client.get(
            f"/v1/employees/{employee_b['id']}/employments/{employment_b['id']}",
            headers={**scoped_headers, "X-Company-Id": str(company_a)},
        )
        assert response.status_code == 404
    finally:
        await _teardown(company_id=company_a, user_id=user_a)
        await _teardown(company_id=company_b, user_id=user_b)
        await _cleanup_scoped_users()


# --- Data-scope enforcement (write path, Finding C / F9) ---------------------------------------
#
# `docs/modules/employee/39_EMPLOYEE_ACCESS_CONTROL_IMPLEMENTATION_PLAN.md` Phase 2: every write
# route in this module now resolves the caller's `DataScope` and enforces it against the target
# employee, in addition to the bare permission check that already existed. An out-of-scope target
# behaves exactly like a nonexistent one (`404`, not `403`).


async def test_create_employment_reportees_scope_target_visibility(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A caller holding `EMPLOYEE.CREATE` at `REPORTEES` scope can create an employment episode
    for a direct report, but not for an employee outside their reportee set."""
    from datetime import UTC, date, datetime

    from hrms.modules.employee.models import EmployeeAssignment
    from hrms.modules.employee.permissions import EMPLOYEE_CREATE

    headers, company_id, user_id = await _register_tenant(client)
    try:
        manager, _manager_entity = await _setup_employee_and_entity(client, headers)
        report, report_entity = await _setup_employee_and_entity(client, headers)
        unrelated, unrelated_entity = await _setup_employee_and_entity(client, headers)

        factory = get_session_factory()
        async with factory() as session:
            now = datetime.now(UTC)
            session.add(
                EmployeeAssignment(
                    id=uuid4(),
                    company_id=company_id,
                    employee_id=UUID(report["id"]),
                    reporting_manager_id=UUID(manager["id"]),
                    effective_from=date(2027, 6, 1),
                    effective_to=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.commit()

        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[EMPLOYEE_CREATE],
            data_scope="REPORTEES",
            caller_employee_id=UUID(manager["id"]),
        )

        in_scope = await client.post(
            f"/v1/employees/{report['id']}/employments",
            headers=scoped_headers,
            json={"legal_entity_id": report_entity["id"], "joining_date": "2027-06-01"},
        )
        assert in_scope.status_code == 201, in_scope.text

        out_of_scope = await client.post(
            f"/v1/employees/{unrelated['id']}/employments",
            headers=scoped_headers,
            json={"legal_entity_id": unrelated_entity["id"], "joining_date": "2027-06-01"},
        )
        assert out_of_scope.status_code == 404
    finally:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                text("DELETE FROM employee_assignment WHERE company_id = :cid"),
                {"cid": str(company_id)},
            )
            await session.commit()
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_update_employment_reportees_scope_target_visibility(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A caller holding `EMPLOYEE.UPDATE` at `REPORTEES` scope can update a direct report's
    employment, but an unrelated employee's employment is invisible (`404`), never `403`."""
    from datetime import UTC, date, datetime

    from hrms.modules.employee.models import EmployeeAssignment
    from hrms.modules.employee.permissions import EMPLOYEE_UPDATE

    headers, company_id, user_id = await _register_tenant(client)
    try:
        manager, _manager_entity = await _setup_employee_and_entity(client, headers)
        report, report_entity = await _setup_employee_and_entity(client, headers)
        report_employment = await _create_employment(
            client, headers, employee_id=report["id"], legal_entity_id=report_entity["id"]
        )
        unrelated, unrelated_entity = await _setup_employee_and_entity(client, headers)
        unrelated_employment = await _create_employment(
            client, headers, employee_id=unrelated["id"], legal_entity_id=unrelated_entity["id"]
        )
        other_entity = await _create_legal_entity(client, headers, name="Other Legal Entity")

        factory = get_session_factory()
        async with factory() as session:
            now = datetime.now(UTC)
            session.add(
                EmployeeAssignment(
                    id=uuid4(),
                    company_id=company_id,
                    employee_id=UUID(report["id"]),
                    reporting_manager_id=UUID(manager["id"]),
                    effective_from=date(2027, 6, 1),
                    effective_to=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.commit()

        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[EMPLOYEE_UPDATE],
            data_scope="REPORTEES",
            caller_employee_id=UUID(manager["id"]),
        )

        in_scope = await client.patch(
            f"/v1/employees/{report['id']}/employments/{report_employment['id']}",
            headers={**scoped_headers, "If-Match": str(report_employment["version"])},
            json={"legal_entity_id": other_entity["id"]},
        )
        assert in_scope.status_code == 200, in_scope.text

        out_of_scope = await client.patch(
            f"/v1/employees/{unrelated['id']}/employments/{unrelated_employment['id']}",
            headers={**scoped_headers, "If-Match": str(unrelated_employment["version"])},
            json={"legal_entity_id": other_entity["id"]},
        )
        assert out_of_scope.status_code == 404
    finally:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                text("DELETE FROM employee_assignment WHERE company_id = :cid"),
                {"cid": str(company_id)},
            )
            await session.commit()
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_terminate_employment_reportees_scope_target_visibility(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """A caller holding `EMPLOYEE.TERMINATE` at `REPORTEES` scope can terminate a direct
    report's employment, but an unrelated employee's employment is invisible (`404`), never
    `403` — the exact scenario `39_...PLAN.md` §13 names as the concrete write-path risk."""
    from datetime import UTC, date, datetime

    from hrms.modules.employee.models import EmployeeAssignment
    from hrms.modules.employee.permissions import EMPLOYEE_TERMINATE

    headers, company_id, user_id = await _register_tenant(client)
    try:
        manager, _manager_entity = await _setup_employee_and_entity(client, headers)
        report, report_entity = await _setup_employee_and_entity(client, headers)
        report_employment = await _create_employment(
            client, headers, employee_id=report["id"], legal_entity_id=report_entity["id"]
        )
        unrelated, unrelated_entity = await _setup_employee_and_entity(client, headers)
        unrelated_employment = await _create_employment(
            client, headers, employee_id=unrelated["id"], legal_entity_id=unrelated_entity["id"]
        )

        factory = get_session_factory()
        async with factory() as session:
            now = datetime.now(UTC)
            session.add(
                EmployeeAssignment(
                    id=uuid4(),
                    company_id=company_id,
                    employee_id=UUID(report["id"]),
                    reporting_manager_id=UUID(manager["id"]),
                    effective_from=date(2027, 6, 1),
                    effective_to=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.commit()

        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id,
            permission_codes=[EMPLOYEE_TERMINATE],
            data_scope="REPORTEES",
            caller_employee_id=UUID(manager["id"]),
        )

        out_of_scope = await client.post(
            f"/v1/employees/{unrelated['id']}/employments/{unrelated_employment['id']}/terminate",
            headers={**scoped_headers, "If-Match": str(unrelated_employment["version"])},
            json={"last_working_day": "2027-07-01"},
        )
        assert out_of_scope.status_code == 404

        in_scope = await client.post(
            f"/v1/employees/{report['id']}/employments/{report_employment['id']}/terminate",
            headers={**scoped_headers, "If-Match": str(report_employment["version"])},
            json={"last_working_day": "2027-07-01"},
        )
        assert in_scope.status_code == 200, in_scope.text
    finally:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                text("DELETE FROM employee_assignment WHERE company_id = :cid"),
                {"cid": str(company_id)},
            )
            await session.commit()
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_create_employment_cross_tenant_scoped_actor_denied(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Cross-tenant + data-scope composed on a write route: a `COMPANY`-scoped actor in tenant A
    cannot create an employment episode for tenant B's employee, tenant isolation wins first."""
    from hrms.modules.employee.permissions import EMPLOYEE_CREATE

    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        _self_employee_a, _entity_a = await _setup_employee_and_entity(client, headers_a)
        employee_b, entity_b = await _setup_employee_and_entity(client, headers_b)

        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_a,
            permission_codes=[EMPLOYEE_CREATE],
            data_scope="COMPANY",
        )

        response = await client.post(
            f"/v1/employees/{employee_b['id']}/employments",
            headers={**scoped_headers, "X-Company-Id": str(company_a)},
            json={"legal_entity_id": entity_b["id"], "joining_date": "2027-06-01"},
        )
        assert response.status_code == 404
    finally:
        await _teardown(company_id=company_a, user_id=user_a)
        await _teardown(company_id=company_b, user_id=user_b)
        await _cleanup_scoped_users()


# --- Termination closes current assignment/compensation (E-03 -> E-04/E-06 lifecycle fix) ----
#
# `docs/modules/employee/22_TERMINATION_ASSIGNMENT_COMPENSATION_PLAN.md` — `terminate_employment`
# now closes the employee's currently-open `employee_assignment`/`employee_compensation` row (if
# any) at `effective_to = last_working_day`, in the same transaction as the `employment` update.


async def _teardown_with_assignment_and_compensation(
    *, company_id: UUID, user_id: UUID | None
) -> None:
    """FK-safe order: compensation/assignment (-> employee/org) -> employment (-> employee,
    legal_entity) -> employee (-> number_series) -> org structure -> the rest
    (legal_entity/company/roles/user)."""
    await _cleanup_compensations(company_id=company_id)
    await _cleanup_assignments(company_id=company_id)
    await _cleanup_employments(company_id=company_id)
    await _cleanup_employees(company_id=company_id)
    await _cleanup_org_structure(company_id=company_id)
    await _cleanup(company_id=company_id, user_id=user_id)


async def _teardown_with_compensation_only(*, company_id: UUID, user_id: UUID | None) -> None:
    await _cleanup_compensations(company_id=company_id)
    await _cleanup_employments(company_id=company_id)
    await _cleanup_employees(company_id=company_id)
    await _cleanup(company_id=company_id, user_id=user_id)


async def test_terminate_employment_closes_current_assignment_and_compensation(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Plan §17 Basic: an active employment with one open assignment and one open
    compensation — terminating closes both at `effective_to = last_working_day`, and all three
    audit rows (`EMPLOYMENT_TERMINATED`, `ASSIGNMENT_CHANGED`, `COMPENSATION_REVISED`) exist
    with the correct entity and before/after boundary."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, org, employment = await _setup_employee_with_employment(
            client, headers, joining_date="2027-06-01"
        )
        assignment = await _create_assignment(
            client,
            headers,
            employee_id=employee["id"],
            effective_from="2027-06-01",
            change_type="INITIAL",
            branch_id=org["branch"]["id"],
            department_id=org["department"]["id"],
            designation_id=org["designation"]["id"],
        )
        compensation = await _create_compensation(
            client, headers, employee_id=employee["id"], **_joining_payload()
        )

        response = await client.post(
            f"/v1/employees/{employee['id']}/employments/{employment['id']}/terminate",
            headers={**headers, "If-Match": str(employment["version"])},
            json={"last_working_day": "2030-09-30"},
        )
        assert response.status_code == 200
        assert response.json()["data"]["status"] == "TERMINATED"
        assert response.json()["data"]["last_working_day"] == "2030-09-30"

        assignment_after = await client.get(
            f"/v1/employees/{employee['id']}/assignments/{assignment['id']}", headers=headers
        )
        assert assignment_after.json()["data"]["effective_to"] == "2030-09-30"

        compensation_after = await client.get(
            f"/v1/employees/{employee['id']}/compensation/{compensation['id']}", headers=headers
        )
        assert compensation_after.json()["data"]["effective_to"] == "2030-09-30"

        factory = get_session_factory()
        async with factory() as session:
            audit_rows = (
                (
                    await session.execute(
                        select(AuditLog).where(
                            AuditLog.company_id == company_id,
                            AuditLog.action.in_(
                                [
                                    "EMPLOYMENT_TERMINATED",
                                    "ASSIGNMENT_CHANGED",
                                    "COMPENSATION_REVISED",
                                ]
                            ),
                        )
                    )
                )
                .scalars()
                .all()
            )
            actions_present = {row.action for row in audit_rows}
            assert actions_present == {
                "EMPLOYMENT_TERMINATED",
                "ASSIGNMENT_CHANGED",
                "COMPENSATION_REVISED",
            }

            # The employee's very first assignment/compensation write also records an
            # `ASSIGNMENT_CHANGED`/`COMPENSATION_REVISED` row (with `before=None`) — select the
            # *closure* event specifically by its `after.effective_to`, not just the action name.
            assignment_audit = next(
                row
                for row in audit_rows
                if row.action == "ASSIGNMENT_CHANGED"
                and row.after_json is not None
                and row.after_json["effective_to"] == "2030-09-30"
            )
            assert assignment_audit.entity_type == "employee_assignment"
            assert assignment_audit.entity_id == UUID(assignment["id"])
            assert assignment_audit.before_json["effective_to"] is None
            for field in ("branch_id", "department_id", "designation_id", "employee_id"):
                assert assignment_audit.before_json[field] == assignment_audit.after_json[field]

            compensation_audit = next(
                row
                for row in audit_rows
                if row.action == "COMPENSATION_REVISED"
                and row.after_json is not None
                and row.after_json["effective_to"] == "2030-09-30"
            )
            assert compensation_audit.entity_type == "employee_compensation"
            assert compensation_audit.entity_id == UUID(compensation["id"])
            assert compensation_audit.before_json["effective_to"] is None
            assert (
                compensation_audit.before_json["annual_ctc_minor"]
                == compensation_audit.after_json["annual_ctc_minor"]
            )

            employment_audit = next(
                row for row in audit_rows if row.action == "EMPLOYMENT_TERMINATED"
            )
            assert employment_audit.entity_type == "employment"
            assert employment_audit.entity_id == UUID(employment["id"])
    finally:
        await _teardown_with_assignment_and_compensation(company_id=company_id, user_id=user_id)


async def test_terminate_employment_no_assignment_still_succeeds(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Plan §17 Missing data: no current assignment exists (only compensation) — termination
    still succeeds, no `ASSIGNMENT_CHANGED` audit row is written, nothing errors."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, legal_entity = await _setup_employee_and_entity(client, headers)
        employment = await _create_employment(
            client, headers, employee_id=employee["id"], legal_entity_id=legal_entity["id"]
        )
        compensation = await _create_compensation(
            client, headers, employee_id=employee["id"], **_joining_payload()
        )

        response = await client.post(
            f"/v1/employees/{employee['id']}/employments/{employment['id']}/terminate",
            headers={**headers, "If-Match": str(employment["version"])},
            json={"last_working_day": "2030-09-30"},
        )
        assert response.status_code == 200

        compensation_after = await client.get(
            f"/v1/employees/{employee['id']}/compensation/{compensation['id']}", headers=headers
        )
        assert compensation_after.json()["data"]["effective_to"] == "2030-09-30"

        factory = get_session_factory()
        async with factory() as session:
            actions = (
                (
                    await session.execute(
                        select(AuditLog.action).where(
                            AuditLog.company_id == company_id,
                            AuditLog.entity_type == "employee_assignment",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert actions == []
    finally:
        await _teardown_with_compensation_only(company_id=company_id, user_id=user_id)


async def test_terminate_employment_no_compensation_still_succeeds(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Plan §17 Missing data: no current compensation exists (only assignment) — termination
    still succeeds, no `COMPENSATION_REVISED` audit row is written."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, org, employment = await _setup_employee_with_employment(
            client, headers, joining_date="2027-06-01"
        )
        assignment = await _create_assignment(
            client,
            headers,
            employee_id=employee["id"],
            effective_from="2027-06-01",
            change_type="INITIAL",
            branch_id=org["branch"]["id"],
            department_id=org["department"]["id"],
            designation_id=org["designation"]["id"],
        )

        response = await client.post(
            f"/v1/employees/{employee['id']}/employments/{employment['id']}/terminate",
            headers={**headers, "If-Match": str(employment["version"])},
            json={"last_working_day": "2030-09-30"},
        )
        assert response.status_code == 200

        assignment_after = await client.get(
            f"/v1/employees/{employee['id']}/assignments/{assignment['id']}", headers=headers
        )
        assert assignment_after.json()["data"]["effective_to"] == "2030-09-30"

        factory = get_session_factory()
        async with factory() as session:
            actions = (
                (
                    await session.execute(
                        select(AuditLog.action).where(
                            AuditLog.company_id == company_id,
                            AuditLog.entity_type == "employee_compensation",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert actions == []
    finally:
        await _teardown_with_assignment_and_compensation(company_id=company_id, user_id=user_id)


async def test_terminate_employment_leaves_historical_rows_untouched(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Plan §17 Historical data: prior transfers/revisions leave closed historical rows behind
    a current open row. Terminating must only touch the one currently-open row per table —
    closed historical rows are byte-for-byte identical before and after."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, org, employment = await _setup_employee_with_employment(
            client, headers, joining_date="2027-06-01"
        )
        first_assignment = await _create_assignment(
            client,
            headers,
            employee_id=employee["id"],
            effective_from="2027-06-01",
            change_type="INITIAL",
            branch_id=org["branch"]["id"],
            department_id=org["department"]["id"],
            designation_id=org["designation"]["id"],
        )
        new_department = await _create_department(client, headers, name="Sales")
        current_assignment = await _create_assignment(
            client,
            headers,
            employee_id=employee["id"],
            if_match=str(first_assignment["version"]),
            effective_from="2028-04-01",
            change_type="TRANSFER",
            department_id=new_department["id"],
        )

        first_compensation = await _create_compensation(
            client, headers, employee_id=employee["id"], **_joining_payload()
        )
        current_compensation = await _create_compensation(
            client,
            headers,
            employee_id=employee["id"],
            if_match=str(first_compensation["version"]),
            effective_from="2029-01-01",
            annual_ctc_minor=15_00_000_00,
            currency="INR",
            revision_type="ANNUAL",
            revision_reason="Annual increment",
        )

        # Snapshots taken once each historical row has already been closed by its own
        # transfer/revision write (`version` incremented then) — the invariant under test is
        # "unchanged by *termination*", not "unchanged since creation".
        first_assignment_before_terminate = (
            await client.get(
                f"/v1/employees/{employee['id']}/assignments/{first_assignment['id']}",
                headers=headers,
            )
        ).json()["data"]
        first_compensation_before_terminate = (
            await client.get(
                f"/v1/employees/{employee['id']}/compensation/{first_compensation['id']}",
                headers=headers,
            )
        ).json()["data"]

        response = await client.post(
            f"/v1/employees/{employee['id']}/employments/{employment['id']}/terminate",
            headers={**headers, "If-Match": str(employment["version"])},
            json={"last_working_day": "2030-09-30"},
        )
        assert response.status_code == 200

        first_assignment_after = await client.get(
            f"/v1/employees/{employee['id']}/assignments/{first_assignment['id']}",
            headers=headers,
        )
        # Untouched — same historical boundary the transfer itself set, not the exit date, and
        # byte-for-byte identical to the pre-terminate snapshot (including `version`).
        assert first_assignment_after.json()["data"]["effective_to"] == "2028-03-31"
        assert first_assignment_after.json()["data"] == first_assignment_before_terminate

        current_assignment_after = await client.get(
            f"/v1/employees/{employee['id']}/assignments/{current_assignment['id']}",
            headers=headers,
        )
        assert current_assignment_after.json()["data"]["effective_to"] == "2030-09-30"

        first_compensation_after = await client.get(
            f"/v1/employees/{employee['id']}/compensation/{first_compensation['id']}",
            headers=headers,
        )
        assert first_compensation_after.json()["data"]["effective_to"] == "2028-12-31"
        assert first_compensation_after.json()["data"] == first_compensation_before_terminate

        current_compensation_after = await client.get(
            f"/v1/employees/{employee['id']}/compensation/{current_compensation['id']}",
            headers=headers,
        )
        assert current_compensation_after.json()["data"]["effective_to"] == "2030-09-30"
    finally:
        await _teardown_with_assignment_and_compensation(company_id=company_id, user_id=user_id)


async def test_terminate_employment_future_dated_assignment_left_open(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Plan §8/§19 OD-1 (explicitly open, resolved for this implementation as "leave the row
    open, termination still succeeds" rather than inventing a rejection rule): the current
    assignment's `effective_from` is after the new `last_working_day` — a transfer already
    scheduled to start after what turns out to be the employee's actual exit. Closing it would
    produce an invalid `effective_to < effective_from` range, so it is left open."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, org, employment = await _setup_employee_with_employment(
            client, headers, joining_date="2027-06-01"
        )
        future_assignment = await _create_assignment(
            client,
            headers,
            employee_id=employee["id"],
            effective_from="2031-01-01",
            change_type="INITIAL",
            branch_id=org["branch"]["id"],
            department_id=org["department"]["id"],
            designation_id=org["designation"]["id"],
        )

        response = await client.post(
            f"/v1/employees/{employee['id']}/employments/{employment['id']}/terminate",
            headers={**headers, "If-Match": str(employment["version"])},
            json={"last_working_day": "2030-09-30"},
        )
        assert response.status_code == 200
        assert response.json()["data"]["status"] == "TERMINATED"

        assignment_after = await client.get(
            f"/v1/employees/{employee['id']}/assignments/{future_assignment['id']}",
            headers=headers,
        )
        assert assignment_after.json()["data"]["effective_to"] is None
        assert assignment_after.json()["data"]["version"] == future_assignment["version"]

        factory = get_session_factory()
        async with factory() as session:
            audit_rows = (
                (
                    await session.execute(
                        select(AuditLog).where(
                            AuditLog.company_id == company_id,
                            AuditLog.entity_type == "employee_assignment",
                        )
                    )
                )
                .scalars()
                .all()
            )
            # Exactly one `ASSIGNMENT_CHANGED` row exists — from the row's own creation
            # (`before=None`). Termination did not close it, so no second row was added.
            assert len(audit_rows) == 1
            assert audit_rows[0].before_json is None
    finally:
        await _teardown_with_assignment_and_compensation(company_id=company_id, user_id=user_id)


async def test_terminate_employment_future_dated_compensation_left_open(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Mirrors `test_terminate_employment_future_dated_assignment_left_open` for
    `employee_compensation` — same OD-1 rule (plan §8/§19)."""
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
        future_compensation = await _create_compensation(
            client,
            headers,
            employee_id=employee["id"],
            **_joining_payload(effective_from="2031-01-01"),
        )

        response = await client.post(
            f"/v1/employees/{employee['id']}/employments/{employment['id']}/terminate",
            headers={**headers, "If-Match": str(employment["version"])},
            json={"last_working_day": "2030-09-30"},
        )
        assert response.status_code == 200

        compensation_after = await client.get(
            f"/v1/employees/{employee['id']}/compensation/{future_compensation['id']}",
            headers=headers,
        )
        assert compensation_after.json()["data"]["effective_to"] is None
        assert compensation_after.json()["data"]["version"] == future_compensation["version"]
    finally:
        await _teardown_with_compensation_only(company_id=company_id, user_id=user_id)


async def test_terminate_employment_rolls_back_on_compensation_close_failure(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Plan §10/§17 Concurrency — the concrete "rollback undoes everything" test: assignment
    closes successfully, then compensation's close reports a lost concurrency race (`None`).
    The whole request must roll back: `employment` stays `ACTIVE`, the assignment stays open,
    the compensation stays open, and none of the three audit rows are persisted. Simulated with
    a real DB session (`session_scope`, mirroring `get_session`'s own commit/rollback wrapper)
    and a patched `close_compensation` — a genuine cross-request race is not deterministically
    reproducible in a test, but the failure *outcome* (a stale-version `None`) is identical."""
    from datetime import date
    from unittest.mock import AsyncMock

    from hrms.core.db.session import session_scope
    from hrms.modules.employee.exceptions import StaleResourceError
    from hrms.modules.employee.schemas import EmploymentTerminate
    from hrms.modules.employee.service import EmploymentService

    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, org, employment = await _setup_employee_with_employment(
            client, headers, joining_date="2027-06-01"
        )
        assignment = await _create_assignment(
            client,
            headers,
            employee_id=employee["id"],
            effective_from="2027-06-01",
            change_type="INITIAL",
            branch_id=org["branch"]["id"],
            department_id=org["department"]["id"],
            designation_id=org["designation"]["id"],
        )
        compensation = await _create_compensation(
            client, headers, employee_id=employee["id"], **_joining_payload()
        )

        # The exception must propagate all the way out of `session_scope`'s own `async with`
        # block for its `except Exception: rollback(); raise` branch to run at all — catching it
        # any closer in (e.g. around just the `terminate_employment` call) would let
        # `session_scope` reach its own `await session.commit()` unaware anything failed.
        with pytest.raises(StaleResourceError):
            async with session_scope(company_id=str(company_id)) as session:
                service = EmploymentService(session)
                service._compensation_repo.close_compensation = AsyncMock(return_value=None)
                await service.terminate_employment(
                    company_id,
                    UUID(employee["id"]),
                    UUID(employment["id"]),
                    EmploymentTerminate(last_working_day=date(2030, 9, 30)),
                    expected_version=employment["version"],
                    actor_user_id=user_id,
                )

        # Verified against a fresh session — `session_scope` rolled back the transaction the
        # (failed) request ran in, so this must see the pre-request state, not a partial write.
        employment_after = await client.get(
            f"/v1/employees/{employee['id']}/employments/{employment['id']}", headers=headers
        )
        assert employment_after.json()["data"]["status"] == "ACTIVE"
        assert employment_after.json()["data"]["version"] == employment["version"]

        assignment_after = await client.get(
            f"/v1/employees/{employee['id']}/assignments/{assignment['id']}", headers=headers
        )
        assert assignment_after.json()["data"]["effective_to"] is None
        assert assignment_after.json()["data"]["version"] == assignment["version"]

        compensation_after = await client.get(
            f"/v1/employees/{employee['id']}/compensation/{compensation['id']}", headers=headers
        )
        assert compensation_after.json()["data"]["effective_to"] is None
        assert compensation_after.json()["data"]["version"] == compensation["version"]

        factory = get_session_factory()
        async with factory() as session:
            # `EMPLOYMENT_TERMINATED` only ever fires from a termination — must be absent
            # entirely. `ASSIGNMENT_CHANGED`/`COMPENSATION_REVISED` each already have one row
            # from the row's own creation (`before=None`) — the rolled-back close must not have
            # added a second (`before` = the pre-close snapshot).
            employment_actions = (
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
            assert employment_actions == []

            assignment_audit_rows = (
                (
                    await session.execute(
                        select(AuditLog).where(
                            AuditLog.entity_id == UUID(assignment["id"]),
                            AuditLog.action == "ASSIGNMENT_CHANGED",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(assignment_audit_rows) == 1
            assert assignment_audit_rows[0].before_json is None

            compensation_audit_rows = (
                (
                    await session.execute(
                        select(AuditLog).where(
                            AuditLog.entity_id == UUID(compensation["id"]),
                            AuditLog.action == "COMPENSATION_REVISED",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(compensation_audit_rows) == 1
            assert compensation_audit_rows[0].before_json is None
    finally:
        await _teardown_with_assignment_and_compensation(company_id=company_id, user_id=user_id)


async def test_terminate_employment_does_not_affect_other_tenant_assignment_or_compensation(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Tenant isolation for the new closure behavior: terminating tenant A's employment must
    never touch tenant B's assignment/compensation rows, even for a coincidentally-similar
    setup — the new repository calls are `(company_id, employee_id)`-filtered exactly like
    every other method on `EmployeeAssignmentRepository`/`EmployeeCompensationRepository`."""
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        employee_a, org_a, employment_a = await _setup_employee_with_employment(
            client, headers_a, joining_date="2027-06-01"
        )
        await _create_assignment(
            client,
            headers_a,
            employee_id=employee_a["id"],
            effective_from="2027-06-01",
            change_type="INITIAL",
            branch_id=org_a["branch"]["id"],
            department_id=org_a["department"]["id"],
            designation_id=org_a["designation"]["id"],
        )
        await _create_compensation(
            client, headers_a, employee_id=employee_a["id"], **_joining_payload()
        )

        employee_b, org_b, _employment_b = await _setup_employee_with_employment(
            client, headers_b, joining_date="2027-06-01"
        )
        assignment_b = await _create_assignment(
            client,
            headers_b,
            employee_id=employee_b["id"],
            effective_from="2027-06-01",
            change_type="INITIAL",
            branch_id=org_b["branch"]["id"],
            department_id=org_b["department"]["id"],
            designation_id=org_b["designation"]["id"],
        )
        compensation_b = await _create_compensation(
            client, headers_b, employee_id=employee_b["id"], **_joining_payload()
        )

        response = await client.post(
            f"/v1/employees/{employee_a['id']}/employments/{employment_a['id']}/terminate",
            headers={**headers_a, "If-Match": str(employment_a["version"])},
            json={"last_working_day": "2030-09-30"},
        )
        assert response.status_code == 200

        assignment_b_after = await client.get(
            f"/v1/employees/{employee_b['id']}/assignments/{assignment_b['id']}",
            headers=headers_b,
        )
        assert assignment_b_after.json()["data"]["effective_to"] is None
        assert assignment_b_after.json()["data"]["version"] == assignment_b["version"]

        compensation_b_after = await client.get(
            f"/v1/employees/{employee_b['id']}/compensation/{compensation_b['id']}",
            headers=headers_b,
        )
        assert compensation_b_after.json()["data"]["effective_to"] is None
        assert compensation_b_after.json()["data"]["version"] == compensation_b["version"]
    finally:
        await _teardown_with_assignment_and_compensation(company_id=company_a, user_id=user_a)
        await _teardown_with_assignment_and_compensation(company_id=company_b, user_id=user_b)
