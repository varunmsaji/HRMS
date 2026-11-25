"""EH-B-01 — an unexpected exception in an import row must never be stored (and later returned by
`GET /employee-imports/{id}/errors`) as its raw text: a database error carries SQL and schema
names. Domain errors keep their curated text."""

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.exc import DBAPIError

from hrms.core.errors.base import NotFoundError
from hrms.modules.employee_import.service import EmployeeImportService


class _Repo:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def insert_row_error(self, _session: object, *, data: dict[str, Any]) -> None:
        self.rows.append(data)


async def _record(exc: Exception) -> dict[str, Any]:
    service = EmployeeImportService.__new__(EmployeeImportService)
    repo = _Repo()
    service._repo = repo  # type: ignore[assignment]
    service._session = SimpleNamespace()  # type: ignore[assignment]
    await service._record_row_error(uuid4(), uuid4(), 2, {"email": "a@b.c"}, exc)
    return repo.rows[0]


@pytest.mark.asyncio
async def test_database_error_text_is_not_stored() -> None:
    exc = DBAPIError(
        "SELECT secret_column FROM hidden_table WHERE x = $1", None, Exception("relation missing")
    )
    row = await _record(exc)
    assert row["error_code"] == "IMPORT_ROW_FAILED"
    for leaked in ("SELECT", "hidden_table", "secret_column", "relation missing"):
        assert leaked not in row["error_message"]


@pytest.mark.asyncio
async def test_plain_exception_text_is_not_stored() -> None:
    row = await _record(KeyError("internal_dict_key"))
    assert "internal_dict_key" not in row["error_message"]


@pytest.mark.asyncio
async def test_domain_error_keeps_its_curated_message() -> None:
    row = await _record(NotFoundError("Department not found", code="DEPARTMENT_NOT_FOUND"))
    assert row["error_code"] == "DEPARTMENT_NOT_FOUND"
    assert row["error_message"] == "Department not found"
