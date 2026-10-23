"""Platform console: platform-admin sign-in and company lifecycle management.

Every state change is (1) a compare-and-set on `company.status` (a concurrent change makes it a
409, never a silent overwrite), (2) recorded in the append-only `platform_audit_log` and in the
company's own `audit_log`, and (3) committed *before* the best-effort notification email is sent,
so an email is never sent for a change that rolled back."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.audit.service import AuditService
from hrms.core.auth.passwords import (
    hash_password,
    is_password_strong_enough,
    verify_password,
)
from hrms.core.config.settings import Settings, get_settings
from hrms.core.db.models.identity import Company, User
from hrms.core.db.session import set_rls_company_id
from hrms.core.errors.auth import InvalidCredentialsError
from hrms.core.observability.logging import get_logger, safe_log
from hrms.core.observability.security_events import security_event
from hrms.core.tenancy.context import current_request_id
from hrms.modules.onboarding.email_sender import get_email_sender, log_email_failure
from hrms.modules.organisation.service import TRIAL_PERIOD_DAYS
from hrms.modules.platform.email_templates import build_status_email
from hrms.modules.platform.exceptions import (
    AdminAlreadyVerifiedError,
    CannotRemoveLastAdminError,
    CompanyNotFoundError,
    ConfirmationMismatchError,
    InvalidCompanyTransitionError,
    NoSubscriptionError,
    PlanNotFoundError,
    PlatformAdminLockedError,
    PlatformAdminNotFoundError,
    PlatformUsernameTakenError,
    WeakPlatformPasswordError,
)
from hrms.modules.platform.repository import PlatformRepository
from hrms.modules.platform.schemas import (
    CompanyDetail,
    CompanyListItem,
    DashboardData,
    DayCount,
    PlanItem,
    PlatformAdminItem,
    PlatformAuditEntry,
    PlatformLoginRequest,
    PlatformTokenData,
    SubscriptionInfo,
    SubscriptionPatch,
    UsageInfo,
)
from hrms.modules.platform.security import PlatformPrincipal, create_platform_token

_logger = get_logger(__name__)

MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 15


@dataclass(frozen=True)
class RequestInfo:
    ip: str | None = None
    user_agent: str | None = None


#: action -> (allowed current statuses, resulting status). `reactivate` resolves its target below.
_TRANSITIONS: dict[str, tuple[tuple[str, ...], str]] = {
    "approve": (("PENDING_APPROVAL", "REJECTED"), "TRIAL"),
    "reject": (("PENDING_APPROVAL",), "REJECTED"),
    "suspend": (("TRIAL", "ACTIVE"), "SUSPENDED"),
    "reactivate": (("SUSPENDED",), "ACTIVE"),
    "terminate": (("PENDING_APPROVAL", "REJECTED", "TRIAL", "ACTIVE", "SUSPENDED"), "TERMINATED"),
}
_EVENT = {
    "approve": "approved",
    "reject": "rejected",
    "suspend": "suspended",
    "reactivate": "reactivated",
    "terminate": "terminated",
}


def _admin_name(user: User | None) -> str | None:
    if user is None:
        return None
    name = " ".join(p for p in (user.first_name, user.last_name) if p)
    return name or None


def _list_item(company: Company, admin: User | None) -> CompanyListItem:
    return CompanyListItem(
        id=company.id,
        name=company.name,
        status=company.status,  # type: ignore[arg-type]
        industry_code=company.industry_code,
        company_size=company.company_size,
        created_at=company.created_at,
        trial_ends_at=company.trial_ends_at,
        admin_email=admin.email if admin else None,
        admin_name=_admin_name(admin),
    )


class PlatformService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._repo = PlatformRepository()
        self._tenant_audit = AuditService()

    # ---- auth ----------------------------------------------------------------------------
    async def login(self, body: PlatformLoginRequest, info: RequestInfo) -> PlatformTokenData:
        admin = await self._repo.get_admin_by_username(self._session, body.username)
        now = datetime.now(UTC)
        if admin is None or admin.status != "ACTIVE":
            self._login_failed("unknown_or_disabled", info)
            raise InvalidCredentialsError("Invalid username or password")
        if admin.locked_until and admin.locked_until > now:
            self._login_failed("locked", info, admin_id=admin.id)
            raise PlatformAdminLockedError()
        if not verify_password(admin.password_hash, body.password):
            updated = await self._repo.record_failed_login(
                self._session, admin.id, max_attempts=MAX_FAILED_LOGINS, lock_minutes=LOCK_MINUTES
            )
            await self._session.commit()  # `get_session` rolls back on the raise below
            self._login_failed("bad_password", info, admin_id=admin.id)
            if updated.locked_until and updated.locked_until > now:
                security_event("platform.account_locked", level="warning", admin_id=str(admin.id))
            raise InvalidCredentialsError("Invalid username or password")

        await self._repo.record_successful_login(self._session, admin.id)
        token_session = await self._repo.create_session(
            self._session,
            admin_id=admin.id,
            expires_at=now + timedelta(minutes=self._settings.platform_access_ttl_minutes),
            ip=info.ip,
            user_agent=info.user_agent,
        )
        token, expires_at = create_platform_token(
            admin_id=admin.id, session_id=token_session.id, settings=self._settings
        )
        await self._audit(admin.id, admin.username, "PLATFORM_LOGIN", info=info)
        security_event("platform.login.succeeded", admin_id=str(admin.id), client_ip=info.ip)
        return PlatformTokenData(access_token=token, expires_at=expires_at, username=admin.username)

    @staticmethod
    def _login_failed(reason: str, info: RequestInfo, admin_id: UUID | None = None) -> None:
        security_event(
            "platform.login.failed",
            level="warning",
            reason=reason,
            admin_id=str(admin_id) if admin_id else None,
            client_ip=info.ip,
        )

    async def logout(self, principal: PlatformPrincipal, info: RequestInfo) -> None:
        await self._repo.revoke_session(self._session, principal.session_id)
        await self._audit(principal.admin_id, principal.username, "PLATFORM_LOGOUT", info=info)

    # ---- queries -------------------------------------------------------------------------
    async def dashboard(self) -> DashboardData:
        now = datetime.now(UTC)
        counts = await self._repo.status_counts(self._session)
        since = (now - timedelta(days=29)).replace(hour=0, minute=0, second=0, microsecond=0)
        per_day = dict(await self._repo.registrations_per_day(self._session, since))
        series = [
            DayCount(
                day=(since + timedelta(days=i)).date(),
                count=per_day.get((since + timedelta(days=i)).date(), 0),
            )
            for i in range(30)
        ]
        pending_rows, _ = await self._repo.list_companies(
            self._session,
            status="PENDING_APPROVAL",
            query=None,
            limit=5,
            offset=0,
            oldest_first=True,
        )
        trial_cutoff = now + timedelta(days=7)
        trials = await self._repo.list_trials_expiring(self._session, trial_cutoff, 5)
        retention = await self._repo.list_retention_due(self._session, now + timedelta(days=30), 5)
        activity, _ = await self.list_audit(company_id=None, action=None, limit=8, offset=0)
        return DashboardData(
            counts_by_status=counts,
            total_companies=sum(counts.values()),
            pending_count=counts.get("PENDING_APPROVAL", 0),
            oldest_pending_since=await self._repo.oldest_pending_since(self._session),
            trials_expiring_within_7_days=await self._repo.trials_expiring_before(
                self._session, trial_cutoff
            ),
            registrations_last_30_days=series,
            registrations_total_30_days=sum(d.count for d in series),
            locked_company_admins=await self._repo.count_locked_company_admins(self._session),
            active_platform_admins=await self._repo.count_active_admins(self._session),
            pending=[_list_item(c, u) for c, u in pending_rows],
            trials_expiring=[_list_item(c, u) for c, u in trials],
            retention_due=[_list_item(c, u) for c, u in retention],
            recent_activity=activity,
        )

    async def list_plans(self) -> list[PlanItem]:
        return [
            PlanItem(code=p.code, name=p.name, description=p.description)
            for p in await self._repo.list_plans(self._session)
        ]

    async def list_companies(
        self, *, status: str | None, query: str | None, limit: int, offset: int
    ) -> tuple[list[CompanyListItem], int]:
        rows, total = await self._repo.list_companies(
            self._session, status=status, query=query, limit=limit, offset=offset
        )
        return [_list_item(c, u) for c, u in rows], total

    async def get_company(self, company_id: UUID) -> CompanyDetail:
        company = await self._repo.get_company(self._session, company_id)
        if company is None:
            raise CompanyNotFoundError()
        admin = await self._repo.get_company_admin(self._session, company)
        # subscription / employee / user_company are RLS tables: scope this transaction to the
        # one company being inspected (the platform role never bypasses RLS).
        await set_rls_company_id(self._session, str(company.id))
        sub = await self._repo.get_live_subscription(self._session, company.id)
        usage = await self._repo.usage_counts(self._session, company.id)
        now = datetime.now(UTC)
        return CompanyDetail(
            **_list_item(company, admin).model_dump(),
            country_code=company.country_code,
            timezone=company.timezone,
            status_reason=company.status_reason,
            status_changed_at=company.status_changed_at,
            approved_at=company.approved_at,
            retention_until=company.retention_until,
            admin_locked=bool(admin and admin.locked_until and admin.locked_until > now),
            subscription=(
                SubscriptionInfo(
                    plan_code=sub[1].code,
                    plan_name=sub[1].name,
                    status=sub[0].status,
                    trial_ends_at=sub[0].trial_ends_at,
                    seat_limit_override=sub[0].seat_limit_override,
                )
                if sub
                else None
            ),
            usage=UsageInfo(**usage),
        )

    async def list_audit(
        self, *, company_id: UUID | None, action: str | None, limit: int, offset: int
    ) -> tuple[list[PlatformAuditEntry], int]:
        rows, total = await self._repo.list_audit(
            self._session, company_id=company_id, action=action, limit=limit, offset=offset
        )
        return [
            PlatformAuditEntry(
                id=r.id,
                created_at=r.created_at,
                actor_username=r.actor_username,
                action=r.action,
                company_id=r.company_id,
                reason=r.reason,
                before_status=r.before_status,
                after_status=r.after_status,
                request_id=r.request_id,
            )
            for r in rows
        ], total

    # ---- lifecycle -----------------------------------------------------------------------
    async def change_status(
        self,
        action: str,
        company_id: UUID,
        principal: PlatformPrincipal,
        info: RequestInfo,
        *,
        reason: str | None,
        confirm_name: str | None = None,
    ) -> CompanyDetail:
        from_statuses, target = _TRANSITIONS[action]
        company = await self._repo.get_company(self._session, company_id)
        if company is None:
            raise CompanyNotFoundError()
        if action == "terminate" and (confirm_name or "").strip() != company.name:
            raise ConfirmationMismatchError()
        if company.status not in from_statuses:
            raise InvalidCompanyTransitionError(action, company.status)

        now = datetime.now(UTC)
        before = company.status
        values: dict[str, Any] = {
            "status": target,
            "status_reason": reason,
            "status_changed_at": now,
            "status_changed_by_platform_admin_id": principal.admin_id,
            "updated_at": now,
        }
        if action == "approve":
            values["approved_at"] = now
            values["trial_ends_at"] = now + timedelta(days=TRIAL_PERIOD_DAYS)
            values["retention_until"] = None
        elif action == "reactivate":
            # Back to TRIAL if the trial clock is still running, otherwise ACTIVE.
            if company.trial_ends_at is not None and company.trial_ends_at > now:
                values["status"] = target = "TRIAL"
        elif action == "terminate":
            values["retention_until"] = now + timedelta(
                days=self._settings.terminated_company_retention_days
            )

        updated = await self._repo.transition_company(
            self._session, company_id=company_id, from_statuses=from_statuses, values=values
        )
        if updated is None:  # changed by someone else between our read and the write
            raise InvalidCompanyTransitionError(action, "changed concurrently")

        await set_rls_company_id(self._session, str(company_id))
        if action == "approve":
            sub = await self._repo.get_live_subscription(self._session, company_id)
            if sub is not None:
                sub[0].trial_ends_at = values["trial_ends_at"]
        # No session revocation: `get_current_user` / refresh / login consult the company status
        # on every request, so a REJECTED / TERMINATED company is locked out at once and its users
        # get the specific COMPANY_* error rather than a generic 401. It also keeps reject ->
        # approve reversible without forcing everyone to sign in again.

        action_code = f"COMPANY_{_EVENT[action].upper()}"
        await self._audit(
            principal.admin_id,
            principal.username,
            action_code,
            info=info,
            company_id=company_id,
            reason=reason,
            before_status=before,
            after_status=target,
        )
        await self._tenant_audit.record(
            self._session,
            company_id=company_id,
            actor_user_id=None,
            action="COMPANY_STATUS_CHANGED_BY_PLATFORM",
            entity_type="company",
            entity_id=company_id,
            before={"status": before},
            after={"status": target, "reason": reason},
            ip=info.ip,
            user_agent=info.user_agent,
        )
        security_event(
            "platform.company.status_changed",
            level="warning" if action in ("suspend", "terminate", "reject") else "info",
            company_id=str(company_id),
            action=action,
            before=before,
            after=target,
            admin_id=str(principal.admin_id),
        )
        await self._session.commit()

        await self._notify(updated, _EVENT[action], reason)
        return await self.get_company(company_id)

    async def update_subscription(
        self,
        company_id: UUID,
        patch: SubscriptionPatch,
        principal: PlatformPrincipal,
        info: RequestInfo,
    ) -> CompanyDetail:
        company = await self._repo.get_company(self._session, company_id)
        if company is None:
            raise CompanyNotFoundError()
        await set_rls_company_id(self._session, str(company_id))
        live = await self._repo.get_live_subscription(self._session, company_id)
        if live is None:
            raise NoSubscriptionError()
        sub = live[0]
        now = datetime.now(UTC)
        changes: dict[str, Any] = {}

        if patch.plan_code is not None:
            plan = await self._repo.get_plan_by_code(self._session, patch.plan_code)
            if plan is None:
                raise PlanNotFoundError()
            changes["plan_code"] = {"from": live[1].code, "to": plan.code}
            sub.plan_id = plan.id
        if patch.extend_trial_days is not None:
            base = max(sub.trial_ends_at or now, now)
            new_end = base + timedelta(days=patch.extend_trial_days)
            changes["trial_ends_at"] = new_end.isoformat()
            sub.trial_ends_at = new_end
            if company.status == "TRIAL":
                company.trial_ends_at = new_end
        if "seat_limit_override" in patch.model_fields_set:
            changes["seat_limit_override"] = {
                "from": sub.seat_limit_override,
                "to": patch.seat_limit_override,
            }
            sub.seat_limit_override = patch.seat_limit_override
        if changes:
            sub.version += 1
            sub.updated_at = now
            await self._session.flush()
            await self._audit(
                principal.admin_id,
                principal.username,
                "SUBSCRIPTION_CHANGED",
                info=info,
                company_id=company_id,
                reason=patch.reason,
                details=changes,
            )
        return await self.get_company(company_id)

    async def unlock_company_admin(
        self, company_id: UUID, principal: PlatformPrincipal, info: RequestInfo
    ) -> CompanyDetail:
        company = await self._repo.get_company(self._session, company_id)
        if company is None:
            raise CompanyNotFoundError()
        admin = await self._repo.get_company_admin(self._session, company)
        if admin is not None:
            await self._repo.unlock_user(self._session, admin.id)
            await self._audit(
                principal.admin_id,
                principal.username,
                "COMPANY_ADMIN_UNLOCKED",
                info=info,
                company_id=company_id,
            )
        return await self.get_company(company_id)

    # ---- platform admin accounts ---------------------------------------------------------
    async def list_admins(self, principal: PlatformPrincipal) -> list[PlatformAdminItem]:
        now = datetime.now(UTC)
        return [
            PlatformAdminItem(
                id=a.id,
                username=a.username,
                status=a.status,  # type: ignore[arg-type]
                locked=bool(a.locked_until and a.locked_until > now),
                last_login_at=a.last_login_at,
                created_at=a.created_at,
                is_you=a.id == principal.admin_id,
            )
            for a in await self._repo.list_admins(self._session)
        ]

    async def create_admin(
        self, username: str, password: str, principal: PlatformPrincipal, info: RequestInfo
    ) -> PlatformAdminItem:
        if not is_password_strong_enough(password):
            raise WeakPlatformPasswordError()
        if await self._repo.get_admin_by_username(self._session, username) is not None:
            raise PlatformUsernameTakenError()
        admin = await self._repo.create_admin(
            self._session, username=username, password_hash=hash_password(password)
        )
        await self._audit(
            principal.admin_id,
            principal.username,
            "PLATFORM_ADMIN_CREATED",
            info=info,
            details={"username": username},
        )
        return await self._admin_item(admin.id, principal)

    async def set_admin_status(
        self, admin_id: UUID, status: str, principal: PlatformPrincipal, info: RequestInfo
    ) -> PlatformAdminItem:
        admin = await self._repo.get_admin(self._session, admin_id)
        if admin is None:
            raise PlatformAdminNotFoundError()
        if status == "DISABLED" and admin.status == "ACTIVE":
            if admin.id == principal.admin_id:
                raise CannotRemoveLastAdminError("You cannot disable your own account")
            if await self._repo.count_active_admins(self._session) <= 1:
                raise CannotRemoveLastAdminError("At least one platform admin must stay active")
        if admin.status != status:
            admin.status = status
            admin.updated_at = datetime.now(UTC)
            if status == "DISABLED":
                await self._repo.revoke_admin_sessions(self._session, admin.id)
            await self._audit(
                principal.admin_id,
                principal.username,
                "PLATFORM_ADMIN_DISABLED" if status == "DISABLED" else "PLATFORM_ADMIN_ENABLED",
                info=info,
                details={"username": admin.username},
            )
        return await self._admin_item(admin.id, principal)

    async def reset_admin_password(
        self,
        admin_id: UUID,
        password: str,
        principal: PlatformPrincipal,
        info: RequestInfo,
    ) -> PlatformAdminItem:
        admin = await self._repo.get_admin(self._session, admin_id)
        if admin is None:
            raise PlatformAdminNotFoundError()
        if not is_password_strong_enough(password):
            raise WeakPlatformPasswordError()
        admin.password_hash = hash_password(password)
        admin.failed_login_count = 0
        admin.locked_until = None
        admin.updated_at = datetime.now(UTC)
        # Everyone signed in as this admin is signed out — except the caller resetting their own.
        if admin.id != principal.admin_id:
            await self._repo.revoke_admin_sessions(self._session, admin.id)
        await self._audit(
            principal.admin_id,
            principal.username,
            "PLATFORM_ADMIN_PASSWORD_RESET",
            info=info,
            details={"username": admin.username},
        )
        return await self._admin_item(admin.id, principal)

    async def _admin_item(self, admin_id: UUID, principal: PlatformPrincipal) -> PlatformAdminItem:
        items = await self.list_admins(principal)
        return next(i for i in items if i.id == admin_id)

    # ---- support -------------------------------------------------------------------------
    async def resend_admin_verification(
        self, company_id: UUID, principal: PlatformPrincipal, info: RequestInfo
    ) -> CompanyDetail:
        from hrms.modules.identity.service import IdentityService

        company = await self._repo.get_company(self._session, company_id)
        if company is None:
            raise CompanyNotFoundError()
        admin = await self._repo.get_company_admin(self._session, company)
        if admin is not None and admin.email:
            if admin.email_verified_at is not None:
                raise AdminAlreadyVerifiedError()
            await IdentityService(self._session, self._settings).send_verification_email(
                user_id=admin.id, email=admin.email, first_name=admin.first_name
            )
            await self._audit(
                principal.admin_id,
                principal.username,
                "COMPANY_ADMIN_VERIFICATION_RESENT",
                info=info,
                company_id=company_id,
            )
        return await self.get_company(company_id)

    # ---- internals -----------------------------------------------------------------------
    async def _audit(
        self,
        admin_id: UUID | None,
        username: str | None,
        action: str,
        *,
        info: RequestInfo,
        company_id: UUID | None = None,
        reason: str | None = None,
        before_status: str | None = None,
        after_status: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        await self._repo.add_audit(
            self._session,
            actor_platform_admin_id=admin_id,
            actor_username=username,
            action=action,
            company_id=company_id,
            reason=reason,
            before_status=before_status,
            after_status=after_status,
            details=details,
            ip=info.ip,
            user_agent=(info.user_agent or "")[:255] or None,
            request_id=current_request_id(),
        )

    async def _notify(self, company: Company, event: str, reason: str | None) -> None:
        """Best-effort email to the company's admin; a delivery failure never undoes the change."""
        try:
            admin = await self._repo.get_company_admin(self._session, company)
            if admin is None or not admin.email:
                return
            subject, html, text = build_status_email(
                event=event,
                first_name=admin.first_name,
                company_name=company.name,
                reason=reason,
                retention_until=(
                    company.retention_until.date().isoformat() if company.retention_until else None
                ),
            )
            await get_email_sender(self._settings).send(
                to=admin.email, subject=subject, html_body=html, text_body=text
            )
        except Exception as exc:  # noqa: BLE001 — see docstring
            log_email_failure(f"company_{event}", exc, company_id=str(company.id))
            safe_log(_logger.warning, "platform.notification_failed", notification=event)
