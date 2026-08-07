from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.db.models.identity import Permission, Role, RolePermission, UserCompany, UserRole


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
