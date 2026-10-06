"""Pydantic request/response shapes for the Leave module (L1/L2/L4)."""

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Annotated, Any, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from hrms.modules.leave.year import LEAVE_YEAR_TYPES

if TYPE_CHECKING:
    from hrms.modules.leave.models import (
        LeaveApplication,
        LeaveApplicationAction,
        LeaveApplicationDay,
        LeaveCombinationRule,
        LeaveLedgerEntry,
        LeavePolicy,
        LeavePolicyVersion,
        LeaveType,
        LeaveYearSetting,
        StatutoryLeaveMinimum,
    )

_ACCRUAL_FREQUENCIES = ("NONE", "MONTHLY", "YEARLY")
# Decision 11 (`docs/audits/PAYROLL_BUSINESS_DECISIONS.md`) — what happens at leave-year start.
_YEAR_END_ACTIONS = ("CARRY_FORWARD", "LAPSE", "ENCASH_EXCESS")
# LD-23 — client's three-level chain (Manager -> Head of Department -> HR), same "engine reads
# whatever HR configures" posture as every other approval_chain value.
_APPROVAL_CHAINS = ("AUTO", "MANAGER", "MANAGER_THEN_HR", "MANAGER_THEN_HOD_THEN_HR", "HR")
# LD-22 — client spec §16. Fixed statutory taxonomy a company's free-form leave types classify
# against; kept in sync with the migration's CHECK constraint on both `leave_type` and
# `statutory_leave_minimum`.
STATUTORY_LEAVE_CATEGORIES = ("EARNED", "SICK", "CASUAL", "MATERNITY", "PATERNITY")
_LEDGER_ENTRY_TYPES = (
    "ACCRUAL",
    "APPLICATION",
    "ADJUSTMENT",
    "ENCASHMENT",
    "CARRY_FORWARD",
    "COMP_OFF_CREDIT",
)
_HALF_DAY_VALUES = ("FIRST_HALF", "SECOND_HALF")

#: Decision 15 - the longest span, in calendar days, one leave application may cover. Enforced at
#: the schema so an oversized range is refused before any per-day calendar or period work runs.
MAX_LEAVE_REQUEST_DAYS = 90


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
    # LEAVE_DECISION_LOG.md LD-14 — marks this the company's comp-off balance type. At most one
    # active is_comp_off=true leave type per company (DB partial unique index); the L5 credit
    # engine skips crediting for a company that hasn't designated one yet.
    is_comp_off: bool = False
    # LD-22 — client spec §16. NULL (default) means this leave type has no statutory category and
    # is never checked against a `statutory_leave_minimum` floor.
    statutory_category: str | None = None

    @field_validator("statutory_category")
    @classmethod
    def validate_statutory_category(cls, value: str | None) -> str | None:
        _check_choice("statutory_category", value, STATUTORY_LEAVE_CATEGORIES)
        return value


class LeaveTypeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=150)
    is_paid_default: bool | None = None
    requires_balance: bool | None = None
    is_comp_off: bool | None = None
    statutory_category: str | None = None
    is_active: bool | None = None

    @field_validator("statutory_category")
    @classmethod
    def validate_statutory_category(cls, value: str | None) -> str | None:
        _check_choice("statutory_category", value, STATUTORY_LEAVE_CATEGORIES)
        return value


