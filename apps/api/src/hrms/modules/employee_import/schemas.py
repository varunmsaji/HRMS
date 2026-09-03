"""Pydantic request/response schemas for employee_import.

`EmployeeImportRow` mirrors the four schemas it drives per row
(`employee.schemas.EmployeeCreate`/`EmploymentCreate`/`AssignmentCreate`/`CompensationCreate`),
flattened into one CSV row with human-readable references (branch/department/designation/grade
by code-or-name, reporting_manager by employee_code-or-email) resolved to UUIDs by
`EmployeeImportService` before those schemas are ever constructed — this schema itself carries
only strings/primitives, exactly what a CSV cell is.
"""

from datetime import date, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from hrms.modules.employee.schemas import WorkLocationType

if TYPE_CHECKING:
    from hrms.modules.employee_import.models import EmployeeImportBatch, EmployeeImportRowError

#: Column order also doubles as the downloadable template's header row.
REQUIRED_COLUMNS = (
    "first_name",
    "legal_entity",
    "branch",
    "department",
    "designation",
    "joining_date",
    "annual_ctc_minor",
    "currency",
)
OPTIONAL_COLUMNS = (
    "employee_code",
    "middle_name",
    "last_name",
    "date_of_birth",
    "gender",
    "blood_group",
    "marital_status",
    "nationality",
    "personal_email",
    "personal_mobile",
    "grade",
    "reporting_manager",
    "work_location_type",
)
ALL_COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS

#: Upload-time guard (`docs` plan: "generous for a single migration chunk in the 50-5,000
#: employee target range, cheap to raise later").
MAX_IMPORT_ROWS = 1000


class EmployeeImportRow(BaseModel):
    """One validated CSV row. Every field arrives as a string from `csv.DictReader`; this model
    does the type coercion (dates, ints) and required-field checks in one place. Reference
    columns (`legal_entity`/`branch`/.../`reporting_manager`) stay as raw strings here —
    resolving them to UUIDs happens in `EmployeeImportService._resolve_row`, against this
    company's actual org-structure data, which this schema has no access to."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    employee_code: str | None = None
    first_name: str = Field(min_length=1, max_length=100)
    middle_name: str | None = None
    last_name: str | None = None
    date_of_birth: date | None = None
    gender: str | None = None
    blood_group: str | None = None
    marital_status: str | None = None
    nationality: str | None = None
    personal_email: str | None = None
    personal_mobile: str | None = None
    legal_entity: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    department: str = Field(min_length=1)
    designation: str = Field(min_length=1)
    grade: str | None = None
    reporting_manager: str | None = None
    work_location_type: WorkLocationType = "OFFICE"
    joining_date: date
    annual_ctc_minor: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)

    @field_validator(
        "employee_code",
        "middle_name",
        "last_name",
        "date_of_birth",
        "gender",
        "blood_group",
        "marital_status",
        "nationality",
        "personal_email",
        "personal_mobile",
        "grade",
        "reporting_manager",
        mode="before",
    )
    @classmethod
    def blank_to_none(cls, value: object) -> object:
        """A blank CSV cell arrives as `""`, not a missing key — without this, every optional
        field would fail validation as an empty string instead of being treated as absent."""
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    @field_validator("work_location_type", mode="before")
    @classmethod
    def blank_work_location_type_defaults_to_office(cls, value: object) -> object:
        """A blank cell means "not specified," not an invalid value — falls back to the
        field's own `"OFFICE"` default rather than failing the `Literal` validation below."""
        if isinstance(value, str) and value.strip() == "":
            return "OFFICE"
        return value

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        if not value.isalpha():
            raise ValueError("currency must contain only letters")
        return value.upper()


class EmployeeImportBatchRead(BaseModel):
    id: UUID
    company_id: UUID
    status: str
    original_filename: str
    total_rows: int
    processed_rows: int
    success_count: int
    error_count: int
    started_at: str | None
    completed_at: str | None
    created_at: str
    updated_at: str


class EmployeeImportRowErrorRead(BaseModel):
    id: UUID
    row_number: int
    raw_row: dict[str, str]
    error_code: str
    error_message: str


def _format_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


def batch_to_read(batch: "EmployeeImportBatch") -> EmployeeImportBatchRead:
    return EmployeeImportBatchRead(
        id=batch.id,
        company_id=batch.company_id,
        status=batch.status,
        original_filename=batch.original_filename,
        total_rows=batch.total_rows,
        processed_rows=batch.processed_rows,
        success_count=batch.success_count,
        error_count=batch.error_count,
        started_at=_format_timestamp(batch.started_at),
        completed_at=_format_timestamp(batch.completed_at),
        created_at=_format_timestamp(batch.created_at) or "",
        updated_at=_format_timestamp(batch.updated_at) or "",
    )


def row_error_to_read(row_error: "EmployeeImportRowError") -> EmployeeImportRowErrorRead:
    return EmployeeImportRowErrorRead(
        id=row_error.id,
        row_number=row_error.row_number,
        raw_row=row_error.raw_row,
        error_code=row_error.error_code,
        error_message=row_error.error_message,
    )
