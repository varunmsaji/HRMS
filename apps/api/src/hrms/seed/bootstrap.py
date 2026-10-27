import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.auth.passwords import hash_password
from hrms.core.db.models.identity import (
    Company,
    Permission,
    Role,
    RolePermission,
    User,
    UserCompany,
    UserRole,
)
from hrms.modules.attendance.permissions import ATTENDANCE_PERMISSIONS
from hrms.modules.employee.permissions import EMPLOYEE_PERMISSIONS
from hrms.modules.identity.permissions import B1_PERMISSIONS
from hrms.modules.leave.permissions import LEAVE_PERMISSIONS
from hrms.modules.onboarding.permissions import ONBOARDING_PERMISSIONS
from hrms.modules.organisation.permissions import ORGANISATION_PERMISSIONS
from hrms.modules.payroll.permissions import PAYROLL_PERMISSIONS
from hrms.seed.constants import (
    ADMIN_EMAIL,
    ADMIN_USER_ID,
    COMPANY_A_ID,
    COMPANY_A_NAME,
    COMPANY_B_ID,
    COMPANY_B_NAME,
    DEMO_PASSWORD,
    VIEWER_EMAIL,
    VIEWER_USER_ID,
)


async def seed_b1_foundation(session: AsyncSession) -> None:
    """Insert B1 demo companies, permissions, roles, and users (idempotent)."""
    now = datetime.now(UTC)

    for company_id, name in ((COMPANY_A_ID, COMPANY_A_NAME), (COMPANY_B_ID, COMPANY_B_NAME)):
        existing = await session.get(Company, company_id)
        if existing is None:
            session.add(
                Company(
                    id=company_id,
                    name=name,
                    status="ACTIVE",
                    created_at=now,
                    updated_at=now,
                )
            )

    permission_rows: dict[str, Permission] = {}
    for code, domain, description in [
        *B1_PERMISSIONS,
        *ORGANISATION_PERMISSIONS,
        *EMPLOYEE_PERMISSIONS,
        *ATTENDANCE_PERMISSIONS,
        *LEAVE_PERMISSIONS,
        *ONBOARDING_PERMISSIONS,
        *PAYROLL_PERMISSIONS,
    ]:
        row = (
            await session.execute(select(Permission).where(Permission.code == code))
        ).scalar_one_or_none()
        if row is None:
            row = Permission(id=uuid4(), code=code, domain=domain, description=description)
            session.add(row)
            await session.flush()
        permission_rows[code] = row

    admin_role_a = await _ensure_role(
        session,
        company_id=COMPANY_A_ID,
        code="COMPANY_ADMIN",
        name="Company Administrator",
        is_system=True,
    )
    viewer_role_a = await _ensure_role(
        session,
        company_id=COMPANY_A_ID,
        code="EMPLOYEE_VIEWER",
        name="Employee Viewer",
        is_system=True,
    )

    for perm in permission_rows.values():
        await _ensure_role_permission(session, admin_role_a.id, perm.id)

    from hrms.modules.identity.permissions import EMPLOYEE_VIEW

    await _ensure_role_permission(session, viewer_role_a.id, permission_rows[EMPLOYEE_VIEW].id)

    await _ensure_user(
        session,
        user_id=ADMIN_USER_ID,
        email=ADMIN_EMAIL,
        password=DEMO_PASSWORD,
        now=now,
    )
    await _ensure_user(
        session,
        user_id=VIEWER_USER_ID,
        email=VIEWER_EMAIL,
        password=DEMO_PASSWORD,
        now=now,
    )

    admin_uc_a = await _ensure_user_company(
        session, user_id=ADMIN_USER_ID, company_id=COMPANY_A_ID, is_primary=True
    )
    await _ensure_user_company(
        session, user_id=ADMIN_USER_ID, company_id=COMPANY_B_ID, is_primary=False
    )
    viewer_uc_a = await _ensure_user_company(
        session, user_id=VIEWER_USER_ID, company_id=COMPANY_A_ID, is_primary=True
    )

    await _ensure_user_role(session, admin_uc_a.id, admin_role_a.id)
    await _ensure_user_role(session, viewer_uc_a.id, viewer_role_a.id)

    await session.flush()


async def clear_b1_seed(session: AsyncSession) -> None:
    """Remove demo seed rows (for test isolation).

    Destructive: TRUNCATEs every company and user. Refuses to run against the persistent
    developer database (`hrms_dev`) outside CI, because a bare `pytest` run defaults to it and
    would silently wipe real companies/users created through the app. Use
    `run_full_tests.py` (isolated `hrms_test`), or set `HRMS_ALLOW_DEV_DB_WIPE=1` to override.
    """
    database = session.get_bind().engine.url.database
    if (
        database == "hrms_dev"
        and not os.environ.get("CI")
        and os.environ.get("HRMS_ALLOW_DEV_DB_WIPE") != "1"
    ):
        raise RuntimeError(
            "Refusing to TRUNCATE company/user on the persistent 'hrms_dev' database. "
            "Run the suite via run_full_tests.py (uses hrms_test), point DATABASE_URL at a "
            "throwaway database, or set HRMS_ALLOW_DEV_DB_WIPE=1 if you really mean it."
        )
    await session.execute(text('TRUNCATE company, "user", audit_log, plan CASCADE;'))
    await session.flush()


async def _ensure_role(
    session: AsyncSession,
    *,
    company_id: UUID,
    code: str,
    name: str,
    is_system: bool,
) -> Role:
    row = (
        await session.execute(select(Role).where(Role.company_id == company_id, Role.code == code))
    ).scalar_one_or_none()
    if row is not None:
        return row
    now = datetime.now(UTC)
    row = Role(
        id=uuid4(),
        company_id=company_id,
        code=code,
        name=name,
        is_system=is_system,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.flush()
    return row


async def _ensure_role_permission(
    session: AsyncSession, role_id: UUID, permission_id: UUID
) -> None:
    exists = (
        await session.execute(
            select(RolePermission).where(
                RolePermission.role_id == role_id,
                RolePermission.permission_id == permission_id,
            )
        )
    ).scalar_one_or_none()
    if exists is None:
        session.add(RolePermission(role_id=role_id, permission_id=permission_id))


async def _ensure_user_company(
    session: AsyncSession,
    *,
    user_id: UUID,
    company_id: UUID,
    is_primary: bool,
) -> UserCompany:
    row = (
        await session.execute(
            select(UserCompany).where(
                UserCompany.user_id == user_id,
                UserCompany.company_id == company_id,
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        return row
    now = datetime.now(UTC)
    row = UserCompany(
        id=uuid4(),
        user_id=user_id,
        company_id=company_id,
        is_primary=is_primary,
        status="ACTIVE",
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.flush()
    return row


async def _ensure_user_role(session: AsyncSession, user_company_id: UUID, role_id: UUID) -> None:
    exists = (
        await session.execute(
            select(UserRole).where(
                UserRole.user_company_id == user_company_id,
                UserRole.role_id == role_id,
            )
        )
    ).scalar_one_or_none()
    if exists is None:
        session.add(UserRole(id=uuid4(), user_company_id=user_company_id, role_id=role_id))


async def _ensure_user(
    session: AsyncSession,
    *,
    user_id: UUID,
    email: str,
    password: str,
    now: datetime,
) -> None:
    row = await session.get(User, user_id)
    if row is not None:
        return
    session.add(
        User(
            id=user_id,
            email=email,
            password_hash=hash_password(password),
            status="ACTIVE",
            created_at=now,
            updated_at=now,
        )
    )
