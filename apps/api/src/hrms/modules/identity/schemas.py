from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, model_validator

from hrms.core.auth.passwords import PASSWORD_MAX_LENGTH
from hrms.shared.pagination import ResponseMeta


class LoginRequest(BaseModel):
    """Sign in with an email, or with a company code plus employee ID (e.g. `ACME` +
    `EMP-0007`). Exactly one of the two must be given."""

    email: EmailStr | None = None
    company_code: str | None = Field(default=None, min_length=1, max_length=12)
    employee_code: str | None = Field(default=None, min_length=1, max_length=30)
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)
    company_id: UUID | None = None

    @model_validator(mode="after")
    def _one_identifier(self) -> "LoginRequest":
        by_employee = self.company_code is not None or self.employee_code is not None
        if self.email is not None and by_employee:
            raise ValueError("Sign in with either an email or a company code and employee ID")
        if self.email is None:
            if not (self.company_code and self.company_code.strip()):
                raise ValueError("Company code is required to sign in with an employee ID")
            if not (self.employee_code and self.employee_code.strip()):
                raise ValueError("Email or employee ID is required")
        return self

    @property
    def login_subject(self) -> str:
        """What the caller typed, for rate limiting and failed-login logging (hashed there)."""
        if self.email is not None:
            return str(self.email)
        return f"{(self.company_code or '').strip()}/{(self.employee_code or '').strip()}".lower()


class RefreshRequest(BaseModel):
    refresh_token: str | None = None


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)


class VerifyEmailRequest(BaseModel):
    token: str


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class CompanySummary(BaseModel):
    id: UUID
    name: str
    is_primary: bool


class TokenResponseData(BaseModel):
    """Internal service-layer shape — `refresh_token` is the raw token a router must move into
    an HttpOnly cookie (`hrms.core.auth.refresh_cookie`) before responding. Never return this
    model directly from an HTTP route (see `PublicTokenResponseData` below); SEC-06
    (RELEASE_HARDENING_PHASE_3A) — a 30-day refresh token must never appear in a JSON body a
    page's own JavaScript (and therefore an XSS payload) can read."""

    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in_minutes: int
    company_id: UUID
    companies: list[CompanySummary] = Field(default_factory=list)


class PublicTokenResponseData(BaseModel):
    """SEC-06 (RELEASE_HARDENING_PHASE_3A) — the actual HTTP response shape for every
    token-issuing endpoint (login, refresh, registration, invite acceptance): identical to
    `TokenResponseData` minus `refresh_token`, which travels only as an HttpOnly cookie
    (`hrms.core.auth.refresh_cookie.set_refresh_cookie`)."""

    access_token: str
    token_type: str = "Bearer"
    expires_in_minutes: int
    company_id: UUID
    companies: list[CompanySummary] = Field(default_factory=list)


def to_public_token_response(data: TokenResponseData) -> PublicTokenResponseData:
    return PublicTokenResponseData(
        access_token=data.access_token,
        token_type=data.token_type,
        expires_in_minutes=data.expires_in_minutes,
        company_id=data.company_id,
        companies=data.companies,
    )


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
    # Platform console: the company's lifecycle status (`PENDING_APPROVAL`, `TRIAL`, `ACTIVE`,
    # `SUSPENDED`, ...). Clients show a read-only banner for `PENDING_APPROVAL` / `SUSPENDED`.
    company_status: str = "ACTIVE"


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
