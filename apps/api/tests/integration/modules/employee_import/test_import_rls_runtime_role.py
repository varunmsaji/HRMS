"""Stage 1 (production-readiness programme): employee import under the restricted `hrms_app` role.

Every API call and the `process_batch` pipeline run as `hrms_app`; registration, setup, assertions
and teardown use the admin role and touch only rows these tests created.

Asserts that tenant B cannot read tenant A's batch/errors (404 identical to an unknown id, so the
response does not reveal existence), that reference data is tenant-scoped, and that a CSV in
tenant B naming tenant A's organisation entities resolves nothing and creates no employee."""

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.employee_import.service import EmployeeImportService

from ..employee.test_employee_assignment import _setup_org_structure
from ..organisation.test_registration_flow import _cleanup
from .test_employee_import import (
    _build_csv,
    _cleanup_employee_rows,
    _cleanup_import_tables,
    _cleanup_org_structure,
    _register_tenant,
)

pytestmark = pytest.mark.asyncio


async def _two_tenants(client: AsyncClient) -> tuple[tuple, tuple, dict]:
    """Tenant A owns an org structure; tenant B owns none, so any org name B can see came from A."""
    a = await _register_tenant(client)
    b = await _register_tenant(client)
    org_a = await _setup_org_structure(client, a[0])
    return a, b, org_a


async def _cleanup_tenant(company_id: UUID, user_id: UUID | None) -> None:
    await _cleanup_import_tables(company_id=company_id)
    await _cleanup_employee_rows(company_id=company_id)
    await _cleanup_org_structure(company_id=company_id)
    await _cleanup(company_id=company_id, user_id=user_id)


async def test_tenant_b_cannot_read_tenant_a_import_batch_or_errors(
    client: AsyncClient,
    seeded_plan_catalogue: None,
    app_as_runtime_role: object,
    admin_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hrms.modules.employee_import import tasks

    monkeypatch.setattr(tasks.process_batch, "delay", lambda *a, **k: None)
    a, b, org_a = await _two_tenants(client)
    (headers_a, company_a, user_a), (headers_b, company_b, user_b) = a, b
    try:
        async with app_as_runtime_role():  # type: ignore[operator]
            up = await client.post(
                "/v1/employee-imports",
                headers=headers_a,
                files={"file": ("employees.csv", _build_csv(org_a), "text/csv")},
            )
            assert up.status_code == 201, up.text
            batch_id = up.json()["data"]["id"]

            own = await client.get(f"/v1/employee-imports/{batch_id}", headers=headers_a)
            assert own.status_code == 200, own.text

            cross = await client.get(f"/v1/employee-imports/{batch_id}", headers=headers_b)
            cross_errors = await client.get(
                f"/v1/employee-imports/{batch_id}/errors", headers=headers_b
            )
            unknown = await client.get(f"/v1/employee-imports/{uuid4()}", headers=headers_b)
            # Foreign-tenant header with tenant A's token is refused outright.
            mismatched = await client.get(
                f"/v1/employee-imports/{batch_id}",
                headers={**headers_b, "Authorization": headers_a["Authorization"]},
            )

        assert cross.status_code == 404, cross.text
        assert cross_errors.status_code == 404, cross_errors.text
        # No existence oracle: a real foreign id is indistinguishable from an unknown one.
        assert cross.json()["error"]["code"] == unknown.json()["error"]["code"]
        assert mismatched.status_code in (401, 403, 404), mismatched.text
        async with admin_engine.connect() as conn:
            leaked = (
                await conn.execute(
                    text("SELECT count(*) FROM employee_import_batch WHERE company_id = :c"),
                    {"c": str(company_b)},
                )
            ).scalar_one()
        assert leaked == 0
    finally:
        await _cleanup_tenant(company_a, user_a)
        await _cleanup_tenant(company_b, user_b)


async def test_reference_data_and_processing_ignore_foreign_tenant_org_entities(
    client: AsyncClient,
    seeded_plan_catalogue: None,
    app_as_runtime_role: object,
    admin_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hrms.modules.employee_import import tasks

    monkeypatch.setattr(tasks.process_batch, "delay", lambda *a, **k: None)
    a, b, org_a = await _two_tenants(client)
    (_headers_a, company_a, user_a), (headers_b, company_b, user_b) = a, b
    try:
        async with app_as_runtime_role():  # type: ignore[operator]
            ref = await client.get("/v1/employee-imports/reference-data", headers=headers_b)
            assert ref.status_code == 200, ref.text
            assert org_a["legal_entity"]["name"] not in ref.text
            assert org_a["branch"]["name"] not in ref.text

            # Tenant B uploads a CSV that names tenant A's entities.
            up = await client.post(
                "/v1/employee-imports",
                headers=headers_b,
                files={"file": ("employees.csv", _build_csv(org_a), "text/csv")},
            )
            assert up.status_code == 201, up.text
            batch_id = UUID(up.json()["data"]["id"])

            factory = get_session_factory()
            async with factory() as session:
                await set_rls_company_id(session, str(company_b))
                await EmployeeImportService(session).process_batch(company_b, batch_id, user_b)

        async with admin_engine.connect() as conn:
            created_b = (
                await conn.execute(
                    text("SELECT count(*) FROM employee WHERE company_id = :c"),
                    {"c": str(company_b)},
                )
            ).scalar_one()
            created_a = (
                await conn.execute(
                    text("SELECT count(*) FROM employee WHERE company_id = :c"),
                    {"c": str(company_a)},
                )
            ).scalar_one()
            foreign_refs = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM employee_assignment ea "
                        "JOIN branch br ON br.id = ea.branch_id "
                        "WHERE ea.company_id = :b AND br.company_id <> :b"
                    ),
                    {"b": str(company_b)},
                )
            ).scalar_one()
        assert created_b == 0  # every row failed to resolve tenant-A names
        assert created_a == 0  # nothing was written into tenant A
        assert foreign_refs == 0
    finally:
        await _cleanup_tenant(company_a, user_a)
        await _cleanup_tenant(company_b, user_b)
