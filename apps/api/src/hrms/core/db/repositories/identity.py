from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.db.models.identity import (
    Company,
    RefreshToken,
    Session,
    User,
    UserCompany,
)


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

    async def list_user_companies(self, session: AsyncSession, user_id: UUID) -> list[UserCompany]:
        stmt = select(UserCompany).where(
            UserCompany.user_id == user_id,
            UserCompany.status == "ACTIVE",
        )
        return list((await session.execute(stmt)).scalars().all())

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
            update(Session)
            .where(Session.id == session_id)
            .values(revoked_at=datetime.now(UTC))
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
            update(User)
            .where(User.id == user_id)
            .values(failed_login_count=0, locked_until=None)
        )
