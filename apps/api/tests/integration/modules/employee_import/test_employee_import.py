"""Integration tests for employee_import — CSV bulk employee import.

`process_batch` is invoked directly (not via a real Celery worker/broker), same convention as
`tests/integration/modules/leave/test_leave_accrual.py` for this codebase's only other
Celery-backed pipeline: it's the same coroutine the task calls via `asyncio.run`, so calling it
directly exercises the real code path minus the Celery/asyncio bridge itself. `POST
/v1/employee-imports` is still exercised through the real HTTP client (upload, header/row-cap
validation, permission gate, S3 write, batch row creation) — only the async hand-off to a worker
is bypassed.
"""

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.employee_import.service import EmployeeImportService

from ..employee.test_employee_assignment import _setup_org_structure
from ..organisation.test_registration_flow import _cleanup, _register

pytestmark = pytest.mark.asyncio

CSV_HEADER = (
    "employee_code,first_name,middle_name,last_name,date_of_birth,gender,blood_group,"
    "marital_status,nationality,personal_email,personal_mobile,legal_entity,branch,department,"
    "designation,grade,reporting_manager,work_location_type,joining_date,annual_ctc_minor,currency"
)


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


def _build_csv(org: dict[str, Any]) -> bytes:
    legal_entity = org["legal_entity"]["name"]
    branch = org["branch"]["name"]
    department = org["department"]["name"]
    designation = org["designation"]["title"]
    rows = [
        # Row 1 (CSV line 2): valid, auto-allocated employee_code.
        f",Ravi,,Kumar,1995-06-12,MALE,,,Indian,ravi@example.com,9876500001,"
        f"{legal_entity},{branch},{department},{designation},,,OFFICE,2026-09-15,120000000,inr",
        # Row 2 (line 3): valid, custom employee_code override.
        f"EMP-CUSTOM-001,Anita,,Desai,1992-03-20,FEMALE,,,Indian,anita@example.com,9876500002,"
        f"{legal_entity},{branch},{department},{designation},,,HYBRID,2026-09-16,150000000,INR",
        # Row 3 (line 4): unresolvable branch reference.
        f",Sunil,,Rao,1990-01-01,MALE,,,Indian,sunil@example.com,9876500003,"
        f"{legal_entity},NOT-A-REAL-BRANCH,{department},{designation},,,OFFICE,2026-09-17,100000000,INR",
        # Row 4 (line 5): duplicate of row 2's custom employee_code.
        f"EMP-CUSTOM-001,Dupe,,Person,1990-01-01,MALE,,,Indian,dupe@example.com,9876500004,"
        f"{legal_entity},{branch},{department},{designation},,,OFFICE,2026-09-18,100000000,INR",
        # Row 5 (line 6): missing required first_name.
        f",,,,1990-01-01,MALE,,,Indian,noname@example.com,9876500005,"
        f"{legal_entity},{branch},{department},{designation},,,OFFICE,2026-09-19,100000000,INR",
    ]
    return (CSV_HEADER + "\n" + "\n".join(rows) + "\n").encode()


