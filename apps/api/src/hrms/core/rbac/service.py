from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.db.models.identity import Permission, Role, RolePermission, UserCompany, UserRole
from hrms.core.rbac.types import DataScope, DataScopeLevel


class RbacRepository:
    async def get_permission_codes_for_user(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        company_id: UUID,
    ) -> set[str]:
        stmt = (
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(Role, Role.id == RolePermission.role_id)
            .join(UserRole, UserRole.role_id == Role.id)
            .join(UserCompany, UserCompany.id == UserRole.user_company_id)
            .where(
                UserCompany.user_id == user_id,
                UserCompany.company_id == company_id,
                UserCompany.status == "ACTIVE",
            )
        )
        result = await session.execute(stmt)
        return set(result.scalars().all())

    async def get_data_scopes_for_permission(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        company_id: UUID,
        code: str,
    ) -> set[str]:
        """Every distinct `role_permission.data_scope` value granted to this user, for this one
        permission code, across every role they hold — one row per matching `(role, permission)`
        pair (`docs/modules/employee/25_EMPLOYEE_RBAC_DATA_SCOPE_IMPLEMENTATION_PLAN.md` §12: a
        user with two roles that both grant `code` gets both roles' scope values back; resolving
        them into one effective scope is the caller's job, not this query's)."""
        stmt = (
            select(RolePermission.data_scope)
            .join(Role, Role.id == RolePermission.role_id)
            .join(UserRole, UserRole.role_id == Role.id)
            .join(UserCompany, UserCompany.id == UserRole.user_company_id)
            .join(Permission, Permission.id == RolePermission.permission_id)
            .where(
                UserCompany.user_id == user_id,
                UserCompany.company_id == company_id,
                UserCompany.status == "ACTIVE",
                Permission.code == code,
            )
        )
        result = await session.execute(stmt)
        return set(result.scalars().all())

    async def list_user_ids_with_permission(
        self, session: AsyncSession, *, company_id: UUID, code: str
    ) -> list[UUID]:
        """Every active member of `company_id` holding `code` through any role — e.g. who to
        notify about work only they can do (PAY-006's HR reminder digest)."""
        stmt = (
            select(UserCompany.user_id)
            .join(UserRole, UserRole.user_company_id == UserCompany.id)
            .join(Role, Role.id == UserRole.role_id)
            .join(RolePermission, RolePermission.role_id == Role.id)
            .join(Permission, Permission.id == RolePermission.permission_id)
            .where(
                UserCompany.company_id == company_id,
                UserCompany.status == "ACTIVE",
                Permission.code == code,
            )
            .distinct()
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


class RbacService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = RbacRepository()

    async def get_permission_codes(self, user_id: UUID, company_id: UUID) -> set[str]:
        return await self._repo.get_permission_codes_for_user(
            self._session, user_id=user_id, company_id=company_id
        )

    async def has_permission(self, user_id: UUID, company_id: UUID, code: str) -> bool:
        codes = await self.get_permission_codes(user_id, company_id)
        return code in codes

    async def resolve_data_scope(self, user_id: UUID, company_id: UUID, code: str) -> DataScope:
        """Which `DataScopeLevel`(s) this user's roles grant for `code` — purely from
        `role_permission`/`role`/`user_role`/`user_company`; `core/rbac` has no knowledge of
        `employee_assignment` or any other module's domain data (`hrms.core` may not import
        `hrms.modules`, `apps/api/.importlinter`). Turning `levels` into a concrete set of
        visible record IDs is the consuming module's job
        (`docs/modules/employee/25_EMPLOYEE_RBAC_DATA_SCOPE_IMPLEMENTATION_PLAN.md` §7). An empty
        result (no matching grant — should not happen on the success path, since
        `require_permission` already confirmed `code` is held, but handled defensively) fails
        closed: an empty `DataScope.levels`, never a fallback to `COMPANY`."""
        raw_scopes = await self._repo.get_data_scopes_for_permission(
            self._session, user_id=user_id, company_id=company_id, code=code
        )
        levels = frozenset(DataScopeLevel(value) for value in raw_scopes)
        return DataScope(levels=levels)
