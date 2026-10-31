"""Regression for Stage 7 finding F-02: the enqueue-failure path under the restricted `hrms_app`.

`test_import_idempotency.py::test_a_failed_enqueue_closes_the_batch_instead_of_leaving_it_pending`
covers the same contract as the schema owner, which bypasses RLS. Under `hrms_app` the commit
before the publish clears the transaction-local `app.company_id`, so the follow-up `FAILED` update
used to die with `invalid input syntax for type uuid: ""` (HTTP 500, batch left `PENDING`).

Only the API call runs as `hrms_app`; registration, setup, assertions and teardown use the admin
role and touch only rows this test created."""

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

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


async def test_failed_enqueue_under_runtime_role_returns_503_and_closes_the_batch(
    client: AsyncClient,
    seeded_plan_catalogue: None,
    app_as_runtime_role: object,
    admin_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hrms.modules.employee_import import tasks

    def refuse(*args: object, **kwargs: object) -> None:
        raise ConnectionError("broker down")

    monkeypatch.setattr(tasks.process_batch, "delay", refuse)
    headers, company_id, user_id = await _register_tenant(client)
    org = await _setup_org_structure(client, headers)
    try:
        async with app_as_runtime_role():  # type: ignore[operator]
            response = await client.post(
                "/v1/employee-imports",
                headers=headers,
                files={"file": ("employees.csv", _build_csv(org), "text/csv")},
            )

        assert response.status_code == 503, response.text
        assert response.json()["error"]["code"] == "IMPORT_QUEUE_UNAVAILABLE"
        async with admin_engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT status, completed_at IS NOT NULL FROM employee_import_batch "
                        "WHERE company_id = :c"
                    ),
                    {"c": str(company_id)},
                )
            ).all()
        assert [tuple(r) for r in rows] == [("FAILED", True)]  # nothing left PENDING
    finally:
        await _cleanup_import_tables(company_id=company_id)
        await _cleanup_employee_rows(company_id=company_id)
        await _cleanup_org_structure(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