class LeaveTypeRead(BaseModel):
    id: UUID
    company_id: UUID
    code: str
    name: str
    is_paid_default: bool
    requires_balance: bool
    is_comp_off: bool
    statutory_category: str | None
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
        is_comp_off=row.is_comp_off,
        statutory_category=row.statutory_category,
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
    negative_balance_floor: Decimal | None = Field(default=None, ge=0, le=365)
    year_end_action: str = "CARRY_FORWARD"
    sandwich_rule_enabled: bool = True
    reserve_balance_on_submission: bool = False
    pre_delivery_days: int | None = Field(default=None, ge=0)
    post_delivery_days: int | None = Field(default=None, ge=0)
    allowed_during_probation: bool = True
    accrue_during_probation: bool = True
    max_consecutive_days: int = Field(default=30, ge=1, le=MAX_LEAVE_REQUEST_DAYS)
    max_encashment_days: Decimal | None = Field(default=None, ge=0)
    min_balance_after_encashment: Decimal | None = Field(default=None, ge=0)
    encashment_frequency: str | None = Field(default=None, max_length=20)
    encashment_calculation_basis: str | None = Field(default=None, max_length=50)

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

    @field_validator("year_end_action")
    @classmethod
    def validate_year_end_action(cls, value: str) -> str:
        _check_choice("year_end_action", value, _YEAR_END_ACTIONS)
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
    negative_balance_floor: Decimal | None = Field(default=None, ge=0, le=365)
    year_end_action: str | None = None
    sandwich_rule_enabled: bool | None = None
    reserve_balance_on_submission: bool | None = None
    pre_delivery_days: int | None = Field(default=None, ge=0)
    post_delivery_days: int | None = Field(default=None, ge=0)
    allowed_during_probation: bool | None = None
    accrue_during_probation: bool | None = None
    max_consecutive_days: int | None = Field(default=None, ge=1, le=MAX_LEAVE_REQUEST_DAYS)
    max_encashment_days: Decimal | None = Field(default=None, ge=0)
    min_balance_after_encashment: Decimal | None = Field(default=None, ge=0)
    encashment_frequency: str | None = Field(default=None, max_length=20)
    encashment_calculation_basis: str | None = Field(default=None, max_length=50)

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

    @field_validator("year_end_action")
    @classmethod
    def validate_year_end_action(cls, value: str | None) -> str | None:
        _check_choice("year_end_action", value, _YEAR_END_ACTIONS)
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
    negative_balance_floor: Decimal | None
    year_end_action: str
    sandwich_rule_enabled: bool
    reserve_balance_on_submission: bool
    pre_delivery_days: int | None
    post_delivery_days: int | None
    allowed_during_probation: bool
    accrue_during_probation: bool
    max_consecutive_days: int
    max_encashment_days: Decimal | None
    min_balance_after_encashment: Decimal | None
    encashment_frequency: str | None
    encashment_calculation_basis: str | None

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
        negative_balance_floor=row.negative_balance_floor,
        year_end_action=row.year_end_action,
        sandwich_rule_enabled=row.sandwich_rule_enabled,
        reserve_balance_on_submission=row.reserve_balance_on_submission,
        pre_delivery_days=row.pre_delivery_days,
        post_delivery_days=row.post_delivery_days,
        allowed_during_probation=row.allowed_during_probation,
        accrue_during_probation=row.accrue_during_probation,
        max_consecutive_days=row.max_consecutive_days,
        max_encashment_days=row.max_encashment_days,
        min_balance_after_encashment=row.min_balance_after_encashment,
        encashment_frequency=row.encashment_frequency,
        encashment_calculation_basis=row.encashment_calculation_basis,
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
    """Input for a manual HR balance correction, writing a generic `ADJUSTMENT` entry
    (ACCRUAL/APPLICATION/CARRY_FORWARD/COMP_OFF_CREDIT are reserved for L3/L4/L5; `ENCASHMENT`
    has its own dedicated, validated path — `LeaveLedgerEncashmentCreate` below, LD-19).
    `employee_id` lives in the body, mirroring `RegularizationRequestCreate`'s convention, not a
    query param."""

    model_config = ConfigDict(extra="forbid")

    employee_id: UUID
    leave_type_id: UUID
    # LM-07 - `leave_ledger.amount` is NUMERIC(6, 2): bound the input to what the column stores so
    # an oversized or over-precise value is a field-level 422, not a database error.
    amount: Decimal = Field(
        description="Signed — positive credits, negative debits.",
        max_digits=6,
        decimal_places=2,
        gt=Decimal("-10000"),
        lt=Decimal("10000"),
    )
    effective_date: date
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("amount")
    @classmethod
    def validate_amount_nonzero(cls, value: Decimal) -> Decimal:
        if value == 0:
            raise ValueError("amount must not be zero")
        return value