async def _cleanup_import_tables(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        await session.execute(
            text("DELETE FROM employee_import_row_error WHERE company_id = :cid"),
            {"cid": str(company_id)},
        )
        await session.execute(
            text("DELETE FROM employee_import_batch WHERE company_id = :cid"),
            {"cid": str(company_id)},
        )
        await session.commit()


async def _cleanup_employee_rows(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        for table in (
            "employee_compensation",
            "employee_assignment",
            "employment",
            "employee",
            "number_series",
        ):
            await session.execute(
                text(f"DELETE FROM {table} WHERE company_id = :cid"), {"cid": str(company_id)}
            )
        await session.commit()


async def _cleanup_org_structure(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        for table in ("designation", "grade", "department", "branch"):
            await session.execute(
                text(f"DELETE FROM {table} WHERE company_id = :cid"), {"cid": str(company_id)}
            )
        await session.commit()


@pytest.mark.asyncio
async def test_bulk_import_end_to_end(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    org = await _setup_org_structure(client, headers)
    csv_bytes = _build_csv(org)

    try:
        upload_response = await client.post(
            "/v1/employee-imports",
            headers=headers,
            files={"file": ("employees.csv", csv_bytes, "text/csv")},
        )
        assert upload_response.status_code == 201, upload_response.text
        batch = upload_response.json()["data"]
        assert batch["status"] == "PENDING"
        assert batch["total_rows"] == 5
        batch_id = UUID(batch["id"])

        # Runs the real pipeline synchronously — bypasses only the Celery dispatch itself
        # (module docstring above).
        factory = get_session_factory()
        async with factory() as session:
            await set_rls_company_id(session, str(company_id))
            await EmployeeImportService(session).process_batch(company_id, batch_id, user_id)

        status_response = await client.get(f"/v1/employee-imports/{batch_id}", headers=headers)
        assert status_response.status_code == 200
        result = status_response.json()["data"]
        assert result["status"] == "COMPLETED_WITH_ERRORS"
        assert result["processed_rows"] == 5
        assert result["success_count"] == 2
        assert result["error_count"] == 3

        errors_response = await client.get(
            f"/v1/employee-imports/{batch_id}/errors", headers=headers
        )
        assert errors_response.status_code == 200
        errors = {e["row_number"]: e for e in errors_response.json()["data"]}
        assert set(errors) == {4, 5, 6}
        assert errors[4]["error_code"] == "VALIDATION_ERROR"
        assert "NOT-A-REAL-BRANCH" in errors[4]["error_message"]
        assert errors[5]["error_code"] == "DUPLICATE_EMPLOYEE_CODE"
        assert errors[6]["error_code"] == "VALIDATION_ERROR"
        assert "first_name" in errors[6]["error_message"]

        employees_response = await client.get("/v1/employees", headers=headers)
        employees = {e["personal_email"]: e for e in employees_response.json()["data"]}
        assert set(employees) == {"ravi@example.com", "anita@example.com"}
        assert employees["ravi@example.com"]["employee_code"].startswith("EMP-")
        assert employees["anita@example.com"]["employee_code"] == "EMP-CUSTOM-001"

        anita_id = employees["anita@example.com"]["id"]
        assignments_response = await client.get(
            f"/v1/employees/{anita_id}/assignments", headers=headers
        )
        assignment = assignments_response.json()["data"][0]
        assert assignment["work_location_type"] == "HYBRID"
        assert assignment["change_type"] == "INITIAL"

        compensation_response = await client.get(
            f"/v1/employees/{anita_id}/compensation", headers=headers
        )
        compensation = compensation_response.json()["data"][0]
        assert compensation["annual_ctc_minor"] == 150000000
        assert compensation["revision_type"] == "JOINING"
    finally:
        await _cleanup_import_tables(company_id=company_id)
        await _cleanup_employee_rows(company_id=company_id)
        await _cleanup_org_structure(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


@pytest.mark.asyncio
async def test_cross_tenant_batch_not_visible(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_id_a, user_id_a = await _register_tenant(client)
    headers_b, company_id_b, user_id_b = await _register_tenant(client)
    org_a = await _setup_org_structure(client, headers_a)

    try:
        # A single valid row is enough — this test only cares about cross-tenant visibility.
        csv_bytes = (
            CSV_HEADER + "\n"
            f",Ravi,,Kumar,1995-06-12,MALE,,,Indian,ravi@example.com,9876500001,"
            f"{org_a['legal_entity']['name']},{org_a['branch']['name']},"
            f"{org_a['department']['name']},{org_a['designation']['title']},,,OFFICE,"
            "2026-09-15,120000000,INR\n"
        ).encode()
        upload_response = await client.post(
            "/v1/employee-imports",
            headers=headers_a,
            files={"file": ("employees.csv", csv_bytes, "text/csv")},
        )
        assert upload_response.status_code == 201, upload_response.text
        batch_id = upload_response.json()["data"]["id"]

        cross_tenant_response = await client.get(
            f"/v1/employee-imports/{batch_id}", headers=headers_b
        )
        assert cross_tenant_response.status_code == 404

        cross_tenant_errors_response = await client.get(
            f"/v1/employee-imports/{batch_id}/errors", headers=headers_b
        )
        assert cross_tenant_errors_response.status_code == 404
    finally:
        await _cleanup_import_tables(company_id=company_id_a)
        await _cleanup_org_structure(company_id=company_id_a)
        await _cleanup(company_id=company_id_a, user_id=user_id_a)
        await _cleanup(company_id=company_id_b, user_id=user_id_b)
