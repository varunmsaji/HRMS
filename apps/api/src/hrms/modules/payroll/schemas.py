"""Pydantic request/response shapes for the Payroll module (Phase 5.1 — salary setup)."""

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from hrms.modules.payroll.breakup import APPLIES_WHEN, CALCULATION_TYPES, COMPONENT_TYPES

if TYPE_CHECKING:
    from hrms.modules.payroll.models import (
        EmployeeSalary,
        SalaryComponent,
        SalaryStructure,
        SalaryStructureLine,
        SalaryStructureVersion,
    )


def _format_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    return str(value.isoformat()).replace("+00:00", "Z")


def _check_choice(field: str, value: str | None, choices: tuple[str, ...]) -> None:
    if value is not None and value not in choices:
        raise ValueError(f"{field} must be one of {choices}")


# ---------------------------------------------------------------------------
# Salary component
# ---------------------------------------------------------------------------


class SalaryComponentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=30, pattern=r"^[A-Z0-9_]+$")
    name: str = Field(min_length=1, max_length=150)
    component_type: str
    is_taxable: bool = True
    is_pf_wage: bool = False
    is_esi_wage: bool = False
    is_prorated: bool = True
    show_on_payslip: bool = True
    display_order: int = Field(default=0, ge=0, le=10_000)

    @field_validator("component_type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        _check_choice("component_type", value, COMPONENT_TYPES)
        return value


class SalaryComponentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=150)
    component_type: str | None = None
    is_taxable: bool | None = None
    is_pf_wage: bool | None = None
    is_esi_wage: bool | None = None
    is_prorated: bool | None = None
    show_on_payslip: bool | None = None
    display_order: int | None = Field(default=None, ge=0, le=10_000)
    is_active: bool | None = None

    @field_validator("component_type")
    @classmethod
    def validate_type(cls, value: str | None) -> str | None:
        _check_choice("component_type", value, COMPONENT_TYPES)
        return value


class SalaryComponentRead(BaseModel):
    id: UUID
    company_id: UUID
    code: str
    name: str
    component_type: str
    is_system: bool
    is_taxable: bool
    is_pf_wage: bool
    is_esi_wage: bool
    is_prorated: bool
    show_on_payslip: bool
    display_order: int
    is_active: bool
    version: int
    created_at: str
    updated_at: str


def salary_component_to_read(row: "SalaryComponent") -> SalaryComponentRead:
    return SalaryComponentRead(
        id=row.id,
        company_id=row.company_id,
        code=row.code,
        name=row.name,
        component_type=row.component_type,
        is_system=row.is_system,
        is_taxable=row.is_taxable,
        is_pf_wage=row.is_pf_wage,
        is_esi_wage=row.is_esi_wage,
        is_prorated=row.is_prorated,
        show_on_payslip=row.show_on_payslip,
        display_order=row.display_order,
        is_active=row.is_active,
        version=row.version,
        created_at=_format_timestamp(row.created_at) or "",
        updated_at=_format_timestamp(row.updated_at) or "",
    )


# ---------------------------------------------------------------------------
# Salary structure
# ---------------------------------------------------------------------------


class SalaryStructureLineInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    salary_component_id: UUID
    calculation_type: str
    percentage: Decimal | None = Field(default=None, ge=0, le=100, decimal_places=4)
    amount_monthly_minor: int | None = Field(default=None, ge=0)
    base_salary_component_id: UUID | None = None
    max_monthly_minor: int | None = Field(default=None, ge=0)
    applies_when: str = "ALWAYS"
    display_order: int = Field(default=0, ge=0, le=10_000)

    @field_validator("calculation_type")
    @classmethod
    def validate_calculation(cls, value: str) -> str:
        _check_choice("calculation_type", value, CALCULATION_TYPES)
        return value

    @field_validator("applies_when")
    @classmethod
    def validate_applies_when(cls, value: str) -> str:
        _check_choice("applies_when", value, APPLIES_WHEN)
        return value


