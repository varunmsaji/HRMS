from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from hrms.core.auth.passwords import PASSWORD_MAX_LENGTH

CompanyStatus = Literal[
    "PENDING_APPROVAL", "TRIAL", "ACTIVE", "SUSPENDED", "REJECTED", "TERMINATED"
]

#: A mandatory, human-readable reason (stored in the audit trail and emailed to the company).
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlatformLoginRequest(_Strict):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)

    @field_validator("username")
    @classmethod
    def _normalise(cls, value: str) -> str:
        return value.strip().lower()


class PlatformTokenData(BaseModel):
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_at: datetime
    username: str


class PlatformMe(BaseModel):
    username: str


class ReasonRequest(_Strict):
    reason: Reason


class OptionalReasonRequest(_Strict):
    reason: Reason | None = None


class TerminateRequest(_Strict):
    reason: Reason
    confirm_name: str = Field(min_length=1, max_length=200)


class SubscriptionPatch(_Strict):
    plan_code: str | None = Field(default=None, min_length=1, max_length=40)
    extend_trial_days: int | None = Field(default=None, ge=1, le=365)
    #: Explicit `null` clears the override; omit the key to leave it unchanged.
    seat_limit_override: int | None = Field(default=None, ge=1, le=1_000_000)
    reason: Reason | None = None


class CompanyListItem(BaseModel):
    id: UUID
    name: str
    status: CompanyStatus
    industry_code: str | None
    company_size: str | None
    created_at: datetime
    trial_ends_at: datetime | None
    admin_email: str | None
    admin_name: str | None


class SubscriptionInfo(BaseModel):
    plan_code: str
    plan_name: str
    status: str
    trial_ends_at: datetime | None
    seat_limit_override: int | None


class UsageInfo(BaseModel):
    employees: int
    active_users: int


class CompanyDetail(CompanyListItem):
    country_code: str
    timezone: str
    status_reason: str | None
    status_changed_at: datetime | None
    approved_at: datetime | None
    retention_until: datetime | None
    admin_locked: bool
    subscription: SubscriptionInfo | None
    usage: UsageInfo


class DashboardData(BaseModel):
    counts_by_status: dict[str, int]
    pending_count: int
    oldest_pending_since: datetime | None
    trials_expiring_within_7_days: int


class PlatformAuditEntry(BaseModel):
    id: UUID
    created_at: datetime
    actor_username: str | None
    action: str
    company_id: UUID | None
    reason: str | None
    before_status: str | None
    after_status: str | None
    request_id: str | None
