"""Pydantic request/response shapes for the Payroll module (Phase 5.1 — salary setup; Phase 5.2 —
pay runs)."""

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from hrms.modules.payroll.breakup import APPLIES_WHEN, CALCULATION_TYPES, COMPONENT_TYPES

if TYPE_CHECKING:
    from hrms.modules.payroll.models import (
        EmployeeSalary,
        PayrollSetting,
        PayRun,
        PayRunEmployee,
        PayRunLine,
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


# ---------------------------------------------------------------------------
# Phase 5.2 — settings and pay runs
# ---------------------------------------------------------------------------

PAY_RUN_STATUSES = ("DRAFT", "INPUTS_LOCKED", "COMPUTED", "APPROVED", "FINALISED", "PAID")


def _money_str(value: Decimal | None) -> str | None:
    return None if value is None else format(value.normalize(), "f")


class PayrollSettingRead(BaseModel):
    company_id: UUID
    variance_threshold_percent: str
    version: int


class PayrollSettingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variance_threshold_percent: Decimal = Field(gt=0, le=100, decimal_places=2)


def payroll_setting_to_read(row: "PayrollSetting") -> PayrollSettingRead:
    return PayrollSettingRead(
        company_id=row.company_id,
        variance_threshold_percent=_money_str(row.variance_threshold_percent) or "0",
        version=row.version,
    )


class PayRunCreate(BaseModel):
    """`month` is `YYYY-MM` — a pay run always covers one whole calendar month (decision 18).
    `pay_date` defaults to the first weekday of the following month (D11)."""

    model_config = ConfigDict(extra="forbid")

    legal_entity_id: UUID
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    pay_date: date | None = None


class PayRunUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pay_date: date


class PayRunRollback(BaseModel):
    """Back to `DRAFT` (drops the snapshot) or `INPUTS_LOCKED` (drops the computed pay)."""

    model_config = ConfigDict(extra="forbid")

    to_status: str
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("to_status")
    @classmethod
    def validate_target(cls, value: str) -> str:
        _check_choice("to_status", value, ("DRAFT", "INPUTS_LOCKED"))
        return value


class PayRunVarianceAcknowledge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=1000)


class PayRunRead(BaseModel):
    id: UUID
    company_id: UUID
    legal_entity_id: UUID
    month: str
    period_start: date
    period_end: date
    days_in_month: int
    status: str
    pay_date: date
    attendance_period_id: UUID | None
    variance_threshold_percent: str | None
    previous_pay_run_id: UUID | None
    employee_count: int
    gross_minor: int
    deductions_minor: int
    employer_contributions_minor: int
    net_minor: int
    error_count: int
    warning_count: int
    variance_flag_count: int
    variance_open_count: int
    created_by_user_id: UUID | None
    inputs_locked_at: str | None
    inputs_locked_by_user_id: UUID | None
    computed_at: str | None
    computed_by_user_id: UUID | None
    approved_at: str | None
    approved_by_user_id: UUID | None
    finalised_at: str | None
    finalised_by_user_id: UUID | None
    paid_at: str | None
    paid_by_user_id: UUID | None
    last_rollback_reason: str | None
    version: int
    created_at: str
    updated_at: str


