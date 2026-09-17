import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.audit.service import AuditService
from hrms.core.auth.jwt import create_access_token
from hrms.core.auth.passwords import hash_password, is_password_strong_enough, verify_password
from hrms.core.auth.tokens import generate_refresh_token, hash_token
from hrms.core.config.settings import Settings, get_settings
from hrms.core.db.repositories.identity import IdentityRepository
from hrms.core.db.session import set_rls_company_id
from hrms.core.errors.auth import (
    AccountLockedError,
    InvalidCredentialsError,
    InvalidTokenError,
)
from hrms.core.errors.base import ValidationError
from hrms.core.rbac.service import RbacService
from hrms.modules.identity.email_templates import build_password_reset_email
from hrms.modules.identity.schemas import (
    CompanyDetail,
    CompanySummary,
    LoginRequest,
    MeResponseData,
    TokenResponseData,
    UserProfile,
)
from hrms.modules.onboarding.email_sender import get_email_sender

#: Matches `account_invite`'s own default — no stated reason for a different window, and a
#: shorter-lived credential (a password reset, vs. a first-time account setup) if anything argues
#: for parity rather than a longer one.
PASSWORD_RESET_TTL_HOURS = 2


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

        memberships = await self._repo.list_user_companies_for_login(self._session, user.id)
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

        # `active_company_id` is now verified (matched against a real membership row above) —
        # set the RLS GUC before issue_tokens_for, which resolves the caller's Employee row
        # (RLS-protected) via _resolve_employee_id. Same GUC-timing shape as the
        # get_tenant_context fix (POSTGRES_RLS_ROLE_MIGRATION_PLAN.md §16), applied here because
        # login has no prior request-scoped tenant context to inherit it from.
        await set_rls_company_id(self._session, str(active_company_id))

        return await self.issue_tokens_for(
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

        memberships = await self._repo.list_user_companies_for_login(self._session, record.user_id)
        summaries: list[CompanySummary] = []
        for m in memberships:
            company = await self._repo.get_company_by_id(self._session, m.company_id)
            if company:
                summaries.append(
                    CompanySummary(id=company.id, name=company.name, is_primary=m.is_primary)
                )

        # record.company_id is already known/verified (from the refresh_token row itself) —
        # set the RLS GUC before issue_tokens_for's Employee lookup, same reasoning as login()
        # above.
        await set_rls_company_id(self._session, str(record.company_id))

        return await self.issue_tokens_for(
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

    async def get_me(
        self, user_id: UUID, company_id: UUID, employee_id: UUID | None
    ) -> MeResponseData:
        user = await self._repo.get_user_by_id(self._session, user_id)
        if user is None:
            raise InvalidCredentialsError("Invalid email or password")
        company = await self._repo.get_company_by_id(self._session, company_id)
        if company is None:
            raise InvalidCredentialsError("Invalid email or password")
        permissions = sorted(await self._rbac.get_permission_codes(user_id, company_id))
        return MeResponseData(
            user=UserProfile(
                id=user.id,
                email=user.email,
                company_id=company_id,
                employee_id=employee_id,
                permissions=permissions,
                company_timezone=company.timezone,
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

    async def _resolve_employee_id(self, *, user_id: UUID, company_id: UUID) -> UUID | None:
        """Local, function-scoped import — same cross-module-seam convention as
        `attendance.service._resolve_visible_employee_ids`. Company admins with no linked
        `Employee` row are valid (`None` is not an error); employees must get their real
        `employee_id` so `SELF` data-scope and self-service routes work from the real JWT."""
        from hrms.modules.employee.service import EmployeeService

        employee_service = EmployeeService(self._session, self._settings)
        return await employee_service.resolve_employee_id_for_user(company_id, user_id)

    async def issue_tokens_for(
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

        employee_id = await self._resolve_employee_id(user_id=user_id, company_id=company_id)

        access = create_access_token(
            user_id=user_id,
            company_id=company_id,
            session_id=session_id,
            employee_id=employee_id,
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

    async def forgot_password(self, email: str) -> None:
        """`POST /auth/password/forgot` (Phase 3, Decision P6) — always returns successfully
        regardless of whether the email matches a real account, to avoid account-existence
        enumeration (the same anti-enumeration posture `login`'s own company-mismatch branch
        already follows). If the email does match an active user, issues a time-boxed reset
        token using the exact hash/TTL shape `AccountInviteService`/`OnboardingTokenService`
        already established, and emails it — best-effort, a delivery failure must not surface to
        the caller (same reasoning as every other best-effort send in this codebase)."""
        user = await self._repo.get_user_by_email(self._session, email.lower())
        if user is None or user.deleted_at is not None or user.status != "ACTIVE":
            return

        now = datetime.now(UTC)
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        await self._repo.create_password_reset_token(
            self._session,
            user_id=user.id,
            token_hash=token_hash,
            expires_at=now + timedelta(hours=PASSWORD_RESET_TTL_HOURS),
        )

        reset_url = f"{self._settings.web_app_base_url}/reset-password/{raw_token}"
        subject, html_body, text_body = build_password_reset_email(
            first_name=user.first_name, reset_url=reset_url
        )
        try:
            await get_email_sender(self._settings).send(
                to=user.email or email, subject=subject, html_body=html_body, text_body=text_body
            )
        except Exception:  # noqa: BLE001 — delivery failure must not fail the request
            pass

        # No `AuditService.record` call here, deliberately: that table's `company_id` is a real
        # tenant FK (and RLS-protected) — a password reset has no company context to attach to
        # (a `User` can belong to several), so there is no correct value to pass. Every other
        # `audit_action` in this module fires only once a `company_id` is genuinely known
        # (`login`/`refresh` resolve one before calling `issue_tokens_for`).

    async def reset_password(self, raw_token: str, new_password: str) -> None:
        """`POST /auth/password/reset` — single-use, TTL-bound, same failure-mode-hiding posture
        as `AccountInviteService.accept`: an invalid/expired/already-used token and a
        never-existed one raise the identical error."""
        if not is_password_strong_enough(new_password):
            raise ValidationError(
                "Password does not meet minimum strength requirements",
                details=[
                    {
                        "field": "password",
                        "code": "WEAK_PASSWORD",
                        "message": "Password must be at least 8 characters and include "
                        "both a letter and a digit",
                    }
                ],
            )

        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        token = await self._repo.get_password_reset_token_by_hash(self._session, token_hash)
        now = datetime.now(UTC)
        if token is None or token.used_at is not None or token.expires_at <= now:
            raise InvalidTokenError("This password reset link is invalid or has expired")

        await self._repo.update_user_password(
            self._session, user_id=token.user_id, password_hash=hash_password(new_password)
        )
        await self._repo.mark_password_reset_token_used(self._session, token, now)
        # No `AuditService.record` call — same reasoning as `forgot_password` above.
