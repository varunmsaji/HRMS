"""ORM model for the account-invite module (`docs/modules/employee/
41_EMPLOYEE_ACCOUNT_PROVISIONING_LOGIN_AUDIT_AND_PLAN.md` Phase 2) — the mechanism that finally
lets an `Employee` (or a second admin/HR user) get a real login `User`.

Deliberately generalized as `AccountInvite`, not `EmployeeInvite` — the same table and service
serve both `POST /employees/{id}/invite` (an existing Employee gets a login) and
`POST /users/invite` (a brand-new user with no Employee record at all, e.g. a second
COMPANY_ADMIN/HR_ADMIN) — `employee_id` is simply `NULL` for the latter.

Shape is a direct copy of `hrms.modules.onboarding.models.OnboardingToken` — that table already
solved the exact same problem (a public, unauthenticated caller needs to resolve a secure link
before any tenant context exists) and is production-proven. Same reasoning applies here: **no RLS
policy** (see this table's own migration for why — mirrors the corrective migration onboarding_token
needed, applied up front here instead of as a follow-up fix)."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from hrms.core.db.base import Base, TimestampMixin


class AccountInvite(Base, TimestampMixin):
    """`token_hash` is a SHA-256 hex digest — the raw token is never persisted, identical to
    `OnboardingToken.token_hash`'s own convention. Only one live (non-revoked, non-expired,
    non-accepted) row per `(employee_id)` or `(email)` target is ever meant to exist at a time;
    issuing a new one revokes the previous live row (service layer, not a DB constraint) — same
    convention as onboarding's `revoke_live_tokens_for_case`."""

    __tablename__ = "account_invite"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company.id"), index=True
    )
    email: Mapped[str] = mapped_column(String(255), index=True)
    employee_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employee.id"), nullable=True
    )
    role_code: Mapped[str] = mapped_column(String(60))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_by_user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("user.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
