"""Per-status onboarding case counts (`GET /v1/onboarding-cases/status-counts`) for the tab strip
on the onboarding list. Read-only; a status with no cases is simply absent."""

from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class OnboardingStatusCounts(BaseModel):
    total: int
    by_status: dict[str, int]


async def onboarding_status_counts(
    session: AsyncSession, company_id: UUID
) -> OnboardingStatusCounts:
    rows = (
        await session.execute(
            text(
                "SELECT status, count(*) AS n FROM onboarding_case "
                "WHERE company_id = :cid GROUP BY status"
            ),
            {"cid": company_id},
        )
    ).all()
    by_status = {r.status: int(r.n) for r in rows}
    return OnboardingStatusCounts(total=sum(by_status.values()), by_status=by_status)
