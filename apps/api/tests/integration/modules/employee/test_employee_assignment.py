"""Integration tests for the Employee Assignment API (E-04) —
`/v1/employees/{employee_id}/assignments*`.

Follows the same checklist as `test_employment.py` (E-03): create, list, get, mass-assignment
rejection, stale-version conflict, cross-tenant isolation, permission matrix — plus the
scenarios specific to this slice: the `employee_assignment_no_overlap` GiST exclusion
constraint's friendly-error surface (both via the service's own close-then-insert path and via
a raw insert that bypasses it entirely), the as-of-date read pattern, transfer/promotion
carry-forward semantics, the "no covering employment" rule, and rehire compatibility.
"""

from datetime import date
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

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
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _create_legal_entity(
    client: AsyncClient, headers: dict[str, str], name: str = "Acme Legal Entity"
) -> dict[str, Any]:
    response = await client.post("/v1/legal-entities", headers=headers, json={"name": name})
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _create_branch(
    client: AsyncClient, headers: dict[str, str], legal_entity_id: str, name: str = "HQ Branch"
) -> dict[str, Any]:
    response = await client.post(
        "/v1/branches", headers=headers, json={"legal_entity_id": legal_entity_id, "name": name}
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _create_department(
    client: AsyncClient, headers: dict[str, str], name: str = "Engineering", **extra: Any
) -> dict[str, Any]:
    response = await client.post("/v1/departments", headers=headers, json={"name": name, **extra})
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _create_designation(
    client: AsyncClient, headers: dict[str, str], title: str = "Software Engineer", **extra: Any
) -> dict[str, Any]:
    response = await client.post(
        "/v1/designations", headers=headers, json={"title": title, **extra}
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _create_grade(
    client: AsyncClient, headers: dict[str, str], code: str = "L5", **extra: Any
) -> dict[str, Any]:
    response = await client.post(
        "/v1/grades", headers=headers, json={"code": code, "name": "Senior Engineer", **extra}
    )
    assert response.status_code == 201, response.text
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


async def _create_shift(
    client: AsyncClient, headers: dict[str, str], code: str = "GEN", **extra: Any
) -> dict[str, Any]:
    payload = {
        "code": code,
        "name": "General Shift",
        "start_time": "09:00",
        "end_time": "18:00",
        **extra,
    }
    response = await client.post("/v1/shifts", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _create_assignment(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    employee_id: str,
    if_match: str | None = None,
    expected_status: int = 201,
    **body: Any,
) -> dict[str, Any]:
    request_headers = dict(headers)
    if if_match is not None:
        request_headers["If-Match"] = if_match
    response = await client.post(
        f"/v1/employees/{employee_id}/assignments", headers=request_headers, json=body
    )
    assert response.status_code == expected_status, response.text
    return dict(response.json()["data"]) if expected_status < 400 else dict(response.json())


async def _setup_org_structure(client: AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    legal_entity = await _create_legal_entity(client, headers)
    branch = await _create_branch(client, headers, legal_entity_id=legal_entity["id"])
    department = await _create_department(client, headers, branch_id=branch["id"])
    designation = await _create_designation(client, headers, department_id=department["id"])
    grade = await _create_grade(client, headers)
    return {
        "legal_entity": legal_entity,
        "branch": branch,
        "department": department,
        "designation": designation,
        "grade": grade,
    }


async def _setup_employee_with_employment(
    client: AsyncClient, headers: dict[str, str], *, joining_date: str = "2027-06-01"
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    employee = await _create_employee(client, headers)
    org = await _setup_org_structure(client, headers)
    employment = await _create_employment(
        client,
        headers,
        employee_id=employee["id"],
        legal_entity_id=org["legal_entity"]["id"],
        joining_date=joining_date,
    )
    return employee, org, employment


async def _cleanup_assignments(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("DELETE FROM employee_assignment WHERE company_id = :cid"),
            {"cid": str(company_id)},
        )
        await session.commit()


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


async def _cleanup_org_structure(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        # FK-safe order: designation/grade (no dependents) -> department (SET NULL on branch) ->
        # branch (RESTRICT on legal_entity, so must go before `_cleanup`'s own legal_entity delete).
        await session.execute(
            text("DELETE FROM designation WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.execute(
            text("DELETE FROM grade WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.execute(
            text("DELETE FROM department WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.execute(
            text("DELETE FROM branch WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.commit()


async def _cleanup_shifts(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("DELETE FROM shift WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.commit()


async def _teardown(*, company_id: UUID, user_id: UUID | None) -> None:
    """Full teardown in FK-safe order: assignment (-> employee/branch/department/designation/
    shift) -> employment (-> employee, legal_entity) -> employee (-> number_series) ->
    designation/grade/department/branch/shift -> the rest (legal_entity/company/roles/user)."""
    await _cleanup_assignments(company_id=company_id)
    await _cleanup_employments(company_id=company_id)
    await _cleanup_employees(company_id=company_id)
    await _cleanup_org_structure(company_id=company_id)
    await _cleanup_shifts(company_id=company_id)
    await _cleanup(company_id=company_id, user_id=user_id)


# --- Create: first assignment (no current row) ---------------------------------------------


async def test_create_first_assignment_success(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, org, _employment = await _setup_employee_with_employment(client, headers)

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

        assert assignment["employee_id"] == employee["id"]
        assert assignment["branch_id"] == org["branch"]["id"]
        assert assignment["department_id"] == org["department"]["id"]
        assert assignment["designation_id"] == org["designation"]["id"]
        assert assignment["effective_to"] is None
        assert assignment["version"] == 1

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
            assert len(audit_rows) == 1
            assert audit_rows[0].action == "ASSIGNMENT_CHANGED"
            assert audit_rows[0].before_json is None
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_first_assignment_missing_mandatory_field_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, org, _employment = await _setup_employee_with_employment(client, headers)

        response = await client.post(
            f"/v1/employees/{employee['id']}/assignments",
            headers=headers,
            json={
                "effective_from": "2027-06-01",
                "change_type": "INITIAL",
                "branch_id": org["branch"]["id"],
                "department_id": org["department"]["id"],
                # designation_id omitted — mandatory for the very first assignment
            },
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "ASSIGNMENT_FIELDS_REQUIRED"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_assignment_without_covering_employment_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        org = await _setup_org_structure(client, headers)
        # No employment created for this employee at all.

        response = await client.post(
            f"/v1/employees/{employee['id']}/assignments",
            headers=headers,
            json={
                "effective_from": "2027-06-01",
                "change_type": "INITIAL",
                "branch_id": org["branch"]["id"],
                "department_id": org["department"]["id"],
                "designation_id": org["designation"]["id"],
            },
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "NO_ACTIVE_EMPLOYMENT"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_assignment_mass_assignment_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, org, _employment = await _setup_employee_with_employment(client, headers)

        response = await client.post(
            f"/v1/employees/{employee['id']}/assignments",
            headers=headers,
            json={
                "effective_from": "2027-06-01",
                "change_type": "INITIAL",
                "branch_id": org["branch"]["id"],
                "department_id": org["department"]["id"],
                "designation_id": org["designation"]["id"],
                "version": 99,
                "company_id": str(uuid4()),
            },
        )
        assert response.status_code == 422
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_assignment_unknown_employee_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        org = await _setup_org_structure(client, headers)
        response = await client.post(
            f"/v1/employees/{uuid4()}/assignments",
            headers=headers,
            json={
                "effective_from": "2027-06-01",
                "change_type": "INITIAL",
                "branch_id": org["branch"]["id"],
                "department_id": org["department"]["id"],
                "designation_id": org["designation"]["id"],
            },
        )
        assert response.status_code == 404
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_assignment_invalid_branch_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, org, _employment = await _setup_employee_with_employment(client, headers)

        response = await client.post(
            f"/v1/employees/{employee['id']}/assignments",
            headers=headers,
            json={
                "effective_from": "2027-06-01",
                "change_type": "INITIAL",
                "branch_id": str(uuid4()),
                "department_id": org["department"]["id"],
                "designation_id": org["designation"]["id"],
            },
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_BRANCH"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_assignment_reporting_manager_self_reference_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, org, _employment = await _setup_employee_with_employment(client, headers)

        response = await client.post(
            f"/v1/employees/{employee['id']}/assignments",
            headers=headers,
            json={
                "effective_from": "2027-06-01",
                "change_type": "INITIAL",
                "branch_id": org["branch"]["id"],
                "department_id": org["department"]["id"],
                "designation_id": org["designation"]["id"],
                "reporting_manager_id": employee["id"],
            },
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_REPORTING_MANAGER"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


# --- Read / list (incl. as-of) --------------------------------------------------------------


async def test_list_assignments_empty_state(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        response = await client.get(f"/v1/employees/{employee['id']}/assignments", headers=headers)
        assert response.status_code == 200
        assert response.json()["data"] == []
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_get_assignment_not_found(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee = await _create_employee(client, headers)
        response = await client.get(
            f"/v1/employees/{employee['id']}/assignments/{uuid4()}", headers=headers
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_list_assignments_as_of_date_boundaries(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The as-of-date read pattern against the brief's own worked example: 2027 placement,
    2028 department transfer — checked at the exact `effective_from`/`effective_to`
    boundaries and just outside them."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, org, _employment = await _setup_employee_with_employment(client, headers)
        first = await _create_assignment(
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
        await _create_assignment(
            client,
            headers,
            employee_id=employee["id"],
            if_match=str(first["version"]),
            effective_from="2028-04-01",
            change_type="TRANSFER",
            department_id=new_department["id"],
        )

        async def _as_of(day: str) -> list[dict[str, Any]]:
            resp = await client.get(
                f"/v1/employees/{employee['id']}/assignments",
                headers=headers,
                params={"as_of": day},
            )
            assert resp.status_code == 200
            return list(resp.json()["data"])

        assert len(await _as_of("2027-06-01")) == 1  # first row's start, inclusive
        assert (await _as_of("2028-03-31"))[0]["department_id"] == org["department"]["id"]
        assert (await _as_of("2028-04-01"))[0]["department_id"] == new_department["id"]
        assert await _as_of("2027-05-31") == []  # one day before the first row starts

        history = await client.get(f"/v1/employees/{employee['id']}/assignments", headers=headers)
        assert len(history.json()["data"]) == 2
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


# --- Transfer / promotion carry-forward -----------------------------------------------------


async def test_transfer_closes_current_and_carries_forward_unspecified_fields(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, org, _employment = await _setup_employee_with_employment(client, headers)
        first = await _create_assignment(
            client,
            headers,
            employee_id=employee["id"],
            effective_from="2027-06-01",
            change_type="INITIAL",
            branch_id=org["branch"]["id"],
            department_id=org["department"]["id"],
            designation_id=org["designation"]["id"],
        )
        new_branch = await _create_branch(
            client, headers, legal_entity_id=org["legal_entity"]["id"], name="Second Branch"
        )

        second = await _create_assignment(
            client,
            headers,
            employee_id=employee["id"],
            if_match=str(first["version"]),
            effective_from="2028-04-01",
            change_type="TRANSFER",
            change_reason="Relocation",
            branch_id=new_branch["id"],
        )

        assert second["branch_id"] == new_branch["id"]
        assert second["department_id"] == org["department"]["id"]  # carried forward
        assert second["designation_id"] == org["designation"]["id"]  # carried forward
        assert second["change_type"] == "TRANSFER"
        assert second["change_reason"] == "Relocation"

        first_after = await client.get(
            f"/v1/employees/{employee['id']}/assignments/{first['id']}", headers=headers
        )
        assert first_after.json()["data"]["effective_to"] == "2028-03-31"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_promotion_changes_designation_and_grade(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, org, _employment = await _setup_employee_with_employment(client, headers)
        first = await _create_assignment(
            client,
            headers,
            employee_id=employee["id"],
            effective_from="2027-06-01",
            change_type="INITIAL",
            branch_id=org["branch"]["id"],
            department_id=org["department"]["id"],
            designation_id=org["designation"]["id"],
        )
        new_designation = await _create_designation(client, headers, title="Staff Engineer")

        promoted = await _create_assignment(
            client,
            headers,
            employee_id=employee["id"],
            if_match=str(first["version"]),
            effective_from="2029-01-01",
            change_type="PROMOTION",
            designation_id=new_designation["id"],
            grade_id=org["grade"]["id"],
        )

        assert promoted["designation_id"] == new_designation["id"]
        assert promoted["grade_id"] == org["grade"]["id"]
        assert promoted["branch_id"] == org["branch"]["id"]  # carried forward
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_assignment_missing_if_match_when_current_exists_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, org, _employment = await _setup_employee_with_employment(client, headers)
        await _create_assignment(
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
            f"/v1/employees/{employee['id']}/assignments",
            headers=headers,
            json={"effective_from": "2028-01-01", "change_type": "TRANSFER"},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "ASSIGNMENT_VERSION_REQUIRED"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_assignment_stale_version_conflict(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, org, _employment = await _setup_employee_with_employment(client, headers)
        await _create_assignment(
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
            f"/v1/employees/{employee['id']}/assignments",
            headers={**headers, "If-Match": "999"},
            json={"effective_from": "2028-01-01", "change_type": "TRANSFER"},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "STALE_RESOURCE"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_create_assignment_effective_from_not_after_current_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, org, _employment = await _setup_employee_with_employment(client, headers)
        first = await _create_assignment(
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
            f"/v1/employees/{employee['id']}/assignments",
            headers={**headers, "If-Match": str(first["version"])},
            json={"effective_from": "2027-06-01", "change_type": "TRANSFER"},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_EFFECTIVE_FROM"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


# --- GiST exclusion constraint (§00 §16 "E-04" named first test) ---------------------------


async def test_raw_overlapping_insert_rejected_at_database_level(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Bypasses the service's own close-then-insert logic entirely — a raw `INSERT` with dates
    overlapping the existing row must be rejected by `employee_assignment_no_overlap` itself,
    proving the DB constraint is the actual backstop, not just an application-level check."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, org, _employment = await _setup_employee_with_employment(client, headers)
        first = await _create_assignment(
            client,
            headers,
            employee_id=employee["id"],
            effective_from="2027-06-01",
            change_type="INITIAL",
            branch_id=org["branch"]["id"],
            department_id=org["department"]["id"],
            designation_id=org["designation"]["id"],
        )

        factory = get_session_factory()
        async with factory() as session:
            await session.execute(text("SET LOCAL row_security = off"))
            with pytest.raises(IntegrityError):
                await session.execute(
                    text(
                        """
                        INSERT INTO employee_assignment
                            (id, company_id, employee_id, effective_from, effective_to,
                             created_at, updated_at, version)
                        VALUES
                            (gen_random_uuid(), :company_id, :employee_id, :effective_from, NULL,
                             now(), now(), 1)
                        """
                    ),
                    {
                        "company_id": str(company_id),
                        "employee_id": employee["id"],
                        "effective_from": date(2027, 12, 1),
                    },
                )
            await session.rollback()
        assert first["effective_to"] is None
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


# --- Rehire compatibility --------------------------------------------------------------------


async def test_rehire_first_assignment_after_gap(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The rejoin scenario: an employee's first spell ends, a gap follows, then a new
    employment episode starts. The rejoin's first assignment behaves exactly like any other
    "no current row to carry forward from" placement — no rehire-specific code path exists.

    Known limitation (documented in the implementation report, not silently glossed over
    here): terminating `employment #1` does **not** automatically close the still-open
    `employee_assignment` row from that spell (E-04's `create_assignment` is the only mutation
    path, and nothing in this slice hooks into `EmploymentService.terminate_employment`). The
    pre-exit assignment therefore remains open until the rehire's own `create_assignment` call
    closes it — at the rehire's `effective_from - 1 day`, not the original exit date. This test
    asserts that *actual* behavior rather than the idealized "closed exactly at exit" timeline
    `05_EMPLOYEE_ARCHITECTURE_DECISIONS.md` Part D illustrates.
    """
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, org, employment = await _setup_employee_with_employment(
            client, headers, joining_date="2027-06-01"
        )
        pre_exit = await _create_assignment(
            client,
            headers,
            employee_id=employee["id"],
            effective_from="2027-06-01",
            change_type="INITIAL",
            branch_id=org["branch"]["id"],
            department_id=org["department"]["id"],
            designation_id=org["designation"]["id"],
        )

        terminate = await client.post(
            f"/v1/employees/{employee['id']}/employments/{employment['id']}/terminate",
            headers={**headers, "If-Match": str(employment["version"])},
            json={"last_working_day": "2030-09-30"},
        )
        assert terminate.status_code == 200

        rehire_employment = await _create_employment(
            client,
            headers,
            employee_id=employee["id"],
            legal_entity_id=org["legal_entity"]["id"],
            joining_date="2034-02-01",
        )
        assert rehire_employment["previous_employment_id"] == employment["id"]

        rehire_assignment = await _create_assignment(
            client,
            headers,
            employee_id=employee["id"],
            if_match=str(pre_exit["version"]),
            effective_from="2034-02-01",
            change_type="INITIAL",
            branch_id=org["branch"]["id"],
            department_id=org["department"]["id"],
            designation_id=org["designation"]["id"],
        )

        assert rehire_assignment["employee_id"] == employee["id"]
        assert rehire_assignment["effective_to"] is None

        pre_exit_after = await client.get(
            f"/v1/employees/{employee['id']}/assignments/{pre_exit['id']}", headers=headers
        )
        assert pre_exit_after.json()["data"]["effective_to"] == "2034-01-31"

        history = await client.get(f"/v1/employees/{employee['id']}/assignments", headers=headers)
        history_ids = [row["id"] for row in history.json()["data"]]
        assert history_ids == [pre_exit["id"], rehire_assignment["id"]]

        # Employee identity is unaffected — same id/employee_code throughout.
        employee_after = await client.get(f"/v1/employees/{employee['id']}", headers=headers)
        assert employee_after.json()["data"]["employee_code"] == employee["employee_code"]
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


# --- Shift change (E-05) ----------------------------------------------------------------------


async def test_shift_change_success(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, org, _employment = await _setup_employee_with_employment(client, headers)
        shift = await _create_shift(client, headers)
        first = await _create_assignment(
            client,
            headers,
            employee_id=employee["id"],
            effective_from="2027-06-01",
            change_type="INITIAL",
            branch_id=org["branch"]["id"],
            department_id=org["department"]["id"],
            designation_id=org["designation"]["id"],
        )
        assert first["shift_id"] is None

        changed = await _create_assignment(
            client,
            headers,
            employee_id=employee["id"],
            if_match=str(first["version"]),
            effective_from="2028-04-01",
            change_type="SHIFT_CHANGE",
            shift_id=shift["id"],
        )

        assert changed["shift_id"] == shift["id"]
        assert changed["change_type"] == "SHIFT_CHANGE"
        # Every other field carried forward from the current row.
        assert changed["branch_id"] == org["branch"]["id"]
        assert changed["department_id"] == org["department"]["id"]
        assert changed["designation_id"] == org["designation"]["id"]

        fetched = await client.get(
            f"/v1/employees/{employee['id']}/assignments/{changed['id']}", headers=headers
        )
        assert fetched.json()["data"]["shift_id"] == shift["id"]

        factory = get_session_factory()
        async with factory() as session:
            audit_rows = (
                (
                    await session.execute(
                        select(AuditLog).where(
                            AuditLog.company_id == company_id,
                            AuditLog.entity_type == "employee_assignment",
                            AuditLog.entity_id == UUID(changed["id"]),
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(audit_rows) == 1
            assert audit_rows[0].action == "ASSIGNMENT_CHANGED"
            assert audit_rows[0].before_json["shift_id"] is None
            assert audit_rows[0].after_json["shift_id"] == shift["id"]
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_shift_change_missing_shift_id_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, org, _employment = await _setup_employee_with_employment(client, headers)
        first = await _create_assignment(
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
            f"/v1/employees/{employee['id']}/assignments",
            headers={**headers, "If-Match": str(first["version"])},
            json={"effective_from": "2028-04-01", "change_type": "SHIFT_CHANGE"},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "SHIFT_ID_REQUIRED"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_shift_change_invalid_shift_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, org, _employment = await _setup_employee_with_employment(client, headers)
        first = await _create_assignment(
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
            f"/v1/employees/{employee['id']}/assignments",
            headers={**headers, "If-Match": str(first["version"])},
            json={
                "effective_from": "2028-04-01",
                "change_type": "SHIFT_CHANGE",
                "shift_id": str(uuid4()),
            },
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_SHIFT"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_shift_change_cross_tenant_shift_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        employee_a, org_a, _employment_a = await _setup_employee_with_employment(client, headers_a)
        shift_b = await _create_shift(client, headers_b)
        first = await _create_assignment(
            client,
            headers_a,
            employee_id=employee_a["id"],
            effective_from="2027-06-01",
            change_type="INITIAL",
            branch_id=org_a["branch"]["id"],
            department_id=org_a["department"]["id"],
            designation_id=org_a["designation"]["id"],
        )

        response = await client.post(
            f"/v1/employees/{employee_a['id']}/assignments",
            headers={**headers_a, "If-Match": str(first["version"])},
            json={
                "effective_from": "2028-04-01",
                "change_type": "SHIFT_CHANGE",
                "shift_id": shift_b["id"],
            },
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_SHIFT"
    finally:
        await _teardown(company_id=company_a, user_id=user_a)
        await _teardown(company_id=company_b, user_id=user_b)


async def test_shift_change_deactivated_shift_succeeds(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """No document requires the referenced shift to be active — `_assert_shift_ownership`
    reuses `get_shift` verbatim (existence + tenant-scope only), matching every sibling
    reference field's validation depth
    (`docs/modules/employee/13_EMPLOYEE_SHIFT_ASSIGNMENT_IMPLEMENTATION_PLAN.md` §7.4)."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, org, _employment = await _setup_employee_with_employment(client, headers)
        shift = await _create_shift(client, headers)
        deactivate = await client.delete(
            f"/v1/shifts/{shift['id']}", headers={**headers, "If-Match": str(shift["version"])}
        )
        assert deactivate.status_code == 200
        assert deactivate.json()["data"]["is_active"] is False

        first = await _create_assignment(
            client,
            headers,
            employee_id=employee["id"],
            effective_from="2027-06-01",
            change_type="INITIAL",
            branch_id=org["branch"]["id"],
            department_id=org["department"]["id"],
            designation_id=org["designation"]["id"],
        )

        changed = await _create_assignment(
            client,
            headers,
            employee_id=employee["id"],
            if_match=str(first["version"]),
            effective_from="2028-04-01",
            change_type="SHIFT_CHANGE",
            shift_id=shift["id"],
        )
        assert changed["shift_id"] == shift["id"]
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_shift_change_mass_assignment_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, org, _employment = await _setup_employee_with_employment(client, headers)
        shift = await _create_shift(client, headers)
        first = await _create_assignment(
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
            f"/v1/employees/{employee['id']}/assignments",
            headers={**headers, "If-Match": str(first["version"])},
            json={
                "effective_from": "2028-04-01",
                "change_type": "SHIFT_CHANGE",
                "shift_id": shift["id"],
                "not_a_real_field": "x",
            },
        )
        assert response.status_code == 422
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_shift_change_without_transfer_permission_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    from hrms.modules.identity.permissions import EMPLOYEE_VIEW

    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, org, _employment = await _setup_employee_with_employment(client, headers)
        shift = await _create_shift(client, headers)
        first = await _create_assignment(
            client,
            headers,
            employee_id=employee["id"],
            effective_from="2027-06-01",
            change_type="INITIAL",
            branch_id=org["branch"]["id"],
            department_id=org["department"]["id"],
            designation_id=org["designation"]["id"],
        )
        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=[EMPLOYEE_VIEW]
        )

        response = await client.post(
            f"/v1/employees/{employee['id']}/assignments",
            headers={**scoped_headers, "If-Match": str(first["version"])},
            json={
                "effective_from": "2028-04-01",
                "change_type": "SHIFT_CHANGE",
                "shift_id": shift["id"],
            },
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_shift_change_with_transfer_permission_succeeds(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Proves `SHIFT_CHANGE` really is gated by `EMPLOYEE.TRANSFER` (the locked decision,
    plan §12) — a caller holding exactly `.VIEW` + `.TRANSFER` (no `.PROMOTE`,
    no `.UPDATE`) must succeed."""
    from hrms.modules.employee.permissions import EMPLOYEE_TRANSFER
    from hrms.modules.identity.permissions import EMPLOYEE_VIEW

    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, org, _employment = await _setup_employee_with_employment(client, headers)
        shift = await _create_shift(client, headers)
        first = await _create_assignment(
            client,
            headers,
            employee_id=employee["id"],
            effective_from="2027-06-01",
            change_type="INITIAL",
            branch_id=org["branch"]["id"],
            department_id=org["department"]["id"],
            designation_id=org["designation"]["id"],
        )
        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=[EMPLOYEE_VIEW, EMPLOYEE_TRANSFER]
        )

        response = await client.post(
            f"/v1/employees/{employee['id']}/assignments",
            headers={**scoped_headers, "If-Match": str(first["version"])},
            json={
                "effective_from": "2028-04-01",
                "change_type": "SHIFT_CHANGE",
                "shift_id": shift["id"],
            },
        )
        assert response.status_code == 201, response.text
        assert response.json()["data"]["shift_id"] == shift["id"]
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_rehire_carries_forward_stale_shift_id(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Documents the known, flagged (not silently glossed over) rehire behavior: a rehire's
    first assignment, if it omits `shift_id`, carries forward the pre-exit row's `shift_id` —
    same carry-forward rule every other field already follows on this same path (plan §10/§19
    item 1). This is not BR-14 (no cascading default is synthesized); it is the existing
    carry-forward mechanism applied to one more field."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, org, employment = await _setup_employee_with_employment(
            client, headers, joining_date="2027-06-01"
        )
        shift = await _create_shift(client, headers)
        pre_exit = await _create_assignment(
            client,
            headers,
            employee_id=employee["id"],
            effective_from="2027-06-01",
            change_type="INITIAL",
            branch_id=org["branch"]["id"],
            department_id=org["department"]["id"],
            designation_id=org["designation"]["id"],
            shift_id=shift["id"],
        )
        assert pre_exit["shift_id"] == shift["id"]

        terminate = await client.post(
            f"/v1/employees/{employee['id']}/employments/{employment['id']}/terminate",
            headers={**headers, "If-Match": str(employment["version"])},
            json={"last_working_day": "2030-09-30"},
        )
        assert terminate.status_code == 200

        await _create_employment(
            client,
            headers,
            employee_id=employee["id"],
            legal_entity_id=org["legal_entity"]["id"],
            joining_date="2034-02-01",
        )

        rehire_assignment = await _create_assignment(
            client,
            headers,
            employee_id=employee["id"],
            if_match=str(pre_exit["version"]),
            effective_from="2034-02-01",
            change_type="INITIAL",
            branch_id=org["branch"]["id"],
            department_id=org["department"]["id"],
            designation_id=org["designation"]["id"],
            # shift_id intentionally omitted — carries forward from the pre-exit row.
        )

        assert rehire_assignment["shift_id"] == shift["id"]
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


async def test_no_br14_default_shift_columns_on_org_entities(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """BR-14 (the Company -> Branch -> Department -> Grade -> Employee cascading shift/notice-
    period default override chain) remains explicitly deferred — no `default_shift_id` column
    exists on Branch/Department/Designation/Grade, and creating those entities without ever
    mentioning a shift succeeds exactly as before E-05."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        org = await _setup_org_structure(client, headers)
        for entity in ("branch", "department", "designation", "grade"):
            assert "default_shift_id" not in org[entity]
    finally:
        await _teardown(company_id=company_id, user_id=user_id)


# --- Tenant isolation ------------------------------------------------------------------------


async def test_cannot_get_assignment_from_other_tenant(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        employee_a, org_a, _employment_a = await _setup_employee_with_employment(client, headers_a)
        assignment_a = await _create_assignment(
            client,
            headers_a,
            employee_id=employee_a["id"],
            effective_from="2027-06-01",
            change_type="INITIAL",
            branch_id=org_a["branch"]["id"],
            department_id=org_a["department"]["id"],
            designation_id=org_a["designation"]["id"],
        )

        response = await client.get(
            f"/v1/employees/{employee_a['id']}/assignments/{assignment_a['id']}",
            headers=headers_b,
        )
        assert response.status_code == 404
    finally:
        await _teardown(company_id=company_a, user_id=user_a)
        await _teardown(company_id=company_b, user_id=user_b)


async def test_cannot_reference_other_tenant_branch(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_a, user_a = await _register_tenant(client)
    headers_b, company_b, user_b = await _register_tenant(client)
    try:
        employee_a, _org_a, _employment_a = await _setup_employee_with_employment(client, headers_a)
        org_b = await _setup_org_structure(client, headers_b)

        response = await client.post(
            f"/v1/employees/{employee_a['id']}/assignments",
            headers=headers_a,
            json={
                "effective_from": "2027-06-01",
                "change_type": "INITIAL",
                "branch_id": org_b["branch"]["id"],
                "department_id": org_b["department"]["id"],
                "designation_id": org_b["designation"]["id"],
            },
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_BRANCH"
    finally:
        await _teardown(company_id=company_a, user_id=user_a)
        await _teardown(company_id=company_b, user_id=user_b)


# --- Permission matrix -----------------------------------------------------------------------


async def _create_permission_scoped_user(
    *, company_id: UUID, permission_codes: list[str]
) -> tuple[dict[str, str], UUID]:
    """Registers a second user in the same tenant, granted only the given permission codes —
    mirrors `test_employment.py::test_create_employment_without_permission_rejected`'s own
    inline setup exactly, generalized to an arbitrary code list."""
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
                code=f"ASSIGNMENT_TEST_ROLE_{role_id.hex[:8]}",
                name="Assignment test role",
                is_system=False,
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        for permission in permissions:
            session.add(RolePermission(role_id=role_id, permission_id=permission.id))

        scoped_user_id = _uuid4()
        session.add(
            User(
                id=scoped_user_id,
                email=f"scoped-{scoped_user_id.hex[:8]}@example.com",
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
        employee_id=None,
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
                "(SELECT id FROM \"user\" WHERE email LIKE 'scoped-%')"
            )
        )
        await session.execute(text("DELETE FROM \"user\" WHERE email LIKE 'scoped-%'"))
        await session.commit()


async def test_create_assignment_without_transfer_permission_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    from hrms.modules.identity.permissions import EMPLOYEE_VIEW

    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, org, _employment = await _setup_employee_with_employment(client, headers)
        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=[EMPLOYEE_VIEW]
        )

        response = await client.post(
            f"/v1/employees/{employee['id']}/assignments",
            headers=scoped_headers,
            json={
                "effective_from": "2027-06-01",
                "change_type": "INITIAL",
                "branch_id": org["branch"]["id"],
                "department_id": org["department"]["id"],
                "designation_id": org["designation"]["id"],
            },
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_promotion_requires_promote_not_transfer_permission(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """`change_type=PROMOTION` requires `EMPLOYEE.PROMOTE` specifically — holding only
    `EMPLOYEE.TRANSFER` (plus the `.VIEW`/`.CREATE` needed to set up the fixture) must not be
    sufficient, proving the permission selection is genuinely keyed off `change_type` and not
    just "any assignment-write permission"."""
    from hrms.modules.employee.permissions import EMPLOYEE_TRANSFER
    from hrms.modules.identity.permissions import EMPLOYEE_VIEW

    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee, org, _employment = await _setup_employee_with_employment(client, headers)
        first = await _create_assignment(
            client,
            headers,
            employee_id=employee["id"],
            effective_from="2027-06-01",
            change_type="INITIAL",
            branch_id=org["branch"]["id"],
            department_id=org["department"]["id"],
            designation_id=org["designation"]["id"],
        )
        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=[EMPLOYEE_VIEW, EMPLOYEE_TRANSFER]
        )

        response = await client.post(
            f"/v1/employees/{employee['id']}/assignments",
            headers={**scoped_headers, "If-Match": str(first["version"])},
            json={
                "effective_from": "2029-01-01",
                "change_type": "PROMOTION",
                "grade_id": org["grade"]["id"],
            },
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"
    finally:
        await _teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()
