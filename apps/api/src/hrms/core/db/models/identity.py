from datetime import UTC, datetime, time
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    Time,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from hrms.core.db.base import Base, TimestampMixin


def _default_working_days_pattern() -> list[dict[str, Any]]:
    return [
        {"day": "MON", "is_working": True},
        {"day": "TUE", "is_working": True},
        {"day": "WED", "is_working": True},
        {"day": "THU", "is_working": True},
        {"day": "FRI", "is_working": True},
        {"day": "SAT", "is_working": False},
        {"day": "SUN", "is_working": False},
    ]


class Company(Base, TimestampMixin):
    __tablename__ = "company"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    legal_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    subdomain: Mapped[str | None] = mapped_column(String(63), nullable=True)
    industry_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    country_code: Mapped[str] = mapped_column(String(2), default="IN")
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    timezone: Mapped[str] = mapped_column(String(50), default="Asia/Kolkata")
    fy_start_month: Mapped[int] = mapped_column(SmallInteger, default=4)
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    theme_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="TRIAL")
    onboarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    data_region: Mapped[str | None] = mapped_column(String(20), nullable=True)
    registration_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    website: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company_size: Mapped[str | None] = mapped_column(String(20), nullable=True)
    address_line1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    address_state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    address_postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    address_country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    locale_language_code: Mapped[str] = mapped_column(String(10), default="en-IN")
    date_format: Mapped[str] = mapped_column(String(20), default="DD/MM/YYYY")
    working_days_pattern: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=_default_working_days_pattern
    )
    business_hours_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    business_hours_end: Mapped[time | None] = mapped_column(Time, nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class User(Base, TimestampMixin):
    __tablename__ = "user"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # SEC-09 (RELEASE_HARDENING_PHASE_3A) — `NULL` means unverified. Defaults to "verified now"
    # so every existing account-creation path this codebase already has (invite acceptance,
    # direct test/seed fixtures constructing `User(...)`) keeps working unchanged; the one path
    # that deliberately opts OUT of that default is self-service company registration
    # (`organisation/repository.insert_user`'s `email_verified_at=None` override), which is the
    # only flow the original finding was about (an unverified address minting a live tenant).
    # `IdentityService.login` blocks a *subsequent* login while this is `NULL` — the session
    # registration itself issues is unaffected (see `organisation/service.py`).
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=lambda: datetime.now(UTC)
    )
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class UserCompany(Base, TimestampMixin):
    __tablename__ = "user_company"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("company.id"))
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("user.id"))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")


class Role(Base, TimestampMixin):
    __tablename__ = "role"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    code: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(120))
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Permission(Base):
    __tablename__ = "permission"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    code: Mapped[str] = mapped_column(String(100), unique=True)
    domain: Mapped[str] = mapped_column(String(40))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class RolePermission(Base):
    __tablename__ = "role_permission"

    role_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("role.id"), primary_key=True
    )
    permission_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("permission.id"), primary_key=True
    )
    # `SELF`/`REPORTEES`/`REPORTEE_TREE`/`COMPANY` — `docs/architecture/
    # RBAC_DATA_SCOPE_DECISIONS.md` Decision A; `DEFAULT 'COMPANY'` (migration
    # `20260815120000_role_permission_data_scope.py`) preserves every existing grant's behavior.
    data_scope: Mapped[str] = mapped_column(String(20), default="COMPANY")


class UserRole(Base):
    __tablename__ = "user_role"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    user_company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user_company.id")
    )
    role_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("role.id"))


class Session(Base):
    __tablename__ = "session"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("user.id"))
    company_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PasswordResetToken(Base):
    """`docs/modules/employee/41_EMPLOYEE_ACCOUNT_PROVISIONING_LOGIN_AUDIT_AND_PLAN.md` Phase 3 —
    same hash-only-storage, TTL-bound shape as `RefreshToken`/`account_invite`. No RLS, matching
    `refresh_token`'s own precedent: a public, unauthenticated `POST /auth/password/reset` caller
    has no tenant context yet, and `user`/`refresh_token` are the only two tables this table needs
    to join against, neither of which is RLS-protected either."""

    __tablename__ = "password_reset_token"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("user.id"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EmailVerificationToken(Base):
    """SEC-09 (RELEASE_HARDENING_PHASE_3A) — same hash-only-storage, single-use, TTL-bound shape
    as `PasswordResetToken`. No RLS, same reasoning: a public `POST /auth/email/verify` caller
    has no tenant context yet, and `user` is the only table this needs to join against."""

    __tablename__ = "email_verification_token"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("user.id"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RefreshToken(Base):
    __tablename__ = "refresh_token"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("user.id"))
    token_hash: Mapped[str] = mapped_column(Text)
    token_family_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    session_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("session.id"))
    company_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("company.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
