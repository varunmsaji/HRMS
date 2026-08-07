from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.audit.service import AuditService
from hrms.core.auth.jwt import create_access_token
from hrms.core.auth.passwords import verify_password
from hrms.core.auth.tokens import generate_refresh_token, hash_token
from hrms.core.config.settings import Settings, get_settings
from hrms.core.db.repositories.identity import IdentityRepository
from hrms.core.errors.auth import (
    AccountLockedError,
    InvalidCredentialsError,
    InvalidTokenError,
)
from hrms.core.rbac.service import RbacService
from hrms.modules.identity.schemas import (
    CompanyDetail,
    CompanySummary,
    LoginRequest,
    MeResponseData,
    TokenResponseData,
    UserProfile,
)


class IdentityService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._repo = IdentityRepository()
        self._audit = AuditService()
        self._rbac = RbacService(session)

    async def login(
        self,
        body: LoginRequest,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> TokenResponseData:
        user = await self._repo.get_user_by_email(self._session, body.email.lower())
        if user is None or not user.password_hash:
            raise InvalidCredentialsError("Invalid email or password")

        now = datetime.now(UTC)
        if user.locked_until and user.locked_until > now:
            raise AccountLockedError("Account is temporarily locked")

        if not verify_password(user.password_hash, body.password):
            await self._repo.increment_failed_login(self._session, user.id)
            raise InvalidCredentialsError("Invalid email or password")

        await self._repo.reset_failed_login(self._session, user.id)

        memberships = await self._repo.list_user_companies(self._session, user.id)
        if not memberships:
            raise InvalidCredentialsError("Invalid email or password")

        company_summaries: list[CompanySummary] = []
        for m in memberships:
            company = await self._repo.get_company_by_id(self._session, m.company_id)
            if company:
                company_summaries.append(
                    CompanySummary(id=company.id, name=company.name, is_primary=m.is_primary)
                )

        active_company_id = body.company_id
        if active_company_id is None:
            primary = next((m for m in memberships if m.is_primary), memberships[0])
            active_company_id = primary.company_id
        elif not any(m.company_id == active_company_id for m in memberships):
            raise InvalidCredentialsError("Invalid email or password")

        return await self._issue_tokens(
            user_id=user.id,
            company_id=active_company_id,
            companies=company_summaries,
            ip_address=ip_address,
            user_agent=user_agent,
            audit_action="LOGIN",
        )

    async def refresh(self, raw_refresh_token: str) -> TokenResponseData:
        token_hash = hash_token(raw_refresh_token)
        record = await self._repo.get_refresh_by_hash(self._session, token_hash)
        now = datetime.now(UTC)

        if record is None:
            raise InvalidTokenError("Refresh token is invalid")

        if record.revoked_at is not None:
            if record.token_family_id:
                await self._repo.revoke_refresh_family(
                    self._session, record.token_family_id, "REUSE_DETECTED"
                )
            raise InvalidTokenError("Refresh token has been revoked")

        if record.expires_at < now:
            raise InvalidTokenError("Refresh token has expired")

        if record.company_id is None or record.session_id is None:
            raise InvalidTokenError("Refresh token is invalid")

        await self._repo.revoke_refresh_token(self._session, record.id, "ROTATED")

        memberships = await self._repo.list_user_companies(self._session, record.user_id)
        summaries: list[CompanySummary] = []
        for m in memberships:
            company = await self._repo.get_company_by_id(self._session, m.company_id)
            if company:
                summaries.append(
                    CompanySummary(id=company.id, name=company.name, is_primary=m.is_primary)
                )

        return await self._issue_tokens(
            user_id=record.user_id,
            company_id=record.company_id,
            companies=summaries,
            ip_address=None,
            user_agent=None,
            audit_action="TOKEN_REFRESH",
            token_family_id=record.token_family_id,
            existing_session_id=record.session_id,
        )

    async def logout(self, session_id: UUID, user_id: UUID, company_id: UUID) -> None:
        await self._repo.revoke_session(self._session, session_id)
        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=user_id,
            action="LOGOUT",
            entity_type="session",
            entity_id=session_id,
        )

    async def get_me(self, user_id: UUID, company_id: UUID) -> MeResponseData:
        user = await self._repo.get_user_by_id(self._session, user_id)
        if user is None:
            raise InvalidCredentialsError("Invalid email or password")
        permissions = sorted(await self._rbac.get_permission_codes(user_id, company_id))
        return MeResponseData(
            user=UserProfile(
                id=user.id,
                email=user.email,
                company_id=company_id,
                permissions=permissions,
            )
        )

    async def get_company(self, company_id: UUID, viewer_company_id: UUID) -> CompanyDetail:
        if company_id != viewer_company_id:
            from hrms.core.errors.base import NotFoundError

            raise NotFoundError("Resource not found")
        company = await self._repo.get_company_by_id(self._session, company_id)
        if company is None:
            from hrms.core.errors.base import NotFoundError

            raise NotFoundError("Resource not found")
        return CompanyDetail(id=company.id, name=company.name, status=company.status)

    async def _issue_tokens(
        self,
        *,
        user_id: UUID,
        company_id: UUID,
        companies: list[CompanySummary],
        ip_address: str | None,
        user_agent: str | None,
        audit_action: str,
        token_family_id: UUID | None = None,
        existing_session_id: UUID | None = None,
    ) -> TokenResponseData:
        now = datetime.now(UTC)
        session_expires = now + timedelta(days=self._settings.jwt_refresh_ttl_days)
        refresh_expires = session_expires

        if existing_session_id:
            session_id = existing_session_id
        else:
            db_session = await self._repo.create_session(
                self._session,
                user_id=user_id,
                company_id=company_id,
                ip_address=ip_address,
                user_agent=user_agent,
                expires_at=session_expires,
            )
            session_id = db_session.id

        family_id = token_family_id or uuid4()
        raw_refresh = generate_refresh_token()
        await self._repo.create_refresh_token(
            self._session,
            user_id=user_id,
            company_id=company_id,
            session_id=session_id,
            token_family_id=family_id,
            token_hash=hash_token(raw_refresh),
            expires_at=refresh_expires,
        )

        access = create_access_token(
            user_id=user_id,
            company_id=company_id,
            session_id=session_id,
            employee_id=None,
            settings=self._settings,
        )

        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=user_id,
            action=audit_action,
            entity_type="session",
            entity_id=session_id,
            ip=ip_address,
            user_agent=user_agent,
        )

        return TokenResponseData(
            access_token=access,
            refresh_token=raw_refresh,
            expires_in_minutes=self._settings.jwt_access_ttl_minutes,
            company_id=company_id,
            companies=companies,
        )
