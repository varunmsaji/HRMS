"""Names of the role HR offered, for the candidate's welcome screen (read-only)."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.modules.onboarding.schemas import PublicRoleSummary


async def public_role_summary(
    session: AsyncSession, company_id: UUID, case_id: UUID
) -> PublicRoleSummary:
    row = (
        await session.execute(
            text(
                """
                SELECT c.name AS company_name, dg.title AS designation,
                       d.name AS department, b.name AS branch
                FROM onboarding_case oc
                JOIN company c ON c.id = oc.company_id
                LEFT JOIN designation dg ON dg.id = oc.designation_id
                LEFT JOIN department d ON d.id = oc.department_id
                LEFT JOIN branch b ON b.id = oc.branch_id
                WHERE oc.id = :case AND oc.company_id = :cid
                """
            ),
            {"case": case_id, "cid": company_id},
        )
    ).first()
    if row is None:
        return PublicRoleSummary()
    return PublicRoleSummary(
        company_name=row.company_name,
        designation=row.designation,
        department=row.department,
        branch=row.branch,
    )
