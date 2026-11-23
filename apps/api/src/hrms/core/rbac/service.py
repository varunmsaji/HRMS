from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.db.models.identity import (
    Permission,
    Role,
    RolePermission,
    UserBranchAccess,
    UserCompany,
    UserRole,
)
from hrms.core.rbac.types import DataScope, DataScopeLevel

#: Roles whose company-wide / single-branch grants are narrowed to the admin-assigned branches.
BRANCH_RESTRICTED_ROLE_CODES = frozenset({"HR_ADMIN", "BRANCH_MANAGER"})
#: `HR_ADMIN` is the role whose `COMPANY` grants carry HR-stage approval.
_HR_ROLE_CODE = "HR_ADMIN"
_COMPANY_ADMIN_ROLE_CODE = "COMPANY_ADMIN"
#: Permission families whose data is keyed by employee, so a branch assignment can narrow it.
#: Everything else (settings, org masters, payroll setup and runs) stays as granted: payroll is
#: narrowed in its own, later change together with its branch filtering.
BRANCH_SCOPED_PERMISSION_PREFIXES = ("EMPLOYEE.", "ATTENDANCE.", "LEAVE.", "ONBOARDING.")


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

    async def get_grants_for_permission(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        company_id: UUID,
        code: str,
    ) -> set[tuple[str, str]]:
        """Like `get_data_scopes_for_permission`, but each grant also names the role it came from:
        `(data_scope, role_code)` pairs. Needed to narrow only the `HR_ADMIN` / `BRANCH_MANAGER`
        grants to assigned branches and leave every other role's grant untouched."""
        stmt = (
            select(RolePermission.data_scope, Role.code)
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
        return {(scope, role_code) for scope, role_code in result.all()}

    async def holds_role(
        self, session: AsyncSession, *, user_id: UUID, company_id: UUID, role_code: str
    ) -> bool:
        stmt = (
            select(UserRole.id)
            .join(Role, Role.id == UserRole.role_id)
            .join(UserCompany, UserCompany.id == UserRole.user_company_id)
            .where(
                UserCompany.user_id == user_id,
                UserCompany.company_id == company_id,
                UserCompany.status == "ACTIVE",
                Role.code == role_code,
                Role.deleted_at.is_(None),
            )
            .limit(1)
        )
        return (await session.execute(stmt)).first() is not None

    async def list_live_branch_ids(
        self, session: AsyncSession, *, user_id: UUID, company_id: UUID
    ) -> set[UUID]:
        """The user's live `user_branch_access` branch ids. Whether each branch is itself still
        active is the consuming module's check (`core` has no knowledge of the branch table)."""
        stmt = select(UserBranchAccess.branch_id).where(
            UserBranchAccess.company_id == company_id,
            UserBranchAccess.user_id == user_id,
            UserBranchAccess.deleted_at.is_(None),
        )
        return set((await session.execute(stmt)).scalars().all())

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
        if not code.startswith(BRANCH_SCOPED_PERMISSION_PREFIXES):
            raw_scopes = await self._repo.get_data_scopes_for_permission(
                self._session, user_id=user_id, company_id=company_id, code=code
            )
            return DataScope(levels=frozenset(DataScopeLevel(value) for value in raw_scopes))

        grants = await self._repo.get_grants_for_permission(
            self._session, user_id=user_id, company_id=company_id, code=code
        )
        # Fast path: nothing here comes from a branch-restricted role, so nothing is narrowed.
        if not any(
            role_code in BRANCH_RESTRICTED_ROLE_CODES and scope in ("COMPANY", "BRANCH")
            for scope, role_code in grants
        ):
            return DataScope(levels=frozenset(DataScopeLevel(scope) for scope, _ in grants))

        # A company admin ignores the branch list and keeps the whole company, even when they
        # also hold HR_ADMIN (company-wide access wins).
        if await self._repo.holds_role(
            self._session,
            user_id=user_id,
            company_id=company_id,
            role_code=_COMPANY_ADMIN_ROLE_CODE,
        ):
            return DataScope(levels=frozenset(DataScopeLevel(scope) for scope, _ in grants))

        levels: set[DataScopeLevel] = set()
        narrowed = False
        company_grant_restricted = False
        for scope, role_code in grants:
            if role_code in BRANCH_RESTRICTED_ROLE_CODES and scope in ("COMPANY", "BRANCH"):
                narrowed = True
                levels.add(DataScopeLevel.ASSIGNED_BRANCHES)
                if scope == "COMPANY" and role_code == _HR_ROLE_CODE:
                    company_grant_restricted = True
            else:
                levels.add(DataScopeLevel(scope))
        branch_ids: frozenset[UUID] = frozenset()
        if narrowed:
            branch_ids = frozenset(
                await self._repo.list_live_branch_ids(
                    self._session, user_id=user_id, company_id=company_id
                )
            )
        # A `COMPANY` level that survives came from a role outside the restricted pair (say a
        # custom role): that role's grant is honoured as written.
        return DataScope(
            levels=frozenset(levels),
            branch_ids=branch_ids,
            company_grant_restricted=company_grant_restricted,
        )