def pay_run_to_read(row: "PayRun") -> PayRunRead:
    return PayRunRead(
        id=row.id,
        company_id=row.company_id,
        legal_entity_id=row.legal_entity_id,
        month=row.period_month.strftime("%Y-%m"),
        period_start=row.period_start,
        period_end=row.period_end,
        days_in_month=row.days_in_month,
        status=row.status,
        pay_date=row.pay_date,
        attendance_period_id=row.attendance_period_id,
        variance_threshold_percent=_money_str(row.variance_threshold_percent),
        previous_pay_run_id=row.previous_pay_run_id,
        employee_count=row.employee_count,
        gross_minor=row.gross_minor,
        deductions_minor=row.deductions_minor,
        employer_contributions_minor=row.employer_contributions_minor,
        net_minor=row.net_minor,
        error_count=row.error_count,
        warning_count=row.warning_count,
        variance_flag_count=row.variance_flag_count,
        variance_open_count=row.variance_open_count,
        created_by_user_id=row.created_by_user_id,
        inputs_locked_at=_format_timestamp(row.inputs_locked_at),
        inputs_locked_by_user_id=row.inputs_locked_by_user_id,
        computed_at=_format_timestamp(row.computed_at),
        computed_by_user_id=row.computed_by_user_id,
        approved_at=_format_timestamp(row.approved_at),
        approved_by_user_id=row.approved_by_user_id,
        finalised_at=_format_timestamp(row.finalised_at),
        finalised_by_user_id=row.finalised_by_user_id,
        paid_at=_format_timestamp(row.paid_at),
        paid_by_user_id=row.paid_by_user_id,
        last_rollback_reason=row.last_rollback_reason,
        version=row.version,
        created_at=_format_timestamp(row.created_at) or "",
        updated_at=_format_timestamp(row.updated_at) or "",
    )


class PayRunIssueRead(BaseModel):
    code: str
    severity: str
    message: str


class PayRunEmployeeRead(BaseModel):
    id: UUID
    employee_id: UUID
    employee_code: str | None
    employee_name: str | None
    pay_basis: str | None
    paid_days: str | None
    lop_days: str | None
    payable_days: str | None
    is_computed: bool
    gross_minor: int
    deductions_minor: int
    employer_contributions_minor: int
    rounding_minor: int
    net_minor: int
    issues: list[PayRunIssueRead]
    has_error: bool
    previous_net_minor: int | None
    variance_percent: str | None
    variance_flagged: bool
    variance_reason: str | None
    variance_acknowledged_by_user_id: UUID | None
    variance_acknowledged_at: str | None


def pay_run_employee_to_read(row: "PayRunEmployee") -> PayRunEmployeeRead:
    return PayRunEmployeeRead(
        id=row.id,
        employee_id=row.employee_id,
        employee_code=row.employee_code,
        employee_name=row.employee_name,
        pay_basis=row.pay_basis,
        paid_days=_money_str(row.paid_days),
        lop_days=_money_str(row.lop_days),
        payable_days=_money_str(row.payable_days),
        is_computed=row.is_computed,
        gross_minor=row.gross_minor,
        deductions_minor=row.deductions_minor,
        employer_contributions_minor=row.employer_contributions_minor,
        rounding_minor=row.rounding_minor,
        net_minor=row.net_minor,
        issues=[PayRunIssueRead(**issue) for issue in row.issues or []],
        has_error=row.has_error,
        previous_net_minor=row.previous_net_minor,
        variance_percent=_money_str(row.variance_percent),
        variance_flagged=row.variance_flagged,
        variance_reason=row.variance_reason,
        variance_acknowledged_by_user_id=row.variance_acknowledged_by_user_id,
        variance_acknowledged_at=_format_timestamp(row.variance_acknowledged_at),
    )


class PayRunLineRead(BaseModel):
    component_code: str
    component_name: str
    line_type: str
    full_monthly_minor: int | None
    amount_minor: int
    display_order: int
    trace: dict[str, Any]


def pay_run_line_to_read(row: "PayRunLine") -> PayRunLineRead:
    return PayRunLineRead(
        component_code=row.component_code,
        component_name=row.component_name,
        line_type=row.line_type,
        full_monthly_minor=row.full_monthly_minor,
        amount_minor=row.amount_minor,
        display_order=row.display_order,
        trace=row.trace,
    )


class PayRunEmployeeDetailRead(PayRunEmployeeRead):
    """One employee's pay in a run: the totals, every line with its trace, and the input
    snapshot the figures were computed from."""

    lines: list[PayRunLineRead]
    snapshot: dict[str, Any]
