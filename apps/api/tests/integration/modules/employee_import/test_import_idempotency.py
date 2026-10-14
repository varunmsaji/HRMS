"""Import idempotency guard and lifecycle events (mission Phase 5 / decision D-B groundwork).

The pipeline is create-only: a second run of the same batch would create a duplicate of every row
that has no colliding `employee_code` (row 1 of the fixture auto-allocates its code). A batch is
therefore processed only if it is atomically claimed PENDING -> PROCESSING; a repeated or
concurrent delivery is skipped and logged. A normally pending batch is processed exactly as
before (the end-to-end test in `test_employee_import.py` still covers that)."""

import asyncio
import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from pytest import CaptureFixture
from sqlalchemy import text

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


def _events(raw: str, name: str) -> list[dict[str, Any]]:
    out = []
    for line in raw.splitlines():
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict) and parsed.get("event") == name:
            out.append(parsed)
    return out


async def _process(company_id: UUID, batch_id: UUID, user_id: UUID | None) -> None:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        await EmployeeImportService(session).process_batch(company_id, batch_id, user_id)


async def _upload(client: AsyncClient, headers: dict[str, str], org: dict[str, Any]) -> UUID:
    response = await client.post(
        "/v1/employee-imports",
        headers=headers,
        files={"file": ("employees.csv", _build_csv(org), "text/csv")},
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["data"]["id"])


async def _employee_count(client: AsyncClient, headers: dict[str, str]) -> int:
    return len((await client.get("/v1/employees", headers=headers)).json()["data"])


async def test_a_processed_batch_is_never_processed_again(
    client: AsyncClient, seeded_plan_catalogue: None, capfd: CaptureFixture[str]
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    org = await _setup_org_structure(client, headers)
    try:
        batch_id = await _upload(client, headers, org)
        capfd.readouterr()
        await _process(company_id, batch_id, user_id)
        first = capfd.readouterr().out
        assert await _employee_count(client, headers) == 2

        await _process(company_id, batch_id, user_id)  # redelivered message
        second = capfd.readouterr().out
        assert await _employee_count(client, headers) == 2  # no duplicate "Ravi"

        (finished,) = _events(first, "employee_import.batch.finished")
        assert finished["status"] == "COMPLETED_WITH_ERRORS"
        assert (finished["success_count"], finished["error_count"]) == (2, 3)
        assert finished["level"] == "warning"  # some rows failed
        assert finished["batch_id"] == str(batch_id)
        assert "ravi@example.com" not in first

        (skipped,) = _events(second, "employee_import.batch.skipped")
        assert skipped["reason"] == "not_pending"
        assert skipped["status"] == "COMPLETED_WITH_ERRORS"
        assert _events(second, "employee_import.batch.finished") == []
    finally:
        await _cleanup_import_tables(company_id=company_id)
        await _cleanup_employee_rows(company_id=company_id)
        await _cleanup_org_structure(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_concurrent_deliveries_process_the_batch_once(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    org = await _setup_org_structure(client, headers)
    try:
        batch_id = await _upload(client, headers, org)
        await asyncio.gather(
            _process(company_id, batch_id, user_id), _process(company_id, batch_id, user_id)
        )
        assert await _employee_count(client, headers) == 2
        status = (await client.get(f"/v1/employee-imports/{batch_id}", headers=headers)).json()
        assert status["data"]["status"] == "COMPLETED_WITH_ERRORS"
    finally:
        await _cleanup_import_tables(company_id=company_id)
        await _cleanup_employee_rows(company_id=company_id)
        await _cleanup_org_structure(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_a_message_for_a_missing_batch_is_logged_and_ignored(
    client: AsyncClient, seeded_plan_catalogue: None, capfd: CaptureFixture[str]
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        capfd.readouterr()
        await _process(company_id, uuid4(), user_id)
        (skipped,) = _events(capfd.readouterr().out, "employee_import.batch.skipped")
        assert skipped["reason"] == "missing"
    finally:
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_a_failed_enqueue_closes_the_batch_instead_of_leaving_it_pending(
    client: AsyncClient,
    seeded_plan_catalogue: None,
    capfd: CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Broker unreachable at upload time: the batch is committed before the publish, so without
    handling it stayed PENDING with no message behind it and the caller got a bare 500."""
    from hrms.modules.employee_import import tasks

    def refuse(*args: object, **kwargs: object) -> None:
        raise ConnectionError("broker down")

    monkeypatch.setattr(tasks.process_batch, "delay", refuse)
    headers, company_id, user_id = await _register_tenant(client)
    org = await _setup_org_structure(client, headers)
    try:
        capfd.readouterr()
        response = await client.post(
            "/v1/employee-imports",
            headers=headers,
            files={"file": ("employees.csv", _build_csv(org), "text/csv")},
        )

        assert response.status_code == 503, response.text
        assert response.json()["error"]["code"] == "IMPORT_QUEUE_UNAVAILABLE"
        (failed,) = _events(capfd.readouterr().out, "employee_import.batch.enqueue_failed")
        assert failed["company_id"] == str(company_id)
        async with get_session_factory()() as session:
            await set_rls_company_id(session, str(company_id))
            rows = await session.execute(
                text("SELECT status FROM employee_import_batch WHERE company_id = :c"),
                {"c": str(company_id)},
            )
            assert [r[0] for r in rows] == ["FAILED"]  # nothing left PENDING
        assert await _employee_count(client, headers) == 0
    finally:
        await _cleanup_import_tables(company_id=company_id)
        await _cleanup_employee_rows(company_id=company_id)
        await _cleanup_org_structure(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
