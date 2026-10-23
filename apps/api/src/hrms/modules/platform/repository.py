from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import ColumnElement, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.db.models.identity import Company, User
from hrms.modules.organisation.models import Plan, Subscription
from hrms.modules.platform.models import PlatformAdmin, PlatformAuditLog, PlatformSession

_LIVE_SUBSCRIPTION_EXCLUDED = ("CANCELED", "EXPIRED")


class PlatformRepository:
    # ---- platform identity -------------------------------------------------------------
    async def get_admin(self, session: AsyncSession, admin_id: UUID) -> PlatformAdmin | None:
        return await session.get(PlatformAdmin, admin_id)

    async def get_admin_by_username(
        self, session: AsyncSession, username: str
    ) -> PlatformAdmin | None:
        stmt = select(PlatformAdmin).where(PlatformAdmin.username == username)
        return (await session.execute(stmt)).scalar_one_or_none()

    async def get_session(self, session: AsyncSession, session_id: UUID) -> PlatformSession | None:
        return await session.get(PlatformSession, session_id)

    async def create_session(
        self,
        session: AsyncSession,
        *,
        admin_id: UUID,
        expires_at: datetime,
        ip: str | None,
        user_agent: str | None,
    ) -> PlatformSession:
        row = PlatformSession(
            id=uuid4(),
            platform_admin_id=admin_id,
            expires_at=expires_at,
            ip=ip,
            user_agent=(user_agent or "")[:255] or None,
        )
        session.add(row)
        await session.flush()
        return row

    async def revoke_session(self, session: AsyncSession, session_id: UUID) -> None:
        await session.execute(
            update(PlatformSession)
            .where(PlatformSession.id == session_id, PlatformSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )

    async def record_failed_login(
        self, session: AsyncSession, admin_id: UUID, *, max_attempts: int, lock_minutes: int
    ) -> PlatformAdmin:
        """Atomic increment; locks the account when the threshold is crossed."""
        await session.execute(
            text(
                """
                    UPDATE platform_admin
                    SET failed_login_count = failed_login_count + 1,
                        locked_until = CASE WHEN failed_login_count + 1 >= :max
                          THEN now() + make_interval(mins => :mins) ELSE locked_until END,
                        updated_at = now()
                    WHERE id = :id 
                    """
            ),
            {"id": admin_id, "max": max_attempts, "mins": lock_minutes},
        )
        admin = await session.get(PlatformAdmin, admin_id, populate_existing=True)
        assert admin is not None
        return admin

    async def record_successful_login(self, session: AsyncSession, admin_id: UUID) -> None:
        await session.execute(
            update(PlatformAdmin)
            .where(PlatformAdmin.id == admin_id)
            .values(failed_login_count=0, locked_until=None, last_login_at=datetime.now(UTC))
        )

    # ---- companies ---------------------------------------------------------------------
    async def get_company(self, session: AsyncSession, company_id: UUID) -> Company | None:
        stmt = select(Company).where(Company.id == company_id, Company.deleted_at.is_(None))
        return (await session.execute(stmt)).scalar_one_or_none()

    async def list_companies(
        self,
        session: AsyncSession,
        *,
        status: str | None,
        query: str | None,
        limit: int,
        offset: int,
        oldest_first: bool = False,
    ) -> tuple[list[tuple[Company, User | None]], int]:
        conditions: list[ColumnElement[bool]] = [Company.deleted_at.is_(None)]
        if status:
            conditions.append(Company.status == status)
        if query:
            like = f"%{query.strip().replace('%', r'\%').replace('_', r'\_')}%"
            conditions.append(or_(Company.name.ilike(like), User.email.ilike(like)))
        base = (
            select(Company, User).outerjoin(User, User.id == Company.created_by).where(*conditions)
        )
        total = (
            await session.execute(
                select(func.count())
                .select_from(Company)
                .outerjoin(User, User.id == Company.created_by)
                .where(*conditions)
            )
        ).scalar_one()
        rows = (
            await session.execute(
                base.order_by(
                    Company.created_at.asc() if oldest_first else Company.created_at.desc(),
                    Company.id,
                )
                .limit(limit)
                .offset(offset)
            )
        ).all()
        return [(c, u) for c, u in rows], int(total)

    async def get_company_admin(self, session: AsyncSession, company: Company) -> User | None:
        if company.created_by is None:
            return None
        return await session.get(User, company.created_by)

    async def transition_company(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        from_statuses: tuple[str, ...],
        values: dict[str, Any],
    ) -> Company | None:
        """Atomic compare-and-set on `status`: a concurrent transition makes this return None."""
        stmt = (
            update(Company)
            .where(
                Company.id == company_id,
                Company.status.in_(from_statuses),
                Company.deleted_at.is_(None),
            )
            .values(**values, version=Company.version + 1)
            .returning(Company)
            .execution_options(populate_existing=True)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def unlock_user(self, session: AsyncSession, user_id: UUID) -> None:
        await session.execute(
            update(User).where(User.id == user_id).values(failed_login_count=0, locked_until=None)
        )

    # ---- subscription / plan (RLS: caller must have set app.company_id) -------------------
    async def get_live_subscription(
        self, session: AsyncSession, company_id: UUID
    ) -> tuple[Subscription, Plan] | None:
        stmt = (
            select(Subscription, Plan)
            .join(Plan, Plan.id == Subscription.plan_id)
            .where(
                Subscription.company_id == company_id,
                Subscription.deleted_at.is_(None),
                Subscription.status.notin_(_LIVE_SUBSCRIPTION_EXCLUDED),
            )
        )
        row = (await session.execute(stmt)).first()
        return (row[0], row[1]) if row else None

    async def get_plan_by_code(self, session: AsyncSession, code: str) -> Plan | None:
        stmt = select(Plan).where(Plan.code == code, Plan.is_active.is_(True))
        return (await session.execute(stmt)).scalar_one_or_none()

    async def usage_counts(self, session: AsyncSession, company_id: UUID) -> dict[str, int]:
        """Aggregates only (never rows). `employee` / `user_company` are RLS tables: the caller
        has pointed `app.company_id` at this one company."""
        employees = (
            await session.execute(
                text("SELECT count(*) FROM employee WHERE company_id = :c"),
                {"c": company_id},
            )
        ).scalar_one()
        users = (
            await session.execute(
                text(
                    "SELECT count(*) FROM user_company WHERE company_id = :c AND status = 'ACTIVE'"
                ),
                {"c": company_id},
            )
        ).scalar_one()
        return {"employees": int(employees), "active_users": int(users)}

    # ---- dashboard / audit -------------------------------------------------------------
    async def status_counts(self, session: AsyncSession) -> dict[str, int]:
        rows = (
            await session.execute(
                select(Company.status, func.count())
                .where(Company.deleted_at.is_(None))
                .group_by(Company.status)
            )
        ).all()
        return {status: int(n) for status, n in rows}

    async def oldest_pending_since(self, session: AsyncSession) -> datetime | None:
        return (
            await session.execute(
                select(func.min(Company.created_at)).where(
                    Company.status == "PENDING_APPROVAL", Company.deleted_at.is_(None)
                )
            )
        ).scalar_one()

    async def trials_expiring_before(self, session: AsyncSession, cutoff: datetime) -> int:
        return int(
            (
                await session.execute(
                    select(func.count()).where(
                        Company.status == "TRIAL",
                        Company.trial_ends_at.is_not(None),
                        Company.trial_ends_at <= cutoff,
                        Company.deleted_at.is_(None),
                    )
                )
            ).scalar_one()
        )

    async def add_audit(self, session: AsyncSession, **fields: Any) -> PlatformAuditLog:
        row = PlatformAuditLog(id=uuid4(), **fields)
        session.add(row)
        await session.flush()
        return row

    async def list_audit(
        self,
        session: AsyncSession,
        *,
        company_id: UUID | None,
        action: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[PlatformAuditLog], int]:
        conditions: list[ColumnElement[bool]] = []
        if company_id:
            conditions.append(PlatformAuditLog.company_id == company_id)
        if action:
            conditions.append(PlatformAuditLog.action == action)
        total = (
            await session.execute(
                select(func.count()).select_from(PlatformAuditLog).where(*conditions)
            )
        ).scalar_one()
        rows = (
            (
                await session.execute(
                    select(PlatformAuditLog)
                    .where(*conditions)
                    .order_by(PlatformAuditLog.created_at.desc(), PlatformAuditLog.id)
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
        return list(rows), int(total)

    # ---- dashboard extras ----------------------------------------------------------------
    async def registrations_per_day(
        self, session: AsyncSession, since: datetime
    ) -> list[tuple[Any, int]]:
        day = func.date_trunc("day", Company.created_at)
        rows = (
            await session.execute(
                select(day, func.count())
                .where(Company.created_at >= since, Company.deleted_at.is_(None))
                .group_by(day)
                .order_by(day)
            )
        ).all()
        return [(d.date(), int(n)) for d, n in rows]

    async def list_trials_expiring(
        self, session: AsyncSession, cutoff: datetime, limit: int
    ) -> list[tuple[Company, User | None]]:
        stmt = (
            select(Company, User)
            .outerjoin(User, User.id == Company.created_by)
            .where(
                Company.status == "TRIAL",
                Company.trial_ends_at.is_not(None),
                Company.trial_ends_at <= cutoff,
                Company.deleted_at.is_(None),
            )
            .order_by(Company.trial_ends_at.asc())
            .limit(limit)
        )
        return [(c, u) for c, u in (await session.execute(stmt)).all()]

    async def list_retention_due(
        self, session: AsyncSession, cutoff: datetime, limit: int
    ) -> list[tuple[Company, User | None]]:
        stmt = (
            select(Company, User)
            .outerjoin(User, User.id == Company.created_by)
            .where(
                Company.status == "TERMINATED",
                Company.retention_until.is_not(None),
                Company.retention_until <= cutoff,
                Company.deleted_at.is_(None),
            )
            .order_by(Company.retention_until.asc())
            .limit(limit)
        )
        return [(c, u) for c, u in (await session.execute(stmt)).all()]

    async def count_locked_company_admins(self, session: AsyncSession) -> int:
        stmt = (
            select(func.count())
            .select_from(Company)
            .join(User, User.id == Company.created_by)
            .where(
                User.locked_until.is_not(None),
                User.locked_until > datetime.now(UTC),
                Company.deleted_at.is_(None),
            )
        )
        return int((await session.execute(stmt)).scalar_one())

    async def list_plans(self, session: AsyncSession) -> list[Plan]:
        stmt = select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.code)
        return list((await session.execute(stmt)).scalars().all())

    # ---- platform admin accounts -----------------------------------------------------------
    async def list_admins(self, session: AsyncSession) -> list[PlatformAdmin]:
        stmt = select(PlatformAdmin).order_by(PlatformAdmin.created_at, PlatformAdmin.username)
        return list((await session.execute(stmt)).scalars().all())

    async def count_active_admins(self, session: AsyncSession) -> int:
        stmt = (
            select(func.count()).select_from(PlatformAdmin).where(PlatformAdmin.status == "ACTIVE")
        )
        return int((await session.execute(stmt)).scalar_one())

    async def create_admin(
        self, session: AsyncSession, *, username: str, password_hash: str
    ) -> PlatformAdmin:
        row = PlatformAdmin(id=uuid4(), username=username, password_hash=password_hash)
        session.add(row)
        await session.flush()
        return row

    async def revoke_admin_sessions(self, session: AsyncSession, admin_id: UUID) -> None:
        await session.execute(
            update(PlatformSession)
            .where(
                PlatformSession.platform_admin_id == admin_id,
                PlatformSession.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
