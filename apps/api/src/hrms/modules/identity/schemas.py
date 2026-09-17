from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from hrms.shared.pagination import ResponseMeta


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)
    company_id: UUID | None = None


class RefreshRequest(BaseModel):
    refresh_token: str | None = None


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    password: str = Field(min_length=1)


class CompanySummary(BaseModel):
    id: UUID
    name: str
    is_primary: bool


class TokenResponseData(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in_minutes: int
    company_id: UUID
    companies: list[CompanySummary] = Field(default_factory=list)


class UserProfile(BaseModel):
    id: UUID
    email: str | None
    company_id: UUID
    employee_id: UUID | None
    permissions: list[str]
    # `TZ-07` (execution gate §13, Phase 4/6) — the resolved business timezone, shipped in the
    # session/bootstrap payload so the web client can compute `businessToday()` and render
    # attendance timestamps without a separate round trip or client-side guesswork. Always
    # `Company.timezone` here (never a per-shift/branch WD-06 resolution) — this is the
    # session-wide default the UI falls back to; any screen showing a specific employee's
    # attendance uses that record's own already-resolved timezone instead.
    company_timezone: str


class MeResponseData(BaseModel):
    user: UserProfile


class CompanyDetail(BaseModel):
    id: UUID
    name: str
    status: str


def build_meta(request_id: str) -> ResponseMeta:
    return ResponseMeta(
        request_id=request_id,
        server_time=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )
