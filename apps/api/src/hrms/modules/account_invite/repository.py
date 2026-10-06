"""Pure-query repository for the account-invite module — no business rules (Module Standard §2),
mirroring `organisation/repository.py`'s own convention exactly. Touches `Role`/`UserRole`/
`UserCompany` (identity-owned models) directly for the same reason `OrganisationRepository`
already does — there is no dedicated role-management repository anywhere yet."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.db.models.identity import Role, User, UserCompany, UserRole
from hrms.modules.account_invite.models import AccountInvite


class AccountInviteRepository:
    async def list_user_companies_for_company(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[tuple[UserCompany, User]]:
        """Backs `GET /users` — every `UserCompany` membership for this tenant, joined to its
        `User` row. `limit=None` (the default) returns every row unpaginated — preserves the
        exact pre-FINDING-03 behavior for any non-HTTP caller. `GET /users` always passes an
        explicit `limit`/`offset`, applied at the SQL layer. `id` is a stable secondary key —
        `created_at` alone can tie for memberships created in the same request burst (e.g. a
        bulk invite), which would make page boundaries non-deterministic."""
        stmt = (
            select(UserCompany, User)
            .join(User, User.id == UserCompany.user_id)
            .where(UserCompany.company_id == company_id)
            .order_by(UserCompany.created_at, UserCompany.id)
        )
        if limit is not None:
            stmt = stmt.limit(limit).offset(offset)
        return [(row.UserCompany, row.User) for row in (await session.execute(stmt)).all()]

    async def count_user_companies_for_company(
        self, session: AsyncSession, *, company_id: UUID
    ) -> int:
        """Same predicate as `list_user_companies_for_company`, no `ORDER BY`/`LIMIT` — the
        paired COUNT query for `GET /users`'s `pagination.total` (FINDING-03)."""
        stmt = (
            select(func.count())
            .select_from(UserCompany)
            .where(UserCompany.company_id == company_id)
        )
        return int((await session.execute(stmt)).scalar_one())

    async def insert_invite(self, session: AsyncSession, *, data: dict[str, Any]) -> AccountInvite:
        row = AccountInvite(**data)
        session.add(row)
        await session.flush()
        return row

    async def get_by_hash(
        self, session: AsyncSession, *, token_hash: str, for_update: bool = False
    ) -> AccountInvite | None:
        stmt = select(AccountInvite).where(AccountInvite.token_hash == token_hash)
        if for_update:
            stmt = stmt.with_for_update()
        return (await session.execute(stmt)).scalar_one_or_none()

    async def revoke_live_invites_for_employee(
        self, session: AsyncSession, *, employee_id: UUID, now: datetime
    ) -> None:
        await session.execute(
            update(AccountInvite)
            .where(
                AccountInvite.employee_id == employee_id,
                AccountInvite.accepted_at.is_(None),
                AccountInvite.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )

    async def revoke_live_invites_for_email(
        self, session: AsyncSession, *, company_id: UUID, email: str, now: datetime
    ) -> None:
        await session.execute(
            update(AccountInvite)
            .where(
                AccountInvite.company_id == company_id,
                AccountInvite.email == email,
                AccountInvite.employee_id.is_(None),
                AccountInvite.accepted_at.is_(None),
                AccountInvite.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )

    async def mark_accepted(
        self, session: AsyncSession, *, invite: AccountInvite, now: datetime
    ) -> None:
        invite.accepted_at = now
        await session.flush()

    async def get_role_by_code(
        self, session: AsyncSession, *, company_id: UUID, code: str
    ) -> Role | None:
        stmt = select(Role).where(
            Role.company_id == company_id, Role.code == code, Role.deleted_at.is_(None)
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    async def list_role_codes_for_user_company(
        self, session: AsyncSession, *, user_company_id: UUID
    ) -> list[str]:
        stmt = (
            select(Role.code)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_company_id == user_company_id)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def replace_user_roles(
        self, session: AsyncSession, *, user_company_id: UUID, role_ids: list[UUID]
    ) -> None:
        """Full replace, not a diff — the caller (`AccountInviteService.assign_roles`) already
        resolved and validated every `role_ids` entry against the four fixed role codes; this is
        the same "delete then insert" shape `PolicyAssignment`-style replace endpoints elsewhere
        in this codebase already use for a small, bounded set of rows."""
        await session.execute(delete(UserRole).where(UserRole.user_company_id == user_company_id))
        for role_id in role_ids:
            session.add(UserRole(id=uuid4(), user_company_id=user_company_id, role_id=role_id))
        await session.flush()
