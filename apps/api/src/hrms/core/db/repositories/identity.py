from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.db.models.identity import (
    Company,
    EmailVerificationToken,
    PasswordResetToken,
    RefreshToken,
    Session,
    User,
    UserCompany,
)


@dataclass(frozen=True, slots=True)
class UserCompanyMembership:
    company_id: UUID
    is_primary: bool


class IdentityRepository:
    async def get_user_by_email(self, session: AsyncSession, email: str) -> User | None:
        stmt = select(User).where(User.email == email, User.deleted_at.is_(None))
        return (await session.execute(stmt)).scalar_one_or_none()

    async def get_user_by_id(self, session: AsyncSession, user_id: UUID) -> User | None:
        stmt = select(User).where(User.id == user_id, User.deleted_at.is_(None))
        return (await session.execute(stmt)).scalar_one_or_none()

    async def get_company_by_id(self, session: AsyncSession, company_id: UUID) -> Company | None:
        stmt = select(Company).where(Company.id == company_id, Company.deleted_at.is_(None))
        return (await session.execute(stmt)).scalar_one_or_none()

    async def list_user_companies_for_login(
        self, session: AsyncSession, user_id: UUID
    ) -> list[UserCompanyMembership]:
        """Login/token-refresh only. Resolves a user's active company memberships *before* any
        tenant context (and therefore the `app.company_id` RLS GUC) exists, by routing through the
        `login_lookup_user_companies` SECURITY DEFINER function (migration 20260828090000) instead
        of querying `user_company` directly — that table's `tenant_isolation` policy would
        otherwise hide every row under the app's runtime role (`hrms_app`, which has no RLS bypass
        by design; see docs/architecture/POSTGRES_RLS_ROLE_MIGRATION_PLAN.md). Do not use this for
        an already tenant-scoped read — `get_user_company` below already covers that case
        correctly under RLS."""
        stmt = text("SELECT company_id, is_primary FROM login_lookup_user_companies(:user_id)")
        rows = (await session.execute(stmt, {"user_id": str(user_id)})).all()
        return [
            UserCompanyMembership(company_id=row.company_id, is_primary=row.is_primary)
            for row in rows
        ]

    async def get_user_company(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        company_id: UUID,
    ) -> UserCompany | None:
        stmt = select(UserCompany).where(
            UserCompany.user_id == user_id,
            UserCompany.company_id == company_id,
            UserCompany.status == "ACTIVE",
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def get_session_by_id(self, session: AsyncSession, session_id: UUID) -> Session | None:
        stmt = select(Session).where(Session.id == session_id)
        return (await session.execute(stmt)).scalar_one_or_none()

    async def create_session(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        company_id: UUID,
        ip_address: str | None,
        user_agent: str | None,
        expires_at: datetime,
    ) -> Session:
        row = Session(
            id=uuid4(),
            user_id=user_id,
            company_id=company_id,
            ip_address=ip_address,
            user_agent=user_agent,
            expires_at=expires_at,
        )
        session.add(row)
        await session.flush()
        return row

    async def revoke_session(self, session: AsyncSession, session_id: UUID) -> None:
        await session.execute(
            update(Session).where(Session.id == session_id).values(revoked_at=datetime.now(UTC))
        )

    async def create_refresh_token(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        company_id: UUID,
        session_id: UUID,
        token_family_id: UUID,
        token_hash: str,
        expires_at: datetime,
    ) -> RefreshToken:
        row = RefreshToken(
            id=uuid4(),
            user_id=user_id,
            company_id=company_id,
            session_id=session_id,
            token_family_id=token_family_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        session.add(row)
        await session.flush()
        return row

    async def get_refresh_by_hash(
        self, session: AsyncSession, token_hash: str
    ) -> RefreshToken | None:
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        return (await session.execute(stmt)).scalar_one_or_none()

    async def revoke_refresh_token(
        self,
        session: AsyncSession,
        token_id: UUID,
        reason: str,
    ) -> None:
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.id == token_id)
            .values(revoked_at=datetime.now(UTC), revoked_reason=reason)
        )

    async def revoke_refresh_family(
        self,
        session: AsyncSession,
        token_family_id: UUID,
        reason: str,
    ) -> None:
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.token_family_id == token_family_id)
            .values(revoked_at=datetime.now(UTC), revoked_reason=reason)
        )
        await session.execute(
            update(Session)
            .where(
                Session.id.in_(
                    select(RefreshToken.session_id).where(
                        RefreshToken.token_family_id == token_family_id
                    )
                )
            )
            .values(revoked_at=datetime.now(UTC))
        )

    async def revoke_all_sessions_for_user(
        self,
        session: AsyncSession,
        user_id: UUID,
        reason: str,
    ) -> None:
        """SEC-07 — every live `Session`/`RefreshToken` belonging to `user_id`, across every
        company and device, not just the family the caller happens to hold. `get_current_user`
        (`core/auth/dependencies.py`) re-checks `Session.revoked_at` on every request, so this
        takes effect immediately for already-issued access tokens too, not only on their next
        refresh — no separate access-token blocklist is needed."""
        now = datetime.now(UTC)
        await session.execute(
            update(Session)
            .where(Session.user_id == user_id, Session.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now, revoked_reason=reason)
        )

    async def create_password_reset_token(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        token_hash: str,
        expires_at: datetime,
    ) -> PasswordResetToken:
        row = PasswordResetToken(
            id=uuid4(), user_id=user_id, token_hash=token_hash, expires_at=expires_at
        )
        session.add(row)
        await session.flush()
        return row

    async def get_password_reset_token_by_hash(
        self, session: AsyncSession, token_hash: str
    ) -> PasswordResetToken | None:
        stmt = select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
        return (await session.execute(stmt)).scalar_one_or_none()

    async def mark_password_reset_token_used(
        self, session: AsyncSession, token: PasswordResetToken, now: datetime
    ) -> None:
        token.used_at = now
        await session.flush()

    async def update_user_password(
        self, session: AsyncSession, *, user_id: UUID, password_hash: str
    ) -> None:
        await session.execute(
            update(User)
            .where(User.id == user_id)
            .values(password_hash=password_hash, failed_login_count=0, locked_until=None)
        )

    async def create_email_verification_token(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        token_hash: str,
        expires_at: datetime,
    ) -> EmailVerificationToken:
        row = EmailVerificationToken(
            id=uuid4(), user_id=user_id, token_hash=token_hash, expires_at=expires_at
        )
        session.add(row)
        await session.flush()
        return row

    async def get_email_verification_token_by_hash(
        self, session: AsyncSession, token_hash: str
    ) -> EmailVerificationToken | None:
        stmt = select(EmailVerificationToken).where(EmailVerificationToken.token_hash == token_hash)
        return (await session.execute(stmt)).scalar_one_or_none()

    async def mark_email_verification_token_used(
        self, session: AsyncSession, token: EmailVerificationToken, now: datetime
    ) -> None:
        token.used_at = now
        await session.flush()

    async def mark_user_email_verified(
        self, session: AsyncSession, user_id: UUID, now: datetime
    ) -> None:
        await session.execute(update(User).where(User.id == user_id).values(email_verified_at=now))

    async def increment_failed_login(self, session: AsyncSession, user_id: UUID) -> User:
        user = await self.get_user_by_id(session, user_id)
        if user is None:
            raise ValueError("user missing")
        user.failed_login_count += 1
        if user.failed_login_count >= 5:
            user.locked_until = datetime.now(UTC) + timedelta(minutes=15)
        await session.flush()
        return user

    async def reset_failed_login(self, session: AsyncSession, user_id: UUID) -> None:
        await session.execute(
            update(User).where(User.id == user_id).values(failed_login_count=0, locked_until=None)
        )
