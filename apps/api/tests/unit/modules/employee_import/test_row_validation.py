"""Unit tests for employee_import's pure row-shape logic — CSV row validation
(`EmployeeImportRow`), header-shape checks, and code/name reference-lookup resolution. No DB —
mirrors `tests/unit/modules/employee/test_employee_service.py`'s mock-only convention for
anything that doesn't need a real session.
"""

from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError

from hrms.core.errors.base import ValidationError
from hrms.modules.employee_import.exceptions import (
    ImportFileEmptyError,
    ImportHeaderInvalidError,
    ImportRowLimitExceededError,
)
from hrms.modules.employee_import.schemas import ALL_COLUMNS, REQUIRED_COLUMNS, EmployeeImportRow
from hrms.modules.employee_import.service import (
    EmployeeImportService,
    _index_by_code_or_name,
    _lookup,
    _sanitize_raw_row,
)


def _valid_row(**overrides: str) -> dict[str, str]:
    row = {
        "employee_code": "",
        "first_name": "Ravi",
        "middle_name": "",
        "last_name": "Kumar",
        "date_of_birth": "",
        "gender": "",
        "blood_group": "",
        "marital_status": "",
        "nationality": "",
        "personal_email": "",
        "personal_mobile": "",
        "legal_entity": "Acme Manufacturing Pvt Ltd",
        "branch": "HO-BLR",
        "department": "Engineering",
        "designation": "Software Engineer",
        "grade": "",
        "reporting_manager": "",
        "work_location_type": "",
        "joining_date": "2026-09-15",
        "annual_ctc_minor": "120000000",
        "currency": "inr",
    }
    row.update(overrides)
    return row


def test_valid_row_parses_with_defaults() -> None:
    parsed = EmployeeImportRow.model_validate(_valid_row())

    assert parsed.first_name == "Ravi"
    assert parsed.employee_code is None  # blank -> None, not ""
    assert parsed.work_location_type == "OFFICE"  # blank -> default
    assert parsed.currency == "INR"  # upper-cased


def test_blank_required_field_fails_validation() -> None:
    with pytest.raises(PydanticValidationError) as exc_info:
        EmployeeImportRow.model_validate(_valid_row(first_name=""))

    errors = exc_info.value.errors()
    assert any(error["loc"] == ("first_name",) for error in errors)


def test_negative_ctc_fails_validation() -> None:
    with pytest.raises(PydanticValidationError):
        EmployeeImportRow.model_validate(_valid_row(annual_ctc_minor="-1"))


def test_invalid_work_location_type_fails_validation() -> None:
    with pytest.raises(PydanticValidationError):
        EmployeeImportRow.model_validate(_valid_row(work_location_type="MOON_BASE"))


def test_extra_column_is_rejected() -> None:
    with pytest.raises(PydanticValidationError):
        EmployeeImportRow.model_validate(_valid_row(unexpected_column="x"))


def test_employee_code_override_is_preserved_when_present() -> None:
    parsed = EmployeeImportRow.model_validate(_valid_row(employee_code="EMP-LEGACY-001"))
    assert parsed.employee_code == "EMP-LEGACY-001"


def test_all_columns_covers_required_and_optional() -> None:
    assert set(REQUIRED_COLUMNS) <= set(ALL_COLUMNS)
    assert "first_name" in REQUIRED_COLUMNS
    assert "employee_code" not in REQUIRED_COLUMNS


def test_sanitize_raw_row_drops_none_key_and_fills_none_values() -> None:
    # `csv.DictReader`'s `restkey`/`restval` shapes for a malformed data row.
    raw = {"first_name": "Ravi", "last_name": None, None: ["extra", "columns"]}
    sanitized = _sanitize_raw_row(raw)

    assert sanitized == {"first_name": "Ravi", "last_name": ""}


class _FakeOrgRow:
    def __init__(self, *, id: object, code: str | None = None, name: str | None = None) -> None:
        self.id = id
        self.code = code
        self.name = name


def test_index_by_code_or_name_matches_code_case_insensitively() -> None:
    branch_id = uuid4()
    index = _index_by_code_or_name([_FakeOrgRow(id=branch_id, code="HO-BLR", name="Bangalore HO")])

    assert index["ho-blr"] == branch_id
    assert index["bangalore ho"] == branch_id


def test_index_by_code_or_name_handles_missing_code_attr() -> None:
    # `LegalEntityRead` has no `code` field at all — `getattr(..., None)` must not raise.
    entity_id = uuid4()
    index = _index_by_code_or_name([_FakeOrgRow(id=entity_id, name="Acme Manufacturing Pvt Ltd")])

    assert index["acme manufacturing pvt ltd"] == entity_id


def test_lookup_raises_validation_error_for_unmatched_value() -> None:
    with pytest.raises(ValidationError, match="branch 'Nope' does not match"):
        _lookup({}, "Nope", field_name="branch")


def test_lookup_strips_and_lowercases_before_matching() -> None:
    target_id = uuid4()
    resolved = _lookup({"engineering": target_id}, "  Engineering  ", field_name="department")
    assert resolved == target_id


def test_parse_and_validate_shape_rejects_missing_required_column() -> None:
    service = EmployeeImportService.__new__(EmployeeImportService)  # bypass __init__, no DB needed
    header = ",".join(c for c in ALL_COLUMNS if c != "first_name")
    csv_bytes = (header + "\nx\n").encode()

    with pytest.raises(ImportHeaderInvalidError) as exc_info:
        service._parse_and_validate_shape(csv_bytes)
    assert "first_name" in str(exc_info.value)


def test_parse_and_validate_shape_rejects_unexpected_column() -> None:
    service = EmployeeImportService.__new__(EmployeeImportService)
    header = ",".join([*ALL_COLUMNS, "not_a_real_column"])
    row = ",".join(["x"] * len(ALL_COLUMNS) + ["y"])
    csv_bytes = (header + "\n" + row + "\n").encode()

    with pytest.raises(ImportHeaderInvalidError) as exc_info:
        service._parse_and_validate_shape(csv_bytes)
    assert "not_a_real_column" in str(exc_info.value)


def test_parse_and_validate_shape_rejects_empty_file() -> None:
    service = EmployeeImportService.__new__(EmployeeImportService)
    csv_bytes = (",".join(ALL_COLUMNS) + "\n").encode()

    with pytest.raises(ImportFileEmptyError):
        service._parse_and_validate_shape(csv_bytes)


def test_parse_and_validate_shape_rejects_too_many_rows() -> None:
    service = EmployeeImportService.__new__(EmployeeImportService)
    header = ",".join(ALL_COLUMNS)
    row = ",".join(_valid_row()[c] for c in ALL_COLUMNS)
    csv_bytes = (header + "\n" + (row + "\n") * 1001).encode()

    with pytest.raises(ImportRowLimitExceededError) as exc_info:
        service._parse_and_validate_shape(csv_bytes)
    assert "1001" in str(exc_info.value)