class SalaryStructureCreate(BaseModel):
    """Creates the structure and its first draft version (with `lines`, if given)."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=30, pattern=r"^[A-Z0-9_]+$")
    name: str = Field(min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=2000)
    lines: list[SalaryStructureLineInput] = Field(default_factory=list, max_length=50)


class SalaryStructureUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None


class SalaryStructureVersionCreate(BaseModel):
    """A new draft. Without `lines`, it starts as a copy of the latest published version."""

    model_config = ConfigDict(extra="forbid")

    lines: list[SalaryStructureLineInput] | None = Field(default=None, max_length=50)


class SalaryStructureVersionLinesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lines: list[SalaryStructureLineInput] = Field(max_length=50)


class SalaryStructureVersionPublish(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effective_from: date


class SalaryStructureLineRead(BaseModel):
    id: UUID
    salary_component_id: UUID
    component_code: str
    component_name: str
    component_type: str
    calculation_type: str
    percentage: str | None
    amount_monthly_minor: int | None
    base_salary_component_id: UUID | None
    max_monthly_minor: int | None
    applies_when: str
    display_order: int


class SalaryStructureVersionRead(BaseModel):
    id: UUID
    salary_structure_id: UUID
    version_number: int
    status: str
    effective_from: date | None
    effective_to: date | None
    published_at: str | None
    version: int
    lines: list[SalaryStructureLineRead]


class SalaryStructureRead(BaseModel):
    id: UUID
    company_id: UUID
    code: str
    name: str
    description: str | None
    is_active: bool
    version: int
    versions: list[SalaryStructureVersionRead]
    created_at: str
    updated_at: str


def salary_structure_line_to_read(
    row: "SalaryStructureLine", component: "SalaryComponent"
) -> SalaryStructureLineRead:
    return SalaryStructureLineRead(
        id=row.id,
        salary_component_id=row.salary_component_id,
        component_code=component.code,
        component_name=component.name,
        component_type=component.component_type,
        calculation_type=row.calculation_type,
        percentage=(
            format(row.percentage.normalize(), "f") if row.percentage is not None else None
        ),
        amount_monthly_minor=row.amount_monthly_minor,
        base_salary_component_id=row.base_salary_component_id,
        max_monthly_minor=row.max_monthly_minor,
        applies_when=row.applies_when,
        display_order=row.display_order,
    )


def salary_structure_version_to_read(
    row: "SalaryStructureVersion", lines: list[SalaryStructureLineRead]
) -> SalaryStructureVersionRead:
    return SalaryStructureVersionRead(
        id=row.id,
        salary_structure_id=row.salary_structure_id,
        version_number=row.version_number,
        status=row.status,
        effective_from=row.effective_from,
        effective_to=row.effective_to,
        published_at=_format_timestamp(row.published_at),
        version=row.version,
        lines=lines,
    )


def salary_structure_to_read(
    row: "SalaryStructure", versions: list[SalaryStructureVersionRead]
) -> SalaryStructureRead:
    return SalaryStructureRead(
        id=row.id,
        company_id=row.company_id,
        code=row.code,
        name=row.name,
        description=row.description,
        is_active=row.is_active,
        version=row.version,
        versions=versions,
        created_at=_format_timestamp(row.created_at) or "",
        updated_at=_format_timestamp(row.updated_at) or "",
    )


# ---------------------------------------------------------------------------
# Breakup
# ---------------------------------------------------------------------------


class SalaryBreakupPreviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    annual_ctc_minor: int = Field(gt=0)
    pf_applicable: bool = True
    esi_applicable: bool = False


class SalaryBreakupLineRead(BaseModel):
    component_code: str
    component_name: str
    component_type: str
    monthly_minor: int
    annual_minor: int
    basis: str


class SalaryBreakupRead(BaseModel):
    annual_ctc_minor: int
    monthly_ctc_minor: int
    gross_monthly_minor: int
    employer_contributions_monthly_minor: int
    lines: list[SalaryBreakupLineRead]


class EmployeeSalaryBreakupRead(BaseModel):
    """An employee's pay as of a date: the structure breakup for a monthly-paid employee, or the
    daily rate for a daily-wage one (D5) — `breakup` is `None` then."""

    employee_id: UUID
    as_of: date
    pay_basis: str
    salary_structure_id: UUID | None
    salary_structure_version_id: UUID | None
    daily_rate_minor: int | None
    pf_applicable: bool
    esi_applicable: bool
    breakup: SalaryBreakupRead | None


# ---------------------------------------------------------------------------
# Employee salary assignment
# ---------------------------------------------------------------------------


class EmployeeSalaryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    salary_structure_id: UUID | None = None
    daily_rate_minor: int | None = Field(default=None, gt=0)
    effective_from: date
    reason: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_basis(self) -> "EmployeeSalaryCreate":
        if (self.salary_structure_id is None) == (self.daily_rate_minor is None):
            raise ValueError("Send either salary_structure_id or daily_rate_minor")
        return self


class EmployeeSalaryRead(BaseModel):
    id: UUID
    company_id: UUID
    employee_id: UUID
    salary_structure_id: UUID | None
    daily_rate_minor: int | None
    effective_from: date
    effective_to: date | None
    reason: str | None
    version: int
    created_at: str
    updated_at: str


def employee_salary_to_read(row: "EmployeeSalary") -> EmployeeSalaryRead:
    return EmployeeSalaryRead(
        id=row.id,
        company_id=row.company_id,
        employee_id=row.employee_id,
        salary_structure_id=row.salary_structure_id,
        daily_rate_minor=row.daily_rate_minor,
        effective_from=row.effective_from,
        effective_to=row.effective_to,
        reason=row.reason,
        version=row.version,
        created_at=_format_timestamp(row.created_at) or "",
        updated_at=_format_timestamp(row.updated_at) or "",
    )


class EmployeeSalaryBulkAssign(BaseModel):
    """Assign one structure to monthly-paid employees who have no salary assignment covering
    `effective_from` — the one-off step that lets existing employees reach their first pay run.
    Without `employee_ids`, every such employee employed on that date."""

    model_config = ConfigDict(extra="forbid")

    salary_structure_id: UUID
    effective_from: date
    reason: str = Field(default="Initial salary structure assignment", min_length=1, max_length=500)
    employee_ids: list[UUID] | None = Field(default=None, min_length=1, max_length=5000)


class EmployeeSalaryBulkSkip(BaseModel):
    employee_id: UUID
    reason: str


class EmployeeSalaryBulkResult(BaseModel):
    assigned: list[UUID]
    skipped: list[EmployeeSalaryBulkSkip]