class LeaveLedgerEncashmentCreate(BaseModel):
    """Input for L2.5's dedicated encashment path (client spec §12, LD-19) — `days` is always
    positive (the amount encashed, debited from balance), unlike `LeaveLedgerAdjustmentCreate.
    amount`'s signed shape. Validated against the applicable `LeavePolicyVersion`'s
    `encashment_allowed`/`max_encashment_days`/`min_balance_after_encashment` before writing an
    `ENCASHMENT` entry — never a bare unvalidated adjustment."""

    model_config = ConfigDict(extra="forbid")

    employee_id: UUID
    leave_type_id: UUID
    days: Decimal = Field(gt=0, lt=Decimal("10000"), max_digits=6, decimal_places=2)
    effective_date: date
    reason: str = Field(min_length=1, max_length=2000)


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


#: Decision 19 - a ledger entry's free-text `reason` stays on the ledger row (the business record,
#: reachable by `ledger_entry id`) and is not duplicated into the audit log.
_LEDGER_AUDIT_EXCLUDED = ("reason",)


def leave_ledger_entry_to_audit_dict(read: LeaveLedgerEntryRead) -> dict[str, Any]:
    return {
        key: value
        for key, value in read.model_dump(mode="json").items()
        if key not in _LEDGER_AUDIT_EXCLUDED
    }


class LeaveBalanceRead(BaseModel):
    """One row per leave type that `requires_balance` — a type with zero ledger activity still
    appears, with `balance=0`, rather than being silently omitted.

    `balance` (LD-03's derived ledger sum, "Available Balance" in the client's own terminology)
    is never reduced by a pending application unless `reserve_balance_on_submission` is enabled
    for it — `reserved_balance` (LD-15) is always shown alongside it regardless, so HR/employee
    can see both figures separately (client spec §8) even when reservation itself is off."""

    employee_id: UUID
    leave_type_id: UUID
    leave_type_code: str
    leave_type_name: str
    balance: Decimal
    reserved_balance: Decimal


# ---------------------------------------------------------------------------
# Leave Application — L4
# ---------------------------------------------------------------------------


class LeaveApplicationCreate(BaseModel):
    """Shared by self-submit and on-behalf-submit (router decides `employee_id`, mirrors
    `RegularizationRequestCreate`'s convention). `half_day` is only valid for a single-day
    application (`start_date == end_date`) — this first cut does not support a half-day
    boundary on a multi-day range (e.g. half day at the start, full days between, half day at
    the end); every day in a multi-day range is a full day or a sandwich-rule-generated day."""

    model_config = ConfigDict(extra="forbid")

    employee_id: UUID | None = None
    leave_type_id: UUID
    start_date: date
    end_date: date
    half_day: str | None = None
    reason: str | None = None
    attachment_reference: str | None = Field(default=None, max_length=500)
    # LD-17 — client spec §F. Generic and optional, harmless for every non-maternity leave type;
    # never read by day-counting or balance logic, purely informational.
    expected_delivery_date: date | None = None

    @field_validator("half_day")
    @classmethod
    def validate_half_day(cls, value: str | None) -> str | None:
        if value is not None and value not in _HALF_DAY_VALUES:
            raise ValueError(f"half_day must be one of {_HALF_DAY_VALUES}")
        return value

    @model_validator(mode="after")
    def validate_date_range(self) -> Self:
        if self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        if (self.end_date - self.start_date).days + 1 > MAX_LEAVE_REQUEST_DAYS:
            raise ValueError(
                f"A leave application cannot span more than {MAX_LEAVE_REQUEST_DAYS} calendar days"
            )
        if self.half_day is not None and self.start_date != self.end_date:
            raise ValueError("half_day is only valid for a single-day application")
        return self


