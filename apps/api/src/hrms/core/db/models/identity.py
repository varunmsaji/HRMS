from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from hrms.core.db.base import Base, TimestampMixin


class Company(Base, TimestampMixin):
    __tablename__ = "company"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    legal_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    subdomain: Mapped[str | None] = mapped_column(String(63), nullable=True)
    country_code: Mapped[str] = mapped_column(String(2), default="IN")
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    timezone: Mapped[str] = mapped_column(String(50), default="Asia/Kolkata")
    status: Mapped[str] = mapped_column(String(20), default="TRIAL")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class User(Base, TimestampMixin):
    __tablename__ = "user"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
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
