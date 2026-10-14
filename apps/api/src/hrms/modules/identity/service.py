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
    EmailNotVerifiedError,
    InvalidCredentialsError,
    InvalidTokenError,
)
from hrms.core.errors.base import ValidationError
from hrms.core.observability.logging import get_logger, safe_log
from hrms.core.rbac.service import RbacService
from hrms.modules.identity.email_templates import (
    build_email_verification_email,
    build_password_reset_email,
)
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

#: SEC-09 — longer than the password-reset window: verifying an address is lower-stakes than
#: recovering account access, and a registrant may reasonably check their inbox a day later.
EMAIL_VERIFICATION_TTL_HOURS = 24

_logger = get_logger(__name__)


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
            # `get_session` rolls the request transaction back on any exception, which would
            # silently discard this increment and make lockout impossible — persist it first.
            await self._session.commit()
            raise InvalidCredentialsError("Invalid email or password")

        await self._repo.reset_failed_login(self._session, user.id)

        # Suspended/deactivated accounts get the same answer as a wrong password — the status
        # is not disclosed, and (like the email-verified check below) only after the password is
        # confirmed so it cannot act as an account-existence oracle.
        if user.status != "ACTIVE":
            raise InvalidCredentialsError("Invalid email or password")

        # SEC-09 (RELEASE_HARDENING_PHASE_3A) — checked only after the password itself is
        # confirmed correct, so this never doubles as an account-existence oracle (an attacker
        # who doesn't know the password gets the identical INVALID_CREDENTIALS response either
        # way). Deliberately does not block the *first* session — registration/invite-acceptance
        # both issue tokens via `issue_tokens_for` directly, never through this method — only a
        # subsequent login attempt.
        if user.email_verified_at is None:
            raise EmailNotVerifiedError("Please verify your email address before signing in")

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
            await self._revoke_family_on_reuse(record.token_family_id, record.user_id)
            raise InvalidTokenError("Refresh token has been revoked")

        if record.expires_at < now:
            raise InvalidTokenError("Refresh token has expired")

        if record.company_id is None or record.session_id is None:
            raise InvalidTokenError("Refresh token is invalid")

        # A refresh token is only as good as the session, account and membership behind it —
        # re-check all three, exactly as `get_current_user` does for an access token, so logout,
        # deactivation and membership removal end the refresh chain too.
        db_session = await self._repo.get_session_by_id(self._session, record.session_id)
        if db_session is None or db_session.revoked_at is not None:
            raise InvalidTokenError("Session is no longer valid")
        user = await self._repo.get_user_by_id(self._session, record.user_id)
        if user is None or user.status != "ACTIVE":
            raise InvalidTokenError("User is not active")
        memberships = await self._repo.list_user_companies_for_login(self._session, record.user_id)
        if not any(m.company_id == record.company_id for m in memberships):
            raise InvalidTokenError("Company membership is not valid")

        if not await self._repo.rotate_refresh_token(self._session, record.id):
            # Another request rotated (or revoked) this token between our read and this write —
            # the same token presented twice, i.e. reuse.
            await self._revoke_family_on_reuse(record.token_family_id, record.user_id)
            raise InvalidTokenError("Refresh token has been revoked")
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

    async def _revoke_family_on_reuse(self, token_family_id: UUID | None, user_id: UUID) -> None:
        """Reuse of an already-rotated refresh token means the chain may be stolen: revoke every
        token in the family and the session(s) behind it, so the newest refresh token *and* every
        access token minted for that session stop working (`get_current_user` checks the session).

        The caller raises `InvalidTokenError` right after this, and `get_session` rolls the request
        transaction back on any exception — which would silently undo the revocation. So it is
        committed here, before the raise (the same reason `login` commits its failed-attempt
        counter). Both callers reach this before the request has written anything else, so the
        commit persists only the revocation. If the commit itself fails, the database error
        propagates (a 500, logged) instead of a 401 that would imply the family was revoked."""
        if token_family_id is not None:
            await self._repo.revoke_refresh_family(self._session, token_family_id, "REUSE_DETECTED")
        await self._session.commit()
        safe_log(
            _logger.warning,
            "security.refresh_token_reuse_detected",
            user_id=str(user_id),
            token_family_id=str(token_family_id) if token_family_id else None,
            family_revoked=token_family_id is not None,
        )

    async def logout(self, session_id: UUID, user_id: UUID, company_id: UUID) -> None:
        await self._repo.revoke_session(self._session, session_id)
        await self._repo.revoke_refresh_tokens_for_session(self._session, session_id, "LOGOUT")
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
        never-existed one raise the identical error.

        SEC-07 — a password reset also revokes every existing `Session`/`RefreshToken` for this
        user (every company, every device), not just the browser that performed the reset. If an
        attacker's session prompted the reset (stolen credential, XSS-exfiltrated refresh token),
        the new password alone would otherwise do nothing to end it — the access token stays
        valid until its own short expiry, and the refresh token would keep minting new ones
        indefinitely. `revoke_all_sessions_for_user` reuses the exact mechanism `get_current_user`
        already re-checks on every request (`Session.revoked_at`), so this takes effect
        immediately, not just on the next refresh attempt."""
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
        await self._repo.revoke_all_sessions_for_user(
            self._session, token.user_id, reason="PASSWORD_RESET"
        )
        await self._repo.mark_password_reset_token_used(self._session, token, now)
        # No `AuditService.record` call — same reasoning as `forgot_password` above.

    async def send_verification_email(
        self, *, user_id: UUID, email: str, first_name: str | None
    ) -> None:
        """SEC-09 — issues a fresh, single-use, TTL-bound token and emails it via the same
        `EmailSender` abstraction `forgot_password` already uses. Called from
        `organisation.service.register_company` right after the new admin `User` row is created;
        best-effort by the same convention every other send in this codebase follows — a delivery
        failure must not fail the registration request itself (the account still exists, and
        `resend_verification_email` below lets the user retry)."""
        now = datetime.now(UTC)
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        await self._repo.create_email_verification_token(
            self._session,
            user_id=user_id,
            token_hash=token_hash,
            expires_at=now + timedelta(hours=EMAIL_VERIFICATION_TTL_HOURS),
        )

        verify_url = f"{self._settings.web_app_base_url}/verify-email/{raw_token}"
        subject, html_body, text_body = build_email_verification_email(
            first_name=first_name, verify_url=verify_url
        )
        try:
            await get_email_sender(self._settings).send(
                to=email, subject=subject, html_body=html_body, text_body=text_body
            )
        except Exception:  # noqa: BLE001 — delivery failure must not fail the caller
            pass

    async def verify_email(self, raw_token: str) -> None:
        """`POST /auth/email/verify` — single-use, TTL-bound, same failure-mode-hiding posture as
        `reset_password`: an invalid/expired/already-used token and a never-existed one raise the
        identical error, so this endpoint cannot be used to probe for valid tokens."""
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        token = await self._repo.get_email_verification_token_by_hash(self._session, token_hash)
        now = datetime.now(UTC)
        if token is None or token.used_at is not None or token.expires_at <= now:
            raise InvalidTokenError("This verification link is invalid or has expired")

        await self._repo.mark_user_email_verified(self._session, token.user_id, now)
        await self._repo.mark_email_verification_token_used(self._session, token, now)

    async def resend_verification_email(self, email: str) -> None:
        """`POST /auth/email/resend-verification` — always returns successfully regardless of
        whether the email matches a real, still-unverified account, matching `forgot_password`'s
        own anti-enumeration posture."""
        user = await self._repo.get_user_by_email(self._session, email.lower())
        if (
            user is None
            or user.deleted_at is not None
            or user.status != "ACTIVE"
            or user.email_verified_at is not None
        ):
            return
        await self.send_verification_email(
            user_id=user.id, email=user.email or email, first_name=user.first_name
        )
