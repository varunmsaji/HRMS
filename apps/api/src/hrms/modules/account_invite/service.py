"""Business logic for the account-invite module — `docs/modules/employee/
41_EMPLOYEE_ACCOUNT_PROVISIONING_LOGIN_AUDIT_AND_PLAN.md` Phase 2. Token issue/resolve/accept
directly mirrors `hrms.modules.onboarding.service.OnboardingTokenService` (hash-only storage,
revoke-prior-on-reissue, same-error-for-every-failure-mode), reused rather than reinvented — see
that module's own service for the reference shape this was copied from."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.audit.service import AuditService
from hrms.core.auth.passwords import hash_password, is_password_strong_enough, verify_password
from hrms.core.config.settings import Settings, get_settings
from hrms.core.db.repositories.identity import IdentityRepository
from hrms.core.db.session import set_rls_company_id
from hrms.core.errors.auth import AccountLockedError, InvalidCredentialsError
from hrms.core.errors.base import NotFoundError, ValidationError
from hrms.modules.account_invite.email_templates import build_account_invite_email
from hrms.modules.account_invite.exceptions import (
    AccountInviteInvalidError,
    EmployeeAlreadyHasAccountError,
    EmployeeMissingEmailError,
    InvalidRoleCodeError,
    SelfRoleChangeNotAllowedError,
    UserAlreadyInCompanyError,
)
from hrms.modules.account_invite.models import AccountInvite
from hrms.modules.account_invite.repository import AccountInviteRepository
from hrms.modules.account_invite.schemas import (
    AccountInviteRead,
    PublicAccountInviteRead,
    RoleAssignmentRequest,
    UserInviteRequest,
    UserSummary,
)
from hrms.modules.identity.schemas import CompanySummary, TokenResponseData
from hrms.modules.identity.service import IdentityService
from hrms.modules.onboarding.email_sender import get_email_sender

#: Matches onboarding's own `DEFAULT_TOKEN_TTL_DAYS` — no stated reason for a different window.
DEFAULT_INVITE_TTL_DAYS = 7

#: The default roles `docs/architecture/RBAC_DATA_SCOPE_DECISIONS.md` Decision H (plus its
#: 2026-09-23/24 Addendum for `BRANCH_MANAGER`) locks. Deliberately not a role-authoring surface —
#: assignment among exactly these five, nothing else (Decision P5).
ASSIGNABLE_ROLE_CODES = (
    "COMPANY_ADMIN",
    "HR_ADMIN",
    "REPORTING_MANAGER",
    "BRANCH_MANAGER",
    "EMPLOYEE",
)


class AccountInviteService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._repo = AccountInviteRepository()
        self._identity_repo = IdentityRepository()
        self._audit = AuditService()

    async def issue_for_employee(
        self,
        company_id: UUID,
        employee_id: UUID,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AccountInviteRead:
        """`POST /employees/{id}/invite` — path 2 of Decision P2: on-demand invite for an
        employee who already exists (created before this feature shipped, or via manual entry /
        CSV import, neither of which ever creates a login)."""
        from hrms.modules.employee.repository import EmployeeRepository
        from hrms.modules.organisation.service import EMPLOYEE_ROLE_CODE

        employee = await EmployeeRepository().get_employee(
            self._session, company_id=company_id, employee_id=employee_id
        )
        if employee is None:
            raise NotFoundError("Resource not found")
        if employee.user_id is not None:
            raise EmployeeAlreadyHasAccountError()
        if not employee.personal_email:
            raise EmployeeMissingEmailError()

        return await self._issue(
            company_id,
            email=employee.personal_email.lower(),
            employee_id=employee.id,
            role_code=EMPLOYEE_ROLE_CODE,
            first_name=employee.first_name,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def issue_for_user(
        self,
        company_id: UUID,
        body: UserInviteRequest,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AccountInviteRead:
        """`POST /users/invite` (Decision P5's other funnel) — a second admin/HR user, with no
        `Employee` record required at all."""
        return await self._issue(
            company_id,
            email=body.email.lower(),
            employee_id=None,
            role_code=body.role_code,
            first_name=None,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def _issue(
        self,
        company_id: UUID,
        *,
        email: str,
        employee_id: UUID | None,
        role_code: str,
        first_name: str | None,
        actor_user_id: UUID | None,
        ip_address: str | None,
        user_agent: str | None,
    ) -> AccountInviteRead:
        if role_code not in ASSIGNABLE_ROLE_CODES:
            raise InvalidRoleCodeError(role_code)
        role = await self._repo.get_role_by_code(
            self._session, company_id=company_id, code=role_code
        )
        if role is None:
            # Shouldn't happen for a company registered after Phase 1, or backfilled by
            # `20260920090000_default_roles_backfill.py` — surfaced as the same client-facing
            # shape as any other bad role code rather than a 500, in case a role was deleted.
            raise InvalidRoleCodeError(role_code)

        now = datetime.now(UTC)
        if employee_id is not None:
            await self._repo.revoke_live_invites_for_employee(
                self._session, employee_id=employee_id, now=now
            )
        else:
            await self._repo.revoke_live_invites_for_email(
                self._session, company_id=company_id, email=email, now=now
            )

        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        expires_at = now + timedelta(days=DEFAULT_INVITE_TTL_DAYS)
        invite = await self._repo.insert_invite(
            self._session,
            data={
                "id": uuid4(),
                "company_id": company_id,
                "email": email,
                "employee_id": employee_id,
                "role_code": role_code,
                "token_hash": token_hash,
                "created_by_user_id": actor_user_id,
                "expires_at": expires_at,
                "created_at": now,
                "updated_at": now,
            },
        )

        invite_url = f"{self._settings.web_app_base_url}/accept-invite/{raw_token}"

        # Cross-module read only, same lazy-import convention as `onboarding.send_invite`.
        from hrms.modules.organisation.service import OrganisationService

        organisation = OrganisationService(self._session, self._settings)
        company = await organisation.get_company_profile(company_id)

        subject, html_body, text_body = build_account_invite_email(
            first_name=first_name, company_name=company.name, invite_url=invite_url
        )
        email_sent = True
        try:
            await get_email_sender(self._settings).send(
                to=email, subject=subject, html_body=html_body, text_body=text_body
            )
        except Exception:  # noqa: BLE001 — delivery failure must not fail the request
            email_sent = False

        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="ACCOUNT_INVITE_ISSUED",
            entity_type="account_invite",
            entity_id=invite.id,
            ip=ip_address,
            user_agent=user_agent,
        )

        return AccountInviteRead(
            id=invite.id,
            email=email,
            role_code=role_code,
            expires_at=expires_at,
            invite_url=invite_url,
            email_sent=email_sent,
        )

    async def resolve(self, raw_token: str) -> PublicAccountInviteRead:
        """`GET /public/account-invites/{token}` — shown before the accept form. Deliberately
        raises the same `AccountInviteInvalidError` (404) for every failure mode, identical
        reasoning to `OnboardingTokenService.resolve_and_touch`."""
        invite = await self._get_live_invite(raw_token)
        await set_rls_company_id(self._session, str(invite.company_id))
        company = await self._identity_repo.get_company_by_id(self._session, invite.company_id)
        if company is None:
            raise AccountInviteInvalidError()
        existing_user = await self._identity_repo.get_user_by_email(self._session, invite.email)
        return PublicAccountInviteRead(
            email=invite.email,
            company_name=company.name,
            expires_at=invite.expires_at,
            existing_account=existing_user is not None,
        )

    async def accept(
        self,
        raw_token: str,
        password: str,
        *,
        first_name: str | None,
        last_name: str | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> TokenResponseData:
        """`POST /public/account-invites/{token}/accept` — creates or reuses the `User` (P3:
        `user.email` carries a real global unique index, so there is at most one candidate row to
        reuse), links `Employee.user_id` when the invite was for an existing employee, grants the
        invite's role, marks the invite accepted, and logs the new session in immediately (same
        `issue_tokens_for` seam `register_company`/`login` already use).

        SEC-08 — an invite must never authenticate an existing account by itself: possession of
        the invite link proves only that the inviter's email delivery reached that address, not
        that the caller controls the existing account. When `invite.email` already has a `User`
        row, `password` is verified against that account's real hash (the identical
        `verify_password`/lockout mechanism `IdentityService.login` uses, reused rather than
        reinvented) before any membership or session is granted; a mismatch raises the same
        `InvalidCredentialsError`/`AccountLockedError` login itself would, and leaves the invite
        unconsumed (`mark_accepted` never runs) so a legitimate holder can retry. The password-
        strength check only applies to the brand-new-account path — for an existing account,
        `password` is a login credential being verified, not a new one being chosen."""
        invite = await self._get_live_invite(raw_token)
        await set_rls_company_id(self._session, str(invite.company_id))

        role = await self._repo.get_role_by_code(
            self._session, company_id=invite.company_id, code=invite.role_code
        )
        if role is None:
            raise AccountInviteInvalidError()

        # Cross-module reuse of `OrganisationRepository`'s own `User`/`UserCompany`/`UserRole`
        # writers — same precedent as `organisation/service.py:register_company`, which is the
        # only other place these rows are created.
        from hrms.modules.organisation.repository import OrganisationRepository

        org_repo = OrganisationRepository()
        now = datetime.now(UTC)

        existing_user = await self._identity_repo.get_user_by_email(self._session, invite.email)
        if existing_user is not None:
            if existing_user.locked_until and existing_user.locked_until > now:
                raise AccountLockedError("Account is temporarily locked")
            if not existing_user.password_hash or not verify_password(
                existing_user.password_hash, password
            ):
                await self._identity_repo.increment_failed_login(self._session, existing_user.id)
                raise InvalidCredentialsError("Invalid email or password")
            await self._identity_repo.reset_failed_login(self._session, existing_user.id)

            existing_membership = await self._identity_repo.get_user_company(
                self._session, user_id=existing_user.id, company_id=invite.company_id
            )
            if existing_membership is not None:
                raise UserAlreadyInCompanyError()
            user_id = existing_user.id
            user_company = await org_repo.insert_user_company(
                self._session,
                user_id=user_id,
                company_id=invite.company_id,
                is_primary=False,
                now=now,
            )
        else:
            if not is_password_strong_enough(password):
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
            user_id = uuid4()
            await org_repo.insert_user(
                self._session,
                user_id=user_id,
                email=invite.email,
                password_hash=hash_password(password),
                first_name=first_name or "",
                last_name=last_name or "",
                now=now,
                # SEC-09 — accepting a token delivered to `invite.email` is itself proof of
                # receipt, unlike self-service registration (this method's other, unverified
                # branch is `insert_user`'s own default — see that method's docstring).
                email_verified_at=now,
            )
            user_company = await org_repo.insert_user_company(
                self._session,
                user_id=user_id,
                company_id=invite.company_id,
                is_primary=True,
                now=now,
            )

        await org_repo.insert_user_role(
            self._session, user_company_id=user_company.id, role_id=role.id
        )

        if invite.employee_id is not None:
            from hrms.modules.employee.repository import EmployeeRepository

            await EmployeeRepository().link_user(
                self._session,
                company_id=invite.company_id,
                employee_id=invite.employee_id,
                user_id=user_id,
            )

        await self._repo.mark_accepted(self._session, invite=invite, now=now)

        await self._audit.record(
            self._session,
            company_id=invite.company_id,
            actor_user_id=user_id,
            action="ACCOUNT_INVITE_ACCEPTED",
            entity_type="account_invite",
            entity_id=invite.id,
            ip=ip_address,
            user_agent=user_agent,
        )

        # Same membership-gathering shape as `IdentityService.login` — correct regardless of
        # whether this was a brand-new `User` (one membership) or a reused one (N memberships).
        memberships = await self._identity_repo.list_user_companies_for_login(
            self._session, user_id
        )
        companies: list[CompanySummary] = []
        for m in memberships:
            company = await self._identity_repo.get_company_by_id(self._session, m.company_id)
            if company:
                companies.append(
                    CompanySummary(id=company.id, name=company.name, is_primary=m.is_primary)
                )

        identity = IdentityService(self._session, self._settings)
        return await identity.issue_tokens_for(
            user_id=user_id,
            company_id=invite.company_id,
            companies=companies,
            ip_address=ip_address,
            user_agent=user_agent,
            audit_action="ACCOUNT_INVITE_LOGIN",
        )

    async def _get_live_invite(self, raw_token: str) -> AccountInvite:
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        invite = await self._repo.get_by_hash(self._session, token_hash=token_hash)
        if invite is None:
            raise AccountInviteInvalidError()
        now = datetime.now(UTC)
        if (
            invite.revoked_at is not None
            or invite.accepted_at is not None
            or invite.expires_at <= now
        ):
            raise AccountInviteInvalidError()
        return invite

    async def list_users(self, company_id: UUID) -> list[UserSummary]:
        """`GET /users` — backs the minimal Settings > Users screen (Phase 4). Deliberately
        N+1 (one role-lookup query per membership) rather than a join — this is a small,
        unpaginated, admin-only list, and the join would need a `GROUP BY`/`array_agg` for no
        real benefit at this scale."""
        rows = await self._repo.list_user_companies_for_company(
            self._session, company_id=company_id
        )
        summaries = []
        for user_company, user in rows:
            role_codes = await self._repo.list_role_codes_for_user_company(
                self._session, user_company_id=user_company.id
            )
            summaries.append(
                UserSummary(
                    user_id=user.id,
                    email=user.email,
                    first_name=user.first_name,
                    last_name=user.last_name,
                    is_primary=user_company.is_primary,
                    status=user_company.status,
                    role_codes=sorted(role_codes),
                )
            )
        return summaries

    async def assign_roles(
        self,
        company_id: UUID,
        target_user_id: UUID,
        body: RoleAssignmentRequest,
        *,
        actor_user_id: UUID | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> list[str]:
        """`PATCH /users/{user_id}/roles` (Decision P5) — full replace among the four fixed role
        codes. Blocks changing your own role assignment entirely (see
        `SelfRoleChangeNotAllowedError` for why this, not a narrower "last admin" check, is this
        phase's guard)."""
        if target_user_id == actor_user_id:
            raise SelfRoleChangeNotAllowedError()

        for code in body.role_codes:
            if code not in ASSIGNABLE_ROLE_CODES:
                raise InvalidRoleCodeError(code)

        membership = await self._identity_repo.get_user_company(
            self._session, user_id=target_user_id, company_id=company_id
        )
        if membership is None:
            raise NotFoundError("Resource not found")

        role_ids: list[UUID] = []
        for code in body.role_codes:
            role = await self._repo.get_role_by_code(
                self._session, company_id=company_id, code=code
            )
            if role is None:
                raise InvalidRoleCodeError(code)
            role_ids.append(role.id)

        await self._repo.replace_user_roles(
            self._session, user_company_id=membership.id, role_ids=role_ids
        )

        await self._audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            action="USER_ROLES_ASSIGNED",
            entity_type="user_company",
            entity_id=membership.id,
            after={"role_codes": body.role_codes},
            ip=ip_address,
            user_agent=user_agent,
        )

        return body.role_codes
