"""Pydantic request/response shapes for the Leave module (L1/L2)."""

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

if TYPE_CHECKING:
    from hrms.modules.leave.models import (
        LeaveLedgerEntry,
        LeavePolicy,
        LeavePolicyVersion,
        LeaveType,
    )

_ACCRUAL_FREQUENCIES = ("NONE", "MONTHLY", "YEARLY")
_APPROVAL_CHAINS = ("AUTO", "MANAGER", "MANAGER_THEN_HR", "HR")
_LEDGER_ENTRY_TYPES = (
    "ACCRUAL",
    "APPLICATION",
    "ADJUSTMENT",
    "ENCASHMENT",
    "CARRY_FORWARD",
    "COMP_OFF_CREDIT",
)


def _format_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    iso = str(value.isoformat())
    return iso.replace("+00:00", "Z")


def _check_choice(field: str, value: str | None, choices: tuple[str, ...]) -> None:
    if value is not None and value not in choices:
        raise ValueError(f"{field} must be one of {choices}")


# ---------------------------------------------------------------------------
# Leave Type
# ---------------------------------------------------------------------------


class LeaveTypeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=150)
    is_paid_default: bool = True
    requires_balance: bool = True


class LeaveTypeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=150)
    is_paid_default: bool | None = None
    requires_balance: bool | None = None
    is_active: bool | None = None


class LeaveTypeRead(BaseModel):
    id: UUID
    company_id: UUID
    code: str
    name: str
    is_paid_default: bool
    requires_balance: bool
    is_active: bool
    version: int
    created_at: str
    updated_at: str


def leave_type_to_read(row: "LeaveType") -> LeaveTypeRead:
    return LeaveTypeRead(
        id=row.id,
        company_id=row.company_id,
        code=row.code,
        name=row.name,
        is_paid_default=row.is_paid_default,
        requires_balance=row.requires_balance,
        is_active=row.is_active,
        version=row.version,
        created_at=_format_timestamp(row.created_at) or "",
        updated_at=_format_timestamp(row.updated_at) or "",
    )


def leave_type_to_audit_dict(read: LeaveTypeRead) -> dict[str, Any]:
    return read.model_dump(mode="json")


def build_leave_type_update_values(patch: LeaveTypeUpdate) -> dict[str, Any]:
    return {field: getattr(patch, field) for field in patch.model_fields_set}


# ---------------------------------------------------------------------------
# Leave Policy — identity
# ---------------------------------------------------------------------------


class LeavePolicyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    leave_type_id: UUID
    name: str = Field(min_length=1, max_length=150)
    code: str | None = Field(default=None, max_length=30)


class LeavePolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=150)
    code: str | None = Field(default=None, max_length=30)
    is_active: bool | None = None


class LeavePolicyRead(BaseModel):
    id: UUID
    company_id: UUID
    leave_type_id: UUID
    name: str
    code: str | None
    is_active: bool
    version: int
    created_at: str
    updated_at: str


def leave_policy_to_read(row: "LeavePolicy") -> LeavePolicyRead:
    return LeavePolicyRead(
        id=row.id,
        company_id=row.company_id,
        leave_type_id=row.leave_type_id,
        name=row.name,
        code=row.code,
        is_active=row.is_active,
        version=row.version,
        created_at=_format_timestamp(row.created_at) or "",
        updated_at=_format_timestamp(row.updated_at) or "",
    )


def leave_policy_to_audit_dict(read: LeavePolicyRead) -> dict[str, Any]:
    return read.model_dump(mode="json")


def build_leave_policy_update_values(patch: LeavePolicyUpdate) -> dict[str, Any]:
    return {field: getattr(patch, field) for field in patch.model_fields_set}


# ---------------------------------------------------------------------------
# Leave Policy — versions
# ---------------------------------------------------------------------------


class LeavePolicyVersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effective_from: date | None = None
    allow_employee_request: bool = True
    allow_manager_request_on_behalf: bool = True
    allow_hr_request_on_behalf: bool = True
    max_backdated_days: int | None = None
    max_requests_per_month: int | None = None
    reason_required: bool = True
    attachment_required: bool = False
    approval_chain: str = "MANAGER"
    half_day_allowed: bool = True
    accrual_frequency: str = "NONE"
    accrual_rate_per_cycle: Decimal | None = Field(default=None, ge=0)
    max_carry_forward_days: Decimal | None = Field(default=None, ge=0)
    encashment_allowed: bool = False
    allow_negative_balance: bool = False
    sandwich_rule_enabled: bool = True

    @field_validator("approval_chain")
    @classmethod
    def validate_approval_chain(cls, value: str) -> str:
        _check_choice("approval_chain", value, _APPROVAL_CHAINS)
        return value

    @field_validator("accrual_frequency")
    @classmethod
    def validate_accrual_frequency(cls, value: str) -> str:
        _check_choice("accrual_frequency", value, _ACCRUAL_FREQUENCIES)
        return value


class LeavePolicyVersionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effective_from: date | None = None
    allow_employee_request: bool | None = None
    allow_manager_request_on_behalf: bool | None = None
    allow_hr_request_on_behalf: bool | None = None
    max_backdated_days: int | None = None
    max_requests_per_month: int | None = None
    reason_required: bool | None = None
    attachment_required: bool | None = None
    approval_chain: str | None = None
    half_day_allowed: bool | None = None
    accrual_frequency: str | None = None
    accrual_rate_per_cycle: Decimal | None = Field(default=None, ge=0)
    max_carry_forward_days: Decimal | None = Field(default=None, ge=0)
    encashment_allowed: bool | None = None
    allow_negative_balance: bool | None = None
    sandwich_rule_enabled: bool | None = None

    @field_validator("approval_chain")
    @classmethod
    def validate_approval_chain(cls, value: str | None) -> str | None:
        _check_choice("approval_chain", value, _APPROVAL_CHAINS)
        return value

    @field_validator("accrual_frequency")
    @classmethod
    def validate_accrual_frequency(cls, value: str | None) -> str | None:
        _check_choice("accrual_frequency", value, _ACCRUAL_FREQUENCIES)
        return value


class LeavePolicyVersionPublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    publish_reason: str | None = Field(default=None, max_length=2000)
    expected_previous_version: int | None = None


class LeavePolicyVersionRead(BaseModel):
    id: UUID
    company_id: UUID
    policy_id: UUID
    status: str
    version: int
    effective_from: date | None
    effective_to: date | None

    allow_employee_request: bool
    allow_manager_request_on_behalf: bool
    allow_hr_request_on_behalf: bool
    max_backdated_days: int | None
    max_requests_per_month: int | None
    reason_required: bool
    attachment_required: bool
    approval_chain: str
    half_day_allowed: bool

    accrual_frequency: str
    accrual_rate_per_cycle: Decimal | None
    max_carry_forward_days: Decimal | None
    encashment_allowed: bool
    allow_negative_balance: bool
    sandwich_rule_enabled: bool

    publish_reason: str | None
    published_at: str | None
    published_by: UUID | None
    created_at: str
    updated_at: str


def leave_policy_version_to_read(row: "LeavePolicyVersion") -> LeavePolicyVersionRead:
    return LeavePolicyVersionRead(
        id=row.id,
        company_id=row.company_id,
        policy_id=row.policy_id,
        status=row.status,
        version=row.version,
        effective_from=row.effective_from,
        effective_to=row.effective_to,
        allow_employee_request=row.allow_employee_request,
        allow_manager_request_on_behalf=row.allow_manager_request_on_behalf,
        allow_hr_request_on_behalf=row.allow_hr_request_on_behalf,
        max_backdated_days=row.max_backdated_days,
        max_requests_per_month=row.max_requests_per_month,
        reason_required=row.reason_required,
        attachment_required=row.attachment_required,
        approval_chain=row.approval_chain,
        half_day_allowed=row.half_day_allowed,
        accrual_frequency=row.accrual_frequency,
        accrual_rate_per_cycle=row.accrual_rate_per_cycle,
        max_carry_forward_days=row.max_carry_forward_days,
        encashment_allowed=row.encashment_allowed,
        allow_negative_balance=row.allow_negative_balance,
        sandwich_rule_enabled=row.sandwich_rule_enabled,
        publish_reason=row.publish_reason,
        published_at=_format_timestamp(row.published_at),
        published_by=row.published_by,
        created_at=_format_timestamp(row.created_at) or "",
        updated_at=_format_timestamp(row.updated_at) or "",
    )


def leave_policy_version_to_audit_dict(read: LeavePolicyVersionRead) -> dict[str, Any]:
    return read.model_dump(mode="json")


def build_leave_policy_version_update_values(patch: LeavePolicyVersionUpdate) -> dict[str, Any]:
    return {field: getattr(patch, field) for field in patch.model_fields_set}


# ---------------------------------------------------------------------------
# Leave Ledger — L2
# ---------------------------------------------------------------------------


class LeaveLedgerAdjustmentCreate(BaseModel):
    """Input for a manual HR balance correction — the only entry_type L2's API can write
    (ACCRUAL/APPLICATION/ENCASHMENT/CARRY_FORWARD/COMP_OFF_CREDIT are reserved for L3/L4/L5).
    `employee_id` lives in the body, mirroring `RegularizationRequestCreate`'s convention, not a
    query param."""

    model_config = ConfigDict(extra="forbid")

    employee_id: UUID
    leave_type_id: UUID
    amount: Decimal = Field(description="Signed — positive credits, negative debits.")
    effective_date: date
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("amount")
    @classmethod
    def validate_amount_nonzero(cls, value: Decimal) -> Decimal:
        if value == 0:
            raise ValueError("amount must not be zero")
        return value


class LeaveLedgerEntryRead(BaseModel):
    id: UUID
    company_id: UUID
    employee_id: UUID
    leave_type_id: UUID
    entry_type: str
    amount: Decimal
    effective_date: date
    reference_id: UUID | None
    reason: str | None
    created_by_user_id: UUID | None
    created_at: str


def leave_ledger_entry_to_read(row: "LeaveLedgerEntry") -> LeaveLedgerEntryRead:
    return LeaveLedgerEntryRead(
        id=row.id,
        company_id=row.company_id,
        employee_id=row.employee_id,
        leave_type_id=row.leave_type_id,
        entry_type=row.entry_type,
        amount=row.amount,
        effective_date=row.effective_date,
        reference_id=row.reference_id,
        reason=row.reason,
        created_by_user_id=row.created_by_user_id,
        created_at=_format_timestamp(row.created_at) or "",
    )


def leave_ledger_entry_to_audit_dict(read: LeaveLedgerEntryRead) -> dict[str, Any]:
    return read.model_dump(mode="json")


class LeaveBalanceRead(BaseModel):
    """One row per leave type that `requires_balance` — a type with zero ledger activity still
    appears, with `balance=0`, rather than being silently omitted."""

    employee_id: UUID
    leave_type_id: UUID
    leave_type_code: str
    leave_type_name: str
    balance: Decimal