class LeaveApplicationReviewInput(BaseModel):
    """Body for approve/reject — mirrors `RegularizationReviewInput` exactly. `rejection_reason`
    is only meaningful on reject; ignored (not an error) if supplied on approve."""

    model_config = ConfigDict(extra="forbid")

    reviewer_comment: str | None = None
    rejection_reason: str | None = None
    # PAY-010 (decision 9) — approve even though the balance no longer covers the application:
    # the uncovered days become unpaid (LOP) leave. Without it such an approval is refused with
    # `LEAVE_APPLICATION_BALANCE_SHORTFALL`, whose details state the shortfall.
    excess_as_lop: bool = False


class LeaveApplicationReassignInput(BaseModel):
    """Decision 13 - HR hands a stuck approval stage to another approver. `reason` is mandatory."""

    model_config = ConfigDict(extra="forbid")

    new_approver_employee_id: UUID
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class LeaveApplicationCancelInput(BaseModel):
    """Optional body for cancel. `reason` is mandatory when HR cancels an approved application
    that has already started (decision 10); recorded whenever given."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=2000)


class LeaveApplicationDayRead(BaseModel):
    id: UUID
    calendar_date: date
    fraction: Decimal
    half: str | None
    is_sandwich_generated: bool
    is_lop: bool
    leave_day_projection_id: UUID | None


def leave_application_day_to_read(row: "LeaveApplicationDay") -> LeaveApplicationDayRead:
    return LeaveApplicationDayRead(
        id=row.id,
        calendar_date=row.calendar_date,
        fraction=row.fraction,
        half=row.half,
        is_sandwich_generated=row.is_sandwich_generated,
        is_lop=row.is_lop,
        leave_day_projection_id=row.leave_day_projection_id,
    )


class LeaveApplicationActionRead(BaseModel):
    id: UUID
    action: str
    actor_user_id: UUID | None
    actor_employee_id: UUID | None
    stage: str | None
    comment: str | None
    created_at: str


def leave_application_action_to_read(row: "LeaveApplicationAction") -> LeaveApplicationActionRead:
    return LeaveApplicationActionRead(
        id=row.id,
        action=row.action,
        actor_user_id=row.actor_user_id,
        actor_employee_id=row.actor_employee_id,
        stage=row.stage,
        comment=row.comment,
        created_at=_format_timestamp(row.created_at) or "",
    )


class LeaveApplicationRead(BaseModel):
    id: UUID
    company_id: UUID
    employee_id: UUID
    leave_type_id: UUID
    leave_policy_version_id: UUID

    start_date: date
    end_date: date
    total_days: Decimal
    lop_days: Decimal
    reason: str | None
    attachment_reference: str | None
    expected_delivery_date: date | None

    status: str
    approval_chain: str
    approval_stage: str | None
    resolved_approver_manager_id: UUID | None
    resolved_department_head_id: UUID | None

    submitted_by_user_id: UUID | None
    submitted_at: str

    reviewed_by_user_id: UUID | None
    reviewed_at: str | None
    reviewer_comment: str | None
    rejection_reason: str | None

    cancelled_at: str | None
    cancelled_by_user_id: UUID | None
    cancellation_reason: str | None

    version: int

    days: list[LeaveApplicationDayRead]
    actions: list[LeaveApplicationActionRead]

    created_at: str
    updated_at: str


def leave_application_to_read(
    row: "LeaveApplication",
    *,
    days: list["LeaveApplicationDay"],
    actions: list["LeaveApplicationAction"],
) -> LeaveApplicationRead:
    return LeaveApplicationRead(
        id=row.id,
        company_id=row.company_id,
        employee_id=row.employee_id,
        leave_type_id=row.leave_type_id,
        leave_policy_version_id=row.leave_policy_version_id,
        start_date=row.start_date,
        end_date=row.end_date,
        total_days=row.total_days,
        lop_days=row.lop_days,
        reason=row.reason,
        attachment_reference=row.attachment_reference,
        expected_delivery_date=row.expected_delivery_date,
        status=row.status,
        approval_chain=row.approval_chain,
        approval_stage=row.approval_stage,
        resolved_approver_manager_id=row.resolved_approver_manager_id,
        resolved_department_head_id=row.resolved_department_head_id,
        submitted_by_user_id=row.submitted_by_user_id,
        submitted_at=_format_timestamp(row.submitted_at) or "",
        reviewed_by_user_id=row.reviewed_by_user_id,
        reviewed_at=_format_timestamp(row.reviewed_at),
        reviewer_comment=row.reviewer_comment,
        rejection_reason=row.rejection_reason,
        cancelled_at=_format_timestamp(row.cancelled_at),
        cancelled_by_user_id=row.cancelled_by_user_id,
        cancellation_reason=row.cancellation_reason,
        version=row.version,
        days=[leave_application_day_to_read(d) for d in days],
        actions=[leave_application_action_to_read(a) for a in actions],
        created_at=_format_timestamp(row.created_at) or "",
        updated_at=_format_timestamp(row.updated_at) or "",
    )


#: Decision 19 - what an application contributes to the immutable audit log: structure only. The
#: free-text fields (`reason`, `attachment_reference`, `expected_delivery_date`, the reviewer's
#: comment, the rejection and cancellation reasons) can carry medical or personal detail and could
#: never be erased once written, so they stay on the application itself and are NOT copied here.
#: An explicit allow-list: a field added to `LeaveApplicationRead` later is excluded until someone
#: decides it belongs.
LEAVE_APPLICATION_AUDIT_FIELDS: tuple[str, ...] = (
    "id",
    "employee_id",
    "leave_type_id",
    "leave_policy_version_id",
    "start_date",
    "end_date",
    "total_days",
    "lop_days",
    "status",
    "approval_chain",
    "approval_stage",
    "resolved_approver_manager_id",
    "resolved_department_head_id",
    "submitted_by_user_id",
    "submitted_at",
    "reviewed_by_user_id",
    "reviewed_at",
    "cancelled_at",
    "cancelled_by_user_id",
    "version",
)


def leave_application_to_audit_dict(read: LeaveApplicationRead) -> dict[str, Any]:
    full = read.model_dump(mode="json")
    return {field: full[field] for field in LEAVE_APPLICATION_AUDIT_FIELDS}


# ---------------------------------------------------------------------------
# Leave Combination Rule — client spec §7 (LD-16)
# ---------------------------------------------------------------------------


class LeaveCombinationRuleCreate(BaseModel):
    """`leave_type_id_a`/`_b` may be given in either order — the pair is unordered (LD-16)."""

    model_config = ConfigDict(extra="forbid")

    leave_type_id_a: UUID
    leave_type_id_b: UUID
    allowed: bool
    reason: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_distinct_types(self) -> "LeaveCombinationRuleCreate":
        if self.leave_type_id_a == self.leave_type_id_b:
            raise ValueError("leave_type_id_a and leave_type_id_b must be different leave types")
        return self


class LeaveCombinationRuleRead(BaseModel):
    id: UUID
    company_id: UUID
    leave_type_id_a: UUID
    leave_type_id_b: UUID
    allowed: bool
    reason: str | None
    created_by_user_id: UUID | None
    created_at: str
    updated_at: str


def leave_combination_rule_to_read(row: "LeaveCombinationRule") -> LeaveCombinationRuleRead:
    return LeaveCombinationRuleRead(
        id=row.id,
        company_id=row.company_id,
        leave_type_id_a=row.leave_type_id_a,
        leave_type_id_b=row.leave_type_id_b,
        allowed=row.allowed,
        reason=row.reason,
        created_by_user_id=row.created_by_user_id,
        created_at=_format_timestamp(row.created_at) or "",
        updated_at=_format_timestamp(row.updated_at) or "",
    )


def leave_combination_rule_to_audit_dict(read: LeaveCombinationRuleRead) -> dict[str, Any]:
    return read.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Leave Year Setting — client spec §10 (LD-20), singleton per company
# ---------------------------------------------------------------------------


class LeaveYearSettingUpsert(BaseModel):
    """`start_month`/`start_day` only apply to `CUSTOM` — required together when
    `leave_year_type=CUSTOM`, ignored (must be omitted) otherwise, since `CALENDAR`/`FINANCIAL`
    have fixed, non-configurable start dates and `ANNIVERSARY` has no company-wide date at all
    (LD-20)."""

    model_config = ConfigDict(extra="forbid")

    leave_year_type: str
    start_month: int | None = Field(default=None, ge=1, le=12)
    start_day: int | None = Field(default=None, ge=1, le=31)

    @field_validator("leave_year_type")
    @classmethod
    def validate_leave_year_type(cls, value: str) -> str:
        _check_choice("leave_year_type", value, LEAVE_YEAR_TYPES)
        return value

    @model_validator(mode="after")
    def validate_custom_requires_start(self) -> "LeaveYearSettingUpsert":
        if self.leave_year_type == "CUSTOM":
            if self.start_month is None or self.start_day is None:
                raise ValueError(
                    "start_month and start_day are required when leave_year_type is CUSTOM"
                )
        elif self.start_month is not None or self.start_day is not None:
            raise ValueError(
                "start_month/start_day are only meaningful when leave_year_type is CUSTOM"
            )
        return self


class LeaveYearSettingRead(BaseModel):
    id: UUID
    company_id: UUID
    leave_year_type: str
    start_month: int | None
    start_day: int | None
    version: int
    created_at: str
    updated_at: str


def leave_year_setting_to_read(row: "LeaveYearSetting") -> LeaveYearSettingRead:
    return LeaveYearSettingRead(
        id=row.id,
        company_id=row.company_id,
        leave_year_type=row.leave_year_type,
        start_month=row.start_month,
        start_day=row.start_day,
        version=row.version,
        created_at=_format_timestamp(row.created_at) or "",
        updated_at=_format_timestamp(row.updated_at) or "",
    )


def leave_year_setting_to_audit_dict(read: LeaveYearSettingRead) -> dict[str, Any]:
    return read.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Statutory Leave Minimum — client spec §16 (LD-22), legal compliance floor
# ---------------------------------------------------------------------------


class StatutoryLeaveMinimumCreate(BaseModel):
    """`state_code`/`establishment_type` are optional narrowing dimensions, not required
    identifiers — `None` on either means "applies regardless of that dimension" (LD-22)."""

    model_config = ConfigDict(extra="forbid")

    state_code: str | None = Field(default=None, max_length=10)
    establishment_type: str | None = Field(default=None, max_length=30)
    leave_category: str
    min_days_per_year: Decimal = Field(gt=0)
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("leave_category")
    @classmethod
    def validate_leave_category(cls, value: str) -> str:
        _check_choice("leave_category", value, STATUTORY_LEAVE_CATEGORIES)
        return value


class StatutoryLeaveMinimumRead(BaseModel):
    id: UUID
    company_id: UUID
    state_code: str | None
    establishment_type: str | None
    leave_category: str
    min_days_per_year: Decimal
    note: str | None
    created_by_user_id: UUID | None
    created_at: str
    updated_at: str


def statutory_leave_minimum_to_read(row: "StatutoryLeaveMinimum") -> StatutoryLeaveMinimumRead:
    return StatutoryLeaveMinimumRead(
        id=row.id,
        company_id=row.company_id,
        state_code=row.state_code,
        establishment_type=row.establishment_type,
        leave_category=row.leave_category,
        min_days_per_year=row.min_days_per_year,
        note=row.note,
        created_by_user_id=row.created_by_user_id,
        created_at=_format_timestamp(row.created_at) or "",
        updated_at=_format_timestamp(row.updated_at) or "",
    )


def statutory_leave_minimum_to_audit_dict(read: StatutoryLeaveMinimumRead) -> dict[str, Any]:
    return read.model_dump(mode="json")
